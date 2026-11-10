// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.usb

import android.hardware.usb.UsbConstants
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbDeviceConnection
import android.hardware.usb.UsbEndpoint
import android.hardware.usb.UsbInterface
import android.hardware.usb.UsbManager
import io.github.nonotrichlozz.r36sstudio.core.BulkTransport
import io.github.nonotrichlozz.r36sstudio.core.NoMediumException
import io.github.nonotrichlozz.r36sstudio.core.ScsiBlockDevice
import java.io.Closeable
import java.io.IOException

/** Tuyaux USB d'un lecteur de carte, vus par `ScsiBlockDevice`. */
private class AndroidBulkTransport(
    private val connection: UsbDeviceConnection,
    private val usbInterface: UsbInterface,
    private val endpointIn: UsbEndpoint,
    private val endpointOut: UsbEndpoint,
) : BulkTransport {

    override fun bulkOut(data: ByteArray, offset: Int, length: Int): Int =
        connection.bulkTransfer(endpointOut, data, offset, length, TIMEOUT_MS)

    override fun bulkIn(data: ByteArray, offset: Int, length: Int): Int =
        connection.bulkTransfer(endpointIn, data, offset, length, TIMEOUT_MS)

    override fun resetRecovery() {
        // Bulk-Only Mass Storage Reset, puis CLEAR_FEATURE(ENDPOINT_HALT) sur les deux tuyaux.
        connection.controlTransfer(0x21, 0xFF, 0, usbInterface.id, null, 0, CONTROL_TIMEOUT_MS)
        connection.controlTransfer(0x02, 0x01, 0, endpointIn.address, null, 0, CONTROL_TIMEOUT_MS)
        connection.controlTransfer(0x02, 0x01, 0, endpointOut.address, null, 0, CONTROL_TIMEOUT_MS)
    }

    fun maxLun(): Int {
        val buffer = ByteArray(1)
        val n = connection.controlTransfer(0xA1, 0xFE, 0, usbInterface.id, buffer, 1, CONTROL_TIMEOUT_MS)
        return if (n == 1) (buffer[0].toInt() and 0x0F) else 0
    }

    companion object {
        // Une carte lente peut mettre plusieurs secondes à avaler un bloc.
        const val TIMEOUT_MS = 30_000
        const val CONTROL_TIMEOUT_MS = 5_000
    }
}

/** Une carte ouverte : à fermer après usage (relâche le lecteur). */
class UsbCard internal constructor(
    private val connection: UsbDeviceConnection,
    private val usbInterface: UsbInterface,
    val block: ScsiBlockDevice,
    val display: String,
) : Closeable {
    override fun close() {
        try {
            connection.releaseInterface(usbInterface)
        } catch (ignored: Exception) {
        }
        try {
            connection.close()
        } catch (ignored: Exception) {
        }
    }
}

object UsbCards {
    private const val SUBCLASS_SCSI = 6
    private const val PROTOCOL_BULK_ONLY = 0x50

    /** Lecteurs de carte / clés branchés sur le téléphone (stockage de masse USB). */
    fun list(manager: UsbManager): List<UsbDevice> =
        manager.deviceList.values.filter { findInterface(it) != null }.sortedBy { it.deviceName }

    private fun findInterface(device: UsbDevice): UsbInterface? {
        for (i in 0 until device.interfaceCount) {
            val candidate = device.getInterface(i)
            if (candidate.interfaceClass == UsbConstants.USB_CLASS_MASS_STORAGE &&
                candidate.interfaceProtocol == PROTOCOL_BULK_ONLY &&
                (candidate.interfaceSubclass == SUBCLASS_SCSI || candidate.interfaceSubclass == 0xFF ||
                    candidate.interfaceSubclass == 0)
            ) {
                return candidate
            }
        }
        return null
    }

    /**
     * Ouvre la carte (l'autorisation USB doit déjà être accordée). Sur un
     * lecteur à plusieurs fentes, prend la première qui contient une carte.
     */
    @Throws(IOException::class)
    fun open(manager: UsbManager, device: UsbDevice): UsbCard {
        val usbInterface = findInterface(device) ?: throw IOException("Ce n'est pas un lecteur de carte")
        var endpointIn: UsbEndpoint? = null
        var endpointOut: UsbEndpoint? = null
        for (i in 0 until usbInterface.endpointCount) {
            val endpoint = usbInterface.getEndpoint(i)
            if (endpoint.type != UsbConstants.USB_ENDPOINT_XFER_BULK) continue
            if (endpoint.direction == UsbConstants.USB_DIR_IN) {
                if (endpointIn == null) endpointIn = endpoint
            } else {
                if (endpointOut == null) endpointOut = endpoint
            }
        }
        if (endpointIn == null || endpointOut == null) throw IOException("Lecteur de carte non reconnu")

        val connection = manager.openDevice(device) ?: throw IOException("Impossible d'ouvrir le lecteur de carte")
        var ok = false
        try {
            // force = true : détache le pilote d'Android, qui tient sinon le lecteur.
            if (!connection.claimInterface(usbInterface, true)) {
                throw IOException("Le lecteur de carte est utilisé par une autre application")
            }
            val transport = AndroidBulkTransport(connection, usbInterface, endpointIn, endpointOut)
            val maxLun = transport.maxLun()
            var lastError: IOException? = null
            for (lun in 0..maxLun) {
                val block = ScsiBlockDevice(transport, lun)
                try {
                    block.init()
                } catch (e: IOException) {
                    lastError = e
                    continue
                }
                val name = listOf(block.vendor, block.product).filter { it.isNotBlank() }.joinToString(" ")
                val display = name.ifBlank { device.productName ?: "Carte SD" }
                ok = true
                return UsbCard(connection, usbInterface, block, display)
            }
            throw lastError ?: NoMediumException()
        } finally {
            if (!ok) {
                try {
                    connection.releaseInterface(usbInterface)
                } catch (ignored: Exception) {
                }
                connection.close()
            }
        }
    }
}
