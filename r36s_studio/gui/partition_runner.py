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

import subprocess

from PySide6.QtCore import QThread, Signal

from r36s_studio.devices import Device
from r36s_studio.identify import IdentifyFailureReason, IdentifyResult, identify_from_boot_directory
from r36s_studio.imaging.copy import OperationCancelled, ProgressEvent
from r36s_studio.partitions import (
    BOOT_LABEL,
    MacosNtfsWriteUnsupported,
    MountpointNotWritable,
    PartitionNotFound,
    PartitionNotMounted,
    copy_games,
    extract_boot,
    extract_easyroms,
    inject_boot,
    locate_mounted,
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


class WizardIdentifyRunner(QThread):
    """Identification de la console (étape 2 du mode assisté, §5) : monte
    la partition BOOT de la carte source et y cherche un `.dtb`
    exploitable (`identify.identify_from_boot_directory`), sur un thread
    séparé comme `PartitionJobRunner` -- `locate_mounted` peut bloquer
    jusqu'à `MOUNT_WAIT_SECONDS` (§4.4) si le système n'a pas encore monté
    la partition automatiquement. Émet toujours `finished_identify`
    (`IdentifyResult`) -- ne lève jamais (§4.5 : une détection ratée ne
    doit jamais planter l'interface, et l'absence d'identification a un
    repli prévu, MultiPanel). Distingue le montage raté (`MOUNT_FAILED` --
    carte probablement défaillante, courant sur les cartes fournies avec
    la console) des deux échecs décidés par `identify_from_boot_directory`
    une fois la partition lisible (`NO_DTB_FOUND`/`ALL_DTB_INVALID`) --
    chacun a son propre message à l'étape 2."""

    finished_identify = Signal(object)  # IdentifyResult

    def __init__(self, device_path: str, parent=None):
        super().__init__(parent)
        self._device_path = device_path

    def run(self) -> None:
        try:
            boot = locate_mounted(self._device_path, BOOT_LABEL)
        except (PartitionNotFound, PartitionNotMounted, OSError, subprocess.CalledProcessError):
            self.finished_identify.emit(IdentifyResult(failure_reason=IdentifyFailureReason.MOUNT_FAILED))
            return
        if not boot.mountpoint:
            self.finished_identify.emit(IdentifyResult(failure_reason=IdentifyFailureReason.MOUNT_FAILED))
            return
        self.finished_identify.emit(identify_from_boot_directory(boot.mountpoint))


class WizardFingerprintRunner(QThread):
    """Empreinte de contenu de la carte (§5 mode assisté, garde-fou des
    étapes 1/4, `safety/card_fingerprint.py`), sur un thread séparé comme
    `WizardIdentifyRunner` -- `compute_boot_fingerprint` peut monter la
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
