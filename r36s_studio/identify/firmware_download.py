# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Choix et téléchargement d'un firmware, sans Qt : fonctions synchrones à
callback de progression et annulation coopérative (même forme que
`imaging/copy.py`), qui traduisent les exceptions en codes d'erreur
(`gui/strings.py::_ERROR_MESSAGE_KEYS`). Appelées par les threads Qt
(`gui/partition_runner.py`, `consoles_diverses/search_runner.py`) et par
le bot Telegram (`bot/`).

- `list_rocknix_variants` : variantes RK3326 de la dernière release ROCKNIX
  (jamais de choix automatique entre `-a`/`-b`) ;
- `resolve_auto_download` : fichier d'une entrée à `auto_download` (KNULLI),
  par `consoles_diverses/telechargement.py::resoudre`, SHA-256 exigée ;
- `download_firmware` : téléchargement par blocs, progression réelle
  (au plus ~4 événements/s, toujours le dernier), somme vérifiée, dans
  `~/Documents/R36S Studio/Firmwares/`."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from r36s_studio.consoles_diverses.telechargement import (
    FichierFirmware,
    Telechargement,
    TelechargementErreur,
    resoudre,
)
from r36s_studio.imaging.copy import PROGRESS_INTERVAL

from . import rocknix
from .firmware_catalog import AutoDownload
from .rocknix import (
    ChecksumMismatchError,
    DownloadCancelledError,
    RocknixAsset,
    RocknixAssetNotFoundError,
    RocknixReleaseError,
)

__all__ = [
    "DownloadOutcome",
    "ResolveOutcome",
    "VariantsOutcome",
    "asset_for",
    "download_firmware",
    "list_rocknix_variants",
    "resolve_auto_download",
    "resolve_firmware",
    "telechargement_for",
]


@dataclass
class VariantsOutcome:
    variants: List[Tuple[RocknixAsset, Optional[str]]] = field(default_factory=list)
    error_code: Optional[str] = None
    error_detail: str = ""


def list_rocknix_variants() -> VariantsOutcome:
    try:
        return VariantsOutcome(variants=rocknix.resolve_latest_r36s_assets())
    except RocknixAssetNotFoundError as exc:
        return VariantsOutcome(error_code="ROCKNIX_ASSET_NOT_FOUND", error_detail=str(exc))
    except RocknixReleaseError as exc:
        return VariantsOutcome(error_code="ROCKNIX_DOWNLOAD_FAILED", error_detail=str(exc))


def telechargement_for(download: AutoDownload) -> Telechargement:
    return Telechargement(
        depot=download.depot,
        motif_fichier=download.motif_fichier,
        url_directe=download.url_directe,
        sha256_connus=download.sha256_connus,
        exiger_sha256=True,
    )


@dataclass
class ResolveOutcome:
    fichier: Optional[FichierFirmware] = None
    error_code: Optional[str] = None
    error_detail: str = ""


def resolve_firmware(telechargement: Telechargement, opener=None) -> ResolveOutcome:
    """Dernière release puis `url_directe` (`resoudre`) ; jamais d'exception."""
    try:
        fichier = resoudre(telechargement, opener=opener) if opener is not None else resoudre(telechargement)
    except TelechargementErreur as exc:
        return ResolveOutcome(error_code="FIRMWARE_NOT_FOUND", error_detail=str(exc))
    except Exception as exc:  # filet : réponse inattendue de l'API
        return ResolveOutcome(error_code="FIRMWARE_NOT_FOUND", error_detail=str(exc))
    return ResolveOutcome(fichier=fichier)


def resolve_auto_download(download: AutoDownload, opener=None) -> ResolveOutcome:
    return resolve_firmware(telechargement_for(download), opener=opener)


def asset_for(fichier: FichierFirmware) -> RocknixAsset:
    return RocknixAsset(name=fichier.nom, download_url=fichier.url, size_bytes=fichier.taille)


@dataclass
class DownloadOutcome:
    path: Optional[Path] = None
    error_code: Optional[str] = None
    error_detail: str = ""

    @property
    def ok(self) -> bool:
        return self.path is not None


def download_firmware(
    asset: RocknixAsset,
    expected_sha256: Optional[str] = None,
    on_progress: Optional[Callable[[int, int, float], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    transform: Optional[Callable[[bytes], bytes]] = None,
    destination_dir: Optional[Path] = None,
) -> DownloadOutcome:
    """`on_progress(fait, total, débit)` au plus toutes les
    `PROGRESS_INTERVAL` secondes, et toujours pour le compte final exact
    (§2 n°5). Aucun fichier partiel, faux ou annulé n'est gardé."""
    start = time.monotonic()
    last_emit = start

    def progress(done: int, total: int) -> None:
        nonlocal last_emit
        if on_progress is None:
            return
        now = time.monotonic()
        if now - last_emit < PROGRESS_INTERVAL and done != total:
            return
        last_emit = now
        elapsed = now - start
        on_progress(done, total, done / elapsed if elapsed > 0 else 0.0)

    destination = (destination_dir or rocknix.default_firmware_downloads_dir()) / asset.name
    try:
        rocknix.download_asset(
            asset,
            destination,
            expected_sha256=expected_sha256,
            on_progress=progress,
            should_cancel=should_cancel,
            transform=transform,
        )
    except DownloadCancelledError as exc:
        return DownloadOutcome(error_code="CANCELLED", error_detail=str(exc))
    except ChecksumMismatchError as exc:
        return DownloadOutcome(error_code="ROCKNIX_CHECKSUM_MISMATCH", error_detail=str(exc))
    except RocknixReleaseError as exc:
        return DownloadOutcome(error_code="ROCKNIX_DOWNLOAD_FAILED", error_detail=str(exc))
    return DownloadOutcome(path=destination)
