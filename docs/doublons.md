# Outil « Doublons de jeux »

Objectif : analyser un dossier de ROMs et proposer de déplacer les
doublons, sans jamais rien supprimer.

## Emplacement
Nouvel outil autonome, accessible depuis l'accueil (pas dans
« Consoles diverses »). Il sert pour toutes les consoles.
Code isolé dans un package doublons/, tests dédiés.
Ne modifie pas r36s-studio-cloud.

## Source à analyser
Un dossier choisi par l'utilisateur : sur le PC, sur une carte SD ou
sur un disque externe. Analyse RÉCURSIVE des sous-dossiers.

## Dossiers à ignorer par défaut (cochables)
cubegm, rootfs, BGM, Music, Movie, Photo, Ebook, SteamLibrary,
.res, Imgs, media, bios, tout dossier commençant par un point.
L'utilisateur voit la liste et peut la modifier.

## Extensions considérées comme des jeux
Liste dans un fichier de données (JSON), pas en dur : nes, sfc, smc,
gb, gbc, gba, md, gen, smd, pce, gg, sms, n64, z64, iso, chd, cue,
bin, img, m3u, zip, 7z, ngp, ngc, ws, wsc, a26, col, int, etc.
Tout autre fichier est ignoré.

## Deux niveaux de détection
1. Copies identiques : même taille, puis même empreinte SHA-256
   (ne calculer l'empreinte que pour les fichiers de même taille).
   Certain : peut être proposé coché par défaut.
2. Versions du même jeu : titre normalisé identique.
   Normalisation : minuscules, accents retirés, ponctuation et
   espaces retirés, suppression des tags entre parenthèses et
   crochets — (USA), (Europe), (Fr), (Rev A), (v1.1), [!], [b],
   (Beta), (Proto)… Jamais coché par défaut : l'utilisateur choisit.

## Version conservée par défaut dans un groupe de versions
Ordre de priorité : (France)/(Fr) > (Europe) > (World) > (USA) >
(Japan) > autre. À priorité égale : la révision la plus haute, puis
le fichier le plus gros. L'utilisateur peut changer la sélection
dans chaque groupe.

## Fichiers liés — RÈGLE CRITIQUE
Un jeu peut tenir en plusieurs fichiers : .cue + .bin, .m3u + .chd,
.gdi, dossiers de disques multiples.
- Ne jamais déplacer un .bin sans son .cue, ni un fichier listé dans
  un .m3u ou un .cue sans l'ensemble du groupe.
- Lire le contenu des .cue et .m3u pour connaître les fichiers liés.
- Un groupe se déplace entier ou pas du tout.
- Si un fichier lié est introuvable, exclure le groupe et le signaler.

## Action
- Déplacement vers un dossier _doublons créé à la racine du dossier
  analysé, en recréant l'arborescence d'origine
  (_doublons/GBA/jeu.gba).
- JAMAIS de suppression, aucune option de suppression.
- Journal de l'opération écrit dans _doublons/journal.json
  (chemin d'origine, destination, date).
- Bouton « Tout annuler » qui remet les fichiers à leur place à
  partir de ce journal.
- Si le fichier de destination existe déjà, renommer sans écraser.
- Vérifier l'espace disque et que la destination est accessible en
  écriture avant de commencer.

## Interface
1. Choix du dossier, options (récursif, dossiers ignorés).
2. Analyse en arrière-plan, barre de progression annulable,
   l'interface ne gèle jamais (des dizaines de milliers de fichiers).
3. Résultat : résumé (nombre de fichiers, de groupes, espace
   récupérable), puis liste de groupes repliables. Chaque groupe
   montre les fichiers, leur taille, leur chemin, avec la version
   conservée en évidence. Cases à cocher par groupe et par fichier.
4. Bouton « Déplacer la sélection », avec confirmation indiquant le
   nombre de fichiers et l'espace concerné.
5. Export du rapport en texte avant action.

## Tests
Arborescences factices : copies identiques, versions multilingues,
.cue/.bin, .m3u multi-disques, fichier lié manquant, dossiers
ignorés, destination déjà existante, annulation, interruption en
cours d'analyse.

Propose le plan AVANT de coder. Commite, ne pousse rien.