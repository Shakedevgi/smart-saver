package com.shakedivgi.smartsaver

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.viewmodel.compose.viewModel
import com.shakedivgi.smartsaver.ui.dashboard.DashboardScreen
import com.shakedivgi.smartsaver.ui.dashboard.DashboardViewModel
import com.shakedivgi.smartsaver.ui.theme.SmartSaverTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            SmartSaverTheme {
                val vm: DashboardViewModel = viewModel()
                DashboardScreen(vm = vm)
            }
        }
    }
}
