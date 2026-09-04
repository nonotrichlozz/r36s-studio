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


def is_same_card_or_unverifiable(
    source_fingerprint: Optional[str],
    target_fingerprint: Optional[str],
    source_path: str,
    target_path: str,
) -> bool:
    """Bug corrigé, confirmé sur du vrai matériel : quand la carte
    *source* n'a pas d'empreinte (vierge, ou firmware dont le BOOT n'est
    pas reconnu -- réaliste depuis que le parcours de clonage clone
    n'importe quel firmware, §5), `is_same_card` ne peut plus rien
    affirmer et retourne toujours `False`, quelle que soit la carte
    réellement branchée à l'étape 3 -- le garde-fou est alors
    silencieusement désactivé pour tout le reste du parcours, avec le
    risque d'écrire l'image de sauvegarde par-dessus la carte source
    elle-même si l'utilisateur ne l'a pas physiquement retirée.

    Repli sur `source_path`/`target_path` dans ce cas précis : un chemin
    identique ne *prouve* jamais qu'il s'agit de la même carte physique
    (certains lecteurs Windows gardent le même chemin de disque physique
    quelle que soit la carte insérée dans le même emplacement, §4.4) -- mais
    l'inverse n'est pas prouvable non plus dans ce cas, et le contenu ne
    permet déjà pas de trancher. Échoue donc du côté prudent (bloque)
    plutôt que de laisser passer silencieusement une carte qui pourrait
    être la source (§2 règle 1) : un chemin différent, lui, reste autorisé
    à passer (aucune preuve positive de similarité). Pas d'échappatoire
    dans ce module -- un lecteur à emplacement unique bloquera donc tant
    que la carte source garde une empreinte indisponible, décision
    délibérée (prudence par défaut plutôt qu'une confirmation manuelle
    pour l'instant)."""
    if is_same_card(source_fingerprint, target_fingerprint):
        return True
    if source_fingerprint is None and source_path == target_path:
        return True
    return False
