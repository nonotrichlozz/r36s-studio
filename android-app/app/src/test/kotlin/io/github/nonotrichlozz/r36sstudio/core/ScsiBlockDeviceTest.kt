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

        // 3 Mio : plus qu'une commande (512 Kio) et plus qu'un transfert USB (64 Kio).
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
