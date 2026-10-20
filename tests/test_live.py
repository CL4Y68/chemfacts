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
