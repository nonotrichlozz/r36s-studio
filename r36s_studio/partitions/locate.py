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

"""Localisation de la partition `BOOT` ou `EASYROMS` d'une carte ArkOS déjà
flashée (§4.4), par OS. Contrairement à `imaging/` (accès brut au
périphérique entier), ce module ne travaille qu'avec les partitions telles
que le système d'exploitation les voit — montage compris.

**BOOT sans étiquette (bug confirmé sur du vrai matériel)** : sur une vraie
carte ArkOS R36S, la première partition n'a aucune étiquette — `diskutil`
l'affiche « NO NAME », type DOS_FAT_16, ~117,4 Mo. L'identifier par
étiquette est fragile (elle varie selon les versions d'ArkOS et les
vendeurs). BOOT est donc identifiée par sa **position** (première partition
du disque) et son **système de fichiers** (FAT16 ou FAT32) — l'étiquette
« BOOT », quand elle existe, ne sert que de repli.

**BOOT en GPT/EFI (cas confirmé sur du vrai matériel)** : certaines cartes
R36S d'origine utilisent un schéma GPT dont la première partition est de
type EFI (System Partition), contenant malgré tout un FAT16 tout à fait
valide (`Image`, `uInitrd`, `extlinux/`, les `.bmp` de batterie et les
`.dtb`). macOS refuse de la monter automatiquement à cause de ce type —
`diskutil mount` échoue, et son sondage de système de fichiers pour ce cas
précis n'est pas toujours fiable (`_macos_filesystem` peut renvoyer une
chaîne vide). `_select_boot` accepte donc aussi la première partition
quand son type (`partition_type`, renseigné depuis `Content` sur macOS)
vaut EFI et que son système de fichiers, quand il est connu, est un FAT ;
`_mount_macos` retente en plus un montage forcé (`mount -t msdos` sur un
point de montage temporaire, `_force_mount_macos`) quand `diskutil mount`
échoue — confirmé fonctionner sur du vrai matériel là où `diskutil`
échoue. `unmount_forced` démonte proprement ce montage temporaire une
fois la partition exploitée (ne fait rien pour un montage `diskutil`
normal).

**Montage forcé et droits administrateur (confirmé sur du vrai
matériel).** Même le montage forcé non élevé ci-dessus échoue en
pratique (`mount -t msdos` refuse pour la même raison qu'un utilisateur
normal ne peut pas monter un périphérique brut sans passer par
DiskArbitration, §3) : le test manuel réussi utilisait `sudo mount -t
msdos ...`. Ce module reste volontairement sans dépendance vers `gui/` (il
doit rester utilisable depuis le CLI et testable sans Qt, §3) : il expose
donc `set_privileged_mount_hook`, un point d'extension optionnel que la
GUI installe (`gui/main_window.py`, macOS uniquement) pour retenter le
montage forcé avec élévation (`gui/elevate.py::run_privileged_mount`,
même mécanisme que `backup`/`flash`) quand la tentative non élevée
échoue. Sans hook installé (CLI, tests, autres OS), le comportement reste
inchangé : `_force_mount_macos` échoue simplement, comme avant ce
correctif.

**Système de fichiers d'EASYROMS** : le brief initial (§4.4) prévoyait du
FAT32, à vérifier sur une carte réelle. Test fait sur du vrai matériel :
c'est en réalité du **NTFS**. Windows et Linux y écrivent nativement ; le
pilote NTFS intégré de macOS, lui, ne monte les volumes NTFS qu'en lecture
seule — voir `jobs.copy_games`, qui détecte ce cas précis plutôt que de
laisser une copie échouer avec une erreur d'écriture obscure. EASYROMS
étant bien nommée en pratique, elle reste identifiée par étiquette en
priorité, avec un repli sur la position (troisième partition) et le
système de fichiers (NTFS ou FAT) si l'étiquette est absente."""

from __future__ import annotations

import json
import os
import plistlib
import platform
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, replace
from typing import Callable, Optional

from r36s_studio.winprocess import no_console_kwargs

BOOT_LABEL = "BOOT"
EASYROMS_LABEL = "EASYROMS"

# "msdos" (macOS), "vfat" (Linux), "fat16"/"fat32"/"fat" (Windows, générique) :
# toutes les graphies de FAT rencontrées selon l'OS.
FAT_FILESYSTEMS = {"msdos", "vfat", "fat", "fat16", "fat32"}
# Confirmé sur du vrai matériel : le système de fichiers d'EASYROMS varie
# selon le vendeur (NTFS constaté sur certaines cartes, exFAT sur d'autres) --
# une info à consigner, jamais un critère d'exclusion (§ note de module).
EASYROMS_FALLBACK_FILESYSTEMS = FAT_FILESYSTEMS | {"ntfs", "exfat"}

BOOT_PARTITION_INDEX = 0  # première partition du disque
EASYROMS_PARTITION_INDEX = 2  # troisième partition du disque

MOUNT_WAIT_SECONDS = 10.0
MOUNT_POLL_INTERVAL = 0.5


@dataclass
class PartitionInfo:
    device_path: str  # /dev/disk4s1 | /dev/sdb1 | "E:\\" (Windows : déjà la lettre)
    label: str
    filesystem: str  # "fat32", "ntfs", "ext4"... (toujours en minuscules)
    mountpoint: Optional[str]
    # Type de partition (schéma GPT/MBR), pas le système de fichiers --
    # seul macOS le renseigne pour l'instant (`Content` de `diskutil`, voir
    # `_macos_partition_type`), pour reconnaître le cas confirmé sur du vrai
    # matériel d'une première partition GPT de type EFI contenant malgré
    # tout un FAT16 valide (note de module, `_looks_like_efi_boot`).
    partition_type: str = ""
    # Taille en octets, quand l'OS la fournit sans accès brut au
    # périphérique (§4.3, `imaging/system_backup.py::estimate_system_
    # backup_size_unprivileged`) -- `None` sinon (jamais deviné). Confirmé
    # sur du vrai matériel : lire la table de partitions brute (`/dev/
    # diskN`) exige les droits administrateur sur macOS, contrairement à
    # `diskutil info -plist`/`lsblk`/`Get-Volume`, qui exposent déjà la
    # taille sans élévation.
    size_bytes: Optional[int] = None


class PartitionNotFound(Exception):
    def __init__(self, label: str, device_path: str):
        super().__init__(f"Partition « {label} » introuvable sur {device_path}")
        self.label = label


class PartitionNotMounted(Exception):
    def __init__(self, label: str, device_path: str):
        super().__init__(
            f"La partition « {label} » de {device_path} n'a pas été montée "
            "automatiquement (délai dépassé)."
        )
        self.label = label


def _is_fat(filesystem: str) -> bool:
    return filesystem in FAT_FILESYSTEMS


def list_partitions(device_path: str) -> list[PartitionInfo]:
    """Retourne toutes les partitions de `device_path`, dans l'ordre du
    disque (nécessaire pour identifier BOOT/EASYROMS par position)."""
    system = platform.system()
    if system == "Darwin":
        return _list_macos(device_path)
    if system == "Linux":
        return _list_linux(device_path)
    if system == "Windows":
        return _list_windows(device_path)
    raise NotImplementedError(f"OS non supporté : {system}")


def _select_boot(partitions: list[PartitionInfo], device_path: str) -> PartitionInfo:
    """Position + système de fichiers d'abord (voir note de module) ;
    l'étiquette « BOOT » n'est qu'un repli, pour le cas où la première
    partition ne serait pas FAT (carte non standard)."""
    if partitions:
        first = partitions[BOOT_PARTITION_INDEX]
        if _is_fat(first.filesystem) or _looks_like_efi_boot(first):
            return first
    for partition in partitions:
        if partition.label.upper() == BOOT_LABEL:
            return partition
    raise PartitionNotFound(BOOT_LABEL, device_path)


def _looks_like_efi_boot(partition: PartitionInfo) -> bool:
    """Cas confirmé sur du vrai matériel (voir note de module) : une
    première partition GPT de type EFI peut contenir un FAT16 tout à fait
    valide que macOS ne sait pas toujours rapporter comme tel via
    `_macos_filesystem`. Accepté quand le type est EFI et que le système
    de fichiers, s'il est connu, n'est pas explicitement autre chose qu'un
    FAT."""
    if partition.partition_type != "efi":
        return False
    return not partition.filesystem or _is_fat(partition.filesystem)


def _select_easyroms(partitions: list[PartitionInfo], device_path: str) -> PartitionInfo:
    """Étiquette d'abord (EASYROMS est bien nommée en pratique) ; repli sur
    la position (troisième partition) et le système de fichiers (NTFS, FAT
    ou exFAT -- varie selon le vendeur, confirmé sur du vrai matériel) si
    l'étiquette est absente."""
    for partition in partitions:
        if partition.label.upper() == EASYROMS_LABEL:
            return partition
    if len(partitions) > EASYROMS_PARTITION_INDEX:
        candidate = partitions[EASYROMS_PARTITION_INDEX]
        if candidate.filesystem in EASYROMS_FALLBACK_FILESYSTEMS:
            return candidate
    raise PartitionNotFound(EASYROMS_LABEL, device_path)


def has_boot_partition(partitions: list[PartitionInfo]) -> bool:
    """Vrai si `partitions` contient une partition BOOT identifiable
    (position + système de fichiers, voir `_select_boot`) — utilisé par
    `detect` pour savoir si l'extraction du BOOT (§4.4, workflow à deux
    cartes) a un sens sur la carte branchée, sans repasser par
    `find_partition` (qui referait l'appel `list_partitions`)."""
    try:
        _select_boot(partitions, "")
    except PartitionNotFound:
        return False
    return True


def has_easyroms_partition(partitions: list[PartitionInfo]) -> bool:
    """Symétrique de `has_boot_partition`, pour EASYROMS."""
    try:
        _select_easyroms(partitions, "")
    except PartitionNotFound:
        return False
    return True


def selected_easyroms_partition(partitions: list[PartitionInfo]) -> Optional[PartitionInfo]:
    """Retourne la partition EASYROMS identifiée (voir `_select_easyroms`),
    ou `None` si aucune ne l'est -- utilisé par `detect` pour connaître son
    système de fichiers réel (ex. distinguer une EASYROMS NTFS, bloquée en
    écriture sur macOS, d'une EASYROMS exFAT, écriturable nativement) sans
    dupliquer la logique d'identification déjà en place ici."""
    try:
        return _select_easyroms(partitions, "")
    except PartitionNotFound:
        return None


def looks_like_arkos(partitions: list[PartitionInfo]) -> bool:
    """Vrai si `partitions` contient à la fois une partition BOOT et une
    partition EASYROMS identifiables — utilisé par `detect` pour
    reconnaître une carte déjà flashée."""
    return has_boot_partition(partitions) and has_easyroms_partition(partitions)


def find_partition(device_path: str, label: str) -> PartitionInfo:
    """Retourne la partition `label` de `device_path` telle qu'elle est
    actuellement — montée ou non. `BOOT_LABEL`/`EASYROMS_LABEL` déclenchent
    leur stratégie dédiée (position + système de fichiers, voir
    `_select_boot`/`_select_easyroms`) ; tout autre label retombe sur une
    simple recherche par étiquette. Lève `PartitionNotFound` si rien ne
    correspond."""
    partitions = list_partitions(device_path)

    if label == BOOT_LABEL:
        return _select_boot(partitions, device_path)
    if label == EASYROMS_LABEL:
        return _select_easyroms(partitions, device_path)

    for partition in partitions:
        if partition.label.upper() == label.upper():
            return partition
    raise PartitionNotFound(label, device_path)


def locate_mounted(
    device_path: str,
    label: str,
    timeout: float = MOUNT_WAIT_SECONDS,
    poll_interval: float = MOUNT_POLL_INTERVAL,
) -> PartitionInfo:
    """Attend que la partition `label` apparaisse montée (§4.4 : « attendre
    l'apparition automatique du volume, avec une temporisation et un
    contrôle »). Windows monte seul les partitions après un flash — d'où la
    boucle d'attente plutôt qu'une seule lecture. Sur Linux et macOS, tente
    en plus un montage actif (`udisksctl`/`diskutil mount`, aucun des deux
    ne demandant les droits root pour un périphérique amovible) dès que la
    partition est trouvée non montée : une partition démontée par un flash
    précédent ou un `hdiutil detach` ne remonte jamais toute seule — attendre
    passivement dans ce cas échouerait systématiquement sur
    `PartitionNotMounted` (bug confirmé sur du vrai matériel).

    Lève `PartitionNotFound` si la partition n'existe pas du tout, ou
    `PartitionNotMounted` si le délai est dépassé sans qu'elle soit montée."""
    deadline = time.monotonic() + timeout
    partition = find_partition(device_path, label)

    while partition.mountpoint is None:
        system = platform.system()
        if system == "Linux":
            partition = _mount_linux(partition)
            if partition.mountpoint is not None:
                break
        elif system == "Darwin":
            partition = _mount_macos(partition)
            if partition.mountpoint is not None:
                break
        if time.monotonic() >= deadline:
            raise PartitionNotMounted(label, device_path)
        time.sleep(poll_interval)
        partition = find_partition(device_path, label)

    return partition


# --- macOS -------------------------------------------------------------


def _macos_partition_ids(device_path: str) -> list[str]:
    disk_id = device_path.rsplit("/", 1)[-1]
    result = subprocess.run(
        ["diskutil", "list", "-plist", disk_id], capture_output=True, check=True
    )
    data = plistlib.loads(result.stdout)
    for disk in data.get("AllDisksAndPartitions", []):
        if disk.get("DeviceIdentifier") == disk_id:
            return [p["DeviceIdentifier"] for p in disk.get("Partitions", [])]
    return []


def _macos_info(partition_id: str) -> dict:
    result = subprocess.run(
        ["diskutil", "info", "-plist", partition_id], capture_output=True, check=True
    )
    return plistlib.loads(result.stdout)


def _mount_macos(partition: PartitionInfo) -> PartitionInfo:
    """`diskutil mount` ne demande pas les droits root pour un périphérique
    amovible — symétrique de `_mount_linux` (`udisksctl`). Nécessaire car
    macOS ne remonte jamais tout seul une partition explicitement démontée
    (par un flash précédent, un `hdiutil detach`...) : attendre passivement
    un montage automatique qui n'aura jamais lieu échouerait à coup sûr sur
    `PartitionNotMounted` (bug confirmé sur du vrai matériel). Un échec
    laisse `partition` inchangée sauf repli forcé (`_force_mount_macos`,
    note de module) ; l'appelant (`locate_mounted`) revérifiera à la
    prochaine itération si les deux échouent."""
    result = subprocess.run(
        ["diskutil", "mount", partition.device_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return _force_mount_macos(partition)
    partition_id = partition.device_path.rsplit("/", 1)[-1]
    mountpoint = _macos_info(partition_id).get("MountPoint") or None
    if mountpoint is None:
        return _force_mount_macos(partition)
    return replace(partition, mountpoint=mountpoint)


# Points de montage créés par `_force_mount_macos`, pour qu'`unmount_forced`
# sache lesquels démonter/supprimer lui-même plutôt qu'un montage `diskutil`
# normal (géré par le système jusqu'à l'éjection finale, §4.4).
_FORCED_MOUNTPOINTS: set[str] = set()

# Point d'extension optionnel (note de module) : la GUI y installe un
# repli avec élévation pour le montage forcé, sur macOS uniquement --
# `None` par défaut (CLI, tests, autres OS), auquel cas `_force_mount_macos`
# se contente de l'échec non élevé, comme avant ce point d'extension.
_privileged_mount_hook: Optional[Callable[[str, str], bool]] = None


def set_privileged_mount_hook(hook: Optional[Callable[[str, str], bool]]) -> None:
    """Installe (ou retire, avec `None`) le repli élevé pour le montage
    forcé -- `hook(device_path, mountpoint)` doit monter `device_path` sur
    `mountpoint` avec élévation et retourner si le montage a réussi
    (`gui/main_window.py` l'installe avec `gui/elevate.py::
    run_privileged_mount`, macOS uniquement, note de module)."""
    global _privileged_mount_hook
    _privileged_mount_hook = hook


def _force_mount_macos(partition: PartitionInfo) -> PartitionInfo:
    """Repli quand `diskutil mount` échoue -- confirmé sur du vrai matériel
    pour une première partition GPT de type EFI contenant malgré tout un
    FAT16 valide (note de module) : `diskutil mount` refuse ce type même
    quand le contenu est un FAT parfaitement lisible, mais `mount -t
    msdos` sur un point de montage temporaire y accède, avec élévation
    (confirmé nécessaire sur du vrai matériel -- voir `_privileged_mount_
    hook` ci-dessus). N'est tenté que si le système de fichiers, quand il
    est connu, est un FAT (jamais pour une NTFS/ext4 dont l'échec
    `diskutil` a une autre cause) -- sans quoi la tentative échouerait de
    toute façon, pour rien. Best-effort comme `_mount_macos` : un échec
    laisse `partition` inchangée après avoir nettoyé le point de montage
    temporaire créé."""
    if partition.filesystem and not _is_fat(partition.filesystem):
        return partition
    mountpoint = tempfile.mkdtemp(prefix="r36s-studio-")
    result = subprocess.run(
        ["mount", "-t", "msdos", partition.device_path, mountpoint],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        _FORCED_MOUNTPOINTS.add(mountpoint)
        return replace(partition, mountpoint=mountpoint)
    if _privileged_mount_hook is not None and _privileged_mount_hook(partition.device_path, mountpoint):
        _FORCED_MOUNTPOINTS.add(mountpoint)
        return replace(partition, mountpoint=mountpoint)
    os.rmdir(mountpoint)
    return partition


def unmount_forced(partition: PartitionInfo) -> None:
    """Démonte proprement un montage forcé par `_force_mount_macos` et
    supprime son point de montage temporaire, une fois la partition
    exploitée (copie, identification...) -- ne fait rien pour un montage
    `diskutil`/`udisksctl` normal, qui reste géré par le système jusqu'à
    l'éjection finale (§4.4), comme avant ce correctif. Best-effort : un
    échec de démontage n'empêche jamais l'appelant de continuer (le
    résultat de l'opération précédente, ex. une copie déjà terminée,
    n'est jamais remis en cause par un souci de nettoyage)."""
    mountpoint = partition.mountpoint
    if mountpoint is None or mountpoint not in _FORCED_MOUNTPOINTS:
        return
    subprocess.run(["umount", mountpoint], capture_output=True)
    _FORCED_MOUNTPOINTS.discard(mountpoint)
    try:
        os.rmdir(mountpoint)
    except OSError:
        pass


def _macos_filesystem(info: dict) -> str:
    """Normalise vers le petit vocabulaire canonique de `FAT_FILESYSTEMS`/
    `"ntfs"`, plutôt que de renvoyer tel quel le champ `diskutil` — bug
    confirmé sur du vrai matériel : `FilesystemType` a été observé renvoyer
    `Windows_NTFS` (le nom du type de partition, pas la personnalité de
    montage `ntfs` attendue) pour une vraie partition EASYROMS. Une
    comparaison stricte en aval (`jobs._reject_macos_ntfs_write`, l'exact
    `== "ntfs"`) échouait alors silencieusement, laissant passer une copie
    qui finissait par échouer en plein milieu avec `[Errno 30] Read-only
    file system` au lieu du refus explicite attendu. `FilesystemType` et
    `Content` sont donc cherchés ensemble, insensible à la casse, pour toute
    variante ("ntfs", "NTFS", "Windows_NTFS"...)."""
    combined = " ".join(str(info.get(key) or "") for key in ("FilesystemType", "Content")).lower()
    if "ntfs" in combined:
        return "ntfs"
    if "fat" in combined or "msdos" in combined:
        return "msdos"
    return (info.get("FilesystemType") or "").lower()


def _macos_partition_type(info: dict) -> str:
    """Type de partition (schéma GPT/MBR, ex. "EFI", "Linux Filesystem",
    "Microsoft Basic Data"), distinct du système de fichiers -- `Content`
    est déjà utilisé par `_macos_filesystem` en repli pour deviner le
    système de fichiers, mais garde ici sa valeur brute (normalisée en
    minuscules) pour `_looks_like_efi_boot` (note de module)."""
    return str(info.get("Content") or "").lower()


def _list_macos(device_path: str) -> list[PartitionInfo]:
    partitions = []
    for partition_id in _macos_partition_ids(device_path):
        info = _macos_info(partition_id)
        partitions.append(
            PartitionInfo(
                device_path=f"/dev/{partition_id}",
                label=info.get("VolumeName") or "",
                filesystem=_macos_filesystem(info),
                mountpoint=info.get("MountPoint") or None,
                partition_type=_macos_partition_type(info),
                size_bytes=info.get("Size"),
            )
        )
    return partitions


# --- Linux ---------------------------------------------------------------


def _list_linux(device_path: str) -> list[PartitionInfo]:
    result = subprocess.run(
        ["lsblk", "-J", "-b", "-o", "PATH,LABEL,FSTYPE,MOUNTPOINTS,SIZE", device_path],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    disks = data.get("blockdevices", [])
    children = disks[0].get("children", []) if disks else []

    partitions = []
    for child in children:
        mountpoints = [m for m in (child.get("mountpoints") or []) if m]
        size = child.get("size")
        partitions.append(
            PartitionInfo(
                device_path=child.get("path", ""),
                label=child.get("label") or "",
                filesystem=(child.get("fstype") or "").lower(),
                mountpoint=mountpoints[0] if mountpoints else None,
                # `-b` (octets) déjà demandé ci-dessus, mais certaines
                # versions de lsblk renvoient quand même `size` sous forme
                # de chaîne dans le JSON -- converti explicitement plutôt
                # que de propager un type incohérent selon la version.
                size_bytes=int(size) if size is not None else None,
            )
        )
    return partitions


def _mount_linux(partition: PartitionInfo) -> PartitionInfo:
    """`udisksctl mount` ne demande pas les droits root pour un périphérique
    amovible (§4.4) — contrairement à `mount` directement. Un échec (déjà
    monté entre-temps, permission refusée...) laisse `partition` inchangée ;
    l'appelant (`locate_mounted`) revérifiera à la prochaine itération."""
    result = subprocess.run(
        ["udisksctl", "mount", "-b", partition.device_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return partition
    mountpoint = _parse_udisksctl_mountpoint(result.stdout)
    if mountpoint is None:
        return partition
    return replace(partition, mountpoint=mountpoint)


def _parse_udisksctl_mountpoint(stdout: str) -> Optional[str]:
    # Ex. "Mounted /dev/sdb1 at /media/user/EASYROMS.\n"
    marker = " at "
    idx = stdout.find(marker)
    if idx == -1:
        return None
    return stdout[idx + len(marker) :].strip().rstrip(".")


# --- Windows ---------------------------------------------------------------


def _windows_disk_number(device_path: str) -> str:
    match = re.search(r"PhysicalDrive(\d+)", device_path)
    if not match:
        raise ValueError(f"chemin de périphérique Windows invalide : {device_path}")
    return match.group(1)


def _list_windows(device_path: str) -> list[PartitionInfo]:
    disk_number = _windows_disk_number(device_path)
    # Confirmé sur du vrai matériel (bug rapporté : « Aucune partition de
    # jeux reconnue » pour la sauvegarde système, échec intermittent) :
    # `Get-Partition -DiskNumber N | Sort-Object PartitionNumber | Get-
    # Volume` ne préserve PAS l'ordre du tri en entrée -- `Get-Volume`
    # renvoie ses résultats selon sa propre énumération interne, pas selon
    # l'ordre de son entrée pipeline. Observé en répétant l'appel sur une
    # carte réelle : l'ordre BOOT/EASYROMS alternait d'un appel à l'autre
    # sans aucun changement matériel entre les deux. Comme l'identification
    # de BOOT/EASYROMS par position (voir note de module) et le calcul de
    # `system_backup.py` en dépendent, chaque volume est ici explicitement
    # ré-associé à son `PartitionNumber` d'origine (`Add-Member` dans la
    # boucle, plutôt que de faire confiance à l'ordre du pipeline), et
    # trié une seconde fois côté Python -- qui n'a, lui, aucune raison de
    # réordonner une liste déjà triée.
    # `AccessPaths` (propriété de `Get-Partition`, pas de `Get-Volume`) porte
    # toujours un chemin GUID de volume (`\\?\Volume{...}\`), même quand
    # Windows n'attribue aucune lettre de lecteur -- confirmé lisible sur du
    # vrai matériel (`os.listdir`/`open`, sans élévation) : une partition
    # `BOOT` sans lettre n'est donc *pas* forcément illisible, voir note de
    # module plus bas (repli `mountpoint`).
    command = (
        f"Get-Partition -DiskNumber {disk_number} | Sort-Object PartitionNumber | "
        "ForEach-Object { $p = $_; $vol = $p | Get-Volume -ErrorAction SilentlyContinue; "
        "if ($vol) { $volPath = ($p.AccessPaths | Where-Object { $_.StartsWith('\\\\?\\Volume') } "
        "| Select-Object -First 1); $vol | Add-Member -NotePropertyName PartitionNumber "
        "-NotePropertyValue $p.PartitionNumber -Force; $vol | Add-Member -NotePropertyName "
        "VolumeGuidPath -NotePropertyValue $volPath -PassThru } } | ConvertTo-Json -Depth 3"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
        **no_console_kwargs(),
    )
    volumes = _as_list(json.loads(result.stdout)) if result.stdout.strip() else []
    volumes.sort(key=lambda v: v.get("PartitionNumber") if v.get("PartitionNumber") is not None else 0)

    partitions = []
    for volume in volumes:
        drive_letter = volume.get("DriveLetter")
        # Confirmé sur du vrai matériel : une partition BOOT (FAT32, saine
        # et lisible) peut très bien n'avoir aucune lettre de lecteur --
        # Windows n'en attribue pas spontanément à toute partition d'un
        # disque (notamment une partition cachée/de type non standard sur
        # un disque non explicitement "removable"), ce n'est pas un défaut
        # matériel (§4.4, note de module). Plutôt que d'attendre en vain
        # une lettre qui n'arrivera jamais (`locate_mounted`, aucune
        # tentative de montage actif sur Windows contrairement à Linux/
        # macOS), le chemin GUID du volume (`AccessPaths`, ci-dessus) sert
        # de repli -- lisible sans élévation, sans lettre de lecteur.
        mountpoint = f"{drive_letter}:\\" if drive_letter else (volume.get("VolumeGuidPath") or None)
        size = volume.get("Size")
        # Confirmé sur du vrai matériel : pour une partition dont Windows
        # ne reconnaît pas le système de fichiers (ext4, la partition
        # root Linux d'une carte ArkOS), `Get-Volume` renvoie tout de même
        # un volume "RAW", mais avec `Size: 0` -- pas absent. Une vraie
        # partition de 0 octet n'existe pas sur une carte SD flashée ; `0`
        # ici veut dire « taille inconnue », comme le `None` que ce champ
        # représente déjà pour les OS où l'info manque carrément (§4.3).
        # Sans ce garde-fou, `imaging/system_backup.py::estimate_system_
        # backup_size_unprivileged` sous-comptait silencieusement une
        # carte dont une partition système garder n'est pas montable par
        # Windows, au lieu de retomber sur le repli élevé prévu pour ce cas.
        size_bytes = int(size) if size else None
        partitions.append(
            PartitionInfo(
                device_path=mountpoint or "",
                label=volume.get("FileSystemLabel") or "",
                filesystem=(volume.get("FileSystem") or "").lower(),
                mountpoint=mountpoint,
                size_bytes=size_bytes,
            )
        )
    return partitions


def _as_list(data) -> list[dict]:
    # ConvertTo-Json renvoie un objet nu (pas une liste) pour un seul résultat.
    if isinstance(data, dict):
        return [data]
    return list(data or [])
