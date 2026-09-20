"""Tests de `android/emulators.py` -- catalogue local des émulateurs
Android recommandés (`android/data/emulateurs.json`, jamais en dur dans le
code, § brief). Vérifie en particulier que le fichier de données réel du
dépôt ne prétend aucune licence ni aucun prix sans vérification (demandé
explicitement)."""

from __future__ import annotations

import json

import pytest

from r36s_studio.android import emulators


def test_load_emulators_reads_the_real_data_file():
    catalog = emulators.load_emulators()

    assert catalog.avertissement
    assert len(catalog.emulateurs) >= 1


def test_load_emulators_never_asserts_a_licence_or_price_without_verification():
    """Demandé explicitement : aucune entrée de départ n'affirme une
    licence ni un prix -- toutes doivent porter `SENTINEL_A_VERIFIER`
    jusqu'à vérification humaine sur la page officielle du projet."""
    catalog = emulators.load_emulators()

    for entry in catalog.emulateurs:
        assert entry.licence == emulators.SENTINEL_A_VERIFIER, entry.id
        assert entry.prix == emulators.SENTINEL_A_VERIFIER, entry.id
        assert entry.telechargement_auto_autorise is False, entry.id


def test_load_emulators_entries_have_a_source_url_and_official_url():
    catalog = emulators.load_emulators()

    for entry in catalog.emulateurs:
        assert entry.source_url.startswith("http")
        assert entry.url_officielle.startswith("http")
        assert entry.systemes_emules


def test_load_emulators_contains_the_newly_requested_entries():
    """Console/systèmes demandés explicitement, vérifiés individuellement
    avant l'ajout (URL officielle/source réelle, statut du projet) --
    chaque `id` doit exister dans le catalogue réel du dépôt."""
    catalog = emulators.load_emulators()
    ids = {entry.id for entry in catalog.emulateurs}

    for expected_id in (
        "eden",
        "nethersx2",
        "vita3k",
        "azahar",
        "melonds_android",
        "flycast",
        "redream",
    ):
        assert expected_id in ids


def test_load_emulators_dolphin_covers_gamecube_and_wii():
    catalog = emulators.load_emulators()
    dolphin = next(entry for entry in catalog.emulateurs if entry.id == "dolphin")

    assert "GameCube" in dolphin.systemes_emules
    assert "Wii" in dolphin.systemes_emules


def test_load_emulators_nethersx2_mentions_aethersx2_being_unmaintained():
    catalog = emulators.load_emulators()
    nethersx2 = next(entry for entry in catalog.emulateurs if entry.id == "nethersx2")

    combined = " ".join(nethersx2.systemes_emules).lower()
    assert "aethersx2" in combined
    assert "2023" in combined or "arrêt" in combined or "abandon" in combined


def test_load_emulators_does_not_contain_xbox_or_wiiu_entries():
    """Demandé explicitement : aucun émulateur Android fonctionnel connu
    pour Xbox/Xbox 360/Wii U -- ne pas en ajouter sans une source fiable
    proposée d'abord à l'utilisateur."""
    catalog = emulators.load_emulators()
    noms = " ".join(entry.nom.lower() for entry in catalog.emulateurs)

    assert "xbox" not in noms
    assert "wii u" not in noms
    assert "cemu" not in noms
    assert "xenia" not in noms


def test_load_emulators_from_explicit_path(tmp_path):
    path = tmp_path / "emulateurs.json"
    path.write_text(
        json.dumps(
            {
                "avertissement": "Test.",
                "emulateurs": [
                    {
                        "id": "x",
                        "nom": "X",
                        "systemes_emules": ["Y"],
                        "licence": "a_verifier",
                        "prix": "a_verifier",
                        "statut_projet": "actif",
                        "url_officielle": "https://example.invalid/",
                        "source_url": "https://example.invalid/",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    catalog = emulators.load_emulators(path)

    assert catalog.avertissement == "Test."
    assert catalog.emulateurs[0].id == "x"
    assert catalog.emulateurs[0].telechargement_auto_autorise is False  # valeur par défaut, absente du JSON


def test_load_emulators_raises_on_missing_required_field(tmp_path):
    path = tmp_path / "emulateurs.json"
    path.write_text(json.dumps({"emulateurs": [{"id": "x", "nom": "X"}]}), encoding="utf-8")

    with pytest.raises(ValueError):
        emulators.load_emulators(path)


def test_load_emulators_raises_when_systemes_emules_is_not_a_list(tmp_path):
    path = tmp_path / "emulateurs.json"
    path.write_text(
        json.dumps(
            {
                "emulateurs": [
                    {
                        "id": "x",
                        "nom": "X",
                        "systemes_emules": "pas une liste",
                        "licence": "a_verifier",
                        "prix": "a_verifier",
                        "statut_projet": "actif",
                        "url_officielle": "https://example.invalid/",
                        "source_url": "https://example.invalid/",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        emulators.load_emulators(path)


def test_load_emulators_with_empty_list_returns_empty_catalog(tmp_path):
    path = tmp_path / "emulateurs.json"
    path.write_text(json.dumps({"avertissement": "A.", "emulateurs": []}), encoding="utf-8")

    catalog = emulators.load_emulators(path)

    assert catalog.emulateurs == []


def test_load_emulators_raises_when_statut_projet_is_not_a_known_value(tmp_path):
    path = tmp_path / "emulateurs.json"
    path.write_text(
        json.dumps(
            {
                "emulateurs": [
                    {
                        "id": "x",
                        "nom": "X",
                        "systemes_emules": ["Y"],
                        "licence": "a_verifier",
                        "prix": "a_verifier",
                        "statut_projet": "en_pleine_forme",
                        "url_officielle": "https://example.invalid/",
                        "source_url": "https://example.invalid/",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        emulators.load_emulators(path)


def test_load_emulators_entries_have_a_known_statut_projet():
    catalog = emulators.load_emulators()

    for entry in catalog.emulateurs:
        assert entry.statut_projet in emulators.STATUT_PROJET_VALUES, entry.id
