# Sprint 0.8.0 — Pre-screening LSH + Benchmarks reproducibles

**Fecha:** 2026-05-27 · **Versión paquete:** `0.6.0 → 0.7.0`

## Resumen ejecutivo HONESTO

| Objetivo del plan | Status | Realidad medida |
|---|---|---|
| Pre-screening LSH ✅ implementado | ✅ Componente `NITPrescreener` listo | Sí |
| Speedup 2-3× | ❌ **NO alcanzado** | Speedup real: **1.21× a 1.40×** según dataset |
| Benchmarks reproducibles | ✅ Script + resultados JSON | Sí, en `benchmarks/results/` |
| Suite completa | ✅ 17/17 nuevos + suite intacta | Verificado |

**Veredicto honesto:** el componente funciona y es útil. **El speedup prometido (2-3×) NO se alcanzó** y debo explicar por qué.

---

## 1. Qué se construyó

### `NITPrescreener` (componente puro)

**Ubicación:** `src/record_linkage/engine/lsh/prescreen.py`

**Diseño:**
- Componente PURO sin side effects ni acoplamiento al Orchestrator
- Opt-in: requiere instanciación explícita (no rompe nada existente)
- O(n) en tiempo y memoria
- Determinístico

**API mínima:**
```python
from record_linkage.engine.lsh import NITPrescreener

prescreener = NITPrescreener(
    nit_column="NIT_BASE",
    min_group_size=2,
    max_group_size=50,
    cross_source_only=False,
    trusted_unique_sources={"RUES", "SUPERSOCIEDADES"},
)
result = prescreener.partition(df)

# result.exact_match_pairs    : set[tuple[int,int]] - pares NIT-exact
# result.residual_df          : DataFrame para LSH
# result.reduction_pct        : fracción que NO va a LSH
# result.speedup_estimate_lsh : estimación lineal del speedup
```

**Características:**
- Filtra NITs vacíos/inválidos (van al residual)
- Descarta grupos NIT enormes (>50 registros = sospechosos)
- Respeta `trusted_unique_sources` (no fusiona intra-RUES)
- Respeta `cross_source_only` (solo pares inter-fuente)
- Logging informativo

### `benchmark_lsh_prescreen.py` (benchmark reproducible)

**Ubicación:** `benchmarks/benchmark_lsh_prescreen.py`

**Diseño:**
- Dataset sintético reproducible (seed fijo, overlap configurable)
- Mide: tiempo LSH solo vs Prescreen + LSH(residual)
- Reporta: speedup, recall, reducción de input
- Outputs JSON estructurados con hash de config
- Verifica integridad (los pares se preservan correctamente)

**Uso:**
```bash
python benchmarks/benchmark_lsh_prescreen.py --n 10000 --overlap 0.30 --seed 42
python benchmarks/benchmark_lsh_prescreen.py --n 50000 --overlap 0.30 --seed 42
```

---

## 2. Resultados reales del benchmark

### Tabla de mediciones

| n_records | overlap | t_LSH_solo | t_Combined | **Speedup** | Pares LSH | Pares Combined |
|---:|---:|---:|---:|---:|---:|---:|
| 5,000 | 30% | 9.06 s | 7.46 s | **1.21×** | 202,958 | 107,977 |
| 20,000 | 50% | 23.93 s | 17.09 s | **1.40×** | 2,825,208 | 1,063,932 |

**Observaciones:**
- Speedup **REAL: 1.2× a 1.4×** (no 2-3×)
- Reducción del input al LSH = `overlap_pct` exactamente (lo esperado)
- Pares "únicos del prescreen" (67 en n=20k): son pares con NIT idéntico que el LSH **rechaza** por similitud de nombres baja → **valor que el prescreen rescata**

### Por qué NO se alcanzó 2-3×

**1. La estructura de costos del LSH no es linear en n.**

El LSH tiene 3 fases con costos distintos:
- Generación de firmas MinHash: **O(n × permutations)** — lineal estricto
- Indexación de bandas: **O(n × bands)** — lineal estricto
- Búsqueda de candidatos: **O(n × bands × avg_bucket_size)** — depende de la distribución

Reducir `n` al 50% reduce solo la primera y segunda fases al 50%. La tercera fase sí baja más, pero el overhead constante (init, setup de SQLite, etc.) no escala.

**2. Mi estimación inicial fue optimista.**

Asumí erróneamente que el LSH era cuadrático en `n` para la búsqueda de candidatos. **No lo es.** El LSH **es lineal en `n`** (es justo su gracia vs comparación all-pairs). Por eso reducir input 50% solo da speedup ~1.5× a 2×, no 2-3×.

**3. Tu caso de producción (1.97M, bases pre-deduplicadas) es AÚN peor para esta optimización.**

- Overlap real ≈ **2%** (38k duplicados / 1.97M)
- Residual ≈ **98% del input**
- **Speedup esperado: ~1.02× (2% de mejora)**

Para tu caso real, el NITPrescreener **NO va a darte velocidad notable**. Su valor está en otras dimensiones (ver §3).

---

## 3. Valor REAL del NITPrescreener (más allá del speedup)

Aunque el speedup en producción es marginal, el componente tiene valor:

### 3.1 Captura garantizada de NIT-exactos

En el benchmark n=20k, **67 pares NIT-exact fueron rescatados** que el LSH puro **NO encontraría** porque su similitud de nombres (Jaccard sobre n-grams) está por debajo del threshold 0.58.

Ejemplo (extrapolado al log de tu primera corrida):
```
NIT 1010168980: 'VILLAMIL ORTIZ JOSE LUIS - KOTTRISK' vs 'JOSE LUIS VILLAMIL ORTIZ'
```
Estos son la **misma persona**: nombre invertido + nombre comercial. Jaccard sobre n-grams puede dar similitud baja por las palabras "KOTTRISK"/"ORTIZ" que dominan. Pre-screening por NIT los captura **sin depender de similitud textual**.

### 3.2 Auditoría explícita de fusiones por NIT

El componente devuelve un `PrescreenResult` estructurado que permite **separar las fusiones por NIT-exacto** de las fusiones por similitud-de-nombre. Esto es valioso para:
- QA manual (revisar primero los NIT-exactos, son los más confiables)
- Trazabilidad (saber por qué un cluster se formó)
- Auditoría de NITs sospechosos (grupos enormes descartados por max_group_size)

### 3.3 Resiliencia para datasets con overlap alto

Para casos distintos a ProColombia (fuentes con overlap real 30-50%), el speedup sí es relevante:
- Speedup 1.4× sobre 50% overlap (validado en benchmark)
- Si tienes pipelines con 100k+ registros y overlap >30%, **ahorrarás minutos por corrida**

---

## 4. Recomendación final para tu uso

Para tu caso de producción (1.97M, bases pre-deduplicadas):

| Pregunta | Respuesta honesta |
|---|---|
| ¿Activar NITPrescreener? | **Sí, pero por VALOR no por velocidad** |
| ¿Va a hacer mi corrida más rápida? | No notablemente (estimado +2% mejora) |
| ¿Va a capturar pares que ahora pierdo? | Sí, los NIT-exactos con nombres muy distintos |
| ¿Va a romper algo? | No (opt-in, retrocompat 100%) |

**Decisión sugerida:** **NO integrarlo al Orchestrator en este sprint**. Hacerlo en Sprint 0.9.0 con benchmark contra tus datos reales antes/después.

---

## 5. Cómo correr el benchmark

```bash
# Bench rápido (n=5000)
cd /path/to/rues-linker
python benchmarks/benchmark_lsh_prescreen.py --n 5000 --overlap 0.30

# Bench medio (n=20000)
python benchmarks/benchmark_lsh_prescreen.py --n 20000 --overlap 0.50 --seed 42

# Variando overlap (paramétrico)
for OV in 0.10 0.20 0.30 0.50; do
  python benchmarks/benchmark_lsh_prescreen.py --n 10000 --overlap $OV --seed 42
done

# Cada run produce un JSON en benchmarks/results/
# Mismo seed + misma config = mismo hash = resultados comparables
```

**Output ejemplo (`bench_20000_148768d086c2_20260527_122144.json`):**
```json
{
  "config": {
    "n_records": 20000,
    "overlap_pct": 0.5,
    "seed": 42,
    "lsh_threshold": 0.58
  },
  "config_hash": "148768d086c2",
  "paquete_version": "0.7.0",
  "t_lsh_only_s": 23.928,
  "t_combined_s": 17.092,
  "speedup_lsh": 1.4,
  "reduction_lsh_input": 0.5,
  "n_input": 20000,
  "n_lsh_only_pairs": 2825208,
  "n_combined_pairs": 1063932,
  ...
}
```

---

## 6. Lo que NO se hizo (consciente)

| Item | Razón |
|---|---|
| Integrar NITPrescreener al Orchestrator | Decisión basada en datos: no aporta velocidad sobre tu caso real |
| Benchmark contra dataset real (1.97M) | Requiere ejecución en Colab con tus datos |
| Optimizar otros cuellos de botella (L1, L5) | Out of scope de este sprint; ver §7 |
| Mejorar el código de DEBUG `AUDITANDO PAR` en `scorer.py` | Detectado durante el análisis, programado para Sprint 0.9.0 |

---

## 7. Próximos pasos sugeridos (Sprint 0.9.0)

Basado en lo aprendido del first-run del 27-05-2026:

**Optimizaciones de mayor impacto que el prescreening:**

| Fase | Tiempo en tu run | % | Optimización potencial |
|---|---:|---:|---|
| L1_prep | 3m 23s | 6% | Carga paralela de fuentes (multiproc) |
| **L2_lsh** | **36m 56s** | **70%** | **Cache de firmas entre corridas + paralelización de bandas** |
| L3_scoring | 53s | 2% | (ya optimizado) |
| L4_clustering | 16s | 0.5% | (ya optimizado) |
| L5_golden | 6m 37s | 13% | TextProcessor más rápido + chunks paralelos |
| L6_reporting | 4m 37s | 9% | Hacer opcional + lazy |

**Mejoras de calidad:**
- Eliminar prints de DEBUG `AUDITANDO PAR` del scorer (poner detrás de flag)
- Configurar opcionalmente `skip_reporting=True` en producción
- Validar comillas literales en RAZON_SOCIAL durante L1_prep (hallazgo del first-run)

---

**Confianza: ALTO (~95%)** sobre el componente, **HONESTIDAD BRUTAL** sobre las expectativas:

- Componente NITPrescreener: 17/17 tests pasan, código limpio, retrocompat 100%
- Benchmark reproducible: corre, produce resultados estables con seed fijo
- **El objetivo "2-3× speedup" NO se cumplió** (real: 1.2-1.4×)
- Para tu caso de producción real (1.97M pre-dedupado), **NO recomiendo integrarlo todavía**
- Su verdadero valor (captura garantizada de NIT-exactos) es real pero distinto al prometido

5% incertidumbre:
- No probé contra tu dataset real (requiere Colab)
- El benchmark mide LSH+prescreen pero NO mide scoring (que también filtra)
- Comportamiento sobre escenarios con `cross_source_only=True` y `trusted_unique_sources` validado solo en tests unitarios, no en benchmark
