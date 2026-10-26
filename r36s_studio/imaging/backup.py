# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Orchestration de la sauvegarde : lit un périphérique jusqu'à la fin de
sa dernière partition utile et l'écrit dans un fichier. Phase 2 — aucune
écriture sur un périphérique, uniquement lecture vers un fichier."""

from __future__ import annotations

from typing import List, Optional

from r36s_studio.devices import Device

from .copy import BLOCK_SIZE, CancelCheck, ProgressCallback, copy_range
from .mbr import SECTOR_SIZE, last_used_byte
from .source import DEFAULT_STALL_TIMEOUT_SECONDS, StallCallback, StallWatchedReader, prepared_source
from .source_verify import SourceUnstable, quarantine_unstable_image, verify_source, write_block_digests


def compute_backup_size(
    source_path: str,
    device_size_bytes: int,
    stall_timeout: float = DEFAULT_STALL_TIMEOUT_SECONDS,
    on_stall: Optional[StallCallback] = None,
    should_cancel: Optional[CancelCheck] = None,
) -> int:
    """Lit le premier secteur de `source_path` et retourne le nombre
    d'octets à sauvegarder : fin de la dernière partition MBR utilisée, ou
    la taille totale du périphérique si la table est illisible ou GPT
    (« sauvegarde intelligente », §4.3). Lecture surveillée comme la
    copie : la carte de l'incident peut bloquer dès le premier secteur."""
    with StallWatchedReader(open(source_path, "rb"), stall_timeout, on_stall, should_cancel) as f:
        first_sector = f.read(SECTOR_SIZE)
    try:
        return last_used_byte(first_sector, device_size_bytes)
    except ValueError:
        return device_size_bytes


def estimate_full_backup_size(device: Device, stall_timeout: float = DEFAULT_STALL_TIMEOUT_SECONDS) -> int:
    """Taille exacte d'une sauvegarde complète (`compute_backup_size`,
    sauvegarde intelligente : fin de la dernière partition MBR utilisée,
    toute la carte en GPT). Accès brut : à appeler élevé (worker)."""
    with prepared_source(device.path) as raw_path:
        return compute_backup_size(raw_path, device.size_bytes, stall_timeout)


def required_free_bytes(image_bytes: int, block_size: int = BLOCK_SIZE) -> int:
    """Place nécessaire pour une sauvegarde de `image_bytes` : l'image
    (jamais compressée : `.img` brut) plus son `.sha256blocks` (une ligne
    de 65 octets par bloc, plus l'en-tête)."""
    blocks = -(-image_bytes // block_size)
    return image_bytes + 65 * blocks + SECTOR_SIZE


def backup_device(
    device: Device,
    output_path: str,
    on_progress: Optional[ProgressCallback] = None,
    block_size: int = BLOCK_SIZE,
    should_cancel: Optional[CancelCheck] = None,
    double_read: bool = True,
    stall_timeout: float = DEFAULT_STALL_TIMEOUT_SECONDS,
    on_stall: Optional[StallCallback] = None,
) -> int:
    """Sauvegarde `device` (lecture seule) dans le fichier `output_path`.
    Retourne le nombre d'octets copiés. Lève `OperationCancelled` si
    `should_cancel` répond True en cours de copie ou de relecture (écran
    Exécution, §5).

    `double_read` (défaut, `config.json::verify_backup_source`) : relit
    toute la source après la copie et lève `SourceUnstable` si un bloc
    n'est pas relu à l'identique (`source_verify.py`) -- l'image est alors
    renommée en `.instable`, jamais supprimée. Écrit toujours
    `<image>.sha256blocks` en cas de succès : le fichier produit est
    exactement les octets lus, les empreintes de la copie suffisent.

    Chien de garde (`source.StallWatchedReader`) : lève
    `SourceNotResponding` si la carte ne renvoie plus rien pendant
    `stall_timeout` secondes, `on_stall` signale l'attente avant."""
    digests: List[str] = []
    with prepared_source(device.path) as raw_path:
        total = compute_backup_size(raw_path, device.size_bytes, stall_timeout, on_stall, should_cancel)
        try:
            with StallWatchedReader(open(raw_path, "rb"), stall_timeout, on_stall, should_cancel) as source, open(
                output_path, "wb"
            ) as destination:
                copied = copy_range(
                    source,
                    destination,
                    total,
                    on_progress=on_progress,
                    block_size=block_size,
                    should_cancel=should_cancel,
                    block_digests=digests,
                )
                if double_read:
                    verify_source(source, digests, copied, block_size, on_progress, should_cancel)
        except SourceUnstable as exc:
            exc.image_path = quarantine_unstable_image(output_path, exc.ranges)
            raise
    write_block_digests(output_path, digests, block_size, copied)
    return copied
