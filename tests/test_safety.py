"""Tests du module `safety`, avec des `Device` entièrement factices — aucun
disque réel n'est touché."""

from __future__ import annotations

import pytest

from r36s_studio.devices import Device
from r36s_studio.safety import SafetyConfig, describe_rejection, filter_devices, is_allowed


def make_device(**overrides) -> Device:
    base = dict(
        path="/dev/fake-disk-test-sdb",
        display="Carte SD factice 32 Go",
        size_bytes=32_000_000_000,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=["/media/sdcard"],
    )
    base.update(overrides)
    return Device(**base)


@pytest.fixture
def config(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    return SafetyConfig(max_size_bytes=1_000_000_000_000, app_path=str(app_dir))


# --- cas nominal ---------------------------------------------------------

def test_valid_sd_card_is_allowed(config):
    assert is_allowed(make_device(), config) is True


# --- règle : disque système ------------------------------------------------

def test_system_disk_is_rejected(config):
    device = make_device(is_system=True, mountpoints=["/"])
    assert is_allowed(device, config) is False


# --- règle : contient le dossier de l'application --------------------------

def test_disk_containing_app_folder_is_rejected(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    config = SafetyConfig(app_path=str(app_dir))
    device = make_device(mountpoints=[str(tmp_path)])
    assert is_allowed(device, config) is False


def test_disk_not_containing_app_folder_is_allowed(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    config = SafetyConfig(app_path=str(app_dir))
    device = make_device(mountpoints=[str(unrelated)])
    assert is_allowed(device, config) is True


# --- règle : non amovible et pas en USB ------------------------------------

def test_non_removable_non_usb_is_rejected(config):
    device = make_device(removable=False, bus="SATA")
    assert is_allowed(device, config) is False


def test_non_removable_but_usb_is_allowed(config):
    device = make_device(removable=False, bus="USB")
    assert is_allowed(device, config) is True


def test_removable_non_usb_is_allowed(config):
    device = make_device(removable=True, bus="SD")
    assert is_allowed(device, config) is True


# --- règle : taille nulle ou inconnue --------------------------------------

def test_zero_size_is_rejected(config):
    assert is_allowed(make_device(size_bytes=0), config) is False


def test_unknown_size_is_rejected(config):
    assert is_allowed(make_device(size_bytes=None), config) is False


# --- règle : taille au-delà du seuil ---------------------------------------

def test_oversized_disk_is_rejected(config):
    device = make_device(size_bytes=config.max_size_bytes + 1)
    assert is_allowed(device, config) is False


def test_size_exactly_at_threshold_is_allowed(config):
    device = make_device(size_bytes=config.max_size_bytes)
    assert is_allowed(device, config) is True


def test_custom_threshold_is_respected():
    config = SafetyConfig(max_size_bytes=64_000_000_000, app_path="/nonexistent-app-path")
    small = make_device(size_bytes=32_000_000_000)
    large = make_device(size_bytes=128_000_000_000)
    assert is_allowed(small, config) is True
    assert is_allowed(large, config) is False


# --- filter_devices : liste complète ---------------------------------------

def test_filter_devices_keeps_only_safe_ones(config):
    devices = [
        make_device(path="/dev/fake-disk-test-sdb"),
        make_device(path="/dev/fake-disk-test-sda", is_system=True, mountpoints=["/"]),
        make_device(path="/dev/fake-disk-test-sdc", size_bytes=0),
        make_device(path="/dev/fake-disk-test-sdd", removable=False, bus="SATA"),
        make_device(path="/dev/fake-disk-test-sde", size_bytes=2_000_000_000_000),
    ]
    result = filter_devices(devices, config)
    assert [d.path for d in result] == ["/dev/fake-disk-test-sdb"]


def test_filter_devices_preserves_order(config):
    devices = [make_device(path="/dev/fake-disk-test-sdb"), make_device(path="/dev/fake-disk-test-sdc")]
    result = filter_devices(devices, config)
    assert [d.path for d in result] == ["/dev/fake-disk-test-sdb", "/dev/fake-disk-test-sdc"]


def test_filter_devices_empty_input_returns_empty_list(config):
    assert filter_devices([], config) == []


def test_filter_devices_uses_default_config_when_none_given():
    # Ne doit pas planter même sans config explicite (utilise SafetyConfig()).
    devices = [make_device(size_bytes=0)]
    assert filter_devices(devices) == []


# --- describe_rejection : diagnostic (§5 mode assisté, journal de bord) ----
#
# Même règles que is_allowed, mais avec la raison -- utilisé pour tracer
# dans le journal pourquoi un périphérique n'apparaît pas dans la liste
# plutôt que de laisser l'utilisateur deviner un écart entre les modes.


def test_describe_rejection_returns_none_when_allowed(config):
    assert describe_rejection(make_device(), config) is None


def test_describe_rejection_flags_system_disk(config):
    device = make_device(is_system=True, mountpoints=["/"])
    assert describe_rejection(device, config) is not None
    assert "système" in describe_rejection(device, config)


def test_describe_rejection_flags_app_path(config, tmp_path):
    device = make_device(mountpoints=[str(tmp_path)])
    reason = describe_rejection(device, config)
    assert reason is not None
    assert "application" in reason


def test_describe_rejection_flags_non_removable_non_usb(config):
    device = make_device(removable=False, bus="SATA")
    reason = describe_rejection(device, config)
    assert reason is not None
    assert "amovible" in reason or "USB" in reason


def test_describe_rejection_flags_zero_size(config):
    device = make_device(size_bytes=0)
    reason = describe_rejection(device, config)
    assert reason is not None
    assert "taille" in reason


def test_describe_rejection_flags_oversized(config):
    device = make_device(size_bytes=config.max_size_bytes + 1)
    reason = describe_rejection(device, config)
    assert reason is not None
    assert "taille" in reason
