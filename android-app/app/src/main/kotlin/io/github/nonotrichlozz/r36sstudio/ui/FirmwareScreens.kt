// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import io.github.nonotrichlozz.r36sstudio.Audience
import io.github.nonotrichlozz.r36sstudio.Firmware
import io.github.nonotrichlozz.r36sstudio.FirmwareStatus
import io.github.nonotrichlozz.r36sstudio.Firmwares
import io.github.nonotrichlozz.r36sstudio.Strings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.ConcurrentHashMap

private val ThumbShape = RoundedCornerShape(12.dp)
private val PhotoShape = RoundedCornerShape(14.dp)

/**
 * Choix du système, en plein écran : une liste de fiches, puis la fiche du
 * système choisi (photo, description, « À savoir », bouton d'installation).
 * Le bouton Retour du téléphone revient de la fiche à la liste, puis ferme.
 */
@Composable
fun FirmwarePickerDialog(
    onDismiss: () -> Unit,
    onDownload: (Firmware) -> Unit,
    onPickFile: () -> Unit,
) {
    var selected by remember { mutableStateOf<Firmware?>(null) }
    val back = { if (selected != null) selected = null else onDismiss() }

    Dialog(onDismissRequest = back, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(Palette.BgDark)
                .windowInsetsPadding(WindowInsets.safeDrawing)
                .padding(horizontal = 16.dp, vertical = 12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                SecondaryButton(Strings.PICKER_BACK, enabled = true, onClick = back)
                Spacer(Modifier.width(12.dp))
                Text(
                    selected?.title ?: Strings.PICKER_TITLE,
                    color = Palette.TextPrimary,
                    fontSize = 20.sp,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(Modifier.height(12.dp))
            val current = selected
            if (current == null) {
                FirmwareList(onSelect = { selected = it }, onPickFile = onPickFile)
            } else {
                FirmwareDetail(firmware = current, onDownload = onDownload, onPickFile = onPickFile)
            }
        }
    }
}

// ----------------------------------------------------------------------
// Liste
// ----------------------------------------------------------------------

@Composable
private fun FirmwareList(onSelect: (Firmware) -> Unit, onPickFile: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Text(Strings.PICKER_SUBTITLE, color = Palette.TextSecondary, fontSize = 13.sp)

        SectionLabel(Strings.PICKER_SECTION_DIRECT)
        for (firmware in Firmwares.ALL) {
            if (firmware.download != null) FirmwareRow(firmware, onClick = { onSelect(firmware) })
        }

        SectionLabel(Strings.PICKER_SECTION_LINK)
        for (firmware in Firmwares.ALL) {
            if (firmware.download == null) FirmwareRow(firmware, onClick = { onSelect(firmware) })
        }

        SectionLabel(Strings.PICKER_SECTION_FILE)
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(PanelShape)
                .background(Palette.Surface)
                .border(1.dp, Palette.Border, PanelShape)
                .clickable(onClick = onPickFile)
                .padding(14.dp),
        ) {
            Text(Strings.PICKER_FILE, color = Palette.TextPrimary, fontSize = 15.sp, fontWeight = FontWeight.Bold)
            Text(Strings.PICKER_FILE_DESC, color = Palette.TextSecondary, fontSize = 12.sp)
        }
        Spacer(Modifier.height(8.dp))
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(
        text,
        color = Palette.Cyan,
        fontSize = 11.sp,
        fontWeight = FontWeight.Bold,
        modifier = Modifier.padding(top = 6.dp),
    )
}

@Composable
private fun FirmwareRow(firmware: Firmware, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(PanelShape)
            .background(Palette.Surface)
            .border(1.dp, Palette.Border, PanelShape)
            .clickable(onClick = onClick)
            .padding(12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(56.dp)
                .clip(ThumbShape)
                .background(Palette.SurfaceRaised)
                .border(1.dp, Palette.Border, ThumbShape),
            contentAlignment = Alignment.Center,
        ) {
            val photo = rememberRemoteImage(Firmwares.photoUrl(firmware))
            if (photo != null) {
                Image(
                    bitmap = photo,
                    contentDescription = null,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxSize(),
                )
            } else {
                Text(firmware.monogram, color = Palette.Cyan, fontSize = 18.sp, fontWeight = FontWeight.Bold)
            }
        }
        Spacer(Modifier.width(12.dp))
        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(firmware.title, color = Palette.TextPrimary, fontSize = 16.sp, fontWeight = FontWeight.Bold)
            Text(firmware.tagline, color = Palette.TextSecondary, fontSize = 12.sp)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                AudienceBadge(firmware.audience)
                StatusBadge(firmware.status)
            }
        }
        Spacer(Modifier.width(8.dp))
        Text("›", color = Palette.TextSecondary, fontSize = 26.sp)
    }
}

@Composable
private fun AudienceBadge(audience: Audience) {
    val label = when (audience) {
        Audience.ORIGINAL -> Strings.AUDIENCE_ORIGINAL
        Audience.CLONE -> Strings.AUDIENCE_CLONE
        Audience.BOTH -> Strings.AUDIENCE_BOTH
    }
    Badge(text = label, background = Palette.SurfaceRaised, foreground = Palette.TextPrimary)
}

@Composable
private fun StatusBadge(status: FirmwareStatus) {
    val label: String
    val background: Color
    val foreground: Color
    when (status) {
        FirmwareStatus.MAINTAINED -> {
            label = Strings.STATUS_MAINTAINED
            background = Palette.AvailableBg
            foreground = Palette.AvailableFg
        }
        FirmwareStatus.EXPERIMENTAL -> {
            label = Strings.STATUS_EXPERIMENTAL
            background = Palette.WarningBg
            foreground = Palette.WarningFg
        }
        FirmwareStatus.ARCHIVED -> {
            label = Strings.STATUS_ARCHIVED
            background = Palette.NotRelevantBg
            foreground = Palette.TextSecondary
        }
    }
    Badge(text = label, background = background, foreground = foreground)
}

// ----------------------------------------------------------------------
// Fiche
// ----------------------------------------------------------------------

@Composable
private fun FirmwareDetail(firmware: Firmware, onDownload: (Firmware) -> Unit, onPickFile: () -> Unit) {
    val uriHandler = LocalUriHandler.current
    var browserFailed by remember(firmware) { mutableStateOf(false) }

    Column(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .weight(1f)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            // Photo du système (16:9), ou vignette en attendant.
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .aspectRatio(16f / 9f)
                    .clip(PhotoShape)
                    .background(Palette.Surface)
                    .border(1.dp, Palette.Border, PhotoShape),
                contentAlignment = Alignment.Center,
            ) {
                val photo = rememberRemoteImage(Firmwares.photoUrl(firmware))
                if (photo != null) {
                    Image(
                        bitmap = photo,
                        contentDescription = firmware.title,
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize(),
                    )
                } else {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(firmware.monogram, color = Palette.Cyan, fontSize = 44.sp, fontWeight = FontWeight.Bold)
                        Text(Strings.PICKER_PHOTO_MISSING, color = Palette.TextSecondary, fontSize = 12.sp)
                    }
                }
            }

            Text(firmware.tagline, color = Palette.TextPrimary, fontSize = 17.sp, fontWeight = FontWeight.Bold)
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                AudienceBadge(firmware.audience)
                StatusBadge(firmware.status)
                if (firmware.download != null) {
                    Badge(text = Strings.BADGE_DIRECT, background = Palette.SurfaceRaised, foreground = Palette.Cyan)
                }
            }
            Text(firmware.description, color = Palette.TextPrimary, fontSize = 14.sp)

            if (firmware.note.isNotEmpty() || !firmware.phoneReady) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(PanelShape)
                        .background(Palette.WarningBg)
                        .border(1.dp, Palette.WarningFg, PanelShape)
                        .padding(12.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text(Strings.PICKER_NOTE_TITLE, color = Palette.WarningFg, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                    if (firmware.note.isNotEmpty()) {
                        Text(firmware.note, color = Palette.TextPrimary, fontSize = 13.sp)
                    }
                    if (!firmware.phoneReady) {
                        Text(Strings.PICKER_NOT_PHONE, color = Palette.TextPrimary, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                    }
                }
            }

            if (firmware.download == null) {
                Text(Strings.PICKER_LINK_HELP, color = Palette.TextSecondary, fontSize = 12.sp)
                Text(
                    firmware.pageUrl.removePrefix("https://"),
                    color = Palette.TextSecondary,
                    fontSize = 11.sp,
                    fontFamily = FontFamily.Monospace,
                )
            }
            if (browserFailed) {
                Text(Strings.PICKER_NO_BROWSER, color = Palette.DangerFg, fontSize = 12.sp)
            }
        }

        Spacer(Modifier.height(10.dp))
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.End),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            if (firmware.download != null) {
                PrimaryButton(Strings.PICKER_DOWNLOAD_INSTALL, enabled = true, onClick = { onDownload(firmware) })
            } else {
                if (firmware.phoneReady) {
                    SecondaryButton(Strings.PICKER_PICK_DOWNLOADED, enabled = true, onClick = onPickFile)
                }
                PrimaryButton(
                    Strings.PICKER_OPEN_PAGE,
                    enabled = true,
                    onClick = {
                        try {
                            uriHandler.openUri(firmware.pageUrl)
                        } catch (e: Exception) {
                            browserFailed = true
                        }
                    },
                )
            }
        }
    }
}

// ----------------------------------------------------------------------
// Photos : chargées depuis le dépôt GitHub du projet, jamais embarquées
// ----------------------------------------------------------------------

private val photoCache = ConcurrentHashMap<String, ImageBitmap>()
private val photoMissing = ConcurrentHashMap.newKeySet<String>()
private const val MAX_PHOTO_BYTES = 3 * 1024 * 1024

/** `null` tant que la photo n'est pas chargée, et pour toujours si elle n'existe pas. */
@Composable
private fun rememberRemoteImage(url: String): ImageBitmap? {
    val state = produceState(initialValue = photoCache[url], url) {
        if (value == null && !photoMissing.contains(url)) {
            value = withContext(Dispatchers.IO) { loadPhoto(url) }
        }
    }
    return state.value
}

private fun loadPhoto(url: String): ImageBitmap? {
    return try {
        val connection = URL(url).openConnection() as HttpURLConnection
        connection.connectTimeout = 8_000
        connection.readTimeout = 10_000
        try {
            if (connection.responseCode != 200) {
                if (connection.responseCode == 404) photoMissing.add(url)
                return null
            }
            val bytes = connection.inputStream.use { input ->
                val out = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(64 * 1024)
                while (true) {
                    val n = input.read(buffer)
                    if (n < 0) break
                    out.write(buffer, 0, n)
                    if (out.size() > MAX_PHOTO_BYTES) return null
                }
                out.toByteArray()
            }
            val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return null
            val image = bitmap.asImageBitmap()
            photoCache[url] = image
            image
        } finally {
            connection.disconnect()
        }
    } catch (e: Exception) {
        null
    }
}
