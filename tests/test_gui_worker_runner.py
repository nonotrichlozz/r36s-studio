"""Tests de WorkerRunner (gui/worker_runner.py) : traduction du fichier de
progression JSON Lines en signaux Qt, annulation coopérative, détection
d'un worker qui s'arrête sans émettre "done". `elevate.launch_elevated_worker`
est mocké — aucune élévation réelle n'est demandée."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from r36s_studio.gui.worker_runner import WorkerRunner


def _fake_process(poll_sequence):
    """`poll_sequence` : valeurs successives retournées par `.poll()`
    (None = toujours actif)."""
    process = MagicMock()
    process.poll.side_effect = poll_sequence
    return process


@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_start_builds_argv_with_worker_progress_and_cancel_files(mock_launch, qapp):
    mock_launch.return_value = _fake_process([None])
    runner = WorkerRunner(["backup", "--device", "/dev/disk3", "--output", "x.img"])

    runner.start()

    full_argv = mock_launch.call_args.args[0]
    assert full_argv[:5] == ["backup", "--device", "/dev/disk3", "--output", "x.img"]
    assert "--worker" in full_argv
    assert "--progress-file" in full_argv
    assert "--cancel-file" in full_argv
    runner._stop()


@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_dispatches_progress_log_error_done_events(mock_launch, qapp):
    mock_launch.return_value = _fake_process([None] * 10)
    runner = WorkerRunner(["backup", "--device", "/dev/disk3", "--output", "x.img"])
    runner.start()

    progress_events = []
    log_events = []
    error_events = []
    finished_events = []
    runner.progress.connect(lambda *a: progress_events.append(a))
    runner.log.connect(lambda *a: log_events.append(a))
    runner.error.connect(lambda *a: error_events.append(a))
    runner.finished.connect(lambda ok: finished_events.append(ok))

    _write_events(
        runner._progress_file,
        [
            {"type": "log", "level": "info", "msg": "démarrage"},
            {"type": "progress", "done": 10, "total": 100, "speed": 5.0},
            {"type": "error", "code": "IO_ERROR", "msg": "boom"},
            {"type": "done", "ok": False},
        ],
    )

    runner._poll()

    assert log_events == [("info", "démarrage")]
    assert progress_events == [(10, 100, 5.0)]
    assert error_events == [("IO_ERROR", "boom")]
    assert finished_events == [False]


@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_cancel_file_does_not_exist_until_cancel_is_called(mock_launch, qapp):
    """Le fichier d'annulation ne doit PAS exister dès `start()` : le
    worker le détecte via `os.path.exists()` (voir `_make_should_cancel`
    dans `__main__.py`) -- s'il existait déjà, l'opération s'annulerait
    immédiatement."""
    mock_launch.return_value = _fake_process([None])
    runner = WorkerRunner(["backup", "--device", "/dev/disk3", "--output", "x.img"])
    runner.start()

    assert not runner._cancel_file.exists()

    runner.cancel()

    assert runner._cancel_file.exists()
    runner._stop()


@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_process_exit_without_done_reports_elevation_failed(mock_launch, qapp):
    # Le process (osascript/pkexec) se termine (poll() != None) sans qu'un
    # événement "done" n'ait été écrit -- élévation refusée par exemple.
    mock_launch.return_value = _fake_process([1])
    runner = WorkerRunner(["backup", "--device", "/dev/disk3", "--output", "x.img"])
    runner.start()

    error_events = []
    finished_events = []
    runner.error.connect(lambda *a: error_events.append(a))
    runner.finished.connect(lambda ok: finished_events.append(ok))

    runner._poll()

    assert error_events and error_events[0][0] == "ELEVATION_FAILED"
    assert finished_events == [False]


@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_process_exit_with_done_already_emitted_does_not_double_report(mock_launch, qapp):
    mock_launch.return_value = _fake_process([1])
    runner = WorkerRunner(["backup", "--device", "/dev/disk3", "--output", "x.img"])
    runner.start()

    finished_events = []
    error_events = []
    runner.finished.connect(lambda ok: finished_events.append(ok))
    runner.error.connect(lambda *a: error_events.append(a))

    _write_events(runner._progress_file, [{"type": "done", "ok": True}])

    runner._poll()

    assert finished_events == [True]
    assert error_events == []  # pas de faux "ELEVATION_FAILED" en plus


@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_stop_removes_progress_and_cancel_files(mock_launch, qapp):
    mock_launch.return_value = _fake_process([None])
    runner = WorkerRunner(["backup", "--device", "/dev/disk3", "--output", "x.img"])
    runner.start()
    progress_file, cancel_file = runner._progress_file, runner._cancel_file

    runner._stop()

    assert not progress_file.exists()
    assert not cancel_file.exists()


def _write_events(path, events):
    with open(path, "a", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
