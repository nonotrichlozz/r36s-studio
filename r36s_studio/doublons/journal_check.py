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

"""Vérification du journal de déplacement (`move.py::JOURNAL_FILENAME`)
contre l'état réel du disque -- signalé explicitement : « donne-moi une
commande pour comparer le journal avec ce qui existe réellement à la
source et à destination, pour vérifier qu'aucun fichier n'a été perdu ».

Commande : `python -m r36s_studio doublons-verify-journal --destination
CHEMIN` (`__main__.py::cmd_doublons_verify_journal`).

Pour chaque entrée du journal (`{source, destination, moved_at}`), quatre
issues possibles selon ce qui existe *réellement* aujourd'hui :

- **`MOVED`** -- destination présente, source absente : état normal après
  un déplacement réussi, rien à signaler.
- **`RESTORED`** -- destination absente, source présente : cohérent avec
  un « Tout annuler » (`undo.py`) déjà passé par là.
- **`LOST`** -- ni l'une ni l'autre n'existe : le cas que cette commande
  sert justement à détecter, un fichier disparu des deux côtés.
- **`DUPLICATED`** -- les deux existent : une copie laissée derrière
  (interruption, bug), pas une perte mais une incohérence à nettoyer.

Lecture seule, jamais un `os.stat` sur un périphérique brut ni une
élévation -- les mêmes chemins que ceux déjà consultés/écrits par
`move.py`/`undo.py`."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from .move import JOURNAL_FILENAME, _read_journal

__all__ = ["JournalCheckEntry", "JournalCheckReport", "verify_journal"]


@dataclass
class JournalCheckEntry:
    source: str
    destination: str
    moved_at: str
    status: str  # "MOVED" | "RESTORED" | "LOST" | "DUPLICATED"


@dataclass
class JournalCheckReport:
    destination: str
    entries: List[JournalCheckEntry] = field(default_factory=list)

    @property
    def lost(self) -> List[JournalCheckEntry]:
        return [entry for entry in self.entries if entry.status == "LOST"]

    @property
    def duplicated(self) -> List[JournalCheckEntry]:
        return [entry for entry in self.entries if entry.status == "DUPLICATED"]

    @property
    def ok(self) -> bool:
        """Faux dès qu'au moins un fichier est réellement perdu -- une
        entrée `DUPLICATED` n'en fait pas partie (rien de perdu, juste
        une copie de trop à nettoyer à la main)."""
        return not self.lost


def _status_for(source_exists: bool, destination_exists: bool) -> str:
    if destination_exists and not source_exists:
        return "MOVED"
    if source_exists and not destination_exists:
        return "RESTORED"
    if not source_exists and not destination_exists:
        return "LOST"
    return "DUPLICATED"


def verify_journal(destination: str) -> JournalCheckReport:
    """Relit `journal.json` dans `destination` (comme `move.py`/`undo.py`)
    et classe chaque entrée -- jamais une exception : un journal absent ou
    corrompu donne simplement un rapport vide (`_read_journal`, déjà
    tolérant, réutilisé tel quel)."""
    journal_path = Path(destination).resolve() / JOURNAL_FILENAME
    report = JournalCheckReport(destination=str(Path(destination).resolve()))
    for raw in _read_journal(journal_path):
        source = raw.get("source", "")
        dest = raw.get("destination", "")
        moved_at = raw.get("moved_at", "")
        status = _status_for(Path(source).exists(), Path(dest).exists())
        report.entries.append(JournalCheckEntry(source=source, destination=dest, moved_at=moved_at, status=status))
    return report
