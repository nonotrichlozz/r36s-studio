> **Cette version ne contient que l'application Windows.**
> Les versions macOS et Linux arriveront plus tard.

## Windows

1. Télécharge **R36S-Studio-Setup.exe** (plus bas, dans « Assets ») et
   double-clique dessus.
2. Une fenêtre bleue « Windows a protégé votre ordinateur » (SmartScreen)
   peut s'afficher. C'est normal : R36S Studio n'a pas encore de certificat
   de signature, qui permettrait à Windows de reconnaître l'éditeur. Clique
   sur **Informations complémentaires**, puis sur **Exécuter quand même**.
3. Suis l'installation, puis lance R36S Studio depuis le raccourci du Bureau.

L'installeur met en place le dossier complet de l'application
(`R36S Studio.exe` et son dossier `_internal`) : ne copie jamais
`R36S Studio.exe` seul ailleurs, il ne démarrerait pas (« Failed to load
Python DLL »).

Pour mettre à jour : télécharge et lance le nouvel installeur, il remplace
l'ancienne version.

<!--
Instructions macOS et Linux, à remettre quand ces plateformes rejoindront la
Release (.github/workflows/release.yml, job publish).

## Mac

1. Double-clique sur **R36S-Studio-macOS.dmg**, puis fais glisser
   **R36S Studio** sur le dossier **Applications**.
2. Premier lancement : fais un **clic droit** sur R36S Studio dans
   Applications, choisis **Ouvrir**, puis **Ouvrir** à nouveau.
3. Pour lire et écrire ta carte SD, R36S Studio a besoin de l'**Accès complet
   au disque** : Réglages Système → Confidentialité et sécurité → Accès
   complet au disque → bouton **+** → R36S Studio.

**Après chaque mise à jour**, refais l'étape 3 : retire l'ancienne ligne
R36S Studio de la liste (bouton **−**), puis rajoute la nouvelle (bouton
**+**). Décocher puis recocher ne suffit pas.

## Linux

Décompresse le fichier, puis double-clique sur **R36S Studio** dans le dossier.
-->
