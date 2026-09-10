# R36S Studio
# Copyright (C) 2026 nonotrichlozz
#
# Ce fichier fait partie de R36S Studio. R36S Studio est un logiciel libre :
# vous pouvez le redistribuer et/ou le modifier selon les termes de la GNU
# General Public License telle que publiée par la Free Software Foundation,
# version 3 de la licence.
#
# R36S Studio est distribué dans l'espoir qu'il sera utile, mais SANS
# AUCUNE GARANTIE ; sans même la garantie implicite de QUALITÉ MARCHANDE ou
# d'ADÉQUATION À UN USAGE PARTICULIER. Consultez la GNU General Public
# License pour plus de détails.
#
# Vous devez avoir reçu une copie de la GNU General Public License avec
# R36S Studio. Si ce n'est pas le cas, consultez <https://www.gnu.org/licenses/>.

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
