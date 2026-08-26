"""Tests de l'orchestration d'écriture (imaging/flash.py). Le périphérique
est simulé par un fichier local et `prepared_write_target` (démontage /
verrouillage par OS, déjà couvert par test_write_target.py) est neutralisé.
Aucun disque réel n'est touché."""

from __future__ import annotations

import contextlib
import gzip
import hashlib
from unittest.mock import patch

from r36s_studio.devices import Device
from r36s_studio.imaging.flash import flash_device

FAKE_IMAGE_DATA = b"R36S-fake-disk-image-" * 1000  # 22 000 octets


@contextlib.contextmanager
def _no_prep(device):
    yield device.path


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


def _make_fake_target(tmp_path, size: int) -> str:
    """Un fichier régulier assez grand pour recevoir l'image, faisant office
    de périphérique cible ouvert en "r+b"."""
    path = tmp_path / "fake_target.img"
    path.write_bytes(bytes(size))
    return str(path)


@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_writes_plain_img_and_verifies(mock_prep, tmp_path):
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)

    result = flash_device(device, str(image_path))

    assert result.bytes_written == len(FAKE_IMAGE_DATA)
    assert result.verified is True
    assert result.source_sha256 == hashlib.sha256(FAKE_IMAGE_DATA).hexdigest()
    assert result.written_sha256 == result.source_sha256

    with open(target_path, "rb") as f:
        assert f.read(len(FAKE_IMAGE_DATA)) == FAKE_IMAGE_DATA


@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_decompresses_gz_on_the_fly(mock_prep, tmp_path):
    image_path = tmp_path / "src.img.gz"
    image_path.write_bytes(gzip.compress(FAKE_IMAGE_DATA))
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)

    result = flash_device(device, str(image_path))

    assert result.bytes_written == len(FAKE_IMAGE_DATA)
    assert result.verified is True
    with open(target_path, "rb") as f:
        assert f.read(len(FAKE_IMAGE_DATA)) == FAKE_IMAGE_DATA


@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_never_writes_beyond_source_length(mock_prep, tmp_path):
    """Le reste du fichier cible (au-delà de l'image écrite) doit rester
    inchangé -- le flash ne doit jamais écraser plus que la source."""
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    extra = 5000
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + extra)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + extra)

    flash_device(device, str(image_path))

    with open(target_path, "rb") as f:
        f.seek(len(FAKE_IMAGE_DATA))
        tail = f.read()
    assert tail == bytes(extra)  # toujours des zéros, jamais touché


@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_reports_progress(mock_prep, tmp_path):
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)
    events = []

    flash_device(device, str(image_path), on_progress=events.append, block_size=1024)

    assert events
    assert events[-1].done == len(FAKE_IMAGE_DATA)


@patch("r36s_studio.imaging.flash._hash_file_range", return_value="hash-invalide")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_reports_verification_failure_without_raising(mock_prep, mock_hash, tmp_path):
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)

    result = flash_device(device, str(image_path))

    assert result.verified is False
    assert result.written_sha256 == "hash-invalide"
    assert result.source_sha256 != result.written_sha256


@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_prep)
def test_flash_uses_prepared_write_target_with_device(mock_prep, tmp_path):
    image_path = tmp_path / "src.img"
    image_path.write_bytes(FAKE_IMAGE_DATA)
    target_path = _make_fake_target(tmp_path, len(FAKE_IMAGE_DATA) + 1000)
    device = _make_device(target_path, len(FAKE_IMAGE_DATA) + 1000)

    flash_device(device, str(image_path))

    mock_prep.assert_called_once_with(device)
