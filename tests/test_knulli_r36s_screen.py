"""Écran d'une carte KNULLI R36S (`partitions/boot_sets.py`,
`partitions/screen_backup.py`) sur l'arborescence réelle de
`knulli-rk3326-r36s-scarab-20260510.img.gz` (relevée le 2026-10-19) :
u-boot lit `rk3326-odroidgo2-linux.dtb` à la racine, le noyau
`boot/rk3326-rg351mp-linux.dtb`. Bug corrigé : l'écran d'origine était
renommé comme le .dtb d'u-boot et l'aurait écrasé."""

from __future__ import annotations

from pathlib import Path

import pytest

from r36s_studio.partitions import boot_sets, screen_backup

UBOOT = b"dtb u-boot odroidgo2"
KNULLI_KERNEL = b"dtb noyau KNULLI (R35S/R36S fix by lxc)"
FACTORY_KERNEL = b"dtb noyau d'usine rk3326-r35s"


def _knulli_card(root: Path, boot_dir: str = "BOOT", board: bytes = b"r36s\n") -> Path:
    """Fichiers de la partition FAT « KNULLI » de l'image (gros fichiers
    réduits à quelques octets)."""
    (root / "knulli-boot.conf").write_text("sharedevice=INTERNAL\nautoresize=true\n")
    (root / "boot.ini").write_text("load mmc 1:1 ${dtb_loadaddr} boot/rk3326-rg351mp-linux.dtb\n")
    (root / "rk3326-odroidgo2-linux.dtb").write_bytes(UBOOT)
    boot = root / boot_dir
    boot.mkdir()
    for name in ("linux", "uInitrd", "knulli", "firmware.sig"):
        (boot / name).write_bytes(b"x")
    (boot / "knulli.board").write_bytes(board)
    (boot / "rk3326-rg351mp-linux.dtb").write_bytes(KNULLI_KERNEL)
    return root


def _factory_screen(folder: Path) -> Path:
    """`.dtb` + `boot.ini` mis de côté d'une R36S d'usine (screen_backup)."""
    folder.mkdir()
    (folder / "rg351mp-kernel.dtb").write_bytes(b"dtb u-boot d'usine")
    (folder / "rk3326-r35s-linux.dtb").write_bytes(FACTORY_KERNEL)
    (folder / "boot.ini").write_text("usine")
    return folder


@pytest.mark.parametrize("boot_dir", ["BOOT", "boot"])
def test_original_screen_is_placed_only_as_the_knulli_kernel_dtb(tmp_path, boot_dir):
    (tmp_path / "card").mkdir()
    card = _knulli_card(tmp_path / "card", boot_dir)
    saved = _factory_screen(tmp_path / "saved")

    names = screen_backup.install_original_screen(saved, card)

    assert names == {"rk3326-r35s-linux.dtb": "rk3326-rg351mp-linux.dtb"}
    placed = sorted(p.name for p in (card / boot_sets.ORIGINAL_SCREEN_DIR).iterdir())
    assert placed == ["rk3326-rg351mp-linux.dtb"]  # jamais le .dtb d'u-boot d'usine
    assert (card / "rk3326-odroidgo2-linux.dtb").read_bytes() == UBOOT


@pytest.mark.parametrize("boot_dir", ["BOOT", "boot"])
def test_choose_screen_replaces_only_the_kernel_dtb_and_can_go_back(tmp_path, boot_dir):
    card = tmp_path / "card"
    card.mkdir()
    _knulli_card(card, boot_dir)
    screen_backup.install_original_screen(_factory_screen(tmp_path / "saved"), card)

    sets = boot_sets.list_sets(card)

    # Le dossier `boot/` du système n'est jamais un jeu : un seul jeu, une seule destination.
    assert [(s.set_id, s.files) for s in sets] == [
        ("ecran-d-origine", (("ecran-d-origine/rk3326-rg351mp-linux.dtb", f"{boot_dir}/rk3326-rg351mp-linux.dtb"),))
    ]
    boot_sets.apply_set(card, "ecran-d-origine")
    assert (card / boot_dir / "rk3326-rg351mp-linux.dtb").read_bytes() == FACTORY_KERNEL
    assert (card / "rk3326-odroidgo2-linux.dtb").read_bytes() == UBOOT
    assert not (card / "rk3326-r35s-linux.dtb").exists()

    boot_sets.restore_original(card)
    assert (card / boot_dir / "rk3326-rg351mp-linux.dtb").read_bytes() == KNULLI_KERNEL
    assert (card / "rk3326-odroidgo2-linux.dtb").read_bytes() == UBOOT


def test_a_hand_picked_folder_never_reaches_the_uboot_dtb(tmp_path):
    """« Utiliser des fichiers d'écran de mon ordinateur… » : un dossier qui
    contient aussi un `rk3326-odroidgo2-linux.dtb` (BOOT d'une autre carte)."""
    card = tmp_path / "card"
    card.mkdir()
    _knulli_card(card)
    chosen = tmp_path / "choisi"
    chosen.mkdir()
    (chosen / "rk3326-odroidgo2-linux.dtb").write_bytes(b"autre u-boot")
    (chosen / "rk3326-r35s-linux.dtb").write_bytes(FACTORY_KERNEL)

    assert screen_backup.install_original_screen(chosen, card) == {"rk3326-r35s-linux.dtb": "rk3326-rg351mp-linux.dtb"}
    boot_sets.apply_set(card, "ecran-d-origine")
    assert (card / "rk3326-odroidgo2-linux.dtb").read_bytes() == UBOOT

    only_uboot = tmp_path / "seulement-uboot"
    only_uboot.mkdir()
    (only_uboot / "rk3326-odroidgo2-linux.dtb").write_bytes(b"autre u-boot")
    assert screen_backup.install_original_screen(only_uboot, card) is None


def test_a_set_copied_by_hand_onto_the_card_cannot_write_the_uboot_dtb(tmp_path, monkeypatch):
    card = tmp_path / "card"
    card.mkdir()
    _knulli_card(card)
    panel = card / "Panels" / "Panel4"
    panel.mkdir(parents=True)
    (panel / "rk3326-odroidgo2-linux.dtb").write_bytes(b"u-boot du panneau")
    (panel / "rg351mp-kernel.dtb").write_bytes(b"autre")
    assert boot_sets.list_sets(card) == []  # aucun .dtb noyau : pas un jeu pour KNULLI

    # Même un jeu qui viserait la racine (garde-fou d'`apply_set`) est refusé.
    forged = boot_sets.BootFileSet(
        "Panels/Panel4", "Panel4", (("Panels/Panel4/rk3326-odroidgo2-linux.dtb", "rk3326-odroidgo2-linux.dtb"),)
    )
    monkeypatch.setattr(boot_sets, "list_sets", lambda root: [forged])
    with pytest.raises(ValueError, match="KNULLI"):
        boot_sets.apply_set(card, "Panels/Panel4")
    assert (card / "rk3326-odroidgo2-linux.dtb").read_bytes() == UBOOT


def test_other_knulli_boards_and_other_cards_keep_the_usual_behaviour(tmp_path):
    card = tmp_path / "card"
    card.mkdir()
    _knulli_card(card, board=b"rg40xx-v\n")
    assert boot_sets.knulli_kernel_dtb(card) is None

    darkosen = tmp_path / "darkosen"
    darkosen.mkdir()
    (darkosen / "rg351mp-uboot.dtb").write_bytes(b"u")
    (darkosen / "rk3326-r36s-linux.dtb").write_bytes(b"k")
    names = screen_backup.install_original_screen(_factory_screen(tmp_path / "saved"), darkosen)
    assert names == {"rg351mp-kernel.dtb": "rg351mp-uboot.dtb", "rk3326-r35s-linux.dtb": "rk3326-r36s-linux.dtb"}
