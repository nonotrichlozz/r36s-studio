# Mode assisté — accueil, parcours de clonage, flux ponctuels

À lire quand tu touches au mode assisté : `AssistedLandingScreen`, `gui/wizard_flow.py`, les méthodes `_wizard_*`/`_prepare_card_*` de `gui/main_window.py`, `WizardFingerprintRunner`, ou `safety/card_fingerprint.py`.

> Les renvois « §N » de ce texte désignent les sections de l'ancien `CLAUDE.md` monolithique (commit `930f3c9`) : §3 → `elevation-macos.md`, §4.1/§4.2 → `devices-safety.md`, §4.3 → `imaging.md`/`reset-card.md`, §4.4 → `partitions.md`, §4.5 → `detect.md`, §4.6 → `firmwares-flash.md`, §5 → `interface.md`/`assisted-wizard.md`, §6 → `packaging.md`, §8 → `testing.md` ; §1/§2/§9 restent dans `CLAUDE.md`.

> 📚 Historique détaillé (bugs corrigés, investigations) : `docs/bugs-interface.md`

**Mode assisté (phase 8), par défaut au lancement.** Le mode expert
(six étapes, ci-dessus) reste disponible en entier, mais n'est plus
l'écran de démarrage — `config.py` (première vraie implémentation de
`~/.config/r36s-studio/config.json`, §6) mémorise `ui_mode`
(`"assisted"` par défaut, `"expert"`) d'un lancement à l'autre.

**Accueil** (`gui/screens.py::AssistedLandingScreen`) : sa propre
`ConsoleStage` (instance séparée de celle de `MainView`, plus grande,
centrée — les deux écrans ne sont jamais affichés en même temps, donc
pas de conflit de parent), un bouton cyan plein « Préparer ma carte
automatiquement » (nouveau rôle `QPushButton[role="cta"]`, `theme.py`)
et un bouton discret « Mode expert » en haut à droite.

⚠️ **Corrigé : le mode expert n'avait pas de chemin de retour.** Une
fois basculé via « Mode expert », rien ne permettait de revenir à
l'accueil assisté — et `ui_mode` étant persisté (`config.py`),
l'utilisateur restait bloqué en mode expert même après redémarrage.
`HomeScreen` porte désormais le bouton symétrique « Mode assisté », en
haut à droite du titre (même ligne, pas une ligne séparée qui aurait
repoussé les six étapes) — `MainWindow._switch_to_assisted_mode`
persiste `ui_mode="assisted"` et ramène directement à
`AssistedLandingScreen` (pas de notion de parcours à reprendre côté
mode expert). Vérifié par un test qui traverse la bascule dans les deux
sens et contrôle que la configuration suit à chaque fois.

⚠️ **Garde ajoutée : les deux boutons de bascule restaient cliquables
pendant une opération disque.** Changer de mode en plein flash ou en
pleine copie laisserait un job orphelin. `HomeScreen.set_busy`
(existant, désactivait déjà les six étapes) désactive maintenant aussi
`_assisted_mode_button` ; `AssistedLandingScreen.set_busy` (nouveau,
même principe) désactive `_expert_button` — gardé défensivement même si
l'accueil n'est en pratique jamais visible pendant une opération en
cours dans le déroulé normal, sauf brièvement entre une annulation
coopérative (`_cancel_wizard`) et l'arrêt effectif du job. `MainWindow`
appelle les deux `set_busy` ensemble, à l'entrée (`_start_worker`) et à
la sortie (`_on_worker_finished`) de toute opération passant par ce
pipeline (backup/flash/extract_boot/extract_easyroms/inject_boot/
copy_games, mode expert et mode assisté confondus) — pas étendu à
l'identification (étape 2) ni au calcul d'empreinte (étapes 1/4) : ces
lectures en arrière-plan ne laissent rien d'orphelin de dangereux si le
mode change entre-temps, contrairement à une écriture.

⚠️ **Bug rapporté et corrigé : la carte semblait détectée en mode
expert mais pas en mode assisté à l'étape 1.** Diagnostic : les deux
modes appellent la même fonction (`_list_devices_with_diagnostics`, qui
encapsule `list_devices`/`filter_devices`) — il n'y a jamais eu de
filtre différent côté assisté. La vraie cause : `_on_wizard_poll`
n'acceptait de continuer que si `_list_safe_devices()` renvoyait
*exactement* un candidat ; à plusieurs (ex. un disque USB qui passe le
filtre §4.2 en plus de la carte SD), `candidate` retombait à `None` —
indiscernable de « aucune carte », d'où l'impression d'une détection
cassée alors qu'elle voyait la bonne carte, simplement noyée avec une
autre. **Corrigé** : au-delà d'un candidat, `_on_wizard_poll` arrête le
sondage et ouvre la fenêtre Choix de la carte (`DeviceDialog`, la même
qu'en mode expert) plutôt que de rester bloqué en silence ;
`_on_device_chosen` reconnaît ce contexte (étape 1/4 en cours) et
reprend directement le calcul d'empreinte sur la carte choisie, sans
toucher `self._mode`/`self._device` du mode expert.

**Bouton Rafraîchir, étapes 1/4** : symétrique de celui du mode expert
(`DeviceDialog`) — relance la recherche immédiatement (sans attendre le
tick suivant) et redémarre le sondage automatique s'il s'était arrêté,
notamment après un choix annulé dans la fenêtre Choix de la carte.

⚠️ **Correction de conception majeure : le parcours guidé à sept étapes
(identification DTB puis extraction/injection BOOT-EASYROMS, propre à
ArkOS) a été remplacé par un parcours de clonage à cinq étapes, en
image disque brute.** Le parcours à sept étapes ne fonctionnait que
pour une carte de structure ArkOS reconnaissable (BOOT/EASYROMS) — une
carte EmuELEC, ROCKNIX, ou un firmware Android nécessitait déjà des
contournements dédiés (CardSystem/ROCKNIX ci-dessous, désormais retiré
de ce module). Le nouveau parcours n'a plus cette limitation : il clone
la carte source telle quelle (`imaging.backup_device`/
`imaging.backup_system_only`) puis restaure l'image obtenue
(`imaging.flash_device`) sur la carte neuve — indépendant du firmware
installé et du système de fichiers, puisqu'aucune opération ne descend
au niveau fichier.

**Les cinq étapes** (`gui/wizard_flow.py::WizardJob`, un job par étape
visible — plus besoin qu'un même écran en recouvre deux comme
auparavant) :
1. **Détecter la carte source** — même sondage automatique
   qu'auparavant (`list_devices`/`filter_devices` par `QTimer`, 1,5 s),
   inchangé.
2. **Créer l'image** — `screens.py::BackupKindDialog` demande d'abord
   copie complète ou système seul (sans les jeux) avant d'ouvrir
   `FileDialog` pour choisir où l'enregistrer :
   - *Copie complète* (`backup --device`) : la taille annoncée avant
     même le choix du fichier est `device.size_bytes` — un majorant
     sûr sans lecture supplémentaire, puisque `backup_device` s'arrête
     toujours à la fin de la dernière partition utilisée.
   - *Système seul* (`backup --device --system-only`) : réutilise
     **tel quel** le pipeline d'estimation à deux niveaux déjà en place
     pour l'opération ad-hoc équivalente de l'accueil assisté
     (`_start_system_backup_estimate`/`SystemBackupEstimateRunner`,
     estimation non élevée d'abord, élevée en repli, §4.3) — aucune
     duplication.
3. **Détecter la carte neuve** — éjecte d'abord la carte source
   (`_run_wizard_source_eject`, logique inchangée depuis le parcours
   précédent : la carte source doit rester montée pendant l'étape 2,
   c'est de là que l'image est lue), puis sonde la nouvelle carte.
4. **Restaurer l'image** — flash direct de l'image créée à l'étape 2
   sur la carte neuve, sans aucun choix de firmware (ce n'est pas une
   nouvelle image téléchargée, c'est la propre sauvegarde de
   l'utilisateur) : `FileDialog` n'est même pas ouverte pour cette
   étape, contrairement au flash du mode expert. Fenêtre Confirmation
   obligatoire (§2 n°6) avant l'écriture réelle, jamais sautée.
5. **Éjecter** — inchangé.

`MainWindow` réutilise tel quel le pipeline `_start_worker`/
`_on_worker_finished` du mode expert (`WorkerRunner` pour `backup`/
`flash`, jamais `PartitionJobRunner` — le nouveau parcours n'écrit plus
jamais sur une partition déjà montée) — le drapeau `_wizard_active`
décide comme avant si la fin d'opération avance la machine à états ou
suit le chemin expert existant.

**Trois vérifications obligatoires avant d'écrire quoi que ce soit**
(demandées explicitement, jamais un échec après une longue copie déjà
lancée) :
1. **Espace disque libre sur l'ordinateur**, avant de créer l'image —
   `MainWindow._check_free_space_or_warn` (`shutil.disk_usage`, pré-
   contrôle rapide côté GUI, non élevé) et, en autorité réelle,
   `__main__.py::cmd_backup` (nouveau code d'erreur
   `INSUFFICIENT_DISK_SPACE`) — le worker élevé refait la même
   vérification, seule habilitée à bloquer réellement si l'estimation
   locale manque.
2. **Taille de la carte de destination ≥ taille de l'image**, avant la
   restauration — une carte plus petite tronque et corrompt la table
   GPT secondaire (déjà rencontré, §4.3 « point critique table GPT »).
   `imaging.image_source.estimate_total_bytes` (déjà existante, exacte
   et non privilégiée pour `.img`/`.img.gz`/`.img.xz`, lue depuis le
   pied du fichier sans décompression) comparée à `device.size_bytes` —
   côté GUI (`_enter_wizard_restore_image_step`, nouveau code
   `DESTINATION_TOO_SMALL`) et côté `__main__.py::cmd_flash`, même
   principe pré-contrôle/autorité que ci-dessus. `None` (pied
   tronqué/non standard, cas résiduel) laisse passer plutôt que de
   bloquer sur une estimation incertaine — `flash_device` échoue alors
   avec une vraie erreur d'écriture (ENOSPC) plutôt que de tronquer
   silencieusement.
3. **Empreinte de carte, refuse d'écrire sur la carte source** —
   `safety/card_fingerprint.py::compute_boot_fingerprint`/
   `is_same_card`, via `WizardFingerprintRunner` aux étapes 1 et 3 (même
   garde-fou qu'auparavant aux étapes 1/4). Exception délibérée et
   limitée à « aucune opération au niveau fichier » : c'est un garde-fou
   de pré-vol, pas une des deux opérations centrales du clonage
   (création/restauration), et il se dégrade sans risque — une carte
   neuve vierge ou d'un firmware différent n'a simplement aucune
   partition BOOT montable, donc pas d'empreinte (`None`), et
   `is_same_card` ne bloque jamais ce cas (le cas courant : une carte
   neuve vierge). Il ne bloque que le cas qui compte : la carte source
   encore branchée par erreur à l'étape 3.

   ⚠️ **Bug corrigé, confirmé sur du vrai matériel : ce garde-fou peut se
   désactiver silencieusement, pas seulement se dégrader sans risque.**
   Le raisonnement ci-dessus suppose que c'est toujours la carte
   *cible* qui manque d'empreinte -- faux depuis que le parcours de
   clonage clone n'importe quel firmware (§5) : si la carte *source*
   elle-même n'a pas d'empreinte (vierge, ou dont le BOOT n'est
   simplement pas reconnu), `is_same_card` ne peut plus rien affirmer et
   retourne toujours `False`, quelle que soit la carte réellement
   branchée à l'étape 3 -- le garde-fou est alors désactivé pour tout le
   reste du parcours. Combiné à une observation Windows sur du vrai
   matériel (certains lecteurs de carte gardent le même chemin de disque
   physique quelle que soit la carte insérée, la sauvegarde et le flash
   du même parcours utilisant tous deux le même chemin), le chemin seul
   ne peut pas non plus prouver qu'il s'agit de deux cartes différentes
   dans ce cas précis -- risque réel d'écrire l'image par-dessus la
   carte source elle-même si l'utilisateur ne l'a pas changée.

   (Premier correctif tenté, `is_same_card_or_unverifiable` par repli sur `device.path`, retiré : les lecteurs Realtek intégrés gardent le même `\\.\PhysicalDrive1` quelle que soit la carte — récit dans `docs/bugs-interface.md`.)

   **Corrigé pour de bon** : `safety/card_fingerprint.py::
   size_proves_different_card` (remplace `is_same_card_or_unverifiable`,
   `is_same_card` elle-même toujours inchangée) n'affirme une carte
   différente que si les deux tailles sont connues et *diffèrent* -- une
   carte ne change jamais de capacité, c'est une preuve positive fiable
   contrairement au chemin. Une taille identique, comme une empreinte
   manquante, ne prouve jamais rien dans un sens ou dans l'autre. Quand
   ni le contenu ni la taille ne peuvent trancher,
   `gui/screens.py::SameCardUnverifiedDialog` (nouvelle fenêtre modale,
   même famille que `ConfirmDialog` -- case à cocher obligatoire, fond
   "danger") exige une confirmation *explicite* de l'utilisateur plutôt
   qu'un signal automatique supplémentaire ou un blocage sans issue :
   récapitule le modèle et la taille détectés, jamais pré-cochée.
   `gui/main_window.py::_on_wizard_fingerprint_ready` l'ouvre (et arrête
   le sondage automatique, comme pour plusieurs candidats détectés) dès
   que `fingerprint is None` et qu'aucune différence de taille n'est
   prouvée ; `_on_same_card_unverified_confirmed` accepte alors la carte
   en attente (`_pending_target_candidate`) exactement comme si un
   signal automatique avait tranché. Annuler la fenêtre laisse le
   sondage arrêté (même convention que `DeviceDialog` sur plusieurs
   candidats, §5 mode assisté) -- le bouton Actualiser de l'étape 3 le
   relance. C'est délibérément le garde-fou le plus critique du
   parcours : écrire par erreur sur la carte source détruirait la seule
   copie fonctionnelle de la console de l'utilisateur.

**Ce qui est sorti du mode assisté, déplacement pas suppression** —
reste pleinement en place pour le mode expert, qui l'utilisait déjà
indépendamment du parcours guidé :
- **Identification DTB** (`identify.identify_from_boot_directory`,
  `WizardIdentifyRunner` retiré) : plus aucune étape du parcours de
  clonage n'en a besoin (indépendant du firmware). Reste accessible en
  diagnostic CLI (`python -m r36s_studio identify --boot-dir DIR`),
  inchangé — aucune UI ne l'expose plus nulle part ailleurs.
- **Extraction/injection BOOT-EASYROMS** (étapes A/B/D/E) : toujours
  utilisées par le mode expert (§4.6), qui les appelait déjà de façon
  indépendante du parcours guidé — rien n'y change.
- **`CardSystem`/ROCKNIX** (§4.5) : `detect_card_system_for_device`
  (le point d'entrée spécifique à l'ancienne adaptation du parcours
  guidé) retiré ; `CardSystem`/`detect_card_system`/`ROCKNIX_BOOT_LABEL`
  restent, toujours utilisés par `detect_workflow_status` pour les
  badges `SYSTEM_INCOMPATIBLE` du mode expert.
- **Choix du firmware au flash** (ArkOS/ROCKNIX/EmuELEC, bouton
  « Voir les versions disponibles », préselection console clone) :
  n'a plus de sens dans le parcours de clonage, qui restaure la propre
  sauvegarde de l'utilisateur, jamais une nouvelle image téléchargée.
  Reste la façon de choisir un firmware à flasher en mode expert
  uniquement (`FileDialog`).

**Erreur, à n'importe quelle étape** : le parcours s'arrête,
`LogPanel.finish_error` affiche le message clair (§5, vocabulaire),
`WizardStepPanel.show_error()` remplace le bouton Continuer par
Reprendre/Mode expert — inchangé.

**Flux ponctuels depuis l'accueil assisté** (sauvegarde système, puis « Préparer une carte avec cette sauvegarde ») :

**Proposée aussi comme option du mode assisté**, pas seulement depuis
l'écran expert (`gui/screens.py::AssistedLandingScreen`, bouton discret
sous le bouton principal) : `MainWindow._start_backup_system_from_
assisted_landing` réutilise `MainView`/`_log_panel` le temps de
l'opération, pour bénéficier du journal de bord et des états occupé
déjà en place, sans en faire un vrai changement de mode — contrairement
au bouton « Mode expert », `ui_mode` n'est ni modifié ni persisté ici.

Deux nouveaux signaux dédiés sur `WizardStepPanel`
(`prepare_card_requested`/`return_to_home_requested`, distincts de
`continue_requested`/`cancel_requested` du vrai parcours guidé) et un
drapeau d'instance, `_assisted_ad_hoc_active` (distinct de `_wizard_active`),
signalent ce contexte à `_on_worker_finished` -- réutiliser les signaux du
vrai parcours aurait avancé/corrompu son état interne pour de vrai.
« Préparer une carte avec cette sauvegarde » (`_on_prepare_card_requested`)
réutilise le fichier fraîchement créé comme source du flash (fenêtre Choix
du fichier sautée, `_skip_file_dialog_for_flash`) ; la fenêtre Confirmation
reste obligatoire avant d'écrire pour de vrai (§2 règle 6, jamais sautée).
L'écran de choix de la carte pour ce flux ponctuel réplique le mécanisme des
étapes 1/4 du vrai parcours guidé, mais avec son propre minuteur et son
propre état -- jamais `_wizard_poll_timer`/`self._wizard_flow`, qui
corromprait le vrai parcours guidé s'il tournait en parallèle :
`_prepare_card_poll_timer` sonde automatiquement, et `_prepare_card_candidate`
(`None` sauf carte unique détectée) active le bouton Continuer, vérifié par
`_on_wizard_continue` en tout premier, avant même `self._wizard_flow` -- les
deux parcours s'excluent mutuellement par construction
(`_wizard_active`/`_assisted_ad_hoc_active`).

**Exclusion mutuelle des deux parcours** (récit du bug de la mauvaise carte dans la fenêtre Confirmation dans `docs/bugs-imaging-partitions.md`) :

**Corrigé à deux niveaux** : `_start_wizard()` réinitialise désormais
`_prepare_card_candidate`/`_assisted_ad_hoc_active` (et arrête `_prepare_
card_poll_timer` s'il tournait), symétriquement à ce que `_cancel_wizard`/
`_on_assisted_ad_hoc_return_home` font déjà en sens inverse -- ces deux
parcours sont censés être mutuellement exclusifs, démarrer l'un doit
repartir d'un état propre pour l'autre. En plus, garde-fou en dernier
recours directement dans `_on_wizard_continue`/`_on_wizard_refresh_
requested` (`and not self._wizard_active` ajouté à leur condition de
routage ad-hoc) : même si un futur chemin laissait à nouveau cet état
incohérent, le Continuer/Actualiser du vrai parcours guidé ne peut plus
jamais être détourné vers le parcours ponctuel pendant qu'il tourne.

**Sondage automatique des étapes 1/3 — chien de garde** (`_check_wizard_poll_stall`, seuil `_WIZARD_POLL_STALL_THRESHOLD_SECONDS` = 6 s ; `_start_wizard_poll_timer`/`_stop_wizard_poll_timer` sont les seuls points de passage pour démarrer/arrêter `_wizard_poll_timer` et réinitialisent la référence de temps à chaque redémarrage — une pause volontaire, pendant la sauvegarde ou le calcul d'empreinte, ne compte jamais comme un arrêt). Historique des faux positifs dans `docs/bugs-interface.md`.

✅ **Question d'origine répondue** : le minuteur ne s'arrête pas réellement --
il tourne, mais chaque cycle était trop lent (§4.1, corrigé). Le chien de
garde le journalisait donc à répétition, à chaque tick, tant que le
ralentissement durait. **Corrigé** : `_wizard_poll_stall_warned` évite de
répéter la même ligne tant qu'un même épisode persiste (remis à `False`
seulement quand un sondage retrouve un rythme normal, jamais par une
relance) ; le chien de garde relance directement le minuteur (`.start()`)
plutôt que de seulement journaliser ; `_start_wizard_poll_timer`/
`_stop_wizard_poll_timer` (remplacent les appels directs `.start()`/
`.stop()` dispersés) journalisent chaque vraie transition arrêté/actif une
seule fois, jamais à chaque relance interne pendant l'attente.

⚠️ **Limite structurelle non traitée** : `_check_wizard_poll_stall` n'est
appelée que par le `timeout` du minuteur lui-même -- un minuteur réellement
arrêté ne rappellerait plus jamais cette fonction, donc ce chien de garde ne
peut détecter (ni corriger) qu'un ralentissement, jamais un arrêt complet.
Aucun cas réel de ce genre n'a été confirmé une fois le vrai ralentissement
identifié.
