# Bot Telegram (`r36s_studio/bot/`)

Interface Telegram de R36S Studio, pilotée depuis un téléphone, pour une
machine Linux où la GUI est impossible (Eee PC i686 sous antiX : PySide6
n'existe pas en 32 bits). Ajouté le 2026-10-20.

## Règles

- **Même cœur que la GUI, jamais une réimplémentation.** Le bot appelle les
  modules sans Qt extraits des threads de la GUI :
  - `doublons/run.py` : `run_scan`, `run_move` (politique « ignorer ce
    fichier », plus de question après `AUTO_SKIP_AFTER` échecs de même
    raison), `default_units_to_move` (sélection par défaut de l'écran de
    résultats), `prune_moved`, `preferred_destination` ;
  - `tri/run.py` : `run_plan`, `run_apply` (aperçu et application d'un
    tri/filtre/conversion) ;
  - `identify/firmware_download.py` : `list_rocknix_variants`,
    `resolve_auto_download` (KNULLI, SHA-256 exigée), `download_firmware`.
  Forme commune : fonctions synchrones, `on_progress`, `should_cancel`,
  codes d'erreur de `strings.py::_ERROR_MESSAGE_KEYS` (ou `tri_error_*`).
  `gui/doublons_runner.py`, `gui/tri_runner.py`, `gui/partition_runner.py`
  (`RocknixListRunner`, `RocknixDownloadRunner`) et
  `consoles_diverses/search_runner.py::FirmwareResolveRunner` ne font plus
  que relayer ces fonctions vers des signaux Qt.
- **Import absolu** : rien sous `r36s_studio.gui`, ni PySide6 (vérifié par
  `tests/test_bot_imports.py`, PySide6 rendu introuvable). Pour ça,
  `gui/strings.py`, `gui/strings_en.py` et `gui/logs.py` (déjà sans Qt) ont
  été déplacés à la racine du paquet (`r36s_studio/strings.py`…) ; les
  anciens noms restent des alias (`sys.modules[__name__] = module`, même
  objet : imports et `patch` existants inchangés). `doublons/move.py` et
  `consoles_diverses/{client,models}.py` importent désormais
  `r36s_studio.logs`.
- **Dépendance** : `requirements-bot.txt` (`python-telegram-bot>=21,<23`),
  jamais `requirements.txt` (PySide6). La chaîne d'imports du bot ne charge
  ni py7zr ni cryptography.
- **Suppression jamais directe** : comme la GUI, les doublons sont **mis de
  côté** (dossier `_doublons` ou dernière destination choisie), jamais
  supprimés ; le bot liste ce qu'il a trouvé puis demande confirmation par
  deux boutons en ligne (§2 n°6). Même chose pour le filtre (`_hors_filtre`).
  Le mode simulation de `config.json` s'applique. « Tout annuler » reste
  dans la GUI.
- **Pas de flash** : le bot télécharge un système (dans
  `~/Documents/R36S Studio/Firmwares/`), jamais d'écriture sur une carte.
- **Vocabulaire (§5)** : messages sans jargon ; chemins et messages bruts du
  cœur sur une ligne à part (`bot_detail` « Détail : … », `bot_path`
  « 📁 … »). Chaînes `bot_*` dans `strings.py`/`strings_en.py`.

## Installation (machine sans écran)

1. `pip install -r requirements-bot.txt` (rien d'autre : le cœur n'utilise
   que la bibliothèque standard).
2. Créer le bot avec BotFather, récupérer le jeton.
3. `python -m r36s_studio.bot` une première fois : crée un modèle
   `~/.config/r36s-studio/telegram.json` (droits 600) et s'arrête.
   Y mettre `{"token": "…", "chat_ids": [<ton identifiant>]}`. Pour trouver
   l'identifiant : lancer le bot, lui écrire ; une conversation absente de
   `chat_ids` n'obtient aucune réponse et son identifiant est écrit sur la
   sortie d'erreur (`[bot] conversation refusée …`).
4. Fichier lisible par d'autres comptes : refusé (`chmod 600`), le jeton
   n'est jamais lu ni affiché (`BotConfig.__repr__` le masque).

## Fonctionnement

- `/start` : menu à clavier persistant, avec les libellés des outils de la
  GUI (« Chercher les doublons », « Filtrer par région et par langue ») et
  « Télécharger un système pour la carte ». Les libellés lettrés A–F
  n'existent plus depuis le 2026-10-14 (accueil expert sans lettres).
- Une seule opération à la fois par conversation (`bot_busy`).
- Carte : `bot/cards.py::find_games_folders` -- cartes acceptées par
  `safety.filter_devices` (mêmes garde-fous que la GUI), espace de jeux
  EASYROMS monté par `locate_mounted` (udisksctl sous Linux). Toujours un
  bouton par carte, même seule (§4.2). KNULLI/ROCKNIX (pas d'EASYROMS) : « aucune
  carte avec un espace de jeux ».
- Questions au milieu d'un travail (dossier volumineux, fichier qui
  résiste) : `BotSession.ask_from_thread`.

## Deuxième lot (2026-10-20) : sauvegarde, remise à zéro, raccourcis web

Menu : en plus du premier lot, « Sauvegarder l'image complète de ma carte »,
« Sauvegarder mon système sans les jeux », « Remettre la carte à zéro »,
« Web » (mêmes libellés que la GUI).

- **Choix de la carte** : un bouton par carte acceptée par `safety`
  (`filter_devices`), **jamais de présélection, même pour une seule carte**
  (§4.2) -- aussi pour les doublons et le filtre depuis ce lot.
- **Confirmation à deux boutons** (§2 n°6), récapitulatif qui nomme la
  carte (nom affiché par la GUI + capacité) et ce qui sera détruit :
  rien pour une sauvegarde (la carte est seulement lue, un nouveau fichier
  horodaté est créé, jamais un existant remplacé) ; **tout** pour la remise
  à zéro (système, jeux, sauvegardes de parties). La remise à zéro n'a pas
  de bouton Annuler une fois lancée (carte à moitié formatée).
- **Destination des sauvegardes** : `~/Documents/R36S Studio/`
  (`partitions/archives.default_archives_dir`, même convention que la GUI,
  jamais `~/.config`, §6), `sauvegarde_<date>.img` / `systeme_<date>.img`.
  Pas de saisie de chemin : Telegram n'a pas de sélecteur de fichiers.
- **Espace vérifié avant toute sauvegarde** : le bot demande d'abord la
  taille exacte au worker élevé (`backup --estimate-only`, désormais aussi
  pour la sauvegarde complète : `imaging/backup.estimate_full_backup_size`,
  sauvegarde intelligente §4.3 -- fin de la dernière partition MBR, toute
  la carte en GPT), y ajoute le `.sha256blocks` (`required_free_bytes`) et
  compare à l'espace libre du dossier. Refus avant de commencer, avec
  l'espace manquant. **Compression** : aucune, les sauvegardes sont des
  `.img` bruts (`.img.gz`/`.img.xz` jamais implémentés en écriture) --
  l'estimation est donc la taille réelle. Le worker refait le même calcul
  pour sa propre vérification (auparavant : toute la capacité de la carte
  pour une sauvegarde complète, ce qui aurait refusé ce que le bot acceptait).
- **Raccourcis web** (`r36s_studio/shortcuts.py`) : liste livrée vide,
  aucun lien en dur. Fichier personnel `~/.config/r36s-studio/raccourcis.json`,
  absent par défaut, hors dépôt :

      [{"nom": "Mon tableau de bord", "url": "https://exemple.org/"}]

  Seuls les liens `https://` sont gardés (20 au plus). Un bouton par
  raccourci, la réponse est le lien. La tuile « Web » de la GUI reste
  pilotée par `R36S_STUDIO_WEB_URL`, inchangée.
- **Téléchargement** : celui du premier lot (« Télécharger un système pour
  la carte »). Envoyer une sauvegarde sur le téléphone n'est pas proposé
  (une image fait plusieurs Go, l'API des bots plafonne l'envoi à 50 Mo).

## Autorisation (sudo) -- à installer à la main, jamais automatiquement

Le bot tourne en **utilisateur normal**, jamais en root (§3). Seuls la
sauvegarde et la remise à zéro passent par le worker élevé
(`bot/worker.py`) : `sudo -n /usr/local/sbin/r36s-studio-worker <backup|
reset-card> ... --worker`. `-n` : sudo ne demande jamais de mot de passe ;
sans la règle, échec immédiat et message « l'autorisation n'est pas
installée ». Le worker refait toutes les vérifications (`safety` : disque
système, disque trop gros, chemin inconnu refusés).

1. **Copie du projet appartenant à root**, non modifiable par le compte du
   bot (sinon ce compte pourrait faire exécuter n'importe quel code en
   root) :

       sudo git clone https://github.com/nonotrichlozz/r36s-studio /opt/r36s-studio
       sudo chown -R root:root /opt/r36s-studio
       sudo chmod -R go-w /opt/r36s-studio

   Le bot lui-même peut tourner depuis cette copie ou une autre.
2. **Script lanceur** `/usr/local/sbin/r36s-studio-worker`, `root:root`,
   `0755` :

       #!/bin/sh
       cd /opt/r36s-studio || exit 1
       exec /usr/bin/python3 -E -s -m r36s_studio "$@"

   (`-E` : aucune variable `PYTHON*` du compte appelant ; `-s` : pas de
   paquets du dossier personnel.)
3. **Règle sudoers**, avec `sudo visudo -f /etc/sudoers.d/r36s-studio-bot`
   (remplacer `bot` par le compte qui lance le bot) :

       bot ALL=(root) NOPASSWD: /usr/local/sbin/r36s-studio-worker backup *, /usr/local/sbin/r36s-studio-worker reset-card *

   Uniquement ces deux commandes : ni `flash`, ni un shell, ni Python
   directement. `sudo -l -U bot` pour vérifier.

Les cartes, elles, restent protégées par le garde-fou du worker ; la liste
blanche `chat_ids` décide qui peut demander une opération
(`bot/dispatch.py`, vérifiée pour chaque commande, texte et clic --
`tests/test_bot_whitelist.py`).

## Progression (`bot/progress.py`)

Telegram plafonne à environ un message par seconde et par conversation,
éditions comprises ; le cœur émet jusqu'à ~4 événements/s.
`ProgressRelay` garde le dernier événement (thread-safe), n'édite qu'une
fois toutes les 2,5 s et seulement s'il a changé, puis fait **toujours**
une édition finale avec le dernier compte exact (et retire le bouton
Annuler), au moins 1,1 s après la précédente. Une édition refusée pour débit
(`RetryAfter`) est retentée après le délai demandé (`telegram_app.PtbPort`) ;
« message is not modified » n'est pas une erreur.

## Tests

`tests/test_bot_*.py`, `tests/test_core_runs.py` : API Telegram
entièrement simulée (`FakePort` ; fausse bibliothèque `telegram` pour
`PtbPort`), aucun réseau, aucune vraie carte (`find_games_folders`
remplacée). Le cœur est le vrai : vrais doublons mis de côté, vrai filtre
dans un dossier temporaire.

## Non vérifié

Jamais lancé sur l'Eee PC ni contre la vraie API Telegram ; version de
Python d'antiX i686 non vérifiée (le code exige 3.9+ : `asyncio.to_thread`).
Règle sudo et script lanceur jamais essayés sur une vraie machine. Remise à
zéro sous Linux : déjà un point ouvert de la GUI (CLAUDE.md §7, best-effort).
