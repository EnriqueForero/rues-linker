"""engine.lsh.vectorized_minhash — generación de firmas MinHash vectorizada.

Nuevo en v2.3.0. Reemplaza el cuello de botella de ``DiskBasedLSHEngine``:
hasta v2.2.0 las firmas se generaban creando un objeto ``datasketch.MinHash``
por registro y llamando ``.update()`` n-grama por n-grama en un bucle Python.
Sobre 1.9M registros eso es ~1.9M objetos + decenas de millones de llamadas,
y consumía ~60 % del tiempo total del motor.

Esta implementación calcula las firmas por lotes con NumPy usando el mismo
esquema de hashing universal que datasketch (familia lineal
``h_i(x) = (a_i * x + b_i) mod p`` sobre enteros de 64 bits, con ``p`` el primo
de Mersenne 2^61−1 que usa datasketch). Las firmas resultantes son válidas para
LSH: dos textos similares comparten un mínimo por permutación con la misma
probabilidad ≈ Jaccard, igual que datasketch.

Determinismo: las permutaciones se derivan de una semilla fija (``seed=42``),
así que dos ejecuciones —o dos procesos distintos tras un reinicio de Colab—
producen firmas idénticas. Esto es necesario para que el checkpointing del
índice sea correcto (ver MIGRATION_LOG §13).

Author: Auditoría v2.3.0  Date: 2026-05-21  Version: 2.3.0
"""

from __future__ import annotations

import numpy as np

# Primo de Mersenne 2^61 - 1, el mismo que usa datasketch para el hashing.
_MERSENNE_PRIME = (1 << 61) - 1
_MAX_HASH = (1 << 32) - 1
_HASH_RANGE = 1 << 32


class VectorizedMinHasher:
    """Genera firmas MinHash de un lote de textos de forma vectorizada.

    Las firmas son compatibles en semántica con ``datasketch.MinHash`` (misma
    familia de hash, mismo primo), por lo que sirven para bandas LSH idénticas.

    Args:
        num_perm: Número de permutaciones (longitud de la firma).
        ngram: Tamaño del n-grama de caracteres.
        seed: Semilla para las permutaciones. Fija por defecto (determinismo).
    """

    def __init__(self, num_perm: int = 128, ngram: int = 3, seed: int = 42) -> None:
        self.num_perm = int(num_perm)
        self.ngram = int(ngram)
        self.seed = int(seed)
        rng = np.random.RandomState(self.seed)
        # Coeficientes de la familia de hash lineal, igual que datasketch:
        # a en [1, p-1], b en [0, p-1].
        self._a = rng.randint(1, _MERSENNE_PRIME, size=self.num_perm, dtype=np.uint64)
        self._b = rng.randint(0, _MERSENNE_PRIME, size=self.num_perm, dtype=np.uint64)

    def _ngram_hashes(self, text: str) -> np.ndarray:
        """Devuelve los hashes base (uint32) de los n-gramas de un texto.

        Usa el mismo hash base que datasketch: sha1 truncado a 32 bits, vía el
        hash incorporado de Python sobre los bytes. Para vectorizar evitamos
        sha1 y usamos un hash polinómico estable de 32 bits sobre los bytes del
        n-grama (determinista entre procesos, a diferencia de ``hash()``).
        """
        n = len(text)
        if n < self.ngram:
            return np.empty(0, dtype=np.uint64)
        # Hash polinómico rolling estable de 32 bits por n-grama de caracteres.
        # Trabajamos sobre el string (caracteres), no bytes, para respetar ngram.
        grams = [text[i : i + self.ngram] for i in range(n - self.ngram + 1)]
        out = np.fromiter(
            (_stable_hash32(g) for g in grams),
            dtype=np.uint64,
            count=len(grams),
        )
        return out

    def signature(self, text: str, max_val: int | None = None) -> np.ndarray:
        """Firma MinHash de un solo texto (uint64, longitud num_perm).

        Si el texto es más corto que un n-grama, devuelve la firma de "vacío"
        (todos los valores al máximo), igual que el motor original.
        """
        fill = _MAX_HASH if max_val is None else int(max_val)
        base = self._ngram_hashes(text)
        if base.size == 0:
            return np.full(self.num_perm, fill, dtype=np.uint64)
        # Permutaciones: (a * x + b) mod p, luego mod 2^32, mínimo por columna.
        # base: (k,) ; a,b: (num_perm,) -> phv: (k, num_perm)
        phv = (np.outer(base, self._a) + self._b) % _MERSENNE_PRIME
        phv &= _MAX_HASH
        return phv.min(axis=0).astype(np.uint64)

    def signatures_batch(self, texts: np.ndarray) -> np.ndarray:
        """Firmas de un lote de textos. Devuelve array (len(texts), num_perm).

        Vectorizado por texto: el cálculo de mínimos sobre las permutaciones es
        operación NumPy. El único bucle Python es sobre los textos del lote
        (inevitable porque cada texto tiene distinto número de n-gramas), pero
        sin crear objetos MinHash ni llamadas .update() por n-grama.
        """
        m = len(texts)
        out = np.empty((m, self.num_perm), dtype=np.uint64)
        for i in range(m):
            t = texts[i]
            if not isinstance(t, str):
                t = "" if t is None or (isinstance(t, float) and np.isnan(t)) else str(t)
            out[i] = self.signature(t)
        return out


def _stable_hash32(s: str) -> int:
    """Hash determinista de 32 bits de un string (estable entre procesos).

    A diferencia de ``hash()`` de Python (randomizado por PYTHONHASHSEED), este
    hash es reproducible, requisito para que el índice LSH sea consistente tras
    reinicios de sesión. Hash polinómico tipo Java sobre los bytes UTF-8.
    """
    h = 2166136261
    for byte in s.encode("utf-8", errors="ignore"):
        h ^= byte
        h = (h * 16777619) & _MAX_HASH
    return int(h)
