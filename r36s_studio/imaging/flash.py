# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Orchestration de l'écriture disque (§4.3, §4.6) : décompresse
`image_path` à la volée et l'écrit sur `device`, puis vérifie le SHA-256
en relisant la carte. La confirmation utilisateur (règle §2 n°6) est de la
responsabilité de l'appelant (CLI/GUI) — ce module écrit dès qu'on le lui
demande, sans redemander confirmation lui-même."""

from __future__ import annotations

import hashlib
import os
import platform
import time
from dataclasses import dataclass
from typing import Callable, Optional

from r36s_studio.devices import Device

from .copy import BLOCK_SIZE, CancelCheck, ProgressCallback, ProgressEvent, copy_range
from .image_source import check_image_format, estimate_total_bytes, is_unstable_image, open_image_source
from .source_verify import check_image_digests, check_sidecar_matches_size
from .write_target import WINDOWS_SECTOR_SIZE, prepared_write_target, reunmount_before_verify

HASH_CHUNK_SIZE = 4 * 1024 * 1024

# Début de l'image (table de partitions MBR + GPT primaire, et de la marge)
# écrit EN DERNIER, après tout le reste -- voir `_write_deferred_head` et
# docs/bugs-imaging-io.md (« [Errno 9] Bad file descriptor », cause
# identifiée le 11/10/2026, correctif à confirmer sur du vrai matériel).
# 1 Mio : multiple de tout secteur, couvre le MBR (secteur 0), l'en-tête
# GPT (secteur 1) et ses 128 entrées (secteurs 2-33).
DEFERRED_HEAD_BYTES = 1024 * 1024

# Fin de la carte remise à zéro avant d'écrire la table de partitions --
# voir `_wipe_stale_tail` : une table GPT de secours laissée par un ancien
# système (ArkOS, EmuELEC, une autre carte...) empêche ROCKNIX d'agrandir sa
# partition de stockage au premier démarrage.
TAIL_WIPE_BYTES = 1024 * 1024

# Windows seulement : délai avant de relire le début de la carte sur une
# poignée neuve, si Windows a révoqué la poignée d'écriture juste après
# l'écriture de la table (`_read_back_head`).
WINDOWS_REMOUNT_SETTLE_SECONDS = 2.0


class UnstableImageRefused(Exception):
    """Image `.img.instable` (sauvegarde d'une carte source instable) sans
    autorisation explicite (`allow_unstable`, mode expert seulement)."""


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


def _read_up_to(stream, num_bytes: int) -> bytes:
    """Lit jusqu'à `num_bytes` (moins seulement si la source s'épuise) --
    un flux décompressé (`gzip`/`lzma`) peut renvoyer moins que demandé
    sans être terminé."""
    parts = []
    remaining = num_bytes
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            break
        parts.append(chunk)
        remaining -= len(chunk)
    return b"".join(parts)


def _pad_to_sector(data: bytes, sector_size: Optional[int]) -> bytes:
    if sector_size and len(data) % sector_size != 0:
        return data + b"\x00" * (sector_size - len(data) % sector_size)
    return data


def _offset_progress(on_progress: Optional[ProgressCallback], offset: int) -> Optional[ProgressCallback]:
    """La copie du corps de l'image commence après `DEFERRED_HEAD_BYTES` :
    on décale ses événements pour que la barre reflète toujours l'image
    entière (règle §2 n°5, progression réelle) -- le début, déjà lu, est
    compté comme fait."""
    if on_progress is None or offset == 0:
        return on_progress

    def _shifted(event: ProgressEvent) -> None:
        on_progress(
            ProgressEvent(
                done=event.done + offset,
                total=event.total + offset,
                speed=event.speed,
                phase=event.phase,
            )
        )

    return _shifted


def _sync(destination) -> None:
    destination.flush()
    try:
        os.fsync(destination.fileno())
    except (AttributeError, OSError):
        pass  # flux sans descripteur réel (tests) ; voir aussi `copy_range`


def _wipe_stale_tail(destination, device: Device, image_end: int, sector_size: Optional[int]) -> bool:
    """Remet à zéro le dernier `TAIL_WIPE_BYTES` de la carte, s'il est
    entièrement au-delà de l'image écrite (jamais un octet de l'image).

    Bug corrigé, confirmé sur du vrai matériel (R36S, ROCKNIX 20261001,
    carte de test de 32 Go ayant déjà porté ArkOS puis d'autres systèmes) :
    au premier démarrage, ROCKNIX échoue à agrandir sa partition de
    stockage (`parted ... resizepart 2 100%` -> « Can't have overlapping
    partitions », visible dans `fs-resize.log` sur la partition ROCKNIX),
    qui reste à 32 Mo : écran noir après le logo. L'écriture de l'image ne
    touche que son propre début -- la table GPT de secours d'un ancien
    système, rangée dans les derniers secteurs de la carte, survit au flash
    et contredit la nouvelle table. Même précaution que les outils de
    flash grand public (effacer le début ET la fin).

    Retourne False (sans lever) si la zone n'a pas pu être écrite : un
    échec ici n'empêche pas une carte de démarrer, l'appelant prévient
    l'utilisateur (`on_warning`) plutôt que d'annuler un flash réussi."""
    size = device.size_bytes or 0
    align = sector_size or 512
    start = (size - TAIL_WIPE_BYTES) // align * align
    image_end_aligned = -(-image_end // align) * align
    if size <= 0 or start < image_end_aligned or start >= size:
        return True  # carte trop petite pour une zone distincte de l'image : rien à faire
    try:
        destination.seek(start)
        destination.write(b"\x00" * (size - start))
        _sync(destination)
    except OSError:
        return False
    return True


def _write_deferred_head(destination, head: bytes, sector_size: Optional[int]) -> None:
    """Écrit le début de l'image (dont la table de partitions) en tout
    dernier, une fois tout le reste en place.

    Cause identifiée sur du vrai matériel (Windows, lecteur
    Realtek PCIE CardReader, image ROCKNIX-RK3326 sur une carte de 32 Go
    qu'un `diskpart clean` venait de vider) : `[Errno 9] Bad file
    descriptor` après 160 Mo écrits / 7,4 s, et aussitôt après l'échec,
    deux NOUVEAUX lecteurs dans l'Explorateur -- « ROCKNIX (D:) » et un
    « Disque amovible (E:) » : les partitions de l'image en cours
    d'écriture. Mécanisme : en écrivant le début de l'image en premier, on
    pose dès la première seconde une table de partitions valide ; Windows
    la découvre en cours de copie, crée et monte ces volumes -- qui ne
    sont PAS verrouillés (`prepared_write_target` ne peut verrouiller que
    les volumes qui existaient AVANT l'écriture) -- puis révoque la
    poignée `\\\\.\\PhysicalDriveN` dès qu'on écrit dans leurs secteurs.
    Ça explique aussi l'échec « non résolu » sur la carte ArkOS complète
    (docs/bugs-imaging-io.md) : verrouiller les anciennes partitions ne
    protège pas des nouvelles, dès que la nouvelle table diffère de
    l'ancienne. Écrire la table en dernier supprime la cause : pendant
    toute la copie, la carte garde son ancienne table (volumes verrouillés)
    et aucun nouveau volume ne peut apparaître. Une annulation ou une
    erreur en cours de copie laisse au passage une carte sans nouvelle
    table plutôt qu'une table pointant vers des partitions à moitié
    écrites. ⚠️ Correctif pas encore re-testé sur du vrai matériel au
    moment de l'écrire (voir docs/bugs-imaging-io.md)."""
    destination.seek(0)
    destination.write(_pad_to_sector(head, sector_size))
    _sync(destination)


def _hash_written_body(destination, head: bytes, body_len: int) -> "hashlib._Hash":
    """SHA-256 de ce qui est sur la carte, relu AVANT d'écrire la table de
    partitions : `head` (encore en mémoire, pas encore écrit) suivi du corps
    relu depuis la carte. `_read_back_head` vérifie ensuite que le début
    relu après écriture est identique à `head` -- les deux ensemble
    valent une relecture complète.

    Bug corrigé, constaté sur du vrai matériel (Windows, 11/10/2026, premier
    flash réussi après `_write_deferred_head`) : écriture complète
    (2 198 863 872 octets) mais « vérification échouée ». Une fois la table
    écrite, Windows monte la partition ROCKNIX (FAT) et y crée aussitôt
    `System Volume Information` (indexeur) -- dossier bien présent sur la
    carte juste après, avec `KERNEL` intact (md5 conforme). Relire APRÈS
    l'écriture de la table laissait Windows modifier la carte pendant la
    relecture ; tant que la table n'est pas écrite, aucun volume ne peut
    être monté, la relecture voit exactement ce qu'on a écrit. Même
    protection contre l'indexation macOS (Spotlight, fseventsd).

    Toujours sur le MÊME descripteur que l'écriture, jamais refermé puis
    rouvert -- bug corrigé plus ancien, constaté sur du vrai matériel
    macOS : refermer le descripteur d'écriture puis rouvrir le même chemin
    laissait une fenêtre pendant laquelle macOS remontait le disque et y
    écrivait des fichiers d'index, divergences tombant exactement dans la
    zone FAT de la première partition."""
    digest = hashlib.sha256(head)
    destination.seek(len(head))
    remaining = body_len
    while remaining > 0:
        chunk = destination.read(min(HASH_CHUNK_SIZE, remaining))
        if not chunk:
            break
        digest.update(chunk)
        remaining -= len(chunk)
    return digest


def _read_back_head(destination, device: Device, length: int) -> bytes:
    """Relit le début de la carte juste après l'avoir écrit, sur la même
    poignée. Si Windows l'a déjà révoquée (nouvelle table découverte, voir
    `_write_deferred_head`), relit sur une poignée neuve en lecture seule --
    lire le début d'un disque dont des volumes sont montés est permis, et
    cette zone (table de partitions) n'appartient à aucun volume."""
    try:
        destination.seek(0)
        return _read_up_to(destination, length)
    except OSError:
        time.sleep(WINDOWS_REMOUNT_SETTLE_SECONDS)
        with open(device.path, "rb") as fresh:
            return _read_up_to(fresh, length)


def flash_device(
    device: Device,
    image_path: str,
    on_progress: Optional[ProgressCallback] = None,
    block_size: int = BLOCK_SIZE,
    should_cancel: Optional[CancelCheck] = None,
    allow_unstable: bool = False,
    on_warning: Optional[Callable[[str], None]] = None,
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
    inutilisable (règle §2 n°6).

    Toujours avant `prepared_write_target` aussi : refus d'une image
    `.img.instable` sans `allow_unstable` (`UnstableImageRefused`), puis,
    si `<image>.sha256blocks` existe, recalcul des empreintes par bloc de
    l'image (phase de progression `verify_image`) -- `ImageModified` au
    moindre écart, la carte n'est jamais touchée. Sans compagnon (image
    ancienne ou téléchargée) : `on_warning` est appelé et le flash se
    poursuit comme avant."""
    check_image_format(image_path)
    if is_unstable_image(image_path) and not allow_unstable:
        raise UnstableImageRefused(f"{image_path} est la sauvegarde d'une carte instable, non fiable.")
    total_hint = estimate_total_bytes(image_path)
    sidecar = check_sidecar_matches_size(image_path)
    if sidecar is None:
        if on_warning is not None:
            on_warning(
                "Pas d'empreintes de sauvegarde à côté de cette image (image ancienne ou téléchargée) : "
                "son intégrité ne peut pas être contrôlée avant l'écriture."
            )
    else:
        with open_image_source(image_path) as image_stream:
            check_image_digests(image_stream, sidecar, on_progress, should_cancel)
    if total_hint is None:
        # Pied d'archive illisible (fichier tronqué, format non standard) :
        # repli sur la taille du périphérique cible plutôt que de traiter la
        # copie comme non bornée (bug corrigé : sans ce repli, la barre de
        # progression affichait 100 % dès le premier octet écrit — voir
        # `copy_range`, qui rapporte `done` comme `total` quand aucune borne
        # n'est connue).
        total_hint = device.size_bytes or None
    sector_size = WINDOWS_SECTOR_SIZE if platform.system() == "Windows" else None

    tail_wiped = True

    with prepared_write_target(device) as raw_path:
        # `destination` reste ouvert jusqu'à la fin de la vérification --
        # voir `_hash_written_body`.
        with open(raw_path, "r+b") as destination:
            with open_image_source(image_path) as raw_source:
                hashing_source = _HashingReader(raw_source)
                # Début de l'image lu tout de suite (pour le SHA-256, dans
                # l'ordre), mais écrit en dernier -- `_write_deferred_head`.
                head = _read_up_to(hashing_source, DEFERRED_HEAD_BYTES)
                body_written = 0
                if len(head) == DEFERRED_HEAD_BYTES:
                    destination.seek(len(head))
                    body_written = copy_range(
                        hashing_source,
                        destination,
                        total_bytes=(None if total_hint is None else max(total_hint - len(head), 0)),
                        on_progress=_offset_progress(on_progress, len(head)),
                        block_size=block_size,
                        sector_size=sector_size,
                        should_cancel=should_cancel,
                    )
                elif should_cancel is not None and should_cancel():
                    # Image plus petite que `DEFERRED_HEAD_BYTES` (tests,
                    # images minuscules) : pas de copie du corps, mais
                    # l'annulation reste honorée avant toute écriture.
                    from .copy import OperationCancelled

                    raise OperationCancelled(0)
            source_sha256 = hashing_source.hexdigest()
            written = len(head) + body_written
            tail_wiped = _wipe_stale_tail(destination, device, written, sector_size)
            # Relecture du corps AVANT d'écrire la table -- voir
            # `_hash_written_body`. `destination` reste le même descripteur
            # que pour l'écriture (le refermer puis le rouvrir laisserait
            # macOS remonter le disque entre les deux) ; `reunmount_before_verify` reste un
            # filet de sécurité pour macOS.
            reunmount_before_verify(device)
            verify_digest = _hash_written_body(destination, head, body_written)
            _write_deferred_head(destination, head, sector_size)
            head_back = _read_back_head(destination, device, len(head))
            if on_progress is not None and len(head) < DEFERRED_HEAD_BYTES:
                on_progress(ProgressEvent(done=written, total=written, speed=0.0))

    if head_back == head:
        written_sha256 = verify_digest.hexdigest()
    else:
        # Début de carte relu différent de ce qui vient d'être écrit : on
        # le signale par une empreinte qui ne peut pas égaler la source.
        written_sha256 = hashlib.sha256(head_back).hexdigest()

    if not tail_wiped and on_warning is not None:
        on_warning(
            "La fin de la carte n'a pas pu être remise à zéro : si le système ne démarre pas "
            "correctement (partition de stockage non agrandie), efface complètement la carte et reflashe-la."
        )

    return FlashResult(
        bytes_written=written,
        source_sha256=source_sha256,
        written_sha256=written_sha256,
        verified=(written_sha256 == source_sha256),
    )
