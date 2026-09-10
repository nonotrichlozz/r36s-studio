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

"""Préparation de l'accès en écriture brute à un périphérique, par OS
(§4.3). C'est ici, et seulement ici, qu'un périphérique peut être ouvert en
écriture dans ce module — jamais dans `copy.py` ni `flash.py`."""

from __future__ import annotations

import contextlib
import platform
import re
import subprocess
from typing import Iterator, List

from r36s_studio.devices import Device

from .source import raw_read_path

WINDOWS_SECTOR_SIZE = 512


def _windows_all_volume_paths(device_path: str) -> List[str]:
    """Chemin GUID (`\\\\?\\Volume{...}\\`) de *toutes* les partitions
    montables du disque cible -- lettre de lecteur ou non.

    Bug corrigé, confirmé sur du vrai matériel : `prepared_write_target`
    ne verrouillait/démontait que `device.mountpoints` (`devices/
    windows.py`, uniquement les lettres de lecteur) avant d'ouvrir
    `\\\\.\\PhysicalDriveN` en écriture. Sur une carte ArkOS complète
    (BOOT + root + EASYROMS, seule EASYROMS montée avec une lettre), BOOT
    restait donc monté pendant toute l'écriture brute du disque entier --
    et environ une seconde après le début de l'écriture (celle des
    premiers secteurs, qui appartiennent justement à BOOT), Windows
    détecte que le contenu d'un volume encore monté change sous lui et
    révoque le handle physique en cours d'écriture pour protéger ce
    volume, plutôt que de le laisser continuer : `[Errno 9] Bad file
    descriptor` (`ERROR_INVALID_HANDLE`) côté Python, en toute logique.
    L'ouverture de `\\\\.\\PhysicalDriveN` elle-même a lieu correctement
    *après* `lock_and_dismount_volumes` (jamais avant) -- ce n'est pas
    l'ordre des opérations qui était en cause, mais leur périmètre :
    verrouiller/démonter seulement les volumes lettrés en oublie
    silencieusement ceux qui n'en ont pas.

    `Get-Partition -DiskNumber N` (même disque que `device.path`, requête
    PowerShell distincte de celle de `partitions/locate.py::_list_windows`
    pour ne pas coupler `imaging/` à `partitions/` pour un simple besoin
    d'énumération) expose `AccessPaths` pour chaque partition -- un chemin
    GUID de volume y figure toujours dès qu'un volume existe, même sans
    lettre (confirmé sur du vrai matériel ailleurs dans ce projet, §4.4) ;
    une partition dont Windows ne reconnaît pas le système de fichiers
    (ext4, la partition root d'une carte ArkOS) obtient tout de même un
    volume "RAW" avec son propre chemin GUID -- verrouiller/démonter un
    volume RAW non monté est sans risque (`FSCTL_LOCK_VOLUME` réussit
    trivialement dessus).

    Bug corrigé, confirmé sur du vrai matériel : sur un disque *sans
    aucune partition* (carte vierge, `Clear-Disk` ou équivalent avant un
    premier flash), `Get-Partition -DiskNumber N` ne renvoie pas une liste
    vide -- il lève `ObjectNotFound` et PowerShell sort en code 1, vérifié
    à la main. `check=True` traitait ça comme un échec fatal alors
    qu'« aucune partition à verrouiller » est un résultat parfaitement
    normal avant un flash sur une carte neuve -- même principe que
    `write_target.reunmount_before_verify` sur macOS, qui utilise déjà
    `check=False` pour cette raison exacte (rien à démonter n'est pas une
    erreur). `check=False` ici : un code de retour non nul (disque sans
    partition, ou toute autre erreur PowerShell) retombe sur une liste
    vide plutôt que de lever -- `lock_and_dismount_volumes([])` est déjà
    un no-op sûr (boucle vide)."""
    match = re.search(r"PhysicalDrive(\d+)", device_path)
    if not match:
        raise ValueError(f"chemin de périphérique Windows invalide : {device_path}")
    disk_number = match.group(1)
    command = (
        f"Get-Partition -DiskNumber {disk_number} | "
        "ForEach-Object { $_.AccessPaths } | "
        "Where-Object { $_ -like '\\\\?\\Volume*' }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


@contextlib.contextmanager
def prepared_write_target(device: Device) -> Iterator[str]:
    """Démonte/verrouille `device` selon l'OS courant, puis fournit le
    chemin à ouvrir pour l'écriture brute."""
    system = platform.system()

    if system == "Darwin":
        # Sans démontage préalable, macOS verrouille l'accès brut à
        # /dev/rdiskN tant qu'une partition est montée. Succès jugé
        # uniquement sur le code de retour (`check=True`) : `diskutil`
        # écrit parfois son message de succès sur stderr, jamais un signe
        # d'échec en soi. `capture_output=True` empêche ce message de se
        # mélanger à la sortie du worker (voir `source.py`, même correctif).
        subprocess.run(["diskutil", "unmountDisk", device.path], check=True, capture_output=True)
        yield raw_read_path(device.path)
        return

    if system == "Linux":
        for mountpoint in device.mountpoints:
            subprocess.run(["umount", mountpoint], check=False, capture_output=True)
        yield device.path
        return

    if system == "Windows":
        from . import winlock

        # Toutes les partitions montables du disque, lettre de lecteur ou
        # non -- pas seulement `device.mountpoints` (voir le docstring de
        # `_windows_all_volume_paths` : le bug corrigé qui motive cet appel
        # au lieu du précédent `device.mountpoints`).
        volume_paths = _windows_all_volume_paths(device.path)
        handles = winlock.lock_and_dismount_volumes(volume_paths)
        try:
            yield device.path
        finally:
            winlock.unlock_volumes(handles)
            winlock.refresh_disk_properties(device.path)
        return

    raise NotImplementedError(f"OS non supporté pour l'écriture : {system}")


def reunmount_before_verify(device: Device) -> None:
    """Bug corrigé, constaté sur du vrai matériel : le flash réussissait
    mais la vérification SHA-256 échouait quand même. Cause : l'appel
    `diskutil unmountDisk` fait par `prepared_write_target`, avant
    l'écriture, ne démonte qu'une fois -- rien n'empêche macOS de remonter
    automatiquement les partitions juste après, puisque le disque porte
    maintenant une table de partitions et des systèmes de fichiers valides
    (ce qu'il n'avait pas forcément avant le flash). Une fois montée, la
    partition BOOT (FAT) reçoit aussitôt des fichiers d'index
    (`.Spotlight-V100`, `.fseventsd`...) que macOS écrit à l'ouverture de
    tout volume -- ça modifie des octets qu'on s'apprête à relire pour la
    vérification, entre la fin de l'écriture et cette relecture. À appeler
    juste avant de relire (`flash.py`), pas seulement avant d'écrire.

    `check=False` : rien à démonter (le montage automatique n'a peut-être
    pas encore eu lieu, ou l'écriture ne touchait qu'une image sans
    filesystem reconnu) est un résultat normal ici, pas une erreur -- au
    contraire de l'unmount initial, où un échec signale un vrai problème."""
    if platform.system() == "Darwin":
        subprocess.run(["diskutil", "unmountDisk", device.path], check=False, capture_output=True)
