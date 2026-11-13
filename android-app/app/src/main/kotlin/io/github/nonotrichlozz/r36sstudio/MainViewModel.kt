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
import io.github.nonotrichlozz.r36sstudio.core.BlockDevice
import io.github.nonotrichlozz.r36sstudio.core.CancelToken
import io.github.nonotrichlozz.r36sstudio.core.CardRecovery
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
import io.github.nonotrichlozz.r36sstudio.core.ScsiBlockDevice
import io.github.nonotrichlozz.r36sstudio.core.SevenZipArchiveException
import io.github.nonotrichlozz.r36sstudio.core.SourceUnstableException
import io.github.nonotrichlozz.r36sstudio.core.UnsupportedImageException
import io.github.nonotrichlozz.r36sstudio.core.VerifyFailedException
import io.github.nonotrichlozz.r36sstudio.core.WriteProtectedException
import io.github.nonotrichlozz.r36sstudio.core.readFully
import io.github.nonotrichlozz.r36sstudio.usb.UsbCard
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
    data class Ready(
        val device: UsbDevice,
        val display: String,
        val sizeBytes: Long,
        val headHash: String,
        val writeProtected: Boolean = false,
        val detail: String = "",
    ) : CardState
    data class Problem(val message: String, val detail: String = "") : CardState
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
    data class ConfirmErase(val cardDisplay: String, val cardBytes: Long) : DialogState
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

    // ATTENTION, ordre d'initialisation : tout champ utilisé par `refreshCards()`
    // doit être déclaré AVANT le bloc `init` ci-dessous, qui l'appelle. Un champ
    // déclaré plus bas vaut encore `null` à ce moment-là (plantage au lancement
    // de la construction 6ec8da0, 2026-11-11 : `synchronized(sessionLock)`).
    private val sessionLock = Any()
    private var session: UsbCard? = null
    private var sessionDeviceName: String? = null

    /** Remettre le lecteur à zéro à l'ouverture ; coupé si l'essai sans remise à zéro lève le verrouillage. */
    @Volatile
    private var openWithReset = true

    @Volatile
    private var isCardOperation = false

    private var updateFallbackTried = false

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
        // En premier, et à l'abri du reste : une version cassée doit toujours
        // pouvoir se réparer toute seule par la mise à jour suivante.
        checkForUpdate()
        try {
            ContextCompat.registerReceiver(application, receiver, filter, ContextCompat.RECEIVER_NOT_EXPORTED)
        } catch (e: Exception) {
            reportInternalError(e)
        }
        refreshCards()
        viewModelScope.launch {
            Updater.failure.collect { detail ->
                if (detail != null) {
                    // Statut 3 : la demande d'Android a été refusée, fermée ou laissée sans réponse.
                    val refused = detail.startsWith("statut 3")
                    log(Strings.logDetail(detail), LogKind.DETAIL)
                    // Un seul second essai par lancement, par l'installateur du téléphone.
                    if (!updateFallbackTried) {
                        updateFallbackTried = true
                        if (Updater.installWithSystemInstaller(app)) {
                            log(Strings.LOG_UPDATE_SECOND_TRY)
                            return@collect
                        }
                    }
                    log(if (refused) Strings.ERROR_UPDATE_REFUSED else Strings.ERROR_UPDATE, LogKind.ERROR)
                }
            }
        }
    }

    // ------------------------------------------------------------------
    // Mise à jour automatique, une fois par lancement
    // ------------------------------------------------------------------

    private fun checkForUpdate() {
        viewModelScope.launch(Dispatchers.IO) {
            // Lancé depuis `init` : laisser l'objet finir de se construire.
            kotlinx.coroutines.delay(300)
            val info = Updater.check() ?: return@launch
            // Jamais par-dessus une opération déjà lancée entre-temps.
            if (busy) return@launch
            startOperation(Strings.OP_UPDATE, Strings.PHASE_DOWNLOAD, cardOperation = false, networkOperation = true) { token ->
                log(Strings.logUpdateFound(info.build))
                val apk = try {
                    Updater.download(app, info, token, ProgressMeter(progressListener))
                } catch (e: OperationCancelled) {
                    throw e
                } catch (e: Exception) {
                    log(Strings.ERROR_UPDATE_DOWNLOAD, LogKind.ERROR)
                    log(Strings.logDetail("${e.javaClass.simpleName} : ${e.message}"), LogKind.DETAIL)
                    return@startOperation
                }
                log(Strings.LOG_UPDATE_INSTALLING)
                Updater.install(app, apk)
                log(Strings.LOG_UPDATE_CONFIRM)
            }
        }
    }

    override fun onCleared() {
        try {
            app.unregisterReceiver(receiver)
        } catch (ignored: Exception) {
        }
        cancelToken.cancelled = true
        OperationService.stop()
        closeSession()
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
        try {
            refreshCardsUnguarded(force)
        } catch (e: Exception) {
            reportInternalError(e)
        }
    }

    /** Une erreur imprévue s'affiche dans le bandeau au lieu de fermer l'appli. */
    private fun reportInternalError(e: Exception) {
        val detail = e.javaClass.simpleName + " : " + (e.message ?: "") + " @ " + (e.stackTrace.firstOrNull()?.toString() ?: "?")
        _state.update { it.copy(card = CardState.Problem(Strings.ERROR_GENERIC, detail)) }
    }

    private fun refreshCardsUnguarded(force: Boolean) {
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
        closeSession()
        _state.update { it.copy(card = card) }
    }

    // Le lecteur est gardé ouvert tant qu'il reste branché. Le relâcher entre
    // deux opérations le rendrait à Android, qui se remet aussitôt à lire la
    // carte ; le lui reprendre au milieu d'une de ses commandes laisse le
    // lecteur dans un état incohérent (échec du 2026-11-11 : carte détectée,
    // puis « ne répond plus » à l'opération suivante).
    private fun closeSession() {
        synchronized(sessionLock) {
            session?.close()
            session = null
            sessionDeviceName = null
        }
    }

    /** Session sur ce lecteur ; la carte est relue (taille, présence) à chaque appel. */
    private fun acquire(device: UsbDevice): UsbCard = synchronized(sessionLock) {
        val current = session
        if (current != null && sessionDeviceName == device.deviceName) {
            try {
                current.block.init()
                return@synchronized current
            } catch (e: IOException) {
                // Session abîmée : on repart d'une ouverture complète.
            }
        }
        session?.close()
        session = null
        sessionDeviceName = null
        val opened = UsbCards.open(usbManager, device, reset = openWithReset)
        session = opened
        sessionDeviceName = device.deviceName
        opened
    }

    private fun probe(device: UsbDevice) {
        val generation = ++probeGeneration
        _state.update { it.copy(card = CardState.Probing(device)) }
        viewModelScope.launch(Dispatchers.IO) {
            val result: CardState = try {
                acquire(device).let { card ->
                    val size = card.block.sizeBytes
                    when (Safety.rejection(size)) {
                        Safety.Rejection.SIZE_UNKNOWN -> CardState.Problem(Strings.CARD_REJECTED_SIZE)
                        Safety.Rejection.TOO_LARGE -> CardState.Problem(Strings.CARD_REJECTED_LARGE)
                        null -> {
                            val head = ByteArray(minOf(Imaging.CHUNK_BYTES.toLong(), size).toInt())
                            card.block.read(0, head, head.size / card.block.blockSize)
                            val hash = Imaging.toHex(MessageDigest.getInstance("SHA-256").digest(head))
                            // Le lecteur croit-il la carte verrouillée, avant toute écriture ?
                            var locked = card.block.reportedWriteProtect()
                            var detail = ""
                            if (locked == true) {
                                // Essai croisé : on rend le lecteur à Android, on le
                                // reprend SANS remise à zéro, et on repose la question.
                                val first = if (openWithReset) "avec remise à zéro" else "sans remise à zéro"
                                closeSession()
                                Thread.sleep(2500)
                                openWithReset = !openWithReset
                                val second = try {
                                    acquire(device).block.reportedWriteProtect()
                                } catch (e: IOException) {
                                    null
                                }
                                val secondLabel = if (openWithReset) "avec remise à zéro" else "sans remise à zéro"
                                detail = "carte verrouillée selon le lecteur : oui $first, ${yesNo(second)} $secondLabel"
                                if (second != false) openWithReset = !openWithReset // pas mieux : on revient au réglage d'origine
                                locked = second ?: true
                                acquire(device) // session valide quel que soit le résultat
                            }
                            CardState.Ready(device, card.display, size, hash, writeProtected = locked == true, detail = detail)
                        }
                    }
                }
            } catch (e: NoMediumException) {
                closeSession()
                CardState.Problem(Strings.CARD_NO_MEDIUM_HINT, probeDetail(device, e))
            } catch (e: Exception) {
                closeSession()
                CardState.Problem(Strings.ERROR_CARD_GONE, probeDetail(device, e))
            }
            if (generation == probeGeneration) _state.update { it.copy(card = result) }
        }
    }

    private fun yesNo(value: Boolean?): String = when (value) {
        true -> "oui"
        false -> "non"
        null -> "pas de réponse"
    }

    /** Ligne brute pour le diagnostic : jamais dans le message principal. */
    private fun probeDetail(device: UsbDevice, e: Exception): String =
        String.format(
            Locale.ROOT,
            "USB %04x:%04x — %s : %s",
            device.vendorId,
            device.productId,
            e.javaClass.simpleName,
            e.message ?: "",
        )

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
            acquire(card.device).let { usbCard ->
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
                val recover: CardRecovery = { e -> reconnectCard(card.device, e) }
                val written = try {
                    Imaging.flash(open, source.sizeBytes, source.format, usbCard.block, token, progressListener, recover)
                } catch (e: WriteProtectedException) {
                    val announced = when (usbCard.block.reportedWriteProtect()) {
                        true -> "oui"
                        false -> "non"
                        null -> "pas de réponse"
                    }
                    log(Strings.logDetail("lecteur : protection en écriture annoncée = $announced ; petites commandes essayées = ${usbCard.block.reducedCommands}"), LogKind.DETAIL)
                    throw e
                }
                // Après une reprise, la session est peut-être un nouveau lecteur ouvert.
                val block = currentBlock() ?: usbCard.block
                if (block.reducedCommands) log(Strings.logDetail("écriture par petites commandes (lecteur capricieux)"), LogKind.DETAIL)
                block.flush()
                if (block.retries > 0) log(Strings.logDetail("${block.retries} commande(s) recommencée(s)"), LogKind.DETAIL)
                log(Strings.logFlashDone(written), LogKind.SUCCESS)
                log(Strings.LOG_CAN_REMOVE, LogKind.SUCCESS)
            }
        }
    }

    // ------------------------------------------------------------------
    // Effacer la carte (après la fenêtre rouge uniquement)
    // ------------------------------------------------------------------

    fun askErase() {
        if (!canStartCardAction()) return
        val card = _state.value.card as? CardState.Ready ?: return
        _state.update { it.copy(dialog = DialogState.ConfirmErase(card.display, card.sizeBytes)) }
    }

    fun confirmErase(dialog: DialogState.ConfirmErase) {
        if (busy) return
        val card = _state.value.card as? CardState.Ready
        dismissDialog()
        if (card == null) {
            showMessage(Strings.ERROR_NO_CARD)
            return
        }
        startOperation(Strings.OP_ERASE, Strings.PHASE_ERASE, cardOperation = true, destructive = true) { token ->
            acquire(card.device).let { usbCard ->
                // Même contrôle que pour l'installation : la carte ouverte est celle confirmée.
                if (Safety.rejection(usbCard.block.sizeBytes) != null || usbCard.block.sizeBytes != dialog.cardBytes) {
                    throw IOException("La carte a changé depuis la confirmation")
                }
                val head = ByteArray(minOf(Imaging.CHUNK_BYTES.toLong(), usbCard.block.sizeBytes).toInt())
                usbCard.block.read(0, head, head.size / usbCard.block.blockSize)
                if (Imaging.toHex(MessageDigest.getInstance("SHA-256").digest(head)) != card.headHash) {
                    throw IOException("La carte a changé depuis la confirmation")
                }
                log(Strings.LOG_ERASE_START)
                log(Strings.logDetail("${usbCard.display}, ${usbCard.block.blockCount} blocs de ${usbCard.block.blockSize} octets"), LogKind.DETAIL)
                val erased = Imaging.erase(usbCard.block, token, progressListener) { e -> reconnectCard(card.device, e) }
                log(Strings.logDetail("${Strings.formatSize(erased)} remis à zéro (début et fin de la carte)"), LogKind.DETAIL)
                log(Strings.LOG_ERASE_DONE, LogKind.SUCCESS)
            }
        }
    }

    // ------------------------------------------------------------------
    // Reprise quand le lecteur décroche en pleine écriture
    // ------------------------------------------------------------------

    private fun currentBlock(): ScsiBlockDevice? = synchronized(sessionLock) { session?.block }

    /**
     * Le lecteur ne répond plus (2026-11-13 : « WRITE(10) bloc 2996224 a
     * échoué », réinstallation d'Arch R depuis le téléphone). D'abord sans
     * rendre le lecteur à Android : remise à zéro et nouvel accueil ; sinon
     * réouverture complète. La reprise continue par petites commandes. La
     * relecture finale reste la preuve que la carte est juste.
     */
    private fun reconnectCard(device: UsbDevice, cause: IOException): BlockDevice? {
        log(Strings.LOG_RECONNECTING)
        log(Strings.logDetail("${cause.javaClass.simpleName} : ${cause.message}"), LogKind.DETAIL)
        val current = currentBlock()
        if (current != null) {
            try {
                current.revive(RECONNECT_SETTLE_MS)
                current.useSmallCommands()
                log(Strings.LOG_RECONNECTED, LogKind.SUCCESS)
                log(Strings.logDetail("lecteur remis en état sans le relâcher"), LogKind.DETAIL)
                return current
            } catch (e: IOException) {
                log(Strings.logDetail("remise en état sans relâcher : ${e.message}"), LogKind.DETAIL)
            }
        }
        for (attempt in 0 until RECONNECT_ATTEMPTS) {
            closeSession()
            try {
                Thread.sleep(RECONNECT_DELAY_MS)
            } catch (e: InterruptedException) {
                Thread.currentThread().interrupt()
                return null
            }
            // Le même lecteur, autorisé : s'il a été rebranché, Android lui a peut-être donné un autre nom.
            val target = usbManager.deviceList.values.firstOrNull { it.deviceName == device.deviceName }
                ?: UsbCards.list(usbManager).singleOrNull {
                    it.vendorId == device.vendorId && it.productId == device.productId
                }
            if (target == null || !usbManager.hasPermission(target)) {
                log(Strings.logDetail("lecteur introuvable ou non autorisé (essai ${attempt + 1})"), LogKind.DETAIL)
                continue
            }
            try {
                val opened = synchronized(sessionLock) {
                    val card = UsbCards.open(usbManager, target, reset = true)
                    session = card
                    sessionDeviceName = target.deviceName
                    card
                }
                opened.block.useSmallCommands()
                log(Strings.LOG_RECONNECTED, LogKind.SUCCESS)
                log(Strings.logDetail("lecteur rouvert (essai ${attempt + 1})"), LogKind.DETAIL)
                return opened.block
            } catch (e: IOException) {
                log(Strings.logDetail("réouverture, essai ${attempt + 1} : ${e.message}"), LogKind.DETAIL)
            }
        }
        return null
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
            acquire(card.device).let { usbCard ->
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
        @Suppress("UNUSED_PARAMETER") networkOperation: Boolean = false,
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
        is WriteProtectedException -> Strings.ERROR_WRITE_PROTECTED
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
        private const val RECONNECT_SETTLE_MS = 2000L
        private const val RECONNECT_DELAY_MS = 3000L
        private const val RECONNECT_ATTEMPTS = 3
        private const val ACTION_USB_PERMISSION = "io.github.nonotrichlozz.r36sstudio.USB_PERMISSION"
    }
}
