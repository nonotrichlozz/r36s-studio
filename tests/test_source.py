"""Tests de la préparation macOS : lecture sur `/dev/rdiskN` et démontage
via `diskutil unmountDisk` avant lecture (imaging/source.py). `subprocess`
et `platform.system` sont mockés — aucun `diskutil` réel n'est appelé."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from r36s_studio.imaging.source import prepared_source, raw_read_path


@patch("r36s_studio.imaging.source.platform.system", return_value="Darwin")
def test_raw_read_path_uses_rdisk_on_macos(mock_system):
    assert raw_read_path("/dev/disk3") == "/dev/rdisk3"


@patch("r36s_studio.imaging.source.platform.system", return_value="Linux")
def test_raw_read_path_unchanged_on_linux(mock_system):
    assert raw_read_path("/dev/sdb") == "/dev/sdb"


@patch("r36s_studio.imaging.source.platform.system", return_value="Windows")
def test_raw_read_path_unchanged_on_windows(mock_system):
    assert raw_read_path(r"\\.\PhysicalDrive2") == r"\\.\PhysicalDrive2"


@patch("r36s_studio.imaging.source.subprocess.run")
@patch("r36s_studio.imaging.source.platform.system", return_value="Darwin")
def test_prepared_source_unmounts_disk_and_yields_rdisk_on_macos(mock_system, mock_run):
    with prepared_source("/dev/disk3") as path:
        assert path == "/dev/rdisk3"
    mock_run.assert_called_once_with(
        ["diskutil", "unmountDisk", "/dev/disk3"], check=True, capture_output=True
    )


@patch("r36s_studio.imaging.source.subprocess.run")
@patch("r36s_studio.imaging.source.platform.system", return_value="Darwin")
def test_prepared_source_succeeds_when_diskutil_writes_success_message_to_stderr(mock_system, mock_run):
    """Reproduit le bug : `diskutil unmountDisk` écrit parfois son message
    de succès sur stderr avec un code de retour 0 -- ça reste un succès,
    jamais une erreur, quel que soit le flux où le texte atterrit."""
    mock_run.return_value = subprocess.CompletedProcess(
        args=["diskutil", "unmountDisk", "/dev/disk3"],
        returncode=0,
        stdout=b"",
        stderr=b"Unmount of all volumes on disk3 was successful\n",
    )

    with prepared_source("/dev/disk3") as path:
        assert path == "/dev/rdisk3"  # aucune exception levée


@patch("r36s_studio.imaging.source.subprocess.run")
@patch("r36s_studio.imaging.source.platform.system", return_value="Linux")
def test_prepared_source_does_not_unmount_on_linux(mock_system, mock_run):
    with prepared_source("/dev/sdb") as path:
        assert path == "/dev/sdb"
    mock_run.assert_not_called()
