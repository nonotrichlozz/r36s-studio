# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""En-tête d'un paquet Spreadtrum/Unisoc (`.pac`), lu avant tout flash.

Disposition relevée sur le vrai `ums512_1h10_rg_rotate_gammaos_1.4.1_lite.pac`
(`BP_R2.0.1`, 2026-10-27), identique à celle de `BP_R1.0.0` pour ces champs ;
chaînes en UTF-16LE terminées par un zéro :

    0     version du format  (24 caractères)  « BP_R2.0.1 »
    52    nom de produit     (256 caractères) « ums512_1h10 »
    564   version            (256 caractères) « 1.4.1 »
    1076  nombre de fichiers (uint32)
    1080  position de la table des fichiers (uint32)
    1104  nom affiché        (100 caractères) « RG_ROTATE_GAMMAOS_NEXT_LITE »

UpgradeDownload affiche le même paquet comme
`PACKET: RG_ROTATE_GAMMAOS_NEXT_LITE ; Version: 1.4.1`."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

TAILLE_EN_TETE = 1304  # 1104 + 100 caractères UTF-16


class PacInvalide(ValueError):
    pass


@dataclass
class EnTetePac:
    format: str
    produit: str
    version: str
    nom: str
    nombre_fichiers: int


def _chaine(donnees: bytes, debut: int, caracteres: int) -> str:
    brut = donnees[debut : debut + caracteres * 2].decode("utf-16-le", errors="replace")
    return brut.split("\x00", 1)[0].strip()


def lire_en_tete(chemin: Path) -> EnTetePac:
    with open(chemin, "rb") as fichier:
        donnees = fichier.read(TAILLE_EN_TETE)
    if len(donnees) < TAILLE_EN_TETE:
        raise PacInvalide("fichier trop court")
    format_pac = _chaine(donnees, 0, 24)
    if not format_pac.startswith("BP_R"):
        raise PacInvalide(f"format inconnu : {format_pac!r}")
    (nombre,) = struct.unpack_from("<I", donnees, 1076)
    return EnTetePac(
        format=format_pac,
        produit=_chaine(donnees, 52, 256),
        version=_chaine(donnees, 564, 256),
        nom=_chaine(donnees, 1104, 100),
        nombre_fichiers=nombre,
    )


def ecart(en_tete: EnTetePac, produit: str, version: Optional[str], nom: Optional[str]) -> Optional[str]:
    """Premier champ qui ne correspond pas à ce que la fiche attend
    (`"produit"`, `"version"`, `"nom"`), ou `None` si le paquet convient.
    Comparaison sans tenir compte de la casse ; `version`/`nom` à `None`
    ne sont pas vérifiés (firmware d'origine : nom inconnu d'avance)."""
    if en_tete.produit.lower() != produit.lower():
        return "produit"
    if version and en_tete.version.lower() != version.lower():
        return "version"
    if nom and en_tete.nom.lower() != nom.lower():
        return "nom"
    return None


__all__ = ["EnTetePac", "PacInvalide", "lire_en_tete", "ecart", "TAILLE_EN_TETE"]
