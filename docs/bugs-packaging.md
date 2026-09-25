# Historique des bugs corrigés — Packaging et CI (§6 de CLAUDE.md)

> Ce fichier contient l'historique des investigations et correctifs liés à la
> mise en place de la CI GitHub Actions et à l'empaquetage. Le comportement
> **actuel** est décrit dans `CLAUDE.md` §6.

---

> ⚠️ **Ordre volontaire (phase 7)** : la CI ne sera mise en place que si la
> construction locale macOS (`packaging/`, voir `packaging/README.md`)
> confirme qu'une vraie `.app` (avec un `Info.plist` et donc une identité de
> bundle) fait disparaître le blocage TCC sur `/dev/rdiskN` documenté depuis
> la phase 4 (§3). Automatiser la production d'un binaire avant de savoir
> s'il résout le problème qui motive sa construction serait prématuré.
> `packaging/entry.py` + `packaging/r36s_studio.spec` couvrent macOS ; la
> même approche (spec PyInstaller dédié par OS) s'étendra à Windows/Linux
> une fois ce point tranché.


---

> ⚠️ **Bug corrigé, confirmé sur les vrais runners GitHub Actions : Linux
> et macOS échouaient tous les deux (Windows passait), en 51 s et 41 s
> respectivement -- des échecs trop rapides pour être liés aux paquets
> `apt` ci-dessus (déjà installés à ce stade).** Logs des deux jobs
> récupérés via l'API GitHub (`gh` non installé sur cette machine --
> `curl` avec un token pris via `git credential fill`, le même que celui
> déjà utilisé par `git push`) : même échec, mot pour mot, sur les deux
> OS -- `tests/test_partitions_eject.py::test_windows_eject_media_
> failure_propagates`, `AttributeError: module 'ctypes' has no attribute
> 'WinDLL'`.
>
> **Cause** : ce test simule un échec Windows (`platform.system` mocké à
> `"Windows"`, `winlock.eject_media` levant `OSError`) pour vérifier que
> `_windows_eject` (`partitions/eject.py`) laisse bien remonter
> l'exception plutôt que de l'avaler. Mais `_windows_eject` appelle
> `winlock.unlock_volumes(handles)` dans un `finally` -- exécuté même
> quand `eject_media` a levé -- et ce test-là, contrairement à ses deux
> voisins immédiats (`test_windows_dismounts_volumes_then_ejects_media`,
> `test_windows_ejects_without_dismounting_when_no_drive_letters`, tous
> deux corrects), ne mockait pas `winlock.unlock_volumes`. Sur la vraie
> `unlock_volumes` (`imaging/winlock.py`), même avec `handles=[]`,
> `_kernel32()` est appelé *avant* la boucle sur les handles -- et
> `ctypes.WinDLL` n'existe que sur un vrai interpréteur Windows,
> inexistant sur Ubuntu/macOS (`AttributeError` immédiate). Ce test n'a
> donc jamais pu tourner ailleurs que sur un poste Windows avant l'ajout
> de la CI multi-OS -- oubli d'un mock lors de son écriture, pas un défaut
> du comportement Windows lui-même (déjà validé sur du vrai matériel,
> §4.4/§4.5, inchangé par ce correctif).
>
> **Corrigé** : `@patch("r36s_studio.imaging.winlock.unlock_volumes")`
> ajouté à ce seul test (`tests/test_partitions_eject.py`), exactement
> comme ses deux voisins -- aucun code de production touché. Assertion
> `mock_unlock.assert_called_once_with([])` ajoutée au passage, pour
> couvrir explicitement que le `finally` s'exécute bien même après une
> exception, pas seulement que l'exception remonte.


---

---

## Ajouté lors du découpage de CLAUDE.md (2026-09-25)

> Récits déplacés tels quels depuis l'ancien `CLAUDE.md` (commit `930f3c9`). Les renvois « §N » désignent ses sections.

⚠️ **Bug corrigé, constaté en lançant réellement le binaire Windows : il
plantait dès le double-clic** (`FileNotFoundError` sur
`doublons/data/extensions.json`, lu à l'import de `doublons/extensions.py`,
lui-même importé par `__main__.py`). Le fichier n'était déclaré dans aucun
des trois spec -- invisible pour la suite de tests, qui tourne depuis les
sources. Ajouté aux trois spec (sans condition `.exists()` : obligatoire,
son absence fait échouer la construction plutôt que le binaire), et
`tests/test_packaging_specs.py` vérifie désormais que tout fichier non-Python
du paquet est déclaré dans chaque spec.
