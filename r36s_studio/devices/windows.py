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

"""Détection des périphériques sous Windows, via PowerShell (`Get-Disk` /
`Get-Partition`)."""

from __future__ import annotations

import json
import subprocess

from .base import Device, DeviceProvider


_LIST_DEVICES_COMMAND = (
    "$disks = Get-Disk; "
    "$partitions = Get-Partition; "
    "$drives = Get-CimInstance Win32_DiskDrive | Select-Object Index, MediaType; "
    "@{ Disks = $disks; Partitions = $partitions; Drives = $drives } | ConvertTo-Json -Depth 3"
)


class WindowsDeviceProvider(DeviceProvider):
    def list_devices(self, allow_disk_image: bool = False) -> list[Device]:
        # `allow_disk_image` n'a rien à faire ici : `Get-Disk` ne distingue
        # pas les VHD/VHDX montés des disques physiques, il n'y a donc pas
        # d'exclusion à lever côté Windows (contrairement à macOS/Linux).
        # Le paramètre reste accepté pour respecter l'interface commune de
        # `DeviceProvider`.
        del allow_disk_image
        # Une seule invocation PowerShell pour les trois requêtes (plutôt que
        # trois `subprocess.run` séquentiels) -- chaque lancement de
        # `powershell.exe` coûte plusieurs centaines de millisecondes à
        # plus d'une seconde (démarrage à froid, antivirus qui scrute
        # chaque nouveau processus, plus sensible sur un binaire empaqueté
        # fraîchement construit) ; multiplié par trois à chaque sondage
        # automatique du parcours de clonage (§5, toutes les 1,5 s), ça
        # suffit à dépasser le seuil du chien de garde (`_wizard_poll_timer`,
        # `gui/main_window.py`) à quasiment chaque cycle -- constaté en usage
        # réel sur le binaire empaqueté (le sondage semble "ne rien
        # détecter" alors qu'il tourne, simplement trop lentement).
        combined_raw = self._run_powershell(_LIST_DEVICES_COMMAND)
        combined = json.loads(combined_raw) if combined_raw.strip() else {}
        return self._build(combined.get("Disks"), combined.get("Partitions"), combined.get("Drives"))

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
    def _build(cls, disks_raw, partitions_raw, drives_raw=None) -> list[Device]:
        disks = cls._as_list(disks_raw)
        partitions = cls._as_list(partitions_raw)
        drives = cls._as_list(drives_raw)
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
