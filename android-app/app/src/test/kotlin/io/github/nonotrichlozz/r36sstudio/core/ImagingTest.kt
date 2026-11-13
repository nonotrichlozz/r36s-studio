// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.zip.GZIPInputStream
import java.util.zip.GZIPOutputStream
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

class ImagingTest {

    private fun gzip(data: ByteArray): ByteArray {
        val out = ByteArrayOutputStream()
        GZIPOutputStream(out).use { it.write(data) }
        return out.toByteArray()
    }

    // --- Formats ---

    @Test
    fun formatIsDetectedFromHeaderBytes() {
        assertEquals(ImageFormat.GZIP, ImageSource.detectFormat(gzip(ByteArray(10)).copyOf(8)))
        assertEquals(ImageFormat.XZ, ImageSource.detectFormat(byteArrayOf(0xFD.toByte(), 0x37, 0x7A, 0x58, 0x5A, 0x00, 0, 0)))
        assertEquals(ImageFormat.ZIP, ImageSource.detectFormat(byteArrayOf(0x50, 0x4B, 0x03, 0x04, 0, 0, 0, 0)))
        assertEquals(
            ImageFormat.SEVEN_ZIP,
            ImageSource.detectFormat(byteArrayOf(0x37, 0x7A, 0xBC.toByte(), 0xAF.toByte(), 0x27, 0x1C, 0, 0)),
        )
        assertEquals(ImageFormat.RAW, ImageSource.detectFormat(ByteArray(8)))
        assertEquals(ImageFormat.RAW, ImageSource.detectFormat(ByteArray(0)))
    }

    @Test
    fun sevenZipIsRefusedNotWritten() {
        try {
            ImageSource.openDecompressed(ByteArrayInputStream(ByteArray(8)), ImageFormat.SEVEN_ZIP)
            fail("SevenZipArchiveException attendue")
        } catch (e: SevenZipArchiveException) {
            // attendu
        }
    }

    @Test
    fun zipGivesItsImgEntry() {
        val image = patternBytes(5000)
        val out = ByteArrayOutputStream()
        ZipOutputStream(out).use { zip ->
            zip.putNextEntry(ZipEntry("lisezmoi.txt"))
            zip.write("bonjour".toByteArray())
            zip.closeEntry()
            zip.putNextEntry(ZipEntry("systeme.IMG"))
            zip.write(image)
            zip.closeEntry()
        }
        val read = ImageSource.openDecompressed(ByteArrayInputStream(out.toByteArray()), ImageFormat.ZIP).use { it.readBytes() }
        assertArrayEquals(image, read)
    }

    // --- Flash ---

    @Test
    fun flashWritesAndVerifiesRawImage() {
        val image = patternBytes(3 * 1024 * 1024 + 512)
        val card = MemoryBlockDevice(ByteArray(8 * 1024 * 1024))
        val listener = RecordingListener()
        val written = Imaging.flash({ ByteArrayInputStream(image) }, image.size.toLong(), ImageFormat.RAW, card, CancelToken(), listener)
        assertEquals(image.size.toLong(), written)
        assertArrayEquals(image, card.data.copyOf(image.size))
        assertEquals(listOf(Phase.WRITE, Phase.VERIFY), listener.phases)
        assertEquals(image.size.toLong(), listener.lastDone)
        assertEquals(image.size.toLong(), listener.lastTotal)
        assertTrue(card.flushes >= 1)
    }

    @Test
    fun flashDecompressesGzipAndPadsLastBlock() {
        val image = patternBytes(1024 * 1024 + 100) // ne tombe pas sur une limite de bloc
        val compressed = gzip(image)
        val card = MemoryBlockDevice(ByteArray(4 * 1024 * 1024))
        java.util.Arrays.fill(card.data, 0x55)
        val written = Imaging.flash({ ByteArrayInputStream(compressed) }, compressed.size.toLong(), ImageFormat.GZIP, card, CancelToken(), RecordingListener())
        assertEquals(1024L * 1024 + 512, written)
        assertArrayEquals(image, card.data.copyOf(image.size))
        // Fin du dernier bloc complétée par des zéros, et rien au-delà n'est touché.
        for (i in image.size until written.toInt()) assertEquals(0, card.data[i].toInt())
        assertEquals(0x55, card.data[written.toInt()].toInt())
    }

    @Test
    fun flashRefusesImageLargerThanCard() {
        val image = patternBytes(3 * 1024 * 1024)
        val card = MemoryBlockDevice(ByteArray(2 * 1024 * 1024))
        try {
            Imaging.flash({ ByteArrayInputStream(image) }, image.size.toLong(), ImageFormat.RAW, card, CancelToken(), RecordingListener())
            fail("ImageTooLargeException attendue")
        } catch (e: ImageTooLargeException) {
            assertEquals(2L * 1024 * 1024, e.cardBytes)
        }
    }

    @Test
    fun flashDetectsCardThatDoesNotKeepWhatWasWritten() {
        val image = patternBytes(2 * 1024 * 1024)
        val card = object : MemoryBlockDevice(ByteArray(4 * 1024 * 1024)) {
            override fun read(lba: Long, buffer: ByteArray, blocks: Int) {
                super.read(lba, buffer, blocks)
                if (lba == 2048L) buffer[10] = (buffer[10].toInt() xor 1).toByte()
            }
        }
        try {
            Imaging.flash({ ByteArrayInputStream(image) }, image.size.toLong(), ImageFormat.RAW, card, CancelToken(), RecordingListener())
            fail("VerifyFailedException attendue")
        } catch (e: VerifyFailedException) {
            assertEquals(1024L * 1024 + 10, e.offset)
        }
    }

    @Test
    fun flashStopsWhenCancelled() {
        val image = patternBytes(2 * 1024 * 1024)
        val card = MemoryBlockDevice(ByteArray(4 * 1024 * 1024))
        val token = CancelToken()
        token.cancelled = true
        try {
            Imaging.flash({ ByteArrayInputStream(image) }, image.size.toLong(), ImageFormat.RAW, card, token, RecordingListener())
            fail("OperationCancelled attendue")
        } catch (e: OperationCancelled) {
            assertArrayEquals(ByteArray(4 * 1024 * 1024), card.data)
        }
    }

    // --- Sauvegarde ---

    @Test
    fun backupProducesGzipOfTheUsedArea() {
        val content = patternBytes(4 * 1024 * 1024)
        val card = MemoryBlockDevice(content.copyOf())
        val out = ByteArrayOutputStream()
        val listener = RecordingListener()
        val length = 2L * 1024 * 1024 + 512
        Imaging.backup(card, length, out, CancelToken(), listener)
        val restored = GZIPInputStream(ByteArrayInputStream(out.toByteArray())).use { it.readBytes() }
        assertArrayEquals(content.copyOf(length.toInt()), restored)
        assertEquals(listOf(Phase.READ, Phase.VERIFY_SOURCE), listener.phases)
        assertArrayEquals(content, card.data) // la carte source n'est jamais modifiée
    }

    @Test
    fun backupDetectsUnstableSource() {
        var reads = 0
        val card = object : MemoryBlockDevice(patternBytes(2 * 1024 * 1024)) {
            override fun read(lba: Long, buffer: ByteArray, blocks: Int) {
                super.read(lba, buffer, blocks)
                reads++
                if (reads == 3) buffer[0] = (buffer[0].toInt() xor 0x40).toByte()
            }
        }
        try {
            Imaging.backup(card, 2L * 1024 * 1024, ByteArrayOutputStream(), CancelToken(), RecordingListener())
            fail("SourceUnstableException attendue")
        } catch (e: SourceUnstableException) {
            // attendu
        }
    }

    // --- Table de partitions ---

    private fun mbrCard(sizeBytes: Int, partitions: List<Triple<Int, Int, Int>>): MemoryBlockDevice {
        val data = ByteArray(sizeBytes)
        val buffer = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        partitions.forEachIndexed { index, (type, start, sectors) ->
            val base = 446 + index * 16
            data[base + 4] = type.toByte()
            buffer.putInt(base + 8, start)
            buffer.putInt(base + 12, sectors)
        }
        data[510] = 0x55
        data[511] = 0xAA.toByte()
        return MemoryBlockDevice(data)
    }

    @Test
    fun usedAreaStopsAtEndOfLastPartition() {
        val card = mbrCard(8 * 1024 * 1024, listOf(Triple(0x0C, 2048, 2048), Triple(0x83, 4096, 4096)))
        val used = PartitionTable.usedArea(card)
        assertEquals(UsedArea(8192L * 512, gpt = false, partitions = 2), used)
    }

    @Test
    fun usedAreaIsUnknownWithoutTable() {
        assertNull(PartitionTable.usedArea(MemoryBlockDevice(ByteArray(1024 * 1024))))
    }

    @Test
    fun usedAreaIsUnknownWhenPartitionExceedsCard() {
        val card = mbrCard(1024 * 1024, listOf(Triple(0x0C, 2048, 100000)))
        assertNull(PartitionTable.usedArea(card))
    }

    @Test
    fun usedAreaReadsGpt() {
        val card = mbrCard(4 * 1024 * 1024, listOf(Triple(0xEE, 1, 8191)))
        val data = card.data
        val buffer = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
        "EFI PART".toByteArray(Charsets.US_ASCII).copyInto(data, 512)
        buffer.putLong(512 + 72, 2)
        buffer.putInt(512 + 80, 4)
        buffer.putInt(512 + 84, 128)
        val entry0 = 2 * 512
        data[entry0] = 1 // GUID de type non nul
        buffer.putLong(entry0 + 32, 2048)
        buffer.putLong(entry0 + 40, 4095)
        val entry1 = entry0 + 128
        data[entry1] = 1
        buffer.putLong(entry1 + 32, 4096)
        buffer.putLong(entry1 + 40, 6143)
        assertEquals(UsedArea(6144L * 512, gpt = true, partitions = 2), PartitionTable.usedArea(card))
    }

    // --- Garde-fou ---

    @Test
    fun safetyRefusesUnknownAndHugeSizes() {
        assertEquals(Safety.Rejection.SIZE_UNKNOWN, Safety.rejection(0))
        assertEquals(Safety.Rejection.TOO_LARGE, Safety.rejection(Safety.DEFAULT_MAX_BYTES + 1))
        assertNull(Safety.rejection(64L * 1024 * 1024 * 1024))
    }

    // --- Reprise quand le lecteur décroche (2026-11-13) ---

    /** Carte qui « décroche » une fois arrivée à un bloc donné, comme le lecteur du 2026-11-13. */
    private class DroppingDevice(data: ByteArray, private val failAtLba: Long) : MemoryBlockDevice(data) {
        var dead = false

        override fun write(lba: Long, buffer: ByteArray, blocks: Int) {
            if (dead || lba >= failAtLba) {
                dead = true
                throw java.io.IOException("Le lecteur de carte ne répond plus (envoi de la commande 0x03)")
            }
            super.write(lba, buffer, blocks)
        }
    }

    @Test
    fun flashResumesAtTheFailedBlockAfterRecovery() {
        val image = patternBytes(5 * Imaging.CHUNK_BYTES)
        val disk = ByteArray(8 * Imaging.CHUNK_BYTES)
        val dropping = DroppingDevice(disk, failAtLba = (3L * Imaging.CHUNK_BYTES) / 512)
        var recoveries = 0
        val written = Imaging.flash(
            { ByteArrayInputStream(image) },
            image.size.toLong(),
            ImageFormat.RAW,
            dropping,
            CancelToken(),
            RecordingListener(),
        ) {
            recoveries++
            MemoryBlockDevice(disk) // même carte, lecteur rouvert
        }
        assertEquals(1, recoveries)
        assertEquals(image.size.toLong(), written)
        assertArrayEquals(image, disk.copyOf(image.size))
    }

    @Test
    fun flashGivesUpWhenRecoveryFails() {
        val image = patternBytes(2 * Imaging.CHUNK_BYTES)
        val dropping = DroppingDevice(ByteArray(4 * Imaging.CHUNK_BYTES), failAtLba = 0)
        var recoveries = 0
        try {
            Imaging.flash({ ByteArrayInputStream(image) }, image.size.toLong(), ImageFormat.RAW, dropping, CancelToken(), RecordingListener()) {
                recoveries++
                null
            }
            fail("IOException attendue")
        } catch (e: java.io.IOException) {
            assertTrue(e.message!!.contains("ne répond plus"))
        }
        assertEquals(1, recoveries)
    }

    @Test
    fun flashStopsAfterTooManyRecoveries() {
        val image = patternBytes(2 * Imaging.CHUNK_BYTES)
        val disk = ByteArray(4 * Imaging.CHUNK_BYTES)
        var recoveries = 0
        try {
            Imaging.flash({ ByteArrayInputStream(image) }, image.size.toLong(), ImageFormat.RAW, DroppingDevice(disk, 0), CancelToken(), RecordingListener()) {
                recoveries++
                DroppingDevice(disk, 0)
            }
            fail("IOException attendue")
        } catch (e: java.io.IOException) {
            // attendu
        }
        assertEquals(Imaging.MAX_RECOVERIES, recoveries)
    }

    @Test
    fun recoveryOntoAnotherCardIsRefused() {
        val image = patternBytes(2 * Imaging.CHUNK_BYTES)
        try {
            Imaging.flash(
                { ByteArrayInputStream(image) },
                image.size.toLong(),
                ImageFormat.RAW,
                DroppingDevice(ByteArray(4 * Imaging.CHUNK_BYTES), 0),
                CancelToken(),
                RecordingListener(),
            ) { MemoryBlockDevice(ByteArray(8 * Imaging.CHUNK_BYTES)) }
            fail("IOException attendue")
        } catch (e: java.io.IOException) {
            assertTrue(e.message!!.contains("même carte"))
        }
    }

    @Test
    fun writeProtectedIsNeverRecovered() {
        val device = object : MemoryBlockDevice(ByteArray(4 * Imaging.CHUNK_BYTES)) {
            override fun write(lba: Long, buffer: ByteArray, blocks: Int) {
                throw WriteProtectedException("7/27")
            }
        }
        var recoveries = 0
        try {
            Imaging.flash({ ByteArrayInputStream(ByteArray(1024)) }, 1024, ImageFormat.RAW, device, CancelToken(), RecordingListener()) {
                recoveries++
                device
            }
            fail("WriteProtectedException attendue")
        } catch (e: WriteProtectedException) {
            // attendu
        }
        assertEquals(0, recoveries)
    }

    // --- Effacement ---

    @Test
    fun eraseZeroesHeadAndTailOnly() {
        val size = 64 * Imaging.CHUNK_BYTES
        val disk = patternBytes(size)
        val original = disk.copyOf()
        val device = MemoryBlockDevice(disk)
        val listener = RecordingListener()
        val erased = Imaging.erase(device, CancelToken(), listener)
        assertEquals(Imaging.ERASE_HEAD_BYTES + Imaging.ERASE_TAIL_BYTES, erased)
        val head = Imaging.ERASE_HEAD_BYTES.toInt()
        val tail = size - Imaging.ERASE_TAIL_BYTES.toInt()
        assertTrue((0 until head).all { disk[it] == 0.toByte() })
        assertTrue((tail until size).all { disk[it] == 0.toByte() })
        assertArrayEquals(original.copyOfRange(head, tail), disk.copyOfRange(head, tail))
        assertEquals(listOf(Phase.WRITE, Phase.VERIFY), listener.phases)
        assertEquals(1, device.flushes)
    }

    @Test
    fun eraseOfSmallCardCoversItOnce() {
        val size = 8 * Imaging.CHUNK_BYTES
        val disk = patternBytes(size)
        val erased = Imaging.erase(MemoryBlockDevice(disk), CancelToken(), RecordingListener())
        assertEquals(size.toLong(), erased)
        assertTrue(disk.all { it == 0.toByte() })
    }

    @Test
    fun eraseDetectsACardThatKeepsItsData() {
        val device = object : MemoryBlockDevice(patternBytes(64 * Imaging.CHUNK_BYTES)) {
            override fun write(lba: Long, buffer: ByteArray, blocks: Int) {
                // Carte défaillante : accepte l'écriture sans rien changer.
            }
        }
        try {
            Imaging.erase(device, CancelToken(), RecordingListener())
            fail("VerifyFailedException attendue")
        } catch (e: VerifyFailedException) {
            assertEquals(0L, e.offset)
        }
    }
}
