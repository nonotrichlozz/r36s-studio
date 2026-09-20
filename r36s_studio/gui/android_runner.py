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

"""Threads Qt pour l'outil « Console Android » (étape 1, docs/android-
adb.md) -- fichier séparé des autres runners (`partition_runner.py`,
`doublons_runner.py`, `consoles_diverses/search_runner.py`) : domaine
indépendant, aucune dépendance vers `Device`/`imaging`/`partitions`. Le
brief interdit toute commande adb qui modifie le système -- aucune
élévation de privilèges n'est donc jamais nécessaire ici, contrairement à
`partition_runner.py`/`worker_runner.py`.

Toutes les commandes adb passent par ces threads dédiés (brief, §
Interface : "l'interface ne gèle jamais, délai maximal par commande")."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from r36s_studio.android import adb, platform_tools


class AndroidDetectRunner(QThread):
    """Un aller-retour `adb devices -l` (+ `getprop` si un appareil est
    prêt) sur un thread séparé -- même piège que n'importe quel appel
    bloquant sur le thread Qt principal (`consoles_diverses/search_runner.
    py`, `gui/partition_runner.py`)."""

    finished_detect = Signal(object)  # android.models.DetectionResult

    def __init__(self, adb_path, parent=None):
        super().__init__(parent)
        self._adb_path = adb_path

    def run(self) -> None:
        result = adb.detect_connected_device(self._adb_path)
        self.finished_detect.emit(result)


class AndroidPlatformToolsSizeRunner(QThread):
    """Taille annoncée par Google pour les platform-tools (requête `HEAD`),
    affichée sur l'écran de consentement avant tout téléchargement (brief :
    "afficher l'URL et la taille") -- sur un thread séparé comme tout
    aller-retour réseau de ce projet."""

    finished_size = Signal(object)  # Optional[int]

    def run(self) -> None:
        size = platform_tools.fetch_platform_tools_size()
        self.finished_size.emit(size)


class AndroidPlatformToolsDownloadRunner(QThread):
    """Téléchargement + extraction des platform-tools, après accord
    explicite de l'utilisateur -- progression réelle (règle §2 n°5 du
    CLAUDE.md racine), même famille que `gui/partition_runner.py::
    RocknixDownloadRunner`."""

    progress = Signal("qint64", "qint64")  # done, total
    error = Signal(str, str)  # code, msg
    finished_download = Signal(bool, str)  # ok, chemin adb ("" si échec)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancelled = False

    def cancel(self) -> None:
        """Coopératif, comme les autres runners de ce projet -- consulté
        par `platform_tools.download_and_install` avant chaque bloc."""
        self._cancelled = True

    def run(self) -> None:
        def on_progress(done: int, total: int) -> None:
            self.progress.emit(done, total)

        try:
            adb_path = platform_tools.download_and_install(
                on_progress=on_progress, should_cancel=lambda: self._cancelled
            )
        except platform_tools.PlatformToolsDownloadCancelledError as exc:
            self.error.emit("CANCELLED", str(exc))
            self.finished_download.emit(False, "")
            return
        except platform_tools.PlatformToolsError as exc:
            self.error.emit("PLATFORM_TOOLS_ERROR", str(exc))
            self.finished_download.emit(False, "")
            return
        self.finished_download.emit(True, str(adb_path))


__all__ = ["AndroidDetectRunner", "AndroidPlatformToolsSizeRunner", "AndroidPlatformToolsDownloadRunner"]
