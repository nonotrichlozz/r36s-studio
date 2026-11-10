// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio

import android.app.Application
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.usb.UsbDevice
import android.hardware.usb.UsbManager
import android.net.Uri
import android.os.Build
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import io.github.nonotrichlozz.r36sstudio.core.CancelToken
import io.github.nonotrichlozz.r36sstudio.core.ImageFormat
import io.github.nonotrichlozz.r36sstudio.core.ImageSource
import io.github.nonotrichlozz.r36sstudio.core.ImageTooLargeException
import io.github.nonotrichlozz.r36sstudio.core.Imaging
import io.github.nonotrichlozz.r36sstudio.core.NoMediumException
import io.github.nonotrichlozz.r36sstudio.core.OperationCancelled
import io.github.nonotrichlozz.r36sstudio.core.PartitionTable
import io.github.nonotrichlozz.r36sstudio.core.Phase
import io.github.nonotrichlozz.r36sstudio.core.ProgressListener
import io.github.nonotrichlozz.r36sstudio.core.ProgressMeter
import io.github.nonotrichlozz.r36sstudio.core.Safety
import io.github.nonotrichlozz.r36sstudio.core.SevenZipArchiveException
import io.github.nonotrichlozz.r36sstudio.core.SourceUnstableException
import io.github.nonotrichlozz.r36sstudio.core.UnsupportedImageException
import io.github.nonotrichlozz.r36sstudio.core.VerifyFailedException
import io.github.nonotrichlozz.r36sstudio.core.readFully
import io.github.nonotrichlozz.r36sstudio.usb.UsbCards
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.io.File
import java.io.FileInputStream
import java.io.IOException
import java.io.InputStream
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

sealed interface CardState {
    data object None : CardState
    data object Several : CardState
    data class NeedsPermission(val device: UsbDevice) : CardState
    data class Probing(val device: UsbDevice) : CardState
    data class Ready(val device: UsbDevice, val display: String, val sizeBytes: Long, val headHash: String) : CardState
    data class Problem(val message: String) : CardState
}

enum class LogKind { INFO, SUCCESS, ERROR, DETAIL }

data class LogLine(val time: String, val text: String, val kind: LogKind)

data class OpState(
    val title: String,
    val phase: String,
    val done: Long = 0,
    val total: Long = 0,
    val speed: Long = 0,
    val phaseStartMs: Long = System.currentTimeMillis(),
    val cancelling: Boolean = false,
)

/** D'où vient l'image à écrire : un fichier choisi (uri) ou un firmware téléchargé (file). */
data class FlashSource(
    val label: String,
    val uri: Uri?,
    val file: File?,
    val format: ImageFormat,
    val sizeBytes: Long,
)

sealed interface DialogState {
    data object None : DialogState
    data object FirmwarePicker : DialogState
    data class ConfirmFlash(val source: FlashSource, val cardDisplay: String, val cardBytes: Long) : DialogState
    data class Message(val text: String) : DialogState
}

data class UiState(
    val card: CardState = CardState.None,
    val op: OpState? = null,
    val log: List<LogLine> = emptyList(),
    val dialog: DialogState = DialogState.None,
)

class MainViewModel(application: Application) : AndroidViewModel(application) {

    private val app: Application = application
    private val usbManager = application.getSystemService(Context.USB_SERVICE) as UsbManager
    private val timeFormat = SimpleDateFormat("HH:mm:ss", Locale.FRANCE)

    private val _state = MutableStateFlow(UiState())
    val state: StateFlow<UiState> = _state

    private var job: Job? = null
    private var cancelToken = CancelToken()
    private var probeGeneration = 0

    // Clonage : la sauvegarde qu'on vient de faire, et l'empreinte du début de
    // la carte d'origine, pour refuser de la « restaurer » sur elle-même.
    private var lastBackupUri: Uri? = null
    private var lastBackupHeadHash: String? = null

    private val receiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            refreshCards(force = intent.action == ACTION_USB_PERMISSION)
        }
    }

    init {
        val filter = IntentFilter().apply {
            addAction(ACTION_USB_PERMISSION)
            addAction(UsbManager.ACTION_USB_DEVICE_ATTACHED)
            addAction(UsbManager.ACTION_USB_DEVICE_DETACHED)
        }
        ContextCompat.registerReceiver(application, receiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
        refreshCards()
    }

    override fun onCleared() {
        try {
            app.unregisterReceiver(receiver)
        } catch (ignored: Exception) {
        }
        cancelToken.cancelled = true
        OperationService.stop()
    }

    // ------------------------------------------------------------------
    // Détection de la carte
    // ------------------------------------------------------------------

    /**
     * `force` (bouton Rafraîchir, fin d'une opération) relit la carte même si
     * le lecteur n'a pas changé : on peut changer de carte sans débrancher
     * le lecteur, et Android ne prévient pas dans ce cas.
     */
    fun refreshCards(force: Boolean = false) {
        if (_state.value.op != null && job?.isActive == true && isCardOperation) return
        val devices = UsbCards.list(usbManager)
        when {
            devices.isEmpty() -> setCard(CardState.None)
            devices.size > 1 -> setCard(CardState.Several)
            else -> {
                val device = devices[0]
                if (!usbManager.hasPermission(device)) {
                    setCard(CardState.NeedsPermission(device))
                    return
                }
                val known = when (val current = _state.value.card) {
                    is CardState.Ready -> current.device
                    is CardState.Probing -> current.device
                    else -> null
                }
                if (!force && known != null && known.deviceName == device.deviceName) return
                probe(device)
            }
        }
    }

    /** Demandée seulement quand l'utilisateur appuie sur « Autoriser ». */
    fun requestPermission() {
        val card = _state.value.card as? CardState.NeedsPermission ?: return
        val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0
        val intent = Intent(ACTION_USB_PERMISSION).setPackage(app.packageName)
        usbManager.requestPermission(card.device, PendingIntent.getBroadcast(app, 0, intent, flags))
    }

    private fun setCard(card: CardState) {
        probeGeneration++
        _state.update { it.copy(card = card) }
    }

    private fun probe(device: UsbDevice) {
        val generation = ++probeGeneration
        _state.update { it.copy(card = CardState.Probing(device)) }
        viewModelScope.launch(Dispatchers.IO) {
            val result: CardState = try {
                UsbCards.open(usbManager, device).use { card ->
                    val size = card.block.sizeBytes
                    when (Safety.rejection(size)) {
                        Safety.Rejection.SIZE_UNKNOWN -> CardState.Problem(Strings.CARD_REJECTED_SIZE)
                        Safety.Rejection.TOO_LARGE -> CardState.Problem(Strings.CARD_REJECTED_LARGE)
                        null -> {
                            val head = ByteArray(minOf(Imaging.CHUNK_BYTES.toLong(), size).toInt())
                            card.block.read(0, head, head.size / card.block.blockSize)
                            val hash = Imaging.toHex(MessageDigest.getInstance("SHA-256").digest(head))
                            CardState.Ready(device, card.display, size, hash)
                        }
                    }
                }
            } catch (e: NoMediumException) {
                CardState.Problem(Strings.CARD_NO_MEDIUM_HINT)
            } catch (e: Exception) {
                CardState.Problem(Strings.ERROR_CARD_GONE)
            }
            if (generation == probeGeneration) _state.update { it.copy(card = result) }
        }
    }

    // ------------------------------------------------------------------
    // Fenêtres
    // ------------------------------------------------------------------

    fun openFirmwarePicker() {
        if (busy) return
        _state.update { it.copy(dialog = DialogState.FirmwarePicker) }
    }

    fun dismissDialog() {
        _state.update { it.copy(dialog = DialogState.None) }
    }

    private fun showMessage(text: String) {
        _state.update { it.copy(dialog = DialogState.Message(text)) }
    }

    private val busy: Boolean get() = _state.value.op != null

    @Volatile
    private var isCardOperation = false

    // ------------------------------------------------------------------
    // Choix d'un fichier image (installation ou restauration)
    // ------------------------------------------------------------------

    /** Vérifie ce qui peut l'être avant la fenêtre rouge : format, taille. */
    fun onImagePicked(uri: Uri) {
        if (busy) return
        val card = _state.value.card as? CardState.Ready
        if (card == null) {
            showMessage(Strings.ERROR_NO_CARD)
            return
        }
        viewModelScope.launch(Dispatchers.IO) {
            try {
                val (name, size) = queryNameAndSize(uri)
                val header = ByteArray(ImageSource.HEADER_BYTES)
                val read = openUri(uri).use { readFully(it, header) }
                val format = ImageSource.detectFormat(header.copyOf(read))
                when {
                    format == ImageFormat.SEVEN_ZIP -> showMessage(Strings.ERROR_SEVEN_ZIP)
                    read == 0 -> showMessage(Strings.ERROR_UNSUPPORTED)
                    format == ImageFormat.RAW && size > card.sizeBytes -> showMessage(Strings.errorTooLarge(card.sizeBytes))
                    uri == lastBackupUri && card.headHash == lastBackupHeadHash -> showMessage(Strings.ERROR_SAME_CARD)
                    else -> {
                        val source = FlashSource(name, uri, null, format, size)
                        _state.update { it.copy(dialog = DialogState.ConfirmFlash(source, card.display, card.sizeBytes)) }
                    }
                }
            } catch (e: Exception) {
                showMessage(Strings.ERROR_FILE_UNREADABLE)
            }
        }
    }

    private fun queryNameAndSize(uri: Uri): Pair<String, Long> {
        var name = uri.lastPathSegment ?: "image"
        var size = -1L
        app.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (nameIndex >= 0 && !cursor.isNull(nameIndex)) name = cursor.getString(nameIndex)
                if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) size = cursor.getLong(sizeIndex)
            }
        }
        return Pair(name, size)
    }

    private fun openUri(uri: Uri): InputStream =
        app.contentResolver.openInputStream(uri) ?: throw IOException("Fichier inaccessible")

    // ------------------------------------------------------------------
    // Téléchargement d'un firmware, puis fenêtre de confirmation
    // ------------------------------------------------------------------

    fun downloadFirmware(firmware: Firmware) {
        if (busy) return
        val card = _state.value.card as? CardState.Ready
        if (card == null) {
            showMessage(Strings.ERROR_NO_CARD)
            return
        }
        dismissDialog()
        startOperation(Strings.OP_DOWNLOAD, Strings.PHASE_DOWNLOAD, cardOperation = false) { token ->
            log(Strings.LOG_RESOLVING)
            val asset = Firmwares.resolve(firmware)
            log(Strings.logDownloading(asset.name))
            val directory = File(app.getExternalFilesDir(null) ?: app.filesDir, "Firmwares")
            val file = Firmwares.download(asset, directory, token, ProgressMeter(progressListener))
            log(Strings.LOG_DOWNLOAD_VERIFIED, LogKind.SUCCESS)
            log(Strings.logDetail(file.absolutePath), LogKind.DETAIL)
            val header = ByteArray(ImageSource.HEADER_BYTES)
            val read = FileInputStream(file).use { readFully(it, header) }
            val source = FlashSource(asset.name, null, file, ImageSource.detectFormat(header.copyOf(read)), file.length())
            // La confirmation n'est jamais sautée, même après un téléchargement automatique.
            val current = _state.value.card as? CardState.Ready
            if (current == null) {
                showMessage(Strings.ERROR_NO_CARD)
            } else {
                _state.update { it.copy(dialog = DialogState.ConfirmFlash(source, current.display, current.sizeBytes)) }
            }
        }
    }

    // ------------------------------------------------------------------
    // Flash (après la fenêtre rouge uniquement)
    // ------------------------------------------------------------------

    fun confirmFlash(dialog: DialogState.ConfirmFlash) {
        if (busy) return
        val card = _state.value.card as? CardState.Ready
        dismissDialog()
        if (card == null) {
            showMessage(Strings.ERROR_NO_CARD)
            return
        }
        val source = dialog.source
        startOperation(Strings.OP_FLASH, Strings.PHASE_WRITE, cardOperation = true, destructive = true) { token ->
            UsbCards.open(usbManager, card.device).use { usbCard ->
                // Le worker revérifie : la carte ouverte doit être celle qui a été confirmée.
                if (Safety.rejection(usbCard.block.sizeBytes) != null || usbCard.block.sizeBytes != dialog.cardBytes) {
                    throw IOException("La carte a changé depuis la confirmation")
                }
                // Même lecteur, mais la carte a pu être changée depuis : son début doit être celui relevé.
                val head = ByteArray(minOf(Imaging.CHUNK_BYTES.toLong(), usbCard.block.sizeBytes).toInt())
                usbCard.block.read(0, head, head.size / usbCard.block.blockSize)
                if (Imaging.toHex(MessageDigest.getInstance("SHA-256").digest(head)) != card.headHash) {
                    throw IOException("La carte a changé depuis la confirmation")
                }
                log(Strings.logDetail("${usbCard.display}, ${usbCard.block.blockCount} blocs de ${usbCard.block.blockSize} octets"), LogKind.DETAIL)
                val open: () -> InputStream = {
                    if (source.file != null) FileInputStream(source.file) else openUri(source.uri!!)
                }
                val written = Imaging.flash(open, source.sizeBytes, source.format, usbCard.block, token, progressListener)
                usbCard.block.flush()
                log(Strings.logFlashDone(written), LogKind.SUCCESS)
                log(Strings.LOG_CAN_REMOVE, LogKind.SUCCESS)
            }
        }
    }

    // ------------------------------------------------------------------
    // Sauvegarde (non destructrice : pas de fenêtre rouge)
    // ------------------------------------------------------------------

    fun suggestedBackupName(): String =
        "R36S_" + SimpleDateFormat("yyyy-MM-dd_HH-mm", Locale.FRANCE).format(Date()) + ".img.gz"

    fun canStartCardAction(): Boolean {
        if (busy) return false
        if (_state.value.card is CardState.Ready) return true
        showMessage(Strings.ERROR_NO_CARD)
        return false
    }

    fun startBackup(destination: Uri) {
        if (busy) return
        val card = _state.value.card as? CardState.Ready
        if (card == null) {
            showMessage(Strings.ERROR_NO_CARD)
            deleteDocument(destination)
            return
        }
        startOperation(
            Strings.OP_BACKUP,
            Strings.PHASE_READ,
            cardOperation = true,
            onFailure = { error ->
                if (error is SourceUnstableException) markUnstable(destination) else deleteDocument(destination)
            },
        ) { token ->
            UsbCards.open(usbManager, card.device).use { usbCard ->
                val block = usbCard.block
                val used = try {
                    PartitionTable.usedArea(block)
                } catch (e: IOException) {
                    null
                }
                val length = if (used != null && used.endBytes < block.sizeBytes) {
                    log(Strings.logBackupUsed(used.endBytes, block.sizeBytes))
                    used.endBytes
                } else {
                    log(Strings.logBackupWhole(block.sizeBytes))
                    block.sizeBytes
                }
                val opened = try {
                    app.contentResolver.openOutputStream(destination, "w")
                } catch (e: Exception) {
                    null
                }
                val output = opened ?: throw BackupWriteException()
                val hash = try {
                    Imaging.backup(block, length, output, token, progressListener)
                } catch (e: IOException) {
                    // Téléphone plein : ce n'est pas la carte qui est en cause.
                    val message = e.message ?: ""
                    if (message.contains("ENOSPC") || message.contains("No space")) throw BackupWriteException()
                    throw e
                }
                lastBackupUri = destination
                lastBackupHeadHash = card.headHash
                log(Strings.logBackupDone(length), LogKind.SUCCESS)
                log(Strings.logDetail("SHA-256 du contenu : $hash"), LogKind.DETAIL)
                log(Strings.LOG_BACKUP_NEXT)
            }
        }
    }

    private class BackupWriteException : IOException("Écriture de la sauvegarde impossible")

    private fun deleteDocument(uri: Uri) {
        try {
            DocumentsContract.deleteDocument(app.contentResolver, uri)
        } catch (ignored: Exception) {
        }
    }

    /** Une sauvegarde douteuse n'est jamais supprimée : elle est renommée. */
    private fun markUnstable(uri: Uri) {
        try {
            val (name, _) = queryNameAndSize(uri)
            DocumentsContract.renameDocument(app.contentResolver, uri, "$name.instable")
        } catch (ignored: Exception) {
        }
    }

    // ------------------------------------------------------------------
    // Exécution, progression, journal
    // ------------------------------------------------------------------

    private val progressListener = object : ProgressListener {
        override fun onPhase(phase: Phase) {
            val label = when (phase) {
                Phase.WRITE -> Strings.PHASE_WRITE
                Phase.VERIFY -> Strings.PHASE_VERIFY
                Phase.READ -> Strings.PHASE_READ
                Phase.VERIFY_SOURCE -> Strings.PHASE_VERIFY_SOURCE
            }
            when (phase) {
                Phase.WRITE -> log(Strings.LOG_FLASH_START)
                Phase.VERIFY -> log(Strings.LOG_VERIFY_START)
                Phase.READ -> log(Strings.LOG_BACKUP_START)
                Phase.VERIFY_SOURCE -> log(Strings.LOG_BACKUP_VERIFY)
            }
            _state.update { state ->
                state.copy(op = state.op?.copy(phase = label, done = 0, total = 0, speed = 0, phaseStartMs = System.currentTimeMillis()))
            }
        }

        override fun onProgress(done: Long, total: Long, bytesPerSecond: Long) {
            _state.update { state -> state.copy(op = state.op?.copy(done = done, total = total, speed = bytesPerSecond)) }
        }
    }

    private fun startOperation(
        title: String,
        phase: String,
        cardOperation: Boolean,
        destructive: Boolean = false,
        onFailure: (Throwable) -> Unit = {},
        body: (CancelToken) -> Unit,
    ) {
        val token = CancelToken()
        cancelToken = token
        isCardOperation = cardOperation
        // Le journal est vidé au démarrage d'une opération, jamais entre-temps.
        _state.update { it.copy(op = OpState(title, phase), log = emptyList()) }
        // Au mieux : si Android refuse, l'opération continue, mais il faut alors garder l'appli affichée.
        if (!OperationService.start(app, title)) log(Strings.LOG_NO_BACKGROUND)
        job = viewModelScope.launch(Dispatchers.IO) {
            try {
                body(token)
            } catch (e: Throwable) {
                try {
                    onFailure(e)
                } catch (ignored: Exception) {
                }
                if (e is OperationCancelled) {
                    log(if (destructive) Strings.LOG_CANCELLED_FLASH else Strings.LOG_CANCELLED, LogKind.ERROR)
                } else {
                    log(friendlyError(e), LogKind.ERROR)
                    val detail = e.message
                    if (!detail.isNullOrBlank()) log(Strings.logDetail("${e.javaClass.simpleName} : $detail"), LogKind.DETAIL)
                }
            } finally {
                OperationService.stop()
                isCardOperation = false
                _state.update { it.copy(op = null) }
                if (cardOperation) refreshCards(force = true)
            }
        }
    }

    fun cancel() {
        val op = _state.value.op ?: return
        if (op.cancelling) return
        cancelToken.cancelled = true
        _state.update { it.copy(op = it.op?.copy(cancelling = true)) }
        log(Strings.LOG_CANCELLING)
    }

    private fun friendlyError(e: Throwable): String = when (e) {
        is SevenZipArchiveException -> Strings.ERROR_SEVEN_ZIP
        is UnsupportedImageException -> Strings.ERROR_UNSUPPORTED
        is ImageTooLargeException -> Strings.errorTooLarge(e.cardBytes)
        is VerifyFailedException -> Strings.ERROR_VERIFY
        is SourceUnstableException -> Strings.ERROR_SOURCE_UNSTABLE
        is ChecksumMismatchException -> Strings.ERROR_CHECKSUM
        is NotEnoughSpaceException -> Strings.errorNoSpace(e.neededBytes)
        is BackupWriteException -> Strings.ERROR_BACKUP_WRITE
        is java.net.UnknownHostException, is java.net.SocketException, is java.net.SocketTimeoutException,
        is javax.net.ssl.SSLException -> Strings.ERROR_NETWORK
        is java.util.zip.ZipException, is org.tukaani.xz.XZIOException -> Strings.ERROR_UNSUPPORTED
        is IOException -> if (isCardOperation) Strings.ERROR_CARD_GONE else Strings.ERROR_NETWORK
        else -> Strings.ERROR_GENERIC
    }

    private fun log(text: String, kind: LogKind = LogKind.INFO) {
        val line = LogLine(synchronized(timeFormat) { timeFormat.format(Date()) }, text, kind)
        _state.update { it.copy(log = it.log + line) }
    }

    companion object {
        private const val ACTION_USB_PERMISSION = "io.github.nonotrichlozz.r36sstudio.USB_PERMISSION"
    }
}
