"""User-curated manual entries for substances PubChem does not carry.

PubChem has no single-compound record for polymers (PTMEG / PTMG-2000),
mixtures (TDI 80/20) and vendor grades, so they come back unresolved from
every PubChem query. This registry holds entries the user verified against a
primary document (supplier COA / SDS / internal spec sheet): a label plus
the values they recorded. The tool never invents any of it — a manual row
is only produced from a user entry, and is always marked
"user-curated entry (manuals.json)" at every exit, so it can never be read
back as a database value.

Same contract as the other registries: plain JSON, diff-able, committable;
env override CHEMFACTS_MANUALS; default ``<cache dir>/manuals.json``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def _default_path() -> Path:
    env = os.environ.get("CHEMFACTS_MANUALS")
    if env:
        return Path(env)
    cache_dir = os.environ.get("CHEMFACTS_CACHE_DIR", str(Path.home() / ".cache" / "chemfacts"))
    return Path(cache_dir) / "manuals.json"


@dataclass
class ManualEntry:
    """One user-verified substance with no PubChem record.

    `identifier` is the user's label (e.g. PTMG-2000, TDI_8020) — polymers
    have no single-cas of their own, so labels stay raw by design.
    All value fields are verbatim user input; display them as recorded and
    attribute them to the user, never to PubChem.
    """

    identifier: str  # normalized uppercase
    name_en: str = ""
    cas: str = ""
    formula: str = ""
    mw: str = ""  # verbatim, e.g. "2000 (COA)" or "1950-2050"
    note: str = ""  # where the values were verified
    added: str = ""  # ISO date


@dataclass
class ManualRegistry:
    """JSON-file backed manual-entry store. All lookups are case-insensitive."""

    path: Path = field(default_factory=_default_path)
    _entries: dict[str, ManualEntry] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._load()

    # -- persistence ----------------------------------------------------------

    def _load(self) -> None:
        self._entries = {}
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        for key, data in raw.items():
            self._entries[key.upper()] = ManualEntry(
                identifier=key.upper(),
                name_en=data.get("name_en", ""),
                cas=data.get("cas", ""),
                formula=data.get("formula", ""),
                mw=data.get("mw", ""),
                note=data.get("note", ""),
                added=data.get("added", ""),
            )

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            e.identifier: {
                "name_en": e.name_en,
                "cas": e.cas,
                "formula": e.formula,
                "mw": e.mw,
                "note": e.note,
                "added": e.added,
            }
            for e in sorted(self._entries.values(), key=lambda e: e.identifier)
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        self.path.write_text(text, encoding="utf-8")

    # -- api -------------------------------------------------------------------

    def get(self, identifier: str) -> ManualEntry | None:
        return self._entries.get(identifier.strip().upper())

    def by_cas(self, cas: str) -> ManualEntry | None:
        """Entry whose recorded CAS matches (polymers: user's best-known CAS)."""
        want = cas.strip()
        for e in self._entries.values():
            if e.cas and e.cas.strip() == want:
                return e
        return None

    def add(self, entry: ManualEntry) -> ManualEntry:
        self._entries[entry.identifier] = entry
        self._save()
        return entry

    def remove(self, identifier: str) -> bool:
        gone = self._entries.pop(identifier.strip().upper(), None)
        if gone is not None:
            self._save()
            return True
        return False

    def list(self) -> list[ManualEntry]:
        return sorted(self._entries.values(), key=lambda e: e.identifier)


def new_entry(
    identifier: str,
    name_en: str = "",
    cas: str = "",
    formula: str = "",
    mw: str = "",
    note: str = "",
) -> ManualEntry:
    return ManualEntry(
        identifier=identifier.strip().upper(),
        name_en=name_en.strip(),
        cas=cas.strip(),
        formula=formula.strip(),
        mw=mw.strip(),
        note=note.strip(),
        added=datetime.now(UTC).strftime("%Y-%m-%d"),
    )
