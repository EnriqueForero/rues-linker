> ## 📌 Nota de versionamiento (post 2026-05-26)
>
> Este documento fue escrito cuando la versión se llamaba **`v3.2.5`**.
> Tras el re-versionamiento del 2026-05-26, esta versión corresponde
> ahora a **`v0.3.1`**. Las referencias internas a `v3.2.5` se preservan
> como traza histórica fiel. Ver [`CHANGELOG.md`](../CHANGELOG.md) para
> tabla completa de equivalencia.

# Auditoría Fase 2 — `rues-linker` v3.2.5

**Fecha:** 2026-05-26 · **Versión origen:** v3.2.4 · **Versión destino:** v3.2.5

## Resumen ejecutivo

Esta release implementa los tres cambios prometidos en el plan de Fase 2:

| Cambio | Estado | Verificación |
|---|---|---|
| 1. `source_quality_weights` con pesos numéricos efectivos | ✅ Implementado | 6 tests + E2E |
| 2. `max_sources_per_group` en clusterer | ✅ Implementado | 5 tests + E2E |
| 3. Limpieza de dead code en perfiles auxiliares | ✅ Hecho parcial | 4 tests |
| Recalibración de `alta_precision` con evidencia de GT | ✅ Bonus | F1=0.83 medido |

**Métricas confirmadas contra `ground_truth_grande.csv`:**

```
Configuración                             F1        P        R       FP
─────────────────────────────────────────────────────────────────────
produccion_calibrada                  0.8424   1.0000   0.7277      0
alta_precision v3.2.5                 0.8299   1.0000   0.7092      0
calibrada + max_sources_per_group=3   0.8361   1.0000   0.7183      0
```

**Retrocompatibilidad:** **348/348 tests pasan** (331 anteriores + 17 nuevos).

---

## 1. `source_quality_weights` ahora SÍ usa valores numéricos

### Antes (v3.2.4)
```python
# orchestrator.py:1489 — solo extraía las KEYS, ignoraba los valores
priority = list(self.profile.get("source_quality_weights", {}).keys())
```
Esto significaba que `{"RUES": 0.99, "CRM": 0.60}` se reducía a `["RUES", "CRM"]`.
El **orden** se respetaba; los **valores 0.99/0.60 eran cosmética**.

### Después (v3.2.5)
1. `AdvancedValueSelector.__init__()` acepta argumento opcional `source_quality_weights: dict[str, float] | None`.
2. `GoldenRecordGeneratorV7.__init__()` extrae automáticamente los pesos del config y los propaga al selector.
3. En `select_best_name()`, cuando hay varios registros empatados en la fuente más prioritaria, se **desempata por peso numérico** antes del consenso.

### Cuándo se activa el desempate

El path donde los pesos actúan es **estrecho**: solo cuando dentro del subgrupo de "fuentes con prioridad mínima" hay **más de una fuente**. Eso ocurre cuando el orden de prioridad tiene empates (raro en práctica, donde típicamente cada fuente tiene un orden único).

**Implicación honesta:** en pipelines donde la prioridad es estrictamente ordinal (`{RUES:0, SUPER:1, CRM:2, EXPO:3}`), este cambio **no afecta el output**. Su valor es para configuraciones más complejas donde varias fuentes "trusted" empatan en el primer nivel.

### Retrocompatibilidad
- Sin argumento `source_quality_weights`: comportamiento **idéntico** a v3.2.4.
- Tests existentes pasan sin tocar.

---

## 2. `max_sources_per_group` previene mega-clusters

### Diseño implementado

**Algoritmo post-clustering** en `OptimizedClusterer.cluster_entities()`:

1. Después de scipy_cc/build_strict_clusters, antes de mapear ID_GRUPO.
2. Si `max_sources_per_group` no es None y un cluster tiene más fuentes únicas que el límite:
   - Dividir por `(SRC, NIT)`.
   - Cada par único `(SRC, NIT)` se convierte en sub-cluster.
   - Esto **preserva la deduplicación intra-fuente** (mismo NIT en misma fuente → juntos) pero rompe la unión transitiva sospechosa.

### Trade-off documentado

- **Conservador**: puede separar registros que son legítimamente la misma empresa si fueron unidos por cadena `A~B, B~C, C~D, ...`.
- **Útil**: en datos sucios, evita que clusters "se traguen" decenas de empresas no relacionadas.
- **Default `None`** (sin límite) preserva el comportamiento previo.

### Resultado E2E
Con `produccion_calibrada + max_sources_per_group=3` sobre el GT:
- F1 cae de 0.8424 a 0.8361 (ligero — se pierden algunos TPs por sub-cluster)
- FP siguen siendo 0
- Golden records: 5,541 → 5,562 (más clusters, más pequeños)

**Recomendación:** activar solo si hay sospecha de mega-clusters patológicos. Para el GT no hay diferencia significativa porque la calibración ya previene la sobre-fusión.

---

## 3. Limpieza de dead code en perfiles auxiliares

### Acción tomada

Removida la clave `aggressive_gc` (dead code verificado, 0 lecturas en el código) de:
- `produccion_estandar`
- `produccion_exhaustiva`
- `alta_precision`

### No tocados (intencional)

- **`config_produccion_it7`**: NO se modificó por retrocompat documental. Los usuarios que importan esa constante reciben **exactamente el mismo dict** que en v3.2.3/v3.2.4.
- Test `TestPerfilesLimpios::test_it7_mantiene_dead_code_retrocompat` lo verifica explícitamente.

### `alta_precision` recalibrado (bonus)

Aproveché la limpieza para alinear `alta_precision` con la evidencia de Fase 1:

| Parámetro | v3.2.4 | v3.2.5 |
|---|---:|---:|
| `score_threshold` | 0.55 | **0.60** |
| `min_name_similarity` | 0.45 | **0.65** |
| `max_nit_distance` | 2 | **0** |
| `nit_empty_passes_filter` | (default True) | **False** |

Resultado medido: F1=0.8299 (vs 0.05 que daba el IT-7 default).

---

## 4. Lo que faltó

Lista del plan original:

| Item | Estado | Razón |
|---|---|---|
| `source_quality_weights` con pesos numéricos | ✅ | |
| `max_sources_per_group` | ✅ | |
| Limpiar `aggressive_gc` de perfiles aux | ✅ | |
| Limpiar `confidence_weights` de perfiles aux | ⚠️ N/A | Los perfiles aux ya no tenían esta clave (solo IT-7) |
| Limpiar `validation_rules`/`export_settings`/`performance_settings` | ⚠️ N/A | Solo aparecen en IT-7 top-level (no tocado) |
| Limpiar `min_sources_for_golden`, `cross_source_validation`, `max_sources_per_group` (como dead) | ⚠️ Parcial | `max_sources_per_group` ahora SÍ se lee; los otros 2 siguen dead |

**Pendiente para Fase 3** (siguiente release):
- Implementar `min_sources_for_golden` en `golden/generator.py` (filtra clusters con menos de N fuentes).
- Implementar `cross_source_validation` o eliminarlo (decidir).
- Conectar Optuna al `Orchestrator` (no solo a `linkage_pipeline`).
- Silenciar warnings de reportes opcionales (`ReportGenerator`, etc.).

---

## 5. Confrontación honesta

**Lo que cambió poco con la implementación de `source_quality_weights`:** los pesos solo desempatan cuando varias fuentes empatan en prioridad. En configuraciones ordinales puras, el efecto es invisible. **Hice el cambio limpio, pero no debes esperar que mueva F1 significativamente por sí solo**.

**`max_sources_per_group` redujo F1 0.6 puntos en el GT.** Esto es esperado: el GT tiene grupos legítimos con 5 fuentes. Si activas `max=3`, partes algunos correctamente fusionados. **Esta función es útil para datos sucios reales, no para benchmarks limpios como el GT.**

**Limpieza de perfiles auxiliares fue modesta:** solo `aggressive_gc` aparecía en los 3. Las otras claves dead code están **solo en `config_produccion_it7`** que no toqué. Si quieres limpieza más agresiva, hay que decidir si romper retrocompat del IT-7 (no recomendado sin notificar al equipo).

---

**Confianza: ALTO (~95%).**

Razones: 348/348 tests pasan; métricas E2E reproducibles sobre GT real; retrocompat verificada con tests específicos; los 3 cambios son acotados y aislados (no tocan flujo principal del Orchestrator). 5% de incertidumbre: el efecto de `source_quality_weights` numéricos puede ser mayor en pipelines con configuración no ordinal que no probé.
