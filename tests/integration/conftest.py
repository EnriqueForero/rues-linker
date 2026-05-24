"""Fixtures compartidas para tests de integración.

Diseño:
    - DataFrames pequeños (≤50 filas) con duplicados *conocidos* y matches
      *cross-source* sembrados intencionalmente.
    - Semilla fija (RNG_SEED) para reproducibilidad.
    - Cada fixture incluye, en su docstring, el ground truth esperado.
"""

from __future__ import annotations

import pandas as pd
import pytest

RNG_SEED = 42


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures de datos sintéticos pequeños
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def df_single_source_with_duplicates() -> pd.DataFrame:
    """DataFrame de una sola fuente con 3 duplicados sembrados.

    Ground truth:
        - Filas 0, 1: mismo NIT '900123456', razón social ligeramente
          distinta (mayúsculas + SAS vs S.A.S.) → DEBEN agruparse.
        - Filas 2, 3: mismo NIT '800999111', razón social idéntica
          → DEBEN agruparse.
        - Filas 4-7: NITs únicos → 4 grupos distintos.
        - Total: 8 registros, 6 grupos finales.
    """
    return pd.DataFrame(
        {
            "NIT": [
                "900123456",
                "900123456",
                "800999111",
                "800999111",
                "700555222",
                "600444333",
                "500333111",
                "400222999",
            ],
            "RAZON_SOCIAL": [
                "ACME COLOMBIA SAS",
                "ACME COLOMBIA S.A.S.",
                "INVERSIONES BETA LTDA",
                "INVERSIONES BETA LTDA",
                "GAMMA INDUSTRIES SAS",
                "DELTA EXPORTS COLOMBIA",
                "EPSILON LOGISTICS",
                "ZETA TRADING CO",
            ],
        }
    )


@pytest.fixture
def df_two_sources_with_cross_matches() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Dos DataFrames con 3 NITs en común (matches cross-source esperados).

    Ground truth:
        - source_a: 5 registros, NITs únicos {900,800,700,600,500}.
        - source_b: 5 registros, NITs únicos {900,800,700,400,300}.
        - Intersección: {900,800,700} → 3 matches cross-source esperados.
    """
    source_a = pd.DataFrame(
        {
            "NIT": ["900111111", "800222222", "700333333", "600444444", "500555555"],
            "RAZON_SOCIAL": [
                "ALPHA TECH SAS",
                "BETA SOLUTIONS LTDA",
                "GAMMA EXPORTS SA",
                "DELTA LOGISTICS",
                "EPSILON TRADING",
            ],
            "SRC": ["SOURCE_A"] * 5,
        }
    )
    source_b = pd.DataFrame(
        {
            "NIT": ["900111111", "800222222", "700333333", "400666666", "300777777"],
            "RAZON_SOCIAL": [
                "ALPHA TECH S.A.S.",  # match con A0
                "BETA SOLUTIONS",  # match con A1
                "GAMMA EXPORTS S.A.",  # match con A2
                "ZETA COMMERCE",
                "OMEGA HOLDINGS",
            ],
            "SRC": ["SOURCE_B"] * 5,
        }
    )
    return source_a, source_b


@pytest.fixture
def df_empty() -> pd.DataFrame:
    """DataFrame vacío para validar manejo de error explícito."""
    return pd.DataFrame(columns=["NIT", "RAZON_SOCIAL"])
