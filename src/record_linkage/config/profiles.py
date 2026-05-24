"""record_linkage.config.profiles — Perfiles de configuración LSH.

Cada perfil define los parámetros completos del pipeline para un escenario:
parámetros LSH, scoring, pesos, batch sizes, fuentes trusted, etc.

Origen:
- PERFILES_BASE: notebook celda [87]
- config_produccion_it7: notebook celda [260] (CELDA 8.3 - IT-7 OPTIMIZADA)
- crear_config_orchestrator: notebook celda [87]
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..golden._priorities import obtener_prioridades_fuentes

PERFILES_BASE = {
    # ═══════════════════════════════════════════════════════════════════════════
    # PERFIL: PRUEBA RÁPIDA (para desarrollo y testing)
    # ═══════════════════════════════════════════════════════════════════════════
    "prueba_rapida": {
        "description": "Prueba rápida con parámetros conservadores",
        # Limpieza de texto
        "cleaning_mode": "BALANCEADO",
        "remove_top_words": 0,
        # LSH - Locality Sensitive Hashing
        "lsh_permutations": 128,
        "lsh_threshold": 0.55,
        "lsh_ngram": 3,
        # Scoring
        "score_threshold": 0.45,
        "min_name_similarity": 0.30,
        "max_nit_distance": 3,
        # Pesos de similitud
        "weights": {"name": 0.5, "nit": 0.5, "phonetic": 0.0},
        # Recursos (conservador para Colab)
        "batch_size": 50_000,
        "lsh_batch_size": 30_000,
        "scoring_batch_size": 50_000,
        # Opciones
        "cross_source_only": False,  # ⚠️ DEPRECADO: usar trusted_unique_sources
        "trusted_unique_sources": [],  # ✅ Paso 1.6: fuentes que no se comparan internamente
        "use_disk_cache": True,
        "force_disk_results": True,
        "use_strict_clusters": True,  # ← NUEVO: Paso 1.1
    },
    # ═══════════════════════════════════════════════════════════════════════════
    # PERFIL: PRODUCCIÓN ESTÁNDAR (IT-7 - balance óptimo)
    # ═══════════════════════════════════════════════════════════════════════════
    "produccion_estandar": {
        "description": "Producción estándar - Balance calidad/tiempo (8-9 horas)",
        # Limpieza
        "cleaning_mode": "BALANCEADO",
        "remove_top_words": 0,
        # LSH - Configuración IT-7 validada
        "lsh_permutations": 252,
        "lsh_threshold": 0.55,
        "lsh_ngram": 3,
        # Scoring
        "score_threshold": 0.45,
        "min_name_similarity": 0.30,
        "max_nit_distance": 3,
        # Pesos
        "weights": {"name": 0.5, "nit": 0.5, "phonetic": 0.0},
        # Recursos
        "batch_size": 100_000,
        "lsh_batch_size": 50_000,
        "lsh_chunk_size": 150_000,
        "scoring_batch_size": 75_000,
        "clustering_batch_size": 100_000,
        "golden_chunk_size": 100_000,
        # Memoria
        "max_memory_gb": 8.5,
        "aggressive_gc": True,
        # Opciones
        "cross_source_only": False,  # ⚠️ DEPRECADO: usar trusted_unique_sources
        "trusted_unique_sources": [],  # ✅ Paso 1.6
        "use_disk_cache": True,
        "force_disk_results": True,
        "use_strict_clusters": True,  # ← NUEVO: Paso 1.1
    },
    # ═══════════════════════════════════════════════════════════════════════════
    # PERFIL: PRODUCCIÓN EXHAUSTIVA (IT-9 - máxima detección)
    # ═══════════════════════════════════════════════════════════════════════════
    "produccion_exhaustiva": {
        "description": "Producción exhaustiva - Máxima detección (12-14 horas)",
        # Limpieza
        "cleaning_mode": "BALANCEADO",
        "remove_top_words": 0,
        # LSH - Más permisivo
        "lsh_permutations": 252,
        "lsh_threshold": 0.58,  # Más bajo = más candidatos
        "lsh_ngram": 3,
        # Scoring - Más permisivo
        "score_threshold": 0.40,
        "min_name_similarity": 0.25,
        "max_nit_distance": 4,
        # Pesos
        "weights": {"name": 0.5, "nit": 0.5, "phonetic": 0.0},
        # Recursos
        "batch_size": 100_000,
        "lsh_batch_size": 50_000,
        "lsh_chunk_size": 150_000,
        "scoring_batch_size": 75_000,
        "clustering_batch_size": 100_000,
        "golden_chunk_size": 100_000,
        # Memoria
        "max_memory_gb": 8.5,
        "aggressive_gc": True,
        # Opciones
        "cross_source_only": False,  # ⚠️ DEPRECADO: usar trusted_unique_sources
        "trusted_unique_sources": [],  # ✅ Paso 1.6
        "use_disk_cache": True,
        "force_disk_results": True,
        "use_strict_clusters": True,  # ← NUEVO: Paso 1.1
    },
    # ═══════════════════════════════════════════════════════════════════════════
    # PERFIL: ALTA PRECISIÓN (menos falsos positivos)
    # ═══════════════════════════════════════════════════════════════════════════
    "alta_precision": {
        "description": "Alta precisión - Minimiza falsos positivos",
        # Limpieza
        "cleaning_mode": "AGRESIVO",
        "remove_top_words": 5,
        # LSH - Restrictivo
        "lsh_permutations": 252,
        "lsh_threshold": 0.65,  # Más alto = menos candidatos
        "lsh_ngram": 3,
        # Scoring - Estricto
        "score_threshold": 0.55,
        "min_name_similarity": 0.45,
        "max_nit_distance": 2,
        # Pesos
        "weights": {
            "name": 0.50,
            "nit": 0.50,  # Mayor peso al NIT
            "phonetic": 0.0,
        },
        # Recursos
        "batch_size": 100_000,
        "lsh_batch_size": 50_000,
        # Opciones
        "cross_source_only": False,  # ⚠️ DEPRECADO: usar trusted_unique_sources
        "trusted_unique_sources": [],  # ✅ Paso 1.6
        "use_disk_cache": True,
        "force_disk_results": True,
        "use_strict_clusters": True,  # ← NUEVO: Paso 1.1
    },
    # ═══════════════════════════════════════════════════════════════════════════
    # PERFIL: DEDUPLICACIÓN SIMPLE (una sola fuente)
    # ═══════════════════════════════════════════════════════════════════════════
    "deduplicacion_simple": {
        "description": "Deduplicación de una sola fuente",
        # Limpieza
        "cleaning_mode": "BALANCEADO",
        "remove_top_words": 0,
        # LSH
        "lsh_permutations": 128,
        "lsh_threshold": 0.50,
        "lsh_ngram": 3,
        # Scoring
        "score_threshold": 0.45,
        "min_name_similarity": 0.35,
        "max_nit_distance": 3,
        # Pesos
        "weights": {"name": 0.50, "nit": 0.50, "phonetic": 0.0},
        # Recursos (conservador)
        "batch_size": 50_000,
        "lsh_batch_size": 30_000,
        # Opciones
        "cross_source_only": False,  # ⚠️ DEPRECADO: usar trusted_unique_sources
        "trusted_unique_sources": [],  # ✅ Paso 1.6
        "use_disk_cache": True,
        "force_disk_results": True,
        "use_strict_clusters": True,  # ← NUEVO: Paso 1.1
    },
}


# NOTA: en el notebook fuente (celda 260), `output_directory` y `lsh_storage_dir`
# referenciaban globales `WORKSPACE` y `NOMBRE_EJECUCION` definidas en runtime.
# En el paquete .py se exponen como placeholders ("$WORKSPACE", "$NOMBRE_EJECUCION")
# que el `Orchestrator` debe sustituir o el script orquestador debe sobrescribir
# antes de ejecutar. Esto preserva la estructura del config sin romper imports.
config_produccion_it7 = {
    "profile": "enterprise_scale_4_sources",
    "output_directory": "$WORKSPACE",  # ← sobrescribir antes de ejecutar
    "linkage_engine_class": "disk_based",
    "lsh_storage_dir": "lsh_$NOMBRE_EJECUCION",  # ← sobrescribir antes de ejecutar
    "cleaning_mode": "AGRESIVO",
    "profiles": {
        "enterprise_scale_4_sources": {
            "description": "IT-7 + Trusted Sources (RUES, SUPERSOCIEDADES)",
            # ─── PARÁMETROS LSH ──────────────────────────────────────────
            "lsh_permutations": 252,
            "lsh_threshold": 0.58,
            "lsh_ngram": 2,
            # ─── ✅ TRUSTED SOURCES (Paso 1.6 — CORREGIDO) ──────────────
            # RUES y SUPERSOCIEDADES: fuentes maestras, únicas por definición.
            # NO se comparan internamente → elimina ~95% de candidatos.
            # SÍ se cruzan con CRM y EXPORTACIONES normalmente.
            "cross_source_only": False,
            "trusted_unique_sources": ["RUES", "SUPERSOCIEDADES"],
            # ─── MEMORIA Y VELOCIDAD ─────────────────────────────────────
            "force_disk_results": True,
            "memory_threshold_candidates": 1_000_000,
            # ─── TAMAÑOS DE BATCH ────────────────────────────────────────
            "batch_size": 200_000,
            "lsh_batch_size": 75_000,
            "lsh_chunk_size": 200_000,
            "scoring_batch_size": 100_000,
            "clustering_batch_size": 200_000,
            "golden_chunk_size": 150_000,
            "correlative_chunk_size": 150_000,
            # ─── SCORING ─────────────────────────────────────────────────
            "score_threshold": 0.40,
            "min_name_similarity": 0.25,
            "max_nit_distance": 2,
            # ─── SISTEMA ─────────────────────────────────────────────────
            "aggressive_gc": True,
            "max_memory_gb": 11.0,
            "use_disk_cache": True,
            "memory_monitor_interval": 20_000,
            "sqlite_cache_size": -3000000,
            "sqlite_batch_size": 100_000,
            "commit_interval": 400_000,
            # ─── PESOS (Paso 1.4: fonético=0 → redistribuido) ───────────
            "weights": {"name": 0.50, "nit": 0.50, "phonetic": 0.00},
            "confidence_weights": {
                "source_priority": 0.40,
                "nit_consistency": 0.35,
                "name_consistency": 0.15,
                "source_count": 0.10,
            },
            "remove_top_words": 35,
            "max_sources_per_group": 4,
            "min_sources_for_golden": 1,
            "cross_source_validation": True,
            "source_quality_weights": {
                "RUES": 0.99,
                "SUPERSOCIEDADES": 0.90,
                "EXPORTACIONES": 0.80,
                "CRM": 0.60,
            },
        }
    },
    "min_nit_length": 1,
    "max_nit_length": 20,
    "remove_test_data": False,
    "remove_invalid_nits": False,
    "validation_rules": {
        "min_nit_length": 1,
        "max_nit_length": 20,
        "min_name_length": 3,
        "max_name_length": 500,
        "remove_test_data": False,
        "remove_invalid_nits": False,
        "validate_cross_sources": True,
        "min_confidence_export": 0.60,
    },
    "export_settings": {
        "excel_max_rows": 800_000,
        "csv_compression": "gzip",
        "parquet_compression": "snappy",
        "include_diagnostics": True,
        "export_chunk_size": 50_000,
        "split_large_exports": False,
        "max_file_size_mb": 500,
    },
    "performance_settings": {
        "enable_profiling": True,
        "log_memory_usage": True,
        "save_intermediate_results": True,
        "checkpoint_interval": 500_000,
        "performance_log_interval": 100_000,
        "memory_warning_threshold": 7.0,
        "auto_cleanup_temp": True,
    },
}


def crear_config_orchestrator(
    perfil: str = "produccion_estandar", workspace: str | None = None, **overrides
) -> dict[str, Any]:
    """
    Crea configuración completa para el Orchestrator.

    Args:
        perfil: Nombre del perfil base (de PERFILES_BASE)
        workspace: Directorio de trabajo (se genera si no se proporciona)
        **overrides: Parámetros para sobrescribir del perfil

    Returns:
        Dict con configuración completa lista para Orchestrator

    Example:
        config = crear_config_orchestrator(
            perfil='produccion_estandar',
            lsh_threshold=0.50  # Override específico
        )
    """
    # Validar perfil
    if perfil not in PERFILES_BASE:
        perfiles_disponibles = ", ".join(PERFILES_BASE.keys())
        raise ValueError(
            f"❌ Perfil '{perfil}' no existe.\n   Perfiles disponibles: {perfiles_disponibles}"
        )

    # Obtener perfil base
    perfil_config = PERFILES_BASE[perfil].copy()

    # Aplicar overrides
    if overrides:
        # Validar claves permitidas
        claves_validas = set(perfil_config.keys())
        claves_override = set(overrides.keys())
        claves_invalidas = claves_override - claves_validas

        if claves_invalidas:
            print(f"⚠️ Parámetros desconocidos ignorados: {claves_invalidas}")

        # Aplicar solo claves válidas
        for clave, valor in overrides.items():
            if clave in claves_validas:
                perfil_config[clave] = valor

    # Generar workspace si no se proporciona
    if workspace is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        workspace = f"z_workspace_{perfil}_{timestamp}"

    # Construir configuración completa
    config = {
        "profile": perfil,
        "output_directory": workspace,
        "linkage_engine_class": "disk_based",
        "source_priorities": obtener_prioridades_fuentes(),
        "profiles": {perfil: perfil_config},
    }

    return config
