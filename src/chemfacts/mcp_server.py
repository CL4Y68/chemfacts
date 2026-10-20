"""MCP server: expose chemfacts as standard MCP tools.

Any MCP client (Claude Code, Codex, Zed, Hermes, agent harnesses, ...) can
register this server, and LLMs then verify chemical facts by provenance
instead of by memory.

Two transports:

- ``stdio`` (default): the agent spawns the server as a local process.
- ``streamable-http``: a network service for Docker / multi-client sharing
  (one shared fact cache + alias registry via mounted volumes).

Tools return structured JSON (``dict``) with provenance; unresolved input
comes back as ``{"ok": false, "error": ...}`` instead of a protocol error.
"""

from __future__ import annotations

import argparse

from mcp.server.mcpserver import MCPServer

from . import core
from .model import CompoundIdentity, PropertyValue
from .pubchem import PubChemError

_INSTRUCTIONS = (
    "chemfacts: provenance-first chemical fact verification. Every returned value "
    "carries its source and access date; a value that cannot be sourced is reported "
    "as 'no sourced value', never invented. Ambiguous abbreviations (DMPA, H12MDI, "
    "BA, ...) are resolved through a local alias registry when pinned; pin new ones "
    "with chemfacts_alias action='add'."
)

server = MCPServer(
    name="chemfacts",
    description="Provenance-first chemical fact verification (PubChem-backed, never fabricates).",
    instructions=_INSTRUCTIONS,
)

# Lazy singleton, overridable in tests (monkeypatch this attribute).
_FACTS: core.ChemFacts | None = None


def _facts() -> core.ChemFacts:
    global _FACTS
    if _FACTS is None:
        _FACTS = core.ChemFacts()
    return _FACTS


# -- serializers -------------------------------------------------------------


def _identity_payload(ident: CompoundIdentity) -> dict:
    out: dict = {
        "cid": ident.cid,
        "name": ident.name,
        "iupac": ident.iupac_name,
        "cas": ident.cas,
        "formula": ident.formula,
        "molecular_weight": ident.molecular_weight,
        "canonical_smiles": ident.canonical_smiles,
        "inchi_key": ident.inchi_key,
        "accessed_at": ident.accessed_at,
        "source": ident.source,
    }
    return out


def _value_payload(v: PropertyValue) -> dict:
    return {
        "property": v.property_name,
        "value": v.value,
        "source": v.source_name,
        "reference_number": v.reference_number,
        "kind": v.kind,  # experimental | computed | registry
        "accessed_at": v.accessed_at,
    }


def _entry_payload(e) -> dict:
    return {"alias": e.alias, "identifier": e.identifier, "note": e.note, "added": e.added}


# -- tools ---------------------------------------------------------------------


@server.tool()
def chemfacts_resolve(identifier: str) -> dict:
    """Resolve a compound name / CAS / CID / SMILES / pinned abbreviation to its
    identity (IUPAC, CAS, formula, MW, SMILES, InChIKey), with provenance.

    Abbreviations registered in the alias registry are pinned to a unique
    identifier before resolution, so 'DMPA' or 'H12MDI' never guess.
    """
    f = _facts()
    try:
        ident = f.resolve(identifier)
    except PubChemError as e:
        return {"ok": False, "error": f"unresolved: {e}", "input": identifier}
    out = _identity_payload(ident)
    out["ok"] = True
    entry = f.aliases.get(identifier)
    if entry is not None:
        out["pinned_via_alias"] = entry.identifier
        out["alias_note"] = entry.note
    return out


@server.tool()
def chemfacts_lookup(identifier: str, property_slug: str) -> dict:
    """Every *sourced* value of one property for a compound, with provenance.

    property_slug is one of: flash-point, boiling-point, melting-point,
    density, solubility, vapor-pressure, autoignition-point, explosive-limits,
    surface-tension, viscosity, mw, formula.
    """
    f = _facts()
    try:
        values = f.lookup(identifier, property_slug)
    except PubChemError as e:
        return {"ok": False, "error": f"unresolved: {e}", "input": identifier}
    if not values:
        return {
            "ok": True,
            "property": core._heading(property_slug),
            "values": [],
            "note": "no sourced value found - not verified, not fabricated",
        }
    return {
        "ok": True,
        "property": core._heading(property_slug),
        "values": [_value_payload(v) for v in values],
    }


@server.tool()
def chemfacts_crosscheck(identifier: str, property_slug: str = "flash-point") -> dict:
    """Compare all sourced values of one property; return status
    (verified / conflict / unverified) plus every value with its source.
    Conflicts are flagged, not averaged away."""
    f = _facts()
    try:
        values, status = f.crosscheck(identifier, property_slug)
    except PubChemError as e:
        return {"ok": False, "error": f"unresolved: {e}", "input": identifier}
    return {
        "ok": True,
        "property": core._heading(property_slug),
        "status": status,
        "values": [_value_payload(v) for v in values],
    }


@server.tool()
def chemfacts_verify(
    identifier: str, property_slug: str, claim: str, tolerance: float = 0.02
) -> dict:
    """The point of chemfacts: hold a claimed value against every sourced value.

    Returns verdict: 'confirmed' (a sourced value agrees within tolerance),
    'mismatch' (closest sourced value + its source), or 'not_found' (no sourced
    value exists - the claim stays unverified).
    """
    f = _facts()
    try:
        result = f.verify(identifier, property_slug, claim, tolerance)
    except PubChemError as e:
        return {"ok": False, "error": f"unresolved: {e}", "input": identifier}
    out: dict = {
        "ok": True,
        "property": result.claimed_property,
        "claim": result.claimed_value,
        "verdict": result.verdict,
        "detail": result.detail,
    }
    if result.closest is not None:
        out["closest"] = _value_payload(result.closest)
    out["matches"] = [_value_payload(v) for v in result.matches]
    return out


@server.tool()
def chemfacts_card(
    identifier: str,
    properties: list[str] | None = None,
    fmt: str = "obsidian",
) -> dict:
    """Build an auditable fact card for a compound (identity + sourced properties
    + status + notes). fmt: 'obsidian' (YAML frontmatter, Chinese vault layout),
    'md' (plain English), or 'json'."""
    f = _facts()
    try:
        card = f.build_card(identifier, properties=properties)
    except PubChemError as e:
        return {"ok": False, "error": f"unresolved: {e}", "input": identifier}
    if fmt == "json":
        return {"ok": True, "status": card.status, "card_json": core.card_to_json(card)}
    obsidian = fmt != "md"
    md = core.card_to_markdown(card, obsidian=obsidian)
    return {"ok": True, "status": card.status, "card_markdown": md}


@server.tool()
def chemfacts_alias(action: str, alias: str = "", identifier: str = "", note: str = "") -> dict:
    """Manage the abbreviation -> compound registry (disambiguation pins).

    action='list': all pins. action='add': alias + identifier (CAS preferred) +
    note. action='show': one alias. action='remove': one alias. The registry is a
    small, stable, unambiguous JSON file; structure/name/InChIKey are derived
    from the pinned CAS at resolution time.
    """
    f = _facts()
    reg = f.aliases
    if action == "list":
        return {"ok": True, "entries": [_entry_payload(e) for e in reg.list()]}
    if action == "add":
        if not alias or not identifier:
            return {"ok": False, "error": "add requires alias + identifier (CAS preferred)"}
        return {"ok": True, "entry": _entry_payload(reg.add(alias, identifier, note))}
    if action == "show":
        e = reg.get(alias)
        if e is None:
            return {"ok": False, "error": f"{alias.upper()} not in registry"}
        return {"ok": True, "entry": _entry_payload(e)}
    if action == "remove":
        ok = reg.remove(alias)
        return {"ok": ok, "removed": alias.upper() if ok else None}
    return {"ok": False, "error": f"unknown action '{action}' (use add|list|show|remove)"}


# -- entry points --------------------------------------------------------------


def main(
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    path: str = "/mcp",
) -> None:
    """Blocking server entry point. transport: stdio | streamable-http | sse."""
    if transport == "stdio":
        server.run("stdio")
    else:
        server.run(transport, host=host, port=port, streamable_http_path=path)


def run_main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="chemfacts-mcp", description="Run the chemfacts MCP server.")
    p.add_argument("--transport", choices=["stdio", "streamable-http", "sse"], default="stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--path", default="/mcp", help="streamable-http mount path")
    a = p.parse_args(argv)
    main(a.transport, a.host, a.port, a.path)


if __name__ == "__main__":
    run_main()
