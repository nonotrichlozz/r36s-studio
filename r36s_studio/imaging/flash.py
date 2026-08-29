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

from .copy import BLOCK_SIZE, CancelCheck, ProgressCallback, copy_range
from .image_source import check_image_format, estimate_total_bytes, open_image_source
from .write_target import WINDOWS_SECTOR_SIZE, prepared_write_target, reunmount_before_verify

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


def _hash_stream_range(stream, num_bytes: int, chunk_size: int = HASH_CHUNK_SIZE) -> str:
    """Relit `num_bytes` depuis `stream` pour la vérification, en le
    repositionnant au début (`seek(0)`) plutôt que de rouvrir le chemin par
    lequel il a été ouvert. Bug corrigé, constaté sur du vrai matériel :
    refermer le descripteur d'écriture puis rouvrir le même chemin pour
    relire laisse une fenêtre, même brève, pendant laquelle macOS peut
    remonter automatiquement le disque fraîchement écrit et y écrire des
    fichiers d'index (Spotlight, fseventsd) — invalidant les octets qu'on
    s'apprête à relire (comparaison octet par octet confirmée : les
    divergences tombent exactement dans la zone FAT de la première
    partition). Garder le même descripteur ouvert entre l'écriture et
    cette relecture (`flash_device`) referme cette fenêtre ;
    `write_target.reunmount_before_verify` reste un filet de sécurité en
    plus, pour le cas où une partition individuelle se monterait
    indépendamment du périphérique brut."""
    stream.seek(0)
    digest = hashlib.sha256()
    remaining = num_bytes
    while remaining > 0:
        chunk = stream.read(min(chunk_size, remaining))
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
    should_cancel: Optional[CancelCheck] = None,
) -> FlashResult:
    """Écrit `image_path` (`.img`, `.img.gz` ou `.img.xz`) sur `device`,
    puis relit ce qui a été écrit et compare son SHA-256 à celui de la
    source. Lève `ValueError`/`OSError` en cas d'échec ; ne lève jamais en
    cas de désaccord de hash — c'est `FlashResult.verified` qui le porte,
    pour laisser l'appelant décider quoi en faire. Lève `OperationCancelled`
    si `should_cancel` répond True en cours d'écriture — dans ce cas,
    aucune vérification SHA-256 n'est faite sur une carte partiellement
    écrite. Lève `SevenZipArchiveError`/`UnsupportedImageFormatError`
    (`check_image_format`, appelé en tout premier ici -- avant
    `prepared_write_target`) si `image_path` n'est pas une image flashable :
    ne jamais démonter/préparer la carte pour une source qu'on sait déjà
    inutilisable (règle §2 n°6)."""
    check_image_format(image_path)
    total_hint = estimate_total_bytes(image_path)
    if total_hint is None:
        # Pied d'archive illisible (fichier tronqué, format non standard) :
        # repli sur la taille du périphérique cible plutôt que de traiter la
        # copie comme non bornée (bug corrigé : sans ce repli, la barre de
        # progression affichait 100 % dès le premier octet écrit — voir
        # `copy_range`, qui rapporte `done` comme `total` quand aucune borne
        # n'est connue).
        total_hint = device.size_bytes or None
    sector_size = WINDOWS_SECTOR_SIZE if platform.system() == "Windows" else None

    with prepared_write_target(device) as raw_path:
        # `destination` reste ouvert jusqu'à la fin de la vérification --
        # voir la note sur `_hash_stream_range` : un descripteur d'écriture
        # tenu ouvert sur le périphérique brut referme la fenêtre pendant
        # laquelle macOS pourrait remonter automatiquement le disque entre
        # la fin de l'écriture et la relecture. `raw_source` (l'image
        # source), lui, n'est plus utile une fois la copie terminée.
        with open(raw_path, "r+b") as destination:
            with open_image_source(image_path) as raw_source:
                hashing_source = _HashingReader(raw_source)
                written = copy_range(
                    hashing_source,
                    destination,
                    total_bytes=total_hint,
                    on_progress=on_progress,
                    block_size=block_size,
                    sector_size=sector_size,
                    should_cancel=should_cancel,
                )
            source_sha256 = hashing_source.hexdigest()
            # Bug corrigé, constaté sur du vrai matériel : macOS peut
            # remonter automatiquement les partitions fraîchement écrites
            # (table de partitions désormais valide) et y écrire aussitôt
            # des fichiers d'index (Spotlight, fseventsd) qui invalident la
            # vérification -- voir `write_target.reunmount_before_verify`.
            # Démonter une seule fois avant l'écriture
            # (`prepared_write_target`) ne suffit pas ; garder `destination`
            # ouvert (ci-dessus) non plus à lui seul, une partition pouvant
            # se monter indépendamment du périphérique brut -- les deux
            # mesures se complètent.
            reunmount_before_verify(device)
            written_sha256 = _hash_stream_range(destination, written)

    return FlashResult(
        bytes_written=written,
        source_sha256=source_sha256,
        written_sha256=written_sha256,
        verified=(written_sha256 == source_sha256),
    )
