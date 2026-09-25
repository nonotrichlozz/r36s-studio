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

⚠️ **Point non résolu à ce jour** : malgré ce verrouillage complet, une
écriture Windows sur une carte ArkOS complète (BOOT + root + EASYROMS) peut
encore échouer avec `[Errno 9] Bad file descriptor` peu après le début de
l'écriture -- cause exacte non confirmée (hypothèses : reset du pilote de
stockage au démontage, ou état PowerShell/WMI transitoire non encore
retombé). `imaging/copy.py::copy_range` inclut le nombre d'octets déjà
écrits et le temps écoulé dans le message d'erreur pour faciliter un futur
diagnostic.

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
