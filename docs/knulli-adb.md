# Copier des jeux sur une console KNULLI en USB (ADB)

« Copier des jeux sur ma console (USB) » : jeux et BIOS copiés sur une
console KNULLI branchée en USB, mode ADB, sans retirer la carte SD.

- Module : `r36s_studio/android/knulli.py` (aucune dépendance vers `gui/`).
- Écran : `gui/knulli_screen.py`, ouvert depuis l'écran « Console Android »
  quand la console détectée est une KNULLI.
- Threads : `gui/android_runner.py` (`KnulliPlanRunner`, `KnulliCopyRunner`).
- adb : celui du module Android (`android/adb.py::resolve_adb_path`, PATH ou
  platform-tools téléchargés, `docs/android-adb.md`).

## Relevé sur la vraie console (2026-10-19)

RG40XXV, KNULLI Scarab 20260511, Start → Paramètres de l'appareil → Mode
USB → ADB.

| Point | Constat |
|---|---|
| `adb devices -l` | `0123456789 device product:occam model:Nexus_4 device:mako` : identité ADB générique, inutilisable |
| `adb shell id` | `uid=0(root)` : déjà root, jamais `adb root` |
| `getprop` | absent (`/bin/sh: 1: getprop: not found`) |
| `/etc/os-release` | `NAME=Batocera.linux`, `VERSION=42`, `OS_NAME="knulli"`, `OS_DATE=20260511` |
| Code de sortie | `adb shell` rend **toujours 0** (ancien protocole) : chaque contrôle lit une sortie (`stat`, `curl -w`), jamais un code |
| `/userdata` | la carte SD elle-même (`/dev/mmcblk1p1`, `SDCARD`), **exFAT** (fuseblk) : pas de limite à 4 Gio, `: ? * " < > \| \\` interdits |
| Jeux / BIOS | `/userdata/roms/<système>`, `/userdata/bios` |
| Place | `df -P -B1 /userdata` (8,7 Gio libres sur 59 Gio le jour du relevé) |
| Outils | `stat`, `find -printf`, `curl` présents (GNU) |
| Débit | ~4,4 Mo/s (fichier de 20 Mio, carte exFAT via FUSE) |

## Détection

`android/adb.py::detect_connected_device` : quand `getprop` ne donne
**aucune** propriété, une seule commande de plus (`cat /etc/os-release`) ;
`DetectionResult.linux_console` est renseigné si une règle de
`knulli.LINUX_CONSOLE_RULES` correspond. Un vrai Android (propriétés lues)
n'a aucune commande de plus. Règle KNULLI : `OS_NAME=knulli`. Batocera seul
(`NAME=Batocera.linux` sans `OS_NAME=knulli`) : une ligne à ajouter dans
`LINUX_CONSOLE_RULES`, après vérification de ses dossiers.

## Systèmes : `es_systems.cfg`, pas `GET /systems`

- `GET /systems` (API d'EmulationStation) ne renvoie que les systèmes
  **qui ont déjà des jeux** (20 entrées sur la console, collections
  comprises) : copier les premiers jeux d'un système vide serait impossible.
- Lu à chaud : `/usr/share/emulationstation/es_systems.cfg` (185 systèmes,
  180 sous `/userdata/roms`), le fichier qu'EmulationStation charge :
  nom de dossier + extensions acceptées (`parse_es_systems`). Prime toujours.
- Table figée pour le tri hors connexion : `tri/data/firmware_folders.json`,
  entrée `knulli` (générée depuis ce fichier, `verified_on_hardware: true`).
  Noms qui diffèrent des autres firmwares : `wswan`, `wswanc`, `lynx`.
- Non lus : `es_systems_*.cfg` personnels de `/userdata/system/configs/
  emulationstation/` (aucun sur la console du relevé).

## Liste de jeux

L'écran compose une **liste** (`tri/selection.py::GameSelection`, composant
`gui/game_list_widget.py`, sans ADB : réutilisable par « Copier des jeux
sur la carte ») :
- « Ajouter des jeux… » (`QFileDialog.getOpenFileNames`, plusieurs
  fichiers), « Ajouter un dossier… » (sous-dossiers compris), glisser-déposer
  de fichiers et de dossiers ; ajouts répétés et dossiers mélangés ;
- même fichier ajouté deux fois (même par un dossier) : une seule ligne ;
- une ligne par jeu (fichiers liés d'un `.cue`/`.m3u` regroupés) : nom,
  taille, système (rangement ci-dessous, avec les systèmes lus sur la
  console à l'ouverture de l'écran ; « … » tant qu'ils ne le sont pas) ;
  retrait par « Retirer » ou Suppr (tout le groupe part), « Tout vider » ;
- choisir un `.cue`/`.m3u` ajoute ses fichiers (en chaîne) ; choisir un
  `.bin` cité par un manifeste du même dossier ajoute ce manifeste ;
- dernier dossier ouvert : `config.json::last_games_folder` (point de départ
  des sélecteurs, rien d'autre).

Chaque fichier garde son dossier de départ : le dossier ajouté, ou le
dossier parent d'un fichier choisi seul (un `.sfc` choisi dans `snes/` va
dans `snes`).

## Rangement (`build_copy_plan_from`, lecture seule)

1. Le premier dossier du chemin (en partant du haut, dossier de départ compris)
   dont le nom est un dossier de la console (`psx`, `snes`… casse ignorée)
   donne le système ; le reste du chemin est gardé dessous. Un dossier
   `bios` va dans `/userdata/bios`.
2. Sinon, l'identification du tri (`tri/identify.py`, extension et en-tête)
   et la table figée KNULLI ; le fichier va à la racine du dossier du système.
3. Sinon : « non reconnu », ignoré et signalé.

Signalés et ignorés : format que le système n'accepte pas (ex. `.7z` pour
`psx`) ; un `.bin` cité par un `.cue` accepté suit son `.cue` (même
regroupement que le tri, `_linked_groups`) ; disque incomplet ; deux
fichiers vers le même nom (casse ignorée, exFAT). Nom interdit en exFAT :
renommé (caractère remplacé par `_`, affiché dans le résumé), sauf dans un
jeu en plusieurs fichiers (le `.cue` ne retrouverait plus son `.bin`) :
ignoré et signalé.

## Avant la copie

- Fichiers déjà présents : `find <dossiers visés> -type f -printf`. Chacun
  fait l'objet d'une question : **Ignorer / Remplacer / Tout ignorer**.
  Jamais remplacé sans « Remplacer ».
- Place : total à copier (un fichier remplacé libère l'ancien) + **500 Mio**
  de marge. Ne tient pas : bouton de copie désactivé, message clair, détail
  par système ; revérifié par `copy_plan` juste avant la première copie
  (`NotEnoughSpace`).

## Copie (`copy_plan`)

Fichier par fichier : `mkdir -p`, `adb push` vers
`<dossier>/.r36s_studio_copie.partial`, taille relevée par `stat` toutes les
0,5 s (progression réelle, `adb push` n'en donne pas hors terminal), taille
finale comparée, puis `mv -f` vers le nom final et nouvelle vérification.
Annuler : `adb push` arrêté, fichier temporaire supprimé. Un fichier qui ne
grossit plus pendant 60 s : abandonné (`stalled`). Un fichier apparu depuis
le résumé n'est jamais écrasé (`exists`). `_check_remote` refuse tout chemin
hors de `/userdata/roms/<dossier>/` et `/userdata/bios/`, ou contenant `..`.

## Rafraîchir la liste des jeux

API d'EmulationStation sur `127.0.0.1:1234` côté console (jamais de port
ouvert sur le PC) : `adb shell curl`. `/runningGame` répond **201** sans jeu
en cours (200 avec un jeu) ; `/reloadgames` répond 200. Après la copie,
`/reloadgames` seulement si `/runningGame` a répondu 201 ; sinon le
résultat dit de faire « Mettre à jour la liste des jeux » dans le menu.
Essai unique sur la console le 2026-10-19 : 200 immédiat, EmulationStation
toujours joignable après.

## Vérifié sur la console

Parcours complet depuis l'app (0.1.17) sur la RG40XXV, 2026-10-19 : jeux
copiés en USB (ADB), puis affichés par EmulationStation après le
rafraîchissement automatique (`/reloadgames`), sans redémarrage.

## Points ouverts

- Console débranchée en pleine copie : fichier temporaire laissé sur la
  carte (supprimé à la prochaine copie dans ce dossier).
