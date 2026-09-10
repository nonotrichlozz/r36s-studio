# Historique des bugs corrigés — Architecture (§3 de CLAUDE.md)

> Ce fichier contient l'historique des investigations et correctifs liés à
> l'élévation de privilèges et à la communication GUI ↔ worker. Le
> comportement **actuel** est décrit dans `CLAUDE.md` §3 ; ce document
> n'a de valeur que rétrospective (pourquoi le code est ce qu'il est).

---

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : `ELEVATION_FAILED`
> affiché à tort alors que l'élévation Windows réussissait, masquant un
> refus légitime du worker.** Rapporté comme un `ELEVATION_FAILED`
> systématique après ~12 s d'attente. Lancé à la main en administrateur
> (`py -m r36s_studio backup ...`), le worker émettait en réalité
> correctement `{"type":"error","code":"GAMES_PARTITION_NOT_FOUND"}` --
> carte cible de 32 Go branchée, sans partition de jeux : un refus
> légitime (§4.3), pas un défaut d'élévation. Le vrai problème : ce
> message n'atteignait jamais la GUI, qui affichait `ELEVATION_FAILED` à
> la place.
>
> Cause : `protocol.py::emit_error` écrit déjà l'événement dans le fichier
> de progression (`--progress-file`, `protocol.configure`) quand le
> worker est élevé -- `WorkerRunner._dispatch` (`gui/worker_runner.py`) le
> relayait donc bien via `self.error.emit(...)`. Mais de nombreux chemins
> d'erreur de `__main__.py` (`GAMES_PARTITION_NOT_FOUND` entre autres)
> font seulement `emit_error(...); return 1`, sans jamais appeler
> `emit_done(False)` -- et `WorkerRunner._poll()` ne savait détecter la
> fin d'une opération en erreur qu'à `_done_emitted`, jamais à un `error`
> déjà reçu. Résultat : dès que le process élevé se terminait (`poll()`
> non `None`) sans `"done"`, `_poll()` retombait sur sa branche «
> élévation refusée/échouée » et écrasait le vrai code déjà délivré par un
> `ELEVATION_FAILED` générique -- et sur Windows en particulier,
> `ShellExecuteW` ne fournissant aucun tube stdout/stderr vers le
> processus élevé (contrairement à `osascript`/`pkexec`/`sudo`), rien
> d'autre ne permettait de distinguer un vrai refus d'élévation d'un
> worker qui avait échoué proprement pour une tout autre raison.
>
> **Corrigé** : `WorkerRunner` retient désormais si un vrai événement
> `"error"` a déjà été reçu (`_error_emitted`, mis à `True` dans
> `_dispatch`) -- la branche de fin de `_poll()` ne synthétise
> `ELEVATION_FAILED` (ou les cas macOS TCC détectés via le journal
> d'élévation) que si aucune erreur réelle n'était déjà connue ;
> `finished.emit(False)` reste émis dans tous les cas, une seule fois. Le
> contenu déjà présent dans le fichier de progression prime donc toujours
> sur une élévation supposée en échec, quel que soit l'OS -- pas seulement
> pour ce code précis.


---

> ⚠️ **Limitation macOS confirmée par test.** `osascript … with administrator
> privileges` obtient bien les droits root pour le worker, mais **ne peut pas
> accéder à `/dev/rdiskN`** — même avec le Terminal autorisé en Accès complet au
> disque (Réglages Système → Confidentialité et sécurité). TCC (Transparency,
> Consent and Control) filtre au-dessus des droits Unix classiques, et le
> processus lancé par `osascript` n'hérite d'aucune identité TCC propre : il n'y
> a rien à autoriser tant qu'il n'est pas packagé comme application.
>
> **Décision (historique) :** cette limitation ne sera résolue qu'en phase 7,
> quand l'appli sera empaquetée (PyInstaller) — un binaire packagé a sa propre
> identité TCC et pourra être ajouté à la liste Accès complet au disque. Elle ne
> bloque pas les phases 5 et 6. En attendant, la GUI doit détecter cet échec
> spécifique et afficher un message explicite invitant à utiliser la ligne de
> commande avec `sudo` (depuis un Terminal autorisé en Accès complet au disque)
> plutôt qu'un message d'erreur générique. Linux (`pkexec`) et Windows (UAC) ne
> sont pas concernés par cette limitation.
>
> ✅ **Résolu (phase 7), confirmé sur du vrai matériel.** Une fois l'app
> empaquetée (`packaging/`) ajoutée à Accès complet au disque, `osascript`
> restait bloqué sur `/dev/rdiskN` même ainsi : c'est bien lui le problème, pas
> l'absence de bundle. Cause : `osascript` est un processus système sans
> rapport avec le bundle de l'app — l'enfant qu'il lance n'hérite d'aucune
> identité TCC, packagée ou non. **Correctif :** sur l'app empaquetée,
> `gui/elevate.py` relance désormais le worker directement depuis le binaire
> du bundle lui-même (`sys.executable`, via `AuthorizationExecuteWithPrivileges`
> — `Security.framework`, pas `osascript`/`do shell script`)
> (`MacosAuthorizedProcess`). Un enfant direct du binaire signé **hérite bien**
> de l'autorisation Accès complet au disque du bundle — vérifié par une sonde
> read-only sur `/dev/rdiskN` avant d'implémenter quoi que ce soit de plus
> lourd. `osascript` reste utilisé en développement (pas de bundle, donc rien
> à hériter) et comme repli si cette API — non documentée par Apple depuis
> macOS 10.7, mais toujours présente au moment de ce test (macOS 12) —
> disparaissait d'une future version de macOS.
>
> ⚠️ **La signature ad hoc change à chaque reconstruction.** PyInstaller signe
> le bundle ad hoc par défaut (aucun certificat Developer ID nécessaire, §6),
> mais cette signature change à chaque `packaging/build_macos.sh` — même sans
> changement de code observable. macOS lie l'autorisation Accès complet au
> disque à cette signature : après chaque reconstruction, l'autorisation
> précédente est invalidée et doit être refaite (retirer puis rajouter l'app
> dans la liste, pas juste désactiver/réactiver le bouton existant — voir
> `packaging/README.md` §4). C'est pour ça que le message d'erreur
> `MACOS_TCC_BLOCKED` (`gui/worker_runner.py`) et l'écran Aide dédié
> (`gui/screens.py::HelpScreen`, accessible depuis l'accueil sur macOS) pointent
> tous les deux vers cette autorisation plutôt que vers la ligne de commande —
> devenue inutile pour ce cas précis.
>
> Le deuxième cas ci-dessous (`MACOS_TCC_PROTECTED_FOLDER`, fichiers dans
> Téléchargements/Bureau/Documents) n'a pas été retesté avec ce nouveau chemin
> d'élévation — probablement concerné par le même principe (un enfant du
> bundle hérite de l'identité TCC), mais non vérifié sur du vrai matériel :
> son message et sa détection restent donc inchangés pour l'instant.
>
> ⚠️ **Deuxième cas confirmé sur du vrai matériel, distinct du précédent** :
> `[Errno 1] Operation not permitted` survient aussi sur des **fichiers
> ordinaires** (l'image `.img.xz` à flasher, typiquement), pas seulement sur
> `/dev/rdiskN`, quand ce fichier se trouve dans l'un des trois dossiers que
> macOS protège par TCC : Téléchargements, Bureau, Documents — même quand le
> Terminal a l'Accès complet au disque, cette autorisation ne s'étend pas au
> worker élevé par `osascript`. Exemples réels :
> `/Users/x/Downloads/ArkOS...img.xz`, `/Users/x/Desktop/r36s/ArkOS...img.xz`
> (dans un sous-dossier — la détection doit chercher le nom de dossier
> n'importe où dans le chemin, pas seulement en tête). `worker_runner.py`
> détecte ce cas séparément (`MACOS_TCC_PROTECTED_FOLDER`, distinct de
> `MACOS_TCC_BLOCKED`) et invite à déplacer le fichier ailleurs — plutôt qu'à
> utiliser `sudo`, qui ne changerait rien ici puisque le problème n'est pas le
> périphérique brut mais l'un de ces trois dossiers précis.


---

> ⚠️ **Bug corrigé, confirmé sur du vrai matériel : `AttributeError: Slot
> 'MainWindow::_on_progress(int,int,double)' not found`, en continu pendant
> un flash.** Cause réelle, trouvée via une capture `QT_FATAL_WARNINGS=1`
> sur le binaire empaqueté : un `OverflowError` intercalé juste avant
> chaque occurrence du message. `WorkerRunner.progress`/
> `PartitionJobRunner.progress` étaient déclarés `Signal(int, int, float)`
> — `int` correspond à un entier **32 bits** côté Qt (~2,1 milliards max),
> alors qu'un compte d'octets pour une carte de 32 Go dépasse 34
> milliards. PySide6/libshiboken échoue alors à convertir l'argument et
> n'émet jamais d'exception Python (l'`emit()` continue silencieusement) :
> le seul symptôme visible est ce message trompeur, comme si le slot
> n'existait pas, alors que le vrai problème est la conversion de
> l'argument en amont. C'est pour ça qu'aucun test (ni les miens en
> investigation, avec des valeurs de type 50/200 octets) ne l'attrapait :
> tous restaient sous 2 Go.
>
> **Corrigé** en déclarant `Signal("qint64", "qint64", float)` (entier 64
> bits) sur ces deux signaux (`gui/worker_runner.py`,
> `gui/partition_runner.py`), et le `@Slot("qint64", "qint64", float)`
> assorti sur `MainWindow._on_progress`. Les `@Slot(str, str)`/`@Slot(bool)`
> sur `_on_worker_error`/`_on_worker_finished` (ajoutés par précaution lors
> de l'étape précédente de cette investigation, avant que la vraie cause
> ne soit identifiée) restent en place : sans risque, et cohérents avec le
> principe de déclarer explicitement les slots recevant un signal
> potentiellement inter-thread (`PartitionJobRunner`). Toute taille en
> octets transitant par un signal Qt doit désormais utiliser `"qint64"`,
> jamais `int` nu — vérifié : ce sont les deux seuls signaux du projet à
> transporter des tailles en octets (`grep -rn "Signal(" r36s_studio/`).
>
> `QT_FATAL_WARNINGS=1` s'est révélé être le bon outil une fois débarrassé
> du faux positif rencontré en environnement `QT_QPA_PLATFORM=offscreen`
> (l'avertissement anodin `qt.qpa.fonts: Populating font family aliases…`,
> que PySide6 émet systématiquement et qui devient fatal avec cette
> variable) : sur un vrai écran, sans `offscreen`, il a directement pointé
> vers l'`OverflowError` réel.


---

> ⚠️ **Bug corrigé, constaté en usage réel : l'invite mot de passe
> administrateur était redemandée à chaque étape du parcours guidé
> nécessitant l'élévation, plutôt qu'une seule fois pour tout le
> parcours.** Cause : `WorkerRunner.start()` appelait `elevate.
> launch_elevated_worker(...)` sans rien conserver d'un appel à l'autre —
> sur macOS packagé (`MacosAuthorizedProcess`), ça revenait à créer puis
> libérer une nouvelle `AuthorizationRef` (`AuthorizationCreate`/
> `AuthorizationFree`, Security.framework) à chaque worker élevé, forçant
> `AuthorizationExecuteWithPrivileges` à repasser par l'invite à chaque
> fois plutôt que de profiter d'une autorisation déjà accordée.
>
> **Corrigé** en conservant une seule `AuthorizationRef` vivante pour
> toute une session plutôt qu'une par opération :
> `elevate.MacosAuthorizationSession` (nouvelle classe) l'obtient une
> fois (`AuthorizationCreate`) et la libère à la fermeture de l'app
> (`close()`, appelé depuis `MainWindow.closeEvent`) ; `_run_authorized`
> accepte désormais un `auth_ref` optionnel et, quand il est fourni, ne
> crée ni ne libère sa propre référence (délégué à l'appelant) —
> `MacosAuthorizedProcess`/`_launch_macos`/`launch_elevated_worker` le
> propagent tous jusqu'à `WorkerRunner`, qui l'extrait d'un
> `macos_auth_session` optionnel passé à son constructeur.
>
> `MainWindow._get_or_create_macos_auth_session()` en possède une seule
> pour toute l'application, créée **au premier besoin** plutôt qu'au
> lancement de l'app ou du parcours guidé lui-même — jamais avant qu'une
> opération élevée ne soit réellement lancée (principe déjà appliqué
> ailleurs dans ce projet : ne jamais demander une permission avant d'en
> avoir besoin). Elle est ensuite réutilisée par tout `WorkerRunner`
> suivant, mode expert et mode assisté confondus — pas seulement au sein
> d'un seul parcours guidé, mais pour toute la durée de vie de la
> fenêtre : enchaîner par exemple une sauvegarde complète puis un flash
> en mode expert ne redemande donc désormais qu'une seule fois l'invite,
> pas deux.
>
> Portée volontairement limitée à macOS packagé
> (`MacosAuthorizedProcess`) : `osascript` (macOS en développement, ou
> repli si l'API historique disparaissait) ne consomme aucune
> `AuthorizationRef` et n'est pas concerné ; `pkexec`/`sudo` (Linux) et
> UAC (Windows) n'ont pas d'équivalent léger de ce genre dans ce
> squelette — ce correctif ne change donc rien pour ces deux OS, qui
> continuent de redemander l'élévation à chaque worker élevé comme
> avant. Une `MacosAuthorizationSession` non créable (`OSError`, ex.
> Security.framework indisponible) retombe silencieusement sur le
> comportement d'origine (une référence par opération) plutôt que
> d'empêcher l'opération.


---

