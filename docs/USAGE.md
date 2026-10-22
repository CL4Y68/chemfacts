# chemfacts User Manual

> User-facing feature reference, operating guide, and verifiable evidence.
> 中文版见 [USAGE_zh](USAGE_zh.md) · project home: [README](../README.md) / [README_zh](../README_zh.md).

This manual follows the design goal of chemfacts: **no fabrication, every value is
traceable**. Every command output below is therefore **not illustrative text** — it is a
result actually produced on a fixed data snapshot. You should be able to replay each one
and check it against the primary sources.

---

## 0. How to read this manual: the evidence snapshot

To make "verifiable" concrete, every example in this manual comes from the same run
environment. Before replaying, match your environment to the table below, or trace
sources yourself per §5.

| Item | Value |
|---|---|
| Version | `0.3.0` |
| Data source | PubChem (PUG REST identity + PUG View values), local cache `~/.cache/chemfacts/facts.db` |
| Alias registry | `~/.cache/chemfacts/aliases.json` (13 pinned entries) |
| Cache size (this snapshot) | `identity 14 · value 224 · ref 1227` |
| Snapshot date | 2026-10-21 (cache `accessed` fields span 2026-10-20 to 2026-10-21) |
| How to run | `uv run chemfacts …` (or `chemfacts …` after install) |

> The cache has a 30-day TTL. Within the TTL the values do not change; after
> `cache clear`, values are re-fetched from PubChem and the `accessed` date updates, but
> the three provenance elements — source + reference number + value — should stay
> identical.

---

## 1. What it is, what it solves

`chemfacts` is a **provenance-first** chemical fact verifier. Give it an identifier
(name / CAS / CID / SMILES / pinned abbreviation) and a property (e.g. flash point) and it
returns **every sourced value** — each with its source, reference number, access date, and
experimental/computed kind — instead of "the number a model remembers".

Three rules hold everywhere:

1. **No fabrication.** Absence is reported as absence (`no sourced value found for: …`),
   never filled in.
2. **Provenance on every value.** Source name (OSHA / HSDB / CAMEO / ILO ICSC / NIOSH /
   EPA …) + PubChem reference number + access date + `experimental` / `computed` kind.
3. **Ambiguous abbreviations get pinned first.** One abbreviation can mean several
   compounds (DMPA, H12MDI, BA…); the registry pins it to a unique CAS once, and every
   later lookup follows that answer. The pin is a JSON entry, not a memory.

Data flow:

```
identifier -> [alias registry pin] -> PubChem (identity + values) -> local cache (TTL + provenance)
            -> cross-check (unit normalisation / comparable-only filter / per-property floors)
            -> status -> auditable fact card
```

---

## 2. Install

**CLI / library (pick one)**

```bash
# primary: install from PyPI
pip install chemfacts
# alternative: install from GitHub (latest dev)
git clone https://github.com/CL4Y68/chemfacts.git
cd chemfacts
pip install .
# or one-liner
pip install git+https://github.com/CL4Y68/chemfacts
# or (this repo, dev mode)
uv run chemfacts --help
```

**MCP server (for any MCP-capable agent, see §4.8)**

```bash
# stdio: the agent spawns it locally, no service to run
# Docker: one shared retrieval DB, many clients point at the same URL
docker build -t chemfacts-mcp .
docker run -d -p 8000:8000 -v chemfacts-data:/data chemfacts-mcp
```

Requires Python ≥ 3.11.

---

## 3. Core concepts (read first)

### 3.1 The three statuses

After cross-checking all sourced values of a property, one of three statuses results:

| Status | Meaning | Trigger |
|---|---|---|
| `verified` | Checked out | single source / spread within floor / difference explained by closed-cup vs open-cup |
| `conflict` | Sources genuinely disagree | spread exceeds the floor **and** it is not a cup-type difference — a human must review; every value is listed |
| `unverified` | Nothing to check | no sourced value exists — reported as absence, never invented |

Per-property conflict floors keep normal source-to-source variation from being flagged:
mp ±3 °C, bp ±2 °C, flash point ±1.5 °C, autoignition ±20 °C, density ±0.01 g/cm³;
everything else uses a 10% relative threshold. Closed-cup (c.c.) vs open-cup (o.c.)
differences are recognised and do not count as conflicts.

### 3.2 Property slugs (CLI, mapped to PubChem PUG View headings)

| slug | PUG View heading |
|---|---|
| `flash-point` / `flash` | Flash Point |
| `boiling-point` / `boiling` / `bp` | Boiling Point |
| `melting-point` / `melting` / `mp` | Melting Point |
| `density` | Density |
| `solubility` | Solubility |
| `vapor-pressure` | Vapor Pressure |
| `autoignition-point` | Autoignition Point |
| `explosive-limits` | Explosive Limits |
| `surface-tension` | Surface Tension |
| `viscosity` | Viscosity |
| `molecular-weight` / `mw` | MolecularWeight (via PUG REST identity) |
| `formula` | MolecularFormula (via PUG REST identity) |

### 3.3 Exit codes (for scripts)

| Command | Exit codes |
|---|---|
| `resolve` | 0 = success |
| `verify` | 0 = CONFIRMED, 1 = MISMATCH / NOT_FOUND |
| `crosscheck` | 0 = VERIFIED / UNVERIFIED, 2 = CONFLICT |
| `lookup` / `card` / `alias` / `cache` / `export` | 0 = success |
| `zhname` / `manual` | 0 = success (entry found/changed), 1 = not curated |

---

## 4. Commands, one by one (feature + how-to + real output)

> All outputs below were produced on the §0 snapshot. Each carries a **how to verify** note.

### 4.1 `resolve` — identifier → identity

```
$ chemfacts resolve NMP
pinned via alias: NMP -> 872-50-4  # N-methyl-2-pyrrolidone (solvent)
identity        : N-methyl-2-pyrrolidone
CID             : 13387
CAS             : 872-50-4
IUPAC           : 1-methylpyrrolidin-2-one
Formula         : C5H9NO
MW              : 99.13 g/mol
SMILES          : CN1CCCC1=O
InChIKey        : SECXISVLQFMRJM-UHFFFAOYSA-N
Accessed        : 2026-10-20 13:30:02Z  source: pubchem
```

**How to verify:** open <https://pubchem.ncbi.nlm.nih.gov/compound/13387> — formula
C5H9NO, MW 99.13 and the InChIKey should match character for character. The
`pinned via alias` line shows NMP went through the registry pin (§4.7).

### 4.2 `lookup` — every sourced value of a property

```
$ chemfacts lookup NMP flash-point
204 °F                                                       | OSHA (ref #84, experimental) | 2026-10-20
204 °F (96 °C) (OPEN CUP)                                    | HSDB (ref #46, experimental) | 2026-10-20
204 °F (NTP, 1992)                                           | CAMEO (ref #9, experimental) | 2026-10-20
86 °C c.c.                                                   | ILO ICSC (ref #47, experimental) | 2026-10-20
96 °C                                                        | N-Methyl-2-pyrrolidone (ref #44, experimental) | 2026-10-20
```

**How to verify:** `ref #47` = the ILO ICSC card; its closed-cup flash point of 86 °C is
in the public ICSC database. `ref #46` = HSDB; `204 °F (96 °C) (OPEN CUP)` is the
open-cup value. Closed-cup 86 °C and open-cup 96 °C coexisting is exactly the
"cup difference is not a conflict" case from §3.1.

### 4.3 `verify` — hold a claimed value against every sourced value (the point of the tool)

Three real verdicts, one per outcome:

```
$ chemfacts verify NMP mw --claim 99.13      # CONFIRMED
verdict: CONFIRMED
detail : 1 sourced value(s) agree within 2%
closest: 99.13 g/mol (PubChem PUG REST (computed from formula))
match  : 99.13 g/mol (PubChem PUG REST (computed from formula))
(exit 0)

$ chemfacts verify NMP mw --claim 80         # MISMATCH
verdict: MISMATCH
detail : claim 80 not confirmed; closest sourced value: 99.13 g/mol (PubChem PUG REST (computed from formula))
closest: 99.13 g/mol (PubChem PUG REST (computed from formula))
(exit 1)

$ chemfacts verify NMP explosive-limits --claim "0.6-9.0"   # NOT_FOUND
verdict: NOT_FOUND
detail : no sourced value found for this property - claim stays unverified
(exit 1)
```

**How to verify:** the CONFIRMED case — MW 99.13 is computed by PubChem PUG REST from the
formula C5H9NO (C 5×12.011 + H 9×1.008 + N 14.007 + O 15.999 ≈ 99.13); it is marked
`computed from formula`, not an experimental measurement. Recompute it yourself to check.
The NOT_FOUND case is deliberate: NMP has no sourced explosive-limits value, so the tool
reports absence instead of inventing one.

### 4.4 `crosscheck` — compare all sourced values of a property, get the status

One real example per status:

```
$ chemfacts crosscheck NMP        # VERIFIED (cup difference recognised, not a conflict)
status: VERIFIED
204 °F               | OSHA (ref #84)
204 °F (96 °C) (OPEN CUP) | HSDB (ref #46)
204 °F (NTP, 1992)   | CAMEO (ref #9)
86 °C c.c.           | ILO ICSC (ref #47)
96 °C                | N-Methyl-2-pyrrolidone (ref #44)
(exit 0)

$ chemfacts crosscheck TDI_24     # CONFLICT (values genuinely disagree; each is listed)
status: CONFLICT
127 °C               | Toluene-2,4-diisocyanate (ref #36)
127 °C c.c.          | ILO ICSC (ref #43)
260 °F               | NIOSH (ref #73)
260 °F (127 °C)      | HSDB (ref #39)
270 °F (EPA, 1998)   | CAMEO (ref #6)
270 °F for an 80/20% 2,4/ 2,6 TDI mixture | OSHA (ref #59)
(exit 2)

$ chemfacts crosscheck IBOA       # UNVERIFIED (no sourced value; absence reported, not filled in)
status: UNVERIFIED
(exit 0)
```

**How to verify the TDI_24 CONFLICT:** the last two entries put 270 °F (≈132 °C) next to
127 °C (≈260 °F), and the OSHA entry explicitly says "for an 80/20% 2,4/2,6 TDI mixture"
— the sources use different material bases (pure 2,4-TDI vs industrial mixture), so the
tool flags a **real conflict**, not a cup-type difference, and lists every value for you
to judge. That is the "show the evidence, don't decide for you" design.

### 4.5 `card` — build an auditable fact card

Formats: `md` (default), `obsidian` (with frontmatter), `json`. Options: `--out file`,
`--properties a,b,c`.

`md` (NMP, abridged to the provenance-bearing lines):

```
# N-methyl-2-pyrrolidone (C5H9NO)
- Aliases (registry-pinned): NMP
- IUPAC: 1-methylpyrrolidin-2-one
- Formula: `C5H9NO` | MW: 99.13 g/mol
- CAS: 872-50-4 | CID: 13387

## Properties (status: verified)
### Flash Point
- 204 °F — OSHA (ref #84, accessed 2026-10-20)
- 204 °F (96 °C) (OPEN CUP) — HSDB (ref #46, accessed 2026-10-20)
- 86 °C c.c. — ILO ICSC (ref #47, accessed 2026-10-20)

## Notes
- abbreviation pinned via registry: NMP -> 872-50-4 (N-methyl-2-pyrrolidone (solvent))
```

`obsidian` frontmatter (drops straight into an Obsidian vault):

```
---
name: "N-methyl-2-pyrrolidone"
cas: 872-50-4
cid: 13387
status: verified
accessed: 2026-10-20
aliases: ["NMP"]
---
```

`json` (DMPA — note `status: unverified` + the absence note, a "report absence, don't
invent" sample):

```
{
  "identity": { "cid": 78501, "name": "Dimethylolpropionic acid",
    "cas": "4767-03-7", "formula": "C5H10O4", "molecular_weight": 134.13,
    "accessed_at": "2026-10-20 16:36:36Z", "source": "pubchem" },
  "status": "unverified",
  "aliases": ["DMPA"],
  "notes": [ "no sourced value found for: Flash Point, Boiling Point, Melting Point, Density" ],
  "properties": { "Flash Point": [], "Boiling Point": [], ... }
}
```

**How to verify:** every `ref #` on a card traces back as in §4.2; the `status` follows the
§4.4 rules. `--out` writes the card to a file (e.g. your Obsidian vault).

### 4.6 `cache` — manage the local retrieval database

```
$ chemfacts cache show
identity   14
value      224
ref        1227
```

`cache clear` drops the whole cache; the next lookup re-fetches from PubChem and the
`accessed` dates refresh. **Verification lever:** `cache clear`, re-run §4.2/§4.4 — the
values, sources and reference numbers should be unchanged; only the dates move.

### 4.7 `alias` — pin ambiguous abbreviations to one compound

The registry stores only the small, stable, unambiguous part: the abbreviation, its pinned
CAS, and a note recording *why* this compound and which were excluded. Plain JSON
(default `~/.cache/chemfacts/aliases.json`, override with `CHEMFACTS_ALIASES`); commit it
to version control.

Real session (temporary entry, removed afterwards):

```
$ chemfacts alias add XYZ123 100-00-0 --note "manual-doc test pin (temporary)"
pinned XYZ123 -> 100-00-0 (2026-10-21)

$ chemfacts alias show XYZ123
alias     : XYZ123
pinned to : 100-00-0
note      : manual-doc test pin (temporary)
added     : 2026-10-21

$ chemfacts alias remove XYZ123
removed XYZ123
```

The 13 pinned entries (real `alias list` output, abridged):

```
DMPA       -> 4767-03-7  # dimethylolpropionic acid, ... (NOT 1,4-dimethylpiperazine / TMEDA)
H12MDI     -> 5124-30-1  # hydrogenated MDI / 4,4'-dicyclohexylmethane diisocyanate
                        #  (NOT 1,12-diisocyanatododecane 13879-35-1)
IBOA       -> 5888-33-5  # isobornyl acrylate C13H20O2, MW 208.30
                        #  (NOT the C13H22O2 / 210.32 mis-memory)
NMP        -> 872-50-4   # N-methyl-2-pyrrolidone (solvent)
```

**How to verify:** the `NOT …` notes are the exclusion evidence — H12MDI is pinned to
hydrogenated MDI (5124-30-1) and explicitly excludes 1,12-diisocyanatododecane
(13879-35-1). Search both CAS numbers in PubChem: different formula/MW, which is exactly
why the pin matters.

### 4.8 `export` — the correspondence table (abbreviation | Chinese | English | properties)

One command builds the master correspondence table for a list of subjects:
abbreviation → Chinese name → English name → IUPAC → CAS → CID → formula → MW →
melting / boiling / flash point / density, each property carrying its source list.

- **Online-first:** an empty or stale local database is no obstacle — every row is
  answered by pulling PubChem (the cache is only a TTL accelerator, not the source
  of truth). `--fresh` forces a live pull for this run.
- **Curation columns are fail-closed:** the abbreviation and Chinese-name cells come
  from your registries only (`aliases.json` + `zhnames.json`). A missing curation is
  an empty cell, never a guess.
- Unresolvable subjects are reported as `(unresolved: …)` rows, not dropped.

Real run (15 rows shown as 1 row, THF):

```
$ chemfacts export tetrahydrofuran --format md
| 缩写 | 中文名 | 英文名 | IUPAC | CAS | CID | 分子式 | 分子量 | … | 熔点 | … |
|  | 四氢呋喃 | Tetrahydrofuran | oxolane | 109-99-9 | 8028 | C4H8O | 72.11 g/mol | … | -108.3 °C ; … | … |
```

```
# whole registry + named subjects, CSV to a file, live pull:
chemfacts export --all-aliases tetrahydrofuran "4,4'-diphenylmethanediisocyanate" \
    --format csv --out map.csv --fresh
```

### 4.9 `zhname` — curate Chinese names (PubChem has none; this tool never invents any)

`zhnames.json` (default `~/.cache/chemfacts/zhnames.json`, override with
`CHEMFACTS_ZHNAMES`) holds user-verified Chinese names, keyed by CAS (preferred) or
CID — the same identifier space as `aliases.json`, so the two files agree on "which
compound". A name/abbreviation input to `add` is resolved through PubChem first and
stored under its CAS, with the source of your verification recorded.

```
$ chemfacts zhname add THF 四氢呋喃 --source "通用名 (common name)"
curated 109-99-9 -> 四氢呋喃 (2026-10-21) [resolved to Tetrahydrofuran (109-99-9)]

$ chemfacts zhname show THF
identifier : 109-99-9
name_zh    : 四氢呋喃
source     : 通用名 (common name)

$ chemfacts zhname list
109-99-9           四氢呋喃  # 来源: 通用名 (common name)
```

The curation surfaces in `resolve` output, fact cards (Obsidian/MD/JSON), MCP tool
payloads (`name_zh`, `name_zh_source`, `registered_abbrevs`), and the `export` table's
中文名列 (Chinese-name column). A compound without a curation shows an empty cell —
missing = missing, not guessed.

### 4.10 `mcp` — let any MCP-capable agent use chemfacts

Exposes the six capabilities as MCP tools, so Claude Code, Codex, ZCode, Hermes or any
agent harness can verify chemical facts by provenance instead of by model memory. Two
transports: `stdio` (agent spawns it locally) and `streamable-http` (Docker / multi-client
share one retrieval DB).

Real tool list (from an MCP client's `list_tools`):

```
chemfacts_resolve, chemfacts_lookup, chemfacts_crosscheck,
chemfacts_verify, chemfacts_card, chemfacts_alias
```

A real tool call (structured JSON with provenance):

```
$ chemfacts_verify('NMP', 'flash-point', '96 C')
{
  "ok": true, "property": "Flash Point", "claim": "96 C", "verdict": "confirmed",
  "detail": "1 sourced value(s) agree within 2%",
  "closest": { "value": "96 °C", "source": "N-Methyl-2-pyrrolidone",
               "reference_number": 44, "kind": "experimental",
               "accessed_at": "2026-10-20 13:30:03Z" }
}
```

Registration (syntax varies per agent; the command is always `chemfacts-mcp`, default
stdio):

```bash
# Claude Code
claude mcp add chemfacts -- chemfacts-mcp
# shared service (Docker + streamable-HTTP, one deployment for all agents)
docker build -t chemfacts-mcp .
docker run -d -p 8000:8000 -v chemfacts-data:/data chemfacts-mcp
# every agent points at http://<host>:8000/mcp ; the /data volume IS the shared
# retrieval database (facts.db + aliases.json)
```

**Local-proxy gotcha:** if the host runs a global HTTP proxy, set
`NO_PROXY=127.0.0.1,localhost` so agent↔server localhost traffic isn't routed through it.

### 4.11 `manual` — record substances PubChem does not carry (polymers, blends, vendor grades)

PubChem has no single-compound record for polymers (PTMEG/PTMG-2000), mixtures
(TDI 80/20) or vendor grades — they come back `(unresolved: …)` from every query,
which is the correct, honest answer. If you have the values from a primary document
(supplier COA, SDS, internal spec sheet), record them once and the `export` table
picks them up:

```
$ chemfacts manual add PTMG-2000 \
    --name-en "Polytetramethylene glycol (PTMEG-2000)" \
    --cas "25268-40-0" --mw "2000 (COA)" --note "supplier COA, lot 2026-08"
recorded PTMG-2000 (2026-10-21); verify values against supplier COA, lot 2026-08

$ chemfacts manual list
PTMG-2000      Polytetramethylene glycol (PTMEG-2000) · CAS 25268-40-0 · 2000 (COA)  # 出处: supplier COA, lot 2026-08
```

Three rules keep this honest:

- **Verbatim, user-owned values.** Entries are stored exactly as recorded
  (`manuals.json`, default `~/.cache/chemfacts/manuals.json`, override with
  `CHEMFACTS_MANUALS`); the tool never fills in, rounds or "fixes" anything.
- **Always marked.** In `export` output the English-name cell carries
  `（人工条目 · 无 PubChem 记录）` and the MW source says
  `user-curated entry (manuals.json) — no PubChem record`; property cells stay
  empty unless you recorded them. A manual row can never be read back as a database value.
- **No entry, no row.** A subject with neither a PubChem record nor a manual entry
  still shows as `(unresolved: …)`.

---

## 5. Verifiable evidence: tracing every number to its primary source

This is the line between this manual and "what the model recited". Every chemfacts output
carries **four elements** that let you check a number without this tool:

| Element | Where | Use |
|---|---|---|
| Source name | after each value: `OSHA / HSDB / CAMEO / ILO ICSC / NIOSH / EPA` | who measured / who compiled it |
| Reference number | `ref #46` etc. | the concrete entry in PubChem's reference list for that compound |
| Access date | `accessed 2026-10-20` | when the snapshot was taken |
| Kind | `experimental` / `computed` | measured or derived from the formula |

**Three independent verification paths:**

1. **Via the PubChem reference number.** Open the CID page from `resolve` (NMP = 13387)
   → "Experimental Properties" → the property lists its sources; the `ref #` is the
   entry number in that reference list. If source name and `ref #` line up, it checks out.
2. **Via the primary database.** `ILO ICSC` = the ILO chemical safety cards (public,
   searchable by CAS/name); `HSDB` = the NLM Hazardous Substances Data Bank; NIOSH /
   OSHA / CAMEO each have public pages. The card's values should be findable there.
3. **Via cache replay.** `cache show` for the snapshot size → `cache clear` → re-run the
   same command → values/sources/reference numbers should be identical, only the
   `accessed` dates change. Identical means the data reproduces.

**Honest boundaries of verifiability:**
- `computed` values (e.g. MW from the formula) are not measurements — verify by
  recomputing from the formula, not by finding a lab record.
- A `conflict` is not "wrong"; it means the sources genuinely disagree. The tool lists
  every value for you to judge; it does not decide for you.
- `unverified` / NOT_FOUND means "no public sourced data exists". No claim is treated as
  verified because of that — by design, not by failure.

---

## 6. Common workflows

**A. Safety check of a solvent before a reaction (flash point / autoignition)**
```
chemfacts lookup NMP flash-point          # see every sourced value
chemfacts verify NMP autoignition-point --claim 253   # check the number on your note
```
Report flash point per cup type; write the safety assessment only from `confirmed`.

**B. Verify a paper's cited value before citing it**
```
chemfacts verify <compound> <property> --claim <the paper's number>
```
`CONFIRMED` → cite. `MISMATCH` → look at `closest` and correct. `NOT_FOUND` → the number
has no public sourced support; cite cautiously.

**C. Meet a new ambiguous abbreviation: pin it, then use it**
```
chemfacts alias add <ABBR> <CAS> --note "why this one, what was excluded"
chemfacts resolve <ABBR>        # every later lookup follows the pin
```

**D. Archive a full fact card into Obsidian**
```
chemfacts card <compound> --format obsidian --out "<vault>/chemical-facts/<name>.md"
```

**E. Let an agent verify chemical facts by provenance**
Register the MCP server per §4.8; the agent calls `chemfacts_verify` etc. and gets
sourced JSON back instead of model memory.

---

## 7. FAQ / gotchas

- **A value looks wrong?** Check `experimental` vs `computed`, closed-cup vs open-cup,
  and the `ref #`'s primary source. The tool lists every value; the judgment is yours.
- **CONFLICT?** Not an error. Read each `ref #` and source basis (pure vs mixture,
  different test methods), pick the trustworthy value, note it in the alias registry.
- **Can UNVERIFIED / NOT_FOUND be "filled in"?** No. No public source, no number. Go to
  the primary database yourself; the tool will not invent one.
- **Cache stale?** 30-day TTL by default; `cache clear` for a fresh pull.
- **Local MCP won't connect / "Server returned an error"?** Usually the global HTTP proxy
  is hijacking 127.0.0.1: set `NO_PROXY=127.0.0.1,localhost`.
- **Pinned the wrong compound?** `alias show` → `alias remove` → `alias add` with the
  right CAS.

---

## Appendix: division of labour with the READMEs

- "Why is it designed this way" (architecture, status logic, alias disambiguation) →
  [README](../README.md) / [README_zh](../README_zh.md).
- "Pick it up and use it" → this manual.
- §0/§5 guarantee: every number you see here can be replayed and traced to a primary source.
