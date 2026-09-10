# Historique des bugs corrigés — Imaging : lecture/écriture brute (§4.3 de CLAUDE.md)

> Ce fichier contient l'historique des investigations et correctifs liés à la
> copie bloc par bloc du périphérique brut (verrouillage/démontage Windows,
> montage macOS, alignement des écritures). Pour la manipulation des tables
> de partitions (troncature, réparation GPT/MBR, partition de jeux, remise à
> zéro de carte), voir [docs/bugs-imaging-partitions.md](bugs-imaging-partitions.md).
> Le comportement **actuel** est décrit dans `CLAUDE.md` §4.3.

---

> ⚠️ **Diagnostic partiel, PAS le correctif complet -- voir la note plus
> bas (« Investigation en cours, non résolue ») : cette hypothèse (BOOT
> resté monté) a corrigé un vrai bug de champ d'application, mais
> l'échec `[Errno 9] Bad file descriptor` persiste sur du vrai matériel
> même une fois BOOT verrouillé/démonté comme le reste.** Gardé tel quel
> ci-dessous (raisonnement toujours valide sur ce point précis, et
> nécessaire au correctif de la carte vierge qui suit), mais ne pas le
> lire comme la cause complète de `[Errno 9]` sur Windows.
>
> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : `[Errno 9] Bad file
> descriptor` une seconde après le début de l'écriture Windows.** Rapporté
> sur une carte cible portant un ArkOS complet (BOOT + root + EASYROMS,
> seule EASYROMS montée avec une lettre de lecteur), `ConfirmDialog`
> affichée correctement, l'échec survenait au tout début de l'écriture
> réelle. Cause : `write_target.prepared_write_target` (§4.3) verrouillait/
> démontait `device.mountpoints` (`devices/windows.py`) avant d'ouvrir
> `\\.\PhysicalDriveN` -- mais ce champ ne contient que les partitions
> *avec une lettre de lecteur*. BOOT (FAT, typiquement sans lettre sur une
> carte ArkOS, §4.4) restait donc monté pendant toute l'écriture brute du
> disque entier. Environ une seconde après le début de l'écriture --
> celle des tout premiers secteurs, qui appartiennent justement à BOOT --
> Windows détecte que le contenu d'un volume encore monté change sous lui
> et révoque le handle physique en cours d'écriture pour protéger ce
> volume plutôt que de le laisser continuer : `ERROR_INVALID_HANDLE` côté
> Win32, `[Errno 9] Bad file descriptor` côté Python. L'ordre des
> opérations lui-même était déjà correct (`\\.\PhysicalDriveN` n'est
> ouvert qu'*après* `lock_and_dismount_volumes`, jamais avant) -- ce n'est
> pas la séquence qui était en cause, mais son périmètre : verrouiller
> seulement les volumes lettrés en oublie silencieusement ceux qui n'en
> ont pas. Confirmé sans rapport avec `eject_media()`/`IOCTL_STORAGE_
> EJECT_MEDIA` (ajoutés dans le même module par un commit récent, §4.4
> « Éjection ») : ce code n'est appelé que par l'étape F (éjection),
> jamais pendant l'écriture -- vérifié par une recherche exhaustive des
> appelants (`eject_media`/`_windows_eject` : uniquement `partitions/
> eject.py`).
>
> **Corrigé** : `write_target._windows_all_volume_paths` (nouvelle
> fonction) interroge `Get-Partition -DiskNumber N` (même mécanisme
> `AccessPaths` que `partitions/locate.py::_list_windows`, requête
> PowerShell distincte pour ne pas coupler `imaging/` à `partitions/` pour
> un simple besoin d'énumération) et retourne le chemin GUID
> (`\\?\Volume{...}\`) de *toutes* les partitions du disque, lettrées ou
> non -- une partition dont Windows ne reconnaît pas le système de
> fichiers (ext4, la partition root) obtient tout de même un volume "RAW"
> avec son propre chemin GUID (§4.4, comportement déjà confirmé
> ailleurs) ; le verrouiller/démonter sans risque (`FSCTL_LOCK_VOLUME`
> réussit trivialement sur un volume RAW non monté). `prepared_write_
> target` verrouille désormais cette liste complète plutôt que `device.
> mountpoints`. `winlock._drive_letter_to_volume_path` accepte maintenant
> aussi bien une lettre (`"D:\\"`) qu'un chemin déjà dans l'espace de noms
> périphérique (le repasser tel quel, débarrassé seulement de son `\`
> final, plutôt que de le préfixer une seconde fois par `\\.\` -- ce qui
> aurait produit un chemin invalide).
>
> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : le correctif ci-dessus
> faisait planter la restauration sur une carte vierge.** Testé
> spécifiquement pour trancher entre les hypothèses en cours sur ce même
> code (voir plus bas) : carte de 32 Go effacée (`Clear-Disk`, zéro
> partition, aucun volume monté), la restauration échouait avec `Command
> [...] "Get-Partition -DiskNumber 1 | ..." returned non-zero exit status
> 1`. Cause : sur un disque sans aucune partition, `Get-Partition` ne
> renvoie pas une liste vide -- il lève `ObjectNotFound` et PowerShell sort
> en code 1 (vérifié à la main). `check=True` traitait ça comme un échec
> fatal, alors qu'« aucune partition à verrouiller » est un résultat
> parfaitement normal avant un premier flash sur une carte neuve -- même
> principe que `reunmount_before_verify` sur macOS, qui utilise déjà
> `check=False` pour cette raison exacte. **Corrigé** : `check=False`, un
> code de retour non nul retombe sur une liste vide plutôt que de lever --
> `lock_and_dismount_volumes([])` est déjà un no-op sûr.
>
> ⚠️ **Investigation en cours, non résolue : `[Errno 9] Bad file
> descriptor` persiste sur la carte ArkOS complète malgré le correctif
> ci-dessus (verrouillage de toutes les partitions, lettrées ou non).**
> Confirmé sur du vrai matériel en testant les deux cartes en séquence
> pour isoler la cause : la carte vierge produit l'échec `ObjectNotFound`
> ci-dessus (corrigé), mais la même séquence de code sur la carte ArkOS
> (BOOT + root + EASYROMS, EASYROMS lettrée) redonne `[Errno 9] Bad file
> descriptor` -- donc l'hypothèse initiale (BOOT resté monté parce
> qu'exclu de `device.mountpoints`) est réfutée par cette nouvelle
> donnée : BOOT est désormais verrouillé/démonté comme les autres, et
> l'échec persiste quand même. Le mécanisme réel reste à confirmer -- pas
> encore une explication établie, seulement des pistes :
> - Le démontage (`FSCTL_DISMOUNT_VOLUME`) lui-même pourrait déclencher,
>   sur un lecteur de carte SD amovible, un comportement du pilote de
>   stockage (reset/re-détection du périphérique USB) qui invalide toute
>   poignée ouverte sur le disque physique peu après -- y compris une
>   poignée ouverte *après* le démontage, ce qui expliquerait pourquoi
>   l'ordre actuel (ouvrir `\\.\PhysicalDriveN` seulement après
>   `lock_and_dismount_volumes`, jamais avant) ne suffit pas.
> - Le sous-processus PowerShell de `_windows_all_volume_paths`
>   (`Get-Partition`) pourrait laisser un état transitoire (WMI/CIM) qui
>   n'a pas fini de se libérer au moment où le verrouillage direct
>   (`ctypes`) commence.
>
> Aucune des deux n'est vérifiée -- correctif non tenté tant que la cause
> réelle n'est pas confirmée, pour ne pas répéter l'erreur du correctif
> précédent (une hypothèse plausible mais incomplète, présentée comme
> réglée avant d'être re-testée sur du vrai matériel). **Diagnostic ajouté
> en attendant** : `imaging/copy.py::copy_range` inclut désormais, dans le
> message de l'exception ré-levée en cas d'échec d'écriture, le nombre
> d'octets déjà écrits et le temps écoulé depuis le début de la copie --
> ce contexte atteint déjà le journal de bord via le chemin d'erreur
> existant (`IO_ERROR` -> `str(exc)`, §5 vocabulaire) sans nouveau
> mécanisme. Le prochain test sur la carte ArkOS dira si l'échec survient
> toujours au même octet/délai caractéristique (cohérent avec un
> mécanisme déterministe côté pilote) ou de façon variable.
>
> ⚠️ **Piste supplémentaire, non vérifiée mais à rapprocher de ce qui
> suit** : un bug distinct confirmé juste après (`FSCTL_LOCK_VOLUME`
> refusé par un autre processus, ci-dessous) établit qu'Explorateur/
> indexeur/antivirus interfèrent réellement avec ce même verrouillage sur
> du vrai matériel Windows. Rien ne prouve encore un lien avec le `[Errno
> 9]` ci-dessus, mais la même famille de cause (un processus tiers qui
> rouvre un descriptor sur le volume ou le disque physique juste après le
> démontage) reste plausible et n'a pas été exclue -- à garder en tête si
> une future session revient sur cette investigation.


---

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : `FSCTL_LOCK_VOLUME`
> refusé (`DeviceIoControl a échoué (code 0x90018, erreur 5)`,
> `ERROR_ACCESS_DENIED`) alors que le worker est bien élevé.** Le worker
> élevé ne manque donc jamais de privilèges pour ce refus précis -- une
> élévation refusée ou absente échouerait plus tôt, avant même d'atteindre
> ce point. Cause : un AUTRE processus (l'Explorateur qui prévisualise le
> volume, l'indexeur de recherche Windows, un antivirus) tient encore un
> descripteur ouvert sur ce volume au moment précis où le worker tente de
> le verrouiller -- un état transitoire qui se libère très souvent en une
> ou deux secondes. Le code refusait déjà correctement d'écrire sans ce
> verrouillage (§4.3 : sans lui, Windows refuse l'écriture ou corrompt la
> carte) -- le vrai défaut était le message affiché, `error_io_error`
> (« Vérifie que la carte est toujours branchée »), faux et inutile dans
> ce cas précis : la carte est bien branchée, le worker bien élevé, rien à
> vérifier de ce côté.
>
> **Corrigé en deux temps**, tous les deux dans `imaging/winlock.py` :
> 1. **Nouvelles tentatives avant d'abandonner.** `_lock_volume` (remplace
>    l'appel direct à `_device_io_control(handle, FSCTL_LOCK_VOLUME)` dans
>    `lock_and_dismount_volumes`) réessaie jusqu'à `LOCK_VOLUME_RETRY_
>    COUNT` fois (5), espacées de `LOCK_VOLUME_RETRY_DELAY_SECONDS` (0,5 s),
>    mais *seulement* quand l'échec est `ERROR_ACCESS_DENIED` -- toute
>    autre erreur (volume déjà absent, périphérique disparu...) est
>    propagée immédiatement, réessayer n'y changerait rien.
>    `_device_io_control` porte désormais le code Win32 réel sur
>    l'exception qu'elle lève (`DeviceIoControlError.win32_error`, nouvelle
>    classe -- sous-classe d'`OSError`, donc rien ne casse côté appelants
>    existants qui attrapent `OSError` génériquement) pour que `_lock_
>    volume` puisse distinguer les deux cas sans reparser le message.
> 2. **Message dédié si les tentatives s'épuisent.** `VolumeInUseError`
>    (nouvelle exception, `imaging/winlock.py`) -- `cmd_flash`
>    (`__main__.py`) l'intercepte *avant* le repli générique `except
>    (OSError, ...)` (dont elle hérite, mais l'ordre des `except` fait
>    gagner la branche spécifique) et émet un nouveau code dédié,
>    `VOLUME_IN_USE`, plutôt que `IO_ERROR`. Message convivial
>    (`gui/strings.py::error_volume_in_use`) : invite explicitement à
>    fermer les fenêtres de l'Explorateur qui affichent la carte, plutôt
>    que de suggérer (à tort) un débranchement.
>
> Portée volontairement limitée à `FSCTL_LOCK_VOLUME` (l'écriture, §4.3) --
> `eject_media`/`refresh_disk_properties` (`partitions/eject.py`, même
> module) ne bénéficient pas encore de ces nouvelles tentatives ; même
> mécanisme d'interférence plausible pour l'éjection, mais non rapporté et
> non traité ici, par cohérence avec le principe déjà appliqué ailleurs
> dans ce fichier (ne corriger que ce qui a été signalé, noter le reste
> comme piste future).


---

> ⚠️ **Défaut corrigé au passage, signalé comme sans conséquence
> fonctionnelle : le journal affichait « Éjection automatique de la carte
> (firmware Android)… » après un flash ArkOS.** Cause : `--eject-after`
> a été généralisé à tout le catalogue (§4.6, au moins une partition de
> tout firmware -- pas seulement Android -- est illisible pour Windows),
> mais le message correspondant dans `__main__.py::cmd_flash` était resté
> celui d'avant cette généralisation, jamais mis à jour. L'éjection
> elle-même se déclenchait déjà correctement pour ArkOS (comportement
> voulu depuis la généralisation) -- seul le texte affiché était trompeur,
> laissant croire à une erreur de détection de firmware qui n'existait pas.
> **Corrigé** : message neutre, « Éjection automatique de la carte… »,
> sans mention d'un firmware précis -- cohérent avec le fait que ce
> drapeau s'applique désormais à tout le catalogue. Corrigé au passage
> dans l'aide `--eject-after` du parser (`--help`), qui portait la même
> affirmation obsolète.


---

> ⚠️ **Écart constaté en documentant la fonctionnalité ci-dessous** :
> `.img.zip` n'a en réalité jamais été implémenté —
> `image_source.SUPPORTED_EXTENSIONS` ne couvre que `.img`/`.img.gz`/
> `.img.xz`. Un `.zip` choisi pour le flash échoue donc aujourd'hui avec le
> message générique de format non supporté (ci-dessous), jamais avec une
> décompression réussie. Non corrigé pour l'instant (pas demandé) — signalé
> ici pour que la ligne ci-dessus ne serve pas de source de vérité erronée
> à une future session.


---

