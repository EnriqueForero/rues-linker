"""
engine.disk_based — record_linkage_pipeline

Componentes:
    - class DiskBasedLSHEngine  (origen: notebook celda [120])

NOTA: Lógica de negocio preservada exactamente como en el notebook
fuente. Solo se agregan imports, docstring de módulo y se eliminan
directivas de Jupyter (%%time, !pip, etc.). Ver MIGRATION_LOG.md.
"""

from __future__ import annotations

import gc
import json
import logging
import os
import sqlite3
import time
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import (
    Any,
)

import h5py
import numpy as np
import pandas as pd
from datasketch import MinHash
from tqdm import tqdm

from .defaults import LSHDefaults
from .metrics import EngineMetrics
from .state import EngineState
from .vectorized_minhash import VectorizedMinHasher


def _hash_rows_stable(band_data: np.ndarray) -> np.ndarray:
    """Hash determinista de 64 bits para cada fila de una banda LSH.

    Reemplaza ``hash(row.tobytes())`` (randomizado por PYTHONHASHSEED, inestable
    entre procesos). Usa FNV-1a de 64 bits acumulado sobre las columnas uint64
    de la banda — vectorizado sobre todas las filas a la vez. Determinista, así
    que el índice LSH es consistente tras reinicios de sesión.

    Args:
        band_data: Array (n_filas, rows_per_band) de uint64 con los mínimos de
            la banda para cada registro.

    Returns:
        Array (n_filas,) de int64 con el hash estable de cada fila.
    """
    if band_data.ndim == 1:
        band_data = band_data.reshape(-1, 1)
    n_rows, n_cols = band_data.shape
    # FNV-1a de 64 bits, vectorizado por columna sobre todas las filas.
    fnv_offset = np.uint64(14695981039346656037)
    fnv_prime = np.uint64(1099511628211)
    acc = np.full(n_rows, fnv_offset, dtype=np.uint64)
    cols = band_data.astype(np.uint64, copy=False)
    with np.errstate(over="ignore"):  # el overflow uint64 es el wrap deseado
        for c in range(n_cols):
            acc = (acc ^ cols[:, c]) * fnv_prime
    # A int64 con signo para almacenar en SQLite (rango de 64 bits con signo).
    return acc.astype(np.int64)


class DiskBasedLSHEngine:
    """
    Motor LSH de producción con almacenamiento en disco para Google Colab.

    Diseñado para procesar datasets de millones de registros en entornos
    con memoria limitada mediante:

    - Almacenamiento de firmas MinHash en HDF5 comprimido
    - Índice LSH en SQLite con configuración de alto rendimiento
    - Procesamiento por bandas para evitar explosión de memoria
    - Checkpointing transaccional para recuperación ante interrupciones

    Parameters
    ----------
    profile : Dict[str, Any], optional
        Perfil de configuración con parámetros LSH.
    config : Dict[str, Any], optional
        Configuración global del pipeline.

    Examples
    --------
    >>> engine = DiskBasedLSHEngine(profile, config)
    >>> candidates = engine.find_candidates(df, output_dir='/tmp/output')
    >>> print(engine.get_stats())
    >>> engine.cleanup()
    """

    VERSION: str = "4.0.0"

    # ═══════════════════════════════════════════════════════════════════════════
    # INICIALIZACIÓN Y CONFIGURACIÓN
    # ═══════════════════════════════════════════════════════════════════════════

    def __init__(
        self, profile: dict[str, Any] | None = None, config: dict[str, Any] | None = None
    ) -> None:
        """Inicializa el motor LSH."""
        self.logger = logging.getLogger("DiskBasedLSHEngine")

        # Configuración
        self.profile: dict[str, Any] = profile.copy() if profile else {}
        self.config: dict[str, Any] = config.copy() if config else {}

        # Estado
        self.state: EngineState = EngineState.UNINITIALIZED
        self.metrics: EngineMetrics = EngineMetrics()

        # Rutas (se configuran en find_candidates)
        self._storage_dir: Path | None = None
        self._signatures_file: Path | None = None
        self._index_db_file: Path | None = None
        self._candidates_db_file: Path | None = None
        self._checkpoint_file: Path | None = None

        # Conexiones activas
        self._active_connections: list[sqlite3.Connection] = []

        # Extraer parámetros
        self._extract_and_validate_parameters()

        # Configuración SQLite optimizada
        self._sqlite_config: dict[str, Any] = {
            "journal_mode": "DELETE",  # <--- CRÍTICO: Cambiar de WAL a DELETE u OFF
            "synchronous": "OFF",  # Optimización para velocidad
            "cache_size": -512000,  # ~500MB RAM
            "temp_store": "MEMORY",  # Temporales en RAM, no en disco lento
            "mmap_size": 0,  # Desactivar mmap en sistemas de red, antes estaba:  536870912,
            "page_size": 32768,  # Bloques grandes para menos I/O
            "locking_mode": "EXCLUSIVE",  # ANtes estaba: 'NORMAL',
            # 'wal_autocheckpoint': 1000, <-- BORRAR ESTA LÍNEA (No aplica en modo DELETE)
        }

        self.state = EngineState.INITIALIZED
        self.logger.info(
            f"DiskBasedLSHEngine v{self.VERSION} inicializado | "
            f"perm={self._num_perm}, th={self._threshold:.3f}, "
            f"ngram={self._ngram}, chunk={self._chunk_size:,}"
        )

    def _extract_and_validate_parameters(self) -> None:
        """Extrae y valida parámetros de configuración."""
        defaults = LSHDefaults()
        active_params: dict[str, Any] = {}

        # Prioridad: config global > profile directo > defaults
        if "profiles" in self.config:
            profile_name = self.config.get("profile", "")
            if profile_name and profile_name in self.config["profiles"]:
                active_params = self.config["profiles"][profile_name].copy()

        if self.profile:
            active_params.update(self.profile)

        # Extraer con validación
        self._num_perm = self._validate_int(
            active_params.get("lsh_permutations", defaults.PERMUTATIONS),
            16,
            512,
            "lsh_permutations",
        )
        self._threshold = self._validate_float(
            active_params.get("lsh_threshold", defaults.THRESHOLD), 0.1, 0.99, "lsh_threshold"
        )
        self._ngram = self._validate_int(
            active_params.get("lsh_ngram", defaults.NGRAM_SIZE), 1, 5, "lsh_ngram"
        )
        self._chunk_size = self._validate_int(
            active_params.get("lsh_chunk_size", defaults.CHUNK_SIZE),
            1000,
            500_000,
            "lsh_chunk_size",
        )
        self._batch_size = self._validate_int(
            active_params.get("sqlite_batch_size", defaults.BATCH_SIZE),
            1000,
            200_000,
            "sqlite_batch_size",
        )
        self._memory_threshold = self._validate_int(
            active_params.get("memory_threshold_candidates", defaults.MEMORY_THRESHOLD_CANDIDATES),
            0,
            50_000_000,
            "memory_threshold_candidates",
        )
        self._max_bucket_size = self._validate_int(
            active_params.get("max_bucket_size", defaults.MAX_BUCKET_SIZE),
            10,
            5000,
            "max_bucket_size",
        )
        self._force_disk = bool(active_params.get("force_disk_results", False))

        # ── P0-1 (v2.5.0): bloqueo por NIT base como complemento al LSH ──
        # Por defecto activo: ataca la causa raíz del cuello de recall
        # (pares con mismo NIT pero nombres incomparables por LSH).
        self._enable_nit_blocking = bool(active_params.get("enable_nit_blocking", True))
        self._nit_blocking_neighbors = bool(active_params.get("nit_blocking_neighbors", True))
        self._nit_blocking_max_bucket = self._validate_int(
            active_params.get("nit_blocking_max_bucket", 200),
            2,
            5000,
            "nit_blocking_max_bucket",
        )
        self._nit_blocking_column = str(active_params.get("nit_blocking_column", "NIT_BASE"))

    @staticmethod
    def _validate_int(value: Any, min_val: int, max_val: int, name: str) -> int:
        """Valida y convierte un valor a entero dentro de un rango."""
        try:
            val = int(value)
            return max(min_val, min(val, max_val))
        except (TypeError, ValueError):
            return min_val

    @staticmethod
    def _validate_float(value: Any, min_val: float, max_val: float, name: str) -> float:
        """Valida y convierte un valor a float dentro de un rango."""
        try:
            val = float(value)
            return max(min_val, min(val, max_val))
        except (TypeError, ValueError):
            return min_val

    # ═══════════════════════════════════════════════════════════════════════════
    # API PÚBLICA REQUERIDA POR EL PIPELINE
    # ═══════════════════════════════════════════════════════════════════════════

    def update_config(self, new_config: dict[str, Any]) -> None:
        """
        Actualiza la configuración del motor en tiempo de ejecución.

        Requerido por RecordLinkageEngine._update_profile().

        Parameters
        ----------
        new_config : Dict[str, Any]
            Nuevos parámetros de configuración.
        """
        if not new_config:
            return

        self.logger.info(f"♻️ Actualizando config: {list(new_config.keys())}")
        self.profile.update(new_config)
        self._extract_and_validate_parameters()

    def find_candidates(
        self,
        df: pd.DataFrame,
        output_dir: str | None = None,
        cross_source_only: bool = False,
        trusted_unique_sources: set | None = None,
    ) -> set[tuple[int, int]] | str:
        """
        Encuentra pares candidatos usando MinHash-LSH.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame con columna 'NOMBRE_LIMPIO'.
        output_dir : str
            Directorio de trabajo (OBLIGATORIO).
        cross_source_only : bool
            Si True, solo cruza entre diferentes fuentes.
        trusted_unique_sources : set | None
            **Aceptado por compatibilidad con `RecordLinkageEngine.link()`,
            pero IGNORADO en este motor base.** El soporte real de fuentes
            confiables vive en `TrustedSourceLSHEngine`, que recibe el set
            en `__init__` (no acá). Si se pasa un set no vacío a este motor
            base, se emite warning. v2.10.0 bug-fix: antes este kwarg
            provocaba TypeError en el path disk_based del pipeline. Ver
            MIGRATION_LOG §21.

        Returns
        -------
        Union[Set[Tuple[int, int]], str]
            Set de pares o ruta a DB SQLite.
        """
        if trusted_unique_sources:
            self.logger.warning(
                "DiskBasedLSHEngine recibió trusted_unique_sources=%s pero "
                "este motor no las procesa. Use TrustedSourceLSHEngine si "
                "necesita el comportamiento de fuentes confiables.",
                sorted(trusted_unique_sources),
            )
        # Validaciones
        if not output_dir:
            raise ValueError("output_dir es OBLIGATORIO")

        if "NOMBRE_LIMPIO" not in df.columns:
            raise ValueError("DataFrame requiere columna 'NOMBRE_LIMPIO'")

        if cross_source_only and "FUENTE" not in df.columns:
            self.logger.warning("cross_source_only=True pero sin columna 'FUENTE'")
            cross_source_only = False

        n_records = len(df)
        if n_records == 0:
            return set()

        self.logger.info(f"═══ LSH para {n_records:,} registros ═══")

        # Configurar rutas
        self._storage_dir = Path(output_dir) / "lsh_disk_cache"
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        self._signatures_file = self._storage_dir / "signatures.h5"
        self._index_db_file = self._storage_dir / "lsh_index.db"
        self._candidates_db_file = self._storage_dir / "candidates.db"
        self._checkpoint_file = self._storage_dir / "checkpoint.json"

        total_start = time.time()

        try:
            # 1. Firmas
            self._generate_signatures(df)

            # 2. Índice
            n_bands, _rows_per_band = self._build_lsh_index(n_records)

            # 3. Candidatos
            self._find_candidate_pairs(df, n_bands, cross_source_only)

            self.state = EngineState.CANDIDATES_READY
            self.logger.info(
                f"═══ LSH completado: {self.metrics.candidates_found:,} candidatos "
                f"en {(time.time() - total_start) / 60:.1f} min ═══"
            )

            return self._decide_return_format()

        except Exception as e:
            self.state = EngineState.ERROR
            self.logger.error(f"Error en LSH: {e}", exc_info=True)
            raise RuntimeError(f"Error en LSH: {e}") from e

    def cleanup(self, force: bool = False) -> None:
        """
        Limpia archivos temporales y libera recursos.

        Parameters
        ----------
        force : bool
            Si True, limpia aunque el proceso no haya completado.
        """
        self.logger.info("🧹 Limpiando recursos LSH...")

        # Cerrar conexiones
        for conn in self._active_connections:
            with suppress(Exception):
                conn.close()
        self._active_connections.clear()
        gc.collect()

        if not force and self.state not in (EngineState.CANDIDATES_READY, EngineState.CLEANED):
            self.logger.warning("Use cleanup(force=True) para forzar limpieza")
            return

        # Eliminar archivos
        files_to_remove: list[Path] = []
        if self._signatures_file:
            files_to_remove.append(self._signatures_file)
        if self._index_db_file:
            files_to_remove.extend(
                [
                    self._index_db_file,
                    self._index_db_file.with_suffix(".db-wal"),
                    self._index_db_file.with_suffix(".db-shm"),
                ]
            )
        if self._candidates_db_file:
            files_to_remove.extend(
                [
                    self._candidates_db_file,
                    self._candidates_db_file.with_suffix(".db-wal"),
                    self._candidates_db_file.with_suffix(".db-shm"),
                ]
            )
        if self._checkpoint_file:
            files_to_remove.append(self._checkpoint_file)

        removed = 0
        for f in files_to_remove:
            if f and f.exists():
                try:
                    f.unlink()
                    removed += 1
                except OSError:
                    pass

        if self._storage_dir and self._storage_dir.exists():
            with suppress(OSError):
                self._storage_dir.rmdir()

        self.state = EngineState.CLEANED
        self.logger.info(f"✅ Limpieza: {removed} archivos eliminados")
        gc.collect()

    def get_stats(self) -> dict[str, Any]:
        """Obtiene estadísticas del motor."""
        stats = {
            "engine": f"DiskBasedLSHEngine v{self.VERSION}",
            "version": self.VERSION,
            "state": self.state.name,
            "config": {
                "permutations": self._num_perm,
                "threshold": self._threshold,
                "ngram": self._ngram,
                "chunk_size": self._chunk_size,
            },
            "metrics": {
                "signatures_generated": self.metrics.signatures_generated,
                "index_entries": self.metrics.index_entries,
                "candidates_found": self.metrics.candidates_found,
                "bands_processed": self.metrics.bands_processed,
                "time_signatures_sec": round(self.metrics.time_signatures, 2),
                "time_indexing_sec": round(self.metrics.time_indexing, 2),
                "time_candidates_sec": round(self.metrics.time_candidates, 2),
            },
        }
        return stats

    def should_use_disk_processing(self, n_records: int) -> bool:
        """Determina si usar procesamiento en disco."""
        estimated_gb = (n_records * self._num_perm * 8) / (1024**3)

        try:
            import psutil

            available_gb = psutil.virtual_memory().available / (1024**3)
        except ImportError:
            available_gb = 8.0

        return estimated_gb > available_gb * 0.7 or n_records > 500_000 or self._force_disk

    # ═══════════════════════════════════════════════════════════════════════════
    # GENERACIÓN DE FIRMAS
    # ═══════════════════════════════════════════════════════════════════════════

    def _generate_signatures(self, df: pd.DataFrame) -> None:
        """Genera y almacena firmas MinHash en HDF5."""
        if self._signatures_file.exists():
            if self._validate_signatures_file(len(df)):
                self.logger.info("📝 Reutilizando firmas existentes")
                self.state = EngineState.SIGNATURES_READY
                return
            self._signatures_file.unlink()

        n_records = len(df)
        self.logger.info(f"📝 Generando {n_records:,} firmas MinHash...")
        start_time = time.time()

        with h5py.File(str(self._signatures_file), "w") as hf:
            chunk_rows = min(self._chunk_size, n_records)
            signatures_ds = hf.create_dataset(
                "signatures",
                shape=(n_records, self._num_perm),
                dtype="uint64",
                chunks=(chunk_rows, self._num_perm),
                compression="gzip",
                compression_opts=1,
            )

            hf.attrs["n_records"] = n_records
            hf.attrs["num_perm"] = self._num_perm
            hf.attrs["ngram"] = self._ngram
            hf.attrs["version"] = self.VERSION

            texts = df["NOMBRE_LIMPIO"].values

            # v2.3.0: firmas vectorizadas con NumPy en vez de un objeto MinHash
            # de datasketch por registro. Mismo esquema de hashing (familia
            # lineal sobre el primo de Mersenne) y determinista. Ver
            # MIGRATION_LOG §13.1. El hasher se construye una sola vez.
            hasher = VectorizedMinHasher(num_perm=self._num_perm, ngram=self._ngram, seed=42)

            with tqdm(total=n_records, desc="Generando firmas", unit="rec") as pbar:
                for start in range(0, n_records, self._chunk_size):
                    end = min(start + self._chunk_size, n_records)

                    batch_sigs = hasher.signatures_batch(texts[start:end])

                    signatures_ds[start:end] = batch_sigs
                    pbar.update(end - start)

                    if (start // self._chunk_size) % LSHDefaults.GC_INTERVAL == 0:
                        del batch_sigs
                        gc.collect()

        self.metrics.signatures_generated = n_records
        self.metrics.time_signatures = time.time() - start_time
        self.state = EngineState.SIGNATURES_READY
        self.logger.info(f"✅ Firmas generadas en {self.metrics.time_signatures:.1f}s")

    def _create_minhash(self, text: Any, max_val: int) -> np.ndarray:
        """Crea firma MinHash para un texto (un registro).

        DEPRECADO en v2.3.0: ya no se usa internamente. La generación de firmas
        ahora es vectorizada vía ``VectorizedMinHasher`` (ver ``_generate_signatures``
        y MIGRATION_LOG §13.1). Se conserva por compatibilidad con código externo
        que pudiera invocarlo. Para nuevas firmas usa ``VectorizedMinHasher``.
        """
        if pd.isna(text):
            text = ""
        elif not isinstance(text, str):
            text = str(text)

        if len(text) < self._ngram:
            return np.full(self._num_perm, max_val, dtype=np.uint64)

        try:
            minhash = MinHash(num_perm=self._num_perm)
            for i in range(len(text) - self._ngram + 1):
                minhash.update(text[i : i + self._ngram].encode("utf-8"))
            return minhash.hashvalues
        except Exception:
            return np.full(self._num_perm, max_val, dtype=np.uint64)

    def _validate_signatures_file(self, expected_records: int) -> bool:
        """Valida archivo de firmas existente."""
        try:
            with h5py.File(str(self._signatures_file), "r") as hf:
                return (
                    "signatures" in hf
                    and hf.attrs.get("n_records", 0) == expected_records
                    and hf.attrs.get("num_perm", 0) == self._num_perm
                    and hf.attrs.get("ngram", 0) == self._ngram
                )
        except Exception:
            return False

    # ═══════════════════════════════════════════════════════════════════════════
    # CONSTRUCCIÓN DE ÍNDICE LSH
    # ═══════════════════════════════════════════════════════════════════════════

    def _build_lsh_index(self, n_records: int) -> tuple[int, int]:
        """
        Construye el índice LSH con validación robusta y eficiente.

        Versión V4.4 - Combina eficiencia, robustez y principio DRY.

        Parameters
        ----------
        n_records : int
            Número total de registros a indexar.

        Returns
        -------
        Tuple[int, int]
            (número_de_bandas, filas_por_banda)
        """
        n_bands, rows_per_band = self._calculate_optimal_bands()
        eff_thresh = (1.0 / n_bands) ** (1.0 / rows_per_band)

        self.logger.info(
            f"📊 Config: {n_bands} bandas × {rows_per_band} filas "
            f"(threshold efectivo: {eff_thresh:.3f})"
        )

        # 1. Verificar si ya está completo y válido (con n_records para umbral preciso)
        if self._is_index_complete(n_bands, n_records):
            self.logger.info("📊 Índice existente verificado (tamaño + metadatos + datos)")
            self.state = EngineState.INDEX_READY
            return n_bands, rows_per_band

        # 2. El índice no sirve o no existe → Limpiar y reconstruir
        self.logger.info("🧹 Iniciando construcción de índice (limpiando archivos previos)...")
        self._clean_index_files()

        # 3. Verificar si podemos reanudar desde checkpoint
        checkpoint = self._load_checkpoint()
        start_band = 0

        if checkpoint:
            saved_band = checkpoint.get("completed_bands", 0)
            saved_records = checkpoint.get("n_records", 0)

            # Solo reanudar si el checkpoint es coherente con la ejecución actual
            if saved_records == n_records and saved_band > 0 and saved_band < n_bands:
                # Verificar que el archivo existe y tiene tamaño razonable
                if self._index_db_file.exists():
                    file_size = self._index_db_file.stat().st_size
                    min_size = saved_band * 50_000  # ~50KB por banda mínimo
                    if file_size >= min_size:
                        start_band = saved_band
                        self.logger.info(f"♻️ Reanudando desde banda {start_band}")
                        self.metrics.resumed_from_checkpoint = True

        # 4. Inicializar schema si empezamos de cero
        if start_band == 0:
            with self._get_sqlite_connection(self._index_db_file) as conn:
                self._init_index_schema(conn, n_bands, rows_per_band)

        # 5. Proceso de indexación
        start_time = time.time()

        with self._get_sqlite_connection(self._index_db_file) as conn:
            with h5py.File(str(self._signatures_file), "r") as hf:
                signatures = hf["signatures"]

                with tqdm(
                    total=n_bands, initial=start_band, desc="Indexando", unit="banda"
                ) as pbar:
                    for band_idx in range(start_band, n_bands):
                        self._index_band(conn, signatures, band_idx, rows_per_band, n_records)

                        self._save_checkpoint(
                            {
                                "completed_bands": band_idx + 1,
                                "total_bands": n_bands,
                                "n_records": n_records,
                            }
                        )

                        pbar.update(1)
                        self.metrics.bands_processed = band_idx + 1

                        if band_idx % LSHDefaults.GC_INTERVAL == 0:
                            gc.collect()

            # 6. Marcar como completo
            conn.execute("INSERT OR REPLACE INTO metadata VALUES ('is_complete', '1')")
            conn.execute(
                "INSERT OR REPLACE INTO metadata VALUES ('total_bands', ?)", (str(n_bands),)
            )
            conn.commit()

            with suppress(Exception):
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        # 7. Sincronización y espera para Google Drive
        with suppress(AttributeError, OSError):
            os.sync()

        time.sleep(2)

        # 8. Validación final (DRY: reutiliza _is_index_complete)
        if not self._is_index_complete(n_bands, n_records):
            # Limpiar para que el próximo intento empiece limpio
            self._clean_index_files()
            raise RuntimeError(
                "❌ Error crítico: El índice se construyó pero falló la validación final. "
                "Los archivos corruptos fueron eliminados. Por favor re-ejecute."
            )

        self.metrics.time_indexing = time.time() - start_time
        self.state = EngineState.INDEX_READY

        file_size = self._index_db_file.stat().st_size
        self.logger.info(
            f"✅ Índice construido: {file_size / (1024 * 1024):.1f} MB "
            f"en {self.metrics.time_indexing:.1f}s"
        )

        return n_bands, rows_per_band

    def _init_index_schema(
        self, conn: sqlite3.Connection, n_bands: int, rows_per_band: int
    ) -> None:
        """Inicializa schema del índice."""
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lsh_buckets (
                band_id INTEGER NOT NULL,
                hash_value INTEGER NOT NULL,
                record_id INTEGER NOT NULL
            )
        """)
        cursor.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT)")
        cursor.execute("INSERT OR REPLACE INTO metadata VALUES ('n_bands', ?)", (str(n_bands),))
        cursor.execute(
            "INSERT OR REPLACE INTO metadata VALUES ('rows_per_band', ?)", (str(rows_per_band),)
        )
        conn.commit()

    def _index_band(
        self,
        conn: sqlite3.Connection,
        signatures: h5py.Dataset,
        band_idx: int,
        rows_per_band: int,
        n_records: int,
    ) -> None:
        """Indexa una banda."""
        cursor = conn.cursor()
        cursor.execute("BEGIN TRANSACTION")

        start_col = band_idx * rows_per_band
        end_col = start_col + rows_per_band
        entries = 0

        for start_row in range(0, n_records, self._chunk_size):
            end_row = min(start_row + self._chunk_size, n_records)
            band_data = signatures[start_row:end_row, start_col:end_col]

            # v2.3.0: hash de banda DETERMINISTA. Antes se usaba hash(row.tobytes())
            # que está randomizado por PYTHONHASHSEED: tras un reinicio de Colab y
            # reanudación desde checkpoint, las bandas nuevas producían hashes que
            # NO coincidían con los del índice previo, corrompiendo los buckets y
            # perdiendo pares en silencio. Usamos un hash estable de 64 bits.
            # Ver MIGRATION_LOG §13.2.
            hashes = _hash_rows_stable(band_data)
            record_ids = np.arange(start_row, end_row, dtype=np.int64)

            data = [
                (int(band_idx), int(h), int(rid))
                for h, rid in zip(hashes, record_ids, strict=False)
            ]
            cursor.executemany("INSERT INTO lsh_buckets VALUES (?, ?, ?)", data)
            entries += len(data)

        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_band_{band_idx}
            ON lsh_buckets (hash_value) WHERE band_id = {band_idx}
        """)
        conn.commit()
        self.metrics.index_entries += entries

    def _calculate_optimal_bands(self) -> tuple[int, int]:
        """Calcula configuración óptima de bandas."""
        best_b, best_r = 1, self._num_perm
        min_error = float("inf")

        for b in range(1, self._num_perm + 1):
            if self._num_perm % b == 0:
                r = self._num_perm // b
                effective = (1.0 / b) ** (1.0 / r)
                error = abs(effective - self._threshold)

                if effective <= self._threshold:
                    error *= 0.85

                if error < min_error:
                    min_error = error
                    best_b, best_r = b, r

        return best_b, best_r

    def _is_index_complete(self, expected_bands: int, n_records: int | None = None) -> bool:
        """
        Verifica si el índice existe, está completo Y tiene datos válidos.

        Versión V4.4 - Optimizada para eficiencia O(1) y precisión.

        Parameters
        ----------
        expected_bands : int
            Número de bandas esperado según configuración LSH.
        n_records : int, optional
            Número de registros del dataset. Si no se proporciona, usa
            heurística basada en tamaño de archivo.

        Returns
        -------
        bool
            True solo si el índice pasa TODAS las validaciones.
        """
        # 1. Verificar existencia del archivo
        if not self._index_db_file or not self._index_db_file.exists():
            return False

        # 2. Verificar tamaño mínimo del archivo (heurística rápida, sin SQL)
        file_size = self._index_db_file.stat().st_size

        if n_records:
            # Umbral dinámico: ~20 bytes por registro mínimo
            min_size = max(100 * 1024, n_records * 20)
        else:
            # Fallback: mínimo 10MB para índices reales
            min_size = 10 * 1024 * 1024

        if file_size < min_size:
            self.logger.warning(
                f"⚠️ Índice muy pequeño: {file_size:,} bytes "
                f"(esperado ≥{min_size:,}). Se reconstruirá."
            )
            return False

        # 3. Validaciones SQL (solo si pasó verificación de tamaño)
        try:
            with self._get_sqlite_connection(self._index_db_file, readonly=True) as conn:
                cursor = conn.cursor()

                # 3a. Verificar metadato is_complete
                cursor.execute("SELECT value FROM metadata WHERE key = 'is_complete'")
                result = cursor.fetchone()
                if not result or result[0] != "1":
                    self.logger.info("📋 Índice marcado como incompleto en metadatos")
                    return False

                # 3b. Verificar número de bandas
                cursor.execute("SELECT value FROM metadata WHERE key = 'total_bands'")
                result = cursor.fetchone()
                if not result or int(result[0]) != expected_bands:
                    self.logger.info(
                        f"📋 Bandas no coinciden: {result[0] if result else 'N/A'} "
                        f"vs esperado {expected_bands}"
                    )
                    return False

                # 3c. Verificar que lsh_buckets tenga datos (O(1) con LIMIT 1)
                cursor.execute("SELECT 1 FROM lsh_buckets LIMIT 1")
                if not cursor.fetchone():
                    self.logger.warning(
                        "⚠️ Índice marcado completo pero tabla lsh_buckets vacía. Se reconstruirá."
                    )
                    return False

                # ✅ Todas las validaciones pasaron
                self.logger.info(
                    f"📊 Índice verificado: {file_size / (1024 * 1024):.1f} MB, "
                    f"{expected_bands} bandas"
                )
                return True

        except (sqlite3.DatabaseError, sqlite3.OperationalError) as e:
            self.logger.warning(f"⚠️ Error SQL verificando índice: {e}. Se reconstruirá.")
            return False
        except Exception as e:
            self.logger.warning(f"⚠️ Error inesperado: {e}")
            return False

    def _clean_index_files(self) -> None:
        """
        Elimina archivos de índice LSH y archivos asociados.

        Limpia: lsh_index.db, .db-wal, .db-shm, .db-journal, checkpoint.json
        """
        if not self._index_db_file:
            return

        # Archivos de base de datos SQLite
        for ext in ["", "-wal", "-shm", "-journal"]:
            f_path = self._index_db_file.parent / (self._index_db_file.name + ext)
            if f_path.exists():
                try:
                    f_path.unlink()
                    self.logger.debug(f"🧹 Eliminado: {f_path.name}")
                except OSError as e:
                    self.logger.warning(f"No se pudo eliminar {f_path.name}: {e}")

        # Checkpoint
        if self._checkpoint_file and self._checkpoint_file.exists():
            try:
                self._checkpoint_file.unlink()
                self.logger.debug("🧹 Eliminado: checkpoint.json")
            except OSError:
                pass

    # ═══════════════════════════════════════════════════════════════════════════
    # BÚSQUEDA DE CANDIDATOS
    # ═══════════════════════════════════════════════════════════════════════════

    def _find_candidate_pairs(
        self, df: pd.DataFrame, n_bands: int, cross_source_only: bool
    ) -> None:
        """Genera pares candidatos con limpieza preventiva de archivos corruptos."""
        self.logger.info(f"🔍 Buscando candidatos (cross_source={cross_source_only})...")
        start_time = time.time()

        source_map: dict[int, str] | None = None
        if cross_source_only and "FUENTE" in df.columns:
            source_map = df["FUENTE"].to_dict()

        cand_checkpoint = self._load_candidates_checkpoint()
        start_band = cand_checkpoint.get("completed_bands", 0) if cand_checkpoint else 0

        if start_band > 0:
            self.logger.info(f"♻️ Reanudando búsqueda desde banda {start_band}")
        else:
            # === INICIO AGREGADO: Limpieza preventiva para candidates.db ===
            # Si empezamos de cero, aseguramos que no existan residuos corruptos
            for ext in ["", "-wal", "-shm", "-journal"]:
                f_path = self._candidates_db_file.parent / (self._candidates_db_file.name + ext)
                if f_path.exists():
                    try:
                        f_path.unlink()
                        self.logger.info(f"🧹 Limpieza preventiva: eliminado {f_path.name}")
                    except OSError:
                        pass
            # === FIN AGREGADO ===

        # Aquí ya usa su nuevo _get_sqlite_connection robusto
        with self._get_sqlite_connection(self._candidates_db_file) as conn_cand:
            self._init_candidates_schema(conn_cand)

            with self._get_sqlite_connection(self._index_db_file, readonly=True) as conn_lsh:
                with tqdm(
                    total=n_bands, initial=start_band, desc="Candidatos", unit="banda"
                ) as pbar:
                    for band_idx in range(start_band, n_bands):
                        self._process_band_candidates(conn_lsh, conn_cand, band_idx, source_map)
                        self._save_candidates_checkpoint(conn_cand, band_idx + 1)
                        pbar.update(1)

                        if band_idx % 10 == 0:
                            pbar.set_postfix(pairs=f"{self._count_candidates(conn_cand):,}")

                        if band_idx % LSHDefaults.GC_INTERVAL == 0:
                            gc.collect()

            self.metrics.candidates_found = self._count_candidates(conn_cand)

        self.metrics.time_candidates = time.time() - start_time
        self.logger.info(
            f"✅ {self.metrics.candidates_found:,} candidatos en {self.metrics.time_candidates:.1f}s"
        )

    def _merge_nit_blocking_pairs(self, df: pd.DataFrame, cross_source_only: bool) -> None:
        """Fusiona pares de bloqueo por NIT base con los candidatos LSH (v2.5.0).

        Ataque a la causa raíz del cuello de recall (P0-1): pares cuyas
        razones sociales no comparten n-gramas pero sí comparten NIT (o NIT a
        distancia 1). Estos pares NUNCA entrarían por el LSH de nombre.

        Implementación: usa el módulo ``nit_blocking`` (vectorizado), filtra
        por ``cross_source_only`` si aplica, y los inserta en la misma tabla
        ``candidate_pairs`` con ``INSERT OR IGNORE`` para deduplicar respecto
        a los pares LSH ya escritos.

        Args:
            df: DataFrame con índice posicional 0..n-1 y columnas
                NIT_BASE (o la columna configurada) y FUENTE (si cross_source).
            cross_source_only: Si True, descarta pares de la misma fuente
                (consistente con el filtro del LSH).
        """
        from .nit_blocking import NitBlockingConfig, block_by_nit_base

        nit_col = self._nit_blocking_column
        if nit_col not in df.columns:
            self.logger.info(
                f"[nit_blocking] Columna '{nit_col}' no presente, se omite el "
                f"bloqueo por NIT (esto es esperado en algunos modos)."
            )
            return

        start_time = time.time()
        cfg = NitBlockingConfig(
            enable_exact=True,
            enable_neighbors=self._nit_blocking_neighbors,
            max_bucket_size=self._nit_blocking_max_bucket,
            min_nit_length=6,
        )

        pairs = block_by_nit_base(df, nit_column=nit_col, config=cfg)
        if not pairs:
            self.logger.info("[nit_blocking] 0 pares generados por bloqueo de NIT.")
            return

        # Filtro cross-source: descartar pares de la misma fuente.
        if cross_source_only and "FUENTE" in df.columns:
            sources = df["FUENTE"].to_numpy()
            n = len(sources)
            filtered = [
                (a, b) for (a, b) in pairs if 0 <= a < n and 0 <= b < n and sources[a] != sources[b]
            ]
            self.logger.info(
                f"[nit_blocking] Filtro cross_source: {len(pairs):,} → {len(filtered):,} pares"
            )
            pairs_to_insert: list[tuple[int, int]] = filtered
        else:
            pairs_to_insert = list(pairs)

        if not pairs_to_insert:
            return

        # Insertar en lote con INSERT OR IGNORE: la PK (idx_0, idx_1) absorbe
        # los duplicados respecto a los pares LSH ya escritos.
        before = 0
        added = 0
        batch_size = 50_000
        with self._get_sqlite_connection(self._candidates_db_file) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM candidate_pairs")
            before = cursor.fetchone()[0]
            cursor.execute("BEGIN TRANSACTION")
            for i in range(0, len(pairs_to_insert), batch_size):
                chunk = pairs_to_insert[i : i + batch_size]
                cursor.executemany("INSERT OR IGNORE INTO candidate_pairs VALUES (?, ?)", chunk)
            cursor.execute("COMMIT")
            cursor.execute("SELECT COUNT(*) FROM candidate_pairs")
            after = cursor.fetchone()[0]
            added = after - before
            self.metrics.candidates_found = after

        elapsed = time.time() - start_time
        self.logger.info(
            f"[nit_blocking] Fusión: {before:,} LSH + {len(pairs_to_insert):,} NIT → "
            f"{after:,} totales (+{added:,} nuevos por NIT) en {elapsed:.2f}s"
        )

    def _init_candidates_schema(self, conn: sqlite3.Connection) -> None:
        """Inicializa schema de candidatos."""
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS candidate_pairs (
                idx_0 INTEGER NOT NULL,
                idx_1 INTEGER NOT NULL,
                PRIMARY KEY (idx_0, idx_1)
            ) WITHOUT ROWID
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS _progress (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                completed_bands INTEGER DEFAULT 0
            )
        """)
        cursor.execute("INSERT OR IGNORE INTO _progress (id, completed_bands) VALUES (1, 0)")
        conn.commit()

    def _process_band_candidates(
        self,
        conn_lsh: sqlite3.Connection,
        conn_cand: sqlite3.Connection,
        band_idx: int,
        source_map: dict[int, str] | None,
    ) -> None:
        """Procesa candidatos de una banda."""
        cursor_lsh = conn_lsh.cursor()
        cursor_cand = conn_cand.cursor()

        cursor_lsh.execute(f"""
            SELECT hash_value, GROUP_CONCAT(record_id) as records
            FROM lsh_buckets
            WHERE band_id = {band_idx}
            GROUP BY hash_value
            HAVING COUNT(record_id) BETWEEN {LSHDefaults.MIN_BUCKET_SIZE} AND {self._max_bucket_size}
        """)

        cursor_cand.execute("BEGIN TRANSACTION")

        for row in cursor_lsh:
            _, records_str = row
            record_ids = [int(x) for x in records_str.split(",")]
            self.metrics.buckets_processed += 1

            pairs = self._generate_bucket_pairs(record_ids, source_map)
            if pairs:
                cursor_cand.executemany(
                    "INSERT OR IGNORE INTO candidate_pairs VALUES (?, ?)", pairs
                )

        cursor_cand.execute("COMMIT")

    def _generate_bucket_pairs(
        self, record_ids: list[int], source_map: dict[int, str] | None
    ) -> list[tuple[int, int]]:
        """Genera todos los pares (i<j) de un bucket, vectorizado.

        v2.3.0: reemplaza el doble bucle Python ``for i: for j:`` por
        ``np.triu_indices``, que produce las combinaciones en C. Para buckets
        grandes (hasta max_bucket_size) esto es sustancialmente más rápido. La
        semántica es idéntica: pares ordenados (menor, mayor), opcionalmente
        filtrados a cross-source.
        """
        n = len(record_ids)
        if n < 2:
            return []

        ids = np.asarray(record_ids, dtype=np.int64)
        # Índices de la parte triangular superior (todos los pares i<j).
        ii, jj = np.triu_indices(n, k=1)
        a = ids[ii]
        b = ids[jj]
        # Ordenar cada par (menor, mayor) de forma vectorizada.
        lo = np.minimum(a, b)
        hi = np.maximum(a, b)

        if source_map:
            # Filtro cross-source: descartar pares de la misma fuente.
            src = np.array([source_map.get(int(x)) for x in ids], dtype=object)
            keep = src[ii] != src[jj]
            lo = lo[keep]
            hi = hi[keep]

        return list(zip(lo.tolist(), hi.tolist(), strict=False))

    def _count_candidates(self, conn: sqlite3.Connection) -> int:
        """Cuenta candidatos."""
        return conn.execute("SELECT COUNT(*) FROM candidate_pairs").fetchone()[0]

    def _save_candidates_checkpoint(self, conn: sqlite3.Connection, completed_bands: int) -> None:
        """Guarda checkpoint de candidatos."""
        conn.execute("UPDATE _progress SET completed_bands = ? WHERE id = 1", (completed_bands,))
        conn.commit()

    def _load_candidates_checkpoint(self) -> dict[str, Any] | None:
        """Carga checkpoint de candidatos."""
        if not self._candidates_db_file or not self._candidates_db_file.exists():
            return None
        try:
            with self._get_sqlite_connection(self._candidates_db_file, readonly=True) as conn:
                result = conn.execute(
                    "SELECT completed_bands FROM _progress WHERE id = 1"
                ).fetchone()
                return {"completed_bands": result[0]} if result else None
        except Exception:
            return None

    # ═══════════════════════════════════════════════════════════════════════════
    # DECISIÓN DE RETORNO
    # ═══════════════════════════════════════════════════════════════════════════

    def _decide_return_format(self) -> set[tuple[int, int]] | str:
        """Decide formato de retorno."""
        n = self.metrics.candidates_found

        if self._force_disk or n > self._memory_threshold:
            self.logger.info(f"💾 Retornando DB ({n:,} pares)")
            return str(self._candidates_db_file)

        self.logger.info(f"📥 Cargando {n:,} candidatos a memoria...")
        return self._load_candidates_to_memory()

    def _load_candidates_to_memory(self) -> set[tuple[int, int]]:
        """Carga candidatos a memoria."""
        candidates: set[tuple[int, int]] = set()

        with self._get_sqlite_connection(self._candidates_db_file, readonly=True) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT idx_0, idx_1 FROM candidate_pairs")
            while True:
                rows = cursor.fetchmany(50_000)
                if not rows:
                    break
                candidates.update((r[0], r[1]) for r in rows)

        return candidates

    # ═══════════════════════════════════════════════════════════════════════════
    # CHECKPOINTING
    # ═══════════════════════════════════════════════════════════════════════════

    def _save_checkpoint(self, data: dict[str, Any]) -> None:
        """Guarda checkpoint."""
        if not self._checkpoint_file:
            return

        data["timestamp"] = time.time()
        data["version"] = self.VERSION

        temp = self._checkpoint_file.with_suffix(".tmp")
        with open(temp, "w") as f:
            json.dump(data, f)
        temp.replace(self._checkpoint_file)

    def _load_checkpoint(self) -> dict[str, Any] | None:
        """Carga checkpoint."""
        if not self._checkpoint_file or not self._checkpoint_file.exists():
            return None
        try:
            with open(self._checkpoint_file) as f:
                data = json.load(f)
            return data if data.get("version") == self.VERSION else None
        except Exception:
            return None

    # ═══════════════════════════════════════════════════════════════════════════
    # UTILIDADES
    # ═══════════════════════════════════════════════════════════════════════════

    @contextmanager
    def _get_sqlite_connection(
        self, db_path: Path, readonly: bool = False
    ) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager para conexiones SQLite con manejo de corrupción y latencia de Drive.
        Versión corregida V4.2 - Incluye lógica de reintento (Retry) para lectura.
        """
        # Asegurar que sea un objeto Path
        db_path = Path(db_path)

        # Intentar conectar
        try:
            if readonly:
                # --- CORRECCIÓN: Lógica de Reintento para Google Drive ---
                # Si el archivo no aparece inmediatamente, esperar hasta 10 segundos
                if not db_path.exists():
                    self.logger.warning(
                        f"⏳ Esperando sincronización de archivo en disco: {db_path.name}..."
                    )
                    for i in range(5):
                        time.sleep(2)  # Esperar 2 segundos
                        if db_path.exists():
                            self.logger.info(f"✅ Archivo detectado tras {(i + 1) * 2}s.")
                            break

                # Si después de esperar sigue sin existir, lanzar error
                if not db_path.exists():
                    raise FileNotFoundError(f"Base de datos no encontrada tras espera: {db_path}")

                conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            else:
                conn = sqlite3.connect(str(db_path))
        except sqlite3.DatabaseError as e:
            self.logger.error(f"❌ BD Corrupta detectada al conectar: {db_path} - {e}")
            # Si estamos en modo escritura, intentar eliminar y reintentar
            if not readonly:
                try:
                    if db_path.exists():
                        db_path.unlink()
                    shm = db_path.with_suffix(".db-shm")
                    wal = db_path.with_suffix(".db-wal")
                    if shm.exists():
                        shm.unlink()
                    if wal.exists():
                        wal.unlink()
                    self.logger.warning(
                        "🧹 Archivos corruptos eliminados. Reintentando conexión nueva..."
                    )
                    conn = sqlite3.connect(str(db_path))
                except Exception as cleanup_error:
                    raise RuntimeError(
                        f"No se pudo recuperar la BD corrupta: {cleanup_error}"
                    ) from e
            else:
                raise

        try:
            cursor = conn.cursor()
            # CONFIGURACIÓN OPTIMIZADA PERO SEGURA
            optimizations = {
                "journal_mode": "OFF",  # Mantener OFF para ahorrar espacio en Drive
                "synchronous": "NORMAL",  # ← CAMBIO: NORMAL es más lento pero seguro en Drive
                "cache_size": -512000,  # ~500MB RAM cache
                "temp_store": "MEMORY",  # Temporales en RAM
                "mmap_size": 268435456,  # 256MB mmap
                "locking_mode": "EXCLUSIVE",  # Evita overhead de locks
            }

            for pragma, value in optimizations.items():
                with suppress(sqlite3.Error):
                    cursor.execute(f"PRAGMA {pragma} = {value}")

            self._active_connections.append(conn)
            yield conn

        except sqlite3.DatabaseError as e:
            self.logger.error(f"❌ Error de base de datos durante operación: {e}")
            raise
        finally:
            if conn in self._active_connections:
                self._active_connections.remove(conn)
            # Cerrar conexión de forma segura
            with suppress(Exception):
                conn.close()
