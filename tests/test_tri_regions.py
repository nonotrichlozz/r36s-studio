"""Tests de `tri/regions.py` -- filtre région/langue d'après les noms
No-Intro (docs/tri-roms.md)."""

from __future__ import annotations

import pytest

from r36s_studio.tri.regions import (
    KEEP,
    LANGUAGE_EXCLUDED,
    NO_REGION,
    REGION_EXCLUDED,
    RegionFilter,
    evaluate,
    parse_regions_and_languages,
)

EUROPE = RegionFilter(regions=frozenset({"Europe"}))
FRENCH = RegionFilter(languages=frozenset({"Fr"}))
EUROPE_FRENCH = RegionFilter(regions=frozenset({"Europe"}), languages=frozenset({"Fr"}))


@pytest.mark.parametrize(
    "stem, regions, languages",
    [
        ("Sonic (Europe)", {"europe"}, set()),
        ("Zelda (USA, Europe) (En,Fr,De)", {"usa", "europe"}, {"En", "Fr", "De"}),
        # Noms déjà passés par la règle des virgules (cartes SF3000).
        ("Zelda (USA Europe) (En-Fr-De)", {"usa", "europe"}, {"En", "Fr", "De"}),
        ("Pokemon (Europe) (En,Fr,De,Es,It+En,Fr,De)", {"europe"}, {"En", "Fr", "De", "Es", "It"}),
        ("Jeu (Taiwan) (Zh-Hant)", {"taiwan"}, {"Zh"}),
        ("Jeu (United Kingdom)", {"united kingdom"}, set()),
        ("Tetris (Rev 1) (Beta) [!]", set(), set()),
        ("Ukraine Story (Unl)", set(), set()),
    ],
)
def test_parse_regions_and_languages(stem, regions, languages):
    assert parse_regions_and_languages(stem) == (frozenset(regions), frozenset(languages))


def test_no_criteria_keeps_everything():
    assert evaluate("Jeu (Japan)", RegionFilter()) == KEEP


def test_europe_without_language_is_kept_for_french():
    """Beaucoup de jeux (Europe) sans mention de langue sont en français."""
    assert evaluate("Sonic (Europe)", FRENCH) == KEEP
    assert evaluate("Sonic (Europe)", EUROPE_FRENCH) == KEEP


def test_multilingual_usa_with_french_is_kept_even_outside_the_chosen_region():
    assert evaluate("Jeu (USA) (En,Fr,Es)", EUROPE_FRENCH) == KEEP
    assert evaluate("Jeu (USA) (En,Es)", EUROPE_FRENCH) == LANGUAGE_EXCLUDED


def test_name_without_region_is_kept_and_flagged_never_set_aside():
    assert evaluate("Homebrew Pong", EUROPE_FRENCH) == NO_REGION
    assert evaluate("Homebrew Pong (Unl)", EUROPE) == NO_REGION


def test_region_filter_sets_aside_other_regions():
    assert evaluate("Jeu (Japan)", EUROPE) == REGION_EXCLUDED
    assert evaluate("Jeu (USA, Europe)", EUROPE) == KEEP


def test_world_matches_any_chosen_region():
    assert evaluate("Tetris (World)", EUROPE) == KEEP


def test_single_language_region_is_set_aside_by_the_language_filter():
    """(USA) seul → anglais ; (Japan) seul → japonais."""
    assert evaluate("Jeu (USA)", FRENCH) == LANGUAGE_EXCLUDED
    assert evaluate("Jeu (Japan)", FRENCH) == LANGUAGE_EXCLUDED
    assert evaluate("Jeu (France)", FRENCH) == KEEP
    assert evaluate("Jeu (USA, Europe)", FRENCH) == KEEP  # Europe : langue indéterminée
