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
