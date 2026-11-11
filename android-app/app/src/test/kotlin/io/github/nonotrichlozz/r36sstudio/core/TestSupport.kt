// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Carte en mémoire : aucun matériel réel n'est jamais touché par les tests. */
open class MemoryBlockDevice(val data: ByteArray, override val blockSize: Int = 512) : BlockDevice {
    override val blockCount: Long get() = (data.size / blockSize).toLong()
    var flushes = 0

    override fun read(lba: Long, buffer: ByteArray, blocks: Int) {
        System.arraycopy(data, (lba * blockSize).toInt(), buffer, 0, blocks * blockSize)
    }

    override fun write(lba: Long, buffer: ByteArray, blocks: Int) {
        System.arraycopy(buffer, 0, data, (lba * blockSize).toInt(), blocks * blockSize)
    }

    override fun flush() {
        flushes++
    }
}

class RecordingListener : ProgressListener {
    val phases = mutableListOf<Phase>()
    var lastDone = -1L
    var lastTotal = -1L

    override fun onPhase(phase: Phase) {
        phases.add(phase)
    }

    override fun onProgress(done: Long, total: Long, bytesPerSecond: Long) {
        lastDone = done
        lastTotal = total
    }
}

fun patternBytes(size: Int, seed: Int = 7): ByteArray {
    val out = ByteArray(size)
    var x = seed
    for (i in out.indices) {
        x = x * 1103515245 + 12345
        out[i] = (x ushr 16).toByte()
    }
    return out
}

/** Faux lecteur de carte USB : répond au protocole Bulk-Only/SCSI sur un disque en mémoire. */
class FakeUsbReader(val disk: ByteArray, val blockSize: Int = 512) : BulkTransport {
    var mediumPresent = true

    /** Nombre de TEST UNIT READY qui répondent « pas de carte » avant que la carte apparaisse. */
    var noMediumCount = 0

    /** Lecteur qui répond toujours « pas prêt » mais lit et écrit quand même. */
    var neverReady = false
    var unitAttentionCount = 0
    var resets = 0
    val commands = mutableListOf<Int>()

    private var pendingIn: ByteArray = ByteArray(0)
    private var pendingInPos = 0
    private var csw: ByteArray? = null
    private var writeOffset = -1
    private var writeRemaining = 0
    private var writeTag = 0
    private var sense = byteArrayOf(0, 0, 0)
    private var stalledIn = false
    var clearHalts = 0

    override fun bulkOut(data: ByteArray, offset: Int, length: Int): Int {
        if (writeRemaining > 0) {
            System.arraycopy(data, offset, disk, writeOffset, length)
            writeOffset += length
            writeRemaining -= length
            if (writeRemaining == 0) csw = makeCsw(writeTag, 0)
            return length
        }
        require(length == ScsiBlockDevice.CBW_SIZE) { "CBW attendu" }
        val cbw = ByteBuffer.wrap(data, offset, length).order(ByteOrder.LITTLE_ENDIAN)
        require(cbw.int == ScsiBlockDevice.CBW_SIGNATURE)
        val tag = cbw.int
        cbw.int // longueur
        cbw.get() // sens
        cbw.get() // lun
        val cdbLength = cbw.get().toInt()
        val cdb = ByteArray(cdbLength)
        cbw.get(cdb)
        val op = cdb[0].toInt() and 0xFF
        commands.add(op)
        pendingIn = ByteArray(0)
        pendingInPos = 0
        when (op) {
            0x12 -> {
                val reply = ByteArray(36)
                reply[1] = 0x80.toByte()
                "Generic ".toByteArray(Charsets.US_ASCII).copyInto(reply, 8)
                "Card Reader     ".toByteArray(Charsets.US_ASCII).copyInto(reply, 16)
                pendingIn = reply
                csw = makeCsw(tag, 0)
            }
            0x00 -> {
                if (!mediumPresent || neverReady) {
                    sense = byteArrayOf(2, 0x3A, 0)
                    csw = makeCsw(tag, 1)
                } else if (noMediumCount > 0) {
                    noMediumCount--
                    sense = byteArrayOf(2, 0x3A, 0)
                    csw = makeCsw(tag, 1)
                } else if (unitAttentionCount > 0) {
                    unitAttentionCount--
                    sense = byteArrayOf(6, 0x28, 0)
                    csw = makeCsw(tag, 1)
                } else {
                    csw = makeCsw(tag, 0)
                }
            }
            0x03 -> {
                val reply = ByteArray(18)
                reply[0] = 0x70
                reply[2] = sense[0]
                reply[12] = sense[1]
                reply[13] = sense[2]
                pendingIn = reply
                csw = makeCsw(tag, 0)
            }
            0x1B -> csw = makeCsw(tag, 0)
            0x25 -> if (!mediumPresent) {
                // Comme un vrai lecteur : pas de données, tuyau bloqué, puis état « échec ».
                sense = byteArrayOf(2, 0x3A, 0)
                stalledIn = true
                csw = makeCsw(tag, 1)
            } else {
                val reply = ByteBuffer.allocate(8).order(ByteOrder.BIG_ENDIAN)
                reply.putInt(disk.size / blockSize - 1)
                reply.putInt(blockSize)
                pendingIn = reply.array()
                csw = makeCsw(tag, 0)
            }
            0x28, 0x2A -> {
                val address = ByteBuffer.wrap(cdb, 2, 4).order(ByteOrder.BIG_ENDIAN).int
                val count = ((cdb[7].toInt() and 0xFF) shl 8) or (cdb[8].toInt() and 0xFF)
                if (op == 0x28) {
                    pendingIn = disk.copyOfRange(address * blockSize, (address + count) * blockSize)
                    csw = makeCsw(tag, 0)
                } else {
                    writeOffset = address * blockSize
                    writeRemaining = count * blockSize
                    writeTag = tag
                    csw = null
                }
            }
            0x35 -> {
                sense = byteArrayOf(5, 0x20, 0)
                csw = makeCsw(tag, 1)
            }
            else -> {
                sense = byteArrayOf(5, 0x20, 0)
                csw = makeCsw(tag, 1)
            }
        }
        return length
    }

    override fun bulkIn(data: ByteArray, offset: Int, length: Int): Int {
        if (stalledIn) return -1
        val remaining = pendingIn.size - pendingInPos
        if (remaining > 0) {
            val n = minOf(length, remaining)
            System.arraycopy(pendingIn, pendingInPos, data, offset, n)
            pendingInPos += n
            return n
        }
        val reply = csw ?: return -1
        csw = null
        System.arraycopy(reply, 0, data, offset, reply.size)
        return reply.size
    }

    override fun clearHalt(directionIn: Boolean) {
        clearHalts++
        if (directionIn) stalledIn = false
    }

    override fun resetRecovery() {
        resets++
    }

    private fun makeCsw(tag: Int, status: Int): ByteArray {
        val out = ByteBuffer.allocate(ScsiBlockDevice.CSW_SIZE).order(ByteOrder.LITTLE_ENDIAN)
        out.putInt(ScsiBlockDevice.CSW_SIGNATURE)
        out.putInt(tag)
        out.putInt(0)
        out.put(status.toByte())
        return out.array()
    }
}
