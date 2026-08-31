"""Configuration utilisateur persistée (§6) : `~/.config/r36s-studio/
config.json` (`%APPDATA%\\r36s-studio\\config.json` sous Windows, même
convention que `gui/logs.py:log_dir()`). Contient uniquement des
préférences locales -- jamais de secret (§9).

Aujourd'hui : le mode d'interface choisi (assisté/expert, §5 mode
assisté), mémorisé d'un lancement à l'autre. Un fichier absent ou
corrompu retombe silencieusement sur les valeurs par défaut plutôt que de
lever -- une préférence perdue n'est jamais bloquante, contrairement à une
détection de carte ratée (§4.5), mais le principe est le même."""

from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

DEFAULT_UI_MODE = "assisted"
_VALID_UI_MODES = {"assisted", "expert"}

# Firmware choisi pour l'étape de flash (§4.6 étape C / §5 mode assisté
# étape 5) : "arkos" (dArkOS, la configuration classique), "rocknix"
# (système plus récent, transfert de jeux par USB intégré), ou "emuelec"
# (consoles clones -- ArkOS/ROCKNIX standard n'y démarrent pas, §5 mode
# assisté étape 2, `identify/__init__.py::CLONE_DTB_FILENAMES`). Mémorisé
# d'un lancement à l'autre comme `ui_mode`, avec le même principe de repli
# silencieux sur la valeur par défaut.
DEFAULT_FIRMWARE = "arkos"
_VALID_FIRMWARES = {"arkos", "rocknix", "emuelec"}


@dataclass
class AppConfig:
    ui_mode: str = DEFAULT_UI_MODE
    firmware: str = DEFAULT_FIRMWARE
    # Archives BOOT/EASYROMS déjà extraites, par empreinte de carte source
    # (§5 mode assisté, `safety.card_fingerprint`) : { empreinte: { "BOOT"
    # ou "EASYROMS": {"path": ..., "created_at": ISO8601} } }. Permet au
    # parcours guidé de proposer de réutiliser une sauvegarde existante
    # plutôt que de tout recopier à chaque nouveau passage sur la même
    # carte -- EASYROMS en particulier peut représenter plusieurs Go
    # recopiés inutilement. Simples dicts (pas une dataclass imbriquée) :
    # `json.loads` ne recrée de toute façon que des dicts, autant garder
    # une seule forme des deux côtés plutôt que de convertir.
    archive_records: Dict[str, Dict[str, Dict[str, str]]] = field(default_factory=dict)


def config_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    else:
        base = Path.home() / ".config"
    path = base / "r36s-studio"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.json"


def load_config() -> AppConfig:
    path = config_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return AppConfig()

    ui_mode = raw.get("ui_mode")
    if ui_mode not in _VALID_UI_MODES:
        ui_mode = DEFAULT_UI_MODE
    firmware = raw.get("firmware")
    if firmware not in _VALID_FIRMWARES:
        firmware = DEFAULT_FIRMWARE
    archive_records = _normalize_archive_records(raw.get("archive_records"))
    return AppConfig(ui_mode=ui_mode, firmware=firmware, archive_records=archive_records)


def _normalize_archive_records(raw) -> Dict[str, Dict[str, Dict[str, str]]]:
    """Valide la forme de `archive_records` lue depuis le JSON -- un
    fichier corrompu ou modifié à la main ne doit jamais faire planter le
    chargement de la configuration (même principe que `ui_mode`/
    `firmware` ci-dessus) : toute entrée qui ne correspond pas exactement
    à la forme attendue est simplement ignorée plutôt que de faire
    échouer le chargement entier."""
    if not isinstance(raw, dict):
        return {}
    normalized: Dict[str, Dict[str, Dict[str, str]]] = {}
    for fingerprint, labels in raw.items():
        if not isinstance(fingerprint, str) or not isinstance(labels, dict):
            continue
        normalized_labels: Dict[str, Dict[str, str]] = {}
        for label, record in labels.items():
            if (
                isinstance(label, str)
                and isinstance(record, dict)
                and isinstance(record.get("path"), str)
                and isinstance(record.get("created_at"), str)
            ):
                normalized_labels[label] = {"path": record["path"], "created_at": record["created_at"]}
        if normalized_labels:
            normalized[fingerprint] = normalized_labels
    return normalized


def save_config(config: AppConfig) -> None:
    path = config_path()
    path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False), encoding="utf-8")


def get_archive_record(config: AppConfig, fingerprint: Optional[str], label: str) -> Optional[Dict[str, str]]:
    """Sauvegarde déjà connue (`{"path", "created_at"}`) pour `label`
    (`BOOT_LABEL`/`EASYROMS_LABEL`, `partitions.locate`) sur la carte
    d'empreinte `fingerprint` -- `None` si `fingerprint` est `None`
    (empreinte non calculable) ou si rien n'est encore mémorisé pour
    cette combinaison. Ne vérifie pas que le chemin existe encore sur le
    disque -- à la charge de l'appelant (l'utilisateur a pu déplacer ou
    supprimer l'archive depuis)."""
    if fingerprint is None:
        return None
    return config.archive_records.get(fingerprint, {}).get(label)


def set_archive_record(config: AppConfig, fingerprint: str, label: str, path: str, created_at: Optional[datetime] = None) -> None:
    """Mémorise `path` comme dernière sauvegarde `label` connue pour la
    carte d'empreinte `fingerprint` -- écrase silencieusement un
    enregistrement précédent pour la même combinaison (une nouvelle
    extraction remplace l'ancienne référence, jamais les deux gardées à
    la fois). N'écrit rien sur le disque : appelle `save_config` toi-même
    après, comme pour `ui_mode`/`firmware`."""
    timestamp = (created_at or datetime.now()).isoformat()
    config.archive_records.setdefault(fingerprint, {})[label] = {"path": path, "created_at": timestamp}
