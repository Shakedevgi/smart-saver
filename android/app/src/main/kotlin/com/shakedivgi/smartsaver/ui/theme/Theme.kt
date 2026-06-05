package com.shakedivgi.smartsaver.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Brand palette — mirrors the iOS `Brand` enum in ContentView.swift
object BrandColors {
    val electricBlue   = Color(0xFF3E86F8)
    val gradientTop    = Color(0xFF0A205C)
    val gradientBottom = Color(0xFF3E86F8)
    val midnightDeep   = Color(0xFF050818)
    val midnightMid    = Color(0xFF080F2A)
    val cardBackground = Color(0xFF0E1637)
    val cardBorder     = Color(0x473E86F8) // electricBlue at 28% opacity
    val success        = Color(0xFF4CAF50)
    val warning        = Color(0xFFFFC107)
    val danger         = Color(0xFFE57373)
}

private val SmartSaverColorScheme = darkColorScheme(
    primary            = BrandColors.electricBlue,
    onPrimary          = Color.White,
    primaryContainer   = BrandColors.gradientTop,
    secondary          = BrandColors.electricBlue.copy(alpha = 0.7f),
    onSecondary        = Color.White,
    background         = BrandColors.midnightDeep,
    onBackground       = Color.White,
    surface            = BrandColors.cardBackground,
    onSurface          = Color.White,
    surfaceVariant     = BrandColors.midnightMid,
    onSurfaceVariant   = Color.White.copy(alpha = 0.7f),
    error              = BrandColors.danger,
    onError            = Color.White,
)

@Composable
fun SmartSaverTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = SmartSaverColorScheme,
        content = content
    )
}
