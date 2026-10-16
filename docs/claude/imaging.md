# `imaging/` — lecture et écriture brutes

À lire quand tu touches à `imaging/` (sauvegarde, sauvegarde système, flash, vérification SHA-256, formats d'image, partition de jeux automatique) ou à `cmd_backup`/`cmd_flash`.

> Les renvois « §N » de ce texte désignent les sections de l'ancien `CLAUDE.md` monolithique (commit `930f3c9`) : §3 → `elevation-macos.md`, §4.1/§4.2 → `devices-safety.md`, §4.3 → `imaging.md`/`reset-card.md`, §4.4 → `partitions.md`, §4.5 → `detect.md`, §4.6 → `firmwares-flash.md`, §5 → `interface.md`/`assisted-wizard.md`, §6 → `packaging.md`, §8 → `testing.md` ; §1/§2/§9 restent dans `CLAUDE.md`.

> 📚 Historique détaillé (bugs corrigés, investigations) : `docs/bugs-imaging-io.md`, `docs/bugs-imaging-partitions.md`

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

Sous Windows, le verrouillage/démontage porte sur *toutes* les partitions du
disque, lettrées ou non (`write_target._windows_all_volume_paths`, via
`Get-Partition -DiskNumber N` -- pas seulement `device.mountpoints`, qui
omet BOOT quand elle n'a pas de lettre) ; `FSCTL_LOCK_VOLUME` est retenté
jusqu'à 5 fois (0,5 s d'intervalle) sur `ERROR_ACCESS_DENIED` avant
d'abandonner avec un code dédié, `VOLUME_IN_USE` (invite à fermer les
fenêtres de l'Explorateur affichant la carte plutôt que de suggérer un
débranchement).

**Ordre d'écriture du flash (`imaging/flash.py`)** : le premier Mio de
l'image (MBR + GPT primaire) est lu en premier mais écrit **en dernier**
(`DEFERRED_HEAD_BYTES`, `_write_deferred_head`), et le dernier Mio de la
carte est remis à zéro juste avant (`TAIL_WIPE_BYTES`, `_wipe_stale_tail`,
jamais s'il chevauche l'image). La vérification relit le corps de l'image
**avant** d'écrire la table (`_hash_written_body` -- aucun volume ne peut
encore être monté, donc ni Windows ni macOS ne peuvent y écrire), puis
relit seulement le début de la carte après l'avoir écrit
(`_read_back_head`, sur une poignée neuve si Windows a révoqué la
poignée d'écriture).

⚠️ **`[Errno 9] Bad file descriptor` sous Windows -- cause identifiée le
11/10/2026, correctif à confirmer sur du vrai matériel** : écrire la table de
partitions en premier laissait Windows découvrir et monter les partitions de
l'image *pendant* la copie (nouveaux lecteurs visibles dans l'Explorateur
juste après l'échec) ; ces volumes-là n'étaient pas verrouillés, et Windows
révoquait la poignée physique. Détail : docs/bugs-imaging-io.md.

**Sauvegarde intelligente :** ne pas copier 128 Go quand la dernière partition s'arrête
à 8 Go. Lire la table de partitions (MBR ou GPT), calculer la fin du dernier secteur
utilisé, et ne sauvegarder que jusque-là. Proposer une compression `.img.gz` ou
`.img.xz` à la volée.

**Sauvegarde système sans les jeux (phase 9), section « Par sécurité ».**
La sauvegarde intelligente ci-dessus s'arrête déjà à la fin de la
*dernière* partition utilisée — mais sur une carte R36S d'origine, cette
dernière partition est justement EASYROMS (ou STORAGE sur EmuELEC), qui
représente l'essentiel de l'espace (100 Go typiques contre 8-9 Go pour
le système seul). `imaging/system_backup.py::backup_system_only`
s'arrête plutôt à la fin de la *dernière partition système*, juste
avant celle des jeux — identifiée via `partitions/locate.py::
list_partitions` (étiquette EASYROMS/STORAGE, comme le reste du projet)
plutôt qu'en lisant la table brute pour ça, une table MBR n'ayant aucun
concept d'étiquette. La table brute (MBR ou GPT, schéma détecté
automatiquement comme pour la sauvegarde intelligente) ne sert qu'à
trouver l'octet exact où s'arrête la partition précédente, une fois
l'index de la partition de jeux connu — même hypothèse de correspondance
par position entre `list_partitions` et la table brute que celle déjà
faite ailleurs dans ce projet (`BOOT_PARTITION_INDEX`/`EASYROMS_
PARTITION_INDEX`). Lève `GamesPartitionNotFound` quand aucune partition
de jeux n'est reconnaissable (carte ROCKNIX, où les jeux vivent dans la
partition Linux plutôt qu'une partition séparée ; ou carte au système
non reconnu) — pas de frontière évidente où s'arrêter dans ce cas.

**Point critique, table GPT** (`imaging/gpt.py`) : contrairement à MBR
(une table unique en tête de disque), GPT porte une table secondaire en
toute fin de disque, et l'en-tête primaire y pointe (`AlternateLBA`).
Une simple troncature laisserait cette table secondaire manquante et
l'en-tête primaire pointant hors du fichier — un outil de flashage
rejette alors l'image comme corrompue plutôt que de simplement accepter
une partition en moins. `backup_system_only` reconstruit donc une table
secondaire cohérente à la nouvelle fin de fichier (partition de jeux
retirée des deux tableaux d'entrées, primaire et secondaire), et met à
jour l'en-tête primaire en conséquence (`AlternateLBA`/`LastUsableLBA`,
CRC32 des deux recalculés dans le bon ordre imposé par la spec UEFI :
CRC32 du tableau d'entrées d'abord, puis CRC32 de l'en-tête lui-même
avec son propre champ à zéro pendant le calcul). CRC32 : l'algorithme
demandé par la spec UEFI (Annex D, ISO/IEC 13239:2002) est le CRC-32
IEEE 802.3 standard, le même que `zlib.crc32`/PNG — aucune inversion de
bits ni table personnalisée à gérer. Les GUID (type et identifiant de
partition) sont traités comme des blobs opaques de 16 octets, jamais
interprétés ni reconstruits, seulement recopiés tels quels. Vérifié par
des tests qui reconstruisent l'image complète et la reparsent bout en
bout (CRC32 des deux en-têtes et des deux tableaux d'entrées, contenu
des partitions gardées).

Le secteur 0 (MBR protecteur, type `0xEE`) doit également être corrigé après
troncature : `_repair_protective_mbr_after_truncation` (appelée juste après
`_rewrite_gpt_tables_after_truncation` dans `backup_system_only`) recalcule
son compte de secteurs à partir de la taille réelle du fichier produit,
reconstruit depuis `source` (lisible) plutôt que `destination` (écriture
seule). Sans ce correctif, `gdisk` (ou tout outil validant la cohérence entre
le MBR protecteur et la taille réelle du disque) signale l'image comme
corrompue -- « Disk size is smaller than the main header indicates » -- même
avec un en-tête GPT par ailleurs parfaitement réparé, puisque LBA0 continue
de décrire la taille du disque *source* (ex. 128 Go) plutôt que celle du
fichier produit (8-9 Go).

**Schéma MBR pur, vérifié distinctement (« la logique diffère
complètement » entre les deux schémas, confirmé en relisant le code)** :
contrairement à GPT, une table MBR pure n'a nulle part de champ séparé
déclarant la taille totale du disque -- chaque partition ne décrit que
sa propre étendue (`start_lba`/`sector_count`), déjà correcte et
inchangée pour les partitions gardées. Aucun équivalent du bug
protective-MBR n'est donc possible côté MBR pur, structurellement. Déjà
couvert bout en bout (pas seulement en isolation) par `test_backup_
system_only_mbr_output_table_is_consistent_with_real_file_size`, qui
vérifie qu'aucune partition gardée ne déborde du fichier produit.

**Identification de la partition de jeux, repli sans étiquette
reconnue** (`_fallback_games_partition_index`) : une carte qui ne nomme
ni EASYROMS ni STORAGE reste couverte — dernière partition du disque,
système de fichiers FAT ou NTFS, et taille au-dessus de `_LARGE_
PARTITION_THRESHOLD_BYTES` (1 Go, un seuil qui évite de prendre une
petite partition système FAT — BOOT, par exemple — pour la partition de
jeux). La taille vient de la table brute (MBR/GPT), `list_partitions`
n'exposant aucune taille ; le système de fichiers et la position («
dernière partition ») viennent de `list_partitions`, comme pour
l'identification par étiquette.

**Réparation de la table MBR aussi, pas seulement GPT.** Moins visible
que le cas GPT ci-dessus (pas de table secondaire à reconstruire), mais
tout aussi nécessaire : une simple troncature laisserait, dans l'image
MBR produite, l'entrée de la partition de jeux décrivant un espace qui
s'étend bien au-delà de la fin réelle du fichier. `backup_system_only`
met donc à zéro, dans le premier secteur de l'image produite, le
créneau de cette entrée (et de toute entrée après elle) — une simple
reconstruction en mémoire à partir du premier secteur déjà lu côté
source (`destination` étant ouvert en écriture seule, jamais relu),
MBR n'ayant ni CRC ni table secondaire à recalculer contrairement à GPT.

**Estimation avant de lancer, et confirmation explicite** (§5) :
`gui/partition_runner.py::SystemBackupEstimateRunner`, un thread séparé
comme les autres runners de ce module (lire la table de partitions est
rapide, mais le montage du BOOT pour l'identification du modèle peut
bloquer jusqu'à `MOUNT_WAIT_SECONDS`, §4.4) — calcule la taille estimée
(`imaging/system_backup.py::estimate_system_backup_size`, journalisée
avant l'ouverture de la fenêtre Choix du fichier) et tente, en
best-effort, d'identifier la console (`identify_from_boot_directory`
sur le BOOT monté) pour
suggérer un nom de fichier qui inclut le modèle *quand il est connu* —
un échec d'identification n'empêche jamais l'estimation d'aboutir, cette
partie est purement décorative. Nom suggéré : `systeme_{modèle}_
{AAAA-MM-JJ}_{HH-MM}.img` dans `~/Documents/R36S Studio/` (même
convention que `partitions/archives.py`, jamais `~/.config`, §6) —
`{modèle}` est l'identifiant brut du `.dtb` (ex. `rk3326-r35s`, ou
`G80CA-MB-V1.2` avec un point, préservé par la mise en sécurité du nom
de fichier plutôt que défiguré), pas un nom convivial (rien de tel
n'existe ailleurs dans ce projet). Comme pour toute proposition de ce
genre dans l'appli, toujours remplaçable en entier via Parcourir,
jamais imposé.

La taille estimée est affichée deux fois : dans le journal de bord, et
directement sur la fenêtre Choix du fichier (`FileDialog.
set_estimated_size`, sauvegarde système uniquement) — un débutant
pourrait ne pas remarquer une ligne de journal qui défile. Cliquer
Suivant sur cette fenêtre (taille visible, fichier choisi) sert de
confirmation explicite avant de lancer la copie ; contrairement au
flash, rien n'est effacé ici (lecture seule du périphérique, écriture
seulement dans un fichier), donc pas de fenêtre rouge de type
`ConfirmDialog` — celle-ci reste réservée aux opérations destructrices
(§2 règle 6).

Passe par le worker élevé comme la sauvegarde complète (`backup
--system-only`, `__main__.py::cmd_backup`) — c'est une lecture brute du
périphérique, §3.

**Estimation sans élévation (correctif du `[Errno 13] Permission denied` sur `/dev/diskN`, récit dans `docs/bugs-imaging-partitions.md`)** :

**Corrigé en deux temps, dans cet ordre de préférence (une estimation
ne devrait pas demander de mot de passe) :**
1. **Estimation sans accès brut.** `partitions/locate.py::PartitionInfo`
   porte désormais un champ `size_bytes`, renseigné sans élévation par
   les outils déjà utilisés pour lister les partitions : `diskutil info
   -plist` (`Size`) sur macOS, `lsblk -o ...,SIZE` sous Linux,
   PowerShell `Get-Volume` (`Size`) sous Windows. `imaging/system_
   backup.py::estimate_system_backup_size_unprivileged` additionne les
   tailles des partitions gardées (même logique d'identification de la
   partition de jeux que `backup_system_only` — étiquette EASYROMS/
   STORAGE puis repli par position/système de fichiers/taille) ;
   approximatif (arrondi à la taille de partition déclarée par l'OS,
   pas l'octet exact de fin d'usage comme la copie réelle), mais
   suffisant pour une estimation affichée avant de lancer l'opération.
2. **Repli élevé, seulement si une taille manque.** Si l'OS n'expose
   pas la taille d'une des partitions gardées (`size_bytes` absent),
   `estimate_system_backup_size_unprivileged` renvoie `None` plutôt que
   d'inventer une valeur ; `SystemBackupEstimateRunner` relance alors
   l'estimation via le worker élevé — un nouveau mode `backup --system-
   only --estimate-only` (`__main__.py::cmd_backup`, `--output` devient
   optionnel dans ce mode) qui calcule la taille exacte
   (`compute_system_boundary`, accès brut) sans rien écrire, et
   l'émet via un nouvel événement `estimate` du protocole JSON Lines
   (`protocol.py::emit_estimate`, `{"type": "estimate", "size_bytes":
   ...}`). Passe par la même `MacosAuthorizationSession` partagée que
   toute autre opération élevée (`MainWindow._get_or_create_macos_auth_
   session()`, §3) — jamais une invite mot de passe séparée pour ce
   repli. `WorkerRunner` gagne un signal `estimate = Signal("qint64")`
   (même raison `qint64` que `progress`, §3 — une taille peut dépasser
   2 Go) pour le relayer à la GUI.

La sauvegarde réelle (`backup_system_only`/`compute_system_boundary`,
lancée une fois le fichier choisi) n'a pas changé : elle passait déjà
par le worker élevé comme toute écriture/lecture brute (§3), et continue
de partager la même session — vérifié par un test dédié qui enchaîne une
sauvegarde système puis un flash et contrôle qu'une seule
`AuthorizationRef` est créée pour les deux.

**Corrigé pour de bon : décision entièrement automatique, prise par le
worker élevé lui-même après l'écriture, jamais par la GUI.** L'app
dispose déjà de toute l'information nécessaire pour décider seule --
la taille de l'image qu'elle vient d'écrire, la taille réelle de la
carte -- sans jamais demander à l'utilisateur de la deviner :
- `imaging/games_partition.py::create_and_format_games_partition_if_
  worthwhile` (nouveau point d'entrée, remplace l'ancien `--create-
  games-partition` conditionnel) : calcule d'abord, en lecture seule
  (`_peek_free_games_partition_bytes`, sans `prepared_write_target` --
  lire quelques secteurs d'un périphérique déjà monté fonctionne
  nativement sur les trois OS, contrairement à l'écriture, §4.3),
  l'espace qui serait disponible ; ne tente la création réelle
  (verrouillage + écriture, `create_and_format_games_partition`) que si
  cet espace atteint `GAMES_PARTITION_WORTHWHILE_BYTES` (1 Go, seuil
  demandé explicitement -- un seuil *métier*, distinct du minimum
  *technique* `MIN_GAMES_PARTITION_BYTES` de 64 Mo en dessous duquel une
  partition ne serait de toute façon pas assez grande pour un seul jeu).
  En dessous du seuil, ou si `NoFreeSpaceForGamesPartition`/
  `NoFreeMbrSlot` sont quand même levées lors de la tentative réelle
  (rare : l'espace a pu changer entre l'estimation et l'écriture) --
  retourne `None` sans jamais lever, « sinon ne rien faire » plutôt
  qu'un échec.
- `__main__.py::cmd_flash` : plus de drapeau `--create-games-partition`
  à passer (retiré de l'argument parser) -- tentée pour **tout** flash
  réussi et vérifié, sur toute plateforme, sans condition sur le
  firmware ni sur la provenance du fichier. Journalise systématiquement
  la décision et son résultat (§4.4 : jamais silencieusement) -- « pas
  assez d'espace libre », ou la taille effectivement créée. Une
  véritable erreur d'écriture/formatage (`OSError`,
  `subprocess.CalledProcessError`, `ValueError`) est journalisée en
  avertissement (`emit_log(..., level="warning")`) mais **ne fait
  jamais échouer le flash déjà réussi** -- même principe déjà établi
  pour `--eject-after` (§4.6) : un bonus qui échoue après coup ne doit
  pas renverser un résultat par ailleurs correct et déjà vérifié par
  SHA-256. Les anciens codes `GAMES_PARTITION_CREATE_FAILED`/
  `GAMES_PARTITION_FORMAT_FAILED` (qui faisaient échouer tout le flash)
  ont été retirés en conséquence, `gui/strings.py` compris.

**Exception : carte de console SF3000 (2026-09-28).** Quand la première
partition de la carte fraîchement écrite contient `cubegm/rkgame` (menu
d'origine HiChip ou TreeFrogUI), `cmd_flash` ne crée **aucune** partition
de jeux et le journalise (« Carte de console SF3000 reconnue… »). Le
système de ces consoles ne lit que `/mnt/sdcard`, la première partition
(`cubegm/*.sh`, `rootfs/etc/mdev/mount-helper.sh` de la carte d'origine :
toute autre partition finirait sous `/media/mmcblk0pN`, qu'aucun programme
ne lit) -- une EASYROMS y était de l'espace perdu (constaté : clone d'une
carte d'origine de 48,8 Go sur 128 Go, EASYROMS de 70 Go vide et
invisible). Détection en lecture seule sur le périphérique brut
(`imaging/card_probe.py`, exFAT et FAT32, jamais d'exception), donc
identique en mode expert et dans le parcours guidé. **Étendre la
partition principale à la place n'est pas fait** : l'exFAT ne se
redimensionne pas sans déplacer toutes les données (table d'allocation de
taille fixée au formatage, suivie immédiatement des données), aucun outil
standard ne le fait (Windows refuse, exfatprogs n'a pas de redimensionnement)
-- l'espace restant reste non partitionné par ce chemin ; « utiliser toute
la carte » (ci-dessous) est l'alternative. Détection vérifiée depuis sur
la vraie image d'une carte d'origine (fichier `.img`, lecture seule).

**Exception : carte ROCKNIX (2026-10-11).** Première partition FAT32
étiquetée `ROCKNIX` (`imaging/card_probe.py::is_rocknix_card`, lecture
brute de l'étiquette du secteur de démarrage, vérifiée sur l'image
`ROCKNIX-RK3326.aarch64-20261001-a`) : aucune partition de jeux. ROCKNIX
agrandit lui-même sa partition de stockage (32 Mo dans l'image) jusqu'à la
fin de la carte au premier démarrage (`resizepart 2 100%`) ; une partition
de jeux créée derrière elle l'en empêche -- exactement « Can't have
overlapping partitions » dans `fs-resize.log`, stockage resté à 32 Mo, écran
noir après le logo. Cause probable de l'incident du 11/10/2026, en plus de
la table GPT de secours périmée (`docs/bugs-imaging-io.md`) : **à confirmer
sur du vrai matériel** (le journal du flash concerné aurait dû contenir
« Espace de jeux recréé… »).

**Généralisé : toute carte qui a déjà sa partition de jeux (2026-10-17).**
`card_probe.py::own_games_partition_bytes` (lecture brute, nom GPT ou
étiquette FAT16/FAT32/exFAT/ext4 EASYROMS ou STORAGE) : si vrai, aucune
partition créée, journal « ta console va agrandir sa partition de jeux
toute seule… ». Toute image de firmware porte sa propre partition de jeux
et l'agrandit au premier démarrage ; seule une sauvegarde système (partition
retirée) reçoit donc l'espace de jeux automatique. Incident : dArkOSen,
constaté deux fois -- EASYROMS restée à 99 Mo, pleine, derrière une
partition de 20,9 Go illisible par la console. Étiquette STORAGE (ext4)
vérifiée sur l'image ROCKNIX 20261001-a ; EASYROMS de dArkOSen d'après le
constat, pas relue sur l'image.
Cas inverse, **sauvegarde complète restaurée sur une carte plus grande**
(32 Go sur 128 Go) : la partition de jeux a déjà été agrandie une fois et
ne le sera plus. Si elle fait au moins 1 Go et qu'il reste au moins 1 Go
libre derrière (`GAMES_PARTITION_WORTHWHILE_BYTES`, seuil supposé, jamais
mesuré), `_report_space_after_own_games_partition` avertit : « … restent
inutilisés. Pour en profiter, restaure plutôt ta sauvegarde système, puis
copie tes jeux ». Pas d'agrandissement automatique (exFAT non
redimensionnable, voir SF3000 ci-dessous).

**« Utiliser toute la carte » (carte SF3000, 2026-09-29).** Commande
`clone-sf3000` (`__main__.py::cmd_clone_sf3000`, `imaging/sf3000_clone.py`,
lecteur `imaging/exfat_reader.py`) : au lieu d'écrire l'image brute, une
seule partition exFAT sur toute la carte, puis copie des fichiers de
l'image un par un. **Windows uniquement** (formatage `Format-Volume`) ;
image `.img` non compressée seulement (sinon : copie brute, comme avant).
Étapes :
1. Avant toute écriture : image exFAT avec `cubegm/rkgame`
   (`NOT_SF3000_IMAGE`), inventaire complet, noms impossibles sous
   Windows refusés (`INVALID_FILE_NAMES`), place suffisante
   (`DESTINATION_TOO_SMALL`). Puis la confirmation (§2 n°6).
2. Disposition : les 16 premiers Kio de l'image recopiés (vérifié sur la
   carte d'origine : MBR à code de démarrage nul + signature de disque,
   secteurs 1-31 à zéro -- rien d'autre à restituer), seule l'entrée 1
   réécrite (type `0x07`, début secteur 32, fin de carte moins 1 Mio) ;
   1 Mio effacé après l'en-tête (un ancien secteur de démarrage exFAT au
   même décalage ferait remonter l'ancien volume) et en fin de carte.
3. Formatage exFAT, clusters de 64 Kio, étiquette de l'image (aucune sur
   la carte d'origine) ; lettre de lecteur obligatoire
   (`WHOLE_CARD_PREPARE_FAILED` sinon).
4. Fichier témoin `R36S_STUDIO_COPIE_EN_COURS.txt` à la racine, copie
   (chemins `\\?\`, dates de modification, attributs lecture seule/caché/
   système, `fsync` par fichier, SHA-256 calculé pendant la copie ;
   `System Volume Information` sauté), progression en octets réels.
5. Vérification (par défaut ; `--no-verify` en mode expert seulement) :
   volumes démontés d'abord (sinon la relecture viendrait du cache de
   Windows), puis SHA-256 de chaque fichier relu ; arrêt au premier écart
   (`VERIFY_FAILED`, chemin du fichier dans le détail).
6. Témoin retiré, `cubegm/rkgame` relu sur la carte, éjection
   (`--eject-after`, mode expert).
Tout échec après l'étape 2 : carte à refaire depuis le début (pas de
reprise) ; le témoin la signale au prochain branchement (journal,
`MainWindow._warn_if_interrupted_whole_card_copy`). L'image n'est jamais
que lue.

Interface : mode expert, `WholeCardChoiceDialog` avant la Confirmation
dès que l'image est une carte SF3000 exFAT et la carte plus grande d'au
moins 1 Gio (`sf3000_clone.whole_card_used_bytes`, lecture rapide du
bitmap d'allocation, sans élévation) -- chaque option annonce son coût
(minutes de plus / espace inutilisable), case « vérifier » cochée par
défaut. Mode assisté (parcours de clonage, étape 4, et « Préparer une
carte avec cette sauvegarde ») : toute la carte automatiquement,
vérification toujours faite, décision et durée journalisées.

Durées : débits supposés (`FILE_COPY_BYTES_PER_SECOND` 25 Mio/s,
`RAW_WRITE_BYTES_PER_SECOND` 35 Mio/s, `VERIFY_BYTES_PER_SECOND`
80 Mio/s), **à recaler au premier essai réel**. Carte d'origine
(29 486 fichiers, 191 dossiers, 45,5 Gio, inventaire lu en 2 s) : environ
8 min de plus qu'une copie brute, 10 min de vérification, 42 min en tout.

Prérequis vérifié sur du vrai matériel avant d'écrire le code
(procédure manuelle `diskpart` `offset=16` + `format fs=exfat unit=64K` +
`robocopy`, fichier de remplissage de 60 Go pour pousser des données
au-delà de l'ancienne limite) : la console démarre et les jeux
fonctionnent. **Jamais lancé depuis l'app sur une vraie carte à ce jour.**

**Non confirmé sur du vrai matériel au moment d'écrire cette note** :
couvert par des tests qui isolent le calcul (lecture directe d'un
fichier factice servant de périphérique, sans verrouillage) et la
décision (mocks), plus les tests CLI existants -- pas par une vraie
restauration Windows. À vérifier au prochain flash réel d'une image plus
petite que la carte : la ligne « Espace de jeux recréé sur l'espace
libre restant (… octets) » doit apparaître dans le journal, sans aucune
action de l'utilisateur.

**Ligne de commande complète journalisée au lancement de tout worker
élevé (§4.4), pour vérifier ce genre de chose sans avoir à instrumenter
le worker à chaque doute.** Redemandé après le correctif ci-dessus :
vérifier depuis les traces d'élévation elles-mêmes qu'un drapeau donné
est bien transmis (`--create-games-partition`, entre autres, avant
d'être retiré) n'était possible qu'en lisant le code, jamais en
observant ce que l'app avait réellement lancé. `gui/main_window.py::
_start_worker`/`_start_eject` journalisent désormais, juste avant de
construire le `WorkerRunner`, une ligne `[diagnostic] worker : …` avec
l'argv complet joint par des espaces (se lit comme la ligne qu'un
utilisateur pourrait retaper lui-même) -- pour *tout* lancement
(backup/flash/éjection), pas seulement celui suspecté à l'origine de la
demande. Généralisé volontairement plutôt que limité au seul cas du
moment : la même question (« qu'est-ce qui a été lancé, exactement ? »)
se reposera pour d'autres drapeaux à l'avenir.

**Formats source acceptés au flash :** `.img`, `.img.gz`, `.img.xz`
(décompression en flux, sans fichier temporaire). `.img.zip` a été
envisagé mais n'a jamais été implémenté — `image_source.SUPPORTED_EXTENSIONS`
ne couvre que ces trois extensions ; un `.zip` choisi pour le flash échoue
avec le message générique de format non supporté (ci-dessous), jamais avec
une décompression réussie.

**Détection du format par octets d'en-tête, pas seulement l'extension
(phase 8).** Les images ArkOS sont distribuées en `.7z` — jusqu'ici,
choisir ce fichier pour le flash échouait avec un message générique et
peu clair (`error_generic`, "Une erreur est survenue.", faute d'un code
d'erreur dédié). Pire : un `.7z` renommé en `.img` (une confusion facile
pour un néophyte) n'était même pas détecté — `open_image_source`
décidait uniquement sur l'extension et aurait écrit l'archive telle
quelle sur la carte, silencieusement incorrect (règle §2 n°5/n°6).

`image_source._detect_format` lit désormais les premiers octets du
fichier (signatures gzip `1F 8B`, xz `FD 37 7A 58 5A 00`, zip
`50 4B 03 04`, 7z `37 7A BC AF 27 1C`) plutôt que de se fier à
l'extension ; `check_image_format` en tire `SevenZipArchiveError`
(message dédié) ou `UnsupportedImageFormatError` (générique, ex. `.zip`
ci-dessus). Appelé à **deux endroits** :
1. **`imaging/flash.py::flash_device`**, en tout premier — avant
   `prepared_write_target` — pour ne jamais démonter/préparer la carte
   pour une source déjà connue comme inutilisable (règle §2 n°6). Couvre
   le CLI direct et sert de filet de sécurité si la GUI est contournée.
2. **`gui/main_window.py::_on_file_chosen`**, juste après le choix du
   fichier pour le flash — *avant* même la fenêtre Confirmation, et donc
   avant toute élévation de privilèges (§3). Sans ce doublon côté GUI,
   un fichier invalide coûterait à l'utilisateur une demande de mot de
   passe administrateur pour un échec connu d'avance.

Message affiché (`gui/strings.py`, §5 vocabulaire) : *« Ce fichier est
une archive 7-Zip. Décompresse-la d'abord — tu obtiendras un fichier
.img que tu pourras flasher directement. »* Le worker élevé (CLI) émet
les codes `SEVEN_ZIP_ARCHIVE`/`UNSUPPORTED_IMAGE_FORMAT` (`__main__.py`,
`protocol.py`) que `friendly_error_message` traduit côté GUI si jamais
ce chemin est atteint malgré la vérification préalable.

**Prévenir avant même le téléchargement** : `FileDialog` (flash, firmware
ArkOS uniquement) affiche désormais en permanence, sous le bouton « Voir
les versions disponibles en ligne », un rappel — *« Le fichier téléchargé
sera une archive .7z : décompresse-la d'abord, puis choisis ici le
fichier .img qu'elle contient. »* — pour qu'un débutant sache quoi faire
avant de se retrouver bloqué avec un fichier que le logiciel refuse,
plutôt qu'après coup seulement via le message d'erreur ci-dessus.

**Décompression native du `.7z` (py7zr) : envisagée, non retenue** (streaming impossible sans fichier temporaire + poids des dépendances C). Évaluation complète dans `docs/bugs-imaging-io.md` ; à revisiter seulement sur demande explicite.

**Taille décompressée d'un `.xz`** : lue sans décompression depuis l'Index au pied de l'archive (`image_source._xz_uncompressed_size`, comme le champ ISIZE pour `.gz`) ; si le format n'est pas standard, `flash_device` retombe sur la taille du périphérique cible plutôt que de traiter la copie comme non bornée (sinon la barre affiche 100 % dès le premier octet — récit dans `docs/bugs-imaging-io.md`).

**Vérification SHA-256 après flash sur macOS** : macOS peut remonter automatiquement les partitions juste après l'écriture et y écrire (`.Spotlight-V100`, `.fseventsd`…), faussant la relecture — récit complet dans `docs/bugs-imaging-io.md`.

**Corrigé par deux mesures complémentaires :**
1. `write_target.reunmount_before_verify` démonte à nouveau (macOS
   uniquement, `check=False` — rien à démonter est un résultat normal
   ici) juste avant la relecture (`flash.py`), pas seulement avant
   l'écriture.
2. Le descripteur d'écriture (`destination`, `open(raw_path, "r+b")`)
   reste ouvert jusqu'à la fin de la vérification plutôt que d'être
   refermé puis rouvert pour relire (`_hash_stream_range` reçoit
   directement ce flux, repositionné à `seek(0)`, pas un chemin à
   rouvrir) — ça referme la fenêtre de course elle-même, la mesure 1
   restant un filet de sécurité pour le cas où une partition
   individuelle se monterait indépendamment du périphérique brut.

Vérifié séparément : la relecture (`_hash_stream_range`) ne porte que sur
exactement `written` (le compte d'octets réellement copiés depuis la
source, cf. `copy_range`) — jamais sur l'espace non alloué au-delà, que
ce soit la fin d'une carte plus grande que l'image ou un reste d'un
flash précédent. C'était déjà correct avant ce correctif ; couvert
explicitement par un test depuis (`test_flash.py`).

**Double lecture de la source et `.sha256blocks` (2026-10-10, `imaging/source_verify.py`).**
Incident réel : une carte d'origine noname (fabricant SD 0xFE) a renvoyé,
sans erreur d'E/S, des bits inversés (blocs isolés de 1 à 4 Ko, flash
dégradée) pendant une sauvegarde système ; l'image fausse a été flashée sur
une SanDisk et la vérification SHA-256 du flash est passée (elle compare la
carte à l'image, déjà fausse) -- libcairo corrompue, RetroArch qui plante.
- **Pendant la copie** : `copy_range(..., block_digests=liste)` ajoute le
  SHA-256 de chaque bloc réellement lu (4 Mio). Autres appelants inchangés.
- **Relecture** (`verify_source`, phase de progression `verify_source`,
  annulable bloc par bloc) : même plage, mêmes décalages (multiples de
  4 Mio, donc alignés sur le secteur sous Windows). Bloc différent : relu
  jusqu'à 3 fois, accepté dès 2 relectures égales à la copie, instable
  sinon. Linux : `posix_fadvise(DONTNEED)` avant chaque relecture (sinon le
  cache de pages de `/dev/sdX` servirait la relecture). Une carte qui renvoie
  *toujours* les mêmes octets faux n'est pas détectable ainsi.
- **Source instable** (`SourceUnstable`, code `SOURCE_UNSTABLE`) : l'image
  n'est jamais supprimée (peut-être la seule copie d'une carte qui meurt) --
  renommée en `<nom>.img.instable`, plages dans `<nom>.img.instable.txt`,
  pas de `.sha256blocks`. Le flash la refuse (`UNSTABLE_IMAGE`), sauf mode
  expert après une confirmation explicite (`--allow-unstable`) ; le
  sélecteur d'image ne la propose que via un filtre secondaire.
- **Option** : `config.json::verify_backup_source` (vrai par défaut), case
  « Vérifier la source par double lecture (recommandé) » sur la fenêtre
  Choix du fichier des sauvegardes, mode expert seulement ; la GUI passe
  `--no-source-verify` au worker (qui ne lit pas forcément le même
  `config.json`, root sous macOS). Désactivée : environ deux fois plus
  rapide, `.sha256blocks` toujours écrit.
- **Format `<image>.sha256blocks`** (ASCII, `\n`) : en-tête
  `R36S-SHA256BLOCKS 1 block_size=4194304 total_size=<octets>`, puis une
  empreinte hex par bloc, dans l'ordre ; le dernier bloc peut être plus
  court. Sauvegarde complète : empreintes de la copie (fichier = octets lus).
  Sauvegarde système : sur le fichier FINAL -- les blocs réécrits après la
  copie (LBA0, en-tête et tableau primaires GPT, tout ce qui suit
  `end_bytes`) sont relus dans le `.img` produit (`_rewritten_block_indices`),
  les autres reprennent les empreintes de la copie. Format des `.img`
  inchangé.
- **Avant le flash** (`flash_device`, avant `prepared_write_target`) :
  compagnon présent -> recalcul des empreintes de l'image (phase
  `verify_image`, `.gz`/`.xz` compris) ; un écart lève `ImageModified`
  (`IMAGE_MODIFIED`, liste des blocs), la carte n'est pas touchée. Pas de
  compagnon (image ancienne ou téléchargée) : avertissement dans le journal,
  flash comme avant. GUI : contrôles gratuits seulement avant l'élévation
  (écart à l'invariant documenté dans `CLAUDE.md` §5). La vérification
  SHA-256 après écriture (`FlashResult.verified`) est inchangée.
- **Non fait** : `clone-sf3000` ne contrôle pas encore le compagnon (TODO,
  `CLAUDE.md` §7).

**Chien de garde de lecture (2026-10-10, `imaging/source.py::StallWatchedReader`).**
Cas réel : la même carte noname bloque parfois une lecture pendant des
heures, sans erreur ni donnée -- barre figée en silence.
- **Lectures surveillées** : copie et relecture de `backup_device`/
  `backup_system_only`, et lecture initiale des tables (`compute_backup_size`,
  `compute_system_boundary`, donc aussi `estimate_system_backup_size`).
  Chaque `read()` part dans un thread **daemon** (`r36s-source-read`) ; le
  thread appelant attend par tranches d'une seconde et reste annulable.
- **Signalement** : au-delà de 5 s sans données (`STALL_NOTICE_SECONDS`),
  événement `stalled` (`seconds`/`limit`) environ chaque seconde ; la GUI
  (`LogPanel.show_stalled`) affiche en rouge « La carte ne répond plus depuis
  N s (arrêt à M s) », une seule ligne au journal par blocage, effacé au
  prochain `progress`.
- **Abandon** : aucun octet pendant `config.json::source_stall_timeout_seconds`
  (60 s par défaut, minimum 10, invalide -> 60 ; la GUI ne passe
  `--stall-timeout` que si la valeur diffère du défaut) -> `SourceNotResponding`
  (sous-classe d'`OSError`, attrapée avant), code `SOURCE_NOT_RESPONDING`.
- **Sortie du worker** : le flux bloqué n'est jamais refermé (le thread
  coincé tient son verrou, `close()` bloquerait aussi). Si un thread de
  lecture est encore vivant à la fin d'une commande `--worker`
  (`has_stuck_reads`), `__main__.main` quitte par `os._exit(code)`, après
  les événements finaux et la fermeture du fichier de progression -- jamais
  bloqué par la finalisation de l'interpréteur. Un `ReadFile` Windows coincé
  dans le pilote peut encore retarder la disparition du processus ; la GUI
  n'en dépend pas (elle s'arrête sur l'événement `done`).
- **Non surveillé** : `list_partitions` (avant la lecture des tables
  système), l'écriture du flash (**TODO**, `CLAUDE.md` §7). Après un
  abandon, image partielle laissée sans `.sha256blocks`.
