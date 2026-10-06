# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Filtre région/langue (docs/tri-roms.md), d'après les mentions entre
parenthèses des noms de fichiers : convention No-Intro (« (Europe) »,
« (USA, Europe) », « (France) », « (En,Fr,De) »), codes GoodTools plus
anciens (« (J) », « (UE) », « (JUE) »), et formes déjà renommées par la
règle des virgules (« (USA Europe) », « (En-Fr-De) », « (USA- Europe) »).

**Les formes reconnues sont celles relevées sur de vraies collections**
(carte SF3000, 12 567 jeux, 2026-10-06 ; carte ArkOS 256 Go, 39 059 jeux,
2026-10-07 -- voir docs/tri-roms.md), pas une liste complétée de mémoire. Une forme absente du relevé reste inconnue :
le jeu est alors gardé et signalé (« sans région »), jamais écarté à tort.

Règle, dans cet ordre :
1. aucun critère choisi → gardé ;
2. filtre langue actif et langues écrites dans le nom → décidé par les
   langues seules : un « (USA) (En,Fr) » est gardé pour Fr même si la
   région USA n'est pas cochée ;
3. aucune région dans le nom → gardé, mais signalé (`NO_REGION`) :
   jamais écarté sans qu'on le voie ;
4. filtre langue actif et pays qui implique une langue cochée → gardé :
   « (France) » est en français, quelle que soit la région cochée ;
5. filtre région actif → gardé si une région du nom est cochée. Un pays
   compte pour sa région large (« (France) », « (Germany) »… → Europe) ;
   « World » vaut pour toutes les régions ;
6. filtre langue actif, sans langue écrite → écarté seulement si chaque
   région du nom implique une seule langue, non cochée (« (USA) » → En,
   « (Japan) » → Ja). Europe, World, Asia… n'impliquent aucune langue : un
   « (Europe) » sans langue, souvent en français, est gardé."""

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

# Régions et pays reconnus -> langue impliquée quand il n'y en a qu'une
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
    "denmark": "Da",
    "brazil": "Pt",
    "portugal": "Pt",
    "russia": "Ru",
    "korea": "Ko",
    "china": "Zh",
    "taiwan": "Zh",
    "hong kong": "Zh",
}
# Pays -> région large qu'ils représentent pour le filtre région
# (« Europe » cochée garde « (France) »).
_PARENT_REGION = {
    country: "europe"
    for country in (
        "france", "germany", "spain", "italy", "netherlands", "sweden", "denmark",
        "portugal", "uk", "united kingdom", "russia", "scandinavia",
    )
}
# Codes GoodTools relevés dans les collections, **dans la casse observée** :
# entre crochets, « [a] », « [b] », « [f] »… sont des marqueurs de dump
# (alternatif, mauvais, corrigé), jamais des régions -- un code d'une
# lettre n'est donc reconnu que tel qu'il a été vu.
_REGION_CODES = {
    "J": ("japan",), "JP": ("japan",), "j": ("japan",),
    "U": ("usa",), "US": ("usa",), "u": ("usa",),
    "E": ("europe",), "EU": ("europe",), "Euro": ("europe",),
    "UE": ("usa", "europe"), "JU": ("japan", "usa"), "EJ": ("europe", "japan"),
    "JUE": ("japan", "usa", "europe"), "jue": ("japan", "usa", "europe"),
    "F": ("france",), "FR": ("france",), "G": ("germany",), "R": ("russia",),
    "K": ("korea",), "CH": ("china",), "A": ("australia",), "BR": ("brazil",),
    "W": ("world",),
}
# Formulations libres relevées (casse indifférente) -> régions.
_REGION_PHRASES = {
    "europe and america": ("europe", "usa"),
    "european and american": ("europe", "usa"),
}
# Mentions entières relevées -> langue (casse indifférente).
_LANGUAGE_ALIASES = {"chinese": "Zh", "chinese version": "Zh", "simple chinese": "Zh", "eng": "En"}

_REGION_NAME = "|".join(sorted((re.escape(name) for name in _REGION_LANGUAGE), key=len, reverse=True))
# Séparateurs : virgule, espace, et « - » (« (USA- Europe) », règle des virgules).
_REGION_TAG_RE = re.compile(rf"\s*(?:{_REGION_NAME})(?:\s*[,\-]\s*|\s+)?", re.IGNORECASE)
_LANGUAGE_TAG_RE = re.compile(r"[A-Z][a-z](?:-[A-Z][a-z]{3})?(?:\s*[,+\-]\s*[A-Z][a-z](?:-[A-Z][a-z]{3})?)*")
_LANGUAGE_SEPARATOR_RE = re.compile(r"[\s,+\-]+")


def _regions_of(tag: str) -> Optional[FrozenSet[str]]:
    """Régions d'une mention faite uniquement de régions/pays (ou d'un
    alias relevé), sinon None."""
    # « (FR) » est un alias de pays, « (Fr) » une langue : jamais d'alias
    # pour une mention qui a la forme d'un code de langue.
    tag = tag.strip()
    alias = None if _LANGUAGE_TAG_RE.fullmatch(tag) else _REGION_CODES.get(tag) or _REGION_PHRASES.get(tag.lower())
    if alias is not None:
        return frozenset(alias)
    position, found = 0, set()
    while position < len(tag):
        match = _REGION_TAG_RE.match(tag, position)
        if match is None or match.end() == position:
            return None
        found.add(re.sub(r"[\s,\-]+", " ", match.group()).strip().lower())
        position = match.end()
    return frozenset(found) or None


def parse_regions_and_languages(stem: str) -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """`(régions et pays en minuscules, codes de langue)` trouvés dans `stem`."""
    _title, tags = extract_tags(stem)
    regions, languages = set(), set()
    for tag in tags:
        tag = tag.strip()
        tag_regions = _regions_of(tag)
        if tag_regions is not None:
            regions |= tag_regions
        elif tag.lower() in _LANGUAGE_ALIASES:
            languages.add(_LANGUAGE_ALIASES[tag.lower()])
        elif _LANGUAGE_TAG_RE.fullmatch(tag):
            # « Zh-Hant » : le code est « Zh », pas « Ha ».
            languages |= {code for code in _LANGUAGE_SEPARATOR_RE.split(tag) if len(code) == 2}
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
    implied = {_REGION_LANGUAGE[region] for region in regions}
    if criteria.languages and implied & criteria.languages:
        return KEEP
    chosen_regions = {region.lower() for region in criteria.regions}
    broad_regions = regions | {_PARENT_REGION[r] for r in regions if r in _PARENT_REGION}
    if chosen_regions and "world" not in broad_regions and not broad_regions & chosen_regions:
        return REGION_EXCLUDED
    if criteria.languages and None not in implied:
        return LANGUAGE_EXCLUDED
    return KEEP
