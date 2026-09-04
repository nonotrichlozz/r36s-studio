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


def test_drive_letter_to_volume_path_passes_through_guid_volume_path():
    """Bug corrigé, confirmé sur du vrai matériel : un chemin déjà dans
    l'espace de noms périphérique (une partition sans lettre de lecteur,
    ex. BOOT sur une carte ArkOS, identifiée par son chemin GUID) ne doit
    pas être préfixé une seconde fois par `\\\\.\\` -- ça produirait un
    chemin invalide, ce qui a provoqué un `[Errno 9] Bad file descriptor`
    en cours d'écriture (write_target.py laissait BOOT monté faute de le
    verrouiller correctement)."""
    assert winlock._drive_letter_to_volume_path("\\\\?\\Volume{abc-123}\\") == "\\\\?\\Volume{abc-123}"
    assert winlock._drive_letter_to_volume_path(r"\\.\D:") == r"\\.\D:"


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


@patch("r36s_studio.imaging.winlock._last_error", return_value=99)
@patch("r36s_studio.imaging.winlock._kernel32")
def test_device_io_control_error_carries_win32_error_code(mock_kernel32_factory, mock_last_error):
    kernel32 = MagicMock()
    kernel32.DeviceIoControl.return_value = False
    mock_kernel32_factory.return_value = kernel32

    try:
        winlock._device_io_control(123, winlock.FSCTL_LOCK_VOLUME)
        assert False, "aurait dû lever DeviceIoControlError"
    except winlock.DeviceIoControlError as exc:
        assert exc.win32_error == 99


# --- _lock_volume : bug corrigé, confirmé sur du vrai matériel ------------
# -- FSCTL_LOCK_VOLUME échoue avec ERROR_ACCESS_DENIED (5) même sur un ----
# worker déjà élevé quand un autre processus (Explorateur, indexeur, ------
# antivirus) tient encore un descripteur ouvert sur le volume -- ce genre -
# de descripteur se libère très souvent en une ou deux secondes -----------


@patch("time.sleep")
@patch("r36s_studio.imaging.winlock._last_error", return_value=winlock.ERROR_ACCESS_DENIED)
@patch("r36s_studio.imaging.winlock._kernel32")
def test_lock_volume_retries_on_access_denied_then_succeeds(mock_kernel32_factory, mock_last_error, mock_sleep):
    kernel32 = MagicMock()
    # Échoue deux fois (ERROR_ACCESS_DENIED), réussit à la 3e tentative.
    kernel32.DeviceIoControl.side_effect = [False, False, True]
    mock_kernel32_factory.return_value = kernel32

    winlock._lock_volume(123)  # ne doit lever aucune exception

    assert kernel32.DeviceIoControl.call_count == 3
    assert mock_sleep.call_count == 2
    mock_sleep.assert_called_with(winlock.LOCK_VOLUME_RETRY_DELAY_SECONDS)


@patch("time.sleep")
@patch("r36s_studio.imaging.winlock._last_error", return_value=winlock.ERROR_ACCESS_DENIED)
@patch("r36s_studio.imaging.winlock._kernel32")
def test_lock_volume_raises_volume_in_use_after_exhausting_retries(mock_kernel32_factory, mock_last_error, mock_sleep):
    kernel32 = MagicMock()
    kernel32.DeviceIoControl.return_value = False  # échoue systématiquement
    mock_kernel32_factory.return_value = kernel32

    try:
        winlock._lock_volume(123)
        assert False, "aurait dû lever VolumeInUseError"
    except winlock.VolumeInUseError:
        pass

    assert kernel32.DeviceIoControl.call_count == winlock.LOCK_VOLUME_RETRY_COUNT
    # Un délai entre chaque tentative, mais pas après la dernière.
    assert mock_sleep.call_count == winlock.LOCK_VOLUME_RETRY_COUNT - 1


@patch("time.sleep")
@patch("r36s_studio.imaging.winlock._last_error", return_value=1223)  # ERROR_CANCELLED, sans rapport
@patch("r36s_studio.imaging.winlock._kernel32")
def test_lock_volume_does_not_retry_on_unrelated_errors(mock_kernel32_factory, mock_last_error, mock_sleep):
    """Seul ERROR_ACCESS_DENIED (5) justifie une nouvelle tentative --
    toute autre erreur (volume déjà démonté, périphérique disparu...) est
    propagée immédiatement, réessayer n'y changerait rien."""
    kernel32 = MagicMock()
    kernel32.DeviceIoControl.return_value = False
    mock_kernel32_factory.return_value = kernel32

    try:
        winlock._lock_volume(123)
        assert False, "aurait dû lever DeviceIoControlError"
    except winlock.DeviceIoControlError:
        pass
    except winlock.VolumeInUseError:
        assert False, "ne doit pas être classé comme volume occupé : erreur sans rapport"

    assert kernel32.DeviceIoControl.call_count == 1
    mock_sleep.assert_not_called()


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

    winlock.refresh_disk_properties(r"\\.\PhysicalDrive9902")

    codes = [c.args[1] for c in kernel32.DeviceIoControl.call_args_list]
    assert codes == [winlock.IOCTL_DISK_UPDATE_PROPERTIES]
    kernel32.CloseHandle.assert_called_once()


@patch("r36s_studio.imaging.winlock._kernel32")
def test_refresh_disk_properties_is_best_effort_on_invalid_handle(mock_kernel32_factory):
    kernel32 = MagicMock()
    kernel32.CreateFileW.return_value = winlock.INVALID_HANDLE_VALUE
    mock_kernel32_factory.return_value = kernel32

    winlock.refresh_disk_properties(r"\\.\PhysicalDrive9902")  # ne doit pas lever

    kernel32.DeviceIoControl.assert_not_called()


@patch("r36s_studio.imaging.winlock._kernel32")
def test_eject_media_sends_eject_ioctl_and_closes_handle(mock_kernel32_factory):
    kernel32 = _fake_kernel32()
    mock_kernel32_factory.return_value = kernel32

    winlock.eject_media(r"\\.\PhysicalDrive9902")

    codes = [c.args[1] for c in kernel32.DeviceIoControl.call_args_list]
    assert codes == [winlock.IOCTL_STORAGE_EJECT_MEDIA]
    kernel32.CloseHandle.assert_called_once()


@patch("r36s_studio.imaging.winlock._kernel32")
def test_eject_media_raises_on_invalid_handle(mock_kernel32_factory):
    """Contrairement à `refresh_disk_properties` (best-effort), une
    éjection qui échoue doit être signalée, pas avalée silencieusement."""
    kernel32 = MagicMock()
    kernel32.CreateFileW.return_value = winlock.INVALID_HANDLE_VALUE
    mock_kernel32_factory.return_value = kernel32

    try:
        winlock.eject_media(r"\\.\PhysicalDrive9902")
        assert False, "aurait dû lever OSError"
    except OSError:
        pass


@patch("r36s_studio.imaging.winlock._kernel32")
def test_eject_media_raises_and_still_closes_handle_when_ioctl_fails(mock_kernel32_factory):
    kernel32 = _fake_kernel32()
    kernel32.DeviceIoControl.return_value = False
    mock_kernel32_factory.return_value = kernel32

    try:
        winlock.eject_media(r"\\.\PhysicalDrive9902")
        assert False, "aurait dû lever OSError"
    except OSError:
        pass

    kernel32.CloseHandle.assert_called_once()
