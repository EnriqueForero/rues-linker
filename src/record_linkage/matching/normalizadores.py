"""matching.normalizadores — normalización por tipo con diccionarios por locale.

Sustituye la inferencia de genéricos por frecuencia de corpus
(``remove_top_words``, que dejó al régimen SIN_NIT en el filo de percolación,
ver diagnóstico 0.7.6) por **diccionarios declarados por locale**: sufijos
legales y términos genéricos son datos versionados y auditables, no un
artefacto del dataset de turno.

Diseño (F2.3):
    - Toda función es vectorizada (``pd.Series`` → ``pd.Series``); sin bucles
      Python por fila.
    - Quitar genéricos es OPT-IN y con piso: nunca deja un nombre por debajo
      de ``min_tokens`` tokens (el sobre-borrado fue la causa mecánica de la
      percolación SIN_NIT).
    - Placeholders ("SIN DATO", "0", "N/A", …) se normalizan a faltante
      (cadena vacía) ANTES de comparar: la salvaguarda de F2.4 depende de
      esto (ningún override opera sobre faltantes).
    - Locales: ES completo (reusa los 152 sufijos legales validados del
      paquete), EN funcional, KR semilla declarada. Extensible por dict.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from ..processing._constants import LEGAL_SUFFIXES

if TYPE_CHECKING:  # pragma: no cover - solo tipado
    from .campos import CampoSpec

# ═══════════════════════════════════════════════════════════════════════════
# Placeholders → faltante
# ═══════════════════════════════════════════════════════════════════════════

#: Valores que representan "no hay dato" y deben tratarse como faltante.
#: La salvaguarda de F2.4 (ningún override sobre faltantes) parte de aquí.
PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "",
        "0",
        "00",
        "000",
        "N/A",
        "NA",
        "N.A.",
        "NONE",
        "NULL",
        "NAN",
        "SIN DATO",
        "SIN DATOS",
        "SIN INFORMACION",
        "SIN INFORMACIÓN",
        "NO REGISTRA",
        "NO APLICA",
        "NO REPORTA",
        "-",
        "--",
        ".",
        "S/D",
        "SD",
        "X",
        "XX",
        "XXX",
        "PENDIENTE",
        "DESCONOCIDO",
    }
)


def es_faltante(serie: pd.Series) -> np.ndarray:
    """Máscara booleana: True donde el valor es null o placeholder.

    Args:
        serie: valores crudos o normalizados.

    Returns:
        ``np.ndarray[bool]`` por posición.
    """
    s = serie.astype("string")
    limpio = s.str.strip().str.upper()
    return (s.isna() | limpio.isin(PLACEHOLDERS)).to_numpy()


# ═══════════════════════════════════════════════════════════════════════════
# Diccionarios por locale (DECLARADOS, no inferidos)
# ═══════════════════════════════════════════════════════════════════════════

_GENERICOS_ES: frozenset[str] = frozenset(
    {
        "INVERSIONES",
        "COMERCIALIZADORA",
        "DISTRIBUIDORA",
        "DISTRIBUCIONES",
        "IMPORTADORA",
        "EXPORTADORA",
        "REPRESENTACIONES",
        "SERVICIOS",
        "SOLUCIONES",
        "CONSULTORES",
        "CONSULTORIA",
        "ASESORIAS",
        "GRUPO",
        "INTERNACIONAL",
        "NACIONAL",
        "COLOMBIA",
        "COLOMBIANA",
        "ANDINA",
        "GLOBAL",
        "GENERAL",
        "INDUSTRIAS",
        "MANUFACTURAS",
        "PRODUCTOS",
        "SUMINISTROS",
        "LOGISTICA",
        "TRANSPORTES",
        "CONSTRUCCIONES",
        "PROYECTOS",
    }
)

_GENERICOS_EN: frozenset[str] = frozenset(
    {
        "INTERNATIONAL",
        "GLOBAL",
        "GENERAL",
        "GROUP",
        "HOLDINGS",
        "SERVICES",
        "SOLUTIONS",
        "CONSULTING",
        "TRADING",
        "INDUSTRIES",
        "PRODUCTS",
        "SUPPLY",
        "LOGISTICS",
        "TRANSPORT",
        "ENTERPRISES",
        "PARTNERS",
        "VENTURES",
        "WORLDWIDE",
    }
)

_SUFIJOS_EN: frozenset[str] = frozenset(
    {
        "INC",
        "INC.",
        "INCORPORATED",
        "LLC",
        "L.L.C.",
        "LLP",
        "LTD",
        "LTD.",
        "LIMITED",
        "CORP",
        "CORP.",
        "CORPORATION",
        "CO",
        "CO.",
        "COMPANY",
        "PLC",
        "GMBH",
        "S.A.",
        "SA",
    }
)

# Semilla declarada para coreano (razones sociales KR frecuentes en aduanas).
# Ampliable por acta; NO se infiere del corpus.
_SUFIJOS_KR: frozenset[str] = frozenset(
    {
        "주식회사",  # sociedad anónima (prefijo o sufijo)
        "(주)",
        "㈜",
        "유한회사",  # sociedad limitada
        "유한책임회사",
        "합자회사",
        "합명회사",
        "CO LTD",
        "CO., LTD.",
        "CO.,LTD.",
    }
)

_GENERICOS_KR: frozenset[str] = frozenset({"코리아", "인터내셔널", "글로벌", "그룹"})

#: Registro de locales: sufijos legales y genéricos DECLARADOS por idioma.
LOCALES: dict[str, dict[str, frozenset[str]]] = {
    "ES": {"sufijos": frozenset(LEGAL_SUFFIXES), "genericos": _GENERICOS_ES},
    "EN": {"sufijos": _SUFIJOS_EN, "genericos": _GENERICOS_EN},
    "KR": {"sufijos": _SUFIJOS_KR, "genericos": _GENERICOS_KR},
}

#: Abreviaturas viales ES → forma canónica (dirección colombiana).
_ABREV_DIRECCION_ES: dict[str, str] = {
    "CL": "CALLE",
    "CLL": "CALLE",
    "CALL": "CALLE",
    "CRA": "CARRERA",
    "CR": "CARRERA",
    "KR": "CARRERA",
    "KRA": "CARRERA",
    "AV": "AVENIDA",
    "AVDA": "AVENIDA",
    "AK": "AVENIDA CARRERA",
    "AC": "AVENIDA CALLE",
    "DG": "DIAGONAL",
    "DIAG": "DIAGONAL",
    "TV": "TRANSVERSAL",
    "TRANSV": "TRANSVERSAL",
    "APTO": "APARTAMENTO",
    "APT": "APARTAMENTO",
    "OF": "OFICINA",
    "OFC": "OFICINA",
    "ED": "EDIFICIO",
    "EDIF": "EDIFICIO",
    "BRR": "BARRIO",
    "PISO": "PISO",
}


def _ascii_upper(serie: pd.Series) -> pd.Series:
    """MAYÚSCULAS sin tildes (NFKD → ASCII), vectorizado, null→''."""
    s = serie.astype("string").fillna("")
    return (
        s.str.normalize("NFKD")
        .str.encode("ascii", errors="ignore")
        .str.decode("ascii")
        .str.upper()
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )


def _quitar_terminos(serie: pd.Series, terminos: frozenset[str], min_tokens: int) -> pd.Series:
    """Quita términos exactos (por token) respetando el piso ``min_tokens``.

    Si al quitar quedarían menos de ``min_tokens`` tokens, se conserva el
    valor SIN recorte adicional (piso anti-percolación, F2.3).
    """
    if not len(serie):
        return serie
    tokens = serie.str.split()
    filtrados = tokens.apply(lambda ts: [t for t in ts if t not in terminos])
    n_filtrados = filtrados.str.len()
    usar_filtrado = n_filtrados >= min_tokens
    resultado = filtrados.str.join(" ")
    return resultado.where(usar_filtrado, serie)


# ═══════════════════════════════════════════════════════════════════════════
# Normalizadores por tipo (todos: pd.Series → pd.Series de string, ''=faltante)
# ═══════════════════════════════════════════════════════════════════════════


def normalizar_nombre(
    serie: pd.Series,
    *,
    locale: str = "ES",
    quitar_sufijos: bool = True,
    quitar_genericos: bool = False,
    min_tokens: int = 2,
) -> pd.Series:
    """Normaliza razones sociales / nombres de persona.

    Args:
        serie: nombres crudos.
        locale: clave de ``LOCALES`` ("ES", "EN", "KR").
        quitar_sufijos: elimina sufijos legales declarados del locale.
        quitar_genericos: OPT-IN; elimina genéricos declarados del locale,
            nunca por debajo de ``min_tokens`` tokens.
        min_tokens: piso de tokens preservados (anti-percolación).

    Raises:
        KeyError: locale no declarado (lista los disponibles).
    """
    if locale not in LOCALES:
        raise KeyError(
            f"Locale '{locale}' no declarado. Disponibles: {sorted(LOCALES)}. "
            f"Amplíe LOCALES con acta si necesita otro."
        )
    s = (
        _ascii_upper(serie)
        if locale != "KR"
        else (
            serie.astype("string")
            .fillna("")
            .str.replace(r"\s+", " ", regex=True)
            .str.strip()
            .str.upper()
        )
    )
    s = (
        s.str.replace(r"[^\w\s()]", " ", regex=True)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    if quitar_sufijos:
        sufijos_norm = (
            {_ascii_upper(pd.Series([suf])).iloc[0] for suf in LOCALES[locale]["sufijos"]}
            if locale != "KR"
            else set(LOCALES[locale]["sufijos"])
        )
        # Frases multi-token (p. ej. "SUCURSAL DE COLOMBIA"): quitar como frase
        # COMPLETA al final del nombre, nunca token a token (borrar "COLOMBIA"
        # suelto destruiría información real). De más larga a más corta.
        frases = sorted((x for x in sufijos_norm if " " in x), key=lambda x: -len(x.split()))
        for frase in frases:
            s = s.str.replace(rf"\s+{re.escape(frase)}$", "", regex=True)
        # Tokens de una sola palabra (SAS, LTDA, SA, INC…): por token, piso 1.
        tokens_sufijo = frozenset(x for x in sufijos_norm if " " not in x)
        s = _quitar_terminos(s, tokens_sufijo, min_tokens=1)
    if quitar_genericos:
        s = _quitar_terminos(s, LOCALES[locale]["genericos"], min_tokens=min_tokens)
    s = s.where(~pd.Series(es_faltante(s), index=s.index), "")
    return s


def normalizar_identificador(serie: pd.Series) -> pd.Series:
    """NIT/documento: solo dígitos; placeholders y <6 dígitos → faltante ('')."""
    s = serie.astype("string").fillna("").str.replace(r"\D+", "", regex=True)
    s = s.where(s.str.len() >= 6, "")
    return s.where(~s.isin({"0" * k for k in range(6, 16)}), "")


def normalizar_telefono(serie: pd.Series, *, locale: str = "ES") -> pd.Series:
    """Teléfono: dígitos, sin prefijo de país del locale; <7 dígitos → ''.

    Prefijos: ES/CO→57, EN/US→1, KR→82. El comparador ``PhoneLastDigits``
    añade robustez adicional por últimos N dígitos.
    """
    prefijo = {"ES": "57", "EN": "1", "KR": "82"}.get(locale, "")
    s = serie.astype("string").fillna("").str.replace(r"\D+", "", regex=True)
    if prefijo:
        con_prefijo = s.str.startswith(prefijo) & (s.str.len() >= 7 + len(prefijo))
        s = s.where(~con_prefijo, s.str.slice(len(prefijo)))
    return s.where(s.str.len() >= 7, "")


def normalizar_email(serie: pd.Series) -> pd.Series:
    """Email: minúsculas y trim; sin '@' o placeholder → faltante ('')."""
    s = serie.astype("string").fillna("").str.strip().str.lower()
    s = s.where(s.str.contains("@", regex=False), "")
    return s.where(~pd.Series(es_faltante(s), index=s.index), "")


def normalizar_direccion(serie: pd.Series, *, locale: str = "ES") -> pd.Series:
    """Dirección: ASCII/upper + abreviaturas viales canónicas del locale."""
    s = _ascii_upper(serie)
    s = s.str.replace(r"[#º°\.]", " ", regex=True)
    s = s.str.replace(r"\bNO\b", " ", regex=True)
    if locale == "ES":
        for abrev, canon in _ABREV_DIRECCION_ES.items():
            s = s.str.replace(rf"\b{abrev}\b", canon, regex=True)
    s = s.str.replace(r"\s+", " ", regex=True).str.strip()
    return s.where(~pd.Series(es_faltante(s), index=s.index), "")


def normalizar_ciudad(serie: pd.Series) -> pd.Series:
    """Ciudad: ASCII/upper/trim; placeholders → ''."""
    s = _ascii_upper(serie)
    return s.where(~pd.Series(es_faltante(s), index=s.index), "")


def normalizar_fecha(serie: pd.Series, *, locale: str = "ES") -> pd.Series:
    """Fecha → ISO 'YYYY-MM-DD' como string; inválidas → ''.

    ``dayfirst`` según locale (ES=True). El comparador trabaja en días.
    """
    dt = pd.to_datetime(serie, errors="coerce", dayfirst=(locale == "ES"))
    return dt.dt.strftime("%Y-%m-%d").fillna("")


def normalizar_numero(serie: pd.Series) -> pd.Series:
    """Numérico → string canónico de float; inválidos → ''."""
    v = pd.to_numeric(serie.astype("string").str.replace(",", ".", regex=False), errors="coerce")
    return v.map(lambda x: "" if pd.isna(x) else repr(float(x))).astype("string")


def normalizar_geo(lat: pd.Series, lon: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Lat/Lon → floats válidos; fuera de rango o no numérico → NaN."""
    la = pd.to_numeric(lat, errors="coerce")
    lo = pd.to_numeric(lon, errors="coerce")
    ok = la.between(-90, 90) & lo.between(-180, 180)
    return la.where(ok), lo.where(ok)


def normalizar_categorico(serie: pd.Series) -> pd.Series:
    """Categórico: ASCII/upper/trim; placeholders → ''."""
    return normalizar_ciudad(serie)


def normalizar_campo(serie: pd.Series, campo: CampoSpec) -> pd.Series:
    """Aplica el normalizador del tipo declarado en ``campo`` (registro F2.3)."""
    from .campos import TipoCampo  # import local: evita ciclo campos↔normalizadores

    t = campo.tipo
    if t in (TipoCampo.NOMBRE_EMPRESA, TipoCampo.NOMBRE_PERSONA):
        return normalizar_nombre(
            serie,
            locale=campo.locale,
            quitar_sufijos=campo.params.get("quitar_sufijos", True),
            quitar_genericos=campo.params.get("quitar_genericos", False),
            min_tokens=campo.params.get("min_tokens", 2),
        )
    if t is TipoCampo.IDENTIFICADOR:
        return normalizar_identificador(serie)
    if t is TipoCampo.TELEFONO:
        return normalizar_telefono(serie, locale=campo.locale)
    if t is TipoCampo.EMAIL:
        return normalizar_email(serie)
    if t is TipoCampo.DIRECCION:
        return normalizar_direccion(serie, locale=campo.locale)
    if t is TipoCampo.CIUDAD:
        return normalizar_ciudad(serie)
    if t is TipoCampo.FECHA:
        return normalizar_fecha(serie, locale=campo.locale)
    if t is TipoCampo.NUMERICO:
        return normalizar_numero(serie)
    if t is TipoCampo.CATEGORICO:
        return normalizar_categorico(serie)
    raise ValueError(f"Tipo sin normalizador de serie única: {t} (GEO usa normalizar_geo).")
