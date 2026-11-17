// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import io.github.nonotrichlozz.r36sstudio.BrowserState
import io.github.nonotrichlozz.r36sstudio.Strings
import io.github.nonotrichlozz.r36sstudio.core.FsEntry
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Explorateur de la carte, en plein écran et en lecture seule : d'abord les
 * espaces de la carte, puis les dossiers de celui qu'on ouvre. Le bouton
 * Retour du téléphone remonte d'un niveau, puis ferme.
 */
@Composable
fun BrowserDialog(
    state: BrowserState,
    onOpenSpace: (Int) -> Unit,
    onOpenFolder: (FsEntry) -> Unit,
    onBack: () -> Unit,
) {
    val dateFormat = remember { SimpleDateFormat("dd/MM/yyyy HH:mm", Locale.FRANCE) }

    Dialog(onDismissRequest = onBack, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .background(Palette.BgDark)
                .windowInsetsPadding(WindowInsets.safeDrawing)
                .padding(horizontal = 16.dp, vertical = 12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                SecondaryButton(Strings.BROWSER_BACK, enabled = true, onClick = onBack)
                Spacer(Modifier.width(12.dp))
                Text(
                    state.volumeTitle ?: Strings.BROWSER_TITLE,
                    color = Palette.TextPrimary,
                    fontSize = 20.sp,
                    fontWeight = FontWeight.Bold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            Spacer(Modifier.height(10.dp))
            Text(Strings.BROWSER_READ_ONLY, color = Palette.AvailableFg, fontSize = 12.sp)
            if (state.path.isNotEmpty()) {
                Spacer(Modifier.height(4.dp))
                Text("/ " + state.path.joinToString(" / "), color = Palette.Cyan, fontSize = 13.sp, fontFamily = FontFamily.Monospace)
            }
            Spacer(Modifier.height(10.dp))

            if (state.error != null) {
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(PanelShape)
                        .background(Palette.DangerBg)
                        .border(1.dp, Palette.DangerBorder, PanelShape)
                        .padding(12.dp),
                ) {
                    Text(state.error, color = Palette.DangerFg, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                    Text(Strings.ERROR_BROWSE_HINT, color = Palette.TextSecondary, fontSize = 12.sp)
                    if (state.errorDetail.isNotBlank()) {
                        Text(Strings.logDetail(state.errorDetail), color = Palette.TextSecondary, fontSize = 11.sp, fontFamily = FontFamily.Monospace)
                    }
                }
                Spacer(Modifier.height(10.dp))
            }

            if (state.loading) {
                Text(Strings.BROWSER_LOADING, color = Palette.TextSecondary, fontSize = 14.sp)
            } else if (state.volumeTitle == null) {
                SpaceList(state, onOpenSpace, Modifier.weight(1f))
            } else {
                FolderList(state, dateFormat, onOpenFolder, Modifier.weight(1f))
            }

            if (!state.loading) {
                Spacer(Modifier.height(8.dp))
                Text(Strings.BROWSER_NO_COPY_YET, color = Palette.NotRelevantFg, fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun SpaceList(state: BrowserState, onOpenSpace: (Int) -> Unit, modifier: Modifier) {
    val rows = state.rows
    if (rows != null && rows.isEmpty()) {
        Text(Strings.BROWSER_NO_SPACE, color = Palette.TextSecondary, fontSize = 14.sp, modifier = modifier)
        return
    }
    LazyColumn(modifier = modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        itemsIndexed(rows.orEmpty()) { index, row ->
            Column(
                modifier = Modifier
                    .fillMaxWidth()
                    .alpha(if (row.readable) 1f else 0.5f)
                    .clip(PanelShape)
                    .background(Palette.Surface)
                    .border(1.dp, Palette.Border, PanelShape)
                    .clickable(enabled = row.readable) { onOpenSpace(index) }
                    .padding(14.dp),
            ) {
                Text(row.title, color = Palette.TextPrimary, fontSize = 16.sp, fontWeight = FontWeight.Bold)
                Text(row.info, color = Palette.TextSecondary, fontSize = 13.sp)
            }
        }
    }
}

@Composable
private fun FolderList(state: BrowserState, dateFormat: SimpleDateFormat, onOpenFolder: (FsEntry) -> Unit, modifier: Modifier) {
    if (state.items.isEmpty()) {
        Text(Strings.BROWSER_EMPTY_FOLDER, color = Palette.TextSecondary, fontSize = 14.sp, modifier = modifier)
        return
    }
    LazyColumn(modifier = modifier, verticalArrangement = Arrangement.spacedBy(6.dp)) {
        itemsIndexed(state.items) { _, entry ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .alpha(if (entry.hidden) 0.55f else 1f)
                    .clip(PanelShape)
                    .background(Palette.Surface)
                    .border(1.dp, Palette.Border, PanelShape)
                    .clickable(enabled = entry.isDirectory) { onOpenFolder(entry) }
                    .padding(horizontal = 14.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        entry.name,
                        color = if (entry.isDirectory) Palette.Cyan else Palette.TextPrimary,
                        fontSize = 15.sp,
                        fontWeight = if (entry.isDirectory) FontWeight.Bold else FontWeight.Normal,
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                    val date = entry.modifiedMillis?.let { dateFormat.format(Date(it)) }
                    if (entry.isDirectory) {
                        if (date != null) Text(date, color = Palette.TextSecondary, fontSize = 12.sp)
                    } else {
                        Text(Strings.browserFileInfo(entry.sizeBytes, date), color = Palette.TextSecondary, fontSize = 12.sp)
                    }
                }
                if (entry.isDirectory) Text("›", color = Palette.Cyan, fontSize = 20.sp)
            }
        }
    }
}
