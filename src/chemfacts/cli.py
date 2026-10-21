"""chemfacts CLI.

    chemfacts resolve "NMP"
    chemfacts lookup  "NMP" flash-point
    chemfacts card    "IPDI" --format obsidian --out ipdi.md
    chemfacts verify  "IPDI" mw --claim "222.28"
    chemfacts cache clear
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import typer

from . import core, model, pubchem
from .aliases import AliasRegistry
from .manuals import ManualRegistry, new_entry
from .zhnames import ZhNameRegistry

app = typer.Typer(
    name="chemfacts",
    help="Provenance-first chemical fact verification. No fabrication, ever.",
    no_args_is_help=True,
    add_completion=False,
)
cache_app = typer.Typer(help="Manage the local fact cache.")
app.add_typer(cache_app, name="cache")
alias_app = typer.Typer(help="Manage the abbreviation -> compound registry.")
app.add_typer(alias_app, name="alias")
zhname_app = typer.Typer(help="Manage curated Chinese names (manual curation only, never guessed).")
app.add_typer(zhname_app, name="zhname")
manual_app = typer.Typer(
    help="Manage manual entries for substances PubChem does not carry "
    "(polymers, mixtures, vendor grades)."
)
app.add_typer(manual_app, name="manual")


def _facts() -> core.ChemFacts:
    return core.ChemFacts()


@app.command()
def resolve(identifier: str = typer.Argument(..., help="name, CAS, SMILES, InChI or CID")):
    """Resolve an identifier to a compound identity (with provenance)."""
    f = _facts()
    try:
        ident = f.resolve(identifier)
    except pubchem.PubChemError as e:
        typer.echo(f"UNRESOLVED: {e}")
        raise typer.Exit(1) from e
    entry = f.aliases.get(identifier)
    if entry is not None:
        typer.echo(f"pinned via alias: {entry.alias} -> {entry.identifier}"
                   + (f"  # {entry.note}" if entry.note else ""))
    typer.echo(f"identity        : {ident.name or ident.title or identifier}")
    typer.echo(f"CID             : {ident.cid}")
    typer.echo(f"CAS             : {ident.cas or '(not found)'}")
    typer.echo(f"IUPAC           : {ident.iupac_name or '(n/a)'}")
    zh = f.zhnames.find(ident.cas, ident.cid)
    if zh is not None:
        src = f"  (来源: {zh.source})" if zh.source else "  (人工录入)"
        typer.echo(f"中文名          : {zh.name_zh}{src}")
    typer.echo(f"Formula         : {ident.formula or '(n/a)'}")
    mw = f"{ident.molecular_weight} g/mol" if ident.molecular_weight is not None else "(n/a)"
    typer.echo(f"MW              : {mw}")
    typer.echo(f"SMILES          : {ident.canonical_smiles or '(n/a)'}")
    typer.echo(f"InChIKey        : {ident.inchi_key or '(n/a)'}")
    key = ident.cas if ident.cas else (str(ident.cid) if ident.cid is not None else "")
    if key:
        abbrs = [e.alias for e in f.aliases.aliases_for(key)]
        if abbrs:
            typer.echo(f"Registered abbr : {', '.join(abbrs)}  (registry)")
    typer.echo(f"Accessed        : {ident.accessed_at}  source: {ident.source}")


@app.command()
def lookup(
    identifier: str = typer.Argument(..., help="compound name / CAS / CID"),
    property_slug: str = typer.Argument(
        "flash-point", help="flash-point | boiling-point | melting-point | density | ..."
    ),
) -> None:
    """List every sourced value of a property for a compound."""
    f = _facts()
    try:
        values = f.lookup(identifier, property_slug)
    except pubchem.PubChemError as e:
        typer.echo(f"UNRESOLVED: {e}")
        raise typer.Exit(1) from e
    if not values:
        heading = core._heading(property_slug)
        typer.echo(f"NO SOURCED VALUE for '{heading}' - not verified, not fabricated.")
        raise typer.Exit(2)
    for v in values:
        typer.echo(
            f"{v.value:60.60} | {v.source_name} (ref #{v.reference_number}, {v.kind}) "
            f"| {v.accessed_at[:10]}"
        )


@app.command()
def card(
    identifier: str = typer.Argument(...),
    fmt: str = typer.Option("md", "--format", help="md | obsidian | json"),
    out: Path | None = typer.Option(None, "--out", help="write to file instead of stdout"),
    properties: str = typer.Option(
        "",
        "--properties",
        help="comma-separated property list",
    ),
) -> None:
    """Build an auditable fact card (Markdown/JSON) for a compound."""
    f = _facts()
    props = [p.strip() for p in properties.split(",") if p.strip()] or None
    fact_card = f.build_card(identifier, properties=props)
    if fmt == "json":
        text = core.card_to_json(fact_card)
    elif fmt == "obsidian":
        text = core.card_to_markdown(fact_card, obsidian=True)
    else:
        text = core.card_to_markdown(fact_card, obsidian=False)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        typer.echo(f"wrote {out}  (status: {fact_card.status})")
    else:
        typer.echo(text)


@app.command()
def verify(
    identifier: str = typer.Argument(...),
    property_slug: str = typer.Argument(...),
    claim: str = typer.Option(
        ..., "--claim", help="value you (or a model) reported, e.g. '155' or '155 C closed cup'"
    ),
    tolerance: float = typer.Option(0.02, help="relative tolerance for 'confirmed'"),
) -> None:
    """Hold a claimed value against every sourced value. The point of chemfacts."""
    f = _facts()
    try:
        result: model.VerifyResult = f.verify(identifier, property_slug, claim, tolerance)
    except pubchem.PubChemError as e:
        typer.echo(f"UNRESOLVED: {e}")
        raise typer.Exit(1) from e
    typer.echo(f"verdict: {result.verdict.upper()}")
    typer.echo(f"detail : {result.detail}")
    if result.closest:
        typer.echo(f"closest: {result.closest.value} ({result.closest.source_name})")
    for m in result.matches:
        typer.echo(f"match  : {m.value} ({m.source_name})")
    raise typer.Exit(0 if result.verdict == "confirmed" else 1)


@app.command()
def crosscheck(
    identifier: str = typer.Argument(...),
    property_slug: str = typer.Argument("flash-point"),
) -> None:
    """Compare sourced values of one property; flag real conflicts."""
    f = _facts()
    values, status = f.crosscheck(identifier, property_slug)
    typer.echo(f"status: {status.upper()}")
    for v in values:
        typer.echo(f"{v.value:60.60} | {v.source_name} (ref #{v.reference_number})")
    raise typer.Exit(0 if status != "conflict" else 2)


@app.command()
def export(
    identifiers: list[str] = typer.Argument(
        None, help="compounds: name / CAS / CID / registered abbreviation"
    ),
    all_aliases: bool = typer.Option(
        False, "--all-aliases", help="include every registered abbreviation as a subject"
    ),
    fmt: str = typer.Option("csv", "--format", help="csv | md | json"),
    out: Path | None = typer.Option(None, "--out", help="write to a file instead of stdout"),
    fresh: bool = typer.Option(
        False, "--fresh", help="bypass the local cache; pull identity + properties online now"
    ),
):
    """Correspondence table: 缩写 | 中文名 | 英文名 | CAS | CID | 分子式 | 分子量 |
    熔点 | 沸点 | 闪点 | 密度，每一格带来源。

    Online-first: works with an empty local DB — the cache is a TTL accelerator,
    PubChem is the source of truth. Curation columns (abbreviation / Chinese name)
    come from the user's registries only; empty = not curated, never guessed.
    """
    import csv
    import io

    f = _facts()
    subjects: list[str] = []
    if all_aliases:
        subjects.extend(e.alias for e in f.aliases.list())
    subjects.extend(identifiers or [])
    if not subjects:
        typer.echo("no subjects: pass compounds, or use --all-aliases", err=True)
        raise typer.Exit(1)
    seen: set[str] = set()
    subjects = [s for s in subjects if not (s.upper() in seen or seen.add(s.upper()))]
    rows = core.export_rows(f, subjects, fresh=fresh)

    cols = [
        "缩写", "中文名", "英文名", "IUPAC", "CAS", "CID", "分子式",
        "分子量", "分子量来源",
        "熔点", "熔点来源", "沸点", "沸点来源", "闪点", "闪点来源", "密度", "密度来源",
        "备注",
    ]

    def _vals(r: dict) -> dict[str, str]:
        if r.get("unresolved"):
            v = {c: "" for c in cols}
            v["英文名"] = f"(unresolved: {r.get('error', '')})"
            return v
        name_en = r.get("name_en", "")
        if r.get("manual"):
            name_en = f"{name_en}（人工条目 · 无 PubChem 记录）"
        return {
            "缩写": ", ".join(r.get("abbrevs", [])),
            "中文名": r.get("name_zh", ""),
            "英文名": name_en,
            "IUPAC": r.get("iupac", ""),
            "CAS": r.get("cas", ""),
            "CID": str(r.get("cid", "")),
            "分子式": r.get("formula", ""),
            "分子量": r.get("mw", ""),
            "分子量来源": r.get("mw_source", ""),
            "熔点": r.get("melting-point", ""),
            "熔点来源": r.get("melting-point_source", ""),
            "沸点": r.get("boiling-point", ""),
            "沸点来源": r.get("boiling-point_source", ""),
            "闪点": r.get("flash-point", ""),
            "闪点来源": r.get("flash-point_source", ""),
            "密度": r.get("density", ""),
            "密度来源": r.get("density_source", ""),
            "备注": r.get("note", ""),
        }

    if fmt == "json":
        text = json.dumps(rows, indent=2, ensure_ascii=False)
    elif fmt == "md":
        lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for r in rows:
            v = _vals(r)
            lines.append("| " + " | ".join(v[c] for c in cols) + " |")
        text = "\n".join(lines)
    else:  # csv
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for r in rows:
            v = _vals(r)
            w.writerow([v[c] for c in cols])
        text = buf.getvalue()

    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        # BOM so Excel opens the Chinese headers correctly
        out.write_text(text, encoding="utf-8-sig" if fmt == "csv" else "utf-8")
        typer.echo(f"wrote {out}  ({len(rows)} rows)")
    else:
        typer.echo(text)


def _registry() -> AliasRegistry:
    return AliasRegistry()


@alias_app.command("add")
def alias_add(
    alias: str = typer.Argument(..., help="abbreviation, e.g. DMPA"),
    identifier: str = typer.Argument(
        ..., help="pinned CAS / CID / IUPAC / SMILES (CAS preferred)"
    ),
    note: str = typer.Option(
        "", "--note", help="disambiguation note: which compound, and which NOT"
    ),
) -> None:
    """Pin an ambiguous abbreviation to one compound (registry, JSON file)."""
    entry = _registry().add(alias, identifier, note)
    typer.echo(f"pinned {entry.alias} -> {entry.identifier} ({entry.added})")


@alias_app.command("remove")
def alias_remove(alias: str = typer.Argument(..., help="abbreviation to remove")) -> None:
    ok = _registry().remove(alias)
    typer.echo(f"removed {alias.upper()}" if ok else f"{alias.upper()} not in registry")
    raise typer.Exit(0 if ok else 1)


@alias_app.command("list")
def alias_list() -> None:
    entries = _registry().list()
    if not entries:
        typer.echo("(registry empty)")
        return
    for e in entries:
        note = f"  # {e.note}" if e.note else ""
        typer.echo(f"{e.alias:10} -> {e.identifier}{note}")


@alias_app.command("show")
def alias_show(alias: str = typer.Argument(..., help="abbreviation to inspect")) -> None:
    e = _registry().get(alias)
    if e is None:
        typer.echo(f"{alias.upper()} not in registry")
        raise typer.Exit(1)
    typer.echo(f"alias     : {e.alias}")
    typer.echo(f"pinned to : {e.identifier}")
    typer.echo(f"note      : {e.note or '(none)'}")
    typer.echo(f"added     : {e.added or '(unknown)'}")


def _zhnames() -> ZhNameRegistry:
    return ZhNameRegistry()


_CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


def _zh_key_for(identifier: str) -> tuple[str, str]:
    """Key a curation entry on CAS (preferred) or CID, the registry contract.

    A CAS-like or numeric input is used as-is. Anything else (a name or
    abbreviation) is resolved through PubChem first, so the file stays
    machine-readable: a key always names the compound unambiguously.
    """
    raw = identifier.strip()
    if _CAS_RE.match(raw) or raw.isdigit():
        return raw.upper(), "as-is"
    ident = _facts().resolve(raw)
    key = ident.cas or (str(ident.cid) if ident.cid is not None else raw.upper())
    return key, f"resolved to {ident.name or ident.title or raw} ({key})"


@zhname_app.command("add")
def zhname_add(
    identifier: str = typer.Argument(
        ..., help="compound identifier (CAS preferred; names/abbrevs are resolved)"
    ),
    name_zh: str = typer.Argument(..., help="the Chinese name, e.g. 四氢呋喃"),
    source: str = typer.Option(
        "", "--source", help="where this name was verified (SDS / lab handbook / internal sheet...)"
    ),
) -> None:
    """Curate a Chinese name for a compound. Manual curation only — the tool never
    guesses or translates; a missing name stays missing."""
    try:
        key, how = _zh_key_for(identifier)
    except pubchem.PubChemError as e:
        typer.echo(f"cannot key the curation: identifier not resolvable ({e})")
        raise typer.Exit(1) from e
    entry = _zhnames().add(key, name_zh, source)
    typer.echo(f"curated {entry.identifier} -> {entry.name_zh} ({entry.added}) [{how}]")


@zhname_app.command("list")
def zhname_list() -> None:
    entries = _zhnames().list()
    if not entries:
        typer.echo("(no curated Chinese names)")
        return
    for e in entries:
        src = f"  # 来源: {e.source}" if e.source else ""
        typer.echo(f"{e.identifier:16} {e.name_zh}{src}")


@zhname_app.command("show")
def zhname_show(identifier: str = typer.Argument(..., help="compound identifier")) -> None:
    reg = _zhnames()
    e = reg.get(identifier)
    if e is None:
        try:
            key, _how = _zh_key_for(identifier)
        except pubchem.PubChemError:
            key = None
        if key is not None:
            e = reg.get(key)
    if e is None:
        typer.echo(
            f"no curated Chinese name for {identifier.upper()} "
            "(missing = missing, not guessed)"
        )
        raise typer.Exit(1)
    typer.echo(f"identifier : {e.identifier}")
    typer.echo(f"name_zh    : {e.name_zh}")
    typer.echo(f"source     : {e.source or '(none)'}")
    typer.echo(f"added      : {e.added or '(unknown)'}")


@zhname_app.command("remove")
def zhname_remove(identifier: str = typer.Argument(..., help="compound identifier")) -> None:
    reg = _zhnames()
    ok = reg.remove(identifier)
    if not ok:
        try:
            key, _how = _zh_key_for(identifier)
            ok = key != identifier.strip().upper() and reg.remove(key)
        except pubchem.PubChemError:
            pass
    typer.echo(f"removed {identifier.upper()}" if ok else f"{identifier.upper()} not in curation")
    raise typer.Exit(0 if ok else 1)


def _manuals() -> ManualRegistry:
    return ManualRegistry()


@manual_app.command("add")
def manual_add(
    identifier: str = typer.Argument(
        ..., help="your label, e.g. PTMG-2000 or TDI_8020 (kept as-is, uppercase)"
    ),
    name_en: str = typer.Option("", "--name-en", help="English / trade name"),
    cas: str = typer.Option("", "--cas", help="best-known CAS if one exists"),
    formula: str = typer.Option("", "--formula", help="formula or repeat unit, verbatim"),
    mw: str = typer.Option("", "--mw", help="MW as recorded, verbatim (e.g. '2000 (COA)')"),
    note: str = typer.Option(
        "", "--note", help="where these values were verified (supplier COA / SDS / internal spec)"
    ),
) -> None:
    """Record a user-verified entry for a substance PubChem does not carry.

    Values are stored verbatim and displayed only with a
    'user-curated entry (manuals.json)' marker — never as database values.
    """
    entry = new_entry(identifier, name_en, cas, formula, mw, note)
    _manuals().add(entry)
    src = note or "your source"
    typer.echo(f"recorded {entry.identifier} ({entry.added}); verify values against {src}")


@manual_app.command("list")
def manual_list() -> None:
    entries = _manuals().list()
    if not entries:
        typer.echo("(no manual entries)")
        return
    for e in entries:
        bits = [b for b in (e.name_en, f"CAS {e.cas}" if e.cas else "", e.mw) if b]
        extra = " · ".join(bits)
        typer.echo(f"{e.identifier:14} {extra}  # 出处: {e.note or '(none)'}")


@manual_app.command("show")
def manual_show(identifier: str = typer.Argument(..., help="manual-entry label or CAS")) -> None:
    reg = _manuals()
    e = reg.get(identifier) or reg.by_cas(identifier)
    if e is None:
        typer.echo(f"no manual entry for {identifier.upper()}")
        raise typer.Exit(1)
    for k in ("identifier", "name_en", "cas", "formula", "mw", "note", "added"):
        typer.echo(f"{k:10}: {getattr(e, k) or '(none)'}")


@manual_app.command("remove")
def manual_remove(identifier: str = typer.Argument(..., help="manual-entry label")) -> None:
    ok = _manuals().remove(identifier)
    label = identifier.upper()
    typer.echo(f"removed {label}" if ok else f"{label} not in manual entries")
    raise typer.Exit(0 if ok else 1)


@cache_app.command()
def clear() -> None:
    """Drop the entire local fact cache."""
    f = _facts()
    typer.echo(f"cleared {f.cache.clear()} rows")


@cache_app.command()
def show() -> None:
    """Show what is in the cache."""
    f = _facts()
    for table in ("identity", "value", "ref"):
        n = f.cache.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        typer.echo(f"{table:10} {n}")


@app.command()
def mcp(
    transport: str = typer.Option("stdio", help="stdio | streamable-http | sse"),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8000),
    path: str = typer.Option("/mcp", help="streamable-http mount path"),
) -> None:
    """Run the MCP server so any MCP client (Claude Code, Codex, ...) can use chemfacts."""
    from .mcp_server import main as run_mcp_server

    if transport != "stdio":
        typer.echo(f"serving MCP over {transport} (host={host}, port={port}, path={path})")
    run_mcp_server(transport, host, port, path)


def main() -> None:
    """Entry point (installed as `chemfacts`)."""
    app()


if __name__ == "__main__":
    main()
