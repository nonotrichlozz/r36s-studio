"""Tests d'éjection (partitions/eject.py, étape F du workflow §4.4/§4.5).
`subprocess.run`/`platform.system` sont mockés — aucune carte réelle n'est
éjectée."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from r36s_studio.partitions.eject import eject


@patch("r36s_studio.partitions.eject.subprocess.run")
@patch("r36s_studio.partitions.eject.platform.system", return_value="Darwin")
def test_macos_uses_diskutil_eject(mock_platform, mock_run):
    eject("/dev/fake-disk-test-4")

    mock_run.assert_called_once_with(["diskutil", "eject", "/dev/fake-disk-test-4"], check=True)


@patch("r36s_studio.partitions.eject.subprocess.run")
@patch("r36s_studio.partitions.eject.platform.system", return_value="Linux")
def test_linux_uses_udisksctl_power_off(mock_platform, mock_run):
    eject("/dev/fake-disk-test-4")

    mock_run.assert_called_once_with(
        ["udisksctl", "power-off", "-b", "/dev/fake-disk-test-4"], check=True
    )


@patch("r36s_studio.partitions.eject.platform.system", return_value="Windows")
def test_windows_raises_not_implemented(mock_platform):
    with pytest.raises(NotImplementedError):
        eject("/dev/fake-disk-test-4")


@patch("r36s_studio.partitions.eject.platform.system", return_value="Plan9")
def test_unsupported_os_raises_not_implemented(mock_platform):
    with pytest.raises(NotImplementedError):
        eject("/dev/fake-disk-test-4")


@patch("r36s_studio.partitions.eject.subprocess.run", side_effect=OSError("busy"))
@patch("r36s_studio.partitions.eject.platform.system", return_value="Darwin")
def test_failure_propagates(mock_platform, mock_run):
    with pytest.raises(OSError):
        eject("/dev/fake-disk-test-4")
