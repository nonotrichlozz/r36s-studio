"""Tests de l'ouverture d'image avec décompression à la volée
(imaging/image_source.py) — fichiers factices générés localement (`gzip`,
`lzma` stdlib), aucun téléchargement ni image réelle."""

from __future__ import annotations

import gzip
import lzma

import pytest

from r36s_studio.imaging.image_source import estimate_total_bytes, open_image_source

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
