"""Jeux de fichiers de rechange du BOOT (`partitions/boot_sets.py`), leur
historique (`config.py`) et la commande `boot-sets` -- sur un dossier
temporaire, jamais une vraie carte."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from r36s_studio import __main__ as cli
from r36s_studio import config
from r36s_studio.devices import Device
from r36s_studio.partitions import boot_sets
from r36s_studio.partitions.locate import PartitionInfo


def _boot(tmp_path):
    """BOOT façon portage Android / K36 : dtb d'origine à la racine, deux
    écrans dans Panels/, dont un qui ajoute un fichier absent à l'origine."""
    root = tmp_path / "BOOT"
    (root / "Panels" / "Panel 1").mkdir(parents=True)
    (root / "Panels" / "Panel 2").mkdir(parents=True)
    (root / "board.dtb").write_bytes(b"origine")
    (root / "Panels" / "Panel 1" / "board.dtb").write_bytes(b"ecran1")
    (root / "Panels" / "Panel 2" / "board.dtb").write_bytes(b"ecran2")
    (root / "Panels" / "Panel 2" / "extra.dtbo").write_bytes(b"extra2")
    return root


def test_lists_panels_subfolders_and_rocknix_overlays(tmp_path):
    root = _boot(tmp_path)
    (root / "overlays" / "panels").mkdir(parents=True)
    (root / "overlays" / "panels" / "mipi-panel.dtbo.r36s_clone").write_bytes(b"p")
    (root / "overlays" / "panels" / "README.TXT").write_bytes(b"x")
    (root / "Panels" / "vide").mkdir()

    sets = boot_sets.list_sets(root)

    assert [(s.set_id, s.name) for s in sets] == [
        ("Panels/Panel 1", "Panel 1"),
        ("Panels/Panel 2", "Panel 2"),
        ("overlays/panels/mipi-panel.dtbo.r36s_clone", "r36s_clone"),
    ]
    assert sets[1].files == (
        ("Panels/Panel 2/board.dtb", "board.dtb"),
        ("Panels/Panel 2/extra.dtbo", "extra.dtbo"),
    )
    assert sets[2].files == (("overlays/panels/mipi-panel.dtbo.r36s_clone", "overlays/mipi-panel.dtbo"),)


def test_any_panels_tree_without_assumed_names(tmp_path):
    """Arborescence relevée sur R36Droid (Panel0..Panel8 + « Clone type 3
    panel 1 », deux .dtb chacun), plus un niveau de regroupement inventé."""
    root = tmp_path / "BOOT"
    names = [f"Panel{i}" for i in range(9)] + ["Clone type 3 panel 1"]
    for name in names:
        folder = root / "panels" / name
        folder.mkdir(parents=True)
        (folder / "rk3326-a.dtb").write_bytes(name.encode())
        (folder / "rk3326-b.dtb").write_bytes(name.encode())
    (root / "panels" / "Autres" / "Ecran X").mkdir(parents=True)
    (root / "panels" / "Autres" / "Ecran X" / "x.dtb").write_bytes(b"x")
    (root / "panels" / "LISEZMOI.txt").write_bytes(b"pas un jeu")

    sets = boot_sets.list_sets(root)

    assert [s.name for s in sets] == ["Autres / Ecran X", "Clone type 3 panel 1", *names[:9]]
    clone = sets[1]
    assert clone.set_id == "panels/Clone type 3 panel 1"
    assert clone.files == (
        ("panels/Clone type 3 panel 1/rk3326-a.dtb", "rk3326-a.dtb"),
        ("panels/Clone type 3 panel 1/rk3326-b.dtb", "rk3326-b.dtb"),
    )
    boot_sets.apply_set(root, "panels/Autres/Ecran X")
    assert (root / "x.dtb").read_bytes() == b"x"


def test_screen_folder_found_by_dtb_whatever_its_name(tmp_path):
    """Clone ArkOS relevé : `ScreenFiles/` à côté de `BMPs/` et `extlinux/`.
    Les .dtb de ROCKNIX (`device_trees/`) et la copie d'origine
    (`r36s-studio/`) ne sont jamais des écrans."""
    root = tmp_path / "BOOT"
    for folder in ("ScreenFiles/Panel 1", "BMPs", "extlinux", "device_trees", "r36s-studio/origine"):
        (root / folder).mkdir(parents=True)
    (root / "rk3326-r35s-linux.dtb").write_bytes(b"origine")
    (root / "ScreenFiles" / "Panel 1" / "rk3326-r35s-linux.dtb").write_bytes(b"ecran1")
    (root / "BMPs" / "logo.bmp").write_bytes(b"x")
    (root / "extlinux" / "extlinux.conf").write_bytes(b"x")
    (root / "device_trees" / "rk3326-a.dtb").write_bytes(b"x")
    (root / "r36s-studio" / "origine" / "rk3326-r35s-linux.dtb").write_bytes(b"x")

    assert [(s.set_id, s.name) for s in boot_sets.list_sets(root)] == [("ScreenFiles/Panel 1", "Panel 1")]


def test_apply_then_restore_returns_to_original(tmp_path):
    root = _boot(tmp_path)
    assert boot_sets.read_state(root) == boot_sets.BootSetState(None, None, False)

    first = boot_sets.apply_set(root, "Panels/Panel 2")
    assert (root / "board.dtb").read_bytes() == b"ecran2"
    assert (root / "extra.dtbo").read_bytes() == b"extra2"
    assert first.applied == "Panels/Panel 2" and first.can_restore and first.card_id

    # Deuxième essai : la copie d'origine n'est jamais écrasée par l'écran 2.
    second = boot_sets.apply_set(root, "Panels/Panel 1")
    assert second.card_id == first.card_id
    assert (root / "board.dtb").read_bytes() == b"ecran1"

    restored = boot_sets.restore_original(root)
    assert (root / "board.dtb").read_bytes() == b"origine"
    assert not (root / "extra.dtbo").exists()  # absent à l'origine : retiré
    assert restored == boot_sets.BootSetState(first.card_id, None, False)
    assert not list(root.rglob("*.r36s-tmp"))


def test_darkosre_set_removes_stale_root_dtb_like_select_device_ps1(tmp_path):
    """Relevé sur dArkOSRE_R36_trixie_03082026.img : les jeux clone ont
    `rg351v-uboot.dtb`, les R36S `rg351mp-uboot.dtb` ; l'ancien ne doit pas
    rester à la racine. Ailleurs (Panels/), rien n'est retiré."""
    root = tmp_path / "BOOT"
    folder = root / "dtb" / "r36s" / "R36S-V22 2024-12-18"
    folder.mkdir(parents=True)
    (root / "dtb" / "r36_devices.ini").write_text("[R36S-V22 2024-12-18]\nvariant = r36s\n")
    (root / "rg351v-uboot.dtb").write_bytes(b"clone-uboot")
    (root / "RK3326-R36S-LINUX.DTB").write_bytes(b"clone-linux")
    (folder / "rg351mp-uboot.dtb").write_bytes(b"r36s-uboot")
    (folder / "rk3326-r36s-linux.dtb").write_bytes(b"r36s-linux")

    set_id = "dtb/r36s/R36S-V22 2024-12-18"
    assert [s.name for s in boot_sets.list_sets(root)] == ["r36s / R36S-V22 2024-12-18"]
    boot_sets.apply_set(root, set_id)
    names = {p.name.lower() for p in root.iterdir() if p.is_file()}
    assert names == {"rg351mp-uboot.dtb", "rk3326-r36s-linux.dtb"}  # casse différente : copié, pas supprimé

    boot_sets.restore_original(root)
    assert (root / "rg351v-uboot.dtb").read_bytes() == b"clone-uboot"
    assert not (root / "rg351mp-uboot.dtb").exists()

    other = _boot(tmp_path / "autre")
    (other / "garde.dtb").write_bytes(b"x")
    boot_sets.apply_set(other, "Panels/Panel 1")
    assert (other / "garde.dtb").exists()


def test_manifest_written_before_any_boot_file_changes(tmp_path):
    """Retrait de la carte en pleine copie : l'origine reste restaurable."""
    root = _boot(tmp_path)
    real_copy = boot_sets._copy_atomic

    def copy_then_fail(source, dest):
        if dest == root / "extra.dtbo":
            raise OSError("carte retirée")
        real_copy(source, dest)

    with patch.object(boot_sets, "_copy_atomic", side_effect=copy_then_fail):
        with pytest.raises(OSError):
            boot_sets.apply_set(root, "Panels/Panel 2")
    assert (root / "board.dtb").read_bytes() == b"ecran2"

    boot_sets.restore_original(root)
    assert (root / "board.dtb").read_bytes() == b"origine"


def test_restore_refuses_when_originals_incomplete(tmp_path):
    root = _boot(tmp_path)
    boot_sets.apply_set(root, "Panels/Panel 1")
    (root / "r36s-studio" / "origine" / "board.dtb").unlink()

    with pytest.raises(boot_sets.OriginalsMissing):
        boot_sets.restore_original(root)
    assert (root / "board.dtb").read_bytes() == b"ecran1"  # rien touché


def test_unknown_set_and_escaping_destination_refused(tmp_path):
    root = _boot(tmp_path)
    with pytest.raises(boot_sets.UnknownBootSet):
        boot_sets.apply_set(root, "Panels/Panel 9")
    with pytest.raises(boot_sets.OriginalsMissing):
        boot_sets.restore_original(root)
    for bad in ("../x", "/abs", "r36s-studio/carte.json", "R36S-Studio/x"):
        with pytest.raises(ValueError):
            boot_sets._inside(root, bad)


def test_trial_history_round_trip_and_invalid_entries_dropped():
    cfg = config.AppConfig()
    config.record_boot_set_trial(cfg, "abc", "Panels/Panel 1", "Panel 1", "2026-10-11")
    config.record_boot_set_trial(cfg, "abc", "Panels/Panel 2", "Panel 2", "2026-10-11")
    config.set_boot_set_outcome(cfg, "abc", "Panels/Panel 1", "failed")
    config.record_boot_set_trial(cfg, "abc", "Panels/Panel 1", "Panel 1", "2026-10-12")  # réessayé
    config.save_config(cfg)

    loaded = config.load_config()
    assert loaded.boot_set_trials == {
        "abc": [
            {"set_id": "Panels/Panel 2", "name": "Panel 2", "date": "2026-10-11", "outcome": "tried"},
            {"set_id": "Panels/Panel 1", "name": "Panel 1", "date": "2026-10-12", "outcome": "tried"},
        ]
    }
    with pytest.raises(ValueError):
        config.set_boot_set_outcome(cfg, "abc", "Panels/Panel 1", "works")

    raw = {"boot_set_trials": {"abc": [{"set_id": "x", "name": "x", "date": "d", "outcome": "magic"}, 3], "k": "x"}}
    config.config_path().write_text(json.dumps(raw), encoding="utf-8")
    assert config.load_config().boot_set_trials == {}


def _device() -> Device:
    return Device(
        path="/dev/fake-disk-test-7",
        display="Carte SD factice",
        size_bytes=32_000_000_000,
        removable=True,
        bus="USB",
        is_system=False,
        mountpoints=[],
    )


def _run_cli(argv, root):
    boot = PartitionInfo(device_path="/dev/fake-disk-test-7s1", label="", filesystem="vfat", mountpoint=str(root))
    with patch("r36s_studio.__main__.list_devices", return_value=[_device()]), patch(
        "r36s_studio.__main__.locate_mounted", return_value=boot
    ), patch("r36s_studio.__main__.unmount_forced") as unmount:
        args = cli.build_parser().parse_args(["boot-sets", "--device", "/dev/fake-disk-test-7", *argv])
        code = args.func(args)
    unmount.assert_called_once_with(boot)
    return code


def _result(out: str) -> dict:
    events = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    return next(e["result"] for e in events if e["type"] == "boot_sets_result")


def test_cli_apply_restore_and_errors(tmp_path, capsys):
    root = _boot(tmp_path)

    assert _run_cli(["--apply", "Panels/Panel 1"], root) == 0
    result = _result(capsys.readouterr().out)
    assert result["applied"] == "Panels/Panel 1" and result["can_restore"]
    assert {"set_id": "Panels/Panel 2", "name": "Panel 2"} in result["sets"]

    assert _run_cli(["--restore"], root) == 0
    assert _result(capsys.readouterr().out)["applied"] is None
    assert (root / "board.dtb").read_bytes() == b"origine"

    assert _run_cli(["--apply", "nope"], root) == 1
    assert '"code": "SOURCE_NOT_FOUND"' in capsys.readouterr().out
