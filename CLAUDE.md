# R36S Studio — Spécification technique

> Application de bureau multiplateforme pour préparer une carte SD de console R36S.
> Document destiné à servir de brief de départ (`CLAUDE.md`) pour Claude Code.
> Nom de travail : **R36S Studio** — à renommer librement.

---

## 1. Objectif

Permettre à n'importe qui, sans ligne de commande, de :

1. **Sauvegarder** l'ancienne carte SD dans un fichier image
2. **Flasher** ArkOS sur une carte SD neuve
3. **Injecter** les fichiers du BOOT d'origine (écran, config console)
4. **Copier** un dossier de jeux vers la partition EASYROMS

Le tout depuis une fenêtre graphique, lancée par un double-clic, sur **Windows, macOS et Linux**.

**Public visé : le néophyte total.** Quelqu'un qui n'a jamais ouvert un terminal et qui
ne sait pas ce qu'est une partition. L'application reconnaît d'elle-même ce qu'il y a sur
la carte et propose l'action pertinente.

Conséquences directes sur la conception :

- Aucun compte à créer, aucune clé à saisir, aucune configuration préalable
- Aucune connexion internet requise pour les opérations principales
- Aucune ligne de commande, jamais, à aucune étape
- Le chemin par défaut doit fonctionner sans que l'utilisateur ait à comprendre ce qu'il fait

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

**Pourquoi séparer :** l'interface ne doit jamais tourner en administrateur. Seules les
quelques secondes d'écriture disque le nécessitent. C'est aussi ce qui rend le worker
testable en isolation, sans interface.

**Protocole GUI ↔ worker** — une ligne JSON par événement sur `stdout` :

```json
{"type":"progress","done":1048576,"total":3221225472,"speed":18400000}
{"type":"log","level":"info","msg":"Partition BOOT montée sur /Volumes/BOOT"}
{"type":"error","code":"DEVICE_BUSY","msg":"..."}
{"type":"done","ok":true}
```

**Élévation de privilèges, par OS :**

| OS | Méthode |
|----|---------|
| Windows | Relance du worker via `ShellExecuteW` verbe `runas` → invite UAC |
| macOS | `osascript -e 'do shell script "…" with administrator privileges'` |
| Linux | `pkexec` (fallback `sudo` en terminal si absent) |

> ⚠️ **Limitation macOS confirmée par test.** `osascript … with administrator
> privileges` obtient bien les droits root pour le worker, mais **ne peut pas
> accéder à `/dev/rdiskN`** — même avec le Terminal autorisé en Accès complet au
> disque (Réglages Système → Confidentialité et sécurité). TCC (Transparency,
> Consent and Control) filtre au-dessus des droits Unix classiques, et le
> processus lancé par `osascript` n'hérite d'aucune identité TCC propre : il n'y
> a rien à autoriser tant qu'il n'est pas packagé comme application.
>
> **Décision (historique) :** cette limitation ne sera résolue qu'en phase 7,
> quand l'appli sera empaquetée (PyInstaller) — un binaire packagé a sa propre
> identité TCC et pourra être ajouté à la liste Accès complet au disque. Elle ne
> bloque pas les phases 5 et 6. En attendant, la GUI doit détecter cet échec
> spécifique et afficher un message explicite invitant à utiliser la ligne de
> commande avec `sudo` (depuis un Terminal autorisé en Accès complet au disque)
> plutôt qu'un message d'erreur générique. Linux (`pkexec`) et Windows (UAC) ne
> sont pas concernés par cette limitation.
>
> ✅ **Résolu (phase 7), confirmé sur du vrai matériel.** Une fois l'app
> empaquetée (`packaging/`) ajoutée à Accès complet au disque, `osascript`
> restait bloqué sur `/dev/rdiskN` même ainsi : c'est bien lui le problème, pas
> l'absence de bundle. Cause : `osascript` est un processus système sans
> rapport avec le bundle de l'app — l'enfant qu'il lance n'hérite d'aucune
> identité TCC, packagée ou non. **Correctif :** sur l'app empaquetée,
> `gui/elevate.py` relance désormais le worker directement depuis le binaire
> du bundle lui-même (`sys.executable`, via `AuthorizationExecuteWithPrivileges`
> — `Security.framework`, pas `osascript`/`do shell script`)
> (`MacosAuthorizedProcess`). Un enfant direct du binaire signé **hérite bien**
> de l'autorisation Accès complet au disque du bundle — vérifié par une sonde
> read-only sur `/dev/rdiskN` avant d'implémenter quoi que ce soit de plus
> lourd. `osascript` reste utilisé en développement (pas de bundle, donc rien
> à hériter) et comme repli si cette API — non documentée par Apple depuis
> macOS 10.7, mais toujours présente au moment de ce test (macOS 12) —
> disparaissait d'une future version de macOS.
>
> ⚠️ **La signature ad hoc change à chaque reconstruction.** PyInstaller signe
> le bundle ad hoc par défaut (aucun certificat Developer ID nécessaire, §6),
> mais cette signature change à chaque `packaging/build_macos.sh` — même sans
> changement de code observable. macOS lie l'autorisation Accès complet au
> disque à cette signature : après chaque reconstruction, l'autorisation
> précédente est invalidée et doit être refaite (retirer puis rajouter l'app
> dans la liste, pas juste désactiver/réactiver le bouton existant — voir
> `packaging/README.md` §4). C'est pour ça que le message d'erreur
> `MACOS_TCC_BLOCKED` (`gui/worker_runner.py`) et l'écran Aide dédié
> (`gui/screens.py::HelpScreen`, accessible depuis l'accueil sur macOS) pointent
> tous les deux vers cette autorisation plutôt que vers la ligne de commande —
> devenue inutile pour ce cas précis.
>
> Le deuxième cas ci-dessous (`MACOS_TCC_PROTECTED_FOLDER`, fichiers dans
> Téléchargements/Bureau/Documents) n'a pas été retesté avec ce nouveau chemin
> d'élévation — probablement concerné par le même principe (un enfant du
> bundle hérite de l'identité TCC), mais non vérifié sur du vrai matériel :
> son message et sa détection restent donc inchangés pour l'instant.
>
> ⚠️ **Deuxième cas confirmé sur du vrai matériel, distinct du précédent** :
> `[Errno 1] Operation not permitted` survient aussi sur des **fichiers
> ordinaires** (l'image `.img.xz` à flasher, typiquement), pas seulement sur
> `/dev/rdiskN`, quand ce fichier se trouve dans l'un des trois dossiers que
> macOS protège par TCC : Téléchargements, Bureau, Documents — même quand le
> Terminal a l'Accès complet au disque, cette autorisation ne s'étend pas au
> worker élevé par `osascript`. Exemples réels :
> `/Users/x/Downloads/ArkOS...img.xz`, `/Users/x/Desktop/r36s/ArkOS...img.xz`
> (dans un sous-dossier — la détection doit chercher le nom de dossier
> n'importe où dans le chemin, pas seulement en tête). `worker_runner.py`
> détecte ce cas séparément (`MACOS_TCC_PROTECTED_FOLDER`, distinct de
> `MACOS_TCC_BLOCKED`) et invite à déplacer le fichier ailleurs — plutôt qu'à
> utiliser `sudo`, qui ne changerait rien ici puisque le problème n'est pas le
> périphérique brut mais l'un de ces trois dossiers précis.

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : `AttributeError: Slot
> 'MainWindow::_on_progress(int,int,double)' not found`, en continu pendant
> un flash.** Cause réelle, trouvée via une capture `QT_FATAL_WARNINGS=1`
> sur le binaire empaqueté : un `OverflowError` intercalé juste avant
> chaque occurrence du message. `WorkerRunner.progress`/
> `PartitionJobRunner.progress` étaient déclarés `Signal(int, int, float)`
> — `int` correspond à un entier **32 bits** côté Qt (~2,1 milliards max),
> alors qu'un compte d'octets pour une carte de 32 Go dépasse 34
> milliards. PySide6/libshiboken échoue alors à convertir l'argument et
> n'émet jamais d'exception Python (l'`emit()` continue silencieusement) :
> le seul symptôme visible est ce message trompeur, comme si le slot
> n'existait pas, alors que le vrai problème est la conversion de
> l'argument en amont. C'est pour ça qu'aucun test (ni les miens en
> investigation, avec des valeurs de type 50/200 octets) ne l'attrapait :
> tous restaient sous 2 Go.
>
> **Corrigé** en déclarant `Signal("qint64", "qint64", float)` (entier 64
> bits) sur ces deux signaux (`gui/worker_runner.py`,
> `gui/partition_runner.py`), et le `@Slot("qint64", "qint64", float)`
> assorti sur `MainWindow._on_progress`. Les `@Slot(str, str)`/`@Slot(bool)`
> sur `_on_worker_error`/`_on_worker_finished` (ajoutés par précaution lors
> de l'étape précédente de cette investigation, avant que la vraie cause
> ne soit identifiée) restent en place : sans risque, et cohérents avec le
> principe de déclarer explicitement les slots recevant un signal
> potentiellement inter-thread (`PartitionJobRunner`). Toute taille en
> octets transitant par un signal Qt doit désormais utiliser `"qint64"`,
> jamais `int` nu — vérifié : ce sont les deux seuls signaux du projet à
> transporter des tailles en octets (`grep -rn "Signal(" r36s_studio/`).
>
> `QT_FATAL_WARNINGS=1` s'est révélé être le bon outil une fois débarrassé
> du faux positif rencontré en environnement `QT_QPA_PLATFORM=offscreen`
> (l'avertissement anodin `qt.qpa.fonts: Populating font family aliases…`,
> que PySide6 émet systématiquement et qui devient fatal avec cette
> variable) : sur un vrai écran, sans `offscreen`, il a directement pointé
> vers l'`OverflowError` réel.

---

## 4. Modules

### 4.1 `devices/` — détection des cartes SD

Une implémentation par OS, une interface commune retournant une liste de :

```python
@dataclass
class Device:
    path: str          # \\.\PhysicalDrive2 | /dev/disk4 | /dev/sdb
    display: str       # "SanDisk Ultra 128 Go"
    size_bytes: int
    removable: bool
    bus: str           # "USB", "SD", "NVMe"…
    is_system: bool    # contient l'OS en cours ?
    mountpoints: list[str]
```

| OS | Commande source |
|----|-----------------|
| Linux | `lsblk -J -b -o PATH,SIZE,MODEL,VENDOR,RM,HOTPLUG,TRAN,TYPE,MOUNTPOINTS` |
| macOS | `diskutil list -plist external physical` puis `diskutil info -plist diskN` |
| Windows | PowerShell `Get-Disk \| ConvertTo-Json` + `Get-Partition` pour les lettres |

### 4.2 `safety/` — le garde-fou

Un périphérique est **refusé** si l'une de ces conditions est vraie :

- `is_system` est vrai, ou il contient la partition de démarrage
- il contient le dossier d'où l'application s'exécute
- `removable` est faux **et** `bus` n'est pas USB
- `size_bytes` dépasse un seuil configurable (défaut : 1 To)
- `size_bytes` est nul ou inconnu

Un périphérique refusé n'apparaît pas dans la liste — il ne suffit pas de le griser.
Aucune sélection par défaut : l'utilisateur choisit toujours activement.

### 4.3 `imaging/` — lecture et écriture brutes

**Ne pas appeler `dd`.** Écrire la boucle en Python donne un code unique pour les trois
OS et une progression exacte.

```
ouvrir source et cible en binaire
boucle par blocs de 4 MiB :
    lire, écrire, cumuler les octets
    émettre un événement progress (max ~4/seconde)
flush + fsync
```

**Spécificités par OS :**

- **macOS** — démonter d'abord (`diskutil unmountDisk`), puis écrire sur `/dev/rdiskN`
  (le `r` = accès brut, environ 10× plus rapide que `/dev/diskN`).
- **Windows** — c'est la partie la plus délicate du projet. Avant d'ouvrir
  `\\.\PhysicalDriveN`, il faut, via `ctypes` + `DeviceIoControl`, pour chaque volume
  de ce disque : `FSCTL_LOCK_VOLUME` puis `FSCTL_DISMOUNT_VOLUME`. Les écritures
  doivent être alignées sur la taille de secteur (512 ou 4096 octets). Après coup,
  `IOCTL_DISK_UPDATE_PROPERTIES` pour que l'explorateur se rafraîchisse.
  Sans ce verrouillage, Windows refuse l'écriture ou corrompt la carte.
- **Linux** — `open(path, O_RDWR)` après `umount` des partitions montées. Rien d'exotique.

**Sauvegarde intelligente :** ne pas copier 128 Go quand la dernière partition s'arrête
à 8 Go. Lire la table de partitions (MBR ou GPT), calculer la fin du dernier secteur
utilisé, et ne sauvegarder que jusque-là. Proposer une compression `.img.gz` ou
`.img.xz` à la volée.

**Formats source acceptés au flash :** `.img`, `.img.gz`, `.img.xz`, `.img.zip`
(décompression en flux, sans fichier temporaire).

> ⚠️ **Bug corrigé, constaté en conditions réelles** (flash d'une image
> `ArkOS_R35S-R36S_v2.0_11072025_MultiPanel.img.xz`) : la barre de
> progression affichait 100 % et le temps restant 0 s dès le premier octet
> écrit, alors que l'écriture durait plusieurs minutes (le débit, lui,
> s'affichait correctement). Cause : `estimate_total_bytes` renvoyait
> toujours `None` pour `.img.xz` (la taille décompressée étant jugée non
> récupérable sans décompression complète), et `copy_range` traite alors la
> copie comme non bornée en rapportant `done` comme `total` — `done ==
> total` était donc vrai dès le premier événement. Corrigé : la taille
> décompressée d'un `.xz` est en fait récupérable sans décompression
> complète, via l'Index au pied de l'archive (format-xz.txt) — comme le
> champ ISIZE le fait déjà pour `.gz`. `image_source._xz_uncompressed_size`
> lit ce pied ; si le format n'est pas standard (fichier tronqué, flux
> multiples...), `flash_device` retombe sur la taille du périphérique cible
> plutôt que de traiter la copie comme non bornée.

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel par comparaison octet par
> octet** : le flash se déroulait sans erreur, mais la vérification
> SHA-256 qui suit (§4.6) échouait quand même. Diagnostic : les 16 premiers
> Mo de la relecture étaient identiques à la source, la première
> divergence tombait à l'octet 16 778 216 (juste après le début de la
> première partition), et seuls 3 blocs différaient sur les 22 premiers
> Mo — tous dans la zone FAT de la partition BOOT. Cause : `diskutil
> unmountDisk` (`write_target.prepared_write_target`) ne démonte qu'une
> fois, **avant** l'écriture — rien n'empêche macOS de remonter
> automatiquement les partitions juste après, puisque le disque porte
> désormais une table de partitions et des systèmes de fichiers valides
> (ce qu'il n'avait pas forcément avant le flash). Une fois montée, la
> partition BOOT reçoit aussitôt des fichiers d'index système
> (`.Spotlight-V100`, `.fseventsd`, dates d'accès...) que macOS écrit à
> l'ouverture de tout volume — ça modifie, dans la fenêtre entre la fin de
> l'écriture et la relecture de vérification, exactement les octets qu'on
> s'apprête à relire.
>
> **Corrigé par deux mesures complémentaires :**
> 1. `write_target.reunmount_before_verify` démonte à nouveau (macOS
>    uniquement, `check=False` — rien à démonter est un résultat normal
>    ici) juste avant la relecture (`flash.py`), pas seulement avant
>    l'écriture.
> 2. Le descripteur d'écriture (`destination`, `open(raw_path, "r+b")`)
>    reste ouvert jusqu'à la fin de la vérification plutôt que d'être
>    refermé puis rouvert pour relire (`_hash_stream_range` reçoit
>    directement ce flux, repositionné à `seek(0)`, pas un chemin à
>    rouvrir) — ça referme la fenêtre de course elle-même, la mesure 1
>    restant un filet de sécurité pour le cas où une partition
>    individuelle se monterait indépendamment du périphérique brut.
>
> Vérifié séparément : la relecture (`_hash_stream_range`) ne porte que sur
> exactement `written` (le compte d'octets réellement copiés depuis la
> source, cf. `copy_range`) — jamais sur l'espace non alloué au-delà, que
> ce soit la fin d'une carte plus grande que l'image ou un reste d'un
> flash précédent. C'était déjà correct avant ce correctif ; couvert
> explicitement par un test depuis (`test_flash.py`).

### 4.4 `partitions/` — accès aux fichiers de la SD

Après flash, la carte R36S expose trois partitions : `BOOT`, `root`, `EASYROMS`.
`BOOT` est en FAT — montable et inscriptible nativement par les trois OS.
`root` est en ext4 et n'est pas nécessaire aux fonctions prévues.

> ⚠️ **Confirmé sur du vrai matériel** : `EASYROMS` est en **NTFS**, pas en FAT32
> comme le supposait le brief initial. Windows et Linux y écrivent nativement.
> **macOS ne peut pas y écrire** : son pilote NTFS intégré ne monte les volumes
> NTFS qu'en lecture seule (pas de rapport avec la limitation TCC du §3 — un
> pilote NTFS en écriture tiers, ex. Tuxera/Paragon, contournerait celle-ci). Le
> module `partitions/` doit détecter ce cas précis (OS macOS + partition NTFS
> détectée) *avant* toute tentative d'écriture, et afficher un message explicite
> plutôt que de laisser la copie échouer avec une erreur obscure (règle §1 :
> jamais de terminal, jamais de jargon pour l'utilisateur final).
>
> ⚠️ **Bug corrigé sur du vrai matériel** : cette détection ne se déclenchait
> pas — `copy-games` échouait avec `[Errno 30] Read-only file system` au lieu
> du refus explicite. Cause : `diskutil info -plist` ne renvoie pas
> systématiquement la chaîne exacte `ntfs` pour `FilesystemType` (variante de
> casse, ou nom de type de partition `Windows_NTFS`), et la comparaison
> stricte `== "ntfs"` échouait silencieusement. `_macos_filesystem` normalise
> désormais toute variante contenant `ntfs` (`FilesystemType` et `Content`,
> insensible à la casse) vers la valeur canonique `"ntfs"`. En complément,
> `partitions/copy.py` vérifie maintenant l'inscriptibilité réelle du point
> de montage (écriture d'un fichier sonde) *avant* toute copie, quel que
> soit l'OS ou le système de fichiers — filet de sécurité générique pour
> tout futur cas de détection erronée, pas seulement celui-ci.

> ⚠️ **Confirmé sur du vrai matériel** : sur une vraie carte ArkOS R36S, la
> partition `BOOT` (la première du disque) **n'a aucune étiquette** — `diskutil`
> l'affiche « NO NAME », type DOS_FAT_16, ~117,4 Mo. L'identifier par étiquette
> seule est fragile (variable selon les versions d'ArkOS et les vendeurs) et
> ratait systématiquement cette partition. `BOOT` est donc identifiée par sa
> **position** (première partition du disque) et son **système de fichiers**
> (FAT16 ou FAT32) ; l'étiquette « BOOT », quand elle existe, ne sert que de
> repli. `EASYROMS` étant bien nommée en pratique, elle reste identifiée par
> étiquette en priorité, avec un repli sur la position (troisième partition,
> NTFS ou FAT32) si l'étiquette est absente.

Montage : attendre l'apparition automatique du volume (Windows/macOS le font seuls),
avec une temporisation et un contrôle. Sur Linux, `udisksctl mount` évite d'avoir
besoin des droits root pour cette étape.

Copie de fichiers : parcours récursif avec cumul d'octets pour la progression, puis
`fsync` et démontage propre à la fin.

> ⚠️ **Correction de conception** : la première version de ce brief ne décrivait que
> l'*injection* (BOOT/EASYROMS sauvegardés → carte neuve), en supposant à tort que
> l'utilisateur disposait déjà de ces fichiers. Le vrai parcours enchaîne **deux
> cartes** (l'ancienne, déjà en usage, puis la neuve) et nécessite donc aussi
> l'**extraction** : copier le BOOT et l'EASYROMS de l'ancienne carte vers
> l'ordinateur, avant de pouvoir les réinjecter sur la neuve. `partitions/jobs.py`
> fournit donc `extract_boot`/`extract_easyroms`, symétriques d'`inject_boot`/
> `copy_games` (même montage de la partition source, mais copie dans le sens
> partition → dossier de l'ordinateur plutôt que l'inverse). L'extraction
> d'EASYROMS ne lève jamais `MacosNtfsWriteUnsupported` : elle ne fait que lire la
> partition, et macOS monte nativement le NTFS en lecture seule — la limitation
> d'écriture ne concerne que l'injection (étape E, sur la carte neuve).
>
> **Dossiers d'archive horodatés** (`partitions/archives.py`) : chaque extraction
> crée un dossier nommé `{BOOT,EASYROMS}_{AAAA-MM-JJ}_{HH-MM}` (ex.
> `BOOT_2026-07-06_00-21`) dans `~/Documents/R36S Studio/` par défaut — jamais
> dans `~/.config` (§6). L'injection sur la carte neuve propose de choisir parmi
> les archives existantes plutôt que de redemander un dossier à chaque fois,
> avec un repli « Parcourir… » pour une source manuelle.
>
> ⚠️ **Régression corrigée** : une version intermédiaire a généré le chemin de
> destination des étapes A/B entièrement automatiquement, sans écran de choix —
> ce qui empêchait l'utilisateur de décider où son archive est enregistrée.
> Rétabli : l'écran Choix du fichier reste toujours affiché pour A/B, avec
> `~/Documents/R36S Studio/` pré-rempli comme *proposition*, acceptable tel
> quel ou remplaçable par n'importe quel autre emplacement (y compris un
> disque externe) — seul le nom horodaté à l'intérieur du dossier choisi reste
> généré automatiquement, jamais laissé au clavier de l'utilisateur.
>
> **Écran Résultat après une extraction (A/B)** : affiche le chemin complet de
> l'archive créée, sa taille (comptée depuis le dernier événement de
> progression — `copy_range`/`copy_tree` en émettent toujours un avec le
> compte final exact, §2 n°5), et un bouton pour la révéler dans le
> gestionnaire de fichiers de l'OS (`gui/reveal.py` : `open -R` sur macOS,
> `xdg-open` sur Linux, `explorer /select,` sous Windows — GUI uniquement, le
> CLI n'en a pas besoin). Après une injection (D/E), la même zone indique
> plutôt quelle archive a servi de source, avec le même bouton de révélation.
>
> **Éjection** (`partitions/eject.py`, déplacé depuis la GUI) : démonte toutes
> les partitions de la carte puis l'éjecte (`diskutil eject` / `udisksctl
> power-off -b`, qui font déjà les deux à la fois). La confirmation explicite
> que la carte peut être retirée physiquement est à la charge de l'appelant
> (CLI : message `emit_log` ; GUI : écran Résultat ou boîte de dialogue) —
> jamais un succès silencieux.

### 4.5 `detect/` — statut des étapes du parcours

> ⚠️ **Correction de conception.** Ce module a d'abord été pensé autour d'un état
> unique de la carte branchée (`CardState` : `NO_CARD`/`BLANK`/`ORIGINAL`/`ARKOS`/
> `UNKNOWN`) qui décidait d'*une* action à mettre en avant. C'était incompatible
> avec le vrai parcours : celui-ci enchaîne **deux cartes différentes** (l'ancienne,
> puis la neuve) sur **six étapes chronologiques fixes** — un état unique de « la »
> carte branchée n'a jamais de sens, puisque ce n'est jamais la même carte d'une
> étape à l'autre. `CardState`/`detect_card_state` ont été retirés.

Le module `detect` ne décide donc plus *quoi* mettre en avant — il indique
seulement, pour chacune des six étapes ci-dessous, un statut informatif :

```python
class StepStatus(Enum):
    AVAILABLE      # faisable
    DONE           # déjà faite
    NOT_RELEVANT   # non pertinente pour la carte actuellement branchée
```

Les six étapes (§4.6) restent **toujours toutes visibles et cliquables** — le statut
guide le débutant, il ne masque et ne verrouille jamais rien : un utilisateur averti
garde toujours la main, y compris pour refaire une étape déjà marquée « faite » ou
en tenter une marquée « non pertinente ».

`detect_workflow_status(device)` réutilise `partitions.locate.list_partitions()`
(déjà en lecture seule) et `has_boot_partition`/`has_easyroms_partition`/
`looks_like_arkos` pour déterminer, à partir de la carte *actuellement* branchée,
quelles étapes ont un sens maintenant (ex. : injecter le BOOT ne veut rien dire sur
une carte pas encore flashée) et lesquelles sont déjà accomplies (une archive
existe déjà pour l'extraction ; la carte est déjà ArkOS pour le flash). Aucune
écriture, aucun montage en écriture — ce module doit pouvoir tourner sans
privilèges élevés autant que possible. Toute erreur de lecture (OS non supporté,
carte débranchée entre-temps) retombe sur un statut prudent plutôt que de lever —
l'appli ne doit jamais planter sur une détection ratée.

**Cas non couvert** : plusieurs cartes candidates branchées à la fois — on ne peut
pas savoir laquelle des six étapes concerne. Décision : `detect_workflow_status`
reçoit alors `None` (comme pour aucune carte), tout est marqué « non pertinent »,
mais les six étapes restent affichées normalement — l'écran Choix du périphérique
les liste toutes.

### 4.6 `jobs/` — les opérations du parcours

> ⚠️ **Correction de conception** : cette table ne listait à l'origine que quatre
> opérations, en supposant que l'utilisateur disposait déjà des fichiers BOOT et
> EASYROMS à injecter. Le vrai parcours à deux cartes (§4.4/§4.5) en compte six,
> dans cet ordre chronologique fixe (A→F) :

| Étape | Job | Entrée | Sortie |
|-------|-----|--------|--------|
| A | `extract_boot` | carte source | dossier horodaté `BOOT_AAAA-MM-JJ_HH-MM` sur l'ordinateur |
| B | `extract_easyroms` | carte source | dossier horodaté `EASYROMS_AAAA-MM-JJ_HH-MM` sur l'ordinateur |
| C | `flash` | fichier image + carte neuve | carte écrite + vérifiée (SHA-256) |
| D | `inject_boot` | archive BOOT (étape A) + carte neuve | fichiers copiés sur `BOOT` |
| E | `copy_games` | archive EASYROMS (étape B) + carte neuve | fichiers copiés sur `EASYROMS` |
| F | `eject` | carte (neuve, en général) | partitions démontées, carte éjectée |

En dehors de ce parcours, `backup` (périphérique source → fichier `.img`/`.img.xz`)
reste disponible comme opération de sécurité indépendante (§5) : une sauvegarde
complète de l'image disque, pas une étape du parcours.

Après un flash, proposer une **vérification** : relire la carte et comparer le hash
SHA-256 avec celui de l'image source. Facultatif mais c'est ce qui distingue un outil
sérieux d'un script.

---

## 5. Interface

Un assistant linéaire, une étape par écran.

1. **Accueil** — les six étapes du parcours à deux cartes (§4.5/§4.6), **toujours
   toutes visibles et cliquables**, dans leur ordre chronologique fixe A→F. Chaque
   tuile porte un statut informatif (faisable / déjà faite / non pertinente pour la
   carte branchée) qui guide sans jamais rien masquer ni verrouiller. La sauvegarde
   complète de l'image disque est une tuile séparée, en dehors de cette liste — une
   opération de sécurité, pas une étape du parcours. Bouton « Rafraîchir » pour
   relancer la détection sans changer d'écran.
2. **Choix du périphérique** — liste des cartes détectées : modèle, taille, bus.
   Bouton « Rafraîchir ». Aucune sélection par défaut — même quand une seule
   carte est branchée, et même pour l'étape F qui n'ouvre pas d'écran Fichier
   ensuite.
3. **Choix du fichier** — image source pour le flash, fichier de sortie pour la
   sauvegarde ; pour les étapes A/B (extraction), un dossier de destination
   avec `~/Documents/R36S Studio/` proposé par défaut mais toujours
   remplaçable (y compris par un disque externe) — le nom horodaté à
   l'intérieur reste automatique ; pour les étapes D/E (injection sur la carte
   neuve), une sauvegarde à choisir parmi les archives déjà extraites (§4.4),
   avec un repli « Parcourir… » pour une source manuelle. Seule l'étape F
   (éjection) saute cet écran : elle ne demande rien d'autre que la carte.
4. **Confirmation** — écran rouge récapitulant : *« Toutes les données de
   SanDisk Ultra 128 Go seront effacées. »* + case à cocher obligatoire. Seul le
   flash (étape C) écrit sur le périphérique brut et déclenche cet écran.
5. **Exécution** — barre de progression réelle, débit en Mo/s, temps restant estimé,
   bouton Annuler actif. Absente pour l'éjection (étape F), immédiate.
6. **Résultat** — succès ou erreur lisible (jamais de jargon — voir Vocabulaire),
   bouton « Éjecter la carte ». Pour l'étape F elle-même, confirme explicitement que
   la carte peut être retirée physiquement — jamais un succès silencieux.

**Vocabulaire :** aucun terme technique dans l'interface. Pas de « périphérique bloc »,
pas de `/dev/sdb`, pas de « partition ». On dit « ta carte SD », « les jeux », « le
système de la console ». Le chemin technique — ou tout message brut du backend
(chemin, nom de système de fichiers...) — reste consultable dans un panneau
« Détails » replié sur l'écran Résultat, jamais affiché dans le message principal.

Interface en français, avec les chaînes isolées dans un fichier de traduction dès le
départ (l'anglais viendra vite si tu diffuses la vidéo hors France).

---

## 6. Packaging et diffusion

**Pile :** Python 3.11+, PySide6, PyInstaller.

**Le problème des machines de compilation :** PyInstaller ne sait pas compiler pour un
autre système que celui sur lequel il tourne. Or l'Eee PC est en i686 32 bits — il ne
peut pas produire de binaire Linux moderne, et le MacBook 2015 ne produira qu'un binaire
Intel (qui tournera néanmoins sur Apple Silicon via Rosetta).

**Solution :** GitHub Actions. Trois jobs parallèles (`windows-latest`, `macos-latest`,
`ubuntu-22.04`), chacun produisant son artefact, publiés automatiquement en Release à
chaque tag. C'est gratuit pour un dépôt public et ça règle le problème définitivement.

> ⚠️ **Ordre volontaire (phase 7)** : la CI ne sera mise en place que si la
> construction locale macOS (`packaging/`, voir `packaging/README.md`)
> confirme qu'une vraie `.app` (avec un `Info.plist` et donc une identité de
> bundle) fait disparaître le blocage TCC sur `/dev/rdiskN` documenté depuis
> la phase 4 (§3). Automatiser la production d'un binaire avant de savoir
> s'il résout le problème qui motive sa construction serait prématuré.
> `packaging/entry.py` + `packaging/r36s_studio.spec` couvrent macOS ; la
> même approche (spec PyInstaller dédié par OS) s'étendra à Windows/Linux
> une fois ce point tranché.

**Signature :**

- **Windows** — sans certificat, SmartScreen affichera un avertissement. Il s'atténue
  avec le nombre de téléchargements. Un certificat coûte 200–400 €/an : à ne pas faire
  au départ.
- **macOS** — sans notarisation (99 $/an), Gatekeeper bloque l'ouverture. Le contournement
  est un clic droit → Ouvrir. À documenter clairement, idéalement dans ta vidéo.
- **Linux** — AppImage, aucun souci de signature.

**Fichier de configuration utilisateur** (`~/.config/r36s-studio/config.json`) : chemins
récemment utilisés, langue, seuil de taille maximale. Jamais de secret.

---

## 7. Feuille de route

| Phase | Contenu | Critère de fin |
|-------|---------|----------------|
| **1** | Module `devices` + `safety`, en ligne de commande uniquement | `python -m r36s_studio list` affiche les SD et **uniquement** les SD, testé sur les 3 OS |
| **2** | Module `imaging` — lecture (backup) avec progression réelle | Une image de la SD est produite et remontable en boucle |
| **3** | Module `imaging` — écriture (flash) + vérification SHA-256 | Une carte flashée démarre réellement sur la R36S |
| **4** | Squelette GUI PySide6 branché sur les phases 1–3 | Backup et flash utilisables sans terminal |
| **5** | Modules `partitions` — injection BOOT et copie de jeux | Les opérations d'injection sont complètes |
| **6** | Extraction BOOT/EASYROMS + éjection (`partitions`/CLI), module `detect` branché sur l'interface | Les six étapes du parcours à deux cartes (§4.5/§4.6) sont toutes visibles, cliquables, et annotées d'un statut faisable/déjà faite/non pertinente |
| **7** | CI GitHub Actions, packaging, documentation, traduction | Trois binaires téléchargeables depuis une Release |

**La phase 1 est la plus importante du projet.** Tant que la détection et le filtrage
de sécurité ne sont pas irréprochables sur les trois systèmes, aucune ligne de code
d'écriture ne doit être écrite.

---

## 8. Tests

- Jeu de données de test : tables de partitions MBR et GPT factices.
- Test manuel obligatoire avant chaque release : brancher un disque dur externe et
  vérifier qu'il **n'apparaît pas** comme carte SD si les critères l'excluent.
- **Mode développement** (`--allow-disk-image` sur les sous-commandes CLI, ou
  `R36S_STUDIO_DEV=1`) : les providers `devices/` excluent par défaut les disk
  images/périphériques loop (une `.dmg` montée sur macOS, un `losetup` sur
  Linux) — sans ce mode, `inject-boot`, `copy-games` et le futur `detect` ne
  sont testables qu'avec une vraie carte SD. Ce mode lève *uniquement* cette
  exclusion : les règles de `safety` (§4.2 — disque système, taille, bus...)
  n'en ont aucune connaissance et restent pleinement appliquées. Toujours
  désactivé en mode worker (`--worker`), donc **jamais accessible depuis la
  GUI** — y compris si la variable d'environnement traîne dans le shell qui
  l'a lancée — et toujours accompagné d'un avertissement affiché (stderr +
  `emit_log`), jamais silencieux.
  > ⚠️ **Bug corrigé sur macOS** : `allow_disk_image` levait bien l'exclusion
  > en aval (`_is_disk_image`) mais une image montée via `hdiutil attach
  > -imagekey diskimage-class=CRawDiskImage -nomount` restait invisible quand
  > même — l'avertissement de mode développement s'affichait, mais
  > `diskutil list -plist physical` exclut les disk images de l'énumération
  > elle-même, avant même qu'`_is_disk_image` ait son mot à dire. Corrigé en
  > retirant aussi le filtre `physical` (→ `diskutil list -plist`) quand
  > `allow_disk_image` est actif. Vérifier ce genre de bug demande de
  > distinguer, dans les fixtures de test, la commande d'énumération filtrée
  > de la non filtrée — un mock qui renvoie la même liste dans les deux cas
  > masque exactement ce défaut (voir `tests/test_devices_macos.py`).
- **Incident corrigé — sous-processus réel exécuté par un test** : un test
  utilisant `/dev/disk3`/`/dev/disk4` comme chemin factice coïncidait avec un
  vrai disque externe branché sur la machine de dev ; une version
  temporairement mal mockée a exécuté un vrai `diskutil mount` dessus. Deux
  mesures structurelles en réponse :
  - Les chemins de périphérique dans les tests utilisent des identifiants
    impossibles à confondre avec du matériel réel (`/dev/fake-disk-test-*`,
    `/dev/fake-loop-test-*`) — sauf quand le code testé dépend du format
    `/dev/diskN`/`/dev/rdiskN` propre à macOS (conversion accès brut, §4.3) ou
    `PhysicalDriveN` propre à Windows : dans ce cas, le préfixe est conservé
    et seul le numéro est rendu implausible (`disk9903`, `PhysicalDrive9902`).
  - `tests/conftest.py` patche `subprocess.run`/`subprocess.Popen` en
    fixture `autouse` sur toute la suite : un appel non mocké lève
    `UnmockedSubprocessError` au lieu d'exécuter quoi que ce soit pour de
    vrai. Les rares tests qui doivent réellement lancer un sous-processus
    (voir `tests/test_gui_elevate.py`) le déclarent avec
    `@pytest.mark.real_subprocess` (marker enregistré dans `pytest.ini`).

---

## 9. Ce que le dépôt ne contient jamais

- Aucun token, aucune clé API
- Aucune ROM, aucun BIOS
- Aucune image système `.img`
- Aucun chemin personnel en dur

L'image ArkOS est soit téléchargée par l'application depuis la source officielle avec
vérification de somme de contrôle, soit sélectionnée par l'utilisateur dans ses fichiers.
