# Copyright (c) 2026 Arnaud
# Licence : PolyForm Strict 1.0.0, voir LICENSE

"""Catalogue des firmwares proposés à l'étape de flash (§4.6, mode expert
uniquement -- le parcours de clonage du mode assisté n'a pas de choix de
firmware, il restaure la propre sauvegarde de l'utilisateur, §5). Une
entrée par choix radio de `FileDialog`.

Centralise ce qui était auparavant éparpillé en plusieurs branches à
trois choix codées en dur dans `gui/screens.py`/`gui/main_window.py`
(`_on_firmware_toggled`, `_update_firmware_buttons_visibility`, le repli
`{"rocknix": ..., "emuelec": ...}` de `set_mode`, et le ternaire
`_on_releases_requested`) -- nécessaire dès qu'on dépasse trois choix,
chaque branchement en dur devenant un endroit de plus où un nouveau
firmware peut être oublié en silence (cas réel confirmé en lisant ce
code : `_on_releases_requested` retombait déjà sur l'URL ArkOS pour tout
firmware non reconnu, avant ce module).

Seul ROCKNIX a un téléchargement automatique (images attachées
directement aux releases GitHub, `identify/rocknix.py`) -- volontairement
**pas généralisé ici** : vérifié directement sur les pages de releases
avant d'ajouter ce catalogue, les releases officielles d'AmberELEC ne
publient que des images taguées RG351/RG552 (aucun asset RK3326/R36S), et
celles d'EmuELEC ne publient que des images Amlogic (aucun asset RK3326/
R36S non plus) -- ni l'une ni l'autre n'a donc la structure « une image
par SoC » qui rend le téléchargement automatique de ROCKNIX possible.
Toutes les entrées ajoutées ici (AmberELEC, MinUI, R36Droid, andr36oid)
sont donc en lien manuel, comme ArkOS -- `releases_url=None` reste réservé
au seul cas d'automatisation existant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .releases import DARKOS_R36S_RELEASES_URL, DARKOSEN_R36S_RELEASES_URL, EMUELEC_R36S_RELEASES_URL

# Vérifiées manuellement (WebFetch sur les pages de releases réelles)
# avant l'ajout de ce catalogue -- pas de nouveau module de téléchargement
# automatique pour elles (voir docstring de module) :
# - AmberELEC : conçu pour RG351/RG552 (même famille de SoC RK3326 que la
#   R36S, mais compatibilité R36S elle-même non confirmée).
# - MinUI : le dépôt officiel (`shauninman/MinUI`) ne prend pas en charge
#   la R36S ; le portage actif pour R36S vit dans un fork communautaire
#   (`Turro75/MyMinUI`, releases R36S régulières en 2026).
# - R36Droid/andr36oid : deux portages Android (LineageOS) indépendants
#   pour R36S/RK3326, tous deux communautaires et expérimentaux.
AMBERELEC_R36S_RELEASES_URL = "https://github.com/AmberELEC/AmberELEC/releases"
MINUI_R36S_RELEASES_URL = "https://github.com/Turro75/MyMinUI/releases"
R36DROID_RELEASES_URL = "https://github.com/creeperxyz86/R36Droid/releases"
ANDR36OID_RELEASES_URL = "https://github.com/andr36oid/releases/releases"


@dataclass(frozen=True)
class FirmwareEntry:
    id: str
    title_key: str
    desc_key: str
    status: str  # "maintained" | "archived" | "experimental"
    is_clone_safe: bool = False
    # Constaté sur du vrai matériel : Windows ne sait lire aucune des
    # partitions d'une image Android (boot/system/vendor/userdata...) et
    # propose de les formater dès qu'il les découvre -- une par partition
    # illisible (quatre boîtes « Vous devez formater le disque » observées
    # pour R36Droid), qu'un débutant risque d'accepter et de détruire ce
    # qui vient d'être écrit (§4.6/§5 : `MainWindow` en tire un
    # avertissement explicite dans le journal après le flash, et un
    # `--eject-after` best-effort côté CLI).
    is_android: bool = False
    # Clé `gui/strings.py` d'une consigne propre au firmware, ajoutée au
    # journal après un flash réussi en mode expert (`MainWindow.
    # _on_worker_finished`), en plus des avertissements de formatage : la
    # description lue avant le flash est oubliée plusieurs minutes après.
    post_flash_log_key: Optional[str] = None
    # None = ROCKNIX (téléchargement automatique, identify/rocknix.py) --
    # le seul cas à ce jour, voir docstring de module.
    releases_url: Optional[str] = None


# ArkOS : seul le projet d'origine est archivé (lecture seule depuis
# décembre 2025). L'entrée pointe vers dArkOS (southoz/dArkOSRE-R36),
# vérifié sur l'API GitHub le 2026-09-25 : non archivé, dernière release
# `dArkOSRE-R36(03082026)` publiée le 2026-03-10 (tag au format
# MMJJAAAA, soit le 8 mars et non le 3 août), dernier commit le
# 2026-05-01, R36S et clones G80CA/R36 Max/Ultra en cours d'ajout --
# d'où « maintenu ». Toujours en lien manuel : aucune image attachée aux
# releases (Mega, Google Drive, OneDrive, torrent).
FIRMWARE_CATALOG: Tuple[FirmwareEntry, ...] = (
    FirmwareEntry(
        "arkos",
        "file_firmware_arkos_title",
        "file_firmware_arkos_desc",
        status="maintained",
        releases_url=DARKOS_R36S_RELEASES_URL,
    ),
    # dArkOSen : « maintenu » (vérifié le 2026-09-29, voir `identify/
    # releases.py::DARKOSEN_R36S_RELEASES_URL`). Jamais `is_clone_safe` :
    # son README l'exclut explicitement de tout clone. Lien manuel : l'image
    # est attachée à la release mais en 7-Zip découpé, que l'app ne
    # décompresse pas (téléchargement automatique à part, non fait).
    FirmwareEntry(
        "darkosen",
        "file_firmware_darkosen_title",
        "file_firmware_darkosen_desc",
        status="maintained",
        post_flash_log_key="flash_darkosen_model_selection_note",
        releases_url=DARKOSEN_R36S_RELEASES_URL,
    ),
    FirmwareEntry(
        "rocknix",
        "file_firmware_rocknix_title",
        "file_firmware_rocknix_desc",
        status="maintained",
        releases_url=None,
    ),
    FirmwareEntry(
        "emuelec",
        "file_firmware_emuelec_title",
        "file_firmware_emuelec_desc",
        status="experimental",
        is_clone_safe=True,
        releases_url=EMUELEC_R36S_RELEASES_URL,
    ),
    FirmwareEntry(
        "amberelec",
        "file_firmware_amberelec_title",
        "file_firmware_amberelec_desc",
        status="experimental",
        releases_url=AMBERELEC_R36S_RELEASES_URL,
    ),
    FirmwareEntry(
        "minui",
        "file_firmware_minui_title",
        "file_firmware_minui_desc",
        status="experimental",
        releases_url=MINUI_R36S_RELEASES_URL,
    ),
    FirmwareEntry(
        "r36droid",
        "file_firmware_r36droid_title",
        "file_firmware_r36droid_desc",
        status="experimental",
        is_android=True,
        releases_url=R36DROID_RELEASES_URL,
    ),
    FirmwareEntry(
        "andr36oid",
        "file_firmware_andr36oid_title",
        "file_firmware_andr36oid_desc",
        status="experimental",
        is_android=True,
        releases_url=ANDR36OID_RELEASES_URL,
    ),
)

FIRMWARE_BY_ID: Dict[str, FirmwareEntry] = {entry.id: entry for entry in FIRMWARE_CATALOG}

__all__ = ["FirmwareEntry", "FIRMWARE_CATALOG", "FIRMWARE_BY_ID"]
