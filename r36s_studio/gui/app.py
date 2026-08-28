"""Point d'entrée de la GUI : `python -m r36s_studio gui`."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from . import theme
from .main_window import MainWindow


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme.STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec()
