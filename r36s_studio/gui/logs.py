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

"""Emplacement du journal du worker élevé.

Utile quand l'élévation échoue silencieusement côté GUI : `osascript`
(macOS) et `pkexec`/`sudo` (Linux) n'écrivent l'erreur réelle que sur leur
propre `stderr`, jamais dans le fichier de progression du protocole (§3) —
sans ce journal, un échec comme "No module named r36s_studio" (le worker
lancé depuis un répertoire de travail qui n'a aucune raison de contenir le
projet) disparaissait complètement, remplacé par un message générique côté
GUI."""

from __future__ import annotations

import os
import platform
from pathlib import Path


def log_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    else:
        base = Path.home() / ".config"
    path = base / "r36s-studio" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def elevation_log_path() -> Path:
    """Écrasé à chaque lancement élevé — reflète toujours la dernière
    tentative, pas un historique."""
    return log_dir() / "elevation.log"


def consoles_diverses_log_path() -> Path:
    """Journal des fiches rejetées par `consoles_diverses/models.py::
    fiche_depuis_json` -- le champ en cause n'est jamais affiché à l'écran
    (le message utilisateur reste générique, `strings.py::error_reponse_
    invalide`), ce fichier est le seul endroit où le détail technique
    atterrit. Ajouté en continu (contrairement à `elevation_log_path`,
    écrasé à chaque lancement) -- une ligne par fiche rejetée, pas un seul
    incident à la fois."""
    return log_dir() / "consoles_diverses.log"


def android_log_path() -> Path:
    """Journal de l'outil « Console Android » (android/, étape 1) --
    signalé : « Impossible de joindre le serveur » affiché depuis cet
    écran alors que la même recherche fonctionne depuis Consoles diverses,
    bien que `main_window.py` construise le client avec exactement la même
    source de configuration (`AppConfig.consoles_diverses_server_url`,
    `consoles_diverses_settings_store.lire_licence()`) -- voir le test
    dédié qui compare les deux chemins d'appel. En l'absence d'un accès
    au serveur réel pour reproduire ici, ce journal consigne l'URL
    effectivement appelée et le code d'erreur reçu, pour comparer d'une
    session à l'autre plutôt que de deviner. Ajouté en continu, comme
    `consoles_diverses_log_path` -- jamais écrasé."""
    return log_dir() / "android.log"


def doublons_log_path() -> Path:
    """Journal de l'outil « Doublons de jeux » (`doublons/move.py`) --
    signalé explicitement : échec réel de déplacement vers un disque
    externe, message générique affiché sans aucun détail exploitable.
    Consigne l'exception exacte, l'étape en cause (copie, vérification,
    suppression de la source) et le chemin complet du fichier -- jamais
    affiché à l'écran (§5 vocabulaire, jamais de jargon), ce fichier est
    le seul endroit où le détail technique atterrit. Ajouté en continu,
    comme `consoles_diverses_log_path`/`android_log_path` -- jamais
    écrasé."""
    return log_dir() / "doublons.log"
