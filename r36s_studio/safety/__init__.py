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
    config = config or SafetyConfig()

    if device.is_system:
        return False

    if _contains_app_path(device, config.app_path):
        return False

    if not device.removable and device.bus.upper() != "USB":
        return False

    if not device.size_bytes or device.size_bytes <= 0:
        return False

    if device.size_bytes > config.max_size_bytes:
        return False

    return True


def filter_devices(devices: list[Device], config: SafetyConfig | None = None) -> list[Device]:
    config = config or SafetyConfig()
    return [d for d in devices if is_allowed(d, config)]


__all__ = ["SafetyConfig", "DEFAULT_MAX_SIZE_BYTES", "is_allowed", "filter_devices"]
