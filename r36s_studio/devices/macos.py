"""Détection des périphériques sous macOS, via `diskutil`.

Un lecteur de carte SD intégré (MacBook) est classé "internal" par diskutil :
`diskutil list -plist external physical` ne le retourne donc jamais. On
interroge tous les disques physiques (`physical`, sans le filtre `external`),
puis on détermine l'amovibilité réelle via les champs dédiés de
`diskutil info` plutôt que via `Internal`. On exclut au passage les disk
images (montage d'un `.dmg`), qui ne sont pas de vrais disques."""

from __future__ import annotations

import plistlib
import subprocess

from .base import Device, DeviceProvider


class MacDeviceProvider(DeviceProvider):
    def list_devices(self) -> list[Device]:
        devices = []
        for disk_id in self._list_disk_ids():
            info = self._disk_info(disk_id)
            if info is None or self._is_disk_image(info):
                continue
            devices.append(self._to_device(disk_id, info))
        return devices

    @staticmethod
    def _list_disk_ids() -> list[str]:
        result = subprocess.run(
            ["diskutil", "list", "-plist", "physical"],
            capture_output=True,
            check=True,
        )
        data = plistlib.loads(result.stdout)
        return list(data.get("WholeDisks", []))

    @staticmethod
    def _disk_info(disk_id: str) -> dict | None:
        try:
            result = subprocess.run(
                ["diskutil", "info", "-plist", disk_id],
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            return None
        return plistlib.loads(result.stdout)

    @staticmethod
    def _is_disk_image(info: dict) -> bool:
        """Un fichier .dmg monté (ex. disk2) apparaît dans la liste des
        disques physiques mais n'est pas un vrai disque."""
        if info.get("VirtualOrPhysical") == "Virtual":
            return True
        return (info.get("BusProtocol") or "").strip().lower() == "disk image"

    @staticmethod
    def _resolve_removable(info: dict) -> bool:
        """`Internal` ne dit rien de l'amovibilité réelle (un lecteur de
        carte SD intégré est "internal" mais bien éjectable) : on préfère
        RemovableMediaOrExternalDevice, avec repli sur Removable puis
        Ejectable."""
        for key in ("RemovableMediaOrExternalDevice", "RemovableMedia", "Ejectable"):
            value = info.get(key)
            if value is not None:
                return bool(value)
        return False

    @classmethod
    def _to_device(cls, disk_id: str, info: dict) -> Device:
        mountpoint = info.get("MountPoint") or ""
        removable = cls._resolve_removable(info)
        # Un disque interne non amovible héberge potentiellement le système ;
        # un lecteur de carte SD intégré est "Internal" mais éjectable, donc
        # ne doit pas être traité comme un disque système.
        is_system = mountpoint == "/" or (bool(info.get("Internal")) and not removable)

        return Device(
            path=f"/dev/{disk_id}",
            display=info.get("MediaName") or disk_id,
            size_bytes=int(info.get("TotalSize") or 0),
            removable=removable,
            bus=(info.get("BusProtocol") or "").upper(),
            is_system=is_system,
            mountpoints=[mountpoint] if mountpoint else [],
        )
