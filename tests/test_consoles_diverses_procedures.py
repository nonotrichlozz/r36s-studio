"""Moteur des installations guidées par USB (`consoles_diverses/procedures/`) :
lecture de la fiche, plan des phases, en-tête .pac, téléchargement avec
reprise et SHA-256, 7-Zip (mot de passe sur l'entrée standard), sortie de
CmdDloader, appareils USB, pilotes, outils, commande du worker élevé.
Aucun réseau, aucun vrai programme lancé (`_forbid_real_subprocess`)."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from r36s_studio.consoles_diverses.models import fiche_depuis_json
from r36s_studio.consoles_diverses.procedures import cmddloader, outils, pac, pilotes, septzip, usb
from r36s_studio.consoles_diverses.procedures import telechargement as tel
from r36s_studio.consoles_diverses.procedures.fiche import (
    auteur_depuis_url,
    fichiers_a_telecharger,
    motif_desactivation,
    premiere_url,
    procedure_depuis_json,
    procedures_depuis_json,
    version_a_verifier,
)

FIXTURE = Path(__file__).parent / "fixtures_fiche_anbernic_rg_rotate.json"


def _fiche_json() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _procedures():
    return {p.id: p for p in procedures_depuis_json(_fiche_json()["procedures"])}


# --- fiche -------------------------------------------------------------------


def test_les_trois_procedures_sont_lues():
    procs = _procedures()
    assert set(procs) == {
        "gammaos-next-1-4-1-installation",
        "gammaos-next-1-4-1-restauration-super",
        "firmware-origine-restauration",
    }
    inst = procs["gammaos-next-1-4-1-installation"]
    assert inst.efface_donnees and inst.mot_de_passe_requis
    assert inst.vid_pid == ["1782:4d00"] and inst.vid_pid_a_verifier
    assert inst.pac_produit == "ums512_1h10"
    assert [v.id for v in inst.variantes] == ["lite", "full"]
    assert inst.variante("lite").recommande and inst.variante("lite").pac_nom == "RG_ROTATE_GAMMAOS_NEXT_LITE"
    assert inst.variante("lite").fichier_final == "ums512_1h10_rg_rotate_gammaos_1.4.1_lite.pac"
    assert len(inst.depannage) == 4


def test_la_fiche_complete_porte_ses_procedures():
    fiche = fiche_depuis_json(_fiche_json())
    assert len(fiche.procedures) == 3


def test_phases_de_l_installation_dans_l_ordre():
    assert _procedures()["gammaos-next-1-4-1-installation"].phases() == [
        "prerequis", "telechargement", "pilotes", "extraction", "verification_pac", "consignes", "flash",
        "premier_demarrage",
    ]


def test_un_flash_impose_outils_pilotes_et_verification():
    phases = _procedures()["firmware-origine-restauration"].phases()
    assert {"telechargement", "pilotes", "verification_pac", "flash"} <= set(phases)


def test_installation_disponible_sous_windows_seulement():
    inst = _procedures()["gammaos-next-1-4-1-installation"]
    assert motif_desactivation(inst, "windows") is None
    assert motif_desactivation(inst, "macos") == "systeme"
    assert motif_desactivation(inst, "linux") == "systeme"


def test_restauration_super_desactivee_etape_inconnue():
    """`selectionner_partitions` n'est pas pris en charge : jamais un flash
    complet à la place d'un flash de la seule partition Super."""
    assert motif_desactivation(_procedures()["gammaos-next-1-4-1-restauration-super"], "windows") == "etape"


def test_sans_pac_produit_aucun_flash():
    data = _fiche_json()["procedures"][0]
    del data["pac_produit"]
    assert motif_desactivation(procedure_depuis_json(data), "windows") == "pac"


def test_autre_mode_desactive():
    data = dict(_fiche_json()["procedures"][0], mode="carte_sd")
    assert motif_desactivation(procedure_depuis_json(data), "windows") == "mode"


def test_fichiers_par_variante_et_telechargeables():
    inst = _procedures()["gammaos-next-1-4-1-installation"]
    noms = [f.nom for f in fichiers_a_telecharger(inst, "lite")]
    assert noms == [
        "ums512_1h10_rg_rotate_gammaos_1.4.1_lite.7z.001",
        "ums512_1h10_rg_rotate_gammaos_1.4.1_lite.7z.002",
        "UnisocTools_RG_ROTATE.zip",
    ]
    origine = _procedures()["firmware-origine-restauration"]
    # Google Drive : jamais téléchargé automatiquement.
    assert [f.nom for f in fichiers_a_telecharger(origine, None)] == ["UnisocTools_RG_ROTATE.zip"]


def test_fichier_sans_sha256_n_est_pas_telecharge():
    data = _fiche_json()["procedures"][0]
    for t in data["telechargements"]:
        t.pop("sha256", None)
    assert fichiers_a_telecharger(procedure_depuis_json(data), "lite") == []


def test_entrees_inexploitables_ignorees():
    assert procedures_depuis_json([None, {}, {"id": "x"}, "texte"]) == []
    assert procedures_depuis_json("pas une liste") == []
    data = _fiche_json()["procedures"][0]
    data["variantes"][0]["fichier_final"] = "../../windows/system32/x.pac"
    assert procedure_depuis_json(data).variantes[0].fichier_final is None


def test_url_non_https_refusee():
    data = _fiche_json()["procedures"][0]
    data["telechargements"][0]["url"] = "http://exemple.org/x"
    assert all(f.url.startswith("https://") for f in procedure_depuis_json(data).telechargements)


def test_auteur_lien_et_version():
    assert auteur_depuis_url("https://github.com/TheGammaSqueeze/GammaOSNext/releases/tag/x") == "TheGammaSqueeze"
    assert auteur_depuis_url("https://drive.google.com/file/d/x") is None
    assert premiere_url("Réservé (https://www.patreon.com/GammaOS). Saisis-le.") == "https://www.patreon.com/GammaOS"
    assert premiere_url("aucun lien") is None
    procs = _procedures()
    assert version_a_verifier(procs["gammaos-next-1-4-1-installation"]) == "1.4.1"
    assert version_a_verifier(procs["firmware-origine-restauration"]) is None


# --- en-tête .pac --------------------------------------------------------------


def _faux_pac(chemin: Path, produit="ums512_1h10", version="1.4.1", nom="RG_ROTATE_GAMMAOS_NEXT_LITE", fmt="BP_R2.0.1"):
    """Faux .pac minimal : les champs aux positions relevées sur le vrai."""
    donnees = bytearray(pac.TAILLE_EN_TETE + 64)
    for debut, texte in ((0, fmt), (52, produit), (564, version), (1104, nom)):
        brut = texte.encode("utf-16-le")
        donnees[debut : debut + len(brut)] = brut
    struct.pack_into("<I", donnees, 1076, 71)
    chemin.write_bytes(bytes(donnees))
    return chemin


def test_en_tete_pac(tmp_path):
    en_tete = pac.lire_en_tete(_faux_pac(tmp_path / "a.pac"))
    assert (en_tete.format, en_tete.produit, en_tete.version, en_tete.nom, en_tete.nombre_fichiers) == (
        "BP_R2.0.1", "ums512_1h10", "1.4.1", "RG_ROTATE_GAMMAOS_NEXT_LITE", 71,
    )
    assert pac.ecart(en_tete, "UMS512_1H10", "1.4.1", "rg_rotate_gammaos_next_lite") is None


@pytest.mark.parametrize(
    "attendu,champ",
    [
        (("ums9230_xxx", "1.4.1", None), "produit"),
        (("ums512_1h10", "1.4.0", None), "version"),
        (("ums512_1h10", "1.4.1", "RG_ROTATE_GAMMAOS_NEXT_FULL"), "nom"),
        (("ums512_1h10", None, None), None),
    ],
)
def test_ecart_pac(tmp_path, attendu, champ):
    en_tete = pac.lire_en_tete(_faux_pac(tmp_path / "a.pac"))
    assert pac.ecart(en_tete, *attendu) == champ


def test_pac_invalide(tmp_path):
    (tmp_path / "court.pac").write_bytes(b"BP_R")
    with pytest.raises(pac.PacInvalide):
        pac.lire_en_tete(tmp_path / "court.pac")
    with pytest.raises(pac.PacInvalide):
        pac.lire_en_tete(_faux_pac(tmp_path / "zip.pac", fmt="PK\x03\x04"))


# --- téléchargement ---------------------------------------------------------------


class _Reponse(io.BytesIO):
    def __init__(self, contenu: bytes, status=200):
        super().__init__(contenu)
        self.status = status
        self.headers = {"Content-Length": str(len(contenu))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _opener(contenu: bytes, honore_range=True):
    requetes = []

    def ouvrir(requete, timeout=None):
        requetes.append(requete)
        plage = requete.get_header("Range")
        if plage and honore_range:
            debut = int(plage.split("=")[1].rstrip("-"))
            return _Reponse(contenu[debut:], status=206)
        return _Reponse(contenu)

    ouvrir.requetes = requetes
    return ouvrir


def test_telechargement_complet_et_sha256(tmp_path):
    contenu = b"x" * 3_000_000
    sha = hashlib.sha256(contenu).hexdigest()
    vus = []
    chemin = tel.telecharger("https://github.com/a/b", tmp_path / "f.bin", sha, lambda f, t: vus.append((f, t)),
                             opener=_opener(contenu))
    assert chemin.read_bytes() == contenu
    assert vus[-1] == (len(contenu), len(contenu))
    assert not (tmp_path / "f.bin.part").exists()


def test_telechargement_reprend_apres_coupure(tmp_path):
    contenu = bytes(range(256)) * 10_000
    (tmp_path / "f.bin.part").write_bytes(contenu[:1000])
    ouvrir = _opener(contenu)
    tel.telecharger("https://github.com/a/b", tmp_path / "f.bin", hashlib.sha256(contenu).hexdigest(), opener=ouvrir)
    assert ouvrir.requetes[0].get_header("Range") == "bytes=1000-"
    assert (tmp_path / "f.bin").read_bytes() == contenu


def test_serveur_sans_range_repart_de_zero(tmp_path):
    contenu = b"abc" * 1000
    (tmp_path / "f.bin.part").write_bytes(b"ordures")
    tel.telecharger("https://github.com/a/b", tmp_path / "f.bin", hashlib.sha256(contenu).hexdigest(),
                    opener=_opener(contenu, honore_range=False))
    assert (tmp_path / "f.bin").read_bytes() == contenu


def test_mauvaise_empreinte_supprime_le_partiel(tmp_path):
    with pytest.raises(tel.TelechargementErreur) as erreur:
        tel.telecharger("https://github.com/a/b", tmp_path / "f.bin", "0" * 64, opener=_opener(b"contenu"))
    assert erreur.value.code == "empreinte"
    assert not (tmp_path / "f.bin").exists() and not (tmp_path / "f.bin.part").exists()


def test_fichier_deja_present_pas_retelecharge(tmp_path):
    contenu = b"deja la"
    (tmp_path / "f.bin").write_bytes(contenu)

    def interdit(*args, **kwargs):
        raise AssertionError("aucune requête attendue")

    tel.telecharger("https://github.com/a/b", tmp_path / "f.bin", hashlib.sha256(contenu).hexdigest(), opener=interdit)


def test_telechargement_annule_et_url_refusee(tmp_path):
    with pytest.raises(tel.TelechargementErreur) as erreur:
        tel.telecharger("https://github.com/a/b", tmp_path / "f.bin", "0" * 64, annule=lambda: True,
                        opener=_opener(b"x" * 10))
    assert erreur.value.code == "annule"
    with pytest.raises(tel.TelechargementErreur):
        tel.telecharger("http://github.com/a/b", tmp_path / "g.bin", "0" * 64, opener=_opener(b""))


# --- 7-Zip ------------------------------------------------------------------------


def test_lignes_7zip():
    assert septzip.analyser_ligne(" 42% - lite.pac") == 42
    assert septzip.analyser_ligne("ERROR: Data Error in encrypted file. Wrong password? : lite.pac") == "mot_de_passe"
    assert septzip.analyser_ligne("Can't open as archive: 1") == "mot_de_passe"
    assert septzip.analyser_ligne("ERROR: disque plein") == "erreur"
    assert septzip.analyser_ligne("Everything is Ok") is None


def test_mot_de_passe_jamais_dans_la_commande():
    for argv in (septzip.commande_test(Path("7z.exe"), Path("a.7z.001")),
                 septzip.commande_extraction(Path("7z.exe"), Path("a.7z.001"), Path("sortie"))):
        assert not any(a.startswith("-p") for a in argv)


class _Processus:
    def __init__(self, sortie: bytes, code=0):
        self.stdin = MagicMock()
        self.stdout = io.BytesIO(sortie)
        self._code = code
        self.tue = False

    def poll(self):
        return None if not self.tue and self._code is None else self._code

    def wait(self):
        return self._code

    def kill(self):
        self.tue = True


def test_extraction_mot_de_passe_sur_l_entree_standard(monkeypatch, tmp_path):
    processus = _Processus(b"  0%\r 50% - a\r100%\r\nEverything is Ok\r\n")
    monkeypatch.setattr(septzip.subprocess, "Popen", lambda argv, **kw: processus)
    vus = []
    septzip.extraire(Path("7z.exe"), Path("a.7z.001"), tmp_path / "o", "s3cret", vus.append)
    processus.stdin.write.assert_called_once_with(b"s3cret\n")
    assert vus == [0, 50, 100]


def test_mauvais_mot_de_passe_detecte(monkeypatch):
    processus = _Processus(b"ERROR: Data Error in encrypted file. Wrong password? : x.pac\r\n", code=2)
    monkeypatch.setattr(septzip.subprocess, "Popen", lambda argv, **kw: processus)
    journal = []
    with pytest.raises(septzip.SeptZipErreur) as erreur:
        septzip.verifier_mot_de_passe(Path("7z.exe"), Path("a.7z.001"), "faux", journal=journal.append)
    assert erreur.value.code == "mot_de_passe"
    assert not any("faux" in ligne for ligne in journal)


def test_verification_s_arrete_au_premier_pourcent(monkeypatch):
    processus = _Processus(b"  0%\r  1% - x.pac\r", code=None)
    monkeypatch.setattr(septzip.subprocess, "Popen", lambda argv, **kw: processus)
    septzip.verifier_mot_de_passe(Path("7z.exe"), Path("a.7z.001"), "bon")
    assert processus.tue


# --- CmdDloader --------------------------------------------------------------------

# Sortie reconstituée à partir des formats `printf` relevés dans
# CmdDloader.exe (27.24.2301) -- aucune vraie capture sur console encore.
SORTIE_CMDDLOADER = """Start loading packet...
Loading packet progress is  10%
Loading packet progress is 100%
End loading packet
PACKET: RG_ROTATE_GAMMAOS_NEXT_LITE; Version: 1.4.1; Packet Size: 6365.29MB; LoadTime = 2026/10/27 02:30
Please connect the DUT in  58s
PORT = COM5
Start Downloading...
No.001 FDL                        Progress:  50%; Size: 0.057M; Time:12ms
[Status] 37%
[Status] 100%
Download Result = Passed;
Elapsed Time = 512.40s
"""


def test_commande_cmddloader():
    assert cmddloader.commande(Path("C:/o/CmdDloader.exe"), Path("C:/f/x.pac"), 900000) == [
        str(Path("C:/o/CmdDloader.exe")), "-pac", str(Path("C:/f/x.pac")), "-Version", "2", "-Port", "0",
        "-Timeout", "900000", "-Reset",
    ]


def test_sortie_cmddloader_analysee():
    evenements = [e for e in map(cmddloader.analyser_ligne, SORTIE_CMDDLOADER.splitlines()) if e]
    assert [(e.type, e.valeur) for e in evenements] == [
        ("chargement", 10), ("chargement", 100), ("paquet", ("RG_ROTATE_GAMMAOS_NEXT_LITE", "1.4.1")),
        ("attente", 58), ("port", 5), ("fichier", 50), ("progression", 37), ("progression", 100),
        ("resultat", True),
    ]


def test_echec_et_delai_cmddloader():
    echec = cmddloader.analyser_ligne("Download Result = Failed; Error Messag = Write flash fail")
    assert (echec.type, echec.valeur, echec.texte) == ("resultat", False, "Write flash fail")
    assert cmddloader.analyser_ligne("Connect DUT timeout( 60s )").type == "delai"


# --- USB ----------------------------------------------------------------------------


def test_appareils_usb():
    un = usb.analyser('{"PNPDeviceID":"USB\\\\VID_1782&PID_4D00\\\\5&2B1D7621&0&1","Name":"SPRD U2S Diag (COM5)"}')
    assert un == [usb.Appareil("USB\\VID_1782&PID_4D00\\5&2B1D7621&0&1", "SPRD U2S Diag (COM5)")]
    assert un[0].vid_pid == "1782:4d00"
    assert usb.analyser("") == [] and usb.analyser("pas du json") == [] and usb.analyser("42") == []
    plusieurs = usb.analyser(json.dumps([
        {"PNPDeviceID": "USB\\VID_046D&PID_C52F\\1", "Name": "Souris"},
        {"PNPDeviceID": "USB\\VID_18D1&PID_4EE7\\2", "Name": "Android Composite ADB Interface"},
        {"Name": "sans identifiant"},
    ]))
    assert len(plusieurs) == 2


def test_classement_usb():
    download = usb.Appareil("USB\\VID_1782&PID_4D00\\1", "Périphérique série")
    nommé = usb.Appareil("USB\\VID_9999&PID_0001\\1", "SPRD U2S Diag (COM4)")
    android = usb.Appareil("USB\\VID_18D1&PID_4EE7\\2", "Android Composite ADB Interface")
    souris = usb.Appareil("USB\\VID_046D&PID_C52F\\1", "Souris")
    assert usb.classer(download, ["1782:4d00"]) == "download"
    assert usb.classer(nommé, []) == "download"
    assert usb.classer(android, ["1782:4d00"]) == "android"
    assert usb.classer(souris, ["1782:4d00"]) is None
    assert usb.nouveaux([souris], [souris, android]) == [android]
    assert usb.etat([souris, download, android], ["1782:4d00"]) == {"download": [download], "android": [android]}


# --- pilotes et outils ----------------------------------------------------------------


def _zip_outils(chemin: Path, avec_inf=True) -> Path:
    with zipfile.ZipFile(chemin, "w") as z:
        base = "UnisocTools_RG_VITA/"
        z.writestr(base + "SPRD_Download_Tool/CmdDloader.exe", b"MZ")
        z.writestr(base + "SPRD_Download_Tool/UpgradeDownload.exe", b"MZ")
        z.writestr(base + "SPRD_Download_Tool/System/Tools/7zip/32/7z.exe", b"MZ")
        if avec_inf:
            z.writestr(base + "UnisocDrivers/Win10/Drivers/sprdvcom.inf", b"[Version]")
        z.writestr(base + "UnisocDrivers/Win10/Drivers/amd64/sprdvcom.sys", b"sys")
        z.writestr(base + "UnisocDrivers/Win7/Drivers/sprdvcom.inf", b"ancien")
    return chemin


def test_pilotes_detectes_quelle_que_soit_la_langue():
    assert pilotes.sont_installes_dans("Nom d’origine :      sprdvcom.inf\n")
    assert pilotes.sont_installes_dans("Original Name:      SPRDVCOM.INF")
    assert not pilotes.sont_installes_dans("Original Name: autre.inf")


def test_membres_pilotes_win10_avec_sous_dossiers():
    noms = [
        "U/UnisocDrivers/Win10/Drivers/sprdvcom.inf",
        "U/UnisocDrivers/Win10/Drivers/amd64/sprdvcom.sys",
        "U/UnisocDrivers/Win10/Drivers/",
        "U/UnisocDrivers/Win7/Drivers/sprdvcom.inf",
        "U/UnisocDrivers/Win10/Drivers/../../evil.exe",
    ]
    assert [(m, str(r)) for m, r in pilotes.membres_pilotes(noms)] == [
        ("U/UnisocDrivers/Win10/Drivers/sprdvcom.inf", "sprdvcom.inf"),
        ("U/UnisocDrivers/Win10/Drivers/amd64/sprdvcom.sys", "amd64/sprdvcom.sys"),
    ]


def test_installation_pilotes_par_pnputil(monkeypatch, tmp_path):
    zip_path = _zip_outils(tmp_path / "outils.zip")
    sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    appels = []

    def run(argv, **kwargs):
        appels.append(argv)
        dossier = Path(argv[2]).parent if argv[1] == "/add-driver" else None
        if dossier is not None:
            assert (dossier / "sprdvcom.inf").is_file() and (dossier / "amd64" / "sprdvcom.sys").is_file()
            return MagicMock(returncode=3010, stdout="ok")
        return MagicMock(returncode=0, stdout="Original Name: sprdvcom.inf")

    monkeypatch.setattr(pilotes.subprocess, "run", run)
    resultat = pilotes.installer(zip_path, sha)
    assert resultat.redemarrage and resultat.installes
    assert appels[0][:2] == ["pnputil", "/add-driver"] and appels[0][-1] == "/install"
    assert not Path(appels[0][2]).parent.exists()  # dossier temporaire supprimé


def test_pilotes_refuses_si_zip_modifie(tmp_path):
    zip_path = _zip_outils(tmp_path / "outils.zip")
    with pytest.raises(pilotes.PilotesErreur) as erreur:
        pilotes.installer(zip_path, "0" * 64)
    assert erreur.value.code == "empreinte"


def test_pilotes_inf_absent(tmp_path):
    zip_path = _zip_outils(tmp_path / "outils.zip", avec_inf=False)
    with pytest.raises(pilotes.PilotesErreur) as erreur:
        pilotes.installer(zip_path, hashlib.sha256(zip_path.read_bytes()).hexdigest())
    assert erreur.value.code == "zip"


def test_echec_pnputil(monkeypatch, tmp_path):
    zip_path = _zip_outils(tmp_path / "outils.zip")
    monkeypatch.setattr(pilotes.subprocess, "run", lambda argv, **kw: MagicMock(returncode=5, stdout="refus"))
    with pytest.raises(pilotes.PilotesErreur) as erreur:
        pilotes.installer(zip_path, hashlib.sha256(zip_path.read_bytes()).hexdigest())
    assert erreur.value.code == "pnputil"


def test_outils_trouves_par_leur_nom(tmp_path):
    zip_path = _zip_outils(tmp_path / "outils.zip")
    trouves = outils.preparer(zip_path, tmp_path / "outils")
    assert trouves.cmddloader.name == "CmdDloader.exe"
    assert trouves.septzip.parts[-4:] == ("Tools", "7zip", "32", "7z.exe")
    assert trouves.upgradedownload is not None
    zip_path.unlink()  # deuxième appel : pas de nouvelle extraction
    assert outils.preparer(zip_path, tmp_path / "outils").cmddloader == trouves.cmddloader


def test_zip_slip_refuse(tmp_path):
    with zipfile.ZipFile(tmp_path / "mal.zip", "w") as z:
        z.writestr("../dehors.txt", b"x")
    with pytest.raises(outils.OutilsIntrouvables):
        outils.extraire_zip(tmp_path / "mal.zip", tmp_path / "dest")
    assert not (tmp_path / "dehors.txt").exists()


# --- commande du worker élevé ------------------------------------------------------------


@pytest.fixture(autouse=True)
def _protocole_remis_a_zero():
    """`--progress-file` redirige le protocole vers un fichier refermé
    ensuite : sans remise à zéro, les tests suivants y écriraient."""
    yield
    from r36s_studio import protocol

    protocol.configure(None)


def _evenements(chemin: Path):
    return [json.loads(ligne) for ligne in chemin.read_text(encoding="utf-8").splitlines()]


def test_worker_pilotes_hors_windows(monkeypatch, tmp_path):
    from r36s_studio import __main__ as cli

    monkeypatch.setattr(cli.platform, "system", lambda: "Linux")
    progression = tmp_path / "p.jsonl"
    code = cli.main(["install-unisoc-drivers", "--zip", "x.zip", "--sha256", "0" * 64, "--worker",
                     "--progress-file", str(progression)])
    assert code == 1
    assert _evenements(progression)[0]["code"] == "UNSUPPORTED_OS"


def test_worker_pilotes_resultat(monkeypatch, tmp_path):
    from r36s_studio import __main__ as cli

    monkeypatch.setattr(cli.platform, "system", lambda: "Windows")
    monkeypatch.setattr(pilotes, "installer", lambda zip_path, sha: pilotes.ResultatPilotes(0, False, True))
    progression = tmp_path / "p.jsonl"
    assert cli.main(["install-unisoc-drivers", "--zip", "x.zip", "--sha256", "a" * 64, "--worker",
                     "--progress-file", str(progression)]) == 0
    resultat = [e for e in _evenements(progression) if e["type"] == "drivers_result"]
    assert resultat == [{"type": "drivers_result", "result": {"code_retour": 0, "redemarrage": False, "installes": True}}]


def test_worker_pilotes_empreinte(monkeypatch, tmp_path):
    from r36s_studio import __main__ as cli

    monkeypatch.setattr(cli.platform, "system", lambda: "Windows")

    def refuse(zip_path, sha):
        raise pilotes.PilotesErreur("empreinte", "x.zip")

    monkeypatch.setattr(pilotes, "installer", refuse)
    progression = tmp_path / "p.jsonl"
    assert cli.main(["install-unisoc-drivers", "--zip", "x.zip", "--sha256", "a" * 64, "--worker",
                     "--progress-file", str(progression)]) == 1
    assert _evenements(progression)[0]["code"] == "DRIVERS_CHECKSUM"
