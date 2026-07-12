"""API de alto nivel para record linkage multi-fuente.

Expone `linkage()`, el punto de entrada único y recomendado para producción.
Encapsula la construcción de configuración + Orchestrator en una sola llamada,
de modo que el usuario no necesite conocer la estructura interna del paquete.

Diseño:
    - Un solo camino: siempre vía Orchestrator (motor en disco).
    - Multi-fuente y multi-variable de fábrica.
    - `trusted_sources` para fuentes con identidad verificada (NIT confiable).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pandas as pd


def linkage(
    sources: dict[str, pd.DataFrame],
    *,
    trusted_sources: set[str] | list[str] | None = None,
    col_name: str = "RAZON_SOCIAL",
    col_nit: str = "NIT",
    col_ciudad: str | None = "CIUDAD",
    extra_features: list[str] | None = None,
    work_dir: str | None = None,
    profile: str = "produccion_estandar",
    matching_profile: Any = None,
    return_matcher_audit: bool = False,
) -> dict[str, Any]:
    """Ejecuta deduplicación + record linkage multi-fuente en una sola llamada.

    Esta es la API de alto nivel recomendada. Internamente usa el `Orchestrator`
    (motor en disco), que es el único camino que separa correctamente los
    regímenes CON_NIT y SIN_NIT cuando se mezclan fuentes.

    Args:
        sources: dict {nombre_fuente: DataFrame}. Una entrada por fuente. Cada
            DataFrame debe tener al menos la columna `col_name`.
        trusted_sources: nombres de fuentes confiables (NIT verificado). Estas
            fuentes no se deduplican internamente (se asume que ya están limpias)
            y tienen prioridad para el nombre canónico del golden record. Ej:
            {"RUES", "SUPERSOCIEDADES"}.
        col_name: nombre de la columna de razón social. Default "RAZON_SOCIAL".
        col_nit: nombre de la columna de NIT. Default "NIT". Si una fuente no
            tiene NIT, déjala vacía ("") en esa fuente.
        col_ciudad: nombre de la columna de ciudad, o None si no aplica.
        extra_features: columnas adicionales para el scoring (p. ej.
            ["TELEFONO", "EMAIL", "DIRECCION"]). Cada una contribuye a la
            similitud según el perfil.
        work_dir: directorio de trabajo. Todos los archivos intermedios (SQLite,
            parquet) se escriben ahí. Si es None, se usa un temporal.
        profile: perfil de configuración. Ver `record_linkage.config.profiles`.
            Para fuentes sin NIT usar "deduplication_sin_nit_conservador".
        matching_profile: MatchingProfile (de
            ``record_linkage.matching``) o string para activar refinamiento
            multi-variable post-clustering. Opciones:
              - None (default): pipeline core sin refinamiento. Comportamiento
                idéntico al comportamiento sin matcher.
              - "colombia": aplica ``default_colombia_profile()``.
              - "international": aplica ``default_international_profile()``.
              - Instancia de MatchingProfile: usa ese profile exacto.
            El refinamiento SEPARA clusters predichos donde no se cumplen las
            reglas multi-variable. Sube precision sin afectar recall LSH.
            Útil sobre todo para mejorar SIN_NIT donde el scorer plano da FP.
        return_matcher_audit: si True y matching_profile no es None, incluye
            en el resultado las claves "matcher_stats" (métricas de la refinación)
            y "matcher_decisions" (DataFrame con scores por variable para cada
            par evaluado). Útil para auditoría/debugging. Default False.

    Returns:
        dict con dos claves base:
            - "golden": DataFrame con un registro por entidad única (deduplicado).
            - "correlative": DataFrame que mapea cada registro original a su
              ID_GRUPO.
        Si ``return_matcher_audit=True`` y ``matching_profile`` está activo:
            - "matcher_stats": dict con métricas de la refinación.
            - "matcher_decisions": DataFrame con decisión por par evaluado.

    Ejemplo (con matcher):
        >>> from record_linkage import linkage
        >>> result = linkage(
        ...     sources={"RUES": df_rues, "DIAN": df_dian, "CRM": df_crm},
        ...     trusted_sources={"RUES"},
        ...     col_ciudad="CIUDAD",
        ...     extra_features=["TELEFONO", "EMAIL"],
        ...     matching_profile="colombia",  # NUEVO: refinamiento multi-variable
        ...     return_matcher_audit=True,
        ... )
        >>> print(result["matcher_stats"])  # cuántos clusters se separaron
        >>> result["correlative"].to_parquet("correlativa.parquet")

    Ejemplo (sin matcher):
        >>> result = linkage(sources={"RUES": df})  # mismo comportamiento que antes

    Nota sobre calidad medida (ground truth sintético):
        Las cifras del docstring previas (F1 ≈ 0.875) NO eran trazables.
        Para benchmarks reproducibles, ejecutar:
            scripts/benchmark_e2e_matcher.py
        ADVERTENCIA: todo está medido sobre GT sintético. No es sustituto
        de medición sobre datos reales etiquetados (RUES). Ver
        scripts/active_labeling.py para construir tu ground truth real.
    """
    import tempfile

    from .config.profiles import crear_config_orchestrator
    from .pipeline.orchestrator import Orchestrator

    if not sources:
        raise ValueError("Debe proporcionar al menos una fuente en `sources`.")

    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="rues_linker_")

    trusted = list(trusted_sources) if trusted_sources else []

    # Construir overrides para el perfil. Los nombres de columna y features
    # se inyectan vía la config; trusted_unique_sources es el mecanismo real
    # del Orchestrator para fuentes confiables.
    overrides: dict[str, Any] = {
        "trusted_unique_sources": trusted,
        "col_name": col_name,
        "col_nit": col_nit,
    }
    if col_ciudad:
        overrides["col_ciudad"] = col_ciudad
    if extra_features:
        overrides["extra_features"] = extra_features

    config = crear_config_orchestrator(perfil=profile, workspace=work_dir, **overrides)
    orchestrator = Orchestrator(config=config, sources=sources, work_dir=work_dir)
    result = orchestrator.run()

    # ── Refinamiento opt-in con MatcherPostProcessor ──────────
    if matching_profile is not None:
        from .matching import (
            MatcherPostProcessor,
            default_colombia_profile,
            default_international_profile,
        )
        from .matching.spec import MatchingProfile as MatchingProfileCls

        # Resolver string → instancia
        if isinstance(matching_profile, str):
            from .matching import (
                default_colombia_profile_conservative,
                default_colombia_profile_recall,
            )

            if matching_profile in ("colombia", "colombia_balanced"):
                profile_obj = default_colombia_profile()
            elif matching_profile == "colombia_conservative":
                profile_obj = default_colombia_profile_conservative()
            elif matching_profile == "colombia_recall":
                profile_obj = default_colombia_profile_recall()
            elif matching_profile == "international":
                profile_obj = default_international_profile()
            else:
                raise ValueError(
                    f"matching_profile string desconocido: '{matching_profile}'. "
                    "Opciones: 'colombia' (balanced, default), "
                    "'colombia_conservative' (max precision), "
                    "'colombia_recall' (max recall), 'international', "
                    "o instancia de MatchingProfile."
                )
        elif isinstance(matching_profile, MatchingProfileCls):
            profile_obj = matching_profile
        else:
            raise TypeError(
                f"matching_profile debe ser str o MatchingProfile, recibido "
                f"{type(matching_profile).__name__}"
            )

        # Reconstruir df_source combinando todas las fuentes
        import pandas as _pd

        combined_source = _pd.concat(
            [src for src in sources.values()],
            ignore_index=True,
        )

        # Aplicar post-procesador
        postproc = MatcherPostProcessor(profile_obj, verbose=False)
        refined_correlative = postproc.apply(
            result["correlative"],
            combined_source,
        )
        # Re-derivar golden
        refined_golden = refined_correlative.drop_duplicates(subset=["ID_GRUPO"], keep="first")

        result["correlative"] = refined_correlative
        result["golden"] = refined_golden

        if return_matcher_audit:
            result["matcher_stats"] = postproc.last_stats
            result["matcher_decisions"] = postproc.decisions_log

    return result
