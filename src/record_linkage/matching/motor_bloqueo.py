"""matching.bloqueo — bloqueo componible por tipo con medición PC/RR (F2.5).

Cada estrategia genera pares candidatos (índices posicionales ``i < j``); la
unión de estrategias es el conjunto candidato del motor. ``medir`` calcula,
contra un ground truth, la completitud de pares (PC) y la razón de reducción
(RR) por estrategia individual y combinada — el eje de recall del playbook
se gobierna aquí (R ≈ PC × R_match).

Estrategias:
    - ``LlaveExacta``: identificadores/teléfonos/emails normalizados.
    - ``LSHTexto``: MinHash-LSH de shingles de caracteres para nombres.
    - ``VecindarioOrdenado``: sorted-neighborhood para fecha/numérico.
    - ``RejillaGeo``: celdas geográficas con vecindad 3×3 (geohash-grid).
"""

from __future__ import annotations

from itertools import combinations
from typing import Protocol, runtime_checkable

import numpy as np
import pandas as pd


@runtime_checkable
class EstrategiaBloqueo(Protocol):
    """Protocolo de una estrategia de bloqueo."""

    nombre: str

    def pares(self, valores: dict[str, np.ndarray]) -> np.ndarray:
        """Pares candidatos como array ``(m, 2)`` int64 con ``i < j``.

        Args:
            valores: columnas normalizadas por nombre de campo ('' = faltante;
                GEO entrega array ``(n, 2)`` float con NaN = faltante).
        """
        ...


def _canonizar(pares: list[tuple[int, int]]) -> np.ndarray:
    """Lista de pares → array (m,2) único con i<j; vacío → (0,2)."""
    if not pares:
        return np.empty((0, 2), dtype=np.int64)
    arr = np.asarray(pares, dtype=np.int64)
    arr = np.sort(arr, axis=1)
    return np.unique(arr, axis=0)


def _pares_grupo(indices: np.ndarray) -> list[tuple[int, int]]:
    return list(combinations(indices.tolist(), 2))


class LlaveExacta:
    """Pares dentro de cada valor idéntico no-faltante de una columna.

    Args:
        campo: nombre del campo (clave en ``valores``).
        max_grupo: tope de tamaño de grupo; grupos mayores se OMITEN y se
            registran en ``grupos_omitidos`` (una llave degenerada — p. ej.
            un placeholder que escapó — no debe producir O(n²) pares).
    """

    def __init__(self, campo: str, *, max_grupo: int = 2000) -> None:
        self.campo = campo
        self.max_grupo = int(max_grupo)
        self.nombre = f"llave_exacta[{campo}]"
        self.grupos_omitidos: list[tuple[str, int]] = []

    def pares(self, valores: dict[str, np.ndarray]) -> np.ndarray:
        v = pd.Series(valores[self.campo])
        self.grupos_omitidos = []
        pares: list[tuple[int, int]] = []
        for clave, idx in v[v != ""].groupby(v[v != ""]).groups.items():
            ind = np.asarray(idx, dtype=np.int64)
            if len(ind) < 2:
                continue
            if len(ind) > self.max_grupo:
                self.grupos_omitidos.append((str(clave), len(ind)))
                continue
            pares.extend(_pares_grupo(ind))
        return _canonizar(pares)


class LSHTexto:
    """MinHash-LSH sobre shingles de caracteres (nombres y texto largo).

    Determinista: la semilla de MinHash es fija (seed=1, convención
    datasketch) y el orden de inserción es el posicional del DataFrame.
    """

    def __init__(
        self,
        campo: str,
        *,
        umbral: float = 0.4,
        permutaciones: int = 64,
        ngram: int = 3,
    ) -> None:
        if not (0.0 < umbral < 1.0):
            raise ValueError(f"umbral={umbral} fuera de (0, 1).")
        self.campo = campo
        self.umbral = float(umbral)
        self.permutaciones = int(permutaciones)
        self.ngram = int(ngram)
        self.nombre = f"lsh_texto[{campo}]"

    def _shingles(self, texto: str) -> set[bytes]:
        t = f" {texto} "
        k = self.ngram
        return {t[i : i + k].encode("utf-8") for i in range(len(t) - k + 1)}

    def pares(self, valores: dict[str, np.ndarray]) -> np.ndarray:
        from datasketch import MinHash, MinHashLSH

        v = valores[self.campo]
        lsh = MinHashLSH(threshold=self.umbral, num_perm=self.permutaciones)
        firmas: dict[int, MinHash] = {}
        for i, texto in enumerate(v):
            if not texto:
                continue
            mh = MinHash(num_perm=self.permutaciones)
            for sh in self._shingles(str(texto)):
                mh.update(sh)
            firmas[i] = mh
            lsh.insert(str(i), mh)
        pares: list[tuple[int, int]] = []
        for i, mh in firmas.items():
            for j_str in lsh.query(mh):
                j = int(j_str)
                if j > i:
                    pares.append((i, j))
        return _canonizar(pares)


class VecindarioOrdenado:
    """Sorted-neighborhood: pares a distancia ≤ ventana en el orden del campo."""

    def __init__(self, campo: str, *, ventana: int = 3) -> None:
        if ventana < 1:
            raise ValueError(f"ventana={ventana} debe ser >= 1.")
        self.campo = campo
        self.ventana = int(ventana)
        self.nombre = f"vecindario[{campo}]"

    def pares(self, valores: dict[str, np.ndarray]) -> np.ndarray:
        v = pd.Series(valores[self.campo])
        validos = np.flatnonzero((v != "").to_numpy())
        if len(validos) < 2:
            return _canonizar([])
        orden = validos[np.argsort(v.iloc[validos].to_numpy(), kind="stable")]
        pares: list[tuple[int, int]] = []
        for d in range(1, self.ventana + 1):
            pares.extend(zip(orden[:-d].tolist(), orden[d:].tolist(), strict=False))
        return _canonizar(pares)


class RejillaGeo:
    """Celdas geográficas de ~``celda_km`` con vecindad 3×3 (geohash-grid).

    ``campo`` debe entregar un array ``(n, 2)`` float [lat, lon] (NaN =
    faltante). Garantiza candidato para todo par a distancia ≤ celda_km.
    """

    _KM_POR_GRADO = 111.32

    def __init__(self, campo: str, *, celda_km: float = 1.0) -> None:
        if celda_km <= 0:
            raise ValueError(f"celda_km={celda_km} debe ser > 0.")
        self.campo = campo
        self.celda_km = float(celda_km)
        self.nombre = f"rejilla_geo[{campo}]"

    def pares(self, valores: dict[str, np.ndarray]) -> np.ndarray:
        xy = np.asarray(valores[self.campo], dtype=np.float64)
        ok = ~np.isnan(xy).any(axis=1)
        idx = np.flatnonzero(ok)
        if len(idx) < 2:
            return _canonizar([])
        dlat = self.celda_km / self._KM_POR_GRADO
        lat_media = float(np.nanmean(xy[idx, 0]))
        dlon = self.celda_km / (self._KM_POR_GRADO * max(0.1, abs(np.cos(np.radians(lat_media)))))
        celdas: dict[tuple[int, int], list[int]] = {}
        for i in idx.tolist():
            c = (int(np.floor(xy[i, 0] / dlat)), int(np.floor(xy[i, 1] / dlon)))
            celdas.setdefault(c, []).append(i)
        pares: list[tuple[int, int]] = []
        for (cx, cy), miembros in celdas.items():
            pares.extend(_pares_grupo(np.asarray(miembros)))
            for ox, oy in ((0, 1), (1, -1), (1, 0), (1, 1)):  # 4 vecinos canónicos
                vecinos = celdas.get((cx + ox, cy + oy))
                if vecinos:
                    pares.extend((a, b) for a in miembros for b in vecinos)
        return _canonizar(pares)


class BloqueoComponible:
    """Unión de estrategias (F2.5) con medición PC/RR por estrategia."""

    def __init__(self, estrategias: list[EstrategiaBloqueo]) -> None:
        if not estrategias:
            raise ValueError("BloqueoComponible requiere al menos una estrategia.")
        self.estrategias = list(estrategias)

    def pares(self, valores: dict[str, np.ndarray]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        """Unión canónica y pares por estrategia (para auditoría/medición)."""
        por_estrategia = {e.nombre: e.pares(valores) for e in self.estrategias}
        todos = [p for p in por_estrategia.values() if len(p)]
        if not todos:
            return np.empty((0, 2), dtype=np.int64), por_estrategia
        union = np.unique(np.vstack(todos), axis=0)
        return union, por_estrategia

    @staticmethod
    def medir(
        por_estrategia: dict[str, np.ndarray],
        union: np.ndarray,
        id_true: np.ndarray,
    ) -> dict[str, dict[str, float]]:
        """PC y RR contra un ground truth (columna de identidad verdadera).

        PC = fracción de pares verdaderos capturados; RR = 1 − candidatos /
        C(n, 2). Se reporta por estrategia y para la unión ("combinada").
        """
        n = len(id_true)
        s = pd.Series(id_true)
        verdaderos: set[tuple[int, int]] = set()
        for _, idx in s.groupby(s).groups.items():
            verdaderos.update(_pares_grupo(np.asarray(idx, dtype=np.int64)))
        total_posibles = n * (n - 1) / 2.0
        salida: dict[str, dict[str, float]] = {}

        def _metricas(pares_arr: np.ndarray) -> dict[str, float]:
            cand = {(int(a), int(b)) for a, b in pares_arr}
            pc = (len(cand & verdaderos) / len(verdaderos)) if verdaderos else 1.0
            rr = 1.0 - (len(cand) / total_posibles if total_posibles else 0.0)
            return {
                "pc": round(pc, 6),
                "rr": round(rr, 6),
                "n_pares": float(len(cand)),
            }

        for nombre, arr in por_estrategia.items():
            salida[nombre] = _metricas(arr)
        salida["combinada"] = _metricas(union)
        return salida
