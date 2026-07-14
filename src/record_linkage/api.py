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

import hashlib
import json
from dataclasses import dataclass
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


# ═══════════════════════════════════════════════════════════════════════════
# FACHADA CANÓNICA (F1, v0.9.0): ResultadoLinkage · dedupe · link
# ═══════════════════════════════════════════════════════════════════════════

#: Semilla global del pipeline (determinismo contractual, ver F0.6).
_SEED_GLOBAL = 42


@dataclass
class ResultadoLinkage:
    """Resultado tipado de la fachada (F1.5): datos + métricas + trazabilidad.

    Attributes:
        correlativa: mapeo registro→ID_GRUPO (una fila por registro de entrada).
        golden: un registro canónico por entidad, o None si la ruta no lo
            produce en memoria (``dedupe`` los escribe por régimen en
            ``metricas['output_dir']``).
        metricas: conteos de la corrida y estadísticas del pipeline.
        manifiesto: trazabilidad total — función, timestamp UTC, seed,
            parámetros y su hash, huella de cada insumo, versiones del entorno.
    """

    correlativa: pd.DataFrame
    golden: pd.DataFrame | None
    metricas: dict[str, Any]
    manifiesto: dict[str, Any]

    def resumen(self) -> str:
        """Resumen humano de una línea (para logs y actas)."""
        m, man = self.metricas, self.manifiesto
        return (
            f"{man.get('funcion', '?')}: {m.get('n_registros', '?')} registros "
            f"→ {m.get('n_grupos', '?')} grupos únicos "
            f"(rues-linker {man.get('versiones', {}).get('rues-linker', '?')}, "
            f"hash_parametros {man.get('hash_parametros', '?')})"
        )


def _huella_dataset(df: pd.DataFrame) -> str:
    """Huella SHA-256 (16 hex) de forma+columnas+muestra del contenido.

    Permite auditar que una corrida se hizo sobre ESE insumo exacto sin
    almacenar los datos (mismo patrón que la key del cache MinHash).
    """
    h = hashlib.sha256()
    h.update(f"n={len(df)};cols={list(df.columns)};".encode())
    paso = max(1, len(df) // 200)
    for i in range(0, len(df), paso):
        h.update(str(df.iloc[i].to_dict())[:200].encode("utf-8", errors="ignore"))
        h.update(b"|")
    return h.hexdigest()[:16]


def _versiones_entorno() -> dict[str, str]:
    """Versiones de la librería y dependencias que alteran resultados."""
    from importlib.metadata import PackageNotFoundError, version

    out: dict[str, str] = {}
    for paq in ("rues-linker", "datasketch", "pandas", "numpy", "networkx", "rapidfuzz"):
        try:
            out[paq] = version(paq)
        except PackageNotFoundError:  # pragma: no cover - entorno incompleto
            out[paq] = "no-instalado"
    return out


def _manifiesto(
    funcion: str,
    parametros: dict[str, Any],
    entradas: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    """Manifiesto de corrida (F1.5): qué corrió, con qué parámetros, sobre qué."""
    from datetime import datetime, timezone

    hash_par = hashlib.sha256(
        json.dumps(parametros, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return {
        "funcion": funcion,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seed": _SEED_GLOBAL,
        "parametros": parametros,
        "hash_parametros": hash_par,
        "entradas": {
            nombre: {
                "filas": len(d),
                "columnas": list(d.columns),
                "huella": _huella_dataset(d),
            }
            for nombre, d in entradas.items()
        },
        "versiones": _versiones_entorno(),
    }


def _preflight(df: Any, columnas: list[str], nombre_arg: str) -> None:
    """Validación fail-fast con mensajes accionables (F1.4).

    Formato de todo error: qué pasó / por qué importa / qué hacer.
    """
    import pandas as pd

    if not isinstance(df, pd.DataFrame):
        raise TypeError(
            f"Qué pasó: `{nombre_arg}` es {type(df).__name__}, no un DataFrame. "
            f"Por qué importa: el pipeline opera sobre pandas. "
            f"Qué hacer: conviértalo con pd.DataFrame(datos) o cargue con "
            f"pd.read_csv/read_parquet/read_excel."
        )
    if df.empty:
        raise ValueError(
            f"Qué pasó: `{nombre_arg}` está vacío (0 filas). "
            f"Por qué importa: no hay nada que enlazar y un resultado vacío "
            f"suele esconder un error de carga aguas arriba. "
            f"Qué hacer: verifique la ruta/filtros con los que cargó el insumo."
        )
    faltantes = [c for c in columnas if c not in df.columns]
    if faltantes:
        raise ValueError(
            f"Qué pasó: a `{nombre_arg}` le faltan las columnas {faltantes} "
            f"(tiene: {list(df.columns)}). "
            f"Por qué importa: son el insumo del matching. "
            f"Qué hacer: renombre (df.rename(columns={{...}})) o pase "
            f"col_nit=/col_name= con los nombres reales; si la fuente no tiene "
            f"NIT, cree la columna vacía: df['{faltantes[0]}'] = ''."
        )


def dedupe(
    df: pd.DataFrame,
    *,
    col_nit: str = "NIT",
    col_name: str = "RAZON_SOCIAL",
    mode: str = "AGRESIVO",
    profile_con_nit: str | None = None,
    profile_sin_nit: str | None = None,
    output_dir: str | None = None,
) -> ResultadoLinkage:
    """Deduplica UNA tabla por la ruta canónica de producción (F1.1).

    Envuelve `deduplicate_auto` (enrutamiento CON_NIT/SIN_NIT con perfiles
    validados; baseline v0_9_0 y canario de percolación la protegen) sin
    transformar los datos: la correlativa es bit a bit idéntica a la de la
    ruta directa (paridad verificada sobre el GT de 12.427, CHANGELOG 0.9.0).

    Args:
        df: tabla con al menos ``col_nit`` y ``col_name``.
        col_nit: columna de NIT (vacío/None → régimen SIN_NIT).
        col_name: columna de razón social.
        mode: modo de `deduplicate_unified` (default "AGRESIVO").
        profile_con_nit: perfil para el régimen CON_NIT; None = default
            validado de la ruta auto. Ver ``get_profile``/``REGISTRO_PERFILES``.
        profile_sin_nit: ídem para SIN_NIT.
        output_dir: carpeta de salida (reportes y golden por régimen). None →
            temporal; la ruta queda en ``metricas['output_dir']``.

    Returns:
        ResultadoLinkage. ``golden`` es None aquí: los golden y reportes por
        régimen quedan escritos en ``metricas['output_dir']``.

    Raises:
        TypeError | ValueError: preflight accionable (qué pasó / por qué
            importa / qué hacer).

    Ejemplo:
        >>> import pandas as pd, record_linkage as rl
        >>> df = pd.read_parquet("empresas.parquet")
        >>> res = rl.dedupe(df)
        >>> print(res.resumen())
        >>> res.correlativa.to_parquet("correlativa.parquet")
    """
    import tempfile

    from .deduplication.auto import deduplicate_auto

    _preflight(df, [col_nit, col_name], "df")
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="rues_linker_dedupe_")

    kwargs: dict[str, Any] = {}
    if profile_con_nit is not None:
        kwargs["profile_con_nit"] = profile_con_nit
    if profile_sin_nit is not None:
        kwargs["profile_sin_nit"] = profile_sin_nit

    corr, stats = deduplicate_auto(
        df_input=df,
        col_nit=col_nit,
        col_name=col_name,
        mode=mode,
        output_dir=str(output_dir),
        **kwargs,
    )
    metricas: dict[str, Any] = {
        "n_registros": len(corr),
        "n_grupos": int(corr["ID_GRUPO"].nunique()),
        "n_registros_con_nit": int((corr["REGIMEN_AUTO"] == "CON_NIT").sum()),
        "n_registros_sin_nit": int((corr["REGIMEN_AUTO"] == "SIN_NIT").sum()),
        "stats_pipeline": stats,
        "output_dir": str(output_dir),
    }
    manifiesto = _manifiesto(
        "dedupe",
        {
            "col_nit": col_nit,
            "col_name": col_name,
            "mode": mode,
            "profile_con_nit": profile_con_nit,
            "profile_sin_nit": profile_sin_nit,
        },
        {"df": df},
    )
    return ResultadoLinkage(correlativa=corr, golden=None, metricas=metricas, manifiesto=manifiesto)


def link(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    *,
    nombre_a: str = "A",
    nombre_b: str = "B",
    trusted: set[str] | list[str] | None = None,
    col_nit: str = "NIT",
    col_name: str = "RAZON_SOCIAL",
    col_ciudad: str | None = "CIUDAD",
    extra_features: list[str] | None = None,
    profile: str = "produccion_estandar",
    matching_profile: Any = None,
    work_dir: str | None = None,
) -> ResultadoLinkage:
    """Cruza DOS tablas (record linkage A↔B) sobre el Orchestrator (F1.1).

    Un match = ambos registros comparten ``ID_GRUPO`` en la correlativa (la
    columna ``SRC`` dice de qué tabla vino cada uno). Envuelve ``linkage()``
    con dos fuentes, añadiendo preflight, métricas de cruce y manifiesto.

    Args:
        df_a, df_b: tablas con ``col_nit`` y ``col_name`` (NIT puede ir vacío).
        nombre_a, nombre_b: etiquetas de fuente (aparecen en ``SRC``).
        trusted: fuentes con identidad verificada (p. ej. {"RUES"}).
        col_ciudad: columna de ciudad o None si no aplica.
        extra_features: columnas adicionales para el scoring.
        profile: plantilla del Orchestrator (``PERFILES_BASE``).
        matching_profile: refinamiento multi-variable opcional (ver linkage()).
        work_dir: carpeta de trabajo; None → temporal.

    Returns:
        ResultadoLinkage con ``golden`` multi-fuente y, en ``metricas``:
        ``n_grupos_cruzados`` (entidades presentes en AMBAS tablas) y
        ``n_pares_a_b`` (pares registro-a-registro implicados).

    Ejemplo:
        >>> res = rl.link(df_rues, df_aduanas, nombre_a="RUES",
        ...               nombre_b="ADUANAS", trusted={"RUES"})
        >>> cruz = res.correlativa.groupby("ID_GRUPO")["SRC"].nunique()
        >>> res.correlativa[res.correlativa["ID_GRUPO"].isin(cruz[cruz > 1].index)]
    """
    _preflight(df_a, [col_nit, col_name], "df_a")
    _preflight(df_b, [col_nit, col_name], "df_b")
    if nombre_a == nombre_b:
        raise ValueError(
            f"Qué pasó: nombre_a y nombre_b son iguales ('{nombre_a}'). "
            f"Por qué importa: la columna SRC no podría distinguir las fuentes "
            f"y las métricas de cruce serían falsas. "
            f"Qué hacer: use etiquetas distintas, p. ej. nombre_a='RUES', "
            f"nombre_b='ADUANAS'."
        )

    res = linkage(
        sources={nombre_a: df_a, nombre_b: df_b},
        trusted_sources=trusted,
        col_name=col_name,
        col_nit=col_nit,
        col_ciudad=col_ciudad,
        extra_features=extra_features,
        work_dir=work_dir,
        profile=profile,
        matching_profile=matching_profile,
    )
    corr = res["correlative"]

    conteos = (
        corr.groupby(["ID_GRUPO", "SRC"]).size().unstack(fill_value=0)
        if "SRC" in corr.columns
        else None
    )
    if conteos is not None and nombre_a in conteos and nombre_b in conteos:
        mask_cruz = (conteos[nombre_a] > 0) & (conteos[nombre_b] > 0)
        n_cruzados = int(mask_cruz.sum())
        n_pares = int((conteos.loc[mask_cruz, nombre_a] * conteos.loc[mask_cruz, nombre_b]).sum())
    else:  # pragma: no cover - defensivo ante cambios del Orchestrator
        n_cruzados, n_pares = -1, -1

    metricas: dict[str, Any] = {
        "n_registros": len(corr),
        "n_registros_a": len(df_a),
        "n_registros_b": len(df_b),
        "n_grupos": int(corr["ID_GRUPO"].nunique()),
        "n_grupos_cruzados": n_cruzados,
        "n_pares_a_b": n_pares,
        "report_files": res.get("report_files"),
    }
    manifiesto = _manifiesto(
        "link",
        {
            "nombre_a": nombre_a,
            "nombre_b": nombre_b,
            "trusted": sorted(trusted) if trusted else None,
            "col_nit": col_nit,
            "col_name": col_name,
            "col_ciudad": col_ciudad,
            "extra_features": extra_features,
            "profile": profile,
            "matching_profile": str(matching_profile) if matching_profile else None,
        },
        {nombre_a: df_a, nombre_b: df_b},
    )
    return ResultadoLinkage(
        correlativa=corr,
        golden=res.get("golden"),
        metricas=metricas,
        manifiesto=manifiesto,
    )
