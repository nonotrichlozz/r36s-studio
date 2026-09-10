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
