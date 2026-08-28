"""Tests de identify/__init__.py -- identify_from_boot_directory, utilisée
par l'étape 2 du mode assisté (§5 mode assisté) pour identifier la console
à partir des `.dtb` déjà présents sur la partition BOOT montée (avant toute
copie -- distinct de l'extraction elle-même, étape 3)."""

from __future__ import annotations

from r36s_studio.identify import identify_from_boot_directory
from r36s_studio.identify.dtb import DtbInfo


def test_returns_none_when_directory_has_no_dtb_file(tmp_path):
    (tmp_path / "boot.ini").write_text("console=r36s", encoding="utf-8")

    assert identify_from_boot_directory(tmp_path) is None


def test_returns_none_when_directory_does_not_exist(tmp_path):
    assert identify_from_boot_directory(tmp_path / "does-not-exist") is None


def test_parses_the_first_valid_dtb_found(tmp_path):
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "broken.dtb").write_bytes(b"not a real dtb")
    (tmp_path / "board.dtb").write_bytes(_build_fake_dtb())

    info = identify_from_boot_directory(tmp_path)

    assert info == DtbInfo(
        board_compatible="rk3326-evb-lp3-v12",
        panel_compatible="sitronix,st7703",
        timings={
            "hactive": 640,
            "vactive": 480,
            "clock-frequency": 25175000,
            "hfront-porch": 16,
            "hback-porch": 48,
            "hsync-len": 96,
            "vfront-porch": 10,
            "vback-porch": 33,
            "vsync-len": 2,
            "dsi,lanes": 4,
        },
    )


def test_skips_invalid_dtb_files_and_uses_the_next_valid_one(tmp_path):
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "a_broken.dtb").write_bytes(b"garbage, not a dtb at all")
    (tmp_path / "b_valid.dtb").write_bytes(_build_fake_dtb())

    info = identify_from_boot_directory(tmp_path)

    assert info is not None
    assert info.board_compatible == "rk3326-evb-lp3-v12"
