# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Accès aux fichiers d'une carte SD (§4.4) : localisation et montage des
partitions BOOT/EASYROMS, copie de fichiers, gestion des dossiers
d'archive horodatés, et les jobs qui s'en servent (§4.6) — extraction
depuis l'ancienne carte, injection sur la carte neuve, éjection."""

from __future__ import annotations

from . import archives
from .copy import MountpointNotWritable, copy_tree
from .jobs import (
    MacosNtfsWriteUnsupported,
    copy_games,
    extract_boot,
    extract_easyroms,
    inject_boot,
)
from .locate import (
    BOOT_LABEL,
    EASYROMS_LABEL,
    PartitionInfo,
    PartitionNotFound,
    PartitionNotMounted,
    find_partition,
    has_boot_partition,
    has_easyroms_partition,
    list_partitions,
    locate_mounted,
    looks_like_arkos,
    set_privileged_mount_hook,
    unmount_forced,
)

__all__ = [
    "archives",
    "copy_tree",
    "MountpointNotWritable",
    "MacosNtfsWriteUnsupported",
    "copy_games",
    "extract_boot",
    "extract_easyroms",
    "inject_boot",
    "BOOT_LABEL",
    "EASYROMS_LABEL",
    "PartitionInfo",
    "PartitionNotFound",
    "PartitionNotMounted",
    "find_partition",
    "has_boot_partition",
    "has_easyroms_partition",
    "list_partitions",
    "locate_mounted",
    "looks_like_arkos",
    "set_privileged_mount_hook",
    "unmount_forced",
]
