# Section « Consoles diverses » - étape 1 : mode recherche

## Statut : terminée (recherche + affichage)
Recherche, affichage de la fiche (badge vérifié/non vérifié, bloc « À
savoir », carte Matériel, options par catégorie, section Sources) et
réglages (adresse serveur, clé de licence) sont en place et testés.
Serveur de production en ligne : `https://r36s-studio-cloud.r36studio.workers.dev`
(HTTPS) -- confirmé en conditions réelles avec une vraie recherche
(SF3000HD, `trouve_dans_catalogue`). Un en-tête `User-Agent` explicite
est nécessaire contre ce serveur précis : sans lui, Cloudflare bloque la
requête (403) avant même qu'elle n'atteigne le Worker -- voir
`consoles_diverses/client.py`.

Reste (voir « Prochaines étapes » en bas) : analyse de carte SD,
installation, contributions au catalogue, dédoublonnage des jeux.

## Règle absolue : isolation
- Ne pas modifier le code R36S existant, sauf le strict minimum pour
  ajouter l'entrée « Consoles diverses » dans la navigation principale.
- Tout le nouveau code dans un package séparé consoles_diverses/
  (écrans, client réseau, données, tests, CLAUDE.md dédié).
- Tous les tests R36S existants doivent passer sans modification.

## Contexte
Un serveur séparé (projet r36s-studio-cloud) renvoie des fiches console.
En développement, il tourne en local : http://localhost:8787
(visé seulement via R36S_STUDIO_CLOUD_URL, voir « Réglages » ci-dessous)
En production : https://r36s-studio-cloud.r36studio.workers.dev (HTTPS,
derrière Cloudflare -- voir la note User-Agent ci-dessus).
Documentation de référence (dépôts locaux séparés, lecture seule, ne rien
modifier) :
- r36s-studio-cloud/README.md
- r36s-studio-catalogue/schema/console.schema.json
- r36s-studio-catalogue/consoles/sf3000hd.json (exemple)
Ne jamais lire de fichier .dev.vars.

## Appel serveur
POST /recherche, corps JSON { "reference": "..." },
en-tête X-Licence-Key.
Statuts de réponse à gérer : trouve_dans_catalogue, trouve_par_ia,
aucune_information_trouvee.
Erreurs à traduire en messages clairs pour un débutant :
reference_invalide, licence_requise, licence_invalide,
recherche_ia_indisponible, configuration_manquante, erreur_api_ia,
serveur injoignable.
- Appel en arrière-plan (l'interface ne gèle jamais), délai max 30 s,
  indicateur « Recherche en cours… » (la recherche IA prend 10 à 15 s).

## Réglages de la section
- Adresse du serveur : **plus un réglage** (révisé après coup). En dur,
  https://r36s-studio-cloud.r36studio.workers.dev ; un client ne saurait
  pas quoi saisir. Worker local en développement : variable
  d'environnement R36S_STUDIO_CLOUD_URL (ex. http://localhost:8787),
  jamais accessible depuis l'interface.
- Clé de licence (seul champ de la fenêtre de réglages) : champ masqué, mémorisée dans
  `config.json` (voir `consoles_diverses/CLAUDE.md`, « Clé de licence »).

## Écran de recherche
- Champ « Référence de la console » + bouton Rechercher.
- Badge : « Vérifié » (vert) ou « Non vérifié » (orange).
- Identité : nom, fabricant, SoC, architecture, type d'OS.
- Options par catégorie : Front-end, Système / CFW, Firmware d'origine,
  Mises à jour. Pour chaque option : nom, description, lien, licence.
- Si restriction_commerciale est vrai (option ou fiche) : bandeau rouge
  bien visible « Licence non commerciale : usage commercial interdit ».
- Si licence_a_verifier est vrai : mention « Licence à vérifier ».
- Incompatibles : liste en rouge avec la raison de chacun.
- Sources : liens cliquables.
- Liens ouverts dans le navigateur, jamais de téléchargement automatique.
- Fiche non vérifiée : bandeau « Informations trouvées automatiquement,
  non vérifiées », et aucune action d'installation proposée.
- Aucune information trouvée : message simple, bouton pour réessayer.

## Prochaines étapes (hors périmètre de l'étape 1, recherche + affichage)
- Analyse de carte SD (le champ `detection_sd` du schéma existe déjà côté
  catalogue mais n'est pas exploité côté app).
- Installation/téléchargement d'un firmware ou frontend depuis cette
  section -- aujourd'hui, seuls des liens ouverts dans le navigateur.
- Contributions/soumissions au catalogue depuis l'app (aujourd'hui,
  uniquement via une PR GitHub ouverte côté serveur pour une fiche IA).
- Dédoublonnage des jeux (détecter qu'un jeu déjà présent sur la carte
  correspond à un jeu qu'on s'apprête à recopier, pour ne pas dupliquer).

## Tests
Réponses serveur simulées (aucun appel réseau réel) : fiche vérifiée,
fiche IA avec restriction commerciale, aucune info, chaque erreur,
serveur injoignable, délai dépassé.

## Méthode
Lis CLAUDE.md et l'architecture, propose un plan AVANT de coder,
attends ma validation. Commits locaux uniquement, ne pousse rien.
Interface en français, même style visuel que l'existant.