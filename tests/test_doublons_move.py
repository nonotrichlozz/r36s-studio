"""Tests de `doublons/move.py` -- déplacement des doublons écartés vers un
dossier de destination configurable (signalé : « permettre de choisir
l'emplacement du dossier de destination, au lieu de _doublons imposé à la
racine du dossier analysé »). Couvre les garde-fous ajoutés après
validation du plan (mode simulation, lecture seule, espace insuffisant,
journal écrit au fil de l'eau, disque différent, destination refusée)."""

from __future__ import annotations

import json
import os

import pytest

from r36s_studio.doublons.move import (
    CopyVerificationFailed,
    DestinationInsideRootNotAllowed,
    DestinationIsFilesystemRoot,
    DestinationNotWritable,
    DuplicatesOutsideRoot,
    InsufficientDiskSpace,
    MoveCancelled,
    check_destination_allowed,
    default_destination,
    is_cross_volume_destination,
    move_duplicates,
)
from r36s_studio.doublons.scan import Unit


def _touch(path, content=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _single_file_unit(path, content=b"x", known_sha256=None):
    _touch(path, content)
    return Unit(
        representative=path,
        members=[path],
        total_size_bytes=len(content),
        is_linked=False,
        known_sha256=known_sha256,
    )


def _make_cross_volume(monkeypatch, destination_suffix="_doublons"):
    """Simule une destination sur un volume différent de `root` --
    `os.stat` renvoie un `st_dev` différent pour tout chemin dont le nom
    se termine par `destination_suffix`, même principe que l'ancien test
    « volume différent » avant que cette fonctionnalité ne soit ajoutée."""
    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if str(path).endswith(destination_suffix):

            class FakeStat:
                st_dev = result.st_dev + 1

            return FakeStat()
        return result

    monkeypatch.setattr("r36s_studio.doublons.move.os.stat", fake_stat)


# --- Même disque (comportement historique) ---------------------------------


def test_move_duplicates_moves_file_under_doublons_preserving_relative_path(tmp_path):
    game = tmp_path / "SNES" / "Game.zip"
    unit = _single_file_unit(game, b"x" * 10)

    moved = move_duplicates(str(tmp_path), [unit])

    assert moved == 1
    assert not game.exists()
    assert (tmp_path / "_doublons" / "SNES" / "Game.zip").exists()


def test_move_duplicates_moves_an_entire_linked_unit_never_partially(tmp_path):
    cue = tmp_path / "PSX" / "Game.cue"
    bin_ = tmp_path / "PSX" / "Game.bin"
    _touch(cue, b"cue")
    _touch(bin_, b"bin" * 10)
    unit = Unit(representative=cue, members=[cue, bin_], total_size_bytes=33, is_linked=True)

    moved = move_duplicates(str(tmp_path), [unit])

    assert moved == 2
    assert (tmp_path / "_doublons" / "PSX" / "Game.cue").exists()
    assert (tmp_path / "_doublons" / "PSX" / "Game.bin").exists()


def test_move_duplicates_resolves_name_collision_with_a_numeric_suffix(tmp_path):
    unit = _single_file_unit(tmp_path / "Game.zip")
    _touch(tmp_path / "_doublons" / "Game.zip", b"already there")

    move_duplicates(str(tmp_path), [unit])

    assert (tmp_path / "_doublons" / "Game_2.zip").exists()
    assert (tmp_path / "_doublons" / "Game.zip").read_bytes() == b"already there"


def test_move_duplicates_dry_run_touches_nothing(tmp_path):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game)

    moved = move_duplicates(str(tmp_path), [unit], dry_run=True)

    assert moved == 1
    assert game.exists()
    assert not (tmp_path / "_doublons").exists()


def test_move_duplicates_writes_journal_incrementally_so_a_crash_mid_batch_leaves_it_accurate(tmp_path):
    paths = []
    units = []
    for name in ("A.zip", "B.zip", "C.zip"):
        path = tmp_path / name
        units.append(_single_file_unit(path))
        paths.append(path)

    def flaky_progress(done, total):
        if done == 2:
            raise RuntimeError("simulated crash")

    with pytest.raises(RuntimeError):
        move_duplicates(str(tmp_path), units, on_progress=flaky_progress)

    journal = json.loads((tmp_path / "_doublons" / "journal.json").read_text(encoding="utf-8"))
    assert len(journal) == 2
    assert not paths[0].exists()
    assert not paths[1].exists()
    assert paths[2].exists()  # jamais atteint, l'exception a interrompu avant


def test_move_duplicates_journal_entries_use_absolute_paths(tmp_path):
    game = tmp_path / "SNES" / "Game.zip"
    unit = _single_file_unit(game)

    move_duplicates(str(tmp_path), [unit])

    journal = json.loads((tmp_path / "_doublons" / "journal.json").read_text(encoding="utf-8"))
    assert os.path.isabs(journal[0]["source"])
    assert os.path.isabs(journal[0]["destination"])


def test_move_duplicates_reports_destination_not_writable_before_moving(tmp_path, monkeypatch):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game)

    def fail_open(*args, **kwargs):
        raise OSError("simulated read-only volume")

    monkeypatch.setattr("r36s_studio.doublons.move.open", fail_open, raising=False)

    with pytest.raises(DestinationNotWritable):
        move_duplicates(str(tmp_path), [unit])

    assert game.exists()


def test_move_duplicates_reports_insufficient_disk_space_before_moving(tmp_path, monkeypatch):
    game = tmp_path / "Game.zip"
    unit = _single_file_unit(game, b"x" * 100)

    class FakeUsage:
        free = 10

    monkeypatch.setattr("r36s_studio.doublons.move.shutil.disk_usage", lambda path: FakeUsage())

    with pytest.raises(InsufficientDiskSpace):
        move_duplicates(str(tmp_path), [unit])

    assert game.exists()


def test_move_duplicates_rejects_a_file_outside_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside" / "Game.zip"
    unit = _single_file_unit(outside)

    with pytest.raises(DuplicatesOutsideRoot):
        move_duplicates(str(root), [unit])


def test_move_duplicates_cooperative_cancel_stops_mid_batch(tmp_path):
    paths = []
    units = []
    for name in ("A.zip", "B.zip"):
        path = tmp_path / name
        units.append(_single_file_unit(path))
        paths.append(path)

    with pytest.raises(MoveCancelled):
        move_duplicates(str(tmp_path), units, should_cancel=lambda: True)

    assert paths[0].exists()
    assert paths[1].exists()


def test_move_duplicates_reports_progress_per_file(tmp_path):
    units = [_single_file_unit(tmp_path / name) for name in ("A.zip", "B.zip")]

    events = []
    move_duplicates(str(tmp_path), units, on_progress=lambda done, total: events.append((done, total)))

    assert events == [(1, 2), (2, 2)]


# --- Destination personnalisée, même disque --------------------------------


def test_move_duplicates_accepts_a_destination_outside_root(tmp_path):
    root = tmp_path / "root"
    destination = tmp_path / "backup"
    game = root / "SNES" / "Game.zip"
    unit = _single_file_unit(game)

    moved = move_duplicates(str(root), [unit], destination=str(destination))

    assert moved == 1
    assert not game.exists()
    assert (destination / "SNES" / "Game.zip").exists()
    # Aucun `_doublons/` créé à la racine -- la destination choisie
    # remplace entièrement la proposition par défaut.
    assert not (root / "_doublons").exists()


def test_move_duplicates_keeps_original_tree_structure_under_a_custom_destination(tmp_path):
    root = tmp_path / "root"
    destination = tmp_path / "backup"
    a = root / "SNES" / "sub" / "A.zip"
    b = root / "PSX" / "B.zip"
    units = [_single_file_unit(a), _single_file_unit(b)]

    move_duplicates(str(root), units, destination=str(destination))

    assert (destination / "SNES" / "sub" / "A.zip").exists()
    assert (destination / "PSX" / "B.zip").exists()


def test_default_destination_is_root_slash_doublons(tmp_path):
    assert default_destination(str(tmp_path)) == str((tmp_path / "_doublons").resolve())


# --- Destination refusée (§ garde-fou demandé) -----------------------------


def test_check_destination_allowed_refuses_a_subfolder_of_root_other_than_doublons(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    other = root / "some_other_folder"

    with pytest.raises(DestinationInsideRootNotAllowed):
        check_destination_allowed(str(root), str(other))


def test_check_destination_allowed_accepts_the_default_doublons_folder(tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    check_destination_allowed(str(root), str(root / "_doublons"))  # ne lève pas


def test_check_destination_allowed_accepts_a_subfolder_of_doublons(tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    check_destination_allowed(str(root), str(root / "_doublons" / "session1"))  # ne lève pas


def test_check_destination_allowed_accepts_anything_outside_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "elsewhere"

    check_destination_allowed(str(root), str(outside))  # ne lève pas, même si `outside` n'existe pas encore


def test_check_destination_allowed_refuses_a_filesystem_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr("r36s_studio.doublons.move.is_filesystem_root", lambda path: True)

    with pytest.raises(DestinationIsFilesystemRoot):
        check_destination_allowed(str(root), str(tmp_path / "anything"))


def test_check_destination_allowed_refuses_a_read_only_destination(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    destination = tmp_path / "backup"
    destination.mkdir()

    def fail_open(*args, **kwargs):
        raise OSError("simulated read-only volume")

    monkeypatch.setattr("r36s_studio.doublons.move.open", fail_open, raising=False)

    with pytest.raises(DestinationNotWritable):
        check_destination_allowed(str(root), str(destination))


def test_check_destination_allowed_never_creates_a_destination_that_does_not_exist_yet(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    destination = tmp_path / "not_created_yet" / "backup"

    check_destination_allowed(str(root), str(destination))

    assert not destination.exists()
    assert not destination.parent.exists()


def test_move_duplicates_refuses_destination_inside_root_before_moving_anything(tmp_path):
    root = tmp_path / "root"
    game = root / "Game.zip"
    unit = _single_file_unit(game)
    other = root / "some_other_folder"

    with pytest.raises(DestinationInsideRootNotAllowed):
        move_duplicates(str(root), [unit], destination=str(other))

    assert game.exists()


def test_move_duplicates_refuses_destination_inside_root_even_in_dry_run(tmp_path):
    """§ garde-fou demandé : refuser une destination invalide, y compris
    en simulation -- prévenir tôt plutôt que de laisser croire que ce
    choix serait accepté pour de vrai ensuite."""
    root = tmp_path / "root"
    game = root / "Game.zip"
    unit = _single_file_unit(game)
    other = root / "some_other_folder"

    with pytest.raises(DestinationInsideRootNotAllowed):
        move_duplicates(str(root), [unit], destination=str(other), dry_run=True)


# --- Disque différent (§ garde-fou demandé) ---------------------------------


def test_is_cross_volume_destination_true_when_devices_differ(tmp_path, monkeypatch):
    _make_cross_volume(monkeypatch, destination_suffix="backup")
    root = tmp_path / "root"
    root.mkdir()
    destination = tmp_path / "backup"
    destination.mkdir()

    assert is_cross_volume_destination(str(root), str(destination)) is True


def test_is_cross_volume_destination_false_when_devices_match(tmp_path):
    root = tmp_path / "root"
    root.mkdir()

    assert is_cross_volume_destination(str(root), str(root / "_doublons")) is False


def test_is_cross_volume_destination_false_when_undetermined(tmp_path, monkeypatch):
    """Jamais affirmé sans preuve -- un `os.stat` qui échoue des deux
    côtés (chemin qui ne peut être résolu du tout) ne doit jamais faire
    basculer sur le chemin lent par supposition."""
    monkeypatch.setattr(
        "r36s_studio.doublons.move.os.stat", lambda *a, **k: (_ for _ in ()).throw(OSError("indisponible"))
    )

    assert is_cross_volume_destination(str(tmp_path), str(tmp_path / "x")) is False


def test_move_duplicates_moves_the_file_when_destination_is_on_another_volume(tmp_path, monkeypatch):
    _make_cross_volume(monkeypatch, destination_suffix="backup")
    root = tmp_path / "root"
    destination = tmp_path / "backup"
    game = root / "SNES" / "Game.zip"
    unit = _single_file_unit(game, b"contenu de test")

    moved = move_duplicates(str(root), [unit], destination=str(destination))

    assert moved == 1
    assert not game.exists()
    result = destination / "SNES" / "Game.zip"
    assert result.exists()
    assert result.read_bytes() == b"contenu de test"
    # Aucun fichier temporaire orphelin après un déplacement réussi.
    assert list((destination / "SNES").iterdir()) == [result]


def test_move_duplicates_cross_volume_verifies_known_sha256_before_deleting_source(tmp_path, monkeypatch):
    import hashlib

    _make_cross_volume(monkeypatch, destination_suffix="backup")
    root = tmp_path / "root"
    destination = tmp_path / "backup"
    content = b"contenu identique"
    game = root / "Game.zip"
    digest = hashlib.sha256(content).hexdigest()
    unit = _single_file_unit(game, content, known_sha256=digest)

    move_duplicates(str(root), [unit], destination=str(destination))

    assert (destination / "Game.zip").read_bytes() == content


def test_move_duplicates_cross_volume_raises_and_keeps_source_when_copy_is_corrupted(tmp_path, monkeypatch):
    """Interruption/altération pendant la copie (signalé explicitement) --
    la source ne doit jamais être supprimée, et aucun fichier ne doit
    exister à moitié sous son nom final."""
    _make_cross_volume(monkeypatch, destination_suffix="backup")
    root = tmp_path / "root"
    destination = tmp_path / "backup"
    destination.mkdir()
    game = root / "Game.zip"
    unit = _single_file_unit(game, b"x" * 100)

    real_copy2 = __import__("shutil").copy2

    def truncating_copy2(src, dst, *args, **kwargs):
        real_copy2(src, dst, *args, **kwargs)
        # Simule une copie interrompue/tronquée : le fichier temporaire
        # existe mais avec une taille différente de la source.
        with open(dst, "wb") as handle:
            handle.write(b"x" * 10)

    monkeypatch.setattr("r36s_studio.doublons.move.shutil.copy2", truncating_copy2)

    with pytest.raises(CopyVerificationFailed):
        move_duplicates(str(root), [unit], destination=str(destination))

    assert game.exists()  # jamais touchée
    assert game.read_bytes() == b"x" * 100  # jamais altérée
    final = destination / "Game.zip"
    assert not final.exists()  # jamais un fichier à moitié écrit sous son nom final
    # Aucun fichier temporaire orphelin après l'échec.
    assert not any(destination.glob("*.r36s_studio_doublons_partial"))


def test_move_duplicates_cross_volume_raises_when_copy_itself_fails(tmp_path, monkeypatch):
    """Interruption avant même la fin de la copie (ex. carte débranchée,
    coupure) -- même garantie : source intacte, rien à moitié écrit."""
    _make_cross_volume(monkeypatch, destination_suffix="backup")
    root = tmp_path / "root"
    destination = tmp_path / "backup"
    destination.mkdir()
    game = root / "Game.zip"
    unit = _single_file_unit(game, b"x" * 100)

    def failing_copy2(src, dst, *args, **kwargs):
        # Écrit un fragment puis échoue -- imite une coupure en cours de
        # copie plutôt qu'un échec avant la moindre écriture.
        with open(dst, "wb") as handle:
            handle.write(b"partiel")
        raise OSError("coupure simulée")

    monkeypatch.setattr("r36s_studio.doublons.move.shutil.copy2", failing_copy2)

    with pytest.raises(OSError):
        move_duplicates(str(root), [unit], destination=str(destination))

    assert game.exists()
    assert game.read_bytes() == b"x" * 100
    assert not (destination / "Game.zip").exists()
    assert not any(destination.glob("*.r36s_studio_doublons_partial"))


def test_move_duplicates_cross_volume_checks_disk_space_on_the_destination_volume(tmp_path, monkeypatch):
    _make_cross_volume(monkeypatch, destination_suffix="backup")
    root = tmp_path / "root"
    destination = tmp_path / "backup"
    game = root / "Game.zip"
    unit = _single_file_unit(game, b"x" * 100)

    seen_paths = []
    real_usage = __import__("shutil").disk_usage

    class FakeUsage:
        free = 10

    def fake_disk_usage(path):
        seen_paths.append(str(path))
        return FakeUsage()

    monkeypatch.setattr("r36s_studio.doublons.move.shutil.disk_usage", fake_disk_usage)

    with pytest.raises(InsufficientDiskSpace):
        move_duplicates(str(root), [unit], destination=str(destination))

    assert game.exists()
    # Vérifié sur le volume de la destination, jamais celui de root.
    assert any("backup" in path for path in seen_paths)


def test_move_duplicates_cross_volume_cooperative_cancel_leaves_source_intact(tmp_path, monkeypatch):
    _make_cross_volume(monkeypatch, destination_suffix="backup")
    root = tmp_path / "root"
    destination = tmp_path / "backup"
    game = root / "Game.zip"
    unit = _single_file_unit(game)

    with pytest.raises(MoveCancelled):
        move_duplicates(str(root), [unit], destination=str(destination), should_cancel=lambda: True)

    assert game.exists()
