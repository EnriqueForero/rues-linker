# Configuración de credenciales — Colab Secrets, env, archivo

Este pipeline conecta a Snowflake. **Nunca** se incluyen credenciales en el
código fuente, en notebooks committeables ni en variables globales del kernel.

El módulo `record_linkage.config.credentials` busca las credenciales en este
orden y se queda con la primera fuente válida:

1. **Google Colab Secrets** (recomendado para Colab)
2. **Variables de entorno** (recomendado para CI/CD)
3. **Archivo `config.json` local** (último recurso, en `.gitignore`)

---

## Opción 1: Google Colab Secrets

En Colab, abre el panel lateral izquierdo y selecciona el icono de llave
(🔑 "Secrets"). Agrega los siguientes secretos. Asegúrate de activar el
toggle "Notebook access" en cada uno.

| Nombre del secret      | Valor                          |
|-----------------------|--------------------------------|
| `SNOWFLAKE_ACCOUNT`   | `mi-cuenta.us-east-1`          |
| `SNOWFLAKE_USER`      | `mi_usuario`                   |
| `SNOWFLAKE_PASSWORD`  | `mi_contraseña`                |
| `SNOWFLAKE_WAREHOUSE` | `MI_WH`                        |
| `SNOWFLAKE_DATABASE`  | `MI_DB`                        |
| `SNOWFLAKE_SCHEMA`    | `MI_SCHEMA`                    |
| `SNOWFLAKE_ROLE`      | (opcional) `MI_ROLE`           |

Uso en el notebook:

```python
from record_linkage.config import get_snowflake_credentials

creds = get_snowflake_credentials()  # carga desde Colab Secrets automáticamente
import snowflake.connector
conn = snowflake.connector.connect(**creds.to_connector_kwargs())
```

**Ventaja**: los secretos no se filtran ni con `print(globals())` ni con
checkpoints, y no quedan en el `.ipynb` exportado.

---

## Opción 2: Variables de entorno

Útil para CI/CD, Docker o cuando se corre fuera de Colab.

```bash
export SNOWFLAKE_ACCOUNT="mi-cuenta.us-east-1"
export SNOWFLAKE_USER="mi_usuario"
export SNOWFLAKE_PASSWORD="mi_contraseña"
export SNOWFLAKE_WAREHOUSE="MI_WH"
export SNOWFLAKE_DATABASE="MI_DB"
export SNOWFLAKE_SCHEMA="MI_SCHEMA"
export SNOWFLAKE_ROLE="MI_ROLE"  # opcional

python scripts/ejecutar_produccion.py --workspace /data/rl --iteracion IT8
```

En GitHub Actions, configurar como repository secrets y exponerlos en el job:

```yaml
- name: Run pipeline
  env:
    SNOWFLAKE_ACCOUNT: ${{ secrets.SNOWFLAKE_ACCOUNT }}
    SNOWFLAKE_USER: ${{ secrets.SNOWFLAKE_USER }}
    SNOWFLAKE_PASSWORD: ${{ secrets.SNOWFLAKE_PASSWORD }}
    SNOWFLAKE_WAREHOUSE: ${{ secrets.SNOWFLAKE_WAREHOUSE }}
    SNOWFLAKE_DATABASE: ${{ secrets.SNOWFLAKE_DATABASE }}
    SNOWFLAKE_SCHEMA: ${{ secrets.SNOWFLAKE_SCHEMA }}
  run: python scripts/ejecutar_produccion.py ...
```

---

## Opción 3: Archivo `config.json` local (último recurso)

**Riesgo:** si lo committeas a Git por error, exposición de credenciales en
historial. El `.gitignore` del proyecto bloquea `config.json` y `.env`, pero
nada impide forzar el commit con `git add -f`.

```json
{
  "snowflake": {
    "account": "mi-cuenta.us-east-1",
    "user": "mi_usuario",
    "password": "mi_contraseña",
    "warehouse": "MI_WH",
    "database": "MI_DB",
    "schema": "MI_SCHEMA",
    "role": "MI_ROLE"
  }
}
```

Colocar en la raíz del repo o pasar la ruta explícitamente:

```python
from pathlib import Path
from record_linkage.config import get_snowflake_credentials

creds = get_snowflake_credentials(config_path=Path("/secure/snowflake.json"))
```

---

## Migrar desde credenciales hardcoded (acción inmediata)

Si tu notebook anterior tenía credenciales en código (típico patrón de
`account = "..."; user = "..."; password = "..."`), **rótalas hoy** en
Snowflake (`ALTER USER ... SET PASSWORD = ...`) y migra al método 1 o 2 de
arriba. Después de rotarlas:

1. Verifica que ni el notebook ni los commits anteriores tengan la versión
   nueva:
   ```bash
   git log -p | grep -i "password\|account" | head
   ```
2. Si las credenciales viejas están en el historial de Git, considera
   reescribir el historial con `git filter-repo` o crear un repo nuevo
   (lo más limpio).

---

## Verificación

Tras configurar el método elegido, ejecuta:

```python
from record_linkage.config import get_snowflake_credentials
creds = get_snowflake_credentials()
print(f"✅ Cargado: cuenta={creds.account}, usuario={creds.user}")
# NUNCA imprimir creds.password
```

El logger del módulo informa de qué fuente cargó las credenciales (nivel INFO).
