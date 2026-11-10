// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat

/**
 * Garde l'appli en vie pendant une opération (écriture, sauvegarde,
 * téléchargement) quand l'utilisateur passe à une autre appli ou que l'écran
 * s'éteint : sans lui, Android peut couper l'appli au milieu d'une écriture.
 *
 * Il ne fait aucun travail lui-même : l'opération tourne dans
 * `MainViewModel`. Tout est « au mieux » -- s'il ne peut pas démarrer,
 * l'opération continue quand même (l'écran reste allumé tant que l'appli est
 * affichée).
 */
class OperationService : Service() {

    private var wakeLock: PowerManager.WakeLock? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        instance = this
        val title = intent?.getStringExtra(EXTRA_TITLE) ?: Strings.APP_TITLE
        try {
            // Toujours appelé, même si l'arrêt a déjà été demandé : Android
            // l'exige après un startForegroundService.
            val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE
            } else {
                0
            }
            ServiceCompat.startForeground(this, NOTIFICATION_ID, buildNotification(title), type)
        } catch (e: Exception) {
            finish()
            return START_NOT_STICKY
        }
        if (!wanted) {
            finish()
            return START_NOT_STICKY
        }
        if (wakeLock == null) {
            try {
                val power = getSystemService(Context.POWER_SERVICE) as PowerManager
                wakeLock = power.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "r36sstudio:operation").apply {
                    setReferenceCounted(false)
                    acquire(WAKE_LOCK_TIMEOUT_MS)
                }
            } catch (ignored: Exception) {
            }
        }
        return START_NOT_STICKY
    }

    private fun buildNotification(title: String): Notification {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, Strings.NOTIFICATION_CHANNEL, NotificationManager.IMPORTANCE_LOW),
            )
        }
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(Strings.NOTIFICATION_TEXT)
            .setOngoing(true)
            .setContentIntent(open)
            .build()
    }

    private fun finish() {
        releaseWakeLock()
        try {
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        } catch (ignored: Exception) {
        }
        stopSelf()
    }

    private fun releaseWakeLock() {
        try {
            wakeLock?.let { if (it.isHeld) it.release() }
        } catch (ignored: Exception) {
        }
        wakeLock = null
    }

    override fun onDestroy() {
        releaseWakeLock()
        if (instance === this) instance = null
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL_ID = "operation"
        private const val NOTIFICATION_ID = 1
        private const val EXTRA_TITLE = "title"

        // Garde-fou : jamais de téléphone tenu éveillé indéfiniment.
        private const val WAKE_LOCK_TIMEOUT_MS = 6L * 60 * 60 * 1000

        @Volatile
        private var wanted = false

        @Volatile
        private var instance: OperationService? = null

        /** Renvoie `false` si Android a refusé (l'opération continue sans). */
        fun start(context: Context, title: String): Boolean {
            wanted = true
            return try {
                ContextCompat.startForegroundService(
                    context,
                    Intent(context, OperationService::class.java).putExtra(EXTRA_TITLE, title),
                )
                true
            } catch (e: Exception) {
                wanted = false
                false
            }
        }

        /**
         * Sans `stopService` : appelé juste après `start`, il ferait planter
         * l'appli (service arrêté avant d'être passé au premier plan). Le
         * service s'arrête lui-même, tout de suite s'il tourne, sinon dès son
         * démarrage (`wanted`).
         */
        fun stop() {
            wanted = false
            Handler(Looper.getMainLooper()).post { instance?.finish() }
        }
    }
}
