"""Tests de gui/strings.py — fichier de traduction isolé (§5)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from r36s_studio.gui.strings import STRINGS, error_log_detail, friendly_error_message, tr


def test_tr_returns_plain_string_without_placeholders():
    assert tr("app_title") == "R36S Studio"


def test_tr_interpolates_kwargs():
    result = tr("confirm_erase", display="Carte X", size_go=12.345)
    assert "Carte X" in result
    assert "12.3" in result


def test_tr_unknown_key_raises():
    with pytest.raises(KeyError):
        tr("clef_qui_n_existe_pas")


def test_no_technical_jargon_in_visible_strings():
    """Vocabulaire (§5) : pas de terme technique dans les chaînes
    visibles."""
    forbidden = ["/dev/", "\\\\.\\physicaldrive", "périphérique bloc", "partition"]
    for key, template in STRINGS.items():
        lowered = template.lower()
        for term in forbidden:
            assert term not in lowered, f"{key!r} contient un terme technique : {term!r}"


# --- friendly_error_message / error_log_detail (bug corrigé : "Une erreur
# est survenue" générique pour des codes réels du protocole, non mappés) --


@pytest.mark.parametrize(
    "code",
    [
        "CANCELLED",
        "PARTITION_NOT_FOUND",
        "PARTITION_NOT_MOUNTED",
        "EASYROMS_NTFS_MACOS",
        "MOUNTPOINT_NOT_WRITABLE",
        "DEVICE_NOT_ALLOWED",
        "SOURCE_NOT_FOUND",
        "VERIFY_FAILED",
        "EJECT_FAILED",
        "MACOS_TCC_BLOCKED",
        "MACOS_TCC_PROTECTED_FOLDER",
        "SEVEN_ZIP_ARCHIVE",
        "UNSUPPORTED_IMAGE_FORMAT",
        "ROCKNIX_ASSET_NOT_FOUND",
        "ROCKNIX_CHECKSUM_MISMATCH",
        "ROCKNIX_DOWNLOAD_FAILED",
        "GAMES_PARTITION_NOT_FOUND",
        "INSUFFICIENT_DISK_SPACE",
        "DESTINATION_TOO_SMALL",
        # Codes émis par __main__.py mais absents de _ERROR_MESSAGE_KEYS
        # jusqu'ici (bug corrigé) -- IO_ERROR en particulier est le repli
        # générique de la quasi-totalité des commandes CLI.
        "OUTPUT_EXISTS",
        "IMAGE_NOT_FOUND",
        "IO_ERROR",
        "UNSUPPORTED_OS",
        "CONFIRMATION_REFUSED",
        "INVALID_ARGS",
    ],
)
def test_friendly_error_message_never_falls_back_to_generic_for_known_codes(code):
    assert friendly_error_message(code) != tr("error_generic")


def test_friendly_error_message_falls_back_to_generic_for_truly_unknown_code():
    assert friendly_error_message("CODE_QUI_N_EXISTE_PAS") == tr("error_generic")


def test_error_log_detail_returns_plain_message_for_known_code():
    assert error_log_detail("EJECT_FAILED", "carte occupée") == "carte occupée"


def test_error_log_detail_prefixes_raw_code_for_unknown_code():
    """Bug corrigé, confirmé sur du vrai matériel : un code sans
    traduction connue ne laissait auparavant aucune trace du code réel
    dans le journal -- seul le message générique s'affichait."""
    detail = error_log_detail("SOME_FUTURE_CODE", "détail brut")
    assert "SOME_FUTURE_CODE" in detail
    assert "détail brut" in detail


def test_error_log_detail_unknown_code_without_message_still_shows_code():
    assert error_log_detail("SOME_FUTURE_CODE", "") == "SOME_FUTURE_CODE"


def test_error_log_detail_handles_none_code_and_message():
    assert error_log_detail(None, None) == ""


def test_every_cli_emitted_error_code_is_mapped_to_a_friendly_message():
    """Balaye `__main__.py::emit_error("CODE", ...)` littéralement --
    filet de sécurité pour qu'un futur code ajouté côté CLI ne retombe
    plus jamais silencieusement sur `error_generic` (bug corrigé,
    confirmé sur du vrai matériel : c'était déjà le cas pour six codes
    avant cette suite de tests)."""
    main_source = (Path(__file__).resolve().parent.parent / "r36s_studio" / "__main__.py").read_text(
        encoding="utf-8"
    )
    codes = set(re.findall(r'emit_error\(\s*"([A-Z_]+)"', main_source))
    assert codes, "aucun code trouvé -- le motif de recherche a-t-il changé ?"
    for code in codes:
        assert friendly_error_message(code) != tr("error_generic"), f"{code!r} n'est pas mappé"
