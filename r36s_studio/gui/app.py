# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Point d'entrée de la GUI : `python -m r36s_studio gui`."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QSplashScreen

from r36s_studio import config as app_config
from r36s_studio import i18n

from . import theme
from .main_window import MainWindow
from .strings import tr


def _build_splash() -> QSplashScreen:
    """Écran de démarrage affiché *avant* la construction de `MainWindow`.

    Le constructeur de `MainWindow` détecte la carte de façon synchrone
    (`_refresh_home_state`, PowerShell `Get-Disk`/`Get-Partition` sous
    Windows) : mesuré à ~20 s sur une vraie machine Windows avant que la
    moindre fenêtre n'apparaisse -- un débutant en conclut que l'app ne se
    lance pas et double-clique à nouveau. Ce splash donne un retour visuel
    immédiat sans toucher à l'ordre d'initialisation de `MainWindow`.
    Dessiné au `QPainter` (aucune image requise), mêmes couleurs que
    `theme.py`."""
    pixmap = QPixmap(420, 160)
    pixmap.fill(QColor(theme.BG_DARK))
    painter = QPainter(pixmap)
    painter.setPen(QPen(QColor(theme.BORDER_CYAN), 2))
    painter.drawRoundedRect(1, 1, 418, 158, 10, 10)
    font = painter.font()
    font.setPointSize(18)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(theme.TEXT_PRIMARY))
    painter.drawText(pixmap.rect().adjusted(0, 30, 0, -70), Qt.AlignCenter, tr("app_title"))
    font.setPointSize(10)
    font.setBold(False)
    painter.setFont(font)
    painter.setPen(QColor(theme.ACCENT_CYAN))
    painter.drawText(pixmap.rect().adjusted(0, 95, 0, -25), Qt.AlignCenter, tr("splash_starting"))
    painter.end()
    return QSplashScreen(pixmap)


def run() -> int:
    # Avant le premier widget, écran d'attente compris : chaque écran lit
    # `tr()` à sa construction (i18n.py).
    i18n.set_language(app_config.load_config().language)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme.STYLESHEET)
    splash = _build_splash()
    splash.show()
    app.processEvents()
    window = MainWindow()
    window.show()
    window.start_update_check()
    splash.finish(window)
    return app.exec()
