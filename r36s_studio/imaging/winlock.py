# R36S Studio
# Copyright (C) 2026 nonotrichlozz
#
# Ce fichier fait partie de R36S Studio. R36S Studio est un logiciel libre :
# vous pouvez le redistribuer et/ou le modifier selon les termes de la GNU
# General Public License telle que publiée par la Free Software Foundation,
# version 3 de la licence.
#
# R36S Studio est distribué dans l'espoir qu'il sera utile, mais SANS
# AUCUNE GARANTIE ; sans même la garantie implicite de QUALITÉ MARCHANDE ou
# d'ADÉQUATION À UN USAGE PARTICULIER. Consultez la GNU General Public
# License pour plus de détails.
#
# Vous devez avoir reçu une copie de la GNU General Public License avec
# R36S Studio. Si ce n'est pas le cas, consultez <https://www.gnu.org/licenses/>.

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
import time
from typing import List, Optional

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

ERROR_ACCESS_DENIED = 5

# Bug corrigé, confirmé sur du vrai matériel : `FSCTL_LOCK_VOLUME` échoue
# régulièrement avec `ERROR_ACCESS_DENIED` (5) même sur un worker déjà
# élevé -- ce n'est donc jamais un problème de privilèges (une élévation
# refusée/absente échouerait autrement, avant même d'atteindre ce point),
# mais un AUTRE processus (Explorateur qui prévisualise le volume,
# l'indexeur de recherche, un antivirus) qui tient encore un descripteur
# ouvert dessus au moment précis où le worker tente de le verrouiller.
# Ce genre de descripteur transitoire se libère très souvent en une ou
# deux secondes -- quelques tentatives espacées d'un court délai avant
# d'abandonner, plutôt qu'un échec immédiat sur la toute première.
LOCK_VOLUME_RETRY_COUNT = 5
LOCK_VOLUME_RETRY_DELAY_SECONDS = 0.5


class DeviceIoControlError(OSError):
    """Levée par `_device_io_control` -- porte le code Win32 réel
    (`GetLastError`) dans `win32_error`, pour que l'appelant puisse
    distinguer un refus d'accès (`ERROR_ACCESS_DENIED`, 5) d'une autre
    défaillance sans avoir à reparser le message."""

    def __init__(self, message: str, win32_error: Optional[int]):
        super().__init__(message)
        self.win32_error = win32_error


class VolumeInUseError(OSError):
    """`FSCTL_LOCK_VOLUME` a échoué avec `ERROR_ACCESS_DENIED` sur toutes
    les tentatives (`LOCK_VOLUME_RETRY_COUNT`, voir plus haut) -- distincte
    d'une `OSError` générique pour que `write_target.py`/le protocole
    puissent émettre un message dédié (« un programme utilise encore la
    carte ») plutôt que le message générique d'erreur d'E/S, faux dans ce
    cas précis (le worker est bien élevé, la carte est bien branchée)."""


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _last_error():
    """`ctypes.get_last_error` n'existe que sous Windows -- absent du
    module sur macOS/Linux, ce qui romprait l'import de ce fichier si on
    y accédait sans garde (même juste pour le message d'erreur)."""
    get_last_error = getattr(ctypes, "get_last_error", None)
    return get_last_error() if get_last_error is not None else None


def _drive_letter_to_volume_path(mountpoint: str) -> str:
    """"D:\\" -> "\\\\.\\D:" -- un chemin déjà dans l'espace de noms
    périphérique (`\\\\?\\Volume{GUID}\\`, une partition sans lettre de
    lecteur identifiée par son chemin GUID, §4.4/§4.3) est retourné tel
    quel, seulement débarrassé de son `\\` final : le préfixer à nouveau
    par `\\\\.\\` produirait un chemin invalide."""
    if mountpoint.startswith("\\\\?\\") or mountpoint.startswith("\\\\.\\"):
        return mountpoint.rstrip("\\")
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
        error = _last_error()
        raise DeviceIoControlError(f"DeviceIoControl a échoué (code {code:#x}, erreur {error})", error)


def _lock_volume(handle) -> None:
    """`FSCTL_LOCK_VOLUME` avec quelques tentatives en cas d'`ERROR_ACCESS_
    DENIED` (voir `LOCK_VOLUME_RETRY_COUNT` ci-dessus) -- toute autre
    erreur est propagée immédiatement, sans intérêt à réessayer."""
    last_exc: Optional[DeviceIoControlError] = None
    for attempt in range(LOCK_VOLUME_RETRY_COUNT):
        try:
            _device_io_control(handle, FSCTL_LOCK_VOLUME)
            return
        except DeviceIoControlError as exc:
            if exc.win32_error != ERROR_ACCESS_DENIED:
                raise
            last_exc = exc
            if attempt < LOCK_VOLUME_RETRY_COUNT - 1:
                time.sleep(LOCK_VOLUME_RETRY_DELAY_SECONDS)
    raise VolumeInUseError(
        "impossible de verrouiller le volume -- probablement utilisé par un autre "
        f"programme (Explorateur, indexeur, antivirus) : {last_exc}"
    ) from last_exc


def lock_and_dismount_volumes(mountpoints: List[str]) -> List[object]:
    """Verrouille (`FSCTL_LOCK_VOLUME`) puis démonte (`FSCTL_DISMOUNT_VOLUME`)
    chaque volume monté du disque cible. `mountpoints` : une lettre de
    lecteur (`"D:\\"`) ou un chemin déjà dans l'espace de noms périphérique
    (`\\\\?\\Volume{GUID}\\`, pour une partition sans lettre -- l'appelant
    doit énumérer *tous* les volumes du disque, lettrés ou non, voir
    `write_target.py` : ne verrouiller que les volumes lettrés laisse un
    volume comme BOOT (FAT, souvent sans lettre sur une carte ArkOS)
    monté pendant l'écriture brute du disque entier, ce que Windows finit
    par détecter en invalidant le handle `\\\\.\\PhysicalDriveN` en cours
    d'écriture pour protéger ce volume). Retourne les handles ouverts, à
    refermer avec `unlock_volumes` une fois l'écriture terminée. Si un
    volume échoue, referme d'abord ceux déjà verrouillés avant de
    propager l'erreur."""
    handles: List[object] = []
    try:
        for mountpoint in mountpoints:
            volume_path = _drive_letter_to_volume_path(mountpoint)
            handle = _open_volume_handle(volume_path)
            _lock_volume(handle)
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
