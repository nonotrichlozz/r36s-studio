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

    /** Débloque un tuyau que le lecteur a bloqué (STALL) pour refuser une commande. */
    fun clearHalt(directionIn: Boolean)

    /** Remise en état après une erreur de protocole (reset + clear halt). */
    fun resetRecovery()
}

open class ScsiException(
    message: String,
    val senseKey: Int = -1,
    val asc: Int = -1,
    val ascq: Int = -1,
) : IOException(message)

/** La carte (ou le lecteur) refuse toute écriture : sense 7/27, « write protected ». */
class WriteProtectedException(detail: String) : ScsiException(detail, 7, 0x27, 0)

/** Le lecteur est là, mais aucune carte n'est dedans. */
class NoMediumException(attempts: Int = 1) :
    ScsiException("Aucune carte dans le lecteur (sense 2/58/0, $attempts essais)", 2, 0x3A, 0)

/**
 * Carte vue à travers un lecteur USB de stockage de masse (SCSI transparent
 * sur Bulk-Only Transport). Sans root : c'est l'appli qui parle directement
 * au lecteur, Android ne monte rien.
 */
class ScsiBlockDevice(
    private val transport: BulkTransport,
    private val lun: Int = 0,
    private val sleep: (Long) -> Unit = { Thread.sleep(it) },
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

    private var commandBytes: Int = MAX_BYTES_PER_COMMAND

    /** Vrai si l'appli a dû passer aux petites commandes pour ce lecteur (diagnostic). */
    var reducedCommands: Boolean = false
        private set

    /**
     * Ce que le lecteur annonce au repos (MODE SENSE) : `true` protégée,
     * `false` non, `null` s'il ne répond pas à la question. Diagnostic
     * seulement, appelé après un refus d'écriture.
     */
    fun reportedWriteProtect(): Boolean? {
        return try {
            val data = ByteArray(4)
            val status = execute(byteArrayOf(0x1A, 0, 0x3F, 0, 4, 0), data, 0, data.size, directionIn = true, exact = false)
            if (status != 0) {
                senseException("MODE SENSE")
                null
            } else {
                (data[2].toInt() and 0x80) != 0
            }
        } catch (e: IOException) {
            null
        }
    }

    /**
     * Passe aux petites commandes (32 Ko) : après un décrochage du lecteur,
     * l'appli reprend plus doucement, une carte occupée avale mieux de
     * petites écritures.
     */
    fun useSmallCommands() {
        commandBytes = SMALL_COMMAND_BYTES
        reducedCommands = true
    }

    /**
     * Remet le lecteur en état sans le rendre à Android (qui se remettrait
     * aussitôt à lire la carte) : remise à zéro du protocole, pause, puis
     * même accueil qu'à l'ouverture. Lève une erreur si le lecteur reste muet.
     */
    @Throws(IOException::class)
    fun revive(settleMs: Long) {
        transport.resetRecovery()
        pause(settleMs)
        init()
    }

    /** Nombre de commandes qu'il a fallu recommencer (diagnostic). */
    var retries: Int = 0
        private set

    /** INQUIRY, attente que la carte soit prête, puis lecture de sa capacité. */
    @Throws(IOException::class)
    fun init() {
        inquiry()
        val notReady = waitReady()
        if (notReady == null) {
            readCapacity()
            return
        }
        // Certains lecteurs bon marché répondent « pas prêt » indéfiniment tout
        // en donnant la capacité et les blocs : dernier essai avant d'abandonner.
        try {
            readCapacity()
        } catch (e: IOException) {
            throw notReady
        }
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

    /**
     * Attend que la carte soit prête. Renvoie `null` si elle l'est, sinon la
     * dernière raison donnée par le lecteur.
     *
     * « Pas de carte » (sense 2/3A) n'est pas cru sur parole : juste après
     * que l'appli a pris le lecteur à Android, beaucoup de lecteurs bon
     * marché l'annoncent pendant quelques secondes alors que la carte est là
     * (constaté le 2026-11-11, lecteur « USB 2.0 micro SD » + SanDisk 32 Go).
     * On leur demande de démarrer (START STOP UNIT) et on réessaie.
     */
    private fun waitReady(): ScsiException? {
        var last: ScsiException? = null
        for (attempt in 0 until READY_ATTEMPTS) {
            val status = execute(byteArrayOf(0, 0, 0, 0, 0, 0), null, 0, 0, directionIn = false, exact = true)
            if (status == 0) return null
            val sense = senseException("TEST UNIT READY")
            last = if (sense.senseKey == 2 && sense.asc == 0x3A) NoMediumException(attempt + 1) else sense
            if (sense.senseKey == 2 && attempt % 4 == 0) startUnit()
            try {
                sleep(READY_DELAY_MS)
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
                throw IOException("Interrompu")
            }
        }
        return last ?: ScsiException("La carte ne répond pas")
    }

    /** START STOP UNIT (démarrer) : au mieux, un refus est sans importance. */
    private fun startUnit() {
        val status = execute(byteArrayOf(0x1B, 0, 0, 0, 0x01, 0), null, 0, 0, directionIn = false, exact = true)
        if (status != 0) senseException("START STOP UNIT")
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
        var done = 0
        while (done < blocks) {
            val count = minOf(maxOf(1, commandBytes / blockSize), blocks - done)
            val current = lba + done
            val cdb = ByteArray(10)
            cdb[0] = if (write) 0x2A else 0x28
            cdb[2] = (current ushr 24).toByte()
            cdb[3] = (current ushr 16).toByte()
            cdb[4] = (current ushr 8).toByte()
            cdb[5] = current.toByte()
            cdb[7] = (count ushr 8).toByte()
            cdb[8] = count.toByte()
            try {
                executeBlocks(cdb, buffer, done * blockSize, count * blockSize, write, current)
            } catch (e: WriteProtectedException) {
                // Carte neuve refusée en écriture (2026-11-11) : avant de croire
                // le lecteur, on réessaie par petits morceaux -- certains
                // lecteurs bon marché répondent n'importe quoi à une grosse
                // commande. Si le refus persiste, il est vrai.
                if (commandBytes <= SMALL_COMMAND_BYTES) throw e
                commandBytes = SMALL_COMMAND_BYTES
                reducedCommands = true
                continue
            }
            done += count
        }
    }

    /**
     * Une commande de lecture/écriture de blocs, réessayée après une remise
     * en état du lecteur : un lecteur bon marché rate parfois un transfert
     * sans raison durable (constaté le 2026-11-11). Relire ou réécrire les
     * mêmes blocs est sans effet de bord.
     */
    private fun executeBlocks(cdb: ByteArray, buffer: ByteArray, offset: Int, length: Int, write: Boolean, lba: Long) {
        val what = if (write) "WRITE(10) bloc $lba" else "READ(10) bloc $lba"
        var last: IOException? = null
        for (attempt in 0 until TRANSFER_ATTEMPTS) {
            if (attempt > 0) {
                transport.resetRecovery()
                pause(RETRY_DELAY_MS)
                retries++
            }
            try {
                val status = execute(cdb, buffer, offset, length, directionIn = !write, exact = true)
                if (status == 0) return
                val sense = senseException(what)
                // « Le lecteur vient d'être réinitialisé » (unit attention) ou « pas encore prêt » : on réessaie.
                if (sense.senseKey == 7) throw WriteProtectedException(sense.message ?: what)
                if (sense.senseKey != 6 && sense.senseKey != 2) throw sense
                last = sense
            } catch (e: ScsiException) {
                // Raison illisible (REQUEST SENSE sans réponse) : c'est le lecteur
                // qui a décroché, pas la carte qui refuse (2026-11-13, R36S
                // Arch R réinstallée depuis le téléphone). On le remet en état
                // et on recommence, comme pour un transfert raté.
                if (e.senseKey >= 0) throw e
                last = e
            } catch (e: IOException) {
                last = IOException("$what : ${e.message}")
            }
        }
        throw last ?: IOException("$what a échoué")
    }

    private fun pause(milliseconds: Long) {
        try {
            sleep(milliseconds)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
            throw IOException("Interrompu")
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
            throw IOException("Le lecteur de carte ne répond plus (envoi de la commande ${opName(cdb)})")
        }

        // Un lecteur qui refuse une commande avec données bloque le tuyau au
        // lieu d'envoyer les données : on le débloque et on lit quand même
        // l'état de la commande (qui dira « échec » -> REQUEST SENSE).
        var stalled = false
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
                    transport.clearHalt(directionIn)
                    stalled = true
                    break
                }
                done += n
                if (n < chunk) {
                    if (exact) {
                        transport.resetRecovery()
                        throw IOException("Transfert incomplet ($done sur $length octets, commande ${opName(cdb)})")
                    }
                    break
                }
            }
        }

        val csw = ByteArray(CSW_SIZE)
        var n = transport.bulkIn(csw, 0, CSW_SIZE)
        if (n < 0) {
            // Un second essai après déblocage, comme le prévoit la norme.
            transport.clearHalt(true)
            n = transport.bulkIn(csw, 0, CSW_SIZE)
        }
        if (n != CSW_SIZE) {
            transport.resetRecovery()
            throw IOException("Le lecteur de carte ne répond plus (état de la commande ${opName(cdb)})")
        }
        val reply = ByteBuffer.wrap(csw).order(ByteOrder.LITTLE_ENDIAN)
        val signature = reply.int
        val replyTag = reply.int
        reply.int // résidu, non utilisé
        val status = reply.get().toInt() and 0xFF
        if (signature != CSW_SIGNATURE || replyTag != currentTag || status > 1) {
            transport.resetRecovery()
            throw IOException("Réponse inattendue du lecteur de carte (statut $status, commande ${opName(cdb)})")
        }
        if (stalled && status == 0) {
            transport.resetRecovery()
            throw IOException("Le lecteur de carte ne répond plus (données de la commande ${opName(cdb)})")
        }
        return status
    }

    private fun opName(cdb: ByteArray): String = String.format("0x%02X", cdb[0].toInt() and 0xFF)

    companion object {
        const val CBW_SIZE = 31
        const val CSW_SIZE = 13
        const val CBW_SIGNATURE = 0x43425355
        const val CSW_SIGNATURE = 0x53425355

        /** Octets par commande READ/WRITE(10). */
        const val MAX_BYTES_PER_COMMAND = 512 * 1024

        /** Repli pour les lecteurs qui refusent les grosses commandes. */
        const val SMALL_COMMAND_BYTES = 32 * 1024

        /** Octets par appel au tuyau USB (multiple de la taille de paquet). */
        const val MAX_BULK_CHUNK = 64 * 1024

        // 40 x 250 ms : dix secondes de patience avant de déclarer la carte absente.
        private const val READY_ATTEMPTS = 40
        private const val READY_DELAY_MS = 250L
        private const val TRANSFER_ATTEMPTS = 4
        private const val RETRY_DELAY_MS = 300L
    }
}
