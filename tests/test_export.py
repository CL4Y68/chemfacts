"""Offline tests for the export correspondence table (fake client, tmp registries)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from chemfacts import cli, core
from chemfacts.cache import FactCache
from tests.test_core import FakePubChem

runner = CliRunner()


@pytest.fixture()
def facts(tmp_path, monkeypatch):
    monkeypatch.setenv("CHEMFACTS_ALIASES", str(tmp_path / "aliases.json"))
    monkeypatch.setenv("CHEMFACTS_ZHNAMES", str(tmp_path / "zhnames.json"))
    monkeypatch.setenv("CHEMFACTS_MANUALS", str(tmp_path / "manuals.json"))
    fake = FakePubChem()
    f = core.ChemFacts(client=fake, cache=FactCache(str(tmp_path / "f.db")))
    # curation fixtures: one abbreviation pin + one Chinese-name curation per compound
    f.aliases.add("NMP", "872-50-4", note="solvent")
    f.aliases.add("THF", "109-99-9", note="solvent")
    f.zhnames.add("872-50-4", "N-甲基-2-吡咯烷酮", source="lab handbook")
    return f


def test_export_row_fields(facts):
    rows = core.export_rows(facts, ["NMP"])
    assert len(rows) == 1
    r = rows[0]
    assert r["name_en"] == "N-Methyl-2-pyrrolidone"
    assert r["cas"] == "872-50-4"
    assert r["cid"] == 13387
    assert r["formula"] == "C5H9NO"
    assert r["mw"] == "99.13 g/mol"
    assert "computed from formula" in r["mw_source"]
    assert r["abbrevs"] == ["NMP"]  # registry-pinned abbreviation comes back
    assert r["name_zh"] == "N-甲基-2-吡咯烷酮"
    assert r["name_zh_source"] == "lab handbook"
    # property cells with provenance
    assert "96 °C" in r["flash-point"]
    assert "HSDB" in r["flash-point_source"]
    assert "202 °C" in r["boiling-point"]
    # missing property is reported, never invented
    assert r["melting-point"] == "(no source found)"
    assert r["density"] == "(no source found)"


def test_export_uncurated_columns_stay_empty(facts):
    rows = core.export_rows(facts, ["IPDI"])
    r = rows[0]
    assert r["abbrevs"] == []  # no abbreviation registered for IPDI
    assert r["name_zh"] == ""  # no Chinese name curated -> empty, not guessed
    assert r["name_zh_source"] == ""


def test_export_merges_duplicate_subjects(facts):
    rows = core.export_rows(facts, ["NMP", "872-50-4"])
    assert len(rows) == 1
    assert set(rows[0]["inputs"]) == {"NMP", "872-50-4"}


def test_export_unresolved_subject_is_reported(facts):
    rows = core.export_rows(facts, ["NMP", "no-such-compound-zzz"])
    assert rows[0]["unresolved"] is False
    assert rows[1]["unresolved"] is True
    assert "no-such-compound-zzz" in rows[1]["error"]


def test_export_uses_cache_then_bypasses_it(facts, monkeypatch):
    # warm the cache, then verify --fresh forces client calls
    core.export_rows(facts, ["NMP"])
    calls_after_warm = len(facts.client.calls)
    core.export_rows(facts, ["NMP"], fresh=True)
    assert len(facts.client.calls) > calls_after_warm  # fresh bypassed the cache


def test_cli_export_md(facts, monkeypatch):
    def _facts_stub():
        return facts

    monkeypatch.setattr(cli, "_facts", _facts_stub)
    r = runner.invoke(cli.app, ["export", "NMP", "--format", "md"])
    assert r.exit_code == 0, r.output
    out = r.output
    assert "N-甲基-2-吡咯烷酮" in out  # Chinese name column
    assert "872-50-4" in out
    assert "99.13 g/mol" in out
    assert "(no source found)" in out  # melting point missing, honestly marked


# -- manual entries: substances PubChem does not carry (polymers, blends) -----


def test_export_manual_entry_fills_unresolved_row(facts):
    from chemfacts import new_entry

    facts.manuals.add(
        new_entry(
            "PTMG-2000",
            name_en="Polytetramethylene glycol (PTMEG-2000)",
            cas="25268-40-0",
            formula="C4H8O)n",
            mw="2000 (COA)",
            note="supplier COA, lot 2026-08",
        )
    )
    rows = core.export_rows(facts, ["PTMG-2000"])
    assert len(rows) == 1
    r = rows[0]
    assert r.get("manual") is True          # flagged, never passes as a DB value
    assert r["unresolved"] is False
    assert r["name_en"] == "Polytetramethylene glycol (PTMEG-2000)"
    assert r["cas"] == "25268-40-0"
    assert r["mw"] == "2000 (COA)"
    assert "manuals.json" in r["mw_source"]
    assert r["note"] == "supplier COA, lot 2026-08"
    # no PubChem record -> property cells stay empty (no invented values)
    assert r["flash-point"] == ""
    assert r["density"] == ""


def test_export_manual_match_by_cas(facts):
    from chemfacts import new_entry

    facts.manuals.add(new_entry("PTMG-2000", cas="25268-40-0", mw="2000 (COA)"))
    rows = core.export_rows(facts, ["25268-40-0"])
    assert len(rows) == 1
    assert rows[0].get("manual") is True
    assert rows[0]["manual_label"] == "PTMG-2000"


def test_export_manual_merges_duplicate_inputs(facts):
    from chemfacts import new_entry

    facts.manuals.add(new_entry("PTMG-2000", cas="25268-40-0"))
    rows = core.export_rows(facts, ["ptmg-2000", "PTMG-2000"])
    assert len(rows) == 1
    assert len(rows[0]["inputs"]) == 2


def test_export_unresolved_without_manual_stays_error_row(facts):
    rows = core.export_rows(facts, ["PTMG-2000"])
    assert len(rows) == 1
    assert rows[0]["unresolved"] is True
    assert rows[0].get("manual") is None


def test_cli_export_md_marks_manual_rows(facts, monkeypatch):
    from chemfacts import new_entry

    facts.manuals.add(
        new_entry("PTMG-2000", name_en="Polytetramethylene glycol",
                  mw="2000 (COA)", note="supplier COA")
    )

    def _facts_stub():
        return facts

    monkeypatch.setattr(cli, "_facts", _facts_stub)
    r = runner.invoke(cli.app, ["export", "PTMG-2000", "--format", "md"])
    assert r.exit_code == 0, r.output
    out = r.output
    assert "Polytetramethylene glycol" in out
    assert "（人工条目 · 无 PubChem 记录）" in out  # row is visibly marked
    assert "supplier COA" in out                       # 备注 column
