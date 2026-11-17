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

/**
 * La carte ne se relit pas pareil d'une fois sur l'autre (lecteur USB qui
 * décroche ou décale les octets). On arrête avant de toucher aux tables du
 * volume : le fichier n'est pas ajouté, la carte n'est pas abîmée.
 */
class UnstableCardReadException(detail: String) : IOException(detail)

/** Copie arrêtée en route, avant l'ajout de l'entrée : fichier absent, carte intacte (au pire de la place perdue). */
class CopyInterruptedException(cause: IOException) : IOException(cause.message, cause)

/**
 * Remplacement arrêté entre le retrait de l'ancien fichier et l'ajout du
 * nouveau : aucun des deux n'apparaît, la carte n'est pas abîmée. Il suffit
 * de recommencer la copie.
 */
class ReplaceInterruptedException(cause: IOException) : IOException(cause.message, cause)

/** Le fichier est écrit, mais il n'a pas pu être relu jusqu'au bout. */
class CopyNotVerifiedException(cause: IOException) : IOException(cause.message, cause)

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

    /** Le fichier du même nom à remplacer : où est son entrée, quels clusters il occupe. */
    private class Replaced(val setOffset: Int, val setLength: Int, val clusters: List<Long>)

    /** Tout ce que la copie a besoin de savoir, lu sur la carte avant d'écrire. */
    private class Plan(
        val volume: ExFatVolume,
        val boot: ByteArray,
        val dirClusters: List<Long>,
        val dirData: ByteArray,
        val upcase: CharArray,
        val bitmap: ByteArray,
        val bitmapClusters: List<Long>,
        val runs: List<Run>,
        val slot: Int,
        val replaced: Replaced?,
    ) {
        /** `null` si les deux préparations sont identiques, sinon ce qui diffère (pour le journal). */
        fun differenceFrom(other: Plan): String? = when {
            !boot.contentEquals(other.boot) -> "secteur de démarrage"
            dirClusters != other.dirClusters -> "clusters du dossier"
            !dirData.contentEquals(other.dirData) -> "contenu du dossier"
            !upcase.contentEquals(other.upcase) -> "table des majuscules"
            !bitmap.contentEquals(other.bitmap) -> "table d'allocation"
            bitmapClusters != other.bitmapClusters -> "clusters de la table d'allocation"
            runs.map { it.start to it.length } != other.runs.map { it.start to it.length } -> "place choisie"
            slot != other.slot -> "place dans le dossier"
            replaced?.setOffset != other.replaced?.setOffset || replaced?.setLength != other.replaced?.setLength ||
                replaced?.clusters != other.replaced?.clusters -> "fichier à remplacer"
            else -> null
        }

        fun describe(fragmented: Boolean): String {
            val where = runs.joinToString(", ") { "${it.start}+${it.length}" }
            return "clusters de ${volume.clusterSize} octets, " +
                (if (runs.isEmpty()) "fichier vide" else if (fragmented) "en ${runs.size} morceaux ($where)" else "d'un seul tenant ($where)") +
                ", entrée à l'octet $slot du dossier" +
                (if (replaced != null) ", remplace l'entrée de l'octet ${replaced.setOffset} (${replaced.clusters.size} clusters libérés)" else "")
        }
    }

    /** Résumé de la dernière copie préparée (pour le journal de l'appli). */
    var lastPlanDescription: String = ""
        private set

    private fun plan(dirPath: List<String>, name: String, sizeBytes: Long, replace: Boolean): Plan {
        val reader = VolumeReader(device, partitionStart, partitionSize)
        val volume = ExFatVolume(reader)
        if (volume.clusterSize % device.blockSize != 0 || (partitionStart + volume.heapOffset) % device.blockSize != 0L) {
            throw FsException("clusters non alignés sur les secteurs de la carte")
        }
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
        val dirClusters = volume.dirClusterList(dir)
        val dirData = volume.readDirBytes(dir)
        val existing = siblings.firstOrNull { upcased(it.name, upcase) == wantedKey }
        var replaced: Replaced? = null
        if (existing != null) {
            // Un dossier du même nom n'est jamais remplacé, un fichier seulement si on l'a demandé.
            if (!replace || existing.isDirectory) throw AlreadyOnCardException(name)
            val (setOffset, setLength) = findSet(dirData, wantedKey, upcase) ?: throw FsException("entrée du fichier à remplacer introuvable")
            replaced = Replaced(setOffset, setLength, if (existing.sizeBytes == 0L) emptyList() else volume.clustersOf(existing))
        }

        val clusterSize = volume.clusterSize
        val neededClusters = (sizeBytes + clusterSize - 1) / clusterSize
        val bitmap = volume.readBitmap()
        val runs = if (neededClusters == 0L) emptyList() else planRuns(bitmap, volume.clusterCount, neededClusters)
            ?: throw NotEnoughSpaceOnCardException(neededClusters * clusterSize)

        val setBytes = 32 * (2 + (name.length + 14) / 15)
        val slot = findFreeSlot(dirData, setBytes) ?: throw DirectoryFullException()
        return Plan(
            volume = volume,
            boot = reader.read(0, 512),
            dirClusters = dirClusters,
            dirData = dirData,
            upcase = upcase,
            bitmap = bitmap,
            bitmapClusters = volume.systemFileClusters(volume.bitmapCluster, volume.bitmapLength),
            runs = runs,
            slot = slot,
            replaced = replaced,
        )
    }

    /** Ce qu'une copie a ajouté, pour la relecture. */
    class Added(val dirPath: List<String>, val name: String, val sizeBytes: Long, val replaced: Boolean = false)

    @Throws(IOException::class)
    fun copyFile(
        dirPath: List<String>,
        wantedName: String,
        sizeBytes: Long,
        openSource: () -> InputStream,
        cancel: CancelToken,
        progress: CopyProgress,
        replace: Boolean = false,
    ): Added {
        if (sizeBytes < 0) throw IOException("Taille du fichier inconnue")
        val name = sanitizeName(wantedName)

        // ---- 1. Tout vérifier, sans rien écrire -------------------------------
        // Deux préparations complètes, chacune avec son propre cache de lecture :
        // un lecteur qui rend des octets faux (décalés, incomplets) donnerait
        // deux plans différents. Dans ce cas on s'arrête avant d'écrire quoi que ce soit.
        val plan = plan(dirPath, name, sizeBytes, replace)
        val second = plan(dirPath, name, sizeBytes, replace)
        val difference = plan.differenceFrom(second)
        if (difference != null) throw UnstableCardReadException("deux lectures de la carte ne concordent pas ($difference)")

        val volume = plan.volume
        val bitmap = plan.bitmap.copyOf()
        val runs = plan.runs
        val slot = plan.slot
        val dirClusters = plan.dirClusters
        val dirData = plan.dirData
        val nameEntries = (name.length + 14) / 15
        val setBytes = 32 * (2 + nameEntries)
        val firstCluster = runs.firstOrNull()?.start ?: 0L
        val fragmented = runs.size > 1
        val entrySet = buildEntrySet(name, plan.upcase, nameEntries, sizeBytes, firstCluster, contiguous = !fragmented)
        lastPlanDescription = plan.describe(fragmented)

        // Toutes les écritures dans les tables du volume, préparées d'avance.
        val bitmapClusters = plan.bitmapClusters
        val fatPieces = ArrayList<Pair<Long, ByteArray>>()
        if (fragmented) {
            for ((index, run) in runs.withIndex()) {
                val bytes = ByteArray((run.length * 4).toInt())
                for (k in 0 until run.length.toInt()) {
                    val lastOfRun = k == run.length.toInt() - 1
                    val next = when {
                        lastOfRun && index == runs.size - 1 -> 0xFFFFFFFFL
                        lastOfRun -> runs[index + 1].start
                        else -> run.start + k + 1
                    }
                    putU32(bytes, k * 4, next)
                }
                fatPieces.add(Pair(volume.fatOffset + run.start * 4, bytes))
            }
        }
        var bitmapLo = Int.MAX_VALUE
        var bitmapHi = -1
        for (run in runs) {
            for (c in run.start until run.start + run.length) {
                val bit = c - 2
                val index = (bit shr 3).toInt()
                bitmap[index] = (bitmap[index].toInt() or (1 shl (bit and 7L).toInt())).toByte()
                if (index < bitmapLo) bitmapLo = index
                if (index > bitmapHi) bitmapHi = index
            }
        }
        // Remplacement : l'ancienne entrée est retirée (octets de type sans le bit « en service »),
        // puis ses clusters sont rendus à la table d'allocation, une fois le nouveau fichier en place.
        val replaced = plan.replaced
        val oldSet = replaced?.let { r -> dirData.copyOfRange(r.setOffset, r.setOffset + r.setLength) }
        oldSet?.let { set -> for (k in set.indices step 32) set[k] = (set[k].toInt() and 0x7F).toByte() }
        val freed = bitmap.copyOf()
        var freeLo = Int.MAX_VALUE
        var freeHi = -1
        for (c in replaced?.clusters.orEmpty()) {
            val bit = c - 2
            val index = (bit shr 3).toInt()
            freed[index] = (freed[index].toInt() and (1 shl (bit and 7L).toInt()).inv()).toByte()
            if (index < freeLo) freeLo = index
            if (index > freeHi) freeHi = index
        }

        val inactive = entrySet.copyOf()
        inactive[0] = 0x05 // entrée « supprimée » le temps d'écrire le reste
        val tail = if (slot + setBytes + 32 <= dirData.size) ByteArray(32) else ByteArray(0)
        val dirWrite = inactive + tail

        // Photo, AVANT toute écriture, des secteurs qui seront modifiés ; puis
        // relecture directe : si la carte ne se relit pas pareil, on s'arrête là.
        val shadow = HashMap<Long, ByteArray>()
        val pieces = ArrayList<Pair<Long, Int>>()
        for ((offset, bytes) in fatPieces) pieces.add(Pair(offset, bytes.size))
        if (bitmapHi >= 0) pieces.addAll(mapToClusters(volume, bitmapClusters, bitmapLo.toLong(), bitmapHi - bitmapLo + 1))
        pieces.addAll(mapToClusters(volume, dirClusters, slot.toLong(), dirWrite.size))
        if (replaced != null) pieces.addAll(mapToClusters(volume, dirClusters, replaced.setOffset.toLong(), replaced.setLength))
        if (freeHi >= 0) pieces.addAll(mapToClusters(volume, bitmapClusters, freeLo.toLong(), freeHi - freeLo + 1))
        for ((offset, length) in pieces) snapshot(volume, shadow, offset, length)
        checkStable(shadow)

        var activated = false
        var oldRemoved = false
        try {
            // ---- 2. Les données, dans des clusters libres (que rien ne référence) ---
            if (cancel.cancelled) throw OperationCancelled()
            writeData(volume, runs, sizeBytes, openSource, cancel, progress)

            // Dernier point d'annulation : jusqu'ici, seule de la place libre a reçu des octets.
            if (cancel.cancelled) throw OperationCancelled()

            // ---- 3. La chaîne FAT (seulement si le fichier est en plusieurs morceaux) -
            for ((offset, bytes) in fatPieces) writeMeta(shadow, offset, bytes, 0, bytes.size)

            // ---- 4. La table d'allocation : les clusters deviennent « occupés » ------
            if (bitmapHi >= 0) {
                writeMetaInClusters(volume, shadow, bitmapClusters, bitmapLo.toLong(), bitmap.copyOfRange(bitmapLo, bitmapHi + 1))
            }

            // ---- 5. L'entrée du dossier, en dernier, activée d'un seul octet ---------
            writeMetaInClusters(volume, shadow, dirClusters, slot.toLong(), dirWrite)
            device.flush()
            if (replaced != null && oldSet != null) {
                // Retrait de l'ancien : d'abord son entrée principale (il disparaît d'un coup), puis le reste.
                oldRemoved = true
                writeMetaInClusters(volume, shadow, dirClusters, replaced.setOffset.toLong(), oldSet.copyOfRange(0, 1))
                writeMetaInClusters(volume, shadow, dirClusters, replaced.setOffset + 32L, oldSet.copyOfRange(32, oldSet.size))
                device.flush()
            }
            activated = true
            writeMetaInClusters(volume, shadow, dirClusters, slot.toLong(), byteArrayOf(0x85.toByte()))
            device.flush()
        } catch (e: OperationCancelled) {
            throw e
        } catch (e: IOException) {
            // Avant l'octet d'activation, le nouveau fichier n'existe pas pour la carte.
            if (activated) throw CopyNotVerifiedException(e)
            if (oldRemoved) throw ReplaceInterruptedException(e)
            if (e is UnstableCardReadException) throw e
            throw CopyInterruptedException(e)
        }

        // ---- 6. Remplacement : la place de l'ancien fichier redevient libre --------
        // Le nouveau fichier est déjà en place : un échec ici ne laisse que de la place perdue.
        if (freeHi >= 0) {
            try {
                // `freed` = table avec les bits du nouveau fichier, sans ceux de l'ancien.
                writeMetaInClusters(volume, shadow, bitmapClusters, freeLo.toLong(), freed.copyOfRange(freeLo, freeHi + 1))
                device.flush()
            } catch (e: IOException) {
                lastPlanDescription += " ; place de l'ancien fichier non libérée (${e.message})"
            }
        }
        return Added(dirPath, name, sizeBytes, replaced = replaced != null)
    }

    // ------------------------------------------------------------------------
    // Suppression d'un fichier (jamais d'un dossier)
    // ------------------------------------------------------------------------

    private class DeletePlan(
        val volume: ExFatVolume,
        val boot: ByteArray,
        val dirClusters: List<Long>,
        val dirData: ByteArray,
        val bitmap: ByteArray,
        val bitmapClusters: List<Long>,
        val target: Replaced,
    ) {
        fun differenceFrom(other: DeletePlan): String? = when {
            !boot.contentEquals(other.boot) -> "secteur de démarrage"
            dirClusters != other.dirClusters -> "clusters du dossier"
            !dirData.contentEquals(other.dirData) -> "contenu du dossier"
            !bitmap.contentEquals(other.bitmap) -> "table d'allocation"
            bitmapClusters != other.bitmapClusters -> "clusters de la table d'allocation"
            target.setOffset != other.target.setOffset || target.setLength != other.target.setLength ||
                target.clusters != other.target.clusters -> "fichier à supprimer"
            else -> null
        }
    }

    private fun deletePlan(dirPath: List<String>, name: String): DeletePlan {
        val reader = VolumeReader(device, partitionStart, partitionSize)
        val volume = ExFatVolume(reader)
        if (volume.clusterSize % device.blockSize != 0 || (partitionStart + volume.heapOffset) % device.blockSize != 0L) {
            throw FsException("clusters non alignés sur les secteurs de la carte")
        }
        var dir = volume.rootRef
        var siblings = volume.listRoot()
        for (part in dirPath) {
            val next = siblings.firstOrNull { it.isDirectory && it.name.equals(part, ignoreCase = true) }
                ?: throw FsException("dossier introuvable : $part")
            dir = volume.refOf(next)
            siblings = volume.list(next)
        }
        val upcase = volume.readUpcase() ?: throw FsException("table des majuscules illisible")
        // Nom exact : on ne supprime que le fichier que l'on a montré.
        val entry = siblings.firstOrNull { it.name == name } ?: throw FsException("fichier introuvable : $name")
        if (entry.isDirectory) throw FsException("un dossier ne se supprime pas ici")
        val dirData = volume.readDirBytes(dir)
        val (setOffset, setLength) = findSet(dirData, upcased(name, upcase), upcase) ?: throw FsException("entrée introuvable")
        return DeletePlan(
            volume = volume,
            boot = reader.read(0, 512),
            dirClusters = volume.dirClusterList(dir),
            dirData = dirData,
            bitmap = volume.readBitmap(),
            bitmapClusters = volume.systemFileClusters(volume.bitmapCluster, volume.bitmapLength),
            target = Replaced(setOffset, setLength, if (entry.sizeBytes == 0L) emptyList() else volume.clustersOf(entry)),
        )
    }

    /**
     * Supprime un fichier : son entrée est retirée (d'abord l'entrée
     * principale, il disparaît d'un coup), puis sa place est rendue. Une
     * coupure entre les deux ne laisse que de la place perdue. Mêmes
     * protections que la copie : deux préparations identiques, secteurs
     * relus avant et après chaque écriture. Puis relecture : le fichier ne
     * doit plus apparaître.
     */
    @Throws(IOException::class)
    fun deleteFile(dirPath: List<String>, name: String) {
        val plan = deletePlan(dirPath, name)
        val difference = plan.differenceFrom(deletePlan(dirPath, name))
        if (difference != null) throw UnstableCardReadException("deux lectures de la carte ne concordent pas ($difference)")

        val volume = plan.volume
        val target = plan.target
        val oldSet = plan.dirData.copyOfRange(target.setOffset, target.setOffset + target.setLength)
        for (k in oldSet.indices step 32) oldSet[k] = (oldSet[k].toInt() and 0x7F).toByte()
        val freed = plan.bitmap.copyOf()
        var lo = Int.MAX_VALUE
        var hi = -1
        for (c in target.clusters) {
            val bit = c - 2
            val index = (bit shr 3).toInt()
            freed[index] = (freed[index].toInt() and (1 shl (bit and 7L).toInt()).inv()).toByte()
            if (index < lo) lo = index
            if (index > hi) hi = index
        }

        val shadow = HashMap<Long, ByteArray>()
        val pieces = ArrayList<Pair<Long, Int>>()
        pieces.addAll(mapToClusters(volume, plan.dirClusters, target.setOffset.toLong(), target.setLength))
        if (hi >= 0) pieces.addAll(mapToClusters(volume, plan.bitmapClusters, lo.toLong(), hi - lo + 1))
        for ((offset, length) in pieces) snapshot(volume, shadow, offset, length)
        checkStable(shadow)

        writeMetaInClusters(volume, shadow, plan.dirClusters, target.setOffset.toLong(), oldSet.copyOfRange(0, 1))
        writeMetaInClusters(volume, shadow, plan.dirClusters, target.setOffset + 32L, oldSet.copyOfRange(32, oldSet.size))
        device.flush()
        if (hi >= 0) {
            writeMetaInClusters(volume, shadow, plan.bitmapClusters, lo.toLong(), freed.copyOfRange(lo, hi + 1))
            device.flush()
        }

        val after = ExFatVolume(VolumeReader(device, partitionStart, partitionSize))
        var siblings = after.listRoot()
        for (part in dirPath) siblings = after.list(siblings.first { it.isDirectory && it.name.equals(part, ignoreCase = true) })
        if (siblings.any { it.name == name }) throw CopyVerifyFailedException("le fichier est toujours là après la suppression")
    }

    /**
     * Relit tout, avec un volume neuf (rien de ce qui a été lu avant n'est
     * réutilisé) : l'entrée existe et sa somme de contrôle est juste, les
     * clusters sont marqués occupés, et le contenu est celui de l'original.
     */
    @Throws(IOException::class)
    fun verify(added: Added, openSource: () -> InputStream, cancel: CancelToken, progress: CopyProgress) {
        try {
            try {
                verifyUnguarded(added, openSource, cancel, progress)
            } catch (e: CopyVerifyFailedException) {
                // Une différence peut venir d'une mauvaise lecture du lecteur USB, pas de la carte :
                // une seconde relecture complète, avec un cache neuf, tranche.
                verifyUnguarded(added, openSource, cancel, progress)
            }
        } catch (e: CopyVerifyFailedException) {
            throw e
        } catch (e: OperationCancelled) {
            throw e
        } catch (e: IOException) {
            throw CopyNotVerifiedException(e)
        }
    }

    private fun verifyUnguarded(added: Added, openSource: () -> InputStream, cancel: CancelToken, progress: CopyProgress) {
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

    /** Morceaux (position dans la partition, longueur) d'une plage d'octets d'une liste de clusters. */
    private fun mapToClusters(volume: ExFatVolume, clusters: List<Long>, offset: Long, length: Int): List<Pair<Long, Int>> {
        val clusterSize = volume.clusterSize
        val out = ArrayList<Pair<Long, Int>>()
        var done = 0
        while (done < length) {
            val position = offset + done
            val index = (position / clusterSize).toInt()
            val inCluster = (position % clusterSize).toInt()
            if (index >= clusters.size) throw FsException("écriture au-delà de la liste de clusters")
            val n = minOf(length - done, clusterSize - inCluster)
            out.add(Pair(volume.clusterOffset(clusters[index]) + inCluster, n))
            done += n
        }
        return out
    }

    private fun writeMetaInClusters(volume: ExFatVolume, shadow: MutableMap<Long, ByteArray>, clusters: List<Long>, offset: Long, data: ByteArray) {
        var from = 0
        for ((position, length) in mapToClusters(volume, clusters, offset, data.size)) {
            writeMeta(shadow, position, data, from, length)
            from += length
        }
    }

    /** Photo des secteurs couvrant cette plage, lus au moment de préparer la copie. */
    private fun snapshot(volume: ExFatVolume, shadow: MutableMap<Long, ByteArray>, offset: Long, length: Int) {
        val bs = device.blockSize
        val first = (partitionStart + offset) / bs
        val last = (partitionStart + offset + length - 1) / bs
        for (lba in first..last) {
            if (shadow.containsKey(lba)) continue
            shadow[lba] = volume.readRaw(lba * bs - partitionStart, bs)
        }
    }

    /** Relit directement chaque secteur photographié : il doit être identique, sinon le lecteur n'est pas fiable. */
    private fun checkStable(shadow: Map<Long, ByteArray>) {
        val bs = device.blockSize
        val buffer = ByteArray(bs)
        for ((lba, expected) in shadow) {
            device.read(lba, buffer, 1)
            if (!buffer.contentEquals(expected)) {
                throw UnstableCardReadException("secteur $lba relu différemment (${describeShift(expected, buffer)})")
            }
        }
    }

    /**
     * Écrit dans une table du volume : on relit le secteur, il doit être
     * exactement celui de la photo ; on ne change que nos octets ; on relit
     * après écriture pour s'assurer que la carte a gardé ce qu'on a écrit.
     */
    private fun writeMeta(shadow: MutableMap<Long, ByteArray>, offset: Long, data: ByteArray, from: Int, length: Int) {
        if (offset < 0 || offset + length > partitionSize) throw FsException("écriture hors de la partition")
        val bs = device.blockSize
        val absolute = partitionStart + offset
        val firstBlock = absolute / bs
        val blocks = ((absolute + length - 1) / bs - firstBlock + 1).toInt()
        val buffer = ByteArray(blocks * bs)
        device.read(firstBlock, buffer, blocks)
        for (k in 0 until blocks) {
            val expected = shadow[firstBlock + k] ?: throw FsException("secteur ${firstBlock + k} non préparé")
            if (!expected.contentEquals(buffer.copyOfRange(k * bs, (k + 1) * bs))) {
                throw UnstableCardReadException("secteur ${firstBlock + k} différent de la photo (${describeShift(expected, buffer.copyOfRange(k * bs, (k + 1) * bs))})")
            }
        }
        System.arraycopy(data, from, buffer, (absolute - firstBlock * bs).toInt(), length)
        device.write(firstBlock, buffer, blocks)
        val check = ByteArray(blocks * bs)
        device.read(firstBlock, check, blocks)
        if (!check.contentEquals(buffer)) throw UnstableCardReadException("secteur $firstBlock relu différent après écriture")
        for (k in 0 until blocks) shadow[firstBlock + k] = buffer.copyOfRange(k * bs, (k + 1) * bs)
    }

    /** Pour le journal : premier octet différent, et si le contenu semble simplement décalé. */
    private fun describeShift(expected: ByteArray, got: ByteArray): String {
        val first = expected.indices.firstOrNull { expected[it] != got[it] } ?: return "identique"
        for (shift in 1..64) {
            if (shift >= got.size) break
            var same = true
            for (i in 0 until minOf(64, got.size - shift)) {
                if (got[i + shift] != expected[i]) { same = false; break }
            }
            if (same) return "1er écart à l'octet $first, contenu décalé de $shift octets"
        }
        return "1er écart à l'octet $first"
    }

    /** Données : écriture alignée sur les secteurs, dans des clusters libres. */
    private fun writeAt(offset: Long, data: ByteArray, from: Int, length: Int) {
        if (offset < 0 || offset + length > partitionSize) throw FsException("écriture hors de la partition")
        val bs = device.blockSize
        val absolute = partitionStart + offset
        if (absolute % bs != 0L || length % bs != 0) throw FsException("écriture de données non alignée")
        val buffer = if (from == 0 && data.size == length) data else data.copyOfRange(from, from + length)
        device.write(absolute / bs, buffer, length / bs)
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

    /** Position et longueur de l'ensemble d'entrées portant ce nom (comparé en majuscules). */
    private fun findSet(dirData: ByteArray, key: String, upcase: CharArray): Pair<Int, Int>? {
        var i = 0
        while (i + 32 <= dirData.size) {
            val kind = dirData[i].toInt() and 0xFF
            if (kind == 0x00) return null
            if (kind != 0x85) {
                i += 32
                continue
            }
            val length = 32 * ((dirData[i + 1].toInt() and 0xFF) + 1)
            if (i + length > dirData.size) return null
            val units = dirData[i + 32 + 3].toInt() and 0xFF
            val raw = java.io.ByteArrayOutputStream()
            var k = i + 64
            while (k + 32 <= i + length) {
                if ((dirData[k].toInt() and 0xFF) == 0xC1) raw.write(dirData, k + 2, 30)
                k += 32
            }
            val name = String(raw.toByteArray(), Charsets.UTF_16LE).take(units)
            if (upcased(name, upcase) == key) return Pair(i, length)
            i += length
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
