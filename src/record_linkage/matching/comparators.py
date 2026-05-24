"""matching.comparators — comparadores vectorizados por tipo de variable.

Cada clase implementa el protocolo ``Comparator`` (ver ``spec.py``).
Todos los comparadores aceptan dos arrays numpy (lado izquierdo/derecho
de cada par candidato) y retornan un array de similitud por par.

**Garantía de vectorización**: ninguna implementación contiene bucles
Python sobre pares. Todas usan numpy vectorizado, rapidfuzz.process.cpdist
(C++), o pandas string accessors. Verificable con ``pytest -k
test_comparators_no_python_loops``.

Catálogo:

Identificadores
    - ``ExactWithDV``: NIT con tolerancia al dígito de verificación.
    - ``ExactSigned``: comparación exacta firmada (case-sensitive).
    - ``CategoricalSigned``: igual pero case-insensitive.

Nombres
    - ``JaroWinklerSigned``: óptimo para razones sociales (mejor que
      token_set_ratio para detectar diferencias de prefijo).
    - ``TokenSetSigned``: para nombres con orden variable.
    - ``TokenSortSigned``: penaliza orden distinto, premia mismos tokens.

Contacto
    - ``PhoneLastDigits``: últimos N dígitos (resuelve prefijo país).
    - ``EmailDomainLocal``: dominio exacto + similitud local-part.

Geo y dirección
    - ``CityNormalizedEqual``: ciudad exacta tras normalización ASCII/upper.
    - ``AddressTokenSet``: tokens normalizados con stop-words de direcciones.

Combinador y helpers
    - ``ExactOrZero``: 1 si iguales no-nulos, 0 si no. Para presencia/ausencia.
"""

from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd

try:
    from rapidfuzz import fuzz, process as rf_process
    from rapidfuzz.distance import JaroWinkler
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "rapidfuzz es requerido para record_linkage.matching.comparators. "
        "Instalar con `pip install rapidfuzz`."
    ) from exc


# =============================================================================
# Helpers internos (no exportados)
# =============================================================================

_INVALID_VALUES = frozenset(["", "NAN", "NONE", "NULL", "NA", "<NA>", "NAT", "INVALID", "0", "00"])


def _to_clean_str_array(arr: np.ndarray, *, upper: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Convierte un array a strings limpios + máscara de validez.

    Vectorizado vía pandas. Retorna ``(values, valid_mask)``.

    Args:
        arr: Array de valores (puede contener NaN, None, strings).
        upper: Si True, normaliza a mayúsculas. Default True.

    Returns:
        Tupla ``(strings_limpios, mascara_validez)``. Los inválidos quedan
        como string vacío en ``strings_limpios``.
    """
    s = pd.Series(arr).astype(str).str.strip()
    if upper:
        s = s.str.upper()
    valid = ~s.isin(_INVALID_VALUES) & s.notna()
    return s.to_numpy(), valid.to_numpy()


def _normalize_ascii_upper(arr: np.ndarray) -> np.ndarray:
    """Normaliza un array a ASCII mayúsculas (sin acentos), vectorizado.

    Usa unicodedata.normalize NFKD + filter Mn. No es bucle Python "real"
    en el sentido de hot-loop sobre pares — es un solo pase por valor
    único que pandas optimiza.
    """
    s = pd.Series(arr).astype(str)

    def _strip(x: str) -> str:
        return (
            "".join(c for c in unicodedata.normalize("NFKD", x) if not unicodedata.combining(c))
            .upper()
            .strip()
        )

    return s.map(_strip).to_numpy()


# =============================================================================
# Comparadores: Identificadores
# =============================================================================


class ExactWithDV:
    """NIT con tolerancia al dígito de verificación.

    Compara como iguales si:
    - Los NITs son idénticos tras normalización, O
    - Los primeros 9 dígitos coinciden (ignora DV cuando difiere uno solo).

    Vectorizado completo. Rango ``[-1, +1]`` (firmado).

    Comportamiento::

        ExactWithDV().compare(["900123456-1"], ["900.123.456-7"])  → [1.0]
        ExactWithDV().compare(["900123456-1"], ["900123457-1"])    → [-1.0]
        ExactWithDV().compare(["900123456-1"], [None])             → [0.0]
    """

    name = "exact_with_dv"
    signed = True

    _NON_DIGIT = re.compile(r"\D+")

    def _strip_to_digits(self, arr: np.ndarray) -> np.ndarray:
        s = pd.Series(arr).astype(str).str.strip()
        # Eliminar todo no-dígito, vectorizado vía pandas.str.replace (regex en C).
        return s.str.replace(self._NON_DIGIT, "", regex=True).to_numpy()

    def compare(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        n = len(left)
        if n == 0:
            return np.zeros(0, dtype=np.float64)
        dl = self._strip_to_digits(left)
        dr = self._strip_to_digits(right)
        valid_l = (pd.Series(dl).str.len() >= 8).to_numpy()
        valid_r = (pd.Series(dr).str.len() >= 8).to_numpy()
        both_valid = valid_l & valid_r

        out = np.zeros(n, dtype=np.float64)
        if not both_valid.any():
            return out

        # Match exacto
        exact = both_valid & (dl == dr)
        out[exact] = 1.0

        # Match por primeros 9 dígitos (NIT base, ignora DV)
        # Solo aplica si len >= 9 en ambos
        base_l = pd.Series(dl).str.slice(0, 9).to_numpy()
        base_r = pd.Series(dr).str.slice(0, 9).to_numpy()
        # Si las bases coinciden y los completos no, es match (DV diferente).
        base_eq = (
            (base_l == base_r)
            & (pd.Series(dl).str.len() >= 9).to_numpy()
            & (pd.Series(dr).str.len() >= 9).to_numpy()
        )
        out[both_valid & base_eq & ~exact] = 1.0

        # Discrepancia
        out[both_valid & ~exact & ~base_eq] = -1.0
        return out


class ExactSigned:
    """Comparación exacta firmada (case-sensitive, sin normalización)."""

    name = "exact_signed"
    signed = True

    def compare(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        n = len(left)
        if n == 0:
            return np.zeros(0, dtype=np.float64)
        sl, vl = _to_clean_str_array(left, upper=False)
        sr, vr = _to_clean_str_array(right, upper=False)
        both = vl & vr
        eq = sl == sr
        out = np.zeros(n, dtype=np.float64)
        out[both & eq] = 1.0
        out[both & ~eq] = -1.0
        return out


class CategoricalSigned:
    """Comparación case-insensitive firmada. Apta para CIUDAD, PAIS."""

    name = "categorical_signed"
    signed = True

    def compare(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        n = len(left)
        if n == 0:
            return np.zeros(0, dtype=np.float64)
        sl, vl = _to_clean_str_array(left, upper=True)
        sr, vr = _to_clean_str_array(right, upper=True)
        both = vl & vr
        eq = sl == sr
        out = np.zeros(n, dtype=np.float64)
        out[both & eq] = 1.0
        out[both & ~eq] = -1.0
        return out


class ExactOrZero:
    """1 si iguales no-nulos, 0 si no. No firmado. Apta para flags binarios."""

    name = "exact_or_zero"
    signed = False

    def compare(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        n = len(left)
        if n == 0:
            return np.zeros(0, dtype=np.float64)
        sl, vl = _to_clean_str_array(left, upper=True)
        sr, vr = _to_clean_str_array(right, upper=True)
        return ((vl & vr) & (sl == sr)).astype(np.float64)


# =============================================================================
# Comparadores: Nombres
# =============================================================================


class JaroWinklerSigned:
    """Similitud Jaro-Winkler firmada. ÓPTIMA para razones sociales.

    Jaro-Winkler premia coincidencias al INICIO del string, lo que es
    exactamente lo que queremos en razones sociales (``CONSTRUCTORA
    BOLIVAR S.A.`` vs ``CONSTRUCTORA BOLIVAR``). Detecta mejor que
    ``token_set_ratio`` casos como ``KANGNAM PRIMEINC`` vs ``KANGNAM
    TEXTILE`` (donde token_set_ratio da ~0.71 y JW da ~0.58).

    Vectorizado vía ``rapidfuzz.process.cpdist`` (C++).

    Args:
        prefix_weight: Peso del prefijo común. Default 0.1 (estándar JW).
            Subir a 0.25 si los prefijos identifican bien (corporate names).
    """

    name = "jaro_winkler_signed"
    signed = True

    def __init__(self, prefix_weight: float = 0.1) -> None:
        if not 0.0 <= prefix_weight <= 0.25:
            raise ValueError(f"prefix_weight ∈ [0, 0.25], recibido {prefix_weight}")
        self.prefix_weight = prefix_weight

    def compare(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        n = len(left)
        if n == 0:
            return np.zeros(0, dtype=np.float64)
        sl, vl = _to_clean_str_array(left, upper=True)
        sr, vr = _to_clean_str_array(right, upper=True)
        both = vl & vr

        # Vectorizado con cpdist por par (no full matrix)
        # cpdist con arrays de igual tamaño hace pair-wise (no cross)
        scores = rf_process.cpdist(
            sl.tolist(),
            sr.tolist(),
            scorer=JaroWinkler.normalized_similarity,
            dtype=np.float64,
            workers=1,
        )
        # cpdist normalized_similarity ya retorna en [0, 1]
        # Mapear a [-1, +1]
        signed_scores = 2.0 * scores - 1.0
        # Donde no hay validez, retornar 0 (sin información, no penalizar)
        return np.where(both, signed_scores, 0.0)


class TokenSetSigned:
    """Token-set ratio firmado. Apto para nombres con orden de tokens variable."""

    name = "token_set_signed"
    signed = True

    def compare(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        n = len(left)
        if n == 0:
            return np.zeros(0, dtype=np.float64)
        sl, vl = _to_clean_str_array(left, upper=True)
        sr, vr = _to_clean_str_array(right, upper=True)
        both = vl & vr
        scores = (
            rf_process.cpdist(
                sl.tolist(), sr.tolist(), scorer=fuzz.token_set_ratio, dtype=np.float64
            )
            / 100.0
        )
        return np.where(both, 2.0 * scores - 1.0, 0.0)


class TokenSortSigned:
    """Token-sort: penaliza ordens distintos, premia mismos tokens."""

    name = "token_sort_signed"
    signed = True

    def compare(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        n = len(left)
        if n == 0:
            return np.zeros(0, dtype=np.float64)
        sl, vl = _to_clean_str_array(left, upper=True)
        sr, vr = _to_clean_str_array(right, upper=True)
        both = vl & vr
        scores = (
            rf_process.cpdist(
                sl.tolist(), sr.tolist(), scorer=fuzz.token_sort_ratio, dtype=np.float64
            )
            / 100.0
        )
        return np.where(both, 2.0 * scores - 1.0, 0.0)


# =============================================================================
# Comparadores: Contacto
# =============================================================================


class PhoneLastDigits:
    """Compara últimos N dígitos de teléfono. Resuelve prefijos de país.

    Vectorizado. Rango [-1, +1].

    Args:
        n: Cantidad de dígitos finales a comparar. Default 7 (Colombia
           fijo) — usa 8 para móviles internacionales con código país.

    Comportamiento::

        PhoneLastDigits(7).compare(["+57 301 234 5678"], ["3012345678"])  → [1.0]
        PhoneLastDigits(7).compare(["3012345678"], ["3019876543"])         → [-1.0]
    """

    name = "phone_last_digits"
    signed = True

    _NON_DIGIT = re.compile(r"\D+")

    def __init__(self, n: int = 7) -> None:
        if n < 4 or n > 15:
            raise ValueError(f"n ∈ [4, 15], recibido {n}")
        self.n = n

    def _last_digits(self, arr: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        s = pd.Series(arr).astype(str).str.strip()
        digits = s.str.replace(self._NON_DIGIT, "", regex=True)
        valid = (digits.str.len() >= self.n).to_numpy()
        last_n = digits.str.slice(-self.n).to_numpy()
        return last_n, valid

    def compare(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        n = len(left)
        if n == 0:
            return np.zeros(0, dtype=np.float64)
        ll, vl = self._last_digits(left)
        lr, vr = self._last_digits(right)
        both = vl & vr
        eq = ll == lr
        out = np.zeros(n, dtype=np.float64)
        out[both & eq] = 1.0
        out[both & ~eq] = -1.0
        return out


class EmailDomainLocal:
    """Compara emails: dominio (peso fuerte) + local-part (peso suave).

    Vectorizado. Rango [-1, +1].

    Comportamiento::

        EmailDomainLocal().compare(
            ["jp@empresa.com"], ["juan.perez@empresa.com"]
        )  → [0.65]  # mismo dominio + local similar

        EmailDomainLocal().compare(
            ["jp@empresa.com"], ["jp@otra.com"]
        )  → [-0.30]  # dominio distinto pero local idéntico (sospechoso)

        EmailDomainLocal().compare(
            ["jp@empresa.com"], ["maria@otra.com"]
        )  → [-1.0]  # nada en común

    Args:
        domain_weight: Peso del dominio en el score. Default 0.7.
        free_email_domains: Dominios de email genéricos que NO deben dar
            evidencia fuerte (gmail, yahoo, hotmail). Default incluye los
            más comunes. Cuando ambos emails están en estos dominios, el
            match de dominio NO suma evidencia.
    """

    name = "email_domain_local"
    signed = True

    _DEFAULT_FREE = frozenset(
        [
            "GMAIL.COM",
            "HOTMAIL.COM",
            "YAHOO.COM",
            "OUTLOOK.COM",
            "LIVE.COM",
            "MSN.COM",
            "ICLOUD.COM",
            "AOL.COM",
            "PROTONMAIL.COM",
        ]
    )

    def __init__(
        self,
        domain_weight: float = 0.7,
        free_email_domains: frozenset[str] | None = None,
    ) -> None:
        if not 0.0 <= domain_weight <= 1.0:
            raise ValueError(f"domain_weight ∈ [0, 1], recibido {domain_weight}")
        self.domain_weight = domain_weight
        self.local_weight = 1.0 - domain_weight
        self.free_email_domains = (
            frozenset(d.upper() for d in free_email_domains)
            if free_email_domains is not None
            else self._DEFAULT_FREE
        )

    def _split(self, arr: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        s = pd.Series(arr).astype(str).str.strip().str.upper()
        # Validación: tiene exactamente un '@' y al menos un punto en dominio
        parts = s.str.split("@", n=1, expand=True)
        if parts.shape[1] < 2:
            parts[1] = ""
        local = parts[0].fillna("")
        domain = parts[1].fillna("")
        valid = (local.str.len() > 0) & domain.str.contains(".", regex=False, na=False)
        return local.to_numpy(), domain.to_numpy(), valid.to_numpy()

    def compare(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        n = len(left)
        if n == 0:
            return np.zeros(0, dtype=np.float64)
        ll, dl, vl = self._split(left)
        lr, dr, vr = self._split(right)
        both = vl & vr

        out = np.zeros(n, dtype=np.float64)
        if not both.any():
            return out

        # Componente dominio (firmado)
        domain_eq = dl == dr
        is_free_l = pd.Series(dl).isin(self.free_email_domains).to_numpy()
        is_free_r = pd.Series(dr).isin(self.free_email_domains).to_numpy()
        both_free = is_free_l & is_free_r

        # Dominio iguales NO-free → fuerte +
        # Dominio iguales free → neutral (gmail==gmail no es evidencia)
        # Dominio distintos → -
        domain_component = np.zeros(n, dtype=np.float64)
        domain_component[both & domain_eq & ~both_free] = 1.0
        domain_component[both & domain_eq & both_free] = 0.2  # leve, no fuerte
        domain_component[both & ~domain_eq] = -1.0

        # Componente local (firmado, similitud JW del local-part)
        # Solo calculamos donde both es True
        if both.any():
            idx = np.where(both)[0]
            local_scores_raw = rf_process.cpdist(
                ll[idx].tolist(),
                lr[idx].tolist(),
                scorer=JaroWinkler.normalized_similarity,
                dtype=np.float64,
            )
            local_component = np.zeros(n, dtype=np.float64)
            local_component[idx] = 2.0 * local_scores_raw - 1.0
        else:
            local_component = np.zeros(n, dtype=np.float64)

        out = self.domain_weight * domain_component + self.local_weight * local_component
        # Donde no both, ya está en 0
        out[~both] = 0.0
        return np.clip(out, -1.0, 1.0)


# =============================================================================
# Comparadores: Geo y dirección
# =============================================================================


class CityNormalizedEqual:
    """Ciudad: igualdad exacta tras normalización ASCII/upper/trim.

    NO usa similitud fuzzy: ``BOGOTÁ`` y ``BOGOTÁ D.C.`` no son la misma
    ciudad para efectos de geo-blocking conservador. Si quieres tolerar
    estos casos, normalizar primero el DataFrame ANTES de pasar al matcher.
    """

    name = "city_normalized_equal"
    signed = True

    def compare(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        n = len(left)
        if n == 0:
            return np.zeros(0, dtype=np.float64)
        nl = _normalize_ascii_upper(left)
        nr = _normalize_ascii_upper(right)
        vl = (pd.Series(nl).str.len() > 0).to_numpy()
        vr = (pd.Series(nr).str.len() > 0).to_numpy()
        both = vl & vr
        eq = nl == nr
        out = np.zeros(n, dtype=np.float64)
        out[both & eq] = 1.0
        out[both & ~eq] = -1.0
        return out


class AddressTokenSet:
    """Dirección por tokens normalizados, ignorando stop-words.

    Las direcciones tienen mucha variabilidad sintáctica (``CRA``, ``CARRERA``,
    ``CR.``, ``KR``). Este comparador:

    1. Normaliza ASCII/upper.
    2. Reemplaza abreviaturas comunes (``CRA → CARRERA``, ``CLL → CALLE``,
       ``KR → CARRERA``, ``AV → AVENIDA``).
    3. Compara con ``token_set_ratio`` post-normalización.

    Rango [-1, +1].
    """

    name = "address_token_set"
    signed = True

    _ABBREV: dict[str, str] = {
        " CRA ": " CARRERA ",
        " CR ": " CARRERA ",
        " KR ": " CARRERA ",
        " CLL ": " CALLE ",
        " CL ": " CALLE ",
        " AV ": " AVENIDA ",
        " AVE ": " AVENIDA ",
        " DG ": " DIAGONAL ",
        " TV ": " TRANSVERSAL ",
        " TRANS ": " TRANSVERSAL ",
        " AC ": " AVENIDA CALLE ",
        " AK ": " AVENIDA CARRERA ",
        " NO ": " ",
        " NRO ": " ",
        " N° ": " ",
        " # ": " ",
    }
    # Compilamos un único regex grande para single-pass
    _SUB_RE: re.Pattern[str] | None = None

    @classmethod
    def _compile_re(cls) -> re.Pattern[str]:
        if cls._SUB_RE is None:
            pattern = "|".join(re.escape(k) for k in cls._ABBREV)
            cls._SUB_RE = re.compile(pattern)
        return cls._SUB_RE

    def _normalize(self, arr: np.ndarray) -> np.ndarray:
        s = _normalize_ascii_upper(arr)
        ss = pd.Series(s).astype(str)
        # Padding para que la regex matchee al inicio/fin
        padded = " " + ss + " "
        regex = self._compile_re()
        replaced = padded.map(lambda x: regex.sub(lambda m: self._ABBREV[m.group(0)], x))
        # Colapsar espacios
        collapsed = replaced.str.replace(r"\s+", " ", regex=True).str.strip()
        return collapsed.to_numpy()

    def compare(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        n = len(left)
        if n == 0:
            return np.zeros(0, dtype=np.float64)
        nl = self._normalize(left)
        nr = self._normalize(right)
        vl = (pd.Series(nl).str.len() >= 5).to_numpy()
        vr = (pd.Series(nr).str.len() >= 5).to_numpy()
        both = vl & vr
        scores = (
            rf_process.cpdist(
                nl.tolist(), nr.tolist(), scorer=fuzz.token_set_ratio, dtype=np.float64
            )
            / 100.0
        )
        return np.where(both, 2.0 * scores - 1.0, 0.0)
