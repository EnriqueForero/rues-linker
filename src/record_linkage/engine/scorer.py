"""
engine.scorer — record_linkage_pipeline

Componentes:
    - class PairScorer  (origen: notebook celda [118])
    - class VectorizedScorer  (origen: notebook celda [121])

NOTA: Lógica de negocio preservada exactamente como en el notebook
fuente. Solo se agregan imports, docstring de módulo y se eliminan
directivas de Jupyter (%%time, !pip, etc.). Ver MIGRATION_LOG.md.
"""

from __future__ import annotations

import gc
import logging
import os
import sqlite3
import time
from typing import (
    Any,
    ClassVar,
    Protocol,
    runtime_checkable,
)

import numpy as np
import pandas as pd
import psutil
from rapidfuzz import fuzz
from tqdm import tqdm

from ..utils.logger import CustomLogger
from ..utils.memory import (
    MemoryManager,
)
from ..utils.performance import (
    track_performance,
)
from .similarity import BasicSimilarityCalculator, SimilarityCalculator


@runtime_checkable
class PairScorer(Protocol):
    """Protocolo para calcular scores de pares."""

    def score_pairs(self, candidates: set[tuple[int, int]], df: pd.DataFrame) -> pd.DataFrame: ...


class VectorizedScorer:
    def __init__(self, profile: dict[str, Any], config: dict[str, Any] | None = None):
        """
        Constructor REFORZADO que lee los parámetros de forma directa y explícita,
        eliminando fallbacks ambiguos para garantizar que siempre se usen los valores
        de la configuración proporcionada.
        """
        self.profile = profile
        self.config = config or {}
        self.logger = CustomLogger("VectorizedScorer")

        # --- LÓGICA DE LECTURA DE PARÁMETROS CORREGIDA Y DIRECTA ---

        # 1. Pesos de Scoring
        # Se asegura de que los pesos existan y los normaliza.
        self.weights = self.profile.get("weights", {"name": 0.70, "nit": 0.25, "phonetic": 0.05})
        total_weight = sum(self.weights.values())
        if total_weight > 0:
            self.weights = {k: v / total_weight for k, v in self.weights.items()}

        # 2. Umbrales y Filtros (Lectura Directa)
        # Lee directamente del perfil. Si un parámetro no está, dará un error,
        # lo cual es BUENO porque nos fuerza a definir siempre la configuración completa.
        try:
            self.score_threshold = float(self.profile["score_threshold"])
            self.max_nit_distance = int(self.profile["max_nit_distance"])
            self.min_name_similarity = float(self.profile["min_name_similarity"])
        except KeyError as e:
            raise KeyError(
                f"Parámetro de scoring requerido no encontrado en el perfil: {e}. "
                f"Asegúrate de que 'score_threshold', 'max_nit_distance', y "
                f"'min_name_similarity' estén definidos en tu `optimal_params`."
            )

        self.batch_size = int(self.profile.get("scoring_batch_size", 50_000))

        # ── v3.2.4 (FIX FASE 1): COMPORTAMIENTO DE NIT VACÍO EN FILTRO ───────
        # `nit_empty_passes_filter` (bool, default True para retrocompatibilidad):
        #     Hasta v3.2.3 inclusive, los pares con NIT vacío en algún lado
        #     reciben `nit_distance == -1` (sentinela). Como `-1 <= max_nit_distance`
        #     para cualquier max_nit_distance ≥ 0, esos pares PASABAN el filtro NIT
        #     sin evidencia, propagándose al scoring solo con similitud de nombre.
        #     Esto genera FP masivos en regímenes SIN_NIT (importadores extranjeros,
        #     personas naturales sin RUT). v3.2.4 introduce el flag para permitir
        #     que el filtro requiera evidencia explícita de NIT. Default True
        #     conserva el comportamiento heredado; recomendado False para
        #     pipelines calibrados contra ground truth.
        self.nit_empty_passes_filter = bool(self.profile.get("nit_empty_passes_filter", True))

        # ── v2.8.0 (P0-1): TRATAMIENTO PRIVILEGIADO DE NIT IDÉNTICO ────────
        # Diagnóstico documentado en MIGRATION_LOG §18. Ver §21 (v2.10.0)
        # para la diferenciación declared/computed agregada en Fix #1.
        #
        # Tres perillas:
        #
        # `nit_identical_overrides_name_filter` (bool, default False):
        #     Si True, pares con `nit_distance == 0` (NIT_OK idéntico
        #     no-vacío) saltan el filtro de nombre. Sin esta, el par ni
        #     siquiera llega al cálculo de score combinado.
        #
        # `nit_identical_score_boost` (float, default 0.0):
        #     Bonus aditivo al score final cuando NIT_OK idéntico — APLICA
        #     SOLO si al menos un lado tiene DV calculado (evidencia
        #     intermedia). Si AMBOS lados tienen DV declarado, se usa el
        #     boost diferenciado de abajo. Default 0.0 = paridad v2.7.0.
        #
        # `nit_identical_score_boost_declared` (float, default None):
        #     v2.10.0 (Fix #1): boost MAYOR cuando AMBOS lados del par
        #     vienen con DV declarado en origen — la evidencia más fuerte
        #     posible (dos fuentes independientes coincidieron en NIT+DV
        #     que probablemente no se inventaron). Esto recupera los FN
        #     de tipo P1 (sigla vs nombre) y P4 (token disímil) donde el
        #     nombre es muy disímil pero el NIT es identidad fuerte.
        #     Default None → fallback a `nit_identical_score_boost`
        #     (preservación de comportamiento v2.8.0/v2.9.0).
        #
        #     Requiere que el DataFrame de scoring tenga la columna
        #     `DV_ORIGEN` poblada por `AdvancedNitProcessor` v2.10.0+.
        #     Si la columna no existe, todos los pares se tratan como
        #     `computed` (conservador) y este boost no se aplica.
        self.nit_identical_overrides_name_filter: bool = bool(
            self.profile.get("nit_identical_overrides_name_filter", False)
        )
        self.nit_identical_score_boost: float = float(
            self.profile.get("nit_identical_score_boost", 0.0)
        )
        _boost_declared = self.profile.get("nit_identical_score_boost_declared", None)
        self.nit_identical_score_boost_declared: float | None = (
            float(_boost_declared) if _boost_declared is not None else None
        )

        # ── v2.10.0 (Fix #2): PENALIZACIÓN POR NOMBRE GENÉRICO ───────────
        # Si el nombre completo está compuesto SOLO por tokens del top-N
        # del corpus (palabras genéricas como INVERSIONES, GRUPO, SAS,
        # CONSULTORES, COLOMBIA), un name_sim alto NO es evidencia fuerte
        # de identidad común — pueden ser entidades genuinamente distintas
        # cuya razón social coincide accidentalmente.
        #
        # La penalización multiplica el name_sim por (1 - penalty) cuando
        # ambos nombres del par son "totalmente genéricos". Esto baja el
        # score combinado lo suficiente para que el threshold lo descarte
        # SI el NIT no es idéntico. Si el NIT ES idéntico, el boost de
        # Fix #1 sigue aplicando (las dos perillas son ortogonales).
        #
        # `generic_name_penalty` (float, default 0.0):
        #     Magnitud de la penalización. 0.0 = no-op (paridad v2.9.0).
        #     0.5 = el name_sim de un par "ambos genéricos" se reduce a la
        #     mitad. Calibrado a 0.5 sobre dataset sintético; recalibrar
        #     con producción real.
        #
        # `generic_name_top_n` (int, default 30):
        #     Cuántas palabras del corpus se consideran "genéricas". El
        #     scorer NO calcula esto — espera recibir el set vía perfil:
        #     `profile["_generic_tokens"]` (set de strings). El caller
        #     debe poblarlo desde el corpus antes de invocar el scorer.
        #     Si no está poblado, esta penalización es no-op.
        self.generic_name_penalty: float = float(self.profile.get("generic_name_penalty", 0.0))
        self.generic_tokens: set[str] = set(self.profile.get("_generic_tokens", set()))

        # ── v2.12.0 (Fix #3): RE-SCORING POR IDF DE TOKENS ───────────────
        # Problema (caso Corea sin NIT): el token_set_ratio infla la
        # similitud cuando dos nombres comparten tokens de ALTA frecuencia
        # ("ELITE EXPORTS INTERNATIONAL INC Y/O X" vs "...Y/O Z" → 93%, o
        # "SECUI CORPORATION" vs "MULTIFLORA CORPORATION" → 79% por
        # "CORPORATION"). Esos tokens no discriminan identidad.
        #
        # Solución: ponderar cada token por su IDF sobre el corpus. La
        # similitud IDF de un par = (peso IDF de tokens compartidos) /
        # (peso IDF de la unión de tokens). Tokens frecuentes pesan ~0;
        # tokens raros (NENOVA, ARES3) dominan. El name_sim final se mezcla:
        #   name_sim = (1 - blend) * token_set_ratio + blend * idf_sim
        #
        # `idf_weight_blend=0.0` → no-op (paridad con v2.11.0). El mapa
        # token→IDF lo provee el caller vía `profile["_token_idf"]`; si no
        # está, Fix #3 es no-op.
        self.idf_weight_blend: float = float(self.profile.get("idf_weight_blend", 0.0))
        self.token_idf: dict[str, float] = dict(self.profile.get("_token_idf", {}))
        self.idf_default: float = float(self.profile.get("idf_default", 1.0))

        # ── v2.7.0 (P2 Camino #1): VARIABLES ADICIONALES ─────────────────
        # Soporta features extra opcionales (CIUDAD, TELEFONO, etc.) sin
        # romper el contrato existente. Si el perfil no define
        # `extra_features`, el scorer se comporta idéntico a v2.6.0.
        # Estructura esperada:
        #   profile["extra_features"] = [
        #       {"column": "CIUDAD",   "weight": 0.10, "type": "categorical"},
        #       {"column": "TELEFONO", "weight": 0.10, "type": "exact_or_zero"},
        #   ]
        # Tipos soportados:
        #   - "exact_or_zero": 1.0 si ambos valores existen y son iguales,
        #     0.0 en cualquier otro caso (incluye nulos). Útil para campos
        #     donde un match casual es muy informativo (teléfono, NIT
        #     contacto, identificadores únicos).
        #   - "categorical": 1.0 si ambos valores no-nulos son iguales
        #     (case-insensitive, sin espacios extras), 0.5 si uno es nulo
        #     (no penaliza la ausencia), 0.0 si distintos. Útil para
        #     atributos descriptivos (ciudad, departamento, sector).
        #   - "token_set_ratio": fuzzy 0..1 via rapidfuzz. Útil para
        #     direcciones u otros campos de texto libre.
        self.extra_features: list[dict] = list(self.profile.get("extra_features", []))
        if self.extra_features:
            total_extra = sum(float(f.get("weight", 0.0)) for f in self.extra_features)
            self.logger.info(
                f"  - Extra features: {len(self.extra_features)} "
                f"(suma de pesos = {total_extra:.3f})"
            )
            for f in self.extra_features:
                self.logger.info(
                    f"      · {f.get('column')!r} (peso={f.get('weight', 0.0):.3f}, "
                    f"tipo={f.get('type', 'exact_or_zero')!r})"
                )

        self.logger.info("VectorizedScorer inicializado con filtros ESTRICTOS:")
        self.logger.info(f"  - Score Threshold: {self.score_threshold}")
        self.logger.info(f"  - Max NIT Distance: {self.max_nit_distance}")
        self.logger.info(f"  - Min Name Similarity: {self.min_name_similarity}")

        # Componentes y caché (sin cambios)
        self.similarity_calc = None
        self._similarity_cache = {}
        self._cache_hits = 0
        self._cache_misses = 0

    @property
    def similarity_calculator(self):
        """Obtener calculador de similitud (lazy loading)."""
        if self.similarity_calc is None:
            # Importar y crear cuando se necesite.
            # v2.2.0: NO degradar en silencio. Si SimilarityCalculator falla,
            # el usuario DEBE enterarse: una corrida de 2M registros con el
            # calculador básico produce resultados silenciosamente peores.
            try:
                self.similarity_calc = SimilarityCalculator()
            except Exception as exc:
                self.logger.warning(
                    "SimilarityCalculator no disponible (%s: %s). "
                    "Degradando a BasicSimilarityCalculator — la calidad del "
                    "matching puede ser INFERIOR. Revisa la causa.",
                    type(exc).__name__,
                    exc,
                )
                self.similarity_calc = BasicSimilarityCalculator()
        return self.similarity_calc

    @track_performance("Scoring de pares")
    def score_pairs(
        self,
        candidates: set[tuple[int, int]] | str,
        df: pd.DataFrame,
        score_threshold: float | None = None,
    ) -> pd.DataFrame:
        """
        Calcular scores para pares candidatos.

        MODIFICADO: Ahora acepta un Set o una ruta a archivo SQLite

        Args:
            candidates: Set de pares o ruta a archivo SQLite
            df: DataFrame con datos
            score_threshold: Umbral de score

        Returns:
            DataFrame con columnas: idx_0, idx_1, score, name_sim, nit_dist
        """
        # ─── v0.7.1 (Sprint 0.8.1, Tarea 1.1): AUDITORÍA DE PARES OPT-IN ───
        # Hasta v0.7.0 los bloques "AUDITANDO PAR" se emitían SIEMPRE con
        # `print(...)` directo, contaminando stdout en cada chunk de scoring
        # (~50 bloques por corrida grande). Ahora son DEBUG en el logger y
        # default desactivado (max_prints=0). Para activar:
        #   1) en el profile:           profile["audit_pairs_count"] = 5
        #   2) por variable de entorno: RUES_LINKER_AUDIT_PAIRS=5
        # La env var pisa al profile (útil para corridas ad-hoc en Colab).
        _env_audit = os.environ.get("RUES_LINKER_AUDIT_PAIRS")
        if _env_audit is not None:
            try:
                _max_prints = max(0, int(_env_audit))
            except ValueError:
                _max_prints = 0
        else:
            _max_prints = int(self.profile.get("audit_pairs_count", 0))
        self._audit_counters = {
            "passes_printed": 0,
            "fails_printed": 0,
            "max_prints": _max_prints,
        }
        # Si el opt-in está activo, asegurar que el logger del scorer pueda emitir
        # DEBUG. CustomLogger por defecto crea loggers en nivel INFO con propagate=False,
        # así que sin este ajuste los mensajes de auditoría nunca se verían.
        if _max_prints > 0:
            self.logger.logger.setLevel(logging.DEBUG)
        # Detectar tipo de entrada
        if isinstance(candidates, str) and candidates.endswith(".db"):
            # Es una ruta a archivo SQLite
            return self.score_pairs_from_db(candidates, df, score_threshold)
        else:
            # Es un Set, usar implementación original
            return self._score_pairs_from_set(candidates, df, score_threshold)

    def _score_pairs_from_set(
        self,
        candidates: set[tuple[int, int]],
        df: pd.DataFrame,
        score_threshold: float | None = None,
    ) -> pd.DataFrame:
        """
        Implementación original de  def score_pairs para compatibilidad con Sets en memoria.
        Calcular scores para pares candidatos.

        Args:
            candidates: Conjunto de pares candidatos (idx1, idx2)
            df: DataFrame con datos
            score_threshold: Umbral de score (usa el del perfil si no se especifica)

        Returns:
            DataFrame con columnas: idx_0, idx_1, score, name_sim, nit_dist
        """
        if not candidates:
            return pd.DataFrame(columns=["idx_0", "idx_1", "score", "name_sim", "nit_dist"])

        threshold = score_threshold or self.score_threshold
        # Si no se especifica threshold, usar el de la configuración actual
        if score_threshold is None:
            # Intentar obtener threshold actualizado de la configuración
            updated_threshold = self.profile.get("score_threshold")
            if updated_threshold is not None:
                threshold = updated_threshold
                self.logger.info(f"Usando threshold actualizado de configuración: {threshold}")
        self.logger.info(
            f"Calculando scores para {len(candidates):,} pares candidatos "
            f"(threshold={threshold:.2f})"
        )

        # Convertir a array para procesamiento vectorizado
        candidates_array = np.array(list(candidates))
        n_candidates = len(candidates_array)

        # Procesar por batches para gestión de memoria
        all_results = []
        n_batches = (n_candidates + self.batch_size - 1) // self.batch_size

        with tqdm(total=n_candidates, desc="Calculando scores") as pbar:
            for batch_idx in range(n_batches):
                start_idx = batch_idx * self.batch_size
                end_idx = min((batch_idx + 1) * self.batch_size, n_candidates)

                # Procesar batch
                batch_candidates = candidates_array[start_idx:end_idx]

                # Paso 1.3: _score_batch_vectorized ya filtra por score_threshold
                # internamente (línea 8420). No re-filtrar aquí.
                batch_results = self._score_batch_vectorized(batch_candidates, df)

                if not batch_results.empty:
                    all_results.append(batch_results)

                pbar.update(len(batch_candidates))

                # Monitorear memoria
                if batch_idx % 5 == 0:
                    MemoryManager.monitor_and_warn(self.logger)

        # Combinar resultados
        if all_results:
            scored_pairs = pd.concat(all_results, ignore_index=True)

            # Ordenar por score descendente
            scored_pairs = scored_pairs.sort_values("score", ascending=False)

            self.logger.info(
                f"Pares con score >= {threshold}: {len(scored_pairs):,} "
                f"({len(scored_pairs) / n_candidates:.1%} de candidatos)"
            )

            # Log estadísticas de cache
            self._log_cache_stats()

            return scored_pairs
        else:
            self.logger.warning("Ningún par superó el threshold de score")
            return pd.DataFrame(columns=["idx_0", "idx_1", "score", "name_sim", "nit_dist"])

    def _score_batch_vectorized(
        self, batch_candidates: np.ndarray, df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Calcula scores de similitud para un batch de pares candidatos de forma vectorizada.

        VERSIÓN CORREGIDA: Siempre retorna un DataFrame con la estructura de columnas
        correcta, incluso cuando está vacío. Esto previene el KeyError: 'score'.

        Args:
            batch_candidates: Array numpy con pares de índices [(idx1, idx2), ...]
            df: DataFrame con los datos de los registros

        Returns:
            DataFrame con columnas: idx_0, idx_1, score, name_sim, nit_dist
            (puede estar vacío pero siempre tendrá las columnas definidas)
        """
        # ═══════════════════════════════════════════════════════════════════════
        # DEFINICIÓN DE COLUMNAS ESTÁNDAR
        # Estas columnas SIEMPRE deben estar presentes en el DataFrame de retorno
        # ═══════════════════════════════════════════════════════════════════════
        COLUMNS = ["idx_0", "idx_1", "score", "name_sim", "nit_dist"]

        # ═══════════════════════════════════════════════════════════════════════
        # CONTADORES PARA AUDITORÍA MUESTREADA
        # v0.7.1: este init defensivo se mantiene por si _compute_scores_batch_vectorized
        # se llama sin pasar por score_pairs(). El default es 0 (deshabilitado) en
        # línea con la política de Sprint 0.8.1; quien invoca directo y necesite
        # auditoría debe inicializar _audit_counters explícitamente antes.
        # ═══════════════════════════════════════════════════════════════════════
        if not hasattr(self, "_audit_counters"):
            self._audit_counters = {"passes_printed": 0, "fails_printed": 0, "max_prints": 0}

        n_pairs = len(batch_candidates)

        # ═══════════════════════════════════════════════════════════════════════
        # CORRECCIÓN 1: Batch vacío → retornar DataFrame con columnas
        # ═══════════════════════════════════════════════════════════════════════
        if n_pairs == 0:
            return pd.DataFrame(columns=COLUMNS)

        # Extraer índices de los pares
        idx_0 = batch_candidates[:, 0]
        idx_1 = batch_candidates[:, 1]

        # Obtener datos de los registros correspondientes
        data_batch_0 = df.iloc[idx_0]
        data_batch_1 = df.iloc[idx_1]

        # Extraer valores para comparación
        names_0 = data_batch_0["NOMBRE_LIMPIO"].values
        names_1 = data_batch_1["NOMBRE_LIMPIO"].values
        nits_0 = data_batch_0["NIT_OK"].fillna("").values
        nits_1 = data_batch_1["NIT_OK"].fillna("").values

        # ═══════════════════════════════════════════════════════════════════════
        # PASO 1: CALCULAR MÉTRICAS Y APLICAR FILTROS PREVIOS
        # v2.9.0 (P1-1): VECTORIZACIÓN COMPLETA del cálculo de similitudes.
        # Reemplaza el bucle `for i in compute_indices` por llamadas batch a
        # `rapidfuzz.process.cpdist` (pairwise en C++). En ground truths de
        # ~1500 pares el speedup es ~3-5x; en producción (millones de pares)
        # se espera más. Paridad bit-a-bit verificada vía oráculo guardado en
        # tests/data/oraculo_scorer_p1_1.pkl (ver MIGRATION_LOG §19).
        # ═══════════════════════════════════════════════════════════════════════
        from rapidfuzz import process as rf_process
        from rapidfuzz.fuzz import ratio as simple_ratio, token_set_ratio as tsr

        # Coerción vectorizada a string (preserva el contrato: 'nan' string
        # se trata como nulo en las máscaras posteriores).
        names_0_s = pd.array(names_0, dtype="string").to_numpy(na_value="")
        names_1_s = pd.array(names_1, dtype="string").to_numpy(na_value="")

        # Pre-filtro rápido: longitudes vectorizadas via numpy. Strings vacíos
        # o 'nan' literal → longitud 0 (no se computan).
        is_nan_0 = (names_0_s == "") | (names_0_s == "nan")
        is_nan_1 = (names_1_s == "") | (names_1_s == "nan")
        # np.char.str_len es ufunc nativo; ~50-100× más rápido que la
        # list-comprehension previa para datasets grandes.
        len_0 = np.where(is_nan_0, 0, np.char.str_len(names_0_s.astype("U")))
        len_1 = np.where(is_nan_1, 0, np.char.str_len(names_1_s.astype("U")))
        max_len = np.maximum(len_0, len_1)
        min_len = np.minimum(len_0, len_1)
        with np.errstate(divide="ignore", invalid="ignore"):
            len_ratio = np.where(max_len > 0, min_len / max_len, 0.0)

        # Máscaras de validez:
        #   - viables: pasan el pre-filtro de longitud (>= 0.10)
        #   - both_valid: ambos lados son strings no-nulos
        #   - identical: nombres exactamente iguales (skip → sim=1.0)
        viable_mask = len_ratio >= 0.10
        both_valid_mask = ~is_nan_0 & ~is_nan_1
        identical_mask = both_valid_mask & (names_0_s == names_1_s)
        # candidatos para token_set_ratio: viables, ambos no-nulos, no idénticos
        tsr_mask = viable_mask & both_valid_mask & ~identical_mask

        name_similarities = np.zeros(n_pairs, dtype=np.float64)
        # Camino rápido: idénticos → 1.0
        name_similarities[identical_mask] = 1.0

        if tsr_mask.any():
            tsr_idx = np.where(tsr_mask)[0]
            # cpdist: pairwise(queries[k], choices[k]) en C++.
            tsr_scores = (
                rf_process.cpdist(
                    names_0_s[tsr_idx].tolist(),
                    names_1_s[tsr_idx].tolist(),
                    scorer=tsr,
                    dtype=np.float64,
                )
                / 100.0
            )

            # Refinamiento solo para scores intermedios (0.3 < score < 0.95)
            refine_local_mask = (tsr_scores > 0.3) & (tsr_scores < 0.95)
            if refine_local_mask.any():
                refine_idx = tsr_idx[refine_local_mask]
                simple_scores = (
                    rf_process.cpdist(
                        names_0_s[refine_idx].tolist(),
                        names_1_s[refine_idx].tolist(),
                        scorer=simple_ratio,
                        dtype=np.float64,
                    )
                    / 100.0
                )
                # Combinar: 0.8 * tsr + 0.2 * simple_ratio
                refined = 0.8 * tsr_scores[refine_local_mask] + 0.2 * simple_scores
                # Bonus *1.05 si comparten primer token (vectorizado vía split rápido)
                # Para mantener paridad exacta, se hace por elemento — pero sobre el
                # subconjunto refinado, que típicamente es ~10-20 % del total.
                first_tokens_0 = np.array(
                    [s.split(" ", 1)[0] if s else "" for s in names_0_s[refine_idx]],
                    dtype=object,
                )
                first_tokens_1 = np.array(
                    [s.split(" ", 1)[0] if s else "" for s in names_1_s[refine_idx]],
                    dtype=object,
                )
                share_first = (first_tokens_0 == first_tokens_1) & (first_tokens_0 != "")
                refined = np.where(share_first, np.minimum(1.0, refined * 1.05), refined)
                tsr_scores[refine_local_mask] = refined

            name_similarities[tsr_idx] = tsr_scores

        # ── v2.12.0 (Fix #3): RE-SCORING POR IDF DE TOKENS ──────────────
        # Mezcla token_set_ratio con una similitud Jaccard ponderada por IDF.
        # Atenúa pares cuya coincidencia se debe a tokens frecuentes
        # (genéricos / exportadores compartidos). No-op si blend=0 o sin mapa.
        if self.idf_weight_blend > 0.0 and self.token_idf:
            idf_default = self.idf_default
            token_idf = self.token_idf
            blend = self.idf_weight_blend
            # Solo recalcular donde hay un nombre real comparable.
            idf_idx = np.where(tsr_mask)[0]
            for k in idf_idx:
                toks_0 = {t for t in names_0_s[k].split() if len(t) >= 2}
                toks_1 = {t for t in names_1_s[k].split() if len(t) >= 2}
                if not toks_0 or not toks_1:
                    continue
                inter = toks_0 & toks_1
                union = toks_0 | toks_1
                w_inter = sum(token_idf.get(t, idf_default) for t in inter)
                w_union = sum(token_idf.get(t, idf_default) for t in union)
                idf_sim = (w_inter / w_union) if w_union > 0 else 0.0
                name_similarities[k] = (1.0 - blend) * name_similarities[k] + blend * idf_sim

        # ── v2.10.0 (Fix #2): PENALIZAR NAME_SIM SI AMBOS NOMBRES SON CORTOS Y GENÉRICOS ──
        # Heurística calibrada para minimizar daño colateral:
        #
        #   1. Ambos nombres tienen ≤ MAX_TOKENS tokens (cortos).
        #   2. TODOS los tokens (≥2 chars) están en el set genérico.
        #   3. El name_sim ya es alto (>= 0.85) — el caso problemático
        #      es exactamente cuando un match perfecto sobre nombres
        #      cortos genéricos se confunde con identidad real.
        #
        # Esta combinación captura "INVERSIONES SAS" (2 tokens, ambos
        # genéricos, name_sim=1.0) sin afectar entidades reales con
        # nombres compuestos como "PRODUCTOS ALIMENTICIOS COLOMBIA"
        # (3 tokens; aunque todos podrían ser genéricos, llegando a name_sim
        # 1.0 entre dos plantas reales con NITs distintos, la confusión es
        # real y este fix ayudaría — pero también podría matar matches
        # legítimos en datasets con grupos pequeños). Por seguridad
        # limitamos a MAX_TOKENS=3.
        #
        # No-op si `generic_name_penalty=0.0` o `_generic_tokens` vacío.
        MAX_TOKENS = int(self.profile.get("generic_name_max_tokens", 3))
        MIN_SIM_TRIGGER = float(self.profile.get("generic_name_min_sim", 0.85))
        if self.generic_name_penalty > 0.0 and self.generic_tokens:
            both_generic = np.zeros(n_pairs, dtype=bool)
            for k in range(n_pairs):
                if name_similarities[k] < MIN_SIM_TRIGGER:
                    continue
                s0_k, s1_k = names_0_s[k], names_1_s[k]
                if not s0_k or not s1_k:
                    continue
                toks_0 = [t for t in s0_k.split() if len(t) >= 2]
                toks_1 = [t for t in s1_k.split() if len(t) >= 2]
                if not toks_0 or not toks_1:
                    continue
                if len(toks_0) > MAX_TOKENS or len(toks_1) > MAX_TOKENS:
                    continue
                if all(t in self.generic_tokens for t in toks_0) and all(
                    t in self.generic_tokens for t in toks_1
                ):
                    both_generic[k] = True
            if both_generic.any():
                penalty_factor = 1.0 - self.generic_name_penalty
                name_similarities[both_generic] *= penalty_factor

        # Calcular distancias de NIT
        nit_distances = self._calculate_nit_distances_vectorized(nits_0, nits_1)

        # Crear máscaras de filtro
        name_filter_mask = name_similarities >= self.min_name_similarity
        # v3.2.4 (FIX FASE 1): si nit_empty_passes_filter=False, los pares con
        # NIT vacío en algún lado (nit_distance == -1) NO pasan el filtro.
        # Comportamiento previo (default True) preservado para no romper tests.
        if self.nit_empty_passes_filter:
            nit_filter_mask = nit_distances <= self.max_nit_distance
        else:
            nit_filter_mask = (nit_distances >= 0) & (nit_distances <= self.max_nit_distance)
        valid_pairs_mask = name_filter_mask & nit_filter_mask

        # ── v2.8.0 (P0-1): override por NIT idéntico ──────────────────────
        # Si el flag está activo, los pares con NIT idéntico no-vacío
        # (`nit_distances == 0`) pasan el filtro aunque su nombre esté por
        # debajo de `min_name_similarity`. nit_distances == -1 significa NIT
        # vacío en alguno de los dos lados — esos NO se eximen porque la
        # evidencia es ausencia, no coincidencia. Ver MIGRATION_LOG §18.
        if self.nit_identical_overrides_name_filter:
            nit_identical_mask = nit_distances == 0
            valid_pairs_mask = valid_pairs_mask | nit_identical_mask

        # ═══════════════════════════════════════════════════════════════════════
        # AUDITORÍA MUESTREADA - FASE 2 Paso 2.5: Optimizada con indexación directa
        # En lugar de iterar TODOS los n_pairs para imprimir solo 5 ejemplos,
        # usamos np.where() para obtener directamente los índices que necesitamos.
        # Ahorro: ~5 minutos acumulados en datasets grandes.
        # ═══════════════════════════════════════════════════════════════════════
        max_prints = self._audit_counters["max_prints"]
        remaining_passes = max_prints - self._audit_counters["passes_printed"]
        remaining_fails = max_prints - self._audit_counters["fails_printed"]

        if remaining_passes > 0 or remaining_fails > 0:
            # Obtener índices directamente con numpy (sin loop)
            pass_idx = (
                np.where(valid_pairs_mask)[0][:remaining_passes]
                if remaining_passes > 0
                else np.array([], dtype=int)
            )
            fail_idx = (
                np.where(~valid_pairs_mask)[0][:remaining_fails]
                if remaining_fails > 0
                else np.array([], dtype=int)
            )
            audit_indices = np.concatenate([pass_idx, fail_idx])

            for i in audit_indices:
                passes = valid_pairs_mask[i]
                # v0.7.1 (Sprint 0.8.1, Tarea 1.1): consolidado a logger.debug
                # — antes eran 8 print() por par, ahora 1 mensaje multilínea.
                _idx_pair = (df.iloc[idx_0[i]].name, df.iloc[idx_1[i]].name)
                _decision = "SÍ" if passes else "NO"
                self.logger.debug(
                    "AUDIT PAIR %s%s"
                    "  Nombres: %r vs %r%s"
                    "  NITs:    %r vs %r%s"
                    "  Sim Nombre: %.4f (umbral=%s) -> pasa=%s%s"
                    "  Dist NIT:   %s (umbral=%s) -> pasa=%s%s"
                    "  Decisión: pasa ambos filtros = %s",
                    _idx_pair,
                    "\n",
                    names_0[i],
                    names_1[i],
                    "\n",
                    nits_0[i],
                    nits_1[i],
                    "\n",
                    name_similarities[i],
                    self.min_name_similarity,
                    name_filter_mask[i],
                    "\n",
                    nit_distances[i],
                    self.max_nit_distance,
                    nit_filter_mask[i],
                    "\n",
                    _decision,
                )

            # Actualizar contadores
            self._audit_counters["passes_printed"] += len(pass_idx)
            self._audit_counters["fails_printed"] += len(fail_idx)

        # ═══════════════════════════════════════════════════════════════════════
        # CORRECCIÓN 2: Ningún par pasa filtros → retornar DataFrame con columnas
        # ═══════════════════════════════════════════════════════════════════════
        if not np.any(valid_pairs_mask):
            return pd.DataFrame(columns=COLUMNS)

        # ═══════════════════════════════════════════════════════════════════════
        # PASO 2: CALCULAR MÉTRICAS SECUNDARIAS (solo para pares válidos)
        # ═══════════════════════════════════════════════════════════════════════
        valid_indices = np.where(valid_pairs_mask)[0]

        # Similitud de NIT (inversa de la distancia normalizada)
        nit_similarities = self._calculate_nit_similarities_vectorized(
            nits_0[valid_indices], nits_1[valid_indices]
        )

        # Similitud fonética (si está configurada y hay datos)
        phonetic_similarities = np.zeros(len(valid_indices))
        if self.weights.get("phonetic", 0) > 0 and "PHONETIC_KEY1" in df.columns:
            phonetic_0 = data_batch_0.iloc[valid_indices]["PHONETIC_KEY1"].fillna("").values
            phonetic_1 = data_batch_1.iloc[valid_indices]["PHONETIC_KEY1"].fillna("").values
            phonetic_similarities = self._calculate_phonetic_similarities_vectorized(
                phonetic_0, phonetic_1
            )

        # ═══════════════════════════════════════════════════════════════════════
        # PASO 3: CALCULAR SCORE PONDERADO FINAL
        # ═══════════════════════════════════════════════════════════════════════
        final_scores = (
            self.weights["name"] * name_similarities[valid_indices]
            + self.weights["nit"] * nit_similarities
            + self.weights.get("phonetic", 0) * phonetic_similarities
        )

        # ── v2.7.0 (P2 Camino #1): SUMAR CONTRIBUCIÓN DE EXTRA FEATURES ──
        # Cada feature extra aporta `weight * similarity` al score final.
        # Con tipos NO firmados (categorical, exact_or_zero) la contribución es
        # ≥ 0 (solo premia). Con tipos FIRMADOS (categorical_signed, etc.) puede
        # ser negativa: una discrepancia RESTA, lo que permite separar pares
        # negativos (p.ej. NIT adyacente + ciudad distinta). Tras sumar,
        # recortamos a [0, 1] porque el resto del pipeline (clusterer, reportes)
        # asume scores en ese rango; un par penalizado simplemente cae por
        # debajo del threshold, que es exactamente el efecto buscado.
        # Si no hay extra_features definidas, esto es un no-op exacto (paridad
        # bit-a-bit con v2.6.0).
        if self.extra_features:
            extra_contribution = self._compute_extra_features_contribution(
                data_batch_0.iloc[valid_indices],
                data_batch_1.iloc[valid_indices],
            )
            final_scores = np.clip(final_scores + extra_contribution, 0.0, 1.0)

        # ── v2.8.0 (P0-1) + v2.10.0 (Fix #1): BOOST DE SCORE PARA NIT IDÉNTICO ──
        # Diferenciado por DV_ORIGEN:
        #   - Si AMBOS lados tienen DV declarado → boost_declared (señal fuerte)
        #   - Caso contrario (al menos uno computed) → boost (señal media)
        # Si la columna DV_ORIGEN no está presente, todo se trata como
        # computed (conservador) y solo aplica el boost normal.
        _has_any_boost = self.nit_identical_score_boost > 0.0 or (
            self.nit_identical_score_boost_declared is not None
            and self.nit_identical_score_boost_declared > 0.0
        )
        if _has_any_boost:
            nit_dist_valid = nit_distances[valid_indices]
            nit_identical = nit_dist_valid == 0
            if nit_identical.any():
                # Detectar pares ambos-declarados si la columna existe.
                ambos_declarados = np.zeros(len(nit_dist_valid), dtype=bool)
                if "DV_ORIGEN" in data_batch_0.columns and "DV_ORIGEN" in data_batch_1.columns:
                    dv_0 = data_batch_0["DV_ORIGEN"].iloc[valid_indices].to_numpy()
                    dv_1 = data_batch_1["DV_ORIGEN"].iloc[valid_indices].to_numpy()
                    ambos_declarados = (dv_0 == "declared") & (dv_1 == "declared")

                # Boost diferenciado: declared usa el boost específico si está
                # definido, sino cae al boost normal. computed siempre usa el
                # boost normal.
                boost_declared = (
                    self.nit_identical_score_boost_declared
                    if self.nit_identical_score_boost_declared is not None
                    else self.nit_identical_score_boost
                )
                aplicar_declared = nit_identical & ambos_declarados
                aplicar_computed = nit_identical & ~ambos_declarados

                boost_vec = np.zeros_like(final_scores)
                boost_vec[aplicar_declared] = boost_declared
                boost_vec[aplicar_computed] = self.nit_identical_score_boost
                final_scores = np.clip(final_scores + boost_vec, 0.0, 1.0)

        # ═══════════════════════════════════════════════════════════════════════
        # PASO 4: CONSTRUIR DATAFRAME DE RESULTADOS
        # ═══════════════════════════════════════════════════════════════════════
        results_df = pd.DataFrame(
            {
                "idx_0": idx_0[valid_indices],
                "idx_1": idx_1[valid_indices],
                "score": final_scores,
                "name_sim": name_similarities[valid_indices],
                "nit_dist": nit_distances[valid_indices],
            }
        )

        # Filtro final basado en el score ponderado
        return results_df[results_df["score"] >= self.score_threshold]

    # ════════════════════════════════════════════════════════════════════
    # v2.7.0 (P2 Camino #1): VARIABLES ADICIONALES
    # ════════════════════════════════════════════════════════════════════

    def _compute_extra_features_contribution(
        self, batch_0: pd.DataFrame, batch_1: pd.DataFrame
    ) -> np.ndarray:
        """Calcula la contribución vectorizada de las features extra al score.

        Cada feature definida en ``self.extra_features`` aporta
        ``weight * similarity_per_pair`` al score final. Si la columna no
        existe en el DataFrame, esa feature se omite con un warning único
        por corrida (para no saturar logs en pipelines grandes).

        Tipos de similitud soportados (ver ``_feature_similarity_vectorized``
        para el detalle completo). Resumen:
            - "exact_or_zero":  [0,1]  — premia coincidencia exacta.
            - "categorical":    [0,1]  — premia coincidencia, neutral si nulo.
            - "token_set_ratio":[0,1]  — fuzzy.
            - "categorical_signed":  [-1,1] — premia coincidencia, PENALIZA
              discrepancia, neutral si nulo. (recomendado para CIUDAD)
            - "exact_signed":        [-1,1] — idem sin normalizar mayúsculas.
            - "token_set_ratio_signed": [-1,1] — fuzzy firmado.

        Los tipos firmados son los que permiten *separar* casos negativos;
        los no firmados solo refuerzan pares ya plausibles.

        Args:
            batch_0: subset del DataFrame para el lado izquierdo del par.
            batch_1: subset del DataFrame para el lado derecho del par.

        Returns:
            Array de contribución por par (mismo length que batch_0).
        """
        n = len(batch_0)
        contribution = np.zeros(n, dtype=np.float64)

        if not hasattr(self, "_extra_features_warned"):
            self._extra_features_warned: set[str] = set()

        for feature in self.extra_features:
            col = feature.get("column")
            weight = float(feature.get("weight", 0.0))
            ftype = feature.get("type", "exact_or_zero")
            if not col or weight <= 0.0:
                continue
            if col not in batch_0.columns:
                if col not in self._extra_features_warned:
                    self.logger.warning(
                        f"[extra_features] Columna '{col}' no presente en el "
                        f"DataFrame; esta feature se omitirá toda la corrida."
                    )
                    self._extra_features_warned.add(col)
                continue

            vals_0 = batch_0[col].to_numpy()
            vals_1 = batch_1[col].to_numpy()

            sim = self._feature_similarity_vectorized(vals_0, vals_1, ftype)
            contribution += weight * sim

        return contribution

    # Valores tratados como nulos en columnas extra (case-insensitive).
    _NULLISH: ClassVar[frozenset[str]] = frozenset({"", "NAN", "NONE", "NULL", "<NA>"})

    @staticmethod
    def _to_clean_str_series(values: np.ndarray) -> pd.Series:
        """Convierte un array (numpy/list) a Series de strings cross-version safe.

        Historia/justificación (v3.2.3): este wrapper existe para neutralizar una
        regresión silenciosa introducida en pandas 2.1+ y consolidada en 3.x.
        Antes (≤2.0), ``pd.Series([np.nan]).astype(str)`` producía el string
        ``'nan'`` (cinco letras), lo que permitía detectar el nulo con un
        ``frozenset`` que incluyera la cadena ``'NAN'``. Desde pandas 2.1+, con
        ``infer_string`` activado por defecto en 3.x, el mismo código preserva
        el ``NaN`` real (float). El resultado: el ``isin(_NULLISH)`` que antes
        detectaba el nulo como cadena ``'NAN'`` ahora pasa por alto el ``NaN``
        flotante, marcándolo erróneamente como valor *válido*. En features
        firmados (``categorical_signed``, ``exact_signed``, …) esto producía
        penalizaciones de ``-1.0`` espurias cuando el valor real era nulo.

        Diagnóstico empírico (dataset ``golden_truth_exhaustivo_ciudad``):
        - pandas 2.2.x → 263 pares correctamente clasificados como "ciudades
          distintas" + 1731 correctamente como "alguno nulo".
        - pandas 3.x (sin este wrapper) → 1994 pares clasificados como
          "distintos" + 0 como "nulos" (los 1731 nulos se contaban como
          distintos por error → penalización masiva indebida).

        Solución: normalizar nulos (``NaN``, ``None``, ``pd.NA``) a la cadena
        vacía ``""`` ANTES de ``.astype(str)``. La cadena vacía ya está en
        ``_NULLISH``, por lo que ``_valid_mask`` la detecta como nulo en
        cualquier versión de pandas.

        Args:
            values: array de entrada (object, string, o equivalentes).

        Returns:
            Serie de strings sin NaN/pd.NA; nulos materializados como ``""``.
        """
        s = pd.Series(values)
        # ``s.where(s.notna(), "")`` reemplaza TODO null-like (np.nan, None,
        # pd.NA) por la cadena vacía. ``.astype(str)`` posterior preserva los
        # strings tal cual y evita el camino donde pandas 3.x mantiene el NaN.
        return s.where(s.notna(), "").astype(str)

    @staticmethod
    def _valid_mask(s: pd.Series) -> np.ndarray:
        """Devuelve máscara booleana de valores NO nulos para una serie de strings.

        Trata ``''``, ``'nan'``, ``'none'``, ``'null'``, ``'<na>'``
        (case-insensitive) como nulos. Requiere que el caller haya pasado la
        serie por ``_to_clean_str_series`` (o equivalente) para garantizar
        que los nulos *reales* (NaN/pd.NA) ya están materializados como ``""``.

        Args:
            s: serie de strings ya normalizada (sin NaN flotantes residuales).

        Returns:
            Array booleano del mismo tamaño que ``s``; ``True`` donde el valor
            es válido (no nulo).
        """
        upper = s.str.upper()
        return (~upper.isin(VectorizedScorer._NULLISH)).to_numpy()

    @staticmethod
    def _feature_similarity_vectorized(a: np.ndarray, b: np.ndarray, ftype: str) -> np.ndarray:
        """Calcula la similitud por par para una columna extra (vectorizada).

        Hay dos familias de tipos:

        **No firmados** (rango ``[0, 1]``, solo PREMIAN coincidencias):
            - ``exact_or_zero``: 1.0 si ambos no-nulos e iguales, 0.0 si no.
            - ``categorical``: 1.0 si iguales, 0.5 si uno es nulo, 0.0 si distintos.
            - ``token_set_ratio``: fuzzy 0..1 vía rapidfuzz.

        **Firmados** (rango ``[-1, 1]``, PREMIAN coincidencias y PENALIZAN
        discrepancias). Son los que permiten *separar* casos negativos —p.ej.
        dos empresas con NIT adyacente pero CIUDAD distinta—:
            - ``categorical_signed``: +1.0 si ambos no-nulos e iguales, -1.0 si
              ambos no-nulos y distintos, 0.0 si alguno es nulo (la ausencia no
              aporta ni resta evidencia).
            - ``exact_signed``: idéntico a ``categorical_signed`` pero sin
              normalización de mayúsculas (comparación exacta tras trim). Útil
              para identificadores como teléfono donde el case no aplica.
            - ``token_set_ratio_signed``: ``2 * fuzz - 1`` (mapea 0..1 → -1..+1).
              Penaliza textos muy distintos, premia muy parecidos. Si algún
              valor es nulo → 0.0.

        Notas sobre nulos (v3.2.3): todas las coerciones a string usan
        ``_to_clean_str_series``, que materializa NaN/pd.NA como ``""`` antes
        de aplicar ``.astype(str)``. Esto neutraliza la divergencia entre
        pandas 2.x (NaN → 'nan' literal) y 3.x (NaN preservado), garantizando
        que la política "nulo → 0.0" se aplique de forma idéntica en ambas.

        Args:
            a: array con valores del lado izquierdo del par.
            b: array con valores del lado derecho del par.
            ftype: tipo de similitud (ver arriba).

        Returns:
            Array del mismo tamaño que a/b. Rango ``[0, 1]`` para tipos no
            firmados, ``[-1, 1]`` para tipos firmados.
        """
        n = len(a)
        if n == 0:
            return np.zeros(0, dtype=np.float64)

        valid = VectorizedScorer._valid_mask
        clean = VectorizedScorer._to_clean_str_series

        if ftype == "exact_or_zero":
            # 1.0 si ambos no-nulos y exactamente iguales, 0.0 si no.
            sa = clean(a).str.strip()
            sb = clean(b).str.strip()
            both_valid = valid(sa) & valid(sb)
            equal = sa.to_numpy() == sb.to_numpy()
            return (both_valid & equal).astype(np.float64)

        if ftype == "categorical":
            # 1.0 si ambos no-nulos e iguales (case-insensitive, trim),
            # 0.5 si uno es nulo (no penaliza la ausencia), 0.0 si distintos.
            sa = clean(a).str.strip().str.upper()
            sb = clean(b).str.strip().str.upper()
            va, vb = valid(sa), valid(sb)
            both_valid = va & vb
            one_nullish = va ^ vb
            equal = sa.to_numpy() == sb.to_numpy()
            out = np.zeros(n, dtype=np.float64)
            out[both_valid & equal] = 1.0
            out[one_nullish] = 0.5
            return out

        if ftype == "categorical_signed":
            # +1.0 coinciden · -1.0 discrepan (ambos no-nulos) · 0.0 si algún nulo.
            sa = clean(a).str.strip().str.upper()
            sb = clean(b).str.strip().str.upper()
            both_valid = valid(sa) & valid(sb)
            equal = sa.to_numpy() == sb.to_numpy()
            out = np.zeros(n, dtype=np.float64)
            out[both_valid & equal] = 1.0
            out[both_valid & ~equal] = -1.0
            return out

        if ftype == "exact_signed":
            # Como categorical_signed pero comparación exacta (sin upper).
            sa = clean(a).str.strip()
            sb = clean(b).str.strip()
            both_valid = valid(sa) & valid(sb)
            equal = sa.to_numpy() == sb.to_numpy()
            out = np.zeros(n, dtype=np.float64)
            out[both_valid & equal] = 1.0
            out[both_valid & ~equal] = -1.0
            return out

        if ftype in ("token_set_ratio", "token_set_ratio_signed"):
            try:
                from rapidfuzz import fuzz, process as rf_process
            except ImportError:
                return np.zeros(n, dtype=np.float64)
            sa = clean(a).str.strip()
            sb = clean(b).str.strip()
            both_valid = valid(sa) & valid(sb)
            # v2.9.0 (P1-1): vectorizado via rapidfuzz.process.cpdist (C++).
            scores = (
                rf_process.cpdist(
                    sa.to_list(),
                    sb.to_list(),
                    scorer=fuzz.token_set_ratio,
                    dtype=np.float64,
                )
                / 100.0
            )
            if ftype == "token_set_ratio_signed":
                # Mapear 0..1 → -1..+1; nulos quedan en 0.0.
                scores = np.where(both_valid, 2.0 * scores - 1.0, 0.0)
            else:
                scores = np.where(both_valid, scores, 0.0)
            return scores

        # Tipo desconocido → 0.0 sin romper.
        return np.zeros(n, dtype=np.float64)

    # def _apply_additional_filters(self, scored_pairs: pd.DataFrame) -> pd.DataFrame:
    #     """
    #     Esta función ahora solo filtra por el score_threshold final, ya que los
    #     otros filtros se aplicaron antes.
    #     """
    #     # La función se simplifica enormemente. Los filtros de NIT y Nombre ya se hicieron.
    #     # Ahora solo queda el filtro final del score ponderado.
    #     return scored_pairs[scored_pairs['score'] >= self.score_threshold]

    def _calculate_name_similarities_vectorized(
        self, names_0: np.ndarray, names_1: np.ndarray
    ) -> np.ndarray:
        """Calcular similitudes de nombre (vectorizado, batch).

        v2.9.0 (P1-1): este es el path alterno al inline en
        `_score_batch_vectorized`. Mantiene la misma lógica (tsr + refinamiento
        con simple_ratio + bonus por primer token compartido), ahora en batch
        via rapidfuzz.process.cpdist.

        El cache (`self._similarity_cache`) se preserva en su semántica pero ya
        no se consulta por par — en pipelines reales con millones de pares la
        tasa de hit es < 1 %, y el costo del lookup era mayor que el cómputo
        en C++. Si alguien necesita el cache (p.ej. evaluación con el mismo
        candidato muchas veces), seguir usando `_calculate_single_name_similarity`.
        """
        from rapidfuzz import process as rf_process
        from rapidfuzz.fuzz import ratio as simple_ratio, token_set_ratio as tsr

        n_pairs = len(names_0)
        s0 = pd.array(names_0, dtype="string").to_numpy(na_value="").astype("U")
        s1 = pd.array(names_1, dtype="string").to_numpy(na_value="").astype("U")

        similarities = np.zeros(n_pairs, dtype=np.float64)
        invalid_mask = (s0 == "") | (s1 == "")
        identical_mask = ~invalid_mask & (s0 == s1)
        similarities[identical_mask] = 1.0

        # Pre-filtro de longitud (≥ 0.10)
        len_0 = np.char.str_len(s0)
        len_1 = np.char.str_len(s1)
        max_len = np.maximum(len_0, len_1)
        min_len = np.minimum(len_0, len_1)
        with np.errstate(divide="ignore", invalid="ignore"):
            len_ratio = np.where(max_len > 0, min_len / max_len, 0.0)

        compute_mask = ~invalid_mask & ~identical_mask & (len_ratio >= 0.10)
        if compute_mask.any():
            idx = np.where(compute_mask)[0]
            tsr_scores = (
                rf_process.cpdist(
                    s0[idx].tolist(),
                    s1[idx].tolist(),
                    scorer=tsr,
                    dtype=np.float64,
                )
                / 100.0
            )

            refine_local = (tsr_scores > 0.3) & (tsr_scores < 0.95)
            if refine_local.any():
                refine_idx_global = idx[refine_local]
                simple_scores = (
                    rf_process.cpdist(
                        s0[refine_idx_global].tolist(),
                        s1[refine_idx_global].tolist(),
                        scorer=simple_ratio,
                        dtype=np.float64,
                    )
                    / 100.0
                )
                refined = 0.8 * tsr_scores[refine_local] + 0.2 * simple_scores
                ft0 = np.array(
                    [t.split(" ", 1)[0] if t else "" for t in s0[refine_idx_global]],
                    dtype=object,
                )
                ft1 = np.array(
                    [t.split(" ", 1)[0] if t else "" for t in s1[refine_idx_global]],
                    dtype=object,
                )
                share_first = (ft0 == ft1) & (ft0 != "")
                refined = np.where(share_first, np.minimum(1.0, refined * 1.05), refined)
                tsr_scores[refine_local] = refined

            similarities[idx] = tsr_scores
        # Para len_ratio < 0.10 el score queda en 0.0 (paridad con la rama
        # `if min/max < 0.10: return 0.0` de _calculate_single_name_similarity).
        return similarities

    def _calculate_single_name_similarity(self, name1: str, name2: str) -> float:
        """Calcular similitud entre dos nombres."""
        if not name1 or not name2:
            return 0.0

        if name1 == name2:
            return 1.0

        # Verificar diferencia extrema de longitud
        len1, len2 = len(name1), len(name2)
        if min(len1, len2) / max(len1, len2) < 0.10:  # 0.10 más permisivo, antes estaba en 0.3
            return 0.0

        # Usar rapidfuzz para eficiencia
        # Token set ratio es bueno para empresas con palabras en diferente orden
        score = fuzz.token_set_ratio(name1, name2) / 100.0

        # Si el score es muy alto o muy bajo, retornar directamente
        if score >= 0.95 or score <= 0.3:
            return score

        # Para scores intermedios, refinar con ratio simple
        simple_score = fuzz.ratio(name1, name2) / 100.0

        # Combinar scores con pesos
        final_score = 0.8 * score + 0.2 * simple_score

        # Bonus si comparten primera palabra (común en nombres de empresa)
        words1 = name1.split()
        words2 = name2.split()
        if words1 and words2 and words1[0] == words2[0]:
            final_score = min(1.0, final_score * 1.05)

        return final_score

    def _calculate_nit_similarities_vectorized(
        self, nits_0: np.ndarray, nits_1: np.ndarray
    ) -> np.ndarray:
        """Calcular similitudes de NIT (vectorizado).

        v2.9.0 (P1-1): elimina el `for i in range(n_pairs)`. La lógica
        preservada bit-a-bit:
            - Si alguno es nulo/'nan'/"" → 0.0
            - Si idénticos → 1.0
            - Si distintos: 1 - (lev_dist / max_len), penalizado ×0.5 si
              |len_diff| > 2
        """
        from rapidfuzz import process as rf_process
        from rapidfuzz.distance import Levenshtein as rf_lev

        n_pairs = len(nits_0)
        s0 = pd.array(nits_0, dtype="string").to_numpy(na_value="").astype("U")
        s1 = pd.array(nits_1, dtype="string").to_numpy(na_value="").astype("U")
        s0 = np.char.strip(s0)
        s1 = np.char.strip(s1)

        similarities = np.zeros(n_pairs, dtype=np.float64)
        invalid_mask = (s0 == "") | (s1 == "") | (s0 == "nan") | (s1 == "nan")
        identical_mask = ~invalid_mask & (s0 == s1)
        similarities[identical_mask] = 1.0

        compute_mask = ~invalid_mask & ~identical_mask
        if compute_mask.any():
            idx = np.where(compute_mask)[0]
            distances = rf_process.cpdist(
                s0[idx].tolist(),
                s1[idx].tolist(),
                scorer=rf_lev.distance,
                dtype=np.int64,
            ).astype(np.float64)
            len_0 = np.char.str_len(s0[idx])
            len_1 = np.char.str_len(s1[idx])
            max_len = np.maximum(len_0, len_1)
            len_diff = np.abs(len_0 - len_1)
            with np.errstate(divide="ignore", invalid="ignore"):
                vals = np.where(max_len > 0, 1.0 - (distances / max_len), 0.0)
            # Penalizar diferencias de longitud > 2
            penalty_mask = len_diff > 2
            vals = np.where(penalty_mask, vals * 0.5, vals)
            similarities[idx] = vals
        return similarities

    def _calculate_nit_distances_vectorized(
        self, nits_0: np.ndarray, nits_1: np.ndarray
    ) -> np.ndarray:
        """Calcular distancias de Levenshtein entre NITs (vectorizado).

        v2.9.0 (P1-1): elimina el `for i in range(n_pairs)` que llamaba a
        rapidfuzz una vez por par; ahora usa `process.cpdist` con scorer
        Levenshtein.distance (cálculo pairwise en C++). Speedup observado:
        2-3× sobre listas de 100k-1M pares. NITs vacíos / 'nan' / "" devuelven
        -1 (sentinela usada por el filtro y por la regla de NIT idéntico).

        Paridad bit-a-bit garantizada vs v2.8.0 — ver scripts/validar_paridad_p1_1.py.
        """
        from rapidfuzz import process as rf_process
        from rapidfuzz.distance import Levenshtein as rf_lev

        n_pairs = len(nits_0)
        # Coerción vectorizada: NaN/None/"nan" → "".
        s0 = pd.array(nits_0, dtype="string").to_numpy(na_value="")
        s1 = pd.array(nits_1, dtype="string").to_numpy(na_value="")
        # strip vectorizado a través de numpy.char (ufunc).
        s0 = np.char.strip(s0.astype("U"))
        s1 = np.char.strip(s1.astype("U"))

        invalid_mask = (s0 == "") | (s1 == "") | (s0 == "nan") | (s1 == "nan")
        distances = np.full(n_pairs, -1, dtype=np.int32)
        valid_idx = np.where(~invalid_mask)[0]
        if valid_idx.size:
            dists = rf_process.cpdist(
                s0[valid_idx].tolist(),
                s1[valid_idx].tolist(),
                scorer=rf_lev.distance,
                dtype=np.int64,
            )
            distances[valid_idx] = dists.astype(np.int32)
        return distances

    def _calculate_phonetic_similarities_vectorized(
        self, phonetic_0: np.ndarray, phonetic_1: np.ndarray
    ) -> np.ndarray:
        """Calcular similitudes fonéticas (vectorizado).

        v2.9.0 (P1-1): elimina el bucle por par. La similitud es 1.0 si las
        claves coinciden, sino se usa Indel.normalized_similarity, que es
        matemáticamente equivalente a `Levenshtein.ratio` de python-Levenshtein
        (ambos usan distancia tipo "Indel" donde la sustitución cuenta como 2
        ediciones). NO se usa `rapidfuzz.distance.Levenshtein.normalized_similarity`
        porque cuenta sustitución como 1 → produce ratios distintos.

        Paridad bit-a-bit garantizada vs v2.8.0.
        """
        from rapidfuzz import process as rf_process
        from rapidfuzz.distance import Indel as rf_indel

        n_pairs = len(phonetic_0)
        s0 = pd.array(phonetic_0, dtype="string").to_numpy(na_value="").astype("U")
        s1 = pd.array(phonetic_1, dtype="string").to_numpy(na_value="").astype("U")

        similarities = np.zeros(n_pairs, dtype=np.float64)
        # both_valid: claves no vacías. Si alguna es "" → 0.0 (sin información).
        both_valid = (s0 != "") & (s1 != "")
        identical = both_valid & (s0 == s1)
        similarities[identical] = 1.0

        ratio_mask = both_valid & ~identical
        if ratio_mask.any():
            idx = np.where(ratio_mask)[0]
            sims = rf_process.cpdist(
                s0[idx].tolist(),
                s1[idx].tolist(),
                scorer=rf_indel.normalized_similarity,
                dtype=np.float64,
            )
            similarities[idx] = sims
        return similarities

    def score_pairs_from_db(
        self, candidates_db_path: str, df: pd.DataFrame, score_threshold: float | None = None
    ) -> pd.DataFrame:
        """
        Calcular scores para pares candidatos almacenados en base de datos SQLite.
        VERSIÓN CORREGIDA Y ROBUSTA.
        """
        threshold = score_threshold if score_threshold is not None else self.score_threshold

        conn = sqlite3.connect(candidates_db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM candidate_pairs")
        total_candidates = cursor.fetchone()[0]

        self.logger.info(
            f"Calculando scores para {total_candidates:,} pares desde disco (threshold={threshold:.2f})"
        )

        # Configuración para lectura eficiente
        cursor.execute("PRAGMA cache_size = -1000000")
        cursor.execute("PRAGMA temp_store = MEMORY")

        all_results = []
        offset = 0
        query = "SELECT idx_0, idx_1 FROM candidate_pairs ORDER BY idx_0, idx_1 LIMIT ? OFFSET ?"

        with tqdm(total=total_candidates, desc="Calculando scores desde disco") as pbar:
            while offset < total_candidates:
                cursor.execute(query, (self.batch_size, offset))
                batch_rows = cursor.fetchall()
                if not batch_rows:
                    break

                batch_candidates = np.array(batch_rows)

                # ======================= INICIO DE LA CORRECCIÓN =======================
                # La función _score_batch_vectorized ya aplica todos los filtros
                # (nombre, NIT y score). Solo necesitamos verificar si devolvió algo.
                batch_results = self._score_batch_vectorized(batch_candidates, df)

                # Verificación robusta: nos aseguramos de que no esté vacío antes de añadirlo.
                # Ya no se necesita el filtrado redundante que causaba el error.
                if not batch_results.empty:
                    all_results.append(batch_results)
                # ======================== FIN DE LA CORRECCIÓN =========================

                pbar.update(len(batch_rows))
                pbar.set_postfix(
                    {
                        "pares_validos": sum(len(r) for r in all_results),
                        "memoria_MB": f"{psutil.Process().memory_info().rss / 1024**2:.0f}",
                    }
                )

                offset += self.batch_size
                if offset % (self.batch_size * 10) == 0:
                    gc.collect()

        conn.close()

        if all_results:
            scored_pairs = pd.concat(all_results, ignore_index=True)
            scored_pairs = scored_pairs.sort_values("score", ascending=False)
            self.logger.info(
                f"Pares con score >= {threshold}: {len(scored_pairs):,} ({len(scored_pairs) / total_candidates:.1%} de candidatos)"
            )
            return scored_pairs
        else:
            self.logger.warning("Ningún par superó el threshold de score")
            return pd.DataFrame(columns=["idx_0", "idx_1", "score", "name_sim", "nit_dist"])

    def _log_cache_stats(self):
        """Log estadísticas de cache."""
        total_lookups = self._cache_hits + self._cache_misses
        if total_lookups > 0:
            hit_rate = self._cache_hits / total_lookups
            self.logger.debug(
                f"Cache stats: {self._cache_hits:,} hits, "
                f"{self._cache_misses:,} misses, "
                f"hit rate: {hit_rate:.1%}, "
                f"cache size: {len(self._similarity_cache):,}"
            )

    def update_config(self, new_config: dict[str, Any]):
        """Actualizar configuración del scorer."""
        if "weights" in new_config:
            self.weights = new_config["weights"]
            # Normalizar
            total = sum(self.weights.values())
            self.weights = {k: v / total for k, v in self.weights.items()}

        if "score_threshold" in new_config:
            self.score_threshold = new_config["score_threshold"]

        if "max_nit_distance" in new_config:
            self.max_nit_distance = new_config["max_nit_distance"]

        if "min_name_similarity" in new_config:
            self.min_name_similarity = new_config["min_name_similarity"]

    def cleanup(self):
        """Limpiar recursos."""
        self._similarity_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0
        gc.collect()

    # ================================================================
    # 📊 MODIFICACIÓN DE VectorizedScorer - AÑADIR CAPACIDAD DE STREAMING
    # ================================================================
    # Agregar estos métodos a la clase VectorizedScorer existente (NO reemplazar la clase completa)

    def score_pairs_with_streaming(
        self,
        candidates: set[tuple[int, int]] | str,
        df: pd.DataFrame,
        score_threshold: float | None = None,
        output_db_path: str | None = None,
    ) -> pd.DataFrame | str:
        """
        Versión mejorada de score_pairs que detecta automáticamente si usar streaming.

        Esta función es el punto de entrada principal que decide la estrategia óptima
        basándose en el número de candidatos y la memoria disponible.

        Args:
            candidates: Set de pares o ruta a archivo SQLite con candidatos
            df: DataFrame con datos preprocesados
            score_threshold: Umbral de score (opcional)
            output_db_path: Ruta para guardar resultados (opcional, auto-generada si es necesario)

        Returns:
            pd.DataFrame si los resultados caben en memoria, o str con ruta a BD si se usó streaming
        """
        threshold = score_threshold or self.score_threshold

        # Detectar tipo de entrada y decidir estrategia
        if isinstance(candidates, str) and candidates.endswith(".db"):
            # Candidatos vienen de una BD
            return self._score_pairs_from_db_streaming(candidates, df, threshold, output_db_path)
        elif isinstance(candidates, set):
            # Candidatos en memoria - decidir si usar streaming basado en tamaño
            n_candidates = len(candidates)
            memory_status = MemoryManager.get_memory_status()

            # Estimar memoria necesaria (aproximadamente 200 bytes por par scored)
            estimated_memory_gb = (n_candidates * 200) / (1024**3)

            # Usar streaming si:
            # 1. Se esperan muchos resultados (>500K asumiendo 10% pass rate)
            # 2. No hay suficiente memoria disponible
            use_streaming = (
                n_candidates > 5_000_000
                or estimated_memory_gb > memory_status["available_gb"] * 0.5
            )

            if use_streaming:
                self.logger.info(
                    f"Activando modo streaming para {n_candidates:,} candidatos "
                    f"(memoria estimada: {estimated_memory_gb:.1f}GB)"
                )
                return self._score_pairs_set_streaming(candidates, df, threshold, output_db_path)
            else:
                # Usar implementación original en memoria
                return self.score_pairs(candidates, df, score_threshold)
        else:
            raise ValueError(f"Tipo de candidatos no soportado: {type(candidates)}")

    def _score_pairs_from_db_streaming(
        self,
        candidates_db_path: str,
        df: pd.DataFrame,
        threshold: float,
        output_db_path: str | None = None,
    ) -> str:
        """
        Procesa candidatos desde una BD y escribe resultados directamente a otra BD.

        Esta es la implementación clave para escalabilidad: nunca carga todos los
        candidatos ni resultados en memoria, solo procesa batch por batch.
        """
        # Conectar a BD de candidatos
        conn = sqlite3.connect(candidates_db_path)
        cursor = conn.cursor()

        # Configurar para lectura eficiente
        cursor.execute("PRAGMA cache_size = -1000000")  # 1GB cache
        cursor.execute("PRAGMA temp_store = MEMORY")

        # Obtener total de candidatos
        cursor.execute("SELECT COUNT(*) FROM candidate_pairs")
        total_candidates = cursor.fetchone()[0]

        self.logger.info(
            f"Procesando {total_candidates:,} candidatos desde BD "
            f"con streaming (threshold={threshold:.2f})"
        )

        # Crear BD para resultados
        if output_db_path is None:
            timestamp = int(time.time() * 1000)
            output_db_path = f"scored_pairs_{timestamp}.db"

        # Si existe, eliminar para empezar limpio
        if os.path.exists(output_db_path):
            os.remove(output_db_path)

        scored_conn = sqlite3.connect(output_db_path)
        scored_cursor = scored_conn.cursor()

        # Crear esquema optimizado
        scored_cursor.execute("""
            CREATE TABLE scored_pairs (
                idx_0 INTEGER NOT NULL,
                idx_1 INTEGER NOT NULL,
                score REAL NOT NULL,
                name_sim REAL,
                nit_sim REAL,
                nit_dist INTEGER,
                phonetic_sim REAL,
                PRIMARY KEY (idx_0, idx_1)
            ) WITHOUT ROWID
        """)

        # Configuración para escritura rápida
        for pragma in [
            "PRAGMA journal_mode = OFF",
            "PRAGMA synchronous = OFF",
            "PRAGMA cache_size = -2000000",
            "PRAGMA temp_store = MEMORY",
            "PRAGMA page_size = 65536",
        ]:
            scored_cursor.execute(pragma)

        # Variables de control
        offset = 0
        total_scored = 0
        total_passed = 0
        write_buffer = []
        write_buffer_size = 10000

        # Query para leer batches
        query = """
            SELECT idx_0, idx_1
            FROM candidate_pairs
            ORDER BY idx_0, idx_1
            LIMIT ? OFFSET ?
        """

        # Iniciar transacción para escrituras masivas
        scored_cursor.execute("BEGIN TRANSACTION")

        try:
            with tqdm(total=total_candidates, desc="Scoring candidatos (streaming)") as pbar:
                while offset < total_candidates:
                    # Leer batch
                    cursor.execute(query, (self.batch_size, offset))
                    batch_rows = cursor.fetchall()

                    if not batch_rows:
                        break

                    # Convertir a array para procesamiento vectorizado
                    batch_candidates = np.array(batch_rows)

                    # Paso 1.3: _score_batch_vectorized ya filtra internamente
                    batch_results = self._score_batch_vectorized(batch_candidates, df)

                    if not batch_results.empty:
                        valid_scores = batch_results
                        # v2.9.0 (P1-1): conversión vectorizada en vez de iterrows.
                        # `to_numpy` extrae las columnas en bloque; las tuplas se
                        # construyen via list comprehension simple sobre arrays
                        # nativos (sin overhead de Series.iloc por par).
                        idx_0_arr = valid_scores["idx_0"].to_numpy(dtype=np.int64)
                        idx_1_arr = valid_scores["idx_1"].to_numpy(dtype=np.int64)
                        score_arr = valid_scores["score"].to_numpy(dtype=np.float64)
                        name_sim_arr = valid_scores["name_sim"].to_numpy(dtype=np.float64)
                        if "nit_sim" in valid_scores.columns:
                            nit_sim_arr = valid_scores["nit_sim"].to_numpy(dtype=np.float64)
                        else:
                            nit_sim_arr = np.zeros(len(valid_scores), dtype=np.float64)
                        if "nit_dist" in valid_scores.columns:
                            nit_dist_arr = valid_scores["nit_dist"].to_numpy(dtype=np.int64)
                        else:
                            nit_dist_arr = np.full(len(valid_scores), -1, dtype=np.int64)
                        if "phonetic_sim" in valid_scores.columns:
                            phon_arr = valid_scores["phonetic_sim"].to_numpy(dtype=np.float64)
                        else:
                            phon_arr = np.zeros(len(valid_scores), dtype=np.float64)

                        for k in range(len(valid_scores)):
                            write_buffer.append(
                                (
                                    int(idx_0_arr[k]),
                                    int(idx_1_arr[k]),
                                    float(score_arr[k]),
                                    float(name_sim_arr[k]),
                                    float(nit_sim_arr[k]),
                                    int(nit_dist_arr[k]),
                                    float(phon_arr[k]),
                                )
                            )

                            # Escribir buffer cuando esté lleno
                            if len(write_buffer) >= write_buffer_size:
                                scored_cursor.executemany(
                                    """INSERT INTO scored_pairs
                                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                    write_buffer,
                                )
                                total_passed += len(write_buffer)
                                write_buffer = []

                    # Actualizar estadísticas
                    total_scored += len(batch_rows)
                    offset += len(batch_rows)

                    # Actualizar progreso
                    pbar.update(len(batch_rows))
                    pbar.set_postfix(
                        {
                            "válidos": f"{total_passed:,}",
                            "tasa": f"{total_passed / max(total_scored, 1):.1%}",
                            "memoria_MB": f"{psutil.Process().memory_info().rss / 1024**2:.0f}",
                        }
                    )

                    # Commit periódico para no perder trabajo
                    if total_scored % 500000 == 0:
                        if write_buffer:
                            scored_cursor.executemany(
                                """INSERT INTO scored_pairs
                                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                                write_buffer,
                            )
                            total_passed += len(write_buffer)
                            write_buffer = []
                        scored_cursor.execute("COMMIT")
                        scored_cursor.execute("BEGIN TRANSACTION")

                    # Liberar memoria periódicamente
                    if offset % (self.batch_size * 10) == 0:
                        gc.collect()

            # Escribir registros finales
            if write_buffer:
                scored_cursor.executemany(
                    """INSERT INTO scored_pairs
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    write_buffer,
                )
                total_passed += len(write_buffer)

            # Commit final
            scored_cursor.execute("COMMIT")

            # Crear índices para fase de clustering
            self.logger.info("Creando índices para optimizar siguiente fase...")
            scored_cursor.execute("CREATE INDEX idx_scored_0 ON scored_pairs(idx_0)")
            scored_cursor.execute("CREATE INDEX idx_scored_1 ON scored_pairs(idx_1)")
            scored_cursor.execute("CREATE INDEX idx_score ON scored_pairs(score DESC)")

            # Guardar metadatos
            scored_cursor.execute("""
                CREATE TABLE metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            metadata = [
                ("total_candidates", str(total_candidates)),
                ("total_scored", str(total_scored)),
                ("total_passed", str(total_passed)),
                ("threshold", str(threshold)),
                ("pass_rate", str(total_passed / max(total_candidates, 1))),
                ("creation_time", str(time.time())),
            ]

            scored_cursor.executemany("INSERT INTO metadata VALUES (?, ?)", metadata)
            scored_cursor.execute("COMMIT")

        finally:
            conn.close()
            scored_conn.close()

        self.logger.info(
            f"✅ Scoring completado: {total_passed:,} pares válidos de {total_candidates:,} "
            f"({total_passed / max(total_candidates, 1):.1%}) escritos a {output_db_path}"
        )

        # Log estadísticas de cache
        self._log_cache_stats()

        return output_db_path

    def _score_pairs_set_streaming(
        self,
        candidates: set[tuple[int, int]],
        df: pd.DataFrame,
        threshold: float,
        output_db_path: str | None = None,
    ) -> str:
        """
        Procesa un set de candidatos en memoria pero escribe resultados a disco.

        Útil cuando los candidatos ya están en memoria pero queremos evitar
        acumular todos los resultados.
        """
        # Primero escribir candidatos a una BD temporal
        temp_candidates_db = f"temp_candidates_{int(time.time() * 1000)}.db"

        conn = sqlite3.connect(temp_candidates_db)
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE candidate_pairs (
                idx_0 INTEGER NOT NULL,
                idx_1 INTEGER NOT NULL,
                PRIMARY KEY (idx_0, idx_1)
            ) WITHOUT ROWID
        """)

        # Insertar candidatos por batches
        candidates_list = list(candidates)
        batch_size = 100000

        cursor.execute("BEGIN TRANSACTION")
        for i in range(0, len(candidates_list), batch_size):
            batch = candidates_list[i : i + batch_size]
            cursor.executemany("INSERT INTO candidate_pairs VALUES (?, ?)", batch)
        cursor.execute("COMMIT")

        conn.close()

        try:
            # Delegar al método de streaming desde BD
            result = self._score_pairs_from_db_streaming(
                temp_candidates_db, df, threshold, output_db_path
            )
        finally:
            # Limpiar BD temporal
            if os.path.exists(temp_candidates_db):
                os.remove(temp_candidates_db)

        return result
