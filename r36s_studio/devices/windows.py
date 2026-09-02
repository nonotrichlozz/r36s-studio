"""Détection des périphériques sous Windows, via PowerShell (`Get-Disk` /
`Get-Partition`)."""

from __future__ import annotations

import json
import subprocess

from .base import Device, DeviceProvider


class WindowsDeviceProvider(DeviceProvider):
    def list_devices(self, allow_disk_image: bool = False) -> list[Device]:
        # `allow_disk_image` n'a rien à faire ici : `Get-Disk` ne distingue
        # pas les VHD/VHDX montés des disques physiques, il n'y a donc pas
        # d'exclusion à lever côté Windows (contrairement à macOS/Linux).
        # Le paramètre reste accepté pour respecter l'interface commune de
        # `DeviceProvider`.
        del allow_disk_image
        disks_raw = self._run_powershell("Get-Disk | ConvertTo-Json -Depth 3")
        partitions_raw = self._run_powershell("Get-Partition | ConvertTo-Json -Depth 3")
        drives_raw = self._run_powershell(
            "Get-CimInstance Win32_DiskDrive | Select-Object Index, MediaType | ConvertTo-Json -Depth 3"
        )
        return self._build(disks_raw, partitions_raw, drives_raw)

    @staticmethod
    def _run_powershell(command: str) -> str:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    @classmethod
    def _build(cls, disks_raw: str, partitions_raw: str, drives_raw: str = "") -> list[Device]:
        disks = cls._as_list(json.loads(disks_raw)) if disks_raw.strip() else []
        partitions = cls._as_list(json.loads(partitions_raw)) if partitions_raw.strip() else []
        drives = cls._as_list(json.loads(drives_raw)) if drives_raw.strip() else []
        media_type_by_index = {
            int(d["Index"]): d.get("MediaType") for d in drives if d.get("Index") is not None
        }

        devices = []
        for disk in disks:
            number = disk.get("Number")
            letters = [
                f"{p['DriveLetter']}:\\"
                for p in partitions
                if p.get("DiskNumber") == number and p.get("DriveLetter")
            ]
            media_type = media_type_by_index.get(number) if number is not None else None
            devices.append(cls._to_device(disk, letters, media_type))
        return devices

    @staticmethod
    def _as_list(data) -> list[dict]:
        # ConvertTo-Json renvoie un objet nu (pas une liste) quand il n'y a
        # qu'un seul résultat.
        if isinstance(data, dict):
            return [data]
        return list(data or [])

    @staticmethod
    def _to_device(disk: dict, mountpoints: list[str], media_type: str | None = None) -> Device:
        bus = (disk.get("BusType") or "").upper()
        is_removable = disk.get("IsRemovable")
        if is_removable is None:
            # `Get-Disk.IsRemovable` est absent (pas juste faux) sur certains
            # lecteurs de carte SD intégrés (ex. Realtek PCIE CardReader,
            # `BusType: SCSI`) -- `Win32_DiskDrive.MediaType` distingue
            # correctement ce cas ("Removable Media" contre "Fixed hard disk
            # media" pour un disque système), constaté sur du vrai matériel.
            normalized_media_type = (media_type or "").strip().lower()
            if normalized_media_type == "removable media":
                is_removable = True
            elif normalized_media_type == "fixed hard disk media":
                is_removable = False
        if is_removable is None:
            is_removable = bus == "USB"

        return Device(
            path=r"\\.\PhysicalDrive" + str(disk.get("Number", "")),
            display=disk.get("FriendlyName") or "",
            size_bytes=int(disk.get("Size") or 0),
            removable=bool(is_removable),
            bus=bus,
            is_system=bool(disk.get("IsSystem")) or bool(disk.get("IsBoot")),
            mountpoints=mountpoints,
        )
