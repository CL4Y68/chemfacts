"""Core data model for chemfacts.

Every value carries provenance: who it came from (source), when we accessed it,
and whether it is an experimental or computed quantity.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%SZ")


@dataclass
class CompoundIdentity:
    """What a compound *is* — stable identifiers, not properties."""

    identifier: str  # the input the user gave (name/CAS/SMILES/CID)
    cid: int | None = None
    name: str | None = None
    iupac_name: str | None = None
    cas: str | None = None
    formula: str | None = None
    molecular_weight: float | None = None
    canonical_smiles: str | None = None
    isomeric_smiles: str | None = None
    inchi: str | None = None
    inchi_key: str | None = None
    title: str | None = None
    accessed_at: str = field(default_factory=_now)
    source: str = "pubchem"


@dataclass
class PropertyValue:
    """One value of one property, with full provenance."""

    property_name: str  # PUG View heading, e.g. "Flash Point"
    value: str  # raw string as published, e.g. "134 deg C (closed cup)"
    reference_number: int
    source_name: str
    kind: str = "experimental"  # experimental | computed | registry
    accessed_at: str = field(default_factory=_now)
    url: str | None = None

    def numeric(self) -> float | None:
        """Best-effort first numeric component, else None. For cross-checking."""
        import re

        m = re.search(r"-?\d+(?:\.\d+)?", self.value)
        return float(m.group(0)) if m else None


@dataclass
class FactCard:
    identity: CompoundIdentity
    properties: dict[str, list[PropertyValue]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    status: str = "verified"  # verified | unverified | conflict
    accessed_at: str = field(default_factory=_now)
    aliases: list[str] = field(default_factory=list)  # registered abbreviations pinned here
    name_zh: str = ""  # curated Chinese name (registry only; empty = not curated, never guessed)
    name_zh_source: str = ""  # where the user verified the Chinese name


@dataclass
class VerifyResult:
    claimed_property: str
    claimed_value: str
    found: bool
    matches: list[PropertyValue]
    closest: PropertyValue | None
    verdict: str  # confirmed | mismatch | not_found
    detail: str = ""
