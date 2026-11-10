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
    const val CARD_PROBLEM = "Carte illisible"
    const val CARD_NO_MEDIUM_HINT = "Le lecteur est branché, mais il n'y a pas de carte dedans."
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
    const val SECTION_SAFETY = "Par sécurité"
    const val BADGE_READY = "Prêt"
    const val BADGE_NO_CARD = "Branche une carte"

    // --- Choix du système ---
    const val PICKER_TITLE = "Quel système installer ?"
    const val PICKER_DOWNLOAD = "Télécharger et installer"
    const val PICKER_FILE = "Choisir un fichier sur le téléphone"
    const val PICKER_FILE_DESC = "Un fichier .img, .img.gz, .img.xz ou .zip que tu as déjà. Une archive .7z doit d'abord être décompressée."
    const val FIRMWARE_ARCHR_DESC = "Système récent pour la vraie R36S. L'espace pour les jeux apparaît au premier démarrage de la console."
    const val FIRMWARE_ARCHR_CLONE_DESC = "La même chose, pour les copies de R36S. Si l'écran reste noir avec l'autre version, essaie celle-ci."
    const val FIRMWARE_KNULLI_DESC = "Système complet et simple. Pas encore essayé par R36S Studio sur une vraie R36S."
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

    // --- Journal de bord ---
    const val LOG_TITLE_ACTIVE = "OPÉRATION ACTIVE"
    const val LOG_TITLE_IDLE = "En attente"
    const val LOG_EMPTY = "Le journal de bord s'affichera ici."
    const val OP_FLASH = "Installation du système"
    const val OP_BACKUP = "Sauvegarde de la carte"
    const val OP_DOWNLOAD = "Téléchargement"
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
    const val ERROR_CARD_GONE = "La carte ne répond plus. Vérifie qu'elle est bien branchée, puis recommence."
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
