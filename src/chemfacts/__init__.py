"""chemfacts - provenance-first chemical fact verification.

Query PubChem, cross-check sources, never fabricate.

    from chemfacts import ChemFacts

    f = ChemFacts()
    ident = f.resolve("NMP")            # -> CompoundIdentity (CID, CAS, formula, MW, ...)
    vals = f.lookup("NMP", "flash-point")   # -> [PropertyValue, ...] each with source + date
    res = f.verify("NMP", "flash-point", "96 C")  # confirmed / mismatch / not_found
    card = f.build_card("NMP")          # -> FactCard, render with core.card_to_markdown()
"""

from .aliases import AliasEntry, AliasRegistry
from .core import ChemFacts, card_to_json, card_to_markdown, export_rows
from .model import CompoundIdentity, FactCard, PropertyValue, VerifyResult
from .pubchem import PubChemClient, PubChemError
from .zhnames import ZhNameEntry, ZhNameRegistry

__version__ = "0.4.0"

__all__ = [
    "ChemFacts",
    "CompoundIdentity",
    "FactCard",
    "PropertyValue",
    "VerifyResult",
    "PubChemClient",
    "PubChemError",
    "AliasEntry",
    "AliasRegistry",
    "ZhNameEntry",
    "ZhNameRegistry",
    "export_rows",
    "card_to_json",
    "card_to_markdown",
    "__version__",
]
