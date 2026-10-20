"""chemfacts CLI.

    chemfacts resolve "NMP"
    chemfacts lookup  "NMP" flash-point
    chemfacts card    "IPDI" --format obsidian --out ipdi.md
    chemfacts verify  "IPDI" mw --claim "222.28"
    chemfacts cache clear
"""

from __future__ import annotations

from pathlib import Path

import typer

from . import core, model, pubchem

app = typer.Typer(
    name="chemfacts",
    help="Provenance-first chemical fact verification. No fabrication, ever.",
    no_args_is_help=True,
    add_completion=False,
)
cache_app = typer.Typer(help="Manage the local fact cache.")
app.add_typer(cache_app, name="cache")


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
    typer.echo(f"identity        : {ident.name or ident.title or identifier}")
    typer.echo(f"CID             : {ident.cid}")
    typer.echo(f"CAS             : {ident.cas or '(not found)'}")
    typer.echo(f"IUPAC           : {ident.iupac_name or '(n/a)'}")
    typer.echo(f"Formula         : {ident.formula or '(n/a)'}")
    mw = f"{ident.molecular_weight} g/mol" if ident.molecular_weight is not None else "(n/a)"
    typer.echo(f"MW              : {mw}")
    typer.echo(f"SMILES          : {ident.canonical_smiles or '(n/a)'}")
    typer.echo(f"InChIKey        : {ident.inchi_key or '(n/a)'}")
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


def main() -> None:
    """Entry point (installed as `chemfacts`)."""
    app()


if __name__ == "__main__":
    main()
