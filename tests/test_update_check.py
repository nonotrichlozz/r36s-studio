import io
import json

from r36s_studio import update_check


def test_is_newer_compares_numerically():
    assert update_check.is_newer("v0.10.0", "0.9.1")
    assert not update_check.is_newer("v0.1.0", "0.1.0")
    assert not update_check.is_newer("v0.0.9", "0.1.0")
    assert not update_check.is_newer("nightly", "0.1.0")


def test_fetch_latest_reads_tag_and_notes():
    body = json.dumps({"tag_name": "v1.2.0", "body": "Notes"}).encode()
    assert update_check.fetch_latest(opener=lambda req, timeout: io.BytesIO(body)) == ("v1.2.0", "Notes")


def test_fetch_latest_is_silent_on_network_error():
    def offline(req, timeout):
        raise OSError("hors ligne")

    assert update_check.fetch_latest(opener=offline) is None


# --- mise à jour automatique (installeur Windows vérifié) -------------------

import hashlib

import pytest

_INSTALLER = b"MZ" + b"installeur-de-test" * 100
_SHA = hashlib.sha256(_INSTALLER).hexdigest()
_URL = "https://github.com/nonotrichlozz/r36s-studio/releases/download/v9.0.0/R36S-Studio-Setup.exe"


def _release_json(**asset_overrides):
    asset = {
        "name": "R36S-Studio-Setup.exe",
        "browser_download_url": _URL,
        "size": len(_INSTALLER),
        "digest": f"sha256:{_SHA}",
    }
    asset.update(asset_overrides)
    return json.dumps({"tag_name": "v9.0.0", "body": "Notes", "assets": [asset]}).encode()


def test_fetch_latest_release_reads_the_verifiable_installer():
    release = update_check.fetch_latest_release(opener=lambda req, timeout: io.BytesIO(_release_json()))
    assert release.tag == "v9.0.0" and release.notes == "Notes"
    assert release.installer_url == _URL
    assert release.installer_size == len(_INSTALLER)
    assert release.installer_sha256 == _SHA
    assert release.can_auto_install


@pytest.mark.parametrize(
    "overrides",
    [
        {"digest": None},  # pas de SHA-256 publiée : jamais d'installation automatique
        {"digest": "md5:abc"},
        {"browser_download_url": "https://exemple.invalid/R36S-Studio-Setup.exe"},
        {"browser_download_url": "https://github.com/autre/depot/releases/download/v9/R36S-Studio-Setup.exe"},
        {"size": 0},
        {"size": 10 * 1024 * 1024 * 1024},
        {"name": "autre.exe"},
    ],
)
def test_fetch_latest_release_refuses_an_untrustworthy_installer(overrides):
    release = update_check.fetch_latest_release(opener=lambda req, timeout: io.BytesIO(_release_json(**overrides)))
    assert release.tag == "v9.0.0"
    assert not release.can_auto_install


def test_fetch_latest_release_is_silent_on_network_error():
    def offline(req, timeout):
        raise OSError("hors ligne")

    assert update_check.fetch_latest_release(opener=offline) is None


def _release():
    return update_check.LatestRelease("v9.0.0", "Notes", _URL, len(_INSTALLER), _SHA)


def test_download_installer_verifies_and_keeps_a_good_file(tmp_path):
    path = update_check.download_installer(
        _release(), tmp_path, opener=lambda req, timeout: io.BytesIO(_INSTALLER), block_size=64
    )
    assert path.read_bytes() == _INSTALLER
    assert path.name == "R36S-Studio-Setup-v9.0.0.exe"
    assert not list(tmp_path.glob("*.part"))


def test_download_installer_reuses_an_already_verified_file(tmp_path):
    update_check.download_installer(_release(), tmp_path, opener=lambda req, timeout: io.BytesIO(_INSTALLER))

    def must_not_download(req, timeout):
        raise AssertionError("fichier déjà vérifié : pas de nouveau téléchargement")

    assert update_check.download_installer(_release(), tmp_path, opener=must_not_download).is_file()


@pytest.mark.parametrize(
    "content",
    [_INSTALLER[:-1], _INSTALLER[:-1] + b"X", _INSTALLER + b"en trop"],
    ids=["incomplet", "modifie", "trop-long"],
)
def test_download_installer_never_keeps_a_bad_file(tmp_path, content):
    with pytest.raises(update_check.InstallerDownloadError):
        update_check.download_installer(_release(), tmp_path, opener=lambda req, timeout: io.BytesIO(content))
    assert list(tmp_path.iterdir()) == []


def test_download_installer_refuses_a_release_without_checksum(tmp_path):
    with pytest.raises(update_check.InstallerDownloadError):
        update_check.download_installer(update_check.LatestRelease("v9.0.0", "Notes", _URL, 10, ""), tmp_path)


def test_launch_installer_runs_it_silently(tmp_path):
    calls = []
    update_check.launch_installer(tmp_path / "setup.exe", popen=lambda args, **kwargs: calls.append(args))
    assert calls == [[str(tmp_path / "setup.exe"), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/RELANCER=1"]]


def test_auto_install_only_for_the_packaged_windows_app(monkeypatch):
    monkeypatch.setattr(update_check.sys, "platform", "linux")
    monkeypatch.setattr(update_check.sys, "frozen", True, raising=False)
    assert not update_check.auto_install_supported()
    monkeypatch.setattr(update_check.sys, "platform", "win32")
    assert update_check.auto_install_supported()
    monkeypatch.delattr(update_check.sys, "frozen")
    assert not update_check.auto_install_supported()
