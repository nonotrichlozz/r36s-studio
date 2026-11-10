// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.security.MessageDigest
import java.util.zip.Deflater
import java.util.zip.GZIPOutputStream

enum class Phase { WRITE, VERIFY, READ, VERIFY_SOURCE }

interface ProgressListener {
    fun onPhase(phase: Phase)

    /** Progression réelle, jamais simulée : octets traités, total, débit. */
    fun onProgress(done: Long, total: Long, bytesPerSecond: Long)
}

class ImageTooLargeException(val cardBytes: Long) : IOException("L'image est plus grande que la carte")

class VerifyFailedException(val offset: Long) : IOException("Relecture différente de l'image à l'octet $offset")

/** La carte source a renvoyé deux contenus différents en deux lectures. */
class SourceUnstableException : IOException("La carte source ne renvoie pas deux fois le même contenu")

/** Limite les événements de progression (~4/seconde) et calcule le débit. */
class ProgressMeter(
    private val listener: ProgressListener,
    private val clock: () -> Long = System::nanoTime,
) {
    private var startNanos = clock()
    private var lastEmitNanos = 0L
    private var workBytes = 0L

    fun reset() {
        startNanos = clock()
        lastEmitNanos = 0L
        workBytes = 0L
    }

    /** `work` : octets réellement lus/écrits sur la carte depuis le dernier appel (pour le débit). */
    fun update(done: Long, total: Long, work: Long, force: Boolean = false) {
        workBytes += work
        val now = clock()
        if (!force && now - lastEmitNanos < EMIT_INTERVAL_NANOS) return
        lastEmitNanos = now
        val elapsed = now - startNanos
        val speed = if (elapsed > 0) (workBytes.toDouble() * 1e9 / elapsed).toLong() else 0L
        listener.onProgress(done, total, speed)
    }

    companion object {
        private const val EMIT_INTERVAL_NANOS = 250_000_000L
    }
}

object Imaging {
    const val CHUNK_BYTES = 1024 * 1024

    /**
     * Écrit l'image sur la carte puis la relit et la compare octet par octet.
     *
     * `openSource` rouvre le fichier (compressé ou non) depuis le début : une
     * fois pour écrire, une fois pour vérifier. La progression se mesure sur
     * les octets lus dans ce fichier (`sourceBytes` = sa taille), ce qui reste
     * exact même quand la taille décompressée n'est pas connue d'avance.
     *
     * Renvoie le nombre d'octets écrits sur la carte.
     */
    @Throws(IOException::class)
    fun flash(
        openSource: () -> InputStream,
        sourceBytes: Long,
        format: ImageFormat,
        device: BlockDevice,
        cancel: CancelToken,
        listener: ProgressListener,
    ): Long {
        val blockSize = device.blockSize
        require(CHUNK_BYTES % blockSize == 0) { "Taille de bloc non gérée : $blockSize" }
        val cardBytes = device.sizeBytes
        val meter = ProgressMeter(listener)
        val buffer = ByteArray(CHUNK_BYTES)

        // --- Écriture ---
        listener.onPhase(Phase.WRITE)
        meter.reset()
        var written = 0L
        CountingInputStream(openSource()).use { counting ->
            ImageSource.openDecompressed(counting, format).use { image ->
                while (true) {
                    if (cancel.cancelled) throw OperationCancelled()
                    val n = readFully(image, buffer)
                    if (n == 0) break
                    val padded = roundUp(n, blockSize)
                    if (padded > n) java.util.Arrays.fill(buffer, n, padded, 0.toByte())
                    if (written + padded > cardBytes) throw ImageTooLargeException(cardBytes)
                    device.write(written / blockSize, buffer, padded / blockSize)
                    written += padded
                    meter.update(counting.count, sourceBytes, padded.toLong())
                    if (n < buffer.size) break
                }
                meter.update(counting.count, sourceBytes, 0, force = true)
            }
        }
        if (written == 0L) throw UnsupportedImageException("Le fichier est vide")
        device.flush()

        // --- Vérification : relecture de la carte, comparée à l'image ---
        listener.onPhase(Phase.VERIFY)
        meter.reset()
        val readBack = ByteArray(CHUNK_BYTES)
        var verified = 0L
        CountingInputStream(openSource()).use { counting ->
            ImageSource.openDecompressed(counting, format).use { image ->
                while (verified < written) {
                    if (cancel.cancelled) throw OperationCancelled()
                    val n = readFully(image, buffer)
                    if (n == 0) throw VerifyFailedException(verified)
                    val padded = roundUp(n, blockSize)
                    if (padded > n) java.util.Arrays.fill(buffer, n, padded, 0.toByte())
                    device.read(verified / blockSize, readBack, padded / blockSize)
                    for (i in 0 until padded) {
                        if (buffer[i] != readBack[i]) throw VerifyFailedException(verified + i)
                    }
                    verified += padded
                    meter.update(counting.count, sourceBytes, padded.toLong())
                }
                meter.update(counting.count, sourceBytes, 0, force = true)
            }
        }
        return written
    }

    /**
     * Sauvegarde les `lengthBytes` premiers octets de la carte dans `output`
     * (compressé en gzip), puis relit la carte une seconde fois et compare
     * les empreintes : une carte dégradée peut renvoyer des octets faux sans
     * signaler d'erreur. Renvoie la SHA-256 (hexadécimal) du contenu brut.
     */
    @Throws(IOException::class)
    fun backup(
        device: BlockDevice,
        lengthBytes: Long,
        output: OutputStream,
        cancel: CancelToken,
        listener: ProgressListener,
        verifySource: Boolean = true,
    ): String {
        val blockSize = device.blockSize
        require(CHUNK_BYTES % blockSize == 0) { "Taille de bloc non gérée : $blockSize" }
        require(lengthBytes > 0 && lengthBytes % blockSize == 0L && lengthBytes <= device.sizeBytes) {
            "Longueur de sauvegarde invalide : $lengthBytes"
        }
        val meter = ProgressMeter(listener)
        val buffer = ByteArray(CHUNK_BYTES)

        listener.onPhase(Phase.READ)
        meter.reset()
        val first = MessageDigest.getInstance("SHA-256")
        val gzip = FastGzipOutputStream(output)
        try {
            readRange(device, lengthBytes, buffer, cancel, meter) { n ->
                first.update(buffer, 0, n)
                gzip.write(buffer, 0, n)
            }
            gzip.finish()
            gzip.flush()
        } finally {
            gzip.close()
        }
        val firstHash = toHex(first.digest())

        if (verifySource) {
            listener.onPhase(Phase.VERIFY_SOURCE)
            meter.reset()
            val second = MessageDigest.getInstance("SHA-256")
            readRange(device, lengthBytes, buffer, cancel, meter) { n -> second.update(buffer, 0, n) }
            if (toHex(second.digest()) != firstHash) throw SourceUnstableException()
        }
        return firstHash
    }

    private fun readRange(
        device: BlockDevice,
        lengthBytes: Long,
        buffer: ByteArray,
        cancel: CancelToken,
        meter: ProgressMeter,
        consume: (Int) -> Unit,
    ) {
        val blockSize = device.blockSize
        var done = 0L
        while (done < lengthBytes) {
            if (cancel.cancelled) throw OperationCancelled()
            val n = minOf(buffer.size.toLong(), lengthBytes - done).toInt()
            device.read(done / blockSize, buffer, n / blockSize)
            consume(n)
            done += n
            meter.update(done, lengthBytes, n.toLong())
        }
        meter.update(done, lengthBytes, 0, force = true)
    }

    private fun roundUp(value: Int, multiple: Int): Int = (value + multiple - 1) / multiple * multiple

    fun toHex(bytes: ByteArray): String {
        val out = StringBuilder(bytes.size * 2)
        for (b in bytes) {
            val v = b.toInt() and 0xFF
            out.append(HEX[v ushr 4]).append(HEX[v and 0x0F])
        }
        return out.toString()
    }

    private const val HEX = "0123456789abcdef"
}

/** gzip au niveau le plus rapide : sur un téléphone, c'est la carte qui doit limiter le débit. */
private class FastGzipOutputStream(out: OutputStream) : GZIPOutputStream(out, 64 * 1024) {
    init {
        def.setLevel(Deflater.BEST_SPEED)
    }
}
