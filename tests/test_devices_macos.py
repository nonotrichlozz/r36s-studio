"""Tests du provider macOS — reproduit le bug du lecteur de carte SD intégré :
`diskutil` le classe "internal", donc `diskutil list -plist external
physical` ne le retournait jamais. Jeu de données factice, aucun `diskutil`
réel n'est appelé (mock de `subprocess.run`).

Contexte reproduit (machine réelle du rapport de bug) :
- fake-disk-test-0 : disque système interne
- fake-disk-test-2 : disk image montée (pas un vrai disque)
- fake-disk-test-3 : carte SD dans le lecteur intégré (internal, mais éjectable/USB)
- fake-disk-test-4 : disque dur externe USB
"""

from __future__ import annotations

import plistlib
import subprocess
from unittest.mock import patch

from r36s_studio.devices.macos import MacDeviceProvider
from r36s_studio.safety import SafetyConfig, filter_devices

WHOLE_DISKS = ["fake-disk-test-0", "fake-disk-test-2", "fake-disk-test-3", "fake-disk-test-4"]

DISK_INFO = {
    "fake-disk-test-0": {
        "DeviceIdentifier": "fake-disk-test-0",
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
    "fake-disk-test-2": {
        "DeviceIdentifier": "fake-disk-test-2",
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
    "fake-disk-test-3": {
        "DeviceIdentifier": "fake-disk-test-3",
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
    "fake-disk-test-4": {
        "DeviceIdentifier": "fake-disk-test-4",
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
    sd_card = devices["/dev/fake-disk-test-3"]
    assert sd_card.removable is True
    assert sd_card.is_system is False
    assert sd_card.bus == "USB"


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run)
def test_mounted_disk_image_is_excluded(mock_run):
    devices = MacDeviceProvider().list_devices()
    assert "/dev/fake-disk-test-2" not in [d.path for d in devices]
    assert len(devices) == 3  # fake-disk-test-0, fake-disk-test-3, fake-disk-test-4 -- fake-disk-test-2 exclu


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run)
def test_internal_system_disk_is_still_flagged_as_system(mock_run):
    devices = {d.path: d for d in MacDeviceProvider().list_devices()}
    assert devices["/dev/fake-disk-test-0"].is_system is True
    assert devices["/dev/fake-disk-test-0"].removable is False


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run)
def test_external_usb_drive_is_detected(mock_run):
    devices = {d.path: d for d in MacDeviceProvider().list_devices()}
    hdd = devices["/dev/fake-disk-test-4"]
    assert hdd.removable is True
    assert hdd.is_system is False
    assert hdd.size_bytes == 999_999_999_999


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run)
def test_safety_filter_keeps_only_sd_card_and_external_drive(mock_run):
    devices = MacDeviceProvider().list_devices()
    config = SafetyConfig(app_path="/nonexistent-app-path")
    safe = filter_devices(devices, config)
    assert sorted(d.path for d in safe) == ["/dev/fake-disk-test-3", "/dev/fake-disk-test-4"]


# --- mode développement (--allow-disk-image / R36S_STUDIO_DEV) -------------


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run)
def test_disk_image_still_excluded_when_allow_disk_image_not_passed(mock_run):
    """Comportement par défaut inchangé : `allow_disk_image` a une valeur
    par défaut (False) qui ne doit rien changer par rapport à avant son
    introduction."""
    devices = MacDeviceProvider().list_devices(allow_disk_image=False)
    assert "/dev/fake-disk-test-2" not in [d.path for d in devices]


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run)
def test_allow_disk_image_includes_mounted_disk_image(mock_run):
    devices = MacDeviceProvider().list_devices(allow_disk_image=True)
    assert "/dev/fake-disk-test-2" in [d.path for d in devices]
    assert len(devices) == 4  # les 3 précédents + la disk image


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run)
def test_allow_disk_image_does_not_relax_other_safety_rules(mock_run):
    """Le mode développement ne doit lever QUE l'exclusion des disk images
    côté `devices/` — les règles de `safety` (disque système, taille,
    bus...) ne le voient même pas et restent donc pleinement appliquées."""
    devices = MacDeviceProvider().list_devices(allow_disk_image=True)
    config = SafetyConfig(app_path="/nonexistent-app-path")
    safe = {d.path for d in filter_devices(devices, config)}
    assert "/dev/fake-disk-test-0" not in safe  # disque système : toujours refusé
    assert "/dev/fake-disk-test-2" in safe  # disk image : maintenant visible et sûre


# --- bug rapporté : `physical` exclut l'image de l'énumération elle-même --
#
# `_fake_run` ci-dessus ne distingue pas `diskutil list -plist physical` de
# `diskutil list -plist` : il renvoie systématiquement les mêmes
# `WHOLE_DISKS`, quel que soit le filtre. C'est exactement ce qui a caché le
# bug -- les tests ci-dessus passaient déjà avant le correctif de
# `_list_disk_ids`, sans jamais exercer la vraie différence entre les deux
# commandes. Les fixtures ci-dessous reproduisent fidèlement le rapport :
# une image montée via `hdiutil attach -imagekey diskimage-class=
# CRawDiskImage -nomount` n'apparaît PAS dans `diskutil list -plist
# physical` (elle est virtuelle), seulement dans `diskutil list -plist` sans
# filtre.

HDIUTIL_IMAGE_ID = "fake-disk-test-5"

# Valeurs exactes rapportées par `diskutil info -plist` sur la machine réelle.
HDIUTIL_IMAGE_INFO = {
    "DeviceIdentifier": HDIUTIL_IMAGE_ID,
    "MediaName": "Disk Image",
    "TotalSize": 31914983424,
    "Internal": False,
    "Ejectable": True,
    "RemovableMedia": True,
    "RemovableMediaOrExternalDevice": True,
    "VirtualOrPhysical": "Virtual",
    "BusProtocol": "Disk Image",
    "MountPoint": "",
}


def _fake_run_with_hdiutil_image(cmd, **kwargs):
    if cmd == ["diskutil", "list", "-plist", "physical"]:
        payload = {"WholeDisks": list(WHOLE_DISKS)}  # l'image virtuelle n'y est jamais
    elif cmd == ["diskutil", "list", "-plist"]:
        payload = {"WholeDisks": list(WHOLE_DISKS) + [HDIUTIL_IMAGE_ID]}
    elif cmd[:2] == ["diskutil", "info"] and cmd[-1] == HDIUTIL_IMAGE_ID:
        payload = HDIUTIL_IMAGE_INFO
    elif cmd[:2] == ["diskutil", "info"]:
        payload = DISK_INFO[cmd[-1]]
    else:
        raise AssertionError(f"commande inattendue : {cmd}")
    return subprocess.CompletedProcess(cmd, 0, stdout=plistlib.dumps(payload), stderr=b"")


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run_with_hdiutil_image)
def test_hdiutil_raw_disk_image_absent_by_default_even_before_is_disk_image_check(mock_run):
    """Sans mode développement, l'image reste exclue -- et pour la bonne
    raison : elle n'est même jamais énumérée par `diskutil list -plist
    physical` (pas seulement écartée ensuite par `_is_disk_image`)."""
    devices = MacDeviceProvider().list_devices()
    assert f"/dev/{HDIUTIL_IMAGE_ID}" not in [d.path for d in devices]

    list_cmd = mock_run.call_args_list[0].args[0]
    assert list_cmd == ["diskutil", "list", "-plist", "physical"]


@patch("r36s_studio.devices.macos.subprocess.run", side_effect=_fake_run_with_hdiutil_image)
def test_allow_disk_image_widens_enumeration_so_hdiutil_image_appears(mock_run):
    """Le correctif : `allow_disk_image=True` retire aussi le filtre
    `physical` de l'énumération, pas seulement l'exclusion en aval -- sans
    quoi l'image n'atteint jamais `_is_disk_image()` pour que
    `allow_disk_image` ait quoi que ce soit à lever."""
    devices = MacDeviceProvider().list_devices(allow_disk_image=True)
    assert f"/dev/{HDIUTIL_IMAGE_ID}" in [d.path for d in devices]

    list_cmd = mock_run.call_args_list[0].args[0]
    assert list_cmd == ["diskutil", "list", "-plist"]
    assert "physical" not in list_cmd
