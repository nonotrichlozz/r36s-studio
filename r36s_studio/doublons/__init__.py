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

"""Outil « Doublons de jeux » (docs/doublons.md) -- package autonome,
sans dépendance vers `partitions/`/`devices/` : analyse et déplacement de
doublons sur n'importe quel dossier déjà accessible (PC, carte SD montée,
disque externe), jamais un accès brut à un périphérique -- aucune
élévation de privilèges n'est donc jamais nécessaire ici."""

from __future__ import annotations

from .extensions import ROM_EXTENSIONS, ExtensionKind, classify
from .linked_files import LinkedResolution, resolve_manifest
from .move import (
    CopyVerificationFailed,
    DestinationInsideRootNotAllowed,
    DestinationIsFilesystemRoot,
    DestinationNotWritable,
    DuplicatesOutsideRoot,
    InsufficientDiskSpace,
    MoveCancelled,
    MoveProgressCallback,
    check_destination_allowed,
    default_destination,
    free_space_at_destination,
    has_pending_journal_entries,
    is_cross_volume_destination,
    move_duplicates,
)
from .normalize import extract_tags, normalize_title, priority_score, region_rank, revision_score
from .report import build_report
from .safety import LARGE_FOLDER_FILE_THRESHOLD, is_filesystem_root, is_whole_user_folder
from .scan import (
    DUPLICATES_DIR_NAME,
    ExactDuplicateGroup,
    ExclusionWarning,
    HashCache,
    HashCacheEntry,
    OperationCancelled,
    ScanResult,
    Unit,
    VersionGroup,
    find_duplicates,
)
from .scan_cache import (
    CachedScan,
    default_cache_dir,
    default_hash_cache_path,
    find_most_recent_scan_cache,
    load_hash_cache,
    load_scan_cache,
    save_hash_cache,
    save_scan_cache,
    scan_cache_path_for_root,
    verify_scan_cache,
)
from .undo import UndoConflict, UndoResult, undo_all

__all__ = [
    "ROM_EXTENSIONS",
    "ExtensionKind",
    "classify",
    "LinkedResolution",
    "resolve_manifest",
    "extract_tags",
    "normalize_title",
    "priority_score",
    "region_rank",
    "revision_score",
    "LARGE_FOLDER_FILE_THRESHOLD",
    "is_filesystem_root",
    "is_whole_user_folder",
    "DUPLICATES_DIR_NAME",
    "Unit",
    "ExclusionWarning",
    "ExactDuplicateGroup",
    "VersionGroup",
    "ScanResult",
    "OperationCancelled",
    "HashCache",
    "HashCacheEntry",
    "find_duplicates",
    "CachedScan",
    "default_cache_dir",
    "default_hash_cache_path",
    "scan_cache_path_for_root",
    "save_scan_cache",
    "load_scan_cache",
    "find_most_recent_scan_cache",
    "load_hash_cache",
    "save_hash_cache",
    "verify_scan_cache",
    "MoveProgressCallback",
    "MoveCancelled",
    "DestinationNotWritable",
    "InsufficientDiskSpace",
    "DestinationInsideRootNotAllowed",
    "DestinationIsFilesystemRoot",
    "CopyVerificationFailed",
    "DuplicatesOutsideRoot",
    "default_destination",
    "check_destination_allowed",
    "is_cross_volume_destination",
    "free_space_at_destination",
    "move_duplicates",
    "has_pending_journal_entries",
    "UndoConflict",
    "UndoResult",
    "undo_all",
    "build_report",
]
