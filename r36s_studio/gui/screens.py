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
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from r36s_studio.detect import StepStatus
from r36s_studio.devices import Device
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
    avec le reste de l'habillage sans dépendance externe."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(28, 28)

    def paintEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.ACCENT_CYAN))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        body = self.rect().adjusted(2, 5, -2, -5)
        painter.drawRoundedRect(body, 4, 4)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.ACCENT_CYAN))
        for dx in (8, 13):
            painter.drawEllipse(body.right() - dx, body.center().y() - 2, 3, 3)


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
        title_row.addWidget(title)
        title_row.addStretch()
        self._assisted_mode_button = QPushButton(tr("home_assisted_mode_button"))
        self._assisted_mode_button.setProperty("role", "flat")
        self._assisted_mode_button.clicked.connect(self.assisted_mode_requested.emit)
        title_row.addWidget(self._assisted_mode_button)
        layout.addLayout(title_row)

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
            layout.addWidget(row)

        separator = QLabel(tr("home_backup_separator"))
        separator.setProperty("role", "secondary")
        layout.addWidget(separator)
        self._backup_row, backup_badge = self._build_row(
            "◆", tr("home_tile_backup"), tr("home_tile_backup_desc"), self.backup_selected
        )
        backup_badge.setVisible(False)  # jamais de badge de statut pour la sauvegarde (§5)
        layout.addWidget(self._backup_row)
        self._backup_system_row, backup_system_badge = self._build_row(
            "◆",
            tr("home_tile_backup_system"),
            tr("home_tile_backup_system_desc"),
            self.backup_system_selected,
        )
        backup_system_badge.setVisible(False)  # jamais de badge de statut pour la sauvegarde (§5)
        layout.addWidget(self._backup_system_row)
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
        layout.addWidget(self._reset_card_row)

        layout.addStretch()

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
        self, status: Dict[str, StepStatus], device: Optional[Device] = None, has_device: Optional[bool] = None
    ) -> None:
        """`status` (voir `detect.detect_workflow_status`) annote chaque
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
            badge.setText(tr(_STATUS_TEXT_KEYS[step_status]))
            badge.setProperty("badgeKind", _BADGE_KIND_BY_STATUS[step_status])
            theme.repolish(badge)
            badge.setVisible(True)

        if has_device is not None:
            self._has_device = has_device
            self._update_backup_rows_enabled()

        self._update_banner(status, device)

    def _update_banner(self, status: Dict[str, StepStatus], device: Optional[Device]) -> None:
        if device is None:
            self._banner_device_label.setText(tr("home_banner_state_none"))
            self._banner_state_label.setText("")
            return
        size_go = device.size_bytes / 1_000_000_000
        self._banner_device_label.setText(tr("home_banner_line_device", display=device.display, size_go=size_go))
        # Le flash marqué "déjà faite" est le seul signal fiable déjà
        # calculé par `detect_workflow_status` pour "cette carte est déjà
        # ArkOS" -- pas besoin d'exposer `is_arkos` séparément.
        is_arkos = status.get("flash") == StepStatus.DONE
        state_key = "home_banner_state_arkos" if is_arkos else "home_banner_state_unprepared"
        self._banner_state_label.setText(tr(state_key))


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
            size_go = device.size_bytes / 1_000_000_000
            item = QListWidgetItem(f"{device.display} — {size_go:.1f} Go — {device.bus}")
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

_FRENCH_MONTHS = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]  # fmt: skip


def format_datetime_label(timestamp) -> str:
    """Date/heure conviviale (§5, pas de jargon) -- ex. « 6 juillet 2026 à
    00h21 » -- réutilisée par `format_archive_label` (nom d'un dossier
    d'archive horodaté) et `ArchiveReuseDialog` (date d'une sauvegarde déjà
    mémorisée dans la configuration, §5 mode assisté)."""
    month = _FRENCH_MONTHS[timestamp.month - 1]
    return f"{timestamp.day} {month} {timestamp.year} à {timestamp.hour:02d}h{timestamp.minute:02d}"


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
            layout.addWidget(row)

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
        size_go = device.size_bytes / 1_000_000_000
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
        size_go = device.size_bytes / 1_000_000_000 if device.size_bytes else 0.0
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
    choisit l'étiquette du volume avant la fenêtre Confirmation
    obligatoire (§2 n°6, ouverte ensuite par l'appelant). `set_default_
    label` pré-remplit une valeur simple à chaque ouverture -- jamais
    imposée, toujours remplaçable, même principe que les chemins par
    défaut proposés ailleurs dans ce projet (§4.4)."""

    label_chosen = Signal(str)

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

        self.resize(420, 220)

    def set_default_label(self, label: str) -> None:
        self._label_edit.setText(label)

    def _on_continue(self) -> None:
        label = self._label_edit.text().strip()
        if not label:
            return
        self.close()
        self.label_chosen.emit(label)


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
        self._header_label.setText(tr("log_header_idle"))
        self._bar.setVisible(False)
        self._speed_label.setVisible(False)
        self._eta_label.setVisible(False)
        self._cancel_button.setVisible(False)
        self._eject_button.setVisible(False)
        self._reveal_button.setVisible(False)

    def start_operation(self, title: str) -> None:
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

    # --- fin d'opération : résultat affiché dans le journal, pas un écran -

    def finish_success(self, message: str, allow_eject: bool, reveal_path: Optional[str]) -> None:
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
    for unit in ("o", "Ko", "Mo", "Go"):
        if size < 1024 or unit == "Go":
            return f"{int(size)} {unit}" if unit == "o" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} To"


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


class AssistedLandingScreen(Screen):
    """Écran d'accueil du mode assisté (§5 mode assisté) -- par défaut au
    lancement (`ui_mode` en configuration, §6). Sa propre `ConsoleStage`
    (instance séparée de celle de `MainView`, plus grande, mêmes effets
    lumineux) plutôt qu'une réutilisation : les deux écrans ne sont jamais
    affichés en même temps (`MainWindow` bascule entre eux), donc pas de
    conflit de parent, et chacun reste autonome/testable isolément."""

    prepare_requested = Signal()
    expert_mode_requested = Signal()
    backup_system_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self._backdrop = build_window_backdrop(self)
        if self._backdrop is not None:
            self._backdrop.lower()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 24)

        top_row = QHBoxLayout()
        top_row.addStretch()
        self._expert_button = QPushButton(tr("assisted_expert_mode_button"))
        self._expert_button.setProperty("role", "flat")
        self._expert_button.clicked.connect(self.expert_mode_requested.emit)
        top_row.addWidget(self._expert_button)
        root.addLayout(top_row)

        root.addStretch(2)

        self.console_stage = build_console_stage(self)
        if self.console_stage is not None:
            root.addWidget(self.console_stage, 5)

        self._prepare_button = QPushButton(tr("assisted_prepare_button"))
        self._prepare_button.setProperty("role", "cta")
        self._prepare_button.clicked.connect(self.prepare_requested.emit)
        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(self._prepare_button)
        button_row.addStretch()
        root.addLayout(button_row)

        # Sauvegarde système sans les jeux (§4.3), aussi proposée comme
        # option du mode assisté -- discrète (rôle "flat", comme le bouton
        # Mode expert), en dessous du bouton principal, pour ne jamais
        # rivaliser avec le parcours guidé qui reste l'action mise en avant.
        self._backup_system_button = QPushButton(tr("assisted_backup_system_button"))
        self._backup_system_button.setProperty("role", "flat")
        self._backup_system_button.clicked.connect(self.backup_system_requested.emit)
        backup_system_row = QHBoxLayout()
        backup_system_row.addStretch()
        backup_system_row.addWidget(self._backup_system_button)
        backup_system_row.addStretch()
        root.addLayout(backup_system_row)

        root.addStretch(3)

    def set_busy(self, busy: bool) -> None:
        """Changer de mode en plein flash ou en pleine copie laisserait un
        job orphelin (§5 mode assisté) -- même garde que
        `HomeScreen.set_busy`, sur le bouton symétrique. Landing n'est en
        pratique jamais visible pendant une opération en cours (l'écran
        bascule vers `MainView` dès qu'une opération démarre), mais reste
        gardé défensivement -- notamment la brève fenêtre entre une
        annulation coopérative et l'arrêt effectif du job."""
        self._expert_button.setEnabled(not busy)
        self._backup_system_button.setEnabled(not busy)

    def resizeEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        super().resizeEvent(event)
        if self._backdrop is not None:
            self._backdrop.setGeometry(self.rect())


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
