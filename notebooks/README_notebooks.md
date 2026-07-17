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
