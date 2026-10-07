# `partitions/` — accès aux fichiers de la SD

À lire quand tu touches à `partitions/` (localisation/montage des partitions, copie de fichiers, archives, éjection) ou à `safety/card_fingerprint.py::compute_boot_fingerprint`.

> Les renvois « §N » de ce texte désignent les sections de l'ancien `CLAUDE.md` monolithique (commit `930f3c9`) : §3 → `elevation-macos.md`, §4.1/§4.2 → `devices-safety.md`, §4.3 → `imaging.md`/`reset-card.md`, §4.4 → `partitions.md`, §4.5 → `detect.md`, §4.6 → `firmwares-flash.md`, §5 → `interface.md`/`assisted-wizard.md`, §6 → `packaging.md`, §8 → `testing.md` ; §1/§2/§9 restent dans `CLAUDE.md`.

> 📚 Historique détaillé (bugs corrigés, investigations) : `docs/bugs-devices-partitions.md`

Après flash, la carte R36S expose trois partitions : `BOOT`, `root`, `EASYROMS`.
`BOOT` est en FAT — montable et inscriptible nativement par les trois OS.
`root` est en ext4 et n'est pas nécessaire aux fonctions prévues.

⚠️ **Confirmé sur du vrai matériel** : `EASYROMS` est en **NTFS**, pas en FAT32
comme le supposait le brief initial. Windows et Linux y écrivent nativement.
**macOS ne peut pas y écrire** : son pilote NTFS intégré ne monte les volumes
NTFS qu'en lecture seule (pas de rapport avec la limitation TCC du §3 — un
pilote NTFS en écriture tiers, ex. Tuxera/Paragon, contournerait celle-ci). Le
module `partitions/` doit détecter ce cas précis (OS macOS + partition NTFS
détectée) *avant* toute tentative d'écriture, et afficher un message explicite
plutôt que de laisser la copie échouer avec une erreur obscure (règle §1 :
jamais de terminal, jamais de jargon pour l'utilisateur final).

**Détection NTFS sur macOS** : `_macos_filesystem` normalise toute variante contenant `ntfs` (`FilesystemType` et `Content`, insensible à la casse, ex. `Windows_NTFS`) vers `"ntfs"` ; `partitions/copy.py` vérifie en plus l'inscriptibilité réelle du point de montage (fichier sonde) avant toute copie, quel que soit l'OS. Récit du bug (`[Errno 30] Read-only file system`) dans `docs/bugs-devices-partitions.md`.

⚠️ **Confirmé sur du vrai matériel : `EASYROMS` peut aussi être en exFAT,
pas seulement en NTFS.** Rapporté sur une carte R36S branchée à un
ThinkPad Windows : `Get-Volume` y montre bien l'étiquette `EASYROMS`,
mais son `FileSystem` vaut `exFAT`, pas `NTFS` — le système de fichiers
d'EASYROMS varie donc selon le vendeur de la carte, comme `BOOT` (§4.4
ci-dessus, FAT16 ou FAT32 selon les cartes). Traiter ce champ comme un
critère d'exclusion plutôt qu'une simple info cassait deux chemins qui le
comparaient à un ensemble figé de systèmes de fichiers plausibles :
1. `imaging/system_backup.py::GAMES_PARTITION_FALLBACK_FILESYSTEMS`
   (sauvegarde « système sans les jeux », §4.3) et `partitions/
   locate.py::EASYROMS_FALLBACK_FILESYSTEMS` (repli sans étiquette,
   ci-dessus) ne listaient que FAT/NTFS — une carte dont EASYROMS
   retombe sur ce repli (étiquette absente ou non lue) et se trouve en
   exFAT y échouait avec `GamesPartitionNotFound`/`PartitionNotFound`.
   Les deux ensembles incluent désormais `"exfat"`.
2. `detect/__init__.py::detect_workflow_status` marquait `copy_games`
   `StepStatus.PLATFORM_LIMITED` sur macOS *inconditionnellement* (badge
   « PC ou Linux »), en supposant EASYROMS toujours en NTFS — alors que
   macOS écrit l'exFAT nativement, contrairement au NTFS (pilote intégré
   en lecture seule). Corrigé : `selected_easyroms_partition` (nouvelle
   fonction publique de `locate.py`, réutilise `_select_easyroms` sans
   dupliquer sa logique d'identification) donne le système de fichiers
   réel d'EASYROMS sur la carte *actuellement* branchée ; la limitation
   n'est levée que si celui-ci est *positivement* confirmé différent de
   NTFS — par défaut (aucune carte, ou EASYROMS non identifiable sur
   celle-ci), le badge reste affiché comme avant, pour garder
   l'avertissement précoce même sans carte insérée.

Ni `jobs.py::_reject_macos_ntfs_write` (compare l'exact `== "ntfs"`) ni
`_macos_filesystem` (normalise vers `"ntfs"` ou tombe sur la valeur brute
du système, `"exfat"` déjà telle quelle chez `diskutil`) n'avaient besoin
de changer : une EASYROMS exFAT sur macOS n'a jamais déclenché
`MacosNtfsWriteUnsupported` à tort, seul le badge informatif était trop
pessimiste.

⚠️ **Confirmé sur du vrai matériel** : sur une vraie carte ArkOS R36S, la
partition `BOOT` (la première du disque) **n'a aucune étiquette** — `diskutil`
l'affiche « NO NAME », type DOS_FAT_16, ~117,4 Mo. L'identifier par étiquette
seule est fragile (variable selon les versions d'ArkOS et les vendeurs) et
ratait systématiquement cette partition. `BOOT` est donc identifiée par sa
**position** (première partition du disque) et son **système de fichiers**
(FAT16 ou FAT32) ; l'étiquette « BOOT », quand elle existe, ne sert que de
repli. `EASYROMS` étant bien nommée en pratique, elle reste identifiée par
étiquette en priorité, avec un repli sur la position (troisième partition,
NTFS ou FAT32) si l'étiquette est absente.

⚠️ **Confirmé sur du vrai matériel** : sur certaines cartes R36S d'origine,
la partition de démarrage est dans un schéma **GPT** dont la première
partition est de **type EFI** (System Partition), avec malgré tout un
**FAT16 tout à fait valide** à l'intérieur — `Image`, `uInitrd`,
`extlinux/`, les `.bmp` de batterie et les `.dtb` (relevé exact :
`disk2s1` type EFI « NO NAME » 536,9 Mo FAT16, puis `disk2s2` Linux, puis
`disk2s3` Microsoft Basic Data « EASYROMS »). **macOS refuse de monter
cette partition automatiquement à cause de ce type** — `diskutil mount`
échoue — et son sondage de système de fichiers pour ce cas précis n'est
pas toujours fiable non plus (`_macos_filesystem` peut renvoyer une
chaîne vide, contrairement au cas NTFS ci-dessus où `FilesystemType` finit
toujours par contenir une variante exploitable). Un montage forcé, lui,
fonctionne : `sudo mount -t msdos /dev/diskNs1 /Volumes/POINT` donne accès
à tous les fichiers, .dtb compris.

**Corrigé en deux temps**, tous deux dans `locate.py` :
1. `PartitionInfo` porte désormais un champ `partition_type` (type de
   partition GPT/MBR, ex. `"efi"` — distinct du système de fichiers),
   renseigné sur macOS depuis `Content` (`_macos_partition_type`).
   `_select_boot` accepte la première partition dès que ce type vaut EFI
   et que le système de fichiers, quand il est connu, n'est pas
   explicitement autre chose qu'un FAT (`_looks_like_efi_boot`) — couvre
   aussi bien le cas où `_macos_filesystem` échoue à identifier le FAT
   (chaîne vide) que le cas où il y parvient malgré tout.
2. `_mount_macos` retente, quand `diskutil mount` échoue, un montage
   forcé (`_force_mount_macos` : `mount -t msdos` sur un point de montage
   temporaire, `tempfile.mkdtemp`) — seulement si le système de fichiers,
   quand il est connu, est un FAT (jamais pour une NTFS/ext4 dont l'échec
   aurait une autre cause). `unmount_forced` démonte proprement ce
   montage temporaire et supprime son dossier une fois la partition
   exploitée — ne fait rien pour un montage `diskutil`/`udisksctl`
   normal, qui reste géré par le système jusqu'à l'éjection finale comme
   avant ce correctif. Appelé après chaque usage : `extract_boot`,
   `extract_easyroms`, `inject_boot`, `copy_games` (`jobs.py`) et le
   calcul d'empreinte des étapes 1/3 du parcours de clonage (§5,
   `compute_boot_fingerprint`, `safety/card_fingerprint.py`).

⚠️ **Confirmé sur du vrai matériel : le montage forcé lui-même demande
les droits administrateur.** L'appel non élevé ci-dessus échoue en
pratique pour la même raison qu'un utilisateur normal ne peut pas monter
un périphérique brut sans passer par DiskArbitration (§3) — le test
manuel réussi utilisait `sudo mount -t msdos ...`. `partitions/` reste
volontairement sans dépendance vers `gui/` (utilisable depuis le CLI,
testable sans Qt) : `locate.py` expose donc `set_privileged_mount_hook`,
un point d'extension optionnel (`Callable[[device_path, mountpoint],
bool]`, `None` par défaut) plutôt qu'un import direct de `gui/elevate.py`.

`gui/main_window.py` l'installe au constructeur, **macOS uniquement**
(`platform.system() == "Darwin"`, jamais Linux/Windows — `pkexec`/`sudo`
et UAC n'ont pas cet équivalent léger dans ce squelette, `locate.py`
retombe sur son comportement non élevé sur ces deux OS comme avant ce
correctif), avec `MainWindow._mount_boot_privileged` : réutilise
`_get_or_create_macos_auth_session()` (§3, la même session partagée
qu'un `WorkerRunner` de backup/flash — jamais une invite mot de passe
séparée pour ce cas précis) puis délègue à `gui/elevate.py::
run_privileged_mount`, un nouveau point d'entrée synchrone (contrairement
à `launch_elevated_worker`, asynchrone et pensé pour la relance du worker
complet avec son protocole JSON Lines/fichier de progression — une
commande aussi courte qu'un montage n'en a pas besoin). Réutilise le même
chemin bas niveau que le worker (`MacosAuthorizedProcess`/
`AuthorizationExecuteWithPrivileges` si `sys.frozen` et l'API historique
disponible, `osascript … with administrator privileges` sinon) ; ni l'un
ni l'autre ne remonte de façon fiable le code de sortie de la commande
élevée elle-même, donc le succès est vérifié après coup via
`os.path.ismount(mountpoint)`, jamais supposé du simple fait qu'aucune
exception n'a été levée. `_force_mount_macos` n'appelle ce repli qu'en
tout dernier recours, après l'échec du montage forcé non élevé — jamais
d'invite avant d'en avoir réellement besoin (§5).

⚠️ **Même cas sous Windows, bug corrigé (confirmé sur du vrai matériel,
carte ArkOS 256 Go GPT, 2026-10-07)** : Windows attribue une lettre à la
partition EFI (`I:`) mais **`Get-Volume` ne renvoie aucun volume** pour
elle. `_list_windows` ne gardait que les partitions avec volume : la BOOT
disparaissait de la liste, la carte s'affichait « Carte non préparée »
(A et D « non pertinentes », flash non marqué fait) et les positions
étaient décalées d'un cran. Corrigé : une partition sans volume est gardée
**seulement si son `GptType` est EFI** (`_EFI_SYSTEM_PARTITION_GPT_TYPE`),
avec `partition_type="efi"` (comme `_macos_partition_type`) --
`_looks_like_efi_boot` l'accepte alors comme BOOT. Jamais les autres
partitions sans volume : une partition réservée Microsoft (MSR, type
`{e3c9e316-…}`) n'en a pas non plus et fausserait la détection par
position. **Lecture** : sans élévation, Windows refuse l'accès à cette
partition (`I:\` comme son chemin GUID : « accès refusé ») ; **en
administrateur, elle se lit normalement** (vérifié : `Image`, `extlinux/`,
`.bmp`, `.dtb`) -- les étapes A/D, qui passent par le worker élevé, en
ont l'usage. **« Identifier ma console »** (sans élévation) : corrigé
aussi, voir `elevation-macos.md` (« Identification élevée sous Windows ») --
l'accès refusé n'est plus confondu avec « aucun `.dtb` » (`IdentifyFailure
Reason.ACCESS_DENIED`) et la lecture repasse par le worker élevé.

**Vérifié séparément** : la reconnaissance d'EASYROMS fonctionne aussi
sur ce schéma GPT, où son type de partition est « Microsoft Basic Data »
(confirmé sur du vrai matériel) plutôt que « Windows_NTFS » comme sur les
cartes MBR (bug déjà corrigé plus haut) — sans changement de code
nécessaire : `_select_easyroms` la retrouve par étiquette, indépendamment
de `partition_type`, et `FilesystemType` reste `"ntfs"` pour ce type de
partition ordinaire (contrairement au cas EFI ci-dessus, `diskutil` le
probe normalement).

Montage : attendre l'apparition automatique du volume (Windows/macOS le font seuls),
avec une temporisation et un contrôle. Sur Linux, `udisksctl mount` évite d'avoir
besoin des droits root pour cette étape.

Sous Windows, `_list_windows` ré-associe explicitement chaque volume à son
`PartitionNumber` d'origine dans la boucle PowerShell (`Get-Volume` ne préserve
pas l'ordre de son entrée) puis retrie côté Python sur ce champ — sans ça,
l'ordre des partitions rapporté peut varier d'un appel à l'autre. Une taille de
volume à `0` (partition dont Windows ne reconnaît pas le système de fichiers,
ex. la partition Linux ext4) est traitée comme inconnue (`None`), jamais comme
une vraie partition vide, pour ne pas fausser les estimations de taille.

**Partition sans lettre de lecteur sous Windows** (récit du faux « carte défaillante » dans `docs/bugs-devices-partitions.md`) :

**Corrigé en deux temps**, tous les deux dans `locate.py`/`gui/main_
window.py` :
1. **Monter sans lettre de lecteur, sans élévation.** Chaque volume a
   aussi un chemin GUID stable (`\\?\Volume{...}\`, propriété
   `AccessPaths` de `Get-Partition`, distincte de `Get-Volume`) —
   confirmé lisible sur du vrai matériel (`os.listdir`/`open`, sans
   élévation, sans lettre de lecteur assignée) : une identification
   complète (lecture des `.dtb`, reconnaissance du modèle) a réussi en
   passant directement par ce chemin. `_list_windows` (dans la même
   boucle PowerShell qui ré-associe déjà `PartitionNumber`, voir plus
   haut) récupère désormais aussi ce chemin (`VolumeGuidPath`) et
   l'utilise comme `mountpoint` quand aucune lettre n'est disponible —
   `locate_mounted` n'a alors même plus besoin d'attendre : le montage
   est déjà là dès le premier appel. Respecte §4.4 (l'identification
   doit rester non privilégiée) : aucune élévation n'est nécessaire,
   c'est un simple chemin de fichier alternatif vers le même volume.

Bénéfice au passage : ce repli sert `_list_windows` pour *toute*
opération sur une partition sans lettre de lecteur, pas seulement
l'identification — extraction du BOOT (étape A) comprise, qui aurait
échoué de la même façon sur une carte avec cette même particularité.

Copie de fichiers : parcours récursif avec cumul d'octets pour la progression, puis
`fsync` et démontage propre à la fin. `partitions/copy.py::_walk_files`
(`os.scandir()` récursif) énumère et récupère taille/type de fichier en un seul
passage — un aller-retour séparé par fichier (`Path.rglob` + `Path.stat()`)
dégraderait en O(n²) sur un dossier à dizaines de milliers de fichiers, un
système de fichiers FAT/exFAT parcourant sa table de répertoire linéairement à
chaque recherche par nom.

⚠️ **Correction de conception** : la première version de ce brief ne décrivait que
l'*injection* (BOOT/EASYROMS sauvegardés → carte neuve), en supposant à tort que
l'utilisateur disposait déjà de ces fichiers. Le vrai parcours enchaîne **deux
cartes** (l'ancienne, déjà en usage, puis la neuve) et nécessite donc aussi
l'**extraction** : copier le BOOT et l'EASYROMS de l'ancienne carte vers
l'ordinateur, avant de pouvoir les réinjecter sur la neuve. `partitions/jobs.py`
fournit donc `extract_boot`/`extract_easyroms`, symétriques d'`inject_boot`/
`copy_games` (même montage de la partition source, mais copie dans le sens
partition → dossier de l'ordinateur plutôt que l'inverse). L'extraction
d'EASYROMS ne lève jamais `MacosNtfsWriteUnsupported` : elle ne fait que lire la
partition, et macOS monte nativement le NTFS en lecture seule — la limitation
d'écriture ne concerne que l'injection (étape E, sur la carte neuve).

**Dossiers d'archive horodatés** (`partitions/archives.py`) : chaque extraction
crée un dossier nommé `{BOOT,EASYROMS}_{AAAA-MM-JJ}_{HH-MM}` (ex.
`BOOT_2026-07-06_00-21`) dans `~/Documents/R36S Studio/` par défaut — jamais
dans `~/.config` (§6). L'injection sur la carte neuve propose de choisir parmi
les archives existantes plutôt que de redemander un dossier à chaque fois,
avec un repli « Parcourir… » pour une source manuelle.

⚠️ **Régression corrigée** : une version intermédiaire a généré le chemin de
destination des étapes A/B entièrement automatiquement, sans écran de choix —
ce qui empêchait l'utilisateur de décider où son archive est enregistrée.
Rétabli : l'écran Choix du fichier reste toujours affiché pour A/B, avec
`~/Documents/R36S Studio/` pré-rempli comme *proposition*, acceptable tel
quel ou remplaçable par n'importe quel autre emplacement (y compris un
disque externe) — seul le nom horodaté à l'intérieur du dossier choisi reste
généré automatiquement, jamais laissé au clavier de l'utilisateur.

**Écran Résultat après une extraction (A/B)** : affiche le chemin complet de
l'archive créée, sa taille (comptée depuis le dernier événement de
progression — `copy_range`/`copy_tree` en émettent toujours un avec le
compte final exact, §2 n°5), et un bouton pour la révéler dans le
gestionnaire de fichiers de l'OS (`gui/reveal.py` : `open -R` sur macOS,
`xdg-open` sur Linux, `explorer /select,` sous Windows — GUI uniquement, le
CLI n'en a pas besoin). Après une injection (D/E), la même zone indique
plutôt quelle archive a servi de source, avec le même bouton de révélation.

**Éjection** (`partitions/eject.py`, déplacé depuis la GUI) : démonte toutes
les partitions de la carte puis l'éjecte (`diskutil eject` / `udisksctl
power-off -b`, qui font déjà les deux à la fois). La confirmation explicite
que la carte peut être retirée physiquement est à la charge de l'appelant
(CLI : message `emit_log` ; GUI : journal de bord permanent, §5, ou boîte de
dialogue) — jamais un succès silencieux.

Sur les trois OS, `eject()` n'est jamais appelée directement dans le
processus GUI : les quatre points d'appel (bouton du journal, mode expert,
étapes 3 et 5 du parcours de clonage) passent par un worker élevé dédié
(`gui/main_window.py::_start_eject`, même mécanisme que `backup`/`flash`,
`cmd_eject --worker`) — l'accès au disque physique pour l'éjection matérielle
exige les mêmes privilèges que l'écriture. Sur Windows, ce worker verrouille/
démonte chaque volume monté du disque puis envoie l'éjection matérielle
(`IOCTL_STORAGE_EJECT_MEDIA`) ; avant chaque tentative, la carte est
re-détectée (`_list_safe_devices()`, jamais un `Device` capturé une fois pour
toutes) pour éviter de cibler un chemin `\\.\PhysicalDriveN` périmé après un
premier échec. L'éjection de la carte source à l'étape 3 du parcours de
clonage est chaînée dans le worker de sauvegarde déjà élevé (`backup
--eject-after`, résultat rapporté séparément via l'événement `eject_result`
plutôt que mélangé au résultat de la sauvegarde) pour éviter une seconde
invite d'élévation — l'étape 5 (carte cible) reste un worker d'éjection
dédié, non chaînée dans le flash.

⚠️ **Point non vérifié à ce jour** : seule la branche Windows d'`eject()`
est confirmée sur du vrai matériel ; les commandes macOS (`diskutil eject`)
et Linux (`udisksctl power-off -b`) n'ont jamais été testées sur un vrai
périphérique dans ce projet. Un signalement isolé sur Windows (l'éjection
automatique de la carte source à l'étape 3 ne se déclenchant pas dans au
moins un cas observé) reste non reproduit et non confirmé — un diagnostic
renforcé (journalisation en tout premier, avant toute autre action) a été
ajouté en attendant, mais n'a pas encore été retesté sur le matériel en cause.

**Retiré, ne pas réintroduire** : `AppConfig.archive_records`/`get_archive_record`/`set_archive_record` et `ArchiveReuseDialog` (propres à l'ancien parcours guidé à sept étapes). Les étapes A/B, `_EXTRACTION_MODES`, `archives.default_archives_dir()`/`list_archives` restent en place pour le mode expert. Détail dans `docs/claude/archive-obsolete.md`.
