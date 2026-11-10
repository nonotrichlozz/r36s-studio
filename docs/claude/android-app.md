# Application Android (`android-app/`)

Version téléphone de R36S Studio : la carte SD se branche sur le téléphone
avec un adaptateur USB (OTG). **Réécriture en Kotlin / Jetpack Compose**, pas
un portage : rien du code Python n'est réutilisé à l'exécution (pas de worker
élevé, pas de PySide6). À ne pas confondre avec `r36s_studio/android/` (outil
ADB de la version ordinateur, `docs/android-adb.md`).

## Périmètre de la v1 (décidé le 2026-11-10)

- **Installer un système** : téléchargement direct (Arch R d'origine, Arch R
  clone, KNULLI R36S — mêmes dépôts et SHA-256 de repli que
  `identify/firmware_catalog.py`) ou fichier choisi sur le téléphone
  (`.img`, `.img.gz`, `.img.xz`, `.zip` contenant un `.img`), écriture puis
  relecture comparée octet par octet.
- **Sauvegarder ma carte** : image `.img.gz` enregistrée où l'utilisateur
  veut (sélecteur de fichiers Android), limitée à la fin de la dernière
  partition (MBR ou GPT), suivie d'une seconde lecture de contrôle.
- **Restaurer une sauvegarde** (= clonage : sauvegarder, changer de carte,
  restaurer).

**Volontairement absents** : tout ce qui demande de lire ou d'écrire des
*fichiers* sur la carte (copie de jeux, choix de l'écran, doublons, tri,
remise à zéro avec formatage). Sans root, Android ne monte ni ext4 ni NTFS,
et l'appli prend le lecteur en accès brut. Conséquence : **ROCKNIX n'est pas
proposé** (il lui faut `extlinux.conf.r36s` et un fichier d'écran posés sur
la carte après le flash, `identify/rocknix_r36s.py`).

## Architecture

| Fichier | Rôle |
|---|---|
| `core/ScsiBlockDevice.kt` | Carte vue par USB : SCSI sur Bulk-Only Transport, écrit à la main (aucune bibliothèque) |
| `core/Imaging.kt` | `flash` (écriture + vérification), `backup` (lecture + seconde lecture) |
| `core/ImageSource.kt` | Format par octets d'en-tête, décompression en flux |
| `core/PartitionTable.kt` | Fin de la zone utilisée (MBR, GPT) |
| `core/Safety.kt` | Garde-fou de taille |
| `usb/UsbCards.kt` | Détection et ouverture du lecteur (API USB Host d'Android) |
| `Firmwares.kt` | Catalogue, dernière release GitHub, téléchargement vérifié |
| `MainViewModel.kt` | État de l'écran, opérations, journal |
| `ui/Screens.kt`, `ui/Theme.kt` | Interface ; palette recopiée de `gui/theme.py` |
| `Strings.kt` | Tous les textes (équivalent de `gui/strings.py`) |

`core/` n'importe rien d'Android : il se teste sur la machine de
construction avec un faux lecteur USB en mémoire
(`app/src/test/.../TestSupport.kt::FakeUsbReader`). Aucun test ne touche de
matériel réel.

## Règles reprises de la version ordinateur

- Fenêtre rouge avec case obligatoire (jamais pré-cochée) avant toute
  écriture, y compris après un téléchargement automatique. Pas de fenêtre
  rouge pour la sauvegarde.
- Format `.7z` et image plus grosse que la carte refusés *avant* la fenêtre
  rouge quand c'est décidable (image brute) ; revérifié pendant l'écriture.
- Progression réelle : mesurée sur les octets lus dans le fichier source
  (exacte même quand la taille décompressée n'est pas connue).
- Téléchargement : jamais sans SHA-256 ; fichier `.part` renommé seulement
  après vérification.
- Source instable (deux lectures différentes) : la sauvegarde est renommée
  en `.instable`, jamais supprimée.
- Vocabulaire sans jargon ; détails bruts en lignes `[détail]` du journal.
- Version : `versionName` relu dans `r36s_studio/__init__.py::APP_VERSION`.

## Écarts assumés

- **Carte unique choisie d'office** : avec un seul lecteur branché, il n'y a
  pas de fenêtre « Choix de la carte » ; la fenêtre rouge nomme la carte et
  sa taille. Avec plusieurs lecteurs, tout est bloqué (« n'en laisse qu'une »).
- **Garde-fou** : la mémoire du téléphone est hors de portée par
  construction (l'appli ne parle qu'à la prise USB) ; restent les refus de
  taille nulle et de plus de 1 To. Un disque dur USB de moins de 1 To
  **passerait** — la fenêtre rouge est alors le seul rempart.
- **Changement de carte sans débrancher le lecteur** : Android ne prévient
  pas. Avant d'écrire, l'appli relit le début de la carte et refuse si ce
  n'est plus celui relevé à la détection ; le bouton Rafraîchir relit.
- Pas de `.sha256blocks`, pas de chien de garde de lecture, pas de sauvegarde
  « système sans les jeux ».
- Sauvegarde d'une carte GPT : la copie de secours de la table (fin de carte)
  n'est pas dans l'image.
- L'écran reste allumé pendant une opération, mais il n'y a **pas de service
  d'avant-plan** : quitter l'appli pendant une écriture peut l'interrompre.

## Construction

`.github/workflows/android.yml` : tests du cœur puis `assembleDebug`, APK en
artefact « R36S-Studio-Android ». APK de débogage : signature propre à chaque
construction, donc désinstaller l'ancienne version avant d'installer la
nouvelle. Pas encore d'APK signé pour diffusion.

## Jamais vérifié sur du vrai matériel

Tout ce qui touche au téléphone : détection du lecteur, demande
d'autorisation, débit réel, comportement d'Android quand l'appli prend le
lecteur (notification « carte non prise en charge » possible), lecteurs à
plusieurs fentes, cartes à blocs de 4096 octets.
