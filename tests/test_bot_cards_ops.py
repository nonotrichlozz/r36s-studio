"""Deuxième lot du bot : sauvegarde d'une carte avec ou sans jeux, remise à
zéro, raccourcis web. API Telegram simulée (`FakePort`), worker élevé
simulé (`run_worker` remplacé), aucune vraie carte."""

from __future__ import annotations

import asyncio
import json
from collections import namedtuple
from unittest.mock import patch

import pytest

from r36s_studio.bot import flows
from r36s_studio.bot.worker import WorkerResult
from r36s_studio.devices import Device
from r36s_studio.strings import tr

from tests.test_bot_flows import FakePort, _click, _session, _wait_for_question

GIB = 1024**3
DiskUsage = namedtuple("DiskUsage", "total used free")


def _card(path="/dev/fake-disk-test-7", display="Carte SanDisk", size=32 * GIB):
    return Device(path=path, display=display, size_bytes=size, removable=True, bus="USB", is_system=False, mountpoints=[])


@pytest.fixture
def documents(tmp_path):
    folder = tmp_path / "Documents" / "R36S Studio"
    with patch("r36s_studio.bot.flows.archives.default_archives_dir", return_value=folder):
        yield folder


def _devices(*devices):
    return patch("r36s_studio.bot.flows.filter_devices", return_value=list(devices)), patch(
        "r36s_studio.bot.flows.list_devices", return_value=list(devices)
    )


async def _drive(flow, port, session, clicks):
    task = asyncio.ensure_future(flow(session))
    questions = []
    for label in clicks:
        questions.append(await _click(session, port, label))
    await task
    return questions


def test_backup_refused_before_starting_when_the_destination_is_full(documents):
    """Destination artificiellement pleine : refus avec l'espace manquant,
    jamais de copie lancée (sur Telegram, on ne voit pas son disque)."""
    estimate = WorkerResult(ok=True, estimate=8 * GIB)
    port = FakePort()

    async def main():
        session = _session(port)
        list_patch, filter_patch = _devices(_card())
        with list_patch, filter_patch, patch("r36s_studio.bot.flows.run_worker", return_value=estimate) as run_worker, patch(
            "r36s_studio.bot.flows.shutil.disk_usage", return_value=DiskUsage(100 * GIB, 99 * GIB, 1 * GIB)
        ):
            await _drive(flows.backup_flow, port, session, ["Carte SanDisk"])
        return run_worker

    run_worker = asyncio.run(main())
    assert run_worker.call_count == 1  # l'estimation seulement, jamais la sauvegarde
    assert run_worker.call_args.args[0] == ["backup", "--device", "/dev/fake-disk-test-7", "--estimate-only"]
    from r36s_studio.imaging.backup import required_free_bytes

    needed = required_free_bytes(8 * GIB)  # image non compressée + son .sha256blocks
    expected = tr(
        "bot_backup_no_space",
        missing=flows.format_size(needed - GIB),
        needed=flows.format_size(needed),
        free=flows.format_size(GIB),
    )
    assert port.texts()[-1] == expected + "\n" + tr("bot_path", path=str(documents))
    assert "7.0 Go" in expected  # il manque ~7 Go
    assert not documents.exists()


@pytest.mark.parametrize("system_only", [False, True])
def test_backup_confirmed_writes_a_new_file_in_documents_never_config(documents, system_only):
    calls = []

    def fake_worker(argv, on_event=None, should_cancel=None):
        calls.append(argv)
        if "--estimate-only" in argv:
            return WorkerResult(ok=True, estimate=2 * GIB)
        on_event({"type": "progress", "done": GIB, "total": 2 * GIB, "speed": 1.0})
        on_event({"type": "phase", "name": "verify_source"})
        on_event({"type": "progress", "done": 2 * GIB, "total": 2 * GIB, "speed": 1.0})
        return WorkerResult(ok=True)

    port = FakePort()

    async def main():
        session = _session(port)
        list_patch, filter_patch = _devices(_card())
        with list_patch, filter_patch, patch("r36s_studio.bot.flows.run_worker", side_effect=fake_worker), patch(
            "r36s_studio.bot.flows.shutil.disk_usage", return_value=DiskUsage(100 * GIB, 10 * GIB, 90 * GIB)
        ):
            flow = flows.system_backup_flow if system_only else flows.backup_flow
            return await _drive(flow, port, session, ["Carte SanDisk", tr("bot_backup_confirm_button")])

    questions = asyncio.run(main())
    recap = questions[1]
    assert "Carte SanDisk — 32.0" in recap and "Rien ne sera effacé" in recap
    assert ("sans les jeux" in recap) is system_only
    backup_argv = calls[1]
    assert backup_argv[:3] == ["backup", "--device", "/dev/fake-disk-test-7"]
    assert ("--system-only" in backup_argv) is system_only
    output = backup_argv[backup_argv.index("--output") + 1]
    assert output.startswith(str(documents)) and ".config" not in output and output.endswith(".img")
    assert tr("bot_path", path=output) in recap  # chemin sur sa propre ligne
    assert port.texts()[-1] == tr("bot_backup_done", card="Carte SanDisk") + "\n" + tr("bot_path", path=output)
    progress = [m[0] for m in port.messages.values() if "(100 %)" in m[0]]
    assert progress == [tr("bot_backup_verifying", done="2.0 Go", total="2.0 Go", percent=100)]


def test_the_only_card_is_never_preselected():
    port = FakePort()

    async def main():
        session = _session(port)
        list_patch, filter_patch = _devices(_card())
        with list_patch, filter_patch, patch("r36s_studio.bot.flows.run_worker") as run_worker:
            task = asyncio.ensure_future(flows.reset_flow(session))
            text, buttons = await _wait_for_question(port)
            await _click(session, port, tr("bot_cancel"))
            await task
        return text, buttons, run_worker

    text, buttons, run_worker = asyncio.run(main())
    assert text == tr("bot_choose_card")
    assert [b.label for row in buttons for b in row] == ["Carte SanDisk — 32.0 Go", tr("bot_cancel")]
    run_worker.assert_not_called()


def test_reset_names_the_card_and_what_is_destroyed_then_needs_the_second_button():
    port = FakePort()

    async def main(confirm):
        session = _session(port)
        list_patch, filter_patch = _devices(_card(), _card("/dev/fake-disk-test-8", "Carte noname", 16 * GIB))
        with list_patch, filter_patch, patch("r36s_studio.bot.flows.run_worker", return_value=WorkerResult(ok=True)) as run_worker:
            questions = await _drive(
                flows.reset_flow, port, session, ["Carte noname", tr("bot_reset_confirm_button") if confirm else tr("bot_cancel")]
            )
        return questions, run_worker

    questions, run_worker = asyncio.run(main(confirm=False))
    recap = questions[1]
    assert "Carte noname — 16.0" in recap and "TOUT" in recap and "jeux" in recap and "sauvegardes" in recap
    run_worker.assert_not_called()
    assert port.texts()[-1] == tr("bot_nothing_changed")

    questions, run_worker = asyncio.run(main(confirm=True))
    argv = run_worker.call_args.args[0]
    assert argv[:3] == ["reset-card", "--device", "/dev/fake-disk-test-8"]
    assert run_worker.call_args.kwargs.get("should_cancel") is None  # jamais interrompue en cours
    assert port.texts()[-1] == tr("bot_reset_done", card="Carte noname")


def test_missing_sudo_rule_says_so_without_jargon():
    port = FakePort()
    refused = WorkerResult(error_code="ELEVATION_FAILED", error_detail="sudo: a password is required")

    async def main():
        session = _session(port)
        list_patch, filter_patch = _devices(_card())
        with list_patch, filter_patch, patch("r36s_studio.bot.flows.run_worker", return_value=refused):
            await _drive(flows.backup_flow, port, session, ["Carte SanDisk"])

    asyncio.run(main())
    main_text, _, detail = port.texts()[-1].partition("\n\n")
    assert main_text == tr("bot_sudo_missing") and "sudo:" not in main_text
    assert detail == tr("bot_detail", detail="sudo: a password is required")


def test_web_shortcuts_empty_by_default_then_one_button_each(tmp_path):
    from r36s_studio import shortcuts

    port = FakePort()

    async def run_once():
        session = _session(port)
        task = asyncio.ensure_future(flows.web_flow(session))
        if shortcuts.shortcuts_path().exists():
            await _click(session, port, "Mon tableau")
        await task

    asyncio.run(run_once())
    assert port.texts()[-1] == tr("bot_web_none") + "\n" + tr("bot_path", path=str(shortcuts.shortcuts_path()))

    shortcuts.shortcuts_path().write_text(
        json.dumps([{"nom": "Mon tableau", "url": "https://exemple.org/tableau"}, {"nom": "Piège", "url": "javascript:alert(1)"}]),
        encoding="utf-8",
    )
    asyncio.run(run_once())
    assert port.texts()[-1] == "Mon tableau\nhttps://exemple.org/tableau"
    asked = [m for m in port.messages.values() if m[0].startswith(tr("bot_web_choose"))]
    assert "Piège" not in asked[-1][0]
