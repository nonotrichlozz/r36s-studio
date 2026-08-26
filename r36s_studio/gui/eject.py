"""Éjection de la carte SD après une opération (écran Résultat, §5 point
6), par OS. Best-effort : une erreur ici ne remet jamais en cause le
résultat de l'opération qui vient de se terminer, à l'appelant de
l'afficher sans bloquer le reste de l'écran."""

from __future__ import annotations

import platform
import subprocess


def eject(device_path: str) -> None:
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["diskutil", "eject", device_path], check=True)
    elif system == "Linux":
        subprocess.run(["udisksctl", "power-off", "-b", device_path], check=True)
    elif system == "Windows":
        raise NotImplementedError(
            "Éjection non implémentée sous Windows dans ce squelette : "
            "éjecte la carte manuellement depuis l'Explorateur."
        )
    else:
        raise NotImplementedError(f"Éjection non supportée sur {system}")
