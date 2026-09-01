"""Tests de la sous-commande CLI `backup --system-only` (__main__.py) --
sauvegarde système sans les jeux (imaging/system_backup.py). `list_devices`
et `backup_system_only` sont mockés -- aucune carte réelle."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio import __main__ as cli
from r36s_studio.devices import Device
from r36s_studio.imaging.system_backup import GamesPartitionNotFound


def _make_device(path="/dev/fake-disk-test-3") -> Device:
    return Device(
        path=path, display="Carte SD factice", size_bytes=32_000_000_000, removable=True, bus="USB",
        is_system=False, mountpoints=[],
    )


def _parse(argv):
    return cli.build_parser().parse_args(argv)


@patch("r36s_studio.__main__.backup_system_only")
@patch("r36s_studio.__main__.backup_device")
@patch("r36s_studio.__main__.list_devices")
def test_system_only_flag_calls_backup_system_only_not_backup_device(
    mock_list, mock_backup_device, mock_backup_system_only, tmp_path
):
    mock_list.return_value = [_make_device()]
    mock_backup_system_only.return_value = 9_000_000_000

    args = _parse(
        ["backup", "--device", "/dev/fake-disk-test-3", "--output", str(tmp_path / "out.img"), "--system-only"]
    )
    code = cli.cmd_backup(args)

    assert code == 0
    mock_backup_system_only.assert_called_once()
    mock_backup_device.assert_not_called()


@patch("r36s_studio.__main__.backup_device")
@patch("r36s_studio.__main__.list_devices")
def test_without_the_flag_calls_backup_device_as_before(mock_list, mock_backup_device, tmp_path):
    mock_list.return_value = [_make_device()]
    mock_backup_device.return_value = 32_000_000_000

    args = _parse(["backup", "--device", "/dev/fake-disk-test-3", "--output", str(tmp_path / "out.img")])
    code = cli.cmd_backup(args)

    assert code == 0
    mock_backup_device.assert_called_once()


@patch("r36s_studio.__main__.backup_system_only", side_effect=GamesPartitionNotFound("aucune partition de jeux"))
@patch("r36s_studio.__main__.list_devices")
def test_system_only_reports_a_clear_error_when_no_games_partition_found(mock_list, mock_backup_system_only, tmp_path, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(
        ["backup", "--device", "/dev/fake-disk-test-3", "--output", str(tmp_path / "out.img"), "--system-only"]
    )
    code = cli.cmd_backup(args)

    assert code == 1
    out = capsys.readouterr().out
    assert "GAMES_PARTITION_NOT_FOUND" in out or "jeux" in out.lower()
