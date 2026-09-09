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

from PySide6.QtWidgets import QWidget

from r36s_studio.gui.worker_runner import MACOS_TCC_BLOCKED, MACOS_TCC_PROTECTED_FOLDER, WorkerRunner


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
    runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])

    runner.start()

    full_argv = mock_launch.call_args.args[0]
    assert full_argv[:5] == ["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"]
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
    runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])

    runner.start()

    assert mock_launch.call_args.kwargs["stderr_log"] == log_path
    runner._stop()


# --- réutilisation d'une session d'autorisation macOS (§5 mode assisté) ----
#
# Correctif d'un comportement observé en usage réel : le parcours guidé
# redemandait l'invite mot de passe à chaque étape élevée. `MainWindow`
# possède désormais une seule `MacosAuthorizationSession` pour toute
# l'application, passée à chaque `WorkerRunner` -- ce dernier doit en
# extraire `auth_ref` et le transmettre à `launch_elevated_worker`.


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_start_forwards_macos_auth_ref_from_session(mock_launch, mock_log_path, tmp_path, qapp):
    mock_log_path.return_value = tmp_path / "elevation.log"
    mock_launch.return_value = _fake_process([None])
    session = MagicMock()
    session.auth_ref = "fake-auth-ref"
    runner = WorkerRunner(
        ["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"], macos_auth_session=session
    )

    runner.start()

    assert mock_launch.call_args.kwargs["macos_auth_ref"] == "fake-auth-ref"
    runner._stop()


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_start_passes_none_macos_auth_ref_without_a_session(mock_launch, mock_log_path, tmp_path, qapp):
    """Comportement d'origine préservé sans session fournie (Linux/Windows,
    ou macOS en développement) : `launch_elevated_worker` reçoit `None`,
    chemin déjà géré (`osascript`/`pkexec`/UAC ne consomment aucun
    `AuthorizationRef`)."""
    mock_log_path.return_value = tmp_path / "elevation.log"
    mock_launch.return_value = _fake_process([None])
    runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])

    runner.start()

    assert mock_launch.call_args.kwargs["macos_auth_ref"] is None
    runner._stop()


# --- handle de fenêtre transmis à ShellExecuteExW (Windows) ----------------
#
# Signalé : une invite UAC pourrait rester en arrière-plan, invisible pour
# l'utilisateur (deux minutes avant l'échec observé). `ShellExecuteExW`
# recevait `hwnd=None` depuis toujours -- transmettre le handle natif du
# parent (`MainWindow`) est la pratique recommandée par Microsoft, sans
# garantie que ce soit la cause réelle (voir `_windows_parent_hwnd`).


@patch("r36s_studio.gui.worker_runner.platform.system", return_value="Windows")
@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_start_forwards_parent_window_handle_on_windows(mock_launch, mock_log_path, mock_platform, tmp_path, qapp):
    mock_log_path.return_value = tmp_path / "elevation.log"
    mock_launch.return_value = _fake_process([None])
    parent = QWidget()
    with patch.object(parent, "winId", return_value=424242):
        runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"], parent=parent)
        runner.start()

    assert mock_launch.call_args.kwargs["parent_hwnd"] == 424242
    runner._stop()


@patch("r36s_studio.gui.worker_runner.platform.system", return_value="Windows")
@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_start_parent_hwnd_is_none_without_a_parent(mock_launch, mock_log_path, mock_platform, tmp_path, qapp):
    mock_log_path.return_value = tmp_path / "elevation.log"
    mock_launch.return_value = _fake_process([None])
    runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])

    runner.start()

    assert mock_launch.call_args.kwargs["parent_hwnd"] is None
    runner._stop()


@patch("r36s_studio.gui.worker_runner.platform.system", return_value="Windows")
@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_start_parent_hwnd_falls_back_to_none_when_winid_raises(
    mock_launch, mock_log_path, mock_platform, tmp_path, qapp
):
    """Jamais un plantage si `winId()` échoue pour une raison quelconque
    (ex. widget pas encore affiché) -- comportement historique (`hwnd=None`)
    préservé dans ce cas."""
    mock_log_path.return_value = tmp_path / "elevation.log"
    mock_launch.return_value = _fake_process([None])
    parent = QWidget()
    with patch.object(parent, "winId", side_effect=RuntimeError("pas encore affiché")):
        runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"], parent=parent)
        runner.start()

    assert mock_launch.call_args.kwargs["parent_hwnd"] is None
    runner._stop()


@patch("r36s_studio.gui.worker_runner.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_start_parent_hwnd_is_none_outside_windows(mock_launch, mock_log_path, mock_platform, tmp_path, qapp):
    """`parent_hwnd` n'a de sens que pour `ShellExecuteExW` (Windows) --
    jamais calculé (ni transmis comme autre chose que `None`) sur macOS/
    Linux, ignoré de toute façon côté `elevate.py`."""
    mock_log_path.return_value = tmp_path / "elevation.log"
    mock_launch.return_value = _fake_process([None])
    parent = QWidget()
    with patch.object(parent, "winId", return_value=424242):
        runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"], parent=parent)
        runner.start()

    assert mock_launch.call_args.kwargs["parent_hwnd"] is None
    runner._stop()


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_dispatches_progress_log_error_done_events(mock_launch, mock_log_path, tmp_path, qapp):
    mock_log_path.return_value = tmp_path / "elevation.log"
    mock_launch.return_value = _fake_process([None] * 10)
    runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])
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
def test_dispatches_estimate_event(mock_launch, mock_log_path, tmp_path, qapp):
    """Repli élevé pour l'estimation de la sauvegarde système sans les
    jeux (§4.3, `backup --system-only --estimate-only`)."""
    mock_log_path.return_value = tmp_path / "elevation.log"
    mock_launch.return_value = _fake_process([None] * 5)
    runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--system-only", "--estimate-only"])
    runner.start()

    estimate_events = []
    runner.estimate.connect(lambda size: estimate_events.append(size))

    _write_events(runner._progress_file, [{"type": "estimate", "size_bytes": 9_000_000_000}])
    runner._poll()

    assert estimate_events == [9_000_000_000]


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_cancel_file_does_not_exist_until_cancel_is_called(mock_launch, mock_log_path, tmp_path, qapp):
    """Le fichier d'annulation ne doit PAS exister dès `start()` : le
    worker le détecte via `os.path.exists()` (voir `_make_should_cancel`
    dans `__main__.py`) -- s'il existait déjà, l'opération s'annulerait
    immédiatement."""
    mock_log_path.return_value = tmp_path / "elevation.log"
    mock_launch.return_value = _fake_process([None])
    runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])
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
    runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])
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
    runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])
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
    runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])
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
    runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])
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
def test_process_exit_after_real_error_without_done_does_not_overwrite_with_elevation_failed(
    mock_launch, mock_log_path, tmp_path, qapp
):
    """Bug corrigé, confirmé sur du vrai matériel : le worker élevé émettait
    bien un vrai code d'erreur (ex. GAMES_PARTITION_NOT_FOUND -- une carte
    cible sans partition de jeux, refus légitime) dans le fichier de
    progression, puis se terminait sans jamais écrire "done" (de nombreux
    chemins d'erreur de __main__.py ne le font pas). Sur Windows,
    `ShellExecuteW` ne fournit aucun tube stdout/stderr : sans ce
    correctif, ce vrai code disparaissait, remplacé par un `ELEVATION_
    FAILED` générique et trompeur dès que le process élevé se terminait."""
    mock_log_path.return_value = tmp_path / "elevation.log"  # n'existe pas
    mock_launch.return_value = _fake_process([None, 1])
    runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])
    runner.start()

    error_events = []
    finished_events = []
    runner.error.connect(lambda *a: error_events.append(a))
    runner.finished.connect(lambda ok: finished_events.append(ok))

    # Le worker écrit un vrai événement d'erreur puis meurt sans "done".
    _write_events(runner._progress_file, [{"type": "error", "code": "GAMES_PARTITION_NOT_FOUND", "msg": "..."}])
    runner._poll()  # process encore actif (poll() -> None) : lit l'erreur
    runner._poll()  # process terminé (poll() -> 1) : ne doit pas l'écraser

    assert error_events == [("GAMES_PARTITION_NOT_FOUND", "...")]
    assert finished_events == [False]


@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_stop_removes_progress_and_cancel_files_but_keeps_log(mock_launch, mock_log_path, tmp_path, qapp):
    log_path = tmp_path / "elevation.log"
    log_path.write_text("une erreur quelconque", encoding="utf-8")
    mock_log_path.return_value = log_path
    mock_launch.return_value = _fake_process([None])
    runner = WorkerRunner(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])
    runner.start()
    progress_file, cancel_file = runner._progress_file, runner._cancel_file

    runner._stop()

    assert not progress_file.exists()
    assert not cancel_file.exists()
    assert log_path.exists()  # conservé pour inspection post-mortem


@patch("r36s_studio.gui.worker_runner.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_macos_tcc_block_produces_explicit_full_disk_access_hint(mock_launch, mock_log_path, mock_platform, tmp_path, qapp):
    """Cas documenté dans CLAUDE.md §3 : ce message précis, sur macOS, doit
    produire un code dédié plutôt que l'ELEVATION_FAILED générique. Depuis la
    résolution phase 7 (élévation directe depuis le binaire du bundle, sans
    passer par `osascript`), ce cas signifie que l'app n'a pas -- ou plus,
    après une reconstruction qui change sa signature -- la permission Accès
    complet au disque : le message doit inviter à l'accorder, pas à utiliser
    `sudo` en ligne de commande (qui ne résout plus rien pour ce cas précis)."""
    log_path = tmp_path / "elevation.log"
    log_path.write_text(
        "Operation not permitted: '/dev/rdisk9904'\n",
        encoding="utf-8",
    )
    mock_log_path.return_value = log_path
    mock_launch.return_value = _fake_process([1])
    runner = WorkerRunner(["backup", "--device", "/dev/disk9904", "--output", "x.img"])
    runner.start()

    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner._poll()

    assert error_events
    code, msg = error_events[0]
    assert code == MACOS_TCC_BLOCKED
    assert "Accès complet au disque" in msg
    assert "sudo" not in msg


@patch("r36s_studio.gui.worker_runner.platform.system", return_value="Linux")
@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_permission_denied_on_other_os_keeps_generic_elevation_failed(
    mock_launch, mock_log_path, mock_platform, tmp_path, qapp
):
    """La limitation TCC est spécifique à macOS (§3 de CLAUDE.md) : le même
    texte sur Linux/Windows ne doit pas déclencher le message dédié."""
    log_path = tmp_path / "elevation.log"
    log_path.write_text("Operation not permitted: '/dev/rdisk9904'\n", encoding="utf-8")
    mock_log_path.return_value = log_path
    mock_launch.return_value = _fake_process([1])
    runner = WorkerRunner(["backup", "--device", "/dev/disk9904", "--output", "x.img"])
    runner.start()

    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner._poll()

    assert error_events
    code, _ = error_events[0]
    assert code == "ELEVATION_FAILED"


@patch("r36s_studio.gui.worker_runner.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_macos_tcc_protected_downloads_folder_produces_distinct_move_file_hint(
    mock_launch, mock_log_path, mock_platform, tmp_path, qapp
):
    """Cas réel rapporté : `[Errno 1] Operation not permitted` survient
    aussi sur un fichier ordinaire (l'image à flasher) situé dans
    Téléchargements -- distinct du blocage /dev/rdiskN, et devant produire
    un message différent invitant à déplacer le fichier."""
    log_path = tmp_path / "elevation.log"
    log_path.write_text(
        "[IO_ERROR] [Errno 1] Operation not permitted: "
        "'/Users/proprio/Downloads/ArkOS_r36s_20250523.img.xz'\n",
        encoding="utf-8",
    )
    mock_log_path.return_value = log_path
    mock_launch.return_value = _fake_process([1])
    runner = WorkerRunner(["flash", "--image", "x.img.xz", "--device", "/dev/disk9904"])
    runner.start()

    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner._poll()

    assert error_events
    code, msg = error_events[0]
    assert code == MACOS_TCC_PROTECTED_FOLDER
    assert "déplace" in msg.lower()


@patch("r36s_studio.gui.worker_runner.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_macos_tcc_protected_desktop_subfolder_is_detected(
    mock_launch, mock_log_path, mock_platform, tmp_path, qapp
):
    """Deuxième cas réel rapporté : le fichier n'est pas directement à la
    racine de Bureau, mais dans un sous-dossier -- doit être détecté
    quand même."""
    log_path = tmp_path / "elevation.log"
    log_path.write_text(
        "[IO_ERROR] [Errno 1] Operation not permitted: "
        "'/Users/proprio/Desktop/r36s/ArkOS_r36s_20250523.img.xz'\n",
        encoding="utf-8",
    )
    mock_log_path.return_value = log_path
    mock_launch.return_value = _fake_process([1])
    runner = WorkerRunner(["flash", "--image", "x.img.xz", "--device", "/dev/disk9904"])
    runner.start()

    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner._poll()

    assert error_events[0][0] == MACOS_TCC_PROTECTED_FOLDER


@patch("r36s_studio.gui.worker_runner.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_macos_tcc_protected_documents_folder_is_detected(
    mock_launch, mock_log_path, mock_platform, tmp_path, qapp
):
    log_path = tmp_path / "elevation.log"
    log_path.write_text(
        "[Errno 1] Operation not permitted: '/Users/proprio/Documents/ArkOS.img.xz'\n",
        encoding="utf-8",
    )
    mock_log_path.return_value = log_path
    mock_launch.return_value = _fake_process([1])
    runner = WorkerRunner(["flash", "--image", "x.img.xz", "--device", "/dev/disk9904"])
    runner.start()

    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner._poll()

    assert error_events[0][0] == MACOS_TCC_PROTECTED_FOLDER


@patch("r36s_studio.gui.worker_runner.platform.system", return_value="Linux")
@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_macos_tcc_protected_folder_is_macos_only(mock_launch, mock_log_path, mock_platform, tmp_path, qapp):
    """Même texte, même chemin, mais pas macOS : ce blocage TCC n'existe
    pas ailleurs -- doit rester un ELEVATION_FAILED générique."""
    log_path = tmp_path / "elevation.log"
    log_path.write_text(
        "[Errno 1] Operation not permitted: '/home/x/Downloads/ArkOS.img.xz'\n",
        encoding="utf-8",
    )
    mock_log_path.return_value = log_path
    mock_launch.return_value = _fake_process([1])
    runner = WorkerRunner(["flash", "--image", "x.img.xz", "--device", "/dev/sdb"])
    runner.start()

    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner._poll()

    assert error_events[0][0] == "ELEVATION_FAILED"


@patch("r36s_studio.gui.worker_runner.platform.system", return_value="Darwin")
@patch("r36s_studio.gui.worker_runner.logs.elevation_log_path")
@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
def test_macos_rdisk_block_takes_priority_over_protected_folder_check(
    mock_launch, mock_log_path, mock_platform, tmp_path, qapp
):
    """Un chemin /dev/rdiskN ne contient aucun des trois noms de dossier
    protégés -- les deux détections restent mutuellement exclusives en
    pratique, mais on vérifie explicitement que le cas historique n'a pas
    régressé."""
    log_path = tmp_path / "elevation.log"
    log_path.write_text("Operation not permitted: '/dev/rdisk9904'\n", encoding="utf-8")
    mock_log_path.return_value = log_path
    mock_launch.return_value = _fake_process([1])
    runner = WorkerRunner(["backup", "--device", "/dev/disk9904", "--output", "x.img"])
    runner.start()

    error_events = []
    runner.error.connect(lambda *a: error_events.append(a))

    runner._poll()

    assert error_events[0][0] == MACOS_TCC_BLOCKED


def _write_events(path, events):
    with open(path, "a", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event) + "\n")
