"""
golden.generator — record_linkage_pipeline

Componentes:
    - class GoldenRecordGeneratorV7  (origen: notebook celda [126])

NOTA: Lógica de negocio preservada exactamente como en el notebook
fuente. Solo se agregan imports, docstring de módulo y se eliminan
directivas de Jupyter (%%time, !pip, etc.). Ver MIGRATION_LOG.md.
"""

from __future__ import annotations

import gc
import logging
import os
import re
import shutil
import tempfile
import time
import unicodedata
from functools import lru_cache
from typing import Any

import numpy as np
import pandas as pd
from rapidfuzz.distance import Levenshtein
from tqdm import tqdm

from .selector import AdvancedValueSelector
from .utils import MemoryMonitor, SafeSQLiteConnection


class GoldenRecordGeneratorV7:
    """
    Versión optimizada para producción con:
    - Procesamiento 100% vectorizado
    - Escritura optimizada a disco con chunks masivos
    - Construcción incremental de tabla correlativa
    - Gestión inteligente de memoria
    """

    # Configuración de constantes
    MIN_NAME_LENGTH = 5
    MIN_NIT_LENGTH = 6
    DEFAULT_BATCH_SIZE = 30_000
    DEFAULT_BUFFER_SIZE = 10_000
    MEMORY_THRESHOLD_GB = 1.5
    SQLITE_MAX_VARIABLES = 32000  # Límite conservador de SQLite

    def __init__(self, source_priority: list[str], config: dict[str, Any] | None = None):
        """
        Inicializa el generador con configuración optimizada.

        Args:
            source_priority: Lista de fuentes en orden de prioridad
            config: Configuración opcional del generador

        v3.2.5 (FASE 2): si `config` contiene `source_quality_weights` (dict
        de pesos numéricos por fuente), se propaga al `AdvancedValueSelector`
        para desempates en nombres.
        """
        self.source_priority_list = source_priority
        self.source_priority_map = {src: i for i, src in enumerate(source_priority)}

        # v3.2.5: extraer pesos numéricos si están disponibles en el config
        # del perfil activo. Mantiene retrocompatibilidad: si no existen, el
        # selector usa solo el orden de prioridad (comportamiento <= v3.2.4).
        source_quality_weights: dict[str, float] | None = None
        if config:
            # Buscar en el perfil activo dentro de profiles{}, y también top-level
            active_profile_name = config.get("profile")
            if active_profile_name and "profiles" in config:
                active_prof = config["profiles"].get(active_profile_name, {})
                sqw = active_prof.get("source_quality_weights")
                if isinstance(sqw, dict) and sqw:
                    source_quality_weights = {str(k): float(v) for k, v in sqw.items()}
            # Fallback: buscar top-level (algunos pipelines lo pasan ahí)
            if source_quality_weights is None:
                sqw = config.get("source_quality_weights")
                if isinstance(sqw, dict) and sqw:
                    source_quality_weights = {str(k): float(v) for k, v in sqw.items()}

        self.source_quality_weights = source_quality_weights or {}
        self.value_selector = AdvancedValueSelector(
            self.source_priority_map,
            source_quality_weights=source_quality_weights,
        )  # Instanciar el selector avanzado

        # v3.2.7 (FASE 4): min_sources_for_golden — filtro post-generación.
        # Si está definido y > 1, los golden records que provengan de
        # clusters con menos fuentes únicas que el límite son EXCLUIDOS del
        # golden. La correlativa NO se modifica (conserva los registros
        # originales para que el usuario pueda reconstruir si lo necesita).
        # Default None o 0 o 1 → sin filtro (retrocompat).
        # Localización extracción: profiles[active] → top-level → 0.
        min_src_raw: int = 0
        if config:
            active_name = config.get("profile")
            if active_name and "profiles" in config:
                active_prof = config["profiles"].get(active_name, {})
                min_src_raw = int(active_prof.get("min_sources_for_golden") or 0)
            if min_src_raw == 0:
                min_src_raw = int(config.get("min_sources_for_golden") or 0)
        self.min_sources_for_golden: int = max(0, min_src_raw)

        # Configuración con valores optimizados
        cfg = self.config = config or {}
        self.base_batch_size = cfg.get("batch_size", self.DEFAULT_BATCH_SIZE)
        self.buffer_size = cfg.get("buffer_size", self.DEFAULT_BUFFER_SIZE)
        self.memory_threshold = cfg.get("memory_threshold_gb", self.MEMORY_THRESHOLD_GB)
        self.sqlite_max_vars = cfg.get("sqlite_max_variables", self.SQLITE_MAX_VARIABLES)

        # Logger configurado
        self.logger = self._setup_logger()

        # Regex precompilados para rendimiento
        self.SOCIETARY_PATTERNS_REGEX = re.compile(
            r"\b(S\.?A\.?S\.?|S\.?A\.?|LTDA\.?|LIMITADA|E\.?U\.?)\b", re.IGNORECASE
        )
        self.STOPWORDS_REGEX = re.compile(
            r"\b(GRUPO|HOLDING|INTERNACIONAL|COMERCIALIZADORA|SERVICIOS)\b", re.IGNORECASE
        )
        self.COMMON_CONNECTORS_REGEX = re.compile(r"\b(DE|LA|EL|Y|AND|OF)\b", re.IGNORECASE)

        # Cachés controladas
        self._fingerprint_cache = {}
        self._dv_cache = {}
        self.temp_dir = None

    def _setup_logger(self) -> logging.Logger:
        """Configura logger con formato optimizado."""
        logger = logging.getLogger("GoldenRecordGeneratorV7_Production")
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s | %(name)s | %(levelname)s | %(message)s", datefmt="%H:%M:%S"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
        return logger

    def generate(self, df_linked: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        API principal - genera golden records con arquitectura optimizada.

        Args:
            df_linked: DataFrame con registros linkados

        Returns:
            Tupla (golden_records, correlative_table)
        """
        initial_memory = MemoryMonitor.get_memory_status()
        self.logger.info("🚀 Iniciando procesamiento optimizado V7")
        self.logger.info(
            f"📊 Entrada: {len(df_linked):,} filas → {df_linked['ID_GRUPO'].nunique():,} grupos"
        )
        self.logger.info(
            f"💾 Memoria inicial: {initial_memory['process_memory_gb']:.1f}GB ({initial_memory['memory_percent']:.0f}%)"
        )

        # Limpiar el DataFrame de entrada si viene de una ejecución previa
        columns_to_clean = [
            "source_score",
            "nit_len",
            "nit_is_valid",
            "name_len",
            "name_is_generic",
            "final_quality_score",
            "NIT_FINAL",
            "RAZON_SOCIAL_FINAL",
            "NAME_SIMILARITY_SCORE",
            "NIT_DISTANCE",
            "CONFIANZA",
        ]

        existing_temp_cols = [col for col in columns_to_clean if col in df_linked.columns]
        if existing_temp_cols:
            self.logger.info(f"🧹 Limpiando {len(existing_temp_cols)} columnas de ejecución previa")
            df_linked = df_linked.drop(columns=existing_temp_cols)

        self.temp_dir = tempfile.mkdtemp(prefix="golden_v7_prod_")

        try:
            in_db = os.path.join(self.temp_dir, "input.db")
            out_db = os.path.join(self.temp_dir, "output.db")

            # Pipeline optimizado
            start_time = time.time()

            # Fase 1: Escritura optimizada
            self._save_dataframe_optimized(df_linked, in_db)

            # Fase 2: Procesamiento vectorizado
            self._process_vectorized_batches(in_db, out_db)

            # Fase 3: Carga directa sin merge masivo
            golden, correl = self._load_results_from_db(out_db)

            elapsed_time = time.time() - start_time
            final_memory = MemoryMonitor.get_memory_status()

            self.logger.info(f"✅ Completado en {elapsed_time:.1f}s")
            self.logger.info(f"📊 Resultado: {len(golden):,} golden records")
            self.logger.info(f"💾 Memoria final: {final_memory['process_memory_gb']:.1f}GB")

            return golden, correl

        except Exception as e:
            self.logger.error(f"❌ Error en procesamiento: {e}", exc_info=True)
            raise
        finally:
            self._cleanup_resources()

    def _save_dataframe_optimized(self, df: pd.DataFrame, db_path: str):
        """
        Guarda DataFrame con escritura optimizada y chunks calculados dinámicamente.
        Maneja dinámicamente todas las columnas del DataFrame incluyendo las del preprocesamiento.
        """
        start_time = time.time()

        # Limpiar columnas temporales si existen (de ejecuciones previas)
        temp_cols = [
            "source_score",
            "nit_len",
            "nit_is_valid",
            "name_len",
            "name_is_generic",
            "final_quality_score",
        ]
        cols_to_drop = [col for col in temp_cols if col in df.columns]
        if cols_to_drop:
            self.logger.info(
                f"🧹 Eliminando columnas temporales de ejecución previa: {cols_to_drop}"
            )
            df = df.drop(columns=cols_to_drop)

        # Si ya existen columnas FINAL de una ejecución previa, las eliminamos
        final_cols = ["NIT_FINAL", "RAZON_SOCIAL_FINAL", "NAME_SIMILARITY_SCORE", "NIT_DISTANCE"]
        final_cols_to_drop = [col for col in final_cols if col in df.columns]
        if final_cols_to_drop:
            self.logger.info(
                f"🧹 Eliminando columnas finales de ejecución previa: {final_cols_to_drop}"
            )
            df = df.drop(columns=final_cols_to_drop)

        # Validar columnas mínimas requeridas
        required_cols = ["ID_GRUPO", "NIT", "RAZON_SOCIAL", "SRC"]
        missing = [c for c in required_cols if c not in df.columns]

        if missing:
            raise KeyError(f"Faltan columnas requeridas: {missing}")

        # Añadir índice original si no existe
        if "ORIGINAL_INDEX" not in df.columns:
            df = df.copy()
            df["ORIGINAL_INDEX"] = np.arange(len(df), dtype=np.int32)

        # Log de columnas detectadas
        self.logger.info(f"📋 Columnas a guardar: {list(df.columns)}")

        # Optimizar tipos de datos
        df_opt = self._optimize_dataframe_types(df)

        # Calcular chunk size seguro basado en número de columnas
        num_columns = len(df_opt.columns)
        # Usar 90% del límite para tener margen de seguridad
        safe_chunk_size = int((self.sqlite_max_vars * 0.9) // num_columns)
        # Limitar entre valores razonables
        safe_chunk_size = min(safe_chunk_size, 10_000)  # Máximo 10k por chunk
        safe_chunk_size = max(safe_chunk_size, 100)  # Mínimo 100 por chunk

        total_rows = len(df_opt)
        total_chunks = (total_rows + safe_chunk_size - 1) // safe_chunk_size

        self.logger.info(
            f"💾 Guardando {total_rows:,} registros en {total_chunks:,} chunks de {safe_chunk_size:,} filas"
        )
        self.logger.info(
            f"   (SQLite límite: {self.sqlite_max_vars:,} variables, {num_columns} columnas)"
        )

        with SafeSQLiteConnection(db_path, "rw") as conn:
            cursor = conn.cursor()

            try:
                # Crear tabla dinámicamente basada en las columnas del DataFrame
                cursor.execute("DROP TABLE IF EXISTS correlative_table")

                # Generar definición de columnas dinámicamente
                # Esto asegura que TODAS las columnas del DataFrame estén en la tabla
                column_definitions = []
                for col in df_opt.columns:
                    if col == "ID_GRUPO" or col == "ORIGINAL_INDEX":
                        column_definitions.append(f'"{col}" INTEGER')
                    else:
                        column_definitions.append(f'"{col}" TEXT')

                create_table_sql = f"""
                    CREATE TABLE correlative_table (
                        {", ".join(column_definitions)}
                    )
                """

                self.logger.info(f"Creando tabla con {len(df_opt.columns)} columnas")
                cursor.execute(create_table_sql)

                # Iniciar transacción masiva
                cursor.execute("BEGIN TRANSACTION")

                # Insertar por chunks con progreso
                with tqdm(total=total_rows, unit="reg", desc="💾 Guardando") as pbar:
                    for i in range(0, total_rows, safe_chunk_size):
                        chunk = df_opt.iloc[i : i + safe_chunk_size]

                        # Usar to_sql con if_exists='append' para todos los chunks
                        chunk.to_sql(
                            "correlative_table",
                            conn,
                            index=False,
                            if_exists="append",
                            method="multi",
                        )

                        pbar.update(len(chunk))

                        # Commit periódico cada 50 chunks para evitar transacciones gigantes
                        if (i // safe_chunk_size) % 50 == 49:
                            conn.commit()
                            cursor.execute("BEGIN TRANSACTION")

                # Commit final
                conn.commit()

                # Crear índices después del commit
                self._create_input_indexes(conn)

            except Exception as e:
                conn.rollback()
                self.logger.error(f"Error en escritura: {e}")
                # Intentar con chunks más pequeños como fallback
                self.logger.info("Reintentando con chunks más pequeños...")
                return self._save_dataframe_fallback(df_opt, db_path)

        elapsed = time.time() - start_time
        self.logger.info(
            f"✅ Guardado completado en {elapsed:.1f}s ({total_rows / elapsed:.0f} filas/s)"
        )

    def _save_dataframe_fallback(self, df_opt: pd.DataFrame, db_path: str):
        """
        Método de respaldo para guardar con chunks muy pequeños si falla el método principal.
        """
        self.logger.warning("🔄 Ejecutando método fallback con chunks pequeños...")

        # Usar chunks muy pequeños para máxima compatibilidad
        fallback_chunk_size = 500
        total_rows = len(df_opt)

        self.logger.info(
            f"🔄 Modo fallback: {total_rows:,} filas en chunks de {fallback_chunk_size}"
        )

        with SafeSQLiteConnection(db_path, "rw") as conn:
            cursor = conn.cursor()

            # Recrear tabla con esquema dinámico
            cursor.execute("DROP TABLE IF EXISTS correlative_table")

            # Crear tabla con todas las columnas del DataFrame
            column_definitions = []
            for col in df_opt.columns:
                if col in ["ID_GRUPO", "ORIGINAL_INDEX"]:
                    column_definitions.append(f'"{col}" INTEGER')
                else:
                    column_definitions.append(f'"{col}" TEXT')

            create_table_sql = f"""
                CREATE TABLE correlative_table (
                    {", ".join(column_definitions)}
                )
            """
            cursor.execute(create_table_sql)
            conn.commit()

            # Insertar en chunks pequeños con progreso
            with tqdm(total=total_rows, unit="reg", desc="💾 Guardando (fallback)") as pbar:
                for i in range(0, total_rows, fallback_chunk_size):
                    chunk = df_opt.iloc[i : i + fallback_chunk_size]

                    try:
                        chunk.to_sql(
                            "correlative_table",
                            conn,
                            index=False,
                            if_exists="append",
                            method=None,  # Método básico, más lento pero más seguro
                        )
                        pbar.update(len(chunk))

                        # Commit frecuente en modo fallback
                        if i % (fallback_chunk_size * 10) == 0:
                            conn.commit()
                    except Exception as e:
                        self.logger.error(f"Error en chunk {i // fallback_chunk_size}: {e}")
                        # Continuar con el siguiente chunk
                        continue

            conn.commit()

            # Crear índices
            self._create_input_indexes(conn)

        self.logger.info("✅ Fallback completado")

    def _optimize_dataframe_types(self, df: pd.DataFrame) -> pd.DataFrame:
        """Optimiza tipos de datos para reducir memoria."""
        df_opt = df.copy()

        # Definir columnas conocidas
        text_cols_base = ["NIT", "RAZON_SOCIAL", "NIT_OK", "SRC"]
        text_cols_extra = [
            "NOMBRE_LIMPIO",
            "NIT_CLEAN",
            "NIT_BASE",
        ]  # Columnas del preprocesamiento

        # Procesar columnas de texto conocidas
        for col in text_cols_base + text_cols_extra:
            if col in df_opt.columns:
                if col == "SRC":  # SRC tiene pocos valores únicos
                    # Verificar si ya es categoría
                    if df_opt[col].dtype.name != "category":
                        try:
                            df_opt[col] = df_opt[col].astype("category")
                        except Exception:
                            df_opt[col] = df_opt[col].astype("string").fillna("")
                else:
                    # Convertir a string si no lo es ya
                    if df_opt[col].dtype == "object":
                        df_opt[col] = df_opt[col].astype("string").fillna("")
                    elif df_opt[col].dtype.name == "category":
                        # Si ya es categoría, dejarla así
                        pass

        # Procesar cualquier otra columna de texto no especificada
        for col in df_opt.columns:
            if col not in text_cols_base + text_cols_extra + ["ID_GRUPO", "ORIGINAL_INDEX"]:
                if df_opt[col].dtype == "object":
                    # Convertir objetos a string
                    df_opt[col] = df_opt[col].astype("string").fillna("")

        # Optimizar enteros
        if "ID_GRUPO" in df_opt.columns and df_opt["ID_GRUPO"].dtype != np.int32:
            max_val = df_opt["ID_GRUPO"].max()
            if max_val < 2**31:
                df_opt["ID_GRUPO"] = df_opt["ID_GRUPO"].astype(np.int32)

        if "ORIGINAL_INDEX" in df_opt.columns:
            if df_opt["ORIGINAL_INDEX"].dtype != np.int32:
                df_opt["ORIGINAL_INDEX"] = df_opt["ORIGINAL_INDEX"].astype(np.int32)

        return df_opt

    def _process_vectorized_batches(self, in_db: str, out_db: str):
        """
        Procesamiento completamente vectorizado sin bucles iterativos.
        Mejora clave: operaciones vectoriales y construcción incremental.
        """
        with SafeSQLiteConnection(in_db, "ro") as cin, SafeSQLiteConnection(out_db, "rw") as cout:
            # Preparar base de datos de salida con dos tablas
            self._prepare_output_database_v2(cout)

            # Analizar estructura de grupos
            cur_in = cin.cursor()
            total_groups = cur_in.execute(
                "SELECT COUNT(DISTINCT ID_GRUPO) FROM correlative_table"
            ).fetchone()[0]
            min_group = cur_in.execute("SELECT MIN(ID_GRUPO) FROM correlative_table").fetchone()[0]
            max_group = cur_in.execute("SELECT MAX(ID_GRUPO) FROM correlative_table").fetchone()[0]

            self.logger.info(
                f"📊 Procesando {total_groups:,} grupos (rango: {min_group:,}-{max_group:,})"
            )

            # Buffers para escritura eficiente
            golden_buffer = []
            correl_buffer = []
            processed_groups = 0

            with tqdm(
                total=total_groups, unit="grupo", desc="🔄 Procesamiento vectorizado"
            ) as pbar:
                current_group = min_group

                while current_group <= max_group:
                    # Calcular batch size dinámico
                    batch_size = MemoryMonitor.calculate_optimal_batch_size(self.base_batch_size)
                    batch_end = min(current_group + batch_size - 1, max_group)

                    # Cargar batch completo con todas las columnas
                    batch_query = """
                        SELECT *
                        FROM correlative_table
                        WHERE ID_GRUPO BETWEEN ? AND ?
                        ORDER BY ID_GRUPO
                    """
                    batch_df = pd.read_sql_query(
                        batch_query, cin, params=(current_group, batch_end)
                    )

                    if not batch_df.empty:
                        # Limpiar columnas de procesamiento previo si existen
                        cols_to_clean = [
                            "source_score",
                            "nit_len",
                            "nit_is_valid",
                            "name_len",
                            "name_is_generic",
                            "final_quality_score",
                            "NIT_FINAL",
                            "RAZON_SOCIAL_FINAL",
                        ]
                        existing_cols = [col for col in cols_to_clean if col in batch_df.columns]
                        if existing_cols:
                            batch_df = batch_df.drop(columns=existing_cols)

                        # PROCESAMIENTO VECTORIZADO
                        golden_batch, correl_batch = self._process_batch_vectorized(batch_df)

                        # Añadir a buffers
                        golden_buffer.extend(golden_batch.to_dict("records"))
                        correl_buffer.extend(correl_batch.to_dict("records"))

                        # Actualizar progreso
                        groups_in_batch = batch_df["ID_GRUPO"].nunique()
                        processed_groups += groups_in_batch
                        pbar.update(groups_in_batch)

                    # Escribir buffers cuando sea necesario
                    if len(golden_buffer) >= self.buffer_size:
                        self._write_buffer_to_table(cout, golden_buffer, "golden_records")
                        golden_buffer = []

                    if len(correl_buffer) >= self.buffer_size * 2:
                        self._write_buffer_to_table(cout, correl_buffer, "correlative_table")
                        correl_buffer = []

                    # Gestión inteligente de memoria
                    if MemoryMonitor.should_clear_memory(self.memory_threshold):
                        self._intelligent_memory_cleanup()

                    current_group = batch_end + 1

            # Escribir buffers finales
            if golden_buffer:
                self._write_buffer_to_table(cout, golden_buffer, "golden_records")
            if correl_buffer:
                self._write_buffer_to_table(cout, correl_buffer, "correlative_table")

            cout.commit()

            # Añadir métricas de calidad e índices
            self._add_quality_metrics(cout)
            self._create_output_indexes(cout)

    def _process_batch_vectorized(
        self, batch_df: pd.DataFrame
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Procesa un batch completo usando operaciones vectorizadas.
        Sin bucles iterativos - todo vectorial.

        Mejoras implementadas:
        - Delega la selección de nombres y NITs al AdvancedValueSelector
        - Calcula métricas sobre columnas originales para reflejar variación real
        - Mantiene consistencia en el procesamiento de datos
        """
        # Limpiar columnas de scoring si ya existen
        score_cols = [
            "source_score",
            "nit_len",
            "nit_is_valid",
            "name_len",
            "name_is_generic",
            "final_quality_score",
        ]
        for col in score_cols:
            if col in batch_df.columns:
                batch_df = batch_df.drop(columns=[col])

        # 1. SISTEMA DE PUNTUACIÓN DE CALIDAD
        batch_df = self._calculate_quality_scores(batch_df)

        # 2. APLICAR ALGORITMOS DE CONSENSO (VECTORIZADO POR LOTES — v2.4.0)
        # Antes: dos groupby().apply(lambda g: select_best_*(g)) — un bucle Python
        # por grupo, el 40 % del tiempo del pipeline en datos reales. Ahora se usa
        # la API batch del selector, que procesa todos los grupos en una pasada
        # vectorizada con paridad bit-a-bit (test_golden_selector_paridad.py).
        golden_names = self.value_selector.select_best_name_batch(batch_df, "ID_GRUPO")
        golden_nits = self.value_selector.select_best_nit_batch(batch_df, "ID_GRUPO")

        # 3. CALCULAR MÉTRICAS (vectorizado)
        # CORRECCIÓN: Asegurarse de que las métricas también usen la columna original.
        name_col_original = "RAZON_SOCIAL"
        nit_col_ok = "NIT_OK" if "NIT_OK" in batch_df.columns else "NIT"

        # PRIMARY_SOURCE vectorizado: la fuente de menor prioridad por grupo.
        # v2.4.0: antes era un lambda min(key=...) por grupo. Ahora se precomputa
        # la prioridad como columna y se toma, por grupo, la fila de prioridad
        # mínima (idxmin). Equivalente exacto.
        bm = batch_df[["ID_GRUPO", "SRC"]].copy()
        bm["__prio"] = bm["SRC"].map(self.source_priority_map).fillna(999)
        bm = bm.sort_values(["ID_GRUPO", "__prio"], kind="stable")
        primary_source = bm.drop_duplicates("ID_GRUPO", keep="first").set_index("ID_GRUPO")["SRC"]

        group_metrics = batch_df.groupby("ID_GRUPO").agg(
            SOURCES_LIST=("SRC", lambda s: "|".join(sorted(s.unique()))),
            SOURCES_COUNT=("SRC", "nunique"),
            RECORD_COUNT=("SRC", "size"),
            # Se calcula la variación sobre la columna original.
            NAME_VARIATIONS=(name_col_original, "nunique"),
            NIT_VARIATIONS=(nit_col_ok, "nunique"),
        )
        group_metrics["PRIMARY_SOURCE"] = primary_source

        # 5. CONSTRUIR GOLDEN RECORDS
        golden_df = pd.DataFrame(
            {
                "ID_GRUPO": golden_names.index,
                "NIT_FINAL": golden_nits.values,
                "RAZON_SOCIAL_FINAL": golden_names.values,
            }
        )
        golden_df = golden_df.merge(group_metrics, on="ID_GRUPO", how="left")

        # ── Paso 1.5: Confianza (VECTORIZADO con np.select — v2.4.0) ──
        # Reproduce _calcular_confianza sin apply(axis=1):
        #   ALTA  — NIT único (NIT_VARIATIONS==1) y ≥2 fuentes
        #   MEDIA — ≤2 NITs y grupo pequeño (≤5 miembros)
        #   BAJA  — resto
        nit_vars = golden_df["NIT_VARIATIONS"].fillna(1)
        fuentes = golden_df["SOURCES_COUNT"].fillna(1)
        miembros = golden_df["RECORD_COUNT"].fillna(1)
        golden_df["CONFIANZA"] = np.select(
            [
                (nit_vars == 1) & (fuentes >= 2),
                (nit_vars <= 2) & (miembros <= 5),
            ],
            ["ALTA", "MEDIA"],
            default="BAJA",
        )

        # 6. CONSTRUIR TABLA CORRELATIVA
        # Eliminar columnas finales anteriores si existen
        final_cols = ["NIT_FINAL", "RAZON_SOCIAL_FINAL"]
        for col in final_cols:
            if col in batch_df.columns:
                batch_df = batch_df.drop(columns=[col])

        # Hacer merge con los nuevos valores finales
        correl_df = batch_df.merge(
            golden_df[["ID_GRUPO", "NIT_FINAL", "RAZON_SOCIAL_FINAL"]], on="ID_GRUPO", how="left"
        )

        return golden_df, correl_df

    @staticmethod
    def _calcular_confianza(row) -> str:
        """
        Asigna nivel de confianza ALTA/MEDIA/BAJA basado en evidencia del grupo.

        Reglas:
          ALTA  — NIT único + más de una fuente confirma
          MEDIA — NIT único con una sola fuente, o ≤2 NITs con grupo pequeño
          BAJA  — Múltiples NITs, o grupo muy grande (>5 miembros)

        Paso 1.5 del Plan Maestro.
        """
        nit_vars = row.get("NIT_VARIATIONS", 1)
        fuentes = row.get("SOURCES_COUNT", 1)
        n_miembros = row.get("RECORD_COUNT", 1)

        # ALTA: NIT único confirmado por múltiples fuentes
        if nit_vars == 1 and fuentes >= 2:
            return "ALTA"

        # MEDIA: NIT único pero solo una fuente,
        #        o hasta 2 NITs con grupo pequeño (≤5)
        elif nit_vars <= 2 and n_miembros <= 5:
            return "MEDIA"

        # BAJA: Múltiples NITs, o grupo demasiado grande
        else:
            return "BAJA"

    def _calculate_quality_scores(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Calcula scores de calidad para cada registro (100% vectorizado).
        Maneja columnas opcionales del preprocesamiento.
        """
        # Hacer una copia para evitar modificar el DataFrame original
        df = df.copy()

        # Score de fuente (menor prioridad = mejor score)
        df["source_score"] = df["SRC"].map(self.source_priority_map).fillna(999)

        # Score de calidad de NIT
        # Usar NIT_OK si existe, si no usar NIT
        nit_col = "NIT_OK" if "NIT_OK" in df.columns else "NIT"
        df["nit_len"] = df[nit_col].str.len().fillna(0)
        df["nit_is_valid"] = (
            (df["nit_len"].isin([9, 10])) & (df[nit_col].str.isdigit().fillna(False))
        ).astype(int)

        # Score de calidad de nombre
        # Usar NOMBRE_LIMPIO si existe, si no usar RAZON_SOCIAL
        name_col = "NOMBRE_LIMPIO" if "NOMBRE_LIMPIO" in df.columns else "RAZON_SOCIAL"
        df["name_len"] = df[name_col].str.len().fillna(0)
        df["name_is_generic"] = (
            df[name_col]
            .str.contains("SIN NOMBRE|NO REGISTRA|NO REPORTA", na=False, case=False)
            .astype(int)
        )

        # Score final combinado (diseñado para que sort descendente = mejor primero)
        df["final_quality_score"] = (
            -df["source_score"] * 1_000_000  # Prioridad de fuente domina
            + df["nit_is_valid"] * 10_000  # NITs válidos segundo
            + df["name_len"] * 100  # Nombres largos tercero
            - df["name_is_generic"] * 50_000  # Penalización por genéricos
        )

        return df

    def _select_best_name_vectorized(self, names_series: pd.Series) -> str:
        """Selección de nombre optimizada para vectorización."""
        valid_names = names_series.dropna()

        # Convertir a string y filtrar vacíos
        valid_names = valid_names.astype(str)
        valid_names = valid_names[valid_names.str.strip() != ""]

        if valid_names.empty:
            return ""

        # Aplicar fingerprinting y seleccionar el más común
        fingerprints = valid_names.apply(self._get_fingerprint)

        if not fingerprints.empty:
            # Encontrar el fingerprint más común
            fp_counts = fingerprints.value_counts()
            if not fp_counts.empty:
                best_fp = fp_counts.index[0]
                # De los nombres con ese fingerprint, elegir el más largo
                candidates = valid_names[fingerprints == best_fp]
                if not candidates.empty:
                    return max(candidates, key=len)

        # Fallback: nombre más común
        return valid_names.value_counts().index[0] if not valid_names.empty else ""

    def _select_best_nit_vectorized(self, nits_series: pd.Series) -> str:
        """Selección de NIT optimizada para vectorización."""
        valid_nits = nits_series.dropna()

        # Convertir a string y filtrar solo dígitos
        valid_nits = valid_nits.astype(str)
        valid_nits = valid_nits[valid_nits.str.isdigit()]

        if valid_nits.empty:
            return ""

        # Priorizar NITs de 9-10 dígitos
        nit_lengths = valid_nits.str.len()
        enterprise_nits = valid_nits[nit_lengths.isin([9, 10])]

        if not enterprise_nits.empty:
            # Votación posicional simplificada
            if len(enterprise_nits) == 1:
                nit = enterprise_nits.iloc[0]
                if len(nit) == 9:
                    return nit + self._calculate_dv(nit)
                return nit

            # Tomar el más común
            most_common = enterprise_nits.value_counts()
            if not most_common.empty:
                nit = most_common.index[0]
                if len(nit) == 9:
                    return nit + self._calculate_dv(nit)
                return nit

        # Fallback: NIT más común
        return valid_nits.value_counts().index[0] if not valid_nits.empty else ""

    @lru_cache(maxsize=10_000)
    def _get_fingerprint(self, name: str) -> str:
        """Genera fingerprint con cache para rendimiento."""
        if not name:
            return ""

        # Normalizar y limpiar
        fp = unicodedata.normalize("NFKD", name.upper()).encode("ascii", "ignore").decode()
        fp = self.SOCIETARY_PATTERNS_REGEX.sub("", fp)
        fp = self.STOPWORDS_REGEX.sub("", fp)
        fp = self.COMMON_CONNECTORS_REGEX.sub("", fp)
        fp = re.sub(r"[^A-Z0-9]", "", fp)

        return fp

    @lru_cache(maxsize=5_000)
    def _calculate_dv(self, base: str) -> str:
        """Cálculo optimizado del dígito verificación."""
        if not base or not base.isdigit() or len(base) != 9:
            return ""

        pesos = [3, 7, 13, 17, 19, 23, 29, 37, 41]
        r = sum(int(base[8 - i]) * pesos[i] for i in range(9)) % 11
        return str(r) if r < 2 else str(11 - r)

    def _prepare_output_database_v2(self, conn):
        """Prepara base de datos de salida con dos tablas."""
        cursor = conn.cursor()

        # Tabla de golden records
        cursor.execute("DROP TABLE IF EXISTS golden_records")
        cursor.execute("""
            CREATE TABLE golden_records (
                "ID_GRUPO" INTEGER PRIMARY KEY,
                "NIT_FINAL" TEXT,
                "RAZON_SOCIAL_FINAL" TEXT,
                "PRIMARY_SOURCE" TEXT,
                "SOURCES_LIST" TEXT,
                "SOURCES_COUNT" INTEGER,
                "RECORD_COUNT" INTEGER,
                "NAME_VARIATIONS" INTEGER,
                "NIT_VARIATIONS" INTEGER,
                "CONFIDENCE_SCORE" REAL DEFAULT 0,
                "CONFIANZA" TEXT,
                "REQUIRES_REVIEW" INTEGER DEFAULT 0,
                "CREATED_AT" TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Tabla correlativa - se creará dinámicamente cuando se escriban los datos
        cursor.execute("DROP TABLE IF EXISTS correlative_table")

        conn.commit()

    def _write_buffer_to_table(self, conn, buffer: list[dict], table_name: str):
        """Escritura optimizada a tabla específica."""
        if not buffer:
            return

        df_buffer = pd.DataFrame(buffer)

        # Limpiar columnas temporales del buffer si existen
        temp_cols = [
            "source_score",
            "nit_len",
            "nit_is_valid",
            "name_len",
            "name_is_generic",
            "final_quality_score",
        ]
        cols_to_drop = [col for col in temp_cols if col in df_buffer.columns]
        if cols_to_drop and table_name == "correlative_table":
            df_buffer = df_buffer.drop(columns=cols_to_drop)

        # Para la tabla correlativa, crear la tabla si no existe con esquema dinámico
        if table_name == "correlative_table":
            cursor = conn.cursor()
            # Verificar si la tabla existe
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='correlative_table'
            """)
            if not cursor.fetchone():
                # Crear tabla con esquema dinámico basado en el buffer
                column_definitions = []
                for col in df_buffer.columns:
                    if col in ["ID_GRUPO", "ORIGINAL_INDEX"]:
                        column_definitions.append(f'"{col}" INTEGER')
                    else:
                        column_definitions.append(f'"{col}" TEXT')

                create_sql = f"""
                    CREATE TABLE correlative_table (
                        {", ".join(column_definitions)}
                    )
                """
                cursor.execute(create_sql)
                conn.commit()

        # Escribir datos
        try:
            df_buffer.to_sql(
                table_name, conn, if_exists="append", index=False, method="multi", chunksize=1000
            )
        except Exception as e:
            self.logger.error(f"Error escribiendo buffer a {table_name}: {e}")
            # Intentar con chunks más pequeños
            df_buffer.to_sql(
                table_name, conn, if_exists="append", index=False, method=None, chunksize=100
            )

    def _add_quality_metrics(self, conn):
        """Añade métricas de calidad a golden records."""
        conn.execute("""
            UPDATE golden_records SET
                "CONFIDENCE_SCORE" = ROUND(
                    CASE
                        WHEN "NIT_VARIATIONS" = 1 AND "NAME_VARIATIONS" = 1 THEN 1.0
                        WHEN "SOURCES_COUNT" = 1 THEN 0.85
                        ELSE
                            (0.5 / MAX(1.0, "NIT_VARIATIONS")) +
                            (0.4 / MAX(1.0, "NAME_VARIATIONS")) +
                            (0.1 * MIN(1.0, "SOURCES_COUNT" / 3.0))
                    END, 4
                ),
                "REQUIRES_REVIEW" = CASE
                    WHEN "NIT_VARIATIONS" > 3 OR "NAME_VARIATIONS" > 5 THEN 1
                    WHEN "RECORD_COUNT" > 20 THEN 1
                    WHEN LENGTH("NIT_FINAL") < 6 THEN 1
                    ELSE 0
                END
        """)
        conn.commit()

    def _create_input_indexes(self, conn):
        """Crea índices en la tabla de entrada."""
        indexes = [
            'CREATE INDEX IF NOT EXISTS idx_id_grupo ON correlative_table("ID_GRUPO")',
            'CREATE INDEX IF NOT EXISTS idx_src_grupo ON correlative_table("SRC", "ID_GRUPO")',
            'CREATE INDEX IF NOT EXISTS idx_original ON correlative_table("ORIGINAL_INDEX")',
        ]
        for idx in indexes:
            try:
                conn.execute(idx)
            except Exception as e:
                self.logger.warning(f"No se pudo crear índice: {e}")
        conn.commit()

    def _create_output_indexes(self, conn):
        """Crea índices en las tablas de salida."""
        indexes = [
            # Golden records
            'CREATE INDEX IF NOT EXISTS idx_golden_nit ON golden_records("NIT_FINAL")',
            'CREATE INDEX IF NOT EXISTS idx_golden_conf ON golden_records("CONFIDENCE_SCORE")',
            'CREATE INDEX IF NOT EXISTS idx_golden_review ON golden_records("REQUIRES_REVIEW")',
            # Correlative
            'CREATE INDEX IF NOT EXISTS idx_correl_grupo ON correlative_table("ID_GRUPO")',
            'CREATE INDEX IF NOT EXISTS idx_correl_original ON correlative_table("ORIGINAL_INDEX")',
        ]
        for idx in indexes:
            try:
                conn.execute(idx)
            except Exception as e:
                self.logger.warning(f"No se pudo crear índice: {e}")
        conn.commit()

    def _load_results_from_db(self, output_db: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Carga resultados directamente desde la base de datos.
        Sin merge masivo - las tablas ya están construidas.
        """
        self.logger.info("📥 Cargando resultados finales...")

        with SafeSQLiteConnection(output_db, "ro") as conn:
            # Cargar golden records
            golden = pd.read_sql_query('SELECT * FROM golden_records ORDER BY "ID_GRUPO"', conn)

            # Cargar tabla correlativa (ya tiene los golden fields)
            # Primero verificar qué columnas existen
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(correlative_table)")
            columns = [col[1] for col in cursor.fetchall()]

            self.logger.info(f"📋 Columnas en correlative_table: {len(columns)} columnas")

            # Determinar columna para ordenar
            order_col = "ORIGINAL_INDEX" if "ORIGINAL_INDEX" in columns else "ID_GRUPO"

            correl = pd.read_sql_query(
                f'SELECT * FROM correlative_table ORDER BY "{order_col}"', conn
            )

        # Verificar si necesitamos añadir métricas de diagnóstico
        if "NAME_SIMILARITY_SCORE" not in correl.columns:
            try:
                correl = self._add_diagnostic_metrics(correl)
            except Exception as e:
                self.logger.warning(f"No se pudieron añadir métricas de diagnóstico: {e}")

        self.logger.info(
            f"✅ Cargados {len(golden):,} golden records y {len(correl):,} registros correlativos"
        )

        # v3.2.7 (FASE 4): filtrar golden por min_sources_for_golden.
        # Política: el filtro se aplica SOLO al golden (no a correlativa)
        # para preservar trazabilidad. Si el usuario necesita los descartados,
        # puede reconstruirlos desde la correlativa.
        if self.min_sources_for_golden > 1 and "ID_GRUPO" in correl.columns:
            golden = self._filter_golden_by_min_sources(golden, correl)

        return golden, correl

    def _filter_golden_by_min_sources(
        self, golden: pd.DataFrame, correl: pd.DataFrame
    ) -> pd.DataFrame:
        """v3.2.7 (FASE 4): excluye del golden los clusters con menos de
        `min_sources_for_golden` fuentes únicas.

        No modifica la correlativa. La operación es idempotente.

        Args:
            golden: DataFrame de golden records.
            correl: DataFrame correlativa con columnas 'ID_GRUPO' y 'SRC'.

        Returns:
            golden filtrado.
        """
        if "SRC" not in correl.columns or "ID_GRUPO" not in correl.columns:
            self.logger.warning(
                "min_sources_for_golden activo pero falta 'SRC' o 'ID_GRUPO' "
                "en correlativa; saltando filtro."
            )
            return golden

        # Contar fuentes únicas por ID_GRUPO
        sources_per_group = correl.groupby("ID_GRUPO")["SRC"].nunique()
        valid_groups = set(
            sources_per_group[sources_per_group >= self.min_sources_for_golden].index
        )

        n_before = len(golden)
        if "ID_GRUPO" not in golden.columns:
            self.logger.warning(
                "golden sin columna 'ID_GRUPO'; saltando filtro min_sources_for_golden."
            )
            return golden

        golden_filtered = golden[golden["ID_GRUPO"].isin(valid_groups)].copy()
        n_excluded = n_before - len(golden_filtered)

        self.logger.info(
            f"🪒 min_sources_for_golden={self.min_sources_for_golden}: "
            f"excluidos {n_excluded:,} golden records "
            f"({n_before:,} → {len(golden_filtered):,})"
        )

        return golden_filtered

    def _add_diagnostic_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Añade métricas de diagnóstico de forma eficiente.
        Maneja columnas opcionales del preprocesamiento.
        """
        # Verificar que las columnas necesarias existan
        required_cols = ["RAZON_SOCIAL_FINAL", "NIT_FINAL"]
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            self.logger.warning(f"Columnas faltantes para métricas de diagnóstico: {missing_cols}")
            self.logger.warning(f"Columnas disponibles: {list(df.columns)}")
            # Retornar el DataFrame sin modificar si faltan columnas críticas
            return df

        # Usar NOMBRE_LIMPIO si existe, si no usar RAZON_SOCIAL
        name_col = "NOMBRE_LIMPIO" if "NOMBRE_LIMPIO" in df.columns else "RAZON_SOCIAL"

        # Verificar que la columna de nombre existe
        if name_col not in df.columns:
            self.logger.warning(
                f"Columna {name_col} no encontrada, saltando métricas de diagnóstico"
            )
            return df

        # Preparar datos
        name1 = df[name_col].fillna("").astype(str)
        name2 = df["RAZON_SOCIAL_FINAL"].fillna("").astype(str)
        nit1 = df.get("NIT", pd.Series(dtype=str)).fillna("").astype(str)
        nit2 = df["NIT_FINAL"].fillna("").astype(str)

        # Similitud de nombres (vectorizado con numpy)
        def calculate_similarity(s1: pd.Series, s2: pd.Series) -> np.ndarray:
            similarities = np.zeros(len(s1))

            for i, (n1, n2) in enumerate(zip(s1, s2, strict=False)):
                if not n1.strip() or not n2.strip():
                    similarities[i] = 0.0
                elif n1 == n2:
                    similarities[i] = 1.0
                else:
                    max_len = max(len(n1), len(n2))
                    if max_len > 0:
                        distance = Levenshtein.distance(n1, n2)
                        similarities[i] = max(0.0, 1.0 - (distance / max_len))

            return similarities

        # Añadir columnas de métricas solo si no existen
        if "NAME_SIMILARITY_SCORE" not in df.columns:
            df["NAME_SIMILARITY_SCORE"] = calculate_similarity(name1, name2)

        if "NIT_DISTANCE" not in df.columns:
            # Distancia de NITs (vectorizado)
            df["NIT_DISTANCE"] = [
                Levenshtein.distance(a, b) if a and b else 0
                for a, b in zip(nit1, nit2, strict=False)
            ]

        return df

    def _intelligent_memory_cleanup(self):
        """Limpieza inteligente de memoria basada en uso actual."""
        mem_status = MemoryMonitor.get_memory_status()

        if mem_status["memory_percent"] > 85:
            # Limpieza agresiva
            self._fingerprint_cache.clear()
            self._dv_cache.clear()
            self._get_fingerprint.cache_clear()
            self._calculate_dv.cache_clear()
            gc.collect()
            self.logger.info("🧹 Limpieza agresiva de memoria ejecutada")
        elif mem_status["memory_percent"] > 75:
            # Limpieza moderada
            if len(self._fingerprint_cache) > 15_000:
                self._fingerprint_cache.clear()
            gc.collect()
        elif len(self._fingerprint_cache) > 30_000:
            # Limpieza preventiva de cachés grandes
            self._fingerprint_cache.clear()

    def _cleanup_resources(self):
        """Limpieza final de recursos."""
        # Limpiar cachés
        self._fingerprint_cache.clear()
        self._dv_cache.clear()

        # Limpiar cachés LRU
        self._get_fingerprint.cache_clear()
        self._calculate_dv.cache_clear()

        # Eliminar directorio temporal
        if self.temp_dir and os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except Exception as e:
                self.logger.warning(f"No se pudo limpiar temp_dir: {e}")

        # Forzar recolección de basura
        gc.collect()

        self.logger.info("🧹 Recursos liberados")
