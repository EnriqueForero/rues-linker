"""Constantes y helpers internos del notebook fuente.

Estos símbolos eran globales del notebook. Aquí se preservan
para mantener compatibilidad con clases que los referencian.
"""

from __future__ import annotations

import gc
import logging
from contextlib import contextmanager

import pandas as pd

from ..processing._constants import LEGAL_SUFFIXES, ORGANIZATIONAL_TERMS, STOPWORDS_BASIC

# ────────────────────────────────────────────────────────────
# COMMERCIAL_TERMS  (origen: notebook celda [147])
# ────────────────────────────────────────────────────────────
COMMERCIAL_TERMS = {
    "COMERCIALIZADORA",
    "TRADING",
    "SERVICIOS",
    "SOLUCIONES",
    "SOLUTIONS",
    "INVERSIONES",
    "INVESTMENT",
    "DISTRIBUIDORA",
    "CONSULTING",
    "CONSULTORES",
    "ASESORES",
    "TECHNOLOGIES",
    "TECH",
    "TECHNOLOGY",
    "SYSTEMS",
    "MANAGEMENT",
    "INVESTMENTS",
    "CAPITAL",
    "PRODUCTS",
    "EQUIPOS",
    "SUMINISTROS",
    "WHOLESALE",
    "RETAIL",
    "GROWTH",
    "DISTRIBUTION",
    "DISTRIBUIDOR",
}

# ────────────────────────────────────────────────────────────
# DEDUP_CLEANING_MODES  (origen: notebook celda [147], tipo: assign)
# ────────────────────────────────────────────────────────────
DEDUP_CLEANING_MODES = {
    "CONSERVADOR": STOPWORDS_BASIC | LEGAL_SUFFIXES,
    "BALANCEADO": STOPWORDS_BASIC | LEGAL_SUFFIXES | ORGANIZATIONAL_TERMS,
    "AGRESIVO": STOPWORDS_BASIC | LEGAL_SUFFIXES | ORGANIZATIONAL_TERMS | COMMERCIAL_TERMS,
}

# ────────────────────────────────────────────────────────────
# PROFILES  (origen: notebook celda [108], tipo: assign)
# ────────────────────────────────────────────────────────────
PROFILES = {
    "standard": {
        "description": "Perfil estándar para datasets medianos (<500k registros)",
        "lsh_permutations": 128,
        "lsh_threshold": 0.75,
        "lsh_ngram": 3,
        "batch_size": 30_000,
        "score_threshold": 0.82,
        "max_nit_distance": 2,
        "min_name_similarity": 0.65,
        "remove_top_words": 20,
        "weights": {"name": 0.65, "nit": 0.35, "phonetic": 0.0},
        "confidence_weights": {
            "source_priority": 0.4,
            "nit_consistency": 0.3,
            "name_consistency": 0.2,
            "source_count": 0.1,
        },
        "golden_chunk_size": 50_000,
        "correlative_chunk_size": 50_000,
        "trusted_unique_sources": [],  # ✅ Paso 1.6
    },
    "large_dataset_fast": {
        "description": "Perfil optimizado para datasets grandes (>3M registros)",
        "lsh_permutations": 128,
        "lsh_threshold": 0.65,
        "lsh_ngram": 3,
        "batch_size": 50_000,
        "lsh_batch_size": 10_000,
        "score_threshold": 0.7,
        "max_nit_distance": 2,
        "min_name_similarity": 0.70,
        "remove_top_words": 25,
        "weights": {"name": 0.70, "nit": 0.30, "phonetic": 0.0},
        "confidence_weights": {
            "source_priority": 0.4,
            "nit_consistency": 0.3,
            "name_consistency": 0.2,
            "source_count": 0.1,
        },
        "golden_chunk_size": 200_000,
        "correlative_chunk_size": 100_000,
        "use_disk_cache": True,
        "aggressive_gc": True,
        "trusted_unique_sources": [],  # ✅ Paso 1.6
    },
    "large_scale": {
        "description": "Perfil optimizado para datasets grandes (>3M registros)",
        "lsh_permutations": 96,
        "lsh_threshold": 0.82,
        "lsh_ngram": 3,
        "batch_size": 50_000,
        "lsh_batch_size": 10_000,
        "score_threshold": 0.85,
        "max_nit_distance": 2,
        "min_name_similarity": 0.70,
        "remove_top_words": 25,
        "weights": {"name": 0.70, "nit": 0.30, "phonetic": 0.00},
        "confidence_weights": {
            "source_priority": 0.4,
            "nit_consistency": 0.3,
            "name_consistency": 0.2,
            "source_count": 0.1,
        },
        "golden_chunk_size": 100_000,
        "correlative_chunk_size": 100_000,
        "use_disk_cache": True,
        "aggressive_gc": True,
        "trusted_unique_sources": [],  # ✅ Paso 1.6
    },
    "high_precision": {
        "description": "Perfil para máxima precisión (menos falsos positivos)",
        "lsh_permutations": 128,
        "lsh_threshold": 0.85,
        "lsh_ngram": 4,
        "batch_size": 20_000,
        "score_threshold": 0.90,
        "max_nit_distance": 1,
        "min_name_similarity": 0.80,
        "remove_top_words": 30,
        "weights": {"name": 0.60, "nit": 0.40, "phonetic": 0.00},
        "confidence_weights": {
            "source_priority": 0.5,
            "nit_consistency": 0.3,
            "name_consistency": 0.15,
            "source_count": 0.05,
        },
        "golden_chunk_size": 30_000,
        "correlative_chunk_size": 30_000,
        "trusted_unique_sources": [],  # ✅ Paso 1.6
    },
    "high_recall": {
        "description": "Perfil para máximo recall (encontrar más matches)",
        "lsh_permutations": 128,
        "lsh_threshold": 0.65,
        "lsh_ngram": 2,
        "batch_size": 40_000,
        "score_threshold": 0.70,
        "max_nit_distance": 3,
        "min_name_similarity": 0.55,
        "remove_top_words": 15,
        "weights": {"name": 0.70, "nit": 0.30, "phonetic": 0.00},
        "confidence_weights": {
            "source_priority": 0.3,
            "nit_consistency": 0.3,
            "name_consistency": 0.3,
            "source_count": 0.1,
        },
        "golden_chunk_size": 50_000,
        "correlative_chunk_size": 50_000,
        "trusted_unique_sources": [],  # ✅ Paso 1.6
    },
    "memory_constrained": {
        "description": "Perfil para entornos con memoria limitada (Google Colab)",
        "lsh_permutations": 64,
        "lsh_threshold": 0.80,
        "lsh_ngram": 3,
        "batch_size": 10_000,
        "lsh_batch_size": 5_000,
        "score_threshold": 0.85,
        "max_nit_distance": 2,
        "min_name_similarity": 0.70,
        "remove_top_words": 20,
        "weights": {"name": 0.70, "nit": 0.30, "phonetic": 0.00},
        "confidence_weights": {
            "source_priority": 0.4,
            "nit_consistency": 0.3,
            "name_consistency": 0.2,
            "source_count": 0.1,
        },
        "golden_chunk_size": 20_000,
        "correlative_chunk_size": 20_000,
        "use_disk_cache": True,
        "aggressive_gc": True,
        "max_memory_gb": 8.0,
        "trusted_unique_sources": [],  # ✅ Paso 1.6
    },
}

# ────────────────────────────────────────────────────────────
# DEDUPLICATION_PROFILES  (origen: notebook celda [147], tipo: assign)
# ────────────────────────────────────────────────────────────
DEDUPLICATION_PROFILES = {
    "deduplication_standard": {
        "description": "Deduplicación estándar para datasets medianos",
        "lsh_permutations": 128,
        # v2.2.0 — recalibrado contra ground truth (test_data_y_tabla_verdad,
        # 269 registros / 84 grupos). Ver tests/test_quality_golden.py y
        # MIGRATION_LOG §11. Resultados medidos del cambio:
        #   F1     0.406 → 0.635   (+56 %)
        #   recall 0.267 → 0.510   (casi 2×)
        #   prec.  0.848 → 0.839   (sin pérdida material)
        # Diagnóstico: el bloqueo LSH a 0.75 descartaba pares con typos antes
        # de compararlos (causa raíz del bajo recall); el NIT pesaba 0.45 pese
        # a ser poco fiable (dígitos errados); la fonética estaba apagada.
        "lsh_threshold": 0.30,  # antes 0.75 — bloqueo más permisivo
        "lsh_ngram": 3,
        "batch_size": 30_000,
        "score_threshold": 0.68,  # antes 0.85
        "max_nit_distance": 3,
        "min_name_similarity": 0.60,  # antes 0.65
        "remove_top_words": 20,
        # antes name:0.55 nit:0.45 phonetic:0.0
        "weights": {"name": 0.65, "nit": 0.20, "phonetic": 0.15},
        # v2.8.0 (P0-1): tratamiento privilegiado de NIT idéntico.
        # Ver MIGRATION_LOG §18 para diagnóstico completo.
        "nit_identical_overrides_name_filter": True,
        "nit_identical_score_boost": 0.05,
        # v2.10.0 (Fix #1): boost diferenciado para NIT con DV declarado.
        # Cuando AMBOS lados del par vienen con DV declarado en origen
        # (longitud original >= 10 dígitos o formato 'XXXXXXXXX-D'), la
        # evidencia de identidad es FUERTE — dos fuentes independientes
        # acordaron en el mismo NIT+DV que probablemente no se inventaron.
        # Boost 0.10 (vs 0.05 de computed) recupera FN de tipo P4 (token
        # disímil con NIT idéntico). Calibración contra dataset sintético;
        # recalibrar con producción real. Boost > 0.10 regresa golden 269.
        "nit_identical_score_boost_declared": 0.10,
        # v2.10.0 (Fix #2): penalización por nombre genérico (OPT-IN).
        # Penaliza name_sim cuando ambos nombres son cortos (≤3 tokens) y
        # están compuestos SOLO por tokens del set genérico (curado +
        # top-N del corpus). Resuelve el FP de "INVERSIONES SAS × 3" en
        # el dataset sintético robusto, PERO produce regresión en golden
        # 269 (F1 0.759→0.647) porque la lista curada de stop-words
        # empresariales incluye tokens (COMPAÑIA, COLOMBIA, EMPRESA, etc.)
        # que aparecen en nombres de empresas reales pequeñas.
        #
        # Default 0.0 = OFF. Activar SOLO tras calibrar con producción
        # real: si la muestra tiene 50k+ regs, los top-N del corpus
        # tomarán solo palabras genuinamente frecuentes y la regla será
        # más segura. Recomendado entonces:
        #     "generic_name_penalty": 0.5,
        #     "generic_name_top_n": 50,
        #     "generic_name_max_tokens": 3,
        #     "generic_name_min_sim": 0.85,
        "generic_name_penalty": 0.0,
        "generic_name_top_n": 30,
        "generic_name_max_tokens": 3,
        "generic_name_min_sim": 0.85,
        "use_strict_clusters": True,
        "cross_source_only": False,  # Clave para deduplicación
    },
    "deduplication_colab_3M": {
        "description": "Optimizado para RUES 3M+ registros en Colab",
        "lsh_permutations": 128,  # 96
        "lsh_threshold": 0.7,  # 0.82
        "lsh_ngram": 3,
        "batch_size": 15_000,
        "score_threshold": 0.88,
        "max_nit_distance": 2,
        "min_name_similarity": 0.70,
        "remove_top_words": 25,
        "weights": {"name": 0.70, "nit": 0.30, "phonetic": 0.0},
        "use_disk_cache": True,
        "aggressive_gc": True,
        "streaming_mode": True,
        "max_memory_gb": 10.5,
        "use_strict_clusters": True,
        "cross_source_only": False,
    },
    "deduplication_colab_1M": {
        "description": "Optimizado para DANE 1M registros en Colab",
        "lsh_permutations": 128,
        "lsh_threshold": 0.78,
        "lsh_ngram": 3,
        "batch_size": 25_000,
        "score_threshold": 0.85,
        "max_nit_distance": 3,
        "min_name_similarity": 0.65,
        "remove_top_words": 20,
        "weights": {"name": 0.65, "nit": 0.30, "phonetic": 0.05},
        "use_disk_cache": True,
        "aggressive_gc": False,
        "max_memory_gb": 10.0,
        "use_strict_clusters": True,
        "cross_source_only": False,
    },
    "deduplication_sin_nit_conservador": {
        # v2.11.0 — Perfil para fuentes SIN NIT (solo Razón Social [+ Ciudad]).
        # Caso real: importaciones (Corea del Sur), donde no hay NIT y el
        # único discriminante es el nombre + ciudad. En ese régimen el perfil
        # estándar SOBRE-FUSIONA: une empresas distintas que comparten un
        # token y la ciudad (p. ej. WORLD FLORA + DAEDONG GARDENING en SEOUL,
        # o tres compañías KOREA *POWER* CO LTD distintas).
        #
        # Calibración (barrido sobre 818 registros reales de Corea, v2.11.0):
        #   estándar (0.68/0.60/0.30) -> 324 grupos, grupo monstruo n=82,
        #     fusiona mal WORLD FLORA + DAEDONG.
        #   este perfil (0.80/0.75/0.50/ciudad 0.40) -> 450 grupos, max n=33
        #     (NENOVA, agrupación CORRECTA), separa WORLD FLORA de DAEDONG.
        # Prioriza PRECISIÓN sobre recall: preferimos NO fusionar dudosos.
        #
        # SIN ground truth no se puede afirmar un F1; estos números son de
        # composición (cuántos grupos, tamaño máximo), no de calidad medida.
        # Recalibrar si se obtiene un ground truth etiquetado del dominio.
        "description": "Conservador para fuentes sin NIT (solo nombre + ciudad)",
        "lsh_permutations": 128,
        "lsh_threshold": 0.50,  # más estricto que 0.30 — menos candidatos ruidosos
        "lsh_ngram": 3,
        "batch_size": 30_000,
        "score_threshold": 0.80,  # más alto que 0.68 — exige más evidencia para unir
        "max_nit_distance": 3,
        "min_name_similarity": 0.75,  # más alto que 0.60 — nombres deben parecerse más
        "remove_top_words": 20,
        # Sin NIT, el peso del NIT (0.20) se reparte: nombre domina, ciudad
        # entra vía extra_features (signed) para penalizar ciudades distintas.
        "weights": {"name": 0.65, "nit": 0.20, "phonetic": 0.15},
        # El override por NIT idéntico no aplica sin NIT, pero lo dejamos OFF
        # explícitamente para que el perfil sea autoexplicativo.
        "nit_identical_overrides_name_filter": False,
        "nit_identical_score_boost": 0.0,
        "nit_identical_score_boost_declared": 0.0,
        "generic_name_penalty": 0.0,
        "generic_name_top_n": 30,
        "generic_name_max_tokens": 3,
        "generic_name_min_sim": 0.85,
        # v2.12.0 (Fix #3): re-scoring por IDF de tokens. CLAVE para este
        # régimen. Sin IDF, el token_set_ratio agrupa por tokens frecuentes
        # ("ELITE EXPORTS INTERNATIONAL INC Y/O X" vs "...Y/O Z" = 93%, o
        # "SECUI CORPORATION" vs "MULTIFLORA CORPORATION" = 79% por
        # "CORPORATION"). Con blend=0.5 esos pares caen por debajo del
        # umbral y las empresas distintas dejan de fusionarse, mientras las
        # variantes reales (NENOVA, WORLD FLORA, ARES3...) se mantienen.
        #
        # Medido sobre Corea (818 sin NIT): SECUI/MULTIFLORA/CK/KSCORP pasan
        # de 1 grupo común a 4 grupos distintos; ELITE...Y/O X se separan en
        # singletons; NENOVA (n=28) y WORLD FLORA (n=18) se preservan.
        #
        # ⚠️ Este valor DAÑA los datasets con NIT (golden 269: F1 0.759→0.538)
        # porque penaliza la señal de nombre que el NIT debería complementar.
        # Por eso vive SOLO en este perfil, no en deduplication_standard.
        "idf_weight_blend": 0.5,
        "use_strict_clusters": True,
        "cross_source_only": False,
    },
}

# ────────────────────────────────────────────────────────────
# ALL_PROFILES  (origen: notebook celda [147], tipo: assign)
# ────────────────────────────────────────────────────────────
ALL_PROFILES = {**PROFILES, **DEDUPLICATION_PROFILES}

# ────────────────────────────────────────────────────────────
# DEFAULT_CONFIG  (origen: notebook celda [108], tipo: assign)
# ────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "profile": "standard",
    "output_directory": "resultados_record_linkage",
    "max_file_size_mb": 100,
    "compress_large_files": True,
    "cleaning_mode": "BALANCEADO",
    "validation_rules": {
        "min_nit_length": 6,
        "max_nit_length": 15,
        "min_name_length": 5,
        "max_name_length": 300,
        "remove_test_data": True,
        "remove_invalid_nits": True,
    },
    "quality_thresholds": {
        "min_coverage": 0.05,
        "max_group_size": 100,
        "review_threshold": 0.75,
        "min_confidence": 0.50,
        "min_quality_score": 0.30,
    },
    "export_settings": {
        "excel_max_rows": 1_000_000,
        "csv_compression": "gzip",
        "parquet_compression": "snappy",
        "include_diagnostics": True,
    },
    "performance_settings": {
        "enable_profiling": False,
        "log_memory_usage": True,
        "save_intermediate_results": False,
    },
}


# ────────────────────────────────────────────────────────────
# _class_exists  (origen: notebook celda [192], tipo: function)
# ────────────────────────────────────────────────────────────
def _class_exists(class_name: str) -> bool:
    """
    Verifica si una clase existe en el contexto global de forma segura.

    Más robusto que verificar directamente en globals() ya que
    maneja casos edge como nombres con sintaxis inválida.

    Args:
        class_name: Nombre de la clase a verificar

    Returns:
        True si la clase existe y es accesible, False en caso contrario
    """
    try:
        cls = eval(class_name)
        return cls is not None
    except (NameError, SyntaxError, Exception):
        return False


# ────────────────────────────────────────────────────────────
# _fmt_time  (origen: notebook celda [192], tipo: function)
# ────────────────────────────────────────────────────────────
def _fmt_time(seconds: float) -> str:
    """
    Formatea segundos a string legible.

    Args:
        seconds: Tiempo en segundos

    Returns:
        String formateado (ej: "2h 30m", "45m 12s", "3.5s")
    """
    if seconds >= 3600:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"
    elif seconds >= 60:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    return f"{seconds:.1f}s"


# ────────────────────────────────────────────────────────────
# _get_logger  (origen: notebook celda [192], tipo: function)
# ────────────────────────────────────────────────────────────
def _get_logger(name: str = "Orchestrator") -> logging.Logger:
    """
    Configura y retorna logger con formato consistente.

    El logger usa formato con timestamp y nivel, ideal para
    seguimiento de procesos largos.

    Args:
        name: Nombre del logger

    Returns:
        Logger configurado
    """
    logger = logging.getLogger(name)

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-5s | %(message)s", "%H:%M:%S")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger


# ────────────────────────────────────────────────────────────
# _phase_cleanup  (origen: notebook celda [192], tipo: function)
# ────────────────────────────────────────────────────────────
@contextmanager
def _phase_cleanup():
    """
    Context manager para limpieza de memoria entre fases.

    Ejecuta gc.collect() al finalizar cada fase (incluso si la fase
    lanza excepción) para liberar memoria y evitar acumulación en
    procesos largos.

    Uso:
        with _phase_cleanup():
            resultado = ejecutar_fase()
    """
    try:
        yield
    finally:
        gc.collect()


# ────────────────────────────────────────────────────────────
# _validate_sources  (origen: notebook celda [192], tipo: function)
# ────────────────────────────────────────────────────────────
def _validate_sources(
    sources: dict[str, pd.DataFrame], logger: logging.Logger
) -> tuple[bool, list[str]]:
    """
    Valida que las fuentes de datos tengan la estructura esperada.

    Verifica:
    - Que existan fuentes definidas
    - Que cada fuente sea un DataFrame válido y no vacío
    - Que cada fuente tenga las columnas requeridas (NIT, RAZON_SOCIAL)

    Args:
        sources: Diccionario de fuentes {nombre: DataFrame}
        logger: Logger para reportar errores

    Returns:
        Tupla (es_valido, lista_de_errores)
    """
    errores = []
    columnas_requeridas = ["NIT", "RAZON_SOCIAL"]

    if not sources:
        return False, ["No hay fuentes definidas"]

    for nombre, df in sources.items():
        if df is None:
            errores.append(f"{nombre}: DataFrame es None")
            continue

        if not isinstance(df, pd.DataFrame):
            errores.append(f"{nombre}: No es un DataFrame válido (tipo: {type(df).__name__})")
            continue

        if len(df) == 0:
            errores.append(f"{nombre}: DataFrame vacío (0 registros)")
            continue

        # Verificar columnas requeridas
        faltantes = [col for col in columnas_requeridas if col not in df.columns]
        if faltantes:
            errores.append(f"{nombre}: Faltan columnas requeridas: {faltantes}")
            disponibles = list(df.columns)[:10]
            errores.append(f"   Columnas disponibles (primeras 10): {disponibles}")

    # Reportar todos los errores encontrados
    if errores:
        for err in errores:
            logger.error(f"   ❌ {err}")

    return len(errores) == 0, errores
