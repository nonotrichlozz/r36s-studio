"""Préparation de l'accès en écriture brute à un périphérique, par OS
(§4.3). C'est ici, et seulement ici, qu'un périphérique peut être ouvert en
écriture dans ce module — jamais dans `copy.py` ni `flash.py`."""

from __future__ import annotations

import contextlib
import platform
import subprocess
from typing import Iterator

from r36s_studio.devices import Device

from .source import raw_read_path

WINDOWS_SECTOR_SIZE = 512


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

        handles = winlock.lock_and_dismount_volumes(device.mountpoints)
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
