# Deuda conocida: limpieza de razón social destruye nombres en modos no-AGRESIVO

**Estado:** defecto REAL, con causa raíz identificada y fix disponible, pero
**BLOQUEADO** porque corregirlo en aislamiento regresa la compuerta de calidad del
propio proyecto. Requiere recalibración validada sobre datos REALES antes de
aplicarse. No se incluye en la librería entregada.

---

## 1. El defecto

En los modos `CONSERVADOR` y `BALANCEADO` (este último es el **default** del
pipeline), el sufijo societario se convierte en tokens de una sola letra que el
filtro de stopwords reduce a basura, destruyendo el nombre:

| Entrada                          | Salida actual (BALANCEADO) | Esperado          |
|----------------------------------|----------------------------|-------------------|
| `Comercial Andina S.A.S.`        | `S S`                      | `COMERCIAL ANDINA`|
| `C.I. Flores de Colombia S.A.S.` | `C I S S`                  | `FLORES COLOMBIA` |
| `Almacenes Éxito S.A.`           | `EXITO S`                  | `ALMACENES EXITO` |
| `Bancolombia S.A.`               | `BANCOLOMBIA S`            | `BANCOLOMBIA`     |

Esto inyecta ruido y borra señal justo en el régimen **SIN_NIT**, que depende del
nombre. Es coherente con el F1 SIN_NIT bajo (~0.63 sobre GT sintético).

## 2. Causa raíz

La eliminación de sufijos legales (`legal_suffixes_patterns`) y el colapso de
siglas (`_clean_initials_and_symbols`) **solo se ejecutan en modo `AGRESIVO`**. En
los demás modos, `"S.A.S."` pasa directo por `non_alpha_regex` → `"S A S"`, y el
filtro de stopwords lo deja en `"S S"`.

Archivo: `src/record_linkage/processing/text.py`, método `_clean_name_impl`, rama
`else` (modos no-AGRESIVO).

## 3. Por qué NO está corregido en esta entrega

El fix es de 12 líneas y parece obviamente correcto. **Pero al medirlo, regresa la
compuerta de calidad del proyecto.** Evidencia empírica por aislamiento (mismo
seed, mismo dataset, único cambio = el fix):

| text.py                     | `test_quality_golden` | F1 sintético |
|-----------------------------|-----------------------|--------------|
| base (con el bug)           | **5 passed**          | ≥ 0.73       |
| con el fix de limpieza      | **2 failed**          | **0.714**    |

(`tests/test_quality_golden.py::test_f1_no_retrocede` exige F1 ≥ 0.73;
`test_recall_no_retrocede` también falla.)

La causa: el **blocking y el scoring están calibrados contra la limpieza actual
(con bug)**. Al limpiar bien, los puntajes y los buckets de blocking se desplazan,
y el recall cae por debajo del piso de la compuerta. No es que el fix sea malo —
es que **no se puede cambiar la limpieza sin recalibrar el resto del sistema.**

Las únicas dos formas de "hacer pasar" la compuerta con el fix puesto serían:
1. **Bajar el umbral** de la compuerta → fraude (mover la meta para tapar una
   regresión).
2. **Recalibrar contra el sintético** → circular (el GT sintético y la
   calibración están acoplados a la limpieza con bug; el número no es autoritativo).

Ninguna es aceptable. Por eso el fix queda documentado y bloqueado, no aplicado.

## 4. El fix (NO aplicar sin recalibración)

El parche está en `docs/_fix_limpieza_sufijos.patch` (adjunto). En esencia, en la
rama no-AGRESIVO de `_clean_name_impl`:

```python
else:
    # quitar sufijos legales y colapsar siglas ANTES de pasar a espacios
    text = self._remove_patterns(text, self.legal_suffixes_patterns)
    text = self._remove_patterns(text, self.legal_suffixes_patterns)  # 2x: anidados (SAS BIC)
    text = self._clean_initials_and_symbols(text)
    text = self.non_alpha_regex.sub(" ", text)
```

Verificado cualitativamente: elimina la basura de tokens de una letra y recupera
los nombres (ver tabla §1). Verificado cuantitativamente: **regresa el F1
sintético** (§3).

## 5. Remediación correcta (en este orden)

1. Aplicar el fix de limpieza (`_fix_limpieza_sufijos.patch`).
2. **Recalibrar** los umbrales de blocking y de scoring con la limpieza nueva.
3. **Validar sobre datos REALES etiquetados** (protocolo de la Fase 2: 2
   anotadores, κ ≥ 0.80), NO sobre el GT sintético. El sintético está acoplado a
   la limpieza con bug y no sirve como juez de este cambio.
4. Solo si el F1 SIN_NIT real **sube**, fijar el nuevo piso de la compuerta y
   mergear.

## 6. La lección (por qué esto importa más que el bug)

Este defecto, y el hecho de que su fix "obvio" regrese la única métrica
disponible, es **prueba concreta del problema central del proyecto**: sin datos
reales etiquetados no se puede saber si un cambio mejora o empeora. La intuición
("quitar basura del nombre tiene que ayudar") falló contra la medición. Y la
medición que existe (sintética) no es confiable para juzgarlo. El muro real sigue
siendo el mismo: **conseguir datos reales y etiquetadores humanos.**
