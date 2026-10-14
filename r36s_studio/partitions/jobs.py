# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Orchestration des jobs du §4.6 : extraction d'EASYROMS vers
l'ordinateur, et copie de jeux sur une carte (déplacer ses jeux entre deux
cartes de taille ou de firmware différents). L'extraction/injection du
BOOT a été retirée le 2026-10-14 (doublon de la sauvegarde système).
Localise et attend le montage de la partition source/cible (`locate.py`),
puis copie (`copy.py`).

**Extraction vs injection** : l'extraction ne fait que *lire* la partition
source (`partition.mountpoint` devient la source de `copy_tree`, l'écriture
se fait vers un dossier de l'ordinateur) — la limitation d'écriture NTFS de
macOS (`_reject_macos_ntfs_write`) ne s'applique donc jamais à l'extraction
d'EASYROMS : macOS monte nativement les volumes NTFS en lecture seule, ce
qui suffit très bien pour lire."""

from __future__ import annotations

import platform
from typing import Optional

from r36s_studio.devices import Device
from r36s_studio.imaging.copy import CancelCheck, ProgressCallback

from .copy import copy_tree
from .locate import EASYROMS_LABEL, PartitionInfo, locate_mounted, unmount_forced


class MacosNtfsWriteUnsupported(Exception):
    """EASYROMS est en NTFS (confirmé sur du vrai matériel — §4.4). Le
    pilote NTFS intégré de macOS ne le monte qu'en lecture seule : sans
    détection explicite, la copie échouerait avec une erreur d'écriture
    incompréhensible pour un néophyte (règle §1 : jamais de terminal, jamais
    de jargon)."""

    def __init__(self, label: str):
        super().__init__(
            f"macOS ne peut pas écrire sur la partition « {label} » (NTFS) : son "
            "pilote intégré ne la monte qu'en lecture seule. Utilise un PC "
            "Windows ou Linux pour copier des jeux, ou installe un pilote NTFS "
            "en écriture sur ce Mac (ex. Tuxera NTFS, Paragon NTFS for Mac)."
        )
        self.label = label


def copy_games(
    device: Device,
    games_source_dir: str,
    on_progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCheck] = None,
) -> int:
    """Copie `games_source_dir` sur la partition EASYROMS de `device`. Lève
    `MacosNtfsWriteUnsupported` avant toute écriture si l'OS courant est
    macOS et que la partition est en NTFS (cas confirmé sur du matériel
    réel, voir `locate.py`)."""
    partition = locate_mounted(device.path, EASYROMS_LABEL)
    _reject_macos_ntfs_write(partition)
    copied = copy_tree(
        games_source_dir, partition.mountpoint, on_progress=on_progress, should_cancel=should_cancel
    )
    unmount_forced(partition)
    return copied


def _reject_macos_ntfs_write(partition: PartitionInfo) -> None:
    if platform.system() == "Darwin" and partition.filesystem == "ntfs":
        raise MacosNtfsWriteUnsupported(partition.label)


def extract_easyroms(
    device: Device,
    dest_dir: str,
    on_progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCheck] = None,
) -> int:
    """Copie la partition EASYROMS de `device` vers `dest_dir`. Contrairement
    à `copy_games`, ne lève jamais `MacosNtfsWriteUnsupported` : on ne fait
    que lire EASYROMS ici, jamais y écrire (voir note de module)."""
    partition = locate_mounted(device.path, EASYROMS_LABEL)
    copied = copy_tree(
        partition.mountpoint, dest_dir, on_progress=on_progress, should_cancel=should_cancel
    )
    unmount_forced(partition)
    return copied


