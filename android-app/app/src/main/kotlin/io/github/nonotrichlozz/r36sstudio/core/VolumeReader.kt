// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import java.io.IOException

/**
 * Lecture d'octets quelconques dans une partition (début `startBytes` sur la
 * carte, `sizeBytes` de long), avec un petit cache : relire à chaque fois les
 * 4 octets d'une table d'allocation coûterait une commande USB entière.
 * Lecture seule par construction : l'appareil reçu n'est jamais écrit.
 */
class VolumeReader(device: BlockDevice, val startBytes: Long, val sizeBytes: Long) {
    private val device: BlockDevice = if (device is ReadOnlyBlockDevice) device else ReadOnlyBlockDevice(device)
    private val blockSize = device.blockSize
    private val pageSize = maxOf(PAGE_BYTES, blockSize)
    private val deviceBytes = device.blockSize.toLong() * device.blockCount
    private val cache = object : LinkedHashMap<Long, ByteArray>(64, 0.75f, true) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<Long, ByteArray>?): Boolean = size > MAX_PAGES
    }

    @Synchronized
    @Throws(IOException::class)
    fun read(offset: Long, length: Int): ByteArray {
        if (offset < 0 || length < 0 || offset + length > sizeBytes) {
            throw IOException("Lecture hors de la partition (offset $offset, $length octets)")
        }
        val out = ByteArray(length)
        var done = 0
        while (done < length) {
            val absolute = startBytes + offset + done
            val pageIndex = absolute / pageSize
            val page = page(pageIndex)
            val inPage = (absolute - pageIndex * pageSize).toInt()
            if (inPage >= page.size) throw IOException("Lecture au-delà de la carte (octet $absolute)")
            val n = minOf(length - done, page.size - inPage)
            System.arraycopy(page, inPage, out, done, n)
            done += n
        }
        return out
    }

    private fun page(index: Long): ByteArray {
        cache[index]?.let { return it }
        val start = index * pageSize
        val bytes = minOf(pageSize.toLong(), deviceBytes - start)
        if (bytes <= 0) throw IOException("Lecture au-delà de la carte (octet $start)")
        val blocks = ((bytes + blockSize - 1) / blockSize).toInt()
        val buffer = ByteArray(blocks * blockSize)
        device.read(start / blockSize, buffer, blocks)
        val page = if (buffer.size.toLong() == bytes) buffer else buffer.copyOf(bytes.toInt())
        cache[index] = page
        return page
    }

    companion object {
        private const val PAGE_BYTES = 64 * 1024
        private const val MAX_PAGES = 128 // 8 Mio
    }
}
