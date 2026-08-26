"""Éjection de la carte SD (étape F du workflow à deux cartes, §4.4/§4.5) :
démonte toutes les partitions du périphérique et l'éjecte, par OS. La
confirmation explicite que la carte peut être retirée physiquement (§4.5)
est de la responsabilité de l'appelant (CLI/GUI) — cette fonction se
contente de réussir ou de lever, sans afficher quoi que ce soit elle-même.

Best-effort : une erreur ici ne remet jamais en cause le résultat d'une
opération précédente (backup/flash/...) — à l'appelant de l'afficher sans
bloquer le reste de l'écran quand elle est déclenchée depuis l'écran
Résultat plutôt que comme étape F à part entière."""

from __future__ import annotations

import platform
import subprocess


def eject(device_path: str) -> None:
    """Démonte `device_path` (toutes ses partitions, pas juste une) puis
    l'éjecte. Lève en cas d'échec ; ne retourne rien de particulier en cas
    de succès — c'est l'absence d'exception qui vaut confirmation."""
    system = platform.system()
    if system == "Darwin":
        # `diskutil eject` démonte d'abord tous les volumes du disque
        # (équivalent à `unmountDisk`) avant l'éjection matérielle.
        subprocess.run(["diskutil", "eject", device_path], check=True)
    elif system == "Linux":
        # `power-off` démonte toutes les partitions montées du périphérique
        # puis coupe l'alimentation du bus -- la carte peut être retirée.
        subprocess.run(["udisksctl", "power-off", "-b", device_path], check=True)
    elif system == "Windows":
        raise NotImplementedError(
            "Éjection non implémentée sous Windows dans ce squelette : "
            "éjecte la carte manuellement depuis l'Explorateur."
        )
    else:
        raise NotImplementedError(f"Éjection non supportée sur {system}")


__all__ = ["eject"]
