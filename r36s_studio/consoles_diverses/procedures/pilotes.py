# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Pilotes USB UniSoc (Windows) : détection, et installation silencieuse
par le worker élevé (`__main__.py::cmd_install_unisoc_drivers`).

`pnputil` (fourni avec Windows) plutôt que `DPInst64.exe` du paquet :
aucune fenêtre, codes de retour clairs (0, 3010 = redémarrage conseillé).
DPInst bloque l'automatisation de ses clics (constaté le 2026-10-27).

Détection : le nom d'origine `sprdvcom.inf` apparaît tel quel dans
`pnputil /enum-drivers`, quelle que soit la langue de Windows (les libellés
autour, eux, sont traduits)."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import List, Tuple

INF_PRINCIPAL = "sprdvcom.inf"
# Paquet Windows 10 : convient aussi à Windows 11 (procédure officielle).
DOSSIER_PILOTES = ("UnisocDrivers", "Win10", "Drivers")
CODES_REUSSITE = (0, 3010)
_SANS_FENETRE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class PilotesErreur(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code  # "empreinte", "zip", "pnputil"
        self.detail = detail


@dataclass
class ResultatPilotes:
    code_retour: int
    redemarrage: bool
    installes: bool


def sont_installes_dans(sortie_enum_drivers: str) -> bool:
    return INF_PRINCIPAL in sortie_enum_drivers.lower()


def sont_installes() -> bool:
    try:
        sortie = subprocess.run(
            ["pnputil", "/enum-drivers"], capture_output=True, text=True, errors="replace", timeout=60,
            creationflags=_SANS_FENETRE,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return sont_installes_dans(sortie or "")


def membres_pilotes(noms: List[str]) -> List[Tuple[str, PurePosixPath]]:
    """(membre du zip, chemin relatif sous `Drivers/`) pour les fichiers de
    `…/UnisocDrivers/Win10/Drivers/` -- sous-dossiers `amd64/`/`i386/`
    gardés (les .inf y cherchent les .sys) ; `..` et chemins absolus refusés."""
    cible = tuple(p.lower() for p in DOSSIER_PILOTES)
    retenus = []
    for nom in noms:
        if nom.endswith("/"):
            continue
        parties = PurePosixPath(nom).parts
        bas = tuple(p.lower() for p in parties)
        for i in range(len(bas) - len(cible)):
            if bas[i : i + len(cible)] == cible:
                relatif = parties[i + len(cible) :]
                if relatif and ".." not in relatif and not PurePosixPath(nom).is_absolute():
                    retenus.append((nom, PurePosixPath(*relatif)))
                break
    return retenus


def commande_installation(dossier: Path) -> List[str]:
    return ["pnputil", "/add-driver", str(dossier / "*.inf"), "/install"]


def _sha256(chemin: Path) -> str:
    empreinte = hashlib.sha256()
    with open(chemin, "rb") as fichier:
        for bloc in iter(lambda: fichier.read(1024 * 1024), b""):
            empreinte.update(bloc)
    return empreinte.hexdigest()


def installer(zip_path: Path, sha256: str) -> ResultatPilotes:
    """Côté worker élevé. Revérifie la SHA-256 du zip (un fichier du
    dossier de l'utilisateur, modifiable par lui), extrait seulement les
    pilotes Windows 10 dans un dossier temporaire neuf, puis `pnputil`."""
    if _sha256(zip_path) != sha256.lower():
        raise PilotesErreur("empreinte", zip_path.name)
    dossier = Path(tempfile.mkdtemp(prefix="r36s_pilotes_"))
    try:
        with zipfile.ZipFile(zip_path) as archive:
            membres = membres_pilotes(archive.namelist())
            if not any(str(relatif).lower() == INF_PRINCIPAL for _, relatif in membres):
                raise PilotesErreur("zip", f"{INF_PRINCIPAL} absent")
            for membre, relatif in membres:
                cible = dossier.joinpath(*relatif.parts)
                cible.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(membre) as source, open(cible, "wb") as sortie:
                    shutil.copyfileobj(source, sortie)
        processus = subprocess.run(
            commande_installation(dossier), capture_output=True, text=True, errors="replace", timeout=300,
            creationflags=_SANS_FENETRE,
        )
        if processus.returncode not in CODES_REUSSITE:
            raise PilotesErreur("pnputil", f"code {processus.returncode} : {(processus.stdout or '')[-500:]}")
        return ResultatPilotes(processus.returncode, processus.returncode == 3010, sont_installes())
    finally:
        shutil.rmtree(dossier, ignore_errors=True)


def resultat_vers_dict(resultat: ResultatPilotes) -> dict:
    return {"code_retour": resultat.code_retour, "redemarrage": resultat.redemarrage, "installes": resultat.installes}


def resultat_depuis_dict(data: dict) -> Tuple[bool, bool]:
    """(installés, redémarrage conseillé) depuis l'événement du worker."""
    return bool(data.get("installes")), bool(data.get("redemarrage"))


__all__ = [
    "PilotesErreur",
    "ResultatPilotes",
    "sont_installes",
    "sont_installes_dans",
    "membres_pilotes",
    "commande_installation",
    "installer",
    "resultat_vers_dict",
    "resultat_depuis_dict",
    "INF_PRINCIPAL",
]
