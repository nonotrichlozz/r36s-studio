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

"""« Utiliser toute la carte » pour une carte de console SF3000 : au lieu
d'écrire l'image brute (dont la partition exFAT garde la taille de la carte
d'origine, le reste de la carte devenant inutilisable -- `cmd_flash`), crée
une seule partition exFAT sur toute la carte et y recopie les fichiers de
l'image un par un (`__main__.py::cmd_clone_sf3000`).

Pourquoi c'est sûr, vérifié sur du vrai matériel (2026-09-29) :
- les 16 premiers Kio de l'image d'origine ne contiennent que le MBR (code
  de démarrage à zéro, signature de disque, une entrée) et des zéros : la
  console démarre depuis sa mémoire interne puis lit des *fichiers*
  (`cubegm/`). Recopiés quand même tels quels (signature de disque
  conservée), seule l'entrée de partition est réécrite ;
- la console démarre et lit les jeux depuis un volume exFAT formaté par
  Windows (début à 16 Kio, clusters de 64 Kio), rempli par copie de
  fichiers, y compris au-delà de l'ancienne limite de la partition
  (procédure manuelle `diskpart` + `robocopy` de l'utilisateur).

Windows uniquement pour l'instant (formatage `Format-Volume`, seule
plateforme testable sur du vrai matériel ici) ; macOS/Linux gardent la
copie brute."""

from __future__ import annotations

import contextlib
import hashlib
import math
import os
import platform
import time
from dataclasses import dataclass, field
from typing import BinaryIO, Callable, Dict, Iterator, List, Optional, Tuple

from r36s_studio.devices import Device

from .card_probe import SIGNATURE_PATH, is_sf3000_card
from .copy import CancelCheck, OperationCancelled, ProgressCallback, ProgressEvent, PROGRESS_INTERVAL
from .exfat_reader import ATTR_HIDDEN, ATTR_READ_ONLY, ATTR_SYSTEM, ExFatEntry, ExFatError, ExFatVolume, first_partition_start
from .games_partition import ALIGNMENT_SECTORS, MBR_NTFS_EXFAT_PARTITION_TYPE
from .mbr import PARTITION_ENTRY_SIZE, PARTITION_TABLE_OFFSET, SECTOR_SIZE
from .write_target import prepared_write_target

# Début de la partition sur la carte d'origine : secteur 32 (16 Kio).
PARTITION_START_LBA = 32
HEAD_BYTES = PARTITION_START_LBA * SECTOR_SIZE
CLUSTER_SIZE = 64 * 1024
# Marge effacée en fin de carte (ancienne table GPT secondaire), comme la
# remise à zéro (`reset_card._WIPE_EDGE_SECTORS`).
_TAIL_SECTORS = ALIGNMENT_SECTORS
# Utiliser toute la carte n'a d'intérêt que si elle dépasse l'image d'au
# moins ça (même seuil que la partition de jeux automatique).
WORTHWHILE_EXTRA_BYTES = 1024**3
# Marge pour les métadonnées du volume (FAT, bitmap, répertoires) dans le
# contrôle de place.
_METADATA_MARGIN_BYTES = 64 * 1024**2

# Présent à la racine de la carte pendant toute la copie, retiré en tout
# dernier : une carte dont la copie a été interrompue reste reconnaissable.
MARKER_NAME = "R36S_STUDIO_COPIE_EN_COURS.txt"
_MARKER_TEXT = (
    "Copie interrompue : cette carte est incomplète.\r\n"
    "Relance l'opération dans R36S Studio pour la refaire depuis le début.\r\n"
)
# Jamais recopié : propre à chaque volume Windows, recréé par Windows.
_SKIPPED_ROOT_DIRS = {"system volume information"}

_COPY_CHUNK = 1024 * 1024

# ponytail: débits prudents supposés, pas encore mesurés -- à recaler après
# le premier essai réel (copie fichier par fichier sur carte SD, lecture).
FILE_COPY_BYTES_PER_SECOND = 25 * 1024**2
RAW_WRITE_BYTES_PER_SECOND = 35 * 1024**2
VERIFY_BYTES_PER_SECOND = 80 * 1024**2

_WINDOWS_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL"} | {f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)}
_WINDOWS_FORBIDDEN_CHARS = set('<>:"/\\|?*')


class NotSf3000Image(Exception):
    """L'image n'a pas de première partition exFAT contenant `cubegm/rkgame`."""


class InvalidFileNames(Exception):
    def __init__(self, names: List[str]):
        super().__init__(", ".join(names[:5]) + (f" (+{len(names) - 5})" if len(names) > 5 else ""))
        self.names = names


class VerifyMismatch(Exception):
    def __init__(self, path: str):
        super().__init__(path)
        self.path = path


@dataclass
class ImageContent:
    entries: List[ExFatEntry] = field(default_factory=list)
    file_count: int = 0
    dir_count: int = 0
    total_bytes: int = 0

    def required_bytes(self) -> int:
        """Place nécessaire sur la nouvelle partition (clusters de 64 Kio)."""
        clusters = sum(math.ceil(e.size / CLUSTER_SIZE) for e in self.entries if not e.is_dir) + self.dir_count
        return clusters * CLUSTER_SIZE + _METADATA_MARGIN_BYTES


# --- lecture de l'image ------------------------------------------------------


@contextlib.contextmanager
def open_sf3000_image(image_path: str) -> Iterator[Tuple[BinaryIO, ExFatVolume]]:
    """Ouvre l'image et sa première partition exFAT ; lève `NotSf3000Image`
    si ce n'est pas une carte SF3000 en exFAT (TreeFrogUI en FAT32, image
    compressée, ArkOS...)."""
    if not is_sf3000_card(image_path):
        raise NotSf3000Image(f"{'/'.join(SIGNATURE_PATH)} absent de la première partition")
    with open(image_path, "rb") as f:
        try:
            volume = ExFatVolume(f, first_partition_start(f))
        except (ExFatError, EOFError) as exc:
            raise NotSf3000Image(str(exc)) from exc
        yield f, volume


def is_invalid_windows_name(name: str) -> bool:
    if name.endswith((" ", ".")):
        return True
    if any(c in _WINDOWS_FORBIDDEN_CHARS or ord(c) < 32 for c in name):
        return True
    return name.split(".")[0].upper() in _WINDOWS_RESERVED_NAMES


def scan_image(volume: ExFatVolume) -> ImageContent:
    """Liste tout ce qui sera copié ; lève `InvalidFileNames` avant toute
    écriture si un nom ne peut pas être créé sous Windows."""
    content = ImageContent()
    invalid: List[str] = []
    for entry in volume.walk():
        if entry.parts[0].lower() in _SKIPPED_ROOT_DIRS or entry.parts == (MARKER_NAME,):
            continue
        if is_invalid_windows_name(entry.parts[-1]):
            invalid.append("/".join(entry.parts))
        content.entries.append(entry)
        if entry.is_dir:
            content.dir_count += 1
        else:
            content.file_count += 1
            content.total_bytes += entry.size
    if invalid:
        raise InvalidFileNames(invalid)
    return content


def whole_card_used_bytes(image_path: str, device: Device) -> Optional[int]:
    """Côté interface, sans élévation : espace occupé dans l'image si
    « utiliser toute la carte » est proposable pour cette image et cette
    carte (Windows, image SF3000 exFAT, carte plus grande que l'image d'au
    moins `WORTHWHILE_EXTRA_BYTES`), sinon None. Lecture rapide (secteur de
    démarrage, bitmap d'allocation, quelques répertoires)."""
    if platform.system() != "Windows":
        return None
    try:
        image_bytes = os.path.getsize(image_path)
        if device.size_bytes < image_bytes + WORTHWHILE_EXTRA_BYTES:
            return None
        with open_sf3000_image(image_path) as (_f, volume):
            return volume.used_bytes()
    except (OSError, NotSf3000Image, ExFatError, EOFError):
        return None


def _minutes(seconds: float) -> int:
    return max(1, math.ceil(seconds / 60))


def extra_minutes_vs_raw(used_bytes: int, image_bytes: int) -> int:
    """Durée supplémentaire estimée de la copie fichier par fichier par
    rapport à la copie brute (sans compter les vérifications)."""
    return _minutes(used_bytes / FILE_COPY_BYTES_PER_SECOND - image_bytes / RAW_WRITE_BYTES_PER_SECOND)


def verify_minutes(used_bytes: int) -> int:
    return _minutes(used_bytes / VERIFY_BYTES_PER_SECOND)


def total_minutes(used_bytes: int, verify: bool = True) -> int:
    seconds = used_bytes / FILE_COPY_BYTES_PER_SECOND
    if verify:
        seconds += used_bytes / VERIFY_BYTES_PER_SECOND
    return _minutes(seconds)


# --- disposition de la carte ------------------------------------------------


def partition_sector_count(device: Device) -> int:
    return device.size_bytes // SECTOR_SIZE - _TAIL_SECTORS - PARTITION_START_LBA


def build_head(image_head: bytes, device: Device) -> bytes:
    """Les 16 premiers Kio de l'image, avec une seule entrée de partition :
    exFAT (0x07), début au secteur 32, jusqu'à la marge de fin de carte.
    Le reste (signature de disque, zéros) est conservé octet pour octet."""
    if len(image_head) != HEAD_BYTES:
        raise ValueError("en-tête d'image incomplet")
    head = bytearray(image_head)
    table_end = PARTITION_TABLE_OFFSET + 4 * PARTITION_ENTRY_SIZE
    head[PARTITION_TABLE_OFFSET:table_end] = bytes(table_end - PARTITION_TABLE_OFFSET)
    entry = bytearray(PARTITION_ENTRY_SIZE)
    entry[4] = MBR_NTFS_EXFAT_PARTITION_TYPE
    entry[8:12] = PARTITION_START_LBA.to_bytes(4, "little")
    entry[12:16] = partition_sector_count(device).to_bytes(4, "little")
    head[PARTITION_TABLE_OFFSET : PARTITION_TABLE_OFFSET + PARTITION_ENTRY_SIZE] = entry
    head[510:512] = b"\x55\xaa"
    return bytes(head)


def write_layout(device: Device, head: bytes) -> None:
    """Écrit l'en-tête (table + 16 Kio), efface le début de la nouvelle
    partition (un ancien secteur de démarrage exFAT au même endroit, cas
    d'une carte déjà clonée en brut, ferait remonter l'ancien volume avant
    le formatage) et la marge de fin de carte. Windows : laisse un instant
    pour reprendre en compte la nouvelle table avant le formatage (même
    piège que `reset_card.create_single_partition`)."""
    total_sectors = device.size_bytes // SECTOR_SIZE
    with prepared_write_target(device) as raw_path:
        with open(raw_path, "r+b") as f:
            f.write(head)
            f.write(b"\x00" * (_TAIL_SECTORS * SECTOR_SIZE))
            f.seek((total_sectors - _TAIL_SECTORS) * SECTOR_SIZE)
            f.write(b"\x00" * (_TAIL_SECTORS * SECTOR_SIZE))
            f.flush()
            os.fsync(f.fileno())
    if platform.system() == "Windows":
        time.sleep(1.0)


def format_whole_card(device: Device, label: str) -> Optional[str]:
    """exFAT, clusters de 64 Kio, étiquette de l'image (souvent aucune) ;
    renvoie la lettre de lecteur attribuée."""
    from .games_partition import _format_windows

    if platform.system() != "Windows":
        raise NotImplementedError("« utiliser toute la carte » n'est disponible que sous Windows")
    return _format_windows(device.path, label, "exfat", allocation_unit_size=CLUSTER_SIZE)


def drop_volume_cache(device: Device) -> None:
    """Démonte les volumes de la carte (Windows les remonte au prochain
    accès) : la vérification relit alors la carte, pas le cache de
    l'ordinateur."""
    if platform.system() != "Windows":
        return
    from . import winlock
    from .write_target import _windows_all_volume_paths

    winlock.unlock_volumes(winlock.lock_and_dismount_volumes(_windows_all_volume_paths(device.path)))


# --- copie et vérification --------------------------------------------------


class _Progress:
    def __init__(self, total: int, on_progress: Optional[ProgressCallback], should_cancel: Optional[CancelCheck]):
        self.total, self.done = total, 0
        self._on_progress, self._should_cancel = on_progress, should_cancel
        self._start = self._last = time.monotonic()

    def add(self, n: int) -> None:
        self.done += n
        now = time.monotonic()
        if now - self._last >= PROGRESS_INTERVAL:
            self._last = now
            self.emit()
        if self._should_cancel is not None and self._should_cancel():
            raise OperationCancelled(self.done)

    def emit(self) -> None:
        if self._on_progress is not None:
            elapsed = time.monotonic() - self._start
            self._on_progress(ProgressEvent(self.done, self.total, self.done / elapsed if elapsed > 0 else 0.0))


def _dest(root: str, entry: ExFatEntry) -> str:
    return os.path.join(root, *entry.parts)


def long_path_root(drive_letter: str) -> str:
    """Racine de la carte en chemin étendu Windows (au-delà de 260 caractères)."""
    return f"\\\\?\\{drive_letter}:\\"


def _set_attributes(path: str, attributes: int) -> None:
    kept = attributes & (ATTR_READ_ONLY | ATTR_HIDDEN | ATTR_SYSTEM)
    if kept and platform.system() == "Windows":
        import ctypes

        if not ctypes.windll.kernel32.SetFileAttributesW(path, kept):
            raise OSError(f"attributs non appliqués : {path}")


def write_marker(root: str) -> None:
    with open(os.path.join(root, MARKER_NAME), "w", encoding="utf-8", newline="") as f:
        f.write(_MARKER_TEXT)
        f.flush()
        os.fsync(f.fileno())


def remove_marker(root: str) -> None:
    os.remove(os.path.join(root, MARKER_NAME))


def has_marker(mountpoint: str) -> bool:
    return os.path.exists(os.path.join(mountpoint, MARKER_NAME))


def copy_files(
    volume: ExFatVolume,
    content: ImageContent,
    root: str,
    on_progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCheck] = None,
    on_file: Optional[Callable[[str], None]] = None,
) -> Dict[Tuple[str, ...], str]:
    """Recrée l'arborescence sous `root` et copie chaque fichier (contenu,
    date de modification, attributs), chacun forcé sur la carte (`fsync`).
    Renvoie le SHA-256 de chaque fichier, calculé pendant la copie (la
    source n'est lue qu'une fois)."""
    progress = _Progress(content.total_bytes, on_progress, should_cancel)
    hashes: Dict[Tuple[str, ...], str] = {}
    for entry in content.entries:
        path = _dest(root, entry)
        if entry.is_dir:
            os.makedirs(path, exist_ok=True)
            continue
        if on_file is not None:
            on_file("/".join(entry.parts))
        digest = hashlib.sha256()
        with open(path, "wb") as out:
            for chunk in volume.read_file(entry, _COPY_CHUNK):
                digest.update(chunk)
                out.write(chunk)
                progress.add(len(chunk))
            out.flush()
            os.fsync(out.fileno())
        if entry.mtime is not None:
            os.utime(path, (entry.mtime, entry.mtime))
        _set_attributes(path, entry.attributes)
        hashes[entry.parts] = digest.hexdigest()
    # Dates et attributs des dossiers en dernier, du plus profond au moins
    # profond : y créer des fichiers change leur date.
    for entry in reversed(content.entries):
        if entry.is_dir:
            path = _dest(root, entry)
            if entry.mtime is not None:
                os.utime(path, (entry.mtime, entry.mtime))
            _set_attributes(path, entry.attributes & ~ATTR_READ_ONLY)
    progress.emit()
    return hashes


def verify_files(
    hashes: Dict[Tuple[str, ...], str],
    root: str,
    total_bytes: int,
    on_progress: Optional[ProgressCallback] = None,
    should_cancel: Optional[CancelCheck] = None,
) -> None:
    """Relit chaque fichier sur la carte et compare son SHA-256 à celui de
    la source ; lève `VerifyMismatch` au premier écart."""
    progress = _Progress(total_bytes, on_progress, should_cancel)
    for parts, expected in hashes.items():
        digest = hashlib.sha256()
        with open(os.path.join(root, *parts), "rb") as f:
            while chunk := f.read(_COPY_CHUNK):
                digest.update(chunk)
                progress.add(len(chunk))
        if digest.hexdigest() != expected:
            raise VerifyMismatch("/".join(parts))
    progress.emit()


__all__ = [
    "CLUSTER_SIZE",
    "HEAD_BYTES",
    "MARKER_NAME",
    "PARTITION_START_LBA",
    "ImageContent",
    "InvalidFileNames",
    "NotSf3000Image",
    "VerifyMismatch",
    "build_head",
    "copy_files",
    "drop_volume_cache",
    "extra_minutes_vs_raw",
    "format_whole_card",
    "has_marker",
    "is_invalid_windows_name",
    "long_path_root",
    "open_sf3000_image",
    "partition_sector_count",
    "remove_marker",
    "scan_image",
    "total_minutes",
    "verify_files",
    "verify_minutes",
    "whole_card_used_bytes",
    "write_layout",
    "write_marker",
]
