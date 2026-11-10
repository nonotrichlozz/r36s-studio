// Copyright (c) 2026 Arnaud
// Licence : PolyForm Strict 1.0.0, voir LICENSE

package io.github.nonotrichlozz.r36sstudio

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import io.github.nonotrichlozz.r36sstudio.ui.MainScreen

class MainActivity : ComponentActivity() {

    private val viewModel: MainViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Android 13+ : sans cet accord, la notification « opération en cours »
        // reste cachée (l'opération, elle, tourne quand même).
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && savedInstanceState == null &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
        setContent {
            MainScreen(viewModel = viewModel, keepScreenOn = ::setKeepScreenOn)
        }
    }

    /** Ouverte par le branchement d'une carte alors qu'elle tourne déjà. */
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        viewModel.refreshCards()
    }

    override fun onResume() {
        super.onResume()
        viewModel.refreshCards()
    }

    /** L'écran reste allumé pendant une opération : une mise en veille pourrait l'interrompre. */
    private fun setKeepScreenOn(on: Boolean) {
        if (on) {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        } else {
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }
}
