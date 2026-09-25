"""Tests de `tri/identify.py` -- identification en cascade (extension,
puis en-tête), jamais de supposition (docs/tri-roms.md)."""

from __future__ import annotations

import pytest

from r36s_studio.tri.identify import identify_file

from . import tri_fixtures as fx


@pytest.mark.parametrize(
    "name, content, system",
    [
        ("jeu.nes", fx.nes(), "nes"),
        ("jeu.fds", fx.fds(), "fds"),
        ("jeu.gb", fx.gb(), "gb"),
        ("jeu.gbc", fx.gb(), "gbc"),
        ("jeu.gba", fx.gba(), "gba"),
        ("jeu.z64", fx.n64(), "n64"),
        ("jeu.md", fx.megadrive(), "megadrive"),
        ("jeu.gen", fx.megadrive(), "megadrive"),
        ("jeu.smd", fx.smd(), "megadrive"),
        ("jeu.32x", fx.sega32x(), "sega32x"),
        ("jeu.ngp", fx.snk(), "ngp"),
        ("jeu.ngc", fx.snk(), "ngpc"),
        ("jeu.a78", fx.atari7800(), "atari7800"),
        ("jeu.lnx", fx.lynx(), "atarilynx"),
        ("jeu.col", fx.coleco(), "colecovision"),
    ],
)
def test_extension_with_matching_header_is_identified(tmp_path, name, content, system):
    result = identify_file(fx.write(tmp_path / name, content))
    assert result.system_id == system
    assert result.reason == "extension_header"


@pytest.mark.parametrize(
    "name, system",
    [
        ("jeu.sfc", "snes"),
        ("jeu.smc", "snes"),
        ("jeu.sms", "mastersystem"),
        ("jeu.gg", "gamegear"),
        ("jeu.pce", "pcengine"),
        ("jeu.ws", "wonderswan"),
        ("jeu.wsc", "wonderswancolor"),
        ("jeu.a26", "atari2600"),
        ("jeu.vb", "virtualboy"),
    ],
)
def test_extension_without_universal_signature_is_trusted(tmp_path, name, system):
    result = identify_file(fx.write(tmp_path / name, fx.raw()))
    assert result.system_id == system
    assert result.reason == "extension"


def test_extension_is_case_insensitive(tmp_path):
    assert identify_file(fx.write(tmp_path / "JEU.NES", fx.nes())).system_id == "nes"


@pytest.mark.parametrize("name", ["faux.nes", "faux.gba", "faux.gb", "faux.z64", "faux.md", "faux.lnx", "faux.col"])
def test_extension_contradicted_by_header_is_never_sorted(tmp_path, name):
    result = identify_file(fx.write(tmp_path / name, fx.raw()))
    assert result.system_id is None
    assert result.reason == "header_mismatch"


def test_md_with_32x_header_is_a_contradiction_not_a_guess(tmp_path):
    result = identify_file(fx.write(tmp_path / "jeu.md", fx.sega32x()))
    assert result.system_id is None
    assert result.reason == "header_mismatch"


def test_bin_with_mega_drive_header(tmp_path):
    result = identify_file(fx.write(tmp_path / "jeu.bin", fx.megadrive()))
    assert (result.system_id, result.reason) == ("megadrive", "bin_header")


def test_bin_with_32x_header(tmp_path):
    assert identify_file(fx.write(tmp_path / "jeu.bin", fx.sega32x())).system_id == "sega32x"


def test_bin_disc_track_is_never_taken_for_a_cartridge(tmp_path):
    result = identify_file(fx.write(tmp_path / "piste.bin", fx.cd_bin()))
    assert (result.system_id, result.reason) == (None, "disc_image")


def test_bin_without_known_header_is_unidentified(tmp_path):
    result = identify_file(fx.write(tmp_path / "jeu.bin", fx.raw()))
    assert (result.system_id, result.reason) == (None, "bin_unknown")


@pytest.mark.parametrize("name", ["jeu.chd", "jeu.iso", "jeu.pbp", "jeu.cue"])
def test_disc_formats_are_not_covered(tmp_path, name):
    result = identify_file(fx.write(tmp_path / name, fx.raw()))
    assert (result.system_id, result.reason) == (None, "disc_image")


def test_7z_is_not_read(tmp_path):
    result = identify_file(fx.write(tmp_path / "jeu.7z", fx.raw()))
    assert (result.system_id, result.reason) == (None, "archive_7z")


def test_unknown_extension(tmp_path):
    result = identify_file(fx.write(tmp_path / "notes.txt", b"hello"))
    assert (result.system_id, result.reason) == (None, "unknown_extension")


def test_zip_with_single_rom_is_identified_by_its_content(tmp_path):
    path = fx.write_zip(tmp_path / "jeu.zip", {"jeu.gba": fx.gba(), "lisezmoi.txt": b"info"})
    result = identify_file(path)
    assert (result.system_id, result.reason, result.detail) == ("gba", "zip_content", "jeu.gba")


def test_zip_content_header_is_checked_too(tmp_path):
    path = fx.write_zip(tmp_path / "jeu.zip", {"jeu.nes": fx.raw()})
    result = identify_file(path)
    assert (result.system_id, result.reason) == (None, "header_mismatch")


def test_zip_with_several_files_is_arcade_like_and_unidentified(tmp_path):
    path = fx.write_zip(tmp_path / "sf2.zip", {"sf2.01": b"a", "sf2.02": b"b"})
    result = identify_file(path)
    assert (result.system_id, result.reason) == (None, "zip_multiple")


def test_zip_with_single_unknown_file_is_unidentified(tmp_path):
    path = fx.write_zip(tmp_path / "jeu.zip", {"jeu.rom": b"a"})
    assert identify_file(path).system_id is None


def test_corrupt_zip_is_unidentified(tmp_path):
    result = identify_file(fx.write(tmp_path / "casse.zip", b"PK\x03\x04pas un zip"))
    assert (result.system_id, result.reason) == (None, "zip_unreadable")


def test_empty_zip_is_unidentified(tmp_path):
    result = identify_file(fx.write_zip(tmp_path / "vide.zip", {"lisezmoi.txt": b"x"}))
    assert (result.system_id, result.reason) == (None, "zip_empty")
