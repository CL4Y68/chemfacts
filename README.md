# chemfacts

**Provenance-first chemical fact verification.**

Every number chemfacts reports is *sourced, dated, and cross-checked*; if a value
cannot be sourced, it says so instead of inventing one. Chemical property values
(molecular weight, flash point, melting/boiling point, …) are the classic place where
both humans and LLMs quietly get things wrong *confidently* — a mis-copied digit, a
value remembered from the wrong compound, "a literature value". chemfacts exists to
make that failure mode impossible.

[English](README.md) | [中文文档](README_zh.md)

> **Pick it up and use it?** Read the [User Manual](docs/USAGE.md) /
> [使用手册（中文）](docs/USAGE_zh.md) — feature reference, operating guide, and
> verifiable evidence (every example is a real, replayable output).

## A real catch

```
$ chemfacts verify "1,12-diisocyanatododecane" mw --claim "262.35"
verdict: MISMATCH
detail : claim 262.35 not confirmed; closest sourced value: 252.35 g/mol (PubChem PUG REST)
```

Now pin the ambiguous abbreviation to the compound you actually use:

```
$ chemfacts alias add H12MDI 5124-30-1 --note "hydrogenated MDI, not 1,12-diisocyanatododecane"
$ chemfacts verify H12MDI mw --claim "262.35"
verdict: CONFIRMED
```

The *same* number is wrong for one compound and right for the other. chemfacts only
knows the difference because the abbreviation was pinned. That pin is a two-line JSON
entry, not a memory.

## How it works

```mermaid
%%{init: {"look": "neo", "theme": "base", "themeVariables": {"lineColor": "#94a3b8", "primaryTextColor": "#0f172a", "edgeLabelBackground": "#ffffff"}, "flowchart": {"curve": "basis", "htmlLabels": true, "nodeSpacing": 42, "rankSpacing": 56, "padding": 10}} }%%
flowchart LR
    A(["input · name / CAS / CID / SMILES / abbreviation"]):::io --> B

    subgraph REG["alias registry · pins ambiguous abbreviations"]
        B{"registered alias?"}:::decide
    end
    B -- "yes → pin to unique CAS" --> D["classify identifier"]:::proc
    B -- "no → classify as-is" --> D

    subgraph PUB["PubChem · network"]
        D --> E["PUG REST · identity<br/>IUPAC · CAS · formula · MW · SMILES · InChIKey"]:::proc
        D --> F["PUG View · sourced values<br/>flash point · bp · mp · density …"]:::proc
    end

    subgraph LOCAL["local state · SQLite + JSON"]
        E --> G[("fact cache<br/>TTL + full provenance")]:::store
        F --> G
    end
    classDef io      fill:#e0e7ff,stroke:#4f46e5,stroke-width:2px,color:#312e81
    classDef proc    fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef decide  fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef store   fill:#d1fae5,stroke:#059669,color:#064e3b
    classDef ok      fill:#bbf7d0,stroke:#16a34a,stroke-width:2px,color:#14532d
    classDef warn    fill:#fecaca,stroke:#dc2626,stroke-width:2px,color:#7f1d1d
    classDef plain   fill:#e2e8f0,stroke:#64748b,color:#334155
    classDef card   fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    classDef mcp    fill:#cffafe,stroke:#0891b2,color:#164e63
    classDef ext    fill:#f8fafc,stroke:#94a3b8,stroke-dasharray:5 4,color:#475569
```

Step 1 — **resolve** a query into identity + sourced values:
pin the abbreviation (if registered), classify the identifier, pull
PubChem, and cache locally with provenance.

```mermaid
%%{init: {"look": "neo", "theme": "base", "themeVariables": {"lineColor": "#94a3b8", "primaryTextColor": "#0f172a", "edgeLabelBackground": "#ffffff"}, "flowchart": {"curve": "basis", "htmlLabels": true, "nodeSpacing": 42, "rankSpacing": 56, "padding": 10}} }%%
flowchart LR
    G[("fact cache<br/>TTL + full provenance")]:::store --> H

    H["cross-check<br/>unit-normalise · drop qualified / sub-atmospheric"]:::proc
    H --> I{"spread vs per-property floor?"}:::decide
    I -- "no values" --> J(["unverified"]):::plain
    I -- "spread > floor" --> K(["conflict<br/>unless closed-cup vs open-cup"]):::warn
    I -- "within floor" --> L(["verified"]):::ok
    J --> M["auditable fact card<br/>Markdown · Obsidian frontmatter · JSON"]:::card
    K --> M
    L --> M
    classDef io      fill:#e0e7ff,stroke:#4f46e5,stroke-width:2px,color:#312e81
    classDef proc    fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef decide  fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef store   fill:#d1fae5,stroke:#059669,color:#064e3b
    classDef ok      fill:#bbf7d0,stroke:#16a34a,stroke-width:2px,color:#14532d
    classDef warn    fill:#fecaca,stroke:#dc2626,stroke-width:2px,color:#7f1d1d
    classDef plain   fill:#e2e8f0,stroke:#64748b,color:#334155
    classDef card   fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    classDef mcp    fill:#cffafe,stroke:#0891b2,color:#164e63
    classDef ext    fill:#f8fafc,stroke:#94a3b8,stroke-dasharray:5 4,color:#475569
```

Step 2 — **verify**: cross-check the cached values against
per-property conflict floors; whatever the outcome, everything lands
in one auditable card.


Two design rules hold everywhere:

1. **No fabrication.** Absence of data is reported as absence
   ("no sourced value found for: Boiling Point"), never filled in.
2. **Provenance on every value** — source name (HSDB, ILO ICSC, EPA, CAMEO, …),
   PubChem reference number, access date, and `experimental` vs `computed` kind.

## Abbreviation disambiguation

One abbreviation can mean several compounds (DMPA is dimethylolpropionic acid *or*
dimethylpiperazine; H12MDI is hydrogenated MDI *or* 1,12-diisocyanatododecane; BA is
butyl acrylate). The registry resolves that once, for every subsequent lookup:

```mermaid
%%{init: {"look": "neo", "theme": "base", "themeVariables": {"lineColor": "#94a3b8", "primaryTextColor": "#0f172a", "edgeLabelBackground": "#ffffff"}, "flowchart": {"curve": "basis", "htmlLabels": true, "nodeSpacing": 42, "rankSpacing": 56, "padding": 10}} }%%
flowchart LR
    A(["DMPA<br/>ambiguous abbreviation"]):::io
    B["alias registry<br/>pin → CAS 4767-03-7<br/>+ why-not note"]:::decide
    C["PubChem identity<br/>IUPAC · C5H10O4 · SMILES · InChIKey · MW"]:::proc
    D["PubChem PUG View<br/>sourced property values"]:::proc
    E["fact card<br/>name + structure + values + provenance"]:::card

    A -- "registry pin" --> B
    B -- "resolve (CAS = unique key)" --> C
    B -- "query" --> D
    C --> E
    D --> E
    classDef io      fill:#e0e7ff,stroke:#4f46e5,stroke-width:2px,color:#312e81
    classDef proc    fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef decide  fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef store   fill:#d1fae5,stroke:#059669,color:#064e3b
    classDef ok      fill:#bbf7d0,stroke:#16a34a,stroke-width:2px,color:#14532d
    classDef warn    fill:#fecaca,stroke:#dc2626,stroke-width:2px,color:#7f1d1d
    classDef plain   fill:#e2e8f0,stroke:#64748b,color:#334155
    classDef card   fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    classDef mcp    fill:#cffafe,stroke:#0891b2,color:#164e63
    classDef ext    fill:#f8fafc,stroke:#94a3b8,stroke-dasharray:5 4,color:#475569
```

What is pinned and why: a registry entry stores only the **small, stable, unambiguous
part** — the abbreviation and its pinned CAS plus a note recording *why* this
compound was chosen (and which ones were not). Structure, name, and InChIKey are
*derived* from the CAS at resolution time, so they can never drift out of sync with
the values. The entry format:

```json
{
  "DMPA": {
    "identifier": "4767-03-7",
    "note": "dimethylolpropionic acid, anionic WPU component; NOT 1,4-dimethylpiperazine / TMEDA",
    "added": "2026-10-20"
  }
}
```

```bash
$ chemfacts alias add DMPA 4767-03-7 --note "dimethylolpropionic acid, NOT dimethylpiperazine"
pinned DMPA -> 4767-03-7 (2026-10-20)
$ chemfacts alias list
DMPA       -> 4767-03-7  # dimethylolpropionic acid, NOT dimethylpiperazine
$ chemfacts alias show DMPA
$ chemfacts alias remove DMPA
```

The file is plain JSON (`~/.cache/chemfacts/aliases.json` by default; override with
`CHEMFACTS_ALIASES`), so you can keep it next to your fact-card vault and commit it
to version control. See [aliases.example.json](aliases.example.json).

## Status logic

```mermaid
%%{init: {"look": "neo", "theme": "base", "themeVariables": {"lineColor": "#94a3b8", "primaryTextColor": "#0f172a", "edgeLabelBackground": "#ffffff"}, "flowchart": {"curve": "basis", "htmlLabels": true, "nodeSpacing": 42, "rankSpacing": 56, "padding": 10}} }%%
flowchart LR
    A["sourced values for one property"]:::proc
    B["keep only comparable values<br/>drop qualified ('approx.') &<br/>sub-atmospheric ('10 mmHg')<br/>normalise °F → °C"]:::proc
    C{"≥ 2 values?"}:::decide
    D{"spread > floor?"}:::decide
    E{"closed-cup AND open-cup<br/>both present?"}:::decide
    V(["verified<br/>single source · within floor · cup difference"]):::ok
    X(["CONFLICT<br/>flag it · show every value + source"]):::warn
    N["per-property floors<br/>mp ±3 · bp ±2 · flash ±1.5 · autoignition ±20 · density ±0.01<br/>other: 10% relative"]:::plain

    A --> B --> C
    C -- "no" --> V
    C -- "yes" --> D
    D -- "no" --> V
    D -- "yes" --> E
    E -- "yes" --> V
    E -- "no" --> X
    D -. "floors" .-> N
    classDef io      fill:#e0e7ff,stroke:#4f46e5,stroke-width:2px,color:#312e81
    classDef proc    fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef decide  fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef store   fill:#d1fae5,stroke:#059669,color:#064e3b
    classDef ok      fill:#bbf7d0,stroke:#16a34a,stroke-width:2px,color:#14532d
    classDef warn    fill:#fecaca,stroke:#dc2626,stroke-width:2px,color:#7f1d1d
    classDef plain   fill:#e2e8f0,stroke:#64748b,color:#334155
    classDef card   fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    classDef mcp    fill:#cffafe,stroke:#0891b2,color:#164e63
    classDef ext    fill:#f8fafc,stroke:#94a3b8,stroke-dasharray:5 4,color:#475569
```

Per-property floors keep normal source-to-source variation from being flagged:
melting point ±3 °C, boiling point ±2 °C, flash point ±1.5 °C, autoignition ±20 °C,
density ±0.01 g/cm³; everything else uses a 10 % relative threshold.

## Architecture

```mermaid
%%{init: {"look": "neo", "theme": "base", "themeVariables": {"lineColor": "#94a3b8", "primaryTextColor": "#0f172a", "edgeLabelBackground": "#ffffff"}, "flowchart": {"curve": "basis", "htmlLabels": true, "nodeSpacing": 42, "rankSpacing": 56, "padding": 10}} }%%
flowchart LR
    CLI["cli.py · typer<br/>resolve · lookup · verify · crosscheck · card<br/>cache · alias · mcp"]:::mcp
    subgraph CORE["core.py — ChemFacts facade"]
        direction TB
        R["resolve()<br/>alias pin → identity → cache"]:::proc
        L["lookup()<br/>PUG View values + provenance"]:::proc
        X["crosscheck()<br/>comparable filter + conflict floors"]:::proc
        V["verify()<br/>claim vs all sourced values"]:::proc
        C["build_card()<br/>identity + properties + status"]:::proc

        R ~~~ L
        L ~~~ X
        X ~~~ V
        V ~~~ C
    end
    CLI --> CORE
    M["mcp_server.py<br/>stdio + streamable-http<br/>any MCP client"]:::mcp
    CORE --> M
    M --> AG["agents · Claude Code · Codex · ZCode · Hermes …"]:::ext
    CORE --> P["pubchem.py<br/>PUG REST + PUG View client<br/>throttled · retried · 4xx → PubChemError"]:::proc
    CORE --> CA["cache.py<br/>SQLite: identity / value / ref<br/>TTL · provenance kept on reload"]:::store
    CORE --> AL["aliases.py<br/>JSON registry<br/>abbreviation → CAS + note"]:::store
    P --> PC[("PubChem API")]:::ext
    CA --> DB[("~/.cache/chemfacts/facts.db")]:::ext
    AL --> J[("~/.cache/chemfacts/aliases.json")]:::ext
    classDef io      fill:#e0e7ff,stroke:#4f46e5,stroke-width:2px,color:#312e81
    classDef proc    fill:#dbeafe,stroke:#2563eb,color:#1e3a8a
    classDef decide  fill:#fef3c7,stroke:#d97706,color:#78350f
    classDef store   fill:#d1fae5,stroke:#059669,color:#064e3b
    classDef ok      fill:#bbf7d0,stroke:#16a34a,stroke-width:2px,color:#14532d
    classDef warn    fill:#fecaca,stroke:#dc2626,stroke-width:2px,color:#7f1d1d
    classDef plain   fill:#e2e8f0,stroke:#64748b,color:#334155
    classDef card   fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#4c1d95
    classDef mcp    fill:#cffafe,stroke:#0891b2,color:#164e63
    classDef ext    fill:#f8fafc,stroke:#94a3b8,stroke-dasharray:5 4,color:#475569
```

## Commands

| Command | What |
|---|---|
| `chemfacts resolve <id>` | Resolve a name / CAS / SMILES / InChI / CID (or a pinned abbreviation) to identity: IUPAC, CAS, formula, MW, SMILES, InChIKey |
| `chemfacts lookup <id> <property>` | Every *sourced* value of a property, each tagged with source, reference #, kind, access date |
| `chemfacts card <id> [--format md\|obsidian\|json] [--out file]` | An auditable fact card, ready for a lab notebook, manuscript, or Obsidian vault |
| `chemfacts verify <id> <property> --claim <value>` | Hold a claimed value against all sourced values → `confirmed` / `mismatch` (closest value + its source) / `not_found` |
| `chemfacts crosscheck <id> <property>` | Compare sourced values; flag real conflicts, tolerate closed-cup/open-cup differences |
| `chemfacts alias add\|list\|show\|remove` | Manage the abbreviation → compound registry |
| `chemfacts cache clear\|show` | Manage the local SQLite fact cache |

Property slugs: `flash-point`, `boiling-point`, `melting-point`, `density`,
`solubility`, `vapor-pressure`, `autoignition-point`, `explosive-limits`,
`surface-tension`, `viscosity`, `mw`, `formula`.

## Install

```bash
pip install chemfacts
# or
uv tool install chemfacts
```

Requires Python ≥ 3.11.

## Examples

```bash
# identity
$ chemfacts resolve NMP
identity        : N-Methyl-2-pyrrolidone
CID             : 13387
CAS             : 872-50-4
IUPAC           : 1-methylpyrrolidin-2-one
Formula         : C5H9NO
MW              : 99.13 g/mol
SMILES          : CN1CCCC1=O

# every sourced flash point, with provenance
$ chemfacts lookup NMP flash-point
96 °C                                                  | HSDB (ref #46, experimental) | 2026-10-20
204 °F (96 °C) (OPEN CUP)                              | HSDB (ref #46, experimental) | 2026-10-20

# fact card into an Obsidian vault
$ chemfacts card IPDI --format obsidian --out ~/vault/chemical-facts/IPDI.md
wrote /home/you/vault/chemical-facts/IPDI.md  (status: verified)

# verify a number you (or your model) wrote down
$ chemfacts verify NMP mw --claim "99.13"
verdict: CONFIRMED
$ chemfacts verify NMP mw --claim "110.0"
verdict: MISMATCH
detail : claim 110.0 not confirmed; closest sourced value: 99.13 g/mol (PubChem PUG REST)
```

## Use from any agent: MCP server

chemfacts ships an [MCP](https://modelcontextprotocol.io) server, so *any*
MCP-capable agent (Claude Code, Codex, ZCode, Hermes, agent harnesses, ...) can
verify chemical facts by provenance. Six tools are exposed:
`chemfacts_resolve`, `chemfacts_lookup`, `chemfacts_crosscheck`,
`chemfacts_verify`, `chemfacts_card`, `chemfacts_alias`.

### Option 1 — local stdio (no service to run)

```bash
pip install chemfacts
```

Register the `chemfacts-mcp` command with your agent (one entry each; exact
syntax varies by agent/version, the command is always `chemfacts-mcp`
which defaults to stdio):

| Agent | Example registration |
|---|---|
| Claude Code | `claude mcp add chemfacts -- chemfacts-mcp` (or a `mcpServers` entry in `.mcp.json`) |
| Codex | an MCP-server entry for `chemfacts-mcp` in Codex's config |
| Hermes | register `chemfacts-mcp` as a local MCP server (joins the academic MCP group) |

### Option 2 — shared service (Docker + streamable-HTTP, one deployment for many clients)

```bash
docker build -t chemfacts-mcp .
docker run -d -p 8000:8000 -v chemfacts-data:/data chemfacts-mcp
```

Every agent then points at the same URL `http://<host>:8000/mcp`
(e.g. `claude mcp add --transport http chemfacts http://host:8000/mcp`).
The `/data` volume **is the shared retrieval database**:
`facts.db` (SQLite cache, provenance kept on reload) +
`aliases.json` (abbreviation pins) — edit the file, all clients see it.

> If the host machine runs a global HTTP proxy, set `NO_PROXY=127.0.0.1,localhost`
> so agent↔server traffic on localhost is not routed through it.

## Library

```python
from chemfacts import ChemFacts, card_to_markdown

f = ChemFacts()
ident = f.resolve("IPDI")                       # -> CompoundIdentity (CID, CAS, formula, MW, ...)
vals = f.lookup("IPDI", "flash-point")          # -> [PropertyValue, ...] each with source + date
res = f.verify("IPDI", "mw", "222.28")          # -> VerifyResult(verdict="confirmed", ...)
card = f.build_card("IPDI")                     # -> FactCard
print(card_to_markdown(card, obsidian=True))
```

## Caching & provenance

All fetched facts land in a local SQLite database (`~/.cache/chemfacts/facts.db`,
override with `CHEMFACTS_CACHE_DIR`); each row keeps its source and access date.
Entries age out (default 30 days, `ChemFacts(ttl_days=…)`), after which values are
re-fetched — the provenance is never lost, only refreshed.

| Variable | Default | Purpose |
|---|---|---|
| `CHEMFACTS_CACHE_DIR` | `~/.cache/chemfacts` | fact cache DB location |
| `CHEMFACTS_ALIASES` | `<cache dir>/aliases.json` | abbreviation registry file |

## Sources

v0.2 uses **PubChem** (PUG REST for identity, PUG View for experimental property
values aggregated from HSDB, ILO ICSC, EPA, CAMEO, NTP, …). Second-source
cross-checking (NIST WebBook, GESTIS/ECHA) is on the roadmap.

## Roadmap

- [x] PubChem identity + experimental properties, card / verify / crosscheck, SQLite cache
- [x] Abbreviation registry: pin ambiguous names to one compound (JSON, user-editable)
- [ ] NIST WebBook as a second source (phase-transition data)
- [ ] GESTIS / ECHA / vendor SDS for authoritative flash points
- [ ] `batch` mode: verify a whole reagent list for a recipe in one pass
- [x] MCP server: stdio + streamable-http transports, Docker image, six tools — register in any MCP client

## Development

```bash
uv sync
uv run ruff check .
uv run pytest -m "not live"   # offline suite (fake PubChem client + real SQLite)
uv run pytest -m live         # hits the real PubChem API
```

## License

MIT — see [LICENSE](LICENSE).

## Disclaimer

chemfacts reports *published* values with their sources; it is a research aid, not a
safety system. For anything safety-critical (flash points, explosive limits), confirm
against the SDS of the exact product you hold in your hand.
