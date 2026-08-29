"""Tests de navigation de MainWindow (gui/main_window.py, §5 refonte
navigation) : une seule vue permanente (deux colonnes) devant laquelle les
choix ponctuels s'ouvrent en fenêtres modales, plutôt qu'une succession
d'écrans. Traverse le parcours de bout en bout pour les six étapes du
workflow à deux cartes (§4.4/§4.5) et la sauvegarde complète. `list_devices`,
`detect_workflow_status`, `WorkerRunner`/`PartitionJobRunner`, `archives` et
`eject_device` sont mockés — aucun périphérique réel, aucune élévation,
aucune écriture disque."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from r36s_studio.config import AppConfig
from r36s_studio.detect import StepStatus
from r36s_studio.devices import Device
from r36s_studio.gui.main_window import MainWindow
from r36s_studio.gui.worker_runner import WorkerRunner
from r36s_studio.imaging.copy import ProgressEvent

# La plupart des tests de ce fichier portent sur le parcours à six étapes
# (mode expert) -- `_EXPERT_MODE_CONFIG` démarre `MainWindow` directement
# sur `HomeScreen` plutôt que sur l'accueil du mode assisté (§5 mode
# assisté, par défaut sinon), pour ne pas changer le sens de tests déjà
# en place. Les tests du mode assisté lui-même (plus bas) repatchent
# `app_config.load_config` explicitement selon leurs besoins.
_EXPERT_MODE_CONFIG = AppConfig(ui_mode="expert")


def _make_device(path="/dev/fake-disk-test-3", size_bytes=32_000_000_000, display="Carte SD factice") -> Device:
    return Device(
        path=path,
        display=display,
        size_bytes=size_bytes,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=[],
    )


def _all_status(value: StepStatus) -> dict:
    return {
        "extract_boot": value,
        "extract_easyroms": value,
        "flash": value,
        "inject_boot": value,
        "copy_games": value,
        "eject": value,
    }


def _mock_runner_class():
    """Fabrique une classe de substitution pour WorkerRunner : chaque
    instance créée est un MagicMock enregistré dans `.instances` pour
    inspection, avec de vrais attributs Signal-like (mockés) sur lesquels
    `.connect()` fonctionne sans effet."""
    instances = []

    def _factory(argv, parent=None):
        instance = MagicMock()
        instance.argv = argv
        instances.append(instance)
        return instance

    factory = MagicMock(side_effect=_factory)
    factory.instances = instances
    return factory


def _mock_partition_runner_class():
    """Même principe que `_mock_runner_class`, pour `PartitionJobRunner`
    (mode, device, source_path positionnels)."""
    instances = []

    def _factory(mode, device, source_path, parent=None):
        instance = MagicMock()
        instance.mode = mode
        instance.device = device
        instance.source_path = source_path
        instances.append(instance)
        return instance

    factory = MagicMock(side_effect=_factory)
    factory.instances = instances
    return factory


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_flow_reaches_worker_with_correct_argv(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window = MainWindow()
        window._home.backup_selected.emit()

        assert window._device_dialog.isVisible() is True
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

        assert window._device_dialog.isVisible() is False  # fermée par MainWindow après le choix
        assert window._file_dialog.isVisible() is True

        with patch("r36s_studio.gui.screens.QFileDialog.getSaveFileName", return_value=("/tmp/out.img", "")):
            window._file_dialog._browse()
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

        # Backup n'écrit jamais sur un périphérique : pas de fenêtre de
        # confirmation, l'opération démarre directement.
        assert window._file_dialog.isVisible() is False
        assert window._confirm_dialog.isVisible() is False

    runner_class.assert_called_once()
    argv = runner_class.instances[0].argv
    assert argv == ["backup", "--device", "/dev/fake-disk-test-3", "--output", "/tmp/out.img"]
    runner_class.instances[0].start.assert_called_once()
    assert window._home._backup_row.isEnabled() is False  # occupé pendant l'opération


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_flash_flow_requires_confirmation_before_worker_starts(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window = MainWindow()
        window._home.flash_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

        with patch(
            "r36s_studio.gui.screens.QFileDialog.getOpenFileName", return_value=("/tmp/sd.img", "")
        ):
            window._file_dialog._browse()
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

        # Le flash écrit sur le périphérique : confirmation obligatoire.
        assert window._confirm_dialog.isVisible() is True
        runner_class.assert_not_called()

        window._confirm_dialog._checkbox.setChecked(True)
        window._confirm_dialog.confirmed.emit()

        assert window._confirm_dialog.isVisible() is False

    argv = runner_class.instances[0].argv
    assert argv == ["flash", "--image", "/tmp/sd.img", "--device", "/dev/fake-disk-test-3"]


@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_confirm_dialog_cancel_never_starts_the_worker(mock_list, mock_filter, mock_detect, qapp):
    """Annuler ferme simplement la fenêtre de confirmation (§5, refonte
    navigation) -- plus de retour à une fenêtre Fichier chaînée, juste un
    abandon qui laisse la vue principale inchangée derrière."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window = MainWindow()
        window._home.flash_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()
        window._file_dialog.file_chosen.emit("/tmp/sd.img")
        assert window._confirm_dialog.isVisible() is True

        window._confirm_dialog.close()

    assert window._confirm_dialog.isVisible() is False
    runner_class.assert_not_called()


# --- câblage réel signal/slot, pas un WorkerRunner mocké --------------------
#
# Toutes les autres traversées du flash/backup passent par `_mock_runner_class`
# (un `MagicMock`) : `.progress` y est lui-même un `MagicMock`, donc
# `.connect(...)` ne fait qu'enregistrer un appel -- aucun signal Qt réel
# n'est jamais émis. Une régression du câblage (mauvais nom de méthode,
# signature de slot qui ne correspond plus au signal, connexion oubliée)
# passerait entièrement inaperçue dans ces tests. Celui-ci utilise un vrai
# `WorkerRunner` (vrai `QObject`, vrai `Signal("qint64", "qint64", float)`)
# et vérifie que le journal de bord de `MainWindow` se met à jour quand ce
# signal est réellement émis -- seule `elevate.launch_elevated_worker` est
# mockée, pour ne lancer aucune élévation ni sous-processus réel.


@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_flash_progress_reaches_log_panel_through_real_worker_runner(
    mock_list, mock_filter, mock_detect, mock_launch, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_launch.return_value = MagicMock(poll=MagicMock(return_value=None))

    window = MainWindow()
    window._home.flash_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    window._device_dialog._emit_chosen()

    with patch("r36s_studio.gui.screens.QFileDialog.getOpenFileName", return_value=("/tmp/sd.img", "")):
        window._file_dialog._browse()
    window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    window._confirm_dialog._checkbox.setChecked(True)
    window._confirm_dialog.confirmed.emit()

    assert isinstance(window._runner, WorkerRunner)  # pas un mock : le vrai câblage Qt est en jeu
    assert window._home._tiles["flash"].isEnabled() is False  # occupé pendant l'opération

    window._runner.progress.emit(50, 200, 12_000_000.0)

    assert window._log_panel._bar.value() == 25  # 50/200 = 25 %
    assert "12.0" in window._log_panel._speed_label.text()


# --- bug corrigé : débordement d'entier 32 bits sur les tailles en octets --
#
# Constaté en conditions réelles (flash d'une carte de 32 Go) : `Signal(int,
# int, float)` mappe `int` sur un entier C++ 32 bits (~2,1 milliards max),
# dépassé par n'importe quel compte d'octets au-delà de 2 Go. PySide6 ne
# lève alors aucune exception Python -- il échoue silencieusement à livrer
# le signal (`libshiboken: Overflow`, `OverflowError` côté C++), ce qui se
# manifestait côté GUI par le message trompeur `AttributeError: Slot
# '...(int,int,double)' not found`, comme si le slot n'existait pas. Les
# tests précédents (50, 200 octets) ne pouvaient pas l'attraper : trop
# petits pour dépasser 2^31. Corrigé en déclarant `Signal("qint64",
# "qint64", float)` (`worker_runner.py`/`partition_runner.py`) et le
# `@Slot` assorti sur `MainWindow._on_progress`.


@patch("r36s_studio.gui.worker_runner.elevate.launch_elevated_worker")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_flash_progress_survives_byte_counts_beyond_32_bit_int(
    mock_list, mock_filter, mock_detect, mock_launch, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_launch.return_value = MagicMock(poll=MagicMock(return_value=None))

    window = MainWindow()
    window._home.flash_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    window._device_dialog._emit_chosen()

    with patch("r36s_studio.gui.screens.QFileDialog.getOpenFileName", return_value=("/tmp/sd.img", "")):
        window._file_dialog._browse()
    window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    window._confirm_dialog._checkbox.setChecked(True)
    window._confirm_dialog.confirmed.emit()

    total_32gb = 34_359_738_368  # 32 Go, très au-delà de 2**31 - 1 (~2,1 milliards)
    assert total_32gb > 2**31

    window._runner.progress.emit(total_32gb // 2, total_32gb, 12_000_000.0)

    assert window._log_panel._bar.value() == 50
    assert window._last_progress_bytes == total_32gb // 2


@patch("r36s_studio.gui.partition_runner.copy_games")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_copy_games_progress_reaches_log_panel_through_real_cross_thread_signal(
    mock_list, mock_filter, mock_detect, mock_copy_games, qapp
):
    """`PartitionJobRunner` est un vrai `QThread` (contrairement à
    `WorkerRunner`, qui reste sur le thread Qt principal via `QTimer`) :
    son signal `progress` traverse donc réellement une frontière de
    thread jusqu'à `MainWindow._on_progress` -- la connexion devient une
    file d'attente Qt (`Qt.QueuedConnection` automatique), le seul endroit
    de ce projet où une régression de câblage se manifesterait
    différemment qu'en même thread. À couvrir spécifiquement."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_copy_games.side_effect = lambda device, source_path, on_progress=None, should_cancel=None: on_progress(
        ProgressEvent(done=30, total=100, speed=2_000_000.0)
    )

    window = MainWindow()
    window._mode = "copy_games"
    window._device = device
    window._file_path = "/tmp/games"
    window._start_worker()

    assert window._runner.wait(2000)  # laisse le vrai QThread se terminer
    for _ in range(20):
        qapp.processEvents()  # livre les signaux mis en file d'attente entre threads

    assert window._log_panel._bar.value() == 30


@patch("r36s_studio.gui.partition_runner.extract_easyroms")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_easyroms_progress_survives_byte_counts_beyond_32_bit_int_cross_thread(
    mock_list, mock_filter, mock_detect, mock_extract_easyroms, qapp
):
    """Même bug que `test_flash_progress_survives_byte_counts_beyond_32_bit_int`,
    mais sur le seul chemin réellement inter-thread du projet
    (`PartitionJobRunner`, un vrai `QThread`) -- une EASYROMS de plusieurs
    dizaines de Go dépasse tout aussi facilement 2**31 octets."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    total_32gb = 34_359_738_368  # 32 Go, très au-delà de 2**31 - 1 (~2,1 milliards)
    assert total_32gb > 2**31
    mock_extract_easyroms.side_effect = (
        lambda device, source_path, on_progress=None, should_cancel=None: on_progress(
            ProgressEvent(done=total_32gb // 2, total=total_32gb, speed=2_000_000.0)
        )
    )

    window = MainWindow()
    window._mode = "extract_easyroms"
    window._device = device
    window._file_path = "/tmp/EASYROMS_archive"
    window._start_worker()

    assert window._runner.wait(2000)
    for _ in range(20):
        qapp.processEvents()

    assert window._log_panel._bar.value() == 50
    assert window._last_progress_bytes == total_32gb // 2


# --- colonne gauche désactivée pendant une opération (§5, refonte nav.) ----


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_start_worker_disables_home_and_reenables_on_finish(mock_list, mock_filter, qapp):
    window = MainWindow()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()
        for row in window._home._tiles.values():
            assert row.isEnabled() is False
        assert window._home._backup_row.isEnabled() is False

        window._on_worker_finished(True)

    for row in window._home._tiles.values():
        assert row.isEnabled() is True
    assert window._home._backup_row.isEnabled() is True


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_start_worker_disables_both_mode_switch_buttons_and_reenables_on_finish(mock_list, mock_filter, qapp):
    """Changer de mode en plein flash ou en pleine copie laisserait un job
    orphelin (§5 mode assisté) -- les deux boutons de bascule (Mode
    assisté sur HomeScreen, Mode expert sur AssistedLandingScreen) doivent
    être désactivés pendant toute opération disque, dans les deux sens."""
    window = MainWindow()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()
        assert window._home._assisted_mode_button.isEnabled() is False
        assert window._assisted_landing._expert_button.isEnabled() is False

        window._on_worker_finished(True)

    assert window._home._assisted_mode_button.isEnabled() is True
    assert window._assisted_landing._expert_button.isEnabled() is True


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_start_worker_pauses_console_stage_and_resumes_on_finish(mock_list, mock_filter, qapp):
    """§5 (animations console) : mises en pause pendant une opération
    disque pour ne pas consommer de ressources, reprises à la fin."""
    window = MainWindow()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"
    window._console_stage = MagicMock()
    runner_class = _mock_runner_class()

    with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
        window._start_worker()
        window._console_stage.pause.assert_called_once()
        window._console_stage.resume.assert_not_called()

        window._on_worker_finished(True)

    window._console_stage.resume.assert_called_once()


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_cancel_requested_calls_runner_cancel(mock_list, mock_filter, qapp):
    window = MainWindow()
    fake_runner = MagicMock()
    window._runner = fake_runner

    window._on_cancel_requested()

    fake_runner.cancel.assert_called_once()


# --- résultats dans le journal de bord, pas un écran séparé (§5) -----------


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_worker_success_logs_message_and_shows_eject_for_flash(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché (MainWindow, pas un descendant)
    window._mode = "flash"
    window._device = _make_device()
    window._file_path = "/tmp/sd.img"

    window._on_worker_finished(True)

    assert window._log_panel._eject_button.isVisible() is True
    assert "prête" in window._log_panel._log_view.toPlainText()


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_worker_error_logs_cancelled_message(mock_list, mock_filter, qapp):
    window = MainWindow()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"

    window._on_worker_error("CANCELLED", "Sauvegarde annulée après 1024 octets")
    window._on_worker_finished(False)

    assert "annulée" in window._log_panel._log_view.toPlainText()


@patch("r36s_studio.gui.main_window.eject_device")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_eject_requested_calls_eject_module_with_device_path(mock_list, mock_filter, mock_eject, qapp):
    window = MainWindow()
    window._device = _make_device(path="/dev/fake-disk-test-3")

    window._on_eject_requested()

    mock_eject.assert_called_once_with("/dev/fake-disk-test-3")


# --- colonne gauche : six étapes toujours visibles, statut informatif ------
# (§4.5) ----------------------------------------------------------------


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_startup_detects_single_card_and_annotates_home(mock_list, mock_filter, mock_detect, mock_load, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    status = _all_status(StepStatus.AVAILABLE)
    mock_detect.return_value = status
    window = MainWindow()
    window.show()

    mock_detect.assert_called_once_with(device)
    # Les six lignes restent visibles quel que soit le statut (§4.5).
    for tile in window._home._tiles.values():
        assert tile.isVisible() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_startup_with_no_card_still_shows_all_six_tiles(mock_list, mock_filter, mock_detect, mock_load, qapp):
    mock_list.return_value = []
    mock_filter.return_value = []
    mock_detect.return_value = _all_status(StepStatus.NOT_RELEVANT)
    window = MainWindow()
    window.show()

    mock_detect.assert_called_once_with(None)
    for tile in window._home._tiles.values():
        assert tile.isVisible() is True


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_startup_with_multiple_cards_passes_none_to_detection(mock_list, mock_filter, mock_detect, mock_load, qapp):
    """Cas non couvert par une carte unique : plusieurs cartes candidates
    -- `detect_workflow_status` reçoit `None` (aucune mise en avant
    possible), mais les six lignes restent affichées normalement."""
    devices = [_make_device(path="/dev/fake-disk-test-3"), _make_device(path="/dev/fake-disk-test-4")]
    mock_list.return_value = devices
    mock_filter.return_value = devices
    mock_detect.return_value = _all_status(StepStatus.NOT_RELEVANT)
    window = MainWindow()
    window.show()

    mock_detect.assert_called_once_with(None)
    for tile in window._home._tiles.values():
        assert tile.isVisible() is True


@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_home_refresh_requested_re_runs_detection(mock_list, mock_filter, mock_detect, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_detect.return_value = _all_status(StepStatus.AVAILABLE)
    window = MainWindow()
    mock_detect.reset_mock()

    window._home.refresh_requested.emit()

    mock_detect.assert_called_once_with(device)


@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_worker_finished_re_runs_detection(mock_list, mock_filter, mock_detect, qapp):
    """La carte a changé d'état après une opération (flash, injection...) --
    la détection doit se relancer automatiquement, sans qu'il y ait de
    bouton "retour à l'accueil" à cliquer (§5, refonte navigation : plus
    d'écran Résultat séparé avec un tel bouton, la vue est déjà là)."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_detect.return_value = _all_status(StepStatus.AVAILABLE)
    window = MainWindow()
    window._mode = "flash"
    window._device = device
    window._file_path = "/tmp/sd.img"
    mock_detect.reset_mock()

    mock_detect.return_value = _all_status(StepStatus.DONE)
    window._on_worker_finished(True)

    mock_detect.assert_called_once_with(device)


# --- fenêtre Aide (macOS uniquement, §3) ------------------------------------


@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
@patch("r36s_studio.gui.screens.platform.system", return_value="Darwin")
def test_home_help_requested_opens_help_dialog(mock_platform, mock_list, mock_filter, mock_detect, qapp):
    mock_list.return_value = []
    mock_filter.return_value = []
    mock_detect.return_value = _all_status(StepStatus.NOT_RELEVANT)
    window = MainWindow()

    window._home.help_requested.emit()

    assert window._help_dialog.isVisible() is True


@patch("r36s_studio.gui.main_window.subprocess.run")
@patch("r36s_studio.gui.main_window.detect_workflow_status")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_help_dialog_open_settings_opens_full_disk_access_pane(mock_list, mock_filter, mock_detect, mock_run, qapp):
    mock_list.return_value = []
    mock_filter.return_value = []
    mock_detect.return_value = _all_status(StepStatus.NOT_RELEVANT)
    window = MainWindow()

    window._help_dialog.open_settings_requested.emit()

    mock_run.assert_called_once_with(
        ["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles"], check=True
    )


# --- inject-boot / copy-games (étapes D/E) : PartitionJobRunner, archives --


@patch("r36s_studio.gui.main_window.archives.list_archives", return_value=["/tmp/R36S Studio/BOOT_x"])
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_inject_boot_flow_offers_existing_archive_and_uses_partition_runner(
    mock_list, mock_filter, mock_detect, mock_list_archives, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window = MainWindow()
        window._home.inject_boot_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

        mock_list_archives.assert_called_once_with("BOOT")
        assert window._file_dialog.isVisible() is True
        assert window._file_dialog._archive_list.count() == 1

        window._file_dialog._archive_list.setCurrentRow(0)
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    runner_class.assert_called_once_with("inject_boot", device, "/tmp/R36S Studio/BOOT_x", parent=window)
    runner_class.instances[0].start.assert_called_once()


@patch("r36s_studio.gui.main_window.archives.list_archives", return_value=[])
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_copy_games_flow_falls_back_to_manual_browse_when_no_archives(
    mock_list, mock_filter, mock_detect, mock_list_archives, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window = MainWindow()
        window._home.copy_games_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

        mock_list_archives.assert_called_once_with("EASYROMS")

        with patch("r36s_studio.gui.screens.QFileDialog.getExistingDirectory", return_value="/tmp/games"):
            window._file_dialog._browse()
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    runner_class.assert_called_once_with("copy_games", device, "/tmp/games", parent=window)


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_copy_games_success_message_and_allows_eject(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window.show()
    window._mode = "copy_games"
    window._device = _make_device(display="Carte de Léo")

    window._on_worker_finished(True)

    assert "Carte de Léo" in window._log_panel._log_view.toPlainText()
    assert window._log_panel._eject_button.isVisible() is True


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_success_never_allows_eject(mock_list, mock_filter, qapp):
    """La sauvegarde n'écrit que dans un fichier, jamais sur la carte
    (§5 point 6) -- rien à éjecter."""
    window = MainWindow()
    window.show()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"

    window._on_worker_finished(True)

    assert window._log_panel._eject_button.isVisible() is False


# --- extract-boot / extract-easyroms (étapes A/B) : choix du dossier ------
#
# Régression corrigée : la destination était devenue un chemin généré
# automatiquement, sans que l'utilisateur puisse décider où son archive est
# enregistrée. La fenêtre Fichier est rétablie, avec un dossier par défaut
# (~/Documents/R36S Studio) que l'utilisateur peut accepter tel quel ou
# remplacer par n'importe quel emplacement -- seul le nom horodaté à
# l'intérieur reste automatique.


@patch("r36s_studio.gui.main_window.archives.default_archives_dir")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_boot_shows_file_dialog_with_default_path_preselected(
    mock_list, mock_filter, mock_detect, mock_default_dir, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_default_dir.return_value = "/home/x/Documents/R36S Studio"

    window = MainWindow()
    window._home.extract_boot_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    window._device_dialog._emit_chosen()

    assert window._file_dialog.isVisible() is True
    assert window._file_dialog._path_label.text() == "/home/x/Documents/R36S Studio"
    assert window._file_dialog._next_button.isEnabled() is True  # défaut déjà accepté


@patch("r36s_studio.gui.main_window.archives.new_archive_path")
@patch("r36s_studio.gui.main_window.archives.default_archives_dir", return_value="/home/x/Documents/R36S Studio")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_boot_accepting_default_uses_it_as_base_dir(
    mock_list, mock_filter, mock_detect, mock_default_dir, mock_new_path, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_new_path.return_value = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window = MainWindow()
        window._home.extract_boot_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

        # L'utilisateur accepte simplement le défaut proposé.
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    from pathlib import Path

    mock_new_path.assert_called_once_with("BOOT", base_dir=Path("/home/x/Documents/R36S Studio"))
    runner_class.assert_called_once_with(
        "extract_boot", device, "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21", parent=window
    )


@patch("r36s_studio.gui.main_window.archives.new_archive_path")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_boot_can_replace_default_with_external_drive(
    mock_list, mock_filter, mock_detect, mock_new_path, qapp
):
    """L'utilisateur peut remplacer le dossier proposé par n'importe quel
    autre emplacement, y compris un disque externe."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_new_path.return_value = "/Volumes/DisqueExterne/BOOT_2026-07-06_00-21"
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window = MainWindow()
        window._home.extract_boot_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()

        with patch(
            "r36s_studio.gui.screens.QFileDialog.getExistingDirectory",
            return_value="/Volumes/DisqueExterne",
        ):
            window._file_dialog._browse()
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    from pathlib import Path

    mock_new_path.assert_called_once_with("BOOT", base_dir=Path("/Volumes/DisqueExterne"))


@patch("r36s_studio.gui.main_window.archives.new_archive_path")
@patch("r36s_studio.gui.main_window.archives.default_archives_dir", return_value="/home/x/Documents/R36S Studio")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_easyroms_uses_easyroms_label(
    mock_list, mock_filter, mock_detect, mock_default_dir, mock_new_path, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    mock_new_path.return_value = "/home/x/Documents/R36S Studio/EASYROMS_2026-07-06_00-21"

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", _mock_partition_runner_class()):
        window = MainWindow()
        window._home.extract_easyroms_selected.emit()
        window._device_dialog._list.setCurrentRow(0)
        window._device_dialog._emit_chosen()
        window._file_dialog.file_chosen.emit(window._file_dialog._path_label.text())

    from pathlib import Path

    mock_new_path.assert_called_once_with("EASYROMS", base_dir=Path("/home/x/Documents/R36S Studio"))


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_extract_boot_success_logs_archive_path_size_and_shows_reveal(mock_list, mock_filter, mock_load, qapp):
    window = MainWindow()
    window.show()
    window._mode = "extract_boot"
    window._device = _make_device()
    window._file_path = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    window._last_progress_bytes = 12_582_912  # 12 Mo

    window._on_worker_finished(True)

    assert window._log_panel._eject_button.isVisible() is True
    log_text = window._log_panel._log_view.toPlainText()
    assert "ordinateur" in log_text
    assert "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21" in log_text
    assert "12.0 Mo" in log_text
    assert window._log_panel._reveal_button.isVisible() is True


@patch("r36s_studio.gui.main_window.reveal")
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_reveal_requested_calls_reveal_with_archive_path(mock_list, mock_filter, mock_reveal, qapp):
    window = MainWindow()
    window._mode = "extract_boot"
    window._device = _make_device()
    window._file_path = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"
    window._on_worker_finished(True)

    window._log_panel._reveal_button.click()

    mock_reveal.assert_called_once_with("/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21")


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_inject_boot_success_logs_source_archive_path(mock_list, mock_filter, mock_load, qapp):
    """Étapes D/E : la même ligne indique quelle archive a servi de
    source, plutôt que « archive créée »."""
    window = MainWindow()
    window.show()
    window._mode = "inject_boot"
    window._device = _make_device()
    window._file_path = "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21"

    window._on_worker_finished(True)

    log_text = window._log_panel._log_view.toPlainText()
    assert "/home/x/Documents/R36S Studio/BOOT_2026-07-06_00-21" in log_text
    assert window._log_panel._reveal_button.isVisible() is True


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_backup_success_shows_no_reveal_button(mock_list, mock_filter, qapp):
    """backup/flash ne manipulent pas de dossier d'archive -- rien à
    révéler."""
    window = MainWindow()
    window.show()
    window._mode = "backup"
    window._device = _make_device()
    window._file_path = "/tmp/out.img"

    window._on_worker_finished(True)

    assert window._log_panel._reveal_button.isVisible() is False


# --- eject (étape F) : immédiat, sans fenêtre Fichier ni opération ----------


@patch("r36s_studio.gui.main_window.eject_device")
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_eject_flow_is_immediate_and_confirms_success(mock_list, mock_filter, mock_detect, mock_eject, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]

    window = MainWindow()
    window.show()
    window._home.eject_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    window._device_dialog._emit_chosen()

    mock_eject.assert_called_once_with(device.path)
    assert "retirée en toute sécurité" in window._log_panel._log_view.toPlainText()
    assert window._file_dialog.isVisible() is False  # étape F : aucune fenêtre Fichier


@patch("r36s_studio.gui.main_window.eject_device", side_effect=OSError("carte occupée"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_eject_flow_logs_friendly_error_and_raw_detail_on_failure(mock_list, mock_filter, mock_detect, mock_eject, qapp):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]

    window = MainWindow()
    window.show()
    window._home.eject_selected.emit()
    window._device_dialog._list.setCurrentRow(0)
    window._device_dialog._emit_chosen()

    log_text = window._log_panel._log_view.toPlainText()
    assert "carte occupée" in log_text  # journal de bord : tout y va, plus de panneau Détails séparé (§5)


# --- messages d'erreur conviviaux + détail brut dans le journal (§5) -------


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_partition_not_found_error_logs_friendly_message_then_raw_detail(
    mock_list, mock_filter, qapp
):
    window = MainWindow()
    window.show()
    window._mode = "inject_boot"
    window._device = _make_device()

    window._on_worker_error("PARTITION_NOT_FOUND", "Partition « BOOT » introuvable sur /dev/fake-disk-test-3")
    window._on_worker_finished(False)

    lines = window._log_panel._log_view.toPlainText().splitlines()
    assert any("carte" in line.lower() and "/dev/fake-disk-test-3" not in line for line in lines)
    assert any("/dev/fake-disk-test-3" in line for line in lines)


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_unrecognized_error_code_falls_back_to_generic_friendly_message(mock_list, mock_filter, qapp):
    window = MainWindow()
    window.show()
    window._mode = "backup"
    window._device = _make_device()

    window._on_worker_error("SOME_FUTURE_CODE", "détail technique quelconque")
    window._on_worker_finished(False)

    log_text = window._log_panel._log_view.toPlainText()
    assert "Une erreur est survenue" in log_text
    assert "détail technique quelconque" in log_text  # journal de bord : le détail brut suit quand même


@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_macos_tcc_protected_folder_error_shows_dedicated_friendly_message(mock_list, mock_filter, qapp):
    """La détection élargie (worker_runner.py) ne sert à rien si le
    message dédié reste caché derrière le message générique -- vérifie
    qu'il apparaît bien dans le journal."""
    window = MainWindow()
    window.show()
    window._mode = "flash"
    window._device = _make_device()

    window._on_worker_error(
        "MACOS_TCC_PROTECTED_FOLDER",
        "[Errno 1] Operation not permitted: '/Users/x/Downloads/ArkOS.img.xz'",
    )
    window._on_worker_finished(False)

    log_text = window._log_panel._log_view.toPlainText()
    assert "dossier protégé" in log_text
    assert "/Users/x/Downloads" in log_text  # détail brut, en ligne suivante -- pas masqué (§5)


# --- mode assisté (§5 mode assisté) -----------------------------------------
#
# ui_mode (config.py) pilote l'écran affiché au lancement ; le mode assisté
# enchaîne 7 étapes (gui/wizard_flow.py) sur la même MainView que le mode
# expert (colonne gauche remplacée par WizardStepPanel).

from r36s_studio.gui.wizard_flow import WizardJob


def _mock_identify_runner_class():
    instances = []

    def _factory(device_path, parent=None):
        instance = MagicMock()
        instance.device_path = device_path
        instances.append(instance)
        return instance

    factory = MagicMock(side_effect=_factory)
    factory.instances = instances
    return factory


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_default_startup_shows_assisted_landing_screen(mock_list, mock_filter, mock_detect, mock_load, qapp):
    window = MainWindow()

    assert window._root_stack.currentWidget() is window._assisted_landing


@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="expert"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_expert_ui_mode_startup_shows_main_view_with_home(mock_list, mock_filter, mock_detect, mock_load, qapp):
    window = MainWindow()

    assert window._root_stack.currentWidget() is window._main_view
    assert window._main_view._left_stack.currentWidget() is window._home


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_expert_mode_button_from_landing_persists_config_and_shows_home(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    window = MainWindow()

    window._assisted_landing.expert_mode_requested.emit()

    assert window._root_stack.currentWidget() is window._main_view
    assert window._main_view._left_stack.currentWidget() is window._home
    mock_save.assert_called_once()
    assert mock_save.call_args[0][0].ui_mode == "expert"


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_ui_mode_switch_works_both_ways_and_config_follows(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    """Sans bouton de retour, basculer en mode expert était un aller
    simple -- ui_mode étant persisté (config.py), l'utilisateur restait
    bloqué en mode expert même après redémarrage."""
    window = MainWindow()
    assert window._root_stack.currentWidget() is window._assisted_landing

    window._assisted_landing.expert_mode_requested.emit()

    assert window._root_stack.currentWidget() is window._main_view
    assert window._main_view._left_stack.currentWidget() is window._home
    assert mock_save.call_args[0][0].ui_mode == "expert"

    window._home.assisted_mode_requested.emit()

    assert window._root_stack.currentWidget() is window._assisted_landing
    assert mock_save.call_args[0][0].ui_mode == "assisted"
    assert mock_save.call_count == 2


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_prepare_button_starts_wizard_on_step_one(mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp):
    window = MainWindow()

    window._assisted_landing.prepare_requested.emit()

    assert window._root_stack.currentWidget() is window._main_view
    assert window._main_view._left_stack.currentWidget() is window._wizard_panel
    assert window._wizard_flow.current_job() == WizardJob.DETECT_SOURCE
    assert window._wizard_poll_timer.isActive() is True


def _mock_fingerprint_runner_class():
    """Même principe que `_mock_identify_runner_class`, pour
    `WizardFingerprintRunner` (§5 mode assisté, correctif : plus de
    `compute_boot_fingerprint` synchrone sur le thread principal)."""
    instances = []

    def _factory(device_path, parent=None):
        instance = MagicMock()
        instance.device_path = device_path
        instances.append(instance)
        return instance

    factory = MagicMock(side_effect=_factory)
    factory.instances = instances
    return factory


# --- plusieurs cartes candidates à l'étape 1/4 : proposer un choix --------
#
# Bug rapporté : _list_safe_devices() peut retourner plusieurs candidates
# (ex. un disque USB qui passe le filtre en plus de la carte SD) -- avant
# ce correctif, `candidate` retombait à None dans ce cas, indiscernable de
# "aucune carte" (même statut "en attente"), ce qui donnait l'impression
# que la détection était cassée en mode assisté alors qu'elle voit
# exactement la même chose que le mode expert (_list_safe_devices()
# partagée par les deux).


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_step_one_poll_with_multiple_candidates_opens_device_dialog(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    sd_card = _make_device(path="/dev/fake-disk-test-1", display="Carte SD")
    usb_disk = _make_device(path="/dev/fake-disk-test-2", display="Disque USB 123 Go")
    mock_list.return_value = [sd_card, usb_disk]
    mock_filter.return_value = [sd_card, usb_disk]
    fingerprint_runner_class = _mock_fingerprint_runner_class()

    window = MainWindow()
    window.show()
    window._assisted_landing.prepare_requested.emit()

    with patch("r36s_studio.gui.main_window.WizardFingerprintRunner", fingerprint_runner_class):
        window._on_wizard_poll()

    fingerprint_runner_class.assert_not_called()  # pas de choix fait -> pas d'empreinte encore
    assert window._device_dialog.isVisible() is True
    assert window._device_dialog._devices == [sd_card, usb_disk]
    assert window._wizard_poll_timer.isActive() is False


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_choosing_a_candidate_from_device_dialog_starts_fingerprint_check(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    sd_card = _make_device(path="/dev/fake-disk-test-1", display="Carte SD")
    usb_disk = _make_device(path="/dev/fake-disk-test-2", display="Disque USB 123 Go")
    mock_list.return_value = [sd_card, usb_disk]
    mock_filter.return_value = [sd_card, usb_disk]
    fingerprint_runner_class = _mock_fingerprint_runner_class()

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._on_wizard_poll()  # ouvre la fenêtre Choix de la carte (2 candidates)

    with patch("r36s_studio.gui.main_window.WizardFingerprintRunner", fingerprint_runner_class):
        window._device_dialog.device_chosen.emit(sd_card)

    assert window._device_dialog.isVisible() is False
    fingerprint_runner_class.assert_called_once_with(sd_card.path, parent=window)
    # Ne doit pas non plus avoir déclenché le chemin mode expert.
    assert window._device is None


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_poll_logs_rejected_devices_with_reason_once(mock_list, mock_load, mock_save, qapp):
    """Trace diagnosticable (§5 mode assisté) : combien de périphériques
    trouvés et lesquels écartés, avec la raison -- sans filtre
    supplémentaire côté assisté (même appel que le mode expert). Ne doit
    pas se répéter à chaque sondage identique (pas de spam du journal)."""
    system_disk = Device(
        path="/dev/fake-disk-test-1",
        display="Disque système",
        size_bytes=500_000_000_000,
        removable=False,
        bus="Internal",
        is_system=True,
        mountpoints=["/"],
    )
    mock_list.return_value = [system_disk]

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    window._on_wizard_poll()
    window._on_wizard_poll()  # état identique -> ne doit pas dupliquer la ligne

    log_text = window._log_panel._log_view.toPlainText()
    assert log_text.count("Détection") == 1
    assert "Disque système" in log_text
    assert "carte système" in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_step_panel_refresh_button_triggers_immediate_poll(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    fingerprint_runner_class = _mock_fingerprint_runner_class()

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._wizard_poll_timer.stop()

    with patch("r36s_studio.gui.main_window.WizardFingerprintRunner", fingerprint_runner_class):
        window._wizard_panel.refresh_requested.emit()

    # Relance immédiatement une recherche, sans attendre le prochain tick
    # (jusqu'à 1,5 s) -- la carte est trouvée du premier coup, le sondage
    # s'arrête donc de nouveau (comportement normal, déjà couvert par
    # test_wizard_step_one_poll_starts_fingerprint_runner_on_a_separate_thread).
    fingerprint_runner_class.assert_called_once_with(device.path, parent=window)


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_step_panel_refresh_button_resumes_automatic_polling_when_nothing_found(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    """Cas d'un rafraîchissement manuel après un choix annulé dans la
    fenêtre Choix de la carte : le sondage automatique doit reprendre,
    pas seulement une recherche isolée."""
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._wizard_poll_timer.stop()

    window._wizard_panel.refresh_requested.emit()

    assert window._wizard_poll_timer.isActive() is True


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_step_one_shows_refresh_button(mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp):
    window = MainWindow()
    window.show()

    window._assisted_landing.prepare_requested.emit()

    assert window._wizard_panel._refresh_button.isVisible() is True


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_step_one_poll_starts_fingerprint_runner_on_a_separate_thread(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    """Correctif : monter BOOT pour calculer l'empreinte (§4.4) peut
    bloquer jusqu'à MOUNT_WAIT_SECONDS -- un gel de l'interface pendant ce
    montage se lit comme un plantage. `_on_wizard_poll` ne doit donc plus
    jamais appeler `compute_boot_fingerprint` directement sur le thread Qt
    principal, seulement démarrer `WizardFingerprintRunner`."""
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    fingerprint_runner_class = _mock_fingerprint_runner_class()

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    assert window._wizard_panel._continue_button.isEnabled() is False

    with patch("r36s_studio.gui.main_window.WizardFingerprintRunner", fingerprint_runner_class):
        window._on_wizard_poll()

    fingerprint_runner_class.assert_called_once_with(device.path, parent=window)
    fingerprint_runner_class.instances[0].start.assert_called_once()
    # Toujours en attente du résultat -- rien n'est encore décidé.
    assert window._wizard_panel._continue_button.isEnabled() is False
    assert window._wizard_source_device is None
    assert window._wizard_poll_timer.isActive() is False  # pas de deuxième calcul en parallèle


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_fingerprint_ready_for_detect_source_stores_device_and_enables_continue(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    device = _make_device()
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    window._on_wizard_fingerprint_ready(WizardJob.DETECT_SOURCE, device, "fp-source")

    assert window._wizard_panel._continue_button.isEnabled() is True
    assert window._wizard_source_device is device
    assert window._wizard_source_fingerprint == "fp-source"


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_continue_on_step_one_advances_to_identify_and_starts_identify_runner(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    device = _make_device()
    identify_runner_class = _mock_identify_runner_class()

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._on_wizard_fingerprint_ready(WizardJob.DETECT_SOURCE, device, "fp-source")

    with patch("r36s_studio.gui.main_window.WizardIdentifyRunner", identify_runner_class):
        window._wizard_panel.continue_requested.emit()

    assert window._wizard_flow.is_done(WizardJob.DETECT_SOURCE) is True
    assert window._wizard_flow.current_job() == WizardJob.IDENTIFY
    identify_runner_class.assert_called_once_with(device.path, parent=window)
    identify_runner_class.instances[0].start.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_success_enables_continue_and_logs_result(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyResult
    from r36s_studio.identify.dtb import DtbInfo

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    window._wizard_flow.mark_done(WizardJob.DETECT_SOURCE)
    window._wizard_panel._continue_button.setEnabled(False)

    info = DtbInfo(board_compatible="rk3326-evb-lp3-v12", panel_compatible="sitronix,st7703", timings={})
    window._on_wizard_identify_finished(IdentifyResult(info=info))

    assert window._wizard_panel._continue_button.isEnabled() is True
    log_text = window._log_panel._log_view.toPlainText()
    assert "rk3326-evb-lp3-v12" in log_text


# --- échec d'identification : trois causes distinctes, trois messages -----


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_mount_failed_suggests_a_faulty_card(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyFailureReason, IdentifyResult

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    window._on_wizard_identify_finished(IdentifyResult(failure_reason=IdentifyFailureReason.MOUNT_FAILED))

    assert window._wizard_panel._continue_button.isEnabled() is True
    log_text = window._log_panel._log_view.toPlainText()
    assert "défaillante" in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_no_dtb_found_message_differs_from_mount_failed(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyFailureReason, IdentifyResult

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    window._on_wizard_identify_finished(IdentifyResult(failure_reason=IdentifyFailureReason.NO_DTB_FOUND))

    assert window._wizard_panel._continue_button.isEnabled() is True
    log_text = window._log_panel._log_view.toPlainText()
    assert "défaillante" not in log_text
    assert "fraîchement flashée" in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_invalid_dtb_message_differs_from_the_other_two(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyFailureReason, IdentifyResult

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    window._on_wizard_identify_finished(IdentifyResult(failure_reason=IdentifyFailureReason.ALL_DTB_INVALID))

    assert window._wizard_panel._continue_button.isEnabled() is True
    log_text = window._log_panel._log_view.toPlainText()
    assert "défaillante" not in log_text
    assert "fraîchement flashée" not in log_text
    assert "illisible, corrompu" in log_text


# --- journal : chemin examiné et fichiers .dtb, dans tous les cas ---------


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_logs_scanned_directory_and_examined_files_on_success(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyResult
    from r36s_studio.identify.dtb import DtbInfo

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    info = DtbInfo(board_compatible="rk3326-evb-lp3-v12", panel_compatible="sitronix,st7703", timings={})
    result = IdentifyResult(info=info, scanned_directory="/Volumes/BOOT", examined_files=["/Volumes/BOOT/board.dtb"])
    window._on_wizard_identify_finished(result)

    log_text = window._log_panel._log_view.toPlainText()
    assert "/Volumes/BOOT" in log_text
    assert "board.dtb" in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_logs_scanned_directory_and_examined_files_on_no_dtb_found(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyFailureReason, IdentifyResult

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    result = IdentifyResult(
        failure_reason=IdentifyFailureReason.NO_DTB_FOUND,
        scanned_directory="/Volumes/BOOT",
        examined_files=[],
    )
    window._on_wizard_identify_finished(result)

    log_text = window._log_panel._log_view.toPlainText()
    assert "/Volumes/BOOT" in log_text


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_identify_logs_raw_detail_on_mount_failed(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    from r36s_studio.identify import IdentifyFailureReason, IdentifyResult

    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()

    result = IdentifyResult(failure_reason=IdentifyFailureReason.MOUNT_FAILED, detail="délai dépassé sur /dev/x")
    window._on_wizard_identify_finished(result)

    log_text = window._log_panel._log_view.toPlainText()
    assert "délai dépassé sur /dev/x" in log_text


# --- étape 4 : garde-fou par empreinte de contenu, pas path/size_bytes -----


def _target_setup(window, device):
    window._wizard_flow.reset()
    for job in (WizardJob.DETECT_SOURCE, WizardJob.IDENTIFY, WizardJob.EXTRACT_BOOT, WizardJob.EXTRACT_EASYROMS):
        window._wizard_flow.mark_done(job)
    window._wizard_source_fingerprint = "fp-source"


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_step_four_poll_also_starts_fingerprint_runner(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    same_card = _make_device(path="/dev/fake-disk-test-9")
    mock_list.return_value = [same_card]
    mock_filter.return_value = [same_card]
    fingerprint_runner_class = _mock_fingerprint_runner_class()

    window = MainWindow()
    _target_setup(window, same_card)
    window._enter_wizard_job(WizardJob.DETECT_TARGET)

    with patch("r36s_studio.gui.main_window.WizardFingerprintRunner", fingerprint_runner_class):
        window._on_wizard_poll()

    fingerprint_runner_class.assert_called_once_with(same_card.path, parent=window)
    assert window._wizard_poll_timer.isActive() is False  # pas de deuxième calcul en parallèle


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_step_four_refuses_to_continue_when_fingerprint_matches_source(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    same_card = _make_device(path="/dev/fake-disk-test-9")

    window = MainWindow()
    _target_setup(window, same_card)
    window._enter_wizard_job(WizardJob.DETECT_TARGET)

    window._on_wizard_fingerprint_ready(WizardJob.DETECT_TARGET, same_card, "fp-source")

    assert window._wizard_panel._continue_button.isEnabled() is False
    assert window._wizard_target_device is None
    assert window._wizard_poll_timer.isActive() is True  # continue d'attendre une vraie carte différente


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_step_four_allows_continue_when_fingerprint_differs(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    new_card = _make_device(path="/dev/fake-disk-test-9")

    window = MainWindow()
    _target_setup(window, new_card)
    window._enter_wizard_job(WizardJob.DETECT_TARGET)

    window._on_wizard_fingerprint_ready(WizardJob.DETECT_TARGET, new_card, "fp-blank-or-different")

    assert window._wizard_panel._continue_button.isEnabled() is True
    assert window._wizard_target_device is new_card
    assert window._wizard_poll_timer.isActive() is False


# --- reprise après erreur : ne rejoue jamais un job déjà réussi -------------


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices")
@patch("r36s_studio.gui.main_window.list_devices")
def test_wizard_resume_after_easyroms_failure_only_reruns_easyroms_not_boot(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    device = _make_device()
    mock_list.return_value = [device]
    mock_filter.return_value = [device]
    runner_class = _mock_partition_runner_class()

    with patch("r36s_studio.gui.main_window.PartitionJobRunner", runner_class):
        window = MainWindow()
        window.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
        window._main_view.show_wizard_panel()
        window._root_stack.setCurrentWidget(window._main_view)
        window._wizard_flow.reset()
        window._wizard_flow.mark_done(WizardJob.DETECT_SOURCE)
        window._wizard_flow.mark_done(WizardJob.IDENTIFY)
        window._wizard_source_device = device
        window._wizard_active = True

        # Étape 3a (BOOT) réussie.
        window._enter_wizard_job(WizardJob.EXTRACT_BOOT)
        window._on_worker_finished(True)
        assert window._wizard_flow.is_done(WizardJob.EXTRACT_BOOT) is True

        # Étape 3b (EASYROMS) échoue.
        assert window._wizard_flow.current_job() == WizardJob.EXTRACT_EASYROMS
        window._on_worker_error("IO_ERROR", "disque plein")
        window._on_worker_finished(False)

        assert window._wizard_flow.is_done(WizardJob.EXTRACT_EASYROMS) is False
        assert window._wizard_panel._resume_button.isVisible() is True

        # Reprendre : ne relance qu'EASYROMS, jamais le BOOT une deuxième fois.
        runner_class.reset_mock()
        runner_class.instances.clear()
        window._wizard_panel.resume_requested.emit()

    runner_class.assert_called_once()
    resume_call_args = runner_class.instances[0]
    assert resume_call_args.mode == "extract_easyroms"
    assert resume_call_args.device is device
    assert "EASYROMS" in resume_call_args.source_path


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=AppConfig(ui_mode="assisted"))
@patch("r36s_studio.gui.main_window.detect_workflow_status", return_value=_all_status(StepStatus.AVAILABLE))
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_wizard_cancel_returns_to_landing_and_stops_polling(
    mock_list, mock_filter, mock_detect, mock_load, mock_save, qapp
):
    window = MainWindow()
    window._assisted_landing.prepare_requested.emit()
    assert window._wizard_poll_timer.isActive() is True

    window._wizard_panel.cancel_requested.emit()

    assert window._root_stack.currentWidget() is window._assisted_landing
    assert window._wizard_poll_timer.isActive() is False
    assert window._wizard_active is False


# --- bouton "Voir les versions disponibles" (flash, §5 mode assisté) -------


@patch("r36s_studio.gui.main_window.webbrowser.open")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_releases_button_opens_darkos_r36s_releases_url(mock_list, mock_filter, mock_load, mock_open, qapp):
    from r36s_studio.identify.releases import DARKOS_R36S_RELEASES_URL

    window = MainWindow()

    window._file_dialog.releases_requested.emit()

    mock_open.assert_called_once_with(DARKOS_R36S_RELEASES_URL)


# --- choix du firmware (ArkOS/ROCKNIX) à l'étape de flash (§5) -------------


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_entering_flash_mode_initializes_file_dialog_firmware_from_config(
    mock_list, mock_filter, mock_load, mock_save, qapp
):
    window = MainWindow()
    device = _make_device()
    window._device = device
    window._mode = "flash"

    window._on_device_chosen(device)

    assert window._file_dialog._firmware == "arkos"


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_choosing_rocknix_persists_firmware_to_config(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()

    window._file_dialog.firmware_changed.emit("rocknix")

    assert window._app_config.firmware == "rocknix"
    mock_save.assert_called_once()
    assert mock_save.call_args[0][0].firmware == "rocknix"


# --- téléchargement automatique ROCKNIX (§5, étape de flash) ---------------
#
# `RocknixDownloadRunner` (partition_runner.py) est mocké ici -- aucun accès
# réseau réel, même principe que `PartitionJobRunner`/`WorkerRunner` mockés
# ailleurs dans ce fichier.


def _mock_rocknix_runner_class():
    instances = []

    def _factory(parent=None):
        instance = MagicMock()
        instances.append(instance)
        return instance

    factory = MagicMock(side_effect=_factory)
    factory.instances = instances
    return factory


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_rocknix_download_requested_starts_runner_and_marks_busy(mock_list, mock_filter, mock_load, mock_save, qapp):
    window = MainWindow()
    window._device = _make_device()
    window._mode = "flash"
    runner_class = _mock_rocknix_runner_class()

    with patch("r36s_studio.gui.main_window.RocknixDownloadRunner", runner_class):
        window._file_dialog.rocknix_download_requested.emit()

    runner_class.assert_called_once_with(parent=window)
    assert window._home._tiles["flash"].isEnabled() is False  # occupé pendant le téléchargement
    runner_class.instances[0].start.assert_called_once()


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_rocknix_download_success_opens_confirm_dialog_with_downloaded_path(
    mock_list, mock_filter, mock_load, mock_save, qapp
):
    window = MainWindow()
    device = _make_device()
    window._device = device
    window._mode = "flash"
    runner_class = _mock_rocknix_runner_class()

    with patch("r36s_studio.gui.main_window.RocknixDownloadRunner", runner_class):
        window._file_dialog.rocknix_download_requested.emit()

    window._on_rocknix_download_finished(True, "/tmp/ROCKNIX-RK3326.img.gz")

    assert window._file_path == "/tmp/ROCKNIX-RK3326.img.gz"
    assert window._confirm_dialog.isVisible() is True
    assert window._home._tiles["flash"].isEnabled() is True  # plus occupé, la fenêtre Confirmation prend le relais


@patch("r36s_studio.gui.main_window.app_config.save_config")
@patch("r36s_studio.gui.main_window.app_config.load_config", return_value=_EXPERT_MODE_CONFIG)
@patch("r36s_studio.gui.main_window.filter_devices", return_value=[])
@patch("r36s_studio.gui.main_window.list_devices", return_value=[])
def test_rocknix_download_failure_shows_friendly_message_in_log_panel(
    mock_list, mock_filter, mock_load, mock_save, qapp
):
    window = MainWindow()
    window._device = _make_device()
    window._mode = "flash"
    runner_class = _mock_rocknix_runner_class()

    with patch("r36s_studio.gui.main_window.RocknixDownloadRunner", runner_class):
        window._file_dialog.rocknix_download_requested.emit()

    window._on_worker_error("ROCKNIX_ASSET_NOT_FOUND", "détail technique")
    window._on_rocknix_download_finished(False, "")

    log_text = window._log_panel._log_view.toPlainText()
    assert "trouver la version ROCKNIX" in log_text
    assert window._confirm_dialog.isVisible() is False
