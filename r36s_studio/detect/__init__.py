"""Détection de l'état de la carte SD insérée (§4.5) — le module qui rend
l'application utilisable par un néophyte. Le vrai parcours utilisateur
enchaîne deux cartes différentes (l'ancienne, puis la neuve) sur six
étapes chronologiques fixes (§4.5, §4.6) : ce module n'essaie donc plus de
résumer la carte branchée en un seul état qui déciderait d'une action à
mettre en avant — il indique seulement, pour chacune des six étapes,
si elle est faisable, déjà faite, ou non pertinente pour la carte
actuellement branchée. Les six étapes restent toujours toutes visibles et
cliquables (§4.5) : ce module *informe*, il ne masque jamais rien.

Lecture seule stricte (§4.5 : « aucune écriture, aucun montage en
écriture ») : s'appuie sur `partitions.locate.list_partitions`, qui
n'interroge que `diskutil`/`lsblk`/`Get-Partition` — jamais un montage,
jamais une écriture — et sur `partitions.archives.list_archives`, une
simple lecture du système de fichiers local (aucune commande système)."""

from __future__ import annotations

import platform
import subprocess
from enum import Enum
from typing import Dict, List, Optional

from r36s_studio.devices import Device
from r36s_studio.partitions import archives
from r36s_studio.partitions.locate import (
    BOOT_LABEL,
    EASYROMS_LABEL,
    PartitionInfo,
    has_boot_partition,
    has_easyroms_partition,
    list_partitions,
    looks_like_arkos,
)

# Clés = noms de job (§4.6), identiques à ceux déjà utilisés par
# `partition_runner.py`/`__main__.py` — "copy_games" reste le nom de
# l'injection sur EASYROMS, même si le §4.5 la décrit comme l'étape E.
EXTRACT_BOOT = "extract_boot"
EXTRACT_EASYROMS = "extract_easyroms"
FLASH = "flash"
INJECT_BOOT = "inject_boot"
COPY_GAMES = "copy_games"
EJECT = "eject"

ALL_STEPS = [EXTRACT_BOOT, EXTRACT_EASYROMS, FLASH, INJECT_BOOT, COPY_GAMES, EJECT]


class StepStatus(Enum):
    AVAILABLE = "available"  # faisable
    DONE = "done"  # déjà faite
    NOT_RELEVANT = "not_relevant"  # non pertinente pour la carte branchée
    PLATFORM_LIMITED = "platform_limited"  # possible en soi, mais bloqué par cet OS (badge « PC ou Linux »)


def _list_partitions_safe(device: Optional[Device]) -> Optional[List[PartitionInfo]]:
    """`None` = lecture impossible (OS non supporté, carte débranchée entre
    temps...) — distinct d'une liste vide (carte vierge, §4.5 `BLANK`).
    Ne lève jamais : une détection ratée ne doit pas planter l'interface."""
    if device is None:
        return None
    try:
        return list_partitions(device.path)
    except (NotImplementedError, OSError, ValueError, subprocess.CalledProcessError):
        return None


def detect_workflow_status(device: Optional[Device]) -> Dict[str, StepStatus]:
    """Statut des six étapes du workflow (§4.5) pour la carte actuellement
    branchée (`device` à `None` si aucune carte, ou plusieurs candidates
    ambiguës — l'appelant décide, voir `main_window.py`). Ne détermine
    jamais qu'une étape est impossible à cliquer : sert uniquement de
    guide, jamais de verrou (un utilisateur averti garde toujours la
    main)."""
    partitions = _list_partitions_safe(device)
    has_card = device is not None
    can_boot = has_card and partitions is not None and has_boot_partition(partitions)
    can_easyroms = has_card and partitions is not None and has_easyroms_partition(partitions)
    is_arkos = has_card and partitions is not None and looks_like_arkos(partitions)

    def _extraction_status(possible: bool, label: str) -> StepStatus:
        if not possible:
            return StepStatus.NOT_RELEVANT
        return StepStatus.DONE if archives.list_archives(label) else StepStatus.AVAILABLE

    def _injection_status(possible: bool) -> StepStatus:
        # "déjà faite" n'a pas de signal fiable ici (rien à comparer sans
        # relire tout le contenu) -- seule la pertinence est indiquée.
        return StepStatus.AVAILABLE if possible else StepStatus.NOT_RELEVANT

    return {
        EXTRACT_BOOT: _extraction_status(can_boot, BOOT_LABEL),
        EXTRACT_EASYROMS: _extraction_status(can_easyroms, EASYROMS_LABEL),
        FLASH: (
            StepStatus.NOT_RELEVANT
            if not has_card
            else (StepStatus.DONE if is_arkos else StepStatus.AVAILABLE)
        ),
        INJECT_BOOT: _injection_status(is_arkos),
        # EASYROMS est en NTFS sur une vraie carte R36S (§4.4) : macOS ne
        # monte le NTFS qu'en lecture seule, donc cette étape échoue
        # toujours sur cet OS, quelle que soit la carte branchée (ou même
        # sans carte du tout) -- une limite de la plateforme, pas de la
        # carte. Prioritaire sur `_injection_status` : contrairement à
        # NOT_RELEVANT (qui dépend de la carte), ce statut ne changerait
        # pas en branchant une autre carte.
        COPY_GAMES: (
            StepStatus.PLATFORM_LIMITED if platform.system() == "Darwin" else _injection_status(is_arkos)
        ),
        EJECT: StepStatus.AVAILABLE if has_card else StepStatus.NOT_RELEVANT,
    }


__all__ = [
    "StepStatus",
    "detect_workflow_status",
    "EXTRACT_BOOT",
    "EXTRACT_EASYROMS",
    "FLASH",
    "INJECT_BOOT",
    "COPY_GAMES",
    "EJECT",
    "ALL_STEPS",
]
