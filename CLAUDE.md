# R36S Studio — Spécification technique

> Application de bureau multiplateforme pour préparer une carte SD de console R36S.
> Nom de travail : **R36S Studio**.

Ce fichier ne contient que ce qui sert à chaque session. Le détail de chaque
module vit dans `docs/claude/` : **lis le fichier indiqué avant de travailler
sur le module correspondant** (liste au §4). L'historique des bugs corrigés
est dans `docs/bugs-*.md`.

---

## 1. Objectif

Permettre à n'importe qui, sans ligne de commande, de sauvegarder sa carte SD,
flasher un firmware (ROCKNIX par défaut, ArkOS/dArkOS, EmuELEC…), cloner une
carte vers une autre, choisir l'écran de la console et copier des jeux — depuis
une fenêtre lancée par un double-clic, sur **Windows, macOS et Linux**.

**Public visé : le néophyte total** (n'a jamais ouvert un terminal, ne sait pas
ce qu'est une partition). Donc : aucun compte, aucune clé, aucune configuration
préalable ; pas d'internet requis pour les opérations principales ; aucune
ligne de commande, jamais, à aucune étape ; le chemin par défaut doit marcher
sans que l'utilisateur comprenne ce qu'il fait.

---

## 2. Contraintes non négociables

| # | Règle | Raison |
|---|-------|--------|
| 1 | Aucun `/dev/sdX` ni lettre de lecteur en dur | Détruire le disque système d'un utilisateur est irréversible |
| 2 | Aucun secret dans le code (token, clé API) | Le code sera public |
| 3 | Aucune ROM, aucun BIOS embarqué dans le paquet | Diffusion illégale |
| 4 | Aucune image ArkOS embarquée | Poids (2–6 Go) + versions qui changent |
| 5 | Progression réelle, jamais simulée | Une fausse barre fait débrancher la SD trop tôt |
| 6 | Toute écriture disque exige une confirmation explicite | Dernier rempart avant la casse |

---

## 3. Architecture

Deux processus séparés. C'est le point structurant du projet.

```
┌─────────────────────────────┐
│  GUI (privilèges normaux)   │   PySide6
│  - choix du périphérique    │
│  - affichage progression    │
│  - confirmations            │
└──────────┬──────────────────┘
           │ lance en élevé, lit stdout ligne par ligne
           ▼
┌─────────────────────────────┐
│  WORKER (privilèges admin)  │   même binaire, argument --worker
│  - lecture/écriture brute   │
│  - montage / démontage      │
│  - émet du JSON Lines       │
└─────────────────────────────┘
```

L'interface ne tourne jamais en administrateur ; le worker est testable seul,
sans interface (c'est un CLI : `python -m r36s_studio <commande>`).

**Protocole GUI ↔ worker** — une ligne JSON par événement (`protocol.py`) :
`progress` (`done`/`total`/`speed`), `log` (`level`/`msg`), `error`
(`code`/`msg`), `done` (`ok`), plus `estimate` (`size_bytes`), `step_progress`
(`step_index`/`step_count`/`step_name`), `eject_result`, `identify_result`
(`result`, identification élevée sous Windows), `phase` (`name` :
`verify_source`/`verify_image` -- les `progress` suivants repartent de 0) et
`stalled` (`seconds`/`limit` : la carte source ne renvoie plus rien),
`boot_sets_result` (`result` : jeux de fichiers du BOOT et état de la carte,
`boot-sets`).

**Élévation, par OS** (détail et pièges macOS : `docs/claude/elevation-macos.md`) :

| OS | Méthode |
|----|---------|
| Windows | Relance du worker via `ShellExecuteExW` verbe `runas` (UAC), fenêtre masquée (`SW_HIDE`) |
| macOS empaqueté | `AuthorizationExecuteWithPrivileges` depuis le binaire du bundle (hérite de l'Accès complet au disque) |
| macOS en dev | `osascript … with administrator privileges` — **ne peut pas** lire `/dev/rdiskN` (TCC) |
| Linux | `pkexec`, repli `sudo` si absent |

Une seule `MacosAuthorizationSession` pour toute la vie de l'app (mot de passe
demandé une fois) ; Windows/Linux redemandent l'élévation à chaque worker.

---

## 4. Modules — quel fichier lire

| Tu travailles sur… | Lis d'abord |
|---|---|
| `gui/elevate.py`, worker élevé, TCC/Accès complet au disque macOS | `docs/claude/elevation-macos.md` |
| `devices/` (détection des cartes), `safety/` (garde-fou) | `docs/claude/devices-safety.md` |
| `imaging/` : sauvegarde, sauvegarde système (GPT/MBR), flash, SHA-256, formats, partition de jeux auto, « utiliser toute la carte » SF3000 | `docs/claude/imaging.md` |
| `imaging/reset_card.py`, `cmd_reset_card`, `_format_windows` | `docs/claude/reset-card.md` |
| `partitions/` : localisation/montage, copie, archives, éjection | `docs/claude/partitions.md` |
| `detect/` : badges de statut des étapes du mode expert | `docs/claude/detect.md` |
| Opérations du mode expert, catalogue de firmwares, ROCKNIX, clones, avertissements après flash | `docs/claude/firmwares-flash.md` |
| `gui/screens.py`, `gui/theme.py`, `gui/strings.py`/`strings_en.py`, `i18n.py`, `LogPanel`, mode expert | `docs/claude/interface.md` |
| Mode assisté : accueil, parcours de clonage, empreinte de carte, sondage | `docs/claude/assisted-wizard.md` |
| `packaging/`, `.spec`, CI, releases, `config.json` | `docs/claude/packaging.md` |
| Écrire/déboguer des tests, bancs de test matériel | `docs/claude/testing.md` |
| `android/` (ADB) | `docs/android-adb.md` |
| `consoles_diverses/` | `r36s_studio/consoles_diverses/CLAUDE.md`, `docs/consoles-diverses-design.md`, `docs/consoles-diverses-recherche.md` |
| `doublons/` | `docs/doublons.md`, `docs/doublons-selection.md` |
| `tri/`, `gui/tri_screen.py` (Ranger des jeux mélangés, Filtrer par région et par langue, tables de dossiers par firmware) | `docs/tri-roms.md` |

**Garde-fou `safety/` (toujours applicable)** — un périphérique est **refusé**
(absent de la liste, pas seulement grisé) si : `is_system` ou contient la
partition de démarrage ; contient le dossier d'où l'app s'exécute ;
`removable` faux **et** bus non USB ; taille > seuil (défaut 1 To) ; taille
nulle ou inconnue. Aucune sélection par défaut, jamais.

**Deux modes d'interface** : *assisté* (défaut, `ui_mode` persisté) — accueil
par situations (« Ma console ne démarre plus », carte neuve, sauvegarde ;
`assisted-wizard.md`) ; le parcours de clonage en 5 étapes reste dans le code
mais n'a plus de tuile ; et
*expert* — quatre étapes sans lettres (copier les jeux sur l'ordinateur,
installer un système, copier des jeux sur la carte, éjecter) + « Par
sécurité » (sauvegarde complète, sauvegarde système sans les jeux, remise à
zéro) + outils. Extraction/injection du BOOT retirées le 2026-10-14 :
doublon de la sauvegarde système (qui contient tout le BOOT, la partition
système et le chargeur de démarrage) ; le bon écran passe par « Choisir
l'écran de la console » (`boot-sets`).

---

## 5. Invariants transversaux

- **Signaux Qt de tailles en `"qint64"`**, jamais `int` : PySide6 laisse
  tomber l'`emit()` au-delà de ~2,1 Go, sans exception.
- **Un vrai `error` du worker prime** sur un `ELEVATION_FAILED` synthétisé par
  timeout côté GUI (`WorkerRunner._error_emitted`) ; `finished` n'est émis
  qu'une fois.
- **Confirmation** : `ConfirmDialog` (fond rouge, case obligatoire, jamais
  pré-cochée) avant toute écriture sur le périphérique brut (flash, remise à
  zéro), jamais sautée, y compris dans les flux automatiques. Pas de fenêtre
  rouge pour une opération non destructrice (sauvegarde).
- **Vérifications avant élévation** : ce qui peut être refusé d'avance (format
  d'image `.7z`, carte trop petite, espace disque) est vérifié côté GUI *avant*
  toute demande de mot de passe, puis revérifié par le worker (autorité réelle).
  **Écart assumé, `.sha256blocks`** : côté GUI, seuls les contrôles gratuits
  (compagnon présent, en-tête lisible, taille annoncée = taille de l'image ;
  refus d'un `.img.instable` hors mode expert) ; le recalcul complet des
  empreintes (plusieurs Go à relire) se fait seulement dans le worker, après
  l'élévation -- le faire deux fois doublerait une minute de lecture.
- **Double lecture de la source** (`imaging/source_verify.py`, incident réel :
  carte dégradée renvoyant des octets faux sans erreur d'E/S) : toute
  sauvegarde relit la source et compare les empreintes par bloc
  (`config.json::verify_backup_source`, case en mode expert seulement,
  `--no-source-verify`). Source instable : image renommée en `.img.instable`
  (jamais supprimée) + `.instable.txt`, code `SOURCE_UNSTABLE`. Chaque
  sauvegarde réussie écrit `<image>.sha256blocks`, recontrôlé avant tout
  flash (`IMAGE_MODIFIED`, carte jamais touchée). Format : `imaging.md`.
- **Chien de garde de lecture** (`imaging/source.py::StallWatchedReader`,
  incident réel : lecture bloquée des heures sans erreur) : toute lecture de
  la carte source d'une sauvegarde passe par lui. Événement `stalled` après
  5 s, abandon `SOURCE_NOT_RESPONDING` après
  `config.json::source_stall_timeout_seconds` (60 s, `--stall-timeout`) ;
  un worker qui garde un thread de lecture coincé quitte par `os._exit`.
- **Codes d'erreur** : tout `emit_error("CODE", …)` de `__main__.py` doit avoir
  un message dans `gui/strings.py::_ERROR_MESSAGE_KEYS` (vérifié par
  `tests/test_gui_strings.py`). Les détails passent par `error_log_detail`.
- **Diagnostic** : `_start_worker`/`_start_eject` journalisent l'argv complet
  (`[diagnostic] worker : …`) de chaque worker élevé.
- **Jamais silencieux** : chaque décision automatique (partition de jeux,
  éjection, montage) est journalisée ; un bonus qui échoue après un flash
  vérifié (éjection, partition de jeux) est un avertissement, jamais un échec.
- **Vocabulaire** : aucun terme technique dans l'interface (« ta carte SD »,
  « les jeux », « le système de la console ») ; chemin ou message brut en
  ligne supplémentaire du journal, jamais dans le message principal.
  Chaînes dans `gui/strings.py` (français, référence) et
  `gui/strings_en.py`, mêmes clés et mêmes `{…}` ; langue fixée au
  démarrage (`i18n.py`, `config.json::language`). Une langue n'est
  ajoutée que si quelqu'un peut la relire (§2 n°6).
- **Tailles affichées en base 1024 partout** (`_capacity_go`/`_format_size`,
  dupliqué dans `__main__.py` pour que le CLI ne dépende pas de PySide6).
- **Thème** : aucune couleur en dur dans les écrans ; `setProperty("role"/
  "badgeKind", …)` puis `theme.repolish(widget)`. Palette dans `gui/theme.py`.
- **Threads** : tout ce qui peut bloquer (montage, réseau, lecture de table)
  tourne hors du thread Qt principal (runners de `gui/partition_runner.py`…).
- **Dossiers utilisateur** : archives, sauvegardes, firmwares dans
  `~/Documents/R36S Studio/`, proposés mais toujours remplaçables ; jamais dans
  `~/.config` (réservé à `config.json`, sans secret).
- **Version** : `APP_VERSION` (`r36s_studio/__init__.py`) est la seule
  source (`--version`, vérification des mises à jour) ; `release.yml`
  refuse un tag `v*` qui ne lui correspond pas. Pour sortir une version :
  changer `APP_VERSION` et pousser sur `main` suffit (brouillon de Release
  construit automatiquement, sans tag à créer).
- **Licences** : R36S Studio est sous PolyForm Strict 1.0.0 (`LICENSE`) ;
  aucun composant embarqué sous GPL seule (exclusion `_EXCLUDED_QT` des
  specs), chaque composant tiers listé dans `THIRD_PARTY_NOTICES.txt`.
- **Paquet** : tout fichier non-Python lu à l'exécution doit être déclaré dans
  les trois `packaging/*.spec` (vérifié par `tests/test_packaging_specs.py`).
- **Dépendances de `partitions/`** : jamais d'import de `gui/` (points
  d'extension, ex. `set_privileged_mount_hook`).

---

## 6. Tests — règles de base

Détail et bancs de test : `docs/claude/testing.md`.

- `tests/conftest.py` patche `subprocess.run`/`Popen` en autouse : un appel non
  mocké lève `UnmockedSubprocessError`. Exceptions déclarées par marqueur :
  `@pytest.mark.real_subprocess`, `@pytest.mark.real_fda_probe`
  (`has_full_disk_access` est stubée à `True` par défaut).
- `config.json` est redirigé vers `tmp_path` en autouse (`conftest.py`, et
  `APPDATA` aussi) : un test ne doit jamais écrire le vrai fichier de la
  machine. `_real_config_dir_guard` (hook d'audit) fait échouer tout test qui
  ouvre, crée ou renomme quoi que ce soit dans le vrai dossier de config,
  même par une copie importée (`from r36s_studio.config import config_path`,
  incident du 2026-10-10).
- Chemins de périphérique factices impossibles à confondre avec du matériel
  réel : `/dev/fake-disk-test-*`, ou numéro implausible quand le format compte
  (`disk9903`, `PhysicalDrive9902`).
- Mode dev (`--allow-disk-image` ou `R36S_STUDIO_DEV=1`) : lève uniquement
  l'exclusion des disk images/loop, jamais les règles `safety` ; désactivé en
  `--worker`.
- **Débit anormalement bas : vérifier la carte SD avant de suspecter le
  code** (cartes d'origine non-marque ~6 Mo/s contre ~88 Mo/s pour une SanDisk ;
  capacité exposée très inférieure à l'annoncée = carte falsifiée ; l'app le
  signale après une sauvegarde, `_slow_card_read_speed`). Ne jamais
  accuser un changement récent sur une simple corrélation temporelle.
- Test manuel obligatoire avant chaque release : un disque dur externe
  branché ne doit **pas** apparaître comme carte SD.

---

## 7. Points ouverts (non vérifiés sur du vrai matériel)

- Windows : `[Errno 9] Bad file descriptor` possible peu après le début d'une
  écriture sur une carte ArkOS complète, cause non confirmée (`imaging.md`).
- Éjection macOS (`diskutil eject`) et Linux (`udisksctl power-off`) ; un cas
  Windows d'éjection de la source non déclenchée, non reproduit (`partitions.md`).
- Remise à zéro et montage best-effort sur macOS/Linux (`reset-card.md`).
- Carte SF3000 (`cubegm/rkgame`) : aucune partition de jeux après un flash --
  détection (`imaging/card_probe.py`) vérifiée sur l'image d'une vraie carte,
  pas encore sur la carte elle-même (`imaging.md`).
- Partition de jeux recréée automatiquement après un flash plus petit que la
  carte : ligne « Espace de jeux recréé… » attendue dans le journal (`imaging.md`).
- Avertissement de formatage Windows après un flash « Linux » (`firmwares-flash.md`).
- Tour complet UAC depuis le binaire Windows empaqueté ; paquets `apt` du job
  CI Linux ; `release.yml` (installeur Inno Setup, test de fumée `_internal`
  + `--version`) : Release Windows seule depuis le 2026-10-07, jamais
  encore publiée (`packaging.md`).
- « Utiliser toute la carte » (`clone-sf3000`, carte SF3000, Windows) :
  jamais lancé depuis l'app sur une vraie carte ; durées estimées à
  recaler au premier essai (`imaging.md`).
- Chien de garde du sondage : ne détecte qu'un ralentissement, jamais un arrêt
  complet du minuteur (`assisted-wizard.md`).
- Double lecture de la source : jamais lancée sur la carte noname (0xFE) de
  l'incident ; `posix_fadvise(DONTNEED)` (Linux) et l'absence de cache sur
  `\\.\PhysicalDriveN` (Windows) supposés, non mesurés (`imaging.md`).
- Chien de garde de lecture : jamais déclenché sur la vraie carte ; sortie
  d'un worker dont le `ReadFile` reste coincé dans le pilote non vérifiée.
  **TODO** : l'écriture du flash (carte cible qui cesse de répondre) n'est
  pas surveillée (`imaging.md`).
- **TODO** : `clone-sf3000` (« Utiliser toute la carte ») ne contrôle pas
  encore le `.sha256blocks` de l'image avant d'écrire -- même contrôle que
  `flash_device` à ajouter.
- « Identifier ma console » sur une carte à BOOT EFI : vérifié sous Windows
  (worker élevé) ; sous Linux, montage `udisksctl` d'une partition EFI non
  vérifié -- un refus donnerait le message « protection de l'ordinateur »,
  sans relecture élevée (`elevation-macos.md`).
- Table matérielle de dArkOSRE (`identify/hardware_table.py`) : vérifiée sur
  les `.dtb` de dArkOSRE, jamais sur un `.dtb` de carte d'usine -- que son
  `model` porte bien ces chaînes reste supposé (`assisted-wizard.md`).
- ROCKNIX sur R36S : réglages automatiques après le flash (`extlinux.conf.r36s`,
  fichier d'écran téléchargé, empreintes fixées) et absence de partition de jeux
  sur carte ROCKNIX -- jamais lancés sur la console (`firmwares-flash.md`,
  `imaging.md`).

---

## 8. Ce que le dépôt ne contient jamais

- Aucun token, aucune clé API
- Aucune ROM, aucun BIOS
- Aucune image système `.img`
- Aucun chemin personnel en dur

L'image ArkOS est soit téléchargée par l'application depuis la source officielle avec
vérification de somme de contrôle, soit sélectionnée par l'utilisateur dans ses fichiers.
