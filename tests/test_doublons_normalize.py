from __future__ import annotations

from r36s_studio.doublons.normalize import (
    extract_tags,
    normalize_title,
    priority_score,
    region_rank,
    revision_score,
)


def test_normalize_title_strips_case_accents_and_tags():
    assert normalize_title("Pokémon Rouge (France) (Rev A)") == "pokemon rouge"


def test_normalize_title_collapses_punctuation_and_whitespace():
    assert normalize_title("Chrono  Trigger!!  ") == "chrono trigger"


def test_extract_tags_returns_title_and_tag_contents():
    title, tags = extract_tags("Game (Europe) [!]")
    assert title.strip() == "Game"
    assert tags == ["Europe", "!"]


def test_region_rank_prefers_france_then_europe_then_world_then_usa_then_japan():
    assert region_rank(["France"]) == 0
    assert region_rank(["Fr"]) == 0
    assert region_rank(["Europe"]) == 1
    assert region_rank(["World"]) == 2
    assert region_rank(["USA"]) == 3
    assert region_rank(["Japan"]) == 4


def test_region_rank_unknown_region_is_worst():
    assert region_rank(["Beta"]) > region_rank(["Japan"])


def test_region_rank_never_matches_a_substring():
    """"Français" ne doit jamais matcher "fr" par accident de sous-chaîne
    -- seule une correspondance de mot entier compte."""
    assert region_rank(["Francais"]) == region_rank(["Beta"])


def test_revision_score_prefers_higher_version_number():
    assert revision_score(["v1.1"]) > revision_score(["v1.0"])


def test_revision_score_prefers_higher_letter_revision():
    assert revision_score(["Rev B"]) > revision_score(["Rev A"])


def test_revision_score_with_no_revision_is_lowest():
    assert revision_score(["Europe"]) < revision_score(["Rev A"])


def test_priority_score_orders_region_before_revision_before_size():
    france = priority_score("Game (France)", size_bytes=1)
    europe_rev_b = priority_score("Game (Europe) (Rev B)", size_bytes=1_000_000)
    assert france > europe_rev_b  # la région prime toujours sur la taille
