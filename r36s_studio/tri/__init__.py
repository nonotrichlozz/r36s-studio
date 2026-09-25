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

"""Outil « Ranger mes jeux » (docs/tri-roms.md) -- répartit un dossier de
ROMs mélangées dans des sous-dossiers par système, nommés comme le
firmware cible les attend. Package autonome, sans Qt ni accès brut à un
périphérique (même principe que `doublons/`) : aucune élévation."""

from __future__ import annotations

from .apply import ApplyResult, apply_plan, has_journal, journal_path, undo_sort
from .identify import Identification, identify_bytes, identify_file
from .plan import (
    SORT_JOURNAL_FILENAME,
    UNIDENTIFIED_DIR_NAME,
    PlannedMove,
    SortCancelled,
    SortPlan,
    SortRootRefused,
    TooManyFiles,
    build_plan,
)
from .tables import SORT_FIRMWARE_IDS, FirmwareFolders, SystemInfo, load_firmware_tables, load_systems

__all__ = [
    "ApplyResult",
    "FirmwareFolders",
    "Identification",
    "PlannedMove",
    "SORT_FIRMWARE_IDS",
    "SORT_JOURNAL_FILENAME",
    "SortCancelled",
    "SortPlan",
    "SortRootRefused",
    "SystemInfo",
    "TooManyFiles",
    "UNIDENTIFIED_DIR_NAME",
    "apply_plan",
    "build_plan",
    "has_journal",
    "identify_bytes",
    "identify_file",
    "journal_path",
    "load_firmware_tables",
    "load_systems",
    "undo_sort",
]
