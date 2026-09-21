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


# --- Classement par console émulée (categorize/count_by_category/
# filter_by_category) -----------------------------------------------------


def test_categorize_falls_back_to_retro_for_multi_system_text():
    assert emulators.categorize(_entry(systemes_emules=["Multi-système (cœurs libretro)"])) == ["retro"]


def test_categorize_falls_back_to_retro_for_a_system_not_in_the_named_categories():
    """Nintendo 64 n'est pas l'une des quatorze catégories demandées --
    repli sur « Rétro », jamais une catégorie inventée."""
    assert emulators.categorize(_entry(systemes_emules=["Nintendo 64"])) == ["retro"]


@pytest.mark.parametrize(
    "systemes, expected",
    [
        (["GameCube"], ["gc_wii"]),
        (["Wii"], ["gc_wii"]),
        (["GameCube", "Wii"], ["gc_wii"]),  # une seule catégorie, jamais dupliquée
        (["Wii U"], ["wii_u"]),
        (["Nintendo Switch"], ["switch"]),
        (["Nintendo DS"], ["ds"]),
        (["Nintendo DSi"], ["ds"]),
        (["Nintendo 3DS"], ["n3ds"]),
        (["PlayStation (PS1)"], ["ps1"]),
        (["PlayStation 2"], ["ps2"]),
        (["PlayStation 3"], ["ps3"]),
        (["PSP"], ["psp"]),
        (["PlayStation Vita"], ["ps_vita"]),
        (["Xbox"], ["xbox"]),
        (["Xbox 360"], ["xbox360"]),
        (["Dreamcast"], ["dreamcast"]),
        (["Applications et jeux Windows (via Wine)"], ["pc"]),
    ],
)
def test_categorize_matches_each_named_category(systemes, expected):
    assert emulators.categorize(_entry(systemes_emules=systemes)) == expected


def test_categorize_wii_u_never_also_matches_gc_wii():
    """Bug potentiel écarté explicitement : "Wii" est un mot complet à
    l'intérieur de "Wii U", un classement naïf y verrait aussi GC/Wii."""
    assert emulators.categorize(_entry(systemes_emules=["Wii U"])) == ["wii_u"]


def test_categorize_xbox_360_never_also_matches_xbox():
    assert emulators.categorize(_entry(systemes_emules=["Xbox 360"])) == ["xbox360"]


def test_categorize_n3ds_never_also_matches_ds():
    assert emulators.categorize(_entry(systemes_emules=["Nintendo 3DS"])) == ["n3ds"]


def test_categorize_ignores_descriptive_sentences_that_name_no_console():
    """Certaines entrées portent une phrase descriptive en plus du nom du
    système (ex. NetherSX2/Azahar) -- ignorée par le classement, elle ne
    doit jamais produire de catégorie fantôme ni faire échouer le calcul."""
    entry = _entry(
        systemes_emules=[
            "PlayStation 2",
            "Suite communautaire d'AetherSX2, dont le développement a été arrêté par son auteur en 2023",
        ]
    )

    assert emulators.categorize(entry) == ["ps2"]


def test_categorize_can_return_multiple_categories_for_one_entry():
    entry = _entry(systemes_emules=["PlayStation 2", "Nintendo Switch"])

    assert set(emulators.categorize(entry)) == {"ps2", "switch"}


def test_count_by_category_includes_every_category_even_at_zero():
    counts = emulators.count_by_category([_entry(systemes_emules=["PSP"])])

    assert set(counts) == {category_id for category_id, _ in emulators.CATEGORIES}
    assert counts["psp"] == 1
    assert counts["xbox"] == 0


def test_count_by_category_on_the_real_catalog_matches_manual_expectations():
    catalog = emulators.load_emulators()
    counts = emulators.count_by_category(catalog.emulateurs)

    assert counts["xbox"] == 0
    assert counts["xbox360"] == 0
    assert counts["wii_u"] == 0
    assert counts["ps3"] == 0
    assert counts["dreamcast"] == 2  # flycast + redream
    assert sum(counts.values()) >= len(catalog.emulateurs)  # >= : une entrée peut compter dans 2 catégories


def test_filter_by_category_none_returns_full_list():
    entries = [_entry(id="a"), _entry(id="b", systemes_emules=["PSP"])]

    assert emulators.filter_by_category(entries, None) == entries


def test_filter_by_category_returns_only_matching_entries():
    entries = [
        _entry(id="a", systemes_emules=["PSP"]),
        _entry(id="b", systemes_emules=["Nintendo Switch"]),
    ]

    assert [e.id for e in emulators.filter_by_category(entries, "psp")] == ["a"]


def test_filter_by_category_unknown_category_returns_empty_list():
    entries = [_entry(id="a", systemes_emules=["PSP"])]

    assert emulators.filter_by_category(entries, "wii_u") == []


# --- Variantes (EmulatorVariant) -------------------------------------------


def test_load_emulators_entries_without_variantes_default_to_empty_list(tmp_path):
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

    assert catalog.emulateurs[0].variantes == []


def test_load_emulators_reads_variantes_when_present(tmp_path):
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
                        "variantes": [
                            {
                                "nom": "Standard",
                                "url_officielle": "https://example.invalid/standard",
                                "source_url": "https://example.invalid/standard",
                            },
                            {
                                "nom": "Edge",
                                "url_officielle": "https://example.invalid/edge",
                                "source_url": "https://example.invalid/edge",
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    catalog = emulators.load_emulators(path)

    variantes = catalog.emulateurs[0].variantes
    assert [v.nom for v in variantes] == ["Standard", "Edge"]
    assert variantes[0].url_officielle == "https://example.invalid/standard"


def test_load_emulators_raises_on_variante_missing_required_field(tmp_path):
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
                        "variantes": [{"nom": "Standard"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        emulators.load_emulators(path)


def test_load_emulators_real_catalog_variant_entries_have_at_least_two_variants():
    """Vérifié individuellement avant l'ajout (deux forks communautaires
    réels et distincts) -- jamais une seule variante isolée, qui n'aurait
    aucun sens dans un menu déroulant."""
    catalog = emulators.load_emulators()
    with_variants = [entry for entry in catalog.emulateurs if entry.variantes]

    assert len(with_variants) >= 1
    for entry in with_variants:
        assert len(entry.variantes) >= 2, entry.id
        for variant in entry.variantes:
            assert variant.url_officielle.startswith("http")
            assert variant.source_url.startswith("http")
