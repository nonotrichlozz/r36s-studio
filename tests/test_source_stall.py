"""Chien de garde de lecture (imaging/source.py::StallWatchedReader) -- cas
réel : la carte noname bloque parfois une lecture pendant des heures, sans
erreur ni donnée. Faux flux qui bloque sur un `threading.Event` ; délais
du module réduits pour que les tests durent moins d'une seconde."""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import struct
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from r36s_studio import __main__ as cli
from r36s_studio import config as app_config
from r36s_studio.config import AppConfig
from r36s_studio.devices import Device
from r36s_studio.imaging import source as source_module
from r36s_studio.imaging.backup import backup_device
from r36s_studio.imaging.copy import OperationCancelled
from r36s_studio.imaging.source import SourceNotResponding, StallWatchedReader


@pytest.fixture(autouse=True)
def _fast_watchdog():
    with patch.object(source_module, "_WAIT_TICK_SECONDS", 0.02), patch.object(
        source_module, "STALL_NOTICE_SECONDS", 0.05
    ):
        yield


class _BlockingSource(io.BytesIO):
    """Renvoie normalement les octets jusqu'à `block_at`, puis bloque les
    lectures suivantes (sans erreur, sans donnée) jusqu'à `release`, ou
    pendant `delay` secondes si fourni."""

    def __init__(self, data: bytes, block_at: int, delay=None):
        super().__init__(data)
        self._block_at = block_at
        self._delay = delay
        self.release = threading.Event()

    def read(self, n=-1):
        if self.tell() >= self._block_at and not self.release.is_set():
            self.release.wait(self._delay)
        return super().read(n)


@pytest.fixture
def blocking_sources():
    created = []
    yield created
    for source in created:  # libère les threads de lecture restés bloqués
        source.release.set()


def test_blocked_read_raises_source_not_responding_and_reports_the_wait(blocking_sources):
    source = _BlockingSource(os.urandom(4096), block_at=1024)
    blocking_sources.append(source)
    stalls = []
    reader = StallWatchedReader(source, timeout=0.3, on_stall=lambda waited, limit: stalls.append((waited, limit)))

    assert len(reader.read(1024)) == 1024
    with pytest.raises(SourceNotResponding) as excinfo:
        reader.read(1024)

    assert excinfo.value.done == 1024
    assert "ne répond plus" in str(excinfo.value)
    # L'attente qui grandit est signalée, jamais une barre figée en silence.
    assert len(stalls) >= 2 and stalls[0][0] < stalls[-1][0] and stalls[-1][1] == 0.3


def test_slow_read_under_the_limit_completes(blocking_sources):
    data = os.urandom(2048)
    source = _BlockingSource(data, block_at=1024, delay=0.15)
    blocking_sources.append(source)
    stalls = []
    reader = StallWatchedReader(source, timeout=1.0, on_stall=lambda *a: stalls.append(a))

    assert reader.read(1024) + reader.read(1024) == data
    assert stalls  # signalée pendant l'attente, sans abandon


def test_cancel_while_blocked_raises_operation_cancelled(blocking_sources):
    source = _BlockingSource(os.urandom(2048), block_at=0)
    blocking_sources.append(source)
    cancel_at = time.monotonic() + 0.1
    reader = StallWatchedReader(source, timeout=30, should_cancel=lambda: time.monotonic() > cancel_at)

    started = time.monotonic()
    with pytest.raises(OperationCancelled):
        reader.read(1024)
    assert time.monotonic() - started < 5  # Annuler reste actif pendant le blocage


def test_stuck_stream_is_not_closed_on_exit(blocking_sources):
    """Le thread bloqué tient le verrou du flux : `close()` bloquerait aussi."""
    source = _BlockingSource(os.urandom(1024), block_at=0)
    blocking_sources.append(source)
    with pytest.raises(SourceNotResponding):
        with StallWatchedReader(source, timeout=0.1) as reader:
            reader.read(512)
    assert not source.closed


def test_errors_from_the_stream_are_raised_unchanged():
    class _Broken(io.BytesIO):
        def read(self, n=-1):
            raise OSError("lecture impossible")

    with pytest.raises(OSError, match="lecture impossible"):
        StallWatchedReader(_Broken(), timeout=1).read(10)


# --- bout en bout : sauvegarde puis CLI -------------------------------------


@contextlib.contextmanager
def _no_prep(path):
    yield path


def _fake_sd_bytes(sectors: int = 20) -> bytes:
    data = bytearray(os.urandom(sectors * 512))
    data[446:510] = bytes(64)
    data[446 + 4] = 0x0B
    data[446 + 8 : 446 + 12] = struct.pack("<I", 1)
    data[446 + 12 : 446 + 16] = struct.pack("<I", sectors - 1)
    data[510:512] = b"\x55\xaa"
    return bytes(data)


def _make_device(path="/dev/fake-disk-test-3") -> Device:
    return Device(
        path=path, display="Carte SD factice", size_bytes=1 << 20, removable=True, bus="USB",
        is_system=False, mountpoints=[],
    )


@patch("r36s_studio.imaging.backup.prepared_source", side_effect=_no_prep)
def test_backup_of_a_card_that_stops_answering_fails_with_source_not_responding(mock_prep, tmp_path, blocking_sources):
    raw = tmp_path / "fake_sd.img"
    raw.write_bytes(_fake_sd_bytes())
    real_open = builtins.open

    def fake_open(path, mode="r", *args, **kwargs):
        # La carte bloque après 4 Kio lus par la boucle de copie.
        if str(path) == str(raw) and "rb" in mode:
            source = _BlockingSource(raw.read_bytes(), block_at=4096)
            blocking_sources.append(source)
            return source
        return real_open(path, mode, *args, **kwargs)

    stalls = []
    with patch("r36s_studio.imaging.backup.compute_backup_size", return_value=20 * 512), patch(
        "r36s_studio.imaging.backup.open", side_effect=fake_open, create=True
    ):
        with pytest.raises(SourceNotResponding) as excinfo:
            backup_device(
                _make_device(str(raw)), str(tmp_path / "out.img"), block_size=1024, stall_timeout=0.3,
                on_stall=lambda *a: stalls.append(a),
            )
    assert excinfo.value.done == 4096
    assert stalls


@patch("r36s_studio.__main__.shutil.disk_usage")
@patch("r36s_studio.__main__.backup_device")
@patch("r36s_studio.__main__.list_devices")
def test_cli_emits_stalled_events_then_source_not_responding(mock_list, mock_backup, mock_usage, tmp_path, capsys):
    mock_list.return_value = [_make_device()]
    mock_usage.return_value = MagicMock(free=10**12)

    def fake_backup(device, output, on_stall, stall_timeout, **kwargs):
        on_stall(6.2, stall_timeout)
        on_stall(7.4, stall_timeout)
        raise SourceNotResponding(stall_timeout, 4096)

    mock_backup.side_effect = fake_backup
    args = cli.build_parser().parse_args(
        ["backup", "--device", "/dev/fake-disk-test-3", "--output", str(tmp_path / "out.img"), "--stall-timeout", "30"]
    )

    assert cli.cmd_backup(args) == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert [e for e in events if e["type"] == "stalled"] == [
        {"type": "stalled", "seconds": 6, "limit": 30},
        {"type": "stalled", "seconds": 7, "limit": 30},
    ]
    assert [e["code"] for e in events if e["type"] == "error"] == ["SOURCE_NOT_RESPONDING"]


def test_cli_stall_timeout_defaults_to_60_seconds():
    args = cli.build_parser().parse_args(["backup", "--device", "/dev/fake-disk-test-3", "--output", "x.img"])
    assert args.stall_timeout == 60


@pytest.mark.parametrize("raw, expected", [(120, 120), (5, 60), (True, 60), ("60", 60)])
def test_config_stall_timeout_is_validated(raw, expected):
    # Via le module, jamais `from ... import config_path` : `conftest.py`
    # redirige `config.config_path` -- une copie importée pointerait sur le
    # vrai config.json de la machine (déjà arrivé en écrivant ce test).
    app_config.config_path().write_text(json.dumps({"source_stall_timeout_seconds": raw}), encoding="utf-8")
    assert app_config.load_config().source_stall_timeout_seconds == expected
    assert AppConfig().source_stall_timeout_seconds == 60


# --- GUI : l'état bloqué est visible, puis effacé ---------------------------


def test_log_panel_shows_stalled_state_then_clears_it(qapp):
    from r36s_studio.gui.screens import LogPanel

    panel = LogPanel()
    panel.start_operation("Sauvegarde")
    panel.show_stalled(12, 60)
    panel.show_stalled(13, 60)

    assert "13" in panel._speed_label.text() and "60" in panel._speed_label.text()
    assert panel._speed_label.property("role") == "dangerMessage"
    assert len(panel._log_view.toPlainText().splitlines()) == 1  # une seule ligne au journal par blocage

    panel.update_progress(4096, 8192, 1_000_000.0)
    assert panel._speed_label.property("role") == "secondary"


def test_gui_passes_stall_timeout_only_when_changed(qapp):
    from r36s_studio.gui.main_window import MainWindow

    with patch("r36s_studio.gui.main_window.list_devices", return_value=[]), patch(
        "r36s_studio.gui.main_window.filter_devices", return_value=[]
    ):
        window = MainWindow()
    window._mode, window._device, window._file_path = "backup", _make_device(), "/tmp/out.img"

    def argv():
        runner_class = MagicMock()
        with patch("r36s_studio.gui.main_window.WorkerRunner", runner_class):
            window._start_worker()
        return runner_class.call_args.args[0]

    assert "--stall-timeout" not in argv()
    window._app_config.source_stall_timeout_seconds = 300
    assert argv()[-2:] == ["--stall-timeout", "300"]


# --- lecture des tables et sortie du worker ---------------------------------


def test_read_threads_are_daemon_and_reported_as_stuck(blocking_sources):
    source = _BlockingSource(os.urandom(1024), block_at=0)
    blocking_sources.append(source)
    with pytest.raises(SourceNotResponding):
        StallWatchedReader(source, timeout=0.1).read(512)

    stuck = [t for t in threading.enumerate() if t.name == source_module._READ_THREAD_NAME]
    assert stuck and all(t.daemon for t in stuck)
    assert source_module.has_stuck_reads()


def test_partition_table_reads_are_watched(tmp_path, blocking_sources):
    from r36s_studio.imaging.backup import compute_backup_size
    from r36s_studio.imaging.system_backup import compute_system_boundary

    raw = tmp_path / "fake_sd.img"
    raw.write_bytes(_fake_sd_bytes())

    def fake_open(path, mode="r", *args, **kwargs):
        source = _BlockingSource(raw.read_bytes(), block_at=0)  # bloque dès le MBR
        blocking_sources.append(source)
        return source

    with patch("r36s_studio.imaging.backup.open", side_effect=fake_open, create=True):
        with pytest.raises(SourceNotResponding):
            compute_backup_size(str(raw), 1 << 20, stall_timeout=0.2)
    with patch("r36s_studio.imaging.system_backup.list_partitions", return_value=[]), patch(
        "r36s_studio.imaging.system_backup.open", side_effect=fake_open, create=True
    ):
        with pytest.raises(SourceNotResponding):
            compute_system_boundary(str(raw), stall_timeout=0.2)


_FOREVER_WORKER = r"""
import atexit, io, sys, threading
from unittest.mock import MagicMock, patch
from r36s_studio import __main__ as cli
from r36s_studio.devices import Device
from r36s_studio.imaging.source import StallWatchedReader

class Forever(io.RawIOBase):  # le ReadFile Windows qui ne rend jamais la main
    def readable(self):
        return True
    def readinto(self, buffer):
        threading.Event().wait()

def fake_backup(device, output, stall_timeout, on_stall, **kwargs):
    with StallWatchedReader(io.BufferedReader(Forever()), stall_timeout, on_stall) as source:
        source.read(4096)

# Ne s'exécute que par une sortie normale : `os._exit` le saute.
atexit.register(lambda: print("finalisation normale", file=sys.stderr))
device = Device(path="/dev/fake-disk-test-9", display="Carte factice", size_bytes=1 << 20,
                removable=True, bus="USB", is_system=False, mountpoints=[])
with patch.object(cli, "_resolve_device", return_value=device), \
        patch.object(cli, "backup_device", fake_backup), \
        patch.object(cli.shutil, "disk_usage", return_value=MagicMock(free=10**12)):
    cli.main(sys.argv[1:])
print("main() a rendu la main", file=sys.stderr)
"""


@pytest.mark.real_subprocess
def test_worker_exits_quickly_even_with_a_read_blocked_forever(tmp_path):
    import subprocess
    import sys

    script = tmp_path / "forever_worker.py"
    script.write_text(_FOREVER_WORKER, encoding="utf-8")
    progress = tmp_path / "progress.jsonl"
    stall_timeout = 2
    # Jamais le vrai config.json ni le vrai dossier de l'utilisateur.
    env = dict(os.environ, APPDATA=str(tmp_path), HOME=str(tmp_path), XDG_CONFIG_HOME=str(tmp_path))
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = repo_root + os.pathsep + env.get("PYTHONPATH", "")

    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, str(script), "backup", "--device", "/dev/fake-disk-test-9",
         "--output", str(tmp_path / "out.img"), "--worker", "--progress-file", str(progress),
         "--stall-timeout", str(stall_timeout)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    elapsed = time.monotonic() - started

    assert completed.returncode == 1, completed.stderr
    assert elapsed < stall_timeout + 15  # démarrage de l'interpréteur compris
    assert "finalisation normale" not in completed.stderr  # sortie par os._exit
    assert "main() a rendu la main" not in completed.stderr
    events = [json.loads(line) for line in progress.read_text(encoding="utf-8").splitlines()]
    assert [e["code"] for e in events if e["type"] == "error"] == ["SOURCE_NOT_RESPONDING"]
    assert events[-1] == {"type": "done", "ok": False}  # écrit et vidé avant de quitter
