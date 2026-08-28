"""Page des releases du dépôt officiel dArkOS pour R36S (§5 mode assisté,
étape 5, et étape C du mode expert). Les images n'y sont pas hébergées --
la page renvoie vers Mega, Google Drive, OneDrive et un torrent, jamais un
lien téléchargeable directement -- donc rien à automatiser au-delà de
l'ouverture de cette page dans le navigateur ; l'utilisateur télécharge
lui-même, puis choisit le fichier obtenu."""

from __future__ import annotations

DARKOS_R36S_RELEASES_URL = "https://github.com/southoz/dArkOSRE-R36/releases"
