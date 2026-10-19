"""Flux du bot (`bot/session.py`, `bot/flows.py`) avec une API Telegram
entièrement simulée (`FakePort`) : aucun appel réseau, aucune vraie carte
(`find_games_folders` remplacée par un dossier temporaire). Le cœur, lui,
est le vrai (`doublons/run.py`, `tri/run.py`...)."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from r36s_studio import config as app_config
from r36s_studio.bot import flows
from r36s_studio.bot.cards import GamesFolder
from r36s_studio.bot.session import BotSession, menu_labels
from r36s_studio.strings import tr


class FakePort:
    def __init__(self):
        self.messages = {}  # id -> [texte, boutons]
        self.order = []
        self.edits = 0
        self.menus = []

    async def send(self, chat_id, text, buttons=None, menu=None):
        message_id = len(self.order) + 1
        self.messages[message_id] = [text, buttons]
        self.order.append(message_id)
        if menu:
            self.menus.append(menu)
        return message_id

    async def edit(self, chat_id, message_id, text, buttons=None):
        self.messages[message_id] = [text, buttons]
        self.edits += 1

    def texts(self):
        return [self.messages[i][0] for i in self.order]

    def pending(self):
        """Dernier message qui porte encore des boutons (hors Annuler seul)."""
        for message_id in reversed(self.order):
            text, buttons = self.messages[message_id]
            if buttons and not (len(buttons) == 1 and len(buttons[0]) == 1 and buttons[0][0].data.startswith("c")):
                return text, buttons
        return None


async def _wait_for_question(port, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        found = port.pending()
        if found:
            return found
        await asyncio.sleep(0.01)
    raise AssertionError(f"aucune question posée ; messages : {port.texts()}")


async def _click(session, port, label_part):
    text, buttons = await _wait_for_question(port)
    for row in buttons:
        for button in row:
            if label_part in button.label:
                await session.on_callback(button.data)
                await asyncio.sleep(0.02)
                return text
    raise AssertionError(f"bouton « {label_part} » absent de : {[b.label for r in buttons for b in r]}")


def _session(port):
    session = BotSession(port, chat_id=42, interval=0.05, min_gap=0.0)
    session.loop = asyncio.get_running_loop()
    return session


def _games(tmp_path) -> Path:
    root = tmp_path / "EASYROMS"
    (root / "snes").mkdir(parents=True)
    (root / "snes" / "Mario (Europe).sfc").write_bytes(b"m" * 2048)
    shutil.copyfile(root / "snes" / "Mario (Europe).sfc", root / "snes" / "Mario (Europe) copie.sfc")
    (root / "snes" / "Zelda (Japan).sfc").write_bytes(b"z" * 1024)
    return root


@pytest.fixture
def real_moves():
    app_config.save_config(app_config.AppConfig(doublons_simulation_mode=False))


def test_menu_uses_the_gui_tool_labels():
    labels = [row[0] for row in menu_labels()]
    assert labels == [tr("home_tile_find_duplicates"), tr("home_tile_filter_games"), tr("bot_menu_firmware")]
    assert set(flows.flows_by_label()) == set(labels)


def test_unknown_text_shows_the_menu_and_only_one_operation_runs_at_a_time():
    async def main():
        port = FakePort()
        session = _session(port)
        await session.on_text("bonjour", flows.flows_by_label())
        assert port.menus and port.texts()[-1] == tr("bot_help")
        never_ends = asyncio.Event()

        async def slow(_session):
            await never_ends.wait()

        await session.on_text("x", {"x": slow})
        await session.on_text("x", {"x": slow})
        assert port.texts()[-1] == tr("bot_busy")
        never_ends.set()

    asyncio.run(main())


def test_doublons_lists_then_asks_and_cancel_moves_nothing(tmp_path, real_moves):
    root = _games(tmp_path)

    async def main():
        port = FakePort()
        session = _session(port)
        with patch("r36s_studio.bot.flows.find_games_folders", return_value=[GamesFolder("Carte", str(root))]), patch(
            "r36s_studio.bot.flows.run_move"
        ) as run_move:
            task = asyncio.ensure_future(flows.doublons_flow(session))
            question = await _click(session, port, tr("bot_cancel"))
            await task
        run_move.assert_not_called()  # jamais sans confirmation (§2 n°6)
        assert "Mario (Europe)" in question
        main_lines = question.split(tr("bot_doublons_where"))[0]
        assert str(root) not in main_lines  # chemin seulement sur sa ligne à part
        assert tr("bot_path", path=str(root / "_doublons")) in question
        assert port.texts()[-1] == tr("bot_nothing_changed")

    asyncio.run(main())
    assert sorted(p.name for p in (root / "snes").iterdir()) == ["Mario (Europe) copie.sfc", "Mario (Europe).sfc", "Zelda (Japan).sfc"]


def test_doublons_confirmed_sets_one_copy_aside_and_reports_the_exact_count(tmp_path, real_moves):
    root = _games(tmp_path)

    async def main():
        port = FakePort()
        session = _session(port)
        with patch("r36s_studio.bot.flows.find_games_folders", return_value=[GamesFolder("Carte", str(root))]):
            task = asyncio.ensure_future(flows.doublons_flow(session))
            await _click(session, port, tr("bot_doublons_confirm", count=1))
            await task
        return port

    port = asyncio.run(main())
    kept = sorted(p.name for p in (root / "snes").iterdir())
    assert len([name for name in kept if name.startswith("Mario")]) == 1  # une copie toujours gardée
    assert len(list((root / "_doublons").rglob("*.sfc"))) == 1  # mise de côté, pas supprimée
    assert tr("bot_doublons_done", count=1, size=flows.format_size(2048)) in port.texts()[-1]
    # Message de progression : dernière édition = compte exact, sans bouton Annuler.
    progress = [m for m in port.messages.values() if m[0].startswith(tr("bot_doublons_moving", done=0, total=1)[:10])]
    assert progress[-1] == [tr("bot_doublons_moving", done=1, total=1), None]


def test_doublons_error_keeps_the_raw_detail_on_its_own_line(tmp_path):
    from r36s_studio.doublons.run import ScanOutcome

    async def main():
        port = FakePort()
        session = _session(port)
        with patch("r36s_studio.bot.flows.find_games_folders", return_value=[GamesFolder("Carte", str(tmp_path))]), patch(
            "r36s_studio.bot.flows.run_scan",
            return_value=ScanOutcome(error_code="DOUBLONS_IO_ERROR", error_detail=f"[Errno 5] {tmp_path}"),
        ):
            await flows.doublons_flow(session)
        return port.texts()[-1]

    text = asyncio.run(main())
    main_part, _, detail = text.partition("\n\n")
    assert str(tmp_path) not in main_part and "Errno" not in main_part
    assert detail == tr("bot_detail", detail=f"[Errno 5] {tmp_path}")


def test_no_card_found_says_so_simply():
    async def main():
        port = FakePort()
        with patch("r36s_studio.bot.flows.find_games_folders", return_value=[]):
            await flows.filter_flow(_session(port))
        return port.texts()[-1]

    assert asyncio.run(main()) == tr("bot_no_games_card")


def test_filter_criteria_preview_then_confirm_sets_aside_the_other_regions(tmp_path):
    root = _games(tmp_path)

    async def main():
        port = FakePort()
        session = _session(port)
        with patch("r36s_studio.bot.flows.find_games_folders", return_value=[GamesFolder("Carte", str(root))]):
            task = asyncio.ensure_future(flows.filter_flow(session))
            await _click(session, port, tr("bot_filter_preview"))  # aucun critère : refusé
            await _click(session, port, tr("filter_region_europe"))
            await _click(session, port, tr("bot_filter_preview"))
            preview = await _click(session, port, tr("filter_sort_button"))
            await task
        return port, preview

    port, preview = asyncio.run(main())
    assert tr("filter_criteria_needed") in port.texts()
    assert "Zelda (Japan).sfc" in preview
    assert (root / "_hors_filtre").is_dir() and list((root / "_hors_filtre").rglob("Zelda*"))
    assert (root / "snes" / "Mario (Europe).sfc").exists()


def test_firmware_knulli_needs_personal_use_then_downloads_with_the_required_sha(tmp_path):
    from r36s_studio.consoles_diverses.telechargement import FichierFirmware
    from r36s_studio.identify.firmware_download import DownloadOutcome, ResolveOutcome

    fichier = FichierFirmware(
        nom="knulli-rk3326-r36s-scarab-20260510.img.gz",
        url="https://github.com/x/knulli-rk3326-r36s-scarab-20260510.img.gz",
        taille=4096,
        sha256="e" * 64,
        depuis_derniere_release=True,
        appareil_notes="Game Console R36S",
    )

    def fake_download(asset, sha, on_progress=None, should_cancel=None):
        on_progress(1024, 4096, 1.0)
        on_progress(4096, 4096, 1.0)
        return DownloadOutcome(path=tmp_path / asset.name)

    async def main(agree):
        port = FakePort()
        session = _session(port)
        with patch("r36s_studio.bot.flows.resolve_auto_download", return_value=ResolveOutcome(fichier=fichier)), patch(
            "r36s_studio.bot.flows.download_firmware", side_effect=fake_download
        ) as download:
            task = asyncio.ensure_future(flows.firmware_flow(session))
            await _click(session, port, "KNULLI")
            await _click(session, port, tr("personal_use_checkbox", firmware="KNULLI") if agree else tr("bot_cancel"))
            await task
        return port, download

    port, download = asyncio.run(main(agree=False))
    download.assert_not_called()

    port, download = asyncio.run(main(agree=True))
    asset, sha = download.call_args.args
    assert asset.name == fichier.nom and sha == "e" * 64
    texts = port.texts()
    assert tr("knulli_notes_device_log", device="Game Console R36S") in texts
    final = texts[-1]
    assert final.startswith(tr("bot_firmware_downloaded", firmware="KNULLI"))
    assert final.endswith(tr("bot_path", path=str(tmp_path / fichier.nom)))
    progress_text = [m[0] for m in port.messages.values() if "%" in m[0]][-1]
    assert "100 %" in progress_text  # compte final exact


def test_firmware_rocknix_variant_is_always_chosen_by_the_user(tmp_path):
    from r36s_studio.identify.firmware_download import DownloadOutcome, VariantsOutcome
    from r36s_studio.identify.rocknix import RocknixAsset

    a = RocknixAsset("ROCKNIX-RK3326-a.img.gz", "https://github.com/x/a", 10)
    b = RocknixAsset("ROCKNIX-RK3326-b.img.gz", "https://github.com/x/b", 10)

    async def main():
        port = FakePort()
        session = _session(port)
        with patch("r36s_studio.bot.flows.list_rocknix_variants", return_value=VariantsOutcome([(a, "1" * 64), (b, None)])), patch(
            "r36s_studio.bot.flows.download_firmware", return_value=DownloadOutcome(path=tmp_path / b.name)
        ) as download:
            task = asyncio.ensure_future(flows.firmware_flow(session))
            await _click(session, port, "ROCKNIX")
            await _click(session, port, "-b.img.gz")
            await task
        return download

    download = asyncio.run(main())
    assert download.call_args.args[:2] == (b, None)


def test_firmware_manual_link_entry_only_sends_its_page():
    async def main():
        port = FakePort()
        session = _session(port)
        with patch("r36s_studio.bot.flows.download_firmware") as download:
            task = asyncio.ensure_future(flows.firmware_flow(session))
            await _click(session, port, tr("file_firmware_darkosen_title"))
            await task
        return port.texts()[-1], download

    text, download = asyncio.run(main())
    download.assert_not_called()
    assert text.endswith(tr("bot_path", path="https://github.com/djparentx/dArkOSen-R36S/releases"))


def test_a_file_that_resists_is_asked_about_from_the_worker_thread(tmp_path, real_moves):
    from r36s_studio.doublons.move import MoveFileFailed
    from r36s_studio.doublons.run import MoveOutcome

    root = _games(tmp_path)
    answers = []

    def fake_move(root_path, units, dry_run, destination, on_progress, should_cancel, ask_file_error):
        failure = MoveFileFailed(str(Path(root_path) / "snes" / "Mario (Europe) copie.sfc"), "move", "access_denied", "refusé")
        answers.append(ask_file_error(failure))
        return MoveOutcome(False, "PARTIAL_MOVE_COMPLETED", "1 ignoré", skipped=[(units[0], failure)])

    async def main():
        port = FakePort()
        session = _session(port)
        with patch("r36s_studio.bot.flows.find_games_folders", return_value=[GamesFolder("Carte", str(root))]), patch(
            "r36s_studio.bot.flows.run_move", side_effect=fake_move
        ):
            task = asyncio.ensure_future(flows.doublons_flow(session))
            await _click(session, port, tr("bot_doublons_confirm", count=1))
            question = await _click(session, port, tr("bot_skip_file"))
            await task
        return port, question

    port, question = asyncio.run(main())
    assert answers == [(True, False)]
    assert question.startswith(tr("bot_doublons_file_error", name="Mario (Europe) copie.sfc"))
    assert tr("bot_doublons_skipped", count=1) in port.texts()[-1]
