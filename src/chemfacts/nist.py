"""Client for NIST WebBook (webbook.nist.gov) — independent second source.

chemfacts is provenance-first: every value is reported with who published it,
when it was accessed, and where to re-check it. NIST WebBook contributes
independent phase-change measurements (boiling point, melting point, enthalpy
of vaporization) cross-checked against PubChem.

The WebBook has no stable JSON API; this client parses the HTML phase-change
tables (``Mask=4``) of the per-compound page, keyed by CAS number.

Fail-closed discipline (same as the rest of the project):
- unknown CAS / missing section / network failure -> empty list, never a guess
- every row keeps its raw NIST value, units, and the NIST reference citation
"""

from __future__ import annotations

import html as _html
import re
import time

import requests

from .model import PropertyValue

_BASE = "https://webbook.nist.gov/cgi/cbook.cgi"

# NIST quantity label (tags stripped) -> PUG View heading used across chemfacts
_QUANTITY_MAP = {
    "Tboil": "Boiling Point",
    "Tfus": "Melting Point",
    "dHvap": "Enthalpy of Vaporization",  # 1-D table label "ΔvapH°"
}

# table aria-labels that carry ΔvapH rows without a quantity column
_DHVAP_TABLE_LABELS = {"Enthalpy of vaporization"}

_CAS_RE = re.compile(r"^\d{2,7}-\d{2}-\d$")


class NistError(RuntimeError):
    """Raised when the WebBook page cannot be fetched."""


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment)
    return _html.unescape(text).strip()


class NistClient:
    """Fetch NIST WebBook phase-change data for a CAS number."""

    def __init__(
        self,
        timeout: float = 30.0,
        session: requests.Session | None = None,
        min_interval: float = 1.0,
    ):
        self.timeout = timeout
        self.min_interval = min_interval
        self._last_call = 0.0
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = (
            "chemfacts/0.5 (+https://github.com/CL4Y68/chemfacts)"
        )

    # -- transport ----------------------------------------------------------

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last_call = time.monotonic()

    def _get_html(self, url: str, params: dict | None = None) -> str:
        self._throttle()
        try:
            r = self.session.get(url, params=params, timeout=self.timeout)
        except requests.RequestException as e:
            raise NistError(f"request failed: {url}: {e}") from e
        if r.status_code >= 400:
            raise NistError(f"http {r.status_code}: {url}")
        return r.text

    # -- parsing ------------------------------------------------------------

    @staticmethod
    def _nist_id(cas: str) -> str | None:
        """'109-99-9' -> 'C109999'; None when the CAS pattern does not match."""
        if not _CAS_RE.match(cas):
            return None
        return "C" + cas.replace("-", "")

    def _section(self, page: str) -> str:
        """The #Thermo-Phase section of the page, or '' when absent."""
        parts = page.split('id="Thermo-Phase"')
        if len(parts) < 2:
            return ""
        return parts[1].split('id="Refs"')[0]

    @staticmethod
    def _data_rows(section: str) -> list[dict[str, str]]:
        """Every data row in the section, tagged with its table context.

        One-dimensional tables carry the quantity in the first cell;
        two-dimensional tables (e.g. ΔvapH vs T) carry it in the
        aria-label of the table instead.
        """
        rows: list[dict[str, str]] = []
        for table in re.findall(r"<table class=\"data\"[^>]*>.*?</table>", section, re.S):
            label_m = re.search(r'aria-label="([^"]+)"', table)
            label = label_m.group(1) if label_m else ""
            for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.S):
                cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
                if not cells:
                    continue  # header row
                clean = [_strip_tags(c) for c in cells]
                if label in _DHVAP_TABLE_LABELS and len(clean) >= 2:
                    # [ΔvapH (kJ/mol), Temperature (K), Method, Reference, Comment]
                    # The WebBook page also mixes in *coefficient / range*
                    # tables (e.g. "302. to 339." temperature ranges with fit
                    # coefficients, numeric "reference" cells) — keep only
                    # point-value measurement rows, fail-closed otherwise.
                    if re.search(r"\bto\b", clean[0]) or re.search(r"\bto\b", clean[1]):
                        continue
                    if len(clean) > 3 and clean[3] and not re.search(r"[A-Za-z]", clean[3]):
                        continue  # "reference" cell is a number -> coefficients table
                    rows.append(
                        {
                            "quantity": "dHvap",
                            "value": clean[0],
                            "units": "kJ/mol",
                            "temperature": clean[1] if len(clean) > 1 else "",
                            "method": clean[2] if len(clean) > 2 else "",
                            "reference": clean[3] if len(clean) > 3 else "",
                        }
                    )
                elif len(clean) >= 5:
                    # [Quantity, Value, Units, Method, Reference, Comment]
                    quantity = _normalize_quantity(clean[0])
                    if quantity:
                        rows.append(
                            {
                                "quantity": quantity,
                                "value": clean[1],
                                "units": clean[2],
                                "temperature": "",
                                "method": clean[3],
                                "reference": clean[4],
                            }
                        )
        return rows

    def phase_change_rows(
        self, cas: str, heading: str
    ) -> list[PropertyValue]:
        """All NIST WebBook rows for one property heading of one CAS.

        Returns [] (never raises for 'not found') when the CAS is unknown to
        the WebBook or the property is absent — a missing NIST value is a
        missing value, reported as such by the caller. Transport failures
        raise NistError so the caller can fall back to PubChem-only.
        """
        nid = self._nist_id(cas)
        if nid is None:
            return []
        page = self._get_html(_BASE, params={"ID": nid, "Units": "SI", "Mask": "4"})
        section = self._section(page)
        if not section:
            return []
        url_page = f"{_BASE}?ID={nid}&Units=SI&Mask=4#Thermo-Phase"
        out: list[PropertyValue] = []
        for row in self._data_rows(section):
            heading_for_row = _QUANTITY_MAP.get(row["quantity"])
            if heading_for_row != heading:
                continue
            value = row["value"]
            if not value:
                continue
            ref = row.get("reference", "")
            # attribution: "NIST WebBook (Majer and Svoboda, 1985)";
            # AVG rows cite the NIST-derived average instead of a paper
            if row.get("method") == "AVG" or ref in ("", "N/A"):
                source = (
                    "NIST WebBook (TRC average of experimental values)"
                    if row["quantity"] == "Tboil"
                    else "NIST WebBook"
                )
            else:
                source = f"NIST WebBook ({ref})"
            if row.get("temperature"):
                value = f"{value} {row['units']} at {row['temperature']} K"
            else:
                value = f"{value} {row['units']}"
            out.append(
                PropertyValue(
                    property_name=heading,
                    value=value,
                    reference_number=0,
                    source_name=source,
                    kind="experimental",
                    url=url_page,
                )
            )
        return out


def _normalize_quantity(raw: str) -> str | None:
    """'Tboil' | 'Tfus' | 'ΔvapH°' (tags already stripped) -> internal key."""
    q = raw.strip()
    if q.startswith("T"):
        key = q.replace("°", "").rstrip()
        if key in ("Tboil", "Tfus", "Ttriple", "Tc", "Pc"):
            return "Tboil" if key == "Tboil" else "Tfus" if key == "Tfus" else None
        return None
    if "vap" in q:
        return "dHvap"
    if "fus" in q and q.startswith("Δ"):
        return "dHvap_fus"  # enthalpy of fusion: out of scope, not mapped
    return None
