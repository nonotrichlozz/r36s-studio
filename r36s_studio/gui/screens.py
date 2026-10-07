# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Vue principale et fenêtres modales de l'application (§5, refonte
navigation) : plus une succession d'écrans dans un `QStackedWidget`, mais
une structure permanente à deux colonnes (`HomeScreen` à gauche, l'image de
la console et le journal de bord à droite, assemblées par `main_window.py`)
devant laquelle les choix ponctuels (carte, fichier, confirmation, aide)
s'ouvrent en fenêtres modales (`Dialog` et ses sous-classes) plutôt que de
remplacer la vue. Chaque widget communique avec `main_window.py`
uniquement par signaux — aucun ne connaît les autres.

Vocabulaire : aucun terme technique dans les libellés visibles (§5) — le
chemin technique du périphérique n'apparaît que dans le journal de bord."""

from __future__ import annotations

import platform
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from r36s_studio.android.emulators import (
    CATEGORIES as ANDROID_EMULATOR_CATEGORIES,
    SENTINEL_A_VERIFIER,
    EmulatorCatalog,
    EmulatorEntry,
    count_by_category as android_count_emulators_by_category,
    filter_by_category as android_filter_emulators_by_category,
    filter_for_device as android_filter_emulators_for_device,
)
from r36s_studio.android.models import VALEUR_INCONNUE, AndroidDeviceInfo, DetectionResult
# Réutilisation explicitement demandée par docs/android-adb.md (§ Identification
# et propositions : "réutiliser le client de consoles_diverses") -- lecture
# seule d'un type de données public et d'une fonction de traduction déjà
# publique, jamais une modification du package (règle d'isolation, son
# propre CLAUDE.md : "Ne modifie jamais r36s-studio-cloud"/"Ne touche pas
# ... à consoles_diverses/").
from r36s_studio import i18n
from r36s_studio.consoles_diverses.models import FicheConsole
from r36s_studio.consoles_diverses.strings import tr as _consoles_diverses_tr
from r36s_studio.detect import (
    COPY_GAMES,
    EJECT,
    FLASH,
    IDENTIFY,
    OTHER_SYSTEMS,
    CardSystem,
    StepStatus,
)
from r36s_studio.devices import Device
from r36s_studio.doublons.normalize import extract_tags, region_rank
from r36s_studio.doublons.scan import ExactDuplicateGroup, ExclusionWarning, ScanResult, Unit, VersionGroup
from r36s_studio.identify import IdentifyFailureReason, IdentifyResult
from r36s_studio.identify.firmware_catalog import FIRMWARE_BY_ID, FIRMWARE_CATALOG
from r36s_studio.partitions.archives import parse_archive_timestamp

from . import asset_paths, build_info, theme
from .reveal import reveal_label
from .strings import tr

_STATUS_TEXT_KEYS = {
    StepStatus.AVAILABLE: "status_available",
    StepStatus.DONE: "status_done",
    StepStatus.NOT_RELEVANT: "status_not_relevant",
    StepStatus.PLATFORM_LIMITED: "status_platform_limited",
    StepStatus.SYSTEM_INCOMPATIBLE: "status_system_incompatible",
}

# Couleur du badge (theme.py, sélecteur QSS `QLabel[badgeKind="..."]`) pour
# chaque statut -- distinct de `_STATUS_TEXT_KEYS` (le texte affiché).
_BADGE_KIND_BY_STATUS = {
    StepStatus.AVAILABLE: "available",
    StepStatus.DONE: "done",
    StepStatus.NOT_RELEVANT: "not_relevant",
    StepStatus.PLATFORM_LIMITED: "platform_limited",
    StepStatus.SYSTEM_INCOMPATIBLE: "system_incompatible",
}


def card_system_name(card_system: Optional[CardSystem]) -> str:
    """Nom du système d'une carte non ArkOS, tel qu'affiché (« EmuELEC »,
    « ROCKNIX », « non ArkOS » si non reconnu ou inconnu de l'appelant)."""
    if card_system not in OTHER_SYSTEMS:
        card_system = CardSystem.UNKNOWN
    return tr(f"card_system_{card_system.value}")


def _status_text(status: StepStatus, card_system: Optional[CardSystem]) -> str:
    return tr(_STATUS_TEXT_KEYS[status], system=card_system_name(card_system))


def _banner_state_text(is_arkos: bool, card_system: Optional[CardSystem]) -> str:
    """« Carte EmuELEC reconnue » plutôt que « Carte non préparée » : une
    carte d'un autre système reconnu n'a rien de mal préparé."""
    if is_arkos:
        return tr("home_banner_state_arkos")
    if card_system in OTHER_SYSTEMS:
        return tr("home_banner_state_other_system", system=card_system_name(card_system))
    return tr("home_banner_state_unprepared")


# Les six étapes chronologiques fixes du workflow à deux cartes (§4.4/§4.5),
# dans l'ordre A à F. Clés identiques aux noms de job déjà utilisés par
# `partition_runner.py`/`__main__.py`. La lettre est l'icône affichée à
# gauche de chaque ligne (§5 -- pas d'image, un simple repère de position
# dans le parcours, cohérent avec le texte déjà lettré A à F).
_STEP_SPECS = [
    ("extract_boot", "A", "home_step_a_title", "home_step_a_desc"),
    ("extract_easyroms", "B", "home_step_b_title", "home_step_b_desc"),
    ("flash", "C", "home_step_c_title", "home_step_c_desc"),
    ("inject_boot", "D", "home_step_d_title", "home_step_d_desc"),
    ("copy_games", "E", "home_step_e_title", "home_step_e_desc"),
    ("eject", "F", "home_step_f_title", "home_step_f_desc"),
]


class Screen(QWidget):
    """Base commune aux widgets permanents de la vue principale (§5) : pose
    `WA_StyledBackground` une seule fois. Un `QWidget` nu n'honore pas
    `background-color` en feuille de style sans cet attribut (piège Qt
    classique) -- sans lui, le fond du « poste de commande » ne serait
    peint que par accident, quand le widget se trouve avoir un parent qui
    le peint à sa place (vrai dans `MainWindow`, faux dès qu'il est affiché
    seul, ex. rendu isolé pour vérification visuelle ou tests)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)


class Dialog(QDialog):
    """Base commune aux fenêtres modales (§5, refonte navigation) : les
    choix qui demandaient un écran séparé (carte, fichier, confirmation,
    aide) s'ouvrent maintenant par-dessus la vue principale plutôt que de
    la remplacer. `open()` (modal, non bloquant -- contrairement à
    `exec()`) laisse la structure à deux colonnes visible derrière et
    garde le style signal/slot déjà utilisé partout ailleurs
    (`main_window.py` ne bloque jamais en attendant une réponse). Pose
    `WA_StyledBackground` comme `Screen` (même piège Qt, voir `theme.py`).
    Chaque sous-classe se contente d'émettre des signaux sur l'action de
    l'utilisateur -- c'est `main_window.py` qui décide quand fermer la
    fenêtre, jamais la fenêtre elle-même (sauf annulation, qui se ferme
    directement : rien à faire suivre dans ce cas)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setModal(True)


class ClickableFrame(QFrame):
    """Cadre cliquable : sert de ligne d'étape ou de bandeau (accueil), à
    la place d'un `QPushButton` -- un bouton ne permet pas de styler
    indépendamment l'icône, le titre/la description et le badge qu'il
    contient (chacun a sa propre couleur, voir `theme.py`)."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "row")
        self.setCursor(Qt.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        self.clicked.emit()
        super().mousePressEvent(event)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 (nom imposé par Qt)
        # Qt ne délivre déjà plus les clics à un widget désactivé -- ce
        # n'est que l'apparence qu'il faut corriger à la main, pour ne pas
        # suggérer une ligne cliquable pendant une opération (§5,
        # `HomeScreen.set_busy`). Le curseur d'abord ; la teinte de fond
        # `:disabled` (theme.py) existe mais reste trop proche de la
        # surface habituelle pour se voir clairement seule sur une palette
        # sombre -- une opacité réduite est un signal "désactivé"
        # nettement plus lisible, quelle que soit la couleur exacte en
        # dessous.
        super().setEnabled(enabled)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        if enabled:
            self.setGraphicsEffect(None)
        else:
            effect = QGraphicsOpacityEffect(self)
            effect.setOpacity(0.45)
            self.setGraphicsEffect(effect)


class _ConsoleIcon(QWidget):
    """Icône du bandeau de détection (§5) : dessinée avec `QPainter`
    plutôt qu'une image ou une police d'icônes -- un simple boîtier
    arrondi avec deux petits boutons, dans la couleur d'accent, cohérent
    avec le reste de l'habillage sans dépendance externe. `size` (défaut
    28, celui du bandeau de `HomeScreen`) -- constantes de dessin
    calibrées pour 28 et remises à l'échelle proportionnellement (même
    principe que `_icon_scale` pour les tuiles, plus bas dans ce fichier)
    pour rester nette à une taille bien plus grande (110 dans le panneau
    « Carte détectée » de l'accueil assisté, §5)."""

    _REFERENCE_SIZE = 28.0

    def __init__(self, size: int = 28, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        s = self.width() / self._REFERENCE_SIZE
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.ACCENT_CYAN))
        pen.setWidthF(max(1.5, 2 * s))
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        body = self.rect().adjusted(round(2 * s), round(5 * s), -round(2 * s), -round(5 * s))
        painter.drawRoundedRect(body, round(4 * s), round(4 * s))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.ACCENT_CYAN))
        for dx in (8, 13):
            painter.drawEllipse(body.right() - round(dx * s), body.center().y() - round(2 * s), round(3 * s), round(3 * s))


# --- Icônes de tuile (accueil assisté, §5 refonte menu de tuiles) ---------
#
# Même principe que `_ConsoleIcon` ci-dessus : formes géométriques simples
# dessinées au `QPainter`, jamais une image ni une police d'icônes. Chaque
# fonction reçoit la couleur à utiliser (jamais un hex en dur ici -- la
# couleur vient de `Tile`, choisie parmi les constantes de `theme.py` selon
# le rôle de la tuile) plutôt que de la fixer elle-même.
#
# Constantes calibrées à l'origine pour une icône de 28×28 (taille du
# bandeau de détection, `_ConsoleIcon`) -- `_icon_scale` les remet à
# l'échelle proportionnellement à la taille réelle demandée (56 en tuile
# normale, 76 sur la tuile 1, §5 refonte visuelle) plutôt que de fixer des
# décalages en pixels absolus, qui rendraient l'icône minuscule dans une
# tuile agrandie.
_ICON_REFERENCE_SIZE = 28.0


def _icon_scale(rect: QRect) -> float:
    return min(rect.width(), rect.height()) / _ICON_REFERENCE_SIZE


def _icon_pen(color: QColor, rect: QRect, width: float = 2.0) -> QPen:
    pen = QPen(color)
    pen.setWidthF(max(1.5, width * _icon_scale(rect)))
    return pen


def _tile_icon_prepare(painter: QPainter, rect: QRect, color: QColor) -> None:
    s = _icon_scale(rect)
    painter.setPen(_icon_pen(color, rect))
    painter.setBrush(Qt.NoBrush)
    body = rect.adjusted(round(4 * s), round(2 * s), -round(4 * s), -round(2 * s))
    painter.drawRoundedRect(body, round(3 * s), round(3 * s))
    cx = body.center().x()
    painter.drawLine(cx, body.bottom() - round(3 * s), cx, body.top() + round(3 * s))
    painter.drawLine(cx, body.top() + round(3 * s), cx - round(4 * s), body.top() + round(8 * s))
    painter.drawLine(cx, body.top() + round(3 * s), cx + round(4 * s), body.top() + round(8 * s))


def _tile_icon_identify(painter: QPainter, rect: QRect, color: QColor) -> None:
    s = _icon_scale(rect)
    painter.setPen(_icon_pen(color, rect))
    painter.setBrush(Qt.NoBrush)
    glass = rect.adjusted(round(2 * s), round(2 * s), -round(9 * s), -round(9 * s))
    painter.drawEllipse(glass)
    painter.drawLine(glass.bottomRight(), rect.bottomRight() - QPoint(round(1 * s), round(1 * s)))


def _tile_icon_backup(painter: QPainter, rect: QRect, color: QColor) -> None:
    s = _icon_scale(rect)
    painter.setPen(_icon_pen(color, rect))
    painter.setBrush(Qt.NoBrush)
    cx = rect.center().x()
    painter.drawLine(cx, rect.top() + round(3 * s), cx, rect.bottom() - round(8 * s))
    painter.drawLine(cx, rect.bottom() - round(8 * s), cx - round(4 * s), rect.bottom() - round(13 * s))
    painter.drawLine(cx, rect.bottom() - round(8 * s), cx + round(4 * s), rect.bottom() - round(13 * s))
    painter.drawLine(rect.left() + round(3 * s), rect.bottom() - round(3 * s), rect.right() - round(3 * s), rect.bottom() - round(3 * s))


def _tile_icon_flash(painter: QPainter, rect: QRect, color: QColor) -> None:
    s = _icon_scale(rect)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    cx, cy = rect.center().x(), rect.center().y()
    points = [
        QPoint(cx + round(3 * s), rect.top() + round(2 * s)),
        QPoint(rect.left() + round(6 * s), cy + round(1 * s)),
        QPoint(cx, cy + round(1 * s)),
        QPoint(cx - round(3 * s), rect.bottom() - round(2 * s)),
        QPoint(rect.right() - round(6 * s), cy - round(1 * s)),
        QPoint(cx, cy - round(1 * s)),
    ]
    painter.drawPolygon(QPolygon(points))


def _tile_icon_copy_games(painter: QPainter, rect: QRect, color: QColor) -> None:
    s = _icon_scale(rect)
    painter.setPen(_icon_pen(color, rect))
    painter.setBrush(Qt.NoBrush)
    body = rect.adjusted(round(4 * s), round(4 * s), -round(4 * s), -round(4 * s))
    painter.drawRoundedRect(body, round(3 * s), round(3 * s))
    y = body.top() + round(6 * s)
    for _ in range(3):
        painter.drawLine(body.left() + round(3 * s), y, body.right() - round(3 * s), y)
        y += round(4 * s)


def _tile_icon_duplicates(painter: QPainter, rect: QRect, color: QColor) -> None:
    s = _icon_scale(rect)
    painter.setPen(_icon_pen(color, rect))
    painter.setBrush(Qt.NoBrush)
    back = rect.adjusted(round(2 * s), round(2 * s), -round(9 * s), -round(9 * s))
    front = rect.adjusted(round(9 * s), round(9 * s), -round(2 * s), -round(2 * s))
    painter.drawRoundedRect(back, round(2 * s), round(2 * s))
    painter.drawRoundedRect(front, round(2 * s), round(2 * s))


def _tile_icon_sort(painter: QPainter, rect: QRect, color: QColor) -> None:
    """« Ranger mes jeux » (docs/tri-roms.md) : trois rayonnages empilés,
    chacun avec un jeu rangé -- un dossier par console."""
    s = _icon_scale(rect)
    painter.setPen(_icon_pen(color, rect))
    painter.setBrush(Qt.NoBrush)
    left = rect.left() + round(2 * s)
    right = rect.right() - round(2 * s)
    shelf_height = round(6 * s)
    top = rect.top() + round(3 * s)
    for index in range(3):
        y = top + index * (shelf_height + round(2 * s))
        painter.drawLine(left, y + shelf_height, right, y + shelf_height)
        box_left = left + round((2 + 5 * index) * s)
        painter.drawRect(box_left, y + round(1 * s), round(4 * s), shelf_height - round(1 * s))


def _tile_icon_inject_boot(painter: QPainter, rect: QRect, color: QColor) -> None:
    s = _icon_scale(rect)
    painter.setPen(_icon_pen(color, rect))
    painter.setBrush(Qt.NoBrush)
    screen = rect.adjusted(round(2 * s), round(2 * s), -round(2 * s), -round(9 * s))
    painter.drawRoundedRect(screen, round(2 * s), round(2 * s))
    painter.drawLine(
        rect.center().x() - round(4 * s), rect.bottom() - round(3 * s), rect.center().x() + round(4 * s), rect.bottom() - round(3 * s)
    )


def _tile_icon_eject(painter: QPainter, rect: QRect, color: QColor) -> None:
    s = _icon_scale(rect)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    triangle = QPolygon(
        [
            QPoint(rect.center().x(), rect.top() + round(2 * s)),
            QPoint(rect.left() + round(4 * s), rect.center().y() + round(2 * s)),
            QPoint(rect.right() - round(4 * s), rect.center().y() + round(2 * s)),
        ]
    )
    painter.drawPolygon(triangle)
    painter.drawRect(
        QRect(rect.left() + round(4 * s), rect.bottom() - round(6 * s), rect.width() - round(8 * s), round(4 * s))
    )


def _tile_icon_reset_card(painter: QPainter, rect: QRect, color: QColor) -> None:
    s = _icon_scale(rect)
    painter.setPen(_icon_pen(color, rect))
    painter.setBrush(Qt.NoBrush)
    arc_rect = rect.adjusted(round(3 * s), round(3 * s), -round(3 * s), -round(3 * s))
    painter.drawArc(arc_rect, 40 * 16, 260 * 16)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    tip = QPoint(arc_rect.right() - round(2 * s), arc_rect.top() + round(4 * s))
    painter.drawPolygon(
        QPolygon([tip, tip + QPoint(-round(6 * s), -round(2 * s)), tip + QPoint(-round(2 * s), round(5 * s))])
    )


def _tile_icon_help(painter: QPainter, rect: QRect, color: QColor) -> None:
    s = _icon_scale(rect)
    painter.setPen(_icon_pen(color, rect))
    painter.setBrush(Qt.NoBrush)
    circle = rect.adjusted(round(2 * s), round(2 * s), -round(2 * s), -round(2 * s))
    painter.drawEllipse(circle)
    # `QFont(theme.FONT_FAMILY)` interpréterait la chaîne de repli CSS
    # ("-apple-system, 'Segoe UI', ...") comme un unique nom de police --
    # Qt ne le trouve alors jamais et substitue un glyphe de remplacement
    # (rectangle vide) au lieu du "?" -- constaté en rendant l'icône hors
    # écran avant ce correctif. `QFont()` (police système par défaut, même
    # principe que `ConsoleTerminalOverlay._terminal_font`, qui utilise
    # `setFamilies` plutôt que le constructeur pour la même raison) laisse
    # Qt choisir une police réellement installée.
    font = QFont()
    font.setBold(True)
    font.setPixelSize(max(round(circle.height() - 10 * s), 8))
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(circle, Qt.AlignCenter, "?")


def _tile_icon_web(painter: QPainter, rect: QRect, color: QColor) -> None:
    """Globe simple (cercle + équateur + méridien) -- tuile personnelle
    « Web », jamais distribuée (config.py::personal_web_url)."""
    s = _icon_scale(rect)
    painter.setPen(_icon_pen(color, rect))
    painter.setBrush(Qt.NoBrush)
    circle = rect.adjusted(round(2 * s), round(2 * s), -round(2 * s), -round(2 * s))
    painter.drawEllipse(circle)
    painter.drawLine(circle.left(), circle.center().y(), circle.right(), circle.center().y())
    meridian = QRect(circle.center().x() - round(4 * s), circle.top(), round(8 * s), circle.height())
    painter.drawEllipse(meridian)


def _tile_icon_android(painter: QPainter, rect: QRect, color: QColor) -> None:
    """Téléphone/console portable simple (rectangle arrondi vertical +
    petite barre « bouton » en bas) -- tuile « Console Android »
    (android/, étape 1)."""
    s = _icon_scale(rect)
    painter.setPen(_icon_pen(color, rect))
    painter.setBrush(Qt.NoBrush)
    body = rect.adjusted(round(4 * s), round(1 * s), -round(4 * s), -round(1 * s))
    painter.drawRoundedRect(body, round(2 * s), round(2 * s))
    painter.drawLine(
        body.center().x() - round(2 * s),
        body.bottom() - round(3 * s),
        body.center().x() + round(2 * s),
        body.bottom() - round(3 * s),
    )


_TILE_ICON_PAINTERS = {
    "prepare": _tile_icon_prepare,
    "identify": _tile_icon_identify,
    "backup": _tile_icon_backup,
    "flash": _tile_icon_flash,
    "copy_games": _tile_icon_copy_games,
    "duplicates": _tile_icon_duplicates,
    "sort": _tile_icon_sort,
    "inject_boot": _tile_icon_inject_boot,
    "eject": _tile_icon_eject,
    "android": _tile_icon_android,
    "reset_card": _tile_icon_reset_card,
    "help": _tile_icon_help,
    "web": _tile_icon_web,
}


class _TileIcon(QWidget):
    """Icône d'une tuile de l'accueil assisté (§5, refonte menu de tuiles)
    -- même moule que `_ConsoleIcon` (`QPainter` seul, jamais une image),
    mais paramétrée par glyphe (`_TILE_ICON_PAINTERS`), couleur (jamais un
    hex en dur ici, choisie par `Tile` selon son rôle -- cyan normalement,
    `BG_DARK` sur la tuile 1 mise en avant, `DANGER_FG` sur la tuile
    destructive) et taille (44 en tuile normale, §5 deuxième correctif de
    taille -- tuiles réduites à 160x160 pour tenir sur un écran réel
    1366x768/728 ; 60 sur la tuile 1 mise en avant -- même rapport
    160/200 qu'avant ce correctif, §5 -- « c'est l'icône qui doit porter
    la tuile »)."""

    DEFAULT_SIZE = 44

    def __init__(self, glyph: str, color: str, size: int = DEFAULT_SIZE, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._glyph = glyph
        self._color = QColor(color)

    def paintEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        drawer = _TILE_ICON_PAINTERS.get(self._glyph)
        if drawer is not None:
            drawer(painter, self.rect(), self._color)


# Taille de police réelle de chaque rôle de libellé de tuile (theme.py,
# QSS) -- dupliquée ici volontairement : `_tile_label_reserved_height` a
# besoin de la connaître *avant* que le style QSS ne soit appliqué au
# widget (au moment de la construction de `Tile`, avant tout affichage),
# et Qt Style Sheets ne s'interroge pas depuis Python -- une seule autre
# façon de le faire serait de construire un `QLabel`, l'ajouter à une
# hiérarchie stylée, forcer un `ensurePolished()`, puis lire sa police,
# nettement plus lourd pour gagner la même information.
_TILE_LABEL_FONT_PIXEL_SIZE = {
    "tileLabel": 14,
    "tileLabelLarge": 16,
}
_TILE_LABEL_FONT_WEIGHT = {
    "tileLabel": 600,
    "tileLabelLarge": 700,
}


def _tile_label_reserved_height(label_role: str, lines: int) -> int:
    """Hauteur à réserver pour `lines` lignes du rôle de libellé donné
    (§5, deuxième correctif de taille) -- jamais déduite du texte
    réellement affiché (variable d'une tuile à l'autre), pour que toutes
    les tuiles d'un même rôle aient exactement la même hauteur de zone
    libellé, et que la plus longue ne soit jamais coupée.

    Mesurée avec la police du thème (`theme.FONT_FAMILY`, graisse du
    rôle), pas la police par défaut de Qt : bug corrigé, constaté au
    rendu en anglais -- « Prepare my card » (tuile 1, une seule ligne
    réservée) perdait le bas de ses « p »/« y », 18 px réservés pour 21
    nécessaires avec Segoe UI gras. Le français était touché aussi
    (« Préparer »), moins visiblement."""
    font = QFont()
    font.setFamilies([name.strip(" '\"") for name in theme.FONT_FAMILY.split(",")])
    font.setPixelSize(_TILE_LABEL_FONT_PIXEL_SIZE[label_role])
    font.setWeight(QFont.Weight(_TILE_LABEL_FONT_WEIGHT[label_role]))
    return QFontMetrics(font).lineSpacing() * lines


class Tile(ClickableFrame):
    """Tuile de l'accueil assisté (§5, refonte menu de tuiles) -- hérite
    de `ClickableFrame` pour son mécanisme clic/désactivation (opacité
    0,45 sur `setEnabled(False)`, déjà correct tel quel), carrée à taille
    FIXE (`setFixedSize`, jamais `setMinimumSize` -- ne doit jamais
    s'étirer dans la grille, l'effet « menu d'applications » en dépend) :
    badge de statut en haut-droite (hauteur toujours réservée, voir
    `set_badge`), icône centrée dans la moitié haute, libellé en
    bas-gauche. `role` distingue les trois variantes
    (`"tile"`/`"tileEmphasized"`/`"tileDestructive"`, voir `theme.py`) --
    remplace le `"row"` posé par `ClickableFrame.__init__`.

    Tuile 1 (« Préparer ma carte ») est la seule à porter une
    description sous son libellé (`description`, icône/libellé plus
    grands aussi -- voir `AssistedLandingScreen`, qui passe des valeurs
    différentes pour cette seule tuile).

    Taille réduite à 160 (§5, deuxième correctif de taille) : à 200,
    l'arithmétique verticale ne rentrait plus sur un écran réel de
    1366x768/728 (zone client ~720-728, en-tête ~86-100 + trois rangées
    de 200 + deux gouttières de 12 = 724, ça ne rentre jamais, quel que
    soit le réglage des marges autour). 160x160 (332x160 pour la tuile 1)
    -- 100 + 480 + 24 = 604, de la marge reste. `SPACING` inchangé (12,
    seule la taille des tuiles elles-mêmes change)."""

    SIZE = 160
    SPACING = 12

    def __init__(
        self,
        glyph: str,
        label_text: str,
        role: str = "tile",
        icon_color: Optional[str] = None,
        icon_size: int = _TileIcon.DEFAULT_SIZE,
        label_role: str = "tileLabel",
        label_lines: int = 3,
        description: Optional[str] = None,
        width: Optional[int] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setProperty("role", role)
        self.setFixedSize(width or self.SIZE, self.SIZE)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)

        header = QHBoxLayout()
        header.addStretch()
        # Toujours visible (jamais `setVisible(False)`, y compris quand
        # vide) : la hauteur du badge reste réservée quel que soit son
        # contenu, pour que les tuiles ne bougent jamais selon leur statut
        # (§5, correctif visuel -- voir `set_badge`).
        self._badge = QLabel("")
        self._badge.setProperty("role", "badge")
        header.addWidget(self._badge)
        layout.addLayout(header)

        # Icône centrée dans la moitié haute de la tuile -- c'est elle qui
        # doit porter la tuile, pas le libellé (§5, correctif visuel).
        # Positionnée par les seuls espaces élastiques de `layout``
        # ci-dessous (`addStretch`, jamais un `QWidget` intermédiaire) :
        # un `QWidget` nu sans rôle QSS hérite quand même du fond sombre
        # global (`QMainWindow, QWidget {{ background-color: ... }}`,
        # theme.py) dès qu'un style d'application est actif -- correctif
        # d'un bug constaté (un rectangle sombre plein entourait chaque
        # icône, opaque au point de rendre celle de la tuile 1 invisible,
        # dessinée en `BG_DARK` sur ce même `BG_DARK`). Une disposition
        # par layouts seuls (`QHBoxLayout`/`addStretch`) ne peint jamais
        # rien par elle-même -- l'icône se dessine directement sur le
        # fond de la tuile.
        icon_row = QHBoxLayout()
        icon_row.addStretch()
        icon_row.addWidget(_TileIcon(glyph, icon_color or theme.ACCENT_CYAN, size=icon_size))
        icon_row.addStretch()
        layout.addStretch(1)
        layout.addLayout(icon_row)
        layout.addStretch(2)

        label_row = QHBoxLayout()
        self._label = QLabel(label_text)
        self._label.setProperty("role", label_role)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        # Hauteur réservée pour `label_lines` lignes (3 par défaut -- §5,
        # deuxième correctif de taille), jamais une hauteur déduite du
        # texte réellement passé : sans ça, une tuile au libellé court
        # (« Aide ») et une au libellé long (« Remettre la carte à
        # zéro ») n'auraient pas la même hauteur de zone libellé, et rien
        # ne garantirait que le texte le plus long ne dépasse pas de la
        # tuile. Calculée depuis la taille de police réelle du rôle
        # (`_TILE_LABEL_FONT_PIXEL_SIZE`), pas depuis la police par défaut
        # de l'application (qui ne reflète pas la taille QSS avant que le
        # style ne soit appliqué).
        self._label.setFixedHeight(_tile_label_reserved_height(label_role, label_lines))
        label_row.addWidget(self._label)
        label_row.addStretch()
        layout.addLayout(label_row)

        if description:
            desc_row = QHBoxLayout()
            desc_label = QLabel(description)
            # Rôle dédié (jamais "rowDesc", en `TEXT_SECONDARY` -- illisible
            # sur le fond cyan plein de cette seule tuile, correctif
            # demandé) : `BG_DARK`, comme `tileLabelLarge` ci-dessus.
            desc_label.setProperty("role", "tileDescLarge")
            desc_label.setWordWrap(True)
            desc_row.addWidget(desc_label)
            layout.addLayout(desc_row)

    def set_badge(self, status: Optional[StepStatus], card_system: Optional[CardSystem] = None) -> None:
        """Même mécanique que `HomeScreen.set_status` (§5) : `setProperty`
        puis `theme.repolish` -- Qt ne réévalue un sélecteur
        `[badgeKind="..."]` qu'au moment où le style est recalculé, pas à
        chaque changement de propriété seul.

        `None` (tuile sans statut, ex. tuile 1/3/9/10) et `NOT_RELEVANT`
        se traitent tous deux comme « rien à afficher » -- **jamais
        `setVisible(False)`** : un badge vide, sans `badgeKind`
        correspondant, n'a ni fond ni bordure (`QLabel[role="badge"]` ne
        colore que sur un `badgeKind` reconnu, `theme.py`) mais réserve
        toujours sa hauteur (`min-height`, même règle QSS) -- correctif
        demandé : « Non pertinente pour cette carte » dominait
        visuellement la grille sur quatre tuiles, et les tuiles auraient
        sinon changé de hauteur selon leur statut."""
        if status is None or status == StepStatus.NOT_RELEVANT:
            self._badge.setText("")
            self._badge.setProperty("badgeKind", None)
            theme.repolish(self._badge)
            return
        self._badge.setText(_status_text(status, card_system))
        self._badge.setProperty("badgeKind", _BADGE_KIND_BY_STATUS[status])
        theme.repolish(self._badge)


class ConsoleArt(QWidget):
    """Illustration de la console R36S, en haut de la colonne droite (§5,
    refonte navigation) : grande, bien visible, à une opacité fixe d'
    environ 70 %. Peinte au `QPainter` plutôt qu'affichée via
    `QLabel.setPixmap`, avec l'opacité appliquée directement dans
    `paintEvent` (`painter.setOpacity`). Absente sans lever d'exception
    si le fichier n'existe pas (`build_console_stage` retourne alors
    None) -- l'interface s'affiche normalement sans elle (§5).

    ⚠️ **Animations retirées.** Cette console portait auparavant un halo
    et un socle lumineux pulsants (`ConsoleHalo`/`ConsoleBasePlate`,
    retirés) plus une légère flottaison verticale (`floatOffset`, retirée
    ici aussi) -- mesuré en pratique à 7-9 % d'un cœur au repos (backend
    `offscreen`), et de toute façon désactivé systématiquement en usage
    réel (le réglage « Animations de la console » restait décoché). La
    console est désormais immobile, de face, à opacité fixe -- plus
    aucun état à animer, plus aucun repeint périodique."""

    _OPACITY = 0.70

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._source_pixmap = pixmap
        self._scaled_pixmap = QPixmap()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def resizeEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        super().resizeEvent(event)
        self._scaled_pixmap = self._source_pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        if self._scaled_pixmap.isNull():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        x = (self.width() - self._scaled_pixmap.width()) / 2
        y = (self.height() - self._scaled_pixmap.height()) / 2
        painter.setOpacity(self._OPACITY)
        painter.drawPixmap(int(x), int(y), self._scaled_pixmap)

    def rendered_size(self):
        """Taille réelle de l'image affichée (après mise à l'échelle avec
        conservation du ratio).

        ⚠️ Peut être périmée juste après un `setGeometry()` sur ce widget
        (Qt diffère la livraison du `resizeEvent` d'un widget enfant
        redimensionné depuis l'intérieur du `resizeEvent` de son parent,
        voir `ConsoleStage.resizeEvent`) -- ce dernier ne s'appuie donc
        plus sur cette méthode pour ses propres calculs
        (`_fit_within_aspect_ratio` ci-dessous, un calcul pur qui ne
        dépend d'aucune livraison d'événement)."""
        return self._scaled_pixmap.size()

    def source_size(self):
        """Taille de l'image source, avant mise à l'échelle -- utilisée
        par `_fit_within_aspect_ratio` pour calculer, par le calcul plutôt
        qu'en lisant `rendered_size()` (périmée juste après un
        `setGeometry`, voir sa docstring), la taille qu'aurait le rendu
        pour une boîte donnée."""
        return self._source_pixmap.size()


def _fit_within_aspect_ratio(source, target):
    """Réplique `QPixmap.scaled(target, Qt.KeepAspectRatio)` par le calcul
    plutôt que d'attendre le résultat réel de `ConsoleArt` -- voir la mise
    en garde sur `ConsoleArt.rendered_size()` : lire cette taille juste
    après un `setGeometry()`, à l'intérieur du `resizeEvent` d'un widget
    parent, peut refléter l'état précédent (livraison différée par Qt).
    `ConsoleStage.resizeEvent` a besoin de cette taille immédiatement pour
    placer le terminal d'activité sur l'écran de la console -- ce calcul,
    indépendant de tout événement Qt, ne peut jamais être périmé."""
    if source.isEmpty() or target.width() <= 0 or target.height() <= 0:
        return QSize(0, 0)
    scale = min(target.width() / source.width(), target.height() / source.height())
    return QSize(max(1, round(source.width() * scale)), max(1, round(source.height() * scale)))


class ConsoleTerminalOverlay(QWidget):
    """Terminal d'activité disque, superposé à l'écran de la console R36S
    (§5) : une ligne par événement de progression réellement émis par
    `imaging/copy.py::copy_range`/`partitions/copy.py::copy_tree`
    (relayés par `MainWindow._on_progress` -> `ConsoleStage.append_line`)
    -- jamais une ligne inventée (§2 règle 5) : au repos, rien d'autre
    qu'un curseur clignotant, jamais de fausse activité.

    Vert monospace sur fond sombre, mêmes couleurs que le journal de bord
    (`theme.LOG_BG`/`theme.LOG_TEXT`) pour rester cohérent avec le reste
    de l'habillage (§5) tout en restant un affichage distinct : le
    journal garde les heures de début/fin, l'éjection, les erreurs ;
    celui-ci ne montre que l'activité brute, au fil de l'eau.

    Taille et position de ce widget sont décidées par `ConsoleStage`, en
    proportion de l'image de la console redimensionnée -- jamais en
    coordonnées absolues (même piège que le rognage du bas de la console,
    déjà corrigé une fois pour la flottaison, désormais retirée). La
    taille de police, elle, est calculée ici en proportion de la hauteur
    du widget lui-même (`resizeEvent`), pour la même raison.

    **Correctif de performance appliqué par précaution** (`append_line`/
    `_toggle_cursor`/`clear_lines` ne font que muter l'état interne
    (`_dirty = True`), jamais `self.update()` directement -- un `QTimer`
    dédié, `_repaint_timer`, cadencé à `_REPAINT_INTERVAL_MS` (~33 ms,
    ~30 im/s), impose un unique repeint groupé par tick, seulement si
    quelque chose a changé depuis le tick précédent. `_terminal_font` met
    en cache le `QFont` construit, invalidé seulement quand la hauteur de
    ligne change. **Correction de conception, confirmée sur du vrai
    matériel : ce correctif visait un faux coupable.** Ce terminal avait
    été soupçonné (puis entièrement retiré une première fois) d'un
    ralentissement de la sauvegarde système d'un facteur dix (~85 Mo/s ->
    6,7 Mo/s) -- la cause réelle, confirmée en bissectant par mesure du
    débit CLI pur (sans la moindre interface, donc sans ce terminal), était
    une carte SD d'origine de console non reconnue (~6 Mo/s en lecture,
    contre ~88 Mo/s pour une SanDisk sur le même port) : capacité exposée
    (104,8 Go) très inférieure à celle annoncée (128 Go), signe révélateur
    d'une carte de capacité falsifiée -- jamais un défaut logiciel. Voir
    §8 pour la même mise en garde générale. Le cadencement du repeint et
    la mise en cache de la police restent en place (ils ne coûtent rien et
    restent une bonne pratique), mais aucun correctif supplémentaire sur ce
    terminal ne doit plus être tenté sur la seule foi d'un débit mesuré
    bas : toujours vérifier la carte en premier."""

    _MAX_LINES = 500  # borne mémoire large, bien au-delà de ce qu'affiche jamais cette zone
    _CURSOR_BLINK_MS = 500
    _REPAINT_INTERVAL_MS = 33  # ~30 im/s -- voir la docstring de la classe
    _LINE_HEIGHT_FRACTION = 0.16  # ~6 lignes visibles dans le cadre calibré (§ ConsoleStage)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._lines: List[str] = []
        self._cursor_on = True
        self._dirty = False
        self._font_cache: Optional[QFont] = None
        self._font_cache_line_height = -1

        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(self._CURSOR_BLINK_MS)
        self._blink_timer.timeout.connect(self._toggle_cursor)
        self._blink_timer.start()

        # Repeint cadencé, découplé des setters -- voir le correctif de
        # performance dans la docstring de la classe. Tourne en permanence
        # (le curseur cligne même au repos) ; son coût par tick quand rien
        # n'a changé se limite à un test booléen.
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setInterval(self._REPAINT_INTERVAL_MS)
        self._repaint_timer.timeout.connect(self._flush_repaint)
        self._repaint_timer.start()

    def _toggle_cursor(self) -> None:
        self._cursor_on = not self._cursor_on
        self._dirty = True

    def append_line(self, text: str) -> None:
        """Une ligne par événement de progression réel -- jamais appelée
        pour simuler une activité (§2 règle 5). Ne repeint jamais elle-même
        (voir le correctif de performance de la docstring de classe) :
        `_repaint_timer` s'en charge, à cadence bornée."""
        self._lines.append(text)
        if len(self._lines) > self._MAX_LINES:
            del self._lines[: len(self._lines) - self._MAX_LINES]
        self._dirty = True

    def clear_lines(self) -> None:
        """Retour à l'état de repos (`ConsoleStage.start_activity`/
        `stop_activity`) -- curseur seul, jamais les dernières lignes
        d'une activité terminée."""
        if not self._lines:
            return
        self._lines.clear()
        self._dirty = True

    def _flush_repaint(self) -> None:
        if self._dirty:
            self._dirty = False
            self.update()

    def _line_height(self) -> int:
        return max(6, int(self.height() * self._LINE_HEIGHT_FRACTION))

    def _terminal_font(self) -> QFont:
        """Mis en cache (voir le correctif de performance de la docstring
        de classe) -- reconstruit seulement quand la hauteur de ligne
        change, jamais à chaque `paintEvent`."""
        line_height = self._line_height()
        if self._font_cache is not None and self._font_cache_line_height == line_height:
            return self._font_cache
        font = QFont()
        # Mêmes polices de repli que `theme.MONO_FONT_FAMILY` (utilisé en
        # QSS pour le journal de bord) -- `setFamilies` (pas un simple nom
        # unique) pour un vrai repli monospace sur les trois OS, `Consolas`
        # (Windows) n'existant ni sur macOS ni sur Linux.
        font.setFamilies(["Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"])
        font.setStyleHint(QFont.Monospace)
        font.setFixedPitch(True)
        font.setPixelSize(max(6, int(line_height * 0.72)))
        self._font_cache = font
        self._font_cache_line_height = line_height
        return font

    def resizeEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        super().resizeEvent(event)
        self._dirty = True

    def paintEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.LOG_BG))
        if self.width() <= 0 or self.height() <= 0:
            return
        painter.setFont(self._terminal_font())
        painter.setPen(QColor(theme.LOG_TEXT))
        line_height = self._line_height()
        max_lines = max(1, self.height() // line_height)
        visible = self._lines[-max_lines:]
        margin = 4
        y = line_height
        for line in visible:
            painter.drawText(margin, y, line)
            y += line_height
        cursor_text = "_" if self._cursor_on else " "
        if visible:
            last_width = painter.fontMetrics().horizontalAdvance(visible[-1])
            painter.drawText(margin + last_width + 2, y - line_height, cursor_text)
        else:
            painter.drawText(margin, line_height, cursor_text)


class ConsoleStage(QWidget):
    """Zone du haut de la colonne droite (§5) : la console (`ConsoleArt`),
    immobile et à opacité fixe (animations retirées, voir sa docstring),
    et son terminal d'activité disque (`ConsoleTerminalOverlay`),
    superposé à l'écran de la console.

    Le rectangle de l'écran (`_SCREEN_RECT_FRACTIONS`) est exprimé en
    fraction de l'image *source* (`gui/assets/console.png`, 595x900 --
    photo recadrée, vue de face, fond rendu transparent) -- calibré par
    script en mesurant la boîte englobante des pixels opaques, de
    luminosité moyenne (70-210) et de faible saturation (écart max entre
    canaux < 25) dans la moitié supérieure de l'image (distingue l'écran,
    verre gris neutre, du corps de la console -- bien plus sombre -- et
    des boutons colorés), puis resserré d'environ 3 % pour rester dans le
    verre plutôt que sur son biseau. Cette photo de face donne un écran
    quasiment rectangulaire dans le plan de l'image -- le rectangle aligné
    sur les axes épouse donc ses quatre coins nettement mieux qu'avec
    l'ancienne vue de profil en perspective (vérifié visuellement,
    superposition du rectangle sur l'image). Ces fractions s'appliquent à
    la taille *rendue* de la console (calculée par `_fit_within_aspect_
    ratio`, jamais en coordonnées absolues -- même piège que le rognage du
    bas de la console, déjà corrigé une fois pour la flottaison désormais
    retirée), pour rester juste quelle que soit la taille de la fenêtre."""

    _SCREEN_RECT_FRACTIONS = (0.11, 0.08, 0.88, 0.465)  # x0, y0, x1, y1

    def __init__(self, console_art: ConsoleArt, parent=None):
        super().__init__(parent)
        self._console_art = console_art
        self._console_art.setParent(self)
        self._terminal = ConsoleTerminalOverlay(self)
        self._terminal.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        super().resizeEvent(event)
        self._console_art.setGeometry(0, 0, self.width(), self.height())

        # Bug corrigé par le passé, toujours valable ici : lire
        # `self._console_art.rendered_size()` juste après `setGeometry()`
        # peut refléter l'état *précédent* (livraison différée du
        # `resizeEvent` de l'enfant, voir `ConsoleArt.rendered_size`) --
        # `_fit_within_aspect_ratio` (pur) reproduit ce même calcul sans
        # dépendre de cette livraison.
        source_size = self._console_art.source_size()
        rendered = _fit_within_aspect_ratio(source_size, self.size())
        art_x = (self.width() - rendered.width()) // 2
        art_y = (self.height() - rendered.height()) // 2

        x0f, y0f, x1f, y1f = self._SCREEN_RECT_FRACTIONS
        screen_rect = QRect(
            art_x + int(rendered.width() * x0f),
            art_y + int(rendered.height() * y0f),
            max(1, int(rendered.width() * (x1f - x0f))),
            max(1, int(rendered.height() * (y1f - y0f))),
        )
        self._terminal.setGeometry(screen_rect)

    def append_line(self, text: str) -> None:
        self._terminal.append_line(text)

    def start_activity(self) -> None:
        """À appeler au démarrage d'une opération disque (§4.3/§4.4) --
        prépare un terminal vierge pour la nouvelle activité plutôt que
        de continuer d'accumuler les lignes de l'opération précédente."""
        self._terminal.clear_lines()

    def stop_activity(self) -> None:
        """À appeler à la fin d'une opération disque -- au repos, l'écran
        de la console n'affiche qu'un curseur, jamais les dernières
        lignes d'une activité terminée (§ demande explicite : « pas de
        fausse activité »)."""
        self._terminal.clear_lines()


def build_console_stage(parent=None) -> Optional[ConsoleStage]:
    """None si `gui/assets/console.png` est absente ou illisible -- ne
    doit jamais empêcher l'affichage du reste de l'interface (§5)."""
    path = asset_paths.asset_path("console.png")
    if path is None:
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    return ConsoleStage(ConsoleArt(pixmap), parent)


class WindowBackdrop(QWidget):
    """Motif de fond décoratif sur toute la fenêtre, derrière les deux
    colonnes (§5, refonte navigation) : `assets/circuit.png`, répété en
    mosaïque (`QPainter.drawTiledPixmap`) à 15 % d'opacité fixe -- jamais
    mis à l'échelle, pour rester net à n'importe quelle taille de fenêtre
    (une image étirée perdrait en netteté, une mosaïque non). Les panneaux
    des colonnes gardent un fond opaque (`theme.py`) et restent donc
    lisibles par-dessus, quelle que soit la zone qu'ils recouvrent. Jamais
    cliquable (`WA_TransparentForMouseEvents`) ; absent sans lever
    d'exception si le fichier n'existe pas (`build_window_backdrop`)."""

    _OPACITY = 0.15

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._pixmap = pixmap
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        painter = QPainter(self)
        painter.setOpacity(self._OPACITY)
        painter.drawTiledPixmap(self.rect(), self._pixmap)


def build_window_backdrop(parent=None) -> Optional[WindowBackdrop]:
    """None si `gui/assets/circuit.png` est absente ou illisible -- ne doit
    jamais empêcher l'affichage du reste de l'interface (§5)."""
    path = asset_paths.asset_path("circuit.png")
    if path is None:
        return None
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return None
    return WindowBackdrop(pixmap, parent)


class LanguageSelector(QComboBox):
    """Choix de la langue de l'interface (`r36s_studio/i18n.py`), présent
    sur les deux accueils. Chaque langue est écrite dans sa propre langue
    (« English », jamais « Anglais ») et l'infobulle est bilingue : un
    utilisateur qui ne lit pas la langue affichée doit pouvoir le trouver.
    N'émet `language_selected` que sur un choix de l'utilisateur, jamais
    sur `set_language` (synchronisation entre les deux accueils)."""

    language_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        for code, name in i18n.LANGUAGE_NAMES.items():
            self.addItem(name, code)
        self.setToolTip(tr("language_selector_label"))
        self.setAccessibleName(tr("language_selector_label"))
        self.set_language(i18n.get_language())
        self.activated.connect(self._on_activated)

    def set_language(self, code: str) -> None:
        index = self.findData(code)
        if index >= 0:
            self.blockSignals(True)
            self.setCurrentIndex(index)
            self.blockSignals(False)

    def _on_activated(self, index: int) -> None:
        self.language_selected.emit(self.itemData(index))


class UpdateControls(QWidget):
    """Sous le sélecteur de langue des deux accueils : badge « Nouvelle
    version disponible » (masqué tant que `MainWindow` n'en signale pas)
    et case « Rechercher les mises à jour » (`config.check_updates`)."""

    badge_clicked = Signal()
    check_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.badge = QPushButton(tr("update_badge"))
        self.badge.setProperty("role", "cta")
        self.badge.clicked.connect(self.badge_clicked.emit)
        self.badge.hide()
        layout.addWidget(self.badge, 0, Qt.AlignRight)
        self.checkbox = QCheckBox(tr("update_check_label"))
        self.checkbox.toggled.connect(self.check_toggled.emit)
        layout.addWidget(self.checkbox, 0, Qt.AlignRight)

    def set_checked(self, checked: bool) -> None:
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        self.checkbox.blockSignals(False)


class UpdateDialog(Dialog):
    """Notes de la nouvelle version + bouton vers la boutique
    (`update_check.STORE_URL`, ouvert par `MainWindow`, `download_requested`)."""

    download_requested = Signal()

    def __init__(self, tag: str, notes: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("update_dialog_title", version=tag))
        layout = QVBoxLayout(self)
        title = QLabel(tr("update_dialog_title", version=tag))
        title.setProperty("role", "title")
        layout.addWidget(title)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setMarkdown(notes)
        layout.addWidget(browser, 1)
        buttons = QHBoxLayout()
        later = QPushButton(tr("update_dialog_later"))
        later.clicked.connect(self.close)
        download = QPushButton(tr("update_dialog_download"))
        download.setProperty("role", "primary")
        download.clicked.connect(self.download_requested.emit)
        buttons.addWidget(later)
        buttons.addStretch()
        buttons.addWidget(download)
        layout.addLayout(buttons)
        self.resize(520, 440)


class HomeScreen(Screen):
    """Colonne gauche, largeur fixe, toujours visible (§5, refonte
    navigation) : bandeau de détection, six étapes A à F, puis la
    sauvegarde complète sous « Par sécurité ». `detect.StepStatus`
    n'indique qu'un statut informatif par étape (faisable / déjà faite /
    non pertinente pour la carte branchée / limitée par la plateforme),
    jamais un verrou -- un utilisateur averti garde toujours la main,
    *sauf* pendant qu'une opération est en cours (`set_busy`), où cliquer
    une deuxième étape n'aurait pas de sens tant que la première tourne."""

    extract_boot_selected = Signal()
    extract_easyroms_selected = Signal()
    flash_selected = Signal()
    inject_boot_selected = Signal()
    copy_games_selected = Signal()
    eject_selected = Signal()
    backup_selected = Signal()
    backup_system_selected = Signal()
    reset_card_selected = Signal()
    refresh_requested = Signal()
    help_requested = Signal()
    assisted_mode_requested = Signal()
    # Section « Consoles diverses » (consoles_diverses/, étape 1) --
    # bouton discret, même rôle que assisted_mode_requested, jamais un
    # import du package consoles_diverses ici : cet écran ne fait
    # qu'émettre un signal, c'est main_window.py qui sait quoi en faire
    # (règle d'isolation, consoles_diverses/CLAUDE.md).
    consoles_diverses_requested = Signal()
    # Outil « Console Android » (android/, étape 1, docs/android-adb.md) --
    # même principe : bouton discret, cet écran ne fait qu'émettre un
    # signal, c'est main_window.py qui décide quoi en faire.
    android_requested = Signal()
    # Tuile personnelle « Web » (config.py::personal_web_url, jamais
    # distribuée) -- signal distinct des six étapes, jamais ajouté à
    # `ALL_STEPS`/`detect.py`.
    web_requested = Signal()
    # Outils autonomes sur un dossier (docs/doublons.md, docs/tri-roms.md)
    # -- section « Outils » : retirés de l'accueil assisté, allégé pour
    # le néophyte (§1), ils ne vivent plus qu'ici.
    find_duplicates_requested = Signal()
    sort_games_requested = Signal()
    filter_games_requested = Signal()
    # Choix de la langue (i18n.py) -- cet écran ne fait qu'émettre le
    # code choisi, main_window.py le mémorise.
    language_selected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        # Combinés par `_update_backup_rows_enabled` : « Par sécurité »
        # (sauvegarde complète et sauvegarde système sans les jeux, §4.3)
        # exige une carte, contrairement aux six étapes lettrées -- jamais
        # désactivé avant le premier `set_status(has_device=...)` (`True`
        # par défaut, pas de fausse alerte avant que la détection n'ait
        # tourné une première fois).
        self._busy = False
        self._has_device = True

        # Titre à gauche, bouton « Mode assisté » en haut à droite (§5
        # mode assisté) -- symétrique du bouton « Mode expert » de
        # AssistedLandingScreen. Sans lui, basculer en mode expert était
        # un aller simple : ui_mode étant persisté (config.py), rien ne
        # permettait de revenir au mode assisté, même après redémarrage.
        title_row = QHBoxLayout()
        title = QLabel(tr("home_title"))
        title.setProperty("role", "title")
        # Retour à la ligne plutôt que coupé par les trois boutons de
        # l'en-tête dans la colonne de ~480 px (constaté au rendu).
        title.setWordWrap(True)
        title_row.addWidget(title, 1)
        title_row.addStretch()
        self._consoles_diverses_button = QPushButton(tr("home_consoles_diverses_button"))
        self._consoles_diverses_button.setProperty("role", "flat")
        self._consoles_diverses_button.clicked.connect(self.consoles_diverses_requested.emit)
        title_row.addWidget(self._consoles_diverses_button)
        self._android_button = QPushButton(tr("home_android_button"))
        self._android_button.setProperty("role", "flat")
        self._android_button.clicked.connect(self.android_requested.emit)
        title_row.addWidget(self._android_button)
        self._assisted_mode_button = QPushButton(tr("home_assisted_mode_button"))
        self._assisted_mode_button.setProperty("role", "flat")
        self._assisted_mode_button.clicked.connect(self.assisted_mode_requested.emit)
        title_row.addWidget(self._assisted_mode_button)
        layout.addLayout(title_row)
        # Sur sa propre ligne, alignée à droite : l'en-tête ci-dessus porte
        # déjà trois boutons dans une colonne étroite, un quatrième ferait
        # chevaucher les libellés plus longs d'une autre langue.
        language_row = QHBoxLayout()
        language_row.addStretch()
        self._language_selector = LanguageSelector()
        self._language_selector.language_selected.connect(self.language_selected.emit)
        language_row.addWidget(self._language_selector)
        layout.addLayout(language_row)
        self.update_controls = UpdateControls()
        layout.addWidget(self.update_controls, 0, Qt.AlignRight)

        # Bandeau de détection, toujours en haut -- cadre à bordure cyan et
        # coins arrondis (theme.py, role="banner"), distinct des lignes
        # d'étape (bordure neutre au repos) : icône à gauche, modèle et
        # taille de la carte au centre, bouton Rafraîchir à droite, tous
        # dans la même ligne (§5).
        self._banner = QFrame()
        self._banner.setProperty("role", "banner")
        banner_layout = QHBoxLayout(self._banner)
        banner_layout.setContentsMargins(14, 10, 14, 10)
        banner_layout.setSpacing(12)

        banner_layout.addWidget(_ConsoleIcon())

        banner_texts = QVBoxLayout()
        banner_texts.setSpacing(2)
        self._banner_device_label = QLabel()
        self._banner_device_label.setProperty("role", "rowTitle")
        self._banner_state_label = QLabel()
        self._banner_state_label.setProperty("role", "secondary")
        banner_texts.addWidget(self._banner_device_label)
        banner_texts.addWidget(self._banner_state_label)
        banner_layout.addLayout(banner_texts, 1)

        self._refresh_button = QPushButton(tr("home_refresh"))
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        banner_layout.addWidget(self._refresh_button, 0, Qt.AlignVCenter)

        layout.addWidget(self._banner)

        # Autorisation Accès complet au disque (§3) : seul macOS en a
        # besoin -- ne pas afficher ce bouton ailleurs éviterait de dérouter
        # les utilisateurs Windows/Linux avec une procédure qui ne les
        # concerne pas. Absent du bandeau de détection (§5, dédié à la
        # carte) : sa propre ligne, en dessous.
        if platform.system() == "Darwin":
            help_row = QHBoxLayout()
            self._help_button = QPushButton(tr("home_help"))
            self._help_button.clicked.connect(self.help_requested.emit)
            help_row.addWidget(self._help_button)
            help_row.addStretch()
            layout.addLayout(help_row)

        # Lignes dans une zone qui défile : avec la section « Outils »,
        # la liste dépasse la hauteur minimale de la fenêtre (690, mesurée
        # à 677 sans elle, `main_window.py`) -- jamais une ligne coupée ou
        # chevauchée sur un écran 1366x768, seulement un défilement.
        rows_container = QWidget()
        rows_layout = QVBoxLayout(rows_container)
        rows_layout.setContentsMargins(0, 0, 0, 0)
        rows_scroll = QScrollArea()
        rows_scroll.setFrameShape(QFrame.NoFrame)
        rows_scroll.setWidgetResizable(True)
        rows_scroll.setWidget(rows_container)
        layout.addWidget(rows_scroll, 1)
        self._rows_scroll = rows_scroll  # exposé pour les tests

        step_signals = {
            "extract_boot": self.extract_boot_selected,
            "extract_easyroms": self.extract_easyroms_selected,
            "flash": self.flash_selected,
            "inject_boot": self.inject_boot_selected,
            "copy_games": self.copy_games_selected,
            "eject": self.eject_selected,
        }
        self._tiles: Dict[str, ClickableFrame] = {}
        self._badges: Dict[str, QLabel] = {}
        for key, letter, title_key, desc_key in _STEP_SPECS:
            row, badge = self._build_row(letter, tr(title_key), tr(desc_key), step_signals[key])
            self._tiles[key] = row
            self._badges[key] = badge
            rows_layout.addWidget(row)

        separator = QLabel(tr("home_backup_separator"))
        separator.setProperty("role", "secondary")
        rows_layout.addWidget(separator)
        self._backup_row, backup_badge = self._build_row(
            "◆", tr("home_tile_backup"), tr("home_tile_backup_desc"), self.backup_selected
        )
        backup_badge.setVisible(False)  # jamais de badge de statut pour la sauvegarde (§5)
        rows_layout.addWidget(self._backup_row)
        self._backup_system_row, backup_system_badge = self._build_row(
            "◆",
            tr("home_tile_backup_system"),
            tr("home_tile_backup_system_desc"),
            self.backup_system_selected,
        )
        backup_system_badge.setVisible(False)  # jamais de badge de statut pour la sauvegarde (§5)
        rows_layout.addWidget(self._backup_system_row)
        # Remise à zéro (§4.3 bis) : sous « Par sécurité » comme les deux
        # sauvegardes ci-dessus, jamais dans le parcours assisté -- une
        # opération destructrice qui n'en fait pas partie (§5).
        self._reset_card_row, reset_card_badge = self._build_row(
            "◆",
            tr("home_tile_reset_card"),
            tr("home_tile_reset_card_desc"),
            self.reset_card_selected,
        )
        reset_card_badge.setVisible(False)  # jamais de badge de statut pour cette ligne (§5)
        rows_layout.addWidget(self._reset_card_row)

        tools_separator = QLabel(tr("home_tools_separator"))
        tools_separator.setProperty("role", "secondary")
        rows_layout.addWidget(tools_separator)
        self._find_duplicates_row, duplicates_badge = self._build_row(
            "◆", tr("home_tile_find_duplicates"), tr("home_tile_find_duplicates_desc"), self.find_duplicates_requested
        )
        duplicates_badge.setVisible(False)
        rows_layout.addWidget(self._find_duplicates_row)
        self._sort_games_row, sort_badge = self._build_row(
            "◆", tr("home_tile_sort_games"), tr("home_tile_sort_games_desc"), self.sort_games_requested
        )
        sort_badge.setVisible(False)
        rows_layout.addWidget(self._sort_games_row)
        self._filter_games_row, filter_badge = self._build_row(
            "◆", tr("home_tile_filter_games"), tr("home_tile_filter_games_desc"), self.filter_games_requested
        )
        filter_badge.setVisible(False)
        rows_layout.addWidget(self._filter_games_row)

        # Tuile personnelle « Web » -- construite inconditionnellement
        # (même principe que `HelpDialog`, dont le bouton déclencheur n'est
        # lui non plus affiché que sur macOS) mais cachée par défaut ;
        # `MainWindow` décide seule de l'afficher, une fois, via
        # `set_web_tile_visible`, selon `config.personal_web_url()` --
        # cet écran ne lit lui-même ni variable d'environnement ni config.
        self._web_row, web_badge = self._build_row(
            "◆", tr("home_tile_web"), tr("home_tile_web_desc"), self.web_requested
        )
        web_badge.setVisible(False)  # jamais de badge de statut pour cette ligne (§5)
        self._web_row.setVisible(False)
        rows_layout.addWidget(self._web_row)

        rows_layout.addStretch()

        # Numéro de version + horodatage de construction (§5, à la demande
        # explicite d'un utilisateur ayant perdu le fil entre plusieurs
        # reconstructions locales) : sans repère visible, impossible de
        # savoir si l'app en cours d'exécution contient les derniers
        # correctifs -- vrai en développement, vrai aussi pour un
        # utilisateur qui signale un bug plus tard.
        self._version_label = QLabel(build_info.version_label())
        self._version_label.setProperty("role", "secondary")
        layout.addWidget(self._version_label)

        self.set_status({})

    def set_busy(self, busy: bool) -> None:
        """Désactive visuellement les six étapes et la sauvegarde pendant
        qu'une opération est en cours (§5, refonte navigation) -- la carte
        concernée est déjà en cours d'utilisation, en démarrer une
        deuxième n'aurait pas de sens tant que la première ne s'est pas
        terminée. `setEnabled(False)` empêche aussi Qt de délivrer les
        clics, pas seulement l'apparence."""
        self._busy = busy
        for row in self._tiles.values():
            row.setEnabled(not busy)
        self._update_backup_rows_enabled()
        # Changer de mode en plein flash ou en pleine copie laisserait un
        # job orphelin (§5 mode assisté) -- même garde que les étapes.
        self._assisted_mode_button.setEnabled(not busy)
        self._consoles_diverses_button.setEnabled(not busy)
        self._android_button.setEnabled(not busy)
        self._web_row.setEnabled(not busy)
        self._find_duplicates_row.setEnabled(not busy)
        self._sort_games_row.setEnabled(not busy)
        self._filter_games_row.setEnabled(not busy)

    def set_web_tile_visible(self, visible: bool) -> None:
        self._web_row.setVisible(visible)

    def set_language(self, code: str) -> None:
        """Aligne le sélecteur sur la langue mémorisée (choix fait depuis
        l'autre accueil), sans réémettre `language_selected`."""
        self._language_selector.set_language(code)

    def _update_backup_rows_enabled(self) -> None:
        """« Par sécurité » (§4.3) exige une carte -- contrairement aux
        six étapes lettrées, toujours cliquables par principe (§4.5) : la
        fenêtre Choix de la carte guide même sans carte branchée, alors
        qu'une sauvegarde sans carte n'a tout simplement rien à faire.
        Bug rapporté : lançable alors que la carte venait d'être éjectée
        (bandeau « Aucune carte détectée ») -- combine avec `_busy`, une
        opération en cours restant prioritaire sur une carte qui
        réapparaîtrait entre-temps (le bouton Rafraîchir n'est pas
        désactivé par `set_busy`, contrairement aux lignes elles-mêmes)."""
        enabled = self._has_device and not self._busy
        self._backup_row.setEnabled(enabled)
        self._backup_system_row.setEnabled(enabled)
        self._reset_card_row.setEnabled(enabled)

    def _build_row(self, letter: str, title: str, desc: str, signal: Signal) -> Tuple[ClickableFrame, QLabel]:
        """Une ligne d'étape : icône (lettre) à gauche, titre + description
        au centre, badge de statut à droite (§5). Retourne le cadre
        cliquable et le badge -- le seul élément que `set_status` doit
        ensuite pouvoir modifier."""
        row = ClickableFrame()
        row.clicked.connect(signal.emit)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(12, 10, 12, 10)
        row_layout.setSpacing(12)

        icon = QLabel(letter)
        icon.setProperty("role", "stepIcon")
        icon.setFixedSize(32, 32)
        icon.setAlignment(Qt.AlignCenter)
        row_layout.addWidget(icon)

        texts = QVBoxLayout()
        texts.setSpacing(2)
        title_label = QLabel(title)
        title_label.setProperty("role", "rowTitle")
        # Retour à la ligne aussi sur le titre, pas seulement la
        # description : même garantie qu'aucun libellé n'est jamais coupé
        # que les tuiles de l'accueil assisté (`Tile`).
        title_label.setWordWrap(True)
        desc_label = QLabel(desc)
        desc_label.setProperty("role", "rowDesc")
        desc_label.setWordWrap(True)
        texts.addWidget(title_label)
        texts.addWidget(desc_label)
        row_layout.addLayout(texts, 1)

        badge = QLabel("")
        badge.setProperty("role", "badge")
        badge.setVisible(False)
        row_layout.addWidget(badge, 0, Qt.AlignVCenter)

        return row, badge

    def set_status(
        self,
        status: Dict[str, StepStatus],
        device: Optional[Device] = None,
        has_device: Optional[bool] = None,
        card_system: Optional[CardSystem] = None,
    ) -> None:
        """`card_system` (voir `detect.detect_card`) nomme le système dans
        le badge « Non applicable » et le bandeau. `status` annote chaque
        ligne d'un badge de statut — jamais de ligne masquée ni désactivée
        par ceci pour les six étapes (voir `set_busy` pour leur seule
        désactivation prévue) : une étape absente du dict (détection pas
        encore lancée) n'affiche simplement aucun badge. `device`, quand
        fourni, alimente le bandeau carte détectée en haut de la colonne
        (modèle, taille, état reconnu) -- `None` aussi bien quand aucune
        carte n'est branchée que quand plusieurs candidates le sont à la
        fois (§4.5), donc jamais fiable à lui seul pour distinguer ces
        deux cas. `has_device`, quand fourni, sert précisément cette
        distinction pour « Par sécurité » (§4.3, `_update_backup_rows_
        enabled`) : `True` dès qu'au moins une carte est branchée, y
        compris plusieurs candidates ambiguës (choisir laquelle reste
        possible) -- seul `False` (aucune carte du tout) désactive ces
        lignes. `None` (non précisé) laisse leur état inchangé."""
        for key, badge in self._badges.items():
            step_status = status.get(key)
            if step_status is None:
                badge.setVisible(False)
                badge.setText("")
                continue
            badge.setText(_status_text(step_status, card_system))
            badge.setProperty("badgeKind", _BADGE_KIND_BY_STATUS[step_status])
            theme.repolish(badge)
            badge.setVisible(True)

        if has_device is not None:
            self._has_device = has_device
            self._update_backup_rows_enabled()

        self._update_banner(status, device, card_system)

    def _update_banner(
        self, status: Dict[str, StepStatus], device: Optional[Device], card_system: Optional[CardSystem] = None
    ) -> None:
        if device is None:
            self._banner_device_label.setText(tr("home_banner_state_none"))
            self._banner_state_label.setText("")
            return
        size_go = _capacity_go(device.size_bytes)
        self._banner_device_label.setText(tr("home_banner_line_device", display=device.display, size_go=size_go))
        # Le flash marqué "déjà faite" est le seul signal fiable déjà
        # calculé par `detect_workflow_status` pour "cette carte est déjà
        # ArkOS" -- pas besoin d'exposer `is_arkos` séparément.
        is_arkos = status.get("flash") == StepStatus.DONE
        self._banner_state_label.setText(_banner_state_text(is_arkos, card_system))


class DeviceDialog(Dialog):
    """Choix du périphérique (§5, refonte navigation -- fenêtre modale à la
    place d'un écran séparé) : liste filtrée par `safety` (modèle, taille,
    bus), bouton Rafraîchir, aucune sélection par défaut."""

    device_chosen = Signal(object)  # Device
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("device_title"))
        self._devices: List[Device] = []

        layout = QVBoxLayout(self)
        title = QLabel(tr("device_title"))
        title.setProperty("role", "title")
        layout.addWidget(title)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        self._list.itemSelectionChanged.connect(self._update_next_enabled)
        layout.addWidget(self._list)

        self._empty_label = QLabel(tr("device_empty"))
        self._empty_label.setWordWrap(True)
        layout.addWidget(self._empty_label)

        buttons = QHBoxLayout()
        back_button = QPushButton(tr("device_back"))
        back_button.clicked.connect(self.close)
        refresh_button = QPushButton(tr("device_refresh"))
        refresh_button.clicked.connect(self.refresh_requested.emit)
        self._next_button = QPushButton(tr("device_next"))
        self._next_button.setEnabled(False)
        self._next_button.clicked.connect(self._emit_chosen)
        buttons.addWidget(back_button)
        buttons.addWidget(refresh_button)
        buttons.addStretch()
        buttons.addWidget(self._next_button)
        layout.addLayout(buttons)

        self.resize(440, 380)
        self.set_devices([])

    def set_devices(self, devices: List[Device]) -> None:
        self._devices = devices
        self._list.clear()
        for device in devices:
            size_go = _capacity_go(device.size_bytes)
            item = QListWidgetItem(tr("device_list_entry", display=device.display, size_go=size_go, bus=device.bus))
            item.setData(Qt.UserRole, device)
            self._list.addItem(item)
        self._empty_label.setVisible(not devices)
        self._list.setVisible(bool(devices))
        self._update_next_enabled()

    def _update_next_enabled(self) -> None:
        self._next_button.setEnabled(bool(self._list.selectedItems()))

    def _emit_chosen(self) -> None:
        items = self._list.selectedItems()
        if items:
            self.device_chosen.emit(items[0].data(Qt.UserRole))


class RocknixVariantDialog(Dialog):
    """Choix entre plusieurs variantes ROCKNIX pour la R36S (§5, étape de
    flash) : une vraie release peut publier plusieurs images RK3326 à la
    fois (suffixes `-a`/`-b` observés en pratique, dont la différence
    reste à élucider, CLAUDE.md) — jamais de sélection automatique entre
    elles, chaque variante est affichée avec son nom de fichier complet
    pour que l'utilisateur choisisse en connaissance de cause."""

    variant_chosen = Signal(object, object)  # RocknixAsset, Optional[str] (sha256 attendu)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("rocknix_variant_title"))
        self._variants: List[Tuple[object, Optional[str]]] = []

        layout = QVBoxLayout(self)
        title = QLabel(tr("rocknix_variant_title"))
        title.setProperty("role", "title")
        layout.addWidget(title)

        hint = QLabel(tr("rocknix_variant_hint"))
        hint.setWordWrap(True)
        hint.setProperty("role", "secondary")
        layout.addWidget(hint)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SingleSelection)
        self._list.itemSelectionChanged.connect(self._update_next_enabled)
        layout.addWidget(self._list)

        buttons = QHBoxLayout()
        back_button = QPushButton(tr("file_back"))
        back_button.clicked.connect(self.close)
        self._next_button = QPushButton(tr("file_rocknix_download_button"))
        self._next_button.setEnabled(False)
        self._next_button.clicked.connect(self._emit_chosen)
        buttons.addWidget(back_button)
        buttons.addStretch()
        buttons.addWidget(self._next_button)
        layout.addLayout(buttons)

        self.resize(480, 340)

    def set_variants(self, variants) -> None:
        self._variants = list(variants)
        self._list.clear()
        for asset, _expected_sha256 in self._variants:
            self._list.addItem(QListWidgetItem(asset.name))
        self._update_next_enabled()

    def _update_next_enabled(self) -> None:
        self._next_button.setEnabled(bool(self._list.selectedItems()))

    def _emit_chosen(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        asset, expected_sha256 = self._variants[row]
        self.variant_chosen.emit(asset, expected_sha256)


_FILE_TITLE_KEYS = {
    "backup": "file_title_backup",
    "backup_system": "file_title_backup_system",
    "flash": "file_title_flash",
    "extract_boot": "file_title_extract_boot",
    "extract_easyroms": "file_title_extract_easyroms",
    "inject_boot": "file_title_inject_boot",
    "copy_games": "file_title_copy_games",
}


_ARCHIVE_MODES = {"inject_boot", "copy_games"}  # étapes D/E : choix parmi les archives existantes
_DESTINATION_MODES = {"extract_boot", "extract_easyroms"}  # étapes A/B : dossier de destination, avec défaut



def format_datetime_label(timestamp) -> str:
    """Date/heure conviviale (§5, pas de jargon) -- ex. « 6 juillet 2026 à
    00h21 » -- réutilisée par `format_archive_label` (nom d'un dossier
    d'archive horodaté) et `ArchiveReuseDialog` (date d'une sauvegarde déjà
    mémorisée dans la configuration, §5 mode assisté)."""
    return tr(
        "datetime_label",
        day=timestamp.day,
        month=tr(f"month_{timestamp.month:02d}"),
        year=timestamp.year,
        hour=timestamp.hour,
        minute=timestamp.minute,
    )


def format_archive_label(path) -> str:
    """Nom convivial (§5, pas de jargon) d'un dossier d'archive horodaté —
    ex. « 6 juillet 2026 à 00h21 » plutôt que le nom de dossier brut. Repli
    sur le nom du dossier si ce n'est pas une archive nommée par
    `archives.new_archive_path` (dossier choisi manuellement via
    Parcourir)."""
    from pathlib import Path as _Path

    path = _Path(path)
    timestamp = parse_archive_timestamp(path)
    if timestamp is None:
        return path.name
    return format_datetime_label(timestamp)


class FileDialog(Dialog):
    """Choix du fichier (§5, refonte navigation -- fenêtre modale à la
    place d'un écran séparé) : fichier de sortie pour la sauvegarde, image
    source pour le flash, un dossier de destination pour l'extraction du
    BOOT/EASYROMS (§4.4, étapes A/B — un emplacement par défaut est
    proposé, jamais imposé), ou — pour l'injection sur la carte neuve
    (étapes D/E) — une sauvegarde parmi celles déjà extraites, avec un
    repli « Parcourir… » pour une source manuelle.

    Pour le flash uniquement (étape C, mode expert -- le parcours de
    clonage du mode assisté n'a pas de choix de firmware, il restaure la
    propre sauvegarde de l'utilisateur, §5) : choix du firmware, construit
    dynamiquement depuis `identify/firmware_catalog.py::FIRMWARE_CATALOG`
    (un bouton radio par entrée, groupés dans `self._firmware_group`,
    chacun avec une pastille de statut maintenu/archivé/expérimental) --
    plutôt que des branches à trois choix codées en dur, qui ne passaient
    pas à l'échelle au-delà de trois firmwares. ROCKNIX est la seule
    entrée à téléchargement automatique (images attachées directement aux
    releases GitHub, `identify/rocknix.py`,
    `rocknix_download_requested`) ; toutes les autres sont en lien manuel
    (bouton ouvrant la page des releases dans le navigateur,
    `releases_requested`) -- vérifié individuellement pour chacune avant
    l'ajout du catalogue (voir `identify/firmware_catalog.py`)."""

    file_chosen = Signal(str)
    releases_requested = Signal(str)  # firmware sélectionné à l'instant du clic (arkos/emuelec)
    rocknix_download_requested = Signal()
    firmware_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "backup"
        self._firmware = FIRMWARE_CATALOG[0].id

        layout = QVBoxLayout(self)
        self._title = QLabel()
        self._title.setProperty("role", "title")
        layout.addWidget(self._title)

        # Taille estimée, sauvegarde système sans les jeux uniquement
        # (§4.3 : « affiche la taille estimée et demande confirmation
        # avant de lancer ») -- affichée directement sur cette fenêtre
        # plutôt que seulement dans le journal de bord, pour qu'un
        # débutant la voie avant de cliquer Suivant. `set_estimated_size`
        # la renseigne une fois l'estimation prête (calcul en arrière-plan,
        # §4.4) ; masquée par défaut et à chaque changement de mode.
        self._system_backup_size_label = QLabel()
        self._system_backup_size_label.setWordWrap(True)
        self._system_backup_size_label.setProperty("role", "secondary")
        self._system_backup_size_label.setVisible(False)
        layout.addWidget(self._system_backup_size_label)

        # Choix du firmware, flash uniquement (§5, étape de flash) --
        # une ligne par entrée du catalogue (§4.6), construite
        # dynamiquement plutôt que codée en dur : un bouton radio, une
        # pastille de statut (maintenu/archivé/expérimental), une
        # description courte sous les deux plutôt qu'une info-bulle, pour
        # rester visible sans interaction (§5 vocabulaire : pas de
        # jargon, une phrase compréhensible par un néophyte).
        self._firmware_radios: Dict[str, QRadioButton] = {}
        self._firmware_rows: List[QWidget] = []
        self._firmware_group = QButtonGroup(self)
        # Lignes dans une zone qui défile, comme `HomeScreen._rows_scroll` --
        # bug corrigé, constaté au rendu à l'ajout de dArkOSen (8e entrée) :
        # empilées directement dans la fenêtre, les lignes étaient écrasées
        # dès que leur hauteur totale dépassait celle de la fenêtre, et les
        # descriptions sur plusieurs lignes débordaient sur la ligne
        # suivante (déjà visible avant cet ajout pour ArkOS et EmuELEC).
        firmware_container = QWidget()
        firmware_layout = QVBoxLayout(firmware_container)
        firmware_layout.setContentsMargins(0, 0, 0, 0)
        self._firmware_scroll = QScrollArea()
        self._firmware_scroll.setFrameShape(QFrame.NoFrame)
        self._firmware_scroll.setWidgetResizable(True)
        self._firmware_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._firmware_scroll.setMinimumHeight(260)
        self._firmware_scroll.setWidget(firmware_container)
        layout.addWidget(self._firmware_scroll, 1)
        for entry in FIRMWARE_CATALOG:
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            header = QHBoxLayout()
            radio = QRadioButton(tr(entry.title_key))
            radio.toggled.connect(self._on_firmware_toggled)
            badge = QLabel(tr(f"firmware_status_{entry.status}"))
            badge.setProperty("role", "badge")
            badge.setProperty("badgeKind", entry.status)
            header.addWidget(radio)
            header.addWidget(badge)
            header.addStretch()
            row_layout.addLayout(header)
            desc = QLabel(tr(entry.desc_key))
            desc.setWordWrap(True)
            desc.setProperty("role", "secondary")
            row_layout.addWidget(desc)
            self._firmware_group.addButton(radio)
            self._firmware_radios[entry.id] = radio
            self._firmware_rows.append(row)
            firmware_layout.addWidget(row)
        firmware_layout.addStretch()

        # Lien manuel (tout le catalogue sauf ROCKNIX, §4.6) -- aucune
        # image hébergée directement sur GitHub pour ces entrées, donc
        # rien à automatiser au-delà de l'ouverture de la page ;
        # l'utilisateur télécharge lui-même, puis choisit le fichier
        # obtenu via Parcourir.
        self._releases_button = QPushButton(tr("file_releases_button"))
        self._releases_button.clicked.connect(lambda: self.releases_requested.emit(self._firmware))
        layout.addWidget(self._releases_button)

        # Certaines archives de firmware (ex. les images ArkOS, en .7z)
        # ne sont pas décompressées par ce logiciel
        # (imaging/image_source.py -- voir CLAUDE.md pour l'évaluation de
        # py7zr) : annoncé ici, avant même le téléchargement, plutôt que
        # de laisser un débutant découvrir le problème après coup avec un
        # fichier que le flash refuse (§5).
        self._download_hint = QLabel(tr("file_manual_download_hint"))
        self._download_hint.setWordWrap(True)
        self._download_hint.setProperty("role", "secondary")
        layout.addWidget(self._download_hint)

        # ROCKNIX -- seule entrée du catalogue dont les images sont
        # attachées directement aux releases GitHub
        # (identify/rocknix.py) : téléchargement automatique possible,
        # contrairement à toutes les autres entrées ci-dessus.
        self._rocknix_download_button = QPushButton(tr("file_rocknix_download_button"))
        self._rocknix_download_button.clicked.connect(self.rocknix_download_requested.emit)
        layout.addWidget(self._rocknix_download_button)

        self._archive_list = QListWidget()
        self._archive_list.setSelectionMode(QListWidget.SingleSelection)
        self._archive_list.itemSelectionChanged.connect(self._on_archive_selected)
        layout.addWidget(self._archive_list)

        self._archive_empty_label = QLabel(tr("file_archive_empty"))
        self._archive_empty_label.setWordWrap(True)
        layout.addWidget(self._archive_empty_label)

        self._path_label = QLabel()
        self._path_label.setWordWrap(True)
        layout.addWidget(self._path_label)

        self._destination_hint_label = QLabel(tr("file_destination_hint"))
        self._destination_hint_label.setWordWrap(True)
        self._destination_hint_label.setProperty("role", "secondary")
        layout.addWidget(self._destination_hint_label)

        browse_button = QPushButton(tr("file_browse"))
        browse_button.clicked.connect(self._browse)
        layout.addWidget(browse_button)
        layout.addStretch()

        buttons = QHBoxLayout()
        back_button = QPushButton(tr("file_back"))
        back_button.clicked.connect(self.close)
        self._next_button = QPushButton(tr("file_next"))
        self._next_button.setEnabled(False)
        self._next_button.clicked.connect(lambda: self.file_chosen.emit(self._path_label.text()))
        buttons.addWidget(back_button)
        buttons.addStretch()
        buttons.addWidget(self._next_button)
        layout.addLayout(buttons)

        self.resize(480, 420)

    def set_mode(
        self,
        mode: str,
        archive_choices: Optional[List] = None,
        default_path: Optional[str] = None,
        firmware: Optional[str] = None,
    ) -> None:
        """`mode` : "backup" (choisir où enregistrer), "flash" (choisir
        l'image source), "extract_boot"/"extract_easyroms" (choisir un
        dossier de destination — `default_path` le pré-remplit, toujours
        remplaçable via Parcourir), ou "inject_boot"/"copy_games" (choisir
        une sauvegarde parmi `archive_choices`, ou en désigner une autre
        via Parcourir). `firmware` (un id du catalogue, §4.6, ignoré hors
        flash) initialise le choix depuis la configuration persistée
        (`config.py`) plutôt que de toujours repartir sur la première
        entrée du catalogue."""
        self._mode = mode
        self._title.setText(tr(_FILE_TITLE_KEYS[mode]))
        self.setWindowTitle(tr(_FILE_TITLE_KEYS[mode]))
        self._path_label.setText(default_path or "")
        self._next_button.setEnabled(bool(default_path))
        # Toujours repartie à zéro : une estimation affichée reste propre
        # à l'ouverture qui l'a produite, jamais reportée d'un mode/appel
        # au suivant (`set_estimated_size` la renseigne à nouveau une fois
        # prête, §4.3).
        self._system_backup_size_label.setVisible(False)

        is_flash = mode == "flash"
        self._firmware_scroll.setVisible(is_flash)
        for row in self._firmware_rows:
            row.setVisible(is_flash)
        if is_flash:
            self._firmware = firmware if firmware in self._firmware_radios else FIRMWARE_CATALOG[0].id
            radio = self._firmware_radios[self._firmware]
            radio.blockSignals(True)
            radio.setChecked(True)
            radio.blockSignals(False)
            self._update_firmware_buttons_visibility()
        else:
            self._releases_button.setVisible(False)
            self._rocknix_download_button.setVisible(False)
            self._download_hint.setVisible(False)

        is_archive_mode = mode in _ARCHIVE_MODES
        self._archive_list.clear()
        if is_archive_mode:
            for path in archive_choices or []:
                item = QListWidgetItem(format_archive_label(path))
                item.setData(Qt.UserRole, str(path))
                self._archive_list.addItem(item)
        self._archive_list.setVisible(is_archive_mode)
        self._archive_empty_label.setVisible(is_archive_mode and not archive_choices)
        self._destination_hint_label.setVisible(mode in _DESTINATION_MODES)

    def set_estimated_size(self, text: str) -> None:
        """Affiche `text` (déjà formaté, ex. « Taille estimée : environ
        8,4 Go ») directement sur cette fenêtre -- sauvegarde système sans
        les jeux uniquement (§4.3), une fois l'estimation prête. Visible
        tant que `set_mode` n'a pas été rappelé depuis (qui la masque
        systématiquement, voir plus haut)."""
        self._system_backup_size_label.setText(text)
        self._system_backup_size_label.setVisible(bool(text))

    def _update_firmware_buttons_visibility(self) -> None:
        is_flash = self._mode == "flash"
        entry = FIRMWARE_BY_ID[self._firmware]
        is_manual_link = entry.releases_url is not None
        self._releases_button.setVisible(is_flash and is_manual_link)
        self._download_hint.setVisible(is_flash and is_manual_link)
        self._rocknix_download_button.setVisible(is_flash and not is_manual_link)

    def _on_firmware_toggled(self, checked: bool) -> None:
        if not checked:
            return
        for firmware_id, radio in self._firmware_radios.items():
            if radio.isChecked():
                self._firmware = firmware_id
                break
        self._update_firmware_buttons_visibility()
        self.firmware_changed.emit(self._firmware)

    def _on_archive_selected(self) -> None:
        items = self._archive_list.selectedItems()
        if items:
            self._path_label.setText(items[0].data(Qt.UserRole))
            self._next_button.setEnabled(True)

    def _browse(self) -> None:
        title = tr(_FILE_TITLE_KEYS[self._mode])
        if self._mode == "backup":
            path, _ = QFileDialog.getSaveFileName(self, title, "", "Image (*.img)")
        elif self._mode == "backup_system":
            # Démarre sur le nom de fichier proposé (§4.3) -- l'utilisateur
            # peut le remplacer entièrement, y compris l'emplacement.
            path, _ = QFileDialog.getSaveFileName(self, title, self._path_label.text(), "Image (*.img)")
        elif self._mode == "flash":
            path, _ = QFileDialog.getOpenFileName(self, title, "", "Image disque (*.img *.img.gz *.img.xz)")
        elif self._mode in _DESTINATION_MODES:
            # Démarre sur l'emplacement déjà affiché (le défaut proposé,
            # ou le dernier choisi) plutôt que de repartir de zéro.
            path = QFileDialog.getExistingDirectory(self, title, self._path_label.text())
        else:
            path = QFileDialog.getExistingDirectory(self, title)
        if path:
            self._archive_list.clearSelection()
            self._path_label.setText(path)
            self._next_button.setEnabled(True)


class ConfirmDialog(Dialog):
    """Confirmation (§5, refonte navigation -- fenêtre modale rouge à la
    place d'un écran séparé), récapitulatif explicite, case à cocher
    obligatoire — dernier rempart avant écriture (règle §2 n°6). Uniquement
    pour le flash : la sauvegarde n'écrit jamais sur un périphérique."""

    confirmed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("confirm_title"))
        self.setProperty("role", "danger")  # WA_StyledBackground déjà posé par Dialog

        layout = QVBoxLayout(self)
        title = QLabel(tr("confirm_title"))
        title.setProperty("role", "dangerTitle")
        layout.addWidget(title)

        self._message = QLabel()
        self._message.setWordWrap(True)
        self._message.setProperty("role", "dangerMessage")
        layout.addWidget(self._message)

        self._checkbox = QCheckBox(tr("confirm_checkbox"))
        self._checkbox.stateChanged.connect(self._update_go_enabled)
        layout.addWidget(self._checkbox)
        layout.addStretch()

        buttons = QHBoxLayout()
        cancel_button = QPushButton(tr("confirm_cancel"))
        cancel_button.clicked.connect(self.close)
        self._go_button = QPushButton(tr("confirm_go"))
        self._go_button.setEnabled(False)
        self._go_button.clicked.connect(self.confirmed.emit)
        buttons.addWidget(cancel_button)
        buttons.addStretch()
        buttons.addWidget(self._go_button)
        layout.addLayout(buttons)

        self.resize(440, 300)

    def set_device(self, device: Device) -> None:
        size_go = _capacity_go(device.size_bytes)
        self._message.setText(tr("confirm_erase", display=device.display, size_go=size_go))
        self._checkbox.setChecked(False)

    def _update_go_enabled(self) -> None:
        self._go_button.setEnabled(self._checkbox.isChecked())


class SameCardUnverifiedDialog(Dialog):
    """Étape 3 du parcours de clonage (§5), quand ni le contenu (empreinte
    de BOOT, §4.4) ni la taille de la carte détectée ne peuvent prouver
    qu'il s'agit d'une carte différente de la carte source -- confirmé sur
    du vrai matériel : le chemin de périphérique (`\\\\.\\PhysicalDriveN`)
    ne peut pas non plus servir de repli sur Windows, certains lecteurs de
    carte SD gardant le même chemin quelle que soit la carte insérée.
    Garde-fou le plus critique du parcours (écrire par erreur sur la carte
    source détruirait la seule copie fonctionnelle de la console) : jamais
    un passage silencieux dans ce cas -- une confirmation explicite est
    exigée, récapitulatif du modèle et de la taille détectés à l'appui,
    même esprit que `ConfirmDialog` (case à cocher obligatoire, §2
    règle 6)."""

    confirmed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("same_card_unverified_title"))
        self.setProperty("role", "danger")  # WA_StyledBackground déjà posé par Dialog

        layout = QVBoxLayout(self)
        title = QLabel(tr("same_card_unverified_title"))
        title.setProperty("role", "dangerTitle")
        layout.addWidget(title)

        self._message = QLabel()
        self._message.setWordWrap(True)
        self._message.setProperty("role", "dangerMessage")
        layout.addWidget(self._message)

        self._checkbox = QCheckBox(tr("same_card_unverified_checkbox"))
        self._checkbox.stateChanged.connect(self._update_go_enabled)
        layout.addWidget(self._checkbox)
        layout.addStretch()

        buttons = QHBoxLayout()
        cancel_button = QPushButton(tr("confirm_cancel"))
        cancel_button.clicked.connect(self.close)
        self._go_button = QPushButton(tr("same_card_unverified_confirm"))
        self._go_button.setEnabled(False)
        self._go_button.clicked.connect(self.confirmed.emit)
        buttons.addWidget(cancel_button)
        buttons.addStretch()
        buttons.addWidget(self._go_button)
        layout.addLayout(buttons)

        self.resize(460, 320)

    def set_device(self, device: Device) -> None:
        size_go = _capacity_go(device.size_bytes) if device.size_bytes else 0.0
        self._message.setText(tr("same_card_unverified_message", display=device.display, size_go=size_go))
        self._checkbox.setChecked(False)

    def _update_go_enabled(self) -> None:
        self._go_button.setEnabled(self._checkbox.isChecked())


class BackupKindDialog(Dialog):
    """Étape 2 du parcours de clonage (§5 mode assisté) : demande quoi
    sauvegarder avant de créer l'image sur l'ordinateur -- copie complète
    (système + jeux, réutilise `imaging.backup_device`) ou système seul
    (sans les jeux, réutilise `imaging.backup_system_only` via le pipeline
    d'estimation déjà en place pour l'opération ad-hoc équivalente de
    l'accueil assisté). Même forme que l'ancien `ArchiveReuseDialog`
    qu'elle remplace : deux boutons principaux avec une courte description
    chacun, jamais un choix pré-coché -- l'utilisateur choisit toujours
    activement (§5 vocabulaire)."""

    full_copy_requested = Signal()
    system_only_requested = Signal()
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._title = QLabel(tr("wizard_backup_kind_title"))
        self._title.setProperty("role", "title")
        self.setWindowTitle(tr("wizard_backup_kind_title"))
        layout.addWidget(self._title)
        layout.addStretch()

        self._full_button = QPushButton(tr("wizard_backup_kind_full"))
        self._full_button.setProperty("role", "primary")
        self._full_button.setDefault(True)
        self._full_button.clicked.connect(self._on_full)
        full_desc = QLabel(tr("wizard_backup_kind_full_desc"))
        full_desc.setWordWrap(True)
        full_desc.setProperty("role", "secondary")
        layout.addWidget(self._full_button)
        layout.addWidget(full_desc)

        self._system_button = QPushButton(tr("wizard_backup_kind_system"))
        self._system_button.clicked.connect(self._on_system)
        system_desc = QLabel(tr("wizard_backup_kind_system_desc"))
        system_desc.setWordWrap(True)
        system_desc.setProperty("role", "secondary")
        layout.addWidget(self._system_button)
        layout.addWidget(system_desc)
        layout.addStretch()

        buttons = QHBoxLayout()
        cancel_button = QPushButton(tr("confirm_cancel"))
        cancel_button.clicked.connect(self._on_cancel)
        buttons.addWidget(cancel_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.resize(460, 320)

    def _on_full(self) -> None:
        self.close()
        self.full_copy_requested.emit()

    def _on_system(self) -> None:
        self.close()
        self.system_only_requested.emit()

    def _on_cancel(self) -> None:
        self.close()
        self.cancelled.emit()


class ResetCardLabelDialog(Dialog):
    """« Remettre la carte à zéro » (§4.3 bis, mode expert uniquement) --
    choisit l'étiquette du volume et son système de fichiers avant la
    fenêtre Confirmation obligatoire (§2 n°6, ouverte ensuite par
    l'appelant). `set_default_label`/`set_default_filesystem` pré-
    remplissent des valeurs simples à chaque ouverture -- jamais imposées,
    toujours remplaçables, même principe que les chemins par défaut
    proposés ailleurs dans ce projet (§4.4).

    Choix du système de fichiers ajouté suite à un signalement (carte de
    SF3000HD inutilisable après le formatage exFAT jusque-là
    systématique -- vraisemblablement pour TreeFrogUI, la carte d'origine
    de cette console étant elle-même en exFAT, voir docs/claude/
    reset-card.md). exFAT reste le choix par
    défaut (le plus courant) ; FAT32 est décrit en une phrase plutôt
    qu'en jargon technique sec (§5 vocabulaire), avec un rappel de sa
    limite de taille de fichier (4 Go) -- une surprise plausible pour un
    néophyte qui y copierait un gros fichier plus tard."""

    label_chosen = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("reset_card_label_title"))

        layout = QVBoxLayout(self)
        title = QLabel(tr("reset_card_label_title"))
        title.setProperty("role", "title")
        layout.addWidget(title)

        instruction = QLabel(tr("reset_card_label_instruction"))
        instruction.setWordWrap(True)
        instruction.setProperty("role", "secondary")
        layout.addWidget(instruction)

        self._label_edit = QLineEdit()
        self._label_edit.returnPressed.connect(self._on_continue)
        layout.addWidget(self._label_edit)

        filesystem_title = QLabel(tr("reset_card_filesystem_title"))
        filesystem_title.setProperty("role", "secondary")
        layout.addWidget(filesystem_title)

        self._filesystem_group = QButtonGroup(self)

        self._exfat_radio = QRadioButton(tr("reset_card_filesystem_exfat"))
        self._exfat_radio.setChecked(True)
        exfat_desc = QLabel(tr("reset_card_filesystem_exfat_desc"))
        exfat_desc.setWordWrap(True)
        exfat_desc.setProperty("role", "secondary")
        self._filesystem_group.addButton(self._exfat_radio)
        layout.addWidget(self._exfat_radio)
        layout.addWidget(exfat_desc)

        self._fat32_radio = QRadioButton(tr("reset_card_filesystem_fat32"))
        fat32_desc = QLabel(tr("reset_card_filesystem_fat32_desc"))
        fat32_desc.setWordWrap(True)
        fat32_desc.setProperty("role", "secondary")
        self._filesystem_group.addButton(self._fat32_radio)
        layout.addWidget(self._fat32_radio)
        layout.addWidget(fat32_desc)

        # Rappel de la limite de taille de fichier du FAT32 (4 Go) --
        # visible seulement quand ce choix est sélectionné, plutôt qu'en
        # permanence (n'a aucun sens tant qu'exFAT, sans cette limite,
        # reste choisi).
        self._fat32_file_size_note = QLabel(tr("reset_card_filesystem_fat32_note"))
        self._fat32_file_size_note.setWordWrap(True)
        self._fat32_file_size_note.setProperty("role", "secondary")
        self._fat32_file_size_note.setVisible(False)
        layout.addWidget(self._fat32_file_size_note)
        self._fat32_radio.toggled.connect(self._fat32_file_size_note.setVisible)

        layout.addStretch()

        buttons = QHBoxLayout()
        cancel_button = QPushButton(tr("confirm_cancel"))
        cancel_button.clicked.connect(self.close)
        self._continue_button = QPushButton(tr("reset_card_label_continue"))
        self._continue_button.setProperty("role", "primary")
        self._continue_button.setDefault(True)
        self._continue_button.clicked.connect(self._on_continue)
        buttons.addWidget(cancel_button)
        buttons.addStretch()
        buttons.addWidget(self._continue_button)
        layout.addLayout(buttons)

        self.resize(460, 420)

    def set_default_label(self, label: str) -> None:
        self._label_edit.setText(label)

    def set_default_filesystem(self, filesystem: str) -> None:
        if filesystem == "fat32":
            self._fat32_radio.setChecked(True)
        else:
            self._exfat_radio.setChecked(True)

    def _on_continue(self) -> None:
        label = self._label_edit.text().strip()
        if not label:
            return
        filesystem = "fat32" if self._fat32_radio.isChecked() else "exfat"
        self.close()
        self.label_chosen.emit(label, filesystem)


class WholeCardChoiceDialog(Dialog):
    """Image de carte SF3000 plus petite que la carte cible (mode expert,
    `imaging/sf3000_clone.py`) : utiliser toute la carte (copie fichier par
    fichier, plus longue) ou copie brute (plus rapide, le reste de la carte
    perdu). Chaque option annonce son coût -- la durée en plus, l'espace
    inutilisable -- demandé explicitement après un clone de 48,8 Go sur
    128 Go qui en avait perdu 70 sans le dire. Précède toujours la fenêtre
    Confirmation (§2 n°6)."""

    choice_made = Signal(bool, bool)  # (toute la carte, vérifier chaque fichier)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("whole_card_title"))

        layout = QVBoxLayout(self)
        title = QLabel(tr("whole_card_title"))
        title.setProperty("role", "title")
        layout.addWidget(title)

        instruction = QLabel(tr("whole_card_instruction"))
        instruction.setWordWrap(True)
        instruction.setProperty("role", "secondary")
        layout.addWidget(instruction)

        self._group = QButtonGroup(self)
        self._whole_radio = QRadioButton(tr("whole_card_option_whole"))
        self._whole_radio.setChecked(True)
        self._whole_desc = QLabel()
        self._whole_desc.setWordWrap(True)
        self._whole_desc.setProperty("role", "secondary")
        self._raw_radio = QRadioButton(tr("whole_card_option_raw"))
        self._raw_desc = QLabel()
        self._raw_desc.setWordWrap(True)
        self._raw_desc.setProperty("role", "secondary")
        for widget in (self._whole_radio, self._whole_desc, self._raw_radio, self._raw_desc):
            layout.addWidget(widget)
        self._group.addButton(self._whole_radio)
        self._group.addButton(self._raw_radio)

        self._verify_check = QCheckBox()
        self._verify_check.setChecked(True)
        layout.addWidget(self._verify_check)
        # La vérification ne concerne que la copie fichier par fichier (la
        # copie brute vérifie toujours toute l'image).
        self._whole_radio.toggled.connect(self._verify_check.setEnabled)

        layout.addStretch()

        buttons = QHBoxLayout()
        cancel_button = QPushButton(tr("confirm_cancel"))
        cancel_button.clicked.connect(self.close)
        continue_button = QPushButton(tr("whole_card_continue"))
        continue_button.setProperty("role", "primary")
        continue_button.setDefault(True)
        continue_button.clicked.connect(self._on_continue)
        buttons.addWidget(cancel_button)
        buttons.addStretch()
        buttons.addWidget(continue_button)
        layout.addLayout(buttons)

        self.resize(480, 420)

    def set_estimates(self, card_bytes: int, image_bytes: int, extra_minutes: int, verify_minutes: int) -> None:
        """Remet aussi les choix par défaut (toute la carte, vérification)."""
        self._whole_desc.setText(
            tr("whole_card_option_whole_desc", card=_format_size(card_bytes), extra=extra_minutes)
        )
        self._raw_desc.setText(
            tr(
                "whole_card_option_raw_desc",
                image=_format_size(image_bytes),
                remaining=_format_size(max(0, card_bytes - image_bytes)),
            )
        )
        self._verify_check.setText(tr("whole_card_verify", minutes=verify_minutes))
        self._whole_radio.setChecked(True)
        self._verify_check.setChecked(True)

    def _on_continue(self) -> None:
        self.close()
        self.choice_made.emit(self._whole_radio.isChecked(), self._verify_check.isChecked())


_OPERATION_TITLE_KEYS = {
    "backup": "execute_title_backup",
    "backup_system": "execute_title_backup_system",
    "flash": "execute_title_flash",
    "reset_card": "execute_title_reset_card",
    "extract_boot": "execute_title_extract_boot",
    "extract_easyroms": "execute_title_extract_easyroms",
    "inject_boot": "execute_title_inject_boot",
    "copy_games": "execute_title_copy_games",
    "eject": "home_step_f_title",
}


class LogPanel(QFrame):
    """Journal de bord permanent, en bas de la colonne droite (§5, refonte
    navigation) : remplace les anciens écrans Exécution et Résultat,
    désormais supprimés — plus de navigation vers un écran séparé, tout se
    passe ici. Cadre à bordure cyan, fond très sombre, texte vert clair en
    police monospace pour les lignes du journal.

    En-tête « OPÉRATION ACTIVE » suivi du nom de l'étape en cours, ou
    « En attente » au repos (§5). Barre de progression (débit, temps
    restant) sous l'en-tête pendant une opération. Lignes horodatées en
    dessous (`10:44:02 - Montage des partitions: OK`), qui défilent
    automatiquement et s'accumulent pour la durée de l'opération en cours
    -- vidées seulement au démarrage de la suivante (`start_operation`),
    jamais entre-temps. Les résultats de fin d'opération (succès ou
    erreur) s'affichent comme une ligne de plus dans le journal, avec les
    actions qui suivaient auparavant sur l'écran Résultat (éjecter,
    afficher dans le gestionnaire de fichiers) réapparaissant dans
    l'en-tête plutôt qu'ailleurs."""

    cancel_requested = Signal()
    eject_requested = Signal()
    reveal_requested = Signal(str)  # chemin à révéler

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "logPanel")
        # État explicite plutôt que `_cancel_button.isVisible()` -- piège Qt
        # déjà rencontré ailleurs dans ce fichier : `isVisible()` ne reflète
        # `setVisible(True)` qu'une fois la fenêtre réellement affichée
        # (chaîne de visibilité des parents comprise), pas dans un test
        # hors écran qui ne l'affiche jamais. `is_operation_active()` doit
        # rester fiable même dans ce cas (`MainWindow.closeEvent`, §2).
        self._operation_active = False
        layout = QVBoxLayout(self)

        header_row = QHBoxLayout()
        self._header_label = QLabel()
        self._header_label.setProperty("role", "logHeader")
        header_row.addWidget(self._header_label)
        header_row.addStretch()

        self._reveal_button = QPushButton(reveal_label())
        self._reveal_button.setVisible(False)
        self._reveal_button.clicked.connect(lambda: self.reveal_requested.emit(self._reveal_path))
        header_row.addWidget(self._reveal_button)

        self._eject_button = QPushButton(tr("result_eject"))
        self._eject_button.setVisible(False)
        self._eject_button.clicked.connect(self.eject_requested.emit)
        header_row.addWidget(self._eject_button)

        self._cancel_button = QPushButton(tr("execute_cancel"))
        self._cancel_button.setProperty("role", "primary")
        self._cancel_button.setVisible(False)
        self._cancel_button.clicked.connect(self.cancel_requested.emit)
        header_row.addWidget(self._cancel_button)

        layout.addLayout(header_row)

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setVisible(False)
        layout.addWidget(self._bar)

        self._speed_label = QLabel()
        self._speed_label.setProperty("role", "secondary")
        self._speed_label.setVisible(False)
        layout.addWidget(self._speed_label)
        self._eta_label = QLabel()
        self._eta_label.setProperty("role", "secondary")
        self._eta_label.setVisible(False)
        layout.addWidget(self._eta_label)

        self._log_view = QPlainTextEdit()
        self._log_view.setProperty("role", "log")
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(2000)  # borne raisonnable, jamais atteinte en usage normal
        layout.addWidget(self._log_view, 1)

        self._reveal_path: Optional[str] = None
        self.set_idle()

    # --- cycle d'une opération -------------------------------------------

    def set_idle(self) -> None:
        """État de repos initial (§5) : avant toute opération. Contrairement
        à `finish_success`/`finish_error`, masque aussi les boutons
        Éjecter/Afficher -- rien à proposer tant qu'aucune opération n'a
        encore eu lieu."""
        self._operation_active = False
        self._header_label.setText(tr("log_header_idle"))
        self._bar.setVisible(False)
        self._speed_label.setVisible(False)
        self._eta_label.setVisible(False)
        self._cancel_button.setVisible(False)
        self._eject_button.setVisible(False)
        self._reveal_button.setVisible(False)

    def start_operation(self, title: str) -> None:
        self._operation_active = True
        self._header_label.setText(tr("log_header_active", title=title))
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setVisible(True)
        self._speed_label.setText("")
        self._speed_label.setVisible(True)
        self._eta_label.setText(tr("execute_eta_unknown"))
        self._eta_label.setVisible(True)
        self._cancel_button.setVisible(True)
        self._cancel_button.setEnabled(True)
        self._eject_button.setVisible(False)
        self._reveal_button.setVisible(False)
        self._log_view.clear()  # ne conserve l'historique que de l'opération qui démarre (§5)

    def update_progress(self, done: int, total: int, speed: float) -> None:
        if total > 0:
            self._bar.setRange(0, 100)
            self._bar.setValue(int(done * 100 / total))
        else:
            # Taille inconnue (image .img.xz, §4.3) : pas de fausse
            # progression (règle §2 n°5) -- barre indéterminée.
            self._bar.setRange(0, 0)

        self._speed_label.setText(tr("execute_speed", speed=speed / 1_000_000))

        if total > 0 and speed > 0:
            remaining_seconds = max(0, (total - done)) / speed
            self._eta_label.setText(tr("execute_eta", eta=_format_duration(remaining_seconds)))
        else:
            self._eta_label.setText(tr("execute_eta_unknown"))

    def update_step_progress(self, step_index: int, step_count: int, step_name: str) -> None:
        """Progression par étapes réelles plutôt que par octets (§2 n°5 :
        jamais une progression simulée) -- « Remettre la carte à zéro »
        (§4.3 bis) n'a rien à copier, mais chaque étape terminée
        (effacement, création, formatage, éjection) est un jalon réel : la
        barre n'avance qu'à chaque étape effectivement terminée, jamais à
        un minuteur. `step_index` : nombre d'étapes déjà terminées (0 au
        tout début, `step_count` à la toute fin -- 100 %). Le débit/temps
        restant n'ont pas de sens ici (quelques secondes, non
        prévisibles) : `step_name` (l'étape EN COURS) les remplace."""
        self._bar.setRange(0, 100)
        self._bar.setValue(int(step_index * 100 / step_count) if step_count else 0)
        self._speed_label.setText(step_name)
        self._speed_label.setVisible(True)
        self._eta_label.setVisible(False)

    def append_log(self, msg: str) -> None:
        """Ajoute une ligne horodatée (`21:44:02 - {msg}`) au journal de
        bord et fait défiler jusqu'en bas -- jamais de remplacement de
        l'historique."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._log_view.appendPlainText(f"{timestamp} - {msg}")
        scrollbar = self._log_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def set_cancel_enabled(self, enabled: bool) -> None:
        self._cancel_button.setEnabled(enabled)

    def is_operation_active(self) -> bool:
        """Vrai entre `start_operation` et `finish_success`/`finish_error`
        -- drapeau explicite plutôt que `_cancel_button.isVisible()` (qui
        ne reflète `setVisible(True)` qu'une fois la fenêtre réellement
        affichée, jamais le cas dans un test hors écran). Utilisé par
        `MainWindow.closeEvent` pour savoir s'il faut arrêter un worker
        élevé encore en cours avant de fermer (§2 -- un worker orphelin
        peut garder un verrou sur une carte SD, un risque réel plutôt
        qu'une simple gêne)."""
        return self._operation_active

    # --- fin d'opération : résultat affiché dans le journal, pas un écran -

    def finish_success(self, message: str, allow_eject: bool, reveal_path: Optional[str]) -> None:
        self._operation_active = False
        self.append_log(message)
        self._reveal_path = reveal_path
        self._reveal_button.setVisible(bool(reveal_path))
        self._eject_button.setVisible(allow_eject)
        self._bar.setVisible(False)
        self._speed_label.setVisible(False)
        self._eta_label.setVisible(False)
        self._cancel_button.setVisible(False)
        self._header_label.setText(tr("log_header_idle"))

    def finish_error(self, message: str, details: str = "") -> None:
        self._operation_active = False
        self.append_log(message)
        if details and details != message:
            self.append_log(details)
        self._reveal_button.setVisible(False)
        self._eject_button.setVisible(False)
        self._bar.setVisible(False)
        self._speed_label.setVisible(False)
        self._eta_label.setVisible(False)
        self._cancel_button.setVisible(False)
        self._header_label.setText(tr("log_header_idle"))


def _format_duration(seconds: float) -> str:
    seconds = int(seconds)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {seconds:02d} s"
    return f"{seconds} s"


def _format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("unit_bytes", "unit_kb", "unit_mb", "unit_gb"):
        if size < 1024 or unit == "unit_gb":
            return f"{int(size)} {tr(unit)}" if unit == "unit_bytes" else f"{size:.1f} {tr(unit)}"
        size /= 1024
    return f"{size:.1f} {tr('unit_tb')}"


def _capacity_go(size_bytes: int) -> float:
    """Capacité d'une carte entière, en « Go » -- calculée en base 1024
    (comme `_format_size` ci-dessus), pas en base 1000. Signalé sur du
    vrai matériel : l'app affichait « 31,9 Go » (alors calculée en base
    1000, `/ 1_000_000_000`) là où l'Explorateur Windows affiche « 29,7
    Go » pour la même carte -- au point qu'un utilisateur pouvait croire à
    une perte de capacité.

    Vérifié plutôt que supposé (les trois OS n'ont *pas* la même
    convention, aucune ne fait consensus) :
    - **Windows** (Explorateur) : base 1024, étiqueté « Go » -- c'est la
      source de l'écart signalé (31 907 643 392 octets -> 29,7 « Go »).
    - **macOS** (Finder) : base 1000 depuis Snow Leopard (10.6, 2009),
      étiqueté « Go » correctement -- ce que l'app calculait déjà pour la
      capacité d'une carte, mais pas pour les octets copiés/archivés
      (`_format_size`, toujours en base 1024). L'app avait donc déjà DEUX
      conventions différentes en interne, pas seulement un désaccord avec
      Windows.
    - **Linux** : mélangé selon le gestionnaire de fichiers -- GNOME
      Fichiers (Nautilus) suit la même convention que macOS (base 1000,
      « Go » correctement étiqueté) ; les outils historiques en ligne de
      commande (`df`, `lsblk`) utilisent traditionnellement la base 1024
      avec un « G » tout aussi ambigu que celui de Windows. Aucune
      convention unique ne fait donc consensus sur Linux non plus.

    Choix retenu, faute de convention qui satisferait les trois OS à la
    fois : aligner **toute** l'app sur une seule et même base -- celle
    déjà utilisée par `_format_size` (base 1024), pour ne plus jamais
    avoir deux nombres différents pour la même carte selon l'écran
    consulté au sein de cette app. Ce choix rapproche aussi l'affichage de
    Windows, la plateforme la plus testée sur du vrai matériel dans ce
    projet -- au prix d'un désaccord avec le Finder macOS/Nautilus (une
    carte annoncée « 128 Go » par son fabricant, et vue comme telle dans
    Finder, s'affichera ici autour de 119 Go, comme dans l'Explorateur
    Windows) : aucune option n'évite complètement l'écart, celle-ci
    l'élimine au moins entre les propres écrans de l'app, et avec la
    plateforme la plus vérifiée ici."""
    return size_bytes / (1024**3)


class HelpDialog(Dialog):
    """Aide (macOS uniquement, §3 -- fenêtre modale à la place d'un écran
    séparé) : explique l'autorisation Accès complet au disque, que chaque
    utilisateur doit accorder une fois pour que R36S Studio accède à la
    carte SD. Accessible depuis la colonne gauche (`HomeScreen.
    help_requested`).

    Contrairement au reste de l'interface (§5 : jamais de jargon), le texte
    ici nomme volontairement les vrais réglages système (« Réglages
    Système », « Accès complet au disque ») -- c'est une procédure système
    réelle à suivre, pas la description d'une action de l'app."""

    open_settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("help_title"))
        layout = QVBoxLayout(self)

        title = QLabel(tr("help_title"))
        title.setProperty("role", "title")
        layout.addWidget(title)

        body = QLabel(tr("help_body"))
        body.setWordWrap(True)
        layout.addWidget(body)
        layout.addStretch()

        buttons = QHBoxLayout()
        self._back_button = QPushButton(tr("help_back"))
        self._back_button.clicked.connect(self.close)
        self._open_settings_button = QPushButton(tr("help_open_settings"))
        self._open_settings_button.clicked.connect(self.open_settings_requested.emit)
        buttons.addWidget(self._back_button)
        buttons.addStretch()
        buttons.addWidget(self._open_settings_button)
        layout.addLayout(buttons)

        self.resize(440, 380)


class MainView(Screen):
    """Vue principale, permanente (§5, refonte navigation) : deux colonnes
    -- une colonne gauche, largeur fixe autour de 480 px (`HomeScreen` en
    mode expert, ou `WizardStepPanel` en mode assisté -- un petit
    `QStackedWidget` interne bascule entre les deux, §5 mode assisté) et
    une colonne droite avec l'image de la console en haut et le journal
    de bord en bas -- devant un motif de fond en mosaïque sur toute la
    fenêtre (`WindowBackdrop`, absent sans lever si `assets/circuit.png`
    n'existe pas). Construite une fois par `MainWindow` (`setCentralWidget`) ;
    la structure ne change plus jamais ensuite -- les choix ponctuels
    (carte, fichier, confirmation, aide) s'ouvrent en fenêtres modales
    par-dessus, jamais en remplacement de cette vue."""

    _LEFT_COLUMN_WIDTH = 480

    def __init__(
        self,
        home: HomeScreen,
        console_stage: Optional[ConsoleStage],
        log_panel: LogPanel,
        wizard_panel: Optional["WizardStepPanel"] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.console_stage = console_stage

        # Motif de fond sur toute la fenêtre, envoyé derrière les colonnes
        # (`lower()`) -- posé avant le layout pour qu'il n'intercepte
        # jamais les widgets ajoutés ensuite.
        self._backdrop = build_window_backdrop(self)
        if self._backdrop is not None:
            self._backdrop.lower()

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # `setFixedWidth` sur chaque widget individuellement (pas sur le
        # `QStackedWidget` qui les contient) : un test peut ainsi vérifier
        # la largeur d'un widget donné indépendamment de son conteneur.
        self._left_stack = QStackedWidget()
        self._home = home
        self._wizard_panel = wizard_panel
        home.setFixedWidth(self._LEFT_COLUMN_WIDTH)
        self._left_stack.addWidget(home)
        if wizard_panel is not None:
            wizard_panel.setFixedWidth(self._LEFT_COLUMN_WIDTH)
            self._left_stack.addWidget(wizard_panel)
        root.addWidget(self._left_stack)

        right_column = QVBoxLayout()
        right_column.setContentsMargins(12, 12, 12, 12)
        right_column.setSpacing(12)
        if console_stage is not None:
            right_column.addWidget(console_stage, 3)
        right_column.addWidget(log_panel, 2)
        root.addLayout(right_column, 1)

    def show_home(self) -> None:
        self._left_stack.setCurrentWidget(self._home)

    def show_wizard_panel(self) -> None:
        """Pas d'effet si aucun `wizard_panel` n'a été fourni (mode expert
        seul) -- reste sur `home`."""
        if self._wizard_panel is not None:
            self._left_stack.setCurrentWidget(self._wizard_panel)

    def resizeEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        super().resizeEvent(event)
        if self._backdrop is not None:
            self._backdrop.setGeometry(self.rect())


class FullDiskAccessScreen(Screen):
    """Écran de bienvenue macOS uniquement, affiché tant que l'Accès
    complet au disque n'est pas détecté (`elevate.has_full_disk_access`,
    §3) -- à la place de l'accueil habituel (assisté ou expert), qui
    n'apparaît qu'une fois l'autorisation confirmée. `MainWindow` décide
    quand construire/afficher cet écran ; lui-même ne sait rien du reste
    du parcours, seulement expliquer la procédure et laisser vérifier.

    Contrairement au reste de l'interface (§5 : jamais de jargon), le
    texte ici nomme volontairement les vrais réglages système -- même
    principe que `HelpDialog`, dont ce texte reprend l'essentiel adapté au
    premier lancement (§3, LISEZ-MOI.txt de l'archive de distribution)."""

    open_settings_requested = Signal()
    recheck_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._backdrop = build_window_backdrop(self)
        if self._backdrop is not None:
            self._backdrop.lower()

        root = QVBoxLayout(self)
        root.setContentsMargins(48, 32, 48, 32)
        root.addStretch(1)

        title = QLabel(tr("fda_welcome_title"))
        title.setProperty("role", "title")
        root.addWidget(title)

        body = QLabel(tr("fda_welcome_body"))
        body.setWordWrap(True)
        root.addWidget(body)

        self._still_not_detected_label = QLabel(tr("fda_welcome_still_not_detected"))
        self._still_not_detected_label.setProperty("role", "danger")
        self._still_not_detected_label.setWordWrap(True)
        self._still_not_detected_label.setVisible(False)
        root.addWidget(self._still_not_detected_label)

        root.addStretch(1)

        buttons = QHBoxLayout()
        self._open_settings_button = QPushButton(tr("fda_welcome_open_settings"))
        self._open_settings_button.clicked.connect(self.open_settings_requested.emit)
        buttons.addWidget(self._open_settings_button)
        buttons.addStretch()
        self._done_button = QPushButton(tr("fda_welcome_done"))
        self._done_button.setProperty("role", "cta")
        self._done_button.clicked.connect(self.recheck_requested.emit)
        buttons.addWidget(self._done_button)
        root.addLayout(buttons)

    def set_still_not_detected(self, still_not_detected: bool) -> None:
        """Après un clic sur « J'ai terminé » qui ne détecte toujours pas
        l'autorisation -- jamais un échec silencieux (§5) : l'utilisateur
        doit savoir que son clic a bien été pris en compte, pas seulement
        que rien ne s'est passé."""
        self._still_not_detected_label.setVisible(still_not_detected)

    def resizeEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        super().resizeEvent(event)
        if self._backdrop is not None:
            self._backdrop.setGeometry(self.rect())


# Grille de tuiles de l'accueil assisté (§5, refonte menu de tuiles) :
# (glyphe, clé du libellé, rôle QSS, nom du signal émis au clic, clé de
# statut `detect.StepStatus` ou `None` si la tuile n'affiche jamais de
# badge, largeur en colonnes). Ordre = ordre d'apparition dans la grille
# (4 colonnes), après la tuile 1 (double largeur, construite à part plus
# bas -- seule à porter icône/libellé agrandis et une description).
# 2 (double) + 2 = rangée 0 pleine ; 4 = rangée 1 pleine ; 2 = rangée 2,
# 9 tuiles au total (« Rechercher ma console » et « Consoles diverses »
# fusionnées en une seule tuile « Identifier ma console » -- l'écran de
# résultat de l'identification propose l'accès au catalogue en dessous,
# `IdentifyResultDialog.catalog_requested`).
#
# « Remettre l'écran d'origine » (inject_boot) retirée de cette grille
# (§5, correctif visuel) : déjà couverte par le mode expert (ligne D) et
# par le parcours guidé lui-même (qui restaure l'écran d'origine avec le
# reste de l'image), elle n'apportait rien de plus ici. `inject_boot`
# reste pleinement fonctionnelle ailleurs -- seule cette tuile disparaît,
# avec son signal (`inject_boot_requested`) et l'entrée correspondante
# des tables ad-hoc de `main_window.py`.
_ASSISTED_TILE_SPECS = [
    ("identify", "assisted_tile_identify", "tile", "identify_requested", IDENTIFY, 1),
    ("backup", "assisted_tile_backup", "tile", "backup_requested", None, 1),
    ("eject", "assisted_tile_eject", "tile", "eject_requested", EJECT, 1),
    ("help", "assisted_tile_help", "tile", "help_requested", None, 1),
]
# Accueil allégé pour le néophyte (§1) : seulement ce qui sert à préparer
# une première carte. « Installer un système », « Copier mes jeux »,
# « Chercher les doublons », « Ranger mes jeux », « Remettre la carte à
# zéro », « Console Android » et « Web » vivent désormais uniquement en
# mode expert (`HomeScreen`), à un clic via le bouton « Mode expert ».

_ASSISTED_TILE_GRID_COLUMNS = 4

_ICON_COLOR_BY_ROLE = {
    "tileEmphasized": "BG_DARK",
    "tileDestructive": "DANGER_FG",
}

# Icône du panneau « Carte détectée » (§5, refonte menu de tuiles,
# correctif visuel) -- nettement plus grande que celle du bandeau
# horizontal de HomeScreen (28, inchangée là-bas).
_ASSISTED_PANEL_ICON_SIZE = 110

# Nombre de rangées dérivé du nombre de tuiles (retour à la ligne
# automatique : la tuile 1 occupe deux cellules, les autres une chacune),
# jamais une constante à resynchroniser à la main quand la grille change
# -- toujours calculé ici plutôt qu'à partir d'un widget dans un
# `QScrollArea`, dont le `sizeHint` ne reflète pas fidèlement un contenu
# défilable (§5, correctif visuel). Sert à donner au panneau « Carte
# détectée » exactement la même hauteur que la grille (`Tile.SIZE *
# lignes + Tile.SPACING * (lignes - 1)`) et à garantir que la fenêtre
# s'ouvre assez grande pour afficher toutes les rangées sans défiler
# (`main_window.py`).
_ASSISTED_GRID_CELLS = 2 + sum(spec[5] for spec in _ASSISTED_TILE_SPECS)
_ASSISTED_GRID_ROWS = -(-_ASSISTED_GRID_CELLS // _ASSISTED_TILE_GRID_COLUMNS)
_ASSISTED_GRID_TOTAL_HEIGHT = _ASSISTED_GRID_ROWS * Tile.SIZE + (_ASSISTED_GRID_ROWS - 1) * Tile.SPACING
_ASSISTED_GRID_TOTAL_WIDTH = _ASSISTED_TILE_GRID_COLUMNS * Tile.SIZE + (_ASSISTED_TILE_GRID_COLUMNS - 1) * Tile.SPACING
# Gouttière entre la grille et le panneau de droite -- distincte de
# `Tile.SPACING` (12, entre les tuiles elles-mêmes), plus large pour
# séparer clairement les deux zones (§5, correctif visuel).
_ASSISTED_CONTENT_SPACING = 40
# Largeur fixe du panneau « Carte détectée » (§5, correctif visuel, point
# 2) -- constante nommée plutôt qu'un nombre répété dans `main_window.py`
# (calcul de la taille minimale de fenêtre) et ici (construction du
# panneau) : une seule source de vérité.
_ASSISTED_PANEL_WIDTH = 308
# Largeur totale du bloc centré (§5, correctif de centrage) : grille +
# gouttière + panneau, jamais recalculée séparément. L'en-tête et
# l'étiquette de section sont chacun placés dans un conteneur de cette
# même largeur, lui-même centré de la même façon (`addStretch` de même
# facteur avant/après) que la grille+panneau -- sans ça, ces deux lignes
# resteraient calées sur les bords de la fenêtre pendant que le bloc
# grille+panneau se centre en dessous, un décalage visuel entre le titre
# et les tuiles qu'il surplombe.
_ASSISTED_CENTERED_BLOCK_WIDTH = _ASSISTED_GRID_TOTAL_WIDTH + _ASSISTED_CONTENT_SPACING + _ASSISTED_PANEL_WIDTH


def _centered_row(widget: QWidget) -> QHBoxLayout:
    """Enveloppe `widget` (largeur fixe) dans une ligne horizontale qui le
    centre -- `addStretch` de même facteur (1) de part et d'autre, pour
    que le vide restant de la fenêtre se répartisse également des deux
    côtés plutôt que de se concentrer à droite (§5, correctif de
    centrage). Réutilisée pour l'en-tête, l'étiquette de section, et
    directement en ligne pour la grille+panneau (`content_row`, qui a
    déjà sa propre largeur fixe cumulée par construction)."""
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(widget)
    row.addStretch(1)
    return row


class AssistedLandingScreen(Screen):
    """Écran d'accueil du mode assisté (§5 mode assisté) -- par défaut au
    lancement (`ui_mode` en configuration, §6). Grille de tuiles façon
    menu d'applications (refonte menu de tuiles, remplace la console en
    grand + 3 boutons) : chaque tuile expose une action déjà disponible en
    mode expert (ou nouvelle -- identification, doublons), avec le même
    système de badges de statut (`detect.StepStatus`) que `HomeScreen`.
    La console n'est plus affichée en grand ici -- `ConsoleStage`/
    `ConsoleArt` restent utilisés ailleurs (`MainView`), pas sur cet écran
    -- seule une `_ConsoleIcon` agrandie figure dans le panneau « Carte
    détectée » à droite de la grille, même icône que le bandeau de
    `HomeScreen`.

    Grille à taille fixe, alignée en haut à gauche (`Qt.AlignTop |
    Qt.AlignLeft`, jamais de facteur d'étirement) -- correctif visuel :
    les tuiles s'étiraient auparavant en rectangles pour remplir l'espace
    disponible, l'effet « menu d'applications » en dépend. La fenêtre
    peut respirer autour (`addStretch()` après la grille/le panneau, à
    droite et en bas).

    **Fond uni, jamais `WindowBackdrop`** (§5, correctif visuel) --
    contrairement à `MainView`/l'ancien accueil assisté (console en
    grand), cet écran n'affiche plus le motif décoratif « circuit imprimé »
    : `WindowBackdrop`/`build_window_backdrop` restent pleinement en
    place et utilisés ailleurs, simplement jamais instanciés ici."""

    prepare_requested = Signal()
    identify_requested = Signal()
    backup_requested = Signal()
    eject_requested = Signal()
    help_requested = Signal()
    expert_mode_requested = Signal()
    # Choix de la langue (i18n.py), même rôle que sur `HomeScreen`.
    language_selected = Signal(str)
    refresh_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        root = QVBoxLayout(self)
        # Marges resserrées (§5, correctif visuel, deuxième correctif de
        # taille) : la grille elle-même est fixe (624 -- trois rangées de
        # 200 + deux gouttières de 12, jamais autre chose) ; c'est donc
        # uniquement l'habillage autour d'elle (marges, en-tête, étiquette
        # de section) qui doit rester le plus compact possible pour que la
        # fenêtre entière tienne sur un écran 1366x768 réel (barre de
        # titre/tâches comprises) -- un `setMinimumHeight` généreux ne
        # suffit pas si le contenu réel dépasse déjà l'écran (bug constaté :
        # la fenêtre s'ouvrait plus haute que l'écran, coupant la dernière
        # rangée), le vrai correctif est ici, pas seulement dans
        # `main_window.py`.
        root.setContentsMargins(24, 10, 24, 10)

        # En-tête (§5, refonte menu de tuiles -- manquait entièrement) :
        # nom de l'application en lettres espacées, couleur d'accent, un
        # sous-titre d'orientation en dessous ; bouton Mode expert aligné
        # sur la ligne du titre, à droite. Construit dans un conteneur de
        # largeur fixe (`_ASSISTED_CENTERED_BLOCK_WIDTH`, §5, correctif de
        # centrage) plutôt que directement sur `root` -- sans ce
        # conteneur, cette ligne s'étirerait sur toute la largeur de la
        # fenêtre (bords collés aux marges) pendant que la grille en
        # dessous se centre indépendamment, décalant visuellement le
        # titre par rapport aux tuiles qu'il surplombe.
        header_container = QWidget()
        header_container.setFixedWidth(_ASSISTED_CENTERED_BLOCK_WIDTH)
        header_row = QHBoxLayout(header_container)
        header_row.setContentsMargins(0, 0, 0, 0)
        brand_col = QVBoxLayout()
        brand_col.setSpacing(2)
        brand_title = QLabel(tr("app_title").upper())
        brand_title.setProperty("role", "brandTitle")
        # Qt Style Sheets ne supporte pas `letter-spacing` (contrairement
        # à CSS) -- posé sur la police directement, seule façon d'obtenir
        # l'espacement demandé.
        brand_font = brand_title.font()
        brand_font.setLetterSpacing(QFont.AbsoluteSpacing, 2)
        brand_title.setFont(brand_font)
        brand_col.addWidget(brand_title)
        brand_subtitle = QLabel(tr("assisted_brand_subtitle"))
        brand_subtitle.setProperty("role", "secondary")
        brand_col.addWidget(brand_subtitle)
        header_row.addLayout(brand_col)
        header_row.addStretch()
        self._expert_button = QPushButton(tr("assisted_expert_mode_button"))
        self._expert_button.setProperty("role", "flat")
        self._expert_button.clicked.connect(self.expert_mode_requested.emit)
        # Sélecteur de langue sous le bouton Mode expert, dans la même
        # colonne de droite : l'en-tête garde sa largeur fixe.
        header_actions = QVBoxLayout()
        header_actions.setSpacing(4)
        header_actions.addWidget(self._expert_button, 0, Qt.AlignRight)
        self._language_selector = LanguageSelector()
        self._language_selector.language_selected.connect(self.language_selected.emit)
        header_actions.addWidget(self._language_selector, 0, Qt.AlignRight)
        self.update_controls = UpdateControls()
        header_actions.addWidget(self.update_controls, 0, Qt.AlignRight)
        header_row.addLayout(header_actions)
        root.addLayout(_centered_row(header_container))

        root.addSpacing(8)

        # Étiquette de section, en lettres espacées (maquette de référence,
        # docs/screenshots/maquette-accueil.png) -- manquait entièrement.
        # Même conteneur de largeur fixe centré que l'en-tête ci-dessus
        # (§5, correctif de centrage) -- son bord gauche doit tomber au
        # même endroit que celui de la grille juste en dessous, dont elle
        # introduit visuellement la section.
        section_container = QWidget()
        section_container.setFixedWidth(_ASSISTED_CENTERED_BLOCK_WIDTH)
        section_row = QHBoxLayout(section_container)
        section_row.setContentsMargins(0, 0, 0, 0)
        section_label = QLabel(tr("assisted_section_label"))
        section_label.setProperty("role", "sectionLabel")
        section_font = section_label.font()
        section_font.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        section_label.setFont(section_font)
        section_row.addWidget(section_label)
        section_row.addStretch()
        root.addLayout(_centered_row(section_container))
        root.addSpacing(8)

        content_row = QHBoxLayout()
        content_row.setSpacing(_ASSISTED_CONTENT_SPACING)

        grid_widget = QWidget()
        grid_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(Tile.SPACING)
        # Aucune ligne ni colonne extensible (§5, deuxième correctif de
        # taille) -- déjà le comportement par défaut de `QGridLayout`
        # (facteur 0 tant que rien ne l'augmente), posé explicitement ici
        # pour qu'aucun ajout futur de widget dans cette grille ne puisse
        # silencieusement en étirer une ligne ou une colonne.
        for row in range(_ASSISTED_GRID_ROWS):
            grid.setRowStretch(row, 0)
        for column in range(_ASSISTED_TILE_GRID_COLUMNS):
            grid.setColumnStretch(column, 0)
        self._tiles_by_status_key: Dict[str, Tile] = {}
        self._all_tiles: List[Tile] = []

        # Tuile 1, seule à porter icône/libellé agrandis et une
        # description (§5, correctif visuel) -- construite à part plutôt
        # que par une entrée de plus dans `_ASSISTED_TILE_SPECS`, dont les
        # champs ne varient sinon jamais d'une tuile à l'autre.
        tile1 = Tile(
            "prepare",
            tr("assisted_tile_prepare"),
            role="tileEmphasized",
            icon_color=theme.BG_DARK,
            icon_size=60,
            label_role="tileLabelLarge",
            # Une seule ligne réservée, pas les 3 par défaut (§5, deuxième
            # correctif de taille) : contrairement aux 8 autres tuiles,
            # celle-ci a un texte de titre fixe et toujours court
            # ("Préparer ma carte") -- réserver 3 lignes ici gaspillerait
            # de la place au détriment de la description en dessous, sans
            # jamais servir (rien ne rallonge ce texte précis).
            label_lines=1,
            description=tr("assisted_tile_prepare_desc"),
            width=Tile.SIZE * 2 + Tile.SPACING,
        )
        tile1.clicked.connect(self.prepare_requested.emit)
        grid.addWidget(tile1, 0, 0, 1, 2)
        self._all_tiles.append(tile1)

        row_index = 0
        col_index = 2
        for glyph, label_key, role, signal_name, status_key, span in _ASSISTED_TILE_SPECS:
            icon_color = getattr(theme, _ICON_COLOR_BY_ROLE.get(role, "ACCENT_CYAN"))
            tile = Tile(glyph, tr(label_key), role=role, icon_color=icon_color)
            tile.clicked.connect(getattr(self, signal_name).emit)
            grid.addWidget(tile, row_index, col_index, 1, span)
            if status_key is not None:
                self._tiles_by_status_key[status_key] = tile
            self._all_tiles.append(tile)
            col_index += span
            if col_index >= _ASSISTED_TILE_GRID_COLUMNS:
                col_index = 0
                row_index += 1


        # Zone de la grille dans un `QScrollArea` (§5, correctif visuel) :
        # la dernière rangée sortait de la fenêtre quand celle-ci n'était
        # pas assez haute. `MainWindow` fixe une taille initiale assez
        # grande pour afficher les trois rangées sans défiler
        # (`main_window.py`, dérivée de `_ASSISTED_GRID_TOTAL_HEIGHT`/
        # `_ASSISTED_GRID_TOTAL_WIDTH`) -- ce `QScrollArea` reste un filet
        # de sécurité pour le cas où l'utilisateur redimensionne plus
        # petit, pas le chemin normal. `setWidgetResizable(False)` (le
        # défaut) : `grid_widget` garde sa taille naturelle fixe, jamais
        # étiré par la zone de défilement.
        #
        # Bug corrigé (correctif visuel, deuxième passe) : `QScrollArea`
        # a par défaut une `sizePolicy` `Expanding`/`Expanding` -- même
        # avec `grid_widget` fixe à l'intérieur et un facteur d'étirement
        # nul dans `content_row.addWidget`, ce `QScrollArea` pouvait donc
        # quand même se voir attribuer une partie de l'espace horizontal
        # (et vertical) disponible en trop dans `content_row`, ouvrant un
        # vide entre la grille visible et le panneau -- fixée explicitement
        # à `Fixed`/`Fixed` (sur sa propre taille naturelle, égale à celle
        # de `grid_widget`) pour ne plus jamais concourir pour l'espace en
        # trop : seul le `addStretch()` final de `content_row` doit
        # l'absorber (§5, correctif visuel, point 2).
        grid_scroll = QScrollArea()
        grid_scroll.setFrameShape(QFrame.NoFrame)
        grid_scroll.setWidget(grid_widget)
        grid_scroll.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        grid_scroll.setFixedSize(_ASSISTED_GRID_TOTAL_WIDTH, _ASSISTED_GRID_TOTAL_HEIGHT)
        # `addStretch(1)` AVANT la grille (§5, correctif de centrage) --
        # avec celui de même facteur après le panneau plus bas, le vide
        # restant de la fenêtre se répartit également des deux côtés du
        # bloc grille+panneau plutôt que de se concentrer entièrement à
        # droite. Grille et panneau gardent leur largeur fixe -- rien
        # dans ce bloc ne s'étire jamais, seuls les deux vides de part et
        # d'autre grandissent ou rétrécissent.
        content_row.addStretch(1)
        content_row.addWidget(grid_scroll, 0, Qt.AlignTop)
        self._grid_scroll = grid_scroll  # exposé pour les tests (taille fixe, jamais étirée)

        # Panneau « Carte détectée » (§5, refonte menu de tuiles) : même
        # icône/textes que le bandeau de `HomeScreen` (agrandie ici), en
        # panneau vertical plutôt qu'en ligne horizontale -- code dédié
        # plutôt qu'une fonction partagée avec `HomeScreen._banner`
        # (orientations trop différentes pour un partage simple sans
        # complexifier les deux). Largeur fixée à 308 (§5, correctif
        # visuel, point 2) ; hauteur fixée à celle de la grille entière
        # (§5, correctif visuel, point 5 : « du haut de la première rangée
        # au bas de la dernière ») -- calculée une fois pour toutes
        # (`_ASSISTED_GRID_TOTAL_HEIGHT`) plutôt que déduite d'un widget
        # dans un `QScrollArea`, dont le `sizeHint` ne reflète pas
        # fidèlement un contenu défilable.
        panel = QFrame()
        panel.setProperty("role", "banner")
        panel.setFixedWidth(_ASSISTED_PANEL_WIDTH)
        panel.setFixedHeight(_ASSISTED_GRID_TOTAL_HEIGHT)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 14, 14, 14)
        panel_layout.setSpacing(10)
        # `addStretch(1)` avant le premier élément (§5, correctif de
        # centrage, point 3) -- avec celui de même facteur après le
        # bouton Rafraîchir plus bas, tout le contenu (icône, modèle,
        # état, bouton) se centre verticalement dans le panneau plutôt
        # que de rester tassé en haut avec le vide entier en dessous.
        panel_layout.addStretch(1)
        panel_layout.addWidget(_ConsoleIcon(size=_ASSISTED_PANEL_ICON_SIZE), 0, Qt.AlignHCenter)
        self._panel_device_label = QLabel()
        self._panel_device_label.setProperty("role", "rowTitle")
        self._panel_device_label.setWordWrap(True)
        self._panel_device_label.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(self._panel_device_label)
        # État sous forme de pastille (`role="badge"`), pas du texte nu
        # (§5, correctif visuel) -- même mécanique que `Tile.set_badge`.
        self._panel_state_badge = QLabel("")
        self._panel_state_badge.setProperty("role", "badge")
        self._panel_state_badge.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(self._panel_state_badge, 0, Qt.AlignHCenter)
        self._refresh_button = QPushButton(tr("home_refresh"))
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        panel_layout.addWidget(self._refresh_button)
        panel_layout.addStretch(1)
        content_row.addWidget(panel, 0, Qt.AlignTop)
        self._panel = panel  # exposé pour les tests (largeur/hauteur fixes)

        # `addStretch(1)` après le panneau, même facteur que celui avant
        # la grille plus haut (§5, correctif de centrage) -- le vide
        # restant se répartit également des deux côtés plutôt que de se
        # concentrer entièrement ici.
        content_row.addStretch(1)
        root.addLayout(content_row)
        root.addStretch()  # respire en bas

    def set_busy(self, busy: bool) -> None:
        """Désactive toutes les tuiles (9, ou 10 avec la tuile personnelle
        « Web » quand elle est visible) et le bouton Mode expert pendant
        qu'une opération est en cours (§5, refonte menu de tuiles) --
        même garde que `HomeScreen.set_busy` : changer de mode ou lancer
        une deuxième action en plein flash/copie laisserait un job
        orphelin. Signature/sémantique inchangées par rapport à l'écran
        précédent -- tous les appels existants `self._assisted_landing.
        set_busy(...)` dans `main_window.py` continuent de fonctionner
        sans modification."""
        for tile in self._all_tiles:
            tile.setEnabled(not busy)
        self._expert_button.setEnabled(not busy)

    def set_language(self, code: str) -> None:
        """Miroir de `HomeScreen.set_language`."""
        self._language_selector.set_language(code)

    def set_status(
        self,
        status: Dict[str, StepStatus],
        device: Optional[Device] = None,
        has_device: Optional[bool] = None,
        card_system: Optional[CardSystem] = None,
    ) -> None:
        """Miroir de `HomeScreen.set_status` (§5) : pousse le badge sur
        chaque tuile qui en affiche un (`identify`/`flash`/`copy_games`/
        `eject` -- les cinq autres tuiles, dont « Chercher les doublons »
        depuis qu'elle ouvre un outil autonome sans rapport avec la carte
        détectée, n'ont structurellement pas d'entrée dans
        `_tiles_by_status_key`, jamais de badge) et met à jour le panneau
        de détection. `has_device`
        accepté pour la même signature que `HomeScreen.set_status`
        (l'appelant, `_refresh_home_state`, pousse le même résultat aux
        deux écrans) mais sans effet ici -- contrairement aux lignes
        « Par sécurité » du mode expert, aucune tuile n'est désactivée par
        l'absence de carte : les neuf restent cliquables par principe
        (§4.5), `_start_flow` guide déjà sans carte branchée."""
        for key, tile in self._tiles_by_status_key.items():
            tile.set_badge(status.get(key), card_system)
        self._update_panel(status, device, card_system)

    def _update_panel(
        self, status: Dict[str, StepStatus], device: Optional[Device], card_system: Optional[CardSystem] = None
    ) -> None:
        if device is None:
            self._panel_device_label.setText(tr("home_banner_state_none"))
            self._panel_state_badge.setText("")
            self._panel_state_badge.setProperty("badgeKind", None)
            theme.repolish(self._panel_state_badge)
            return
        size_go = _capacity_go(device.size_bytes)
        self._panel_device_label.setText(tr("home_banner_line_device", display=device.display, size_go=size_go))
        is_arkos = status.get("flash") == StepStatus.DONE
        self._panel_state_badge.setText(_banner_state_text(is_arkos, card_system))
        self._panel_state_badge.setProperty("badgeKind", "done" if is_arkos else "neutral")
        theme.repolish(self._panel_state_badge)


class AboutDialog(Dialog):
    """« À propos », tuile Aide de l'accueil assisté sur Windows/Linux
    (§5, refonte menu de tuiles) -- macOS ouvre `HelpDialog` (Accès
    complet au disque) à la place, contenu sans rapport avec ces deux OS.
    Minimaliste : numéro de version (`build_info.version_label()`, déjà
    prêt à l'emploi mais jamais affiché dans une fenêtre jusqu'ici) + un
    court paragraphe d'orientation statique, un seul bouton Fermer --
    même structure que `HelpDialog` sans son bouton « Ouvrir les
    réglages », qui n'a pas d'équivalent ici."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("about_title"))
        layout = QVBoxLayout(self)

        title = QLabel(tr("about_title"))
        title.setProperty("role", "title")
        layout.addWidget(title)

        self._version_label = QLabel(build_info.version_label())
        self._version_label.setProperty("role", "secondary")
        layout.addWidget(self._version_label)

        body = QLabel(tr("about_orientation"))
        body.setWordWrap(True)
        layout.addWidget(body)
        licence = QLabel(tr("about_licence"))
        licence.setProperty("role", "secondary")
        licence.setWordWrap(True)
        layout.addWidget(licence)
        layout.addStretch()

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_button = QPushButton(tr("about_close"))
        close_button.setProperty("role", "primary")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.resize(420, 280)


_IDENTIFY_FAILURE_MESSAGE_KEYS = {
    IdentifyFailureReason.MOUNT_FAILED: "identify_failed_mount_failed",
    IdentifyFailureReason.NO_DTB_FOUND: "identify_failed_no_dtb_found",
    IdentifyFailureReason.ALL_DTB_INVALID: "identify_failed_all_dtb_invalid",
    IdentifyFailureReason.ACCESS_DENIED: "identify_failed_access_denied",
    IdentifyFailureReason.ELEVATION_REFUSED: "identify_failed_elevation_refused",
}


class IdentifyResultDialog(Dialog):
    """Résultat de la tuile « Identifier ma console » (§5, refonte menu de
    tuiles -- fusion de « Rechercher ma console » et « Consoles diverses »
    en une seule tuile) : affiche l'identifiant brut du `.dtb`
    (`result.info.board_compatible`, jamais un nom convivial inventé --
    convention déjà suivie ailleurs dans ce projet, §4.6) et un
    avertissement si la carte est un clone (`result.is_clone`), ou le
    message correspondant à `result.failure_reason` en cas d'échec (3 cas,
    `identify/__init__.py::IdentifyFailureReason`) ; propose en dessous
    l'accès au catalogue (`catalog_requested`, `main_window.py` route vers
    `ConsolesDiversesScreen`, déjà existant) -- toujours affiché, succès ou
    échec de l'identification : le catalogue reste utile même sans
    identification DTB réussie (recherche manuelle par nom, par exemple)."""

    catalog_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("identify_result_title"))
        layout = QVBoxLayout(self)

        title = QLabel(tr("identify_result_title"))
        title.setProperty("role", "title")
        layout.addWidget(title)

        self._message = QLabel()
        self._message.setWordWrap(True)
        layout.addWidget(self._message)

        # Même pattern que `consoles_diverses/screen.py::
        # _build_warning_banner` -- encadré orange (`role="warning"`),
        # signal de prudence plutôt que de danger.
        self._clone_warning_frame = QFrame()
        self._clone_warning_frame.setProperty("role", "warning")
        clone_warning_layout = QVBoxLayout(self._clone_warning_frame)
        clone_warning_label = QLabel(tr("identify_result_clone_warning"))
        clone_warning_label.setWordWrap(True)
        clone_warning_label.setProperty("role", "dangerTitle")
        clone_warning_layout.addWidget(clone_warning_label)
        self._clone_warning_frame.setVisible(False)
        layout.addWidget(self._clone_warning_frame)

        layout.addStretch()

        catalog_button = QPushButton(tr("identify_result_catalog_button"))
        catalog_button.setProperty("role", "link")
        catalog_button.clicked.connect(self._on_catalog_clicked)
        layout.addWidget(catalog_button)

        buttons = QHBoxLayout()
        buttons.addStretch()
        close_button = QPushButton(tr("about_close"))
        close_button.setProperty("role", "primary")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

        self.resize(440, 320)

    def set_result(self, result: IdentifyResult) -> None:
        if result.ok:
            self._message.setText(tr("identify_result_board", board=result.info.board_compatible))
        else:
            key = _IDENTIFY_FAILURE_MESSAGE_KEYS.get(result.failure_reason, "identify_failed_mount_failed")
            self._message.setText(tr(key))
        self._clone_warning_frame.setVisible(result.is_clone)

    def _on_catalog_clicked(self) -> None:
        self.close()
        self.catalog_requested.emit()


# --- Outil « Console Android » (android/, étape 1, docs/android-adb.md)
# -- écran dédié, écran/chaînes câblés « comme le reste » plutôt qu'isolés
# dans un package séparé comme consoles_diverses/ (dont la règle
# d'isolation ne s'applique qu'à ce package-là). Jamais d'écriture disque,
# jamais d'élévation de privilèges : adb en lecture seule uniquement. ----

# État -> (titre, texte d'aide) affichés dans la carte de statut quand
# aucun appareil exploitable n'est détecté (§ Détection/Interface du
# brief). `adb_missing` n'y figure pas : ce cas ouvre l'écran de
# consentement au téléchargement (`show_need_consent`), jamais cette carte.
_ANDROID_STATE_HELP_KEYS = {
    "no_device": ("android_state_no_device_title", "android_state_no_device_help"),
    "unauthorized": ("android_state_unauthorized_title", "android_state_unauthorized_help"),
    "multiple_devices": ("android_state_multiple_title", "android_state_multiple_help"),
    "adb_error": ("android_state_adb_error_title", "android_state_adb_error_help"),
}

# Les cinq propriétés de `android.models.AndroidDeviceInfo` (§ Détection du
# brief), dans l'ordre d'affichage de la carte « Console détectée ».
_ANDROID_DEVICE_FIELDS = [
    ("android_device_label_manufacturer", "manufacturer"),
    ("android_device_label_model", "model"),
    ("android_device_label_product_name", "product_name"),
    ("android_device_label_android_version", "android_version"),
    ("android_device_label_abi", "abi"),
]


def _android_plain_label(text: str, role: Optional[str] = None, wrap: bool = False) -> QLabel:
    """`QLabel` verrouillée sur `PlainText` -- une donnée d'appareil (dump
    `getprop`) ou de serveur (fiche catalogue) n'est jamais interprétée
    comme du HTML, même garantie que `consoles_diverses/screen.py::
    _plain_label` (fonction privée à ce module-là, § règle d'isolation --
    non réutilisée directement, même contrat réécrit ici)."""
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    if role:
        label.setProperty("role", role)
    if wrap:
        label.setWordWrap(True)
    return label


def _android_is_safe_external_url(url: Optional[str]) -> bool:
    """Un lien n'est cliquable que s'il s'agit explicitement d'une URL
    http(s) -- même garde que `consoles_diverses/screen.py::
    _est_url_externe_sure`, appliquée ici à `android/data/emulateurs.json`
    (un fichier du dépôt, donc a priori sûr, mais cette garde ne coûte
    rien et évite qu'une future entrée mal formée n'ouvre un schéma
    inattendu, ex. `file:`)."""
    if not url:
        return False
    try:
        scheme = urlsplit(url).scheme.lower()
    except ValueError:
        return False
    return scheme in ("http", "https")


def _android_link_button(url: str, label: str) -> QWidget:
    if not _android_is_safe_external_url(url):
        return _android_plain_label(url, role="secondary", wrap=True)
    button = QPushButton(label)
    button.setProperty("role", "link")
    button.setCursor(Qt.PointingHandCursor)
    button.setToolTip(url)
    button.clicked.connect(lambda checked=False, u=url: QDesktopServices.openUrl(QUrl(u)))
    return button


def _android_badge(text: str, badge_kind: str = "neutral") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.PlainText)
    label.setProperty("role", "badge")
    label.setProperty("badgeKind", badge_kind)
    return label


def _android_clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.deleteLater()


# Statut du projet (android/emulators.py::STATUT_PROJET_VALUES, demandé
# explicitement) -- même réutilisation des couleurs de badge déjà établie
# pour le statut d'un firmware du catalogue (`identify/firmware_catalog.py`,
# maintenu/archivé/expérimental) : même trio vert/gris-bleu/orange, même
# incertitude "à vérifier" traitée comme "expérimental" (orange, prudence).
_ANDROID_STATUS_BADGE_KIND = {
    "actif": "maintained",
    "abandonne": "archived",
    "a_verifier": "experimental",
}
_ANDROID_STATUS_LABEL_KEY = {
    "actif": "android_emulator_status_actif",
    "abandonne": "android_emulator_status_abandonne",
    "a_verifier": "android_emulator_status_a_verifier",
}


def _android_build_emulator_row(
    entry: EmulatorEntry, checked: bool, on_toggle: Callable[[str, bool], None]
) -> Tuple[QWidget, QCheckBox]:
    """Une carte par émulateur du catalogue local (`android/data/
    emulateurs.json`) -- licence/prix affichés « à vérifier » tant que
    l'entrée porte `SENTINEL_A_VERIFIER` (demandé explicitement : jamais
    "gratuit"/"payant" affirmé sans vérification humaine sur la page
    officielle du projet, § avertissement permanent de la liste).

    Retourne aussi la case à cocher (jamais reconstruite ailleurs) pour
    que l'appelant (`AndroidScreen._render_visible_emulator_cards`) puisse
    la piloter directement depuis « Tout cocher »/« Tout décocher », même
    principe que `DoublonsResultsScreen._all_checkboxes`."""
    frame = QFrame()
    frame.setProperty("role", "row")
    layout = QVBoxLayout(frame)

    header_row = QHBoxLayout()
    checkbox = QCheckBox()
    checkbox.setChecked(checked)
    checkbox.toggled.connect(lambda value, entry_id=entry.id: on_toggle(entry_id, value))
    header_row.addWidget(checkbox)
    header_row.addWidget(_android_plain_label(entry.nom, role="rowTitle"), 1)
    layout.addLayout(header_row)

    if entry.systemes_emules:
        layout.addWidget(_android_plain_label(", ".join(entry.systemes_emules), role="rowDesc", wrap=True))

    badges_row = QHBoxLayout()
    status_kind = _ANDROID_STATUS_BADGE_KIND.get(entry.statut_projet, "neutral")
    status_label_key = _ANDROID_STATUS_LABEL_KEY.get(entry.statut_projet, "android_emulator_status_a_verifier")
    badges_row.addWidget(_android_badge(tr(status_label_key), status_kind))
    licence_text = tr("android_emulator_licence_a_verifier") if entry.licence == SENTINEL_A_VERIFIER else entry.licence
    badges_row.addWidget(_android_badge(licence_text))
    prix_text = tr("android_emulator_prix_a_verifier") if entry.prix == SENTINEL_A_VERIFIER else entry.prix
    badges_row.addWidget(_android_badge(prix_text))
    badges_row.addStretch()
    layout.addLayout(badges_row)

    links_row = QHBoxLayout()
    layout.addLayout(links_row)
    # Exposé pour les tests uniquement -- `QWidget.deleteLater()` (via
    # `_android_clear_layout` ci-dessous) diffère la destruction réelle
    # des anciens boutons à l'itération suivante de la boucle d'événements
    # Qt, donc `frame.findChildren(QPushButton)` resterait trompeur juste
    # après un changement de variante sans faire tourner cette boucle ;
    # lire `links_row` directement reflète toujours l'état réel et
    # immédiat de la mise en page, indépendamment de ce délai.
    frame._links_row = links_row

    def _show_links(url_officielle: str, source_url: str) -> None:
        _android_clear_layout(links_row)
        links_row.addWidget(_android_link_button(url_officielle, tr("android_emulator_official_link")))
        links_row.addWidget(_android_link_button(source_url, tr("android_emulator_source_link")))
        links_row.addStretch()

    if entry.variantes:
        # Menu déroulant (demandé explicitement) -- remplace les deux
        # boutons de lien de base par ceux de la variante choisie, jamais
        # les deux affichés à la fois (une seule paire de liens visible,
        # toujours cohérente avec la variante sélectionnée).
        variant_row = QHBoxLayout()
        variant_row.addWidget(_android_plain_label(tr("android_emulator_variant_label"), role="secondary"))
        variant_combo = QComboBox()
        for variant in entry.variantes:
            variant_combo.addItem(variant.nom)
        variant_row.addWidget(variant_combo, 1)
        layout.addLayout(variant_row)

        def _on_variant_changed(index: int, variants=entry.variantes) -> None:
            if 0 <= index < len(variants):
                _show_links(variants[index].url_officielle, variants[index].source_url)

        variant_combo.currentIndexChanged.connect(_on_variant_changed)
        _show_links(entry.variantes[0].url_officielle, entry.variantes[0].source_url)
    else:
        _show_links(entry.url_officielle, entry.source_url)

    return frame, checkbox


class AndroidScreen(Screen):
    """Écran de l'outil « Console Android » (étape 1, docs/android-adb.md)
    -- détection d'une console Android en USB via adb (lecture seule),
    fiche catalogue (réutilisation explicitement demandée du client
    `consoles_diverses`, jamais de modification de ce package), liste
    d'émulateurs recommandés. Chaque état est piloté par `main_window.py`
    via les méthodes publiques ci-dessous -- cet écran ne connaît ni adb
    ni le réseau, uniquement des signaux et des setters, même principe que
    le reste de ce fichier (§5 du CLAUDE.md racine)."""

    back_requested = Signal()
    refresh_requested = Signal()
    consent_download_requested = Signal()
    cancel_download_requested = Signal()
    search_catalog_requested = Signal(str)  # référence (modèle lu par getprop)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_model = ""
        # Filtrage de la liste d'émulateurs par appareil détecté (signalé :
        # « la liste d'émulateurs est identique quelle que soit la console »)
        # -- catalogue complet mémorisé une fois (`set_emulator_catalog`),
        # appareil courant mémorisé à chaque détection (`_populate_device`),
        # `_render_emulator_list` recombine les deux à chaque changement de
        # l'un ou l'autre.
        self._emulator_catalog: Optional[EmulatorCatalog] = None
        self._current_device: Optional[AndroidDeviceInfo] = None
        # Sous-ensemble déjà filtré par appareil (ci-dessus), avant tout
        # filtrage par catégorie -- sert de base au classement par console
        # émulée (colonne de gauche) et au compteur global "cochés"
        # (demandés explicitement).
        self._device_filtered_emulateurs: List[EmulatorEntry] = []
        # `None` == pseudo-catégorie "Toutes" (§ classement par console).
        self._selected_category: Optional[str] = None
        # État de sélection global (id d'émulateur -> coché), indépendant
        # de la catégorie actuellement affichée -- une case cochée dans
        # une catégorie reste cochée en changeant de catégorie.
        self._checked_emulator_ids: set = set()
        # Cases à cocher actuellement affichées (id -> widget), jamais
        # reconstruites pour « Tout cocher »/« Tout décocher » -- même
        # principe que `DoublonsResultsScreen._all_checkboxes`.
        self._visible_checkboxes: Dict[str, QCheckBox] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 24)

        header = QHBoxLayout()
        back_button = QPushButton(tr("android_back_button"))
        back_button.setProperty("role", "flat")
        back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(back_button)
        title = QLabel(tr("android_screen_title"))
        title.setProperty("role", "title")
        header.addWidget(title)
        header.addStretch()
        self._refresh_button = QPushButton(tr("android_refresh_button"))
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        header.addWidget(self._refresh_button)
        root.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(12)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # --- Consentement au téléchargement d'adb (brief § adb) --------
        self._consent_frame = QFrame()
        self._consent_frame.setProperty("role", "row")
        consent_layout = QVBoxLayout(self._consent_frame)
        consent_layout.addWidget(_android_plain_label(tr("android_consent_title"), role="rowTitle"))
        consent_layout.addWidget(_android_plain_label(tr("android_consent_body"), role="rowDesc", wrap=True))
        self._consent_url_label = _android_plain_label("", role="secondary", wrap=True)
        consent_layout.addWidget(self._consent_url_label)
        self._consent_size_label = _android_plain_label("", role="secondary")
        consent_layout.addWidget(self._consent_size_label)
        self._consent_download_button = QPushButton(tr("android_consent_download_button"))
        self._consent_download_button.setProperty("role", "primary")
        self._consent_download_button.clicked.connect(self.consent_download_requested.emit)
        consent_layout.addWidget(self._consent_download_button, alignment=Qt.AlignLeft)
        self._download_status_label = _android_plain_label(tr("android_downloading_status"), role="secondary")
        self._download_status_label.setVisible(False)
        consent_layout.addWidget(self._download_status_label)
        self._download_bar = QProgressBar()
        self._download_bar.setRange(0, 100)
        self._download_bar.setVisible(False)
        consent_layout.addWidget(self._download_bar)
        self._download_cancel_button = QPushButton(tr("android_download_cancel_button"))
        self._download_cancel_button.setVisible(False)
        self._download_cancel_button.clicked.connect(self.cancel_download_requested.emit)
        consent_layout.addWidget(self._download_cancel_button, alignment=Qt.AlignLeft)
        self._download_error_label = _android_plain_label("", role="warning", wrap=True)
        self._download_error_label.setVisible(False)
        consent_layout.addWidget(self._download_error_label)
        content_layout.addWidget(self._consent_frame)

        # --- Détection en cours / états informatifs (aucun appareil,
        # non autorisé, plusieurs appareils, erreur adb) -----------------
        self._status_frame = QFrame()
        self._status_frame.setProperty("role", "row")
        status_layout = QVBoxLayout(self._status_frame)
        self._status_title_label = _android_plain_label("", role="rowTitle")
        status_layout.addWidget(self._status_title_label)
        self._status_help_label = _android_plain_label("", role="rowDesc", wrap=True)
        status_layout.addWidget(self._status_help_label)
        # Sortie adb en texte brut (brief § Interface : "Textes serveur et
        # sortie adb affichés en texte brut") -- `role="log"` déjà utilisé
        # par `LogPanel` (police monospace, fond sombre, texte vert clair).
        self._status_raw_output = QPlainTextEdit()
        self._status_raw_output.setProperty("role", "log")
        self._status_raw_output.setReadOnly(True)
        self._status_raw_output.setMaximumHeight(120)
        self._status_raw_output.setVisible(False)
        status_layout.addWidget(self._status_raw_output)
        content_layout.addWidget(self._status_frame)

        # --- Console détectée --------------------------------------------
        self._device_frame = QFrame()
        self._device_frame.setProperty("role", "row")
        device_layout = QVBoxLayout(self._device_frame)
        device_layout.addWidget(_android_plain_label(tr("android_device_card_title"), role="title"))
        device_grid = QGridLayout()
        device_grid.setColumnStretch(1, 1)
        self._device_value_labels: Dict[str, QLabel] = {}
        for row_index, (label_key, field_name) in enumerate(_ANDROID_DEVICE_FIELDS):
            device_grid.addWidget(_android_plain_label(tr(label_key), role="secondary"), row_index, 0)
            value_label = _android_plain_label("", wrap=True)
            device_grid.addWidget(value_label, row_index, 1)
            self._device_value_labels[field_name] = value_label
        device_layout.addLayout(device_grid)
        content_layout.addWidget(self._device_frame)

        # --- Catalogue (réutilise `consoles_diverses.client`, demandé
        # explicitement par le brief -- jamais de recherche automatique,
        # cohérent avec le reste du projet : `consoles_diverses/screen.py`
        # exige elle aussi un clic explicite avant tout appel réseau) ----
        self._catalog_frame = QFrame()
        self._catalog_frame.setProperty("role", "row")
        catalog_layout = QVBoxLayout(self._catalog_frame)
        self._catalog_search_button = QPushButton(tr("android_catalog_search_button"))
        self._catalog_search_button.clicked.connect(self._on_search_catalog_clicked)
        catalog_layout.addWidget(self._catalog_search_button, alignment=Qt.AlignLeft)
        self._catalog_status_label = _android_plain_label("", role="secondary", wrap=True)
        self._catalog_status_label.setVisible(False)
        catalog_layout.addWidget(self._catalog_status_label)
        self._catalog_result_layout = QVBoxLayout()
        catalog_layout.addLayout(self._catalog_result_layout)
        content_layout.addWidget(self._catalog_frame)

        # --- Émulateurs recommandés (`android/data/emulateurs.json`) ---
        self._emulators_frame = QFrame()
        self._emulators_frame.setProperty("role", "row")
        emulators_layout = QVBoxLayout(self._emulators_frame)
        emulators_layout.addWidget(_android_plain_label(tr("android_emulators_title"), role="title"))
        self._emulators_warning_label = _android_plain_label("", role="warning", wrap=True)
        self._emulators_warning_label.setVisible(False)
        emulators_layout.addWidget(self._emulators_warning_label)
        # Mention « liste générique » (signalé : liste identique quelle que
        # soit la console) -- distincte de l'avertissement ci-dessus (qui
        # porte sur la fiabilité des données, pas sur le filtrage).
        self._emulators_generic_label = _android_plain_label(
            tr("android_emulators_generic_notice"), role="secondary", wrap=True
        )
        self._emulators_generic_label.setVisible(False)
        emulators_layout.addWidget(self._emulators_generic_label)

        # Classement par console émulée (demandé explicitement, inspiré
        # d'un logiciel concurrent) -- colonne de gauche (catégories +
        # nombre d'émulateurs par catégorie), liste filtrée à droite.
        emulators_content_row = QHBoxLayout()
        self._category_list = QListWidget()
        self._category_list.setSelectionMode(QListWidget.SingleSelection)
        # Largeur fixe, raisonnable pour les libellés les plus longs
        # ("GameCube / Wii (1)") -- pas de constante partagée ailleurs
        # dans ce fichier pour ce cas précis, une valeur simple suffit.
        self._category_list.setFixedWidth(170)
        self._category_list.currentItemChanged.connect(self._on_category_row_changed)
        emulators_content_row.addWidget(self._category_list)

        emulators_right_column = QVBoxLayout()
        selection_toolbar = QHBoxLayout()
        self._check_all_button = QPushButton(tr("android_check_all_button"))
        self._check_all_button.clicked.connect(self._on_check_all_clicked)
        selection_toolbar.addWidget(self._check_all_button)
        self._uncheck_all_button = QPushButton(tr("android_uncheck_all_button"))
        self._uncheck_all_button.clicked.connect(self._on_uncheck_all_clicked)
        selection_toolbar.addWidget(self._uncheck_all_button)
        selection_toolbar.addStretch()
        self._checked_counter_label = _android_plain_label("", role="secondary")
        selection_toolbar.addWidget(self._checked_counter_label)
        emulators_right_column.addLayout(selection_toolbar)

        self._emulators_list_layout = QVBoxLayout()
        emulators_right_column.addLayout(self._emulators_list_layout)
        emulators_content_row.addLayout(emulators_right_column, 1)

        emulators_layout.addLayout(emulators_content_row)
        content_layout.addWidget(self._emulators_frame)

        content_layout.addStretch()

        self._show_zone("detecting")
        self._status_title_label.setText(tr("android_detecting_status"))

    # --- Zones --------------------------------------------------------

    def _show_zone(self, zone: str) -> None:
        self._consent_frame.setVisible(zone == "consent")
        self._status_frame.setVisible(zone in ("detecting", "status"))
        self._device_frame.setVisible(zone == "ready")
        self._catalog_frame.setVisible(zone == "ready")
        self._emulators_frame.setVisible(zone == "ready")

    # --- Consentement / téléchargement d'adb ---------------------------

    def show_need_consent(self, url: str) -> None:
        self._show_zone("consent")
        self._consent_url_label.setText(tr("android_consent_url_label", url=url))
        self._consent_size_label.setText(tr("android_consent_size_unknown"))
        self._set_consent_downloading(False)
        self._download_error_label.setVisible(False)

    def set_platform_tools_size(self, size_bytes: Optional[int]) -> None:
        if size_bytes is None:
            self._consent_size_label.setText(tr("android_consent_size_unknown"))
        else:
            self._consent_size_label.setText(tr("android_consent_size_label", size=_format_size(size_bytes)))

    def _set_consent_downloading(self, downloading: bool) -> None:
        self._consent_download_button.setVisible(not downloading)
        self._download_status_label.setVisible(downloading)
        self._download_bar.setVisible(downloading)
        self._download_cancel_button.setVisible(downloading)

    def show_downloading(self) -> None:
        self._show_zone("consent")
        self._download_error_label.setVisible(False)
        self._set_consent_downloading(True)
        self._download_bar.setRange(0, 0)  # indéterminé tant qu'aucun octet n'est encore arrivé

    def set_download_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._download_bar.setRange(0, 100)
            self._download_bar.setValue(int(done * 100 / total))
        else:
            self._download_bar.setRange(0, 0)

    def show_download_error(self, message: str) -> None:
        self._set_consent_downloading(False)
        self._download_error_label.setText(message)
        self._download_error_label.setVisible(True)

    # --- Détection ------------------------------------------------------

    def show_detecting(self) -> None:
        self._show_zone("detecting")
        self._status_title_label.setText(tr("android_detecting_status"))
        self._status_help_label.setText("")
        self._status_raw_output.setVisible(False)

    def show_detection_result(self, result: DetectionResult) -> None:
        if result.state == "ready" and result.device is not None:
            self._show_zone("ready")
            self._populate_device(result.device)
            self._current_model = result.device.model
            self._reset_catalog_section()
            return

        self._show_zone("status")
        title_key, help_key = _ANDROID_STATE_HELP_KEYS.get(
            result.state, ("android_state_adb_error_title", "android_state_adb_error_help")
        )
        self._status_title_label.setText(tr(title_key))
        self._status_help_label.setText(tr(help_key))

        raw_lines = [f"{entry.serial}\t{entry.state}" for entry in result.devices]
        if result.error_detail:
            raw_lines.append(result.error_detail)
        self._status_raw_output.setPlainText("\n".join(raw_lines))
        self._status_raw_output.setVisible(bool(raw_lines))

    def _populate_device(self, device: AndroidDeviceInfo) -> None:
        for field_name, label in self._device_value_labels.items():
            raw = getattr(device, field_name)
            unknown = raw == VALEUR_INCONNUE
            label.setText(tr("android_value_not_found") if unknown else raw)
            label.setProperty("role", "secondary" if unknown else "")
            theme.repolish(label)
        self._current_device = device
        self._render_emulator_list()

    # --- Catalogue --------------------------------------------------------

    def _reset_catalog_section(self) -> None:
        self._catalog_search_button.setText(tr("android_catalog_search_button"))
        self._catalog_search_button.setEnabled(True)
        self._catalog_status_label.setVisible(False)
        _android_clear_layout(self._catalog_result_layout)

    def _on_search_catalog_clicked(self) -> None:
        self.search_catalog_requested.emit(self._current_model)

    def show_catalog_searching(self) -> None:
        self._catalog_search_button.setEnabled(False)
        self._catalog_status_label.setText(tr("android_catalog_searching"))
        self._catalog_status_label.setVisible(True)
        _android_clear_layout(self._catalog_result_layout)

    def show_catalog_not_found(self) -> None:
        self._catalog_search_button.setEnabled(True)
        self._catalog_status_label.setText(tr("android_catalog_not_found"))
        self._catalog_status_label.setVisible(True)
        _android_clear_layout(self._catalog_result_layout)

    def show_catalog_error(self, message: str) -> None:
        self._catalog_search_button.setEnabled(True)
        self._catalog_status_label.setText(message)
        self._catalog_status_label.setVisible(True)
        _android_clear_layout(self._catalog_result_layout)

    def show_catalog_found(self, fiche: FicheConsole) -> None:
        self._catalog_search_button.setEnabled(True)
        self._catalog_status_label.setVisible(False)
        _android_clear_layout(self._catalog_result_layout)
        self._catalog_result_layout.addWidget(_android_plain_label(fiche.nom, role="rowTitle"))
        badge_text = _consoles_diverses_tr("badge_verified" if fiche.verifiee else "badge_unverified")
        self._catalog_result_layout.addWidget(
            _android_badge(badge_text, "maintained" if fiche.verifiee else "experimental"), alignment=Qt.AlignLeft
        )
        details = ", ".join(
            part for part in (fiche.fabricant, fiche.soc, fiche.os_type) if part and part != "inconnu"
        )
        if details:
            self._catalog_result_layout.addWidget(_android_plain_label(details, role="secondary", wrap=True))

    # --- Émulateurs recommandés ------------------------------------------

    def set_emulator_catalog(self, catalog: EmulatorCatalog) -> None:
        self._emulator_catalog = catalog
        self._render_emulator_list()

    def _render_emulator_list(self) -> None:
        """Recombine le catalogue complet (`set_emulator_catalog`) et
        l'appareil actuellement détecté (`_populate_device`) à chaque
        changement de l'un ou l'autre -- signalé : « la liste d'émulateurs
        est identique quelle que soit la console détectée »."""
        if self._emulator_catalog is None:
            return
        filtered = android_filter_emulators_for_device(self._emulator_catalog, self._current_device)
        self._emulators_warning_label.setText(filtered.avertissement)
        self._emulators_warning_label.setVisible(bool(filtered.avertissement))
        self._emulators_generic_label.setVisible(filtered.generique)
        self._device_filtered_emulateurs = filtered.emulateurs
        # Un nouvel appareil détecté peut rendre une entrée cochée non
        # réaliste (ex. remplacé par un appareil moins capable) -- jamais
        # comptée dans le compteur global une fois disparue de la liste.
        visible_ids = {entry.id for entry in filtered.emulateurs}
        self._checked_emulator_ids &= visible_ids
        self._render_category_sidebar()
        self._render_visible_emulator_cards()

    def _render_category_sidebar(self) -> None:
        """Classement par console émulée (§ écran Console Android, demandé
        explicitement, « inspiré d'un logiciel concurrent ») -- pseudo-
        catégorie « Toutes » en tête, puis les quatorze catégories de
        `android.emulators.CATEGORIES`, toujours toutes présentes (y
        compris à 0) pour que la colonne reste stable d'un appareil à
        l'autre. Reconstruite à chaque rendu (peu coûteux, quinze entrées
        fixes) plutôt que mise à jour en place -- même principe que le
        reste de cet écran (`_android_clear_layout`)."""
        counts = android_count_emulators_by_category(self._device_filtered_emulateurs)
        total = len(self._device_filtered_emulateurs)
        previous_selection = self._selected_category

        self._category_list.blockSignals(True)
        self._category_list.clear()
        all_item = QListWidgetItem(tr("android_category_all", count=total))
        all_item.setData(Qt.UserRole, None)
        self._category_list.addItem(all_item)
        for category_id, label in ANDROID_EMULATOR_CATEGORIES:
            item = QListWidgetItem(f"{label} ({counts[category_id]})")
            item.setData(Qt.UserRole, category_id)
            self._category_list.addItem(item)

        # Restaure la sélection précédente par identifiant (pas par index,
        # même si l'ordre ne change jamais) -- « Toutes » par défaut, y
        # compris au tout premier rendu (`previous_selection` vaut alors
        # déjà `None`, la valeur de « Toutes »).
        target_row = 0
        for row in range(self._category_list.count()):
            if self._category_list.item(row).data(Qt.UserRole) == previous_selection:
                target_row = row
                break
        self._category_list.setCurrentRow(target_row)
        self._category_list.blockSignals(False)

    def _on_category_row_changed(self, current: Optional[QListWidgetItem], previous) -> None:
        if current is None:
            return
        self._selected_category = current.data(Qt.UserRole)
        self._render_visible_emulator_cards()

    def _render_visible_emulator_cards(self) -> None:
        """Reconstruit uniquement les cartes (la colonne de gauche garde
        son état, gérée séparément par `_render_category_sidebar`) --
        appelée à chaque changement de catégorie, en plus d'un rendu
        complet (`_render_emulator_list`)."""
        visible = android_filter_emulators_by_category(self._device_filtered_emulateurs, self._selected_category)
        _android_clear_layout(self._emulators_list_layout)
        self._visible_checkboxes = {}
        for entry in visible:
            row, checkbox = _android_build_emulator_row(
                entry, entry.id in self._checked_emulator_ids, self._on_emulator_checked
            )
            self._visible_checkboxes[entry.id] = checkbox
            self._emulators_list_layout.addWidget(row)
        self._update_checked_counter()

    def _on_emulator_checked(self, entry_id: str, checked: bool) -> None:
        if checked:
            self._checked_emulator_ids.add(entry_id)
        else:
            self._checked_emulator_ids.discard(entry_id)
        self._update_checked_counter()

    def _update_checked_counter(self) -> None:
        """Compteur global (§ écran Console Android, demandé explicitement)
        -- porte sur l'ensemble filtré par appareil (`_device_filtered_
        emulateurs`), pas seulement la catégorie actuellement affichée :
        rester exact en changeant de catégorie, sans jamais perdre le
        compte des cases cochées ailleurs."""
        total = len(self._device_filtered_emulateurs)
        checked = len(self._checked_emulator_ids)
        self._checked_counter_label.setText(tr("android_checked_counter", checked=checked, total=total))

    def _on_check_all_clicked(self) -> None:
        """« Tout cocher », par catégorie (demandé explicitement) -- ne
        coche que les cartes actuellement affichées (`_visible_
        checkboxes`, déjà limitées à la catégorie en cours), jamais tout
        le catalogue derrière. Pilote les cases existantes directement
        (`setChecked`, qui déclenche `toggled` -> `_on_emulator_checked`)
        plutôt que de reconstruire les cartes -- même principe que
        `DoublonsResultsScreen._on_select_all`."""
        for checkbox in self._visible_checkboxes.values():
            checkbox.setChecked(True)

    def _on_uncheck_all_clicked(self) -> None:
        for checkbox in self._visible_checkboxes.values():
            checkbox.setChecked(False)


# --- Outil « Doublons de jeux » (docs/doublons.md, remplace l'ancien flux
# carte-SD-uniquement de la tuile) -- écrans autonomes, aucun rapport avec
# `Device`/`partitions/` : le dossier analysé est déjà accessible tel
# quel (PC, carte SD montée, disque externe), jamais un accès brut. ------


class DoublonsFolderScreen(Screen):
    """Choix du dossier à analyser -- outil autonome (docs/doublons.md) :
    n'importe quel dossier, pas seulement EASYROMS. Raccourcis cliquables
    vers les cartes/disques amovibles détectés (même confort que l'ancien
    flux carte SD, demandé explicitement) en plus du sélecteur de dossier
    classique -- jamais l'un à la place de l'autre. Options (dossiers
    ignorés, mode simulation) juste en dessous, appliquées au clic sur un
    raccourci ou après « Parcourir… »."""

    back_requested = Signal()
    folder_chosen = Signal(str)
    refresh_requested = Signal()
    # Signalé explicitement : « ne jamais obliger à relancer une analyse » --
    # affiché seulement quand un résultat en cache existe encore
    # (`set_resume_available`), jamais présumé disponible par défaut.
    resume_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 24)

        header = QHBoxLayout()
        back_button = QPushButton(tr("doublons_back_button"))
        back_button.setProperty("role", "flat")
        back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(back_button)
        title = QLabel(tr("doublons_folder_title"))
        title.setProperty("role", "title")
        header.addWidget(title)
        header.addStretch()
        refresh_button = QPushButton(tr("home_refresh"))
        refresh_button.clicked.connect(self.refresh_requested.emit)
        header.addWidget(refresh_button)
        root.addLayout(header)

        hint = QLabel(tr("doublons_folder_hint"))
        hint.setWordWrap(True)
        hint.setProperty("role", "secondary")
        root.addWidget(hint)

        # « Reprendre la dernière analyse » (§ demandé explicitement) --
        # masqué tant qu'aucun résultat n'est en cache (`set_resume_
        # available(None, None)`, état initial). Un cadre distinct plutôt
        # qu'un simple bouton perdu dans la liste : c'est la voie la plus
        # rapide pour revenir aux résultats, mérite d'être vue en premier.
        self._resume_frame = QFrame()
        self._resume_frame.setProperty("role", "row")
        resume_layout = QVBoxLayout(self._resume_frame)
        self._resume_label = QLabel()
        self._resume_label.setProperty("role", "secondary")
        self._resume_label.setWordWrap(True)
        resume_layout.addWidget(self._resume_label)
        self._resume_button = QPushButton(tr("doublons_resume_button"))
        self._resume_button.setProperty("role", "primary")
        self._resume_button.clicked.connect(self.resume_requested.emit)
        resume_layout.addWidget(self._resume_button, 0, Qt.AlignLeft)
        root.addWidget(self._resume_frame)
        self._resume_frame.setVisible(False)

        # Raccourcis -- un clic navigue directement (pas de bouton
        # Continuer séparé : ce sont des raccourcis, pas une sélection à
        # confirmer, contrairement à `DeviceDialog`).
        self._shortcuts_list = QListWidget()
        self._shortcuts_list.itemClicked.connect(self._on_shortcut_clicked)
        root.addWidget(self._shortcuts_list)
        self._shortcuts_empty_label = QLabel(tr("doublons_folder_no_shortcuts"))
        self._shortcuts_empty_label.setProperty("role", "secondary")
        root.addWidget(self._shortcuts_empty_label)

        browse_button = QPushButton(tr("doublons_browse_button"))
        browse_button.setProperty("role", "primary")
        browse_button.clicked.connect(self._on_browse_clicked)
        root.addWidget(browse_button)

        options_title = QLabel(tr("doublons_options_title"))
        options_title.setProperty("role", "sectionLabel")
        root.addWidget(options_title)

        # Coché par défaut au premier lancement (`AppConfig.
        # doublons_simulation_mode`, § garde-fou 1) -- l'utilisateur
        # décoche sciemment pour agir pour de vrai.
        self._simulation_checkbox = QCheckBox(tr("doublons_simulation_checkbox"))
        root.addWidget(self._simulation_checkbox)

        ignored_title = QLabel(tr("doublons_ignored_folders_title"))
        ignored_title.setProperty("role", "secondary")
        root.addWidget(ignored_title)
        self._ignored_folders_layout = QVBoxLayout()
        root.addLayout(self._ignored_folders_layout)
        self._ignored_checkboxes: Dict[str, QCheckBox] = {}

        root.addStretch()

    def set_resume_available(self, folder_display: Optional[str], date_display: Optional[str]) -> None:
        """`None` (les deux, toujours ensemble) masque le cadre --
        aucun résultat en cache, ou son dossier a disparu entre-temps
        (§ `main_window.py::_refresh_doublons_resume_button`). Le texte
        est déjà formaté par l'appelant (date lisible, chemin) -- cet
        écran n'a besoin de rien savoir du format du cache lui-même."""
        available = folder_display is not None and date_display is not None
        self._resume_frame.setVisible(available)
        if available:
            self._resume_label.setText(tr("doublons_resume_info", folder=folder_display, date=date_display))

    def set_simulation_mode(self, enabled: bool) -> None:
        self._simulation_checkbox.setChecked(enabled)

    def simulation_mode(self) -> bool:
        return self._simulation_checkbox.isChecked()

    def set_ignored_folders(self, names: List[str]) -> None:
        """Reconstruit entièrement la liste -- toutes cochées par défaut
        (dossiers ignorés *par défaut*, §brief), modifiable ensuite."""
        while self._ignored_folders_layout.count():
            item = self._ignored_folders_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._ignored_checkboxes = {}
        for name in names:
            checkbox = QCheckBox(name)
            checkbox.setChecked(True)
            self._ignored_folders_layout.addWidget(checkbox)
            self._ignored_checkboxes[name] = checkbox

    def ignored_folders(self) -> List[str]:
        return [name for name, checkbox in self._ignored_checkboxes.items() if checkbox.isChecked()]

    def set_shortcuts(self, shortcuts: List[Tuple[str, str]]) -> None:
        """`shortcuts` : liste de `(libellé, chemin)` -- cartes/disques
        amovibles détectés, EASYROMS en priorité quand elle est
        identifiable (§ demandé explicitement)."""
        self._shortcuts_list.clear()
        for label, path in shortcuts:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, path)
            self._shortcuts_list.addItem(item)
        self._shortcuts_empty_label.setVisible(not shortcuts)
        self._shortcuts_list.setVisible(bool(shortcuts))

    def _on_shortcut_clicked(self, item: QListWidgetItem) -> None:
        self.folder_chosen.emit(item.data(Qt.UserRole))

    def _on_browse_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("doublons_browse_button"))
        if path:
            self.folder_chosen.emit(path)


class DoublonsScanProgressScreen(Screen):
    """Analyse en cours (§ interface, « barre de progression annulable,
    l'interface ne gèle jamais ») -- `QProgressBar` indéterminée : le
    nombre total de fichiers n'est jamais connu à l'avance (ce serait
    l'analyse elle-même, en double)."""

    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 24)
        root.addStretch()

        title = QLabel(tr("doublons_scan_progress_title"))
        title.setProperty("role", "title")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        self._count_label = QLabel("")
        self._count_label.setAlignment(Qt.AlignCenter)
        self._count_label.setProperty("role", "secondary")
        root.addWidget(self._count_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        root.addWidget(self._progress_bar)

        cancel_button = QPushButton(tr("doublons_scan_cancel_button"))
        cancel_button.clicked.connect(self.cancel_requested.emit)
        root.addWidget(cancel_button, 0, Qt.AlignCenter)

        root.addStretch()

    def set_files_scanned(self, count: int) -> None:
        self._count_label.setText(tr("doublons_scan_progress_count", count=count))


class DoublonsMoveProgressScreen(Screen):
    """Déplacement en cours (signalement utilisateur -- bouton principal
    « Écarter X fichiers ») -- contrairement au scan ci-dessus, le total
    est connu dès le départ (`DoublonsMoveRunner.progress` émet
    `(fait, total)`), donc une barre déterminée plutôt qu'indéterminée."""

    cancel_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 24)
        root.addStretch()

        title = QLabel(tr("doublons_move_progress_title"))
        title.setProperty("role", "title")
        title.setAlignment(Qt.AlignCenter)
        root.addWidget(title)

        self._count_label = QLabel("")
        self._count_label.setAlignment(Qt.AlignCenter)
        self._count_label.setProperty("role", "secondary")
        root.addWidget(self._count_label)

        self._progress_bar = QProgressBar()
        root.addWidget(self._progress_bar)

        cancel_button = QPushButton(tr("doublons_scan_cancel_button"))
        cancel_button.clicked.connect(self.cancel_requested.emit)
        root.addWidget(cancel_button, 0, Qt.AlignCenter)

        root.addStretch()

    def set_progress(self, done: int, total: int) -> None:
        self._progress_bar.setRange(0, total)
        self._progress_bar.setValue(done)
        self._count_label.setText(tr("doublons_move_progress_count", done=done, total=total))


class DoublonsRiskConfirmDialog(Dialog):
    """Confirmation dédiée avant de lancer une analyse à risque (§ garde-
    fous ajoutés après validation du plan : racine de disque, dossier
    utilisateur entier, ou plus de 200 000 fichiers rencontrés en cours
    d'analyse) -- un seul message à la fois, posé par l'appelant selon le
    cas précis rencontré. Jamais `role="danger"` : rien n'est encore
    modifié à ce stade, juste une analyse potentiellement longue/hors
    de propos."""

    confirmed = Signal()
    # Émis en plus d'une simple fermeture (§ le cas des 200 000 fichiers,
    # `DoublonsScanRunner` reste bloqué en attente d'une réponse -- Annuler
    # doit le débloquer explicitement, pas seulement fermer la fenêtre).
    # Les deux autres cas (racine de disque, dossier utilisateur entier)
    # n'ont besoin de rien de plus qu'une fermeture -- `cancelled` reste
    # sans effet s'il n'est jamais connecté pour eux.
    cancelled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self._title_label = QLabel(tr("doublons_risk_title"))
        self._title_label.setProperty("role", "title")
        layout.addWidget(self._title_label)
        self._message = QLabel()
        self._message.setWordWrap(True)
        layout.addWidget(self._message)
        layout.addStretch()

        buttons = QHBoxLayout()
        cancel_button = QPushButton(tr("doublons_risk_cancel"))
        cancel_button.clicked.connect(self._on_cancel)
        confirm_button = QPushButton(tr("doublons_risk_continue"))
        confirm_button.setProperty("role", "primary")
        confirm_button.clicked.connect(self._on_confirm)
        buttons.addWidget(cancel_button)
        buttons.addStretch()
        buttons.addWidget(confirm_button)
        layout.addLayout(buttons)

        self.resize(440, 260)

    def _on_cancel(self) -> None:
        self.close()
        self.cancelled.emit()

    def set_message(self, message: str) -> None:
        self._message.setText(message)

    def set_title(self, title: str) -> None:
        """Troisième réutilisation de cette fenêtre (racine de disque,
        dossier utilisateur entier, dossier volumineux -- toutes trois au
        titre par défaut) : « ignorer ce fichier et continuer » (§ demandé
        explicitement, point 4) a besoin d'un titre différent, ce
        déplacement n'ayant rien à voir avec une analyse à risque."""
        self._title_label.setText(title)

    def _on_confirm(self) -> None:
        self.close()
        self.confirmed.emit()


class DoublonsResultsScreen(Screen):
    """Résultats de l'analyse (docs/doublons.md §Interface point 3) --
    deux sections distinctes : copies identiques (palier 1, « certain »,
    précochées -- seule exception à la règle générale de ce projet
    « jamais de présélection », explicitement demandée par le brief) et
    versions différentes (palier 2, jamais précochées, version suggérée
    mise en évidence par une étoile). Groupes exclus (fichier lié
    introuvable) affichés séparément, jamais silencieusement absents."""

    back_requested = Signal()
    move_requested = Signal(list)  # List[Unit] à écarter (jamais le fichier gardé)
    export_requested = Signal()
    undo_requested = Signal()
    # Signalé : « permettre de choisir l'emplacement du dossier de
    # destination » -- ce champ ouvre lui-même le sélecteur de dossier
    # (même principe que `DoublonsFolderScreen._on_browse_clicked`) et
    # n'émet que le chemin choisi ; la validation (dossier refusé --
    # à l'intérieur du dossier analysé ailleurs qu'en _doublons, racine
    # d'un disque, lecture seule) reste à la charge de `main_window.py`,
    # qui seul connaît `doublons.move.check_destination_allowed` et le
    # dossier actuellement analysé.
    destination_chosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 24)

        header = QHBoxLayout()
        back_button = QPushButton(tr("doublons_back_button"))
        back_button.setProperty("role", "flat")
        back_button.clicked.connect(self.back_requested.emit)
        header.addWidget(back_button)
        title = QLabel(tr("doublons_results_title"))
        title.setProperty("role", "title")
        header.addWidget(title)
        header.addStretch()
        self._undo_button = QPushButton(tr("doublons_undo_button"))
        self._undo_button.setEnabled(False)
        self._undo_button.clicked.connect(self.undo_requested.emit)
        header.addWidget(self._undo_button)
        export_button = QPushButton(tr("doublons_export_button"))
        export_button.clicked.connect(self.export_requested.emit)
        header.addWidget(export_button)
        # Bouton principal (signalement utilisateur -- 1900 fichiers sur
        # 1272 groupes) -- sans lui, traiter toute la sélection à cette
        # échelle demandait de rouvrir chaque groupe un par un pour son
        # propre « Écarter la sélection ». Répété en bas de la liste
        # (reconstruit à chaque `set_results`, ci-dessous) ; les deux
        # instances sont tenues synchronisées par `_update_selection_summary`.
        self._move_all_button_top = QPushButton()
        self._move_all_button_top.setProperty("role", "primary")
        self._move_all_button_top.clicked.connect(self._on_move_all_selected)
        header.addWidget(self._move_all_button_top)
        self._move_all_button_bottom: Optional[QPushButton] = None
        root.addLayout(header)

        # Emplacement du dossier de destination (signalé explicitement :
        # « permettre de choisir l'emplacement... au lieu de _doublons
        # imposé à la racine du dossier analysé ») -- champ en lecture
        # seule (jamais tapé à la main, seul un vrai sélecteur de dossier
        # garantit un chemin valide) prérempli par `main_window.py` via
        # `set_destination` (`<dossier analysé>/_doublons` par défaut, ou
        # la dernière destination mémorisée, § point 5).
        destination_row = QHBoxLayout()
        destination_label = QLabel(tr("doublons_destination_label"))
        destination_label.setProperty("role", "secondary")
        destination_row.addWidget(destination_label)
        self._destination_edit = QLineEdit()
        self._destination_edit.setReadOnly(True)
        destination_row.addWidget(self._destination_edit, 1)
        change_destination_button = QPushButton(tr("doublons_destination_change_button"))
        change_destination_button.clicked.connect(self._on_change_destination_clicked)
        destination_row.addWidget(change_destination_button)
        root.addLayout(destination_row)

        # Signalé (point 2) : disque différent du dossier analysé --
        # copie puis suppression de la source, plus lent qu'un
        # déplacement instantané. Jamais bloquant, seulement informatif
        # (même famille visuelle que `_simulation_banner`/`_auto_
        # selection_banner` ci-dessous, `role="warning"`).
        self._cross_volume_banner = QLabel(tr("doublons_destination_cross_volume_warning"))
        self._cross_volume_banner.setProperty("role", "warning")
        self._cross_volume_banner.setWordWrap(True)
        self._cross_volume_banner.setVisible(False)
        root.addWidget(self._cross_volume_banner)

        # Bandeau permanent tant que le mode simulation est actif (§
        # garde-fou 1) -- jamais un simple détail dans le journal, ce
        # doit être visible en permanence sur cet écran.
        self._simulation_banner = QLabel(tr("doublons_simulation_banner"))
        self._simulation_banner.setProperty("role", "warning")
        self._simulation_banner.setVisible(False)
        root.addWidget(self._simulation_banner)

        # Sélection automatique (docs/doublons-selection.md) -- rappel
        # permanent qu'une case cochée par défaut reste une suggestion,
        # jamais une garantie, tant qu'il reste au moins un groupe affiché.
        self._auto_selection_banner = QLabel(tr("doublons_auto_selection_banner"))
        self._auto_selection_banner.setProperty("role", "warning")
        self._auto_selection_banner.setVisible(False)
        root.addWidget(self._auto_selection_banner)

        # Trois actions globales (docs/doublons-selection.md) -- à l'échelle
        # de milliers de groupes, rouvrir chacun pour ajuster sa sélection
        # à la main serait irréaliste. `_version_group_checkboxes` (distinct
        # de `_all_checkboxes` ci-dessous) ne retient que les cases du
        # palier 2 : « ne garder que France/Europe » n'a de sens que pour
        # des versions du même jeu, jamais pour des copies strictement
        # identiques (palier 1, aucune notion de région à départager).
        self._version_group_checkboxes: Dict[QCheckBox, Unit] = {}
        self._selection_buttons_row = QWidget()
        buttons_row = QHBoxLayout(self._selection_buttons_row)
        buttons_row.setContentsMargins(0, 0, 0, 0)
        select_all_button = QPushButton(tr("doublons_select_all_button"))
        select_all_button.clicked.connect(self._on_select_all)
        buttons_row.addWidget(select_all_button)
        select_none_button = QPushButton(tr("doublons_select_none_button"))
        select_none_button.clicked.connect(self._on_select_none)
        buttons_row.addWidget(select_none_button)
        keep_french_european_button = QPushButton(tr("doublons_keep_french_european_button"))
        keep_french_european_button.clicked.connect(self._on_keep_only_french_european)
        buttons_row.addWidget(keep_french_european_button)
        buttons_row.addStretch()
        self._selection_buttons_row.setVisible(False)
        root.addWidget(self._selection_buttons_row)

        # Compteur global (toutes cases à cocher confondues, tous groupes) --
        # demandé après un essai réel sur des milliers de fichiers, où le
        # total à écarter n'était visible qu'en dépliant chaque groupe un
        # par un. `_all_checkboxes` reconstruit à chaque `set_results`.
        self._all_checkboxes: Dict[QCheckBox, Unit] = {}
        self._selection_label = QLabel()
        self._selection_label.setProperty("role", "secondary")
        root.addWidget(self._selection_label)

        self._summary_label = QLabel()
        self._summary_label.setWordWrap(True)
        self._summary_label.setProperty("role", "secondary")
        root.addWidget(self._summary_label)

        self._empty_label = QLabel(tr("doublons_empty"))
        self._empty_label.setProperty("role", "secondary")
        self._empty_label.setVisible(False)
        root.addWidget(self._empty_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self._list_container = QWidget()
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setSpacing(12)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_container)
        root.addWidget(scroll, 1)

        self._scan_result: ScanResult = ScanResult()
        self._macos_move_blocked = False

    def set_simulation_mode(self, enabled: bool) -> None:
        self._simulation_banner.setVisible(enabled)

    def set_undo_available(self, available: bool) -> None:
        self._undo_button.setEnabled(available)

    def set_destination(self, path: str) -> None:
        self._destination_edit.setText(path)
        self._destination_edit.setToolTip(path)

    def destination(self) -> str:
        return self._destination_edit.text()

    def set_cross_volume_warning(self, cross_volume: bool) -> None:
        self._cross_volume_banner.setVisible(cross_volume)

    def _on_change_destination_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("doublons_destination_change_button"))
        if path:
            self.destination_chosen.emit(path)

    def set_results(self, scan_result: ScanResult, macos_move_blocked: bool = False) -> None:
        """Reconstruit entièrement la liste -- appelé après chaque scan,
        y compris un nouveau scan relancé après un déplacement réussi
        (reflète toujours l'état réel du dossier, jamais une mise à jour
        partielle de l'affichage précédent). Mémorisé (`self._scan_result`/
        `self._macos_move_blocked`) pour que `remove_units` ci-dessous
        puisse reconstruire un résultat filtré sans que l'appelant n'ait à
        le refournir -- lui-même ne rebâtit jamais silencieusement les
        cases à cocher, § juste en dessous."""
        self._scan_result = scan_result
        self._macos_move_blocked = macos_move_blocked
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._all_checkboxes = {}
        self._version_group_checkboxes = {}

        has_groups = bool(scan_result.exact_duplicate_groups or scan_result.version_groups)
        self._empty_label.setVisible(not has_groups)
        self._auto_selection_banner.setVisible(has_groups)
        self._selection_buttons_row.setVisible(has_groups)
        self._summary_label.setText(
            tr(
                "doublons_summary",
                files=scan_result.files_scanned,
                exact=len(scan_result.exact_duplicate_groups),
                versions=len(scan_result.version_groups),
            )
        )

        insert_at = 0
        if scan_result.excluded:
            self._list_layout.insertWidget(insert_at, self._build_excluded_section(scan_result.excluded))
            insert_at += 1
        for group in scan_result.exact_duplicate_groups:
            self._list_layout.insertWidget(insert_at, self._build_exact_group_row(group, macos_move_blocked))
            insert_at += 1
        for group in scan_result.version_groups:
            self._list_layout.insertWidget(insert_at, self._build_version_group_row(group, macos_move_blocked))
            insert_at += 1

        # Répété en bas de la liste -- sur 1272 groupes (signalement
        # utilisateur), faire défiler jusqu'en haut pour agir n'est pas
        # raisonnable. `None` quand la liste est vide : rien à déplacer,
        # même logique que `_selection_buttons_row` ci-dessus.
        self._move_all_button_bottom = None
        if has_groups:
            bottom_wrapper = QWidget()
            bottom_layout = QHBoxLayout(bottom_wrapper)
            bottom_layout.setContentsMargins(0, 8, 0, 8)
            bottom_layout.addStretch()
            self._move_all_button_bottom = QPushButton()
            self._move_all_button_bottom.setProperty("role", "primary")
            self._move_all_button_bottom.clicked.connect(self._on_move_all_selected)
            bottom_layout.addWidget(self._move_all_button_bottom)
            self._list_layout.insertWidget(insert_at, bottom_wrapper)
            insert_at += 1

        self._update_selection_summary()

    def remove_units(self, moved_units: List[Unit]) -> None:
        """Retire les unités déjà déplacées avec succès du résultat
        affiché -- § bug corrigé, signalé explicitement : après une
        erreur de déplacement, l'app relançait l'analyse complète au lieu
        de revenir aux résultats « en retirant les fichiers déjà déplacés
        avec succès », sélection intacte pour le reste. Reconstruit la
        liste comme `set_results` (aucune API incrémentale plus fine
        n'existe pour retirer une seule unité d'un groupe déjà affiché),
        mais réapplique l'état de chaque case déjà cochée par
        l'utilisateur -- identifiée par identité d'objet (`id(unit)`, les
        `Unit` restantes sont exactement les mêmes instances qu'avant,
        jamais des copies) plutôt que par valeur, pour ne jamais confondre
        deux fichiers de même taille/contenu."""
        if not moved_units:
            return
        moved_ids = {id(unit) for unit in moved_units}
        previous_checked = {id(unit): checkbox.isChecked() for checkbox, unit in self._all_checkboxes.items()}

        def _prune(units: List[Unit]) -> List[Unit]:
            return [unit for unit in units if id(unit) not in moved_ids]

        exact_groups: List[ExactDuplicateGroup] = []
        for group in self._scan_result.exact_duplicate_groups:
            remaining = _prune(group.units)
            if len(remaining) >= 2:
                exact_groups.append(ExactDuplicateGroup(units=remaining, sha256=group.sha256))

        version_groups: List[VersionGroup] = []
        for group in self._scan_result.version_groups:
            remaining = _prune(group.units)
            if len(remaining) >= 2:
                suggested = group.suggested_keep if group.suggested_keep in remaining else remaining[0]
                version_groups.append(
                    VersionGroup(
                        system_folder=group.system_folder,
                        normalized_title=group.normalized_title,
                        units=remaining,
                        suggested_keep=suggested,
                    )
                )

        new_result = ScanResult(
            exact_duplicate_groups=exact_groups,
            version_groups=version_groups,
            excluded=self._scan_result.excluded,
            files_scanned=self._scan_result.files_scanned,
        )
        self.set_results(new_result, self._macos_move_blocked)
        for checkbox, unit in self._all_checkboxes.items():
            previous = previous_checked.get(id(unit))
            if previous is not None:
                checkbox.setChecked(previous)

    def _update_selection_summary(self) -> None:
        selected = [unit for checkbox, unit in self._all_checkboxes.items() if checkbox.isChecked()]
        total_files = sum(len(unit.members) for unit in selected)
        total_bytes = sum(unit.total_size_bytes for unit in selected)
        self._selection_label.setText(
            tr("doublons_selection_summary", count=total_files, size=_format_size(total_bytes))
        )
        move_all_label = tr("doublons_move_all_button", count=total_files, size=_format_size(total_bytes))
        for button in (self._move_all_button_top, self._move_all_button_bottom):
            if button is not None:
                button.setText(move_all_label)
                button.setEnabled(total_files > 0)

    def _on_move_all_selected(self) -> None:
        selected = [unit for checkbox, unit in self._all_checkboxes.items() if checkbox.isChecked()]
        if selected:
            self.move_requested.emit(selected)

    def _on_select_all(self) -> None:
        for checkbox in self._all_checkboxes:
            checkbox.setChecked(True)

    def _on_select_none(self) -> None:
        for checkbox in self._all_checkboxes:
            checkbox.setChecked(False)

    def _on_keep_only_french_european(self) -> None:
        """Ne touche que le palier 2 -- une copie strictement identique
        (palier 1) n'a pas de région à départager entre ses membres."""
        for checkbox, unit in self._version_group_checkboxes.items():
            _title, tags = extract_tags(unit.representative.stem)
            # Rangs 0 (France/Fr) et 1 (Europe) -- `region_rank`,
            # normalize.py -- gardés (décochés) ; tout le reste écarté.
            keep = region_rank(tags) <= 1
            checkbox.setChecked(not keep)

    def _build_exact_group_row(self, group: ExactDuplicateGroup, macos_move_blocked: bool) -> QWidget:
        frame = QFrame()
        frame.setProperty("role", "row")
        layout = QVBoxLayout(frame)

        header = QHBoxLayout()
        title = QLabel(tr("doublons_group_exact_title"))
        title.setProperty("role", "rowTitle")
        header.addWidget(title)
        # 8 premiers caractères de l'empreinte (§ vérifiée par
        # `Get-FileHash` sur du vrai matériel, aucune coïncidence de
        # taille -- le contenu est bel et bien identique octet pour
        # octet) -- à côté du titre, pas dans un texte à déplier.
        hash_label = QLabel(tr("doublons_exact_group_hash_label", hash=group.sha256[:8]))
        hash_label.setProperty("role", "secondary")
        header.addWidget(hash_label)
        header.addStretch()
        badge = QLabel(tr("status_done"))
        badge.setProperty("role", "badge")
        badge.setProperty("badgeKind", "done")
        header.addWidget(badge)
        layout.addLayout(header)

        notice = QLabel(tr("doublons_exact_group_identical_notice"))
        notice.setProperty("role", "secondary")
        notice.setWordWrap(True)
        layout.addWidget(notice)

        checkboxes: Dict[QCheckBox, Unit] = {}
        for index, unit in enumerate(group.units):
            row = QHBoxLayout()
            checkbox = QCheckBox(tr("doublons_move_this_one"))
            # « Certain », donc précoché par défaut -- sauf le premier,
            # gardé (§ garde-fou 1, seule exception documentée à la règle
            # générale de ce projet contre toute présélection).
            checkbox.setChecked(index != 0)
            checkboxes[checkbox] = unit
            self._all_checkboxes[checkbox] = unit
            checkbox.toggled.connect(self._update_selection_summary)
            row.addWidget(checkbox)
            label = QLabel(f"{unit.representative} — {_format_size(unit.total_size_bytes)}")
            label.setProperty("role", "secondary")
            label.setWordWrap(True)
            row.addWidget(label, 1)
            layout.addLayout(row)

        move_button = QPushButton(tr("doublons_move_selected_button"))
        move_button.setProperty("role", "primary")
        move_button.setEnabled(not macos_move_blocked)
        move_button.clicked.connect(lambda: self._emit_move_requested(checkboxes))
        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(move_button)
        layout.addLayout(button_row)
        return frame

    def _build_version_group_row(self, group: VersionGroup, macos_move_blocked: bool) -> QWidget:
        frame = QFrame()
        frame.setProperty("role", "row")
        layout = QVBoxLayout(frame)

        header = QHBoxLayout()
        label_text = f"{group.system_folder} — {group.normalized_title}" if group.system_folder else group.normalized_title
        title = QLabel(label_text)
        title.setProperty("role", "rowTitle")
        header.addWidget(title)
        header.addStretch()
        if macos_move_blocked:
            badge = QLabel(tr("status_platform_limited"))
            badge.setProperty("role", "badge")
            badge.setProperty("badgeKind", "platform_limited")
            header.addWidget(badge)
        layout.addLayout(header)

        checkboxes: Dict[QCheckBox, Unit] = {}
        move_button = QPushButton(tr("doublons_move_selected_button"))
        move_button.setProperty("role", "primary")
        move_button.setEnabled(False)

        def _on_toggled() -> None:
            any_checked = any(box.isChecked() for box in checkboxes)
            move_button.setEnabled(any_checked and not macos_move_blocked)

        for unit in group.units:
            row = QHBoxLayout()
            checkbox = QCheckBox(tr("doublons_move_this_one"))
            checkbox.toggled.connect(_on_toggled)
            checkboxes[checkbox] = unit
            self._all_checkboxes[checkbox] = unit
            self._version_group_checkboxes[checkbox] = unit
            checkbox.toggled.connect(self._update_selection_summary)
            # Sélection automatique (docs/doublons-selection.md) : tout
            # sauf la version suggérée (étoile) précoché par défaut --
            # sans quoi l'outil reste inutilisable à l'échelle de milliers
            # de groupes de versions (constat réel : 1272 groupes, 3
            # fichiers sélectionnés). Toujours modifiable à la main
            # ensuite (point 5 du brief) -- une suggestion, pas une
            # garantie (bandeau ci-dessus).
            checkbox.setChecked(unit is not group.suggested_keep)
            row.addWidget(checkbox)
            suggested_marker = " ★" if unit is group.suggested_keep else ""
            path_label = QLabel(f"{unit.representative} — {_format_size(unit.total_size_bytes)}{suggested_marker}")
            path_label.setProperty("role", "secondary")
            path_label.setWordWrap(True)
            row.addWidget(path_label, 1)
            layout.addLayout(row)

        move_button.clicked.connect(lambda: self._emit_move_requested(checkboxes))
        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(move_button)
        layout.addLayout(button_row)
        return frame

    def _emit_move_requested(self, checkboxes: Dict[QCheckBox, Unit]) -> None:
        selected = [unit for checkbox, unit in checkboxes.items() if checkbox.isChecked()]
        if selected:
            self.move_requested.emit(selected)

    def _build_excluded_section(self, excluded: List[ExclusionWarning]) -> QWidget:
        frame = QFrame()
        frame.setProperty("role", "danger")
        layout = QVBoxLayout(frame)
        title = QLabel(tr("doublons_excluded_title"))
        title.setProperty("role", "dangerTitle")
        layout.addWidget(title)
        for warning in excluded:
            text = tr("doublons_excluded_entry", manifest=warning.manifest.name, missing=", ".join(warning.missing))
            label = QLabel(text)
            label.setProperty("role", "dangerMessage")
            label.setWordWrap(True)
            layout.addWidget(label)
        return frame


class ConfirmMoveDoublonsDialog(Dialog):
    """Confirmation avant d'écarter des doublons (§ interface point 4) --
    **pas** `role="danger"` : rien n'est perdu (déplacement vers
    `_doublons/`, jamais une suppression), un simple bouton de
    confirmation suffit plutôt que la friction d'une case à cocher
    réservée aux actions réellement irréversibles. Texte adapté si le
    mode simulation est actif (« Simuler le déplacement de... »).

    Signalé : le champ Destination de l'écran de résultats « passe
    inaperçu » -- cette fenêtre, le tout dernier geste avant une écriture
    réelle, affiche désormais la destination en évidence avec son propre
    bouton « Changer… » et les avertissements associés (autre disque,
    espace libre), plutôt que de les laisser seulement sur l'écran
    derrière. Fermer cette fenêtre (Annuler) ne fait rien d'autre que la
    fermer : l'écran de résultats en dessous n'a jamais été quitté (cette
    fenêtre est une simple superposition, `Dialog.open()` -- règle §2 du
    déplacement 2, « revenir en arrière ramène aux résultats, sélection
    intacte », déjà garanti par cette seule architecture)."""

    confirmed = Signal()
    # Même contrat que `DoublonsResultsScreen.destination_chosen` --
    # cette fenêtre ouvre elle-même le sélecteur de dossier, la
    # validation reste à la charge de `main_window.py`.
    destination_chosen = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("doublons_confirm_title"))
        layout = QVBoxLayout(self)
        title = QLabel(tr("doublons_confirm_title"))
        title.setProperty("role", "title")
        layout.addWidget(title)
        self._message = QLabel()
        self._message.setWordWrap(True)
        layout.addWidget(self._message)

        # Destination en évidence (signalé explicitement) -- même
        # contrôle en lecture seule + bouton Changer… que l'écran de
        # résultats, jamais un champ modifiable à la main.
        destination_row = QHBoxLayout()
        destination_label = QLabel(tr("doublons_destination_label"))
        destination_label.setProperty("role", "secondary")
        destination_row.addWidget(destination_label)
        self._destination_edit = QLineEdit()
        self._destination_edit.setReadOnly(True)
        destination_row.addWidget(self._destination_edit, 1)
        change_destination_button = QPushButton(tr("doublons_destination_change_button"))
        change_destination_button.clicked.connect(self._on_change_destination_clicked)
        destination_row.addWidget(change_destination_button)
        layout.addLayout(destination_row)

        self._cross_volume_banner = QLabel(tr("doublons_destination_cross_volume_warning"))
        self._cross_volume_banner.setProperty("role", "warning")
        self._cross_volume_banner.setWordWrap(True)
        self._cross_volume_banner.setVisible(False)
        layout.addWidget(self._cross_volume_banner)

        self._space_warning_banner = QLabel()
        self._space_warning_banner.setProperty("role", "warning")
        self._space_warning_banner.setWordWrap(True)
        self._space_warning_banner.setVisible(False)
        layout.addWidget(self._space_warning_banner)

        # § demandé explicitement, point 6 : annoncé ici, avant même de
        # cliquer sur le bouton de validation -- jamais découvert en
        # cours de route sur un fichier parmi d'autres (`move_duplicates`
        # refuse pour de vrai le lot entier dans ce cas, § autorité
        # réelle déjà appliquée ailleurs dans ce projet).
        self._fat_warning_banner = QLabel()
        self._fat_warning_banner.setProperty("role", "warning")
        self._fat_warning_banner.setWordWrap(True)
        self._fat_warning_banner.setVisible(False)
        layout.addWidget(self._fat_warning_banner)

        layout.addStretch()

        buttons = QHBoxLayout()
        cancel_button = QPushButton(tr("doublons_confirm_cancel"))
        cancel_button.clicked.connect(self.close)
        self._confirm_button = QPushButton(tr("doublons_confirm_button"))
        self._confirm_button.setProperty("role", "primary")
        self._confirm_button.clicked.connect(self._on_confirm)
        buttons.addWidget(cancel_button)
        buttons.addStretch()
        buttons.addWidget(self._confirm_button)
        layout.addLayout(buttons)

        # Le bouton de validation reste désactivé tant que la destination
        # n'est pas structurellement valide (§ demandé explicitement) --
        # `main_window.py` l'établit via `set_destination_valid` dès
        # l'ouverture, avant même que l'utilisateur touche « Changer… ».
        self._destination_valid = True
        self.resize(480, 360)

    def set_units(self, units: List[Unit], dry_run: bool) -> None:
        total_files = sum(len(unit.members) for unit in units)
        total_bytes = sum(unit.total_size_bytes for unit in units)
        message_key = "doublons_confirm_message_simulation" if dry_run else "doublons_confirm_message"
        button_key = "doublons_confirm_button_simulation" if dry_run else "doublons_confirm_button"
        self._message.setText(tr(message_key, count=total_files, size=_format_size(total_bytes)))
        self._confirm_button.setText(tr(button_key))

    def set_destination(self, path: str) -> None:
        self._destination_edit.setText(path)
        self._destination_edit.setToolTip(path)

    def destination(self) -> str:
        return self._destination_edit.text()

    def set_cross_volume_warning(self, cross_volume: bool) -> None:
        self._cross_volume_banner.setVisible(cross_volume)

    def set_space_warning(self, insufficient: bool, available_display: str = "") -> None:
        """`insufficient=True` affiche l'espace libre actuellement
        disponible à la destination (`available_display`, déjà formaté
        par l'appelant, § `_format_size`) -- purement informatif, ne
        conditionne jamais `_destination_valid` (contrairement aux
        refus structurels ci-dessous) : l'espace peut changer entre cette
        estimation et l'écriture réelle, qui refait de toute façon sa
        propre vérification définitive (`move.py::_check_disk_space`)."""
        self._space_warning_banner.setVisible(insufficient)
        if insufficient:
            self._space_warning_banner.setText(
                tr("doublons_destination_space_warning", available=available_display)
            )

    def set_fat_warning(self, oversized_count: int) -> None:
        """`oversized_count > 0` : au moins un fichier sélectionné dépasse
        la limite FAT (4 Gio) et la destination est identifiée comme FAT
        (§ demandé explicitement, point 6) -- purement informatif, comme
        `set_space_warning` : ne conditionne jamais `_destination_valid`,
        `move_duplicates` refuse le lot entier pour de vrai au moment de
        l'exécuter (`FatFileSizeLimitExceeded`), c'est cette vérification-là
        qui fait réellement autorité."""
        self._fat_warning_banner.setVisible(oversized_count > 0)
        if oversized_count > 0:
            self._fat_warning_banner.setText(tr("doublons_destination_fat_warning", count=oversized_count))

    def set_destination_valid(self, valid: bool) -> None:
        """Signalé explicitement : « le bouton de validation reste
        désactivé tant que la destination n'est pas valide » -- `valid`
        reflète `doublons.move.check_destination_allowed` (dossier à
        l'intérieur du dossier analysé ailleurs qu'en _doublons, racine
        d'un disque, lecture seule), jamais l'espace disque (avertissement
        seulement, ci-dessus)."""
        self._destination_valid = valid
        self._confirm_button.setEnabled(valid)

    def _on_change_destination_clicked(self) -> None:
        path = QFileDialog.getExistingDirectory(self, tr("doublons_destination_change_button"))
        if path:
            self.destination_chosen.emit(path)

    def _on_confirm(self) -> None:
        if not self._destination_valid:
            return
        self.close()
        self.confirmed.emit()


class ConfirmUndoDoublonsDialog(Dialog):
    """Confirmation avant « Tout annuler » (§ interface) -- même famille
    que `ConfirmMoveDoublonsDialog` : restaurer des fichiers n'est pas
    non plus une action destructrice, jamais `role="danger"`."""

    confirmed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("doublons_undo_confirm_title"))
        layout = QVBoxLayout(self)
        title = QLabel(tr("doublons_undo_confirm_title"))
        title.setProperty("role", "title")
        layout.addWidget(title)
        message = QLabel(tr("doublons_undo_confirm_message"))
        message.setWordWrap(True)
        layout.addWidget(message)
        layout.addStretch()

        buttons = QHBoxLayout()
        cancel_button = QPushButton(tr("doublons_confirm_cancel"))
        cancel_button.clicked.connect(self.close)
        confirm_button = QPushButton(tr("doublons_undo_confirm_button"))
        confirm_button.setProperty("role", "primary")
        confirm_button.clicked.connect(self._on_confirm)
        buttons.addWidget(cancel_button)
        buttons.addStretch()
        buttons.addWidget(confirm_button)
        layout.addLayout(buttons)

        self.resize(440, 260)

    def _on_confirm(self) -> None:
        self.close()
        self.confirmed.emit()


class WizardStepPanel(Screen):
    """Colonne gauche du mode assisté en cours (§5 mode assisté), une
    étape à la fois -- remplace `HomeScreen` dans `MainView` pendant le
    parcours guidé. Deux jeux de boutons mutuellement exclusifs :
    Continuer (normal, activé seulement quand l'étape est prête) et
    Reprendre/Mode expert (uniquement après une erreur, §5 : « le parcours
    s'arrête... et propose de reprendre ou de passer en mode expert »).
    Annuler reste toujours visible -- `main_window.py` décide de ce
    qu'annuler signifie concrètement (annuler le job en cours, revenir à
    l'accueil assisté)."""

    continue_requested = Signal()
    cancel_requested = Signal()
    resume_requested = Signal()
    expert_mode_requested = Signal()
    refresh_requested = Signal()
    # État « opération terminée, propose la suite » (§4.3, sauvegarde
    # système depuis l'accueil assisté) -- signaux dédiés, jamais
    # continue_requested/cancel_requested : ceux-ci restent câblés à des
    # gestionnaires qui supposent un parcours guidé réellement actif
    # (`_on_wizard_continue`/`_cancel_wizard`), à ne jamais déclencher pour
    # une opération ponctuelle hors parcours.
    prepare_card_requested = Signal()
    return_to_home_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._title_label = QLabel()
        self._title_label.setProperty("role", "title")
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        self._instruction_label = QLabel()
        self._instruction_label.setWordWrap(True)
        layout.addWidget(self._instruction_label)

        self._status_label = QLabel()
        self._status_label.setProperty("role", "secondary")
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        # Étapes 1/4 (détection) uniquement -- relance la recherche
        # manuellement quand le sondage automatique n'aboutit pas, comme
        # le bouton équivalent du mode expert (§5 mode assisté).
        self._refresh_button = QPushButton(tr("home_refresh"))
        self._refresh_button.setVisible(False)
        self._refresh_button.clicked.connect(self.refresh_requested.emit)
        layout.addWidget(self._refresh_button)

        layout.addStretch()

        self._continue_button = QPushButton(tr("wizard_continue"))
        self._continue_button.setProperty("role", "primary")
        self._continue_button.clicked.connect(self.continue_requested.emit)
        layout.addWidget(self._continue_button)

        self._resume_button = QPushButton(tr("wizard_resume"))
        self._resume_button.setProperty("role", "primary")
        self._resume_button.setVisible(False)
        self._resume_button.clicked.connect(self.resume_requested.emit)
        layout.addWidget(self._resume_button)

        self._expert_button = QPushButton(tr("assisted_expert_mode_button"))
        self._expert_button.setVisible(False)
        self._expert_button.clicked.connect(self.expert_mode_requested.emit)
        layout.addWidget(self._expert_button)

        self._cancel_button = QPushButton(tr("wizard_cancel"))
        self._cancel_button.setProperty("role", "flat")
        self._cancel_button.clicked.connect(self.cancel_requested.emit)
        layout.addWidget(self._cancel_button)

        # État « opération terminée, propose la suite » (§4.3) -- boutons
        # dédiés, masqués par défaut (voir show_next_step_choice).
        self._prepare_card_button = QPushButton(tr("assisted_prepare_card_button"))
        self._prepare_card_button.setProperty("role", "primary")
        self._prepare_card_button.setVisible(False)
        self._prepare_card_button.clicked.connect(self.prepare_card_requested.emit)
        layout.addWidget(self._prepare_card_button)

        self._return_home_button = QPushButton(tr("assisted_return_home_button"))
        self._return_home_button.setVisible(False)
        self._return_home_button.clicked.connect(self.return_to_home_requested.emit)
        layout.addWidget(self._return_home_button)

    def show_step(
        self,
        title: str,
        instruction: str,
        status: str = "",
        *,
        can_continue: bool = False,
        show_refresh: bool = False,
    ) -> None:
        """Affiche une nouvelle étape -- revient toujours à l'état normal
        (Continuer), même si l'étape précédente était en erreur.
        `show_refresh` : étapes 1/4 (détection) uniquement."""
        self._title_label.setText(title)
        self._instruction_label.setText(instruction)
        self._status_label.setText(status)
        self._status_label.setVisible(bool(status))
        self._continue_button.setVisible(True)
        self._continue_button.setEnabled(can_continue)
        self._resume_button.setVisible(False)
        self._expert_button.setVisible(False)
        self._refresh_button.setVisible(show_refresh)
        self._prepare_card_button.setVisible(False)
        self._return_home_button.setVisible(False)

    def set_status(self, status: str) -> None:
        self._status_label.setText(status)
        self._status_label.setVisible(bool(status))

    def set_can_continue(self, enabled: bool) -> None:
        self._continue_button.setEnabled(enabled)

    def show_error(self) -> None:
        """Le message d'erreur lui-même vit dans le journal de bord
        (`LogPanel.finish_error`, §5) -- ce panneau ne montre que les deux
        actions possibles ensuite."""
        self._continue_button.setVisible(False)
        self._resume_button.setVisible(True)
        self._expert_button.setVisible(True)
        self._prepare_card_button.setVisible(False)
        self._return_home_button.setVisible(False)

    def show_next_step_choice(self, title: str, instruction: str, *, show_prepare_card: bool = True) -> None:
        """État « opération terminée, propose la suite » (§4.3, sauvegarde
        système lancée depuis l'accueil assisté) -- jamais un écran sans
        issue une fois l'opération terminée. Aucun des boutons du vrai
        parcours guidé (Continuer/Reprendre/Mode expert/Actualiser/Annuler)
        n'est affiché : ceux-ci restent câblés à des gestionnaires qui
        supposent un parcours réellement actif, jamais à déclencher pour
        une opération ponctuelle hors parcours. `show_prepare_card=False`
        après un échec -- rien à préparer, seul le retour a du sens."""
        self._title_label.setText(title)
        self._instruction_label.setText(instruction)
        self._status_label.setVisible(False)
        self._continue_button.setVisible(False)
        self._resume_button.setVisible(False)
        self._expert_button.setVisible(False)
        self._refresh_button.setVisible(False)
        self._cancel_button.setVisible(False)
        self._prepare_card_button.setVisible(show_prepare_card)
        self._return_home_button.setVisible(True)
