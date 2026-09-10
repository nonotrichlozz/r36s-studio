# R36S Studio

Application de bureau (Windows, macOS, Linux) pour préparer une carte SD de
console R36S sans ligne de commande : sauvegarder l'ancienne carte, flasher
ArkOS/ROCKNIX/EmuELEC sur une carte neuve, réinjecter l'écran d'origine et
copier les jeux — le tout depuis une interface graphique.

Le cahier des charges complet (contraintes de sécurité, architecture
GUI/worker, détail des modules) vit dans [`CLAUDE.md`](CLAUDE.md).

## Développement

Prérequis : Python 3.11+.

```sh
python3 -m venv .venv
source .venv/bin/activate          # .venv\Scripts\Activate.ps1 sous Windows
pip install -r requirements.txt -r requirements-dev.txt
```

Lancer l'assistant graphique sans rien construire :

```sh
python -m r36s_studio gui
```

L'app est aussi utilisable en ligne de commande (utile pour le
développement et le diagnostic — jamais exposé à l'utilisateur final,
§1/§5 de `CLAUDE.md`) : `list`, `backup`, `flash`, `extract-boot`,
`extract-easyroms`, `inject-boot`, `copy-games`, `identify`, `eject`.
Détail de chaque sous-commande :

```sh
python -m r36s_studio --help
python -m r36s_studio <sous-commande> --help
```

### Tests

```sh
python -m pytest
```

Aucun sous-processus réel n'est autorisé pendant les tests
(`tests/conftest.py` intercepte `subprocess.run`/`Popen` — voir §8 de
`CLAUDE.md`) : la suite entière tourne sans carte SD ni droits
administrateur, sur les trois OS.

## Construire un binaire localement

Chaque OS a son propre script de construction ([PyInstaller](https://pyinstaller.org/)) sous
`packaging/` :

| OS | Script | Résultat |
|----|--------|----------|
| macOS | `packaging/build_macos.sh` | `dist/R36S Studio.app` |
| Windows | `packaging/build_windows.ps1` | `dist/R36S Studio/R36S Studio.exe` |
| Linux | `packaging/build_linux.sh` | `dist/R36S Studio/R36S Studio` |

`packaging/build_macos.sh dist` construit puis produit en plus
`dist/R36S-Studio-macos.zip`, prêt à distribuer : l'app accompagnée de
`packaging/LISEZ-MOI.txt` (marche à suivre pour un utilisateur final —
autoriser l'app malgré Gatekeeper, puis lui accorder l'Accès complet au
disque). C'est cette même commande qu'utilise la CI (ci-dessous) pour
produire l'artefact macOS de chaque Release.

Chaque script crée son propre `.venv/` s'il n'existe pas déjà, installe les
dépendances, puis appelle le `.spec` PyInstaller correspondant
(`packaging/r36s_studio.spec` pour macOS, `..._windows.spec`,
`..._linux.spec`). Détail complet de la construction macOS — la seule à
avoir une contrainte particulière (accès disque bloqué par TCC tant que
l'app n'a pas d'identité de bundle propre, résolu depuis la phase 7) — et
de la procédure de vérification sur du vrai matériel : voir
[`packaging/README.md`](packaging/README.md).

Aucun des trois binaires n'est signé avec un certificat payant (§6 du
brief) : au premier lancement, Windows SmartScreen et macOS Gatekeeper
affichent un avertissement — pour macOS, clic droit sur l'app → Ouvrir.

## Intégration continue et publication d'une Release

`.github/workflows/build.yml` définit quatre jobs GitHub Actions :

- **Windows**, **macOS**, **Linux** (`windows-latest`, `macos-latest`,
  `ubuntu-22.04`) — chacun installe les dépendances, **lance la suite de
  tests complète** (`python -m pytest`), puis construit le binaire de son
  OS avec le script correspondant ci-dessus et l'empaquette
  (`.zip` pour Windows/macOS, `.tar.gz` pour Linux). Ces trois jobs
  tournent sur **chaque push sur `main`** et **chaque pull request** — un
  changement qui casse la construction ou une régression sur un OS
  particulier est visible avant merge, pas seulement en local sur la seule
  machine du contributeur (§7 du brief : la CI existe justement parce que
  les machines de développement disponibles ne peuvent chacune compiler
  que pour leur propre OS).
- **release** — ne se déclenche **que sur un tag** de la forme `v*` (ex.
  `v0.2.0`) et seulement si les trois constructions précédentes ont
  réussi (`needs:`). Télécharge les trois artefacts et les publie sur une
  [Release GitHub](../../releases) via `softprops/action-gh-release`, avec
  des notes de version générées automatiquement à partir des commits
  depuis le tag précédent.

### Publier une nouvelle version

```sh
git tag v0.2.0
git push origin v0.2.0
```

Le tag déclenche le workflow complet (tests + construction sur les trois
OS), puis, si tout est vert, la Release GitHub correspondante apparaît
automatiquement avec les trois binaires en pièces jointes — rien d'autre à
faire manuellement. Le numéro de version affiché dans l'app elle-même
(pied de page de l'écran d'accueil, `gui/build_info.py`) vient de
`r36s_studio/__init__.py::__version__`, à mettre à jour avant de poser le
tag pour que les deux restent cohérents.

## Licences

Ce projet est distribué sous licence **GNU General Public License version 3
(GPLv3)** — texte intégral dans [`LICENSE`](LICENSE). La dépendance
principale a des implications à connaître avant toute redistribution :

| Dépendance | Rôle | Licence |
|---|---|---|
| [PySide6](https://pypi.org/project/PySide6/) (Qt pour Python) | Interface graphique | [LGPLv3](https://www.gnu.org/licenses/lgpl-3.0.html) (alternative : licence commerciale Qt, payante — ce projet utilise la voie LGPL) |
| [pytest](https://pypi.org/project/pytest/) (dépendance de développement uniquement, jamais distribuée avec l'app) | Suite de tests | [MIT](https://github.com/pytest-dev/pytest/blob/main/LICENSE) |

**Obligation LGPLv3 de PySide6, et comment ce projet la respecte** : la LGPL
exige que l'utilisateur final puisse remplacer la bibliothèque Qt par une
version modifiée ou plus récente de son choix — impossible si elle est
fusionnée dans un exécutable opaque. Les trois constructions PyInstaller
produisent donc volontairement un dossier **onedir**, jamais un
**onefile** (voir [Construire un binaire
localement](#construire-un-binaire-localement) ci-dessus) : les
DLL/dylib/so de Qt restent des fichiers séparés dans `_internal/PySide6/`,
librement remplaçables sans recompiler l'application.

`gui/assets/console.png` est une photographie prise par l'auteur du projet,
qui en détient les droits — couverte par la licence de ce dépôt comme le
reste du code et des ressources.
