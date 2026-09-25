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

"""Point d'entrée CLI :

- `python -m r36s_studio list` (phase 1) — cartes SD détectées.
- `python -m r36s_studio backup --device X --output Y` (phase 2) —
  sauvegarde en lecture seule d'une carte SD vers un fichier `.img`.
- `python -m r36s_studio flash --image X --device Y` (phase 3) — écrit une
  image (`.img`, `.img.gz`, `.img.xz`) sur une carte SD, avec confirmation
  explicite (règle §2 n°6) et vérification SHA-256.
- `python -m r36s_studio reset-card --device X [--label ÉTIQUETTE]
  [--filesystem exfat|fat32]` (§4.3 bis, mode expert uniquement, sous
  « Par sécurité ») — « Remettre la carte à zéro » : efface toute la
  table de partitions et recrée une seule partition (exFAT par défaut,
  FAT32 sur demande -- pour les consoles anciennes qui ne lisent pas
  l'exFAT) occupant toute la carte, pour une carte laissée en plusieurs
  partitions illisibles après des essais de firmware. Même confirmation
  explicite obligatoire que `flash` (règle §2 n°6).
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
- `python -m r36s_studio extract-boot --device X [--output-dir DIR]` et
  `python -m r36s_studio extract-easyroms --device X [--output-dir DIR]`
  (phase 6, workflow à deux cartes §4.4/§4.5) — l'inverse d'`inject-boot`/
  `copy-games` : copient la partition BOOT/EASYROMS de la carte *source*
  (l'ancienne) vers un dossier horodaté de l'ordinateur
  (`~/R36S Studio/BOOT_2026-07-06_00-21` par défaut, voir
  `partitions/archives.py`), pour réinjection ultérieure sur la carte
  neuve. Ni élévation ni écriture sur la carte : mêmes conditions
  qu'`inject-boot`/`copy-games`.
- `python -m r36s_studio eject --device X` — démonte toutes les partitions
  de la carte et l'éjecte (étape F du workflow à deux cartes, §4.5) ; émet
  une confirmation explicite que la carte peut être retirée physiquement.
- `python -m r36s_studio identify --boot-dir DIR` (phase 8, mode assisté
  §5) — lance `identify.identify_from_boot_directory` sur un dossier
  local de `.dtb`, sans carte physique ni montage : pour valider le
  parseur DTB et la future table de correspondance sur des variantes de
  console fournies par d'autres utilisateurs, pas seulement sur la carte
  du développeur. Sortie texte simple (pas le protocole JSON Lines, §3 --
  cette commande est un outil de diagnostic interactif, pas un worker
  piloté par la GUI).

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
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, TextIO

from r36s_studio.devices import Device, list_devices
from r36s_studio.doublons.journal_check import verify_journal
from r36s_studio.identify import identify_from_boot_directory
from r36s_studio.imaging import (
    DEFAULT_RESET_LABEL,
    CardTooSmallForReset,
    GamesPartitionNotFound,
    OperationCancelled,
    ProgressEvent,
    SevenZipArchiveError,
    UnsupportedImageFormatError,
    backup_device,
    backup_system_only,
    check_fat32_feasible,
    create_and_format_games_partition_if_worthwhile,
    create_single_partition,
    erase_partition_table,
    estimate_system_backup_size,
    estimate_system_backup_size_unprivileged,
    estimate_total_bytes,
    flash_device,
    format_reset_partition,
)
from r36s_studio.imaging.fat32 import Fat32VolumeTooSmall
from r36s_studio.imaging.winlock import VolumeInUseError
from r36s_studio.partitions import (
    BOOT_LABEL,
    EASYROMS_LABEL,
    MacosNtfsWriteUnsupported,
    MountpointNotWritable,
    PartitionNotFound,
    PartitionNotMounted,
    archives,
    copy_games,
    extract_boot,
    extract_easyroms,
    inject_boot,
)
from r36s_studio.partitions.eject import eject as eject_device
from r36s_studio.protocol import configure as configure_protocol
from r36s_studio.protocol import (
    emit_done,
    emit_eject_result,
    emit_error,
    emit_estimate,
    emit_log,
    emit_progress,
    emit_step_progress,
)
from r36s_studio.safety import DEFAULT_MAX_SIZE_BYTES, SafetyConfig, filter_devices

DEV_MODE_ENV_VAR = "R36S_STUDIO_DEV"
_DEV_MODE_FALSY = {"", "0", "false", "False"}


def _capacity_go(size_bytes: int) -> float:
    """Capacité d'une carte entière, en « Go », calculée en base 1024 --
    même choix et même raison que `gui/screens.py::_capacity_go` (bug
    corrigé, signalé sur du vrai matériel : l'app affichait « 31,9 Go » là
    où l'Explorateur Windows affiche « 29,7 Go » pour la même carte,
    calculée elle aussi en base 1024 sous l'étiquette « Go »). Dupliquée
    ici plutôt qu'importée de `gui/` : trop petite pour justifier un
    module utilitaire partagé, et `__main__.py` ne doit pas dépendre de
    `gui/` (§3 : le CLI fonctionne sans PySide6)."""
    return size_bytes / (1024**3)


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
        size_go = _capacity_go(device.size_bytes)
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

        if args.estimate_only:
            # Repli élevé pour l'estimation de la sauvegarde système sans
            # les jeux (§4.3) -- appelé uniquement quand `partitions/
            # locate.py::list_partitions` (non élevé) n'a pas pu produire
            # d'estimation lui-même (taille manquante pour au moins une
            # partition). N'écrit jamais rien, `--output` n'a pas de sens
            # ici.
            if not args.system_only:
                emit_error("INVALID_ARGS", "--estimate-only n'est utilisable qu'avec --system-only")
                return 1
            try:
                size_bytes = estimate_system_backup_size(device.path)
            except GamesPartitionNotFound as exc:
                emit_error("GAMES_PARTITION_NOT_FOUND", str(exc))
                return 1
            except (OSError, subprocess.CalledProcessError) as exc:
                emit_error("IO_ERROR", str(exc))
                return 1
            emit_estimate(size_bytes)
            emit_done(True)
            return 0

        if args.output is None:
            emit_error("INVALID_ARGS", "--output est requis (sauf avec --estimate-only)")
            return 1

        if os.path.exists(args.output):
            emit_error("OUTPUT_EXISTS", f"Le fichier de sortie existe déjà : {args.output}")
            return 1

        # Pré-vol (§5 mode assisté, parcours de clonage) : jamais un échec
        # après une longue copie déjà lancée -- vérifié ici, sur le
        # backend, comme seule autorité réelle (un pré-contrôle côté GUI,
        # plus rapide, ne fait qu'éviter de lancer ce worker élevé pour
        # rien). `device.size_bytes` pour une copie complète est un
        # majorant sûr, sans lecture supplémentaire : `backup_device` ne
        # dépasse jamais la taille du périphérique source (il s'arrête à
        # la fin de la dernière partition utilisée). Pour la sauvegarde
        # système, réutilise l'estimation non élevée déjà disponible
        # (`list_partitions`, §4.3) et ne retombe sur le calcul exact
        # élevé que si elle manque une taille.
        try:
            required_bytes = (
                device.size_bytes
                if not args.system_only
                else (
                    estimate_system_backup_size_unprivileged(device.path)
                    or estimate_system_backup_size(device.path)
                )
            )
        except GamesPartitionNotFound as exc:
            emit_error("GAMES_PARTITION_NOT_FOUND", str(exc))
            return 1
        try:
            free_bytes = shutil.disk_usage(Path(args.output).resolve().parent).free
        except OSError as exc:
            emit_error("IO_ERROR", str(exc))
            return 1
        if free_bytes < required_bytes:
            emit_error(
                "INSUFFICIENT_DISK_SPACE",
                f"Espace libre insuffisant sur {Path(args.output).resolve().parent} : "
                f"{free_bytes} octets disponibles, ~{required_bytes} nécessaires.",
            )
            return 1

        if args.system_only:
            emit_log(
                f"Sauvegarde système (sans les jeux) de {device.display} ({device.path}) vers {args.output}"
            )
        else:
            emit_log(f"Sauvegarde de {device.display} ({device.path}) vers {args.output}")

        def on_progress(event: ProgressEvent) -> None:
            emit_progress(event.done, event.total, event.speed)

        backup_function = backup_system_only if args.system_only else backup_device
        try:
            copied = backup_function(
                device,
                args.output,
                on_progress=on_progress,
                should_cancel=_make_should_cancel(args),
            )
        except GamesPartitionNotFound as exc:
            emit_error("GAMES_PARTITION_NOT_FOUND", str(exc))
            return 1
        except OperationCancelled as exc:
            emit_error("CANCELLED", f"Sauvegarde annulée après {exc.done} octets")
            emit_done(False)
            return 1
        except (OSError, subprocess.CalledProcessError) as exc:
            emit_error("IO_ERROR", str(exc))
            return 1

        emit_log(f"{copied} octets copiés")

        if args.eject_after:
            # Chaîne l'éjection de la carte source dans ce même worker déjà
            # élevé (§5 mode assisté, `_run_wizard_source_eject`) plutôt que
            # d'en relancer un second dédié -- évite une invite UAC
            # supplémentaire dans le cas courant. Contrairement à
            # `--eject-after` de `cmd_flash` (best-effort, jamais fatal),
            # `emit_eject_result` rapporte le résultat séparément :
            # `_start_worker`/`_on_wizard_source_eject_result` (GUI) s'en
            # servent pour décider d'enchaîner directement sur la détection
            # de la carte neuve ou de retomber sur le worker d'éjection
            # dédié -- mais la sauvegarde elle-même, déjà réussie et
            # vérifiée à ce stade, ne doit jamais échouer à cause d'un
            # échec d'éjection qui la suivrait.
            emit_log("Éjection automatique de la carte source...")
            try:
                eject_device(device.path)
            except Exception as exc:
                emit_log(f"Éjection automatique impossible : {exc}", level="warning")
                emit_eject_result(False, str(exc))
            else:
                emit_log(f"{device.display} peut maintenant être retirée en toute sécurité.")
                emit_eject_result(True)

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
    size_go = _capacity_go(device.size_bytes)
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

        # Pré-vol (§5 mode assisté, parcours de clonage) : une carte plus
        # petite que l'image tronque et corrompt la table GPT secondaire
        # (déjà rencontré) -- `estimate_total_bytes` est exacte et non
        # privilégiée pour `.img`/`.img.gz`/`.img.xz` (lue depuis le pied
        # du fichier, sans décompression). `None` seulement pour un pied
        # tronqué/non standard (cas résiduel) : le contrôle est alors
        # sauté plutôt que bloqué -- `flash_device` échouera de toute
        # façon avec une vraie erreur d'écriture (ENOSPC) si ça ne rentre
        # pas, jamais une troncature silencieuse.
        total_hint = estimate_total_bytes(args.image)
        if total_hint is not None and total_hint > device.size_bytes:
            emit_error(
                "DESTINATION_TOO_SMALL",
                f"Image de {total_hint} octets, carte cible « {device.display} » de {device.size_bytes} octets.",
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
        except SevenZipArchiveError as exc:
            emit_error("SEVEN_ZIP_ARCHIVE", str(exc))
            return 1
        except UnsupportedImageFormatError as exc:
            emit_error("UNSUPPORTED_IMAGE_FORMAT", str(exc))
            return 1
        except VolumeInUseError as exc:
            # Bug corrigé, confirmé sur du vrai matériel : FSCTL_LOCK_VOLUME
            # refusé (ERROR_ACCESS_DENIED) même sur un worker déjà élevé --
            # un autre processus (Explorateur, indexeur, antivirus) tient
            # encore un descripteur sur le volume, jamais un problème de
            # privilèges ni une carte débranchée (§4.3). Code dédié pour ne
            # pas retomber sur le message générique IO_ERROR, faux dans ce
            # cas précis (`winlock._lock_volume` a déjà réessayé plusieurs
            # fois avant d'abandonner).
            emit_error("VOLUME_IN_USE", str(exc))
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

        # Décision automatique, après l'écriture et la vérification (§4.3) :
        # une restauration d'image (sauvegarde « système sans les jeux »,
        # mais aussi n'importe quel firmware plus petit que la carte de
        # destination) peut laisser de l'espace non partitionné. L'app
        # dispose de toute l'information nécessaire (taille de l'image déjà
        # écrite, taille réelle de la carte) pour décider seule s'il vaut la
        # peine d'y recréer une partition de jeux -- l'utilisateur ne peut
        # pas le savoir lui-même, surtout avec un firmware qu'il découvre
        # (§1). Plus de drapeau `--create-games-partition` à passer :
        # tentée pour tout flash, sur toute plateforme, jamais seulement
        # pour un fichier reconnu comme une sauvegarde système de cette
        # session (comparaison de chemin, GUI -- retirée, trop fragile et
        # trop étroite : ni les images d'origine externe ni le mode expert
        # n'en bénéficiaient). Jamais un échec du flash déjà réussi pour ce
        # motif (best-effort, même principe que `--eject-after` ci-dessous)
        # -- journalisé dans tous les cas (§4.4 : jamais une décision
        # silencieuse), que le résultat soit « rien à faire », un succès ou
        # un échec.
        try:
            games_result = create_and_format_games_partition_if_worthwhile(device)
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            emit_log(f"Espace de jeux non recréé : {exc}", level="warning")
        else:
            if games_result is None:
                emit_log("Pas assez d'espace libre restant pour créer un espace de jeux supplémentaire.")
            else:
                emit_log(f"Espace de jeux recréé sur l'espace libre restant ({games_result.size_bytes} octets).")
                if games_result.drive_letter:
                    # Bug corrigé, confirmé sur du vrai matériel (§4.3
                    # bis) : sans lettre de lecteur, un volume exFAT
                    # fraîchement formaté n'apparaît pas dans
                    # l'Explorateur malgré un formatage réussi.
                    emit_log(f"La carte est disponible sous {games_result.drive_letter}:.")

        if args.eject_after:
            # Généralisé au-delà d'Android (§4.6) : au moins une partition
            # de tout firmware du catalogue est illisible pour Windows (le
            # système ext4 "Linux" pour ArkOS/ROCKNIX/EmuELEC/AmberELEC/
            # MinUI, plusieurs partitions en plus pour Android), qui
            # propose alors de la formater dès qu'il la remarque -- ce qui
            # arrive généralement tout de suite après l'écriture, dès que
            # `prepared_write_target` relâche le disque (§4.3, `IOCTL_
            # DISK_UPDATE_PROPERTIES`, qui force justement Windows à
            # redécouvrir les partitions). Éjecter tout de suite, dans ce
            # même worker déjà élevé (pas de nouvelle invite), réduit la
            # fenêtre pendant laquelle ces propositions de formatage
            # peuvent apparaître -- sans garantie de gagner la course à
            # chaque fois (non vérifié sur du vrai matériel, §5 : le
            # message explicite du journal de bord reste le filet de
            # sécurité qui compte vraiment, y compris si la carte est un
            # jour rebranchée ailleurs). Un échec d'éjection ici ne remet
            # jamais en cause le flash déjà réussi -- best-effort,
            # seulement journalisé.
            #
            # Bug corrigé, signalé sur du vrai matériel : ce message
            # affichait « (firmware Android) » y compris après un flash
            # ArkOS -- resté d'avant la généralisation de `--eject-after`
            # à tout le catalogue (§4.6), jamais mis à jour alors que ce
            # drapeau n'est plus spécifique à Android depuis. Message
            # neutre désormais, sans conséquence fonctionnelle (l'éjection
            # elle-même n'a jamais dépendu de ce texte) mais trompeur pour
            # qui lit le journal.
            # Bug corrigé, confirmé sur du vrai matériel : ce résultat
            # n'était jusqu'ici *que* journalisé (`emit_log`, best-effort)
            # -- indiscernable côté GUI d'un succès, `_on_worker_finished`
            # masquait donc systématiquement le bouton Éjecter dès que ce
            # drapeau était posé (`format_prompt_flash`), en supposant la
            # carte déjà éjectée. Un échec silencieux de cette éjection
            # chaînée laissait alors la carte réellement non éjectée, sans
            # aucun moyen évident de le refaire dans le prolongement du
            # flash -- l'utilisateur devait deviner qu'il fallait passer par
            # l'étape F séparée, qui redemande sa propre élévation (§3,
            # aucun équivalent de `MacosAuthorizationSession` sur Windows) :
            # exactement la « invite UAC dédiée, deux minutes plus tard »
            # rapportée. `emit_eject_result` (même mécanisme que `backup
            # --eject-after`, §5 mode assisté) rapporte désormais ce
            # résultat séparément -- `_on_worker_finished` (GUI) ne masque
            # le bouton que si ce résultat confirme un succès, jamais par
            # défaut.
            emit_log("Éjection automatique de la carte...")
            try:
                eject_device(device.path)
            except Exception as exc:
                emit_log(f"Éjection automatique impossible : {exc}", level="warning")
                emit_eject_result(False, str(exc))
            else:
                emit_log(f"{device.display} peut maintenant être retirée en toute sécurité.")
                emit_eject_result(True)

        emit_done(True)
        return 0
    finally:
        if progress_file is not None:
            progress_file.close()


_RESET_CARD_STEP_COUNT = 4


def cmd_reset_card(args: argparse.Namespace) -> int:
    """« Remettre la carte à zéro » (§4.3 bis) : après des essais de
    firmware, une carte peut rester en trois à cinq partitions illisibles
    pour un PC (constaté en usage réel) -- Windows ne sait pas la remettre
    simplement en état de carte de stockage normale. Efface toute la table
    de partitions et recrée une seule partition (`--filesystem`, exFAT par
    défaut ou FAT32) occupant toute la carte, en quatre étapes réelles
    (`imaging/reset_card.py`, qui réutilise le verrouillage/démontage de
    `imaging/winlock.py`, et le formatage natif déjà en place pour la
    partition de jeux, `imaging/games_partition.py::format_games_
    partition` -- sauf pour le cas Windows+FAT32, § `imaging/reset_card.py
    ::format_reset_partition`, contourné par un formateur FAT32 écrit à la
    main : `Format-Volume`/`format.exe`/`diskpart` refusent tous le FAT32
    au-delà de 32 Go, ce qui le rend impossible en pratique sur une carte
    SD R36S typique avec l'outil natif). Écrit sur le périphérique brut,
    exactement comme `flash` : même confirmation explicite obligatoire
    (règle §2 n°6) -- réutilise `_confirm_flash`, son texte générique
    s'applique tel quel ici.

    Bug corrigé, confirmé sur du vrai matériel : le formatage échouait
    *silencieusement* (aucune partition exFAT créée, carte restée brute)
    -- chaque étape est désormais journalisée avant et après (`emit_log`)
    et suivie d'une progression réelle (`emit_step_progress`, jamais un
    minuteur, §2 n°5 -- la barre n'avance qu'à chaque étape effectivement
    terminée, avec son nom affiché à la place d'un débit/temps restant qui
    n'auraient pas de sens ici) : un échec à mi-parcours ne peut plus
    ressembler à un succès, ni rester muet sur l'étape en cause.

    Éjecte automatiquement à la fin (dernière étape suivie par la barre)
    -- contrairement à la première version de cette commande : bien
    qu'une partition exFAT neuve ne déclenche pas le risque de
    proposition de formatage propre à `--eject-after` (§4.6), l'éjection
    reste une étape réelle et attendue de l'opération elle-même, pas une
    action facultative proposée après coup. Best-effort (comme `--eject-
    after`) : un échec d'éjection ne remet jamais en cause la remise à
    zéro déjà réussie."""
    progress_file = _open_progress_file(args)
    try:
        device = _resolve_device_or_report(args)
        if device is None:
            return 1

        label = args.label or DEFAULT_RESET_LABEL
        filesystem = args.filesystem
        fs_label = "exFAT" if filesystem == "exfat" else "FAT32"

        # Demande explicite : « si le FAT32 s'avère impossible sur une
        # taille donnée, le dire clairement avant de lancer l'opération,
        # jamais après » -- avant même la confirmation, pour ne pas
        # demander à l'utilisateur de confirmer une opération dont on sait
        # déjà qu'elle ne peut pas aboutir. L'effacement de la table
        # (étape 1/4, juste en dessous) est irréversible ; découvrir
        # l'impossibilité seulement à l'étape de formatage (3/4) serait
        # déjà trop tard.
        if filesystem == "fat32":
            try:
                check_fat32_feasible(device)
            except (CardTooSmallForReset, Fat32VolumeTooSmall) as exc:
                emit_error("RESET_CARD_FAILED", f"FAT32 impossible sur cette carte : {exc}")
                return 1

        if not args.worker and not _confirm_flash(device):
            emit_error("CONFIRMATION_REFUSED", "Remise à zéro annulée : confirmation non reçue.")
            return 1

        emit_step_progress(0, _RESET_CARD_STEP_COUNT, "Effacement de la table de partitions…")
        emit_log(f"Effacement de la table de partitions de {device.display} ({device.path})...")
        try:
            erase_partition_table(device)
        except (OSError, subprocess.CalledProcessError, ValueError) as exc:
            emit_error("RESET_CARD_FAILED", f"Effacement de la table de partitions : {exc}")
            emit_done(False)
            return 1
        emit_log("Table de partitions effacée.")

        emit_step_progress(1, _RESET_CARD_STEP_COUNT, "Création de la partition…")
        try:
            plan = create_single_partition(device, filesystem)
        except (CardTooSmallForReset, OSError, subprocess.CalledProcessError, ValueError) as exc:
            emit_error("RESET_CARD_FAILED", f"Création de la partition : {exc}")
            emit_done(False)
            return 1
        emit_log(f"Nouvelle partition créée ({plan.size_bytes} octets).")

        emit_step_progress(2, _RESET_CARD_STEP_COUNT, f"Formatage {fs_label}…")
        try:
            drive_letter = format_reset_partition(device, plan, label, filesystem)
        except (Fat32VolumeTooSmall, OSError, subprocess.CalledProcessError, ValueError) as exc:
            emit_error("RESET_CARD_FAILED", f"Formatage {fs_label} : {exc}")
            emit_done(False)
            return 1
        emit_log(f"Partition formatée en {fs_label}, étiquette « {label} » posée.")
        if drive_letter:
            # Bug corrigé, confirmé sur du vrai matériel : `Get-Volume`
            # montrait déjà un volume exFAT correctement formaté, mais
            # sans lettre de lecteur il n'apparaissait pas dans
            # l'Explorateur -- la carte semblait non reconnue alors
            # qu'elle était parfaitement formatée.
            emit_log(f"La carte est disponible sous {drive_letter}:.")

        emit_step_progress(3, _RESET_CARD_STEP_COUNT, "Éjection de la carte…")
        emit_log("Éjection automatique de la carte...")
        try:
            eject_device(device.path)
        except Exception as exc:
            emit_log(f"Éjection automatique impossible : {exc}", level="warning")
        else:
            emit_log(f"{device.display} peut maintenant être retirée en toute sécurité.")

        emit_step_progress(_RESET_CARD_STEP_COUNT, _RESET_CARD_STEP_COUNT, "Terminé.")
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


def cmd_extract_boot(args: argparse.Namespace) -> int:
    device = _resolve_device_or_report(args)
    if device is None:
        return 1

    base_dir = Path(args.output_dir) if args.output_dir else None
    dest_dir = archives.new_archive_path(BOOT_LABEL, base_dir=base_dir)

    emit_log(f"Extraction du BOOT de {device.display} vers {dest_dir}")

    def on_progress(event: ProgressEvent) -> None:
        emit_progress(event.done, event.total, event.speed)

    try:
        copied = extract_boot(
            device, str(dest_dir), on_progress=on_progress, should_cancel=_make_should_cancel(args)
        )
    except OperationCancelled as exc:
        emit_error("CANCELLED", f"Extraction annulée après {exc.done} octets")
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

    emit_log(f"{copied} octets copiés dans {dest_dir}")
    emit_done(True)
    return 0


def cmd_extract_easyroms(args: argparse.Namespace) -> int:
    device = _resolve_device_or_report(args)
    if device is None:
        return 1

    base_dir = Path(args.output_dir) if args.output_dir else None
    dest_dir = archives.new_archive_path(EASYROMS_LABEL, base_dir=base_dir)

    emit_log(f"Extraction d'EASYROMS de {device.display} vers {dest_dir}")

    def on_progress(event: ProgressEvent) -> None:
        emit_progress(event.done, event.total, event.speed)

    try:
        copied = extract_easyroms(
            device, str(dest_dir), on_progress=on_progress, should_cancel=_make_should_cancel(args)
        )
    except OperationCancelled as exc:
        emit_error("CANCELLED", f"Extraction annulée après {exc.done} octets")
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

    emit_log(f"{copied} octets copiés dans {dest_dir}")
    emit_done(True)
    return 0


def cmd_identify(args: argparse.Namespace) -> int:
    """Lance `identify_from_boot_directory` sur un dossier local -- sans
    carte physique, sans montage, aucune commande système. Pensé pour
    valider le parseur DTB et la future table de correspondance sur des
    variantes de console fournies par d'autres utilisateurs (un dossier
    de `.dtb` reçu par e-mail, une archive déjà extraite...), pas
    seulement sur la propre carte du développeur."""
    result = identify_from_boot_directory(args.boot_dir)

    print(f"Dossier examiné : {result.scanned_directory}")
    if result.examined_files:
        print(f"Fichiers .dtb trouvés ({len(result.examined_files)}) :")
        for path in result.examined_files:
            print(f"  {path}")
    else:
        print("Aucun fichier .dtb trouvé.")

    if result.is_clone:
        print("Console clone détectée (nom de .dtb, critère validé par l'outil officiel ArkOS) : "
              "les systèmes prévus pour la R36S standard peuvent ne pas démarrer sur ce matériel ; "
              "dArkOS et EmuELEC annoncent prendre en charge ces consoles, "
              "EmuELEC a été vérifié sur un clone réel.")

    if result.info is not None:
        print(f"Carte identifiée : {result.info.board_compatible}")
        print(f"Écran : {result.info.panel_compatible or '(non trouvé)'}")
        if result.info.timings:
            print("Timings :")
            for key, value in result.info.timings.items():
                print(f"  {key} = {value}")
        return 0

    print(f"Échec de l'identification : {result.failure_reason.value}")
    return 1


def cmd_doublons_verify_journal(args: argparse.Namespace) -> int:
    """Signalé explicitement : « donne-moi une commande pour comparer le
    journal avec ce qui existe réellement à la source et à destination,
    pour vérifier qu'aucun fichier n'a été perdu » -- lecture seule,
    aucun périphérique, aucune élévation (`doublons/journal_check.py`,
    même principe d'autonomie que le reste du package)."""
    report = verify_journal(args.destination)

    if not report.entries:
        print(f"Aucune entrée de journal trouvée dans « {report.destination} ».")
        return 0

    counts = {"MOVED": 0, "RESTORED": 0, "LOST": 0, "DUPLICATED": 0}
    for entry in report.entries:
        counts[entry.status] += 1

    print(f"Journal de « {report.destination} » : {len(report.entries)} entrée(s).")
    print(f"  Déplacés (normal)      : {counts['MOVED']}")
    print(f"  Restaurés (annulation) : {counts['RESTORED']}")
    print(f"  Perdus                 : {counts['LOST']}")
    print(f"  En double (source+dest): {counts['DUPLICATED']}")

    if report.lost:
        print("\nFichiers perdus (absents à la fois de la source et de la destination) :")
        for entry in report.lost:
            print(f"  - source      : {entry.source}")
            print(f"    destination : {entry.destination}")
            print(f"    déplacé le  : {entry.moved_at}")

    if report.duplicated:
        print("\nFichiers présents des deux côtés (source ET destination, à nettoyer à la main) :")
        for entry in report.duplicated:
            print(f"  - {entry.source}")
            print(f"    {entry.destination}")

    if report.ok:
        print("\nAucun fichier perdu.")
        return 0
    print(f"\n{len(report.lost)} fichier(s) perdu(s) -- voir la liste ci-dessus.")
    return 1


def cmd_eject(args: argparse.Namespace) -> int:
    """Bug corrigé, confirmé sur du vrai matériel : sur Windows, ouvrir
    `\\\\.\\PhysicalDriveN` pour `IOCTL_STORAGE_EJECT_MEDIA` (`partitions/
    eject.py::_windows_eject` -> `imaging/winlock.py::eject_media`) exige
    l'élévation, exactement comme l'écriture brute (§4.3) -- mais cette
    commande tournait jusqu'ici uniquement dans le processus GUI, à
    privilèges normaux (`ERROR_ACCESS_DENIED`, erreur 5). `--worker`/
    `--progress-file`/`--cancel-file` (`_add_worker_args`, ci-dessous) la
    rendent utilisable par `gui.worker_runner.WorkerRunner` comme `backup`/
    `flash` -- la GUI ne l'appelle donc plus jamais directement, seulement
    via un worker élevé (`gui/main_window.py::_start_eject`)."""
    progress_file = _open_progress_file(args)
    try:
        device = _resolve_device_or_report(args)
        if device is None:
            return 1

        emit_log(f"Éjection de {device.display}")

        try:
            eject_device(device.path)
        except NotImplementedError as exc:
            emit_error("UNSUPPORTED_OS", str(exc))
            return 1
        except (OSError, subprocess.CalledProcessError) as exc:
            # Code dédié (déjà utilisé côté GUI pour un échec local avant ce
            # correctif, `friendly_error_message("EJECT_FAILED")`) plutôt
            # que le générique IO_ERROR -- son message (« ferme les
            # fichiers ouverts... ou retire-la manuellement ») est plus
            # précis pour ce cas précis qu'un renvoi vers « vérifie que la
            # carte est branchée ».
            emit_error("EJECT_FAILED", str(exc))
            return 1

        emit_log(f"{device.display} peut maintenant être retirée en toute sécurité.")
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
    _add_dev_args(list_parser)
    list_parser.set_defaults(func=cmd_list)

    backup_parser = subparsers.add_parser(
        "backup", help="Sauvegarde une carte SD (lecture seule) vers un fichier image"
    )
    backup_parser.add_argument(
        "--device", required=True, help="Chemin du périphérique à sauvegarder (voir `list`)"
    )
    backup_parser.add_argument(
        "--output", help="Fichier image de destination (requis sauf avec --estimate-only)"
    )
    backup_parser.add_argument(
        "--system-only",
        action="store_true",
        help=(
            "Ne sauvegarde que les partitions système, jusqu'à la fin de la dernière "
            "partition avant la partition de jeux (EASYROMS ou STORAGE) -- exclut les "
            "jeux, typiquement 8-9 Go au lieu de 100 Go sur une carte R36S d'origine"
        ),
    )
    backup_parser.add_argument(
        "--estimate-only",
        action="store_true",
        help=(
            "N'écrit rien : calcule et affiche seulement la taille estimée -- repli "
            "élevé pour --system-only quand l'estimation non élevée échoue (§4.3)"
        ),
    )
    backup_parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE_BYTES,
        help="Taille maximale acceptée en octets (défaut : 1 To)",
    )
    backup_parser.add_argument(
        "--eject-after",
        action="store_true",
        help=(
            "Éjecte la carte source automatiquement après la sauvegarde, dans ce même "
            "worker déjà élevé (§5 mode assisté, parcours de clonage) -- évite une "
            "seconde invite d'élévation dédiée juste pour l'éjection. Contrairement au "
            "`--eject-after` de `flash` (best-effort, ne fait jamais échouer l'opération), "
            "le résultat est rapporté séparément (événement `eject_result`) sans jamais "
            "faire échouer la sauvegarde elle-même, déjà réussie à ce stade"
        ),
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
    flash_parser.add_argument(
        "--eject-after",
        action="store_true",
        help=(
            "Éjecte la carte automatiquement après l'écriture et la vérification (§4.6 -- "
            "au moins une partition de tout firmware du catalogue est illisible pour "
            "Windows, qui propose sinon de la formater)"
        ),
    )
    _add_worker_args(flash_parser)
    _add_dev_args(flash_parser)
    flash_parser.set_defaults(func=cmd_flash)

    reset_card_parser = subparsers.add_parser(
        "reset-card",
        help=(
            "Efface toute la table de partitions et recrée une seule partition exFAT "
            "occupant toute la carte -- pour une carte laissée en plusieurs partitions "
            "illisibles après des essais de firmware"
        ),
    )
    reset_card_parser.add_argument(
        "--device", required=True, help="Chemin du périphérique cible (voir `list`)"
    )
    reset_card_parser.add_argument(
        "--label",
        default=DEFAULT_RESET_LABEL,
        help=f"Étiquette du volume créé (défaut : {DEFAULT_RESET_LABEL})",
    )
    reset_card_parser.add_argument(
        "--filesystem",
        choices=["exfat", "fat32"],
        default="exfat",
        help=(
            "Système de fichiers du volume créé (défaut : exfat) -- fat32 pour les "
            "consoles anciennes qui ne lisent pas l'exFAT (ex. SF3000HD)"
        ),
    )
    reset_card_parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE_BYTES,
        help="Taille maximale acceptée en octets (défaut : 1 To)",
    )
    _add_worker_args(reset_card_parser)
    _add_dev_args(reset_card_parser)
    reset_card_parser.set_defaults(func=cmd_reset_card)

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

    extract_boot_parser = subparsers.add_parser(
        "extract-boot",
        help="Copie la partition BOOT de la carte source vers un dossier horodaté de l'ordinateur",
    )
    extract_boot_parser.add_argument(
        "--device", required=True, help="Chemin du périphérique source (voir `list`)"
    )
    extract_boot_parser.add_argument(
        "--output-dir",
        help="Dossier où créer l'archive horodatée (défaut : ~/R36S Studio)",
    )
    extract_boot_parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE_BYTES,
        help="Taille maximale acceptée en octets (défaut : 1 To)",
    )
    extract_boot_parser.add_argument("--cancel-file", help=argparse.SUPPRESS)
    _add_dev_args(extract_boot_parser)
    extract_boot_parser.set_defaults(func=cmd_extract_boot)

    extract_easyroms_parser = subparsers.add_parser(
        "extract-easyroms",
        help="Copie la partition EASYROMS de la carte source vers un dossier horodaté de l'ordinateur",
    )
    extract_easyroms_parser.add_argument(
        "--device", required=True, help="Chemin du périphérique source (voir `list`)"
    )
    extract_easyroms_parser.add_argument(
        "--output-dir",
        help="Dossier où créer l'archive horodatée (défaut : ~/R36S Studio)",
    )
    extract_easyroms_parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE_BYTES,
        help="Taille maximale acceptée en octets (défaut : 1 To)",
    )
    extract_easyroms_parser.add_argument("--cancel-file", help=argparse.SUPPRESS)
    _add_dev_args(extract_easyroms_parser)
    extract_easyroms_parser.set_defaults(func=cmd_extract_easyroms)

    identify_parser = subparsers.add_parser(
        "identify",
        help="Teste le module d'identification (§4.5) sur un dossier local de .dtb, sans carte physique",
    )
    identify_parser.add_argument(
        "--boot-dir",
        required=True,
        help="Dossier contenant des .dtb à analyser (BOOT déjà extrait, ou fourni par un autre utilisateur)",
    )
    identify_parser.set_defaults(func=cmd_identify)

    doublons_verify_journal_parser = subparsers.add_parser(
        "doublons-verify-journal",
        help="Compare le journal d'un déplacement de doublons à l'état réel du disque (source/destination)",
    )
    doublons_verify_journal_parser.add_argument(
        "--destination",
        required=True,
        help="Dossier de destination du déplacement (celui qui contient journal.json)",
    )
    doublons_verify_journal_parser.set_defaults(func=cmd_doublons_verify_journal)

    eject_parser = subparsers.add_parser(
        "eject", help="Démonte toutes les partitions de la carte et l'éjecte"
    )
    eject_parser.add_argument("--device", required=True, help="Chemin du périphérique à éjecter (voir `list`)")
    eject_parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE_BYTES,
        help="Taille maximale acceptée en octets (défaut : 1 To)",
    )
    _add_worker_args(eject_parser)
    _add_dev_args(eject_parser)
    eject_parser.set_defaults(func=cmd_eject)

    gui_parser = subparsers.add_parser("gui", help="Lance l'assistant graphique (PySide6)")
    gui_parser.set_defaults(func=cmd_gui)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """`argv` à `None` retombe sur `sys.argv[1:]`, comme d'habitude. Dans
    les deux cas, une liste vide (aucune sous-commande) lance la GUI plutôt
    que de laisser `argparse` exiger une sous-commande. Nécessaire pour le
    binaire empaqueté (§6/§7, `packaging/entry.py`) : un double-clic depuis
    le Finder invoque l'exécutable sans le moindre argument, et une erreur
    argparse sur stderr ne serait jamais vue (aucune console visible) —
    l'appli semblerait juste ne rien faire. N'affecte aucun usage CLI
    existant, qui passe toujours une sous-commande explicite."""
    effective_argv = sys.argv[1:] if argv is None else argv
    if not effective_argv:
        effective_argv = ["gui"]
    parser = build_parser()
    args = parser.parse_args(effective_argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
