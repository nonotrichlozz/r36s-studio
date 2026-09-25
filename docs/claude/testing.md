# Tests — règles détaillées et bancs de test

À lire quand tu écris ou débogues des tests, ou quand tu testes sur du vrai matériel.

> Les renvois « §N » de ce texte désignent les sections de l'ancien `CLAUDE.md` monolithique (commit `930f3c9`) : §3 → `elevation-macos.md`, §4.1/§4.2 → `devices-safety.md`, §4.3 → `imaging.md`/`reset-card.md`, §4.4 → `partitions.md`, §4.5 → `detect.md`, §4.6 → `firmwares-flash.md`, §5 → `interface.md`/`assisted-wizard.md`, §6 → `packaging.md`, §8 → `testing.md` ; §1/§2/§9 restent dans `CLAUDE.md`.

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
