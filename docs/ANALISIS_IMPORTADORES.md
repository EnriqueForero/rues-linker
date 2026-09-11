# Deduplicación de la base de importadores por razón social y país

Informe de la corrida de referencia · base `empresas_importadoras.csv`
(211.949 registros de destinatarios de exportación colombianos).
Notebook: [`notebooks/07_deduplicar_importadores_razon_social_pais.ipynb`](../notebooks/07_deduplicar_importadores_razon_social_pais.ipynb).

---

## 1. Resultado en una línea

**211.949 registros → 99.914 importadores distintos (−52,9 %).** La
concentración del valor FOB en el top-100 pasa de **22,4 % a 35,2 %**: la base
sin deduplicar subestima a la mitad qué tan concentrado está el comercio.

| | Antes | Después |
|---|---:|---:|
| Entidades (razón social × país) | 211.891 | 99.856 |
| FOB en el top 10 | 5,32 % | 10,17 % |
| FOB en el top 100 | 22,40 % | 35,15 % |
| FOB en el top 1.000 | 51,95 % | 69,32 % |
| Grafías de país | 529 | 204 |

Cifras sin los 58 registros de destinatario reservado (§5).

---

## 2. Qué se hizo

Empalme por **razón social + país**, con el país como bloqueo duro: dos
registros solo se unen si el país canónico coincide exactamente y la
similitud de nombre supera 0,84.

```
saneamiento → canonización de país → normalización de nombre
   → bloqueo LSH por partición de país → score multicampo (rues-linker)
   → componentes conexas → cobertura por estrellas → registro consolidado
```

La librería `rues-linker 0.21.0` aporta la normalización (`normalizar_nombre`,
152 sufijos legales ES + EN), el bloqueo (`LSHTexto`, MinHash vectorizado), el
IDF (`construir_idf`), el motor de decisión (`EsquemaCampos`,
`evaluar_esquema`) y el clustering con restricciones
(`clusters_desde_decisiones`). El notebook añade, por el punto de extensión
`CampoSpec(comparador=...)`, dos cosas que el caso exigía y la librería no
traía: un comparador de razones sociales que mezcla informatividad de tokens
con similitud de cadena, y un refinamiento por cobertura que corta el
encadenamiento transitivo.

Corrida de referencia: **267 s** y **2,6 GiB** de RSS pico sobre 14,1 millones
de pares candidatos. Cabe en Colab Free con holgura.

---

## 3. Calidad del emparejamiento

### 3.1 Precisión — 160 asignaciones revisadas a mano

| Banda de similitud | Asignaciones | Precisión estricta | Precisión amplia |
|---|---:|---:|---:|
| 0,84 – 0,88 | 6.915 | 0,825 | 0,925 |
| 0,88 – 0,92 | 4.223 | 0,950 | 1,000 |
| 0,92 – 0,96 | 3.515 | 0,850 | 0,900 |
| 0,96 – 1,00 | 41.952 | 1,000 | 1,000 |
| **Ponderada** | **56.605** | **0,966** | **0,985** |

"Estricta" cuenta los casos dudosos como error. La muestra es aleatoria
estratificada (40 por banda, semilla 42) y se exporta en la hoja
`MUESTRA_REVISION` para que cualquiera repita el conteo.

### 3.2 Recall del bloqueo — medido por fuerza bruta, no estimado

El bloqueo decide qué pares llegan a compararse. Los que no pasan son
invisibles para todas las métricas posteriores: un bloqueo malo produce un
resultado que *parece* impecable. Por eso se midió comparando **todos** los
pares de tres particiones completas:

| País | Nombres | Pares totales | Pares verdaderos | PC (recall) | RR |
|---|---:|---:|---:|---:|---:|
| GTM | 2.681 | 3.592.540 | 301 | **1,000** | 0,942 |
| NLD | 2.630 | 3.457.135 | 478 | **1,000** | 0,956 |
| DEU | 1.683 | 1.415.403 | 230 | **1,000** | 0,975 |

**Esta medición cambió la configuración.** El ajuste que parecía razonable
—64 permutaciones, umbral 0,35— recuperaba solo entre el **67 % y el 81 %** de
los pares verdaderos, sin ningún síntoma visible: menos candidatos, corrida
más rápida, métricas internas iguales. Un cuarto de los empalmes correctos
se perdía en silencio.

### 3.3 Invariantes — se verifican en cada corrida y detienen el notebook

Las nueve pasan: una fila de salida por fila de entrada, ningún grupo cruza
dos países, toda asignación cumple el umbral declarado, cada grupo tiene
exactamente un nombre final, el FOB se conserva (diferencia relativa 1,5·10⁻¹⁶).

---

## 4. Las tres fallas que hubo que corregir

No son hipotéticas: las tres estaban en la primera versión de este pipeline y
salieron al revisar resultados, no al leer código.

**1. Imán genérico.** `INTERNATIONAL` absorbió 157 razones sociales; `MQE`,
214; `COMERCIAL`, 133. Causa: si "A está contenido en B" cuenta como
evidencia, cualquier nombre corto se traga todo lo que lo mencione.
Corrección: la contención exige compartir al menos un token no genérico y
suficientemente distintivo.

**2. El IDF aprendido no distingue marca de genérico.** Medido en esta base:
`IMPORTADORA` (737 nombres) pesa 5,96 de IDF y `ZELECTA` (490 nombres) pesa
6,37 — la marca pesa *menos* que la palabra genérica, porque la frecuencia de
una marca crece con el número de variantes de la misma empresa. Corrección:
la lista de genéricos es un dato declarado y editable (Celda D), no una
inferencia del corpus. Es la misma doctrina que los `LOCALES` de la librería.

**3. Encadenamiento transitivo.** Las componentes conexas son single-linkage:
si `a≈b` y `b≈c`, unen `a` con `c` aunque no se parezcan. Produjo grupos de
200 empresas distintas encadenadas por prefijos genéricos. Corrección:
cobertura por estrellas, que garantiza que **todo miembro está a ≤ 0,16 de su
nombre final** — exactamente lo que la correlativa afirma.

Y una cuarta, de calibración: el umbral inicial de 0,88 era demasiado
estricto. Revisar 40 pares del tramo 0,84–0,88 mostró **92,5 % de aciertos**:
se estaban descartando cerca de 7.000 empalmes correctos. Bajarlo a 0,84 es
la decisión mejor respaldada de toda la configuración.

---

## 5. Hallazgos sobre los datos (no sobre el método)

**El 20,5 % del valor FOB no tiene destinatario identificable.** 53 registros
con razón social `"0"` concentran **USD 42.797 millones**. Es el patrón típico
de destinatario reservado en oro, carbón y petróleo. Quedan marcados como
`sin_nombre_utilizable` y **nunca se fusionan entre sí**: unirlos inventaría
una empresa gigante inexistente. Cualquier ranking, participación de mercado o
análisis de concentración que ignore esta quinta parte del valor está mal.

**76 grafías del campo "país de destino final" no son países** sino zonas
francas colombianas (`ZONA FRANCA PERMANENTE…`, `ZFP…`, `ZFPE…`): 397 filas y
USD 3.297 millones (1,58 %). Mezclarlas con destinos reales contamina
cualquier lectura por mercado.

**El campo país tenía 529 grafías para 203 países.** El 58,3 % de las filas
cambió de valor de país al canonizar. Los pares que ninguna similitud de
cadenas resuelve —`TURQUÍA`/`TÜRKIYE`, `CHEQUIA`/`REPÚBLICA CHECA`,
`YIBUTI`/`DJIBOUTI`, `COSTA DE MARFIL`/`CÔTE D'IVOIRE`— son la razón de que el
catálogo sea declarado y no inferido. Y los que *sí* se parecen —`GUINEA` /
`GUINEA ECUATORIAL` / `GUINEA-BISSAU`, `CONGO` / `REPÚBLICA DEMOCRÁTICA DEL
CONGO`— son países distintos: el fuzzy matching los habría unido.

**La dispersión de grafías es masiva en los grandes.** `ES WINDOWS`: 36
grafías, USD 1.878 millones. `DILLON GAGE`: 13 grafías, y la mayor por sí sola
es apenas el **45 %** del total consolidado — en la base cruda esa empresa
aparece con menos de la mitad de su tamaño real.

---

## 6. Lo que este resultado NO es

- **No resuelve personas jurídicas, resuelve grupos comerciales por destino.**
  `BARRY CALLEBAUT USA` y `BARRY CALLEBAUT CANADA` quedan juntos; también
  `LATAM AIRLINES GROUP` con `LATAM AIRLINES ECUADOR` y `KOREA EAST-WEST
  POWER` con `KOREA SOUTH-EAST POWER`. Es consecuencia directa de tratar la
  geografía como ruido —lo que a su vez permite unir `NETAFIM QUITO` con
  `NETAFIM ECUADOR S.A.`—. Se apaga con `GEOGRAFIA_ES_RUIDO = False`, y ese
  es el modo de error dominante de la banda 0,92–0,96 (4 de 40 revisadas).
- **No une empresas entre países.** Por diseño: el país es variable de
  empalme. `INTEROCEAN COAL SALES` aparece siete veces, una por destino. La
  columna `ID_EMPRESA_GLOBAL` las une, pero solo por coincidencia **exacta**
  del nombre normalizado.
- **Los consolidadores de carga se quedan con su clientela.**
  `X PRESS SHAPEWEAR LL ‹cliente›` cae en el grupo de la marca (49 grafías).
  El destinatario declarado ante la DIAN *es* el consolidador, así que el
  resultado es defendible, pero si le interesa el cliente final no sirve.
- **La precisión de 0,966 es una estimación con 160 observaciones**, no un
  censo. El intervalo de confianza al 95 % sobre la banda peor medida
  (0,84–0,88, n=40, p=0,825) va de 0,67 a 0,93. Para cerrarlo hacen falta más
  etiquetas, no más código.

---

## 7. Reproducir y recalibrar

```
notebooks/07_deduplicar_importadores_razon_social_pais.ipynb
  Celda A  entorno            Celda B  parámetros      ← lo que se edita
  Celda C  catálogo de países Celda D  listas de limpieza
  Celda E  motor              F ejecutar · G auditar · H exportar
```

Para recalibrar: cambie **un** parámetro, corra, y vuelva a contar la muestra
de `MUESTRA_REVISION`. La hoja `SENSIBILIDAD` muestra, sin volver a correr
nada, cuántas fusiones añade o quita cada umbral:

| umbral | pares fusionados | vs. defecto |
|---:|---:|---:|
| 0,80 | 60.261 | +27.753 |
| 0,82 | 50.853 | +18.345 |
| **0,84** | **32.508** | **0** |
| 0,88 | 15.115 | −17.393 |
| 0,92 | 9.976 | −22.532 |

---

## 8. Método

Fellegi, I. & Sunter, A. (1969). *A Theory for Record Linkage*. JASA 64(328),
1183–1210. — Spärck Jones, K. (1972). *A statistical interpretation of term
specificity and its application in retrieval*. Journal of Documentation 28(1).
— Winkler, W. (1990). *String comparator metrics and enhanced decision rules
in the Fellegi-Sunter model of record linkage*. — Wagstaff, K. & Cardie, C.
(2000). *Clustering with instance-level constraints*. ICML. — Christen, P.
(2012). *Data Matching*. Springer.
