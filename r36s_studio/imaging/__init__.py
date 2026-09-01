"""Lecture et écriture brutes d'un périphérique — phases 2 et 3.

Toute écriture disque passe par `flash_device()`, jamais directement par
`copy_range()` : c'est `write_target.prepared_write_target()` qui applique
les spécificités par OS du §4.3 (démontage/verrouillage) avant d'ouvrir le
périphérique."""

from __future__ import annotations

from .backup import backup_device, compute_backup_size
from .copy import BLOCK_SIZE, CancelCheck, OperationCancelled, ProgressCallback, ProgressEvent, copy_range
from .flash import FlashResult, flash_device
from .image_source import (
    SevenZipArchiveError,
    UnsupportedImageFormatError,
    check_image_format,
    estimate_total_bytes,
    open_image_source,
)
from .mbr import MbrPartition, is_gpt_protective, last_used_byte, parse_mbr
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
]
