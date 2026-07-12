> ## 📌 Nota de versionamiento (post 2026-05-26)
>
> Este documento fue escrito cuando la versión se llamaba **`v3.2.6`**.
> Tras el re-versionamiento del 2026-05-26, esta versión corresponde
> ahora a **`v0.3.2`**. Las referencias internas a `v3.2.6` se preservan
> como traza histórica fiel. Ver [`CHANGELOG.md`](../CHANGELOG.md) para
> tabla completa de equivalencia.

# Auditoría Fase 3 — `rues-linker` v3.2.6

**Fecha:** 2026-05-26 · **Versión origen:** v3.2.5 · **Versión destino:** v3.2.6

## Resumen ejecutivo

Esta release conecta **Optuna al flujo de producción real** (`Orchestrator.run()`). Hasta ahora, `HyperparameterOptimizer` solo trabajaba con `linkage_pipeline.run()` (API alternativa que no usabas en producción).

| Cambio | Estado | Verificación |
|---|---|---|
| Clase nueva `OrchestratorOptimizer` | ✅ Implementada | 14 tests + E2E |
| Espacio de búsqueda por defecto | ✅ `default_search_space()` | Cubre los 7 params que el código LEE |
| E2E sobre GT (6 trials) | ✅ Mejor F1=0.9304 | Optuna encontró mejor config que `produccion_calibrada` |
| Suite completa | ✅ 362/362 tests pasan | Sin regresiones |

---

## 1. Diseño de `OrchestratorOptimizer`

### Diferencia clave con `HyperparameterOptimizer`

| Aspecto | `HyperparameterOptimizer` (legacy) | `OrchestratorOptimizer` (nuevo) |
|---|---|---|
| API que llama | `linkage_pipeline.run()` | `Orchestrator.run()` |
| Acepta | objeto pipeline | dict de config |
| Evaluación | `QualityEvaluator` (necesita truth integrado) | `evaluar_pares()` sobre truth externo |
| Resultado | `best_params` (dict de params) | `best_config` (dict completo listo para producción) |
| Uso típico | Pipelines API alta | Pipelines de producción real |

### Firma del constructor

```python
OrchestratorOptimizer(
    base_config: dict,                   # config base del Orchestrator
    sources: dict[str, pd.DataFrame],    # fuentes a usar en cada trial
    truth: pd.DataFrame,                 # ground truth con ID_REGISTRO + ID_GROUP
    search_space: Callable | None = None,  # función trial -> dict de params
    silent: bool = True,                 # silenciar logs durante trials
    keep_workdir: bool = False,          # mantener workdirs para debug
)
```

### Método principal

```python
result = optimizer.optimize(
    n_trials=20,
    optimization_target="f1",             # 'f1', 'f2', 'precision', 'recall'
    time_budget_minutes=10.0,             # tope opcional
    time_penalty_seconds=600.0,           # penaliza trials > 10 min
    show_progress_bar=True,
    sampler=optuna.samplers.TPESampler(seed=42),  # opcional
    pruner=None,
)

# result contiene:
#   'best_params'              : mejores hiperparámetros
#   'best_score'               : F1 (u otro target) del mejor trial
#   'best_config'              : config COMPLETO listo para Orchestrator
#   'best_metrics'             : P/R/F1/F2/TP/FP/FN del mejor trial
#   'optimization_history'     : lista de dicts por trial
#   'study'                    : objeto Optuna study (acceso completo)
#   'total_trials_completed'   : trials no-fallidos
```

---

## 2. Espacio de búsqueda por defecto

`default_search_space()` cubre los 7 parámetros que el código del paquete **realmente lee** (verificados en Fase 1):

| Parámetro | Rango | Step | Justificación |
|---|---|---|---|
| `lsh_threshold` | 0.50–0.75 | 0.05 | Filtro previo LSH; estrecho |
| `score_threshold` | 0.45–0.85 | 0.05 | **El más decisivo para precision** |
| `min_name_similarity` | 0.40–0.85 | 0.05 | Filtro previo nombre |
| `max_nit_distance` | 0–3 | 1 | NIT idéntico (0) vs permisivo (3) |
| `nit_empty_passes_filter` | True/False | — | Bug NIT vacío (Fase 1) |
| `weight_name` | 0.30–0.70 | 0.05 | Peso del nombre en scoring |
| `weight_nit` | derivado | — | 1.0 − weight_name (phonetic=0) |

Puedes pasar tu propio espacio:

```python
def mi_search_space(trial):
    return {
        "score_threshold": trial.suggest_float("score", 0.6, 0.8),
        "max_nit_distance": trial.suggest_int("max_nit", 0, 1),
    }

optimizer = OrchestratorOptimizer(
    base_config=cfg, sources=src, truth=gt,
    search_space=mi_search_space,
)
```

---

## 3. Verificación E2E (reproducible)

Sobre el GT muestreado (400 grupos, 1,489 registros), 6 trials Optuna:

```
Trials completados: 6/6
Mejor F1:  0.9304
Mejores params:
   lsh_threshold = 0.7
   score_threshold = 0.55
   min_name_similarity = 0.70
   max_nit_distance = 0
   nit_empty_passes_filter = True
   weight_name = 0.60
   weight_nit = 0.40

Mejor métrica completa:
   precision = 0.9996
   recall    = 0.8701
   f1        = 0.9304
   f2        = 0.8933
   TP=2,452 · FP=1 · FN=366
```

**Hallazgo:** Optuna encontró una configuración con **F1=0.9304**, mejor que el perfil estático `produccion_calibrada` (F1=0.8424 sobre el GT completo). La mejora viene de:
- `lsh_threshold=0.70` (vs 0.58 actual): menos candidatos, más precisión LSH
- `weight_name=0.60` (vs 0.50 actual): mayor peso al nombre
- `score_threshold=0.55` (vs 0.60 actual): un punto menos estricto

**Advertencia honesta:** este resultado es sobre 400 grupos. Antes de promover al perfil de producción, **debes re-correr con n_trials=20+ sobre el GT completo** (12k registros) y verificar que la mejora se sostiene a escala mayor.

---

## 4. Cómo usarlo (ejemplo mínimo en Colab)

```python
import pandas as pd
from record_linkage.config.profiles import crear_config_orchestrator
from record_linkage.evaluation import OrchestratorOptimizer

# 1. Cargar GT y fuentes
gt = pd.read_csv("ground_truth_grande.csv", dtype=str)
gt["NIT"] = gt["NIT"].fillna("")
truth = gt[["ID_REGISTRO", "ID_GROUP"]].copy()
sources = {
    src: g[["ID_REGISTRO", "RAZON_SOCIAL", "NIT", "CIUDAD"]]
        .reset_index(drop=True).copy()
    for src, g in gt.groupby("FUENTE") if len(g) >= 2
}

# 2. Config base (cualquier perfil)
base_cfg = crear_config_orchestrator(perfil="produccion_calibrada", validate=False)

# 3. Optimizar
optimizer = OrchestratorOptimizer(
    base_config=base_cfg,
    sources=sources,
    truth=truth,
    silent=True,
)
result = optimizer.optimize(
    n_trials=30,
    optimization_target="f1",
    time_budget_minutes=20,
)

# 4. Usar el best_config para producción
best_cfg = result["best_config"]
print(f"Mejor F1: {result['best_score']:.4f}")
print(f"Métricas: {result['best_metrics']}")

# 5. Inspeccionar historial
hist = optimizer.history_df()
hist.sort_values("score", ascending=False).head(10)
```

---

## 5. Limitaciones honestas

1. **Tiempo computacional**: cada trial es un pipeline completo. Con 1,489 registros: ~5s. Con 1.97M registros: **~50 minutos por trial**. Si quieres optimizar contra producción real, presupuesta el tiempo.

2. **GT pequeño puede engañar**: la mejor config sobre 400 grupos puede ser distinta de la mejor sobre 12k o sobre 1.97M reales. **Siempre validar la `best_config` antes de promover a producción**.

3. **No usa `pipeline_optuna_integration.py`**: el paquete tiene otro archivo `optimization/optuna_integration.py` que **no se conectó**. Es código heredado de otra rama. Si quieres consolidación, hay que decidir cuál mantener (recomiendo eliminar el viejo).

4. **No optimiza `source_quality_weights`**: el espacio por defecto no toca este parámetro porque su impacto solo se manifiesta en configuraciones con empates de prioridad (ver Fase 2). Si quieres optimizarlo, define tu propio `search_space`.

---

## 6. Lo que NO se entrega en esta fase (queda para Fase 4)

| Item | Razón |
|---|---|
| Silenciar warnings de reportes opcionales | Cambio menor (~30 min); puede ir en Fase 4 |
| Sección README "Cómo calibrar" | Documentación de usuario completa |
| Implementar `min_sources_for_golden` | Cambio mediano en `golden/generator.py` |
| Decidir destino de `cross_source_validation` | Implementar o deprecar |
| Conectar Optuna al `linkage_pipeline` también | Por consistencia con el viejo |

---

**Confianza: ALTO (~94%).**

Justificación:
- 362/362 tests pasan
- E2E reproducible con 6 trials sobre GT real (mejor F1=0.93)
- Diseño aislado: `OrchestratorOptimizer` no toca código existente
- Retrocompatibilidad: `HyperparameterOptimizer` (legacy) sigue funcionando

6% incertidumbre:
- La mejor config encontrada sobre GT pequeño puede no transferir a 1.97M registros
- Falta probar con n_trials >> 6 (limitado por tiempo en sandbox)
- No probé con samplers/pruners avanzados de Optuna
