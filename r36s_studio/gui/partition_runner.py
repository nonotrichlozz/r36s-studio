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

"""Exécute les jobs d'extraction/injection (`partitions/jobs.py`) sur un
thread Qt séparé, plutôt que via le worker élevé de `worker_runner.py`.

Contrairement à `backup`/`flash` (§3), ces jobs écrivent sur une partition
déjà montée par le système (ou sur un dossier de l'ordinateur, pour
l'extraction) — jamais sur le périphérique brut —, et ne nécessitent donc
aucune élévation de privilèges (voir `__main__.py`, qui ne leur donne
d'ailleurs ni `--worker` ni `--progress-file`). Pas de frontière de
privilège à franchir : on les appelle directement, dans ce process, sur un
`QThread` pour ne pas geler l'interface pendant la copie."""

from __future__ import annotations

import platform
import subprocess
import time
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QThread, Signal

from r36s_studio.devices import Device
from r36s_studio.identify import IdentifyFailureReason, IdentifyResult, identify_from_boot_directory
from r36s_studio.identify.rocknix import (
    ChecksumMismatchError,
    DownloadCancelledError,
    RocknixAsset,
    RocknixAssetNotFoundError,
    RocknixReleaseError,
    default_firmware_downloads_dir,
    download_asset,
    resolve_latest_r36s_assets,
)
from r36s_studio.imaging.copy import PROGRESS_INTERVAL, OperationCancelled, ProgressEvent
from r36s_studio.imaging.system_backup import GamesPartitionNotFound, estimate_system_backup_size_unprivileged
from r36s_studio.partitions import (
    BOOT_LABEL,
    EASYROMS_LABEL,
    MacosNtfsWriteUnsupported,
    MountpointNotWritable,
    PartitionNotFound,
    PartitionNotMounted,
    copy_games,
    extract_boot,
    extract_easyroms,
    inject_boot,
    locate_mounted,
    unmount_forced,
)
from r36s_studio.safety.card_fingerprint import compute_boot_fingerprint


class PartitionJobRunner(QThread):
    """`mode` : "extract_boot", "extract_easyroms", "inject_boot" ou
    "copy_games" (§4.4/§4.6, étapes A/B/D/E du workflow). Émet les mêmes
    signaux que `WorkerRunner` pour la progression/l'erreur/la fin (pas de
    `log` : ces jobs n'émettent pas d'événements `emit_log`, contrairement
    au CLI `backup`/`flash`), pour que `main_window.py` puisse réutiliser
    `ExecuteScreen`/`ResultScreen` sans distinction."""

    # "qint64", pas "int" -- voir la note équivalente dans worker_runner.py :
    # un `int` C++ (32 bits, ~2,1 milliards max) déborde silencieusement dès
    # qu'une carte dépasse ~2 Go.
    progress = Signal("qint64", "qint64", float)  # done, total, speed
    error = Signal(str, str)  # code, msg
    finished_job = Signal(bool)  # ok -- nom distinct de QThread.finished

    def __init__(self, mode: str, device: Device, source_path: str, parent=None):
        super().__init__(parent)
        self._mode = mode
        self._device = device
        self._source_path = source_path
        self._cancelled = False

    def cancel(self) -> None:
        """Coopératif, comme `WorkerRunner.cancel()` : le job s'arrête
        proprement à la prochaine itération de sa boucle de copie."""
        self._cancelled = True

    def run(self) -> None:
        def on_progress(event: ProgressEvent) -> None:
            self.progress.emit(event.done, event.total, event.speed)

        def should_cancel() -> bool:
            return self._cancelled

        # Résolu ici, pas mémorisé en `__init__` ou dans un dict de module :
        # une résolution précoce capturerait la fonction d'origine avant
        # qu'un test ne puisse la patcher via
        # `r36s_studio.gui.partition_runner.inject_boot`/`copy_games`/etc.
        jobs = {
            "extract_boot": extract_boot,
            "extract_easyroms": extract_easyroms,
            "inject_boot": inject_boot,
            "copy_games": copy_games,
        }
        job = jobs[self._mode]

        try:
            job(self._device, self._source_path, on_progress=on_progress, should_cancel=should_cancel)
        except OperationCancelled as exc:
            self.error.emit("CANCELLED", f"Opération annulée après {exc.done} octets")
            self.finished_job.emit(False)
            return
        except MacosNtfsWriteUnsupported as exc:
            self.error.emit("EASYROMS_NTFS_MACOS", str(exc))
            self.finished_job.emit(False)
            return
        except PartitionNotFound as exc:
            self.error.emit("PARTITION_NOT_FOUND", str(exc))
            self.finished_job.emit(False)
            return
        except PartitionNotMounted as exc:
            self.error.emit("PARTITION_NOT_MOUNTED", str(exc))
            self.finished_job.emit(False)
            return
        except MountpointNotWritable as exc:
            self.error.emit("MOUNTPOINT_NOT_WRITABLE", str(exc))
            self.finished_job.emit(False)
            return
        except OSError as exc:
            self.error.emit("IO_ERROR", str(exc))
            self.finished_job.emit(False)
            return

        self.finished_job.emit(True)


class WizardFingerprintRunner(QThread):
    """Empreinte de contenu de la carte (§5 mode assisté, garde-fou des
    étapes 1/3 du parcours de clonage, `safety/card_fingerprint.py`), sur
    un thread séparé -- `compute_boot_fingerprint` peut monter la
    partition BOOT et bloquer jusqu'à `MOUNT_WAIT_SECONDS` (§4.4). Geler
    l'interface pendant ce montage se lit comme un plantage, constaté en
    usage réel -- c'est tout le correctif : ne plus jamais appeler
    `compute_boot_fingerprint` directement sur le thread Qt principal."""

    finished_fingerprint = Signal(object)  # Optional[str]

    def __init__(self, device_path: str, parent=None):
        super().__init__(parent)
        self._device_path = device_path

    def run(self) -> None:
        self.finished_fingerprint.emit(compute_boot_fingerprint(self._device_path))


class RocknixListRunner(QThread):
    """Recherche des variantes ROCKNIX disponibles pour la R36S (§5, étape
    de flash) -- sur un thread séparé comme les autres runners de ce
    module : un aller-retour réseau bloquant sur le thread Qt principal se
    lirait comme un gel de l'interface, même piège que le montage d'une
    partition (§4.4). Une vraie release ROCKNIX peut publier plusieurs
    images RK3326 à la fois (variantes `-a`/`-b`, dont la différence reste
    à élucider, CLAUDE.md) -- ce runner ne tranche jamais entre elles, il
    les remonte toutes à `MainWindow` pour que
    `screens.RocknixVariantDialog` propose un choix explicite."""

    finished_list = Signal(object)  # List[Tuple[RocknixAsset, Optional[str]]]
    error = Signal(str, str)  # code, msg

    def cancel(self) -> None:
        """Rien à interrompre proprement pendant un simple aller-retour à
        l'API GitHub (bien plus court qu'un téléchargement d'image) --
        présent uniquement pour que le bouton Annuler du journal de bord
        (§5) ne lève jamais d'exception s'il est cliqué pendant cette
        étape, plutôt que pour une vraie annulation coopérative."""

    def run(self) -> None:
        try:
            variants = resolve_latest_r36s_assets()
        except RocknixAssetNotFoundError as exc:
            self.error.emit("ROCKNIX_ASSET_NOT_FOUND", str(exc))
            self.finished_list.emit([])
            return
        except RocknixReleaseError as exc:
            self.error.emit("ROCKNIX_DOWNLOAD_FAILED", str(exc))
            self.finished_list.emit([])
            return
        self.finished_list.emit(variants)


class RocknixDownloadRunner(QThread):
    """Téléchargement d'une variante ROCKNIX déjà choisie par l'utilisateur
    (`RocknixListRunner`/`screens.RocknixVariantDialog` ci-dessus) -- ce
    runner ne choisit plus rien lui-même, `asset`/`expected_sha256` sont
    fournis au constructeur. Contrairement à dArkOS, dont le bouton se
    contente d'ouvrir la page des releases dans le navigateur
    (`identify/releases.py`, images sur Mega/Google Drive/OneDrive),
    ROCKNIX publie ses images directement en assets GitHub
    (`identify/rocknix.py`) : ce runner télécharge l'image choisie avec
    progression réelle, et vérifie sa somme de contrôle si elle est
    connue. Sur un thread séparé comme les autres runners de ce module --
    un téléchargement dure largement plus qu'un aller-retour réseau
    instantané."""

    # Mêmes types Qt que `PartitionJobRunner`/`WorkerRunner` -- voir la
    # note équivalente sur le débordement d'un `int` 32 bits au-delà de
    # ~2 Go.
    progress = Signal("qint64", "qint64", float)  # done, total, speed
    error = Signal(str, str)  # code, msg
    finished_download = Signal(bool, str)  # ok, chemin téléchargé ("" si échec)

    def __init__(self, asset: RocknixAsset, expected_sha256: Optional[str] = None, parent=None):
        super().__init__(parent)
        self._asset = asset
        self._expected_sha256 = expected_sha256
        self._cancelled = False

    def cancel(self) -> None:
        """Coopératif, comme `PartitionJobRunner.cancel()` : consulté par
        `download_asset` avant chaque bloc -- le bouton Annuler du journal
        de bord (§5) reste actif pendant un téléchargement, pas seulement
        pendant une écriture disque."""
        self._cancelled = True

    def run(self) -> None:
        start = time.monotonic()
        last_emit = start

        def on_progress(done: int, total: int) -> None:
            nonlocal last_emit
            now = time.monotonic()
            # Même limitation qu'`imaging/copy.py::copy_range` (règle §2
            # n°5) -- mais toujours le dernier événement, `done == total`,
            # pour que la barre de progression finisse bien à 100 %.
            if now - last_emit < PROGRESS_INTERVAL and done != total:
                return
            last_emit = now
            elapsed = now - start
            speed = done / elapsed if elapsed > 0 else 0.0
            self.progress.emit(done, total, speed)

        destination = default_firmware_downloads_dir() / self._asset.name
        try:
            download_asset(
                self._asset,
                destination,
                expected_sha256=self._expected_sha256,
                on_progress=on_progress,
                should_cancel=lambda: self._cancelled,
            )
        except DownloadCancelledError as exc:
            self.error.emit("CANCELLED", str(exc))
            self.finished_download.emit(False, "")
            return
        except ChecksumMismatchError as exc:
            self.error.emit("ROCKNIX_CHECKSUM_MISMATCH", str(exc))
            self.finished_download.emit(False, "")
            return
        except RocknixReleaseError as exc:
            self.error.emit("ROCKNIX_DOWNLOAD_FAILED", str(exc))
            self.finished_download.emit(False, "")
            return

        self.finished_download.emit(True, str(destination))


@dataclass
class SystemBackupEstimate:
    """Résultat de `SystemBackupEstimateRunner` -- trois issues possibles :
    `size_bytes` renseigné (succès, `error`/`needs_elevation` restent
    respectivement `None`/`False`) ; `error` (code du protocole, §3)
    accompagné de `detail`, le message brut de l'exception d'origine --
    bug corrigé : sans lui, une erreur à cette étape n'affichait que le
    message générique « Une erreur est survenue », sans aucune cause
    exploitable, contrairement à toute autre opération de l'appli (§5 :
    le détail brut suit toujours le message principal dans le journal) ;
    ou `needs_elevation=True` (§4.3, confirmé sur du vrai matériel :
    `list_partitions` -- non élevé -- n'a pas pu exposer la taille d'au
    moins une partition à sommer) -- l'appelant relance alors un calcul
    élevé plutôt que d'afficher une erreur, la carte n'étant pas en
    cause. `board_compatible` est un pur bonus, jamais requis pour un
    résultat par ailleurs réussi -- y compris avec `needs_elevation`,
    déjà tenté à ce stade pour ne pas le refaire après coup."""

    size_bytes: Optional[int] = None
    error: Optional[str] = None
    detail: Optional[str] = None
    board_compatible: Optional[str] = None
    needs_elevation: bool = False


class IdentifyRunner(QThread):
    """Tuile « Rechercher ma console » de l'accueil assisté (§5, refonte
    menu de tuiles) -- version non décorative de `_best_effort_board_
    compatible` ci-dessous : celle-ci avale toute exception (son résultat
    n'est qu'un bonus pour un nom de fichier suggéré), celle-ci doit au
    contraire remonter un vrai résultat -- succès ou échec -- à afficher.
    Sur un thread séparé comme les autres runners de ce module : monter le
    BOOT peut bloquer jusqu'à `MOUNT_WAIT_SECONDS` (`locate_mounted`)."""

    finished_identify = Signal(object)  # IdentifyResult

    def __init__(self, device_path: str, parent=None):
        super().__init__(parent)
        self._device_path = device_path

    def run(self) -> None:
        try:
            boot = locate_mounted(self._device_path, BOOT_LABEL)
        except (PartitionNotFound, PartitionNotMounted) as exc:
            # Carte sans BOOT lisible -- `IdentifyResultDialog` n'a alors
            # qu'un seul type d'entrée à gérer (un `IdentifyResult`,
            # succès ou échec confondus), jamais une exception à part.
            self.finished_identify.emit(
                IdentifyResult(failure_reason=IdentifyFailureReason.MOUNT_FAILED, detail=str(exc))
            )
            return
        try:
            result = identify_from_boot_directory(boot.mountpoint)
        finally:
            unmount_forced(boot)
        self.finished_identify.emit(result)


def _best_effort_board_compatible(device_path: str) -> Optional[str]:
    """Identification de la console (pour suggérer un nom de fichier «
    quand il est connu », §4.3), purement décorative : n'importe quel
    échec (montage impossible, pas de `.dtb`, carte défaillante...) est
    avalé silencieusement plutôt que de faire échouer l'estimation."""
    try:
        boot = locate_mounted(device_path, BOOT_LABEL)
        if not boot.mountpoint:
            return None
        result = identify_from_boot_directory(boot.mountpoint)
        unmount_forced(boot)
        return result.info.board_compatible if result.info is not None else None
    except Exception:
        return None


class SystemBackupEstimateRunner(QThread):
    """Étape préalable à la sauvegarde système sans les jeux (§4.3) : sur
    un thread séparé comme les autres runners de ce module, puisque lire
    la table de partitions et, en best-effort, monter le BOOT pour
    l'identification peut bloquer (`locate_mounted`, jusqu'à `MOUNT_WAIT_
    SECONDS`) -- un gel de l'interface pendant ce calcul se lirait comme
    un plantage (même piège que `WizardIdentifyRunner`/`WizardFingerprint
    Runner`).

    Utilise `estimate_system_backup_size_unprivileged` -- jamais un accès
    brut au périphérique, confirmé exiger les droits administrateur sur
    macOS (`[Errno 13] Permission denied: '/dev/diskN'`) pour ce qui n'est
    qu'un calcul d'estimation avant de lancer l'opération réelle (celle-ci
    reste élevée via le worker, §3, comme `backup`/`flash`). Émet
    `needs_elevation=True` plutôt que de tenter elle-même un accès brut
    quand cette estimation légère ne suffit pas -- c'est `MainWindow`
    (pas ce thread) qui relance alors un calcul élevé, en réutilisant la
    session d'autorisation déjà partagée avec `WorkerRunner`."""

    finished_estimate = Signal(object)  # SystemBackupEstimate

    def __init__(self, device_path: str, parent=None):
        super().__init__(parent)
        self._device_path = device_path

    def run(self) -> None:
        try:
            size_bytes = estimate_system_backup_size_unprivileged(self._device_path)
        except GamesPartitionNotFound as exc:
            self.finished_estimate.emit(SystemBackupEstimate(error="GAMES_PARTITION_NOT_FOUND", detail=str(exc)))
            return
        except (OSError, subprocess.CalledProcessError) as exc:
            self.finished_estimate.emit(SystemBackupEstimate(error="IO_ERROR", detail=str(exc)))
            return

        board_compatible = _best_effort_board_compatible(self._device_path)

        if size_bytes is None:
            self.finished_estimate.emit(SystemBackupEstimate(needs_elevation=True, board_compatible=board_compatible))
            return

        self.finished_estimate.emit(SystemBackupEstimate(size_bytes=size_bytes, board_compatible=board_compatible))
