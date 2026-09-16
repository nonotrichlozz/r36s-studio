# Section « Consoles diverses » - étape 1 : mode recherche

## Règle absolue : isolation
- Ne pas modifier le code R36S existant, sauf le strict minimum pour
  ajouter l'entrée « Consoles diverses » dans la navigation principale.
- Tout le nouveau code dans un package séparé consoles_diverses/
  (écrans, client réseau, données, tests, CLAUDE.md dédié).
- Tous les tests R36S existants doivent passer sans modification.

## Contexte
Un serveur séparé (projet r36s-studio-cloud) renvoie des fiches console.
En développement, il tourne en local : http://localhost:8787
Documentation de référence (lecture seule, ne rien modifier) :
- C:/Users/astru/r36s-studio-cloud/README.md
- C:/Users/astru/r36s-studio-catalogue/schema/console.schema.json
- C:/Users/astru/r36s-studio-catalogue/consoles/sf3000hd.json (exemple)
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
- Adresse du serveur (par défaut http://localhost:8787).
- Clé de licence : champ masqué, stockée avec le trousseau du système
  (bibliothèque keyring), jamais en clair dans un fichier de config.

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

## Hors périmètre pour cette étape
Analyse de carte SD, installation, contributions : plus tard.

## Tests
Réponses serveur simulées (aucun appel réseau réel) : fiche vérifiée,
fiche IA avec restriction commerciale, aucune info, chaque erreur,
serveur injoignable, délai dépassé.

## Méthode
Lis CLAUDE.md et l'architecture, propose un plan AVANT de coder,
attends ma validation. Commits locaux uniquement, ne pousse rien.
Interface en français, même style visuel que l'existant.