"""Tests des CLI `extract-boot`, `extract-easyroms` et `eject`
(__main__.py, workflow à deux cartes §4.4/§4.5). `list_devices`,
`extract_boot`/`extract_easyroms`/`eject_device` sont mockés — aucune carte
réelle n'est touchée."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from r36s_studio import __main__ as cli
from r36s_studio.devices import Device
from r36s_studio.imaging import OperationCancelled
from r36s_studio.partitions.copy import MountpointNotWritable
from r36s_studio.partitions.locate import PartitionNotFound, PartitionNotMounted


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


# --- extract-boot ------------------------------------------------------


@patch("r36s_studio.__main__.archives.new_archive_path")
@patch("r36s_studio.__main__.extract_boot", return_value=42)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_boot_success_emits_done_true_with_archive_path(
    mock_list, mock_extract, mock_new_path, tmp_path, capsys
):
    mock_list.return_value = [_make_device()]
    dest = tmp_path / "BOOT_2026-07-06_00-21"
    mock_new_path.return_value = dest

    args = _parse(["extract-boot", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    mock_extract.assert_called_once()
    assert mock_extract.call_args.args[1] == str(dest)
    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert "BOOT_2026-07-06_00-21" in out


@patch("r36s_studio.__main__.archives.new_archive_path")
@patch("r36s_studio.__main__.extract_boot")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_boot_passes_output_dir_to_new_archive_path(mock_list, mock_extract, mock_new_path, tmp_path):
    mock_list.return_value = [_make_device()]
    custom_dir = tmp_path / "custom"

    args = _parse(["extract-boot", "--device", "/dev/fake-disk-test-3", "--output-dir", str(custom_dir)])
    args.func(args)

    from pathlib import Path

    mock_new_path.assert_called_once_with("BOOT", base_dir=Path(custom_dir))


@patch("r36s_studio.__main__.archives.new_archive_path")
@patch("r36s_studio.__main__.extract_boot")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_boot_without_output_dir_passes_none_as_base_dir(mock_list, mock_extract, mock_new_path):
    mock_list.return_value = [_make_device()]

    args = _parse(["extract-boot", "--device", "/dev/fake-disk-test-3"])
    args.func(args)

    mock_new_path.assert_called_once_with("BOOT", base_dir=None)


@patch("r36s_studio.__main__.archives.new_archive_path", return_value="dest")
@patch("r36s_studio.__main__.extract_boot", side_effect=PartitionNotFound("BOOT", "/dev/fake-disk-test-3"))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_boot_reports_partition_not_found(mock_list, mock_extract, mock_new_path, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["extract-boot", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    assert "PARTITION_NOT_FOUND" in capsys.readouterr().out


@patch("r36s_studio.__main__.archives.new_archive_path", return_value="dest")
@patch("r36s_studio.__main__.extract_boot", side_effect=OperationCancelled(1024))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_boot_reports_cancellation(mock_list, mock_extract, mock_new_path, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["extract-boot", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    out = capsys.readouterr().out
    assert "CANCELLED" in out
    assert '"ok": false' in out


@patch("r36s_studio.__main__.extract_boot")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_boot_rejects_device_not_in_safe_list(mock_list, mock_extract, capsys):
    mock_list.return_value = [_make_device(path="/dev/fake-disk-test-9")]

    args = _parse(["extract-boot", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    mock_extract.assert_not_called()
    assert "DEVICE_NOT_ALLOWED" in capsys.readouterr().out


# --- extract-easyroms ----------------------------------------------------


@patch("r36s_studio.__main__.archives.new_archive_path")
@patch("r36s_studio.__main__.extract_easyroms", return_value=99)
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_easyroms_success_emits_done_true(mock_list, mock_extract, mock_new_path, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    dest = tmp_path / "EASYROMS_2026-07-06_00-21"
    mock_new_path.return_value = dest

    args = _parse(["extract-easyroms", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    mock_new_path.assert_called_once()
    assert mock_new_path.call_args.args[0] == "EASYROMS"
    out = capsys.readouterr().out
    assert '"ok": true' in out


@patch("r36s_studio.__main__.archives.new_archive_path", return_value="dest")
@patch("r36s_studio.__main__.extract_easyroms", side_effect=MountpointNotWritable("dest", "boom"))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_easyroms_reports_mountpoint_not_writable(mock_list, mock_extract, mock_new_path, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["extract-easyroms", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    assert "MOUNTPOINT_NOT_WRITABLE" in capsys.readouterr().out


@patch("r36s_studio.__main__.archives.new_archive_path", return_value="dest")
@patch("r36s_studio.__main__.extract_easyroms", side_effect=PartitionNotMounted("EASYROMS", "/dev/fake-disk-test-3"))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_extract_easyroms_reports_partition_not_mounted(mock_list, mock_extract, mock_new_path, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["extract-easyroms", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    assert "PARTITION_NOT_MOUNTED" in capsys.readouterr().out


# --- eject -----------------------------------------------------------------


@patch("r36s_studio.__main__.eject_device")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_eject_success_emits_safe_to_remove_confirmation(mock_list, mock_eject, capsys):
    device = _make_device()
    mock_list.return_value = [device]

    args = _parse(["eject", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 0
    mock_eject.assert_called_once_with(device.path)
    out = capsys.readouterr().out
    assert '"ok": true' in out
    assert "retirée en toute sécurité" in out


@patch("r36s_studio.__main__.eject_device", side_effect=NotImplementedError("pas sous Windows"))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_eject_unsupported_os_reports_error(mock_list, mock_eject, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["eject", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    assert "UNSUPPORTED_OS" in capsys.readouterr().out


@patch("r36s_studio.__main__.eject_device", side_effect=OSError("carte occupée"))
@patch("r36s_studio.__main__.list_devices")
def test_cmd_eject_io_error_reports_error(mock_list, mock_eject, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["eject", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    assert "IO_ERROR" in capsys.readouterr().out


@patch("r36s_studio.__main__.eject_device")
@patch("r36s_studio.__main__.list_devices")
def test_cmd_eject_rejects_device_not_in_safe_list(mock_list, mock_eject, capsys):
    mock_list.return_value = [_make_device(path="/dev/fake-disk-test-9")]

    args = _parse(["eject", "--device", "/dev/fake-disk-test-3"])
    code = args.func(args)

    assert code == 1
    mock_eject.assert_not_called()
    assert "DEVICE_NOT_ALLOWED" in capsys.readouterr().out
