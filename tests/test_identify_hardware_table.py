"""Table matérielle de dArkOSRE (identify/hardware_table.py) : `model` du
.dtb -> famille de console -> profil du parcours assisté."""

from __future__ import annotations

from r36s_studio.identify import identify_from_boot_directory
from r36s_studio.identify import console_profile as cp
from r36s_studio.identify.dtb import parse_dtb
from r36s_studio.identify.hardware_table import CLONE, R36S, SOYSAUCE, family_for_hardware

from tests.test_identify_dtb import _build_fake_dtb


def test_family_exact_prefix_and_ambiguous():
    assert family_for_hardware("G80CA-MB V1.2-20250422") == CLONE  # sans le « Panel 8 » de dArkOSRE
    assert family_for_hardware("g80ca-mb  v1.2-20250422 panel 9") == CLONE
    assert family_for_hardware("R36S-V21 2024-12-18") == R36S  # model réel des .dtb « 2550 »/« 2552 »
    assert family_for_hardware("Y3506_V03_20241210") == SOYSAUCE
    assert family_for_hardware("R36S-V12 2023-08-18") is None  # R36S et clones
    assert family_for_hardware("R36S-V12 2023-08-18 Panel 0") == R36S
    assert family_for_hardware("G80") is None  # pas un mot entier
    assert family_for_hardware("Hardkernel ODROID-GO3") is None
    assert family_for_hardware(None) is None and family_for_hardware("  ") is None


def test_parse_dtb_reads_root_model():
    assert parse_dtb(_build_fake_dtb(model="G80CA-MB V1.2-20250422")).model == "G80CA-MB V1.2-20250422"
    assert parse_dtb(_build_fake_dtb()).model is None


def test_identify_takes_root_model_and_profiles_it(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.dtb").write_bytes(_build_fake_dtb(model="R36S-V22 2024-12-18"))
    (tmp_path / "z.dtb").write_bytes(_build_fake_dtb(model="G80CA-MB V1.2-20250422"))
    result = identify_from_boot_directory(tmp_path)
    assert result.hardware_model == "G80CA-MB V1.2-20250422"
    assert cp.profile_from_identify(result) == cp.CLONE


def test_darkosre_card_root_dtb_is_a_choice_not_the_console(tmp_path):
    (tmp_path / "dtb").mkdir()
    (tmp_path / "dtb" / "r36_devices.ini").write_text("[x]\n")
    (tmp_path / "board.dtb").write_bytes(_build_fake_dtb(model="G80CA-MB V1.2-20250422 Panel 8"))
    result = identify_from_boot_directory(tmp_path)
    assert result.hardware_model is None
    assert cp.profile_from_identify(result) == cp.ORIGIN  # comportement d'avant : carte lisible


def test_reference_typed_by_user_goes_through_the_table():
    assert cp.profile_from_reference("R36S-V21 2024-12-18") == cp.ORIGIN
    assert cp.profile_from_reference("G80C-MB V1.1-20250319") == cp.CLONE
    assert cp.profile_from_reference("Y3506_V05_20251215") == cp.UNKNOWN
    assert cp.profile_from_reference("g80ca") == cp.CLONE  # ancienne sous-chaîne, toujours là


def test_ambiguous_reference_is_told_to_the_user():
    assert cp.profile_from_reference("R36S-V12 2023-08-18") == cp.AMBIGUOUS  # saisie du 2026-10-14
    assert cp.recommended_releases_url(cp.AMBIGUOUS) == cp.recommended_releases_url(cp.UNKNOWN)
    assert cp.profile_from_reference("R36S-V12 2023-08-18 Panel 0") == cp.ORIGIN
