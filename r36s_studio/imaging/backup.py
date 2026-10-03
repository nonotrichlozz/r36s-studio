# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Orchestration de la sauvegarde : lit un périphérique jusqu'à la fin de
sa dernière partition utile et l'écrit dans un fichier. Phase 2 — aucune
écriture sur un périphérique, uniquement lecture vers un fichier."""

from __future__ import annotations

from typing import Optional

from r36s_studio.devices import Device

from .copy import BLOCK_SIZE, CancelCheck, ProgressCallback, copy_range
from .mbr import SECTOR_SIZE, last_used_byte
from .source import prepared_source


def compute_backup_size(source_path: str, device_size_bytes: int) -> int:
    """Lit le premier secteur de `source_path` et retourne le nombre
    d'octets à sauvegarder : fin de la dernière partition MBR utilisée, ou
    la taille totale du périphérique si la table est illisible ou GPT
    (« sauvegarde intelligente », §4.3)."""
    with open(source_path, "rb") as f:
        first_sector = f.read(SECTOR_SIZE)
    try:
        return last_used_byte(first_sector, device_size_bytes)
    except ValueError:
        return device_size_bytes


def backup_device(
    device: Device,
    output_path: str,
    on_progress: Optional[ProgressCallback] = None,
    block_size: int = BLOCK_SIZE,
    should_cancel: Optional[CancelCheck] = None,
) -> int:
    """Sauvegarde `device` (lecture seule) dans le fichier `output_path`.
    Retourne le nombre d'octets copiés. Lève `OperationCancelled` si
    `should_cancel` répond True en cours de copie (écran Exécution, §5)."""
    with prepared_source(device.path) as raw_path:
        total = compute_backup_size(raw_path, device.size_bytes)
        with open(raw_path, "rb") as source, open(output_path, "wb") as destination:
            return copy_range(
                source,
                destination,
                total,
                on_progress=on_progress,
                block_size=block_size,
                should_cancel=should_cancel,
            )
