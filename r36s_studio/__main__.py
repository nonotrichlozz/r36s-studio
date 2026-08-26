"""Point d'entrée CLI :

- `python -m r36s_studio list` (phase 1) — cartes SD détectées.
- `python -m r36s_studio backup --device X --output Y` (phase 2) —
  sauvegarde en lecture seule d'une carte SD vers un fichier `.img`.
- `python -m r36s_studio flash --image X --device Y` (phase 3) — écrit une
  image (`.img`, `.img.gz`, `.img.xz`) sur une carte SD, avec confirmation
  explicite (règle §2 n°6) et vérification SHA-256.
- `python -m r36s_studio gui` (phase 4) — assistant graphique PySide6,
  branché sur `backup`/`flash` via un worker élevé (§3).

`--worker`, `--progress-file` et `--cancel-file` sur `backup`/`flash` sont
un détail d'implémentation réservé à la GUI (§3 : le worker, même binaire,
lancé avec les privilèges admin) — volontairement absents de `--help`."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import List, Optional, TextIO

from r36s_studio.devices import Device, list_devices
from r36s_studio.imaging import OperationCancelled, ProgressEvent, backup_device, flash_device
from r36s_studio.protocol import configure as configure_protocol
from r36s_studio.protocol import emit_done, emit_error, emit_log, emit_progress
from r36s_studio.safety import DEFAULT_MAX_SIZE_BYTES, SafetyConfig, filter_devices


def _resolve_device(device_path: str, max_size_bytes: int) -> Optional[Device]:
    """Retourne le `Device` correspondant à `device_path` s'il fait partie
    de la liste filtrée par `safety`, sinon None. Un périphérique refusé
    par le filtre est traité exactement comme un périphérique inexistant —
    jamais grisé, jamais accessible par son chemin. Laisse remonter
    `NotImplementedError` si l'OS courant n'a pas de provider (à charge de
    l'appelant de la distinguer d'un simple périphérique introuvable)."""
    devices = list_devices()
    config = SafetyConfig(max_size_bytes=max_size_bytes)
    safe_devices = {d.path: d for d in filter_devices(devices, config)}
    return safe_devices.get(device_path)


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
    try:
        devices = list_devices()
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
        try:
            device = _resolve_device(args.device, args.max_size)
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

        try:
            device = _resolve_device(args.device, args.max_size)
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
    flash_parser.set_defaults(func=cmd_flash)

    gui_parser = subparsers.add_parser("gui", help="Lance l'assistant graphique (PySide6)")
    gui_parser.set_defaults(func=cmd_gui)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
