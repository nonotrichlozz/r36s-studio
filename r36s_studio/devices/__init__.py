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

"""Détection des périphériques de stockage — interface commune, une
implémentation par OS derrière `get_provider()` / `list_devices()`."""

from __future__ import annotations

import platform

from .base import Device, DeviceProvider


def get_provider() -> DeviceProvider:
    system = platform.system()
    if system == "Linux":
        from .linux import LinuxDeviceProvider

        return LinuxDeviceProvider()
    if system == "Darwin":
        from .macos import MacDeviceProvider

        return MacDeviceProvider()
    if system == "Windows":
        from .windows import WindowsDeviceProvider

        return WindowsDeviceProvider()
    raise NotImplementedError(f"OS non supporté : {system}")


def list_devices(allow_disk_image: bool = False) -> list[Device]:
    return get_provider().list_devices(allow_disk_image=allow_disk_image)


__all__ = ["Device", "DeviceProvider", "get_provider", "list_devices"]
