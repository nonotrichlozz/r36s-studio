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

> ⚠️ **Bug corrigé, constaté en usage réel : l'invite mot de passe
> administrateur était redemandée à chaque étape du parcours guidé
> nécessitant l'élévation, plutôt qu'une seule fois pour tout le
> parcours.** Cause : `WorkerRunner.start()` appelait `elevate.
> launch_elevated_worker(...)` sans rien conserver d'un appel à l'autre —
> sur macOS packagé (`MacosAuthorizedProcess`), ça revenait à créer puis
> libérer une nouvelle `AuthorizationRef` (`AuthorizationCreate`/
> `AuthorizationFree`, Security.framework) à chaque worker élevé, forçant
> `AuthorizationExecuteWithPrivileges` à repasser par l'invite à chaque
> fois plutôt que de profiter d'une autorisation déjà accordée.
>
> **Corrigé** en conservant une seule `AuthorizationRef` vivante pour
> toute une session plutôt qu'une par opération :
> `elevate.MacosAuthorizationSession` (nouvelle classe) l'obtient une
> fois (`AuthorizationCreate`) et la libère à la fermeture de l'app
> (`close()`, appelé depuis `MainWindow.closeEvent`) ; `_run_authorized`
> accepte désormais un `auth_ref` optionnel et, quand il est fourni, ne
> crée ni ne libère sa propre référence (délégué à l'appelant) —
> `MacosAuthorizedProcess`/`_launch_macos`/`launch_elevated_worker` le
> propagent tous jusqu'à `WorkerRunner`, qui l'extrait d'un
> `macos_auth_session` optionnel passé à son constructeur.
>
> `MainWindow._get_or_create_macos_auth_session()` en possède une seule
> pour toute l'application, créée **au premier besoin** plutôt qu'au
> lancement de l'app ou du parcours guidé lui-même — jamais avant qu'une
> opération élevée ne soit réellement lancée (principe déjà appliqué
> ailleurs dans ce projet : ne jamais demander une permission avant d'en
> avoir besoin). Elle est ensuite réutilisée par tout `WorkerRunner`
> suivant, mode expert et mode assisté confondus — pas seulement au sein
> d'un seul parcours guidé, mais pour toute la durée de vie de la
> fenêtre : enchaîner par exemple une sauvegarde complète puis un flash
> en mode expert ne redemande donc désormais qu'une seule fois l'invite,
> pas deux.
>
> Portée volontairement limitée à macOS packagé
> (`MacosAuthorizedProcess`) : `osascript` (macOS en développement, ou
> repli si l'API historique disparaissait) ne consomme aucune
> `AuthorizationRef` et n'est pas concerné ; `pkexec`/`sudo` (Linux) et
> UAC (Windows) n'ont pas d'équivalent léger de ce genre dans ce
> squelette — ce correctif ne change donc rien pour ces deux OS, qui
> continuent de redemander l'élévation à chaque worker élevé comme
> avant. Une `MacosAuthorizationSession` non créable (`OSError`, ex.
> Security.framework indisponible) retombe silencieusement sur le
> comportement d'origine (une référence par opération) plutôt que
> d'empêcher l'opération.

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

> ⚠️ **Écart constaté en documentant la fonctionnalité ci-dessous** :
> `.img.zip` n'a en réalité jamais été implémenté —
> `image_source.SUPPORTED_EXTENSIONS` ne couvre que `.img`/`.img.gz`/
> `.img.xz`. Un `.zip` choisi pour le flash échoue donc aujourd'hui avec le
> message générique de format non supporté (ci-dessous), jamais avec une
> décompression réussie. Non corrigé pour l'instant (pas demandé) — signalé
> ici pour que la ligne ci-dessus ne serve pas de source de vérité erronée
> à une future session.

> **Détection du format par octets d'en-tête, pas seulement l'extension
> (phase 8).** Les images ArkOS sont distribuées en `.7z` — jusqu'ici,
> choisir ce fichier pour le flash échouait avec un message générique et
> peu clair (`error_generic`, "Une erreur est survenue.", faute d'un code
> d'erreur dédié). Pire : un `.7z` renommé en `.img` (une confusion facile
> pour un néophyte) n'était même pas détecté — `open_image_source`
> décidait uniquement sur l'extension et aurait écrit l'archive telle
> quelle sur la carte, silencieusement incorrect (règle §2 n°5/n°6).
>
> `image_source._detect_format` lit désormais les premiers octets du
> fichier (signatures gzip `1F 8B`, xz `FD 37 7A 58 5A 00`, zip
> `50 4B 03 04`, 7z `37 7A BC AF 27 1C`) plutôt que de se fier à
> l'extension ; `check_image_format` en tire `SevenZipArchiveError`
> (message dédié) ou `UnsupportedImageFormatError` (générique, ex. `.zip`
> ci-dessus). Appelé à **deux endroits** :
> 1. **`imaging/flash.py::flash_device`**, en tout premier — avant
>    `prepared_write_target` — pour ne jamais démonter/préparer la carte
>    pour une source déjà connue comme inutilisable (règle §2 n°6). Couvre
>    le CLI direct et sert de filet de sécurité si la GUI est contournée.
> 2. **`gui/main_window.py::_on_file_chosen`**, juste après le choix du
>    fichier pour le flash — *avant* même la fenêtre Confirmation, et donc
>    avant toute élévation de privilèges (§3). Sans ce doublon côté GUI,
>    un fichier invalide coûterait à l'utilisateur une demande de mot de
>    passe administrateur pour un échec connu d'avance.
>
> Message affiché (`gui/strings.py`, §5 vocabulaire) : *« Ce fichier est
> une archive 7-Zip. Décompresse-la d'abord — tu obtiendras un fichier
> .img que tu pourras flasher directement. »* Le worker élevé (CLI) émet
> les codes `SEVEN_ZIP_ARCHIVE`/`UNSUPPORTED_IMAGE_FORMAT` (`__main__.py`,
> `protocol.py`) que `friendly_error_message` traduit côté GUI si jamais
> ce chemin est atteint malgré la vérification préalable.
>
> **Prévenir avant même le téléchargement** : `FileDialog` (flash, firmware
> ArkOS uniquement) affiche désormais en permanence, sous le bouton « Voir
> les versions disponibles en ligne », un rappel — *« Le fichier téléchargé
> sera une archive .7z : décompresse-la d'abord, puis choisis ici le
> fichier .img qu'elle contient. »* — pour qu'un débutant sache quoi faire
> avant de se retrouver bloqué avec un fichier que le logiciel refuse,
> plutôt qu'après coup seulement via le message d'erreur ci-dessus.
>
> **Décompression native du `.7z` (py7zr) envisagée, non retenue.**
> Deux obstacles, l'un architectural et l'autre de poids :
> - **Streaming.** `open_image_source`/`copy_range` (§4.3 ci-dessus)
>   décompressent `.gz`/`.xz` en flux, bloc par bloc, sans fichier
>   temporaire — c'est ce qui permet de flasher une image de plusieurs Go
>   sans espace disque supplémentaire. py7zr expose une API d'extraction
>   (`SevenZipFile.read()`/`extractall()`) qui matérialise le contenu en
>   mémoire ou sur disque plutôt qu'un flux lisible bloc par bloc comme
>   `gzip.open`/`lzma.open` — l'intégrer proprement demanderait soit de
>   charger l'image entière en mémoire (rédhibitoire pour 2-6 Go, §1),
>   soit d'extraire vers un fichier temporaire (doublant l'espace disque
>   nécessaire, et contraire au principe "sans fichier temporaire" déjà en
>   place pour `.gz`/`.xz`).
> - **Poids.** py7zr tire plusieurs dépendances C (`pyzstd`, `pyppmd`,
>   `pycryptodomex`, `brotli`...) pour couvrir tous les filtres 7-Zip
>   possibles, alors qu'un seul (LZMA2) est en jeu ici — poids ajouté au
>   binaire empaqueté (§6) sur les trois OS, pour un problème qu'un
>   message clair au bon moment résout déjà sans nouvelle dépendance.
>
> Ni l'un ni l'autre n'est bloquant en soi, mais combinés ils ne justifient
> pas le coût face à la solution déjà en place (détection + message +
> avertissement préalable, ci-dessus). À revisiter si l'utilisateur le
> demande explicitement malgré ce compromis — l'évaluation n'a pas été
> vérifiée en installant réellement py7zr dans ce dépôt (pas d'accès
> réseau au moment d'écrire cette note) : le poids exact des dépendances
> et les capacités précises de l'API de streaming restent à confirmer si
> cette décision est reconsidérée.

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

> ⚠️ **Confirmé sur du vrai matériel** : sur certaines cartes R36S d'origine,
> la partition de démarrage est dans un schéma **GPT** dont la première
> partition est de **type EFI** (System Partition), avec malgré tout un
> **FAT16 tout à fait valide** à l'intérieur — `Image`, `uInitrd`,
> `extlinux/`, les `.bmp` de batterie et les `.dtb` (relevé exact :
> `disk2s1` type EFI « NO NAME » 536,9 Mo FAT16, puis `disk2s2` Linux, puis
> `disk2s3` Microsoft Basic Data « EASYROMS »). **macOS refuse de monter
> cette partition automatiquement à cause de ce type** — `diskutil mount`
> échoue — et son sondage de système de fichiers pour ce cas précis n'est
> pas toujours fiable non plus (`_macos_filesystem` peut renvoyer une
> chaîne vide, contrairement au cas NTFS ci-dessus où `FilesystemType` finit
> toujours par contenir une variante exploitable). Un montage forcé, lui,
> fonctionne : `sudo mount -t msdos /dev/diskNs1 /Volumes/POINT` donne accès
> à tous les fichiers, .dtb compris.
>
> **Corrigé en deux temps**, tous deux dans `locate.py` :
> 1. `PartitionInfo` porte désormais un champ `partition_type` (type de
>    partition GPT/MBR, ex. `"efi"` — distinct du système de fichiers),
>    renseigné sur macOS depuis `Content` (`_macos_partition_type`).
>    `_select_boot` accepte la première partition dès que ce type vaut EFI
>    et que le système de fichiers, quand il est connu, n'est pas
>    explicitement autre chose qu'un FAT (`_looks_like_efi_boot`) — couvre
>    aussi bien le cas où `_macos_filesystem` échoue à identifier le FAT
>    (chaîne vide) que le cas où il y parvient malgré tout.
> 2. `_mount_macos` retente, quand `diskutil mount` échoue, un montage
>    forcé (`_force_mount_macos` : `mount -t msdos` sur un point de montage
>    temporaire, `tempfile.mkdtemp`) — seulement si le système de fichiers,
>    quand il est connu, est un FAT (jamais pour une NTFS/ext4 dont l'échec
>    aurait une autre cause). `unmount_forced` démonte proprement ce
>    montage temporaire et supprime son dossier une fois la partition
>    exploitée — ne fait rien pour un montage `diskutil`/`udisksctl`
>    normal, qui reste géré par le système jusqu'à l'éjection finale comme
>    avant ce correctif. Appelé après chaque usage : `extract_boot`,
>    `extract_easyroms`, `inject_boot`, `copy_games` (`jobs.py`),
>    l'identification de l'étape 2 (`WizardIdentifyRunner`,
>    `gui/partition_runner.py`) et le calcul d'empreinte des étapes 1/4
>    (`compute_boot_fingerprint`, `safety/card_fingerprint.py`).
>
> ⚠️ **Confirmé sur du vrai matériel : le montage forcé lui-même demande
> les droits administrateur.** L'appel non élevé ci-dessus échoue en
> pratique pour la même raison qu'un utilisateur normal ne peut pas monter
> un périphérique brut sans passer par DiskArbitration (§3) — le test
> manuel réussi utilisait `sudo mount -t msdos ...`. `partitions/` reste
> volontairement sans dépendance vers `gui/` (utilisable depuis le CLI,
> testable sans Qt) : `locate.py` expose donc `set_privileged_mount_hook`,
> un point d'extension optionnel (`Callable[[device_path, mountpoint],
> bool]`, `None` par défaut) plutôt qu'un import direct de `gui/elevate.py`.
>
> `gui/main_window.py` l'installe au constructeur, **macOS uniquement**
> (`platform.system() == "Darwin"`, jamais Linux/Windows — `pkexec`/`sudo`
> et UAC n'ont pas cet équivalent léger dans ce squelette, `locate.py`
> retombe sur son comportement non élevé sur ces deux OS comme avant ce
> correctif), avec `MainWindow._mount_boot_privileged` : réutilise
> `_get_or_create_macos_auth_session()` (§3, la même session partagée
> qu'un `WorkerRunner` de backup/flash — jamais une invite mot de passe
> séparée pour ce cas précis) puis délègue à `gui/elevate.py::
> run_privileged_mount`, un nouveau point d'entrée synchrone (contrairement
> à `launch_elevated_worker`, asynchrone et pensé pour la relance du worker
> complet avec son protocole JSON Lines/fichier de progression — une
> commande aussi courte qu'un montage n'en a pas besoin). Réutilise le même
> chemin bas niveau que le worker (`MacosAuthorizedProcess`/
> `AuthorizationExecuteWithPrivileges` si `sys.frozen` et l'API historique
> disponible, `osascript … with administrator privileges` sinon) ; ni l'un
> ni l'autre ne remonte de façon fiable le code de sortie de la commande
> élevée elle-même, donc le succès est vérifié après coup via
> `os.path.ismount(mountpoint)`, jamais supposé du simple fait qu'aucune
> exception n'a été levée. `_force_mount_macos` n'appelle ce repli qu'en
> tout dernier recours, après l'échec du montage forcé non élevé — jamais
> d'invite avant d'en avoir réellement besoin (§5).
>
> **Vérifié séparément** : la reconnaissance d'EASYROMS fonctionne aussi
> sur ce schéma GPT, où son type de partition est « Microsoft Basic Data »
> (confirmé sur du vrai matériel) plutôt que « Windows_NTFS » comme sur les
> cartes MBR (bug déjà corrigé plus haut) — sans changement de code
> nécessaire : `_select_easyroms` la retrouve par étiquette, indépendamment
> de `partition_type`, et `FilesystemType` reste `"ntfs"` pour ce type de
> partition ordinaire (contrairement au cas EFI ci-dessus, `diskutil` le
> probe normalement).

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
> (CLI : message `emit_log` ; GUI : journal de bord permanent, §5, ou boîte de
> dialogue) — jamais un succès silencieux.
>
> **Visibilité des archives en mode assisté (phase 8).** En mode expert,
> l'écran Choix du fichier (ci-dessus) et le résultat de fin d'étape
> montrent déjà le chemin choisi. En mode assisté, le parcours enchaîne les
> étapes sans repasser par cet écran de choix pour les étapes A/B (le
> dossier proposé par défaut est accepté silencieusement,
> `_run_wizard_partition_job`) — sans autre indication, un débutant ne sait
> ni où ses sauvegardes atterrissent pendant la copie, ni si elles sont
> conservées une fois la carte reflashée. Deux ajouts dans
> `gui/main_window.py` :
> - `_start_worker` journalise `"Destination : {chemin}"` dès le début de
>   la copie pour les étapes A/B (`_EXTRACTION_MODES`) — pas seulement au
>   succès final (`_archive_info`, déjà en place) : si l'opération est
>   longue ou échoue en cours de route, l'utilisateur sait déjà où
>   regarder, il n'a pas à attendre la fin.
> - `_finish_wizard` (fin des sept étapes) affiche un récapitulatif dans
>   le journal — chemin complet de l'archive BOOT *et* de l'archive
>   EASYROMS, avec la mention explicite qu'elles sont conservées — plus le
>   bouton de révélation habituel (`LogPanel.finish_success`, déjà utilisé
>   pour A/B individuellement), pointant cette fois vers le dossier parent
>   commun aux deux (`archives.default_archives_dir()`) plutôt qu'une
>   seule des deux archives : un seul bouton ne peut réveler qu'un chemin.
>
> **Dossier de destination en mode assisté, confirmé** : le même que le
> mode expert, `archives.default_archives_dir()` =
> `~/Documents/R36S Studio/` (§4.4 ci-dessus) — le mode assisté ne
> redéfinit rien de spécifique, il appelle la même fonction avec le même
> résultat par défaut.
>
> **Vérifié : aucun nettoyage automatique ne supprime ces archives.**
> `partitions/archives.py` n'expose que `default_archives_dir`/
> `new_archive_path`/`list_archives`/`parse_archive_timestamp` — aucune
> fonction de suppression. Une recherche dans tout le projet
> (`shutil.rmtree`/`os.remove`/`.unlink`/`tempfile`) ne trouve qu'un seul
> appel de suppression sans rapport : `partitions/copy.py` retire un
> petit fichier sonde qu'il vient de créer lui-même pour vérifier qu'un
> point de montage est inscriptible (§4.4, détection NTFS macOS), jamais
> une archive BOOT/EASYROMS. Ces dossiers horodatés sont donc conservés
> indéfiniment, aussi longtemps que l'utilisateur ne les supprime pas
> lui-même — ce qui correspond à l'attente : ce sont ses sauvegardes.

> **Réutilisation d'une sauvegarde déjà connue (phase 8), étapes A/B.**
> Reflasher plusieurs fois la même carte d'origine (essais successifs,
> plusieurs consoles à préparer avec la même carte source) recopiait
> intégralement le BOOT et l'EASYROMS à chaque passage — sur EASYROMS,
> plusieurs Go recopiés inutilement à chaque fois, alors que le contenu
> de la carte source n'a pas changé entre deux passages.
>
> `config.py::AppConfig.archive_records` mémorise désormais, par
> empreinte de carte source (`safety.card_fingerprint`, déjà calculée à
> l'étape 1 pour le garde-fou de l'étape 4, §5 mode assisté), le chemin
> et la date de la dernière archive BOOT/EASYROMS créée — écrasé
> silencieusement à chaque nouvelle extraction (jamais deux
> enregistrements gardés pour la même combinaison carte/label).
> `get_archive_record`/`set_archive_record` encapsulent la lecture/
> écriture ; un fichier de configuration corrompu ou modifié à la main
> retombe sur des enregistrements vides plutôt que de faire planter le
> chargement (même principe que `ui_mode`/`firmware`).
>
> À l'entrée des étapes A/B (`_enter_wizard_extraction_step`), si un
> enregistrement existe pour l'empreinte de la carte source : **vérifie
> d'abord que le dossier référencé existe encore sur le disque**
> (`Path(record["path"]).is_dir()`) — l'utilisateur a pu le déplacer ou
> le supprimer depuis, `config.py` ne mémorisant qu'un chemin, jamais une
> garantie de présence. S'il existe, `screens.py::ArchiveReuseDialog`
> propose trois choix, avec la date et le chemin complet de la
> sauvegarde existante : réutiliser (mis en avant par défaut, bouton
> `role="primary"` et `setDefault(True)`), refaire la sauvegarde
> (relance l'extraction normalement, écrase l'ancien enregistrement une
> fois terminée), ou annuler tout le parcours (jamais une réutilisation
> silencieuse). Un dossier disparu retombe directement sur une nouvelle
> extraction, sans passer par cette fenêtre.
>
> Portée volontairement limitée au mode assisté (`_on_wizard_job_finished`,
> qui est déjà le point d'arrivée spécifique au parcours guidé, distinct
> du générique `_on_worker_finished`) : le mode expert n'a pas de notion
> de carte source « suivie » d'une étape à l'autre (chaque tuile A-F est
> indépendante), donc rien à mémoriser côté empreinte pour ce chemin.

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

> **Statut `PLATFORM_LIMITED` (habillage « poste de commande », phase 8)** :
> `copy_games` (étape E) est en NTFS sur une vraie carte R36S (§4.4) — macOS ne
> monte le NTFS qu'en écriture nulle part, donc cette étape échoue toujours sur
> cet OS, quelle que soit la carte branchée (ou même sans carte du tout). Ce
> n'est pas une question de pertinence pour la carte (`NOT_RELEVANT`), c'est une
> limite de la plateforme : `detect_workflow_status` retourne
> `StepStatus.PLATFORM_LIMITED` pour `copy_games` sur macOS, inconditionnellement,
> prioritaire sur le calcul habituel. L'écran d'accueil l'affiche avec un badge
> orange « PC ou Linux » plutôt que les badges vert/gris habituels.

> **`CardSystem` (phase 8) : reconnaissance ROCKNIX, distincte du
> `CardState` retiré ci-dessus.** Le mode assisté cherchait une structure
> BOOT/EASYROMS façon ArkOS sur *toute* carte source, y compris une carte
> déjà flashée avec ROCKNIX (dépôt alternatif proposé au choix du firmware,
> §5 étape de flash) — ne la trouvant pas dans la forme attendue, le
> parcours guidé échouait avec des messages pensés pour ArkOS
> (« carte fraîchement flashée », erreur de partition introuvable...), sans
> jamais expliquer ce qui avait réellement été trouvé.
>
> **Structure ROCKNIX relevée sur du vrai matériel** : schéma MBR, deux
> partitions seulement — la première étiquetée `ROCKNIX` en FAT32
> (~2,1 Go), la seconde Linux (~29,8 Go), opaque depuis macOS/Windows.
> Aucune partition de jeux séparée : les ROMs vivent dans la partition
> Linux. Conséquence directe : les quatre étapes A (extract_boot), B
> (extract_easyroms), D (inject_boot) et E (copy_games) n'ont **aucun**
> sens sur une carte ROCKNIX, pas seulement le BOOT comme envisagé dans une
> première version de cette note — seuls le flash (C), la sauvegarde
> complète de l'image disque (§4.6, en dehors des six étapes lettrées) et
> l'éjection (F) restent pertinents.
>
> `CardSystem` (`ARKOS`/`ROCKNIX`/`UNKNOWN`) répond à une question plus
> étroite que le `CardState` retiré (ci-dessus) : pas « quelle action
> unique mettre en avant sur toute l'appli », mais « quel système est déjà
> sur cette carte, pour adapter les étapes qui n'ont de sens que pour
> ArkOS ». `detect_card_system(partitions)` reconnaît ROCKNIX par
> l'étiquette de sa partition de démarrage (`ROCKNIX_BOOT_LABEL`, un signal
> fort et gratuit — contrairement à ArkOS, dont la partition BOOT n'a
> jamais d'étiquette, §4.4) ; ArkOS reste reconnu par `looks_like_arkos`
> (vérifié après ROCKNIX, dont la structure ne recouvre de toute façon
> jamais celle d'ArkOS). Ni l'un ni l'autre → `UNKNOWN`. Toujours en
> lecture seule, jamais de montage — même garantie que le reste de ce
> module.
>
> **Mode expert** : `detect_workflow_status` marque désormais les quatre
> étapes A/B/D/E `StepStatus.SYSTEM_INCOMPATIBLE` (prioritaire sur le
> calcul habituel, et sur `PLATFORM_LIMITED` pour `copy_games` — la vraie
> raison sur une carte ROCKNIX est l'absence de partition de jeux, pas la
> limitation NTFS de macOS, moins précise ici) quand la carte est ROCKNIX.
> Badge violet visible « Non applicable — carte ROCKNIX », plutôt que
> `NOT_RELEVANT` (qui n'affiche pas de badge visible, ci-dessus) : sur une
> carte reconnue et un système *connu* qui ne convient pas, l'utilisateur
> doit comprendre pourquoi, pas juste que « ce n'est pas pertinent
> maintenant » comme s'il suffisait d'attendre.
>
> **Mode assisté** (`gui/main_window.py`) : le système de la carte source
> est détecté une fois, à la fin de l'étape 1 (`detect_card_system_for_
> device`, stocké dans `_wizard_source_system`), puis consulté à l'entrée
> de l'étape 2 (`_enter_wizard_identify_step`) :
> - **ROCKNIX** (cas certain, sans ambiguïté) : étapes 2/3 sautées
>   automatiquement (`_skip_boot_easyroms_extraction`, marque IDENTIFY/
>   EXTRACT_BOOT/EXTRACT_EASYROMS faits sans les exécuter), avec une
>   explication dans le journal avant de sauter — jamais un saut
>   silencieux. Le parcours continue directement à l'étape 4 (insertion de
>   la carte neuve).
> - **Système non reconnu** (`UNKNOWN`, ambigu — contrairement à ROCKNIX) :
>   avertissement affiché (journal + statut de l'étape), et le bouton
>   Continuer habituel devient « continuer sans sauvegarde » plutôt que de
>   lancer l'identification (`_wizard_skip_extraction_on_continue`) —
>   l'utilisateur choisit lui-même, l'application ne décide jamais à sa
>   place de continuer sans qu'il l'ait demandé.
> - **ArkOS** : parcours inchangé.
>
> Étape 6 (`_enter_wizard_inject_boot_step`) : si l'extraction a été
> sautée (`_wizard_boot_archive is None`), l'injection n'a rien à
> réinjecter — sautée de la même façon, avec sa propre ligne de journal,
> plutôt que de tenter un job avec une source manquante.
>
> **Jamais un aller simple vers le mode expert** (règle explicitement
> demandée) : dans les deux cas (ROCKNIX ou système non reconnu), le
> parcours guidé continue jusqu'au bout (flash, éjection) — le bouton
> Mode expert reste seulement disponible comme échappatoire volontaire,
> jamais déclenché par l'application elle-même face à une structure
> inattendue.

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

> **Choix du firmware (phase 8), étape C / étape 5 du mode assisté.**
> L'étape de flash propose désormais deux firmwares, avec une courte
> description plutôt qu'un choix technique sec (`gui/screens.py::FileDialog`) :
> **ArkOS / dArkOS**, la configuration classique, et **ROCKNIX**, un système
> plus récent avec le transfert de jeux par USB intégré. Le choix est
> mémorisé d'un lancement à l'autre (`config.py::AppConfig.firmware`,
> `"arkos"` par défaut, même principe que `ui_mode`).
>
> Les deux dépôts ne se prêtent pas au même traitement, ce qui explique la
> dissymétrie entre les deux options :
> - **dArkOS** (`identify/releases.py`) : les images ne sont pas hébergées
>   sur GitHub (elles renvoient vers Mega, Google Drive, OneDrive, un
>   torrent) — comportement inchangé, le bouton se contente d'ouvrir
>   `https://github.com/southoz/dArkOSRE-R36/releases` dans le navigateur,
>   l'utilisateur télécharge et choisit le fichier lui-même.
> - **ROCKNIX** (`identify/rocknix.py`) : le dépôt
>   (`https://github.com/ROCKNIX/distribution/releases`) attache ses
>   images directement à chaque release GitHub — le téléchargement
>   automatique est donc possible. Le module interroge l'API GitHub
>   (`/releases/latest`), sélectionne les assets dont le nom contient
>   `rk3326` (le SoC de la R36S — ROCKNIX publie une image par SoC,
>   partagée par toutes les consoles qui l'utilisent, pas une image par
>   modèle de console), et cherche la somme de contrôle propre à chacun.
>   Le téléchargement lui-même se fait par blocs avec progression réelle
>   et annulation coopérative (même principe que `imaging/copy.py`), sur
>   un thread séparé (`gui/partition_runner.py::RocknixDownloadRunner`) —
>   un appel réseau bloquant sur le thread Qt principal se lirait comme un
>   gel de l'interface, même piège que le montage d'une partition (§4.4).
>   Enregistré dans `~/Documents/R36S Studio/Firmwares/`
>   (`identify/rocknix.default_firmware_downloads_dir`, même convention
>   que `partitions/archives.py`, jamais `~/.config`, §6). Un
>   téléchargement réussi enchaîne directement sur la fenêtre Confirmation
>   (§5), exactement comme un fichier choisi manuellement — le pipeline de
>   flash existant n'a pas besoin de distinguer les deux origines.
>
> ✅ **Nommage des assets vérifié contre une vraie release ROCKNIX**
> (2026-08-01), après une hypothèse initiale non confirmée (précédente
> version de cette note). Pour le RK3326, trois fichiers : deux images
> (`ROCKNIX-RK3326.aarch64-20260801-a.img.gz` et `...-b.img.gz`) et une
> archive du système de fichiers plutôt qu'une image disque
> (`ROCKNIX-RK3326.aarch64-20260801.tar`) — chaque image a son propre
> `.sha256` du même nom (`{image}.sha256`), pas un fichier de sommes
> partagé par la release comme envisagé initialement. **Corrigé en
> conséquence** :
> - `select_r36s_assets` (pluriel — remplace `select_r36s_asset`) ne
>   retient que les `.img.gz` contenant `rk3326`, et exclut explicitement
>   `.tar` et `.sha256`/`.sha256sum` même quand leur nom matche aussi —
>   les extensions génériques `.img.xz`/`.img.zip`/`.img` de la première
>   version n'ont jamais été observées sur une vraie release ROCKNIX et
>   ont été retirées plutôt que laissées comme hypothèse invérifiée.
> - Les deux variantes `-a`/`-b` sont **toutes les deux** remontées à la
>   GUI — leur différence n'est pas connue, et rien n'indique laquelle
>   serait la bonne par défaut. `select_r36s_assets` ne tranche donc
>   jamais tout seul : `gui/partition_runner.py::RocknixListRunner`
>   interroge l'API (thread séparé, même principe que
>   `WizardIdentifyRunner`) puis `screens.py::RocknixVariantDialog`
>   affiche le nom de fichier complet de chaque variante trouvée pour que
>   l'utilisateur choisisse en connaissance de cause — `MainWindow`
>   enchaîne alors sur `RocknixDownloadRunner` avec l'asset et la somme
>   de contrôle correspondants à ce choix précis. **Idée future, pas
>   implémentée** : élucider la différence entre `-a` et `-b` (à partir
>   des notes de release ROCKNIX, ou en la demandant directement au
>   projet) pour, si elle s'avère pertinente pour la R36S précisément,
>   remplacer ce choix manuel par une sélection automatique ou une
>   description plus parlante que le nom de fichier brut.
>
> **Consoles clones et EmuELEC (phase 9), critère validé par l'outil
> officiel ArkOS.** Certaines cartes vendues comme R36S sont en réalité
> des clones (matériel RK3326 différent) sur lesquels les images ArkOS et
> ROCKNIX standard ne démarrent pas — EmuELEC, lui, fonctionne (structure
> relevée sur du vrai matériel : partition de démarrage FAT32 étiquetée
> EMUELEC de 1,1 Go contenant `KERNEL`/`SYSTEM`/`boot.ini`/`extlinux/`,
> partition Linux de 5,4 Go, partition de jeux en FAT32 de 25,5 Go — donc
> inscriptible depuis macOS, contrairement au NTFS d'ArkOS/§4.4).
>
> Le critère de détection est le **nom** du fichier `.dtb` présent sur le
> BOOT, pas son contenu : `rk3326-evb-lp3-v12-linux.dtb` désigne un clone,
> tandis que `rk3326-r35s-linux.dtb`/`gameconsole-r36s.dtb` désignent une
> R36S/R35S standard — confirmé y compris pour une carte relevée avec deux
> `.dtb` au contenu strictement identique (un seul portant le nom du
> clone, §4.4 « BOOT en GPT/EFI » ci-dessus, la même carte). `identify/
> __init__.py::CLONE_DTB_FILENAMES` (ensemble, pas une chaîne unique, pour
> accueillir d'autres clones sans changer la forme du module) est comparé
> à tous les `.dtb` trouvés par `identify_from_boot_directory` —
> indépendamment du `.dtb` retenu pour l'identification normale (`info`,
> premier `.dtb` valide en tri alphabétique, qui peut très bien ne pas
> être celui qui nomme le clone) et indépendamment de la validité de
> parsing (un `.dtb` illisible dont le nom correspond est quand même
> détecté comme clone). `IdentifyResult.is_clone` porte ce signal.
>
> **EmuELEC comme troisième choix de firmware** (`config.py::
> _VALID_FIRMWARES`, `gui/screens.py::FileDialog`) : même comportement
> qu'ArkOS/dArkOS (bouton ouvrant `identify/releases.py::
> EMUELEC_R36S_RELEASES_URL` dans le navigateur — aucune correspondance
> d'assets par SoC vérifiée à ce jour pour EmuELEC, contrairement à
> ROCKNIX, donc pas de téléchargement automatique). Choisissable à tout
> moment, indépendamment d'une détection de clone.
>
> **Orientation à l'étape 2 (identification, §5 mode assisté)** :
> `MainWindow._on_wizard_identify_finished` journalise un avertissement
> clair (`wizard_source_clone_detected`) dès qu'un clone est détecté, et
> mémorise `_wizard_source_is_clone` pour l'étape 5 (flash) qui suit.
> `FileDialog.set_mode(is_clone_console=...)` y affiche un bandeau
> d'avertissement rouge au-dessus des trois choix de firmware et
> présélectionne EmuELEC — même si la configuration persistée pointait
> vers un autre firmware, une console clone détectée l'emporte, ce n'est
> pas qu'une préférence. ArkOS/ROCKNIX restent choisissables : jamais un
> choix imposé, l'utilisateur garde toujours la main (§5). La
> présélection automatique n'émet jamais `firmware_changed` (`blockSignals`,
> même principe que l'initialisation normale du firmware) : elle
> n'écrase donc jamais la préférence persistée tant que l'utilisateur n'a
> pas lui-même interagi avec les boutons.
>
> La commande CLI de diagnostic `identify` (`__main__.py::cmd_identify`,
> texte simple, pas le protocole JSON Lines) affiche aussi ce signal quand
> présent. Le mode expert n'a pas de notion d'identification (pas
> d'équivalent de l'étape 2) : cette orientation n'existe que dans le
> parcours guidé.
>
> **Idée future, pas implémentée** : ROCKNIX fournit un script
> `importpanel.py` qui génère un `mipi-panel.dtbo` à partir d'un `.dtb`
> d'origine (le même type de fichier que celui déjà lu par
> `identify/dtb.py` pour reconnaître le modèle de console, §4.5/§5 étape
> 2). Une fois la console identifiée par notre module `identify`, on
> pourrait imaginer une fonction ultérieure qui invoque `importpanel.py`
> sur le `.dtb` extrait à l'étape A pour produire automatiquement l'overlay
> d'écran ROCKNIX correspondant — mais ceci reste une piste, à explorer
> seulement si l'utilisateur en a besoin.

---

## 5. Interface

> ⚠️ **Refonte de navigation (phase 8)** : l'interface n'était à l'origine
> qu'une succession de six écrans dans un `QStackedWidget` (accueil → choix
> du périphérique → choix du fichier → confirmation → exécution → résultat),
> une étape remplaçant la précédente. Remplacé par une **vue permanente à
> deux colonnes** (`gui/screens.py::MainView`), dont la structure ne change
> jamais, quelle que soit l'opération en cours :
>
> - **Colonne gauche** (`HomeScreen`, largeur fixe ~480 px) : le bandeau de
>   détection, les six étapes A à F, puis la sauvegarde complète sous
>   « Par sécurité » — reste affichée à l'identique en permanence.
> - **Colonne droite** : l'image de la console (`ConsoleArt`) en haut, le
>   journal de bord permanent (`LogPanel`) en bas.
>
> Les choix ponctuels — choix de la carte, choix du fichier/de l'archive,
> confirmation avant écriture, aide macOS — s'ouvrent désormais en
> **fenêtres modales** (`gui/screens.py::Dialog` et ses sous-classes
> `DeviceDialog`/`FileDialog`/`ConfirmDialog`/`HelpDialog`, `QDialog.open()`
> non bloquant plutôt que `exec()`, pour garder le style signal/slot déjà
> utilisé partout ailleurs) **par-dessus** cette vue, jamais en
> remplacement — la structure à deux colonnes reste visible derrière.
> `FileScreen`/`ExecuteScreen`/`ResultScreen` et le `QStackedWidget` qui les
> enchaînait sont supprimés ; leurs rôles sont repris par `FileDialog` et
> par `LogPanel` (progression + résultats, voir plus bas).

1. **Colonne gauche (bandeau + six étapes + sauvegarde)** — un bandeau en
   haut (bordure cyan, coins arrondis) résume la carte détectée : icône de
   console dessinée au `QPainter` (`_ConsoleIcon`, pas une image), modèle et
   taille, bouton « Rafraîchir » aligné à droite, tous sur une seule ligne ;
   une seconde ligne en dessous précise l'état reconnu (« Carte ArkOS
   reconnue », « Carte non préparée », ou « Aucune carte détectée » sans
   carte branchée). En dessous, les six étapes du parcours à deux cartes
   (§4.5/§4.6), **toujours toutes visibles**, dans leur ordre chronologique
   fixe A→F, une ligne par étape (icône lettrée à gauche, titre +
   description au centre, badge de statut à droite, cadre arrondi). Statuts
   (pastilles en forme de capsule) : faisable (vert), déjà faite (gris), non
   pertinente pour la carte branchée (texte seulement, sans badge visible
   dans les faits), ou limitée par la plateforme (orange, « PC ou Linux » —
   §4.5, `StepStatus.PLATFORM_LIMITED`, ex. copier l'EASYROMS sur macOS). Ce
   statut guide sans jamais rien masquer. La sauvegarde complète de l'image
   disque est une ligne séparée sous un titre « Par sécurité », en dehors de
   cette liste — une opération de sécurité, pas une étape du parcours.
   **Cliquables sauf pendant une opération** : `HomeScreen.set_busy(True)`
   désactive alors les six lignes et la sauvegarde (`setEnabled(False)`,
   qui empêche Qt de délivrer les clics — pas seulement l'apparence) et les
   assombrit visiblement (`QGraphicsOpacityEffect`, ~45 % — une simple
   différence de fond QSS via `:disabled` s'est révélée trop proche de la
   surface habituelle pour se voir clairement sur une palette déjà sombre,
   vérifié en comparant des captures avant/après).
2. **Fenêtre Choix de la carte** (`DeviceDialog`) — liste des cartes
   détectées : modèle, taille, bus. Bouton « Rafraîchir ». Aucune sélection
   par défaut — même quand une seule carte est branchée, et même pour
   l'étape F qui n'ouvre pas de fenêtre Fichier ensuite. « Retour » ferme
   simplement la fenêtre (`close()`), sans rien changer à la vue principale
   derrière.
3. **Fenêtre Choix du fichier** (`FileDialog`) — image source pour le
   flash, fichier de sortie pour la sauvegarde ; pour les étapes A/B
   (extraction), un dossier de destination avec `~/Documents/R36S Studio/`
   proposé par défaut mais toujours remplaçable (y compris par un disque
   externe) — le nom horodaté à l'intérieur reste automatique ; pour les
   étapes D/E (injection sur la carte neuve), une sauvegarde à choisir
   parmi les archives déjà extraites (§4.4), avec un repli « Parcourir… »
   pour une source manuelle. Seule l'étape F (éjection) saute cette
   fenêtre : elle ne demande rien d'autre que la carte.
4. **Fenêtre Confirmation** (`ConfirmDialog`) — fond rouge, récapitulatif
   explicite : *« Toutes les données de SanDisk Ultra 128 Go seront
   effacées. »* + case à cocher obligatoire. Seul le flash (étape C) écrit
   sur le périphérique brut et déclenche cette fenêtre. Annuler ferme la
   fenêtre sans démarrer l'opération, sans rien changer derrière.
5. **Journal de bord permanent** (`LogPanel`, bas de la colonne droite) —
   remplace les anciens écrans Exécution et Résultat, tous deux supprimés :
   tout se passe dans ce panneau, toujours visible, jamais un écran séparé.
   Cadre à bordure cyan, fond très sombre, texte vert clair en police
   monospace pour les lignes du journal (seul endroit de toute l'interface
   en dehors des libellés généraux). En-tête « OPÉRATION ACTIVE » suivi du
   nom de l'étape en cours pendant une opération, ou « En attente » au
   repos. Barre de progression réelle (débit en Mo/s, temps restant estimé)
   sous l'en-tête pendant une opération, bouton Annuler actif à côté du
   titre. En dessous, les lignes horodatées défilent automatiquement au
   format `21:44:02 - Montage des partitions: OK` et s'accumulent pour la
   durée de l'opération en cours — vidées seulement au démarrage de la
   suivante (`start_operation`), jamais entre-temps. Les résultats de fin
   d'opération (succès ou erreur, jamais de jargon — voir Vocabulaire)
   s'affichent comme une ligne de plus dans le journal, avec les actions
   qui suivaient auparavant sur l'écran Résultat réapparaissant dans
   l'en-tête : bouton Éjecter après une opération qui a écrit sur la carte,
   bouton Afficher dans le Finder/l'Explorateur après une extraction ou une
   injection. Pour l'étape F (éjection, immédiate — aucune progression),
   confirme explicitement dans le journal que la carte peut être retirée
   physiquement, jamais un succès silencieux.

**Vocabulaire :** aucun terme technique dans l'interface. Pas de « périphérique bloc »,
pas de `/dev/sdb`, pas de « partition ». On dit « ta carte SD », « les jeux », « le
système de la console ». Le chemin technique — ou tout message brut du backend
(chemin, nom de système de fichiers...) — n'est jamais dans le message principal :
il suit comme ligne supplémentaire dans le journal de bord (`LogPanel.finish_error`)
— plus de panneau « Détails » séparé à déplier depuis la refonte de navigation
ci-dessus, un journal étant par nature un endroit où tout finit par être visible.

Interface en français, avec les chaînes isolées dans un fichier de traduction dès le
départ (l'anglais viendra vite si tu diffuses la vidéo hors France).

**Habillage visuel (phase 8) : `gui/theme.py`.** Palette « poste de commande »
sombre et technique, inspirée des interfaces de console de jeu rétro — fond très
sombre, surfaces légèrement plus claires, bordures cyan fines, une seule couleur
d'accent (le cyan, réutilisée pour les bordures actives, les barres de
progression et les icônes). Aucune lueur, ombre portée ni dégradé — Qt les rend
mal (aliasing grossier) et ça nuit à la lisibilité sur une palette déjà sombre.
Toute la palette vit dans ce seul fichier, sous forme de constantes nommées ;
`gui/app.py` applique la feuille de style QSS qui en résulte une fois,
globalement (`QApplication.setStyleSheet`). Les écrans (`gui/screens.py`) ne
posent jamais de couleur en dur : ils fixent un rôle (`role`, ex. `"title"`,
`"secondary"`, `"row"`, `"log"`, `"danger"`) ou un statut de badge
(`badgeKind`) via `setProperty`, et la feuille de style décide de l'apparence à
partir de là — `theme.repolish(widget)` doit être appelé après tout
`setProperty` sur un widget déjà affiché (Qt ne réévalue les sélecteurs
`[propriété="valeur"]` qu'au moment où le style est recalculé).

> ⚠️ **Piège Qt rencontré en construisant cet habillage** : un `QWidget` nu
> n'honore `background-color` en feuille de style que si l'attribut
> `WA_StyledBackground` est posé — sans lui, le fond ne se peint que par
> accident, quand l'écran a un parent qui le peint à sa place (vrai dans
> `MainWindow`/`QStackedWidget`, faux dès qu'un écran est affiché seul, ex. un
> rendu isolé pour vérification visuelle — confirmé en capturant chaque écran
> en image hors écran, `QWidget.grab()`, avant de constater le fond gris clair
> par défaut du système plutôt que le fond sombre voulu). `screens.Screen`,
> classe de base commune à tous les écrans, pose cet attribut une fois pour
> toutes plutôt que de compter sur le contexte d'affichage.

**Second passage, sur maquette de référence.** Coins arrondis sur le bandeau de
détection et les lignes d'étape (`border-radius: 10px`, contre 4px avant) et
badges en forme de capsule plutôt que de simple rectangle arrondi. Le bandeau
de détection regroupe désormais, sur une seule ligne : une icône de console
dessinée au `QPainter` (`screens._ConsoleIcon` — pas une image, pour rester
sans dépendance externe), le modèle et la taille de la carte, et le bouton
Rafraîchir aligné à droite ; le bouton Aide (macOS uniquement, §3) est
descendu sur sa propre ligne, en dessous.

> ⚠️ **Illustration décorative, remplacée par la refonte de navigation
> (phase 8).** La console R36S (`gui/assets/console.png`) pulsait
> auparavant en fond discret de l'accueil (10 % à 16 % d'opacité,
> `QPropertyAnimation`) ; elle est désormais affichée en grand, bien
> visible, à une opacité fixe d'environ 70 % — en haut de la colonne
> droite (`screens.ConsoleArt`), toujours à l'écran, sans animation.
> `ConsoleArt.resizeEvent` la remet à l'échelle (`Qt.KeepAspectRatio`,
> jamais déformée) à chaque redimensionnement de la fenêtre.

**Deux illustrations décoratives, chacune avec son propre rôle
(`gui/assets/`, `gui/asset_paths.py`) :**

- **`console.png`** (`screens.ConsoleArt`, assemblée avec `screens.ConsoleBasePlate`
  dans `screens.ConsoleStage`) : la console R36S détourée, en haut de la colonne
  droite, à ~70 % d'opacité fixe peinte à la main dans `paintEvent`
  (`painter.setOpacity`, pas un `QGraphicsOpacityEffect` — ce slot d'effet est
  réservé au halo animé, voir ci-dessous).
- **`circuit.png`** (`screens.WindowBackdrop`) : un motif de circuit
  imprimé, sur **toute la fenêtre**, derrière les deux colonnes, à 15 %
  d'opacité fixe — répété en mosaïque (`QPainter.drawTiledPixmap`, jamais
  mis à l'échelle) pour rester net à n'importe quelle taille de fenêtre,
  contrairement à une image étirée. Les panneaux des colonnes (bandeau,
  lignes d'étape, journal de bord — tous à fond opaque, `theme.py`) restent
  donc lisibles par-dessus, quelle que soit la zone qu'ils recouvrent.
  Assemblé par `screens.MainView`, qui l'envoie derrière (`lower()`) avant
  d'ajouter les deux colonnes.

Toutes deux : jamais cliquables (`WA_TransparentForMouseEvents`), et absentes
sans lever d'exception si le fichier correspondant n'existe pas
(`asset_paths.asset_path`, retourne `None` — l'interface s'affiche
normalement sans elles, vérifié par test). `packaging/r36s_studio.spec`
n'inclut chaque image dans le binaire empaqueté que si elle est présente au
moment de la construction, même principe — vérifié de bout en bout sur le
vrai binaire pour `console.png` (`sys._MEIPASS` résout bien `gui/assets/`
une fois empaqueté, via le même mécanisme que l'horodatage de construction,
§5 plus haut).

> ⚠️ **Dérogation délibérée à la contrainte « jamais de dégradé ni de
> lueur ».** Cette règle, posée pour le premier habillage (ci-dessus),
> visait les aplats de l'interface elle-même (boutons, bandeaux, badges) —
> Qt les rend mal. Elle a été explicitement levée, sur demande, pour un seul
> élément décoratif : la console de la colonne droite porte deux effets
> lumineux permanents, tous deux peints en Qt pur, sans image
> supplémentaire.
>
> - **Socle lumineux** (`screens.ConsoleBasePlate`) : une ellipse aplatie
>   sous la console (~70 % de sa largeur), peinte via `QRadialGradient`
>   (cyan → transparent) dans `paintEvent` — technique de repère mis à
>   l'échelle (`painter.scale`) pour obtenir un dégradé radial elliptique à
>   partir d'un `QRadialGradient` qui n'accepte qu'un rayon unique. Son
>   opacité pulse entre 25 % et 55 % sur un cycle de 3 s.
> - **Halo** (`ConsoleHalo`) : une ellipse plus large que la console,
>   centrée derrière elle, peinte comme le socle (`QRadialGradient` cyan →
>   transparent). Son opacité pulse entre 15 % et 38 % sur un cycle de 4 s.
>   Peinte plutôt qu'un `QGraphicsDropShadowEffect` — voir le correctif de
>   performance ci-dessous, c'est le second essai de cet élément.
> - **Flottaison** : la console se déplace de ±6 px sur un cycle de 6 s, via
>   une propriété `floatOffset` animée qui décale le point de dessin dans
>   `paintEvent` plutôt que la géométrie du widget (évite tout conflit avec
>   le système de layout).
>
> Les trois animations (`QPropertyAnimation`, `QEasingCurve.InOutSine`,
> boucle infinie) sont regroupées dans un unique `QParallelAnimationGroup`
> (`ConsoleStage._group`) pour une pause/reprise centralisée. Le socle et le
> halo sont volontairement déphasés (périodes différentes, 3 s vs 4 s, plus
> un décalage de départ explicite sur l'animation du halo,
> `setCurrentTime(cycle // 2)`) pour qu'ils ne « respirent » jamais à
> l'unisson. `ConsoleStage.pause()`/`.resume()` sont appelés par
> `MainWindow` autour de chaque opération disque (`_start_worker`/
> `_on_worker_finished`) pour ne pas consommer de ressources pendant une
> écriture. Un réglage (case à cocher « Animations de la console »,
> `MainView.animation_toggle`) permet de les désactiver complètement —
> `set_animations_enabled(False)` arrête le groupe et remet les trois
> valeurs à leur état de repos plutôt que de les figer à une valeur
> intermédiaire arbitraire.

> ⚠️ **Correctif de performance, constaté en conditions réelles :
> l'animation de la console saccadait fortement.** Cause : le halo
> d'origine (ci-dessus) était un `QGraphicsDropShadowEffect` — Qt
> recalcule le flou gaussien de cet effet à chaque repeint du widget
> source, quel que soit le rayon demandé, et la flottaison changeait
> justement l'apparence de `ConsoleArt` en continu (donc un recalcul de
> flou à chaque frame). Trois correctifs, tous dans `screens.py` :
>
> 1. **Le halo n'est plus un `QGraphicsEffect`.** `ConsoleHalo` (ci-dessus)
>    le remplace par une ellipse peinte, sur le même principe que le socle
>    -- seule l'opacité s'anime (entre 15 % et 38 %), plus de rayon de flou
>    à recalculer.
> 2. **Le dégradé radial est mis en cache.** `_RadialGlowWidget`, classe de
>    base commune à `ConsoleBasePlate` et `ConsoleHalo`, ne reconstruit son
>    `QRadialGradient` que dans `resizeEvent` (peint une fois dans un
>    `QPixmap` mis en cache) — jamais depuis le setter de `glowOpacity`.
>    `paintEvent` se limite à un `drawPixmap` + `painter.setOpacity`.
> 3. **Le repeint est cadencé et limité en surface.** Les setters de
>    propriété (`floatOffset`, `glowOpacity`) ne déclenchent plus eux-mêmes
>    de `update()` — `QPropertyAnimation` met sinon à jour ses valeurs à la
>    fréquence du taux de rafraîchissement de l'écran, bien plus vite que
>    nécessaire pour une respiration sur plusieurs secondes.
>    `ConsoleStage._repaint_timer`, un `QTimer` cadencé à 33 ms
>    (~30 images/seconde), impose un unique repeint groupé par tick, limité
>    à `_console_update_rect` (union de la console, de son halo et de son
>    socle, recalculée dans `resizeEvent`) plutôt que `self.rect()` (qui
>    couvrirait toute la zone du haut de la colonne droite, marges vides
>    comprises) — et à plus forte raison jamais toute la fenêtre. Ce
>    minuteur ne tourne que pendant que le groupe d'animations tourne
>    réellement : arrêté dans `pause()` (déjà appelé autour de chaque
>    opération disque) et à la désactivation du réglage, démarré dans
>    `resume()`.
>
> **Vérifié** : mesure de charge CPU (`resource.getrusage`, backend Qt
> `offscreen`) sur `MainWindow` au repos, animations actives, sur 15 s :
> environ 7 à 9 % d'un cœur, entièrement imputable à la boucle de repeint
> de la console (retombe à 0 % avec `set_animations_enabled(False)`,
> confirmé en isolant la mesure). Ce chiffre est probablement surestimé
> par rapport à un vrai écran : le backend `offscreen` rasterise tout en
> logiciel à chaque repeint, sans la compositing GPU dont bénéficierait un
> affichage réel — mais aucun écran physique n'était disponible pour
> confirmer un chiffre définitif en conditions réelles.

> ⚠️ **Bug corrigé, constaté en conditions réelles : le bas de la console
> tronqué net (rognée sous les joysticks) et le socle lumineux jamais
> visible du tout — uniquement sur l'accueil du mode assisté, jamais sur
> la colonne droite du mode expert.** Confirmé en désactivant le réglage
> « Animations de la console » : l'image s'affichait alors entière,
> pointant directement vers la flottaison (`floatOffset`) comme cause.
>
> Cause réelle : `ConsoleStage.resizeEvent` donnait à `ConsoleArt` tout
> `self.rect()`, sans aucune marge réservée, avant de mettre le pixmap à
> l'échelle (`Qt.KeepAspectRatio`). Quand la hauteur de la boîte devient la
> contrainte liante du redimensionnement proportionnel — le cas sur
> l'accueil du mode assisté, dont la `ConsoleStage` est délibérément « plus
> grande, plus carrée » (note plus haut) que celle, plus large que haute,
> du mode expert — le pixmap scalé remplit *exactement* toute la hauteur
> du widget, laissant zéro marge : `floatOffset` pousse alors le bas de la
> console hors des limites de peinture du widget dès qu'il devient positif
> (Qt rogne toute peinture au-delà du rect propre d'un widget), et le halo/
> le socle (calculés à partir de cette même hauteur rendue, sans marge) se
> retrouvent positionnés hors des limites de `ConsoleStage` lui-même —
> rognés à leur tour, puisque Qt rogne aussi un widget enfant aux bornes de
> son parent.
>
> **Corrigé à deux niveaux, complémentaires :**
> 1. `ConsoleArt.resizeEvent` met désormais à l'échelle vers une taille
>    cible réduite de `2 * _FLOAT_AMPLITUDE` en hauteur (au lieu de
>    `self.size()` telle quelle) — garantit `rendered.height() <=
>    self.height() - 2 * amplitude`, donc au moins l'amplitude de marge de
>    chaque côté *dans les limites propres du widget*, quelle que soit la
>    contrainte liante. Fixe le rognage du bas de la console.
> 2. `ConsoleStage.resizeEvent` réserve en plus une marge verticale (haut
>    et bas) *autour* de la boîte donnée à `ConsoleArt`, dérivée des mêmes
>    constantes que la taille du halo (`_HALO_SCALE`, jusqu'à 17,5 % de la
>    hauteur rendue au-delà du haut et du bas de la console) et du socle
>    (`_PLATE_WIDTH_RATIO`/`_PLATE_HEIGHT_RATIO`) — calculée à partir des
>    dimensions du widget lui-même plutôt que de la taille rendue (majorants
>    sûrs, la console rendue ne pouvant jamais dépasser la boîte qu'on lui
>    donne), pour éviter la dépendance circulaire entre marge réservée et
>    taille rendue. Fixe l'invisibilité du socle et un éventuel rognage du
>    halo.
>
> `ConsoleArt._FLOAT_AMPLITUDE` devient la source de vérité unique (déplacé
> depuis `ConsoleStage`, qui la référence désormais) : `ConsoleArt` en a
> besoin pour sa propre réserve de marge (point 1), `ConsoleStage` pour la
> sienne (point 2). Vérifié par des tests couvrant plusieurs formes de
> boîte (plus haute que large, plus large que haute, très petite) balayant
> tout le cycle de `floatOffset`, pas seulement ses deux bornes
> (`tests/test_gui_screens.py`).

> ⚠️ **Trois régressions du correctif ci-dessus, corrigées à nouveau,
> constatées en conditions réelles après coup.** (1) La console avait
> disparu de l'accueil du mode assisté (seul le bouton « Préparer ma carte
> automatiquement » restait visible). (2) En mode expert, la console était
> devenue nettement plus petite qu'avant le premier correctif. (3) Le
> défaut de découpe persistait, différemment : pendant la flottaison, une
> partie de l'image restait fixe pendant que le reste montait/descendait
> — un morceau semblait se détacher ou s'enfoncer selon le sens du
> mouvement.
>
> **Causes réelles, trois bugs distincts :**
> 1. **(1) et (2), une vraie image (499×500, quasi carrée) contre des
>    boîtes synthétiques dans les tests.** Le calcul de marge du premier
>    correctif estimait la taille du socle/du halo à partir de
>    `self.width()`/`self.height()` (la boîte entière) plutôt que de la
>    taille *rendue* réellement — un majorant délibérément généreux
>    « pour ne jamais être insuffisant », mais qui surestimait
>    grossièrement dès que la console est engendrée par la hauteur (le
>    cas normal : une image quasi carrée dans une boîte plus large que
>    haute, en mode expert *comme* sur l'accueil assisté — l'hypothèse
>    initiale que le mode expert avait une marge naturelle suffisante
>    était fausse). Sur l'accueil (boîte plus grande), la surestimation
>    mangeait toute la hauteur disponible ; en mode expert, elle
>    rétrécissait fortement sans l'annuler complètement.
>
>    **Corrigé** par un calcul en deux passes, purement mathématique
>    (`_fit_within_aspect_ratio`, réplique `QPixmap.scaled(...,
>    Qt.KeepAspectRatio)` par le calcul) : une première passe estime le
>    rendu *naturel* (sans marge) pour dériver des tailles de socle/halo
>    réalistes, puis les marges réservées ne descendent jamais sous la
>    marge déjà présente naturellement (`max(marge_naturelle,
>    marge_requise)`) — de quoi éviter de rétrécir une boîte qui
>    contenait déjà tout, et de ne réserver que ce qui manque vraiment
>    sinon. Réserve aussi une marge *horizontale* (pas seulement
>    verticale) : le halo étant `_HALO_SCALE` fois plus large que la
>    console, son bord peut dépasser `self.width()` dès que la console
>    s'ajuste par la largeur, ce qu'une réserve uniquement verticale ne
>    couvrait pas.
>
>    Ce calcul en deux passes a révélé un piège Qt distinct au passage :
>    lire `ConsoleArt.rendered_size()` juste après `setGeometry()`,
>    *depuis l'intérieur du `resizeEvent` d'un widget parent*, peut
>    refléter l'état *précédent* — Qt diffère alors la livraison du
>    `resizeEvent` de l'enfant plutôt que de l'envoyer immédiatement
>    (constaté en conditions réelles : le calcul lisait `(0, 0)`, une
>    valeur périmée, menant à des tailles de socle grossièrement fausses
>    — ex. un socle large de 450px pour une console rendue à 184px). Ce
>    piège ne se manifestait pas dans les tests unitaires les plus
>    simples (`ConsoleStage` redimensionnée directement, hors de tout
>    layout parent), où `setGeometry` livre bien `resizeEvent`
>    immédiatement — d'où son absence de détection avant la vraie
>    application. `_fit_within_aspect_ratio` (calcul pur, indépendant de
>    tout événement Qt) contourne le problème plutôt que de tenter de le
>    résoudre : `setGeometry` reste appelé pour que Qt peigne
>    effectivement le bon résultat dès que l'événement différé arrive,
>    mais plus aucun calcul de `ConsoleStage` n'attend cette livraison.
> 2. **(3)** `ConsoleBasePlate` avait une géométrie fixe, calculée une
>    fois dans `resizeEvent` sans jamais suivre `floatOffset` — la
>    console flottait pendant que son socle restait immobile, donnant
>    l'impression qu'un morceau se détachait ou s'enfonçait selon le sens
>    du mouvement (les deux n'étaient pas dessinés dans le même repère).
>    **Corrigé** : `_repaint_console_area` repositionne désormais le
>    socle (`QWidget.move`, qui ne redéclenche jamais `resizeEvent` —
>    seule la position change, pas la taille, donc aucun recalcul du
>    dégradé mis en cache) à sa position de repos décalée de l'offset
>    courant, exactement comme `ConsoleArt.paintEvent` décale son propre
>    tracé — les deux widgets partagent ainsi la même valeur à chaque
>    tick. `set_animations_enabled(False)` remet aussi le socle à sa
>    position de repos, symétriquement à `floatOffset = 0.0`.
> 3. **(3), également** : le rectangle d'invalidation par tick
>    (`_console_update_rect`, une sous-région calculée) ne suivait pas
>    exactement chaque élément mobile, laissant une partie de l'image
>    sans repeint. **Corrigé** en invalidant `self.rect()` en entier à
>    chaque tick plutôt qu'une sous-région — `ConsoleStage` reste petit
>    et le repeint déjà cadencé à 30 im/s (§5 correctif de performance
>    précédent), le coût reste négligeable ; `_console_update_rect` est
>    retiré, devenu inutile.
>
> **Vérifié** : nombres réels recalculés avec la vraie `console.png`
> (499×500) dans les proportions réelles des deux écrans (mode expert
> ~616×415, accueil du mode assisté ~1072×329) — rendu contenu dans les
> deux cas (socle et halo compris), à une taille visiblement raisonnable
> (~60-70 % de la hauteur disponible), plus grande qu'avec le calcul
> buggé. Captures d'écran (`QWidget.grab()`, backend `offscreen`) des deux
> écrans, animations activées (à `floatOffset` bas/médian/haut) puis
> désactivées : console et halo visibles sur les deux écrans, rien ne
> semble tronqué. Non confirmé sur un vrai écran, faute d'écran physique
> disponible ici (même limite que la mesure de charge CPU plus haut).

> **Mode assisté (phase 8), par défaut au lancement.** Le mode expert
> (six étapes, ci-dessus) reste disponible en entier, mais n'est plus
> l'écran de démarrage — `config.py` (première vraie implémentation de
> `~/.config/r36s-studio/config.json`, §6) mémorise `ui_mode`
> (`"assisted"` par défaut, `"expert"`) d'un lancement à l'autre.
>
> **Accueil** (`gui/screens.py::AssistedLandingScreen`) : sa propre
> `ConsoleStage` (instance séparée de celle de `MainView`, plus grande,
> centrée — les deux écrans ne sont jamais affichés en même temps, donc
> pas de conflit de parent), un bouton cyan plein « Préparer ma carte
> automatiquement » (nouveau rôle `QPushButton[role="cta"]`, `theme.py`)
> et un bouton discret « Mode expert » en haut à droite.
>
> ⚠️ **Corrigé : le mode expert n'avait pas de chemin de retour.** Une
> fois basculé via « Mode expert », rien ne permettait de revenir à
> l'accueil assisté — et `ui_mode` étant persisté (`config.py`),
> l'utilisateur restait bloqué en mode expert même après redémarrage.
> `HomeScreen` porte désormais le bouton symétrique « Mode assisté », en
> haut à droite du titre (même ligne, pas une ligne séparée qui aurait
> repoussé les six étapes) — `MainWindow._switch_to_assisted_mode`
> persiste `ui_mode="assisted"` et ramène directement à
> `AssistedLandingScreen` (pas de notion de parcours à reprendre côté
> mode expert). Vérifié par un test qui traverse la bascule dans les deux
> sens et contrôle que la configuration suit à chaque fois.
>
> ⚠️ **Garde ajoutée : les deux boutons de bascule restaient cliquables
> pendant une opération disque.** Changer de mode en plein flash ou en
> pleine copie laisserait un job orphelin. `HomeScreen.set_busy`
> (existant, désactivait déjà les six étapes) désactive maintenant aussi
> `_assisted_mode_button` ; `AssistedLandingScreen.set_busy` (nouveau,
> même principe) désactive `_expert_button` — gardé défensivement même si
> l'accueil n'est en pratique jamais visible pendant une opération en
> cours dans le déroulé normal, sauf brièvement entre une annulation
> coopérative (`_cancel_wizard`) et l'arrêt effectif du job. `MainWindow`
> appelle les deux `set_busy` ensemble, à l'entrée (`_start_worker`) et à
> la sortie (`_on_worker_finished`) de toute opération passant par ce
> pipeline (backup/flash/extract_boot/extract_easyroms/inject_boot/
> copy_games, mode expert et mode assisté confondus) — pas étendu à
> l'identification (étape 2) ni au calcul d'empreinte (étapes 1/4) : ces
> lectures en arrière-plan ne laissent rien d'orphelin de dangereux si le
> mode change entre-temps, contrairement à une écriture.
>
> ⚠️ **Bug rapporté et corrigé : la carte semblait détectée en mode
> expert mais pas en mode assisté à l'étape 1.** Diagnostic : les deux
> modes appellent la même fonction (`_list_devices_with_diagnostics`, qui
> encapsule `list_devices`/`filter_devices`) — il n'y a jamais eu de
> filtre différent côté assisté. La vraie cause : `_on_wizard_poll`
> n'acceptait de continuer que si `_list_safe_devices()` renvoyait
> *exactement* un candidat ; à plusieurs (ex. un disque USB qui passe le
> filtre §4.2 en plus de la carte SD), `candidate` retombait à `None` —
> indiscernable de « aucune carte », d'où l'impression d'une détection
> cassée alors qu'elle voyait la bonne carte, simplement noyée avec une
> autre. **Corrigé** : au-delà d'un candidat, `_on_wizard_poll` arrête le
> sondage et ouvre la fenêtre Choix de la carte (`DeviceDialog`, la même
> qu'en mode expert) plutôt que de rester bloqué en silence ;
> `_on_device_chosen` reconnaît ce contexte (étape 1/4 en cours) et
> reprend directement le calcul d'empreinte sur la carte choisie, sans
> toucher `self._mode`/`self._device` du mode expert.
>
> **Diagnostic dans le journal** : `safety.describe_rejection` (nouveau,
> mêmes règles que `is_allowed` mais avec la raison) permet à
> `_list_devices_with_diagnostics` de tracer, à chaque sondage dont le
> résultat change, combien de cartes sont retenues et lesquelles sont
> écartées et pourquoi (« carte système », « ni amovible ni en USB »...)
> — dédoublonné par signature pour ne pas noyer le journal d'une ligne
> toutes les 1,5 s en attendant une carte.
>
> **Bouton Rafraîchir, étapes 1/4** : symétrique de celui du mode expert
> (`DeviceDialog`) — relance la recherche immédiatement (sans attendre le
> tick suivant) et redémarre le sondage automatique s'il s'était arrêté,
> notamment après un choix annulé dans la fenêtre Choix de la carte.
>
> **Parcours guidé, une étape à la fois** (`WizardStepPanel`, remplace
> `HomeScreen` dans la colonne gauche de `MainView` — généralisée avec un
> `QStackedWidget` interne, `show_home()`/`show_wizard_panel()`) : sept
> étapes visibles, mais huit *jobs* suivis en interne
> (`gui/wizard_flow.py::WizardFlow`, testable sans Qt) — l'étape 3
> (« Copie de l'écran et des jeux ») recouvre `EXTRACT_BOOT` puis
> `EXTRACT_EASYROMS`, deux jobs indépendants avec chacun leur statut
> fait/pas fait. C'est ce qui garantit qu'après une erreur, « Reprendre »
> ne rejoue jamais un job déjà réussi : `current_job()` reste sur le job
> qui a réellement échoué (le précédent reste marqué fait), même en cas
> de succès partiel — vérifié par un test dédié au scénario exact BOOT
> réussi / EASYROMS en échec.
>
> `MainWindow` orchestre les sept étapes en réutilisant tel quel le
> pipeline `_start_worker`/`_on_worker_finished` du mode expert
> (`PartitionJobRunner` pour extract/inject, `WorkerRunner` pour le
> flash) — un simple drapeau `_wizard_active` décide si la fin
> d'opération avance la machine à états ou suit le chemin expert
> existant. La détection de carte (étapes 1 et 4) interroge
> `list_devices`/`filter_devices` par `QTimer` (1,5 s).
>
> **Garde-fou de l'étape 4** (« insère ta carte neuve ») : comparer
> `path`/`size_bytes` entre la carte de l'étape 1 et celle de l'étape 4
> ne suffit pas — sur macOS le chemin d'un disque peut changer d'un
> branchement à l'autre, et deux cartes du même modèle ont exactement la
> même taille. `safety/card_fingerprint.py` calcule à la place une
> empreinte sha256 du contenu de la partition BOOT (noms de fichiers,
> tailles, contenu tronqué à 64 Ko par fichier), sans élévation (montage
> lecture seule, comme `extract_boot`) — jamais via l'accès brut au
> périphérique, qui exigerait l'élévation (§3) juste pour comparer deux
> cartes à une étape qui n'écrit rien. `is_same_card()` ne conclut à
> l'identité que si les deux empreintes existent et sont égales ; une
> carte vierge (sans BOOT lisible) n'a pas d'empreinte et n'est donc
> jamais prise pour la carte d'origine — l'étape 4 refuse explicitement
> de continuer tant que la carte détectée a la même empreinte que celle
> de l'étape 1.

> ⚠️ **Bug corrigé, signalé par un utilisateur : à l'étape 4, la consigne
> de retirer la carte source s'affichait alors qu'elle était encore
> montée** — la retirer ainsi risque de corrompre des données et
> déclenche un avertissement système. La carte reste nécessairement
> montée pendant les étapes 2 et 3 (lecture des `.dtb`, copie du BOOT et
> d'EASYROMS s'y font depuis cette même carte) ; rien ne la démontait
> ensuite avant d'inviter à la retirer.
>
> **Corrigé** : `MainWindow._enter_wizard_job` traite désormais
> `WizardJob.DETECT_TARGET` à part, via `_run_wizard_source_eject` —
> appelée en tout début de l'étape 4, avant même d'afficher sa consigne
> d'insertion, jamais avant (la carte source doit rester exploitable
> pendant les étapes 2/3, `test_source_card_stays_mounted_during_
> identify_step`/`..._during_extraction_steps` le garantissent). Réutilise
> `partitions/eject.py::eject` (même fonction que l'étape F, §4.4) pour
> démonter toutes les partitions puis éjecter, avant de confirmer dans le
> journal de bord *« Tu peux maintenant retirer ta carte d'origine en
> toute sécurité »* — seulement ensuite la consigne d'insertion de la
> carte neuve s'affiche et le sondage de détection démarre
> (`_wizard_poll_timer.start()`), pour ne jamais risquer de détecter la
> carte source comme si c'était la neuve pendant qu'elle est encore en
> cours d'éjection.
>
> Un échec (volume occupé, partition verrouillée) affiche le message
> explicite existant (`EJECT_FAILED`, déjà utilisé par l'étape F) plutôt
> que de laisser deviner si le retrait est sûr, et bascule le panneau en
> `show_error()` — ce qui fournit gratuitement le bouton Reprendre déjà
> utilisé pour les autres échecs du parcours (§5) : le job DETECT_TARGET
> n'est jamais marqué fait sur un échec d'éjection, donc Reprendre relance
> exactement la même éjection plutôt qu'un nouveau mécanisme dédié.
>
> **Étape 2 (identification)** : `identify.identify_from_boot_directory`
> (scanne les `.dtb` d'un dossier — mountpoint BOOT ici, ou une archive
> déjà extraite en mode expert) tourne sur un thread séparé
> (`WizardIdentifyRunner`, `gui/partition_runner.py`) plutôt que sur le
> thread Qt principal, car `locate_mounted` peut bloquer jusqu'à
> `MOUNT_WAIT_SECONDS` (10 s, §4.4) si le système n'a pas encore monté la
> partition. Annuler pendant l'étape 2 arrête l'affichage mais ne peut pas
> interrompre le thread d'identification déjà lancé (pas de point
> d'annulation coopératif dans `locate_mounted`) — sans risque de
> plantage, le résultat arrive simplement après coup sur un panneau déjà
> quitté.
>
> ⚠️ **Message d'échec affiné : trois causes distinctes plutôt qu'un
> « impossible d'identifier » générique.** `identify.IdentifyResult`
> (`info` + `failure_reason: Optional[IdentifyFailureReason]`) remplace
> le simple `Optional[DtbInfo]` qu'`identify_from_boot_directory`
> renvoyait avant. Trois causes, trois messages :
> - `MOUNT_FAILED` — la partition BOOT elle-même n'a pas pu être montée
>   (décidé par `WizardIdentifyRunner`, avant même d'appeler
>   `identify_from_boot_directory`) : message suggérant explicitement une
>   carte défaillante — fréquent sur les cartes fournies avec la console
>   R36S, constaté en usage réel.
> - `NO_DTB_FOUND` — partition montée et lisible, mais aucun `.dtb`
>   dessus (ex. une carte fraîchement flashée) : le message le dit
>   explicitement et précise que l'identification se refera d'elle-même
>   une fois l'écran d'origine réinjecté (étape 6).
> - `ALL_DTB_INVALID` — des `.dtb` existent mais aucun n'est exploitable :
>   soit `InvalidDtbError`/`OSError` au parsing, soit — affiné depuis la
>   première version — structurellement valide mais sans `compatible`
>   racine (`info.board_compatible` vide/`None`). Un DTB qui « parse »
>   sans rien identifier n'est pas un succès : une identification
>   affichant « Console identifiée : ? » n'aide personne, mieux vaut le
>   traiter comme les autres candidats invalides et continuer à chercher.
>
> Les trois restent non bloquantes (`set_can_continue(True)` dans tous
> les cas) et se terminent par le même repli MultiPanel — seule la partie
> diagnostic du message change. Vocabulaire (§5) : le message principal
> reste sans jargon (« ta carte », jamais « partition »/« .dtb »/
> « BOOT ») ; le mot « défaillante » est le seul terme volontairement
> plus insistant, à la demande explicite d'un utilisateur qui voulait que
> l'appli suggère cette cause précise plutôt que rester vague.
>
> **Journalisé dans tous les cas, succès compris** (« journalise... le
> chemin monté et la liste des fichiers examinés ») : `IdentifyResult`
> porte désormais `scanned_directory`/`examined_files` (toujours
> renseignés par `identify_from_boot_directory`, y compris en cas de
> succès) et `detail` (le message brut de l'exception, uniquement pour
> `MOUNT_FAILED` — rien à scanner dans ce cas, donc pas de
> `scanned_directory`). `_on_wizard_identify_finished` ajoute ces lignes
> au journal après le message principal, jamais dedans (§5 vocabulaire).
>
> **Mode test sans carte physique** : `python -m r36s_studio identify
> --boot-dir DIR` (`cmd_identify`, `__main__.py`) lance
> `identify_from_boot_directory` directement sur un dossier local — pour
> valider le parseur DTB et la future table de correspondance sur des
> variantes de console fournies par d'autres utilisateurs, sans dépendre
> d'une carte réelle. Sortie texte simple, pas le protocole JSON Lines
> (§3) : c'est un outil de diagnostic interactif, jamais piloté par la
> GUI. `MOUNT_FAILED` n'est jamais produit par cette commande (rien à
> monter, `identify_from_boot_directory` ne le renvoie jamais lui-même).
>
> ⚠️ **Corrigé, constaté en conditions réelles : geler l'interface pendant
> le montage se lit comme un plantage.** `_on_wizard_poll` (étapes 1/4)
> appelait `compute_boot_fingerprint` directement sur le thread Qt
> principal — même blocage possible jusqu'à `MOUNT_WAIT_SECONDS` que pour
> l'identification, mais pas encore déplacé sur un thread séparé à
> l'écriture de la note ci-dessus. **Corrigé** : `WizardFingerprintRunner`
> (`gui/partition_runner.py`, même principe que `WizardIdentifyRunner`)
> calcule l'empreinte sur un thread séparé ; `_on_wizard_poll` se contente
> désormais de le démarrer et d'arrêter le sondage le temps du calcul,
> `_on_wizard_fingerprint_ready` reçoit le résultat de façon asynchrone et
> décide ensuite (redémarre le sondage si la carte détectée à l'étape 4
> s'avère être la même qu'à l'étape 1). Vérifié avec un vrai `QThread` non
> mocké (`compute_boot_fingerprint` patché pour répondre vite, boucle
> d'événements Qt réelle) en plus des tests unitaires : le bouton
> Continuer reste désactivé pendant le calcul et se réactive correctement
> une fois le signal cross-thread livré.
>
> **Étape 5 (flash)** : `FileDialog` (identique au mode expert) porte
> désormais un bouton « Voir les versions disponibles en ligne », visible
> uniquement en mode flash, qui ouvre
> `identify/releases.py::DARKOS_R36S_RELEASES_URL`
> (`https://github.com/southoz/dArkOSRE-R36/releases`) dans le navigateur
> par défaut (`webbrowser.open`, `MainWindow._on_releases_requested`).
> Les images n'y sont pas hébergées — la page renvoie vers Mega, Google
> Drive, OneDrive et un torrent, jamais un lien téléchargeable
> directement — donc rien d'autre à automatiser que l'ouverture de cette
> page ; l'utilisateur télécharge lui-même puis choisit le fichier obtenu
> via le sélecteur classique, déjà en place. Un seul dépôt géré (l'app ne
> vise que le R36S) : pas de table de correspondance carte→version à
> construire pour ce bouton.
>
> **Erreur, à n'importe quelle étape** : le parcours s'arrête,
> `LogPanel.finish_error` affiche le message clair (§5, vocabulaire),
> `WizardStepPanel.show_error()` remplace le bouton Continuer par
> Reprendre/Mode expert. Mode expert depuis une étape en erreur ne défait
> rien : une archive BOOT/EASYROMS déjà extraite reste utilisable depuis
> l'étape D/E du mode expert.

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
