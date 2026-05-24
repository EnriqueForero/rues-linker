"""Calidad de linkage sobre el ground truth EXHAUSTIVO (v2.5.0).

Complementa test_quality_golden.py (269 registros) con un dataset mucho más
exigente: 1456 registros, 137 grupos, grupos de hasta 18 variantes, NITs con
errores deliberados (1-2 dígitos, transposición, dígito extra) y CASOS
NEGATIVOS (empresas de nombre similar pero distintas, para medir falsos
positivos). Ver `tests/data/golden_truth_exhaustivo.csv`.

Pisos de regresión:
    - v2.4.0: F1≈0.78, precision≈0.93, recall≈0.67.
    - v2.5.0: F1≈0.86, precision≈0.88, recall≈0.84 (tras P0-1 Paso 1.1:
      bloqueo por NIT base). El recall sube +0.17 a costa de bajar la
      precision 0.05 — neto positivo en F1 (+0.085). Trade-off documentado
      en CHANGELOG.

Igual que en el otro test de calidad: estos números NO son un certificado
de producción, son un piso que impide que la calidad RETROCEDA.
"""

from __future__ import annotations

import logging
import os
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pandas as pd
import pytest

from record_linkage.deduplication.unified import deduplicate_unified
from record_linkage.evaluation.pairwise import evaluar_pares

GOLDEN = Path(__file__).parent / "data" / "golden_truth_exhaustivo.csv"

# Pisos de regresión v2.5.0 (medidos: F1=0.863, P=0.886, R=0.842).
# Se dejan ~0.03 de margen para variabilidad en ejecución.
F1_MIN = 0.83
PRECISION_MIN = 0.85
RECALL_MIN = 0.80


@pytest.fixture(scope="module")
def metricas():
    """Corre el pipeline completo sobre el ground truth exhaustivo."""
    truth = pd.read_csv(GOLDEN, dtype={"NIT": str})
    truth["NIT"] = truth["NIT"].fillna("")
    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, "w") as dn, redirect_stdout(dn), redirect_stderr(dn):
            with tempfile.TemporaryDirectory() as tmp:
                correlativa, _ = deduplicate_unified(
                    df_input=truth[["NIT", "RAZON_SOCIAL"]].copy(),
                    col_nit="NIT",
                    col_name="RAZON_SOCIAL",
                    mode="BALANCEADO",
                    output_dir=tmp,
                )
    finally:
        logging.disable(logging.NOTSET)
    correlativa = correlativa.sort_values("ORIGINAL_INDEX").reset_index(drop=True)
    assert len(correlativa) == len(truth)
    return evaluar_pares(truth["ID_GROUP"].to_numpy(), correlativa["ID_GRUPO"].to_numpy())


def test_f1_no_retrocede(metricas) -> None:
    assert metricas.f1 >= F1_MIN, f"F1 {metricas.f1:.3f} < {F1_MIN}\n{metricas.resumen()}"


def test_precision_alta(metricas) -> None:
    """Con casos negativos en el dataset, la precision es la métrica clave."""
    assert metricas.precision >= PRECISION_MIN, (
        f"Precision {metricas.precision:.3f} < {PRECISION_MIN}: sobre-fusión "
        f"({metricas.fp} pares unidos indebidamente)."
    )


def test_recall_no_retrocede(metricas) -> None:
    assert metricas.recall >= RECALL_MIN, f"Recall {metricas.recall:.3f} < {RECALL_MIN}"


def test_reporte(metricas, capsys) -> None:
    print("\n" + metricas.resumen())
