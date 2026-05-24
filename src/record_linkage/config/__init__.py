"""record_linkage.config — Configuración central del proyecto."""

from .credentials import SnowflakeCredentials, get_snowflake_credentials
from .paths import Rutas
from .settings import Config

__all__ = [
    "Config",
    "Rutas",
    "SnowflakeCredentials",
    "get_snowflake_credentials",
]
