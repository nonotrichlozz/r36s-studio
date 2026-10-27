# Plan de test sur vraie console : RG Rotate, GammaOS Next 1.4.1

Installation guidée par USB (`r36s_studio/consoles_diverses/CLAUDE.md`,
section « Installations guidées par USB »). À faire sur le PC Windows, avec
la RG Rotate, le câble USB-C habituel et le mot de passe de l'archive.

**Prérequis** : la fiche `anbernic-rg-rotate` du catalogue doit porter les
SHA-256, `pac_produit` et `pac_nom` (PR du catalogue). Avant sa fusion :
lancer l'app avec le serveur local, ou tester avec la fixture
`tests/fixtures_fiche_anbernic_rg_rotate.json`.

Tout est consigné dans `consoles_diverses.log` (dossier des journaux de
l'app) et dans le cadre en bas de l'écran. Copier ce journal à la fin de
chaque essai.

## Essais

1. **Fiche** : Consoles diverses → « RG Rotate ». Section « Installations
   guidées » : deux boutons (installation, firmware d'origine), la
   restauration Super affichée sans bouton avec sa raison.
2. **Choix** : Lite cochée par défaut ; « Continuer » grisé tant que la
   case « tout sera effacé » n'est pas cochée.
3. **Vérifications** : ✓ Windows, ✓ espace, pilotes « déjà installés »
   (déjà le cas sur ce PC).
4. **Téléchargement** (2,7 Go + 55 Mo) : couper le Wi-Fi au milieu, puis
   « Réessayer » → doit **reprendre** et non repartir de zéro. Relancer
   toute la procédure ensuite → aucun nouveau téléchargement.
5. **Mot de passe** : d'abord un **faux** → message en quelques secondes,
   sans extraire. Puis le bon → extraction avec pourcentage (noter la durée).
6. **Contrôle du .pac** : ligne « En-tête : … RG_ROTATE_GAMMAOS_NEXT_LITE ».
7. **Consignes** : SD retirée, console éteinte, câble débranché ; cocher
   la seconde case ; « C'est fait ».
8. **Chargement puis attente** : « Préparation du fichier : N % » (~2 min),
   puis « Branche la console en mode installation » avec le compte à
   rebours. Si rien ne s'affiche avant la toute fin : sortie de CmdDloader
   mise en mémoire tampon (à noter).
9. **Essai volontaire raté** : brancher la console **sans** maintenir
   Retour (elle démarre sous Android) → message « La console a démarré
   normalement… ». Débrancher, éteindre.
10. **Annuler** pendant l'attente → retour aux consignes, rien d'écrit.
11. **Vrai flash** : console ouverte en coulissant, Retour maintenu,
    brancher. Le titre devient « Ne débranche pas la console », plus de
    bouton Annuler ; l'ordinateur ne se met pas en veille.
12. **Fin** : « Installation terminée » ; premier démarrage 2-3 min (écran
    noir ~1 min normal) ; GammaOS démarre. Bouton « Installer des
    émulateurs » → écran Console Android.
13. **Pilotes** (si possible sur un autre PC ou après les avoir retirés) :
    une invite Windows, aucune autre fenêtre ; ligne « Pilotes :
    installés=True ».
14. **Windows vierge** (Windows Sandbox) : CmdDloader et 7-Zip se lancent
    sans installer Visual C++.

## À noter et me renvoyer

- VID:PID en **mode Download** : lignes `[diagnostic] USB branché : …` et
  `[diagnostic] console download : …` (sur ce PC le 27/10 : `1782:4d00`,
  « SPRD U2S Diag (COM5) » -- RG Rotate ou RG Vita ?).
- VID:PID de la console **démarrée sous Android** (essai 9).
- Toute la sortie `CmdDloader : …` du journal, surtout la ligne
  `Download Result = …` et ce qui précède une erreur.
- Durées : extraction, chargement du .pac, flash (ligne « CmdDloader
  terminé (code N) en N s »).
- Si une invite administrateur est apparue pour CmdDloader.
- Le moindre écran ou texte incompréhensible pour un débutant.
