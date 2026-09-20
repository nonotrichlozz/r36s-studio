"""Tests de `android/emulators.py` -- catalogue local des émulateurs
Android recommandés (`android/data/emulateurs.json`, jamais en dur dans le
code, § brief). Vérifie en particulier que le fichier de données réel du
dépôt ne prétend aucune licence ni aucun prix sans vérification (demandé
explicitement)."""

from __future__ import annotations

import json

import pytest

from r36s_studio.android import emulators
from r36s_studio.android.models import VALEUR_INCONNUE, AndroidDeviceInfo


def _device(abi="arm64-v8a", android_version="13"):
    return AndroidDeviceInfo(
        serial="SER1",
        manufacturer="Retroid",
        model="RP Flip 2",
        product_name="flip2",
        android_version=android_version,
        abi=abi,
    )


def _entry(**overrides):
    defaults = dict(
        id="x",
        nom="X",
        systemes_emules=["Y"],
        licence=emulators.SENTINEL_A_VERIFIER,
        prix=emulators.SENTINEL_A_VERIFIER,
        statut_projet="actif",
        url_officielle="https://example.invalid/",
        source_url="https://example.invalid/",
    )
    defaults.update(overrides)
    return emulators.EmulatorEntry(**defaults)


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


def test_load_emulators_optional_capability_fields_default_to_none(tmp_path):
    """`architecture_minimale`/`android_minimum` sont optionnels -- absents
    du JSON, ils valent `None` (aucune restriction connue), jamais une
    valeur inventée."""
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
                        "statut_projet": "actif",
                        "url_officielle": "https://example.invalid/",
                        "source_url": "https://example.invalid/",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    catalog = emulators.load_emulators(path)

    assert catalog.emulateurs[0].architecture_minimale is None
    assert catalog.emulateurs[0].android_minimum is None


def test_load_emulators_reads_optional_capability_fields_when_present(tmp_path):
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
                        "statut_projet": "actif",
                        "url_officielle": "https://example.invalid/",
                        "source_url": "https://example.invalid/",
                        "architecture_minimale": "arm64-v8a",
                        "android_minimum": "12",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    catalog = emulators.load_emulators(path)

    assert catalog.emulateurs[0].architecture_minimale == "arm64-v8a"
    assert catalog.emulateurs[0].android_minimum == "12"


# --- is_realistic_for_device / filter_for_device --------------------------


def test_is_realistic_for_device_true_when_no_restriction():
    entry = _entry()

    assert emulators.is_realistic_for_device(entry, _device(abi="armeabi-v7a", android_version="5.0")) is True


def test_is_realistic_for_device_false_when_architecture_does_not_match():
    entry = _entry(architecture_minimale="arm64-v8a")

    assert emulators.is_realistic_for_device(entry, _device(abi="armeabi-v7a")) is False


def test_is_realistic_for_device_true_when_architecture_matches():
    entry = _entry(architecture_minimale="arm64-v8a")

    assert emulators.is_realistic_for_device(entry, _device(abi="arm64-v8a")) is True


def test_is_realistic_for_device_false_when_android_version_too_old():
    entry = _entry(android_minimum="12")

    assert emulators.is_realistic_for_device(entry, _device(android_version="8.1")) is False


def test_is_realistic_for_device_true_when_android_version_meets_minimum():
    entry = _entry(android_minimum="8.0")

    assert emulators.is_realistic_for_device(entry, _device(android_version="8.0")) is True
    assert emulators.is_realistic_for_device(entry, _device(android_version="13")) is True


def test_is_realistic_for_device_handles_multi_segment_versions():
    entry = _entry(android_minimum="8.0")

    assert emulators.is_realistic_for_device(entry, _device(android_version="7.1.2")) is False
    assert emulators.is_realistic_for_device(entry, _device(android_version="9.0.1")) is True


def test_is_realistic_for_device_never_rejects_on_unparseable_version():
    """Un format de version inattendu ne doit jamais faire disparaître une
    entrée sur une simple supposition."""
    entry = _entry(android_minimum="8.0")

    assert emulators.is_realistic_for_device(entry, _device(android_version="Q")) is True


def test_filter_for_device_returns_generic_catalog_when_device_is_none():
    catalog = emulators.EmulatorCatalog(avertissement="A.", emulateurs=[_entry(id="a"), _entry(id="b")])

    result = emulators.filter_for_device(catalog, None)

    assert result.generique is True
    assert [entry.id for entry in result.emulateurs] == ["a", "b"]
    assert result.avertissement == "A."


def test_filter_for_device_returns_generic_catalog_when_abi_unknown():
    catalog = emulators.EmulatorCatalog(avertissement="", emulateurs=[_entry()])
    device = _device(abi=VALEUR_INCONNUE)

    result = emulators.filter_for_device(catalog, device)

    assert result.generique is True


def test_filter_for_device_returns_generic_catalog_when_android_version_unknown():
    catalog = emulators.EmulatorCatalog(avertissement="", emulateurs=[_entry()])
    device = _device(android_version=VALEUR_INCONNUE)

    result = emulators.filter_for_device(catalog, device)

    assert result.generique is True


def test_filter_for_device_filters_when_device_info_is_known():
    catalog = emulators.EmulatorCatalog(
        avertissement="",
        emulateurs=[
            _entry(id="leger"),
            _entry(id="exigeant", architecture_minimale="arm64-v8a", android_minimum="12"),
        ],
    )

    result = emulators.filter_for_device(catalog, _device(abi="armeabi-v7a", android_version="8.0"))

    assert result.generique is False
    assert [entry.id for entry in result.emulateurs] == ["leger"]


def test_filter_for_device_keeps_full_list_for_a_capable_device():
    catalog = emulators.load_emulators()

    result = emulators.filter_for_device(catalog, _device(abi="arm64-v8a", android_version="13"))

    assert result.generique is False
    assert len(result.emulateurs) == len(catalog.emulateurs)
