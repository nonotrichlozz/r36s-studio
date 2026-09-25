# `jobs` et firmwares — les opérations A→F et le choix du firmware

À lire quand tu touches aux six opérations A→F, au catalogue de firmwares (`identify/firmware_catalog.py`), au téléchargement ROCKNIX, à la détection des consoles clones ou aux avertissements après flash.

> Les renvois « §N » de ce texte désignent les sections de l'ancien `CLAUDE.md` monolithique (commit `930f3c9`) : §3 → `elevation-macos.md`, §4.1/§4.2 → `devices-safety.md`, §4.3 → `imaging.md`/`reset-card.md`, §4.4 → `partitions.md`, §4.5 → `detect.md`, §4.6 → `firmwares-flash.md`, §5 → `interface.md`/`assisted-wizard.md`, §6 → `packaging.md`, §8 → `testing.md` ; §1/§2/§9 restent dans `CLAUDE.md`.

> 📚 Historique détaillé (bugs corrigés, investigations) : `docs/bugs-jobs.md`

⚠️ **Correction de conception** : cette table ne listait à l'origine que quatre
opérations, en supposant que l'utilisateur disposait déjà des fichiers BOOT et
EASYROMS à injecter. Le vrai parcours à deux cartes (§4.4/§4.5) en compte six,
dans cet ordre chronologique fixe (A→F) :

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

**Choix du firmware (phase 8, catalogue élargi en phase 10), étape C du
mode expert uniquement** — le parcours de clonage du mode assisté n'a
pas de choix de firmware, il restaure la propre sauvegarde de
l'utilisateur (§5). L'étape de flash construit ses boutons radio
dynamiquement depuis un catalogue centralisé,
`identify/firmware_catalog.py::FIRMWARE_CATALOG` (`FirmwareEntry` : id,
clés de titre/description, statut, `is_clone_safe`, `releases_url`
optionnel), plutôt que des branches à trois choix codées en dur
(`gui/screens.py::FileDialog`) — nécessaire dès qu'on dépasse trois
entrées, chaque branchement en dur devenant un endroit de plus où un
nouveau firmware peut être oublié en silence (cas réel trouvé en lisant
ce code avant l'élargissement : le bouton « Voir les versions
disponibles » retombait déjà silencieusement sur l'URL ArkOS pour tout
firmware non reconnu — corrigé au passage, `main_window.py::
_on_releases_requested` n'ouvre plus rien pour un id absent du
catalogue). Sept entrées : **ArkOS / dArkOS** (archivé), **ROCKNIX**
(maintenu), **EmuELEC** (expérimental, consoles clones), **AmberELEC**,
**MinUI**, **R36Droid** et **andr36oid** (ces quatre derniers
expérimentaux — voir plus bas). Chaque entrée affiche une pastille de
statut *maintenu*/*archivé*/*expérimental* (`gui/theme.py`, réutilise
les couleurs vert/gris-bleu/orange déjà en place pour les pastilles
d'étape — une seule couleur d'accent, §5). Le choix est mémorisé d'un
lancement à l'autre (`config.py::AppConfig.firmware`, `_VALID_FIRMWARES`
dérivé du catalogue plutôt qu'un second ensemble à resynchroniser à la
main). Défaut : **ROCKNIX** (`DEFAULT_FIRMWARE`), pas ArkOS — un vrai
changement de comportement pour toute installation qui n'a jamais
choisi explicitement de firmware, volontaire puisqu'ArkOS est désormais
archivé (ci-dessous) et ROCKNIX la seule entrée maintenue.

**ArkOS archivé** : le projet officiel est figé en lecture seule
depuis décembre 2025 ; la version communautaire pour R36S (dArkOS,
`southoz/dArkOSRE-R36`) reste installable et est celle vers laquelle
pointe déjà le bouton de téléchargement — reste choisissable, jamais
retiré du catalogue, seul son statut affiché change.

**Nouvelles entrées (phase 10), toutes en lien manuel comme ArkOS —
aucune n'a de téléchargement automatique.** Vérifié individuellement
sur les pages de releases GitHub réelles avant l'ajout (même discipline
« confirmé » que le reste de ce document) : ni AmberELEC ni EmuELEC
n'ont d'assets RK3326/R36S attachés à leurs releases officielles
(AmberELEC : uniquement des images taguées RG351/RG552 ; EmuELEC :
uniquement des images Amlogic) — ni l'une ni l'autre n'a donc la
structure « une image par SoC » qui rend le téléchargement automatique
de ROCKNIX possible (ci-dessous). Conséquence directe : **pas de
nouveau module de téléchargement automatique pour AmberELEC** malgré
une hypothèse initiale en sens contraire — corrigée avant
implémentation plutôt qu'après coup. MinUI : le dépôt officiel
(`shauninman/MinUI`) ne prend pas en charge la R36S ; le portage actif
vit dans un fork communautaire (`Turro75/MyMinUI`) — utilisé à la place
comme URL de releases. R36Droid/andr36oid : deux portages Android
(LineageOS) indépendants pour R36S/RK3326, communautaires,
compatibilité non officiellement confirmée par leurs projets
respectifs — descriptions honnêtes sur cette incertitude plutôt qu'une
promesse non vérifiée.

Les deux dépôts ne se prêtent pas au même traitement, ce qui explique la
dissymétrie entre les deux options :
- **dArkOS** (`identify/releases.py`) : les images ne sont pas hébergées
  sur GitHub (elles renvoient vers Mega, Google Drive, OneDrive, un
  torrent) — comportement inchangé, le bouton se contente d'ouvrir
  `https://github.com/southoz/dArkOSRE-R36/releases` dans le navigateur,
  l'utilisateur télécharge et choisit le fichier lui-même.
- **ROCKNIX** (`identify/rocknix.py`) : le dépôt
  (`https://github.com/ROCKNIX/distribution/releases`) attache ses
  images directement à chaque release GitHub — le téléchargement
  automatique est donc possible. Le module interroge l'API GitHub
  (`/releases/latest`), sélectionne les assets dont le nom contient
  `rk3326` (le SoC de la R36S — ROCKNIX publie une image par SoC,
  partagée par toutes les consoles qui l'utilisent, pas une image par
  modèle de console), et cherche la somme de contrôle propre à chacun.
  Le téléchargement lui-même se fait par blocs avec progression réelle
  et annulation coopérative (même principe que `imaging/copy.py`), sur
  un thread séparé (`gui/partition_runner.py::RocknixDownloadRunner`) —
  un appel réseau bloquant sur le thread Qt principal se lirait comme un
  gel de l'interface, même piège que le montage d'une partition (§4.4).
  Enregistré dans `~/Documents/R36S Studio/Firmwares/`
  (`identify/rocknix.default_firmware_downloads_dir`, même convention
  que `partitions/archives.py`, jamais `~/.config`, §6). Un
  téléchargement réussi enchaîne directement sur la fenêtre Confirmation
  (§5), exactement comme un fichier choisi manuellement — le pipeline de
  flash existant n'a pas besoin de distinguer les deux origines.

✅ **Nommage des assets vérifié contre une vraie release ROCKNIX**
(2026-08-01), après une hypothèse initiale non confirmée (précédente
version de cette note). Pour le RK3326, trois fichiers : deux images
(`ROCKNIX-RK3326.aarch64-20260801-a.img.gz` et `...-b.img.gz`) et une
archive du système de fichiers plutôt qu'une image disque
(`ROCKNIX-RK3326.aarch64-20260801.tar`) — chaque image a son propre
`.sha256` du même nom (`{image}.sha256`), pas un fichier de sommes
partagé par la release comme envisagé initialement. **Corrigé en
conséquence** :
- `select_r36s_assets` (pluriel — remplace `select_r36s_asset`) ne
  retient que les `.img.gz` contenant `rk3326`, et exclut explicitement
  `.tar` et `.sha256`/`.sha256sum` même quand leur nom matche aussi —
  les extensions génériques `.img.xz`/`.img.zip`/`.img` de la première
  version n'ont jamais été observées sur une vraie release ROCKNIX et
  ont été retirées plutôt que laissées comme hypothèse invérifiée.
- Les deux variantes `-a`/`-b` sont **toutes les deux** remontées à la
  GUI — leur différence n'est pas connue, et rien n'indique laquelle
  serait la bonne par défaut. `select_r36s_assets` ne tranche donc
  jamais tout seul : `gui/partition_runner.py::RocknixListRunner`
  interroge l'API (thread séparé, même principe que les autres runners
  de ce module) puis `screens.py::RocknixVariantDialog`
  affiche le nom de fichier complet de chaque variante trouvée pour que
  l'utilisateur choisisse en connaissance de cause — `MainWindow`
  enchaîne alors sur `RocknixDownloadRunner` avec l'asset et la somme
  de contrôle correspondants à ce choix précis. **Idée future, pas
  implémentée** : élucider la différence entre `-a` et `-b` (à partir
  des notes de release ROCKNIX, ou en la demandant directement au
  projet) pour, si elle s'avère pertinente pour la R36S précisément,
  remplacer ce choix manuel par une sélection automatique ou une
  description plus parlante que le nom de fichier brut.

**Consoles clones et EmuELEC (phase 9), critère validé par l'outil
officiel ArkOS.** Certaines cartes vendues comme R36S sont en réalité
des clones (matériel RK3326 différent) sur lesquels les images ArkOS et
ROCKNIX standard ne démarrent pas — EmuELEC, lui, fonctionne (structure
relevée sur du vrai matériel : partition de démarrage FAT32 étiquetée
EMUELEC de 1,1 Go contenant `KERNEL`/`SYSTEM`/`boot.ini`/`extlinux/`,
partition Linux de 5,4 Go, partition de jeux en FAT32 de 25,5 Go — donc
inscriptible depuis macOS, contrairement au NTFS d'ArkOS/§4.4).

Le critère de détection est le **nom** du fichier `.dtb` présent sur le
BOOT, pas son contenu : `rk3326-evb-lp3-v12-linux.dtb` désigne un clone,
tandis que `rk3326-r35s-linux.dtb`/`gameconsole-r36s.dtb` désignent une
R36S/R35S standard — confirmé y compris pour une carte relevée avec deux
`.dtb` au contenu strictement identique (un seul portant le nom du
clone, §4.4 « BOOT en GPT/EFI » ci-dessus, la même carte). `identify/
__init__.py::CLONE_DTB_FILENAMES` (ensemble, pas une chaîne unique, pour
accueillir d'autres clones sans changer la forme du module) est comparé
à tous les `.dtb` trouvés par `identify_from_boot_directory` —
indépendamment du `.dtb` retenu pour l'identification normale (`info`,
premier `.dtb` valide en tri alphabétique, qui peut très bien ne pas
être celui qui nomme le clone) et indépendamment de la validité de
parsing (un `.dtb` illisible dont le nom correspond est quand même
détecté comme clone). `IdentifyResult.is_clone` porte ce signal.

**EmuELEC comme entrée du catalogue** (`identify/firmware_catalog.py`,
`is_clone_safe=True` — seule entrée à porter ce signal) : même
comportement que les autres entrées en lien manuel (bouton ouvrant
`identify/releases.py::EMUELEC_R36S_RELEASES_URL` dans le navigateur —
aucune correspondance d'assets par SoC vérifiée à ce jour pour EmuELEC,
contrairement à ROCKNIX, donc pas de téléchargement automatique).
Choisissable à tout moment, indépendamment d'une détection de clone.

**Retiré, ne pas réintroduire** : l'orientation automatique vers EmuELEC à l'étape 2 de l'ancien parcours guidé. `IdentifyResult.is_clone`/`CLONE_DTB_FILENAMES` restent fonctionnels et exposés par la commande CLI `identify`.

⚠️ **Signalé, corrigé : après un flash Android (R36Droid/andr36oid),
Windows affiche une boîte « Vous devez formater le disque » par
partition Android illisible (quatre observées) -- un débutant risque
d'accepter et de détruire ce qui vient d'être écrit.** Cause : ces
firmwares utilisent des partitions (boot/system/vendor/userdata...)
qu'aucun pilote Windows ne sait lire, et Windows propose de les
formater dès qu'il les découvre -- ce qui arrive dès que `prepared_
write_target` relâche le disque en fin d'écriture (§4.3,
`IOCTL_DISK_UPDATE_PROPERTIES`, qui force justement Windows à
redécouvrir les partitions).

**Corrigé en deux temps, complémentaires plutôt qu'exclusifs (les deux
options envisagées ont été retenues) :**
1. **Éjection automatique**, dans le worker élevé lui-même
   (`__main__.py::cmd_flash`, nouveau `--eject-after`) -- appelée juste
   après l'écriture et la vérification, dans le même processus déjà
   élevé (aucune invite supplémentaire), pour réduire la fenêtre
   pendant laquelle Windows peut proposer de formater. Best-effort : un
   échec d'éjection ne remet jamais en cause le flash déjà réussi
   (seulement journalisé). `gui/main_window.py::_start_worker` l'ajoute
   à l'argv du flash uniquement quand `_is_flashing_android_firmware()`
   est vrai (mode expert, jamais le parcours de clonage du mode
   assisté, qui n'a pas de choix de firmware) ; `_on_worker_finished`
   masque alors le bouton Éjecter du succès (déjà fait, redondant).
   **Non garanti de gagner la course contre Windows** (non vérifié sur
   du vrai matériel, aucune image Android disponible ici) -- l'éjection
   a lieu dès que possible côté application, mais rien ne garantit
   qu'elle précède la notification système.
2. **Message explicite dans le journal**, systématique, que l'éjection
   automatique ait réussi ou non -- le vrai filet de sécurité, puisque
   l'éjection automatique ne protège que la session en cours : la même
   carte rebranchée plus tard, sur n'importe quelle machine Windows,
   déclenchera exactement les mêmes propositions de formatage (les
   partitions restent tout aussi illisibles). Contrairement au reste de
   l'interface (§5, jamais de jargon), ce message nomme volontairement
   le vrai texte de la fenêtre Windows (« Vous devez formater le
   disque… ») -- même principe que `HelpDialog` pour les réglages macOS,
   §3 : une vraie fenêtre système à laquelle réagir correctement, pas
   la description d'une action de l'app. `identify/firmware_catalog.py::
   FirmwareEntry.is_android` (nouveau champ, `True` pour `r36droid`/
   `andr36oid` seulement) porte ce signal.

⚠️ **Signalé, corrigé : le correctif ci-dessus était trop étroit --
Windows propose aussi de formater la carte après un flash "Linux"
(ArkOS/ROCKNIX/EmuELEC/AmberELEC/MinUI), pas seulement Android, jusqu'à
cinq boîtes observées au total selon le firmware.** Cause : ces
firmwares aussi utilisent au moins une partition (le système ext4
"root", §4.4) qu'aucun pilote Windows ne sait lire -- une seule boîte
pour eux contre plusieurs pour Android (boot/system/vendor/userdata...),
mais le même risque exact : un débutant qui accepte de formater détruit
la carte qu'il vient de préparer. Aucune entrée du catalogue
(`identify/firmware_catalog.py::FIRMWARE_CATALOG`) n'est donc à l'abri
de ce problème -- filtrer sur `is_android` comme le faisait le premier
correctif laissait tout le reste du catalogue sans aucune protection.

**Corrigé** en généralisant le mécanisme existant plutôt qu'en le
dupliquant pour "Linux" séparément : `gui/main_window.py::MainWindow.
_flash_may_trigger_windows_format_prompt` (nouvelle méthode, même
emplacement et même forme que `_is_flashing_android_firmware`) renvoie
vrai pour **tout** flash mode expert, quel que soit le firmware --
puisqu'aucune entrée du catalogue n'est jamais entièrement lisible par
Windows, pas besoin d'y filtrer par identifiant comme pour Android.
`_is_flashing_android_firmware` reste utilisée séparément, mais
uniquement pour choisir *quel message* afficher (détaillé pour Android,
ci-dessus, générique sinon) -- plus pour décider *si* le mécanisme
s'applique.
- `_start_worker` ajoute désormais `--eject-after` dès que `_flash_may_
  trigger_windows_format_prompt()` est vrai (auparavant : seulement
  `_is_flashing_android_firmware()`) -- couvre donc aussi ROCKNIX/ArkOS/
  EmuELEC/AmberELEC/MinUI, en plus de R36Droid/andr36oid.
- `_on_worker_finished` masque le bouton Éjecter du succès dans les
  mêmes conditions élargies (`allow_eject = ... and not format_prompt_
  flash`), et journalise un nouveau message générique,
  `gui/strings.py::flash_format_prompt_warning_generic` (« Windows va
  peut-être proposer de formater la carte — refuse, c'est normal. »),
  pour tout flash non-Android concerné -- le message Android détaillé
  (mécanisme des écrans de rechange compris, ci-dessous) reste propre à
  Android, `elif format_prompt_flash` évitant les deux messages à la
  fois pour un même flash.

Toujours sans effet sur le parcours de clonage du mode assisté
(`_flash_may_trigger_windows_format_prompt` renvoie faux dès que
`_wizard_active` est vrai, comme `_is_flashing_android_firmware`) --
celui-ci éjecte déjà automatiquement la carte neuve à l'étape 5
(`_run_wizard_eject`), immédiatement après la restauration, quel que
soit le contenu de l'image clonée : un second mécanisme y ferait double
emploi. **Non vérifié sur du vrai matériel au moment d'écrire cette
note** pour le cas "Linux" précisément (le cas Android l'était déjà,
ci-dessus, avec la même réserve sur la course contre Windows) -- couvert
par des tests qui vérifient l'argv du worker et le contenu du journal,
pas une vraie élévation Windows.

⚠️ **Constaté en usage réel : une image Android flashée démarre parfois
sur un écran figé si l'écran choisi ne correspond pas à celui de la
console -- le mécanisme de rechange existe déjà côté firmware, mais rien
ne l'indiquait dans l'app avant ce correctif.** Ces portages (R36Droid/
andr36oid) embarquent un dossier `Panels/` sur le BOOT, un sous-dossier
par type d'écran, chacun contenant les `.dtb` à copier à la racine du
BOOT pour changer d'écran -- exactement le même genre de fichier que
celui déjà lu par `identify/dtb.py` pour reconnaître le modèle de
console (§4.5), mais ici c'est l'utilisateur qui doit le copier à la
main, l'app n'automatise rien de ce mécanisme. Sans explication, un
débutant qui obtient un écran figé au premier démarrage conclut que le
logiciel ne marche pas, alors que le flash a en réalité réussi -- il
manque juste le bon écran.

**Corrigé** : un second message, `gui/strings.py::
flash_android_panel_mismatch_warning`, s'ajoute désormais dans le
journal juste après l'avertissement sur les boîtes de formatage
ci-dessus (`_on_worker_finished`, même bloc `if android_flash`) --
explique le dossier `Panels/` et le fait de copier les `.dtb` à la
racine du BOOT, précise qu'il faut parfois plusieurs essais, et ne
promet jamais que ça marchera : **sur la console de test, les trois
écrans compatibles annoncés pour cette carte
(`rockchip,rk3326-rg351mp-linux` -- Panel1, Panel2/3, Panel4) ont tous
échoué**, aucun n'a produit d'affichage. Message volontairement prudent
en conséquence -- une piste à essayer, jamais une garantie.

**Idée future, pas implémentée** : ROCKNIX fournit un script
`importpanel.py` qui génère un `mipi-panel.dtbo` à partir d'un `.dtb`
d'origine (le même type de fichier que celui déjà lu par
`identify/dtb.py` pour reconnaître le modèle de console, §4.5/§5 étape
2). Une fois la console identifiée par notre module `identify`, on
pourrait imaginer une fonction ultérieure qui invoque `importpanel.py`
sur le `.dtb` extrait à l'étape A pour produire automatiquement l'overlay
d'écran ROCKNIX correspondant — mais ceci reste une piste, à explorer
seulement si l'utilisateur en a besoin.

⚠️ **Investigation close, à ne pas rouvrir sur la seule base d'un écran figé** :
sur la console de test utilisée pour ce projet, le build R36Droid/andr36oid
testé ne démarre pas du tout, quel que soit l'écran choisi parmi les huit
variantes de `Panels/` compatibles — le blocage survient avant même
l'initialisation USB du noyau (confirmé : aucun périphérique `adb`, ni même
en échec, pendant le freeze). Ce n'est donc pas un problème de sélection
d'écran pour ce firmware sur ce matériel précis ; ne pas présenter une future
automatisation du choix de panneau comme la réponse à un simple écran figé
sans d'abord exclure ce cas.
