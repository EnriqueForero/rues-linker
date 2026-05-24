"""
utils.logger — record_linkage_pipeline

Componentes:
    - class CustomLogger  (origen: notebook celda [110])
    - function setup_logger  (origen: notebook celda [124])

NOTA: Lógica de negocio preservada exactamente como en el notebook
fuente. Solo se agregan imports, docstring de módulo y se eliminan
directivas de Jupyter (%%time, !pip, etc.). Ver MIGRATION_LOG.md.
"""

from __future__ import annotations

import logging
import sys
from collections import Counter
from datetime import datetime

import pytz


class CustomLogger:
    """
    Logger personalizado V2.0 - Robusto y Unificado.

    Esta versión mejorada:
    - Centraliza toda la configuración del sistema de logs.
    - Limpia handlers preexistentes para eliminar duplicados de raíz.
    - Utiliza la zona horaria de Colombia ('America/Bogota') de forma consistente.
    - Mantiene la funcionalidad de añadir información de memoria a los logs críticos.

    Notas de diseño (v2.0.1):
        La bandera `_logging_configured` se modela como atributo de clase (no
        variable global de módulo). Esto evita el `NameError` que ocurría al
        usar `global _LOGGING_CONFIGURED` sin inicialización a nivel de
        módulo, y mantiene un único punto de verdad para el estado de
        configuración del root logger.
    """

    # Bandera de configuración del root logger. Se modifica una sola vez,
    # la primera vez que se instancia un CustomLogger en el proceso.
    _logging_configured: bool = False

    def __init__(self, name: str, level: int = logging.INFO):
        """
        Al instanciar, obtiene un logger y se asegura de que la configuración
        global se haya ejecutado una sola vez.
        """
        # 1. Configurar el sistema globalmente, pero solo la primera vez que se llama
        self._setup_global_logging_once()

        # 2. Obtener el logger específico para este módulo/clase
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)

        # 3. Asegurar que este logger no propague mensajes si ya hemos configurado la raíz
        # Esto es una doble seguridad para evitar duplicados en algunos entornos complejos.
        self.logger.propagate = False

        # Contadores para resúmenes
        self.log_counts: Counter[str] = Counter()

    @classmethod
    def _setup_global_logging_once(cls) -> None:
        """
        Configura el logger raíz de manera definitiva.
        Esta función es el núcleo de la solución contra los logs duplicados.

        Idempotente: el atributo de clase `_logging_configured` garantiza que
        el cuerpo se ejecute una sola vez por proceso, sin importar cuántos
        CustomLogger se instancien.
        """
        if cls._logging_configured:
            return

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        # LIMPIEZA TOTAL: Eliminar CUALQUIER handler preexistente (de Colab, IPython, etc.)
        if root_logger.hasHandlers():
            # Iteramos sobre una copia de la lista de handlers para poder modificarla
            for handler in root_logger.handlers[:]:
                root_logger.removeHandler(handler)
                handler.close()  # Cierra el handler para liberar recursos.

        # Definir un Formatter profesional con la zona horaria de Colombia.
        class ColombiaFormatter(logging.Formatter):
            """Formatter personalizado para usar la hora de Bogotá."""

            colombia_tz = pytz.timezone("America/Bogota")

            def formatTime(self, record, datefmt=None):
                dt_colombia = datetime.fromtimestamp(record.created, tz=self.colombia_tz)
                if datefmt:
                    return dt_colombia.strftime(datefmt)
                return dt_colombia.strftime("%Y-%m-%d %H:%M:%S")

        # Crear y añadir nuestro handler ÚNICO Y DEFINITIVO a la raíz.
        handler = logging.StreamHandler(sys.stdout)
        formatter = ColombiaFormatter("%(asctime)s | %(name)-25s | %(levelname)-8s | %(message)s")
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

        cls._logging_configured = True
        root_logger.info("Sistema de Logging configurado exitosamente. Usando hora de Colombia.")

    def _log_with_memory(self, level_name: str, message: str, *args, **kwargs):
        """
        Método interno que añade info de memoria y delega el logging.
        Mantenemos esta funcionalidad intacta.
        """
        level = level_name.upper()
        self.log_counts[level] += 1

        # Añadir info de memoria para logs importantes
        if level in ["WARNING", "ERROR", "CRITICAL"]:
            try:
                # Import diferido para evitar ciclo memory <-> logger.
                from .memory import MemoryManager

                mem_info = MemoryManager.get_memory_status()
                message += f" [Memoria: {mem_info['used_gb']:.1f}GB/{mem_info['total_gb']:.1f}GB]"
            except Exception:
                pass  # No fallar si el monitoreo de memoria falla

        # Delegar el logging al logger de Python subyacente
        self.logger.log(logging.getLevelName(level), message, *args, **kwargs)

    # --- Métodos públicos para logging (interfaz sin cambios) ---
    def info(self, message: str, *args, **kwargs):
        self._log_with_memory("INFO", message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs):
        self._log_with_memory("WARNING", message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs):
        self._log_with_memory("ERROR", message, *args, **kwargs)

    def debug(self, message: str, *args, **kwargs):
        self._log_with_memory("DEBUG", message, *args, **kwargs)

    def get_summary(self) -> dict[str, int]:
        """Obtener resumen de logs emitidos."""
        return dict(self.log_counts)


def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger
