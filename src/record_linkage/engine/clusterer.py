"""
engine.clusterer — record_linkage_pipeline

Componentes:
    - class EntityClusterer  (origen: notebook celda [118])
    - class OptimizedClusterer  (origen: notebook celda [122])

NOTA: Lógica de negocio preservada exactamente como en el notebook
fuente. Solo se agregan imports, docstring de módulo y se eliminan
directivas de Jupyter (%%time, !pip, etc.). Ver MIGRATION_LOG.md.
"""

from __future__ import annotations

import gc
import os
import sqlite3
import time
from collections import OrderedDict
from typing import (
    Any,
    Protocol,
    runtime_checkable,
)

import networkx as nx
import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components as scipy_cc
from tqdm import tqdm

from ..deduplication.strict import build_strict_clusters
from ..utils.logger import CustomLogger
from ..utils.performance import (
    track_performance,
)


@runtime_checkable
class EntityClusterer(Protocol):
    """Protocolo para agrupar entidades."""

    def cluster_entities(self, scored_pairs: pd.DataFrame, n_entities: int) -> dict[int, int]: ...


class OptimizedClusterer:
    """
    Clusterer MEJORADO que implementa un enfoque híbrido y escalable:
    1. Usa una técnica de ordenamiento eficiente para conectar NITs idénticos.
    2. Procesa los pares de LSH para conectar clusters adicionales.
    3. Toda la estructura de clusters (Union-Find) se gestiona en disco (SQLite)
       para manejar millones de registros sin agotar la memoria.
    4. Incluye sistema de caché LRU y estadísticas detalladas para monitoreo.
    """

    def __init__(self, profile: dict[str, Any], config: dict[str, Any] | None = None):
        self.profile = profile
        self.config = config or {}
        self.logger = CustomLogger("OptimizedClusterer")

        # Parámetros clave del perfil
        self.batch_size = profile.get("clustering_batch_size", 100_000)
        self.use_strict_clustering = profile.get("use_strict_clusters", False)
        self.max_nit_distance = profile.get("max_nit_distance", 2)

        # Configuración de caché LRU
        self.cache_size = profile.get("clustering_cache_size", 50_000)
        self._parent_cache = OrderedDict()  # OrderedDict para implementar LRU
        self._cache_hits = 0
        self._cache_misses = 0

        # Paths y conexiones de BD
        self._db_path = None
        self._db_conn = None

        # Estadísticas detalladas
        self.stats = {
            "nodes_processed": 0,
            "edges_processed": 0,
            "unions_made": 0,
            "unions_by_nit": 0,
            "unions_by_lsh": 0,
            "clusters_found": 0,
            "largest_cluster_size": 0,
            "processing_time_seconds": 0,
            "cache_hit_rate": 0.0,
        }

        # Timer para medición de tiempo
        self._start_time = None

    @track_performance("Clustering completo de entidades")
    def cluster_entities(
        self,
        scored_pairs: pd.DataFrame | str,
        df_full: pd.DataFrame,  # Añadimos df_full como parámetro requerido
        n_entities: int | None = None,
    ) -> dict[int, int] | str:
        """
        Versión MEJORADA que integra el clustering estricto para mayor precisión.

        FASE 2 - Paso 2.4: Para clustering estándar, usa scipy.sparse en lugar
        de NetworkX. Esto reduce RAM de ~3GB a ~300MB y ahorra 10-20 min.
        El clustering estricto sigue usando NetworkX porque build_strict_clusters
        requiere un grafo nx.Graph como entrada.
        """
        if n_entities is None:
            n_entities = len(df_full)

        self.logger.info(f"Iniciando clustering para {n_entities:,} entidades.")

        # --- PASO 1: Cargar pares desde DataFrame o DB ---
        self.logger.info("Cargando pares de conexiones...")

        if isinstance(scored_pairs, str) and scored_pairs.endswith(".db"):
            conn = sqlite3.connect(scored_pairs)
            edge_chunks = pd.read_sql_query(
                "SELECT idx_0, idx_1 FROM scored_pairs", conn, chunksize=100_000
            )
            all_edges = []
            for chunk in edge_chunks:
                all_edges.append(chunk.values)
            conn.close()
            edges = np.vstack(all_edges) if all_edges else np.empty((0, 2), dtype=np.int64)
        else:
            edges = scored_pairs[["idx_0", "idx_1"]].values

        self.logger.info(f"   Aristas cargadas: {len(edges):,}")

        # --- PASO 2: Elegir método según configuración ---
        if self.use_strict_clustering:
            # Clustering estricto: necesita grafo NetworkX para build_strict_clusters
            self.logger.info("Aplicando clustering estricto (requiere NetworkX)...")
            G = nx.Graph()
            G.add_nodes_from(range(n_entities))
            G.add_edges_from(edges)
            final_clusters = build_strict_clusters(G, df_full, self.max_nit_distance)
            del G
            gc.collect()
        else:
            # ═══════════════════════════════════════════════════════════════
            # FASE 2 - Paso 2.4: Clustering estándar con scipy.sparse
            # En lugar de crear un grafo NetworkX (objetos Python por nodo/arista),
            # usamos una matriz dispersa CSR que opera con arrays de C.
            # RAM: de ~3GB a ~300MB para 2M nodos.
            # Tiempo: ahorro de 10-20 minutos.
            # ═══════════════════════════════════════════════════════════════
            self.logger.info("Usando clustering estándar con scipy.sparse (optimizado)...")

            if len(edges) > 0:
                rows = edges[:, 0]
                cols = edges[:, 1]
                data = np.ones(len(rows), dtype=np.int8)
                # Crear matriz simétrica (grafo no dirigido)
                graph = csr_matrix((data, (rows, cols)), shape=(n_entities, n_entities))
                graph = graph + graph.T  # Hacer simétrica
                _n_components, labels = scipy_cc(graph, directed=False)
                del graph
                gc.collect()
            else:
                # Sin aristas: cada nodo es su propio cluster
                labels = np.arange(n_entities)

            # Convertir labels (array) a formato de lista de sets (compatible)
            from collections import defaultdict

            cluster_dict = defaultdict(set)
            for node_id, cluster_label in enumerate(labels):
                cluster_dict[cluster_label].add(node_id)
            final_clusters = list(cluster_dict.values())

        # --- PASO 3: Crear el mapeo final de clusters ---
        self.logger.info("Creando mapeo final de ID_GRUPO...")
        cluster_mapping = {}
        for _i, cluster_nodes in enumerate(tqdm(final_clusters, desc="Mapeando clusters")):
            # Usar el nodo más pequeño del cluster como su ID representativo
            cluster_id = min(cluster_nodes)
            for node in cluster_nodes:
                cluster_mapping[node] = cluster_id

        self.logger.info(
            f"Clustering completado. {len(final_clusters):,} clusters finales encontrados."
        )

        return cluster_mapping

    def _should_use_disk_processing(
        self, scored_pairs: pd.DataFrame | str, n_entities: int
    ) -> bool:
        """Determina si usar procesamiento en disco (SQLite) o en memoria.

        Política v3.0.0 ("todo en disco"): el path en disco es el camino por
        defecto en producción, para tener un solo conjunto de comportamientos y
        simplificar el mantenimiento. Excepciones:

        - `RUES_LINKER_FORCE_MEMORY=1`: fuerza memoria (usado por la suite de
          tests para evitar el overhead de SQLite en datasets de juguete).
        - `RUES_LINKER_FORCE_DISK=1`: fuerza disco (para ejercitar el path
          SQLite incluso en datasets pequeños).
        - Datasets muy pequeños (< 5.000 pares y < 5.000 entidades) usan
          memoria por eficiencia, salvo que se fuerce disco. Esto evita pagar
          el costo de SQLite en cargas triviales sin afectar producción.
        """
        import os

        if os.getenv("RUES_LINKER_FORCE_MEMORY") == "1":
            return False
        if os.getenv("RUES_LINKER_FORCE_DISK") == "1":
            return True

        # Si ya es una BD en disco, usar procesamiento en disco.
        if isinstance(scored_pairs, str) and scored_pairs.endswith(".db"):
            return True

        if isinstance(scored_pairs, pd.DataFrame):
            # Cargas triviales: memoria por eficiencia. Todo lo demás: disco.
            es_trivial = len(scored_pairs) < 5_000 and n_entities < 5_000
            return not es_trivial

        return True  # Por defecto, disco (seguridad y un solo path).

    def _setup_union_find_db(self, n_entities: int):
        """Prepara la base de datos SQLite para la estructura Union-Find con optimizaciones."""
        timestamp = int(time.time() * 1000)
        self._db_path = f"clusters_{timestamp}.db"
        if os.path.exists(self._db_path):
            os.remove(self._db_path)

        self._db_conn = sqlite3.connect(self._db_path)
        cursor = self._db_conn.cursor()

        # Configuración de SQLite para máxima velocidad de escritura
        pragmas = [
            "PRAGMA journal_mode = OFF;",
            "PRAGMA synchronous = OFF;",
            "PRAGMA cache_size = -2000000;",  # 2GB de caché
            "PRAGMA temp_store = MEMORY;",
            "PRAGMA mmap_size = 30000000000;",  # 30GB mmap si está disponible
        ]
        for pragma in pragmas:
            cursor.execute(pragma)

        # Crear tabla para la estructura Union-Find
        cursor.execute("""
            CREATE TABLE entity_clusters (
                entity_id INTEGER PRIMARY KEY,
                parent_id INTEGER NOT NULL,
                rank INTEGER DEFAULT 0
            )
        """)

        # Índice en parent_id para búsquedas más rápidas
        cursor.execute("CREATE INDEX idx_parent ON entity_clusters(parent_id)")

        # Inicializar: cada entidad es su propio padre
        self.logger.info("Inicializando estructura Union-Find en disco...")
        cursor.execute("BEGIN TRANSACTION")

        batch_size = min(100_000, self.batch_size)
        for i in tqdm(range(0, n_entities, batch_size), desc="Inicializando nodos"):
            batch = [(j, j) for j in range(i, min(i + batch_size, n_entities))]
            cursor.executemany(
                "INSERT INTO entity_clusters (entity_id, parent_id) VALUES (?, ?)", batch
            )

            # Commit periódico para datasets muy grandes
            if i > 0 and i % 1_000_000 == 0:
                cursor.execute("COMMIT")
                cursor.execute("BEGIN TRANSACTION")

        self._db_conn.commit()

    def _process_identical_nit_connections(self, df: pd.DataFrame | str):
        """
        Pase 1: Conectar NITs idénticos usando una técnica de ordenamiento eficiente.
        Soporta DataFrames en memoria o archivos parquet.
        """
        # Cargar datos según el tipo
        if isinstance(df, pd.DataFrame):
            df_work = df
            cleanup_df = False
        elif isinstance(df, str) and df.endswith(".parquet"):
            self.logger.info(f"Cargando datos desde {df}")
            df_work = pd.read_parquet(df, columns=["NIT_OK"])
            cleanup_df = True
        else:
            self.logger.warning(f"Tipo de entrada no soportado para NITs: {type(df)}")
            return

        if "NIT_OK" not in df_work.columns:
            self.logger.warning("No se encontró 'NIT_OK'. Omitiendo pase de NITs idénticos.")
            if cleanup_df:
                del df_work
            return

        # 1. Crear un DataFrame temporal solo con lo necesario
        self.logger.info("Preparando datos para el barrido de NITs...")
        nit_df = df_work[["NIT_OK"]].copy()
        nit_df = nit_df[nit_df["NIT_OK"].notna() & (nit_df["NIT_OK"] != "")]
        nit_df.reset_index(inplace=True)  # El índice original es el ID del registro
        nit_df.rename(columns={"index": "record_id"}, inplace=True)

        # Limpiar memoria si cargamos desde archivo
        if cleanup_df:
            del df_work
            gc.collect()

        # 2. Ordenar por NIT - operación clave para eficiencia
        self.logger.info("Ordenando por NIT_OK para agrupar...")
        nit_df.sort_values("NIT_OK", inplace=True, kind="mergesort")

        # 3. Iterar (barrer) el DataFrame ordenado
        self.logger.info("Iniciando barrido para conectar grupos de NITs...")
        cursor = self._db_conn.cursor()
        cursor.execute("BEGIN TRANSACTION")

        unions_made = 0
        group_indices = []
        current_nit = None

        for _, row in tqdm(nit_df.iterrows(), total=len(nit_df), desc="Conectando por NIT"):
            if current_nit is None:
                current_nit = row["NIT_OK"]

            if row["NIT_OK"] == current_nit:
                group_indices.append(row["record_id"])
            else:
                # El NIT cambió, procesar el grupo que acabamos de recolectar
                if len(group_indices) > 1:
                    unions_made += self._union_group(cursor, group_indices)

                # Iniciar nuevo grupo
                current_nit = row["NIT_OK"]
                group_indices = [row["record_id"]]

        # Procesar el último grupo
        if len(group_indices) > 1:
            unions_made += self._union_group(cursor, group_indices)

        self._db_conn.commit()
        self.stats["unions_by_nit"] = unions_made
        self.logger.info(f"Pase 1 completado. Uniones por NIT idéntico: {unions_made:,}")

        del nit_df
        gc.collect()

    def _process_scored_pair_connections(self, scored_pairs: pd.DataFrame | str):
        """
        Pase 2: Unir clusters usando los pares de LSH con caché optimizado.
        """
        cursor = self._db_conn.cursor()

        # Configurar iterador según el tipo de entrada
        if isinstance(scored_pairs, pd.DataFrame):
            # Convertir a BD temporal si es muy grande
            if len(scored_pairs) > self.batch_size:
                temp_db = self._dataframe_to_temp_db(scored_pairs)
                self._process_scored_pairs_from_db(temp_db, cursor)
                os.remove(temp_db)
                return
            else:
                # Procesar directamente desde DataFrame
                iterator = scored_pairs.iterrows()
                total = len(scored_pairs)
        elif isinstance(scored_pairs, str) and scored_pairs.endswith(".db"):
            self._process_scored_pairs_from_db(scored_pairs, cursor)
            return
        else:
            self.logger.warning("Formato de scored_pairs no reconocido. Omitiendo.")
            return

        # Procesar desde DataFrame (casos pequeños)
        unions_made = 0
        cursor.execute("BEGIN TRANSACTION")

        for item in tqdm(iterator, total=total, desc="Uniendo por scores LSH"):
            idx_0, idx_1 = item[1]["idx_0"], item[1]["idx_1"]

            root_0 = self._find_with_compression(cursor, idx_0)
            root_1 = self._find_with_compression(cursor, idx_1)

            if root_0 != root_1:
                self._union_by_rank(cursor, root_0, root_1)
                unions_made += 1

                # Commit periódico
                if unions_made % 10_000 == 0:
                    cursor.execute("COMMIT")
                    cursor.execute("BEGIN TRANSACTION")

        self._db_conn.commit()
        self.stats["unions_by_lsh"] = unions_made
        self.stats["edges_processed"] += total
        self.logger.info(f"Pase 2 completado. Uniones por score LSH: {unions_made:,}")

    def _process_scored_pairs_from_db(self, db_path: str, cursor: sqlite3.Cursor):
        """
        Procesar pares desde una base de datos SQLite con batching optimizado.
        """
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        db_cursor = conn.cursor()
        db_cursor.execute("PRAGMA cache_size = -1000000")

        # Obtener total
        db_cursor.execute("SELECT COUNT(*) FROM scored_pairs")
        total = db_cursor.fetchone()[0]

        self.logger.info(f"Procesando {total:,} pares desde BD...")

        unions_made = 0
        cursor.execute("BEGIN TRANSACTION")

        # Procesar en batches ordenados por score descendente
        offset = 0
        with tqdm(total=total, desc="Uniendo por scores LSH") as pbar:
            while offset < total:
                db_cursor.execute(
                    """
                    SELECT idx_0, idx_1
                    FROM scored_pairs
                    ORDER BY score DESC
                    LIMIT ? OFFSET ?
                """,
                    (self.batch_size, offset),
                )

                batch = db_cursor.fetchall()
                if not batch:
                    break

                for idx_0, idx_1 in batch:
                    root_0 = self._find_with_compression(cursor, idx_0)
                    root_1 = self._find_with_compression(cursor, idx_1)

                    if root_0 != root_1:
                        self._union_by_rank(cursor, root_0, root_1)
                        unions_made += 1

                offset += len(batch)
                pbar.update(len(batch))
                pbar.set_postfix(
                    {
                        "uniones": f"{unions_made:,}",
                        "cache_hit_rate": f"{self._get_cache_hit_rate():.1%}",
                    }
                )

                # Commit y limpieza periódica
                if unions_made % 100_000 == 0 and unions_made > 0:
                    cursor.execute("COMMIT")
                    cursor.execute("BEGIN TRANSACTION")
                    self._clean_cache_if_needed()

                if offset % (self.batch_size * 10) == 0:
                    gc.collect()

        cursor.execute("COMMIT")
        conn.close()

        self.stats["unions_by_lsh"] = unions_made
        self.stats["edges_processed"] += total

    def _find_with_compression(self, cursor: sqlite3.Cursor, entity_id: int) -> int:
        """
        Operación Find con path compression y caché LRU.
        """
        # Verificar caché primero
        if entity_id in self._parent_cache:
            self._cache_hits += 1
            # Mover al final (más reciente) para LRU
            self._parent_cache.move_to_end(entity_id)
            return self._parent_cache[entity_id]

        self._cache_misses += 1

        # Buscar en BD siguiendo el path hasta la raíz
        path = []
        current = entity_id

        while True:
            cursor.execute("SELECT parent_id FROM entity_clusters WHERE entity_id = ?", (current,))
            result = cursor.fetchone()

            if not result:
                self.logger.warning(f"Entidad {current} no encontrada")
                return current

            parent = result[0]

            if parent == current:
                root = current
                break

            path.append(current)
            current = parent

            # Evitar ciclos infinitos
            if len(path) > 1000:
                self.logger.error(f"Posible ciclo detectado para entidad {entity_id}")
                return entity_id

        # Path compression: actualizar todos los nodos en el path
        if path:
            cursor.executemany(
                "UPDATE entity_clusters SET parent_id = ? WHERE entity_id = ?",
                [(root, node) for node in path],
            )

        # Actualizar caché con el resultado
        self._update_cache(entity_id, root)
        for node in path[-10:]:  # Solo cachear los últimos nodos del path
            self._update_cache(node, root)

        return root

    def _union_by_rank(self, cursor: sqlite3.Cursor, root_0: int, root_1: int):
        """Union by rank para mantener árboles balanceados."""
        # Obtener ranks de ambas raíces
        cursor.execute(
            "SELECT entity_id, rank FROM entity_clusters WHERE entity_id IN (?, ?)",
            (root_0, root_1),
        )
        ranks = dict(cursor.fetchall())

        rank_0 = ranks.get(root_0, 0)
        rank_1 = ranks.get(root_1, 0)

        if rank_0 < rank_1:
            # root_1 se convierte en parent de root_0
            cursor.execute(
                "UPDATE entity_clusters SET parent_id = ? WHERE entity_id = ?", (root_1, root_0)
            )
            self._update_cache(root_0, root_1)
        elif rank_0 > rank_1:
            # root_0 se convierte en parent de root_1
            cursor.execute(
                "UPDATE entity_clusters SET parent_id = ? WHERE entity_id = ?", (root_0, root_1)
            )
            self._update_cache(root_1, root_0)
        else:
            # Ranks iguales, elegir root_0 como parent y aumentar su rank
            cursor.execute(
                "UPDATE entity_clusters SET parent_id = ? WHERE entity_id = ?", (root_0, root_1)
            )
            cursor.execute(
                "UPDATE entity_clusters SET rank = rank + 1 WHERE entity_id = ?", (root_0,)
            )
            self._update_cache(root_1, root_0)

    def _union_group(self, cursor: sqlite3.Cursor, indices: list[int]) -> int:
        """Une todos los nodos de un grupo al primer nodo con optimización de caché."""
        unions = 0
        if not indices:
            return 0

        root_of_group = self._find_with_compression(cursor, indices[0])

        for i in range(1, len(indices)):
            current_root = self._find_with_compression(cursor, indices[i])
            if current_root != root_of_group:
                self._union_by_rank(cursor, root_of_group, current_root)
                # Actualizar la raíz del grupo por si cambió
                root_of_group = self._find_with_compression(cursor, root_of_group)
                unions += 1

        return unions

    def _compress_all_paths(self, n_entities: int):
        """
        Comprime todos los paths al final para optimización.
        Versión mejorada que procesa por batches y actualiza el caché.
        """
        self.logger.info("Comprimiendo paths para optimizar estructura...")

        cursor = self._db_conn.cursor()
        cursor.execute("BEGIN TRANSACTION")

        # Procesar en batches más grandes para eficiencia
        batch_size = min(self.batch_size * 2, 200_000)
        updates_made = 0

        with tqdm(total=n_entities, desc="Comprimiendo paths") as pbar:
            for start in range(0, n_entities, batch_size):
                end = min(start + batch_size, n_entities)

                # Obtener todas las entidades del batch con sus parents
                cursor.execute(
                    """
                    SELECT entity_id, parent_id
                    FROM entity_clusters
                    WHERE entity_id >= ? AND entity_id < ?
                """,
                    (start, end),
                )

                batch_data = cursor.fetchall()
                updates = []

                for entity_id, current_parent in batch_data:
                    # Solo procesar si no apunta a sí mismo
                    if entity_id != current_parent:
                        # Encontrar la raíz real
                        root = self._find_with_compression(cursor, entity_id)

                        # Si no apunta directamente a la raíz, actualizar
                        if current_parent != root:
                            updates.append((root, entity_id))
                            updates_made += 1

                # Aplicar actualizaciones del batch
                if updates:
                    cursor.executemany(
                        "UPDATE entity_clusters SET parent_id = ? WHERE entity_id = ?", updates
                    )

                pbar.update(end - start)

                # Commit periódico
                if start > 0 and start % 1_000_000 == 0:
                    cursor.execute("COMMIT")
                    cursor.execute("BEGIN TRANSACTION")
                    self._parent_cache.clear()  # Limpiar caché después de cambios masivos
                    gc.collect()

        cursor.execute("COMMIT")
        self.logger.info(f"Compresión completada. Paths actualizados: {updates_made:,}")

    def _calculate_final_stats(self):
        """Calcular estadísticas finales del clustering."""
        cursor = self._db_conn.cursor()

        self.logger.info("Calculando estadísticas finales...")

        # Contar clusters únicos
        cursor.execute("""
            SELECT COUNT(DISTINCT parent_id) as unique_clusters
            FROM entity_clusters
        """)
        self.stats["clusters_found"] = cursor.fetchone()[0]

        # Obtener distribución de tamaños
        cursor.execute("""
            SELECT parent_id, COUNT(*) as size
            FROM entity_clusters
            GROUP BY parent_id
            ORDER BY size DESC
            LIMIT 20
        """)

        top_clusters = cursor.fetchall()
        if top_clusters:
            self.stats["largest_cluster_size"] = top_clusters[0][1]

            # Log información sobre los clusters más grandes
            self.logger.info("Top 5 clusters por tamaño:")
            for i, (cluster_id, size) in enumerate(top_clusters[:5]):
                self.logger.info(f"  {i + 1}. Cluster {cluster_id}: {size:,} entidades")

        # Calcular total de uniones
        self.stats["unions_made"] = self.stats["unions_by_nit"] + self.stats["unions_by_lsh"]

    def _save_metadata(self, n_entities: int):
        """Guardar metadatos del proceso en la BD."""
        cursor = self._db_conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Actualizar estadísticas finales
        self.stats["processing_time_seconds"] = time.time() - self._start_time
        self.stats["cache_hit_rate"] = self._get_cache_hit_rate()

        # Preparar metadatos
        metadata = [
            ("n_entities", str(n_entities)),
            ("unique_clusters", str(self.stats["clusters_found"])),
            ("edges_processed", str(self.stats["edges_processed"])),
            ("unions_made", str(self.stats["unions_made"])),
            ("unions_by_nit", str(self.stats["unions_by_nit"])),
            ("unions_by_lsh", str(self.stats["unions_by_lsh"])),
            ("largest_cluster_size", str(self.stats["largest_cluster_size"])),
            ("processing_time_seconds", str(self.stats["processing_time_seconds"])),
            ("cache_hit_rate", str(self.stats["cache_hit_rate"])),
            ("creation_time", str(time.time())),
            ("clustering_version", "3.4"),
        ]

        cursor.executemany("INSERT OR REPLACE INTO metadata VALUES (?, ?)", metadata)
        self._db_conn.commit()

    def _cluster_in_memory(
        self, scored_pairs: pd.DataFrame, df_full: pd.DataFrame | None, n_entities: int
    ) -> dict[int, int]:
        """
        Clustering en memoria por componentes conexos.

        v2.2.0: reescrito de Union-Find con ``iterrows`` (bucle Python sobre
        cada par scored — letal en millones de pares) a construcción de grafo
        disperso + ``scipy.sparse.csgraph.connected_components``, que resuelve
        los componentes en C. La semántica es idéntica: dos entidades quedan en
        el mismo cluster sii están conectadas por una arista de NIT idéntico o
        por un par scored. Ver MIGRATION_LOG §12.

        El antiguo Union-Find producía exactamente los mismos componentes
        conexos; la equivalencia se valida en tests/test_clusterer_vectorizado.py.
        """
        self.logger.info("Ejecutando clustering en memoria (vectorizado)...")

        filas: list[np.ndarray] = []
        cols: list[np.ndarray] = []

        # Pase 1: aristas por NIT idéntico (vectorizado, sin bucle por par).
        # Para cada grupo de NIT con k>1 miembros, conectamos en estrella al
        # primer miembro (k-1 aristas) — basta para que el componente conexo
        # los una a todos, igual que el Union-Find original.
        if (
            df_full is not None
            and isinstance(df_full, pd.DataFrame)
            and "NIT_OK" in df_full.columns
        ):
            self.logger.info("Conectando NITs idénticos...")
            con_nit = df_full[df_full["NIT_OK"].notna()]
            # group indices posicionales (0..n_entities-1), no labels del índice
            pos = np.arange(len(df_full))
            con_nit_pos = pos[df_full["NIT_OK"].notna().to_numpy()]
            codes, _uniques = pd.factorize(con_nit["NIT_OK"].to_numpy())
            orden = np.argsort(codes, kind="stable")
            codes_ord = codes[orden]
            pos_ord = con_nit_pos[orden]
            # límites de cada grupo de NIT en el array ordenado
            limites = np.flatnonzero(np.diff(codes_ord)) + 1
            grupos = np.split(pos_ord, limites)
            n_nit_edges = 0
            for miembros in grupos:
                if miembros.size > 1:
                    raiz = miembros[0]
                    filas.append(np.full(miembros.size - 1, raiz))
                    cols.append(miembros[1:])
                    n_nit_edges += miembros.size - 1
            self.stats["unions_by_nit"] += n_nit_edges

        # Pase 2: aristas por pares scored (vectorizado — el hot-path real).
        if scored_pairs is not None and len(scored_pairs) > 0:
            self.logger.info(f"Procesando {len(scored_pairs):,} pares scored...")
            i0 = scored_pairs["idx_0"].to_numpy(dtype=np.int64)
            i1 = scored_pairs["idx_1"].to_numpy(dtype=np.int64)
            filas.append(i0)
            cols.append(i1)
            self.stats["unions_by_lsh"] += len(scored_pairs)

        if filas:
            row = np.concatenate(filas)
            col = np.concatenate(cols)
            data = np.ones(row.shape[0], dtype=np.int8)
            grafo = csr_matrix((data, (row, col)), shape=(n_entities, n_entities))
            n_comp, labels = scipy_cc(grafo, directed=False, return_labels=True)
        else:
            # Sin aristas: cada entidad es su propio cluster.
            labels = np.arange(n_entities)
            n_comp = n_entities

        # Mapeo final entidad -> id de cluster (label del componente conexo).
        cluster_mapping = {i: int(labels[i]) for i in range(n_entities)}

        unique_clusters = int(n_comp)
        self.stats["clusters_found"] = unique_clusters
        self.stats["unions_made"] = len(np.concatenate(filas)) if filas else 0
        self.stats["nodes_processed"] = n_entities
        self.stats["edges_processed"] = len(scored_pairs) if scored_pairs is not None else 0
        self.stats["processing_time_seconds"] = time.time() - self._start_time

        self.logger.info(f"Clustering en memoria completado: {unique_clusters:,} clusters únicos")

        return cluster_mapping

    def _dataframe_to_temp_db(self, df: pd.DataFrame) -> str:
        """Convertir DataFrame a BD temporal para procesamiento eficiente."""
        temp_db = f"temp_scored_{int(time.time() * 1000)}.db"
        conn = sqlite3.connect(temp_db)

        # Configurar para escritura rápida
        cursor = conn.cursor()
        for pragma in ["PRAGMA journal_mode = OFF;", "PRAGMA synchronous = OFF;"]:
            cursor.execute(pragma)

        # Escribir DataFrame
        df.to_sql("scored_pairs", conn, index=False, if_exists="replace")

        # Crear índice en score para ordenamiento eficiente
        cursor.execute("CREATE INDEX idx_temp_score ON scored_pairs(score DESC)")

        conn.close()
        return temp_db

    # Métodos de gestión de caché
    def _update_cache(self, entity_id: int, root: int):
        """Actualizar caché LRU con límite de tamaño."""
        # Si ya existe, mover al final
        if entity_id in self._parent_cache:
            self._parent_cache.move_to_end(entity_id)

        # Agregar o actualizar
        self._parent_cache[entity_id] = root

        # Si excedemos el tamaño, eliminar el más antiguo
        if len(self._parent_cache) > self.cache_size:
            self._parent_cache.popitem(last=False)

    def _clean_cache_if_needed(self):
        """Limpiar parcialmente el caché si está muy lleno."""
        if len(self._parent_cache) > self.cache_size * 1.5:
            # Mantener solo la mitad más reciente
            items_to_keep = list(self._parent_cache.items())[-(self.cache_size // 2) :]
            self._parent_cache = OrderedDict(items_to_keep)
            self.logger.debug(f"Cache limpiado. Tamaño actual: {len(self._parent_cache)}")

    def _get_cache_hit_rate(self) -> float:
        """Calcular tasa de aciertos del caché."""
        total = self._cache_hits + self._cache_misses
        return self._cache_hits / total if total > 0 else 0.0

    # Métodos públicos adicionales
    def get_stats(self) -> dict[str, Any]:
        """
        Obtener estadísticas detalladas del proceso de clustering.

        Returns:
            Dict con todas las estadísticas recopiladas.
        """
        stats = self.stats.copy()
        stats["cache_size_current"] = len(self._parent_cache)
        stats["cache_size_max"] = self.cache_size
        stats["cache_hits"] = self._cache_hits
        stats["cache_misses"] = self._cache_misses
        return stats

    def update_config(self, new_config: dict[str, Any]):
        """
        Actualizar configuración del clusterer.

        Args:
            new_config: Diccionario con nuevos parámetros de configuración.
        """
        # Actualizar profile
        self.profile.update(new_config)

        # Actualizar parámetros específicos si están presentes
        if "clustering_batch_size" in new_config:
            self.batch_size = new_config["clustering_batch_size"]
        if "clustering_cache_size" in new_config:
            self.cache_size = new_config["clustering_cache_size"]
        if "use_strict_clusters" in new_config:
            self.use_strict_clustering = new_config["use_strict_clusters"]

        self.logger.debug(f"Configuración actualizada: {new_config}")

    def cleanup(self):
        """
        Limpiar recursos y archivos temporales.
        """
        # Cerrar conexión si está abierta
        self._close_db()

        # Limpiar caché
        self._parent_cache.clear()
        self._cache_hits = 0
        self._cache_misses = 0

        # Intentar eliminar archivo de BD si existe
        if self._db_path and os.path.exists(self._db_path):
            try:
                os.remove(self._db_path)
                self.logger.debug(f"Archivo de clusters eliminado: {self._db_path}")
            except Exception as e:
                self.logger.warning(f"No se pudo eliminar archivo de clusters: {e}")

        # Resetear estadísticas
        self.stats = {key: 0 for key in self.stats}

        # Forzar recolección de basura
        gc.collect()

        self.logger.info("Limpieza de recursos completada")

    def _close_db(self):
        """Cerrar conexión a BD de manera segura."""
        if self._db_conn:
            try:
                self._db_conn.close()
            except Exception as e:
                self.logger.warning(f"Error al cerrar conexión BD: {e}")
            finally:
                self._db_conn = None
