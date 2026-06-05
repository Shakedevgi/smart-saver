package com.shakedivgi.smartsaver.ui.share

import androidx.compose.animation.core.*
import androidx.compose.foundation.layout.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Error
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.shakedivgi.smartsaver.ui.theme.BrandColors
import kotlinx.coroutines.delay

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ShareScreen(
    url: String,
    viewModel: ShareViewModel,
    onDismiss: () -> Unit
) {
    val state by viewModel.state.collectAsState()

    // Kick off the save immediately on first composition
    LaunchedEffect(url) {
        viewModel.save(url)
    }

    // Auto-dismiss 700 ms after successful save — fast enough to feel snappy,
    // long enough for the user to see the green "Saved!" confirmation.
    LaunchedEffect(state) {
        if (state is ShareUiState.Done) {
            delay(700)
            onDismiss()
        }
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        containerColor = BrandColors.cardBackground,
        contentColor = Color.White,
        tonalElevation = 0.dp,
        dragHandle = {
            // Subtle drag handle in brand blue
            Box(
                modifier = Modifier
                    .padding(top = 12.dp, bottom = 8.dp)
                    .size(width = 40.dp, height = 4.dp)
                    .padding(0.dp)
            ) {
                BottomSheetDefaults.DragHandle(color = BrandColors.electricBlue.copy(alpha = 0.4f))
            }
        }
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 24.dp)
                .navigationBarsPadding()
                .padding(bottom = 24.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(14.dp)
        ) {
            // Brand header
            Text(
                text = "Smart Saver",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.Bold,
                color = BrandColors.electricBlue
            )

            HorizontalDivider(color = BrandColors.cardBorder)

            when (val s = state) {
                is ShareUiState.Idle, is ShareUiState.Saving -> SavingContent(url)
                is ShareUiState.Done -> DoneContent()
                is ShareUiState.Error -> ErrorContent(s.message, onDismiss)
            }

            Spacer(Modifier.height(4.dp))
        }
    }
}

@Composable
private fun SavingContent(url: String) {
    CircularProgressIndicator(
        color = BrandColors.electricBlue,
        modifier = Modifier.size(44.dp),
        strokeWidth = 3.dp
    )
    Text(
        text = "Saving to Smart Saver…",
        style = MaterialTheme.typography.bodyLarge,
        fontWeight = FontWeight.Medium,
        color = Color.White
    )
    if (url.isNotEmpty()) {
        Text(
            text = if (url.length > 55) url.take(55) + "…" else url,
            style = MaterialTheme.typography.bodySmall,
            color = Color.White.copy(alpha = 0.4f)
        )
    }
}

@Composable
private fun DoneContent() {
    Icon(
        imageVector = Icons.Default.CheckCircle,
        contentDescription = null,
        tint = BrandColors.success,
        modifier = Modifier.size(44.dp)
    )
    Text(
        text = "Saved!",
        style = MaterialTheme.typography.bodyLarge,
        fontWeight = FontWeight.SemiBold,
        color = BrandColors.success
    )
}

@Composable
private fun ErrorContent(message: String, onDismiss: () -> Unit) {
    Icon(
        imageVector = Icons.Default.Error,
        contentDescription = null,
        tint = BrandColors.danger,
        modifier = Modifier.size(44.dp)
    )
    Text(
        text = "Couldn't save",
        style = MaterialTheme.typography.bodyLarge,
        fontWeight = FontWeight.SemiBold,
        color = BrandColors.danger
    )
    Text(
        text = message.take(120),
        style = MaterialTheme.typography.bodySmall,
        color = Color.White.copy(alpha = 0.6f)
    )
    Spacer(Modifier.height(4.dp))
    Button(
        onClick = onDismiss,
        colors = ButtonDefaults.buttonColors(containerColor = BrandColors.electricBlue)
    ) {
        Text("Close")
    }
}
