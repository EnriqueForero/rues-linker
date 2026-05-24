"""
deduplication.colab — record_linkage_pipeline

Componentes:
    - class ColabOptimizedManager  (origen: notebook celda [155])
    - function deduplicate_large_dataset_colab  (origen: notebook celda [155])

NOTA: Lógica de negocio preservada exactamente como en el notebook
fuente. Solo se agregan imports, docstring de módulo y se eliminan
directivas de Jupyter (%%time, !pip, etc.). Ver MIGRATION_LOG.md.
"""

from __future__ import annotations

import gc
import os
from typing import Any

import pandas as pd

from ..utils.logger import setup_logger
from ..utils.memory import MemoryManager
from .unified import deduplicate_unified


class ColabOptimizedManager:
    """
    Gestor específico para las limitaciones de Google Colab
    con adaptación dinámica según el tamaño del dataset.
    """

    def __init__(self):
        self.max_safe_memory_gb = 11.0  # Límite conservador para Colab
        self.temp_storage = "/content/temp_dedup"
        self.chunk_strategies = {
            "small": {"batch_size": 50_000, "use_disk": False},
            "medium": {"batch_size": 30_000, "use_disk": True},
            "large": {"batch_size": 20_000, "use_disk": True, "aggressive_gc": True},
            "xlarge": {"batch_size": 15_000, "use_disk": True, "streaming_mode": True},
        }

        # Crear directorio temporal si no existe
        os.makedirs(self.temp_storage, exist_ok=True)

    def auto_configure_for_dataset(self, n_records: int) -> dict[str, Any]:
        """
        Configura automáticamente los parámetros óptimos
        según el tamaño del dataset y memoria disponible.
        """
        current_memory = MemoryManager.get_memory_status()

        if n_records > 2_000_000 or current_memory["available_gb"] < 4:
            strategy = "xlarge"
        elif n_records > 1_000_000:
            strategy = "large"
        elif n_records > 500_000:
            strategy = "medium"
        else:
            strategy = "small"

        config = self.chunk_strategies[strategy].copy()
        config.update(
            {
                "lsh_threshold": 0.8,  # Más estricto para reducir candidatos
                "score_threshold": 0.85,  # Más estricto para reducir memoria
                "enable_progress_bars": True,
                "checkpoint_frequency": 100_000,
                "temp_dir": self.temp_storage,
            }
        )

        return config

    def optimize_dataframe_memory(self, df: pd.DataFrame) -> pd.DataFrame:
        """Optimizar tipos de datos del DataFrame para usar menos memoria."""

        logger = setup_logger("memory_optimizer")
        initial_memory = df.memory_usage(deep=True).sum() / 1024**2

        # Optimizar tipos numéricos
        for col in df.select_dtypes(include=["int"]).columns:
            df[col] = pd.to_numeric(df[col], downcast="integer")

        for col in df.select_dtypes(include=["float"]).columns:
            df[col] = pd.to_numeric(df[col], downcast="float")

        # Convertir strings repetitivos a categorical
        for col in df.select_dtypes(include=["object"]).columns:
            num_unique_values = len(df[col].unique())
            num_total_values = len(df[col])
            if num_unique_values / num_total_values < 0.5:
                df[col] = df[col].astype("category")

        final_memory = df.memory_usage(deep=True).sum() / 1024**2
        logger.info(
            f"Memoria optimizada: {initial_memory:.1f}MB -> {final_memory:.1f}MB "
            f"({(1 - final_memory / initial_memory) * 100:.1f}% reducción)"
        )

        return df

    def create_disk_backed_cache(self, cache_name: str):
        """Crear caché respaldado en disco para operaciones grandes."""
        import shelve

        cache_path = os.path.join(self.temp_storage, f"{cache_name}.cache")
        return shelve.open(cache_path, writeback=True)

    def cleanup_temp_files(self):
        """Limpiar archivos temporales creados durante el proceso."""
        import shutil

        if os.path.exists(self.temp_storage):
            shutil.rmtree(self.temp_storage)
            os.makedirs(self.temp_storage, exist_ok=True)


def deduplicate_large_dataset_colab(
    df: pd.DataFrame,
    nit_column: str = "NIT",
    name_column: str = "RAZON_SOCIAL",
    chunk_size: int | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Versión optimizada de deduplicación para datasets grandes en Google Colab.

    Procesa el dataset en chunks para mantener el uso de memoria bajo control.
    """

    colab_manager = ColabOptimizedManager()
    n_records = len(df)

    # Configurar automáticamente
    config = colab_manager.auto_configure_for_dataset(n_records)

    if chunk_size is None:
        chunk_size = config["batch_size"] * 10

    print("🚀 Deduplicación optimizada para Colab")
    print(f"   • Registros: {n_records:,}")
    print(f"   • Estrategia: {config}")
    print(f"   • Procesamiento en chunks de: {chunk_size:,}")

    # Optimizar memoria del DataFrame
    df_optimized = colab_manager.optimize_dataframe_memory(df)

    # Si el dataset es muy grande, procesar por chunks
    if n_records > 1_000_000 and config.get("streaming_mode"):
        print("   • Modo streaming activado")

        # Dividir en chunks y procesar
        results = []
        for i in range(0, n_records, chunk_size):
            chunk_end = min(i + chunk_size, n_records)
            print(f"\n📦 Procesando chunk {i // chunk_size + 1}: registros {i:,} a {chunk_end:,}")

            chunk_df = df_optimized.iloc[i:chunk_end].copy()

            # Procesar chunk
            correlativa_chunk, conexiones_chunk = deduplicate_unified(
                chunk_df,
                col_nit=nit_column,
                col_name=name_column,
                mode="BALANCEADO",
                profile="deduplication_colab_1M",
                output_dir=f"{colab_manager.temp_storage}/chunk_{i}",
                validate_against_legacy=False,
            )

            results.append((correlativa_chunk, conexiones_chunk))

            # Liberar memoria
            del chunk_df
            gc.collect()

        # Consolidar resultados
        print("\n🔄 Consolidando resultados de chunks...")
        # Aquí iría la lógica de consolidación inter-chunks
        # Por simplicidad, retornamos el primer chunk
        return results[0]

    else:
        # Procesar normalmente
        return deduplicate_unified(
            df_optimized,
            col_nit=nit_column,
            col_name=name_column,
            mode="BALANCEADO",
            profile="deduplication_colab_1M" if n_records > 500_000 else "deduplication_standard",
            output_dir=colab_manager.temp_storage,
        )
