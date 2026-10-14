"""Politique « une fenêtre par fichier en échec » (signalé : un millier de
fenêtres) -- case « appliquer aux suivants » et arrêt des questions après
`AUTO_SKIP_AFTER` échecs de même raison."""

import threading
from unittest.mock import patch

from r36s_studio.doublons.move import MoveFileFailed
from r36s_studio.gui.doublons_runner import AUTO_SKIP_AFTER, DoublonsMoveRunner


def _run_with_failures(reasons, answer):
    """Simule `move_duplicates` qui échoue une fois par raison de `reasons` ;
    `answer(runner)` répond à chaque fenêtre. Rend (questions, retours)."""
    runner = DoublonsMoveRunner("/dev/fake-disk-test-root", [], dry_run=False)
    asked, returns = [], []

    def ask(exc):
        asked.append(exc.reason)
        threading.Thread(target=answer, args=(runner,)).start()

    runner.file_error_confirmation_needed.connect(ask)

    def fake_move(*_args, on_file_error, **_kwargs):
        for reason in reasons:
            returns.append(on_file_error(MoveFileFailed("p", "copy", reason, "d")))
        return 0

    with patch("r36s_studio.gui.doublons_runner.move_duplicates", fake_move):
        runner.run()
    return asked, returns


def test_stops_asking_after_identical_failures(qapp):
    asked, returns = _run_with_failures(
        ["source_missing"] * 10 + ["access_denied"],
        lambda r: r.resume_after_file_error_confirmation(True),
    )
    assert asked == ["source_missing"] * AUTO_SKIP_AFTER + ["access_denied"]
    assert all(returns)


def test_apply_to_following_never_asks_again(qapp):
    asked, returns = _run_with_failures(
        ["source_missing", "access_denied", "unknown"],
        lambda r: r.resume_after_file_error_confirmation(True, True),
    )
    assert asked == ["source_missing"]
    assert all(returns)


def test_cancel_choice_still_stops(qapp):
    asked, returns = _run_with_failures(
        ["source_missing"],
        lambda r: r.resume_after_file_error_confirmation(False, True),
    )
    assert returns == [False]
