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

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : `ELEVATION_FAILED`
> affiché à tort alors que l'élévation Windows réussissait, masquant un
> refus légitime du worker.** Rapporté comme un `ELEVATION_FAILED`
> systématique après ~12 s d'attente. Lancé à la main en administrateur
> (`py -m r36s_studio backup ...`), le worker émettait en réalité
> correctement `{"type":"error","code":"GAMES_PARTITION_NOT_FOUND"}` --
> carte cible de 32 Go branchée, sans partition de jeux : un refus
> légitime (§4.3), pas un défaut d'élévation. Le vrai problème : ce
> message n'atteignait jamais la GUI, qui affichait `ELEVATION_FAILED` à
> la place.
>
> Cause : `protocol.py::emit_error` écrit déjà l'événement dans le fichier
> de progression (`--progress-file`, `protocol.configure`) quand le
> worker est élevé -- `WorkerRunner._dispatch` (`gui/worker_runner.py`) le
> relayait donc bien via `self.error.emit(...)`. Mais de nombreux chemins
> d'erreur de `__main__.py` (`GAMES_PARTITION_NOT_FOUND` entre autres)
> font seulement `emit_error(...); return 1`, sans jamais appeler
> `emit_done(False)` -- et `WorkerRunner._poll()` ne savait détecter la
> fin d'une opération en erreur qu'à `_done_emitted`, jamais à un `error`
> déjà reçu. Résultat : dès que le process élevé se terminait (`poll()`
> non `None`) sans `"done"`, `_poll()` retombait sur sa branche «
> élévation refusée/échouée » et écrasait le vrai code déjà délivré par un
> `ELEVATION_FAILED` générique -- et sur Windows en particulier,
> `ShellExecuteW` ne fournissant aucun tube stdout/stderr vers le
> processus élevé (contrairement à `osascript`/`pkexec`/`sudo`), rien
> d'autre ne permettait de distinguer un vrai refus d'élévation d'un
> worker qui avait échoué proprement pour une tout autre raison.
>
> **Corrigé** : `WorkerRunner` retient désormais si un vrai événement
> `"error"` a déjà été reçu (`_error_emitted`, mis à `True` dans
> `_dispatch`) -- la branche de fin de `_poll()` ne synthétise
> `ELEVATION_FAILED` (ou les cas macOS TCC détectés via le journal
> d'élévation) que si aucune erreur réelle n'était déjà connue ;
> `finished.emit(False)` reste émis dans tous les cas, une seule fois. Le
> contenu déjà présent dans le fichier de progression prime donc toujours
> sur une élévation supposée en échec, quel que soit l'OS -- pas seulement
> pour ce code précis.

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

> **Écran de bienvenue macOS, détection proactive de l'Accès complet au
> disque (phase 9).** Jusqu'ici, l'absence de cette autorisation n'était
> détectée qu'*après coup* : l'utilisateur devait lancer une opération,
> attendre l'échec (`MACOS_TCC_BLOCKED`), puis ouvrir l'Aide pour
> comprendre pourquoi. `gui/elevate.py::has_full_disk_access` détecte
> l'autorisation *avant* toute tentative d'écriture, sans élévation :
> `~/Library/Application Support/com.apple.TCC` est un dossier protégé
> par TCC dont la simple lecture (`os.listdir`) échoue avec
> `PermissionError` tant que ce processus n'a pas reçu l'Accès complet au
> disque — TCC s'applique à l'identité du processus, pas à ses privilèges
> Unix, donc cette sonde n'a besoin d'aucun mot de passe administrateur
> pour donner une réponse fiable. `True` par défaut hors macOS (ce
> blocage lui est spécifique) et en cas d'erreur autre que la lecture
> elle-même du dossier n'est jamais affirmé sans preuve positive.
>
> `gui/screens.py::FullDiskAccessScreen` (nouvel écran, ajouté à
> `_root_stack` aux côtés de `MainView`/`AssistedLandingScreen`) remplace
> l'accueil habituel — assisté ou expert, quel que soit `ui_mode` — tant
> que `has_full_disk_access()` renvoie `False` au démarrage, macOS
> uniquement. Explique la procédure (texte repris de `HelpDialog`, adapté
> au premier lancement) avec un bouton « Ouvrir les réglages » (même lien
> profond que `HelpDialog`, `_on_open_settings_requested` partagé) et un
> bouton « J'ai terminé » qui revérifie : détectée, `MainWindow.
> _show_startup_screen()` (factorisé depuis la logique de démarrage
> existante) affiche l'accueil habituel et cet écran ne réapparaît plus
> pour la session en cours ; toujours absente, un message dédié
> s'affiche plutôt qu'un clic silencieusement ignoré (§5). Construit
> inconditionnellement (même principe que `HelpDialog`, dont le bouton
> déclencheur n'apparaît lui aussi que sur macOS) mais n'est choisi comme
> écran de démarrage que sur macOS — un `has_full_disk_access` à `False`
> sur un autre OS (accident de mock, comportement futur imprévu) ne fait
> jamais apparaître cet écran ailleurs, testé explicitement.
>
> Tests (`tests/test_gui_elevate.py`, `tests/test_gui_screens.py`,
> `tests/test_gui_main_window.py`) : `has_full_disk_access` lisant un vrai
> dossier protégé par TCC, son résultat dépendrait sinon de l'autorisation
> réelle du terminal qui lance la suite sur une machine de dev macOS,
> rendant les tests non déterministes selon la machine. Une autofixture
> (`tests/conftest.py::_default_full_disk_access_granted`) la stub à
> `True` par défaut pour tous les tests (comportement historique, avant
> cet écran) ; les tests dédiés à `FullDiskAccessScreen` la repatchent
> explicitement, et les tests de `has_full_disk_access` elle-même se
> marquent `@pytest.mark.real_fda_probe` pour laisser passer leur propre
> implémentation — même principe que `real_subprocess` (§8).
>
> **`packaging/LISEZ-MOI.txt` et cible `dist` (§6, phase 9)** : la même
> procédure (clic droit → Ouvrir pour Gatekeeper, puis Accès complet au
> disque, à refaire après chaque mise à jour puisque la signature ad hoc
> change à chaque reconstruction — ci-dessus) doit aussi atteindre un
> utilisateur qui n'a pas encore ouvert l'app — l'écran de bienvenue
> ci-dessus ne peut rien expliquer avant ce premier lancement bloqué par
> Gatekeeper. `packaging/build_macos.sh dist` construit puis empaquette
> directement `dist/R36S-Studio-macos.zip` (app + `LISEZ-MOI.txt`, mise
> en scène dans un dossier temporaire puis `ditto`, jamais `zip -r` — même
> raison que l'empaquetage CI ci-dessous : seul `ditto` préserve la
> structure et les attributs étendus d'un vrai bundle `.app`) ; la CI
> (`.github/workflows/build.yml`, job `macos`) appelle cette même cible
> plutôt que de dupliquer la logique d'empaquetage — une seule source de
> vérité sur le contenu de l'archive distribuée, locale comme CI.

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

> ⚠️ **Confirmé sur du vrai matériel : `Get-Disk.IsRemovable` est absent
> (pas faux) pour un lecteur de carte SD intégré.** Premier test réel sur
> un ThinkPad avec lecteur SD Realtek intégré (`R36S_STUDIO`, aucune carte
> détectée alors qu'une carte 128 Go était bien montée) : `Get-Disk`
> renvoie `IsRemovable: $null` pour **tous** les disques de cette machine,
> carte SD comprise, et son `BusType` vaut `SCSI` (`FriendlyName: Realtek
> PCIE CardReader`) — jamais `USB`. Le filtre `safety` (§4.2 : « `removable`
> est faux **et** `bus` n'est pas USB ») rejetait donc la carte à tort :
> `is_removable = disk.get("IsRemovable")` retombait sur `is None` avant
> même le repli `bus == "USB"`, qui échoue lui aussi puisque le bus
> annoncé est SCSI. Ce n'est pas propre à cette machine : n'importe quel
> lecteur de carte SD interne (PCIe/SCSI plutôt qu'USB) est concerné.
>
> **Corrigé** en croisant `Get-Disk` avec `Win32_DiskDrive.MediaType`
> (`Get-CimInstance Win32_DiskDrive | Select-Object Index, MediaType`,
> une troisième requête PowerShell dans `devices/windows.py::list_devices`)
> par index de disque — `"Removable Media"` (carte SD, confirmé sur cette
> machine) contre `"Fixed hard disk media"` (NVMe système, confirmé aussi)
> — utilisé seulement quand `IsRemovable` est absent, jamais pour
> contredire une valeur explicite. Le repli `bus == "USB"` reste en tout
> dernier recours si `Win32_DiskDrive` ne répond rien d'exploitable non
> plus (requête échouée, disque absent de sa liste). Aucune autre règle du
> garde-fou §4.2 n'est affaiblie — seul le signal `removable` change de
> source.

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

> ⚠️ **Diagnostic partiel, PAS le correctif complet -- voir la note plus
> bas (« Investigation en cours, non résolue ») : cette hypothèse (BOOT
> resté monté) a corrigé un vrai bug de champ d'application, mais
> l'échec `[Errno 9] Bad file descriptor` persiste sur du vrai matériel
> même une fois BOOT verrouillé/démonté comme le reste.** Gardé tel quel
> ci-dessous (raisonnement toujours valide sur ce point précis, et
> nécessaire au correctif de la carte vierge qui suit), mais ne pas le
> lire comme la cause complète de `[Errno 9]` sur Windows.
>
> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : `[Errno 9] Bad file
> descriptor` une seconde après le début de l'écriture Windows.** Rapporté
> sur une carte cible portant un ArkOS complet (BOOT + root + EASYROMS,
> seule EASYROMS montée avec une lettre de lecteur), `ConfirmDialog`
> affichée correctement, l'échec survenait au tout début de l'écriture
> réelle. Cause : `write_target.prepared_write_target` (§4.3) verrouillait/
> démontait `device.mountpoints` (`devices/windows.py`) avant d'ouvrir
> `\\.\PhysicalDriveN` -- mais ce champ ne contient que les partitions
> *avec une lettre de lecteur*. BOOT (FAT, typiquement sans lettre sur une
> carte ArkOS, §4.4) restait donc monté pendant toute l'écriture brute du
> disque entier. Environ une seconde après le début de l'écriture --
> celle des tout premiers secteurs, qui appartiennent justement à BOOT --
> Windows détecte que le contenu d'un volume encore monté change sous lui
> et révoque le handle physique en cours d'écriture pour protéger ce
> volume plutôt que de le laisser continuer : `ERROR_INVALID_HANDLE` côté
> Win32, `[Errno 9] Bad file descriptor` côté Python. L'ordre des
> opérations lui-même était déjà correct (`\\.\PhysicalDriveN` n'est
> ouvert qu'*après* `lock_and_dismount_volumes`, jamais avant) -- ce n'est
> pas la séquence qui était en cause, mais son périmètre : verrouiller
> seulement les volumes lettrés en oublie silencieusement ceux qui n'en
> ont pas. Confirmé sans rapport avec `eject_media()`/`IOCTL_STORAGE_
> EJECT_MEDIA` (ajoutés dans le même module par un commit récent, §4.4
> « Éjection ») : ce code n'est appelé que par l'étape F (éjection),
> jamais pendant l'écriture -- vérifié par une recherche exhaustive des
> appelants (`eject_media`/`_windows_eject` : uniquement `partitions/
> eject.py`).
>
> **Corrigé** : `write_target._windows_all_volume_paths` (nouvelle
> fonction) interroge `Get-Partition -DiskNumber N` (même mécanisme
> `AccessPaths` que `partitions/locate.py::_list_windows`, requête
> PowerShell distincte pour ne pas coupler `imaging/` à `partitions/` pour
> un simple besoin d'énumération) et retourne le chemin GUID
> (`\\?\Volume{...}\`) de *toutes* les partitions du disque, lettrées ou
> non -- une partition dont Windows ne reconnaît pas le système de
> fichiers (ext4, la partition root) obtient tout de même un volume "RAW"
> avec son propre chemin GUID (§4.4, comportement déjà confirmé
> ailleurs) ; le verrouiller/démonter sans risque (`FSCTL_LOCK_VOLUME`
> réussit trivialement sur un volume RAW non monté). `prepared_write_
> target` verrouille désormais cette liste complète plutôt que `device.
> mountpoints`. `winlock._drive_letter_to_volume_path` accepte maintenant
> aussi bien une lettre (`"D:\\"`) qu'un chemin déjà dans l'espace de noms
> périphérique (le repasser tel quel, débarrassé seulement de son `\`
> final, plutôt que de le préfixer une seconde fois par `\\.\` -- ce qui
> aurait produit un chemin invalide).
>
> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : le correctif ci-dessus
> faisait planter la restauration sur une carte vierge.** Testé
> spécifiquement pour trancher entre les hypothèses en cours sur ce même
> code (voir plus bas) : carte de 32 Go effacée (`Clear-Disk`, zéro
> partition, aucun volume monté), la restauration échouait avec `Command
> [...] "Get-Partition -DiskNumber 1 | ..." returned non-zero exit status
> 1`. Cause : sur un disque sans aucune partition, `Get-Partition` ne
> renvoie pas une liste vide -- il lève `ObjectNotFound` et PowerShell sort
> en code 1 (vérifié à la main). `check=True` traitait ça comme un échec
> fatal, alors qu'« aucune partition à verrouiller » est un résultat
> parfaitement normal avant un premier flash sur une carte neuve -- même
> principe que `reunmount_before_verify` sur macOS, qui utilise déjà
> `check=False` pour cette raison exacte. **Corrigé** : `check=False`, un
> code de retour non nul retombe sur une liste vide plutôt que de lever --
> `lock_and_dismount_volumes([])` est déjà un no-op sûr.
>
> ⚠️ **Investigation en cours, non résolue : `[Errno 9] Bad file
> descriptor` persiste sur la carte ArkOS complète malgré le correctif
> ci-dessus (verrouillage de toutes les partitions, lettrées ou non).**
> Confirmé sur du vrai matériel en testant les deux cartes en séquence
> pour isoler la cause : la carte vierge produit l'échec `ObjectNotFound`
> ci-dessus (corrigé), mais la même séquence de code sur la carte ArkOS
> (BOOT + root + EASYROMS, EASYROMS lettrée) redonne `[Errno 9] Bad file
> descriptor` -- donc l'hypothèse initiale (BOOT resté monté parce
> qu'exclu de `device.mountpoints`) est réfutée par cette nouvelle
> donnée : BOOT est désormais verrouillé/démonté comme les autres, et
> l'échec persiste quand même. Le mécanisme réel reste à confirmer -- pas
> encore une explication établie, seulement des pistes :
> - Le démontage (`FSCTL_DISMOUNT_VOLUME`) lui-même pourrait déclencher,
>   sur un lecteur de carte SD amovible, un comportement du pilote de
>   stockage (reset/re-détection du périphérique USB) qui invalide toute
>   poignée ouverte sur le disque physique peu après -- y compris une
>   poignée ouverte *après* le démontage, ce qui expliquerait pourquoi
>   l'ordre actuel (ouvrir `\\.\PhysicalDriveN` seulement après
>   `lock_and_dismount_volumes`, jamais avant) ne suffit pas.
> - Le sous-processus PowerShell de `_windows_all_volume_paths`
>   (`Get-Partition`) pourrait laisser un état transitoire (WMI/CIM) qui
>   n'a pas fini de se libérer au moment où le verrouillage direct
>   (`ctypes`) commence.
>
> Aucune des deux n'est vérifiée -- correctif non tenté tant que la cause
> réelle n'est pas confirmée, pour ne pas répéter l'erreur du correctif
> précédent (une hypothèse plausible mais incomplète, présentée comme
> réglée avant d'être re-testée sur du vrai matériel). **Diagnostic ajouté
> en attendant** : `imaging/copy.py::copy_range` inclut désormais, dans le
> message de l'exception ré-levée en cas d'échec d'écriture, le nombre
> d'octets déjà écrits et le temps écoulé depuis le début de la copie --
> ce contexte atteint déjà le journal de bord via le chemin d'erreur
> existant (`IO_ERROR` -> `str(exc)`, §5 vocabulaire) sans nouveau
> mécanisme. Le prochain test sur la carte ArkOS dira si l'échec survient
> toujours au même octet/délai caractéristique (cohérent avec un
> mécanisme déterministe côté pilote) ou de façon variable.
>
> ⚠️ **Piste supplémentaire, non vérifiée mais à rapprocher de ce qui
> suit** : un bug distinct confirmé juste après (`FSCTL_LOCK_VOLUME`
> refusé par un autre processus, ci-dessous) établit qu'Explorateur/
> indexeur/antivirus interfèrent réellement avec ce même verrouillage sur
> du vrai matériel Windows. Rien ne prouve encore un lien avec le `[Errno
> 9]` ci-dessus, mais la même famille de cause (un processus tiers qui
> rouvre un descriptor sur le volume ou le disque physique juste après le
> démontage) reste plausible et n'a pas été exclue -- à garder en tête si
> une future session revient sur cette investigation.

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : `FSCTL_LOCK_VOLUME`
> refusé (`DeviceIoControl a échoué (code 0x90018, erreur 5)`,
> `ERROR_ACCESS_DENIED`) alors que le worker est bien élevé.** Le worker
> élevé ne manque donc jamais de privilèges pour ce refus précis -- une
> élévation refusée ou absente échouerait plus tôt, avant même d'atteindre
> ce point. Cause : un AUTRE processus (l'Explorateur qui prévisualise le
> volume, l'indexeur de recherche Windows, un antivirus) tient encore un
> descripteur ouvert sur ce volume au moment précis où le worker tente de
> le verrouiller -- un état transitoire qui se libère très souvent en une
> ou deux secondes. Le code refusait déjà correctement d'écrire sans ce
> verrouillage (§4.3 : sans lui, Windows refuse l'écriture ou corrompt la
> carte) -- le vrai défaut était le message affiché, `error_io_error`
> (« Vérifie que la carte est toujours branchée »), faux et inutile dans
> ce cas précis : la carte est bien branchée, le worker bien élevé, rien à
> vérifier de ce côté.
>
> **Corrigé en deux temps**, tous les deux dans `imaging/winlock.py` :
> 1. **Nouvelles tentatives avant d'abandonner.** `_lock_volume` (remplace
>    l'appel direct à `_device_io_control(handle, FSCTL_LOCK_VOLUME)` dans
>    `lock_and_dismount_volumes`) réessaie jusqu'à `LOCK_VOLUME_RETRY_
>    COUNT` fois (5), espacées de `LOCK_VOLUME_RETRY_DELAY_SECONDS` (0,5 s),
>    mais *seulement* quand l'échec est `ERROR_ACCESS_DENIED` -- toute
>    autre erreur (volume déjà absent, périphérique disparu...) est
>    propagée immédiatement, réessayer n'y changerait rien.
>    `_device_io_control` porte désormais le code Win32 réel sur
>    l'exception qu'elle lève (`DeviceIoControlError.win32_error`, nouvelle
>    classe -- sous-classe d'`OSError`, donc rien ne casse côté appelants
>    existants qui attrapent `OSError` génériquement) pour que `_lock_
>    volume` puisse distinguer les deux cas sans reparser le message.
> 2. **Message dédié si les tentatives s'épuisent.** `VolumeInUseError`
>    (nouvelle exception, `imaging/winlock.py`) -- `cmd_flash`
>    (`__main__.py`) l'intercepte *avant* le repli générique `except
>    (OSError, ...)` (dont elle hérite, mais l'ordre des `except` fait
>    gagner la branche spécifique) et émet un nouveau code dédié,
>    `VOLUME_IN_USE`, plutôt que `IO_ERROR`. Message convivial
>    (`gui/strings.py::error_volume_in_use`) : invite explicitement à
>    fermer les fenêtres de l'Explorateur qui affichent la carte, plutôt
>    que de suggérer (à tort) un débranchement.
>
> Portée volontairement limitée à `FSCTL_LOCK_VOLUME` (l'écriture, §4.3) --
> `eject_media`/`refresh_disk_properties` (`partitions/eject.py`, même
> module) ne bénéficient pas encore de ces nouvelles tentatives ; même
> mécanisme d'interférence plausible pour l'éjection, mais non rapporté et
> non traité ici, par cohérence avec le principe déjà appliqué ailleurs
> dans ce fichier (ne corriger que ce qui a été signalé, noter le reste
> comme piste future).

**Sauvegarde intelligente :** ne pas copier 128 Go quand la dernière partition s'arrête
à 8 Go. Lire la table de partitions (MBR ou GPT), calculer la fin du dernier secteur
utilisé, et ne sauvegarder que jusque-là. Proposer une compression `.img.gz` ou
`.img.xz` à la volée.

> **Sauvegarde système sans les jeux (phase 9), section « Par sécurité ».**
> La sauvegarde intelligente ci-dessus s'arrête déjà à la fin de la
> *dernière* partition utilisée — mais sur une carte R36S d'origine, cette
> dernière partition est justement EASYROMS (ou STORAGE sur EmuELEC), qui
> représente l'essentiel de l'espace (100 Go typiques contre 8-9 Go pour
> le système seul). `imaging/system_backup.py::backup_system_only`
> s'arrête plutôt à la fin de la *dernière partition système*, juste
> avant celle des jeux — identifiée via `partitions/locate.py::
> list_partitions` (étiquette EASYROMS/STORAGE, comme le reste du projet)
> plutôt qu'en lisant la table brute pour ça, une table MBR n'ayant aucun
> concept d'étiquette. La table brute (MBR ou GPT, schéma détecté
> automatiquement comme pour la sauvegarde intelligente) ne sert qu'à
> trouver l'octet exact où s'arrête la partition précédente, une fois
> l'index de la partition de jeux connu — même hypothèse de correspondance
> par position entre `list_partitions` et la table brute que celle déjà
> faite ailleurs dans ce projet (`BOOT_PARTITION_INDEX`/`EASYROMS_
> PARTITION_INDEX`). Lève `GamesPartitionNotFound` quand aucune partition
> de jeux n'est reconnaissable (carte ROCKNIX, où les jeux vivent dans la
> partition Linux plutôt qu'une partition séparée ; ou carte au système
> non reconnu) — pas de frontière évidente où s'arrêter dans ce cas.
>
> **Point critique, table GPT** (`imaging/gpt.py`) : contrairement à MBR
> (une table unique en tête de disque), GPT porte une table secondaire en
> toute fin de disque, et l'en-tête primaire y pointe (`AlternateLBA`).
> Une simple troncature laisserait cette table secondaire manquante et
> l'en-tête primaire pointant hors du fichier — un outil de flashage
> rejette alors l'image comme corrompue plutôt que de simplement accepter
> une partition en moins. `backup_system_only` reconstruit donc une table
> secondaire cohérente à la nouvelle fin de fichier (partition de jeux
> retirée des deux tableaux d'entrées, primaire et secondaire), et met à
> jour l'en-tête primaire en conséquence (`AlternateLBA`/`LastUsableLBA`,
> CRC32 des deux recalculés dans le bon ordre imposé par la spec UEFI :
> CRC32 du tableau d'entrées d'abord, puis CRC32 de l'en-tête lui-même
> avec son propre champ à zéro pendant le calcul). CRC32 : l'algorithme
> demandé par la spec UEFI (Annex D, ISO/IEC 13239:2002) est le CRC-32
> IEEE 802.3 standard, le même que `zlib.crc32`/PNG — aucune inversion de
> bits ni table personnalisée à gérer. Les GUID (type et identifiant de
> partition) sont traités comme des blobs opaques de 16 octets, jamais
> interprétés ni reconstruits, seulement recopiés tels quels. Vérifié par
> des tests qui reconstruisent l'image complète et la reparsent bout en
> bout (CRC32 des deux en-têtes et des deux tableaux d'entrées, contenu
> des partitions gardées).
>
> ✅ **Confirmé sur du vrai matériel, avec le détail exact de l'échec**
> (§5, ce qui a motivé la validation manuelle) : sans cette réparation,
> `gdisk` signale « Disk size is smaller than the main header indicates »
> et « Backup header: ERROR », Linux ne voit aucune partition, et la
> console ne démarre pas à partir de l'image — la simple troncature ne
> suffit pas, exactement le risque anticipé ci-dessus. Le correctif
> manuel effectué pour confirmer (supprimer l'entrée de la partition 3
> puis réécrire la table) est exactement ce qu'automatise `backup_
> system_only`.
>
> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : l'image produite
> restait inbootable même une fois l'en-tête GPT lui-même réparé --
> observé identiquement sur macOS et sur Windows, pas un défaut du chemin
> Windows.** Rapporté indépendamment de toute carte cible (l'image seule,
> testée avec `gdisk -l image.img`, sans jamais être flashée) : le symptôme
> exact déjà documenté ci-dessus (« Disk size is smaller than the main
> header indicates ») persistait. Vérification demandée en trois points --
> réponses trouvées en relisant le code :
> 1. **La réparation est-elle réellement exécutée ?** Oui --
>    `backup_system_only` appelle bien `_rewrite_gpt_tables_after_
>    truncation` juste après la copie tronquée, structurellement, à chaque
>    appel GPT ; `cmd_backup` (`__main__.py`) route bien `--system-only`
>    vers `backup_system_only`, jamais vers `backup_device`. Pas le
>    problème.
> 2. **Les tests portent-ils sur des tables factices plutôt que sur une
>    image réellement produite ?** Non pour le test de cohérence GPT
>    existant (`test_backup_system_only_gpt_output_has_a_consistent_
>    partition_table`) -- il appelle bien `backup_system_only` bout en
>    bout et reparse le fichier produit. Mais un vrai trou : ce test ne
>    vérifiait *jamais* le MBR protecteur (LBA0), seulement l'en-tête GPT
>    et ses tableaux d'entrées.
> 3. **Le cas d'une carte cible plus petite que la source est-il traité ?**
>    Question mal ciblée par la carte cible -- le symptôme est dans le
>    *fichier image* lui-même, avant toute restauration : `gdisk -l` sur
>    l'image seule échoue déjà, indépendamment d'où elle serait ensuite
>    flashée. (La vérification taille-cible-vs-image, § pré-vol n°2 du
>    parcours de clonage, est un problème séparé, déjà traité.)
>
> **Cause réelle, trouvée grâce au point 2** : `_rewrite_gpt_tables_after_
> truncation` corrige bien l'en-tête GPT (primaire et secondaire) et ses
> tableaux d'entrées, mais ne touche jamais LBA0 -- le MBR protecteur qui
> y vit continuait donc de décrire la taille du disque *d'origine* (ex.
> 128 Go pour une carte R36S typique) alors que le fichier produit n'en
> fait plus que 8-9 Go. `gdisk` (et tout outil qui valide la cohérence
> entre le MBR protecteur et la taille réelle du disque) signale cette
> incohérence -- exactement le symptôme rapporté, persistant même une fois
> l'en-tête GPT proprement réparé. Explique aussi pourquoi le symptôme est
> identique sur les deux OS : ce code est entièrement commun (`imaging/
> system_backup.py`), rien de spécifique à une plateforme.
>
> **Corrigé** : `_repair_protective_mbr_after_truncation` (nouvelle
> fonction, appelée juste après `_rewrite_gpt_tables_after_truncation`
> dans `backup_system_only`) recalcule le compte de secteurs du créneau
> MBR protecteur (type `0xEE`, retrouvé via `parse_mbr` plutôt que supposé
> au créneau 0) à partir de la taille réelle du fichier produit (fin de la
> copie tronquée + table secondaire, même formule qu'`estimate_system_
> backup_size`). Reconstruit LBA0 à partir de `source` (lisible) plutôt
> que `destination` (écriture seule), même principe que `_repair_mbr_
> table_after_truncation` pour le cas MBR pur. **Trou de test fermé** :
> `test_backup_system_only_gpt_updates_protective_mbr_sector_count`
> (`tests/test_imaging_system_backup.py`) vérifie ce champ précis sur la
> même image produite bout en bout -- confirmé qu'il échoue sans le
> correctif (533 secteurs, la taille du disque source factice, au lieu des
> 266 attendus) avant d'être vérifié à nouveau après.
>
> **Vérification supplémentaire, entièrement indépendante des fonctions
> testées** (le symptôme persistait, rapporté à nouveau après ce premier
> correctif -- « aucune image `--system-only` n'a jamais démarré une
> console », sur macOS comme sur Windows identiquement). Risque identifié
> dans les tests ci-dessus : `_build_fake_gpt_image` (la fixture qui
> construit le disque source factice) réutilise `build_gpt_header`/
> `build_gpt_entries` -- les mêmes fonctions que celles réparées et
> vérifiées ici. Un bug systématique dans ces fonctions de construction
> pourrait en principe se retrouver identique dans le disque source *et*
> dans la réparation, invisible à toute comparaison entre les deux.
> `test_backup_system_only_gpt_output_survives_fully_independent_
> structural_verification` (même fichier) reconstruit un disque source
> factice et revérifie la sortie entièrement à la main
> (`struct.pack`/`struct.unpack`, CRC32 recalculés directement) --
> aucun import de `imaging/gpt.py`/`imaging/mbr.py` des deux côtés. Résultat
> avec le code actuel (correctif protective-MBR inclus) : MBR protecteur
> cohérent avec la taille réelle du fichier, CRC32 des deux en-têtes
> valides, `AlternateLBA` des deux côtés se référençant correctement l'un
> l'autre, tableau d'entrées primaire ne contenant jamais la partition de
> jeux, aucune entrée gardée ne débordant du fichier -- confirmé en échec
> sans le correctif protective-MBR (comme le test précédent), en succès
> avec. **Non confirmé pour autant sur du vrai matériel** : aucune image
> réelle de 128 Go → 8-9 Go ni `gdisk` n'était disponible pour cette
> vérification (recherchée sur cette machine, absente) -- cette
> vérification structurelle établit que le fichier produit est
> internement cohérent (ce qu'un outil comme `gdisk` validerait), pas
> qu'il démarre réellement une console : une cause distincte, propre au
> matériel RK3326 réel (ex. un composant de démarrage écrit à un offset
> fixe hors du schéma de partitions déclaré) resterait possible et non
> exclue par ce test.
>
> **Schéma MBR pur, vérifié distinctement (« la logique diffère
> complètement » entre les deux schémas, confirmé en relisant le code)** :
> contrairement à GPT, une table MBR pure n'a nulle part de champ séparé
> déclarant la taille totale du disque -- chaque partition ne décrit que
> sa propre étendue (`start_lba`/`sector_count`), déjà correcte et
> inchangée pour les partitions gardées. Aucun équivalent du bug
> protective-MBR n'est donc possible côté MBR pur, structurellement. Déjà
> couvert bout en bout (pas seulement en isolation) par `test_backup_
> system_only_mbr_output_table_is_consistent_with_real_file_size`, qui
> vérifie qu'aucune partition gardée ne déborde du fichier produit.
>
> **Identification de la partition de jeux, repli sans étiquette
> reconnue** (`_fallback_games_partition_index`) : une carte qui ne nomme
> ni EASYROMS ni STORAGE reste couverte — dernière partition du disque,
> système de fichiers FAT ou NTFS, et taille au-dessus de `_LARGE_
> PARTITION_THRESHOLD_BYTES` (1 Go, un seuil qui évite de prendre une
> petite partition système FAT — BOOT, par exemple — pour la partition de
> jeux). La taille vient de la table brute (MBR/GPT), `list_partitions`
> n'exposant aucune taille ; le système de fichiers et la position («
> dernière partition ») viennent de `list_partitions`, comme pour
> l'identification par étiquette.
>
> **Réparation de la table MBR aussi, pas seulement GPT.** Moins visible
> que le cas GPT ci-dessus (pas de table secondaire à reconstruire), mais
> tout aussi nécessaire : une simple troncature laisserait, dans l'image
> MBR produite, l'entrée de la partition de jeux décrivant un espace qui
> s'étend bien au-delà de la fin réelle du fichier. `backup_system_only`
> met donc à zéro, dans le premier secteur de l'image produite, le
> créneau de cette entrée (et de toute entrée après elle) — une simple
> reconstruction en mémoire à partir du premier secteur déjà lu côté
> source (`destination` étant ouvert en écriture seule, jamais relu),
> MBR n'ayant ni CRC ni table secondaire à recalculer contrairement à GPT.
>
> **Estimation avant de lancer, et confirmation explicite** (§5) :
> `gui/partition_runner.py::SystemBackupEstimateRunner`, un thread séparé
> comme les autres runners de ce module (lire la table de partitions est
> rapide, mais le montage du BOOT pour l'identification du modèle peut
> bloquer jusqu'à `MOUNT_WAIT_SECONDS`, §4.4) — calcule la taille estimée
> (`imaging/system_backup.py::estimate_system_backup_size`, journalisée
> avant l'ouverture de la fenêtre Choix du fichier) et tente, en
> best-effort, d'identifier la console (même mécanisme que l'étape 2 du
> mode assisté, `identify_from_boot_directory` sur le BOOT monté) pour
> suggérer un nom de fichier qui inclut le modèle *quand il est connu* —
> un échec d'identification n'empêche jamais l'estimation d'aboutir, cette
> partie est purement décorative. Nom suggéré : `systeme_{modèle}_
> {AAAA-MM-JJ}_{HH-MM}.img` dans `~/Documents/R36S Studio/` (même
> convention que `partitions/archives.py`, jamais `~/.config`, §6) —
> `{modèle}` est l'identifiant brut du `.dtb` (ex. `rk3326-r35s`, ou
> `G80CA-MB-V1.2` avec un point, préservé par la mise en sécurité du nom
> de fichier plutôt que défiguré), pas un nom convivial (rien de tel
> n'existe ailleurs dans ce projet). Comme pour toute proposition de ce
> genre dans l'appli, toujours remplaçable en entier via Parcourir,
> jamais imposé.
>
> La taille estimée est affichée deux fois : dans le journal de bord, et
> directement sur la fenêtre Choix du fichier (`FileDialog.
> set_estimated_size`, sauvegarde système uniquement) — un débutant
> pourrait ne pas remarquer une ligne de journal qui défile. Cliquer
> Suivant sur cette fenêtre (taille visible, fichier choisi) sert de
> confirmation explicite avant de lancer la copie ; contrairement au
> flash, rien n'est effacé ici (lecture seule du périphérique, écriture
> seulement dans un fichier), donc pas de fenêtre rouge de type
> `ConfirmDialog` — celle-ci reste réservée aux opérations destructrices
> (§2 règle 6).
>
> Passe par le worker élevé comme la sauvegarde complète (`backup
> --system-only`, `__main__.py::cmd_backup`) — c'est une lecture brute du
> périphérique, §3.
>
> **Proposée aussi comme option du mode assisté**, pas seulement depuis
> l'écran expert (`gui/screens.py::AssistedLandingScreen`, bouton discret
> sous le bouton principal) : `MainWindow._start_backup_system_from_
> assisted_landing` réutilise `MainView`/`_log_panel` le temps de
> l'opération, pour bénéficier du journal de bord et des états occupé
> déjà en place, sans en faire un vrai changement de mode — contrairement
> au bouton « Mode expert », `ui_mode` n'est ni modifié ni persisté ici.
>
> ⚠️ **Défaut de parcours rapporté en usage réel, corrigé** : la première
> version montrait l'écran expert (`HomeScreen`, les six étapes) pendant
> toute l'opération — un changement de mode visuel non demandé, contraire
> au principe « jamais un aller simple vers le mode expert » déjà énoncé
> ailleurs (§4.5, ROCKNIX/système non reconnu) — et n'offrait ensuite
> *aucune* suite : une fois la sauvegarde terminée, l'utilisateur restait
> sur cet écran expert sans le moindre bouton pertinent. **Corrigé** :
> `_start_backup_system_from_assisted_landing` affiche désormais
> `WizardStepPanel` (déjà utilisé pour le parcours guidé lui-même) plutôt
> que `HomeScreen` — l'infrastructure du journal de bord (`_log_panel`,
> `_start_worker`) reste réutilisée en interne, mais rien d'expert n'est
> jamais rendu visible. À la fin de l'opération (`_on_assisted_ad_hoc_
> worker_finished`, point d'arrivée dédié dans `_on_worker_finished`, au
> même niveau que le `if self._wizard_active:` du vrai parcours guidé),
> le chemin du fichier créé apparaît dans le journal (déjà inclus dans
> `_success_message()`) et `WizardStepPanel.show_next_step_choice` propose
> explicitement la suite : « Préparer une carte avec cette sauvegarde »
> (réussite uniquement — `show_prepare_card=ok`) ou « Revenir à
> l'accueil » (toujours) — jamais un écran sans issue.
>
> Deux nouveaux signaux dédiés sur `WizardStepPanel`
> (`prepare_card_requested`/`return_to_home_requested`), jamais les
> `continue_requested`/`cancel_requested` déjà câblés au vrai parcours
> guidé (`_on_wizard_continue`/`_cancel_wizard`, qui opèrent sur
> `self._wizard_flow` sans jamais vérifier `self._wizard_active` en
> premier lieu) — les réutiliser pour cette opération ponctuelle aurait
> avancé/corrompu l'état interne du parcours guidé pour de vrai. Un
> nouveau drapeau d'instance, `_assisted_ad_hoc_active` (distinct de
> `_wizard_active`), signale ce contexte à `_on_worker_finished`.
>
> « Préparer une carte avec cette sauvegarde »
> (`_on_prepare_card_requested`) réutilise le fichier fraîchement créé
> comme source du flash — la fenêtre Choix du fichier est inutile
> puisqu'il est déjà connu (`_skip_file_dialog_for_flash`, consommé par
> `_on_device_chosen` avant son embranchement habituel) — mais la fenêtre
> Confirmation reste obligatoire avant d'écrire pour de vrai (§2 règle 6,
> jamais sautée) ; `_proceed_to_flash_confirmation` factorise cette
> validation+confirmation, partagée avec le choix de fichier normal
> (`_on_file_chosen`). Reste tout du long dans l'habillage assisté — même
> le bouton Annuler de `WizardStepPanel`, déjà câblé à `_cancel_wizard`,
> fonctionne correctement ici sans changement (annule `self._runner` s'il
> y en a un, revient à l'accueil assisté), aucun gestionnaire dédié
> nécessaire pour ce cas. Vérifié plus largement (`grep show_home()`) :
> c'était la seule bascule non sollicitée vers l'écran expert dans tout
> le mode assisté — les autres opérations (téléchargement ROCKNIX, chaque
> étape du parcours guidé) restent déjà correctement dans `MainView`/
> `WizardStepPanel` ou `AssistedLandingScreen`.
>
> ⚠️ **Blocage constaté en conditions réelles, corrigé** : l'écran
> « Choisis la carte à préparer » (`_on_prepare_card_requested`, ci-dessus)
> s'affichait bien, mais son bouton Continuer ne déclenchait rien — la
> première version ouvrait directement la fenêtre modale Choix de la
> carte (`_device_dialog.open()`, comme n'importe quelle tuile du mode
> expert) sans jamais démarrer le moindre sondage automatique : aucun
> bandeau de détection contrairement aux étapes 1/4 du vrai parcours
> guidé, et le bouton Continuer, affiché mais jamais câblé à une action
> pour cet écran précis, restait désactivé pour toujours (`can_continue=
> False`, jamais réactivé). Confirmé qu'aucun filtre `safety` n'est en
> cause (§4.2 : système, dossier de l'app, amovible/USB, taille —
> jamais le contenu déjà présent sur la carte).
>
> **Corrigé** en répliquant le même mécanisme que les étapes 1/4 :
> `_prepare_card_poll_timer` (nouveau, distinct de `_wizard_poll_timer` --
> ce parcours ponctuel n'est jamais un vrai `WizardJob`, y faire toucher
> `_on_wizard_poll`/`self._wizard_flow` corromprait le vrai parcours
> guidé) et `_on_prepare_card_poll` : une carte unique détectée active
> Continuer avec le nom de la carte affiché en bandeau
> (`wizard_status_device_found`, chaîne déjà utilisée par les étapes
> 1/4) ; zéro carte laisse Continuer désactivé (`wizard_status_waiting`) ;
> plusieurs cartes retombent sur le même repli `_device_dialog` qu'avant
> (`_skip_file_dialog_for_flash` n'est donc plus consommé que par ce cas
> précis). `_prepare_card_candidate` (nouveau, `None` sauf carte unique
> trouvée) fait le lien avec le bouton Continuer : `_on_wizard_continue`
> le vérifie en tout premier, avant même `self._wizard_flow` -- jamais de
> confusion possible entre les deux parcours, l'un exclut l'autre par
> construction (`_wizard_active`/`_assisted_ad_hoc_active`). Bouton
> Actualiser affiché (`show_refresh=True`, comme les étapes 1/4) pour
> resonder manuellement sans attendre le prochain tick, ou après avoir
> fermé le repli multi-cartes sans choisir -- `_on_wizard_refresh_
> requested` route désormais vers le bon sondage selon
> `self._assisted_ad_hoc_active`, jamais `_on_wizard_poll` pour ce cas.
> `_cancel_wizard`/`_on_assisted_ad_hoc_return_home` arrêtent aussi ce
> nouveau minuteur, défensivement.

> ⚠️ **Deux défauts rapportés en usage réel, corrigés.**
>
> **Erreur muette.** Un échec pendant l'estimation (ex. carte débranchée
> entre-temps) n'affichait que « Une erreur est survenue », sans aucune
> cause exploitable — contrairement à toute autre opération de l'appli
> (§5 vocabulaire : le message brut du backend suit toujours le message
> principal comme ligne supplémentaire du journal). Cause : `SystemBackup
> Estimate` (`gui/partition_runner.py`) ne portait qu'un code d'erreur
> (`error`), jamais le message de l'exception d'origine — contrairement
> au couple `code`/`msg` que `WorkerRunner.error` fournit déjà pour
> `backup`/`flash`. Corrigé par un nouveau champ `detail` (`str(exc)`,
> capturé aux deux points où `SystemBackupEstimateRunner` attrapait déjà
> l'exception sans la garder) ; `MainWindow._on_system_backup_estimate_
> ready` journalise ce détail à la suite du message convivial, comme
> `LogPanel.finish_error` le fait déjà pour le reste de l'appli.
>
> **Lançable sans carte.** Déclenchée alors que la carte venait d'être
> éjectée et que le bandeau affichait « Aucune carte détectée ». Les six
> étapes lettrées restent volontairement toujours cliquables, quelle que
> soit la carte branchée (§4.5) — mais « Par sécurité » n'a, elle, jamais
> de sens sans carte du tout (pas de notion de pertinence par carte comme
> les six étapes, juste une carte présente ou non). `HomeScreen.set_
> status` accepte désormais un paramètre `has_device` distinct de
> `device` (`device` vaut déjà `None` aussi bien pour *aucune* carte que
> pour *plusieurs* candidates ambiguës, §4.5 — insuffisant à lui seul
> pour cette distinction ; `has_device` est `True` dès qu'au moins une
> carte est branchée, y compris plusieurs candidates, choisir laquelle
> restant possible). `_update_backup_rows_enabled` combine `has_device`
> avec l'état occupé existant (`_busy`), ce dernier restant prioritaire
> si une carte réapparaît pendant qu'une opération tourne déjà — le
> bouton Rafraîchir n'étant pas désactivé par `set_busy` (§5), un
> `set_status` peut survenir en plein milieu d'une opération.
>
> Cause probable du scénario observé (les deux défauts combinés) :
> l'estimation (`SystemBackupEstimateRunner`) ne marquait pas l'écran
> occupé pendant son calcul en arrière-plan — le bouton Éjecter (ou toute
> autre ligne) restait donc cliquable pendant cette fenêtre, permettant
> d'éjecter la carte en cours d'estimation. Corrigé au passage :
> `_start_system_backup_estimate`/`_on_system_backup_estimate_ready`
> encadrent maintenant le calcul d'un `set_busy(True)`/`set_busy(False)`
> sur `HomeScreen` et `AssistedLandingScreen`, comme `_start_worker`/
> `_on_worker_finished` le font déjà pour les opérations passant par le
> worker élevé.

> ⚠️ **Bug corrigé, signalé par un utilisateur : l'estimation échouait
> avec `[Errno 13] Permission denied: '/dev/disk2'`.** Cause :
> `SystemBackupEstimateRunner` tournait sur un `QThread` ordinaire, sans
> élévation (§3 — seul le worker l'a), et appelait `compute_system_
> boundary`, qui ouvre le périphérique brut (`open(device_path, "rb")`)
> pour lire la table de partitions exacte — nécessaire à la copie réelle,
> mais pas à une simple estimation.
>
> **Corrigé en deux temps, dans cet ordre de préférence (une estimation
> ne devrait pas demander de mot de passe) :**
> 1. **Estimation sans accès brut.** `partitions/locate.py::PartitionInfo`
>    porte désormais un champ `size_bytes`, renseigné sans élévation par
>    les outils déjà utilisés pour lister les partitions : `diskutil info
>    -plist` (`Size`) sur macOS, `lsblk -o ...,SIZE` sous Linux,
>    PowerShell `Get-Volume` (`Size`) sous Windows. `imaging/system_
>    backup.py::estimate_system_backup_size_unprivileged` additionne les
>    tailles des partitions gardées (même logique d'identification de la
>    partition de jeux que `backup_system_only` — étiquette EASYROMS/
>    STORAGE puis repli par position/système de fichiers/taille) ;
>    approximatif (arrondi à la taille de partition déclarée par l'OS,
>    pas l'octet exact de fin d'usage comme la copie réelle), mais
>    suffisant pour une estimation affichée avant de lancer l'opération.
> 2. **Repli élevé, seulement si une taille manque.** Si l'OS n'expose
>    pas la taille d'une des partitions gardées (`size_bytes` absent),
>    `estimate_system_backup_size_unprivileged` renvoie `None` plutôt que
>    d'inventer une valeur ; `SystemBackupEstimateRunner` relance alors
>    l'estimation via le worker élevé — un nouveau mode `backup --system-
>    only --estimate-only` (`__main__.py::cmd_backup`, `--output` devient
>    optionnel dans ce mode) qui calcule la taille exacte
>    (`compute_system_boundary`, accès brut) sans rien écrire, et
>    l'émet via un nouvel événement `estimate` du protocole JSON Lines
>    (`protocol.py::emit_estimate`, `{"type": "estimate", "size_bytes":
>    ...}`). Passe par la même `MacosAuthorizationSession` partagée que
>    toute autre opération élevée (`MainWindow._get_or_create_macos_auth_
>    session()`, §3) — jamais une invite mot de passe séparée pour ce
>    repli. `WorkerRunner` gagne un signal `estimate = Signal("qint64")`
>    (même raison `qint64` que `progress`, §3 — une taille peut dépasser
>    2 Go) pour le relayer à la GUI.
>
> La sauvegarde réelle (`backup_system_only`/`compute_system_boundary`,
> lancée une fois le fichier choisi) n'a pas changé : elle passait déjà
> par le worker élevé comme toute écriture/lecture brute (§3), et continue
> de partager la même session — vérifié par un test dédié qui enchaîne une
> sauvegarde système puis un flash et contrôle qu'une seule
> `AuthorizationRef` est créée pour les deux.

> ⚠️ **Bug corrigé, cause trouvée sur du vrai matériel : une sauvegarde
> « système sans les jeux » restaurée sur une carte neuve démarre bien
> (confirmé sur une console EmuELEC), mais n'a ensuite que ses partitions
> système.** `backup_system_only` retire délibérément la partition de jeux
> de la table (§ ci-dessus) -- correct pour la sauvegarde elle-même. Mais
> côté restauration (`flash.py::flash_device`), rien ne recréait cette
> partition : sur une carte de 32 Go restaurée depuis une image de 11,5 Go,
> une vingtaine de Go restaient non partitionnés, rendant `copy_games`
> (étape E) impossible -- la partition n'existe simplement pas.
> L'hypothèse initiale (« la console recrée la partition de jeux au
> premier démarrage ») est infirmée par ce test réel : pas fiable selon
> les firmwares.
>
> **Corrigé** : `imaging/games_partition.py` (nouveau module) ajoute une
> partition occupant tout l'espace libre restant après un flash réussi, et
> la formate -- exFAT par défaut (système de fichiers relevé sur l'EASYROMS
> de la carte source, §4.4), symétrique de la réparation de table après
> troncature mais dans l'autre sens (GPT : la table secondaire est
> déplacée vers la fin réelle du périphérique de destination -- plus grand
> que l'image restaurée -- et le MBR protecteur corrigé en conséquence,
> même raison que `_repair_protective_mbr_after_truncation` ; MBR : une
> entrée est ajoutée dans le premier créneau libre). `__main__.py::
> cmd_flash` gagne `--create-games-partition`, appelé après l'écriture et
> la vérification SHA-256. Nouveaux codes `GAMES_PARTITION_CREATE_FAILED`
> (pas assez de place libre) et `GAMES_PARTITION_FORMAT_FAILED` (le
> formatage natif a échoué).
>
> ✅ **`--create-games-partition` validé sur du vrai matériel, via le
> CLI directement** : partition de 20 406 861 824 octets créée après une
> restauration système seule, reconnue *immédiatement* par Windows avec
> une lettre de lecteur — sans retrait/réinsertion de la carte (l'incertitude
> qui justifiait de séparer `create_games_partition`/`format_games_
> partition`, ci-dessous, ne s'est pas matérialisée sur ce test).
> `Get-Partition` confirme trois partitions, la nouvelle en position 3,
> type IFS, 19,01 Go. Le calcul/la réécriture de table (déjà testés bout
> en bout en isolation) et le formatage natif (`Format-Volume`) sont donc
> tous les deux confirmés fonctionnels sur Windows ; macOS/Linux restent
> non testés (aucun matériel disponible pour ces deux OS).
>
> ⚠️ **Bug corrigé, trouvé en testant le câblage GUI après cette
> validation CLI : le drapeau n'était en fait jamais passé, ni en mode
> expert ni en mode assisté.** La première implémentation ne le déclenchait
> que via `self._wizard_active and self._wizard_backup_kind == "system"`
> -- couvrant uniquement le vrai parcours guidé à 5 étapes (§5). Deux
> autres chemins mènent pourtant tout autant à restaurer une sauvegarde
> système sans les jeux, et aucun des deux ne passait par ce drapeau :
> l'ad-hoc « Préparer une carte avec cette sauvegarde » de l'accueil
> assisté (`_assisted_ad_hoc_active`, jamais `_wizard_active`), et le
> simple enchaînement manuel en mode expert (ligne « Par sécurité » du
> mode expert -- `HomeScreen.backup_system_selected` -- puis étape « C.
> Flasher » avec le fichier ainsi produit), qui n'a même pas de notion de
> parcours pour porter un tel drapeau.
>
> **Corrigé** en abandonnant le drapeau spécifique au parcours guidé au
> profit d'un état central, `MainWindow._last_system_backup_output_path`
> -- le chemin de sortie de la dernière sauvegarde système réussie de la
> session, rempli une seule fois dans `_on_worker_finished` (« seul point
> d'arrivée de tout runner », déjà établi ailleurs dans ce fichier) dès que
> `self._mode == "backup_system"` et `ok`, peu importe lequel des trois
> chemins y a mené. Au moment de construire les arguments d'un flash,
> `--create-games-partition` est ajouté si et seulement si `self._file_
> path == self._last_system_backup_output_path` -- une comparaison de
> chemin exacte (on sait que ce fichier précis a été produit par
> `backup_system_only` cette session, jamais une supposition sur le
> contenu d'un fichier choisi par ailleurs) plutôt qu'une inspection du
> fichier ou une détection par nom. Couvre les trois chemins uniformément,
> y compris le mode expert : reprendre le même fichier pour l'étape
> « Flasher » suffit désormais à déclencher le drapeau, sans action
> supplémentaire de l'utilisateur ni notion de parcours à faire porter ce
> signal côté mode expert.
>
> **Piste distincte, à ne pas mélanger avec ce qui précède** : l'image
> système seule démarre sur une console EmuELEC mais pas sur la console
> d'origine testée. Peut être la partition de jeux manquante (corrigé
> ci-dessus, confirmé recréée), peut être un écran/DTB différent entre les
> deux consoles (§4.6, `identify/dtb.py`) -- non élucidé, à retester
> maintenant que la partition se recrée correctement.

> ⚠️ **Signalé de nouveau sur du vrai matériel : `--create-games-partition`
> n'atteignait jamais la ligne de commande, dans aucun mode -- pas même le
> vrai parcours guidé, malgré le correctif précédent.** Vérifié dans les
> traces d'élévation : aucune commande `flash` lancée depuis l'app ne
> portait ce drapeau. Cause réelle, trouvée en lisant `FileDialog._browse`
> (`gui/screens.py`) : `QFileDialog.getSaveFileName`/`getOpenFileName`
> renvoient des chemins à séparateurs `/` (convention Qt, y compris sous
> Windows), alors que le chemin par défaut proposé pour une sauvegarde
> système (`_suggested_system_backup_path`, via `pathlib.Path`) utilise le
> séparateur natif de l'OS (`\` sous Windows) -- la comparaison de chaîne
> stricte alors utilisée pour reconnaître « ce fichier vient bien d'une
> sauvegarde système de cette session » échouait dès que l'utilisateur
> cliquait Parcourir, y compris pour re-sélectionner exactement le même
> fichier déjà proposé par défaut. Expliquait aussi pourquoi le mode
> expert était touché **plus durement** (le drapeau n'était proposé
> *jamais*, pas seulement parfois) : son flash n'a **aucun** chemin par
> défaut (`getOpenFileName(..., "", ...)`, toujours vide) -- Parcourir y
> est donc obligatoire, jamais optionnel comme pour la sauvegarde, donc le
> mésappariement de séparateur s'y produisait systématiquement.
>
> **Un premier correctif (comparaison de chemin normalisée, puis une case
> à cocher optionnelle proposée en mode expert pour les cas que la
> comparaison ne pouvait pas reconnaître) a été implémenté, testé, puis
> entièrement retiré sur retour d'usage réel.** La case demandait à
> l'utilisateur de savoir si l'image qu'il restaure laissera de l'espace
> libre -- une information qu'il n'a structurellement pas, surtout avec un
> firmware qu'il découvre (§1 : « le chemin par défaut doit fonctionner
> sans que l'utilisateur ait à comprendre ce qu'il fait »). Signalé
> explicitement : même l'auteur du logiciel hésitait devant cette case --
> un signal fort qu'elle n'avait pas sa place dans une interface pensée
> pour un néophyte total.
>
> **Corrigé pour de bon : décision entièrement automatique, prise par le
> worker élevé lui-même après l'écriture, jamais par la GUI.** L'app
> dispose déjà de toute l'information nécessaire pour décider seule --
> la taille de l'image qu'elle vient d'écrire, la taille réelle de la
> carte -- sans jamais demander à l'utilisateur de la deviner :
> - `imaging/games_partition.py::create_and_format_games_partition_if_
>   worthwhile` (nouveau point d'entrée, remplace l'ancien `--create-
>   games-partition` conditionnel) : calcule d'abord, en lecture seule
>   (`_peek_free_games_partition_bytes`, sans `prepared_write_target` --
>   lire quelques secteurs d'un périphérique déjà monté fonctionne
>   nativement sur les trois OS, contrairement à l'écriture, §4.3),
>   l'espace qui serait disponible ; ne tente la création réelle
>   (verrouillage + écriture, `create_and_format_games_partition`) que si
>   cet espace atteint `GAMES_PARTITION_WORTHWHILE_BYTES` (1 Go, seuil
>   demandé explicitement -- un seuil *métier*, distinct du minimum
>   *technique* `MIN_GAMES_PARTITION_BYTES` de 64 Mo en dessous duquel une
>   partition ne serait de toute façon pas assez grande pour un seul jeu).
>   En dessous du seuil, ou si `NoFreeSpaceForGamesPartition`/
>   `NoFreeMbrSlot` sont quand même levées lors de la tentative réelle
>   (rare : l'espace a pu changer entre l'estimation et l'écriture) --
>   retourne `None` sans jamais lever, « sinon ne rien faire » plutôt
>   qu'un échec.
> - `__main__.py::cmd_flash` : plus de drapeau `--create-games-partition`
>   à passer (retiré de l'argument parser) -- tentée pour **tout** flash
>   réussi et vérifié, sur toute plateforme, sans condition sur le
>   firmware ni sur la provenance du fichier. Journalise systématiquement
>   la décision et son résultat (§4.4 : jamais silencieusement) -- « pas
>   assez d'espace libre », ou la taille effectivement créée. Une
>   véritable erreur d'écriture/formatage (`OSError`,
>   `subprocess.CalledProcessError`, `ValueError`) est journalisée en
>   avertissement (`emit_log(..., level="warning")`) mais **ne fait
>   jamais échouer le flash déjà réussi** -- même principe déjà établi
>   pour `--eject-after` (§4.6) : un bonus qui échoue après coup ne doit
>   pas renverser un résultat par ailleurs correct et déjà vérifié par
>   SHA-256. Les anciens codes `GAMES_PARTITION_CREATE_FAILED`/
>   `GAMES_PARTITION_FORMAT_FAILED` (qui faisaient échouer tout le flash)
>   ont été retirés en conséquence, `gui/strings.py` compris.
> - Côté GUI (`gui/main_window.py`) : plus rien à faire. `_same_output_
>   path`, `_last_system_backup_output_path`, la journalisation de
>   diagnostic associée, et la case `ConfirmDialog._games_partition_
>   checkbox` (`gui/screens.py`) ont tous été retirés -- `_start_worker`
>   ne construit plus jamais ce drapeau, quel que soit le mode.
>
> **Non confirmé sur du vrai matériel au moment d'écrire cette note** :
> couvert par des tests qui isolent le calcul (lecture directe d'un
> fichier factice servant de périphérique, sans verrouillage) et la
> décision (mocks), plus les tests CLI existants -- pas par une vraie
> restauration Windows. À vérifier au prochain flash réel d'une image plus
> petite que la carte : la ligne « Espace de jeux recréé sur l'espace
> libre restant (… octets) » doit apparaître dans le journal, sans aucune
> action de l'utilisateur.

> **Ligne de commande complète journalisée au lancement de tout worker
> élevé (§4.4), pour vérifier ce genre de chose sans avoir à instrumenter
> le worker à chaque doute.** Redemandé après le correctif ci-dessus :
> vérifier depuis les traces d'élévation elles-mêmes qu'un drapeau donné
> est bien transmis (`--create-games-partition`, entre autres, avant
> d'être retiré) n'était possible qu'en lisant le code, jamais en
> observant ce que l'app avait réellement lancé. `gui/main_window.py::
> _start_worker`/`_start_eject` journalisent désormais, juste avant de
> construire le `WorkerRunner`, une ligne `[diagnostic] worker : …` avec
> l'argv complet joint par des espaces (se lit comme la ligne qu'un
> utilisateur pourrait retaper lui-même) -- pour *tout* lancement
> (backup/flash/éjection), pas seulement celui suspecté à l'origine de la
> demande. Généralisé volontairement plutôt que limité au seul cas du
> moment : la même question (« qu'est-ce qui a été lancé, exactement ? »)
> se reposera pour d'autres drapeaux à l'avenir.

> ⚠️ **Audit multi-plateforme (demandé explicitement) : `create_and_
> format_games_partition_if_worthwhile` n'a jamais été validée sur du vrai
> matériel, sur aucun OS -- et sa partie interne réellement confirmée un
> jour (Windows, avant l'ajout du seuil automatique) ne représente qu'une
> moitié du chemin.**
>
> **Code commun aux trois OS, testé (reparsing indépendant, pas seulement
> "ne lève pas"), jamais sur du vrai matériel** : `_peek_free_games_
> partition_bytes` (lecture seule des premiers secteurs) et `create_games_
> partition` (calcul de plan + réécriture MBR/GPT) ne font que de la
> manipulation d'octets sur un chemin de fichier ouvert en binaire --
> aucune branche par OS, un bug ici toucherait les trois de façon
> identique. C'est la partie qui a le plus de tests (`tests/test_imaging_
> games_partition.py`, reparsing indépendant comme `test_imaging_system_
> backup.py`), mais jamais exécutée contre un vrai périphérique bloc, sur
> aucun OS -- seulement contre des fichiers factices.
>
> **Ce qui diverge ensuite, par OS, dans `format_games_partition`** :
> - **Windows** (`_format_windows`, `Get-Partition | Get-Volume | Format-
>   Volume` en PowerShell) : **seule branche jamais confirmée sur du vrai
>   matériel** -- mais cette validation (§4.3 ci-dessus, « partition de
>   20 406 861 824 octets créée, exFAT, étiquetée EASYROMS ») a eu lieu
>   *avant* l'ajout du seuil automatique de 1 Go et de `_peek_free_games_
>   partition_bytes` -- elle a validé `create_games_partition` +
>   `_format_windows` ensemble via l'ancien drapeau `--create-games-
>   partition`, jamais le nouveau chemin `if_worthwhile` (calcul préalable
>   en lecture seule, puis décision, puis appel) dans son intégralité.
> - **macOS** (`_format_macos`, `diskutil eraseVolume ExFAT|MS-DOS\ FAT32
>   <label> <partition>`) -- **jamais exécutée sur du vrai matériel**,
>   dans ce projet, à aucun moment.
> - **Linux** (`_format_linux`, `mkfs.exfat`/`mkfs.vfat -F 32`) --
>   **jamais exécutée sur du vrai matériel** non plus. ⚠️ Écart documentation/
>   code corrigé au passage (`imaging/games_partition.py::format_games_
>   partition`, docstring) : une version antérieure affirmait un repli
>   automatique vers `"fat32"` quand les outils exFAT sont absents --
>   **ce repli n'existe pas dans le code**, `_format_linux` choisit
>   seulement l'outil selon la valeur de `filesystem` déjà reçue, rien ne
>   détecte la disponibilité de `mkfs.exfat` ni ne change ce paramètre.
>   Sur une machine sans `mkfs.exfat` (plausible sur une distribution
>   minimale, ex. antiX -- machine de test Linux disponible pour ce
>   projet, i686, sans PySide6 donc sans GUI, mais le CLI/worker suffit
>   pour tester ce chemin précis), le formatage échoue avec
>   `FileNotFoundError`/`CalledProcessError`, rattrapée en best-effort par
>   `cmd_flash` (§4.3 : jamais un échec du flash déjà réussi, seulement un
>   avertissement journalisé) -- pas par un changement silencieux de
>   système de fichiers. Précondition à vérifier avant tout test réel sur
>   une telle machine : `mkfs.exfat` (paquet `exfatprogs` ou `exfat-utils`
>   selon la distribution) est-il installé, sinon le test validera surtout
>   le repli best-effort plutôt que la création réelle.
>
> **`_wait_for_new_partition`** (macOS/Linux uniquement, ignorée sous
> Windows qui retrouve la partition par position) : ré-interroge `list_
> partitions` jusqu'à ce qu'un chemin absent de `known_partition_paths`
> apparaisse, `PARTITION_WAIT_SECONDS` (15 s) au plus -- le délai qu'un OS
> met réellement à reprendre en compte une table de partitions modifiée
> sous lui n'a jamais été mesuré sur du vrai matériel, sur aucun des deux
> OS (déjà signalé dans la docstring de module depuis l'écriture de ce
> fichier, toujours vrai).
>
> **Reste à vérifier sur du vrai matériel macOS/Linux** : que la partition
> est effectivement créée et formatée (montable, bon système de fichiers,
> bonne étiquette EASYROMS) sur les deux OS ; sur Linux spécifiquement,
> avec et sans `mkfs.exfat` installé, pour confirmer que l'absence de
> l'outil dégrade proprement vers l'avertissement best-effort plutôt que
> de planter ailleurs ; que `_wait_for_new_partition` trouve bien la
> nouvelle partition dans les 15 s sans éjection/réinsertion physique de
> la carte.

**« Remettre la carte à zéro » (§4.3 bis, mode expert uniquement).** Besoin
constaté en usage réel : après des essais de firmware, une carte peut
rester en trois à cinq partitions illisibles pour un PC -- Windows ne sait
pas la remettre simplement en état de carte de stockage normale. Nouvelle
opération : efface toute la table de partitions existante (MBR ou GPT) et
recrée une seule partition exFAT occupant toute la carte.

`imaging/reset_card.py` (nouveau module, délibérément distinct de
`games_partition.py` -- celui-ci *ajoute* une partition à une table
existante, celui-là *remplace* toute la table par une seule partition
neuve, la planification n'a donc pas besoin de lire de table existante)
réutilise les briques déjà en place plutôt que d'en écrire de nouvelles :
`imaging/write_target.py::prepared_write_target` (verrouillage/démontage
par OS, §4.3, identique à `flash_device`/`create_games_partition`) pour
l'écriture, et `imaging/games_partition.py::format_games_partition` (déjà
multiplateforme : `diskutil eraseVolume`/`mkfs.exfat`/PowerShell `Format-
Volume`) pour le formatage natif -- rien de nouveau à maintenir par OS
pour cette dernière étape. Exposé en deux fonctions distinctes plutôt
qu'une seule combinée (§ correctif ci-dessous) :
1. `erase_partition_table` -- efface (zéros) une marge de 1 Mio
   (`ALIGNMENT_SECTORS`) en tête *et* en fin de disque -- une éventuelle
   signature GPT (« EFI PART », LBA1) ou une table secondaire en fin de
   disque ne doit pas pouvoir resurgir une fois le nouveau MBR écrit
   par-dessus le seul LBA0 (un outil qui la retrouverait malgré un MBR
   neuf continuerait de rapporter l'ancien schéma GPT).
2. `create_single_partition` -- écrit un MBR neuf (`build_full_disk_mbr_
   sector` -- contrairement à `rewrite_mbr_with_games_partition`, ne lit
   jamais de secteur existant : tout le reste de la table précédente doit
   disparaître, pas gagner une entrée de plus) avec une unique partition
   alignée occupant tout l'espace restant. Sur Windows uniquement, attend
   ensuite un court instant (§ correctif ci-dessous).

CLI : `python -m r36s_studio reset-card --device X [--label ÉTIQUETTE]`
(`__main__.py::cmd_reset_card`) -- écrit sur le périphérique brut comme
`flash` : même confirmation explicite obligatoire (règle §2 n°6,
réutilise `_confirm_flash` tel quel, son texte générique s'applique sans
changement). Quatre étapes réelles, chacune journalisée avant et après
(effacement, création, formatage, éjection -- voir le correctif
ci-dessous) ; nouveau code d'erreur dédié, `RESET_CARD_FAILED` (carte
trop petite, ou une vraie erreur d'écriture/formatage, avec l'étape en
cause dans le message).

GUI (mode expert uniquement, §5) : troisième ligne sous « Par sécurité »,
à côté des deux sauvegardes -- jamais dans le parcours assisté, une
opération destructrice qui n'en fait pas partie. Carte choisie (fenêtre
habituelle) puis, avant même la fenêtre Confirmation, `screens.
ResetCardLabelDialog` (nouvelle fenêtre) demande l'étiquette du volume --
un champ de texte pré-rempli avec une valeur simple par défaut
(`DEFAULT_RESET_LABEL = "SDCARD"`), jamais imposée, jamais vide (le
bouton Continuer n'émet rien tant que le champ est vide plutôt que de
laisser passer une étiquette vide vers le formatage natif). Fenêtre
Confirmation ensuite, obligatoire, avant toute écriture réelle -- jamais
sautée, exactement comme pour un flash.

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : le formatage ne se
> terminait pas -- aucune partition exFAT n'était créée, la carte
> réinsérée restait brute (non reconnue par Windows), l'exact inverse du
> but de la fonctionnalité -- sans qu'aucune erreur ne soit journalisée.**
> L'effacement de la table fonctionnait ; rien après.
>
> **Cause** : `_format_windows` (`games_partition.py`) interroge
> `Get-Partition -DiskNumber N` pour retrouver la partition tout juste
> créée -- mais Windows n'avait pas encore repris en compte le MBR tout
> juste écrit par `create_single_partition` au moment de cette requête.
> Un pipeline PowerShell dont le tout premier maillon ne renvoie rien
> (`Get-Partition` vide) ne lève **aucune erreur** : il n'y a simplement
> rien à faire suivre à `Get-Volume`/`Format-Volume`, qui ne sont donc
> jamais invoqués -- mais `powershell.exe` sort quand même avec le code 0,
> et l'ancien `subprocess.run(check=True)` ne voyait donc rien d'anormal.
> Un échec à mi-parcours ressemblait alors exactement à un succès --
> exactement le défaut signalé : « un échec silencieux à mi-parcours est
> indistinguable d'un succès ».
>
> **Corrigé en trois temps, complémentaires** :
> 1. **Timing** : `create_single_partition` attend désormais un court
>    instant (`_WINDOWS_TABLE_REFRESH_DELAY_SECONDS`, 1 s, Windows
>    uniquement) après avoir écrit le nouveau MBR -- `prepared_write_
>    target` déclenche déjà `IOCTL_DISK_UPDATE_PROPERTIES` en quittant son
>    bloc `with` (`winlock.refresh_disk_properties`, §4.3, réutilisé tel
>    quel plutôt que dupliqué) ; ce délai laisse le temps à Windows de
>    terminer cette reprise en compte avant l'étape suivante.
> 2. **Défense en profondeur** : `_format_windows` réessaie en plus
>    `Get-Partition` plusieurs fois de son côté (`_WINDOWS_PARTITION_
>    RETRY_COUNT` = 10, espacées de `_WINDOWS_PARTITION_RETRY_DELAY_MS` =
>    500 ms, dans le script PowerShell lui-même) -- ni le délai côté
>    Python ni les réessais côté PowerShell n'ont besoin d'être suffisants
>    à eux seuls.
> 3. **Échec rendu bruyant** : si la partition ou son volume restent
>    introuvables après ces réessais, le script PowerShell sort
>    maintenant explicitement en erreur (`exit 1`) au lieu de ne rien
>    faire silencieusement -- `_format_windows` lève alors `OSError` avec
>    le détail (stderr) inclus dans le message, jamais un succès muet.
>    Bénéficie aussi bien à « Remettre la carte à zéro » qu'à la création
>    de partition de jeux existante (`create_and_format_games_partition`,
>    ci-dessus) : les deux utilisent la même fonction.
>
> **Journalisation par étape, à la demande explicite** (« un échec
> silencieux à mi-parcours est indistinguable d'un succès aujourd'hui ») :
> `cmd_reset_card` journalise désormais chacune des quatre étapes avant et
> après (« Effacement de la table de partitions... » / « Table de
> partitions effacée. », etc.) -- plus aucune étape ne peut échouer sans
> laisser de trace, ni réussir sans confirmation explicite dans le journal.
>
> **Barre de progression par étapes réelles, jamais un minuteur (§2 n°5,
> demande explicite).** Un formatage exFAT prend quelques secondes, sans
> estimation de temps restant qui aurait un sens (contrairement au débit
> d'une copie d'image) -- plutôt qu'une fausse barre qui avancerait avec
> le temps, `protocol.py::emit_step_progress(step_index, step_count,
> step_name)` (nouvel événement JSON Lines, `{"type": "step_progress",
> ...}`) n'avance qu'à chaque étape *effectivement terminée* parmi les
> quatre (effacement, création, formatage, éjection) -- jamais simulée.
> `WorkerRunner.step_progress` (nouveau signal Qt, `Signal(int, int,
> str)`) relaie l'événement ; `LogPanel.update_step_progress` fixe la
> barre à `step_index / step_count` et affiche `step_name` **à la place**
> du débit/temps restant habituels (`_speed_label` réutilisé, `_eta_label`
> masqué) -- ces deux derniers n'ont aucun sens pour une progression par
> étapes. Atteint 100 % à la toute fin (`step_index == step_count`, juste
> avant `emit_done(True)`), comme pour le flash.
>
> **Éjection automatique à la dernière étape, revenu sur la conception
> initiale (bouton après succès) suite à une demande explicite.** Une
> partition exFAT neuve ne déclenche aucune proposition de formatage
> Windows (contrairement à `--eject-after` sur `flash`, §4.6, dont le
> risque ne s'applique pas ici) -- mais l'éjection reste listée comme
> l'une des quatre étapes réelles de l'opération elle-même, pas une action
> facultative proposée après coup : `cmd_reset_card` éjecte donc
> automatiquement à sa dernière étape, en best-effort (un échec d'éjection
> ne remet jamais en cause la remise à zéro déjà réussie, même principe
> que `--eject-after`). `"reset_card"` a été retiré de `_ALLOW_EJECT_
> AFTER_MODES` (`gui/main_window.py`) en conséquence -- un bouton Éjecter
> après coup serait redondant, même principe qu'un flash Android
> (`android_flash`) qui masque déjà ce bouton pour la même raison.

> ⚠️ **Deuxième bug corrigé, confirmé sur du vrai matériel après le
> correctif ci-dessus : le formatage se termine bien (`Get-Volume` montre
> un volume exFAT correctement formaté, bonne taille, bonne étiquette),
> mais sans lettre de lecteur il n'apparaît pas dans l'Explorateur -- la
> carte semble non reconnue alors qu'elle est parfaitement formatée.**
> Attribuer une lettre à la main (`Set-Partition -NewDriveLetter K`) la
> fait apparaître immédiatement -- confirmant que le formatage
> lui-même n'était pas en cause, seule l'étape suivante manquait.
>
> **Corrigé** : `_format_windows` (`games_partition.py`) attribue
> désormais la première lettre libre juste après `Format-Volume`
> (`Add-PartitionAccessPath -AssignDriveLetter`, dans le même script
> PowerShell -- exige l'élévation, « Access denied » sans, même piège que
> `IOCTL_STORAGE_EJECT_MEDIA` pour l'éjection, §4.4 : cette fonction n'est
> jamais appelée en dehors du worker élevé, §3, donc toujours dans le bon
> contexte), puis relit la lettre effectivement attribuée
> (`Get-Partition ... | Select DriveLetter`) et la fait remonter à
> l'appelant via la sortie standard (`DRIVE_LETTER=K`, parsée côté
> Python). `format_games_partition` retourne désormais cette lettre
> (`Optional[str]`, toujours `None` sur macOS/Linux -- aucune notion de
> lettre de lecteur là-bas) plutôt que `None` inconditionnellement ;
> `GamesPartitionResult` gagne un champ `drive_letter` du même nom, rempli
> par `create_and_format_games_partition`. `cmd_reset_card` (nouvelle
> étape journalisée, « La carte est disponible sous K:. ») et `cmd_flash`
> (création automatique de la partition de jeux, §4.3) journalisent tous
> les deux cette lettre quand elle est connue -- le même bug aurait
> affecté les deux fonctionnalités de façon identique, `_format_windows`
> étant partagée entre les deux.
>
> **macOS/Linux, vérifié plutôt que supposé (demande explicite).** Aucune
> notion de lettre de lecteur sur ces deux OS, mais la question sous-
> jacente (le volume fraîchement formaté est-il seulement *accessible* ?)
> se pose tout autant :
> - **macOS** : `diskutil eraseVolume` est documenté pour laisser le
>   volume monté (Disk Arbitration monte automatiquement tout système de
>   fichiers reconnu) -- comportement connu, mais **non vérifié sur du
>   vrai matériel dans ce projet** (aucun Mac disponible ici). `_format_
>   macos` tente désormais en plus un `diskutil mount` explicite en
>   best-effort après l'effacement -- sans effet dans le cas normal
>   (déjà monté), filet de sécurité si l'hypothèse s'avérait fausse dans
>   un cas non couvert ici.
> - **Linux** : contrairement à macOS, `mkfs.exfat`/`mkfs.vfat` ne
>   montent jamais eux-mêmes le système de fichiers qu'ils créent -- que
>   le montage suive ensuite dépend entièrement d'un service
>   d'automontage (udisks2 + un gestionnaire de fichiers de bureau) qui
>   n'est pas garanti présent sur toute installation Linux (ex. une
>   distribution minimale sans environnement de bureau complet -- même
>   machine de test évoquée au §8, Eee PC/antiX). **Écart réel et non
>   théorique, non vérifié faute de matériel Linux disponible ici** :
>   contrairement à macOS, l'hypothèse « ça se monte tout seul » n'a
>   jamais été une garantie documentée du côté de `mkfs.*`. `_format_
>   linux` tente donc désormais un `udisksctl mount -b` explicite en
>   best-effort après le formatage (même mécanisme non privilégié déjà
>   utilisé ailleurs dans ce projet pour le montage, §4.4) -- sans
>   effet si l'automontage a déjà fait le travail, mais comble le cas où
>   il est absent.
>
> Les deux tentatives macOS/Linux sont volontairement best-effort (jamais
> un échec de l'opération globale) et ne remontent aucune information de
> résultat à l'appelant (contrairement à Windows, aucun équivalent de
> "lettre de lecteur" à journaliser côté succès) -- seule la lettre
> Windows est explicitement confirmée et journalisée, comme demandé.

**Non confirmé sur du vrai matériel au moment d'écrire cette note**
(aucune carte physique disponible ici) : ces deux correctifs réparent des
bugs *rapportés* sur du vrai matériel, mais n'ont pas encore été retestés
sur ce même matériel une fois corrigés -- en particulier l'hypothèse
macOS (jamais vérifiée dans ce projet) et le correctif Linux (écrit sans
aucun accès à une machine Linux ici). La logique bas niveau est testée
bout en bout (reparsing indépendant du secteur produit, comme `test_
imaging_games_partition.py`), et le CLI/la GUI sont couverts par des
tests qui mockent `erase_partition_table`/`create_single_partition`/
`format_games_partition`/`WorkerRunner` -- mais jamais contre un vrai
périphérique bloc, sur aucun OS. Le formatage natif hérite des mêmes
zones d'ombre déjà documentées pour `create_and_format_games_partition_
if_worthwhile` ci-dessus (seule la branche Windows a été validée sur du
vrai matériel pour l'ancien mécanisme `--create-games-partition`, jamais
pour celui-ci ni pour macOS/Linux).

> ⚠️ **Défaut corrigé au passage, signalé comme sans conséquence
> fonctionnelle : le journal affichait « Éjection automatique de la carte
> (firmware Android)… » après un flash ArkOS.** Cause : `--eject-after`
> a été généralisé à tout le catalogue (§4.6, au moins une partition de
> tout firmware -- pas seulement Android -- est illisible pour Windows),
> mais le message correspondant dans `__main__.py::cmd_flash` était resté
> celui d'avant cette généralisation, jamais mis à jour. L'éjection
> elle-même se déclenchait déjà correctement pour ArkOS (comportement
> voulu depuis la généralisation) -- seul le texte affiché était trompeur,
> laissant croire à une erreur de détection de firmware qui n'existait pas.
> **Corrigé** : message neutre, « Éjection automatique de la carte… »,
> sans mention d'un firmware précis -- cohérent avec le fait que ce
> drapeau s'applique désormais à tout le catalogue. Corrigé au passage
> dans l'aide `--eject-after` du parser (`--help`), qui portait la même
> affirmation obsolète.

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

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel — cause réelle du rapport
> ci-dessous : `Get-Volume` ne préserve pas l'ordre de son entrée
> pipeline.** `partitions/locate.py::_list_windows` faisait `Get-Partition
> -DiskNumber N | Sort-Object PartitionNumber | Get-Volume`, en supposant
> que trier les partitions *avant* `Get-Volume` suffirait à obtenir les
> volumes dans le même ordre en sortie. Faux : `Get-Volume` renvoie ses
> résultats selon sa propre énumération interne, indépendante de l'ordre
> de son entrée. Constaté en répétant l'appel plusieurs fois de suite sur
> la même carte R36S réelle (ThinkPad, lecteur SD Realtek intégré), sans
> rien changer côté matériel entre les appels : l'ordre alternait entre
> `[EASYROMS, BOOT, (partition Linux)]` et `[BOOT, (partition Linux),
> EASYROMS]` selon l'invocation.
>
> Impact concret : la sauvegarde « système sans les jeux » (§4.3) identifie
> la partition de jeux par étiquette (`EASYROMS`/`STORAGE`), *peu importe*
> son système de fichiers — mais refuse explicitement de continuer si
> cette partition se retrouve en première position (rien à garder avant
> elle). Quand l'ordre aléatoire plaçait `EASYROMS` en tête, l'opération
> échouait avec « Aucune partition de jeux reconnue » (`GamesPartitionNot
> Found`) alors que la carte est parfaitement standard — un échec
> intermittent, pas systématique, cohérent avec un rapport utilisateur qui
> voit l'échec une fois mais pas forcément à chaque tentative.
>
> **Corrigé** : chaque volume est désormais explicitement ré-associé à son
> `PartitionNumber` d'origine dans la boucle PowerShell elle-même
> (`ForEach-Object` + `Add-Member`, plutôt que de faire confiance à l'ordre
> du pipeline), puis la liste est triée une seconde fois côté Python sur ce
> champ. Un ordre déjà correct n'est jamais perturbé par ce second tri
> (stable, et l'ordre PowerShell était déjà par moments le bon). Vérifié en
> répétant l'appel une dizaine de fois de suite sur la carte réelle après
> correctif : ordre `[BOOT, (partition Linux), EASYROMS]` stable à chaque
> fois.
>
> **Second effet de bord découvert en vérifiant ce correctif** : pour la
> partition Linux (`ext4`, système de fichiers que Windows ne reconnaît
> pas), `Get-Volume` renvoie bien un objet volume (« RAW »), mais avec
> `Size: 0` plutôt qu'un champ absent — une vraie partition de 0 octet
> n'existe pas sur une carte SD flashée, `0` ici signifie « taille
> inconnue », comme le `None` que `PartitionInfo.size_bytes` représente
> déjà pour ce cas sur les autres OS. Sans distinction, `imaging/system_
> backup.py::estimate_system_backup_size_unprivileged` (§4.3, l'estimation
> affichée avant de lancer l'opération) additionnait ce `0` au lieu de
> détecter une taille manquante et de retomber sur son repli élevé — sur
> cette carte réelle, ça aurait affiché « ~115 Mo » (la taille de `BOOT`
> seul) au lieu de retomber sur le calcul exact, pour une sauvegarde
> système qui fait en réalité plusieurs Go (`BOOT` + la partition Linux).
> `_list_windows` traite désormais toute taille à `0` comme inconnue
> (`None`), jamais comme une vraie partition vide.

> ⚠️ **Confirmé sur du vrai matériel : `EASYROMS` peut aussi être en exFAT,
> pas seulement en NTFS.** Rapporté sur une carte R36S branchée à un
> ThinkPad Windows : `Get-Volume` y montre bien l'étiquette `EASYROMS`,
> mais son `FileSystem` vaut `exFAT`, pas `NTFS` — le système de fichiers
> d'EASYROMS varie donc selon le vendeur de la carte, comme `BOOT` (§4.4
> ci-dessus, FAT16 ou FAT32 selon les cartes). Traiter ce champ comme un
> critère d'exclusion plutôt qu'une simple info cassait deux chemins qui le
> comparaient à un ensemble figé de systèmes de fichiers plausibles :
> 1. `imaging/system_backup.py::GAMES_PARTITION_FALLBACK_FILESYSTEMS`
>    (sauvegarde « système sans les jeux », §4.3) et `partitions/
>    locate.py::EASYROMS_FALLBACK_FILESYSTEMS` (repli sans étiquette,
>    ci-dessus) ne listaient que FAT/NTFS — une carte dont EASYROMS
>    retombe sur ce repli (étiquette absente ou non lue) et se trouve en
>    exFAT y échouait avec `GamesPartitionNotFound`/`PartitionNotFound`.
>    Les deux ensembles incluent désormais `"exfat"`.
> 2. `detect/__init__.py::detect_workflow_status` marquait `copy_games`
>    `StepStatus.PLATFORM_LIMITED` sur macOS *inconditionnellement* (badge
>    « PC ou Linux »), en supposant EASYROMS toujours en NTFS — alors que
>    macOS écrit l'exFAT nativement, contrairement au NTFS (pilote intégré
>    en lecture seule). Corrigé : `selected_easyroms_partition` (nouvelle
>    fonction publique de `locate.py`, réutilise `_select_easyroms` sans
>    dupliquer sa logique d'identification) donne le système de fichiers
>    réel d'EASYROMS sur la carte *actuellement* branchée ; la limitation
>    n'est levée que si celui-ci est *positivement* confirmé différent de
>    NTFS — par défaut (aucune carte, ou EASYROMS non identifiable sur
>    celle-ci), le badge reste affiché comme avant, pour garder
>    l'avertissement précoce même sans carte insérée.
>
> Ni `jobs.py::_reject_macos_ntfs_write` (compare l'exact `== "ntfs"`) ni
> `_macos_filesystem` (normalise vers `"ntfs"` ou tombe sur la valeur brute
> du système, `"exfat"` déjà telle quelle chez `diskutil`) n'avaient besoin
> de changer : une EASYROMS exFAT sur macOS n'a jamais déclenché
> `MacosNtfsWriteUnsupported` à tort, seul le badge informatif était trop
> pessimiste.

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
>    `extract_easyroms`, `inject_boot`, `copy_games` (`jobs.py`) et le
>    calcul d'empreinte des étapes 1/3 du parcours de clonage (§5,
>    `compute_boot_fingerprint`, `safety/card_fingerprint.py`).
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

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : « carte défaillante »
> affiché à tort à l'étape 2 (identification) sous Windows.** Rapporté sur
> un ThinkPad avec lecteur SD Realtek intégré : le journal montrait
> `PartitionNotMounted` (« délai dépassé ») pour `BOOT`, alors que
> `Get-Volume` confirme que la partition (FAT32, 115 Mo) existe et est
> parfaitement lisible — elle n'a simplement pas de lettre de lecteur.
> Cause de fond : contrairement à macOS/Linux, où `locate_mounted` retente
> activement un montage (`_mount_macos`/`_mount_linux`) avant d'abandonner,
> Windows n'a *aucune* tentative active dans la boucle — `_list_windows`
> attend passivement qu'une lettre apparaisse, ce qui n'arrive jamais pour
> une partition que Windows ne juge pas devoir monter spontanément (rien à
> voir avec un défaut matériel). Le message `MOUNT_FAILED` (« carte
> défaillante, courant sur les cartes fournies avec la console »),
> initialement pensé pour ce cas macOS/Linux, était donc trompeur ici.
>
> **Corrigé en deux temps**, tous les deux dans `locate.py`/`gui/main_
> window.py` :
> 1. **Monter sans lettre de lecteur, sans élévation.** Chaque volume a
>    aussi un chemin GUID stable (`\\?\Volume{...}\`, propriété
>    `AccessPaths` de `Get-Partition`, distincte de `Get-Volume`) —
>    confirmé lisible sur du vrai matériel (`os.listdir`/`open`, sans
>    élévation, sans lettre de lecteur assignée) : une identification
>    complète (lecture des `.dtb`, reconnaissance du modèle) a réussi en
>    passant directement par ce chemin. `_list_windows` (dans la même
>    boucle PowerShell qui ré-associe déjà `PartitionNumber`, voir plus
>    haut) récupère désormais aussi ce chemin (`VolumeGuidPath`) et
>    l'utilise comme `mountpoint` quand aucune lettre n'est disponible —
>    `locate_mounted` n'a alors même plus besoin d'attendre : le montage
>    est déjà là dès le premier appel. Respecte §4.4 (l'identification
>    doit rester non privilégiée) : aucune élévation n'est nécessaire,
>    c'est un simple chemin de fichier alternatif vers le même volume.
> 2. **Message différent selon l'OS pour le cas résiduel.** Même avec ce
>    repli, un échec de montage reste théoriquement possible (aucun
>    `AccessPaths` exploitable). `gui/main_window.py::
>    _identify_failure_message_key` choisit désormais entre le message
>    existant (macOS/Linux, où un échec après tentative active de montage
>    reste un signal fiable de carte défaillante) et un nouveau message
>    Windows (`wizard_identify_failed_mount_windows`, `gui/strings.py`)
>    qui invite à débrancher/rebrancher la carte sans jamais suggérer un
>    défaut matériel.
>
> Bénéfice au passage : ce repli sert `_list_windows` pour *toute*
> opération sur une partition sans lettre de lecteur, pas seulement
> l'identification — extraction du BOOT (étape A) comprise, qui aurait
> échoué de la même façon sur une carte avec cette même particularité.

Copie de fichiers : parcours récursif avec cumul d'octets pour la progression, puis
`fsync` et démontage propre à la fin.

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : une copie EASYROMS
> restait bloquée, CPU à fond, sans jamais rien lire ni écrire.** Rapporté
> pendant un test réel de l'étape 3 (copie de l'écran et des jeux) : 392 s
> de temps CPU consommées, `ReadTransferCount` à 0 Mo, processus toujours
> « Responding ». Hypothèse initiale (chemin GUID de volume, ci-dessus,
> ajouté par un correctif récent et validé seulement sur `BOOT` — 47 Mo,
> arborescence plate) écartée après investigation : la même lenteur
> apparaît **identiquement** via une lettre de lecteur classique (`D:\`)
> que via le chemin GUID — rien à voir avec ce correctif.
>
> **Cause réelle, isolée sur la carte en cause** : un seul dossier
> (`ports/bigboy/tiles`, les tuiles d'un port de jeu) contient **40 964
> fichiers**. `partitions/copy.py::_list_files` énumérait via `Path.
> rglob("*")` puis filtrait avec `Path.is_file()` (un appel), et `copy_
> tree` recalculait ensuite `Path.stat().st_size` (un second appel) pour
> chaque fichier — deux recherches par nom, chacune reprenant l'exploration
> du dossier depuis le début sur un système de fichiers FAT/exFAT (pas
> d'index par nom, seulement une table de répertoire parcourue
> linéairement) : un coût en O(n) par fichier, donc O(n²) pour vider un tel
> dossier. Confirmé isolément sur ce dossier réel : plus de 120 s sans même
> terminer la première passe (`Path.is_file()` seul).
>
> **Corrigé** : `_list_files` est remplacée par `_walk_files`
> (`os.scandir()`, récursif), qui réutilise directement les attributs déjà
> obtenus par l'énumération elle-même (`FindNextFileW` sous Windows, via
> `DirEntry.is_file()`/`DirEntry.stat()`, tous deux mis en cache) plutôt
> que de redemander l'information par une recherche par nom séparée —
> O(n) au total, un seul passage. `copy_tree` ne fait donc plus non plus
> le second passage `Path.stat()` : `_walk_files` retourne directement les
> couples `(chemin, taille)`. **Confirmé sur le dossier réel en cause** :
> les mêmes 40 964 fichiers traités en 0,26 s (repli lettre de lecteur ou
> GUID, indifféremment) ; l'arborescence EASYROMS complète de cette carte
> (46 092 fichiers, ~3,9 Go) traitée en 0,53 s, contre un blocage qui ne
> se serait jamais terminé auparavant.

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
> ⚠️ **Bug corrigé, confirmé sur du vrai matériel (parcours de clonage,
> Windows) : la carte source n'était jamais réellement éjectée à l'étape 3.**
> `eject()` levait purement et simplement `NotImplementedError` sous
> Windows depuis le début du projet -- un vrai trou, pas juste un cas mal
> géré : `_run_wizard_source_eject` (`gui/main_window.py`) l'attrapait
> bien et affichait l'erreur dans le journal (jamais un échec silencieux
> côté GUI), mais la carte, elle, restait montée et non éjectée pour de
> vrai. **Corrigé** : `_windows_eject` (`partitions/eject.py`) verrouille
> et démonte chaque volume monté du disque
> (`imaging/winlock.py::lock_and_dismount_volumes`, même mécanisme que
> l'écriture brute, §4.3), puis envoie l'éjection matérielle proprement
> dite au disque physique (`IOCTL_STORAGE_EJECT_MEDIA`, nouvelle fonction
> `winlock.eject_media` -- contrairement à `refresh_disk_properties`,
> best-effort, celle-ci lève en cas d'échec, une éjection ratée devant
> être signalée, §2 règle 5). Les lettres de lecteur du disque sont
> retrouvées via une requête PowerShell dédiée
> (`_windows_drive_letters`, `Get-Partition -DiskNumber N`) ; une
> partition sans lettre (BOOT sans lettre, §4.4) n'a simplement rien à
> démonter, l'éjection matérielle a quand même lieu.
>
> ⚠️ **Gap connu, non corrigé ici** (repéré en corrigeant le bug d'écriture
> ci-dessous, §4.3 « Bad file descriptor ») : `_windows_drive_letters`
> partage le même défaut que l'ancien code d'écriture -- seules les
> partitions *avec* une lettre de lecteur sont verrouillées/démontées
> avant l'éjection, BOOT (sans lettre) n'y figure jamais. Contrairement à
> l'écriture, une éjection ne maintient pas un accès brut soutenu pendant
> plusieurs minutes : rien ne prouve que ce gap cause un échec observable
> en pratique (pas de rapport en ce sens), mais il partage la même cause
> structurelle et mériterait le même traitement (`write_target.
> _windows_all_volume_paths`, toutes les partitions du disque) si un
> problème d'éjection est un jour rapporté.
>
> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : l'éjection ne
> fonctionnait jamais sur Windows, ni automatiquement (étape 3 du parcours
> de clonage) ni via le bouton du journal (mode expert comme mode
> assisté).** Le correctif ci-dessus (`_windows_eject`) répare bien
> l'implémentation Windows de `partitions/eject.py::eject`, mais cette
> fonction continuait d'être appelée **directement dans le processus GUI**
> (`gui/main_window.py::_perform_eject`/`_on_eject_requested`/`_run_
> wizard_source_eject`/`_run_wizard_eject`) -- à privilèges normaux, alors
> qu'ouvrir `\\.\PhysicalDriveN` pour `IOCTL_STORAGE_EJECT_MEDIA` exige
> l'élévation, exactement comme l'écriture brute (§4.3). Le flash y
> échappe déjà puisqu'il passe par le worker élevé (§3) ; l'éjection, elle,
> ne le faisait jamais. Symptômes observés :
> - **Bouton « Éjecter la carte » du journal** : `impossible d'ouvrir
>   \\.\PhysicalDrive1 (erreur 5)` -- `ERROR_ACCESS_DENIED`, affiché dans
>   une simple `QMessageBox` jamais journalisée (violation de la règle
>   « jamais un succès -- ni un échec -- silencieux », §4.4).
> - **Éjection automatique de la carte source avant l'étape « insère la
>   carte neuve »** (§5, `_run_wizard_source_eject`) : échec entièrement
>   silencieux, aucune ligne dans le journal entre la fin de la sauvegarde
>   et la détection suivante -- risque de corruption si l'utilisateur
>   retire la carte (exFAT/NTFS) sans savoir que l'éjection a échoué.
>
> **Corrigé** : les quatre points d'appel passent désormais par un worker
> élevé dédié (`gui/main_window.py::_start_eject`, réutilise `gui.worker_
> runner.WorkerRunner` avec `["eject", "--device", device.path]` --
> exactement le même mécanisme que `backup`/`flash`), jamais un appel
> synchrone à `partitions.eject.eject` dans le processus GUI. `__main__.py
> ::cmd_eject` gagne `--worker`/`--progress-file`/`--cancel-file`
> (`_add_worker_args`, déjà utilisés par `backup`/`flash`) pour pouvoir
> tourner comme worker élevé -- son échec émet désormais un code dédié,
> `EJECT_FAILED` (déjà utilisé côté GUI avant ce correctif pour un échec
> local, message : « ferme les fichiers ouverts... ou retire-la
> manuellement »), plutôt que le générique `IO_ERROR`. Chaque appelant
> (`_perform_eject`, `_on_eject_requested`, `_run_wizard_source_eject`,
> `_run_wizard_eject`) journalise désormais explicitement le résultat,
> succès comme échec (§4.4) -- `_on_eject_requested` ne se contentait
> auparavant que d'une `QMessageBox` en cas d'échec, jamais du journal.
>
> **Invite d'élévation supplémentaire, tranché en faveur de la
> fiabilité.** Chaîner l'éjection dans le worker qui vient d'écrire/de
> lire (`backup`/`flash`, déjà élevé) aurait évité une seconde invite UAC
> pour l'éjection automatique de l'étape 3 -- envisagé, non retenu : ça
> ferait perdre la distinction entre « la sauvegarde a réussi » et « l'
> éjection qui a suivi a échoué », nécessaire pour bloquer la suite du
> parcours tant que la carte source n'est pas sûre à retirer (le job
> `DETECT_TARGET` n'est jamais marqué fait sur un échec d'éjection --
> `Reprendre` relance alors cette éjection, pas toute la sauvegarde).
> Windows n'a de toute façon pas d'équivalent de `MacosAuthorizationSession`
> (§3, « ce correctif ne change rien pour Windows/Linux, qui continuent de
> redemander l'élévation à chaque worker élevé ») -- une invite
> supplémentaire par éjection reste donc cohérente avec le reste du projet
> sur cet OS, plutôt qu'une exception à ce principe déjà établi.
>
> **Non vérifié** : si `IOCTL_STORAGE_EJECT_MEDIA` fonctionnerait sur un
> handle ouvert en lecture seule sans élévation (ce qui éviterait
> l'élévation pour le seul cas du bouton) -- aucune carte physique
> disponible pour le tester ici, et l'hypothèse la plus probable reste que
> Windows restreint tout accès direct à `\\.\PhysicalDriveN`
> indépendamment du mode d'ouverture (lecture seule ou lecture/écriture),
> comme c'est déjà le cas pour l'écriture brute (§4.3). Piste future, à
> tenter uniquement si une session dispose d'un vrai lecteur de carte SD
> Windows pour vérifier sans risque de casser le correctif actuel.
>
> **Non confirmé sur du vrai matériel au moment d'écrire cette note**
> (aucune carte physique disponible ici) : la logique (worker élevé dédié,
> code d'erreur `EJECT_FAILED`, journalisation systématique) est couverte
> par des tests qui simulent le worker (`WorkerRunner` mocké, callback de
> fin appelé directement pour reproduire un succès ou un échec) plutôt que
> d'exécuter une vraie élévation Windows -- c'est précisément ce mécanisme
> non simulable ici (élévation réelle, disparition effective de la carte
> dans l'Explorateur Windows) qui reste à vérifier au premier test en
> conditions réelles.

> ⚠️ **Quatrième signalement, sur du vrai matériel, non résolu -- diagnostic
> ajouté en attendant, pas encore un correctif.** Malgré tout ce qui
> précède, l'éjection automatique de la carte source (mode assisté, entrée
> dans l'étape 3/DETECT_TARGET) ne se produit toujours pas : journal réel
> montrant la fin de la sauvegarde système suivie *directement* de la
> prochaine ligne de détection, six heures plus tard, sans une seule ligne
> d'éjection entre les deux -- ni succès, ni échec (§4.4 : exactement ce
> que ce module doit justement ne jamais laisser passer). Conséquence
> aggravée avec une image Android (§4.6, `is_android`) : les partitions de
> la carte source restent montées, Windows propose de les formater --
> risque réel de destruction si l'utilisateur accepte par erreur.
>
> **Cause non confirmée.** Avant ce correctif, `_run_wizard_source_eject`
> journalisait `wizard_ejecting_source` *après* `show_step(...)` et *avant*
> `_start_eject(...)`, sans aucune protection contre une exception --
> `self._wizard_source_device` valant `None` (état incohérent, cause non
> vérifiée) aurait fait échouer `_start_eject` sur `device.path` avant même
> d'atteindre `WorkerRunner`, avec l'exception remontant sans jamais
> toucher le journal : une explication plausible du symptôme exact
> rapporté, mais non confirmée sur le vrai matériel en cause -- aucune autre
> piste n'a été exclue non plus (`_on_wizard_job_finished`/`_enter_wizard_
> job` n'atteignant jamais DETECT_TARGET, par exemple).
>
> **Diagnostic ajouté, pas encore un correctif** : la ligne
> `wizard_ejecting_source` est désormais journalisée en tout premier, avant
> `show_step`, avec le reste du corps de `_run_wizard_source_eject`
> protégé par un `try/except` qui journalise explicitement toute exception
> (nouveau message, `friendly_error_message("EJECT_FAILED")` + détail brut)
> plutôt que de la laisser disparaître -- `_start_eject` réinitialise aussi
> l'état « occupé » des deux écrans si la construction du `WorkerRunner`
> échoue avant même son démarrage, pour ne jamais laisser l'interface
> bloquée sans issue dans ce cas. Si cette ligne apparaît enfin au prochain
> test réel (avec ou sans message d'erreur à sa suite), le bug est confirmé
> plus haut dans la chaîne (`_on_wizard_job_finished`/`_enter_wizard_job`)
> et cette instrumentation n'aura fait que l'exclure ; si un message
> d'erreur explicite apparaît à sa place, la cause exacte sera enfin connue
> et corrigeable directement. **Non testé sur du vrai matériel** (aucune
> carte physique disponible ici) -- couvert seulement par deux nouveaux
> tests (`tests/test_gui_main_window.py` :
> `test_entering_detect_target_logs_before_starting_the_eject_worker`,
> `test_entering_detect_target_with_no_source_device_logs_instead_of_
> vanishing`) qui simulent l'état incohérent plutôt que de le reproduire
> sur un vrai lecteur.

> ⚠️ **Audit multi-plateforme (demandé explicitement) : tout le travail
> d'éjection de ces derniers jours n'a été validé que sur Windows --
> revue de ce qui est commun aux trois OS et de ce qui reste propre à
> chacun, pour ne présenter comme acquis que ce qui l'est vraiment.**
>
> **Code commun aux trois OS (`eject()`, `partitions/eject.py`,
> `cmd_eject`, `__main__.py`)** : le dispatch par `platform.system()`, et
> tout le mystère du quatrième signalement ci-dessus (`_run_wizard_source_
> eject`/`_enter_wizard_job`/`_on_wizard_job_finished`, `gui/main_
> window.py`) -- aucune branche par OS avant d'atteindre `eject_device()`.
> Si la cause réelle de « la fonction ne semble jamais appelée » s'avère
> être dans cette partie commune (état incohérent, transition de job
> ratée...), elle concernerait les trois OS de la même façon -- mais
> aucun rapport ni aucun test réel n'existe à ce jour pour macOS/Linux sur
> ce point précis : les quatre signalements disponibles viennent tous du
> même poste Windows. `_start_eject`/`WorkerRunner` (§3) sont eux aussi
> entièrement communs -- invoquer `python -m r36s_studio eject --device
> <chemin> --worker --progress-file <fichier>` (élevé, ex. via `sudo` sur
> Linux) exerce exactement le même chemin que la GUI, sans avoir besoin de
> PySide6 pour le tester.
>
> **Ce qui diverge ensuite, par OS, dans `eject()` lui-même** :
> - **Windows** (`_windows_eject`, `imaging/winlock.py`) : de loin le plus
>   travaillé -- verrouillage par volume, réessais sur `ERROR_ACCESS_
>   DENIED`, gestion des partitions sans lettre de lecteur, `IOCTL_
>   STORAGE_EJECT_MEDIA`... **confirmé sur du vrai matériel**, à plusieurs
>   reprises, avec le détail exact de chaque échec rencontré (§4.3/§4.4
>   ci-dessus).
> - **macOS** (`subprocess.run(["diskutil", "eject", device_path], ...)`)
>   -- une seule commande, jamais modifiée pendant toute cette série de
>   correctifs. **Jamais confirmée sur du vrai matériel** dans ce projet,
>   à aucun moment -- aucune trace d'un test réel dans cet historique,
>   contrairement à Windows. Risque plausible, non vérifié : si la carte a
>   plusieurs volumes montés séparément (BOOT visible mais monté de façon
>   inhabituelle, §4.4), `diskutil eject` sur le disque entier devrait
>   suffire (il démonte tous les volumes du disque avant d'éjecter,
>   d'après sa documentation), mais ça n'a jamais été observé en pratique
>   ici.
> - **Linux** (`subprocess.run(["udisksctl", "power-off", "-b",
>   device_path], ...)`) -- une seule commande également, jamais modifiée
>   non plus. **Jamais confirmée sur du vrai matériel.** Précondition non
>   vérifiée : `udisksctl` (paquet `udisks2`) doit être installé et son
>   service tourner -- pas garanti sur une distribution minimale (ex.
>   antiX, mentionnée explicitement comme banc de test disponible pour ce
>   projet, machine i686 sans environnement de bureau complet) ; si absent,
>   `subprocess.run` lève `FileNotFoundError`, jamais testé ni géré
>   spécifiquement ici (retombe sur le comportement générique du code
>   appelant : `EJECT_FAILED` côté CLI élevé, §4.4).
>
> **Reste à vérifier sur du vrai matériel macOS/Linux** : que `eject()`
> réussit réellement (la carte disparaît du système) sur les deux OS,
> pour un cas simple (une seule partition montée) et pour une carte R36S
> réelle (BOOT + root + EASYROMS/STORAGE, plusieurs volumes) ; que
> `udisksctl` est bien présent sur l'environnement Linux visé, ou sinon
> quel message l'utilisateur voit réellement. La partie « pourquoi la
> fonction ne semble parfois jamais appelée » (quatrième signalement,
> code commun) reste ouverte sur les trois OS, faute de rapport ou de
> test réel en dehors de Windows.

> ⚠️ **Trois défauts distincts rapportés sur l'éjection en mode assisté,
> tous corrigés.**
>
> **1. Message d'erreur faux sur une invite UAC refusée.** `ShellExecuteExW`
> (verbe `runas`) peut lever une exception *synchrone*, avant même que le
> protocole JSON Lines n'ait quoi que ce soit à relayer, quand l'utilisateur
> refuse ou ferme l'invite (`GetLastError() == ERROR_CANCELLED`, 1223) --
> confirmé sur du vrai matériel. Cette exception, un simple `OSError`
> générique jusqu'ici, remontait telle quelle jusqu'à l'appelant : le
> `try/except` de `_run_wizard_source_eject` la retombait systématiquement
> sur le code codé en dur `EJECT_FAILED`, affichant « Ferme les fichiers
> ouverts dessus... » -- sans aucun rapport avec la cause réelle (un refus
> d'élévation, pas un fichier verrouillé). **Corrigé** : `gui/elevate.py::
> ElevationRefusedError` (sous-classe d'`OSError`, rien ne casse côté code
> qui l'attrape encore génériquement) distingue ce cas précis à la source
> (`_launch_windows`, `ERROR_CANCELLED = 1223`). `_start_eject`
> (`main_window.py`) intercepte désormais `runner.start()` lui-même --
> jamais fait auparavant, une omission distincte de ce qui précède -- et
> route systématiquement vers `on_finished(False, code, msg)` plutôt que de
> laisser l'exception se propager : `ELEVATION_REFUSED` pour ce cas précis
> (message dédié, « L'autorisation Windows a été refusée. Réessaie et
> accepte l'invite. »), `EJECT_FAILED` pour toute autre exception au
> démarrage comme avant. Plus aucun appelant (`_perform_eject`, `_on_eject_
> requested`, `_run_wizard_eject`, `_run_wizard_source_eject`) n'a besoin de
> son propre `try/except` pour ce cas précis -- `_run_wizard_source_eject`
> en gardait un pour d'autres causes (ex. `self._wizard_source_device`
> valant `None`), qui reste en place mais ne voit plus jamais passer un
> refus d'élévation par ce chemin.
>
> **2. Chemin périmé réutilisé à la deuxième tentative.** Rapporté : un
> deuxième essai après un premier échec réutilisait tel quel l'ancien
> chemin Windows (`\\.\PhysicalDriveN`) de la première tentative -- rejeté
> ensuite par le worker élevé lui-même comme introuvable
> (`DEVICE_NOT_ALLOWED`, `_resolve_device_or_report`) : Windows a pu
> libérer/renuméroter ce chemin entre les deux essais (ex. après une
> invite UAC refusée). **Corrigé** : `MainWindow._refresh_device_before_
> eject_retry` (nouveau) redétecte la carte (`_list_safe_devices()`, déjà
> non privilégié) avant *chaque* tentative d'éjection -- y compris la toute
> première, sans effet sur le cas normal (retrouve simplement la même
> carte) -- plutôt que de faire confiance à l'objet `Device` capturé une
> fois pour toutes. Un seul candidat détecté -> utilisé directement
> (l'éjection ne modifie aucune donnée, contrairement à une écriture :
> aucune vérification d'empreinte supplémentaire n'est nécessaire ici,
> § pré-vol réservée aux écritures) ; zéro ou plusieurs -> message
> explicite (`DEVICE_NOT_ALLOWED`) plutôt qu'une tentative sur un chemin
> peut-être mort. Appliqué aux deux ejections du parcours guidé (source,
> étape 3 ; cible, étape 5) -- pas aux boutons d'éjection du mode expert
> (`_perform_eject`/`_on_eject_requested`), qui partagent en théorie le
> même risque mais n'ont pas été signalés et n'ont donc pas été touchés
> ici, pour limiter le risque de régression à ce qui a été demandé.
>
> **3. Invite UAC supplémentaire rien que pour l'éjection, en plus de
> celle de la sauvegarde.** Rapporté précisément pour l'éjection de la
> carte *source* (étape 3, `_run_wizard_source_eject`, immédiatement après
> la sauvegarde de l'étape 2) -- chaque étape élevée redemande l'UAC sur
> Windows (§3, aucun équivalent de `MacosAuthorizationSession`), donc
> l'éjection dédiée existante ajoutait une seconde invite juste après
> celle de la sauvegarde. **Chaîner l'éjection dans le worker qui vient de
> lire la carte avait déjà été envisagé et écarté** (voir le docstring de
> `_start_eject` ci-dessus, encore valable pour le cas général) : le
> risque identifié était de perdre la distinction entre « la sauvegarde a
> réussi » et « l'éjection qui a suivi a échoué » -- si un échec
> d'éjection chaîné faisait échouer tout le `backup`, Reprendre relancerait
> toute la copie (potentiellement plusieurs Go, plusieurs minutes) juste
> pour réessayer une éjection ratée. **Résolu sans ce compromis** grâce à
> un canal séparé : `protocol.py::emit_eject_result(ok, msg)` (nouvel
> événement `eject_result`, distinct de `done`) rapporte le résultat de
> l'éjection chaînée sans jamais le mélanger au résultat de la sauvegarde
> elle-même. `backup --eject-after` (nouveau drapeau sur `cmd_backup`,
> distinct du `--eject-after` de `cmd_flash` -- best-effort, jamais
> rapporté séparément, §4.6) éjecte la carte source juste après la copie,
> dans ce même worker déjà élevé ; `WorkerRunner.eject_result` (nouveau
> signal Qt) relaie l'événement à `MainWindow._on_wizard_source_eject_
> result`, qui retient simplement le résultat (`_wizard_source_ejected`,
> `_wizard_source_eject_error_msg`) -- reçu *avant* la fin du worker
> (`eject_result` précède toujours `done` dans `cmd_backup`).
> `_start_worker` ajoute ce drapeau uniquement pour `backup`/`backup_
> system` en mode assisté (`self._wizard_active`), jamais en mode expert
> (aucun rapport avec ce parcours). `_run_wizard_source_eject` vérifie
> `_wizard_source_ejected` en tout premier : `True` (cas courant, les deux
> ont réussi ensemble) saute directement au même point d'arrivée que
> l'ancien chemin (`_on_wizard_source_eject_finished`, réutilisé tel quel)
> -- aucune seconde invite UAC ; `False` (l'éjection chaînée a échoué,
> rapportée séparément) ou `None` (signal jamais reçu) retombent sur le
> worker d'éjection dédié existant, exactement comme avant ce chaînage --
> sans jamais avoir à refaire toute la sauvegarde. `_wizard_source_ejected`/
> `_wizard_source_eject_error_msg` sont remis à `None` par `_start_wizard`,
> comme le reste de l'état du parcours.
>
> Portée volontairement limitée à l'éjection de la carte *source* (étape 3)
> -- celle explicitement rapportée « en plus de celle de la sauvegarde ».
> L'éjection de la carte *cible* (étape 5, `_run_wizard_eject`, après
> RESTORE_IMAGE) reste un worker dédié, non chaînée dans le flash : le
> même compromis (canal séparé, jamais fatal) s'y appliquerait tout aussi
> bien, mais n'a pas été demandé ici -- piste future si un jour signalée.
>
> **Effet secondaire possible, non confirmé, sur le chien de garde du
> sondage et la détection de la carte neuve.** Au moment d'écrire cette
> note, un signalement distinct reste ouvert : le chien de garde
> (`_check_wizard_poll_stall`, ci-dessus) continuerait de journaliser en
> boucle, et la carte neuve resterait non détectée sans clic manuel sur
> Rafraîchir, à l'entrée de l'étape 3 -- après le correctif du chien de
> garde lui-même (faux positifs sur les pauses légitimes, déjà corrigés,
> voir plus haut) et malgré lui. Le chaînage ci-dessus retire un worker
> d'éjection dédié entier -- avec sa propre invite d'élévation, son propre
> cycle de vie Qt -- du chemin courant entre la fin de la sauvegarde et le
> démarrage du sondage de la carte neuve, ce qui pourrait éliminer une
> source d'interférence non identifiée jusqu'ici. **Non confirmé** : aucune
> hypothèse concrète ne relie ce chaînage au symptôme rapporté, et aucun
> test ne le démontre -- à réévaluer au prochain test réel une fois ce
> correctif en place, avant de rouvrir une nouvelle investigation dédiée
> si le symptôme persiste malgré tout.

> ⚠️ **Même défaut rapporté après un flash en mode expert, deux minutes
> plus tard.** `flash --eject-after` (§4.6) existe déjà et chaîne
> l'éjection dans le worker de flash lui-même pour tout flash mode expert
> (`_flash_may_trigger_windows_format_prompt`, quasiment toujours vrai) --
> aucune seconde invite dans le cas courant, contrairement à la source
> confusion initiale. Mais ce mécanisme, best-effort, ne rapportait son
> résultat qu'au journal (`emit_log`, jamais un événement structuré) --
> `_on_worker_finished` masquait alors le bouton Éjecter *inconditionnel-
> lement* dès que ce drapeau était posé, en supposant la carte déjà
> éjectée avec succès. Un échec silencieux de cette éjection chaînée
> laissait donc la carte réellement non éjectée, sans bouton visible pour
> réessayer -- l'utilisateur devait deviner qu'il fallait passer par
> l'étape F séparée du mode expert, qui redemande sa propre élévation
> (§3) : exactement l'« invite UAC dédiée, deux minutes plus tard »
> rapportée, le délai correspondant au temps mis à remarquer que la carte
> n'était pas éjectée puis à cliquer sur cette étape séparée.
>
> **Corrigé** en réutilisant le mécanisme déjà construit pour `backup
> --eject-after` (ci-dessus) : `cmd_flash` appelle désormais aussi
> `emit_eject_result(ok, msg)` en plus du `emit_log` existant.
> `WorkerRunner.eject_result` (même signal, déjà partagé) est connecté à
> un nouveau `MainWindow._on_flash_eject_result` quand `_start_worker`
> pose `--eject-after` sur un flash (`self._flash_ejected`, remis à
> `None` à chaque nouveau worker). `_on_worker_finished` ne masque plus le
> bouton Éjecter inconditionnellement : `allow_eject` réapparaît dès que
> `self._flash_ejected is False` (résultat connu et négatif) -- `True` ou
> `None` (succès, ou signal jamais reçu) le laissent masqué comme avant.
> Portée volontairement limitée au flash (le cas rapporté) : `reset-card`
> éjecte aussi automatiquement mais n'a pas de bouton concurrent à
> masquer (§4.3 bis, déjà retiré de `_ALLOW_EJECT_AFTER_MODES`), rien à
> changer là.
>
> **Question posée en plus, non résolue avec certitude : l'invite UAC
> s'affiche-t-elle au premier plan ?** Deux minutes se sont écoulées avant
> l'échec observé -- cohérent avec une invite restée invisible pour
> l'utilisateur jusqu'à un délai d'expiration Windows, plutôt qu'un refus
> explicite et rapide (`ERROR_CANCELLED` immédiat). `ShellExecuteExW`
> recevait `hwnd=None` depuis toujours (`gui/elevate.py::_launch_
> windows`) -- Microsoft documente ce paramètre comme le propriétaire de
> la fenêtre affichée, et le laisser vide prive Windows d'un signal
> normal pour rattacher/mettre en avant l'invite. **Réserve importante,
> qui limite la portée de ce correctif** : l'invite de consentement UAC
> s'affiche elle-même sur le Bureau sécurisé, un mécanisme Windows séparé
> qui prend la main sur tout l'écran indépendamment de `hwnd` -- ce
> paramètre ne peut donc pas expliquer une invite cachée *derrière* une
> autre fenêtre au sens strict. Une explication au moins aussi probable,
> non vérifiable sans du vrai matériel multi-écran : l'invite apparaît sur
> un second écran hors du champ de vision de l'utilisateur au moment où il
> regarde l'application. **Corrigé quand même, en amélioration en
> l'absence de cause confirmée plutôt qu'en correctif garanti** :
> `WorkerRunner._windows_parent_hwnd` (nouveau) transmet le handle natif
> de `MainWindow` (`winId()`, Windows uniquement, `None` si indisponible
> ou hors Windows) à `launch_elevated_worker`/`_launch_windows`, qui le
> pose sur `info.hwnd` -- pratique recommandée par Microsoft pour
> `ShellExecuteEx`, sans inconvénient connu. **Non confirmé sur du vrai
> matériel** : à réévaluer au prochain flash réel si l'invite reste
> invisible malgré ce changement -- pointerait alors vers l'hypothèse
> multi-écran plutôt que vers un défaut de paramétrage de
> `ShellExecuteExW`.

⚠️ **Bug corrigé, confirmé en relisant le code après le rapport
> ci-dessus : le Continuer du vrai parcours guidé pouvait afficher la
> fenêtre Confirmation avec la mauvaise carte, court-circuitant la
> vérification d'empreinte (§5, § pré-vol n°3).** Rapporté comme : image
> système extraite d'une carte de 128 Go, carte cible de 32 Go insérée,
> message de confirmation annonçant pourtant la perte des données de la
> carte de 128 Go. Cause réelle : `_on_wizard_continue`
> (`gui/main_window.py`) vérifie en tout premier `self._prepare_card_
> candidate` (`Optional[Device]`, propre au parcours ponctuel « Préparer
> une carte avec cette sauvegarde », §4.3) pour décider si le clic
> concerne ce parcours ad-hoc plutôt que le vrai parcours guidé --
> mais `_start_wizard()` ne réinitialisait jamais ce champ (ni
> `_assisted_ad_hoc_active`, ni `_prepare_card_poll_timer`) au démarrage
> du vrai parcours. Un passage antérieur par le parcours ad-hoc laissant
> une carte candidate détectée sans retour explicite à l'accueil (les
> deux seuls chemins qui réinitialisaient déjà ce champ, `_cancel_wizard`
> et `_on_assisted_ad_hoc_return_home`) laissait donc `_prepare_card_
> candidate` non `None` pour toute la suite de la session -- y compris
> pendant un vrai parcours de clonage démarré ensuite. Le Continuer de
> l'étape 3 (détection de la carte cible, qui active ce même bouton une
> fois une carte trouvée -- comme l'étape 1) se retrouvait alors détourné
> vers `_proceed_to_flash_confirmation()` avec la carte candidate
> périmée, **sans jamais passer par `_enter_wizard_restore_image_step`**
> -- ni son affectation `self._mode = "flash"`, ni sa vérification de
> taille de destination (`estimate_total_bytes`, § pré-vol n°2) : les
> deux étaient simplement absentes de ce chemin détourné, pas en défaut
> elles-mêmes (vérifié séparément : `estimate_total_bytes` sur un `.img`
> brut renvoie bien `os.path.getsize()` du fichier, jamais une taille de
> périphérique).
>
> **Corrigé à deux niveaux** : `_start_wizard()` réinitialise désormais
> `_prepare_card_candidate`/`_assisted_ad_hoc_active` (et arrête `_prepare_
> card_poll_timer` s'il tournait), symétriquement à ce que `_cancel_wizard`/
> `_on_assisted_ad_hoc_return_home` font déjà en sens inverse -- ces deux
> parcours sont censés être mutuellement exclusifs, démarrer l'un doit
> repartir d'un état propre pour l'autre. En plus, garde-fou en dernier
> recours directement dans `_on_wizard_continue`/`_on_wizard_refresh_
> requested` (`and not self._wizard_active` ajouté à leur condition de
> routage ad-hoc) : même si un futur chemin laissait à nouveau cet état
> incohérent, le Continuer/Actualiser du vrai parcours guidé ne peut plus
> jamais être détourné vers le parcours ponctuel pendant qu'il tourne.
>
> ⚠️ **Bug corrigé au passage : l'échec final s'affichait comme « Une
> erreur est survenue. », message générique inutile pour diagnostiquer
> quoi que ce soit après coup.** Cause : six codes d'erreur réellement
> émis par le worker élevé (`__main__.py::emit_error`) --
> `OUTPUT_EXISTS`, `IMAGE_NOT_FOUND`, `IO_ERROR`, `UNSUPPORTED_OS`,
> `CONFIRMATION_REFUSED`, `INVALID_ARGS` -- n'avaient jamais été ajoutés à
> `gui/strings.py::_ERROR_MESSAGE_KEYS`, retombant systématiquement sur
> `error_generic` au lieu d'un message précis. `IO_ERROR` en particulier
> est le repli générique de la quasi-totalité des commandes CLI pour une
> erreur disque/E-S imprévue (carte débranchée en cours de copie,
> permission refusée...) -- le plus susceptible d'apparaître en usage
> réel de tous les codes qui manquaient, et une explication plausible du
> message générique vu pendant ce même test (le clic détourné ci-dessus
> relance `backup`/`backup_system` sur un fichier de sortie déjà créé par
> l'étape précédente, ce qui échoue côté CLI avec `OUTPUT_EXISTS`).
>
> **Corrigé** en ajoutant ces six codes à `_ERROR_MESSAGE_KEYS`, avec un
> message convivial dédié chacun. En complément, `gui/strings.py::
> error_log_detail(code, msg)` (nouvelle fonction) garantit qu'un futur
> code encore non mappé n'est plus jamais un trou total : quand
> `friendly_error_message` retombe sur `error_generic`, le code brut du
> protocole précède désormais le message dans le détail journalisé (ex.
> `CODE_INCONNU : message brut`) plutôt que de disparaître silencieusement
> -- un code déjà traduit n'a pas besoin de cette répétition, le message
> brut seul suffit comme avant (§5 vocabulaire : le détail brut suit
> toujours le message principal comme ligne supplémentaire du journal).
> Les six points d'appel de `gui/main_window.py` qui construisaient
> `details=self._last_error_msg or ""` en dur passent désormais par cette
> fonction. Un test dédié (`tests/test_gui_strings.py::test_every_cli_
> emitted_error_code_is_mapped_to_a_friendly_message`) relit littéralement
> tous les `emit_error("CODE", ...)` de `__main__.py` et vérifie qu'aucun
> ne retombe sur le message générique -- filet de sécurité pour qu'un
> futur code ajouté côté CLI ne reproduise pas ce même trou en silence.
>
> ⚠️ **Correction de conception (remplace deux notes « phase 8» retirées
> ici).** Les étapes A/B lettrées (extraction BOOT/EASYROMS) n'existaient
> auparavant en mode assisté que comme jobs internes du parcours guidé à
> sept étapes — la « visibilité des archives » (chemin annoncé dès le
> début de la copie, récapitulatif de fin de parcours) et la
> « réutilisation d'une sauvegarde déjà connue » (`AppConfig.
> archive_records`, `screens.py::ArchiveReuseDialog`) documentées ici
> n'étaient pertinentes que pour ce parcours-là. Le parcours de clonage
> qui l'a remplacé (§5) est entièrement basé sur l'image disque brute —
> il n'appelle plus jamais `extract_boot`/`extract_easyroms` et n'a donc
> plus besoin d'aucun des deux mécanismes. `AppConfig.archive_records`/
> `get_archive_record`/`set_archive_record` et `ArchiveReuseDialog` ont
> été retirés en conséquence. Les étapes A/B elles-mêmes, la journalisation
> de leur destination (`_start_worker`, `_EXTRACTION_MODES`) et
> `archives.default_archives_dir()`/`list_archives` restent pleinement en
> place pour le mode expert (§4.6), qui les utilise indépendamment
> — inchangés.

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
> ⚠️ **Correction de conception : l'adaptation « Mode assisté » décrite ici
> a été retirée.** Le parcours guidé à sept étapes détectait le système de
> la carte source (`detect_card_system_for_device`, stocké dans
> `_wizard_source_system`) pour sauter automatiquement l'identification
> DTB et l'extraction BOOT/EASYROMS sur une carte ROCKNIX, ou avertir sur
> un système non reconnu — logique nécessaire uniquement parce que ce
> parcours travaillait au niveau fichier (BOOT/EASYROMS), donc sensible au
> firmware installé. Le parcours de clonage qui l'a remplacé (§5) clone
> l'image disque brute telle quelle, quel que soit le firmware — il n'a
> plus besoin de reconnaître ROCKNIX ni aucun autre système pour décider
> quoi faire. `detect_card_system_for_device` (le point d'entrée
> spécifique à cette adaptation) a été retiré ; `CardSystem`/
> `detect_card_system`/`ROCKNIX_BOOT_LABEL` restent en place, toujours
> utilisés par `detect_workflow_status` pour le mode expert (badges
> `SYSTEM_INCOMPATIBLE`, ci-dessus, inchangé).

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

> **Choix du firmware (phase 8, catalogue élargi en phase 10), étape C du
> mode expert uniquement** — le parcours de clonage du mode assisté n'a
> pas de choix de firmware, il restaure la propre sauvegarde de
> l'utilisateur (§5). L'étape de flash construit ses boutons radio
> dynamiquement depuis un catalogue centralisé,
> `identify/firmware_catalog.py::FIRMWARE_CATALOG` (`FirmwareEntry` : id,
> clés de titre/description, statut, `is_clone_safe`, `releases_url`
> optionnel), plutôt que des branches à trois choix codées en dur
> (`gui/screens.py::FileDialog`) — nécessaire dès qu'on dépasse trois
> entrées, chaque branchement en dur devenant un endroit de plus où un
> nouveau firmware peut être oublié en silence (cas réel trouvé en lisant
> ce code avant l'élargissement : le bouton « Voir les versions
> disponibles » retombait déjà silencieusement sur l'URL ArkOS pour tout
> firmware non reconnu — corrigé au passage, `main_window.py::
> _on_releases_requested` n'ouvre plus rien pour un id absent du
> catalogue). Sept entrées : **ArkOS / dArkOS** (archivé), **ROCKNIX**
> (maintenu), **EmuELEC** (expérimental, consoles clones), **AmberELEC**,
> **MinUI**, **R36Droid** et **andr36oid** (ces quatre derniers
> expérimentaux — voir plus bas). Chaque entrée affiche une pastille de
> statut *maintenu*/*archivé*/*expérimental* (`gui/theme.py`, réutilise
> les couleurs vert/gris-bleu/orange déjà en place pour les pastilles
> d'étape — une seule couleur d'accent, §5). Le choix est mémorisé d'un
> lancement à l'autre (`config.py::AppConfig.firmware`, `_VALID_FIRMWARES`
> dérivé du catalogue plutôt qu'un second ensemble à resynchroniser à la
> main). Défaut : **ROCKNIX** (`DEFAULT_FIRMWARE`), pas ArkOS — un vrai
> changement de comportement pour toute installation qui n'a jamais
> choisi explicitement de firmware, volontaire puisqu'ArkOS est désormais
> archivé (ci-dessous) et ROCKNIX la seule entrée maintenue.
>
> **ArkOS archivé** : le projet officiel est figé en lecture seule
> depuis décembre 2025 ; la version communautaire pour R36S (dArkOS,
> `southoz/dArkOSRE-R36`) reste installable et est celle vers laquelle
> pointe déjà le bouton de téléchargement — reste choisissable, jamais
> retiré du catalogue, seul son statut affiché change.
>
> **Nouvelles entrées (phase 10), toutes en lien manuel comme ArkOS —
> aucune n'a de téléchargement automatique.** Vérifié individuellement
> sur les pages de releases GitHub réelles avant l'ajout (même discipline
> « confirmé » que le reste de ce document) : ni AmberELEC ni EmuELEC
> n'ont d'assets RK3326/R36S attachés à leurs releases officielles
> (AmberELEC : uniquement des images taguées RG351/RG552 ; EmuELEC :
> uniquement des images Amlogic) — ni l'une ni l'autre n'a donc la
> structure « une image par SoC » qui rend le téléchargement automatique
> de ROCKNIX possible (ci-dessous). Conséquence directe : **pas de
> nouveau module de téléchargement automatique pour AmberELEC** malgré
> une hypothèse initiale en sens contraire — corrigée avant
> implémentation plutôt qu'après coup. MinUI : le dépôt officiel
> (`shauninman/MinUI`) ne prend pas en charge la R36S ; le portage actif
> vit dans un fork communautaire (`Turro75/MyMinUI`) — utilisé à la place
> comme URL de releases. R36Droid/andr36oid : deux portages Android
> (LineageOS) indépendants pour R36S/RK3326, communautaires,
> compatibilité non officiellement confirmée par leurs projets
> respectifs — descriptions honnêtes sur cette incertitude plutôt qu'une
> promesse non vérifiée.
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
>   interroge l'API (thread séparé, même principe que les autres runners
>   de ce module) puis `screens.py::RocknixVariantDialog`
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
> **EmuELEC comme entrée du catalogue** (`identify/firmware_catalog.py`,
> `is_clone_safe=True` — seule entrée à porter ce signal) : même
> comportement que les autres entrées en lien manuel (bouton ouvrant
> `identify/releases.py::EMUELEC_R36S_RELEASES_URL` dans le navigateur —
> aucune correspondance d'assets par SoC vérifiée à ce jour pour EmuELEC,
> contrairement à ROCKNIX, donc pas de téléchargement automatique).
> Choisissable à tout moment, indépendamment d'une détection de clone.
>
> ⚠️ **Correction de conception : l'orientation automatique décrite ici à
> l'étape 2 du parcours guidé (bandeau d'avertissement, présélection
> EmuELEC dans `FileDialog`) a été retirée avec le parcours à sept
> étapes** (§5) — le parcours de clonage qui l'a remplacé n'identifie
> plus la console (indépendant du firmware, donc de la question clone/
> standard). `IdentifyResult.is_clone`/`CLONE_DTB_FILENAMES` restent
> pleinement fonctionnels et testés, seule cette consommation GUI a
> disparu — un clone reste détectable via la commande CLI de diagnostic
> `identify` (`__main__.py::cmd_identify`, texte simple, pas le protocole
> JSON Lines), qui affichait déjà ce signal indépendamment de la GUI. Le
> mode expert n'a jamais eu de notion d'identification (pas d'équivalent
> de l'ancienne étape 2) : cette orientation n'existait que dans le
> parcours guidé, elle n'est donc reprise nulle part ailleurs.
>
> ⚠️ **Signalé, corrigé : après un flash Android (R36Droid/andr36oid),
> Windows affiche une boîte « Vous devez formater le disque » par
> partition Android illisible (quatre observées) -- un débutant risque
> d'accepter et de détruire ce qui vient d'être écrit.** Cause : ces
> firmwares utilisent des partitions (boot/system/vendor/userdata...)
> qu'aucun pilote Windows ne sait lire, et Windows propose de les
> formater dès qu'il les découvre -- ce qui arrive dès que `prepared_
> write_target` relâche le disque en fin d'écriture (§4.3,
> `IOCTL_DISK_UPDATE_PROPERTIES`, qui force justement Windows à
> redécouvrir les partitions).
>
> **Corrigé en deux temps, complémentaires plutôt qu'exclusifs (les deux
> options envisagées ont été retenues) :**
> 1. **Éjection automatique**, dans le worker élevé lui-même
>    (`__main__.py::cmd_flash`, nouveau `--eject-after`) -- appelée juste
>    après l'écriture et la vérification, dans le même processus déjà
>    élevé (aucune invite supplémentaire), pour réduire la fenêtre
>    pendant laquelle Windows peut proposer de formater. Best-effort : un
>    échec d'éjection ne remet jamais en cause le flash déjà réussi
>    (seulement journalisé). `gui/main_window.py::_start_worker` l'ajoute
>    à l'argv du flash uniquement quand `_is_flashing_android_firmware()`
>    est vrai (mode expert, jamais le parcours de clonage du mode
>    assisté, qui n'a pas de choix de firmware) ; `_on_worker_finished`
>    masque alors le bouton Éjecter du succès (déjà fait, redondant).
>    **Non garanti de gagner la course contre Windows** (non vérifié sur
>    du vrai matériel, aucune image Android disponible ici) -- l'éjection
>    a lieu dès que possible côté application, mais rien ne garantit
>    qu'elle précède la notification système.
> 2. **Message explicite dans le journal**, systématique, que l'éjection
>    automatique ait réussi ou non -- le vrai filet de sécurité, puisque
>    l'éjection automatique ne protège que la session en cours : la même
>    carte rebranchée plus tard, sur n'importe quelle machine Windows,
>    déclenchera exactement les mêmes propositions de formatage (les
>    partitions restent tout aussi illisibles). Contrairement au reste de
>    l'interface (§5, jamais de jargon), ce message nomme volontairement
>    le vrai texte de la fenêtre Windows (« Vous devez formater le
>    disque… ») -- même principe que `HelpDialog` pour les réglages macOS,
>    §3 : une vraie fenêtre système à laquelle réagir correctement, pas
>    la description d'une action de l'app. `identify/firmware_catalog.py::
>    FirmwareEntry.is_android` (nouveau champ, `True` pour `r36droid`/
>    `andr36oid` seulement) porte ce signal.

> ⚠️ **Signalé, corrigé : le correctif ci-dessus était trop étroit --
> Windows propose aussi de formater la carte après un flash "Linux"
> (ArkOS/ROCKNIX/EmuELEC/AmberELEC/MinUI), pas seulement Android, jusqu'à
> cinq boîtes observées au total selon le firmware.** Cause : ces
> firmwares aussi utilisent au moins une partition (le système ext4
> "root", §4.4) qu'aucun pilote Windows ne sait lire -- une seule boîte
> pour eux contre plusieurs pour Android (boot/system/vendor/userdata...),
> mais le même risque exact : un débutant qui accepte de formater détruit
> la carte qu'il vient de préparer. Aucune entrée du catalogue
> (`identify/firmware_catalog.py::FIRMWARE_CATALOG`) n'est donc à l'abri
> de ce problème -- filtrer sur `is_android` comme le faisait le premier
> correctif laissait tout le reste du catalogue sans aucune protection.
>
> **Corrigé** en généralisant le mécanisme existant plutôt qu'en le
> dupliquant pour "Linux" séparément : `gui/main_window.py::MainWindow.
> _flash_may_trigger_windows_format_prompt` (nouvelle méthode, même
> emplacement et même forme que `_is_flashing_android_firmware`) renvoie
> vrai pour **tout** flash mode expert, quel que soit le firmware --
> puisqu'aucune entrée du catalogue n'est jamais entièrement lisible par
> Windows, pas besoin d'y filtrer par identifiant comme pour Android.
> `_is_flashing_android_firmware` reste utilisée séparément, mais
> uniquement pour choisir *quel message* afficher (détaillé pour Android,
> ci-dessus, générique sinon) -- plus pour décider *si* le mécanisme
> s'applique.
> - `_start_worker` ajoute désormais `--eject-after` dès que `_flash_may_
>   trigger_windows_format_prompt()` est vrai (auparavant : seulement
>   `_is_flashing_android_firmware()`) -- couvre donc aussi ROCKNIX/ArkOS/
>   EmuELEC/AmberELEC/MinUI, en plus de R36Droid/andr36oid.
> - `_on_worker_finished` masque le bouton Éjecter du succès dans les
>   mêmes conditions élargies (`allow_eject = ... and not format_prompt_
>   flash`), et journalise un nouveau message générique,
>   `gui/strings.py::flash_format_prompt_warning_generic` (« Windows va
>   peut-être proposer de formater la carte — refuse, c'est normal. »),
>   pour tout flash non-Android concerné -- le message Android détaillé
>   (mécanisme des écrans de rechange compris, ci-dessous) reste propre à
>   Android, `elif format_prompt_flash` évitant les deux messages à la
>   fois pour un même flash.
>
> Toujours sans effet sur le parcours de clonage du mode assisté
> (`_flash_may_trigger_windows_format_prompt` renvoie faux dès que
> `_wizard_active` est vrai, comme `_is_flashing_android_firmware`) --
> celui-ci éjecte déjà automatiquement la carte neuve à l'étape 5
> (`_run_wizard_eject`), immédiatement après la restauration, quel que
> soit le contenu de l'image clonée : un second mécanisme y ferait double
> emploi. **Non vérifié sur du vrai matériel au moment d'écrire cette
> note** pour le cas "Linux" précisément (le cas Android l'était déjà,
> ci-dessus, avec la même réserve sur la course contre Windows) -- couvert
> par des tests qui vérifient l'argv du worker et le contenu du journal,
> pas une vraie élévation Windows.

> ⚠️ **Constaté en usage réel : une image Android flashée démarre parfois
> sur un écran figé si l'écran choisi ne correspond pas à celui de la
> console -- le mécanisme de rechange existe déjà côté firmware, mais rien
> ne l'indiquait dans l'app avant ce correctif.** Ces portages (R36Droid/
> andr36oid) embarquent un dossier `Panels/` sur le BOOT, un sous-dossier
> par type d'écran, chacun contenant les `.dtb` à copier à la racine du
> BOOT pour changer d'écran -- exactement le même genre de fichier que
> celui déjà lu par `identify/dtb.py` pour reconnaître le modèle de
> console (§4.5), mais ici c'est l'utilisateur qui doit le copier à la
> main, l'app n'automatise rien de ce mécanisme. Sans explication, un
> débutant qui obtient un écran figé au premier démarrage conclut que le
> logiciel ne marche pas, alors que le flash a en réalité réussi -- il
> manque juste le bon écran.
>
> **Corrigé** : un second message, `gui/strings.py::
> flash_android_panel_mismatch_warning`, s'ajoute désormais dans le
> journal juste après l'avertissement sur les boîtes de formatage
> ci-dessus (`_on_worker_finished`, même bloc `if android_flash`) --
> explique le dossier `Panels/` et le fait de copier les `.dtb` à la
> racine du BOOT, précise qu'il faut parfois plusieurs essais, et ne
> promet jamais que ça marchera : **sur la console de test, les trois
> écrans compatibles annoncés pour cette carte
> (`rockchip,rk3326-rg351mp-linux` -- Panel1, Panel2/3, Panel4) ont tous
> échoué**, aucun n'a produit d'affichage. Message volontairement prudent
> en conséquence -- une piste à essayer, jamais une garantie.
>
> **Usage non prévu de `identify --boot-dir`, utile à documenter** : cette
> commande de diagnostic (§4.6, pensée à l'origine pour valider le parseur
> DTB sur des variantes de console) s'est révélée très efficace pour
> trier les `.dtb` d'un dossier `Panels/` extrait -- exécutée sur chacun
> des sept sous-dossiers de panels de cette image R36Droid, elle a écarté
> quatre d'entre eux en identifiant la carte (`board_compatible`) à
> laquelle chaque `.dtb` est réellement destiné (une autre console de la
> même famille RK3326, pas la R36S/R35S) -- ne laissant que les trois
> panels ci-dessus comme candidats plausibles pour cette console, avant
> même de les essayer un par un sur du vrai matériel. Aucun code n'a
> changé pour permettre cet usage : la commande fonctionne déjà sur
> n'importe quel dossier de `.dtb` local, indépendamment de son origine
> (carte réelle ou dossier `Panels/` extrait d'une image).

> **Idée future, pas implémentée** : ROCKNIX fournit un script
> `importpanel.py` qui génère un `mipi-panel.dtbo` à partir d'un `.dtb`
> d'origine (le même type de fichier que celui déjà lu par
> `identify/dtb.py` pour reconnaître le modèle de console, §4.5/§5 étape
> 2). Une fois la console identifiée par notre module `identify`, on
> pourrait imaginer une fonction ultérieure qui invoque `importpanel.py`
> sur le `.dtb` extrait à l'étape A pour produire automatiquement l'overlay
> d'écran ROCKNIX correspondant — mais ceci reste une piste, à explorer
> seulement si l'utilisateur en a besoin.

> ⚠️ **Investigation clôturée, confirmée sur du vrai matériel : ce build
> Android/LineageOS (R36Droid/andr36oid) ne démarre pas sur cette console,
> et ce n'est pas une histoire de panel.** Deuxième round de test complet,
> sur une carte différente de celle du round précédent (ci-dessus, 3
> panels compatibles testés) : cette fois, **les huit variantes distinctes
> de `Panels/` compatibles `rockchip,rk3326-rg351mp-linux` (après
> dédoublonnage par timing exact) ont toutes figé** -- écran noir ou allumé
> puis gelé/frisant selon le candidat, jamais un démarrage complet.
>
> **Isolation de la cause, méthodique :**
> 1. Premier piège rencontré pendant ce round : `identify --boot-dir`
>    identifie toujours le **premier `.dtb` par ordre alphabétique** d'un
>    dossier (§4.5) -- sur cette image, c'est `rg351mp-kernel.dtb`/
>    `rg351v-kernel.dtb`, jamais celui que `boot.ini` charge réellement au
>    boot (`load mmc 1:1 ${fdt_addr_r} rk3326-r36s-android.dtb`, vérifié en
>    lisant `boot.ini` directement). Un premier essai basé sur le mauvais
>    fichier n'a donc rien changé au boot réel -- corrigé en cours de route
>    en parsant directement `rk3326-r36s-android.dtb` de chaque dossier
>    (`identify.dtb.parse_dtb_file`, appelable directement sur un fichier
>    précis, pas seulement via `--boot-dir` sur un dossier entier).
> 2. Une fois sur le bon fichier : son `board_compatible` racine ne
>    correspond **jamais** à `rg351mp`/`r36s` -- systématiquement
>    `odroidgo3`, `g80ca`, ou `type3` selon le dossier. Seul le nœud panel
>    (timings d'écran) semble avoir été retouché par variante ; le
>    compatible racine reste celui de la base clonée par le porteur
>    communautaire. Filtrer sur ce champ pour ce fichier précis n'a donc
>    aucun sens ici (contrairement à l'usage habituel de ce module sur un
>    BOOT ArkOS/ROCKNIX, §4.5) -- seul le dédoublonnage par timing exact et
>    le contrôleur d'écran (`elida,kd35t133` vs `sitronix,st7703` pour un
>    seul candidat) restent des signaux valides.
> 3. **Test décisif** : même après avoir restauré le fichier *d'origine*,
>    jamais modifié, la console fige exactement pareil -- et, câble/port
>    USB confirmés fonctionnels (même câble, même port, ROCKNIX sur la même
>    console reconnue instantanément par le PC juste après), **aucun
>    périphérique n'apparaît côté PC** (`adb devices` vide, aucune entrée
>    même en échec dans le Gestionnaire de périphériques Windows) pendant
>    le freeze -- ni avec l'original, ni avec aucun des huit candidats.
>    Le blocage survient donc **avant l'initialisation USB du noyau**,
>    un point commun à toutes les configurations testées, écran compris ou
>    non -- la preuve que le panel n'est pour rien dans ce freeze.
>
> **Conclusion, non résolue plus loin faute de matériel** : ce build
> Android ne s'initialise pas correctement sur ce clone, indépendamment du
> panel choisi. Voir le point précis où ça bloque demanderait une capture
> UART (`boot.ini` route la console noyau sur `ttyS2, 115200n8` -- la seule
> fenêtre sur ce qui se passe avant l'USB), non disponible lors de cette
> investigation. `adb`/USB ne peuvent structurellement rien montrer ici,
> quel que soit le câble : le point de blocage est en amont de leur
> initialisation.
>
> **Implication pour une future automatisation de sélection de panel**
> (idée envisagée à ce moment, jamais implémentée en conséquence) : un tel
> outil (détection automatique d'un dossier `Panels/` au flash, application
> du candidat suivant sans reflasher) n'aurait rien résolu pour ce cas
> précis -- le problème n'est pas le choix du panel. Reste potentiellement
> utile pour un autre build Android qui, lui, initialiserait correctement
> le matériel mais afficherait sur le mauvais écran -- mais ne plus jamais
> le présenter comme la réponse à un simple freeze sans d'abord vérifier,
> comme ici, que la configuration d'origine ne fige pas elle aussi.

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

> ⚠️ **Bug corrigé, signalé sur du vrai matériel : l'app affichait « 31,9
> Go » pour une carte que l'Explorateur Windows affiche « 29,7 Go » --
> même carte, mêmes octets, deux nombres différents. Un utilisateur qui
> compare les deux pouvait croire à une perte de capacité.**
>
> **Cause, plus profonde qu'un simple désaccord avec Windows** : l'app
> calculait déjà la capacité d'une carte de deux façons différentes en
> interne. `gui/screens.py::_format_size` (octets copiés/archivés, ex.
> « 8,4 Go » pour une sauvegarde système) divise par 1024 à chaque palier
> (o -> Ko -> Mo -> Go) -- base 1024, comme l'Explorateur Windows, qui
> fait de même sous une étiquette tout aussi ambiguë. Mais les quatre
> endroits qui affichent la capacité d'une carte *entière* (bandeau de
> détection, liste de `DeviceDialog`, `ConfirmDialog`/`SameCardUnverified
> Dialog`, plus `cmd_list`/`_confirm_flash` côté CLI) divisaient par
> `1_000_000_000` -- base 1000, jamais 1024. Deux conventions
> différentes au sein de la même app, pas seulement un désaccord avec
> Windows.
>
> **Vérifié plutôt que supposé** (demande explicite) ce qu'affichent les
> deux autres OS pour la même carte -- aucun des trois ne fait consensus :
> - **macOS** (Finder) : base 1000 depuis Snow Leopard (10.6, 2009),
>   étiqueté « Go » correctement -- ce que l'app calculait déjà pour la
>   capacité d'une carte (mais pas pour `_format_size`, toujours en base
>   1024 : la même incohérence interne existait donc aussi entre cette
>   fonction-là et macOS, dans l'autre sens).
> - **Linux** : mélangé selon l'outil. GNOME Fichiers (Nautilus) suit la
>   même convention que macOS (base 1000, « Go » correctement étiqueté) ;
>   les outils historiques en ligne de commande (`df`, `lsblk`) utilisent
>   traditionnellement la base 1024 avec un « G » tout aussi ambigu que
>   celui de Windows. Aucune convention unique ne fait consensus sur
>   Linux non plus -- vérifié en connaissance des deux familles d'outils
>   plutôt que jamais testé sur une vraie installation Linux ici (aucune
>   disponible).
>
> **Corrigé** en alignant toute l'app sur une seule et même base --
> celle déjà utilisée par `_format_size`, jamais changée : `gui/screens.py
> ::_capacity_go` et son équivalent local `__main__.py::_capacity_go`
> (dupliqué plutôt qu'importé de `gui/` -- trop petit pour un module
> partagé, et le CLI ne doit pas dépendre de PySide6, §3) remplacent les
> six calculs en base 1000 par `size_bytes / 1024**3`. Plus jamais deux
> nombres différents pour la même carte selon l'écran consulté au sein de
> cette app -- et l'affichage se rapproche au passage de l'Explorateur
> Windows, la plateforme la plus vérifiée sur du vrai matériel dans ce
> projet, au prix d'un désaccord avec le Finder macOS/Nautilus (une carte
> annoncée « 128 Go » par son fabricant s'affichera ici autour de 119 Go,
> comme dans l'Explorateur, plutôt que 128 Go comme dans Finder) --
> aucune option n'évite complètement l'écart avec un OS ou un autre,
> celle-ci l'élimine au moins en interne, et avec la plateforme la plus
> testée ici.
>
> Volontairement **pas** de double affichage (« 31,9 Go / 29,7 Gio ») :
> envisagé, écarté -- introduirait un terme jamais vu par un néophyte
> (« Gio »/GiB) pour un problème que l'utilisateur ne remarque de toute
> façon que s'il compare activement les deux écrans, contraire à la règle
> §5 (aucun jargon technique dans l'interface). Un seul nombre cohérent
> partout dans l'app est plus simple à comprendre qu'une explication de
> la différence entre deux conventions de calcul.

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

> ✅ **Animations de la console retirées, sur demande explicite** (§5) --
> `ConsoleHalo`, `ConsoleBasePlate`, la propriété `floatOffset` (console),
> le `QParallelAnimationGroup` qui les pilotait et le minuteur de repeint
> à 30 im/s (`_repaint_timer`) ont tous été supprimés, avec le réglage
> « Animations de la console » qui permettait de les désactiver. Motif :
> mesurées à 7-9 % d'un cœur au repos (§5 ci-dessus, backend `offscreen`)
> et de toute façon désactivées systématiquement en usage réel -- un coût
> permanent pour un agrément jamais utilisé. La console (`ConsoleArt`)
> est désormais immobile, de face, à opacité fixe (70 %, inchangée) ;
> `ConsoleStage` n'a donc plus besoin de réserver de marge pour une
> flottaison qui n'existe plus, ni de calculer la position d'un halo/
> socle qui n'existent plus non plus -- son `resizeEvent` s'en trouve
> largement simplifié (centre `ConsoleArt` dans tout son rect, plus de
> passe d'estimation en deux temps).
>
> ⚠️ **Correction de conception, en deux temps : le terminal
> d'activité disque en temps réel de l'écran de la console a été retiré
> à tort, puis rétabli une fois la vraie cause du ralentissement
> identifiée.** Ajouté pour afficher, en direct sur l'écran de
> `console.png`, une ligne par événement de progression réel (offset
> hexadécimal, taille de bloc, débit) -- `ConsoleTerminalOverlay`
> (`gui/screens.py`), alimentée par `MainWindow._on_progress`. Une
> sauvegarde système mesurée à ~85 Mo/s est retombée à ~6-8 Mo/s peu
> après son ajout (7 min -> 20 min) -- confondu avec une régression
> causée par ce terminal. Un premier correctif de repeint (cadencé à
> 33 ms via un `QTimer` dédié plutôt qu'un `self.update()` synchrone à
> chaque événement, police mise en cache) n'a rien changé au débit
> mesuré -- ce qui aurait dû alerter plus tôt que le terminal n'était
> pas en cause, plutôt que de le retirer entièrement dans un second
> temps.
>
> **Cause réelle, trouvée en bissectant par mesure du débit CLI pur
> (sans la moindre interface, donc sans ce terminal, éliminé comme
> variable) :** une carte SD d'origine de la console (non-marque,
> chinoise), pas un défaut logiciel -- voir la mise en garde générale,
> §8. Confirmé sur du vrai matériel : ~88,5 Mo/s en CLI sur la branche
> principale avec une carte SanDisk, sur le même port, la même machine,
> la même commande -- aucune régression de code n'a jamais existé.
> Piste environnementale (disque de destination plein/fragmenté, Avast)
> également écartée avant d'en arriver là : 222 Go libres sur le disque
> externe, débit inchangé Avast désactivé, et le même débit lent observé
> aussi bien sur une carte de 128 Go que sur une de 32 Go pour la carte
> d'origine en cause.
>
> **Rétabli entièrement** : `ConsoleTerminalOverlay`, `ConsoleStage.
> append_line`/`start_activity`/`stop_activity`, `_SCREEN_RECT_FRACTIONS`,
> `_fit_within_aspect_ratio` et `ConsoleArt.source_size` sont de retour
> dans `gui/screens.py`, avec le correctif de repeint cadencé/police mise
> en cache conservé (sans coût, toujours une bonne pratique, mais plus
> présenté comme correctif d'un problème qu'il n'a jamais résolu) ; les
> points d'appel `start_activity`/`stop_activity` et le bloc `append_line`
> de `_on_progress` (`gui/main_window.py`) aussi. `LogPanel` (bas de la
> colonne droite) reste inchangé, le terminal reste un affichage distinct
> et complémentaire, jamais un remplacement.
>
> **Leçon retenue** : ne jamais accuser un changement récent sur la seule
> foi d'une corrélation temporelle avant d'avoir isolé les autres
> variables (matériel, environnement) -- surtout quand un premier
> correctif censé régler la cause suspectée ne change rien au symptôme
> mesuré, ce qui est en soi un signal fort que l'hypothèse est fausse.
>
> **L'image de la console (photo de face, `gui/assets/console.png`) et sa
> découpe restent inchangées** -- le rectangle d'écran calibré pour y
> placer le terminal (`_SCREEN_RECT_FRACTIONS`) redevient utile tel quel.
> Remplacement de l'image (rappel) : photo source fournie par
> l'utilisateur (`IMG_20260906_105401.png`, 2000x4452, vue de face, écran
> rectangulaire, la console n'y occupant qu'environ un tiers de la
> hauteur). Écart constaté en la traitant : le fond n'était pas
> réellement transparent contrairement à ce qui était attendu (vérifié
> directement sur les pixels, `(255, 255, 255, 255)` partout) -- détourée
> par remplissage par propagation (`scipy.ndimage.label`, seules les
> composantes connexes touchant le bord de l'image retirées, pour ne
> jamais créer de trou dans un reflet clair isolé à l'intérieur de la
> console) puis un léger flou du canal alpha pour adoucir le contour ;
> recadrée à la boîte englobante du canal alpha (+5 % de marge) et
> réduite à 900 px de haut (595x900, contre 499x500 avant). `MainView`
> (expert) et `AssistedLandingScreen` (assisté) chargent toujours le même
> fichier via `build_console_stage()`/`asset_paths.asset_path
> ("console.png")` -- aucun changement de code nécessaire pour que
> l'image comme le terminal s'appliquent aux deux. `packaging/*.spec`
> (trois fichiers) référencent déjà `"console.png"` par ce nom exact,
> inchangé.

> ✅ **Fenêtre de console du worker élevé masquée sur Windows** (§1/§3) --
> `ShellExecuteExW` (`gui/elevate.py::_launch_windows`) ouvrait jusqu'ici
> le worker élevé avec `nShow=SW_SHOWNORMAL` : une fenêtre de console
> visible, vide en pratique (`ShellExecuteW` ne fournit aucun tube stdout/
> stderr vers ce processus, §3 -- toute la communication passe déjà par
> `--progress-file`/le journal d'élévation), qui clignotait à chaque
> opération élevée sous les yeux d'un néophyte -- contraire à la règle §1
> (« aucune ligne de commande, jamais, à aucune étape »). `nShow=SW_HIDE`
> désormais. Sans risque identifié : rien ne lit jamais la sortie de cette
> fenêtre, et le mécanisme d'élévation lui-même (verbe `runas`, détection
> d'échec via le fichier de progression/le journal d'élévation) ne dépend
> en rien de sa visibilité.

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
> ⚠️ **Correction de conception majeure : le parcours guidé à sept étapes
> (identification DTB puis extraction/injection BOOT-EASYROMS, propre à
> ArkOS) a été remplacé par un parcours de clonage à cinq étapes, en
> image disque brute.** Le parcours à sept étapes ne fonctionnait que
> pour une carte de structure ArkOS reconnaissable (BOOT/EASYROMS) — une
> carte EmuELEC, ROCKNIX, ou un firmware Android nécessitait déjà des
> contournements dédiés (CardSystem/ROCKNIX ci-dessous, désormais retiré
> de ce module). Le nouveau parcours n'a plus cette limitation : il clone
> la carte source telle quelle (`imaging.backup_device`/
> `imaging.backup_system_only`) puis restaure l'image obtenue
> (`imaging.flash_device`) sur la carte neuve — indépendant du firmware
> installé et du système de fichiers, puisqu'aucune opération ne descend
> au niveau fichier.
>
> **Les cinq étapes** (`gui/wizard_flow.py::WizardJob`, un job par étape
> visible — plus besoin qu'un même écran en recouvre deux comme
> auparavant) :
> 1. **Détecter la carte source** — même sondage automatique
>    qu'auparavant (`list_devices`/`filter_devices` par `QTimer`, 1,5 s),
>    inchangé.
> 2. **Créer l'image** — `screens.py::BackupKindDialog` demande d'abord
>    copie complète ou système seul (sans les jeux) avant d'ouvrir
>    `FileDialog` pour choisir où l'enregistrer :
>    - *Copie complète* (`backup --device`) : la taille annoncée avant
>      même le choix du fichier est `device.size_bytes` — un majorant
>      sûr sans lecture supplémentaire, puisque `backup_device` s'arrête
>      toujours à la fin de la dernière partition utilisée.
>    - *Système seul* (`backup --device --system-only`) : réutilise
>      **tel quel** le pipeline d'estimation à deux niveaux déjà en place
>      pour l'opération ad-hoc équivalente de l'accueil assisté
>      (`_start_system_backup_estimate`/`SystemBackupEstimateRunner`,
>      estimation non élevée d'abord, élevée en repli, §4.3) — aucune
>      duplication.
> 3. **Détecter la carte neuve** — éjecte d'abord la carte source
>    (`_run_wizard_source_eject`, logique inchangée depuis le parcours
>    précédent : la carte source doit rester montée pendant l'étape 2,
>    c'est de là que l'image est lue), puis sonde la nouvelle carte.
> 4. **Restaurer l'image** — flash direct de l'image créée à l'étape 2
>    sur la carte neuve, sans aucun choix de firmware (ce n'est pas une
>    nouvelle image téléchargée, c'est la propre sauvegarde de
>    l'utilisateur) : `FileDialog` n'est même pas ouverte pour cette
>    étape, contrairement au flash du mode expert. Fenêtre Confirmation
>    obligatoire (§2 n°6) avant l'écriture réelle, jamais sautée.
> 5. **Éjecter** — inchangé.
>
> `MainWindow` réutilise tel quel le pipeline `_start_worker`/
> `_on_worker_finished` du mode expert (`WorkerRunner` pour `backup`/
> `flash`, jamais `PartitionJobRunner` — le nouveau parcours n'écrit plus
> jamais sur une partition déjà montée) — le drapeau `_wizard_active`
> décide comme avant si la fin d'opération avance la machine à états ou
> suit le chemin expert existant.
>
> **Trois vérifications obligatoires avant d'écrire quoi que ce soit**
> (demandées explicitement, jamais un échec après une longue copie déjà
> lancée) :
> 1. **Espace disque libre sur l'ordinateur**, avant de créer l'image —
>    `MainWindow._check_free_space_or_warn` (`shutil.disk_usage`, pré-
>    contrôle rapide côté GUI, non élevé) et, en autorité réelle,
>    `__main__.py::cmd_backup` (nouveau code d'erreur
>    `INSUFFICIENT_DISK_SPACE`) — le worker élevé refait la même
>    vérification, seule habilitée à bloquer réellement si l'estimation
>    locale manque.
> 2. **Taille de la carte de destination ≥ taille de l'image**, avant la
>    restauration — une carte plus petite tronque et corrompt la table
>    GPT secondaire (déjà rencontré, §4.3 « point critique table GPT »).
>    `imaging.image_source.estimate_total_bytes` (déjà existante, exacte
>    et non privilégiée pour `.img`/`.img.gz`/`.img.xz`, lue depuis le
>    pied du fichier sans décompression) comparée à `device.size_bytes` —
>    côté GUI (`_enter_wizard_restore_image_step`, nouveau code
>    `DESTINATION_TOO_SMALL`) et côté `__main__.py::cmd_flash`, même
>    principe pré-contrôle/autorité que ci-dessus. `None` (pied
>    tronqué/non standard, cas résiduel) laisse passer plutôt que de
>    bloquer sur une estimation incertaine — `flash_device` échoue alors
>    avec une vraie erreur d'écriture (ENOSPC) plutôt que de tronquer
>    silencieusement.
> 3. **Empreinte de carte, refuse d'écrire sur la carte source** —
>    `safety/card_fingerprint.py::compute_boot_fingerprint`/
>    `is_same_card`, via `WizardFingerprintRunner` aux étapes 1 et 3 (même
>    garde-fou qu'auparavant aux étapes 1/4). Exception délibérée et
>    limitée à « aucune opération au niveau fichier » : c'est un garde-fou
>    de pré-vol, pas une des deux opérations centrales du clonage
>    (création/restauration), et il se dégrade sans risque — une carte
>    neuve vierge ou d'un firmware différent n'a simplement aucune
>    partition BOOT montable, donc pas d'empreinte (`None`), et
>    `is_same_card` ne bloque jamais ce cas (le cas courant : une carte
>    neuve vierge). Il ne bloque que le cas qui compte : la carte source
>    encore branchée par erreur à l'étape 3.
>
>    ⚠️ **Bug corrigé, confirmé sur du vrai matériel : ce garde-fou peut se
>    désactiver silencieusement, pas seulement se dégrader sans risque.**
>    Le raisonnement ci-dessus suppose que c'est toujours la carte
>    *cible* qui manque d'empreinte -- faux depuis que le parcours de
>    clonage clone n'importe quel firmware (§5) : si la carte *source*
>    elle-même n'a pas d'empreinte (vierge, ou dont le BOOT n'est
>    simplement pas reconnu), `is_same_card` ne peut plus rien affirmer et
>    retourne toujours `False`, quelle que soit la carte réellement
>    branchée à l'étape 3 -- le garde-fou est alors désactivé pour tout le
>    reste du parcours. Combiné à une observation Windows sur du vrai
>    matériel (certains lecteurs de carte gardent le même chemin de disque
>    physique quelle que soit la carte insérée, la sauvegarde et le flash
>    du même parcours utilisant tous deux le même chemin), le chemin seul
>    ne peut pas non plus prouver qu'il s'agit de deux cartes différentes
>    dans ce cas précis -- risque réel d'écrire l'image par-dessus la
>    carte source elle-même si l'utilisateur ne l'a pas changée.
>
>    **Premier correctif tenté (`is_same_card_or_unverifiable`, repli sur
>    `device.path`), non fonctionnel en pratique -- retiré.** Confirmé sur
>    du vrai matériel après coup : le lecteur de carte SD Realtek intégré
>    utilisé pour tester ce parcours (déjà rencontré ailleurs dans ce
>    projet, §4.1/§4.4) garde le *même* `\\.\PhysicalDrive1` quelle que
>    soit la carte insérée -- la sauvegarde (carte source 128 Go) et le
>    flash (carte cible 32 Go) apparaissaient donc sous le même chemin
>    dans les traces d'élévation, alors qu'il s'agit bien de deux cartes
>    physiques différentes. Un repli qui bloque sur un chemin identique
>    bloquait donc *indéfiniment* sur ce type de lecteur, sans aucune
>    issue -- pire que le problème d'origine (un garde-fou inutilisable
>    plutôt qu'un garde-fou dégradé). Restait aussi le trou signalé
>    séparément : deux cartes de même capacité (cas courant en préparant
>    plusieurs consoles) ont le même `size_bytes`, un signal tout aussi
>    inutilisable seul.
>
>    **Corrigé pour de bon** : `safety/card_fingerprint.py::
>    size_proves_different_card` (remplace `is_same_card_or_unverifiable`,
>    `is_same_card` elle-même toujours inchangée) n'affirme une carte
>    différente que si les deux tailles sont connues et *diffèrent* -- une
>    carte ne change jamais de capacité, c'est une preuve positive fiable
>    contrairement au chemin. Une taille identique, comme une empreinte
>    manquante, ne prouve jamais rien dans un sens ou dans l'autre. Quand
>    ni le contenu ni la taille ne peuvent trancher,
>    `gui/screens.py::SameCardUnverifiedDialog` (nouvelle fenêtre modale,
>    même famille que `ConfirmDialog` -- case à cocher obligatoire, fond
>    "danger") exige une confirmation *explicite* de l'utilisateur plutôt
>    qu'un signal automatique supplémentaire ou un blocage sans issue :
>    récapitule le modèle et la taille détectés, jamais pré-cochée.
>    `gui/main_window.py::_on_wizard_fingerprint_ready` l'ouvre (et arrête
>    le sondage automatique, comme pour plusieurs candidats détectés) dès
>    que `fingerprint is None` et qu'aucune différence de taille n'est
>    prouvée ; `_on_same_card_unverified_confirmed` accepte alors la carte
>    en attente (`_pending_target_candidate`) exactement comme si un
>    signal automatique avait tranché. Annuler la fenêtre laisse le
>    sondage arrêté (même convention que `DeviceDialog` sur plusieurs
>    candidats, §5 mode assisté) -- le bouton Actualiser de l'étape 3 le
>    relance. C'est délibérément le garde-fou le plus critique du
>    parcours : écrire par erreur sur la carte source détruirait la seule
>    copie fonctionnelle de la console de l'utilisateur.
>
> **Ce qui est sorti du mode assisté, déplacement pas suppression** —
> reste pleinement en place pour le mode expert, qui l'utilisait déjà
> indépendamment du parcours guidé :
> - **Identification DTB** (`identify.identify_from_boot_directory`,
>   `WizardIdentifyRunner` retiré) : plus aucune étape du parcours de
>   clonage n'en a besoin (indépendant du firmware). Reste accessible en
>   diagnostic CLI (`python -m r36s_studio identify --boot-dir DIR`),
>   inchangé — aucune UI ne l'expose plus nulle part ailleurs.
> - **Extraction/injection BOOT-EASYROMS** (étapes A/B/D/E) : toujours
>   utilisées par le mode expert (§4.6), qui les appelait déjà de façon
>   indépendante du parcours guidé — rien n'y change.
> - **`CardSystem`/ROCKNIX** (§4.5) : `detect_card_system_for_device`
>   (le point d'entrée spécifique à l'ancienne adaptation du parcours
>   guidé) retiré ; `CardSystem`/`detect_card_system`/`ROCKNIX_BOOT_LABEL`
>   restent, toujours utilisés par `detect_workflow_status` pour les
>   badges `SYSTEM_INCOMPATIBLE` du mode expert.
> - **Choix du firmware au flash** (ArkOS/ROCKNIX/EmuELEC, bouton
>   « Voir les versions disponibles », préselection console clone) :
>   n'a plus de sens dans le parcours de clonage, qui restaure la propre
>   sauvegarde de l'utilisateur, jamais une nouvelle image téléchargée.
>   Reste la façon de choisir un firmware à flasher en mode expert
>   uniquement (`FileDialog`).
>
> **Erreur, à n'importe quelle étape** : le parcours s'arrête,
> `LogPanel.finish_error` affiche le message clair (§5, vocabulaire),
> `WizardStepPanel.show_error()` remplace le bouton Continuer par
> Reprendre/Mode expert — inchangé.

> ⚠️ **Signalement non reproduit en isolation : le sondage automatique de
> l'étape 1/4 semblerait parfois s'arrêter tout seul après un retour à
> l'accueil suivi d'une relance.** Rapporté ainsi : lancement du parcours,
> détection de la carte source réussie, arrivée au choix « avec ou sans
> les jeux » (`BackupKindDialog`), retour à l'accueil (bouton Annuler de
> cette fenêtre), relance (« Préparer ma carte automatiquement ») — le
> journal affiche alors « 0 carte(s) retenue(s) » et reste sur ce statut
> jusqu'à un clic manuel sur Rafraîchir, qui retrouve aussitôt la carte
> (toujours branchée, jamais débranchée entre-temps). Signalé comme
> potentiellement « même famille » que le bug d'état périmé
> `_prepare_card_candidate` corrigé plus haut (§4.3/§5, un signal ou un
> drapeau d'un passage précédent contaminant le suivant).
>
> **Relu et rejoué sans trouver de défaut dans ce chemin précis.**
> `_start_wizard` (appelé par « Préparer ma carte automatiquement »)
> réinitialise sans exception tout l'état du parcours --
> `_wizard_flow.reset()`, `_wizard_source_device`/`_wizard_target_device`/
> `_wizard_backup_kind`/`_wizard_estimated_backup_bytes`,
> `_wizard_last_poll_diagnostic`, `_pending_target_candidate`, et l'état ad
> hoc `_prepare_card_candidate`/`_assisted_ad_hoc_active` -- avant
> d'appeler inconditionnellement `_enter_wizard_job(DETECT_SOURCE)`, qui
> démarre `_wizard_poll_timer` sans condition. `_cancel_wizard` (câblé au
> bouton Annuler de `BackupKindDialog`, `cancelled.connect(self.
> _cancel_wizard)`) arrête proprement ce même minuteur et bascule vers
> l'accueil assisté, sans rien laisser d'incohérent pour la relance
> suivante. Un test dédié
> (`tests/test_gui_main_window.py::
> test_wizard_relaunch_after_cancelling_backup_kind_dialog_restarts_poll_and_immediately_redetects_the_device`)
> rejoue exactement cette séquence (détection, Continuer, annulation
> depuis `BackupKindDialog`, relance, sondage) et retrouve la carte dès le
> premier sondage suivant la relance, sans clic sur Rafraîchir -- ce
> chemin précis fonctionne correctement dans ce test.
>
> L'hypothèse initiale du `WizardFingerprintRunner` resté en vol (un
> ancien calcul d'empreinte, lancé sur un thread séparé, qui livrerait son
> résultat après coup et arrêterait à tort le minuteur relancé) a été
> écartée : pour atteindre `BackupKindDialog`, l'empreinte de l'étape
> DETECT_SOURCE doit déjà avoir abouti (Continuer n'est activé qu'une fois
> `_on_wizard_fingerprint_ready` reçu) -- aucun calcul n'est donc encore en
> vol au moment de l'annulation dans ce scénario précis. Un démontage
> résiduel du BOOT par `compute_boot_fingerprint` a aussi été écarté :
> `unmount_forced` est un no-op pour un montage Windows normal (déjà
> documenté ailleurs dans ce fichier).
>
> **Note secondaire du signalement, probablement pas un bug distinct** :
> les lignes de périphériques écartés identiques à deux horodatages
> espacés de plusieurs minutes ne trahissent pas nécessairement un défaut
> du dédoublonnage (`_log_wizard_detection_diagnostic`, qui compare une
> signature `(accepted_count, rejected_lines)` au dernier sondage) --
> `_wizard_last_poll_diagnostic` est remis à `None` par `_start_wizard` à
> chaque relance, donc deux relances distinctes reproduisent légitimement
> une fois chacune le même contenu, sans que le dédoublonnage ait failli
> au sein d'une même relance.
>
> **Diagnostic ajouté en attendant, pas encore un correctif** (le vrai
> mécanisme reste à confirmer sur du vrai matériel, puisqu'il ne se
> reproduit pas ici) : `MainWindow._check_wizard_poll_stall`, appelée en
> tout premier dans `_on_wizard_poll`, retient l'horodatage
> (`time.monotonic`) de chaque sondage réellement exécuté
> (`_wizard_last_poll_monotonic`, remis à `None` par `_start_wizard` comme
> le reste de cet état) et journalise un avertissement explicite si l'écart
> avec le sondage précédent dépasse largement l'intervalle normal de 1,5 s
> (seuil `_WIZARD_POLL_STALL_THRESHOLD_SECONDS`, 6 s -- large marge pour ne
> jamais confondre une latence normale de l'OS avec un arrêt réel du
> minuteur). Si cette ligne apparaît au prochain test réel juste avant le
> « 0 carte(s) retenue(s) » qui a motivé ce signalement, le minuteur
> s'arrête bien réellement de sonner (à chercher alors du côté d'un
> comportement Qt propre au vrai matériel, non reproductible hors écran) ;
> si elle n'apparaît jamais alors que le blocage se reproduit, le minuteur
> tourne mais `list_devices()`/`filter_devices()` retourne réellement zéro
> carte pendant cette fenêtre -- pointant plutôt vers une latence
> d'énumération disque côté OS après le montage/démontage du BOOT pour
> l'empreinte (§4.4), à traiter alors par une retenue/un nouvel essai côté
> `devices/windows.py`, pas ici.

> ⚠️ **Bug corrigé dans le diagnostic lui-même, confirmé sur du vrai
> matériel : le chien de garde ci-dessus se déclenchait en boucle et
> noyait le journal, deux faux positifs distincts.** Journal réel après
> une sauvegarde complète : une première ligne signalant un arrêt de
> 615 s juste après la reprise du sondage à l'étape 3 (« légitimement en
> pause pendant les 10 min de sauvegarde, c'est le comportement voulu »),
> puis la même ligne répétée toutes les 6 à 12 s, indéfiniment, tant que
> la carte neuve n'était pas encore branchée.
>
> **Cause** : `_check_wizard_poll_stall` comparait chaque sondage réel au
> tout dernier, sans distinguer un arrêt anormal d'une pause *voulue* du
> minuteur -- or `_wizard_poll_timer` s'arrête légitimement à plusieurs
> endroits déjà documentés dans ce fichier : pendant toute l'étape
> CREATE_IMAGE (une sauvegarde de plusieurs minutes, aucun sondage
> n'ayant de sens pendant ce temps), et à *chaque* cycle « même carte que
> la source, on continue d'attendre » de l'étape DETECT_TARGET
> (`_on_wizard_fingerprint_ready`), où le minuteur est arrêté le temps de
> calculer l'empreinte (montage/démontage du BOOT, plusieurs secondes)
> puis relancé -- rien de tel qu'un arrêt réel du sondage, juste son
> fonctionnement normal en boucle tant que l'utilisateur n'a pas encore
> échangé les cartes. Comparer le premier sondage suivant chacune de ces
> pauses à celui d'*avant* la pause produisait à chaque fois un écart
> artificiellement énorme.
>
> **Corrigé** : `MainWindow._start_wizard_poll_timer` (nouveau point de
> passage unique pour redémarrer `_wizard_poll_timer`, remplace les
> quatre appels directs à `.start()` du fichier) réinitialise
> `_wizard_last_poll_monotonic` au moment précis de chaque redémarrage --
> plus seulement dans `_start_wizard` comme avant. Une pause volontaire,
> quelle que soit sa durée, ne compte donc plus jamais comme un arrêt
> anormal : seul un écart entre deux sondages *au sein d'une même
> période d'activité continue* du minuteur peut désormais dépasser le
> seuil. Deux tests dédiés (`tests/test_gui_main_window.py::
> test_wizard_poll_stall_diagnostic_does_not_fire_after_a_legitimate_
> pause_for_backup` et `..._does_not_fire_across_repeated_same_card_
> fingerprint_checks`) rejouent chacun des deux scénarios rapportés et
> confirment qu'aucune ligne n'est journalisée dans ces deux cas -- tout
> en gardant `test_wizard_poll_logs_a_stall_when_gap_far_exceeds_the_
> normal_interval` pour vérifier qu'un vrai arrêt (au sein d'une même
> période d'activité) est toujours signalé.
>
> Le mécanisme et le seuil (6 s) eux-mêmes restent inchangés -- c'est
> uniquement le calcul de la référence qui était en cause, pas la logique
> de comparaison. La question d'origine (le sondage automatique reste-t-il
> réellement bloqué après un retour à l'accueil puis une relance, cas non
> reproduit en isolation, ci-dessus) reste donc tout aussi ouverte
> qu'avant -- ce correctif rend seulement le diagnostic utilisable pour y
> répondre, en éliminant le bruit qui aurait masqué un vrai signal.

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

> ✅ **CI en place (phase 7)**, le point ci-dessus étant désormais tranché
> (blocage TCC résolu et confirmé sur du vrai matériel, §3). `packaging/
> r36s_studio_windows.spec`/`r36s_studio_linux.spec` reprennent le même
> squelette que le spec macOS (mêmes `datas` : horodatage de construction,
> illustrations optionnelles) mais sans les éléments propres au bundle
> macOS (`BUNDLE`, `Info.plist`, identifiant de paquet) — inutiles ici,
> l'élévation Windows (UAC/`ShellExecuteW`) et Linux (`pkexec`/`sudo`)
> relance directement le binaire lui-même (`sys.executable`, §3) sans
> identité de paquet à obtenir au préalable, contrairement à macOS.
> `packaging/build_windows.ps1`/`build_linux.sh` sont les scripts de
> construction correspondants, symétriques de `build_macos.sh`.
>
> `.github/workflows/build.yml` : trois jobs (`windows`, `macos`, `linux`)
> lancent `python -m pytest` puis construisent et empaquettent leur
> binaire (`.zip` Windows/macOS via `Compress-Archive`/`ditto`, `.tar.gz`
> Linux) sur **chaque push sur `main` et chaque pull request** — pas
> seulement au moment de taguer une version, pour détecter une régression
> ou une construction cassée avant qu'elle n'atteigne un tag. Un quatrième
> job (`release`) ne se déclenche que sur un tag `v*` et seulement si les
> trois autres ont réussi (`needs:`), télécharge les trois artefacts et
> publie une Release GitHub (`softprops/action-gh-release`). Procédure de
> publication documentée dans `README.md`.
>
> **Linux, dépendances Qt système** : un runner `ubuntu-22.04` nu ne
> fournit pas les bibliothèques partagées dont PySide6/Qt a besoin même en
> mode `offscreen` (celui qu'utilise la suite de tests, `tests/
> conftest.py`) — sans elles, l'import de PySide6 échoue dès le premier
> test GUI avec une erreur de bibliothèque manquante, pas une erreur Qt
> explicite. Le job `linux` installe donc un jeu de paquets `apt`
> (`libegl1`, `libxkbcommon0`, `libxcb-cursor0`...) avant `pip install`,
> non vérifié sur un vrai runner GitHub au moment d'écrire cette note
> (liste dérivée des dépendances Qt6/PySide6 headless documentées par la
> communauté, pas d'accès à un runner Linux pour confirmer en conditions
> réelles ici) — à corriger au premier échec CI si la liste s'avère
> incomplète.
>
> ⚠️ **Bug corrigé, confirmé sur les vrais runners GitHub Actions : Linux
> et macOS échouaient tous les deux (Windows passait), en 51 s et 41 s
> respectivement -- des échecs trop rapides pour être liés aux paquets
> `apt` ci-dessus (déjà installés à ce stade).** Logs des deux jobs
> récupérés via l'API GitHub (`gh` non installé sur cette machine --
> `curl` avec un token pris via `git credential fill`, le même que celui
> déjà utilisé par `git push`) : même échec, mot pour mot, sur les deux
> OS -- `tests/test_partitions_eject.py::test_windows_eject_media_
> failure_propagates`, `AttributeError: module 'ctypes' has no attribute
> 'WinDLL'`.
>
> **Cause** : ce test simule un échec Windows (`platform.system` mocké à
> `"Windows"`, `winlock.eject_media` levant `OSError`) pour vérifier que
> `_windows_eject` (`partitions/eject.py`) laisse bien remonter
> l'exception plutôt que de l'avaler. Mais `_windows_eject` appelle
> `winlock.unlock_volumes(handles)` dans un `finally` -- exécuté même
> quand `eject_media` a levé -- et ce test-là, contrairement à ses deux
> voisins immédiats (`test_windows_dismounts_volumes_then_ejects_media`,
> `test_windows_ejects_without_dismounting_when_no_drive_letters`, tous
> deux corrects), ne mockait pas `winlock.unlock_volumes`. Sur la vraie
> `unlock_volumes` (`imaging/winlock.py`), même avec `handles=[]`,
> `_kernel32()` est appelé *avant* la boucle sur les handles -- et
> `ctypes.WinDLL` n'existe que sur un vrai interpréteur Windows,
> inexistant sur Ubuntu/macOS (`AttributeError` immédiate). Ce test n'a
> donc jamais pu tourner ailleurs que sur un poste Windows avant l'ajout
> de la CI multi-OS -- oubli d'un mock lors de son écriture, pas un défaut
> du comportement Windows lui-même (déjà validé sur du vrai matériel,
> §4.4/§4.5, inchangé par ce correctif).
>
> **Corrigé** : `@patch("r36s_studio.imaging.winlock.unlock_volumes")`
> ajouté à ce seul test (`tests/test_partitions_eject.py`), exactement
> comme ses deux voisins -- aucun code de production touché. Assertion
> `mock_unlock.assert_called_once_with([])` ajoutée au passage, pour
> couvrir explicitement que le `finally` s'exécute bien même après une
> exception, pas seulement que l'exception remonte.
>
> **Linux, `.tar.gz` plutôt qu'AppImage** : le brief (§6 ci-dessous)
> évoque un AppImage pour Linux, mais un AppImage complet demande au
> minimum une icône dédiée et un fichier `.desktop` — ni l'un ni l'autre
> n'existe encore dans ce dépôt (`icon=None` aussi côté macOS/Windows). Un
> simple dossier PyInstaller onedir compressé en `.tar.gz` couvre le besoin
> immédiat (un artefact téléchargeable et exécutable par OS) sans
> introduire un outil de packaging supplémentaire non vérifiable ici. Idée
> future, pas implémentée : un vrai AppImage une fois une icône disponible.

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

- ⚠️ **Toujours vérifier la carte SD avant de suspecter le code, en cas de
  débit anormalement bas.** Confirmé sur du vrai matériel : une carte
  d'origine de console (chinoise, non-marque) peut plafonner à ~6 Mo/s en
  lecture, contre ~88 Mo/s pour une carte SanDisk sur le même port, la
  même machine — une sauvegarde qui prend normalement ~7 min peut alors en
  prendre ~20, sans le moindre défaut logiciel en cause. Un investigation
  entière a été menée à tort sur cette base (voir §5, « le terminal
  d'activité disque en temps réel de l'écran de la console ») avant de
  confirmer, en comparant le débit CLI pur d'une carte suspecte à celui
  d'une carte SanDisk sur la même machine, qu'aucune régression de code
  n'existait. **Signe révélateur** : la capacité exposée par l'OS très
  inférieure à la capacité annoncée sur la carte (ex. 104,8 Go exposés
  pour une carte marquée 128 Go) — un indice classique de carte à capacité
  falsifiée (la carte ment sur sa taille réelle, et est presque toujours
  aussi nettement plus lente que l'annoncée). Avant de bissecter des
  commits ou de soupçonner `imaging/copy.py`, comparer le débit obtenu
  avec une carte connue bonne (SanDisk ou équivalent) sur le même port et
  la même machine.
- **Banc de test Linux CLI disponible : l'Eee PC i686 (§6, déjà utilisé pour
  la limite de compilation croisée) tourne antiX** — pas de GUI possible
  (PySide6 n'a pas de roue pour i686), mais le worker élevé (`backup`/
  `flash`/`eject`) est un simple CLI Python, testable directement sans
  passer par la GUI ni par `gui/elevate.py` : invoquer `python -m
  r36s_studio eject --device <chemin>` (ou `flash`) directement dans un
  terminal déjà élevé (`sudo`) exerce exactement le même code que le
  worker lancé par la GUI (`cmd_eject`/`cmd_flash`, `__main__.py`).
  `pkexec` n'est pas installé sur cette machine — `gui/elevate.py::
  _launch_linux` bascule déjà sur `sudo` quand `shutil.which("pkexec")` ne
  trouve rien, mais ce repli n'est pertinent que pour une future machine
  Linux *avec* GUI ; sur l'Eee PC lui-même (pas de GUI du tout), c'est
  l'utilisateur qui invoque directement `sudo python -m r36s_studio ...`
  dans son propre terminal, sans passer par ce module. Utile en priorité
  pour combler les zones jamais testées sur Linux identifiées ailleurs
  dans ce document (éjection `udisksctl`, §4.4 ; création automatique de
  la partition de jeux `mkfs.exfat`/`mkfs.vfat`, §4.3) — vérifier d'abord
  que `udisksctl`/`mkfs.exfat` sont bien installés sur cette machine avant
  de conclure quoi que ce soit d'un échec.
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
