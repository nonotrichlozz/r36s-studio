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
on n'en ajoute pas pour un schéma de cette taille) : seuls `id`,
`identite.nom` et `statut` sont indispensables à tout affichage sensé (un
titre, une clé, un badge vérifié/non vérifié) -- leur absence fait lever
`ValueError` (le nom du champ en cause est d'abord consigné dans le journal
de l'app, jamais affiché à l'écran, §CLAUDE.md du package -- voir
`_journaliser_fiche_rejetee` ci-dessous), capturée par `client.py` et
traduite en `RechercheErreur("reponse_invalide")`.

**Une fiche générée par IA (`statut: "non_verifie"`) peut légitimement
omettre ou ajouter des champs** par rapport à une fiche vérifiée à la main
-- champ par champ :
- Tout le reste du schéma connu (`fabricant`, `materiel.soc`/
  `materiel.architecture`, `os.type`, `signalements`, `incompatibles`,
  `licences`, `sources`, `liens_officiels`, `date_verification`, et les
  booléens "absents-si-faux" de chaque option) retombe silencieusement sur
  une valeur par défaut (`"inconnu"`/`0`/vide/`False`) quand il est absent
  ou malformé, jamais sur une exception -- une fiche par ailleurs
  exploitable ne doit pas être rejetée pour un champ annexe.
- Tout champ que ce module ne connaît pas du tout (`modele_ia`,
  `sources_collectees`, `recherche_web`, `licences_a_verifier` au niveau
  fiche...) est simplement ignoré -- ce parsing ne lit que les clés dont il
  a besoin, il ne valide jamais qu'aucune autre clé n'existe."""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Dict, List, NoReturn, Optional

from r36s_studio.gui import logs as gui_logs


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


def _str_ou_defaut(value: Any, defaut: str) -> str:
    if isinstance(value, str) and value:
        return value
    return defaut


def _signalements_ou_zero(value: Any) -> int:
    """`signalements` est optionnel depuis qu'une fiche IA peut l'omettre --
    une valeur absente ou du mauvais type retombe sur 0 plutôt que de
    rejeter toute la fiche pour ce seul champ annexe."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _journaliser_fiche_rejetee(champ: str) -> None:
    """Consigne le champ en cause dans le journal de l'app (`gui/logs.py::
    consoles_diverses_log_path`) -- jamais à l'écran, l'utilisateur ne voit
    que le message générique `error_reponse_invalide` (§CLAUDE.md du
    package). Best-effort : un journal inaccessible (droits, disque plein)
    ne doit jamais empêcher le rejet lui-même de remonter normalement."""
    try:
        chemin = gui_logs.consoles_diverses_log_path()
        horodatage = datetime.datetime.now().isoformat(timespec="seconds")
        with open(chemin, "a", encoding="utf-8") as fichier:
            fichier.write(f"{horodatage} fiche rejetée : champ '{champ}' manquant ou invalide.\n")
    except OSError:
        pass


def _rejeter(champ: str, message: str) -> NoReturn:
    _journaliser_fiche_rejetee(champ)
    raise ValueError(message)


def fiche_depuis_json(data: Dict[str, Any]) -> FicheConsole:
    """Construit une `FicheConsole` depuis le JSON `console` renvoyé par le
    serveur. Seuls `id`, `identite.nom` et `statut` sont indispensables --
    leur absence lève `ValueError` (message explicite, jamais silencieux ;
    le nom du champ est d'abord consigné dans le journal de l'app, jamais
    affiché à l'écran) capturée par `client.py::rechercher_console` et
    traduite en `RechercheErreur("reponse_invalide")`. Tout le reste du
    schéma connu retombe sur une valeur par défaut quand il est absent ou
    malformé (une fiche générée par IA peut légitimement l'omettre), et
    tout champ inconnu est simplement ignoré -- voir le docstring du
    module."""
    if not isinstance(data, dict):
        _rejeter("data", "La fiche reçue n'est pas un objet JSON.")

    if not isinstance(data.get("id"), str) or not data["id"]:
        _rejeter("id", "Champ obligatoire 'id' manquant.")

    identite = data.get("identite")
    if not isinstance(identite, dict):
        identite = {}
    nom = identite.get("nom")
    if not isinstance(nom, str) or not nom:
        _rejeter("identite.nom", "Champ obligatoire 'identite.nom' manquant.")

    if not isinstance(data.get("statut"), str) or not data["statut"]:
        _rejeter("statut", "Champ obligatoire 'statut' manquant.")

    materiel = data.get("materiel")
    if not isinstance(materiel, dict):
        materiel = {}
    os_info = data.get("os")
    if not isinstance(os_info, dict):
        os_info = {}

    return FicheConsole(
        id=str(data["id"]),
        nom=nom,
        fabricant=_str_ou_defaut(identite.get("fabricant"), "inconnu"),
        alias=_as_str_list(identite.get("alias")),
        soc=_str_ou_defaut(materiel.get("soc"), "inconnu"),
        architecture=_str_ou_defaut(materiel.get("architecture"), "inconnu"),
        os_type=_str_ou_defaut(os_info.get("type"), "inconnu"),
        options=_options_depuis_json(data.get("options")),
        statut=str(data["statut"]),
        signalements=_signalements_ou_zero(data.get("signalements")),
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
