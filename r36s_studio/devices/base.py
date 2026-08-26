"""Interface commune de détection des périphériques.

Une implémentation par OS (`linux.py`, `macos.py`, `windows.py`) doit produire
une liste de `Device` à partir de cette même interface, pour que le reste de
l'application (et les tests) ne dépendent jamais du système d'exploitation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Device:
    path: str          # \\.\PhysicalDrive2 | /dev/disk4 | /dev/sdb
    display: str        # "SanDisk Ultra 128 Go"
    size_bytes: int
    removable: bool
    bus: str            # "USB", "SD", "NVMe"...
    is_system: bool      # contient l'OS en cours ?
    mountpoints: list[str] = field(default_factory=list)


class DeviceProvider(ABC):
    """Détecte les périphériques de stockage présents sur la machine."""

    @abstractmethod
    def list_devices(self) -> list[Device]:
        """Retourne tous les disques physiques détectés, sans filtrage."""
        raise NotImplementedError
