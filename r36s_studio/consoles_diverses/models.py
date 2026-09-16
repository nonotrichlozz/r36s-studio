# R36S Studio
# Copyright (C) 2026 nonotrichlozz
#
# Ce fichier fait partie de R36S Studio. R36S Studio est un logiciel libre :
# vous pouvez le redistribuer et/ou le modifier selon les termes de la GNU
# General Public License telle que publiée par la Free Software Foundation,
# version 3 de la licence.
#
# R36S Studio est distribué dans l'espoir qu'il sera utile, mais SANS
# AUCUNE GARANTIE ; sans même la garantie implicite de QUALITÉ MARCHANDE ou
# d'ADÉQUATION À UN USAGE PARTICULIER. Consultez la GNU General Public
# License pour plus de détails.
#
# Vous devez avoir reçu une copie de la GNU General Public License avec
# R36S Studio. Si ce n'est pas le cas, consultez <https://www.gnu.org/licenses/>.

"""Modèle de données d'une fiche console, reflet du schéma JSON publié par
`r36s-studio-catalogue/schema/console.schema.json` (lu en lecture seule,
jamais modifié depuis ce dépôt). Parsing défensif plutôt qu'une dépendance
de validation externe (aucune n'est déjà présente dans `requirements.txt`,
on n'en ajoute pas pour un schéma de cette taille) : seuls les champs dont
l'absence empêcherait tout affichage sensé (identité, matériel, statut)
font lever `ValueError` -- capturée par `client.py` et traduite en
`RechercheErreur("reponse_invalide")`. Les champs optionnels du schéma
(`incompatibles`, `licences`, `sources`, `liens_officiels`,
`date_verification`, et les booléens "absents-si-faux" de chaque option)
retombent silencieusement sur une valeur vide/`False`, jamais sur une
exception -- une fiche par ailleurs exploitable ne doit pas être rejetée
pour un champ annexe manquant ou malformé côté serveur."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class OptionConsole:
    """Une entrée de `options.{frontend,systeme_cfw,firmware_origine,
    mises_a_jour}` -- `nom`/`description`/`source_url` sont les seuls
    champs obligatoires du schéma pour une option."""

    nom: str
    description: str
    source_url: str
    url: Optional[str] = None
    licence: Optional[str] = None
    licence_a_verifier: bool = False
    restriction_commerciale: bool = False


@dataclass
class Incompatible:
    nom: str
    raison: str


@dataclass
class Source:
    url: str
    type: str


@dataclass
class OptionsConsole:
    frontend: List[OptionConsole] = field(default_factory=list)
    systeme_cfw: List[OptionConsole] = field(default_factory=list)
    firmware_origine: List[OptionConsole] = field(default_factory=list)
    mises_a_jour: List[OptionConsole] = field(default_factory=list)

    def toutes_les_categories(self) -> List[tuple]:
        """Les quatre catégories dans l'ordre d'affichage de l'écran de
        recherche (§ spec, "Options par catégorie")."""
        return [
            ("frontend", self.frontend),
            ("systeme_cfw", self.systeme_cfw),
            ("firmware_origine", self.firmware_origine),
            ("mises_a_jour", self.mises_a_jour),
        ]


@dataclass
class FicheConsole:
    id: str
    nom: str
    fabricant: str
    alias: List[str]
    soc: str
    architecture: str
    os_type: str
    options: OptionsConsole
    statut: str
    signalements: int
    incompatibles: List[Incompatible] = field(default_factory=list)
    liens_officiels: List[str] = field(default_factory=list)
    licences: List[str] = field(default_factory=list)
    restriction_commerciale: bool = False
    sources: List[Source] = field(default_factory=list)
    date_verification: Optional[str] = None

    @property
    def verifiee(self) -> bool:
        return self.statut == "verifie"

    @property
    def a_une_restriction_commerciale(self) -> bool:
        """Vrai si la fiche elle-même ou au moins une option porte
        `restriction_commerciale` -- déclenche le bandeau rouge de l'écran
        de recherche, quelle que soit l'origine exacte du signal."""
        if self.restriction_commerciale:
            return True
        for _, options in self.options.toutes_les_categories():
            if any(option.restriction_commerciale for option in options):
                return True
        return False


def _as_str_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _option_depuis_json(data: Any) -> Optional[OptionConsole]:
    if not isinstance(data, dict):
        return None
    for champ in ("nom", "description", "source_url"):
        if champ not in data:
            return None
    return OptionConsole(
        nom=str(data["nom"]),
        description=str(data["description"]),
        source_url=str(data["source_url"]),
        url=data.get("url") if isinstance(data.get("url"), str) else None,
        licence=data.get("licence") if isinstance(data.get("licence"), str) else None,
        licence_a_verifier=bool(data.get("licence_a_verifier", False)),
        restriction_commerciale=bool(data.get("restriction_commerciale", False)),
    )


def _option_list_depuis_json(data: Any) -> List[OptionConsole]:
    if not isinstance(data, list):
        return []
    options = [_option_depuis_json(item) for item in data]
    return [option for option in options if option is not None]


def _options_depuis_json(data: Any) -> OptionsConsole:
    if not isinstance(data, dict):
        return OptionsConsole()
    return OptionsConsole(
        frontend=_option_list_depuis_json(data.get("frontend")),
        systeme_cfw=_option_list_depuis_json(data.get("systeme_cfw")),
        firmware_origine=_option_list_depuis_json(data.get("firmware_origine")),
        mises_a_jour=_option_list_depuis_json(data.get("mises_a_jour")),
    )


def _incompatibles_depuis_json(data: Any) -> List[Incompatible]:
    if not isinstance(data, list):
        return []
    result = []
    for item in data:
        if isinstance(item, dict) and "nom" in item and "raison" in item:
            result.append(Incompatible(nom=str(item["nom"]), raison=str(item["raison"])))
    return result


def _sources_depuis_json(data: Any) -> List[Source]:
    if not isinstance(data, list):
        return []
    result = []
    for item in data:
        if isinstance(item, dict) and "url" in item and "type" in item:
            result.append(Source(url=str(item["url"]), type=str(item["type"])))
    return result


def fiche_depuis_json(data: Dict[str, Any]) -> FicheConsole:
    """Construit une `FicheConsole` depuis le JSON `console` renvoyé par le
    serveur. Lève `ValueError` (message explicite, jamais silencieux) si un
    champ dont l'absence empêcherait tout affichage sensé manque -- capturé
    par `client.py::rechercher_console` et traduit en
    `RechercheErreur("reponse_invalide")`."""
    if not isinstance(data, dict):
        raise ValueError("La fiche reçue n'est pas un objet JSON.")

    identite = data.get("identite")
    if not isinstance(identite, dict):
        raise ValueError("Champ 'identite' manquant ou invalide.")
    materiel = data.get("materiel")
    if not isinstance(materiel, dict):
        raise ValueError("Champ 'materiel' manquant ou invalide.")
    os_info = data.get("os")
    if not isinstance(os_info, dict):
        raise ValueError("Champ 'os' manquant ou invalide.")

    for champ in ("id", "statut", "signalements"):
        if champ not in data:
            raise ValueError(f"Champ obligatoire '{champ}' manquant.")
    for champ in ("nom", "fabricant"):
        if champ not in identite:
            raise ValueError(f"Champ obligatoire 'identite.{champ}' manquant.")
    for champ in ("soc", "architecture"):
        if champ not in materiel:
            raise ValueError(f"Champ obligatoire 'materiel.{champ}' manquant.")
    if "type" not in os_info:
        raise ValueError("Champ obligatoire 'os.type' manquant.")

    return FicheConsole(
        id=str(data["id"]),
        nom=str(identite["nom"]),
        fabricant=str(identite["fabricant"]),
        alias=_as_str_list(identite.get("alias")),
        soc=str(materiel["soc"]),
        architecture=str(materiel["architecture"]),
        os_type=str(os_info["type"]),
        options=_options_depuis_json(data.get("options")),
        statut=str(data["statut"]),
        signalements=int(data["signalements"]),
        incompatibles=_incompatibles_depuis_json(data.get("incompatibles")),
        liens_officiels=_as_str_list(data.get("liens_officiels")),
        licences=_as_str_list(data.get("licences")),
        restriction_commerciale=bool(data.get("restriction_commerciale", False)),
        sources=_sources_depuis_json(data.get("sources")),
        date_verification=data.get("date_verification") if isinstance(data.get("date_verification"), str) else None,
    )


__all__ = [
    "OptionConsole",
    "Incompatible",
    "Source",
    "OptionsConsole",
    "FicheConsole",
    "fiche_depuis_json",
]
