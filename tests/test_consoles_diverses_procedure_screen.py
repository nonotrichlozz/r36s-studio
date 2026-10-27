"""Écrans des installations guidées par USB : section « Installations
guidées » de la fiche (catalogue seulement, jamais une fiche IA) et
`ProcedureScreen` (procédure désactivée hors Windows, confirmation
d'effacement jamais pré-cochée, mot de passe jamais gardé, refus d'un .pac
qui ne correspond pas, consignes de branchement venues de la fiche). Aucun
thread lancé : les méthodes de fin de runner sont appelées directement."""

from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton

from r36s_studio.consoles_diverses import procedure_screen as ps
from r36s_studio.consoles_diverses import screen as fiche_screen
from r36s_studio.consoles_diverses.client import ResultatRecherche
from r36s_studio.consoles_diverses.models import fiche_depuis_json
from r36s_studio.consoles_diverses.procedures import cmddloader, pac
from r36s_studio.consoles_diverses.procedures.fiche import procedures_depuis_json
from r36s_studio.consoles_diverses.strings import tr

FIXTURE = Path(__file__).parent / "fixtures_fiche_anbernic_rg_rotate.json"


def _json():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _installation():
    return procedures_depuis_json(_json()["procedures"])[0]


def _boutons(widget, texte):
    return [b for b in widget.findChildren(QPushButton) if b.text() == texte]


def _textes(widget):
    return [label.text() for label in widget.findChildren(QLabel)]


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(ps, "systeme_courant", lambda: "windows")
    monkeypatch.setattr(fiche_screen, "systeme_courant", lambda: "windows")


# --- fiche ----------------------------------------------------------------------


def test_section_procedures_pour_une_fiche_du_catalogue(qapp, windows):
    ecran = fiche_screen.ConsolesDiversesScreen()
    recus = []
    ecran.procedure_requested.connect(lambda fid, proc, verifiee: recus.append((fid, proc.id, verifiee)))
    ecran._on_search_finished(ResultatRecherche(statut="trouve_dans_catalogue", console=fiche_depuis_json(_json())))
    boutons = _boutons(ecran, tr("procedure_button"))
    # Installation et retour au firmware d'origine ; restauration Super désactivée.
    assert len(boutons) == 2
    assert tr("procedure_desactivee_etape") in _textes(ecran)
    boutons[0].click()
    assert recus == [("anbernic-rg-rotate", "gammaos-next-1-4-1-installation", False)]


def test_jamais_de_procedure_pour_une_fiche_ia(qapp, windows):
    ecran = fiche_screen.ConsolesDiversesScreen()
    ecran._on_search_finished(ResultatRecherche(statut="trouve_par_ia", console=fiche_depuis_json(_json())))
    assert _boutons(ecran, tr("procedure_button")) == []


def test_procedures_desactivees_hors_windows(qapp, monkeypatch):
    monkeypatch.setattr(fiche_screen, "systeme_courant", lambda: "macos")
    ecran = fiche_screen.ConsolesDiversesScreen()
    ecran._on_search_finished(ResultatRecherche(statut="trouve_dans_catalogue", console=fiche_depuis_json(_json())))
    assert _boutons(ecran, tr("procedure_button")) == []
    assert tr("procedure_desactivee_systeme", systemes="Windows") in _textes(ecran)


# --- écran de procédure -------------------------------------------------------------


def _ecran(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "default_firmware_downloads_dir", lambda: tmp_path)
    ecran = ps.ProcedureScreen()
    ecran.start("anbernic-rg-rotate", _installation(), verifiee=False)
    return ecran


def test_hors_windows_non_disponible(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "systeme_courant", lambda: "linux")
    ecran = _ecran(qapp, tmp_path, monkeypatch)
    assert tr("procedure_desactivee_systeme", systemes="Windows") in _textes(ecran)
    assert _boutons(ecran._page_choix.parentWidget(), tr("proc_continue")) == []


def test_credit_auteur_et_variante_recommandee(qapp, tmp_path, monkeypatch, windows):
    ecran = _ecran(qapp, tmp_path, monkeypatch)
    assert tr("proc_credit", firmware="GammaOS Next", auteur="TheGammaSqueeze") in _textes(ecran)
    assert ecran._groupe_variantes.checkedButton().property("variante") == "lite"


def test_effacement_a_confirmer_case_jamais_cochee(qapp, tmp_path, monkeypatch, windows):
    ecran = _ecran(qapp, tmp_path, monkeypatch)
    (continuer,) = _boutons(ecran._page_choix.parentWidget(), tr("proc_continue"))
    (case,) = [c for c in ecran.findChildren(QCheckBox) if c.text() == tr("proc_erase_checkbox")]
    assert not case.isChecked() and not continuer.isEnabled()
    case.setChecked(True)
    assert continuer.isEnabled()


def test_prerequis_espace_insuffisant(qapp, tmp_path, monkeypatch, windows):
    ecran = _ecran(qapp, tmp_path, monkeypatch)
    monkeypatch.setattr(ps, "espace_libre", lambda dossier: 1024**3)
    ecran._prerequis_resultat(True)
    page = ecran._page_prerequis.parentWidget()
    assert _boutons(page, tr("proc_continue")) == []
    assert any(t.startswith("✗") for t in _textes(page))


def test_mot_de_passe_vide_le_champ_et_n_est_pas_journalise(qapp, tmp_path, monkeypatch, windows):
    ecran = _ecran(qapp, tmp_path, monkeypatch)
    recus = []
    monkeypatch.setattr(ecran, "_extraire", lambda mot_de_passe, archive=None: recus.append(mot_de_passe))
    ecran._demander_mot_de_passe()
    ecran._mdp_champ.setText("s3cret-du-discord")
    ecran._valider_mot_de_passe()
    assert recus == ["s3cret-du-discord"]
    assert ecran._mdp_champ.text() == ""
    assert "s3cret" not in ecran._journal.toPlainText()


def test_mauvais_mot_de_passe_redemande(qapp, tmp_path, monkeypatch, windows):
    ecran = _ecran(qapp, tmp_path, monkeypatch)
    ecran._extraction_echec("mot_de_passe", "")
    assert ecran._mdp_erreur.text() == tr("proc_password_wrong")


def _faux_pac(chemin: Path, nom: str) -> Path:
    donnees = bytearray(pac.TAILLE_EN_TETE)
    for debut, texte in ((0, "BP_R2.0.1"), (52, "ums512_1h10"), (564, "1.4.1"), (1104, nom)):
        brut = texte.encode("utf-16-le")
        donnees[debut : debut + len(brut)] = brut
    struct.pack_into("<I", donnees, 1076, 1)
    chemin.write_bytes(bytes(donnees))
    return chemin


def test_pac_d_une_autre_variante_refuse(qapp, tmp_path, monkeypatch, windows):
    ecran = _ecran(qapp, tmp_path, monkeypatch)
    ecran._variante = "lite"
    ecran._phases = ["consignes", "flash"]
    ecran._pac = _faux_pac(tmp_path / "x.pac", "RG_ROTATE_GAMMAOS_NEXT_FULL")
    ecran._phase_verification()
    assert ecran._pac is None and not ecran._pac_verifie
    assert ecran._travail_statut.text() == tr("proc_pac_wrong", nom="RG_ROTATE_GAMMAOS_NEXT_FULL", version="1.4.1")
    assert ecran._phases == ["consignes", "flash"]  # rien n'avance


def test_bon_pac_passe_aux_consignes(qapp, tmp_path, monkeypatch, windows):
    ecran = _ecran(qapp, tmp_path, monkeypatch)
    ecran._variante = "lite"
    ecran._phases = ["consignes", "flash"]
    ecran._pac = _faux_pac(tmp_path / "x.pac", "RG_ROTATE_GAMMAOS_NEXT_LITE")
    ecran._phase_verification()
    assert ecran._pac_verifie
    textes = _textes(ecran._page_consignes.parentWidget())
    assert any("Retirer TOUTES les cartes SD" in t for t in textes)
    (case,) = [c for c in ecran._page_consignes.parentWidget().findChildren(QCheckBox)]
    assert not case.isChecked()  # seconde confirmation avant d'écrire


def test_flash_consigne_de_branchement_et_plus_d_annulation(qapp, tmp_path, monkeypatch, windows):
    ecran = _ecran(qapp, tmp_path, monkeypatch)
    ecran._travail("x")
    ecran._evenement_flash(cmddloader.Evenement("attente", 58))
    assert "MAINTENIR le bouton Retour" in ecran._travail_consigne.text()
    ecran._evenement_usb("android", "18d1:4ee7", "Android ADB")
    assert ecran._travail_consigne.text() == tr("proc_flash_android")
    ecran._evenement_flash(cmddloader.Evenement("port", 5))
    assert ecran._travail_titre.text() == tr("proc_flash_running_title")
    assert ecran._travail_annuler.isHidden()


def test_console_jamais_detectee(qapp, tmp_path, monkeypatch, windows):
    ecran = _ecran(qapp, tmp_path, monkeypatch)
    ecran._flash_termine(False, "code de retour 1")
    assert ecran._travail_statut.text() == tr("proc_flash_timeout")


def test_mauvais_bouton_au_branchement(qapp, tmp_path, monkeypatch, windows):
    ecran = _ecran(qapp, tmp_path, monkeypatch)
    ecran._travail("x")
    ecran._evenement_flash(cmddloader.Evenement("bouton"))
    assert "Maintiens le bouton Retour, au centre de la manette" in ecran._travail_consigne.text()
    flash = type("F", (), {"_flash_commence": True, "annule": False, "bouton": True})()
    ecran._flash = flash
    ecran._flash_termine(False, "User cancel")
    assert ecran._travail_statut.text() == tr("proc_flash_bouton_retour")


def test_fin_propose_la_console_android(qapp, tmp_path, monkeypatch, windows):
    ecran = _ecran(qapp, tmp_path, monkeypatch)
    recus = []
    ecran.android_requested.connect(lambda: recus.append(True))
    ecran._afficher_fin()
    assert any("écran noir possible" in t for t in _textes(ecran._page_fin.parentWidget()))
    _boutons(ecran, tr("proc_done_android"))[0].click()
    assert recus == [True]
