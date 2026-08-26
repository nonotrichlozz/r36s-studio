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
import plistlib
import platform
import re
import subprocess
import time
from dataclasses import dataclass, replace
from typing import Optional

BOOT_LABEL = "BOOT"
EASYROMS_LABEL = "EASYROMS"

# "msdos" (macOS), "vfat" (Linux), "fat16"/"fat32"/"fat" (Windows, générique) :
# toutes les graphies de FAT rencontrées selon l'OS.
FAT_FILESYSTEMS = {"msdos", "vfat", "fat", "fat16", "fat32"}
EASYROMS_FALLBACK_FILESYSTEMS = FAT_FILESYSTEMS | {"ntfs"}

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
    if partitions and _is_fat(partitions[BOOT_PARTITION_INDEX].filesystem):
        return partitions[BOOT_PARTITION_INDEX]
    for partition in partitions:
        if partition.label.upper() == BOOT_LABEL:
            return partition
    raise PartitionNotFound(BOOT_LABEL, device_path)


def _select_easyroms(partitions: list[PartitionInfo], device_path: str) -> PartitionInfo:
    """Étiquette d'abord (EASYROMS est bien nommée en pratique) ; repli sur
    la position (troisième partition) et le système de fichiers (NTFS ou
    FAT) si l'étiquette est absente."""
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
    laisse `partition` inchangée ; l'appelant (`locate_mounted`)
    revérifiera à la prochaine itération."""
    result = subprocess.run(
        ["diskutil", "mount", partition.device_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return partition
    partition_id = partition.device_path.rsplit("/", 1)[-1]
    mountpoint = _macos_info(partition_id).get("MountPoint") or None
    if mountpoint is None:
        return partition
    return replace(partition, mountpoint=mountpoint)


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
            )
        )
    return partitions


# --- Linux ---------------------------------------------------------------


def _list_linux(device_path: str) -> list[PartitionInfo]:
    result = subprocess.run(
        ["lsblk", "-J", "-b", "-o", "PATH,LABEL,FSTYPE,MOUNTPOINTS", device_path],
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
        partitions.append(
            PartitionInfo(
                device_path=child.get("path", ""),
                label=child.get("label") or "",
                filesystem=(child.get("fstype") or "").lower(),
                mountpoint=mountpoints[0] if mountpoints else None,
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
    # Trié explicitement par PartitionNumber : l'identification de BOOT/
    # EASYROMS par position en dépend (voir note de module).
    command = (
        f"Get-Partition -DiskNumber {disk_number} | Sort-Object PartitionNumber | "
        "Get-Volume | ConvertTo-Json -Depth 3"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=True,
    )
    volumes = _as_list(json.loads(result.stdout)) if result.stdout.strip() else []

    partitions = []
    for volume in volumes:
        drive_letter = volume.get("DriveLetter")
        mountpoint = f"{drive_letter}:\\" if drive_letter else None
        partitions.append(
            PartitionInfo(
                device_path=mountpoint or "",
                label=volume.get("FileSystemLabel") or "",
                filesystem=(volume.get("FileSystem") or "").lower(),
                mountpoint=mountpoint,
            )
        )
    return partitions


def _as_list(data) -> list[dict]:
    # ConvertTo-Json renvoie un objet nu (pas une liste) pour un seul résultat.
    if isinstance(data, dict):
        return [data]
    return list(data or [])
