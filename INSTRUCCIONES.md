# Fix v0.7.6 — pin `datasketch < 2.0`

## Causa raíz (probada con paridad entero a entero contra su Colab)

`datasketch 2.0.0` (major release publicado entre la captura del baseline
v0.9.0 y hoy) cambia el esquema de firmas MinHash: el mismo input con el
mismo `seed` produce `hashvalues` distintas a las de 1.x. Eso altera el
banding LSH y el grafo de candidatos; el régimen SIN_NIT se sobre-fusiona
(F1 global 0.563 → 0.250; tp=20852, fp=124054, fn=1221 — los mismos enteros
de su error). El código del repo está sano: con datasketch 1.10.0 reproduce
el baseline al tercer decimal. `pyproject.toml` declaraba `datasketch>=1.6`
sin cota superior; Colab instalaba 2.0.0 y el gate (correctamente) bloqueaba.

## Contenido de este paquete

- `pyproject.toml` — versión 0.7.6 + pin `datasketch>=1.6,<2.0` (comentado).
- `CHANGELOG.md` — nueva entrada [0.7.6] con la evidencia medida.
- `tests/test_matching_integration.py` — assert de versión 0.7.5 → 0.7.6.
- Aparte del zip: `Publicacion_GitHub_PyPI_Record_Linkage_v2.ipynb`
  (VERSION='0.7.6', pin en la lista de dependencias que regenera pyproject,
  y nueva Celda A.5 de verificación de coherencia y saneo) y
  `Consolidador_Codigo_y_Docs_record_linkage_v2.ipynb` (excluye build/,
  dist/, runs/ y rues_linker.egg-info del consolidado).

## Pasos en Drive / Colab

1. Copie los tres archivos del zip a las MISMAS rutas dentro de
   `/content/drive/MyDrive/ProColombia/record_linkage/`, sobrescribiendo.
2. Reemplace sus dos notebooks por las versiones `_v2` entregadas.
3. En Colab: Entorno de ejecución → Reiniciar entorno. Luego, en una celda:
   `!pip uninstall -y rues-linker datasketch`
   (elimina cualquier datasketch 2.0 residual del runtime).
4. Ejecute el notebook de publicación desde el inicio, incluida la nueva
   Celda A.5 (valida coherencia de versión, limpia artefactos derivados y
   verifica datasketch < 2.0 con mensaje accionable si algo falla).
5. NO regenere `tests/data/baseline_v0_9_0.json`: con el pin, el pipeline
   vuelve a producir exactamente las métricas congeladas.

## Qué esperar

- Instalación editable reporta `0.7.6`.
- Celda A.5: versión coherente, datasketch <2.0, saneo listado.
- `pytest -m "not canario"`: verde, incluido
  `test_baseline_v0_9_0.py` (global F1=0.563, P=0.401).
- La publicación procede a GitHub/PyPI.

## Validación ya realizada localmente (repo reconstruido de su consolidado)

- Paridad entero a entero con su fallo de Colab bajo datasketch 2.0.0 y
  restauración exacta del baseline bajo 1.10.0 (mismo código, mismos datos).
- Gate de baseline: 16/16 verde (101 s). Suite rápida: 464 verdes; los
  fallos restantes son fixtures de datos excluidos del consolidado, que sí
  existen en su Drive.
- `ruff check` y `ruff format --check` limpios sobre el archivo tocado;
  TOML validado.

## Deuda menor detectada (no bloqueante, para un sprint futuro)

La clave del cache persistente de firmas MinHash (Sprint 0.8.2) incluye
`num_perm/ngram/seed` y una muestra del contenido, pero NO la versión de
datasketch. Con el pin es inocuo; si algún día se migra a 2.x, añadir la
versión de la librería a `compute_key` evita reuso de firmas entre esquemas.

## Migración futura a datasketch 2.x (tarea explícita, no ahora)

Requerirá: levantar el pin en rama dedicada, regenerar el baseline con
`scripts/medir_baseline_v0_9_0.py`, re-evaluar la percolación SIN_NIT
(posible recalibración de `lsh_threshold`/umbrales) y documentar en
CHANGELOG el cambio de métricas.
