"""record_linkage.config.profiles — Perfiles de configuración LSH.

Cada perfil define los parámetros completos del pipeline para un escenario:
parámetros LSH, scoring, pesos, batch sizes, fuentes trusted, etc.

Origen:
- PERFILES_BASE: notebook celda [87]
- config_produccion_it7: notebook celda [260] (CELDA 8.3 - IT-7 OPTIMIZADA)
- crear_config_orchestrator: notebook celda [87]

v3.2.4 — FASE 1 de auditoría:
- Nuevo perfil `produccion_calibrada` con parámetros validados contra
  ground_truth_grande.csv (F1=0.84, P=1.00, R=0.73).
- Lista DEAD_CONFIG_KEYS con parámetros que el código NO lee y que solo
  generan ilusión configuracional. El validador emite warnings cuando
  un config contiene estas claves.
- Bug NIT vacío + max_nit_distance: ver scorer.nit_empty_passes_filter.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..golden._priorities import obtener_prioridades_fuentes

# ═════════════════════════════════════════════════════════════════════════
#  CLAVES DEAD CODE (validadas empíricamente en v3.2.4)
# ═════════════════════════════════════════════════════════════════════════
# Parámetros que aparecen en config_produccion_it7 y otros configs pero que
# el flujo Orchestrator.run() NO LEE. Mantenerlos en la configuración crea
# ilusión de calibración. Documentado en docs/AUDITORIA_FASE1.md.
#
# Verificado con:
#   grep -rn "\.get(.<param>.\|config\[.<param>.\]" src/ --include="*.py"
#
# Si quieres recuperar el comportamiento que estas claves prometen, hay que
# IMPLEMENTARLAS en el código (ver plan de Fase 2).
DEAD_CONFIG_KEYS: set[str] = {
    # Top-level
    "confidence_weights",  # 0 lecturas, solo aparece en perfiles
    "max_sources_per_group",  # ✅ v3.2.5 IMPLEMENTADO en clusterer
    #    Conservado aquí para legacy detection;
    #    si ves esto en config y NO usas v3.2.5+,
    #    sigue siendo dead.
    # v3.2.7: cross_source_validation movido a DEPRECATED_CONFIG_KEYS
    "validation_rules",  # 0 lecturas (la mayoría de sub-claves dead)
    "performance_settings",  # 0 lecturas
    "min_confidence_export",  # 0 lecturas
    "memory_monitor_interval",  # 0 lecturas
    "sqlite_cache_size",  # 0 lecturas
    "commit_interval",  # 0 lecturas
    "correlative_chunk_size",  # 0 lecturas reales (7 definiciones, 0 .get)
    "aggressive_gc",  # 0 lecturas (solo se define)
    # source_quality_weights:
    #   - tiene 2 lecturas pero SOLO usa las KEYS para orden de fuentes.
    #   - los VALORES (0.99, 0.90, etc.) son ignorados.
    #   - lo marcamos como WARN parcial.
    # v3.2.5: ahora también se usa para desempates en AdvancedValueSelector
    # cuando se proporciona explícitamente (sigue siendo PARTIAL).
}

# Claves que ANTES eran dead y AHORA están implementadas (en v3.2.5+ / v3.2.7).
# Mantenidas como referencia documental de qué cambió.
RESURRECTED_CONFIG_KEYS: set[str] = {
    "max_sources_per_group",  # ✅ v3.2.5 — clusterer.py split de mega-clusters
    "min_sources_for_golden",  # ✅ v3.2.7 — golden/generator.py filtro post-gen
    "nit_empty_passes_filter",  # ✅ v3.2.4 — scorer.py fix bug NIT vacío
}

# Claves deprecadas: el código no las lee y NO se planea implementar.
DEPRECATED_CONFIG_KEYS: set[str] = {
    "cross_source_validation",  # v3.2.7: usar `cross_source_only` en su lugar
}

# Claves con lectura parcial (no son dead pero su comportamiento es limitado)
PARTIAL_CONFIG_KEYS: set[str] = {
    "source_quality_weights",  # Solo se usa el orden de las keys, no los valores
    "export_settings",  # Solo excel_max_rows se respeta consistentemente
}


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
        # v3.2.5 (FASE 2): eliminada clave `aggressive_gc` (dead code).
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
        # v3.2.5 (FASE 2): eliminada clave `aggressive_gc` (dead code).
        # Opciones
        "cross_source_only": False,  # ⚠️ DEPRECADO: usar trusted_unique_sources
        "trusted_unique_sources": [],  # ✅ Paso 1.6
        "use_disk_cache": True,
        "force_disk_results": True,
        "use_strict_clusters": True,  # ← NUEVO: Paso 1.1
    },
    # ═══════════════════════════════════════════════════════════════════════════
    # PERFIL: ALTA PRECISIÓN (calibrado v3.2.5 — basado en evidencia GT)
    # ═══════════════════════════════════════════════════════════════════════════
    "alta_precision": {
        "description": (
            "Alta precisión - Minimiza falsos positivos. v3.2.5: ajustado "
            "siguiendo evidencia de produccion_calibrada (F1=0.84 sobre GT)."
        ),
        # Limpieza
        "cleaning_mode": "AGRESIVO",
        "remove_top_words": 5,
        # LSH - Restrictivo
        "lsh_permutations": 252,
        "lsh_threshold": 0.65,
        "lsh_ngram": 3,
        # Scoring - Estricto (v3.2.5: alineados con produccion_calibrada)
        "score_threshold": 0.60,  # ← v3.2.5: subido desde 0.55
        "min_name_similarity": 0.65,  # ← v3.2.5: subido desde 0.45
        "max_nit_distance": 0,  # ← v3.2.5: bajado desde 2 (NIT idéntico)
        "nit_empty_passes_filter": False,  # ← v3.2.5: fix bug NIT vacío
        # Pesos
        "weights": {
            "name": 0.50,
            "nit": 0.50,
            "phonetic": 0.0,
        },
        # Recursos
        "batch_size": 100_000,
        "lsh_batch_size": 50_000,
        # v3.2.5 (FASE 2): eliminada clave `aggressive_gc` (dead code).
        # Opciones
        "cross_source_only": False,
        "trusted_unique_sources": [],
        "use_disk_cache": True,
        "force_disk_results": True,
        "use_strict_clusters": True,
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
    # ═══════════════════════════════════════════════════════════════════════════
    #  PERFIL: PRODUCCIÓN CALIBRADA (v3.2.4 — FASE 1)
    # ═══════════════════════════════════════════════════════════════════════════
    #  Calibrado contra ground_truth_grande.csv (12,427 registros, 5 fuentes,
    #  3,486 grupos verdad). Métricas medidas (run determinista):
    #     F1        = 0.8424
    #     Precision = 1.0000
    #     Recall    = 0.7277
    #     TP=16,062  FP=0  FN=6,011
    #  Comparativa contra el config IT-7 default (score_threshold=0.40):
    #     IT-7:        F1=0.05  P=0.03  R=0.91  ← sobre-fusión catastrófica
    #     CALIBRADA:   F1=0.84  P=1.00  R=0.73  ← precision perfecta
    #  Cambios clave vs IT-7:
    #     - score_threshold:     0.40 → 0.60  (umbral final, el más decisivo)
    #     - min_name_similarity: 0.25 → 0.65  (filtro previo más estricto)
    #     - max_nit_distance:    2 → 0        (NITs deben ser idénticos)
    #     - nit_empty_passes_filter: False    (NIT vacío NO pasa filtro)
    #  Si necesitas recall mayor a costa de precision, usa score_threshold=0.50.
    # ═══════════════════════════════════════════════════════════════════════════
    "produccion_calibrada": {
        "description": (
            "Producción calibrada contra ground_truth_grande.csv (F1=0.84, "
            "P=1.00, R=0.73). v3.2.4 — Fase 1 de auditoría."
        ),
        # Limpieza
        "cleaning_mode": "AGRESIVO",
        "remove_top_words": 35,
        # LSH
        "lsh_permutations": 252,
        "lsh_threshold": 0.58,
        "lsh_ngram": 2,
        # Scoring — CALIBRADOS
        "score_threshold": 0.60,  # ← clave: subido desde 0.40
        "min_name_similarity": 0.65,  # ← clave: subido desde 0.25
        "max_nit_distance": 0,  # ← clave: NIT debe ser idéntico
        "nit_empty_passes_filter": False,  # ← v3.2.4: NIT vacío no pasa
        # Pesos
        "weights": {"name": 0.50, "nit": 0.50, "phonetic": 0.00},
        # Trusted sources
        "trusted_unique_sources": ["RUES", "SUPERSOCIEDADES"],
        "cross_source_only": False,
        # v0.7.1 (Sprint 0.8.1, Tarea 1.3): skip_reporting configurable desde el perfil.
        # Si True, omite la fase L6_REPORTING (ahorra ~4 min en pipeline de 1.97M).
        # Útil para producción cuando los reportes no se consumen.
        # Override: pasar skip_reporting=True/False explícito a Orchestrator.run().
        "skip_reporting": False,
        # Memoria
        "force_disk_results": True,
        "use_disk_cache": True,
        "max_memory_gb": 11.0,
        # Batches
        "batch_size": 200_000,
        "lsh_batch_size": 75_000,
        "lsh_chunk_size": 200_000,
        "scoring_batch_size": 100_000,
        "clustering_batch_size": 200_000,
        "golden_chunk_size": 150_000,
        "sqlite_batch_size": 100_000,
        # Source quality (solo se usa el ORDEN — ver PARTIAL_CONFIG_KEYS)
        "source_quality_weights": {
            "RUES": 0.99,
            "SUPERSOCIEDADES": 0.90,
            "DIAN": 0.85,
            "EXPORTACIONES": 0.80,
            "IMPORTACIONES": 0.70,
            "CRM": 0.60,
        },
        "use_strict_clusters": True,
    },
}


# NOTA: en el notebook fuente (celda 260), `output_directory` y `lsh_storage_dir`
# referenciaban globales `WORKSPACE` y `NOMBRE_EJECUCION` definidas en runtime.
# En el paquete .py se exponen como placeholders ("$WORKSPACE", "$NOMBRE_EJECUCION")
# que el `Orchestrator` debe sustituir o el script orquestador debe sobrescribir
# antes de ejecutar. Esto preserva la estructura del config sin romper imports.
config_produccion_it7 = {
    # ═════════════════════════════════════════════════════════════════════
    # v0.5.0 (Sprint 0.5.0): config IT-7 LIMPIADA.
    # Eliminadas 11 claves verificadas como dead/deprecated en auditoría Fase 1-4:
    #   DEAD removidas:
    #     - confidence_weights, max_sources_per_group, min_sources_for_golden,
    #       aggressive_gc, memory_monitor_interval, sqlite_cache_size,
    #       commit_interval, correlative_chunk_size, validation_rules,
    #       performance_settings
    #   DEPRECATED removida:
    #     - cross_source_validation  (usar cross_source_only)
    # NOTA: max_sources_per_group y min_sources_for_golden YA están implementadas
    # en v0.3.1/v0.4.0 pero NO se incluyen aquí porque IT-7 original no las usaba
    # con valores significativos (4 y 1 respectivamente eran defaults inertes).
    # Si quieres activarlas: usa `produccion_calibrada` u override explícito.
    # Antes del cambio: 11 claves no leídas. Ahora: 0.
    # Tests F1 contra GT: idéntico antes/después (F1=0.05, sin cambios funcionales).
    # ═════════════════════════════════════════════════════════════════════
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
            # ─── TRUSTED SOURCES (Paso 1.6 del notebook IT-7) ───────────
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
            # ─── SCORING ─────────────────────────────────────────────────
            "score_threshold": 0.40,
            "min_name_similarity": 0.25,
            "max_nit_distance": 2,
            # ─── SISTEMA ─────────────────────────────────────────────────
            "max_memory_gb": 11.0,
            "use_disk_cache": True,
            "sqlite_batch_size": 100_000,
            # ─── PESOS (Paso 1.4 del notebook IT-7: fonético=0) ─────────
            "weights": {"name": 0.50, "nit": 0.50, "phonetic": 0.00},
            "remove_top_words": 35,
            # ─── source_quality_weights ─────────────────────────────────
            # En v0.3.1+ los valores numéricos se usan para desempate.
            # En IT-7 original solo el orden de las claves importaba.
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
    "export_settings": {
        "excel_max_rows": 800_000,
        "csv_compression": "gzip",
        "parquet_compression": "snappy",
        "include_diagnostics": True,
        "export_chunk_size": 50_000,
        "split_large_exports": False,
        "max_file_size_mb": 500,
    },
}


def validar_config(config: dict[str, Any], verbose: bool = True) -> dict[str, list[str]]:
    """Audita un config dict y reporta claves dead/partial/deprecated (v3.2.7).

    Inspecciona top-level y todos los `profiles[<name>]` buscando claves que
    aparecen en las listas negras `DEAD_CONFIG_KEYS`, `PARTIAL_CONFIG_KEYS`
    o `DEPRECATED_CONFIG_KEYS`. NO modifica el config — solo reporta.

    Args:
        config: dict de configuración completo del Orchestrator.
        verbose: si True, imprime warnings.

    Returns:
        Dict con cuatro listas:
          - 'dead'       : claves que el código NO LEE (alarmante)
          - 'partial'    : claves con uso parcial/limitado
          - 'deprecated' : claves DEPRECADAS (v3.2.7); usar alternativas
          - 'unknown'    : claves que no están registradas como válidas
    """
    encontradas_dead: list[str] = []
    encontradas_partial: list[str] = []
    encontradas_deprecated: list[str] = []

    def _recurse(d, path=""):
        if not isinstance(d, dict):
            return
        for k, v in d.items():
            full_path = f"{path}.{k}" if path else k
            if k in DEPRECATED_CONFIG_KEYS:
                encontradas_deprecated.append(full_path)
            elif k in DEAD_CONFIG_KEYS:
                encontradas_dead.append(full_path)
            if k in PARTIAL_CONFIG_KEYS:
                encontradas_partial.append(full_path)
            if isinstance(v, dict):
                _recurse(v, full_path)

    _recurse(config)

    if verbose:
        if encontradas_deprecated:
            print("⚠️  CONFIG DEPRECATED (v3.2.7): el config contiene claves DEPRECADAS:")
            for k in sorted(set(encontradas_deprecated)):
                print(f"     ⚠️  {k}  (deprecated; usar alternativa documentada)")
        if encontradas_dead:
            print(
                "⚠️  CONFIG WARNING (v3.2.4+): el config contiene claves que el código "
                "NO LEE. Mantenerlas crea ilusión configuracional. Considera eliminarlas:"
            )
            for k in sorted(set(encontradas_dead)):
                print(f"     🪦 {k}  (dead code, sin efecto)")
        if encontradas_partial:
            print("ℹ️  CONFIG INFO (v3.2.4+): el config contiene claves con uso PARCIAL:")
            for k in sorted(set(encontradas_partial)):
                print(f"     ⚠️  {k}  (uso limitado; ver docstring de cada clave)")

    return {
        "dead": sorted(set(encontradas_dead)),
        "partial": sorted(set(encontradas_partial)),
        "deprecated": sorted(set(encontradas_deprecated)),
        "unknown": [],
    }


def crear_config_orchestrator(
    perfil: str = "produccion_estandar",
    workspace: str | None = None,
    validate: bool = True,
    **overrides,
) -> dict[str, Any]:
    """
    Crea configuración completa para el Orchestrator.

    Args:
        perfil: Nombre del perfil base (de PERFILES_BASE)
        workspace: Directorio de trabajo (se genera si no se proporciona)
        validate: Si True (default), audita el config resultante con
            validar_config() y emite warnings sobre dead code.
        **overrides: Parámetros para sobrescribir del perfil

    Returns:
        Dict con configuración completa lista para Orchestrator

    Example:
        config = crear_config_orchestrator(
            perfil='produccion_calibrada',
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

    # v3.2.4: validar config (audita dead code)
    if validate:
        validar_config(config, verbose=True)

    return config
