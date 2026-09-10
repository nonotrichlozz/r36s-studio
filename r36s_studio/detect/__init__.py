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
    selected_easyroms_partition,
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
    # Système présent sur la carte incompatible avec cette étape (badge visible,
    # ex. « Non applicable — carte ROCKNIX »), distinct de NOT_RELEVANT (qui
    # n'affiche pas de badge visible, §5) : ici l'utilisateur doit comprendre
    # *pourquoi*, la raison ne changerait pas en branchant une autre carte du
    # même système.
    SYSTEM_INCOMPATIBLE = "system_incompatible"


# Étiquette réelle observée sur une vraie partition de démarrage ROCKNIX
# (§4.5, phase 8) : contrairement à ArkOS, dont la partition BOOT n'a
# jamais d'étiquette (« NO NAME », voir partitions/locate.py), ROCKNIX
# nomme la sienne explicitement -- un signal fort, sans avoir besoin de la
# monter (règle de ce module : lecture seule stricte, jamais de montage).
ROCKNIX_BOOT_LABEL = "ROCKNIX"


class CardSystem(Enum):
    """Système déjà présent sur la carte, à partir de ses partitions
    seules (aucun montage, comme le reste de ce module) -- distinct du
    `CardState` retiré plus haut dans l'historique de ce projet
    (`NO_CARD`/`BLANK`/`ORIGINAL`/`ARKOS`/`UNKNOWN`) : celui-ci tentait de
    résumer TOUTE la carte branchée en un état unique décidant d'UNE seule
    action à mettre en avant sur l'accueil, ce qui ne correspondait pas au
    vrai parcours à deux cartes et six étapes toujours visibles (§4.5).
    `CardSystem` répond à une question plus étroite et complémentaire :
    « quel système est déjà sur cette carte ? » -- pour adapter les
    étapes qui n'ont de sens que pour un système donné (extraction/
    injection du BOOT et d'EASYROMS, propres à ArkOS), sans jamais rien
    masquer côté mode expert (toujours toutes les six étapes visibles,
    juste annotées différemment) ni décider d'UNE action à la place de
    l'utilisateur."""

    ARKOS = "arkos"
    ROCKNIX = "rocknix"
    UNKNOWN = "unknown"


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


def detect_card_system(partitions: Optional[List[PartitionInfo]]) -> CardSystem:
    """Système déjà présent sur la carte, à partir de `partitions` seules
    (aucun montage). `partitions` à `None` (lecture impossible) ou vide
    (carte vierge) retombe sur `UNKNOWN` — jamais une exception. ROCKNIX
    reconnu par l'étiquette de sa partition de démarrage (`ROCKNIX_BOOT_
    LABEL`, un signal fort et gratuit, sans montage) ; ArkOS par
    `looks_like_arkos` (BOOT + EASYROMS identifiables par position/
    système de fichiers, §4.4) — vérifié après ROCKNIX, dont la structure
    réelle (MBR, 2 partitions seulement : ROCKNIX en FAT32 ~2,1 Go puis
    une partition Linux ~29,8 Go, opaque depuis macOS/Windows, aucune
    partition de jeux séparée) ne recouvre de toute façon jamais celle
    d'ArkOS."""
    if not partitions:
        return CardSystem.UNKNOWN
    if any(partition.label.upper() == ROCKNIX_BOOT_LABEL for partition in partitions):
        return CardSystem.ROCKNIX
    if looks_like_arkos(partitions):
        return CardSystem.ARKOS
    return CardSystem.UNKNOWN


def detect_workflow_status(device: Optional[Device]) -> Dict[str, StepStatus]:
    """Statut des six étapes du workflow (§4.5) pour la carte actuellement
    branchée (`device` à `None` si aucune carte, ou plusieurs candidates
    ambiguës — l'appelant décide, voir `main_window.py`). Ne détermine
    jamais qu'une étape est impossible à cliquer : sert uniquement de
    guide, jamais de verrou (un utilisateur averti garde toujours la
    main)."""
    partitions = _list_partitions_safe(device)
    has_card = device is not None
    card_system = detect_card_system(partitions)
    # ROCKNIX ne gère ni le BOOT ni l'EASYROMS à la façon d'ArkOS (§4.5,
    # CardSystem) : les quatre étapes qui en dépendent sont incompatibles
    # avec ce système, quel que soit le contenu détaillé des partitions --
    # prioritaire sur le calcul habituel (can_boot/can_easyroms/is_arkos
    # ci-dessous), qui resterait sinon trompeur (ex. la première partition
    # ROCKNIX, en FAT32, passerait à tort le test structurel de BOOT).
    is_rocknix = card_system == CardSystem.ROCKNIX
    can_boot = has_card and partitions is not None and has_boot_partition(partitions)
    can_easyroms = has_card and partitions is not None and has_easyroms_partition(partitions)
    is_arkos = card_system == CardSystem.ARKOS
    # Système de fichiers réel d'EASYROMS sur *cette* carte -- varie selon
    # le vendeur (NTFS constaté sur certaines cartes, exFAT sur d'autres,
    # confirmé sur du vrai matériel). Seul le NTFS est bloqué en écriture
    # par le pilote intégré de macOS ; l'exFAT s'écrit nativement, comme le
    # FAT. Par défaut (aucune carte branchée, ou EASYROMS pas identifiable
    # sur celle-ci) on suppose le pire (NTFS) pour garder l'avertissement
    # précoce sur macOS, même sans carte -- seule une carte dont EASYROMS
    # est *positivement* identifiée avec un autre système de fichiers lève
    # la limitation.
    easyroms_partition = selected_easyroms_partition(partitions) if partitions else None
    easyroms_is_ntfs_or_unknown = easyroms_partition is None or easyroms_partition.filesystem == "ntfs"

    def _extraction_status(possible: bool, label: str) -> StepStatus:
        if is_rocknix:
            return StepStatus.SYSTEM_INCOMPATIBLE
        if not possible:
            return StepStatus.NOT_RELEVANT
        return StepStatus.DONE if archives.list_archives(label) else StepStatus.AVAILABLE

    def _injection_status(possible: bool) -> StepStatus:
        # "déjà faite" n'a pas de signal fiable ici (rien à comparer sans
        # relire tout le contenu) -- seule la pertinence est indiquée.
        if is_rocknix:
            return StepStatus.SYSTEM_INCOMPATIBLE
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
        # EASYROMS est en NTFS sur certaines cartes R36S ArkOS, en exFAT sur
        # d'autres (§4.4, varie selon le vendeur, confirmé sur du vrai
        # matériel) : seul le NTFS est concerné par la limitation macOS (son
        # pilote intégré ne le monte qu'en lecture seule) -- l'exFAT s'écrit
        # nativement, comme le FAT. `easyroms_is_ntfs_or_unknown` ci-dessus
        # ne lève la limitation que si cette carte a positivement confirmé
        # un autre système de fichiers. Vérifié après `is_rocknix` : une
        # carte ROCKNIX n'a de toute façon aucune partition NTFS (sa
        # seconde partition est Linux, opaque depuis tous les OS de bureau
        # de la même façon) -- la vraie raison est alors le système de la
        # carte, pas la plateforme, même sur macOS.
        COPY_GAMES: (
            StepStatus.SYSTEM_INCOMPATIBLE
            if is_rocknix
            else StepStatus.PLATFORM_LIMITED
            if platform.system() == "Darwin" and easyroms_is_ntfs_or_unknown
            else _injection_status(is_arkos)
        ),
        EJECT: StepStatus.AVAILABLE if has_card else StepStatus.NOT_RELEVANT,
    }


__all__ = [
    "StepStatus",
    "CardSystem",
    "ROCKNIX_BOOT_LABEL",
    "detect_card_system",
    "detect_workflow_status",
    "EXTRACT_BOOT",
    "EXTRACT_EASYROMS",
    "FLASH",
    "INJECT_BOOT",
    "COPY_GAMES",
    "EJECT",
    "ALL_STEPS",
]
