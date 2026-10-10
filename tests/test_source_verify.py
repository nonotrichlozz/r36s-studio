"""Double lecture de la source et empreintes par bloc
(imaging/source_verify.py) -- incident réel : une carte dégradée a renvoyé
des octets faux sans erreur d'E/S, l'image fausse a ensuite été flashée et
« vérifiée ». Source simulée par un fichier local ou un faux flux qui ment ;
`prepared_source`/`prepared_write_target` neutralisés. Aucun disque réel."""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import struct
from unittest.mock import patch

import pytest

from r36s_studio.devices import Device
from r36s_studio.imaging.backup import backup_device
from r36s_studio.imaging.copy import OperationCancelled
from r36s_studio.imaging.flash import UnstableImageRefused, flash_device
from r36s_studio.imaging.source_verify import (
    ImageModified,
    SourceUnstable,
    read_block_digests,
    sidecar_path,
    verify_source,
    write_block_digests,
)

BLOCK = 1024
PARTITION_TABLE_OFFSET = 446


@contextlib.contextmanager
def _no_prep(path):
    yield path


@contextlib.contextmanager
def _no_write_prep(device):
    yield device.path


def _make_device(path: str, size_bytes: int) -> Device:
    return Device(
        path=path, display="Carte SD factice", size_bytes=size_bytes, removable=True, bus="USB",
        is_system=False, mountpoints=[],
    )


def _fake_sd(tmp_path, sectors: int = 20) -> str:
    """MBR à une partition qui couvre `sectors` secteurs -- 10 Ko, soit 10
    blocs de 1 Kio dont le dernier est complet."""
    data = bytearray(os.urandom(sectors * 512 + 4096))
    data[PARTITION_TABLE_OFFSET : PARTITION_TABLE_OFFSET + 64] = bytes(64)
    data[PARTITION_TABLE_OFFSET + 4] = 0x0B
    data[PARTITION_TABLE_OFFSET + 8 : PARTITION_TABLE_OFFSET + 12] = struct.pack("<I", 1)
    data[PARTITION_TABLE_OFFSET + 12 : PARTITION_TABLE_OFFSET + 16] = struct.pack("<I", sectors - 1)
    data[510:512] = b"\x55\xaa"
    path = tmp_path / "fake_sd.img"
    path.write_bytes(bytes(data))
    return str(path)


class _LyingSource(io.BytesIO):
    """Flux qui inverse un bit du bloc `bad_offset` aux lectures dont le
    numéro (1 = la copie) est dans `lie_on` -- la flash dégradée de
    l'incident, qui renvoie des octets différents d'une lecture à l'autre."""

    def __init__(self, data: bytes, bad_offset: int, lie_on):
        super().__init__(data)
        self._bad_offset = bad_offset
        self._lie_on = lie_on
        self._reads_of_bad_block = 0

    def read(self, n=-1):
        start = self.tell()
        chunk = super().read(n)
        if start <= self._bad_offset < start + len(chunk):
            self._reads_of_bad_block += 1
            if self._lie_on(self._reads_of_bad_block):
                i = self._bad_offset - start
                chunk = chunk[:i] + bytes([chunk[i] ^ 0x01]) + chunk[i + 1 :]
        return chunk


def _digests(data: bytes, block: int = BLOCK):
    return [hashlib.sha256(data[i : i + block]).hexdigest() for i in range(0, len(data), block)]


# --- double lecture de la source -------------------------------------------


@patch("r36s_studio.imaging.backup.prepared_source", side_effect=_no_prep)
def test_stable_source_backup_succeeds_and_writes_correct_sidecar(mock_prep, tmp_path):
    source_path = _fake_sd(tmp_path)
    output = tmp_path / "out.img"

    copied = backup_device(_make_device(source_path, 1 << 20), str(output), block_size=BLOCK)

    produced = output.read_bytes()
    assert copied == len(produced) == 20 * 512
    block_size, total, digests = read_block_digests(sidecar_path(str(output)))
    assert (block_size, total) == (BLOCK, len(produced))
    assert digests == _digests(produced)
    with open(sidecar_path(str(output)), encoding="ascii") as f:
        assert f.readline().strip() == f"R36S-SHA256BLOCKS 1 block_size={BLOCK} total_size={len(produced)}"


def test_lying_source_raises_source_unstable_with_byte_range():
    data = os.urandom(10 * BLOCK)
    # Bloc 3 : juste à la copie (empreintes de `data`), faux à toutes les relectures.
    source = _LyingSource(data, bad_offset=3 * BLOCK + 17, lie_on=lambda n: True)

    with pytest.raises(SourceUnstable) as excinfo:
        verify_source(source, _digests(data), len(data), BLOCK)

    assert excinfo.value.ranges == [(3 * BLOCK, 4 * BLOCK)]
    assert f"{3 * BLOCK}-{4 * BLOCK - 1}" in str(excinfo.value)


def test_source_that_lies_once_then_stabilises_passes():
    data = os.urandom(10 * BLOCK)
    # Lecture 2 (première relecture) fausse, puis deux relectures justes.
    source = _LyingSource(data, bad_offset=5 * BLOCK, lie_on=lambda n: n == 2)
    source.read(len(data))  # la copie (lecture n°1)

    verify_source(source, _digests(data), len(data), BLOCK)


def test_short_last_block_is_reread_with_its_own_length():
    data = os.urandom(3 * BLOCK + 512)
    verify_source(io.BytesIO(data), _digests(data), len(data), BLOCK)


def test_cancel_during_verification_raises_operation_cancelled():
    data = os.urandom(10 * BLOCK)
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 4

    with pytest.raises(OperationCancelled) as excinfo:
        verify_source(io.BytesIO(data), _digests(data), len(data), BLOCK, should_cancel=should_cancel)
    assert excinfo.value.done == 4 * BLOCK


def test_verification_reports_its_own_progress_phase():
    data = os.urandom(4 * BLOCK)
    events = []
    verify_source(io.BytesIO(data), _digests(data), len(data), BLOCK, on_progress=events.append)
    assert events[-1].phase == "verify_source"
    assert (events[-1].done, events[-1].total) == (len(data), len(data))


@patch("r36s_studio.imaging.backup.verify_source", side_effect=SourceUnstable([(0, BLOCK)]))
@patch("r36s_studio.imaging.backup.prepared_source", side_effect=_no_prep)
def test_unstable_backup_is_kept_as_instable_never_deleted(mock_prep, mock_verify, tmp_path):
    output = tmp_path / "out.img"

    with pytest.raises(SourceUnstable) as excinfo:
        backup_device(_make_device(_fake_sd(tmp_path), 1 << 20), str(output), block_size=BLOCK)

    unstable = tmp_path / "out.img.instable"
    assert excinfo.value.image_path == str(unstable)
    assert not output.exists() and unstable.stat().st_size == 20 * 512
    assert f"0-{BLOCK - 1}" in (tmp_path / "out.img.instable.txt").read_text(encoding="utf-8")
    assert not os.path.exists(sidecar_path(str(output)))


@patch("r36s_studio.imaging.backup.verify_source")
@patch("r36s_studio.imaging.backup.prepared_source", side_effect=_no_prep)
def test_double_read_can_be_disabled(mock_prep, mock_verify, tmp_path):
    output = tmp_path / "out.img"
    backup_device(_make_device(_fake_sd(tmp_path), 1 << 20), str(output), block_size=BLOCK, double_read=False)
    mock_verify.assert_not_called()
    assert os.path.exists(sidecar_path(str(output)))


# --- vérification de l'image avant le flash --------------------------------


def _image_with_sidecar(tmp_path, data: bytes) -> str:
    image = tmp_path / "sauvegarde.img"
    image.write_bytes(data)
    write_block_digests(str(image), _digests(data), BLOCK, len(data))
    return str(image)


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_write_prep)
def test_flash_refuses_image_modified_after_backup_before_any_write(mock_prep, mock_reunmount, tmp_path):
    data = os.urandom(6 * BLOCK)
    image = _image_with_sidecar(tmp_path, data)
    with open(image, "r+b") as f:  # 1 octet modifié après la sauvegarde
        f.seek(4 * BLOCK + 3)
        f.write(bytes([data[4 * BLOCK + 3] ^ 0xFF]))
    target = tmp_path / "target.img"
    target.write_bytes(bytes(len(data)))

    with pytest.raises(ImageModified) as excinfo:
        flash_device(_make_device(str(target), len(data)), image)

    assert excinfo.value.ranges == [(4 * BLOCK, 5 * BLOCK)]
    mock_prep.assert_not_called()
    assert target.read_bytes() == bytes(len(data))


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_write_prep)
def test_flash_with_intact_sidecar_writes_and_reports_verify_phase(mock_prep, mock_reunmount, tmp_path):
    data = os.urandom(6 * BLOCK)
    image = _image_with_sidecar(tmp_path, data)
    target = tmp_path / "target.img"
    target.write_bytes(bytes(len(data)))
    events, warnings = [], []

    result = flash_device(
        _make_device(str(target), len(data)), image, on_progress=events.append, on_warning=warnings.append
    )

    assert result.verified and target.read_bytes() == data
    assert "verify_image" in {e.phase for e in events}
    assert warnings == []


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_write_prep)
def test_flash_without_sidecar_is_allowed_with_a_warning(mock_prep, mock_reunmount, tmp_path):
    data = os.urandom(3 * BLOCK)
    image = tmp_path / "telechargee.img"
    image.write_bytes(data)
    target = tmp_path / "target.img"
    target.write_bytes(bytes(len(data)))
    warnings = []

    result = flash_device(_make_device(str(target), len(data)), str(image), on_warning=warnings.append)

    assert result.verified
    assert len(warnings) == 1


@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_write_prep)
def test_flash_refuses_sidecar_with_wrong_total_size(mock_prep, tmp_path):
    data = os.urandom(3 * BLOCK)
    image = _image_with_sidecar(tmp_path, data)
    with open(image, "ab") as f:
        f.write(b"\x00")

    with pytest.raises(ImageModified):
        flash_device(_make_device(str(tmp_path / "t.img"), 1 << 20), image)
    mock_prep.assert_not_called()


@patch("r36s_studio.imaging.flash.reunmount_before_verify")
@patch("r36s_studio.imaging.flash.prepared_write_target", side_effect=_no_write_prep)
def test_flash_refuses_instable_image_unless_explicitly_allowed(mock_prep, mock_reunmount, tmp_path):
    data = os.urandom(2 * BLOCK)
    image = tmp_path / "out.img.instable"
    image.write_bytes(data)
    target = tmp_path / "target.img"
    target.write_bytes(bytes(len(data)))
    device = _make_device(str(target), len(data))

    with pytest.raises(UnstableImageRefused):
        flash_device(device, str(image))
    mock_prep.assert_not_called()

    assert flash_device(device, str(image), allow_unstable=True).verified
