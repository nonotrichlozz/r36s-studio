# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Threads Qt du moteur de procédures USB (`procedures/`) : tout ce qui
bloque (réseau, 7-Zip, CmdDloader, liste USB) tourne hors du thread Qt
principal (CLAUDE.md racine §5). Le **mot de passe** d'archive n'est passé
qu'à `ExtractionRunner`, en mémoire, et n'est jamais journalisé."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QThread, Signal

from .procedures import cmddloader, outils, pac, septzip, usb
from .procedures.fiche import Fichier
from .procedures.telechargement import TelechargementErreur, telecharger
from .procedures.veille import sans_veille

_SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class TelechargementsRunner(QThread):
    """Télécharge les fichiers un par un (reprise, SHA-256), puis extrait
    et localise les outils Unisoc (`outils.preparer`)."""

    progression = Signal(str, "qint64", "qint64")  # nom, octets reçus, total
    journal = Signal(str)
    echec = Signal(str, str)  # code, détail
    termine = Signal(object)  # OutilsUnisoc

    def __init__(self, fichiers: List[Fichier], dossier: Path, parent=None):
        super().__init__(parent)
        self._fichiers = fichiers
        self._dossier = dossier
        self._annule = False

    def annuler(self) -> None:
        self._annule = True

    def run(self) -> None:
        try:
            for fichier in self._fichiers:
                self.journal.emit(f"Téléchargement : {fichier.nom} ({fichier.url})")
                telecharger(
                    fichier.url,
                    self._dossier / fichier.nom,
                    fichier.sha256 or "",
                    progression=lambda fait, total, nom=fichier.nom: self.progression.emit(nom, fait, total),
                    annule=lambda: self._annule,
                )
                self.journal.emit(f"SHA-256 vérifiée : {fichier.nom}")
            zips = [f for f in self._fichiers if f.nom.lower().endswith(".zip") and f.variante is None]
            if not zips:
                self.echec.emit("outils", "aucun zip d'outils dans la fiche")
                return
            resultat = outils.preparer(self._dossier / zips[0].nom, self._dossier / "outils")
            self.journal.emit(f"Outils : {resultat.cmddloader}")
            self.termine.emit(resultat)
        except TelechargementErreur as exc:
            self.echec.emit(exc.code, exc.detail)
        except outils.OutilsIntrouvables as exc:
            self.echec.emit("outils", str(exc))
        except OSError as exc:
            self.echec.emit("disque", str(exc))


class AppelRunner(QThread):
    """Appelle une fonction bloquante courte (vérification des pilotes...)
    hors du thread Qt ; `termine` porte son résultat."""

    termine = Signal(object)

    def __init__(self, fonction: Callable[[], object], parent=None):
        super().__init__(parent)
        self._fonction = fonction

    def run(self) -> None:
        try:
            self.termine.emit(self._fonction())
        except Exception:  # un contrôle qui échoue vaut « non »
            self.termine.emit(None)


class PilotesRunner(QThread):
    """Appelle l'installateur injecté par `MainWindow` (worker élevé) :
    `installateur(zip, sha256) -> (installés, redémarrage, code d'erreur)`."""

    termine = Signal(bool, bool, str)  # installés, redémarrage conseillé, code d'erreur ("" si aucun)

    def __init__(self, installateur: Callable, zip_path: Path, sha256: str, parent=None):
        super().__init__(parent)
        self._installateur = installateur
        self._zip = zip_path
        self._sha256 = sha256

    def run(self) -> None:
        try:
            installes, redemarrage, code = self._installateur(str(self._zip), self._sha256)
        except Exception as exc:  # jamais une exception qui traverse le thread
            installes, redemarrage, code = False, False, f"exception:{type(exc).__name__}"
        self.termine.emit(bool(installes), bool(redemarrage), code or "")


class ExtractionRunner(QThread):
    """Vérifie le mot de passe sur le début de l'archive, puis extrait, puis
    trouve le `.pac` (nom attendu, sinon l'unique `.pac` extrait)."""

    progression = Signal(int)
    journal = Signal(str)
    echec = Signal(str, str)
    termine = Signal(str)  # chemin du .pac

    def __init__(self, septzip_exe: Path, archive: Path, dossier: Path, mot_de_passe: str,
                 fichier_final: Optional[str], parent=None):
        super().__init__(parent)
        self._septzip = septzip_exe
        self._archive = archive
        self._dossier = dossier
        self._mot_de_passe = mot_de_passe
        self._fichier_final = fichier_final
        self._annule = False

    def annuler(self) -> None:
        self._annule = True

    def run(self) -> None:
        mot_de_passe, self._mot_de_passe = self._mot_de_passe, ""
        try:
            self.journal.emit(f"Vérification du mot de passe sur {self._archive.name}")
            septzip.verifier_mot_de_passe(self._septzip, self._archive, mot_de_passe, lambda: self._annule,
                                          self.journal.emit)
            self.journal.emit(f"Extraction de {self._archive.name} vers {self._dossier}")
            septzip.extraire(self._septzip, self._archive, self._dossier, mot_de_passe, self.progression.emit,
                             lambda: self._annule, self.journal.emit)
        except septzip.SeptZipErreur as exc:
            self.echec.emit(exc.code, exc.detail)
            return
        except OSError as exc:
            self.echec.emit("extraction", str(exc))
            return
        finally:
            del mot_de_passe
        chemin = trouver_pac(self._dossier, self._fichier_final)
        if chemin is None:
            self.echec.emit("pac_absent", self._fichier_final or "*.pac")
            return
        self.journal.emit(f"Paquet extrait : {chemin.name} ({chemin.stat().st_size} octets)")
        self.termine.emit(str(chemin))


def trouver_pac(dossier: Path, fichier_final: Optional[str]) -> Optional[Path]:
    if fichier_final:
        chemin = dossier / fichier_final
        return chemin if chemin.is_file() and chemin.stat().st_size > 0 else None
    trouves = [p for p in dossier.rglob("*.pac") if p.is_file()]
    return trouves[0] if len(trouves) == 1 else None


def espace_libre(dossier: Path) -> int:
    while not dossier.exists() and dossier.parent != dossier:
        dossier = dossier.parent
    return shutil.disk_usage(dossier).free


class FlashRunner(QThread):
    """Lance CmdDloader (qui charge le .pac puis attend la console), lit sa
    sortie ligne par ligne, et surveille l'USB en parallèle : journal de
    tout nouvel appareil (VID:PID), détection d'une console démarrée sous
    Android. Ordinateur maintenu éveillé pendant tout le flash."""

    evenement = Signal(object)  # cmddloader.Evenement
    usb = Signal(str, str, str)  # genre ("download"/"android"/""), VID:PID, nom
    journal = Signal(str)
    termine = Signal(bool, str)  # réussi, message

    def __init__(self, cmd_exe: Path, pac_path: Path, delai_ms: int, vid_pids: List[str], parent=None):
        super().__init__(parent)
        self._cmd = cmd_exe
        self._pac = pac_path
        self._delai_ms = delai_ms
        self._vid_pids = vid_pids
        self._processus: Optional[subprocess.Popen] = None
        self._flash_commence = False
        self.annule = False
        self._fin = threading.Event()

    def annuler(self) -> bool:
        """Arrête CmdDloader **seulement avant** que l'écriture ait commencé
        (rien n'est encore écrit). Rend `False` une fois le flash lancé."""
        if self._flash_commence or self._processus is None:
            return False
        self.annule = True
        self._processus.kill()
        return True

    def _surveiller_usb(self) -> None:
        avant = usb.lister()
        for appareil in avant:
            genre = usb.classer(appareil, self._vid_pids)
            if genre:
                self.usb.emit(genre, appareil.vid_pid or "", appareil.nom)
        while not self._fin.wait(2.0):
            apres = usb.lister()
            for appareil in usb.nouveaux(avant, apres):
                genre = usb.classer(appareil, self._vid_pids) or ""
                self.journal.emit(f"[diagnostic] USB branché : {appareil.vid_pid or '?'} {appareil.nom} ({appareil.identifiant})")
                self.usb.emit(genre, appareil.vid_pid or "", appareil.nom)
            avant = apres

    def run(self) -> None:
        argv = cmddloader.commande(self._cmd, self._pac, self._delai_ms)
        self.journal.emit(f"[diagnostic] flash : {' '.join(argv)}")
        surveillance = threading.Thread(target=self._surveiller_usb, daemon=True)
        surveillance.start()
        resultat: Optional[cmddloader.Evenement] = None
        debut = time.monotonic()
        try:
            with sans_veille():
                self._processus = subprocess.Popen(
                    argv, cwd=str(self._cmd.parent), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL, creationflags=_SANS_FENETRE,
                )
                for ligne in septzip.lignes(self._processus.stdout):
                    if not ligne.strip():
                        continue
                    self.journal.emit(f"CmdDloader : {ligne.strip()}")
                    evenement = cmddloader.analyser_ligne(ligne)
                    if evenement is None:
                        continue
                    if evenement.type in ("port", "fichier", "progression"):
                        self._flash_commence = True
                    if evenement.type == "resultat":
                        resultat = evenement
                    self.evenement.emit(evenement)
                code = self._processus.wait()
        except OSError as exc:
            self._fin.set()
            self.termine.emit(False, str(exc))
            return
        self._fin.set()
        self.journal.emit(f"CmdDloader terminé (code {code}) en {time.monotonic() - debut:.0f} s")
        if resultat is not None:
            self.termine.emit(bool(resultat.valeur), resultat.texte)
        else:
            self.termine.emit(False, f"code de retour {code}")


def verifier_pac(chemin: Path, produit: str, version: Optional[str], nom: Optional[str]):
    """(en-tête ou None, champ en écart ou code d'erreur, ou None)."""
    try:
        en_tete = pac.lire_en_tete(chemin)
    except (OSError, pac.PacInvalide) as exc:
        return None, f"illisible:{exc}"
    return en_tete, pac.ecart(en_tete, produit, version, nom)


__all__ = [
    "TelechargementsRunner",
    "PilotesRunner",
    "ExtractionRunner",
    "FlashRunner",
    "trouver_pac",
    "espace_libre",
    "verifier_pac",
]
