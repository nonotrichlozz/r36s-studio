"""Tests de identify/rocknix_r36s.py -- fichiers d'écran téléchargés à la
demande (empreintes fixées dans le code) et préparation de la partition
ROCKNIX pour une R36S. Réseau toujours simulé (`opener`), partition simulée
par un dossier de `tmp_path`."""

from __future__ import annotations

import hashlib
import io

import pytest

from r36s_studio.identify import rocknix_r36s as r36s


def _panels(*names):
    """Liste de panneaux factices : (nom, empreinte de b"dtbo-<nom>")."""
    return tuple((name, hashlib.sha256(f"dtbo-{name}".encode()).hexdigest()) for name in names)


def _opener(served):
    calls = []

    def opener(url):
        calls.append(url)
        name = url.rsplit("mipi-panel.dtbo.", 1)[1]
        if name not in served:
            raise OSError("hors ligne")
        return io.BytesIO(served[name])

    opener.calls = calls
    return opener


def _rocknix_partition(tmp_path):
    """Partition ROCKNIX telle qu'écrite par l'image RK3326 20261001."""
    root = tmp_path / "carte"
    (root / "extlinux").mkdir(parents=True)
    (root / "extlinux" / "extlinux.conf").write_text("# FDT /your-custom-devicetree.dtb\n")
    (root / "extlinux" / "extlinux.conf.r36s").write_text("FDT /rk3326-gameconsole-r36s.dtb\n")
    (root / "overlays").mkdir()
    return root


def test_pinned_panels_are_in_trial_order_with_full_sha256():
    assert [name for name, _ in r36s.PANELS] == ["r36s_clone", "r36s-panel4", "r36s-panel3", "r36s-panel2", "r36s-panel1"]
    assert all(len(sha) == 64 and int(sha, 16) >= 0 for _, sha in r36s.PANELS)


def test_download_keeps_only_files_matching_the_pinned_sha256(tmp_path):
    panels = _panels("a", "b", "c")
    opener = _opener({"a": b"dtbo-a", "b": b"modifie", "c": b"dtbo-c"})

    failed = r36s.download_missing_panels(tmp_path, panels=panels, opener=opener)

    assert failed == ["b"]
    assert r36s.available_panels(tmp_path, panels=panels) == ["a", "c"]
    assert not (tmp_path / "mipi-panel.dtbo.b").exists()


def test_download_skips_panels_already_cached(tmp_path):
    panels = _panels("a")
    (tmp_path / "mipi-panel.dtbo.a").write_bytes(b"dtbo-a")
    opener = _opener({})

    assert r36s.download_missing_panels(tmp_path, panels=panels, opener=opener) == []
    assert opener.calls == []


def test_download_offline_reports_every_missing_panel(tmp_path):
    panels = _panels("a", "b")
    assert r36s.download_missing_panels(tmp_path, panels=panels, opener=_opener({})) == ["a", "b"]


def test_corrupted_cache_file_is_not_available(tmp_path):
    panels = _panels("a")
    (tmp_path / "mipi-panel.dtbo.a").write_bytes(b"abime")
    assert r36s.available_panels(tmp_path, panels=panels) == []


def test_prepare_switches_extlinux_and_installs_preferred_panel(tmp_path):
    panels = _panels("a", "b")
    cache = tmp_path / "cache"
    cache.mkdir()
    for name in ("a", "b"):
        (cache / f"mipi-panel.dtbo.{name}").write_bytes(f"dtbo-{name}".encode())
    root = _rocknix_partition(tmp_path)

    installed = r36s.prepare_r36s_card(root, cache, preferred="b", panels=panels)

    assert installed == "b"
    assert (root / "extlinux" / "extlinux.conf").read_text() == "FDT /rk3326-gameconsole-r36s.dtb\n"
    assert (root / "extlinux" / "extlinux.conf.orig").read_text() == "# FDT /your-custom-devicetree.dtb\n"
    assert (root / "overlays" / "mipi-panel.dtbo").read_bytes() == b"dtbo-b"
    assert sorted(p.name for p in (root / "overlays" / "panels").iterdir()) == ["mipi-panel.dtbo.a", "mipi-panel.dtbo.b"]


def test_prepare_never_overwrites_an_existing_orig(tmp_path):
    root = _rocknix_partition(tmp_path)
    (root / "extlinux" / "extlinux.conf.orig").write_text("vrai original\n")

    r36s.prepare_r36s_card(root, tmp_path / "vide", panels=_panels("a"))
    r36s.prepare_r36s_card(root, tmp_path / "vide", panels=_panels("a"))

    assert (root / "extlinux" / "extlinux.conf.orig").read_text() == "vrai original\n"


def test_prepare_falls_back_to_first_available_panel_in_trial_order(tmp_path):
    panels = _panels("a", "b", "c")
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "mipi-panel.dtbo.c").write_bytes(b"dtbo-c")
    (cache / "mipi-panel.dtbo.b").write_bytes(b"dtbo-b")

    assert r36s.prepare_r36s_card(_rocknix_partition(tmp_path), cache, preferred="a", panels=panels) == "b"


def test_prepare_without_any_panel_still_fixes_extlinux(tmp_path):
    root = _rocknix_partition(tmp_path)

    assert r36s.prepare_r36s_card(root, tmp_path / "absent", panels=_panels("a")) is None
    assert "r36s" in (root / "extlinux" / "extlinux.conf").read_text()
    assert not (root / "overlays" / "mipi-panel.dtbo").exists()


def test_prepare_refuses_a_partition_without_the_r36s_config(tmp_path):
    root = _rocknix_partition(tmp_path)
    (root / "extlinux" / "extlinux.conf.r36s").unlink()

    with pytest.raises(r36s.R36sConfigMissing):
        r36s.prepare_r36s_card(root, tmp_path, panels=_panels("a"))
    assert not (root / "extlinux" / "extlinux.conf.orig").exists()
