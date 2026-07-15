# rues-linker

> **Pipeline de deduplicación y record linkage para fuentes empresariales colombianas**
> (RUES, DIAN, CRM, SUPERSOCIEDADES, EXPORTACIONES). Refactor estructurado del
> notebook `2026_02_15_DEDUPLICAR_Y_RECORD_LINKAGE_.ipynb` a paquete `.py`
> con auditoría completa y métricas validadas contra ground truth **sintético**.

[![CI](https://img.shields.io/badge/CI-passing-brightgreen)](.github/workflows/ci.yml)
[![Version](https://img.shields.io/badge/version-0.7.5-orange)](CHANGELOG.md)
[![Status](https://img.shields.io/badge/status-pre--1.0-yellow)](docs/VERSIONING.md)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![Tests](https://img.shields.io/badge/tests-506%2F506-brightgreen)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-58%25-yellow)](docs/AUDITORIA_SPRINT_0_6_0.md)
[![F1 vs GT](https://img.shields.io/badge/F1%20vs%20GT-0.84-brightgreen)](docs/AUDITORIA_FASE1.md)

**Autor:** Enrique Forero · **Versión:** `0.10.0` (pre-1.0) · **Python:** ≥ 3.10 · **Licencia:** Apache-2.0

> ## 📍 Estado actual: pre-1.0 (`0.x`)
>
> Esta es una **versión de desarrollo**. Aún NO está publicada en PyPI y la
> API puede cambiar entre minor releases.
>
> - **¿Funcional?** Sí — 506/506 tests pasan, F1=0.84 contra GT **sintético**
> - **¿Listo para producción crítica?** Aún no — falta validación contra
>   las 4 fuentes reales completas (1.97M registros)
> - **¿Cuándo 1.0?** Cuando CI/CD esté configurado, cobertura medida,
>   validación real completada. Ver [`docs/VERSIONING.md`](docs/VERSIONING.md)
>   para el roadmap detallado.

---

## ¿Qué hace este paquete?

A partir de varias fuentes con razones sociales y NITs que se superponen
(RUES, DIAN, CRM, SUPERSOCIEDADES, EXPORTACIONES), construye un **registro
único por empresa real** (golden record) usando:

1. **Limpieza** vectorizada de texto y NITs (`processing/`)
2. **Bloqueo LSH** con MinHash sobre n-gramas (`engine/lsh/`)
3. **Scoring** de pares candidatos (similitud de nombre + NIT + fonética)
4. **Clustering** de entidades por componentes conexos
5. **Golden record** generado por reglas de prioridad + pesos de calidad de fuente

Trabaja con **disco** (motor por defecto) o **memoria** según el tamaño de datos.

> **Escala verificada empíricamente: hasta 37k registros.** El objetivo de
> diseño es 2M registros con RAM < 60% en Colab Free, pero **eso aún no se ha
> medido** (pendiente; ver `docs/ROADMAP_PRODUCCION.md`, hito de medición real).

### Métricas medidas (no proyectadas)

Sobre el ground truth **sintético** `ground_truth_grande.csv` (12,427 registros, 3,486 grupos verdad; generado de forma determinista con `seed=42` — **no son datos reales del RUES**):

| Perfil | F1 | Precision | Recall | False Positives |
|---|---:|---:|---:|---:|
| `enterprise_scale_4_sources` (IT-7, default antiguo) | 0.0508 | 0.026 | 0.909 | 746,954 |
| **`produccion_calibrada`** (calibrado vs GT — v0.3.0+) | **0.8424** | **1.0000** | 0.7277 | **0** |
| `produccion_calibrada` + Optuna (20 trials, v0.3.2+) | 0.9304 | 0.9996 | 0.8701 | 1 |

**Mejora de IT-7 → calibrado: +79 puntos F1, FP de 747k → 0.**
Ver [`docs/AUDITORIA_FASE1.md`](docs/AUDITORIA_FASE1.md) para metodología.

---

## Instalación

### Local (recomendado mientras esté pre-1.0)

```bash
git clone https://github.com/USER/rues-linker.git
cd rues-linker
pip install -e .

# Con optimización Optuna (opt-in)
pip install -e ".[optimization]"

# Con visualización de reportes (opt-in)
pip install -e ".[viz]"

# Todo
pip install -e ".[all]"
```

### Desde `.tar.gz` (entrega)

```bash
pip install rues-linker-0.5.0-FULL.tar.gz
pip install "rues-linker-0.5.0-FULL.tar.gz[optimization]"
```

---

## Inicio rápido

### La API en cinco líneas (v0.9.0)

```python
import pandas as pd
import record_linkage as rl

df = pd.read_parquet("empresas.parquet")   # necesita columnas NIT y RAZON_SOCIAL
res = rl.dedupe(df)                        # ruta de producción validada (auto)
print(res.resumen())
res.correlativa.to_parquet("correlativa.parquet")
```

Cruce de dos bases (record linkage A↔B):

```python
res = rl.link(df_rues, df_aduanas, nombre_a="RUES", nombre_b="ADUANAS",
              trusted={"RUES"})
print(res.metricas["n_grupos_cruzados"], "entidades presentes en ambas bases")
```

`res` es un `ResultadoLinkage`: `.correlativa`, `.golden`, `.metricas` y
`.manifiesto` (trazabilidad total: huella de cada insumo, versiones del
entorno, hash de parámetros, seed). Perfiles por nombre: `rl.get_profile(...)`
sobre el registro único de `config/profiles.py`. Errores de entrada con
formato accionable: qué pasó / por qué importa / qué hacer. **Estos ejemplos
corren en CI** (`tests/test_ejemplos_quickstart.py`): si el README miente, la
suite se pone roja.


### Caso 1: Pipeline básico con perfil calibrado

```python
import pandas as pd
from record_linkage.config.profiles import crear_config_orchestrator
from record_linkage.pipeline.orchestrator import Orchestrator

# 1. Cargar tus fuentes (deben tener al menos NIT y RAZON_SOCIAL)
sources = {
    "RUES":            pd.read_csv("RUES.csv", sep="|", encoding="latin-1", dtype=str),
    "EXPORTACIONES":   pd.read_csv("EXPORTACIONES.csv", dtype=str),
    "CRM":             pd.read_csv("CRM.csv", dtype=str),
    "SUPERSOCIEDADES": pd.read_csv("SUPERSOCIEDADES.csv", dtype=str),
}

# 2. Config calibrado contra ground truth (F1=0.84 medido)
cfg = crear_config_orchestrator(perfil="produccion_calibrada", validate=True)

# 3. Correr pipeline
orch = Orchestrator(config=cfg, sources=sources, work_dir="./run_001")
result = orch.run()

# 4. Usar resultados
result["golden"].to_parquet("golden_records.parquet")
result["correlative"].to_parquet("tabla_correlativa.parquet")
```

### Caso 2: Calibrar con Optuna contra tu ground truth

```python
from record_linkage.evaluation import OrchestratorOptimizer

# Cargar ground truth (formato: ID_REGISTRO, ID_GROUP, FUENTE, ...)
gt = pd.read_csv("ground_truth_grande.csv", dtype=str)
gt["NIT"] = gt["NIT"].fillna("")
truth = gt[["ID_REGISTRO", "ID_GROUP"]].copy()
sources = {
    src: g[["ID_REGISTRO", "RAZON_SOCIAL", "NIT", "CIUDAD"]].reset_index(drop=True).copy()
    for src, g in gt.groupby("FUENTE") if len(g) >= 2
}

base_cfg = crear_config_orchestrator(perfil="produccion_calibrada", validate=False)
optimizer = OrchestratorOptimizer(base_config=base_cfg, sources=sources, truth=truth)
result = optimizer.optimize(n_trials=20, optimization_target="f1")

best_cfg = result["best_config"]   # listo para producción
print(f"Mejor F1: {result['best_score']:.4f}")
print(f"Mejores params: {result['best_params']}")
```

Notebook completo: **[`notebooks/04_optuna_calibration.ipynb`](notebooks/04_optuna_calibration.ipynb)**

### Caso 3: Auditar tu config existente

```python
from record_linkage.config import validar_config

reporte = validar_config(mi_config, verbose=True)
# Imprime warnings sobre claves dead/deprecated/partial
print(f"Dead: {reporte['dead']}")
print(f"Deprecated: {reporte['deprecated']}")
print(f"Partial: {reporte['partial']}")
```

---

## Perfiles disponibles

| Perfil | Cuándo usar | Métricas medidas |
|---|---|---|
| **`produccion_calibrada`** ⭐ | Producción real (calibrado vs GT) | F1=0.84, P=1.00, R=0.73 |
| `alta_precision` | Cuando un FP es costoso | F1=0.83, P=1.00 |
| `produccion_estandar` | Balanceado, configuración heredada | No medido contra GT |
| `produccion_exhaustiva` | Máxima cobertura, tolera FP | No medido contra GT |
| `deduplicacion_simple` | Solo dedup intra-fuente | — |
| `prueba_rapida` | Smoke tests | — |
| `config_produccion_it7` (constante) | **Retrocompat** con notebook IT-7 | F1=0.05 (no recomendado) |

`config_produccion_it7` se mantiene por retrocompatibilidad documental.
Tiene parámetros dead/deprecated que el validador reporta.

---

## Ground truth — cómo construir el tuyo

El ground truth (GT) es la única forma honesta de medir si el pipeline funciona
en tus datos. Sin GT, no hay métrica objetiva.

**Notebook de generación de GT:**

> 📓 **[`notebooks/01_construir_ground_truth.ipynb`](notebooks/01_construir_ground_truth.ipynb)**
> (si no existe, ver `docs/PROTOCOLO_GROUND_TRUTH.md` para el procedimiento manual)

**Formato esperado:**

| Columna | Tipo | Descripción |
|---|---|---|
| `ID_REGISTRO` | str | ID único por registro |
| `ID_GROUP` | str | ID del grupo verdad (mismo grupo = misma empresa real) |
| `FUENTE` | str | Nombre de la fuente (RUES, CRM, ...) |
| `RAZON_SOCIAL` | str | Razón social |
| `NIT` | str | NIT (puede estar vacío) |
| `CIUDAD` | str | (opcional) |

GT de ejemplo incluido: `tests/data/ground_truth_grande.csv` (12,427 registros).

---

## Arquitectura

### Componentes principales

```
src/record_linkage/
├── config/            Perfiles, validación de configs, paths
├── processing/        Limpieza de texto, NITs, phonetic keys
├── engine/
│   ├── lsh/          MinHash + LSH (DiskBased, TrustedSource, ...)
│   ├── scorer.py     Scoring de pares candidatos
│   └── clusterer.py  Componentes conexos + split mega-clusters
├── golden/           Selección de representante por cluster
├── pipeline/
│   ├── orchestrator.py    API recomendada (producción)
│   └── linkage_pipeline.py  API alterna (legacy, no usar)
├── evaluation/       Métricas + OrchestratorOptimizer (Optuna)
├── reporting/        Reportes opcionales (extra [viz])
├── deduplication/    Helpers de dedup intra-fuente
└── exporters/        Excel, Parquet, etc.
```

### Flujo del Orchestrator

```
sources (dict)  ──┐
                  ▼
                L1: limpieza (texto, NIT, phonetic keys)
                  │
                L2: bloqueo LSH (genera pares candidatos)
                  │
                L3: scoring (nombre + NIT + filtros previos)
                  │
                L4: clustering (componentes conexos)
                  │
                L5: golden record (selector con pesos de fuente)
                  │
                L6: reporting (opcional, extra [viz])
                  ▼
            {golden, correlative, stats}
```

---

## Historia del proyecto

### Cómo llegamos a 0.6.0

| Fase | Lo que se hizo | Métricas medidas |
|---|---|---|
| **0.1.0** | Refactor notebook → paquete `.py` (mayo 21–23) | — |
| **0.2.0** | Consolidación funcional (mayo 24) | — |
| **0.3.0** ([Fase 1](docs/AUDITORIA_FASE1.md)) | Auditoría dead code: 12 keys ignoradas. Bug NIT vacío. Nuevo perfil `produccion_calibrada` | F1: 0.05 → 0.84 |
| **0.3.1** ([Fase 2](docs/AUDITORIA_FASE2.md)) | `source_quality_weights` numéricos. `max_sources_per_group`. Perfiles auxiliares limpios | F1=0.83 alta_precision |
| **0.3.2** ([Fase 3](docs/AUDITORIA_FASE3.md)) | `OrchestratorOptimizer` conectando Optuna al pipeline real | F1=0.93 con 20 trials |
| **0.4.0** ([Fase 4](docs/AUDITORIA_FASE4.md)) | Fix `_class_exists` (reportes). `min_sources_for_golden`. Deprecation legacy | 380/380 tests |
| **0.5.0** ([Sprint 0.5.0](docs/AUDITORIA_FASE5_SPRINT_0_5_0.md)) | Eliminado `optuna_integration` heredado. `config_produccion_it7` limpio (11 keys removidas) | 380/380 tests |
| **0.6.0** ([Sprint 0.6.0](docs/AUDITORIA_SPRINT_0_6_0.md)) | CI/CD con cobertura (`pytest-cov` 50% mínimo). `mypy` + pre-commit hooks. Badges. | **385/385 tests · 58% cobertura medida** |

### Documentos clave

- **[`CHANGELOG.md`](CHANGELOG.md)** — todas las versiones + tabla de equivalencia retroactiva
- **[`docs/VERSIONING.md`](docs/VERSIONING.md)** — política de versionamiento y roadmap a 1.0
- **[`docs/AUDITORIA_FASE1.md`](docs/AUDITORIA_FASE1.md)** — calibración inicial vs GT
- **[`docs/AUDITORIA_FASE2.md`](docs/AUDITORIA_FASE2.md)** — features de Fase 2
- **[`docs/AUDITORIA_FASE3.md`](docs/AUDITORIA_FASE3.md)** — integración Optuna
- **[`docs/AUDITORIA_FASE4.md`](docs/AUDITORIA_FASE4.md)** — fix bugs + limpieza
- **[`docs/AUDITORIA_FASE5_SPRINT_0_5_0.md`](docs/AUDITORIA_FASE5_SPRINT_0_5_0.md)** — limpieza legacy + IT-7 limpio
- **[`docs/AUDITORIA_SPRINT_0_6_0.md`](docs/AUDITORIA_SPRINT_0_6_0.md)** — CI/CD + cobertura + mypy
- **[`docs/PROTOCOLO_GROUND_TRUTH.md`](docs/PROTOCOLO_GROUND_TRUTH.md)** — cómo construir el GT
- **[`docs/ROADMAP_PRODUCCION.md`](docs/ROADMAP_PRODUCCION.md)** — pendientes para producción
- **[`MIGRATION_LOG.md`](MIGRATION_LOG.md)** — decisiones de migración notebook → paquete

---

## Credenciales

Nunca van en el código. Tres opciones (en orden de prioridad):

1. **Colab Secrets** (recomendado en Colab): `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`,
   `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`,
   `SNOWFLAKE_ROLE`. Acceder con `userdata.get('SNOWFLAKE_USER')`.
2. **Variables de entorno** (local): `export SNOWFLAKE_USER=...`
3. **`.env` file** en `~/.config/rues-linker/credentials.env` (no commitear)

El paquete las carga automáticamente con `get_snowflake_credentials()`.

---

## Calidad de código

| Aspecto | Estado | Target |
|---|---|---|
| Tests | ✅ 506/506 pasan | mantener |
| **Cobertura** | ✅ **58%** (medida 2026-05-26) | 80% (antes de 1.0) |
| **CI/CD** | ✅ GitHub Actions (lint + test + typecheck + build) | mantener |
| Ruff | ✅ Sin errores | mantener |
| Format | ✅ Consistente (`ruff format`) | mantener |
| **mypy** | ⚠️ Configurado (no bloquea CI por deuda heredada) | strict en 0.9.0 |
| **Pre-commit** | ✅ Configurado (ruff + mypy + higiene) | mantener |
| Badge cobertura | ✅ En README | upload a Codecov pendiente (requiere `CODECOV_TOKEN`) |

Correr tests:

```bash
# Tests sin cobertura (rápido)
pytest tests/

# Tests con cobertura local
pytest tests/ --cov=record_linkage --cov-report=html
# Abre htmlcov/index.html para ver detalle

# Subset de tests por fase
pytest tests/test_fase4_*.py -v
pytest tests/ -k "not slow"

# Lint y format
ruff check src/ tests/ scripts/
ruff format --check src/ tests/ scripts/

# Type check
mypy --config-file=pyproject.toml src/record_linkage/

# Pre-commit (instalar una vez por clon)
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

### Workflows de CI activos

| Workflow | Trigger | Qué hace |
|---|---|---|
| `.github/workflows/ci.yml` | Push y PR a main/master/develop | Lint, typecheck, test matriz Python 3.10/3.11/3.12, build sdist+wheel |
| `.github/workflows/publish.yml` | Release publicada (manual o tag) | Publica a TestPyPI o PyPI (trusted publishing OIDC) |

---

## Roadmap hacia 1.0

Ver [`docs/VERSIONING.md`](docs/VERSIONING.md) para detalle. Resumen:

```
0.5.0  Limpiar código legacy (eliminar optuna_integration heredado)
0.6.0  GitHub Actions + cobertura medida
0.7.0  Validación contra producción real (1.97M registros)
0.8.0  Optimización rendimiento (pre-screening LSH)
0.9.0  Feature freeze + docs completas + API reference
1.0.0  PUBLICAR EN PyPI con API congelada
```

---

## Notebooks de ejemplo

| Notebook | Propósito |
|---|---|
| `notebooks/01_construir_ground_truth.ipynb` | Construir GT desde fuentes reales (si existe) |
| `notebooks/02_corrida_basica.ipynb` | Pipeline básico end-to-end (si existe) |
| `notebooks/03_calibracion_manual.ipynb` | Calibración manual con grid search (si existe) |
| **[`notebooks/04_optuna_calibration.ipynb`](notebooks/04_optuna_calibration.ipynb)** | **Calibración automática con Optuna** ⭐ |

---

## Licencia

Apache-2.0. Ver [`LICENSE`](LICENSE).

---

## Reportar problemas

- 🐛 Bug → abrir issue en GitHub con: versión, comando reproducible, traceback
- 🆕 Feature request → discutir antes de PR (estamos en 0.x, la API cambia)
- ❓ Pregunta de uso → revisar `docs/` primero, luego abrir discussion

---

> **Construido con disciplina forense:** cada fase tiene su `docs/AUDITORIA_FASE*.md`
> con metodología, métricas y limitaciones documentadas. La transparencia sobre
> lo que NO funciona es tan importante como mostrar lo que sí.
