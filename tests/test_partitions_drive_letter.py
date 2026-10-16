# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Partition de jeux sans lettre de lecteur (Windows) : constaté après
l'agrandissement d'EASYROMS par dArkOSen au premier démarrage."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from r36s_studio.partitions import drive_letter
from r36s_studio.partitions.locate import PartitionInfo

DEVICE = "\\\\.\\PhysicalDrive9902"


def _part(label: str, mountpoint: str) -> PartitionInfo:
    return PartitionInfo(device_path=mountpoint, label=label, filesystem="exfat", mountpoint=mountpoint)


@pytest.mark.real_drive_letter_check
@pytest.mark.parametrize(
    "mountpoint, expected",
    [("\\\\?\\Volume{abc-123}\\", True), ("K:\\", False)],
)
@patch("r36s_studio.partitions.drive_letter.platform.system", return_value="Windows")
def test_missing_letter_only_for_a_games_partition_on_its_guid_path(mock_system, mountpoint, expected):
    partitions = [_part("BOOT", "\\\\?\\Volume{boot}\\"), _part("EASYROMS", mountpoint)]
    with patch("r36s_studio.partitions.drive_letter.list_partitions", return_value=partitions):
        assert drive_letter.games_partition_missing_letter(DEVICE) is expected


@pytest.mark.real_drive_letter_check
def test_missing_letter_is_never_checked_outside_windows():
    with patch("r36s_studio.partitions.drive_letter.platform.system", return_value="Darwin"):
        assert drive_letter.games_partition_missing_letter(DEVICE) is False


@pytest.mark.real_drive_letter_check
@patch("r36s_studio.partitions.drive_letter.platform.system", return_value="Windows")
def test_missing_letter_unreadable_card_never_prompts(mock_system):
    with patch("r36s_studio.partitions.drive_letter.list_partitions", side_effect=OSError("boom")):
        assert drive_letter.games_partition_missing_letter(DEVICE) is False


@patch("r36s_studio.partitions.drive_letter.subprocess.run")
def test_assign_parses_letter_filesystem_and_attribute(mock_run):
    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = "GAMES=k|exFAT|True\nGAMES=|NTFS|False\nbruit\n"

    assigned = drive_letter.assign_games_drive_letters(DEVICE)

    assert assigned == [
        drive_letter.AssignedLetter("K", "exFAT", True),
        drive_letter.AssignedLetter("", "NTFS", False),
    ]
    command = mock_run.call_args[0][0][-1]
    assert "$diskNumber = 9902" in command
    assert "Add-PartitionAccessPath -AssignDriveLetter" in command
    assert "Format-Volume" not in command and "Set-Partition" not in command


@patch("r36s_studio.partitions.drive_letter.subprocess.run")
def test_assign_raises_when_powershell_fails(mock_run):
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = "Access denied"
    with pytest.raises(OSError, match="Access denied"):
        drive_letter.assign_games_drive_letters(DEVICE)


def test_assign_refuses_a_non_windows_device_path():
    with pytest.raises(ValueError):
        drive_letter.assign_games_drive_letters("/dev/fake-disk-test-1")


def test_cli_assign_letter_logs_letter_and_filesystem(capsys):
    from r36s_studio.__main__ import build_parser

    args = build_parser().parse_args(["assign-letter", "--device", DEVICE])
    with patch("r36s_studio.__main__._resolve_device_or_report", return_value=type("D", (), {"path": DEVICE})()), patch(
        "r36s_studio.__main__.drive_letter.assign_games_drive_letters",
        return_value=[drive_letter.AssignedLetter("K", "exFAT", False)],
    ):
        assert args.func(args) == 0

    out = capsys.readouterr().out
    assert "disponible sous K: dans l'Explorateur" in out
    assert "système de fichiers exFAT" in out
    assert '"type": "drive_letter_result"' in out
