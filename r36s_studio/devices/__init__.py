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


def list_devices() -> list[Device]:
    return get_provider().list_devices()


__all__ = ["Device", "DeviceProvider", "get_provider", "list_devices"]
