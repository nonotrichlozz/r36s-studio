"""CLI `backup`/`flash` et double lecture de la source / `.sha256blocks`
(imaging/source_verify.py) : codes d'erreur dédiés, drapeaux transmis,
événement `phase`. `list_devices`, `backup_device` et `flash_device` sont
mockés -- aucune carte réelle."""

from __future__ import annotations

import json
from collections import namedtuple
from unittest.mock import patch

from r36s_studio import __main__ as cli
from r36s_studio.devices import Device
from r36s_studio.imaging.copy import ProgressEvent
from r36s_studio.imaging.flash import FlashResult, UnstableImageRefused
from r36s_studio.imaging.source_verify import ImageModified, SourceUnstable

_Usage = namedtuple("_Usage", ["total", "used", "free"])


def _make_device() -> Device:
    return Device(
        path="/dev/fake-disk-test-3", display="Carte SD factice", size_bytes=32_000_000_000, removable=True,
        bus="USB", is_system=False, mountpoints=[],
    )


def _run(argv):
    args = cli.build_parser().parse_args(argv)
    return args.func(args)


def _events(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]


def _backup_argv(tmp_path, *extra):
    return ["backup", "--device", "/dev/fake-disk-test-3", "--output", str(tmp_path / "out.img"), *extra]


@patch("r36s_studio.__main__.shutil.disk_usage", return_value=_Usage(2 * 10**12, 10**12, 10**12))
@patch("r36s_studio.__main__.backup_device")
@patch("r36s_studio.__main__.list_devices", return_value=[_make_device()])
def test_backup_unstable_source_emits_source_unstable(mock_list, mock_backup, mock_usage, tmp_path, capsys):
    mock_backup.side_effect = SourceUnstable([(4096, 8192)], image_path=str(tmp_path / "out.img.instable"))

    assert _run(_backup_argv(tmp_path)) == 1

    errors = [e for e in _events(capsys) if e["type"] == "error"]
    assert errors[0]["code"] == "SOURCE_UNSTABLE"
    assert "4096-8191" in errors[0]["msg"] and "out.img.instable" in errors[0]["msg"]


@patch("r36s_studio.__main__.shutil.disk_usage", return_value=_Usage(2 * 10**12, 10**12, 10**12))
@patch("r36s_studio.__main__.backup_device", return_value=1000)
@patch("r36s_studio.__main__.list_devices", return_value=[_make_device()])
def test_backup_double_read_is_on_by_default_and_can_be_disabled(mock_list, mock_backup, mock_usage, tmp_path):
    assert _run(_backup_argv(tmp_path)) == 0
    assert mock_backup.call_args.kwargs["double_read"] is True

    assert _run(_backup_argv(tmp_path, "--no-source-verify")) == 0
    assert mock_backup.call_args.kwargs["double_read"] is False


@patch("r36s_studio.__main__.shutil.disk_usage", return_value=_Usage(2 * 10**12, 10**12, 10**12))
@patch("r36s_studio.__main__.backup_device")
@patch("r36s_studio.__main__.list_devices", return_value=[_make_device()])
def test_backup_emits_phase_event_when_verification_starts(mock_list, mock_backup, mock_usage, tmp_path, capsys):
    def fake_backup(device, output, on_progress, **kwargs):
        on_progress(ProgressEvent(done=10, total=10, speed=1.0))
        on_progress(ProgressEvent(done=5, total=10, speed=1.0, phase="verify_source"))
        return 10

    mock_backup.side_effect = fake_backup

    assert _run(_backup_argv(tmp_path)) == 0
    phases = [e["name"] for e in _events(capsys) if e["type"] == "phase"]
    assert phases == ["verify_source"]


def _flash_argv(tmp_path, name="sd.img", *extra):
    image = tmp_path / name
    image.write_bytes(b"x" * 100)
    return ["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3", "--worker", *extra]


@patch("r36s_studio.__main__.flash_device", side_effect=ImageModified("modifiée", [(0, 4096)]))
@patch("r36s_studio.__main__.list_devices", return_value=[_make_device()])
def test_flash_image_modified_emits_dedicated_code(mock_list, mock_flash, tmp_path, capsys):
    assert _run(_flash_argv(tmp_path)) == 1
    errors = [e for e in _events(capsys) if e["type"] == "error"]
    assert errors[0]["code"] == "IMAGE_MODIFIED"
    assert "0-4095" in errors[0]["msg"]


@patch("r36s_studio.__main__.flash_device", side_effect=UnstableImageRefused("instable"))
@patch("r36s_studio.__main__.list_devices", return_value=[_make_device()])
def test_flash_unstable_image_refused_by_default(mock_list, mock_flash, tmp_path, capsys):
    assert _run(_flash_argv(tmp_path, "sd.img.instable")) == 1
    assert mock_flash.call_args.kwargs["allow_unstable"] is False
    assert [e["code"] for e in _events(capsys) if e["type"] == "error"] == ["UNSTABLE_IMAGE"]


@patch("r36s_studio.__main__.create_and_format_games_partition_if_worthwhile", return_value=None)
@patch("r36s_studio.__main__.is_sf3000_card", return_value=False)
@patch("r36s_studio.__main__.flash_device", return_value=FlashResult(100, "a", "a", True))
@patch("r36s_studio.__main__.list_devices", return_value=[_make_device()])
def test_flash_allow_unstable_flag_is_passed_through(mock_list, mock_flash, mock_sf3000, mock_games, tmp_path):
    _run(_flash_argv(tmp_path, "sd.img.instable", "--allow-unstable"))
    assert mock_flash.call_args.kwargs["allow_unstable"] is True
