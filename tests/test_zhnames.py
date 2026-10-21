"""Offline tests for the Chinese-name curation registry (no network, no user files)."""

from __future__ import annotations

import json

import pytest

from chemfacts import ZhNameRegistry


@pytest.fixture()
def reg(tmp_path, monkeypatch):
    path = tmp_path / "zhnames.json"
    monkeypatch.setenv("CHEMFACTS_ZHNAMES", str(path))
    return ZhNameRegistry()


def test_add_get_list_remove(reg):
    reg.add("109-99-9", "四氢呋喃", source="lab SDS, manual check")
    e = reg.get("109-99-9")
    assert e is not None and e.name_zh == "四氢呋喃"
    assert e.source == "lab SDS, manual check"
    assert [x.identifier for x in reg.list()] == ["109-99-9"]
    assert reg.remove("109-99-9")
    assert reg.get("109-99-9") is None
    assert not reg.remove("109-99-9")


def test_registry_persists_utf8(reg):
    reg.add("872-50-4", "N-甲基吡咯烷酮")
    raw = json.loads(reg.path.read_text(encoding="utf-8"))
    assert raw["872-50-4"]["name_zh"] == "N-甲基吡咯烷酮"
    again = ZhNameRegistry()
    assert again.get("872-50-4").name_zh == "N-甲基吡咯烷酮"


def test_find_by_cas_then_cid(reg):
    reg.add("872-50-4", "N-甲基-2-吡咯烷酮")  # CAS key
    reg.add("13387", "CID-key 中文名")  # CID key
    assert reg.find("872-50-4", 13387).name_zh == "N-甲基-2-吡咯烷酮"  # CAS wins
    assert reg.find(None, 13387).name_zh == "CID-key 中文名"
    assert reg.find(None, None) is None


def test_missing_is_missing_not_guessed(reg):
    """fail-closed: an uncurated compound has no Chinese name, full stop."""
    assert reg.find("999-99-9", 424242) is None


def test_cli_zh_key_for_normalizes(tmp_path, monkeypatch):
    """`zhname add NMP ...` must key the entry on the CAS, not the raw input,
    so export/resolve lookups (which know CAS/CID, not the user's input word)
    actually hit the curation."""
    from chemfacts import cli
    from chemfacts.aliases import AliasRegistry
    from chemfacts.cache import FactCache
    from chemfacts.core import ChemFacts
    from tests.test_core import FakePubChem

    f = ChemFacts(
        client=FakePubChem(),
        cache=FactCache(str(tmp_path / "facts.db")),
        aliases=AliasRegistry(path=tmp_path / "aliases.json"),
    )
    f.aliases.add("NMP", "872-50-4", "offline test pin")
    monkeypatch.setattr(cli, "_facts", lambda: f)

    key, how = cli._zh_key_for("NMP")
    assert key == "872-50-4"
    assert "resolved" in how

    key2, how2 = cli._zh_key_for("872-50-4")
    assert key2 == "872-50-4" and how2 == "as-is"

    key3, how3 = cli._zh_key_for("13387")
    assert key3 == "13387" and how3 == "as-is"
