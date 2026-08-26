"""Tests du provider macOS — reproduit le bug du lecteur de carte SD intégré :
`diskutil` le classe "internal", donc `diskutil list -plist external
physical` ne le retournait jamais. Jeu de données factice, aucun `diskutil`
réel n'est appelé (mock de `subprocess.run`).

Contexte reproduit (machine réelle du rapport de bug) :
- disk0 : disque système interne
- disk2 : disk image montée (pas un vrai disque)
- disk3 : carte SD dans le lecteur intégré (internal, mais éjectable/USB)
- disk4 : disque dur externe USB
"""

from __future__ import annotations

import plistlib
import subprocess
from unittest.mock import patch

from r36s_studio.devices.macos import MacDeviceProvider
from r36s_studio.safety import SafetyConfig, filter_devices

WHOLE_DISKS = ["disk0", "disk2", "disk3", "disk4"]

DISK_INFO = {
    "disk0": {
        "DeviceIdentifier": "disk0",
        "MediaName": "APPLE SSD",
        "TotalSize": 251000193024,
        "Internal": True,
        "Ejectable": False,
        "RemovableMedia": False,
        "RemovableMediaOrExternalDevice": False,
        "VirtualOrPhysical": "Physical",
        "BusProtocol": "PCI-Express",
        "MountPoint": "/",
    },
    "disk2": {
        "DeviceIdentifier": "disk2",
        "MediaName": "Disk Image",
        "TotalSize": 10485760,
        "Internal": False,
        "Ejectable": True,
        "RemovableMedia": True,
        "RemovableMediaOrExternalDevice": True,
        "VirtualOrPhysical": "Virtual",
        "BusProtocol": "Disk Image",
        "MountPoint": "/Volumes/TestImg",
    },
    "disk3": {
        "DeviceIdentifier": "disk3",
        "MediaName": "SD Card Reader",
        "TotalSize": 31914983424,
        "Internal": True,
        "Ejectable": True,
        "RemovableMedia": True,
        "RemovableMediaOrExternalDevice": True,
        "VirtualOrPhysical": "Physical",
        "BusProtocol": "USB",
        "MountPoint": "",
    },
    "disk4": {
        "DeviceIdentifier": "disk4",
        "MediaName": "EXTERNAL_USB",
        "TotalSize": 999_999_999_999,  # ~1 To, sous le seuil par défaut
        "Internal": False,
        "Ejectable": True,
        "RemovableMedia": False,
        "RemovableMediaOrExternalDevice": True,
        "VirtualOrPhysical": "Physical",
        "BusProtocol": "USB",
        "MountPoint": "/Volumes/EXTERNAL_USB",
    },
}


def _fake_run(cmd, **kwargs):
    if cmd[:3] == ["diskutil", "list", "-plist"]:
        payload = {"WholeDisks": WHOLE_DISKS}
    elif cmd[:2] == ["diskutil", "info"]:
        payload = DISK_INFO[cmd[-1]]
    else:
        raise AssertionError(f"commande inattendue : {cmd}")
    return subprocess.CompletedProcess(cmd, 0, stdout=plistlib.dumps(payload), stderr=b"")


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run)
def test_queries_all_physical_disks_not_just_external(mock_run):
    MacDeviceProvider().list_devices()
    list_cmd = mock_run.call_args_list[0].args[0]
    assert list_cmd == ["diskutil", "list", "-plist", "physical"]
    assert "external" not in list_cmd


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run)
def test_internal_sd_card_reader_is_detected_as_removable(mock_run):
    devices = {d.path: d for d in MacDeviceProvider().list_devices()}
    sd_card = devices["/dev/disk3"]
    assert sd_card.removable is True
    assert sd_card.is_system is False
    assert sd_card.bus == "USB"


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run)
def test_mounted_disk_image_is_excluded(mock_run):
    devices = MacDeviceProvider().list_devices()
    assert "/dev/disk2" not in [d.path for d in devices]
    assert len(devices) == 3  # disk0, disk3, disk4 -- disk2 exclu


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run)
def test_internal_system_disk_is_still_flagged_as_system(mock_run):
    devices = {d.path: d for d in MacDeviceProvider().list_devices()}
    assert devices["/dev/disk0"].is_system is True
    assert devices["/dev/disk0"].removable is False


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run)
def test_external_usb_drive_is_detected(mock_run):
    devices = {d.path: d for d in MacDeviceProvider().list_devices()}
    hdd = devices["/dev/disk4"]
    assert hdd.removable is True
    assert hdd.is_system is False
    assert hdd.size_bytes == 999_999_999_999


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run)
def test_safety_filter_keeps_only_sd_card_and_external_drive(mock_run):
    devices = MacDeviceProvider().list_devices()
    config = SafetyConfig(app_path="/nonexistent-app-path")
    safe = filter_devices(devices, config)
    assert sorted(d.path for d in safe) == ["/dev/disk3", "/dev/disk4"]
