# Consoles diverses : refonte visuelle de la fiche

Objectif : une fiche lisible en 5 secondes par un débutant.
Même thème que le reste de l'app (gui/theme.py). Pas de changement
de logique réseau ni de parsing.

## Ordre d'affichage
1. En-tête (carte) : nom en grand, fabricant en dessous.
   À droite du nom, une petite pastille : « Vérifié » (vert) ou
   « Non vérifié » (orange). Supprimer le bandeau pleine largeur et
   le bandeau bleu en double ; garder une seule phrase discrète sous
   le nom pour les fiches non vérifiées.
2. Bloc « À savoir » (seulement s'il y a quelque chose) :
   - licence non commerciale (rouge),
   - licence à vérifier (orange),
   - incompatibles : « Ne pas installer : ArkOS, dArkOS… », chaque nom
     avec sa raison en dessous en plus petit,
   - console Android : « Console Android : la préparation se fait par
     ADB, pas par la carte SD (bientôt dans R36S Studio). »
     (type d'OS contenant « android », insensible à la casse)
3. Carte « Matériel » : grille 2 colonnes (SoC, Architecture,
   Système). Valeur « inconnu » affichée en gris « Non trouvé ».
4. Options : n'afficher que les catégories qui ont des options.
   Les catégories vides sont regroupées en une seule ligne grise :
   « Rien trouvé pour : Front-end, Système / CFW… ».
   Chaque option = une carte : nom en gras, description, puis une
   ligne de petites pastilles (licence, « non commerciale » en rouge)
   et un bouton « Ouvrir la page » (au lieu de l'URL brute).
   L'URL source n'est plus affichée dans chaque carte.
5. Sources : section repliée par défaut (« Sources (2) »), liens
   cliquables alignés à gauche.
6. Si la fiche n'a aucune option : message clair « Peu
   d'informations trouvées pour cette console. » au lieu de quatre
   « Aucune option ».

## Détails
- Marges et espacements réguliers, largeur de lecture max ~900 px
  centrée sur grand écran.
- Aucun texte centré sauf les titres de page.
- Tous les textes serveur restent en texte brut (Qt.PlainText).
- Liens : http/https uniquement (règle existante).

## Tests
Captures de régression (tests d'état des widgets) pour : SF3000HD
(vérifiée, restriction commerciale, incompatibles), R36S (fixture IA),
fiche Android vide (type Android, aucune option).

Ne modifie jamais r36s-studio-cloud. Propose le plan avant de coder.
Commite, ne pousse rien.