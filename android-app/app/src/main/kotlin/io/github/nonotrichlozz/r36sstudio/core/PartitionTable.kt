// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Résultat de la lecture de la table de partitions : fin de la zone utilisée. */
data class UsedArea(val endBytes: Long, val gpt: Boolean, val partitions: Int)

/**
 * « Sauvegarde intelligente » : ne pas copier 128 Go quand la dernière
 * partition s'arrête à 8 Go. Lecture seule.
 */
object PartitionTable {

    /** `null` si aucune table lisible : l'appelant sauvegarde alors toute la carte. */
    @Throws(IOException::class)
    fun usedArea(device: BlockDevice): UsedArea? {
        val blockSize = device.blockSize
        val sector0 = ByteArray(blockSize)
        device.read(0, sector0, 1)
        if ((sector0[510].toInt() and 0xFF) != 0x55 || (sector0[511].toInt() and 0xFF) != 0xAA) return null

        val mbr = ByteBuffer.wrap(sector0).order(ByteOrder.LITTLE_ENDIAN)
        var protective = false
        var maxEnd = 0L
        var count = 0
        for (i in 0 until 4) {
            val base = 446 + i * 16
            val type = sector0[base + 4].toInt() and 0xFF
            val start = mbr.getInt(base + 8).toLong() and 0xFFFFFFFFL
            val sectors = mbr.getInt(base + 12).toLong() and 0xFFFFFFFFL
            if (type == 0 || sectors == 0L) continue
            if (type == 0xEE) {
                protective = true
                continue
            }
            count++
            maxEnd = maxOf(maxEnd, start + sectors)
        }

        if (protective) {
            val gpt = gptUsedArea(device)
            if (gpt != null) return gpt
        }
        if (count == 0 || maxEnd <= 0 || maxEnd > device.blockCount) return null
        return UsedArea(maxEnd * blockSize, gpt = false, partitions = count)
    }

    private fun gptUsedArea(device: BlockDevice): UsedArea? {
        val blockSize = device.blockSize
        val headerBytes = ByteArray(blockSize)
        device.read(1, headerBytes, 1)
        if (String(headerBytes, 0, 8, Charsets.US_ASCII) != "EFI PART") return null
        val header = ByteBuffer.wrap(headerBytes).order(ByteOrder.LITTLE_ENDIAN)
        val entriesLba = header.getLong(72)
        val entryCount = header.getInt(80)
        val entrySize = header.getInt(84)
        if (entryCount <= 0 || entryCount > 1024 || entrySize < 128 || entrySize > 4096) return null
        if (entriesLba < 2 || entriesLba >= device.blockCount) return null

        val tableBytes = entryCount.toLong() * entrySize
        val tableBlocks = ((tableBytes + blockSize - 1) / blockSize).toInt()
        if (entriesLba + tableBlocks > device.blockCount) return null
        val table = ByteArray(tableBlocks * blockSize)
        device.read(entriesLba, table, tableBlocks)
        val entries = ByteBuffer.wrap(table).order(ByteOrder.LITTLE_ENDIAN)

        var maxLast = 0L
        var count = 0
        for (i in 0 until entryCount) {
            val base = i * entrySize
            var empty = true
            for (j in 0 until 16) {
                if (table[base + j].toInt() != 0) {
                    empty = false
                    break
                }
            }
            if (empty) continue
            val last = entries.getLong(base + 40)
            if (last <= 0 || last >= device.blockCount) return null
            count++
            maxLast = maxOf(maxLast, last)
        }
        if (count == 0) return null
        return UsedArea((maxLast + 1) * blockSize, gpt = true, partitions = count)
    }
}
