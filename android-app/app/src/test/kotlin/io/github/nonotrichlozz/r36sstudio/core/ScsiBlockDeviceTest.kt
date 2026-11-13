// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.core

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.io.IOException

class ScsiBlockDeviceTest {

    @Test
    fun initReadsNameAndCapacity() {
        val reader = FakeUsbReader(ByteArray(4 * 1024 * 1024))
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        assertEquals(512, device.blockSize)
        assertEquals(8192L, device.blockCount)
        assertEquals(4L * 1024 * 1024, device.sizeBytes)
        assertEquals("Generic", device.vendor)
        assertEquals("Card Reader", device.product)
        assertTrue(device.removable)
    }

    @Test
    fun initWaitsThroughUnitAttention() {
        val reader = FakeUsbReader(ByteArray(1024 * 1024))
        reader.unitAttentionCount = 2
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        assertEquals(2048L, device.blockCount)
    }

    @Test
    fun emptyReaderIsReportedAsNoMedium() {
        val reader = FakeUsbReader(ByteArray(1024 * 1024))
        reader.mediumPresent = false
        try {
            ScsiBlockDevice(reader, sleep = {}).init()
            fail("NoMediumException attendue")
        } catch (e: NoMediumException) {
            // attendu, sans remise à zéro brutale du lecteur
            assertTrue(reader.clearHalts >= 1)
            assertEquals(0, reader.resets)
        }
    }

    @Test
    fun waitsWhenReaderFirstClaimsThereIsNoCard() {
        val reader = FakeUsbReader(ByteArray(1024 * 1024))
        reader.noMediumCount = 12
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        assertEquals(2048L, device.blockCount)
        assertTrue(reader.commands.contains(0x1B)) // on lui a demandé de démarrer
    }

    @Test
    fun acceptsReaderThatNeverSaysReadyButGivesCapacity() {
        val reader = FakeUsbReader(ByteArray(1024 * 1024))
        reader.neverReady = true
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        assertEquals(2048L, device.blockCount)
    }

    @Test
    fun readsAndWritesAcrossSeveralCommands() {
        val disk = patternBytes(4 * 1024 * 1024)
        val original = disk.copyOf()
        val reader = FakeUsbReader(disk)
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()

        // 3 Mio : beaucoup plus qu'une commande (64 Kio).
        val buffer = ByteArray(3 * 1024 * 1024)
        device.read(16, buffer, buffer.size / 512)
        assertArrayEquals(original.copyOfRange(16 * 512, 16 * 512 + buffer.size), buffer)

        val payload = patternBytes(3 * 1024 * 1024, seed = 99)
        device.write(32, payload, payload.size / 512)
        assertArrayEquals(payload, disk.copyOfRange(32 * 512, 32 * 512 + payload.size))
        // Rien n'a bougé avant la zone écrite.
        assertArrayEquals(original.copyOfRange(0, 32 * 512), disk.copyOfRange(0, 32 * 512))
    }

    @Test
    fun retriesAReadWhoseDataFailed() {
        val disk = patternBytes(1024 * 1024)
        val reader = FakeUsbReader(disk.copyOf())
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        reader.failDataReads = 2
        val buffer = ByteArray(64 * 1024)
        device.read(8, buffer, buffer.size / 512)
        assertArrayEquals(disk.copyOfRange(8 * 512, 8 * 512 + buffer.size), buffer)
        assertEquals(2, device.retries)
    }

    @Test
    fun givesUpWhenAReadKeepsFailing() {
        val reader = FakeUsbReader(ByteArray(1024 * 1024))
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        reader.failDataReads = 50
        try {
            device.read(0, ByteArray(512), 1)
            fail("IOException attendue")
        } catch (e: IOException) {
            assertTrue(e.message!!.contains("READ(10) bloc 0"))
        }
    }

    @Test
    fun reportsALockedCardWithoutRetrying() {
        val disk = patternBytes(1024 * 1024)
        val reader = FakeUsbReader(disk.copyOf())
        reader.writeProtected = true
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        try {
            device.write(0, ByteArray(4096), 8)
            fail("WriteProtectedException attendue")
        } catch (e: WriteProtectedException) {
            assertEquals(0, device.retries)
        }
        assertArrayEquals(disk, reader.disk) // rien n'a été écrit
        assertEquals(true, device.reportedWriteProtect())
    }

    @Test
    fun retriesAWriteWhenTheReaderDropsDuringTheSense() {
        // 2026-11-13 : « WRITE(10) bloc 2996224 a échoué (Le lecteur de carte
        // ne répond plus (envoi de la commande 0x03)) » -- abandon immédiat,
        // sans aucun nouvel essai.
        val reader = FakeUsbReader(ByteArray(2 * 1024 * 1024))
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        reader.failWritesCount = 1
        reader.dropSenseCount = 1
        val payload = patternBytes(256 * 1024, seed = 9)
        device.write(64, payload, payload.size / 512)
        assertArrayEquals(payload, reader.disk.copyOfRange(64 * 512, 64 * 512 + payload.size))
        assertEquals(1, device.retries)
    }

    @Test
    fun reviveGreetsTheReaderAgainAndKeepsTheCard() {
        val reader = FakeUsbReader(ByteArray(2 * 1024 * 1024))
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        val resetsBefore = reader.resets
        device.revive(0)
        device.useSmallCommands()
        assertEquals(resetsBefore + 1, reader.resets)
        assertEquals(4096L, device.blockCount)
        assertTrue(device.reducedCommands)
        val payload = patternBytes(128 * 1024, seed = 3)
        device.write(0, payload, payload.size / 512)
        assertArrayEquals(payload, reader.disk.copyOf(payload.size))
    }

    @Test
    fun fallsBackToSmallCommandsWhenBigWritesAreRefused() {
        val reader = FakeUsbReader(ByteArray(2 * 1024 * 1024))
        reader.maxWriteBlocks = 64
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        val payload = patternBytes(1024 * 1024, seed = 5)
        device.write(16, payload, payload.size / 512)
        assertArrayEquals(payload, reader.disk.copyOfRange(16 * 512, 16 * 512 + payload.size))
        assertTrue(device.reducedCommands)
        assertEquals(false, device.reportedWriteProtect())
    }

    @Test
    fun readsFromAReaderThatShortchangesBigCommands() {
        // Lecteur Acer du 2026-11-13 : rend 1023 blocs sur 1024 demandés.
        val disk = patternBytes(2 * 1024 * 1024)
        val reader = FakeUsbReader(disk.copyOf())
        reader.maxReadBlocks = 128
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        val buffer = ByteArray(1024 * 1024)
        device.read(0, buffer, buffer.size / 512)
        assertArrayEquals(disk.copyOf(buffer.size), buffer)
        assertEquals(0, device.retries)
        assertTrue(reader.commands.count { it == 0x28 } >= 16)
    }

    @Test
    fun fallsBackToSmallCommandsWhenNormalReadsComeUpShort() {
        val disk = patternBytes(1024 * 1024)
        val reader = FakeUsbReader(disk.copyOf())
        reader.maxReadBlocks = 64
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        val buffer = ByteArray(256 * 1024)
        device.read(8, buffer, buffer.size / 512)
        assertArrayEquals(disk.copyOfRange(8 * 512, 8 * 512 + buffer.size), buffer)
        assertTrue(device.reducedCommands)
    }

    @Test
    fun refusesAccessBeyondTheCard() {
        val reader = FakeUsbReader(ByteArray(1024 * 1024))
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        try {
            device.write(2047, ByteArray(1024), 2)
            fail("IOException attendue")
        } catch (e: IOException) {
            // attendu : aucune commande d'écriture n'a été envoyée
        }
        assertTrue(reader.commands.none { it == 0x2A })
    }

    @Test
    fun flushToleratesReadersWithoutCache() {
        val reader = FakeUsbReader(ByteArray(1024 * 1024))
        val device = ScsiBlockDevice(reader, sleep = {})
        device.init()
        device.flush() // le faux lecteur répond ILLEGAL REQUEST : ne doit pas lever
    }
}
