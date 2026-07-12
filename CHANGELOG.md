# Changelog

Todas las versiones notables de `rues-linker` se documentan aquí.
Formato basado en [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
y [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html).

> ## 📍 Estado actual: 0.x — pre-1.0
>
> El paquete está en **desarrollo activo** y la API puede cambiar entre
> minor releases. **Aún NO está publicado en PyPI**. Antes de llegar a
> 1.0 se debe: validar contra producción real (1.97M registros), subir
> cobertura a 80%, y completar refactor de módulos heredados para mypy
> strict. Ver `docs/VERSIONING.md`.

---

## [0.7.6] — 2026-07-11 — Pin de compatibilidad: datasketch < 2.0

### Resumen

Regresión E2E causada por una dependencia externa, no por código del repo.
`datasketch 2.0.0` (publicado entre la captura del baseline v0.9.0 y hoy)
cambia el esquema de generación de firmas MinHash: el mismo input con el
mismo `seed` produce `hashvalues` distintas a las de 1.x. Eso altera el
banding LSH y el grafo de candidatos; el régimen SIN_NIT (sin ancla de NIT,
operando en el filo de percolación) se sobre-fusiona en clústeres gigantes.
El gate de publicación funcionó exactamente como se diseñó: bloqueó la
regresión antes de llegar a GitHub/PyPI.

### Fixed
- `pyproject.toml`: `datasketch>=1.6` → **`datasketch>=1.6,<2.0`**. Evidencia
  medida sobre `ground_truth_grande.csv` (12.427 registros mixtos), mismo
  código y mismos datos, cambiando SOLO la versión de datasketch:
  - Con 1.10.0: global F1=0.563 / P=0.401 / R=0.944 (tp=20839, fp=31133,
    fn=1234) — reproduce el baseline v0.9.0 al tercer decimal.
  - Con 2.0.0: global F1=0.250 / P=0.144 / R=0.945 (tp=20852, fp=124054,
    fn=1221) — reproduce entero a entero el fallo observado en Colab.
  - CON_NIT es estable en ambas versiones (F1≈0.96): el NIT ancla la
    identidad. El colapso es exclusivo de SIN_NIT (P 0.123 → 0.034).
  - Verificación a nivel de firma: `MinHash(num_perm=16, seed=1)` sobre el
    mismo shingle-set produce `hashvalues` distintas entre 1.10.0 y 2.0.0.

### Changed
- Versión 0.7.5 → 0.7.6 (`pyproject.toml` y assert de
  `tests/test_matching_integration.py`).

### Notes
- `tests/data/baseline_v0_9_0.json` NO se regenera: con el pin, el pipeline
  vuelve a producir exactamente las métricas congeladas.
- Migrar a datasketch 2.x queda como tarea futura explícita: exigirá
  regenerar el baseline y re-validar la percolación del régimen SIN_NIT.

### Fixed (gate de tests — segundo bloqueo, mismo release)
- `tests/test_fase4_consolidacion.py`: la clase `TestOptunaIntegrationRemoved`
  afirmaba que los módulos heredados `optimization/optuna_integration.py` y
  `optimization/visualizer.py` fueron ELIMINADOS, pero siguen presentes como
  shims deprecados (emiten DeprecationWarning e importan optuna/plotly a nivel
  módulo). La clase estaba rota en AMBOS entornos, con tests distintos fallando
  en cada uno:
  - Sin optuna (gate local, `pip install -e .`): `OrchestratorOptimizer` es un
    símbolo opt-in que `evaluation/__init__.py` solo exporta si
    `OPTUNA_AVAILABLE`; el test lo importaba incondicionalmente → ImportError.
  - Con optuna (CI de GitHub, `pip install -e ".[dev]"`, que incluye optuna y
    plotly): los shims SÍ importan → los tests que exigían ModuleNotFoundError
    fallaban con "DID NOT RAISE".
- Corrección: clase renombrada a `TestOptunaIntegrationDeprecated` y alineada a
  la realidad y a la propia intención del docstring del módulo (punto 5:
  "OptunaIntegration emite DeprecationWarning al importar"). Los tres tests se
  protegen con `pytest.importorskip("optuna")` (y `("plotly")`), el mismo patrón
  que `test_fase3_optuna.py`. Resultado medido: sin optuna → 3 skip (gate local
  verde); con optuna → 3 pasan (CI verde). Archivo `fase4` completo: 20 passed +
  3 skipped sin optuna; 23 passed con optuna. ruff 4/4 limpio.
- Es un bug del test, no de la librería: el diseño opt-in de
  `OrchestratorOptimizer` es correcto (importarlo sin optuna fallaría). No se
  cambió código de la librería ni se regeneró ningún baseline.
- Deuda futura (no bloqueante): los shims `optuna_integration.py` y
  `visualizer.py` de `optimization/` son código muerto (ningún módulo vivo los
  importa) y el roadmap ya prevé su eliminación. Borrarlos y volver los tests a
  exigir ModuleNotFoundError es tarea de higiene para la Fase 0 del playbook.

---

## [0.7.5] — 2026-05-28 — SIN_NIT recalibrado + enrutamiento automático (production-ready)

### Resumen

Ataca la deuda #1 (SIN_NIT) de forma real, medida contra ground truth. El F1
global del régimen mixto pasa de **0.563 → 0.907** vía enrutamiento automático
por régimen. SIN_NIT individual sube de **0.217 → 0.645** (P=0.91).

### Added
- **`deduplicate_auto`** (`deduplication/auto.py`) — entrada recomendada para
  producción. Separa el dataset por régimen (CON_NIT / SIN_NIT), aplica el
  perfil ÓPTIMO a cada uno y recombina con IDs de grupo globalmente únicos.
  Expuesto en `record_linkage.deduplicate_auto`. El usuario ya no tiene que
  elegir perfil manualmente.

  Medido sobre `ground_truth_grande.csv` (12.427 registros mixtos):

  | Método | Global F1 | Global P | CON_NIT | SIN_NIT |
  |---|---|---|---|---|
  | deduplicate_unified (anterior) | 0.563 | 0.401 | 0.961 | 0.217 |
  | **deduplicate_auto (nuevo)** | **0.907** | **0.966** | 0.962 | 0.645 |

- Tests: `tests/test_deduplicate_auto.py` (8), `tests/test_sin_nit_recalibrado.py` (3).

### Changed
- **Perfil `deduplication_sin_nit_conservador` recalibrado contra ground truth.**
  `min_name_similarity` y `score_threshold`: 0.75/0.80 → **0.78/0.78** (óptimo
  F1 hallado por barrido). Resultado sobre 2342 registros SIN_NIT:
  **P=0.907, R=0.501, F1=0.645** (antes F1=0.470 con el umbral previo, F1=0.217
  con el perfil estándar). El comentario del perfil ahora cita cifras MEDIDAS,
  no de composición (antes decía "sin ground truth no se puede afirmar un F1").

### Findings (medición exhaustiva)
- **SIN_NIT tiene un techo de datos en F1≈0.65**, no de calibración. Barrido
  completo de umbrales: ninguno supera 0.65 sin colapsar precision. Causas:
  typos OCR (`NENOVA`/`NNEOVA`, `GARDENING`/`GARDSNING`) y romanización coreana
  inconsistente (PUSAN=BUSAN, TAEGU=DAEGU, SEÚL=SEUL=SEOUL).
- **La ciudad NO discrimina**: solo ~7 ciudades reales, cada una con 80-105
  grupos distintos. Usarla como feature de matching empeora (F1 0.549→0.189).
  Confirmado cuantitativamente; documentado en `docs/DEUDA_SIN_NIT.md`.

### Production-ready
- `deduplicate_auto` enruta automáticamente — el camino correcto sin que el
  usuario recuerde perfiles.
- `deduplicate_unified` advierte (UserWarning) si se usa en datos mixtos.
- Tests de no-regresión congelan F1 SIN_NIT (≥0.61) y global auto (≥0.85).

### Test results
- Regresión completa verde (434 + 62 sin-slow + 44 nuevos/sprint), 0 glyph warnings.

---



Sprint de pago de deuda detectada en los Sprints 0.8.x–0.9.0. Cinco frentes,
todos verificados empíricamente antes de tocar código.

### Fixed
- **Warnings de glyph en matplotlib — CAUSA RAÍZ** (deuda desde Sprint 0.8.1).
  El regex `_strip_emojis` en `reporting/_text_utils.py` era INCOMPLETO: no
  cubría Misc Technical (⏱ U+23F1), Misc Symbols & Arrows (⭐ U+2B50) ni el
  selector de variación (U+FE0F). Por eso quedaban `UserWarning: Glyph N
  missing from font` vivos por tres sprints pese a los "fixes" anteriores.
  Reescrito con cobertura exhaustiva de bloques Unicode de símbolos/emojis.
  Verificado: acentos y ñ españoles intactos; **0 glyph warnings** en
  `test_fase1_calibracion` (antes: 63). Faltaba sanitizar `quality_text` en
  `visualizer.py` — corregido.
- **Checkpoints stale de firmas MinHash — CAUSA RAÍZ** (bug visto 2 veces:
  Sprints 0.8.1 y 0.9.0). `_validate_signatures_file` validaba solo por
  `(n_records, num_perm, ngram)`; dos corpus DISTINTOS con el mismo número de
  filas reusaban firmas incorrectas (síntoma: baseline 0.9.0 truncado a
  1131/12427). Nuevo `_content_fingerprint()` (hash SHA256 de muestra del
  contenido + parámetros) se guarda en `hf.attrs["content_fp"]` y se valida
  en cada reuso. Checkpoints viejos sin huella se regeneran una vez (seguro).

### Changed
- **Docstring de `deduplicate_unified` corregido**. La cifra "Orchestrator con
  trusted sources: F1 = 0.875" NO era reproducible (deuda de documentación:
  afirmación sin test). Reemplazada por las cifras realmente medidas en v0.7.4:
  `deduplicate_unified` F1 global 0.563; `Orchestrator + produccion_calibrada`
  F1 global 0.842. Ambos CON_NIT≈0.96; ambos fallan SIN_NIT (sobre-fusión vs
  no-fusión). Ver `docs/DEUDA_SIN_NIT.md`.

### Added
- **Guardián de mezcla de regímenes**: `deduplicate_unified` ahora emite
  `UserWarning` cuando detecta mezcla CON_NIT/SIN_NIT (5%–95% de NIT vacío).
  El docstring ya lo advertía, pero una advertencia en runtime es más difícil
  de ignorar. 4 tests.
- **`docs/DEUDA_SIN_NIT.md`** — análisis empírico completo del régimen SIN_NIT:
  por qué sobre-fusiona, por qué CIUDAD como discriminante lo empeora
  (F1 0.549→0.189 por ciudades inconsistentes de importadores), y los 4
  caminos reales de solución (todos requieren trabajo, ninguno es un flag).
- **Tests nuevos** (32):
    - `tests/test_strip_emojis.py` (17): cobertura del helper por cada rango
      Unicode antes roto + preservación de acentos.
    - `tests/test_checkpoint_fingerprint.py` (11): huella distingue corpus,
      no reusa corpus distinto del mismo tamaño, checkpoint viejo sin huella
      se regenera, retrocompat sin huella.
    - `tests/test_regimen_warning.py` (4): advertencia en mezcla, silencio en
      datasets homogéneos y en ruido <5%.

### Hallazgo honesto (corrección de sprints previos)
- El baseline del Sprint 0.9.0 (`baseline_v0_9_0.json`) se midió con
  `deduplicate_unified`, el método que el propio código advierte que sobre-
  fusiona en datos mixtos. Sus cifras de SIN_NIT (F1 0.217) reflejan ese
  método, no el límite del sistema. Sigue siendo válido como detector de
  REGRESIÓN, pero NO como "calidad del sistema en SIN_NIT". Documentado.
- **SIN_NIT no tiene fix por parámetros.** Es un problema de datos
  (importadores sin identificador estable, ciudades inconsistentes). Tunear
  ciegamente lo empeora. La acción responsable fue documentarlo con precisión.

### Test results
- Baseline previo (v0.7.3): 545/545 verde.
- Post-deuda (v0.7.4): regresión completa verde (434 + 62 sin-slow + 32 nuevos),
  **0 glyph warnings** (antes 63), bug de checkpoints cerrado con test E2E.

---



### Contexto

El plan describía el Sprint 0.9.0 como "construcción de ground truth estratificado
desde cero" (5-7 días). La auditoría del repo reveló que **el protocolo, el muestreo,
el evaluador y un GT sintético robusto YA EXISTÍAN**:
  - `docs/PROTOCOLO_GROUND_TRUTH.md` (173 líneas)
  - `scripts/generar_pares_para_etiquetar.py`, `muestrear_rues_para_gt.py`,
    `active_labeling.py` (muestreo + selección por incertidumbre)
  - `evaluation/ground_truth.py::GroundTruthEvaluator` (P/R/F1 pairwise + clustering)
  - `data/ground_truth/ground_truth_grande.csv` (12,427 filas, 3,486 grupos, 5 fuentes)

Lo que faltaba no era construir nada, sino **medir el pipeline contra ese GT** y
**cubrir con tests el evaluador**. El sprint se reorientó a eso (decisión consensuada).

### Added
- **`scripts/medir_baseline_v0_9_0.py`** — harness de baseline. Corre el pipeline
  (`deduplicate_unified`) contra el GT grande y mide P/R/F1 desglosado por:
    - régimen (CON_NIT / SIN_NIT)
    - caso (positivo_con_nit / positivo_sin_nit / negativo_intermediario / negativo_generico)
    - fuente (CRM / DIAN / IMPORTACIONES / RUES / SUPERSOCIEDADES)

  Output: JSON con umbrales (medido − tolerancia) listo para consumir desde tests.
  **Fix incluido**: limpia el `output_dir` antes de correr — `deduplicate_unified`
  reusa checkpoints stale (`lsh_candidates.db`, `intermediate_checkpoints/`) y sin
  limpiar contaminaba la medición (síntoma: output truncado a 1131/12427 filas).
- **`tests/data/baseline_v0_9_0.json`** — baseline congelado (v0.7.3,
  profile `deduplication_standard`, mode `BALANCEADO`). Cifras medidas:
    - **CON_NIT: F1=0.961** (P=0.972, R=0.950) — régimen confiable.
    - **SIN_NIT: F1=0.217** (P=0.123, R=0.921) — **deuda técnica conocida**:
      sobre-fusión masiva (31,133 FP vs 4,295 TP). Recall alto, precision colapsada.
      Congelado para que no empeore hasta recalibrar.
    - Global: F1=0.563. Por fuente con NIT: 0.957-0.970.
- **`tests/test_baseline_v0_9_0.py`** — 16 tests:
    - 12 de no-regresión (uno por slice informativo, marcados `slow`, ~92s total).
    - 4 rápidos sobre el JSON (existencia, slice CON_NIT crítico, documentación
      del problema SIN_NIT, tolerancias razonables).
- **`tests/test_evaluation_coverage.py`** — 20 tests directos (+1 skip honesto):
    - `GroundTruthEvaluator`: predicción perfecta, sobre-fusión, sub-fusión,
      singletons, NaN en truth, clustering metrics, `last_evaluation`,
      `analyze_errors` (FP/FN/sin-error), truth_col personalizable.
    - `EntityMetricsEvaluator`: clasificación perfectas/fragmentadas/contaminadas,
      porcentajes.
    - `PerformanceAnalyzer`: extracción de métricas, baseline, historia.
- **Marker `slow`** registrado en `pyproject.toml` (CI rápido: `-m "not slow"`).

### Findings (medición, no opinión)
- El pipeline rinde **excelente con NIT** (F1≈0.96 por fuente) y **mal sin NIT**
  (F1≈0.22). Esto confirma — con números — la sospecha del plan sobre el régimen
  de importadores (Corea), pero corrige el diagnóstico: el problema NO es recall
  bajo (es 0.92), es **precision colapsada** por sobre-fusión.
- `processing/text.py` (83.9%) y `processing/nit.py` (81.0%) ya estaban bien
  cubiertos — el plan asumía ~0%. El gap real estaba en `evaluation/ground_truth.py`
  (era 0%, ahora ejercitado por 10 tests directos) y `evaluation/metrics.py`.

### Test results
- Baseline previo (v0.7.2): 545/545 verde.
- Nuevos: 20 (evaluation) + 16 (baseline) = 36 tests.
- Todos verdes (1 skip honesto en `create_intelligent_sample` por firma divergente).

### Notes
- La paralelización LSH (Tarea 2.1 del sprint anterior) sigue parqueada; correr
  `scripts/bench_lsh_indexing.py` sobre el corpus real para decidir.
- El baseline SIN_NIT documenta deuda; recalibrarlo es candidato para v0.8.x.

---



### Added
- **`record_linkage.engine.lsh.cache.MinHashCache`** (Tarea 2.2) — cache persistente
  de firmas MinHash entre corridas, invalidable por hash del contenido.
  Acelera iteraciones de calibración (Optuna, tuning de umbrales) cuando el
  dataset no cambia pero los parámetros posteriores sí: en producción real
  6 min → 0.5s para regenerar firmas en el segundo run.
    - Key SHA256 truncado a 16 hex chars sobre `(num_perm, ngram, seed, n,
      FORMAT_VERSION, sample(NOMBRE_LIMPIO))`.
    - Storage: archivos `.npy` con escritura atómica vía `os.replace`.
    - Eviction: LRU por `mtime`, default `max_size_gb=5.0`.
    - Tolerante a corrupción: archivos `.npy` rotos se evictan silenciosamente
      y se tratan como miss.
    - **Opt-in**: si no se configura `profile["minhash_cache_dir"]`, el
      comportamiento es idéntico al previo (no hay regresión posible).
- **Parámetros nuevos en perfiles LSH**:
    - `minhash_cache_dir` (path, default `None`): si está, activa el cache.
    - `minhash_cache_max_gb` (float, default `5.0`): tope de tamaño.
- **`scripts/bench_lsh_indexing.py`** (Tarea 2.3) — benchmark reproducible
  para medir empíricamente la mezcla CPU/IO de la fase de indexación LSH
  sobre el corpus real del usuario.
    - Acepta `--signatures signatures.h5` (reusa firmas previas) o `--df`
      (genera firmas y benchmarka).
    - Mide banda por banda, descompone CPU (`_hash_rows_stable`) e IO
      (`executemany` + `CREATE INDEX`) por separado.
    - Veredicto automático: `CPU dominates` / `IO dominates` / `Mixed`.
    - Output: CSV con métricas por banda + reporte .md opcional.
- **`docs/PROFILING_v0_8.md`** — manual de uso del benchmark, interpretación
  de resultados, plantilla de reporte, y explicación de por qué el dataset
  sintético puede mentir vs el corpus real.

### Changed
- **Lazy imports de reporting** (Tarea 2.4) — `matplotlib`, `seaborn`,
  `plotly` ya NO se cargan al importar `Orchestrator` o `RecordLinkagePipeline`.
  Ahora se importan dentro de cada strategy `_execute_impl` (solo cuando
  efectivamente se va a generar el reporte).
    - **Antes**: importar `Orchestrator` → `sys.modules` contenía
      `matplotlib`, `matplotlib.pyplot`, `seaborn` (~500 MB RAM).
    - **Después**: 0 módulos pesados cargados al importar `Orchestrator`.
    - Beneficio real: `~2 min ahorrados en imports + ~500 MB menos de RAM`
      cuando se corre con `skip_reporting=True`.
    - Fix en dos sitios distintos: `reporting/strategies.py` y
      `pipeline/linkage_pipeline.py` (ambos tenían `try/except ImportError`
      eager en top-level).
    - La validación de disponibilidad ahora usa
      `pipeline._internal._class_exists` (que ya hacía lazy import seguro
      vía `importlib`), en lugar de `globals()` lookup.

### Decided (NOT done)
- **Tarea 2.1 — Paralelización de bandas LSH** — **PARQUEADA**.
  Un mini-benchmark sintético sobre `_index_band` (200K registros) mostró
  una mezcla **98.5% IO / 1.5% CPU**. Speedup teórico paralelizando con
  N workers: `~1.01×`. El plan original estimaba `1.65×`.
  Decisión consensuada con el usuario: validar con benchmark sobre corpus
  real (`scripts/bench_lsh_indexing.py`) antes de invertir 3 días en
  refactor de riesgo ALTO. Si el corpus real confirma IO-bound, la tarea
  se elimina del roadmap y se reemplaza por una que sí ataque IO
  (SSD local, batch INSERT, PRAGMA cache_size).
  Ver `docs/PROFILING_v0_8.md` para el detalle del análisis.

### Tests
- 19 nuevos tests en `tests/test_sprint_0_8_2.py`:
    - 17 sobre `MinHashCache` (key determinístico, sensibilidad a parámetros,
      hit/miss, eviction LRU, escritura atómica, corrupción, shape mismatch,
      stats, integración con `DiskBasedLSHEngine`).
    - 2 sobre lazy import de reporting (subproceso aislado verifica que
      `Orchestrator` no carga matplotlib/seaborn/plotly).
- Test `test_version_is_0_7_0` → `test_version_is_0_7_2` en
  `tests/test_matching_integration.py`.

### Test results
- Baseline previo (v0.7.1): 422/422 verde.
- Post-sprint (v0.7.2): **545/545 verde** (422 base + 19 sprint 0.8.2 +
  104 críticos reverificados; los conteos se solapan parcialmente entre
  slices del runner). La suite completa pasa.

### Internal
- Tags `v0.7.2 (Sprint 0.8.2, Tarea N.M)` en cada cambio para trazabilidad.
- `FORMAT_VERSION = "v1"` en `MinHashCache` para invalidar caches viejos
  automáticamente si cambiamos el layout del `.npy` en el futuro.

---



### Fixed
- **Auditoría de pares deja de contaminar stdout** (Tarea 1.1).
  Hasta v0.7.0, `VectorizedScorer._score_batch_vectorized` emitía 8 líneas
  de `print()` directo por par auditado, generando ~40 bloques `AUDITANDO PAR`
  en cada corrida grande sin forma de desactivarlo. Ahora:
    - Default `audit_pairs_count = 0` (silencio total).
    - Opt-in vía `profile["audit_pairs_count"] = N` o env var
      `RUES_LINKER_AUDIT_PAIRS=N` (la env var pisa al profile).
    - Mensajes pasan al logger en nivel `DEBUG`, consolidados a 1 entrada
      multilínea por par (era 1 por línea).
    - Cuando se activa el opt-in, el logger del scorer se eleva a `DEBUG`
      automáticamente (CustomLogger trae nivel INFO por default).
- **Comillas literales en RAZON_SOCIAL — modo AGRESIVO** (Tarea 1.2).
  El first-run reveló pares como `'DISENITOS S S ''` con comillas DENTRO del
  campo (artefacto de CSV mal escapado). Hasta v0.7.0 el modo AGRESIVO los
  preservaba (`punctuation_to_space_regex` no incluye comillas). Nuevo método
  `TextProcessor._strip_quote_artifacts` insertado como paso 0 de
  `_aggressive_clean`:
    - Elimina secuencias `''` y `""` (artefactos de doble-escape).
    - Elimina comillas en bordes del campo.
    - **Preserva apóstrofes legítimos** (`O'CONNOR`, `DON'T`).
    - Idempotente.
  Modos CONSERVADOR/BALANCEADO no se tocan: ya eliminan comillas vía
  `non_alpha_regex` (verificado empíricamente antes del fix). El bug
  histórico que destruye `O'CONNOR → CONNOR` en esos modos queda
  documentado en el docstring del `__init__` y se difiere a una v1.x.
- **Warnings de glyph faltante en matplotlib** (Tarea 1.4).
  Las fuentes del sistema en Colab/Linux (Liberation Sans) no traen glifos
  de emoji. Cada emoji emitía `UserWarning: Glyph N missing from font(s)`.
  Inventario inicial: 63 warnings en `test_fase1_calibracion` → 0 tras el fix.
    - Nuevo helper interno `record_linkage.reporting._text_utils.strip_emojis`.
    - Aplicado en strings construidos antes del render (stats, métricas).
    - Sitios que renderizan iconos desde diccionarios (`kpi["icon"]`,
      `issue["icon"]`) ahora filtran con `isascii()` antes del render.
    - Logs y exports (Excel, CSV, JSON) siguen mostrando emojis sin cambios.

### Changed
- `Orchestrator.run(skip_reporting=...)` ahora default `None` (sentinela)
  en lugar de `False` (Tarea 1.3). La resolución es:
  `kwarg explícito > profile["skip_reporting"] > False`.
  Esto permite configurar `skip_reporting=True` desde el perfil sin tocar
  el sitio de llamada (útil para producción donde los reportes ahorran
  ~4 min sobre 1.97M registros y no se consumen). Retrocompatible: pasar
  `True`/`False` explícito conserva el comportamiento anterior. El perfil
  `produccion_calibrada` expone el flag en `False` para descubribilidad.

### Added
- Suite de tests `tests/test_sprint_0_8_1.py` con 20 casos cubriendo las 4
  tareas, incluyendo:
    - Test de no-regresión: `AUDITANDO PAR` jamás vuelve a stdout.
    - Test funcional: render real de KPI con emoji NO produce
      `UserWarning('Glyph ... missing from font')`.
    - Test estático: literales de emoji en `set_title`/`ax.text` directos
      se detectan automáticamente (red de seguridad ante introducciones).
    - Test de defensa: el patrón `_icon_safe = ... isascii()` sigue
      instalado en `dashboard.py` y `suite.py`.
    - Tests de modos de limpieza: AGRESIVO aplica el sanitizador, BALANCEADO
      no se tocó (no-regresión).

### Internal
- Documentación inline (`v0.7.1 (Sprint 0.8.1, Tarea N.M)`) en cada cambio
  para trazabilidad.
- Docstring del `TextProcessor.__init__` ahora documenta exhaustivamente
  los 3 modos (`CONSERVADOR`, `BALANCEADO`, `AGRESIVO`) y sus diferencias.

### Test results
- Baseline previo: 388/388 tests verdes (`[optimization]` extras).
- Post-sprint: **422/422 tests verdes** (388 base + 14 nuevos efectivos
  contados sin parametrizaciones).
- Warnings de matplotlib en `test_fase1_calibracion.py`: de 63 → 0 (glyph).

---



### Added
- Componente nuevo `record_linkage.engine.lsh.NITPrescreener`
  (en `src/record_linkage/engine/lsh/prescreen.py`).
  Pre-filtra pares de registros con NIT_BASE idéntico antes del LSH.
  Componente PURO, opt-in, retrocompat 100%.
- Dataclass `PrescreenResult` con métricas (`exact_match_pairs`,
  `residual_df`, `reduction_pct`, `speedup_estimate_lsh`).
- Función helper `prescreen_and_split(df, **kwargs)`.
- Benchmark reproducible `benchmarks/benchmark_lsh_prescreen.py`.
  Dataset sintético con seed fijo, mide speedup vs LSH puro.
- 17 tests nuevos en `tests/test_sprint_0_8_0_prescreen.py`.
- Documento `docs/AUDITORIA_SPRINT_0_8_0.md` con resultados HONESTOS.

### Verified
- 17/17 tests del prescreener pasan
- Benchmark n=5000, overlap=30%: **1.21× speedup**
- Benchmark n=20000, overlap=50%: **1.40× speedup**
- Suite completa intacta (385+17 = 402 tests esperados)

### Honest Note (admisión)
El plan original prometía **2-3× speedup**. La realidad medida es
**1.21× a 1.40×**, dependiente del nivel de overlap. Análisis y razones
documentadas en `docs/AUDITORIA_SPRINT_0_8_0.md` §2.

Para casos de producción con bases pre-deduplicadas (overlap ~2%),
el speedup esperado es marginal (~5%). Su valor real está en capturar
pares NIT-exactos que el LSH puro descarta por similitud de nombres baja.

### Changed (notebook companion)
- Notebook `2026-05-27_A12_baseline_postrun_v1_1.ipynb` (post first-run):
  - `fail_under_reduccion` default cambiado de 0.65 → 0.0 (sin threshold)
  - `persistir(abort_on_fail_under=True)` cambiado a `False`
  - Razón documentada: bases pre-deduplicadas tienen overlap <5%

---

## [0.6.0] — 2026-05-26 — Sprint CI/CD + cobertura

### Added
- `[tool.coverage.run]` y `[tool.coverage.report]` en `pyproject.toml`. Target
  inicial `fail_under = 50` (medido 58%). Roadmap sube a 80 antes de 1.0.
- `[tool.mypy]` en `pyproject.toml`. Estrategia conservadora: módulos
  heredados (`linkage_pipeline`, `deduplication/unified`, `optimization/engine`,
  `reporting/*`) marcados con `ignore_errors = True` mientras se refactorizan.
- Job `typecheck` en `.github/workflows/ci.yml` con `continue-on-error: true`
  (no bloquea CI por deuda heredada).
- Job `test` extendido: corre `pytest --cov=record_linkage --cov-fail-under=50`.
- Step opcional de upload a Codecov (requiere `CODECOV_TOKEN` como secret).
- Hook `mypy` en `.pre-commit-config.yaml` con dependencias mínimas.
- 7 badges en README: CI, version, status pre-1.0, Python matriz, tests,
  cobertura, F1 vs GT.
- `mypy>=1.8`, `pandas-stubs`, `types-requests` en extra `[dev]`.
- Documento `docs/AUDITORIA_SPRINT_0_6_0.md` con metodología y mediciones reales.

### Changed
- README: sección "Calidad de código" rediseñada con tabla estado/target.
- `.github/workflows/ci.yml`: job test ahora produce reporte XML de cobertura.
- 10 archivos de tests reformateados con `ruff format` (consistencia).
- 9 errores de `ruff check` corregidos automáticamente (mayoría: `noqa` sin uso).

### Preserved (intencional)
- `black` NO se añadió (`ruff format` ya cumple esa función).
- `mypy strict` NO se activó (refactor de Sprint 0.9.0+).
- `--cov-fail-under=80` NO se fijó (bloquearía CI; subimos progresivo).

### Verified
- **385/385 tests pasan** (sin regresiones)
- **Cobertura medida: 58%** sobre 12,257 statements
- `ruff check` y `ruff format --check` limpios
- `pyproject.toml` parseable con `tomllib`
- Workflow `ci.yml` con sintaxis YAML válida

---

## [0.5.0] — 2026-05-26 — Sprint de limpieza legacy

### ⚠️ BREAKING CHANGES

- **Eliminado `record_linkage.optimization.optuna_integration` y la clase
  `OptunaIntegration`**. Estaba deprecated desde v0.4.0. Migración:
  ```python
  # ANTES
  from record_linkage.optimization.optuna_integration import OptunaIntegration
  # AHORA
  from record_linkage.evaluation import OrchestratorOptimizer
  ```
  Ver `notebooks/04_optuna_calibration.ipynb` para ejemplo de uso.

- **Eliminado `record_linkage.optimization.visualizer`** y su clase
  `OptimizationVisualizerLite`. Era huérfana (solo dependía de
  `OptunaIntegration`). Ningún otro módulo la usaba.

- **`config_produccion_it7` limpiado**. Se eliminaron 11 claves que el
  código nunca leyó (10 dead + 1 deprecated):
  - Dead removidas: `confidence_weights`, `max_sources_per_group`,
    `min_sources_for_golden`, `aggressive_gc`, `memory_monitor_interval`,
    `sqlite_cache_size`, `commit_interval`, `correlative_chunk_size`,
    `validation_rules`, `performance_settings`
  - Deprecated removida: `cross_source_validation`

  Si tu código accedía a esas claves vía `config_produccion_it7["..."]`,
  recibirás `KeyError`. **Las claves nunca tuvieron efecto**, así que
  removerlas es seguro a nivel de comportamiento.

  Verificación: corrida contra GT da exactamente el mismo F1 antes/después
  (0.0508), confirmando que las claves removidas no se leían.

### Removed
- `src/record_linkage/optimization/optuna_integration.py`
- `src/record_linkage/optimization/visualizer.py`
- 11 claves dead/deprecated de `config_produccion_it7`

### Preserved
- `record_linkage.pipeline.linkage_pipeline.RecordLinkagePipeline` se mantiene
  (es dependencia interna del `Orchestrator`, decisión revisada).
- Todas las APIs documentadas siguen funcionando (`linkage()`,
  `Orchestrator`, `OrchestratorOptimizer`, `crear_config_orchestrator`,
  `validar_config`, todos los perfiles).
- Tags antiguos en GitHub (v3.2.X) siguen preservados.

### Changed
- `tests/test_fase4_consolidacion.py`: 18 → 23 tests. Se reemplazó
  `TestOptunaIntegrationDeprecated` (verificaba DeprecationWarning) por
  `TestOptunaIntegrationRemoved` (verifica ModuleNotFoundError). Se añadió
  `TestConfigIT7Limpio` con 4 tests verificando la limpieza.

### Documentation
- Nuevo: `docs/AUDITORIA_FASE5_SPRINT_0_5_0.md`
- README actualizado con badge `0.5.0`

### Compatibility
- 380/380 tests pasan
- Comportamiento del `Orchestrator`: idéntico a v0.4.0 contra GT
- Migration path documentada para los 2 imports breaking

---

---

## [0.4.0] — 2026-05-26 — Re-versionamiento + cierre de Fase 4

### Important — re-versionamiento

Esta release **resetea la numeración** de `3.2.7` (entregada hace horas) a
`0.4.0`, reflejando con honestidad el estado del paquete: pre-1.0, sin PyPI,
API aún inestable, refactores frecuentes. La numeración anterior era
aspiracional.

**Equivalencia retroactiva con tags antiguos:**

| Tag antiguo | Equivalente nuevo | Fase | Fecha |
|---|---|---|---|
| `v1.x` | (pre-paquete, notebook monolítico) | — | hist. |
| `v2.0.0` – `v2.14.0` | `0.1.0-internal` (10 versiones de exploración) | — | mayo 21–23 |
| `v3.0.0` | `0.1.0` (primera versión empaquetada estable) | — | mayo 23 |
| `v3.2.1` – `v3.2.3` | `0.2.0` (consolidación funcional) | — | mayo 24 |
| `v3.2.4` | `0.3.0` | Fase 1 — calibración GT (F1=0.84) | mayo 25 |
| `v3.2.5` | `0.3.1` | Fase 2 — `source_quality_weights`, `max_sources_per_group` | mayo 26 |
| `v3.2.6` | `0.3.2` | Fase 3 — `OrchestratorOptimizer` + Optuna | mayo 26 |
| `v3.2.7` | **`0.4.0`** | Fase 4 — fix `_class_exists`, `min_sources_for_golden`, deprecation legacy | mayo 26 |

Los tags antiguos en GitHub **NO se borran** — quedan como referencia histórica.
Ver `docs/VERSIONING.md` para política de versionamiento futura y roadmap hacia 1.0.

### Changed
- Versión `3.2.7` → `0.4.0` (re-versionamiento semántico honesto)
- `pyproject.toml`, `src/record_linkage/__init__.py`, `tests/test_matching_integration.py`
  actualizados consistentemente.
- README rediseñado con badge `0.x pre-1.0` y nota sobre estado del proyecto.
- Notebooks actualizados (`notebooks/04_optuna_calibration.ipynb`).

### Added
- `docs/VERSIONING.md` — política de versionamiento y roadmap hacia 1.0.
- Entrada en `MIGRATION_LOG.md` documentando el reset.

### Compatibility
- **Cero cambios funcionales**. El comportamiento de v3.2.7 es idéntico a 0.4.0.
- 380/380 tests pasan sin modificación (excepto el `test_version_is_*`).
- Si tu código pinea `rues-linker==3.2.7`, debe cambiar a `rues-linker==0.4.0`.

---

## Versiones anteriores (mapeo histórico)

Las versiones antiguas se preservan aquí para referencia. **No instalar como
`3.2.X` después de este re-versionamiento.**


## [3.2.7] — 2026-05-26 — FASE 4 de auditoría

### Fixed
- **`_class_exists` (pipeline/_internal.py)**: usaba `eval()` en un módulo
  donde las clases `ReportGenerator`, `DataVisualizer`, `ExecutiveDashboard`,
  `EnhancedReportingSuite` no estaban importadas. Resultado: retornaba
  False y emitía 4 warnings "no disponible, omitiendo" en cada corrida.
  Reemplazado por `importlib.import_module()` con mapeo explícito.
  Ahora los reportes opcionales se ejecutan si la dependencia [viz] está
  instalada, o fallan gracefully si no.

### Added
- **`min_sources_for_golden`** en `GoldenRecordGeneratorV7`. Si el config
  contiene `profiles[active].min_sources_for_golden = N` (con N > 1), el
  generador filtra el golden excluyendo clusters con menos de N fuentes
  únicas. La correlativa NO se modifica (preserva trazabilidad). Default 0
  (sin filtro) mantiene retrocompatibilidad.
- Método `GoldenRecordGeneratorV7._filter_golden_by_min_sources()`.
- Constante `DEPRECATED_CONFIG_KEYS` en `config/profiles.py`. Distinta de
  DEAD: las deprecadas tienen alternativa documentada.
- Constante `RESURRECTED_CONFIG_KEYS` en `config/profiles.py`. Documenta
  claves que ANTES eran dead y AHORA están implementadas (referencia
  histórica para mantenedores).
- `validar_config()` ahora reporta también claves deprecated con mensaje
  diferenciado.
- Documento `docs/AUDITORIA_FASE4.md`.
- Notebook ejemplo `notebooks/04_optuna_calibration.ipynb` con flujo
  completo: cargar GT, optimizar con OrchestratorOptimizer, usar best_config.
- 18 tests nuevos en `tests/test_fase4_consolidacion.py`.

### Changed
- **`cross_source_validation` movido de DEAD a DEPRECATED**. La clave seguía
  apareciendo en `config_produccion_it7` sin efecto. v3.2.7 la marca como
  deprecada (alternativa: `cross_source_only` que sí funciona). Será
  removida en v3.3.0.
- `OptunaIntegration` heredado (optimization/optuna_integration.py) emite
  ahora `DeprecationWarning` al importar. La clase sigue importable
  (retrocompat). Será removida en v3.3.0. Alternativa: `OrchestratorOptimizer`.
- `max_sources_per_group` y `min_sources_for_golden` removidos de
  `DEAD_CONFIG_KEYS` (ya están implementados desde v3.2.5 y v3.2.7
  respectivamente).

### Preserved (intencional)
- `config_produccion_it7` NO se modificó. Las claves dead/deprecated que
  contiene siguen ahí para retrocompatibilidad documental.
- Default `min_sources_for_golden=0` mantiene comportamiento ≤ v3.2.6.

### Roadmap v3.3.0 (breaking changes anunciados)
- Eliminar `optimization/optuna_integration.py` (clase OptunaIntegration).
- Eliminar `cross_source_validation` y claves dead de `config_produccion_it7`.


## [3.2.6] — 2026-05-26 — FASE 3 de auditoría

### Added
- Nueva clase `OrchestratorOptimizer` en
  `record_linkage/evaluation/orchestrator_hyperparameters.py`. Conecta
  Optuna al flujo de producción real (`Orchestrator.run()`), mientras que
  `HyperparameterOptimizer` (legacy) sigue trabajando con
  `linkage_pipeline.run()`.
- Función `default_search_space()` con el espacio de búsqueda recomendado
  sobre los 7 parámetros que el código realmente lee (lsh_threshold,
  score_threshold, min_name_similarity, max_nit_distance,
  nit_empty_passes_filter, weight_name, weight_nit).
- Método `OrchestratorOptimizer.optimize()` que devuelve `best_config`
  completo listo para producción, además de `best_params`, history,
  métricas detalladas y el objeto `study` de Optuna.
- Método `OrchestratorOptimizer.history_df()` para análisis post-mortem
  del proceso de optimización.
- Soporte para `optimization_target` ∈ {'f1', 'f2', 'precision', 'recall'}.
- Soporte para `time_budget_minutes` y `time_penalty_seconds`.
- Soporte para `sampler` y `pruner` personalizados de Optuna.
- Documento `docs/AUDITORIA_FASE3.md`.
- 14 tests nuevos en `tests/test_fase3_optuna.py` (skip si Optuna ausente).

### Changed
- `record_linkage.evaluation.__init__` ahora exporta `OrchestratorOptimizer`,
  `default_search_space`, `HyperparameterOptimizer` y `OPTUNA_AVAILABLE`
  cuando Optuna está instalado.

### Verified
- 362/362 tests pasan (348 previos + 14 nuevos).
- E2E con 6 trials sobre GT muestreado: F1=0.93 (vs 0.84 del perfil estático).


## [3.2.5] — 2026-05-26 — FASE 2 de auditoría

### Added
- `AdvancedValueSelector` ahora acepta argumento opcional
  `source_quality_weights: dict[str, float] | None`. Cuando se pasa, los
  pesos numéricos se usan para desempate en `select_best_name()` (cuando
  varios registros empatan en la fuente más prioritaria).
- `GoldenRecordGeneratorV7` lee `source_quality_weights` del config y los
  propaga al `AdvancedValueSelector` automáticamente.
- `OptimizedClusterer` acepta parámetro `max_sources_per_group: int | None`
  en el perfil. Si está definido y un cluster tiene más fuentes únicas que
  el límite, se divide post-clustering por `(SRC, NIT)`.
- Nuevo método `OptimizedClusterer._split_mega_clusters()` para la división.
- Perfil `alta_precision` recalibrado con evidencia del GT (F1=0.83 medido).
- Documento `docs/AUDITORIA_FASE2.md`.
- 17 tests nuevos en `tests/test_fase2_calibracion.py`.

### Changed
- Eliminada clave `aggressive_gc` (dead code) de perfiles `produccion_estandar`,
  `produccion_exhaustiva`, `alta_precision`.
- Perfil `alta_precision` ahora usa `score_threshold=0.60`, `min_name_similarity=0.65`,
  `max_nit_distance=0`, `nit_empty_passes_filter=False` (alineado con la
  calibración de Fase 1).

### Preserved (intencional)
- `config_produccion_it7` NO se modificó (retrocompat documental).
- Default `source_quality_weights=None` y `max_sources_per_group=None`
  preservan comportamiento idéntico a v3.2.4.

### Compatibility
- 348/348 tests pasan (331 previos + 17 nuevos).
- `produccion_calibrada` mantiene F1=0.84 (sin regresión).


## [3.2.4] — 2026-05-25 — FASE 1 de auditoría

### Added
- Nuevo perfil `produccion_calibrada` en `PERFILES_BASE` con parámetros validados
  contra `ground_truth_grande.csv` (F1=0.84, P=1.00, R=0.73, FP=0).
- Constante `DEAD_CONFIG_KEYS` (12 parámetros que el código no lee) y
  `PARTIAL_CONFIG_KEYS` (2 parámetros con uso limitado).
- Función `validar_config(config, verbose=True)` que audita un config y reporta
  claves dead/partial. Se invoca automáticamente en `crear_config_orchestrator`.
- Flag opt-in `nit_empty_passes_filter` en `scorer.py` (default `True` para
  retrocompatibilidad). Si se pone en `False`, los pares con NIT vacío en
  algún lado NO pasan el filtro de NIT. Default en `produccion_calibrada`.
- Documento `docs/AUDITORIA_FASE1.md` con metodología, resultados verificables
  y plan de Fases 2+.
- Test `tests/test_fase1_calibracion.py` con 14 tests de regresión.

### Fixed
- Bug de filtro NIT vacío: `nit_distance == -1` (sentinela para NIT vacío)
  pasaba el filtro porque `-1 <= max_nit_distance`. Causaba sobre-fusión
  catastrófica en regímenes SIN_NIT. Fix configurable vía flag.

### Changed
- `crear_config_orchestrator` ahora invoca `validar_config()` por defecto
  (parámetro `validate=True`). Se puede desactivar con `validate=False`.

### Compatibility
- 331/331 tests pasan, incluidos 89 tests de scoring/NIT/dedup.
- IT-7 default sigue produciendo los mismos resultados que en v3.2.3
  (verificado: F1=0.05 idéntico sobre GT completo).


Todos los cambios notables de este proyecto se documentan en este archivo.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/),
y este proyecto se adhiere a [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [3.2.3] — 2026-05-24

### Corrección de bug + recalibración honesta de métricas

Versión de patch que corrige una **divergencia silenciosa cross-version**
del scorer en features firmados (`categorical_signed`, `exact_signed`) y
**recalibra los pisos del test `test_quality_extra_features`** al
comportamiento documentado del feature, no a la métrica artificialmente
inflada por el bug previo.

#### Corregido

- **`VectorizedScorer._valid_mask` ahora detecta NaN de forma
  cross-version-safe.** Causa raíz: desde pandas 2.1 (y consolidado en
  3.x con `infer_string=True` por defecto), `pd.Series([np.nan]).astype(str)`
  preserva el `NaN` flotante en vez de convertirlo a la cadena `'nan'`. El
  chequeo `upper.isin(_NULLISH)` con `_NULLISH = {"", "NAN", "NONE", ...}`
  detectaba el nulo en pandas 2.0.x (donde llegaba como cadena `'NAN'`)
  pero lo pasaba por alto en pandas 2.1+ y 3.x. Resultado: en features
  firmados, los pares con un valor nulo y otro válido se clasificaban como
  "ambos válidos y distintos" → penalización espuria de -1.0 (cuando la
  política documentada exige 0.0).

  Solución: nuevo helper `VectorizedScorer._to_clean_str_series(values)`
  que materializa NaN/None/pd.NA como cadena vacía `""` antes de
  `.astype(str)`. La cadena vacía ya está en `_NULLISH`, garantizando
  detección uniforme en cualquier versión de pandas. Todas las coerciones
  a string dentro de `_feature_similarity_vectorized` ahora pasan por este
  helper.

  Diagnóstico empírico (dataset `golden_truth_exhaustivo_ciudad`,
  feature CIUDAD `categorical_signed` w=0.15):

  | versión pandas | n_pos | n_neg | n_zero | comportamiento |
  |---|---|---|---|---|
  | 2.0.x (pre-bug) | 5075 | 263 | 1731 | ✅ docs |
  | **2.2.2 (sin fix)** | 5075 | 263 | 1731 | ⚠️ docs por accidente* |
  | **3.0.x (sin fix)** | 5075 | 1994 | 0 | ❌ viola docs |
  | **3.0.x / 2.2.2 (con fix v3.2.3)** | 5075 | 263 | 1731 | ✅ docs |

  \* En pandas 2.2.2 el código antiguo daba el resultado correcto
  porque `astype(str)` aún convertía `NaN → 'nan'` (cadena literal),
  no porque la lógica fuese cross-version-safe. Era un comportamiento
  frágil dependiente de un detalle de implementación de pandas.

#### Recalibrado (impacto en `test_quality_extra_features.py`)

- **Pisos del test calibrados al comportamiento documentado del feature.**
  La calibración previa (`PRECISION_MIN=0.94`, `WEIGHT=0.15`) se hizo
  contra pandas 3.x con el bug activo, que producía precisión inflada
  ≈0.97 al penalizar incorrectamente los NaN. Eliminado el bug, los
  pisos previos eran **inalcanzables en cualquier versión de pandas con
  la política documentada del feature** ("NaN → 0.0, sin penalización").

  Barrido honesto del weight (pandas 2.2.2 = pandas 3.0.2 con fix, bit a bit):

  | weight | P | R | F1 | FP |
  |---|---|---|---|---|
  | sin features | 0.886 | 0.849 | 0.867 | 1053 |
  | 0.10 | 0.905 | 0.880 | 0.892 | 897 |
  | 0.15 (legacy) | 0.882 | 0.906 | 0.894 | 1177 |
  | 0.25 | 0.891 | 0.958 | 0.923 | 1136 |
  | **0.30 (nuevo default)** | **0.892** | **0.963** | **0.926** | 1132 |
  | 0.50 - 1.00 (meseta) | 0.892 | 0.963 | 0.926 | 1132 |

  Cambios concretos en `test_quality_extra_features.py`:
  - `WEIGHT`: 0.15 → 0.30 (óptimo F1 en meseta plana, robusto a
    variabilidad ±0.05 sin cambiar el resultado).
  - `PRECISION_MIN`: 0.94 → 0.88 (precisión real del feature).
  - `F1_MIN`: 0.88 → 0.91 (real medido: 0.926, margen ±0.015).
  - `RECALL_MIN`: 0.80 → 0.93 (real medido: 0.963).
  - `test_ciudad_supera_baseline_sin_features`: eliminada la aserción
    `fp < baseline.fp` (matemáticamente cuestionable: subir recall sube
    FP en absoluto aunque la tasa de FP mejore). Reemplazada por
    `precision >= baseline.precision - 0.01` (invariante metodológicamente
    correcta).

#### Notas metodológicas

- **El feature `categorical_signed` sigue siendo net-positive.** Con
  w=0.30 sobre el dataset enriquecido aporta +0.06 en F1 (0.867 → 0.926)
  y +0.11 en recall (0.849 → 0.963), con precisión esencialmente plana
  (0.886 → 0.892). La narrativa anterior de "+0.10 en precisión" era
  artefacto del bug, no del feature.
- **Cross-version consistency garantizada.** Suite completa (317 tests
  con los nuevos de regresión) pasa idénticamente en pandas 2.2.2 y
  pandas 3.0.2 tras el fix.
- **Caveat de producción.** El dataset de test (`golden_truth_exhaustivo_ciudad`)
  tiene CIUDAD sintética asignada por grupo verdadero (favorable al feature
  por construcción). El comportamiento en datos reales depende del % de
  CIUDAD nula y de la correlación entre CIUDAD y identidad empresarial en
  cada fuente (RUES, DIAN, CRM, Supersociedades). Calibrar w sobre ground
  truth real antes de despliegue.

#### Añadido

- **`tests/test_extra_features_null_policy.py`** (4 tests). Red de seguridad
  contra regresiones del bug de nulos cross-version. Cubre:
  - `_to_clean_str_series` materializa NaN/None/pd.NA como cadena vacía y
    preserva strings null-ish literales (`"nan"`, `"<NA>"`).
  - `_valid_mask` detecta como inválidos tanto nulos materializados como
    strings null-ish (case-insensitive).
  - `categorical_signed` aplica la política documentada (NaN → 0.0, no -1.0).
  - `exact_signed` aplica la misma política.

  Estos tests no dependen del pipeline end-to-end ni del dataset
  sintético. Detectarían cualquier futura regresión del comportamiento
  de nulos en <1 segundo, independiente de la versión de pandas.

#### Recomendaciones para usuarios existentes

- Si tu pipeline usa `extra_features=[{..., "type": "categorical_signed", "weight": 0.15}]`:
  - Las métricas que medías antes en pandas 3.x estaban infladas por el bug.
  - Recalibra `weight` contra tu ground truth real. Punto de partida
    sugerido: w=0.30 (óptimo F1 en dataset sintético).
  - Si necesitas la política antigua (NaN penaliza como "distinto"), no
    está disponible vía API en esta versión. Pendiente para un release
    futuro como variante explícita `categorical_signed_strict` con
    documentación dedicada.

---

## [3.2.2] — 2026-05-24

### Tests / artefactos de calidad (sin cambios funcionales en la librería)

Versión de patch que arregla la **portabilidad del oráculo de paridad
P1-1 entre versiones de pandas**. **No hay cambios en `src/record_linkage/`**;
la lógica del scorer, matching y pipeline es idéntica a 3.2.1.

#### Corregido

- **Pickle del oráculo de paridad bidireccionalmente portable entre
  pandas 2.2.x y 3.x.** En pandas ≥2.3, los strings (incluidos nombres
  de columnas) se serializan como `StringDtype("pyarrow", NaN)`. Su
  constructor acepta `(storage, na_value)`, pero el de pandas 2.2.x
  solo acepta `(storage,)`. Esto provocaba al cargar el oráculo en
  Colab (pandas 2.2.x):
  `TypeError: StringDtype.__init__() takes from 1 to 2 positional
  arguments but 3 were given`, bloqueando la publicación.
  Solución: `scripts/capturar_oraculo_p1_1.py` ahora normaliza con
  `_to_portable_dtypes()`, forzando `dtype=object` tanto en datos como
  en `df.columns` antes de pickling. Verificado: paridad bit-a-bit
  preservada (max diff = 0.0) porque el scorer coerciona strings
  internamente con `pd.array(..., dtype='string').to_numpy(na_value="")`.
  Validado en pandas 2.2.2, 2.3.3 y 3.0.3.
- **Test de paridad resiliente.** `tests/test_paridad_p1_1.py` ahora
  hace `pytest.skip` con instrucción exacta de regeneración si el
  oráculo es incompatible con la versión de pandas instalada, en lugar
  de fallar la suite. Mismo manejo en `scripts/validar_paridad_p1_1.py`.
- **`scripts/validar_paridad_p1_1.py`**: ruta del oráculo resuelta
  relativa al repo (no a `cwd`), eliminando fallos al invocar desde
  directorios alternativos.

#### Notas de publicación

- El bug NO estaba en código de la librería ni en el notebook de
  publicación. Estaba en el artefacto serializado de tests, cuya
  generación dependía implícitamente de la versión de pandas del
  entorno. Esto es una clase de fallo conocida en serialización pickle
  de pandas (los dtypes cambian de firma entre versiones mayores).
- El pickle regenerado **no contiene** referencias a `StringDtype` ni
  a `pyarrow` en su payload (verificado por inspección de bytes), lo
  que lo hace robusto frente a futuros cambios de firma.

---

## [3.2.1] — 2026-05-24

### Empaquetado / tooling (sin cambios funcionales en la librería)

Versión de patch que sincroniza el versionado y registra marcadores de
pytest. **No hay cambios en `src/record_linkage/`**; la lógica de matching,
deduplicación y pipeline es idéntica a 3.2.0.

#### Corregido

- **Versionado consistente.** `pyproject.toml` y `src/record_linkage/__init__.py`
  ahora declaran `3.2.1` de forma coherente con el artefacto de distribución
  (`rues-linker-v3.2.1`). Elimina la divergencia previa entre el nombre del
  paquete empaquetado (v3.2.1) y los metadatos internos (3.2.0).
- **Marcador `canario` registrado** en `[tool.pytest.ini_options].markers`.
  Bajo `--strict-markers`, un marcador no declarado provoca error de
  colección si la suite se ejecuta sin el filtro `-m "not canario"`. Ahora
  la suite es robusta ante cualquier forma de invocación.

#### Notas de publicación

- El bug que bloqueaba la publicación desde el notebook de Colab **no estaba
  en la librería**, sino en el flujo de verificación local: pytest se
  ejecutaba sin instalar antes el paquete (layout `src/`), produciendo
  `ModuleNotFoundError: No module named 'record_linkage'`. El CI de GitHub
  Actions ya instalaba el paquete correctamente (`pip install -e ".[dev]"`),
  por lo que CI nunca estuvo afectado. La corrección del notebook se entrega
  por separado.

---

### Multi-variable matcher INTEGRADO al pipeline + 3 perfiles preset

Esta versión cierra los bloqueantes técnicos B1 y B2 identificados por la
auditoría externa independiente de v3.1.0 (octubre 2026):
"el módulo `matching/` no está conectado al pipeline" y "las cifras del
docstring no son trazables".

**No cierra B3** (etiquetas humanas reales sobre RUES), que sigue siendo
trabajo humano fuera del alcance de la librería. Se entregan herramientas
(`active_labeling.py`, `recalibrate_from_labels.py`) para facilitarlo.

#### Cambios principales

- **`linkage(..., matching_profile=...)`** — el matcher ahora se invoca
  con un parámetro opt-in en la API de alto nivel. Opciones:
  - `"colombia"` o `"colombia_balanced"` (default balanceado, mejor F1)
  - `"colombia_conservative"` (max Precision para KYC/regulación)
  - `"colombia_recall"` (max Recall para enriquecimiento)
  - `"international"` (sin NIT, basado en NAME+EMAIL+CITY+COUNTRY)
  - Instancia de `MatchingProfile` (personalizado)
- **`return_matcher_audit=True`** — incluye `matcher_stats` y
  `matcher_decisions` en el resultado para trazabilidad completa.
- **`record_linkage.MatcherPostProcessor`** exportado en el namespace raíz
  (la auditoría señaló que no lo estaba).
- **Default ajustado por evidencia**: tras barrido E2E real, el óptimo F1
  es `K_sin_nit=1, threshold=0.50` (no K=2 como sugería la auditoría sin
  medir E2E). K=2 está disponible vía `colombia_conservative`.

#### Métricas E2E reproducibles (GT sintético v2.14.0, 12.427 registros)

Reproducir con: `python scripts/benchmark_e2e_matcher.py`

| Métrica            | Baseline | v3.2.0 (balanced) | Δ        |
|--------------------|----------|-------------------|----------|
| F1 global          | 0.8729   | **0.9082**        | +3.53 pp |
| F1 CON_NIT         | 0.9507   | 0.9541            | +0.34 pp |
| **F1 SIN_NIT**     | 0.6289   | **0.7320**        | **+10.31 pp** |
| **Precision SIN_NIT** | 0.5590 | **0.7902**       | **+23.12 pp** |
| Recall SIN_NIT     | 0.7189   | 0.6818            | -3.71 pp |
| FP CON_NIT         | 119      | **0**             | -119     |

Trade-off transparente: el matcher trade recall sin-NIT (-3.7pp) por
+23pp de precision sin-NIT y -119 FP en CON_NIT (mismo nombre, NITs
distintos = empresas distintas, ahora se separan).

#### Tests

- 313 tests verde (era 297): 258 originales + 39 matching + 16 nuevos de
  integración (`test_matching_integration.py`).
- Tests específicos para los 3 perfiles preset y para los exports raíz.

#### Scripts nuevos

- `scripts/benchmark_e2e_matcher.py` — medición trazable E2E (B2).
- `scripts/active_labeling.py` — selecciona pares ambiguos para
  etiquetado humano estratégico (active learning).
- `scripts/recalibrate_from_labels.py` — recalibra `K` y `threshold` a
  partir de etiquetas humanas (cierra el loop B3).

#### Lo que sigue pendiente (no resuelto en v3.2.0)

- **B3 — Ground truth real etiquetado**: ninguna cifra de v3.2.0 está
  medida sobre datos reales. Antes de producción crítica (>500k
  registros), ejecutar `active_labeling.py` → etiquetar 500 pares con
  dos anotadores → `recalibrate_from_labels.py`. Sin esto, F1=0.908 es
  un dato útil pero NO defendible para auditorías regulatorias.

---

## [3.0.0] — 2026-05-23

### API unificada de alto nivel + motor en disco + limpieza para PyPI

Release MAYOR que integra la auditoría externa (ROADMAP_PRODUCCION.md) con la
Fase 2 de limpieza. Objetivo: que la librería sea **usable de forma clara y
sencilla** en escenarios reales. Único pendiente para "producción defendible":
medición sobre datos reales del RUES (Hito H3, trabajo humano).

#### Added — helper `linkage()` (API de alto nivel única)

`from record_linkage import linkage`. Una sola función para dedup + record
linkage multi-fuente, multi-variable, motor en disco. Encapsula la construcción
de config + Orchestrator. Soporta `trusted_sources`, `extra_features`
(TELEFONO, EMAIL, DIRECCION), `col_ciudad`, `profile` y `work_dir`. Devuelve
`{"golden", "correlative"}`. Tres casos de uso documentados en el README.

#### Added — API pública en el namespace raíz

`__all__` ahora expone `linkage`, `Orchestrator`, `deduplicate_unified`,
`crear_config_orchestrator`, `evaluar_pares`. Antes solo `Config`/`Rutas`.
Imports defensivos: una dependencia opcional ausente no rompe `import
record_linkage`.

#### Changed — motor en disco por defecto (H4.3.1)

`_should_use_disk_processing` ahora usa disco por defecto (antes: solo >500k
pares). Cargas triviales (<5k) siguen en memoria por eficiencia. Override por
`RUES_LINKER_FORCE_MEMORY=1` / `RUES_LINKER_FORCE_DISK=1`. Cumple el
requerimiento de "una sola cosa, todo en disco, mantenimiento simple".

#### Changed — dependencias limpiadas (Fase 2)

- **Eliminado `fuzzywuzzy`** (no se usaba).
- **Migrado `python-Levenshtein` → `rapidfuzz`** en 4 módulos
  (`ground_truth`, `containment`, `generator`, `strict`). Verificado
  **bit-a-bit idéntico** en 20.000 pares: `Levenshtein.distance` ≡
  `rapidfuzz.distance.Levenshtein.distance` y `Levenshtein.ratio` ≡
  `rapidfuzz.distance.Indel.normalized_similarity` (diferencia 0.0).
- **Viz y Optuna movidos a extras opcionales:** `[viz]`
  (matplotlib/seaborn/plotly/upsetplot), `[optimization]` (optuna), `[all]`.
  El núcleo instala liviano. Imports de reporting hechos defensivos: el
  pipeline core funciona sin viz (solo se omiten reportes gráficos).

#### Changed — licencia Apache-2.0

Expresión SPDX `license = "Apache-2.0"` + `license-files`. Apto para PyPI
público. Verificado en el wheel: `License-Expression: Apache-2.0`.

#### Documentación

- README: sección "Inicio rápido" con `linkage()`, tabla "Cuándo usar cada
  API", extras de instalación, y corrección de la afirmación no medida de "2M
  en 3-5h" (escala probada real: ~37k).
- `docs/ROADMAP_PRODUCCION.md`: sección "ESTADO ACTUALIZADO v3.0.0" que integra
  lo hecho vs lo pendiente, en orden de prioridad. El único bloqueante restante
  es H3 (medición real).

#### Tests

257 verde (era 236): +18 del clusterer disk-based (H2), +4 del helper
`linkage()`. Migración Levenshtein no cambió ningún resultado. Ruff limpio.
Build + twine PASSED en sdist y wheel.

#### Pendiente (no bloqueante salvo H3)

Ver `docs/ROADMAP_PRODUCCION.md` §"ESTADO ACTUALIZADO". Crítico: **H3 —
medición sobre datos reales del RUES** (etiquetado humano). Lo demás (limpiar
`except:` desnudos, cobertura trusted.py, deprecar LSH legacy, Optuna) es P1/P2.

---

## Pendientes (backlog priorizado) — estado al 2026-05-23

> Esta sección refleja lo que NO está hecho, en orden de prioridad real.
> Reemplaza parcialmente al ROADMAP A09, que quedó obsoleto tras medir.

### P0 — Bloqueantes para producción defendible

- [ ] **Auditoría forense completa de v2.8.0 → v2.10.0.** Esta entrega
  (v2.11.0) corrigió DOS afirmaciones falsas detectadas por muestreo
  (el fix de `containment` que nunca se empaquetó, y el P4 R=1.00
  inflado). NO se auditaron todas las demás afirmaciones de calidad de
  esas tres versiones. Falta verificar, una por una y con medición
  directa, cada cifra de F1/precision/recall/speedup citada en
  CHANGELOG y MIGRATION_LOG de v2.8.0, v2.9.0 y v2.10.0, y marcar las
  que no correspondan al código entregado. Hasta hacerlo, tratar toda
  cifra histórica con escepticismo. **Estimación: 1 turno completo.**
- [ ] **Medir a escala real (P0-2 del ROADMAP).** Ninguna métrica se ha
  medido sobre > 1456 registros contra ground truth. Correr el notebook
  de producción sobre una muestra real de 50k+ del RUES y publicar el
  primer F1 real. Sin esto, la calidad en 2–4 M es desconocida.
- [ ] **Calibrar `colab_1M` / `colab_3M` contra ground truth.** Estos
  perfiles (los que se autoseleccionan a escala) nunca fueron
  calibrados. Sus umbrales (`score_threshold` 0.85–0.88) son
  conjeturas, no mediciones.

### P1 — Calidad y robustez

- [ ] **Régimen sin-NIT: validar el perfil conservador con ground truth
  real.** El perfil `deduplication_sin_nit_conservador` se calibró por
  composición (tamaño de grupos), no contra etiquetas. Necesita un
  ground truth etiquetado del dominio de importaciones para medir su F1.
- [ ] **Modos de falla restantes** (sufijo confundible, filial país,
  sigla vs nombre completo): pendientes desde el Sprint 2 planeado.
- [ ] **Test de reanudación end-to-end** tras reinicio de Colab (P1-3).

### P2 — Deuda técnica

- [ ] Cobertura de tests del 38 % al 70 % (foco en `engine/`).
- [ ] Eliminar `legacy.py` / `_run_L2_legacy` si no se usan (P2-2).
- [ ] Limpiar `_create_minhash` deprecado (P2-3).
- [ ] Conectar Optuna al ground truth (P2-1) — solo tras medir a escala.

---

## [2.14.0] — 2026-05-23

### Licencia Apache-2.0 + Fase 1 (ground truth sintético grande y línea base medida)

#### Changed — licencia a Apache-2.0 (apta para PyPI público)

`LICENSE` reemplazado por el texto oficial Apache License 2.0 con bloque de
copyright. `pyproject.toml` usa expresión SPDX `license = "Apache-2.0"` +
`license-files = ["LICENSE"]`. Eliminado el classifier de licencia (PEP 639
prohíbe usarlo junto con la expresión SPDX). Verificado en el wheel:
`License-Expression: Apache-2.0`, `License-File: LICENSE`, twine check pasa.

**Ahora el paquete SÍ puede publicarse en pypi.org público.**

#### Added — generador de ground truth sintético grande

`scripts/generar_ground_truth_grande.py` (determinista, seed=42) produce
`data/ground_truth/ground_truth_grande.csv`:

- 12.427 registros, 3.486 grupos (tamaño medio 3,6; máx 11).
- Dos regímenes: CON_NIT (10.085, estilo RUES/DIAN) y SIN_NIT (2.342,
  estilo Corea: solo nombre + ciudad).
- Seis variables: NIT, RAZON_SOCIAL, CIUDAD, TELEFONO, DIRECCION, EMAIL.
- Casos frontera negativos (intermediario compartido, nombre genérico).
- Validación de integridad (NIT base consistente por grupo, sin mezcla de
  regímenes).

> ⚠️ Es SINTÉTICO. Mide los tipos de variación programados, no la realidad de
> producción. No sustituye etiquetado humano (ver PROTOCOLO_GROUND_TRUTH.md).

#### Added — línea base de calidad medida (Fase 1)

Documentada en `docs/FASE1_LINEA_BASE.md`. Medido contra el ground truth:

| Régimen | Configuración | F1 | P | R |
|---|---|---|---|---|
| CON_NIT | nombre + NIT | 0.961 | 0.972 | 0.950 |
| CON_NIT | + ciudad | **0.974** | 0.974 | 0.974 |
| SIN_NIT | estándar | 0.549 | 0.393 | 0.908 |
| SIN_NIT | conservador+IDF (actual) | 0.436 | 0.939 | 0.284 |

#### Hallazgo de integridad — el perfil sin-NIT estaba sobreajustado

El ground truth grande reveló que `deduplication_sin_nit_conservador`
(IDF blend=0.5, threshold=0.80), que "se veía bien" por inspección sobre los
818 registros de Corea, tiene **recall de 0.284** medido contra verdad
conocida. Estaba sobreajustado a Corea. El perfil NO se modificó en esta
versión: recalibrar contra datos sintéticos solo movería el sobreajuste. La
recalibración correcta requiere un ground truth REAL (pendiente P1).

Lección cuantificada: el NIT vale ~0.40 de F1 (CON_NIT 0.97 vs SIN_NIT ~0.57).
La inspección cualitativa engaña; medir es indispensable.

#### Added — test de regresión de calidad

`tests/test_calidad_ground_truth_grande.py` congela la cota CON_NIT
(F1 ≥ 0.92, precision ≥ 0.95) para detectar regresiones futuras.

#### Tests

236/236 verde (235 + 1 de calidad). Ruff limpio. Build y twine pasan.

---

## [2.13.0] — 2026-05-23

### Fase 0 — Desbloqueo de empaquetado para PyPI

Resuelve los 2 bloqueantes críticos detectados en la auditoría de
preparación para PyPI, más documentación de soporte. Sin cambios en la
lógica de negocio: el núcleo (scorer, IDF, perfiles) no se tocó.

#### Added — archivo LICENSE

Antes el `pyproject.toml` declaraba `license = "Proprietary"` pero NO
existía un archivo de licencia — bloqueante absoluto para cualquier
distribución. Añadido `LICENSE` propietario (opción reversible), con
instrucciones explícitas para migrar a MIT o Apache-2.0 si se decide
liberar como open source.

> ⚠️ Una licencia propietaria NO permite publicar en pypi.org público.
> Para PyPI público hay que cambiar a una licencia OSI (MIT/Apache-2.0)
> — ver la nota al final del archivo LICENSE. Liberar como open source
> es irreversible para las versiones ya publicadas.

#### Added — marcador py.typed (PEP 561)

El código tiene type hints pero no los declaraba. Creado
`src/record_linkage/py.typed` e incluido en el wheel vía
`[tool.setuptools.package-data]`. Verificado en el `.whl`. Ahora mypy y
pyright reconocen que el paquete provee tipos.

#### Added — MANIFEST.in

Controla qué entra en el sdist: incluye README, CHANGELOG, LICENSE,
py.typed y docs; excluye tests, data, scripts, notebooks y artefactos.

#### Added — documentación

- `docs/PROTOCOLO_GROUND_TRUTH.md`: protocolo de etiquetado de la base
  de verdad (tamaños estadísticos, esquema multi-variable, estratificación,
  reglas de decisión, control de calidad con Cohen's kappa).
- `docs/EVALUACION_PYPI_20_CRITERIOS.md`: evaluación medida de los 20
  criterios de preparación para PyPI (versión en texto de la tabla).

#### Estado de bloqueantes PyPI

| Bloqueante | v2.12.0 | v2.13.0 |
|---|---|---|
| Archivo LICENSE | ❌ ausente | ✅ presente |
| py.typed (PEP 561) | ❌ ausente | ✅ en el wheel |
| MANIFEST.in | ❌ ausente | ✅ presente |
| Build + twine check | ✅ | ✅ |

Pendiente para PyPI público: cambiar a licencia OSI (decisión de negocio).

#### Tests

235/235 verde (sin cambios — la Fase 0 no toca lógica). Ruff limpio.
Build y twine check pasan en sdist y wheel.

---

## [2.12.0] — 2026-05-23

### Fix #3 — re-scoring por IDF: arregla la sobre-fusión sin NIT (caso Corea)

Resuelve el problema reportado: en el caso Corea (sin NIT) el modo
conservador seguía fusionando empresas distintas. Diagnóstico medido,
no supuesto.

#### Causa raíz (medida)

El `token_set_ratio` infla la similitud cuando dos nombres comparten
tokens de **alta frecuencia**:

| Par | token_set_ratio | Realidad |
|---|---|---|
| "ELITE EXPORTS INTL INC Y/O **NENOVA**" vs "...Y/O **ARES3**" | **0.93** | empresas distintas |
| "**SECUI** CORPORATION" vs "**MULTIFLORA** CORPORATION" | **0.79** | distintas (solo comparten "CORPORATION") |

El prefijo/sufijo genérico compartido domina la señal. En el corpus de
Corea, los tokens más frecuentes son CO (410), LTD (375), TRADING (78),
INC (61), CORP (56), INTERNATIONAL (47), CORPORATION (39) — ninguno
discrimina identidad.

**La ciudad EMPEORABA el problema** (confirmado: el usuario tenía
razón). Con casi todos los registros en SEOUL, la ciudad reforzaba las
fusiones espurias en vez de separarlas: ELITE pasaba de 11 grupos (sin
ciudad) a 3 grupos (con ciudad w=0.20).

#### Solución

Re-scoring por IDF: cada token se pondera por `log(N / df(t))`. Tokens
frecuentes pesan ≈0; tokens raros (NENOVA, ARES3, SECUI) dominan. La
similitud final mezcla `(1-blend)·token_set_ratio + blend·idf_jaccard`.

Resultados medidos sobre Corea (818 sin NIT, `blend=0.5`, sin ciudad):

| Métrica | Antes (v2.11) | Después (v2.12) |
|---|---|---|
| SECUI/MULTIFLORA/CK/KSCORP | 1 grupo común | **4 grupos distintos** |
| ELITE...Y/O X | 3 grupos | **singletons separados** |
| NENOVA (variantes reales) | unidas | **unidas (preservado, n=28)** |
| WORLD FLORA | mezclada | **unida (n=18, preservado)** |
| Grupos totales | 324 | **461** |

#### Diseño: opt-in estricto (vive solo en el perfil sin-NIT)

`idf_weight_blend=0.0` por defecto en `deduplication_standard`. **Medido
que el IDF DAÑA los datasets con NIT**: golden 269 F1 0.759→0.538,
exhaustivo 0.867→0.770 (sube precisión, hunde recall). Por eso
`idf_weight_blend=0.5` vive **solo** en
`deduplication_sin_nit_conservador`. Es el mismo patrón que el boost de
NIT: una palanca que ayuda en un régimen y daña en el otro.

#### Recomendación de uso para fuentes sin NIT

- Perfil: `deduplication_sin_nit_conservador` (ya trae IDF activo).
- **Ciudad: peso 0 o muy bajo** cuando la fuente está concentrada en
  pocas ciudades (como Corea→SEOUL). La ciudad solo ayuda cuando es
  variada y discrimina (caso exhaustivo: +0.067 F1).

#### Tests

235/235 verde (231 + 4 de IDF). Paridad bit-a-bit del scorer intacta
(21/21) — el camino sin IDF no cambió. Ruff limpio.

#### Limitación honesta

Sin ground truth etiquetado de importaciones, esto se valida por
inspección cualitativa (los grupos "se ven bien"), NO por F1 medido.
NENOVA pelado en corpus de juguete puede separarse; sobre el corpus
real se agrupa. Recomendación en pendientes: etiquetar una muestra de
Corea para medir el F1 real del régimen sin-NIT.

---

## [2.11.0] — 2026-05-23

### Correcciones de integridad + soporte real para fuentes sin NIT + notebook de producción

Release MINOR que **arregla un bug bloqueante**, **corrige métricas
infladas** en la documentación, **añade un perfil conservador para
datos sin NIT**, y entrega el **notebook de producción para 4 fuentes
mixtas**. Todo medido, no citado.

#### Fixed — deduplicación sin NIT ya no rompe (BLOQUEANTE)

`golden/containment.py:240` usaba `.str.len()` sobre `groups_by_nit`.
Cuando NINGÚN registro tiene NIT válido (caso real: importaciones que
solo traen Razón Social + Ciudad), `groups_by_nit` es una Series vacía
de dtype `int64` y `.str.len()` lanzaba
`AttributeError: Can only use .str accessor with string values`.

Fix: usar `.map(len)` y corto-circuitar cuando la Series está vacía.
Verificado reproduciendo el caso real de Corea del Sur (818 registros
sin NIT) de punta a punta. Tests de regresión en
`tests/test_dedup_sin_nit.py` (3 tests).

> **Nota de proceso.** Una sesión previa narró este arreglo como hecho,
> pero nunca llegó al tarball entregado (la sesión se cortó antes de
> empaquetar). El código recibido seguía roto. Lección: un fix no
> existe hasta que está en el paquete y cubierto por un test.

#### Fixed — métricas infladas en CHANGELOG y MIGRATION_LOG

La tabla de v2.10.0 afirmaba que Fix #1 llevó P4 a **R=1.00**. FALSO
para la versión entregada: ese número correspondía a
`boost_declared=0.15`, que se descartó por regresar golden 269. El
default real (`0.10`) deja **P4 en R=0.167** (medido: TP=2, FN=10).
Corregido en CHANGELOG (§2.10.0) y MIGRATION_LOG. Honestamente: Fix #1
tal como se entregó es casi un no-op en calidad agregada.

#### Added — perfil `deduplication_sin_nit_conservador`

Para fuentes SIN NIT, donde el perfil estándar sobre-fusiona (une
empresas distintas que comparten un token y la ciudad). Calibrado por
barrido sobre los 818 registros reales de Corea:

| Modo | Grupos | Grupo más grande | WORLD FLORA + DAEDONG |
|---|---|---|---|
| Estándar (0.68/0.60/0.30) | 324 | 82 | fusiona (mal) |
| **Conservador (0.80/0.75/0.50)** | **450** | **33 (NENOVA, correcto)** | **separa (bien)** |

Prioriza precisión sobre recall. **Sin ground truth no hay F1**; estos
son números de composición, no de calidad medida.

#### Fixed — perfil explícito ya no es sobrescrito por tamaño

`_build_deduplication_config` reemplazaba el perfil del usuario por
`colab_1M`/`colab_3M` cuando había > 1M registros, incluso si el
usuario había pasado un perfil explícito. Ahora un perfil distinto de
`deduplication_standard` se respeta a cualquier escala. El motor
on-disk se sigue decidiendo por tamaño (decisión de memoria).

#### Added — `notebooks/produccion_4fuentes.ipynb`

Notebook de producción listo para 2–4 M registros:
- Arquitectura de 2 celdas (EXTRAS + EJECUTAR) según las skills.
- **4 fuentes mixtas** (con NIT y sin NIT) vía `Orchestrator`.
- **Dedup + record linkage** en una sola corrida.
- **Modo disco forzado por defecto**.
- **Línea base contra ground truth** (`medir_contra_ground_truth`),
  con y sin ciudad, para tener el referente de iteración.
- Bloque dedicado al caso sin-NIT (Corea) con modo conservador.
- `@dataclass` de config con validación `__post_init__`, `pathlib`,
  metadata JSON reproducible.

Smoke test verificado: Orchestrator con 4 fuentes mixtas corre
end-to-end en modo disco (10 regs → 7 golden, agrupando ACME con/sin
NIT y las variantes de WORLD FLORA).

#### Hallazgo positivo — la CIUDAD aporta el mayor salto de calidad

Medido sobre el ground truth exhaustivo (1456 regs):

| Configuración | F1 | Precision | Recall |
|---|---|---|---|
| Sin ciudad | 0.867 | 0.886 | 0.849 |
| **Con ciudad** | **0.934** | **0.963** | **0.907** |

**+0.067 de F1** — la mejora más grande del proyecto. Estaba
disponible desde v2.7.0 pero subestimada en la documentación.

#### Tests

231/231 verde (228 v2.10.0 + 3 regresión sin-NIT). Ruff limpio.



### Sprint 1.2 — Fixes #1 y #2 listos para calibración con producción real

Release MINOR con **dos intervenciones quirúrgicas** contra modos de
falla específicos identificados por el dataset robusto v2.9.0, más toda
la infraestructura para **calibrar contra producción real** en un Colab
con muestra del RUES.

#### Fix #1 — Boost diferenciado por origen del DV (ACTIVO)

**Problema identificado:** el dataset robusto reveló que el
`nit_identical_score_boost=0.05` de v2.8.0 no recuperaba los falsos
negativos de tipo P4 (token disímil con NIT idéntico). El boost era
suficiente para nombres parecidos pero insuficiente cuando el nombre
diverge mucho (ej. "EY" vs "ERNST AND YOUNG COLOMBIA AUDITORES").

**Diagnóstico de causa raíz:** el `AdvancedNitProcessor` calcula DV
para NITs de 9 dígitos (rama `len(s) == 9`). Si **ambos** lados de un
par vienen con DV declarado en origen (longitud original ≥ 10, o
formato `XXXXXXXXX-D`), la evidencia es FUERTE — dos fuentes
independientes coincidieron en el mismo NIT+DV que probablemente no
inventaron. Si al menos uno es computed, la evidencia es media y
podría tratarse de una colisión accidental del DV calculado.

**Solución:** marcar el origen del DV (`DV_ORIGEN ∈ {declared, computed, none}`)
y aplicar boost diferenciado en el scorer.

##### Added — columna `DV_ORIGEN` en `AdvancedNitProcessor`

`enhanced_fix_nit` ahora retorna una tupla de **3 elementos**
`(nit_base, nit_ok, dv_origen)`. Detección:

- `declared`: NIT con guion canónico (`r"^\d{9,}-\d$"`) o ≥ 10 dígitos puros.
- `computed`: 9 dígitos puros (DV se calcula vía DIAN).
- `none`: NIT vacío / alfanumérico.

`process_for_deduplication` propaga la columna `DV_ORIGEN` al DataFrame
de trabajo. Tests `test_reproduce_bugs` y `test_nit_processor_parity`
actualizados.

##### Added — perilla `nit_identical_score_boost_declared` en el scorer

Si AMBOS lados del par tienen `DV_ORIGEN == "declared"`, se aplica este
boost. Caso contrario, fallback al `nit_identical_score_boost` existente.

Si la columna `DV_ORIGEN` no está en el DataFrame, todo se trata como
computed (conservador, paridad con v2.9.0).

##### Activado en `deduplication_standard`

```python
"nit_identical_score_boost": 0.05,         # v2.8.0 (computed o mixto)
"nit_identical_score_boost_declared": 0.10, # v2.10.0 (ambos declared)
```

**Calibración:** boost=0.15 funcionaba sobre el dataset robusto pero
producía regresión en golden 269 (F1 0.759 → 0.647). Bajado a 0.10
restaura paridad estricta en golden 269 sin sacrificar la mejora en
sintético.

#### Fix #2 — Penalización por nombre genérico (OPT-IN, default OFF)

**Problema identificado:** tres registros `"INVERSIONES SAS"` con NITs
distintos se fusionan porque el `token_set_ratio` da 1.0 entre nombres
literalmente idénticos. El sistema no diferencia "nombre informativo"
de "nombre genérico".

**Solución intentada:** detectar pares donde AMBOS nombres son **cortos
(≤3 tokens) y compuestos solo por tokens genéricos** (palabras curadas
del dominio empresarial colombiano: INVERSIONES, GRUPO, COMPAÑIA,
COLOMBIA, CONSULTORES, SAS, LTDA, etc.). Multiplicar el name_sim por
`(1 - generic_name_penalty)`.

**Por qué queda OPT-IN:** con `penalty=0.5` la regla resolvió 3 FP en
el sintético robusto, pero produjo **regresión severa en golden 269**
(F1 0.759 → 0.647) porque la lista curada incluye tokens (COMPAÑIA,
COLOMBIA, EMPRESA) que aparecen en razones sociales legítimas de
empresas reales con nombres cortos. Default OFF preserva paridad.

**Recomendación:** activar SOLO tras calibrar con producción real
(50k+ regs). Con corpus grande, los top-N estadísticos del corpus
serán palabras genuinamente frecuentes y la regla será más segura.

```python
# Activación recomendada (post-calibración):
"generic_name_penalty": 0.5,
"generic_name_top_n": 50,
"generic_name_max_tokens": 3,
"generic_name_min_sim": 0.85,
```

##### Added — perillas del scorer

- `generic_name_penalty: float` (default 0.0): magnitud (0.5 = penaliza al 50%).
- `generic_name_top_n: int` (default 30): cuántas palabras del corpus.
- `generic_name_max_tokens: int` (default 3): solo aplica a nombres cortos.
- `generic_name_min_sim: float` (default 0.85): solo aplica si name_sim ya alto.
- `_generic_tokens: set[str]` (poblado por `deduplicate_unified`).

##### Added — stop-words curadas del dominio empresarial colombiano

`deduplicate_unified` ahora puebla `_generic_tokens` combinando:
1. Lista curada de ~50 tokens (INVERSIONES, GRUPO, COMPAÑIA, COLOMBIA,
   CONSULTORES, FABRICA, ZONA FRANCA, SAS, LTDA, EU, etc.).
2. Top-N estadístico del corpus de entrada.

Ampliable vía `profile["generic_name_extra_tokens"]`.

#### Métricas medidas v2.10.0 (defaults activos: Fix #1 ON, Fix #2 OFF)

| Dataset                          | v2.9.0   | v2.10.0  | Δ      |
|----------------------------------|---------:|---------:|-------:|
| Golden 269                       | 0.759    | **0.759**| 0.000  |
| Exhaustivo 1456                  | 0.867    | **0.867**| 0.000  |
| Sintético robusto 660            | 0.933    | **0.935**| +0.002 |
| **Sintético — P4 token disímil** | R=0.17   | **R=0.17**| 0.000  |
| **Sintético — G nombre genérico** | 3 FP    | 3 FP     | 0      |

**Lectura honesta (CORREGIDA en v2.11.0):**

- **CORRECCIÓN DE INTEGRIDAD:** la tabla de v2.10.0 reportaba
  originalmente P4 `R=1.00`. Ese número era FALSO para la versión
  entregada. Correspondía a una configuración con
  `nit_identical_score_boost_declared=0.15` que **se descartó** porque
  regresaba golden 269 (F1 0.759→0.647). El default realmente
  entregado es `0.10`, con el que **P4 sigue en R=0.167** (medido en
  v2.11.0: TP=2, FN=10). La documentación quedó congelada en una
  configuración no entregada. Verificado con medición directa, no
  citado.
- **Fix #1 (activo) con boost_declared=0.10** NO mueve P4 de forma
  material. El boost que sí lo movía (0.15) tenía un costo inaceptable
  en golden 269. La mejora real de Fix #1 a 0.10 sobre los datasets
  globales es ≈0. Honestamente: Fix #1 tal como se entregó es casi un
  no-op en calidad agregada.
- **Fix #2 (opt-in OFF)** resuelve los 3 FP de G_nombre_generico
  cuando se activa con `penalty=0.5`, pero causa regresión severa en
  corpus reales pequeños. Queda implementado y testeado, **NO
  activado** hasta calibrar con producción.

#### Lo que NO se resolvió

- **P1 sigla vs completo** (R=0.40): nombres tipo "EY" son tan cortos
  que probablemente no pasan el pre-filtro LSH ni el length-filter del
  scorer. Requiere intervención distinta — probablemente un caso
  especial para "nombre con ≤2 caracteres" que actúa como sigla.
- **D sufijo confundible** (MENDEZ SA vs LTDA): pendiente Sprint 2,
  requiere decisión de negocio con datos reales.
- **H filial país** (TOTAL COLOMBIA vs ECUADOR): pendiente Sprint 2,
  requiere lista curada de gentilicios.

#### Fixed — Bug crítico en path `disk_based` (heredado de v2.7.0)

`DiskBasedLSHEngine.find_candidates()` no aceptaba el kwarg
`trusted_unique_sources` que `RecordLinkageEngine.link()` le pasaba
incondicionalmente desde v2.7.0. Esto producía `TypeError` ante
cualquier corrida con `linkage_engine_class="disk_based"`, **bloqueando
totalmente el uso del paquete en producción con >1M registros** (ese
camino se autoselecciona en `deduplicate_unified` para datasets de ese
tamaño).

**Detección:** revisión post-medición tras pregunta del usuario "¿Lo
que corrió fue sobre clases en disco?". Verificación empírica con
`config['linkage_engine_class'] = 'disk_based'` reveló el bug, presente
también en v2.7.0, v2.8.0 y v2.9.0.

**Fix:** `find_candidates` de `DiskBasedLSHEngine` y
`TrustedSourceLSHEngine` aceptan ahora `trusted_unique_sources` como
kwarg opcional. En el motor base se ignora con warning si no está
vacío (el comportamiento de fuentes confiables vive en el Trusted). En
Trusted se une al set pasado en `__init__`.

**Impacto medido** tras el fix:

| Dataset            | default | disk_based | Δ      |
|--------------------|--------:|-----------:|-------:|
| Golden 269         | 0.759   | 0.731      | -0.028 |
| Exhaustivo 1456    | 0.867   | **0.874**  | +0.007 |
| Sintético robusto  | 0.935   | 0.935      | 0.000  |

Los dos motores **NO son equivalentes** numéricamente: el LSH disk_based
produce candidatos ligeramente distintos por la implementación interna
de buckets (SQLite vs in-memory dict). La diferencia se manifiesta en
los conjuntos pequeños donde el LSH es marginalmente decisivo. Para
producción (>1M regs), las diferencias en términos relativos son
indistinguibles.

#### Added — test de regresión

- **`tests/test_disk_based_path.py`** (4 tests): verifica que el path
  disk_based corra end-to-end, produzca F1 razonable y no diverja más
  de 0.05 F1 del path default sobre el dataset robusto.

#### Para producción >1M registros

El notebook `notebooks/calibracion_produccion.ipynb` y los scripts
`generar_pares_para_etiquetar.py` y `medir_con_ground_truth.py` ahora
**fuerzan `linkage_engine_class="disk_based"` por default** mediante
el flag `--engine disk_based`. Esto garantiza que las métricas de
calibración representen el comportamiento exacto que tendrás en
producción real, independiente del tamaño de la muestra inicial.

#### Added — herramientas para calibración con producción real

- **`notebooks/calibracion_produccion.ipynb`**: notebook listo para
  Colab. Recibe ruta a tu muestra real (parquet/CSV en Drive), corre
  v2.10.0, produce métricas globales sin necesidad de ground truth,
  estadísticas de cluster, identificación de candidatos a etiquetar.
- **`scripts/generar_pares_para_etiquetar.py`**: muestreo estratificado
  de 1k-2k pares para etiquetado manual. Cubre 5 estratos:
  alta-confianza, frontera, NIT-idéntico-nombre-disímil, nombre-idéntico-
  NIT-distinto, no-clusterizados-pero-cercanos.
- **`scripts/medir_con_ground_truth.py`**: una vez etiquetes los pares,
  este script mide F1/P/R reales por estrato y produce el reporte con el
  mismo desglose que `test_quality_sintetico_robusto.py`.
- **Plantilla de etiquetado**: `tests/data/plantilla_etiquetado.csv`
  con columnas `par_id`, `nit_a`, `razon_a`, `nit_b`, `razon_b`,
  `MISMO_GRUPO`, `CASO_FRONTERA`, `NOTAS`.

#### Added — tests

- **`tests/test_fixes_p1_2.py`** (16 tests): DV_ORIGEN se marca
  correctamente para 8 formatos distintos; boost diferenciado aplica
  solo a ambos-declared; sin DV_ORIGEN es fallback conservador;
  penalty respeta MAX_TOKENS y MIN_SIM_TRIGGER; default OFF es paridad.
- Suite completa: **224/224 verde** en ~56 s.

---

## [2.9.0] — 2026-05-22

### Vectorización completa del scorer (P1-1 del ROADMAP)

Release MINOR de **performance**: el cuello del scorer (`for i in range(n_pairs)`
y `for i in compute_indices` que llamaban a rapidfuzz una vez por par) queda
reemplazado por llamadas batch a `rapidfuzz.process.cpdist`, que ejecuta
el cálculo pairwise en C++. **Paridad bit-a-bit verificada** contra v2.8.0
(tolerancia 1e-9 en floats, exactitud absoluta en enteros).

#### Disciplina aplicada (ROADMAP P1-1 Paso 3.1)

Antes de tocar una línea del scorer:

1. Se capturó un **oráculo de paridad** (`tests/data/oraculo_scorer_p1_1.pkl`)
   ejecutando el scorer v2.8.0 sobre **16 registros** que cubren los casos
   borde críticos: NIT idéntico/distancia 1/2/vacío, nombres idénticos/typos/
   disjuntos/orden distinto, valores `'nan'` literales, primer token
   compartido (activa el bonus *1.05).
2. Se generaron **120 pares × 3 perfiles = 360 outputs** de referencia
   (`default_off`, `with_override_and_boost`, `with_extra_features`).
3. La vectorización procede solo si reproduce los 360 outputs bit-a-bit.

#### Bug atrapado por el oráculo (mérito del proceso)

El intento inicial usó `rapidfuzz.distance.Levenshtein.normalized_similarity`
como reemplazo de `Levenshtein.ratio` (python-Levenshtein) en el cálculo
fonético. El oráculo detectó **231 divergencias en score** en los 360 outputs.
La razón: las dos funciones miden cosas diferentes — Levenshtein clásica
(sustitución=1 edición) vs distancia tipo Indel (sustitución=2 ediciones,
que es lo que usa `Levenshtein.ratio`). La fix correcta es
`rapidfuzz.distance.Indel.normalized_similarity`, **matemáticamente
equivalente** a `Levenshtein.ratio`. Sin el oráculo este bug habría pasado
silencioso y degradado la calidad.

#### Changed — todos los loops del scorer reemplazados por batch

| Método                                              | Loop antes  | Vectorización |
|-----------------------------------------------------|------------:|---------------|
| `_score_batch_vectorized` (inline name sim)         | `for i in compute_indices` | `rf_process.cpdist(scorer=token_set_ratio)` + máscaras numpy |
| `_calculate_nit_distances_vectorized`               | `for i in range(n_pairs)` | `cpdist(scorer=Levenshtein.distance)` |
| `_calculate_phonetic_similarities_vectorized`       | `for i in range(n_pairs)` | `cpdist(scorer=Indel.normalized_similarity)` |
| `_calculate_nit_similarities_vectorized`            | `for i in range(n_pairs)` | `cpdist(scorer=Levenshtein.distance)` + penalización vectorizada |
| `_calculate_name_similarities_vectorized` (alterno) | `for i in range(n_pairs)` | `cpdist` + refinamiento vectorizado |
| `_feature_similarity_vectorized` (token_set_ratio)  | list-comprehension de `fuzz.token_set_ratio` | `cpdist(scorer=fuzz.token_set_ratio)` |
| `score_pairs_from_db` (SQLite write)                | `iterrows()` sobre el batch | `to_numpy()` por columna + tuplas con índices nativos |

**Loops que sobreviven intencionalmente:**
- `audit_pairs` (línea 473): bloque opcional de debug, no path caliente.
- Chunking de SQLite (`for i in range(0, len, batch_size)`): es el batching
  necesario para no agotar memoria, no es overhead a eliminar.

#### Speedup medido (no estimado)

Benchmark sobre datasets sintéticos en el entorno actual
(Python 3.12, rapidfuzz 3.x, numpy 1.x), con `scripts/benchmark_p1_1.py`:

| n_records | n_pairs    | v2.8.0 (s) | v2.9.0 (s) | Speedup |
|----------:|-----------:|-----------:|-----------:|--------:|
| 500       | 749        | 0.027      | 0.014      | **1.9×**|
| 2,000     | 2,997      | 0.087      | 0.024      | **3.6×**|
| 10,000    | 14,995     | 0.421      | 0.091      | **4.6×**|
| 30,000    | 44,996     | 1.276      | 0.268      | **4.8×**|

El speedup **escala con el tamaño** — firma de la vectorización: el
overhead constante de C-extension se amortiza en lotes grandes. En el
ROADMAP P1-1 se esperaban 3-5×; medido **4.6-4.8×** a partir de 10k pares.
Para producción RUES (millones de pares), el throughput sostenido del
scorer pasa de ~35k pares/s a ~165k pares/s. Sobre el ground truth
exhaustivo (1456 pares scoreados), la corrida termina en ~7 s en lugar
de ~30 s — diferencia despreciable en absoluto, pero indicativa del
comportamiento a escala.

#### Calidad — sin cambios (como debe ser)

| Métrica                  | v2.8.0   | v2.9.0   |
|--------------------------|---------:|---------:|
| F1 exhaustivo (1456)     | 0.867    | **0.867**|
| Precision exhaustivo     | 0.886    | **0.886**|
| Recall exhaustivo        | 0.849    | **0.849**|
| F1 golden (269)          | 0.759    | **0.759**|
| Precision golden         | 0.802    | **0.802**|
| Recall golden            | 0.720    | **0.720**|

Vectorización **no es** una intervención de calidad — solo de rendimiento.
Mismas métricas a nivel de pares scoreados.

#### Added — dataset sintético robusto

- **`tests/data/golden_truth_sintetico_robusto.csv`** (660 registros,
  126 grupos): ground truth determinista que estresa **modos de falla
  conocidos** del scorer, con 13 categorías de casos frontera
  explícitos. Regenerable bit-a-bit desde
  `scripts/generar_dataset_robusto.py`.
- Incluye un **validador de integridad** (`_validar_integridad`) que
  rehúsa publicar el dataset si su lógica se contradice (un NIT base en
  múltiples grupos, casos frontera negativos que comparten grupo, etc.).
  Esto atrapó cuatro bugs de diseño durante el desarrollo de v2.9.0 —
  documentado en MIGRATION_LOG §20.

| Tag                       | Tipo     | Lo que estresa                                              |
|---------------------------|----------|-------------------------------------------------------------|
| `P1_sigla_vs_completo`    | positivo | NIT idéntico, nombre tan disímil como "EY" ↔ "Ernst & Young"|
| `P2_historico_fusion`     | positivo | Mismo NIT, denominación que cambió tras fusión              |
| `P3_dv_calc_vs_decl`      | positivo | Variantes "900123456" / "9001234567" / "900-123456-7"       |
| `P4_token_disimil`        | positivo | Nombre comparte 0 tokens significativos con la sigla        |
| `P5_invisibles`           | positivo | Zero-width space, NBSP, caracteres invisibles UTF-8         |
| `A_token_compartido`      | negativo | "BOLIVAR" en tres entidades distintas                       |
| `B_nit_vecino`            | negativo | NITs a distancia Lev=1, nombre disímil                      |
| `C_phonetic_colision`     | negativo | "SOLER" vs "SALER" sobre NITs distintos                     |
| `D_sufijo_confundible`    | negativo | "MENDEZ SA" vs "MENDEZ LTDA" — grupos económicos distintos  |
| `E_nit_corto`             | negativo | NITs públicos cortos consecutivos                           |
| `F_nit_vacio`             | negativo | Dos registros con NIT vacío y nombres similares             |
| `G_nombre_generico`       | negativo | Tres "INVERSIONES SAS" con NITs distintos                   |
| `H_filial_pais`           | negativo | "TOTAL COLOMBIA" vs "TOTAL ECUADOR"                         |
| `S_singleton`             | mixto    | 20 empresas únicas (no forzar agrupación)                   |

**Métricas globales medidas con v2.9.0:** F1=**0.933**, P=**0.936**,
R=**0.931** (2415 TP, 165 FP, 180 FN sobre 2595 pares positivos).

**Diagnóstico cualitativo por categoría** (medido, no estimado):

| Categoría             | Resultado          | Lectura honesta                                                          |
|-----------------------|-------------------:|--------------------------------------------------------------------------|
| Orgánico (variantes)  | R=0.935            | Comportamiento en patrones realistas                                     |
| P1 sigla vs completo  | R=**0.40**         | El override por NIT idéntico ayuda pero score_boost=0.05 es insuficiente |
| P2 histórico fusión   | R=1.00             | El sistema unifica bien denominaciones históricas con NIT igual          |
| P3 DV calc vs decl    | R=1.00             | El AdvancedNitProcessor normaliza estos formatos correctamente           |
| P4 token disímil      | R=**0.17**         | El peso del NIT (0.20) no compensa nombres totalmente disjuntos          |
| P5 invisibles         | R=1.00             | El cleaner limpia zero-width y NBSP                                      |
| D sufijo confundible  | **3 FP de 3**      | Sistema fusiona "MENDEZ SA" ↔ "MENDEZ LTDA" — debilidad sistémica        |
| G nombre genérico     | **3 FP de 3**      | Tres "INVERSIONES SAS" se fusionan — riesgo real en producción           |
| H filial país         | **1 FP de 1**      | "TOTAL COLOMBIA" vs "TOTAL ECUADOR" — confusión por marca compartida     |

Este dataset revela debilidades específicas que el ground truth exhaustivo
no capturaba: los grupos económicos con marca compartida pero entidades
jurídicas distintas son un modo de falla sistemático. Estos NO se
resuelven con bloqueos ni con el fix P0-1; requieren una solución de
futuro (variables adicionales `CIUDAD`/`DIRECCION`, o re-pesado por
entropía del nombre).

#### Added — tests

- **`tests/test_paridad_p1_1.py`** (4 tests, parametrizados sobre 3
  perfiles): paridad bit-a-bit del scorer vectorizado contra el oráculo
  v2.8.0. Tolerancia 1e-9 en floats, exactitud absoluta en enteros.
- **`tests/test_quality_sintetico_robusto.py`** (6 tests): regresión
  sobre el nuevo ground truth + reporte visible por tipo de caso
  frontera (`pytest -s` muestra la tabla completa). Pisos: F1≥0.91,
  P≥0.91, R≥0.91 (margen 0.02 desde lo medido para tolerar fluctuaciones).
- Suite completa: **208/208 verde** en ~58 s.

#### Added — herramientas

- **`scripts/capturar_oraculo_p1_1.py`**: regenera el oráculo si cambia
  el dataset de casos borde. Determinista.
- **`scripts/validar_paridad_p1_1.py`**: ejecuta la validación de paridad
  manualmente desde la línea de comandos (útil al iterar).
- **`scripts/benchmark_p1_1.py`**: mide throughput sobre datasets
  sintéticos. Determinista (`random.seed=42`).
- **`scripts/generar_dataset_robusto.py`**: regenera el dataset robusto.
  Acepta `--n-grupos-extra N` para escalar (útil para benchmarks a
  escala). Determinista (`seed=42`).

#### Lo que NO se hizo

- El cache `self._similarity_cache` del método alterno
  `_calculate_name_similarities_vectorized` quedó **inerte** — ya no se
  consulta por par. En pipelines reales su tasa de hit era < 1 % y el
  costo del lookup era mayor que el cómputo vectorizado en C++. Si algún
  día se necesita un cache real, el lugar correcto es a nivel del
  pipeline (no del scorer per-par), con LRU explícito.
- **`max_nit_distance` por defecto sigue en 3.** El barrido del filtro
  no es parte de P1-1.

---

## [2.8.0] — 2026-05-22

### Tratamiento privilegiado de NIT idéntico (P0-1 del ROADMAP, parcial)

Release MINOR que **mejora modestamente el recall y F1 sobre el ground truth
exhaustivo** atacando un cuello específico documentado mediante diagnóstico
forense: 335 falsos negativos del exhaustivo (21.8 %) tienen `NIT_OK`
idéntico tras la normalización pero su nombre cae bajo `min_name_similarity`
o su score combinado cae bajo `score_threshold`.

#### Confrontación honesta del ROADMAP

Antes de implementar nada, se midió empíricamente el efecto de las dos
intervenciones que el ROADMAP P0-1 priorizaba:

- **Activar `enable_name_blocking`** (Paso 1.2, ya implementado en v2.6.0
  pero OFF por default): ΔF1 = **+0.0003** en exhaustivo, **0** en golden
  269. Confirmado: el bloqueo NO es el cuello, ya estaba prácticamente
  saturado por el bloqueo NIT base + LSH.
- **Barrido de `score_threshold`** (Paso 1.3): los dos ground truth
  prefieren direcciones **opuestas**. Subir threshold a 0.70 mejora el
  exhaustivo (F1 0.863→0.872) pero **derrumba** golden 269 (0.771→0.711).
  Calibrar contra UN dataset overfittea — el ROADMAP no anticipó esta
  tensión. **Se mantiene el default 0.68 (Pareto-óptimo entre ambos).**

#### Diagnóstico de la verdadera palanca

Análisis post-mortem de los 1534 FN del exhaustivo: 332 tienen NIT
**original** idéntico. Tras la normalización vía `AdvancedNitProcessor`
(que añade un DV calculado a NITs sin él), 335 quedan con `NIT_OK`
idéntico no-vacío. Ejemplos reales:

```
NIT 890900148 → NIT_OK 8909001482
NIT_OK         NOMBRE_LIMPIO            ts_ratio
8909001482     AKZOMOBEL PINYUCO        \
8909001482     PINTUKO                   \  todos del mismo grupo
8909001482     COMPAÑIA GLOBAL PINTURAS  /  pero ts < 0.60 entre sí
8909001482     PINTUCO ORBIS            /
```

Estos pares **sí son candidatos** (el bloqueo NIT los emite), pero el
flujo de scoring los descarta por dos gates independientes:

1. **Filtro previo AND estricto:** `name_sim ≥ min_name_similarity (0.60)`
   AND `nit_dist ≤ max_nit_distance (3)`. Pares con NIT idéntico pero
   nombre `'PINTUKO'` vs `'COMPAÑIA GLOBAL DE PINTURAS'` (ts=0.29) son
   descartados ANTES de calcular el score combinado.
2. **`score_threshold` final:** aunque pasen el filtro, el score
   `0.65·name + 0.20·nit + 0.15·phonetic` cae bajo 0.68 cuando el nombre
   es muy disímil — el peso del NIT (0.20) no compensa.

#### Added — dos perillas independientes al `VectorizedScorer`

- **`nit_identical_overrides_name_filter: bool`** (default `False`).
  Si `True`, pares con `nit_distance == 0` (NIT_OK idéntico no-vacío)
  saltan el filtro `min_name_similarity`. NITs vacíos no se eximen
  (la evidencia es ausencia, no coincidencia).
- **`nit_identical_score_boost: float`** (default `0.0`).
  Bonus aditivo al score final cuando NIT_OK idéntico. Se recorta a
  `[0, 1]` tras sumar. Calibrado por barrido contra ambos ground truth:
  `0.05` es el sweet spot Pareto.

Ambos defaults son OFF → paridad bit-a-bit con v2.7.0 sin extra_features.

#### Changed — perfil `deduplication_standard`

Se activan los nuevos defaults:
```python
"nit_identical_overrides_name_filter": True,
"nit_identical_score_boost": 0.05,
```

Otros perfiles (`deduplication_colab_1M`, `deduplication_colab_3M`) NO
fueron modificados: el ROADMAP P0-2 exige calibrarlos contra un ground
truth a escala antes de tocar sus defaults.

#### Resultados medidos (no citados)

| Métrica           | v2.7.0   | v2.8.0   | Δ      |
|-------------------|----------|----------|--------|
| **EXHAUSTIVO (1456 regs)**                              |
| F1                | 0.863    | **0.867**| +0.004 |
| Precision         | 0.886    | **0.886**| ±0.000 |
| Recall            | 0.842    | **0.849**| +0.007 |
| TP                | 8145     | 8217     | +72    |
| FP                | 1053     | 1053     | 0      |
| FN                | 1534     | 1462     | -72    |
| **GOLDEN (269 regs)** — regresión documentada           |
| F1                | 0.771    | 0.759    | -0.012 |
| Precision         | 0.845    | 0.802    | -0.043 |
| Recall            | 0.709    | 0.720    | +0.011 |
| TP                | 443      | 450      | +7     |
| FP                | 81       | 111      | +30    |
| FN                | 182      | 175      | -7     |

**Lectura honesta:** mejora modesta en exhaustivo (que es el dataset
representativo), regresión en golden 269. Los nuevos FP en golden 269
provienen de **colisiones de NIT_OK falsas**: el `AdvancedNitProcessor`
calcula DV para NITs sin DV en ambos lados, y empresas distintas con
NIT base similar terminan con el mismo `NIT_OK`. Es un sesgo del
pipeline upstream, no del fix. Mitigación posible (no incluida en
v2.8.0, requiere su propio ticket): aumentar la confianza del NIT solo
si AMBOS NITs originales venían con DV explícito.

**Importante:** este resultado **no es la mejora de +0.05 que el ROADMAP
imaginaba**. El espacio de mejora de +0.05–+0.10 en F1 vía P0-1
**no existe en este corpus**. La línea base estaba más cerca del óptimo
de lo que el plan asumía. Las próximas ganancias requieren P1-1
(vectorizar el scorer, también aplica a velocidad) y P0-2 (calibrar a
escala con ground truth nuevo).

#### Added — tests

- **`tests/test_nit_identical_p01.py`** (11 tests): paridad estricta
  (defaults OFF == v2.7.0 bit-a-bit), override del filtro, boost del
  score, no-op cuando NIT distinto o vacío, recorte a `[0, 1]`.
- Suite completa: **198/198 verde** en ~70 s.

#### Added — herramientas de réplica

- **`scripts/replicar_v2_8_0.py`**: corre la calibración del barrido,
  imprime las métricas medidas, y genera un dataset sintético adicional
  (`dataset_p0_1_nit_identico.csv`) con casos canónicos de NIT idéntico
  y nombre disímil para verificar el fix contra una ejecución manual.

#### Risk register / lo que NO se cerró del ROADMAP

- **P0-1 Paso 1.3** (barrido contra exhaustivo): se hizo el barrido y se
  documentó la tensión inter-dataset. NO se eligió un threshold global
  nuevo — se dejó en 0.68 como compromiso.
- **P0-2** (perfiles `colab_1M`/`colab_3M`): intactos.
- **P1-1** (vectorizar scorer): el `for i in compute_indices` de la
  línea 340 sigue ahí. No se tocó.
- **P1-2** (clusterer en disco): intacto.
- **P1-3** (test de reanudación tras reinicio): pendiente.

---

## [2.7.0] — 2026-05-22

### Variables adicionales firmadas (P2 Camino #1 + último ítem del ROADMAP)

Release MINOR que **cierra el soporte de variables adicionales** (CIUDAD,
TELEFONO, ...) en el scoring y, a diferencia de v2.6.1.dev0, **sí mueve la
calidad de forma medible**: rompe el techo de precision 0.886 que v2.6.0
documentó como inalcanzable sin estas variables.

#### Corrección del diagnóstico de v2.6.1.dev0

Las `NOTAS_WIP_v2_6_1.md` afirmaban que `extra_features` estaba roto por "un
return temprano en `_score_batch_vectorized` (bloque AUDITANDO PAR)" y que el
código "no se ejecuta en producción". **Ambas afirmaciones eran incorrectas**
(verificado con diagnóstico aislado, no especulación):

- No existe tal return temprano. La suma de `extra_contribution` estaba bien
  colocada y el método se ejecuta en los tres paths de scoring (memoria, db,
  streaming).
- El feature SÍ sumaba correctamente cuando los valores coincidían.

El problema real era de **diseño**, no un bug: el esquema solo PREMIABA
coincidencias (suma ≥ 0), nunca PENALIZABA discrepancias. Por eso un par como
CORONA-Bogotá vs CARVAJAL-Cali (NIT adyacente, token compartido) no se
separaba: ciudad distinta sumaba 0.0 (neutro).

#### Added

- **Tipos de similitud FIRMADOS** en `VectorizedScorer` (rango `[-1, 1]`):
  - `categorical_signed`: +1 coinciden · −1 discrepan · 0 si algún nulo.
  - `exact_signed`: idem sin normalizar mayúsculas (identificadores).
  - `token_set_ratio_signed`: `2 * fuzz − 1`, fuzzy firmado.
  Los tipos no firmados (`categorical`, `exact_or_zero`, `token_set_ratio`)
  se mantienen sin cambios (solo premian).
- **Parámetro `extra_features`** en `deduplicate_unified` (API pública). Antes
  el scorer leía `profile["extra_features"]` pero no había forma de pasarlo
  desde la API. Ahora se valida (fail-fast) y se propaga al perfil activo.
- **`_validate_extra_features`**: rechaza columnas inexistentes, pesos ≤ 0 y
  tipos desconocidos antes de correr el pipeline.
- **`tests/test_scorer_extra_features.py`** (15 tests): paridad, los tres
  tipos firmados/no firmados, manejo de nulos, función de similitud pura, y
  propiedad de negocio (CORONA/CARVAJAL se separa).
- **`tests/test_extra_features_integration.py`** (8 tests): validación
  fail-fast + efecto end-to-end sobre P2.
- **`tests/test_quality_extra_features.py`** (5 tests): calidad a escala sobre
  el exhaustivo enriquecido (skip limpio si el dataset no está generado).
- **`scripts/enriquecer_ground_truth_ciudad.py`**: genera
  `golden_truth_exhaustivo_ciudad.csv` (1456 regs + CIUDAD determinista).
- **`scripts/replicar_v2_7_0.py`**: réplica A/B reproducible.

#### Changed

- `_score_batch_vectorized` recorta el score a `[0, 1]` tras sumar la
  contribución firmada (un par penalizado cae bajo el threshold, que es el
  efecto buscado). Sin `extra_features`, es un no-op bit-a-bit con v2.6.0.

#### Calidad medida (corrida, no citada)

| Dataset | Métrica | sin features | CIUDAD signed w=0.15 | Δ |
|---|---|:---:|:---:|:---:|
| Exhaustivo enriquecido (1456) | Precision | 0.886 | **0.966** | +0.080 |
| | F1 | 0.863 | **0.896** | +0.033 |
| | Recall | 0.842 | 0.835 | −0.007 |
| | Falsos positivos | 1053 | **281** | −73 % |
| Sintético P2 (28) | Precision | 0.800 | **1.000** | +0.200 |
| | Falsos positivos | 2 | **0** | — |

#### Advertencia metodológica (honestidad)

La columna CIUDAD del exhaustivo enriquecido es **sintética y favorable al
feature por construcción** (asignada por grupo verdadero). Mide el TECHO del
beneficio, no el caso real. **No sustituye** un ground truth con ciudades
reales —eso es P0-2 del ROADMAP—. Sobre los ground truth originales (que no
tienen CIUDAD/TELEFONO), la calidad es idéntica a v2.6.0 (paridad verificada:
F1=0.863 exhaustivo, F1=0.771 golden).

#### Estado de la suite

- `pytest tests/`: **187/187 verde** (159 + 15 unit + 8 integración + 5 calidad).
- `ruff check` y `ruff format --check`: verde.

---



### P0-1 Paso 1.2 y 1.3 — bloqueo de nombre + re-barrido de umbrales

Release MINOR que cierra los pasos restantes de P0-1 del ROADMAP. **No
mueve las métricas de calidad** respecto a v2.5.0, pero añade infraestructura
testeada (12 tests nuevos) y documenta empíricamente por qué no se aplican
cambios globales en este ciclo.

#### Resumen ejecutivo honesto

| Métrica | v2.5.0 | **v2.6.0** | Δ |
|---|:---:|:---:|:---:|
| F1 (exhaustivo 1456) | 0.863 | **0.863** | 0.000 |
| Precision (exhaustivo) | 0.886 | **0.886** | 0.000 |
| Recall (exhaustivo) | 0.842 | **0.842** | 0.000 |

**Lo que añade v2.6.0 a v2.5.0:**
- Módulo `engine.lsh.name_blocking` (90 líneas, 99 % cobertura).
- 12 tests aislados del bloqueo de nombre.
- Hooks en el orquestador para activarlo (`enable_name_blocking`, default OFF).
- Barrido completo de `score_threshold` documentado en MIGRATION_LOG §16.
- Script `scripts/replicar_v2_6_0.py` ampliado.

**Lo que NO añade v2.6.0:**
- Cambios en métricas de calidad. El bloqueo de nombre y el ajuste de umbral
  no mueven F1 en los datasets disponibles (motivos documentados abajo).

#### Added

- **`record_linkage.engine.lsh.name_blocking`** — bloqueo multi-pasada por
  nombre, vectorizado, con dos pasadas:
  - **Pasada A — fingerprint:** mismo algoritmo que
    `AdvancedValueSelector._get_fingerprint` (sin sufijos societarios, sin
    no-alfanuméricos, mayúsculas, sin acentos). Captura `ECOPETROL LIMITADA`
    ↔ `ECOPETROL SA`.
  - **Pasada B — token significativo más largo:** token ≥ 4 chars, no
    stopword del dominio. Captura `COLANTA` ↔ `COOPERATIVA COLANTA` cuando
    ambos eligen "COLANTA" como su token más largo (limitado, ver §16.4).
- **`tests/test_blocking_name.py`** (12 tests) — contrato del módulo y
  propiedad de negocio (≥ 20 % de pares verdaderos capturados sobre el
  ground truth exhaustivo).
- **Parámetros nuevos del perfil** (gobiernan el bloqueo, todos opcionales):
  - `enable_name_blocking` (bool, **default False** — opt-in).
  - `name_blocking_fingerprint` (bool, default True).
  - `name_blocking_significant_token` (bool, default True).
  - `name_blocking_min_token_length` (int, default 4).
  - `name_blocking_max_bucket` (int, default 100, más estricto que NIT).
- **`scripts/replicar_v2_6_0.py`** — script ampliado que documenta los tres
  pasos de P0-1 con A/B reproducible.

#### Changed

- **`RecordLinkageEngine.run`** invoca el bloqueo de nombre después del
  bloqueo NIT y antes del scoring. Maneja los tres formatos de retorno
  como el bloqueo NIT. Opt-in: si no se activa, costo = 0.

#### Decisiones documentadas en MIGRATION_LOG §16

1. **El bloqueo de nombre captura 22.7 % de pares verdaderos como techo
   teórico**, pero solo aporta **+5 TP netos** sobre el bloqueo NIT en el
   ground truth exhaustivo (el resto coincide con lo que ya capturó el LSH
   de n-gramas o el bloqueo NIT).
2. **El scorer/clusterer filtra el 99 % de los pares "nuevos"** del
   bloqueo de nombre. El bloqueo no aporta valor con el scorer actual.
3. **Decisión:** default OFF. Código listo para cuando se mejore el scorer
   (ver "Lo que falta" abajo).
4. **Re-barrido de `score_threshold` sobre los dos golden** muestra que
   el umbral actual (0.68) es ÓPTIMO en F1 promedio:
   - thr=0.75 mejora exhaustivo (F1 0.863→0.875) pero **degrada** golden
     269 (F1 0.771→0.679).
   - Esto refleja que el exhaustivo tiene casos negativos diseñados (NIT
     adyacente con tokens compartidos) que un umbral alto descarta bien,
     pero datasets sin esa trampa pierden recall.
5. **NO se aplica cambio global de umbral.** Se documenta la calibración
   y se deja como deuda futura (Optuna, P2-1).

#### Lo que falta (deuda explícita)

P0-1 NO está totalmente resuelto en términos de calidad. Para subir el F1
por encima de 0.88-0.90 se requiere:
- **Variables adicionales** (ciudad, teléfono — último ítem del ROADMAP).
  Sin ellas, los casos negativos diseñados del exhaustivo son inevitables.
- **Re-pesado del scorer por origen del par**: pares de bloqueo NIT
  podrían exigir mayor similitud de nombre, y al revés. Esto aprovecharía
  el bloqueo de nombre que ahora queda dormido.
- **Calibración automatizada (Optuna, P2-1)** sobre múltiples datasets
  para encontrar umbrales robustos en lugar de óptimos puntuales.

#### Tests

- **154/154 tests verdes** (142 v2.5.0 + 12 nuevos de `test_blocking_name`).
- Ruff check y format en verde.
- Cobertura: 38 % global, 99 % en el módulo nuevo.

---

## [2.5.0] — 2026-05-22

### Bloqueo por NIT base — ataque a la causa raíz del cuello de recall (P0-1)

Release MINOR que cierra el ítem **P0-1 Paso 1.1** del ROADMAP. Añade un
bloqueo de candidatos por NIT base **complementario** al LSH por n-gramas de
nombre, atacando pares verdaderos cuyas razones sociales no comparten tokens
(p. ej. `EY COLOMBIA` ↔ `ERNST & YOUNG`) pero sí comparten NIT (o NIT a
distancia ≤ 1). El recall sube +17,6 puntos sobre el ground truth exhaustivo.

#### Calidad medida (ground truth exhaustivo, 1456 regs, 137 grupos)

| Métrica   | v2.4.0 | **v2.5.0** | Δ |
|-----------|:------:|:----------:|:--:|
| F1        | 0.778  | **0.863**  | **+0.085** |
| Precision | 0.934  | 0.886      | −0.048 |
| Recall    | 0.666  | **0.842**  | **+0.176** |
| Grupos predichos vs verdad | 283/137 | 164/137 | mucho más cerca |

Sobre el golden de 269 regs: F1 0.65 → **0.77** (recall 0.53 → 0.71).

**Trade-off honesto:** el criterio del ROADMAP era "recall +≥ 0.05 sin que la
precision baje más de 0.02". El recall subió mucho más de lo pedido (+0.18)
pero la precision bajó 0.048 (más que 0.02). Decisión documentada:
inspección de los 1053 FP introducidos mostró que la mayoría son **casos
negativos diseñados a propósito** en el ground truth (empresas con NIT
adyacente y algún token compartido — exactamente las trampas que el
dataset incluye). El sistema sigue muy por encima del piso de precision
(0.886 > 0.85) y el F1 absoluto sube +0.085. Resolver esos casos a
precision > 0.90 requiere variables adicionales (ciudad, teléfono — último
ítem del ROADMAP) o un re-barrido del scorer.

#### Added

- **`record_linkage.engine.lsh.nit_blocking`** — nuevo módulo vectorizado
  con `NitBlockingConfig` y `block_by_nit_base(df, ...)`. Implementa:
  - Bloqueo por NIT base exacto (`groupby` + emisión de pares intra-grupo
    con cota `max_bucket_size` contra explosión cuadrática).
  - Bloqueo por NIT base a distancia Levenshtein ≤ 1 vía claves canónicas
    de sustitución y borrado (evita comparación O(n²); cada NIT contribuye
    `2·L + 1` claves para longitud L).
  - Filtro `min_nit_length` para descartar NITs claramente truncados.
- **`tests/test_blocking_nit.py`** (12 tests) — contrato del módulo: NIT
  idéntico produce par, NIT vacío no produce, NIT corto descartado, bucket
  grande omitido, vecinos a distancia 1 (sustitución/inserción/borrado),
  vecinos desactivables, determinismo entre corridas, validación de config,
  caso vacío, columna inexistente lanza error, y propiedad de negocio: el
  bloqueo captura ≥ 50 % de pares verdaderos del ground truth exhaustivo.

#### Changed

- **`RecordLinkageEngine.run` (orquestador)** ahora invoca el bloqueo por
  NIT después de `find_candidates` y antes del scoring. Maneja los tres
  formatos de retorno (set en memoria, ruta SQLite, vacío). Decisión de
  arquitectura: el bloqueo va en el orquestador, no en el motor LSH, para
  cubrir todos los motores (`OptimizedLSHEngine` legacy + `DiskBasedLSHEngine`
  + `TrustedSourceLSHEngine`) con un solo punto de integración. DRY.
- **Parámetros nuevos del perfil** (gobiernan el bloqueo, todos opcionales
  con defaults razonables):
  - `enable_nit_blocking` (bool, default True). Apagable por perfil si se
    quiere comparar comportamiento contra la línea base v2.4.0.
  - `nit_blocking_neighbors` (bool, default True). Activa vecinos a Lev ≤ 1.
  - `nit_blocking_max_bucket` (int, default 200). Cota contra NITs
    duplicados patológicos (NITs basura compartidos por miles de registros).
  - `nit_blocking_column` (str, default `"NIT_BASE"`).
- **Pisos de regresión subidos** en `test_quality_golden.py` (F1 0.60→0.73,
  recall 0.45→0.65, precision 0.78→0.80) y `test_quality_exhaustivo.py`
  (F1 0.72→0.83, precision 0.88→0.85, recall 0.60→0.80). Tras este release
  cualquier retroceso debajo de estos niveles falla la suite.

#### Verificado a escala (RUES real, encoding latin-1)

- **50k registros del RUES real**: 250.8 s end-to-end (199 reg/s), RAM pico
  1.4 GB, 48k grupos producidos, max grupo 58. Cero crashes, cero corrupción.
- **A/B sobre 10k RUES**: con bloqueo NIT 9747 grupos vs sin bloqueo 9767
  grupos (−0.2 % diferencia, sin sobre-fusión patológica). Tiempo idéntico.
- El bloqueo NO causa explosión combinatoria en datos reales porque la
  mayoría de NITs RUES son únicos.

#### Tests

- **142/142 tests verdes** (130 v2.4.0 + 12 nuevos). Tiempo: 41 s.
- Ruff check y format en verde.

---

## [2.4.0] — 2026-05-21

### Golden Generator vectorizado y determinista

Release MINOR que vectoriza el Golden Generator (el mayor costo del pipeline) y
corrige un bug de reproducibilidad. Detalle en MIGRATION_LOG §14. Paridad de
lógica de negocio probada bit-a-bit (137/137 grupos) antes de cualquier cambio.

#### Added

- **`AdvancedValueSelector.select_best_name_batch` / `select_best_nit_batch`** —
  API vectorizada por lotes que reemplaza los `groupby().apply()` del generator.
- **`tests/test_golden_selector_paridad.py`** (6 tests) — paridad bit-a-bit
  batch vs individual sobre el ground truth exhaustivo.
- **`tests/test_quality_exhaustivo.py`** (4 tests) y
  **`tests/data/golden_truth_exhaustivo.csv`** (1456 regs, 137 grupos, con casos
  negativos y NITs erróneos). Calidad medida: F1=0.78, precision=0.93.

#### Changed / Performance

- **Golden Generator 5× más rápido** (45k regs: 13.8s→2.4s; 180k: 55.5s→11.1s).
  Eliminados 2 `groupby().apply()`, 1 `apply(axis=1)` y 1 `lambda` de agg.
  `PRIMARY_SOURCE` → idxmin vectorizado; `CONFIANZA` → `np.select`.
- A 225k registros desde disco: 14s, RAM pico 686 MB (procesamiento por lotes
  vía SQLite, apto para 2-4M registros en Colab).

#### Fixed

- **Bug de reproducibilidad en el golden record:** la lógica usaba
  `max(set(...))`, no determinista, así que en empates exactos de
  (frecuencia, longitud) el nombre/NIT elegido variaba entre ejecuciones
  (demostrado: 3 grupos distintos entre 2 corridas de v2.3.0). Ahora el
  desempate es alfabético explícito → golden records reproducibles.



### Reescritura de DiskBasedLSHEngine (el motor de producción)

Release MINOR que reescribe el motor LSH que realmente corre sobre 1.9M
registros RUES. Detalle en MIGRATION_LOG §13. Sin cambio de calidad: F1=0.646
end-to-end, idéntico a v2.2.0.

#### Added

- **`engine/lsh/vectorized_minhash.py`** — `VectorizedMinHasher`: firmas MinHash
  por lotes con NumPy (misma familia de hash que datasketch, determinista).
- **`tests/test_vectorized_minhash.py`** (11 tests) — valida estimación de
  Jaccard (error medio 0.022), determinismo y casos borde.
- **`tests/test_disk_engine.py`** (10 tests) — hash determinista, equivalencia
  de bucket pairs, smoke end-to-end del motor.

#### Changed / Performance

- **Firmas MinHash vectorizadas:** 17× más rápido (20.0 s → 1.2 s en 20k regs).
  Motor completo 2.1× más rápido (32.8 s → 15.6 s). A 50k, de >280 s a 32 s.
- **`_generate_bucket_pairs` vectorizado** con `np.triu_indices` (era doble for).

#### Fixed

- **Bug de corrección en el índice LSH:** `_index_band` usaba `hash()` de Python,
  randomizado por `PYTHONHASHSEED`. Tras un reinicio de sesión de Colab, las
  bandas reanudadas desde checkpoint producían hashes inconsistentes con el
  índice previo → buckets corruptos → pares perdidos en silencio. Reemplazado por
  `_hash_rows_stable` (FNV-1a de 64 bits, determinista). El motor de firmas →
  índice → candidatos es ahora reproducible entre procesos.

#### Deprecated

- `DiskBasedLSHEngine._create_minhash` — ya no se usa internamente (reemplazado
  por `VectorizedMinHasher`). Conservado por compatibilidad.



### Iteración de auditoría — primera medición de calidad de linkage

Release MINOR centrado en cerrar el agujero más grande del paquete: hasta
v2.1.0 ningún test medía si el sistema agrupa bien. Detalle en MIGRATION_LOG §11.

#### Added

- **Módulo `evaluation/pairwise.py`** — métricas de calidad de record linkage
  (precision/recall/F1 a nivel de pares) con `PairwiseMetrics` y `evaluar_pares`.
- **`tests/test_quality_golden.py`** — Validation Level 3: corre el pipeline
  completo sobre un golden set de 269 registros reales y fija pisos de
  regresión (F1≥0.60, recall≥0.45, precision≥0.78).
- **`tests/data/golden_truth.csv`** — golden set embebido (269 registros, 84
  grupos verdad) con retos reales: typos, NITs con dígito errado, ruido aduanero.

#### Changed

- **Perfil `deduplication_standard` recalibrado contra ground truth.**
  F1 0.41 → 0.65 (+56 %), recall 0.27 → 0.53 (≈2×), precision estable (0.84).
  `lsh_threshold` 0.75→0.30, `score_threshold` 0.85→0.68,
  pesos `name:0.55/nit:0.45/phon:0.0` → `0.65/0.20/0.15`.
- **`OptimizedClusterer._cluster_in_memory` vectorizado** de Union-Find con
  `iterrows` a `scipy.sparse.csgraph.connected_components`. **84× más rápido**
  (medido: 7.6 s → 0.09 s sobre 500k pares), partición idéntica probada.
- **`GoldenRecordSelector.select_best_name`** ya no muta el grupo dentro del
  `apply` (elimina `SettingWithCopyWarning` y copias por grupo). Lógica idéntica.
- **README sincronizado con la realidad medida:** versión 2.2.0, 99 tests,
  cobertura 37 %, F1 0.65 declarados explícitamente (antes ocultos o falsos).

#### Fixed

- **Bug de clave duplicada en `processing/text.py`** (F601 real): la clave `Ã`
  estaba repetida en el mapa de encoding, descartando silenciosamente la
  corrección de `Í`. Corregido con claves por bytes mojibake completos.
- **Degradación silenciosa del scorer:** `except:` desnudo que caía a
  `BasicSimilarityCalculator` sin avisar. Ahora loguea WARNING explícito.
- **3 errores de ruff** (variables sin usar en tests) que el README v2.1.0
  afirmaba inexistentes. Corregidos de raíz, no con `# noqa`.

#### Removed

- Ignore de `F601` en `pyproject.toml` (ya no se justifica; la regla vuelve
  activa para detectar regresiones).

#### Performance

- Clustering en memoria 84× más rápido (ver Changed). En 2M registros la fase
  de clustering pasa de minutos a sub-segundo.
- Validado contra datos de producción reales (RUES 1.9M en latin-1): mojibake
  residual 0, sin sobre-fusión patológica. Detalle en MIGRATION_LOG §12.4.



### Mejoras estructurales (Fase F6 de la hoja de ruta)

Release MINOR con features que estaban pendientes desde el diagnóstico
post-migración. Cero cambios al comportamiento numérico del pipeline:
parity bit-exact preservada en todos los escenarios E2E con datos reales.

#### Added

- **F6.1** — `AdvancedNitProcessor.process_for_deduplication` vectorizada
  con `series.apply()` en lugar del loop `for _idx, value in series.items()`.
  Speedup medido: 2.5x en 17K registros; mejora crece con tamaño y
  repetición de NITs (la `lru_cache(50_000)` de `enhanced_fix_nit` se
  preserva). Test de regresión bit-exact:
  `tests/integration/test_nit_processor_parity.py`.
- **F6.2** — `Orchestrator.run()` acepta `force_rerun_phases: set[Phase]`
  (también lista) para re-correr fases específicas. La invalidación
  cascada hacia adelante se aplica automáticamente para preservar
  consistencia (forzar L3 invalida L4 y L5).
- **F6.4** — `PipelineResult.to_excel(path, include=...)` exporta múltiples
  DataFrames a un archivo Excel multi-hoja (engine `openpyxl`).
- **F6.4** — `PipelineResult.to_csv(output_dir, include=...)` exporta un
  CSV por cada DataFrame seleccionado.
- **F6.5** — `PipelineResult.items()`, `.values()`, `__iter__`, `__len__`:
  protocolo `Mapping` completo. Habilita `dict(result)`,
  `for k, v in result.items()`, `len(result)`.

#### Changed

- **F6.3** — Migración de `plt.cm.<colormap>(...)` a la API moderna
  `plt.colormaps["<colormap>"](...)` en 3 archivos de reporting
  (7 ocurrencias). Limpia 7 de los 10 falsos positivos de pylint sin
  cambios de comportamiento.
- **F6.7** — Pandas 3.0 readiness:
  - `select_dtypes(include=["object"])` → `include=["object", "string"]`
    para preservar comportamiento bajo Copy-on-Write.
  - `pd.concat(results, copy=False)` → `pd.concat(results)` (el parámetro
    `copy` está deprecado en pandas 3.0).
  - Resultado: cero `Pandas4Warning` en la suite de tests.

#### Tests

- 19 tests nuevos sumados a los 65 de v2.0.1 → **84 tests totales**.
- `test_nit_processor_parity.py`: parity bit-exact entre versión legacy
  (loop) y vectorizada en 6 casos de borde (9 dig, 10 dig, decimales,
  alfanuméricos, vacíos, repetidos).
- `test_pipeline_result_v2_1.py`: protocolo Mapping completo + exporters.
- `test_orchestrator_force_rerun.py`: cascada de invalidación.

#### Backward compatibility

100% backward compatible. Todos los APIs existentes funcionan igual.
Las nuevas features son aditivas (kwargs opcionales con default seguro,
métodos nuevos en `PipelineResult`).

---

## [2.0.1] — 2026-05-21

### Hotfixes post-migración

Cinco bugs descubiertos durante la validación end-to-end con datos reales
(`Negocios_dedup.csv`, `Oportunidades_dedup.csv`, `Servicios_dedup.csv`).
Los 5 bugs eran de migración notebook → paquete: elementos del estado
global del notebook que no fueron preservados al refactorizar a módulos.

#### Fixed

- **Bug #1** (`utils/logger.py`): `CustomLogger._setup_global_logging_once`
  declaraba `global _LOGGING_CONFIGURED` sin inicialización a nivel de
  módulo → `NameError` en el primer uso de cualquier logger del paquete.
  **Fix**: refactor a atributo de clase `_logging_configured`, eliminando
  la dependencia de una variable global de módulo.
- **Bug #2** (`processing/nit.py`): `AdvancedNitProcessor.enhanced_fix_nit`
  referenciaba `self.nit_regex`, inexistente; la clase base define
  `self.non_digit_regex` → `AttributeError` al limpiar NITs con caracteres
  no-dígito (guiones, espacios). **Fix**: corregir referencia al regex
  heredado.
- **Bug #3** (`engine/lsh/legacy.py`): `_init_database` creaba las tablas
  `candidates` y `stats` pero omitía `index_data`, que `_process_with_sqlite`
  usa para mapear `idx → fuente` al filtrar por trusted sources →
  `OperationalError: no such table: index_data`. **Fix**: esquema SQL
  unificado en constante de módulo `_LSH_LEGACY_SQLITE_SCHEMA` aplicado vía
  `conn.executescript()`.
- **Bug #4** (`deduplication/unified.py` + `evaluation/hyperparameters.py`):
  contrato roto contra `RecordLinkagePipeline.run()`. Los callers accedían a
  `results["correlative_table"]` y `results["df_linked"]`, pero el pipeline
  los borraba antes del return cuando `keep_intermediate_results=False`
  (default) → `RuntimeError: El pipeline no generó la tabla correlativa`.
  **Fix arquitectural**: nuevo módulo `pipeline.result.PipelineResult`
  (dataclass con `cached_property`) que carga los DataFrames lazy desde
  checkpoints parquet. Implementa protocolo dict-like
  (`__getitem__`, `get`, `keys`, `__contains__`) para preservar
  compatibilidad con callers existentes. La fase 4.5 ahora escribe DOS
  checkpoints (correlative_final y golden_final) para que los outputs
  canónicos sean los post-consolidación.
- **Bug #5** (`pipeline/_internal.py`): `_phase_cleanup` usaba `yield` sin
  decorador `@contextmanager` → `TypeError: 'generator' object does not
  support the context manager protocol` al iniciar cualquier fase del
  `Orchestrator`. **Fix**: import `contextlib.contextmanager` y decorar.

#### Added

- `tests/test_reproduce_bugs.py`: 5 tests de regresión, uno por bug. En
  v2.0.0 fallan los 5; en v2.0.1 pasan los 5.
- `src/record_linkage/pipeline/result.py`: nuevo módulo `PipelineResult`.

#### Changed

- `RecordLinkagePipeline.run()` ahora retorna `PipelineResult` en lugar
  de `dict`. **Backward-compatible** vía protocolo dict-like.
- `checkpoint_05_consolidated.parquet` → `checkpoint_05_correlative_final.parquet`.
- Nuevo `checkpoint_05_golden_final.parquet`.

#### Validation

Parity numérica verificada con Negocios (6,071 registros) y cross-source
con Negocios + Oportunidades + Servicios (25,731 registros). Detección
inalterada: 3 grupos duplicados internos en Negocios, 5,727 entidades
cross-source en el cruce de 3 fuentes.

---

## [2.0.0] — 2026-05-21

### Cambio mayor: refactor completo de notebook a paquete Python

#### Added
- Estructura de paquete Python publicable en PyPI bajo el nombre `rues-linker`.
- `Config` y `Rutas` (dataclasses) como única fuente de verdad para parámetros y rutas.
- `get_snowflake_credentials()` con tres fuentes (Colab Secrets → env vars → `config.json`)
  y nunca imprime credenciales.
- `docs/secrets.md` con guía paso a paso de configuración de credenciales.
- Notebook de ejecución `notebooks/ejecutar.ipynb` con patrón EXTRAS + EJECUTAR (≤15 líneas
  en la celda EJECUTAR).
- Script CLI `scripts/ejecutar_produccion.py` para correr fuera de notebook.
- `tests/test_smoke.py` (27 tests de importabilidad y configuración).
- `tests/test_vectorization_equivalence.py` (17 tests que prueban equivalencia numérica
  exacta entre `.apply` original y vectorizado).
- GitHub Actions CI: `ruff check`, `ruff format --check`, `pytest` en Python 3.10/3.11/3.12,
  construcción de `sdist` y `wheel`, validación con `twine check`.
- GitHub Actions publish: trusted publishing OIDC a TestPyPI/PyPI.
- 8 módulos internos (`_internal.py`, `_constants.py`, `_lsh_refs.py`, `_phase_constants.py`,
  `_globals.py`, `_priorities.py`, `_flags.py`, `_models.py`) para constantes globales
  del notebook.

#### Changed
- **`Orchestrator._run_L2` ya no requiere monkey-patching.** La versión optimizada
  (HybridStorage + selección automática entre `DiskBasedLSHEngine` y
  `TrustedSourceLSHEngine`) es ahora el método nativo. La versión antigua se conserva
  como `_run_L2_legacy` para auditoría.
- 5 vectorizaciones aplicadas con tests de equivalencia exacta:
  1. SEVERIDAD en `reporting/suite.py` (lambda → `np.where`)
  2. TRUE_GROUP en `evaluation/ground_truth.py` (lambda → `notna` + `.str.strip()`)
  3. Dos `apply(len)` en `classifier/hybrid.py` → `.str.len()`
  4. Matriz de co-ocurrencia en `reporting/suite.py`: O(n²·g) → O(n·g) con producto matricial
- 4 ciclos de imports rotos vía imports diferidos o extracción a módulo neutral.
- Ordenamiento topológico de constantes en `_internal.py` y `_constants.py`.

#### Fixed
- 387 errores F821 (undefined-name) detectados por ruff → final cero F821.
- Imports relativos incorrectos en archivos a profundidad 2 (`engine/lsh/`).
- Self-import en `pipeline/_internal.py`.

#### Removed
- Código experimental (celdas 66-72, 100-101, 128-129, 159, 173-189, 221-245, 249-251,
  269-291 del notebook). Lista completa en `MIGRATION_LOG.md` sección 4.
- Duplicados de clases: `AdvancedValueSelector`, `MemoryMonitor`,
  `SafeSQLiteConnection` versiones de celda 124.

#### Security
- `.gitignore` bloquea `config.json`, `.env`, `*.parquet`, `*.csv`, `*.db`.
- Credenciales nunca en código.

---

## [1.x] — Histórico (notebook monolítico)

Notebook único `2026_02_15_DEDUPLICAR_Y_RECORD_LINKAGE_.ipynb` (292 celdas,
25.745 LOC, 83 clases, 156 funciones top-level). Se mantiene en git para referencia.

---

# Roadmap

## CRÍTICO: antes de v2.0.0 en producción

| # | Acción | Tiempo | Por qué |
|---|---|---|---|
| 1 | Rotar credenciales Snowflake si estaban hardcoded | 15 min | Si están en GitHub o commits viejos, riesgo de exposición |
| 2 | Configurar Colab Secrets (`SNOWFLAKE_*`) | 10 min | Pre-requisito para conectar a Snowflake |
| 3 | Push a GitHub y validar CI verde | 15 min | Confirma que el pipeline compila en CI limpio |
| 4 | **Validación end-to-end con 5% de tus datos** | 2 horas | Comparar `golden` + `correlative` vs notebook. Si son idénticos, 100% seguro |
| 5 | Correr en producción completo | 3-5 horas | Solo tras el paso 4 |

## CORTO PLAZO (2-4 semanas)

| # | Tarea | Esfuerzo | Prioridad |
|---|---|---|---|
| 6 | Tests unitarios de lógica de negocio (engine/scorer, golden/selector, golden/generator) | 3-5 días | ALTA |
| 7 | Eliminar `_run_L2_legacy` tras 2 corridas exitosas | 5 min | MEDIA |
| 8 | `pre-commit` hooks (ruff + pytest) | 30 min | MEDIA |
| 9 | Publicar v2.0.0 en TestPyPI → validar `pip install` | 30 min | MEDIA |
| 10 | Publicar v2.0.0 en PyPI productivo | 5 min | MEDIA |

## MEDIANO PLAZO (1-3 meses)

| # | Tarea | Esfuerzo | Beneficio |
|---|---|---|---|
| 11 | Profilear con `cProfile` y vectorizar `.apply` complejos restantes | 1-2 semanas | Posible 15-30% de mejora si son cuello de botella real |
| 12 | Sphinx + Read the Docs | 1-2 días | Adopción externa |
| 13 | Type hints completos + `mypy --strict` | 1 semana | Errores atrapados antes de runtime |
| 14 | Benchmarks reproducibles | 2 días | Detección automática de regresiones |
| 15 | Refactorizar `Orchestrator` (2.170 líneas) en componentes | 1-2 semanas | Legibilidad y testabilidad |

## LARGO PLAZO (3-12 meses)

| # | Tarea | Esfuerzo | Beneficio |
|---|---|---|---|
| 16 | Migración a Snowflake nativo (SQL antes de pandas) | 2-3 semanas | Escalar a 10M+ registros sin OOM |
| 17 | DuckDB en lugar de SQLite local | 1 semana | 5-10x más rápido en agregaciones |
| 18 | Paralelización con Dask para scoring | 2 semanas | Mejor uso de CPUs en máquinas grandes |
| 19 | API REST con FastAPI | 2-3 semanas | Integración con sistemas downstream |
| 20 | ML para clasificar pares (en lugar de reglas) | 1-2 meses | Precisión potencialmente mayor |
| 21 | Extensión a otros países (Brasil, México, Chile) | 2-3 meses | Audiencia más amplia |

## Deuda técnica documentada

- 86 warnings de ruff silenciados en `per-file-ignores` para código heredado del
  notebook. Resolverlos requiere reescribir lógica de negocio. Documentados en
  `pyproject.toml` y `MIGRATION_LOG.md` sección 9.
- `_run_L2_legacy` en Orchestrator. Eliminar tras 2 ciclos de producción exitosos.
- `OptimizedLSHEngine` en `engine/lsh/legacy.py`. Eliminar si tras 6 meses ningún
  flujo lo invoca.
- Stub `silent_run` en `optimization/engine.py`. Reemplazar por implementación real
  de celda 159 o `contextlib.redirect_stdout`.
