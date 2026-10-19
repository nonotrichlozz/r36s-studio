"""Copie de jeux sur une console KNULLI en ADB (`android/knulli.py`) : fausse
console (runner `adb shell` qui interprète les quelques commandes utilisées
sur un dictionnaire chemin -> taille) et faux `adb push` (Popen remplacé) --
aucune commande adb réelle."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from r36s_studio.android import adb, knulli
from r36s_studio.android.knulli import (
    NotEnoughSpace,
    attach_console_state,
    build_copy_plan,
    copy_plan,
    identify_linux_console,
    reload_games_if_idle,
)

KNULLI_OS_RELEASE = 'NAME=Batocera.linux\nVERSION=42\nID=buildroot\nOS_NAME="knulli"\nOS_DATE=20260511\n'
ES_SYSTEMS = """<?xml version="1.0"?><systemList>
<system><name>psx</name><path>/userdata/roms/psx</path><extension>.cue .chd .m3u</extension></system>
<system><name>snes</name><path>/userdata/roms/snes</path><extension>.sfc .smc .zip .7z</extension></system>
<system><name>kodi</name><path>/userdata/kodi</path><extension>.sh</extension></system>
</systemList>"""
SYSTEMS = knulli.parse_es_systems(ES_SYSTEMS)


def _done(stdout):
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


class FakeConsole:
    def __init__(self, free=10 * 1024**3, running_game=False):
        self.files = {}
        self.free = free
        self.running_game = running_game
        self.commands = []

    def __call__(self, args, timeout):
        command = args[4]
        self.commands.append(command)
        words = shlex.split(command.replace("&&", ";"))
        if command == "cat /etc/os-release":
            return _done(KNULLI_OS_RELEASE)
        if command.startswith("cat /usr/share"):
            return _done(ES_SYSTEMS)
        if words[0] == "df":
            return _done(f"Filesystem 1-blocks Used Available Capacity Mounted\n/dev/x 1 1 {self.free} 1% /userdata\n")
        if words[0] == "find":
            dirs = [w for w in words[1:] if w.startswith("/")]
            return _done("".join(f"{s}|{p}\n" for p, s in self.files.items() if any(p.startswith(d + "/") for d in dirs)))
        if words[0] == "stat":
            size = self.files.get(words[3])
            return _done("" if size is None else str(size))
        if words[0] == "curl":
            if words[-1].endswith("/runningGame"):
                return _done("200" if self.running_game else "201")
            return _done("200")
        for part in command.split("&&"):
            part = shlex.split(part)
            if part[:2] == ["rm", "-f"]:
                self.files.pop(part[2], None)
            elif part[:2] == ["mv", "-f"]:
                self.files[part[3]] = self.files.pop(part[2])
        return _done("")


class FakePush:
    """`adb push` : remplit le fichier distant en `steps` appels à poll()."""

    def __init__(self, console, steps=3, returncode=0, short_by=0):
        self.console, self.steps, self.code, self.short_by = console, steps, returncode, short_by
        self.pushed = []

    def __call__(self, argv):
        self.local, self.remote = Path(argv[4]), argv[5]
        self.size = self.local.stat().st_size - self.short_by
        self.calls, self.returncode, self.terminated = 0, None, False
        self.pushed.append(self.remote)
        return self

    def poll(self):
        if self.returncode is None and not self.terminated:
            self.calls += 1
            self.console.files[self.remote] = self.size * min(self.calls, self.steps) // self.steps
            if self.calls >= self.steps:
                self.returncode = self.code
        return self.returncode

    def terminate(self):
        self.terminated, self.returncode = True, -15

    def wait(self):
        return self.returncode


@pytest.fixture
def console(monkeypatch):
    fake = FakeConsole()
    push = FakePush(fake)
    monkeypatch.setattr(knulli, "_popen", push)
    monkeypatch.setattr(knulli, "POLL_SECONDS", 0)
    fake.push = push
    return fake


def _write(path: Path, size=1000) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00" * size)
    return path


def _collection(tmp_path: Path) -> Path:
    root = tmp_path / "Mes jeux"
    _write(root / "PS1" / "psx" / "Game.cue").write_text('FILE "Game.bin" BINARY\n')
    _write(root / "PS1" / "psx" / "Game.bin", 5000)
    _write(root / "PS1" / "psx" / "Other.7z")
    _write(root / "PS1" / "psx" / "Lost.cue").write_text('FILE "Lost.bin" BINARY\n')
    _write(root / "Mario.sfc", 2000)  # hors dossier de système : extension
    _write(root / "readme.txt")
    _write(root / "BIOS" / "scph1001.bin", 512)
    return root


def test_plan_sorts_by_folder_or_extension_and_explains_the_rest(tmp_path):
    plan = build_copy_plan(str(_collection(tmp_path)), SYSTEMS)

    assert sorted((i.remote, i.size) for i in plan.items) == [
        ("/userdata/bios/scph1001.bin", 512),
        ("/userdata/roms/psx/Game.bin", 5000),  # cité par Game.cue, accepté avec lui
        ("/userdata/roms/psx/Game.cue", (tmp_path / "Mes jeux" / "PS1" / "psx" / "Game.cue").stat().st_size),
        ("/userdata/roms/snes/Mario.sfc", 2000),
    ]
    assert sorted((s.local.name, s.reason) for s in plan.skipped) == [
        ("Lost.cue", "disc_missing_files"),
        ("Other.7z", "format_not_accepted"),  # .7z que psx n'accepte pas
        ("readme.txt", "not_recognised"),
    ]
    assert plan.by_folder()["psx"][0] == 2


def test_forbidden_names_get_a_safe_name_and_never_leave_the_game_folders(tmp_path):
    assert knulli.safe_name('Zelda: A <Link>?.sfc') == "Zelda_ A _Link__.sfc"
    for bad in ("/userdata/roms/../system/x", "/userdata/roms/psx", "/etc/passwd", "/userdata/bios/", "/userdata/roms/psx//x"):
        with pytest.raises(ValueError):
            knulli._check_remote(bad)


@pytest.mark.skipif(sys.platform == "win32", reason="Windows refuse déjà ces caractères dans un nom de fichier")
def test_forbidden_name_is_renamed_in_the_plan(tmp_path):
    _write(tmp_path / "snes" / "Zelda: Link.sfc")
    item = build_copy_plan(str(tmp_path), SYSTEMS).items[0]
    assert item.remote == "/userdata/roms/snes/Zelda_ Link.sfc" and item.renamed_from == "Zelda: Link.sfc"


def test_not_enough_space_refuses_before_copying_anything(tmp_path, console):
    _write(tmp_path / "snes" / "Big.sfc", 2000)
    plan = build_copy_plan(str(tmp_path), SYSTEMS)
    console.free = knulli.SPACE_MARGIN_BYTES + 1999  # il manque 1 octet avec la marge

    with pytest.raises(NotEnoughSpace):
        copy_plan("adb", "S", plan, runner=console)
    assert console.push.pushed == [] and plan.missing_bytes() == 1


def test_copy_has_real_progress_and_checks_the_size_then_reload(tmp_path, console):
    _write(tmp_path / "snes" / "Mario.sfc", 3000)
    plan = build_copy_plan(str(tmp_path), SYSTEMS)
    progress = []

    result = copy_plan("adb", "S", plan, runner=console, on_progress=lambda d, t, n: progress.append((d, t)))

    assert [i.remote for i in result.copied] == ["/userdata/roms/snes/Mario.sfc"] and not result.failures
    assert console.files == {"/userdata/roms/snes/Mario.sfc": 3000}  # fichier temporaire renommé
    assert progress[0] == (1000, 3000) and progress[-1] == (3000, 3000)
    assert reload_games_if_idle("adb", "S", runner=console) == "reloaded"


def test_existing_file_is_never_overwritten_without_asking(tmp_path, console):
    _write(tmp_path / "snes" / "Mario.sfc", 3000)
    console.files["/userdata/roms/snes/mario.sfc"] = 10  # exFAT : casse ignorée
    plan = build_copy_plan(str(tmp_path), SYSTEMS)
    attach_console_state(plan, knulli.read_existing("adb", "S", knulli.plan_folders(plan), runner=console), 10**12)

    assert [i.existing_size for i in plan.conflicts()] == [10]
    console.files["/userdata/roms/snes/Mario.sfc"] = console.files.pop("/userdata/roms/snes/mario.sfc")
    result = copy_plan("adb", "S", plan, runner=console)
    assert [r for _i, r in result.failures] == ["exists"] and console.push.pushed == []

    plan.items[0].replace = True
    assert plan.bytes_needed() == 3000 - 10
    result = copy_plan("adb", "S", plan, runner=console)
    assert result.copied and console.files["/userdata/roms/snes/Mario.sfc"] == 3000

    plan.skip(plan.items[0])  # « Ignorer »
    assert plan.items == [] and plan.skipped[-1].reason == "exists"


def test_cancel_removes_the_partial_file(tmp_path, console):
    console.push.steps = 10**9
    _write(tmp_path / "snes" / "Mario.sfc", 3000)
    calls = iter([False, False, False, True])

    result = copy_plan("adb", "S", build_copy_plan(str(tmp_path), SYSTEMS), runner=console, should_cancel=lambda: next(calls, True))

    assert result.cancelled and console.push.terminated and console.files == {}


@pytest.mark.parametrize("code, short_by, reason", [(1, 0, "push_failed"), (0, 7, "size_mismatch")])
def test_failed_or_short_copy_leaves_nothing(tmp_path, console, code, short_by, reason):
    console.push.code, console.push.short_by = code, short_by
    _write(tmp_path / "snes" / "Mario.sfc", 3000)

    result = copy_plan("adb", "S", build_copy_plan(str(tmp_path), SYSTEMS), runner=console)

    assert [r for _i, r in result.failures] == [reason] and console.files == {}


def test_game_running_means_no_reload():
    fake = FakeConsole(running_game=True)
    assert reload_games_if_idle("adb", "S", runner=fake) == "game_running"
    assert not any("reloadgames" in c for c in fake.commands)


def test_only_knulli_is_recognised():
    assert identify_linux_console(KNULLI_OS_RELEASE).id == "knulli"
    assert identify_linux_console('NAME=Batocera.linux\nVERSION=42\n') is None  # Batocera seul : plus tard
    assert identify_linux_console("") is None


def test_detection_reports_knulli_only_when_getprop_is_missing():
    def knulli_runner(args, timeout):
        if args[1] == "devices":
            return _done("List of devices attached\n0123456789\tdevice product:occam model:Nexus_4\n")
        if args[-1] == "getprop":
            return _done("/bin/sh: 1: getprop: not found\n")
        return FakeConsole()(args, timeout)

    result = adb.detect_connected_device("adb", runner=knulli_runner)
    assert result.state == "ready" and result.linux_console.id == "knulli" and result.linux_console.version == "20260511"

    calls = []

    def phone_runner(args, timeout):
        calls.append(args)
        if args[1] == "devices":
            return _done("List of devices attached\nABC\tdevice\n")
        return _done("[ro.product.model]: [RP Flip 2]\n")

    assert adb.detect_connected_device("adb", runner=phone_runner).linux_console is None
    assert len(calls) == 2  # aucune commande de plus pour un vrai Android
