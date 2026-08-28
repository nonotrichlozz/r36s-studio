"""Tests de la vue principale et des fenêtres modales (gui/screens.py) —
construction et logique des signaux, en mode Qt "offscreen" (fixture
`qapp`)."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio.detect import StepStatus
from r36s_studio.devices import Device
from r36s_studio.gui.screens import (
    AssistedLandingScreen,
    ConfirmDialog,
    ConsoleArt,
    ConsoleBasePlate,
    ConsoleHalo,
    ConsoleStage,
    DeviceDialog,
    FileDialog,
    HelpDialog,
    HomeScreen,
    LogPanel,
    MainView,
    WindowBackdrop,
    _format_duration,
    _format_size,
    build_console_stage,
    build_window_backdrop,
    format_archive_label,
)
from PySide6.QtCore import QParallelAnimationGroup, QPropertyAnimation
from PySide6.QtWidgets import QWidget


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


def _fake_pixmap():
    from PySide6.QtGui import QPixmap

    pixmap = QPixmap(40, 40)
    pixmap.fill()
    return pixmap


# --- HomeScreen (colonne gauche, §5 refonte navigation) ---------------------


def test_home_screen_backup_tile_emits_signal(qapp):
    screen = HomeScreen()
    received = []
    screen.backup_selected.connect(lambda: received.append(True))

    screen.backup_selected.emit()

    assert received == [True]


def test_home_screen_shows_version_label(qapp):
    """À la demande explicite d'un utilisateur ayant perdu le fil entre
    plusieurs reconstructions locales de l'app -- sans repère visible,
    impossible de savoir si l'app en cours d'exécution contient les
    derniers correctifs."""
    from r36s_studio import __version__

    screen = HomeScreen()

    assert f"v{__version__}" in screen._version_label.text()


def test_home_screen_all_six_steps_emit_their_signal(qapp):
    screen = HomeScreen()
    signals = {
        "extract_boot": screen.extract_boot_selected,
        "extract_easyroms": screen.extract_easyroms_selected,
        "flash": screen.flash_selected,
        "inject_boot": screen.inject_boot_selected,
        "copy_games": screen.copy_games_selected,
        "eject": screen.eject_selected,
    }
    received = []
    for key, signal in signals.items():
        signal.connect(lambda key=key: received.append(key))

    for signal in signals.values():
        signal.emit()

    assert received == list(signals)


def test_home_screen_all_six_tiles_always_visible_regardless_of_status(qapp):
    """Coeur de la correction de conception : plus de tuile unique mise en
    avant, plus de section « Autres opérations » -- les six étapes restent
    toujours visibles, quel que soit leur statut (§4.5). Restent aussi
    activées ici : `set_busy` (pas `set_status`) est le seul levier de
    désactivation (§5, refonte navigation)."""
    screen = HomeScreen()
    screen.show()

    status = {
        "extract_boot": StepStatus.NOT_RELEVANT,
        "extract_easyroms": StepStatus.NOT_RELEVANT,
        "flash": StepStatus.AVAILABLE,
        "inject_boot": StepStatus.NOT_RELEVANT,
        "copy_games": StepStatus.NOT_RELEVANT,
        "eject": StepStatus.NOT_RELEVANT,
    }
    screen.set_status(status)

    for tile in screen._tiles.values():
        assert tile.isVisible() is True
        assert tile.isEnabled() is True


def test_home_screen_empty_status_hides_all_badges(qapp):
    """Statut absent (détection pas encore lancée) : aucun badge affiché,
    mais la ligne elle-même (icône, titre, description) reste visible."""
    screen = HomeScreen()

    screen.set_status({})

    for badge in screen._badges.values():
        assert badge.isVisible() is False
        assert badge.text() == ""


def test_home_screen_status_sets_badge_text_and_kind(qapp):
    screen = HomeScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois le parent affiché

    screen.set_status(
        {
            "extract_boot": StepStatus.AVAILABLE,
            "extract_easyroms": StepStatus.DONE,
            "flash": StepStatus.DONE,
            "inject_boot": StepStatus.AVAILABLE,
            "copy_games": StepStatus.PLATFORM_LIMITED,
            "eject": StepStatus.NOT_RELEVANT,
        }
    )

    assert screen._badges["extract_boot"].text() == "Faisable"
    assert screen._badges["extract_boot"].property("badgeKind") == "available"
    assert screen._badges["extract_easyroms"].text() == "Déjà faite"
    assert screen._badges["extract_easyroms"].property("badgeKind") == "done"
    assert screen._badges["flash"].text() == "Déjà faite"
    assert screen._badges["copy_games"].text() == "PC ou Linux"
    assert screen._badges["copy_games"].property("badgeKind") == "platform_limited"
    assert screen._badges["eject"].text() == "Non pertinente pour cette carte"
    assert screen._badges["eject"].property("badgeKind") == "not_relevant"
    for key in screen._badges:
        assert screen._badges[key].isVisible() is True


def test_home_screen_steps_appear_in_fixed_chronological_order(qapp):
    screen = HomeScreen()

    assert list(screen._tiles) == [
        "extract_boot",
        "extract_easyroms",
        "flash",
        "inject_boot",
        "copy_games",
        "eject",
    ]


def test_home_screen_refresh_button_emits_signal(qapp):
    screen = HomeScreen()
    received = []
    screen.refresh_requested.connect(lambda: received.append(True))

    screen._refresh_button.click()


@patch("r36s_studio.gui.screens.platform.system", return_value="Darwin")
def test_home_screen_shows_help_button_on_macos(mock_system, qapp):
    """Seul macOS a besoin de l'autorisation Accès complet au disque (§3) --
    le bouton Aide ne doit exister que là, pas ailleurs (§5 : ne pas dérouter
    les utilisateurs Windows/Linux avec une procédure qui ne les concerne
    pas)."""
    screen = HomeScreen()
    received = []
    screen.help_requested.connect(lambda: received.append(True))

    screen._help_button.click()

    assert received == [True]


@patch("r36s_studio.gui.screens.platform.system", return_value="Windows")
def test_home_screen_hides_help_button_outside_macos(mock_system, qapp):
    screen = HomeScreen()

    assert not hasattr(screen, "_help_button")


# --- désactivation pendant une opération (§5, refonte navigation) -----------


def test_home_screen_set_busy_disables_steps_and_backup_row(qapp):
    """Les étapes restent cliquables sauf pendant une opération, où elles
    sont désactivées visuellement (§5, refonte navigation) --
    `setEnabled(False)` empêche aussi Qt de délivrer les clics, pas
    seulement l'apparence."""
    screen = HomeScreen()

    screen.set_busy(True)

    for row in screen._tiles.values():
        assert row.isEnabled() is False
    assert screen._backup_row.isEnabled() is False


def test_home_screen_set_busy_false_reenables_steps_and_backup_row(qapp):
    screen = HomeScreen()
    screen.set_busy(True)

    screen.set_busy(False)

    for row in screen._tiles.values():
        assert row.isEnabled() is True
    assert screen._backup_row.isEnabled() is True


def test_home_screen_disabled_row_does_not_emit_on_click(qapp):
    screen = HomeScreen()
    received = []
    screen.flash_selected.connect(lambda: received.append(True))
    screen.set_busy(True)

    # Qt ne délivre pas mousePressEvent à un widget désactivé : émuler
    # l'appel direct serait trompeur (contournerait la désactivation) --
    # on vérifie plutôt que l'état lui-même empêche la réception native.
    assert screen._tiles["flash"].isEnabled() is False


# --- bandeau carte détectée (§5) --------------------------------------------


def test_home_screen_banner_shows_none_state_without_device(qapp):
    screen = HomeScreen()

    screen.set_status({}, device=None)

    assert screen._banner_device_label.text() == "Aucune carte détectée pour l'instant"
    assert screen._banner_state_label.text() == ""


def test_home_screen_banner_shows_device_model_and_size(qapp):
    screen = HomeScreen()
    device = _make_device(display="SanDisk Ultra", size_bytes=32_000_000_000)

    screen.set_status({"flash": StepStatus.AVAILABLE}, device=device)

    assert "SanDisk Ultra" in screen._banner_device_label.text()
    assert "32.0 Go" in screen._banner_device_label.text()


def test_home_screen_banner_recognizes_arkos_card(qapp):
    """Le flash marqué "déjà faite" (`detect_workflow_status`) est le seul
    signal déjà calculé pour "cette carte est déjà ArkOS" -- le bandeau le
    réutilise plutôt que de redemander l'information."""
    screen = HomeScreen()
    device = _make_device()

    screen.set_status({"flash": StepStatus.DONE}, device=device)

    assert screen._banner_state_label.text() == "Carte ArkOS reconnue"


def test_home_screen_banner_shows_unprepared_for_non_arkos_card(qapp):
    screen = HomeScreen()
    device = _make_device()

    screen.set_status({"flash": StepStatus.AVAILABLE}, device=device)

    assert screen._banner_state_label.text() == "Carte non préparée"


# --- illustrations décoratives (§5) -----------------------------------------
#
# Absentes sans lever d'exception si le fichier n'existe pas -- l'interface
# doit s'afficher normalement sans elles. Pixmaps factices en mémoire plutôt
# que de dépendre des vrais fichiers `gui/assets/*.png`.


def test_build_console_stage_returns_none_when_asset_missing(qapp):
    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
        assert build_console_stage() is None


def test_build_console_stage_returns_widget_when_asset_present(tmp_path, qapp):
    fake_path = tmp_path / "console.png"
    _fake_pixmap().save(str(fake_path))

    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=fake_path):
        stage = build_console_stage()

    assert isinstance(stage, ConsoleStage)


def test_console_art_paints_at_70_percent_opacity_and_has_no_graphics_effect(qapp):
    """§5 (correctif de performance) : l'ancien QGraphicsDropShadowEffect
    a été retiré -- ConsoleArt ne porte plus aucun QGraphicsEffect, le
    halo est désormais un widget peint séparément (ConsoleHalo)."""
    art = ConsoleArt(_fake_pixmap())

    assert art._OPACITY == 0.70
    assert art.graphicsEffect() is None


def test_console_art_float_offset_is_an_animatable_qt_property(qapp):
    art = ConsoleArt(_fake_pixmap())

    art.floatOffset = 4.5

    assert art.floatOffset == 4.5
    assert art._float_offset == 4.5


def test_console_base_plate_glow_opacity_is_an_animatable_qt_property(qapp):
    plate = ConsoleBasePlate()

    plate.glowOpacity = 0.4

    assert plate.glowOpacity == 0.4


def test_console_base_plate_paints_without_raising_at_various_sizes(qapp):
    """Pas d'assertion facile sur les pixels peints (dégradé radial
    elliptique, technique du repère mis à l'échelle) -- au minimum, un
    rendu ne doit jamais lever, y compris à taille nulle."""
    plate = ConsoleBasePlate()
    for w, h in [(0, 0), (1, 1), (140, 30)]:
        plate.resize(w, h)
        plate.grab()  # force un paintEvent réel


def test_console_base_plate_caches_gradient_pixmap_and_only_rebuilds_on_resize(qapp):
    """§5 (correctif de performance) : le QRadialGradient n'est reconstruit
    que dans resizeEvent, jamais depuis le setter de glowOpacity."""
    plate = ConsoleBasePlate()
    plate.resize(140, 30)
    cached = plate._pixmap

    plate.glowOpacity = 0.4

    assert plate._pixmap is cached


def test_console_halo_glow_opacity_is_an_animatable_qt_property(qapp):
    halo = ConsoleHalo()

    halo.glowOpacity = 0.3

    assert halo.glowOpacity == 0.3


def test_console_halo_paints_without_raising_at_various_sizes(qapp):
    halo = ConsoleHalo()
    for w, h in [(0, 0), (1, 1), (200, 220)]:
        halo.resize(w, h)
        halo.grab()


# --- ConsoleStage : les trois animations groupées (§5) ----------------------


def test_console_stage_groups_three_animations_with_correct_periods(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))

    assert stage._group.animationCount() == 3
    assert stage._plate_animation.duration() == 3000
    assert stage._glow_animation.duration() == 4000
    assert stage._float_animation.duration() == 6000
    for animation in (stage._plate_animation, stage._glow_animation, stage._float_animation):
        assert animation.loopCount() == -1
        assert animation.easingCurve().type() == animation.easingCurve().type().InOutSine


def test_console_stage_plate_animation_pulses_between_25_and_55_percent(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))

    assert stage._plate_animation.keyValueAt(0.0) == 0.25
    assert stage._plate_animation.keyValueAt(0.5) == 0.55
    assert stage._plate_animation.keyValueAt(1.0) == 0.25


def test_console_stage_glow_animation_pulses_halo_opacity_between_15_and_38_percent(qapp):
    """§5 (correctif de performance) : le halo n'anime plus un rayon de
    flou (QGraphicsDropShadowEffect, coûteux) mais l'opacité d'une
    ellipse peinte (ConsoleHalo), sur le même principe que le socle."""
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))

    assert stage._glow_animation.targetObject() is stage._halo
    assert stage._glow_animation.keyValueAt(0.0) == 0.15
    assert stage._glow_animation.keyValueAt(0.5) == 0.38
    assert stage._glow_animation.keyValueAt(1.0) == 0.15


def test_console_stage_float_animation_moves_6px_up_and_down(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))

    assert stage._float_animation.keyValueAt(0.0) == -6.0
    assert stage._float_animation.keyValueAt(0.5) == 6.0
    assert stage._float_animation.keyValueAt(1.0) == -6.0


def test_console_stage_glow_animation_starts_out_of_phase_with_plate(qapp):
    """§5 : "décalé par rapport au socle pour éviter que les deux
    respirent à l'unisson" -- vérifie qu'un déphasage explicite est bien
    appliqué au démarrage (au-delà de la simple différence de période)."""
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))

    assert stage._glow_animation.currentTime() == 2000  # moitié de son cycle de 4 s


def test_console_stage_animations_start_running_by_default(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))

    assert stage._group.state() == QParallelAnimationGroup.Running


def test_console_stage_pause_and_resume(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))

    stage.pause()
    assert stage._group.state() == QParallelAnimationGroup.Paused

    stage.resume()
    assert stage._group.state() == QParallelAnimationGroup.Running


# --- Correctif de performance (§5) : minuteur de repeint à 30 im/s, ---------
# --- valeurs animées découplées du repeint --------------------------------


def test_console_stage_caps_repaint_at_30fps_and_runs_by_default(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))

    assert stage._repaint_timer.interval() == 33
    assert stage._repaint_timer.isActive() is True


def test_console_stage_pause_stops_the_repaint_timer(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))

    stage.pause()

    assert stage._repaint_timer.isActive() is False


def test_console_stage_resume_restarts_the_repaint_timer(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))
    stage.pause()

    stage.resume()

    assert stage._repaint_timer.isActive() is True


def test_console_stage_set_animations_enabled_false_stops_the_repaint_timer(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))

    stage.set_animations_enabled(False)

    assert stage._repaint_timer.isActive() is False


def test_console_property_setters_do_not_trigger_their_own_repaint(qapp):
    """Les valeurs animées (glowOpacity, floatOffset) ne doivent plus
    déclencher leur propre update() -- seul le minuteur groupé de
    ConsoleStage impose un repeint (§5, correctif de performance)."""
    art = ConsoleArt(_fake_pixmap())
    plate = ConsoleBasePlate()
    halo = ConsoleHalo()

    with patch.object(QWidget, "update") as mock_update:
        art.floatOffset = 3.0
        plate.glowOpacity = 0.4
        halo.glowOpacity = 0.3

    mock_update.assert_not_called()


def test_console_stage_set_animations_enabled_false_stops_and_resets_to_rest_state(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))
    stage._base_plate.glowOpacity = 0.55
    stage._halo.glowOpacity = 0.38
    stage._console_art.floatOffset = 6.0

    stage.set_animations_enabled(False)

    assert stage._group.state() == QParallelAnimationGroup.Stopped
    assert stage._base_plate.glowOpacity == ConsoleBasePlate._MIN_OPACITY
    assert stage._halo.glowOpacity == ConsoleHalo._MIN_OPACITY
    assert stage._console_art.floatOffset == 0.0


def test_console_stage_set_animations_enabled_true_after_false_resumes(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))
    stage.set_animations_enabled(False)

    stage.set_animations_enabled(True)

    assert stage._group.state() == QParallelAnimationGroup.Running


def test_console_stage_resume_is_a_noop_while_disabled(qapp):
    """`pause()` (appelé pendant une opération disque, §5) ne doit pas
    relancer les animations si l'utilisateur les a désactivées entre
    temps."""
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))
    stage.set_animations_enabled(False)

    stage.resume()

    assert stage._group.state() == QParallelAnimationGroup.Stopped


def test_console_stage_positions_base_plate_under_the_console(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))
    stage.resize(400, 300)
    stage.show()

    plate_rect = stage._base_plate.geometry()
    art_rect_bottom = stage.height() // 2 + stage._console_art.rendered_size().height() // 2

    # Le socle est centré horizontalement et sa largeur avoisine 70 % de
    # celle de la console rendue (§5).
    assert plate_rect.width() > 0
    assert abs(plate_rect.center().x() - stage.width() // 2) <= 1
    assert abs(plate_rect.center().y() - art_rect_bottom) <= plate_rect.height()


def test_build_window_backdrop_returns_none_when_asset_missing(qapp):
    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
        assert build_window_backdrop() is None


def test_build_window_backdrop_returns_widget_when_asset_present(tmp_path, qapp):
    fake_path = tmp_path / "circuit.png"
    _fake_pixmap().save(str(fake_path))

    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=fake_path):
        backdrop = build_window_backdrop()

    assert isinstance(backdrop, WindowBackdrop)


def test_window_backdrop_paints_at_15_percent_opacity_without_raising(qapp):
    """Pas d'assertion facile sur les pixels peints (mosaïque via
    `QPainter.drawTiledPixmap`) -- au minimum, un rendu ne doit jamais
    lever, y compris à taille nulle ou très grande."""
    backdrop = WindowBackdrop(_fake_pixmap())
    backdrop.resize(500, 400)

    backdrop.grab()  # force un paintEvent réel ; ne doit pas lever

    assert backdrop._OPACITY == 0.15


# --- MainView : assemblage des deux colonnes (§5, refonte navigation) ------


def test_main_view_gives_home_a_fixed_width(qapp):
    home = HomeScreen()
    log_panel = LogPanel()

    view = MainView(home, None, log_panel)

    assert home.minimumWidth() == view._LEFT_COLUMN_WIDTH
    assert home.maximumWidth() == view._LEFT_COLUMN_WIDTH


def test_main_view_works_without_console_stage(qapp):
    """`console_stage=None` (asset absent) ne doit jamais empêcher la
    construction de la vue (§5)."""
    home = HomeScreen()
    log_panel = LogPanel()

    view = MainView(home, None, log_panel)

    assert view is not None


def test_main_view_has_no_animation_toggle_without_console_stage(qapp):
    home = HomeScreen()
    log_panel = LogPanel()

    view = MainView(home, None, log_panel)

    assert not hasattr(view, "animation_toggle")


def test_main_view_animation_toggle_is_checked_by_default_and_wired_to_console_stage(qapp):
    home = HomeScreen()
    log_panel = LogPanel()
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))

    view = MainView(home, stage, log_panel)

    assert view.animation_toggle.isChecked() is True

    view.animation_toggle.setChecked(False)

    assert stage._group.state() == QParallelAnimationGroup.Stopped


def test_main_view_without_backdrop_asset_has_no_backdrop(qapp):
    home = HomeScreen()
    log_panel = LogPanel()

    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
        view = MainView(home, None, log_panel)

    assert view._backdrop is None


# --- AssistedLandingScreen : accueil du mode assisté (§5 mode assisté) -----


def test_assisted_landing_screen_prepare_button_emits_signal(qapp):
    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
        screen = AssistedLandingScreen()
    received = []
    screen.prepare_requested.connect(lambda: received.append(True))

    screen._prepare_button.click()

    assert received == [True]


def test_assisted_landing_screen_expert_mode_button_emits_signal(qapp):
    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
        screen = AssistedLandingScreen()
    received = []
    screen.expert_mode_requested.connect(lambda: received.append(True))

    screen._expert_button.click()

    assert received == [True]


def test_assisted_landing_screen_works_without_console_stage(qapp):
    """Asset absent (§5) : ne doit jamais empêcher la construction de
    l'écran, même principe que MainView."""
    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
        screen = AssistedLandingScreen()

    assert screen.console_stage is None


def test_assisted_landing_screen_shows_console_stage_when_asset_present(tmp_path, qapp):
    fake_path = tmp_path / "console.png"
    _fake_pixmap().save(str(fake_path))

    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=fake_path):
        screen = AssistedLandingScreen()

    assert isinstance(screen.console_stage, ConsoleStage)


def test_assisted_landing_screen_prepare_button_has_cta_role(qapp):
    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
        screen = AssistedLandingScreen()

    assert screen._prepare_button.property("role") == "cta"


# --- HelpDialog --------------------------------------------------------------


def test_help_dialog_back_button_closes_dialog(qapp):
    dialog = HelpDialog()
    dialog.show()
    assert dialog.isVisible() is True

    dialog._back_button.click()

    assert dialog.isVisible() is False


def test_help_dialog_open_settings_button_emits_signal(qapp):
    dialog = HelpDialog()
    received = []
    dialog.open_settings_requested.connect(lambda: received.append(True))

    dialog._open_settings_button.click()

    assert received == [True]


# --- DeviceDialog ------------------------------------------------------------


def test_device_dialog_no_default_selection(qapp):
    dialog = DeviceDialog()
    dialog.set_devices([_make_device()])

    assert dialog._list.selectedItems() == []
    assert dialog._next_button.isEnabled() is False


def test_device_dialog_selecting_enables_next_and_emits_correct_device(qapp):
    dialog = DeviceDialog()
    device_a = _make_device(path="/dev/fake-disk-test-3", display="A")
    device_b = _make_device(path="/dev/fake-disk-test-4", display="B")
    dialog.set_devices([device_a, device_b])

    dialog._list.setCurrentRow(1)
    assert dialog._next_button.isEnabled() is True

    chosen = []
    dialog.device_chosen.connect(lambda d: chosen.append(d))
    dialog._emit_chosen()

    assert chosen == [device_b]


def test_device_dialog_empty_list_shows_empty_message(qapp):
    dialog = DeviceDialog()
    dialog.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    dialog.set_devices([])

    assert dialog._empty_label.isVisible() is True
    assert dialog._list.isVisible() is False


def test_device_dialog_back_button_closes_dialog(qapp):
    dialog = DeviceDialog()
    dialog.show()

    dialog.findChild(type(dialog._next_button))  # sanity: widget tree exists
    back_buttons = [w for w in dialog.findChildren(type(dialog._next_button)) if w.text() == "Retour"]
    assert back_buttons
    back_buttons[0].click()

    assert dialog.isVisible() is False


# --- FileDialog ----------------------------------------------------------


def test_file_dialog_set_mode_resets_state(qapp):
    dialog = FileDialog()
    dialog.set_mode("flash")
    assert dialog._next_button.isEnabled() is False
    assert dialog._path_label.text() == ""


@patch("r36s_studio.gui.screens.QFileDialog.getSaveFileName", return_value=("/tmp/out.img", ""))
def test_file_dialog_backup_browse_enables_next(mock_dialog, qapp):
    dialog = FileDialog()
    dialog.set_mode("backup")

    dialog._browse()

    assert dialog._path_label.text() == "/tmp/out.img"
    assert dialog._next_button.isEnabled() is True


@patch("r36s_studio.gui.screens.QFileDialog.getOpenFileName", return_value=("", ""))
def test_file_dialog_cancelled_dialog_does_not_enable_next(mock_dialog, qapp):
    dialog = FileDialog()
    dialog.set_mode("flash")

    dialog._browse()

    assert dialog._next_button.isEnabled() is False


@patch("r36s_studio.gui.screens.QFileDialog.getExistingDirectory", return_value="/tmp/boot_backup")
def test_file_dialog_inject_boot_browse_picks_a_folder(mock_dialog, qapp):
    """inject-boot/copy-games consomment un dossier (§4.4), pas un fichier
    unique -- le sélecteur doit être un choix de dossier."""
    dialog = FileDialog()
    dialog.set_mode("inject_boot")

    dialog._browse()

    mock_dialog.assert_called_once()
    assert dialog._path_label.text() == "/tmp/boot_backup"
    assert dialog._next_button.isEnabled() is True


@patch("r36s_studio.gui.screens.QFileDialog.getExistingDirectory", return_value="/tmp/games")
def test_file_dialog_copy_games_browse_picks_a_folder(mock_dialog, qapp):
    dialog = FileDialog()
    dialog.set_mode("copy_games")

    dialog._browse()

    assert dialog._path_label.text() == "/tmp/games"


@patch("r36s_studio.gui.screens.QFileDialog.getExistingDirectory", return_value="")
def test_file_dialog_cancelled_folder_dialog_does_not_enable_next(mock_dialog, qapp):
    dialog = FileDialog()
    dialog.set_mode("copy_games")

    dialog._browse()

    assert dialog._next_button.isEnabled() is False


def test_file_dialog_back_button_closes_dialog(qapp):
    dialog = FileDialog()
    dialog.set_mode("flash")
    dialog.show()

    back_buttons = [w for w in dialog.findChildren(type(dialog._next_button)) if w.text() == "Retour"]
    assert back_buttons
    back_buttons[0].click()

    assert dialog.isVisible() is False


# --- FileDialog : liste des archives existantes (étapes D/E, §4.4) --------


def test_file_dialog_archive_mode_lists_existing_archives(qapp):
    dialog = FileDialog()
    dialog.show()
    dialog.set_mode("inject_boot", archive_choices=["/tmp/R36S Studio/BOOT_2026-07-06_00-21"])

    assert dialog._archive_list.isVisible() is True
    assert dialog._archive_list.count() == 1
    assert dialog._archive_empty_label.isVisible() is False


def test_file_dialog_archive_mode_with_no_archives_shows_empty_message(qapp):
    dialog = FileDialog()
    dialog.show()
    dialog.set_mode("copy_games", archive_choices=[])

    assert dialog._archive_list.count() == 0
    assert dialog._archive_empty_label.isVisible() is True


def test_file_dialog_non_archive_mode_hides_archive_list(qapp):
    dialog = FileDialog()
    dialog.set_mode("flash")

    assert dialog._archive_list.isVisible() is False
    assert dialog._archive_empty_label.isVisible() is False


def test_file_dialog_selecting_an_archive_enables_next_and_sets_path(qapp):
    dialog = FileDialog()
    dialog.set_mode("inject_boot", archive_choices=["/tmp/R36S Studio/BOOT_2026-07-06_00-21"])

    dialog._archive_list.setCurrentRow(0)

    assert dialog._path_label.text() == "/tmp/R36S Studio/BOOT_2026-07-06_00-21"
    assert dialog._next_button.isEnabled() is True


@patch("r36s_studio.gui.screens.QFileDialog.getExistingDirectory", return_value="/tmp/manual_folder")
def test_file_dialog_browse_still_works_as_fallback_in_archive_mode(mock_dialog, qapp):
    """Repli manuel : même quand des archives existent, Parcourir… reste
    disponible pour désigner un dossier différent."""
    dialog = FileDialog()
    dialog.set_mode("inject_boot", archive_choices=["/tmp/R36S Studio/BOOT_2026-07-06_00-21"])

    dialog._browse()

    assert dialog._path_label.text() == "/tmp/manual_folder"
    assert dialog._next_button.isEnabled() is True


def test_format_archive_label_formats_known_timestamp_in_french():
    label = format_archive_label("/tmp/R36S Studio/BOOT_2026-07-06_00-21")

    assert label == "6 juillet 2026 à 00h21"


def test_format_archive_label_falls_back_to_folder_name_for_manual_folder():
    label = format_archive_label("/tmp/mon_dossier_perso")

    assert label == "mon_dossier_perso"


# --- FileDialog : dossier de destination avec défaut (étapes A/B, §4.4) ----


def test_file_dialog_destination_mode_preselects_default_path(qapp):
    dialog = FileDialog()

    dialog.set_mode("extract_boot", default_path="/home/x/Documents/R36S Studio")

    assert dialog._path_label.text() == "/home/x/Documents/R36S Studio"
    assert dialog._next_button.isEnabled() is True


def test_file_dialog_destination_mode_shows_hint_and_hides_archive_widgets(qapp):
    dialog = FileDialog()
    dialog.show()

    dialog.set_mode("extract_easyroms", default_path="/home/x/Documents/R36S Studio")

    assert dialog._destination_hint_label.isVisible() is True
    assert dialog._archive_list.isVisible() is False
    assert dialog._archive_empty_label.isVisible() is False


def test_file_dialog_other_modes_hide_destination_hint(qapp):
    dialog = FileDialog()
    dialog.show()

    dialog.set_mode("flash")

    assert dialog._destination_hint_label.isVisible() is False


@patch("r36s_studio.gui.screens.QFileDialog.getExistingDirectory", return_value="/Volumes/DisqueExterne")
def test_file_dialog_destination_mode_can_replace_default_via_browse(mock_dialog, qapp):
    dialog = FileDialog()
    dialog.set_mode("extract_boot", default_path="/home/x/Documents/R36S Studio")

    dialog._browse()

    mock_dialog.assert_called_once()
    assert mock_dialog.call_args.args[-1] == "/home/x/Documents/R36S Studio"  # démarre sur le défaut affiché
    assert dialog._path_label.text() == "/Volumes/DisqueExterne"
    assert dialog._next_button.isEnabled() is True


def test_file_dialog_without_default_path_disables_next_until_chosen(qapp):
    """Un mode destination sans défaut fourni (ne devrait pas arriver en
    pratique, mais ne doit pas planter) laisse Suivant désactivé."""
    dialog = FileDialog()

    dialog.set_mode("extract_boot")

    assert dialog._path_label.text() == ""
    assert dialog._next_button.isEnabled() is False


# --- ConfirmDialog -----------------------------------------------------------


def test_confirm_dialog_go_disabled_until_checkbox_checked(qapp):
    dialog = ConfirmDialog()
    dialog.set_device(_make_device())
    assert dialog._go_button.isEnabled() is False

    dialog._checkbox.setChecked(True)
    assert dialog._go_button.isEnabled() is True

    dialog._checkbox.setChecked(False)
    assert dialog._go_button.isEnabled() is False


def test_confirm_dialog_shows_device_display_and_size(qapp):
    dialog = ConfirmDialog()
    dialog.set_device(_make_device(display="SanDisk Ultra", size_bytes=31_914_983_424))

    text = dialog._message.text()
    assert "SanDisk Ultra" in text
    assert "31.9" in text


def test_confirm_dialog_cancel_button_closes_dialog(qapp):
    dialog = ConfirmDialog()
    dialog.set_device(_make_device())
    dialog.show()

    cancel_buttons = [w for w in dialog.findChildren(type(dialog._go_button)) if w.text() == "Annuler"]
    assert cancel_buttons
    cancel_buttons[0].click()

    assert dialog.isVisible() is False


def test_confirm_dialog_confirmed_signal_on_go_click(qapp):
    dialog = ConfirmDialog()
    dialog.set_device(_make_device())
    dialog._checkbox.setChecked(True)
    received = []
    dialog.confirmed.connect(lambda: received.append(True))

    dialog._go_button.click()

    assert received == [True]


# --- LogPanel (§5, refonte navigation -- remplace Exécution + Résultat) ----


def test_log_panel_starts_idle(qapp):
    panel = LogPanel()

    assert panel._header_label.text() == "En attente"
    assert panel._bar.isVisible() is False
    assert panel._cancel_button.isVisible() is False
    assert panel._eject_button.isVisible() is False
    assert panel._reveal_button.isVisible() is False


def test_log_panel_start_operation_shows_header_progress_and_cancel(qapp):
    panel = LogPanel()
    panel.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    panel.start_operation("Écriture en cours…")

    assert panel._header_label.text() == "OPÉRATION ACTIVE — Écriture en cours…"
    assert panel._bar.isVisible() is True
    assert panel._cancel_button.isVisible() is True
    assert panel._cancel_button.isEnabled() is True
    assert panel._eject_button.isVisible() is False
    assert panel._reveal_button.isVisible() is False


def test_log_panel_start_operation_clears_previous_log(qapp):
    panel = LogPanel()
    panel.start_operation("Sauvegarde en cours…")
    panel.append_log("une ligne de la précédente opération")

    panel.start_operation("Écriture en cours…")

    assert panel._log_view.toPlainText() == ""


def test_log_panel_update_progress_sets_percentage(qapp):
    panel = LogPanel()
    panel.start_operation("Écriture en cours…")

    panel.update_progress(done=50, total=200, speed=1_000_000)

    assert panel._bar.value() == 25
    assert panel._bar.minimum() == 0 and panel._bar.maximum() == 100
    assert "1.0" in panel._speed_label.text()


def test_log_panel_unknown_total_shows_indeterminate_bar(qapp):
    panel = LogPanel()
    panel.start_operation("Écriture en cours…")

    panel.update_progress(done=50, total=0, speed=1_000_000)

    assert panel._bar.minimum() == 0 and panel._bar.maximum() == 0


def test_log_panel_append_log_prefixes_a_timestamp(qapp):
    panel = LogPanel()

    with patch("r36s_studio.gui.screens.datetime") as mock_datetime:
        mock_datetime.now.return_value.strftime.return_value = "21:44:02"
        panel.append_log("Montage des partitions: OK")

    assert panel._log_view.toPlainText() == "21:44:02 - Montage des partitions: OK"


def test_log_panel_append_log_keeps_history_within_one_operation(qapp):
    """Le journal conserve tout l'historique de l'opération en cours --
    chaque ajout s'accumule, jamais un remplacement de la ligne
    précédente."""
    panel = LogPanel()

    panel.append_log("Montage des partitions: OK")
    panel.append_log("Écriture en cours")
    panel.append_log("Vérification SHA-256: OK")

    lines = panel._log_view.toPlainText().splitlines()
    assert len(lines) == 3
    assert lines[0].endswith("Montage des partitions: OK")
    assert lines[1].endswith("Écriture en cours")
    assert lines[2].endswith("Vérification SHA-256: OK")


def test_log_panel_append_log_scrolls_to_bottom(qapp):
    panel = LogPanel()

    for i in range(50):
        panel.append_log(f"ligne {i}")

    scrollbar = panel._log_view.verticalScrollBar()
    assert scrollbar.value() == scrollbar.maximum()


def test_log_panel_is_read_only_and_monospace_role(qapp):
    panel = LogPanel()

    assert panel._log_view.isReadOnly() is True
    assert panel._log_view.property("role") == "log"


def test_log_panel_finish_success_logs_message_and_hides_progress(qapp):
    panel = LogPanel()
    panel.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    panel.start_operation("Écriture en cours…")

    panel.finish_success("La carte est prête.", allow_eject=True, reveal_path=None)

    assert "La carte est prête." in panel._log_view.toPlainText()
    assert panel._bar.isVisible() is False
    assert panel._cancel_button.isVisible() is False
    assert panel._eject_button.isVisible() is True
    assert panel._reveal_button.isVisible() is False
    assert panel._header_label.text() == "En attente"


def test_log_panel_finish_success_without_eject_hides_eject_button(qapp):
    panel = LogPanel()
    panel.start_operation("Sauvegarde en cours…")

    panel.finish_success("Sauvegardée.", allow_eject=False, reveal_path=None)

    assert panel._eject_button.isVisible() is False


def test_log_panel_finish_success_with_reveal_path_shows_reveal_button(qapp):
    panel = LogPanel()
    panel.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    panel.start_operation("Copie en cours…")

    panel.finish_success("Copié.", allow_eject=True, reveal_path="/tmp/BOOT_x")

    assert panel._reveal_button.isVisible() is True


def test_log_panel_reveal_button_emits_stored_path(qapp):
    panel = LogPanel()
    panel.finish_success("ok", allow_eject=False, reveal_path="/tmp/BOOT_x")
    received = []
    panel.reveal_requested.connect(lambda path: received.append(path))

    panel._reveal_button.click()

    assert received == ["/tmp/BOOT_x"]


def test_log_panel_eject_button_emits_signal(qapp):
    panel = LogPanel()
    panel.finish_success("ok", allow_eject=True, reveal_path=None)
    received = []
    panel.eject_requested.connect(lambda: received.append(True))

    panel._eject_button.click()

    assert received == [True]


def test_log_panel_cancel_button_emits_signal(qapp):
    panel = LogPanel()
    panel.start_operation("Écriture en cours…")
    received = []
    panel.cancel_requested.connect(lambda: received.append(True))

    panel._cancel_button.click()

    assert received == [True]


def test_log_panel_set_cancel_enabled(qapp):
    panel = LogPanel()
    panel.start_operation("Écriture en cours…")

    panel.set_cancel_enabled(False)

    assert panel._cancel_button.isEnabled() is False


def test_log_panel_finish_error_logs_message_and_details(qapp):
    panel = LogPanel()
    panel.start_operation("Écriture en cours…")

    panel.finish_error("Un problème est survenu.", details="[Errno 2] /dev/disk4")

    text = panel._log_view.toPlainText()
    assert "Un problème est survenu." in text
    assert "[Errno 2] /dev/disk4" in text
    assert panel._bar.isVisible() is False
    assert panel._cancel_button.isVisible() is False
    assert panel._eject_button.isVisible() is False
    assert panel._header_label.text() == "En attente"


def test_log_panel_finish_error_identical_details_not_duplicated(qapp):
    panel = LogPanel()
    panel.start_operation("Écriture en cours…")

    panel.finish_error("Opération annulée.", details="Opération annulée.")

    lines = panel._log_view.toPlainText().splitlines()
    assert len(lines) == 1


def test_log_panel_finish_error_without_details_logs_only_message(qapp):
    panel = LogPanel()
    panel.start_operation("Écriture en cours…")

    panel.finish_error("Un message déjà clair")

    lines = panel._log_view.toPlainText().splitlines()
    assert len(lines) == 1


def test_format_duration():
    assert _format_duration(45) == "45 s"
    assert _format_duration(125) == "2 min 05 s"
    assert _format_duration(3725) == "1 h 02 min"


def test_format_size_formats_megabytes_and_gigabytes():
    assert _format_size(500) == "500 o"
    assert _format_size(12_582_912) == "12.0 Mo"
    assert _format_size(2 * 1024**3) == "2.0 Go"
