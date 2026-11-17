// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import java.io.IOException
import java.util.Calendar
import java.util.TimeZone

/** Système de fichiers illisible ou incohérent. Le message est montré tel quel dans le détail. */
class FsException(message: String) : IOException(message)

/** Ce système de fichiers existe mais n'est pas lisible ici (ext4, NTFS...). */
class UnsupportedFilesystemException(val fsName: String) : IOException("Système de fichiers non lisible : $fsName")

/**
 * Un fichier ou un dossier. `cluster`, `contiguous` et `dataLength` ne servent
 * qu'au lecteur qui l'a produit pour ouvrir le dossier.
 */
class FsEntry(
    val name: String,
    val isDirectory: Boolean,
    val sizeBytes: Long,
    val modifiedMillis: Long?,
    val hidden: Boolean,
    internal val cluster: Long,
    internal val contiguous: Boolean,
    internal val dataLength: Long,
)

/** Parcours en lecture seule. Aucune méthode n'écrit. */
abstract class FsVolume {
    abstract val fsName: String
    abstract val label: String
    abstract fun listRoot(): List<FsEntry>
    abstract fun list(dir: FsEntry): List<FsEntry>
}

/** Ce que l'on sait d'une partition sans l'ouvrir en entier. */
data class VolumeProbe(val fsName: String, val label: String, val readable: Boolean)

object Filesystems {

    /** Secteur de démarrage d'un volume FAT ou exFAT (sert aussi aux cartes sans table de partitions). */
    fun looksLikeFatOrExFatBootSector(sector: ByteArray): Boolean {
        if (sector.size < 512) return false
        if ((sector[510].toInt() and 0xFF) != 0x55 || (sector[511].toInt() and 0xFF) != 0xAA) return false
        if (String(sector, 3, 8, Charsets.ISO_8859_1) == "EXFAT   ") return true
        val jump = sector[0].toInt() and 0xFF
        if (jump != 0xEB && jump != 0xE9) return false
        val tag16 = String(sector, 54, 5, Charsets.ISO_8859_1)
        val tag32 = String(sector, 82, 5, Charsets.ISO_8859_1)
        return tag16 == "FAT12" || tag16 == "FAT16" || tag32 == "FAT32"
    }

    /** Reconnaît le système de fichiers de la partition. Ne lève jamais d'exception de lecture : `fsName` vaut alors « ? ». */
    fun probe(reader: VolumeReader): VolumeProbe {
        return try {
            val boot = reader.read(0, minOf(512L, reader.sizeBytes).toInt())
            when {
                boot.size >= 512 && String(boot, 3, 8, Charsets.ISO_8859_1) == "EXFAT   " ->
                    VolumeProbe("exFAT", "", readable = true)
                boot.size >= 512 && FatVolume.isFatBootSector(boot) ->
                    VolumeProbe("FAT", "", readable = true)
                boot.size >= 512 && String(boot, 3, 8, Charsets.ISO_8859_1) == "NTFS    " ->
                    VolumeProbe("NTFS", "", readable = false)
                else -> probeExt(reader)
            }
        } catch (e: IOException) {
            VolumeProbe("?", "", readable = false)
        }
    }

    private fun probeExt(reader: VolumeReader): VolumeProbe {
        if (reader.sizeBytes < 2048) return VolumeProbe("?", "", false)
        val sb = reader.read(1024, 136)
        if ((sb[56].toInt() and 0xFF) == 0x53 && (sb[57].toInt() and 0xFF) == 0xEF) {
            val label = String(sb, 120, 16, Charsets.UTF_8).substringBefore('\u0000')
            return VolumeProbe("ext4", label, readable = false)
        }
        return VolumeProbe("?", "", readable = false)
    }

    /** Ouvre la partition ; lève `UnsupportedFilesystemException` si on ne sait pas la lire. */
    @Throws(IOException::class)
    fun open(reader: VolumeReader): FsVolume {
        val probe = probe(reader)
        if (!probe.readable) throw UnsupportedFilesystemException(probe.fsName)
        return if (probe.fsName == "exFAT") ExFatVolume(reader) else FatVolume(reader)
    }

    /** Date locale ou UTC -> millisecondes, `null` si la date n'existe pas. */
    internal fun toMillis(
        year: Int, month: Int, day: Int, hour: Int, minute: Int, second: Int,
        utcOffsetQuarters: Int? = null,
    ): Long? {
        if (month !in 1..12 || day !in 1..31 || hour !in 0..23 || minute !in 0..59 || second !in 0..59) return null
        val calendar = Calendar.getInstance(if (utcOffsetQuarters != null) TimeZone.getTimeZone("UTC") else TimeZone.getDefault())
        calendar.isLenient = false
        return try {
            calendar.clear()
            calendar.set(year, month - 1, day, hour, minute, second)
            var millis = calendar.timeInMillis
            if (utcOffsetQuarters != null) millis -= utcOffsetQuarters * 15L * 60_000L
            millis
        } catch (e: IllegalArgumentException) {
            null
        }
    }
}
