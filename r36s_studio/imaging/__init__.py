"""Lecture brute d'un périphérique — phase 2. Aucune écriture sur un
périphérique n'est implémentée ici (voir §7 : l'écriture, phase 3, ne doit
commencer que la détection/sécurité irréprochables)."""

from __future__ import annotations

from .backup import backup_device, compute_backup_size
from .copy import BLOCK_SIZE, ProgressCallback, ProgressEvent, copy_range
from .mbr import MbrPartition, is_gpt_protective, last_used_byte, parse_mbr
from .source import prepared_source, raw_read_path

__all__ = [
    "backup_device",
    "compute_backup_size",
    "BLOCK_SIZE",
    "ProgressCallback",
    "ProgressEvent",
    "copy_range",
    "MbrPartition",
    "is_gpt_protective",
    "last_used_byte",
    "parse_mbr",
    "prepared_source",
    "raw_read_path",
]
