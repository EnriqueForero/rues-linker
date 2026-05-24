# Auditoría preventiva — release v2.0.1

Resultado consolidado de la fase F3 (auditoría estática) sobre los módulos
modificados y de impacto crítico. Documentado para que futuros mantenedores
no re-investiguen los falsos positivos ya triados.

## 1. Herramientas aplicadas

| Herramienta | Alcance | Estado |
|---|---|---|
| `ruff check` (default config) | Archivos modificados en v2.0.1 | ✅ Limpio |
| `mypy --ignore-missing-imports` | `pipeline/result.py`, `pipeline/_internal.py`, `utils/logger.py` | ✅ Limpio (1 issue tipográfico corregido) |
| `pylint --enable=no-member,undefined-variable,used-before-assignment` | `src/record_linkage/` completo | ⚠️ 10 hits, 10 falsos positivos triados (ver §3) |
| `pytest tests/` | Suite completa | ✅ 65/65 (49 originales + 16 integración) |
| Pruebas E2E con datos reales | 1, 2 y 3 fuentes | ✅ Parity 100% |

## 2. Bugs reales encontrados por la auditoría

| Archivo | Línea | Issue | Estado |
|---|---|---|---|
| `utils/logger.py` | 62 | `log_counts` sin type annotation (mypy) | ✅ Corregido: `Counter[str]` |

Cero bugs **funcionales** encontrados más allá de los 5 ya conocidos. La
auditoría confirma que los hotfixes F1.1–F1.5 son suficientes para esta
release.

## 3. Falsos positivos de pylint (justificados)

### 3.1 `matplotlib.cm.<colormap>` (8 ocurrencias)

```
src/record_linkage/reporting/visualizer.py:1375:21: E1101: Module 'matplotlib.cm' has no 'viridis' member (no-member)
src/record_linkage/reporting/visualizer.py:1511:21: E1101: Module 'matplotlib.cm' has no 'Set3' member (no-member)
src/record_linkage/reporting/suite.py:734,1044,1108
src/record_linkage/reporting/dashboard.py:844,915
```

**Por qué es falso positivo**: pylint hace análisis estático y no resuelve
atributos generados dinámicamente. `matplotlib.cm.viridis`, `matplotlib.cm.Set3`,
`matplotlib.cm.RdYlGn_r`, `matplotlib.cm.coolwarm` se registran en runtime
desde `matplotlib.colormaps`. El código funciona correctamente.

**Acción**: ninguna. Documentado aquí.

**Alternativa futura** (post v2.0.1): migrar a la API moderna
`matplotlib.colormaps["viridis"]` para que pylint pueda resolverlos.

### 3.2 `numpy.random.RandomState` (1 ocurrencia)

```
src/record_linkage/engine/lsh/minhash.py:77:14: E1101: Module 'numpy.random' has no 'RandomState' member (no-member)
```

**Por qué es falso positivo**: `RandomState` es API estable y pública de
numpy. Pylint no resuelve los re-exports del módulo `numpy.random`.

**Acción**: ninguna.

### 3.3 `RecordLinkageEngine.critical_params` (2 ocurrencias)

```
src/record_linkage/engine/linkage.py:363,364: E1101: Instance of 'RecordLinkageEngine' has no 'critical_params' member (no-member)
```

**Por qué es falso positivo**: el código está protegido por un check
defensivo `hasattr` en la línea inmediatamente anterior:

```python
if hasattr(self, "critical_params") and self.critical_params:
    for param, value in self.critical_params.items():
```

El atributo `critical_params` se setea opcionalmente desde fuera (patrón
"duck typing" intencional para callers que quieren inyectar overrides).
Pylint no honra el guard de `hasattr`.

**Acción**: ninguna. El guard `hasattr` es la práctica correcta.

## 4. Patrones de migración auditados manualmente

Patrones que históricamente generaron bugs en este paquete (refactor
notebook → módulo). Revisión sistemática:

### 4.1 Variables globales en módulos (origen del bug #1)

Búsqueda: `grep -rn "^global " src/` aplicada después del fix F1.1.

**Resultado**: cero ocurrencias. La única variable global declarada
(`_LOGGING_CONFIGURED`) fue eliminada en F1.1 a favor de un classvar.

### 4.2 Atributos `self.X` referenciados pero no asignados (origen del bug #2)

Auditoría AST manual sobre todas las clases del paquete. Revisada la lista
de candidatos sospechosos (atributos terminados en `_regex`, `_config`,
`_cache`, `_processor`, `_engine`, `_table`, `_path`, `_dir`).

**Resultado**: salvo `nit_regex` (bug #2, corregido en F1.2), todas las
lecturas de `self.X` tienen asignación correspondiente o están bajo guard
`hasattr` (§3.3).

### 4.3 Tablas SQL referenciadas pero no creadas (origen del bug #3)

Búsqueda: archivos que contienen `cursor.execute` con tablas en `FROM` o
`INTO` no presentes en algún `CREATE TABLE` del mismo archivo o del
paquete.

**Resultado**: cero tablas faltantes tras el fix F1.3. Las referencias a
`metadata` y `scored_pairs` cruzadas entre módulos están justificadas
(cada motor crea su propio esquema en su propio archivo SQLite).

### 4.4 Generadores Python que deberían ser context managers (origen del bug #5)

Búsqueda AST: funciones que contienen `yield` y son llamadas con `with`.

**Resultado**: solo `_phase_cleanup` (bug #5, corregido en F1.5). Ningún
otro generador en el paquete se usa como context manager sin estar
decorado.

### 4.5 Callers de `pipeline.run()` (origen del bug #4)

Inventario de todos los call-sites de `RecordLinkagePipeline.run`:

| Archivo | Acceso a `result` | Estado |
|---|---|---|
| `deduplication/unified.py:69` | `result.get("correlative_table")` | ✅ usa contrato lazy F1.4 |
| `evaluation/hyperparameters.py:81` | `result["df_linked"]` | ✅ usa contrato lazy F1.4 |
| `optimization/engine.py:247` | `result.get("correlative_table")` | ✅ usa contrato lazy F1.4 |
| `pipeline/orchestrator.py:174` | Lazy creation, no llama `.run()` directo | N/A |

## 5. Cobertura de tests

| Suite | Tests | Tiempo | Cobertura funcional |
|---|---|---|---|
| `tests/test_smoke.py` | 27 | <1s | Imports + estructura |
| `tests/test_vectorization_equivalence.py` | 17 | ~2s | Equivalencia vectorial unitaria |
| `tests/test_reproduce_bugs.py` | 5 | ~3s | Regresión de los 5 bugs documentados |
| `tests/integration/test_deduplicate_unified.py` | 5 | ~5s | API público de deduplicación |
| `tests/integration/test_orchestrator.py` | 3 | ~10s | Record linkage cross-source |
| `tests/integration/test_pipeline_result.py` | 8 | ~1s | Contrato lazy F1.4 |
| **Total** | **65** | **~22s** | — |

Cobertura E2E con datos reales del repositorio (no en CI, smoke local):

| Escenario | Input | Tiempo | Resultado |
|---|---|---|---|
| Negocios dedup | 6,071 reg | 13s | 3 duplicados detectados |
| Negocios + Oportunidades | 14,302 reg | 36s | 5,727 cross-source matches |
| Negocios + Oport. + Servicios | 25,731 reg | 60s | 5,261 entidades en las 3 fuentes |

## 6. Lecciones para futuros refactors notebook → paquete

1. **Variables globales del notebook se pierden en el refactor**. Cualquier
   `_VAR_NAME = ...` en el cuerpo de un notebook debe verificarse explícitamente
   tras la migración. Mejor aún: convertir a classvar o ClassConfig.

2. **Generadores con `yield` no son context managers por defecto**. Si el
   notebook usaba `with generador():`, el refactor DEBE preservar el
   decorador `@contextmanager`.

3. **Naming mismatches entre superclase y subclase** son invisibles para
   pruebas estructurales (importación, llamada vacía). Solo aparecen con
   inputs reales que ejerciten la rama. Por eso son obligatorios los
   tests de integración con datos sintéticos que cubran cada rama
   condicional.

4. **Defaults peligrosos en APIs públicas** (como `keep_intermediate_results=False`
   que silenciosamente borra el resultado canónico) son antipatrón.
   Preferir contratos lazy o explicit-required.

5. **Tablas SQL deben tener UN solo punto de definición**. Constantes de
   módulo aplicadas vía `conn.executescript()` evitan que un método
   ejecute `INSERT` sobre una tabla que un compañero olvidó añadir a
   `CREATE TABLE`.

---

## 7. Actualización post v2.1.0 (F6)

Tras aplicar Fase F6 (mejoras estructurales):

### 7.1 Pylint enfocado: de 10 → 3 hits

Los 7 hits de `matplotlib.cm.<colormap>` desaparecieron al migrar a la API
moderna `matplotlib.colormaps["<name>"]` (F6.3). Los 3 hits restantes son
los mismos falsos positivos documentados en §3 (2 `critical_params` con
`hasattr` defensivo, 1 `numpy.random.RandomState` por re-export dinámico).

### 7.2 Pandas4Warning: de 16 → 0

`select_dtypes(include=["object"])` y `pd.concat(copy=False)` fueron
ajustados (F6.7). La suite corre sin warnings de pandas 3.0.

### 7.3 Parity verificada con tests dedicados

- `test_nit_processor_parity.py`: comparación bit-exact entre versión
  legacy y vectorizada en 6 casos de borde y dataset real de 17K
  registros (`Expo_bienes_dedup.csv`).
- `test_pipeline_result_v2_1.py`: protocolo Mapping completo testeado
  con `dict(result)`.
- `test_orchestrator_force_rerun.py`: cascada de invalidación.

### 7.4 Cobertura final de tests

| Suite | v2.0.0 | v2.0.1 | v2.1.0 |
|---|---|---|---|
| Smoke + vectorización | 44 | 44 | 44 |
| Regresión de bugs | 0 | 5 | 5 |
| Integración | 0 | 16 | 35 |
| **Total** | **44** | **65** | **84** |
| Tiempo suite | ~2s | ~22s | ~46s |
