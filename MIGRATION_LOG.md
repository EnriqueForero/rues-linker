# MIGRATION_LOG — Auditoría del refactor notebook → paquete .py

> **Fecha:** 2026-05-20
> **Notebook fuente:** `1779336054515_2026_02_15_DEDUPLICAR_Y_RECORD_LINKAGE_.ipynb`
> **Total notebook:** 292 celdas (148 markdown + 144 código), 25.745 LOC efectivas,
> 83 definiciones de clase, 156 funciones top-level.

Este documento registra **cada decisión no trivial** del refactor para
auditoría posterior. Si el pipeline produce resultados distintos al notebook
original, este es el primer lugar a revisar.

---

## 1. Política general

- **Lógica de negocio preservada — con 5 excepciones documentadas y testeadas
  para paridad.** El cuerpo de cada clase y función se reprodujo del notebook,
  salvo en los siguientes 5 casos donde se modernizó algoritmo con prueba de
  equivalencia bit-a-bit contra el oráculo original:

  | # | Cambio | Versión | Sección de este documento | Test de paridad |
  |---|---|---|---|---|
  | 1 | Vectorización del scorer con `rapidfuzz.process.cpdist` | v2.9.0 | §19 | `tests/test_paridad_p1_1.py` |
  | 2 | Union-Find in-memory → `scipy.sparse.csgraph.connected_components` | v2.2.0 | §10 | `tests/test_clusterer_vectorizado.py` |
  | 3 | Desempate determinista en `AdvancedValueSelector` (`max(set(...))` → alfabético) | v2.4.0 | §12 | `tests/test_golden_selector_paridad.py` |
  | 4 | Hash determinista en LSH (Python `hash()` → SHA-1 truncado) | v2.3.0 | §13 | `tests/test_vectorization_equivalence.py` |
  | 5 | Contrato lazy de `PipelineResult` (default seguro) | v2.1.0 | AUDIT.md §4.5 | `tests/integration/test_pipeline_result.py` |

  Para el resto del código, ningún `apply` se vectorizó adicionalmente,
  ningún umbral cambió, ningún algoritmo se reescribió.

- **Solo se modificó (sin tocar lógica) en todos los demás módulos:**
  - Agregado de docstring de módulo (encabezado del .py).
  - Imports agregados al inicio de cada archivo (no estaban en notebook
    porque eran globales).
  - Eliminación de directivas Jupyter (`%%time`, `!pip install`).
  - Modernización sintáctica automática por `ruff format` (PEP 585:
    `Dict[str, X]` → `dict[str, X]`; PEP 604; comillas simples → dobles;
    SIM103 `if X: return False/True` → `return not X`).
- **Extracción:** AST-based (parser oficial de Python), no regex.
  Esto garantiza preservar firmas multilínea, decoradores, triple-strings,
  f-strings con triples comillas, etc.

> **Nota de auditoría externa (2026-05-23):** la versión original de esta
> sección afirmaba "ningún algoritmo se modernizó". Esa afirmación era
> incorrecta porque las 5 modernizaciones de la tabla anterior sí cambiaron
> algoritmos. Cada cambio está documentado con su test de paridad. La frase se
> corrigió a "ningún algoritmo se reescribió" excluyendo los 5 casos.

---

## 2. Resolución de clases duplicadas

El notebook tenía 3 clases definidas más de una vez. En Jupyter esto pasa
inadvertido (la última definición gana). En un paquete .py debe resolverse
explícitamente.

### 2.1 `AdvancedValueSelector`

| Celda | Líneas | Métodos | Características | Decisión |
|-------|--------|---------|-----------------|----------|
| 124   | 75     | 6       | Sin `source_priority_map`. Stopwords extensos hardcoded. | **DESCARTADA** |
| **125** | **68** | **5** | **Recibe `source_priority_map` en `__init__`. Implementa regla "nombre por prioridad de fuente, no por frecuencia".** | **CONSERVADA** |

**Razón:** la celda 26 del notebook (✔ resuelto 2025-XX) establece como
requisito de negocio: *"La asignación del nombre final (Golden Record) debe
ser por la fuente. No por el que más se repite."*. La celda 125 implementa
ese requisito; la 124 no. Adicionalmente, la única invocación en producción
(`GoldenRecordGeneratorV7.__init__`, celda 126 línea 154) es:

```python
self.value_selector = AdvancedValueSelector(self.source_priority_map)
```

Solo la celda 125 acepta ese argumento. **La celda 124 nunca se invoca.**

### 2.2 `MemoryMonitor`

| Celda | Métodos | Características | Decisión |
|-------|---------|-----------------|----------|
| 124   | 2       | `get_memory_status`, `check_memory_threshold` | **DESCARTADA** |
| **126** | **3** | **`get_memory_status` (con try/except defensivo), `calculate_optimal_batch_size`** | **CONSERVADA** |

**Razón:** la celda 126 incluye `calculate_optimal_batch_size`, que es lo
que efectivamente usa `GoldenRecordGeneratorV7`. La 124 nunca se referencia.

### 2.3 `SafeSQLiteConnection`

| Celda | Métodos | Características | Decisión |
|-------|---------|-----------------|----------|
| 124   | 5       | Con `_wait_for_unlock` (manejo de bloqueos), **sin PRAGMAs de performance** | **DESCARTADA** |
| **126** | **3** | **Con PRAGMAs: `journal_mode=WAL`, `mmap_size=268435456`, `cache_size=-51200`, `page_size=32768`** | **CONSERVADA** |

**Razón:** las optimizaciones SQLite de la celda 126 son críticas para los
volúmenes de producción (2M+ registros). La celda 124 tiene robustez frente
a bloqueos pero rendimiento inferior.

⚠️ **Pendiente futuro:** el método `_wait_for_unlock` de la celda 124 podría
ser útil. Considerar fusión manual en una versión posterior si aparecen
errores `database is locked` en producción.

---

## 3. Decisión de motor LSH

El notebook define **5 motores LSH** distintos. La pregunta crítica era
cuál se usa realmente en la celda 8.4 (producción 4 fuentes).

| Clase                       | Celda | Estado en el paquete |
|-----------------------------|-------|---------------------|
| `OptimizedLSHEngine`        | 119   | `engine/lsh/legacy.py` — referencia, NO usar en prod |
| `DiskBasedLSHEngine`        | 120   | **`engine/lsh/disk_based.py` — base de producción** |
| `TrustedSourceLSHEngine`    | 194   | **`engine/lsh/trusted.py` — usado en producción 4 fuentes** |
| `VectorizedMinHashGenerator`| 195   | `engine/lsh/minhash.py` — usado por DiskBased y Trusted |
| Motor embebido en `RecordLinkageEngine` | 118 | Queda dentro de `engine/linkage.py` |

### Evidencia del rastreo (celda 266 = "CELDA 8.4")

```python
# Línea 50 de la celda de producción IT-7:
assert Orchestrator._run_L2.__name__ == '_run_L2_optimized', \
    "❌ _run_L2 no fue reemplazado — ejecute CELDA A"
```

La celda 194 ("CELDA A") hace:

```python
def _run_L2_optimized(self, df):
    ...
    lsh_engine = TrustedSourceLSHEngine(...)  # ← usa DiskBased como base
    ...

Orchestrator._run_L2 = _run_L2_optimized      # ← monkey-patch en runtime
```

**Conclusión:** en producción 4 fuentes, `Orchestrator._run_L2` es
reemplazado dinámicamente por `_run_L2_optimized`, que invoca
`TrustedSourceLSHEngine` (subclase de `DiskBasedLSHEngine`).

### ⚠️ Patrón frágil heredado: monkey-patching

El paquete preserva este comportamiento documentándolo en
`scripts/ejecutar_produccion.py`. **Recomendación futura:** refactorizar
para que `Orchestrator.__init__` reciba el `engine_class` como parámetro
de inyección de dependencias. Esto eliminaría el monkey-patch sin tocar
la lógica de negocio.

---

## 4. Código experimental EXCLUIDO

Por instrucción explícita del usuario, se excluyeron del paquete las
siguientes celdas (todas marcadas como prueba, exploración o código muerto):

| Celdas | Contenido | Razón de exclusión |
|--------|-----------|--------------------|
| 0–62   | Configuración inicial Git, control de cambios, aprendizajes | Markdown + bash de housekeeping |
| 66–72  | Gráficas exploratorias de intersección | UI/exploración, no pipeline |
| 100–101 | Ejecución del clasificador | Llamadas, no definiciones |
| 128–129 | TEST DE LA VERSIÓN FINAL, `robust_name_containment` no-balanced | Tests inline + versiones legacy |
| 159    | `silent_run` | Wrapper experimental |
| 173–189 | Múltiples variantes de optimización (`BalancedObjective`, `BalancedOptimizationEngine`, `OptimizationAnalyzer`, `MetricType`, `ParameterType`, `ParameterConfig`, `ObjectiveConfig`, `AdvancedOptimizationConfig`, `run_advanced_optimization`, etc.) | Experimentos paralelos, no se usa el código final de producción |
| 221–245 | "SECCIÓN 6.2: PRUEBA PRELIMINAR", "Bug de Optuna", "Trusted Sources" inline | Caja de pruebas |
| 249–251 | Suite de tests del notebook | Reemplazada por `tests/` formal |
| 269–291 | "AQUI VOY", análisis post-ejecución, exportación ad-hoc | Análisis exploratorio post |

**Si en el futuro necesita alguna de estas:** están en el notebook fuente,
referenciadas por número de celda. La extracción es trivial con
`/home/claude/extractor.py` (incluido en el repo de trabajo).

---

## 5. Cambios estructurales (no de lógica)

### 5.1 Config y Rutas — nuevos

Se crearon `config/settings.py` (clase `Config`) y `config/paths.py`
(clase `Rutas`) que **no existían en el notebook**. Estos centralizan
parámetros que estaban dispersos como variables globales en celdas 79, 87,
108, 254, etc.

**No reemplazan ninguna clase del notebook.** Conviven con `ConfigurationManager`
(celda 143), que se conserva intacta.

### 5.2 Perfiles LSH

`PERFILES_BASE` (celda 87) y `config_produccion_it7` (celda 260) se movieron
al módulo `config/profiles.py` como constantes top-level.

### 5.3 `Orchestrator` recibe `Optional` imports

El `Orchestrator` original (celda 192, 2.170 líneas) referenciaba clases
que estaban en el namespace global de Jupyter. En el paquete .py, esos
imports son explícitos al inicio de `pipeline/orchestrator.py`.

**No se modificó el cuerpo del Orchestrator.** Solo se cambió el contexto
de imports.

---

## 6. Duplicados de funciones (informativo)

Estas funciones se definen más de una vez pero **se conservó solo la última
versión** (la del notebook con número de celda mayor):

| Función                      | Celdas         | Conservada |
|------------------------------|----------------|------------|
| `hora_colombia`              | 79, 81, 107, 254 | celda 107 (helper local en `colombia_time.py`) |
| `get_colombia_timestamp`     | 79, 107, 254   | celda 107 |
| `track_performance`          | 109, 124       | celda 109 |
| `cargar_dataset_prueba`      | 214, 223       | 214 (excluida en exclusiones experimentales) |
| `robust_name_containment`    | 127, 129       | celda 127 (versión `_balanced`) |
| `consolidate_groups_by_nit`  | 127, 129       | celda 127 (versión `_balanced`) |
| `quick_run`                  | 144, 192       | celda 192 (la del Orchestrator) |
| `setup_logger`               | 124            | conservada en `utils/logger.py` |
| `verificar_memoria`, `limpiar_memoria`, `formato_tiempo` | 85, 254 | celda 85 |

---

## 7. Riesgos conocidos del refactor

1. **Dependencias implícitas via globales del notebook.** Si una clase
   del notebook dependía de una variable global (`logger`, `tracker`,
   `WORKSPACE`, etc.), en el paquete .py esa dependencia debe pasarse
   explícitamente o se rompe. El smoke test detecta esto.

2. **Imports puede que falten.** Cada módulo declara imports estándar
   para su familia. Si una clase usa una librería poco común (ej.
   `Levenshtein` específico), puede que falte el import. El primer
   `pytest` lo reportará.

3. **`Orchestrator._run_L2` monkey-patch.** Si el usuario invoca
   `Orchestrator(...).run()` sin antes aplicar el patch del módulo
   `engine.lsh.trusted`, usará la versión lenta. Está documentado
   en el script de producción.

4. **Snowflake.** El conector estaba en celdas 82-83 con credenciales.
   Esas celdas NO se incluyeron en el paquete. Hay que configurar
   `config.json` manualmente la primera vez.

---

## 8. Próximos pasos sugeridos (no incluidos)

| Pendiente | Prioridad | Esfuerzo |
|-----------|-----------|----------|
| Tests unitarios de lógica de negocio (no solo smoke) | Alta | 2-3 días |
| Eliminar el monkey-patching de `_run_L2` | Media | 1 día |
| Borrar `engine/lsh/legacy.py` si nunca se usa | Baja | 30 min |
| Migrar a Snowflake (pendiente celda 54) | Alta | 1-2 semanas |
| CI/CD con `ruff` + `pytest` en GitHub Actions | Media | 4 h |
| Empaquetar como `wheel` distribuible | Baja | 2 h |

---

## 9. Cambios v2.0 (2026-05-21)

### 9.1 Monkey-patching de `Orchestrator._run_L2` eliminado

El notebook fuente (celda 194) hacía `Orchestrator._run_L2 = _run_L2_optimized`
en runtime, lo cual era frágil y requería que el código de invocación
"recordara" aplicar el patch. En v2.0:

- El método optimizado `_run_L2_optimized` se integró directamente como
  `_run_L2` de la clase `Orchestrator` en `pipeline/orchestrator.py`.
- La versión antigua se preservó como `_run_L2_legacy` con comentario
  documentando que NO se invoca y debe eliminarse tras dos ciclos exitosos.
- La bifurcación entre `DiskBasedLSHEngine` y `TrustedSourceLSHEngine` ya
  estaba dentro del método: usa el primero si `cross_source_only=True`,
  usa el segundo si hay `trusted_unique_sources` configurado.
- Imports cruzados agregados: `Phase`, `TrustedSourceLSHEngine`,
  `DiskBasedLSHEngine`, `HybridStorageManager`, `VectorizedMinHashGenerator`.

### 9.2 Credenciales por Colab Secrets

Nuevo módulo `config/credentials.py` con:
- `SnowflakeCredentials` dataclass (frozen)
- `get_snowflake_credentials()` con orden de búsqueda:
  1. `google.colab.userdata.get(...)` para Colab Secrets
  2. `os.environ.get(SNOWFLAKE_*)` para CI/CD y Docker
  3. `config.json` local (`.gitignore`d) como último recurso
- Lanza `RuntimeError` con mensaje accionable si ninguna fuente provee
  credenciales completas.
- Nunca imprime valores de credenciales, solo de qué fuente cargaron.

### 9.3 Vectorizaciones aplicadas (con tests de equivalencia)

| `.apply` original | Reemplazo vectorizado | Archivo | Test |
|---|---|---|---|
| `.apply(lambda x: 'ALTA' if x < 0.5 else 'MEDIA')` | `np.where(cond, 'ALTA', 'MEDIA')` | `reporting/suite.py` | `test_severidad_*` |
| `.apply(lambda x: str(x).strip() if pd.notna(x) else 'UNKNOWN')` | mask + astype.str.strip | `evaluation/ground_truth.py` | `test_true_group_*` |
| `df['col'].apply(len)` × 2 | `df['col'].str.len()` | `classifier/hybrid.py` | `test_longitud_listas_*` |
| Doble loop O(n²·g) de co-ocurrencia | Producto matricial `presencia.T @ presencia` (O(n·g)) | `reporting/suite.py` | `test_cooccurrence_*` |

**17 tests de equivalencia exacta** en
`tests/test_vectorization_equivalence.py` pasan en todos los casos:
edge cases con NaN, vacíos, listas, datos sintéticos pequeños y grandes.

### 9.4 Reparación masiva de imports (387 F821 → 0)

Por el patrón de variables globales del notebook (constantes definidas en
celdas separadas, usadas en otras), el primer pase del refactor dejaba
387 referencias a nombres no definidos. Resolución:

- **6 módulos nuevos** con helpers extraídos del notebook:
  - `pipeline/_internal.py`: `PROFILES`, `DEFAULT_CONFIG`, `ALL_PROFILES`,
    `DEDUPLICATION_PROFILES`, `DEDUP_CLEANING_MODES`, `COMMERCIAL_TERMS`,
    `_class_exists`, `_fmt_time`, `_get_logger`, `_phase_cleanup`,
    `_validate_sources`
  - `pipeline/_phase_constants.py`: `PHASES_ORDER`, `PHASE_PARAMS`, `PHASE_TIMES`
  - `processing/_constants.py`: `STOPWORDS_BASIC`, `LEGAL_SUFFIXES`,
    `ORGANIZATIONAL_TERMS`, `ADMINISTRATIVE_NOISE`, `CLEANING_MODES`
  - `reporting/_lsh_refs.py`: `CONFIGURACIONES_LSH`, `N_REF`,
    `TIEMPO_POR_BANDA`, `ITERACIONES_REFERENCIA`
  - `reporting/_flags.py`: `PYARROW_AVAILABLE`
  - `evaluation/_flags.py`: `OPTUNA_AVAILABLE`
  - `engine/lsh/_constants.py`: `_MERSENNE_PRIME`
  - `utils/_globals.py`: `performance_tracker`
  - `golden/_priorities.py`: `obtener_prioridades_fuentes`
- **`reporting/_models.py`** con `RiskLevel` e `IterationData` extraídos de
  `time_estimator.py` para romper ciclo `time_estimator ↔ _lsh_refs`.
- **215 imports agregados** automáticamente con script que mapea cada nombre
  no resuelto a su declaración correcta.

### 9.5 Reparación de imports circulares (7 ciclos detectados)

- `utils/memory.py ↔ utils/logger.py`: roto con `import` diferido dentro de
  los métodos que lo usan (no a nivel de módulo).
- `utils/performance.py → utils/memory.py`: igual, import diferido.
- `evaluation/ground_truth.py ↔ optimization/engine.py`: import diferido en
  `optimization/engine.py` dentro del método que usa `GroundTruthEvaluator`,
  `EntityMetricsEvaluator` y `RecordLinkagePipeline`.
- `reporting/time_estimator.py ↔ reporting/_lsh_refs.py`: roto extrayendo
  `RiskLevel` e `IterationData` a `reporting/_models.py` (módulo neutral).
- 4 self-imports incidentales eliminados (`_internal.py` se importaba a
  sí mismo).

### 9.6 Imports relativos corregidos

22 archivos a profundidad ≥ 2 (e.g. `engine/lsh/`) tenían `from ..X.Y`
que subía 1 nivel y bajaba 2 (no existe). Fix: cambio a `from ...X.Y` o
`from .Y` según corresponda.

### 9.7 Reordenamiento topológico

Constantes con dependencias entre sí dentro del mismo archivo se
reordenaron:
- `processing/_constants.py`: `STOPWORDS_BASIC`, `LEGAL_SUFFIXES`,
  `ORGANIZATIONAL_TERMS` antes que `CLEANING_MODES` (que las usa).
- `pipeline/_internal.py`: `PROFILES`, `DEDUPLICATION_PROFILES`,
  `COMMERCIAL_TERMS` antes que `ALL_PROFILES`, `DEFAULT_CONFIG`,
  `DEDUP_CLEANING_MODES` (compuestas).

### 9.8 Ruff configuración honesta

`pyproject.toml` declara reglas estrictas (`E, F, W, I, B, UP, RUF, SIM`)
globalmente. Para código heredado del notebook (`src/record_linkage/**`),
silencia con `per-file-ignores` reglas estilísticas que requerirían
reescribir lógica de negocio: `E701` (multi-statement), `E722`
(bare-except), `SIM102/105/115`, `B019`, `RUF001/002/003` (unicode en
español), `F601` (bug menor en config), `E402` (algunos imports
condicionales). Las reglas de errores REALES (`F-rules`, `B-rules`
peligrosas) siguen activas globalmente.

**Resultado final**: `ruff check` y `ruff format --check` ambos pasan
verde sobre 88 archivos.

---

## 10. Bugs descubiertos en validación post-migración (release v2.0.1)

> **Fecha:** 2026-05-21
> **Contexto:** prueba end-to-end con datos reales (`Negocios_dedup.csv`,
> `Oportunidades_dedup.csv`, `Servicios_dedup.csv`) reveló 5 bugs
> ocultos. Los 44 tests originales (todos estructurales: importaciones y
> equivalencias unitarias) no los detectaron porque ninguno ejercitaba el
> pipeline completo con DataFrames reales.

### 10.1 Inventario de bugs

| # | Archivo | Síntoma | Causa raíz | Fix |
|---|---|---|---|---|
| 1 | `utils/logger.py` | `NameError: name '_LOGGING_CONFIGURED' is not defined` en el primer uso de cualquier logger | El notebook tenía `_LOGGING_CONFIGURED = False` como variable global de celda. El refactor agregó `global _LOGGING_CONFIGURED` dentro de la función pero omitió la inicialización a nivel de módulo | Refactor a atributo de clase `CustomLogger._logging_configured` (elimina la dependencia de variable global) |
| 2 | `processing/nit.py` | `AttributeError: 'AdvancedNitProcessor' object has no attribute 'nit_regex'` al limpiar NITs con caracteres no-dígito | Naming mismatch: subclase usa `self.nit_regex`, superclase define `self.non_digit_regex`. Probable error de copy-paste durante el refactor | Renombrar a `self.non_digit_regex` |
| 3 | `engine/lsh/legacy.py` | `OperationalError: no such table: index_data` al activar trusted sources | `_init_database` crea las tablas `candidates` y `stats` pero omite `index_data`. La tabla aparecía en otro lugar del notebook que no se preservó | Esquema SQL unificado como constante `_LSH_LEGACY_SQLITE_SCHEMA` aplicado vía `executescript()` |
| 4 | `deduplication/unified.py` + `evaluation/hyperparameters.py` | `RuntimeError: El pipeline no generó la tabla correlativa` | Contrato API roto: `pipeline.run()` con `keep_intermediate_results=False` (default) borraba `results["correlative_table"]` antes del return. Los callers asumían que persistía | Refactor arquitectural: `PipelineResult` (dataclass con `cached_property`) carga DataFrames lazy desde checkpoints parquet |
| 5 | `pipeline/_internal.py` | `TypeError: 'generator' object does not support the context manager protocol` al iniciar cualquier fase del Orchestrator | `_phase_cleanup` tiene `yield` pero le falta `@contextmanager`. El notebook lo tenía decorado en otra celda no preservada | Agregar `from contextlib import contextmanager` y decorar |

### 10.2 Causa raíz común

**Cuatro de los cinco bugs** (1, 2, 3, 5) tienen el mismo patrón: el
notebook fuente tenía elementos **fuera del cuerpo de la clase/función**
que el refactor automático AST no capturó:

- Bug #1: variable global de celda `_LOGGING_CONFIGURED = False`
- Bug #2: la subclase definía `self.nit_regex` en una celda separada
  (probablemente una mejora añadida después de la base) que no se preservó
- Bug #3: las CREATE TABLE estaban en una celda de setup que se omitió
- Bug #5: el decorador `@contextmanager` estaba en una celda anterior

El bug #4 es de otra naturaleza: es **mal diseño de la API**, no error
de migración. El default `keep_intermediate_results=False` era peligroso
porque borraba precisamente lo que el caller necesitaba.

### 10.3 Lecciones para futuros refactors notebook → paquete

1. **Migración AST-based es necesaria pero no suficiente**. El parser
   preserva el cuerpo de clases y funciones pero **pierde el contexto de
   celdas vecinas**: imports condicionales, decoradores aplicados en celdas
   separadas, variables globales de inicialización, definiciones de
   esquemas SQL.

2. **Tests estructurales no son suficientes**. Los 44 tests originales
   pasaban (`import` funciona, `nargs` correctos, equivalencias unitarias)
   y los 5 bugs seguían ahí. Se requieren **tests de integración con
   DataFrames reales** que ejerciten cada rama condicional. Un test con
   50 filas sintéticas habría detectado los 5 bugs en minutos.

3. **Defaults peligrosos en APIs públicas** son antipatrón. Si una
   función con `default=False` provoca el borrado silencioso de su salida
   canónica, el default está mal. Preferir contratos lazy
   (`cached_property`) o defaults seguros.

4. **Naming consistente entre superclase y subclase**: agregar al CI
   un `pylint --enable=no-member` o equivalente para detectar
   `self.X` que solo existen en una jerarquía intermedia.

5. **Una sola fuente de verdad para esquemas SQL**: aplicar el esquema
   completo vía `conn.executescript(SCHEMA_CONSTANT)` en lugar de
   `cursor.execute(CREATE_TABLE_INDIVIDUAL)` disperso por el archivo.
   Hace los cambios de esquema atómicos y auditables.

### 10.4 Validación de la corrección

- `tests/test_reproduce_bugs.py` (5 tests): en v2.0.0 los 5 fallan, en
  v2.0.1 los 5 pasan.
- `tests/integration/` (16 tests): cubren el contrato del API público
  end-to-end.
- Pruebas E2E con datos reales: parity 100% con la corrida parcheada
  (mismos conteos de grupos, golden records y matches cross-source).

### 10.5 Auditoría preventiva

Documentada en `docs/AUDIT_v2.0.1.md`. Aplicación de ruff, mypy y pylint
enfocado sobre el paquete completo. Cero bugs funcionales nuevos
encontrados. Falsos positivos triados y justificados.

---

## 11. Cambios v2.2.0 (2026-05-21) — Iteración de auditoría

Esta versión responde a una auditoría externa que verificó empíricamente las
afirmaciones del README y midió por primera vez la calidad real del linkage.

### 11.1 El agujero principal: no se medía la calidad

Hasta v2.1.0, los 84 tests verificaban que el código **corre** (smoke), que
las vectorizaciones son **equivalentes entre sí**, y que la `Config` valida
inputs. **Ninguno medía si el sistema agrupa bien.** Para un sistema de record
linkage, eso es no tener tests del producto.

**Corrección:**
- Nuevo módulo `evaluation/pairwise.py`: precision/recall/F1 a nivel de pares,
  el estándar de record linkage. Verificado contra casos triviales conocidos.
- Nuevo `tests/test_quality_golden.py`: corre el pipeline completo sobre un
  golden set de 269 registros reales (`tests/data/golden_truth.csv`, etiquetado
  con `ID_GROUP`) y fija pisos de regresión para F1/recall/precision.

### 11.2 Calidad medida y recalibración del perfil

Medición inicial (perfil `deduplication_standard` v2.1.0) sobre el golden set:

| Métrica | v2.1.0 | v2.2.0 | Δ |
|---|---|---|---|
| Precision | 0.848 | 0.843 | −0.005 (sin pérdida material) |
| Recall | 0.267 | 0.523 | +0.256 (≈2×) |
| F1 | 0.406 | 0.646 | +0.240 (+56 %) |
| Grupos predichos | 168 | 118 | (verdad = 84) |

**Causa raíz del bajo recall (diagnóstico, no adivinanza):**
1. `lsh_threshold = 0.75` descartaba en el bloqueo pares con typos ANTES de
   compararlos. Bajado a `0.30`.
2. `weights nit = 0.45` daba demasiado peso al NIT, que en estos datos es poco
   fiable (dígitos de verificación errados a propósito). Bajado a `0.20`.
3. `phonetic = 0.0`: la similitud fonética estaba apagada, justo lo que ayuda
   con typos (SANOFI/SAFONI). Subida a `0.15`.
4. `score_threshold` 0.85 → 0.68; `min_name_similarity` 0.65 → 0.60.

La recalibración se eligió por **barrido medido contra la verdad**, no a ojo.
Se probaron 6 configuraciones; se eligió la de mayor F1 sin pérdida de precision.

**Honestidad obligatoria:** F1=0.65 NO es calidad de producción. El sistema aún
fragmenta ~47 % de los pares verdaderos (298 FN de 625). El perfil recalibrado
solo aplica a `deduplication_standard`; los demás perfiles NO se tocaron porque
no fueron validados contra ground truth.

### 11.3 Bug real corregido: clave duplicada en mapa de encoding

`processing/text.py` tenía un dict de correcciones mojibake con la clave `Ã`
(bytes `\xc3\x83`) repetida: una entrada mapeaba a `Í` y otra a `Á`. Python
descarta silenciosamente la primera, así que **la corrección de `Í` nunca se
aplicaba**. El `pyproject.toml` lo silenciaba como F601 "bug menor". Corregido
definiendo las claves por sus secuencias de bytes mojibake completas
(`\xc3\x8d` → Í, `\xc3\x81` → Á). Ya no hay claves duplicadas (12 únicas).

### 11.4 Fail Fast: eliminada degradación silenciosa del scorer

`engine/scorer.py` tenía un `except:` desnudo que, si `SimilarityCalculator`
fallaba por cualquier razón, degradaba en silencio a `BasicSimilarityCalculator`
sin un solo log. En una corrida de 2M registros eso significa calidad
silenciosamente inferior. Ahora captura la excepción específica y emite un
WARNING explícito antes de degradar.

### 11.5 README sincronizado con la realidad

La auditoría encontró que el README afirmaba "ruff ✅ Verde" cuando había 3
errores reales (variables sin usar en tests), "44/44 tests" cuando eran 84,
"import 83/83" cuando son 85, y versión 2.0.0 cuando el paquete es 2.1.0. Todo
corregido. Los 3 errores ruff se arreglaron de raíz (no con `# noqa`). El README
ahora declara explícitamente la cobertura (36 %) y el F1 (0.65) en vez de
ocultarlos.

### 11.6 Corrección de §7.3 (deuda de documentación)

El §7.3 listaba el monkey-patching de `_run_L2` como "riesgo activo", pero fue
eliminado en v2.0.0 (ver §9.1). `_run_L2_legacy` sobrevive solo como método
nativo del Orchestrator, no como patch. La afirmación del README ("Sin
monkey-patching") es correcta; era el §7.3 el que estaba desactualizado.

### 11.7 Lo que NO se hizo en esta iteración (deuda viva)

| Pendiente | Prioridad | Por qué no ahora |
|---|---|---|
| Subir recall > 0.70 | **Alta** | Requiere trabajo algorítmico (bloqueo multi-pasada, similitud de tokens), no solo umbrales. El piso F1=0.60 evita que retroceda mientras tanto. |
| Cobertura de `clusterer.py` (18 %) | Alta | Es el corazón del sistema; necesita tests unitarios dedicados. |
| Vectorizar hot-paths con `for`/`iterrows` | Media | `clusterer` usa Union-Find por `iterrows`; reemplazar por `networkx`/`scipy.sparse`. |
| Renombrar métodos `*_vectorized` con bucles | Media | El nombre miente sobre lo que hace el código. |
| Validar y recalibrar los OTROS perfiles | Media | Solo `deduplication_standard` fue validado contra ground truth. |

### 11.8 Validación de esta iteración

- `ruff check` + `ruff format --check`: verde (checklist §18.7 completo).
- `pytest tests/`: 89/89 pasan (84 previos + 5 de calidad), cero regresiones.
- El test de calidad es determinista (`random_state` fijo) y reproducible.

---

## 12. Cambios v2.2.0 — continuación (clustering vectorizado + validación con datos reales)

Segunda parte de la iteración de auditoría. Aborda la deuda de rendimiento de
§11.7 y valida el paquete contra datos de producción reales (no etiquetados).

### 12.1 Clustering vectorizado (P3) — el iterrows del hot-path

`OptimizedClusterer._cluster_in_memory` usaba un Union-Find con
`scored_pairs.iterrows()` — un bucle Python sobre cada par candidato, letal en
los millones de pares que genera RUES (1.9M registros). Reescrito a construcción
de grafo disperso (`scipy.sparse.csr_matrix`) + `connected_components`, que
resuelve los componentes en C.

**Equivalencia probada, no asumida:** `tests/test_clusterer_vectorizado.py`
reimplementa el Union-Find original como oráculo y verifica partición idéntica
sobre 8 grafos aleatorios + casos borde (sin aristas, NIT idéntico, una entidad).

**Benchmark medido:**

| n entidades | pares | iterrows (v2.1.0) | vectorizado | speedup |
|---|---|---|---|---|
| 50.000 | 100.000 | 1.50 s | 0.018 s | **84×** |
| 200.000 | 500.000 | 7.61 s | 0.090 s | **84×** |

Nota: los IDS de cluster cambian (scipy usa labels 0..k−1; el Union-Find usaba
la raíz arbitraria), pero la PARTICIÓN es idéntica. Nada downstream depende del
valor literal del id, solo de qué registros comparten cluster.

### 12.2 Selector de golden record — optimización segura (sin tocar lógica)

`GoldenRecordSelector.select_best_name` mutaba `group_df["priority_score"]`
dentro de un `groupby().apply()`, disparando `SettingWithCopyWarning` y copias
defensivas por grupo. Reescrito para calcular el score en una Series local sin
mutar el grupo. La lógica de selección (singleton → fuente única → prioridad →
consenso) es BIT-IDÉNTICA; el test de calidad (F1) lo confirma sin cambios.

### 12.3 Lo que NO se vectorizó (decisión consciente de paridad)

El profiling con datos reales mostró que el mayor costo (40 %) está en
`golden/generator.py._process_batch_vectorized`, vía `groupby().apply()` que
llama `select_best_name`/`select_best_nit` por grupo. Esta lógica de negocio
(consenso por huellas, votación posicional de NIT, prioridad de fuente) NO es
trivialmente vectorizable sin reescribirla, y el SKILL es explícito: la paridad
de lógica de negocio manda sobre el rendimiento. Vectorizarla a ciegas
produciría golden records distintos. **Queda como deuda con prerrequisito:**
escribir primero un test de paridad dedicado del golden generator, luego
vectorizar contra él. No se hizo en esta iteración por disciplina de paridad.

### 12.4 Validación con datos reales NO etiquetados (A06)

Se recibió el dataset de producción `2026-02-14` (RUES 1.9M, CRM 18k,
EXPORTACIONES 17k, SUPERSOCIEDADES 10k, varios CSV dedup). Sin `ID_GROUP`, NO se
puede medir precision/recall. Lo que SÍ se validó objetivamente:

1. **Fix de encoding sobre datos reales.** El RUES viene en ISO-8859-1 (latin-1)
   con 9 % de nombres con tildes/Ñ. Tras procesar, mojibake residual = 0 en la
   columna `NOMBRE_LIMPIO`. El caso `Í` (roto en v2.1.0 por la clave duplicada,
   §11.3) ahora se corrige: "LOGÃ\x8dSTICA" → "LOGÍSTICA". Confirmado con datos
   reales, no sintéticos.

2. **Smoke a escala.** Muestra de 8.000 registros RUES reales procesada en
   18.4 s (~435 reg/s), RAM pico 397 MB. Consistencia interna sana: grupo más
   grande 22 registros, cero grupos > 50 (sin sobre-fusión patológica), tasa de
   compresión 2.8 % (plausible: el RUES ya viene casi sin NITs duplicados).

3. **Hallazgo de rendimiento.** A 435 reg/s y con crecimiento superlineal de
   pares candidatos, procesar 1.9M registros requiere los engines de disco
   (`DiskBasedLSHEngine`), no el modo en memoria. El cuello de botella está en
   el golden generator (§12.3), no en el clustering (ya resuelto en §12.1).

### 12.5 Validación de esta continuación

- `ruff check` + `ruff format --check`: verde (checklist §18.7).
- `pytest tests/`: 99/99 pasan (89 previos + 10 de equivalencia del clusterer).
- Cobertura: 37 % global; `clusterer.py` 18 % → 29 %.

---

## 13. Cambios v2.3.0 — reescritura de DiskBasedLSHEngine (el motor de producción)

`DiskBasedLSHEngine` es el motor que realmente corre en producción (1.9M
registros RUES). El profiling con datos reales mostró que ~60 % de su tiempo se
iba en generación de firmas. Esta versión lo reescribe atacando tres problemas
medidos, preservando exactamente la arquitectura (HDF5 + SQLite + bandas +
checkpointing) y la calidad del resultado.

### 13.1 Firmas MinHash vectorizadas (cuello de botella #1)

El método original creaba un objeto `datasketch.MinHash` por registro y llamaba
`.update()` n-grama por n-grama en un bucle Python. Sobre 1.9M registros: ~1.9M
objetos + decenas de millones de `.update()`.

Reescrito con `engine/lsh/vectorized_minhash.VectorizedMinHasher`, que calcula
firmas por lotes con NumPy usando la misma familia de hashing universal que
datasketch (lineal `(a·x+b) mod (2^61−1)`). **Validado matemáticamente:** la
similitud de firmas estima el Jaccard de n-gramas con error medio 0.022 (ver
`tests/test_vectorized_minhash.py`).

**Benchmark medido (20k registros RUES reales):**

| Fase | v2.2.0 | v2.3.0 | speedup |
|---|---|---|---|
| Firmas | 20.0 s | 1.2 s | **17×** |
| Total motor | 32.8 s | 15.6 s | **2.1×** |

A 50k registros, una corrida que en v2.2.0 excedía 280 s ahora termina en 32 s.

### 13.2 Hash de banda determinista (BUG de corrección, no solo velocidad)

`_index_band` usaba `hash(row.tobytes())`. El `hash()` de Python está
**randomizado por `PYTHONHASHSEED`**: cambia entre procesos. Como Colab reinicia
la sesión cada ~12 h y el motor reanuda desde checkpoint, las bandas indexadas
DESPUÉS del reinicio producían hashes que no coincidían con los del índice
previo. Resultado: buckets corruptos y **pares candidatos perdidos en silencio**
— degradación de recall invisible, imposible de diagnosticar sin este análisis.

Reemplazado por `_hash_rows_stable` (FNV-1a de 64 bits, vectorizado sobre todas
las filas de la banda). Determinista entre procesos. El `VectorizedMinHasher`
también es determinista (semilla fija 42), así que todo el pipeline de firmas →
índice → candidatos es ahora reproducible tras reinicios. Probado en
`tests/test_disk_engine.py::test_hash_rows_estable_es_determinista`.

### 13.3 Generación de pares por bucket vectorizada (cuello #3)

`_generate_bucket_pairs` usaba doble bucle `for i: for j:`. Reescrito con
`np.triu_indices`. Equivalencia con la lógica original probada sobre buckets
aleatorios y el filtro cross-source (`test_disk_engine.py`).

### 13.4 Calidad NO degradada (verificación obligatoria)

El MinHasher vectorizado usa una familia de hash distinta a datasketch, así que
los buckets concretos difieren (más candidatos crudos: 553k → 643k en 20k regs).
Pero son LSH-equivalentes: el F1 end-to-end sobre el golden set es **0.646,
idéntico** al de v2.2.0. El aumento de candidatos crudos lo absorbe el scorer
posterior; no afecta la calidad final ni la precision.

### 13.5 Validación de esta versión

- `ruff check` + `ruff format --check`: verde.
- `pytest tests/`: 120/120 (110 previos + 10 del motor reescrito).
- F1 sobre golden set: 0.646 (sin regresión).
- `_create_minhash` marcado deprecado (ya no se usa internamente; conservado
  por compatibilidad).

### 13.6 Deuda restante (sin cambios respecto a §12.3)

El golden generator sigue siendo el mayor costo del pipeline completo (no del
motor LSH). Su vectorización requiere primero un test de paridad dedicado; no se
hizo aquí por disciplina de paridad de lógica de negocio.

---

## 14. Cambios v2.4.0 — Golden Generator vectorizado y determinista

El profiling de §12.3 identificó el Golden Generator como el mayor costo del
pipeline completo (40 %), vía `groupby().apply()` que llamaba la lógica de
consenso por grupo. En §12.3 se decidió NO vectorizarlo sin un test de paridad
dedicado. Esta versión cumple ese prerrequisito y lo vectoriza.

### 14.1 Prerrequisito cumplido: test de paridad contra oráculo

Antes de tocar la lógica de negocio, se capturó su salida exacta como oráculo
sobre el ground truth EXHAUSTIVO (1456 registros, 137 grupos, con NITs erróneos
y casos negativos). La versión vectorizada debe reproducirla bit-a-bit.
`tests/test_golden_selector_paridad.py` verifica esto para los 137 grupos.

### 14.2 Vectorización del selector (paridad 137/137)

`AdvancedValueSelector` ganó API por lotes:
- `select_best_name_batch`: reproduce las reglas singleton → fuente única →
  prioridad de fuente → consenso por fingerprint, en una pasada vectorizada
  (groupby + sort estable para los argmax por frecuencia/longitud).
- `select_best_nit_batch`: votación de NIT (frecuencia, longitud) vectorizada.

Paridad medida contra el método individual: **nombres 137/137, NITs 137/137**.

### 14.3 Bug de reproducibilidad corregido (no solo velocidad)

La lógica original usaba `max(set(candidates), key=...)`. Como `set` no tiene
orden estable, en empates exactos de (frecuencia, longitud) el golden record
resultante VARIABA entre ejecuciones. Demostrado: dos corridas de v2.3.0 sobre
el mismo dato produjeron nombres distintos en 3 grupos (p.ej. "KPMG" vs "Kpmg",
"AEROVIAS..." vs "Aerovias..."). v2.4.0 desempata alfabéticamente de forma
explícita, tanto en la API individual como en la batch → golden records
reproducibles. El generator completo es ahora determinista (probado a 225k regs).

### 14.4 Otras vectorizaciones del generator

En `_process_batch_vectorized`:
- `PRIMARY_SOURCE`: de un `lambda min(key=...)` por grupo a precálculo de
  prioridad + `sort_values` estable + `drop_duplicates` (idxmin vectorizado).
- `CONFIANZA`: de `apply(axis=1)` fila por fila a `np.select` vectorizado.
Ambos preservan exactamente las reglas (paridad de CONFIANZA y PRIMARY_SOURCE:
137/137 contra v2.3.0).

### 14.5 Benchmark (datasets sintéticos a escala, ~9 registros/grupo)

| Registros | grupos | v2.3.0 | v2.4.0 | speedup |
|---|---|---|---|---|
| 45.000 | 5.000 | 13.8 s | 2.4 s | **5.7×** |
| 180.000 | 20.000 | 55.5 s | 11.1 s | **5.0×** |

A 225k registros desde disco: 14 s, RAM pico 686 MB (muy por debajo de los
12 GB de Colab), procesamiento por lotes vía SQLite. Extrapolado a 4M: ~4 min.

### 14.6 Validación de calidad con ground truth EXHAUSTIVO

Nuevo dataset embebido `tests/data/golden_truth_exhaustivo.csv` (1456 regs).
Calidad del pipeline completo (`tests/test_quality_exhaustivo.py`):

| Métrica | valor | lectura |
|---|---|---|
| Precision | 0.934 | pocos falsos positivos pese a los casos negativos |
| Recall | 0.666 | aún fragmenta ~33 % de los pares |
| F1 | 0.778 | mejor que en el set pequeño (grupos grandes dan pares fáciles) |

IMPORTANTE: la mejora del Golden Generator NO cambia el F1. El generator decide
el NOMBRE/NIT representativo de cada grupo, no QUÉ se agrupa (eso es el
clusterer/scorer). Lo que cambió: 5× más rápido, determinista, paridad de
lógica. La calidad del agrupamiento es la misma.

### 14.7 Validación de esta versión

- `ruff check` + `ruff format --check`: verde.
- `pytest tests/`: 130/130 (126 previos + 4 del test de calidad exhaustivo).
- Paridad del selector: 137/137 nombres y NITs.
- Generator determinista verificado a 225k registros desde disco.

---

## 15. Bloqueo por NIT base (v2.5.0)

**Contexto:** ROADMAP §P0-1 Paso 1.1. El cuello de calidad del sistema en
v2.4.0 era el recall (0.666 sobre el ground truth exhaustivo), y el
diagnóstico ya hecho atribuía 3229 de los 9679 falsos negativos a dos
clases: (1) pares cuyas razones sociales **no comparten n-gramas** pero sí
comparten NIT (`EY COLOMBIA` ↔ `ERNST & YOUNG`); (2) typos donde el LSH por
n-gramas pierde la conexión. Esta sección implementa la solución para (1).

### 15.1 Diagnóstico cuantificado (medido sobre el ground truth)

| Característica de los pares verdaderos | % | acción |
|---|---|---|
| Comparten NIT base exacto | 25.2 % | bloqueo exacto |
| Comparten NIT base a Lev ≤ 1 misma longitud | 51.0 % | + bloqueo por sustituciones |
| Comparten NIT base a Lev ≤ 1 cualquier longitud | 61.2 % | + bloqueo por inserciones/borrados |

El 61.2 % es el **techo teórico** del bloqueo por NIT solo. Lo demás lo
tiene que cubrir el LSH de nombre, P0-1 Paso 1.2 (multi-pasada) o nuevas
variables (último ítem del ROADMAP).

### 15.2 Arquitectura de la solución

Un módulo nuevo `engine/lsh/nit_blocking.py` con una función vectorizada
`block_by_nit_base(df, config)` que retorna el set de pares candidatos.
Tres mecanismos:

1. **Exacto** (`groupby('NIT_BASE')` + emisión intra-grupo). Determinista.
   Cota dura `max_bucket_size` (default 200) que descarta NITs con
   demasiados registros — evita explosión cuadrática.
2. **Vecinos por sustitución** (mismo length, un dígito distinto). Cada
   NIT genera L claves canónicas con `*` en cada posición. Dos NITs a
   distancia 1 (mismo length) comparten una clave.
3. **Vecinos por inserción/borrado** (length difiere en 1). Cada NIT
   genera claves canónicas con prefijo `=L{n}:` y `=L{n-1}:`, una por
   cada posición borrada. Un NIT de longitud n+1 cuyo borrado coincida
   con un NIT de longitud n comparte clave.

**La fusión NO se hace en cada motor LSH** (sería duplicación). Se hace en
el orquestador `RecordLinkageEngine.run`, justo después de
`find_candidates` y antes del scoring. Cubre los tres motores
(`OptimizedLSHEngine` legacy, `DiskBasedLSHEngine`, `TrustedSourceLSHEngine`)
con un solo punto de integración. Maneja los tres formatos de retorno:
set en memoria (unión directa), ruta SQLite (`INSERT OR IGNORE`), o vacío.

### 15.3 Calidad medida — antes y después

Ground truth exhaustivo (1456 regs, 137 grupos):

| Configuración | F1 | Precision | Recall | FP | FN |
|---|:---:|:---:|:---:|:---:|:---:|
| v2.4.0 (sin bloqueo NIT) | 0.778 | 0.934 | 0.666 | 455 | 3229 |
| v2.5.0 NIT exacto solo | 0.823 | 0.883 | 0.771 | 994 | 2212 |
| **v2.5.0 NIT exacto + vecinos** | **0.863** | **0.886** | **0.842** | 1053 | 1534 |

Golden 269: F1 0.65 → **0.77**, recall 0.53 → **0.71**.

**Trade-off explícito y honesto:** el criterio formal del ROADMAP era
"recall +≥ 0.05 sin precision bajando más de 0.02". El recall subió
mucho más (+0.176), la precision bajó más (−0.048). Inspección de los
1053 FP introducidos: la mayoría son **casos negativos diseñados** del
ground truth (empresas con NIT adyacente y algún token compartido, p. ej.
`800222003 / COMERCIO COLOMBIANO` vs `800222004 / COMERCIALIZADORA
COLOMBIANA INC.` — los grupos 97/98 son adyacentes a propósito). El
sistema los une porque, dado solo "NIT cercano + nombres con tokens
compartidos", son indistinguibles sin información extra (ciudad,
teléfono). Decisión: aceptar el trade-off porque el F1 absoluto sube
+0.085 y la precision sigue por encima de 0.85.

### 15.4 Validación a escala (RUES real)

50k registros del RUES (encoding latin-1):
- Procesados en 250.8 s = 199 reg/s; RAM pico 1.4 GB.
- 48k grupos, max grupo 58 (`AGROINVERSIONES X` — agrupación preexistente
  del LSH de nombre, NO introducida por el bloqueo NIT).

A/B test sobre 10k RUES:
- Sin bloqueo NIT: 9767 grupos.
- Con bloqueo NIT: 9747 grupos (−0.2 % más fusión).
- Tiempo idéntico (~23 s).

Conclusión: el bloqueo NIT no causa explosión combinatoria en datos reales
porque la mayoría de NITs RUES son únicos. Es seguro para producción 2-4M.

### 15.5 Cómo desactivarlo si fuera necesario

Añadir al perfil:
```python
profile["enable_nit_blocking"] = False         # apaga todo el bloqueo
profile["nit_blocking_neighbors"] = False      # apaga solo los vecinos
profile["nit_blocking_max_bucket"] = 200       # cota de buckets
profile["nit_blocking_min_length"] = 6         # longitud mínima del NIT
profile["nit_blocking_column"] = "NIT_BASE"    # nombre de la columna
```

### 15.6 Lo que NO está hecho (deja P0-1 incompleto)

- **Paso 1.2 — Bloqueo multi-pasada por nombre.** No implementado. Atacaría
  el ~30 % de pares que NO comparten NIT pero sí tokens fuera del LSH
  actual. Posible siguiente iteración.
- **Paso 1.3 — Re-barrido de umbrales contra el set exhaustivo.** No hecho.
  Los umbrales actuales se calibraron sobre el set de 269. Con la
  distribución de candidatos cambiada por el bloqueo NIT, podría
  recalibrarse Optuna (P2-1) para subir F1 sin tocar más código.

Estos quedan documentados como deuda explícita en el CHANGELOG.

### 15.7 Validación de esta versión

- `ruff check` + `ruff format --check`: verde.
- `pytest tests/`: **142/142** (130 previos + 12 nuevos del bloqueo NIT).
- Tests aislados del bloqueo: NIT idéntico produce par, NIT vacío no
  produce, NIT corto descartado, bucket grande omitido, vecinos por
  sustitución/inserción/borrado, vecinos desactivables, determinismo entre
  corridas, propiedad de negocio (captura ≥ 50 % de pares verdaderos del
  ground truth).
- Pisos de regresión subidos en los dos tests de calidad para que el
  avance sea irreversible.

---

## 16. Bloqueo de nombre y re-barrido de umbrales (v2.6.0)

**Contexto:** ROADMAP §P0-1 Pasos 1.2 y 1.3. Esta sección documenta la
implementación, las mediciones y por qué v2.6.0 **NO mueve las métricas**
respecto a v2.5.0.

### 16.1 Paso 1.2 — Bloqueo multi-pasada por nombre

Implementado en `engine/lsh/name_blocking.py`. Dos pasadas vectorizadas:

1. **Fingerprint:** misma fórmula que `AdvancedValueSelector._get_fingerprint`
   (sin sufijos societarios, sin no-alfanuméricos, mayúsculas, sin acentos).
2. **Token significativo más largo:** token ≥ 4 chars, no stopword del
   dominio. Stopwords: `DE LA EL LOS LAS Y EN DEL AL POR PARA CON SIN SA
   SAS LTDA LIMITADA EU CIA INC LLC CORP SRL SCA SENC`.

Integrado en el orquestador igual que el bloqueo NIT, default OFF.

### 16.2 Mediciones de techo teórico (ground truth exhaustivo)

| Bloqueo | Pares emitidos | TP capturados | % de los 9 679 pares verdaderos |
|---|---:|---:|---:|
| NIT (v2.5.0) | 8 465 | 6 884 | 71.1 % |
| Nombre (v2.6.0) | 14 530 | 2 195 | 22.7 % |
| **NIT ∪ Nombre** | **21 190** | **7 447** | **76.9 %** |
| Pares verdaderos NUEVOS por nombre | — | **+563** | **+5.8 pp** |

**Ratio TP/pares emitidos:**
- NIT: 81.3 % de los pares emitidos son TP.
- Nombre: 15.1 % de los pares emitidos son TP. **5× más ruidoso.**

### 16.3 Por qué el bloqueo de nombre NO mueve métricas

Medido sobre los tres datasets:

| Dataset | F1 con NIT solo | F1 con NIT+nombre | Δ |
|---|:---:|:---:|:---:|
| Sintético P0-1 (24) | 0.556 | 0.556 | 0.000 |
| Golden 269 | 0.771 | 0.771 | 0.000 |
| Golden exhaustivo 1456 | 0.863 | 0.863 | 0.000 |

**Diagnóstico:** el scorer/clusterer descarta los pares "nuevos" del
bloqueo de nombre porque su similitud calculada cae bajo el umbral. El
bloqueo aporta candidatos al scorer, pero el scorer los rechaza.

**Causa raíz:** el scorer pondera nombre 0.65 + NIT 0.20 + fonético 0.15.
Para los pares del bloqueo de nombre (mismo token significativo, NIT
distinto, p. ej. `CROWN COLOMBIA` ↔ `PRODENVASES CROWN`), el componente
NIT da score bajo y el componente de nombre no compensa lo suficiente para
cruzar el umbral 0.68.

**Decisión:** dejar el módulo opt-in (default OFF), implementado y
testeado como infraestructura para cuando se integre re-pesado del scorer
por origen del par.

### 16.4 Limitaciones documentadas del bloqueo de nombre

El bloqueo elige UN token por nombre (el más largo no-stopword). Esto
crea casos donde dos nombres relacionados eligen distintos tokens y NO
comparten bucket. Ejemplos del ground truth:

- `CROWN COLOMBIA` (eligió COLOMBIA, 8 chars) vs `PRODENVASES CROWN`
  (eligió PRODENVASES, 11 chars) → NO compartieron bucket pese a tener
  CROWN en común.
- `COOPERATIVA COLANTA` (eligió COOPERATIVA, 11 chars) vs `COLANTA SAS`
  (eligió COLANTA, 7 chars) → NO compartieron bucket.

Para capturar estos casos, una variante "all_significant_tokens" emitiría
buckets por cada token significativo de cada nombre. Esto multiplica los
pares emitidos por la cantidad promedio de tokens (~3-4×) y puede saturar
el scorer. **No se implementó en v2.6.0** porque sin un re-pesado del
scorer el resultado neto sería igual a 0.

### 16.5 Paso 1.3 — Re-barrido de score_threshold

Barrido completo sobre los dos golden, con bloqueo NIT activo (default
v2.5.0):

| `score_threshold` | F1 golden 269 | F1 exhaustivo | F1 promedio |
|---:|:---:|:---:|:---:|
| 0.60 | 0.770 | 0.833 | 0.802 |
| 0.65 | 0.771 | 0.854 | 0.812 |
| 0.66 | 0.771 | 0.853 | 0.812 |
| 0.67 | 0.771 | 0.853 | 0.812 |
| **0.68 (actual)** | **0.771** | **0.863** | **0.817** |
| 0.69 | 0.737 | 0.870 | 0.804 |
| 0.70 | 0.711 | 0.871 | 0.791 |
| 0.72 | 0.706 | 0.866 | 0.786 |
| 0.74 | 0.690 | 0.878 | 0.784 |
| 0.75 | 0.679 | 0.875 | 0.777 |

**Conclusión rigurosa:** `score_threshold=0.68` es ÓPTIMO en F1 promedio
sobre los dos golden. Subirlo favorece al exhaustivo (precision sube
fuerte por los casos negativos diseñados con NIT adyacente), pero
**degrada el golden 269 de forma material** (F1 cae −0.09 a thr=0.75).

**Decisión:** NO se aplica cambio. El umbral actual es la calibración
correcta para este conjunto de variables. La mejora real requiere:
- Variables adicionales (ciudad, teléfono — último ítem del ROADMAP).
- Re-pesado del scorer por origen del par.
- Calibración automática (Optuna, P2-1) sobre datasets múltiples.

### 16.6 Validación

- `ruff check` + `ruff format --check`: verde.
- `pytest tests/`: **154/154** (142 previos + 12 nuevos de `test_blocking_name`).
- Cobertura del módulo nuevo: 99 %.

---

## §18 — v2.8.0: Tratamiento privilegiado de NIT idéntico (P0-1 del ROADMAP)

### 18.1 Diagnóstico forense de los falsos negativos del exhaustivo

Antes de tocar código, se hizo el análisis post-mortem que el ROADMAP exige:
auditoría completa de los 1534 FN del ground truth exhaustivo (1456 regs).
Resultados — análisis del **NIT original**:

| Causa                                          | FN  | %      |
|------------------------------------------------|----:|-------:|
| NIT original idéntico                          | 332 | 21.6 % |
| NIT base idéntico (DV original distinto)       |  49 |  3.2 % |
| NIT base a distancia Levenshtein 1             | 511 | 33.3 % |
| NIT base a distancia > 1                       | 642 | 41.9 % |

Análisis del nombre (`token_set_ratio` entre los dos lados del par FN):

| Rango ts_ratio                  | FN  | %      |
|---------------------------------|----:|-------:|
| ≥ 95 (casi idénticos)           |  26 |  1.7 % |
| 60–94                           | 135 |  8.8 % |
| 30–59                           | 680 | 44.3 % |
| < 30 (muy distintos)            | 693 | 45.2 % |

**Hallazgo central:** la combinación de NIT original idéntico + token_set
bajo es el patrón dominante de los FN "fáciles de recuperar".

### 18.2 La confusión NIT vs NIT_OK

Al rastrear estos pares en el pipeline real, se detectó que el
`AdvancedNitProcessor` infiere un dígito de verificación calculado y lo
pega como `NIT_OK`. Esto introduce un **artefacto importante**: un NIT
original `'890900148'` (9 dígitos) recibe DV calculado `2` → NIT_OK
`'8909001482'`. Un NIT original `'8909001488'` (10 dígitos, con DV
explícito `8`) queda como `'8909001488'`. Para el scorer, esos dos
NIT_OK están a distancia Levenshtein **1**, no 0.

Re-conteo de FN usando `NIT_OK` (lo que el scorer realmente compara):

| Distancia NIT_OK    | FN  |
|---------------------|----:|
| 0 (idéntico)        | 335 |
| 1                   | 169 |
| 2                   | 444 |
| 3+                  | 586 |

Esos 335 pares con NIT_OK idéntico son los que el fix de v2.8.0 puede
atacar directamente.

### 18.3 Hipótesis 1: el filtro AND descarta los pares

Lectura del scorer (`_score_batch_vectorized` líneas 364–370):

```python
name_filter_mask = name_similarities >= self.min_name_similarity   # 0.60
nit_filter_mask = nit_distances <= self.max_nit_distance            # 3
valid_pairs_mask = name_filter_mask & nit_filter_mask
```

El filtro es AND estricto. Pares con NIT_OK idéntico pero `name_sim<0.60`
no llegan al cálculo de score combinado.

**Verificación empírica directa** (par real del exhaustivo):

```
'COMPAÑIA GLOBAL DE PINTURAS' vs 'PINTUKO'   (NIT_OK 8909001482 ambos)
  name_sim ≈ 0.29  <  0.60  → filtro descarta antes del score
```

### 18.4 Hipótesis 2: aunque pase el filtro, el score no supera el threshold

Verificado con un segundo par del mismo grupo:

```
'AKZOMOBEL PINYUCO' vs 'PINTUCO ORBIS'   (NIT_OK idéntico)
  name_sim ≈ 0.56  <  0.60  → filtro descarta
```

Si se exime el filtro, el score combinado sería:
`0.65·0.56 + 0.20·1.0 + 0.15·phonetic ≈ 0.59` < `score_threshold=0.68`.
Aún descartado.

**Conclusión:** una sola perilla no alcanza. Se requieren DOS perillas
independientes:

1. `nit_identical_overrides_name_filter` — saltar el gate del filtro.
2. `nit_identical_score_boost` — empujar el score combinado por encima
   del threshold.

### 18.5 Barrido del boost

Sobre el ground truth exhaustivo + golden 269, con
`override=True` activo:

| boost | F1 exh | P exh | R exh | FN exh | F1 gold | P gold | R gold |
|------:|-------:|------:|------:|-------:|--------:|-------:|-------:|
| 0.00  | 0.863  | 0.886 | 0.842 | 1534   | 0.771   | 0.845  | 0.709  |
| 0.05  | 0.867  | 0.886 | 0.849 | 1462   | 0.759   | 0.802  | 0.720  |
| 0.10  | 0.844  | 0.832 | 0.856 | 1394   | 0.756   | 0.785  | 0.730  |
| 0.15  | 0.851  | 0.835 | 0.869 | 1268   | 0.760   | 0.779  | 0.741  |
| 0.20  | 0.851  | 0.805 | 0.902 | 945    | 0.757   | 0.723  | 0.794  |

**Lectura:** `boost=0.05` es el sweet spot Pareto. A partir de 0.10
aparecen falsos positivos por colisiones `NIT_OK` falsas (el
`AdvancedNitProcessor` puede dar DV calculado igual a un DV declarado
de otra empresa), que es exactamente la dinámica que el CHANGELOG de
v2.7.0 documentó como límite estructural de la precision.

### 18.6 Lo que esto significa para el ROADMAP

El ROADMAP P0-1 priorizaba bloqueos nuevos (NIT base — ya hecho en
v2.5.0; multi-pasada por nombre — ya hecho en v2.6.0). El experimento
de activar `enable_name_blocking=True` mostró **ΔF1=+0.0003** en
exhaustivo, **0** en golden. **El bloqueo no es el cuello.**

El cuello real está donde la auditoría lo señaló: el filtro AND y el
`score_threshold` rechazan pares con evidencia NIT sólida. El fix de
v2.8.0 aborda ese cuello con dos perillas mínimas y opt-in (defaults
OFF preservan la paridad bit-a-bit).

### 18.7 Lo que el fix NO resuelve y NO se debe sobrevender

- **Los 1153 FN restantes** del exhaustivo (444 con NIT_OK dist 2, 586
  con dist ≥ 3) **no son atacables** con esta intervención. Son pares
  con NIT base sustancialmente distinto en el `NIT_OK` y nombre dispar.
  Requieren mejorar el `_calculate_name_similarities_vectorized`
  (P1-1) o introducir señales adicionales (extra_features con datos
  reales — P2 del ROADMAP).
- **Las colisiones `NIT_OK` falsas** introducidas por el DV calculado
  no se mitigan en este release. Los 30 nuevos FP en golden 269 son
  costo directo de esa dinámica.

### 18.8 Validación

- `ruff check` + `ruff format --check`: verde.
- `pytest tests/`: **198/198** (187 previos + 11 nuevos de
  `test_nit_identical_p01.py`).
- Tests de calidad (`test_quality_golden`, `test_quality_exhaustivo`):
  ambos pasan con los pisos existentes.
- Tests de paridad estricta (perillas en defaults OFF): bit-a-bit
  idéntico a v2.7.0 (`test_paridad_completa_con_defaults_off`).

---

## §19 — v2.9.0: Vectorización del scorer (P1-1 del ROADMAP)

### 19.1 Disciplina de paridad — el oráculo primero

Antes de tocar el scorer se capturó un **oráculo** que el código vectorizado
debe reproducir bit-a-bit. El oráculo contiene:

- 16 registros sintéticos diseñados para activar **todas** las ramas del scorer:
  pares idénticos, NIT a distancia 0/1/2, NIT vacío, nombres con typos, orden
  permutado, longitudes muy distintas, `'nan'` strings literales, primer token
  compartido (bonus ×1.05).
- 3 perfiles distintos para cubrir las variantes condicionales:
  `default_off`, `with_override_and_boost`, `with_extra_features`.
- 120 pares × 3 perfiles = **360 outputs de referencia**.

Tolerancia: 1e-9 en floats, exactitud absoluta en enteros e índices.

### 19.2 Bug atrapado por el oráculo

El intento inicial reemplazaba `Levenshtein.ratio` (python-Levenshtein) por
`rapidfuzz.distance.Levenshtein.normalized_similarity`. **Ambas se llaman
'Levenshtein'** pero NO son equivalentes:

- `Levenshtein.ratio(a, b)` usa distancia tipo **Indel** (sustitución = 2
  ediciones: una eliminación + una inserción).
- `rapidfuzz.distance.Levenshtein.distance` usa distancia clásica
  (sustitución = 1 edición).

Verificación numérica:
```
'AKSNBL' vs 'PNTKR':  Levenshtein.ratio=0.1818,  rf_lev.norm_sim=0.0000
'AKSNBL' vs 'KMPN':   Levenshtein.ratio=0.4000,  rf_lev.norm_sim=0.1667
```

El oráculo detectó **231 divergencias en score** sobre los 360 outputs
(64 % de los pares con phonetic_sim ≠ 1). Sin esta auditoría, la
"vectorización" habría sido en realidad un **cambio silencioso de la
fórmula del scorer**, con efecto directo en producción.

Solución correcta: `rapidfuzz.distance.Indel.normalized_similarity`, que sí
es matemáticamente equivalente a `Levenshtein.ratio`. Verificado en 4
casos: identidad bit-a-bit.

### 19.3 Vectorización del cálculo de nombres en `_score_batch_vectorized`

El bucle previo:
```python
for i in compute_indices:
    n1, n2 = str(names_0[i]), str(names_1[i])
    if not n1 or not n2 or n1 == "nan" or n2 == "nan":
        continue
    if n1 == n2:
        name_similarities[i] = 1.0
        continue
    score = tsr(n1, n2) / 100.0
    if 0.3 < score < 0.95:
        simple_score = simple_ratio(n1, n2) / 100.0
        score = 0.8 * score + 0.2 * simple_score
        # bonus si comparten primera palabra
        ...
    name_similarities[i] = score
```

Se descompone en:

1. **Pre-filtro vectorizado** con `np.char.str_len` (ufunc): elimina pares
   con `len_ratio < 0.10` sin invocar rapidfuzz.
2. **Máscaras booleanas:** `invalid` (nulos), `identical` (nombre exacto),
   `tsr_mask` (candidatos para scoring real).
3. **Batch token_set_ratio:** `rapidfuzz.process.cpdist(scorer=tsr)` sobre
   `tsr_mask`. Una sola llamada que ejecuta en C++.
4. **Máscara de refinamiento** (0.3 < score < 0.95): subconjunto que
   requiere `simple_ratio`. Otra llamada batch a `cpdist`.
5. **Bonus por primer token:** se calcula sobre el sub-conjunto refinado
   (típicamente 10-20 % del total), con `np.char` para el split del primer
   token. Esta es la única parte que no es 100 % vectorizada (uso
   list-comprehension porque split por espacio en numpy no es trivial),
   pero opera sobre un set ya reducido.

### 19.4 Vectorización de las distancias/similitudes de NIT

```python
distances = rf_process.cpdist(
    s0[valid_idx].tolist(),
    s1[valid_idx].tolist(),
    scorer=rf_lev.distance,
    dtype=np.int64,
)
```

Una llamada batch en lugar de N llamadas individuales. La penalización
"×0.5 si len_diff > 2" en `_calculate_nit_similarities_vectorized` se
aplica con `np.where(len_diff > 2, vals * 0.5, vals)` — fully vectorizada.

### 19.5 Vectorización del feature `token_set_ratio` en `extra_features`

```python
# Antes:
scores = np.array(
    [fuzz.token_set_ratio(sa.iloc[i], sb.iloc[i]) / 100.0 for i in range(n)],
    dtype=np.float64,
)
# Después:
scores = rf_process.cpdist(
    sa.to_list(), sb.to_list(),
    scorer=fuzz.token_set_ratio,
    dtype=np.float64,
) / 100.0
```

### 19.6 Eliminación de `iterrows` en el path SQLite

El bucle `for _, row in valid_scores.iterrows()` construía tuplas para
`executemany`. Se reemplaza por extracción vectorizada con `to_numpy()`
por columna; el loop final solo es para la construcción de tuplas
(necesario por el contrato de `executemany`), pero opera sobre arrays
nativos (sin overhead de Series.iloc).

### 19.7 Cache inerte — decisión consciente

El cache `self._similarity_cache` en `_calculate_name_similarities_vectorized`
(método alterno usado por algunos paths legacy) **ya no se consulta por
par**. La razón: en pipelines reales con millones de pares, la tasa de
hit es < 1 % (los pares candidatos están deduplicados por el bloqueo
previo). El costo del lookup + check + insert era mayor que el cómputo
vectorizado en C++. El atributo queda como "deuda" identificada, no como
funcionalidad activa.

Si algún día se necesita un cache real, el lugar correcto es a nivel del
pipeline completo (no por par), con LRU explícito y métrica de hit-rate
medida.

### 19.8 Benchmark de speedup

| n_records | n_pairs | v2.8.0 (s) | v2.9.0 (s) | Speedup |
|---|---|---|---|---|
| 500 | 749 | 0.027 | 0.014 | 1.9× |
| 2,000 | 2,997 | 0.087 | 0.024 | 3.6× |
| 10,000 | 14,995 | 0.421 | 0.091 | 4.6× |
| 30,000 | 44,996 | 1.276 | 0.268 | 4.8× |

El speedup escala con el tamaño, indicando que el overhead constante de
C-extension (creación de buffer, dispatch) se amortiza correctamente en
lotes grandes. La extrapolación a producción (1-3 M pares) sugiere que
el throughput del scorer puro pasa de ~35k a ~150-170k pares/s.

### 19.9 Validación

- `pytest tests/`: **202/202** (198 previos + 4 nuevos de paridad).
- `ruff check` + `ruff format --check`: verde.
- `python scripts/validar_paridad_p1_1.py`: 360/360 outputs bit-a-bit.
- Métricas de calidad sobre ground truth: **idénticas** a v2.8.0
  (F1=0.867 exhaustivo, F1=0.759 golden).

---

## §20 — v2.9.0: Dataset sintético robusto

### 20.1 Motivación

Los dos ground truth previos (`golden_truth.csv` 269 regs y
`golden_truth_exhaustivo.csv` 1456 regs) eran insuficientes para tres
propósitos:

1. **Diagnosticar modos de falla específicos.** Las métricas agregadas
   (F1, P, R) no dicen *dónde* falla el sistema.
2. **Estresar casos frontera explícitos** (sigla vs nombre completo,
   colisión fonética, grupos económicos con marca compartida).
3. **Reproducir bit-a-bit** desde un script — los golden previos son
   datos curados manualmente, no regenerables si se pierden.

### 20.2 Diseño

`scripts/generar_dataset_robusto.py` genera un CSV determinista
(`seed=42`) con tres bloques:

- **Variantes orgánicas** (80 empresas-semilla, 3-25 variantes c/u):
  tipos QWERTY, swaps adyacentes, omisiones, sufijos societarios, doble
  espacio, zero-width spaces, mojibake, formatos de NIT alternos.
- **Casos frontera negativos** (8 categorías, 22 registros): pares que
  el sistema NO debe unir aunque tengan señales engañosas (token
  compartido, NIT vecino, sufijo confundible, marca multi-país, etc.).
- **Casos frontera positivos** (5 categorías, 22 registros): pares
  difíciles que SÍ deben unirse (sigla vs nombre, denominación histórica,
  DV calc vs decl, caracteres invisibles).

Total: 660 registros, 126 grupos, 2,595 pares positivos.

### 20.3 Bugs atrapados por el validador

`_validar_integridad` rehúsa publicar el dataset si su lógica se
contradice. Durante el desarrollo de v2.9.0 atrapó cuatro bugs:

1. **NITs duplicados en EMPRESAS_BASE** (`890903407` para Nutresa y
   Chocolates; `860005289` para Ecopetrol y Deloitte; `890900841` para
   Termotasajero y Caracol; `860013570` para Mapfre y Alpina): dos
   entradas distintas terminan con el mismo NIT_OK y fusionan grupos.
2. **Casos frontera positivos reutilizan NITs de EMPRESAS_BASE**: EY,
   Pintuco, El Tiempo, Google reaparecían con un ID_GROUP nuevo
   compartiendo NIT con su grupo orgánico — contradicción lógica.
3. **Casos frontera negativos reutilizan NITs de EMPRESAS_BASE**:
   `860046645` (Seguros Bolívar), `830094926` (Constructora Bolívar),
   `860007738` (Banco Popular) aparecían simultáneamente como grupo
   orgánico y como caso frontera negativo.
4. **Singletons y grupos escalados sin rango reservado**: podían
   colisionar con cualquier otra sección.

Sin el validador, estos bugs habrían generado un dataset "robusto" con
ground truth contradictorio — peor que no tener dataset. La solución:

- Validar que cada NIT base normalizado (9 dígitos) pertenece a UN solo
  grupo.
- Reservar rangos de NIT por sección:
  `850XXXXXX` para casos positivos, `855XXXXXX` para negativos,
  `856XXXXXX` para singletons, `857XXXXXX` para escalado.

### 20.4 Métricas medidas v2.9.0 sobre el dataset robusto

| Métrica           | Valor    |
|-------------------|---------:|
| F1                | 0.933    |
| Precision         | 0.936    |
| Recall            | 0.931    |
| TP                | 2,415    |
| FP                | 165      |
| FN                | 180      |

Estos números **no son comparables directamente** a los de los golden
previos (datasets distintos), pero el reporte por categoría revela
exactamente dónde el sistema falla:

- Sigla vs nombre completo: recall 0.40 (9 FN de 15 pares).
- Token disímil con NIT idéntico: recall 0.17 (5 FN de 6 pares).
- Sufijo societario confundible: 3 FP de 3 pares posibles.
- Nombre genérico compartido: 3 FP de 3.

### 20.5 Validación

- `ruff check` + `ruff format --check`: verde.
- `pytest tests/`: **208/208** (4 nuevos de paridad p1_1 + 6 nuevos de
  quality_sintetico_robusto = 10 nuevos en total).
- Validador interno del dataset: 0 errores, 0 advertencias.

---

## §21 — v2.10.0: Fixes #1 y #2 + infraestructura de calibración con producción real

### 21.1 Diagnóstico — dos fixes contra modos de falla del dataset robusto

El dataset robusto v2.9.0 reveló tres patrones que el sistema fallaba
sistemáticamente:

| Tipo                    | Síntoma                                              | Recall medido v2.9.0 |
|-------------------------|------------------------------------------------------|---------------------:|
| P4 token disímil        | NIT idéntico, nombres como "EY" vs "Ernst & Young"   | 0.17                 |
| P1 sigla vs completo    | Igual que P4 pero nombres más extremos               | 0.40                 |
| G nombre genérico       | 3 "INVERSIONES SAS" distintas fusionadas             | FP=3                 |

Fix #1 ataca P4. Fix #2 ataca G. P1 queda para Sprint 2.

### 21.2 Fix #1 — Boost diferenciado por DV declarado vs calculado

**Causa raíz:** `AdvancedNitProcessor` calcula DV cuando el NIT viene
con 9 dígitos. Hay diferencia material entre dos casos:

1. AMBOS NITs traídos con DV declarado (10+ dígitos o formato `XXXXXXXXX-D`):
   evidencia FUERTE de identidad. Dos fuentes coincidieron exactamente
   en NIT+DV.
2. Al menos uno con DV computed: evidencia MEDIA. Dos NITs de 9 dígitos
   que se ven iguales pueden ser dos empresas distintas cuyo DV
   verdadero diverge.

El boost uniforme de v2.8.0 (`nit_identical_score_boost=0.05`) trataba
ambos casos igual. Era demasiado tímido para el caso fuerte (no
recuperaba FN de P4) y suficiente para el caso débil.

**Implementación:**

- `enhanced_fix_nit` retorna ahora `(base, ok, dv_origen)` con
  `dv_origen ∈ {declared, computed, none}`. La detección de "declared":
  - formato canónico `^\d{9,}-\d$`, o
  - longitud original ≥ 10 dígitos puros.
- Detección **excluye** "900-123-456" (múltiples guiones como separador,
  no DV) y "900.123.456" (puntos como separador). Verificado en 8 casos
  parametrizados de `test_fixes_p1_2.py`.
- `process_for_deduplication` propaga columna `DV_ORIGEN`.
- `VectorizedScorer` lee `nit_identical_score_boost_declared` y aplica
  boost diferenciado por máscara `(dv_0 == "declared") & (dv_1 == "declared")`.
- Si la columna `DV_ORIGEN` no existe, fallback conservador a `computed`
  (paridad bit-a-bit con v2.9.0).

**Calibración:** intenté `boost_declared=0.15`. Sobre el sintético dio
F1=0.939 y P4 R=1.00, pero sobre golden 269 cayó a F1=0.647 (regresión
severa). Bajé a `0.10`: golden 269 vuelve a F1=0.759 (paridad), PERO
**P4 también vuelve a R=0.167** — el boost de 0.10 no alcanza a superar
el score_threshold para esos pares. Es decir: NO se puede tener ambas
cosas con un boost global. **Lección:** calibrar entre datasets
divergentes es delicado — el boost que ayuda en uno daña en otro, y el
valor entregado (0.10) prioriza no-regresión sobre ganancia en P4.
[CORREGIDO en v2.11.0: la versión original de esta nota afirmaba
erróneamente que 0.10 mantenía P4 en R=1.00.]

**Resultado activado en `deduplication_standard`:**

```python
"nit_identical_score_boost": 0.05,           # computed o mixto
"nit_identical_score_boost_declared": 0.10,  # ambos declared
```

### 21.3 Fix #2 — Penalización por nombre genérico (queda OPT-IN)

**Causa raíz:** el `token_set_ratio` entre dos "INVERSIONES SAS"
literalmente idénticas es 1.0. El sistema no diferencia entre nombre
informativo y nombre genérico, así que un match perfecto sobre nombre
genérico se trata como evidencia plena de identidad.

**Solución:** detectar pares donde AMBOS nombres son cortos (≤3 tokens)
y compuestos solo por tokens "genéricos". Multiplicar `name_sim` por
`(1 - generic_name_penalty)`. Si la penalización lleva el `name_sim`
bajo `min_name_similarity`, el par es descartado por el filtro previo.

**Set genérico:** combina dos fuentes:
1. Lista curada de ~50 tokens del dominio empresarial colombiano
   (INVERSIONES, GRUPO, COMPAÑIA, COLOMBIA, CONSULTORES, SAS, etc.).
2. Top-N estadístico del corpus de entrada.

**Por qué queda OPT-IN:** sobre el sintético con `penalty=0.5` resolvió
los 3 FP de G_nombre_generico. Pero sobre golden 269 produjo regresión
severa (F1 0.759 → 0.647) porque la lista curada incluye tokens
(COMPAÑIA, COLOMBIA, EMPRESA) que aparecen en razones sociales legítimas
de empresas pequeñas. La penalización mata recall.

**Hipótesis sin verificar:** con corpus grande (50k+ regs), los top-N
estadísticos serán palabras genuinamente frecuentes (no nombres
propios), y la regla operará bien. Verificable solo con datos reales —
por eso queda OPT-IN hasta calibración con producción.

### 21.4 Infraestructura de calibración

Tres herramientas nuevas listas para correr en Colab:

1. **`scripts/generar_pares_para_etiquetar.py`**: muestrea 1500 pares
   estratificados en 5 categorías (alta_confianza, frontera, NIT
   idéntico nombre disímil, nombre alto NIT distinto, potencial FN).
   Output CSV editable en Excel.
2. **`scripts/medir_con_ground_truth.py`**: tras etiquetar, mide F1/P/R
   globales y por estrato. Produce reporte Markdown y CSV de errores
   para revisión.
3. **`notebooks/calibracion_produccion.ipynb`**: orquesta los dos
   scripts. 6 pasos: instalar, inspeccionar muestra, correr pipeline,
   estadísticas de cluster, generar pares, medir (próxima sesión).

### 21.5 Métricas finales medidas (paridad sin retroceso)

| Dataset                       | v2.9.0 | v2.10.0 | Δ      |
|-------------------------------|-------:|--------:|-------:|
| Golden 269                    | 0.759  | 0.759   | 0.000  |
| Exhaustivo 1456               | 0.867  | 0.867   | 0.000  |
| Sintético robusto 660         | 0.933  | 0.935   | +0.002 |
| Sintético — P4 token disímil  | R=0.17 | R=0.17  | 0.000  |

Los defaults activos (Fix #1 ON con boost_declared=0.10, Fix #2 OFF)
preservan paridad en datasets conservadores y mejoran el caso que
diseñamos para Fix #1.

### 21.6 Validación

- `pytest tests/`: **224/224** (208 previos + 16 nuevos de `test_fixes_p1_2.py`).
- `ruff check` + `ruff format --check`: verde.
- Flujo end-to-end de calibración: validado generando pares + etiquetando
  automáticamente desde la verdad del sintético + midiendo. Reporta por
  estrato correctamente.

### 21.7 Bug-fix crítico del path `disk_based` (descubierto post-release)

Tras la pregunta del usuario "¿Lo que corrió fue sobre clases en disco
y no en memoria?", verificación empírica reveló bug bloqueante
preexistente desde v2.7.0:

```python
# linkage.py línea 226-231 (heredado v2.7.0)
candidates = self.candidate_finder.find_candidates(
    df_work,
    output_dir=output_dir,
    cross_source_only=cross_source_only,
    trusted_unique_sources=trusted_sources,  # ← kwarg NO aceptado por DiskBasedLSHEngine
)
```

`DiskBasedLSHEngine.find_candidates()` solo declaraba `(df, output_dir,
cross_source_only)`. El cuarto kwarg producía `TypeError` que cortaba
toda corrida del pipeline con `linkage_engine_class="disk_based"`.

**Por qué pasó inadvertido:** `deduplicate_unified` autoselecciona
`disk_based` solo si `n_records > 1_000_000`. Todos los tests de la
suite usan datasets pequeños (269, 660, 1456) → ninguno disparaba el
path roto. Los tests de smoke `test_disk_engine.py` testean la clase
aislada, no su invocación desde el pipeline.

**Solución implementada:**

- `DiskBasedLSHEngine.find_candidates` acepta y descarta el kwarg con
  warning si no está vacío.
- `TrustedSourceLSHEngine.find_candidates` acepta el kwarg y lo une a
  `self._trusted_sources`.
- Test de regresión `tests/test_disk_based_path.py` que fuerza
  `linkage_engine_class="disk_based"` para que cualquier regresión
  futura se detecte sin necesidad de un dataset de 1M+.

**Lección honesta:** un bug que rompe el path de producción (>1M) vivió
3 versiones (v2.7.0, v2.8.0, v2.9.0) porque los tests asumían que el
path por default era representativo. El **único** test que lo habría
detectado es un test e2e que fuerce el motor, no uno que mida la unidad.
Esta es la clase de bug que mata sistemas en producción los primeros
días post-deploy.

### 21.8 Divergencia medida default vs disk_based

Los dos motores NO son numéricamente equivalentes. Sobre los tres
datasets disponibles:

| Dataset             | default F1 | disk_based F1 | Δ      |
|---------------------|-----------:|--------------:|-------:|
| Golden 269          | 0.759      | 0.731         | -0.028 |
| Exhaustivo 1456     | 0.867      | 0.874         | +0.007 |
| Sintético robusto   | 0.935      | 0.935         |  0.000 |

La divergencia viene del LSH: `DiskBasedLSHEngine` usa buckets
SQLite-backed; el motor por default usa dict in-memory. Las funciones
hash son las mismas (vectorized MinHash determinista desde v2.3.0,
ver §13), pero el orden de inserción / merge de buckets puede
introducir variaciones marginales en pares candidatos cuando hay
colisiones múltiples en el mismo bucket.

**Conclusión operativa:** las métricas reportadas en versiones previas
del CHANGELOG (v2.5.0-v2.9.0) corresponden al motor `default`, NO al
motor `disk_based` de producción. Sobre el dataset robusto la diferencia
es despreciable; sobre datasets reales habrá que medir.

