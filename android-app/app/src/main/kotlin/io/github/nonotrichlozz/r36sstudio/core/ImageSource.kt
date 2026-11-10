// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import org.tukaani.xz.XZInputStream
import java.io.BufferedInputStream
import java.io.FilterInputStream
import java.io.IOException
import java.io.InputStream
import java.util.zip.GZIPInputStream
import java.util.zip.ZipInputStream

enum class ImageFormat { RAW, GZIP, XZ, ZIP, SEVEN_ZIP }

/** Archive .7z : à décompresser d'abord (même règle que la version ordinateur). */
class SevenZipArchiveException : IOException("Archive 7-Zip")

class UnsupportedImageException(message: String) : IOException(message)

object ImageSource {
    const val HEADER_BYTES = 8

    /**
     * Format décidé sur les premiers octets du fichier, jamais sur son nom :
     * un .7z renommé en .img serait sinon écrit tel quel sur la carte.
     */
    fun detectFormat(header: ByteArray): ImageFormat {
        fun starts(vararg magic: Int): Boolean {
            if (header.size < magic.size) return false
            for (i in magic.indices) {
                if ((header[i].toInt() and 0xFF) != magic[i]) return false
            }
            return true
        }
        return when {
            starts(0x1F, 0x8B) -> ImageFormat.GZIP
            starts(0xFD, 0x37, 0x7A, 0x58, 0x5A, 0x00) -> ImageFormat.XZ
            starts(0x50, 0x4B, 0x03, 0x04) -> ImageFormat.ZIP
            starts(0x37, 0x7A, 0xBC, 0xAF, 0x27, 0x1C) -> ImageFormat.SEVEN_ZIP
            else -> ImageFormat.RAW
        }
    }

    /** Flux décompressé à la volée, sans fichier temporaire. */
    @Throws(IOException::class)
    fun openDecompressed(raw: InputStream, format: ImageFormat): InputStream {
        return when (format) {
            ImageFormat.RAW -> raw
            ImageFormat.GZIP -> GZIPInputStream(raw, 64 * 1024)
            ImageFormat.XZ -> XZInputStream(BufferedInputStream(raw, 64 * 1024))
            ImageFormat.ZIP -> {
                val zip = ZipInputStream(BufferedInputStream(raw, 64 * 1024))
                while (true) {
                    val entry = zip.nextEntry ?: break
                    if (!entry.isDirectory && entry.name.lowercase().endsWith(".img")) return zip
                }
                zip.close()
                throw UnsupportedImageException("Aucun fichier .img dans cette archive .zip")
            }
            ImageFormat.SEVEN_ZIP -> throw SevenZipArchiveException()
        }
    }
}

/** Compte les octets réellement lus dans le fichier source : base de la progression. */
class CountingInputStream(inner: InputStream) : FilterInputStream(inner) {
    @Volatile
    var count: Long = 0
        private set

    override fun read(): Int {
        val value = super.read()
        if (value >= 0) count++
        return value
    }

    override fun read(b: ByteArray, off: Int, len: Int): Int {
        val n = super.read(b, off, len)
        if (n > 0) count += n
        return n
    }

    override fun skip(n: Long): Long {
        val skipped = super.skip(n)
        if (skipped > 0) count += skipped
        return skipped
    }
}

/** Remplit `buffer` autant que possible ; renvoie le nombre d'octets lus (0 = fin du flux). */
@Throws(IOException::class)
fun readFully(input: InputStream, buffer: ByteArray): Int {
    var total = 0
    while (total < buffer.size) {
        val n = input.read(buffer, total, buffer.size - total)
        if (n < 0) break
        total += n
    }
    return total
}
