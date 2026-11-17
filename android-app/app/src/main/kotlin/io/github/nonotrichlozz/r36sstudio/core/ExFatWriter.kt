// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import java.io.IOException
import java.io.InputStream
import java.util.Calendar
import java.util.TimeZone

/** Pas assez de place libre sur la carte. */
class NotEnoughSpaceOnCardException(val neededBytes: Long) : IOException("Pas assez de place sur la carte")

/** Le dossier n'a plus de place pour une entrée de plus. Rien n'est écrit. */
class DirectoryFullException : IOException("Le dossier est plein")

/** Un fichier de ce nom existe déjà dans le dossier. Rien n'est écrit. */
class AlreadyOnCardException(val name: String) : IOException("« $name » existe déjà dans ce dossier")

/** La copie est écrite, mais sa relecture ne donne pas la même chose que l'original. */
class CopyVerifyFailedException(detail: String) : IOException(detail)

/** Où en est la copie : octets déjà traités sur le total. */
fun interface CopyProgress {
    fun onProgress(done: Long, total: Long, workBytes: Long)
}

/**
 * Ajoute des fichiers à une partition exFAT, **sans jamais rien effacer ni
 * remplacer**. Écrit à la main, donc entouré de garde-fous :
 *
 * - tout est vérifié avant la première écriture (place, nom, dossier, tables
 *   du volume) : au moindre doute, rien n'est écrit ;
 * - ordre d'écriture sûr : les données dans des clusters encore libres (que
 *   rien ne référence), puis la table d'allocation, puis, en dernier,
 *   l'entrée du dossier, activée d'un seul octet : une coupure à n'importe
 *   quel moment laisse au pire de la place perdue, jamais un volume abîmé ;
 * - seuls les octets nécessaires sont touchés (jamais un secteur entier
 *   réécrit sans l'avoir relu), et `verify` relit tout après coup.
 */
class ExFatWriter(
    private val device: BlockDevice,
    private val partitionStart: Long,
    private val partitionSize: Long,
) {
    private class Run(val start: Long, val length: Long)

    /** Ce qu'une copie a ajouté, pour la relecture. */
    class Added(val dirPath: List<String>, val name: String, val sizeBytes: Long)

    @Throws(IOException::class)
    fun copyFile(
        dirPath: List<String>,
        wantedName: String,
        sizeBytes: Long,
        openSource: () -> InputStream,
        cancel: CancelToken,
        progress: CopyProgress,
    ): Added {
        if (sizeBytes < 0) throw IOException("Taille du fichier inconnue")
        val name = sanitizeName(wantedName)

        // ---- 1. Tout vérifier, sans rien écrire -------------------------------
        val volume = ExFatVolume(VolumeReader(device, partitionStart, partitionSize))
        var dir = volume.rootRef
        var siblings = volume.listRoot()
        for (part in dirPath) {
            val next = siblings.firstOrNull { it.isDirectory && it.name.equals(part, ignoreCase = true) }
                ?: throw FsException("dossier introuvable : $part")
            dir = volume.refOf(next)
            siblings = volume.list(next)
        }
        val upcase = volume.readUpcase() ?: throw FsException("table des majuscules illisible")
        val wantedKey = upcased(name, upcase)
        if (siblings.any { upcased(it.name, upcase) == wantedKey }) throw AlreadyOnCardException(name)

        val clusterSize = volume.clusterSize
        val neededClusters = (sizeBytes + clusterSize - 1) / clusterSize
        val bitmap = volume.readBitmap()
        val runs = if (neededClusters == 0L) emptyList() else planRuns(bitmap, volume.clusterCount, neededClusters)
            ?: throw NotEnoughSpaceOnCardException(neededClusters * clusterSize)

        val nameEntries = (name.length + 14) / 15
        val setBytes = 32 * (2 + nameEntries)
        val dirClusters = volume.dirClusterList(dir)
        val dirData = volume.readDirBytes(dir)
        val slot = findFreeSlot(dirData, setBytes) ?: throw DirectoryFullException()

        val firstCluster = runs.firstOrNull()?.start ?: 0L
        val fragmented = runs.size > 1
        val entrySet = buildEntrySet(name, upcase, nameEntries, sizeBytes, firstCluster, contiguous = !fragmented)

        // ---- 2. Les données, dans des clusters libres ---------------------------
        if (cancel.cancelled) throw OperationCancelled()
        writeData(volume, runs, sizeBytes, openSource, cancel, progress)

        // Dernier point d'annulation : jusqu'ici, seule de la place libre a reçu des octets.
        if (cancel.cancelled) throw OperationCancelled()

        // ---- 3. La chaîne FAT (seulement si le fichier est en plusieurs morceaux) -
        if (fragmented) {
            for ((index, run) in runs.withIndex()) {
                val bytes = ByteArray((run.length * 4).toInt())
                for (k in 0 until run.length.toInt()) {
                    val last = index == runs.size - 1 && k == run.length.toInt() - 1
                    val next = if (last) 0xFFFFFFFFL else if (k == run.length.toInt() - 1) runs[index + 1].start else run.start + k + 1
                    putU32(bytes, k * 4, next)
                }
                writeAt(volume.fatOffset + run.start * 4, bytes, 0, bytes.size)
            }
        }

        // ---- 4. La table d'allocation : les clusters deviennent « occupés » ------
        if (runs.isNotEmpty()) {
            var lo = Int.MAX_VALUE
            var hi = -1
            for (run in runs) {
                for (c in run.start until run.start + run.length) {
                    val bit = (c - 2)
                    val index = (bit shr 3).toInt()
                    bitmap[index] = (bitmap[index].toInt() or (1 shl (bit and 7L).toInt())).toByte()
                    if (index < lo) lo = index
                    if (index > hi) hi = index
                }
            }
            writeInClusters(volume, volume.systemFileClusters(volume.bitmapCluster, volume.bitmapLength), lo.toLong(), bitmap.copyOfRange(lo, hi + 1))
        }

        // ---- 5. L'entrée du dossier, en dernier, activée d'un seul octet ---------
        val inactive = entrySet.copyOf()
        inactive[0] = 0x05 // entrée « supprimée » le temps d'écrire le reste
        val tail = if (slot + setBytes + 32 <= dirData.size) ByteArray(32) else ByteArray(0)
        writeInClusters(volume, dirClusters, slot.toLong(), inactive + tail)
        device.flush()
        writeInClusters(volume, dirClusters, slot.toLong(), byteArrayOf(0x85.toByte()))
        device.flush()
        return Added(dirPath, name, sizeBytes)
    }

    /**
     * Relit tout, avec un volume neuf (rien de ce qui a été lu avant n'est
     * réutilisé) : l'entrée existe et sa somme de contrôle est juste, les
     * clusters sont marqués occupés, et le contenu est celui de l'original.
     */
    @Throws(IOException::class)
    fun verify(added: Added, openSource: () -> InputStream, cancel: CancelToken, progress: CopyProgress) {
        val volume = ExFatVolume(VolumeReader(device, partitionStart, partitionSize))
        var dir = volume.rootRef
        var siblings = volume.listRoot()
        for (part in added.dirPath) {
            val next = siblings.firstOrNull { it.isDirectory && it.name.equals(part, ignoreCase = true) }
                ?: throw CopyVerifyFailedException("dossier introuvable après la copie : $part")
            dir = volume.refOf(next)
            siblings = volume.list(next)
        }
        val entry = siblings.firstOrNull { it.name == added.name && !it.isDirectory }
            ?: throw CopyVerifyFailedException("fichier absent du dossier après la copie")
        if (entry.sizeBytes != added.sizeBytes) throw CopyVerifyFailedException("taille différente après la copie")
        if (!entrySetChecksumIsValid(volume.readDirBytes(dir), added.name)) {
            throw CopyVerifyFailedException("somme de contrôle de l'entrée fausse")
        }
        if (added.sizeBytes > 0) {
            val bitmap = volume.readBitmap()
            val list = volume.clustersOf(entry)
            for (c in list) {
                val bit = c - 2
                if (((bitmap[(bit shr 3).toInt()].toInt() shr (bit and 7L).toInt()) and 1) == 0) {
                    throw CopyVerifyFailedException("cluster $c non marqué occupé")
                }
            }
        }
        // Contenu : relu depuis la carte, comparé à l'original relu depuis le téléphone.
        var done = 0L
        openSource().use { source ->
            val buffer = ByteArray(VERIFY_CHUNK)
            volume.forEachFileChunk(entry, VERIFY_CHUNK) { fromCard ->
                if (cancel.cancelled) throw OperationCancelled()
                var filled = 0
                while (filled < fromCard.size) {
                    val n = source.read(buffer, filled, fromCard.size - filled)
                    if (n < 0) throw CopyVerifyFailedException("l'original est plus court que la copie")
                    filled += n
                }
                for (i in fromCard.indices) {
                    if (fromCard[i] != buffer[i]) throw CopyVerifyFailedException("contenu différent à l'octet ${done + i}")
                }
                done += fromCard.size
                progress.onProgress(done, added.sizeBytes, fromCard.size.toLong())
            }
            if (source.read() >= 0) throw CopyVerifyFailedException("l'original est plus long que la copie")
        }
    }

    // ------------------------------------------------------------------------
    // Données
    // ------------------------------------------------------------------------

    private fun writeData(
        volume: ExFatVolume,
        runs: List<Run>,
        sizeBytes: Long,
        openSource: () -> InputStream,
        cancel: CancelToken,
        progress: CopyProgress,
    ) {
        if (sizeBytes == 0L) return
        val clusterSize = volume.clusterSize
        val chunkClusters = maxOf(1, WRITE_CHUNK / clusterSize)
        val buffer = ByteArray(chunkClusters * clusterSize)
        var runIndex = 0
        var usedInRun = 0L
        var done = 0L
        openSource().use { source ->
            while (done < sizeBytes) {
                if (cancel.cancelled) throw OperationCancelled()
                val want = minOf(buffer.size.toLong(), sizeBytes - done).toInt()
                var filled = 0
                while (filled < want) {
                    val n = source.read(buffer, filled, want - filled)
                    if (n < 0) throw IOException("Le fichier est plus court que prévu")
                    filled += n
                }
                val clusters = (want + clusterSize - 1) / clusterSize
                java.util.Arrays.fill(buffer, want, clusters * clusterSize, 0.toByte()) // fin du dernier cluster
                var pos = 0
                var left = clusters
                while (left > 0) {
                    val run = runs[runIndex]
                    val take = minOf(left.toLong(), run.length - usedInRun).toInt()
                    writeAt(volume.clusterOffset(run.start + usedInRun), buffer, pos, take * clusterSize)
                    pos += take * clusterSize
                    left -= take
                    usedInRun += take
                    if (usedInRun == run.length) {
                        runIndex++
                        usedInRun = 0
                    }
                }
                done += want
                progress.onProgress(done, sizeBytes, (clusters * clusterSize).toLong())
            }
            if (source.read() >= 0) throw IOException("Le fichier est plus long que prévu")
        }
    }

    /** Écrit `data` à `offset` octets du début de la liste de clusters (en coupant aux limites de clusters). */
    private fun writeInClusters(volume: ExFatVolume, clusters: List<Long>, offset: Long, data: ByteArray) {
        val clusterSize = volume.clusterSize
        var written = 0
        while (written < data.size) {
            val position = offset + written
            val index = (position / clusterSize).toInt()
            val inCluster = (position % clusterSize).toInt()
            if (index >= clusters.size) throw FsException("écriture au-delà de la liste de clusters")
            val n = minOf(data.size - written, clusterSize - inCluster)
            writeAt(volume.clusterOffset(clusters[index]) + inCluster, data, written, n)
            written += n
        }
    }

    /** Écriture d'octets quelconques ; les secteurs partiels sont relus avant d'être réécrits. */
    private fun writeAt(offset: Long, data: ByteArray, from: Int, length: Int) {
        if (offset < 0 || offset + length > partitionSize) throw FsException("écriture hors de la partition")
        val bs = device.blockSize
        val absolute = partitionStart + offset
        val firstBlock = absolute / bs
        val lastBlock = (absolute + length - 1) / bs
        val blocks = (lastBlock - firstBlock + 1).toInt()
        val buffer = ByteArray(blocks * bs)
        val head = (absolute - firstBlock * bs).toInt()
        val aligned = head == 0 && length % bs == 0
        if (!aligned) device.read(firstBlock, buffer, blocks) // relire avant de réécrire : on ne touche que nos octets
        System.arraycopy(data, from, buffer, head, length)
        device.write(firstBlock, buffer, blocks)
    }

    // ------------------------------------------------------------------------
    // Allocation, entrées
    // ------------------------------------------------------------------------

    private fun isUsed(bitmap: ByteArray, cluster: Long): Boolean {
        val bit = cluster - 2
        return ((bitmap[(bit shr 3).toInt()].toInt() shr (bit and 7L).toInt()) and 1) != 0
    }

    /** Un seul morceau libre si possible (fichier contigu, rien à écrire dans la FAT), sinon plusieurs. */
    private fun planRuns(bitmap: ByteArray, clusterCount: Long, needed: Long): List<Run>? {
        var start = -1L
        var length = 0L
        for (c in 2 until clusterCount + 2) {
            if (!isUsed(bitmap, c)) {
                if (length == 0L) start = c
                length++
                if (length == needed) return listOf(Run(start, needed))
            } else {
                length = 0
            }
        }
        val runs = ArrayList<Run>()
        var remaining = needed
        var runStart = -1L
        var runLength = 0L
        for (c in 2 until clusterCount + 2) {
            if (remaining == 0L) break
            if (!isUsed(bitmap, c)) {
                if (runLength == 0L) runStart = c
                runLength++
                remaining--
            } else if (runLength > 0) {
                runs.add(Run(runStart, runLength))
                runLength = 0
            }
        }
        if (runLength > 0) runs.add(Run(runStart, runLength))
        return if (remaining == 0L) runs else null
    }

    /** Début de la première place libre assez grande (au marqueur de fin du dossier), `null` si le dossier est plein. */
    private fun findFreeSlot(dirData: ByteArray, setBytes: Int): Int? {
        var i = 0
        while (i + 32 <= dirData.size) {
            val kind = dirData[i].toInt() and 0xFF
            if (kind == 0x00) return if (i + setBytes <= dirData.size) i else null
            i += if (kind == 0x85) 32 * ((dirData[i + 1].toInt() and 0xFF) + 1) else 32
        }
        return null
    }

    private fun buildEntrySet(
        name: String, upcase: CharArray, nameEntries: Int, sizeBytes: Long, firstCluster: Long, contiguous: Boolean,
    ): ByteArray {
        val set = ByteArray(32 * (2 + nameEntries))
        val now = Calendar.getInstance()
        val stamp = ((now.get(Calendar.YEAR) - 1980).toLong() shl 25) or ((now.get(Calendar.MONTH) + 1).toLong() shl 21) or
            (now.get(Calendar.DAY_OF_MONTH).toLong() shl 16) or (now.get(Calendar.HOUR_OF_DAY).toLong() shl 11) or
            (now.get(Calendar.MINUTE).toLong() shl 5) or (now.get(Calendar.SECOND) / 2).toLong()
        val offsetMillis = TimeZone.getDefault().getOffset(now.timeInMillis)
        val quarters = (offsetMillis / (15 * 60_000)) and 0x7F
        val utcByte = (0x80 or quarters).toByte()

        set[0] = 0x85.toByte()
        set[1] = (1 + nameEntries).toByte()
        set[4] = 0x20 // archive
        for (o in intArrayOf(8, 12, 16)) putU32(set, o, stamp)
        set[22] = utcByte; set[23] = utcByte; set[24] = utcByte

        val stream = 32
        set[stream] = 0xC0.toByte()
        set[stream + 1] = (if (sizeBytes == 0L) 0x00 else if (contiguous) 0x03 else 0x01).toByte()
        set[stream + 3] = name.length.toByte()
        val hash = nameHash(name, upcase)
        set[stream + 4] = hash.toByte(); set[stream + 5] = (hash shr 8).toByte()
        putU64(set, stream + 8, sizeBytes)
        putU32(set, stream + 20, firstCluster)
        putU64(set, stream + 24, sizeBytes)

        val units = name.toByteArray(Charsets.UTF_16LE)
        for (n in 0 until nameEntries) {
            val base = 64 + n * 32
            set[base] = 0xC1.toByte()
            val chunk = units.copyOfRange(n * 30, minOf(units.size, (n + 1) * 30))
            System.arraycopy(chunk, 0, set, base + 2, chunk.size)
        }
        val checksum = setChecksum(set, set.size)
        set[2] = checksum.toByte(); set[3] = (checksum shr 8).toByte()
        return set
    }

    /** Vrai si l'entrée de ce nom, dans ces octets de dossier, a une somme de contrôle juste. */
    private fun entrySetChecksumIsValid(dirData: ByteArray, name: String): Boolean {
        var i = 0
        while (i + 32 <= dirData.size) {
            val kind = dirData[i].toInt() and 0xFF
            if (kind == 0x00) return false
            if (kind != 0x85) {
                i += 32
                continue
            }
            val length = 32 * ((dirData[i + 1].toInt() and 0xFF) + 1)
            if (i + length > dirData.size) return false
            val set = dirData.copyOfRange(i, i + length)
            val units = set[32 + 3].toInt() and 0xFF
            val sb = java.io.ByteArrayOutputStream()
            var k = 64
            while (k + 32 <= set.size) {
                if ((set[k].toInt() and 0xFF) == 0xC1) sb.write(set, k + 2, 30)
                k += 32
            }
            if (String(sb.toByteArray(), Charsets.UTF_16LE).take(units) == name) {
                val stored = (set[2].toInt() and 0xFF) or ((set[3].toInt() and 0xFF) shl 8)
                return stored == setChecksum(set, set.size)
            }
            i += length
        }
        return false
    }

    internal companion object {
        private const val WRITE_CHUNK = 1024 * 1024
        private const val VERIFY_CHUNK = 1024 * 1024

        private fun putU32(b: ByteArray, o: Int, v: Long) {
            for (k in 0..3) b[o + k] = (v shr (8 * k)).toByte()
        }

        private fun putU64(b: ByteArray, o: Int, v: Long) {
            for (k in 0..7) b[o + k] = (v shr (8 * k)).toByte()
        }

        /** Somme de contrôle de l'ensemble d'entrées : tout, sauf les deux octets de la somme elle-même. */
        fun setChecksum(set: ByteArray, length: Int): Int {
            var sum = 0
            for (i in 0 until length) {
                if (i == 2 || i == 3) continue
                sum = (((sum and 1) shl 15) or (sum shr 1)) + (set[i].toInt() and 0xFF)
                sum = sum and 0xFFFF
            }
            return sum
        }

        fun upcased(name: String, table: CharArray): String {
            val sb = StringBuilder(name.length)
            for (ch in name) sb.append(table[ch.code])
            return sb.toString()
        }

        /** Hachage du nom en majuscules, comme le calcule le formateur exFAT. */
        fun nameHash(name: String, table: CharArray): Int {
            var hash = 0
            for (ch in upcased(name, table)) {
                val code = ch.code
                for (byte in intArrayOf(code and 0xFF, code shr 8)) {
                    hash = (((hash and 1) shl 15) or (hash shr 1)) + byte
                    hash = hash and 0xFFFF
                }
            }
            return hash
        }

        /** Nom accepté par exFAT : pas de caractère interdit, 255 caractères au plus. */
        fun sanitizeName(raw: String): String {
            var name = raw.map { if (it.code < 0x20 || it in "\"*/:<>?\\|") '_' else it }.joinToString("").trim()
            name = name.trimEnd('.', ' ')
            if (name.isEmpty()) name = "fichier"
            if (name.length > 255) {
                val dot = name.lastIndexOf('.')
                val ext = if (dot in 1..(name.length - 1) && name.length - dot <= 16) name.substring(dot) else ""
                name = name.substring(0, 255 - ext.length) + ext
            }
            return name
        }
    }

    private fun sanitizeName(raw: String) = Companion.sanitizeName(raw)
    private fun upcased(name: String, table: CharArray) = Companion.upcased(name, table)
    private fun nameHash(name: String, table: CharArray) = Companion.nameHash(name, table)
    private fun setChecksum(set: ByteArray, length: Int) = Companion.setChecksum(set, length)
    private fun putU32(b: ByteArray, o: Int, v: Long) = Companion.putU32(b, o, v)
    private fun putU64(b: ByteArray, o: Int, v: Long) = Companion.putU64(b, o, v)
}
