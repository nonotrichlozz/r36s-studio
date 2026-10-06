# Outils « Ranger des jeux mélangés » et « Filtrer par région et par langue »

Deux fonctions distinctes, deux lignes de la section « Outils » du mode
expert, à côté de « Chercher les doublons » (retirées de l'accueil
assisté, allégé pour le néophyte) :

- **Ranger des jeux mélangés** (« tri ») : répartir un dossier de ROMs en
  vrac dans des sous-dossiers par console, nommés comme le firmware cible
  les attend. Exige le dossier parent : un dossier qui porte lui-même un
  nom de console est refusé (le trier créerait `snes/snes/`).
- **Filtrer par région et par langue** (§ « Filtre région / langue ») :
  ne réorganise rien, écarte seulement ce qui ne correspond pas aux
  critères. N'importe quel dossier -- un dossier de console seul (`SNES`)
  ou une collection déjà rangée, dont chaque sous-dossier est parcouru.
  Aucun firmware. Les mélanger produisait des refus sans raison (un
  dossier `SNES` refusé alors qu'on voulait justement le filtrer).

Principes communs : aperçu avant action, déplacement vers un dossier à
part (jamais de suppression), annulation -- avec **un journal par
fonction** (`_rangement_journal.json`, `_filtre_journal.json`) : annuler
un filtrage ne défait jamais un rangement fait avant dans le même
dossier.

Code : `r36s_studio/tri/` (sans Qt ; `plan.py` tri, `filter.py` filtre,
`regions.py` règle région/langue, `apply.py` déplacement et annulation
communs), écrans `gui/tri_screen.py` (`TriScreen`, et `FilterScreen` qui
n'en remplace que la page de choix, l'aperçu, quelques libellés
`filter_*` et le journal), threads `gui/tri_runner.py`. Tests :
`tests/test_tri_*.py`, `tests/test_gui_tri_screen.py`.

## ⚠️ Piège majeur TreeFrogUI : les ROM en `.7z`

Sur TreeFrogUI, une ROM en **`.7z` donne un écran noir ou un plantage** :
le jeu apparaît dans la liste et se lance, mais `picoarch` ne sait
décompresser que le `.zip` et **le cœur reçoit l'archive au lieu du
jeu**. Rien n'avertit l'utilisateur. Vérifié sur carte réelle le
2026-09-27 : les mêmes jeux Mega Drive, reconvertis en `.zip` (deflate),
démarrent dans `MD` (picodrive) comme dans `gpgx` (genesis_plus_gx), et
FrogUI affiche alors l'icône de manette (vrai jeu reconnu). Détail et
journaux au § « TreeFrogUI : alias et casse des dossiers ». Pour
« Ranger des jeux mélangés » : ne jamais ranger un `.7z` vers TreeFrogUI tel
quel (refuser, ou convertir en `.zip` après vérification du CRC).

## ⚠️ Les BIOS ne sont pas des ROMs

Un BIOS (ou boot ROM, firmware de lecteur CD, d'adaptateur) ne doit
**jamais** être rangé vers un dossier de système : la console l'affiche
comme un jeu, qui ne démarre pas ou affiche n'importe quoi. « Ranger mes
jeux » doit les reconnaître et soit les laisser où ils sont, soit les
envoyer vers le dossier BIOS du firmware cible -- jamais les traiter
comme des jeux.

**Dossier BIOS de TreeFrogUI : `cubegm/bios/`**, et nulle part ailleurs
(README § « BIOS files required », `docs/cores/ps1.md`, et le seul
chemin `system` présent dans `cubegm/picoarch` : `/mnt/sdcard/cubegm/bios`).
PS1 (`ps1r`, pcsx_rearmed) exige un `scph*.bin` à cet endroit.

**Piège No-Intro** : le tag `[BIOS]` marque aussi des **jeux intégrés à
une console** (Master System II : *Alex Kidd in Miracle World*,
*Hang On*, *Sonic The Hedgehog (Europe)*, *Missile Defense 3-D* -- ROM
de 128 à 256 Kio, jouables). Le tag seul ne suffit donc pas : il faut
une liste des BIOS connus (nom et/ou CRC), pas un simple motif.

Cas réel (carte SF3000 HD, 2026-09-27) : 39 fichiers `[BIOS]` dans
`roms/` ; 32 vrais BIOS (Game Boy, GBA bêta, Mega-CD, TMSS, Master
System, adaptateurs NES, SNES CD) déplacés vers `cubegm/bios/`, 7 jeux
intégrés laissés dans `sega/SMS/`. Déplacés tels quels (`.zip`,
noms No-Intro) : ils ne sont **pas utilisés** par les cœurs, qui
attendent des noms exacts non compressés (`bios_CD_E.bin`,
`bios_E.sms`, `gba_bios.bin`…) ; ils ne s'affichent simplement plus
comme des jeux.

**État actuel de l'outil** : un dossier nommé `bios` n'est jamais
parcouru (`config.py::DEFAULT_DOUBLONS_IGNORED_FOLDERS`), mais un BIOS
**mélangé aux jeux** est identifié par son en-tête (ex. `TMR SEGA`) et
rangé comme un jeu. À corriger (point ouvert ci-dessous).

## ⚠️ Risque principal : un nom de dossier faux

Si un nom de dossier est faux, la console n'affiche **aucun** jeu de ce
dossier et l'utilisateur ne comprend pas pourquoi. Parades en place :

1. **Une table par firmware** (`tri/data/firmware_folders.json`), jamais
   une liste unique ni un nom supposé. Chaque table porte sa source, sa
   date et un indicateur `verified_on_hardware`.
2. **Extensions acceptées relevées au même endroit** que les noms : un
   fichier que le firmware n'afficherait pas dans le dossier visé n'y est
   jamais rangé (motif `extension_not_accepted`). Vérifié par
   `test_tri_tables.py::test_every_routed_extension_is_accepted_by_its_folder`.
3. **Système absent d'une table = non rangé** (motif
   `system_not_supported`), jamais un nom deviné. Ex. dArkOS n'a pas de
   Famicom Disk System, TreeFrogUI n'a pas de Nintendo 64.
4. **Casse** : un dossier existant qui ne diffère que par la casse
   (`SNES` au lieu de `snes`) est signalé dans l'aperçu, et les jeux de
   cette console **restent en place** (motif `folder_case_conflict`).
   Sur Windows et sur les cartes FAT/exFAT, « créer » `snes` à côté de
   `SNES` écrirait en réalité dans `SNES` -- un dossier que la console
   risque de ne pas voir (TreeFrogUI documente « Folders are
   case-sensitive » dans `docs/cores.md` sur la carte).
5. **Aperçu** : l'écran affiche le firmware ciblé, si ses noms sont
   vérifiés sur une vraie carte ou non, et le nom exact de chaque dossier
   de destination avant toute confirmation.

## Tables par firmware -- statut de vérification

| Firmware | Source | Date | Vérifié sur vrai matériel |
|---|---|---|---|
| ArkOS / dArkOS (`arkos`) | `southoz/dArkOSRE-R36` @ `26820cdbc630`, `files/ROOTFS/etc/emulationstation/es_systems.cfg` | 2026-03-10 | ❌ **non** -- relevé dans la configuration officielle. Validation prévue sur une carte ArkOS de l'utilisateur (ci-dessous) |
| ROCKNIX (`rocknix`) | `ROCKNIX/distribution` @ `31d4f58d390a`, `config/emulators/<système>.conf` (`SYSTEM_PATH`, `SYSTEM_EXTENSION`) | 2026-07-11 | ❌ **non** -- relevé dans la configuration officielle |
| EmuELEC (`emuelec`) | `EmuELEC/EmuELEC` @ `9909590417bc`, `packages/sx05re/emuelec-emulationstation/config/es_systems.json` | 2026-09-17 | ❌ **non** -- relevé dans la configuration officielle |
| TreeFrogUI (`treefrogui`) | Carte SF3000 HD réelle (`roms\` sur la carte) + `docs/cores.md` présent sur la carte | 2026-09-25 | ✅ **oui** pour l'existence des dossiers ; jeux affichés confirmés pour `gba` et `snes`, pas encore pour les autres. Extensions acceptées non connues (`null`, aucun contrôle) |

Seule `treefrogui` porte `verified_on_hardware: true` -- figé par
`test_tri_tables.py::test_only_the_real_card_table_claims_hardware_verification`.
Passer une autre table à `true` exige une vérification sur du vrai
matériel, documentée ici.

La table `arkos` décrit **dArkOS** (la version maintenue vers laquelle
pointe le catalogue de flash), pas l'ArkOS d'origine archivé. Si une
carte ArkOS d'origine diffère, le noter ici avant de trancher.

### Noms de dossiers (générés depuis le JSON)

| Console | Extensions | dArkOS | ROCKNIX | EmuELEC | TreeFrogUI |
|---|---|---|---|---|---|
| NES | `.nes` | `nes` | `nes` | `nes` | `nes` |
| Famicom Disk System | `.fds` | — *(absent)* | `fds` | `fds` | `fds` |
| Super Nintendo | `.sfc` `.smc` | `snes` | `snes` | `snes` | `snes` |
| Game Boy | `.gb` | `gb` | `gb` | `gb` | `gb` |
| Game Boy Color | `.gbc` | `gbc` | `gbc` | `gbc` | `gb` |
| Game Boy Advance | `.gba` | `gba` | `gba` | `gba` | `gba` |
| Nintendo 64 | `.n64` `.z64` `.v64` | `n64` | `n64` | `n64` | — *(absent)* |
| Mega Drive | `.md` `.gen` `.smd` | `megadrive` | `megadrive` | `megadrive` | `sega` |
| Master System | `.sms` | `mastersystem` | `mastersystem` | `mastersystem` | `sega` |
| Game Gear | `.gg` | `gamegear` | `gamegear` | `gamegear` | `gg` |
| Sega 32X | `.32x` | `sega32x` | `sega32x` | `sega32x` | `32x` |
| PC Engine | `.pce` | `pcengine` | `pcengine` | `pcengine` | `pce` |
| Neo Geo Pocket | `.ngp` | `ngp` | `ngp` | `ngp` | `ngpc` |
| Neo Geo Pocket Color | `.ngc` | `ngpc` | `ngpc` | `ngpc` | `ngpc` |
| WonderSwan | `.ws` | `wonderswan` | `wonderswan` | `wonderswan` | `wswan` |
| WonderSwan Color | `.wsc` | `wonderswancolor` | `wonderswancolor` | `wonderswancolor` | `wswan` |
| Atari 2600 | `.a26` | `atari2600` | `atari2600` | `atari2600` | `a26` |
| Atari 7800 | `.a78` | `atari7800` | `atari7800` | `atari7800` | `a78` |
| Atari Lynx | `.lnx` | `atarilynx` | `atarilynx` | `atarilynx` | `lnx` |
| Virtual Boy | `.vb` | `virtualboy` | `virtualboy` | `virtualboy` | `vb` |
| ColecoVision | `.col` | `coleco` | `coleco` | `coleco` | `col` |

Écarts notables : ColecoVision = `coleco` sur les trois firmwares
EmulationStation, `col` sur TreeFrogUI ; TreeFrogUI range Mega Drive et
Master System ensemble dans `sega`, Game Boy Color dans `gb`, Neo Geo
Pocket dans `ngpc`, WonderSwan (Color) dans `wswan`. Les trois firmwares
ont aussi un dossier `genesis` : `megadrive` est retenu (présent partout).

### TreeFrogUI : alias et casse des dossiers (carte réelle, 2026-09-26)

Sources sur la carte (TreeFrogUI v1.5.0_l) : `README.md` § « ROM folder
setup » et `docs/cores.md` § Sega, concordants ; table des cœurs de
`cubegm/cores/frogui_libretro.so` (chaînes).

- **Mega Drive / Master System** : trois noms acceptés, `sega`, `MD`,
  `SMS` (→ `picodrive_libretro.so`) ; `gpgx` → `genesis_plus_gx`.
  **`md` en minuscules n'est pas dans la liste documentée**. (Les chaînes
  du binaire ne tranchent pas : chaque chaîne n'y figure qu'une fois,
  partagée entre tables.) `megadrive` et `genesis` n'existent pas sur ce
  firmware. L'archive officielle ne crée ni `MD` ni `md` dans `roms/` :
  le nom livré est `sega` ; `MD` n'a ni fond ni icône (`sega`, `gpgx` en
  ont).
- **`gpgx`** (→ `genesis_plus_gx`) : dossier livré par l'archive
  officielle, en minuscules, avec fond `frogui/gpgx.jpg` et icônes.
- **La casse change le système, pas seulement la visibilité** :
  « Folders are case-sensitive » (`docs/cores.md`), et `nes` → fceumm
  mais `NES` → quicknes, `FC` → fceumm. Ne jamais « corriger » un
  dossier majuscule existant (`MD`, `SMS`, `GG`, `GBA`, `FC`, `SFC`, `PS`)
  sans vérifier la table : c'est souvent un alias valide.
- L'outil range dans `sega` (nom canonique) ; un `MD` déjà présent sur la
  carte est un alias valide, pas une erreur à signaler.
- **`D:\MD\` (racine) ≠ `roms\MD\`** : le `MD` de la racine contient
  `dummy.md` + `filelist.csv`, que l'autorun du menu d'origine
  (`cubegm/setting.xml`) lance pour démarrer TreeFrogUI. Cas réel : ces
  deux fichiers retrouvés dans `roms\MD\` (très probablement déplacés avec
  les jeux) → logo puis écran noir, **aucun journal écrit**
  (`tfhijack.log` et `log.txt` inchangés). Un outil qui range ou copie
  vers la carte ne doit jamais toucher au `MD` de la racine.
- **`.7z` NON supportés** (vérifié le 2026-09-26 avec les journaux
  picoarch) : FrogUI **liste** les `.7z` et les lance, mais `picoarch` ne
  décompresse que le `.zip` (inflate/zlib seulement, « Unsupported zip
  file ») ; un `.7z` est passé brut au cœur (`retro_load_game
  path=….7z`, `cores.log` : « Loading 362398 bytes », taille du `.7z`
  et non de la ROM de 524 288 octets). Résultat : écran noir, sur
  `picodrive` comme sur `genesis_plus_gx` (le cœur, ne reconnaissant
  pas les données, se met en mode Master System : `Screen: 256x192`).
  Un `.7z` qui « démarre » n'est donc pas une preuve qu'il est lu.
  **Piège pour l'outil** : le jeu apparaît dans la liste, l'utilisateur
  ne comprend pas l'écran noir. Toujours `.zip` (deflate) ou ROM nue.
  Confirmé le 2026-09-27 : Sonic, Aladdin, Gunstar Heroes reconvertis en
  `.zip` fonctionnent dans `MD` et `gpgx` ; `picodrive` n'était pas en
  cause.
- Journaux utiles : créer un dossier vide `logs/` à la racine de la carte
  (+ `log.txt` existant) → `logs/picoarch.log` et `logs/cores.log`.
- Un jeu pirate (en-tête non standard) lancé depuis `MD` a fait planter
  FrogUI (`log.txt` : `frogui exited rc=139`) -- probablement la même
  cause (`.7z` brut), pas le jeu lui-même.

### Validation de la table ArkOS sur une vraie carte

Lister les dossiers de la partition de jeux (EASYROMS) d'une carte ArkOS
(`ls -1` sur la racine du lecteur EASYROMS), puis comparer avec la
colonne dArkOS ci-dessus. En cas d'écart, corriger le JSON, mettre à jour
ce document et `test_tri_tables.py`.

## Identification en cascade (phase 1)

Même principe que `imaging/image_source.py::_detect_format` : les octets
d'en-tête priment. `tri/identify.py`.

1. **Extension propre à un seul système** (`tri/data/systems.json`,
   unicité vérifiée au chargement).
2. **Signature d'en-tête**, quand le format en a une universelle -- si
   elle manque, le fichier **n'est pas rangé** (`header_mismatch`) :

   | Signature | Formats | Contrôle |
   |---|---|---|
   | `ines` | `.nes` | `NES\x1A` en tête |
   | `fds` | `.fds` | `FDS\x1A` ou `\x01*NINTENDO-HVC*` en tête |
   | `gb_logo` | `.gb` `.gbc` | logo Nintendo à 0x104 (48 octets) |
   | `gba_header` | `.gba` | logo à 0x04 + valeur fixe `0x96` à 0xB2 |
   | `n64` | `.z64` `.v64` `.n64` | un des trois ordres d'octets magiques |
   | `megadrive` | `.md` `.gen` | `SEGA` à 0x100, pas `32X`, pas un disque |
   | `smd_interleaved` | `.smd` | `AA BB` à l'octet 8, ou `SEGA` à 0x100 |
   | `sega_header` | `.32x` | `SEGA` à 0x100 |
   | `snk` | `.ngp` `.ngc` | `COPYRIGHT BY SNK CORPORATION` / ` LICENSED BY SNK…` |
   | `atari7800` | `.a78` | `ATARI7800` à l'octet 1 |
   | `lynx` | `.lnx` | `LYNX` en tête |
   | `coleco` | `.col` | `AA 55` ou `55 AA` en tête |

   **Extension seule** (aucune signature universelle) : `.sfc` `.smc`
   (les en-têtes internes SNES ont souvent une somme de contrôle fausse
   sur les traductions et hacks), `.sms` `.gg` (beaucoup de jeux japonais
   Master System n'ont pas l'en-tête `TMR SEGA`), `.pce`, `.ws` `.wsc`,
   `.a26`, `.vb`.
3. **Cas ambigus** :
   - `.zip` : contenu listé sans extraction. Exactement un fichier de jeu
     exigé (`.txt`/`.nfo`/`.diz` tolérés à côté) ; son extension et son
     en-tête sont contrôlés comme ci-dessus. Plusieurs fichiers =
     typiquement de l'arcade → non rangé (`zip_multiple`).
   - `.bin` : secteur CD brut ou en-tête Mega-CD → disque (non rangé) ;
     `SEGA` à 0x100 → Mega Drive (ou 32X) ; sinon non rangé (`bin_unknown`).
4. Tout le reste : `_non_identifies`, avec un motif.

**Signatures non encore vérifiées sur de vraies ROMs** : elles suivent
les formats publiés, mais les tests n'utilisent que des en-têtes
factices (`tests/tri_fixtures.py`). Un taux anormal de `header_mismatch`
sur une vraie collection serait le premier signal d'une règle trop
stricte (notamment `gba_header` pour des homebrews non passés par
`gbafix`, ou `megadrive` pour des homebrews sans `SEGA`).

## Ce qui n'est pas couvert (phase 1)

- **Images de disque** (`.cue` `.bin` de disque `.chd` `.iso` `.img`
  `.m3u` `.pbp` `.cso` `.gdi`…) : PS1, Mega-CD, PC Engine CD, Saturn…
  partagent les mêmes formats. Mises de côté dans `_non_identifies`, **en
  groupe** (`.m3u` → `.cue` → `.bin`, `doublons/linked_files.py`) ; un
  `.cue` dont un fichier manque est signalé (`disc_image_missing_files`).
- **`.7z`** : contenu non lu (le projet ne dépend pas de py7zr).
- **Arcade** (MAME, FBNeo, CPS, Neo Geo) : un zip à plusieurs fichiers.
- **Ordinateurs** (C64, MSX, Amiga, DOS…), PSP, NDS, Dreamcast, N64DD.
- Firmwares sans table : AmberELEC, MinUI, R36Droid/andr36oid (non
  proposés dans l'écran).
- Extensions en majuscules : non renommées ; leur acceptation par chaque
  firmware (comparaison sensible à la casse ou non) n'est pas vérifiée.

## Parcours et dossiers ignorés

Récursif. **Jamais descendus** :
- `_non_identifies`, `_hors_filtre`, `_doublons`, les dossiers cachés (`.xxx`) ;
- la liste par défaut du dédoublonnage (`config.py::DEFAULT_DOUBLONS_
  IGNORED_FOLDERS` : `bios`, `Imgs`, `media`, `.res`, `cubegm`…) -- sinon
  BIOS et jaquettes partiraient dans `_non_identifies` ;
- **tout dossier portant un nom de système du firmware cible**, à
  n'importe quelle profondeur, pas seulement ceux créés par l'outil :
  une collection rangée à la main n'est jamais redéplacée (listés dans
  l'aperçu, « Dossiers déjà rangés, non touchés »). Comparaison
  insensible à la casse, pour ignorer plus plutôt que moins.

Refusés d'office : racine d'un disque, dossier personnel entier (mêmes
règles que `doublons/safety.py`), dossier qui porte lui-même un nom de
système (le trier créerait `snes/snes/`), plus de 200 000 fichiers.
Conséquence : le tri ne s'applique pas à la racine d'une carte SD ; il
vise un dossier sur l'ordinateur, copié ensuite sur la carte.

## Destination libre

Par défaut les jeux sont rangés dans le dossier analysé lui-même. L'écran
permet d'en choisir un autre, n'importe où (« Choisir une autre
destination… », retour avec « Ranger sur place ») : les jeux rangés vont
dans `<destination>/<système>/`, **tout ce qui est mis de côté reste près
du dossier analysé** (`_non_identifies`, `_hors_filtre`), ainsi que le
journal -- la destination, souvent une carte, ne reçoit que des jeux.
- Toute destination acceptée, racine d'un disque comprise (les firmwares
  EmulationStation rangent à la racine de leur partition de jeux), sauf
  un dossier portant lui-même un nom de système (`snes/snes/`, motif
  `destination_system_folder`).
- Contrôle de casse fait sur les dossiers déjà présents dans la
  destination (même règle `folder_case_conflict`).
- Destination sur un autre disque (`doublons/move.py::is_cross_volume_
  destination`) : place vérifiée avant tout déplacement (« Pas assez de
  place… », rien n'est déplacé), puis chaque jeu copié, vérifié, et
  seulement ensuite retiré de la source (`_move_one_file`, chemin
  `cross_volume`).
- Le firmware ne sert qu'aux noms de dossiers : aucune carte n'est exigée.

## Filtre région / langue (fonction distincte)

`tri/filter.py` + `tri/regions.py`, d'après la convention No-Intro des noms
(« (Europe) », « (USA, Europe) », « (En,Fr,De) » ; aussi les formes
renommées par la règle des virgules, « (USA Europe) », « (En-Fr-De) »).
Régions proposées : Europe, USA, Japon, Monde ; langues : Fr, En, De, Es,
It. Au moins un critère exigé avant de parcourir le dossier.

- **N'importe quel dossier**, nom de console compris, sauf le dossier
  personnel entier. Récursif ; mêmes dossiers jamais descendus que le tri
  (`_hors_filtre`, `_non_identifies`, `bios`, cachés…).
- **Racine d'un lecteur** (`E:\`, partition de jeux d'une carte ArkOS) :
  acceptée seulement si elle appartient à un périphérique retenu par
  `safety.filter_devices` (§4.2 de `docs/claude/devices-safety.md` :
  amovible, pas le disque système, sous le seuil de taille) --
  `filter.safe_card_volume`, jamais sur l'apparence du contenu. Toute autre
  racine reste refusée (disque système, gros disque externe, détection
  impossible). L'aperçu nomme alors la carte : « EASYROMS (E:) — 1 437
  jeu(x) » (étiquette de la partition, ou nom du lecteur si elle n'en a
  pas). Vérifié sur ce PC le 2026-10-06 : `E:\` (EASYROMS, lecteur SD) →
  acceptée ; `C:\` → refusée (carte système) ; `F:\` (disque USB de
  931,5 Gio) → refusée (seuil de taille). Sur macOS/Linux, une carte est
  montée dans un sous-dossier (`/media/…/EASYROMS`), déjà accepté ; son
  nom s'affiche de la même façon.
- **Taille à côté du nom** (« EASYROMS (E:), 71.5 Go — … ») : une carte
  expose souvent plusieurs volumes, dont certains sans étiquette (le nom
  du lecteur s'affiche alors) ; la taille permet de voir lequel est choisi.
  Volume illisible depuis l'OS (partition Linux sous Windows) : nom seul.
- **Aucun jeu reconnu** dans le dossier : avertissement (« Ce dossier ne
  contient aucun jeu… choisis celui de tes jeux, souvent EASYROMS, pas
  celui du système ») au lieu d'un aperçu vide ; « Écarter » désactivé.

Essai réel (lecture seule, 2026-10-06, carte ArkOS à trois volumes, filtre
Europe) : `I:` (512 Mo, sans étiquette) et `D:` (partition Linux,
illisible) → 0 fichier, avertissement ; `E:` EASYROMS → 71 893 fichiers,
39 017 jeux, 15 179 écartés, **18 220 sans région dans le nom** (gardés) :
près de la moitié de cette collection n'a aucun tag No-Intro.
- **Seuls les jeux sont jugés** (`filter.GAME_EXTENSIONS` : extensions de
  `systems.json`, images de disque, `.bin`, `.zip`, `.7z`) : jaquettes,
  `filelist.csv`, `.txt` ne sont jamais déplacés ni listés.
- Un groupe `.m3u`/`.cue`/`.bin` est jugé sur le nom de son manifeste et
  déplacé entier.
- Aucun jeu gardé ne bouge ; aucun dossier de système n'est créé.

Règle, dans cet ordre :
1. langues écrites dans le nom + filtre langue actif → décidé par les
   langues seules (« (USA) (En,Fr) » gardé pour Fr, même sans USA coché) ;
2. **aucune région dans le nom → gardé et signalé** (catégorie « Sans
   région dans le nom, gardés » de l'aperçu), jamais écarté ;
3. filtre langue actif et **pays qui implique une langue cochée → gardé**
   (« (France) » est en français, quelle que soit la région cochée) ;
4. filtre région → gardé si une région du nom est cochée ; **un pays compte
   pour sa région large** (France, Germany, Spain, Italy, Netherlands,
   Sweden, Denmark, Portugal, UK, Russia → Europe) ; World vaut pour
   toutes ;
5. filtre langue sans langue écrite → écarté seulement si chaque région
   n'implique qu'une langue non cochée (USA/UK/Australia → En, Japan → Ja,
   Germany → De…). **Europe, World, Asia n'impliquent aucune langue : un
   « (Europe) » sans langue (souvent en français) est gardé.**

> ⚠️ **Bug corrigé, constaté sur du vrai matériel** : avec Europe +
> Français cochés, « Pokemon - Version Emeraude (France) », « Pitfall -
> L'Expédition Perdue (France) »… partaient dans `_hors_filtre`. Cause :
> le contrôle de région passait avant la langue, et un pays n'était pas
> rattaché à sa région large -- « France » n'étant pas « Europe », le jeu
> était écarté avant que « France → français » ne soit consulté. Sur la
> carte SF3000 : 70 des 75 jeux « (France) » écartés avant, 0 après.

**Formes reconnues = formes relevées**, pas une liste de mémoire. Relevé
fait le 2026-10-06 sur la carte SF3000 (12 567 jeux, 225 mentions
distinctes ; le `_hors_filtre` du test avait été annulé, vide) :

| Mentions réelles | Lues comme |
|---|---|
| `(Japan)` 2 625, `(japan)` 277, `(Europe)` 1 362, `(USA)` 1 131, `(USA Europe)` 129, `(Asia)` 69, `(World)` 44, `(Australia)`, `(Europe Australia)`, `(Brazil)`, `(Russia)`, `(Hong Kong)` | régions |
| `(France)` 75, `(Germany)` 30, `(Spain)` 22, `(Italy)` 13, `(Netherlands)` 5, `(Denmark)` 1, `(China)` 31, `(Korea)` 12, `(Taiwan)` 11 | pays |
| GoodTools : `(J)` 76, `(JP)` 16, `(j)` 3, `(U)` 14, `(US)` 3, `(u)`, `(E)`, `(EU)`, `(Euro)`, `(K)`, `(FR)` 4, `(UE)` 51, `(JUE)` 27, `(jue)` | alias de régions/pays |
| `(Europe and America)` 23, `(European and American)`, `(USA- Europe)` 6, `(Japan- USA)`, `(Asia- Australia)` | plusieurs régions |
| `(En-Fr-De-Es-It)` 291, `(En)` 85… (64 combinaisons) | langues |
| `(Chinese version)` 34 (aussi entre crochets), `(Chinese)` | langue chinoise |

Second relevé le 2026-10-07 sur la carte ArkOS 256 Go (39 059 jeux,
1 212 mentions distinctes) : codes GoodTools en plus `(JU)` 50, `(BR)` 131,
`(F)` 7, `(R)` 7, `(W)` 6, `(G)`, `(A)`, `(EJ)`, `(CH)` ; langues `(eng)`,
`(Simple Chinese)`. **Les codes d'une lettre ne sont reconnus que dans la
casse observée** (`(A)` pays, mais `[a]`/`[b]`/`[f]` = marqueurs de dump
alternatif/mauvais/corrigé) ; seuls `(j)`, `(u)`, `(jue)` ont été vus en
minuscules. Résultat sur cette carte (Europe + Français) : 175 versions
France, aucune écartée ; 6 205 gardés, 14 668 sans région, 17 303 écartés
pour la région, 883 pour la langue.

Non lues comme région (volontairement) : `(PAL)` 15 et `(NTSC)` 3
(normes vidéo), `(Unl)`, `(Rev 1)`, `(Proto)`, `(Beta)`, `(NP)`…
`(FR)` est un pays, `(Fr)` une langue : jamais d'alias pour une mention
qui a la forme d'un code de langue. Une forme absente de ce relevé reste
inconnue → jeu gardé et signalé « sans région ». Après correction, sur
cette carte (Europe + Français) : 4 111 écartés pour la région, 237 pour
la langue, 1 800 gardés, 6 419 sans région.

Écartés : déplacés dans `<dossier>/_hors_filtre/<chemin d'origine>`
(jamais parcouru ensuite ; `F:\Jeux\snes\X` → `F:\Jeux\_hors_filtre\snes\X`),
motif `region_excluded`/`language_excluded`, consignés dans
`_filtre_journal.json` -- « Annuler le filtrage » les remet en place.
Aperçu : nombre de jeux écartés, gardés, et sans région ; groupes dédiés
dans l'arbre.

Non vérifié sur une vraie collection : le taux de noms sans région ou
aux tags inhabituels (`(Europe) (Beta)`, traductions `[T-Fr]`…) est
inconnu ; `[T-Fr]` (crochets, traduction de fan) n'est **pas** lu comme
une langue.

## Déplacement et annulation

- Destination : `<destination>/<nom du système>/<fichier>` (à plat) ;
  `<dossier>/_non_identifies/<chemin d'origine>` pour les non identifiés
  (chemin conservé : un groupe `.cue`/`.bin` reste cohérent).
- **Déplacer, jamais supprimer.** Aucun écrasement : suffixe `_2` pour un
  jeu ; un groupe non identifié dont un fichier existe déjà dans
  `_non_identifies` reste en place (renommer un `.bin` casserait son
  `.cue`).
- Réutilise `doublons/move.py::_move_one_file`/`_unique_destination`.
- Journal : `<dossier>/_rangement_journal.json`, **JSON Lines** (une ligne
  par fichier, écrite au fil de l'eau) -- pas le format liste de
  `doublons/move.py`, qui réécrit tout le fichier à chaque ajout (coût
  quadratique sur des milliers de jeux). Une dernière ligne tronquée par
  une coupure est ignorée.
- Échec sur un fichier : consigné, le tri continue ; arrêt après 20
  échecs consécutifs (carte probablement retirée).
- « Annuler le rangement » : du plus récent au plus ancien, jamais
  d'écrasement (conflit signalé, entrée conservée pour un futur essai).
  Journal supprimé une fois entièrement consommé. Les dossiers créés
  restent (vides) : rien n'est supprimé.
- Confirmation : page simple dans l'écran, jamais sautée -- pas la
  fenêtre rouge, réservée aux écritures sur le périphérique brut.
- Le firmware proposé par défaut est celui choisi pour le flash
  (`AppConfig.firmware`) s'il a une table, ROCKNIX sinon ; toujours
  remplaçable.

## Points ouverts

- Table dArkOS non vérifiée sur une vraie carte (validation ArkOS en
  attente) ; ROCKNIX et EmuELEC non vérifiées.
- TreeFrogUI : affichage des jeux confirmé pour `gba`/`snes` seulement ;
  les `.7z` sont listés mais jamais lus (écran noir) : un rangement vers
  TreeFrogUI devrait refuser ou convertir les `.7z` (motif
  `extension_not_accepted`), à décider.
- Aucun essai sur une vraie collection de ROMs (signatures d'en-tête).
- BIOS mélangés aux jeux : non détectés, rangés comme des jeux. Il faut
  une liste de BIOS connus (nom/CRC), en excluant les jeux intégrés tagués
  `[BIOS]` (voir § « Les BIOS ne sont pas des ROMs »), puis les laisser en
  place ou les envoyer vers le dossier BIOS du firmware (`cubegm/bios/`
  pour TreeFrogUI ; à relever pour les autres firmwares).
