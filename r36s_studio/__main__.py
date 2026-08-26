"""Point d'entrée CLI de la phase 1 : `python -m r36s_studio list`.

Affiche les cartes SD détectées, et uniquement les cartes SD — le filtrage se
fait via `safety.filter_devices`, jamais dans l'affichage."""

from __future__ import annotations

import argparse
import sys

from r36s_studio.devices import list_devices
from r36s_studio.safety import DEFAULT_MAX_SIZE_BYTES, SafetyConfig, filter_devices


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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
