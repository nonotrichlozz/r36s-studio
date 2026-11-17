// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

/**
 * Vérificateur exFAT écrit à part, sans rien reprendre du lecteur ni de
 * l'écrivain : il refait, à sa façon, ce que ferait `fsck.exfat`. Il sert à
 * juger ce que l'écrivain laisse sur la carte.
 *
 * `errors` : le volume serait abîmé (somme de contrôle, hachage de nom, cluster
 * utilisé mais libre, deux fichiers sur le même cluster, chaîne fausse...).
 * `leaks` : des clusters marqués occupés que personne n'utilise (de la place
 * perdue, sans gravité : `chkdsk` la rend).
 */
class ExFatChecker(private val img: ByteArray) {
    val errors = ArrayList<String>()
    val leaks = ArrayList<Long>()

    private val clusterSize = 1 shl (9 + (img[109].toInt() and 0xFF))
    private val fatOffset = u32(80) * 512
    private val heapOffset = u32(88) * 512
    private val clusterCount = u32(92)
    private val rootCluster = u32(96)
    private val owner = HashMap<Long, String>()
    private var upcase = CharArray(0)

    private fun u32(o: Long): Long = u32(o.toInt())
    private fun u32(o: Int): Long =
        (img[o].toLong() and 0xFF) or ((img[o + 1].toLong() and 0xFF) shl 8) or ((img[o + 2].toLong() and 0xFF) shl 16) or ((img[o + 3].toLong() and 0xFF) shl 24)
    private fun u64(o: Int): Long = u32(o) or (u32(o + 4) shl 32)
    private fun u16(o: Int): Int = (img[o].toInt() and 0xFF) or ((img[o + 1].toInt() and 0xFF) shl 8)

    private fun clusterOff(c: Long) = (heapOffset + (c - 2) * clusterSize).toInt()
    private fun fat(c: Long) = u32(fatOffset + c * 4)

    private fun chain(first: Long, noFatChain: Boolean, size: Long?, what: String): List<Long> {
        val out = ArrayList<Long>()
        if (noFatChain) {
            val n = ((size ?: 0) + clusterSize - 1) / clusterSize
            for (i in 0 until n) out.add(first + i)
        } else {
            var c = first
            val seen = HashSet<Long>()
            while (c in 2 until 0xFFFFFFF7L) {
                if (!seen.add(c)) { errors.add("$what : chaîne qui boucle"); break }
                out.add(c)
                c = fat(c)
            }
            if (c != 0xFFFFFFFFL && c < 0xFFFFFFF7L) errors.add("$what : chaîne mal terminée ($c)")
            if (size != null) {
                val expected = (size + clusterSize - 1) / clusterSize
                if (out.size.toLong() != expected) errors.add("$what : chaîne de ${out.size} clusters pour $expected attendus")
            }
        }
        for (c in out) if (c < 2 || c >= clusterCount + 2) errors.add("$what : cluster $c hors du volume")
        return out
    }

    private fun claim(clusters: List<Long>, what: String) {
        for (c in clusters) {
            val previous = owner.put(c, what)
            if (previous != null) errors.add("cluster $c utilisé par « $previous » et « $what »")
        }
    }

    private fun readClusters(list: List<Long>, length: Int): ByteArray {
        val out = ByteArray(length)
        var done = 0
        for (c in list) {
            val n = minOf(clusterSize, length - done)
            if (n <= 0) break
            System.arraycopy(img, clusterOff(c), out, done, n)
            done += n
        }
        return out
    }

    fun run(): ExFatChecker {
        val rootList = chain(rootCluster, false, null, "racine")
        claim(rootList, "racine")
        val rootData = readClusters(rootList, rootList.size * clusterSize)
        var bitmapFirst = 0L
        var bitmapLength = 0L
        var i = 0
        while (i + 32 <= rootData.size) {
            val kind = rootData[i].toInt() and 0xFF
            if (kind == 0) break
            val o = i
            fun d(k: Int) = rootData[o + k]
            when (kind) {
                0x81 -> {
                    bitmapFirst = (0 until 4).sumOf { ((d(20 + it).toLong() and 0xFF) shl (8 * it)) }
                    bitmapLength = (0 until 8).sumOf { ((d(24 + it).toLong() and 0xFF) shl (8 * it)) }
                }
                0x82 -> {
                    val first = (0 until 4).sumOf { ((d(20 + it).toLong() and 0xFF) shl (8 * it)) }
                    val length = (0 until 8).sumOf { ((d(24 + it).toLong() and 0xFF) shl (8 * it)) }
                    val list = chain(first, false, length, "majuscules")
                    claim(list, "majuscules")
                    val raw = readClusters(list, length.toInt())
                    upcase = CharArray(65536) { it.toChar() }
                    var idx = 0
                    var k = 0
                    while (k + 1 < raw.size) {
                        val w = (raw[k].toInt() and 0xFF) or ((raw[k + 1].toInt() and 0xFF) shl 8)
                        k += 2
                        if (w == 0xFFFF) { // série compressée : le mot suivant dit combien de caractères restent identiques
                            idx += (raw[k].toInt() and 0xFF) or ((raw[k + 1].toInt() and 0xFF) shl 8)
                            k += 2
                        } else {
                            upcase[idx++] = w.toChar()
                        }
                    }
                }
            }
            i += if (kind == 0x85) 32 * ((rootData[i + 1].toInt() and 0xFF) + 1) else 32
        }
        val bitmapList = chain(bitmapFirst, false, bitmapLength, "bitmap")
        claim(bitmapList, "bitmap")
        if (upcase.isEmpty()) errors.add("table des majuscules absente")

        walk(rootData, "")

        val bitmap = readClusters(bitmapList, bitmapLength.toInt())
        for (c in 2 until clusterCount + 2) {
            val bit = c - 2
            val set = ((bitmap[(bit shr 3).toInt()].toInt() shr (bit and 7L).toInt()) and 1) != 0
            val used = owner.containsKey(c)
            if (used && !set) errors.add("cluster $c utilisé (${owner[c]}) mais marqué libre")
            if (!used && set) leaks.add(c)
        }
        return this
    }

    private fun walk(data: ByteArray, path: String) {
        val seenNames = HashSet<String>()
        var i = 0
        while (i + 32 <= data.size) {
            val kind = data[i].toInt() and 0xFF
            if (kind == 0) return
            if (kind != 0x85) {
                i += 32
                continue
            }
            val count = data[i + 1].toInt() and 0xFF
            val length = 32 * (count + 1)
            if (i + length > data.size) { errors.add("$path : entrée tronquée"); return }
            val set = data.copyOfRange(i, i + length)
            i += length

            var sum = 0
            for (k in set.indices) {
                if (k == 2 || k == 3) continue
                sum = ((((sum and 1) shl 15) or (sum shr 1)) + (set[k].toInt() and 0xFF)) and 0xFFFF
            }
            val stored = (set[2].toInt() and 0xFF) or ((set[3].toInt() and 0xFF) shl 8)
            if (stored != sum) errors.add("$path : somme de contrôle fausse")

            if ((set[32].toInt() and 0xFF) != 0xC0) { errors.add("$path : pas de flux"); continue }
            val units = set[35].toInt() and 0xFF
            val raw = java.io.ByteArrayOutputStream()
            var k = 64
            while (k + 32 <= set.size) {
                if ((set[k].toInt() and 0xFF) == 0xC1) raw.write(set, k + 2, 30)
                k += 32
            }
            if (count != 1 + (units + 14) / 15) errors.add("$path : nombre d'entrées de nom faux")
            val name = String(raw.toByteArray(), Charsets.UTF_16LE).take(units)
            val full = "$path/$name"
            var hash = 0
            for (ch in name) {
                val up = upcase[ch.code].code
                for (b in intArrayOf(up and 0xFF, up shr 8)) hash = ((((hash and 1) shl 15) or (hash shr 1)) + b) and 0xFFFF
            }
            val storedHash = (set[36].toInt() and 0xFF) or ((set[37].toInt() and 0xFF) shl 8)
            if (storedHash != hash) errors.add("$full : hachage du nom faux")
            val key = name.map { upcase[it.code] }.joinToString("")
            if (!seenNames.add(key)) errors.add("$full : deux entrées portent ce nom")

            val flags = set[33].toInt() and 0xFF
            val noFatChain = flags and 0x02 != 0
            val first = (0 until 4).sumOf { ((set[32 + 20 + it].toLong() and 0xFF) shl (8 * it)) }
            val dataLength = (0 until 8).sumOf { ((set[32 + 24 + it].toLong() and 0xFF) shl (8 * it)) }
            val valid = (0 until 8).sumOf { ((set[32 + 8 + it].toLong() and 0xFF) shl (8 * it)) }
            if (valid > dataLength) errors.add("$full : taille valide > taille")
            val isDir = (set[4].toInt() and 0x10) != 0
            if (dataLength == 0L) {
                if (first != 0L) errors.add("$full : fichier vide avec un cluster")
                continue
            }
            val list = chain(first, noFatChain, dataLength, full)
            claim(list, full)
            if (isDir) walk(readClusters(list, dataLength.toInt()), full)
        }
    }
}
