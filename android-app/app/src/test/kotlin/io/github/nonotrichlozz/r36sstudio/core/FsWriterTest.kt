// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.ByteArrayInputStream
import java.io.IOException

class FsWriterTest {

    private class Scene(val img: ExFatImage, val roms: ExFatImage.Dir, val oldContent: ByteArray)

    private fun scene(romsClusters: Int = 2): Scene {
        val img = ExFatImage("EASYROMS")
        val roms = img.mkdir(img.root, "roms", romsClusters)
        val old = patternBytes(1500, seed = 3)
        img.addFile(roms, "old.bin", old)
        return Scene(img, roms, old)
    }

    private fun check(bytes: ByteArray): ExFatChecker = ExFatChecker(bytes).run()

    private fun writer(device: BlockDevice, size: Int) = ExFatWriter(device, 0, size.toLong())

    private val noProgress = CopyProgress { _, _, _ -> }

    private fun copy(device: BlockDevice, size: Int, path: List<String>, name: String, data: ByteArray, cancel: CancelToken = CancelToken()): ExFatWriter.Added =
        writer(device, size).copyFile(path, name, data.size.toLong(), { ByteArrayInputStream(data) }, cancel, noProgress)

    @Test
    fun theCheckerAcceptsTheBuilderImage() {
        val s = scene()
        val c = check(s.img.bytes)
        assertEquals(emptyList<String>(), c.errors)
        assertEquals(emptyList<Long>(), c.leaks)
    }

    @Test
    fun theCheckerCatchesRealDamage() {
        val s = scene()
        val bytes = s.img.bytes.copyOf()
        val volume = ExFatVolume(VolumeReader(MemoryBlockDevice(bytes), 0, bytes.size.toLong()))
        val old = volume.list(volume.listRoot().first { it.name == "roms" }).first { it.name == "old.bin" }
        val bit = (volume.clustersOf(old).first() - 2).toInt()
        // un cluster de old.bin redevient « libre » dans la table d'allocation
        val at = s.img.clusterOffset(volume.bitmapCluster.toInt()) + bit / 8
        bytes[at] = (bytes[at].toInt() and (1 shl (bit % 8)).inv()).toByte()
        assertTrue(check(bytes).errors.any { it.contains("marqué libre") })

        // une somme de contrôle d'entrée qui ne correspond plus
        val bytes2 = s.img.bytes.copyOf()
        val rootData = volume.readDirBytes(volume.rootRef)
        var i = 0
        while ((rootData[i].toInt() and 0xFF) != 0x85) i += 32
        bytes2[s.img.clusterOffset(2) + i + 2] = (bytes2[s.img.clusterOffset(2) + i + 2] + 1).toByte()
        assertTrue(check(bytes2).errors.any { it.contains("somme de contrôle") })
    }

    @Test
    fun copyingAContiguousFileLeavesAConsistentVolumeAndReadsBackIdentically() {
        val s = scene()
        val device = MemoryBlockDevice(s.img.bytes.copyOf())
        val before = device.data.copyOf()
        val data = patternBytes(5000, seed = 11)
        val w = writer(device, device.data.size)
        val added = w.copyFile(listOf("roms"), "Super Game (Europe).zip", data.size.toLong(), { ByteArrayInputStream(data) }, CancelToken(), noProgress)
        w.verify(added, { ByteArrayInputStream(data) }, CancelToken(), noProgress)

        val c = check(device.data)
        assertEquals(emptyList<String>(), c.errors)
        assertEquals(emptyList<Long>(), c.leaks)

        val volume = ExFatVolume(VolumeReader(device, 0, device.data.size.toLong()))
        val files = volume.list(volume.listRoot().first { it.name == "roms" })
        assertEquals(listOf("old.bin", "Super Game (Europe).zip"), files.map { it.name })
        assertEquals(5000L, files.first { it.name == "Super Game (Europe).zip" }.sizeBytes)

        // L'ancien fichier est intact, octet pour octet.
        val old = files.first { it.name == "old.bin" }
        val oldBytes = java.io.ByteArrayOutputStream()
        volume.forEachFileChunk(old, 4096) { oldBytes.write(it) }
        assertTrue(s.oldContent.contentEquals(oldBytes.toByteArray()))

        // Seuls ont changé : les clusters du nouveau fichier, la table d'allocation, la place dans le dossier.
        val newEntry = files.first { it.name == "Super Game (Europe).zip" }
        val allowed = HashSet<Int>()
        for (cl in volume.clustersOf(newEntry)) for (b in 0 until 512) allowed.add(s.img.clusterOffset(cl.toInt()) + b)
        for (b in 0 until 50) allowed.add(s.img.clusterOffset(6) + b)
        val rom = volume.refOf(volume.listRoot().first { it.name == "roms" })
        val dirCluster = volume.dirClusterList(rom).first().toInt()
        for (b in 0 until 1024) allowed.add(s.img.clusterOffset(dirCluster) + b)
        for (i in before.indices) if (before[i] != device.data[i]) assertTrue("octet $i modifié hors de la zone prévue", i in allowed)
    }

    @Test
    fun aFragmentedFileUsesAFatChainAndStaysConsistent() {
        val s = scene()
        // Plus aucun morceau libre de plus d'un cluster : le fichier de 10 clusters sera en 10 morceaux.
        s.img.freeOnly((100..118 step 2).toSet())
        val device = MemoryBlockDevice(s.img.bytes.copyOf())
        val data = patternBytes(5000, seed = 5)
        val w = writer(device, device.data.size)
        val added = w.copyFile(listOf("roms"), "fragmente.bin", data.size.toLong(), { ByteArrayInputStream(data) }, CancelToken(), noProgress)
        w.verify(added, { ByteArrayInputStream(data) }, CancelToken(), noProgress)
        val c = check(device.data)
        assertEquals(emptyList<String>(), c.errors)
    }

    @Test
    fun aCompressedUpcaseTableGivesTheSameNameHashAsTheFormatter() {
        // Les vraies cartes ont une table compressée : un hachage faux rendrait le fichier introuvable sous Linux.
        val img = ExFatImage("EASYROMS", compressedUpcase = true)
        val roms = img.mkdir(img.root, "roms", 2)
        img.addFile(roms, "old.bin", patternBytes(700))
        assertEquals(emptyList<String>(), check(img.bytes).errors)
        val device = MemoryBlockDevice(img.bytes.copyOf())
        val data = patternBytes(3000, seed = 8)
        val w = writer(device, device.data.size)
        val added = w.copyFile(listOf("roms"), "Mario Kart (Europe) (Fr,De).zip", data.size.toLong(), { ByteArrayInputStream(data) }, CancelToken(), noProgress)
        w.verify(added, { ByteArrayInputStream(data) }, CancelToken(), noProgress)
        assertEquals(emptyList<String>(), check(device.data).errors)
        // Un nom en minuscules et le même en majuscules sont le même fichier pour exFAT.
        try {
            copy(device, device.data.size, listOf("roms"), "MARIO KART (EUROPE) (FR,DE).ZIP", patternBytes(5))
            fail("même nom, casse différente")
        } catch (e: AlreadyOnCardException) {
            // attendu
        }
    }

    @Test
    fun emptyFileIsAddedWithoutAnyCluster() {
        val s = scene()
        val device = MemoryBlockDevice(s.img.bytes.copyOf())
        val w = writer(device, device.data.size)
        val added = w.copyFile(listOf("roms"), "vide.txt", 0, { ByteArrayInputStream(ByteArray(0)) }, CancelToken(), noProgress)
        w.verify(added, { ByteArrayInputStream(ByteArray(0)) }, CancelToken(), noProgress)
        assertEquals(emptyList<String>(), check(device.data).errors)
    }

    @Test
    fun filesGoIntoTheRootToo() {
        val s = scene()
        val device = MemoryBlockDevice(s.img.bytes.copyOf())
        copy(device, device.data.size, emptyList(), "readme.txt", patternBytes(100))
        assertEquals(emptyList<String>(), check(device.data).errors)
    }

    @Test
    fun invalidCharactersInTheNameAreReplaced() {
        assertEquals("a_b_c_.gba", ExFatWriter.sanitizeName("a:b*c?.gba"))
        assertEquals("fichier", ExFatWriter.sanitizeName("..."))
        assertEquals(255, ExFatWriter.sanitizeName("x".repeat(300) + ".zip").length)
        assertTrue(ExFatWriter.sanitizeName("x".repeat(300) + ".zip").endsWith(".zip"))
    }

    @Test
    fun anExistingNameIsNeverReplacedEvenWithDifferentCase() {
        val s = scene()
        val device = MemoryBlockDevice(s.img.bytes.copyOf())
        val before = device.data.copyOf()
        try {
            copy(device, device.data.size, listOf("roms"), "OLD.BIN", patternBytes(10))
            fail("un fichier existant ne doit jamais être remplacé")
        } catch (e: AlreadyOnCardException) {
            // attendu
        }
        assertTrue(before.contentEquals(device.data))
    }

    @Test
    fun notEnoughSpaceWritesNothing() {
        val s = scene()
        s.img.freeOnly((100..104).toSet()) // 5 clusters libres = 2560 octets
        val device = MemoryBlockDevice(s.img.bytes.copyOf())
        val before = device.data.copyOf()
        try {
            copy(device, device.data.size, listOf("roms"), "trop gros.bin", patternBytes(5000))
            fail("pas assez de place")
        } catch (e: NotEnoughSpaceOnCardException) {
            // attendu
        }
        assertTrue(before.contentEquals(device.data))
    }

    @Test
    fun aFullDirectoryWritesNothing() {
        val img = ExFatImage()
        val dir = img.mkdir(img.root, "plein", 1) // 16 entrées de 32 octets
        for (n in 1..5) img.addFile(dir, "f$n.bin", patternBytes(10, seed = n)) // 5 x 3 entrées = 15 : il en reste 1
        val device = MemoryBlockDevice(img.bytes.copyOf())
        val before = device.data.copyOf()
        try {
            copy(device, device.data.size, listOf("plein"), "un de trop.bin", patternBytes(10))
            fail("le dossier est plein")
        } catch (e: DirectoryFullException) {
            // attendu
        }
        assertTrue(before.contentEquals(device.data))
    }

    @Test
    fun cancelledBeforeStartWritesNothing() {
        val s = scene()
        val device = MemoryBlockDevice(s.img.bytes.copyOf())
        val before = device.data.copyOf()
        val token = CancelToken().apply { cancelled = true }
        try {
            copy(device, device.data.size, listOf("roms"), "x.bin", patternBytes(100), token)
            fail("annulé")
        } catch (e: OperationCancelled) {
            // attendu
        }
        assertTrue(before.contentEquals(device.data))
    }

    @Test
    fun cancelledAfterTheDataLeavesTheVolumeCleanAndTheFileAbsent() {
        val s = scene()
        val device = MemoryBlockDevice(s.img.bytes.copyOf())
        val token = CancelToken()
        try {
            writer(device, device.data.size).copyFile(
                listOf("roms"), "x.bin", 5000, { ByteArrayInputStream(patternBytes(5000)) }, token,
            ) { _, _, _ -> token.cancelled = true }
            fail("annulé")
        } catch (e: OperationCancelled) {
            // attendu
        }
        val c = check(device.data)
        assertEquals(emptyList<String>(), c.errors)
        assertEquals(emptyList<Long>(), c.leaks) // la table d'allocation n'a pas encore été touchée
        val volume = ExFatVolume(VolumeReader(device, 0, device.data.size.toLong()))
        assertEquals(listOf("old.bin"), volume.list(volume.listRoot().first { it.name == "roms" }).map { it.name })
    }

    /** Appareil qui lâche après un nombre donné d'écritures : branchement arraché, plantage, batterie. */
    private class FailingDevice(bytes: ByteArray, val failAt: Int) : MemoryBlockDevice(bytes) {
        var writes = 0
        override fun write(lba: Long, buffer: ByteArray, blocks: Int) {
            if (writes++ >= failAt) throw IOException("lecteur débranché")
            super.write(lba, buffer, blocks)
        }
    }

    @Test
    fun interruptedAtAnyWriteNeverDamagesTheVolume() {
        for (variant in 0..1) {
            val base = scene()
            if (variant == 1) base.img.freeOnly((100..118 step 2).toSet()) // aussi avec une chaîne FAT
            val image = base.img.bytes
            var total = -1
            // Premier passage sans panne : combien d'écritures au total ?
            run {
                val d = FailingDevice(image.copyOf(), Int.MAX_VALUE)
                copy(d, image.size, listOf("roms"), "jeu.bin", patternBytes(5000, seed = 9))
                total = d.writes
            }
            for (failAt in 0 until total) {
                val d = FailingDevice(image.copyOf(), failAt)
                try {
                    copy(d, image.size, listOf("roms"), "jeu.bin", patternBytes(5000, seed = 9))
                    fail("la panne aurait dû interrompre la copie (écriture $failAt)")
                } catch (e: IOException) {
                    // attendu
                }
                val c = check(d.data)
                assertEquals("variante $variant, panne à l'écriture $failAt : ${c.errors}", emptyList<String>(), c.errors)
                // L'ancien fichier est toujours là et intact.
                val volume = ExFatVolume(VolumeReader(d, 0, d.data.size.toLong()))
                val names = volume.list(volume.listRoot().first { it.name == "roms" }).map { it.name }
                assertTrue("old.bin a disparu (panne à $failAt)", "old.bin" in names)
            }
        }
    }

    @Test
    fun verifyCatchesACorruptedCopy() {
        val s = scene()
        val device = MemoryBlockDevice(s.img.bytes.copyOf())
        val data = patternBytes(5000, seed = 2)
        val w = writer(device, device.data.size)
        val added = w.copyFile(listOf("roms"), "jeu.bin", data.size.toLong(), { ByteArrayInputStream(data) }, CancelToken(), noProgress)
        val volume = ExFatVolume(VolumeReader(device, 0, device.data.size.toLong()))
        val entry = volume.list(volume.listRoot().first { it.name == "roms" }).first { it.name == "jeu.bin" }
        device.data[s.img.clusterOffset(volume.clustersOf(entry).first().toInt()) + 100] = 0x42 // un octet qui change
        try {
            w.verify(added, { ByteArrayInputStream(data) }, CancelToken(), noProgress)
            fail("la relecture doit voir la différence")
        } catch (e: CopyVerifyFailedException) {
            assertTrue(e.message!!.contains("contenu différent"))
        }
    }

    @Test
    fun partitionOffsetAndLargeBlocksWork() {
        // Même scénario avec la partition décalée dans la carte et des blocs de 4096 octets.
        val s = scene()
        val partition = s.img.bytes
        val offset = 8 * 4096
        val disk = ByteArray(offset + partition.size + 4096 * 3)
        partition.copyInto(disk, offset)
        val device = MemoryBlockDevice(disk, blockSize = 4096)
        val data = patternBytes(7000, seed = 4)
        val w = ExFatWriter(device, offset.toLong(), partition.size.toLong())
        val added = w.copyFile(listOf("roms"), "jeu.bin", data.size.toLong(), { ByteArrayInputStream(data) }, CancelToken(), noProgress)
        w.verify(added, { ByteArrayInputStream(data) }, CancelToken(), noProgress)
        assertEquals(emptyList<String>(), check(disk.copyOfRange(offset, offset + partition.size)).errors)
    }
}
