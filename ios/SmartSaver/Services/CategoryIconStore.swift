// Local-only persistence for per-category SF Symbol overrides.
//
// The backend stays oblivious — it only knows category *names*. The user
// gets to pick a personal icon for each category through the Edit sheet,
// and we cache the choice in UserDefaults. If the category gets renamed
// via PATCH /api/categories, we migrate the override key to match.

import Foundation
import SwiftUI

@MainActor
final class CategoryIconStore: ObservableObject {
    @Published private(set) var overrides: [String: String] = [:]

    private let defaultsKey = "categoryIconOverridesV1"

    init() { load() }

    func icon(for category: String) -> String? {
        overrides[category]
    }

    func setIcon(_ symbol: String, for category: String) {
        overrides[category] = symbol
        save()
    }

    func clearIcon(for category: String) {
        if overrides.removeValue(forKey: category) != nil {
            save()
        }
    }

    /// Migrate an existing override when the user renames a category on
    /// the backend, so the icon they picked travels with the new name.
    func renameCategory(from old: String, to new: String) {
        guard old != new else { return }
        if let icon = overrides.removeValue(forKey: old) {
            overrides[new] = icon
            save()
        }
    }

    // MARK: - Persistence

    private func load() {
        guard let data = UserDefaults.standard.data(forKey: defaultsKey),
              let dict = try? JSONDecoder().decode([String: String].self, from: data)
        else { return }
        overrides = dict
    }

    private func save() {
        if let data = try? JSONEncoder().encode(overrides) {
            UserDefaults.standard.set(data, forKey: defaultsKey)
        }
    }
}
