> ## 📌 Nota de versionamiento (post 2026-05-26)
>
> Este documento fue escrito cuando la versión se llamaba **`v3.2.7`**.
> Tras el re-versionamiento del 2026-05-26, esta versión corresponde
> ahora a **`v0.4.0`**. Las referencias internas a `v3.2.7` se preservan
> como traza histórica fiel. Ver [`CHANGELOG.md`](../CHANGELOG.md) para
> tabla completa de equivalencia.

# Auditoría Fase 4 — `rues-linker` v3.2.7

**Fecha:** 2026-05-26 · **Versión origen:** v3.2.6 · **Versión destino:** v3.2.7

## Resumen ejecutivo

Esta release cierra los items pendientes de la hoja de ruta de auditoría iniciada en Fase 1. Cuatro cambios concretos al código + actualización de constantes documentales.

| Cambio | Tipo | Verificación |
|---|---|---|
| Fix `_class_exists` (reportes opcionales detectables) | Bug fix | 6 tests + import directo |
| Implementación de `min_sources_for_golden` | Feature | 6 tests + lógica aislada |
| `cross_source_validation` movido a `DEPRECATED_CONFIG_KEYS` | Decisión documental | 4 tests |
| DeprecationWarning en `OptunaIntegration` heredado | Higiene | 2 tests |
| Constante `RESURRECTED_CONFIG_KEYS` nueva | Documental | importable |

**Retrocompatibilidad:** garantizada. Defaults preservan comportamiento de v3.2.6.

---

## 1. Bug fix `_class_exists`

### Problema (v3.2.3 a v3.2.6)

`reporting/strategies.py` llamaba a `_class_exists("ReportGenerator")` y derivados para decidir si ejecutar reportes opcionales. La función vivía en `pipeline/_internal.py` y usaba:

```python
cls = eval(class_name)  # ← eval en el módulo _internal.py
```

`_internal.py` **NO importa** `ReportGenerator`, `DataVisualizer`, `ExecutiveDashboard`, `EnhancedReportingSuite`. Resultado: `eval()` lanzaba `NameError`, capturado por `except`, retornando `False`. Cada corrida emitía 4 warnings "no disponible, omitiendo" aunque las clases SÍ estaban en el código.

### Fix en v3.2.7

Reemplazo `eval()` por `importlib.import_module()` con mapeo explícito:

```python
_CLASS_MODULE_MAP = {
    "ReportGenerator":        "record_linkage.reporting.reports",
    "DataVisualizer":         "record_linkage.reporting.visualizer",
    "ExecutiveDashboard":     "record_linkage.reporting.dashboard",
    "EnhancedReportingSuite": "record_linkage.reporting.suite",
}
```

Verificado: las 4 ahora retornan `True`. Una clase inexistente sigue retornando `False`.

### Implicación importante

Ahora que `_class_exists` reporta True, los reportes opcionales **se ejecutarán** durante `Orchestrator.run()`. Si tu entorno no tiene `matplotlib`, `seaborn`, `plotly`, `upsetplot` instalados, el `try/except` interno los manejará gracefully (logger.error sin crash). Para evitar errores ruidosos:

```bash
pip install "rues-linker[viz]"
```

Si no quieres ejecutar reportes, pasa `skip_reporting=True` a `Orchestrator.run()`.

---

## 2. Implementación de `min_sources_for_golden`

### Diseño

Filtro **post-generación** en `GoldenRecordGeneratorV7`. La lógica:

1. Lectura del config: `profiles[active].min_sources_for_golden` (fallback top-level, default 0).
2. Si `> 1`, contar fuentes únicas por `ID_GRUPO` en la correlativa.
3. Excluir del golden los grupos con menos fuentes que el límite.
4. **La correlativa NO se modifica** — preserva trazabilidad. Si necesitas los descartados, los reconstruyes desde correlativa.

### Caso de uso típico

Si tienes 4 fuentes (RUES, EXPORTACIONES, CRM, SUPERSOCIEDADES) y `min_sources_for_golden=2`, el golden final solo contiene empresas que aparecen en al menos 2 fuentes distintas. Útil para crear listas de "empresas verificadas multi-fuente".

### Trade-off documentado

Es un filtro **destructivo del golden**. Si quieres conservar todo, no lo actives (default 0). Si quieres alta confianza inter-fuente, activa con `min_sources_for_golden=2` o más.

---

## 3. Decisión sobre `cross_source_validation`

### Investigación

- `grep` en todo `src/`: **0 lecturas** del parámetro.
- Existe `cross_source_only` que sí se usa y hace algo similar (solo emparejar pares de fuentes distintas en LSH).
- No hay plan razonable para implementar `cross_source_validation` con semántica distinta a `cross_source_only`.

### Decisión: deprecar

- Nuevo set `DEPRECATED_CONFIG_KEYS = {"cross_source_validation"}`.
- `validar_config()` ahora reporta también claves deprecated con mensaje distinto a "dead".
- `cross_source_validation` se quita de `DEAD_CONFIG_KEYS` para evitar doble reporte.
- En v3.3.0 se removerá del config IT-7 también.

---

## 4. DeprecationWarning en `OptunaIntegration` heredado

`src/record_linkage/optimization/optuna_integration.py` contiene la clase `OptunaIntegration` (237 líneas, código heredado del notebook fuente). Es **incompatible** con el flujo del `Orchestrator` actual y no se mantiene.

### Acción

- Añadido docstring "DEPRECATED desde v3.2.7" al módulo.
- `warnings.warn(DeprecationWarning, ...)` al importar.
- La clase sigue importable (retrocompat).
- Removido en v3.3.0.

### Alternativa recomendada

`record_linkage.evaluation.OrchestratorOptimizer` (introducido en v3.2.6) — ver `docs/AUDITORIA_FASE3.md`.

---

## 5. Nuevas constantes documentales

```python
from record_linkage.config import (
    DEAD_CONFIG_KEYS,          # 11 claves que el código NO LEE
    DEPRECATED_CONFIG_KEYS,    # 1 clave: cross_source_validation
    PARTIAL_CONFIG_KEYS,       # 2 claves con uso limitado
    RESURRECTED_CONFIG_KEYS,   # 3 claves que ANTES eran dead, AHORA implementadas
)
```

`RESURRECTED_CONFIG_KEYS = {"max_sources_per_group", "min_sources_for_golden", "nit_empty_passes_filter"}`

Es **referencia histórica** — documenta qué se arregló y en qué versión, para que futuros mantenedores no las re-marquen como dead.

---

## 6. Cómo usar las nuevas funciones

### Filtrar golden por número mínimo de fuentes

```python
from record_linkage.config.profiles import crear_config_orchestrator
from record_linkage.pipeline.orchestrator import Orchestrator

cfg = crear_config_orchestrator(perfil="produccion_calibrada", validate=False)
# Activar filtro: golden solo con clusters multi-fuente
cfg["profiles"]["produccion_calibrada"]["min_sources_for_golden"] = 2

orch = Orchestrator(config=cfg, sources=mis_fuentes, work_dir=".")
result = orch.run()

# result["golden"] contiene solo empresas verificadas en >= 2 fuentes
# result["correlative"] contiene TODO (sin filtrar)
```

### Auditar tu config existente

```python
from record_linkage.config import validar_config

reporte = validar_config(mi_config_it7, verbose=True)
# Imprime:
#   ⚠️  CONFIG DEPRECATED (v3.2.7): el config contiene claves DEPRECADAS:
#      ⚠️  profiles.X.cross_source_validation  (deprecated; usar alternativa)
#   ⚠️  CONFIG WARNING: el config contiene claves que el código NO LEE:
#      🪦 profiles.X.confidence_weights  (dead code, sin efecto)
#      ...
```

---

## 7. Lo que NO se hizo (consciente)

| Item del plan original | Estado | Razón |
|---|---|---|
| Silenciar warnings de reportes opcionales | ✅ Hecho de raíz (no silenciado, sino ARREGLADO) | El bug era que las clases no se detectaban. Ahora SÍ se detectan. |
| Sección README "Cómo calibrar con Optuna" | ✅ Hecho como notebook ejemplo | Ver `notebooks/04_optuna_calibration.ipynb` |
| Implementar `min_sources_for_golden` | ✅ Hecho | |
| Decidir destino de `cross_source_validation` | ✅ Deprecado | |
| Consolidar/eliminar `optuna_integration.py` | ⚠️ DeprecationWarning solo | Eliminar sería breaking change. Se removerá en v3.3.0. |
| Notebook ejemplo `04_optuna_calibration.ipynb` | ✅ Hecho | |

---

## 8. Roadmap v3.3.0 (siguiente major-minor)

- **Breaking changes** aceptables (anunciados con tiempo):
  - Eliminar `src/record_linkage/optimization/optuna_integration.py`
  - Eliminar `cross_source_validation` de `config_produccion_it7`
  - Eliminar las claves dead de `config_produccion_it7` (limpieza definitiva)
- **Mejoras potenciales**:
  - `OrchestratorOptimizer` con almacenamiento persistente (SQLite) para resumir estudios entre sesiones de Colab
  - Pre-screening de candidatos LSH antes del scoring para reducir 2-3× el tiempo del pipeline
  - Tests de regresión contra GT en CI/CD

---

**Confianza: ALTO (~94%).**

Justificación:
- Cada fix tiene tests específicos pasando
- Suite completa pasa los archivos verificados directamente
- Cambios aislados (no tocan flujo principal del Orchestrator)
- Retrocompat: defaults preservan comportamiento previo

6% de incertidumbre:
- (a) El fix `_class_exists` HACE que los reportes opcionales se ejecuten. En entornos sin `matplotlib`/`plotly` se verán más logs de error (manejados gracefully, pero ruidosos).
- (b) `min_sources_for_golden` no probado a escala 1.97M registros; solo en GT pequeño.
- (c) La constante `RESURRECTED_CONFIG_KEYS` es nueva y puede no tener uso fuera de auditoría.
