// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Transport USB « Bulk-Only » : deux tuyaux (sortie, entrée). L'implémentation
 * Android est dans `usb/UsbCards.kt` ; les tests en fournissent une fausse.
 * Les deux méthodes renvoient le nombre d'octets transférés, négatif en cas d'échec.
 */
interface BulkTransport {
    fun bulkOut(data: ByteArray, offset: Int, length: Int): Int
    fun bulkIn(data: ByteArray, offset: Int, length: Int): Int

    /** Remise en état après une erreur de protocole (reset + clear halt). */
    fun resetRecovery()
}

open class ScsiException(
    message: String,
    val senseKey: Int = -1,
    val asc: Int = -1,
    val ascq: Int = -1,
) : IOException(message)

/** Le lecteur est là, mais aucune carte n'est dedans. */
class NoMediumException : ScsiException("Aucune carte dans le lecteur", 2, 0x3A, 0)

/**
 * Carte vue à travers un lecteur USB de stockage de masse (SCSI transparent
 * sur Bulk-Only Transport). Sans root : c'est l'appli qui parle directement
 * au lecteur, Android ne monte rien.
 */
class ScsiBlockDevice(
    private val transport: BulkTransport,
    private val lun: Int = 0,
) : BlockDevice {

    override var blockSize: Int = 0
        private set
    override var blockCount: Long = 0
        private set
    var vendor: String = ""
        private set
    var product: String = ""
        private set
    var removable: Boolean = false
        private set

    private var tag: Int = 1

    /** INQUIRY, attente que la carte soit prête, puis lecture de sa capacité. */
    @Throws(IOException::class)
    fun init() {
        inquiry()
        waitReady()
        readCapacity()
    }

    private fun inquiry() {
        val data = ByteArray(36)
        val cdb = byteArrayOf(0x12, 0, 0, 0, 36, 0)
        val status = execute(cdb, data, 0, data.size, directionIn = true, exact = false)
        if (status != 0) throw senseException("INQUIRY")
        removable = (data[1].toInt() and 0x80) != 0
        vendor = String(data, 8, 8, Charsets.US_ASCII).trim { it <= ' ' }
        product = String(data, 16, 16, Charsets.US_ASCII).trim { it <= ' ' }
    }

    private fun waitReady() {
        var last: ScsiException? = null
        for (attempt in 0 until READY_ATTEMPTS) {
            val status = execute(byteArrayOf(0, 0, 0, 0, 0, 0), null, 0, 0, directionIn = false, exact = true)
            if (status == 0) return
            val sense = senseException("TEST UNIT READY")
            if (sense.senseKey == 2 && sense.asc == 0x3A) throw NoMediumException()
            last = sense
            try {
                Thread.sleep(READY_DELAY_MS)
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
                throw IOException("Interrompu")
            }
        }
        throw last ?: ScsiException("La carte ne répond pas")
    }

    private fun readCapacity() {
        val data = ByteArray(8)
        val cdb = byteArrayOf(0x25, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        val status = execute(cdb, data, 0, data.size, directionIn = true, exact = false)
        if (status != 0) throw senseException("READ CAPACITY")
        val buffer = ByteBuffer.wrap(data).order(ByteOrder.BIG_ENDIAN)
        val lastLba = buffer.int.toLong() and 0xFFFFFFFFL
        val size = buffer.int
        if (lastLba == 0xFFFFFFFFL) throw ScsiException("Carte de plus de 2 To : non prise en charge")
        if (size <= 0 || size % 512 != 0) throw ScsiException("Taille de bloc inattendue : $size")
        blockSize = size
        blockCount = lastLba + 1
    }

    override fun read(lba: Long, buffer: ByteArray, blocks: Int) {
        transfer(lba, buffer, blocks, write = false)
    }

    override fun write(lba: Long, buffer: ByteArray, blocks: Int) {
        transfer(lba, buffer, blocks, write = true)
    }

    private fun transfer(lba: Long, buffer: ByteArray, blocks: Int, write: Boolean) {
        check(blockSize > 0) { "init() n'a pas été appelé" }
        require(blocks >= 0 && blocks.toLong() * blockSize <= buffer.size) { "Tampon trop petit" }
        if (lba < 0 || lba + blocks > blockCount) throw IOException("Accès hors de la carte (bloc $lba + $blocks)")
        val maxBlocks = maxOf(1, MAX_BYTES_PER_COMMAND / blockSize)
        var done = 0
        while (done < blocks) {
            val count = minOf(maxBlocks, blocks - done)
            val current = lba + done
            val cdb = ByteArray(10)
            cdb[0] = if (write) 0x2A else 0x28
            cdb[2] = (current ushr 24).toByte()
            cdb[3] = (current ushr 16).toByte()
            cdb[4] = (current ushr 8).toByte()
            cdb[5] = current.toByte()
            cdb[7] = (count ushr 8).toByte()
            cdb[8] = count.toByte()
            val status = execute(cdb, buffer, done * blockSize, count * blockSize, directionIn = !write, exact = true)
            if (status != 0) throw senseException(if (write) "WRITE(10) bloc $current" else "READ(10) bloc $current")
            done += count
        }
    }

    override fun flush() {
        // SYNCHRONIZE CACHE(10) : beaucoup de lecteurs ne la connaissent pas
        // (ILLEGAL REQUEST) -- sans gravité, ils n'ont alors pas de cache.
        val status = execute(byteArrayOf(0x35, 0, 0, 0, 0, 0, 0, 0, 0, 0), null, 0, 0, directionIn = false, exact = true)
        if (status != 0) {
            val sense = senseException("SYNCHRONIZE CACHE")
            if (sense.senseKey != 5) throw sense
        }
    }

    private fun senseException(what: String): ScsiException {
        val data = ByteArray(18)
        val cdb = byteArrayOf(0x03, 0, 0, 0, 18, 0)
        val status = try {
            execute(cdb, data, 0, data.size, directionIn = true, exact = false)
        } catch (e: IOException) {
            return ScsiException("$what a échoué (${e.message})")
        }
        if (status != 0) return ScsiException("$what a échoué")
        val key = data[2].toInt() and 0x0F
        val asc = data[12].toInt() and 0xFF
        val ascq = data[13].toInt() and 0xFF
        return ScsiException("$what a échoué (sense $key/$asc/$ascq)", key, asc, ascq)
    }

    /**
     * Une commande complète : CBW, données éventuelles, CSW. Renvoie le statut
     * du CSW (0 = réussi, 1 = échec -> REQUEST SENSE). `exact` : la phase de
     * données doit transférer exactement `length` octets (lecture/écriture de
     * blocs) ; sinon un transfert plus court est accepté (INQUIRY...).
     */
    private fun execute(
        cdb: ByteArray,
        data: ByteArray?,
        offset: Int,
        length: Int,
        directionIn: Boolean,
        exact: Boolean,
    ): Int {
        val currentTag = tag++
        val cbw = ByteBuffer.allocate(CBW_SIZE).order(ByteOrder.LITTLE_ENDIAN)
        cbw.putInt(CBW_SIGNATURE)
        cbw.putInt(currentTag)
        cbw.putInt(length)
        cbw.put(if (directionIn) 0x80.toByte() else 0.toByte())
        cbw.put(lun.toByte())
        cbw.put(cdb.size.toByte())
        cbw.put(cdb)
        val cbwBytes = cbw.array()
        if (transport.bulkOut(cbwBytes, 0, CBW_SIZE) != CBW_SIZE) {
            transport.resetRecovery()
            throw IOException("Le lecteur de carte ne répond plus (envoi de commande)")
        }

        if (data != null && length > 0) {
            var done = 0
            while (done < length) {
                val chunk = minOf(MAX_BULK_CHUNK, length - done)
                val n = if (directionIn) {
                    transport.bulkIn(data, offset + done, chunk)
                } else {
                    transport.bulkOut(data, offset + done, chunk)
                }
                if (n < 0) {
                    transport.resetRecovery()
                    throw IOException("Le lecteur de carte ne répond plus (transfert de données)")
                }
                done += n
                if (n < chunk) {
                    if (exact) {
                        transport.resetRecovery()
                        throw IOException("Transfert incomplet ($done sur $length octets)")
                    }
                    break
                }
            }
        }

        val csw = ByteArray(CSW_SIZE)
        var n = transport.bulkIn(csw, 0, CSW_SIZE)
        if (n < 0) n = transport.bulkIn(csw, 0, CSW_SIZE) // un second essai, comme le prévoit la norme
        if (n != CSW_SIZE) {
            transport.resetRecovery()
            throw IOException("Le lecteur de carte ne répond plus (état de commande)")
        }
        val reply = ByteBuffer.wrap(csw).order(ByteOrder.LITTLE_ENDIAN)
        val signature = reply.int
        val replyTag = reply.int
        reply.int // résidu, non utilisé
        val status = reply.get().toInt() and 0xFF
        if (signature != CSW_SIGNATURE || replyTag != currentTag || status > 1) {
            transport.resetRecovery()
            throw IOException("Réponse inattendue du lecteur de carte (statut $status)")
        }
        return status
    }

    companion object {
        const val CBW_SIZE = 31
        const val CSW_SIZE = 13
        const val CBW_SIGNATURE = 0x43425355
        const val CSW_SIGNATURE = 0x53425355

        /** Octets par commande READ/WRITE(10). */
        const val MAX_BYTES_PER_COMMAND = 512 * 1024

        /** Octets par appel au tuyau USB (multiple de la taille de paquet). */
        const val MAX_BULK_CHUNK = 64 * 1024

        private const val READY_ATTEMPTS = 20
        private const val READY_DELAY_MS = 250L
    }
}
