# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Lecture et écriture brutes d'un périphérique — phases 2 et 3.

Toute écriture disque passe par `flash_device()`, jamais directement par
`copy_range()` : c'est `write_target.prepared_write_target()` qui applique
les spécificités par OS du §4.3 (démontage/verrouillage) avant d'ouvrir le
périphérique."""

from __future__ import annotations

from .backup import backup_device, compute_backup_size
from .copy import BLOCK_SIZE, CancelCheck, OperationCancelled, ProgressCallback, ProgressEvent, copy_range
from .flash import FlashResult, flash_device
from .games_partition import (
    GAMES_PARTITION_LABEL,
    GAMES_PARTITION_WORTHWHILE_BYTES,
    MIN_GAMES_PARTITION_BYTES,
    GamesPartitionResult,
    NoFreeMbrSlot,
    NoFreeSpaceForGamesPartition,
    create_and_format_games_partition,
    create_and_format_games_partition_if_worthwhile,
    format_games_partition,
)
from .image_source import (
    SevenZipArchiveError,
    UnsupportedImageFormatError,
    check_image_format,
    estimate_total_bytes,
    open_image_source,
)
from .mbr import MbrPartition, is_gpt_protective, last_used_byte, parse_mbr
from .reset_card import (
    DEFAULT_RESET_LABEL,
    CardTooSmallForReset,
    check_fat32_feasible,
    create_single_partition,
    erase_partition_table,
    format_reset_partition,
)
from .source import prepared_source, raw_read_path
from .system_backup import (
    GamesPartitionNotFound,
    backup_system_only,
    estimate_system_backup_size,
    estimate_system_backup_size_unprivileged,
)
from .write_target import prepared_write_target

__all__ = [
    "backup_device",
    "compute_backup_size",
    "BLOCK_SIZE",
    "CancelCheck",
    "OperationCancelled",
    "ProgressCallback",
    "ProgressEvent",
    "copy_range",
    "FlashResult",
    "flash_device",
    "estimate_total_bytes",
    "open_image_source",
    "check_image_format",
    "UnsupportedImageFormatError",
    "SevenZipArchiveError",
    "MbrPartition",
    "is_gpt_protective",
    "last_used_byte",
    "parse_mbr",
    "prepared_source",
    "raw_read_path",
    "GamesPartitionNotFound",
    "backup_system_only",
    "estimate_system_backup_size",
    "estimate_system_backup_size_unprivileged",
    "prepared_write_target",
    "GAMES_PARTITION_LABEL",
    "GAMES_PARTITION_WORTHWHILE_BYTES",
    "MIN_GAMES_PARTITION_BYTES",
    "GamesPartitionResult",
    "NoFreeMbrSlot",
    "NoFreeSpaceForGamesPartition",
    "create_and_format_games_partition",
    "create_and_format_games_partition_if_worthwhile",
    "format_games_partition",
    "DEFAULT_RESET_LABEL",
    "CardTooSmallForReset",
    "check_fat32_feasible",
    "erase_partition_table",
    "create_single_partition",
    "format_reset_partition",
]
