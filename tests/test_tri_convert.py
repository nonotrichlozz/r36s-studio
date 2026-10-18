"""« Convertir des jeux », phase 1 `.7z` → `.zip` (`tri/convert.py`) : de
vraies archives créées par py7zr dans `tmp_path`, aucun réseau."""

from __future__ import annotations

import os
import zipfile

import py7zr
import pytest

from r36s_studio.doublons.move import InsufficientDiskSpace
from r36s_studio.tri.apply import has_journal
from r36s_studio.tri.convert import apply_conversion, build_convert_plan, convert_7z_to_zip, undo_conversion
from r36s_studio.tri.plan import CONVERT_JOURNAL_FILENAME, build_plan

ROM = os.urandom(3000) + b"\x00" * 40_000


def _make_7z(path, files=None, password=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    with py7zr.SevenZipFile(path, "w", password=password) as archive:
        for name, data in (files or {"Sonic.md": ROM}).items():
            archive.writestr(data, name)
    return path


def _zip_content(path):
    with zipfile.ZipFile(path) as archive:
        return {info.filename: (archive.read(info), info.compress_type) for info in archive.infolist()}


def test_plan_flags_7z_only_where_the_firmware_does_not_read_them(tmp_path):
    _make_7z(tmp_path / "megadrive" / "Sonic.7z")
    _make_7z(tmp_path / "megadrive" / "Already.7z")
    (tmp_path / "megadrive" / "Already.zip").write_bytes(b"x")
    _make_7z(tmp_path / "_originaux" / "megadrive" / "Old.7z")  # jamais reparcouru

    treefrog = build_convert_plan(str(tmp_path), "treefrogui")
    assert [m.members[0].name for m in treefrog.moves] == ["Sonic.7z"]
    assert [(m.members[0].name, m.reason) for m in treefrog.left_in_place] == [("Already.7z", "zip_exists")]

    rocknix = build_convert_plan(str(tmp_path), "rocknix")
    assert rocknix.moves == []
    assert {m.reason for m in rocknix.left_in_place} == {"seven_zip_read"}


def test_conversion_keeps_the_exact_content_in_a_deflate_zip_and_sets_the_original_aside(tmp_path):
    source = _make_7z(tmp_path / "md" / "Sonic.7z", {"Sonic.md": ROM, "notes/readme.txt": b"hello"})
    plan = build_convert_plan(str(tmp_path), "treefrogui")

    result = apply_conversion(plan)

    assert result.moved_files == 1 and not result.failures
    assert _zip_content(tmp_path / "md" / "Sonic.zip") == {
        "Sonic.md": (ROM, zipfile.ZIP_DEFLATED),
        "notes/readme.txt": (b"hello", zipfile.ZIP_DEFLATED),
    }
    assert not source.exists()
    assert (tmp_path / "_originaux" / "md" / "Sonic.7z").exists()
    assert [p.name for p in (tmp_path / "md").iterdir()] == ["Sonic.zip"]  # aucun dossier temporaire laissé
    assert has_journal(str(tmp_path), CONVERT_JOURNAL_FILENAME)


def test_undo_puts_the_7z_back_and_removes_only_the_created_zip(tmp_path):
    _make_7z(tmp_path / "md" / "Sonic.7z")
    apply_conversion(build_convert_plan(str(tmp_path), "treefrogui"))

    result = undo_conversion(str(tmp_path))

    assert result.restored == 1 and not result.conflicts
    assert (tmp_path / "md" / "Sonic.7z").exists()
    assert not (tmp_path / "md" / "Sonic.zip").exists()
    assert not has_journal(str(tmp_path), CONVERT_JOURNAL_FILENAME)


def test_undo_never_removes_a_zip_changed_since_the_conversion(tmp_path):
    _make_7z(tmp_path / "md" / "Sonic.7z")
    apply_conversion(build_convert_plan(str(tmp_path), "treefrogui"))
    (tmp_path / "md" / "Sonic.zip").write_bytes(b"remplace par l'utilisateur")

    result = undo_conversion(str(tmp_path))

    assert result.restored == 0 and result.conflicts[0].reason == "created_changed"
    assert (tmp_path / "md" / "Sonic.zip").read_bytes() == b"remplace par l'utilisateur"
    assert (tmp_path / "_originaux" / "md" / "Sonic.7z").exists()
    assert has_journal(str(tmp_path), CONVERT_JOURNAL_FILENAME)


def test_corrupt_or_protected_archive_is_reported_and_left_untouched(tmp_path):
    corrupt = _make_7z(tmp_path / "md" / "Corrupt.7z")
    data = bytearray(corrupt.read_bytes())
    data[60] ^= 0xFF  # dans les données compressées : py7zr ne le voit qu'à l'extraction
    corrupt.write_bytes(bytes(data))
    _make_7z(tmp_path / "md" / "Locked.7z", password="secret")

    result = apply_conversion(build_convert_plan(str(tmp_path), "treefrogui"))

    assert result.moved_files == 0
    assert sorted((p.name, reason) for p, reason in result.failures) == [("Corrupt.7z", "corrupt"), ("Locked.7z", "password")]
    assert sorted(p.name for p in (tmp_path / "md").iterdir()) == ["Corrupt.7z", "Locked.7z"]
    assert not (tmp_path / "_originaux").exists()


def test_not_enough_space_stops_before_writing_anything(tmp_path, monkeypatch):
    source = _make_7z(tmp_path / "md" / "Sonic.7z")

    def no_space(path, needed):
        raise InsufficientDiskSpace(str(path), needed, 0)

    monkeypatch.setattr("r36s_studio.tri.convert._check_disk_space", no_space)
    with pytest.raises(InsufficientDiskSpace):
        convert_7z_to_zip(source, source.with_suffix(".zip"))
    assert [p.name for p in (tmp_path / "md").iterdir()] == ["Sonic.7z"]


def test_an_existing_zip_is_never_overwritten(tmp_path):
    _make_7z(tmp_path / "md" / "Sonic.7z")
    plan = build_convert_plan(str(tmp_path), "treefrogui")
    (tmp_path / "md" / "Sonic.zip").write_bytes(b"deja la")

    result = apply_conversion(plan)

    assert result.moved_files == 0 and len(result.skipped_existing) == 1
    assert (tmp_path / "md" / "Sonic.zip").read_bytes() == b"deja la"
    assert (tmp_path / "md" / "Sonic.7z").exists()


def test_sorting_never_touches_the_originals_folder_or_the_conversion_journal(tmp_path):
    _make_7z(tmp_path / "md" / "Sonic.7z")
    apply_conversion(build_convert_plan(str(tmp_path), "treefrogui"))

    plan = build_plan(str(tmp_path), "rocknix")

    touched = {member for move in plan.moves + plan.unidentified for member in move.members}
    assert not any("_originaux" in member.parts or member.name == CONVERT_JOURNAL_FILENAME for member in touched)
