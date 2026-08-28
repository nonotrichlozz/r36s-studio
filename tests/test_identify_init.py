"""Tests de identify/__init__.py -- identify_from_boot_directory, utilisée
par l'étape 2 du mode assisté (§5 mode assisté) pour identifier la console
à partir des `.dtb` déjà présents sur la partition BOOT montée (avant toute
copie -- distinct de l'extraction elle-même, étape 3).

Distingue trois échecs (message d'étape 2 différent pour chacun, §5 mode
assisté) : aucun `.dtb` trouvé (`NO_DTB_FOUND`) vs des `.dtb` présents mais
tous invalides ou sans les propriétés attendues (`ALL_DTB_INVALID`) -- le
troisième cas, le montage lui-même qui échoue (carte défaillante), est
décidé un niveau au-dessus (`WizardIdentifyRunner`, avant même d'appeler
cette fonction). Journalise dans tous les cas le dossier examiné et la
liste des fichiers `.dtb` trouvés (`scanned_directory`/`examined_files`)."""

from __future__ import annotations

from r36s_studio.identify import IdentifyFailureReason, IdentifyResult, identify_from_boot_directory
from r36s_studio.identify.dtb import DtbInfo


def test_returns_no_dtb_found_when_directory_has_no_dtb_file(tmp_path):
    (tmp_path / "boot.ini").write_text("console=r36s", encoding="utf-8")

    result = identify_from_boot_directory(tmp_path)

    assert result.info is None
    assert result.failure_reason == IdentifyFailureReason.NO_DTB_FOUND
    assert result.scanned_directory == str(tmp_path)
    assert result.examined_files == []


def test_returns_no_dtb_found_when_directory_does_not_exist(tmp_path):
    result = identify_from_boot_directory(tmp_path / "does-not-exist")

    assert result.info is None
    assert result.failure_reason == IdentifyFailureReason.NO_DTB_FOUND


def test_parses_the_first_valid_dtb_found(tmp_path):
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "broken.dtb").write_bytes(b"not a real dtb")
    (tmp_path / "board.dtb").write_bytes(_build_fake_dtb())

    result = identify_from_boot_directory(tmp_path)

    assert result.failure_reason is None
    assert result.info == DtbInfo(
        board_compatible="rk3326-evb-lp3-v12",
        panel_compatible="sitronix,st7703",
        timings={
            "hactive": 640,
            "vactive": 480,
            "clock-frequency": 25175000,
            "hfront-porch": 16,
            "hback-porch": 48,
            "hsync-len": 96,
            "vfront-porch": 10,
            "vback-porch": 33,
            "vsync-len": 2,
            "dsi,lanes": 4,
        },
    )
    assert result.scanned_directory == str(tmp_path)
    assert sorted(result.examined_files) == sorted(
        [str(tmp_path / "broken.dtb"), str(tmp_path / "board.dtb")]
    )


def test_skips_invalid_dtb_files_and_uses_the_next_valid_one(tmp_path):
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "a_broken.dtb").write_bytes(b"garbage, not a dtb at all")
    (tmp_path / "b_valid.dtb").write_bytes(_build_fake_dtb())

    result = identify_from_boot_directory(tmp_path)

    assert result.info is not None
    assert result.info.board_compatible == "rk3326-evb-lp3-v12"
    assert result.failure_reason is None


def test_returns_all_dtb_invalid_when_every_dtb_file_is_unreadable(tmp_path):
    (tmp_path / "a_broken.dtb").write_bytes(b"garbage, not a dtb at all")
    (tmp_path / "b_broken.dtb").write_bytes(b"also not a dtb")

    result = identify_from_boot_directory(tmp_path)

    assert result.info is None
    assert result.failure_reason == IdentifyFailureReason.ALL_DTB_INVALID
    assert sorted(result.examined_files) == sorted(
        [str(tmp_path / "a_broken.dtb"), str(tmp_path / "b_broken.dtb")]
    )


def test_returns_all_dtb_invalid_when_dtb_parses_but_has_no_board_compatible(tmp_path):
    """.dtb structurellement valide (magic correct, pas d'exception) mais
    sans `compatible` racine exploitable -- une identification « ? »
    n'aide personne, traité comme un échec plutôt qu'un faux succès."""
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "no_board.dtb").write_bytes(_build_fake_dtb(board_compatible=""))

    result = identify_from_boot_directory(tmp_path)

    assert result.info is None
    assert result.failure_reason == IdentifyFailureReason.ALL_DTB_INVALID
