# chemfacts

**Provenance-first chemical fact verification.**

Chemical property values (molecular weight, flash point, melting/boiling point, …) are
the classic place where both humans and LLMs quietly get things wrong *confidently* —
"a literature value", a mis-copied digit, a number remembered from the wrong compound.
`chemfacts` exists to make that failure mode impossible: **every number it reports is
sourced, dated, and cross-checked; if a value cannot be sourced, it says so instead of
inventing one.**

```
chemfacts verify H12MDI mw --claim "262.35"
verdict: MISMATCH
detail : claim 262.35 not confirmed; closest sourced value: 252.35 g/mol (PubChem PUG REST)
```

That above is a *real* catch: 1,12-diisocyanatododecane (H12MDI, C14H24N2O2) is
**252.35 g/mol**, not 262.35. The tool tells you.

## What it does

| Command | What |
|---|---|
| `chemfacts resolve <id>` | Resolve name / CAS / SMILES / InChI / CID to identity: IUPAC, CAS, formula, MW, SMILES, InChIKey |
| `chemfacts lookup <id> <property>` | Every *sourced* value of a property (flash-point, boiling-point, …), each tagged with source, reference #, kind (experimental/computed) and access date |
| `chemfacts card <id>` | An auditable fact card (Markdown with YAML frontmatter for Obsidian, or JSON), ready to drop into a lab notebook or manuscript |
| `chemfacts verify <id> <property> --claim <value>` | The point of the project: hold a claimed value against all sourced values → `confirmed` / `mismatch` (with the closest value + its source) / `not_found` |
| `chemfacts crosscheck <id> <property>` | Compare sourced values; flag real conflicts, tolerate closed-cup/open-cup differences |
| `chemfacts cache …` | Manage the local SQLite fact cache (TTL + full provenance) |

Rules enforced by design:

- **No fabrication.** Absence of data is reported as absence ("no sourced value found").
- **Provenance on every value** — source name (HSDB, ILO ICSC, EPA, CAMEO, …), PubChem
  reference number, access date, and whether it is *experimental* or *computed*.
- **Computed vs. measured** are labelled, so you never cite a predicted logP as an
  experimental value.
- **Conflicts are flagged, not averaged away.** Closed-cup 40 °C vs open-cup 66 °C is
  a condition difference; 155 °C vs 200 °C is a conflict.

## Sources

v0.1 uses **PubChem** (PUG REST for identity, PUG View for experimental property values
aggregated from HSDB, ILO ICSC, EPA, CAMEO, NTP, and more). Second-source cross-checking
(NIST WebBook, GESTIS) is on the roadmap.

## Install

```bash
pip install chemfacts
# or
uv tool install chemfacts
```

## CLI examples

```bash
# identity
$ chemfacts resolve "NMP"
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

## Library

```python
from chemfacts import ChemFacts

f = ChemFacts()
ident = f.resolve("IPDI")
vals = f.lookup("IPDI", "flash-point")
res = f.verify("IPDI", "mw", "222.28")   # -> VerifyResult(verdict="confirmed", ...)
card = f.build_card("IPDI")
from chemfacts import card_to_markdown
print(card_to_markdown(card, obsidian=True))
```

## Caching & provenance

All fetched facts land in a local SQLite database
(`~/.cache/chemfacts/facts.db`, override with `CHEMFACTS_CACHE_DIR`),
each row carrying its source and access date. Cache entries age out (default 30 days,
`ChemFacts(ttl_days=…)`), after which values are re-fetched — the provenance is never
lost, only refreshed.

## Roadmap

- [x] PubChem identity + experimental properties, card/verify/crosscheck, SQLite cache
- [ ] NIST WebBook as a second source (phase-transition data)
- [ ] GESTIS / ECHA / vendor SDS for authoritative flash points
- [ ] `batch` mode: verify a whole reagent list for a recipe in one pass
- [ ] MCP server so LLM agents must source their chemistry claims

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
