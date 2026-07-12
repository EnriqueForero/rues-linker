# Régimen SIN_NIT — calibración y límites

**Estado:** mejorado (v0.7.4) · **F1 0.217 → 0.645** · perfil `deduplication_sin_nit_conservador`

## Resumen

El régimen **SIN_NIT** (registros sin número de identificación tributaria —
típicamente importadores extranjeros) era la deuda de calidad #1. En v0.7.4
se recalibró contra ground truth y se **casi triplicó el F1** (0.217 → 0.645)
manteniendo precision >0.90. El recall (0.50) refleja un **límite de datos**,
no de calibración.

## Solución aplicada (v0.7.4)

Usar el perfil **`deduplication_sin_nit_conservador`** (ya existía, recalibrado)
en lugar del estándar para datos sin NIT:

```python
deduplicate_unified(
    df_input=df_sin_nit, col_nit="NIT", col_name="RAZON_SOCIAL",
    mode="AGRESIVO", profile="deduplication_sin_nit_conservador",
)
```

Parámetros clave recalibrados: `min_name_similarity=0.78`, `score_threshold=0.78`
(óptimo F1 hallado por barrido contra el GT).

## Evidencia medida (2342 registros SIN_NIT, 604 grupos)

| Configuración | P | R | F1 |
|---|---|---|---|
| deduplicate_unified estándar (baseline previo) | 0.123 | 0.921 | **0.217** |
| sin_nit_conservador nsim=0.75 (pre-v0.7.4) | 0.944 | 0.313 | 0.470 |
| **sin_nit_conservador nsim=0.78 (v0.7.4)** | **0.907** | **0.501** | **0.645** |
| nsim=0.80 | 0.944 | 0.313 | 0.470 |

## Por qué el recall se queda en ~0.50 (límite de datos)

Inspección de grupos reales revela dos fuentes de variación intra-grupo que
ningún umbral resuelve sin destruir precision:

1. **Typos tipo OCR** en los nombres: `NENOVA`/`NNEOVA`/`NENOV`,
   `GARDENING`/`GARDSNING`, `CORPORATION`/`CODPORATION`. Son ediciones de
   1-2 caracteres que bajan el `token_set_ratio` por debajo del umbral.
2. **Romanización coreana inconsistente** en ciudades: PUSAN=BUSAN,
   TAEGU=DAEGU, KWANGJU=GWANGJU, SEÚL=SEUL=SEOUL, GYEONGGI DO=GYEONGGI-DO.

Además, la **ciudad no discrimina**: solo hay ~7 ciudades reales y cada una
contiene 80-105 grupos distintos. Por eso usar CIUDAD como feature de matching
EMPEORA el resultado (probado: F1 0.549→0.189) — añade ruido sin señal.

Bajar el umbral para capturar los typos sube recall pero colapsa precision
(grupos distintos que comparten first-token genérico se fusionan: BAEKSHIN
tiene 5 grupos distintos). El barrido completo muestra que **ningún umbral
supera F1~0.65** — es la frontera de Pareto con estos datos.

## Recomendación operativa

- **CON_NIT** (mayoría de empresas colombianas): usar el perfil estándar o
  `produccion_calibrada`. F1≈0.96. Listo para producción.
- **SIN_NIT** (importadores): usar `deduplication_sin_nit_conservador`.
  F1=0.645 con precision 0.91 — cuando agrupa, acierta 9 de cada 10. Deja
  ~50% de duplicados sin unir, lo cual es el trade-off correcto cuando un
  falso positivo (fusionar dos empresas distintas) cuesta más que un duplicado.
- **NUNCA** usar el perfil estándar en datos SIN_NIT (sobre-fusiona, F1 0.22).
  `deduplicate_unified` ahora emite UserWarning si detecta mezcla de regímenes.

## Mejoras futuras posibles (más allá de calibración)

1. **Normalizar romanización coreana** (tabla PUSAN→BUSAN, etc.) antes del
   matching. Recuperaría parte del recall perdido por ciudades inconsistentes.
2. **Similitud a nivel de carácter** (Jaro-Winkler) para tolerar typos OCR
   sin aflojar el match de tokens. Requiere extender el scorer.
3. **Bloqueo por país** si el campo existiera limpio (hoy vacío en el GT).

