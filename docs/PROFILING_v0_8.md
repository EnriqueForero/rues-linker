# Profiling LSH — Sprint 0.8.2, Tarea 2.3

**Versión:** v0.7.2 · **Fecha:** 2026-05-27 · **Estado:** preparado, pendiente medición con corpus real

## Por qué este documento

El **Sprint 0.8.2 Tarea 2.1** (paralelizar bandas del LSH) asumía un
speedup de **1.65×** sobre la fase de indexación. Un mini-benchmark
sintético (`200_000 × 4 columnas uint64`) en este repo mostró una mezcla
distinta a la asumida:

| Fase | % tiempo | Notas |
|---|---|---|
| CPU (`_hash_rows_stable` FNV-1a vectorizado) | **1.5%** | Solo cómputo numérico puro |
| IO  (`executemany` + `CREATE INDEX`) | **98.5%** | SQLite en disco local |

Bajo ese reparto, paralelizar la fase CPU con N workers da:

```
speedup_max = 1 + (0.015) × (N − 1)
            ≈ 1.015 con N=2 vCPU
```

Es decir, **el plan estaba sobre-estimando el beneficio por dos órdenes
de magnitud** según el benchmark sintético. Antes de invertir 3 días en
una refactorización con riesgo ALTO (`ProcessPoolExecutor` + pickle de
`h5py.Dataset` + merge SQLite multi-banda), el equipo decidió **medir
sobre el corpus real** y dejar la decisión al dato, no a la asunción.

Este doc es el manual de cómo correr esa medición y cómo interpretarla.

## Por qué el dataset sintético podría mentir

El benchmark sintético subestima IO en casos donde el real lo sufre, y
subestima CPU donde el real lo necesita. Mecanismos por los que el
corpus real puede dar otra respuesta:

- **Google Drive vs SSD local.** El paquete está calibrado contra Colab
  con storage montado por FUSE. Escrituras `executemany` ahí pueden
  costar 10–50× más que en `/tmp` local — lo que SUBE el porcentaje IO
  (y hace la paralelización CPU aún menos útil).
- **Tamaño real de buckets.** Con `1.97M` registros distribuidos en
  `2^64` hashes los buckets son pequeños y los `INSERT` van rápido. Si
  los datos colisionan (nombres muy repetitivos), los buckets crecen y
  el `CREATE INDEX` se vuelve dominante — también IO.
- **Compresión gzip del HDF5.** Cada lectura de slice descomprime. En
  cores lentos eso SUBE el porcentaje CPU. Vale la pena verificarlo.
- **GIL en `executemany`.** En CPython la transición Python→C en
  `sqlite3.executemany` libera el GIL durante el INSERT en C, pero
  reentra para la siguiente fila Python. Eso genera contención con
  threads concurrentes — relevante si en lugar de `ProcessPoolExecutor`
  alguien sugiere `ThreadPoolExecutor`.

## Cómo correr el benchmark

### Opción A — Reusar un signatures.h5 existente

Lo más rápido. Si ya corriste el pipeline antes y guardaste el
`_lsh_index/signatures.h5` (es lo que hace `DiskBasedLSHEngine` por
default), lo usas directamente:

```bash
python scripts/bench_lsh_indexing.py \
    --signatures /content/drive/work/_lsh_index/signatures.h5 \
    --bands 32 \
    --out /content/bench_lsh.csv \
    --report /content/bench_lsh.md
```

### Opción B — Partir de un DataFrame

Si no tienes el HDF5 a mano:

```bash
python scripts/bench_lsh_indexing.py \
    --df /content/df_preparado.parquet \
    --num-perm 128 --ngram 3 \
    --bands 32 \
    --out /content/bench_lsh.csv
```

Esto genera firmas en un `signatures.h5` temporal y las benchmarka.
**Costo extra:** ~6 min en 1.97M registros. Solo úsalo si no tienes
HDF5 previo — la generación de firmas NO se mide.

### Parámetros

| Flag | Default | Notas |
|---|---|---|
| `--signatures PATH` | — | HDF5 con dataset `"signatures"` shape `(N, num_perm)` uint64 |
| `--df PATH` | — | Parquet/CSV con columna `NOMBRE_LIMPIO` (alternativo) |
| `--num-perm` | 128 | Solo con `--df` |
| `--ngram` | 3 | Solo con `--df` |
| `--bands` | 32 | Número de bandas a medir. Debe dividir num_perm |
| `--chunk-size` | 50_000 | Igual al default de `DiskBasedLSHEngine` |
| `--out` | bench_lsh_results.csv | CSV por banda |
| `--report` | — | Reporte .md humano-legible |

## Cómo interpretar el resultado

El script imprime un **veredicto automático** al final:

```
======================================================================
VEREDICTO: <CPU dominates | IO dominates | Mixed / unclear>
  CPU promedio: XX.X%
  IO  promedio: XX.X%
  Tiempo total <N> bandas: <T>s

→ <recomendación operativa>
======================================================================
```

Criterios:

- **`CPU dominates` (avg CPU ≥ 40%)** → la Tarea 2.1 SÍ tiene sentido.
  Con 2 vCPU el speedup esperado es `1 + (cpu_pct/100) × (N-1)`. Si el
  CPU es 50%, eso es ~1.5×. Procede.
- **`IO dominates` (avg IO ≥ 75%)** → la Tarea 2.1 NO acelera nada
  significativo. Parquearla o reemplazarla por algo que sí ataque IO:
  SSD local en lugar de Drive, batch INSERT más grande, `PRAGMA
  cache_size` más alto.
- **`Mixed / unclear` (entre ambos)** → benchmark inestable o caso
  borderline. Re-correr 2-3 veces y promediar; si persiste, decisión
  judgment-call basada en costo del refactor vs el speedup marginal.

## Plantilla de reporte (rellenar tras correr)

```markdown
## Resultados del benchmark — <fecha>

**Entorno:** <Colab Pro / Colab Free / local>
**Storage:** <Google Drive / local SSD / EBS>
**CPU:** <2 vCPU / 4 vCPU / etc>
**RAM total:** <13 GB / 25 GB / etc>
**Dataset:** <N registros> de <fuente>

### Veredicto

- CPU promedio: __.__%
- IO  promedio: __.__%
- Tiempo total 32 bandas (secuencial): __ s
- Speedup esperado paralelizando con 2 workers: __ ×

### Decisión

- [ ] Proceder con Tarea 2.1 (paralelizar)
- [ ] Parquear Tarea 2.1 (replantear plan)
- [ ] Re-medir con corpus distinto

### Notas
- <observación 1>
- <observación 2>
```

## Otros hotspots a considerar (Tarea 2.3 ampliada)

Más allá de `_index_band`, el `first-run` reportó **L2_lsh = 70% del
tiempo total**. La indexación es solo PARTE de L2. El benchmark de
arriba no mide:

1. **Generación de firmas** (`_generate_signatures`, ~6 min en 1.97M).
   *Ya optimizado* por la Tarea 2.2 (cache MinHash persistente).
2. **Búsqueda de candidatos** (`_find_candidates_disk`). Es secuencial
   y consume SQLite intensivamente. Vale la pena profilear esta fase
   por separado con `py-spy record`:

   ```bash
   pip install py-spy
   py-spy record -o profile_find.svg --pid <PID_DEL_PROCESO> \
       --duration 60 --rate 100
   ```

3. **Bloqueo por NIT** (`enable_nit_blocking=True`). Complementa LSH
   pero también escribe a SQLite — comparte el bottleneck IO si lo hay.

## Lecciones del benchmark sintético

1. **Los planes deben validarse empíricamente antes de codear.** El
   plan original estimó 1.65× sin medir; el benchmark muestra 1.01×.
   Esto no es un error del autor del plan — es la naturaleza de
   estimaciones a priori. La regla es: **antes de un refactor con
   riesgo ALTO, exige medición**.
2. **SQLite serializa escrituras.** Cualquier estrategia que multiplique
   threads escribiendo al mismo SQLite no acelera; solo agrega lock
   contention. Si CPU domina, paralelizar requiere SQLite distintos por
   worker + merge final (lo que el plan sugería pero NO descontó del
   speedup proyectado).
3. **Profiling > intuición.** `py-spy` o `cProfile` durante 1 minuto en
   producción da más insight que 1 día de leer código.

## Referencias

- SQLite write performance: https://www.sqlite.org/faq.html#q19
- `ProcessPoolExecutor` y pickling: https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.ProcessPoolExecutor
- `py-spy` (sampling profiler): https://github.com/benfred/py-spy
- HDF5 chunking + compresión: https://docs.h5py.org/en/stable/high/dataset.html#chunked-storage
