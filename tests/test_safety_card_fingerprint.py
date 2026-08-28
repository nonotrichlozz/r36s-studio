"""Tests de safety/card_fingerprint.py -- garde-fou du mode assisté (§5) :
empreinte du contenu de BOOT, utilisée pour vérifier qu'entre l'étape 1
(carte d'origine) et l'étape 4 (carte neuve), il s'agit bien de deux cartes
différentes -- `path`/`size_bytes` seuls ne suffisent pas (chemin macOS
instable, deux cartes du même modèle ont la même taille)."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from r36s_studio.partitions.locate import PartitionInfo, PartitionNotFound, PartitionNotMounted
from r36s_studio.safety.card_fingerprint import compute_boot_fingerprint, is_same_card


@patch("r36s_studio.safety.card_fingerprint.list_partitions", return_value=[])
def test_compute_boot_fingerprint_returns_none_when_no_boot_partition(mock_list):
    assert compute_boot_fingerprint("/dev/fake-disk-test-1") is None


@patch("r36s_studio.safety.card_fingerprint.locate_mounted", side_effect=PartitionNotMounted("BOOT", "/dev/x"))
@patch("r36s_studio.safety.card_fingerprint.list_partitions")
def test_compute_boot_fingerprint_returns_none_when_boot_cannot_be_mounted(mock_list, mock_locate):
    mock_list.return_value = [PartitionInfo("/dev/fake-disk-test-1s1", "", "fat16", None)]
    assert compute_boot_fingerprint("/dev/fake-disk-test-1") is None


@patch("r36s_studio.safety.card_fingerprint.list_partitions", side_effect=subprocess.CalledProcessError(1, "lsblk"))
def test_compute_boot_fingerprint_returns_none_instead_of_raising_on_read_failure(mock_list):
    assert compute_boot_fingerprint("/dev/fake-disk-test-1") is None


def _boot_partition(mountpoint: str) -> PartitionInfo:
    return PartitionInfo("/dev/fake-disk-test-1s1", "", "fat16", mountpoint)


_FAKE_PARTITION_LIST = [PartitionInfo("/dev/fake-disk-test-1s1", "", "fat16", None)]


def test_compute_boot_fingerprint_differs_for_different_boot_contents(tmp_path):
    boot_a = tmp_path / "boot_a"
    boot_a.mkdir()
    (boot_a / "boot.ini").write_bytes(b"console=r36s panel=st7703")

    boot_b = tmp_path / "boot_b"
    boot_b.mkdir()
    (boot_b / "boot.ini").write_bytes(b"console=r35s panel=other")

    with patch("r36s_studio.safety.card_fingerprint.list_partitions", return_value=_FAKE_PARTITION_LIST):
        with patch("r36s_studio.safety.card_fingerprint.locate_mounted", return_value=_boot_partition(str(boot_a))):
            fingerprint_a = compute_boot_fingerprint("/dev/fake-disk-test-1")
        with patch("r36s_studio.safety.card_fingerprint.locate_mounted", return_value=_boot_partition(str(boot_b))):
            fingerprint_b = compute_boot_fingerprint("/dev/fake-disk-test-2")

    assert fingerprint_a is not None
    assert fingerprint_b is not None
    assert fingerprint_a != fingerprint_b


def test_compute_boot_fingerprint_is_stable_for_identical_boot_contents(tmp_path):
    boot_1 = tmp_path / "boot_1"
    boot_1.mkdir()
    (boot_1 / "boot.ini").write_bytes(b"console=r36s panel=st7703")

    boot_2 = tmp_path / "boot_2"
    boot_2.mkdir()
    (boot_2 / "boot.ini").write_bytes(b"console=r36s panel=st7703")

    with patch("r36s_studio.safety.card_fingerprint.list_partitions", return_value=_FAKE_PARTITION_LIST):
        with patch("r36s_studio.safety.card_fingerprint.locate_mounted", return_value=_boot_partition(str(boot_1))):
            fingerprint_1 = compute_boot_fingerprint("/dev/fake-disk-test-1")
        with patch("r36s_studio.safety.card_fingerprint.locate_mounted", return_value=_boot_partition(str(boot_2))):
            fingerprint_2 = compute_boot_fingerprint("/dev/fake-disk-test-1")

    assert fingerprint_1 == fingerprint_2


def test_is_same_card_true_when_both_fingerprints_present_and_equal():
    assert is_same_card("abc123", "abc123") is True


def test_is_same_card_false_when_fingerprints_differ():
    assert is_same_card("abc123", "def456") is False


def test_is_same_card_false_when_either_fingerprint_missing():
    assert is_same_card(None, "abc123") is False
    assert is_same_card("abc123", None) is False
    assert is_same_card(None, None) is False
