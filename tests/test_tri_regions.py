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


# --- formes relevées sur une vraie collection (carte SF3000, 2026-10-06) ------


@pytest.mark.parametrize(
    "stem",
    [
        # Bug constaté : versions nationales écartées avec Europe + Français cochés.
        "Pokemon - Version Emeraude (France)",
        "Pokemon - Version Rubis (France)",
        "Pitfall - L'Expedition Perdue (France)",
        "Aventures de Jackie Chan- Les - La Legende de la Main Noire(FR)",
        "Jeu (France, Germany)",
        "Jeu (Europe) (En,Fr,De)",
        "Jurassic Park (E) [!]",
        "Dokapon(EU)",
        "Smurfs 2(Euro)",
        "BackTrack(UE)",
        "Adventures of Batman & Robin The (JUE)",
        "Puyo pop (v05) (jue)",
        "Darius Fighter (Europe and America)",
        "Smurfs (European and American)",
        "10-Yard Fight (USA- Europe)",
    ],
)
def test_real_european_and_national_names_are_kept_for_europe_and_french(stem):
    assert evaluate(stem, EUROPE_FRENCH) == KEEP


@pytest.mark.parametrize(
    "stem, verdict",
    [
        ("GG Shinobi (J)", REGION_EXCLUDED),
        ("Boku ha Koukuu Kanseikan(JP)", REGION_EXCLUDED),
        ("Master of syougi (j) [!]", REGION_EXCLUDED),
        ("zero 4 champ (japan) (v1.5)", REGION_EXCLUDED),
        ("Air Zonk (U)", REGION_EXCLUDED),
        ("Moto GP(US)", REGION_EXCLUDED),
        ("Toto World 3 (K)", REGION_EXCLUDED),
        ("1942 (Japan- USA)", REGION_EXCLUDED),
        ("Adventure Island 2 (Chinese version)", LANGUAGE_EXCLUDED),
        # Pays européens d'une autre langue : gardés pour Europe seule, écartés si Fr est coché.
        ("Jeu (Germany)", LANGUAGE_EXCLUDED),
        ("Pixeline i Pixieland (Denmark)", LANGUAGE_EXCLUDED),
    ],
)
def test_real_non_european_names_are_set_aside_for_europe_and_french(stem, verdict):
    assert evaluate(stem, EUROPE_FRENCH) == verdict


def test_french_country_is_kept_for_french_whatever_the_region_ticked():
    usa_french = RegionFilter(regions=frozenset({"USA"}), languages=frozenset({"Fr"}))
    assert evaluate("Pokemon - Version Rubis (France)", usa_french) == KEEP
    assert evaluate("Jeu (Germany)", usa_french) == REGION_EXCLUDED


def test_country_counts_for_its_broad_region():
    assert evaluate("Jeu (Germany)", EUROPE) == KEEP
    assert evaluate("Jeu (Spain)", EUROPE) == KEEP


def test_language_code_is_never_read_as_a_country_alias():
    """« (FR) » : France ; « (Fr) » : la langue."""
    assert parse_regions_and_languages("Jeu (FR)") == (frozenset({"france"}), frozenset())
    assert parse_regions_and_languages("Jeu (Fr)") == (frozenset(), frozenset({"Fr"}))


def test_video_standards_are_not_regions():
    assert parse_regions_and_languages("Strategist (Asia) (PAL) (Unl)") == (frozenset({"asia"}), frozenset())


# --- formes relevées sur la carte ArkOS 256 Go (39 059 jeux, 2026-10-07) -----


@pytest.mark.parametrize(
    "stem, regions, languages",
    [
        ("Donkey Kong Jr. (JU) (PT-BR)", {"japan", "usa"}, set()),
        ("032.Puzzle Bobble Mini (V10) (EJ) [!]", {"europe", "japan"}, set()),
        ("Defender of the Crown (F) [!]", {"france"}, set()),
        ("Robin Hood - Prince of Thieves (G) [!]", {"germany"}, set()),
        ("Cvetnie Linii (R) [!]", {"russia"}, set()),
        ("Super Mario Bros. 1 (W) [!]", {"world"}, set()),
        ("Championship Rally (A) [!]", {"australia"}, set()),
        ("3 Ninjas Kick Back (BR)", {"brazil"}, set()),
        ("Denji Makai (CH)", {"china"}, set()),
        ("Adventures of Batman & Robin The (U) (eng)", {"usa"}, {"En"}),
        ("Tun Shi Tian Di III (China) (Simple Chinese) (Unl)", {"china"}, {"Zh"}),
        # Marqueurs de dump entre crochets : jamais des régions.
        ("017.Download (J) [a]", {"japan"}, set()),
        ("Castlevania II - Simon s Quest (U) [b]", {"usa"}, set()),
        ("1991 Du Ma Racing (Asia) (Unl) (T)", {"asia"}, set()),
    ],
)
def test_arkos_card_forms(stem, regions, languages):
    assert parse_regions_and_languages(stem) == (frozenset(regions), frozenset(languages))


def test_french_goodtools_code_is_kept_for_europe_and_french():
    assert evaluate("Defender of the Crown (F) [!]", EUROPE_FRENCH) == KEEP
