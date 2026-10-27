# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Écran d'une installation guidée par USB (champ `procedures` d'une fiche,
moteur générique `procedures/`). Parcourt les phases de la procédure
(`Procedure.phases()`) : vérifications, téléchargement, pilotes, archive,
contrôle du .pac, consignes, flash, premier démarrage.

Rien de propre à une console ici : textes des gestes, du premier démarrage
et du dépannage viennent de la fiche (texte brut, jamais interprété).

Le **mot de passe** d'archive vit dans le champ de saisie puis dans
`ExtractionRunner`, le temps de l'extraction ; le champ est vidé dès qu'il
est lu. Jamais écrit dans un journal, la configuration ou un rapport."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from r36s_studio.gui import logs as gui_logs
from r36s_studio.gui.screens import Screen, _format_size
from r36s_studio.identify.rocknix import default_firmware_downloads_dir

from .procedure_runner import (
    AppelRunner,
    ExtractionRunner,
    FlashRunner,
    PilotesRunner,
    TelechargementsRunner,
    espace_libre,
    verifier_pac,
)
from .procedures import cmddloader, pilotes
from .procedures.fiche import (
    NOMS_SYSTEMES,
    Procedure,
    auteur_depuis_url,
    est_telechargeable,
    fichiers_a_telecharger,
    motif_desactivation,
    premiere_url,
    systeme_courant,
    version_a_verifier,
)
from .screen import _build_warning_banner, _link_widget, _plain_label
from .strings import tr

# 2,7 Go d'archives + 6,7 Go de .pac + marge (procédure RG Rotate) : seuil
# commun à toutes les procédures USB tant que la fiche ne donne pas de tailles.
ESPACE_REQUIS = 12 * 1024**3
def _journaliser_fichier(texte: str) -> None:
    try:
        with open(gui_logs.consoles_diverses_log_path(), "a", encoding="utf-8") as fichier:
            fichier.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {texte}\n")
    except OSError:
        pass


class ProcedureScreen(Screen):
    back_requested = Signal()
    android_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._procedure: Optional[Procedure] = None
        self._fiche_id = ""
        self._variante: Optional[str] = None
        self._dossier = Path()
        self._outils = None
        self._pac: Optional[Path] = None
        self._pac_verifie = False
        self._pilotes_ok = False
        self._phases: List[str] = []
        self._runner = None
        self._flash: Optional[FlashRunner] = None
        self._reprise: Optional[Callable[[], None]] = None
        self._installateur_pilotes: Optional[Callable] = None

        racine = QVBoxLayout(self)
        haut = QHBoxLayout()
        self._back = QPushButton(tr("proc_back"))
        self._back.setProperty("role", "flat")
        self._back.clicked.connect(self.back_requested.emit)
        haut.addWidget(self._back)
        haut.addStretch()
        self._titre = _plain_label("", role="title")
        haut.addWidget(self._titre)
        haut.addStretch()
        aide = QPushButton(tr("proc_help_button"))
        aide.setProperty("role", "flat")
        aide.clicked.connect(self._afficher_depannage)
        haut.addWidget(aide)
        racine.addLayout(haut)

        self._pages = QStackedWidget()
        racine.addWidget(self._pages, 1)
        self._journal = QPlainTextEdit()
        self._journal.setReadOnly(True)
        self._journal.setProperty("role", "log")
        self._journal.setMaximumHeight(120)
        racine.addWidget(self._journal)

        self._page_choix = self._page()
        self._page_prerequis = self._page()
        self._page_travail = self._page()
        self._page_mot_de_passe = self._page()
        self._page_choisir = self._page()
        self._page_consignes = self._page()
        self._page_fin = self._page()
        self._construire_travail()
        self._construire_mot_de_passe()

    # --- outillage ---------------------------------------------------------

    def _page(self) -> QVBoxLayout:
        defile = QScrollArea()
        defile.setWidgetResizable(True)
        contenu = QWidget()
        disposition = QVBoxLayout(contenu)
        defile.setWidget(contenu)
        self._pages.addWidget(defile)
        disposition.setProperty("defile", defile)
        return disposition

    def _montrer(self, disposition: QVBoxLayout) -> None:
        self._pages.setCurrentWidget(disposition.property("defile"))

    @staticmethod
    def _vider(disposition: QVBoxLayout) -> None:
        while disposition.count():
            element = disposition.takeAt(0)
            if element.widget() is not None:
                element.widget().deleteLater()
            elif element.layout() is not None:
                ProcedureScreen._vider(element.layout())

    def _log(self, texte: str) -> None:
        self._journal.appendPlainText(texte)
        _journaliser_fichier(f"[procédure {self._procedure.id if self._procedure else '?'}] {texte}")

    def set_installateur_pilotes(self, installateur: Callable) -> None:
        """`installateur(zip, sha256) -> (installés, redémarrage, code)`,
        fourni par `MainWindow` (worker élevé) : ce paquet n'appelle jamais
        lui-même l'élévation."""
        self._installateur_pilotes = installateur

    # --- démarrage ---------------------------------------------------------

    def start(self, fiche_id: str, procedure: Procedure, verifiee: bool) -> None:
        self._procedure = procedure
        self._fiche_id = fiche_id
        self._dossier = default_firmware_downloads_dir() / fiche_id
        self._outils = None
        self._pac = None
        self._pac_verifie = False
        self._journal.clear()
        self._titre.setText(procedure.titre)
        self._log(f"Ouverture : {procedure.titre} ({procedure.id})")
        self._construire_choix(verifiee)
        self._montrer(self._page_choix)

    def _construire_choix(self, verifiee: bool) -> None:
        proc = self._procedure
        page = self._page_choix
        self._vider(page)
        if not verifiee:
            page.addWidget(_build_warning_banner(tr("procedure_experimental")))
        auteur = auteur_depuis_url(proc.source_url)
        if auteur:
            page.addWidget(_plain_label(tr("proc_credit", firmware=proc.firmware, auteur=auteur), wrap=True))
        page.addWidget(_link_widget(proc.source_url, tr("proc_credit_page")), alignment=Qt.AlignLeft)

        motif = motif_desactivation(proc, systeme_courant())
        if motif is not None:
            systemes = ", ".join(NOMS_SYSTEMES.get(p, p) for p in proc.plateformes)
            page.addWidget(_plain_label(tr(f"procedure_desactivee_{motif}", systemes=systemes), wrap=True))
            page.addStretch()
            return

        self._groupe_variantes = QButtonGroup(self)
        if proc.variantes:
            page.addWidget(_plain_label(tr("proc_variant_title"), role="rowTitle"))
            ordre = sorted(proc.variantes, key=lambda v: not v.recommande)
            for variante in ordre:
                nom = tr("proc_variant_recommended", nom=variante.nom) if variante.recommande else variante.nom
                bouton = QRadioButton(nom)
                bouton.setProperty("variante", variante.id)
                bouton.setChecked(variante is ordre[0])
                self._groupe_variantes.addButton(bouton)
                page.addWidget(bouton)
                page.addWidget(_plain_label(variante.description, role="rowDesc", wrap=True))

        continuer = QPushButton(tr("proc_continue"))
        continuer.setProperty("role", "primary")
        if proc.efface_donnees:
            page.addWidget(_build_restriction_banner_texte(tr("proc_erase_warning")))
            case = QCheckBox(tr("proc_erase_checkbox"))
            case.setChecked(False)  # jamais pré-cochée (CLAUDE.md §5)
            case.toggled.connect(continuer.setEnabled)
            page.addWidget(case)
            continuer.setEnabled(False)
        continuer.clicked.connect(self._lancer_prerequis)
        page.addWidget(continuer, alignment=Qt.AlignLeft)
        page.addStretch()

    # --- vérifications -------------------------------------------------------

    def _lancer_prerequis(self) -> None:
        bouton = self._groupe_variantes.checkedButton()
        self._variante = bouton.property("variante") if bouton is not None else None
        self._log(f"Version choisie : {self._variante or '-'}")
        page = self._page_prerequis
        self._vider(page)
        page.addWidget(_plain_label(tr("proc_prereq_title"), role="title"))
        page.addWidget(_plain_label(tr("proc_prereq_checking"), role="secondary"))
        self._montrer(page)
        self._back.setEnabled(False)
        self._runner = AppelRunner(pilotes.sont_installes, self)
        self._runner.termine.connect(self._prerequis_resultat)
        self._runner.start()

    def _prerequis_resultat(self, pilotes_installes) -> None:
        self._back.setEnabled(True)
        self._pilotes_ok = pilotes_installes is True
        libre = espace_libre(self._dossier)
        espace_ok = libre >= ESPACE_REQUIS or self._deja_extrait()
        page = self._page_prerequis
        self._vider(page)
        page.addWidget(_plain_label(tr("proc_prereq_title"), role="title"))
        lignes = [
            (True, tr("proc_prereq_os_ok")),
            (espace_ok, tr("proc_prereq_space_ok", libre=_format_size(libre)) if espace_ok
             else tr("proc_prereq_space_ko", requis=_format_size(ESPACE_REQUIS), libre=_format_size(libre))),
            (True, tr("proc_prereq_drivers_ok") if self._pilotes_ok else tr("proc_prereq_drivers_todo")),
            (True, tr("proc_prereq_tools")),
        ]
        for ok, texte in lignes:
            page.addWidget(_plain_label(f"{'✓' if ok else '✗'} {texte}", wrap=True))
            self._log(f"{'OK' if ok else 'NON'} : {texte}")
        if espace_ok:
            continuer = QPushButton(tr("proc_continue"))
            continuer.setProperty("role", "primary")
            continuer.clicked.connect(self._demarrer_phases)
            page.addWidget(continuer, alignment=Qt.AlignLeft)
        page.addStretch()

    def _deja_extrait(self) -> bool:
        variante = self._procedure.variante(self._variante)
        final = variante.fichier_final if variante else None
        return bool(final) and (self._dossier / final).is_file()

    # --- enchaînement des phases ---------------------------------------------

    def _demarrer_phases(self) -> None:
        self._phases = [p for p in self._procedure.phases() if p != "prerequis"]
        self._phase_suivante()

    def _phase_suivante(self) -> None:
        if not self._phases:
            self._afficher_fin()
            return
        phase = self._phases.pop(0)
        self._log(f"Étape : {phase}")
        {
            "telechargement": self._phase_telechargement,
            "pilotes": self._phase_pilotes,
            "extraction": self._obtenir_pac,
            "verification_pac": self._phase_verification,
            "consignes": self._phase_consignes,
            "flash": self._phase_flash,
            "premier_demarrage": self._afficher_fin,
        }[phase]()

    def _construire_travail(self) -> None:
        page = self._page_travail
        self._travail_titre = _plain_label("", role="title")
        self._travail_statut = _plain_label("", wrap=True)
        self._travail_barre = QProgressBar()
        self._travail_consigne = _plain_label("", wrap=True)
        self._travail_annuler = QPushButton(tr("proc_cancel"))
        self._travail_annuler.clicked.connect(self._annuler_travail)
        self._travail_secours = QPushButton(tr("proc_fallback_button"))
        self._travail_secours.clicked.connect(self._ouvrir_outil_graphique)
        self._travail_reessayer = QPushButton(tr("proc_retry"))
        self._travail_reessayer.setProperty("role", "primary")
        self._travail_reessayer.clicked.connect(self._reessayer)
        for widget in (self._travail_titre, self._travail_statut, self._travail_barre, self._travail_consigne):
            page.addWidget(widget)
        boutons = QHBoxLayout()
        for widget in (self._travail_reessayer, self._travail_annuler, self._travail_secours):
            boutons.addWidget(widget)
        boutons.addStretch()
        page.addLayout(boutons)
        page.addStretch()

    def _travail(self, titre: str, statut: str = "", annulable: bool = True) -> None:
        self._travail_titre.setText(titre)
        self._travail_statut.setText(statut)
        self._travail_consigne.setText("")
        self._travail_barre.setRange(0, 0)
        self._travail_annuler.setVisible(annulable)
        self._travail_annuler.setEnabled(True)
        self._travail_secours.setVisible(False)
        self._travail_reessayer.setVisible(False)
        self._back.setEnabled(False)
        self._montrer(self._page_travail)

    def _erreur(self, message: str, reprise: Optional[Callable[[], None]] = None) -> None:
        self._log(f"Problème : {message}")
        self._travail_titre.setText(tr("proc_error_title"))
        self._travail_statut.setText(message)
        self._travail_barre.setRange(0, 1)
        self._travail_barre.setValue(0)
        self._travail_annuler.setVisible(False)
        self._reprise = reprise
        self._travail_reessayer.setVisible(reprise is not None)
        self._back.setEnabled(True)
        self._montrer(self._page_travail)

    def _reessayer(self) -> None:
        if self._reprise is not None:
            reprise, self._reprise = self._reprise, None
            reprise()

    def _annuler_travail(self) -> None:
        if self._flash is not None:
            if not self._flash.annuler():
                self._travail_consigne.setText(tr("proc_flash_cancel_refused"))
                self._travail_annuler.setEnabled(False)
            return
        if self._runner is not None and hasattr(self._runner, "annuler"):
            self._runner.annuler()

    # --- téléchargement -----------------------------------------------------

    def _phase_telechargement(self) -> None:
        fichiers = fichiers_a_telecharger(self._procedure, self._variante)
        if self._deja_extrait():  # les archives ne servent plus : seulement les outils
            fichiers = [f for f in fichiers if f.variante is None]
        self._travail(tr("proc_download_title"))
        runner = TelechargementsRunner(fichiers, self._dossier, self)
        runner.progression.connect(self._progression_telechargement)
        runner.journal.connect(self._log)
        runner.echec.connect(lambda code, detail: self._erreur(
            tr(f"proc_error_{code}", detail=detail) if code in ("reseau", "empreinte", "outils", "disque", "url")
            else tr("proc_error_reseau"),
            None if code == "annule" else self._phase_telechargement,
        ))
        runner.termine.connect(self._telechargement_termine)
        self._runner = runner
        runner.start()

    def _progression_telechargement(self, nom: str, fait: int, total: int) -> None:
        if total:
            self._travail_barre.setRange(0, 1000)
            self._travail_barre.setValue(int(fait * 1000 / total))
            self._travail_statut.setText(tr("proc_download_status", nom=nom, fait=_format_size(fait), total=_format_size(total)))
        else:
            self._travail_statut.setText(tr("proc_download_status_unknown", nom=nom, fait=_format_size(fait)))

    def _telechargement_termine(self, outils_unisoc) -> None:
        self._outils = outils_unisoc
        self._phase_suivante()

    # --- pilotes --------------------------------------------------------------

    def _zip_outils(self):
        return next((f for f in self._procedure.telechargements
                     if f.variante is None and f.nom.lower().endswith(".zip") and f.sha256), None)

    def _phase_pilotes(self) -> None:
        if self._pilotes_ok:
            self._phase_suivante()
            return
        fichier = self._zip_outils()
        if fichier is None or self._installateur_pilotes is None:
            self._erreur(tr("proc_error_pilotes"))
            return
        self._travail(tr("proc_drivers_title"), tr("proc_drivers_status"), annulable=False)
        runner = PilotesRunner(self._installateur_pilotes, self._dossier / fichier.nom, fichier.sha256, self)
        runner.termine.connect(self._pilotes_termine)
        self._runner = runner
        runner.start()

    def _pilotes_termine(self, installes: bool, redemarrage: bool, code: str) -> None:
        self._log(f"Pilotes : installés={installes}, redémarrage={redemarrage}, code={code or '-'}")
        if not installes:
            message = tr("proc_error_pilotes_refus") if code == "refus" else tr("proc_error_pilotes")
            self._erreur(message, self._phase_pilotes)
            return
        self._pilotes_ok = True
        if redemarrage:
            self._log(tr("proc_drivers_reboot"))
        self._phase_suivante()

    # --- fichier du système (.pac) ---------------------------------------------

    def _obtenir_pac(self) -> None:
        if self._pac is not None:
            self._phase_suivante()
            return
        variante = self._procedure.variante(self._variante)
        final = variante.fichier_final if variante else None
        if final and (self._dossier / final).is_file():
            self._pac = self._dossier / final
            self._log(f"Paquet déjà extrait : {self._pac}")
            self._phase_suivante()
            return
        archives = [f for f in self._procedure.fichiers_pour(self._variante)
                    if f.variante is not None and est_telechargeable(f)]
        if archives:
            archive = next((f for f in archives if f.nom.endswith(".001")), archives[0])
            self._archive = self._dossier / archive.nom
            self._fichier_final = final
            if self._procedure.mot_de_passe_requis:
                self._demander_mot_de_passe()
            else:
                self._extraire("")
            return
        self._afficher_choix_fichier()

    def _construire_mot_de_passe(self) -> None:
        page = self._page_mot_de_passe
        page.addWidget(_plain_label(tr("proc_password_title"), role="title"))
        self._mdp_aide = _plain_label("", wrap=True)
        page.addWidget(self._mdp_aide)
        self._mdp_lien = QVBoxLayout()
        page.addLayout(self._mdp_lien)
        ligne = QHBoxLayout()
        self._mdp_champ = QLineEdit()
        self._mdp_champ.setEchoMode(QLineEdit.Password)
        self._mdp_champ.setPlaceholderText(tr("proc_password_placeholder"))
        self._mdp_champ.returnPressed.connect(self._valider_mot_de_passe)
        ligne.addWidget(self._mdp_champ, 1)
        afficher = QCheckBox(tr("proc_password_show"))
        afficher.toggled.connect(
            lambda visible: self._mdp_champ.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password)
        )
        ligne.addWidget(afficher)
        page.addLayout(ligne)
        page.addWidget(_plain_label(tr("proc_password_never_saved"), role="secondary", wrap=True))
        self._mdp_erreur = _plain_label("", wrap=True)
        page.addWidget(self._mdp_erreur)
        valider = QPushButton(tr("proc_continue"))
        valider.setProperty("role", "primary")
        valider.clicked.connect(self._valider_mot_de_passe)
        page.addWidget(valider, alignment=Qt.AlignLeft)
        page.addStretch()

    def _demander_mot_de_passe(self, erreur: str = "") -> None:
        source = self._procedure.mot_de_passe_source
        self._mdp_aide.setText(tr("proc_password_help", source=source))
        self._vider(self._mdp_lien)
        url = premiere_url(source)
        if url:
            self._mdp_lien.addWidget(_link_widget(url), alignment=Qt.AlignLeft)
        self._mdp_erreur.setText(erreur)
        self._mdp_champ.clear()
        self._back.setEnabled(True)
        self._montrer(self._page_mot_de_passe)
        self._mdp_champ.setFocus()

    def _valider_mot_de_passe(self) -> None:
        mot_de_passe = self._mdp_champ.text()
        self._mdp_champ.clear()
        if mot_de_passe:
            self._extraire(mot_de_passe)

    def _extraire(self, mot_de_passe: str, archive: Optional[Path] = None) -> None:
        self._travail(tr("proc_extract_title"), tr("proc_extract_checking"))
        runner = ExtractionRunner(self._outils.septzip, archive or self._archive, self._dossier,
                                  mot_de_passe, self._fichier_final, self)
        del mot_de_passe
        runner.progression.connect(self._progression_extraction)
        runner.journal.connect(self._log)
        runner.echec.connect(self._extraction_echec)
        runner.termine.connect(self._extraction_terminee)
        self._runner = runner
        runner.start()

    def _progression_extraction(self, pourcent: int) -> None:
        self._travail_barre.setRange(0, 100)
        self._travail_barre.setValue(pourcent)
        self._travail_statut.setText(tr("proc_extract_status", pourcent=pourcent))

    def _extraction_echec(self, code: str, detail: str) -> None:
        if code == "mot_de_passe":
            self._log("Mot de passe refusé par l'archive.")
            self._demander_mot_de_passe(tr("proc_password_wrong"))
        elif code == "annule":
            self._erreur(tr("proc_error_extraction"), self._obtenir_pac)
        else:
            self._erreur(tr(f"proc_error_{code}") if code == "pac_absent" else tr("proc_error_extraction"),
                         self._obtenir_pac)

    def _extraction_terminee(self, chemin: str) -> None:
        self._pac = Path(chemin)
        self._phase_suivante()

    def _afficher_choix_fichier(self) -> None:
        page = self._page_choisir
        self._vider(page)
        page.addWidget(_plain_label(tr("proc_pick_title"), role="title"))
        page.addWidget(_plain_label(tr("proc_pick_message"), wrap=True))
        for fichier in self._procedure.fichiers_pour(self._variante):
            if not est_telechargeable(fichier):
                page.addWidget(_plain_label(fichier.nom, role="rowDesc", wrap=True))
                page.addWidget(_link_widget(fichier.url, tr("proc_pick_open_page")), alignment=Qt.AlignLeft)
        choisir = QPushButton(tr("proc_pick_button"))
        choisir.setProperty("role", "primary")
        choisir.clicked.connect(self._choisir_fichier)
        page.addWidget(choisir, alignment=Qt.AlignLeft)
        page.addStretch()
        self._back.setEnabled(True)
        self._montrer(page)

    def _choisir_fichier(self) -> None:
        chemin, _ = QFileDialog.getOpenFileName(self, tr("proc_pick_title"), str(Path.home() / "Downloads"),
                                                "*.pac *.zip *.7z *.rar *.001")
        if not chemin:
            return
        self._log(f"Fichier choisi : {chemin}")
        if chemin.lower().endswith(".pac"):
            self._pac = Path(chemin)
            self._phase_verification()
            return
        self._fichier_final = None
        self._dossier_extrait = self._dossier / "extrait"
        self._extraire_dans(Path(chemin), self._dossier_extrait)

    def _extraire_dans(self, archive: Path, dossier: Path) -> None:
        self._travail(tr("proc_extract_title"))
        runner = ExtractionRunner(self._outils.septzip, archive, dossier, "", None, self)
        runner.progression.connect(self._progression_extraction)
        runner.journal.connect(self._log)
        runner.echec.connect(lambda code, detail: self._erreur(tr("proc_error_extraction"), self._afficher_choix_fichier))
        runner.termine.connect(lambda chemin: (setattr(self, "_pac", Path(chemin)), self._phase_verification()))
        self._runner = runner
        runner.start()

    # --- contrôle du .pac ------------------------------------------------------

    def _phase_verification(self) -> None:
        if self._pac is None:
            self._obtenir_pac()  # la fiche ne liste pas d'extraction : le fichier est demandé ici
            return
        if self._pac_verifie:
            self._phase_suivante()
            return
        variante = self._procedure.variante(self._variante)
        en_tete, ecart = verifier_pac(self._pac, self._procedure.pac_produit,
                                      version_a_verifier(self._procedure), variante.pac_nom if variante else None)
        if en_tete is None:
            self._log(f"Paquet illisible : {ecart}")
            self._pac = None
            self._erreur(tr("proc_pac_unreadable"))
            return
        self._log(f"En-tête : format {en_tete.format}, produit {en_tete.produit}, version {en_tete.version}, nom {en_tete.nom}")
        if ecart is not None:
            self._log(f"Paquet refusé (champ {ecart} différent de la fiche)")
            self._pac = None
            self._erreur(tr("proc_pac_wrong", nom=en_tete.nom or en_tete.produit, version=en_tete.version))
            return
        self._pac_verifie = True
        self._log(tr("proc_pac_ok", nom=en_tete.nom or en_tete.produit, version=en_tete.version))
        if "verification_pac" in self._phases:
            self._phases.remove("verification_pac")
        self._phase_suivante()

    # --- consignes avant le branchement -----------------------------------------

    def _phase_consignes(self) -> None:
        page = self._page_consignes
        self._vider(page)
        page.addWidget(_plain_label(tr("proc_instructions_title"), role="title"))
        for numero, etape in enumerate(self._procedure.etapes_de("consignes"), start=1):
            page.addWidget(_plain_label(f"{numero}. {etape.detail}", wrap=True))
            if etape.avertissement:
                page.addWidget(_plain_label(etape.avertissement, role="secondary", wrap=True))
        delai = QHBoxLayout()
        self._delai_minutes = QSpinBox()
        self._delai_minutes.setRange(5, 60)
        self._delai_minutes.setValue(cmddloader.DELAI_PAR_DEFAUT_MS // 60000)
        self._delai_minutes.setSuffix(" min")
        delai.addWidget(_plain_label(tr("proc_delai_label"), role="secondary"))
        delai.addWidget(self._delai_minutes)
        delai.addStretch()
        page.addLayout(delai)
        continuer = QPushButton(tr("proc_instructions_done"))
        continuer.setProperty("role", "primary")
        if self._procedure.efface_donnees:  # dernière confirmation avant d'écrire (§2 n°6)
            page.addWidget(_build_restriction_banner_texte(tr("proc_erase_warning")))
            case = QCheckBox(tr("proc_erase_checkbox"))
            case.toggled.connect(continuer.setEnabled)
            page.addWidget(case)
            continuer.setEnabled(False)
        continuer.clicked.connect(self._phase_suivante)
        page.addWidget(continuer, alignment=Qt.AlignLeft)
        page.addStretch()
        self._back.setEnabled(True)
        self._montrer(page)

    # --- flash ----------------------------------------------------------------

    def _phase_flash(self) -> None:
        if self._pac is None or not self._pac_verifie or self._outils is None:
            self._erreur(tr("proc_pac_unreadable"))
            return
        self._travail(tr("proc_flash_title"), tr("proc_flash_starting"))
        delai = getattr(self, "_delai_minutes", None)
        delai_ms = delai.value() * 60000 if delai is not None else cmddloader.DELAI_PAR_DEFAUT_MS
        flash = FlashRunner(self._outils.cmddloader, self._pac, delai_ms, self._procedure.vid_pid, self)
        flash.evenement.connect(self._evenement_flash)
        flash.usb.connect(self._evenement_usb)
        flash.journal.connect(self._log)
        flash.termine.connect(self._flash_termine)
        self._flash = flash
        self._log(f"VID:PID attendus : {', '.join(self._procedure.vid_pid) or '-'} "
                  f"({'à vérifier' if self._procedure.vid_pid_a_verifier else 'vérifiés'})")
        flash.start()

    def _evenement_flash(self, evenement) -> None:
        if evenement.type == "chargement":
            self._travail_barre.setRange(0, 100)
            self._travail_barre.setValue(evenement.valeur)
            self._travail_statut.setText(tr("proc_flash_loading", pourcent=evenement.valeur))
        elif evenement.type == "attente":
            self._travail_titre.setText(tr("proc_flash_connect_title"))
            geste = "\n".join(e.detail for e in self._procedure.etapes_de("flash") if e.action == "mode_download")
            self._travail_consigne.setText(geste)
            self._travail_barre.setRange(0, 0)
            self._travail_statut.setText(tr("proc_flash_connect_countdown", secondes=evenement.valeur))
        elif evenement.type == "port":
            self._travail_titre.setText(tr("proc_flash_running_title"))
            self._travail_consigne.setText(tr("proc_flash_detected"))
            self._travail_annuler.setVisible(False)
        elif evenement.type == "progression":
            self._travail_titre.setText(tr("proc_flash_running_title"))
            self._travail_annuler.setVisible(False)
            self._travail_barre.setRange(0, 100)
            self._travail_barre.setValue(evenement.valeur)
            self._travail_statut.setText(tr("proc_flash_running", pourcent=evenement.valeur))

    def _evenement_usb(self, genre: str, vid_pid: str, nom: str) -> None:
        if genre:
            self._log(f"[diagnostic] console {genre} : {vid_pid or '?'} {nom}")
        if genre == "android":
            self._travail_consigne.setText(tr("proc_flash_android"))

    def _flash_termine(self, reussi: bool, message: str) -> None:
        flash, self._flash = self._flash, None
        commence = flash is not None and flash._flash_commence
        self._log(f"Fin du flash : {'réussi' if reussi else 'échec'} {message}")
        if flash is not None and flash.annule:  # avant toute écriture : retour aux consignes
            self._refaire_flash()
            return
        if reussi:
            self._phase_suivante()
            return
        texte = tr("proc_flash_failed", message=message) if commence else tr("proc_flash_timeout")
        self._erreur(texte, self._refaire_flash)
        self._travail_secours.setVisible(self._outils is not None and self._outils.upgradedownload is not None)

    def _refaire_flash(self) -> None:
        """Toujours repasser par les consignes et leur confirmation avant
        de relancer une écriture."""
        self._phases.insert(0, "flash")
        self._phase_consignes()

    def _ouvrir_outil_graphique(self) -> None:
        """Repli : l'outil graphique officiel, chemin du .pac copié."""
        QGuiApplication.clipboard().setText(str(self._pac))
        self._travail_consigne.setText(tr("proc_fallback_guide", chemin=str(self._pac)))
        self._log(f"Repli : ouverture de {self._outils.upgradedownload}")
        QProcess.startDetached(str(self._outils.upgradedownload), [], str(self._outils.dossier))

    # --- fin ---------------------------------------------------------------------

    def _afficher_fin(self) -> None:
        page = self._page_fin
        self._vider(page)
        page.addWidget(_plain_label(tr("proc_done_title"), role="title"))
        for etape in self._procedure.etapes:
            if etape.action in ("fin_flash", "attendre_premier_demarrage", "configuration_initiale"):
                page.addWidget(_plain_label(etape.detail, wrap=True))
        android = QPushButton(tr("proc_done_android"))
        android.setProperty("role", "primary")
        android.clicked.connect(self.android_requested.emit)
        page.addWidget(android, alignment=Qt.AlignLeft)
        fin = QPushButton(tr("proc_done_back"))
        fin.clicked.connect(self.back_requested.emit)
        page.addWidget(fin, alignment=Qt.AlignLeft)
        page.addStretch()
        self._phases = []
        self._back.setEnabled(True)
        self._montrer(page)

    def _afficher_depannage(self) -> None:
        conseils = self._procedure.depannage if self._procedure else []
        texte = "\n\n".join(f"{d.symptome}\n→ {d.solution}" for d in conseils) or tr("proc_help_empty")
        boite = QMessageBox(self)
        boite.setWindowTitle(tr("proc_help_title"))
        boite.setTextFormat(Qt.PlainText)
        boite.setText(texte)
        boite.open()


def _build_restriction_banner_texte(texte: str) -> QWidget:
    """Bandeau rouge (`role=danger`, même habillage que le bandeau de
    restriction de la fiche) avec un texte donné."""
    cadre = QFrame()
    cadre.setProperty("role", "danger")
    QVBoxLayout(cadre).addWidget(_plain_label(texte, role="dangerTitle", wrap=True))
    return cadre


__all__ = ["ProcedureScreen", "ESPACE_REQUIS"]
