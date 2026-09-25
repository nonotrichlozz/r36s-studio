# Historique des bugs corrigés — Détection des cartes et accès aux partitions (§4.1 et §4.4 de CLAUDE.md)

> Ce fichier regroupe l'historique des investigations et correctifs liés à la
> détection des périphériques (`devices/`) et à l'accès aux fichiers des
> partitions (`partitions/`) — deux modules dont les bugs se recoupent souvent
> (identification d'une partition, montage, éjection). Le comportement
> **actuel** est décrit dans `CLAUDE.md` §4.1 et §4.4 ; ce document n'a de
> valeur que rétrospective.

---

## §4.1 `devices/`

> ⚠️ **Confirmé sur du vrai matériel : `Get-Disk.IsRemovable` est absent
> (pas faux) pour un lecteur de carte SD intégré.** Premier test réel sur
> un ThinkPad avec lecteur SD Realtek intégré (`R36S_STUDIO`, aucune carte
> détectée alors qu'une carte 128 Go était bien montée) : `Get-Disk`
> renvoie `IsRemovable: $null` pour **tous** les disques de cette machine,
> carte SD comprise, et son `BusType` vaut `SCSI` (`FriendlyName: Realtek
> PCIE CardReader`) — jamais `USB`. Le filtre `safety` (§4.2 : « `removable`
> est faux **et** `bus` n'est pas USB ») rejetait donc la carte à tort :
> `is_removable = disk.get("IsRemovable")` retombait sur `is None` avant
> même le repli `bus == "USB"`, qui échoue lui aussi puisque le bus
> annoncé est SCSI. Ce n'est pas propre à cette machine : n'importe quel
> lecteur de carte SD interne (PCIe/SCSI plutôt qu'USB) est concerné.
>
> **Corrigé** en croisant `Get-Disk` avec `Win32_DiskDrive.MediaType`
> (`Get-CimInstance Win32_DiskDrive | Select-Object Index, MediaType`,
> une troisième requête PowerShell dans `devices/windows.py::list_devices`)
> par index de disque — `"Removable Media"` (carte SD, confirmé sur cette
> machine) contre `"Fixed hard disk media"` (NVMe système, confirmé aussi)
> — utilisé seulement quand `IsRemovable` est absent, jamais pour
> contredire une valeur explicite. Le repli `bus == "USB"` reste en tout
> dernier recours si `Win32_DiskDrive` ne répond rien d'exploitable non
> plus (requête échouée, disque absent de sa liste). Aucune autre règle du
> garde-fou §4.2 n'est affaiblie — seul le signal `removable` change de
> source.



---

## §4.4 `partitions/`

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel — cause réelle du rapport
> ci-dessous : `Get-Volume` ne préserve pas l'ordre de son entrée
> pipeline.** `partitions/locate.py::_list_windows` faisait `Get-Partition
> -DiskNumber N | Sort-Object PartitionNumber | Get-Volume`, en supposant
> que trier les partitions *avant* `Get-Volume` suffirait à obtenir les
> volumes dans le même ordre en sortie. Faux : `Get-Volume` renvoie ses
> résultats selon sa propre énumération interne, indépendante de l'ordre
> de son entrée. Constaté en répétant l'appel plusieurs fois de suite sur
> la même carte R36S réelle (ThinkPad, lecteur SD Realtek intégré), sans
> rien changer côté matériel entre les appels : l'ordre alternait entre
> `[EASYROMS, BOOT, (partition Linux)]` et `[BOOT, (partition Linux),
> EASYROMS]` selon l'invocation.
>
> Impact concret : la sauvegarde « système sans les jeux » (§4.3) identifie
> la partition de jeux par étiquette (`EASYROMS`/`STORAGE`), *peu importe*
> son système de fichiers — mais refuse explicitement de continuer si
> cette partition se retrouve en première position (rien à garder avant
> elle). Quand l'ordre aléatoire plaçait `EASYROMS` en tête, l'opération
> échouait avec « Aucune partition de jeux reconnue » (`GamesPartitionNot
> Found`) alors que la carte est parfaitement standard — un échec
> intermittent, pas systématique, cohérent avec un rapport utilisateur qui
> voit l'échec une fois mais pas forcément à chaque tentative.
>
> **Corrigé** : chaque volume est désormais explicitement ré-associé à son
> `PartitionNumber` d'origine dans la boucle PowerShell elle-même
> (`ForEach-Object` + `Add-Member`, plutôt que de faire confiance à l'ordre
> du pipeline), puis la liste est triée une seconde fois côté Python sur ce
> champ. Un ordre déjà correct n'est jamais perturbé par ce second tri
> (stable, et l'ordre PowerShell était déjà par moments le bon). Vérifié en
> répétant l'appel une dizaine de fois de suite sur la carte réelle après
> correctif : ordre `[BOOT, (partition Linux), EASYROMS]` stable à chaque
> fois.
>
> **Second effet de bord découvert en vérifiant ce correctif** : pour la
> partition Linux (`ext4`, système de fichiers que Windows ne reconnaît
> pas), `Get-Volume` renvoie bien un objet volume (« RAW »), mais avec
> `Size: 0` plutôt qu'un champ absent — une vraie partition de 0 octet
> n'existe pas sur une carte SD flashée, `0` ici signifie « taille
> inconnue », comme le `None` que `PartitionInfo.size_bytes` représente
> déjà pour ce cas sur les autres OS. Sans distinction, `imaging/system_
> backup.py::estimate_system_backup_size_unprivileged` (§4.3, l'estimation
> affichée avant de lancer l'opération) additionnait ce `0` au lieu de
> détecter une taille manquante et de retomber sur son repli élevé — sur
> cette carte réelle, ça aurait affiché « ~115 Mo » (la taille de `BOOT`
> seul) au lieu de retomber sur le calcul exact, pour une sauvegarde
> système qui fait en réalité plusieurs Go (`BOOT` + la partition Linux).
> `_list_windows` traite désormais toute taille à `0` comme inconnue
> (`None`), jamais comme une vraie partition vide.


---

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : une copie EASYROMS
> restait bloquée, CPU à fond, sans jamais rien lire ni écrire.** Rapporté
> pendant un test réel de l'étape 3 (copie de l'écran et des jeux) : 392 s
> de temps CPU consommées, `ReadTransferCount` à 0 Mo, processus toujours
> « Responding ». Hypothèse initiale (chemin GUID de volume, ci-dessus,
> ajouté par un correctif récent et validé seulement sur `BOOT` — 47 Mo,
> arborescence plate) écartée après investigation : la même lenteur
> apparaît **identiquement** via une lettre de lecteur classique (`D:\`)
> que via le chemin GUID — rien à voir avec ce correctif.
>
> **Cause réelle, isolée sur la carte en cause** : un seul dossier
> (`ports/bigboy/tiles`, les tuiles d'un port de jeu) contient **40 964
> fichiers**. `partitions/copy.py::_list_files` énumérait via `Path.
> rglob("*")` puis filtrait avec `Path.is_file()` (un appel), et `copy_
> tree` recalculait ensuite `Path.stat().st_size` (un second appel) pour
> chaque fichier — deux recherches par nom, chacune reprenant l'exploration
> du dossier depuis le début sur un système de fichiers FAT/exFAT (pas
> d'index par nom, seulement une table de répertoire parcourue
> linéairement) : un coût en O(n) par fichier, donc O(n²) pour vider un tel
> dossier. Confirmé isolément sur ce dossier réel : plus de 120 s sans même
> terminer la première passe (`Path.is_file()` seul).
>
> **Corrigé** : `_list_files` est remplacée par `_walk_files`
> (`os.scandir()`, récursif), qui réutilise directement les attributs déjà
> obtenus par l'énumération elle-même (`FindNextFileW` sous Windows, via
> `DirEntry.is_file()`/`DirEntry.stat()`, tous deux mis en cache) plutôt
> que de redemander l'information par une recherche par nom séparée —
> O(n) au total, un seul passage. `copy_tree` ne fait donc plus non plus
> le second passage `Path.stat()` : `_walk_files` retourne directement les
> couples `(chemin, taille)`. **Confirmé sur le dossier réel en cause** :
> les mêmes 40 964 fichiers traités en 0,26 s (repli lettre de lecteur ou
> GUID, indifféremment) ; l'arborescence EASYROMS complète de cette carte
> (46 092 fichiers, ~3,9 Go) traitée en 0,53 s, contre un blocage qui ne
> se serait jamais terminé auparavant.


---

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel (parcours de clonage,
> Windows) : la carte source n'était jamais réellement éjectée à l'étape 3.**
> `eject()` levait purement et simplement `NotImplementedError` sous
> Windows depuis le début du projet -- un vrai trou, pas juste un cas mal
> géré : `_run_wizard_source_eject` (`gui/main_window.py`) l'attrapait
> bien et affichait l'erreur dans le journal (jamais un échec silencieux
> côté GUI), mais la carte, elle, restait montée et non éjectée pour de
> vrai. **Corrigé** : `_windows_eject` (`partitions/eject.py`) verrouille
> et démonte chaque volume monté du disque
> (`imaging/winlock.py::lock_and_dismount_volumes`, même mécanisme que
> l'écriture brute, §4.3), puis envoie l'éjection matérielle proprement
> dite au disque physique (`IOCTL_STORAGE_EJECT_MEDIA`, nouvelle fonction
> `winlock.eject_media` -- contrairement à `refresh_disk_properties`,
> best-effort, celle-ci lève en cas d'échec, une éjection ratée devant
> être signalée, §2 règle 5). Les lettres de lecteur du disque sont
> retrouvées via une requête PowerShell dédiée
> (`_windows_drive_letters`, `Get-Partition -DiskNumber N`) ; une
> partition sans lettre (BOOT sans lettre, §4.4) n'a simplement rien à
> démonter, l'éjection matérielle a quand même lieu.
>
> ⚠️ **Gap connu, non corrigé ici** (repéré en corrigeant le bug d'écriture
> ci-dessous, §4.3 « Bad file descriptor ») : `_windows_drive_letters`
> partage le même défaut que l'ancien code d'écriture -- seules les
> partitions *avec* une lettre de lecteur sont verrouillées/démontées
> avant l'éjection, BOOT (sans lettre) n'y figure jamais. Contrairement à
> l'écriture, une éjection ne maintient pas un accès brut soutenu pendant
> plusieurs minutes : rien ne prouve que ce gap cause un échec observable
> en pratique (pas de rapport en ce sens), mais il partage la même cause
> structurelle et mériterait le même traitement (`write_target.
> _windows_all_volume_paths`, toutes les partitions du disque) si un
> problème d'éjection est un jour rapporté.
>
> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : l'éjection ne
> fonctionnait jamais sur Windows, ni automatiquement (étape 3 du parcours
> de clonage) ni via le bouton du journal (mode expert comme mode
> assisté).** Le correctif ci-dessus (`_windows_eject`) répare bien
> l'implémentation Windows de `partitions/eject.py::eject`, mais cette
> fonction continuait d'être appelée **directement dans le processus GUI**
> (`gui/main_window.py::_perform_eject`/`_on_eject_requested`/`_run_
> wizard_source_eject`/`_run_wizard_eject`) -- à privilèges normaux, alors
> qu'ouvrir `\\.\PhysicalDriveN` pour `IOCTL_STORAGE_EJECT_MEDIA` exige
> l'élévation, exactement comme l'écriture brute (§4.3). Le flash y
> échappe déjà puisqu'il passe par le worker élevé (§3) ; l'éjection, elle,
> ne le faisait jamais. Symptômes observés :
> - **Bouton « Éjecter la carte » du journal** : `impossible d'ouvrir
>   \\.\PhysicalDrive1 (erreur 5)` -- `ERROR_ACCESS_DENIED`, affiché dans
>   une simple `QMessageBox` jamais journalisée (violation de la règle
>   « jamais un succès -- ni un échec -- silencieux », §4.4).
> - **Éjection automatique de la carte source avant l'étape « insère la
>   carte neuve »** (§5, `_run_wizard_source_eject`) : échec entièrement
>   silencieux, aucune ligne dans le journal entre la fin de la sauvegarde
>   et la détection suivante -- risque de corruption si l'utilisateur
>   retire la carte (exFAT/NTFS) sans savoir que l'éjection a échoué.
>
> **Corrigé** : les quatre points d'appel passent désormais par un worker
> élevé dédié (`gui/main_window.py::_start_eject`, réutilise `gui.worker_
> runner.WorkerRunner` avec `["eject", "--device", device.path]` --
> exactement le même mécanisme que `backup`/`flash`), jamais un appel
> synchrone à `partitions.eject.eject` dans le processus GUI. `__main__.py
> ::cmd_eject` gagne `--worker`/`--progress-file`/`--cancel-file`
> (`_add_worker_args`, déjà utilisés par `backup`/`flash`) pour pouvoir
> tourner comme worker élevé -- son échec émet désormais un code dédié,
> `EJECT_FAILED` (déjà utilisé côté GUI avant ce correctif pour un échec
> local, message : « ferme les fichiers ouverts... ou retire-la
> manuellement »), plutôt que le générique `IO_ERROR`. Chaque appelant
> (`_perform_eject`, `_on_eject_requested`, `_run_wizard_source_eject`,
> `_run_wizard_eject`) journalise désormais explicitement le résultat,
> succès comme échec (§4.4) -- `_on_eject_requested` ne se contentait
> auparavant que d'une `QMessageBox` en cas d'échec, jamais du journal.
>
> **Invite d'élévation supplémentaire, tranché en faveur de la
> fiabilité.** Chaîner l'éjection dans le worker qui vient d'écrire/de
> lire (`backup`/`flash`, déjà élevé) aurait évité une seconde invite UAC
> pour l'éjection automatique de l'étape 3 -- envisagé, non retenu : ça
> ferait perdre la distinction entre « la sauvegarde a réussi » et « l'
> éjection qui a suivi a échoué », nécessaire pour bloquer la suite du
> parcours tant que la carte source n'est pas sûre à retirer (le job
> `DETECT_TARGET` n'est jamais marqué fait sur un échec d'éjection --
> `Reprendre` relance alors cette éjection, pas toute la sauvegarde).
> Windows n'a de toute façon pas d'équivalent de `MacosAuthorizationSession`
> (§3, « ce correctif ne change rien pour Windows/Linux, qui continuent de
> redemander l'élévation à chaque worker élevé ») -- une invite
> supplémentaire par éjection reste donc cohérente avec le reste du projet
> sur cet OS, plutôt qu'une exception à ce principe déjà établi.
>
> **Non vérifié** : si `IOCTL_STORAGE_EJECT_MEDIA` fonctionnerait sur un
> handle ouvert en lecture seule sans élévation (ce qui éviterait
> l'élévation pour le seul cas du bouton) -- aucune carte physique
> disponible pour le tester ici, et l'hypothèse la plus probable reste que
> Windows restreint tout accès direct à `\\.\PhysicalDriveN`
> indépendamment du mode d'ouverture (lecture seule ou lecture/écriture),
> comme c'est déjà le cas pour l'écriture brute (§4.3). Piste future, à
> tenter uniquement si une session dispose d'un vrai lecteur de carte SD
> Windows pour vérifier sans risque de casser le correctif actuel.
>
> **Non confirmé sur du vrai matériel au moment d'écrire cette note**
> (aucune carte physique disponible ici) : la logique (worker élevé dédié,
> code d'erreur `EJECT_FAILED`, journalisation systématique) est couverte
> par des tests qui simulent le worker (`WorkerRunner` mocké, callback de
> fin appelé directement pour reproduire un succès ou un échec) plutôt que
> d'exécuter une vraie élévation Windows -- c'est précisément ce mécanisme
> non simulable ici (élévation réelle, disparition effective de la carte
> dans l'Explorateur Windows) qui reste à vérifier au premier test en
> conditions réelles.


---

> ⚠️ **Quatrième signalement, sur du vrai matériel, non résolu -- diagnostic
> ajouté en attendant, pas encore un correctif.** Malgré tout ce qui
> précède, l'éjection automatique de la carte source (mode assisté, entrée
> dans l'étape 3/DETECT_TARGET) ne se produit toujours pas : journal réel
> montrant la fin de la sauvegarde système suivie *directement* de la
> prochaine ligne de détection, six heures plus tard, sans une seule ligne
> d'éjection entre les deux -- ni succès, ni échec (§4.4 : exactement ce
> que ce module doit justement ne jamais laisser passer). Conséquence
> aggravée avec une image Android (§4.6, `is_android`) : les partitions de
> la carte source restent montées, Windows propose de les formater --
> risque réel de destruction si l'utilisateur accepte par erreur.
>
> **Cause non confirmée.** Avant ce correctif, `_run_wizard_source_eject`
> journalisait `wizard_ejecting_source` *après* `show_step(...)` et *avant*
> `_start_eject(...)`, sans aucune protection contre une exception --
> `self._wizard_source_device` valant `None` (état incohérent, cause non
> vérifiée) aurait fait échouer `_start_eject` sur `device.path` avant même
> d'atteindre `WorkerRunner`, avec l'exception remontant sans jamais
> toucher le journal : une explication plausible du symptôme exact
> rapporté, mais non confirmée sur le vrai matériel en cause -- aucune autre
> piste n'a été exclue non plus (`_on_wizard_job_finished`/`_enter_wizard_
> job` n'atteignant jamais DETECT_TARGET, par exemple).
>
> **Diagnostic ajouté, pas encore un correctif** : la ligne
> `wizard_ejecting_source` est désormais journalisée en tout premier, avant
> `show_step`, avec le reste du corps de `_run_wizard_source_eject`
> protégé par un `try/except` qui journalise explicitement toute exception
> (nouveau message, `friendly_error_message("EJECT_FAILED")` + détail brut)
> plutôt que de la laisser disparaître -- `_start_eject` réinitialise aussi
> l'état « occupé » des deux écrans si la construction du `WorkerRunner`
> échoue avant même son démarrage, pour ne jamais laisser l'interface
> bloquée sans issue dans ce cas. Si cette ligne apparaît enfin au prochain
> test réel (avec ou sans message d'erreur à sa suite), le bug est confirmé
> plus haut dans la chaîne (`_on_wizard_job_finished`/`_enter_wizard_job`)
> et cette instrumentation n'aura fait que l'exclure ; si un message
> d'erreur explicite apparaît à sa place, la cause exacte sera enfin connue
> et corrigeable directement. **Non testé sur du vrai matériel** (aucune
> carte physique disponible ici) -- couvert seulement par deux nouveaux
> tests (`tests/test_gui_main_window.py` :
> `test_entering_detect_target_logs_before_starting_the_eject_worker`,
> `test_entering_detect_target_with_no_source_device_logs_instead_of_
> vanishing`) qui simulent l'état incohérent plutôt que de le reproduire
> sur un vrai lecteur.


---

> ⚠️ **Audit multi-plateforme (demandé explicitement) : tout le travail
> d'éjection de ces derniers jours n'a été validé que sur Windows --
> revue de ce qui est commun aux trois OS et de ce qui reste propre à
> chacun, pour ne présenter comme acquis que ce qui l'est vraiment.**
>
> **Code commun aux trois OS (`eject()`, `partitions/eject.py`,
> `cmd_eject`, `__main__.py`)** : le dispatch par `platform.system()`, et
> tout le mystère du quatrième signalement ci-dessus (`_run_wizard_source_
> eject`/`_enter_wizard_job`/`_on_wizard_job_finished`, `gui/main_
> window.py`) -- aucune branche par OS avant d'atteindre `eject_device()`.
> Si la cause réelle de « la fonction ne semble jamais appelée » s'avère
> être dans cette partie commune (état incohérent, transition de job
> ratée...), elle concernerait les trois OS de la même façon -- mais
> aucun rapport ni aucun test réel n'existe à ce jour pour macOS/Linux sur
> ce point précis : les quatre signalements disponibles viennent tous du
> même poste Windows. `_start_eject`/`WorkerRunner` (§3) sont eux aussi
> entièrement communs -- invoquer `python -m r36s_studio eject --device
> <chemin> --worker --progress-file <fichier>` (élevé, ex. via `sudo` sur
> Linux) exerce exactement le même chemin que la GUI, sans avoir besoin de
> PySide6 pour le tester.
>
> **Ce qui diverge ensuite, par OS, dans `eject()` lui-même** :
> - **Windows** (`_windows_eject`, `imaging/winlock.py`) : de loin le plus
>   travaillé -- verrouillage par volume, réessais sur `ERROR_ACCESS_
>   DENIED`, gestion des partitions sans lettre de lecteur, `IOCTL_
>   STORAGE_EJECT_MEDIA`... **confirmé sur du vrai matériel**, à plusieurs
>   reprises, avec le détail exact de chaque échec rencontré (§4.3/§4.4
>   ci-dessus).
> - **macOS** (`subprocess.run(["diskutil", "eject", device_path], ...)`)
>   -- une seule commande, jamais modifiée pendant toute cette série de
>   correctifs. **Jamais confirmée sur du vrai matériel** dans ce projet,
>   à aucun moment -- aucune trace d'un test réel dans cet historique,
>   contrairement à Windows. Risque plausible, non vérifié : si la carte a
>   plusieurs volumes montés séparément (BOOT visible mais monté de façon
>   inhabituelle, §4.4), `diskutil eject` sur le disque entier devrait
>   suffire (il démonte tous les volumes du disque avant d'éjecter,
>   d'après sa documentation), mais ça n'a jamais été observé en pratique
>   ici.
> - **Linux** (`subprocess.run(["udisksctl", "power-off", "-b",
>   device_path], ...)`) -- une seule commande également, jamais modifiée
>   non plus. **Jamais confirmée sur du vrai matériel.** Précondition non
>   vérifiée : `udisksctl` (paquet `udisks2`) doit être installé et son
>   service tourner -- pas garanti sur une distribution minimale (ex.
>   antiX, mentionnée explicitement comme banc de test disponible pour ce
>   projet, machine i686 sans environnement de bureau complet) ; si absent,
>   `subprocess.run` lève `FileNotFoundError`, jamais testé ni géré
>   spécifiquement ici (retombe sur le comportement générique du code
>   appelant : `EJECT_FAILED` côté CLI élevé, §4.4).
>
> **Reste à vérifier sur du vrai matériel macOS/Linux** : que `eject()`
> réussit réellement (la carte disparaît du système) sur les deux OS,
> pour un cas simple (une seule partition montée) et pour une carte R36S
> réelle (BOOT + root + EASYROMS/STORAGE, plusieurs volumes) ; que
> `udisksctl` est bien présent sur l'environnement Linux visé, ou sinon
> quel message l'utilisateur voit réellement. La partie « pourquoi la
> fonction ne semble parfois jamais appelée » (quatrième signalement,
> code commun) reste ouverte sur les trois OS, faute de rapport ou de
> test réel en dehors de Windows.


---

> ⚠️ **Trois défauts distincts rapportés sur l'éjection en mode assisté,
> tous corrigés.**
>
> **1. Message d'erreur faux sur une invite UAC refusée.** `ShellExecuteExW`
> (verbe `runas`) peut lever une exception *synchrone*, avant même que le
> protocole JSON Lines n'ait quoi que ce soit à relayer, quand l'utilisateur
> refuse ou ferme l'invite (`GetLastError() == ERROR_CANCELLED`, 1223) --
> confirmé sur du vrai matériel. Cette exception, un simple `OSError`
> générique jusqu'ici, remontait telle quelle jusqu'à l'appelant : le
> `try/except` de `_run_wizard_source_eject` la retombait systématiquement
> sur le code codé en dur `EJECT_FAILED`, affichant « Ferme les fichiers
> ouverts dessus... » -- sans aucun rapport avec la cause réelle (un refus
> d'élévation, pas un fichier verrouillé). **Corrigé** : `gui/elevate.py::
> ElevationRefusedError` (sous-classe d'`OSError`, rien ne casse côté code
> qui l'attrape encore génériquement) distingue ce cas précis à la source
> (`_launch_windows`, `ERROR_CANCELLED = 1223`). `_start_eject`
> (`main_window.py`) intercepte désormais `runner.start()` lui-même --
> jamais fait auparavant, une omission distincte de ce qui précède -- et
> route systématiquement vers `on_finished(False, code, msg)` plutôt que de
> laisser l'exception se propager : `ELEVATION_REFUSED` pour ce cas précis
> (message dédié, « L'autorisation Windows a été refusée. Réessaie et
> accepte l'invite. »), `EJECT_FAILED` pour toute autre exception au
> démarrage comme avant. Plus aucun appelant (`_perform_eject`, `_on_eject_
> requested`, `_run_wizard_eject`, `_run_wizard_source_eject`) n'a besoin de
> son propre `try/except` pour ce cas précis -- `_run_wizard_source_eject`
> en gardait un pour d'autres causes (ex. `self._wizard_source_device`
> valant `None`), qui reste en place mais ne voit plus jamais passer un
> refus d'élévation par ce chemin.
>
> **2. Chemin périmé réutilisé à la deuxième tentative.** Rapporté : un
> deuxième essai après un premier échec réutilisait tel quel l'ancien
> chemin Windows (`\\.\PhysicalDriveN`) de la première tentative -- rejeté
> ensuite par le worker élevé lui-même comme introuvable
> (`DEVICE_NOT_ALLOWED`, `_resolve_device_or_report`) : Windows a pu
> libérer/renuméroter ce chemin entre les deux essais (ex. après une
> invite UAC refusée). **Corrigé** : `MainWindow._refresh_device_before_
> eject_retry` (nouveau) redétecte la carte (`_list_safe_devices()`, déjà
> non privilégié) avant *chaque* tentative d'éjection -- y compris la toute
> première, sans effet sur le cas normal (retrouve simplement la même
> carte) -- plutôt que de faire confiance à l'objet `Device` capturé une
> fois pour toutes. Un seul candidat détecté -> utilisé directement
> (l'éjection ne modifie aucune donnée, contrairement à une écriture :
> aucune vérification d'empreinte supplémentaire n'est nécessaire ici,
> § pré-vol réservée aux écritures) ; zéro ou plusieurs -> message
> explicite (`DEVICE_NOT_ALLOWED`) plutôt qu'une tentative sur un chemin
> peut-être mort. Appliqué aux deux ejections du parcours guidé (source,
> étape 3 ; cible, étape 5) -- pas aux boutons d'éjection du mode expert
> (`_perform_eject`/`_on_eject_requested`), qui partagent en théorie le
> même risque mais n'ont pas été signalés et n'ont donc pas été touchés
> ici, pour limiter le risque de régression à ce qui a été demandé.
>
> **3. Invite UAC supplémentaire rien que pour l'éjection, en plus de
> celle de la sauvegarde.** Rapporté précisément pour l'éjection de la
> carte *source* (étape 3, `_run_wizard_source_eject`, immédiatement après
> la sauvegarde de l'étape 2) -- chaque étape élevée redemande l'UAC sur
> Windows (§3, aucun équivalent de `MacosAuthorizationSession`), donc
> l'éjection dédiée existante ajoutait une seconde invite juste après
> celle de la sauvegarde. **Chaîner l'éjection dans le worker qui vient de
> lire la carte avait déjà été envisagé et écarté** (voir le docstring de
> `_start_eject` ci-dessus, encore valable pour le cas général) : le
> risque identifié était de perdre la distinction entre « la sauvegarde a
> réussi » et « l'éjection qui a suivi a échoué » -- si un échec
> d'éjection chaîné faisait échouer tout le `backup`, Reprendre relancerait
> toute la copie (potentiellement plusieurs Go, plusieurs minutes) juste
> pour réessayer une éjection ratée. **Résolu sans ce compromis** grâce à
> un canal séparé : `protocol.py::emit_eject_result(ok, msg)` (nouvel
> événement `eject_result`, distinct de `done`) rapporte le résultat de
> l'éjection chaînée sans jamais le mélanger au résultat de la sauvegarde
> elle-même. `backup --eject-after` (nouveau drapeau sur `cmd_backup`,
> distinct du `--eject-after` de `cmd_flash` -- best-effort, jamais
> rapporté séparément, §4.6) éjecte la carte source juste après la copie,
> dans ce même worker déjà élevé ; `WorkerRunner.eject_result` (nouveau
> signal Qt) relaie l'événement à `MainWindow._on_wizard_source_eject_
> result`, qui retient simplement le résultat (`_wizard_source_ejected`,
> `_wizard_source_eject_error_msg`) -- reçu *avant* la fin du worker
> (`eject_result` précède toujours `done` dans `cmd_backup`).
> `_start_worker` ajoute ce drapeau uniquement pour `backup`/`backup_
> system` en mode assisté (`self._wizard_active`), jamais en mode expert
> (aucun rapport avec ce parcours). `_run_wizard_source_eject` vérifie
> `_wizard_source_ejected` en tout premier : `True` (cas courant, les deux
> ont réussi ensemble) saute directement au même point d'arrivée que
> l'ancien chemin (`_on_wizard_source_eject_finished`, réutilisé tel quel)
> -- aucune seconde invite UAC ; `False` (l'éjection chaînée a échoué,
> rapportée séparément) ou `None` (signal jamais reçu) retombent sur le
> worker d'éjection dédié existant, exactement comme avant ce chaînage --
> sans jamais avoir à refaire toute la sauvegarde. `_wizard_source_ejected`/
> `_wizard_source_eject_error_msg` sont remis à `None` par `_start_wizard`,
> comme le reste de l'état du parcours.
>
> Portée volontairement limitée à l'éjection de la carte *source* (étape 3)
> -- celle explicitement rapportée « en plus de celle de la sauvegarde ».
> L'éjection de la carte *cible* (étape 5, `_run_wizard_eject`, après
> RESTORE_IMAGE) reste un worker dédié, non chaînée dans le flash : le
> même compromis (canal séparé, jamais fatal) s'y appliquerait tout aussi
> bien, mais n'a pas été demandé ici -- piste future si un jour signalée.
>
> **Effet secondaire possible, non confirmé, sur le chien de garde du
> sondage et la détection de la carte neuve.** Au moment d'écrire cette
> note, un signalement distinct reste ouvert : le chien de garde
> (`_check_wizard_poll_stall`, ci-dessus) continuerait de journaliser en
> boucle, et la carte neuve resterait non détectée sans clic manuel sur
> Rafraîchir, à l'entrée de l'étape 3 -- après le correctif du chien de
> garde lui-même (faux positifs sur les pauses légitimes, déjà corrigés,
> voir plus haut) et malgré lui. Le chaînage ci-dessus retire un worker
> d'éjection dédié entier -- avec sa propre invite d'élévation, son propre
> cycle de vie Qt -- du chemin courant entre la fin de la sauvegarde et le
> démarrage du sondage de la carte neuve, ce qui pourrait éliminer une
> source d'interférence non identifiée jusqu'ici. **Non confirmé** : aucune
> hypothèse concrète ne relie ce chaînage au symptôme rapporté, et aucun
> test ne le démontre -- à réévaluer au prochain test réel une fois ce
> correctif en place, avant de rouvrir une nouvelle investigation dédiée
> si le symptôme persiste malgré tout.


---

> ⚠️ **Même défaut rapporté après un flash en mode expert, deux minutes
> plus tard.** `flash --eject-after` (§4.6) existe déjà et chaîne
> l'éjection dans le worker de flash lui-même pour tout flash mode expert
> (`_flash_may_trigger_windows_format_prompt`, quasiment toujours vrai) --
> aucune seconde invite dans le cas courant, contrairement à la source
> confusion initiale. Mais ce mécanisme, best-effort, ne rapportait son
> résultat qu'au journal (`emit_log`, jamais un événement structuré) --
> `_on_worker_finished` masquait alors le bouton Éjecter *inconditionnel-
> lement* dès que ce drapeau était posé, en supposant la carte déjà
> éjectée avec succès. Un échec silencieux de cette éjection chaînée
> laissait donc la carte réellement non éjectée, sans bouton visible pour
> réessayer -- l'utilisateur devait deviner qu'il fallait passer par
> l'étape F séparée du mode expert, qui redemande sa propre élévation
> (§3) : exactement l'« invite UAC dédiée, deux minutes plus tard »
> rapportée, le délai correspondant au temps mis à remarquer que la carte
> n'était pas éjectée puis à cliquer sur cette étape séparée.
>
> **Corrigé** en réutilisant le mécanisme déjà construit pour `backup
> --eject-after` (ci-dessus) : `cmd_flash` appelle désormais aussi
> `emit_eject_result(ok, msg)` en plus du `emit_log` existant.
> `WorkerRunner.eject_result` (même signal, déjà partagé) est connecté à
> un nouveau `MainWindow._on_flash_eject_result` quand `_start_worker`
> pose `--eject-after` sur un flash (`self._flash_ejected`, remis à
> `None` à chaque nouveau worker). `_on_worker_finished` ne masque plus le
> bouton Éjecter inconditionnellement : `allow_eject` réapparaît dès que
> `self._flash_ejected is False` (résultat connu et négatif) -- `True` ou
> `None` (succès, ou signal jamais reçu) le laissent masqué comme avant.
> Portée volontairement limitée au flash (le cas rapporté) : `reset-card`
> éjecte aussi automatiquement mais n'a pas de bouton concurrent à
> masquer (§4.3 bis, déjà retiré de `_ALLOW_EJECT_AFTER_MODES`), rien à
> changer là.
>
> **Question posée en plus, non résolue avec certitude : l'invite UAC
> s'affiche-t-elle au premier plan ?** Deux minutes se sont écoulées avant
> l'échec observé -- cohérent avec une invite restée invisible pour
> l'utilisateur jusqu'à un délai d'expiration Windows, plutôt qu'un refus
> explicite et rapide (`ERROR_CANCELLED` immédiat). `ShellExecuteExW`
> recevait `hwnd=None` depuis toujours (`gui/elevate.py::_launch_
> windows`) -- Microsoft documente ce paramètre comme le propriétaire de
> la fenêtre affichée, et le laisser vide prive Windows d'un signal
> normal pour rattacher/mettre en avant l'invite. **Réserve importante,
> qui limite la portée de ce correctif** : l'invite de consentement UAC
> s'affiche elle-même sur le Bureau sécurisé, un mécanisme Windows séparé
> qui prend la main sur tout l'écran indépendamment de `hwnd` -- ce
> paramètre ne peut donc pas expliquer une invite cachée *derrière* une
> autre fenêtre au sens strict. Une explication au moins aussi probable,
> non vérifiable sans du vrai matériel multi-écran : l'invite apparaît sur
> un second écran hors du champ de vision de l'utilisateur au moment où il
> regarde l'application. **Corrigé quand même, en amélioration en
> l'absence de cause confirmée plutôt qu'en correctif garanti** :
> `WorkerRunner._windows_parent_hwnd` (nouveau) transmet le handle natif
> de `MainWindow` (`winId()`, Windows uniquement, `None` si indisponible
> ou hors Windows) à `launch_elevated_worker`/`_launch_windows`, qui le
> pose sur `info.hwnd` -- pratique recommandée par Microsoft pour
> `ShellExecuteEx`, sans inconvénient connu. **Non confirmé sur du vrai
> matériel** : à réévaluer au prochain flash réel si l'invite reste
> invisible malgré ce changement -- pointerait alors vers l'hypothèse
> multi-écran plutôt que vers un défaut de paramétrage de
> `ShellExecuteExW`.


---


---

⚠️ **Bug corrigé, confirmé sur le binaire empaqueté : le sondage automatique
du parcours de clonage (§5, `_wizard_poll_timer`, toutes les 1,5 s) semblait
ne jamais détecter une carte insérée après l'ouverture de l'app, forçant un
clic manuel sur Rafraîchir — contraire à §1.** Cause : `list_devices()`
lançait trois processus PowerShell séquentiels (`Get-Disk`, `Get-Partition`,
`Get-CimInstance Win32_DiskDrive`), chacun coûtant de quelques centaines de
millisecondes à plus d'une seconde à démarrer (plus sensible sur un binaire
empaqueté fraîchement construit, plus scruté par l'antivirus) — exécutés
*synchrones sur le thread Qt principal* à chaque tick du minuteur. Le cumul
dépassait régulièrement le seuil du chien de garde (`_check_wizard_poll_
stall`, §5), qui journalisait un ralentissement à répétition sans que le
minuteur lui-même ne soit en cause. **Corrigé** : `_LIST_DEVICES_COMMAND`
combine les trois requêtes en une seule invocation PowerShell (un objet
`@{ Disks = …; Partitions = …; Drives = … } | ConvertTo-Json`), une seule
fois par sondage plutôt que trois. `_build` accepte désormais directement
les objets déjà désérialisés (`combined.get("Disks")`, etc.) plutôt que des
chaînes JSON brutes.

---

## Ajouté lors du découpage de CLAUDE.md (2026-09-25)

> Récits déplacés tels quels depuis l'ancien `CLAUDE.md` (commit `930f3c9`). Les renvois « §N » désignent ses sections.

⚠️ **Bug corrigé sur du vrai matériel** : cette détection ne se déclenchait
pas — `copy-games` échouait avec `[Errno 30] Read-only file system` au lieu
du refus explicite. Cause : `diskutil info -plist` ne renvoie pas
systématiquement la chaîne exacte `ntfs` pour `FilesystemType` (variante de
casse, ou nom de type de partition `Windows_NTFS`), et la comparaison
stricte `== "ntfs"` échouait silencieusement. `_macos_filesystem` normalise
désormais toute variante contenant `ntfs` (`FilesystemType` et `Content`,
insensible à la casse) vers la valeur canonique `"ntfs"`. En complément,
`partitions/copy.py` vérifie maintenant l'inscriptibilité réelle du point
de montage (écriture d'un fichier sonde) *avant* toute copie, quel que
soit l'OS ou le système de fichiers — filet de sécurité générique pour
tout futur cas de détection erronée, pas seulement celui-ci.

⚠️ **Bug corrigé, confirmé sur du vrai matériel : « carte défaillante »
affiché à tort à l'étape 2 (identification) sous Windows.** Rapporté sur
un ThinkPad avec lecteur SD Realtek intégré : le journal montrait
`PartitionNotMounted` (« délai dépassé ») pour `BOOT`, alors que
`Get-Volume` confirme que la partition (FAT32, 115 Mo) existe et est
parfaitement lisible — elle n'a simplement pas de lettre de lecteur.
Cause de fond : contrairement à macOS/Linux, où `locate_mounted` retente
activement un montage (`_mount_macos`/`_mount_linux`) avant d'abandonner,
Windows n'a *aucune* tentative active dans la boucle — `_list_windows`
attend passivement qu'une lettre apparaisse, ce qui n'arrive jamais pour
une partition que Windows ne juge pas devoir monter spontanément (rien à
voir avec un défaut matériel). Le message `MOUNT_FAILED` (« carte
défaillante, courant sur les cartes fournies avec la console »),
initialement pensé pour ce cas macOS/Linux, était donc trompeur ici.
