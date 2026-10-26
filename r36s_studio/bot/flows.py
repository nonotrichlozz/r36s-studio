# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Les trois outils du bot, sur le même cœur que la GUI :

- doublons de l'espace de jeux (`doublons/run.py`) : analyse, liste, puis
  **confirmation à deux boutons** avant toute mise de côté (§2 n°6) --
  jamais une suppression : les doublons partent dans un dossier, comme
  dans la GUI ;
- filtre par région et par langue (`tri/run.py`, `tri/filter.py`) : choix
  des critères, aperçu, confirmation, mise de côté dans `_hors_filtre` ;
- choix et téléchargement d'un système (`identify/firmware_download.py`) :
  jamais d'écriture sur une carte (pas de flash depuis le bot) ;
- sauvegarde d'une carte, avec ou sans les jeux, et remise à zéro : worker
  élevé par sudo (`bot/worker.py`), espace vérifié avant toute sauvegarde,
  carte choisie par un bouton (jamais présélectionnée, même seule, §4.2),
  confirmation à deux boutons qui nomme la carte et ce qui sera détruit ;
- raccourcis web personnels (`r36s_studio/shortcuts.py`, liste livrée vide).

Vocabulaire (§5) : messages sans jargon ; chemins et messages bruts du
cœur toujours sur une ligne à part (`bot_detail`/`bot_path`)."""

from __future__ import annotations

import asyncio
import shutil
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import List, Optional, Tuple

from r36s_studio import config as app_config
from r36s_studio import shortcuts as web_shortcuts
from r36s_studio.devices import Device, list_devices
from r36s_studio.doublons import scan_cache
from r36s_studio.doublons.run import default_units_to_move, preferred_destination, run_move, run_scan
from r36s_studio.identify.firmware_catalog import FIRMWARE_CATALOG, FirmwareEntry
from r36s_studio.imaging import DEFAULT_RESET_LABEL
from r36s_studio.imaging.backup import required_free_bytes
from r36s_studio.imaging.source import DEFAULT_STALL_TIMEOUT_SECONDS
from r36s_studio.partitions import archives
from r36s_studio.safety import filter_devices
from r36s_studio.identify.firmware_download import (
    asset_for,
    download_firmware,
    list_rocknix_variants,
    resolve_auto_download,
)
from r36s_studio.strings import STRINGS, friendly_error_message, tr
from r36s_studio.tri.filter import build_filter_plan
from r36s_studio.tri.plan import FILTER_JOURNAL_FILENAME
from r36s_studio.tri.regions import LANGUAGE_CHOICES, REGION_CHOICES, RegionFilter
from r36s_studio.tri.run import run_apply, run_plan

from .cards import GamesFolder, find_games_folders
from .session import BotSession
from .worker import run_worker

MAX_LISTED = 15

__all__ = [
    "backup_flow",
    "doublons_flow",
    "filter_flow",
    "firmware_flow",
    "flows_by_label",
    "format_size",
    "reset_flow",
    "system_backup_flow",
    "web_flow",
]


def format_size(num_bytes: int) -> str:
    """Base 1024 partout (CLAUDE.md §5), mêmes unités que la GUI."""
    size = float(num_bytes)
    for unit in ("unit_bytes", "unit_kb", "unit_mb", "unit_gb"):
        if size < 1024 or unit == "unit_gb":
            return f"{int(size)} {tr(unit)}" if unit == "unit_bytes" else f"{size:.1f} {tr(unit)}"
        size /= 1024
    return f"{size:.1f} {tr('unit_tb')}"


def _error_text(main: str, detail: str = "") -> str:
    return main + (f"\n\n{tr('bot_detail', detail=detail)}" if detail else "")


async def _choose_games_folder(session: BotSession) -> Optional[GamesFolder]:
    await session.send(tr("bot_looking_for_card"))
    folders = await asyncio.to_thread(find_games_folders)
    if not folders:
        await session.send(tr("bot_no_games_card"))
        return None
    # Un bouton par carte, même s'il n'y en a qu'une : jamais de sélection
    # par défaut (§4.2).
    choices = [[(f"{folder.card}", str(index))] for index, folder in enumerate(folders)]
    choices.append([(tr("bot_cancel"), "cancel")])
    answer = await session.ask(tr("bot_choose_card"), choices)
    return None if answer == "cancel" else folders[int(answer)]


def _card_label(device: Device) -> str:
    return f"{device.display} — {format_size(device.size_bytes)}"


async def _choose_card(session: BotSession) -> Optional[Device]:
    """Cartes acceptées par `safety` (jamais un disque système), un bouton
    chacune, aucune présélection même seule (§4.2)."""
    await session.send(tr("bot_looking_for_card"))
    try:
        devices = await asyncio.to_thread(lambda: filter_devices(list_devices()))
    except (NotImplementedError, OSError) as exc:
        await session.send(_error_text(tr("bot_no_card"), str(exc)))
        return None
    if not devices:
        await session.send(tr("bot_no_card"))
        return None
    choices = [[(_card_label(device), str(index))] for index, device in enumerate(devices)]
    choices.append([(tr("bot_cancel"), "cancel")])
    answer = await session.ask(tr("bot_choose_card"), choices)
    return None if answer == "cancel" else devices[int(answer)]


def _worker_error_text(code: Optional[str], detail: str) -> str:
    main = tr("bot_sudo_missing") if code == "ELEVATION_FAILED" else friendly_error_message(code or "")
    return _error_text(main, detail)


# --- doublons ---------------------------------------------------------------


async def doublons_flow(session: BotSession) -> None:
    folder = await _choose_games_folder(session)
    if folder is None:
        return
    settings = app_config.load_config()
    hash_cache = scan_cache.load_hash_cache()

    def confirm_large_folder() -> bool:
        answer = session.ask_from_thread(
            tr("doublons_risk_large_folder"), [[(tr("bot_continue"), "yes"), (tr("bot_cancel"), "no")]]
        )
        return answer == "yes"

    def work(report, should_cancel):
        return run_scan(
            folder.path,
            settings.doublons_ignored_folders,
            hash_cache,
            on_progress=report,
            should_cancel=should_cancel,
            confirm_large_folder=confirm_large_folder,
        )

    outcome = await session.run_with_progress(
        lambda values: tr("bot_doublons_scanning", count=values[0] if values else 0), work
    )
    try:  # best-effort, comme la GUI : jamais un échec du résultat
        scan_cache.save_hash_cache(hash_cache)
        if outcome.result is not None:
            scan_cache.save_scan_cache(folder.path, outcome.result)
    except OSError:
        pass
    if outcome.cancelled:
        await session.send(tr("bot_cancelled"))
        return
    if outcome.error_code is not None:
        await session.send(_error_text(friendly_error_message(outcome.error_code), outcome.error_detail))
        return

    result = outcome.result
    units = default_units_to_move(result)
    if not units:
        await session.send(tr("doublons_empty"))
        return
    total_files = sum(len(unit.members) for unit in units)
    total_bytes = sum(unit.total_size_bytes for unit in units)
    destination = preferred_destination(folder.path, settings.doublons_last_destination)
    lines = [
        tr(
            "doublons_summary",
            files=result.files_scanned,
            exact=len(result.exact_duplicate_groups),
            versions=len(result.version_groups),
        ),
        tr("bot_doublons_found", count=total_files, size=format_size(total_bytes)),
    ]
    lines += [f"• {unit.representative.name} — {format_size(unit.total_size_bytes)}" for unit in units[:MAX_LISTED]]
    if len(units) > MAX_LISTED:
        lines.append(tr("bot_and_more", count=len(units) - MAX_LISTED))
    if settings.doublons_simulation_mode:
        lines.append(tr("bot_doublons_simulation"))
    lines.append(tr("bot_doublons_where"))
    lines.append(tr("bot_path", path=destination))
    answer = await session.ask(
        "\n".join(lines),
        [[(tr("bot_doublons_confirm", count=total_files), "move"), (tr("bot_cancel"), "cancel")]],
    )
    if answer != "move":
        await session.send(tr("bot_nothing_changed"))
        return

    if not settings.doublons_simulation_mode:
        # Mémorisée avant le résultat : le journal écrit au fil de l'eau doit
        # rester trouvable par « Tout annuler » de la GUI, même interrompu.
        app_config.record_doublons_destination(settings, destination)
        app_config.save_config(settings)

    def ask_file_error(exc) -> Tuple[bool, bool]:
        answer = session.ask_from_thread(
            _error_text(tr("bot_doublons_file_error", name=Path(exc.path).name), str(exc)),
            [
                [(tr("bot_skip_file"), "skip"), (tr("bot_skip_all"), "all")],
                [(tr("bot_stop"), "stop")],
            ],
        )
        return answer in ("skip", "all"), answer == "all"

    def move_work(report, should_cancel):
        return run_move(
            folder.path,
            units,
            settings.doublons_simulation_mode,
            destination=destination,
            on_progress=report,
            should_cancel=should_cancel,
            ask_file_error=ask_file_error,
        )

    moved = await session.run_with_progress(
        lambda values: tr("bot_doublons_moving", done=values[0], total=values[1])
        if values
        else tr("bot_doublons_moving", done=0, total=total_files),
        move_work,
    )
    moved_units = units if moved.ok else moved.moved_units
    done_text = tr(
        "bot_doublons_done",
        count=sum(len(unit.members) for unit in moved_units),
        size=format_size(sum(unit.total_size_bytes for unit in moved_units)),
    )
    if moved.ok:
        await session.send(done_text + "\n" + tr("bot_path", path=destination))
        return
    main = friendly_error_message(moved.error_code)
    if moved.skipped:
        main += "\n" + tr("bot_doublons_skipped", count=len(moved.skipped))
    await session.send(_error_text(done_text + "\n" + main, moved.error_detail))


# --- filtre par région et par langue ----------------------------------------


def _ft(key: str, **kwargs) -> str:
    """Texte du filtre (`filter_<clé>`), sinon celui du tri (`tri_<clé>`) --
    même règle que l'écran de la GUI."""
    specific = "filter_" + key
    return tr(specific if specific in STRINGS else "tri_" + key, **kwargs)


async def _choose_criteria(session: BotSession) -> Optional[RegionFilter]:
    regions: set = set()
    languages: set = set()
    message_id = None
    while True:
        def mark(selected: bool, label: str) -> str:
            return ("✓ " if selected else "") + label

        choices: List[List[Tuple[str, str]]] = [
            [(mark(r in regions, tr("filter_region_" + r.lower())), "r:" + r) for r in REGION_CHOICES],
            [(mark(lang in languages, tr("filter_language_" + lang.lower())), "l:" + lang) for lang in LANGUAGE_CHOICES],
            [(tr("bot_filter_preview"), "go"), (tr("bot_cancel"), "cancel")],
        ]
        text = tr("bot_filter_choose")
        if message_id is None:
            message_id = await session.send(text)
        answer = await session.ask(text, choices, message_id=message_id)
        if answer == "cancel":
            await session.send(tr("bot_nothing_changed"))
            return None
        if answer == "go":
            criteria = RegionFilter(regions=frozenset(regions), languages=frozenset(languages))
            if criteria.is_active():
                return criteria
            await session.send(tr("filter_criteria_needed"))
            message_id = None
            continue
        kind, _, value = answer.partition(":")
        target = regions if kind == "r" else languages
        target.symmetric_difference_update({value})


async def filter_flow(session: BotSession) -> None:
    folder = await _choose_games_folder(session)
    if folder is None:
        return
    criteria = await _choose_criteria(session)
    if criteria is None:
        return
    settings = app_config.load_config()
    build = partial(build_filter_plan, folder.path, criteria, settings.doublons_ignored_folders)
    outcome = await session.run_with_progress(
        lambda values: tr("bot_filter_scanning", count=values[0] if values else 0),
        lambda report, should_cancel: run_plan(build, on_progress=report, should_cancel=should_cancel),
    )
    if outcome.cancelled:
        await session.send(tr("bot_cancelled"))
        return
    if outcome.error_code is not None:
        await session.send(_error_text(_ft(f"error_{outcome.error_code.lower()}"), outcome.error_detail))
        return
    plan = outcome.plan
    games = plan.kept_count + len(plan.filtered_out)
    if games == 0:
        await session.send(_ft("preview_no_games", files=plan.files_seen))
        return
    if not plan.filtered_out:
        await session.send(_ft("preview_nothing", kept=plan.kept_count, no_region=len(plan.no_region)))
        return
    summary = _ft("preview_summary", filtered=len(plan.filtered_out), kept=plan.kept_count, no_region=len(plan.no_region))
    lines = [summary]
    lines += [f"• {move.members[0].name}" for move in plan.filtered_out[:MAX_LISTED]]
    if len(plan.filtered_out) > MAX_LISTED:
        lines.append(tr("bot_and_more", count=len(plan.filtered_out) - MAX_LISTED))
    lines.append(tr("bot_filter_confirm", count=plan.file_count()))
    answer = await session.ask("\n".join(lines), [[(tr("filter_sort_button"), "apply"), (tr("bot_cancel"), "cancel")]])
    if answer != "apply":
        await session.send(tr("bot_nothing_changed"))
        return
    total = plan.file_count()
    applied = await session.run_with_progress(
        lambda values: tr("bot_filter_moving", done=values[0], total=values[1])
        if values
        else tr("bot_filter_moving", done=0, total=total),
        lambda report, should_cancel: run_apply(
            plan, on_progress=report, should_cancel=should_cancel, journal_name=FILTER_JOURNAL_FILENAME
        ),
    )
    if applied.error_code is not None:
        await session.send(_error_text(_ft(f"error_{applied.error_code.lower()}"), applied.error_detail))
        return
    result = applied.result
    lines = [_ft("result_cancelled_title" if result.cancelled or result.aborted else "result_title")]
    lines.append(_ft("result_moved", count=result.moved_files))
    if result.failures:
        lines.append(_ft("result_failures", count=len(result.failures)))
    if result.skipped_existing:
        lines.append(_ft("result_skipped_existing", count=len(result.skipped_existing)))
    lines.append(tr("bot_filter_undo_hint"))
    await session.send("\n".join(lines))


# --- choix et téléchargement d'un système -----------------------------------


def _entry_label(entry: FirmwareEntry) -> str:
    return f"{tr(entry.title_key)} ({tr('firmware_status_' + entry.status)})"


async def firmware_flow(session: BotSession) -> None:
    choices = [[(_entry_label(entry), entry.id)] for entry in FIRMWARE_CATALOG]
    choices.append([(tr("bot_cancel"), "cancel")])
    answer = await session.ask(tr("bot_firmware_choose"), choices)
    entry = next((e for e in FIRMWARE_CATALOG if e.id == answer), None)
    if entry is None:
        await session.send(tr("bot_nothing_changed"))
        return
    title = tr(entry.title_key)
    if entry.releases_url is not None:
        # Lien manuel : rien à automatiser (images hors de GitHub, ou .7z).
        await session.send(tr("bot_firmware_manual", firmware=title) + "\n" + tr("bot_path", path=entry.releases_url))
        return

    if entry.auto_download is not None:
        if entry.non_commercial:
            agreed = await session.ask(
                tr("personal_use_text", firmware=title),
                [[(tr("personal_use_checkbox", firmware=title), "yes")], [(tr("bot_cancel"), "no")]],
            )
            if agreed != "yes":
                await session.send(tr("bot_nothing_changed"))
                return
        await session.send(tr("catalogue_install_searching_log", firmware=title, console="R36S"))
        resolved = await asyncio.to_thread(resolve_auto_download, entry.auto_download)
        if resolved.error_code is not None:
            await session.send(_error_text(friendly_error_message(resolved.error_code), resolved.error_detail))
            return
        fichier = resolved.fichier
        notes = (
            tr("knulli_notes_device_log", device=fichier.appareil_notes)
            if fichier.appareil_notes
            else tr("knulli_notes_missing_log") if fichier.depuis_derniere_release else None
        )
        if notes:
            await session.send(notes)
        asset, sha256 = asset_for(fichier), fichier.sha256
    else:  # ROCKNIX : la variante est toujours choisie par l'utilisateur
        variants = await asyncio.to_thread(list_rocknix_variants)
        if variants.error_code is not None:
            await session.send(_error_text(friendly_error_message(variants.error_code), variants.error_detail))
            return
        rows = [
            [(variant.name + (" ★" if variant.is_for_r36s else ""), str(index))]
            for index, (variant, _sha) in enumerate(variants.variants)
        ]
        rows.append([(tr("bot_cancel"), "cancel")])
        picked = await session.ask(tr("rocknix_variant_hint"), rows)
        if picked == "cancel":
            await session.send(tr("bot_nothing_changed"))
            return
        asset, sha256 = variants.variants[int(picked)]

    def render(values) -> str:
        if not values:
            return tr("execute_title_download_firmware", firmware=title)
        done, total = values[0], values[1]
        if total:
            return tr("bot_download_progress_total", firmware=title, done=format_size(done), total=format_size(total), percent=done * 100 // total)
        return tr("bot_download_progress", firmware=title, done=format_size(done))

    outcome = await session.run_with_progress(
        render,
        lambda report, should_cancel: download_firmware(asset, sha256, on_progress=report, should_cancel=should_cancel),
    )
    if not outcome.ok:
        main = tr("bot_cancelled") if outcome.error_code == "CANCELLED" else friendly_error_message(outcome.error_code)
        await session.send(_error_text(main, outcome.error_detail))
        return
    await session.send(tr("bot_firmware_downloaded", firmware=title) + "\n" + tr("bot_path", path=str(outcome.path)))


# --- sauvegarde d'une carte (avec ou sans les jeux) -------------------------


def _new_backup_path(system_only: bool) -> Path:
    """Convention de la GUI : `~/Documents/R36S Studio/`, jamais `~/.config`
    (§6) ; nom horodaté, jamais un fichier existant écrasé."""
    folder = archives.default_archives_dir()
    stamp = datetime.now().strftime(archives.TIMESTAMP_FORMAT)
    base = f"{'systeme' if system_only else 'sauvegarde'}_{stamp}"
    path, index = folder / f"{base}.img", 2
    while path.exists():
        path, index = folder / f"{base}-{index}.img", index + 1
    return path


def _free_bytes(folder: Path) -> int:
    existing = folder
    while not existing.exists() and existing != existing.parent:
        existing = existing.parent
    return shutil.disk_usage(existing).free


def _backup_render(values) -> str:
    if not values:
        return tr("bot_backup_starting")
    phase, done, total, stalled = values
    if stalled:
        return tr("bot_backup_stalled", seconds=stalled)
    key = "bot_backup_verifying" if phase == "verify_source" else "bot_backup_copying"
    percent = done * 100 // total if total else 0
    return tr(key, done=format_size(done), total=format_size(total), percent=percent)


async def _backup(session: BotSession, system_only: bool) -> None:
    device = await _choose_card(session)
    if device is None:
        return
    settings = app_config.load_config()
    base_args = ["backup", "--device", device.path] + (["--system-only"] if system_only else [])

    # Taille exacte d'abord (sauvegarde intelligente, §4.3 ; image jamais
    # compressée), comparée à l'espace libre : sur Telegram, on ne voit pas
    # son disque -- refus avant de commencer, avec ce qui manque.
    await session.send(tr("bot_backup_estimating", card=device.display))
    estimate = await asyncio.to_thread(run_worker, [*base_args, "--estimate-only"])
    if not estimate.ok or estimate.estimate is None:
        await session.send(_worker_error_text(estimate.error_code, estimate.error_detail))
        return
    output = _new_backup_path(system_only)
    needed = required_free_bytes(int(estimate.estimate))
    free = await asyncio.to_thread(_free_bytes, output.parent)
    if free < needed:
        await session.send(
            tr(
                "bot_backup_no_space",
                missing=format_size(needed - free),
                needed=format_size(needed),
                free=format_size(free),
            )
            + "\n"
            + tr("bot_path", path=str(output.parent))
        )
        return

    answer = await session.ask(
        tr(
            "bot_backup_system_confirm" if system_only else "bot_backup_confirm",
            card=_card_label(device),
            size=format_size(int(estimate.estimate)),
        )
        + "\n"
        + tr("bot_path", path=str(output)),
        [[(tr("bot_backup_confirm_button"), "go"), (tr("bot_cancel"), "cancel")]],
    )
    if answer != "go":
        await session.send(tr("bot_nothing_changed"))
        return

    argv = [*base_args, "--output", str(output)]
    if not settings.verify_backup_source:
        argv.append("--no-source-verify")
    if settings.source_stall_timeout_seconds != DEFAULT_STALL_TIMEOUT_SECONDS:
        argv += ["--stall-timeout", str(settings.source_stall_timeout_seconds)]
    output.parent.mkdir(parents=True, exist_ok=True)

    def work(report, should_cancel):
        state = {"phase": "copy", "done": 0, "total": 0}

        def on_event(event: dict) -> None:
            kind = event.get("type")
            if kind == "phase":
                state.update(phase=event.get("name"), done=0)
            elif kind == "progress":
                state.update(done=int(event.get("done", 0)), total=int(event.get("total", 0)))
            elif kind != "stalled":
                return
            report(state["phase"], state["done"], state["total"], event.get("seconds") if kind == "stalled" else None)

        return run_worker(argv, on_event=on_event, should_cancel=should_cancel)

    result = await session.run_with_progress(_backup_render, work)
    if result.ok:
        await session.send(tr("bot_backup_done", card=device.display) + "\n" + tr("bot_path", path=str(output)))
    elif result.error_code == "CANCELLED":
        await session.send(tr("bot_cancelled"))
    else:
        await session.send(_worker_error_text(result.error_code, result.error_detail))


async def backup_flow(session: BotSession) -> None:
    await _backup(session, system_only=False)


async def system_backup_flow(session: BotSession) -> None:
    await _backup(session, system_only=True)


# --- remise à zéro d'une carte ----------------------------------------------


async def reset_flow(session: BotSession) -> None:
    device = await _choose_card(session)
    if device is None:
        return
    settings = app_config.load_config()
    answer = await session.ask(
        tr("bot_reset_confirm", card=_card_label(device)),
        [[(tr("bot_reset_confirm_button"), "erase"), (tr("bot_cancel"), "cancel")]],
    )
    if answer != "erase":
        await session.send(tr("bot_nothing_changed"))
        return
    argv = [
        "reset-card",
        "--device",
        device.path,
        "--label",
        DEFAULT_RESET_LABEL,
        "--filesystem",
        settings.reset_card_filesystem,
    ]

    def work(report, _should_cancel):
        def on_event(event: dict) -> None:
            if event.get("type") == "step_progress":
                report(int(event.get("step_index", 0)) + 1, int(event.get("step_count", 0)))

        # Jamais interrompue en cours : une carte à moitié formatée serait pire.
        return run_worker(argv, on_event=on_event)

    result = await session.run_with_progress(
        lambda values: tr("bot_reset_running", step=values[0], count=values[1]) if values else tr("bot_reset_starting"),
        work,
        cancellable=False,
    )
    if result.ok:
        await session.send(tr("bot_reset_done", card=device.display))
    else:
        await session.send(_worker_error_text(result.error_code, result.error_detail))


# --- raccourcis web -----------------------------------------------------------


async def web_flow(session: BotSession) -> None:
    shortcuts = await asyncio.to_thread(web_shortcuts.load_shortcuts)
    if not shortcuts:
        await session.send(tr("bot_web_none") + "\n" + tr("bot_path", path=str(web_shortcuts.shortcuts_path())))
        return
    choices = [[(shortcut.name, str(index))] for index, shortcut in enumerate(shortcuts)]
    choices.append([(tr("bot_cancel"), "cancel")])
    answer = await session.ask(tr("bot_web_choose"), choices)
    if answer == "cancel":
        return
    shortcut = shortcuts[int(answer)]
    await session.send(f"{shortcut.name}\n{shortcut.url}")


def flows_by_label():
    """Libellé du menu (`session.menu_labels`) -> flux."""
    return {
        tr("home_tile_find_duplicates"): doublons_flow,
        tr("home_tile_filter_games"): filter_flow,
        tr("bot_menu_firmware"): firmware_flow,
        tr("home_tile_backup"): backup_flow,
        tr("home_tile_backup_system"): system_backup_flow,
        tr("home_tile_reset_card"): reset_flow,
        tr("home_tile_web"): web_flow,
    }
