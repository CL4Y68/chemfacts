"""Thin client for PubChem (PUG REST + PUG View).

Only two kinds of endpoints are used:
- PUG REST  -> identity facts (CID, formula, MW, SMILES, InChI, IUPAC name)
- PUG View  -> property values with per-value provenance (reference numbers)
"""

from __future__ import annotations

import re
from typing import Any

import requests

from .model import CompoundIdentity, PropertyValue

_PUG_REST = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound"
_PUG_VIEW = "https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound"

_IDENTITY_PROPS = (
    "MolecularFormula,MolecularWeight,CanonicalSMILES,IsomericSMILES,"
    "IUPACName,InChI,InChIKey,Title"
)

_CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


class PubChemError(RuntimeError):
    """Raised when PubChem cannot resolve an identifier (404 / PUGREST.NotFound)."""


class PubChemClient:
    def __init__(self, timeout: float = 30.0, session: requests.Session | None = None):
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = "chemfacts/0.1 (+https://github.com/CL4Y68/chemfacts)"

    # -- transport ----------------------------------------------------------

    def _get_json(self, url: str, params: dict | None = None) -> Any:
        r = self.session.get(url, params=params, timeout=self.timeout)
        if r.status_code == 404:
            raise PubChemError(f"not found: {url}")
        r.raise_for_status()
        return r.json()

    # -- identity -----------------------------------------------------------

    @staticmethod
    def _classify(identifier: str) -> tuple[str, str]:
        """Return (kind, quoted) where kind in {cid, cas, smiles, name, inchi}."""
        ident = identifier.strip()
        if ident.isdigit():
            return "cid", ident
        if _CAS_RE.match(ident):
            return "cas", ident
        if ident.upper().startswith("INCHIKEY="):
            return "inchi", ident
        if ident.upper().startswith("INCHI="):
            return "inchi", ident
        # SMILES heuristic: starts with CcO/N etc. and contains no spaces
        if re.match(r"^[A-Za-z0-9@+\-\[\]()=#/\\.]+$", ident) and not ident.isalpha():
            return "smiles", ident
        return "name", ident

    def identity(self, identifier: str) -> CompoundIdentity:
        kind, quoted = self._classify(identifier)
        if kind == "cid":
            url = f"{_PUG_REST}/cid/{quoted}/property/{_IDENTITY_PROPS}/JSON"
        elif kind == "smiles":
            url = f"{_PUG_REST}/smiles/{quoted}/property/{_IDENTITY_PROPS}/JSON"
        elif kind == "inchi":
            url = f"{_PUG_REST}/inchi/{quoted}/property/{_IDENTITY_PROPS}/JSON"
        else:  # cas and name both go through the 'name' endpoint
            url = f"{_PUG_REST}/name/{quoted}/property/{_IDENTITY_PROPS}/JSON"

        data = self._get_json(url)
        p = data["PropertyTable"]["Properties"][0]

        cid = p.get("CID")
        ident = CompoundIdentity(
            identifier=identifier,
            cid=cid,
            name=p.get("Title"),
            iupac_name=p.get("IUPACName"),
            formula=p.get("MolecularFormula"),
            molecular_weight=(
                float(p["MolecularWeight"]) if p.get("MolecularWeight") else None
            ),
            canonical_smiles=p.get("CanonicalSMILES") or p.get("ConnectivitySMILES"),
            isomeric_smiles=p.get("IsomericSMILES"),
            inchi=p.get("InChI"),
            inchi_key=p.get("InChIKey"),
            title=p.get("Title"),
        )
        cas = self._cas(cid)
        if cas:
            ident.cas = cas
        return ident

    def _cas(self, cid: int | None) -> str | None:
        """Fetch the CAS number from the PUG View record (Chemical Identifiers -> CAS)."""
        if not cid:
            return None
        try:
            data = self._get_json(f"{_PUG_VIEW}/{cid}/JSON")
        except PubChemError:
            return None
        for info in _walk_information(data.get("Record", {}).get("Section", [])):
            if info.get("TOCHeading") == "CAS":
                return info.get("value")
        return None

    # -- properties ---------------------------------------------------------

    def property_values(self, cid: int, heading: str) -> list[PropertyValue]:
        """All published values for a PUG View heading, with provenance."""
        url = f"{_PUG_VIEW}/{cid}/JSON"
        params = {"heading": heading}
        try:
            data = self._get_json(url, params=params)
        except PubChemError:
            return []
        refs = self._reference_map(cid, data)
        out: list[PropertyValue] = []
        kind = _classify_heading_kind(heading)
        for info in _walk_information(data.get("Record", {}).get("Section", [])):
            if info.get("TOCHeading") != heading:
                continue
            value = info.get("value")
            if value is None:
                continue
            ref_no = info.get("ReferenceNumber", 0)
            source = refs.get(ref_no, f"reference #{ref_no}")
            out.append(
                PropertyValue(
                    property_name=heading,
                    value=value,
                    reference_number=ref_no,
                    source_name=source,
                    kind=kind,
                    url=f"{_PUG_VIEW}/{cid}/JSON?heading={heading}",
                )
            )
        return out

    def _reference_map(self, cid: int, data: Any) -> dict[int, str]:
        out: dict[int, str] = {}
        for ref in data.get("Record", {}).get("Reference", []):
            out[ref.get("ReferenceNumber", 0)] = _short_source(ref)
        return out


# Ordered (marker, label) pairs; first match wins. Markers hit both the
# reference's Name and its Description text.
_SOURCE_MARKERS = (
    ("ILO International Chemical Safety Cards", "ILO ICSC"),
    ("International Chemical Safety Cards", "ILO ICSC"),
    ("Hazardous Substances Data Bank", "HSDB"),
    ("HSDB", "HSDB"),
    ("CAMEO", "CAMEO"),
    ("National Toxicology Program", "NTP"),
    ("NIOSH Pocket Guide", "NIOSH"),
    ("OSHA Occupational Chemical Database", "OSHA"),
    ("NTP", "NTP"),
    ("US EPA", "EPA"),
    ("EPA", "EPA"),
    ("FDA", "FDA"),
    ("ECHA", "ECHA"),
    ("OECD", "OECD"),
    ("Wiley", "Wiley"),
    ("Springer", "Springer"),
)


def _short_source(ref: dict) -> str:
    """Short human source label (HSDB / ILO ICSC / EPA / ...) for a PUG View reference."""
    text = f'{ref.get("Name", "")} {ref.get("Description", "")}'
    for marker, label in _SOURCE_MARKERS:
        if marker in text:
            return label
    return (ref.get("Name") or "unknown source").strip()


# -- helpers to walk PUG View trees -----------------------------------------

def _walk_information(section):
    """Yield dicts: TOCHeading + flattened value + reference number + experimental flag.

    ``section`` may be a single section dict or the list ``Record.Section``
    (PUG View represents sibling sections as a list).
    """
    if isinstance(section, list):
        for child in section:
            yield from _walk_information(child)
        return
    if not isinstance(section, dict):
        return
    for child in section.get("Section", []):
        yield from _walk_information(child)
    for info in section.get("Information", []):
        value = None
        v = info.get("Value", {})
        if "StringWithMarkup" in v and v["StringWithMarkup"]:
            value = v["StringWithMarkup"][0].get("String")
        elif "Number" in v:
            value = str(v["Number"])
        elif "String" in v:
            value = v["String"]
        yield {
            "TOCHeading": section.get("TOCHeading"),
            "value": value,
            "ReferenceNumber": info.get("ReferenceNumber", 0),
        }


# PUG View headings whose values are generated (not measured) by PubChem
_COMPUTED_HEADINGS = {
    "XLogP",
    "TPSA",
    "HBondDonorCount",
    "HBondAcceptorCount",
    "RotatableBondCount",
    "Complexity",
    "ExactMass",
    "MonoisotopicMass",
    "Volume3D",
    "Fingerprint2D",
    "CovalentUnitCount",
    "HeavyAtomCount",
    "AtomStereoCount",
    "BondStereoCount",
}


def _classify_heading_kind(heading: str) -> str:
    """Whether a PUG View heading's values are computed, measured, or registry data."""
    if heading in _COMPUTED_HEADINGS:
        return "computed"
    if heading in {"MolecularWeight", "MolecularFormula", "IUPACName"}:
        return "registry"
    return "experimental"
