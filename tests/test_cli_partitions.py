"""Tests des CLI `inject-boot` et `copy-games` (__main__.py, §4.4/§4.6).
`list_devices`, `inject_boot`/`copy_games` sont mockés — aucune carte réelle
n'est touchée."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from r36s_studio import __main__ as cli
from r36s_studio.devices import Device
from r36s_studio.imaging import OperationCancelled
from r36s_studio.partitions.copy import MountpointNotWritable
from r36s_studio.partitions.jobs import MacosNtfsWriteUnsupported
from r36s_studio.partitions.locate import PartitionNotFound, PartitionNotMounted


@pytest.fixture(autouse=True)
def _card_accepted_for_arkos_steps():
    """Le refus d'une carte non ArkOS (`arkos_step_refusal`) lirait les
    vraies partitions du chemin factice -- neutralisé ici, testé à part."""
    with patch("r36s_studio.__main__.arkos_step_refusal", return_value=None):
        yield


def _make_device(path="/dev/fake-disk-test-3") -> Device:
    return Device(
        path=path,
        display="Carte SD factice",
        size_bytes=32_000_000_000,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=[],
    )


def _parse(argv):
    return cli.build_parser().parse_args(argv)


# --- inject-boot -------------------------------------------------------


@patch("r36s_studio.__main__.inject_boot", return_value=42)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_inject_boot_success_emits_done_true(mock_list, mock_inject, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    boot_source = tmp_path / "boot_backup"
    boot_source.mkdir()

    args = _parse(["inject-boot", "--device", "/dev/fake-disk-test-3", "--boot-source", str(boot_source)])
    code = args.func(args)

    assert code == 0
    out = capsys.readouterr().out
    assert '"type": "done"' in out
    assert '"ok": true' in out


@patch("r36s_studio.__main__.inject_boot")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_inject_boot_rejects_missing_source_folder(mock_list, mock_inject, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["inject-boot", "--device", "/dev/fake-disk-test-3", "--boot-source", "/nonexistent"])
    code = args.func(args)

    assert code == 1
    mock_inject.assert_not_called()
    assert "SOURCE_NOT_FOUND" in capsys.readouterr().out


@patch("r36s_studio.__main__.inject_boot")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_inject_boot_rejects_device_not_in_safe_list(mock_list, mock_inject, tmp_path, capsys):
    mock_list.return_value = [_make_device(path="/dev/fake-disk-test-9")]
    boot_source = tmp_path / "boot_backup"
    boot_source.mkdir()

    args = _parse(["inject-boot", "--device", "/dev/fake-disk-test-3", "--boot-source", str(boot_source)])
    code = args.func(args)

    assert code == 1
    mock_inject.assert_not_called()
    assert "DEVICE_NOT_ALLOWED" in capsys.readouterr().out


@patch("r36s_studio.__main__.inject_boot", side_effect=PartitionNotFound("BOOT", "/dev/fake-disk-test-3"))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_inject_boot_reports_partition_not_found(mock_list, mock_inject, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    boot_source = tmp_path / "boot_backup"
    boot_source.mkdir()

    args = _parse(["inject-boot", "--device", "/dev/fake-disk-test-3", "--boot-source", str(boot_source)])
    code = args.func(args)

    assert code == 1
    assert "PARTITION_NOT_FOUND" in capsys.readouterr().out


@patch("r36s_studio.__main__.inject_boot", side_effect=PartitionNotMounted("BOOT", "/dev/fake-disk-test-3"))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_inject_boot_reports_partition_not_mounted(mock_list, mock_inject, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    boot_source = tmp_path / "boot_backup"
    boot_source.mkdir()

    args = _parse(["inject-boot", "--device", "/dev/fake-disk-test-3", "--boot-source", str(boot_source)])
    code = args.func(args)

    assert code == 1
    assert "PARTITION_NOT_MOUNTED" in capsys.readouterr().out


@patch("r36s_studio.__main__.inject_boot", side_effect=OperationCancelled(1024))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_inject_boot_reports_cancellation(mock_list, mock_inject, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    boot_source = tmp_path / "boot_backup"
    boot_source.mkdir()

    args = _parse(["inject-boot", "--device", "/dev/fake-disk-test-3", "--boot-source", str(boot_source)])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert "CANCELLED" in out
    assert '"ok": false' in out


# --- copy-games --------------------------------------------------------


@patch("r36s_studio.__main__.copy_games", return_value=999)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_copy_games_success_emits_done_true(mock_list, mock_copy, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    games_source = tmp_path / "games"
    games_source.mkdir()

    args = _parse(["copy-games", "--device", "/dev/fake-disk-test-3", "--games-source", str(games_source)])
    code = args.func(args)

    assert code == 0
    out = capsys.readouterr().out
    assert '"type": "done"' in out
    assert '"ok": true' in out


@patch("r36s_studio.__main__.copy_games")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_copy_games_rejects_missing_source_folder(mock_list, mock_copy, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["copy-games", "--device", "/dev/fake-disk-test-3", "--games-source", "/nonexistent"])
    code = args.func(args)

    assert code == 1
    mock_copy.assert_not_called()
    assert "SOURCE_NOT_FOUND" in capsys.readouterr().out


@patch(
    "r36s_studio.__main__.copy_games",
    side_effect=MacosNtfsWriteUnsupported("EASYROMS"),
)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_copy_games_reports_macos_ntfs_limitation_explicitly(mock_list, mock_copy, tmp_path, capsys):
    """Le cas documenté dans CLAUDE.md §4.4 : EASYROMS est en NTFS sur du
    vrai matériel, macOS ne peut pas y écrire nativement. Le message doit
    être explicite plutôt qu'une erreur d'écriture obscure."""
    mock_list.return_value = [_make_device()]
    games_source = tmp_path / "games"
    games_source.mkdir()

    args = _parse(["copy-games", "--device", "/dev/fake-disk-test-3", "--games-source", str(games_source)])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert "EASYROMS_NTFS_MACOS" in out
    assert "NTFS" in out


@patch(
    "r36s_studio.__main__.copy_games",
    side_effect=MountpointNotWritable("/Volumes/EASYROMS", "[Errno 30] Read-only file system"),
)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_copy_games_reports_mountpoint_not_writable_explicitly(mock_list, mock_copy, tmp_path, capsys):
    """Filet de sécurité générique (§4.4) : un volume mal détecté comme
    inscriptible doit produire un message explicite, pas une erreur d'E/S
    brute remontée telle quelle."""
    mock_list.return_value = [_make_device()]
    games_source = tmp_path / "games"
    games_source.mkdir()

    args = _parse(["copy-games", "--device", "/dev/fake-disk-test-3", "--games-source", str(games_source)])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert "MOUNTPOINT_NOT_WRITABLE" in out
    assert "/Volumes/EASYROMS" in out


@patch("r36s_studio.__main__.copy_games", side_effect=OperationCancelled(2048))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_copy_games_reports_cancellation(mock_list, mock_copy, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    games_source = tmp_path / "games"
    games_source.mkdir()

    args = _parse(["copy-games", "--device", "/dev/fake-disk-test-3", "--games-source", str(games_source)])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert "CANCELLED" in out
    assert '"ok": false' in out


def test_make_should_cancel_available_on_copy_games(tmp_path):
    cancel_file = tmp_path / "cancel.flag"
    args = _parse(
        [
            "copy-games",
            "--device",
            "/dev/fake-disk-test-3",
            "--games-source",
            str(tmp_path),
            "--cancel-file",
            str(cancel_file),
        ]
    )

    should_cancel = cli._make_should_cancel(args)

    assert should_cancel() is False
    cancel_file.write_text("")
    assert should_cancel() is True
