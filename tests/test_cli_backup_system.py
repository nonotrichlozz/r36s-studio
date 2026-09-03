"""Tests de la sous-commande CLI `backup --system-only` (__main__.py) --
sauvegarde système sans les jeux (imaging/system_backup.py). `list_devices`
et `backup_system_only` sont mockés -- aucune carte réelle."""

from __future__ import annotations

import json
from collections import namedtuple
from unittest.mock import patch

from r36s_studio import __main__ as cli
from r36s_studio.devices import Device
from r36s_studio.imaging.system_backup import GamesPartitionNotFound

# Pré-vol espace disque libre (§5 mode assisté, parcours de clonage) :
# `_make_device` déclare volontairement une taille factice énorme
# (32 Go) pour rester cohérente avec les autres tests de ce fichier --
# `shutil.disk_usage` est donc mocké partout où `cmd_backup` doit réussir,
# pour ne jamais dépendre de l'espace libre réel de la machine qui lance
# la suite (sans quoi ces tests deviendraient non déterministes selon la
# machine, §8).
_UsageStub = namedtuple("_UsageStub", ["total", "used", "free"])


def _fake_usage(free_bytes: int) -> "_UsageStub":
    return _UsageStub(total=free_bytes * 2, used=free_bytes, free=free_bytes)


def _make_device(path="/dev/fake-disk-test-3") -> Device:
    return Device(
        path=path, display="Carte SD factice", size_bytes=32_000_000_000, removable=True, bus="USB",
        is_system=False, mountpoints=[],
    )


def _parse(argv):
    return cli.build_parser().parse_args(argv)


@patch("r36s_studio.__main__.shutil.disk_usage")
@patch("r36s_studio.__main__.estimate_system_backup_size_unprivileged", return_value=9_000_000_000)
@patch("r36s_studio.__main__.backup_system_only")
@patch("r36s_studio.__main__.backup_device")
@patch("r36s_studio.__main__.list_devices")
def test_system_only_flag_calls_backup_system_only_not_backup_device(
    mock_list, mock_backup_device, mock_backup_system_only, mock_estimate_unprivileged, mock_disk_usage, tmp_path
):
    mock_list.return_value = [_make_device()]
    mock_backup_system_only.return_value = 9_000_000_000
    mock_disk_usage.return_value = _fake_usage(100_000_000_000)

    args = _parse(
        ["backup", "--device", "/dev/fake-disk-test-3", "--output", str(tmp_path / "out.img"), "--system-only"]
    )
    code = cli.cmd_backup(args)

    assert code == 0
    mock_backup_system_only.assert_called_once()
    mock_backup_device.assert_not_called()


@patch("r36s_studio.__main__.shutil.disk_usage")
@patch("r36s_studio.__main__.backup_device")
@patch("r36s_studio.__main__.list_devices")
def test_without_the_flag_calls_backup_device_as_before(mock_list, mock_backup_device, mock_disk_usage, tmp_path):
    mock_list.return_value = [_make_device()]
    mock_backup_device.return_value = 32_000_000_000
    mock_disk_usage.return_value = _fake_usage(100_000_000_000)

    args = _parse(["backup", "--device", "/dev/fake-disk-test-3", "--output", str(tmp_path / "out.img")])
    code = cli.cmd_backup(args)

    assert code == 0
    mock_backup_device.assert_called_once()


@patch("r36s_studio.__main__.shutil.disk_usage")
@patch("r36s_studio.__main__.estimate_system_backup_size_unprivileged", return_value=9_000_000_000)
@patch("r36s_studio.__main__.backup_system_only", side_effect=GamesPartitionNotFound("aucune partition de jeux"))
@patch("r36s_studio.__main__.list_devices")
def test_system_only_reports_a_clear_error_when_no_games_partition_found(
    mock_list, mock_backup_system_only, mock_estimate_unprivileged, mock_disk_usage, tmp_path, capsys
):
    mock_list.return_value = [_make_device()]
    mock_disk_usage.return_value = _fake_usage(100_000_000_000)

    args = _parse(
        ["backup", "--device", "/dev/fake-disk-test-3", "--output", str(tmp_path / "out.img"), "--system-only"]
    )
    code = cli.cmd_backup(args)

    assert code == 1
    out = capsys.readouterr().out
    assert "GAMES_PARTITION_NOT_FOUND" in out or "jeux" in out.lower()


# --- --estimate-only : repli élevé pour l'estimation (§4.3) -----------------
#
# Quand `list_partitions` (non élevé) n'expose pas assez d'information pour
# estimer la taille sans lire la table de partitions brute, la GUI relance
# le worker élevé avec ce mode -- même session d'autorisation que le flash
# et la sauvegarde complète (`WorkerRunner`), jamais de nouvelle invite.


@patch("r36s_studio.__main__.estimate_system_backup_size", return_value=9_000_000_000)
@patch("r36s_studio.__main__.backup_system_only")
@patch("r36s_studio.__main__.list_devices")
def test_estimate_only_emits_the_size_without_writing_anything(
    mock_list, mock_backup_system_only, mock_estimate, capsys
):
    mock_list.return_value = [_make_device()]

    args = _parse(
        ["backup", "--device", "/dev/fake-disk-test-3", "--system-only", "--estimate-only"]
    )
    code = cli.cmd_backup(args)

    assert code == 0
    mock_backup_system_only.assert_not_called()
    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.splitlines()]
    assert {"type": "estimate", "size_bytes": 9_000_000_000} in events


def test_estimate_only_does_not_require_output():
    """`--output` n'a pas de sens pour une estimation -- rien n'est écrit."""
    args = _parse(["backup", "--device", "/dev/fake-disk-test-3", "--system-only", "--estimate-only"])
    assert args.output is None


@patch("r36s_studio.__main__.list_devices")
def test_estimate_only_without_system_only_is_rejected(mock_list, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["backup", "--device", "/dev/fake-disk-test-3", "--estimate-only"])
    code = cli.cmd_backup(args)

    assert code == 1


@patch("r36s_studio.__main__.list_devices")
def test_missing_output_without_estimate_only_is_rejected(mock_list, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["backup", "--device", "/dev/fake-disk-test-3"])
    code = cli.cmd_backup(args)

    assert code == 1


@patch(
    "r36s_studio.__main__.estimate_system_backup_size",
    side_effect=GamesPartitionNotFound("aucune partition de jeux"),
)
@patch("r36s_studio.__main__.list_devices")
def test_estimate_only_reports_games_partition_not_found(mock_list, mock_estimate, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["backup", "--device", "/dev/fake-disk-test-3", "--system-only", "--estimate-only"])
    code = cli.cmd_backup(args)

    assert code == 1
    out = capsys.readouterr().out
    assert "GAMES_PARTITION_NOT_FOUND" in out


@patch("r36s_studio.__main__.estimate_system_backup_size", side_effect=PermissionError("[Errno 13] Permission denied"))
@patch("r36s_studio.__main__.list_devices")
def test_estimate_only_reports_io_error(mock_list, mock_estimate, capsys):
    mock_list.return_value = [_make_device()]

    args = _parse(["backup", "--device", "/dev/fake-disk-test-3", "--system-only", "--estimate-only"])
    code = cli.cmd_backup(args)

    assert code == 1
    out = capsys.readouterr().out
    assert "IO_ERROR" in out
