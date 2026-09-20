"""Tests de `gui/android_runner.py` -- threads Qt de l'outil « Console
Android » (étape 1). `android.adb`/`android.platform_tools` sont mockés au
niveau module (même principe que `tests/test_consoles_diverses_search_
runner.py`) : `run()` est appelée directement (jamais `start()`), aucun
vrai thread ni accès réseau/adb réel."""

from __future__ import annotations

from unittest.mock import patch

from r36s_studio.android.models import DetectionResult
from r36s_studio.android.platform_tools import PlatformToolsDownloadCancelledError, PlatformToolsError
from r36s_studio.gui.android_runner import (
    AndroidDetectRunner,
    AndroidPlatformToolsDownloadRunner,
    AndroidPlatformToolsSizeRunner,
)


@patch("r36s_studio.gui.android_runner.adb.detect_connected_device")
def test_detect_runner_emits_finished_detect(mock_detect, qapp):
    expected = DetectionResult(state="no_device")
    mock_detect.return_value = expected

    runner = AndroidDetectRunner("adb")
    results = []
    runner.finished_detect.connect(lambda result: results.append(result))

    runner.run()

    assert results == [expected]
    mock_detect.assert_called_once_with("adb")


@patch("r36s_studio.gui.android_runner.platform_tools.fetch_platform_tools_size")
def test_size_runner_emits_finished_size(mock_fetch, qapp):
    mock_fetch.return_value = 123456

    runner = AndroidPlatformToolsSizeRunner()
    results = []
    runner.finished_size.connect(lambda size: results.append(size))

    runner.run()

    assert results == [123456]


@patch("r36s_studio.gui.android_runner.platform_tools.fetch_platform_tools_size")
def test_size_runner_emits_none_when_unknown(mock_fetch, qapp):
    mock_fetch.return_value = None

    runner = AndroidPlatformToolsSizeRunner()
    results = []
    runner.finished_size.connect(lambda size: results.append(size))

    runner.run()

    assert results == [None]


@patch("r36s_studio.gui.android_runner.platform_tools.download_and_install")
def test_download_runner_emits_finished_download_on_success(mock_download, qapp, tmp_path):
    adb_path = tmp_path / "adb"
    mock_download.return_value = adb_path

    runner = AndroidPlatformToolsDownloadRunner()
    finished = []
    errors = []
    runner.finished_download.connect(lambda ok, path: finished.append((ok, path)))
    runner.error.connect(lambda code, msg: errors.append((code, msg)))

    runner.run()

    assert finished == [(True, str(adb_path))]
    assert errors == []


@patch("r36s_studio.gui.android_runner.platform_tools.download_and_install")
def test_download_runner_emits_error_and_failure_on_cancellation(mock_download, qapp):
    mock_download.side_effect = PlatformToolsDownloadCancelledError("annulé")

    runner = AndroidPlatformToolsDownloadRunner()
    finished = []
    errors = []
    runner.finished_download.connect(lambda ok, path: finished.append((ok, path)))
    runner.error.connect(lambda code, msg: errors.append((code, msg)))

    runner.run()

    assert finished == [(False, "")]
    assert errors == [("CANCELLED", "annulé")]


@patch("r36s_studio.gui.android_runner.platform_tools.download_and_install")
def test_download_runner_emits_error_and_failure_on_platform_tools_error(mock_download, qapp):
    mock_download.side_effect = PlatformToolsError("échec réseau")

    runner = AndroidPlatformToolsDownloadRunner()
    finished = []
    errors = []
    runner.finished_download.connect(lambda ok, path: finished.append((ok, path)))
    runner.error.connect(lambda code, msg: errors.append((code, msg)))

    runner.run()

    assert finished == [(False, "")]
    assert errors == [("PLATFORM_TOOLS_ERROR", "échec réseau")]


@patch("r36s_studio.gui.android_runner.platform_tools.download_and_install")
def test_download_runner_forwards_progress_events(mock_download, qapp):
    def fake_download(*, on_progress=None, should_cancel=None):
        on_progress(1, 10)
        on_progress(10, 10)
        return "adb"

    mock_download.side_effect = fake_download

    runner = AndroidPlatformToolsDownloadRunner()
    progress_events = []
    runner.progress.connect(lambda done, total: progress_events.append((done, total)))

    runner.run()

    assert progress_events == [(1, 10), (10, 10)]


@patch("r36s_studio.gui.android_runner.platform_tools.download_and_install")
def test_download_runner_cancel_sets_flag_consulted_by_should_cancel(mock_download, qapp):
    seen_cancel_states = []

    def fake_download(*, on_progress=None, should_cancel=None):
        seen_cancel_states.append(should_cancel())
        return "adb"

    mock_download.side_effect = fake_download

    runner = AndroidPlatformToolsDownloadRunner()
    runner.cancel()
    runner.run()

    assert seen_cancel_states == [True]
