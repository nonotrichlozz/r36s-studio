"""Fichiers d'écran de la carte d'origine mis de côté avant un flash puis
reposés sur la carte flashée (`partitions/screen_backup.py`). Noms relevés
sur le BOOT d'une R36S d'usine et dans le README de dArkOSen."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from r36s_studio.partitions import boot_sets, screen_backup


def _factory_boot(root):
    """BOOT d'une R36S d'usine, avec les doublons macOS et les .V1 du cas réel."""
    root.mkdir()
    for name, data in {
        "rg351mp-kernel.dtb": b"uboot-usine",
        "rk3326-r35s-linux.dtb": b"noyau-usine",
        "rg351mp-kernel.dtb.V1": b"ancien",
        "boot.ini": b"ini-usine",
        "Image": b"noyau",
        "._rg351mp-kernel.dtb": b"macos",
        "._boot.ini": b"macos",
    }.items():
        (root / name).write_bytes(data)
    return root


def test_save_keeps_screen_files_only_once_per_card(tmp_path):
    boot = _factory_boot(tmp_path / "boot")
    backups = tmp_path / "backups"

    folder, created = screen_backup.save_original_screen(boot, backups, "ab" * 32, now=datetime(2026, 10, 14, 11, 3))

    assert created
    assert sorted(p.name for p in folder.iterdir()) == ["boot.ini", "origine.json", "rg351mp-kernel.dtb", "rk3326-r35s-linux.dtb"]
    assert json.loads((folder / "origine.json").read_text(encoding="utf-8"))["fingerprint"] == "ab" * 32
    (boot / "rg351mp-kernel.dtb").write_bytes(b"modifie")  # même empreinte : jamais recopié ni écrasé
    assert screen_backup.save_original_screen(boot, backups, "ab" * 32) == (folder, False)
    assert (folder / "rg351mp-kernel.dtb").read_bytes() == b"uboot-usine"


def test_save_without_dtb_saves_nothing(tmp_path):
    boot = tmp_path / "boot"
    boot.mkdir()
    (boot / "boot.ini").write_bytes(b"x")
    assert screen_backup.save_original_screen(boot, tmp_path / "backups", "cd" * 32) is None
    assert not (tmp_path / "backups").exists()


def test_install_renames_like_the_flashed_firmware_and_comes_first(tmp_path):
    folder, _ = screen_backup.save_original_screen(_factory_boot(tmp_path / "boot"), tmp_path / "b", "ef" * 32)
    target = tmp_path / "darkosen"
    (target / "Panels" / "Panel1").mkdir(parents=True)
    for name in ("rg351mp-uboot.dtb", "rk3326-r36s-linux.dtb", "boot.ini", "Panels/Panel1/x.dtb"):
        (target / name).write_bytes(b"darkosen")

    names = screen_backup.install_original_screen(folder, target)

    assert names == {"rg351mp-kernel.dtb": "rg351mp-uboot.dtb", "rk3326-r35s-linux.dtb": "rk3326-r36s-linux.dtb"}
    assert (target / "ecran-d-origine" / "rg351mp-uboot.dtb").read_bytes() == b"uboot-usine"
    assert not (target / "ecran-d-origine" / "boot.ini").exists()  # noyau d'usine : jamais sur un autre firmware
    sets = boot_sets.list_sets(target)
    assert sets[0].set_id == boot_sets.ORIGINAL_SCREEN_DIR
    boot_sets.apply_set(target, boot_sets.ORIGINAL_SCREEN_DIR)
    assert (target / "rk3326-r36s-linux.dtb").read_bytes() == b"noyau-usine"


def test_install_skips_firmware_without_root_dtb(tmp_path):
    folder, _ = screen_backup.save_original_screen(_factory_boot(tmp_path / "boot"), tmp_path / "b", "01" * 32)
    rocknix = tmp_path / "rocknix"
    (rocknix / "device_trees").mkdir(parents=True)
    assert screen_backup.install_original_screen(folder, rocknix) is None
    assert not (rocknix / "ecran-d-origine").exists()


def test_target_names_on_a_real_darkosen_boot():
    """Racine du BOOT d'une vraie carte dArkOSen (2026-10-14) : deux .dtb
    pour u-boot, celui des R36S et celui des clones."""
    darkosen = ["rg351mp-uboot.dtb", "rg351v-uboot.dtb", "rk3326-r36s-linux.dtb"]
    assert screen_backup.target_names(["rg351mp-kernel.dtb", "rk3326-r35s-linux.dtb"], darkosen) == {
        "rg351mp-kernel.dtb": "rg351mp-uboot.dtb",
        "rk3326-r35s-linux.dtb": "rk3326-r36s-linux.dtb",
    }


def test_target_names_never_guess_when_ambiguous():
    assert screen_backup.target_names(["rg351x-kernel.dtb"], ["rg351v-uboot.dtb", "rg351mp-uboot.dtb"]) == {
        "rg351x-kernel.dtb": "rg351x-kernel.dtb"
    }
    assert screen_backup.target_names(["custom.dtb"], ["rg351mp-uboot.dtb"]) == {"custom.dtb": "custom.dtb"}


def test_save_runner_never_blocks_the_flash(qapp, tmp_path):
    """Carte illisible : résultat « failed », jamais une exception."""
    from r36s_studio.gui.partition_runner import OriginalScreenSaveRunner

    runner = OriginalScreenSaveRunner("/dev/fake-disk-test-1", backups_dir=tmp_path)
    results = []
    runner.finished_save.connect(lambda *args: results.append(args))
    with patch("r36s_studio.gui.partition_runner.locate_mounted", side_effect=OSError("débranchée")):
        runner.run()
    assert results == [(None, "failed", "débranchée")]

    boot = _factory_boot(tmp_path / "boot")
    results.clear()
    with patch("r36s_studio.gui.partition_runner.locate_mounted", return_value=MagicMock(mountpoint=str(boot))), patch(
        "r36s_studio.gui.partition_runner.unmount_forced"
    ):
        runner.run()
    assert results[0][1] == "saved"


def test_worker_installs_after_flash_and_skips_rocknix(tmp_path, capsys):
    from r36s_studio.__main__ import _install_original_screen_after_flash

    folder, _ = screen_backup.save_original_screen(_factory_boot(tmp_path / "boot"), tmp_path / "b", "23" * 32)
    target = tmp_path / "flashed"
    target.mkdir()
    (target / "rg351mp-uboot.dtb").write_bytes(b"x")
    device = MagicMock(path="/dev/fake-disk-test-2")
    with patch("r36s_studio.__main__.locate_mounted", return_value=MagicMock(mountpoint=str(target))), patch(
        "r36s_studio.__main__.unmount_forced"
    ):
        _install_original_screen_after_flash(device, str(folder), rocknix=False)
        _install_original_screen_after_flash(device, str(folder), rocknix=True)
    out = capsys.readouterr().out
    assert (target / "ecran-d-origine" / "rg351mp-uboot.dtb").read_bytes() == b"uboot-usine"
    assert "Écran d'origine reposé" in out and "ROCKNIX choisit son écran autrement" in out
