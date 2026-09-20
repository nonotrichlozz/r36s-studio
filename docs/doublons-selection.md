# Sélection automatique dans l'écran Doublons

Constat après essai réel : 1272 groupes de versions différentes, et le
compteur affiche seulement « 3 fichiers sélectionnés ». Les groupes de
versions ne sont pas précochés, l'outil est donc inutilisable à cette
échelle. L'étoile qui marque la version à conserver fonctionne déjà.

## Ce qu'il faut
1. Dans CHAQUE groupe (copies identiques ET versions différentes),
   cocher par défaut tous les fichiers SAUF celui marqué de l'étoile
   (la version à conserver selon la priorité déjà en place :
   France/Fr > Europe > World > USA > Japan > autre, puis révision la
   plus haute, puis taille).
2. Le compteur en haut doit refléter cette sélection dès l'affichage
   des résultats.
3. Bandeau en haut : « Sélection automatique : vérifiez avant de
   déplacer. »
4. Trois boutons en haut : « Tout cocher », « Tout décocher »,
   « Ne garder que les versions françaises et européennes ».
5. L'utilisateur peut toujours modifier chaque case à la main.

## Important
Rien ne change à la détection, qui fonctionne. Il ne s'agit que de
l'état initial des cases et du compteur.

## Tests
- Un groupe de 3 versions : 2 cochées, celle de l'étoile décochée.
- 1272 groupes : le compteur correspond au total réel.
- Les trois boutons modifient bien la sélection et le compteur.