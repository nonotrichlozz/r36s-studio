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
carte vers une autre, injecter le BOOT d'origine et copier des jeux — depuis
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
(`step_index`/`step_count`/`step_name`) et `eject_result`.

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
| `imaging/` : sauvegarde, sauvegarde système (GPT/MBR), flash, SHA-256, formats, partition de jeux auto | `docs/claude/imaging.md` |
| `imaging/reset_card.py`, `cmd_reset_card`, `_format_windows` | `docs/claude/reset-card.md` |
| `partitions/` : localisation/montage, copie, archives, éjection | `docs/claude/partitions.md` |
| `detect/` : badges de statut des étapes A→F | `docs/claude/detect.md` |
| Opérations A→F, catalogue de firmwares, ROCKNIX, clones, avertissements après flash | `docs/claude/firmwares-flash.md` |
| `gui/screens.py`, `gui/theme.py`, `gui/strings.py`, `LogPanel`, mode expert | `docs/claude/interface.md` |
| Mode assisté : accueil, parcours de clonage, empreinte de carte, sondage | `docs/claude/assisted-wizard.md` |
| `packaging/`, `.spec`, CI, releases, `config.json` | `docs/claude/packaging.md` |
| Écrire/déboguer des tests, bancs de test matériel | `docs/claude/testing.md` |
| `android/` (ADB) | `docs/android-adb.md` |
| `consoles_diverses/` | `r36s_studio/consoles_diverses/CLAUDE.md`, `docs/consoles-diverses-design.md`, `docs/consoles-diverses-recherche.md` |
| `doublons/` | `docs/doublons.md`, `docs/doublons-selection.md` |
| `tri/`, `gui/tri_screen.py` (Ranger mes jeux, tables de dossiers par firmware) | `docs/tri-roms.md` |

**Garde-fou `safety/` (toujours applicable)** — un périphérique est **refusé**
(absent de la liste, pas seulement grisé) si : `is_system` ou contient la
partition de démarrage ; contient le dossier d'où l'app s'exécute ;
`removable` faux **et** bus non USB ; taille > seuil (défaut 1 To) ; taille
nulle ou inconnue. Aucune sélection par défaut, jamais.

**Deux modes d'interface** : *assisté* (défaut, `ui_mode` persisté) — parcours
de clonage en 5 étapes par image disque brute, indépendant du firmware ; et
*expert* — six étapes A→F (extraire BOOT, extraire EASYROMS, flasher, injecter
BOOT, copier les jeux, éjecter) + « Par sécurité » (sauvegarde complète,
sauvegarde système sans les jeux, remise à zéro).

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
  Chaînes dans `gui/strings.py`, interface en français.
- **Tailles affichées en base 1024 partout** (`_capacity_go`/`_format_size`,
  dupliqué dans `__main__.py` pour que le CLI ne dépende pas de PySide6).
- **Thème** : aucune couleur en dur dans les écrans ; `setProperty("role"/
  "badgeKind", …)` puis `theme.repolish(widget)`. Palette dans `gui/theme.py`.
- **Threads** : tout ce qui peut bloquer (montage, réseau, lecture de table)
  tourne hors du thread Qt principal (runners de `gui/partition_runner.py`…).
- **Dossiers utilisateur** : archives, sauvegardes, firmwares dans
  `~/Documents/R36S Studio/`, proposés mais toujours remplaçables ; jamais dans
  `~/.config` (réservé à `config.json`, sans secret).
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
- Chemins de périphérique factices impossibles à confondre avec du matériel
  réel : `/dev/fake-disk-test-*`, ou numéro implausible quand le format compte
  (`disk9903`, `PhysicalDrive9902`).
- Mode dev (`--allow-disk-image` ou `R36S_STUDIO_DEV=1`) : lève uniquement
  l'exclusion des disk images/loop, jamais les règles `safety` ; désactivé en
  `--worker`.
- **Débit anormalement bas : vérifier la carte SD avant de suspecter le
  code** (cartes d'origine non-marque ~6 Mo/s contre ~88 Mo/s pour une SanDisk ;
  capacité exposée très inférieure à l'annoncée = carte falsifiée). Ne jamais
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
- Partition de jeux recréée automatiquement après un flash plus petit que la
  carte : ligne « Espace de jeux recréé… » attendue dans le journal (`imaging.md`).
- Avertissement de formatage Windows après un flash « Linux » (`firmwares-flash.md`).
- Tour complet UAC depuis le binaire Windows empaqueté ; paquets `apt` du job
  CI Linux ; aucun tag `v*` créé à ce jour, donc aucune Release (`packaging.md`).
- Chien de garde du sondage : ne détecte qu'un ralentissement, jamais un arrêt
  complet du minuteur (`assisted-wizard.md`).

---

## 8. Ce que le dépôt ne contient jamais

- Aucun token, aucune clé API
- Aucune ROM, aucun BIOS
- Aucune image système `.img`
- Aucun chemin personnel en dur

L'image ArkOS est soit téléchargée par l'application depuis la source officielle avec
vérification de somme de contrôle, soit sélectionnée par l'utilisateur dans ses fichiers.
