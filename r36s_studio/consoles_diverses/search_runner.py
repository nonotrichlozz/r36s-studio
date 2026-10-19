# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Thread dédié pour `client.py::rechercher_console` -- un aller-retour
réseau bloquant sur le thread Qt principal se lirait comme un gel de
l'interface (même principe que `gui/partition_runner.py::RocknixListRunner`,
dont ce module reprend le contrat). Fichier séparé de
`gui/partition_runner.py` plutôt qu'un ajout à ce module existant :
domaine indépendant (§CLAUDE.md du package, règle d'isolation)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QThread, Signal

from .client import Opener, RechercheErreur, rechercher_console
from .telechargement import Telechargement


class ConsoleSearchRunner(QThread):
    """Lance `rechercher_console` sur un thread séparé. Capture toute
    exception -- `RechercheErreur` comme n'importe quelle autre -- et la
    remonte via `error`, jamais en la laissant traverser le thread."""

    finished_ok = Signal(object)  # ResultatRecherche
    error = Signal(str, str)  # code, message_serveur (jamais None -- "" si absent)

    def __init__(
        self,
        reference: str,
        server_url: str,
        licence_key: str,
        opener: Optional[Opener] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._reference = reference
        self._server_url = server_url
        self._licence_key = licence_key
        self._opener = opener

    def run(self) -> None:
        try:
            if self._opener is not None:
                resultat = rechercher_console(
                    self._reference, self._server_url, self._licence_key, opener=self._opener
                )
            else:
                resultat = rechercher_console(self._reference, self._server_url, self._licence_key)
        except RechercheErreur as exc:
            self.error.emit(exc.code, exc.message_serveur or "")
            return
        except Exception as exc:  # filet -- jamais d'exception qui traverse le thread
            self.error.emit("erreur_inattendue", str(exc))
            return
        self.finished_ok.emit(resultat)


class FirmwareResolveRunner(QThread):
    """Lance `telechargement.py::resoudre` (appel à l'API GitHub) sur un
    thread séparé -- même principe que `ConsoleSearchRunner`. Ne
    télécharge rien : le fichier trouvé est remonté à `MainWindow`, qui
    enchaîne sur le téléchargement puis la fenêtre Confirmation."""

    resolved = Signal(object)  # FichierFirmware
    error = Signal(str, str)  # code, détail

    def __init__(self, telechargement: Telechargement, opener=None, parent=None):
        super().__init__(parent)
        self._telechargement = telechargement
        self._opener = opener

    def run(self) -> None:
        # Import local : `identify/firmware_download.py` importe ce paquet
        # (`telechargement.py`), jamais l'inverse au chargement.
        from r36s_studio.identify.firmware_download import resolve_firmware

        outcome = resolve_firmware(self._telechargement, opener=self._opener)
        if outcome.error_code is not None:
            self.error.emit(outcome.error_code, outcome.error_detail)
            return
        self.resolved.emit(outcome.fichier)


__all__ = ["ConsoleSearchRunner", "FirmwareResolveRunner"]
