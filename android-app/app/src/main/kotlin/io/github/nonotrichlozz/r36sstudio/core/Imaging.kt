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

/**
 * Reprise après un décrochage du lecteur : reçoit l'erreur, rouvre la carte
 * et la renvoie (ou `null` pour abandonner). Le morceau en cours est alors
 * réécrit ou relu au même endroit -- sans effet de bord.
 */
typealias CardRecovery = (IOException) -> BlockDevice?

/** Accès carte avec reprise : au plus `MAX_RECOVERIES` réouvertures par opération. */
private class Recovering(var device: BlockDevice, private val recover: CardRecovery?) {
    var recoveries = 0
        private set

    fun write(lba: Long, buffer: ByteArray, blocks: Int) = retry { device.write(lba, buffer, blocks) }

    fun read(lba: Long, buffer: ByteArray, blocks: Int) = retry { device.read(lba, buffer, blocks) }

    fun flush() = retry { device.flush() }

    private inline fun retry(action: () -> Unit) {
        while (true) {
            try {
                action()
                return
            } catch (e: IOException) {
                // Refus réel de la carte, annulation : jamais de reprise.
                if (recover == null || e is WriteProtectedException || e is OperationCancelled ||
                    recoveries >= Imaging.MAX_RECOVERIES
                ) {
                    throw e
                }
                recoveries++
                val reopened = recover.invoke(e) ?: throw e
                if (reopened.blockSize != device.blockSize || reopened.blockCount != device.blockCount) {
                    throw IOException("Ce n'est plus la même carte après la reprise")
                }
                device = reopened
            }
        }
    }
}

object Imaging {
    const val CHUNK_BYTES = 1024 * 1024

    /** Réouvertures du lecteur acceptées pendant une même opération. */
    const val MAX_RECOVERIES = 3

    /** Effacement : début de la carte (tables, démarrage) et fin (copie de la table GPT). */
    const val ERASE_HEAD_BYTES = 32L * 1024 * 1024
    const val ERASE_TAIL_BYTES = 4L * 1024 * 1024

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
        recover: CardRecovery? = null,
    ): Long {
        val card = Recovering(device, recover)
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
                    card.write(written / blockSize, buffer, padded / blockSize)
                    written += padded
                    meter.update(counting.count, sourceBytes, padded.toLong())
                    if (n < buffer.size) break
                }
                meter.update(counting.count, sourceBytes, 0, force = true)
            }
        }
        if (written == 0L) throw UnsupportedImageException("Le fichier est vide")
        card.flush()

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
                    card.read(verified / blockSize, readBack, padded / blockSize)
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
     * Efface la carte : met à zéro son début (tables de partitions, démarrage,
     * début des systèmes de fichiers) et sa fin (copie de secours de la table
     * GPT), puis relit ces zones. La carte redevient « vierge » : le
     * téléphone et l'ordinateur n'y voient plus aucun système. Renvoie le
     * nombre d'octets effacés.
     */
    @Throws(IOException::class)
    fun erase(
        device: BlockDevice,
        cancel: CancelToken,
        listener: ProgressListener,
        recover: CardRecovery? = null,
    ): Long {
        val card = Recovering(device, recover)
        val blockSize = device.blockSize
        require(CHUNK_BYTES % blockSize == 0) { "Taille de bloc non gérée : $blockSize" }
        val size = device.sizeBytes
        val head = minOf(ERASE_HEAD_BYTES, size) / blockSize * blockSize
        val tailStart = maxOf(head, (size - ERASE_TAIL_BYTES) / blockSize * blockSize)
        val ranges = listOf(0L to head, tailStart to size).filter { it.second > it.first }
        val total = ranges.sumOf { it.second - it.first }
        val meter = ProgressMeter(listener)
        val zeros = ByteArray(CHUNK_BYTES)
        val readBack = ByteArray(CHUNK_BYTES)

        listener.onPhase(Phase.WRITE)
        meter.reset()
        var done = 0L
        for ((start, end) in ranges) {
            var offset = start
            while (offset < end) {
                if (cancel.cancelled) throw OperationCancelled()
                val n = minOf(CHUNK_BYTES.toLong(), end - offset).toInt()
                card.write(offset / blockSize, zeros, n / blockSize)
                offset += n
                done += n
                meter.update(done, total, n.toLong())
            }
        }
        meter.update(done, total, 0, force = true)
        card.flush()

        listener.onPhase(Phase.VERIFY)
        meter.reset()
        done = 0L
        for ((start, end) in ranges) {
            var offset = start
            while (offset < end) {
                if (cancel.cancelled) throw OperationCancelled()
                val n = minOf(CHUNK_BYTES.toLong(), end - offset).toInt()
                card.read(offset / blockSize, readBack, n / blockSize)
                for (i in 0 until n) {
                    if (readBack[i] != 0.toByte()) throw VerifyFailedException(offset + i)
                }
                offset += n
                done += n
                meter.update(done, total, n.toLong())
            }
        }
        meter.update(done, total, 0, force = true)
        return total
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
