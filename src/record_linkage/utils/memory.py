"""
utils.memory — record_linkage_pipeline

Componentes:
    - class MemoryManager  (origen: notebook celda [110])
    - class AdaptiveMemoryManager  (origen: notebook celda [110])
    - function memoria_disponible  (origen: notebook celda [85])
    - function limpiar_memoria  (origen: notebook celda [85])
    - function mostrar_memoria  (origen: notebook celda [85])

NOTA: Lógica de negocio preservada exactamente como en el notebook
fuente. Solo se agregan imports, docstring de módulo y se eliminan
directivas de Jupyter (%%time, !pip, etc.). Ver MIGRATION_LOG.md.
"""

from __future__ import annotations

import gc
from typing import Any

import pandas as pd
import psutil


class MemoryManager:
    """Gestor proactivo de memoria para Google Colab."""

    @staticmethod
    def get_memory_status() -> dict[str, float]:
        """
        Versión CORREGIDA que retorna todas las claves necesarias
        para evitar KeyErrors en otras partes del sistema.
        """
        memory = psutil.virtual_memory()
        process = psutil.Process()

        # Calcular memoria del proceso en MB
        process_mb = process.memory_info().rss / (1024**2)

        return {
            "total_gb": memory.total / (1024**3),
            "available_gb": memory.available / (1024**3),
            "used_gb": (memory.total - memory.available) / (1024**3),
            # <--- CORRECCIÓN 1: Se entrega la clave 'memory_percent'.
            "memory_percent": memory.percent,
            "process_mb": process_mb,
            # <--- CORRECCIÓN 2: Se entrega la clave 'process_memory_gb'.
            "process_memory_gb": process_mb / 1024,
        }

    @staticmethod
    def check_memory_availability(required_gb: float = 2.0) -> bool:
        status = MemoryManager.get_memory_status()
        return status["available_gb"] >= required_gb

    @staticmethod
    def optimize_memory():
        collected = gc.collect()
        if (
            hasattr(pd, "_libs")
            and hasattr(pd._libs.lib, "_checknull")
            and hasattr(pd._libs.lib._checknull, "clear")
        ):
            pd._libs.lib._checknull.clear()
        status_after = MemoryManager.get_memory_status()
        return {
            "objects_collected": collected,
            "memory_freed_mb": collected * 0.01,
            "available_gb_after": status_after["available_gb"],
        }

    @staticmethod
    def monitor_and_warn(logger: Any | None = None):
        status = MemoryManager.get_memory_status()
        critical_threshold = globals().get("MEMORY_CRITICAL_THRESHOLD_GB", 10.0)
        warning_threshold = globals().get("MEMORY_WARNING_THRESHOLD_GB", 8.0)
        if status["used_gb"] > critical_threshold:
            message = (
                f"🚨 MEMORIA CRÍTICA: {status['used_gb']:.1f}GB usados "
                f"({status['memory_percent']:.1f}%). Liberando memoria..."
            )
            if logger:
                logger.error(message)
            else:
                print(message)
            MemoryManager.optimize_memory()
        elif status["used_gb"] > warning_threshold:
            message = (
                f"⚠️ Advertencia de memoria: {status['used_gb']:.1f}GB usados "
                f"({status['memory_percent']:.1f}%)"
            )
            if logger:
                logger.warning(message)
            else:
                print(message)

    @staticmethod
    def estimate_dataframe_memory(df: pd.DataFrame) -> float:
        return df.memory_usage(deep=True).sum() / (1024**3)

    @staticmethod
    def can_fit_in_memory(df: pd.DataFrame, safety_factor: float = 1.5) -> bool:
        required_gb = MemoryManager.estimate_dataframe_memory(df) * safety_factor
        return MemoryManager.check_memory_availability(required_gb)


class AdaptiveMemoryManager:
    """Gestor adaptativo de memoria para ajustar parámetros dinámicamente."""

    def __init__(self, warning_threshold_gb: float = 8.0, critical_threshold_gb: float = 9.0):
        """
        Inicializar con thresholds configurables.

        Args:
            warning_threshold_gb: Umbral de advertencia en GB
            critical_threshold_gb: Umbral crítico en GB
        """
        self.warning_threshold = warning_threshold_gb * 1024**3
        self.critical_threshold = critical_threshold_gb * 1024**3
        self.original_config = {}
        # Import diferido para evitar ciclo memory <-> logger.
        from .logger import CustomLogger

        self.logger = CustomLogger(
            "AdaptiveMemoryManager"
        )  # Usar setup_logger en lugar de CustomLogger

    def monitor_and_adapt(self, config: dict[str, Any]) -> dict[str, Any]:
        """Monitorear memoria y adaptar configuración si es necesario."""
        if not self.original_config:
            self.original_config = config.copy()

        mem = psutil.virtual_memory()
        used_gb = (mem.total - mem.available) / (1024**3)

        if mem.available < self.critical_threshold:
            self.logger.warning(
                f"Memoria crítica: {used_gb:.1f}GB usados. Activando modo emergencia"
            )
            return self._emergency_mode(config)
        elif mem.available < self.warning_threshold:
            self.logger.warning(f"Memoria alta: {used_gb:.1f}GB usados. Reduciendo batch sizes")
            return self._reduce_batch_sizes(config)

        return self._try_restore_config(config)

    def _emergency_mode(self, config: dict[str, Any]) -> dict[str, Any]:
        """Configuración de emergencia para evitar OOM."""
        emergency_config = config.copy()
        emergency_config["batch_size"] = 5_000
        emergency_config["lsh_batch_size"] = 2_000
        emergency_config["chunk_size"] = 10_000
        emergency_config["use_disk_cache"] = True
        emergency_config["aggressive_gc"] = True
        emergency_config["max_workers"] = 1
        self.logger.info("Configuración de emergencia aplicada")
        return emergency_config

    def _reduce_batch_sizes(self, config: dict[str, Any]) -> dict[str, Any]:
        """Reducir tamaños de lote proporcionalmente."""
        adapted_config = config.copy()
        batch_params = ["batch_size", "lsh_batch_size", "chunk_size"]

        for param in batch_params:
            if param in adapted_config:
                adapted_config[param] = max(1000, int(adapted_config[param] * 0.5))

        return adapted_config

    def _try_restore_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """Intentar restaurar configuración original si hay memoria."""
        status = MemoryManager.get_memory_status()

        if status["available_gb"] > (8.0 + 2):  # 2GB de margen
            self.logger.info("Memoria suficiente, restaurando configuración original")
            return self.original_config.copy()

        return config


def memoria_disponible() -> dict[str, float]:
    """Retorna información sobre memoria disponible."""
    mem = psutil.virtual_memory()
    return {
        "total_gb": mem.total / (1024**3),
        "disponible_gb": mem.available / (1024**3),
        "usada_gb": mem.used / (1024**3),
        "porcentaje_usado": mem.percent,
    }


def limpiar_memoria():
    """Fuerza liberación de memoria."""
    gc.collect()
    mem = memoria_disponible()
    print(
        f"🧹 Memoria liberada. Disponible: {mem['disponible_gb']:.2f} GB ({100 - mem['porcentaje_usado']:.1f}%)"
    )


def mostrar_memoria():
    """Muestra estado actual de memoria."""
    mem = memoria_disponible()
    usado = mem["porcentaje_usado"]

    # Indicador visual
    if usado < 60:
        icono = "🟢"
    elif usado < 80:
        icono = "🟡"
    else:
        icono = "🔴"

    print(f"{icono} Memoria: {mem['usada_gb']:.1f}/{mem['total_gb']:.1f} GB ({usado:.1f}% usado)")
