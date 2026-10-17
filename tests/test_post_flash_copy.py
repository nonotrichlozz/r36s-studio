"""Tests de `partitions/post_flash_copy.py` -- copies dans une partition
de la carte juste après un flash (ex. `dtb.img` de ROCKNIX sur H700).
Partition simulée par un dossier temporaire."""

from __future__ import annotations

import pytest

from r36s_studio.partitions.post_flash_copy import (
    PostFlashCopy,
    PostFlashCopyError,
    appliquer,
    chemin_relatif_sur,
    copies_depuis_json,
)

DTB = "device_trees/sun50i-h700-anbernic-rg40xx-v.dtb"


@pytest.mark.parametrize(
    "chemin,attendu",
    [
        (DTB, True),
        ("dtb.img", True),
        ("../dtb.img", False),
        ("device_trees/../../x", False),
        ("/etc/passwd", False),
        ("\\\\server\\x", False),
        ("C:/Windows/x", False),
        ("a//b", False),
        ("./dtb.img", False),
        ("", False),
        (None, False),
        ("a b.dtb", False),
    ],
)
def test_chemin_relatif_sur(chemin, attendu):
    assert chemin_relatif_sur(chemin) is attendu


def test_copies_depuis_json_valide():
    copies = copies_depuis_json([{"partition": "ROCKNIX", "copier": DTB, "vers": "dtb.img"}])
    assert copies == [PostFlashCopy("ROCKNIX", DTB, "dtb.img")]


def test_copies_depuis_json_absent_donne_liste_vide():
    assert copies_depuis_json(None) == []


@pytest.mark.parametrize(
    "data",
    [
        "texte",
        [{"partition": "ROCKNIX", "copier": DTB}],
        [{"partition": "ROCKNIX", "copier": "../x", "vers": "dtb.img"}],
        [{"partition": "ROC KNIX", "copier": DTB, "vers": "dtb.img"}],
        [{"partition": "ROCKNIX", "copier": "dtb.img", "vers": "dtb.img"}],
        [{"partition": "ROCKNIX", "copier": DTB, "vers": "dtb.img"}, "pas un objet"],
        [{"partition": "ROCKNIX", "copier": DTB, "vers": "dtb.img"}] * 9,
    ],
)
def test_une_entree_invalide_rejette_toute_la_liste(data):
    assert copies_depuis_json(data) is None


def test_appliquer_copie_le_dtb_a_la_racine(tmp_path):
    (tmp_path / "device_trees").mkdir()
    (tmp_path / DTB).write_bytes(b"dtb rg40xx-v")

    ecrites = appliquer(tmp_path, [PostFlashCopy("ROCKNIX", DTB, "dtb.img")])

    assert ecrites == ["dtb.img"]
    assert (tmp_path / "dtb.img").read_bytes() == b"dtb rg40xx-v"
    assert (tmp_path / DTB).exists()  # la source reste en place


def test_appliquer_source_absente_leve(tmp_path):
    with pytest.raises(PostFlashCopyError):
        appliquer(tmp_path, [PostFlashCopy("ROCKNIX", DTB, "dtb.img")])
    assert not (tmp_path / "dtb.img").exists()


def test_appliquer_refuse_un_chemin_invalide_meme_construit_a_la_main(tmp_path):
    with pytest.raises(PostFlashCopyError):
        appliquer(tmp_path, [PostFlashCopy("ROCKNIX", "../secret", "dtb.img")])
