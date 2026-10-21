"""Chinese-name curation registry.

PubChem provides no Chinese names, so none are ever invented here. This
registry holds user-curated 中文名 entries, each carrying a source field
recording where the user verified the name (lab handbook, SDS, internal
nomenclature sheet, ...). A missing entry is reported as missing —
the tool never falls back to a model guess.

The registry is a plain JSON file so users can edit, diff, and commit it
next to their fact-card vault (same contract as aliases.json).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def _default_path() -> Path:
    env = os.environ.get("CHEMFACTS_ZHNAMES")
    if env:
        return Path(env)
    cache_dir = os.environ.get("CHEMFACTS_CACHE_DIR", str(Path.home() / ".cache" / "chemfacts"))
    return Path(cache_dir) / "zhnames.json"


@dataclass
class ZhNameEntry:
    """One curated Chinese name for a compound, keyed by its identifier.

    `identifier` is the CAS (preferred) or CID / IUPAC / SMILES — the same
    identifier space as the alias registry, so a CAS pin in aliases.json
    and a Chinese-name pin in this file agree on "which compound".
    """

    identifier: str  # normalized uppercase
    name_zh: str  # curated Chinese name, e.g. 四氢呋喃
    source: str = ""  # where the name was verified (manual curation only)
    added: str = ""  # ISO date


@dataclass
class ZhNameRegistry:
    """JSON-file backed Chinese-name store. All lookups are case-insensitive."""

    path: Path = field(default_factory=_default_path)
    _entries: dict[str, ZhNameEntry] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._load()

    # -- persistence ----------------------------------------------------------

    def _load(self) -> None:
        self._entries = {}
        if not self.path.exists():
            return
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        for key, data in raw.items():
            self._entries[key.upper()] = ZhNameEntry(
                identifier=key.upper(),
                name_zh=data["name_zh"],
                source=data.get("source", ""),
                added=data.get("added", ""),
            )

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            e.identifier: {"name_zh": e.name_zh, "source": e.source, "added": e.added}
            for e in sorted(self._entries.values(), key=lambda e: e.identifier)
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        self.path.write_text(text, encoding="utf-8")

    # -- api -------------------------------------------------------------------

    def get(self, identifier: str) -> ZhNameEntry | None:
        return self._entries.get(identifier.strip().upper())

    def add(self, identifier: str, name_zh: str, source: str = "") -> ZhNameEntry:
        entry = ZhNameEntry(
            identifier=identifier.strip().upper(),
            name_zh=name_zh.strip(),
            source=source.strip(),
            added=datetime.now(UTC).strftime("%Y-%m-%d"),
        )
        self._entries[entry.identifier] = entry
        self._save()
        return entry

    def remove(self, identifier: str) -> bool:
        gone = self._entries.pop(identifier.strip().upper(), None)
        if gone is not None:
            self._save()
            return True
        return False

    def list(self) -> list[ZhNameEntry]:
        return sorted(self._entries.values(), key=lambda e: e.identifier)

    def find(self, cas: str | None, cid: int | None) -> ZhNameEntry | None:
        """Look up the curation for a resolved identity: CAS first, then CID."""
        if cas:
            e = self.get(cas)
            if e is not None:
                return e
        if cid is not None:
            return self.get(str(cid))
        return None
