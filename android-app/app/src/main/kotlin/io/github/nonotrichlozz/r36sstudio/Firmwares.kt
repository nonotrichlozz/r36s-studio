// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio

import io.github.nonotrichlozz.r36sstudio.core.CancelToken
import io.github.nonotrichlozz.r36sstudio.core.Imaging
import io.github.nonotrichlozz.r36sstudio.core.OperationCancelled
import io.github.nonotrichlozz.r36sstudio.core.ProgressMeter
import org.json.JSONObject
import java.io.File
import java.io.FileInputStream
import java.io.FileOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * Firmwares téléchargeables directement (mêmes sources et mêmes sommes de
 * contrôle de repli que `r36s_studio/identify/firmware_catalog.py`). Seuls
 * ceux qui démarrent sans réglage après le flash figurent ici : ROCKNIX sur
 * R36S demande des fichiers à poser sur la carte après coup, ce que cette
 * version Android ne sait pas encore faire.
 */
data class Firmware(
    val id: String,
    val title: String,
    val description: String,
    val repo: String,
    val pattern: Regex,
    val fallbackName: String,
    val fallbackUrl: String,
    val fallbackSha256: String,
)

data class ResolvedAsset(val name: String, val url: String, val sha256: String, val sizeBytes: Long)

class ChecksumMismatchException : IOException("Somme de contrôle différente")

class NotEnoughSpaceException(val neededBytes: Long) : IOException("Pas assez de place sur le téléphone")

object Firmwares {
    private const val ARCHR_RELEASES = "https://github.com/archr-linux/Arch-R/releases"
    private const val KNULLI_RELEASES = "https://github.com/knulli-cfw/knulli-linux/releases"

    val ALL: List<Firmware> = listOf(
        Firmware(
            id = "archr",
            title = "Arch R — R36S d'origine",
            description = Strings.FIRMWARE_ARCHR_DESC,
            repo = "archr-linux/Arch-R",
            pattern = Regex("^ArchR-R36S\\.aarch64-\\d{8}-original\\.img\\.gz$"),
            fallbackName = "ArchR-R36S.aarch64-20260709-original.img.gz",
            fallbackUrl = "$ARCHR_RELEASES/download/v2.1.1/ArchR-R36S.aarch64-20260709-original.img.gz",
            fallbackSha256 = "035b58c446e0ffc7f6e23d1c8ef574fd0970307af6c3a41817abe82239aaf577",
        ),
        Firmware(
            id = "archr_clone",
            title = "Arch R — clone de R36S",
            description = Strings.FIRMWARE_ARCHR_CLONE_DESC,
            repo = "archr-linux/Arch-R",
            pattern = Regex("^ArchR-R36S\\.aarch64-\\d{8}-clone\\.img\\.gz$"),
            fallbackName = "ArchR-R36S.aarch64-20260709-clone.img.gz",
            fallbackUrl = "$ARCHR_RELEASES/download/v2.1.1/ArchR-R36S.aarch64-20260709-clone.img.gz",
            fallbackSha256 = "3ea0b970595e0086bd7478e0d17acf71adf1368499b45f1bba21ef6ab63660e2",
        ),
        Firmware(
            id = "knulli",
            title = "KNULLI — R36S",
            description = Strings.FIRMWARE_KNULLI_DESC,
            repo = "knulli-cfw/knulli-linux",
            pattern = Regex("^knulli-rk3326-r36s-.*\\.img\\.gz$"),
            fallbackName = "knulli-rk3326-r36s-scarab-20260510.img.gz",
            fallbackUrl = "$KNULLI_RELEASES/download/20260511/knulli-rk3326-r36s-scarab-20260510.img.gz",
            fallbackSha256 = "068f405b5edcb0414430ce5ed24119ea62a945fe1be088cf9ca0bf22aabda466",
        ),
    )

    /**
     * Dernière version publiée, avec sa SHA-256 (champ `digest` de GitHub).
     * Si GitHub ne répond pas ou ne donne pas de somme de contrôle, repli sur
     * la version connue : jamais de téléchargement sans SHA-256.
     */
    fun resolve(firmware: Firmware): ResolvedAsset {
        try {
            val json = httpGetText("https://api.github.com/repos/${firmware.repo}/releases/latest")
            val assets = JSONObject(json).optJSONArray("assets")
            if (assets != null) {
                for (i in 0 until assets.length()) {
                    val asset = assets.getJSONObject(i)
                    val name = asset.optString("name")
                    if (!firmware.pattern.matches(name)) continue
                    val digest = asset.optString("digest")
                    val url = asset.optString("browser_download_url")
                    if (digest.startsWith("sha256:") && url.startsWith("https://")) {
                        return ResolvedAsset(name, url, digest.removePrefix("sha256:").lowercase(), asset.optLong("size", -1))
                    }
                }
            }
        } catch (e: Exception) {
            // Repli ci-dessous.
        }
        return ResolvedAsset(firmware.fallbackName, firmware.fallbackUrl, firmware.fallbackSha256, -1)
    }

    private fun open(url: String): HttpURLConnection {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = 20_000
        connection.readTimeout = 30_000
        connection.instanceFollowRedirects = true
        connection.setRequestProperty("User-Agent", "R36S-Studio-Android")
        connection.setRequestProperty("Accept", "application/vnd.github+json, application/octet-stream, */*")
        return connection
    }

    private fun httpGetText(url: String): String {
        val connection = open(url)
        try {
            if (connection.responseCode != 200) throw IOException("HTTP ${connection.responseCode}")
            return connection.inputStream.use { it.readBytes().toString(Charsets.UTF_8) }
        } finally {
            connection.disconnect()
        }
    }

    fun sha256Of(file: File, cancel: CancelToken): String {
        val digest = MessageDigest.getInstance("SHA-256")
        val buffer = ByteArray(1024 * 1024)
        FileInputStream(file).use { input ->
            while (true) {
                if (cancel.cancelled) throw OperationCancelled()
                val n = input.read(buffer)
                if (n < 0) break
                digest.update(buffer, 0, n)
            }
        }
        return Imaging.toHex(digest.digest())
    }

    /**
     * Télécharge dans `directory` avec progression réelle, vérifie la SHA-256,
     * et ne laisse jamais un fichier non vérifié sous son nom définitif. Un
     * fichier déjà présent et intact est réutilisé.
     */
    fun download(asset: ResolvedAsset, directory: File, cancel: CancelToken, meter: ProgressMeter): File {
        if (!directory.isDirectory && !directory.mkdirs()) throw IOException("Dossier de téléchargement inaccessible")
        val target = File(directory, asset.name)
        if (target.isFile && sha256Of(target, cancel) == asset.sha256) return target

        val part = File(directory, asset.name + ".part")
        val connection = open(asset.url)
        try {
            if (connection.responseCode != 200) throw IOException("HTTP ${connection.responseCode}")
            val total = if (asset.sizeBytes > 0) asset.sizeBytes else connection.contentLengthLong
            if (total > 0 && directory.usableSpace < total + 64L * 1024 * 1024) throw NotEnoughSpaceException(total)
            val digest = MessageDigest.getInstance("SHA-256")
            val buffer = ByteArray(256 * 1024)
            var done = 0L
            connection.inputStream.use { input ->
                FileOutputStream(part).use { output ->
                    while (true) {
                        if (cancel.cancelled) throw OperationCancelled()
                        val n = input.read(buffer)
                        if (n < 0) break
                        output.write(buffer, 0, n)
                        digest.update(buffer, 0, n)
                        done += n
                        meter.update(done, if (total > 0) total else done, n.toLong())
                    }
                    output.fd.sync()
                }
            }
            meter.update(done, if (total > 0) total else done, 0, force = true)
            if (Imaging.toHex(digest.digest()) != asset.sha256) throw ChecksumMismatchException()
            if (target.exists()) target.delete()
            if (!part.renameTo(target)) throw IOException("Impossible d'enregistrer le fichier téléchargé")
            return target
        } catch (e: Exception) {
            part.delete()
            throw e
        } finally {
            connection.disconnect()
        }
    }
}
