package com.shakedivgi.smartsaver.data

// Kotlin mirrors of the Python Pydantic schemas exposed by src/api/main.py.
// Gson is configured with LOWER_CASE_WITH_UNDERSCORES so camelCase Kotlin names
// automatically map to snake_case JSON keys (e.g. isUncertain ↔ is_uncertain).

// MARK: - Search

data class SearchHit(
    val url: String,
    val distance: Double?,
    val document: String,
    val category: String?,
    val summary: String?,
    val metadata: HitMetadata
)

data class HitMetadata(
    val url: String?,
    val sourceType: String?,
    val title: String?,
    val category: String?,
    val isUncertain: Boolean?,
    val alternativeCategories: String?,
    val summary: String?,
    val keyInsights: String?,
    val price: String?,
    val location: String?,
    val technologies: String?,
    val entitiesJson: String?,
    val ingestedAt: String?,
    val createdAt: Double?,
    val status: String?
) {
    val alternativeCategoriesList: List<String>
        get() = splitPipe(alternativeCategories)

    val technologiesList: List<String>
        get() = splitPipe(technologies)

    private fun splitPipe(joined: String?): List<String> {
        if (joined.isNullOrEmpty()) return emptyList()
        return joined.split("|").map { it.trim() }.filter { it.isNotEmpty() }
    }
}

data class SearchResponse(
    val query: String,
    val category: String?,
    val hits: List<SearchHit>
)

// MARK: - Categories / Health

data class CategoriesResponse(val categories: List<String>)
data class HealthResponse(val status: String, val itemsIndexed: Int)

// MARK: - Ingest (used by Share Activity)

data class IngestRequest(
    val url: String,
    val analyze: Boolean = true,
    val store: Boolean = true,
    val existingCategories: List<String>? = null
)

// MARK: - Search request

data class SearchRequest(
    val query: String,
    val limit: Int = 10,
    val category: String? = null
)

// MARK: - Manual item create (POST /api/items)

data class ManualItemRequest(
    val url: String,
    val title: String,
    val summary: String,
    val category: String
)

// MARK: - Item management (DELETE / PATCH /api/items)

data class DeleteItemRequest(val url: String)
data class DeleteItemResponse(val url: String, val deleted: Boolean)

data class UpdateItemRequest(
    val url: String,
    val title: String? = null,
    val summary: String? = null,
    val category: String? = null
)

data class UpdateItemResponse(val url: String, val updated: Boolean, val item: SearchHit?)

// MARK: - Category management (PATCH / DELETE /api/categories)

data class RenameCategoryRequest(val oldName: String, val newName: String)
data class DeleteCategoryRequest(val name: String)
data class CategoryBulkResponse(val affected: Int)
