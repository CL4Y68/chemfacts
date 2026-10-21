"""Offline tests for the abbreviation registry (no network, no user files)."""

from __future__ import annotations

import json

import pytest

from chemfacts import AliasRegistry
from chemfacts.cache import FactCache
from chemfacts.core import ChemFacts, card_to_markdown
from tests.test_core import FakePubChem


@pytest.fixture()
def reg(tmp_path, monkeypatch):
    path = tmp_path / "aliases.json"
    monkeypatch.setenv("CHEMFACTS_ALIASES", str(path))
    return AliasRegistry()


def test_add_get_list_remove(reg):
    reg.add("DMPA", "4767-03-7", note="dimethylolpropionic acid, not dimethylpiperazine")
    e = reg.get("dmpa")  # case-insensitive
    assert e is not None and e.identifier == "4767-03-7"
    assert "dimethylpiperazine" in e.note
    assert [x.alias for x in reg.list()] == ["DMPA"]
    assert reg.remove("DMPA")
    assert reg.get("DMPA") is None
    assert not reg.remove("DMPA")


def test_registry_persists_to_json(reg):
    reg.add("IBOA", "5888-33-5", "isobornyl acrylate C13H20O2")
    raw = json.loads(reg.path.read_text(encoding="utf-8"))
    assert raw["IBOA"]["identifier"] == "5888-33-5"
    # a fresh instance on the same file sees it
    again = AliasRegistry()
    assert again.get("iboa").identifier == "5888-33-5"


def test_pin_passthrough_for_unknown(reg):
    assert reg.pin("872-50-4") == "872-50-4"
    reg.add("NMP", "872-50-4")
    assert reg.pin("nmp") == "872-50-4"


def test_aliases_for_reverse(reg):
    """compound -> registered abbreviations (the direction 'what is it called')."""
    reg.add("THF", "109-99-9", "tetrahydrofuran (solvent)")
    reg.add("THF-d8", "109-99-9", "deuterated")
    reg.add("NMP", "872-50-4")
    assert [e.alias for e in reg.aliases_for("109-99-9")] == ["THF", "THF-D8"]
    assert [e.alias for e in reg.aliases_for("872-50-4")] == ["NMP"]
    assert reg.aliases_for("000-00-0") == []


@pytest.fixture()
def alias_facts(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEMFACTS_ALIASES", str(tmp_path / "a.json"))
    fake = FakePubChem()
    f = ChemFacts(client=fake, cache=FactCache(str(tmp_path / "f.db")))
    f.aliases.add("XNMP", "13387", note="test pin")
    return f


def test_alias_pins_to_pinned_identifier(alias_facts):
    ident = alias_facts.resolve("XNMP")
    assert ident.cid == 13387
    assert ident.name == "N-Methyl-2-pyrrolidone"
    # audit trail: the original input stays visible
    assert ident.identifier == "XNMP"


def test_alias_card_records_pin(alias_facts):
    card = alias_facts.build_card("XNMP")
    assert "XNMP" in card.aliases
    assert any("XNMP -> 13387" in n for n in card.notes)
    md = card_to_markdown(card, obsidian=True)
    assert '"XNMP"' in md  # frontmatter aliases line


def test_non_alias_path_unchanged(alias_facts):
    ident = alias_facts.resolve("NMP")
    assert ident.cid == 13387
    card = alias_facts.build_card("NMP")
    assert card.aliases == []
