"""
engine.trusted — record_linkage_pipeline

Componentes:
    - class TrustedSourceLSHEngine  (origen: notebook celda [194])

NOTA: Lógica de negocio preservada exactamente como en el notebook
fuente. Solo se agregan imports, docstring de módulo y se eliminan
directivas de Jupyter (%%time, !pip, etc.). Ver MIGRATION_LOG.md.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from .disk_based import DiskBasedLSHEngine


class TrustedSourceLSHEngine(DiskBasedLSHEngine):
    """
    Motor LSH que bloquea comparaciones intra-fuente para fuentes TRUSTED.

    Hereda TODO de DiskBasedLSHEngine v4.0.0 y solo modifica la lógica
    de filtrado de pares candidatos.

    Lógica de filtrado
    ------------------
    - Fuentes TRUSTED (ej: RUES, SUPERSOCIEDADES):
      Sus registros NO se comparan entre sí (son únicos por definición).
    - Fuentes NO trusted (ej: CRM, EXPORTACIONES):
      SÍ se comparan internamente (pueden tener duplicados reales).
    - Cruces entre fuentes:
      SIEMPRE se permiten (RUES↔CRM, RUES↔EXPORTACIONES, etc.).

    Ejemplo
    -------
        ✅ RUES↔RUES → BLOQUEADO (trusted)
        ✅ SUPERSOCIEDADES↔SUPERSOCIEDADES → BLOQUEADO (trusted)
        ✅ CRM↔CRM → PERMITIDO (no trusted)
        ✅ RUES↔CRM → PERMITIDO (cross-source)

    Parameters
    ----------
    profile : dict
        Perfil de configuración LSH.
    config : dict
        Configuración global del pipeline.
    trusted_sources : set[str]
        Nombres de fuentes cuya deduplicación interna se omite.

    Notes
    -----
    RUES tiene 1.92M de 1.97M registros (97.5%). Eliminar comparaciones
    intra-RUES reduce candidatos de ~214M a ~10-15M (>93% reducción).
    """

    VERSION: str = "4.1.0-trusted"

    def __init__(
        self,
        profile: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
        trusted_sources: set[str] | None = None,
    ) -> None:
        """Inicializa motor LSH con soporte para Trusted Sources."""
        super().__init__(profile, config)
        self._trusted_sources: frozenset[str] = frozenset(trusted_sources or set())
        self.logger.info(
            f"🛡️ TrustedSourceLSHEngine v{self.VERSION} | "
            f"trusted={sorted(self._trusted_sources) if self._trusted_sources else 'ninguna'}"
        )

    # ── Override: find_candidates ─────────────────────────────────────────────
    def find_candidates(
        self,
        df: pd.DataFrame,
        output_dir: str | None = None,
        cross_source_only: bool = False,
        trusted_unique_sources: set | None = None,
    ) -> set[tuple[int, int]] | str:
        """
        Override que garantiza compatibilidad SRC→FUENTE y activa cross_source.

        v2.10.0 bug-fix: acepta `trusted_unique_sources` como kwarg para
        compatibilidad con `RecordLinkageEngine.link()`. Si se pasa, se
        agrega a `self._trusted_sources`. Antes este parámetro generaba
        TypeError en el path disk_based desde `linkage.py`. Ver
        MIGRATION_LOG §21.

        Parameters
        ----------
        df : pd.DataFrame
            DataFrame con columnas NOMBRE_LIMPIO y SRC (o FUENTE).
        output_dir : str
            Directorio de trabajo para archivos SQLite/HDF5.
        cross_source_only : bool
            Si True, solo genera pares cross-source (se activa automáticamente
            si hay trusted_sources configuradas).
        trusted_unique_sources : set | None
            Fuentes confiables adicionales. Se unen al set pasado en __init__.

        Returns
        -------
        Union[Set[Tuple[int, int]], str]
            Set de pares candidatos o ruta a candidates.db.
        """
        # Mezclar con el set del __init__ si se pasó por kwarg.
        if trusted_unique_sources:
            extra = frozenset(trusted_unique_sources)
            if extra - self._trusted_sources:
                self.logger.info(
                    "Agregando trusted_unique_sources al motor: %s",
                    sorted(extra - self._trusted_sources),
                )
                self._trusted_sources = self._trusted_sources | extra
        # ── Mapear SRC → FUENTE si no existe ──
        if "FUENTE" not in df.columns and "SRC" in df.columns:
            df = df.copy()  # No mutar el original
            df["FUENTE"] = df["SRC"]
            self.logger.info("   📝 Columna FUENTE creada desde SRC")

        # ── Activar cross_source si hay trusted sources ──
        if self._trusted_sources and not cross_source_only:
            cross_source_only = True
            self.logger.info("   🔄 cross_source_only=True activado por Trusted Sources")

        return super().find_candidates(
            df, output_dir=output_dir, cross_source_only=cross_source_only
        )

    # ── Override: _generate_bucket_pairs ──────────────────────────────────────
    def _generate_bucket_pairs(
        self, record_ids: list[int], source_map: dict[int, str] | None
    ) -> list[tuple[int, int]]:
        """
        Override: Filtra pares con lógica granular por fuente.

        Lógica del padre (DiskBasedLSHEngine v4.0.0):
            Si source_map y cross_source_only=True → bloquea TODOS los pares
            donde source_map[id1] == source_map[id2]. Esto es demasiado
            agresivo: bloquea CRM↔CRM y EXPORTACIONES↔EXPORTACIONES.

        Lógica de este override:
            Solo bloquea el par si AMBOS registros pertenecen a la MISMA
            fuente Y esa fuente está en self._trusted_sources.

        Parameters
        ----------
        record_ids : list[int]
            Índices de registros en un bucket LSH.
        source_map : dict[int, str] | None
            Mapeo record_id → nombre de fuente.

        Returns
        -------
        list[tuple[int, int]]
            Pares candidatos filtrados (id_menor, id_mayor).

        Notes
        -----
        Si no hay source_map o no hay trusted_sources, delega al padre.
        Si el padre no tiene este método, el override no se invoca
        (cross_source_only=True sigue aplicando como fallback).
        """
        # Sin source_map → comportamiento original del padre
        if not source_map:
            return super()._generate_bucket_pairs(record_ids, source_map)

        # Sin trusted sources → comportamiento original del padre
        if not self._trusted_sources:
            return super()._generate_bucket_pairs(record_ids, source_map)

        # ── Filtrado granular por trusted sources ──
        pairs: list[tuple[int, int]] = []
        trusted = self._trusted_sources  # Referencia local para velocidad
        n = len(record_ids)

        for i in range(n):
            for j in range(i + 1, n):
                id1, id2 = record_ids[i], record_ids[j]

                # Normalizar orden (menor primero)
                if id1 > id2:
                    id1, id2 = id2, id1

                src1 = source_map.get(id1, "")
                src2 = source_map.get(id2, "")

                # SOLO bloquear si AMBOS son de la MISMA fuente TRUSTED
                if src1 == src2 and src1 in trusted:
                    continue

                pairs.append((id1, id2))

        return pairs
