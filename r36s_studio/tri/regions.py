# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Filtre région/langue de « Ranger mes jeux » (docs/tri-roms.md), d'après
la convention No-Intro des noms de fichiers : région entre parenthèses
« (Europe) », « (USA, Europe) », langues « (En,Fr,De) ». Les formes déjà
renommées par la règle des virgules (« (USA Europe) », « (En-Fr-De) »)
sont reconnues aussi.

Règle, dans cet ordre :
1. aucun critère choisi → gardé ;
2. filtre langue actif et langues écrites dans le nom → décidé par les
   langues seules : un « (USA) (En,Fr) » est gardé pour Fr même si la
   région USA n'est pas cochée ;
3. aucune région dans le nom → gardé, mais signalé (`NO_REGION`) :
   jamais écarté sans qu'on le voie ;
4. filtre région actif → gardé si une région du nom est cochée ; « World »
   vaut pour toutes les régions ;
5. filtre langue actif, sans langue écrite → écarté seulement si chaque
   région du nom implique une seule langue, non cochée (« (USA) » → En,
   « (Japan) » → Ja). Europe, World, Asia… n'impliquent aucune langue :
   un « (Europe) » sans langue, souvent en français, est gardé."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import FrozenSet, Optional, Tuple

from r36s_studio.doublons.normalize import extract_tags

__all__ = [
    "REGION_CHOICES",
    "LANGUAGE_CHOICES",
    "KEEP",
    "NO_REGION",
    "REGION_EXCLUDED",
    "LANGUAGE_EXCLUDED",
    "RegionFilter",
    "parse_regions_and_languages",
    "evaluate",
]

# Proposés dans l'écran.
REGION_CHOICES = ("Europe", "USA", "Japan", "World")
LANGUAGE_CHOICES = ("Fr", "En", "De", "Es", "It")

KEEP = "keep"
NO_REGION = "no_region"
REGION_EXCLUDED = "region_excluded"
LANGUAGE_EXCLUDED = "language_excluded"

# Régions No-Intro reconnues -> langue impliquée quand il n'y en a qu'une
# (None : plusieurs langues possibles, n'écarte jamais rien).
_REGION_LANGUAGE = {
    "europe": None,
    "world": None,
    "asia": None,
    "scandinavia": None,
    "canada": None,
    "usa": "En",
    "uk": "En",
    "united kingdom": "En",
    "australia": "En",
    "japan": "Ja",
    "france": "Fr",
    "germany": "De",
    "spain": "Es",
    "italy": "It",
    "netherlands": "Nl",
    "sweden": "Sv",
    "brazil": "Pt",
    "portugal": "Pt",
    "russia": "Ru",
    "korea": "Ko",
    "china": "Zh",
    "taiwan": "Zh",
    "hong kong": "Zh",
}
_REGION_NAME = "|".join(sorted((re.escape(name) for name in _REGION_LANGUAGE), key=len, reverse=True))
_REGION_TAG_RE = re.compile(rf"\s*(?:{_REGION_NAME})(?:\s*,\s*|\s+)?", re.IGNORECASE)
_LANGUAGE_TAG_RE = re.compile(r"[A-Z][a-z](?:-[A-Z][a-z]{3})?(?:\s*[,+\-]\s*[A-Z][a-z](?:-[A-Z][a-z]{3})?)*")
_LANGUAGE_SEPARATOR_RE = re.compile(r"[\s,+\-]+")


def _regions_of(tag: str) -> Optional[FrozenSet[str]]:
    """Régions d'un tag fait uniquement de noms de régions, sinon None."""
    position, found = 0, set()
    while position < len(tag):
        match = _REGION_TAG_RE.match(tag, position)
        if match is None or match.end() == position:
            return None
        found.add(re.sub(r"[\s,]+", " ", match.group()).strip().lower())
        position = match.end()
    return frozenset(found) or None


def parse_regions_and_languages(stem: str) -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """`(régions en minuscules, codes de langue)` trouvés dans `stem`."""
    _title, tags = extract_tags(stem)
    regions, languages = set(), set()
    for tag in tags:
        tag_regions = _regions_of(tag.strip())
        if tag_regions is not None:
            regions |= tag_regions
        elif _LANGUAGE_TAG_RE.fullmatch(tag.strip()):
            # « Zh-Hant » : le code est « Zh », pas « Ha ».
            languages |= {code for code in _LANGUAGE_SEPARATOR_RE.split(tag.strip()) if len(code) == 2}
    return frozenset(regions), frozenset(languages)


@dataclass(frozen=True)
class RegionFilter:
    regions: FrozenSet[str] = frozenset()  # ex. {"Europe"}, parmi REGION_CHOICES
    languages: FrozenSet[str] = frozenset()  # ex. {"Fr"}, parmi LANGUAGE_CHOICES

    def is_active(self) -> bool:
        return bool(self.regions or self.languages)


def evaluate(stem: str, criteria: RegionFilter) -> str:
    """`KEEP`, `NO_REGION` (gardé, signalé), `REGION_EXCLUDED` ou
    `LANGUAGE_EXCLUDED` -- voir la règle en tête de module."""
    if not criteria.is_active():
        return KEEP
    regions, languages = parse_regions_and_languages(stem)
    if criteria.languages and languages:
        return KEEP if languages & criteria.languages else LANGUAGE_EXCLUDED
    if not regions:
        return NO_REGION
    chosen_regions = {region.lower() for region in criteria.regions}
    if chosen_regions and "world" not in regions and not regions & chosen_regions:
        return REGION_EXCLUDED
    if criteria.languages:
        implied = {_REGION_LANGUAGE[region] for region in regions}
        if None not in implied and not implied & criteria.languages:
            return LANGUAGE_EXCLUDED
    return KEEP
