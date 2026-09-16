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


__all__ = ["ConsoleSearchRunner"]
