"""Tests de `doublons/scan_cache.py` -- persistance entre deux lancements
(signalé explicitement : « ne jamais obliger à relancer une analyse »).
Couvre les deux caches distincts (résultat d'analyse par dossier, cache
d'empreintes SHA-256 global) et `verify_scan_cache`, qui doit retirer les
fichiers modifiés ou disparus avant qu'un résultat en cache ne soit
réutilisé pour de vrai."""

from __future__ import annotations

import os

import pytest

from r36s_studio.doublons.scan import ExactDuplicateGroup, ScanResult, Unit, find_duplicates
from r36s_studio.doublons.scan_cache import (
    find_most_recent_scan_cache,
    load_hash_cache,
    load_scan_cache,
    save_hash_cache,
    save_scan_cache,
    scan_cache_path_for_root,
    verify_scan_cache,
)


def _touch(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


# --- Cache de résultat d'analyse, par dossier -------------------------------


def test_save_then_load_scan_cache_round_trips_the_result(tmp_path):
    root = tmp_path / "roms"
    _touch(root / "SNES" / "Game (USA).sfc", b"identical-content")
    _touch(root / "SNES" / "Game (Europe).sfc", b"identical-content")
    result = find_duplicates(str(root))

    cache_path = tmp_path / "cache" / "result.json"
    save_scan_cache(str(root), result, path=cache_path)
    cached = load_scan_cache(str(root), path=cache_path)

    assert cached is not None
    assert len(cached.result.exact_duplicate_groups) == 1
    names = {unit.representative.name for unit in cached.result.exact_duplicate_groups[0].units}
    assert names == {"Game (USA).sfc", "Game (Europe).sfc"}


def test_load_scan_cache_returns_none_when_file_absent(tmp_path):
    assert load_scan_cache(str(tmp_path), path=tmp_path / "does-not-exist.json") is None


def test_load_scan_cache_returns_none_on_corrupt_json(tmp_path):
    cache_path = tmp_path / "corrupt.json"
    cache_path.write_text("{not valid json", encoding="utf-8")
    assert load_scan_cache(str(tmp_path), path=cache_path) is None


def test_scan_cache_path_for_root_is_stable_and_distinct_per_root(tmp_path, monkeypatch):
    # `scan_cache_path_for_root` retombe sur `default_cache_dir()` (le vrai
    # dossier de données de l'app) faute de `path` explicite -- jamais
    # touché tel quel dans les tests (§8 discipline établie dans ce projet),
    # redirigé ici vers `tmp_path`.
    monkeypatch.setattr("r36s_studio.doublons.scan_cache.config_dir", lambda: tmp_path)
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()

    assert scan_cache_path_for_root(str(root_a)) == scan_cache_path_for_root(str(root_a))
    assert scan_cache_path_for_root(str(root_a)) != scan_cache_path_for_root(str(root_b))


def test_find_most_recent_scan_cache_picks_the_latest_one(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cachedir"
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    _touch(root_a / "Game.sfc")
    _touch(root_b / "Game.sfc")

    save_scan_cache(str(root_a), find_duplicates(str(root_a)), path=cache_dir / "a.json")
    # Force un `scanned_at` postérieur en réécrivant le fichier ensuite --
    # comparaison purement textuelle de deux horodatages ISO 8601 UTC.
    save_scan_cache(str(root_b), find_duplicates(str(root_b)), path=cache_dir / "b.json")
    # Rend b antérieur à a en manipulant directement le texte du fichier,
    # pour ne dépendre d'aucune granularité d'horloge réelle.
    import json

    a_path = cache_dir / "a.json"
    b_path = cache_dir / "b.json"
    a_payload = json.loads(a_path.read_text(encoding="utf-8"))
    b_payload = json.loads(b_path.read_text(encoding="utf-8"))
    a_payload["scanned_at"] = "2026-01-01T00:00:00+00:00"
    b_payload["scanned_at"] = "2026-06-01T00:00:00+00:00"
    a_path.write_text(json.dumps(a_payload), encoding="utf-8")
    b_path.write_text(json.dumps(b_payload), encoding="utf-8")

    most_recent = find_most_recent_scan_cache(cache_dir=cache_dir)

    assert most_recent is not None
    assert most_recent.root == str(root_b.resolve())


def test_find_most_recent_scan_cache_returns_none_when_dir_absent(tmp_path):
    assert find_most_recent_scan_cache(cache_dir=tmp_path / "never-created") is None


def test_find_most_recent_scan_cache_ignores_the_hash_cache_file(tmp_path):
    cache_dir = tmp_path / "cachedir"
    cache_dir.mkdir()
    save_hash_cache({}, path=cache_dir / "hash_cache.json")

    assert find_most_recent_scan_cache(cache_dir=cache_dir) is None


# --- Cache des empreintes SHA-256, global -----------------------------------


def test_save_then_load_hash_cache_round_trips(tmp_path):
    path = tmp_path / "hash_cache.json"
    cache = {"/some/path": (1234, 1700000000.5, "deadbeef")}

    save_hash_cache(cache, path=path)
    loaded = load_hash_cache(path=path)

    assert loaded == cache


def test_load_hash_cache_returns_empty_dict_when_absent(tmp_path):
    assert load_hash_cache(path=tmp_path / "missing.json") == {}


# --- verify_scan_cache : fraîcheur avant réutilisation ----------------------


def test_verify_scan_cache_keeps_a_group_when_nothing_changed(tmp_path):
    root = tmp_path / "roms"
    _touch(root / "SNES" / "Game (USA).sfc", b"identical-content")
    _touch(root / "SNES" / "Game (Europe).sfc", b"identical-content")
    result = find_duplicates(str(root))

    cache_path = tmp_path / "result.json"
    save_scan_cache(str(root), result, path=cache_path)
    cached = load_scan_cache(str(root), path=cache_path)

    fresh_result, removed = verify_scan_cache(cached)

    assert removed == 0
    assert len(fresh_result.exact_duplicate_groups) == 1


def test_verify_scan_cache_drops_a_unit_whose_file_was_modified(tmp_path):
    root = tmp_path / "roms"
    # Deux noms sans tag de région commun -- palier 1 (contenu identique)
    # uniquement, pas de groupe de versions (palier 2, titres normalisés
    # différents) qui doublerait le compte d'unités retirées ci-dessous.
    one = root / "SNES" / "GameOne.sfc"
    two = root / "SNES" / "GameTwo.sfc"
    _touch(one, b"identical-content")
    _touch(two, b"identical-content")
    result = find_duplicates(str(root))
    assert result.version_groups == []

    cache_path = tmp_path / "result.json"
    save_scan_cache(str(root), result, path=cache_path)
    cached = load_scan_cache(str(root), path=cache_path)

    # Modifie l'un des deux fichiers après l'enregistrement du cache --
    # taille et date de modification changent toutes les deux.
    original_mtime = one.stat().st_mtime
    one.write_bytes(b"changed-content-now")
    os.utime(one, (original_mtime + 5, original_mtime + 5))

    fresh_result, removed = verify_scan_cache(cached)

    # Il ne reste plus qu'une seule unité fraîche -- plus un doublon, le
    # groupe entier disparaît (jamais une réutilisation partielle).
    assert len(fresh_result.exact_duplicate_groups) == 0
    assert removed == 2


def test_verify_scan_cache_drops_a_unit_whose_file_was_deleted(tmp_path):
    root = tmp_path / "roms"
    one = root / "SNES" / "GameOne.sfc"
    two = root / "SNES" / "GameTwo.sfc"
    _touch(one, b"identical-content")
    _touch(two, b"identical-content")
    result = find_duplicates(str(root))
    assert result.version_groups == []

    cache_path = tmp_path / "result.json"
    save_scan_cache(str(root), result, path=cache_path)
    cached = load_scan_cache(str(root), path=cache_path)

    two.unlink()

    fresh_result, removed = verify_scan_cache(cached)

    assert len(fresh_result.exact_duplicate_groups) == 0
    assert removed == 2


def test_verify_scan_cache_keeps_a_group_of_three_when_only_one_member_changed(tmp_path):
    root = tmp_path / "roms"
    a = root / "SNES" / "GameOne.sfc"
    b = root / "SNES" / "GameTwo.sfc"
    c = root / "SNES" / "GameThree.sfc"
    _touch(a, b"identical-content")
    _touch(b, b"identical-content")
    _touch(c, b"identical-content")
    result = find_duplicates(str(root))
    assert result.version_groups == []
    assert len(result.exact_duplicate_groups[0].units) == 3

    cache_path = tmp_path / "result.json"
    save_scan_cache(str(root), result, path=cache_path)
    cached = load_scan_cache(str(root), path=cache_path)

    c.unlink()

    fresh_result, removed = verify_scan_cache(cached)

    assert removed == 1
    assert len(fresh_result.exact_duplicate_groups) == 1
    assert len(fresh_result.exact_duplicate_groups[0].units) == 2
