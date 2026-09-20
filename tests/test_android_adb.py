"""Tests de `android/adb.py` -- détection et lecture d'une console Android
via adb (étape 1, docs/android-adb.md). Toute commande passe par un
paramètre `runner` injectable (même principe que `subprocess.run` mocké
globalement par `tests/conftest.py`) -- aucune commande adb réelle n'est
exécutée dans cette suite, comme demandé par le brief."""

from __future__ import annotations

import subprocess

import pytest

from r36s_studio.android import adb
from r36s_studio.android.models import VALEUR_INCONNUE


def _fake_result(stdout: str) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


# --- list_devices ------------------------------------------------------


def test_list_devices_parses_serial_and_state():
    def runner(args, timeout):
        assert args[:2] == ["adb", "devices"]
        return _fake_result(
            "List of devices attached\n"
            "ABC123\tdevice product:flip2 model:RP_Flip_2 device:flip2\n"
        )

    devices = adb.list_devices("adb", runner=runner)

    assert len(devices) == 1
    assert devices[0].serial == "ABC123"
    assert devices[0].state == "device"


def test_list_devices_returns_empty_list_when_no_device():
    def runner(args, timeout):
        return _fake_result("List of devices attached\n\n")

    assert adb.list_devices("adb", runner=runner) == []


def test_list_devices_parses_unauthorized_state():
    def runner(args, timeout):
        return _fake_result("List of devices attached\nABC123\tunauthorized\n")

    devices = adb.list_devices("adb", runner=runner)

    assert devices[0].state == "unauthorized"


def test_list_devices_parses_multiple_devices():
    def runner(args, timeout):
        return _fake_result("List of devices attached\nSER1\tdevice\nSER2\tdevice\n")

    devices = adb.list_devices("adb", runner=runner)

    assert [d.serial for d in devices] == ["SER1", "SER2"]


def test_list_devices_raises_adb_command_error_on_timeout():
    def runner(args, timeout):
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    with pytest.raises(adb.AdbCommandError):
        adb.list_devices("adb", runner=runner)


def test_list_devices_raises_adb_command_error_when_binary_missing():
    def runner(args, timeout):
        raise OSError("introuvable")

    with pytest.raises(adb.AdbCommandError):
        adb.list_devices("adb", runner=runner)


# --- get_device_props ----------------------------------------------------

_GETPROP_DUMP_RETROID = (
    "[ro.product.manufacturer]: [Retroid]\n"
    "[ro.product.model]: [RP Flip 2]\n"
    "[ro.product.name]: [flip2]\n"
    "[ro.build.version.release]: [13]\n"
    "[ro.product.cpu.abi]: [arm64-v8a]\n"
)

_GETPROP_DUMP_RG406V = (
    "[ro.product.manufacturer]: [Anbernic]\n"
    "[ro.product.model]: [RG406V]\n"
    "[ro.product.name]: [rg406v]\n"
    "[ro.build.version.release]: [12]\n"
    "[ro.product.cpu.abi]: [arm64-v8a]\n"
)

_GETPROP_DUMP_ROTATE = (
    "[ro.product.manufacturer]: [Anbernic]\n"
    "[ro.product.model]: [RG Rotate]\n"
    "[ro.product.name]: [rotate]\n"
    "[ro.build.version.release]: [13]\n"
    "[ro.product.cpu.abi]: [arm64-v8a]\n"
)


@pytest.mark.parametrize(
    "dump, manufacturer, model",
    [
        (_GETPROP_DUMP_RETROID, "Retroid", "RP Flip 2"),
        (_GETPROP_DUMP_RG406V, "Anbernic", "RG406V"),
        (_GETPROP_DUMP_ROTATE, "Anbernic", "RG Rotate"),
    ],
)
def test_get_device_props_reads_the_five_properties(dump, manufacturer, model):
    def runner(args, timeout):
        assert args == ["adb", "-s", "SER1", "shell", "getprop"]
        return _fake_result(dump)

    info = adb.get_device_props("adb", "SER1", runner=runner)

    assert info.serial == "SER1"
    assert info.manufacturer == manufacturer
    assert info.model == model
    assert info.android_version in ("12", "13")
    assert info.abi == "arm64-v8a"


def test_get_device_props_falls_back_to_unknown_for_missing_property():
    def runner(args, timeout):
        return _fake_result("[ro.product.manufacturer]: [Retroid]\n")

    info = adb.get_device_props("adb", "SER1", runner=runner)

    assert info.manufacturer == "Retroid"
    assert info.model == VALEUR_INCONNUE
    assert info.android_version == VALEUR_INCONNUE


def test_get_device_props_raises_adb_command_error_on_timeout():
    def runner(args, timeout):
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    with pytest.raises(adb.AdbCommandError):
        adb.get_device_props("adb", "SER1", runner=runner)


# --- detect_connected_device ------------------------------------------


def test_detect_connected_device_returns_adb_missing_when_path_is_none():
    result = adb.detect_connected_device(None)

    assert result.state == "adb_missing"


def test_detect_connected_device_returns_no_device_when_list_is_empty():
    def runner(args, timeout):
        return _fake_result("List of devices attached\n")

    result = adb.detect_connected_device("adb", runner=runner)

    assert result.state == "no_device"


def test_detect_connected_device_returns_unauthorized():
    def runner(args, timeout):
        return _fake_result("List of devices attached\nSER1\tunauthorized\n")

    result = adb.detect_connected_device("adb", runner=runner)

    assert result.state == "unauthorized"
    assert result.devices[0].serial == "SER1"


def test_detect_connected_device_returns_multiple_devices():
    def runner(args, timeout):
        return _fake_result("List of devices attached\nSER1\tdevice\nSER2\tdevice\n")

    result = adb.detect_connected_device("adb", runner=runner)

    assert result.state == "multiple_devices"
    assert len(result.devices) == 2


def test_detect_connected_device_returns_ready_with_props():
    calls = {"n": 0}

    def runner(args, timeout):
        calls["n"] += 1
        if args[1] == "devices":
            return _fake_result("List of devices attached\nSER1\tdevice\n")
        return _fake_result(_GETPROP_DUMP_RETROID)

    result = adb.detect_connected_device("adb", runner=runner)

    assert result.state == "ready"
    assert result.device is not None
    assert result.device.manufacturer == "Retroid"
    assert calls["n"] == 2


def test_detect_connected_device_returns_adb_error_when_list_devices_fails():
    def runner(args, timeout):
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    result = adb.detect_connected_device("adb", runner=runner)

    assert result.state == "adb_error"
    assert result.error_detail


def test_detect_connected_device_returns_adb_error_when_getprop_fails():
    def runner(args, timeout):
        if args[1] == "devices":
            return _fake_result("List of devices attached\nSER1\tdevice\n")
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    result = adb.detect_connected_device("adb", runner=runner)

    assert result.state == "adb_error"
    assert result.devices  # la liste déjà obtenue reste disponible pour le diagnostic


def test_detect_connected_device_never_raises_on_unexpected_offline_state():
    def runner(args, timeout):
        return _fake_result("List of devices attached\nSER1\toffline\n")

    result = adb.detect_connected_device("adb", runner=runner)

    assert result.state == "no_device"
    assert result.devices[0].state == "offline"


# --- resolve_adb_path ----------------------------------------------------


def test_resolve_adb_path_prefers_path_over_downloaded_copy(monkeypatch):
    monkeypatch.setattr(adb.shutil, "which", lambda name: "/usr/bin/adb")
    monkeypatch.setattr(adb.platform_tools, "installed_adb_path", lambda: None)

    assert adb.resolve_adb_path() == "/usr/bin/adb"


def test_resolve_adb_path_falls_back_to_downloaded_copy(monkeypatch, tmp_path):
    downloaded = tmp_path / "adb"
    monkeypatch.setattr(adb.shutil, "which", lambda name: None)
    monkeypatch.setattr(adb.platform_tools, "installed_adb_path", lambda: downloaded)

    assert adb.resolve_adb_path() == str(downloaded)


def test_resolve_adb_path_returns_none_when_neither_is_available(monkeypatch):
    monkeypatch.setattr(adb.shutil, "which", lambda name: None)
    monkeypatch.setattr(adb.platform_tools, "installed_adb_path", lambda: None)

    assert adb.resolve_adb_path() is None
