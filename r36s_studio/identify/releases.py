"""Pages des releases officielles pour la R36S (§4.6, étape C du mode
expert -- choix du firmware au flash, `identify/firmware_catalog.py`).
Ni dArkOS ni EmuELEC n'ont d'assets attachés de façon exploitable
directement aux releases GitHub (contrairement à ROCKNIX, `identify/
rocknix.py`) -- rien à automatiser au-delà de l'ouverture de la page
dans le navigateur ; l'utilisateur télécharge lui-même, puis choisit le
fichier obtenu."""

from __future__ import annotations

DARKOS_R36S_RELEASES_URL = "https://github.com/southoz/dArkOSRE-R36/releases"

# Consoles clones (`identify/__init__.py::CLONE_DTB_FILENAMES`) : les
# images ArkOS/ROCKNIX standard ne démarrent pas sur ce matériel, EmuELEC
# lui fonctionne (confirmé sur du vrai matériel). Même dépôt officiel du
# projet -- pas de correspondance d'assets par SoC (RK3326) vérifiée à ce
# jour, contrairement à ROCKNIX.
EMUELEC_R36S_RELEASES_URL = "https://github.com/EmuELEC/EmuELEC/releases"
