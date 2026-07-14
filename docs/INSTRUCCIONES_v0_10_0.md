# Instrucciones — Release v0.10.0 (Fase 2 del playbook)

Motor multicampo tipado con esquema declarativo. **No toca el comportamiento
de producción RUES** (el baseline 16/16 y `dedupe()`/`link()` permanecen
intactos, contrato F2.8).

---

## 1. Qué contiene este ZIP

Overlay sobre el repositorio `rues-linker`. Estructura espejo: descomprima en
la raíz del repo y los archivos caen en su lugar.

**Archivos nuevos (9):**
- `src/record_linkage/matching/campos.py` — sistema de tipos, `CampoSpec`, `EsquemaCampos`, `PoliticaFaltante`, presets.
- `src/record_linkage/matching/motor_bloqueo.py` — bloqueo componible + medición PC/RR.
- `src/record_linkage/matching/motor_multicampo.py` — motor de score declarativo + clustering con veto.
- `src/record_linkage/testing/gt_multicampo.py` — generador de GT sintético v3.
- `src/record_linkage/testing/__init__.py` — paquete de testing.
- `tests/test_comparadores_tipos.py` — unit + property-based (hypothesis).
- `tests/test_motor_multicampo.py` — esquema, normalizadores, bloqueo, salvaguardas.
- `tests/test_baseline_multicampo.py` — no-regresión + gate F2.
- `tests/data/baseline_multicampo.json` — baseline congelado.

**Archivos modificados (6):**
- `src/record_linkage/matching/comparators.py` — añadidos `FechaDelta`, `GeoHaversine`, `NumericoRelativo`.
- `src/record_linkage/matching/normalizadores.py` — normalizadores por tipo/locale (incluye el fix de sufijos multi-token).
- `src/record_linkage/__init__.py` — exporta la API multicampo (28 símbolos).
- `pyproject.toml` — versión `0.10.0`.
- `CHANGELOG.md` — entrada `[0.10.0]`.
- `tests/test_matching_integration.py` — assert de versión `0.10.0`.

Más el notebook de publicación `Publicacion_GitHub_PyPI_Record_Linkage_v5.ipynb`.

---

## 2. Aplicar (dos rutas)

### Ruta A — Colab con notebook consolidador (recomendada)
Igual que en releases anteriores: suba el ZIP, use el consolidador para
regenerar el repo, y publique con `Publicacion_GitHub_PyPI_Record_Linkage_v5.ipynb`.
El notebook lee la versión del `pyproject.toml` automáticamente (no hay que
tocar la versión en el notebook).

### Ruta B — Overlay directo sobre el repo local
```bash
cd /ruta/al/repo/rues-linker
unzip -o release_v0_10_0_fase2.zip
pip install -e .
```

---

## 3. Verificar antes de publicar (gate F2, lado suyo)

```bash
# 3.1 · ruff 4/4 sobre lo nuevo
ruff check --fix . && ruff format . && ruff check . && ruff format --check .

# 3.2 · Batería F2 (46 pruebas)
pytest tests/test_comparadores_tipos.py tests/test_motor_multicampo.py \
       tests/test_baseline_multicampo.py -q

# 3.3 · Contrato F2.8: baseline RUES de producción intacto
pytest tests/ -k "baseline and not multicampo" -q      # 16/16 debe seguir verde

# 3.4 · Coherencia de versión
python scripts/verificar_coherencia_version.py           # → 0.10.0 en todos los puntos

# 3.5 · Build + twine
python -m build && python -m twine check dist/*
```

**Criterios del gate F2 (deben cumplirse todos):**
- Baseline RUES 16/16 intacto.
- ≥ 8 tipos de campo con tests (hay 11 definidos).
- PC de bloqueo ≥ 0.98 y F1 global ≥ 0.85 sobre el GT multicampo.
- Cero controles negativos mal fusionados.

Cifras medidas en esta entrega (GT v3, seed=42): **PC = 1.0000 · F1 = 0.9441 ·
P = 1.0000 · R = 0.8940 · negativos = 0**. Es un punto ANCLA; se sube en F3.

---

## 4. Uso mínimo de la API nueva

```python
import pandas as pd
from record_linkage import (
    esquema_multicampo_completo, evaluar_esquema, clusters_desde_decisiones,
)
from record_linkage.matching.motor_bloqueo import (
    BloqueoComponible, LlaveExacta, LSHTexto,
)

df = pd.DataFrame({...})  # con columnas NIT, RAZON_SOCIAL, TELEFONO, EMAIL, DIRECCION, CIUDAD
esquema = esquema_multicampo_completo()
bloqueo = BloqueoComponible([
    LlaveExacta("NIT"), LlaveExacta("EMAIL"), LlaveExacta("TELEFONO"),
    LSHTexto("RAZON_SOCIAL", umbral=0.35, permutaciones=64, ngram=3),
])
res = evaluar_esquema(df, esquema, bloqueo)
grupos = clusters_desde_decisiones(len(df), res.decisiones, respetar_vetos=True)
df["ID_GRUPO"] = grupos
```

Para esquemas propios, declare sus columnas con `CampoSpec` y `EsquemaCampos`;
`esquema.validar(df)` da un preflight accionable si faltan columnas.

**Nota medida (no opinada):** el tipo `GEO` existe y funciona, pero añadirlo
al esquema de referencia baja la precisión sobre el GT v3 (dos sedes urbanas
distintas quedan cerca). Úselo cuando la geolocalización distinga entidades
(p. ej. domicilios residenciales), no sedes urbanas.

---

## 5. No abrir Fase 3 hasta cerrar Fase 2

Publicado 0.10.0 con CI verde y el gate F2 cumplido de su lado, queda cerrada
la Fase 2. La Fase 3 (v0.11.0) sube el ancla de precisión/recall y formaliza
las restricciones de clúster (ya anticipadas con el `cannot-link` de esta fase).
