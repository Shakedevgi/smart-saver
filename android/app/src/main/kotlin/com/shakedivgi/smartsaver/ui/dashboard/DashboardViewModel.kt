package com.shakedivgi.smartsaver.ui.dashboard

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.shakedivgi.smartsaver.SmartSaverApp
import com.shakedivgi.smartsaver.data.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.net.URL

enum class ContentSource(val label: String) {
    All("All"),
    Instagram("Instagram"),
    TikTok("TikTok"),
    YouTube("YouTube"),
    Article("Article");

    companion object {
        fun detect(url: String): ContentSource {
            val host = runCatching { URL(url).host.lowercase() }.getOrDefault("")
            return when {
                "instagram.com" in host || "instagr.am" in host -> Instagram
                "tiktok.com" in host -> TikTok
                "youtube.com" in host || "youtu.be" in host -> YouTube
                else -> Article
            }
        }
    }
}

data class DashboardUiState(
    val categories: List<String> = emptyList(),
    val hits: List<SearchHit> = emptyList(),
    val filteredHits: List<SearchHit> = emptyList(),
    val itemsIndexed: Int = 0,
    val isLoading: Boolean = false,
    val isRefreshing: Boolean = false,
    val error: String? = null,
    val selectedCategory: String? = null,
    val selectedSource: ContentSource = ContentSource.All,
    val query: String = "",
    val editingHit: SearchHit? = null,
    val showAddSheet: Boolean = false
)

class DashboardViewModel : ViewModel() {
    private val api = SmartSaverApp.instance.api

    private val _state = MutableStateFlow(DashboardUiState())
    val state: StateFlow<DashboardUiState> = _state

    init { refresh() }

    fun refresh(isUserPull: Boolean = false) {
        viewModelScope.launch {
            _state.update { it.copy(isRefreshing = isUserPull, isLoading = !isUserPull, error = null) }
            api.categories().onSuccess { r -> _state.update { it.copy(categories = r.categories) } }
            api.health().onSuccess { r -> _state.update { it.copy(itemsIndexed = r.itemsIndexed) } }
            reloadCurrentView()
            _state.update { it.copy(isLoading = false, isRefreshing = false) }
        }
    }

    fun selectCategory(category: String?) {
        _state.update { it.copy(selectedCategory = category) }
        reloadCurrentView()
    }

    fun selectSource(source: ContentSource) {
        _state.update { it.copy(selectedSource = source) }
        applySourceFilter()
    }

    fun setQuery(q: String) = _state.update { it.copy(query = q) }

    fun search() {
        val q = _state.value.query.trim()
        if (q.isEmpty()) { reloadCurrentView(); return }
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            api.search(SearchRequest(query = q, category = _state.value.selectedCategory, limit = 20))
                .onSuccess { resp ->
                    val ranked = hybridRank(resp.hits, q)
                    _state.update { it.copy(hits = ranked, isLoading = false) }
                    applySourceFilter()
                }
                .onFailure { err ->
                    _state.update { it.copy(isLoading = false, error = err.message) }
                }
        }
    }

    fun deleteHit(hit: SearchHit) {
        _state.update { s ->
            s.copy(
                hits = s.hits.filter { it.url != hit.url },
                filteredHits = s.filteredHits.filter { it.url != hit.url },
                itemsIndexed = maxOf(0, s.itemsIndexed - 1)
            )
        }
        viewModelScope.launch {
            api.deleteItem(DeleteItemRequest(url = hit.url)).onFailure { refresh() }
        }
    }

    fun updateHit(original: SearchHit, title: String?, summary: String?, category: String?) {
        viewModelScope.launch {
            api.updateItem(UpdateItemRequest(url = original.url, title = title, summary = summary, category = category))
                .onSuccess { resp ->
                    val updated = resp.item
                    if (updated != null) {
                        _state.update { s ->
                            s.copy(
                                hits = s.hits.map { if (it.url == original.url) updated else it },
                                editingHit = null
                            )
                        }
                        applySourceFilter()
                    } else {
                        _state.update { it.copy(editingHit = null) }
                        refresh()
                    }
                }
                .onFailure { err -> _state.update { it.copy(error = "Couldn't save: ${err.message}") } }
        }
    }

    fun renameCategory(oldName: String, newName: String) {
        viewModelScope.launch {
            api.renameCategory(RenameCategoryRequest(oldName = oldName, newName = newName))
                .onSuccess { refresh() }
                .onFailure { err -> _state.update { it.copy(error = err.message) } }
        }
    }

    fun deleteCategory(name: String) {
        viewModelScope.launch {
            api.deleteCategory(DeleteCategoryRequest(name = name))
                .onSuccess { refresh() }
                .onFailure { err -> _state.update { it.copy(error = err.message) } }
        }
    }

    fun moveCategoryToGeneral(name: String) = renameCategory(name, "General")

    fun addManualItem(url: String, title: String, summary: String, category: String) {
        viewModelScope.launch {
            api.createItem(ManualItemRequest(url = url, title = title, summary = summary, category = category))
                .onSuccess { refresh() }
                .onFailure { err -> _state.update { it.copy(error = "Couldn't add: ${err.message}") } }
        }
    }

    fun setEditingHit(hit: SearchHit?) = _state.update { it.copy(editingHit = hit) }
    fun setShowAddSheet(show: Boolean) = _state.update { it.copy(showAddSheet = show) }
    fun clearError() = _state.update { it.copy(error = null) }

    // ── private helpers ──────────────────────────────────────────────────────

    private fun reloadCurrentView() {
        val q = _state.value.query.trim()
        if (q.isNotEmpty()) { search(); return }
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            api.search(SearchRequest(query = "everything", category = _state.value.selectedCategory, limit = 100))
                .onSuccess { resp ->
                    val sorted = resp.hits.sortedByDescending { it.metadata.createdAt ?: 0.0 }
                    _state.update { it.copy(hits = sorted, isLoading = false) }
                    applySourceFilter()
                }
                .onFailure { _state.update { it.copy(isLoading = false) } }
        }
    }

    private fun applySourceFilter() {
        val source = _state.value.selectedSource
        val filtered = if (source == ContentSource.All) _state.value.hits
        else _state.value.hits.filter { ContentSource.detect(it.url) == source }
        _state.update { it.copy(filteredHits = filtered) }
    }

    private fun hybridRank(hits: List<SearchHit>, query: String): List<SearchHit> {
        val words = query.lowercase().split(Regex("[^a-zA-Z0-9]")).filter { it.length >= 2 }
        if (words.isEmpty()) return hits
        return hits.mapNotNull { hit ->
            val haystack = listOf(
                hit.metadata.title.orEmpty(), hit.summary.orEmpty(),
                hit.metadata.category.orEmpty(), hit.metadata.technologies.orEmpty()
            ).joinToString(" ").lowercase()
            val matches = words.count { haystack.contains(it) }
            val semantic = 1.0 - (hit.distance ?: 1.0).coerceIn(0.0, 1.0)
            val score = semantic + 0.5 * matches
            if (score >= 0.3) hit to score else null
        }.sortedByDescending { (_, score) -> score }.map { (hit, _) -> hit }
    }
}
