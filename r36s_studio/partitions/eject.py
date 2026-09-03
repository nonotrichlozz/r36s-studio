"""Éjection de la carte SD (étape F du workflow à deux cartes, §4.4/§4.5) :
démonte toutes les partitions du périphérique et l'éjecte, par OS. La
confirmation explicite que la carte peut être retirée physiquement (§4.5)
est de la responsabilité de l'appelant (CLI/GUI) — cette fonction se
contente de réussir ou de lever, sans afficher quoi que ce soit elle-même.

Best-effort : une erreur ici ne remet jamais en cause le résultat d'une
opération précédente (backup/flash/...) — à l'appelant de l'afficher sans
bloquer le reste de l'écran quand elle est déclenchée depuis l'écran
Résultat plutôt que comme étape F à part entière."""

from __future__ import annotations

import platform
import re
import subprocess
from typing import List

_PHYSICAL_DRIVE_RE = re.compile(r"PhysicalDrive(\d+)$", re.IGNORECASE)


def eject(device_path: str) -> None:
    """Démonte `device_path` (toutes ses partitions, pas juste une) puis
    l'éjecte. Lève en cas d'échec ; ne retourne rien de particulier en cas
    de succès — c'est l'absence d'exception qui vaut confirmation."""
    system = platform.system()
    if system == "Darwin":
        # `diskutil eject` démonte d'abord tous les volumes du disque
        # (équivalent à `unmountDisk`) avant l'éjection matérielle.
        subprocess.run(["diskutil", "eject", device_path], check=True)
    elif system == "Linux":
        # `power-off` démonte toutes les partitions montées du périphérique
        # puis coupe l'alimentation du bus -- la carte peut être retirée.
        subprocess.run(["udisksctl", "power-off", "-b", device_path], check=True)
    elif system == "Windows":
        _windows_eject(device_path)
    else:
        raise NotImplementedError(f"Éjection non supportée sur {system}")


def _windows_disk_number(device_path: str) -> int:
    match = _PHYSICAL_DRIVE_RE.search(device_path)
    if not match:
        raise OSError(f"chemin de périphérique Windows inattendu : {device_path}")
    return int(match.group(1))


def _windows_drive_letters(disk_number: int) -> List[str]:
    """Lettres de lecteur (`"D:\\"`) des partitions montées du disque --
    certaines partitions (BOOT sans lettre, §4.4) n'en ont pas et sont
    simplement absentes du résultat, rien à démonter pour elles."""
    command = (
        f"Get-Partition -DiskNumber {disk_number} | "
        "Where-Object DriveLetter | "
        "ForEach-Object { \"$($_.DriveLetter):\\\" }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _windows_eject(device_path: str) -> None:
    """Verrouille et démonte chaque volume monté du disque
    (`imaging/winlock.py`, même mécanisme que l'écriture brute, §4.3 --
    sans ce démontage Windows refuse l'éjection tant qu'un volume est
    encore monté), puis envoie l'éjection matérielle proprement dite
    (`IOCTL_STORAGE_EJECT_MEDIA`) au disque physique."""
    from r36s_studio.imaging import winlock

    disk_number = _windows_disk_number(device_path)
    mountpoints = _windows_drive_letters(disk_number)
    handles = winlock.lock_and_dismount_volumes(mountpoints) if mountpoints else []
    try:
        winlock.eject_media(device_path)
    finally:
        winlock.unlock_volumes(handles)


__all__ = ["eject"]
