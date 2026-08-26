"""Tests du dispatch par OS de la préparation à l'écriture
(imaging/write_target.py). `subprocess` et le module `winlock` sont mockés —
aucun périphérique réel n'est démonté, verrouillé ni ouvert."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio.devices import Device
from r36s_studio.imaging.write_target import prepared_write_target


def _make_device(path: str, mountpoints=None) -> Device:
    return Device(
        path=path,
        display="Carte SD factice",
        size_bytes=32_000_000_000,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=mountpoints or [],
    )


@patch("r36s_studio.imaging.write_target.subprocess.run")
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Darwin")
def test_macos_unmounts_disk_and_yields_rdisk(mock_system, mock_run):
    device = _make_device("/dev/disk3")

    with prepared_write_target(device) as path:
        assert path == "/dev/rdisk3"

    mock_run.assert_called_once_with(["diskutil", "unmountDisk", "/dev/disk3"], check=True)


@patch("r36s_studio.imaging.write_target.subprocess.run")
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Linux")
def test_linux_unmounts_each_mountpoint_and_yields_device_path(mock_system, mock_run):
    device = _make_device("/dev/sdb", mountpoints=["/media/BOOT", "/media/EASYROMS"])

    with prepared_write_target(device) as path:
        assert path == "/dev/sdb"

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert calls == [["umount", "/media/BOOT"], ["umount", "/media/EASYROMS"]]


@patch("r36s_studio.imaging.write_target.subprocess.run")
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Linux")
def test_linux_with_no_mountpoints_does_not_call_umount(mock_system, mock_run):
    device = _make_device("/dev/sdb", mountpoints=[])

    with prepared_write_target(device) as path:
        assert path == "/dev/sdb"

    mock_run.assert_not_called()


@patch("r36s_studio.imaging.winlock.refresh_disk_properties")
@patch("r36s_studio.imaging.winlock.unlock_volumes")
@patch("r36s_studio.imaging.winlock.lock_and_dismount_volumes", return_value=[111])
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Windows")
def test_windows_locks_dismounts_then_unlocks_and_refreshes(
    mock_system, mock_lock, mock_unlock, mock_refresh
):
    # `from . import winlock` se fait à l'intérieur de la fonction : on
    # patch les fonctions du vrai module winlock (comme test_winlock.py),
    # plutôt que de tenter de substituer le module entier -- une fois
    # importé, `r36s_studio.imaging.winlock` est mis en cache comme
    # attribut du package, ce qui rendrait un remplacement via
    # `sys.modules` peu fiable.
    device = _make_device(r"\\.\PhysicalDrive2", mountpoints=["D:\\"])

    with prepared_write_target(device) as path:
        assert path == r"\\.\PhysicalDrive2"

    mock_lock.assert_called_once_with(["D:\\"])
    mock_unlock.assert_called_once_with([111])
    mock_refresh.assert_called_once_with(r"\\.\PhysicalDrive2")


@patch("r36s_studio.imaging.winlock.refresh_disk_properties")
@patch("r36s_studio.imaging.winlock.unlock_volumes")
@patch("r36s_studio.imaging.winlock.lock_and_dismount_volumes", return_value=[111])
@patch("r36s_studio.imaging.write_target.platform.system", return_value="Windows")
def test_windows_unlocks_even_if_write_raises(mock_system, mock_lock, mock_unlock, mock_refresh):
    device = _make_device(r"\\.\PhysicalDrive2", mountpoints=["D:\\"])

    try:
        with prepared_write_target(device):
            raise RuntimeError("écriture simulée en échec")
    except RuntimeError:
        pass

    mock_unlock.assert_called_once_with([111])


@patch("r36s_studio.imaging.write_target.platform.system", return_value="Plan9")
def test_unsupported_os_raises(mock_system):
    device = _make_device("/dev/whatever")
    try:
        with prepared_write_target(device):
            pass
        assert False, "aurait dû lever NotImplementedError"
    except NotImplementedError:
        pass
