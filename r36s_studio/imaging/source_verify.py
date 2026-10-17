# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Double lecture de la source et empreintes par bloc (`.sha256blocks`).

Incident réel à l'origine de ce module : une carte d'origine noname
(fabricant SD 0xFE) a renvoyé, *sans aucune erreur d'E/S*, des octets faux
pendant une sauvegarde système -- bits inversés groupés dans des blocs
isolés de 1 à 4 Ko, typique d'une flash dégradée. L'image a ensuite été
flashée et la vérification SHA-256 du flash est passée (elle compare la
carte à l'image, et l'image était déjà fausse) : libcairo corrompue,
RetroArch qui plante, écran noir. Le code de copie n'était pas en cause --
le logiciel faisait aveuglément confiance à la source.

Deux protections :
1. `verify_source` : relecture de la source après la copie, bloc par bloc,
   comparée aux empreintes calculées pendant la copie (`copy_range(...,
   block_digests=...)`). Une source qui ne renvoie pas deux fois les mêmes
   octets fait échouer la sauvegarde (`SourceUnstable`).
2. `<image>.sha256blocks` écrit à côté de l'image, recontrôlé avant tout
   flash (`check_image_digests`) : une image abîmée ou modifiée depuis la
   sauvegarde n'est jamais écrite.

Limite assumée : une carte qui renvoie *toujours* les mêmes octets faux
n'est pas détectable ainsi -- seule l'instabilité l'est."""

from __future__ import annotations

import hashlib
import os
import platform
from typing import BinaryIO, Iterable, List, Optional, Tuple

from .image_source import GZIP_ISIZE_MODULUS, estimate_total_bytes, is_size_exact
from .copy import BLOCK_SIZE, CancelCheck, OperationCancelled, ProgressCallback, ProgressEvent, ProgressThrottle

SIDECAR_SUFFIX = ".sha256blocks"
_HEADER_MAGIC = "R36S-SHA256BLOCKS"
_FORMAT_VERSION = 1

# Relectures d'un bloc dont l'empreinte diffère de la première lecture :
# il est accepté dès que `_REQUIRED_MATCHES` relectures redonnent la même
# empreinte que la copie (les octets déjà écrits dans l'image), instable
# sinon.
_MAX_REREADS = 3
_REQUIRED_MATCHES = 2

PHASE_VERIFY_SOURCE = "verify_source"
PHASE_VERIFY_IMAGE = "verify_image"

ByteRange = Tuple[int, int]  # (début, fin exclue), en octets


def _format_ranges(ranges: List[ByteRange]) -> str:
    return ", ".join(f"{start}-{end - 1}" for start, end in ranges)


class SourceUnstable(Exception):
    """La source a renvoyé des données différentes à chaque lecture d'au
    moins un bloc. `ranges` : plages d'octets (début, fin exclue) des
    blocs instables. `image_path` : où l'image a été mise de côté (renommée
    en `.instable`, jamais supprimée -- elle peut être la seule copie
    restante d'une carte en train de mourir), renseigné par l'appelant."""

    def __init__(self, ranges: List[ByteRange], image_path: Optional[str] = None):
        super().__init__(
            f"source instable : {len(ranges)} bloc(s) différent(s) d'une lecture à l'autre "
            f"(octets {_format_ranges(ranges)})"
        )
        self.ranges = ranges
        self.image_path = image_path


class ImageModified(Exception):
    """L'image ne correspond plus à son `.sha256blocks` (fichier abîmé ou
    modifié depuis la sauvegarde) -- ou l'en-tête de ce dernier ne
    correspond pas à l'image. `ranges` vide quand c'est l'en-tête ou la
    taille qui ne correspond pas, plutôt qu'un bloc précis."""

    def __init__(self, detail: str, ranges: Optional[List[ByteRange]] = None):
        ranges = ranges or []
        if ranges:
            detail = f"{detail} : {len(ranges)} bloc(s) différent(s) (octets {_format_ranges(ranges)})"
        super().__init__(detail)
        self.ranges = ranges


def sidecar_path(image_path: str) -> str:
    return image_path + SIDECAR_SUFFIX


def _block_count(total_size: int, block_size: int) -> int:
    return -(-total_size // block_size)


def _drop_cache(stream: BinaryIO, offset: int, length: int) -> None:
    """Sous Linux, `/dev/sdX` passe par le cache de pages : sans ça, la
    relecture renverrait les octets mis en cache par la première lecture et
    ne testerait rien. `/dev/rdiskN` (macOS) n'est pas mis en cache ;
    `\\\\.\\PhysicalDriveN` (Windows) ne passe pas par le cache du système
    de fichiers. Sans effet sur un flux sans descripteur (tests)."""
    if platform.system() != "Linux" or not hasattr(os, "posix_fadvise"):
        return
    try:
        os.posix_fadvise(stream.fileno(), offset, length, os.POSIX_FADV_DONTNEED)
    except (AttributeError, OSError, ValueError):
        pass


def _read_block_digest(stream: BinaryIO, offset: int, length: int) -> str:
    """Relit un bloc à `offset`. `offset` est toujours un multiple de la
    taille de bloc (4 Mio) et `length` celle du bloc lu à la copie : les
    lectures restent alignées sur le secteur sous Windows
    (`write_target.WINDOWS_SECTOR_SIZE`), exactement comme `copy_range`."""
    _drop_cache(stream, offset, length)
    stream.seek(offset)
    return hashlib.sha256(stream.read(length)).hexdigest()


def verify_source(
    source: BinaryIO,
    digests: List[str],
    total_size: int,
    block_size: int = BLOCK_SIZE,
    on_progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCheck] = None,
) -> None:
    """Relit `total_size` octets de `source` (déjà copiés, `digests` = une
    empreinte par bloc, calculée pendant la copie) et compare chaque bloc.
    Un bloc différent est relu jusqu'à `_MAX_REREADS` fois : accepté dès
    `_REQUIRED_MATCHES` relectures identiques à la première, instable
    sinon. Lève `SourceUnstable` si au moins un bloc est instable,
    `OperationCancelled` si `should_cancel` répond True (consulté avant
    chaque bloc). Progression réelle : octets effectivement relus, phase
    `PHASE_VERIFY_SOURCE` (règle §2 n°5)."""
    throttle = ProgressThrottle(on_progress, total_size, PHASE_VERIFY_SOURCE)
    unstable: List[ByteRange] = []
    done = 0
    for index, expected in enumerate(digests):
        if should_cancel is not None and should_cancel():
            raise OperationCancelled(done)
        offset = index * block_size
        length = min(block_size, total_size - offset)
        if _read_block_digest(source, offset, length) != expected:
            matches = 0
            for _ in range(_MAX_REREADS):
                if _read_block_digest(source, offset, length) == expected:
                    matches += 1
                    if matches >= _REQUIRED_MATCHES:
                        break
            if matches < _REQUIRED_MATCHES:
                unstable.append((offset, offset + length))
        done += length
        throttle.update(done)
    throttle.finish(done)
    if unstable:
        raise SourceUnstable(unstable)


def hash_blocks(
    stream: BinaryIO,
    total_size: Optional[int] = None,
    block_size: int = BLOCK_SIZE,
    on_progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCheck] = None,
    phase: str = PHASE_VERIFY_IMAGE,
) -> Tuple[List[str], int]:
    """Empreintes par bloc de `stream` lu séquentiellement depuis sa
    position courante (fichier image, éventuellement décompressé à la
    volée). Retourne (empreintes, octets lus)."""
    throttle = ProgressThrottle(on_progress, total_size, phase)
    digests: List[str] = []
    done = 0
    while total_size is None or done < total_size:
        if should_cancel is not None and should_cancel():
            raise OperationCancelled(done)
        read_size = block_size if total_size is None else min(block_size, total_size - done)
        chunk = stream.read(read_size)
        if not chunk:
            break
        digests.append(hashlib.sha256(chunk).hexdigest())
        done += len(chunk)
        throttle.update(done)
    throttle.finish(done)
    return digests, done


def rehash_blocks(stream: BinaryIO, digests: List[str], indices: Iterable[int], total_size: int, block_size: int) -> None:
    """Recalcule, dans `digests`, les blocs `indices` à partir de `stream`
    (le fichier produit). Sert à la sauvegarde système : seuls les blocs
    réécrits après la copie (tables MBR/GPT, table secondaire ajoutée en
    fin de fichier) diffèrent des octets lus sur la source -- les relire
    tous serait une passe complète de plus pour rien. La liste est
    agrandie si le fichier dépasse la copie (table secondaire GPT)."""
    count = _block_count(total_size, block_size)
    digests[:] = digests[:count] + [""] * (count - len(digests))
    for index in sorted(set(indices)):
        if 0 <= index < count:
            offset = index * block_size
            stream.seek(offset)
            digests[index] = hashlib.sha256(stream.read(min(block_size, total_size - offset))).hexdigest()


def write_block_digests(image_path: str, digests: List[str], block_size: int, total_size: int) -> str:
    """Écrit `<image>.sha256blocks` : une ligne d'en-tête (`R36S-SHA256BLOCKS
    <version> block_size=<n> total_size=<n>`), puis une empreinte hex par
    bloc, dans l'ordre. Retourne le chemin écrit."""
    path = sidecar_path(image_path)
    lines = [f"{_HEADER_MAGIC} {_FORMAT_VERSION} block_size={block_size} total_size={total_size}", *digests]
    with open(path, "w", encoding="ascii", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def read_block_digests_header(path: str) -> Tuple[int, int]:
    """(block_size, total_size) depuis la première ligne d'un `.sha256blocks`.
    Lève `ImageModified` si l'en-tête est illisible -- assez rapide pour la
    vérification côté GUI, avant la demande de mot de passe (§3)."""
    try:
        with open(path, "r", encoding="ascii") as f:
            header = f.readline()
    except (OSError, UnicodeDecodeError) as exc:
        raise ImageModified(f"fichier d'empreintes illisible : {path} ({exc})") from exc
    parts = header.split()
    try:
        if len(parts) != 4 or parts[0] != _HEADER_MAGIC or int(parts[1]) != _FORMAT_VERSION:
            raise ValueError(header)
        fields = dict(part.split("=", 1) for part in parts[2:])
        block_size, total_size = int(fields["block_size"]), int(fields["total_size"])
    except (ValueError, KeyError) as exc:
        raise ImageModified(f"en-tête d'empreintes non reconnu : {path} ({header.strip()!r})") from exc
    if block_size <= 0 or total_size < 0:
        raise ImageModified(f"en-tête d'empreintes incohérent : {path} ({header.strip()!r})")
    return block_size, total_size


def read_block_digests(path: str) -> Tuple[int, int, List[str]]:
    block_size, total_size = read_block_digests_header(path)
    with open(path, "r", encoding="ascii") as f:
        digests = [line.strip() for line in f.readlines()[1:] if line.strip()]
    if len(digests) != _block_count(total_size, block_size):
        raise ImageModified(
            f"fichier d'empreintes incomplet : {path} ({len(digests)} empreinte(s), "
            f"{_block_count(total_size, block_size)} attendue(s))"
        )
    return block_size, total_size, digests


def check_sidecar_matches_size(image_path: str) -> Optional[str]:
    """Contrôle rapide, sans recalcul : si `<image>.sha256blocks` existe,
    son en-tête doit être lisible et sa taille annoncée égale à la taille
    décompressée de l'image (`estimate_total_bytes`, lue sans
    décompression). Retourne le chemin du compagnon, ou None s'il n'y en a
    pas. Lève `ImageModified` sinon."""
    path = sidecar_path(image_path)
    if not os.path.exists(path):
        return None
    _, total_size = read_block_digests_header(path)
    image_size = estimate_total_bytes(image_path)
    if image_size is not None and not is_size_exact(image_path):
        # `.gz` : taille connue modulo 2**32 seulement, au minimum.
        mismatch = image_size > total_size or (total_size - image_size) % GZIP_ISIZE_MODULUS
    else:
        mismatch = image_size is not None and image_size != total_size
    if mismatch:
        raise ImageModified(
            f"taille de l'image ({image_size} octets) différente de celle de la sauvegarde ({total_size} octets)"
        )
    return path


def check_image_digests(
    image_stream: BinaryIO,
    sidecar: str,
    on_progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCheck] = None,
) -> None:
    """Recalcule les empreintes de l'image et les compare à `sidecar`. Lève
    `ImageModified` (avec la liste des blocs) au moindre écart."""
    block_size, total_size, expected = read_block_digests(sidecar)
    actual, done = hash_blocks(image_stream, total_size, block_size, on_progress, should_cancel)
    if done != total_size or image_stream.read(1):
        raise ImageModified(f"taille de l'image différente de celle de la sauvegarde ({total_size} octets)")
    ranges = [
        (i * block_size, min((i + 1) * block_size, total_size))
        for i, (a, e) in enumerate(zip(actual, expected))
        if a != e
    ]
    if ranges:
        raise ImageModified("le fichier image a été modifié ou abîmé depuis la sauvegarde", ranges)


def quarantine_unstable_image(output_path: str, ranges: List[ByteRange]) -> str:
    """Renomme l'image en `<nom>.instable` et écrit à côté `<nom>.instable.txt`
    (plages instables). Jamais supprimée : la carte source est peut-être en
    train de mourir, et cette image peut être la seule copie restante de
    ses sauvegardes de jeux. Le flash refuse tout `.instable`, sauf en mode
    expert après confirmation explicite. Retourne le nouveau chemin."""
    unstable_path = output_path + ".instable"
    os.replace(output_path, unstable_path)
    with open(unstable_path + ".txt", "w", encoding="utf-8", newline="\n") as f:
        f.write(
            "Carte source instable : elle a renvoyé des données différentes à chaque lecture.\n"
            "Cette image n'est pas fiable. Blocs instables (octets, début-fin inclus) :\n"
        )
        for start, end in ranges:
            f.write(f"{start}-{end - 1}\n")
    return unstable_path
