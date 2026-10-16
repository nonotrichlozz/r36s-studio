# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Partition de jeux sans lettre de lecteur sous Windows.

Constaté sur du vrai matériel (2026-10-17, dArkOSen, carte de 32 Go) :
après l'agrandissement de la partition de jeux par la console au premier
démarrage, Windows ne lui attribue plus de lettre -- elle n'apparaît pas
dans l'Explorateur, l'utilisateur ne sait pas où copier ses jeux. L'app,
elle, la lit déjà par son chemin GUID (`locate.py::_list_windows`).

Deux temps, comme le reste du projet (§3) : la détection
(`games_partition_missing_letter`) se fait sans élévation ; l'attribution
(`assign_games_drive_letters`, `Add-PartitionAccessPath -AssignDriveLetter`,
même mécanisme qu'après un formatage, `imaging/games_partition.py::
_format_windows`) exige l'élévation et ne tourne que dans le worker
(`__main__.py::cmd_assign_letter`). N'écrit rien sur la carte : la lettre
est une affectation de Windows, pas une donnée du disque.
"""

from __future__ import annotations

import platform
import re
import subprocess
from dataclasses import asdict, dataclass
from typing import List

from r36s_studio.winprocess import no_console_kwargs

from .locate import EASYROMS_LABEL, list_partitions

# STORAGE (ROCKNIX, EmuELEC) est en ext4 : jamais de volume Windows à lettrer.
_LETTER_MOUNTPOINT = re.compile(r"^[A-Za-z]:\\?$")


@dataclass
class AssignedLetter:
    letter: str  # "" si Windows n'en a attribué aucune
    filesystem: str  # tel que rapporté par Get-Volume (« exFAT », « NTFS »…)
    no_default_drive_letter: bool  # attribut GPT qui empêche la lettre automatique

    def to_dict(self) -> dict:
        return asdict(self)


def games_partition_missing_letter(device_path: str) -> bool:
    """Vrai si une partition EASYROMS de la carte n'a pas de lettre de
    lecteur. Windows uniquement, sans élévation ; faux en cas de doute
    (jamais d'invite UAC sur une simple erreur de lecture)."""
    if platform.system() != "Windows":
        return False
    try:
        partitions = list_partitions(device_path)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return False
    return any(
        p.label.upper() == EASYROMS_LABEL and not _LETTER_MOUNTPOINT.match(p.mountpoint or "") for p in partitions
    )


def assign_games_drive_letters(device_path: str) -> List[AssignedLetter]:
    """Attribue la première lettre libre à chaque partition EASYROMS sans
    lettre. Exige l'élévation (worker). Lève `OSError` si PowerShell échoue."""
    match = re.search(r"PhysicalDrive(\d+)", device_path)
    if not match:
        raise ValueError(f"chemin de périphérique Windows invalide : {device_path}")
    command = (
        "$diskNumber = %s\n"
        "Get-Partition -DiskNumber $diskNumber | ForEach-Object {\n"
        "    $volume = $_ | Get-Volume -ErrorAction SilentlyContinue\n"
        "    if ($volume -and $volume.FileSystemLabel -eq '%s' -and -not [int][char]$_.DriveLetter) {\n"
        "        $_ | Add-PartitionAccessPath -AssignDriveLetter -ErrorAction SilentlyContinue\n"
        "        $updated = Get-Partition -DiskNumber $diskNumber -PartitionNumber $_.PartitionNumber\n"
        "        $letter = if ([int][char]$updated.DriveLetter) { [string]$updated.DriveLetter } else { '' }\n"
        "        Write-Output \"GAMES=$letter|$($volume.FileSystem)|$($_.NoDefaultDriveLetter)\"\n"
        "    }\n"
        "}\n"
    ) % (match.group(1), EASYROMS_LABEL)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        **no_console_kwargs(),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise OSError(f"Attribution de la lettre de lecteur : échec (code {result.returncode})" + (f" : {detail}" if detail else ""))
    assigned = []
    for line in (result.stdout or "").splitlines():
        found = re.match(r"^GAMES=([A-Za-z]?)\|([^|]*)\|(\w*)$", line.strip())
        if found:
            assigned.append(AssignedLetter(found.group(1).upper(), found.group(2), found.group(3).lower() == "true"))
    return assigned


__all__ = ["AssignedLetter", "assign_games_drive_letters", "games_partition_missing_letter"]
