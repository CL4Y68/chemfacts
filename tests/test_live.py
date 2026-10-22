"""Live tests against the real PubChem API. Deselected by default (-m "not live")."""

from __future__ import annotations

import pytest

from chemfacts import ChemFacts

pytestmark = pytest.mark.live


def test_live_resolve_nmp():
    f = ChemFacts()
    ident = f.resolve("NMP")
    assert ident.cid == 13387
    assert ident.molecular_weight == pytest.approx(99.13)


def test_live_flash_point_ipdi():
    f = ChemFacts()
    vals = f.lookup("IPDI", "flash-point")
    assert vals
    assert all(v.source_name for v in vals)


def test_live_verify_mw():
    f = ChemFacts()
    res = f.verify("NMP", "mw", "99.13")
    assert res.verdict == "confirmed"


def test_live_nist_second_source_boiling_point():
    """PubChem + NIST WebBook must both contribute to one property."""
    f = ChemFacts()
    values = f.lookup("THF", "boiling-point")
    assert values
    sources = [v.source_name for v in values]
    assert any(s.startswith("NIST WebBook") for s in sources), (
        "expected at least one NIST WebBook row for THF boiling point"
    )
    # two independent databases agreeing is the whole point
    _, status = f.crosscheck("THF", "boiling-point")
    assert status in ("verified", "conflict")


def test_live_nist_enthalpy_of_vaporization():
    f = ChemFacts()
    values = f.lookup("THF", "vaporization-enthalpy")
    assert values, "NIST WebBook should carry dHvap for THF"
    assert all(v.source_name.startswith("NIST WebBook") for v in values)
    assert all("kJ/mol" in v.value for v in values)
