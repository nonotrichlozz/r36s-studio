# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Archive chiffrée en plusieurs morceaux (`.7z.001`, `.7z.002`) extraite
avec le 7-Zip fourni dans les outils Unisoc
(`SPRD_Download_Tool/System/Tools/7zip/32/7z.exe`, 7-Zip 19.02).

Choix (préféré à py7zr) : programme natif, rapide sur 6,7 Go, progression
en pourcentage (`-bsp1`), morceaux suivis tout seul. La procédure est de
toute façon réservée à Windows.

**Mot de passe** : écrit sur l'entrée standard de 7-Zip, jamais en `-p` --
la ligne de commande est visible des autres programmes et l'appli journalise
les commandes qu'elle lance. Vérifié avec ce 7z.exe (2026-10-27) : une
archive chiffrée en trois morceaux s'extrait à l'identique avec le mot de
passe reçu sur l'entrée standard.

**Mauvais mot de passe** : 7-Zip le signale dès le premier bloc
(« Wrong password », ou « Can't open as archive » si les en-têtes sont
chiffrés) -- `verifier_mot_de_passe` lance un test et s'arrête dès le
premier pourcentage, avant toute extraction des 6,7 Go."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Callable, List, Optional

_POURCENT = re.compile(r"(\d{1,3})%")
_MARQUES_MOT_DE_PASSE = ("wrong password", "can't open as archive", "cannot open encrypted archive")
_MARQUES_ERREUR = ("error", "erreur")
_SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class SeptZipErreur(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code  # "mot_de_passe", "extraction", "annule"
        self.detail = detail


def commande_test(septzip: Path, archive: Path) -> List[str]:
    return [str(septzip), "t", str(archive), "-bsp1", "-bso1", "-bse1"]


def commande_extraction(septzip: Path, archive: Path, dossier: Path) -> List[str]:
    return [str(septzip), "x", str(archive), f"-o{dossier}", "-y", "-bsp1", "-bso1", "-bse1"]


def analyser_ligne(ligne: str) -> Optional[object]:
    """`int` (pourcentage), `"mot_de_passe"` (mauvais mot de passe),
    `"erreur"` ou `None`."""
    bas = ligne.lower()
    if any(marque in bas for marque in _MARQUES_MOT_DE_PASSE):
        return "mot_de_passe"
    if bas.startswith(_MARQUES_ERREUR):
        return "erreur"
    trouve = _POURCENT.findall(ligne)
    return int(trouve[-1]) if trouve else None


def lignes(flux) -> "iter":
    """Découpe sur `\\r` aussi : 7-Zip réécrit sa ligne de progression."""
    tampon = b""
    while True:
        morceau = flux.read1(4096) if hasattr(flux, "read1") else flux.read(4096)
        if not morceau:
            break
        tampon += morceau
        while True:
            coupure = min((i for i in (tampon.find(b"\r"), tampon.find(b"\n"), tampon.find(b"\x08")) if i >= 0), default=-1)
            if coupure < 0:
                break
            yield tampon[:coupure].decode("utf-8", errors="replace")
            tampon = tampon[coupure + 1 :]
    if tampon:
        yield tampon.decode("utf-8", errors="replace")


def _executer(
    argv: List[str],
    mot_de_passe: str,
    progression: Callable[[int], None],
    annule: Callable[[], bool],
    arret_au_premier_pourcent: bool,
    journal: Callable[[str], None],
) -> None:
    processus = subprocess.Popen(
        argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=_SANS_FENETRE
    )
    try:
        processus.stdin.write(mot_de_passe.encode("utf-8") + b"\n")
        processus.stdin.close()
        erreur = None
        for ligne in lignes(processus.stdout):
            if annule():
                raise SeptZipErreur("annule")
            evenement = analyser_ligne(ligne)
            if evenement == "mot_de_passe":
                raise SeptZipErreur("mot_de_passe")
            if evenement == "erreur":
                erreur = ligne.strip()
                journal(f"7-Zip : {erreur}")
            elif isinstance(evenement, int):
                progression(evenement)
                if arret_au_premier_pourcent and evenement >= 1:
                    return
        code = processus.wait()
        if code != 0:
            raise SeptZipErreur("extraction", erreur or f"code de retour {code}")
    finally:
        if processus.poll() is None:
            processus.kill()
            processus.wait()


def verifier_mot_de_passe(
    septzip: Path, archive: Path, mot_de_passe: str, annule: Callable[[], bool] = lambda: False,
    journal: Callable[[str], None] = lambda texte: None,
) -> None:
    """Lève `SeptZipErreur("mot_de_passe")` si le mot de passe est faux ;
    rend la main dès que 7-Zip a décodé le début de l'archive."""
    _executer(commande_test(septzip, archive), mot_de_passe, lambda p: None, annule, True, journal)


def extraire(
    septzip: Path, archive: Path, dossier: Path, mot_de_passe: str,
    progression: Callable[[int], None] = lambda p: None, annule: Callable[[], bool] = lambda: False,
    journal: Callable[[str], None] = lambda texte: None,
) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    _executer(commande_extraction(septzip, archive, dossier), mot_de_passe, progression, annule, False, journal)


__all__ = [
    "SeptZipErreur",
    "commande_test",
    "commande_extraction",
    "analyser_ligne",
    "verifier_mot_de_passe",
    "extraire",
]
