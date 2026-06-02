// Swift mirrors of the Python Pydantic schemas exposed by `src/api/main.py`.
// JSONDecoder is configured with `.convertFromSnakeCase` at the NetworkManager
// layer, so server keys like `is_uncertain` automatically map to `isUncertain`.

import Foundation

// MARK: - Search

/// One row returned by `POST /api/search`. Mirrors `src.schemas.SearchHit`.
struct SearchHit: Codable, Identifiable, Hashable {
    let url: String
    let distance: Double?
    let document: String
    let category: String?
    let summary: String?
    let metadata: HitMetadata

    var id: String { url }
}

/// Flat metadata payload Chroma persists alongside each item.
/// Mirrors the dict produced by `VectorStoreManager._build_metadata`.
struct HitMetadata: Codable, Hashable {
    let url: String?
    let sourceType: String?
    let title: String?
    let category: String?
    let isUncertain: Bool?
    /// Server stores alternative categories as a pipe-joined string for filterability.
    let alternativeCategories: String?
    let summary: String?
    let keyInsights: String?           // JSON-encoded list
    let price: String?
    let location: String?
    /// Pipe-joined list (matches storage format).
    let technologies: String?
    let entitiesJson: String?
    let ingestedAt: String?
    /// Unix timestamp (seconds since epoch) set at ingestion time.
    /// Used for chronological sorting (newest-first) on the dashboard.
    let createdAt: Double?
    /// One of: "processing" | "completed" | "failed". Populated by the
    /// async pipeline (Step 6). Older rows without this field decode to nil
    /// — treat nil as "completed" so the UI is backward-compatible.
    let status: String?

    var alternativeCategoriesList: [String] {
        Self.splitPipe(alternativeCategories)
    }

    var technologiesList: [String] {
        Self.splitPipe(technologies)
    }

    var keyInsightsList: [String] {
        guard let json = keyInsights,
              let data = json.data(using: .utf8),
              let arr = try? JSONDecoder().decode([String].self, from: data) else {
            return []
        }
        return arr
    }

    private static func splitPipe(_ joined: String?) -> [String] {
        guard let joined = joined, !joined.isEmpty else { return [] }
        return joined
            .split(separator: "|")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
    }
}

struct SearchResponse: Codable {
    let query: String
    let category: String?
    let hits: [SearchHit]
}

// MARK: - Categories / Health

struct CategoriesResponse: Codable {
    let categories: [String]
}

struct HealthResponse: Codable {
    let status: String
    let itemsIndexed: Int
}

// MARK: - Ingest (used by Share Extension)

struct IngestRequest: Codable {
    let url: String
    let analyze: Bool
    let store: Bool
    let existingCategories: [String]?

    init(url: String, analyze: Bool = true, store: Bool = true, existingCategories: [String]? = nil) {
        self.url = url
        self.analyze = analyze
        self.store = store
        self.existingCategories = existingCategories
    }
}

// MARK: - Manual item create (POST /api/items)

struct ManualItemRequest: Codable {
    let url: String
    let title: String
    let summary: String
    let category: String
}

// MARK: - Item management (DELETE / PATCH /api/items)

struct DeleteItemRequest: Codable {
    let url: String
}

struct DeleteItemResponse: Codable {
    let url: String
    let deleted: Bool
}

struct UpdateItemRequest: Codable {
    let url: String
    let title: String?
    let summary: String?
    let category: String?

    init(url: String, title: String? = nil, summary: String? = nil, category: String? = nil) {
        self.url = url
        self.title = title
        self.summary = summary
        self.category = category
    }
}

struct UpdateItemResponse: Codable {
    let url: String
    let updated: Bool
    let item: SearchHit?
}

// MARK: - Category management (PATCH / DELETE /api/categories)

struct RenameCategoryRequest: Codable {
    let oldName: String
    let newName: String
}

struct DeleteCategoryRequest: Codable {
    let name: String
}

struct CategoryBulkResponse: Codable {
    let affected: Int
}
