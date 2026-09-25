"""Tests de cohérence des tables du tri (docs/tri-roms.md). Le risque
principal de l'outil est un nom de dossier faux : ces tests figent les
noms relevés dans les sources officielles, pour qu'un changement soit
toujours un choix explicite, jamais un effet de bord."""

from __future__ import annotations

import pytest

from r36s_studio.identify.firmware_catalog import FIRMWARE_BY_ID
from r36s_studio.tri.tables import SORT_FIRMWARE_IDS, extension_map, load_firmware_tables, load_systems


def test_every_extension_belongs_to_a_single_system():
    # `extension_map` lève si une extension est déclarée deux fois.
    assert ".sfc" in extension_map()


def test_every_firmware_table_is_offered_and_documented():
    tables = load_firmware_tables()
    assert set(tables) == set(SORT_FIRMWARE_IDS)
    for table in tables.values():
        assert table.source and table.source_date


def test_only_the_real_card_table_claims_hardware_verification():
    # docs/tri-roms.md : seule TreeFrogUI a été relevée sur une vraie
    # carte. Changer ce test = avoir vérifié une autre table sur du
    # vrai matériel, et le documenter.
    verified = {firmware for firmware, table in load_firmware_tables().items() if table.verified_on_hardware}
    assert verified == {"treefrogui"}


def test_catalogue_firmwares_share_their_id():
    for firmware in ("arkos", "rocknix", "emuelec"):
        assert firmware in FIRMWARE_BY_ID


def test_tables_only_reference_known_systems():
    systems = set(load_systems())
    for table in load_firmware_tables().values():
        assert set(table.folders) <= systems


@pytest.mark.parametrize("firmware", ["arkos", "rocknix", "emuelec"])
def test_every_routed_extension_is_accepted_by_its_folder(firmware):
    """Relevé dans les fichiers officiels : un fichier rangé dans un
    dossier qui n'accepte pas son extension serait invisible."""
    table = load_firmware_tables()[firmware]
    for system_id, system in load_systems().items():
        if system_id not in table.folders:
            continue
        accepted = table.accepted_extensions[system_id]
        for extension in list(system.extensions) + [".zip"]:
            assert extension in accepted, (firmware, system_id, extension)


@pytest.mark.parametrize(
    "firmware, system_id, folder",
    [
        ("arkos", "megadrive", "megadrive"),
        ("arkos", "colecovision", "coleco"),
        ("rocknix", "colecovision", "coleco"),
        ("emuelec", "colecovision", "coleco"),
        ("rocknix", "sega32x", "sega32x"),
        ("treefrogui", "megadrive", "sega"),
        ("treefrogui", "mastersystem", "sega"),
        ("treefrogui", "gbc", "gb"),
        ("treefrogui", "colecovision", "col"),
    ],
)
def test_folder_names_that_differ_between_firmwares(firmware, system_id, folder):
    assert load_firmware_tables()[firmware].folders[system_id] == folder


def test_known_gaps_are_absent_rather_than_guessed():
    tables = load_firmware_tables()
    assert "fds" not in tables["arkos"].folders  # absent d'es_systems.cfg de dArkOS
    assert "n64" not in tables["treefrogui"].folders  # aucun cœur N64 sur la carte SF3000
