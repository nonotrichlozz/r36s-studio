# Archive — contenu obsolète

> ⚠️ **Ce contenu est périmé et ne doit pas être utilisé comme référence.** Il décrit du code retiré, des comportements contredits par des correctifs ultérieurs ou des plans dépassés. Il est conservé tel quel, extrait de l'ancien `CLAUDE.md` (commit `930f3c9`), uniquement pour l'historique.

## C1 — §4.4 : message d'échec de montage selon l'OS (code retiré avec l'étape d'identification)

2. **Message différent selon l'OS pour le cas résiduel.** Même avec ce
   repli, un échec de montage reste théoriquement possible (aucun
   `AccessPaths` exploitable). `gui/main_window.py::
   _identify_failure_message_key` choisit désormais entre le message
   existant (macOS/Linux, où un échec après tentative active de montage
   reste un signal fiable de carte défaillante) et un nouveau message
   Windows (`wizard_identify_failed_mount_windows`, `gui/strings.py`)
   qui invite à débrancher/rebrancher la carte sans jamais suggérer un
   défaut matériel.

## C2 — §4.3 : estimation de la sauvegarde système, version d'origine (renvoi à une « étape 2 » disparue)

**Estimation avant de lancer, et confirmation explicite** (§5) :
`gui/partition_runner.py::SystemBackupEstimateRunner`, un thread séparé
comme les autres runners de ce module (lire la table de partitions est
rapide, mais le montage du BOOT pour l'identification du modèle peut
bloquer jusqu'à `MOUNT_WAIT_SECONDS`, §4.4) — calcule la taille estimée
(`imaging/system_backup.py::estimate_system_backup_size`, journalisée
avant l'ouverture de la fenêtre Choix du fichier) et tente, en
best-effort, d'identifier la console (même mécanisme que l'étape 2 du
mode assisté, `identify_from_boot_directory` sur le BOOT monté) pour
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

## C3 — §4.5 : `PLATFORM_LIMITED` « inconditionnellement » (contredit par le correctif exFAT)

**Statut `PLATFORM_LIMITED` (habillage « poste de commande », phase 8)** :
`copy_games` (étape E) est en NTFS sur une vraie carte R36S (§4.4) — macOS ne
monte le NTFS qu'en écriture nulle part, donc cette étape échoue toujours sur
cet OS, quelle que soit la carte branchée (ou même sans carte du tout). Ce
n'est pas une question de pertinence pour la carte (`NOT_RELEVANT`), c'est une
limite de la plateforme : `detect_workflow_status` retourne
`StepStatus.PLATFORM_LIMITED` pour `copy_games` sur macOS, inconditionnellement,
prioritaire sur le calcul habituel. L'écran d'accueil l'affiche avec un badge
orange « PC ou Linux » plutôt que les badges vert/gris habituels.

## C4 — §5 : illustrations, version d'origine (`ConsoleBasePlate`, halo animé supprimés)

**Deux illustrations décoratives, chacune avec son propre rôle
(`gui/assets/`, `gui/asset_paths.py`) :**

- **`console.png`** (`screens.ConsoleArt`, assemblée avec `screens.ConsoleBasePlate`
  dans `screens.ConsoleStage`) : la console R36S détourée, en haut de la colonne
  droite, à ~70 % d'opacité fixe peinte à la main dans `paintEvent`
  (`painter.setOpacity`, pas un `QGraphicsOpacityEffect` — ce slot d'effet est
  réservé au halo animé, voir ci-dessous).

## C5 — §6 : « Linux — AppImage » (contredit par le `.tar.gz` réellement produit)

- **Linux** — AppImage, aucun souci de signature.

## C6 — §6 : contenu supposé de `config.json` (faux)

**Fichier de configuration utilisateur** (`~/.config/r36s-studio/config.json`) : chemins
récemment utilisés, langue, seuil de taille maximale. Jamais de secret.

## C7 — §7 : feuille de route des phases 1 à 7 (terminée et dépassée)

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

## C8 — §1 : liste d'objectifs d'origine (« Flasher ArkOS », ArkOS désormais archivé)

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

## C9 — §5.1 : « la sauvegarde complète … une ligne séparée » (trois lignes aujourd'hui)

   statut guide sans jamais rien masquer. La sauvegarde complète de l'image
   disque est une ligne séparée sous un titre « Par sécurité », en dehors de
   cette liste — une opération de sécurité, pas une étape du parcours.

## C10a — §4.3 : GUI de l'ancienne case « partition de jeux » (retirée)

- Côté GUI (`gui/main_window.py`) : plus rien à faire. `_same_output_
  path`, `_last_system_backup_output_path`, la journalisation de
  diagnostic associée, et la case `ConfirmDialog._games_partition_
  checkbox` (`gui/screens.py`) ont tous été retirés -- `_start_worker`
  ne construit plus jamais ce drapeau, quel que soit le mode.

## C10b — §4.4 : retrait de `archive_records`/`ArchiveReuseDialog`

⚠️ **Correction de conception (remplace deux notes « phase 8» retirées
ici).** Les étapes A/B lettrées (extraction BOOT/EASYROMS) n'existaient
auparavant en mode assisté que comme jobs internes du parcours guidé à
sept étapes — la « visibilité des archives » (chemin annoncé dès le
début de la copie, récapitulatif de fin de parcours) et la
« réutilisation d'une sauvegarde déjà connue » (`AppConfig.
archive_records`, `screens.py::ArchiveReuseDialog`) documentées ici
n'étaient pertinentes que pour ce parcours-là. Le parcours de clonage
qui l'a remplacé (§5) est entièrement basé sur l'image disque brute —
il n'appelle plus jamais `extract_boot`/`extract_easyroms` et n'a donc
plus besoin d'aucun des deux mécanismes. `AppConfig.archive_records`/
`get_archive_record`/`set_archive_record` et `ArchiveReuseDialog` ont
été retirés en conséquence. Les étapes A/B elles-mêmes, la journalisation
de leur destination (`_start_worker`, `_EXTRACTION_MODES`) et
`archives.default_archives_dir()`/`list_archives` restent pleinement en
place pour le mode expert (§4.6), qui les utilise indépendamment
— inchangés.

## C10c — §4.5 : `CardState` retiré

### 4.5 `detect/` — statut des étapes du parcours

⚠️ **Correction de conception.** Ce module a d'abord été pensé autour d'un état
unique de la carte branchée (`CardState` : `NO_CARD`/`BLANK`/`ORIGINAL`/`ARKOS`/
`UNKNOWN`) qui décidait d'*une* action à mettre en avant. C'était incompatible
avec le vrai parcours : celui-ci enchaîne **deux cartes différentes** (l'ancienne,
puis la neuve) sur **six étapes chronologiques fixes** — un état unique de « la »
carte branchée n'a jamais de sens, puisque ce n'est jamais la même carte d'une
étape à l'autre. `CardState`/`detect_card_state` ont été retirés.

## C10d — §4.5 : adaptation ROCKNIX du mode assisté retirée

⚠️ **Correction de conception : l'adaptation « Mode assisté » décrite ici
a été retirée.** Le parcours guidé à sept étapes détectait le système de
la carte source (`detect_card_system_for_device`, stocké dans
`_wizard_source_system`) pour sauter automatiquement l'identification
DTB et l'extraction BOOT/EASYROMS sur une carte ROCKNIX, ou avertir sur
un système non reconnu — logique nécessaire uniquement parce que ce
parcours travaillait au niveau fichier (BOOT/EASYROMS), donc sensible au
firmware installé. Le parcours de clonage qui l'a remplacé (§5) clone
l'image disque brute telle quelle, quel que soit le firmware — il n'a
plus besoin de reconnaître ROCKNIX ni aucun autre système pour décider
quoi faire. `detect_card_system_for_device` (le point d'entrée
spécifique à cette adaptation) a été retiré ; `CardSystem`/
`detect_card_system`/`ROCKNIX_BOOT_LABEL` restent en place, toujours
utilisés par `detect_workflow_status` pour le mode expert (badges
`SYSTEM_INCOMPATIBLE`, ci-dessus, inchangé).

## C10e — §4.6 : orientation automatique clone/EmuELEC retirée

⚠️ **Correction de conception : l'orientation automatique décrite ici à
l'étape 2 du parcours guidé (bandeau d'avertissement, présélection
EmuELEC dans `FileDialog`) a été retirée avec le parcours à sept
étapes** (§5) — le parcours de clonage qui l'a remplacé n'identifie
plus la console (indépendant du firmware, donc de la question clone/
standard). `IdentifyResult.is_clone`/`CLONE_DTB_FILENAMES` restent
pleinement fonctionnels et testés, seule cette consommation GUI a
disparu — un clone reste détectable via la commande CLI de diagnostic
`identify` (`__main__.py::cmd_identify`, texte simple, pas le protocole
JSON Lines), qui affichait déjà ce signal indépendamment de la GUI. Le
mode expert n'a jamais eu de notion d'identification (pas d'équivalent
de l'ancienne étape 2) : cette orientation n'existait que dans le
parcours guidé, elle n'est donc reprise nulle part ailleurs.

## C10f — §5 : animations de la console retirées

✅ **Animations de la console retirées, sur demande explicite** (§5) --
`ConsoleHalo`, `ConsoleBasePlate`, la propriété `floatOffset` (console),
le `QParallelAnimationGroup` qui les pilotait et le minuteur de repeint
à 30 im/s (`_repaint_timer`) ont tous été supprimés, avec le réglage
« Animations de la console » qui permettait de les désactiver. Motif :
mesurées à 7-9 % d'un cœur au repos (§5 ci-dessus, backend `offscreen`)
et de toute façon désactivées systématiquement en usage réel -- un coût
permanent pour un agrément jamais utilisé. La console (`ConsoleArt`)
est désormais immobile, de face, à opacité fixe (70 %, inchangée) ;
`ConsoleStage` n'a donc plus besoin de réserver de marge pour une
flottaison qui n'existe plus, ni de calculer la position d'un halo/
socle qui n'existent plus non plus -- son `resizeEvent` s'en trouve
largement simplifié (centre `ConsoleArt` dans tout son rect, plus de
passe d'estimation en deux temps).

## C11a — §5 : signalement non reproduit du sondage (remplacé par sa conclusion)

⚠️ **Signalement non reproduit en isolation : le sondage automatique de
l'étape 1/4 semblerait parfois s'arrêter tout seul après un retour à
l'accueil suivi d'une relance.** Rapporté ainsi : lancement du parcours,
détection de la carte source réussie, arrivée au choix « avec ou sans
les jeux » (`BackupKindDialog`), retour à l'accueil (bouton Annuler de
cette fenêtre), relance (« Préparer ma carte automatiquement ») — le
journal affiche alors « 0 carte(s) retenue(s) » et reste sur ce statut
jusqu'à un clic manuel sur Rafraîchir, qui retrouve aussitôt la carte
(toujours branchée, jamais débranchée entre-temps). Signalé comme
potentiellement « même famille » que le bug d'état périmé
`_prepare_card_candidate` corrigé plus haut (§4.3/§5, un signal ou un
drapeau d'un passage précédent contaminant le suivant).

**Relu et rejoué sans trouver de défaut dans ce chemin précis.**
`_start_wizard` (appelé par « Préparer ma carte automatiquement »)
réinitialise sans exception tout l'état du parcours --
`_wizard_flow.reset()`, `_wizard_source_device`/`_wizard_target_device`/
`_wizard_backup_kind`/`_wizard_estimated_backup_bytes`,
`_wizard_last_poll_diagnostic`, `_pending_target_candidate`, et l'état ad
hoc `_prepare_card_candidate`/`_assisted_ad_hoc_active` -- avant
d'appeler inconditionnellement `_enter_wizard_job(DETECT_SOURCE)`, qui
démarre `_wizard_poll_timer` sans condition. `_cancel_wizard` (câblé au
bouton Annuler de `BackupKindDialog`, `cancelled.connect(self.
_cancel_wizard)`) arrête proprement ce même minuteur et bascule vers
l'accueil assisté, sans rien laisser d'incohérent pour la relance
suivante. Un test dédié
(`tests/test_gui_main_window.py::
test_wizard_relaunch_after_cancelling_backup_kind_dialog_restarts_poll_and_immediately_redetects_the_device`)
rejoue exactement cette séquence (détection, Continuer, annulation
depuis `BackupKindDialog`, relance, sondage) et retrouve la carte dès le
premier sondage suivant la relance, sans clic sur Rafraîchir -- ce
chemin précis fonctionne correctement dans ce test.

L'hypothèse initiale du `WizardFingerprintRunner` resté en vol (un
ancien calcul d'empreinte, lancé sur un thread séparé, qui livrerait son
résultat après coup et arrêterait à tort le minuteur relancé) a été
écartée : pour atteindre `BackupKindDialog`, l'empreinte de l'étape
DETECT_SOURCE doit déjà avoir abouti (Continuer n'est activé qu'une fois
`_on_wizard_fingerprint_ready` reçu) -- aucun calcul n'est donc encore en
vol au moment de l'annulation dans ce scénario précis. Un démontage
résiduel du BOOT par `compute_boot_fingerprint` a aussi été écarté :
`unmount_forced` est un no-op pour un montage Windows normal (déjà
documenté ailleurs dans ce fichier).

**Note secondaire du signalement, probablement pas un bug distinct** :
les lignes de périphériques écartés identiques à deux horodatages
espacés de plusieurs minutes ne trahissent pas nécessairement un défaut
du dédoublonnage (`_log_wizard_detection_diagnostic`, qui compare une
signature `(accepted_count, rejected_lines)` au dernier sondage) --
`_wizard_last_poll_diagnostic` est remis à `None` par `_start_wizard` à
chaque relance, donc deux relances distinctes reproduisent légitimement
une fois chacune le même contenu, sans que le dédoublonnage ait failli
au sein d'une même relance.

**Diagnostic ajouté en attendant, pas encore un correctif** (le vrai
mécanisme reste à confirmer sur du vrai matériel, puisqu'il ne se
reproduit pas ici) : `MainWindow._check_wizard_poll_stall`, appelée en
tout premier dans `_on_wizard_poll`, retient l'horodatage
(`time.monotonic`) de chaque sondage réellement exécuté
(`_wizard_last_poll_monotonic`, remis à `None` par `_start_wizard` comme
le reste de cet état) et journalise un avertissement explicite si l'écart
avec le sondage précédent dépasse largement l'intervalle normal de 1,5 s
(seuil `_WIZARD_POLL_STALL_THRESHOLD_SECONDS`, 6 s -- large marge pour ne
jamais confondre une latence normale de l'OS avec un arrêt réel du
minuteur). Si cette ligne apparaît au prochain test réel juste avant le
« 0 carte(s) retenue(s) » qui a motivé ce signalement, le minuteur
s'arrête bien réellement de sonner (à chercher alors du côté d'un
comportement Qt propre au vrai matériel, non reproductible hors écran) ;
si elle n'apparaît jamais alors que le blocage se reproduit, le minuteur
tourne mais `list_devices()`/`filter_devices()` retourne réellement zéro
carte pendant cette fenêtre -- pointant plutôt vers une latence
d'énumération disque côté OS après le montage/démontage du BOOT pour
l'empreinte (§4.4), à traiter alors par une retenue/un nouvel essai côté
`devices/windows.py`, pas ici.

## C11b — renvois « 📚 Historique détaillé » répétés (un seul renvoi par fichier désormais)

> 📚 Historique détaillé (bugs corrigés, investigations) : [docs/bugs-architecture.md](docs/bugs-architecture.md)

> 📚 Historique détaillé : [docs/bugs-devices-partitions.md](docs/bugs-devices-partitions.md)

> 📚 Historique détaillé (verrouillage Windows, macOS, formats acceptés) :
> [docs/bugs-imaging-io.md](docs/bugs-imaging-io.md)

> 📚 Historique détaillé de cette investigation (diagnostic en plusieurs
> temps, vérification indépendante) : [docs/bugs-imaging-partitions.md](docs/bugs-imaging-partitions.md)

> 📚 Historique détaillé (deux défauts corrigés lors de la mise au point de
> ce flux ponctuel) : [docs/bugs-imaging-partitions.md](docs/bugs-imaging-partitions.md)

> 📚 Historique détaillé : [docs/bugs-imaging-partitions.md](docs/bugs-imaging-partitions.md)

> 📚 Historique détaillé : [docs/bugs-devices-partitions.md](docs/bugs-devices-partitions.md)

> 📚 Historique détaillé : [docs/bugs-jobs.md](docs/bugs-jobs.md)

> 📚 Historique détaillé (refonte de navigation, affichage des tailles, animations
> de la console ajoutées puis retirées) : [docs/bugs-interface.md](docs/bugs-interface.md)

> 📚 Historique détaillé : [docs/bugs-interface.md](docs/bugs-interface.md)

> 📚 Historique détaillé : [docs/bugs-packaging.md](docs/bugs-packaging.md)
