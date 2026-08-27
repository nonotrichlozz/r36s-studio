# Construction locale macOS (phase 7)

Ce dossier construit une vraie `.app` macOS avec [PyInstaller](https://pyinstaller.org/),
uniquement pour un usage **local** pour l'instant — pas de CI, pas de
signature, pas de notarisation (§6 du brief : ça viendra plus tard, et
seulement si le point ci-dessous est confirmé).

**Pourquoi une vraie `.app` plutôt que lancer `python3 -m r36s_studio gui`
directement ?** Depuis la phase 4, l'élévation macOS (`osascript … with
administrator privileges`) obtient les droits root pour le worker mais ne
peut pas accéder à `/dev/rdiskN` : TCC (Transparency, Consent and Control)
filtre au-dessus des droits Unix, et un interpréteur `python3` nu relancé
par `osascript` n'a aucune identité propre à autoriser dans
Réglages Système → Confidentialité et sécurité → **Accès complet au
disque**. Une vraie `.app`, avec son propre `Info.plist` (identifiant de
bundle, nom, version), a cette identité — c'est ce qu'on vérifie ici.

## 1. Construire

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

## 2. Premier lancement

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

## 3. Vérifier l'accès disque — résolu (confirmé sur du vrai matériel)

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
   ouvre directement ce panneau.)
3. Lance l'app, branche une carte SD de test, lance une sauvegarde ou un
   flash jusqu'à l'écran d'exécution.
4. La copie doit progresser normalement jusqu'au bout. Si le blocage
   persiste (`MACOS_TCC_BLOCKED` / `[Errno 1] Operation not permitted` sur
   `/dev/rdiskN`), vérifie d'abord que l'app dans la liste Accès complet
   au disque correspond bien au binaire fraîchement reconstruit —
   **la signature ad hoc change à chaque reconstruction** et invalide
   l'autorisation précédente (retire puis rajoute l'entrée, ne te contente
   pas de désactiver/réactiver le bouton existant).

## 4. Reconstruire après un changement de code

Relance simplement `packaging/build_macos.sh` — PyInstaller régénère
`build/` et `dist/` à chaque fois. Comme l'app n'est pas signée, macOS peut
redemander une autorisation Accès complet au disque après une
reconstruction (le contenu du binaire a changé) ; si besoin, retire puis
rajoute l'app dans la liste plutôt que de désactiver/réactiver le bouton
existant, qui ne recharge pas toujours l'autorisation correctement.

## 5. Personnaliser avant une vraie diffusion

`packaging/r36s_studio.spec` fixe `BUNDLE_IDENTIFIER = "com.r36sstudio.desktop"`
comme valeur de départ. Un identifiant de bundle est ce que macOS retient
pour l'autorisation Accès complet au disque — le changer plus tard oblige
les utilisateurs à réautoriser l'app. À remplacer par un identifiant
stable et qui t'appartient (ex. `com.tonpseudo.r36sstudio`) avant toute
diffusion publique, puis à ne plus jamais changer.

Aucune icône n'est encore configurée (`icon=None` dans le spec) — à
ajouter avant diffusion, pas nécessaire pour cette vérification locale.

## 6. Numéro de version et horodatage de construction

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
