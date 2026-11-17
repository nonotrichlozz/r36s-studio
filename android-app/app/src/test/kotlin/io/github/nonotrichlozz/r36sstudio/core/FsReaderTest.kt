// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.util.Calendar
import java.util.TimeZone

class FsReaderTest {

    private fun open(bytes: ByteArray, device: BlockDevice = MemoryBlockDevice(bytes)): FsVolume =
        Filesystems.open(VolumeReader(device, 0, bytes.size.toLong()))

    private fun names(entries: List<FsEntry>) = entries.map { it.name }.sorted()

    // --- FAT ------------------------------------------------------------------

    @Test
    fun fat16ReadsShortAndLongNamesAndDates() {
        val img = FatImage(16, "MON DISQUE")
        val roms = img.mkdir(img.root, "roms", "ROMS")
        img.add(roms, "Super Mario World (Europe).sfc", "SUPERM~1SFC", 0x20, 0, 1234)
        img.add(img.root, null, "README  TXT", 0x20, 0, 10, caseFlags = 0x18)

        val volume = open(img.bytes)
        assertEquals("FAT16", volume.fsName)
        assertEquals("MON DISQUE", volume.label)
        val root = volume.listRoot()
        assertEquals(listOf("readme.txt", "roms"), names(root))
        val dir = root.first { it.name == "roms" }
        assertTrue(dir.isDirectory)
        val files = volume.list(dir)
        assertEquals(listOf("Super Mario World (Europe).sfc"), names(files))
        assertEquals(1234L, files[0].sizeBytes)
        val c = Calendar.getInstance().apply { timeInMillis = files[0].modifiedMillis!! }
        assertEquals(listOf(2026, Calendar.NOVEMBER, 17, 14, 30, 10), listOf(
            c.get(Calendar.YEAR), c.get(Calendar.MONTH), c.get(Calendar.DAY_OF_MONTH),
            c.get(Calendar.HOUR_OF_DAY), c.get(Calendar.MINUTE), c.get(Calendar.SECOND),
        ))
    }

    @Test
    fun fat32DirectorySpreadOverSeveralClustersIsReadCompletely() {
        val img = FatImage(32, "EASYROMS")
        for (n in 1..14) {
            img.add(img.root, "Jeu %02d – Édition spéciale longue.zip".format(n), "JEU%02d~1ZIP".format(n), 0x20, 0, n)
        }
        val volume = open(img.bytes)
        assertEquals("FAT32", volume.fsName)
        val root = volume.listRoot()
        assertEquals(14, root.size)
        assertTrue(root.any { it.name == "Jeu 07 – Édition spéciale longue.zip" && it.sizeBytes == 7L })
    }

    @Test
    fun fat32SubfolderDoesNotShowDotEntries() {
        val img = FatImage(32)
        val sub = img.mkdir(img.root, "Game Boy Advance", "GAMEBO~1", capacity = 40, spread = true)
        img.add(sub, "Zelda.gba", "ZELDA   GBA", 0x20, 0, 4096)
        val volume = open(img.bytes)
        val dir = volume.listRoot().single()
        assertEquals("Game Boy Advance", dir.name)
        assertEquals(listOf("Zelda.gba"), names(volume.list(dir)))
    }

    @Test
    fun fatChainThatLoopsRaisesInsteadOfHanging() {
        val img = FatImage(32)
        img.setFat(8, 2) // racine : 2 -> 4 -> 6 -> 8 -> 2
        val volume = open(img.bytes)
        try {
            volume.listRoot()
            fail("une chaîne qui boucle doit lever FsException")
        } catch (e: FsException) {
            assertTrue(e.message!!.contains("boucle"))
        }
    }

    // --- exFAT ----------------------------------------------------------------

    @Test
    fun exFatReadsLabelFoldersLongNamesAndUtcDates() {
        val img = ExFatImage("EASYROMS")
        val snes = img.mkdir(img.root, "snes")
        img.add(snes, "Pokémon – Version Rouge.gb", cluster = 300, size = 1048576)
        img.add(img.root, "readme.txt", size = 12)

        val volume = open(img.bytes)
        assertEquals("exFAT", volume.fsName)
        assertEquals("EASYROMS", volume.label)
        val root = volume.listRoot()
        assertEquals(listOf("readme.txt", "snes"), names(root))
        val files = volume.list(root.first { it.name == "snes" })
        assertEquals(listOf("Pokémon – Version Rouge.gb"), names(files))
        assertEquals(1048576L, files[0].sizeBytes)
        // 14:30:10 avec un décalage de +1 h = 13:30:10 UTC
        val utc = Calendar.getInstance(TimeZone.getTimeZone("UTC")).apply { timeInMillis = files[0].modifiedMillis!! }
        assertEquals(listOf(2026, Calendar.NOVEMBER, 17, 13, 30, 10), listOf(
            utc.get(Calendar.YEAR), utc.get(Calendar.MONTH), utc.get(Calendar.DAY_OF_MONTH),
            utc.get(Calendar.HOUR_OF_DAY), utc.get(Calendar.MINUTE), utc.get(Calendar.SECOND),
        ))
    }

    @Test
    fun exFatTruncatedNameRaises() {
        val img = ExFatImage()
        img.add(img.root, "court.txt", nameUnitsOverride = 40)
        val volume = open(img.bytes)
        try {
            volume.listRoot()
            fail("un nom tronqué doit lever FsException")
        } catch (e: FsException) {
            assertTrue(e.message!!.contains("tronqué"))
        }
    }

    @Test
    fun exFatChainThatLoopsRaises() {
        val img = ExFatImage()
        img.setFatEntry(4, 2) // racine : 2 -> 4 -> 2
        val volume = open(img.bytes)
        try {
            volume.listRoot()
            fail("une chaîne qui boucle doit lever FsException")
        } catch (e: FsException) {
            assertTrue(e.message!!.contains("invalide"))
        }
    }

    // --- Table de partitions --------------------------------------------------

    private fun put32(b: ByteArray, o: Int, v: Long) { for (k in 0..3) b[o + k] = (v shr (8 * k)).toByte() }
    private fun put64(b: ByteArray, o: Int, v: Long) { for (k in 0..7) b[o + k] = (v shr (8 * k)).toByte() }

    private fun mbrEntry(disk: ByteArray, slot: Int, type: Int, start: Long, sectors: Long) {
        val base = 446 + slot * 16
        disk[base + 4] = type.toByte()
        put32(disk, base + 8, start)
        put32(disk, base + 12, sectors)
    }

    @Test
    fun mbrCardWithFatAndExt4PartitionsIsProbedAndOnlyFatIsReadable() {
        val fat = FatImage(16, "BOOT")
        val disk = ByteArray(8 * 1024 * 1024)
        disk[510] = 0x55; disk[511] = 0xAA.toByte()
        val fatSectors = fat.bytes.size / 512L
        mbrEntry(disk, 0, 0x0C, 2048, fatSectors)
        val ext4Start = 2048 + fatSectors + 100
        mbrEntry(disk, 1, 0x83, ext4Start, 1000)
        fat.bytes.copyInto(disk, 2048 * 512)
        disk[(ext4Start * 512 + 1080).toInt()] = 0x53
        disk[(ext4Start * 512 + 1081).toInt()] = 0xEF.toByte()
        "ROOTFS".toByteArray().copyInto(disk, (ext4Start * 512 + 1024 + 120).toInt())

        val device = MemoryBlockDevice(disk)
        val parts = PartitionList.read(device)
        assertEquals(listOf(1, 2), parts.map { it.number })

        val first = Filesystems.probe(VolumeReader(device, parts[0].startBytes, parts[0].sizeBytes))
        assertEquals("FAT", first.fsName)
        assertTrue(first.readable)
        val second = Filesystems.probe(VolumeReader(device, parts[1].startBytes, parts[1].sizeBytes))
        assertEquals("ext4", second.fsName)
        assertEquals("ROOTFS", second.label)
        assertFalse(second.readable)
        try {
            Filesystems.open(VolumeReader(device, parts[1].startBytes, parts[1].sizeBytes))
            fail("une partition ext4 n'est pas lisible ici")
        } catch (e: UnsupportedFilesystemException) {
            assertEquals("ext4", e.fsName)
        }
        assertEquals("BOOT", Filesystems.open(VolumeReader(device, parts[0].startBytes, parts[0].sizeBytes)).label)
    }

    @Test
    fun gptCardListsItsPartitionsWithNames() {
        val disk = ByteArray(4 * 1024 * 1024)
        disk[510] = 0x55; disk[511] = 0xAA.toByte()
        mbrEntry(disk, 0, 0xEE, 1, 8191)
        "EFI PART".toByteArray().copyInto(disk, 512)
        put64(disk, 512 + 72, 2)
        put32(disk, 512 + 80, 4)
        put32(disk, 512 + 84, 128)
        val entry = 1024
        disk[entry] = 1 // GUID de type non nul
        put64(disk, entry + 32, 2048)
        put64(disk, entry + 40, 4095)
        "EASYROMS".toByteArray(Charsets.UTF_16LE).copyInto(disk, entry + 56)

        val parts = PartitionList.read(MemoryBlockDevice(disk))
        assertEquals(1, parts.size)
        assertEquals("EASYROMS", parts[0].tableName)
        assertEquals(2048L * 512, parts[0].startBytes)
        assertEquals(2048L * 512, parts[0].sizeBytes)
    }

    @Test
    fun cardWithoutPartitionTableIsOneVolume() {
        val parts = PartitionList.read(MemoryBlockDevice(FatImage(16).bytes))
        assertEquals(1, parts.size)
        assertEquals(0L, parts[0].startBytes)
    }

    @Test
    fun cardWithNothingReadableListsNoPartition() {
        assertTrue(PartitionList.read(MemoryBlockDevice(ByteArray(1024 * 1024))).isEmpty())
    }

    // --- Lecture seule --------------------------------------------------------

    private class CountingDevice(bytes: ByteArray) : MemoryBlockDevice(bytes) {
        var writes = 0
        override fun write(lba: Long, buffer: ByteArray, blocks: Int) {
            writes++
            super.write(lba, buffer, blocks)
        }
    }

    @Test
    fun browsingNeverWritesToTheCard() {
        val img = ExFatImage("EASYROMS")
        val snes = img.mkdir(img.root, "snes")
        img.add(snes, "a.sfc", cluster = 10, size = 5)
        val before = img.bytes.copyOf()
        val device = CountingDevice(img.bytes)
        val reader = VolumeReader(device, 0, img.bytes.size.toLong())
        assertNotNull(Filesystems.probe(reader))
        val volume = Filesystems.open(reader)
        volume.list(volume.listRoot().first { it.isDirectory })
        PartitionList.read(device)
        assertEquals(0, device.writes)
        assertEquals(0, device.flushes)
        assertTrue(before.contentEquals(img.bytes))
    }

    @Test
    fun readOnlyWrapperRefusesWrites() {
        val bytes = ByteArray(4096) { 1 }
        val device = CountingDevice(bytes)
        val wrapper = ReadOnlyBlockDevice(device)
        try {
            wrapper.write(0, ByteArray(512), 1)
            fail("l'écriture doit être refusée")
        } catch (e: ReadOnlyViolation) {
            // attendu
        }
        wrapper.flush()
        assertEquals(0, device.writes)
        assertEquals(0, device.flushes)
        assertTrue(bytes.all { it.toInt() == 1 })
    }
}
