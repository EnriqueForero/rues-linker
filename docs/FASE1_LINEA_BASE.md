# Fase 1 — Línea base medida contra ground truth sintético

**Fecha:** 2026-05-23 · **Versión:** v2.14.0 · **Dataset:** `data/ground_truth/ground_truth_grande.csv`

---

## El ground truth

Generado por `scripts/generar_ground_truth_grande.py` (determinista, `seed=42`).

| Propiedad | Valor |
|---|---|
| Registros | 12.427 |
| Grupos (entidades reales) | 3.486 |
| Tamaño de grupo | min 1, máx 11, media 3,6 |
| Régimen CON_NIT | 10.085 registros |
| Régimen SIN_NIT | 2.342 registros (estilo Corea) |
| Variables | NIT, RAZON_SOCIAL, CIUDAD, TELEFONO, DIRECCION, EMAIL |
| Casos frontera negativos | 43 grupos (intermediario + genérico) |

> ⚠️ **Es un ground truth SINTÉTICO.** Mide cómo el sistema maneja los tipos de
> variación programados (typos, sufijos, formatos de NIT, intermediarios). NO
> sustituye etiquetado humano sobre datos reales. F1 alto aquí es necesario
> pero no suficiente para producción.

---

## Línea base medida

### Régimen CON_NIT (10.085 registros)

| Configuración | F1 | Precision | Recall |
|---|---|---|---|
| Solo nombre + NIT | 0.961 | 0.972 | 0.950 |
| **+ ciudad** | **0.974** | 0.974 | 0.974 |

Sólido. El NIT ancla la identidad. La ciudad añade +0.013. Sobre submuestra,
el aporte marginal de ciudad y teléfono es de solo +0.01 cada uno — porque el
NIT ya hace casi todo el trabajo. **Lección: cuando hay un identificador fuerte,
las variables auxiliares aportan poco.**

### Régimen SIN_NIT (2.342 registros) — el hallazgo incómodo

| Configuración | F1 | Precision | Recall |
|---|---|---|---|
| Perfil estándar | 0.549 | 0.393 | 0.908 |
| Perfil conservador+IDF (como estaba) | 0.436 | 0.939 | 0.284 |
| Mejor combinación hallada (blend 0.1, th 0.65) | ~0.574 | 0.424 | 0.890 |

**Esto corrige un autoengaño anterior.** El perfil `deduplication_sin_nit_conservador`
(IDF blend=0.5, score_threshold=0.80) "se veía bien" por inspección cualitativa
sobre los 818 registros de Corea, pero medido contra un ground truth grande y
diverso resulta **demasiado agresivo**: recall colapsa a 0.284. Estaba
sobreajustado al caso particular de Corea.

El cuello de botella real no era el IDF sino los umbrales altos
(`score_threshold=0.80`, `min_name_similarity=0.75`) que matan el recall.
Bajándolos, el recall sube pero la precisión cae. **Hay un techo real en el
régimen sin-NIT** porque sin un identificador fuerte, nombre+ciudad no alcanza
para discriminar de forma fiable.

---

## Conclusiones accionables

1. **El NIT vale ~0.40 de F1.** La diferencia entre CON_NIT (0.97) y SIN_NIT
   (~0.57) cuantifica el valor de tener un identificador fuerte. Para datos sin
   NIT, conseguir CUALQUIER identificador adicional (teléfono, dirección, NIT
   parcial) es más valioso que afinar el scorer de nombres.

2. **El perfil conservador sin-NIT necesita recalibración.** Los valores
   calibrados sobre Corea (818 regs) no generalizan. Pendiente: recalibrar
   `score_threshold`, `min_name_similarity` e `idf_weight_blend` contra este
   ground truth (o mejor, contra uno real). Mientras tanto, NO se cambió el
   perfil entregado porque cambiar umbrales sin un ground truth REAL solo
   movería el sobreajuste de un dataset sintético a otro.

3. **La inspección cualitativa engaña.** Lo que "se ve bien" en 818 registros
   puede tener recall de 0.28 medido contra verdad conocida. Esta es la
   justificación empírica de por qué la Fase 1 (medir) era prioritaria.

---

## Próximo paso crítico

Lo medido aquí es sobre datos SINTÉTICOS. El salto de valor real es repetir
esta medición sobre un ground truth REAL etiquetado por humanos
(ver `docs/PROTOCOLO_GROUND_TRUTH.md`). Solo entonces los números serán
defendibles para producción. La calibración de pesos (Optuna) debe esperar a
ese ground truth real para no optimizar contra ruido sintético.
