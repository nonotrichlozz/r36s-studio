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
