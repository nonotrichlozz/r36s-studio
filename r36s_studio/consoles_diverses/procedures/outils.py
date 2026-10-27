# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Outils Unisoc fournis par la release (`UnisocTools_<CONSOLE>.zip`) :
extraction du zip et emplacement des programmes utilisés.

Constaté (2026-10-27) : `UnisocTools_RG_ROTATE.zip` contient en réalité un
dossier `UnisocTools_RG_VITA/` -- les programmes sont donc cherchés par leur
nom, jamais par un chemin fixe."""

from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

CMDDLOADER = "CmdDloader.exe"
UPGRADEDOWNLOAD = "UpgradeDownload.exe"
SEPTZIP_RELATIF = ("System", "Tools", "7zip", "32", "7z.exe")


class OutilsIntrouvables(Exception):
    pass


@dataclass
class OutilsUnisoc:
    dossier: Path  # SPRD_Download_Tool
    cmddloader: Path
    upgradedownload: Optional[Path]
    septzip: Path


def extraire_zip(zip_path: Path, destination: Path) -> None:
    """Extraction refusant tout membre qui sortirait de `destination`
    (« zip slip ») : le zip vient d'internet, même avec sa SHA-256."""
    racine = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for membre in archive.infolist():
            cible = (racine / membre.filename).resolve()
            if cible != racine and racine not in cible.parents:
                raise OutilsIntrouvables(f"chemin refusé dans le zip : {membre.filename}")
        archive.extractall(racine)


def trouver(destination: Path) -> OutilsUnisoc:
    for cmd in sorted(destination.rglob(CMDDLOADER)):
        dossier = cmd.parent
        septzip = dossier.joinpath(*SEPTZIP_RELATIF)
        if septzip.is_file():
            upgrade = dossier / UPGRADEDOWNLOAD
            return OutilsUnisoc(dossier, cmd, upgrade if upgrade.is_file() else None, septzip)
    raise OutilsIntrouvables(f"{CMDDLOADER} ou 7-Zip absent de {destination}")


def preparer(zip_path: Path, destination: Path) -> OutilsUnisoc:
    """Extrait le zip une seule fois (marqueur `.extrait-<nom du zip>`),
    puis localise les outils."""
    marqueur = destination / f".extrait-{zip_path.name}"
    if not marqueur.exists():
        destination.mkdir(parents=True, exist_ok=True)
        extraire_zip(zip_path, destination)
        marqueur.write_text("ok", encoding="utf-8")
    return trouver(destination)


__all__ = ["OutilsUnisoc", "OutilsIntrouvables", "extraire_zip", "trouver", "preparer", "CMDDLOADER"]
