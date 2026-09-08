"""Tests de la vue principale et des fenêtres modales (gui/screens.py) —
construction et logique des signaux, en mode Qt "offscreen" (fixture
`qapp`)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from r36s_studio.detect import StepStatus
from r36s_studio.devices import Device
from r36s_studio.gui.screens import (
    AssistedLandingScreen,
    BackupKindDialog,
    ConfirmDialog,
    ConsoleArt,
    ConsoleStage,
    ConsoleTerminalOverlay,
    DeviceDialog,
    FileDialog,
    FullDiskAccessScreen,
    HelpDialog,
    HomeScreen,
    LogPanel,
    MainView,
    ResetCardLabelDialog,
    RocknixVariantDialog,
    WindowBackdrop,
    WizardStepPanel,
    _format_duration,
    _format_size,
    build_console_stage,
    build_window_backdrop,
    format_archive_label,
)
from PySide6.QtWidgets import QLabel, QWidget


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


def test_home_screen_backup_system_tile_emits_signal(qapp):
    screen = HomeScreen()
    received = []
    screen.backup_system_selected.connect(lambda: received.append(True))

    screen.backup_system_selected.emit()

    assert received == [True]


def test_home_screen_reset_card_tile_emits_signal(qapp):
    screen = HomeScreen()
    received = []
    screen.reset_card_selected.connect(lambda: received.append(True))

    screen.reset_card_selected.emit()

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


def test_home_screen_status_shows_system_incompatible_badge_for_rocknix_card(qapp):
    screen = HomeScreen()
    screen.show()

    screen.set_status({"extract_boot": StepStatus.SYSTEM_INCOMPATIBLE})

    assert screen._badges["extract_boot"].text() == "Non applicable — carte ROCKNIX"
    assert screen._badges["extract_boot"].property("badgeKind") == "system_incompatible"


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


def test_home_screen_assisted_mode_button_emits_signal(qapp):
    """Symétrique du bouton « Mode expert » de AssistedLandingScreen (§5
    mode assisté) : sans lui, basculer en mode expert était un aller
    simple -- ui_mode étant persisté, l'utilisateur restait bloqué en
    mode expert même après redémarrage."""
    screen = HomeScreen()
    received = []
    screen.assisted_mode_requested.connect(lambda: received.append(True))

    screen._assisted_mode_button.click()

    assert received == [True]


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
    assert screen._backup_system_row.isEnabled() is False
    assert screen._reset_card_row.isEnabled() is False


def test_home_screen_set_busy_false_reenables_steps_and_backup_row(qapp):
    screen = HomeScreen()
    screen.set_busy(True)

    screen.set_busy(False)

    for row in screen._tiles.values():
        assert row.isEnabled() is True
    assert screen._backup_row.isEnabled() is True
    assert screen._backup_system_row.isEnabled() is True
    assert screen._reset_card_row.isEnabled() is True


def test_home_screen_set_status_disables_backup_rows_without_a_device(qapp):
    """« Par sécurité » (sauvegarde complète et sauvegarde système sans
    les jeux) exige une carte, contrairement aux six étapes lettrées
    (toujours cliquables par principe, §4.5) -- désactivé dès qu'aucune
    carte n'est détectée, pour ne jamais pouvoir être lancé dans le vide
    (bug rapporté : carte éjectée entre-temps, opération quand même
    déclenchable)."""
    screen = HomeScreen()

    screen.set_status({}, device=None, has_device=False)

    assert screen._backup_row.isEnabled() is False
    assert screen._backup_system_row.isEnabled() is False
    assert screen._reset_card_row.isEnabled() is False
    for row in screen._tiles.values():
        assert row.isEnabled() is True  # les six étapes, elles, restent cliquables


def test_home_screen_set_status_enables_backup_rows_with_a_device(qapp):
    screen = HomeScreen()
    screen.set_status({}, device=None, has_device=False)

    screen.set_status({}, device=_make_device(), has_device=True)

    assert screen._backup_row.isEnabled() is True
    assert screen._backup_system_row.isEnabled() is True
    assert screen._reset_card_row.isEnabled() is True


def test_home_screen_set_status_without_has_device_argument_leaves_backup_rows_enabled(qapp):
    """Sans information explicite sur la présence d'une carte (avant tout
    premier `_refresh_home_state`, ou un appel qui ne la précise pas), les
    lignes restent activées -- jamais désactivées par défaut sans raison."""
    screen = HomeScreen()

    screen.set_status({})

    assert screen._backup_row.isEnabled() is True
    assert screen._backup_system_row.isEnabled() is True
    assert screen._reset_card_row.isEnabled() is True


def test_home_screen_busy_state_overrides_device_presence_for_backup_rows(qapp):
    """Une opération en cours doit rester prioritaire : `set_status`
    (ex. rafraîchi entre-temps, le bouton Rafraîchir n'est pas désactivé
    par `set_busy`) ne doit jamais réactiver les lignes pendant qu'une
    opération tourne."""
    screen = HomeScreen()
    screen.set_busy(True)

    screen.set_status({}, device=_make_device(), has_device=True)

    assert screen._backup_row.isEnabled() is False
    assert screen._backup_system_row.isEnabled() is False
    assert screen._reset_card_row.isEnabled() is False


def test_home_screen_set_busy_also_disables_assisted_mode_button(qapp):
    """Changer de mode en plein flash ou en pleine copie laisserait un job
    orphelin (§5 mode assisté) -- le bouton de bascule doit être désactivé
    pendant l'opération, comme les six étapes."""
    screen = HomeScreen()

    screen.set_busy(True)
    assert screen._assisted_mode_button.isEnabled() is False

    screen.set_busy(False)
    assert screen._assisted_mode_button.isEnabled() is True


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
    art = ConsoleArt(_fake_pixmap())

    assert art._OPACITY == 0.70
    assert art.graphicsEffect() is None


def test_console_art_paints_without_raising_at_various_sizes(qapp):
    art = ConsoleArt(_fake_pixmap())
    for w, h in [(0, 0), (1, 1), (200, 220), (400, 300)]:
        art.resize(w, h)
        art.grab()  # force un paintEvent réel


def test_console_art_scales_with_aspect_ratio_preserved(qapp):
    """Animations retirées (§5) : plus de marge de flottaison à réserver,
    la mise à l'échelle utilise directement `self.size()`."""
    art = ConsoleArt(_fake_pixmap())
    art.resize(200, 200)
    art.show()  # resizeEvent n'est livré qu'une fois le widget affiché

    rendered = art.rendered_size()
    assert rendered.width() > 0 and rendered.height() > 0
    assert rendered.width() <= 200 and rendered.height() <= 200


# --- ConsoleTerminalOverlay : activité disque en temps réel (§5) -----------
#
# Correction de conception, confirmée sur du vrai matériel : ce terminal a
# été accusé à tort d'un ralentissement de la sauvegarde système d'un
# facteur dix, puis entièrement retiré -- la cause réelle, confirmée en
# bissectant par mesure du débit CLI pur (donc sans ce terminal), était une
# carte SD d'origine de console non reconnue (~6 Mo/s en lecture contre
# ~88 Mo/s pour une SanDisk, capacité exposée très inférieure à celle
# annoncée -- §8). Rétabli : ce code n'a jamais été la cause du
# ralentissement rapporté.


def test_console_terminal_overlay_starts_empty_with_no_fake_activity(qapp):
    """Au repos, rien d'inventé -- pas de ligne tant qu'aucun événement de
    progression réel n'a été ajouté (§2 règle 5)."""
    overlay = ConsoleTerminalOverlay()

    assert overlay._lines == []


def test_console_terminal_overlay_append_line_records_real_events_only(qapp):
    overlay = ConsoleTerminalOverlay()

    overlay.append_line("0x0000000000  +4.0 Mo  18.4 Mo/s")
    overlay.append_line("0x0000400000  +4.0 Mo  19.1 Mo/s")

    assert overlay._lines == ["0x0000000000  +4.0 Mo  18.4 Mo/s", "0x0000400000  +4.0 Mo  19.1 Mo/s"]


def test_console_terminal_overlay_clear_lines_returns_to_rest_state(qapp):
    overlay = ConsoleTerminalOverlay()
    overlay.append_line("0x0000000000  +4.0 Mo  18.4 Mo/s")

    overlay.clear_lines()

    assert overlay._lines == []


def test_console_terminal_overlay_caps_memory_at_max_lines(qapp):
    overlay = ConsoleTerminalOverlay()

    for i in range(overlay._MAX_LINES + 50):
        overlay.append_line(str(i))

    assert len(overlay._lines) == overlay._MAX_LINES
    assert overlay._lines[-1] == str(overlay._MAX_LINES + 49)  # les plus récentes, pas les plus anciennes


def test_console_terminal_overlay_paints_without_raising_at_various_sizes(qapp):
    overlay = ConsoleTerminalOverlay()
    overlay.append_line("0x0000000000  +4.0 Mo  18.4 Mo/s")
    for w, h in [(0, 0), (1, 1), (140, 60), (300, 120)]:
        overlay.resize(w, h)
        overlay.grab()


def test_console_terminal_overlay_cursor_blinks_on_a_timer(qapp):
    overlay = ConsoleTerminalOverlay()
    initial = overlay._cursor_on

    overlay._toggle_cursor()

    assert overlay._cursor_on is not initial


# --- correctif de performance : repeint cadencé, jamais depuis un setter --
# (appliqué par précaution -- ce n'était pas la cause du ralentissement, ---
# mais reste une bonne pratique, sans coût) --------------------------------


def test_console_terminal_overlay_append_line_never_repaints_directly(qapp):
    overlay = ConsoleTerminalOverlay()

    with patch.object(QWidget, "update") as mock_update:
        overlay.append_line("0x0000000000  +4.0 Mo  18.4 Mo/s")

    mock_update.assert_not_called()
    assert overlay._dirty is True


def test_console_terminal_overlay_toggle_cursor_never_repaints_directly(qapp):
    overlay = ConsoleTerminalOverlay()

    with patch.object(QWidget, "update") as mock_update:
        overlay._toggle_cursor()

    mock_update.assert_not_called()
    assert overlay._dirty is True


def test_console_terminal_overlay_clear_lines_never_repaints_directly(qapp):
    overlay = ConsoleTerminalOverlay()
    overlay.append_line("une ligne")
    overlay._dirty = False

    with patch.object(QWidget, "update") as mock_update:
        overlay.clear_lines()

    mock_update.assert_not_called()
    assert overlay._dirty is True


def test_console_terminal_overlay_repaint_timer_runs_at_30fps(qapp):
    overlay = ConsoleTerminalOverlay()

    assert overlay._repaint_timer.interval() == 33
    assert overlay._repaint_timer.isActive() is True


def test_console_terminal_overlay_flush_repaint_only_updates_when_dirty(qapp):
    overlay = ConsoleTerminalOverlay()
    overlay._dirty = False

    with patch.object(QWidget, "update") as mock_update:
        overlay._flush_repaint()
    mock_update.assert_not_called()

    overlay._dirty = True
    with patch.object(QWidget, "update") as mock_update:
        overlay._flush_repaint()
    mock_update.assert_called_once()
    assert overlay._dirty is False


def test_console_terminal_overlay_caches_font_and_only_rebuilds_on_line_height_change(qapp):
    overlay = ConsoleTerminalOverlay()
    overlay.resize(300, 120)

    font_a = overlay._terminal_font()
    font_b = overlay._terminal_font()
    assert font_a is font_b  # même instance -- pas reconstruite à chaque appel

    overlay.resize(300, 500)  # hauteur de ligne différente
    font_c = overlay._terminal_font()
    assert font_c is not font_a


# --- ConsoleStage : positionnement du terminal en proportion de l'image ----
# --- rendue, jamais en coordonnées absolues (§5) ---------------------------


def test_console_stage_positions_terminal_within_the_rendered_console(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))
    stage.resize(400, 300)
    stage.show()

    terminal_rect = stage._terminal.geometry()
    art_rect = stage._console_art.geometry()

    assert terminal_rect.width() > 0
    assert terminal_rect.height() > 0
    # Entièrement contenu dans la zone de la console (le rectangle de
    # l'écran est une fraction de l'image rendue, jamais hors de ses
    # limites).
    assert art_rect.contains(terminal_rect)


def test_console_stage_terminal_rect_scales_proportionally_not_absolutely(qapp):
    """Même piège que le rognage du bas de la console (déjà corrigé pour
    la flottaison, désormais retirée) : la position/taille du terminal
    doit suivre la taille rendue, jamais une valeur en pixels fixe."""
    small = ConsoleStage(ConsoleArt(_fake_pixmap()))
    small.resize(200, 150)
    small.show()

    large = ConsoleStage(ConsoleArt(_fake_pixmap()))
    large.resize(800, 600)
    large.show()

    assert large._terminal.geometry().width() > small._terminal.geometry().width() * 2
    assert large._terminal.geometry().height() > small._terminal.geometry().height() * 2


def test_console_stage_nothing_clips_on_various_box_shapes(qapp):
    """Formes de boîte réelles (mode expert paysage, accueil assisté plus
    carré, redimensionnement en cours) -- ne doit jamais lever ni placer
    le terminal hors de `ConsoleStage`."""
    for w, h in [(360, 420), (640, 220), (60, 50), (1, 1)]:
        stage = ConsoleStage(ConsoleArt(_fake_pixmap()))
        stage.resize(w, h)
        stage.show()
        assert stage.rect().contains(stage._terminal.geometry())


def test_console_stage_append_line_forwards_to_terminal(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))

    stage.append_line("0x0000000000  +4.0 Mo  18.4 Mo/s")

    assert stage._terminal._lines == ["0x0000000000  +4.0 Mo  18.4 Mo/s"]


def test_console_stage_start_activity_clears_the_terminal(qapp):
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))
    stage.append_line("ligne d'une opération précédente")

    stage.start_activity()

    assert stage._terminal._lines == []


def test_console_stage_stop_activity_clears_the_terminal(qapp):
    """Au repos, l'écran de la console n'affiche qu'un curseur -- jamais
    les dernières lignes d'une activité terminée."""
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))
    stage.append_line("dernière ligne de l'opération")

    stage.stop_activity()

    assert stage._terminal._lines == []


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


def test_main_view_has_no_animation_toggle(qapp):
    """Réglage retiré avec les animations elles-mêmes (§5) : plus rien à
    activer/désactiver, la console est désormais toujours immobile."""
    home = HomeScreen()
    log_panel = LogPanel()
    stage = ConsoleStage(ConsoleArt(_fake_pixmap()))

    view = MainView(home, stage, log_panel)

    assert not hasattr(view, "animation_toggle")


def test_main_view_without_backdrop_asset_has_no_backdrop(qapp):
    home = HomeScreen()
    log_panel = LogPanel()

    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
        view = MainView(home, None, log_panel)

    assert view._backdrop is None


def test_main_view_without_wizard_panel_shows_home_only(qapp):
    """Sans `wizard_panel` (mode expert seul, appels existants) : le
    comportement d'avant l'ajout du mode assisté ne doit pas changer."""
    home = HomeScreen()
    log_panel = LogPanel()

    view = MainView(home, None, log_panel)

    assert view._left_stack.currentWidget() is home


def test_main_view_accepts_a_wizard_panel_and_gives_it_the_same_fixed_width(qapp):
    home = HomeScreen()
    log_panel = LogPanel()
    wizard_panel = WizardStepPanel()

    view = MainView(home, None, log_panel, wizard_panel=wizard_panel)

    assert wizard_panel.minimumWidth() == view._LEFT_COLUMN_WIDTH
    assert wizard_panel.maximumWidth() == view._LEFT_COLUMN_WIDTH


def test_main_view_show_home_and_show_wizard_panel_switch_the_left_column(qapp):
    home = HomeScreen()
    log_panel = LogPanel()
    wizard_panel = WizardStepPanel()

    view = MainView(home, None, log_panel, wizard_panel=wizard_panel)
    assert view._left_stack.currentWidget() is home  # home par défaut

    view.show_wizard_panel()
    assert view._left_stack.currentWidget() is wizard_panel

    view.show_home()
    assert view._left_stack.currentWidget() is home


# --- FullDiskAccessScreen : bienvenue macOS, Accès complet au disque (§3) --


def test_full_disk_access_screen_open_settings_button_emits_signal(qapp):
    screen = FullDiskAccessScreen()
    received = []
    screen.open_settings_requested.connect(lambda: received.append(True))

    screen._open_settings_button.click()

    assert received == [True]


def test_full_disk_access_screen_done_button_emits_recheck_signal(qapp):
    screen = FullDiskAccessScreen()
    received = []
    screen.recheck_requested.connect(lambda: received.append(True))

    screen._done_button.click()

    assert received == [True]


def test_full_disk_access_screen_still_not_detected_hidden_by_default(qapp):
    screen = FullDiskAccessScreen()

    assert screen._still_not_detected_label.isVisible() is False


def test_full_disk_access_screen_set_still_not_detected_shows_label(qapp):
    """Après un « J'ai terminé » qui ne détecte toujours pas l'autorisation
    -- jamais un clic silencieusement ignoré (§5)."""
    screen = FullDiskAccessScreen()
    screen.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    screen.set_still_not_detected(True)
    assert screen._still_not_detected_label.isVisible() is True

    screen.set_still_not_detected(False)
    assert screen._still_not_detected_label.isVisible() is False


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


def test_assisted_landing_screen_set_busy_disables_expert_button(qapp):
    """Symétrique de HomeScreen.set_busy (§5 mode assisté) -- changer de
    mode en plein flash ou en pleine copie laisserait un job orphelin."""
    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
        screen = AssistedLandingScreen()

    screen.set_busy(True)
    assert screen._expert_button.isEnabled() is False


def test_assisted_landing_screen_backup_system_button_emits_signal(qapp):
    """Sauvegarde système sans les jeux, aussi proposée comme option du
    mode assisté (§4.3), pas seulement depuis l'écran expert."""
    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
        screen = AssistedLandingScreen()
    received = []
    screen.backup_system_requested.connect(lambda: received.append(True))

    screen._backup_system_button.click()

    assert received == [True]


def test_assisted_landing_screen_set_busy_disables_backup_system_button(qapp):
    with patch("r36s_studio.gui.screens.asset_paths.asset_path", return_value=None):
        screen = AssistedLandingScreen()

    screen.set_busy(True)
    assert screen._backup_system_button.isEnabled() is False

    screen.set_busy(False)
    assert screen._expert_button.isEnabled() is True


# --- WizardStepPanel : une étape à la fois, mode assisté (§5) --------------


def test_wizard_step_panel_show_step_sets_title_instruction_and_status(qapp):
    panel = WizardStepPanel()

    panel.show_step("Titre", "Consigne", "Statut", can_continue=False)

    assert panel._title_label.text() == "Titre"
    assert panel._instruction_label.text() == "Consigne"
    assert panel._status_label.text() == "Statut"


def test_wizard_step_panel_show_step_hides_refresh_by_default(qapp):
    panel = WizardStepPanel()

    panel.show_step("Titre", "Consigne")

    assert panel._refresh_button.isVisible() is False


def test_wizard_step_panel_show_step_can_show_refresh(qapp):
    """Étapes 1/4 (détection) uniquement -- relance la recherche
    manuellement quand le sondage automatique n'aboutit pas."""
    panel = WizardStepPanel()
    panel.show()  # isVisible() ne reflète setVisible() qu'une fois affiché

    panel.show_step("Titre", "Consigne", show_refresh=True)

    assert panel._refresh_button.isVisible() is True


def test_wizard_step_panel_refresh_button_emits_signal(qapp):
    panel = WizardStepPanel()
    panel.show_step("Titre", "Consigne", show_refresh=True)
    received = []
    panel.refresh_requested.connect(lambda: received.append(True))

    panel._refresh_button.click()

    assert received == [True]


def test_wizard_step_panel_show_step_defaults_continue_to_disabled(qapp):
    panel = WizardStepPanel()

    panel.show_step("Titre", "Consigne")

    assert panel._continue_button.isEnabled() is False


def test_wizard_step_panel_show_step_can_enable_continue(qapp):
    panel = WizardStepPanel()

    panel.show_step("Titre", "Consigne", can_continue=True)

    assert panel._continue_button.isEnabled() is True


def test_wizard_step_panel_set_can_continue_toggles_the_button(qapp):
    panel = WizardStepPanel()
    panel.show_step("Titre", "Consigne", can_continue=False)

    panel.set_can_continue(True)
    assert panel._continue_button.isEnabled() is True

    panel.set_can_continue(False)
    assert panel._continue_button.isEnabled() is False


def test_wizard_step_panel_set_status_updates_the_status_label(qapp):
    panel = WizardStepPanel()

    panel.set_status("Carte reconnue")

    assert panel._status_label.text() == "Carte reconnue"


def test_wizard_step_panel_continue_button_emits_signal(qapp):
    panel = WizardStepPanel()
    panel.show_step("Titre", "Consigne", can_continue=True)
    received = []
    panel.continue_requested.connect(lambda: received.append(True))

    panel._continue_button.click()

    assert received == [True]


def test_wizard_step_panel_cancel_button_emits_signal(qapp):
    panel = WizardStepPanel()
    received = []
    panel.cancel_requested.connect(lambda: received.append(True))

    panel._cancel_button.click()

    assert received == [True]


def test_wizard_step_panel_show_step_hides_error_buttons(qapp):
    panel = WizardStepPanel()
    panel.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    panel.show_error()

    panel.show_step("Titre", "Consigne")

    assert panel._resume_button.isVisible() is False
    assert panel._expert_button.isVisible() is False
    assert panel._continue_button.isVisible() is True


def test_wizard_step_panel_show_error_reveals_resume_and_expert_buttons(qapp):
    panel = WizardStepPanel()
    panel.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    panel.show_step("Titre", "Consigne", can_continue=True)

    panel.show_error()

    assert panel._continue_button.isVisible() is False
    assert panel._resume_button.isVisible() is True
    assert panel._expert_button.isVisible() is True


# --- show_next_step_choice : sauvegarde système depuis l'accueil assisté ---
# --- (§4.3) -- jamais un écran sans issue une fois l'opération terminée ----


def test_wizard_step_panel_show_next_step_choice_sets_title_and_instruction(qapp):
    panel = WizardStepPanel()

    panel.show_next_step_choice("Titre", "Consigne")

    assert panel._title_label.text() == "Titre"
    assert panel._instruction_label.text() == "Consigne"


def test_wizard_step_panel_show_next_step_choice_hides_wizard_specific_buttons(qapp):
    """Jamais les boutons Continuer/Reprendre/Mode expert/Actualiser/Annuler
    du vrai parcours guidé -- déjà câblés à des gestionnaires qui supposent
    un parcours actif (`_on_wizard_continue`/`_cancel_wizard`), qu'il ne
    faut jamais déclencher par accident depuis cet état."""
    panel = WizardStepPanel()
    panel.show()  # isVisible() ne reflète setVisible() qu'une fois affiché
    panel.show_step("Titre", "Consigne", can_continue=True, show_refresh=True)

    panel.show_next_step_choice("Titre", "Consigne")

    assert panel._continue_button.isVisible() is False
    assert panel._resume_button.isVisible() is False
    assert panel._expert_button.isVisible() is False
    assert panel._refresh_button.isVisible() is False
    assert panel._cancel_button.isVisible() is False


def test_wizard_step_panel_show_next_step_choice_shows_both_buttons_by_default(qapp):
    panel = WizardStepPanel()
    panel.show()

    panel.show_next_step_choice("Titre", "Consigne")

    assert panel._prepare_card_button.isVisible() is True
    assert panel._return_home_button.isVisible() is True


def test_wizard_step_panel_show_next_step_choice_can_hide_prepare_card_button(qapp):
    """Après un échec (rien à préparer), seule l'option retour reste
    proposée -- jamais un choix qui n'a pas de sens."""
    panel = WizardStepPanel()
    panel.show()

    panel.show_next_step_choice("Titre", "Consigne", show_prepare_card=False)

    assert panel._prepare_card_button.isVisible() is False
    assert panel._return_home_button.isVisible() is True


def test_wizard_step_panel_prepare_card_button_emits_signal(qapp):
    panel = WizardStepPanel()
    panel.show_next_step_choice("Titre", "Consigne")
    received = []
    panel.prepare_card_requested.connect(lambda: received.append(True))

    panel._prepare_card_button.click()

    assert received == [True]


def test_wizard_step_panel_return_home_button_emits_signal(qapp):
    panel = WizardStepPanel()
    panel.show_next_step_choice("Titre", "Consigne")
    received = []
    panel.return_to_home_requested.connect(lambda: received.append(True))

    panel._return_home_button.click()

    assert received == [True]


def test_wizard_step_panel_show_step_hides_next_step_choice_buttons(qapp):
    """Défensif : un vrai pas du parcours guidé, montré après un passage
    par `show_next_step_choice`, ne doit jamais laisser les boutons de
    l'état précédent visibles par accident."""
    panel = WizardStepPanel()
    panel.show()
    panel.show_next_step_choice("Titre", "Consigne")

    panel.show_step("Titre", "Consigne")

    assert panel._prepare_card_button.isVisible() is False
    assert panel._return_home_button.isVisible() is False


def test_wizard_step_panel_resume_button_emits_signal(qapp):
    panel = WizardStepPanel()
    panel.show_error()
    received = []
    panel.resume_requested.connect(lambda: received.append(True))

    panel._resume_button.click()

    assert received == [True]


def test_wizard_step_panel_expert_button_emits_signal(qapp):
    panel = WizardStepPanel()
    panel.show_error()
    received = []
    panel.expert_mode_requested.connect(lambda: received.append(True))

    panel._expert_button.click()

    assert received == [True]


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


# --- FileDialog : mode backup_system (§4.3, sauvegarde sans les jeux) -----


def test_file_dialog_backup_system_prefills_suggested_path_and_enables_next(qapp):
    dialog = FileDialog()
    dialog.show()

    dialog.set_mode("backup_system", default_path="/home/x/Documents/R36S Studio/systeme_2026-07-06_00-21.img")

    assert dialog._path_label.text() == "/home/x/Documents/R36S Studio/systeme_2026-07-06_00-21.img"
    assert dialog._next_button.isEnabled() is True


def test_file_dialog_backup_system_hides_firmware_choice(qapp):
    dialog = FileDialog()
    dialog.show()

    dialog.set_mode("backup_system", default_path="/tmp/systeme.img")

    assert all(row.isVisible() is False for row in dialog._firmware_rows)
    assert dialog._releases_button.isVisible() is False


def test_file_dialog_estimated_size_label_hidden_by_default(qapp):
    dialog = FileDialog()
    dialog.show()

    dialog.set_mode("backup_system", default_path="/tmp/systeme.img")

    assert dialog._system_backup_size_label.isVisible() is False


def test_file_dialog_set_estimated_size_shows_the_label(qapp):
    """Taille affichée directement sur la fenêtre de confirmation (§4.3 :
    « affiche la taille estimée et demande confirmation avant de lancer »)
    -- pas seulement dans le journal de bord, qu'un débutant pourrait ne
    pas remarquer."""
    dialog = FileDialog()
    dialog.show()
    dialog.set_mode("backup_system", default_path="/tmp/systeme.img")

    dialog.set_estimated_size("environ 8,4 Go (sans les jeux)")

    assert dialog._system_backup_size_label.isVisible() is True
    assert "8,4 Go" in dialog._system_backup_size_label.text()


def test_file_dialog_set_mode_clears_estimated_size_label(qapp):
    dialog = FileDialog()
    dialog.show()
    dialog.set_mode("backup_system", default_path="/tmp/systeme.img")
    dialog.set_estimated_size("environ 8,4 Go (sans les jeux)")

    dialog.set_mode("backup")

    assert dialog._system_backup_size_label.isVisible() is False


# --- FileDialog : bouton releases, flash uniquement (§5 mode assisté) ------


def test_file_dialog_shows_releases_button_only_in_flash_mode(qapp):
    dialog = FileDialog()
    dialog.show()

    dialog.set_mode("flash")
    assert dialog._releases_button.isVisible() is True

    dialog.set_mode("backup")
    assert dialog._releases_button.isVisible() is False

    dialog.set_mode("extract_boot")
    assert dialog._releases_button.isVisible() is False

    dialog.set_mode("inject_boot")
    assert dialog._releases_button.isVisible() is False


def test_file_dialog_releases_button_emits_signal(qapp):
    dialog = FileDialog()
    dialog.set_mode("flash")
    received = []
    dialog.releases_requested.connect(lambda firmware: received.append(firmware))

    dialog._releases_button.click()

    assert received == ["arkos"]


def test_file_dialog_releases_button_emits_emuelec_when_selected(qapp):
    """La page ouverte doit correspondre au firmware réellement
    sélectionné à l'instant du clic, pas à une valeur mémorisée
    séparément (bug potentiel : `set_mode` présélectionne le firmware
    sans émettre `firmware_changed`, §5)."""
    dialog = FileDialog()
    dialog.set_mode("flash")
    dialog._firmware_radios["emuelec"].setChecked(True)
    received = []
    dialog.releases_requested.connect(lambda firmware: received.append(firmware))

    dialog._releases_button.click()

    assert received == ["emuelec"]


# --- FileDialog : choix du firmware, flash uniquement (§4.6 catalogue) ----


def test_file_dialog_firmware_choice_hidden_outside_flash_mode(qapp):
    dialog = FileDialog()
    dialog.show()

    dialog.set_mode("backup")

    assert all(row.isVisible() is False for row in dialog._firmware_rows)


def test_file_dialog_builds_one_radio_per_catalog_entry(qapp):
    from r36s_studio.identify.firmware_catalog import FIRMWARE_CATALOG

    dialog = FileDialog()

    assert set(dialog._firmware_radios.keys()) == {entry.id for entry in FIRMWARE_CATALOG}
    assert len(dialog._firmware_rows) == len(FIRMWARE_CATALOG)


def test_file_dialog_defaults_to_arkos_when_no_firmware_given(qapp):
    dialog = FileDialog()
    dialog.show()

    dialog.set_mode("flash")

    assert dialog._firmware_radios["arkos"].isChecked() is True
    assert dialog._releases_button.isVisible() is True
    assert dialog._rocknix_download_button.isVisible() is False


def test_file_dialog_set_mode_initializes_firmware_from_config(qapp):
    dialog = FileDialog()
    dialog.show()

    dialog.set_mode("flash", firmware="rocknix")

    assert dialog._firmware_radios["rocknix"].isChecked() is True
    assert dialog._releases_button.isVisible() is False
    assert dialog._rocknix_download_button.isVisible() is True


def test_file_dialog_set_mode_initializes_firmware_emuelec(qapp):
    dialog = FileDialog()
    dialog.show()

    dialog.set_mode("flash", firmware="emuelec")

    assert dialog._firmware_radios["emuelec"].isChecked() is True
    assert dialog._releases_button.isVisible() is True  # même comportement qu'ArkOS : lien manuel
    assert dialog._rocknix_download_button.isVisible() is False
    assert dialog._download_hint.isVisible() is True  # rappel générique, plus seulement ArkOS


def test_file_dialog_set_mode_unknown_firmware_falls_back_to_first_catalog_entry(qapp):
    dialog = FileDialog()
    dialog.show()

    dialog.set_mode("flash", firmware="n'importe quoi")

    assert dialog._firmware_radios["arkos"].isChecked() is True


def test_file_dialog_selecting_rocknix_swaps_buttons_and_emits_firmware_changed(qapp):
    dialog = FileDialog()
    dialog.show()
    dialog.set_mode("flash")
    received = []
    dialog.firmware_changed.connect(lambda firmware: received.append(firmware))

    dialog._firmware_radios["rocknix"].setChecked(True)

    assert received == ["rocknix"]
    assert dialog._rocknix_download_button.isVisible() is True
    assert dialog._releases_button.isVisible() is False


def test_file_dialog_selecting_arkos_back_swaps_buttons_and_emits_firmware_changed(qapp):
    dialog = FileDialog()
    dialog.show()
    dialog.set_mode("flash", firmware="rocknix")
    received = []
    dialog.firmware_changed.connect(lambda firmware: received.append(firmware))

    dialog._firmware_radios["arkos"].setChecked(True)

    assert received == ["arkos"]
    assert dialog._releases_button.isVisible() is True
    assert dialog._rocknix_download_button.isVisible() is False


def test_file_dialog_selecting_emuelec_swaps_buttons_and_emits_firmware_changed(qapp):
    dialog = FileDialog()
    dialog.show()
    dialog.set_mode("flash")
    received = []
    dialog.firmware_changed.connect(lambda firmware: received.append(firmware))

    dialog._firmware_radios["emuelec"].setChecked(True)

    assert received == ["emuelec"]
    assert dialog._releases_button.isVisible() is True
    assert dialog._rocknix_download_button.isVisible() is False


@pytest.mark.parametrize("firmware_id", ["amberelec", "minui", "r36droid", "andr36oid"])
def test_file_dialog_selecting_new_catalog_entry_is_manual_link(qapp, firmware_id):
    dialog = FileDialog()
    dialog.show()
    dialog.set_mode("flash")
    received = []
    dialog.firmware_changed.connect(lambda firmware: received.append(firmware))

    dialog._firmware_radios[firmware_id].setChecked(True)

    assert received == [firmware_id]
    assert dialog._releases_button.isVisible() is True
    assert dialog._download_hint.isVisible() is True
    assert dialog._rocknix_download_button.isVisible() is False


def test_file_dialog_firmware_badges_reflect_catalog_status(qapp):
    from r36s_studio.identify.firmware_catalog import FIRMWARE_BY_ID

    dialog = FileDialog()

    for firmware_id, radio in dialog._firmware_radios.items():
        row = radio.parentWidget()
        badges = [w for w in row.findChildren(QLabel) if w.property("role") == "badge"]
        assert len(badges) == 1
        assert badges[0].property("badgeKind") == FIRMWARE_BY_ID[firmware_id].status


def test_file_dialog_manual_download_hint_visible_for_manual_link_firmware(qapp):
    dialog = FileDialog()
    dialog.show()

    dialog.set_mode("flash", firmware="arkos")
    assert dialog._download_hint.isVisible() is True

    dialog.set_mode("flash", firmware="rocknix")
    assert dialog._download_hint.isVisible() is False

    dialog.set_mode("backup")
    assert dialog._download_hint.isVisible() is False


def test_file_dialog_switching_back_to_arkos_shows_hint_again(qapp):
    dialog = FileDialog()
    dialog.show()
    dialog.set_mode("flash", firmware="rocknix")

    dialog._firmware_radios["arkos"].setChecked(True)

    assert dialog._download_hint.isVisible() is True


def test_file_dialog_rocknix_download_button_emits_signal(qapp):
    dialog = FileDialog()
    dialog.set_mode("flash", firmware="rocknix")
    received = []
    dialog.rocknix_download_requested.connect(lambda: received.append(True))

    dialog._rocknix_download_button.click()

    assert received == [True]


def test_file_dialog_set_mode_does_not_emit_firmware_changed_on_its_own(qapp):
    """Réinitialiser le mode reflète la configuration existante, ce n'est
    pas un choix de l'utilisateur -- `main_window.py` ne doit persister
    `firmware` que sur une vraie interaction (§5)."""
    dialog = FileDialog()
    dialog.show()
    received = []
    dialog.firmware_changed.connect(lambda firmware: received.append(firmware))

    dialog.set_mode("flash", firmware="rocknix")
    dialog.set_mode("flash", firmware="arkos")

    assert received == []


# --- RocknixVariantDialog : choix entre plusieurs variantes ROCKNIX (§5) --


def _rocknix_variant(name, sha=None):
    from r36s_studio.identify.rocknix import RocknixAsset

    return RocknixAsset(name=name, download_url=f"https://example.invalid/{name}", size_bytes=100), sha


def test_rocknix_variant_dialog_lists_full_names(qapp):
    variant_a = _rocknix_variant("ROCKNIX-RK3326.aarch64-20260801-a.img.gz")
    variant_b = _rocknix_variant("ROCKNIX-RK3326.aarch64-20260801-b.img.gz")
    dialog = RocknixVariantDialog()

    dialog.set_variants([variant_a, variant_b])

    assert dialog._list.count() == 2
    assert dialog._list.item(0).text() == "ROCKNIX-RK3326.aarch64-20260801-a.img.gz"
    assert dialog._list.item(1).text() == "ROCKNIX-RK3326.aarch64-20260801-b.img.gz"


def test_rocknix_variant_dialog_next_disabled_until_selection(qapp):
    dialog = RocknixVariantDialog()
    dialog.set_variants([_rocknix_variant("a.img.gz"), _rocknix_variant("b.img.gz")])

    assert dialog._next_button.isEnabled() is False

    dialog._list.setCurrentRow(0)

    assert dialog._next_button.isEnabled() is True


def test_rocknix_variant_dialog_emits_chosen_asset_and_checksum(qapp):
    variant_a = _rocknix_variant("a.img.gz", sha="cafebabe" * 8)
    variant_b = _rocknix_variant("b.img.gz")
    dialog = RocknixVariantDialog()
    dialog.set_variants([variant_a, variant_b])
    received = []
    dialog.variant_chosen.connect(lambda asset, sha: received.append((asset, sha)))

    dialog._list.setCurrentRow(1)
    dialog._next_button.click()

    assert received == [variant_b]


def test_rocknix_variant_dialog_closes_without_emitting(qapp):
    dialog = RocknixVariantDialog()
    dialog.set_variants([_rocknix_variant("a.img.gz")])
    dialog.show()
    received = []
    dialog.variant_chosen.connect(lambda asset, sha: received.append((asset, sha)))

    dialog.close()

    assert received == []
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


# --- BackupKindDialog : choix complet/système du parcours de clonage (§5) -


def test_backup_kind_dialog_full_copy_emits_signal_and_closes(qapp):
    dialog = BackupKindDialog()
    dialog.show()
    received = []
    dialog.full_copy_requested.connect(lambda: received.append(True))

    dialog._full_button.click()

    assert received == [True]
    assert dialog.isVisible() is False


def test_backup_kind_dialog_system_only_emits_signal_and_closes(qapp):
    dialog = BackupKindDialog()
    dialog.show()
    received = []
    dialog.system_only_requested.connect(lambda: received.append(True))

    dialog._system_button.click()

    assert received == [True]
    assert dialog.isVisible() is False


def test_backup_kind_dialog_cancel_emits_signal_and_closes(qapp):
    dialog = BackupKindDialog()
    dialog.show()
    received = []
    dialog.cancelled.connect(lambda: received.append(True))

    dialog._on_cancel()

    assert received == [True]
    assert dialog.isVisible() is False


def test_backup_kind_dialog_full_copy_is_the_default_action(qapp):
    """Copie complète est mise en avant par défaut (§5) : c'est le bouton
    `default` de la boîte de dialogue (activé par Entrée) et il porte le
    rôle visuel "primary" -- ni l'un ni l'autre choix n'est pré-coché ou
    imposé, seul le focus par défaut favorise la copie complète."""
    dialog = BackupKindDialog()

    assert dialog._full_button.isDefault() is True
    assert dialog._full_button.property("role") == "primary"


# --- ResetCardLabelDialog : « Remettre la carte à zéro » (§4.3 bis) -------


def test_reset_card_label_dialog_set_default_label_prefills_the_field(qapp):
    dialog = ResetCardLabelDialog()

    dialog.set_default_label("SDCARD")

    assert dialog._label_edit.text() == "SDCARD"


def test_reset_card_label_dialog_continue_emits_the_trimmed_label_and_closes(qapp):
    dialog = ResetCardLabelDialog()
    dialog.show()
    dialog._label_edit.setText("  MACARTE  ")
    received = []
    dialog.label_chosen.connect(received.append)

    dialog._continue_button.click()

    assert received == ["MACARTE"]
    assert dialog.isVisible() is False


def test_reset_card_label_dialog_never_emits_an_empty_label(qapp):
    """Une étiquette vide n'a pas de sens pour un formatage natif -- ne
    doit jamais atteindre `_start_worker` (§4.3 bis)."""
    dialog = ResetCardLabelDialog()
    dialog.show()
    dialog._label_edit.setText("   ")
    received = []
    dialog.label_chosen.connect(received.append)

    dialog._continue_button.click()

    assert received == []
    assert dialog.isVisible() is True  # reste ouverte, pas de fermeture silencieuse


def test_reset_card_label_dialog_return_pressed_also_continues(qapp):
    dialog = ResetCardLabelDialog()
    dialog.show()
    dialog._label_edit.setText("MACARTE")
    received = []
    dialog.label_chosen.connect(received.append)

    dialog._label_edit.returnPressed.emit()

    assert received == ["MACARTE"]


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


# --- progression par étapes réelles (§2 n°5, §4.3 bis « Remettre la carte
# à zéro ») -- jamais un minuteur : la barre n'avance qu'à chaque étape
# effectivement terminée, avec son nom affiché plutôt qu'un débit/temps
# restant inventés.


def test_log_panel_update_step_progress_sets_percentage_from_step_count(qapp):
    panel = LogPanel()
    panel.start_operation("Remise à zéro en cours…")

    panel.update_step_progress(step_index=1, step_count=4, step_name="Création de la partition…")

    assert panel._bar.value() == 25
    assert panel._bar.minimum() == 0 and panel._bar.maximum() == 100


def test_log_panel_update_step_progress_shows_step_name_not_a_fabricated_eta(qapp):
    """Le temps restant n'a pas de sens pour une opération de quelques
    secondes et non prévisible (§ demande explicite) -- le nom de l'étape
    remplace le débit/l'estimation, jamais affichés côte à côte."""
    panel = LogPanel()
    panel.start_operation("Remise à zéro en cours…")

    panel.update_step_progress(step_index=2, step_count=4, step_name="Formatage exFAT…")

    assert panel._speed_label.text() == "Formatage exFAT…"
    assert panel._eta_label.isVisible() is False


def test_log_panel_update_step_progress_reaches_100_percent_on_the_last_step(qapp):
    panel = LogPanel()
    panel.start_operation("Remise à zéro en cours…")

    panel.update_step_progress(step_index=4, step_count=4, step_name="Terminé.")

    assert panel._bar.value() == 100


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
