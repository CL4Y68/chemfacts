"""High-level API: resolve -> lookup -> crosscheck -> verify -> card.

The single rule this module enforces: **a fact that cannot be sourced is not
reported.** Functions return explicit `not_found` results instead of
fabricating plausible values.
"""

from __future__ import annotations

import json
import re

from .aliases import AliasRegistry
from .cache import FactCache
from .manuals import ManualRegistry
from .model import CompoundIdentity, FactCard, PropertyValue, VerifyResult
from .pubchem import PubChemClient, PubChemError
from .zhnames import ZhNameRegistry

# CLI slugs -> PUG View headings
PROPERTY_ALIASES = {
    "flash-point": "Flash Point",
    "flash": "Flash Point",
    "boiling-point": "Boiling Point",
    "boiling": "Boiling Point",
    "bp": "Boiling Point",
    "melting-point": "Melting Point",
    "melting": "Melting Point",
    "mp": "Melting Point",
    "density": "Density",
    "solubility": "Solubility",
    "vapor-pressure": "Vapor Pressure",
    "autoignition-point": "Autoignition Point",
    "explosive-limits": "Explosive Limits",
    "surface-tension": "Surface Tension",
    "viscosity": "Viscosity",
    "molecular-weight": "MolecularWeight",
    "mw": "MolecularWeight",
    "formula": "MolecularFormula",
}

# properties that live in PUG REST identity, not in PUG View headings
_IDENTITY_SOURCES = {
    "MolecularWeight": ("molecular_weight", "PubChem PUG REST (computed from formula)"),
    "MolecularFormula": ("formula", "PubChem PUG REST"),
}

DEFAULT_CARD_PROPERTIES = [
    "Flash Point",
    "Boiling Point",
    "Melting Point",
    "Density",
]


def _heading(slug_or_heading: str) -> str:
    return PROPERTY_ALIASES.get(slug_or_heading.strip().lower(), slug_or_heading.strip())


class ChemFacts:
    """Facade over PubChemClient + FactCache."""

    def __init__(
        self,
        client: PubChemClient | None = None,
        cache: FactCache | None = None,
        ttl_days: int = 30,
        aliases: AliasRegistry | None = None,
        zhnames: ZhNameRegistry | None = None,
        manuals: ManualRegistry | None = None,
    ):
        self.client = client or PubChemClient()
        self.cache = cache or FactCache()
        self.ttl_days = ttl_days
        self.aliases = aliases or AliasRegistry()
        self.zhnames = zhnames or ZhNameRegistry()
        self.manuals = manuals or ManualRegistry()

    # -- identity -----------------------------------------------------------

    def resolve(self, identifier: str, use_cache: bool = True) -> CompoundIdentity:
        """Resolve an identifier to a CompoundIdentity (cached with TTL).

        Registered aliases (the abbreviation registry) are resolved first:
        "DMPA" -> pinned CAS -> compound identity, so ambiguous abbreviations
        never guess. The returned identity keeps the original input string
        (the alias) in `.identifier` for the audit trail.
        """
        pinned = self.aliases.pin(identifier)
        if use_cache:
            cached = (
                self.cache.get_identity_by_identifier(pinned)
                or self.cache.get_identity_by_identifier(identifier)
            )
            if cached and self.cache.is_fresh(cached.accessed_at, self.ttl_days):
                cached.identifier = identifier
                return cached
        ident = self.client.identity(pinned)
        ident.identifier = identifier  # keep the original input (alias) visible
        if ident.cid:
            self.cache.save_identity(ident)
        return ident

    # -- properties ---------------------------------------------------------

    def lookup(
        self, identifier: str, property_slug: str, use_cache: bool = True
    ) -> list[PropertyValue]:
        """All published values for one property, with provenance."""
        heading = _heading(property_slug)
        ident = self.resolve(identifier)
        if not ident.cid:
            return []
        if heading in _IDENTITY_SOURCES:
            attr, source = _IDENTITY_SOURCES[heading]
            raw = getattr(ident, attr)
            if raw is None:
                return []
            value = f"{raw} g/mol" if attr == "molecular_weight" else str(raw)
            return [
                PropertyValue(
                    property_name=heading,
                    value=value,
                    reference_number=0,
                    source_name=source,
                    kind="computed" if attr == "molecular_weight" else "registry",
                    accessed_at=ident.accessed_at,
                    url=f"https://pubchem.ncbi.nlm.nih.gov/compound/{ident.cid}",
                )
            ]
        if use_cache:
            cached = self.cache.get_values(ident.cid, heading)
            if cached and all(self.cache.is_fresh(v.accessed_at, self.ttl_days) for v in cached):
                # keep provenance names fresh from cache when possible
                refs = self.cache.get_refs(ident.cid)
                for v in cached:
                    if not v.source_name:
                        v.source_name = refs.get(
                            v.reference_number, f"reference #{v.reference_number}"
                        )
                return cached
        values = self.client.property_values(ident.cid, heading)
        if values:
            self.cache.save_values(ident.cid, values)
            # refresh reference map
            try:
                data = self.client._get_json(  # noqa: SLF001 - same module family
                    f"https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/{ident.cid}/JSON"
                )
                refs = self.client._reference_map(ident.cid, data)  # noqa: SLF001
                self.cache.save_refs(ident.cid, refs)
            except PubChemError:
                pass
        return values

    # -- cross-check --------------------------------------------------------

    def crosscheck(self, identifier: str, property_slug: str) -> tuple[list[PropertyValue], str]:
        """Return (values, status) where status in {verified, conflict, unverified}."""
        values = self.lookup(identifier, property_slug)
        if not values:
            return values, "unverified"
        heading = _heading(property_slug)
        numeric = [
            _comparable(v.value, heading)
            for v in values
            if _comparable(v.value, heading) is not None
        ]
        if len(numeric) >= 2:
            spread = max(numeric) - min(numeric)
            # meaningfully different numbers -> flag conflict.
            # Temperature properties use a fixed absolute floor (a 10% relative
            # threshold would swallow a 5 degC flash-point gap at 130 degC);
            # other properties keep a scale-relative threshold.
            if heading in _CONFLICT_FLOORS:
                threshold = _CONFLICT_FLOORS[heading]
            else:
                scale = max(abs(min(numeric)), abs(max(numeric)), 1.0)
                threshold = 0.10 * scale
            if spread > threshold:
                # distinguish closed-cup vs open-cup style condition differences
                text = " ".join(v.value.lower() for v in values)
                cup_closed = "closed cup" in text or "c.c." in text or "c.c" in text
                cup_open = "open cup" in text or "o.c." in text or "o.c" in text
                if cup_closed and cup_open:
                    return values, "verified"
                return values, "conflict"
        return values, "verified"

    # -- verify a claim -----------------------------------------------------

    def verify(
        self,
        identifier: str,
        property_slug: str,
        claimed_value: str,
        tolerance: float = 0.02,
    ) -> VerifyResult:
        """Check a claimed value against every sourced value we can find."""
        heading = _heading(property_slug)
        values = self.lookup(identifier, property_slug)
        claimed = _first_number(claimed_value)
        if not values or claimed is None:
            return VerifyResult(
                claimed_property=heading,
                claimed_value=claimed_value,
                found=bool(values),
                matches=[],
                closest=None,
                verdict="not_found",
                detail="no sourced value found for this property - claim stays unverified",
            )
        scored = []
        for v in values:
            n = v.numeric()
            if n is None:
                continue
            scored.append((abs(n - claimed) / max(abs(claimed), 1e-9), v))
        if not scored:
            return VerifyResult(
                claimed_property=heading,
                claimed_value=claimed_value,
                found=True,
                matches=values,
                closest=None,
                verdict="not_found",
                detail="values exist but none are numeric",
            )
        scored.sort(key=lambda x: x[0])
        rel_diff, closest = scored[0]
        matches = [
            v for v in values
            if (
                v.numeric() is not None
                and abs(v.numeric() - claimed) / max(abs(claimed), 1e-9) <= tolerance
            )
        ]
        if matches:
            verdict = "confirmed"
            detail = f"{len(matches)} sourced value(s) agree within {tolerance:.0%}"
        else:
            verdict = "mismatch"
            detail = (
                f"claim {claimed_value} not confirmed; closest sourced value: "
                f"{closest.value} ({closest.source_name})"
            )
        return VerifyResult(
            claimed_property=heading,
            claimed_value=claimed_value,
            found=True,
            matches=matches,
            closest=closest,
            verdict=verdict,
            detail=detail,
        )

    # -- card ---------------------------------------------------------------

    def build_card(
        self, identifier: str, properties: list[str] | None = None
    ) -> FactCard:
        """Assemble a FactCard for one compound: identity + requested properties."""
        ident = self.resolve(identifier)
        props = properties or DEFAULT_CARD_PROPERTIES
        card = FactCard(identity=ident)
        entry = self.aliases.get(identifier)
        if entry is not None:
            card.aliases.append(entry.alias)
            note = f"abbreviation pinned via registry: {entry.alias} -> {entry.identifier}"
            if entry.note:
                note += f" ({entry.note})"
            card.notes.append(note)
        # reverse direction: every registered abbreviation pinned to this
        # compound (CAS match), so "compound -> common abbreviations" is
        # answered from the registry, never invented
        if ident.cas:
            reverse = [e.alias for e in self.aliases.aliases_for(ident.cas)]
            for a in reverse:
                if a not in card.aliases:
                    card.aliases.append(a)
        # curated Chinese name (registry only; missing = empty, never guessed)
        zh = self.zhnames.find(ident.cas, ident.cid)
        if zh is not None:
            card.name_zh = zh.name_zh
            card.name_zh_source = zh.source
            note = f"中文名: {zh.name_zh}"
            if zh.source:
                note += f"（来源: {zh.source}）"
            card.notes.append(note)
        statuses = []
        for slug in props:
            values, status = self.crosscheck(identifier, slug)
            heading = _heading(slug)
            card.properties[heading] = values
            statuses.append(status)
        if "conflict" in statuses:
            card.status = "conflict"
        elif all(v for v in card.properties.values()) or not any(card.properties.values()):
            card.status = "verified" if "unverified" not in statuses else "unverified"
        else:
            card.status = "unverified"
        # missing-property note (honesty by default)
        empty = [h for h, vs in card.properties.items() if not vs]
        if empty:
            card.notes.append(f"no sourced value found for: {', '.join(empty)}")
        return card


def _first_number(s: str) -> float | None:
    """The numeric part of a value string.

    For colon-formatted entries (ICSC "Relative density (water = 1): 1.03")
    the number after the last colon is taken, so the "1" in "water = 1"
    is never returned.
    """
    text = s.strip()
    if ":" in text:
        m = re.search(r"[-+]?\d+(?:\.\d+)?", text.rsplit(":", 1)[1])
        if m:
            return float(m.group(0))
    m = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    return float(m.group(0)) if m else None


_TEMP_SLUGS = {"Flash Point", "Boiling Point", "Melting Point", "Autoignition Point"}

# absolute spread below which sources are considered in agreement
# (below these, differences are normal source/purity variation, not a conflict)
_CONFLICT_FLOORS = {
    "Melting Point": 3.0,
    "Boiling Point": 2.0,
    "Flash Point": 1.5,
    "Autoignition Point": 20.0,
    "Density": 0.01,
}

# values carrying these qualifiers are ranges / estimates, not comparable point values
_QUALIFIERS = (
    "greater than",
    "less than",
    "above",
    "below",
    "approximately",
    "approx.",
    "estimated",
    "calculated",
    "computed",
    "predicted",
    "varies",
)


def _comparable(value_str: str, heading: str) -> float | None:
    """A value usable for cross-source numeric comparison, else None.

    Drops: qualified values ("greater than 200", "approximately -60"),
    computed values, and pressure-conditional values that are not
    atmospheric (e.g. "121 °C at 9 mm Hg" vs "213 °C" at 760 mmHg).
    """
    low = value_str.lower()
    for q in _QUALIFIERS:
        if q in low:
            return None
    in_pressure = re.search(r"\d+(?:\.\d+)?\s*(?:mm\s*hg|torr|kpa)", low)
    if in_pressure and "760" not in low and "atm" not in low:
        return None
    return _to_celsius(value_str, heading)


def _to_celsius(value_str: str, heading: str) -> float | None:
    """Normalize a temperature value to Celsius (°F strings are converted).

    Returns None for non-temperature properties or non-numeric strings.
    """
    n = _first_number(value_str)
    if n is None:
        return None
    if heading not in _TEMP_SLUGS:
        return n
    low = value_str.lower()
    if "°f" in low or low.startswith("f") or "deg f" in low:
        return (n - 32.0) * 5.0 / 9.0
    return n


# -- renderers ---------------------------------------------------------------

_OBSIDIAN_GROUPS = (
    ("基础", ("Density", "MolecularWeight", "MolecularFormula")),
    ("相变（实测）", ("Boiling Point", "Melting Point")),
    ("安全", ("Flash Point", "Autoignition Point", "Explosive Limits")),
)


def _property_lines(values: list[PropertyValue], language: str = "zh") -> list[str]:
    lines: list[str] = []
    if language == "zh":
        missing = "未能查证（查不到，不编）"
    else:
        missing = "not verified (no sourced value found)"
    if not values:
        lines.append(f"- {missing}")
        return lines
    for v in values:
        kind_tag = f" [{v.kind}]" if v.kind == "computed" else ""
        tag = f"{v.source_name}" if v.source_name else "unknown source"
        lines.append(
            f"- {v.value}{kind_tag} — {tag} (ref #{v.reference_number}, "
            f"accessed {v.accessed_at[:10]})"
        )
    return lines


def card_to_markdown(card: FactCard, obsidian: bool = False) -> str:
    """Render a FactCard as Markdown.

    ``obsidian=False``: plain English card (open-source default, language-neutral).
    ``obsidian=True``: bilingual YAML frontmatter + Chinese vault layout
    (基础 / 相变 / 安全), matching the researcher's Obsidian fact library.
    """
    i = card.identity
    lines: list[str] = []
    if obsidian:
        frontmatter = [
            "---",
            f'name: "{i.name or i.identifier}"',
            f"cas: {i.cas or 'unknown'}",
            f"cid: {i.cid or 'unknown'}",
            f"status: {card.status}",
            f"accessed: {i.accessed_at[:10]}",
        ]
        if card.aliases:
            frontmatter.append(f"aliases: {json.dumps(sorted(card.aliases), ensure_ascii=False)}")
        if card.name_zh:
            frontmatter.append(f'name_zh: "{card.name_zh}"')
        lines.extend(
            frontmatter
            + [
                "---",
                "",
                f"# {i.name or i.identifier}",
                "",
                f"- CAS: `{i.cas or '未能查证'}` | PubChem CID: {i.cid or '未能查证'}",
                f"- 查证日期: {i.accessed_at[:10]}",
                "",
                f"- IUPAC: {i.iupac_name or 'n/a'}",
                f"- 分子式: `{i.formula or 'n/a'}`",
                f"- MW: {i.molecular_weight if i.molecular_weight is not None else 'n/a'} g/mol",
                f"- SMILES: `{i.canonical_smiles or 'n/a'}`",
                "",
            ]
            + (
                [
                    f"- 中文名: {card.name_zh}"
                    + (
                        f"（来源: {card.name_zh_source}）"
                        if card.name_zh_source
                        else "（人工录入）"
                    ),
                    "",
                ]
                if card.name_zh
                else []
            )
        )
        for group, heads in _OBSIDIAN_GROUPS:
            lines.append(f"## {group}")
            lines.append("")
            if not any(card.properties.get(h) for h in heads):
                lines.append("- （本组无数据）")
                lines.append("")
                continue
            for h in heads:
                values = card.properties.get(h)
                if values is None:
                    continue
                lines.append(f"### {h}")
                lines.extend(_property_lines(values, "zh"))
                lines.append("")
        status_line = {
            "verified": "已核验 ✓",
            "conflict": "存在来源冲突（见上）",
            "unverified": "待复核",
        }
        lines.append("## 备注")
        for n in card.notes:
            lines.append(f"- {n}")
        lines.append(f"- 状态: {status_line.get(card.status, card.status)}")
        return "\n".join(lines)

    lines.append(f"# {i.name or i.identifier} ({i.formula or 'n/a'})")
    lines.append("")
    if card.aliases:
        lines.append(f"- Aliases (registry-pinned): {', '.join(sorted(card.aliases))}")
        lines.append("")
    lines.append(f"- IUPAC: {i.iupac_name or 'n/a'}")
    if card.name_zh:
        zh_line = f"- 中文名: {card.name_zh}"
        zh_line += (
            f"（来源: {card.name_zh_source}）" if card.name_zh_source else "（人工录入）"
        )
        lines.append(zh_line)
    mw_text = f"{i.molecular_weight} g/mol" if i.molecular_weight is not None else "n/a"
    lines.append(f"- Formula: `{i.formula or 'n/a'}` | MW: {mw_text}")
    lines.append(f"- SMILES: `{i.canonical_smiles or 'n/a'}`")
    lines.append(f"- CAS: {i.cas or 'n/a'} | CID: {i.cid or 'n/a'}")
    lines.append("")
    lines.append(f"## Properties (status: {card.status})")
    for heading, values in card.properties.items():
        lines.append("")
        lines.append(f"### {heading}")
        lines.extend(_property_lines(values, "en"))
    if card.notes:
        lines.append("")
        lines.append("## Notes")
        for n in card.notes:
            lines.append(f"- {n}")
    return "\n".join(lines)


def card_to_json(card: FactCard) -> str:
    i = card.identity
    payload = {
        "identity": i.__dict__,
        "name_zh": card.name_zh,
        "name_zh_source": card.name_zh_source,
        "status": card.status,
        "aliases": card.aliases,
        "notes": card.notes,
        "accessed_at": card.accessed_at,
        "properties": {
            h: [v.__dict__ for v in vals] for h, vals in card.properties.items()
        },
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


# -- export: correspondence table (abbreviation | Chinese name | English name | CAS | ...) ----

#: (slug, PUG View heading, human column label) pulled for each row
EXPORT_PROPERTIES = (
    ("melting-point", "Melting Point", "熔点"),
    ("boiling-point", "Boiling Point", "沸点"),
    ("flash-point", "Flash Point", "闪点"),
    ("density", "Density", "密度"),
)


def _dedup(seq: list[str]) -> list[str]:
    out: list[str] = []
    for s in seq:
        if s and s not in out:
            out.append(s)
    return out


def _value_cell(values: list[PropertyValue]) -> tuple[str, str]:
    """(compact value cell, source cell). Missing values stay 'no source found'."""
    if not values:
        return "(no source found)", ""
    shown = [v.value for v in values[:3]]
    cell = " ; ".join(shown)
    if len(values) > 3:
        cell += f" (+{len(values) - 3} more)"
    return cell, ", ".join(_dedup([v.source_name for v in values]))


def export_rows(
    facts: ChemFacts,
    subjects: list[str],
    fresh: bool = False,
) -> list[dict]:
    """Correspondence table: abbreviation | Chinese name | English name | CAS |
    CID | formula | MW | melting point | boiling point | flash point | density.

    Online-first: the local cache is only a TTL accelerator, not the source
    of truth — with an empty or stale DB every row is still answered by
    pulling PubChem (``fresh=True`` forces that pull for this run).

    Provenance discipline for every column:
    - curation columns (abbreviation, Chinese name) come from the user's
      registries only — never guessed; empty cell = not curated
    - property values are PubChem-sourced; a missing property is reported
      explicitly, never filled in
    - duplicate subjects (same CID) merge into one row with combined inputs
    """
    use_cache = not fresh
    rows: dict[object, dict] = {}
    order: list[object] = []

    for subject in subjects:
        try:
            ident = facts.resolve(subject, use_cache=use_cache)
        except PubChemError as e:
            m = facts.manuals.get(subject) or facts.manuals.by_cas(subject)
            if m is not None:
                # User-curated entry for a substance PubChem does not carry
                # (polymers, mixtures, vendor grades). Never masquerades as a
                # database value: the row is flagged manual and its source
                # column says so.
                key = f"manual:{m.identifier}"
                if key in rows:
                    if subject not in rows[key]["inputs"]:
                        rows[key]["inputs"].append(subject)
                    continue
                row = {
                    "input": subject,
                    "inputs": [subject],
                    "unresolved": False,
                    "manual": True,
                    "manual_label": m.identifier,
                    "name_en": m.name_en or m.identifier,
                    "iupac": "",
                    "cas": m.cas,
                    "cid": "",
                    "formula": m.formula,
                    "mw": m.mw,
                    "mw_source": "user-curated entry (manuals.json) — no PubChem record",
                    "note": m.note,
                    "added": m.added,
                    "unresolved_error": str(e),
                }
                row["abbrevs"] = []
                zh = facts.zhnames.find(m.cas or None, None)
                row["name_zh"] = zh.name_zh if zh else ""
                row["name_zh_source"] = (zh.source if zh else "")
                for slug, heading, _label in EXPORT_PROPERTIES:
                    row[slug] = ""
                    row[f"{slug}_source"] = ""
                    row.setdefault("properties", {})[heading] = []
                rows[key] = row
                if key not in order:
                    order.append(key)
                continue
            key = f"err:{subject}"
            row = {
                "input": subject,
                "unresolved": True,
                "error": str(e),
            }
            rows[key] = row
            if key not in order:
                order.append(key)
            continue

        # merge duplicates of the same compound into one row
        key = ident.cid if ident.cid is not None else (ident.name or subject)
        if key in rows and not rows[key].get("unresolved"):
            row = rows[key]
            if subject not in row["inputs"]:
                row["inputs"].append(subject)
            continue
        row: dict = {
            "input": subject,
            "inputs": [subject],
            "unresolved": False,
            "name_en": ident.name or ident.title or subject,
            "iupac": ident.iupac_name or "",
            "cas": ident.cas or "",
            "cid": ident.cid or "",
            "formula": ident.formula or "",
            "accessed_at": ident.accessed_at,
        }
        if ident.molecular_weight is not None:
            row["mw"] = f"{ident.molecular_weight} g/mol"
            row["mw_source"] = "PubChem PUG REST (computed from formula)"
        else:
            row["mw"] = ""
            row["mw_source"] = ""
        # curation columns: registries only, never invented
        if ident.cas:
            row["abbrevs"] = [e.alias for e in facts.aliases.aliases_for(ident.cas)]
        elif ident.cid is not None:
            row["abbrevs"] = [e.alias for e in facts.aliases.aliases_for(str(ident.cid))]
        else:
            row["abbrevs"] = []
        zh = facts.zhnames.find(ident.cas, ident.cid)
        row["name_zh"] = zh.name_zh if zh else ""
        row["name_zh_source"] = (zh.source if zh else "")
        for slug, heading, _label in EXPORT_PROPERTIES:
            values = facts.lookup(subject, slug, use_cache=use_cache)
            cell, sources = _value_cell(values)
            row[slug] = cell
            row[f"{slug}_source"] = sources
            row.setdefault("properties", {})[heading] = [
                {
                    "value": v.value,
                    "source": v.source_name,
                    "reference_number": v.reference_number,
                    "kind": v.kind,
                    "accessed_at": v.accessed_at,
                }
                for v in values
            ]
        rows[key] = row
        if key not in order:
            order.append(key)

    return [rows[k] for k in order]
