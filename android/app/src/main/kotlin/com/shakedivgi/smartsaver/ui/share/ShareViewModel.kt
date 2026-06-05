package com.shakedivgi.smartsaver.ui.share

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.shakedivgi.smartsaver.SmartSaverApp
import com.shakedivgi.smartsaver.data.IngestRequest
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

sealed class ShareUiState {
    object Idle : ShareUiState()
    object Saving : ShareUiState()
    object Done : ShareUiState()
    data class Error(val message: String) : ShareUiState()
}

class ShareViewModel : ViewModel() {
    private val api = SmartSaverApp.instance.api

    private val _state = MutableStateFlow<ShareUiState>(ShareUiState.Idle)
    val state: StateFlow<ShareUiState> = _state

    fun save(url: String) {
        if (_state.value !is ShareUiState.Idle) return
        _state.value = ShareUiState.Saving
        viewModelScope.launch {
            api.ingest(IngestRequest(url = url))
                .onSuccess { _state.value = ShareUiState.Done }
                .onFailure { err ->
                    _state.value = ShareUiState.Error(err.message ?: "Unknown error")
                }
        }
    }
}
