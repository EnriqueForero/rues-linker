# Notebooks oficiales de `rues-linker` (v0.11.0)

Suite minima que cubre todos los flujos de deduplicacion y record linkage.
Cada notebook sigue el mismo patron: **Celda A** (entorno, una vez por sesion),
**Celda A2** (definiciones) y **Celda B** (la unica que usted edita).

## ¿Cual notebook usar?

- Tengo **UNA base** y quiero encontrar duplicados (NIT + nombre)
  -> `01_deduplicar_una_base.ipynb` (basico, formulario)
- Tengo **DOS bases** y quiero saber que empresas estan en ambas
  -> `02_cruzar_dos_bases.ipynb` (intermedio)
- Tengo **3 o mas fuentes** y necesito el consolidado de produccion
  (trusted, checkpoints, manifiesto, auditoria)
  -> `03_produccion_multifuente.ipynb` (avanzado)
- Quiero deduplicar con **varias variables** (email, telefono, direccion...),
  activar la **corroboracion de veto de NIT (F3)** o medir **P/R/F1**
  -> `04_multicampo_y_evaluacion.ipynb` (experto; trae demo autocontenida)

## Instalacion

Los cuatro notebooks instalan solos la libreria (Celda A):
primero `pip install rues-linker @ git+https://github.com/EnriqueForero/rues-linker@v0.11.0` y, como respaldo,
modo editable desde `/content/drive/MyDrive/ProColombia/record_linkage`.

## Contrato de datos

El motor trabaja con `NIT` y `RAZON_SOCIAL` (y opcionales `CIUDAD`, `EMAIL`,
`TELEFONO`, `DIRECCION`). Sus archivos NO deben renombrarse: en cada notebook
usted declara como se llaman SUS columnas y el notebook hace el mapeo, forzando
el NIT como texto para no perder ceros a la izquierda.

## Reglas de operacion

- Corridas grandes: use el `03` (checkpoints reanudables en Drive por `etiqueta`).
- Resultados: `.xlsx` multi-hoja si toda tabla cabe en 1M de filas; si no, `.csv.gz`.
- Trazabilidad: el `03` escribe `manifiesto_corrida.json` (version, huellas de
  insumos, parametros y conteos).

Estos notebooks reemplazan a: `fuente_unica`, `Cruce_universal_de_dos_bases`,
`rues_linker_universal`, `Nearshoring_tres_fuentes`, `produccion_4fuentes` y
`prueba_datos_reales_v0_7_5`.

## 07 · Deduplicar importadores por razón social + país

`07_deduplicar_importadores_razon_social_pais.ipynb`

Para una base **sin identificador**: destinatarios de exportación, padrones de
compradores, listados de contrapartes. El empalme es por **razón social y
país**, con el país como bloqueo duro y canonizado contra un catálogo ISO-3166
declarado (no por similitud de cadenas: `TURQUÍA`/`TÜRKIYE` y
`CHEQUIA`/`REPÚBLICA CHECA` no se parecen, y `GUINEA`/`GUINEA-BISSAU` sí se
parecen y son países distintos).

Entrega una **correlativa** —cada nombre y país originales con el nombre y
país finales asignados— más la evidencia para juzgarla: precisión por banda
sobre muestra revisable, recall del bloqueo medido por fuerza bruta,
invariantes que detienen el notebook si fallan, y sensibilidad al umbral.

Dos diccionarios editables en celdas propias: el catálogo de países (Celda C)
y las listas de términos a limpiar (Celda D). Son la palanca principal de
calidad: en esta base, el IDF aprendido del corpus da MENOS peso a la marca
`ZELECTA` (6,37) que al genérico `IMPORTADORA` (5,96), así que la lista de
genéricos tiene que ser un dato declarado.

Resultados de la corrida de referencia (211.949 registros, 267 s, 2,6 GiB):
99.914 importadores, precisión ponderada 0,966 sobre 160 asignaciones
revisadas a mano, recall del bloqueo 1,00.
Ver [`docs/ANALISIS_IMPORTADORES.md`](../docs/ANALISIS_IMPORTADORES.md).
