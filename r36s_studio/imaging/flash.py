"""Orchestration de l'écriture disque (§4.3, §4.6) : décompresse
`image_path` à la volée et l'écrit sur `device`, puis vérifie le SHA-256
en relisant la carte. La confirmation utilisateur (règle §2 n°6) est de la
responsabilité de l'appelant (CLI/GUI) — ce module écrit dès qu'on le lui
demande, sans redemander confirmation lui-même."""

from __future__ import annotations

import hashlib
import platform
from dataclasses import dataclass
from typing import Optional

from r36s_studio.devices import Device

from .copy import BLOCK_SIZE, ProgressCallback, copy_range
from .image_source import estimate_total_bytes, open_image_source
from .write_target import WINDOWS_SECTOR_SIZE, prepared_write_target

HASH_CHUNK_SIZE = 4 * 1024 * 1024


@dataclass
class FlashResult:
    bytes_written: int
    source_sha256: str
    written_sha256: str
    verified: bool


class _HashingReader:
    """Enveloppe un flux binaire et calcule son SHA-256 au fil de la
    lecture, sans avoir à le relire ensuite."""

    def __init__(self, stream):
        self._stream = stream
        self._digest = hashlib.sha256()

    def read(self, n: int = -1) -> bytes:
        chunk = self._stream.read(n)
        self._digest.update(chunk)
        return chunk

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def _hash_file_range(path: str, num_bytes: int, chunk_size: int = HASH_CHUNK_SIZE) -> str:
    digest = hashlib.sha256()
    remaining = num_bytes
    with open(path, "rb") as f:
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            digest.update(chunk)
            remaining -= len(chunk)
    return digest.hexdigest()


def flash_device(
    device: Device,
    image_path: str,
    on_progress: Optional[ProgressCallback] = None,
    block_size: int = BLOCK_SIZE,
) -> FlashResult:
    """Écrit `image_path` (`.img`, `.img.gz` ou `.img.xz`) sur `device`,
    puis relit ce qui a été écrit et compare son SHA-256 à celui de la
    source. Lève `ValueError`/`OSError` en cas d'échec ; ne lève jamais en
    cas de désaccord de hash — c'est `FlashResult.verified` qui le porte,
    pour laisser l'appelant décider quoi en faire."""
    total_hint = estimate_total_bytes(image_path)
    sector_size = WINDOWS_SECTOR_SIZE if platform.system() == "Windows" else None

    with prepared_write_target(device) as raw_path:
        with open_image_source(image_path) as raw_source, open(raw_path, "r+b") as destination:
            hashing_source = _HashingReader(raw_source)
            written = copy_range(
                hashing_source,
                destination,
                total_bytes=total_hint,
                on_progress=on_progress,
                block_size=block_size,
                sector_size=sector_size,
            )
        source_sha256 = hashing_source.hexdigest()
        written_sha256 = _hash_file_range(raw_path, written)

    return FlashResult(
        bytes_written=written,
        source_sha256=source_sha256,
        written_sha256=written_sha256,
        verified=(written_sha256 == source_sha256),
    )
