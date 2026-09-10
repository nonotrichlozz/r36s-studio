"""Tests du provider Windows (devices/windows.py).

Cas réel rapporté : un lecteur de carte SD intégré (Realtek PCIE
CardReader) n'apparaît jamais dans `Get-Disk` avec `IsRemovable` renseigné
(la propriété est absente, pas fausse) et son `BusType` est `SCSI`, pas
`USB` -- le filtre `safety` (ni amovible ni en USB) le rejetait donc à
tort. `Win32_DiskDrive.MediaType` ("Removable Media" contre "Fixed hard
disk media") sert de repli, croisé par index de disque. `powershell` réel
n'est jamais appelé (mock de `subprocess.run`)."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

from r36s_studio.devices.windows import WindowsDeviceProvider
from r36s_studio.safety import SafetyConfig, filter_devices

DISKS = [
    {
        "Number": 0,
        "FriendlyName": "NVMe SSD",
        "Size": 512_000_000_000,
        "BusType": "NVMe",
        "IsSystem": True,
        "IsBoot": True,
        "IsRemovable": None,
    },
    {
        "Number": 1,
        "FriendlyName": "Realtek PCIE CardReader",
        "Size": 128_000_000_000,
        "BusType": "SCSI",
        "IsSystem": False,
        "IsBoot": False,
        "IsRemovable": None,
    },
    {
        "Number": 2,
        "FriendlyName": "SanDisk Ultra",
        "Size": 32_000_000_000,
        "BusType": "USB",
        "IsSystem": False,
        "IsBoot": False,
        "IsRemovable": True,
    },
]

PARTITIONS = [
    {"DiskNumber": 0, "DriveLetter": "C"},
    {"DiskNumber": 1, "DriveLetter": "E"},
    {"DiskNumber": 2, "DriveLetter": "F"},
]

DRIVES = [
    {"Index": 0, "MediaType": "Fixed hard disk media"},
    {"Index": 1, "MediaType": "Removable Media"},
    {"Index": 2, "MediaType": "Removable Media"},
]

# Une seule invocation PowerShell désormais (`_LIST_DEVICES_COMMAND`) --
# renvoie les trois jeux de données combinés dans un unique objet JSON,
# quel que soit le contenu exact de la commande.
COMBINED = json.dumps({"Disks": DISKS, "Partitions": PARTITIONS, "Drives": DRIVES})


def _fake_run(cmd, **kwargs):
    return subprocess.CompletedProcess(cmd, 0, stdout=COMBINED, stderr="")


@patch("r36s_studio.devices.windows.subprocess.run", side_effect=_fake_run)
def test_sd_card_reader_without_is_removable_is_detected_via_media_type(mock_run):
    devices = {d.display: d for d in WindowsDeviceProvider().list_devices()}
    reader = devices["Realtek PCIE CardReader"]
    assert reader.removable is True
    assert reader.bus == "SCSI"


@patch("r36s_studio.devices.windows.subprocess.run", side_effect=_fake_run)
def test_list_devices_makes_a_single_powershell_call(mock_run):
    # Sondage automatique du parcours de clonage (§5, toutes les 1,5 s) --
    # trois appels PowerShell séquentiels par cycle suffisaient à dépasser
    # le seuil du chien de garde sur le binaire empaqueté (chaque
    # lancement de powershell.exe coûte plusieurs centaines de ms). Une
    # seule invocation combinée (`_LIST_DEVICES_COMMAND`) plutôt que trois.
    WindowsDeviceProvider().list_devices()
    assert mock_run.call_count == 1


@patch("r36s_studio.devices.windows.subprocess.run", side_effect=_fake_run)
def test_system_disk_without_is_removable_stays_non_removable(mock_run):
    devices = {d.display: d for d in WindowsDeviceProvider().list_devices()}
    system_disk = devices["NVMe SSD"]
    assert system_disk.removable is False


@patch("r36s_studio.devices.windows.subprocess.run", side_effect=_fake_run)
def test_sd_card_reader_passes_safety_filter(mock_run):
    devices = WindowsDeviceProvider().list_devices()
    config = SafetyConfig(app_path="C:\\nonexistent-app-path")
    safe_displays = {d.display for d in filter_devices(devices, config)}
    assert "Realtek PCIE CardReader" in safe_displays
    assert "SanDisk Ultra" in safe_displays
    assert "NVMe SSD" not in safe_displays  # disque système : toujours refusé


@patch("r36s_studio.devices.windows.subprocess.run", side_effect=_fake_run)
def test_normal_usb_drive_with_is_removable_true_still_works(mock_run):
    devices = {d.display: d for d in WindowsDeviceProvider().list_devices()}
    usb = devices["SanDisk Ultra"]
    assert usb.removable is True
    assert usb.bus == "USB"


def test_missing_media_type_falls_back_to_usb_bus():
    # `Win32_DiskDrive` absent/vide (ex. requête échouée) : repli sur le
    # comportement d'origine (bus USB) plutôt que de planter.
    disk = {
        "Number": 5,
        "FriendlyName": "Clé USB",
        "Size": 8_000_000_000,
        "BusType": "USB",
        "IsSystem": False,
        "IsBoot": False,
        "IsRemovable": None,
    }
    device = WindowsDeviceProvider._to_device(disk, mountpoints=[], media_type=None)
    assert device.removable is True
