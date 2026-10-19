# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

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

from r36s_studio.android import adb, knulli, platform_tools


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


class KnulliPlanRunner(QThread):
    """Aperçu de la copie vers une console KNULLI (`android/knulli.py`) :
    systèmes lus sur la console, rangement du dossier choisi, fichiers
    déjà présents et place libre."""

    finished_plan = Signal(object)  # knulli.CopyPlan
    error = Signal(str)  # détail brut, pour le journal

    def __init__(self, adb_path: str, serial: str, root: str, parent=None):
        super().__init__(parent)
        self._adb_path, self._serial, self._root = adb_path, serial, root

    def run(self) -> None:
        try:
            systems = knulli.read_systems(self._adb_path, self._serial)
            plan = knulli.build_copy_plan(self._root, systems)
            existing = knulli.read_existing(self._adb_path, self._serial, knulli.plan_folders(plan))
            knulli.attach_console_state(plan, existing, knulli.read_free_bytes(self._adb_path, self._serial))
        except (adb.AdbCommandError, OSError) as exc:
            self.error.emit(str(exc))
            return
        self.finished_plan.emit(plan)


class KnulliCopyRunner(QThread):
    """Copie fichier par fichier, progression réelle en octets, puis
    rafraîchissement de la liste des jeux si aucun jeu ne tourne."""

    progress = Signal("qint64", "qint64", str)  # done, total, fichier en cours
    finished_copy = Signal(object, str)  # knulli.CopyResult, état du rafraîchissement
    not_enough_space = Signal("qint64", "qint64")  # nécessaire, libre
    error = Signal(str)

    def __init__(self, adb_path: str, serial: str, plan, parent=None):
        super().__init__(parent)
        self._adb_path, self._serial, self._plan = adb_path, serial, plan
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            result = knulli.copy_plan(
                self._adb_path,
                self._serial,
                self._plan,
                on_progress=self.progress.emit,
                should_cancel=lambda: self._cancelled,
            )
        except knulli.NotEnoughSpace as exc:
            self.not_enough_space.emit(exc.needed, exc.free)
            return
        except (adb.AdbCommandError, OSError) as exc:
            self.error.emit(str(exc))
            return
        reload_status = knulli.reload_games_if_idle(self._adb_path, self._serial) if result.copied else "nothing_copied"
        self.finished_copy.emit(result, reload_status)


__all__ = [
    "AndroidDetectRunner",
    "AndroidPlatformToolsSizeRunner",
    "AndroidPlatformToolsDownloadRunner",
    "KnulliPlanRunner",
    "KnulliCopyRunner",
]
