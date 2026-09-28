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
3. **Adresse du serveur en dur** (`settings_store.py::adresse_serveur`,
   `PRODUCTION_SERVER_URL`) -- jamais saisie ni modifiable depuis la GUI
   (champ retiré des réglages : un client ne saurait pas quoi y mettre, et
   une adresse mal tapée rendait la section inutilisable sans message
   clair). Seule surcharge : la variable d'environnement
   `R36S_STUDIO_CLOUD_URL` (Worker local en développement), validée par
   `valider_adresse_serveur` -- `https://` toujours accepté, `http://`
   seulement pour `localhost`/`127.0.0.1` (sinon la clé de licence
   circulerait en clair) ; une valeur refusée est signalée sur la sortie
   d'erreur, repli sur la production. L'ancien champ `AppConfig.
   consoles_diverses_server_url` n'existe plus : un `config.json` qui le
   porte encore (souvent `http://localhost:8787`) est ignoré.
4. **Réponse plafonnée à 1 Mio** (`client.py::MAX_RESPONSE_BYTES`) avant
   tout `json.loads`.

## Clé de licence : `config.json`

Clé saisie dans les réglages de la section (seul champ restant), mémorisée
dans `config.json` (`AppConfig.consoles_diverses_licence_key`), lue et
écrite par `MainWindow` avec le reste de la configuration -- jamais par
un module à part, qui réécrirait `config.json` dans le dos de
`MainWindow._app_config` (sa copie en mémoire écraserait la clé au
prochain `save_config`). `.strip()` à l'enregistrement et à la lecture :
un copier-coller dans un champ masqué laisse souvent un espace ou un
retour à la ligne invisible (bug réel, clé valide refusée).

Exception assumée au « config.json sans secret » (CLAUDE.md racine) :
une clé par client, révocable côté serveur (KV `LICENCES` de
r36s-studio-cloud, `npm run licence -- revoquer`), pas un mot de passe.
**Historique** : la clé était auparavant au trousseau système
(`keyring`), retiré -- sous Windows, `WinVaultKeyring.set_password` peut
lever après avoir réécrit l'ancienne valeur, laissant une clé figée
quelle que soit la ressaisie (deux signalements réels). Plus de
dépendance `keyring`, ni dans `requirements.txt` ni dans les `.spec`.

Refus serveur et message affiché (`strings.py::_ERROR_MESSAGE_KEYS`) :
`licence_requise`, `licence_invalide`, `licence_expiree`,
`licence_revoquee` (403, bouton « Saisir ma clé » sous le message),
`quota_licence_depasse` (429, quota quotidien du client), `licence_non_
supportee` (500, serveur mal réglé). Sans clé, l'écran l'explique d'emblée
(`_no_licence_frame`) au lieu de rester vide.
`client.py::_journaliser_diagnostic_licence` consigne toujours, à chaque
refus de licence, longueur/hash/URL (jamais la clé en clair).

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
test de ce package ne fait un appel réseau réel.
