"""Accès aux fichiers d'une carte ArkOS déjà flashée (§4.4) : localisation
et montage des partitions BOOT/EASYROMS, copie de fichiers, et les deux
jobs qui s'en servent (§4.6) — injection du BOOT et copie de jeux."""

from __future__ import annotations

from .copy import MountpointNotWritable, copy_tree
from .jobs import MacosNtfsWriteUnsupported, copy_games, inject_boot
from .locate import (
    BOOT_LABEL,
    EASYROMS_LABEL,
    PartitionInfo,
    PartitionNotFound,
    PartitionNotMounted,
    find_partition,
    locate_mounted,
)

__all__ = [
    "copy_tree",
    "MountpointNotWritable",
    "MacosNtfsWriteUnsupported",
    "copy_games",
    "inject_boot",
    "BOOT_LABEL",
    "EASYROMS_LABEL",
    "PartitionInfo",
    "PartitionNotFound",
    "PartitionNotMounted",
    "find_partition",
    "locate_mounted",
]
