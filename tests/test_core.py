"""Offline tests: fake PubChem client + real SQLite cache. No network needed."""

from __future__ import annotations

import pytest

from chemfacts.cache import FactCache
from chemfacts.core import ChemFacts, card_to_json, card_to_markdown
from chemfacts.model import CompoundIdentity, PropertyValue
from chemfacts.pubchem import PubChemClient, PubChemError


class FakePubChem:
    """Stands in for PubChemClient with fixture data (IPDI + NMP)."""

    def __init__(self):
        self.calls: list[str] = []

    def _get_json(self, url, params=None):
        raise PubChemError("no network in fake")

    def identity(self, identifier):
        self.calls.append(f"identity:{identifier}")
        if "nmp" in identifier.lower() or identifier == "13387":
            return CompoundIdentity(
                identifier=identifier, cid=13387, name="N-Methyl-2-pyrrolidone",
                iupac_name="1-methylpyrrolidin-2-one", cas="872-50-4",
                formula="C5H9NO", molecular_weight=99.13,
                canonical_smiles="CN1CCCC1=O", inchi_key="XJTMZKTFBROXJF-UHFFFAOYSA-N",
            )
        if "ipdi" in identifier.lower() or identifier == "169132":
            return CompoundIdentity(
                identifier=identifier, cid=169132, name="Isophorone diisocyanate",
                iupac_name="5-isocyanato-1-(isocyanatomethyl)-1,3,3-trimethylcyclohexane",
                cas="5841-80-4", formula="C12H18N2O2", molecular_weight=222.28,
                canonical_smiles="CC1(CCC(CCC1(N=C=O)N=C=O)(C)C)C",
            )
        raise PubChemError(f"unknown identifier {identifier}")

    def property_values(self, cid, heading):
        self.calls.append(f"props:{cid}:{heading}")
        if cid == 169132 and heading == "Flash Point":
            return [
                PropertyValue("Flash Point", "155 °C, Closed cup", 30, "HSDB", "experimental"),
                PropertyValue("Flash Point", "155 °C c.c.", 32, "ILO ICSC", "experimental"),
            ]
        if cid == 13387 and heading == "Flash Point":
            return [
                PropertyValue("Flash Point", "96 °C", 46, "HSDB", "experimental"),
                PropertyValue(
                    "Flash Point", "204 °F (96 °C) (OPEN CUP)", 46, "HSDB", "experimental"
                ),
            ]
        if cid == 13387 and heading == "Boiling Point":
            return [
                PropertyValue("Boiling Point", "202 °C at 760 mm Hg", 46, "HSDB", "experimental"),
            ]
        return []

    def _reference_map(self, cid, data):
        return {}


@pytest.fixture()
def facts(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEMFACTS_ALIASES", str(tmp_path / "aliases.json"))
    fake = FakePubChem()
    cache = FactCache(str(tmp_path / "facts.db"))
    yield ChemFacts(client=fake, cache=cache)


# -- identity -------------------------------------------------------------

def test_resolve_returns_identity(facts):
    ident = facts.resolve("IPDI")
    assert ident.cid == 169132
    assert ident.formula == "C12H18N2O2"
    assert ident.molecular_weight == 222.28
    assert ident.cas == "5841-80-4"


def test_resolve_cached_second_time_no_network(facts):
    facts.resolve("NMP")
    n_calls = len(facts.client.calls)
    ident2 = facts.resolve("NMP")
    assert len(facts.client.calls) == n_calls  # served from cache
    assert ident2.cid == 13387


def test_classify_identifiers():
    c = PubChemClient._classify
    assert c("13387") == ("cid", "13387")
    assert c("872-50-4") == ("cas", "872-50-4")
    assert c("CN1CCCC1=O") == ("smiles", "CN1CCCC1=O")
    inchi = "INCHI=1S/C5H9NO/c1-4-5-6-2-3-4/h2H3,1H"
    assert c(inchi) == ("inchi", inchi)
    assert c("NMP") == ("name", "NMP")


# -- lookup / cache --------------------------------------------------------

def test_lookup_flash_point(facts):
    vals = facts.lookup("IPDI", "flash-point")
    assert len(vals) == 2
    assert {v.value for v in vals} == {"155 °C, Closed cup", "155 °C c.c."}
    assert all(v.source_name for v in vals)


def test_lookup_mw_special_case(facts):
    vals = facts.lookup("NMP", "mw")
    assert vals and vals[0].value == "99.13 g/mol"
    assert vals[0].kind == "computed"


def test_lookup_missing_property_returns_empty(facts):
    assert facts.lookup("NMP", "density") == []


def test_cache_persists_values(facts, tmp_path):
    facts.lookup("IPDI", "flash-point")
    fresh_cache = FactCache(str(tmp_path / "facts2.db"))
    assert not fresh_cache.get_values(169132, "Flash Point")
    # copy the db into a second path via sqlite
    import shutil
    shutil.copy(tmp_path / "facts.db", tmp_path / "facts2.db")
    fresh_cache2 = FactCache(str(tmp_path / "facts2.db"))
    got = fresh_cache2.get_values(169132, "Flash Point")
    assert {v.value for v in got} == {"155 °C, Closed cup", "155 °C c.c."}


# -- crosscheck ------------------------------------------------------------

def test_crosscheck_agreement(facts):
    vals, status = facts.crosscheck("IPDI", "flash-point")
    assert status == "verified"  # 155 C closed cup from two sources
    assert len(vals) == 2


def test_crosscheck_missing_is_unverified(facts):
    vals, status = facts.crosscheck("NMP", "density")
    assert vals == [] and status == "unverified"


# -- verify (the point of the project) --------------------------------------

def test_verify_confirmed(facts):
    res = facts.verify("IPDI", "flash-point", "155")
    assert res.verdict == "confirmed"
    assert len(res.matches) >= 1


def test_verify_mismatch_returns_closest(facts):
    res = facts.verify("IPDI", "flash-point", "200")
    assert res.verdict == "mismatch"
    assert res.closest is not None
    assert "155" in res.closest.value
    assert "HSDB" in res.detail or "ILO" in res.detail


def test_verify_mw_confirmed(facts):
    res = facts.verify("NMP", "mw", "99.13")
    assert res.verdict == "confirmed"


def test_verify_mw_mismatch(facts):
    res = facts.verify("NMP", "mw", "110.00")
    assert res.verdict == "mismatch"
    assert res.closest is not None and res.closest.value == "99.13 g/mol"


def test_verify_not_found_property(facts):
    res = facts.verify("NMP", "density", "1.03")
    assert res.verdict == "not_found"
    assert not res.found


# -- card rendering ----------------------------------------------------------

def test_card_markdown_has_provenance(facts):
    card = facts.build_card("IPDI")
    md = card_to_markdown(card, obsidian=True)
    assert md.startswith("---")
    assert "cas: 5841-80-4" in md
    assert "cid: 169132" in md
    assert "155 °C, Closed cup" in md
    assert "HSDB" in md
    assert "Flash Point" in md
    assert "status: " in md


def test_card_marks_missing_properties_honestly(facts):
    card = facts.build_card("IPDI")
    assert "no sourced value found for" in card_to_markdown(card, obsidian=True) or any(
        n.startswith("no sourced value") for n in card.notes
    )


def test_card_json_roundtrip(facts):
    card = facts.build_card("NMP")
    payload = card_to_json(card)
    assert '"identity"' in payload
    assert "13387" in payload


# -- cache admin --------------------------------------------------------------

def test_cache_clear(facts):
    facts.lookup("IPDI", "flash-point")
    n = facts.cache.clear()
    assert n > 0
    assert facts.cache.get_values(169132, "Flash Point") == []
