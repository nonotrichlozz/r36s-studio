"""Tests de identify/rocknix.py -- sélection de l'image RK3326 (R36S) dans
une release GitHub ROCKNIX, vérification de somme de contrôle, et
téléchargement avec progression. Toute communication réseau est mockée via
le paramètre `opener` injectable -- jamais un accès réseau réel dans les
tests (même principe que `subprocess.run` mocké par `tests/conftest.py`)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from r36s_studio.identify import rocknix


class _FakeResponse:
    """Contexte minimal imitant `urllib.request.urlopen` : `read(n)` sert
    les octets par blocs si `n` est fourni, ou tout d'un coup sinon --
    assez pour exercer la boucle par blocs de `download_asset`."""

    def __init__(self, data: bytes):
        self._data = data
        self._offset = 0

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


def _asset(name: str, url: str = "https://example.invalid/x", size: int = 1024) -> dict:
    return {"name": name, "browser_download_url": url, "size": size}


# --- select_r36s_assets ---------------------------------------------------
# Noms réels vérifiés contre la release ROCKNIX du 2026-08-01 (CLAUDE.md) :
# deux variantes d'image (-a/-b, différence encore inconnue) plus un .tar
# (archive du système de fichiers, pas une image disque) et un .sha256 par
# image -- le filtre doit ignorer .tar et .sha256 même quand ils
# contiennent "rk3326", et ne jamais choisir automatiquement entre -a/-b.

_VARIANT_A = "ROCKNIX-RK3326.aarch64-20260801-a.img.gz"
_VARIANT_B = "ROCKNIX-RK3326.aarch64-20260801-b.img.gz"
_TAR_ASSET = "ROCKNIX-RK3326.aarch64-20260801.tar"


def _real_release_assets():
    return [
        _asset(_VARIANT_A, url="https://example.invalid/a.img.gz", size=111),
        _asset(f"{_VARIANT_A}.sha256", url="https://example.invalid/a.sha256"),
        _asset(_VARIANT_B, url="https://example.invalid/b.img.gz", size=222),
        _asset(f"{_VARIANT_B}.sha256", url="https://example.invalid/b.sha256"),
        _asset(_TAR_ASSET, url="https://example.invalid/all.tar"),
    ]


def test_select_r36s_assets_returns_both_image_variants():
    result = rocknix.select_r36s_assets(_real_release_assets())

    names = [asset.name for asset in result]
    assert names == [_VARIANT_A, _VARIANT_B]


def test_select_r36s_assets_excludes_tar_and_sha256_even_though_names_match():
    result = rocknix.select_r36s_assets(_real_release_assets())

    names = [asset.name for asset in result]
    assert _TAR_ASSET not in names
    assert f"{_VARIANT_A}.sha256" not in names
    assert f"{_VARIANT_B}.sha256" not in names


def test_select_r36s_assets_is_case_insensitive():
    assets = [_asset("rocknix-rk3326.aarch64-20260801-a.IMG.GZ")]

    result = rocknix.select_r36s_assets(assets)

    assert len(result) == 1
    assert result[0].name == "rocknix-rk3326.aarch64-20260801-a.IMG.GZ"


def test_select_r36s_assets_ignores_other_socs():
    assets = [_asset("ROCKNIX-RG351.img.gz"), _asset("ROCKNIX-S922X.img.gz")]

    with pytest.raises(rocknix.RocknixAssetNotFoundError):
        rocknix.select_r36s_assets(assets)


def test_select_r36s_assets_raises_when_only_tar_and_checksum_match():
    """.tar et .sha256 contiennent "rk3326" mais ne sont pas des images
    flashables -- une release qui n'en publierait aucune ne doit pas
    passer le .tar comme un faux positif."""
    assets = [_asset(_TAR_ASSET), _asset(f"{_VARIANT_A}.sha256")]

    with pytest.raises(rocknix.RocknixAssetNotFoundError):
        rocknix.select_r36s_assets(assets)


# --- find_checksum_asset -------------------------------------------------


def test_find_checksum_asset_prefers_dedicated_sidecar():
    image = _asset("ROCKNIX-RK3326.img.gz")
    sidecar = _asset("ROCKNIX-RK3326.img.gz.sha256")
    shared = _asset("sha256sum.txt")

    result = rocknix.find_checksum_asset([image, sidecar, shared], "ROCKNIX-RK3326.img.gz")

    assert result is sidecar


def test_find_checksum_asset_falls_back_to_shared_sums_file():
    image = _asset("ROCKNIX-RK3326.img.gz")
    shared = _asset("SHA256SUMS")

    result = rocknix.find_checksum_asset([image, shared], "ROCKNIX-RK3326.img.gz")

    assert result is shared


def test_find_checksum_asset_returns_none_when_absent():
    image = _asset("ROCKNIX-RK3326.img.gz")

    result = rocknix.find_checksum_asset([image], "ROCKNIX-RK3326.img.gz")

    assert result is None


# --- parse_checksum -------------------------------------------------------


def test_parse_checksum_from_sums_file_format():
    text = (
        "deadbeef" * 8 + "  ROCKNIX-RG351.img.gz\n"
        + "cafebabe" * 8 + "  ROCKNIX-RK3326.img.gz\n"
    )

    result = rocknix.parse_checksum(text, "ROCKNIX-RK3326.img.gz")

    assert result == ("cafebabe" * 8)


def test_parse_checksum_from_bare_single_hash_file():
    text = "abc123ef" * 8 + "\n"

    result = rocknix.parse_checksum(text, "ROCKNIX-RK3326.img.gz.sha256")

    assert result == ("abc123ef" * 8)


def test_parse_checksum_returns_none_for_unrecognized_content():
    result = rocknix.parse_checksum("pas un hash du tout", "ROCKNIX-RK3326.img.gz")

    assert result is None


def test_parse_checksum_returns_none_for_empty_content():
    assert rocknix.parse_checksum("", "ROCKNIX-RK3326.img.gz") is None


# --- fetch_latest_release_assets ------------------------------------------


def test_fetch_latest_release_assets_returns_assets_list():
    payload = json.dumps({"tag_name": "v1", "assets": [_asset("ROCKNIX-RK3326.img.gz")]}).encode("utf-8")
    opener = MagicMock(return_value=_FakeResponse(payload))

    assets = rocknix.fetch_latest_release_assets(opener=opener)

    assert len(assets) == 1
    assert assets[0]["name"] == "ROCKNIX-RK3326.img.gz"
    opener.assert_called_once_with(rocknix.ROCKNIX_RELEASES_API_URL)


def test_fetch_latest_release_assets_wraps_network_error():
    def failing_opener(url):
        raise OSError("no network")

    with pytest.raises(rocknix.RocknixReleaseError):
        rocknix.fetch_latest_release_assets(opener=failing_opener)


def test_fetch_latest_release_assets_wraps_invalid_json():
    opener = MagicMock(return_value=_FakeResponse(b"pas du json"))

    with pytest.raises(rocknix.RocknixReleaseError):
        rocknix.fetch_latest_release_assets(opener=opener)


def test_fetch_latest_release_assets_requires_assets_list_field():
    payload = json.dumps({"tag_name": "v1"}).encode("utf-8")
    opener = MagicMock(return_value=_FakeResponse(payload))

    with pytest.raises(rocknix.RocknixReleaseError):
        rocknix.fetch_latest_release_assets(opener=opener)


# --- resolve_latest_r36s_assets -------------------------------------------


def test_resolve_latest_r36s_assets_pairs_each_variant_with_its_own_checksum():
    """Confirmé sur une vraie release ROCKNIX : chaque image a son propre
    `.sha256` du même nom, pas un fichier de sommes partagé -- -a et -b
    doivent chacune récupérer la leur, pas celle de l'autre."""
    checksum_a = ("cafebabe" * 8 + f"  {_VARIANT_A}\n").encode("utf-8")
    checksum_b = ("deadbeef" * 8 + f"  {_VARIANT_B}\n").encode("utf-8")
    release_payload = json.dumps({"assets": _real_release_assets()}).encode("utf-8")

    responses = {
        rocknix.ROCKNIX_RELEASES_API_URL: _FakeResponse(release_payload),
        "https://example.invalid/a.sha256": _FakeResponse(checksum_a),
        "https://example.invalid/b.sha256": _FakeResponse(checksum_b),
    }
    opener = MagicMock(side_effect=lambda url: responses[url])

    results = rocknix.resolve_latest_r36s_assets(opener=opener)

    assert [(asset.name, checksum) for asset, checksum in results] == [
        (_VARIANT_A, "cafebabe" * 8),
        (_VARIANT_B, "deadbeef" * 8),
    ]


def test_resolve_latest_r36s_assets_returns_none_checksum_when_absent():
    image = _asset("ROCKNIX-RK3326.aarch64-20260801-a.img.gz")
    release_payload = json.dumps({"assets": [image]}).encode("utf-8")
    opener = MagicMock(return_value=_FakeResponse(release_payload))

    results = rocknix.resolve_latest_r36s_assets(opener=opener)

    assert len(results) == 1
    asset, expected_sha256 = results[0]
    assert asset.name == "ROCKNIX-RK3326.aarch64-20260801-a.img.gz"
    assert expected_sha256 is None


# --- download_asset --------------------------------------------------------


def test_download_asset_writes_file_and_reports_progress(tmp_path):
    content = b"x" * (rocknix.BLOCK_SIZE + 10)
    asset = rocknix.RocknixAsset(name="image.img.gz", download_url="https://example.invalid/image", size_bytes=len(content))
    opener = MagicMock(return_value=_FakeResponse(content))
    destination = tmp_path / "downloads" / "image.img.gz"
    events = []

    rocknix.download_asset(asset, destination, on_progress=lambda done, total: events.append((done, total)), opener=opener)

    assert destination.read_bytes() == content
    assert events[-1] == (len(content), len(content))
    assert events[0][1] == len(content)  # total connu dès le premier événement (taille de l'asset)


def test_download_asset_verifies_checksum_and_succeeds_when_it_matches(tmp_path):
    import hashlib

    content = b"contenu de test"
    expected = hashlib.sha256(content).hexdigest()
    asset = rocknix.RocknixAsset(name="image.img.gz", download_url="https://example.invalid/image", size_bytes=len(content))
    opener = MagicMock(return_value=_FakeResponse(content))
    destination = tmp_path / "image.img.gz"

    rocknix.download_asset(asset, destination, expected_sha256=expected, opener=opener)

    assert destination.exists()


def test_download_asset_raises_and_removes_file_on_checksum_mismatch(tmp_path):
    content = b"contenu de test"
    asset = rocknix.RocknixAsset(name="image.img.gz", download_url="https://example.invalid/image", size_bytes=len(content))
    opener = MagicMock(return_value=_FakeResponse(content))
    destination = tmp_path / "image.img.gz"

    with pytest.raises(rocknix.ChecksumMismatchError):
        rocknix.download_asset(asset, destination, expected_sha256="0" * 64, opener=opener)

    assert not destination.exists()


def test_download_asset_raises_and_removes_file_when_cancelled(tmp_path):
    content = b"x" * (rocknix.BLOCK_SIZE + 10)
    asset = rocknix.RocknixAsset(name="image.img.gz", download_url="https://example.invalid/image", size_bytes=len(content))
    opener = MagicMock(return_value=_FakeResponse(content))
    destination = tmp_path / "image.img.gz"
    calls = {"n": 0}

    def should_cancel():
        calls["n"] += 1
        return calls["n"] > 1  # laisse passer un bloc, annule avant le suivant

    with pytest.raises(rocknix.DownloadCancelledError):
        rocknix.download_asset(asset, destination, opener=opener, should_cancel=should_cancel)

    assert not destination.exists()


def test_download_asset_wraps_network_error_and_removes_partial_file(tmp_path):
    asset = rocknix.RocknixAsset(name="image.img.gz", download_url="https://example.invalid/image", size_bytes=100)
    destination = tmp_path / "image.img.gz"

    class _FailingResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def read(self, size=None):
            raise OSError("connexion interrompue")

    opener = MagicMock(return_value=_FailingResponse())

    with pytest.raises(rocknix.RocknixReleaseError):
        rocknix.download_asset(asset, destination, opener=opener)

    assert not destination.exists()


# --- default_firmware_downloads_dir ---------------------------------------


def test_default_firmware_downloads_dir_is_under_documents(monkeypatch, tmp_path):
    monkeypatch.setattr(rocknix.Path, "home", classmethod(lambda cls: tmp_path))

    result = rocknix.default_firmware_downloads_dir()

    assert result == tmp_path / "Documents" / "R36S Studio" / "Firmwares"
