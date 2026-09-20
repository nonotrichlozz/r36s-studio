"""Tests de `android/platform_tools.py` -- téléchargement des
« platform-tools » officiels de Google (adb), sur accord explicite
uniquement. Toute communication réseau passe par un paramètre `opener`
injectable (même principe que `consoles_diverses/client.py`/`identify/
rocknix.py`) -- aucun accès réseau réel dans cette suite."""

from __future__ import annotations

import io
import platform
import zipfile
from unittest.mock import MagicMock

import pytest

from r36s_studio.android import platform_tools


class _Headers:
    def __init__(self, content_length):
        self._content_length = content_length

    def get(self, key, default=None):
        if key == "Content-Length" and self._content_length is not None:
            return str(self._content_length)
        return default


class _FakeResponse:
    """Contexte minimal imitant `urllib.request.urlopen` -- même forme que
    `tests/test_identify_rocknix.py::_FakeResponse`, avec un attribut
    `headers` pour `Content-Length`."""

    def __init__(self, data: bytes, content_length=None):
        self._data = data
        self._offset = 0
        # Par défaut, `Content-Length` reflète la taille réelle des données
        # -- le test dédié à l'en-tête absent réassigne `self.headers`
        # après construction plutôt que de distinguer "omis" de "None" ici.
        self.headers = _Headers(content_length if content_length is not None else len(data))

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def read(self, size=None):
        if size is None:
            chunk = self._data[self._offset :]
            self._offset = len(self._data)
            return chunk
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def _build_platform_tools_zip(adb_name: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"platform-tools/{adb_name}", "faux binaire adb")
        archive.writestr("platform-tools/NOTICE.txt", "texte")
    return buffer.getvalue()


# --- platform_tools_url --------------------------------------------------


def test_platform_tools_url_windows():
    assert "windows" in platform_tools.platform_tools_url("Windows")


def test_platform_tools_url_darwin():
    assert "darwin" in platform_tools.platform_tools_url("Darwin")


def test_platform_tools_url_linux():
    assert "linux" in platform_tools.platform_tools_url("Linux")


def test_platform_tools_url_raises_for_unknown_system():
    with pytest.raises(platform_tools.UnsupportedPlatformError):
        platform_tools.platform_tools_url("PlanNine")


# --- fetch_platform_tools_size --------------------------------------------


def test_fetch_platform_tools_size_reads_content_length_header():
    opener = MagicMock(return_value=_FakeResponse(b"", content_length=123456))

    size = platform_tools.fetch_platform_tools_size(opener=opener, system="Windows")

    assert size == 123456
    request = opener.call_args.args[0]
    assert request.get_method() == "HEAD"


def test_fetch_platform_tools_size_returns_none_when_header_missing():
    opener = MagicMock(return_value=_FakeResponse(b"", content_length=None))
    opener.return_value.headers = _Headers(None)

    assert platform_tools.fetch_platform_tools_size(opener=opener, system="Windows") is None


def test_fetch_platform_tools_size_returns_none_on_network_error():
    def opener(request):
        raise OSError("injoignable")

    assert platform_tools.fetch_platform_tools_size(opener=opener, system="Windows") is None


# --- download_and_install -------------------------------------------------


def test_download_and_install_extracts_adb_and_reports_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_tools, "config_dir", lambda: tmp_path)
    adb_name = "adb.exe" if platform.system() == "Windows" else "adb"
    content = _build_platform_tools_zip(adb_name)
    opener = MagicMock(return_value=_FakeResponse(content))
    events = []

    adb_path = platform_tools.download_and_install(
        on_progress=lambda done, total: events.append((done, total)), opener=opener
    )

    assert adb_path.exists()
    assert adb_path.name == adb_name
    assert events[-1] == (len(content), len(content))
    # Le zip temporaire ne doit jamais rester après une extraction réussie.
    assert not (tmp_path / "platform-tools-download.zip").exists()


def test_download_and_install_raises_and_cleans_up_when_cancelled(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_tools, "config_dir", lambda: tmp_path)
    content = _build_platform_tools_zip("adb")
    opener = MagicMock(return_value=_FakeResponse(content))
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 1

    with pytest.raises(platform_tools.PlatformToolsDownloadCancelledError):
        platform_tools.download_and_install(opener=opener, should_cancel=should_cancel)

    assert not (tmp_path / "platform-tools-download.zip").exists()


def test_download_and_install_raises_platform_tools_error_on_network_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_tools, "config_dir", lambda: tmp_path)

    def opener(request):
        raise OSError("coupure réseau")

    with pytest.raises(platform_tools.PlatformToolsError):
        platform_tools.download_and_install(opener=opener)


def test_download_and_install_raises_platform_tools_error_on_bad_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_tools, "config_dir", lambda: tmp_path)
    opener = MagicMock(return_value=_FakeResponse(b"ceci n'est pas un zip"))

    with pytest.raises(platform_tools.PlatformToolsError):
        platform_tools.download_and_install(opener=opener)


# --- installed_adb_path ---------------------------------------------------


def test_installed_adb_path_returns_none_when_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_tools, "config_dir", lambda: tmp_path)

    assert platform_tools.installed_adb_path() is None


def test_installed_adb_path_returns_path_when_present(tmp_path, monkeypatch):
    monkeypatch.setattr(platform_tools, "config_dir", lambda: tmp_path)
    install_dir = tmp_path / "platform-tools"
    install_dir.mkdir()
    adb_name = "adb.exe" if platform.system() == "Windows" else "adb"
    (install_dir / adb_name).write_text("faux binaire")

    found = platform_tools.installed_adb_path()

    assert found is not None
    assert found.name == adb_name
