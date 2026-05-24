"""Enriquece el ground truth exhaustivo (1456 regs) con una columna CIUDAD.

MOTIVACIÓN
----------
El ground truth exhaustivo solo tiene ``NIT, RAZON_SOCIAL, ID_GROUP``. No
contiene variables adicionales, así que el efecto de ``extra_features``
(introducido en v2.7.0) NO es medible sobre él. Este script genera una versión
enriquecida ``golden_truth_exhaustivo_ciudad.csv`` añadiendo una columna
``CIUDAD`` **determinista** que respeta la verdad del dataset:

- **Coherencia intra-grupo:** todas las variantes de una misma empresa
  verdadera (mismo ``ID_GROUP``) reciben la MISMA ciudad. Esto refleja que
  una empresa real está en una ciudad; sus duplicados también.
- **Divergencia en negativos:** la ciudad se deriva del ``ID_GROUP`` (no del
  NIT), de modo que dos grupos DISTINTOS con NITs adyacentes —los casos
  negativos diseñados que el sistema sobre-fusiona— caen en ciudades
  distintas con alta probabilidad. Es exactamente la señal que una variable
  adicional firmada puede explotar para separarlos.
- **Realismo con ruido:** un 12 % de las filas recibe ciudad vacía (datos
  faltantes, como en el RUES real) para que el test no asuma cobertura
  perfecta. El tipo ``categorical_signed`` trata el nulo como neutral, así
  que el ruido no penaliza injustamente.

IMPORTANTE — honestidad metodológica
------------------------------------
Esta ciudad es SINTÉTICA y favorable al feature por construcción (se asigna
por grupo verdadero). Mide el TECHO del beneficio, no el caso real, donde la
ciudad tendría ruido propio y a veces coincidiría entre empresas distintas.
Sirve para: (1) demostrar que el cableado end-to-end mueve la métrica a
escala, (2) dar un dataset replicable. NO sustituye al ground truth real con
ciudades reales que pide P0-2 del ROADMAP.

El dataset es DETERMINISTA (sin aleatoriedad de runtime; deriva todo del
ID_GROUP y el índice). Se puede regenerar idénticamente.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

# Catálogo de ciudades colombianas (las más pobladas + algunas intermedias).
# El índice de ciudad se deriva del ID_GROUP, así cada grupo verdadero tiene
# una ciudad estable y grupos vecinos tienden a diferir.
_CIUDADES: tuple[str, ...] = (
    "BOGOTA",
    "MEDELLIN",
    "CALI",
    "BARRANQUILLA",
    "CARTAGENA",
    "BUCARAMANGA",
    "PEREIRA",
    "MANIZALES",
    "CUCUTA",
    "IBAGUE",
    "VILLAVICENCIO",
    "SANTA MARTA",
    "PASTO",
    "MONTERIA",
    "NEIVA",
    "ARMENIA",
    "POPAYAN",
    "VALLEDUPAR",
    "SINCELEJO",
    "TUNJA",
)

# Multiplicador primo para dispersar ID_GROUP sobre el catálogo de ciudades:
# evita que grupos consecutivos (los negativos suelen ser adyacentes) caigan
# en la misma ciudad. 7 es coprimo con 20 → recorre todo el catálogo.
_DISPERSION = 7
# 1 de cada N filas recibe ciudad vacía (simula datos faltantes del RUES).
_NULL_EVERY = 8  # ≈12.5 % de nulos


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Añade columna CIUDAD determinista al ground truth.

    Args:
        df: DataFrame con al menos ``ID_GROUP``. El orden de filas se respeta.

    Returns:
        Copia del DataFrame con una columna ``CIUDAD`` añadida.

    Raises:
        ValueError: si falta la columna ``ID_GROUP``.
    """
    if "ID_GROUP" not in df.columns:
        raise ValueError("El DataFrame debe contener la columna 'ID_GROUP'.")

    out = df.copy().reset_index(drop=True)
    group_codes = pd.factorize(out["ID_GROUP"])[0]
    city_idx = (group_codes * _DISPERSION) % len(_CIUDADES)
    ciudades = [_CIUDADES[i] for i in city_idx]

    # Inyectar nulos deterministas por posición de fila.
    ciudades = [
        "" if (pos % _NULL_EVERY == _NULL_EVERY - 1) else c for pos, c in enumerate(ciudades)
    ]
    out["CIUDAD"] = ciudades
    return out


def main() -> None:
    """Lee el exhaustivo, lo enriquece y guarda la versión con CIUDAD."""
    data_dir = Path(__file__).resolve().parent.parent / "tests" / "data"
    src = data_dir / "golden_truth_exhaustivo.csv"
    dst = data_dir / "golden_truth_exhaustivo_ciudad.csv"

    if not src.exists():
        raise FileNotFoundError(f"No se encontró el ground truth base: {src}")

    df = pd.read_csv(src, dtype={"NIT": str})
    enriched = enrich(df)
    enriched.to_csv(dst, index=False)

    n_null = (enriched["CIUDAD"] == "").sum()
    print(f"Enriquecido: {len(enriched)} registros, {enriched['ID_GROUP'].nunique()} grupos.")
    print(
        f"Ciudades distintas: {enriched['CIUDAD'].nunique()} · nulos: {n_null} "
        f"({n_null / len(enriched):.1%})."
    )
    print(f"Guardado en: {dst}")


if __name__ == "__main__":
    main()
