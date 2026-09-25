"""Tests de `doublons/move.py` -- déplacement des doublons écartés vers un
dossier de destination configurable (signalé : « permettre de choisir
l'emplacement du dossier de destination, au lieu de _doublons imposé à la
racine du dossier analysé »). Couvre les garde-fous ajoutés après
validation du plan (mode simulation, lecture seule, espace insuffisant,
journal écrit au fil de l'eau, disque différent, destination refusée)."""

from __future__ import annotations

import errno
import json
import os

import pytest

from r36s_studio.doublons.move import (
    CopyVerificationFailed,
    DestinationInsideRootNotAllowed,
    DestinationIsFilesystemRoot,
    DestinationNotWritable,
    DuplicatesOutsideRoot,
    FatFileSizeLimitExceeded,
    InsufficientDiskSpace,
    MoveCancelled,
    MoveFileFailed,
    PartialMoveFailure,
    check_destination_allowed,
    default_destination,
    destination_filesystem_kind,
    fat_oversized_members,
    is_cross_volume_destination,
    is_fat_filesystem,
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


@pytest.fixture(autouse=True)
def _no_fat_check_by_default(monkeypatch):
    """`move_duplicates` sonde désormais le système de fichiers de la
    destination avant tout déplacement réel (§ demandé explicitement,
    point 6) -- sur une machine non-Windows, cette sonde invoque `mount`
    en sous-processus (`_posix_mount_filesystem`), que le garde-fou
    global (`tests/conftest.py::_forbid_real_subprocess`) refuse sans
    mock explicite. Neutralisée par défaut ici (`None` : indéterminable,
    comportement déjà défini comme sûr, la sonde FAT est alors simplement
    omise) pour que les tests de ce fichier n'aient pas tous à s'en
    soucier -- les tests dédiés à cette sonde (plus bas) repatchent
    `destination_filesystem_kind` eux-mêmes, ce qui l'emporte normalement
    pour la durée de leur propre corps (même principe que `_forbid_real_
    subprocess`)."""
    monkeypatch.setattr("r36s_studio.doublons.move.destination_filesystem_kind", lambda path: None)
    yield


def _make_cross_volume(monkeypatch, destination_suffix="_doublons"):
    """Simule une destination sur un volume différent de `root` --
    `os.stat` renvoie un `st_dev` différent pour tout chemin dont le nom
    se termine par `destination_suffix`, même principe que l'ancien test
    « volume différent » avant que cette fonctionnalité ne soit ajoutée."""
    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if str(path).endswith(destination_suffix):

            # `move.os` est le module `os` global : ce faux `stat` est aussi
            # vu par `os.path.exists`/`os.makedirs`, qui lisent `st_mode`
            # (Python 3.11) -- tout attribut autre que `st_dev` est donc
            # délégué au vrai résultat.
            class FakeStat:
                st_dev = result.st_dev + 1

                def __getattr__(self, name):
                    return getattr(result, name)

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

    real_copyfile = __import__("shutil").copyfile

    def truncating_copyfile(src, dst, *args, **kwargs):
        real_copyfile(src, dst, *args, **kwargs)
        # Simule une copie interrompue/tronquée : le fichier temporaire
        # existe mais avec une taille différente de la source.
        with open(dst, "wb") as handle:
            handle.write(b"x" * 10)

    monkeypatch.setattr("r36s_studio.doublons.move.shutil.copyfile", truncating_copyfile)

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

    def failing_copyfile(src, dst, *args, **kwargs):
        # Écrit un fragment puis échoue -- imite une coupure en cours de
        # copie plutôt qu'un échec avant la moindre écriture.
        with open(dst, "wb") as handle:
            handle.write(b"partiel")
        raise OSError("coupure simulée")

    monkeypatch.setattr("r36s_studio.doublons.move.shutil.copyfile", failing_copyfile)

    # Signalé explicitement (point 3) : une erreur système réelle pendant
    # la copie est désormais enveloppée dans `MoveFileFailed` (fichier en
    # cause, étape, raison traduite) plutôt qu'une `OSError` brute.
    with pytest.raises(MoveFileFailed) as exc_info:
        move_duplicates(str(root), [unit], destination=str(destination))
    assert exc_info.value.step == "copy"
    assert exc_info.value.path == str(game)

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


# --- Échec réel signalé : jamais de nouvelle analyse, fichier/étape/raison
# affichés, proposer d'ignorer et continuer (§ demandé explicitement) -----


def test_move_duplicates_wraps_a_real_os_error_as_move_file_failed(tmp_path):
    root = tmp_path / "root"
    game = root / "Game.zip"
    unit = _single_file_unit(game, b"x" * 10)

    def failing_move(src, dst, *args, **kwargs):
        raise OSError(13, "Access denied")

    import r36s_studio.doublons.move as move_module

    real_move = move_module.shutil.move
    move_module.shutil.move = failing_move
    try:
        with pytest.raises(MoveFileFailed) as exc_info:
            move_duplicates(str(root), [unit])
    finally:
        move_module.shutil.move = real_move

    assert exc_info.value.step == "rename"
    assert exc_info.value.path == str(game)
    assert exc_info.value.reason == "access_denied"
    assert game.exists()  # jamais touchée -- l'échec précède tout déplacement réel


def test_move_duplicates_attaches_moved_units_to_a_hard_abort(tmp_path, monkeypatch):
    root = tmp_path / "root"
    unit_a = _single_file_unit(root / "A.zip", b"a" * 10)
    unit_b = _single_file_unit(root / "B.zip", b"b" * 10)

    real_move = __import__("shutil").move

    def failing_move(src, dst, *args, **kwargs):
        if "B.zip" in str(src):
            raise OSError(13, "Access denied")
        return real_move(src, dst, *args, **kwargs)

    monkeypatch.setattr("r36s_studio.doublons.move.shutil.move", failing_move)

    with pytest.raises(MoveFileFailed) as exc_info:
        move_duplicates(str(root), [unit_a, unit_b])

    # § bug corrigé, demandé explicitement : l'appelant doit pouvoir
    # retirer du résultat affiché ce qui a réellement bougé, sans jamais
    # relancer une analyse complète.
    assert exc_info.value.moved_units == [unit_a]
    assert (root / "_doublons" / "A.zip").exists()
    assert not (root / "_doublons" / "B.zip").exists()


def test_move_duplicates_cancel_attaches_moved_units(tmp_path):
    root = tmp_path / "root"
    unit_a = _single_file_unit(root / "A.zip", b"a" * 10)
    unit_b = _single_file_unit(root / "B.zip", b"b" * 10)

    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 1  # laisse passer la première unité, annule avant la deuxième

    with pytest.raises(MoveCancelled) as exc_info:
        move_duplicates(str(root), [unit_a, unit_b], should_cancel=should_cancel)

    assert exc_info.value.moved_units == [unit_a]


def test_move_duplicates_skips_failed_unit_and_continues_when_on_file_error_returns_true(tmp_path, monkeypatch):
    root = tmp_path / "root"
    unit_a = _single_file_unit(root / "A.zip", b"a" * 10)
    unit_b = _single_file_unit(root / "B.zip", b"b" * 10)
    unit_c = _single_file_unit(root / "C.zip", b"c" * 10)

    real_move = __import__("shutil").move

    def failing_move(src, dst, *args, **kwargs):
        if "B.zip" in str(src):
            raise OSError(13, "Access denied")
        return real_move(src, dst, *args, **kwargs)

    monkeypatch.setattr("r36s_studio.doublons.move.shutil.move", failing_move)

    seen = []

    def on_file_error(exc):
        seen.append(exc)
        return True  # § demandé : ignorer ce fichier et continuer

    with pytest.raises(PartialMoveFailure) as exc_info:
        move_duplicates(str(root), [unit_a, unit_b, unit_c], on_file_error=on_file_error)

    assert len(seen) == 1
    assert seen[0].path == str(root / "B.zip")
    failure = exc_info.value
    assert failure.moved_units == [unit_a, unit_c]
    assert failure.moved_count == 2
    assert failure.skipped[0][0] is unit_b
    assert (root / "_doublons" / "A.zip").exists()
    assert (root / "_doublons" / "C.zip").exists()
    assert not (root / "_doublons" / "B.zip").exists()
    assert (root / "B.zip").exists()  # jamais supprimée puisque jamais déplacée


def test_move_duplicates_on_file_error_returning_false_aborts_like_no_callback(tmp_path, monkeypatch):
    root = tmp_path / "root"
    unit = _single_file_unit(root / "B.zip", b"b" * 10)

    def failing_move(src, dst, *args, **kwargs):
        raise OSError(13, "Access denied")

    monkeypatch.setattr("r36s_studio.doublons.move.shutil.move", failing_move)

    with pytest.raises(MoveFileFailed):
        move_duplicates(str(root), [unit], on_file_error=lambda exc: False)


def test_move_duplicates_cross_volume_reports_copy_succeeded_when_only_delete_fails(tmp_path, monkeypatch):
    """§ demandé explicitement : « si la copie a réussi mais pas la
    suppression de l'original, le dire explicitement »."""
    _make_cross_volume(monkeypatch, destination_suffix="backup")
    root = tmp_path / "root"
    destination = tmp_path / "backup"
    destination.mkdir()
    game = root / "Game.zip"
    unit = _single_file_unit(game, b"x" * 100)

    real_unlink = os.unlink

    def failing_unlink(path, *args, **kwargs):
        if str(path).endswith("Game.zip") and "backup" not in str(path):
            raise OSError(13, "Access denied")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr("r36s_studio.doublons.move.os.unlink", failing_unlink)

    with pytest.raises(MoveFileFailed) as exc_info:
        move_duplicates(str(root), [unit], destination=str(destination))

    assert exc_info.value.step == "delete_source"
    assert exc_info.value.copy_succeeded is True
    # La copie déjà vérifiée n'est jamais perdue pour "annuler" cet échec.
    assert (destination / "Game.zip").read_bytes() == b"x" * 100
    assert game.exists()  # l'original reste, faute d'avoir pu être supprimé


def test_move_duplicates_cross_volume_ignores_a_copystat_failure(tmp_path, monkeypatch):
    """§ demandé explicitement, point 5 : ignorer les erreurs de copie des
    métadonnées (copystat) qui ne concernent pas le contenu."""
    _make_cross_volume(monkeypatch, destination_suffix="backup")
    root = tmp_path / "root"
    destination = tmp_path / "backup"
    game = root / "Game.zip"
    unit = _single_file_unit(game, b"x" * 100)

    def failing_copystat(*args, **kwargs):
        raise OSError("métadonnées non supportées (FAT)")

    monkeypatch.setattr("r36s_studio.doublons.move.shutil.copystat", failing_copystat)

    moved = move_duplicates(str(root), [unit], destination=str(destination))

    assert moved == 1
    assert (destination / "Game.zip").read_bytes() == b"x" * 100
    assert not game.exists()


def test_move_file_failure_is_logged(tmp_path, monkeypatch):
    """§ demandé explicitement, point 2 : journaliser l'exception exacte,
    l'étape en cause et le chemin complet du fichier."""
    from r36s_studio.gui import logs as gui_logs

    root = tmp_path / "root"
    unit = _single_file_unit(root / "Game.zip", b"x" * 10)

    def failing_move(src, dst, *args, **kwargs):
        raise OSError(13, "Access denied")

    monkeypatch.setattr("r36s_studio.doublons.move.shutil.move", failing_move)

    with pytest.raises(MoveFileFailed):
        move_duplicates(str(root), [unit])

    log_content = gui_logs.doublons_log_path().read_text(encoding="utf-8")
    assert "étape=rename" in log_content
    assert "raison=access_denied" in log_content
    assert str(root / "Game.zip") in log_content


# --- Traduction des erreurs système (§ demandé explicitement, point 3) ----


def test_classify_os_error_maps_known_errnos():
    from r36s_studio.doublons import move as move_module

    def make(errno_value):
        exc = OSError()
        exc.errno = errno_value
        return exc

    assert move_module._classify_os_error(make(errno.EACCES)) == move_module.REASON_ACCESS_DENIED
    assert move_module._classify_os_error(make(errno.EPERM)) == move_module.REASON_ACCESS_DENIED
    assert move_module._classify_os_error(make(errno.EROFS)) == move_module.REASON_READ_ONLY
    assert move_module._classify_os_error(make(errno.ENOSPC)) == move_module.REASON_INSUFFICIENT_SPACE
    assert move_module._classify_os_error(make(errno.ENAMETOOLONG)) == move_module.REASON_PATH_TOO_LONG
    assert move_module._classify_os_error(make(errno.EIO)) == move_module.REASON_DRIVE_REMOVED
    assert move_module._classify_os_error(make(999999)) == move_module.REASON_UNKNOWN


def test_classify_os_error_uses_winerror_when_present():
    from r36s_studio.doublons import move as move_module

    exc = OSError()
    exc.errno = None
    exc.winerror = 21  # ERROR_NOT_READY
    assert move_module._classify_os_error(exc) == move_module.REASON_DRIVE_REMOVED


# --- Chemins longs Windows, préfixe \\?\ (§ demandé explicitement, point 5) --


def test_long_path_str_prefixes_windows_paths(tmp_path, monkeypatch):
    monkeypatch.setattr("r36s_studio.doublons.move.platform.system", lambda: "Windows")
    from r36s_studio.doublons import move as move_module

    target = tmp_path / "Game.zip"
    result = move_module._long_path_str(target)

    assert result.startswith("\\\\?\\")
    assert result.endswith("Game.zip")


def test_long_path_str_unchanged_outside_windows(tmp_path, monkeypatch):
    monkeypatch.setattr("r36s_studio.doublons.move.platform.system", lambda: "Linux")
    from r36s_studio.doublons import move as move_module

    target = tmp_path / "Game.zip"
    result = move_module._long_path_str(target)

    assert not result.startswith("\\\\?\\")
    assert result == str(target)


# --- Limite FAT, 4 Gio par fichier (§ demandé explicitement, point 6) ------


def test_is_fat_filesystem_recognizes_known_names():
    assert is_fat_filesystem("FAT32") is True
    assert is_fat_filesystem("vfat") is True
    assert is_fat_filesystem(" FAT16 ") is True
    assert is_fat_filesystem("NTFS") is False
    assert is_fat_filesystem("exFAT") is False  # pas la même limite
    assert is_fat_filesystem(None) is False


def test_fat_oversized_members_flags_only_files_above_the_limit(tmp_path, monkeypatch):
    small = tmp_path / "Small.zip"
    big = tmp_path / "Big.zip"
    _touch(small, b"x")
    _touch(big, b"x")
    unit_small = _single_file_unit(small, b"x")
    unit_big = _single_file_unit(big, b"x")

    fake_sizes = {"Small.zip": 1000, "Big.zip": 2**32}
    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        for name, size in fake_sizes.items():
            if str(path).endswith(name):

                class FakeStat:
                    st_size = size

                return FakeStat()
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr("r36s_studio.doublons.move.os.stat", fake_stat)

    oversized = fat_oversized_members([unit_small, unit_big])

    assert len(oversized) == 1
    assert oversized[0][0] is unit_big
    assert oversized[0][1] == big
    assert oversized[0][2] == 2**32


def test_move_duplicates_raises_fat_file_size_limit_before_any_file_moves(tmp_path, monkeypatch):
    root = tmp_path / "root"
    small = root / "Small.zip"
    big = root / "Big.zip"
    unit_small = _single_file_unit(small, b"x" * 10)
    unit_big = _single_file_unit(big, b"x" * 10)

    monkeypatch.setattr("r36s_studio.doublons.move.destination_filesystem_kind", lambda path: "FAT32")
    monkeypatch.setattr(
        "r36s_studio.doublons.move.fat_oversized_members",
        lambda units: [(unit_big, big, 2**32)],
    )

    with pytest.raises(FatFileSizeLimitExceeded) as exc_info:
        move_duplicates(str(root), [unit_small, unit_big])

    assert exc_info.value.oversized[0][0] is unit_big
    # Refusé avant même le premier fichier -- rien n'a bougé (la sonde
    # d'écriture préalable peut créer le dossier de destination lui-même,
    # comportement déjà existant et sans rapport avec ce garde-fou précis
    # -- seul ce qui compte réellement est vérifié ici : aucun fichier
    # n'y a été copié).
    assert small.exists()
    assert big.exists()
    assert not (root / "_doublons" / "Small.zip").exists()
    assert not (root / "_doublons" / "Big.zip").exists()


def test_move_duplicates_skips_fat_check_when_filesystem_kind_is_not_fat(tmp_path, monkeypatch):
    root = tmp_path / "root"
    unit = _single_file_unit(root / "Game.zip", b"x" * 10)

    monkeypatch.setattr("r36s_studio.doublons.move.destination_filesystem_kind", lambda path: "NTFS")
    called = []
    monkeypatch.setattr(
        "r36s_studio.doublons.move.fat_oversized_members",
        lambda units: called.append(True) or [],
    )

    moved = move_duplicates(str(root), [unit])

    assert moved == 1
    # NTFS n'a pas cette limite -- la sonde par fichier n'est même pas
    # nécessaire (`is_fat_filesystem` la court-circuite avant).
    assert called == []


def test_destination_filesystem_kind_windows_uses_volume_information(tmp_path, monkeypatch):
    monkeypatch.setattr("r36s_studio.doublons.move.platform.system", lambda: "Windows")
    monkeypatch.setattr("r36s_studio.doublons.move._windows_volume_filesystem", lambda root: "FAT32")
    # Sur la CI Linux/macOS, `splitdrive` ne renvoie jamais de lecteur pour
    # un chemin POSIX : sans ce faux lecteur, la fonction s'arrêterait avant
    # même d'interroger `_windows_volume_filesystem`.
    monkeypatch.setattr("r36s_studio.doublons.move.os.path.splitdrive", lambda p: ("C:", p))

    assert destination_filesystem_kind(str(tmp_path)) == "FAT32"


def test_destination_filesystem_kind_returns_none_on_unreachable_drive(tmp_path, monkeypatch):
    monkeypatch.setattr("r36s_studio.doublons.move.platform.system", lambda: "Windows")
    monkeypatch.setattr("r36s_studio.doublons.move._windows_volume_filesystem", lambda root: None)

    assert destination_filesystem_kind(str(tmp_path)) is None


def test_destination_filesystem_kind_posix_uses_mount_parsing(tmp_path, monkeypatch):
    monkeypatch.setattr("r36s_studio.doublons.move.platform.system", lambda: "Linux")
    monkeypatch.setattr("r36s_studio.doublons.move._posix_mount_filesystem", lambda target: "vfat")

    assert destination_filesystem_kind(str(tmp_path)) == "vfat"


def test_posix_mount_filesystem_parses_macos_style_output(monkeypatch):
    from r36s_studio.doublons import move as move_module

    class FakeResult:
        returncode = 0
        stdout = (
            "/dev/disk1s1 on / (apfs, local, journaled)\n"
            "/dev/disk2s1 on /Volumes/EASYROMS (msdos, local, nodev, nosuid, noowners)\n"
        )

    monkeypatch.setattr("r36s_studio.doublons.move.subprocess.run", lambda *a, **k: FakeResult())

    assert move_module._posix_mount_filesystem("/Volumes/EASYROMS") == "msdos"
    assert move_module._posix_mount_filesystem("/Volumes/EASYROMS/sub/dir") == "msdos"
    # Aucun point de montage plus spécifique -- retombe sur la racine
    # (plus long préfixe qui matche encore, comme `mount`/`findmnt`).
    assert move_module._posix_mount_filesystem("/Volumes/Other") == "apfs"


def test_posix_mount_filesystem_parses_linux_style_output(monkeypatch):
    from r36s_studio.doublons import move as move_module

    class FakeResult:
        returncode = 0
        stdout = (
            "/dev/sda1 on / type ext4 (rw,relatime)\n"
            "/dev/sdb1 on /media/user/EASYROMS type vfat (rw,nosuid,nodev,relatime)\n"
        )

    monkeypatch.setattr("r36s_studio.doublons.move.subprocess.run", lambda *a, **k: FakeResult())

    assert move_module._posix_mount_filesystem("/media/user/EASYROMS") == "vfat"


def test_posix_mount_filesystem_returns_none_when_command_fails(monkeypatch):
    from r36s_studio.doublons import move as move_module

    def raising_run(*args, **kwargs):
        raise OSError("mount introuvable")

    monkeypatch.setattr("r36s_studio.doublons.move.subprocess.run", raising_run)

    assert move_module._posix_mount_filesystem("/mnt/x") is None
