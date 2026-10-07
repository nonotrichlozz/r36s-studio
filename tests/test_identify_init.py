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


# --- consoles clones -- critère validé par l'outil officiel ArkOS : le nom
# du fichier .dtb présent sur la carte, pas son contenu. Confirmé sur du
# vrai matériel : une carte GPT/EFI relevée séparément (§4.4, CLAUDE.md)
# porte deux .dtb identiques, rf3536k3ka.dtb et rk3326-evb-lp3-v12-linux.dtb
# -- le second nomme la carte comme clone même si son contenu ne diffère en
# rien d'un .dtb de R36S standard.


def test_detects_clone_from_known_clone_dtb_filename(tmp_path):
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "rk3326-evb-lp3-v12-linux.dtb").write_bytes(_build_fake_dtb())

    result = identify_from_boot_directory(tmp_path)

    assert result.is_clone is True


def test_does_not_flag_a_standard_r35s_dtb_filename_as_clone(tmp_path):
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "rk3326-r35s-linux.dtb").write_bytes(_build_fake_dtb())

    result = identify_from_boot_directory(tmp_path)

    assert result.is_clone is False


def test_does_not_flag_a_standard_r36s_dtb_filename_as_clone(tmp_path):
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "gameconsole-r36s.dtb").write_bytes(_build_fake_dtb())

    result = identify_from_boot_directory(tmp_path)

    assert result.is_clone is False


def test_clone_filename_detection_is_case_insensitive(tmp_path):
    """La casse du nom (hors extension -- la découverte des `.dtb` elle-même
    ne cherche que `*.dtb` en minuscules, sans rapport avec ce correctif)
    ne doit pas empêcher la détection."""
    from tests.test_identify_dtb import _build_fake_dtb

    (tmp_path / "RK3326-EVB-LP3-V12-Linux.dtb").write_bytes(_build_fake_dtb())

    result = identify_from_boot_directory(tmp_path)

    assert result.is_clone is True


def test_detects_clone_even_when_the_alphabetically_first_dtb_has_a_different_name(tmp_path):
    """Reproduction exacte du cas relevé sur du vrai matériel : deux .dtb
    identiques, dont celui qui trie en premier (`identify_from_boot_
    directory` choisit le premier valide pour l'identification de carte)
    ne porte pas le nom du clone -- la détection de clone doit malgré tout
    regarder tous les .dtb trouvés, pas seulement celui retenu pour
    `info`."""
    from tests.test_identify_dtb import _build_fake_dtb

    content = _build_fake_dtb()
    (tmp_path / "rf3536k3ka.dtb").write_bytes(content)  # trie avant, alphabétiquement
    (tmp_path / "rk3326-evb-lp3-v12-linux.dtb").write_bytes(content)

    result = identify_from_boot_directory(tmp_path)

    assert result.info is not None  # l'identification normale n'est pas affectée
    assert result.is_clone is True


def test_is_clone_false_when_no_dtb_found():
    result = IdentifyResult()
    assert result.is_clone is False


def test_clone_detection_does_not_require_a_valid_dtb_parse(tmp_path):
    """Le critère est le nom du fichier, pas son contenu -- même un .dtb
    illisible/corrompu doit être détecté comme clone si son nom
    correspond."""
    (tmp_path / "rk3326-evb-lp3-v12-linux.dtb").write_bytes(b"pas un vrai dtb")

    result = identify_from_boot_directory(tmp_path)

    assert result.failure_reason == IdentifyFailureReason.ALL_DTB_INVALID
    assert result.is_clone is True


# --- accès refusé (Windows, BOOT EFI) et transport depuis le worker élevé ----


def test_access_denied_is_never_reported_as_no_dtb_found(tmp_path, monkeypatch):
    """Bug corrigé, carte ArkOS GPT réelle : sans élévation, Windows refuse
    de lire la partition EFI ; le message disait « aucune information de
    modèle -- normal pour une carte tout juste flashée »."""

    def denied(path):
        raise PermissionError(5, "Accès refusé", str(path))

    monkeypatch.setattr("r36s_studio.identify.os.listdir", denied)

    result = identify_from_boot_directory(tmp_path)

    assert result.failure_reason == IdentifyFailureReason.ACCESS_DENIED
    assert "Accès refusé" in result.detail


def test_result_survives_the_trip_through_the_worker():
    from r36s_studio.identify import result_from_dict, result_to_dict

    original = IdentifyResult(
        info=DtbInfo(board_compatible="rockchip,rk3326-evb-lp3-v12-linux", panel_compatible="sitronix,st7703", timings={"hactive": 640}),
        scanned_directory="I:\\",
        examined_files=["I:\\a.dtb"],
        is_clone=True,
    )
    failure = IdentifyResult(failure_reason=IdentifyFailureReason.ACCESS_DENIED, detail="refus")

    assert result_from_dict(result_to_dict(original)) == original
    assert result_from_dict(result_to_dict(failure)) == failure
