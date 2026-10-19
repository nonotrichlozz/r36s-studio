# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Espace de jeux (EASYROMS) des cartes branchées, monté au besoin --
mêmes garde-fous que la GUI (`safety.filter_devices` : jamais un disque
système, jamais un disque trop gros) et même localisation
(`partitions/locate.py`). Bloquant (montage) : à appeler hors de la boucle
asyncio."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import List

from r36s_studio.devices import list_devices
from r36s_studio.partitions import EASYROMS_LABEL, list_partitions
from r36s_studio.partitions.locate import PartitionNotFound, PartitionNotMounted, locate_mounted, selected_easyroms_partition
from r36s_studio.safety import filter_devices

__all__ = ["GamesFolder", "find_games_folders"]


@dataclass(frozen=True)
class GamesFolder:
    card: str  # nom de la carte, tel qu'affiché par la GUI
    path: str  # point de montage d'EASYROMS (ligne à part, jamais le message principal)


def find_games_folders() -> List[GamesFolder]:
    folders = []
    for device in filter_devices(list_devices()):
        try:
            if selected_easyroms_partition(list_partitions(device.path)) is None:
                continue
            partition = locate_mounted(device.path, EASYROMS_LABEL)
        except (PartitionNotFound, PartitionNotMounted, NotImplementedError, OSError, ValueError, subprocess.CalledProcessError):
            continue
        if partition.mountpoint:
            folders.append(GamesFolder(device.display, partition.mountpoint))
    return folders
