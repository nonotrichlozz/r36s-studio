"""Tests de la gestion des dossiers d'archive BOOT/EASYROMS
(partitions/archives.py, workflow à deux cartes §4.4). Tout se passe sous
`tmp_path` — jamais dans le vrai dossier personnel de l'utilisateur."""

from __future__ import annotations

from datetime import datetime

from r36s_studio.partitions.archives import (
    default_archives_dir,
    list_archives,
    new_archive_path,
    parse_archive_timestamp,
)


def test_default_archives_dir_is_under_home_documents():
    from pathlib import Path

    assert default_archives_dir() == Path.home() / "Documents" / "R36S Studio"


def test_new_archive_path_uses_requested_timestamp_format(tmp_path):
    now = datetime(2026, 7, 6, 0, 21)

    path = new_archive_path("BOOT", base_dir=tmp_path, now=now)

    assert path == tmp_path / "BOOT_2026-07-06_00-21"


def test_new_archive_path_does_not_create_the_directory(tmp_path):
    path = new_archive_path("EASYROMS", base_dir=tmp_path, now=datetime(2026, 1, 1, 0, 0))

    assert not path.exists()


def test_list_archives_empty_when_base_dir_missing(tmp_path):
    assert list_archives("BOOT", base_dir=tmp_path / "does_not_exist") == []


def test_list_archives_filters_by_label_and_sorts_newest_first(tmp_path):
    (tmp_path / "BOOT_2026-01-01_00-00").mkdir()
    (tmp_path / "BOOT_2026-07-06_00-21").mkdir()
    (tmp_path / "EASYROMS_2026-07-06_00-21").mkdir()  # autre label, exclu
    (tmp_path / "BOOT_not_a_folder_marker.txt").write_text("x")  # pas un dossier, exclu

    result = list_archives("BOOT", base_dir=tmp_path)

    assert [p.name for p in result] == ["BOOT_2026-07-06_00-21", "BOOT_2026-01-01_00-00"]


def test_parse_archive_timestamp_extracts_datetime():
    from pathlib import Path

    assert parse_archive_timestamp(Path("BOOT_2026-07-06_00-21")) == datetime(2026, 7, 6, 0, 21)


def test_parse_archive_timestamp_returns_none_for_custom_folder_name():
    from pathlib import Path

    assert parse_archive_timestamp(Path("mon_dossier_perso")) is None
