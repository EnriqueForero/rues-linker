# Política de versionamiento — `rues-linker`

**Última actualización:** 2026-05-26 · **Versión actual:** `0.4.0`

---

## Estándar adoptado

Este paquete sigue [**Semantic Versioning 2.0.0**](https://semver.org/spec/v2.0.0.html):

```
MAJOR.MINOR.PATCH[-PRERELEASE]
```

- **MAJOR** (`X.0.0`): cambios incompatibles en la API pública
- **MINOR** (`0.Y.0`): funcionalidad nueva compatible
- **PATCH** (`0.0.Z`): bug fixes compatibles
- **PRERELEASE** (`-alpha.1`, `-rc.1`, ...): versiones de preparación

### Reglas especiales para `0.x` (pre-1.0)

Mientras la versión sea `0.Y.Z`:

- **`0.Y.0`** puede contener breaking changes (no se requiere bump MAJOR)
- **`0.Y.Z`** debe ser compatible con `0.Y.0`
- La API NO está congelada hasta llegar a `1.0.0`

Esto es **convención estándar** de la comunidad Python (`scikit-learn`,
`pandas`, `requests`, `numpy` operaron así por años antes de su 1.0).

---

## Estado actual: 0.4.0 — pre-1.0

### Por qué somos pre-1.0

| Indicador | Estado |
|---|---|
| ¿Publicado en PyPI? | ❌ No |
| ¿CI/CD configurado? | ❌ No |
| ¿Cobertura de tests medida? | ❌ No |
| ¿API congelada (estable)? | ❌ Aún cambiando (`HyperparameterOptimizer` → `OrchestratorOptimizer`) |
| ¿Validado contra producción real (1.97M registros)? | ❌ Solo GT (12k) |
| ¿Migration guide para usuarios externos? | ❌ No |
| ¿Código legacy eliminado? | ❌ `optuna_integration.py` aún presente (deprecated) |

**Hasta que todos los anteriores sean ✅, la versión correcta es 0.x.**

---

## Roadmap hacia 1.0.0

Ordenado por prioridad. Cada minor release agrupa un sprint completo.

### 0.5.0 — Limpieza de legacy (✅ COMPLETADO 2026-05-26)

- [x] Eliminar `src/record_linkage/optimization/optuna_integration.py`
- [x] Eliminar `src/record_linkage/optimization/visualizer.py` (huérfano)
- [x] **NO eliminar** `src/record_linkage/pipeline/linkage_pipeline.py`
      (decisión revisada: es dependencia interna del Orchestrator)
- [x] Eliminar `cross_source_validation` de `config_produccion_it7`
- [x] Eliminar 10 claves dead remanentes de `config_produccion_it7`
- [x] Documentar breaking changes en CHANGELOG con guía de migración
- [x] 380/380 tests pasan

Ver `docs/AUDITORIA_FASE5_SPRINT_0_5_0.md`.

### 0.6.0 — CI/CD y cobertura (✅ COMPLETADO 2026-05-26)

- [x] GitHub Actions: workflow CI ya existía con matriz Python 3.10/3.11/3.12
- [x] Extender CI con `pytest-cov` y reporte XML + term
- [x] `--cov-fail-under=50` (target inicial, sube progresivamente a 80 antes de 1.0)
- [x] Job `typecheck` con mypy (`continue-on-error: true` por deuda heredada)
- [x] Upload opcional a Codecov si hay token
- [x] `[tool.coverage]` y `[tool.mypy]` configurados en pyproject
- [x] Pre-commit hook de mypy añadido
- [x] Badges en README (CI, cobertura, tests)
- [x] **385/385 tests pasan · cobertura medida 58%**

Ver `docs/AUDITORIA_SPRINT_0_6_0.md`.

### 0.7.0 — Validación en producción real (✅ COMPLETADO 2026-05-27)

- [x] Correr `produccion_calibrada` contra las 4 fuentes reales (1,965,732 registros)
- [x] Documentar métricas reales (`baseline_metrics.json` en cada corrida)
- [x] Notebook v1.0 con análisis estructurado (`BaselineMetrics`, comparativa IT-7)
- [x] Sample QA de 50 clusters estratificados (notebook v1.0 + v1.1)
- [x] Hallazgos del first-run documentados
- [x] Notebook v1.1 con ajustes post-run: `fail_under_reduccion=0.0` (sin threshold)

**Resultados medidos:**
- Tiempo total: 52m 44s sobre 1.97M registros
- Golden: 1,927,187 (reducción 1.96%)
- L2_lsh = 70% del tiempo (cuello de botella identificado)
- Bases ya pre-deduplicadas oficialmente (RUES por NIT)

**Pendiente para 0.9.0+:**
- [ ] Refactorizar `scorer.py` para mover prints DEBUG `AUDITANDO PAR` detrás de flag
- [ ] Investigar comillas literales en RAZON_SOCIAL (`''DISENITOS S S ''`)

### 0.8.0 — Optimización de rendimiento (✅ COMPLETADO 2026-05-27, parcial)

- [x] Pre-screening LSH (`NITPrescreener` en `engine/lsh/prescreen.py`)
- [x] Benchmarks reproducibles (`benchmarks/benchmark_lsh_prescreen.py`)
- [ ] Profiling con `py-spy` (pendiente, no crítico)

**Resultados HONESTOS:**
- Speedup medido: **1.21× a 1.40×** (no 2-3× como prometía el plan)
- Para casos de producción con bases pre-dedupadas (~2% overlap):
  speedup esperado marginal (~5%)
- Valor REAL del componente: captura garantizada de NIT-exactos que el
  LSH puro descarta por threshold de similitud baja

**Recomendación:** NO integrar al Orchestrator todavía. Ver `docs/AUDITORIA_SPRINT_0_8_0.md`.

### 0.8.1 — Mejoras de calidad pendientes (sugerencias post first-run)

Sub-sprint identificado por análisis del first-run:

- [ ] Mover prints DEBUG `AUDITANDO PAR` del `scorer.py` detrás de flag de configuración
- [ ] Validar comillas literales en RAZON_SOCIAL durante L1_prep
- [ ] Hacer `skip_reporting=True` configurable desde top-level (no L6)
- [ ] Cache de firmas MinHash entre corridas (re-uso si el dataset no cambia)

### 0.8.2 — Optimización rendimiento real (basada en datos del first-run)

| Fase | Tiempo en first-run | % | Optimización propuesta |
|---|---:|---:|---|
| L1_prep | 3m 23s | 6% | Carga paralela de fuentes |
| **L2_lsh** | **36m 56s** | **70%** | **Paralelizar bandas + cache firmas** |
| L5_golden | 6m 37s | 13% | TextProcessor más rápido |
| L6_reporting | 4m 37s | 9% | Hacer opcional + lazy |

### 0.9.0 — Feature freeze + docs (~1 semana)

- [ ] Migration guide v0.x → v1.0
- [ ] Sección "Cuándo NO usar cada perfil"
- [ ] API reference completa generada (Sphinx o MkDocs)
- [ ] Guía de calibración exhaustiva
- [ ] Ejemplo end-to-end documentado con datos sintéticos

### 1.0.0 — Primera release pública (~1 semana extra)

- [ ] API congelada
- [ ] **Publicación en PyPI**
- [ ] Comunicación al equipo + usuarios
- [ ] Tag `v1.0.0` en GitHub con release notes completas
- [ ] Anuncio en README

---

## Reglas para nuevas releases

### Cuándo bumpear MAJOR (`0.X.0` → `1.0.0`, después `1.X.0` → `2.0.0`)

Eliminación, renombrado o cambio incompatible de:
- Una clase pública (ej. `Orchestrator`)
- Una firma de método pública (ej. `Orchestrator.run()`)
- Un perfil documentado (ej. `produccion_calibrada`)
- Un comportamiento por default (ej. cambiar `score_threshold` default)

### Cuándo bumpear MINOR (`0.4.0` → `0.5.0`)

- Nueva funcionalidad (nuevo método, nueva clase, nuevo perfil)
- Nuevo parámetro opcional en API existente (default preservando compat)
- Mientras estemos en 0.x: también breaking changes con aviso en CHANGELOG

### Cuándo bumpear PATCH (`0.4.0` → `0.4.1`)

- Bug fix puro (no añade ni quita features)
- Documentación, comentarios, refactor interno sin cambio observable
- Performance improvement sin cambio de API

### Frecuencia recomendada

- PATCH: cuando haya un bug que afecte a usuarios
- MINOR: al cerrar un sprint completo (cada 1-2 semanas)
- MAJOR: solo al saltar a 1.0, luego solo cada varios meses

---

## Cómo declarar breaking changes (mientras estemos en 0.x)

Cada minor en 0.x **puede** contener breaking changes. Debe documentarse así:

```markdown
## [0.5.0] — fecha — Limpieza de legacy

### ⚠️ BREAKING CHANGES
- Eliminado `record_linkage.optimization.optuna_integration` (deprecated desde 0.4.0).
  Migración: usar `record_linkage.evaluation.OrchestratorOptimizer`.
- `config_produccion_it7` ya no incluye `cross_source_validation`.
  Si tu código accede a esa clave: actualizar.
```

Los usuarios que pineen `rues-linker>=0.5.0` saben que pueden recibir
breaking changes desde minor releases. Es el contrato de 0.x.

---

## Re-versionamiento de 2026-05-26: contexto histórico

El paquete venía de un experimento Jupyter (`v1.x` notebook monolítico)
que se refactorizó a paquete `.py` en v2.0.0 (2026-05-21). En 5 días pasaron
por 19 versiones (v2.0.0 → v3.2.7) sin convención clara: a veces minor
para bug fixes, a veces patch para features. Cuando se llegó a v3.2.7
se decidió **resetear honestamente** a `0.4.0`, reflejando que el paquete:

1. Aún no está en PyPI
2. Tuvo refactores profundos (auditoría completa en 4 fases)
3. Tiene código legacy aún presente
4. No tiene CI/CD ni cobertura medida
5. No ha sido validado contra producción real

El reset es honesto, no vergonzoso. `requests`, `scikit-learn`, `pandas`
empezaron en 0.x y se quedaron ahí años antes de su 1.0.

Tabla de equivalencia retroactiva está en `CHANGELOG.md`.

---

## Referencias

- [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html)
- [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
- [PEP 440 — Version Identification](https://peps.python.org/pep-0440/)
- [Python Packaging Guide — Single-source the version](https://packaging.python.org/guides/single-sourcing-package-version/)
