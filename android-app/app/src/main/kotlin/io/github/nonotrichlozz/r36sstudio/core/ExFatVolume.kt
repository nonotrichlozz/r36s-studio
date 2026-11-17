// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import java.io.IOException

/**
 * Lecteur exFAT, lecture seule. Port de `imaging/exfat_reader.py`, vérifié sur
 * de vraies cartes : il **lève** `FsException` à la moindre incohérence plutôt
 * que d'afficher un dossier amputé.
 */
class ExFatVolume(private val reader: VolumeReader) : FsVolume() {
    override val fsName: String = "exFAT"
    override var label: String = ""
        private set

    internal val clusterSize: Int
    internal val clusterCount: Long
    internal val fatOffset: Long
    internal val heapOffset: Long
    internal val rootCluster: Long

    // Fichiers système du volume, repérés dans la racine (utiles à l'écriture).
    internal var bitmapCluster: Long = 0
        private set
    internal var bitmapLength: Long = 0
        private set
    internal var upcaseCluster: Long = 0
        private set
    internal var upcaseLength: Long = 0
        private set

    init {
        val boot = reader.read(0, 512)
        if (String(boot, 3, 8, Charsets.ISO_8859_1) != "EXFAT   ") throw FsException("la partition n'est pas en exFAT")
        val sectorShift = boot[108].toInt() and 0xFF
        val clusterShift = boot[109].toInt() and 0xFF
        if (sectorShift !in 9..12 || sectorShift + clusterShift > 25) throw FsException("taille de cluster invraisemblable")
        val bytesPerSector = 1L shl sectorShift
        clusterSize = (bytesPerSector shl clusterShift).toInt()
        fatOffset = u32(boot, 80) * bytesPerSector
        heapOffset = u32(boot, 88) * bytesPerSector
        clusterCount = u32(boot, 92)
        rootCluster = u32(boot, 96)
        if (clusterCount <= 0 || rootCluster < 2 || rootCluster >= clusterCount + 2) throw FsException("racine introuvable")
        if (heapOffset + clusterCount * clusterSize > reader.sizeBytes) throw FsException("volume plus grand que la partition")
        try {
            for (record in rawEntries(rootCluster, contiguous = false, size = null)) {
                when (record[0].toInt() and 0xFF) {
                    0x83 -> if (label.isEmpty()) {
                        val chars = minOf(record[1].toInt() and 0xFF, 11)
                        label = String(record, 2, chars * 2, Charsets.UTF_16LE)
                    }
                    0x81 -> if (bitmapCluster == 0L) {
                        bitmapCluster = u32(record, 20)
                        bitmapLength = u64(record, 24)
                    }
                    0x82 -> if (upcaseCluster == 0L) {
                        upcaseCluster = u32(record, 20)
                        upcaseLength = u64(record, 24)
                    }
                }
            }
        } catch (e: IOException) {
            // Une étiquette illisible ne doit pas empêcher d'ouvrir la partition.
        }
    }

    override fun listRoot(): List<FsEntry> = entries(rootCluster, contiguous = false, size = null)

    override fun list(dir: FsEntry): List<FsEntry> {
        if (!dir.isDirectory) throw FsException("ce n'est pas un dossier")
        if (dir.dataLength == 0L) return emptyList()
        return entries(dir.cluster, dir.contiguous, dir.dataLength)
    }

    // --- ce que l'écrivain a besoin de connaître (lecture seule ici) ------------

    /** Un dossier : premier cluster, contigu ou non, taille connue (`null` pour la racine). */
    internal class DirRef(val cluster: Long, val contiguous: Boolean, val dataLength: Long?)

    internal val rootRef: DirRef get() = DirRef(rootCluster, false, null)

    internal fun refOf(entry: FsEntry): DirRef = DirRef(entry.cluster, entry.contiguous, entry.dataLength)

    internal fun dirClusterList(ref: DirRef): List<Long> =
        if (ref.dataLength == null) chainUntilEnd(ref.cluster) else clusters(ref.cluster, ref.contiguous, ref.dataLength)

    internal fun readDirBytes(ref: DirRef): ByteArray {
        val list = dirClusterList(ref)
        return readClusters(list, ref.dataLength ?: (list.size.toLong() * clusterSize))
    }

    /** Position d'un cluster dans la partition, en octets. */
    internal fun clusterOffset(cluster: Long): Long = heapOffset + (cluster - 2) * clusterSize

    /** Clusters d'un fichier système (bitmap, table des majuscules) : chaîne FAT, sinon clusters contigus. */
    internal fun systemFileClusters(first: Long, length: Long): List<Long> =
        try {
            clusters(first, false, length)
        } catch (e: FsException) {
            clusters(first, true, length)
        }

    internal fun readBitmap(): ByteArray {
        if (bitmapCluster < 2 || bitmapLength <= 0) throw FsException("table d'allocation introuvable")
        if (bitmapLength * 8 < clusterCount) throw FsException("table d'allocation trop courte")
        if (bitmapLength > MAX_DIR_BYTES) throw FsException("table d'allocation démesurée")
        return readClusters(systemFileClusters(bitmapCluster, bitmapLength), bitmapLength)
    }

    /** Table des majuscules du volume (nécessaire au calcul du hachage des noms), `null` si illisible. */
    internal fun readUpcase(): CharArray? {
        if (upcaseCluster < 2 || upcaseLength <= 0 || upcaseLength > 1024 * 1024) return null
        val raw = try {
            readClusters(systemFileClusters(upcaseCluster, upcaseLength), upcaseLength)
        } catch (e: IOException) {
            return null
        }
        val table = CharArray(65536) { it.toChar() }
        var index = 0
        var p = 0
        while (p + 1 < raw.size) {
            val v = (raw[p].toInt() and 0xFF) or ((raw[p + 1].toInt() and 0xFF) shl 8)
            p += 2
            if (v == 0xFFFF) {
                if (p + 1 >= raw.size) break
                index += (raw[p].toInt() and 0xFF) or ((raw[p + 1].toInt() and 0xFF) shl 8)
                p += 2
            } else {
                if (index >= 65536) break
                table[index++] = v.toChar()
            }
        }
        return table
    }

    /** Liste des clusters d'un fichier (contigus ou en chaîne FAT). */
    internal fun clustersOf(entry: FsEntry): List<Long> = clusters(entry.cluster, entry.contiguous, entry.sizeBytes)

    /** Octets d'un fichier, dans l'ordre, par morceaux d'au plus `chunk` octets. */
    internal fun forEachFileChunk(entry: FsEntry, chunk: Int, consumer: (ByteArray) -> Unit) {
        val list = clusters(entry.cluster, entry.contiguous, entry.sizeBytes)
        var remaining = entry.sizeBytes
        var i = 0
        val perChunk = maxOf(1, chunk / clusterSize)
        while (i < list.size && remaining > 0) {
            var j = i + 1
            while (j < list.size && j - i < perChunk && list[j] == list[j - 1] + 1) j++
            val n = minOf(remaining, (j - i).toLong() * clusterSize).toInt()
            consumer(reader.read(clusterOffset(list[i]), n))
            remaining -= n
            i = j
        }
    }

    // --- clusters -------------------------------------------------------------

    private fun fatEntry(cluster: Long): Long = u32(reader.read(fatOffset + cluster * 4, 4), 0)

    private fun clusters(first: Long, contiguous: Boolean, size: Long): List<Long> {
        val count = ((size + clusterSize - 1) / clusterSize).toInt()
        if (count == 0) return emptyList()
        if (first < 2 || first + (if (contiguous) count else 1) - 2 > clusterCount) throw FsException("cluster hors du volume ($first)")
        if (contiguous) return List(count) { first + it }
        val out = ArrayList<Long>(count)
        var cluster = first
        while (out.size < count) {
            if (cluster < 2 || cluster >= END_OF_CHAIN || cluster - 2 >= clusterCount) throw FsException("chaîne de clusters interrompue (cluster $cluster)")
            out.add(cluster)
            cluster = fatEntry(cluster)
        }
        return out
    }

    /** Dossier sans taille connue (la racine) : on suit la chaîne jusqu'au bout, sans jamais boucler. */
    private fun chainUntilEnd(first: Long): List<Long> {
        val out = ArrayList<Long>()
        val seen = HashSet<Long>()
        var cluster = first
        while (cluster in 2 until END_OF_CHAIN) {
            if (!seen.add(cluster) || cluster - 2 >= clusterCount) throw FsException("chaîne de clusters invalide (cluster $cluster)")
            if (out.size.toLong() * clusterSize >= MAX_DIR_BYTES) throw FsException("dossier démesuré")
            out.add(cluster)
            cluster = fatEntry(cluster)
        }
        return out
    }

    private fun readClusters(list: List<Long>, length: Long): ByteArray {
        val out = ByteArray(length.toInt())
        var written = 0
        var i = 0
        while (i < list.size && written < out.size) {
            var j = i + 1
            while (j < list.size && list[j] == list[j - 1] + 1) j++
            val n = minOf((out.size - written).toLong(), (j - i).toLong() * clusterSize).toInt()
            val chunk = reader.read(heapOffset + (list[i] - 2) * clusterSize, n)
            System.arraycopy(chunk, 0, out, written, n)
            written += n
            i = j
        }
        return out
    }

    // --- dossiers -------------------------------------------------------------

    /** Chaque entrée en service, suivie de ses secondaires pour un fichier (0x85). */
    private fun rawEntries(first: Long, contiguous: Boolean, size: Long?): List<ByteArray> {
        val list: List<Long>
        val length: Long
        if (size == null) {
            list = chainUntilEnd(first)
            length = list.size.toLong() * clusterSize
        } else {
            if (size > MAX_DIR_BYTES) throw FsException("dossier démesuré")
            list = clusters(first, contiguous, size)
            length = size
        }
        val data = readClusters(list, length)
        val out = ArrayList<ByteArray>()
        var i = 0
        while (i + 32 <= data.size) {
            val kind = data[i].toInt() and 0xFF
            if (kind == 0x00) break
            if (kind == 0x85) {
                val end = i + 32 * ((data[i + 1].toInt() and 0xFF) + 1)
                if (end > data.size) throw FsException("entrée de fichier tronquée")
                out.add(data.copyOfRange(i, end))
                i = end
                continue
            }
            if (kind and 0x80 != 0) out.add(data.copyOfRange(i, i + 32))
            i += 32
        }
        return out
    }

    private fun entries(first: Long, contiguous: Boolean, size: Long?): List<FsEntry> {
        val out = ArrayList<FsEntry>()
        for (record in rawEntries(first, contiguous, size)) {
            if ((record[0].toInt() and 0xFF) != 0x85) continue
            if (record.size < 64 || (record[32].toInt() and 0xFF) != 0xC0) throw FsException("entrée de fichier sans extension de flux")
            val nameUnits = record[32 + 3].toInt() and 0xFF
            val nameBytes = java.io.ByteArrayOutputStream()
            var k = 64
            while (k + 32 <= record.size) {
                if ((record[k].toInt() and 0xFF) == 0xC1) nameBytes.write(record, k + 2, 30)
                k += 32
            }
            val name = String(nameBytes.toByteArray(), Charsets.UTF_16LE).take(nameUnits)
            if (name.length != nameUnits || name.isEmpty()) throw FsException("nom de fichier tronqué")
            val attributes = (record[4].toInt() and 0xFF) or ((record[5].toInt() and 0xFF) shl 8)
            val isDir = attributes and 0x10 != 0
            out.add(
                FsEntry(
                    name = name,
                    isDirectory = isDir,
                    sizeBytes = u64(record, 32 + 24),
                    modifiedMillis = timestamp(u32(record, 12), record[23].toInt() and 0xFF),
                    hidden = attributes and 0x06 != 0,
                    cluster = u32(record, 32 + 20),
                    contiguous = (record[32 + 1].toInt() and 0x02) != 0,
                    dataLength = u64(record, 32 + 24),
                ),
            )
        }
        return out
    }

    private fun timestamp(stamp: Long, utcOffset: Int): Long? {
        val quarters = if (utcOffset and 0x80 != 0) (utcOffset and 0x7F).let { if (it >= 64) it - 128 else it } else null
        return Filesystems.toMillis(
            1980 + (stamp shr 25).toInt(),
            ((stamp shr 21) and 0x0F).toInt(),
            ((stamp shr 16) and 0x1F).toInt(),
            ((stamp shr 11) and 0x1F).toInt(),
            ((stamp shr 5) and 0x3F).toInt(),
            ((stamp and 0x1F) * 2).toInt(),
            quarters,
        )
    }

    private companion object {
        const val END_OF_CHAIN = 0xFFFFFFF7L
        const val MAX_DIR_BYTES = 32L * 1024 * 1024

        fun u32(b: ByteArray, o: Int): Long =
            (b[o].toLong() and 0xFF) or ((b[o + 1].toLong() and 0xFF) shl 8) or
                ((b[o + 2].toLong() and 0xFF) shl 16) or ((b[o + 3].toLong() and 0xFF) shl 24)

        fun u64(b: ByteArray, o: Int): Long = u32(b, o) or (u32(b, o + 4) shl 32)
    }
}
