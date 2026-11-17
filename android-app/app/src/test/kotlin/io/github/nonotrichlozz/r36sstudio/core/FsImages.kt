// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

/** Fabrique d'images FAT16 / FAT32 en mémoire (noms longs, dossiers éclatés sur plusieurs clusters). */
class FatImage(val kind: Int, volumeLabel: String = "R36S") {
    private val reserved = if (kind == 32) 32 else 1
    private val rootEntries = if (kind == 32) 0 else 512
    private val clusters = if (kind == 32) 65600 else 5000
    private val fatSectors = ((clusters + 2) * (if (kind == 32) 4 else 2) + 511) / 512
    private val rootDirSectors = rootEntries * 32 / 512
    private val totalSectors = reserved + 2 * fatSectors + rootDirSectors + clusters
    val bytes = ByteArray(totalSectors * 512)
    private val dataOffset = (reserved + 2 * fatSectors + rootDirSectors) * 512
    private var nextCluster = 2

    inner class Dir(private val clusterList: List<Int>?, private val fixedOffset: Int = 0) {
        val firstCluster: Int get() = clusterList?.first() ?: 0
        var count = 0
        fun put(entry: ByteArray) {
            val index = count++
            val offset = if (clusterList == null) {
                fixedOffset + index * 32
            } else {
                clusterOffset(clusterList[index * 32 / 512]) + (index * 32) % 512
            }
            System.arraycopy(entry, 0, bytes, offset, 32)
        }
    }

    lateinit var root: Dir

    init {
        val b = bytes
        b[0] = 0xEB.toByte(); b[1] = 0x3C; b[2] = 0x90.toByte()
        "MSDOS5.0".toByteArray().copyInto(b, 3)
        put16(11, 512); b[13] = 1; put16(14, reserved); b[16] = 2; put16(17, rootEntries)
        if (kind == 16) put16(19, totalSectors)
        b[21] = 0xF8.toByte()
        if (kind == 16) put16(22, fatSectors) else put32(36, fatSectors)
        if (kind == 32) put32(32, totalSectors)
        val labelBytes = volumeLabel.padEnd(11).toByteArray()
        if (kind == 32) {
            put32(44, 2)
            labelBytes.copyInto(b, 71)
            "FAT32   ".toByteArray().copyInto(b, 82)
        } else {
            labelBytes.copyInto(b, 43)
            "FAT16   ".toByteArray().copyInto(b, 54)
        }
        b[510] = 0x55; b[511] = 0xAA.toByte()
        setFat(0, if (kind == 32) 0x0FFFFFF8 else 0xFFF8)
        setFat(1, if (kind == 32) 0x0FFFFFFF else 0xFFFF)
        root = if (kind == 32) Dir(allocate(4, spread = true)) else Dir(null, (reserved + 2 * fatSectors) * 512)
    }

    private fun put16(o: Int, v: Int) { bytes[o] = v.toByte(); bytes[o + 1] = (v shr 8).toByte() }
    private fun put32(o: Int, v: Int) { put16(o, v and 0xFFFF); put16(o + 2, v ushr 16) }

    private fun clusterOffset(c: Int) = dataOffset + (c - 2) * 512

    fun setFat(cluster: Int, value: Int) {
        for (copy in 0..1) {
            val base = (reserved + copy * fatSectors) * 512
            if (kind == 32) put32(base + cluster * 4, value) else put16(base + cluster * 2, value)
        }
    }

    /** Réserve `count` clusters ; `spread` laisse un cluster libre entre deux pour que la chaîne ne soit jamais contiguë. */
    fun allocate(count: Int, spread: Boolean = false): List<Int> {
        val list = ArrayList<Int>()
        repeat(count) {
            list.add(nextCluster)
            nextCluster += if (spread) 2 else 1
        }
        val end = if (kind == 32) 0x0FFFFFFF else 0xFFFF
        list.forEachIndexed { i, c -> setFat(c, if (i == list.size - 1) end else list[i + 1]) }
        return list
    }

    private fun dateWord() = ((2026 - 1980) shl 9) or (11 shl 5) or 17
    private fun timeWord() = (14 shl 11) or (30 shl 5) or 5

    fun add(dir: Dir, longName: String?, short: String, attr: Int, cluster: Int, size: Int, caseFlags: Int = 0) {
        val shortBytes = short.padEnd(11).toByteArray(Charsets.ISO_8859_1)
        if (longName != null) {
            var sum = 0
            for (k in 0 until 11) sum = (((sum and 1) shl 7) + (sum shr 1) + (shortBytes[k].toInt() and 0xFF)) and 0xFF
            val chars = longName.toCharArray().toMutableList()
            if (chars.size % 13 != 0) {
                chars.add('\u0000')
                while (chars.size % 13 != 0) chars.add('￿')
            }
            val parts = chars.size / 13
            for (n in parts downTo 1) {
                val e = ByteArray(32)
                e[0] = (n or (if (n == parts) 0x40 else 0)).toByte()
                e[11] = 0x0F; e[13] = sum.toByte()
                val slice = chars.subList((n - 1) * 13, n * 13)
                val offsets = intArrayOf(1, 3, 5, 7, 9, 14, 16, 18, 20, 22, 24, 28, 30)
                offsets.forEachIndexed { i, o -> e[o] = slice[i].code.toByte(); e[o + 1] = (slice[i].code shr 8).toByte() }
                dir.put(e)
            }
        }
        val e = ByteArray(32)
        shortBytes.copyInto(e, 0)
        e[11] = attr.toByte(); e[12] = caseFlags.toByte()
        e[22] = timeWord().toByte(); e[23] = (timeWord() shr 8).toByte()
        e[24] = dateWord().toByte(); e[25] = (dateWord() shr 8).toByte()
        e[20] = (cluster shr 16).toByte(); e[21] = (cluster shr 24).toByte()
        e[26] = cluster.toByte(); e[27] = (cluster shr 8).toByte()
        for (k in 0..3) e[28 + k] = (size shr (8 * k)).toByte()
        dir.put(e)
    }

    /** Crée un sous-dossier avec « . » et « .. » ; `capacity` = nombre d'entrées de 32 octets prévues. */
    fun mkdir(parent: Dir, longName: String?, short: String, capacity: Int = 16, spread: Boolean = false): Dir {
        val list = allocate((capacity * 32 + 511) / 512, spread)
        val dir = Dir(list)
        add(parent, longName, short, 0x10, list.first(), 0)
        add(dir, null, ".", 0x10, list.first(), 0)
        add(dir, null, "..", 0x10, parent.firstCluster, 0)
        return dir
    }
}

/** Fabrique d'image exFAT en mémoire (clusters de 512 octets). */
class ExFatImage(label: String = "EASYROMS", compressedUpcase: Boolean = false) {
    private val fatOffsetSectors = 24
    private val heapSectors = 32
    private val clusterCount = 400
    val bytes = ByteArray((heapSectors + clusterCount) * 512)
    private var nextCluster = 2
    private val allocated = HashSet<Int>()
    private var bitmapOffset = -1 // octet de la table d'allocation dans l'image, une fois posée

    fun clusterOffset(cluster: Int) = heapSectors * 512 + (cluster - 2) * 512
    val clusterSize = 512
    val totalClusters = clusterCount

    private fun mark(cluster: Int, used: Boolean) {
        val bit = cluster - 2
        val i = bitmapOffset + bit / 8
        bytes[i] = if (used) (bytes[i].toInt() or (1 shl (bit % 8))).toByte() else (bytes[i].toInt() and (1 shl (bit % 8)).inv()).toByte()
    }

    /** Ne laisse libres que ces clusters ; tout ce qui est déjà alloué reste occupé. */
    fun freeOnly(free: Set<Int>) {
        for (c in 2 until clusterCount + 2) mark(c, c in allocated || c !in free)
    }

    inner class Dir(val clusters: List<Int>, val contiguous: Boolean) {
        var count = 0
        fun put(entry: ByteArray) {
            for (k in 0 until entry.size / 32) {
                val index = count++
                val offset = heapSectors * 512 + (clusters[index * 32 / 512] - 2) * 512 + (index * 32) % 512
                System.arraycopy(entry, k * 32, bytes, offset, 32)
            }
        }
        val length: Int get() = clusters.size * 512
    }

    val root: Dir

    private fun put32(o: Int, v: Long) { for (k in 0..3) bytes[o + k] = (v shr (8 * k)).toByte() }
    private fun put64(o: Int, v: Long) { for (k in 0..7) bytes[o + k] = (v shr (8 * k)).toByte() }

    private fun setFat(cluster: Int, value: Long) = put32(fatOffsetSectors * 512 + cluster * 4, value)

    fun allocate(count: Int, chained: Boolean, spread: Boolean = false): List<Int> {
        val list = ArrayList<Int>()
        repeat(count) {
            list.add(nextCluster)
            nextCluster += if (spread) 2 else 1
        }
        if (chained) list.forEachIndexed { i, c -> setFat(c, if (i == list.size - 1) 0xFFFFFFFFL else list[i + 1].toLong()) }
        allocated.addAll(list)
        if (bitmapOffset >= 0) list.forEach { mark(it, true) }
        return list
    }

    init {
        "EXFAT   ".toByteArray().copyInto(bytes, 3)
        put64(72, (heapSectors + clusterCount).toLong())
        put32(80, fatOffsetSectors.toLong()); put32(84, 4); put32(88, heapSectors.toLong())
        put32(92, clusterCount.toLong())
        bytes[108] = 9; bytes[109] = 0
        bytes[510] = 0x55; bytes[511] = 0xAA.toByte()
        // La racine tient dans deux clusters séparés, reliés par la table d'allocation.
        root = Dir(allocate(2, chained = true, spread = true), contiguous = false)
        put32(96, root.clusters.first().toLong())
        val l = ByteArray(32)
        l[0] = 0x83.toByte(); l[1] = label.length.toByte()
        label.toByteArray(Charsets.UTF_16LE).copyInto(l, 2)
        root.put(l)

        // Table d'allocation (50 octets = 400 clusters) et table des majuscules (ASCII), reliées par la FAT.
        val bitmapCluster = allocate(1, chained = true).single()
        val upcaseCluster = allocate(1, chained = true).single()
        bitmapOffset = clusterOffset(bitmapCluster)
        for (c in allocated) mark(c, true)
        val b = ByteArray(32)
        b[0] = 0x81.toByte(); put32Into(b, 20, bitmapCluster.toLong()); put64Into(b, 24, 50)
        root.put(b)
        var upcaseBytes = 256L
        if (compressedUpcase) {
            // Comme le formateur exFAT : « les 0x61 premiers sont identiques », A..Z, « les 0x85 suivants sont identiques ».
            val words = ArrayList<Int>()
            words.add(0xFFFF); words.add(0x61)
            for (ch in 'A'..'Z') words.add(ch.code)
            words.add(0xFFFF); words.add(0x85)
            words.forEachIndexed { i, w ->
                bytes[clusterOffset(upcaseCluster) + 2 * i] = w.toByte()
                bytes[clusterOffset(upcaseCluster) + 2 * i + 1] = (w shr 8).toByte()
            }
            upcaseBytes = words.size * 2L
        } else {
            for (i in 0 until 128) {
                val up = if (i in 'a'.code..'z'.code) i - 32 else i
                bytes[clusterOffset(upcaseCluster) + 2 * i] = up.toByte()
            }
        }
        val u = ByteArray(32)
        u[0] = 0x82.toByte(); put32Into(u, 20, upcaseCluster.toLong()); put64Into(u, 24, upcaseBytes)
        root.put(u)
    }

    /** Fichier réellement présent : clusters réservés, contenu écrit, entrée posée. */
    fun addFile(dir: Dir, name: String, content: ByteArray): List<Int> {
        val count = (content.size + 511) / 512
        val list = if (count == 0) emptyList() else allocate(count, chained = false)
        list.forEachIndexed { i, c ->
            System.arraycopy(content, i * 512, bytes, clusterOffset(c), minOf(512, content.size - i * 512))
        }
        add(dir, name, cluster = list.firstOrNull() ?: 0, size = content.size.toLong())
        return list
    }

    fun mkdir(parent: Dir, name: String, capacityClusters: Int = 1): Dir {
        val dir = Dir(allocate(capacityClusters, chained = false), contiguous = true)
        add(parent, name, attr = 0x10, cluster = dir.clusters.first(), size = capacityClusters * 512L, contiguous = true)
        return dir
    }

    fun add(
        dir: Dir, name: String, attr: Int = 0x20, cluster: Int = 0, size: Long = 0, contiguous: Boolean = true,
        utcOffset: Int = 0x80 or 4, nameUnitsOverride: Int? = null,
    ) {
        val units = name.toByteArray(Charsets.UTF_16LE)
        val nameEntries = (name.length + 14) / 15
        val set = ByteArray(32 * (2 + nameEntries))
        set[0] = 0x85.toByte(); set[1] = (1 + nameEntries).toByte()
        set[4] = attr.toByte()
        // 2026-11-17 14:30:10, décalage +1 h
        val stamp = ((2026 - 1980).toLong() shl 25) or (11L shl 21) or (17L shl 16) or (14L shl 11) or (30L shl 5) or 5L
        put32Into(set, 12, stamp)
        set[23] = utcOffset.toByte()
        set[32] = 0xC0.toByte(); set[33] = (if (contiguous) 0x03 else 0x01).toByte()
        set[32 + 3] = (nameUnitsOverride ?: name.length).toByte()
        put64Into(set, 32 + 8, size); put32Into(set, 32 + 20, cluster.toLong()); put64Into(set, 32 + 24, size)
        for (n in 0 until nameEntries) {
            val base = 64 + n * 32
            set[base] = 0xC1.toByte()
            val chunk = units.copyOfRange(n * 30, minOf(units.size, (n + 1) * 30))
            chunk.copyInto(set, base + 2)
        }
        // Hachage du nom (en majuscules ASCII, comme la table posée par le constructeur) puis somme de contrôle.
        var hash = 0
        for (ch in name) {
            val up = if (ch in 'a'..'z') ch.code - 32 else ch.code
            for (b in intArrayOf(up and 0xFF, up shr 8)) hash = ((((hash and 1) shl 15) or (hash shr 1)) + b) and 0xFFFF
        }
        set[32 + 4] = hash.toByte(); set[32 + 5] = (hash shr 8).toByte()
        var sum = 0
        for (k in set.indices) {
            if (k == 2 || k == 3) continue
            sum = ((((sum and 1) shl 15) or (sum shr 1)) + (set[k].toInt() and 0xFF)) and 0xFFFF
        }
        set[2] = sum.toByte(); set[3] = (sum shr 8).toByte()
        dir.put(set)
    }

    fun setFatEntry(cluster: Int, value: Long) = setFat(cluster, value)

    private fun put32Into(b: ByteArray, o: Int, v: Long) { for (k in 0..3) b[o + k] = (v shr (8 * k)).toByte() }
    private fun put64Into(b: ByteArray, o: Int, v: Long) { for (k in 0..7) b[o + k] = (v shr (8 * k)).toByte() }
}
