# Fase 3 — Análisis build‑vs‑adopt (DuckDB / Splink)

**Paquete:** `rues-linker` v0.7.5 · **Fecha:** 2026‑05‑30
**Naturaleza:** análisis de decisión. **NO cierra la decisión** — la cierra el F1 real de la Fase 2.

---

## Para qué sirve este documento (y para qué NO)

La Fase 3 es una **reacción** al número de la Fase 2. Como ese número no existe, este documento **no decide** rehacer vs adoptar: prepara la decisión para que sea inmediata el día que tenga el F1 sobre datos reales —en particular el **F1 SIN_NIT real**, que es donde se juega todo. Aquí están los hechos actuales de cada opción, los ejes de comparación y una matriz de decisión llaveada al F1. Léalo como el mapa que se usa cuando llegue el dato, no como la ruta ya tomada.

---

## El sistema actual (hechos medidos, no afirmados)

De las fases previas, con medición directa:

- **Motor:** LSH (MinHash) sobre **SQLite**, scoring vectorizado, clustering con `scipy.sparse.connected_components` (~300 MB para 2M nodos). Tras Fase 1, columnas de texto en `string[pyarrow]` (−64% RAM medido).
- **Calibración:** pesos **a mano** (name 0.65, nit 0.20, phonetic 0.15) + umbrales + un post‑procesador `matcher`. **No** hay aprendizaje de parámetros.
- **Métricas (solo GT sintético):** F1 global 0.873 (CON_NIT **0.951**, SIN_NIT **0.629**); con matcher 0.908. A 20k: LSH ~24s, 2.8M pares candidatos.
- **Escala probada:** hasta ~37k. 2M end‑to‑end **sin medir**.
- **Tamaño:** ~33.6k líneas, 99 módulos, 529 tests, Apache‑2.0, CI/CD.
- **Cuello de velocidad conocido:** SQLite ≈ 98.5% del tiempo de LSH.

Traducción honesta: el sistema **ya resuelve CON_NIT** (0.95) y **flaquea en SIN_NIT** (0.63). La aguja de la calidad vive en SIN_NIT.

---

## Las alternativas (hechos actuales, verificados)

### Splink 4 — el estándar de facto
- Splink 4 ya fue liberado; enlaza un millón de registros en un portátil en alrededor de un minuto usando DuckDB. El backend DuckDB ahora está totalmente paralelizado.
- Su algoritmo se basa en el modelo de Fellegi‑Sunter, no requiere datos de entrenamiento (aprendizaje no supervisado), con ajustes por frecuencia de términos y diagnósticos interactivos.
- Adopción institucional fuerte y reciente: la Oficina Australiana de Estadística (ABS) usó Splink para el National Linkage Spine de 2024 y planea usarlo en el control de calidad del Censo 2026; un panel impulsado por Splink ganó el Civil Service Award 2025 a la excelencia en entrega; usado por ONS, UK Health Security Agency, Princeton, Stanford.
- Benchmark independiente (Robin Linacre, feb 2025): presenta resultados deduplicando un conjunto de 7 millones de filas con el backend DuckDB por defecto, presentándose como el tool libre más rápido para deduplicación grande por al menos un orden de magnitud.
- **⚠️ El hecho que reorienta la decisión:** Splink no está diseñado para enlazar una sola columna que contiene un "bag of words", por ejemplo una tabla con una sola columna de nombre de empresa y ningún otro detalle. Rinde mejor con **varias columnas poco correlacionadas** (nombre, fecha, ciudad…).

### recordlinkage (J535D165) y dedupe
- `recordlinkage`: toolkit modular de linkage/deduplicación en Python; sólido pero con menos tracción y empuje actual que Splink.
- `dedupe`: basado en **active learning** (etiquetado interactivo); útil, pero exige etiquetado humano para entrenar —lo mismo que usted está evitando.

### DuckDB "a secas"
No es un linker; es el **motor** columnar sobre el que Splink corre. Migrar el LSH de rues‑linker de SQLite a DuckDB atacaría el cuello del 98.5% **sin** cambiar el método. Es una opción intermedia barata si la decisión fuera solo de velocidad —pero la velocidad no es el problema medido (la calidad SIN_NIT sí).

---

## El choque estructural que nadie ha nombrado

El régimen donde rues‑linker sufre es **SIN_NIT**: registros sin identificador fiable, donde el match descansa esencialmente en **razón social** (+ a veces ciudad). Eso es **casi exactamente** el caso que Splink dice que **no** maneja bien: pocas columnas, una de ellas un nombre tipo "bag of words". Fellegi‑Sunter acumula evidencia a partir de **múltiples campos independientes** (nombre + fecha + ciudad + email…); con uno o dos, su ventaja se diluye.

**Implicación incómoda:** adoptar Splink probablemente **arrasaría en CON_NIT** (que usted ya resuelve al 0.95) y **podría flaquear en SIN_NIT por la misma razón estructural que rues‑linker** —no por mala ingeniería, sino por falta de señal. Adoptar la herramienta del estado del arte **no garantiza** arreglar su punto débil. Lo que lo arreglaría —en cualquier motor— es **enriquecer con más campos**: dirección, fechas de constitución, nombres de representante legal, código CIIU de actividad. Sin más señal, ni Splink ni rues‑linker harán magia con un nombre solo.

Esto es exactamente por qué el F1 SIN_NIT real decide todo: dice si su problema es de **motor** (entonces adoptar/migrar ayuda) o de **datos/señal** (entonces ninguna librería lo salva sin enriquecer).

---

## La pregunta que el build‑vs‑adopt obliga a hacerse

Usted mantiene **33.6k líneas** de motor propio (LSH, scoring, clustering, calibración a mano) que, en buena parte, **reimplementan lo que Splink da validado, más rápido y no supervisado, gratis**. El diferenciador genuino de rues‑linker **no** es el motor —es la **lógica colombiana específica**: normalización de NIT con dígito de verificación, limpieza de razón social, manejo de sufijos societarios (S.A.S., LTDA.). Esa lógica es valiosa y Splink no la tiene.

Eso abre una **tercera vía** que suele ganar: **híbrido**. Usar Splink (DuckDB + Fellegi‑Sunter + escala + diagnósticos) como motor, y alimentarlo con las **features colombianas** de rues‑linker (NIT_OK normalizado, razón social limpia, sufijo, ciudad) como columnas de comparación. Se queda con lo único que de verdad es suyo y delega lo demás en código de grado gubernamental, ya validado y un orden de magnitud más rápido.

---

## Matriz de decisión (se activa con el F1 SIN_NIT real)

| F1 SIN_NIT real | Lectura | Decisión Fase 3 |
|---|---|---|
| **≥ 0.90** | El motor propio funciona, incluso en lo difícil | **No adoptar.** Migrar SQLite→DuckDB solo si la escala 2M lo exige (Fase 1 dejó esto en su Colab). Ir a Fase 4. |
| **0.80 – 0.90** | Funciona pero con modos de falla concretos | **Recalibrar primero** (Fellegi‑Sunter/EM **no necesita** GT etiquetado; ataca los pesos a mano). Considerar **híbrido** si la recalibración no cierra la brecha. |
| **< 0.80** | Problema estructural | **Decisión de arquitectura obligatoria.** Evaluar: (a) **híbrido** Splink+features colombianas, o (b) **enriquecer datos** (dirección/fechas/representante/CIIU) —porque puede ser falta de señal, no de motor. |
| (cualquiera) | Velocidad insuficiente a 2M | Migrar el blocking a **DuckDB** (ataca el 98.5%) o adoptar Splink por el backend. |

---

## Lo que NO recomiendo

- **No** reescribir el motor "a lo Splink" desde cero a mano: si va a adoptar el método, adopte **la librería**, que está validada por gobiernos y mantenida. Reimplementar Fellegi‑Sunter usted mismo repetiría el error de construir en vez de adoptar.
- **No** migrar a DuckDB "porque es lo moderno": la velocidad no es su problema medido. Hágalo solo si la escala 2M real lo obliga.
- **No** tomar ninguna de estas decisiones **sin el F1 real**. Todo lo de arriba es condicional a un número que aún no existe.

---

**Nivel de confianza: alto (≈88%) en el análisis; nulo en la decisión, porque no hay decisión que tomar sin el F1.** Los hechos del estado del arte están verificados con fuentes de 2024‑2025 y citados. La incertidumbre del 12% es honesta: (1) el F1 SIN_NIT real podría sorprender (quizá el motor propio es mejor de lo que el sintético sugiere, o peor); (2) cuánto ayudaría el enriquecimiento de campos a SIN_NIT es una hipótesis razonada, no medida. La decisión build‑vs‑adopt **sigue bloqueada** en el mismo lugar que la Fase 2: necesita el número, y el número necesita datos reales y dos etiquetadores.
