# Historique des bugs corrigés — Imaging : tables de partitions (§4.3 de CLAUDE.md)

> Ce fichier contient l'historique des investigations et correctifs liés à la
> manipulation des tables de partitions : troncature/réparation GPT et MBR
> pour la sauvegarde système sans les jeux, création automatique de la
> partition de jeux après restauration, et « Remettre la carte à zéro ». Pour
> la copie bloc par bloc elle-même (verrouillage Windows, montage macOS), voir
> [docs/bugs-imaging-io.md](bugs-imaging-io.md). Le comportement **actuel**
> est décrit dans `CLAUDE.md` §4.3.

---

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


---

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


---

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


---

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


---

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


---

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


---

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


---

✅ **Confirmé sur du vrai matériel, avec le détail exact de l'échec**
(§5, ce qui a motivé la validation manuelle) : sans cette réparation,
`gdisk` signale « Disk size is smaller than the main header indicates »
et « Backup header: ERROR », Linux ne voit aucune partition, et la
console ne démarre pas à partir de l'image — la simple troncature ne
suffit pas, exactement le risque anticipé ci-dessus. Le correctif
manuel effectué pour confirmer (supprimer l'entrée de la partition 3
puis réécrire la table) est exactement ce qu'automatise `backup_
system_only`.

⚠️ **Bug corrigé, confirmé sur du vrai matériel : l'image produite
restait inbootable même une fois l'en-tête GPT lui-même réparé --
observé identiquement sur macOS et sur Windows, pas un défaut du chemin
Windows.** Rapporté indépendamment de toute carte cible (l'image seule,
testée avec `gdisk -l image.img`, sans jamais être flashée) : le symptôme
exact déjà documenté ci-dessus (« Disk size is smaller than the main
header indicates ») persistait. Vérification demandée en trois points --
réponses trouvées en relisant le code :
1. **La réparation est-elle réellement exécutée ?** Oui --
   `backup_system_only` appelle bien `_rewrite_gpt_tables_after_
   truncation` juste après la copie tronquée, structurellement, à chaque
   appel GPT ; `cmd_backup` (`__main__.py`) route bien `--system-only`
   vers `backup_system_only`, jamais vers `backup_device`. Pas le
   problème.
2. **Les tests portent-ils sur des tables factices plutôt que sur une
   image réellement produite ?** Non pour le test de cohérence GPT
   existant (`test_backup_system_only_gpt_output_has_a_consistent_
   partition_table`) -- il appelle bien `backup_system_only` bout en
   bout et reparse le fichier produit. Mais un vrai trou : ce test ne
   vérifiait *jamais* le MBR protecteur (LBA0), seulement l'en-tête GPT
   et ses tableaux d'entrées.
3. **Le cas d'une carte cible plus petite que la source est-il traité ?**
   Question mal ciblée par la carte cible -- le symptôme est dans le
   *fichier image* lui-même, avant toute restauration : `gdisk -l` sur
   l'image seule échoue déjà, indépendamment d'où elle serait ensuite
   flashée. (La vérification taille-cible-vs-image, § pré-vol n°2 du
   parcours de clonage, est un problème séparé, déjà traité.)

**Cause réelle, trouvée grâce au point 2** : `_rewrite_gpt_tables_after_
truncation` corrige bien l'en-tête GPT (primaire et secondaire) et ses
tableaux d'entrées, mais ne touche jamais LBA0 -- le MBR protecteur qui
y vit continuait donc de décrire la taille du disque *d'origine* (ex.
128 Go pour une carte R36S typique) alors que le fichier produit n'en
fait plus que 8-9 Go. `gdisk` (et tout outil qui valide la cohérence
entre le MBR protecteur et la taille réelle du disque) signale cette
incohérence -- exactement le symptôme rapporté, persistant même une fois
l'en-tête GPT proprement réparé. Explique aussi pourquoi le symptôme est
identique sur les deux OS : ce code est entièrement commun (`imaging/
system_backup.py`), rien de spécifique à une plateforme.

**Corrigé** : `_repair_protective_mbr_after_truncation` (nouvelle
fonction, appelée juste après `_rewrite_gpt_tables_after_truncation`
dans `backup_system_only`) recalcule le compte de secteurs du créneau
MBR protecteur (type `0xEE`, retrouvé via `parse_mbr` plutôt que supposé
au créneau 0) à partir de la taille réelle du fichier produit (fin de la
copie tronquée + table secondaire, même formule qu'`estimate_system_
backup_size`). Reconstruit LBA0 à partir de `source` (lisible) plutôt
que `destination` (écriture seule), même principe que `_repair_mbr_
table_after_truncation` pour le cas MBR pur. **Trou de test fermé** :
`test_backup_system_only_gpt_updates_protective_mbr_sector_count`
(`tests/test_imaging_system_backup.py`) vérifie ce champ précis sur la
même image produite bout en bout -- confirmé qu'il échoue sans le
correctif (533 secteurs, la taille du disque source factice, au lieu des
266 attendus) avant d'être vérifié à nouveau après.

**Vérification supplémentaire, entièrement indépendante des fonctions
testées** (le symptôme persistait, rapporté à nouveau après ce premier
correctif -- « aucune image `--system-only` n'a jamais démarré une
console », sur macOS comme sur Windows identiquement). Risque identifié
dans les tests ci-dessus : `_build_fake_gpt_image` (la fixture qui
construit le disque source factice) réutilise `build_gpt_header`/
`build_gpt_entries` -- les mêmes fonctions que celles réparées et
vérifiées ici. Un bug systématique dans ces fonctions de construction
pourrait en principe se retrouver identique dans le disque source *et*
dans la réparation, invisible à toute comparaison entre les deux.
`test_backup_system_only_gpt_output_survives_fully_independent_
structural_verification` (même fichier) reconstruit un disque source
factice et revérifie la sortie entièrement à la main
(`struct.pack`/`struct.unpack`, CRC32 recalculés directement) --
aucun import de `imaging/gpt.py`/`imaging/mbr.py` des deux côtés. Résultat
avec le code actuel (correctif protective-MBR inclus) : MBR protecteur
cohérent avec la taille réelle du fichier, CRC32 des deux en-têtes
valides, `AlternateLBA` des deux côtés se référençant correctement l'un
l'autre, tableau d'entrées primaire ne contenant jamais la partition de
jeux, aucune entrée gardée ne débordant du fichier -- confirmé en échec
sans le correctif protective-MBR (comme le test précédent), en succès
avec. **Non confirmé pour autant sur du vrai matériel** : aucune image
réelle de 128 Go → 8-9 Go ni `gdisk` n'était disponible pour cette
vérification (recherchée sur cette machine, absente) -- cette
vérification structurelle établit que le fichier produit est
internement cohérent (ce qu'un outil comme `gdisk` validerait), pas
qu'il démarre réellement une console : une cause distincte, propre au
matériel RK3326 réel (ex. un composant de démarrage écrit à un offset
fixe hors du schéma de partitions déclaré) resterait possible et non
exclue par ce test.


---

⚠️ **Défaut de parcours rapporté en usage réel, corrigé** : la première
version montrait l'écran expert (`HomeScreen`, les six étapes) pendant
toute l'opération — un changement de mode visuel non demandé, contraire
au principe « jamais un aller simple vers le mode expert » déjà énoncé
ailleurs (§4.5, ROCKNIX/système non reconnu) — et n'offrait ensuite
*aucune* suite : une fois la sauvegarde terminée, l'utilisateur restait
sur cet écran expert sans le moindre bouton pertinent. **Corrigé** :
`_start_backup_system_from_assisted_landing` affiche désormais
`WizardStepPanel` (déjà utilisé pour le parcours guidé lui-même) plutôt
que `HomeScreen` — l'infrastructure du journal de bord (`_log_panel`,
`_start_worker`) reste réutilisée en interne, mais rien d'expert n'est
jamais rendu visible. À la fin de l'opération (`_on_assisted_ad_hoc_
worker_finished`, point d'arrivée dédié dans `_on_worker_finished`, au
même niveau que le `if self._wizard_active:` du vrai parcours guidé),
le chemin du fichier créé apparaît dans le journal (déjà inclus dans
`_success_message()`) et `WizardStepPanel.show_next_step_choice` propose
explicitement la suite : « Préparer une carte avec cette sauvegarde »
(réussite uniquement — `show_prepare_card=ok`) ou « Revenir à
l'accueil » (toujours) — jamais un écran sans issue.

Deux nouveaux signaux dédiés sur `WizardStepPanel`
(`prepare_card_requested`/`return_to_home_requested`), jamais les
`continue_requested`/`cancel_requested` déjà câblés au vrai parcours
guidé (`_on_wizard_continue`/`_cancel_wizard`, qui opèrent sur
`self._wizard_flow` sans jamais vérifier `self._wizard_active` en
premier lieu) — les réutiliser pour cette opération ponctuelle aurait
avancé/corrompu l'état interne du parcours guidé pour de vrai. Un
nouveau drapeau d'instance, `_assisted_ad_hoc_active` (distinct de
`_wizard_active`), signale ce contexte à `_on_worker_finished`.

« Préparer une carte avec cette sauvegarde »
(`_on_prepare_card_requested`) réutilise le fichier fraîchement créé
comme source du flash — la fenêtre Choix du fichier est inutile
puisqu'il est déjà connu (`_skip_file_dialog_for_flash`, consommé par
`_on_device_chosen` avant son embranchement habituel) — mais la fenêtre
Confirmation reste obligatoire avant d'écrire pour de vrai (§2 règle 6,
jamais sautée) ; `_proceed_to_flash_confirmation` factorise cette
validation+confirmation, partagée avec le choix de fichier normal
(`_on_file_chosen`). Reste tout du long dans l'habillage assisté — même
le bouton Annuler de `WizardStepPanel`, déjà câblé à `_cancel_wizard`,
fonctionne correctement ici sans changement (annule `self._runner` s'il
y en a un, revient à l'accueil assisté), aucun gestionnaire dédié
nécessaire pour ce cas. Vérifié plus largement (`grep show_home()`) :
c'était la seule bascule non sollicitée vers l'écran expert dans tout
le mode assisté — les autres opérations (téléchargement ROCKNIX, chaque
étape du parcours guidé) restent déjà correctement dans `MainView`/
`WizardStepPanel` ou `AssistedLandingScreen`.

⚠️ **Blocage constaté en conditions réelles, corrigé** : l'écran
« Choisis la carte à préparer » (`_on_prepare_card_requested`, ci-dessus)
s'affichait bien, mais son bouton Continuer ne déclenchait rien — la
première version ouvrait directement la fenêtre modale Choix de la
carte (`_device_dialog.open()`, comme n'importe quelle tuile du mode
expert) sans jamais démarrer le moindre sondage automatique : aucun
bandeau de détection contrairement aux étapes 1/4 du vrai parcours
guidé, et le bouton Continuer, affiché mais jamais câblé à une action
pour cet écran précis, restait désactivé pour toujours (`can_continue=
False`, jamais réactivé). Confirmé qu'aucun filtre `safety` n'est en
cause (§4.2 : système, dossier de l'app, amovible/USB, taille —
jamais le contenu déjà présent sur la carte).

**Corrigé** en répliquant le même mécanisme que les étapes 1/4 :
`_prepare_card_poll_timer` (nouveau, distinct de `_wizard_poll_timer` --
ce parcours ponctuel n'est jamais un vrai `WizardJob`, y faire toucher
`_on_wizard_poll`/`self._wizard_flow` corromprait le vrai parcours
guidé) et `_on_prepare_card_poll` : une carte unique détectée active
Continuer avec le nom de la carte affiché en bandeau
(`wizard_status_device_found`, chaîne déjà utilisée par les étapes
1/4) ; zéro carte laisse Continuer désactivé (`wizard_status_waiting`) ;
plusieurs cartes retombent sur le même repli `_device_dialog` qu'avant
(`_skip_file_dialog_for_flash` n'est donc plus consommé que par ce cas
précis). `_prepare_card_candidate` (nouveau, `None` sauf carte unique
trouvée) fait le lien avec le bouton Continuer : `_on_wizard_continue`
le vérifie en tout premier, avant même `self._wizard_flow` -- jamais de
confusion possible entre les deux parcours, l'un exclut l'autre par
construction (`_wizard_active`/`_assisted_ad_hoc_active`). Bouton
Actualiser affiché (`show_refresh=True`, comme les étapes 1/4) pour
resonder manuellement sans attendre le prochain tick, ou après avoir
fermé le repli multi-cartes sans choisir -- `_on_wizard_refresh_
requested` route désormais vers le bon sondage selon
`self._assisted_ad_hoc_active`, jamais `_on_wizard_poll` pour ce cas.
`_cancel_wizard`/`_on_assisted_ad_hoc_return_home` arrêtent aussi ce
nouveau minuteur, défensivement.


---

