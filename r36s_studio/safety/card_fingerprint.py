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
rien. Une carte vierge ou sans BOOT lisible n'a pas d'empreinte (`None`) --
trivialement différente de la carte d'origine, qui elle en a toujours une
à ce stade du parcours."""

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
