"""Tests de l'orchestration de sauvegarde (imaging/backup.py). Le
périphérique est simulé par un fichier local et `prepared_source` (démontage
macOS) est neutralisé — ces deux points sont déjà couverts par
`test_source.py`. Aucun disque réel n'est touché ni écrit."""

from __future__ import annotations

import contextlib
import os
import struct
from unittest.mock import patch

from r36s_studio.devices import Device
from r36s_studio.imaging.backup import backup_device

PARTITION_TABLE_OFFSET = 446


@contextlib.contextmanager
def _no_prep(path):
    yield path


def _build_fake_sd_image(tmp_path, total_size: int, last_partition_end_sectors: int):
    """Fichier factice avec un MBR pointant sur une seule partition qui
    s'arrête bien avant la fin du fichier, pour vérifier que seule la
    partie utile est copiée."""
    data = bytearray(os.urandom(total_size))
    # Table de partitions à zéro d'abord : sinon les 3 entrées inutilisées
    # restent des octets aléatoires que parse_mbr prendrait pour de vraies
    # partitions.
    data[PARTITION_TABLE_OFFSET : PARTITION_TABLE_OFFSET + 4 * 16] = bytes(4 * 16)
    data[PARTITION_TABLE_OFFSET + 4] = 0x0B  # FAT32
    data[PARTITION_TABLE_OFFSET + 8 : PARTITION_TABLE_OFFSET + 12] = struct.pack("<I", 1)
    data[PARTITION_TABLE_OFFSET + 12 : PARTITION_TABLE_OFFSET + 16] = struct.pack(
        "<I", last_partition_end_sectors - 1
    )
    data[510:512] = b"\x55\xaa"
    path = tmp_path / "fake_sd.img"
    path.write_bytes(bytes(data))
    return str(path), last_partition_end_sectors * 512


def _make_device(path: str, size_bytes: int) -> Device:
    return Device(
        path=path,
        display="Carte SD factice",
        size_bytes=size_bytes,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=[],
    )


@patch("r36s_studio.imaging.backup.prepared_source", side_effect=_no_prep)
def test_backup_stops_at_last_partition_end_not_full_device(mock_prep, tmp_path):
    total_size = 200_000
    source_path, expected_bytes = _build_fake_sd_image(
        tmp_path, total_size=total_size, last_partition_end_sectors=300
    )
    device = _make_device(source_path, total_size)
    output_path = tmp_path / "backup.img"

    copied = backup_device(device, str(output_path))

    assert copied == expected_bytes
    assert copied < total_size  # sauvegarde intelligente : pas tout le disque
    assert output_path.stat().st_size == expected_bytes

    with open(source_path, "rb") as f:
        expected_data = f.read(expected_bytes)
    assert output_path.read_bytes() == expected_data


@patch("r36s_studio.imaging.backup.prepared_source", side_effect=_no_prep)
def test_backup_falls_back_to_full_size_without_partition_table(mock_prep, tmp_path):
    data = os.urandom(50_000)  # pas de signature MBR
    source_path = tmp_path / "blank.img"
    source_path.write_bytes(data)
    device = _make_device(str(source_path), len(data))
    output_path = tmp_path / "backup.img"

    copied = backup_device(device, str(output_path))

    assert copied == len(data)
    assert output_path.read_bytes() == data


@patch("r36s_studio.imaging.backup.prepared_source", side_effect=_no_prep)
def test_backup_never_opens_device_for_writing(mock_prep, tmp_path):
    """Le device n'est jamais ouvert autrement qu'en lecture : le fichier
    source doit être strictement inchangé après la sauvegarde."""
    total_size = 40_000
    source_path, _ = _build_fake_sd_image(tmp_path, total_size=total_size, last_partition_end_sectors=50)
    before = open(source_path, "rb").read()

    device = _make_device(source_path, total_size)
    backup_device(device, str(tmp_path / "backup.img"))

    after = open(source_path, "rb").read()
    assert before == after


@patch("r36s_studio.imaging.backup.prepared_source", side_effect=_no_prep)
def test_backup_reports_progress_up_to_expected_total(mock_prep, tmp_path):
    source_path, expected_bytes = _build_fake_sd_image(
        tmp_path, total_size=20_000, last_partition_end_sectors=30
    )
    device = _make_device(source_path, 20_000)
    events = []

    backup_device(device, str(tmp_path / "out.img"), on_progress=events.append, block_size=1024)

    assert events
    assert events[-1].done == expected_bytes
    assert events[-1].total == expected_bytes


@patch("r36s_studio.imaging.backup.prepared_source", side_effect=_no_prep)
def test_backup_uses_prepared_source_with_device_path(mock_prep, tmp_path):
    source_path, _ = _build_fake_sd_image(tmp_path, total_size=20_000, last_partition_end_sectors=30)
    device = _make_device(source_path, 20_000)

    backup_device(device, str(tmp_path / "out.img"))

    mock_prep.assert_called_once_with(source_path)
