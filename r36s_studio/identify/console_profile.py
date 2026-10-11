# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Console d'origine ou clone, et le système à proposer (parcours « Ma
console ne démarre plus », docs/claude/assisted-wizard.md). Sources : la
carte quand elle est lisible (`identify`), sinon la référence de carte mère
tapée par l'utilisateur, en saisie libre. « Je ne sais pas » et toute
référence inconnue -> l'image clone : elle embarque les écrans de rechange,
donc de bonnes chances de démarrer même sur une console d'origine."""

from __future__ import annotations

from typing import Optional

from . import IdentifyResult
from .releases import ARKOS_K36_RELEASES_URL, DARKOS_R36S_RELEASES_URL

ORIGIN = "origin"
CLONE = "clone"
UNKNOWN = "unknown"

# Références de carte mère connues (sous-chaîne, sans la casse). Un seul cas
# documenté le 2026-10-11 ; la base s'enrichira avec les consoles des clients.
KNOWN_CLONE_REFERENCES = ("G80CA",)


def profile_from_identify(result: IdentifyResult) -> Optional[str]:
    """`None` si la carte n'a rien dit (illisible, aucun .dtb...)."""
    if result.is_clone:
        return CLONE
    return ORIGIN if result.info is not None else None


def profile_from_reference(reference: str) -> str:
    text = reference.upper()
    return CLONE if any(ref in text for ref in KNOWN_CLONE_REFERENCES) else UNKNOWN


def recommended_releases_url(profile: str) -> str:
    return DARKOS_R36S_RELEASES_URL if profile == ORIGIN else ARKOS_K36_RELEASES_URL
