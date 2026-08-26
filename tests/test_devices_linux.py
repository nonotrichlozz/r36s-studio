"""Tests du provider Linux (devices/linux.py), notamment le mode
développement (`allow_disk_image`) : un périphérique loop (`losetup`,
utilisé pour tester sans carte SD réelle) a le type "loop" sous `lsblk`,
pas "disk" — exclu par défaut comme une disk image macOS. `lsblk` réel
n'est jamais appelé (mock de `subprocess.run`)."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

from r36s_studio.devices.linux import LinuxDeviceProvider
from r36s_studio.safety import SafetyConfig, filter_devices

LSBLK_OUTPUT = json.dumps(
    {
        "blockdevices": [
            {
                "path": "/dev/fake-disk-test-sda",
                "size": 500_000_000_000,
                "model": "SSD",
                "vendor": "Samsung",
                "rm": False,
                "hotplug": False,
                "tran": "sata",
                "type": "disk",
                "mountpoints": ["/"],
            },
            {
                "path": "/dev/fake-disk-test-sdb",
                "size": 31_914_983_424,
                "model": "Ultra",
                "vendor": "SanDisk",
                "rm": True,
                "hotplug": True,
                "tran": "usb",
                "type": "disk",
                "mountpoints": [None],
            },
            {
                "path": "/dev/fake-loop-test-0",
                "size": 123_456_789,
                "model": "",
                "vendor": "",
                "rm": True,  # losetup factice : configuré "removable" pour passer `safety`
                "hotplug": False,
                "tran": None,
                "type": "loop",
                "mountpoints": [None],
            },
        ]
    }
)


def _fake_run(cmd, **kwargs):
    return subprocess.CompletedProcess(cmd, 0, stdout=LSBLK_OUTPUT, stderr="")


@patch("r36s_studio.devices.linux.subprocess.run", side_effect=_fake_run)
def test_loop_device_excluded_by_default(mock_run):
    devices = LinuxDeviceProvider().list_devices()
    assert "/dev/fake-loop-test-0" not in [d.path for d in devices]
    assert sorted(d.path for d in devices) == ["/dev/fake-disk-test-sda", "/dev/fake-disk-test-sdb"]


@patch("r36s_studio.devices.linux.subprocess.run", side_effect=_fake_run)
def test_loop_device_excluded_when_allow_disk_image_explicitly_false(mock_run):
    devices = LinuxDeviceProvider().list_devices(allow_disk_image=False)
    assert "/dev/fake-loop-test-0" not in [d.path for d in devices]


@patch("r36s_studio.devices.linux.subprocess.run", side_effect=_fake_run)
def test_allow_disk_image_includes_loop_device(mock_run):
    devices = LinuxDeviceProvider().list_devices(allow_disk_image=True)
    assert "/dev/fake-loop-test-0" in [d.path for d in devices]
    assert sorted(d.path for d in devices) == [
        "/dev/fake-disk-test-sda",
        "/dev/fake-disk-test-sdb",
        "/dev/fake-loop-test-0",
    ]


@patch("r36s_studio.devices.linux.subprocess.run", side_effect=_fake_run)
def test_allow_disk_image_does_not_relax_other_safety_rules(mock_run):
    devices = LinuxDeviceProvider().list_devices(allow_disk_image=True)
    config = SafetyConfig(app_path="/nonexistent-app-path")
    safe = {d.path for d in filter_devices(devices, config)}
    assert "/dev/fake-disk-test-sda" not in safe  # disque système (monté sur /) : toujours refusé
    assert "/dev/fake-loop-test-0" in safe  # loop : maintenant visible et sûr
