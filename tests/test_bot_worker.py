"""Worker élevé du bot (`bot/worker.py`) : `sudo -n` + script dédié,
commandes limitées, événements JSON Lines lus en flux, Annuler par fichier.
Aucun vrai sous-processus : `Popen` simulé."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

import pytest

from r36s_studio.bot import worker


class FakeProcess:
    def __init__(self, events, stderr_text="", returncode=0, delay=0.0):
        lines = [json.dumps(e) + "\n" for e in events]
        self.stdout = self._slow(lines, delay)
        self._stderr_text = stderr_text
        self.returncode = returncode

    @staticmethod
    def _slow(lines, delay):
        for line in lines:
            time.sleep(delay)
            yield line

    def wait(self):
        return self.returncode


def _popen(process, seen):
    def factory(command, stdout, stderr, **kwargs):
        seen.append(command)
        stderr.write(process._stderr_text)
        stderr.flush()
        return process

    return factory


def test_only_bot_commands_ever_reach_sudo():
    with pytest.raises(ValueError):
        worker.run_worker(["flash", "--image", "x", "--device", "/dev/fake-disk-test-1"])


def test_events_are_read_and_the_command_is_exactly_the_sudo_rule():
    seen, events = [], []
    process = FakeProcess(
        [
            {"type": "log", "level": "info", "msg": "Sauvegarde…"},
            {"type": "progress", "done": 4, "total": 8, "speed": 1.0},
            {"type": "estimate", "size_bytes": 8},
            {"type": "done", "ok": True},
        ]
    )
    with patch("r36s_studio.bot.worker.subprocess.Popen", _popen(process, seen)):
        result = worker.run_worker(["backup", "--device", "/dev/fake-disk-test-1", "--estimate-only"], on_event=events.append)

    command = seen[0]
    assert command[:3] == ["sudo", "-n", worker.WORKER_COMMAND]
    assert command[3:7] == ["backup", "--device", "/dev/fake-disk-test-1", "--estimate-only"]
    assert command[7] == "--worker" and command[8] == "--cancel-file"
    assert result.ok and result.estimate == 8 and len(events) == 4


def test_sudo_refusal_without_any_event_is_elevation_failed():
    process = FakeProcess([], stderr_text="sudo: a password is required\n", returncode=1)
    with patch("r36s_studio.bot.worker.subprocess.Popen", _popen(process, [])):
        result = worker.run_worker(["reset-card", "--device", "/dev/fake-disk-test-1"])
    assert (result.ok, result.error_code, result.error_detail) == (False, "ELEVATION_FAILED", "sudo: a password is required")


def test_worker_error_event_is_kept_even_if_done_follows():
    process = FakeProcess([{"type": "error", "code": "INSUFFICIENT_DISK_SPACE", "msg": "plein"}, {"type": "done", "ok": False}])
    with patch("r36s_studio.bot.worker.subprocess.Popen", _popen(process, [])):
        result = worker.run_worker(["backup", "--device", "/dev/fake-disk-test-1", "--output", "/tmp/x.img"])
    assert (result.ok, result.error_code, result.error_detail) == (False, "INSUFFICIENT_DISK_SPACE", "plein")


def test_cancel_creates_the_cancel_file_the_worker_watches():
    seen = []
    cancel_paths = []

    class Watching(FakeProcess):
        def wait(self):
            return 0

    process = Watching([{"type": "progress", "done": 1, "total": 9, "speed": 0}] * 3 + [{"type": "done", "ok": False}], delay=0.05)

    def factory(command, stdout, stderr, **kwargs):
        seen.append(command)
        cancel_paths.append(command[command.index("--cancel-file") + 1])
        return process

    def on_event(_event):
        from pathlib import Path

        if Path(cancel_paths[0]).exists():
            on_event.found = True

    on_event.found = False
    with patch("r36s_studio.bot.worker.subprocess.Popen", factory):
        worker.run_worker(["backup", "--device", "/dev/fake-disk-test-1"], on_event=on_event, should_cancel=lambda: True, poll_seconds=0.01)
    assert on_event.found
