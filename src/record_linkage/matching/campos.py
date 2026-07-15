"""matching.campos — sistema de tipos de campo y esquema declarativo (F2.1).

El usuario declara QUÉ es cada columna (tipo, peso, política de faltantes,
locale) y el motor deriva el CÓMO (normalizador, comparador, bloqueo). La
generalidad "muchas variables de diferente tipo" del playbook vive aquí.

Salvaguarda central (F2.4, aprendida del diagnóstico 0.7.6): ninguna regla
de override —"identificador idéntico manda match"— opera jamás sobre valores
faltantes o placeholders. Los normalizadores convierten placeholders en
faltante ('') y los comparadores devuelven 0.0 (neutro) ante faltantes, de
modo que un override exige similitud ≈ 1.0, imposible con faltantes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from .comparators import (
    AddressTokenSet,
    CategoricalSigned,
    CityNormalizedEqual,
    EmailDomainLocal,
    ExactWithDV,
    FechaDelta,
    GeoHaversine,
    JaroWinklerSigned,
    NumericoRelativo,
    PhoneLastDigits,
    TokenSetSigned,
)
from .normalizadores import LOCALES

if TYPE_CHECKING:  # pragma: no cover - solo tipado
    import pandas as pd

    from .spec import Comparator


class TipoCampo(str, Enum):
    """Tipos de campo soportados por el motor multicampo (F2.1)."""

    NOMBRE_EMPRESA = "nombre_empresa"
    NOMBRE_PERSONA = "nombre_persona"
    IDENTIFICADOR = "identificador"  # NIT/documento; DV vía comparador
    TELEFONO = "telefono"
    EMAIL = "email"
    DIRECCION = "direccion"
    CIUDAD = "ciudad"
    GEO = "geo"  # lat/lon; requiere columna_lon
    FECHA = "fecha"
    NUMERICO = "numerico"
    CATEGORICO = "categorico"


class PoliticaFaltante(str, Enum):
    """Política ante faltantes por campo (F2.4), declarada en el esquema.

    - ``IGNORAR`` (default seguro): el campo sale del score de ESE par y los
      pesos restantes se renormalizan. No inventa señal ni castiga ausencia.
    - ``PENALIZAR``: el campo aporta 0 pero su peso SÍ cuenta (diluye el
      score). Para campos donde la ausencia es informativa.
    - ``BLOQUEAR``: si el campo falta en cualquiera de los dos registros,
      el par NO puede fusionarse (generaliza ``required_for_match``).
    """

    IGNORAR = "ignorar"
    PENALIZAR = "penalizar"
    BLOQUEAR = "bloquear"


#: Parámetros admitidos en ``CampoSpec.params`` por tipo (validación fail-fast).
_PARAMS_POR_TIPO: dict[TipoCampo, frozenset[str]] = {
    TipoCampo.NOMBRE_EMPRESA: frozenset({"quitar_sufijos", "quitar_genericos", "min_tokens"}),
    TipoCampo.NOMBRE_PERSONA: frozenset({"quitar_sufijos", "quitar_genericos", "min_tokens"}),
    TipoCampo.IDENTIFICADOR: frozenset(),
    TipoCampo.TELEFONO: frozenset({"ultimos_digitos"}),
    TipoCampo.EMAIL: frozenset(),
    TipoCampo.DIRECCION: frozenset(),
    TipoCampo.CIUDAD: frozenset(),
    TipoCampo.GEO: frozenset({"radio_km"}),
    TipoCampo.FECHA: frozenset({"dias_tolerancia"}),
    TipoCampo.NUMERICO: frozenset({"tolerancia_relativa"}),
    TipoCampo.CATEGORICO: frozenset(),
}

#: Umbral de concordancia por defecto (γ Fellegi-Sunter): exactos 0.99, fuzzy 0.85.
_UMBRAL_DEFECTO: dict[TipoCampo, float] = {
    TipoCampo.NOMBRE_EMPRESA: 0.85,
    TipoCampo.NOMBRE_PERSONA: 0.85,
    TipoCampo.IDENTIFICADOR: 0.99,
    TipoCampo.TELEFONO: 0.99,
    TipoCampo.EMAIL: 0.90,
    TipoCampo.DIRECCION: 0.80,
    TipoCampo.CIUDAD: 0.99,
    TipoCampo.GEO: 0.80,
    TipoCampo.FECHA: 0.80,
    TipoCampo.NUMERICO: 0.80,
    TipoCampo.CATEGORICO: 0.99,
}


def comparador_por_defecto(tipo: TipoCampo, params: dict[str, Any]) -> Comparator:
    """Comparador canónico por tipo (F2.2); reemplazable vía ``CampoSpec.comparador``."""
    if tipo is TipoCampo.NOMBRE_EMPRESA:
        return JaroWinklerSigned()
    if tipo is TipoCampo.NOMBRE_PERSONA:
        return TokenSetSigned()  # robusto a APELLIDO NOMBRE vs NOMBRE APELLIDO
    if tipo is TipoCampo.IDENTIFICADOR:
        return ExactWithDV()  # NIT CO; otros países: pase comparador= explícito
    if tipo is TipoCampo.TELEFONO:
        return PhoneLastDigits(n=int(params.get("ultimos_digitos", 7)))
    if tipo is TipoCampo.EMAIL:
        return EmailDomainLocal()
    if tipo is TipoCampo.DIRECCION:
        return AddressTokenSet()
    if tipo is TipoCampo.CIUDAD:
        return CityNormalizedEqual()
    if tipo is TipoCampo.GEO:
        return GeoHaversine(radio_km=float(params.get("radio_km", 1.0)))
    if tipo is TipoCampo.FECHA:
        return FechaDelta(dias_tolerancia=int(params.get("dias_tolerancia", 30)))
    if tipo is TipoCampo.NUMERICO:
        return NumericoRelativo(tolerancia=float(params.get("tolerancia_relativa", 0.10)))
    if tipo is TipoCampo.CATEGORICO:
        return CategoricalSigned()
    raise ValueError(f"Tipo sin comparador por defecto: {tipo}")


@dataclass
class CampoSpec:
    """Declaración de un campo del esquema (F2.1).

    Args:
        nombre: columna en el DataFrame (para GEO: la columna de LATITUD).
        tipo: ``TipoCampo`` del contenido.
        peso: peso relativo en el score (se renormaliza por par). > 0.
        faltante: ``PoliticaFaltante`` (default seguro: IGNORAR).
        locale: clave de ``normalizadores.LOCALES`` para tipos de texto.
        comparador: instancia de ``Comparator``; None → default del tipo.
        umbral_concordancia: γ del campo; None → default del tipo.
        veta_discrepancia: una discrepancia fuerte (score ≤ −0.5) prohíbe la
            fusión del par; None → True solo para IDENTIFICADOR (la lección
            del diagnóstico: NITs distintos jamás se fusionan).
        columna_lon: SOLO tipo GEO — columna de longitud.
        params: parámetros del tipo (ver ``_PARAMS_POR_TIPO``).
    """

    nombre: str
    tipo: TipoCampo
    peso: float = 1.0
    faltante: PoliticaFaltante = PoliticaFaltante.IGNORAR
    locale: str = "ES"
    comparador: Comparator | None = None
    umbral_concordancia: float | None = None
    veta_discrepancia: bool | None = None
    columna_lon: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.tipo = TipoCampo(self.tipo)
        self.faltante = PoliticaFaltante(self.faltante)
        if not self.nombre or not str(self.nombre).strip():
            raise ValueError("CampoSpec.nombre no puede ser vacío.")
        if not (isinstance(self.peso, (int, float)) and self.peso > 0):
            raise ValueError(f"Campo '{self.nombre}': peso={self.peso!r} inválido (debe ser > 0).")
        if self.locale not in LOCALES:
            raise KeyError(
                f"Campo '{self.nombre}': locale '{self.locale}' no declarado. "
                f"Disponibles: {sorted(LOCALES)}."
            )
        desconocidos = set(self.params) - _PARAMS_POR_TIPO[self.tipo]
        if desconocidos:
            raise ValueError(
                f"Campo '{self.nombre}' (tipo {self.tipo.value}): params "
                f"desconocidos {sorted(desconocidos)}. Admitidos: "
                f"{sorted(_PARAMS_POR_TIPO[self.tipo]) or '(ninguno)'}."
            )
        if self.tipo is TipoCampo.GEO and not self.columna_lon:
            raise ValueError(
                f"Campo '{self.nombre}': tipo GEO requiere columna_lon= "
                f"(nombre = columna de latitud; columna_lon = longitud)."
            )
        if self.tipo is not TipoCampo.GEO and self.columna_lon:
            raise ValueError(f"Campo '{self.nombre}': columna_lon solo aplica a tipo GEO.")
        if self.comparador is None:
            self.comparador = comparador_por_defecto(self.tipo, self.params)
        if self.umbral_concordancia is None:
            self.umbral_concordancia = _UMBRAL_DEFECTO[self.tipo]
        if self.veta_discrepancia is None:
            self.veta_discrepancia = self.tipo is TipoCampo.IDENTIFICADOR

    @property
    def columnas(self) -> list[str]:
        """Columnas del DataFrame que este campo consume."""
        if self.tipo is TipoCampo.GEO:
            return [self.nombre, str(self.columna_lon)]
        return [self.nombre]


@dataclass(frozen=True)
class CorroboracionVeto:
    """Regla de corroboración que puede LEVANTAR un veto de identificador (F3).

    Motivación: dos registros de la MISMA entidad pueden tener NITs distintos
    (un dígito mal capturado, o cambio de NIT por reestructuración). El veto
    de identificador los separa por seguridad. Esta regla permite reunirlos
    SOLO cuando hay evidencia independiente fuerte de que son el mismo ente:
    campos como email o teléfono idénticos (alta entropía), acompañados de
    alta similitud de nombre.

    Salvaguarda anti-falsos-positivos (hereda la filosofía F2.4): la
    corroboración NUNCA opera sobre faltantes ni sobre valores de baja
    entropía (un email genérico gmail compartido, un teléfono de call center).
    El comparador de cada campo ya devuelve 0.0 ante faltantes/placeholders,
    de modo que ``sim ≥ umbral_campo`` exige un valor real y (casi) idéntico.

    Attributes:
        campos_corroborantes: nombres de campo cuya igualdad cuenta como
            evidencia (p. ej. ("EMAIL", "TELEFONO")). Deben existir en el
            esquema y no ser el propio identificador.
        umbral_campo: similitud mínima para considerar un campo "idéntico"
            (default 0.99: prácticamente igualdad exacta).
        min_corroborantes: cuántos de esos campos deben ser idénticos para
            levantar el veto (default 1).
        umbral_nombre_empresa: similitud mínima de nombre de empresa exigida
            en paralelo (default 0.90). Evita reunir entidades homónimas.
        activa: interruptor. Por defecto False → el motor se comporta EXACTO
            como antes de F3 (cero cambios de comportamiento hasta activarla).
    """

    campos_corroborantes: tuple[str, ...] = ()
    umbral_campo: float = 0.99
    min_corroborantes: int = 1
    umbral_nombre_empresa: float = 0.90
    activa: bool = False

    def __post_init__(self) -> None:
        if not (0.0 < self.umbral_campo <= 1.0):
            raise ValueError(f"umbral_campo={self.umbral_campo} fuera de (0, 1].")
        if not (0.0 <= self.umbral_nombre_empresa <= 1.0):
            raise ValueError(f"umbral_nombre_empresa={self.umbral_nombre_empresa} fuera de [0, 1].")
        if self.min_corroborantes < 1:
            raise ValueError("min_corroborantes debe ser >= 1.")
        if self.activa and not self.campos_corroborantes:
            raise ValueError("CorroboracionVeto activa requiere al menos un campo corroborante.")
        if self.activa and self.min_corroborantes > len(self.campos_corroborantes):
            raise ValueError(
                f"min_corroborantes={self.min_corroborantes} supera el nº de "
                f"campos corroborantes ({len(self.campos_corroborantes)})."
            )


@dataclass
class EsquemaCampos:
    """Esquema declarativo completo (F2.6): campos + umbrales de decisión.

    Args:
        campos: lista de ``CampoSpec`` (nombres de columna únicos).
        umbral_score: score ponderado mínimo para fusionar (default 0.65).
        min_concordancias: nº mínimo de campos que deben concordar (γ=1).
        nombre: etiqueta del esquema (aparece en manifiestos).
        corroboracion: regla opcional (F3) que puede levantar el veto de
            identificador ante evidencia fuerte. Por defecto inactiva.
    """

    campos: list[CampoSpec]
    umbral_score: float = 0.65
    min_concordancias: int = 2
    nombre: str = "esquema"
    corroboracion: CorroboracionVeto = field(default_factory=CorroboracionVeto)

    def __post_init__(self) -> None:
        if not self.campos:
            raise ValueError("EsquemaCampos requiere al menos un campo.")
        nombres = [c.nombre for c in self.campos]
        if len(nombres) != len(set(nombres)):
            duplicados = sorted({n for n in nombres if nombres.count(n) > 1})
            raise ValueError(f"Campos duplicados en el esquema: {duplicados}.")
        if not (0.0 < self.umbral_score <= 1.0):
            raise ValueError(f"umbral_score={self.umbral_score} fuera de (0, 1].")
        if not (1 <= self.min_concordancias <= len(self.campos)):
            raise ValueError(
                f"min_concordancias={self.min_concordancias} inválido para "
                f"{len(self.campos)} campos."
            )
        # F3: los campos corroborantes deben existir y no ser el identificador.
        if self.corroboracion.activa:
            nombres_set = set(nombres)
            ids = {c.nombre for c in self.campos if c.tipo is TipoCampo.IDENTIFICADOR}
            for cc in self.corroboracion.campos_corroborantes:
                if cc not in nombres_set:
                    raise ValueError(f"Campo corroborante '{cc}' no existe en el esquema.")
                if cc in ids:
                    raise ValueError(
                        f"Campo corroborante '{cc}' no puede ser el identificador "
                        f"vetado (sería circular)."
                    )

    @property
    def columnas_requeridas(self) -> list[str]:
        """Todas las columnas que el DataFrame debe tener."""
        cols: list[str] = []
        for c in self.campos:
            cols.extend(c.columnas)
        return cols

    def validar(self, df: pd.DataFrame) -> None:
        """Preflight accionable del esquema contra un DataFrame (F1.4-style)."""
        faltan = [c for c in self.columnas_requeridas if c not in df.columns]
        if faltan:
            raise ValueError(
                f"Qué pasó: al DataFrame le faltan las columnas {faltan} que "
                f"declara el esquema '{self.nombre}' "
                f"(tiene: {list(df.columns)}). "
                f"Por qué importa: sin ellas el motor no puede comparar esos "
                f"campos. Qué hacer: renombre las columnas o ajuste los "
                f"CampoSpec(nombre=...) del esquema."
            )


def esquema_rues(
    *,
    col_nit: str = "NIT",
    col_nombre: str = "RAZON_SOCIAL",
    col_ciudad: str | None = "CIUDAD",
) -> EsquemaCampos:
    """Preset RUES (F2.8): NIT + RAZON_SOCIAL (+CIUDAD) sobre el motor nuevo.

    Contrato de paridad permanente: la ruta de producción RUES sigue siendo
    ``dedupe()``/``deduplicate_auto`` con su baseline 16/16 intacto; este
    preset existe para correr datos tipo-RUES en el motor multicampo y
    compararlos — la migración, si procede, se decide con medición en F3.
    """
    campos = [
        CampoSpec(nombre=col_nit, tipo=TipoCampo.IDENTIFICADOR, peso=3.0),
        CampoSpec(nombre=col_nombre, tipo=TipoCampo.NOMBRE_EMPRESA, peso=2.0),
    ]
    if col_ciudad:
        campos.append(
            CampoSpec(
                nombre=col_ciudad,
                tipo=TipoCampo.CIUDAD,
                peso=0.5,
                faltante=PoliticaFaltante.IGNORAR,
            )
        )
    return EsquemaCampos(campos=campos, umbral_score=0.60, min_concordancias=1, nombre="rues")


def esquema_multicampo_completo(
    *,
    umbral_score: float = 0.60,
    min_concordancias: int = 3,
) -> EsquemaCampos:
    """Preset multicampo de referencia (F2.8): NIT + nombre + contacto + dirección.

    Calibrado y MEDIDO sobre el GT sintético v3 (``testing.gt_multicampo``,
    seed=42) con bloqueo por llaves exactas + LSH de nombre y
    ``clusters_desde_decisiones(respetar_vetos=True)``: F1 = 0.937
    (P = 1.000, R = 0.881), PC de bloqueo 0.993, cero controles negativos
    mal fusionados. Los defaults reproducen ese punto; ajústelos con
    medición sobre SU dataset.

    Nota medida (no opinada): el tipo GEO existe y funciona, pero AÑADIRLO a
    este esquema BAJÓ la precisión sobre el GT v3 (dos sedes distintas de la
    misma ciudad quedan cerca y elevan falsos positivos): F1 0.937 → 0.886.
    Por eso el preset no incluye GEO; úselo cuando la geolocalización
    distinga entidades (p. ej. domicilios residenciales), no sedes urbanas.

    Requiere columnas: NIT, RAZON_SOCIAL, TELEFONO, EMAIL, DIRECCION, CIUDAD.
    Quite los campos que no tenga (el motor renormaliza los pesos).
    """
    return EsquemaCampos(
        campos=[
            CampoSpec("NIT", TipoCampo.IDENTIFICADOR, peso=3.0),
            CampoSpec("RAZON_SOCIAL", TipoCampo.NOMBRE_EMPRESA, peso=2.0),
            CampoSpec("TELEFONO", TipoCampo.TELEFONO, peso=1.5),
            CampoSpec("EMAIL", TipoCampo.EMAIL, peso=1.5),
            CampoSpec("DIRECCION", TipoCampo.DIRECCION, peso=1.0),
            CampoSpec("CIUDAD", TipoCampo.CIUDAD, peso=0.5),
        ],
        umbral_score=umbral_score,
        min_concordancias=min_concordancias,
        nombre="multicampo_completo",
    )
