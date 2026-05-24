"""Tests del helper de alto nivel `linkage()` y de la API pública (v3.0.0)."""

from __future__ import annotations

import pandas as pd

import record_linkage
from record_linkage import linkage


def test_api_publica_exporta_simbolos_clave():
    """El namespace raíz debe exponer la API de alto nivel."""
    for nombre in ("linkage", "Orchestrator", "deduplicate_unified", "evaluar_pares"):
        assert hasattr(record_linkage, nombre), f"Falta {nombre} en la API pública"
    assert "linkage" in record_linkage.__all__


def test_linkage_una_fuente_dedup_interna(tmp_path):
    """linkage() sobre una sola fuente deduplica registros de la misma entidad."""
    df = pd.DataFrame(
        {
            "NIT": ["900123456", "900123456", "800555111"],
            "RAZON_SOCIAL": ["ACME COLOMBIA SAS", "ACME COLOMBIA S.A.S.", "GLOBEX LTDA"],
            "CIUDAD": ["BOGOTA", "BOGOTA", "MEDELLIN"],
        }
    )
    res = linkage(sources={"RUES": df}, work_dir=str(tmp_path / "run"))
    assert "golden" in res
    assert "correlative" in res
    # Las dos ACME (mismo NIT) deben colapsar: 3 registros -> 2 entidades.
    assert len(res["golden"]) == 2


def test_linkage_requiere_fuentes():
    """linkage() sin fuentes debe fallar claramente."""
    import pytest

    with pytest.raises(ValueError, match="al menos una fuente"):
        linkage(sources={})


def test_linkage_crea_work_dir_temporal_si_no_se_da():
    """Si no se pasa work_dir, linkage() usa un temporal y no rompe."""
    df = pd.DataFrame({"NIT": ["900123456"], "RAZON_SOCIAL": ["ACME SAS"], "CIUDAD": ["BOGOTA"]})
    res = linkage(sources={"RUES": df})
    assert "golden" in res
