# Construction (Windows, macOS)

Ce dossier construit l'application avec [PyInstaller](https://pyinstaller.org/),
un OS à la fois — voir la section Windows ci-dessous, puis la section macOS
qui suit.

## Windows (phase 7/9)

### 1. Construire

```powershell
packaging/build_windows.ps1
```

Le script crée un environnement virtuel `.venv/` à la racine du projet s'il
n'existe pas déjà, y installe les dépendances (`requirements.txt`,
`requirements-dev.txt`, PyInstaller), puis lance PyInstaller sur
`packaging/r36s_studio_windows.spec`.

Résultat : `dist/R36S Studio/R36S Studio.exe`, accompagné d'un dossier
`_internal/` contenant l'interpréteur Python et les bibliothèques Qt. C'est
ce dossier complet (pas seulement l'exe) qu'il faut distribuer — vérifié en
construisant réellement ce paquet sur cette machine : `_internal/PySide6/`
contient bien 13 DLL Qt distinctes (`Qt6Core.dll`, `Qt6Widgets.dll`,
`Qt6Gui.dll`...), jamais fusionnées dans l'exécutable. Le CLI fonctionne
aussi directement depuis ce binaire (`R36S Studio.exe list` affiche
correctement les cartes détectées) — confirmé sur du vrai matériel, une
carte SD réelle sur le lecteur intégré de cette machine.

C'est aussi la commande utilisée par la CI (`.github/workflows/build.yml`,
job `windows`), qui empaquette ensuite tout le dossier `dist/R36S Studio/`
en `.zip` — même source de vérité que la construction locale.

### 2. Onedir, jamais onefile — obligatoire, pas une préférence

PySide6 est distribué sous licence LGPLv3 (ou, en alternative payante, une
licence commerciale Qt — ce projet utilise la voie LGPL, gratuite, §9 pour
le détail des licences des dépendances). La LGPL exige concrètement que
l'utilisateur final puisse remplacer la bibliothèque LGPL elle-même — ici,
les DLL Qt — par une version modifiée compatible, et que l'application
continue de fonctionner avec.

Un exécutable PyInstaller **onefile** ne permet pas ça : au lancement, il
extrait silencieusement tout son contenu (interpréteur Python et DLL Qt
comprises) dans un dossier temporaire caché, invisible et jetable, puis
charge tout depuis là. Rien n'y est exposé ni raisonnablement remplaçable
par un tiers — en pratique, ça revient à fusionner la bibliothèque LGPL
dans un binaire opaque, ce que ce projet évite délibérément.

Le mode **onedir** (déjà utilisé ici — `EXE(exclude_binaries=True)` suivi
de `COLLECT(...)` dans `packaging/r36s_studio_windows.spec`, jamais
`onefile=True`) garde chaque DLL Qt comme fichier séparé, à côté de
l'exécutable (`_internal/PySide6/Qt6*.dll`, confirmé ci-dessus) — n'importe
qui peut la remplacer directement, sans recompiler quoi que ce soit ni
extraire une archive cachée. C'est cette forme, jamais un onefile, qui doit
être distribuée (`.zip`, produit par la CI sur chaque tag `v*`, §6/§7 de
CLAUDE.md).

Les specs macOS et Linux (`r36s_studio.spec`, `r36s_studio_linux.spec`)
suivent déjà le même principe (`EXE(exclude_binaries=True)` + `COLLECT`,
jamais `onefile`) — cette contrainte n'est donc pas spécifique à Windows,
seule la section ci-dessus la documente explicitement pour l'instant.

### 3. Élévation une fois empaqueté — le worker se relance lui-même

Sans empaquetage, `gui/elevate.py` relance le worker élevé via
`sys.executable` = l'interpréteur `python.exe` du développeur, avec `-c` et
une insertion manuelle de `sys.path` (`_worker_command`, voir le docstring
de module) — nécessaire uniquement parce qu'aucun binaire autonome
n'existe encore à ce stade.

Une fois empaqueté, il n'y a plus de `python.exe` à côté : PyInstaller pose
`sys.frozen = True` sur le processus, et `_worker_command` en tient déjà
compte — `if getattr(sys, "frozen", False): return [sys.executable,
*argv]` bascule alors sur `sys.executable` pointant vers **ce binaire
lui-même** (`R36S Studio.exe`), rappelé directement avec les mêmes
arguments CLI (`backup`/`flash`/`eject`/...), exactement comme le fait déjà
macOS (`AuthorizationExecuteWithPrivileges`, §3 de CLAUDE.md). Ce chemin
est commun aux trois OS — aucune branche spécifique à Windows dans
`_worker_command` — et déjà couvert par un test unitaire dédié
(`tests/test_gui_elevate.py::test_worker_command_when_frozen_skips_module_bootstrap`).

**Ce qui est vérifié, et ce qui ne l'est pas encore.** Construit et lancé
réellement sur cette machine (§1 ci-dessus) : le binaire fonctionne comme
CLI autonome, `sys.frozen` vaut nécessairement `True` dans tout processus
issu de ce binaire (garanti par le bootloader PyInstaller lui-même, pas
quelque chose que ce projet doit re-vérifier). **Non vérifié ici** : le
tour complet réel — cliquer une action qui déclenche l'élévation
(sauvegarde, flash, éjection...) depuis ce binaire précis, accepter
l'invite UAC qui apparaît, et confirmer que le worker élevé qui en résulte
est bien à nouveau `R36S Studio.exe` (pas une tentative de relancer un
`python.exe` absent). Cette dernière étape demande un geste humain
(accepter l'invite UAC) qu'aucun outil automatisé ne peut effectuer à la
place de qui construit ce binaire — **à faire une fois, à la main, avant
la première diffusion publique**, avec une carte SD de test réelle.

### 4. Icône, SmartScreen

Aucune icône n'est encore configurée (`icon=None` dans le spec) — comme pour
macOS (§5 ci-dessous), à ajouter avant une vraie diffusion. Sans certificat
de signature de code, Windows SmartScreen affichera un avertissement
(« Windows a protégé votre ordinateur ») au premier lancement — voir le
README public pour le contournement à documenter côté utilisateur (§6 de
CLAUDE.md : un certificat coûte 200–400 €/an, à ne pas faire au départ).

## macOS (phase 7)

Cette section construit une vraie `.app` macOS, uniquement pour un usage
**local** pour l'instant côté signature/notarisation (§6 du brief : pas de
certificat Developer ID, pas de notarisation — ça viendra plus tard).

**Pourquoi une vraie `.app` plutôt que lancer `python3 -m r36s_studio gui`
directement ?** Depuis la phase 4, l'élévation macOS (`osascript … with
administrator privileges`) obtient les droits root pour le worker mais ne
peut pas accéder à `/dev/rdiskN` : TCC (Transparency, Consent and Control)
filtre au-dessus des droits Unix, et un interpréteur `python3` nu relancé
par `osascript` n'a aucune identité propre à autoriser dans
Réglages Système → Confidentialité et sécurité → **Accès complet au
disque**. Une vraie `.app`, avec son propre `Info.plist` (identifiant de
bundle, nom, version), a cette identité — c'est ce qu'on vérifie ici.

### 1. Construire

```sh
packaging/build_macos.sh
```

Le script crée un environnement virtuel `.venv/` à la racine du projet
s'il n'existe pas déjà, y installe les dépendances (`requirements.txt`,
`requirements-dev.txt`, PyInstaller), puis lance PyInstaller sur
`packaging/r36s_studio.spec`.

Résultat : `dist/R36S Studio.app`. `build/` et `dist/` sont ignorés par
Git (voir `.gitignore`) — ce sont des artefacts de construction, jamais à
committer.

Pour construire à la main sans le script (par exemple avec un
environnement déjà prêt) :

```sh
source .venv/bin/activate
pyinstaller --noconfirm packaging/r36s_studio.spec
```

**Archive prête à distribuer** : `packaging/build_macos.sh dist` construit
puis produit en plus `dist/R36S-Studio-macos.zip`, contenant l'app et
`packaging/LISEZ-MOI.txt` (instructions pour un utilisateur final : clic
droit → Ouvrir, puis Accès complet au disque). C'est cette même commande
qu'utilise la CI (`.github/workflows/build.yml`) pour produire l'artefact
de chaque Release — une seule source de vérité sur le contenu de
l'archive distribuée.

### 2. Premier lancement

L'app n'est ni signée avec un certificat Developer ID, ni notariée : au
premier lancement, Gatekeeper affichera un avertissement (« développeur non
identifié »). Contournement, à documenter aussi pour les futurs
utilisateurs (§6 du brief) : clic droit sur `R36S Studio.app` → **Ouvrir**,
puis confirmer dans la boîte de dialogue — une seule fois.

```sh
open "dist/R36S Studio.app"
```

Vérifie que l'assistant graphique s'affiche normalement (écran d'accueil à
six étapes, §4.5) — un double-clic depuis le Finder n'a jamais de
console : sans le repli sur la sous-commande `gui` (`__main__.main()`
quand aucun argument n'est fourni, ajouté à cette phase), l'app
semblerait juste ne rien faire.

### 3. Vérifier l'accès disque — résolu (confirmé sur du vrai matériel)

La question posée par cette construction locale est désormais tranchée
(CLAUDE.md §3) : la seule identité de bundle ne suffisait pas tant que
l'élévation passait par `osascript` (processus système sans rapport avec
le bundle). `gui/elevate.py` relance maintenant le worker directement
depuis ce binaire (`AuthorizationExecuteWithPrivileges`), et **un enfant
direct du binaire signé hérite bien** de l'autorisation Accès complet au
disque du bundle.

Procédure pour vérifier sur une nouvelle machine (ou après un changement
touchant l'élévation) :

1. Déplace ou copie `dist/R36S Studio.app` vers un emplacement stable
   (ex. `/Applications`) — un chemin qui ne bougera pas d'une
   reconstruction à l'autre facilite le suivi de l'autorisation TCC.
2. **Réglages Système → Confidentialité et sécurité → Accès complet au
   disque** → clique sur `+` → sélectionne `R36S Studio.app` → active le
   bouton. (Dans l'app elle-même, l'écran Aide accessible depuis
   l'accueil sur macOS explique cette même procédure, avec un bouton qui
   ouvre directement ce panneau. Tant que l'autorisation n'est pas
   détectée, un écran de bienvenue -- `gui/screens.py::
   FullDiskAccessScreen`, `elevate.has_full_disk_access` -- s'affiche
   automatiquement à la place de l'accueil habituel et propose ce même
   raccourci, sans qu'il soit nécessaire d'aller chercher l'écran Aide.)
3. Lance l'app, branche une carte SD de test, lance une sauvegarde ou un
   flash jusqu'à l'écran d'exécution.
4. La copie doit progresser normalement jusqu'au bout. Si le blocage
   persiste (`MACOS_TCC_BLOCKED` / `[Errno 1] Operation not permitted` sur
   `/dev/rdiskN`), vérifie d'abord que l'app dans la liste Accès complet
   au disque correspond bien au binaire fraîchement reconstruit —
   **la signature ad hoc change à chaque reconstruction** et invalide
   l'autorisation précédente (retire puis rajoute l'entrée, ne te contente
   pas de désactiver/réactiver le bouton existant).

### 4. Reconstruire après un changement de code

Relance simplement `packaging/build_macos.sh` — PyInstaller régénère
`build/` et `dist/` à chaque fois. Comme l'app n'est pas signée, macOS peut
redemander une autorisation Accès complet au disque après une
reconstruction (le contenu du binaire a changé) ; si besoin, retire puis
rajoute l'app dans la liste plutôt que de désactiver/réactiver le bouton
existant, qui ne recharge pas toujours l'autorisation correctement.

### 5. Personnaliser avant une vraie diffusion

`packaging/r36s_studio.spec` fixe `BUNDLE_IDENTIFIER = "com.r36sstudio.desktop"`
comme valeur de départ. Un identifiant de bundle est ce que macOS retient
pour l'autorisation Accès complet au disque — le changer plus tard oblige
les utilisateurs à réautoriser l'app. À remplacer par un identifiant
stable et qui t'appartient (ex. `com.tonpseudo.r36sstudio`) avant toute
diffusion publique, puis à ne plus jamais changer.

Aucune icône n'est encore configurée (`icon=None` dans le spec) — à
ajouter avant diffusion, pas nécessaire pour cette vérification locale.

### 6. Numéro de version et horodatage de construction

L'écran d'accueil affiche en pied de page `R36S Studio v{version} (build
du {date} à {heure})` (`gui/build_info.py`) — sans ça, impossible de
savoir si le binaire testé contient les derniers correctifs, en
particulier après plusieurs reconstructions locales de suite. `r36s_studio
.spec` génère cet horodatage à chaque construction dans
`build/build_timestamp.txt` (déjà ignoré par Git) et l'embarque via
`datas` ; à l'exécution, l'app le relit depuis `sys._MEIPASS` (pointe vers
`Contents/Frameworks` dans le `.app`, confirmé empiriquement — pas
`Contents/MacOS` comme on pourrait s'y attendre). En développement
(`python -m r36s_studio gui`), ce fichier n'existe pas : seul le numéro de
version (`r36s_studio.__version__`) s'affiche, avec la mention « version
de développement ».

Horodatage en **heure locale de la machine de construction**, pas UTC :
cette même machine sert aussi à tester le binaire juste après, l'UTC
n'ajouterait qu'une conversion mentale à chaque vérification sans aucun
bénéfice tant qu'il n'y a pas de diffusion multi-fuseaux (§7).
