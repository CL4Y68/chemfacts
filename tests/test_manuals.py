"""Offline tests for the manual-entry registry (substances PubChem does not carry)."""

from __future__ import annotations

import json

import pytest

from chemfacts import ManualRegistry, new_entry


@pytest.fixture()
def reg(tmp_path, monkeypatch):
    path = tmp_path / "manuals.json"
    monkeypatch.setenv("CHEMFACTS_MANUALS", str(path))
    return ManualRegistry()


def test_add_get_list_remove(reg):
    e = new_entry(
        "PTMG-2000",
        name_en="Polytetramethylene glycol (PTMEG-2000)",
        cas="25268-40-0",
        mw="2000 (COA)",
        note="supplier COA, lot 2026-08",
    )
    reg.add(e)
    got = reg.get("ptmg-2000")
    assert got is not None and got.name_en.startswith("Polytetramethylene")
    assert got.mw == "2000 (COA)"
    assert [x.identifier for x in reg.list()] == ["PTMG-2000"]
    assert reg.remove("PTMG-2000")
    assert reg.get("PTMG-2000") is None
    assert not reg.remove("PTMG-2000")


def test_by_cas(reg):
    reg.add(new_entry("PTMG-2000", cas="25268-40-0"))
    e = reg.by_cas("25268-40-0")
    assert e is not None and e.identifier == "PTMG-2000"
    assert reg.by_cas("999-99-9") is None
    # an entry without a CAS is never matched by CAS
    reg.add(new_entry("MIX_A", name_en="some blend"))
    assert reg.by_cas("111-11-1") is None


def test_registry_persists_utf8(reg):
    reg.add(new_entry("TDI_8020", name_en="Toluene diisocyanate 80/20", mw="~251 (blend)"))
    raw = json.loads(reg.path.read_text(encoding="utf-8"))
    assert raw["TDI_8020"]["name_en"] == "Toluene diisocyanate 80/20"
    again = ManualRegistry()
    assert again.get("tdi_8020").mw == "~251 (blend)"


def test_missing_is_missing_not_guessed(reg):
    """fail-closed: a label with no entry yields nothing, never a default value."""
    assert reg.get("never-recorded") is None
    assert reg.by_cas("100-00-0") is None
