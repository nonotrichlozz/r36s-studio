from __future__ import annotations

import platform

import pytest

from r36s_studio.doublons.safety import is_filesystem_root, is_whole_user_folder


@pytest.mark.skipif(platform.system() != "Windows", reason="racines de lecteur Windows")
def test_windows_drive_root_is_a_filesystem_root():
    assert is_filesystem_root("C:\\") is True
    assert is_filesystem_root("D:\\") is True


@pytest.mark.skipif(platform.system() == "Windows", reason="racine POSIX")
def test_posix_root_is_a_filesystem_root():
    assert is_filesystem_root("/") is True


def test_a_regular_subfolder_is_never_a_filesystem_root(tmp_path):
    sub = tmp_path / "ROMs"
    sub.mkdir()
    assert is_filesystem_root(str(sub)) is False


def test_home_directory_is_a_whole_user_folder():
    assert is_whole_user_folder(str_home()) is True


def test_home_parent_directory_is_a_whole_user_folder():
    from pathlib import Path

    assert is_whole_user_folder(str(Path.home().resolve().parent)) is True


def test_standard_home_subfolder_taken_whole_is_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: tmp_path))
    documents = tmp_path / "Documents"
    documents.mkdir()

    assert is_whole_user_folder(str(documents)) is True


def test_subfolder_inside_a_standard_home_subfolder_is_never_flagged(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", staticmethod(lambda: tmp_path))
    roms = tmp_path / "Documents" / "ROMs"
    roms.mkdir(parents=True)

    assert is_whole_user_folder(str(roms)) is False


def test_an_unrelated_folder_is_never_a_whole_user_folder(tmp_path):
    unrelated = tmp_path / "Games"
    unrelated.mkdir()
    assert is_whole_user_folder(str(unrelated)) is False


def str_home() -> str:
    from pathlib import Path

    return str(Path.home())
