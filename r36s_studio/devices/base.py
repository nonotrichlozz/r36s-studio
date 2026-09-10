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
    def list_devices(self, allow_disk_image: bool = False) -> list[Device]:
        """Retourne tous les disques physiques détectés, sans filtrage de
        sécurité (`safety`, appliqué séparément par l'appelant).

        `allow_disk_image` lève, sur les OS qui l'implémentent, la seule
        exclusion des disk images / périphériques loop (une .dmg montée sur
        macOS, un `losetup` sur Linux) — jamais les autres critères de
        sécurité, qui vivent exclusivement dans `safety` et n'ont aucune
        connaissance de ce paramètre. Réservé au mode développement CLI
        (`--allow-disk-image` / `R36S_STUDIO_DEV`, voir `__main__.py`) : la
        GUI ne le passe jamais."""
        raise NotImplementedError
