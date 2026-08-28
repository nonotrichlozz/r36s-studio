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

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QParallelAnimationGroup,
    QPointF,
    QPropertyAnimation,
    QRect,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from r36s_studio.detect import StepStatus
from r36s_studio.devices import Device
from r36s_studio.partitions.archives import parse_archive_timestamp

from . import asset_paths, build_info, theme
from .reveal import reveal_label
from .strings import tr

_STATUS_TEXT_KEYS = {
    StepStatus.AVAILABLE: "status_available",
    StepStatus.DONE: "status_done",
    StepStatus.NOT_RELEVANT: "status_not_relevant",
    StepStatus.PLATFORM_LIMITED: "status_platform_limited",
}

# Couleur du badge (theme.py, sélecteur QSS `QLabel[badgeKind="..."]`) pour
# chaque statut -- distinct de `_STATUS_TEXT_KEYS` (le texte affiché).
_BADGE_KIND_BY_STATUS = {
    StepStatus.AVAILABLE: "available",
    StepStatus.DONE: "done",
    StepStatus.NOT_RELEVANT: "not_relevant",
    StepStatus.PLATFORM_LIMITED: "platform_limited",
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
    environ 70 %, avec une légère flottaison verticale. Le halo cyan qui
    l'entoure (§5) est peint séparément par `ConsoleHalo`, pas ici --
    voir la note de performance sur `ConsoleStage`. Peinte au `QPainter`
    plutôt qu'affichée via `QLabel.setPixmap`, avec l'opacité appliquée
    directement dans `paintEvent` (`painter.setOpacity`). Absente sans
    lever d'exception si le fichier n'existe pas (`build_console_stage`
    retourne alors None) -- l'interface s'affiche normalement sans elle
    (§5).

    Le seul état qui change en continu (`floatOffset`, animé par
    `ConsoleStage`) ne déclenche plus lui-même de repeint (pas de
    `self.update()` dans son setter) : `ConsoleStage` en impose un, à
    fréquence limitée, pour tous ses widgets enfants d'un coup (§5,
    correctif de performance -- voir sa docstring)."""

    _OPACITY = 0.70

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self._source_pixmap = pixmap
        self._scaled_pixmap = QPixmap()
        self._float_offset = 0.0
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def _get_float_offset(self) -> float:
        return self._float_offset

    def _set_float_offset(self, value: float) -> None:
        self._float_offset = value

    # Propriété Qt (pas un simple attribut Python) : `QPropertyAnimation`
    # a besoin d'un `Property` déclaré au niveau de la classe pour animer
    # `floatOffset` par son nom (`b"floatOffset"`, voir `ConsoleStage`).
    floatOffset = Property(float, _get_float_offset, _set_float_offset)

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
        y = (self.height() - self._scaled_pixmap.height()) / 2 + self._float_offset
        painter.setOpacity(self._OPACITY)
        painter.drawPixmap(int(x), int(y), self._scaled_pixmap)

    def rendered_size(self):
        """Taille réelle de l'image affichée (après mise à l'échelle avec
        conservation du ratio) -- `ConsoleStage` s'en sert pour placer le
        socle lumineux exactement sous la console, pas sous tout le
        widget (bien plus grand, il occupe toute la zone du haut)."""
        return self._scaled_pixmap.size()


class _RadialGlowWidget(QWidget):
    """Base commune à `ConsoleBasePlate` et `ConsoleHalo` : une ellipse en
    dégradé radial cyan -> transparent, dont seule l'*opacité* s'anime.

    Correctif de performance (§5) : le dégradé n'est reconstruit qu'une
    fois par changement de taille (`resizeEvent`), dans un `QPixmap` mis
    en cache -- jamais à chaque frame. `paintEvent` se contente d'un
    `drawPixmap` suivi de `painter.setOpacity`, le calcul le plus léger
    possible pour Qt. C'est aussi ce qui a remplacé l'ancien halo en
    `QGraphicsDropShadowEffect` (voir `ConsoleHalo`) : un effet Qt recalcule
    son flou gaussien à chaque repeint du widget source, quel que soit son
    rayon -- largement plus coûteux qu'un `drawPixmap`, et la cause du
    saccadement observé en pratique, la flottaison de la console changeant
    justement son apparence en continu."""

    _MIN_OPACITY: float = 0.0
    _MAX_OPACITY: float = 1.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacity = self._MIN_OPACITY
        self._pixmap = QPixmap()
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def _get_glow_opacity(self) -> float:
        return self._opacity

    def _set_glow_opacity(self, value: float) -> None:
        # Pas de self.update() ici : `ConsoleStage` impose un seul repeint
        # groupé, à fréquence limitée, pour tous ses widgets enfants (§5).
        self._opacity = value

    glowOpacity = Property(float, _get_glow_opacity, _set_glow_opacity)

    def resizeEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        super().resizeEvent(event)
        self._pixmap = self._render_pixmap(self.size())

    @staticmethod
    def _render_pixmap(size) -> QPixmap:
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        if size.width() <= 0 or size.height() <= 0:
            return pixmap
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = pixmap.rect()
        # Technique classique pour un dégradé radial elliptique (Qt n'a
        # qu'un rayon unique) : mettre à l'échelle le repère pour que
        # l'ellipse voulue devienne un cercle unité, puis y peindre un
        # dégradé radial défini dans ce même repère mis à l'échelle.
        # L'opacité pleine (alpha 255) est peinte ici, une fois pour
        # toutes -- l'opacité *animée* est appliquée au tracé du pixmap
        # (`paintEvent`), jamais en reconstruisant ce dégradé.
        painter.translate(rect.center())
        painter.scale(max(rect.width(), 1) / 2, max(rect.height(), 1) / 2)
        cyan = QColor(theme.ACCENT_CYAN)
        transparent = QColor(theme.ACCENT_CYAN)
        transparent.setAlpha(0)
        gradient = QRadialGradient(QPointF(0, 0), 1)
        gradient.setColorAt(0.0, cyan)
        gradient.setColorAt(1.0, transparent)
        painter.setPen(Qt.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(0, 0), 1, 1)
        painter.end()
        return pixmap

    def paintEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        if self._pixmap.isNull() or self._opacity <= 0.0:
            return
        painter = QPainter(self)
        painter.setOpacity(self._opacity)
        painter.drawPixmap(0, 0, self._pixmap)


class ConsoleBasePlate(_RadialGlowWidget):
    """Socle lumineux sous la console (§5) : une ellipse aplatie en
    dégradé radial cyan -> transparent. Son opacité (propriété Qt
    `glowOpacity`, animée par `ConsoleStage`) pulse doucement entre 25 %
    et 55 %."""

    _MIN_OPACITY = 0.25
    _MAX_OPACITY = 0.55

    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacity = self._MIN_OPACITY


class ConsoleHalo(_RadialGlowWidget):
    """Lueur cyan diffuse autour de la console (§5) -- remplace l'ancien
    `QGraphicsDropShadowEffect` posé sur `ConsoleArt` : voir la docstring
    de `_RadialGlowWidget` pour la raison (coût du flou gaussien recalculé
    à chaque frame). Une ellipse plus large que la console, centrée
    derrière elle, dont seule l'opacité pulse (entre 15 % et 38 %) plutôt
    qu'un rayon de flou -- même effet visuel de lueur, sans recalcul."""

    _MIN_OPACITY = 0.15
    _MAX_OPACITY = 0.38

    def __init__(self, parent=None):
        super().__init__(parent)
        self._opacity = self._MIN_OPACITY


class ConsoleStage(QWidget):
    """Zone du haut de la colonne droite (§5) : la console (`ConsoleArt`)
    devant son halo (`ConsoleHalo`) et son socle lumineux
    (`ConsoleBasePlate`), plus une légère flottaison verticale de la
    console -- trois animations permanentes, décalées entre elles pour ne
    jamais respirer à l'unisson, regroupées dans un seul
    `QParallelAnimationGroup` en boucle infinie pour un pilotage
    centralisé (`pause`/`resume`/`set_animations_enabled`).
    `QEasingCurve.InOutSine` partout : une respiration, pas un mouvement
    mécanique.

    Chaque animation garde son propre cycle (le socle et le halo n'ont pas
    la même durée) ; le groupe sert à les démarrer/mettre en pause/arrêter
    ensemble en un seul appel -- pas à les synchroniser sur un cycle
    commun, ce qui contredirait justement le "jamais à l'unisson" demandé.
    Mises en pause pendant une opération disque (le journal de bord suffit
    alors comme signal d'activité, pas la peine de faire tourner ceci pour
    rien) et désactivables via un réglage utilisateur -- dans les deux cas,
    retour à l'état de repos plutôt qu'un arrêt figé sur une valeur
    intermédiaire arbitraire.

    **Correctif de performance (constaté en pratique : l'animation
    saccadait fortement).** `QPropertyAnimation` met à jour ses valeurs à
    la fréquence de son minuteur interne (proche du taux de
    rafraîchissement de l'écran) -- bien plus souvent que nécessaire pour
    une respiration lente sur plusieurs secondes, et chaque valeur mise à
    jour appelait jusqu'ici `update()` sur le widget concerné. Les
    widgets enfants (`ConsoleArt`, `ConsoleBasePlate`, `ConsoleHalo`) ne
    déclenchent donc plus eux-mêmes de repeint dans leurs setters de
    propriété : `_repaint_timer`, un simple `QTimer` cadencé à 33 ms
    (~30 images/seconde, largement suffisant pour l'œil sur ce genre de
    mouvement), impose un unique repeint groupé par tick, limité au plus
    petit rectangle couvrant la console, son halo et son socle
    (`_console_update_rect`, recalculé dans `resizeEvent` -- pas
    `self.rect()`, sensiblement plus grand que ce qui est réellement
    visible) -- jamais toute la fenêtre. Le minuteur ne tourne que pendant
    que le groupe d'animations tourne réellement (démarré dans
    `resume()`/`__init__`, arrêté dans `pause()` et à la désactivation) :
    à l'arrêt, aucun repeint périodique, donc aucun coût."""

    _PLATE_CYCLE_MS = 3000
    _GLOW_CYCLE_MS = 4000
    _FLOAT_AMPLITUDE = 6.0
    _FLOAT_CYCLE_MS = 6000
    _REPAINT_INTERVAL_MS = 33  # ~30 im/s -- voir la docstring de la classe

    def __init__(self, console_art: ConsoleArt, parent=None):
        super().__init__(parent)
        self._enabled = True
        self._console_art = console_art
        self._console_art.setParent(self)
        self._halo = ConsoleHalo(self)
        self._base_plate = ConsoleBasePlate(self)
        self._halo.lower()
        self._base_plate.lower()
        self._console_update_rect = QRect()

        self._group = QParallelAnimationGroup(self)

        self._plate_animation = QPropertyAnimation(self._base_plate, b"glowOpacity", self)
        self._plate_animation.setDuration(self._PLATE_CYCLE_MS)
        self._plate_animation.setLoopCount(-1)
        self._plate_animation.setEasingCurve(QEasingCurve.InOutSine)
        self._plate_animation.setKeyValueAt(0.0, ConsoleBasePlate._MIN_OPACITY)
        self._plate_animation.setKeyValueAt(0.5, ConsoleBasePlate._MAX_OPACITY)
        self._plate_animation.setKeyValueAt(1.0, ConsoleBasePlate._MIN_OPACITY)

        self._glow_animation = QPropertyAnimation(self._halo, b"glowOpacity", self)
        self._glow_animation.setDuration(self._GLOW_CYCLE_MS)
        self._glow_animation.setLoopCount(-1)
        self._glow_animation.setEasingCurve(QEasingCurve.InOutSine)
        self._glow_animation.setKeyValueAt(0.0, ConsoleHalo._MIN_OPACITY)
        self._glow_animation.setKeyValueAt(0.5, ConsoleHalo._MAX_OPACITY)
        self._glow_animation.setKeyValueAt(1.0, ConsoleHalo._MIN_OPACITY)

        self._float_animation = QPropertyAnimation(self._console_art, b"floatOffset", self)
        self._float_animation.setDuration(self._FLOAT_CYCLE_MS)
        self._float_animation.setLoopCount(-1)
        self._float_animation.setEasingCurve(QEasingCurve.InOutSine)
        self._float_animation.setKeyValueAt(0.0, -self._FLOAT_AMPLITUDE)
        self._float_animation.setKeyValueAt(0.5, self._FLOAT_AMPLITUDE)
        self._float_animation.setKeyValueAt(1.0, -self._FLOAT_AMPLITUDE)

        self._group.addAnimation(self._plate_animation)
        self._group.addAnimation(self._glow_animation)
        self._group.addAnimation(self._float_animation)
        self._group.setLoopCount(-1)

        self._repaint_timer = QTimer(self)
        self._repaint_timer.setInterval(self._REPAINT_INTERVAL_MS)
        self._repaint_timer.timeout.connect(self._repaint_console_area)

        self._group.start()
        # Décale le halo par rapport au socle (§5 : "pour éviter que les
        # deux respirent à l'unisson") -- au-delà de la simple différence
        # de période (3 s contre 4 s, qui les désynchronise déjà tout
        # seule au fil du temps), un déphasage explicite dès le départ
        # évite qu'ils démarrent malgré tout en phase.
        self._glow_animation.setCurrentTime(self._GLOW_CYCLE_MS // 2)
        self._repaint_timer.start()

    def _repaint_console_area(self) -> None:
        self.update(self._console_update_rect)

    def resizeEvent(self, event) -> None:  # noqa: N802 (nom imposé par Qt)
        super().resizeEvent(event)
        self._console_art.setGeometry(self.rect())
        rendered = self._console_art.rendered_size()
        art_width = rendered.width() or int(self.width() * 0.6)
        # `ConsoleArt.paintEvent` centre toujours l'image verticalement
        # dans son propre rect (qui couvre `self`, voir ligne ci-dessus) :
        # ce centre est donc toujours exact, jamais une valeur de repli --
        # seule sa taille dépend de `rendered`, pas encore connue lors du
        # tout premier passage de layout.
        art_center_y = self.height() // 2
        art_bottom = (self.height() + rendered.height()) // 2 if rendered.height() else self.height()

        plate_width = max(20, int(art_width * 0.7))
        plate_height = max(10, int(plate_width * 0.22))
        plate_x = (self.width() - plate_width) // 2
        plate_y = art_bottom - plate_height // 2
        self._base_plate.setGeometry(plate_x, plate_y, plate_width, plate_height)

        # Halo (§5) : une ellipse plus large que la console rendue,
        # centrée derrière elle -- remplace la zone que couvrait
        # auparavant le flou du QGraphicsDropShadowEffect.
        art_height = rendered.height() or int(self.height() * 0.6)
        halo_width = max(20, int(art_width * 1.35))
        halo_height = max(20, int(art_height * 1.35))
        halo_x = (self.width() - halo_width) // 2
        halo_y = art_center_y - halo_height // 2
        halo_rect = QRect(halo_x, halo_y, halo_width, halo_height)
        self._halo.setGeometry(halo_rect)

        # Rectangle d'invalidation du minuteur de repeint (§5, correctif de
        # performance) : la console (élargie de l'amplitude de la
        # flottaison, ±6 px, dans les deux sens) unie au halo et au socle --
        # nettement plus petit que `self.rect()`, qui couvre toute la zone
        # du haut de la colonne droite, marges vides comprises.
        art_rect = QRect(
            (self.width() - art_width) // 2,
            int(art_center_y - art_height / 2 - self._FLOAT_AMPLITUDE),
            art_width,
            int(art_height + 2 * self._FLOAT_AMPLITUDE),
        )
        self._console_update_rect = art_rect.united(halo_rect).united(self._base_plate.geometry())

    def pause(self) -> None:
        if self._group.state() == QParallelAnimationGroup.Running:
            self._group.pause()
        self._repaint_timer.stop()

    def resume(self) -> None:
        if not self._enabled:
            return
        if self._group.state() == QParallelAnimationGroup.Paused:
            self._group.resume()
        elif self._group.state() != QParallelAnimationGroup.Running:
            self._group.start()
        self._repaint_timer.start()

    def set_animations_enabled(self, enabled: bool) -> None:
        """Réglage utilisateur (§5) : à la désactivation, retombe sur
        l'état de repos (socle au minimum, halo au minimum, pas de
        flottaison) plutôt que de figer une valeur intermédiaire
        arbitraire en plein milieu d'un cycle."""
        self._enabled = enabled
        if enabled:
            self.resume()
        else:
            self._group.stop()
            self._repaint_timer.stop()
            self._base_plate.glowOpacity = ConsoleBasePlate._MIN_OPACITY
            self._halo.glowOpacity = ConsoleHalo._MIN_OPACITY
            self._console_art.floatOffset = 0.0
            # Le minuteur périodique est arrêté : sans ce repeint explicite,
            # le dernier état visible resterait celui d'avant la
            # désactivation jusqu'au prochain événement Qt fortuit.
            self.update(self.rect())


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
    refresh_requested = Signal()
    help_requested = Signal()
    assisted_mode_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

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
        for row in self._tiles.values():
            row.setEnabled(not busy)
        self._backup_row.setEnabled(not busy)

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

    def set_status(self, status: Dict[str, StepStatus], device: Optional[Device] = None) -> None:
        """`status` (voir `detect.detect_workflow_status`) annote chaque
        ligne d'un badge de statut — jamais de ligne masquée ni désactivée
        par ceci (voir `set_busy` pour la seule désactivation prévue) :
        une étape absente du dict (détection pas encore lancée) n'affiche
        simplement aucun badge. `device`, quand fourni, alimente le
        bandeau carte détectée en haut de la colonne (modèle, taille,
        état reconnu)."""
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


_FILE_TITLE_KEYS = {
    "backup": "file_title_backup",
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
    month = _FRENCH_MONTHS[timestamp.month - 1]
    return f"{timestamp.day} {month} {timestamp.year} à {timestamp.hour:02d}h{timestamp.minute:02d}"


class FileDialog(Dialog):
    """Choix du fichier (§5, refonte navigation -- fenêtre modale à la
    place d'un écran séparé) : fichier de sortie pour la sauvegarde, image
    source pour le flash, un dossier de destination pour l'extraction du
    BOOT/EASYROMS (§4.4, étapes A/B — un emplacement par défaut est
    proposé, jamais imposé), ou — pour l'injection sur la carte neuve
    (étapes D/E) — une sauvegarde parmi celles déjà extraites, avec un
    repli « Parcourir… » pour une source manuelle."""

    file_chosen = Signal(str)
    releases_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "backup"

        layout = QVBoxLayout(self)
        self._title = QLabel()
        self._title.setProperty("role", "title")
        layout.addWidget(self._title)

        # Flash uniquement (§5 mode assisté, étape 5) -- l'image n'est pas
        # hébergée sur GitHub (Mega/Google Drive/OneDrive/torrent), donc
        # rien à automatiser au-delà de l'ouverture de cette page.
        self._releases_button = QPushButton(tr("file_releases_button"))
        self._releases_button.clicked.connect(self.releases_requested.emit)
        layout.addWidget(self._releases_button)

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
        self, mode: str, archive_choices: Optional[List] = None, default_path: Optional[str] = None
    ) -> None:
        """`mode` : "backup" (choisir où enregistrer), "flash" (choisir
        l'image source), "extract_boot"/"extract_easyroms" (choisir un
        dossier de destination — `default_path` le pré-remplit, toujours
        remplaçable via Parcourir), ou "inject_boot"/"copy_games" (choisir
        une sauvegarde parmi `archive_choices`, ou en désigner une autre
        via Parcourir)."""
        self._mode = mode
        self._title.setText(tr(_FILE_TITLE_KEYS[mode]))
        self.setWindowTitle(tr(_FILE_TITLE_KEYS[mode]))
        self._path_label.setText(default_path or "")
        self._next_button.setEnabled(bool(default_path))
        self._releases_button.setVisible(mode == "flash")

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

    def _on_archive_selected(self) -> None:
        items = self._archive_list.selectedItems()
        if items:
            self._path_label.setText(items[0].data(Qt.UserRole))
            self._next_button.setEnabled(True)

    def _browse(self) -> None:
        title = tr(_FILE_TITLE_KEYS[self._mode])
        if self._mode == "backup":
            path, _ = QFileDialog.getSaveFileName(self, title, "", "Image (*.img)")
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


_OPERATION_TITLE_KEYS = {
    "backup": "execute_title_backup",
    "flash": "execute_title_flash",
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
            # Réglage utilisateur (§5) : désactive les trois animations de
            # la console -- pas persisté d'une session à l'autre pour
            # l'instant (pas de module de configuration dans le projet à
            # ce stade, §6), comme le réglage équivalent qu'il remplace.
            self.animation_toggle = QCheckBox(tr("console_animation_toggle"))
            self.animation_toggle.setChecked(True)
            self.animation_toggle.toggled.connect(console_stage.set_animations_enabled)
            right_column.addWidget(self.animation_toggle)
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


class AssistedLandingScreen(Screen):
    """Écran d'accueil du mode assisté (§5 mode assisté) -- par défaut au
    lancement (`ui_mode` en configuration, §6). Sa propre `ConsoleStage`
    (instance séparée de celle de `MainView`, plus grande, mêmes effets
    lumineux) plutôt qu'une réutilisation : les deux écrans ne sont jamais
    affichés en même temps (`MainWindow` bascule entre eux), donc pas de
    conflit de parent, et chacun reste autonome/testable isolément."""

    prepare_requested = Signal()
    expert_mode_requested = Signal()

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

        root.addStretch(3)

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

    def show_step(self, title: str, instruction: str, status: str = "", *, can_continue: bool = False) -> None:
        """Affiche une nouvelle étape -- revient toujours à l'état normal
        (Continuer), même si l'étape précédente était en erreur."""
        self._title_label.setText(title)
        self._instruction_label.setText(instruction)
        self._status_label.setText(status)
        self._status_label.setVisible(bool(status))
        self._continue_button.setVisible(True)
        self._continue_button.setEnabled(can_continue)
        self._resume_button.setVisible(False)
        self._expert_button.setVisible(False)

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
