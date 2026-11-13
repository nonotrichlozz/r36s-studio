# Photos des systèmes (appli Android)

Une photo par système, affichée dans la liste et en haut de la fiche de
« Installer un système ». Elles ne sont **pas** dans l'APK : l'appli les
charge depuis la branche `android-apk`, où la construction
(`.github/workflows/android.yml`) recopie ce dossier. Ajouter ou changer une
photo ne demande donc aucune mise à jour de l'appli.

- Nom du fichier : `<identifiant>.jpg`, en minuscules.
- Format conseillé : JPEG paysage 16:9, 1280 × 720, moins de 500 Ko
  (3 Mo au maximum, au-delà l'appli l'ignore).
- Sans fichier, l'appli affiche une vignette avec les initiales du système.
- **Uniquement des photos dont on a les droits** : prises par Arnaud
  (console allumée sur le menu du système), pas d'images récupérées sur les
  sites des projets.

Identifiants : `archr`, `archr_clone`, `knulli`, `arkos_k36`, `emuelec`,
`arkos`, `darkosen`, `rocknix`, `amberelec`, `minui`, `r36droid`,
`andr36oid` (liste de `Firmwares.ALL`).
