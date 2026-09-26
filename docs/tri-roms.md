# Outil « Ranger mes jeux » (tri de ROMs par système)

Objectif : répartir un dossier de ROMs mélangées dans des sous-dossiers
par console, nommés comme le firmware cible les attend, prêts à copier
sur la carte.

Code : `r36s_studio/tri/` (sans Qt), écran `gui/tri_screen.py` (autonome,
pages et threads internes), threads `gui/tri_runner.py`. Ligne « Ranger
mes jeux » de la section « Outils » du mode expert, à côté de « Chercher
les doublons » (retirés de l'accueil assisté, allégé pour le néophyte).
Tests : `tests/test_tri_*.py`, `tests/test_gui_tri_screen.py`.

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
- `_non_identifies`, `_doublons`, les dossiers cachés (`.xxx`) ;
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

## Déplacement et annulation

- Destination : `<dossier>/<nom du système>/<fichier>` (à plat) ;
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
- TreeFrogUI : affichage des jeux confirmé pour `gba`/`snes` seulement.
- Aucun essai sur une vraie collection de ROMs (signatures d'en-tête).
