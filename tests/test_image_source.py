"""Tests de l'ouverture d'image avec décompression à la volée
(imaging/image_source.py) — fichiers factices générés localement (`gzip`,
`lzma` stdlib), aucun téléchargement ni image réelle."""

from __future__ import annotations

import gzip
import lzma

import pytest

from r36s_studio.imaging.image_source import (
    SevenZipArchiveError,
    UnsupportedImageFormatError,
    _detect_format,
    check_image_format,
    estimate_total_bytes,
    open_image_source,
)

_SEVEN_ZIP_MAGIC = bytes.fromhex("377ABCAF271C")

FAKE_IMAGE_DATA = b"R36S-fake-disk-image-" * 500  # 10 500 octets


def test_open_plain_img_reads_raw_bytes(tmp_path):
    path = tmp_path / "sd.img"
    path.write_bytes(FAKE_IMAGE_DATA)

    with open_image_source(str(path)) as f:
        assert f.read() == FAKE_IMAGE_DATA


def test_open_gz_decompresses_on_the_fly(tmp_path):
    path = tmp_path / "sd.img.gz"
    path.write_bytes(gzip.compress(FAKE_IMAGE_DATA))

    with open_image_source(str(path)) as f:
        assert f.read() == FAKE_IMAGE_DATA


def test_open_xz_decompresses_on_the_fly(tmp_path):
    path = tmp_path / "sd.img.xz"
    path.write_bytes(lzma.compress(FAKE_IMAGE_DATA))

    with open_image_source(str(path)) as f:
        assert f.read() == FAKE_IMAGE_DATA


def test_unsupported_extension_is_rejected(tmp_path):
    path = tmp_path / "sd.img.zip"
    path.write_bytes(b"PK\x03\x04")  # zip non supporté en phase 3

    with pytest.raises(ValueError):
        open_image_source(str(path))


def test_estimate_total_bytes_exact_for_plain_img(tmp_path):
    path = tmp_path / "sd.img"
    path.write_bytes(FAKE_IMAGE_DATA)

    assert estimate_total_bytes(str(path)) == len(FAKE_IMAGE_DATA)


def test_estimate_total_bytes_exact_for_gz_via_isize_field(tmp_path):
    path = tmp_path / "sd.img.gz"
    path.write_bytes(gzip.compress(FAKE_IMAGE_DATA))

    assert estimate_total_bytes(str(path)) == len(FAKE_IMAGE_DATA)


def test_estimate_total_bytes_exact_for_xz_via_index_footer(tmp_path):
    # Bug corrigé : la barre de progression affichait 100 % dès le premier
    # octet écrit lors d'un flash .xz (la copie était traitée comme non
    # bornée, `copy_range` rapportant alors `done` comme `total`). La taille
    # décompressée est en fait récupérable sans décompression complète, via
    # l'Index au pied de l'archive xz (format-xz.txt) -- pas besoin de tout
    # lire, ni d'un repli sur la taille compressée du fichier.
    path = tmp_path / "sd.img.xz"
    path.write_bytes(lzma.compress(FAKE_IMAGE_DATA))

    assert estimate_total_bytes(str(path)) == len(FAKE_IMAGE_DATA)


def test_estimate_total_bytes_is_none_for_missing_xz_file():
    assert estimate_total_bytes("whatever.img.xz") is None


def test_estimate_total_bytes_is_none_for_xz_with_corrupted_footer(tmp_path):
    path = tmp_path / "sd.img.xz"
    valid = lzma.compress(FAKE_IMAGE_DATA)
    # Magique du pied ("YZ", les 2 derniers octets) écrasée : un format non
    # standard doit produire None, jamais une taille inventée.
    path.write_bytes(valid[:-2] + b"\x00\x00")

    assert estimate_total_bytes(str(path)) is None


# --- check_image_format / _detect_format -----------------------------------
# Détection par octets d'en-tête (§5), pas seulement l'extension : les images
# ArkOS sont distribuées en .7z, et un fichier renommé (ex. .7z -> .img) doit
# être reconnu pour ce qu'il est réellement plutôt que d'être silencieusement
# écrit tel quel sur la carte (règle §2 n°5/n°6).


def test_detect_format_recognizes_gzip_by_header(tmp_path):
    path = tmp_path / "whatever"  # extension trompeuse, volontairement absente
    path.write_bytes(gzip.compress(FAKE_IMAGE_DATA))

    assert _detect_format(str(path)) == "gz"


def test_detect_format_recognizes_xz_by_header(tmp_path):
    path = tmp_path / "whatever"
    path.write_bytes(lzma.compress(FAKE_IMAGE_DATA))

    assert _detect_format(str(path)) == "xz"


def test_detect_format_recognizes_zip_by_header(tmp_path):
    path = tmp_path / "whatever"
    path.write_bytes(b"PK\x03\x04" + b"\x00" * 20)

    assert _detect_format(str(path)) == "zip"


def test_detect_format_recognizes_seven_zip_by_header(tmp_path):
    path = tmp_path / "whatever"
    path.write_bytes(_SEVEN_ZIP_MAGIC + b"\x00" * 20)

    assert _detect_format(str(path)) == "7z"


def test_detect_format_falls_back_to_raw_for_unrecognized_header(tmp_path):
    path = tmp_path / "sd.img"
    path.write_bytes(FAKE_IMAGE_DATA)  # ne commence par aucune signature connue

    assert _detect_format(str(path)) == "raw"


def test_detect_format_falls_back_to_raw_for_missing_file():
    assert _detect_format("/no/such/file.img") == "raw"


def test_check_image_format_raises_seven_zip_error_for_7z_content(tmp_path):
    path = tmp_path / "ArkOS.img"  # renommé en .img -- doit quand même être détecté
    path.write_bytes(_SEVEN_ZIP_MAGIC + b"\x00" * 20)

    with pytest.raises(SevenZipArchiveError):
        check_image_format(str(path))


def test_check_image_format_raises_seven_zip_error_with_the_real_extension_too(tmp_path):
    path = tmp_path / "ArkOS_R36S.7z"
    path.write_bytes(_SEVEN_ZIP_MAGIC + b"\x00" * 20)

    with pytest.raises(SevenZipArchiveError):
        check_image_format(str(path))


def test_check_image_format_raises_unsupported_for_zip_content(tmp_path):
    path = tmp_path / "sd.img.zip"
    path.write_bytes(b"PK\x03\x04" + b"\x00" * 20)

    with pytest.raises(UnsupportedImageFormatError):
        check_image_format(str(path))


def test_check_image_format_accepts_plain_img(tmp_path):
    path = tmp_path / "sd.img"
    path.write_bytes(FAKE_IMAGE_DATA)

    check_image_format(str(path))  # ne doit pas lever


def test_check_image_format_accepts_gz_and_xz(tmp_path):
    gz_path = tmp_path / "sd.img.gz"
    gz_path.write_bytes(gzip.compress(FAKE_IMAGE_DATA))
    xz_path = tmp_path / "sd.img.xz"
    xz_path.write_bytes(lzma.compress(FAKE_IMAGE_DATA))

    check_image_format(str(gz_path))
    check_image_format(str(xz_path))


def test_seven_zip_archive_error_is_an_unsupported_image_format_error(tmp_path):
    """`SEVEN_ZIP_ARCHIVE` est un cas particulier d'`UNSUPPORTED_IMAGE_FORMAT`
    (§5) -- un appelant qui n'a pas besoin de distinguer les deux (le CLI
    direct, par exemple) peut se contenter d'attraper la classe de base."""
    assert issubclass(SevenZipArchiveError, UnsupportedImageFormatError)
