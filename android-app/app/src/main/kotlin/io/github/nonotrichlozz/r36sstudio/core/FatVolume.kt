// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import java.io.IOException

/** Lecteur FAT12, FAT16 et FAT32 (noms longs compris), lecture seule. */
class FatVolume(private val reader: VolumeReader) : FsVolume() {
    private val bytesPerSector: Int
    private val clusterSize: Int
    private val fatOffset: Long
    private val rootDirOffset: Long // FAT12/16 seulement
    private val rootDirBytes: Int // FAT12/16 seulement
    private val dataOffset: Long
    private val clusterCount: Long
    private val rootCluster: Long // FAT32 seulement
    private val kind: Int // 12, 16 ou 32

    override val fsName: String
    override var label: String = ""
        private set

    init {
        val boot = reader.read(0, 512)
        if (!isFatBootSector(boot)) throw FsException("la partition n'est pas en FAT")
        bytesPerSector = u16(boot, 11)
        val sectorsPerCluster = boot[13].toInt() and 0xFF
        val reserved = u16(boot, 14)
        val fats = boot[16].toInt() and 0xFF
        val rootEntries = u16(boot, 17)
        val total = if (u16(boot, 19) != 0) u16(boot, 19).toLong() else u32(boot, 32)
        val fatSectors = if (u16(boot, 22) != 0) u16(boot, 22).toLong() else u32(boot, 36)
        clusterSize = bytesPerSector * sectorsPerCluster
        val rootSectors = ((rootEntries * 32L) + bytesPerSector - 1) / bytesPerSector
        val dataSectors = total - reserved - fats * fatSectors - rootSectors
        if (dataSectors <= 0) throw FsException("volume FAT incohérent")
        clusterCount = dataSectors / sectorsPerCluster
        kind = when {
            clusterCount < 4085 -> 12
            clusterCount < 65525 -> 16
            else -> 32
        }
        fsName = "FAT$kind"
        fatOffset = reserved.toLong() * bytesPerSector
        rootDirOffset = fatOffset + fats * fatSectors * bytesPerSector
        rootDirBytes = (rootSectors * bytesPerSector).toInt()
        dataOffset = rootDirOffset + rootDirBytes
        rootCluster = if (kind == 32) u32(boot, 44) else 0
        if (kind == 32 && (rootCluster < 2 || rootCluster >= clusterCount + 2)) throw FsException("racine FAT32 introuvable")
        if (dataOffset + clusterCount * clusterSize > reader.sizeBytes) throw FsException("volume plus grand que la partition")
        val bootLabel = String(boot, if (kind == 32) 71 else 43, 11, Charsets.ISO_8859_1).trim()
        label = if (bootLabel == "NO NAME") "" else bootLabel
        try {
            listRoot() // l'étiquette du dossier racine, quand il y en a une, prime sur celle du secteur de démarrage
        } catch (e: IOException) {
            // Une racine illisible sera signalée à l'ouverture du dossier.
        }
    }

    override fun listRoot(): List<FsEntry> {
        val data = if (kind == 32) readChain(rootCluster) else reader.read(rootDirOffset, rootDirBytes)
        return parse(data)
    }

    override fun list(dir: FsEntry): List<FsEntry> {
        if (!dir.isDirectory) throw FsException("ce n'est pas un dossier")
        if (dir.cluster < 2) return listRoot() // « .. » ou cluster 0 : la racine
        return parse(readChain(dir.cluster))
    }

    // --- table d'allocation ---------------------------------------------------

    private fun fatEntry(cluster: Long): Long = when (kind) {
        12 -> {
            val raw = reader.read(fatOffset + cluster + cluster / 2, 2)
            val v = (raw[0].toInt() and 0xFF) or ((raw[1].toInt() and 0xFF) shl 8)
            (if (cluster % 2 == 0L) v and 0xFFF else v shr 4).toLong()
        }
        16 -> u16(reader.read(fatOffset + cluster * 2, 2), 0).toLong()
        else -> u32(reader.read(fatOffset + cluster * 4, 4), 0) and 0x0FFFFFFFL
    }

    private fun isEnd(entry: Long): Boolean = when (kind) {
        12 -> entry >= 0xFF8
        16 -> entry >= 0xFFF8
        else -> entry >= 0x0FFFFFF8
    }

    private fun readChain(first: Long): ByteArray {
        val clusters = ArrayList<Long>()
        val seen = HashSet<Long>()
        var cluster = first
        while (true) {
            if (cluster < 2 || cluster >= clusterCount + 2) throw FsException("chaîne de clusters invalide (cluster $cluster)")
            if (!seen.add(cluster)) throw FsException("chaîne de clusters qui boucle (cluster $cluster)")
            if (clusters.size.toLong() * clusterSize >= MAX_DIR_BYTES) throw FsException("dossier démesuré")
            clusters.add(cluster)
            val next = fatEntry(cluster)
            if (isEnd(next)) break
            cluster = next
        }
        val out = ByteArray(clusters.size * clusterSize)
        var written = 0
        var i = 0
        while (i < clusters.size) {
            var j = i + 1
            while (j < clusters.size && clusters[j] == clusters[j - 1] + 1) j++
            val n = (j - i) * clusterSize
            val chunk = reader.read(dataOffset + (clusters[i] - 2) * clusterSize, n)
            System.arraycopy(chunk, 0, out, written, n)
            written += n
            i = j
        }
        return out
    }

    // --- entrées --------------------------------------------------------------

    private fun parse(data: ByteArray): List<FsEntry> {
        val out = ArrayList<FsEntry>()
        var lfn = arrayOfNulls<CharArray>(21)
        var lfnCount = 0
        var lfnChecksum = -1
        var i = 0
        while (i + 32 <= data.size) {
            val first = data[i].toInt() and 0xFF
            if (first == 0x00) break
            val attr = data[i + 11].toInt() and 0xFF
            if (first == 0xE5) {
                lfnCount = 0
                i += 32
                continue
            }
            if (attr and 0x3F == 0x0F) {
                val seq = first and 0x1F
                if (first and 0x40 != 0) {
                    lfn = arrayOfNulls(21)
                    lfnCount = seq
                    lfnChecksum = data[i + 13].toInt() and 0xFF
                }
                if (seq in 1..20) {
                    val chars = CharArray(13)
                    var c = 0
                    for (offset in intArrayOf(1, 3, 5, 7, 9, 14, 16, 18, 20, 22, 24, 28, 30)) {
                        chars[c++] = ((data[i + offset].toInt() and 0xFF) or ((data[i + offset + 1].toInt() and 0xFF) shl 8)).toChar()
                    }
                    lfn[seq - 1] = chars
                }
                i += 32
                continue
            }
            if (attr and 0x08 != 0) {
                // Étiquette du volume.
                val name = String(data, i, 11, Charsets.ISO_8859_1).trim()
                if (name.isNotEmpty()) label = name
                lfnCount = 0
                i += 32
                continue
            }
            val shortName = shortName(data, i)
            val isDotEntry = shortName == "." || shortName == ".."
            if (!isDotEntry) {
                var name = shortName
                if (lfnCount in 1..20 && lfnChecksum == checksum(data, i) && (0 until lfnCount).all { lfn[it] != null }) {
                    val sb = StringBuilder()
                    for (n in 0 until lfnCount) sb.append(lfn[n]!!)
                    val end = sb.indexOfFirst { it == '\u0000' || it == '￿' }
                    name = if (end >= 0) sb.substring(0, end) else sb.toString()
                }
                val cluster = (u16(data, i + 20).toLong() shl 16) or u16(data, i + 26).toLong()
                out.add(
                    FsEntry(
                        name = name,
                        isDirectory = attr and 0x10 != 0,
                        sizeBytes = u32(data, i + 28),
                        modifiedMillis = modified(u16(data, i + 24), u16(data, i + 22)),
                        hidden = attr and 0x06 != 0,
                        cluster = if (kind == 32) cluster else u16(data, i + 26).toLong(),
                        contiguous = false,
                        dataLength = u32(data, i + 28),
                    ),
                )
            }
            lfnCount = 0
            i += 32
        }
        return out
    }

    private fun shortName(data: ByteArray, i: Int): String {
        val raw = data.copyOfRange(i, i + 11)
        if ((raw[0].toInt() and 0xFF) == 0x05) raw[0] = 0xE5.toByte()
        val flags = data[i + 12].toInt() and 0xFF
        var base = String(raw, 0, 8, Charsets.ISO_8859_1).trimEnd()
        var ext = String(raw, 8, 3, Charsets.ISO_8859_1).trimEnd()
        if (flags and 0x08 != 0) base = base.lowercase()
        if (flags and 0x10 != 0) ext = ext.lowercase()
        return if (ext.isEmpty()) base else "$base.$ext"
    }

    private fun checksum(data: ByteArray, i: Int): Int {
        var sum = 0
        for (k in 0 until 11) sum = (((sum and 1) shl 7) + (sum shr 1) + (data[i + k].toInt() and 0xFF)) and 0xFF
        return sum
    }

    private fun modified(date: Int, time: Int): Long? {
        if (date == 0) return null
        return Filesystems.toMillis(1980 + (date shr 9), (date shr 5) and 0x0F, date and 0x1F, time shr 11, (time shr 5) and 0x3F, (time and 0x1F) * 2)
    }

    companion object {
        private const val MAX_DIR_BYTES = 32L * 1024 * 1024

        fun u16(b: ByteArray, o: Int): Int = (b[o].toInt() and 0xFF) or ((b[o + 1].toInt() and 0xFF) shl 8)

        fun u32(b: ByteArray, o: Int): Long =
            (b[o].toLong() and 0xFF) or ((b[o + 1].toLong() and 0xFF) shl 8) or
                ((b[o + 2].toLong() and 0xFF) shl 16) or ((b[o + 3].toLong() and 0xFF) shl 24)

        /** Secteur de démarrage FAT plausible (jamais de lecture au-delà des 512 premiers octets). */
        fun isFatBootSector(boot: ByteArray): Boolean {
            if (boot.size < 512) return false
            if ((boot[510].toInt() and 0xFF) != 0x55 || (boot[511].toInt() and 0xFF) != 0xAA) return false
            val jump = boot[0].toInt() and 0xFF
            if (jump != 0xEB && jump != 0xE9) return false
            val bytesPerSector = u16(boot, 11)
            val sectorsPerCluster = boot[13].toInt() and 0xFF
            val fats = boot[16].toInt() and 0xFF
            if (bytesPerSector !in intArrayOf(512, 1024, 2048, 4096)) return false
            if (sectorsPerCluster == 0 || sectorsPerCluster and (sectorsPerCluster - 1) != 0) return false
            if (fats !in 1..2 || u16(boot, 14) == 0) return false
            val tag16 = String(boot, 54, 5, Charsets.ISO_8859_1)
            val tag32 = String(boot, 82, 5, Charsets.ISO_8859_1)
            return tag16 == "FAT12" || tag16 == "FAT16" || tag32 == "FAT32"
        }
    }
}
