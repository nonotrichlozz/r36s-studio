# Packaging, CI et diffusion

**Diffusion (à jour, prime sur les paragraphes historiques ci-dessous).**
Modèle : code public, installeurs **vendus sur une boutique**, jamais
téléchargeables depuis GitHub. `release.yml` (tag `v*` = `v` +
`APP_VERSION`, sinon échec) crée une Release **brouillon** (visible des
seuls membres du dépôt) avec `R36S-Studio-Setup.exe` (Inno Setup,
`packaging/windows_installer.iss` : sans UAC, `{localappdata}\Programs`,
`AppId` fixe — ne jamais le changer, sinon une mise à jour s'installe à
côté de l'ancienne), `R36S-Studio-macOS.dmg` (`build_macos.sh dmg`) et
`R36S-Studio-Linux.tar.gz` (non bloquant, pas encore d'AppImage). Test de
fumée Windows : installation `/VERYSILENT` puis `R36S Studio.exe
--version`. Artefacts Actions : passage entre jobs uniquement, rétention
1 jour (sur un dépôt public, tout compte connecté peut les télécharger) ;
`build.yml` n'en produit plus. `scripts/publish_release.sh <tag>` retire
tous les fichiers du brouillon, refuse de continuer s'il en reste, puis
publie (code + notes `packaging/RELEASE_NOTES.md`). Licence : PolyForm
Strict 1.0.0 (`LICENSE`, en-tête de deux lignes dans chaque `.py`).
`THIRD_PARTY_NOTICES.txt` (textes officiels, jamais réécrits de mémoire)
et `LICENSE.txt` sont livrés avec l'installeur, le `.dmg` et le `.tar.gz`.
Les trois specs excluent les modules Qt inutilisés (`_EXCLUDED_QT`) :
Qt Virtual Keyboard n'existe qu'en GPL v3/commercial -- jamais dans le
paquet. Ajouter un module Qt = vérifier sa licence (LGPL v3 obligatoire)
et mettre à jour `THIRD_PARTY_NOTICES.txt`. Page `STORE_URL` :
`docs/site/index.html`, publiée par `pages.yml` (Pages, source « GitHub
Actions »). Icône :
`packaging/r36s_studio.ico` (générée depuis `gui/assets/console.png`).

**Vérification des mises à jour** (`update_check.py`, `UpdateCheckRunner`,
`UpdateControls`/`UpdateDialog` sur les deux accueils) : lancée par
`app.py::run` (jamais par le constructeur de `MainWindow`, donc jamais en
test), au plus une fois par jour (`config.json::last_update_check`),
désactivable (`check_updates`). Toute erreur réseau = silence. Dernière
version trouvée mémorisée (`latest_update_tag`/`latest_update_notes`) :
badge aux lancements suivants sans réseau, jusqu'à ce qu'`APP_VERSION` la
rattrape. Bouton « Obtenir la nouvelle version » → `update_check.
STORE_URL` (page GitHub Pages `docs/site/`, publiée par `pages.yml`, qui
redirigera vers la boutique), jamais un lien de téléchargement GitHub. Badge
masqué tant qu'une opération est en cours, réévalué à chaque
`_on_worker_finished`.

À lire quand tu touches à `packaging/`, aux fichiers `.spec`, à `.github/workflows/build.yml` ou à la publication d'une release.

> Les renvois « §N » de ce texte désignent les sections de l'ancien `CLAUDE.md` monolithique (commit `930f3c9`) : §3 → `elevation-macos.md`, §4.1/§4.2 → `devices-safety.md`, §4.3 → `imaging.md`/`reset-card.md`, §4.4 → `partitions.md`, §4.5 → `detect.md`, §4.6 → `firmwares-flash.md`, §5 → `interface.md`/`assisted-wizard.md`, §6 → `packaging.md`, §8 → `testing.md` ; §1/§2/§9 restent dans `CLAUDE.md`.

> 📚 Historique détaillé (bugs corrigés, investigations) : `docs/bugs-packaging.md`

**Pile :** Python 3.11+, PySide6, PyInstaller.

**Le problème des machines de compilation :** PyInstaller ne sait pas compiler pour un
autre système que celui sur lequel il tourne. Or l'Eee PC est en i686 32 bits — il ne
peut pas produire de binaire Linux moderne, et le MacBook 2015 ne produira qu'un binaire
Intel (qui tournera néanmoins sur Apple Silicon via Rosetta).

**Solution :** GitHub Actions. Trois jobs parallèles (`windows-latest`, `macos-latest`,
`ubuntu-22.04`), chacun produisant son artefact, publiés automatiquement en Release à
chaque tag. C'est gratuit pour un dépôt public et ça règle le problème définitivement.

✅ **CI en place (phase 7)**, le point ci-dessus étant désormais tranché
(blocage TCC résolu et confirmé sur du vrai matériel, §3). `packaging/
r36s_studio_windows.spec`/`r36s_studio_linux.spec` reprennent le même
squelette que le spec macOS (mêmes `datas` : horodatage de construction,
illustrations optionnelles) mais sans les éléments propres au bundle
macOS (`BUNDLE`, `Info.plist`, identifiant de paquet) — inutiles ici,
l'élévation Windows (UAC/`ShellExecuteW`) et Linux (`pkexec`/`sudo`)
relance directement le binaire lui-même (`sys.executable`, §3) sans
identité de paquet à obtenir au préalable, contrairement à macOS.
`packaging/build_windows.ps1`/`build_linux.sh` sont les scripts de
construction correspondants, symétriques de `build_macos.sh`.

`.github/workflows/build.yml` : trois jobs (`windows`, `macos`, `linux`)
lancent `python -m pytest` puis construisent et empaquettent leur
binaire (`.zip` Windows/macOS via `Compress-Archive`/`ditto`, `.tar.gz`
Linux) sur **chaque push sur `main` et chaque pull request** — pas
seulement au moment de taguer une version, pour détecter une régression
ou une construction cassée avant qu'elle n'atteigne un tag. Un quatrième
job (`release`) ne se déclenche que sur un tag `v*` et seulement si les
trois autres ont réussi (`needs:`), télécharge les trois artefacts et
publie une Release GitHub (`softprops/action-gh-release`). Procédure de
publication documentée dans `README.md`.

**Linux, dépendances Qt système** : un runner `ubuntu-22.04` nu ne
fournit pas les bibliothèques partagées dont PySide6/Qt a besoin même en
mode `offscreen` (celui qu'utilise la suite de tests, `tests/
conftest.py`) — sans elles, l'import de PySide6 échoue dès le premier
test GUI avec une erreur de bibliothèque manquante, pas une erreur Qt
explicite. Le job `linux` installe donc un jeu de paquets `apt`
(`libegl1`, `libxkbcommon0`, `libxcb-cursor0`...) avant `pip install`,
non vérifié sur un vrai runner GitHub au moment d'écrire cette note
(liste dérivée des dépendances Qt6/PySide6 headless documentées par la
communauté, pas d'accès à un runner Linux pour confirmer en conditions
réelles ici) — à corriger au premier échec CI si la liste s'avère
incomplète.

**Linux, `.tar.gz` plutôt qu'AppImage** : le brief (§6 ci-dessous)
évoque un AppImage pour Linux, mais un AppImage complet demande au
minimum une icône dédiée et un fichier `.desktop` — ni l'un ni l'autre
n'existe encore dans ce dépôt (`icon=None` aussi côté macOS/Windows). Un
simple dossier PyInstaller onedir compressé en `.tar.gz` couvre le besoin
immédiat (un artefact téléchargeable et exécutable par OS) sans
introduire un outil de packaging supplémentaire non vérifiable ici. Idée
future, pas implémentée : un vrai AppImage une fois une icône disponible.

✅ **Windows : construction réelle vérifiée sur du vrai matériel (phase
9, en vue de la diffusion publique).** `packaging/r36s_studio_windows.
spec`/`build_windows.ps1` existaient déjà (phase 7, commit `7b5086e`)
mais n'avaient jamais été réellement exécutés puis inspectés sur ce
dépôt -- fait ici : `pyinstaller packaging/r36s_studio_windows.spec`
produit bien `dist/R36S Studio/R36S Studio.exe` en mode **onedir**
(`EXE(exclude_binaries=True)` + `COLLECT`, jamais `onefile`) avec
`_internal/PySide6/` contenant 13 DLL Qt distinctes (`Qt6Core.dll`,
`Qt6Widgets.dll`...), jamais fusionnées dans l'exécutable -- condition
nécessaire pour respecter la LGPLv3 de PySide6 (la bibliothèque doit
rester remplaçable par l'utilisateur final, voir `packaging/README.md`
§Windows-2 pour le détail). Le binaire fonctionne aussi comme CLI
autonome : `R36S Studio.exe list` a correctement listé le vrai lecteur
de carte SD de cette machine (`Realtek PCIE CardReader`, déjà documenté
ailleurs dans ce fichier).

**Élévation une fois empaqueté, code déjà correct mais jamais vérifié en
conditions réelles avant ce jour.** `gui/elevate.py::_worker_command`
teste déjà `sys.frozen` de façon commune aux trois OS (aucune branche
Windows spécifique) et relance alors `sys.executable` -- qui pointe vers
**ce binaire lui-même** une fois empaqueté, jamais vers un `python.exe`
absent -- avec les mêmes arguments CLI, exactement comme macOS
(`AuthorizationExecuteWithPrivileges`). Déjà couvert par un test unitaire
dédié (`test_worker_command_when_frozen_skips_module_bootstrap`). **Non
vérifié ici, et à faire avant la première diffusion publique** : le tour
complet réel -- déclencher une action élevée (sauvegarde/flash/éjection)
depuis ce binaire précis, accepter l'invite UAC qui apparaît, confirmer
que le worker élevé résultant est bien à nouveau `R36S Studio.exe`. Cette
étape demande un geste humain (accepter l'invite UAC) qu'aucun outil
automatisé ne peut effectuer à la place de qui construit ce binaire.

**CI déjà branchée pour les trois OS, jamais encore déclenchée pour de
vrai.** `.github/workflows/build.yml` construit déjà les trois binaires
à chaque push/PR sur `main`, et le job `release` publie déjà une Release
GitHub avec les trois artefacts dès qu'un tag `v*` est poussé -- mais
aucun tag n'a jamais été créé sur ce dépôt (`git tag -l` vide au moment
d'écrire cette note) : aucune Release, donc aucun binaire réellement
téléchargeable n'existe encore pour un visiteur du dépôt, malgré une
infrastructure de construction déjà complète et fonctionnelle. Rester
volontairement sans avis sur le choix du numéro de version et le moment
de créer ce premier tag -- décision de diffusion, pas une question
technique.

**Fichiers de données du paquet** : tout fichier non-Python lu à l'exécution (ex. `doublons/data/extensions.json`) doit être déclaré dans les trois `.spec`, sans condition `.exists()` s'il est obligatoire ; `tests/test_packaging_specs.py` le vérifie. Récit du plantage au double-clic dans `docs/bugs-packaging.md`.

**Écran de démarrage** (`gui/app.py::_build_splash`) : `MainWindow` détecte
la carte de façon synchrone dans son constructeur -- mesuré à ~25 s sur une
vraie machine Windows avant l'apparition de la moindre fenêtre (PowerShell
`Get-Disk`/`Get-Partition` lents sur cette machine). Un `QSplashScreen`
(« Démarrage… recherche de ta carte SD ») s'affiche désormais ~5 s après le
double-clic (temps de chargement de Python/Qt), avant la construction de
`MainWindow`, sans en changer l'ordre d'initialisation. Idée future : sortir
cette détection initiale du thread principal pour afficher l'accueil
immédiatement.

Aucune icône configurée côté Windows (`icon=None`, comme macOS/Linux) --
à ajouter avant une vraie diffusion, pas bloquant pour cette
vérification.

**Signature :**

- **Windows** — sans certificat, SmartScreen affichera un avertissement. Il s'atténue
  avec le nombre de téléchargements. Un certificat coûte 200–400 €/an : à ne pas faire
  au départ.
- **macOS** — sans notarisation (99 $/an), Gatekeeper bloque l'ouverture. Le contournement
  est un clic droit → Ouvrir. À documenter clairement, idéalement dans ta vidéo.

- **Linux** — `.tar.gz` (pas encore d'AppImage), aucun souci de signature.

**Fichier de configuration utilisateur** (`~/.config/r36s-studio/config.json`, `%APPDATA%\r36s-studio\` sous Windows) : `ui_mode`, `firmware`, `doublons_recent_destinations`… (voir `config.py::AppConfig`). Jamais de secret. Même fichier lu par le binaire empaqueté et par les sources.
