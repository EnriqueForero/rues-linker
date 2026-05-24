# Protocolo de etiquetado de la base de verdad (ground truth)

**Versión:** 1.0 · **Fecha:** 2026-05-23 · **Proyecto:** rues-linker

Este documento define cómo construir una base de verdad etiquetada con calidad
suficiente para medir el F1 real del sistema y calibrar pesos. Sin esto, toda
métrica de calidad es una conjetura con decimales.

---

## 1. Qué se etiqueta: pares, no registros

La unidad de etiquetado es el **par de registros**, no el registro individual.
Cada par recibe una etiqueta binaria:

- `1` (MATCH): los dos registros son la **misma entidad real** (misma empresa).
- `0` (NO_MATCH): son entidades **distintas**.

Un tercer valor `?` (DUDOSO) se permite durante el etiquetado pero **debe
resolverse** antes de cerrar el dataset (ver §6). No se admiten dudosos en la
versión final.

> Por qué pares y no registros: las métricas (precision, recall, F1) se calculan
> sobre pares. Etiquetar 5.000 registros en grupos genera automáticamente todos
> los pares intra-grupo (positivos) e inter-grupo (negativos).

---

## 2. Cuántos pares se necesitan

El tamaño se deriva del margen de error deseado al 95% de confianza
(`n = 1.96² · 0.25 / E²`):

| Margen de error | Pares por clase | Uso |
|---|---|---|
| ±5% | ~385 | Iteración rápida, primera medición |
| ±3% | ~1.068 | Producción defendible |
| ±2% | ~2.401 | Publicación / claims formales |
| ±1% | ~9.604 | Investigación / benchmark de referencia |

**Lo difícil son los pares POSITIVOS** (mismo grupo), porque para medir recall
necesitas muchos. Cuántos registros etiquetar para obtener N pares positivos
depende del tamaño de grupo promedio:

| Tamaño grupo medio | Pares positivos/grupo | Grupos para 1.000 positivos |
|---|---|---|
| 2 | 1 | ~1.000 |
| 3 | 3 | ~333 |
| 5 | 10 | ~100 |

### Recomendación por nivel

- **Mínimo viable (1ª medición):** 300-500 registros etiquetados en grupos.
  Da ~150-400 pares positivos. Suficiente para medir el régimen sin-NIT (Corea)
  por primera vez.
- **Sólido (producción):** 3.000-5.000 registros estratificados de las fuentes
  reales. La estratificación importa más que el volumen bruto.

---

## 3. Forma del archivo: una columna por variable

El ground truth es un CSV con **una columna por cada variable disponible**,
aunque esté vacía para algunos registros. Esto permite medir el aporte marginal
de cada variable (como se midió que CIUDAD aporta +0.067 de F1 en el exhaustivo
pero daña en Corea).

Esquema obligatorio:

```
ID_REGISTRO,ID_GROUP,NIT,RAZON_SOCIAL,CIUDAD,TELEFONO,DIRECCION,EMAIL,FUENTE,ANOTADOR,NOTA
```

| Columna | Obligatoria | Descripción |
|---|---|---|
| `ID_REGISTRO` | Sí | Identificador único de la fila (no se reutiliza). |
| `ID_GROUP` | Sí | Identificador del grupo. Registros con el mismo `ID_GROUP` son la misma empresa. |
| `NIT` | Sí (puede ir vacío) | NIT si la fuente lo tiene; vacío si no (régimen tipo Corea). |
| `RAZON_SOCIAL` | Sí | Nombre tal como aparece en la fuente (sin limpiar). |
| `CIUDAD` | Recomendada | Ciudad/municipio. Vacío si no aplica. |
| `TELEFONO` | Opcional | Teléfono normalizado o crudo. |
| `DIRECCION` | Opcional | Dirección. |
| `EMAIL` | Opcional | Correo. |
| `FUENTE` | Sí | Origen del registro (RUES, DIAN, IMPORTACIONES, …). |
| `ANOTADOR` | Sí | Quién etiquetó (para medir acuerdo inter-anotador). |
| `NOTA` | Opcional | Justificación de casos difíciles. |

> Regla: nunca pre-limpiar `RAZON_SOCIAL` en el ground truth. El sistema debe
> recibir el dato crudo, igual que en producción.

---

## 4. Estratificación: cubre los casos difíciles a propósito

Una muestra aleatoria está dominada por casos fáciles (nombres idénticos o
totalmente distintos), que no informan sobre el comportamiento en los bordes.
La muestra debe **sobre-representar** deliberadamente los casos límite:

1. **Variantes de escritura** del mismo nombre (NENOVA CO LTD / NENOVA CO., LTD).
2. **Nombres casi genéricos** (X CORPORATION vs Y CORPORATION).
3. **Prefijo/intermediario compartido** (ELITE EXPORTS Y/O X vs Y/O Z).
4. **Mismo nombre, distinta ciudad** (¿filial o empresa distinta?).
5. **Con NIT vs sin NIT** para la misma empresa (cross-régimen).
6. **Sufijos confundibles** (S.A. vs S.A.S., LTD vs LTDA).
7. **Cambios de denominación histórica** (mismo NIT, nombre distinto).
8. **Caracteres especiales / acentos / mayúsculas** (SEOUL/SEUL/SEÚL).

Meta sugerida: ~40% casos difíciles (categorías 1-8), ~60% casos normales.

---

## 5. Reglas de decisión (criterio de etiquetado)

Para que dos anotadores coincidan, las reglas deben ser explícitas:

- **MATCH (1):** misma persona jurídica real. El NIT idéntico (validado) es
  prueba fuerte de match. Sin NIT, exige evidencia convergente: nombre
  esencialmente igual salvo escritura + al menos otra señal (ciudad, dirección).
- **NO_MATCH (0):** entidades distintas, aunque compartan tokens genéricos,
  ciudad o un intermediario común. "ELITE EXPORTS Y/O NENOVA" y "ELITE EXPORTS
  Y/O ARES3" son NO_MATCH: el importador común no las hace la misma empresa.
- **Intermediario / Y/O:** la identidad está en la empresa nombrada **después**
  del "Y/O", no en el exportador que se repite.
- **Filial vs matriz:** por defecto, filiales en países/ciudades distintas con
  NIT distinto son NO_MATCH, salvo que el objetivo de negocio sea consolidar
  grupos empresariales (decidir y documentar ANTES de etiquetar).
- **Dato insuficiente:** si no hay forma de decidir con la información
  disponible, marcar `?` y escalar (no adivinar).

---

## 6. Control de calidad: acuerdo inter-anotador

**Dos anotadores independientes** etiquetan al menos el 20% de los pares en
común (sin verse). Se calcula el coeficiente **Cohen's kappa**:

| Kappa | Interpretación | Acción |
|---|---|---|
| > 0.80 | Acuerdo casi perfecto | Ground truth confiable. |
| 0.60-0.80 | Acuerdo sustancial | Aceptable; revisar discrepancias. |
| 0.40-0.60 | Acuerdo moderado | Revisar reglas §5, re-etiquetar. |
| < 0.40 | Acuerdo pobre | El ground truth es ruido. NO usarlo. |

Los pares en desacuerdo se resuelven por un tercer anotador o consenso, y la
discrepancia alimenta una aclaración de las reglas. Un kappa bajo significa que
las métricas que saques de ese ground truth son **mentiras con decimales**.

---

## 7. Flujo de trabajo recomendado

1. Muestrear registros de las fuentes reales con estratificación (§4).
2. Generar pares candidatos. Útil: usar el propio sistema en modo permisivo
   para proponer pares (los positivos predichos + una muestra de negativos),
   así se etiquetan los pares informativos y no millones de negativos obvios.
   Existe `scripts/generar_pares_para_etiquetar.py` como punto de partida.
3. Dos anotadores etiquetan en paralelo el 20% común + el resto repartido.
4. Calcular kappa. Si < 0.60, volver a §5.
5. Resolver dudosos y desacuerdos.
6. Consolidar a `ID_GROUP` (clausura transitiva de los pares MATCH).
7. Guardar como `ground_truth_<dominio>_<fecha>.csv` con el esquema §3.
8. Medir con `medir_contra_ground_truth()` del notebook de producción.

---

## 8. Qué NO hacer

- No etiquetar solo casos fáciles (infla artificialmente el F1).
- No pre-limpiar los nombres (oculta el trabajo real del sistema).
- No usar el ground truth de calibración también como test final (sobreajuste).
  Reserva un 20% como holdout que solo se mide al final.
- No dejar dudosos en la versión final.
- No confiar en un solo anotador para casos difíciles.
