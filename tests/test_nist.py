"""Offline tests for the NIST WebBook client (fixture HTML, no network)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from chemfacts.cache import FactCache
from chemfacts.core import ChemFacts, _heading, _to_celsius
from chemfacts.model import PropertyValue
from chemfacts.nist import NistClient, NistError
from tests.test_core import FakeNist, FakePubChem

# Minimal WebBook-style page: Tboil (AVG row), two Tfus measurements,
# and a two-dimensional enthalpy-of-vaporization table.
FIXTURE_PAGE = """
<html><body>
<div id="Thermo-Phase">
<h3>Phase change data</h3>
<table class="data" aria-label="One dimensional data">
<tr><th scope="col">Quantity</th><th scope="col">Value</th><th scope="col">Units</th>
<th scope="col">Method</th><th scope="col">Reference</th><th scope="col">Comment</th></tr>
<tr class="cal"><td>T<sub>boil</sub></td><td class="right-nowrap">339. &plusmn; 1.</td>
<td>K</td><td>AVG</td><td>N/A</td><td>Average of 16 out of 17 values</td></tr>
<tr class="exp"><td>T<sub>fus</sub></td><td class="right-nowrap">165.1</td><td>K</td>
<td>N/A</td><td><a href="#ref-1">Hayduk, Laudie, et al., 1973</a></td><td>TRC</td></tr>
<tr class="exp"><td>T<sub>fus</sub></td><td class="right-nowrap">164.15</td><td>K</td>
<td>N/A</td><td><a href="#ref-2">Brooks and Pilcher, 1959</a></td><td>TRC</td></tr>
</table>
<h3>Enthalpy of vaporization</h3>
<table class="data" aria-label="Enthalpy of vaporization">
<tr><th scope="col">&#916;<sub>vap</sub>H (kJ/mol)</th><th scope="col">Temperature (K)</th>
<th scope="col">Method</th><th scope="col">Reference</th><th scope="col">Comment</th></tr>
<tr class="exp"><td>29.81</td><td>339.1</td><td>N/A</td>
<td><a href="#ref-8">Majer and Svoboda, 1985</a></td><td>&nbsp;</td></tr>
</table>
<h3>Enthalpy of vaporization (coefficients)</h3>
<table class="data" aria-label="Enthalpy of vaporization">
<tr><th scope="col">Temperature (K)</th><th scope="col">Value</th><th scope="col">Method</th>
<th scope="col">Reference</th><th scope="col">Comment</th></tr>
<tr class="exp"><td>302. to 339.</td><td>46.11</td><td>0.2699</td>
<td>540.2</td><td><a href="#ref-8">Majer and Svoboda, 1985</a></td></tr>
<tr class="exp"><td>296.29 to 372.8</td><td>4.12118</td><td>1202.942</td>
<td>-46.818</td><td><a href="#ref-9">Scott D.W., 1970</a></td></tr>
</table>
</div>
<div id="Refs">references</div>
</body></html>
"""


class FakeSession:
    """Duck-typed requests.Session returning canned HTML."""

    def __init__(self, text: str = FIXTURE_PAGE, raise_error: bool = False):
        self.headers = {}
        self.text = text
        self.raise_error = raise_error
        self.last_url = None

    def get(self, url, params=None, timeout=None):
        self.last_url = url
        if self.raise_error:
            raise requests.ConnectionError("offline")
        return SimpleNamespace(status_code=200, text=self.text)


def client(page: str = FIXTURE_PAGE, raise_error: bool = False) -> NistClient:
    c = NistClient(session=FakeSession(page, raise_error))
    c.session.min_interval = 0  # type: ignore[assignment]
    c.min_interval = 0
    return c


# -- identification ---------------------------------------------------------

def test_nist_id_normalization():
    c = client()
    assert c._nist_id("109-99-9") == "C109999"
    assert c._nist_id("872-50-4") == "C872504"
    assert c._nist_id("NMP") is None
    assert c._nist_id("109-99-999") is None


# -- parsing ----------------------------------------------------------------

def test_parse_boiling_melting_and_dhvap():
    c = client()
    rows = c.phase_change_rows("109-99-9", "Boiling Point")
    assert [r.value for r in rows] == ["339. ± 1. K"]
    assert rows[0].source_name == "NIST WebBook (TRC average of experimental values)"
    assert rows[0].kind == "experimental"
    assert rows[0].url and "ID=C109999" in rows[0].url

    fus = c.phase_change_rows("109-99-9", "Melting Point")
    assert [r.value for r in fus] == ["165.1 K", "164.15 K"]
    assert fus[0].source_name == "NIST WebBook (Hayduk, Laudie, et al., 1973)"
    assert fus[1].source_name == "NIST WebBook (Brooks and Pilcher, 1959)"

    dhvap = c.phase_change_rows("109-99-9", "Enthalpy of Vaporization")
    assert [r.value for r in dhvap] == ["29.81 kJ/mol at 339.1 K"]
    assert dhvap[0].source_name == "NIST WebBook (Majer and Svoboda, 1985)"


def test_missing_section_returns_empty():
    c = client(page="<html><body><div id='Other'></div></body></html>")
    assert c.phase_change_rows("109-99-9", "Boiling Point") == []


def test_bad_cas_returns_empty_without_fetching():
    sess = FakeSession()
    c = NistClient(session=sess)
    c.min_interval = 0
    assert c.phase_change_rows("not-a-cas", "Boiling Point") == []
    assert sess.last_url is None  # no network access attempted


def test_transport_failure_raises_nist_error():
    c = client(raise_error=True)
    with pytest.raises(NistError):
        c.phase_change_rows("109-99-9", "Boiling Point")


# -- kelvin normalisation ---------------------------------------------------

def test_kelvin_conversion():
    assert _to_celsius("339. ± 1. K", "Boiling Point") == pytest.approx(65.85)
    assert _to_celsius("165.1 K", "Melting Point") == pytest.approx(-108.05)
    # no K marker -> untouched
    assert _to_celsius("66 °C (Kirk-Othmer)", "Boiling Point") == 66.0
    assert _to_celsius("202 °C at 760 mm Hg", "Boiling Point") == 202.0


def test_kelvin_not_applied_to_non_temperature():
    assert _to_celsius("29.81 kJ/mol at 339.1 K", "Enthalpy of Vaporization") == 29.81


# -- integration with lookup / crosscheck ----------------------------------

@pytest.fixture()
def merged_facts(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEMFACTS_ALIASES", str(tmp_path / "aliases.json"))
    nist_rows = {
        ("872-50-4", "Boiling Point"): [
            PropertyValue("Boiling Point", "475.15 K", 0, "NIST WebBook (Fixture, 2001)")
        ]
    }
    f = ChemFacts(
        client=FakePubChem(),
        cache=FactCache(str(tmp_path / "m.db")),
        nist=FakeNist(rows=nist_rows),
    )
    return f


def test_lookup_merges_nist_rows(merged_facts):
    values = merged_facts.lookup("NMP", "boiling-point")
    sources = [v.source_name for v in values]
    assert any(s.startswith("HSDB") for s in sources)      # PubChem row
    assert "NIST WebBook (Fixture, 2001)" in sources       # NIST row
    assert len(values) == 2


def test_crosscheck_two_independent_sources_verified(merged_facts):
    # PubChem: 202 °C ; NIST: 475.15 K == 202.0 °C  -> agreement
    values, status = merged_facts.crosscheck("NMP", "boiling-point")
    assert status == "verified"
    assert len(values) == 2


def test_nist_unavailable_keeps_pubchem_only(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEMFACTS_ALIASES", str(tmp_path / "aliases.json"))
    f = ChemFacts(
        client=FakePubChem(),
        cache=FactCache(str(tmp_path / "u.db")),
        nist=FakeNist(fail=True),
    )
    values = f.lookup("NMP", "boiling-point")
    assert [v.source_name for v in values] == ["HSDB"]  # graceful fallback


def test_stale_cache_backfills_nist_rows(tmp_path, monkeypatch):
    """A cache written before the NIST source must gain NIST rows on next hit."""
    monkeypatch.setenv("CHEMFACTS_ALIASES", str(tmp_path / "aliases.json"))
    cache = FactCache(str(tmp_path / "b.db"))
    pubchem_only = ChemFacts(client=FakePubChem(), cache=cache, nist=FakeNist())
    first = pubchem_only.lookup("NMP", "boiling-point")  # warms cache, no NIST
    assert all(v.source_name.startswith("HSDB") for v in first)

    # second facade over the SAME cache, but now with NIST rows available
    nist_rows = {
        ("872-50-4", "Boiling Point"): [
            PropertyValue("Boiling Point", "475.15 K", 0, "NIST WebBook (Fixture, 2001)")
        ]
    }
    f2 = ChemFacts(
        client=FakePubChem(), cache=cache, nist=FakeNist(rows=nist_rows)
    )
    second = f2.lookup("NMP", "boiling-point")
    sources = [v.source_name for v in second]
    assert any(s.startswith("NIST WebBook") for s in sources), "backfill missing"


def test_vaporization_slug_maps_to_heading():
    assert _heading("vaporization-enthalpy") == "Enthalpy of Vaporization"
    assert _heading("dhvap") == "Enthalpy of Vaporization"
