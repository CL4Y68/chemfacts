"""Abbreviation registry: pin ambiguous names (DMPA, IBOA, H12MDI, ...) to one compound.

Chemical abbreviations are ambiguous: DMPA is dimethylolpropionic acid *or*
1,4-dimethylpiperazine *or* TMEDA depending on the lab; H12MDI is hydrogenated
MDI *or* 1,12-diisocyanatododecane; BA is butyl acrylate. A registry entry pins
one abbreviation to a *unique* identifier (preferably CAS, which unambiguously
determines structure / name / InChIKey at resolution time), plus a human note
recording *why* this one was chosen.

The registry is a plain JSON file so users can edit, diff, and commit it next
to their fact-card vault.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def _default_path() -> Path:
    env = os.environ.get("CHEMFACTS_ALIASES")
    if env:
        return Path(env)
    cache_dir = os.environ.get("CHEMFACTS_CACHE_DIR", str(Path.home() / ".cache" / "chemfacts"))
    return Path(cache_dir) / "aliases.json"


@dataclass
class AliasEntry:
    """One abbreviation -> compound pin, with the reason in `note`."""

    alias: str  # normalized uppercase
    identifier: str  # pinned CAS / CID / IUPAC / SMILES (CAS preferred)
    note: str = ""  # disambiguation note (which compound, and which ones NOT)
    added: str = ""  # ISO date


@dataclass
class AliasRegistry:
    """JSON-file backed alias store. All lookups are case-insensitive."""

    path: Path = field(default_factory=_default_path)
    _entries: dict[str, AliasEntry] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._load()

    # -- persistence ----------------------------------------------------------

    def _load(self) -> None:
        self._entries = {}
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        for key, data in raw.items():
            self._entries[key.upper()] = AliasEntry(
                alias=key.upper(),
                identifier=data["identifier"],
                note=data.get("note", ""),
                added=data.get("added", ""),
            )

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            e.alias: {"identifier": e.identifier, "note": e.note, "added": e.added}
            for e in sorted(self._entries.values(), key=lambda e: e.alias)
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        self.path.write_text(text, encoding="utf-8")

    # -- api -------------------------------------------------------------------

    def get(self, alias: str) -> AliasEntry | None:
        return self._entries.get(alias.strip().upper())

    def add(self, alias: str, identifier: str, note: str = "") -> AliasEntry:
        entry = AliasEntry(
            alias=alias.strip().upper(),
            identifier=identifier.strip(),
            note=note.strip(),
            added=datetime.now(UTC).strftime("%Y-%m-%d"),
        )
        self._entries[entry.alias] = entry
        self._save()
        return entry

    def remove(self, alias: str) -> bool:
        gone = self._entries.pop(alias.strip().upper(), None)
        if gone is not None:
            self._save()
            return True
        return False

    def list(self) -> list[AliasEntry]:
        return sorted(self._entries.values(), key=lambda e: e.alias)

    def pin(self, identifier: str) -> str:
        """Return the pinned identifier for `identifier` if it is a registered
        alias, otherwise the input unchanged."""
        entry = self.get(identifier)
        return entry.identifier if entry is not None else identifier
