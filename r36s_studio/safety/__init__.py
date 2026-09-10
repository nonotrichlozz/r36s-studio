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

"""Garde-fou : détermine quels périphériques peuvent être proposés à
l'utilisateur. Un périphérique refusé n'apparaît jamais dans la liste — il ne
suffit pas de le griser (spec §4.2)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from r36s_studio.devices import Device

DEFAULT_MAX_SIZE_BYTES = 1_000_000_000_000  # 1 To


def _default_app_path() -> str:
    """Dossier d'où l'application s'exécute, à exclure de toute cible."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(sys.argv[0]))


@dataclass
class SafetyConfig:
    max_size_bytes: int = DEFAULT_MAX_SIZE_BYTES
    app_path: str = field(default_factory=_default_app_path)


def _contains_app_path(device: Device, app_path: str) -> bool:
    """Vrai si un des points de montage du périphérique est un ancêtre (ou
    l'égal) du dossier de l'application."""
    app_real = os.path.realpath(app_path)
    for mountpoint in device.mountpoints:
        if not mountpoint:
            continue
        mount_real = os.path.realpath(mountpoint)
        try:
            common = os.path.commonpath([app_real, mount_real])
        except ValueError:
            # chemins sur des lecteurs différents (Windows) -> aucun rapport
            continue
        if common == mount_real:
            return True
    return False


def is_allowed(device: Device, config: SafetyConfig | None = None) -> bool:
    """Applique les cinq règles de refus du §4.2. Retourne False dès qu'une
    seule s'applique."""
    return describe_rejection(device, config) is None


def describe_rejection(device: Device, config: SafetyConfig | None = None) -> str | None:
    """Même règles que `is_allowed`, mais avec la raison -- `None` si le
    périphérique est autorisé. Sert à tracer dans le journal de bord
    pourquoi un périphérique n'apparaît pas dans la liste (§5 mode
    assisté) : un écart apparent entre deux écrans de l'appli n'est
    presque jamais un filtre différent (les deux appellent la même
    fonction), plutôt une carte exclue silencieusement -- ce texte, lui,
    est technique par nécessité (destiné au journal, §5 vocabulaire)."""
    config = config or SafetyConfig()

    if device.is_system:
        return "carte système"

    if _contains_app_path(device, config.app_path):
        return "contient le dossier de l'application"

    if not device.removable and device.bus.upper() != "USB":
        return "ni amovible ni en USB"

    if not device.size_bytes or device.size_bytes <= 0:
        return "taille nulle ou inconnue"

    if device.size_bytes > config.max_size_bytes:
        return "dépasse le seuil de taille"

    return None


def filter_devices(devices: list[Device], config: SafetyConfig | None = None) -> list[Device]:
    config = config or SafetyConfig()
    return [d for d in devices if is_allowed(d, config)]


__all__ = ["SafetyConfig", "DEFAULT_MAX_SIZE_BYTES", "is_allowed", "describe_rejection", "filter_devices"]
