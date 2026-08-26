"""Tests de la logique de verrouillage/démontage Windows
(imaging/winlock.py). `_kernel32` est mocké — aucun appel `ctypes.WinDLL`
réel : ce module ne peut être exécuté que sous Windows, mais sa logique de
contrôle (ordre des appels, gestion des handles, nettoyage sur erreur) est
testable partout."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

from r36s_studio.imaging import winlock


def _fake_kernel32(handles=None):
    """Simule kernel32 : CreateFileW retourne des handles factices
    croissants, DeviceIoControl et CloseHandle réussissent toujours."""
    kernel32 = MagicMock()
    handle_iter = iter(handles or range(100, 200))
    kernel32.CreateFileW.side_effect = lambda *a, **k: next(handle_iter)
    kernel32.DeviceIoControl.return_value = True
    return kernel32


def test_drive_letter_to_volume_path():
    assert winlock._drive_letter_to_volume_path("D:\\") == r"\\.\D:"
    assert winlock._drive_letter_to_volume_path("E:") == r"\\.\E:"


@patch("r36s_studio.imaging.winlock._kernel32")
def test_lock_and_dismount_locks_then_dismounts_each_volume(mock_kernel32_factory):
    kernel32 = _fake_kernel32()
    mock_kernel32_factory.return_value = kernel32

    handles = winlock.lock_and_dismount_volumes(["D:\\", "E:\\"])

    assert handles == [100, 101]
    # Pour chaque volume : verrouillage puis démontage, dans cet ordre.
    codes = [c.args[1] for c in kernel32.DeviceIoControl.call_args_list]
    assert codes == [
        winlock.FSCTL_LOCK_VOLUME,
        winlock.FSCTL_DISMOUNT_VOLUME,
        winlock.FSCTL_LOCK_VOLUME,
        winlock.FSCTL_DISMOUNT_VOLUME,
    ]


@patch("r36s_studio.imaging.winlock._kernel32")
def test_lock_and_dismount_with_no_volumes_returns_empty(mock_kernel32_factory):
    kernel32 = _fake_kernel32()
    mock_kernel32_factory.return_value = kernel32

    handles = winlock.lock_and_dismount_volumes([])

    assert handles == []
    kernel32.CreateFileW.assert_not_called()


@patch("r36s_studio.imaging.winlock._kernel32")
def test_unlock_volumes_closes_every_handle(mock_kernel32_factory):
    kernel32 = _fake_kernel32()
    mock_kernel32_factory.return_value = kernel32

    winlock.unlock_volumes([100, 101, 102])

    assert kernel32.CloseHandle.call_args_list == [call(100), call(101), call(102)]


@patch("r36s_studio.imaging.winlock._kernel32")
def test_open_volume_handle_raises_on_invalid_handle(mock_kernel32_factory):
    kernel32 = MagicMock()
    kernel32.CreateFileW.return_value = winlock.INVALID_HANDLE_VALUE
    mock_kernel32_factory.return_value = kernel32

    try:
        winlock._open_volume_handle(r"\\.\D:")
        assert False, "aurait dû lever OSError"
    except OSError:
        pass


@patch("r36s_studio.imaging.winlock._kernel32")
def test_device_io_control_raises_when_call_fails(mock_kernel32_factory):
    kernel32 = MagicMock()
    kernel32.DeviceIoControl.return_value = False
    mock_kernel32_factory.return_value = kernel32

    try:
        winlock._device_io_control(123, winlock.FSCTL_LOCK_VOLUME)
        assert False, "aurait dû lever OSError"
    except OSError:
        pass


@patch("r36s_studio.imaging.winlock._kernel32")
def test_lock_and_dismount_unlocks_already_locked_volumes_on_failure(mock_kernel32_factory):
    """Si le verrouillage du 2e volume échoue, le 1er (déjà verrouillé) doit
    être refermé avant que l'erreur ne remonte -- pas de handle qui fuit."""
    kernel32 = _fake_kernel32()
    # Le premier DeviceIoControl (lock du volume 1) réussit, le suivant
    # (dismount du volume 1) aussi ; le 3e appel (lock du volume 2) échoue.
    kernel32.DeviceIoControl.side_effect = [True, True, False]
    mock_kernel32_factory.return_value = kernel32

    try:
        winlock.lock_and_dismount_volumes(["D:\\", "E:\\"])
        assert False, "aurait dû lever OSError"
    except OSError:
        pass

    # Le handle du volume 1 (100) a bien été refermé pendant le nettoyage.
    kernel32.CloseHandle.assert_called_once_with(100)


@patch("r36s_studio.imaging.winlock._kernel32")
def test_refresh_disk_properties_sends_update_ioctl(mock_kernel32_factory):
    kernel32 = _fake_kernel32()
    mock_kernel32_factory.return_value = kernel32

    winlock.refresh_disk_properties(r"\\.\PhysicalDrive2")

    codes = [c.args[1] for c in kernel32.DeviceIoControl.call_args_list]
    assert codes == [winlock.IOCTL_DISK_UPDATE_PROPERTIES]
    kernel32.CloseHandle.assert_called_once()


@patch("r36s_studio.imaging.winlock._kernel32")
def test_refresh_disk_properties_is_best_effort_on_invalid_handle(mock_kernel32_factory):
    kernel32 = MagicMock()
    kernel32.CreateFileW.return_value = winlock.INVALID_HANDLE_VALUE
    mock_kernel32_factory.return_value = kernel32

    winlock.refresh_disk_properties(r"\\.\PhysicalDrive2")  # ne doit pas lever

    kernel32.DeviceIoControl.assert_not_called()
