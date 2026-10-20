"""CLI smoke tests (offline, fake client)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from chemfacts import cli
from tests.test_core import FakePubChem

runner = CliRunner()


@pytest.fixture()
def fake_cli(monkeypatch, tmp_path):
    from chemfacts.cache import FactCache
    from chemfacts.core import ChemFacts

    monkeypatch.setenv("CHEMFACTS_ALIASES", str(tmp_path / "aliases.json"))

    def _facts_stub():
        return ChemFacts(client=FakePubChem(), cache=FactCache(str(tmp_path / "c.db")))

    monkeypatch.setattr(cli, "_facts", _facts_stub)


def test_resolve(fake_cli):
    r = runner.invoke(cli.app, ["resolve", "IPDI"])
    assert r.exit_code == 0
    assert "C12H18N2O2" in r.output
    assert "222.28" in r.output


def test_lookup_no_value_exits_2(fake_cli):
    r = runner.invoke(cli.app, ["lookup", "NMP", "density"])
    assert r.exit_code == 2
    assert "NO SOURCED VALUE" in r.output


def test_card_to_stdout(fake_cli):
    r = runner.invoke(cli.app, ["card", "IPDI", "--format", "obsidian"])
    assert r.exit_code == 0
    assert r.output.startswith("---")
    assert "155" in r.output


def test_verify_confirmed_exit0(fake_cli):
    r = runner.invoke(cli.app, ["verify", "IPDI", "flash-point", "--claim", "155"])
    assert r.exit_code == 0
    assert "CONFIRMED" in r.output


def test_verify_mismatch_exit1(fake_cli):
    r = runner.invoke(cli.app, ["verify", "IPDI", "flash-point", "--claim", "200"])
    assert r.exit_code == 1
    assert "MISMATCH" in r.output


def test_cache_show(fake_cli):
    runner.invoke(cli.app, ["lookup", "IPDI", "flash-point"])
    r = runner.invoke(cli.app, ["cache", "show"])
    assert r.exit_code == 0
    assert "value" in r.output
