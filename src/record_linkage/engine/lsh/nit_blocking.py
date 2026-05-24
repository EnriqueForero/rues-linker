"""engine.lsh.nit_blocking — Bloqueo de candidatos por NIT base.

Contexto: Google Colab Free (~12 GB RAM, 2–4 M registros).

El bloqueo LSH por n-gramas de NOMBRE_LIMPIO captura solo pares cuyos nombres
comparten n-gramas. Pero existen pares verdaderos donde **solo el NIT puede
unirlos** porque los nombres no comparten tokens:

    - "EY COLOMBIA"      ↔ "ERNST & YOUNG EN LIQUIDACION"  (mismo NIT)
    - "ACCENTURE SL"     ↔ "DISTRIBUIDORA ANDERSEN CONSULTING"
    - "PINTUCO GRUPO ORBIS" ↔ "AKZONOBEL PINTUCO"

En el ground truth exhaustivo (1456 regs), el 25 % de pares verdaderos
comparte NIT base exacto, y el 61 % comparte NIT base a distancia
Levenshtein ≤ 1. Este módulo genera esos pares de forma vectorizada y los
fusiona con los del LSH antes del scoring, atacando directamente la causa
raíz del cuello de recall (P0-1 del ROADMAP).

Estrategia (vectorizada, RAM-segura):
    1. Bloquear por NIT base exacto: `groupby('NIT_BASE')` y emitir pares
       intra-grupo solo si el grupo tiene ≥ 2 registros y ≤ `max_bucket_size`
       (cota dura contra explosión cuadrática). NITs vacíos se descartan.
    2. (Opcional) Bloquear por NIT base a distancia ≤ 1: cada NIT se conecta
       con los NITs que difieren en exactamente un dígito (sustitución,
       inserción o borrado de un dígito al final). Esto captura los típicos
       errores del RUES: dígito de verificación distinto, transposición o
       dígito extra. Implementado generando "vecinos" canónicos sin
       comparación O(n²).

Output: set de tuplas `(idx_0, idx_1)` con `idx_0 < idx_1`, listo para
fusionar con los candidatos del LSH.

Author: Claude (auditor)  Date: 2026-05-22  Version: 2.5.0
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NitBlockingConfig:
    """Parámetros del bloqueo por NIT base.

    Attributes:
        enable_exact: Activa el bloqueo por NIT base exacto. Default True.
        enable_neighbors: Activa el bloqueo por NITs a distancia 1
            (sustitución/inserción/borrado de un dígito). Default True.
            Aumenta el recall a costa de más pares candidatos.
        max_bucket_size: Tamaño máximo de bucket emitido. Si un NIT tiene
            más registros que esto, se descarta para evitar explosión
            cuadrática (un NIT con 1000 registros genera ~500k pares).
            Default 200.
        min_nit_length: Longitud mínima del NIT base para considerarlo.
            Default 6 (corta NITs claramente truncados).
        min_name_similarity: Filtro post-bloqueo. Si > 0 y la columna
            ``name_column`` está disponible, descarta pares cuyo
            ``token_set_ratio`` entre nombres está por debajo de este
            valor (0..1). Vectorizado con rapidfuzz. Default 0.0 (sin
            filtro). Recomendado 0.30 según calibración v2.7.0.
        name_column: Nombre de la columna con la razón social para el
            filtro ``min_name_similarity``. Solo se usa si dicho filtro
            está activo. Default ``"RAZON_SOCIAL"``.
    """

    enable_exact: bool = True
    enable_neighbors: bool = True
    max_bucket_size: int = 200
    min_nit_length: int = 6
    min_name_similarity: float = 0.0
    name_column: str = "RAZON_SOCIAL"

    def __post_init__(self) -> None:
        if self.max_bucket_size < 2:
            raise ValueError(f"max_bucket_size={self.max_bucket_size} debe ser ≥ 2")
        if self.min_nit_length < 1:
            raise ValueError(f"min_nit_length={self.min_nit_length} debe ser ≥ 1")
        if not (0.0 <= self.min_name_similarity <= 1.0):
            raise ValueError(f"min_name_similarity={self.min_name_similarity} debe estar en [0, 1]")


def _pairs_from_indices(indices: list[int]) -> Iterable[tuple[int, int]]:
    """Genera pares (i, j) con i < j desde una lista de índices."""
    return combinations(sorted(indices), 2)


def _generate_one_digit_neighbors(nit: str) -> set[str]:
    """Genera vecinos canónicos a distancia de edición 1 sobre un NIT.

    Esto evita una comparación O(n²) entre NITs: si dos NITs están a
    distancia ≤ 1, ambos comparten al menos un vecino canónico. Para cada
    NIT emitimos sus vecinos; dos NITs que comparten al menos un vecino
    están a distancia ≤ 1.

    Esquema:
        - Sustitución (mismo length): se emite el NIT con el dígito en `i`
          reemplazado por "*". Dos NITs de igual longitud que difieren en un
          dígito comparten ese patrón.
        - Inserción / borrado (length difiere en 1): el NIT más corto se
          emite tal cual con el prefijo "=" (longitud = len(nit)), y el
          más largo emite cada uno de sus borrados con el prefijo "=" de
          longitud len(nit)−1. Si alguna posición del NIT largo, una vez
          borrada, coincide con el corto, ambos comparten esa clave "=".

    Args:
        nit: NIT base (solo dígitos).

    Returns:
        Conjunto de "vecinos canónicos" del NIT que se usarán como buckets.
    """
    neighbors: set[str] = set()
    n = len(nit)
    # Sustituciones: posición i con '*' (mismo length).
    for i in range(n):
        neighbors.add("*" + nit[:i] + "_" + nit[i + 1 :])
    # Borrados: posición i eliminada (compara con NITs de longitud n−1).
    # El prefijo "=L" indica "este NIT canonicalizado a longitud L".
    for i in range(n):
        # Borrado: contribuye a buckets de longitud n−1.
        neighbors.add(f"=L{n - 1}:" + nit[:i] + nit[i + 1 :])
    # Identidad: el propio NIT como bucket de su longitud, para que NITs
    # más largos puedan caer en este bucket vía su borrado.
    neighbors.add(f"=L{n}:" + nit)
    return neighbors


def block_by_nit_base(
    df: pd.DataFrame,
    nit_column: str = "NIT_BASE",
    config: NitBlockingConfig | None = None,
) -> set[tuple[int, int]]:
    """Genera pares candidatos por bloqueo de NIT base.

    El bloqueo es complementario al LSH por nombre: produce pares que el LSH
    no puede capturar porque los nombres no comparten n-gramas. Vectorizado
    con `groupby` y operaciones sobre arrays, sin bucles por fila.

    Args:
        df: DataFrame con índice posicional (0..n-1) y la columna `nit_column`.
            Debe ser el mismo índice que se usa para los pares LSH (`_idx` o
            la posición de fila).
        nit_column: Nombre de la columna con el NIT base canonicalizado.
        config: Configuración del bloqueo. Si es None, se usa el default.

    Returns:
        Conjunto de pares `(idx_0, idx_1)` con `idx_0 < idx_1` candidatos
        para scoring.

    Raises:
        ValueError: Si la columna NIT no existe o el DataFrame está vacío.
    """
    if config is None:
        config = NitBlockingConfig()

    if df.empty:
        return set()
    if nit_column not in df.columns:
        raise ValueError(
            f"Columna '{nit_column}' no encontrada en DataFrame "
            f"(columnas disponibles: {list(df.columns)})"
        )

    # 1. Normalizar la columna NIT: string, sin nulos, solo dígitos.
    nit_series = df[nit_column].astype(str).str.strip()
    # Filtrar nulos, "nan", "" y NITs cortos.
    valid_mask = (
        (nit_series != "")
        & (nit_series.str.lower() != "nan")
        & (nit_series.str.len() >= config.min_nit_length)
    )
    n_total = len(df)
    n_valid = int(valid_mask.sum())
    if n_valid == 0:
        logger.info("[nit_blocking] Ningún NIT válido para bloquear (todos vacíos o cortos).")
        return set()

    # Trabajar solo con índices posicionales válidos. Usamos np.arange y la
    # máscara para garantizar índices 0..n-1 coherentes con el resto del
    # pipeline (NO el índice del DataFrame, que puede haberse reordenado).
    positional_idx = np.arange(n_total)[valid_mask.to_numpy()]
    nits_valid = nit_series.to_numpy()[valid_mask.to_numpy()]

    pairs: set[tuple[int, int]] = set()

    # 2. Bloqueo por NIT EXACTO (groupby vectorizado).
    if config.enable_exact:
        # Agrupar por NIT. groupby es O(n log n) en pandas pero internamente
        # usa C; no es un bucle Python sobre filas.
        nit_series_valid = pd.Series(nits_valid, index=positional_idx)
        groups = nit_series_valid.groupby(nit_series_valid.values).groups
        n_buckets_emitted = 0
        n_buckets_skipped = 0
        for nit_val, idx_array in groups.items():
            sz = len(idx_array)
            if sz < 2:
                continue
            if sz > config.max_bucket_size:
                n_buckets_skipped += 1
                logger.debug(
                    f"[nit_blocking] Bucket '{nit_val}' descartado: {sz} > "
                    f"max_bucket_size={config.max_bucket_size}"
                )
                continue
            n_buckets_emitted += 1
            indices_list = [int(x) for x in idx_array]
            pairs.update(_pairs_from_indices(indices_list))
        logger.info(
            f"[nit_blocking] Exacto: {n_buckets_emitted:,} buckets emitidos "
            f"({n_buckets_skipped} descartados por tamaño) → {len(pairs):,} pares"
        )

    # 3. Bloqueo por VECINOS (distancia ≤ 1, opcional).
    if config.enable_neighbors:
        # Construir un mapa neighbor_key -> [positional_idx, ...].
        # Cada NIT contribuye múltiples claves (sustituciones + borrados).
        # Pares: misma clave => NITs a distancia ≤ 1. Se descartan pares ya
        # añadidos por el bloqueo exacto.
        from collections import defaultdict

        neighbor_index: dict[str, list[int]] = defaultdict(list)
        for pos_idx, nit_val in zip(positional_idx, nits_valid, strict=True):
            # Generar vecinos canónicos. Solo NITs cortos (≤ 15 dígitos)
            # — los más largos son atípicos y dispararían el costo.
            if len(nit_val) > 15:
                continue
            for key in _generate_one_digit_neighbors(nit_val):
                neighbor_index[key].append(int(pos_idx))

        # Emitir pares por bucket de vecinos, con la misma cota max_bucket_size.
        pairs_before = len(pairs)
        n_neighbor_buckets = 0
        for _, idx_list in neighbor_index.items():
            sz = len(idx_list)
            if sz < 2 or sz > config.max_bucket_size:
                continue
            n_neighbor_buckets += 1
            pairs.update(_pairs_from_indices(idx_list))
        pairs_added = len(pairs) - pairs_before
        logger.info(
            f"[nit_blocking] Vecinos (dist≤1): {n_neighbor_buckets:,} buckets "
            f"→ +{pairs_added:,} pares nuevos"
        )

    logger.info(f"[nit_blocking] Total pares por bloqueo de NIT: {len(pairs):,}")

    # ── FILTRO POST-BLOQUEO: name_sim ≥ min_name_similarity ─────────────
    # v2.7.0 (P2 Camino #2 — re-pesado por origen del par): descarta pares
    # del bloqueo NIT cuyos nombres son muy distintos. Esto sube la
    # precision del bloqueo NIT sin tocar el scorer downstream, atacando
    # exactamente los casos negativos diseñados del ground truth
    # (NITs adyacentes con nombres totalmente distintos como
    # 800999001/TRANSPORTES SUR ↔ 800999002/INDUSTRIAS NORTE).
    if config.min_name_similarity > 0.0 and pairs:
        if config.name_column not in df.columns:
            logger.warning(
                f"[nit_blocking] min_name_similarity={config.min_name_similarity} "
                f"pero columna '{config.name_column}' no existe; se omite el filtro."
            )
        else:
            try:
                from rapidfuzz import fuzz
            except ImportError:
                logger.warning(
                    "[nit_blocking] rapidfuzz no disponible; se omite el filtro de name_sim."
                )
            else:
                names = df[config.name_column].astype(str).str.upper().to_numpy()
                pairs_list = list(pairs)
                n_before = len(pairs_list)
                # Calcular token_set_ratio vectorizadamente.
                # rapidfuzz no tiene una API vectorizada cross-pair sin matriz,
                # pero process_arrays_cdist es overkill aquí. Para n pares
                # con n grande (hasta ~1M en producción) la iteración Python
                # sobre rapidfuzz es aceptable: ~500k ops/s en CPython.
                thr_pct = config.min_name_similarity * 100.0
                pairs_kept: list[tuple[int, int]] = []
                for a, b in pairs_list:
                    if fuzz.token_set_ratio(names[a], names[b]) >= thr_pct:
                        pairs_kept.append((a, b))
                pairs = set(pairs_kept)
                n_dropped = n_before - len(pairs)
                logger.info(
                    f"[nit_blocking] Filtro name_sim ≥ {config.min_name_similarity}: "
                    f"{n_before:,} → {len(pairs):,} (−{n_dropped:,} pares)"
                )

    return pairs
