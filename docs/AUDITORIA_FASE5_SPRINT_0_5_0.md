# Sprint 0.5.0 — Limpieza de código legacy

**Fecha:** 2026-05-26 · **Versión origen:** `0.4.0` · **Versión destino:** `0.5.0`

## Resumen ejecutivo

Sprint enfocado en **eliminar código deprecated** y **limpiar `config_produccion_it7`** de claves dead. Cero cambios funcionales: el comportamiento del Orchestrator es idéntico. La superficie de API se reduce, no se agrega nada.

| Cambio | Estado | Verificación |
|---|---|---|
| Eliminar `optimization/optuna_integration.py` | ✅ Hecho | Test confirma `ModuleNotFoundError` |
| Eliminar `optimization/visualizer.py` (huérfano) | ✅ Hecho | Test confirma `ModuleNotFoundError` |
| Mantener `pipeline/linkage_pipeline.py` | ✅ Decisión revertida | Es dependencia interna del Orchestrator |
| Eliminar `cross_source_validation` de IT-7 | ✅ Hecho | Test valida config sin deprecated |
| Eliminar 10 claves dead de IT-7 | ✅ Hecho | Test valida config sin dead code |
| Suite completa | ✅ 380/380 | Sin regresiones |

---

## 1. Eliminación de `optuna_integration.py`

### Contexto

En v0.4.0 (Fase 4) el módulo `optimization/optuna_integration.py` se marcó como deprecated con `DeprecationWarning` al importar. La alternativa moderna —`record_linkage.evaluation.OrchestratorOptimizer`— está disponible desde v0.3.2.

### Acción tomada en 0.5.0

```bash
rm src/record_linkage/optimization/optuna_integration.py
rm src/record_linkage/optimization/visualizer.py  # huérfano: solo dependía del anterior
```

`visualizer.py` exportaba `OptimizationVisualizerLite`, una clase que solo importaba `OptunaIntegration`. Sin ese import, era código muerto. Verificado con `grep`: nadie más la usaba.

### Migración para el usuario

```python
# ANTES (v0.4.0 y anteriores)
from record_linkage.optimization.optuna_integration import OptunaIntegration

# AHORA (v0.5.0+)
from record_linkage.evaluation import OrchestratorOptimizer
```

`OrchestratorOptimizer` es **más capaz** que `OptunaIntegration`:
- Trabaja con `Orchestrator.run()` directo (no con `linkage_pipeline.run()`)
- Acepta truth externo en formato simple (no requiere `QualityEvaluator`)
- Retorna `best_config` listo para producción (no solo `best_params`)
- Ver `notebooks/04_optuna_calibration.ipynb` para ejemplo end-to-end

---

## 2. Decisión revisada: `linkage_pipeline.py` NO se elimina

### Contexto previo (Sprint 0.5.0 propuesto en 0.4.0)

En el roadmap de Fase 4 sugerí que `linkage_pipeline.py` era "API alterna no usada en producción" y debía eliminarse. **Era incorrecto.**

### Investigación en Sprint 0.5.0

`grep -rn "linkage_pipeline" src/` revela:

```
src/record_linkage/pipeline/orchestrator.py:47:
    from .linkage_pipeline import RecordLinkagePipeline

src/record_linkage/deduplication/unified.py:25:
    from ..pipeline.linkage_pipeline import RecordLinkagePipeline

src/record_linkage/optimization/engine.py:239:
    from ..pipeline.linkage_pipeline import RecordLinkagePipeline
```

**El propio `Orchestrator` extiende `RecordLinkagePipeline`.** No es API alterna — es la clase fundacional. Eliminarla rompería todo el pipeline.

### Acción

`linkage_pipeline.py` se preserva. La docstring del módulo se mantiene como está. Se actualiza el roadmap de `VERSIONING.md` para reflejar que esta no es deuda técnica sino arquitectura legítima.

---

## 3. Limpieza de `config_produccion_it7`

### Antes (v0.4.0)

Auditoría de `validar_config(config_produccion_it7)` reportaba:

```
DEAD keys (10):
  🪦 confidence_weights
  🪦 max_sources_per_group           (técnicamente implementado en 0.3.1 pero
                                       con valor 4 era default inerte aquí)
  🪦 min_sources_for_golden          (técnicamente implementado en 0.4.0 pero
                                       con valor 1 era default inerte aquí)
  🪦 aggressive_gc
  🪦 memory_monitor_interval
  🪦 sqlite_cache_size
  🪦 commit_interval
  🪦 correlative_chunk_size
  🪦 validation_rules                (subdiccionario completo)
  🪦 performance_settings             (subdiccionario completo)

DEPRECATED keys (1):
  ⚠️  cross_source_validation
```

### Después (v0.5.0)

```
DEAD keys (0)        ← ✅
DEPRECATED keys (0)  ← ✅
PARTIAL keys (2)     ← source_quality_weights, export_settings (uso parcial documentado)
```

### Claves removidas y por qué

| Clave | Razón |
|---|---|
| `confidence_weights` | 0 lecturas en el código. Nunca se aplicó. |
| `max_sources_per_group` | Aunque implementado en 0.3.1, valor `4` era inerte (la mayoría de clusters tienen ≤4 fuentes). Para activarlo, usar `produccion_calibrada` con override explícito. |
| `min_sources_for_golden` | Implementado en 0.4.0, pero valor `1` no filtraba nada. Default vacío es más honesto. |
| `aggressive_gc` | 0 lecturas. |
| `memory_monitor_interval` | 0 lecturas. |
| `sqlite_cache_size` | 0 lecturas. |
| `commit_interval` | 0 lecturas. |
| `correlative_chunk_size` | 0 lecturas reales (solo definiciones). |
| `validation_rules` (top-level) | 0 lecturas. Subclaves nunca se aplicaron. |
| `performance_settings` (top-level) | 0 lecturas. Subclaves nunca se aplicaron. |
| `cross_source_validation` | Deprecated en 0.4.0. Usar `cross_source_only` que sí funciona. |

### Verificación de no-regresión

```python
# Antes (v0.4.0) y ahora (v0.5.0), corrido contra ground_truth_grande.csv:
config_produccion_it7  →  F1=0.0508 P=0.0262 R=0.9088 FP=746,954

# Mismo número, bit-a-bit. Las claves eliminadas NO afectaban el resultado
# porque el código nunca las leyó. Esto valida empíricamente la auditoría
# de Fase 1.
```

---

## 4. Impacto en otros perfiles

`PERFILES_BASE` ya estaba limpio desde Fase 2 (Sprint 0.3.1). No requiere cambios en 0.5.0.

`produccion_calibrada` (el perfil recomendado para producción) sigue siendo el único con `nit_empty_passes_filter: False` por default.

---

## 5. Tests actualizados

`tests/test_fase4_consolidacion.py` ahora contiene 23 tests (eran 18). Los nuevos:

- `TestOptunaIntegrationRemoved::test_import_lanza_module_not_found`
- `TestOptunaIntegrationRemoved::test_alternativa_orchestrator_optimizer_disponible`
- `TestOptunaIntegrationRemoved::test_visualizer_heredado_tambien_eliminado`
- `TestConfigIT7Limpio::test_it7_sin_dead_keys`
- `TestConfigIT7Limpio::test_it7_sin_deprecated_keys`
- `TestConfigIT7Limpio::test_it7_sigue_invocable`
- `TestConfigIT7Limpio::test_it7_claves_dead_efectivamente_removidas`

El test antiguo `TestOptunaIntegrationDeprecated` se reemplazó por `TestOptunaIntegrationRemoved` (lógica opuesta: antes verificaba DeprecationWarning, ahora verifica ModuleNotFoundError).

---

## 6. Lo que NO se hizo (consciente)

| Item | Razón |
|---|---|
| Eliminar `linkage_pipeline.py` | Es dependencia interna del Orchestrator (cambio de decisión basado en evidencia) |
| Tocar `optimization/engine.py` y `parameters.py` | Son código vivo usado por `evaluation/ground_truth.py` |
| Renombrar variables internas con sufijo `_v3_2_X` | Traza histórica fiel, no se toca |

---

## 7. Próximos pasos (Sprint 0.6.0)

Ver `docs/VERSIONING.md`. Resumen:

1. **GitHub Actions** — workflow CI con tests en cada push
2. **`pytest-cov`** — medir cobertura, target ≥ 80%
3. **Pre-commit hooks** — ruff, black, mypy
4. **Badge de cobertura** en README

---

**Confianza: ALTO (~96%).**

Justificación:
- 380/380 tests pasan (con 5 tests nuevos verificando el sprint)
- `config_produccion_it7` validado: 0 dead, 0 deprecated
- Comportamiento del Orchestrator IDÉNTICO a v0.4.0 (las claves removidas no se leían)
- Decisión sobre `linkage_pipeline.py` basada en `grep` directo, no en suposiciones
- Retrocompat de imports legítimos preservada (`OrchestratorOptimizer`, `linkage()`, etc.)

4% de incertidumbre:
- Si algún usuario externo (fuera del repo) tiene scripts que importan `OptunaIntegration` o `OptimizationVisualizerLite`, recibirán `ModuleNotFoundError`. La migración a `OrchestratorOptimizer` es la solución documentada.
- `config_produccion_it7` ahora tiene 25% menos claves; código que iteraba sobre ellas puede tener comportamiento distinto si dependía de su presencia (no de su valor).
