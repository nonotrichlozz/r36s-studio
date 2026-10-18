"""Tests de `consoles_diverses/telechargement.py` -- téléchargement direct
d'un firmware décrit par une fiche du catalogue. Aucun appel réseau réel :
tout passe par un `opener` simulé."""

from __future__ import annotations

import io
import json

import pytest

from r36s_studio.consoles_diverses.telechargement import (
    FichierFirmware,
    Telechargement,
    TelechargementErreur,
    nom_fichier_sur,
    resoudre,
    telechargement_depuis_json,
    url_github_sure,
)

DEPOT = "knulli-cfw/knulli-linux"
MOTIF = r"^knulli-h700-rg40xx-v-.*\.img\.gz$"
URL_DIRECTE = (
    "https://github.com/knulli-cfw/knulli-linux/releases/download/20260511/"
    "knulli-h700-rg40xx-v-scarab-20260511.img.gz"
)
SHA = "a" * 64


def _release(*assets):
    return {"tag_name": "20261001", "assets": list(assets)}


def _asset(name, size=1234, digest=None):
    data = {
        "name": name,
        "size": size,
        "browser_download_url": f"https://github.com/{DEPOT}/releases/download/20261001/{name}",
    }
    if digest is not None:
        data["digest"] = digest
    return data


def _opener_json(payload, seen=None):
    def opener(url):
        if seen is not None:
            seen.append(url)
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    return opener


def _opener_en_panne(url):
    raise OSError("réseau indisponible")


def _tel(**kwargs):
    base = {"depot": DEPOT, "motif_fichier": MOTIF, "url_directe": URL_DIRECTE}
    base.update(kwargs)
    return Telechargement(**base)


# --- parsing -----------------------------------------------------------------


def test_parsing_complet():
    tel = telechargement_depuis_json({"depot": DEPOT, "motif_fichier": MOTIF, "url_directe": URL_DIRECTE})
    assert tel == Telechargement(DEPOT, MOTIF, URL_DIRECTE)


@pytest.mark.parametrize(
    "data",
    [
        None,
        "texte",
        {"motif_fichier": MOTIF},
        {"depot": DEPOT},
        {"depot": "pas un depot", "motif_fichier": MOTIF},
        {"depot": "../../etc", "motif_fichier": MOTIF},
        {"depot": DEPOT, "motif_fichier": "(["},
        {"depot": DEPOT, "motif_fichier": ""},
    ],
)
def test_parsing_inexploitable_donne_none(data):
    assert telechargement_depuis_json(data) is None


@pytest.mark.parametrize(
    "url",
    ["http://github.com/x/y.img.gz", "https://evil.example/x.img.gz", "file:///etc/passwd", "javascript:alert(1)"],
)
def test_url_directe_non_github_ignoree(url):
    tel = telechargement_depuis_json({"depot": DEPOT, "motif_fichier": MOTIF, "url_directe": url})
    assert tel is not None and tel.url_directe is None


def test_url_github_sure():
    assert url_github_sure(URL_DIRECTE)
    assert not url_github_sure("https://github.com.evil.example/x")


@pytest.mark.parametrize(
    "nom,attendu",
    [
        ("knulli.img.gz", True),
        ("rocknix.img.xz", True),
        ("image.img", True),
        ("archive.7z.001", False),
        ("outil.zip", False),
        ("../evil.img.gz", False),
        ("dossier\\evil.img", False),
        (".cache.img", False),
        ("", False),
    ],
)
def test_nom_fichier_sur(nom, attendu):
    assert nom_fichier_sur(nom) is attendu


# --- résolution ----------------------------------------------------------------


def test_derniere_release_prioritaire():
    seen = []
    opener = _opener_json(
        _release(
            _asset("knulli-h700-rg40xx-h-scarab-20261001.img.gz"),
            _asset("knulli-h700-rg40xx-v-scarab-20261001.img.gz", size=999, digest=f"sha256:{SHA}"),
        ),
        seen,
    )
    fichier = resoudre(_tel(), opener=opener)
    assert fichier == FichierFirmware(
        nom="knulli-h700-rg40xx-v-scarab-20261001.img.gz",
        url=f"https://github.com/{DEPOT}/releases/download/20261001/knulli-h700-rg40xx-v-scarab-20261001.img.gz",
        taille=999,
        sha256=SHA,
        depuis_derniere_release=True,
    )
    assert seen == [f"https://api.github.com/repos/{DEPOT}/releases/latest"]


def test_digest_invalide_ignore():
    opener = _opener_json(_release(_asset("knulli-h700-rg40xx-v-x.img.gz", digest="md5:abc")))
    assert resoudre(_tel(), opener=opener).sha256 is None


def test_asset_hors_github_ignore():
    asset = _asset("knulli-h700-rg40xx-v-x.img.gz")
    asset["browser_download_url"] = "https://evil.example/knulli-h700-rg40xx-v-x.img.gz"
    fichier = resoudre(_tel(), opener=_opener_json(_release(asset)))
    assert fichier.url == URL_DIRECTE
    assert not fichier.depuis_derniere_release


def test_repli_url_directe_si_api_en_panne():
    fichier = resoudre(_tel(), opener=_opener_en_panne)
    assert fichier == FichierFirmware(nom="knulli-h700-rg40xx-v-scarab-20260511.img.gz", url=URL_DIRECTE)


def test_repli_url_directe_si_aucun_fichier_correspondant():
    opener = _opener_json(_release(_asset("knulli-h700-rg35xx-h-scarab.img.gz")))
    assert resoudre(_tel(), opener=opener).url == URL_DIRECTE


def test_repli_url_directe_si_json_invalide():
    def opener(url):
        return io.BytesIO(b"pas du json")

    assert resoudre(_tel(), opener=opener).url == URL_DIRECTE


def test_erreur_sans_rien_a_telecharger():
    with pytest.raises(TelechargementErreur):
        resoudre(_tel(url_directe=None), opener=_opener_en_panne)


def test_motif_7z_jamais_retenu():
    """Une archive .7z (non flashable directement) n'est jamais choisie,
    même si le motif de la fiche la laisse passer."""
    opener = _opener_json(_release(_asset("knulli-h700-rg40xx-v-x.7z.001")))
    tel = _tel(motif_fichier=r"rg40xx-v", url_directe=None)
    with pytest.raises(TelechargementErreur):
        resoudre(tel, opener=opener)


# --- apres_flash -------------------------------------------------------------


def test_parsing_avec_apres_flash():
    from r36s_studio.partitions.post_flash_copy import PostFlashCopy

    tel = telechargement_depuis_json(
        {
            "depot": "ROCKNIX/distribution",
            "motif_fichier": r"^ROCKNIX-H700\.aarch64-.*-DDR4\.img\.gz$",
            "apres_flash": [
                {"partition": "ROCKNIX", "copier": "device_trees/sun50i-h700-anbernic-rg40xx-v.dtb", "vers": "dtb.img"}
            ],
        }
    )
    assert tel.apres_flash == (
        PostFlashCopy("ROCKNIX", "device_trees/sun50i-h700-anbernic-rg40xx-v.dtb", "dtb.img"),
    )


def test_apres_flash_invalide_retire_tout_le_telechargement():
    tel = telechargement_depuis_json(
        {
            "depot": DEPOT,
            "motif_fichier": MOTIF,
            "apres_flash": [{"partition": "ROCKNIX", "copier": "../../x", "vers": "dtb.img"}],
        }
    )
    assert tel is None


def test_sans_apres_flash_tuple_vide():
    assert telechargement_depuis_json({"depot": DEPOT, "motif_fichier": MOTIF}).apres_flash == ()


CONSIGNE = (
    "Branche la console sur secteur avant de l'allumer, même si la batterie est chargée à 100 % : "
    "KNULLI ne lance son installation que sur secteur."
)


def test_consigne_premier_demarrage_lue_en_texte_brut_sur_une_ligne():
    tel = telechargement_depuis_json(
        {"depot": DEPOT, "motif_fichier": MOTIF, "consigne_premier_demarrage": "  Branche\n\tla console\x00 sur secteur. "}
    )
    assert tel.consigne_premier_demarrage == "Branche la console sur secteur."
    assert telechargement_depuis_json(
        {"depot": DEPOT, "motif_fichier": MOTIF, "consigne_premier_demarrage": CONSIGNE}
    ).consigne_premier_demarrage == CONSIGNE


@pytest.mark.parametrize("valeur", [None, 42, ["x"], "", "   ", "x" * 401])
def test_consigne_absente_ou_invalide_ignoree_sans_retirer_le_bouton(valeur):
    data = {"depot": DEPOT, "motif_fichier": MOTIF}
    if valeur is not None:
        data["consigne_premier_demarrage"] = valeur
    tel = telechargement_depuis_json(data)
    assert tel is not None and tel.consigne_premier_demarrage is None
