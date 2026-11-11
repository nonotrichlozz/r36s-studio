// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import io.github.nonotrichlozz.r36sstudio.CardState
import io.github.nonotrichlozz.r36sstudio.DialogState
import io.github.nonotrichlozz.r36sstudio.Firmwares
import io.github.nonotrichlozz.r36sstudio.LogKind
import io.github.nonotrichlozz.r36sstudio.LogLine
import io.github.nonotrichlozz.r36sstudio.MainViewModel
import io.github.nonotrichlozz.r36sstudio.OpState
import io.github.nonotrichlozz.r36sstudio.Strings

private val PanelShape = RoundedCornerShape(10.dp)
private val CapsuleShape = RoundedCornerShape(50)

private val AppColors = darkColorScheme(
    primary = Palette.Cyan,
    onPrimary = Palette.BgDark,
    background = Palette.BgDark,
    onBackground = Palette.TextPrimary,
    surface = Palette.Surface,
    onSurface = Palette.TextPrimary,
    error = Palette.DangerFg,
)

@Composable
fun MainScreen(viewModel: MainViewModel, keepScreenOn: (Boolean) -> Unit) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val busy = state.op != null
    val cardReady = state.card is CardState.Ready

    LaunchedEffect(busy) { keepScreenOn(busy) }

    val pickImage = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) viewModel.onImagePicked(uri)
    }
    val createBackup = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/gzip")) { uri ->
        if (uri != null) viewModel.startBackup(uri)
    }

    MaterialTheme(colorScheme = AppColors) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(Palette.BgDark)
                .windowInsetsPadding(WindowInsets.safeDrawing)
                .padding(horizontal = 16.dp, vertical = 12.dp),
        ) {
            Column(
                modifier = Modifier
                    .weight(1f)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Text(Strings.APP_TITLE, color = Palette.TextPrimary, fontSize = 24.sp, fontWeight = FontWeight.Bold)
                Text(Strings.APP_SUBTITLE, color = Palette.TextSecondary, fontSize = 13.sp)
                Text(Strings.VERSION_LINE, color = Palette.NotRelevantFg, fontSize = 11.sp)

                CardBanner(
                    card = state.card,
                    busy = busy,
                    onRefresh = { viewModel.refreshCards(force = true) },
                    onAllow = viewModel::requestPermission,
                )

                Tile(
                    title = Strings.TILE_INSTALL,
                    description = Strings.TILE_INSTALL_DESC,
                    ready = cardReady,
                    enabled = !busy,
                    onClick = { if (viewModel.canStartCardAction()) viewModel.openFirmwarePicker() },
                )

                Text(
                    Strings.SECTION_SAFETY,
                    color = Palette.TextSecondary,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(top = 6.dp),
                )
                Tile(
                    title = Strings.TILE_BACKUP,
                    description = Strings.TILE_BACKUP_DESC,
                    ready = cardReady,
                    enabled = !busy,
                    onClick = { if (viewModel.canStartCardAction()) createBackup.launch(viewModel.suggestedBackupName()) },
                )
                Tile(
                    title = Strings.TILE_RESTORE,
                    description = Strings.TILE_RESTORE_DESC,
                    ready = cardReady,
                    enabled = !busy,
                    onClick = { if (viewModel.canStartCardAction()) pickImage.launch(arrayOf("*/*")) },
                )
            }

            Spacer(Modifier.height(10.dp))
            LogPanel(op = state.op, log = state.log, onCancel = viewModel::cancel)
        }

        when (val dialog = state.dialog) {
            DialogState.None -> Unit
            DialogState.FirmwarePicker -> FirmwarePickerDialog(
                onDismiss = viewModel::dismissDialog,
                onFirmware = viewModel::downloadFirmware,
                onPickFile = {
                    viewModel.dismissDialog()
                    pickImage.launch(arrayOf("*/*"))
                },
            )
            is DialogState.ConfirmFlash -> ConfirmFlashDialog(
                dialog = dialog,
                onCancel = viewModel::dismissDialog,
                onConfirm = { viewModel.confirmFlash(dialog) },
            )
            is DialogState.Message -> MessageDialog(text = dialog.text, onDismiss = viewModel::dismissDialog)
        }
    }
}

// ----------------------------------------------------------------------
// Bandeau « carte détectée »
// ----------------------------------------------------------------------

@Composable
private fun CardBanner(card: CardState, busy: Boolean, onRefresh: () -> Unit, onAllow: () -> Unit) {
    val title: String
    val hint: String
    val detail = when (card) {
        is CardState.Problem -> card.detail
        is CardState.Ready -> card.detail
        else -> ""
    }
    when (card) {
        CardState.None -> {
            title = Strings.CARD_NONE
            hint = Strings.CARD_NONE_HINT
        }
        CardState.Several -> {
            title = Strings.CARD_SEVERAL
            hint = Strings.CARD_SEVERAL_HINT
        }
        is CardState.NeedsPermission -> {
            title = Strings.CARD_NEEDS_PERMISSION
            hint = Strings.CARD_NEEDS_PERMISSION_HINT
        }
        is CardState.Probing -> {
            title = Strings.CARD_PROBING
            hint = ""
        }
        is CardState.Ready -> {
            title = card.display + " — " + Strings.formatSize(card.sizeBytes)
            hint = if (card.writeProtected) Strings.CARD_LOCKED_HINT else Strings.CARD_READY_HINT
        }
        is CardState.Problem -> {
            title = Strings.CARD_PROBLEM
            hint = card.message
        }
    }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(PanelShape)
            .background(Palette.Surface)
            .border(1.dp, Palette.Cyan, PanelShape)
            .padding(14.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text(title, color = Palette.TextPrimary, fontSize = 16.sp, fontWeight = FontWeight.Bold)
                if (hint.isNotEmpty()) {
                    val hintColor = when (card) {
                        is CardState.Ready -> if (card.writeProtected) Palette.WarningFg else Palette.AvailableFg
                        is CardState.Problem, CardState.Several -> Palette.WarningFg
                        else -> Palette.TextSecondary
                    }
                    Text(hint, color = hintColor, fontSize = 13.sp)
                }
                if (detail.isNotEmpty()) {
                    Text(Strings.logDetail(detail), color = Palette.TextSecondary, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
                }
            }
            Spacer(Modifier.width(8.dp))
            if (card is CardState.NeedsPermission) {
                PrimaryButton(Strings.CARD_ALLOW, enabled = !busy, onClick = onAllow)
            } else {
                SecondaryButton(Strings.REFRESH, enabled = !busy, onClick = onRefresh)
            }
        }
    }
}

// ----------------------------------------------------------------------
// Tuiles
// ----------------------------------------------------------------------

@Composable
private fun Tile(title: String, description: String, ready: Boolean, enabled: Boolean, onClick: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .alpha(if (enabled) 1f else 0.45f)
            .clip(PanelShape)
            .background(Palette.Surface)
            .border(1.dp, Palette.Border, PanelShape)
            .clickable(enabled = enabled, onClick = onClick)
            .padding(14.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(title, color = Palette.TextPrimary, fontSize = 16.sp, fontWeight = FontWeight.Bold)
            Text(description, color = Palette.TextSecondary, fontSize = 13.sp)
        }
        Spacer(Modifier.width(10.dp))
        Badge(
            text = if (ready) Strings.BADGE_READY else Strings.BADGE_NO_CARD,
            background = if (ready) Palette.AvailableBg else Palette.NotRelevantBg,
            foreground = if (ready) Palette.AvailableFg else Palette.TextSecondary,
        )
    }
}

@Composable
private fun Badge(text: String, background: Color, foreground: Color) {
    Box(
        modifier = Modifier
            .clip(CapsuleShape)
            .background(background)
            .padding(horizontal = 10.dp, vertical = 4.dp),
    ) {
        Text(text, color = foreground, fontSize = 11.sp, fontWeight = FontWeight.Bold)
    }
}

// ----------------------------------------------------------------------
// Journal de bord permanent
// ----------------------------------------------------------------------

@Composable
private fun LogPanel(op: OpState?, log: List<LogLine>, onCancel: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .height(270.dp)
            .clip(PanelShape)
            .background(Palette.LogBg)
            .border(1.dp, Palette.Cyan, PanelShape)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    if (op != null) Strings.LOG_TITLE_ACTIVE else Strings.LOG_TITLE_IDLE,
                    color = Palette.Cyan,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.Bold,
                )
                if (op != null) {
                    Text(op.title + " — " + op.phase, color = Palette.TextPrimary, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                }
            }
            if (op != null) {
                SecondaryButton(Strings.CANCEL, enabled = !op.cancelling, onClick = onCancel)
            }
        }

        if (op != null) {
            val fraction = if (op.total > 0) (op.done.toFloat() / op.total.toFloat()).coerceIn(0f, 1f) else 0f
            LinearProgressIndicator(
                progress = { fraction },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(8.dp)
                    .clip(CapsuleShape),
                color = Palette.Cyan,
                trackColor = Palette.Border,
            )
            val details = StringBuilder()
            if (op.total > 0) details.append((fraction * 100).toInt()).append(" %")
            if (op.speed > 0) details.append("  ·  ").append(Strings.formatSpeed(op.speed))
            val elapsedMs = System.currentTimeMillis() - op.phaseStartMs
            if (op.total > 0 && op.done > 0 && op.done < op.total && elapsedMs > 3000) {
                val remaining = (elapsedMs.toDouble() * (op.total - op.done) / op.done / 1000).toLong()
                details.append("  ·  ").append(Strings.formatRemaining(remaining))
            }
            Text(details.toString(), color = Palette.TextSecondary, fontSize = 12.sp)
            Text(Strings.KEEP_OPEN, color = Palette.WarningFg, fontSize = 12.sp)
        }

        val listState = rememberLazyListState()
        LaunchedEffect(log.size) {
            if (log.isNotEmpty()) listState.scrollToItem(log.size - 1)
        }
        if (log.isEmpty()) {
            Text(Strings.LOG_EMPTY, color = Palette.TextSecondary, fontSize = 12.sp)
        } else {
            LazyColumn(state = listState, modifier = Modifier.fillMaxWidth().weight(1f)) {
                items(log) { line ->
                    val color = when (line.kind) {
                        LogKind.INFO -> Palette.LogText
                        LogKind.SUCCESS -> Palette.AvailableFg
                        LogKind.ERROR -> Palette.DangerFg
                        LogKind.DETAIL -> Palette.TextSecondary
                    }
                    Text(
                        line.time + " - " + line.text,
                        color = color,
                        fontSize = 12.sp,
                        fontFamily = FontFamily.Monospace,
                        fontWeight = if (line.kind == LogKind.ERROR || line.kind == LogKind.SUCCESS) FontWeight.Bold else FontWeight.Normal,
                    )
                }
            }
        }
    }
}

// ----------------------------------------------------------------------
// Fenêtres
// ----------------------------------------------------------------------

@Composable
private fun DialogPanel(
    onDismiss: () -> Unit,
    background: Color = Palette.Surface,
    borderColor: Color = Palette.Cyan,
    content: @Composable () -> Unit,
) {
    Dialog(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .clip(PanelShape)
                .background(background)
                .border(1.dp, borderColor, PanelShape)
                .padding(16.dp)
                .verticalScroll(rememberScrollState()),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            content()
        }
    }
}

@Composable
private fun FirmwarePickerDialog(
    onDismiss: () -> Unit,
    onFirmware: (io.github.nonotrichlozz.r36sstudio.Firmware) -> Unit,
    onPickFile: () -> Unit,
) {
    DialogPanel(onDismiss = onDismiss) {
        Text(Strings.PICKER_TITLE, color = Palette.TextPrimary, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Text(Strings.PICKER_DOWNLOAD, color = Palette.Cyan, fontSize = 12.sp, fontWeight = FontWeight.Bold)
        for (firmware in Firmwares.ALL) {
            ChoiceRow(title = firmware.title, description = firmware.description, onClick = { onFirmware(firmware) })
        }
        Text(Strings.PICKER_FILE, color = Palette.Cyan, fontSize = 12.sp, fontWeight = FontWeight.Bold)
        ChoiceRow(title = Strings.PICKER_FILE, description = Strings.PICKER_FILE_DESC, onClick = onPickFile)
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            SecondaryButton(Strings.CANCEL, enabled = true, onClick = onDismiss)
        }
    }
}

@Composable
private fun ChoiceRow(title: String, description: String, onClick: () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(PanelShape)
            .background(Palette.SurfaceRaised)
            .border(1.dp, Palette.Border, PanelShape)
            .clickable(onClick = onClick)
            .padding(12.dp),
    ) {
        Text(title, color = Palette.TextPrimary, fontSize = 15.sp, fontWeight = FontWeight.Bold)
        Text(description, color = Palette.TextSecondary, fontSize = 12.sp)
    }
}

/** Fond rouge, case obligatoire jamais pré-cochée : dernier rempart avant l'écriture. */
@Composable
private fun ConfirmFlashDialog(dialog: DialogState.ConfirmFlash, onCancel: () -> Unit, onConfirm: () -> Unit) {
    var understood by remember(dialog) { mutableStateOf(false) }
    DialogPanel(onDismiss = onCancel, background = Palette.DangerBg, borderColor = Palette.DangerBorder) {
        Text(Strings.CONFIRM_TITLE, color = Palette.DangerFg, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        Text(
            Strings.confirmErase(dialog.cardDisplay, dialog.cardBytes),
            color = Palette.TextPrimary,
            fontSize = 15.sp,
            fontWeight = FontWeight.Bold,
        )
        Text(Strings.confirmSource(dialog.source.label), color = Palette.TextSecondary, fontSize = 13.sp)
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clickable { understood = !understood },
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Checkbox(
                checked = understood,
                onCheckedChange = { understood = it },
                colors = CheckboxDefaults.colors(
                    checkedColor = Palette.DangerFg,
                    uncheckedColor = Palette.DangerFg,
                    checkmarkColor = Palette.DangerBg,
                ),
            )
            Text(Strings.CONFIRM_CHECKBOX, color = Palette.TextPrimary, fontSize = 13.sp)
        }
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp, Alignment.End)) {
            SecondaryButton(Strings.CANCEL, enabled = true, onClick = onCancel)
            Button(
                onClick = onConfirm,
                enabled = understood,
                colors = ButtonDefaults.buttonColors(
                    containerColor = Palette.DangerFg,
                    contentColor = Palette.DangerBg,
                    disabledContainerColor = Palette.DangerBorder,
                    disabledContentColor = Palette.TextSecondary,
                ),
            ) {
                Text(Strings.CONFIRM_GO, fontWeight = FontWeight.Bold)
            }
        }
    }
}

@Composable
private fun MessageDialog(text: String, onDismiss: () -> Unit) {
    DialogPanel(onDismiss = onDismiss) {
        Text(text, color = Palette.TextPrimary, fontSize = 15.sp)
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
            PrimaryButton(Strings.OK, enabled = true, onClick = onDismiss)
        }
    }
}

// ----------------------------------------------------------------------
// Boutons
// ----------------------------------------------------------------------

@Composable
private fun PrimaryButton(text: String, enabled: Boolean, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        enabled = enabled,
        colors = ButtonDefaults.buttonColors(
            containerColor = Palette.Cyan,
            contentColor = Palette.BgDark,
            disabledContainerColor = Palette.Border,
            disabledContentColor = Palette.TextSecondary,
        ),
    ) {
        Text(text, fontWeight = FontWeight.Bold)
    }
}

@Composable
private fun SecondaryButton(text: String, enabled: Boolean, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        border = BorderStroke(1.dp, if (enabled) Palette.Cyan else Palette.Border),
        colors = ButtonDefaults.outlinedButtonColors(
            contentColor = Palette.Cyan,
            disabledContentColor = Palette.TextSecondary,
        ),
    ) {
        Text(text)
    }
}
