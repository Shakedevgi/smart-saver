package com.shakedivgi.smartsaver

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.core.view.WindowCompat
import androidx.lifecycle.viewmodel.compose.viewModel
import com.shakedivgi.smartsaver.ui.share.ShareScreen
import com.shakedivgi.smartsaver.ui.share.ShareViewModel
import com.shakedivgi.smartsaver.ui.theme.SmartSaverTheme

class ShareActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        WindowCompat.setDecorFitsSystemWindows(window, false)

        val sharedText = intent?.getStringExtra(Intent.EXTRA_TEXT).orEmpty()
        val url = extractUrl(sharedText) ?: sharedText

        setContent {
            SmartSaverTheme {
                val vm: ShareViewModel = viewModel()
                ShareScreen(
                    url = url,
                    viewModel = vm,
                    onDismiss = { finish() }
                )
            }
        }
    }

    private fun extractUrl(text: String): String? {
        if (text.isBlank()) return null
        val regex = Regex("https?://[\\w/:%#\$&?!()@~=+.,\\-]+")
        return regex.find(text)?.value?.trimEnd('.')
    }
}
