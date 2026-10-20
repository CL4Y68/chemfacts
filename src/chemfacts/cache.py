"""SQLite fact cache.

Every stored fact keeps its provenance (source + access date), so re-reading
the cache still tells you *where a number came from* and *how old it is*.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .model import CompoundIdentity, PropertyValue

_DEFAULT_DIR = Path(os.environ.get("CHEMFACTS_CACHE_DIR", Path.home() / ".cache" / "chemfacts"))

_SCHEMA = """
CREATE TABLE IF NOT EXISTS identity (
    cid             INTEGER PRIMARY KEY,
    identifier      TEXT,
    name            TEXT,
    iupac_name      TEXT,
    cas             TEXT,
    formula         TEXT,
    molecular_weight REAL,
    canonical_smiles TEXT,
    isomeric_smiles TEXT,
    inchi           TEXT,
    inchi_key       TEXT,
    title           TEXT,
    accessed_at     TEXT
);
CREATE TABLE IF NOT EXISTS value (
    cid             INTEGER NOT NULL,
    property        TEXT NOT NULL,
    value           TEXT NOT NULL,
    reference_number INTEGER NOT NULL,
    source_name     TEXT,
    kind            TEXT,
    accessed_at     TEXT,
    url             TEXT,
    PRIMARY KEY (cid, property, value, reference_number)
);
CREATE TABLE IF NOT EXISTS ref (
    cid             INTEGER NOT NULL,
    reference_number INTEGER NOT NULL,
    name            TEXT,
    PRIMARY KEY (cid, reference_number)
);
"""


class FactCache:
    def __init__(self, db_path: str | None = None):
        if db_path is None:
            _DEFAULT_DIR.mkdir(parents=True, exist_ok=True)
            db_path = str(_DEFAULT_DIR / "facts.db")
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # -- identity -----------------------------------------------------------

    def get_identity(self, cid: int) -> CompoundIdentity | None:
        cur = self.conn.execute("SELECT * FROM identity WHERE cid=?", (cid,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [c[0] for c in cur.description]
        d = dict(zip(cols, row, strict=False))
        return self._identity_from_row(d)

    @staticmethod
    def _identity_from_row(d: dict) -> CompoundIdentity:
        return CompoundIdentity(
            identifier=str(d.get("cid", "")),
            cid=d.get("cid"),
            name=d.get("name"),
            iupac_name=d.get("iupac_name"),
            cas=d.get("cas"),
            formula=d.get("formula"),
            molecular_weight=d.get("molecular_weight"),
            canonical_smiles=d.get("canonical_smiles"),
            isomeric_smiles=d.get("isomeric_smiles"),
            inchi=d.get("inchi"),
            inchi_key=d.get("inchi_key"),
            title=d.get("title"),
            accessed_at=d.get("accessed_at", ""),
        )

    def get_identity_by_identifier(self, identifier: str) -> CompoundIdentity | None:
        cur = self.conn.execute(
            "SELECT * FROM identity WHERE identifier=? OR name=? OR cas=? OR cid=?",
            (identifier, identifier, identifier, identifier),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cols = [c[0] for c in cur.description]
        d = dict(zip(cols, row, strict=False))
        ident = self._identity_from_row(d)
        ident.identifier = identifier
        return ident

    def save_identity(self, ident: CompoundIdentity) -> None:
        if not ident.cid:
            return
        self.conn.execute(
            """
            INSERT OR REPLACE INTO identity
            (cid, identifier, name, iupac_name, cas, formula, molecular_weight,
             canonical_smiles, isomeric_smiles, inchi, inchi_key, title, accessed_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ident.cid,
                ident.identifier,
                ident.name,
                ident.iupac_name,
                ident.cas,
                ident.formula,
                ident.molecular_weight,
                ident.canonical_smiles,
                ident.isomeric_smiles,
                ident.inchi,
                ident.inchi_key,
                ident.title,
                ident.accessed_at,
            ),
        )
        self.conn.commit()

    # -- values -------------------------------------------------------------

    def get_values(self, cid: int, property_name: str) -> list[PropertyValue]:
        cur = self.conn.execute(
            "SELECT * FROM value WHERE cid=? AND property=?", (cid, property_name)
        )
        rows = cur.fetchall()
        cols = [c[0] for c in cur.description]
        out: list[PropertyValue] = []
        for row in rows:
            d = dict(zip(cols, row, strict=False))
            out.append(
                PropertyValue(
                    property_name=property_name,
                    value=d["value"],
                    reference_number=d["reference_number"],
                    source_name=d.get("source_name") or "",
                    kind=d.get("kind") or "registry",
                    accessed_at=d.get("accessed_at", ""),
                    url=d.get("url"),
                )
            )
        return out

    def save_values(self, cid: int, values: list[PropertyValue]) -> None:
        for pv in values:
            self.conn.execute(
                """
                INSERT OR REPLACE INTO value
                (cid, property, value, reference_number, source_name, kind, accessed_at, url)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    cid,
                    pv.property_name,
                    pv.value,
                    pv.reference_number,
                    pv.source_name,
                    pv.kind,
                    pv.accessed_at,
                    pv.url,
                ),
            )
        self.conn.commit()

    # -- reference map ------------------------------------------------------

    def get_refs(self, cid: int) -> dict[int, str]:
        rows = self.conn.execute(
            "SELECT reference_number, name FROM ref WHERE cid=?", (cid,)
        ).fetchall()
        return {r[0]: r[1] for r in rows}

    def save_refs(self, cid: int, refs: dict[int, str]) -> None:
        for ref_no, name in refs.items():
            self.conn.execute(
                "INSERT OR REPLACE INTO ref (cid, reference_number, name) VALUES (?,?,?)",
                (cid, ref_no, name),
            )
        self.conn.commit()

    # -- TTL -----------------------------------------------------------------

    @staticmethod
    def is_fresh(accessed_at: str, ttl_days: int) -> bool:
        if not accessed_at:
            return False
        try:
            ts = datetime.strptime(accessed_at, "%Y-%m-%d %H:%M:%SZ").replace(tzinfo=UTC)
        except ValueError:
            return False
        age_days = (datetime.now(UTC) - ts).total_seconds() / 86400
        return age_days <= ttl_days

    def clear(self) -> int:
        n = 0
        for table in ("identity", "value", "ref"):
            n += self.conn.execute(f"DELETE FROM {table}").rowcount  # noqa: S608
        self.conn.commit()
        return n
