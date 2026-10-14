# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Console d'origine ou clone, et le système à proposer (parcours « Ma
console ne démarre plus », docs/claude/assisted-wizard.md). Sources : la
carte quand elle est lisible (`identify`), sinon la référence de carte mère
tapée par l'utilisateur, en saisie libre ; les deux passent par la table de
dArkOSRE (`hardware_table.py`). « Je ne sais pas » et toute
référence inconnue -> l'image clone : elle embarque les écrans de rechange,
donc de bonnes chances de démarrer même sur une console d'origine."""

from __future__ import annotations

from typing import Optional

from . import IdentifyResult
from .hardware_table import CLONE as TABLE_CLONE, R36S as TABLE_R36S, families_for_hardware, family_for_hardware
from .releases import ARKOS_K36_RELEASES_URL, DARKOS_R36S_RELEASES_URL

ORIGIN = "origin"
CLONE = "clone"
UNKNOWN = "unknown"
# Référence présente chez les originales et chez les clones (table) : même
# image que UNKNOWN, mais l'utilisateur doit savoir que sa saisie a servi.
AMBIGUOUS = "ambiguous"

# Références de carte mère connues (sous-chaîne, sans la casse), en plus de
# la table : « G80CA » seul, tapé sans la suite.
KNOWN_CLONE_REFERENCES = ("G80CA",)
# « soysauce » (Y3506) : ni l'un ni l'autre, donc UNKNOWN.
_TABLE_PROFILES = {TABLE_R36S: ORIGIN, TABLE_CLONE: CLONE}


def profile_from_identify(result: IdentifyResult) -> Optional[str]:
    """`None` si la carte n'a rien dit (illisible, aucun .dtb...)."""
    if result.is_clone:
        return CLONE
    family = family_for_hardware(result.hardware_model)
    if family is not None:
        return _TABLE_PROFILES.get(family, UNKNOWN)
    return ORIGIN if result.info is not None else None


def profile_from_reference(reference: str) -> str:
    profiles = {_TABLE_PROFILES.get(family, UNKNOWN) for family in families_for_hardware(reference)}
    if {ORIGIN, CLONE} <= profiles:
        return AMBIGUOUS
    if len(profiles) == 1:
        return profiles.pop()
    text = reference.upper()
    return CLONE if any(ref in text for ref in KNOWN_CLONE_REFERENCES) else UNKNOWN


def recommended_releases_url(profile: str) -> str:
    return DARKOS_R36S_RELEASES_URL if profile == ORIGIN else ARKOS_K36_RELEASES_URL
