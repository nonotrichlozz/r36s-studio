# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Copie de jeux et de BIOS sur une console KNULLI branchée en USB, en mode
ADB, sans retirer la carte SD (docs/knulli-adb.md).

Vérifié sur une RG40XXV sous KNULLI Scarab 20260511 :
- le shell `adb` est déjà root, `getprop` n'existe pas, `/etc/os-release`
  porte `OS_NAME="knulli"` ;
- `adb shell` ne rend **pas** le code de sortie de la commande (toujours
  0) : chaque contrôle lit une sortie (`stat`, `echo`), jamais un code ;
- `/userdata` est la carte SD (exFAT) : pas de limite à 4 Gio, mais
  `: ? * " < > | \\` interdits dans les noms ;
- liste des systèmes : `es_systems.cfg` (180 dossiers sous
  `/userdata/roms`), pas `GET /systems` qui omet les systèmes sans jeu ;
- API d'EmulationStation sur `127.0.0.1:1234` (côté console) :
  `/runningGame` répond 201 sans jeu en cours, `/reloadgames` 200.

Aucune écriture hors de `/userdata/roms` et `/userdata/bios`
(`_check_remote`, revérifié avant chaque commande qui écrit). Aucun fichier
existant remplacé sans `CopyItem.replace` (décidé par l'utilisateur)."""

from __future__ import annotations

import os
import shlex
import subprocess
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

from r36s_studio.tri.identify import MANIFEST_EXTENSIONS, identify_file
from r36s_studio.tri.plan import _ALWAYS_IGNORED, _JOURNAL_FILENAMES, _linked_groups
from r36s_studio.tri.tables import load_firmware_tables

from .adb import COMMAND_TIMEOUT_SECONDS, AdbCommandError, Runner
from .models import LinuxConsole

ROMS_ROOT = "/userdata/roms"
BIOS_ROOT = "/userdata/bios"
BIOS_FOLDER = "bios"
ES_SYSTEMS_PATH = "/usr/share/emulationstation/es_systems.cfg"
ES_API = "http://127.0.0.1:1234"
SPACE_MARGIN_BYTES = 500 * 1024**2
FORBIDDEN_NAME_CHARS = frozenset(':?*"<>|\\')
PARTIAL_NAME = ".r36s_studio_copie.partial"
POLL_SECONDS = 0.5
# Fichier en cours qui ne grossit plus : copie abandonnée (câble débranché,
# console éteinte) plutôt qu'une attente sans fin.
STALL_SECONDS = 60.0

# Consoles Linux joignables en ADB (pas de `getprop`), reconnues par
# `/etc/os-release`. Batocera seul (NAME=Batocera.linux sans
# OS_NAME=knulli) : ajouter sa règle ici une fois ses dossiers vérifiés.
LINUX_CONSOLE_RULES: Tuple[Tuple[str, Callable[[Dict[str, str]], bool]], ...] = (
    ("knulli", lambda release: release.get("OS_NAME", "").lower() == "knulli"),
)


class NotEnoughSpace(Exception):
    def __init__(self, needed: int, free: int):
        super().__init__(f"{needed} octets nécessaires, {free} libres")
        self.needed = needed
        self.free = free


@dataclass
class CopyItem:
    local: Path
    remote: str
    folder: str  # dossier de système (« psx ») ou « bios »
    size: int
    renamed_from: str = ""  # nom d'origine quand il a fallu le rendre sûr
    existing_size: Optional[int] = None  # déjà sur la console
    replace: bool = False


@dataclass
class Skipped:
    local: Path
    reason: str  # not_recognised | format_not_accepted | disc_missing_files | name_in_disc | same_destination | exists
    detail: str = ""


@dataclass
class CopyPlan:
    root: Path
    items: List[CopyItem] = field(default_factory=list)
    skipped: List[Skipped] = field(default_factory=list)
    free_bytes: Optional[int] = None

    def by_folder(self) -> Dict[str, Tuple[int, int]]:
        grouped: Dict[str, Tuple[int, int]] = {}
        for item in self.items:
            count, size = grouped.get(item.folder, (0, 0))
            grouped[item.folder] = (count + 1, size + item.size)
        return dict(sorted(grouped.items()))

    def conflicts(self) -> List[CopyItem]:
        return [item for item in self.items if item.existing_size is not None]

    def bytes_needed(self) -> int:
        """Ce que la carte doit recevoir : un fichier remplacé libère la
        place de l'ancien."""
        return sum(item.size - (item.existing_size or 0) if item.replace else item.size for item in self.items)

    def missing_bytes(self) -> int:
        """0 si tout tient avec la marge de 500 Mio, sinon ce qui manque."""
        if self.free_bytes is None:
            return 0
        return max(0, self.bytes_needed() + SPACE_MARGIN_BYTES - self.free_bytes)

    def skip(self, item: CopyItem, reason: str = "exists") -> None:
        self.items.remove(item)
        self.skipped.append(Skipped(item.local, reason, item.remote))


@dataclass
class CopyResult:
    copied: List[CopyItem] = field(default_factory=list)
    failures: List[Tuple[CopyItem, str]] = field(default_factory=list)
    cancelled: bool = False


# --- Commandes ------------------------------------------------------------


def _default_runner(args: List[str], timeout: float) -> "subprocess.CompletedProcess":
    # UTF-8 explicite : la console parle UTF-8, Windows décoderait en cp1252
    # (noms de jeux accentués).
    return subprocess.run(
        args,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _shell(adb_path: str, serial: str, command: str, runner: Runner, timeout: float = COMMAND_TIMEOUT_SECONDS) -> str:
    try:
        result = runner([adb_path, "-s", serial, "shell", command], timeout)
    except subprocess.TimeoutExpired as exc:
        raise AdbCommandError(f"adb shell {command} : délai dépassé ({timeout}s).") from exc
    except OSError as exc:
        raise AdbCommandError(f"adb shell {command} : {exc}") from exc
    return result.stdout or ""


def _check_remote(path: str) -> str:
    """Seule porte vers une commande qui écrit : chemin absolu sous
    `/userdata/roms/<dossier>/` ou `/userdata/bios/`, sans `..`."""
    pure = PurePosixPath(path)
    parts = pure.parts
    allowed = (pure.is_relative_to(ROMS_ROOT) and len(parts) > 4) or (pure.is_relative_to(BIOS_ROOT) and len(parts) > 3)
    if not allowed or any(part in ("..", ".", "") for part in parts[1:]) or str(pure) != path:
        raise ValueError(f"Chemin refusé sur la console : {path}")
    return path


def parse_os_release(text: str) -> Dict[str, str]:
    values = {}
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if sep:
            values[key] = value.strip().strip('"')
    return values


def identify_linux_console(os_release: str) -> Optional[LinuxConsole]:
    release = parse_os_release(os_release)
    for console_id, rule in LINUX_CONSOLE_RULES:
        if rule(release):
            return LinuxConsole(console_id, release.get("OS_DATE") or release.get("VERSION", ""))
    return None


def detect_linux_console(adb_path: str, serial: str, *, runner: Runner = _default_runner) -> Optional[LinuxConsole]:
    return identify_linux_console(_shell(adb_path, serial, "cat /etc/os-release", runner))


def parse_es_systems(text: str) -> Dict[str, FrozenSet[str]]:
    """dossier de `/userdata/roms` -> extensions acceptées (minuscules)."""
    systems: Dict[str, FrozenSet[str]] = {}
    for system in ElementTree.fromstring(text).iter("system"):
        path = PurePosixPath((system.findtext("path") or "").strip())
        if path.parent == PurePosixPath(ROMS_ROOT):
            systems[path.name] = frozenset(ext.lower() for ext in (system.findtext("extension") or "").split())
    return systems


def read_systems(adb_path: str, serial: str, *, runner: Runner = _default_runner) -> Dict[str, FrozenSet[str]]:
    try:
        systems = parse_es_systems(_shell(adb_path, serial, f"cat {ES_SYSTEMS_PATH}", runner))
    except ElementTree.ParseError as exc:
        raise AdbCommandError(f"{ES_SYSTEMS_PATH} illisible : {exc}") from exc
    if not systems:
        raise AdbCommandError(f"{ES_SYSTEMS_PATH} : aucun système sous {ROMS_ROOT}")
    return systems


def read_free_bytes(adb_path: str, serial: str, *, runner: Runner = _default_runner) -> int:
    lines = _shell(adb_path, serial, "df -P -B1 /userdata", runner).strip().splitlines()
    try:
        return int(lines[-1].split()[3])
    except (IndexError, ValueError) as exc:
        raise AdbCommandError(f"df illisible : {lines}") from exc


def read_existing(adb_path: str, serial: str, folders: List[str], *, runner: Runner = _default_runner) -> Dict[str, int]:
    """Chemin (minuscules : exFAT ignore la casse) -> taille, pour les
    fichiers déjà présents dans les dossiers visés."""
    if not folders:
        return {}
    dirs = " ".join(shlex.quote(folder) for folder in folders)
    output = _shell(adb_path, serial, f"find {dirs} -type f -printf '%s|%p\\n' 2>/dev/null", runner, timeout=60)
    existing = {}
    for line in output.splitlines():
        size, sep, path = line.partition("|")
        if sep and size.isdigit():
            existing[path.lower()] = int(size)
    return existing


def _remote_size(adb_path: str, serial: str, path: str, runner: Runner) -> Optional[int]:
    output = _shell(adb_path, serial, f"stat -c %s {shlex.quote(path)} 2>/dev/null", runner).strip()
    return int(output) if output.isdigit() else None


def reload_games_if_idle(adb_path: str, serial: str, *, runner: Runner = _default_runner) -> str:
    """« reloaded », « game_running » (rien demandé : un rechargement
    pendant une partie la couperait) ou « unavailable »."""
    status = f"curl -s -m 5 -o /dev/null -w %{{http_code}} {ES_API}"
    try:
        running = _shell(adb_path, serial, f"{status}/runningGame", runner).strip()
        if running == "200":
            return "game_running"
        if running != "201":
            return "unavailable"
        return "reloaded" if _shell(adb_path, serial, f"{status}/reloadgames", runner).strip() == "200" else "unavailable"
    except AdbCommandError:
        return "unavailable"


# --- Aperçu ---------------------------------------------------------------


def safe_name(name: str) -> str:
    return "".join("_" if char in FORBIDDEN_NAME_CHARS or ord(char) < 32 else char for char in name)


def _walk(root: Path) -> List[Path]:
    files = []
    for directory, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d.lower() not in _ALWAYS_IGNORED)
        for name in sorted(names):
            if not name.startswith(".") and name not in _JOURNAL_FILENAMES:
                files.append(Path(directory) / name)
    return files


def _target(root: Path, path: Path, folders_lower: Dict[str, str]) -> Tuple[Optional[str], List[str]]:
    """Premier dossier de système du chemin en partant du haut (le dossier
    choisi compris : `psx/tools/x.cue` reste dans `psx`) et le reste du
    chemin sous lui. (None, []) si aucun."""
    parts = [root.name, *path.relative_to(root).parts]
    for index in range(len(parts) - 1):
        folder = folders_lower.get(parts[index].lower())
        if folder is not None:
            return folder, parts[index + 1 :]
    return None, []


def build_copy_plan(root: str, systems: Dict[str, FrozenSet[str]]) -> CopyPlan:
    """Range chaque fichier par système : d'abord le nom d'un dossier du
    chemin (`psx/…`, `bios/…`), sinon l'identification du tri (extension
    et en-tête, `tri/identify.py`). Lecture seule, rien n'est copié."""
    root_path = Path(root).resolve()
    plan = CopyPlan(root=root_path)
    folders_lower = {folder.lower(): folder for folder in systems}
    folders_lower[BIOS_FOLDER] = BIOS_FOLDER
    knulli_folders = load_firmware_tables()["knulli"].folders
    files = _walk(root_path)

    groups, missing = _linked_groups(files)
    group_of = {member: group for group in groups for member in group}
    taken: Dict[str, Path] = {}
    for path in files:
        folder, sub = _target(root_path, path, folders_lower)
        group = group_of.get(path)
        if folder is None:
            if group is not None:
                plan.skipped.append(Skipped(path, "not_recognised", "disc_image"))
                continue
            result = identify_file(path)
            folder = knulli_folders.get(result.system_id or "")
            if folder is None or folder not in systems:
                plan.skipped.append(Skipped(path, "not_recognised", result.reason))
                continue
            sub = [path.name]
        if folder != BIOS_FOLDER:
            accepted = systems[folder]
            manifests = [m for m in group or [] if m.suffix.lower() in MANIFEST_EXTENSIONS]
            if group is not None and any(m in missing for m in manifests):
                plan.skipped.append(Skipped(path, "disc_missing_files", ", ".join(n for m in manifests for n in missing.get(m, []))))
                continue
            ok = path.suffix.lower() in accepted or any(m.suffix.lower() in accepted for m in manifests)
            if not ok:
                plan.skipped.append(Skipped(path, "format_not_accepted", path.suffix or path.name))
                continue
        safe = [safe_name(part) for part in sub]
        renamed = "/".join(sub) if safe != sub else ""
        if renamed and group is not None:
            # Renommer un fichier cité par un .cue/.m3u casserait le disque.
            plan.skipped.append(Skipped(path, "name_in_disc", renamed))
            continue
        base = BIOS_ROOT if folder == BIOS_FOLDER else f"{ROMS_ROOT}/{folder}"
        remote = "/".join([base, *safe])
        if remote.lower() in taken:
            plan.skipped.append(Skipped(path, "same_destination", str(taken[remote.lower()])))
            continue
        taken[remote.lower()] = path
        try:
            size = path.stat().st_size
        except OSError:
            plan.skipped.append(Skipped(path, "not_recognised", "unreadable"))
            continue
        plan.items.append(CopyItem(path, _check_remote(remote), folder, size, renamed))
    return plan


def attach_console_state(plan: CopyPlan, existing: Dict[str, int], free_bytes: int) -> None:
    plan.free_bytes = free_bytes
    for item in plan.items:
        item.existing_size = existing.get(item.remote.lower())


def plan_folders(plan: CopyPlan) -> List[str]:
    """Dossiers de système visés sur la console (`read_existing`)."""
    return sorted({BIOS_ROOT if item.folder == BIOS_FOLDER else f"{ROMS_ROOT}/{item.folder}" for item in plan.items})


# --- Copie ----------------------------------------------------------------


def _popen(argv: List[str]):
    return subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def _push_one(adb_path, serial, item, runner, on_bytes, should_cancel) -> Optional[str]:
    """Copie un fichier par `adb push` vers un nom temporaire du même
    dossier, puis le renomme une fois sa taille vérifiée. Renvoie un motif
    d'échec, ou None. `ConnectionAbortedError` : annulé (rien ne reste)."""
    remote = _check_remote(item.remote)
    parent = str(PurePosixPath(remote).parent)
    partial = f"{parent}/{PARTIAL_NAME}"
    quoted_partial = shlex.quote(partial)
    _shell(adb_path, serial, f"mkdir -p {shlex.quote(parent)} && rm -f {quoted_partial}", runner)
    if not item.replace and _remote_size(adb_path, serial, remote, runner) is not None:
        return "exists"  # apparu depuis l'aperçu : jamais écrasé sans demande

    process = _popen([adb_path, "-s", serial, "push", str(item.local), partial])
    last_size, last_change = -1, time.monotonic()
    while process.poll() is None:
        if should_cancel():
            process.terminate()
            process.wait()
            _shell(adb_path, serial, f"rm -f {quoted_partial}", runner)
            raise ConnectionAbortedError()
        time.sleep(POLL_SECONDS)
        size = _remote_size(adb_path, serial, partial, runner) or 0
        if size != last_size:
            last_size, last_change = size, time.monotonic()
            on_bytes(size)
        elif time.monotonic() - last_change > STALL_SECONDS:
            process.terminate()
            process.wait()
            _shell(adb_path, serial, f"rm -f {quoted_partial}", runner)
            return "stalled"

    if process.returncode != 0:
        _shell(adb_path, serial, f"rm -f {quoted_partial}", runner)
        return "push_failed"
    if _remote_size(adb_path, serial, partial, runner) != item.size:
        _shell(adb_path, serial, f"rm -f {quoted_partial}", runner)
        return "size_mismatch"
    _shell(adb_path, serial, f"mv -f {quoted_partial} {shlex.quote(remote)}", runner)
    if _remote_size(adb_path, serial, remote, runner) != item.size:
        return "size_mismatch"
    on_bytes(item.size)
    return None


def copy_plan(
    adb_path: str,
    serial: str,
    plan: CopyPlan,
    *,
    runner: Runner = _default_runner,
    on_progress: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Callable[[], bool] = lambda: False,
) -> CopyResult:
    """Fichier par fichier, progression réelle en octets (taille du
    fichier en cours relevée sur la console). Refuse avant de commencer
    si la place manque (marge de 500 Mio comprise)."""
    free = read_free_bytes(adb_path, serial, runner=runner)
    plan.free_bytes = free
    if plan.missing_bytes():
        raise NotEnoughSpace(plan.bytes_needed() + SPACE_MARGIN_BYTES, free)

    result = CopyResult()
    total = sum(item.size for item in plan.items)
    done = 0
    for item in plan.items:
        if should_cancel():
            result.cancelled = True
            break

        def on_bytes(size: int, base=done, name=item.local.name) -> None:
            if on_progress is not None:
                on_progress(base + size, total, name)

        try:
            reason = _push_one(adb_path, serial, item, runner, on_bytes, should_cancel)
        except ConnectionAbortedError:
            result.cancelled = True
            break
        except (AdbCommandError, OSError) as exc:
            reason = f"adb_error: {exc}"
        if reason is None:
            result.copied.append(item)
        else:
            result.failures.append((item, reason))
        done += item.size
    return result


__all__ = [
    "BIOS_ROOT",
    "ROMS_ROOT",
    "SPACE_MARGIN_BYTES",
    "CopyItem",
    "CopyPlan",
    "CopyResult",
    "LinuxConsole",
    "NotEnoughSpace",
    "Skipped",
    "attach_console_state",
    "build_copy_plan",
    "copy_plan",
    "detect_linux_console",
    "identify_linux_console",
    "parse_es_systems",
    "plan_folders",
    "read_existing",
    "read_free_bytes",
    "read_systems",
    "reload_games_if_idle",
    "safe_name",
]
