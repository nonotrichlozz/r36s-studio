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
serveur (référence invalide...) n'est lui jamais journalisé, ce n'est pas
un incident -- exception : `licence_invalide`/`licence_requise`
consignent un diagnostic dédié (`client.py::_journaliser_diagnostic_
licence`), voir ci-dessous.

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

⚠️ **Bug corrigé (cause n°1), signalé par un utilisateur** : une clé
confirmée valide (`Invoke-RestMethod` contre le serveur de production
renvoie `trouve_dans_catalogue`) était refusée par la GUI (« La clé de
licence renseignée n'est pas reconnue par le serveur »). Cause :
`settings_dialog.py::_on_save` retirait déjà les espaces de l'adresse du
serveur (`.strip()`) mais jamais ceux de la clé de licence -- un
copier-coller laisse souvent un espace ou un retour à la ligne parasite
en tête/fin, jamais visible dans un champ masqué (`QLineEdit.Password`).
`settings_store.py::enregistrer_licence` applique `.strip()` avant tout
stockage (trousseau ou repli mémoire-session).

⚠️ **Bug corrigé (cause n°2, plus grave), même signalement, resurgi après
le correctif ci-dessus** : la clé restait refusée après plusieurs
ressaisies *et un redémarrage complet de l'app* -- le journal de
diagnostic montrait la même longueur, sans espace parasite, à chaque
tentative, preuve qu'une valeur figée était envoyée indépendamment de ce
qui était retapé. Cause réelle, trouvée en relisant `keyring.backends.
Windows.WinVaultKeyring.set_password` (lu en lecture seule, dépendance
tierce) : ce backend relit l'ancienne valeur et la réécrit sous une cible
composée (`{compte}@{service}`, simulation multi-utilisateur que
`WinVaultKeyring` documente lui-même) *avant* d'écrire la nouvelle --
et peut lever une exception à cette étape intermédiaire, avant que la
nouvelle valeur n'ait jamais été écrite. L'ancien `enregistrer_licence`
retombait alors correctement sur la mémoire-session en cas d'échec, mais
`lire_licence()` préférait quand même une relecture trousseau non vide --
qui rendait donc systématiquement l'ancienne valeur, jamais celle qu'on
venait de demander, quel que soit le nombre de tentatives.

**Corrigé** : `_licence_memoire_session` porte désormais la valeur
explicitement demandée à chaque appel d'`enregistrer_licence`, que
l'écriture trousseau réussisse ou non -- et `lire_licence()` la préfère
toujours à une relecture trousseau pour le reste de la session. Une
relecture trousseau n'est tentée qu'en l'absence de toute registration
cette session (premier appel après lancement, ou après
`effacer_licence`) -- ce qui préserve la persistance normale entre deux
lancements quand l'écriture réussit réellement.

**Diagnostics ajoutés pour confirmer/creuser sans jamais journaliser la
clé en clair** (deux points de passage distincts, à comparer entre eux) :
- `settings_store.py::_journaliser_diagnostic_enregistrement`, à chaque
  `enregistrer_licence` : hash (8 premiers caractères du SHA-256) de la
  clé demandée, hash de ce que le trousseau rend en relecture *directe*
  (`keyring.get_password`, pas via le raccourci mémoire ci-dessus --
  volontairement, pour tester l'aller-retour réel du trousseau), et la
  source finalement utilisée (`trousseau`/`memoire`).
- `client.py::_journaliser_diagnostic_licence`, à chaque
  `licence_invalide`/`licence_requise` : longueur de la clé envoyée,
  présence d'un espace parasite, son hash, et le code serveur.

Un écart entre `sha256_demandee` et `sha256_trousseau_relue` au moment de
l'enregistrement confirme un problème d'aller-retour au niveau du
backend `keyring` lui-même (cause n°2 ci-dessus) ; un `sha256_envoyee`
qui ne correspond à aucun des deux au moment d'une recherche pointerait
plutôt vers un autre appelant non couvert par ce correctif.

⚠️ **Suite du même signalement, une fois les causes n°1/n°2 exclues par
comparaison des hashs** (clé identique à l'enregistrement, à la relecture
et à l'envoi -- et fonctionnelle via `Invoke-RestMethod` contre la même
URL de production) : la GUI seule reçoit encore `licence_invalide`, donc
le problème est dans la requête que `client.py` construit, pas dans la
clé. **Trois points vérifiés directement, aucun n'est en cause** (capturé
sur un vrai socket local -- voir le commentaire de `rechercher_console`
pour le détail) :
- **URL finale** (`server_url.rstrip("/") + "/recherche"`) : jamais de
  barre oblique double ni de segment manquant.
- **En-tête `X-Licence-Key`** : stocké en interne sous une casse mutilée
  par `Request.add_header` (`.capitalize()` -> `X-licence-key`), mais
  `AbstractHTTPHandler.do_open` retitre tous les en-têtes (`.title()`)
  juste avant l'envoi -- casse restaurée sur le fil. Sans incidence de
  toute façon : les noms d'en-tête HTTP sont insensibles à la casse par
  spécification, et Cloudflare Workers les normalise en minuscules à la
  réception quelle que soit la casse envoyée.
- **Encodage du corps** : `json.dumps(..., ensure_ascii=True)` (défaut)
  échappe tout caractère non-ASCII avant l'encodage UTF-8 -- le corps
  posté est toujours de l'ASCII pur, jamais un problème de charset
  malgré l'absence de paramètre `charset` explicite sur `Content-Type`.

**Piste restée ouverte, désormais instrumentée** : une redirection HTTP
suivie silencieusement par `urllib` convertirait la requête POST en GET
et supprimerait son corps (`Content-Type`/`Content-Length`), mais PAS les
en-têtes personnalisés comme `X-Licence-Key` (vérifié dans le code source
d'`HTTPRedirectHandler.redirect_request`, lu en lecture seule) -- une
piste plausible seulement si l'URL configurée diffère, même légèrement,
de celle validée manuellement. `client.py::_journaliser_diagnostic_
licence` journalise désormais `statut_http` (le code HTTP numérique,
distinct du code d'erreur `{"erreur": ...}` déjà consigné),
`url_demandee` (celle construite par ce module) et `url_atteinte`
(`HTTPError.url`, celle où l'erreur a réellement été levée -- diffère de
`url_demandee` si une redirection a été suivie) ; `redirection_suivie`
compare les deux.

**Découverte en cours de route, à exploiter au prochain essai réel** :
`r36s-studio-cloud/worker/src/routes/recherche.ts::logLicenceDiagnostic`
(lu en lecture seule, jamais modifié depuis ce dépôt) existe déjà côté
serveur pour cette même enquête -- visible via `wrangler tail`, il
journalise, côté Worker, la liste des en-têtes réellement *reçus*, la
présence/longueur/hash de `X-Licence-Key` tel que le serveur le voit, le
hash de la clé attendue (`LICENCE_TEST_KEY`), et l'URL/`User-Agent` de la
requête reçue. Comparer ce journal serveur (au prochain essai depuis la
GUI, `wrangler tail` ouvert en parallèle) au journal client ci-dessus
pour la même requête tranche définitivement entre un problème d'émission
(ce module) et un problème de réception/configuration côté Worker (ex. :
l'URL configurée dans la GUI pointe vers un environnement Cloudflare
différent de celui interrogé manuellement, avec un `LICENCE_TEST_KEY`
différent -- expliquerait une clé prouvée identique tout du long côté
client, mais refusée uniquement depuis la GUI).

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
