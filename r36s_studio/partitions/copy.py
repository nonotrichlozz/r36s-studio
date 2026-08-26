"""Copie de fichiers vers une partition déjà montée (BOOT ou EASYROMS,
§4.4) : parcours récursif avec cumul d'octets pour une progression réelle
(règle §2 n°5), `fsync` par fichier. Le montage/démontage est à la charge
de l'appelant (`jobs.py`) — ce module ne connaît que deux dossiers."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from r36s_studio.imaging.copy import (
    BLOCK_SIZE,
    PROGRESS_INTERVAL,
    CancelCheck,
    OperationCancelled,
    ProgressCallback,
    ProgressEvent,
)

__all__ = ["MountpointNotWritable", "copy_tree"]

_PROBE_FILENAME = ".r36s_studio_write_test"


class MountpointNotWritable(Exception):
    """Un point de montage sur lequel on s'apprêtait à copier s'avère en
    lecture seule. Vérification générique, indépendante de l'OS et du
    système de fichiers — filet de sécurité même quand une détection plus
    spécifique en amont (ex. `jobs._reject_macos_ntfs_write`) ne suffit pas
    ou plus (bug confirmé sur du vrai matériel : EASYROMS mal détectée comme
    inscriptible, la copie échouait en plein milieu sur `[Errno 30]
    Read-only file system` au lieu d'un refus explicite préalable)."""

    def __init__(self, mountpoint: str, reason: str = ""):
        detail = f" ({reason})" if reason else ""
        super().__init__(f"Impossible d'écrire sur « {mountpoint} »{detail}.")
        self.mountpoint = mountpoint


def _check_writable(mountpoint: str) -> None:
    """Écrit puis supprime un fichier sonde sur `mountpoint` plutôt que de
    se fier aux bits de permission Unix : ceux-ci peuvent rester à "rw-"
    même quand le montage lui-même est en lecture seule (le cas confirmé
    étant un système de fichiers mal identifié comme inscriptible), donc
    `os.access` ne suffit pas — seule une vraie tentative d'écriture le
    révèle de façon fiable, quel que soit l'OS. `mountpoint` est créé s'il
    n'existe pas encore (harmless en production, où c'est toujours déjà un
    vrai point de montage) : nécessaire pour que la première écriture d'un
    `copy_tree` vers un dossier de destination pas encore créé ne soit pas
    prise, à tort, pour un montage en lecture seule."""
    mountpoint_path = Path(mountpoint)
    probe = mountpoint_path / _PROBE_FILENAME
    try:
        mountpoint_path.mkdir(parents=True, exist_ok=True)
        with open(probe, "wb") as f:
            f.write(b"\0")
    except OSError as exc:
        raise MountpointNotWritable(mountpoint, str(exc)) from exc
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


def _list_files(source_dir: str) -> list[Path]:
    return [p for p in Path(source_dir).rglob("*") if p.is_file()]


def _copy_file(src: Path, dst: Path, block_size: int) -> int:
    dst.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with open(src, "rb") as source, open(dst, "wb") as destination:
        while True:
            chunk = source.read(block_size)
            if not chunk:
                break
            destination.write(chunk)
            written += len(chunk)
        destination.flush()
        os.fsync(destination.fileno())
    return written


def copy_tree(
    source_dir: str,
    dest_dir: str,
    on_progress: Optional[ProgressCallback] = None,
    block_size: int = BLOCK_SIZE,
    should_cancel: Optional[CancelCheck] = None,
) -> int:
    """Copie récursivement le contenu de `source_dir` dans `dest_dir` (déjà
    monté), en conservant l'arborescence. Retourne le nombre d'octets
    copiés. `should_cancel` est consulté avant chaque fichier — un dossier
    de jeux contient rarement des fichiers assez gros pour qu'un contrôle
    par bloc soit nécessaire, contrairement à `imaging.copy_range` — et lève
    `OperationCancelled` (bouton Annuler de l'écran Exécution, §5 point 5)
    si l'appelant répond True. Lève `MountpointNotWritable` avant tout
    déplacement de fichier si `dest_dir` s'avère en lecture seule."""
    _check_writable(dest_dir)
    files = _list_files(source_dir)
    total = sum(f.stat().st_size for f in files)
    done = 0
    start = time.monotonic()
    last_emit = start

    def emit() -> None:
        if on_progress is None:
            return
        elapsed = time.monotonic() - start
        speed = done / elapsed if elapsed > 0 else 0.0
        on_progress(ProgressEvent(done=done, total=total, speed=speed))

    source_root = Path(source_dir)
    dest_root = Path(dest_dir)

    for file_path in files:
        if should_cancel is not None and should_cancel():
            raise OperationCancelled(done)

        relative = file_path.relative_to(source_root)
        done += _copy_file(file_path, dest_root / relative, block_size)

        now = time.monotonic()
        if now - last_emit >= PROGRESS_INTERVAL:
            emit()
            last_emit = now

    emit()  # dernier événement avec le compte final exact
    return done
