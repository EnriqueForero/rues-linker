# Medición real (RUES) — Hito H3 / Fase 2

> 🔴 **ESTADO: PENDIENTE — NO HAY MEDICIÓN REAL TODAVÍA.**
> Este documento es una **plantilla**. No contiene ni una sola cifra de F1 sobre
> datos reales porque esa medición **aún no se ha ejecutado**. Mientras las
> tablas de abajo digan «PENDIENTE», la Fase 2 está **abierta** y el proyecto
> **no** es defendible como "talla mundial", por bueno que sea el código.
> El único insumo que falta no es código: es (1) un extracto del **RUES real**
> y (2) **dos personas** que etiquen. La herramienta ya está lista (ver runbook).

---

## Por qué esto es la fase que importa

Las métricas publicadas hoy (F1 ≈ 0.84–0.91) son sobre **ground truth sintético**
generado con `seed=42`. Miden que el sistema es coherente consigo mismo, no que
acierte sobre la realidad sucia del RUES (typos, abreviaturas, NITs faltantes,
fusiones, razones sociales que comparten nombre). Hasta tener un F1 sobre datos
reales con κ reportado, los criterios #17/#18/#19 de la autoevaluación PyPI
siguen en ~2/10 y arrastran el promedio global. Esta es la fase que los mueve.

---

## Runbook turnkey (4 pasos + κ)

Toda la herramienta existe y está auditada/probada. Cuando tenga el extracto del
RUES real (`rues_real.csv`, columnas `NIT`, `RAZON_SOCIAL`, `CIUDAD`, `FUENTE`):

```bash
# 1) Muestra estratificada (NO aleatoria pura) de 50k–100k registros.
python scripts/muestrear_rues_para_gt.py \
    --input rues_real.csv --n 50000 \
    --col-name RAZON_SOCIAL --col-nit NIT --col-ciudad CIUDAD \
    --salida muestra_gt.csv

# 2) ~1000 pares candidatos estratificados por score para etiquetar.
python scripts/generar_pares_para_etiquetar.py \
    --input muestra_gt.csv --col-nit NIT --col-name RAZON_SOCIAL \
    --salida pares_para_etiquetar.csv

# 3) DOS personas etiquetan, por separado, la columna MISMO_GRUPO (SI/NO).
#    Deben solapar >=20% de los pares. Genera dos CSV: A y B.
#    → Medir acuerdo inter-anotador ANTES de fusionar:
python scripts/medir_kappa.py \
    --labeler-a etiquetas_A.csv --labeler-b etiquetas_B.csv \
    --report docs/kappa_reporte.md
#    Compuerta intermedia: κ >= 0.80. Si no, resolver desacuerdos en sesión y,
#    si sigue bajo, REESCRIBIR EL MANUAL de etiquetado (no el sistema).

# 4) Medir F1/P/R sobre los pares etiquetados (consenso), por estrato y régimen.
python scripts/medir_con_ground_truth.py \
    --input muestra_gt.csv --pares-etiquetados pares_consenso.csv \
    --col-nit NIT --col-name RAZON_SOCIAL \
    --reporte docs/MEDICION_REAL.md --errores-csv errores_reales.csv
```

Protocolo completo de etiquetado: [`PROTOCOLO_GROUND_TRUTH.md`](PROTOCOLO_GROUND_TRUTH.md).

---

## Resultados — RELLENAR tras ejecutar

### Metadatos de la corrida
| Campo | Valor |
|---|---|
| Fecha de la medición | _PENDIENTE_ |
| Origen del extracto RUES | _PENDIENTE_ |
| N registros muestreados | _PENDIENTE_ |
| N pares etiquetados | _PENDIENTE_ |
| Anotador A / Anotador B | _PENDIENTE_ |
| **Cohen's κ** | **_PENDIENTE_** |

### Métricas globales (vs etiquetas humanas)
| Métrica | Valor |
|---|---:|
| Precision | _PENDIENTE_ |
| Recall | _PENDIENTE_ |
| **F1** | **_PENDIENTE_** |
| TP / FP / FN / TN | _PENDIENTE_ |

### Por régimen
| Régimen | n | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| CON_NIT | _PEND._ | _PEND._ | _PEND._ | _PEND._ |
| SIN_NIT | _PEND._ | _PEND._ | _PEND._ | _PEND._ |

### Por estrato
| Estrato | n | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| alta_confianza | _PEND._ | _PEND._ | _PEND._ | _PEND._ |
| frontera | _PEND._ | _PEND._ | _PEND._ | _PEND._ |
| potencial_fn | _PEND._ | _PEND._ | _PEND._ | _PEND._ |
| (otros) | _PEND._ | _PEND._ | _PEND._ | _PEND._ |

---

## Decisión (se toma con el F1 real, no con esperanza)

| F1 sobre RUES real | Decisión |
|---|---|
| **≥ 0.90** | El motor sirve. Ir a Fase 4 (endurecer y publicar con cifras reales). |
| **0.80 – 0.90** | Identificar los 5 modos de falla (de `errores_reales.csv`). Fase 3 + recalibración los ataca. |
| **< 0.80** | Problema estructural. La arquitectura de la Fase 3 (DuckDB / Splink) deja de ser opcional. |

**Compuerta dura de la Fase 2:** este documento contiene un F1 real **y** un κ
reportado. Hasta entonces, no está cerrada.
