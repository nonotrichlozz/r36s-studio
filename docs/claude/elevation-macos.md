# Élévation de privilèges et spécificités macOS

À lire quand tu touches à `gui/elevate.py`, `gui/worker_runner.py`, à l'Accès complet au disque (TCC) ou à la fenêtre du worker élevé.

> Les renvois « §N » de ce texte désignent les sections de l'ancien `CLAUDE.md` monolithique (commit `930f3c9`) : §3 → `elevation-macos.md`, §4.1/§4.2 → `devices-safety.md`, §4.3 → `imaging.md`/`reset-card.md`, §4.4 → `partitions.md`, §4.5 → `detect.md`, §4.6 → `firmwares-flash.md`, §5 → `interface.md`/`assisted-wizard.md`, §6 → `packaging.md`, §8 → `testing.md` ; §1/§2/§9 restent dans `CLAUDE.md`.

> 📚 Historique détaillé (bugs corrigés, investigations) : `docs/bugs-architecture.md`

**Détails de mécanisme actuellement en place, utiles pour ne pas les redécouvrir :**

- Un vrai événement `"error"` reçu du worker élevé prime toujours sur un
  `ELEVATION_FAILED` synthétisé côté GUI par timeout (`WorkerRunner._error_emitted`) —
  `finished.emit(False)` n'est de toute façon émis qu'une seule fois, quelle que soit l'issue.
- macOS en développement (sans bundle) : `osascript … with administrator privileges`
  élève bien le worker, mais **ne peut pas accéder à `/dev/rdiskN`** même avec le
  Terminal en Accès complet au disque — TCC ne propage aucune identité au
  processus enfant d'`osascript`.
- macOS une fois empaqueté : `gui/elevate.py` relance le worker directement
  depuis le binaire du bundle (`sys.executable`) via `AuthorizationExecuteWithPrivileges`
  (`Security.framework`, classe `MacosAuthorizedProcess`) plutôt que `osascript` —
  un enfant direct du binaire signé hérite de l'Accès complet au disque du bundle.
  `osascript` reste utilisé en développement et comme repli si cette API
  (non documentée par Apple depuis macOS 10.7) venait à disparaître.
- La signature ad hoc du bundle change à chaque reconstruction
  (`packaging/build_macos.sh`) : l'autorisation Accès complet au disque doit être
  **retirée puis rajoutée** (jamais juste désactivée/réactivée) après chaque nouveau
  build — voir `packaging/README.md` §4.
- Deux codes d'erreur macOS distincts : `MACOS_TCC_BLOCKED` (périphérique brut
  `/dev/rdiskN`) et `MACOS_TCC_PROTECTED_FOLDER` (un fichier ordinaire dans
  Téléchargements/Bureau/Documents) — les deux renvoient vers les réglages
  d'Accès complet au disque, jamais vers `sudo`.
- Une seule `MacosAuthorizationSession` (une `AuthorizationRef`) est créée à la
  demande, au premier besoin, et réutilisée pour toute la durée de vie de
  l'application — partagée par tous les `WorkerRunner` (mode expert et assisté
  confondus), pour ne demander le mot de passe administrateur qu'une fois par
  session plutôt qu'à chaque étape élevée. Ne s'applique qu'à macOS empaqueté :
  Windows (UAC) et Linux (`pkexec`/`sudo`) redemandent l'élévation à chaque worker.
- Tout signal Qt transportant une taille en octets doit être déclaré `"qint64"`,
  jamais un `int` nu — PySide6 laisse silencieusement tomber l'`emit()` au-delà
  d'environ 2,1 Go (dépassement d'un entier 32 bits) sans lever d'exception.

**Écran de bienvenue macOS, détection proactive de l'Accès complet au
disque (phase 9).** Jusqu'ici, l'absence de cette autorisation n'était
détectée qu'*après coup* : l'utilisateur devait lancer une opération,
attendre l'échec (`MACOS_TCC_BLOCKED`), puis ouvrir l'Aide pour
comprendre pourquoi. `gui/elevate.py::has_full_disk_access` détecte
l'autorisation *avant* toute tentative d'écriture, sans élévation :
`~/Library/Application Support/com.apple.TCC` est un dossier protégé
par TCC dont la simple lecture (`os.listdir`) échoue avec
`PermissionError` tant que ce processus n'a pas reçu l'Accès complet au
disque — TCC s'applique à l'identité du processus, pas à ses privilèges
Unix, donc cette sonde n'a besoin d'aucun mot de passe administrateur
pour donner une réponse fiable. `True` par défaut hors macOS (ce
blocage lui est spécifique) et en cas d'erreur autre que la lecture
elle-même du dossier n'est jamais affirmé sans preuve positive.

`gui/screens.py::FullDiskAccessScreen` (nouvel écran, ajouté à
`_root_stack` aux côtés de `MainView`/`AssistedLandingScreen`) remplace
l'accueil habituel — assisté ou expert, quel que soit `ui_mode` — tant
que `has_full_disk_access()` renvoie `False` au démarrage, macOS
uniquement. Explique la procédure (texte repris de `HelpDialog`, adapté
au premier lancement) avec un bouton « Ouvrir les réglages » (même lien
profond que `HelpDialog`, `_on_open_settings_requested` partagé) et un
bouton « J'ai terminé » qui revérifie : détectée, `MainWindow.
_show_startup_screen()` (factorisé depuis la logique de démarrage
existante) affiche l'accueil habituel et cet écran ne réapparaît plus
pour la session en cours ; toujours absente, un message dédié
s'affiche plutôt qu'un clic silencieusement ignoré (§5). Construit
inconditionnellement (même principe que `HelpDialog`, dont le bouton
déclencheur n'apparaît lui aussi que sur macOS) mais n'est choisi comme
écran de démarrage que sur macOS — un `has_full_disk_access` à `False`
sur un autre OS (accident de mock, comportement futur imprévu) ne fait
jamais apparaître cet écran ailleurs, testé explicitement.

Tests (`tests/test_gui_elevate.py`, `tests/test_gui_screens.py`,
`tests/test_gui_main_window.py`) : `has_full_disk_access` lisant un vrai
dossier protégé par TCC, son résultat dépendrait sinon de l'autorisation
réelle du terminal qui lance la suite sur une machine de dev macOS,
rendant les tests non déterministes selon la machine. Une autofixture
(`tests/conftest.py::_default_full_disk_access_granted`) la stub à
`True` par défaut pour tous les tests (comportement historique, avant
cet écran) ; les tests dédiés à `FullDiskAccessScreen` la repatchent
explicitement, et les tests de `has_full_disk_access` elle-même se
marquent `@pytest.mark.real_fda_probe` pour laisser passer leur propre
implémentation — même principe que `real_subprocess` (§8).

**`packaging/LISEZ-MOI.txt` et cible `dist` (§6, phase 9)** : la même
procédure (clic droit → Ouvrir pour Gatekeeper, puis Accès complet au
disque, à refaire après chaque mise à jour puisque la signature ad hoc
change à chaque reconstruction — ci-dessus) doit aussi atteindre un
utilisateur qui n'a pas encore ouvert l'app — l'écran de bienvenue
ci-dessus ne peut rien expliquer avant ce premier lancement bloqué par
Gatekeeper. `packaging/build_macos.sh dist` construit puis empaquette
directement `dist/R36S-Studio-macos.zip` (app + `LISEZ-MOI.txt`, mise
en scène dans un dossier temporaire puis `ditto`, jamais `zip -r` — même
raison que l'empaquetage CI ci-dessous : seul `ditto` préserve la
structure et les attributs étendus d'un vrai bundle `.app`) ; la CI
(`.github/workflows/build.yml`, job `macos`) appelle cette même cible
plutôt que de dupliquer la logique d'empaquetage — une seule source de
vérité sur le contenu de l'archive distribuée, locale comme CI.

✅ **Fenêtre de console du worker élevé masquée sur Windows** (§1/§3) --
`ShellExecuteExW` (`gui/elevate.py::_launch_windows`) ouvrait jusqu'ici
le worker élevé avec `nShow=SW_SHOWNORMAL` : une fenêtre de console
visible, vide en pratique (`ShellExecuteW` ne fournit aucun tube stdout/
stderr vers ce processus, §3 -- toute la communication passe déjà par
`--progress-file`/le journal d'élévation), qui clignotait à chaque
opération élevée sous les yeux d'un néophyte -- contraire à la règle §1
(« aucune ligne de commande, jamais, à aucune étape »). `nShow=SW_HIDE`
désormais. Sans risque identifié : rien ne lit jamais la sortie de cette
fenêtre, et le mécanisme d'élévation lui-même (verbe `runas`, détection
d'échec via le fichier de progression/le journal d'élévation) ne dépend
en rien de sa visibilité.
