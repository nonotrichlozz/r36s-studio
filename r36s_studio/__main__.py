"""Point d'entrée CLI :

- `python -m r36s_studio list` (phase 1) — cartes SD détectées.
- `python -m r36s_studio backup --device X --output Y` (phase 2) —
  sauvegarde en lecture seule d'une carte SD vers un fichier `.img`.
- `python -m r36s_studio flash --image X --device Y` (phase 3) — écrit une
  image (`.img`, `.img.gz`, `.img.xz`) sur une carte SD, avec confirmation
  explicite (règle §2 n°6) et vérification SHA-256.
- `python -m r36s_studio gui` (phase 4) — assistant graphique PySide6,
  branché sur `backup`/`flash` via un worker élevé (§3).
- `python -m r36s_studio inject-boot --device X --boot-source Y` et
  `python -m r36s_studio copy-games --device X --games-source Y` (phase 5,
  §4.4/§4.6) — copient respectivement le dossier BOOT sauvegardé et un
  dossier de jeux vers la carte déjà flashée. Contrairement à
  `backup`/`flash`, ces deux commandes écrivent sur une partition déjà
  montée par le système (BOOT et EASYROMS sont FAT/NTFS, pas un accès
  disque brut) : elles ne passent jamais par le worker élevé (§3), donc pas
  de `--worker` ni `--progress-file` sur ces sous-commandes.

`--worker`, `--progress-file` et `--cancel-file` sur `backup`/`flash` sont
un détail d'implémentation réservé à la GUI (§3 : le worker, même binaire,
lancé avec les privilèges admin) — volontairement absents de `--help`.

**Mode développement** (`--allow-disk-image` / `R36S_STUDIO_DEV=1`) — les
disk images/périphériques loop (`.dmg` montée sur macOS, `losetup` sur
Linux) sont exclus de la liste des cartes SD par les providers `devices/`,
ce qui rend `inject-boot`/`copy-games`/le futur `detect` impossibles à
tester sans carte réelle. Ce mode lève *uniquement* cette exclusion — les
règles de `safety` (disque système, taille, bus...) restent inchangées,
et il est toujours désactivé en mode worker (`--worker`), donc jamais
accessible depuis la GUI même si la variable d'environnement est présente
dans le shell qui l'a lancée. Toujours accompagné d'un avertissement visible
(voir `_warn_dev_mode_if_enabled`)."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import List, Optional, TextIO

from r36s_studio.devices import Device, list_devices
from r36s_studio.imaging import OperationCancelled, ProgressEvent, backup_device, flash_device
from r36s_studio.partitions import (
    MacosNtfsWriteUnsupported,
    MountpointNotWritable,
    PartitionNotFound,
    PartitionNotMounted,
    copy_games,
    inject_boot,
)
from r36s_studio.protocol import configure as configure_protocol
from r36s_studio.protocol import emit_done, emit_error, emit_log, emit_progress
from r36s_studio.safety import DEFAULT_MAX_SIZE_BYTES, SafetyConfig, filter_devices

DEV_MODE_ENV_VAR = "R36S_STUDIO_DEV"
_DEV_MODE_FALSY = {"", "0", "false", "False"}


def _resolve_device(
    device_path: str, max_size_bytes: int, allow_disk_image: bool = False
) -> Optional[Device]:
    """Retourne le `Device` correspondant à `device_path` s'il fait partie
    de la liste filtrée par `safety`, sinon None. Un périphérique refusé
    par le filtre est traité exactement comme un périphérique inexistant —
    jamais grisé, jamais accessible par son chemin. Laisse remonter
    `NotImplementedError` si l'OS courant n'a pas de provider (à charge de
    l'appelant de la distinguer d'un simple périphérique introuvable).

    `allow_disk_image` (mode développement, voir `_dev_mode_enabled`) ne
    fait que lever l'exclusion des disk images/loop côté `devices/` — il
    est transmis tel quel à `list_devices`, jamais à `SafetyConfig` : les
    règles de sécurité elles-mêmes restent strictement inchangées."""
    devices = list_devices(allow_disk_image=allow_disk_image)
    config = SafetyConfig(max_size_bytes=max_size_bytes)
    safe_devices = {d.path: d for d in filter_devices(devices, config)}
    return safe_devices.get(device_path)


def _add_dev_args(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument(
        "--allow-disk-image",
        action="store_true",
        help=(
            "Mode développement : autorise les disk images/périphériques loop "
            "(.dmg montée, losetup...) dans la liste des cartes SD, pour tester "
            "sans carte réelle. Ne relâche aucune autre règle de sécurité. "
            "Jamais utilisé par la GUI."
        ),
    )


def _dev_mode_enabled(args: argparse.Namespace) -> bool:
    """Mode développement : `--allow-disk-image` ou la variable
    d'environnement `R36S_STUDIO_DEV` lèvent l'exclusion des disk
    images/loop (voir `devices/macos.py`, `devices/linux.py`) — jamais les
    autres règles de sécurité, qui vivent dans `safety` et n'ont aucune
    connaissance de ce mode.

    Toujours désactivé en mode worker (`--worker`), quoi qu'il arrive :
    c'est cette seule vérification, et non l'absence du flag dans l'argv de
    la GUI, qui garantit que le mode développement n'est jamais accessible
    depuis la GUI — même si `R36S_STUDIO_DEV` traîne dans l'environnement du
    shell qui l'a lancée."""
    if getattr(args, "worker", False):
        return False
    if getattr(args, "allow_disk_image", False):
        return True
    return os.environ.get(DEV_MODE_ENV_VAR, "") not in _DEV_MODE_FALSY


def _warn_dev_mode_if_enabled(args: argparse.Namespace) -> bool:
    """Affiche un avertissement impossible à manquer avant toute opération
    quand le mode développement est actif (règle §2 : la sécurité ne doit
    jamais être discrète) — à la fois sur le vrai stderr (visible même en
    mode worker, où stdout est redirigé vers le fichier de progression) et
    via `emit_log` (visible dans le protocole JSON Lines lui-même)."""
    enabled = _dev_mode_enabled(args)
    if enabled:
        message = (
            "MODE DÉVELOPPEMENT ACTIF : les disk images/périphériques loop sont "
            "autorisés comme cartes SD (--allow-disk-image / R36S_STUDIO_DEV). "
            "Ne jamais activer ce mode en usage normal."
        )
        print(f"⚠️  {message}", file=sys.stderr)
        emit_log(message, level="warning")
    return enabled


def _open_progress_file(args: argparse.Namespace) -> Optional[TextIO]:
    """Si `--progress-file` est fourni (worker lancé par la GUI, §3), les
    événements JSON Lines sont redirigés vers ce fichier plutôt que vers
    stdout — la GUI le surveille, ne pouvant pas lire en flux la sortie
    standard d'un processus élevé à travers la frontière de privilège."""
    path = getattr(args, "progress_file", None)
    if not path:
        return None
    f = open(path, "a", encoding="utf-8")
    configure_protocol(f)
    return f


def _make_should_cancel(args: argparse.Namespace):
    """Si `--cancel-file` est fourni, l'opération s'arrête proprement dès
    que ce fichier apparaît — c'est le bouton Annuler de l'écran Exécution
    (§5) qui le crée."""
    path = getattr(args, "cancel_file", None)
    if not path:
        return None
    return lambda: os.path.exists(path)


def cmd_list(args: argparse.Namespace) -> int:
    dev_mode = _warn_dev_mode_if_enabled(args)
    try:
        devices = list_devices(allow_disk_image=dev_mode)
    except NotImplementedError as exc:
        print(f"Erreur : {exc}", file=sys.stderr)
        return 1

    config = SafetyConfig(max_size_bytes=args.max_size)
    safe_devices = filter_devices(devices, config)

    if not safe_devices:
        print("Aucune carte SD détectée.")
        return 0

    for device in safe_devices:
        size_go = device.size_bytes / 1_000_000_000
        mounts = ", ".join(device.mountpoints) if device.mountpoints else "-"
        print(f"{device.path}\t{device.display}\t{size_go:.1f} Go\t{device.bus}\t{mounts}")

    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    progress_file = _open_progress_file(args)
    try:
        dev_mode = _warn_dev_mode_if_enabled(args)
        try:
            device = _resolve_device(args.device, args.max_size, allow_disk_image=dev_mode)
        except NotImplementedError as exc:
            emit_error("UNSUPPORTED_OS", str(exc))
            return 1

        if device is None:
            emit_error(
                "DEVICE_NOT_ALLOWED",
                f"Périphérique introuvable ou refusé par la sécurité : {args.device} "
                "(voir `python -m r36s_studio list`)",
            )
            return 1

        if os.path.exists(args.output):
            emit_error("OUTPUT_EXISTS", f"Le fichier de sortie existe déjà : {args.output}")
            return 1

        emit_log(f"Sauvegarde de {device.display} ({device.path}) vers {args.output}")

        def on_progress(event: ProgressEvent) -> None:
            emit_progress(event.done, event.total, event.speed)

        try:
            copied = backup_device(
                device,
                args.output,
                on_progress=on_progress,
                should_cancel=_make_should_cancel(args),
            )
        except OperationCancelled as exc:
            emit_error("CANCELLED", f"Sauvegarde annulée après {exc.done} octets")
            emit_done(False)
            return 1
        except (OSError, subprocess.CalledProcessError) as exc:
            emit_error("IO_ERROR", str(exc))
            return 1

        emit_log(f"{copied} octets copiés")
        emit_done(True)
        return 0
    finally:
        if progress_file is not None:
            progress_file.close()


def _confirm_flash(device: Device, prompt=input) -> bool:
    """Dernier rempart avant l'écriture (règle §2 n°6) : affiche le modèle
    et la taille du périphérique cible, exige que l'utilisateur tape "OUI"
    en toutes lettres — jamais de confirmation implicite ou de sélection
    par défaut. En mode worker (`--worker`), la GUI a déjà obtenu cette
    confirmation sur son propre écran (§5 point 4) : `cmd_flash` ne
    rappelle pas cette fonction dans ce cas."""
    size_go = device.size_bytes / 1_000_000_000
    print(
        f"⚠️  Toutes les données de « {device.display} » "
        f"({size_go:.1f} Go, {device.path}) seront définitivement effacées."
    )
    answer = prompt("Tapez OUI en majuscules pour confirmer : ")
    return answer.strip() == "OUI"


def cmd_flash(args: argparse.Namespace) -> int:
    progress_file = _open_progress_file(args)
    try:
        if not os.path.exists(args.image):
            emit_error("IMAGE_NOT_FOUND", f"Fichier image introuvable : {args.image}")
            return 1

        dev_mode = _warn_dev_mode_if_enabled(args)
        try:
            device = _resolve_device(args.device, args.max_size, allow_disk_image=dev_mode)
        except NotImplementedError as exc:
            emit_error("UNSUPPORTED_OS", str(exc))
            return 1

        if device is None:
            emit_error(
                "DEVICE_NOT_ALLOWED",
                f"Périphérique introuvable ou refusé par la sécurité : {args.device} "
                "(voir `python -m r36s_studio list`)",
            )
            return 1

        if not args.worker and not _confirm_flash(device):
            emit_error("CONFIRMATION_REFUSED", "Écriture annulée : confirmation non reçue.")
            return 1

        emit_log(f"Écriture de {args.image} sur {device.display} ({device.path})")

        def on_progress(event: ProgressEvent) -> None:
            emit_progress(event.done, event.total, event.speed)

        try:
            result = flash_device(
                device,
                args.image,
                on_progress=on_progress,
                should_cancel=_make_should_cancel(args),
            )
        except OperationCancelled as exc:
            emit_error("CANCELLED", f"Écriture annulée après {exc.done} octets")
            emit_done(False)
            return 1
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            emit_error("IO_ERROR", str(exc))
            return 1

        emit_log(f"{result.bytes_written} octets écrits")

        if not result.verified:
            emit_error(
                "VERIFY_FAILED",
                f"Le hash relu ({result.written_sha256}) ne correspond pas à la "
                f"source ({result.source_sha256})",
            )
            emit_done(False)
            return 1

        emit_log(f"Vérification SHA-256 réussie ({result.source_sha256})")
        emit_done(True)
        return 0
    finally:
        if progress_file is not None:
            progress_file.close()


def _resolve_device_or_report(args: argparse.Namespace) -> Optional[Device]:
    """Commun à `inject-boot`/`copy-games` : résout `--device` et émet
    l'erreur adaptée (jamais d'accès par un chemin refusé par `safety`)."""
    dev_mode = _warn_dev_mode_if_enabled(args)
    try:
        device = _resolve_device(args.device, args.max_size, allow_disk_image=dev_mode)
    except NotImplementedError as exc:
        emit_error("UNSUPPORTED_OS", str(exc))
        return None

    if device is None:
        emit_error(
            "DEVICE_NOT_ALLOWED",
            f"Périphérique introuvable ou refusé par la sécurité : {args.device} "
            "(voir `python -m r36s_studio list`)",
        )
        return None
    return device


def cmd_inject_boot(args: argparse.Namespace) -> int:
    device = _resolve_device_or_report(args)
    if device is None:
        return 1

    if not os.path.isdir(args.boot_source):
        emit_error("SOURCE_NOT_FOUND", f"Dossier BOOT introuvable : {args.boot_source}")
        return 1

    emit_log(f"Injection de {args.boot_source} sur la partition BOOT de {device.display}")

    def on_progress(event: ProgressEvent) -> None:
        emit_progress(event.done, event.total, event.speed)

    try:
        copied = inject_boot(
            device, args.boot_source, on_progress=on_progress, should_cancel=_make_should_cancel(args)
        )
    except OperationCancelled as exc:
        emit_error("CANCELLED", f"Injection annulée après {exc.done} octets")
        emit_done(False)
        return 1
    except PartitionNotFound as exc:
        emit_error("PARTITION_NOT_FOUND", str(exc))
        return 1
    except PartitionNotMounted as exc:
        emit_error("PARTITION_NOT_MOUNTED", str(exc))
        return 1
    except MountpointNotWritable as exc:
        emit_error("MOUNTPOINT_NOT_WRITABLE", str(exc))
        return 1
    except (OSError, subprocess.CalledProcessError) as exc:
        emit_error("IO_ERROR", str(exc))
        return 1

    emit_log(f"{copied} octets copiés")
    emit_done(True)
    return 0


def cmd_copy_games(args: argparse.Namespace) -> int:
    device = _resolve_device_or_report(args)
    if device is None:
        return 1

    if not os.path.isdir(args.games_source):
        emit_error("SOURCE_NOT_FOUND", f"Dossier de jeux introuvable : {args.games_source}")
        return 1

    emit_log(f"Copie de {args.games_source} sur la partition EASYROMS de {device.display}")

    def on_progress(event: ProgressEvent) -> None:
        emit_progress(event.done, event.total, event.speed)

    try:
        copied = copy_games(
            device, args.games_source, on_progress=on_progress, should_cancel=_make_should_cancel(args)
        )
    except OperationCancelled as exc:
        emit_error("CANCELLED", f"Copie annulée après {exc.done} octets")
        emit_done(False)
        return 1
    except MacosNtfsWriteUnsupported as exc:
        emit_error("EASYROMS_NTFS_MACOS", str(exc))
        return 1
    except PartitionNotFound as exc:
        emit_error("PARTITION_NOT_FOUND", str(exc))
        return 1
    except PartitionNotMounted as exc:
        emit_error("PARTITION_NOT_MOUNTED", str(exc))
        return 1
    except MountpointNotWritable as exc:
        emit_error("MOUNTPOINT_NOT_WRITABLE", str(exc))
        return 1
    except (OSError, subprocess.CalledProcessError) as exc:
        emit_error("IO_ERROR", str(exc))
        return 1

    emit_log(f"{copied} octets copiés")
    emit_done(True)
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from r36s_studio.gui.app import run

    return run()


def _add_worker_args(subparser: argparse.ArgumentParser) -> None:
    subparser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    subparser.add_argument("--progress-file", help=argparse.SUPPRESS)
    subparser.add_argument("--cancel-file", help=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="r36s_studio")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="Liste les cartes SD détectées")
    list_parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE_BYTES,
        help="Taille maximale acceptée en octets (défaut : 1 To)",
    )
    _add_dev_args(list_parser)
    list_parser.set_defaults(func=cmd_list)

    backup_parser = subparsers.add_parser(
        "backup", help="Sauvegarde une carte SD (lecture seule) vers un fichier image"
    )
    backup_parser.add_argument(
        "--device", required=True, help="Chemin du périphérique à sauvegarder (voir `list`)"
    )
    backup_parser.add_argument("--output", required=True, help="Fichier image de destination")
    backup_parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE_BYTES,
        help="Taille maximale acceptée en octets (défaut : 1 To)",
    )
    _add_worker_args(backup_parser)
    _add_dev_args(backup_parser)
    backup_parser.set_defaults(func=cmd_backup)

    flash_parser = subparsers.add_parser(
        "flash",
        help="Écrit une image (.img, .img.gz, .img.xz) sur une carte SD, avec confirmation et vérification SHA-256",
    )
    flash_parser.add_argument(
        "--image", required=True, help="Fichier image source (.img, .img.gz, .img.xz)"
    )
    flash_parser.add_argument(
        "--device", required=True, help="Chemin du périphérique cible (voir `list`)"
    )
    flash_parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE_BYTES,
        help="Taille maximale acceptée en octets (défaut : 1 To)",
    )
    _add_worker_args(flash_parser)
    _add_dev_args(flash_parser)
    flash_parser.set_defaults(func=cmd_flash)

    inject_boot_parser = subparsers.add_parser(
        "inject-boot",
        help="Copie un dossier BOOT sauvegardé sur la partition BOOT de la carte déjà flashée",
    )
    inject_boot_parser.add_argument(
        "--device", required=True, help="Chemin du périphérique cible (voir `list`)"
    )
    inject_boot_parser.add_argument(
        "--boot-source", required=True, help="Dossier contenant les fichiers BOOT sauvegardés"
    )
    inject_boot_parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE_BYTES,
        help="Taille maximale acceptée en octets (défaut : 1 To)",
    )
    inject_boot_parser.add_argument("--cancel-file", help=argparse.SUPPRESS)
    _add_dev_args(inject_boot_parser)
    inject_boot_parser.set_defaults(func=cmd_inject_boot)

    copy_games_parser = subparsers.add_parser(
        "copy-games", help="Copie un dossier de jeux vers la partition EASYROMS de la carte"
    )
    copy_games_parser.add_argument(
        "--device", required=True, help="Chemin du périphérique cible (voir `list`)"
    )
    copy_games_parser.add_argument(
        "--games-source", required=True, help="Dossier de jeux à copier"
    )
    copy_games_parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE_BYTES,
        help="Taille maximale acceptée en octets (défaut : 1 To)",
    )
    copy_games_parser.add_argument("--cancel-file", help=argparse.SUPPRESS)
    _add_dev_args(copy_games_parser)
    copy_games_parser.set_defaults(func=cmd_copy_games)

    gui_parser = subparsers.add_parser("gui", help="Lance l'assistant graphique (PySide6)")
    gui_parser.set_defaults(func=cmd_gui)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
