> ## 📌 Nota de versionamiento (post 2026-05-26)
>
> Este documento fue escrito cuando la versión se llamaba **`v3.2.4`**.
> Tras el re-versionamiento del 2026-05-26, esta versión corresponde
> ahora a **`v0.3.0`**. Las referencias internas a `v3.2.4` se preservan
> como traza histórica fiel. Ver [`CHANGELOG.md`](../CHANGELOG.md) para
> tabla completa de equivalencia.

# Auditoría Fase 1 — `rues-linker` v3.2.4

**Fecha:** 2026-05-25 · **Versión origen:** v3.2.3 · **Versión destino:** v3.2.4

## Resumen ejecutivo

Esta release entrega tres cambios sustantivos verificados empíricamente contra `ground_truth_grande.csv` (12,427 registros, 3,486 grupos verdad, 5 fuentes):

| Cambio | Tipo | Impacto medido |
|---|---|---|
| Nuevo perfil `produccion_calibrada` | Feature | **F1: 0.05 → 0.84 (+79 puntos), FP: 747k → 0** |
| Flag `nit_empty_passes_filter` en scorer | Bug fix opt-in | Aislado: FP 747k → 15 manteniendo umbrales IT-7 |
| Lista `DEAD_CONFIG_KEYS` + `validar_config` | Observabilidad | Detecta 12 parámetros sin efecto en `Orchestrator.run()` |

**Retrocompatibilidad:** garantizada. 331/331 tests pasan, incluidos los 17 tests críticos de scoring y NIT.

---

## 1. Hallazgo crítico — el problema real NO era lo que parecía

En análisis previos diagnostiqué que faltaban parámetros (`source_quality_weights`, `confidence_weights`, etc.). **Eso era cierto pero irrelevante** — el código NO los lee. El verdadero problema estaba en los umbrales del scorer:

| Métrica | IT-7 default | Perfil calibrado | Diferencia |
|---|---:|---:|---|
| `score_threshold` | 0.40 | 0.60 | +50% |
| `min_name_similarity` | 0.25 | 0.65 | +160% |
| `max_nit_distance` | 2 | 0 | Estricto |
| `nit_empty_passes_filter` | True (heredado) | False | Fix bug |
| **F1** | **0.05** | **0.84** | **+79 puntos** |
| **Precision** | 0.026 | 1.000 | +97 puntos |
| **Recall** | 0.91 | 0.73 | -18 puntos (aceptable) |
| **False Positives** | 746,954 | 0 | -100% |

---

## 2. Bug encontrado: NIT vacío pasa filtro silenciosamente

**Localización:** `src/record_linkage/engine/scorer.py` línea 1166

**Descripción:** la función `_calculate_nit_distances_vectorized` devuelve `-1` cuando uno de los NITs del par está vacío. El filtro era:

```python
# Antes (v3.2.3)
nit_filter_mask = nit_distances <= self.max_nit_distance
```

Con `max_nit_distance=2`, los pares con `-1` pasan (porque `-1 <= 2`). Esto significa que **dos registros sin NIT pasan el filtro NIT solo por nombre** — caso típico de importadores extranjeros o personas naturales sin RUT.

**Fix v3.2.4:**

```python
# Después (v3.2.4) — comportamiento configurable
if self.nit_empty_passes_filter:
    nit_filter_mask = nit_distances <= self.max_nit_distance
else:
    nit_filter_mask = (nit_distances >= 0) & (nit_distances <= self.max_nit_distance)
```

**Default:** `True` (mantiene comportamiento previo para no romper pipelines existentes).
**Recomendado:** `False` (activado en perfil `produccion_calibrada`).

---

## 3. Lista verificada de dead code (`DEAD_CONFIG_KEYS`)

Verificado con `grep -rn "\.get(.<param>.\|config\[.<param>.\]" src/`:

| Parámetro | Lecturas | Veredicto |
|---|---:|---|
| `confidence_weights` | 0 | 🪦 Dead |
| `max_sources_per_group` | 0 | 🪦 Dead |
| `min_sources_for_golden` | 0 | 🪦 Dead |
| `cross_source_validation` | 0 | 🪦 Dead (existe `cross_source_only` que sí funciona) |
| `validation_rules` | 0 | 🪦 Dead |
| `performance_settings` | 0 | 🪦 Dead |
| `min_confidence_export` | 0 | 🪦 Dead |
| `memory_monitor_interval` | 0 | 🪦 Dead |
| `sqlite_cache_size` | 0 | 🪦 Dead |
| `commit_interval` | 0 | 🪦 Dead |
| `correlative_chunk_size` | 0 | 🪦 Dead |
| `aggressive_gc` | 0 | 🪦 Dead |
| `source_quality_weights` | 2 | ⚠️ Parcial (solo KEYS, no valores) |
| `export_settings` | 1 | ⚠️ Parcial (solo `excel_max_rows`) |

**Estos parámetros NO se eliminaron del `config_produccion_it7` para preservar retrocompatibilidad.** El validador los detecta y avisa.

---

## 4. Cómo usar el nuevo perfil

### Vía API (recomendado)

```python
from record_linkage.config import crear_config_orchestrator
from record_linkage.pipeline.orchestrator import Orchestrator

cfg = crear_config_orchestrator(perfil="produccion_calibrada", workspace="/path/to/output")
# El validador audita automáticamente y reporta dead code

orch = Orchestrator(config=cfg, sources=fuentes, work_dir=cfg["output_directory"])
result = orch.run()
```

### Vía dict manual (override de cualquier valor)

```python
cfg = {
    "profile": "mi_calibracion",
    "linkage_engine_class": "disk_based",
    "cleaning_mode": "AGRESIVO",
    "profiles": {
        "mi_calibracion": {
            "lsh_threshold": 0.58,
            "score_threshold": 0.60,        # ← clave para precision
            "min_name_similarity": 0.65,    # ← clave para precision
            "max_nit_distance": 0,           # ← NIT idéntico
            "nit_empty_passes_filter": False,  # ← v3.2.4 fix
            "weights": {"name": 0.50, "nit": 0.50, "phonetic": 0.00},
            "trusted_unique_sources": ["RUES", "SUPERSOCIEDADES"],
            # ... otros params ...
        }
    },
}
```

### Auditar tu config existente

```python
from record_linkage.config import validar_config

reporte = validar_config(mi_config_actual, verbose=True)
# Imprime:
#   ⚠️  CONFIG WARNING: el config contiene claves que el código NO LEE:
#      🪦 profiles.X.confidence_weights  (dead code, sin efecto)
#      🪦 profiles.X.max_sources_per_group  (dead code, sin efecto)
#      ...
print(f"Dead: {reporte['dead']}")
print(f"Partial: {reporte['partial']}")
```

---

## 5. Validación end-to-end (reproducible)

Resultados verificados contra `ground_truth_grande.csv` (12,427 filas):

```
Configuración                                  F1        P        R         FP
──────────────────────────────────────────────────────────────────────────────
IT-7 default                               0.0508   0.0262   0.9088    746,954
IT-7 + nit_empty_passes_filter=False       0.8422   0.9991   0.7279         15
produccion_calibrada                       0.8424   1.0000   0.7277          0
```

**Comando para reproducir:**

```bash
pytest tests/test_fase1_calibracion.py -v
```

**14/14 tests Fase 1 + 317/317 tests existentes = 331/331 PASAN.**

---

## 6. Lo que falta (Fases 2+)

Esta release es **Fase 1**. Lo pendiente:

### 🔴 Pendiente para Fase 2 (~1-2 semanas)

1. **Implementar `source_quality_weights` con valores numéricos reales.**
   - Hoy: en `golden/selector.py` solo se usa el orden de las keys.
   - Fase 2: usar los valores (RUES=0.99, etc.) como factor de confianza en la elección del representante.

2. **Eliminar dead code de `PERFILES_BASE` (NO de `config_produccion_it7`).**
   - Mantener `config_produccion_it7` por retrocompat documental.
   - Limpiar `produccion_estandar`, `produccion_exhaustiva`, `alta_precision` de claves muertas.

3. **Implementar `max_sources_per_group` en clusterer.**
   - Útil para evitar mega-clusters.

### 🟡 Pendiente para Fase 3 (~1 semana)

4. **Conectar Optuna al `Orchestrator`.**
   - Hoy `HyperparameterOptimizer` trabaja con `linkage_pipeline.run()`, no con `Orchestrator.run()`.
   - Crear `OrchestratorOptimizer` en `evaluation/orchestrator_hyperparameters.py`.

5. **Refinar perfiles auxiliares.**
   - `alta_precision` debería usar parámetros de `produccion_calibrada` como base.
   - `produccion_exhaustiva` necesita test contra GT.

### 🟢 Pendiente para Fase 4 (~3 días)

6. **Limpiar warnings de reportes opcionales.**
   - `ReportGenerator`, `DataVisualizer`, `ExecutiveDashboard`, `EnhancedReportingSuite` no se instalan por default.
   - Silenciar warnings cuando el extra `[viz]` no está instalado.

7. **Documentación de usuario:**
   - Sección en README "Cómo calibrar" con ejemplos del GT.
   - Documentar el bug NIT vacío y la mitigación.

---

## 7. Confrontación honesta

**Lo que asumí mal antes:** dije que el problema era "9 parámetros faltantes". Era cierto que faltaban, pero el experimento A vs B mostró que su presencia no movía F1. **El verdadero problema era `score_threshold=0.40`**, que estaba dejando pasar pares basura.

**Lo que tomó dos corridas tuyas de Colab descubrir:** la calibración correcta son tres umbrales más estrictos + un flag de NIT vacío. Esto se podría haber medido el día 1 con el ground truth. Demoré 4 turnos en llegar acá.

**Lo que NO está garantizado:** que el perfil `produccion_calibrada` produzca métricas similares en las 4 fuentes reales de producción (1.97M registros). El GT tiene 12k registros y patrones distintos. **Antes de promover a producción debes correr el perfil contra las 4 fuentes reales y muestrear manualmente.**

---

**Confianza en este entregable: ALTO (~95%).**

Justificación: 331/331 tests pasan, métricas reproducibles contra GT real, retrocompatibilidad preservada (IT-7 default sigue dando los mismos resultados que en v3.2.3). El 5% de incertidumbre es porque el GT (12k filas) no es predictor perfecto de las 4 fuentes reales (1.97M).
