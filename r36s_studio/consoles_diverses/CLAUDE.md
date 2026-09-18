# Consoles diverses — étape 1 : mode recherche

> Sous-brief du package `r36s_studio/consoles_diverses/`. Complète (ne
> remplace pas) `CLAUDE.md` à la racine du dépôt.

**Statut : étape 1 terminée** (recherche + affichage de la fiche,
réglages). Voir `docs/consoles-diverses-recherche.md` pour le brief
d'origine et les prochaines étapes (analyse de carte SD, installation,
contributions, dédoublonnage des jeux).

## Règle d'isolation

Ce package est volontairement indépendant du reste de R36S Studio :

- Il n'appelle jamais le worker élevé, `imaging/`, `partitions/`, `devices/`
  ni `safety/` -- un simple appel HTTP en lecture, rien à voir avec
  l'écriture disque brute (§3 de CLAUDE.md racine).
- Toutes ses chaînes vivent dans `consoles_diverses/strings.py`, jamais dans
  `gui/strings.py`.
- Le code R36S existant n'est modifié qu'au strict minimum pour le point
  d'entrée dans la navigation : un signal et un bouton sur `HomeScreen`/
  `AssistedLandingScreen` (`gui/screens.py`), leur câblage dans
  `gui/main_window.py`, et un champ dans `AppConfig` (`config.py`). Rien
  d'autre.

## Contrat serveur

Le serveur (`r36s-studio-cloud`, projet séparé, documentation lue en
lecture seule -- jamais `.dev.vars`) expose `POST /recherche` :

```
POST /recherche
Content-Type: application/json
X-Licence-Key: (toujours envoyé, même vide)

{"reference": "..."}
```

Réponses : `200 {"statut": "trouve_dans_catalogue"|"trouve_par_ia"|
"aucune_information_trouvee", ...}`, ou une erreur (`400 reference_
invalide`, `403 licence_requise`/`licence_invalide`, `500 configuration_
manquante`, `503 recherche_ia_indisponible`, `502 erreur_api_ia`/
`reponse_ia_non_json`). Côté client (`client.py`) s'ajoutent
`serveur_injoignable`, `delai_depasse` et `reponse_invalide` (réponse
absente/malformée/trop grande). Une fiche `console` suit
`r36s-studio-catalogue/schema/console.schema.json` (`models.py` en fait un
parsing défensif : seuls les champs d'identité indispensables font échouer
le parsing).

✅ **Serveur de production en ligne, confirmé en conditions réelles** :
`https://r36s-studio-cloud.r36studio.workers.dev` (HTTPS, derrière
Cloudflare -- distinct du serveur local de développement,
`http://localhost:8787`, qui n'a pas Cloudflare devant lui).

⚠️ **Bug corrigé, confirmé sur du vrai serveur en ligne** : une recherche
qui fonctionnait contre le serveur local échouait contre le serveur de
production avec `reponse_invalide` (« Le serveur a renvoyé une réponse
inattendue »). Cause : `urllib.request` n'envoie aucun en-tête `User-
Agent` explicite par défaut, retombant sur `"Python-urllib/{version}"` --
une signature que Cloudflare bloque par défaut (403, `error code: 1010`)
avant même que la requête n'atteigne le Worker. Confirmé en isolant la
piste (curl avec différents en-têtes `User-Agent`, requête sinon
identique) : ni la compression (aucun `Content-Encoding` sur la réponse),
ni l'URL, ni le corps, ni l'encodage n'étaient en cause --
`python-requests/...` n'est pas bloqué, ce n'est donc pas une règle
générique anti-script. `client.py` envoie désormais un en-tête `User-
Agent` explicite (`USER_AGENT`, `"R36S-Studio/{version}"`) sur chaque
requête -- même principe déjà suivi côté serveur pour ses propres
requêtes sortantes vers GitHub/Handhelds Wiki
(`r36s-studio-cloud/lib/sources/userAgent.ts`, lu en lecture seule).

Un échec HTTP dont le corps n'est pas la forme `{"erreur": ...}` attendue
(ex. le blocage Cloudflare ci-dessus) est désormais consigné dans le même
journal que les fiches rejetées (`client.py::_journaliser_erreur_http_
inattendue`, `gui/logs.py::consoles_diverses_log_path`) -- statut HTTP et
extrait du corps, tronqué. Un code `{"erreur": ...}` bien formé du
serveur (licence invalide, référence invalide...) n'est lui jamais
journalisé, ce n'est pas un incident.

## Durcissement (une fiche est une donnée externe non fiable)

Le serveur peut renvoyer une fiche générée par IA (`statut: "non_
verifie"`), jamais vérifiée par un humain. Quatre mesures :

1. **Texte brut, jamais interprété** (`screen.py::_plain_label`) --
   `QLabel.setTextFormat(Qt.PlainText)` sur tout texte venu du serveur.
2. **Liens restreints à http(s)** (`screen.py::_est_url_externe_sure`) --
   `file:`/`javascript:`/un chemin local/un schéma absent restent du texte
   simple, jamais un lien ouvert automatiquement.
3. **Adresse du serveur restreinte** (`settings_store.py::
   valider_adresse_serveur`) -- `https://` toujours accepté, `http://`
   seulement pour `localhost`/`127.0.0.1` (sinon la clé de licence
   circulerait en clair).
4. **Réponse plafonnée à 1 Mio** (`client.py::MAX_RESPONSE_BYTES`) avant
   tout `json.loads`.

## Clé de licence : trousseau système, avec repli

`settings_store.py` stocke la clé via `keyring`, jamais en clair dans
`AppConfig`/`config.json`. Si aucun backend `keyring` n'est disponible
(`trousseau_disponible()` renvoie `False` -- typiquement Linux sans
`SecretService`/`kwallet` actif), la clé reste **uniquement en mémoire
pour la session**, jamais écrite sur disque en clair à la place --
`settings_dialog.py` affiche alors un message explicite plutôt qu'un
échec silencieux.

⚠️ **Non vérifié sur du vrai matériel au moment d'écrire cette note** :
seul Windows (Credential Manager, backend natif toujours disponible) a pu
être testé lors de l'implémentation initiale. Le comportement sur macOS
(Keychain) et sur un Linux sans trousseau de bureau (repli mémoire-session
réel) reste à confirmer au premier essai sur ces plateformes.

**Packaging, corrigé après vérification sur du vrai binaire.** L'hypothèse
initiale (PyInstaller ne détecterait pas seul les backends `keyring`,
nécessitant un `hiddenimports` manuel par OS dans `packaging/*.spec`) était
fausse. Construit et inspecté directement (`packaging/r36s_studio_windows.
spec`, `pyinstaller` réel, PYZ embarqué décompressé et listé) : PyInstaller
fournit son propre hook officiel (`hook-keyring.py`,
`collect_submodules('keyring.backends')` + `copy_metadata('keyring')`) qui
s'applique automatiquement dès que `keyring` est importé -- les neuf
sous-modules de `keyring.backends` (`Windows`, `macOS`, `SecretService`,
`kwallet`, `libsecret`, `chainer`, `fail`, `null`, `macOS.api`) et les
métadonnées `keyring-*.dist-info` (indispensables : `keyring` découvre ses
backends via les points d'entrée setuptools de sa propre métadonnée) sont
tous présents dans le binaire construit, sans aucune déclaration manuelle.
Un appel réel `enregistrer_licence`/`lire_licence`/`effacer_licence` depuis
le binaire compilé (Windows Credential Manager) a fonctionné correctement.
Les trois fichiers `.spec` ont été simplifiés en conséquence (retrait des
`hiddenimports` ajoutés par hypothèse). **macOS et Linux restent non
vérifiés sur du vrai matériel** -- le hook lui-même n'est pas conditionné à
l'OS, donc la même collecte s'applique en théorie aux trois plateformes,
mais seul le binaire Windows a été réellement construit et testé à ce
jour.

## Hors périmètre (étape 1)

Analyse de carte SD (`detection_sd` du schéma non affiché), installation ou
téléchargement d'un firmware/frontend depuis cette section (liens externes
ouverts au navigateur uniquement, jamais de téléchargement automatique),
contribution/soumission au catalogue, cache local des fiches consultées,
sous-commande CLI de diagnostic, dédoublonnage des jeux (détecter qu'un
jeu déjà présent sur la carte correspond à un jeu qu'on s'apprête à
recopier). `pr_creee`/`connecteurs` (diagnostic serveur) ne sont jamais
affichés à l'utilisateur.

## Tests

Toute communication réseau passe par un paramètre `opener` injectable
(`client.py::Opener`, même principe que `identify/rocknix.py`) -- aucun
test de ce package ne fait un appel réseau réel. `keyring` est monkeypatché
dans `tests/test_consoles_diverses_settings.py`, jamais un vrai trousseau
système lu ou écrit pendant la suite.
