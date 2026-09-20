# Outil « Console Android » — étape 1 : détection et propositions

Objectif de cette étape : brancher une console Android en USB, la
reconnaître, et proposer les émulateurs adaptés. AUCUNE installation
automatique pour l'instant.

Consoles de test disponibles : Retroid Pocket Flip 2, RG406V,
Anbernic RG Rotate.

## Isolation
Nouveau package android/, écrans dans gui/screens.py comme le reste.
Ne touche pas au code R36S ni à consoles_diverses/.
Ne modifie jamais r36s-studio-cloud.

## adb
- Ne pas l'embarquer dans le dépôt. Au premier lancement de l'outil,
  proposer de télécharger les « platform-tools » officiels de Google
  dans le dossier de données de l'app, après accord explicite de
  l'utilisateur (afficher l'URL et la taille).
- Si adb est déjà installé sur la machine (dans le PATH), l'utiliser.
- Ne jamais lancer adb root, ni aucune commande qui modifie le
  système. En étape 1 : uniquement des lectures.

## Détection
- Lister les appareils connectés (adb devices).
- Aucun appareil : écran d'aide expliquant, en français et pas à pas,
  comment activer le mode développeur et le débogage USB
  (7 appuis sur le numéro de build, etc.), avec la mention que ça
  varie selon la console.
- Appareil non autorisé : expliquer qu'il faut accepter la demande
  affichée sur l'écran de la console.
- Appareil connecté : lire via adb shell getprop le fabricant, le
  modèle, le nom de produit, la version d'Android et l'architecture
  (ro.product.manufacturer, ro.product.model, ro.product.name,
  ro.build.version.release, ro.product.cpu.abi).

## Identification et propositions
- Chercher la console dans le catalogue local/serveur (réutiliser le
  client de consoles_diverses) avec le modèle lu.
- Trouvée : afficher sa fiche.
- Non trouvée : afficher les informations lues, et proposer un bouton
  pour lancer la recherche IA avec le modèle comme référence.
- Liste des émulateurs recommandés : fichier de données JSON local
  (android/data/emulateurs.json) contenant pour chacun : nom,
  systèmes émulés, licence, gratuit ou payant, URL officielle,
  et si le téléchargement automatique sera autorisé plus tard.
  Rien n'est téléchargé à cette étape : un bouton « Ouvrir la page »
  (http/https uniquement).
- Afficher clairement pour chaque émulateur : gratuit / payant /
  licence, pour que l'utilisateur sache ce qu'il fait.

## Interface
- Nouvelle tuile « Console Android » sur l'accueil.
- Écran : état de la connexion, informations lues, fiche console si
  trouvée, liste des émulateurs proposés.
- Bouton « Actualiser ».
- Toutes les commandes adb dans un thread, l'interface ne gèle
  jamais, délai maximal par commande.
- Textes serveur et sortie adb affichés en texte brut.

## Hors périmètre (étape 2)
Installation d'APK, copie de ROMs, sauvegardes, réglages système.

## Tests
adb absent, aucun appareil, appareil non autorisé, plusieurs
appareils, getprop simulé pour les trois consoles de test, console
absente du catalogue. Aucune commande adb réelle dans les tests.

Propose le plan avant de coder. Commite, ne pousse rien.