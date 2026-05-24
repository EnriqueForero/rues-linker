# rues-linker

> **Pipeline de deduplicación y record linkage para fuentes empresariales colombianas**
> (RUES, DIAN, CRM, SUPERSOCIEDADES). Refactor estructurado del notebook
> `2026_02_15_DEDUPLICAR_Y_RECORD_LINKAGE_.ipynb` a paquete `.py` publicable en PyPI.

[![CI](https://github.com/USER/rues-linker/actions/workflows/ci.yml/badge.svg)](https://github.com/USER/rues-linker/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-261230)](https://docs.astral.sh/ruff/)

**Autor:** Enrique Forero · **Versión:** 3.0.0 · **Python:** ≥ 3.10 · **Licencia:** Apache-2.0

> 📍 **Estado del proyecto (2026-05-23):** v3.0.0 unifica la API de alto nivel
> (`linkage()`), pone el motor en disco por defecto, y limpia las dependencias.
> Ver `docs/ROADMAP_PRODUCCION.md` para el estado de cierre y lo que falta
> (medición sobre datos reales del RUES).

---

## ¿Qué hace este paquete?

A partir de varias fuentes con razones sociales y NITs que se superponen
(RUES, DIAN, CRM, SUPERSOCIEDADES, EXPORTACIONES), construye un **registro
único por empresa real** (golden record) usando:

1. Limpieza vectorizada de texto y NITs (`processing/`)
2. Bloqueo LSH con MinHash sobre n-gramas (`engine/lsh/`)
3. Scoring de pares candidatos (similitud de nombre + NIT + fonética)
4. Clustering de entidades por componentes conexos
5. Generación del golden record por reglas de prioridad de fuente
6. Reporteo, dashboards y métricas de calidad

> ⚠️ **Escala probada empíricamente: hasta ~37k registros.** El diseño está
> pensado para 2M+ (motor en disco), pero el rendimiento por encima de 37k aún
> no se ha medido. Ver "Calidad y escala medidas" más abajo.

---

## Inicio rápido

La API recomendada es el helper `linkage()`: una sola función, motor en disco,
multi-fuente y multi-variable.

```python
import pandas as pd
from record_linkage import linkage

# Caso 1 — Una sola fuente (deduplicación interna)
df = pd.read_csv("rues.csv", dtype=str)
result = linkage(sources={"RUES": df}, work_dir="/data/run_dedup")
result["golden"].to_parquet("golden.parquet")        # 1 fila por empresa
result["correlative"].to_parquet("correlativa.parquet")  # original → ID_GRUPO

# Caso 2 — Varias fuentes, una confiable (producción)
result = linkage(
    sources={
        "RUES": pd.read_csv("rues.csv", dtype=str),
        "DIAN": pd.read_csv("dian.csv", dtype=str),
        "CRM":  pd.read_csv("crm.csv", dtype=str),
    },
    trusted_sources={"RUES"},          # fuente con NIT verificado
    col_ciudad="CIUDAD",
    extra_features=["TELEFONO", "EMAIL"],
    work_dir="/data/run_produccion",
)

# Caso 3 — Fuente sin NIT (importaciones tipo Corea)
result = linkage(
    sources={"IMPORTACIONES": df_corea},
    profile="deduplication_sin_nit_conservador",  # techo de F1 conocido (~0.55)
    col_ciudad="CIUDAD",
    work_dir="/data/run_corea",
)
```

### Cuándo usar cada API

| Escenario | API | Razón |
|---|---|---|
| 1 fuente, todos con NIT | `linkage()` | Caso simple, F1 ≈ 0.96 (GT sintético) |
| 1 fuente, sin NIT | `linkage(profile="deduplication_sin_nit_conservador")` | Techo conocido F1 ≈ 0.55 |
| ≥2 fuentes, mezcla con/sin NIT | `linkage(trusted_sources={...})` | Único modo que separa regímenes (F1 ≈ 0.875 vs 0.563) |

> ⚠️ **No uses `deduplicate_unified` directamente sobre datasets que mezclan
> fuentes con y sin NIT.** Colapsa a F1 ≈ 0.563. Usa `linkage()` con
> `trusted_sources`, que internamente usa el `Orchestrator` (F1 ≈ 0.875).

---

## Instalación

```bash
# Núcleo (deduplicación + linkage, sin reportes gráficos) — instalación liviana
pip install rues-linker

# Con visualización y dashboards
pip install "rues-linker[viz]"

# Con optimización de hiperparámetros (Optuna)
pip install "rues-linker[optimization]"

# Todo
pip install "rues-linker[all]"

# Desarrollo (incluye tests + viz + optuna)
git clone https://github.com/USER/rues-linker.git
cd rues-linker
pip install -e ".[dev]"

# Con conector Snowflake
pip install "rues-linker[snowflake]"
```

### En Google Colab

```python
!pip install -q rues-linker
# o desde repo: !pip install -q -e /content/drive/MyDrive/rues-linker
```

---

## Uso rápido

### En notebook de Colab (recomendado)

Abre `notebooks/ejecutar.ipynb` y ejecuta la celda EJECUTAR. Es ≤15 líneas.

### En script CLI

```bash
python scripts/ejecutar_produccion.py \
    --workspace /content/drive/MyDrive/rues-linker \
    --iteracion IT8_PROD \
    --trusted RUES SUPERSOCIEDADES
```

### Programáticamente

```python
from record_linkage.config import Config, Rutas
from record_linkage.config.profiles import config_produccion_it7
from record_linkage.pipeline.orchestrator import Orchestrator

cfg = Config(
    workspace="/data/rl",
    iteracion="IT8_PROD",
    trusted_sources={"RUES", "SUPERSOCIEDADES"},
)
rutas = Rutas.desde_config(cfg)
rutas.crear_directorios()

# fuentes = {"RUES": df_rues, "DIAN": df_dian, ...}
orch = Orchestrator(
    config=config_produccion_it7,
    sources=fuentes,
    work_dir=str(rutas.base),
)
resultado = orch.run()
golden = resultado["golden"]
correlativa = resultado["correlative"]
```

**No requiere monkey-patching.** El `Orchestrator._run_L2` ya es nativo —
selecciona automáticamente `DiskBasedLSHEngine` o `TrustedSourceLSHEngine`
según `trusted_unique_sources` en el perfil.

---

## Credenciales

Nunca van en el código. Tres opciones (en orden de prioridad):

1. **Colab Secrets** (recomendado en Colab): `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`,
   `SNOWFLAKE_PASSWORD`, `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_DATABASE`, `SNOWFLAKE_SCHEMA`,
   `SNOWFLAKE_ROLE` (opcional).
2. **Variables de entorno** (recomendado para CI/CD): mismos nombres.
3. **`config.json` local** (último recurso, está en `.gitignore`).

```python
from record_linkage.config import get_snowflake_credentials
creds = get_snowflake_credentials()
import snowflake.connector
conn = snowflake.connector.connect(**creds.to_connector_kwargs())
```

Ver `docs/secrets.md` para detalles completos.

---

## Estructura del proyecto

```
rues-linker/
├── pyproject.toml              ← Dependencias, ruff, pytest
├── README.md                   ← Este archivo
├── CHANGELOG.md                ← Historial de cambios
├── MIGRATION_LOG.md            ← Auditoría forense del refactor desde el notebook
├── docs/
│   └── secrets.md              ← Guía de configuración de credenciales
├── .github/workflows/
│   ├── ci.yml                  ← Ruff + pytest en 3 versiones de Python
│   └── publish.yml             ← Publicación a PyPI/TestPyPI con OIDC
├── data/                       ← Datos (no versionados)
├── notebooks/
│   └── ejecutar.ipynb          ← Notebook de ejecución de 2 celdas
├── scripts/
│   └── ejecutar_produccion.py  ← CLI de producción (4 fuentes)
├── tests/
│   ├── test_smoke.py                       ← 27 tests estructurales
│   └── test_vectorization_equivalence.py   ← 17 tests de equivalencia .apply → vectorizado
└── src/record_linkage/
    ├── config/         ← Config, Rutas, credentials, perfiles
    ├── utils/          ← Timer, memoria, logger, performance
    ├── classifier/     ← Clasificador híbrido
    ├── processing/     ← Text/NIT cleaning
    ├── engine/         ← Motor de linkage
    │   └── lsh/        ← DiskBased + TrustedSource (producción)
    ├── golden/         ← Generación de golden records
    ├── evaluation/     ← Ground truth + métricas
    ├── reporting/      ← Reportes, dashboards
    ├── pipeline/       ← Orchestrator
    ├── deduplication/  ← Modo dedup
    ├── optimization/   ← Optuna
    └── exporters/      ← SmartExporter
```

---

## Calidad de código

| Estándar | Estado |
|---|---|
| `ruff check` (E, F, W, I, B, UP, RUF, SIM) | ✅ Verde (verificado v2.6.0) |
| `ruff format --check` | ✅ Verde |
| `pytest tests/` | ✅ 231/231 pasan (~85 s) |
| `python -m compileall` | ✅ OK |
| Import de todos los submódulos | ✅ |
| PEP 8 + PEP 257 + PEP 484 (type hints) | ✅ |
| Pathlib (cero `os.path.join`) | ✅ |
| Sin monkey-patching | ✅ (eliminado en v2.0.0) |
| Sin credenciales hardcoded | ✅ (Colab Secrets) |
| **Cobertura de tests** | ⚠️ **~38 %** — smoke alto, lógica de negocio media |
| **Calidad de linkage (F1 pairwise)** | **0.76** golden 269 · **0.87** exhaustivo · **0.934** exhaustivo + CIUDAD (medido v2.11.0) |
| **Velocidad del scorer (v2.9.0)** | **~4.8×** vs v2.8.0 a partir de 10k pares (medido) |

### Calidad de linkage — cifras medidas en v2.11.0 (motor in-memory)

| Dataset | F1 | Precision | Recall |
|---|---|---|---|
| Golden 269 | 0.759 | 0.802 | 0.720 |
| Exhaustivo 1456 | 0.867 | 0.886 | 0.849 |
| **Exhaustivo + CIUDAD** | **0.934** | **0.963** | **0.907** |
| Sintético robusto 660 | 0.935 | 0.936 | 0.934 |

**La ciudad es la palanca de mayor impacto: +0.067 de F1** sobre el
exhaustivo. Para fuentes SIN NIT, usar el perfil
`deduplication_sin_nit_conservador` (ver `notebooks/produccion_4fuentes.ipynb`);
en ese régimen no hay F1 medido — el sistema sobre-fusiona y se prioriza
precisión sobre recall.

> ⚠️ **Todas estas cifras son sobre datasets ≤ 1456 registros.** No hay
> medición a escala de producción (2–4 M) contra ground truth real. Ver
> "Pendientes" en `CHANGELOG.md`.

#### Histórico por versión (referencia)

| Métrica | v2.7.0 | v2.8.0 | v2.9.0 | v2.10.0 | **v2.11.0** |
|---|---|---|---|---|---|
| F1 (269) | 0.77 | 0.76 | 0.76 | 0.759 | **0.759** |
| F1 (exhaustivo 1456) | 0.86 | 0.87 | 0.87 | 0.867 | **0.867** |
| F1 (exhaustivo + CIUDAD) | 0.90* | — | — | — | **0.934** |

\* La cifra 0.90 de v2.7.0 se midió con un método distinto; 0.934 es la
medición directa actual con `evaluar_pares` sobre el mismo dataset.

**Lectura honesta de v2.9.0.** Esta versión NO mueve las métricas de
calidad — solo la velocidad. La vectorización del scorer (Paso P1-1 del
ROADMAP) reemplaza loops por llamadas batch a `rapidfuzz.process.cpdist`.
El speedup escala con el tamaño: **1.9× a 500 pares, 4.8× a 30k**. En
producción (millones de pares) se espera que ronde 5×. Paridad bit-a-bit
verificada con un oráculo de 360 outputs (`tests/test_paridad_p1_1.py`).

Detalle técnico del oráculo y del bug atrapado (Levenshtein vs Indel)
en `MIGRATION_LOG.md` §19.

### Rendimiento del motor LSH (v2.3.0)

`DiskBasedLSHEngine` se reescribió en v2.3.0. La generación de firmas MinHash
pasó de un objeto por registro a cálculo vectorizado con NumPy:

| Fase (20k registros RUES) | v2.2.0 | v2.3.0 |
|---|---|---|
| Firmas MinHash | 20.0 s | **1.2 s** (17×) |
| Motor completo | 32.8 s | **15.6 s** (2.1×) |

Además se corrigió un bug latente: el índice usaba `hash()` de Python
(randomizado por proceso), que corrompía los buckets al reanudar desde
checkpoint tras un reinicio de Colab. Ahora el pipeline LSH es determinista.
Detalle en `MIGRATION_LOG.md` §13.

Las reglas de estilo silenciadas para código heredado del notebook están
documentadas explícitamente en `pyproject.toml` bajo `per-file-ignores`,
con justificación en `MIGRATION_LOG.md` sección 9.

---

## Tests

```bash
# Todos (89 tests, ~32 s)
pytest tests/ -v

# Solo smoke (no requiere deps externas pesadas)
pytest tests/test_smoke.py -v

# Solo equivalencia de vectorizaciones
pytest tests/test_vectorization_equivalence.py -v

# Calidad de linkage contra ground truth (Validation Level 3) — NUEVO v2.2.0
pytest tests/test_quality_golden.py -v -s
```

Los **tests de equivalencia** garantizan que cada `.apply` vectorizado produce
resultados numéricamente idénticos al `.apply` original.

El **test de calidad** (`test_quality_golden.py`) corre el pipeline completo
sobre 269 registros reales y verifica que F1/precision/recall no retroceden
respecto al piso de v2.2.0. Es la única prueba que mide si el sistema
**agrupa bien**, no solo si **corre**.

---

## Trazabilidad

Cada clase y función del paquete documenta su celda de origen en el
notebook fuente. Ver `MIGRATION_LOG.md` para:
- Qué se incluyó / qué se excluyó
- Resolución de duplicados (AdvancedValueSelector, MemoryMonitor, SafeSQLiteConnection)
- Decisión del motor LSH de producción
- Lista exacta de celdas experimentales descartadas
- Vectorizaciones aplicadas con prueba de equivalencia

---

## Plan futuro

Ver `CHANGELOG.md` (sección "Próximos pasos") para el roadmap completo.

Lo más relevante:
- Tests unitarios de lógica de negocio (no solo smoke)
- Eliminar `_run_L2_legacy` tras 2 corridas exitosas
- Migración a Snowflake nativo
- Sphinx + Read the Docs

---

## Licencia

Propietario. Reutilización con autorización del autor.
