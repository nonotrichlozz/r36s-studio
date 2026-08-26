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
