"""Tests du "mode worker" du CLI (--worker, --progress-file, --cancel-file)
— la plomberie que la GUI utilise pour piloter un worker élevé (§3).
`list_devices`, `backup_device`/`flash_device` sont mockés — aucun disque
réel n'est touché."""

from __future__ import annotations

import json
from unittest.mock import patch

from r36s_studio import __main__ as cli
from r36s_studio import protocol
from r36s_studio.devices import Device
from r36s_studio.imaging import OperationCancelled
from r36s_studio.imaging.flash import FlashResult


def teardown_function() -> None:
    protocol.configure(None)


def _make_device(path="/dev/fake-disk-test-3", size_bytes=32_000_000_000) -> Device:
    return Device(
        path=path,
        display="Carte SD factice",
        size_bytes=size_bytes,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=[],
    )


def _parse(argv):
    return cli.build_parser().parse_args(argv)


def _read_events(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# --- --worker saute la confirmation interactive de flash -------------------


@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__._confirm_flash")
@patch("r36s_studio.__main__.list_devices")
def test_flash_worker_mode_skips_interactive_confirmation(mock_list, mock_confirm, mock_flash, tmp_path):
    mock_list.return_value = [_make_device()]
    mock_flash.return_value = FlashResult(
        bytes_written=10, source_sha256="a", written_sha256="a", verified=True
    )
    image = tmp_path / "sd.img"
    image.write_bytes(b"x" * 10)

    args = _parse(["flash", "--image", str(image), "--device", "/dev/fake-disk-test-3", "--worker"])
    code = args.func(args)

    assert code == 0
    mock_confirm.assert_not_called()


# --- --progress-file redirige les événements ------------------------------


@patch("r36s_studio.__main__.backup_device", return_value=42)
@patch("r36s_studio.__main__.list_devices")
def test_backup_worker_mode_writes_events_to_progress_file(mock_list, mock_backup, tmp_path):
    mock_list.return_value = [_make_device()]
    progress_file = tmp_path / "progress.jsonl"
    output = tmp_path / "out.img"

    args = _parse(
        [
            "backup",
            "--device",
            "/dev/fake-disk-test-3",
            "--output",
            str(output),
            "--worker",
            "--progress-file",
            str(progress_file),
        ]
    )
    code = args.func(args)

    assert code == 0
    events = _read_events(progress_file)
    assert events[-1] == {"type": "done", "ok": True}
    assert any(e["type"] == "log" for e in events)


@patch("r36s_studio.__main__.flash_device")
@patch("r36s_studio.__main__.list_devices")
def test_flash_worker_mode_writes_events_to_progress_file(mock_list, mock_flash, tmp_path):
    mock_list.return_value = [_make_device()]
    mock_flash.return_value = FlashResult(
        bytes_written=10, source_sha256="a", written_sha256="a", verified=True
    )
    image = tmp_path / "sd.img"
    image.write_bytes(b"x" * 10)
    progress_file = tmp_path / "progress.jsonl"

    args = _parse(
        [
            "flash",
            "--image",
            str(image),
            "--device",
            "/dev/fake-disk-test-3",
            "--worker",
            "--progress-file",
            str(progress_file),
        ]
    )
    code = args.func(args)

    assert code == 0
    events = _read_events(progress_file)
    assert events[-1] == {"type": "done", "ok": True}


# --- annulation (--cancel-file) --------------------------------------------


@patch("r36s_studio.__main__.backup_device", side_effect=OperationCancelled(1024))
@patch("r36s_studio.__main__.list_devices")
def test_backup_reports_cancellation(mock_list, mock_backup, tmp_path):
    mock_list.return_value = [_make_device()]
    progress_file = tmp_path / "progress.jsonl"

    args = _parse(
        [
            "backup",
            "--device",
            "/dev/fake-disk-test-3",
            "--output",
            str(tmp_path / "out.img"),
            "--worker",
            "--progress-file",
            str(progress_file),
            "--cancel-file",
            str(tmp_path / "cancel.flag"),
        ]
    )
    code = args.func(args)

    assert code == 1
    events = _read_events(progress_file)
    assert events[-2] == {"type": "error", "code": "CANCELLED", "msg": "Sauvegarde annulée après 1024 octets"}
    assert events[-1] == {"type": "done", "ok": False}


@patch("r36s_studio.__main__.flash_device", side_effect=OperationCancelled(2048))
@patch("r36s_studio.__main__.list_devices")
def test_flash_reports_cancellation(mock_list, mock_flash, tmp_path):
    mock_list.return_value = [_make_device()]
    image = tmp_path / "sd.img"
    image.write_bytes(b"x" * 10)
    progress_file = tmp_path / "progress.jsonl"

    args = _parse(
        [
            "flash",
            "--image",
            str(image),
            "--device",
            "/dev/fake-disk-test-3",
            "--worker",
            "--progress-file",
            str(progress_file),
        ]
    )
    code = args.func(args)

    assert code == 1
    events = _read_events(progress_file)
    assert events[-2]["code"] == "CANCELLED"
    assert events[-1] == {"type": "done", "ok": False}


def test_make_should_cancel_reflects_file_presence(tmp_path):
    cancel_file = tmp_path / "cancel.flag"
    args = _parse(
        [
            "backup",
            "--device",
            "/dev/fake-disk-test-3",
            "--output",
            str(tmp_path / "out.img"),
            "--cancel-file",
            str(cancel_file),
        ]
    )

    should_cancel = cli._make_should_cancel(args)

    assert should_cancel() is False
    cancel_file.write_text("")
    assert should_cancel() is True


def test_make_should_cancel_is_none_without_cancel_file(tmp_path):
    args = _parse(
        ["backup", "--device", "/dev/fake-disk-test-3", "--output", str(tmp_path / "out.img")]
    )
    assert cli._make_should_cancel(args) is None
