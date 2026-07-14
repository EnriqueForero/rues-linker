# Release v0.8.0 — Fase 0 del playbook: consolidación y blindaje

## Qué es

Primera fase del playbook de evolución, completa del lado del código y
validada con medición. **Cero cambio de comportamiento del pipeline** (el
baseline v0_9_0 se re-corrió verde 16/16 tras todos los cambios); todo lo
nuevo blinda al proyecto contra las clases de fallo del incidente
datasketch: deriva de dependencias, incoherencia de versión, caches de otro
esquema y percolación silenciosa.

## Hallazgo mayor corregido: el generador del pyproject estaba roto

La Celda A del notebook de publicación **regenera** el `pyproject.toml`
durante el build (el de Drive no viaja: está en `auto_generados`). Su lista
`DEPENDENCIAS` divergía del pyproject validado:

- **Faltaba `networkx`**, que importan `engine/clusterer.py` y
  `deduplication/strict.py` (el corazón del clustering). Una instalación
  limpia por pip habría fallado con ImportError en el primer uso.
- Contenía **dependencias fantasma** con 0 imports en `src/`: `unidecode`,
  `pydantic`, `pyyaml` (y extras propios con `jinja2`, `xlsxwriter`).
- Su extra `dev` **no incluía optuna ni plotly**: el CI de GitHub instala
  `.[dev]` y su paso de importabilidad recorre todos los submódulos
  (incluidos los shims de `optimization/`) → CI rojo garantizado tras la
  primera publicación.

El bloque quedó reescrito como **espejo exacto** del pyproject validado
(verificado por comparación de conjuntos: 13 dependencias runtime y 5 extras
idénticos), con las cotas nuevas de la F0.2.

## Contenido del zip (rutas relativas al repo en Drive)

- `pyproject.toml` — versión 0.8.0 + cotas de major: `scikit-learn<2`,
  `networkx<4`, `rapidfuzz<4` (datasketch<2.0 venía de 0.7.6).
- `CHANGELOG.md` — entrada [0.8.0] completa con la evidencia medida.
- `.gitignore` — añade `runs/` y `.ruff_cache/`.
- `src/record_linkage/__init__.py` — fallback de versión pasa de `"3.2.3"`
  al centinela `"0.0.0+sin.instalar"` (un fallback con pinta de versión real
  fue co-causa de la publicación incoherente de 0.7.6).
- `src/record_linkage/engine/lsh/cache.py` — la clave del cache MinHash
  ahora incluye `ds=<versión datasketch>;rl=<versión rues-linker>`: firmas
  de otro esquema jamás se reusan. Efecto único: los caches existentes se
  invalidan una vez y se recomputan.
- `tests/test_cache_version_key.py` (nuevo) — congela ese contrato.
- `tests/test_determinismo_contrato.py` (nuevo) — doble corrida de
  `deduplicate_auto` sobre dataset sintético inline → correlativas
  idénticas (ID_GRUPO fila a fila + SHA-256). Sin archivos: corre en
  cualquier clon limpio.
- `tests/test_canario_percolacion.py` (nuevo, slow ~150 s) — el clúster
  predicho máximo por régimen ≤ 2× el grupo verdadero máximo, sobre la ruta
  de producción y el GT de 12.427. Calibrado con medición: CON_NIT 18 ≤ 22,
  SIN_NIT 9 ≤ 18. El clúster de 563 del incidente lo habría disparado.
- `tests/test_matching_integration.py` — assert de versión → 0.8.0.
- `scripts/verificar_coherencia_version.py` (nuevo) — pyproject ==
  CHANGELOG tope == distribución instalada, y el fallback debe ser el
  centinela. Integrado en `ci.yml`.
- `constraints/runtime-validado.txt` (nuevo) — las 13 versiones exactas del
  entorno que validó esta versión. Uso opcional:
  `pip install -e . -c constraints/runtime-validado.txt`.
- `.github/workflows/ci.yml` — paso de coherencia de versión en el job test.
- `.github/workflows/nightly.yml` (nuevo) — cada noche instala dependencias
  frescas y corre la suite COMPLETA: detecta deriva de dependencias el día
  que ocurre, no el día que bloquea una publicación.
- `.github/workflows/deps-bump.yml` (nuevo) — mensual: upgrade dentro de los
  rangos → suite completa → si verde, PR con constraints regenerado.

## Pasos en Drive / Colab

1. Copie el contenido del zip a
   `/content/drive/MyDrive/ProColombia/record_linkage/`, **respetando las
   rutas relativas** y sobrescribiendo.
2. Reemplace los notebooks por las versiones **v3** entregadas
   (publicación y consolidador).
3. Colab: Entorno de ejecución → Reiniciar entorno. Luego:
   `!pip uninstall -y rues-linker`
4. Ejecute el notebook de publicación completo (A.5 incluida) y corra
   `publicar_profesional(solo_github=True)`.

## Qué esperar

- Instalación editable reporta **0.8.0**; Celda A.5 verde.
- El gate tarda ~5–6 min más que antes (canario ~2.5 min + determinismo
  ~1.5 min + baseline igual). Es el precio del blindaje, corre una vez por
  publicación.
- Los caches MinHash previos se recomputan una vez (clave nueva).
- Tras el push: en GitHub → Actions verá `CI`, `Nightly` y
  `Deps bump mensual`. Para que deps-bump pueda abrir PRs: Settings →
  Actions → General → "Allow GitHub Actions to create and approve pull
  requests".

## Validación realizada (medida, en este entorno)

- ruff 4/4 en el orden §18.7 sobre los 7 archivos Python tocados.
- Tests nuevos + contrato previo del cache + matching_integration:
  **39 passed** (177 s).
- Canario como test real: **1 passed** (156 s).
- Gate de no-regresión: **baseline 16/16** (164 s) tras TODOS los cambios.
- Coherencia de versión: ✅ 0.8.0 en todos los puntos.
- Wheel: `python -m build` OK, `twine check` **PASSED**, instalación en
  venv + import + versión ✅.
- Paridad generador↔pyproject: conjuntos idénticos (13 runtime, 5 extras).
- YAML de los 3 workflows: válido.

## Cierre del gate F0 (lo que queda, y es de su lado)

Publicar main con esta versión, ver CI verde en GitHub, borrar de Drive los
artefactos `runs/` y `build/` de la era 3.x (el build y el consolidado ya
los excluyen; borrarlos libera ~11 MB), y decidir TestPyPI → PyPI. Con eso
el gate F0 queda cerrado con acta y se abre la Fase 1 (API pública única,
v0.9.0) según el playbook.
