import SwiftUI

// MARK: - View model

@MainActor
final class DashboardViewModel: ObservableObject {
    @Published var categories: [String] = []
    @Published var selectedCategory: String? = nil
    @Published var query: String = ""
    @Published var hits: [SearchHit] = []
    @Published var isLoading: Bool = false
    @Published var errorMessage: String? = nil
    @Published var itemsIndexed: Int = 0
    @Published var editingHit: SearchHit? = nil

    // MARK: - Fetch

    /// Pull the dashboard's primitives (categories + item count) and
    /// re-execute whatever view the user currently has on screen so
    /// counts, badges, and lists are in sync after a mutation.
    func refresh() async {
        errorMessage = nil
        do {
            async let cats = NetworkManager.shared.fetchCategories()
            async let h = NetworkManager.shared.health()
            self.categories = try await cats
            self.itemsIndexed = try await h.itemsIndexed
        } catch {
            errorMessage = error.localizedDescription
        }
        await reloadCurrentView()
    }

    /// Re-run the search/browse for whatever the user has on screen now.
    private func reloadCurrentView() async {
        if let q = query.trimmingCharacters(in: .whitespacesAndNewlines).nonEmpty {
            await runSearch(originalQuery: q, category: selectedCategory,
                            limit: 20, mode: .userQuery)
        } else {
            await runSearch(originalQuery: "everything",
                            category: selectedCategory,
                            limit: 100, mode: .categoryBrowse)
        }
    }

    func performSearch() async {
        let trimmed = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            // Empty search bar → fall back to the All/category browse view.
            await selectCategory(selectedCategory)
            return
        }
        await runSearch(originalQuery: trimmed, category: selectedCategory,
                        limit: 20, mode: .userQuery)
    }

    /// Tapping a category card. `nil` means the "All" tile — show every
    /// item in the library (the Step-7 fix is here: previously this
    /// cleared the hit list instead of loading everything).
    func selectCategory(_ category: String?) async {
        selectedCategory = category
        if let q = query.trimmingCharacters(in: .whitespacesAndNewlines).nonEmpty {
            await runSearch(originalQuery: q, category: category,
                            limit: 20, mode: .userQuery)
        } else {
            await runSearch(originalQuery: "everything",
                            category: category,
                            limit: 100, mode: .categoryBrowse)
        }
    }

    enum SearchMode {
        case userQuery
        case categoryBrowse
    }

    private func runSearch(originalQuery: String, category: String?, limit: Int, mode: SearchMode) async {
        isLoading = true
        defer { isLoading = false }
        do {
            let resp = try await NetworkManager.shared.search(
                query: originalQuery, category: category, limit: limit
            )
            switch mode {
            case .categoryBrowse:
                hits = resp.hits
            case .userQuery:
                hits = Self.hybridRank(resp.hits, query: originalQuery)
            }
        } catch {
            hits = []
            errorMessage = error.localizedDescription
        }
    }

    /// Hybrid keyword + semantic ranking. See the Step-5 commentary in
    /// claude.md §6.8 — the keyword bonus catches "vietnam" hits whose
    /// title is "Hạ Long Bay" but whose summary mentions Vietnam.
    private static func hybridRank(_ hits: [SearchHit], query: String) -> [SearchHit] {
        let queryWords = query
            .lowercased()
            .split(whereSeparator: { !$0.isLetter && !$0.isNumber })
            .map(String.init)
            .filter { $0.count >= 2 }
        guard !queryWords.isEmpty else { return hits }

        struct Scored {
            let hit: SearchHit
            let score: Double
            let keywordMatches: Int
        }
        let scored: [Scored] = hits.map { hit in
            let haystack = [
                hit.metadata.title ?? "",
                hit.summary ?? "",
                hit.metadata.location ?? "",
                hit.metadata.category ?? "",
                hit.metadata.technologies ?? "",
            ].joined(separator: " ").lowercased()
            let matches = queryWords.reduce(0) { count, word in
                haystack.contains(word) ? count + 1 : count
            }
            let semantic = max(0.0, 1.0 - (hit.distance ?? 1.0))
            let total = semantic + 0.5 * Double(matches)
            return Scored(hit: hit, score: total, keywordMatches: matches)
        }
        let kept = scored.filter { $0.keywordMatches > 0 || $0.score >= 0.3 }
        return kept.sorted { $0.score > $1.score }.map(\.hit)
    }

    // MARK: - Mutations (Step 7)

    func deleteHit(_ hit: SearchHit) async {
        // Optimistic: drop from list + decrement count immediately, then
        // call the server. Re-sync from the server on failure.
        hits.removeAll { $0.url == hit.url }
        itemsIndexed = max(0, itemsIndexed - 1)
        do {
            _ = try await NetworkManager.shared.deleteItem(url: hit.url)
        } catch {
            errorMessage = "Couldn't delete: \(error.localizedDescription)"
            await refresh()
        }
    }

    func saveEdit(_ original: SearchHit, payload: EditItemPayload) async {
        do {
            let resp = try await NetworkManager.shared.updateItem(
                url: original.url,
                title: payload.title.isEmpty ? nil : payload.title,
                summary: payload.summary.isEmpty ? nil : payload.summary,
                category: payload.category
            )
            // Optimistic in-place patch of the visible row.
            if let updated = resp.item, let i = hits.firstIndex(where: { $0.url == original.url }) {
                hits[i] = updated
            }
            // Picker may have introduced a brand-new category → refresh chips.
            if let new = payload.category, !categories.contains(new) {
                if let cats = try? await NetworkManager.shared.fetchCategories() {
                    categories = cats
                }
            }
        } catch {
            errorMessage = "Couldn't save: \(error.localizedDescription)"
        }
    }

    func renameCategory(oldName: String, newName: String) async {
        do {
            _ = try await NetworkManager.shared.renameCategory(oldName: oldName, newName: newName)
            if selectedCategory == oldName { selectedCategory = newName }
            await refresh()
        } catch {
            errorMessage = "Couldn't rename: \(error.localizedDescription)"
        }
    }

    /// Smart-delete: move every item in `oldName` to "General" rather
    /// than wiping the rows. Implemented as a rename on the backend —
    /// `PATCH /api/categories` already does bulk-rewrite atomically.
    func moveCategoryToGeneral(oldName: String) async {
        do {
            _ = try await NetworkManager.shared.renameCategory(
                oldName: oldName, newName: "General",
            )
            if selectedCategory == oldName { selectedCategory = "General" }
            await refresh()
        } catch {
            errorMessage = "Couldn't move items: \(error.localizedDescription)"
        }
    }

    func deleteCategory(name: String) async {
        do {
            _ = try await NetworkManager.shared.deleteCategory(name: name)
            if selectedCategory == name { selectedCategory = nil }
            await refresh()
        } catch {
            errorMessage = "Couldn't delete category: \(error.localizedDescription)"
        }
    }

    /// Manual ingestion (Step 11) — fire `POST /api/items` and refresh.
    func addManualItem(_ draft: ManualItemDraft) async {
        do {
            _ = try await NetworkManager.shared.createManualItem(
                url: draft.url,
                title: draft.title,
                summary: draft.summary,
                category: draft.category,
            )
            await refresh()
        } catch {
            errorMessage = "Couldn't add item: \(error.localizedDescription)"
        }
    }
}

private extension String {
    var nonEmpty: String? { isEmpty ? nil : self }
}

// MARK: - Brand colors (match Assets.xcassets/AppIcon.appiconset gradient)

enum Brand {
    static let gradientTop    = Color(red:  10/255, green:  32/255, blue:  92/255)
    static let gradientBottom = Color(red:  62/255, green: 134/255, blue: 248/255)
    static let logoGradient = LinearGradient(
        colors: [gradientTop, gradientBottom],
        startPoint: .top, endPoint: .bottom
    )
}

/// Mini-bookmark tile that matches the Home-Screen app icon. Used as the
/// dashboard's branding anchor and inside any "feature header" view.
struct BookmarkLogo: View {
    var size: CGFloat = 56

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size * 0.25, style: .continuous)
                .fill(Brand.logoGradient)
            Image(systemName: "bookmark.fill")
                .font(.system(size: size * 0.50, weight: .semibold))
                .foregroundStyle(.white)
        }
        .frame(width: size, height: size)
        .shadow(color: .black.opacity(0.15), radius: 4, y: 2)
    }
}

// MARK: - Root view

struct ContentView: View {
    @StateObject private var vm = DashboardViewModel()
    @StateObject private var iconStore = CategoryIconStore()

    // Category-management modal state. `editingCategory` drives the
    // EditCategorySheet (Identifiable so .sheet(item:) binds cleanly);
    // `deleteCategoryTarget` drives the smart-delete alert.
    @State private var editingCategory: EditingCategory? = nil
    @State private var deleteCategoryTarget: String? = nil
    // Step 11 — manual ingestion. + button toggles this.
    @State private var isShowingAddSheet: Bool = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    brandingHeader
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: 6, leading: 16, bottom: 4, trailing: 16))
                    headerSummary
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: 0, leading: 16, bottom: 6, trailing: 16))
                }

                Section {
                    categoryGrid
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: 0, leading: 16, bottom: 12, trailing: 16))
                }

                if let err = vm.errorMessage {
                    Section {
                        errorBanner(err)
                            .listRowBackground(Color.clear)
                            .listRowSeparator(.hidden)
                            .listRowInsets(EdgeInsets(top: 0, leading: 16, bottom: 8, trailing: 16))
                    }
                }

                Section {
                    if vm.isLoading {
                        ProgressView()
                            .frame(maxWidth: .infinity)
                            .padding(.top, 24)
                            .listRowBackground(Color.clear)
                            .listRowSeparator(.hidden)
                    } else if vm.hits.isEmpty {
                        emptyState
                            .listRowBackground(Color.clear)
                            .listRowSeparator(.hidden)
                    } else {
                        resultsHeader
                            .listRowBackground(Color.clear)
                            .listRowSeparator(.hidden)
                            .listRowInsets(EdgeInsets(top: 0, leading: 16, bottom: 4, trailing: 16))
                        ForEach(vm.hits) { hit in
                            SearchResultRow(hit: hit)
                                .listRowBackground(Color.clear)
                                .listRowSeparator(.hidden)
                                .listRowInsets(EdgeInsets(top: 6, leading: 16, bottom: 6, trailing: 16))
                                .contentShape(Rectangle())
                                .onTapGesture { vm.editingHit = hit }
                                .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                    Button(role: .destructive) {
                                        Task { await vm.deleteHit(hit) }
                                    } label: {
                                        Label("Delete", systemImage: "trash")
                                    }
                                }
                                .swipeActions(edge: .leading, allowsFullSwipe: false) {
                                    Button {
                                        vm.editingHit = hit
                                    } label: {
                                        Label("Edit", systemImage: "pencil")
                                    }
                                    .tint(.blue)
                                }
                                .contextMenu {
                                    if let target = URL(string: hit.url) {
                                        Link(destination: target) {
                                            Label("Open in Safari", systemImage: "safari")
                                        }
                                    }
                                    Button {
                                        vm.editingHit = hit
                                    } label: {
                                        Label("Edit", systemImage: "pencil")
                                    }
                                    Button(role: .destructive) {
                                        Task { await vm.deleteHit(hit) }
                                    } label: {
                                        Label("Delete", systemImage: "trash")
                                    }
                                }
                        }
                    }
                }
            }
            .listStyle(.plain)
            .navigationTitle("Smart Saver")
            .searchable(
                text: $vm.query,
                placement: .navigationBarDrawer(displayMode: .always),
                prompt: "Search saved items semantically…"
            )
            .onSubmit(of: .search) {
                Task { await vm.performSearch() }
            }
            .task {
                await vm.refresh()
            }
            .refreshable {
                await vm.refresh()
            }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        isShowingAddSheet = true
                    } label: {
                        Image(systemName: "plus")
                    }
                    .accessibilityLabel("Add item manually")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await vm.refresh() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("Refresh")
                }
            }
            .sheet(item: $vm.editingHit) { hit in
                EditItemSheet(
                    hit: hit,
                    knownCategories: vm.categories
                ) { payload in
                    await vm.saveEdit(hit, payload: payload)
                }
            }
            .sheet(item: $editingCategory) { target in
                EditCategorySheet(originalName: target.name) { newName in
                    await vm.renameCategory(oldName: target.name, newName: newName)
                }
                .environmentObject(iconStore)
            }
            .sheet(isPresented: $isShowingAddSheet) {
                AddItemSheet(knownCategories: vm.categories) { draft in
                    await vm.addManualItem(draft)
                }
            }
            // Smart category deletion (Step 11). When the user taps the
            // trash icon on a category card, we offer two non-destructive
            // outcomes side-by-side: move the items to General, or wipe
            // them. The default cancel option keeps the destructive
            // action a deliberate two-tap path.
            .confirmationDialog(
                deleteCategoryTarget.map { "Delete \"\($0)\"?" } ?? "Delete category?",
                isPresented: Binding(
                    get: { deleteCategoryTarget != nil },
                    set: { if !$0 { deleteCategoryTarget = nil } }
                ),
                titleVisibility: .visible,
                presenting: deleteCategoryTarget
            ) { cat in
                Button("Move items to General") {
                    Task { await vm.moveCategoryToGeneral(oldName: cat) }
                }
                Button("Delete all content", role: .destructive) {
                    Task { await vm.deleteCategory(name: cat) }
                }
                Button("Cancel", role: .cancel) {}
            } message: { cat in
                Text("Items in \"\(cat)\" can be moved to a General bucket, or deleted along with the category.")
            }
        }
        // Resolve `@EnvironmentObject var iconStore: CategoryIconStore`
        // in CategoryCard. The sheet also injects this, but propagating
        // at the NavigationStack level keeps the grid cells working
        // without each one having to thread it through.
        .environmentObject(iconStore)
    }

    // MARK: - Subviews

    private var brandingHeader: some View {
        HStack(spacing: 14) {
            BookmarkLogo(size: 56)
            VStack(alignment: .leading, spacing: 2) {
                Text("Smart Saver")
                    .font(.title2.weight(.bold))
                Text("Your second brain for saved links")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
    }

    private var headerSummary: some View {
        HStack {
            Text("\(vm.itemsIndexed) items · \(vm.categories.count) categories")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(.secondary)
            Spacer()
            if vm.selectedCategory != nil {
                Button {
                    Task { await vm.selectCategory(nil) }
                } label: {
                    Label("Clear filter", systemImage: "xmark.circle.fill")
                        .font(.caption.weight(.semibold))
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
        }
    }

    private var categoryGrid: some View {
        LazyVGrid(
            columns: [GridItem(.adaptive(minimum: 150), spacing: 10)],
            spacing: 10
        ) {
            // "All" is synthetic — no edit / delete buttons.
            CategoryCard(
                label: "All",
                count: vm.itemsIndexed,
                isSelected: vm.selectedCategory == nil,
                onTap: { Task { await vm.selectCategory(nil) } }
            )
            ForEach(vm.categories, id: \.self) { cat in
                // Each closure captures `cat` literally at construction
                // time. CategoryCard renders inline pencil + trash icons
                // whose Button views consume their own taps — there is
                // no long-press / contextMenu involved any more (the
                // Step 8 misattribution bug is gone for good).
                CategoryCard(
                    label: cat,
                    isSelected: vm.selectedCategory == cat,
                    onTap: { Task { await vm.selectCategory(cat) } },
                    onRename: {
                        editingCategory = EditingCategory(name: cat)
                    },
                    onDelete: {
                        deleteCategoryTarget = cat
                    }
                )
            }
        }
    }

    private var resultsHeader: some View {
        HStack(spacing: 6) {
            Text(vm.selectedCategory ?? (vm.query.isEmpty ? "All items" : "Results"))
                .font(.title3.weight(.bold))
            Text("(\(vm.hits.count))")
                .font(.subheadline)
                .foregroundStyle(.secondary)
            Spacer()
        }
    }

    private var emptyState: some View {
        VStack(spacing: 10) {
            Image(systemName: "tray")
                .font(.system(size: 44))
                .foregroundStyle(.secondary)
            Text("Nothing to show yet")
                .font(.headline)
            Text(vm.query.isEmpty
                 ? "Share a link from Safari or Instagram to seed your library."
                 : "No matches for \"\(vm.query)\".")
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 60)
    }

    private func errorBanner(_ message: String) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.octagon.fill")
                .foregroundStyle(.white)
            VStack(alignment: .leading, spacing: 2) {
                Text("Server error")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.white)
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.9))
                    .lineLimit(3)
            }
            Spacer()
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color.red.opacity(0.9))
        )
    }
}

#Preview {
    ContentView()
}
