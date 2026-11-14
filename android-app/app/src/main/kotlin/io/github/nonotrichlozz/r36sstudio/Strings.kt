// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio

import java.util.Locale

/**
 * Tous les textes de l'interface, isolés ici (même principe que
 * `r36s_studio/gui/strings.py`). Vocabulaire : aucun terme technique --
 * « ta carte SD », « le système de la console » ; les détails bruts ne vont
 * que dans le journal, en ligne supplémentaire.
 */
object Strings {
    const val APP_TITLE = "R36S Studio"
    const val APP_SUBTITLE = "Prépare la carte SD de ta console depuis ton téléphone"

    // --- Bandeau « carte détectée » ---
    const val CARD_NONE = "Aucune carte détectée"
    const val CARD_NONE_HINT = "Branche ta carte SD sur le téléphone avec un adaptateur USB."
    const val CARD_SEVERAL = "Plusieurs cartes branchées"
    const val CARD_SEVERAL_HINT = "N'en laisse qu'une seule branchée pour éviter toute erreur."
    const val CARD_NEEDS_PERMISSION = "Carte branchée"
    const val CARD_NEEDS_PERMISSION_HINT = "Autorise R36S Studio à utiliser ta carte."
    const val CARD_ALLOW = "Autoriser"
    const val CARD_PROBING = "Lecture de la carte…"
    const val CARD_READY_HINT = "Carte prête"
    const val CARD_LOCKED_HINT = "Carte lisible, mais le lecteur la dit verrouillée : l'écriture risque d'être refusée."
    const val CARD_PROBLEM = "Carte illisible"
    const val CARD_NO_MEDIUM_HINT =
        "Le lecteur est branché, mais il ne voit pas de carte. Enfonce bien la carte, rebranche le lecteur, puis appuie sur Rafraîchir."
    val VERSION_LINE = "Version " + BuildConfig.VERSION_NAME + " (" + BuildConfig.BUILD_ID + ")"
    const val CARD_REJECTED_SIZE = "Impossible de connaître la taille de cette carte : elle est refusée par sécurité."
    const val CARD_REJECTED_LARGE = "Ce support est trop gros pour être une carte de console : il est refusé par sécurité."
    const val REFRESH = "Rafraîchir"

    // --- Tuiles ---
    const val TILE_INSTALL = "Installer un système"
    const val TILE_INSTALL_DESC = "Télécharge un système ou choisis un fichier, puis écris-le sur ta carte."
    const val TILE_BACKUP = "Sauvegarder ma carte"
    const val TILE_BACKUP_DESC = "Copie toute ta carte dans un fichier sur le téléphone. Rien n'est modifié."
    const val TILE_RESTORE = "Restaurer une sauvegarde"
    const val TILE_RESTORE_DESC = "Remets une sauvegarde sur une carte, la même ou une neuve (clonage)."
    const val TILE_ERASE = "Effacer la carte"
    const val TILE_ERASE_DESC = "Rend la carte vierge, prête pour installer un autre système. Tout ce qu'elle contient est perdu."
    const val SECTION_SAFETY = "Par sécurité"
    const val BADGE_READY = "Prêt"
    const val BADGE_NO_CARD = "Branche une carte"

    // --- Choix du système ---
    // --- Choix du système : liste et fiche ---
    const val PICKER_TITLE = "Choisir un système"
    const val PICKER_SUBTITLE = "Appuie sur un système pour voir sa fiche."
    const val PICKER_SECTION_DIRECT = "INSTALLATION EN UN BOUTON"
    const val PICKER_SECTION_LINK = "À TÉLÉCHARGER SUR LA PAGE DU PROJET"
    const val PICKER_SECTION_FILE = "TU AS DÉJÀ LE FICHIER"
    const val PICKER_FILE = "Choisir un fichier sur le téléphone"
    const val PICKER_FILE_DESC = "Un fichier .img, .img.gz, .img.xz ou .zip que tu as déjà. Une archive .7z doit d'abord être décompressée."
    const val PICKER_BACK = "Retour"
    const val PICKER_DOWNLOAD_INSTALL = "Télécharger et installer"
    const val PICKER_OPEN_PAGE = "Ouvrir la page de téléchargement"
    const val PICKER_PICK_DOWNLOADED = "Choisir le fichier téléchargé"
    const val PICKER_LINK_HELP = "Télécharge le fichier sur la page du projet, reviens ici, puis choisis-le."
    const val PICKER_NOT_PHONE = "Ce système ne s'installe pas correctement depuis un téléphone : utilise R36S Studio sur ordinateur."
    const val PICKER_NOTE_TITLE = "À savoir"
    const val PICKER_PHOTO_MISSING = "Photo à venir"
    const val PICKER_NO_BROWSER = "Impossible d'ouvrir le navigateur du téléphone."
    const val AUDIENCE_ORIGINAL = "R36S d'origine"
    const val AUDIENCE_CLONE = "Clones"
    const val AUDIENCE_BOTH = "R36S et clones"
    const val STATUS_MAINTAINED = "Mis à jour"
    const val STATUS_EXPERIMENTAL = "Expérimental"
    const val STATUS_ARCHIVED = "Arrêté"
    const val BADGE_DIRECT = "1 bouton"

    const val FW_ARCHR_TAGLINE = "Récent, avec son propre menu"
    const val FW_ARCHR_DESC = "Système récent basé sur Arch Linux, avec son propre menu. Les jeux vont dans un espace lisible par Windows, Mac et Linux. Image pour la vraie R36S."
    const val FW_ARCHR_NOTE = "Laisse le premier démarrage se terminer sans éteindre la console : Arch R agrandit la carte et crée l'espace pour les jeux. Si l'écran reste noir, le fichier d'écran de ta console se génère sur arch-r.io/overlay-generator."
    const val FW_ARCHR_CLONE_TAGLINE = "Arch R pour les copies de R36S"
    const val FW_ARCHR_CLONE_DESC = "Le même système Arch R, dans sa version pour les consoles clones de la R36S."
    const val FW_ARCHR_CLONE_NOTE = "Les clones sont tous différents. Essai du 13/11/2026 : cette version n'a pas démarré sur un clone violet (carte G80CA). Si l'écran reste noir, essaie ArkOS K36, ou remets la sauvegarde de la carte d'origine."
    const val FW_KNULLI_TAGLINE = "Complet et simple"
    const val FW_KNULLI_DESC = "Système complet et récent, image faite pour la vraie R36S (pas pour les clones). Licence non commerciale : usage commercial interdit."
    const val FW_KNULLI_NOTE = "Branche la console sur secteur pour le premier démarrage et laisse l'installation se terminer : elle peut prendre plusieurs minutes et redémarrer seule. Retire la deuxième carte (TF2) pour ce premier démarrage. Écran noir avec de la musique : l'écran de KNULLI n'est pas celui de ta console. Le téléphone ne peut pas le changer ; passe la carte dans R36S Studio sur ordinateur, « Choisir l'écran de la console ». Pour l'éviter, installe KNULLI depuis l'ordinateur, à partir de la carte d'origine de la console : son écran est gardé et reposé tout seul."
    const val FW_ARKOS_K36_TAGLINE = "ArkOS pour les clones"
    const val FW_ARKOS_K36_DESC = "Version d'ArkOS faite pour les consoles clones (K36 et semblables). Elle n'est plus mise à jour, mais elle a remis en route deux clones différents avec R36S Studio."
    const val FW_ARKOS_K36_NOTE = "Sur la page du projet, prends la variante « K36 and Similar Clones » (fichier .img.xz). Les fichiers sont hébergés hors de GitHub (Drive, Mediafire, MEGA)."
    const val FW_EMUELEC_TAGLINE = "Le système d'origine de beaucoup de clones"
    const val FW_EMUELEC_DESC = "Une autre option pour les consoles clones, déjà testée avec succès sur l'une d'elles."
    const val FW_EMUELEC_NOTE = "La page du projet ne propose pas d'image toute prête pour ces consoles. Le plus sûr : réinstaller une sauvegarde de la carte d'origine de ta console avec « Restaurer une sauvegarde »."
    const val FW_ARKOS_TAGLINE = "La référence de la R36S"
    const val FW_ARKOS_DESC = "Le système de référence pour la R36S, qui annonce aussi prendre en charge de nombreuses consoles clones. Mis à jour par la communauté (dArkOS)."
    const val FW_ARKOS_NOTE = "Le fichier se télécharge depuis les liens de la page du projet (MEGA, Google Drive…), pas directement sur GitHub."
    const val FW_DARKOSEN_TAGLINE = "Conseillé pour une R36S d'origine"
    const val FW_DARKOSEN_DESC = "Version enrichie de dArkOS, mise à jour environ toutes les deux semaines. Uniquement pour les R36 d'origine (R36S, R36S Plus, R36H, R36H ProMax) : ne fonctionne sur aucune console clone."
    const val FW_DARKOSEN_NOTE = "Le fichier est publié en deux morceaux d'archive 7-Zip à assembler : c'est à faire sur un ordinateur."
    const val FW_ROCKNIX_TAGLINE = "Récent, transfert de jeux par USB"
    const val FW_ROCKNIX_DESC = "Un système plus récent, avec le transfert de jeux par USB intégré."
    const val FW_ROCKNIX_NOTE = "Sur une R36S, ROCKNIX demande un réglage sur la carte juste après l'installation. Seule la version ordinateur de R36S Studio sait le faire."
    const val FW_AMBERELEC_TAGLINE = "Pour la même famille de puce"
    const val FW_AMBERELEC_DESC = "Conçu pour la même famille de puce (RK3326) que la R36S. Compatibilité R36S non officiellement confirmée."
    const val FW_MINUI_TAGLINE = "Interface minimaliste"
    const val FW_MINUI_DESC = "Interface minimaliste. Portage communautaire pour R36S, distinct du projet officiel."
    const val FW_MINUI_NOTE = "Le fichier publié est une archive .zip de fichiers à copier sur une carte déjà formatée, pas une image de carte : l'appli ne peut pas l'installer."
    const val FW_R36DROID_TAGLINE = "Android sur la R36S"
    const val FW_R36DROID_DESC = "Portage communautaire d'Android (LineageOS) pour R36S."
    const val FW_ANDR36OID_TAGLINE = "Un autre Android pour la R36S"
    const val FW_ANDR36OID_DESC = "Autre portage communautaire d'Android (LineageOS) pour R36S."
    const val FW_ANDROID_NOTE = "Très expérimental : lors des essais de R36S Studio sur une R36S, la console restait figée au démarrage."
    const val CANCEL = "Annuler"
    const val CLOSE = "Fermer"
    const val OK = "D'accord"

    // --- Confirmation (fond rouge) ---
    const val CONFIRM_TITLE = "Attention"
    const val CONFIRM_CHECKBOX = "Je comprends que toutes les données de cette carte seront effacées"
    const val CONFIRM_GO = "Effacer et écrire"
    fun confirmErase(display: String, sizeBytes: Long) =
        "Toutes les données de « $display » (${formatSize(sizeBytes)}) seront définitivement effacées."
    fun confirmSource(label: String) = "Fichier écrit sur la carte : $label"
    const val CONFIRM_GO_ERASE = "Effacer la carte"
    const val CONFIRM_ERASE_NOTE = "La carte sera vierge : il faudra ensuite y installer un système."

    // --- Journal de bord ---
    const val LOG_TITLE_ACTIVE = "OPÉRATION ACTIVE"
    const val LOG_TITLE_IDLE = "En attente"
    const val LOG_EMPTY = "Le journal de bord s'affichera ici."
    const val OP_FLASH = "Installation du système"
    const val OP_BACKUP = "Sauvegarde de la carte"
    const val OP_ERASE = "Effacement de la carte"
    const val PHASE_ERASE = "Effacement de la carte"
    const val LOG_ERASE_START = "Effacement de la carte…"
    const val LOG_ERASE_DONE = "Carte effacée et vérifiée : elle est vierge. Tu peux y installer un système."
    const val LOG_RECONNECTING = "Le lecteur de carte ne répond plus : nouvelle tentative, ne débranche rien…"
    const val LOG_RECONNECTED = "Le lecteur répond de nouveau : l'écriture reprend là où elle s'était arrêtée, plus doucement."
    const val OP_DOWNLOAD = "Téléchargement"
    const val OP_UPDATE = "Mise à jour de R36S Studio"
    fun logUpdateFound(build: String) = "Nouvelle version trouvée ($build) : téléchargement…"
    const val LOG_UPDATE_INSTALLING = "Installation de la nouvelle version…"
    const val LOG_UPDATE_CONFIRM = "Si le téléphone le demande, accepte la mise à jour. L'appli va se fermer puis se rouvrir (rouvre-la si besoin)."
    const val ERROR_UPDATE = "La mise à jour n'a pas pu s'installer. Désinstalle R36S Studio, puis installe la dernière version à la main."
    const val LOG_UPDATE_SECOND_TRY = "Deuxième essai : le téléphone ouvre son installateur. Appuie sur « Mettre à jour » ou « Installer »."
    const val ERROR_UPDATE_REFUSED =
        "La mise à jour n'a pas été acceptée. Ferme et rouvre R36S Studio, puis appuie sur « Mettre à jour » quand le téléphone le demande."
    const val ERROR_UPDATE_DOWNLOAD = "La mise à jour n'a pas pu être téléchargée. L'appli continue avec la version actuelle."
    const val PHASE_WRITE = "Écriture sur la carte"
    const val PHASE_VERIFY = "Vérification de la carte"
    const val PHASE_READ = "Lecture de la carte"
    const val PHASE_VERIFY_SOURCE = "Seconde lecture de contrôle"
    const val PHASE_DOWNLOAD = "Téléchargement"
    const val PHASE_CHECK_FILE = "Vérification du fichier"
    const val KEEP_OPEN = "Ne débranche pas la carte et ne ferme pas R36S Studio."
    const val NOTIFICATION_CHANNEL = "Opération en cours"
    const val NOTIFICATION_TEXT = "Ne débranche pas la carte."
    const val LOG_NO_BACKGROUND = "Garde R36S Studio affiché à l'écran jusqu'à la fin."

    const val LOG_RESOLVING = "Recherche de la dernière version…"
    fun logDownloading(name: String) = "Téléchargement de $name"
    const val LOG_DOWNLOAD_VERIFIED = "Fichier téléchargé et vérifié (SHA-256)."
    const val LOG_FLASH_START = "Écriture sur la carte…"
    const val LOG_VERIFY_START = "Relecture de la carte pour vérification…"
    fun logFlashDone(bytes: Long) = "Système écrit et vérifié (${formatSize(bytes)})."
    const val LOG_CAN_REMOVE = "Tu peux retirer la carte du téléphone."
    const val LOG_BACKUP_START = "Lecture de la carte…"
    const val LOG_BACKUP_VERIFY = "Seconde lecture de contrôle…"
    fun logBackupWhole(bytes: Long) = "Toute la carte sera copiée (${formatSize(bytes)})."
    fun logBackupUsed(bytes: Long, cardBytes: Long) =
        "Seule la partie utilisée de la carte est copiée : ${formatSize(bytes)} sur ${formatSize(cardBytes)}."
    fun logBackupDone(bytes: Long) = "Sauvegarde terminée et contrôlée (${formatSize(bytes)} de carte)."
    const val LOG_BACKUP_NEXT = "Pour cloner : retire cette carte, branche la carte neuve, puis « Restaurer une sauvegarde »."
    const val LOG_CANCELLED = "Opération annulée."
    const val LOG_CANCELLED_FLASH = "Opération annulée. La carte est incomplète : recommence l'installation avant de l'utiliser."
    const val LOG_CANCELLING = "Annulation en cours…"
    fun logDetail(detail: String) = "[détail] $detail"

    // --- Erreurs (message principal sans jargon) ---
    const val ERROR_SEVEN_ZIP =
        "Ce fichier est une archive 7-Zip. Décompresse-la d'abord — tu obtiendras un fichier .img que tu pourras installer directement."
    const val ERROR_UNSUPPORTED = "Ce fichier ne peut pas être installé sur une carte."
    const val ERROR_FILE_UNREADABLE = "Impossible de lire ce fichier."
    fun errorTooLarge(cardBytes: Long) =
        "Ce système est trop gros pour ta carte (${formatSize(cardBytes)}). Prends une carte plus grande."
    const val ERROR_VERIFY = "La carte ne contient pas exactement ce qui a été écrit. Elle est peut-être défaillante : essaie une autre carte."
    const val ERROR_SOURCE_UNSTABLE =
        "Ta carte ne renvoie pas deux fois le même contenu : elle est défaillante, cette sauvegarde n'est pas fiable. Le fichier a été gardé et marqué « instable »."
    const val ERROR_WRITE_PROTECTED =
        "Le lecteur dit que cette carte est protégée en écriture. Rien n'a été modifié. Enfonce bien la carte dans le lecteur et recommence ; si ça persiste, essaie un autre lecteur ou une autre carte."
    const val ERROR_CARD_GONE =
        "La carte ne répond plus. Vérifie qu'elle est bien branchée, puis recommence. Si ça se répète au même endroit, essaie un autre lecteur ou une autre carte."
    const val ERROR_NO_CARD = "Aucune carte prête. Branche ta carte SD et autorise l'appli à l'utiliser."
    const val ERROR_SAME_CARD = "C'est la carte que tu viens de sauvegarder. Retire-la et branche la carte neuve."
    const val ERROR_CHECKSUM = "Le fichier téléchargé est abîmé. Recommence le téléchargement."
    const val ERROR_NETWORK = "Le téléchargement a échoué. Vérifie ta connexion internet."
    fun errorNoSpace(needed: Long) = "Il n'y a pas assez de place sur le téléphone (${formatSize(needed)} nécessaires)."
    const val ERROR_BACKUP_WRITE = "Impossible d'écrire la sauvegarde sur le téléphone. Vérifie la place disponible."
    const val ERROR_GENERIC = "Une erreur est survenue."

    /** Tailles en base 1024 partout, comme la version ordinateur. */
    fun formatSize(bytes: Long): String {
        val gib = bytes / (1024.0 * 1024 * 1024)
        if (gib >= 1) return String.format(Locale.FRANCE, "%.1f Go", gib)
        val mib = bytes / (1024.0 * 1024)
        return String.format(Locale.FRANCE, "%.0f Mo", mib)
    }

    fun formatSpeed(bytesPerSecond: Long): String =
        String.format(Locale.FRANCE, "%.1f Mo/s", bytesPerSecond / (1024.0 * 1024))

    fun formatRemaining(seconds: Long): String = when {
        seconds < 60 -> "$seconds s restantes"
        seconds < 3600 -> "${seconds / 60} min ${seconds % 60} s restantes"
        else -> "${seconds / 3600} h ${(seconds % 3600) / 60} min restantes"
    }
}
