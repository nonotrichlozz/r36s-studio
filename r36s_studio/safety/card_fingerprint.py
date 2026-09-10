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

"""Garde-fou du mode assisté (§5) : distingue la carte d'origine (étape 1)
de la carte neuve (étape 4) par une empreinte de son **contenu**, pas par
`path`/`size_bytes` -- ces deux-là ne suffisent pas (sur macOS, le chemin
d'un disque peut changer entre deux branchements ; deux cartes du même
modèle ont exactement la même taille).

Empreinte calculée à partir des fichiers de la partition BOOT (montage en
lecture seule, jamais privilégié -- §4.4, comme `extract_boot`) plutôt que
des octets bruts du périphérique : lire le périphérique brut exige
l'élévation (§3, réservée au worker pour les écritures), ce qu'on ne veut
pas déclencher juste pour comparer deux cartes à une étape qui n'écrit
rien. Une carte vierge ou sans BOOT lisible n'a pas d'empreinte (`None`).

⚠️ Correction de conception, confirmée sur du vrai matériel : la phrase
ci-dessus supposait à tort que la carte *source* a toujours une empreinte
à ce stade du parcours (« trivialement différente de la carte d'origine,
qui elle en a toujours une »). Faux depuis que le parcours de clonage
clone n'importe quel firmware (§5) : une source vierge, ou dont le BOOT
n'est simplement pas reconnu, produit aussi `None` -- et `is_same_card`
seule ne peut alors plus rien affirmer, désactivant silencieusement ce
garde-fou. Voir `is_same_card_or_unverifiable` ci-dessous, le repli requis
dans ce cas précis."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Optional

from r36s_studio.partitions.locate import (
    BOOT_LABEL,
    PartitionNotFound,
    PartitionNotMounted,
    has_boot_partition,
    list_partitions,
    locate_mounted,
    unmount_forced,
)

# Borne le volume lu par fichier (BOOT est FAT, ~100-120 Mo en pratique) --
# assez pour distinguer deux contenus différents sans relire toute la
# partition à chaque étape.
_MAX_BYTES_PER_FILE = 65536


def compute_boot_fingerprint(device_path: str) -> Optional[str]:
    """`None` si aucune empreinte n'a pu être calculée (pas de BOOT, montage
    impossible, lecture ratée) -- ne lève jamais, même principe que
    `detect._list_partitions_safe`."""
    try:
        partitions = list_partitions(device_path)
    except (NotImplementedError, OSError, ValueError, subprocess.CalledProcessError):
        return None

    if not has_boot_partition(partitions):
        return None

    try:
        boot = locate_mounted(device_path, BOOT_LABEL)
    except (PartitionNotFound, PartitionNotMounted, OSError, subprocess.CalledProcessError):
        return None

    if not boot.mountpoint:
        return None

    root = Path(boot.mountpoint)
    digest = hashlib.sha256()
    try:
        paths = sorted(p for p in root.rglob("*") if p.is_file())
    except OSError:
        return None

    for path in paths:
        try:
            relative = path.relative_to(root)
            size = path.stat().st_size
        except OSError:
            continue
        digest.update(str(relative).encode("utf-8", errors="replace"))
        digest.update(str(size).encode("ascii"))
        try:
            with open(path, "rb") as handle:
                digest.update(handle.read(_MAX_BYTES_PER_FILE))
        except OSError:
            continue

    unmount_forced(boot)
    return digest.hexdigest()


def is_same_card(fingerprint_a: Optional[str], fingerprint_b: Optional[str]) -> bool:
    """Vrai seulement si les deux empreintes existent et sont identiques --
    `None` ne prouve jamais une égalité, il signifie « pas d'empreinte »."""
    return fingerprint_a is not None and fingerprint_a == fingerprint_b


def size_proves_different_card(
    source_size_bytes: Optional[int], target_size_bytes: Optional[int]
) -> bool:
    """Vrai seulement si les deux tailles sont connues et diffèrent -- une
    carte ne change jamais de capacité, une différence est donc une preuve
    positive qu'il s'agit d'une carte différente. L'inverse n'est jamais
    vrai : deux tailles identiques (cas courant en préparant plusieurs
    consoles avec des cartes du même modèle) ne prouvent rien -- ni que
    c'est la même carte, ni le contraire. `None` (taille inconnue) ne
    prouve jamais rien non plus.

    ⚠️ Correction de conception, confirmée sur du vrai matériel :
    remplace `is_same_card_or_unverifiable` (repli sur le chemin de
    périphérique), qui s'est révélé non fonctionnel en pratique -- certains
    lecteurs de carte SD Windows gardent le même chemin
    (`\\\\.\\PhysicalDriveN`) quelle que soit la carte insérée dans le même
    emplacement, donc *jamais différent* même après un vrai changement de
    carte. Un repli sur un signal qui ne varie jamais bloquerait le
    parcours indéfiniment sur ce type de lecteur, sans issue -- pire que le
    problème d'origine. Voir `gui/screens.py::SameCardUnverifiedDialog` :
    quand ni le contenu (`is_same_card`) ni la taille ne peuvent trancher,
    le parcours exige désormais une confirmation explicite de
    l'utilisateur plutôt qu'un signal automatique supplémentaire."""
    return (
        source_size_bytes is not None
        and target_size_bytes is not None
        and source_size_bytes != target_size_bytes
    )
