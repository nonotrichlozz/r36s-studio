"""Tests de WorkerRunner (gui/worker_runner.py) : traduction du fichier de
progression JSON Lines en signaux Qt, annulation coopérative, détection
d'un worker qui s'arrête sans émettre "done" (avec remontée du contenu du
journal d'élévation). `elevate.launch_elevated_worker` est mocké — aucune
élévation réelle n'est demandée. `logs.elevation_log_path` est aussi mocké
sur un chemin `tmp_path` : sans ça, chaque test créerait pour de vrai
`~/.config/r36s-studio/logs/` sur la machine qui exécute la suite."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from r36s_studio.gui.worker_runner import MACOS_TCC_BLOCKED, WorkerRunner


def _fake_process(poll_sequence):
    """`poll_sequence` : valeurs successives retournées par `.poll()`
    (None = toujours actif)."""
    process = MagicMock()
    process.poll.side_effect = poll_sequence
    return process


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_start_builds_argv_with_worker_progress_and_cancel_files(mock_launch, mock_log_path, tmp_path, qapp):
    mock_log_path.return_value = tmp_path / "elevation.log"
    mock_launch.return_value = _fake_process([None])
    runner = WorkerRunner(["backup", "--device", "/dev/disk3", "--output", "x.img"])

    runner.start()

    full_argv = mock_launch.call_args.args[0]
    assert full_argv[:5] == ["backup", "--device", "/dev/disk3", "--output", "x.img"]
    assert "--worker" in full_argv
    assert "--progress-file" in full_argv
    assert "--cancel-file" in full_argv
    runner._stop()


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_start_passes_elevation_log_path_to_launch(mock_launch, mock_log_path, tmp_path, qapp):
    log_path = tmp_path / "elevation.log"
    mock_log_path.return_value = log_path
    mock_launch.return_value = _fake_process([None])
    runner = WorkerRunner(["backup", "--device", "/dev/disk3", "--output", "x.img"])

    runner.start()

    assert mock_launch.call_args.kwargs["stderr_log"] == log_path
    runner._stop()


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_dispatches_progress_log_error_done_events(mock_launch, mock_log_path, tmp_path, qapp):
    mock_log_path.return_value = tmp_path / "elevation.log"
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


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_cancel_file_does_not_exist_until_cancel_is_called(mock_launch, mock_log_path, tmp_path, qapp):
    """Le fichier d'annulation ne doit PAS exister dès `start()` : le
    worker le détecte via `os.path.exists()` (voir `_make_should_cancel`
    dans `__main__.py`) -- s'il existait déjà, l'opération s'annulerait
    immédiatement."""
    mock_log_path.return_value = tmp_path / "elevation.log"
    mock_launch.return_value = _fake_process([None])
    runner = WorkerRunner(["backup", "--device", "/dev/disk3", "--output", "x.img"])
    runner.start()

    assert not runner._cancel_file.exists()

    runner.cancel()

    assert runner._cancel_file.exists()
    runner._stop()


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_process_exit_without_done_reports_elevation_failed(mock_launch, mock_log_path, tmp_path, qapp):
    # Le process (osascript/pkexec) se termine (poll() != None) sans qu'un
    # événement "done" n'ait été écrit -- élévation refusée par exemple.
    mock_log_path.return_value = tmp_path / "elevation.log"
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


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_process_exit_without_done_surfaces_elevation_log_content(mock_launch, mock_log_path, tmp_path, qapp):
    """Le bug corrigé : `osascript: No module named r36s_studio` restait
    invisible derrière un message générique. Le contenu du journal
    d'élévation (stderr d'osascript/pkexec, écrit par elevate.py) doit
    maintenant apparaître dans le message d'erreur."""
    log_path = tmp_path / "elevation.log"
    log_path.write_text("python3: No module named r36s_studio\n", encoding="utf-8")
    mock_log_path.return_value = log_path
    mock_launch.return_value = _fake_process([1])
    runner = WorkerRunner(["backup", "--device", "/dev/disk3", "--output", "x.img"])
    runner.start()

    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner._poll()

    assert error_events
    code, msg = error_events[0]
    assert code == "ELEVATION_FAILED"
    assert "No module named r36s_studio" in msg


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_process_exit_without_done_and_empty_log_keeps_generic_message(mock_launch, mock_log_path, tmp_path, qapp):
    mock_log_path.return_value = tmp_path / "elevation.log"  # n'existe pas
    mock_launch.return_value = _fake_process([1])
    runner = WorkerRunner(["backup", "--device", "/dev/disk3", "--output", "x.img"])
    runner.start()

    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner._poll()

    assert error_events
    code, msg = error_events[0]
    assert code == "ELEVATION_FAILED"
    assert "annulée" in msg or "échoué" in msg


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_process_exit_with_done_already_emitted_does_not_double_report(mock_launch, mock_log_path, tmp_path, qapp):
    mock_log_path.return_value = tmp_path / "elevation.log"
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


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_stop_removes_progress_and_cancel_files_but_keeps_log(mock_launch, mock_log_path, tmp_path, qapp):
    log_path = tmp_path / "elevation.log"
    log_path.write_text("une erreur quelconque", encoding="utf-8")
    mock_log_path.return_value = log_path
    mock_launch.return_value = _fake_process([None])
    runner = WorkerRunner(["backup", "--device", "/dev/disk3", "--output", "x.img"])
    runner.start()
    progress_file, cancel_file = runner._progress_file, runner._cancel_file

    runner._stop()

    assert not progress_file.exists()
    assert not cancel_file.exists()
    assert log_path.exists()  # conservé pour inspection post-mortem


@patch("r36s_studio.gui.worker_runner.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_macos_tcc_block_produces_explicit_sudo_hint(mock_launch, mock_log_path, mock_platform, tmp_path, qapp):
    """Cas documenté dans CLAUDE.md §3 : `osascript … with administrator
    privileges` obtient les droits root mais TCC bloque quand même l'accès à
    /dev/rdiskN (aucune identité TCC pour ce processus). Ce message précis, sur
    macOS, doit produire un code dédié plutôt que l'ELEVATION_FAILED générique,
    et inviter à utiliser la ligne de commande avec `sudo`."""
    log_path = tmp_path / "elevation.log"
    log_path.write_text(
        "Operation not permitted: '/dev/rdisk4'\n",
        encoding="utf-8",
    )
    mock_log_path.return_value = log_path
    mock_launch.return_value = _fake_process([1])
    runner = WorkerRunner(["backup", "--device", "/dev/disk4", "--output", "x.img"])
    runner.start()

    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner._poll()

    assert error_events
    code, msg = error_events[0]
    assert code == MACOS_TCC_BLOCKED
    assert "sudo" in msg


@patch("r36s_studio.gui.worker_runner.platform.system", return_value="Linux")
@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_permission_denied_on_other_os_keeps_generic_elevation_failed(
    mock_launch, mock_log_path, mock_platform, tmp_path, qapp
):
    """La limitation TCC est spécifique à macOS (§3 de CLAUDE.md) : le même
    texte sur Linux/Windows ne doit pas déclencher le message dédié."""
    log_path = tmp_path / "elevation.log"
    log_path.write_text("Operation not permitted: '/dev/rdisk4'\n", encoding="utf-8")
    mock_log_path.return_value = log_path
    mock_launch.return_value = _fake_process([1])
    runner = WorkerRunner(["backup", "--device", "/dev/disk4", "--output", "x.img"])
    runner.start()

    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner._poll()

    assert error_events
    code, _ = error_events[0]
    assert code == "ELEVATION_FAILED"


def _write_events(path, events):
    with open(path, "a", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
