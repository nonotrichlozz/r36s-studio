"""Tests de la copie récursive vers une partition montée (partitions/copy.py).
Aucun montage réel : `source_dir`/`dest_dir` sont de simples dossiers locaux
sous `tmp_path`."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from r36s_studio.imaging.copy import OperationCancelled
from r36s_studio.partitions.copy import MountpointNotWritable, _check_writable, copy_tree


def _write(path, content: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def test_copy_tree_preserves_subdirectory_structure(tmp_path):
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "a.txt", b"aaaa")
    _write(source / "sub" / "b.txt", b"bb")

    copied = copy_tree(str(source), str(dest))

    assert copied == 6
    assert (dest / "a.txt").read_bytes() == b"aaaa"
    assert (dest / "sub" / "b.txt").read_bytes() == b"bb"


def test_copy_tree_reports_progress_up_to_total_bytes(tmp_path):
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "a.txt", b"x" * 1000)
    _write(source / "b.txt", b"y" * 2000)
    events = []

    copy_tree(str(source), str(dest), on_progress=events.append, block_size=64)

    assert events
    assert events[-1].done == 3000
    assert events[-1].total == 3000


def test_copy_tree_cancellation_raises_before_next_file(tmp_path):
    source = tmp_path / "source"
    dest = tmp_path / "dest"
    _write(source / "a.txt", b"aaaa")
    _write(source / "b.txt", b"bb")

    calls = {"n": 0}

    def should_cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 1  # laisse passer le premier fichier

    with pytest.raises(OperationCancelled):
        copy_tree(str(source), str(dest), should_cancel=should_cancel)


def test_copy_tree_returns_zero_for_empty_source(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    dest = tmp_path / "dest"

    copied = copy_tree(str(source), str(dest))

    assert copied == 0


# --- _check_writable / MountpointNotWritable -------------------------------
#
# Filet de sécurité générique, indépendant de l'OS et du système de
# fichiers : bug confirmé sur du vrai matériel où une partition EASYROMS
# (NTFS) mal détectée comme inscriptible sur macOS faisait échouer la copie
# en plein milieu avec `[Errno 30] Read-only file system` au lieu d'un refus
# explicite préalable.


def test_check_writable_passes_silently_for_writable_directory(tmp_path):
    _check_writable(str(tmp_path))  # ne doit rien lever


def test_check_writable_removes_its_probe_file(tmp_path):
    _check_writable(str(tmp_path))

    assert list(tmp_path.iterdir()) == []


def test_check_writable_creates_destination_if_missing(tmp_path):
    dest = tmp_path / "not_yet_mounted_by_this_test"

    _check_writable(str(dest))

    assert dest.is_dir()


@patch("r36s_studio.partitions.copy.open", side_effect=OSError(30, "Read-only file system"))
def test_check_writable_raises_explicit_error_on_read_only_mount(mock_open, tmp_path):
    with pytest.raises(MountpointNotWritable) as exc_info:
        _check_writable(str(tmp_path))

    assert str(tmp_path) in str(exc_info.value)
    assert "Read-only file system" in str(exc_info.value)


@patch("r36s_studio.partitions.copy.open", side_effect=OSError(30, "Read-only file system"))
def test_copy_tree_rejects_read_only_destination_before_copying_anything(mock_open, tmp_path):
    """Le cas réel : une partition mal détectée comme inscriptible ne doit
    plus jamais laisser `copy_tree` commencer à écrire des fichiers avant
    d'échouer à mi-course -- le refus doit être immédiat et explicite, quel
    que soit l'OS ou le système de fichiers en cause."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "jeu.zip").write_bytes(b"data")
    dest = tmp_path / "dest"
    dest.mkdir()

    with pytest.raises(MountpointNotWritable):
        copy_tree(str(source), str(dest))

    assert not (dest / "jeu.zip").exists()
