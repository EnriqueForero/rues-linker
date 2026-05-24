# ROADMAP a producción — rues-linker

> **Documento de orientación único y final**
> **Versión base:** v2.14.0 (auditada 2026-05-23)
> **Versión actual:** v3.0.0 (Fase 2 + parte de H1/H4 ya integradas)
> **Versión objetivo:** v3.0.0 apto producción (falta solo H3 — medición real)
> **Autor de la auditoría:** Claude (consultor escéptico externo)
> **Convención:** todo lo marcado **P0** es bloqueante; **P1** importante; **P2** deseable.

Este documento sustituye y consolida los TODOs dispersos en `CHANGELOG.md`,
`MIGRATION_LOG.md`, y los `🚧` del notebook original. Cuando esté completado al
100%, el proyecto cierra.

**Principio rector:** *cerrar el ciclo, no perfeccionarlo eternamente*. Si una
sección dice "como está, está bien", se respeta tal cual.

---

## ESTADO ACTUALIZADO v3.0.0 (integración de avances) — léase primero

Esta sección integra lo realmente hecho en v3.0.0 sobre el plan original. Es la
foto vigente; las secciones siguientes (hitos H1-H5) son el detalle de cada punto.

### ✅ Ya hecho y verificado en v3.0.0

| Punto del plan | Estado | Evidencia |
|---|---|---|
| **H1.1** Sincronizar versiones | ✅ | pyproject, `__init__`, README → 3.0.0 |
| **H1.4** Warning en `deduplicate_unified` | ✅ | docstring con la advertencia y los F1 (0.563 vs 0.875) |
| **H2** Tests path SQLite del clusterer | ✅ | `test_clusterer_disk_based.py` (18 tests) |
| **H4.3.1** Default a disco | ✅ | `_should_use_disk_processing`: disco por defecto, override por env var, memoria solo en cargas triviales (<5k) |
| **H4.3.4** API unificada `linkage()` | ✅ | `record_linkage.linkage()`, un solo punto de entrada, 4 tests |
| **H4.3.5** Multi-variable + multi-fuente en API alto nivel | ✅ | `linkage(extra_features=[...], trusted_sources={...})` |
| **Fase 2** API pública exportada | ✅ | `__all__` expone `linkage`, `Orchestrator`, `deduplicate_unified`, `evaluar_pares` |
| **Fase 2** Dependencias muertas | ✅ | `fuzzywuzzy` eliminado; `python-Levenshtein` migrado a `rapidfuzz` (bit-a-bit idéntico, 20k pares verificados) |
| **Fase 2** Viz/Optuna como extras opcionales | ✅ | core instala liviano; `[viz]`, `[optimization]`, `[all]`; imports defensivos |
| **Licencia** Apache-2.0 | ✅ | `License-Expression: Apache-2.0` en el wheel; twine PASSED |
| Suite de tests | ✅ | 257 verde (era 236) |

### ⬜ Pendiente — en orden de prioridad real

| Prioridad | Punto | Por qué importa | Bloquea release |
|---|---|---|---|
| **🔴 P0 #1** | **H3 — Medición sobre datos REALES del RUES** | Todo el F1 actual es sobre GT sintético. Sin esto, "F1=0.96" es un decimal con falsa precisión. **Es el único bloqueante real.** | **Sí** |
| 🟡 P1 #2 | H1.5 — Limpiar `except:` desnudos (11 sitios) | Robustez; oculta errores reales en producción | No |
| 🟡 P1 #3 | H2.3 — Cobertura `trusted.py` 21%→70% | El path 4-fuentes trusted no está bien testeado | No |
| 🟡 P1 #4 | H4.3.2/3 — Deprecar LSH legacy + quitar monkey-patching | Reduce superficie de mantenimiento | No |
| 🟢 P2 #5 | H1.2/H1.3 — README métricas + MIGRATION_LOG §1 | Honestidad documental | No |
| 🟢 P2 #6 | H5 — Optuna sobre GT real | Solo si H3 da F1 < 0.90 | No |
| 🟢 P2 #7 | Cobertura global 40%→60% | Calidad | No |

### 🎯 Lo único que falta para cerrar: H3

**El proyecto está listo en todo menos en la medición real.** La librería ya es
usable, está limpia, empaquetable y con API clara. El paso que convierte esto en
"producción defendible" es **medir el F1 sobre una muestra etiquetada del RUES
real** (Hito H3). Es trabajo humano (etiquetado), no de código. Hasta entonces,
los números publicados deben decir explícitamente "sobre ground truth sintético".

---

## 0. Resumen ejecutivo de la auditoría

| Dimensión | Estado actual | Veredicto |
|---|---|---|
| Reproducibilidad de métricas declaradas | F1=0.961 CON_NIT, F1=0.549 SIN_NIT verificado bit-exact | ✅ Defendible |
| Determinismo (same input → same output) | Verificado bit-a-bit | ✅ Excelente |
| Empaquetado PyPI (`python -m build` + `twine check`) | Wheel + sdist limpios | ✅ Apto para PyPI público |
| Linting (`ruff check` + `ruff format`) | 119 archivos OK, cero violaciones | ✅ Excelente |
| Suite de tests | 236 OK en ~80s | ✅ Cantidad OK, calidad mixta |
| Cobertura medida | **40%** (no 38% como dice el README) | ⚠️ Gaps críticos en clusterer y trusted LSH |
| Calidad de linkage con NIT (escala 12k) | F1=0.961 sobre GT sintético | ✅ Bueno (pendiente GT real) |
| Calidad de linkage sin NIT (escala 12k) | F1=0.549 (techo conocido) | ⚠️ Limitación estructural |
| Escala probada | **Hasta 37k registros**. Más arriba: no medido. | 🔴 **El gap más grande** |
| Documentación | Excepcional (MIGRATION_LOG 1.569 líneas, CHANGELOG 1.514) | ✅ Por encima del estándar |

**Bloqueante real: ninguna métrica fue medida sobre datos REALES del RUES con
etiquetas humanas, en ninguna escala. Todo lo demás es secundario.**

---

## 1. Estructura del trabajo restante

El roadmap está organizado en **5 hitos**. Cada hito debe completarse antes del siguiente.

| Hito | Objetivo | Esfuerzo | Estado |
|---|---|---:|---|
| **H1** | Cerrar inconsistencias documentales y "pulir el merengue" | 0.5 día | □ |
| **H2** | Añadir tests faltantes para path SQLite del clusterer | 2 días | □ |
| **H3** | **MEDICIÓN REAL** sobre muestra ≥50k registros del RUES con GT etiquetado | 3-5 días | □ |
| **H4** | Migración a modo "siempre en disco" (unificar API) | 5 días | □ |
| **H5** | Integración Optuna ↔ ground truth real (parámetros calibrados) | 3 días | □ |

**Total: ~16 días persona** desde v2.14.0 hasta v3.0.0 apto producción.

---

## 2. HITO H1 — Pulir el merengue (0.5 día)

### H1.1 Sincronizar versiones [P0 · 10 minutos]

**Problema detectado en auditoría:** tres versiones distintas declaradas:

| Archivo | Línea | Dice | Debe decir |
|---|---|---|---|
| `README.md` | 11 | `Versión: 2.12.0` | `Versión: 2.15.0` |
| `src/record_linkage/__init__.py` | 21 (docstring) | `Versión: 2.0.0` | (eliminar línea o actualizar) |
| `pyproject.toml` | 7 | `version = "2.14.0"` | `version = "2.15.0"` |

**Comando de verificación:**
```bash
grep -rn "2\.0\.0\|2\.12\.0\|2\.14\.0" README.md pyproject.toml src/record_linkage/__init__.py
```

### H1.2 Actualizar README con métricas reales medidas en v2.14.0 [P0 · 30 minutos]

**Problema:** la tabla histórica del README llega solo a v2.11.0; v2.14.0 publicó
el ground truth grande pero no actualizó la tabla.

Reemplazar la sección "### Calidad de linkage — cifras medidas en v2.11.0
(motor in-memory)" con la sección 7 de este documento.

### H1.3 Corregir el §1 del MIGRATION_LOG [P0 · 15 minutos]

**Problema:** el §1 afirma "ningún algoritmo se modernizó". La realidad es que
sí hay **5 cambios algorítmicos declarados y testeados**:

1. Vectorización del scorer (v2.9.0, §19 del MIGRATION_LOG)
2. Union-Find del clusterer → `scipy.sparse.csgraph.connected_components` (v2.2.0)
3. Desempate determinista en `AdvancedValueSelector` (v2.4.0)
4. Hash determinista en LSH (v2.3.0)
5. Contrato lazy de `PipelineResult` (v2.1.0)

**Acción:** reescribir el §1 reconociendo estas 5 excepciones y enlazando a las
secciones del MIGRATION_LOG donde están documentadas. Mejor decirlo honesto que
arriesgar a que el siguiente auditor lo encuentre.

### H1.4 Documentar warning sobre `deduplicate_unified` [P0 CRÍTICO · 30 minutos]

**Hallazgo de auditoría:** sobre el GT grande (12.427 registros) con CON_NIT +
SIN_NIT mezclados:

| Modo de uso | F1 |
|---|---:|
| `deduplicate_unified` (perfil estándar, dataset combinado) | **0.563** |
| `Orchestrator` multi-fuente + `trusted_sources={RUES, SUPERSOCIEDADES}` | **0.875** |

**Diferencia: 31 puntos porcentuales.** No hay nada en la documentación que
avise al usuario que usar `deduplicate_unified` sobre un dataset multi-fuente
mezclando regímenes CON_NIT/SIN_NIT es una mala práctica.

**Acción 1 — README:** añadir tabla de decisión:

```markdown
## Cuándo usar cada API

| Escenario | API | Razón |
|---|---|---|
| 1 sola fuente, todos con NIT | `deduplicate_unified` | Caso simple, F1 ~0.96 |
| 1 sola fuente, ninguno con NIT | `deduplicate_unified` + `profile="deduplication_sin_nit_conservador"` | Techo conocido F1 ~0.55 |
| ≥2 fuentes, mezcla CON_NIT/SIN_NIT | **`Orchestrator`** | Único modo que separa regímenes |
| ≥2 fuentes, todas con NIT, una de ellas trusted | `Orchestrator` con `trusted_sources={...}` | Producción 4-fuentes |
```

**Acción 2 — docstring de `deduplicate_unified`:** añadir bloque de advertencia
al inicio:

```python
def deduplicate_unified(...):
    """...

    ⚠️ NO USAR sobre datasets que mezclan registros CON_NIT y SIN_NIT
    provenientes de fuentes distintas. En ese caso usa
    `Orchestrator` con `trusted_sources` declarado.

    Sobre el ground truth grande v2.14.0 (12.427 regs mezclados):
        - `deduplicate_unified` (este método): F1 = 0.563
        - `Orchestrator` con trusted sources:  F1 = 0.875
    """
```

### H1.5 Limpiar `except:` desnudos críticos [P1 · 2 horas]

11 sitios identificados. Lista exacta:

```
src/record_linkage/optimization/optuna_integration.py:123
src/record_linkage/reporting/suite.py:1498
src/record_linkage/reporting/dashboard.py:212, 1459
src/record_linkage/reporting/time_estimator.py:54
src/record_linkage/engine/linkage.py:527
src/record_linkage/pipeline/storage.py:110
src/record_linkage/pipeline/linkage_pipeline.py:992, 1294
src/record_linkage/pipeline/orchestrator.py:1294
```

**Acción:** sustituir cada uno por la excepción específica. Si no se sabe cuál,
ejecutar el código con `except BaseException as e: print(type(e), e); raise` y
documentar el resultado.

**Verificación final:** eliminar `E722` de los `per-file-ignores` en
`pyproject.toml` y correr `ruff check`. Si no aparece nada → trabajo terminado.

---

## 3. HITO H2 — Tests faltantes del path SQLite del clusterer (2 días)

### H2.1 Por qué importa

`OptimizedClusterer._cluster_in_memory` está cubierto al 100% por
`test_clusterer_vectorizado.py` (paridad bit-a-bit con Union-Find oráculo).

Pero el método `_should_use_disk_processing` activa otro path cuando:

```python
return len(scored_pairs) > 500_000 or n_entities > 1_000_000
```

**Ese path es exactamente el que se usa en producción 2M+ registros.** Y **no
tiene un solo test**. Los métodos `_setup_union_find_db`, `_process_scored_pairs_from_db`,
`_find_with_compression`, `_union_by_rank`, `_compress_all_paths`, `_close_db`
nunca se ejercitan en CI.

### H2.2 Plan de pruebas — `tests/test_clusterer_disk_based.py`

**Estrategia:** bajar el umbral de `_should_use_disk_processing` mediante un
parche de test o usando un dataset sintético con muchos pares. Validar paridad
de partición contra `_cluster_in_memory` (oráculo).

```python
# tests/test_clusterer_disk_based.py — esqueleto a implementar

"""Equivalencia in-memory vs disk-based del OptimizedClusterer.

Forzamos el path SQLite del clusterer (que se activa en producción con >500k
pares) sobre un dataset pequeño bajando el umbral. Verificamos que produce la
misma partición que `_cluster_in_memory` (el oráculo ya testeado).

Este test cierra el agujero más grande de cobertura identificado en la
auditoría de v2.14.0: 0% del path disk-based, 100% del in-memory.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch
from record_linkage.engine.clusterer import OptimizedClusterer


def _particion_desde_mapping(mapping, n):
    grupos = {}
    for i in range(n):
        grupos.setdefault(mapping[i], set()).add(i)
    return sorted(grupos.values(), key=min)


@pytest.mark.parametrize("seed", range(8))
def test_disk_based_equivale_in_memory(seed: int, tmp_path):
    """El path SQLite debe producir la misma partición que in-memory."""
    rng = np.random.default_rng(seed)
    n = int(rng.integers(20, 200))
    n_pairs = int(rng.integers(0, n * 3))
    a = rng.integers(0, n, n_pairs)
    b = rng.integers(0, n, n_pairs)
    mask = a != b
    scored = pd.DataFrame({"idx_0": a[mask], "idx_1": b[mask],
                            "score": np.full(mask.sum(), 0.9)})

    # Forzar path in-memory
    cfg_mem = {"chunk_size": 50_000}
    clus_mem = OptimizedClusterer(profile="standard", config=cfg_mem)
    with patch.object(OptimizedClusterer, "_should_use_disk_processing",
                       return_value=False):
        map_mem = clus_mem.cluster_entities(scored, None, n)

    # Forzar path disk-based
    clus_disk = OptimizedClusterer(profile="standard", config=cfg_mem)
    clus_disk._db_dir = str(tmp_path)
    with patch.object(OptimizedClusterer, "_should_use_disk_processing",
                       return_value=True):
        map_disk = clus_disk.cluster_entities(scored, None, n)
    clus_disk.cleanup()

    # La partición DEBE ser idéntica (los IDs pueden diferir; los sets, no)
    part_mem = _particion_desde_mapping(map_mem, n)
    part_disk = _particion_desde_mapping(map_disk, n)
    assert part_mem == part_disk, f"Particiones difieren en seed={seed}"


@pytest.mark.parametrize("n", [50, 200, 1000])
def test_disk_based_union_find_compression(n: int, tmp_path):
    """El path compression de _find_with_compression preserva representantes."""
    # Generar una cadena: 0-1-2-3-...-n  (todos en un solo cluster)
    scored = pd.DataFrame({"idx_0": list(range(n-1)),
                            "idx_1": list(range(1, n)),
                            "score": [0.9]*(n-1)})
    clus = OptimizedClusterer(profile="standard", config={"chunk_size": 50_000})
    clus._db_dir = str(tmp_path)
    with patch.object(OptimizedClusterer, "_should_use_disk_processing",
                       return_value=True):
        mapping = clus.cluster_entities(scored, None, n)
    clus.cleanup()

    # Todos deben tener el mismo cluster
    assert len(set(mapping.values())) == 1


def test_disk_based_clusterer_libera_recursos(tmp_path):
    """cleanup() debe cerrar la conexión y borrar el archivo SQLite."""
    import os
    scored = pd.DataFrame({"idx_0": [0,1,2], "idx_1": [1,2,3], "score": [0.9]*3})
    clus = OptimizedClusterer(profile="standard", config={})
    clus._db_dir = str(tmp_path)
    with patch.object(OptimizedClusterer, "_should_use_disk_processing",
                       return_value=True):
        clus.cluster_entities(scored, None, 4)
    db_path = clus._db_path
    clus.cleanup()
    assert clus._db_conn is None
    # El archivo puede o no borrarse según política, pero la conexión sí
```

### H2.3 Aumentar cobertura de `engine/lsh/trusted.py` de 21% a 70%+

Está al 21% porque solo se ejercita en el smoke test estructural. Producción
4-fuentes lo activa siempre.

**Plan:** añadir `tests/test_trusted_lsh.py` con:
- Test con 2 fuentes trusted + 2 no-trusted, datos sintéticos pequeños.
- Verificar que pares entre fuentes trusted reciben tratamiento privilegiado.
- Verificar paridad con motor disk-based cuando trusted_sources está vacío.

### H2.4 Verificación de cierre de H2

```bash
pytest tests/test_clusterer_disk_based.py tests/test_trusted_lsh.py -v
pytest --cov=record_linkage.engine --cov-report=term | grep -E "clusterer|trusted"
# Objetivo: clusterer.py ≥ 70%, trusted.py ≥ 70%
```

---

## 4. HITO H3 — Medición real (3-5 días) ⭐ EL HITO CRÍTICO

**Este es el bloqueante real. Todo lo demás es accesorio.**

### H3.1 Por qué ningún otro trabajo importa hasta que esto se haga

Llevas 15 meses y 14 versiones. Los F1=0.96 (CON_NIT) y F1=0.55 (SIN_NIT) son
sobre un ground truth **sintético determinista** que tú mismo generaste
(`generar_ground_truth_grande.py`, seed=42). Es honesto, está documentado, y es
**insuficiente para defender producción**. El RUES real tiene:

- Variantes que el generador sintético no contempla (sufijos `EN LIQUIDACION`,
  `EN CONCORDATO`, errores OCR sistemáticos, encoding latin1→utf8 fallido).
- Distribución de tamaños de grupo distinta (el sintético es 1-11 por grupo;
  el RUES real tiene grupos de 50+ en empresas grandes con muchas sucursales).
- Casos de fusión/cambio de razón social en el tiempo no modelados.

**Hasta que midas sobre datos reales, F1=0.96 es un decimal con falsa precisión.**

### H3.2 Paso a paso para hacer la medición real

#### H3.2.1 Obtener una muestra del RUES real [Día 1, mañana]

**Tamaño objetivo:** 50.000 a 100.000 registros. Razones:
- Suficiente para que el clusterer entre en path SQLite (>500k pares).
- Pequeño para etiquetar humanamente en 2-3 días.
- Representativo si se muestrea bien.

**Método de muestreo recomendado** (no aleatorio puro):

```python
# scripts/muestrear_rues_para_gt.py — A IMPLEMENTAR

"""Genera una muestra estratificada del RUES para etiquetado humano.

Estratificación por: tamaño de razón social, presencia de sufijo societario,
fuente, ciudad. Evita el sesgo de muestrear solo el 'cuerpo gordo' de la
distribución (empresas grandes, registros perfectos).
"""

import pandas as pd
from pathlib import Path

def muestrear_estratificado(
    rues_completo_parquet: str,
    n_total: int = 50_000,
    seed: int = 42,
) -> pd.DataFrame:
    df = pd.read_parquet(rues_completo_parquet)

    # Estratos
    df['__len_bin'] = pd.cut(df['RAZON_SOCIAL'].str.len(),
                              bins=[0, 20, 40, 60, 1000],
                              labels=['corto', 'medio', 'largo', 'muy_largo'])
    df['__has_sufijo'] = df['RAZON_SOCIAL'].str.contains(
        r'\b(S\.?A\.?S\.?|LTDA|S\.?A\.?|E\.?U\.?)\b', case=False, regex=True)

    # Muestreo proporcional dentro de cada estrato
    stratum_cols = ['__len_bin', '__has_sufijo']
    sample = df.groupby(stratum_cols, group_keys=False).apply(
        lambda g: g.sample(min(len(g),
                                 int(n_total * len(g) / len(df))),
                             random_state=seed)
    )
    return sample.drop(columns=['__len_bin', '__has_sufijo'])
```

#### H3.2.2 Generar pares candidatos para etiquetar [Día 1, tarde]

Ya existe el script: `scripts/generar_pares_para_etiquetar.py`. Úsalo con la
muestra recién creada:

```bash
python scripts/generar_pares_para_etiquetar.py \
    --input data/muestra_rues_50k.parquet \
    --output data/pares_a_etiquetar.csv \
    --col-nit NIT --col-name RAZON_SOCIAL \
    --n-pares 1000
```

**Distribución sugerida de los 1.000 pares:**
- 400 alta_confianza (score > 0.95): verifican falsos positivos en zona segura
- 400 frontera (score 0.70-0.85): donde se juega el F1
- 200 baja_confianza (score 0.50-0.65): verifican falsos negativos rescatables

#### H3.2.3 Protocolo de etiquetado [Días 2-3]

Ya existe `docs/PROTOCOLO_GROUND_TRUTH.md`. **Respétalo al pie de la letra.**
Resumen mínimo:

1. **2 etiquetadores independientes** (no debe ser solo tú).
2. Resolver desacuerdos en sesión conjunta. Documentar regla aplicada.
3. Cohen's kappa entre etiquetadores debe ser ≥ 0.80.
4. Si κ < 0.80: el problema NO es el sistema, es la definición. Reescribir el
   manual de etiquetado y empezar de nuevo.

**Output:** `data/ground_truth/pares_etiquetados_rues_real.csv` con columna
`MISMO_GRUPO` rellena (True/False).

#### H3.2.4 Medición [Día 4]

```bash
python scripts/medir_con_ground_truth.py \
    --input data/muestra_rues_50k.parquet \
    --pares-etiquetados data/ground_truth/pares_etiquetados_rues_real.csv \
    --col-nit NIT --col-name RAZON_SOCIAL \
    --reporte docs/MEDICION_REAL_v3.0.0.md
```

El reporte se publica como `docs/MEDICION_REAL_v3.0.0.md` y se enlaza
desde el README.

#### H3.2.5 Decisión de release [Día 5]

| F1 medido sobre RUES real | Acción |
|---|---|
| ≥ 0.90 | Release v3.0.0 con cifras publicadas |
| 0.80–0.90 | Identificar top-5 modos de falla. Hito H5 (Optuna) calibra contra ellos. Re-release tras corregir. |
| < 0.80 | Problema estructural. Revisar bloqueo LSH o features. NO release. |

**Esta decisión es binaria y se toma con datos. No con esperanza.**

### H3.3 Si no tienes acceso al RUES completo

Tres alternativas en orden de preferencia:

1. **Pedir extracto a quien tenga acceso.** 50k filas. Anonimizado si es
   necesario (mantener NIT y razón social; los demás campos no son críticos).
   El RUES es público; el acceso por API o descarga masiva puede gestionarse.

2. **Construir el ground truth a partir del cruce conocido.** Si tienes ya
   alguna tabla maestra empresarial donde los duplicados están resueltos
   (Supersociedades sola, por ejemplo, no tiene duplicados internos masivos),
   úsala como base. El cruce de Supersociedades x DIAN x CRM sobre 50k
   registros donde Supersociedades es trusted te da pares positivos
   "gratis": todo lo que matchea con Supersociedades es positivo verificado.

3. **Si las dos anteriores son imposibles:** declara explícitamente en el
   README "calibrado y medido únicamente sobre ground truth sintético; el
   F1 en producción es desconocido". Es honesto pero limita el uso.

---

## 5. HITO H4 — Migración a modo "todo en disco" (5 días)

### H4.1 Por qué

> *"Clave que siempre corra en disco todo, no en memoria, me gustaría una sola
> cosa, con eso el mantenimiento es más sencillo"* — requerimiento del usuario.

**El usuario tiene razón.** Hoy hay 5 motores LSH y 2 paths del clusterer
(in-memory + disk). Eso es navaja suiza con muchas hojas. Para mantenimiento y
para predecibilidad operativa, una sola ruta es mejor.

### H4.2 Estado actual (auditado)

| Componente | Path memoria | Path disco | Selector |
|---|---|---|---|
| Clusterer | `_cluster_in_memory` (scipy) | `_setup_union_find_db` (SQLite) | `_should_use_disk_processing` (>500k pares) |
| LSH | `OptimizedLSHEngine` (legacy, in-memory) | `DiskBasedLSHEngine` | Auto por perfil |
| Scoring | `_score_pairs_from_set` | `_score_pairs_from_db_streaming` | `engine_type` |
| Golden record | `GoldenRecordGeneratorV7` con `SafeSQLiteConnection` (ya en disco) | — | — |

**Lo único que ya está siempre en disco:** Golden record generator.
**Lo que tiene paths duales:** Clusterer, LSH, Scorer.

### H4.3 Plan de migración

#### H4.3.1 Default global a disk-based [P1]

Cambiar el default de `_should_use_disk_processing`:

```python
# ANTES (clusterer.py:188)
def _should_use_disk_processing(self, scored_pairs, n_entities) -> bool:
    if isinstance(scored_pairs, str) and scored_pairs.endswith(".db"):
        return True
    if isinstance(scored_pairs, pd.DataFrame):
        return len(scored_pairs) > 500_000 or n_entities > 1_000_000
    return True

# DESPUÉS (propuesta v3.0.0)
def _should_use_disk_processing(self, scored_pairs, n_entities) -> bool:
    """Default v3.0.0: siempre en disco. Override con env var solo para tests."""
    import os
    if os.getenv("RUES_LINKER_FORCE_MEMORY") == "1":
        return False
    return True
```

**Razones:**
- Un solo path en producción = un solo conjunto de bugs posibles.
- Path SQLite ya está testeado tras H2.
- Para datasets pequeños el overhead de SQLite es ~10s (verificado: 12k regs
  via Orchestrator en 32s, vs 95s vía `deduplicate_unified` in-memory + LSH).
  El "disk siempre" es **MÁS RÁPIDO** en esta librería porque el path
  in-memory llama al LSH legacy que no está vectorizado al mismo nivel.

#### H4.3.2 Deprecar `OptimizedLSHEngine` (legacy in-memory) [P1]

`engine/lsh/legacy.py` (409 líneas) está marcado en el README como "referencia,
NO usar en prod". Pero sigue importable y nada impide a un dev nuevo usarlo.

**Acciones:**
1. Añadir `DeprecationWarning` en `OptimizedLSHEngine.__init__`:
   ```python
   import warnings
   warnings.warn(
       "OptimizedLSHEngine es legacy in-memory. Usa DiskBasedLSHEngine.",
       DeprecationWarning, stacklevel=2,
   )
   ```
2. En v3.1.0 eliminar `legacy.py` por completo.

#### H4.3.3 Eliminar `_run_L2_legacy` y el monkey-patching [P1]

El MIGRATION_LOG §3 documenta el monkey-patching de `Orchestrator._run_L2` como
"patrón frágil heredado". En v2.14.0 sigue. Eliminarlo:

1. `_run_L2_optimized` (con `TrustedSourceLSHEngine`) se convierte en el método
   `_run_L2` permanente.
2. Eliminar `_run_L2_legacy`.
3. Eliminar el `assert __name__ == '_run_L2_optimized'` de los notebooks.

#### H4.3.4 Unificar API pública en `Orchestrator` [P0 CRÍTICO]

**Acción más importante de H4.** Hoy hay dos APIs:

- `from record_linkage.deduplication.unified import deduplicate_unified`
- `from record_linkage.pipeline.orchestrator import Orchestrator`

`deduplicate_unified` colapsa con datasets multi-fuente mixtos (F1=0.563 vs
0.875 del Orchestrator). Esto es trampa para devs nuevos.

**Propuesta v3.0.0:**

```python
# record_linkage/__init__.py
from .pipeline.orchestrator import Orchestrator
from .deduplication.unified import deduplicate_unified  # con warning

# `deduplicate_unified` queda como conveniencia para casos simples
# (1 fuente, dedup interna). Para todo lo demás: Orchestrator.

# Añadir helper de alto nivel:
def linkage(
    sources: dict[str, pd.DataFrame],
    *,
    trusted_sources: set[str] = None,
    col_name: str = "RAZON_SOCIAL",
    col_nit: str = "NIT",
    col_ciudad: str = "CIUDAD",
    extra_features: list[str] = None,
    work_dir: str = None,
    profile: str = "produccion_estandar",
) -> "PipelineResult":
    """API de alto nivel única para record linkage multi-fuente.

    Args:
        sources: dict {nombre_fuente: dataframe}. Una entrada por fuente.
        trusted_sources: set de nombres de fuentes confiables (tienen NIT
            verificado, prioridad para nombre golden).
        col_name, col_nit, col_ciudad: nombres de columnas estándar.
        extra_features: lista de columnas adicionales para usar en scoring
            (telefono, direccion, email, etc.).
        work_dir: directorio de trabajo (todos los SQLite intermedios van ahí).
        profile: perfil de configuración. Ver `config.profiles`.

    Returns:
        PipelineResult con .golden (un registro por entidad), .correlative
        (mapping registro original → ID_GRUPO), .metrics.

    Ejemplo:
        >>> from record_linkage import linkage
        >>> result = linkage(
        ...     sources={"RUES": df_rues, "DIAN": df_dian, "CRM": df_crm},
        ...     trusted_sources={"RUES"},
        ...     col_ciudad="CIUDAD",
        ...     extra_features=["TELEFONO", "EMAIL"],
        ...     work_dir="/data/rl_run_001",
        ... )
        >>> result.golden.head()
        >>> result.correlative.to_parquet("correlativa.parquet")
    """
    from .config.profiles import crear_config_orchestrator
    cfg = crear_config_orchestrator(
        perfil=profile,
        trusted_sources=trusted_sources or set(),
    )
    orch = Orchestrator(config=cfg, sources=sources, work_dir=work_dir)
    return orch.run()
```

Con esto el README cambia a:

```python
from record_linkage import linkage

result = linkage(
    sources={"RUES": df_rues, "DIAN": df_dian, "CRM": df_crm},
    trusted_sources={"RUES"},
    work_dir="/data/run_001",
)
```

**Una sola línea, un solo path, todo en disco.** Cumple con el requerimiento.

#### H4.3.5 Soporte para "varias variables y varias fuentes" [P0]

El usuario pidió específicamente que se soporten **varias variables** (no solo
nombre + NIT) y **varias fuentes**. Hoy ya se soporta vía `extra_features` en
el scorer (`_compute_extra_features_contribution`, líneas 735-820 de
`scorer.py`).

**Acción:** documentar en el README y exponer en la API de alto nivel
(`linkage(...)`) las variables adicionales típicas:

| Variable | Tipo | Aporte estimado al F1 | Cómo se compara |
|---|---|---:|---|
| `CIUDAD` | string | +0.067 medido | `fuzz.token_set_ratio` con peso 0.20 |
| `TELEFONO` | string normalizado | +0.01 estimado | igualdad exacta de últimos 7 dígitos |
| `EMAIL` | string lowercased | +0.01 estimado | igualdad exacta del dominio + similitud del usuario |
| `DIRECCION` | string normalizado | +0.02 estimado | `fuzz.token_set_ratio` con peso 0.10 |
| `PAIS` (para sin-NIT) | string | bloqueador | igualdad exacta (no fuzzy) |

La línea base medida (v2.14.0) tiene CIUDAD ya integrada. Las otras tres
variables están soportadas vía `extra_features` pero **no están documentadas
en el README**. Documentar.

#### H4.3.6 Verificación de cierre de H4

```bash
# Todos los tests siguen pasando
pytest tests/ -v

# El nuevo helper funciona
python -c "
from record_linkage import linkage
import pandas as pd
df = pd.DataFrame({'NIT': ['1','2','3'], 'RAZON_SOCIAL': ['A','B','C']})
result = linkage(sources={'TEST': df}, work_dir='/tmp/h4_check')
print(result.golden.shape)
"

# El path in-memory ya no se activa por default
grep -n "FORCE_MEMORY\|_should_use_disk" src/record_linkage/engine/clusterer.py

# El monkey-patching se eliminó
grep -rn "_run_L2_legacy\|_run_L2_optimized" src/ scripts/ notebooks/
# Esperado: cero referencias activas
```

---

## 6. HITO H5 — Optuna sobre ground truth REAL (3 días)

### H5.1 Estado actual de Optuna

**Clases del notebook que NO migraron a la librería:**
```
AdvancedOptimizationConfig    OptimizationAnalyzer
BalancedObjective             ObjectiveConfig
BalancedOptimizationEngine    ParameterConfig
ParameterType                 MetricType
TestResult
```

**Clases que SÍ están en la librería pero al 0% de cobertura:**
```
src/record_linkage/optimization/engine.py            139 stmts   0%
src/record_linkage/optimization/optuna_integration.py 97 stmts   0%
src/record_linkage/optimization/parameters.py         87 stmts   0%
src/record_linkage/optimization/visualizer.py         27 stmts   0%
```

**Diagnóstico:** la migración de Optuna está a medio camino. Las clases núcleo
(`OptimizationEngine`, `OptunaIntegration`, `ParameterSpace`) están portadas.
Las 9 clases del notebook que no migraron son la capa "avanzada" (multi-fase,
balance precision/recall configurable, métricas custom).

### H5.2 ¿Migrarlas o eliminarlas?

**Pregunta clave:** ¿se usaron alguna vez en producción?

Si la respuesta es "no, fueron exploración", elimínalas del notebook fuente
para no acumular deuda. Si la respuesta es "sí, pero como prototipo", entonces
H5 migra solo lo que se usó.

**Recomendación:** declarar las 9 clases como **deprecated en el notebook
fuente** y eliminarlas. La capa que SÍ migró (`OptimizationEngine` +
`OptunaIntegration`) es funcionalmente suficiente para calibrar
`(score_threshold, min_name_similarity, idf_weight_blend)` que son las 3
palancas reales del F1.

### H5.3 Plan: conectar Optuna al GT real (post-H3)

**Sin H3 (medición real), H5 no tiene sentido.** Optimizar contra un sintético
solo te lleva a un máximo local del sintético.

Cuando H3 esté completo:

```python
# scripts/calibrar_con_optuna.py — A IMPLEMENTAR

"""Calibración Optuna contra ground truth real.

Pre-requisito: archivo de pares etiquetados producido en H3.

Optimiza simultáneamente:
    - score_threshold ∈ [0.60, 0.95]
    - min_name_similarity ∈ [0.50, 0.85]
    - idf_weight_blend ∈ [0.0, 0.7]
    - peso_ciudad ∈ [0.0, 0.4]

Objetivo: maximizar F1 sobre pares etiquetados, con restricción
`precision >= 0.85` (configurable). Sin restricción de precision, el
optimizador encuentra F1 alto recall ~1.0 que es inútil en producción.
"""

import optuna
from record_linkage.optimization.engine import OptimizationEngine
from record_linkage.evaluation.pairwise import evaluar_pares

def objective(trial, df_input, pares_etiquetados):
    params = {
        "score_threshold": trial.suggest_float("score_threshold", 0.60, 0.95),
        "min_name_similarity": trial.suggest_float("min_name_similarity", 0.50, 0.85),
        "idf_weight_blend": trial.suggest_float("idf_weight_blend", 0.0, 0.7),
        "peso_ciudad": trial.suggest_float("peso_ciudad", 0.0, 0.4),
    }
    # ... correr pipeline con esos params, evaluar contra GT
    metrics = evaluar_pares(...)
    if metrics.precision < 0.85:
        return 0.0  # Penalización: no aceptamos baja precision
    return metrics.f1


study = optuna.create_study(direction="maximize",
                             sampler=optuna.samplers.TPESampler(seed=42))
study.optimize(lambda t: objective(t, df_input, pares_etiquetados),
                 n_trials=100)
print(f"Mejor F1: {study.best_value:.4f}")
print(f"Mejores params: {study.best_params}")
```

### H5.4 Salida esperada de H5

Un archivo `data/profiles/produccion_calibrado_v3.0.json` con los parámetros
óptimos. Cargable como perfil en `crear_config_orchestrator()`.

---

## 7. Tabla maestra de métricas a publicar en README

Cuando todos los hitos cierren, esta es la tabla que debe ir al README
reemplazando la actual:

```markdown
## Calidad de linkage — medido v3.0.0

### Sobre ground truth sintético (`data/ground_truth/ground_truth_grande.csv`)

| Dataset | F1 | Precision | Recall | Tiempo |
|---|---:|---:|---:|---:|
| CON_NIT (10.085 regs) | 0.961 | 0.972 | 0.950 | 127s |
| SIN_NIT (2.342 regs, perfil estándar) | 0.549 | 0.393 | 0.908 | 5s |
| **MIX vía Orchestrator (12.427, trusted=RUES+SUPER)** | **0.875** | **0.875** | **0.876** | **32s** |
| MIX vía deduplicate_unified (anti-patrón documentado) | 0.563 | 0.401 | 0.944 | 95s |

### Sobre ground truth REAL del RUES (medido en H3, v3.0.0) ⭐

| Dataset | F1 | Precision | Recall | Tiempo |
|---|---:|---:|---:|---:|
| Muestra estratificada 50k del RUES | _A medir en H3_ | — | — | — |
| Muestra estratificada 50k + DIAN + CRM (3 fuentes) | _A medir en H3_ | — | — | — |

### Escala probada empíricamente

| Volumen | Modo | Tiempo | F1 | Status |
|---|---|---:|---:|---|
| 10k registros | `deduplicate_unified` | 127s | 0.961 | ✅ Verificado |
| 12k mix multi-fuente | `Orchestrator` + trusted | 32s | 0.875 | ✅ Verificado |
| 37k registros (3x con typos) | `Orchestrator` + trusted | 84s | 0.844 | ✅ Verificado |
| 50k registros | `Orchestrator` + trusted | _A medir en H3_ | — | □ |
| 200k registros | `Orchestrator` + trusted | _A medir en H3_ | — | □ |
| **2M registros** | `Orchestrator` + trusted | _A medir en H3_ | — | □ |
```

---

## 8. Pruebas a ejecutar — guía paso a paso

Esta sección es la respuesta directa a *"que explique claramente cómo hacer
las pruebas con las bases de datos crudas para hacer record linkage, cómo
tomar la línea base"*.

### 8.1 Pre-requisitos

```bash
# Instalación limpia
cd rues-linker/
pip install -e ".[dev,snowflake]"

# Verificación
python -c "import record_linkage; print(record_linkage.__version__)"
# Esperado: 3.0.0 (o la versión actual)

pytest tests/ -q
# Esperado: 236+ pasan, ~80s
```

### 8.2 Cómo hacer record linkage sobre fuentes crudas

**Caso 1 — Una sola fuente (dedup interna):**

```python
import pandas as pd
from record_linkage import linkage  # (después de H4)

df = pd.read_csv("rues.csv", dtype=str)
result = linkage(
    sources={"RUES": df},
    work_dir="/data/runs/rues_dedup_001",
)

# Resultado
result.golden       # 1 fila por entidad única
result.correlative  # registro original → ID_GRUPO

result.golden.to_parquet("/data/runs/rues_dedup_001/golden.parquet")
result.correlative.to_parquet("/data/runs/rues_dedup_001/correlative.parquet")
```

**Caso 2 — Multi-fuente con una trusted:**

```python
result = linkage(
    sources={
        "RUES": pd.read_csv("rues.csv", dtype=str),
        "DIAN": pd.read_csv("dian.csv", dtype=str),
        "CRM": pd.read_csv("crm.csv", dtype=str),
        "SUPERSOCIEDADES": pd.read_csv("super.csv", dtype=str),
    },
    trusted_sources={"RUES", "SUPERSOCIEDADES"},
    col_name="RAZON_SOCIAL", col_nit="NIT", col_ciudad="CIUDAD",
    extra_features=["TELEFONO", "EMAIL", "DIRECCION"],
    work_dir="/data/runs/produccion_001",
)
```

**Caso 3 — Fuente sin NIT (importaciones Corea):**

```python
result = linkage(
    sources={"IMPORTACIONES": df_corea},
    profile="deduplication_sin_nit_conservador",  # techo F1 ~0.55
    col_name="RAZON_SOCIAL", col_ciudad="CIUDAD",
    work_dir="/data/runs/corea_dedup",
)
# Aviso: F1 esperado < 0.60. Aceptable solo si precision es prioritario.
```

### 8.3 Cómo tomar línea base (medir F1) sobre tus datos

**Pre-requisito:** tener un archivo de pares etiquetados (`MISMO_GRUPO` rellena).

```bash
# Paso 1: generar pares candidatos sobre tu muestra
python scripts/generar_pares_para_etiquetar.py \
    --input data/mi_muestra.parquet \
    --output data/pares_a_etiquetar.csv \
    --col-nit NIT --col-name RAZON_SOCIAL \
    --n-pares 1000

# Paso 2: etiquetar manualmente la columna MISMO_GRUPO del CSV
# (seguir docs/PROTOCOLO_GROUND_TRUTH.md, dos etiquetadores)

# Paso 3: medir el F1 del sistema contra esos pares
python scripts/medir_con_ground_truth.py \
    --input data/mi_muestra.parquet \
    --pares-etiquetados data/pares_a_etiquetar.csv \
    --col-nit NIT --col-name RAZON_SOCIAL \
    --reporte data/REPORTE_LINEA_BASE.md
```

El reporte contiene:
- F1, precision, recall globales
- Métricas por estrato (alta_confianza, frontera, baja_confianza)
- Lista de FP y FN concretos para diagnóstico
- Sugerencias de parámetros a calibrar

### 8.4 Cómo correr stress test sobre tu volumen real

```bash
# Test con 10% del RUES (~250k registros)
python scripts/stress_test.py \
    --input data/rues_completo.parquet \
    --fraction 0.10 \
    --profile produccion_estandar \
    --output reporte_stress_250k.md
```

(Este script no existe aún; se crea en H3.)

### 8.5 Cómo verificar reproducibilidad

```bash
# Correr 2 veces el mismo input y verificar hash idéntico
python scripts/verificar_determinismo.py \
    --input data/muestra_1k.parquet \
    --runs 2
```

(Script tampoco existe; trivial de implementar.)

---

## 9. Pre-Delivery Checklist v3.0.0

Antes de tagear v3.0.0 y publicar a PyPI:

### Documentación
- [ ] README versión coincide con pyproject.toml
- [ ] README tabla de métricas refleja MEDICIÓN REAL (no sintético)
- [ ] README incluye tabla "Cuándo usar cada API"
- [ ] README incluye sección "Variables adicionales soportadas"
- [ ] MIGRATION_LOG §1 reconoce las 5 modernizaciones algorítmicas
- [ ] CHANGELOG v3.0.0 publicado con changes desde v2.14.0

### Código
- [ ] Helper `linkage()` de alto nivel disponible
- [ ] `_should_use_disk_processing` default = True
- [ ] `DeprecationWarning` en `OptimizedLSHEngine`
- [ ] `_run_L2_legacy` eliminado
- [ ] Monkey-patching en notebooks de producción eliminado
- [ ] Cero `except:` desnudos en `src/` (regla E722 sin ignore)
- [ ] Cero `except Exception:` salvo donde justificado con comentario

### Tests
- [ ] `pytest tests/` pasa 100%
- [ ] `test_clusterer_disk_based.py` implementado
- [ ] `test_trusted_lsh.py` implementado
- [ ] Cobertura `engine/clusterer.py` ≥ 70%
- [ ] Cobertura `engine/lsh/trusted.py` ≥ 70%
- [ ] Cobertura global ≥ 60%

### Calidad
- [ ] `ruff check src/ tests/ scripts/` — All checks passed
- [ ] `ruff format --check` — already formatted
- [ ] `python -m build` produce wheel + sdist
- [ ] `twine check dist/*` — both PASSED

### Empíricas
- [ ] F1 medido sobre RUES real publicado en docs/MEDICION_REAL_v3.0.0.md
- [ ] Tiempo medido en ≥ 200k registros publicado
- [ ] Resultado de stress test a 2M registros publicado (o declarado infactible)

### Release
- [ ] Tag v3.0.0 en git
- [ ] Build subido a TestPyPI primero, smoke test
- [ ] Build subido a PyPI público

---

## 10. Lo que se queda como está (decisiones de no-cambio)

Estas cosas están bien hoy y no se tocan:

- **Cálculo del DV NIT** (3 implementaciones, paridad bit-exact, coinciden con DIAN). ✅
- **Determinismo bit-a-bit** entre corridas (verificado). ✅
- **Empaquetado PyPI** (`twine check` PASSED). ✅
- **Linting `ruff`** (cero violaciones). ✅
- **CI workflows** (.github/workflows/ci.yml y publish.yml están bien diseñados). ✅
- **Manejo de credenciales** (Colab Secrets + env vars + json fallback). ✅
- **Estructura modular** (14 subpaquetes con responsabilidad clara). ✅
- **`pairwise.py`** (cálculo de F1 al 96% de cobertura). ✅
- **`MIGRATION_LOG.md`** (excepto el §1 que se corrige en H1.3). ✅ excepcional
- **`PROTOCOLO_GROUND_TRUTH.md`** (calidad de investigación). ✅
- **`FASE1_LINEA_BASE.md`** (honestidad ejemplar reconociendo autoengaños previos). ✅

---

## 11. Cómo cerrar el ciclo formalmente

Cuando los 5 hitos estén completados:

1. **Tag v3.0.0 en git.**
2. **Publicar a PyPI público.**
3. **Escribir un post de cierre** (LinkedIn, blog interno, o donde corresponda)
   con el siguiente formato sugerido:

   > "Cerramos el ciclo de rues-linker. 15 meses, 14 versiones, 1 medición real
   > sobre el RUES (F1 = X.XX sobre Y mil registros etiquetados). El código
   > queda en PyPI público bajo Apache-2.0. Lecciones aprendidas: [3-5 bullets].
   > Próximo paso: monitoreo en producción durante 6 meses, sin nuevos features."

4. **Cerrar el repositorio a nuevos features** durante 6 meses. Solo bugfixes
   y métricas en producción. Si en 6 meses surge una necesidad real (que no
   sea perfeccionismo del autor), reabrir.

Esto es lo que diferencia "proyecto cerrado" de "proyecto abandonado": el
cierre es activo y documentado, no por agotamiento.

---

## 12. Estimación de esfuerzo total y costo de oportunidad

| Hito | Esfuerzo | Crítico para producción |
|---|---:|:---:|
| H1 — Pulir merengue | 0.5 d | ✅ Sí (warning de `deduplicate_unified` es P0) |
| H2 — Tests clusterer disk-based | 2 d | ✅ Sí |
| H3 — Medición real ⭐ | 3-5 d | ✅ **El único hito que importa de verdad** |
| H4 — Todo en disco + API unificada | 5 d | ✅ Sí |
| H5 — Optuna sobre GT real | 3 d | ⚠️ Solo si H3 muestra F1 < 0.90 |
| **TOTAL** | **13.5–15.5 días** | |

**Costo de no hacerlo:** seguir en el ciclo "v2.16 → v2.17 → ..." indefinidamente,
con métricas sintéticas y cero defensibilidad ante un auditor externo o un
incidente en producción.

**Costo de hacerlo:** 16 días persona. Si tienes capacidad de 2 días/semana
dedicados, son **8 semanas calendario**. Si tienes capacidad full-time, **3
semanas**.

**Asimetría:** los 16 días que cierran el ciclo valen más que los 90 días
acumulados desde v2.10.0 hasta v2.14.0. No es cuestión de horas, es de orden.

---

**Fin del roadmap. Este documento es la única referencia activa para llegar a
v3.0.0. Cuando se complete, marcar este archivo como `ROADMAP_PRODUCCION_CERRADO.md`
y dejar de tocarlo.**
