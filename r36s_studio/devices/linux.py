# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Détection des périphériques sous Linux, via `lsblk`."""

from __future__ import annotations

import json
import subprocess

from .base import Device, DeviceProvider

LSBLK_COLUMNS = "PATH,SIZE,MODEL,VENDOR,RM,HOTPLUG,TRAN,TYPE,MOUNTPOINTS"
SYSTEM_MOUNTPOINTS = {"/", "/boot", "/boot/efi"}


class LinuxDeviceProvider(DeviceProvider):
    def list_devices(self, allow_disk_image: bool = False) -> list[Device]:
        raw = self._run_lsblk()
        return self._parse(raw, allow_disk_image=allow_disk_image)

    @staticmethod
    def _run_lsblk() -> str:
        result = subprocess.run(
            ["lsblk", "-J", "-b", "-o", LSBLK_COLUMNS],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    @classmethod
    def _parse(cls, raw_json: str, allow_disk_image: bool = False) -> list[Device]:
        # Un `losetup` (image montée en loop, utilisé pour tester sans carte
        # SD réelle) apparaît avec type "loop", pas "disk" -- exclu par
        # défaut comme les disk images macOS, autorisé en mode développement.
        allowed_types = {"disk", "loop"} if allow_disk_image else {"disk"}
        data = json.loads(raw_json)
        devices = []
        for entry in data.get("blockdevices", []):
            if entry.get("type") not in allowed_types:
                continue
            devices.append(cls._to_device(entry))
        return devices

    @classmethod
    def _to_device(cls, entry: dict) -> Device:
        mountpoints = [m for m in cls._collect_mountpoints(entry) if m]
        model = (entry.get("model") or "").strip()
        vendor = (entry.get("vendor") or "").strip()
        display = " ".join(part for part in (vendor, model) if part) or entry.get("path", "")

        return Device(
            path=entry.get("path", ""),
            display=display,
            size_bytes=int(entry.get("size") or 0),
            removable=bool(entry.get("rm")) or bool(entry.get("hotplug")),
            bus=(entry.get("tran") or "").upper(),
            is_system=any(mp in SYSTEM_MOUNTPOINTS for mp in mountpoints),
            mountpoints=mountpoints,
        )

    @classmethod
    def _collect_mountpoints(cls, entry: dict) -> list[str]:
        """lsblk expose `mountpoints` (liste) sur les versions récentes et
        `mountpoint` (chaîne) sur les anciennes ; on gère les deux, en
        descendant récursivement dans les partitions enfants."""
        mountpoints: list[str] = []
        raw = entry.get("mountpoints")
        if raw is None:
            raw = entry.get("mountpoint")
        if isinstance(raw, list):
            mountpoints.extend(m for m in raw if m)
        elif raw:
            mountpoints.append(raw)
        for child in entry.get("children") or []:
            mountpoints.extend(cls._collect_mountpoints(child))
        return mountpoints
