"""Verrouillage et démontage des volumes Windows avant l'écriture brute sur
`\\\\.\\PhysicalDriveN` (§4.3). Sans ce verrouillage, Windows refuse
l'écriture ou corrompt la carte.

N'est exécuté que sous `platform.system() == "Windows"` (voir
`write_target.py`) : les appels `ctypes.WinDLL` sont donc systématiquement
enveloppés dans des fonctions, jamais évalués à l'import, pour que ce module
reste important sans erreur sur macOS/Linux (utile pour les tests, en
mockant `_kernel32`)."""

from __future__ import annotations

import ctypes
from typing import List

FSCTL_LOCK_VOLUME = 0x00090018
FSCTL_DISMOUNT_VOLUME = 0x00090020
IOCTL_DISK_UPDATE_PROPERTIES = 0x00070140
IOCTL_STORAGE_EJECT_MEDIA = 0x002D4808

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = 0xFFFFFFFF  # comparé en tant qu'entier non signé 64 bits


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _last_error():
    """`ctypes.get_last_error` n'existe que sous Windows -- absent du
    module sur macOS/Linux, ce qui romprait l'import de ce fichier si on
    y accédait sans garde (même juste pour le message d'erreur)."""
    get_last_error = getattr(ctypes, "get_last_error", None)
    return get_last_error() if get_last_error is not None else None


def _drive_letter_to_volume_path(mountpoint: str) -> str:
    """"D:\\" -> "\\\\.\\D:" """
    letter = mountpoint.rstrip("\\")
    return f"\\\\.\\{letter}"


def _open_volume_handle(volume_path: str):
    kernel32 = _kernel32()
    handle = kernel32.CreateFileW(
        volume_path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle in (0, -1, INVALID_HANDLE_VALUE):
        raise OSError(f"impossible d'ouvrir le volume {volume_path} (erreur {_last_error()})")
    return handle


def _device_io_control(handle, code: int) -> None:
    kernel32 = _kernel32()
    bytes_returned = ctypes.c_ulong(0)
    ok = kernel32.DeviceIoControl(
        handle, code, None, 0, None, 0, ctypes.byref(bytes_returned), None
    )
    if not ok:
        raise OSError(f"DeviceIoControl a échoué (code {code:#x}, erreur {_last_error()})")


def lock_and_dismount_volumes(mountpoints: List[str]) -> List[object]:
    """Verrouille (`FSCTL_LOCK_VOLUME`) puis démonte (`FSCTL_DISMOUNT_VOLUME`)
    chaque volume monté du disque cible. Retourne les handles ouverts, à
    refermer avec `unlock_volumes` une fois l'écriture terminée. Si un
    volume échoue, referme d'abord ceux déjà verrouillés avant de
    propager l'erreur."""
    handles: List[object] = []
    try:
        for mountpoint in mountpoints:
            volume_path = _drive_letter_to_volume_path(mountpoint)
            handle = _open_volume_handle(volume_path)
            _device_io_control(handle, FSCTL_LOCK_VOLUME)
            _device_io_control(handle, FSCTL_DISMOUNT_VOLUME)
            handles.append(handle)
    except Exception:
        unlock_volumes(handles)
        raise
    return handles


def unlock_volumes(handles: List[object]) -> None:
    kernel32 = _kernel32()
    for handle in handles:
        kernel32.CloseHandle(handle)


def eject_media(physical_drive_path: str) -> None:
    """`IOCTL_STORAGE_EJECT_MEDIA` sur `\\\\.\\PhysicalDriveN` (§4.5 étape F
    /`partitions/eject.py`) -- l'éjection matérielle proprement dite,
    distincte du verrouillage/démontage des volumes ci-dessus (nécessaire
    avant, sans quoi Windows refuse l'éjection tant qu'un volume du
    disque est encore monté). Lève en cas d'échec, contrairement à
    `refresh_disk_properties` (best-effort) -- une éjection qui échoue
    doit être signalée, pas avalée silencieusement (§2 règle 5)."""
    kernel32 = _kernel32()
    handle = kernel32.CreateFileW(
        physical_drive_path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle in (0, -1, INVALID_HANDLE_VALUE):
        raise OSError(f"impossible d'ouvrir {physical_drive_path} (erreur {_last_error()})")
    try:
        _device_io_control(handle, IOCTL_STORAGE_EJECT_MEDIA)
    finally:
        kernel32.CloseHandle(handle)


def refresh_disk_properties(physical_drive_path: str) -> None:
    """`IOCTL_DISK_UPDATE_PROPERTIES`, pour que l'explorateur se
    rafraîchisse après l'écriture. Best-effort : une erreur ici n'annule
    pas un flash déjà réussi."""
    kernel32 = _kernel32()
    handle = kernel32.CreateFileW(
        physical_drive_path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle in (0, -1, INVALID_HANDLE_VALUE):
        return
    try:
        _device_io_control(handle, IOCTL_DISK_UPDATE_PROPERTIES)
    except OSError:
        pass
    finally:
        kernel32.CloseHandle(handle)
