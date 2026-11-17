// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import java.io.IOException
import java.nio.ByteBuffer
import java.nio.ByteOrder

/** Une partition de la carte, telle que la table la décrit. */
data class PartitionInfo(val number: Int, val startBytes: Long, val sizeBytes: Long, val tableName: String)

/** Liste des partitions (MBR, MBR étendu, GPT, ou carte sans table). Lecture seule. */
object PartitionList {

    @Throws(IOException::class)
    fun read(device: BlockDevice): List<PartitionInfo> {
        val blockSize = device.blockSize
        val deviceBytes = blockSize.toLong() * device.blockCount
        val sector0 = ByteArray(blockSize)
        device.read(0, sector0, 1)
        if (Filesystems.looksLikeFatOrExFatBootSector(sector0)) {
            return listOf(PartitionInfo(1, 0, deviceBytes, ""))
        }
        if ((sector0[510].toInt() and 0xFF) != 0x55 || (sector0[511].toInt() and 0xFF) != 0xAA) return emptyList()

        val mbr = ByteBuffer.wrap(sector0).order(ByteOrder.LITTLE_ENDIAN)
        var protective = false
        val found = ArrayList<PartitionInfo>()
        var number = 0
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
            number++
            if (type == 0x05 || type == 0x0F || type == 0x85) {
                number = logicalPartitions(device, start, number, found)
                continue
            }
            addIfInside(found, number, start * blockSize, sectors * blockSize, deviceBytes, "")
        }
        if (protective) {
            val gpt = gptPartitions(device, deviceBytes)
            if (gpt != null) return gpt
        }
        return found
    }

    /** Partitions logiques d'une partition étendue : une chaîne de secteurs EBR. */
    private fun logicalPartitions(device: BlockDevice, extendedStart: Long, firstNumber: Int, into: MutableList<PartitionInfo>): Int {
        val blockSize = device.blockSize
        val deviceBytes = blockSize.toLong() * device.blockCount
        var number = firstNumber
        var ebr = extendedStart
        var guard = 0
        // Les numéros des logiques commencent à 5, comme sous Linux.
        if (number < 5) number = 4
        while (guard++ < 32 && ebr < device.blockCount) {
            val sector = ByteArray(blockSize)
            device.read(ebr, sector, 1)
            if ((sector[510].toInt() and 0xFF) != 0x55 || (sector[511].toInt() and 0xFF) != 0xAA) break
            val buf = ByteBuffer.wrap(sector).order(ByteOrder.LITTLE_ENDIAN)
            val type = sector[446 + 4].toInt() and 0xFF
            val start = buf.getInt(446 + 8).toLong() and 0xFFFFFFFFL
            val sectors = buf.getInt(446 + 12).toLong() and 0xFFFFFFFFL
            if (type != 0 && sectors != 0L) {
                number++
                addIfInside(into, number, (ebr + start) * blockSize, sectors * blockSize, deviceBytes, "")
            }
            val nextType = sector[462 + 4].toInt() and 0xFF
            val nextStart = buf.getInt(462 + 8).toLong() and 0xFFFFFFFFL
            if (nextType == 0 || nextStart == 0L) break
            ebr = extendedStart + nextStart
        }
        return number
    }

    private fun gptPartitions(device: BlockDevice, deviceBytes: Long): List<PartitionInfo>? {
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
        val tableBlocks = ((entryCount.toLong() * entrySize + blockSize - 1) / blockSize).toInt()
        if (entriesLba + tableBlocks > device.blockCount) return null
        val table = ByteArray(tableBlocks * blockSize)
        device.read(entriesLba, table, tableBlocks)
        val entries = ByteBuffer.wrap(table).order(ByteOrder.LITTLE_ENDIAN)
        val out = ArrayList<PartitionInfo>()
        for (i in 0 until entryCount) {
            val base = i * entrySize
            if ((0 until 16).all { table[base + it].toInt() == 0 }) continue
            val first = entries.getLong(base + 32)
            val last = entries.getLong(base + 40)
            if (first < 0 || last < first) continue
            val name = String(table, base + 56, 72, Charsets.UTF_16LE).substringBefore('\u0000')
            addIfInside(out, i + 1, first * blockSize, (last - first + 1) * blockSize, deviceBytes, name)
        }
        return out
    }

    private fun addIfInside(into: MutableList<PartitionInfo>, number: Int, start: Long, size: Long, deviceBytes: Long, name: String) {
        if (start < 0 || size <= 0 || start + size > deviceBytes) return
        into.add(PartitionInfo(number, start, size, name))
    }
}
