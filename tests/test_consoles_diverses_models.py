"""Tests de `consoles_diverses/models.py` -- parsing défensif d'une fiche
console conforme à `r36s-studio-catalogue/schema/console.schema.json`. Le
JSON de référence ci-dessous reprend fidèlement
`r36s-studio-catalogue/consoles/sf3000hd.json` (lu en lecture seule lors de
la conception de cette fonctionnalité)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from r36s_studio.consoles_diverses.models import fiche_depuis_json

FIXTURE_REPONSE_R36S = Path(__file__).parent / "fixtures_reponse_r36s.json"


def _fiche_sf3000hd() -> dict:
    return {
        "id": "sf3000hd",
        "identite": {"nom": "SF3000HD", "fabricant": "Data Frog", "alias": []},
        "materiel": {"soc": "HiChip C3100", "architecture": "MIPS"},
        "os": {"type": "proprietaire (H.OS / iCube / cubegm)"},
        "options": {
            "frontend": [
                {
                    "nom": "TreeFrog UI",
                    "description": "Interface/frontend personnalisé pour SF3000HD et consoles apparentées.",
                    "url": "https://github.com/tzubertowski/TreeFrogUI",
                    "licence": "CC-BY-NC-SA-4.0",
                    "restriction_commerciale": True,
                    "source_url": "https://github.com/tzubertowski/TreeFrogUI",
                }
            ],
            "systeme_cfw": [],
            "firmware_origine": [
                {
                    "nom": "Sauvegarde du firmware d'origine",
                    "description": "Procédure de sauvegarde variable selon le modèle exact de console.",
                    "url": "https://github.com/tzubertowski/TreeFrogUI/blob/main/install.md",
                    "source_url": "https://github.com/tzubertowski/TreeFrogUI/blob/main/install.md",
                }
            ],
            "mises_a_jour": [
                {
                    "nom": "update.zip officiel TreeFrog UI",
                    "description": "Copier update.zip à la racine de la carte SD pour mettre à jour TreeFrog UI.",
                    "source_url": "https://github.com/tzubertowski/TreeFrogUI",
                    "licence": "CC-BY-NC-SA-4.0",
                    "restriction_commerciale": True,
                }
            ],
        },
        "incompatibles": [
            {"nom": "ArkOS", "raison": "ARM uniquement, flasher une image ARM corrompt la carte"},
            {"nom": "EmuELEC", "raison": "ARM uniquement, flasher une image ARM corrompt la carte"},
        ],
        "liens_officiels": [],
        "licences": ["CC-BY-NC-SA-4.0"],
        "restriction_commerciale": True,
        "sources": [
            {"url": "https://github.com/tzubertowski/TreeFrogUI", "type": "github"},
        ],
        "statut": "verifie",
        "date_verification": "2026-09-17",
        "signalements": 0,
    }


def test_fiche_depuis_json_parses_identity_and_material():
    fiche = fiche_depuis_json(_fiche_sf3000hd())

    assert fiche.id == "sf3000hd"
    assert fiche.nom == "SF3000HD"
    assert fiche.fabricant == "Data Frog"
    assert fiche.alias == []
    assert fiche.soc == "HiChip C3100"
    assert fiche.architecture == "MIPS"
    assert fiche.os_type == "proprietaire (H.OS / iCube / cubegm)"
    assert fiche.statut == "verifie"
    assert fiche.verifiee is True
    assert fiche.signalements == 0
    assert fiche.date_verification == "2026-09-17"


def test_fiche_depuis_json_parses_options_by_category():
    fiche = fiche_depuis_json(_fiche_sf3000hd())

    assert len(fiche.options.frontend) == 1
    assert fiche.options.frontend[0].nom == "TreeFrog UI"
    assert fiche.options.frontend[0].licence == "CC-BY-NC-SA-4.0"
    assert fiche.options.frontend[0].restriction_commerciale is True
    assert fiche.options.systeme_cfw == []
    assert len(fiche.options.firmware_origine) == 1
    assert len(fiche.options.mises_a_jour) == 1


def test_fiche_depuis_json_parses_incompatibles_and_sources():
    fiche = fiche_depuis_json(_fiche_sf3000hd())

    assert [i.nom for i in fiche.incompatibles] == ["ArkOS", "EmuELEC"]
    assert fiche.sources[0].url == "https://github.com/tzubertowski/TreeFrogUI"
    assert fiche.sources[0].type == "github"
    assert fiche.licences == ["CC-BY-NC-SA-4.0"]
    assert fiche.restriction_commerciale is True


def test_fiche_a_une_restriction_commerciale_true_from_top_level_field():
    fiche = fiche_depuis_json(_fiche_sf3000hd())

    assert fiche.a_une_restriction_commerciale is True


def test_fiche_a_une_restriction_commerciale_true_from_option_only():
    data = _fiche_sf3000hd()
    data["restriction_commerciale"] = False
    fiche = fiche_depuis_json(data)

    # L'option "frontend" porte toujours restriction_commerciale=True.
    assert fiche.a_une_restriction_commerciale is True


def test_fiche_a_une_restriction_commerciale_false_when_absent_everywhere():
    data = _fiche_sf3000hd()
    data["restriction_commerciale"] = False
    data["options"]["frontend"][0]["restriction_commerciale"] = False
    data["options"]["mises_a_jour"][0]["restriction_commerciale"] = False
    fiche = fiche_depuis_json(data)

    assert fiche.a_une_restriction_commerciale is False


def test_fiche_depuis_json_defaults_optional_fields_when_absent():
    data = {
        "id": "console-minimale",
        "identite": {"nom": "Console minimale", "fabricant": "Inconnu", "alias": []},
        "materiel": {"soc": "inconnu", "architecture": "inconnu"},
        "os": {"type": "inconnu"},
        "options": {"frontend": [], "systeme_cfw": [], "firmware_origine": [], "mises_a_jour": []},
        "statut": "non_verifie",
        "signalements": 0,
    }

    fiche = fiche_depuis_json(data)

    assert fiche.incompatibles == []
    assert fiche.liens_officiels == []
    assert fiche.licences == []
    assert fiche.restriction_commerciale is False
    assert fiche.sources == []
    assert fiche.date_verification is None
    assert fiche.verifiee is False


def test_fiche_depuis_json_defaults_missing_options_object_to_empty():
    data = {
        "id": "console-sans-options",
        "identite": {"nom": "X", "fabricant": "Y", "alias": []},
        "materiel": {"soc": "inconnu", "architecture": "inconnu"},
        "os": {"type": "inconnu"},
        "statut": "non_verifie",
        "signalements": 0,
    }

    fiche = fiche_depuis_json(data)

    assert fiche.options.frontend == []
    assert fiche.options.systeme_cfw == []
    assert fiche.options.firmware_origine == []
    assert fiche.options.mises_a_jour == []


def test_fiche_depuis_json_ignores_malformed_option_entries():
    data = _fiche_sf3000hd()
    data["options"]["frontend"].append({"nom": "Sans description ni source"})

    fiche = fiche_depuis_json(data)

    assert len(fiche.options.frontend) == 1


@pytest.mark.parametrize(
    "champ_manquant",
    ["id", "statut"],
)
def test_fiche_depuis_json_raises_when_top_level_field_missing(champ_manquant):
    data = _fiche_sf3000hd()
    del data[champ_manquant]

    with pytest.raises(ValueError):
        fiche_depuis_json(data)


def test_fiche_depuis_json_raises_when_identite_nom_missing():
    data = _fiche_sf3000hd()
    del data["identite"]["nom"]

    with pytest.raises(ValueError):
        fiche_depuis_json(data)


def test_fiche_depuis_json_raises_when_not_a_dict():
    with pytest.raises(ValueError):
        fiche_depuis_json("pas un objet")  # type: ignore[arg-type]


# --- Tolérance aux fiches IA (seuls id/identite.nom/statut restent -------
# --- obligatoires ; le reste du schéma connu retombe sur une valeur -------
# --- par défaut, tout champ inconnu est ignoré) ---------------------------


def test_fiche_depuis_json_defaults_signalements_when_missing():
    data = _fiche_sf3000hd()
    del data["signalements"]

    fiche = fiche_depuis_json(data)

    assert fiche.signalements == 0


def test_fiche_depuis_json_defaults_signalements_when_wrong_type():
    data = _fiche_sf3000hd()
    data["signalements"] = "pas un nombre"

    fiche = fiche_depuis_json(data)

    assert fiche.signalements == 0


def test_fiche_depuis_json_defaults_fabricant_when_identite_missing_it():
    data = _fiche_sf3000hd()
    del data["identite"]["fabricant"]

    fiche = fiche_depuis_json(data)

    assert fiche.fabricant == "inconnu"


def test_fiche_depuis_json_defaults_soc_and_architecture_when_materiel_missing():
    data = _fiche_sf3000hd()
    del data["materiel"]

    fiche = fiche_depuis_json(data)

    assert fiche.soc == "inconnu"
    assert fiche.architecture == "inconnu"


def test_fiche_depuis_json_defaults_os_type_when_os_missing():
    data = _fiche_sf3000hd()
    del data["os"]

    fiche = fiche_depuis_json(data)

    assert fiche.os_type == "inconnu"


def test_fiche_depuis_json_ignores_unknown_fields():
    data = _fiche_sf3000hd()
    data["modele_ia"] = "gemini-3.5-flash-lite"
    data["connecteurs"] = {"github": "ok"}
    data["sources_collectees"] = True
    data["recherche_web"] = False
    data["licences_a_verifier"] = True
    data["detection_sd"] = {"quelque_chose": "d_inattendu"}

    fiche = fiche_depuis_json(data)  # ne lève pas

    assert fiche.id == "sf3000hd"


# --- Journalisation d'une fiche rejetée (jamais à l'écran) -----------------


def test_fiche_depuis_json_logs_the_offending_field_name_when_rejected(tmp_path):
    log_path = tmp_path / "consoles_diverses.log"
    data = _fiche_sf3000hd()
    del data["statut"]

    with patch(
        "r36s_studio.consoles_diverses.models.gui_logs.consoles_diverses_log_path",
        return_value=log_path,
    ):
        with pytest.raises(ValueError):
            fiche_depuis_json(data)

    contenu = log_path.read_text(encoding="utf-8")
    assert "statut" in contenu


def test_fiche_depuis_json_logging_failure_does_not_prevent_the_rejection(tmp_path):
    data = _fiche_sf3000hd()
    del data["id"]

    with patch(
        "r36s_studio.consoles_diverses.models.gui_logs.consoles_diverses_log_path",
        side_effect=OSError("disque plein"),
    ):
        with pytest.raises(ValueError):
            fiche_depuis_json(data)


# --- Régression : vraie réponse serveur pour la R36S (fiche IA, non --------
# --- vérifiée) qui échouait auparavant avec "réponse inattendue" -----------
# --- (reponse_invalide) faute de `signalements`. ---------------------------


def test_fiche_depuis_json_parses_the_real_r36s_ia_response_fixture():
    payload = json.loads(FIXTURE_REPONSE_R36S.read_text(encoding="utf-8-sig"))

    fiche = fiche_depuis_json(payload["console"])

    assert fiche.id == "r36s"
    assert fiche.nom == "R36S"
    assert fiche.fabricant == "inconnu"
    assert fiche.soc.startswith("Rockchip RK3326")
    assert fiche.os_type == "Linux"
    assert fiche.statut == "non_verifie"
    assert fiche.verifiee is False
    assert fiche.signalements == 0  # absent de la fixture, valeur par défaut
    assert fiche.date_verification is None  # absent de la fixture
    assert len(fiche.options.frontend) == 1
    assert fiche.options.frontend[0].nom == "EmulationStation"
    assert fiche.options.frontend[0].licence_a_verifier is True
    assert fiche.licences == ["CC-BY-NC-4.0"]
    assert fiche.sources[0].url == "https://github.com/dov/r36s-programming"
