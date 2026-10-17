"""Source MEGA de « Télécharger et installer » (`consoles_diverses/mega.py`,
`telechargement.py`, muOS) : un faux dossier MEGA chiffré comme le vrai
(clé de dossier, clés de fichiers en AES-ECB, attributs en AES-CBC,
contenu en AES-CTR), servi par un opener injecté -- aucun appel réseau."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import struct

import pytest
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from r36s_studio.consoles_diverses import mega
from r36s_studio.consoles_diverses.telechargement import (
    TelechargementErreur,
    resoudre,
    telechargement_depuis_json,
)
from r36s_studio.identify import rocknix

IMAGE = "MustardOS_RG40XX-V_2601.1_FUNKY_JACARANDA-bc38efa0.img.gz"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _enc(cle: bytes, mode, data: bytes) -> bytes:
    e = Cipher(algorithms.AES(cle), mode).encryptor()
    return e.update(data) + e.finalize()


class FauxDossier:
    def __init__(self, fichiers: dict, coupure: int = 0):
        self.cle = os.urandom(16)
        self.lien = f"https://mega.nz/folder/AbCdEf12#{_b64(self.cle)}"
        self.noeuds, self.contenus = [], {}
        self.coupure = coupure  # octets servis avant une coupure (quota)
        for i, (nom, contenu) in enumerate(fichiers.items()):
            cle, nonce, mac = os.urandom(16), os.urandom(8), os.urandom(8)
            k = struct.unpack(">4I", cle) + struct.unpack(">4I", nonce + mac)
            brute = struct.pack(">8I", k[0] ^ k[4], k[1] ^ k[5], k[2] ^ k[6], k[3] ^ k[7], *k[4:])
            attr = b"MEGA" + json.dumps({"n": nom}).encode()
            attr += bytes(-len(attr) % 16)
            handle = f"h{i:07d}"
            self.noeuds.append(
                {
                    "h": handle,
                    "p": "racine",
                    "t": 0,
                    "s": len(contenu),
                    "a": _b64(_enc(cle, modes.CBC(bytes(16)), attr)),
                    "k": f"autre:{_b64(os.urandom(32))}/racine:{_b64(_enc(self.cle, modes.ECB(), brute))}",
                }
            )
            self.contenus[handle] = _enc(cle, modes.CTR(nonce + bytes(8)), contenu)

    @contextlib.contextmanager
    def opener(self, url, data=None):
        if data is not None:
            assert url.startswith("https://g.api.mega.co.nz/cs?id=0&n=AbCdEf12")
            requete = json.loads(data)[0]
            if requete["a"] == "f":
                yield io.BytesIO(json.dumps([{"f": self.noeuds}]).encode())
            else:
                yield io.BytesIO(json.dumps([{"g": f"https://gfs270n1.userstorage.mega.co.nz/dl/{requete['n']}"}]).encode())
            return
        contenu = self.contenus[url.rsplit("/", 1)[-1]]
        yield io.BytesIO(contenu[: self.coupure] if self.coupure else contenu)


def _tel(dossier: FauxDossier):
    return telechargement_depuis_json(
        {"source": "mega", "dossier": dossier.lien, "motif_fichier": r"^MustardOS_RG40XX-V_.*\.img\.gz$"}
    )


def test_mega_entry_is_parsed_without_a_github_repository():
    tel = _tel(FauxDossier({}))
    assert tel is not None and tel.source == "mega" and tel.depot == "" and tel.url_directe is None


@pytest.mark.parametrize(
    "dossier",
    [
        "https://mega.nz/file/AbCdEf12#" + "A" * 22,  # un fichier, pas un dossier
        "https://evil.example/folder/AbCdEf12#" + "A" * 22,
        "http://mega.nz/folder/AbCdEf12#" + "A" * 22,
        "https://mega.nz/folder/AbCdEf12",  # sans clé
    ],
)
def test_mega_entry_refuses_anything_but_an_official_folder_link(dossier):
    assert telechargement_depuis_json({"source": "mega", "dossier": dossier, "motif_fichier": "x"}) is None


def test_unknown_source_has_no_button():
    assert telechargement_depuis_json({"source": "gofile", "depot": "a/b", "motif_fichier": "x"}) is None


def test_resolve_finds_the_image_its_published_sha256_and_decrypts_it(tmp_path):
    image = os.urandom(70_000)
    hash_txt = f"{'0' * 64} autre.img.gz\n{hashlib.sha256(image).hexdigest()} {IMAGE}\n".encode()
    dossier = FauxDossier({"hash.txt": hash_txt, "MustardOS_RG35XX-H_x.img.gz": b"autre", IMAGE: image})

    fichier = resoudre(_tel(dossier), opener=dossier.opener)

    assert fichier.nom == IMAGE and fichier.taille == len(image)
    assert fichier.sha256 == hashlib.sha256(image).hexdigest()
    assert mega.url_contenu_sure(fichier.url)
    destination = tmp_path / IMAGE
    rocknix.download_asset(
        rocknix.RocknixAsset(name=fichier.nom, download_url=fichier.url, size_bytes=fichier.taille),
        destination,
        expected_sha256=fichier.sha256,
        opener=lambda url: dossier.opener(url),
        block_size=4096,
        transform=mega.dechiffreur(*fichier.dechiffrement),
    )
    assert destination.read_bytes() == image


def test_download_cut_short_by_mega_keeps_no_partial_file(tmp_path):
    image = os.urandom(50_000)
    dossier = FauxDossier({IMAGE: image}, coupure=20_000)
    fichier = resoudre(_tel(dossier), opener=dossier.opener)
    assert fichier.sha256 is None  # pas de hash.txt : la taille reste le garde-fou
    destination = tmp_path / IMAGE

    with pytest.raises(rocknix.RocknixReleaseError, match="incomplet"):
        rocknix.download_asset(
            rocknix.RocknixAsset(name=fichier.nom, download_url=fichier.url, size_bytes=fichier.taille),
            destination,
            opener=lambda url: dossier.opener(url),
            transform=mega.dechiffreur(*fichier.dechiffrement),
        )
    assert not destination.exists()


def test_no_matching_file_or_mega_refusal_is_a_clear_error():
    dossier = FauxDossier({"MustardOS_RG35XX-H_x.img.gz": b"autre"})
    with pytest.raises(TelechargementErreur):
        resoudre(_tel(dossier), opener=dossier.opener)

    @contextlib.contextmanager
    def refus(url, data=None):
        yield io.BytesIO(b"-9")  # code d'erreur MEGA (dossier introuvable)

    with pytest.raises(TelechargementErreur, match="MEGA"):
        resoudre(_tel(dossier), opener=refus)


def test_a_file_name_that_is_not_a_flashable_image_is_never_chosen():
    dossier = FauxDossier({"MustardOS_RG40XX-V_x.img.gz.exe": b"x", "MustardOS_RG40XX-V_x.7z": b"x"})
    tel = telechargement_depuis_json({"source": "mega", "dossier": dossier.lien, "motif_fichier": r"^MustardOS_RG40XX-V_"})
    with pytest.raises(TelechargementErreur):
        resoudre(tel, opener=dossier.opener)
