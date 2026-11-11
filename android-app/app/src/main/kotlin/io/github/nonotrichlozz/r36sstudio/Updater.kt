// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio

import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.os.Build
import androidx.core.content.IntentCompat
import io.github.nonotrichlozz.r36sstudio.core.CancelToken
import io.github.nonotrichlozz.r36sstudio.core.ProgressMeter
import kotlinx.coroutines.flow.MutableStateFlow
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.net.HttpURLConnection
import java.net.URL

/**
 * Mise à jour automatique au lancement. La branche `android-apk` du dépôt
 * (remplie par `.github/workflows/android.yml`) contient l'APK et un
 * `version.json` ; ce dernier n'est publié que pour un APK signé avec la clé
 * stable -- un APK signé autrement ne pourrait pas remplacer l'appli
 * installée.
 *
 * Android ne laisse jamais une appli se remplacer en cachette : il demande
 * une confirmation (au moins la première fois). Toute erreur réseau = pas
 * de mise à jour, jamais de blocage : l'appli marche hors ligne.
 */
object Updater {
    private const val BASE = "https://raw.githubusercontent.com/nonotrichlozz/r36s-studio/android-apk/"
    const val APK_NAME = "R36S-Studio-Android.apk"
    private const val MAX_APK_BYTES = 200L * 1024 * 1024
    const val ACTION_INSTALL_STATUS = "io.github.nonotrichlozz.r36sstudio.INSTALL_STATUS"

    data class Info(val versionCode: Int, val build: String, val sha256: String, val sizeBytes: Long)

    /** Dernier échec d'installation rapporté par Android (détail brut), ou `null`. */
    val failure = MutableStateFlow<String?>(null)

    /** `null` : rien de plus récent, ou impossible de le savoir. */
    fun check(): Info? {
        return try {
            // Le paramètre contourne le cache de GitHub (quelques minutes sinon).
            val connection = URL(BASE + "version.json?t=" + System.currentTimeMillis()).openConnection() as HttpURLConnection
            connection.connectTimeout = 8_000
            connection.readTimeout = 8_000
            connection.setRequestProperty("User-Agent", "R36S-Studio-Android")
            val text = try {
                if (connection.responseCode != 200) return null
                connection.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
            } finally {
                connection.disconnect()
            }
            val json = JSONObject(text)
            val info = Info(
                versionCode = json.getInt("versionCode"),
                build = json.optString("build"),
                sha256 = json.getString("sha256").lowercase(),
                sizeBytes = json.optLong("size", -1),
            )
            val valid = Regex("^[0-9a-f]{64}$").matches(info.sha256) && info.sizeBytes in 1..MAX_APK_BYTES
            if (valid && info.versionCode > BuildConfig.VERSION_CODE) info else null
        } catch (e: Exception) {
            null
        }
    }

    /** Télécharge l'APK et vérifie sa SHA-256 (jamais d'installation sans). */
    fun download(context: Context, info: Info, cancel: CancelToken, meter: ProgressMeter): File {
        val asset = ResolvedAsset(APK_NAME, BASE + APK_NAME + "?t=" + info.sha256.take(12), info.sha256, info.sizeBytes)
        return Firmwares.download(asset, File(context.cacheDir, "update"), cancel, meter)
    }

    /** Remet l'APK à Android. Le résultat arrive dans `UpdateReceiver`. */
    fun install(context: Context, apk: File) {
        failure.value = null
        val installer = context.packageManager.packageInstaller
        val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
        params.setAppPackageName(context.packageName)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            // Sans confirmation quand Android l'accepte (appli déjà mise à jour par elle-même).
            params.setRequireUserAction(PackageInstaller.SessionParams.USER_ACTION_NOT_REQUIRED)
        }
        val sessionId = installer.createSession(params)
        installer.openSession(sessionId).use { session ->
            session.openWrite("base.apk", 0, apk.length()).use { output ->
                FileInputStream(apk).use { it.copyTo(output, 256 * 1024) }
                session.fsync(output)
            }
            val intent = Intent(context, UpdateReceiver::class.java).setAction(ACTION_INSTALL_STATUS)
            val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0)
            session.commit(PendingIntent.getBroadcast(context, sessionId, intent, flags).intentSender)
        }
    }
}

/** Reçoit la réponse d'Android à une demande d'installation. */
class UpdateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Updater.ACTION_INSTALL_STATUS) return
        when (val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)) {
            PackageInstaller.STATUS_SUCCESS -> Unit
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                // Android veut une confirmation : on affiche sa fenêtre.
                val confirm = IntentCompat.getParcelableExtra(intent, Intent.EXTRA_INTENT, Intent::class.java)
                try {
                    if (confirm != null) context.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                } catch (e: Exception) {
                    Updater.failure.value = "confirmation impossible : ${e.message}"
                }
            }
            else -> {
                val message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE) ?: ""
                Updater.failure.value = "statut $status $message".trim()
            }
        }
    }
}

/** Après une mise à jour, rouvre l'appli quand Android le permet (au mieux). */
class RestartReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        try {
            context.startActivity(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (ignored: Exception) {
        }
    }
}
