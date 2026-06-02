import SwiftUI

// MARK: - Brand palette

enum Brand {
    static let electricBlue   = Color(red: 62/255,  green: 134/255, blue: 248/255)
    static let gradientTop    = Color(red: 10/255,  green:  32/255, blue:  92/255)
    static let gradientBottom = Color(red: 62/255,  green: 134/255, blue: 248/255)
    static let midnightDeep   = Color(red:  5/255,  green:   8/255, blue:  24/255)
    static let midnightMid    = Color(red:  8/255,  green:  15/255, blue:  42/255)
    static let cardBackground = Color(red: 14/255,  green:  22/255, blue:  55/255)
    static let cardBorder     = Color(red: 62/255,  green: 134/255, blue: 248/255).opacity(0.28)

    static let logoGradient = LinearGradient(
        colors: [gradientTop, gradientBottom],
        startPoint: .top, endPoint: .bottom
    )
    static let appBackground = LinearGradient(
        colors: [midnightDeep, midnightMid],
        startPoint: .top, endPoint: .bottom
    )
}

// MARK: - Source filter model

enum ContentSource: String, CaseIterable, Identifiable {
    case all       = "All"
    case instagram = "Instagram"
    case tiktok    = "TikTok"
    case youtube   = "YouTube"
    case article   = "Article"

    var id: String { rawValue }

    var systemImage: String {
        switch self {
        case .all:       return "rectangle.grid.2x2.fill"
        case .instagram: return "camera.fill"
        case .tiktok:    return "music.note.tv.fill"
        case .youtube:   return "play.rectangle.fill"
        case .article:   return "doc.text.fill"
        }
    }

    /// Infer the platform from the item URL. Falls back to `.article` for
    /// anything that isn't a recognised social/video host.
    static func detect(url: String, sourceType: String?) -> ContentSource {
        guard let urlObj = URL(string: url),
              let host = urlObj.host?.lowercased() else { return .article }
        if host.contains("instagram.com") || host.contains("instagr.am") { return .instagram }
        if host.contains("tiktok.com")                                   { return .tiktok }
        if host.contains("youtube.com") || host.contains("youtu.be")     { return .youtube }
        return .article
    }
}

// MARK: - View model

@MainActor
final class DashboardViewModel: ObservableObject {
    @Published var categories: [String] = []
    @Published var selectedCategory: String? = nil
    @Published var selectedSource: ContentSource = .all
    @Published var query: String = ""
    @Published var hits: [SearchHit] = []
    @Published var isLoading: Bool = false
    @Published var errorMessage: String? = nil
    @Published var itemsIndexed: Int = 0
    @Published var editingHit: SearchHit? = nil

    /// Client-side source filter applied on top of `hits`. Computed so it
    /// automatically reflects any `hits` or `selectedSource` change.
    var filteredHits: [SearchHit] {
        guard selectedSource != .all else { return hits }
        return hits.filter { hit in
            ContentSource.detect(url: hit.url, sourceType: hit.metadata.sourceType) == selectedSource
        }
    }

    // MARK: - Fetch

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
            await selectCategory(selectedCategory)
            return
        }
        await runSearch(originalQuery: trimmed, category: selectedCategory,
                        limit: 20, mode: .userQuery)
    }

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

    enum SearchMode { case userQuery, categoryBrowse }

    private func runSearch(
        originalQuery: String,
        category: String?,
        limit: Int,
        mode: SearchMode
    ) async {
        isLoading = true
        defer { isLoading = false }
        do {
            let resp = try await NetworkManager.shared.search(
                query: originalQuery, category: category, limit: limit
            )
            switch mode {
            case .categoryBrowse:
                // Newest first — sort by the created_at Unix timestamp stored at
                // ingest time. Items without the field (legacy rows) go to the end.
                hits = resp.hits.sorted {
                    ($0.metadata.createdAt ?? 0) > ($1.metadata.createdAt ?? 0)
                }
            case .userQuery:
                hits = Self.hybridRank(resp.hits, query: originalQuery)
            }
        } catch {
            hits = []
            errorMessage = error.localizedDescription
        }
    }

    private static func hybridRank(_ hits: [SearchHit], query: String) -> [SearchHit] {
        let queryWords = query
            .lowercased()
            .split(whereSeparator: { !$0.isLetter && !$0.isNumber })
            .map(String.init)
            .filter { $0.count >= 2 }
        guard !queryWords.isEmpty else { return hits }

        struct Scored { let hit: SearchHit; let score: Double; let keywordMatches: Int }
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

    // MARK: - Mutations

    func deleteHit(_ hit: SearchHit) async {
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

            let categoryChanged = payload.category != nil && payload.category != original.category

            if let updated = resp.item, let i = hits.firstIndex(where: { $0.url == original.url }) {
                if categoryChanged, let sel = selectedCategory, updated.category != sel {
                    // Item moved to a different category while we're browsing a
                    // specific one — remove it from the visible list immediately.
                    hits.remove(at: i)
                } else {
                    hits[i] = updated
                }
            }

            // Refresh the category chips on any category change so that:
            // • newly invented categories appear as chips
            // • chips whose last item just moved away are removed
            if categoryChanged {
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

    func moveCategoryToGeneral(oldName: String) async {
        do {
            _ = try await NetworkManager.shared.renameCategory(
                oldName: oldName, newName: "General")
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

    func addManualItem(_ draft: ManualItemDraft) async {
        do {
            _ = try await NetworkManager.shared.createManualItem(
                url: draft.url,
                title: draft.title,
                summary: draft.summary,
                category: draft.category
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

// MARK: - Brand logo tile

/// Mini-bookmark tile that matches the Home-Screen app icon. The blue glow
/// shadow ties it visually to the electric-blue brand palette.
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
        .shadow(color: Brand.electricBlue.opacity(0.40), radius: 10, y: 4)
    }
}

// MARK: - Root view

struct ContentView: View {
    @StateObject private var vm = DashboardViewModel()
    @StateObject private var iconStore = CategoryIconStore()

    @State private var editingCategory: EditingCategory? = nil
    @State private var deleteCategoryTarget: String? = nil
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

                Section {
                    sourceFilterBar
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: 0, leading: 16, bottom: 8, trailing: 16))
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
                            .tint(Brand.electricBlue)
                            .listRowBackground(Color.clear)
                            .listRowSeparator(.hidden)
                    } else if vm.filteredHits.isEmpty {
                        emptyState
                            .listRowBackground(Color.clear)
                            .listRowSeparator(.hidden)
                    } else {
                        resultsHeader
                            .listRowBackground(Color.clear)
                            .listRowSeparator(.hidden)
                            .listRowInsets(EdgeInsets(top: 0, leading: 16, bottom: 4, trailing: 16))
                        ForEach(vm.filteredHits) { hit in
                            SearchResultRow(hit: hit)
                                .listRowBackground(Color.clear)
                                .listRowSeparator(.hidden)
                                .listRowInsets(EdgeInsets(top: 5, leading: 16, bottom: 5, trailing: 16))
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
                                    .tint(Brand.electricBlue)
                                }
                                .contextMenu {
                                    if let target = URL(string: hit.url) {
                                        Link(destination: target) {
                                            Label("Open in Safari", systemImage: "safari")
                                        }
                                    }
                                    Button { vm.editingHit = hit } label: {
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
            .scrollContentBackground(.hidden)
            .background(Brand.appBackground.ignoresSafeArea())
            .navigationTitle("Smart Saver")
            .searchable(
                text: $vm.query,
                placement: .navigationBarDrawer(displayMode: .always),
                prompt: "Search saved items semantically…"
            )
            .onSubmit(of: .search) {
                Task { await vm.performSearch() }
            }
            .task { await vm.refresh() }
            .refreshable { await vm.refresh() }
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        isShowingAddSheet = true
                    } label: {
                        Image(systemName: "plus")
                            .fontWeight(.semibold)
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
                EditItemSheet(hit: hit, knownCategories: vm.categories) { payload in
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
        .preferredColorScheme(.dark)
        .tint(Brand.electricBlue)
        .environmentObject(iconStore)
    }

    // MARK: - Subviews

    private var brandingHeader: some View {
        HStack(spacing: 14) {
            BookmarkLogo(size: 52)
            VStack(alignment: .leading, spacing: 3) {
                Text("Smart Saver")
                    .font(.title2.weight(.bold))
                    .foregroundStyle(.white)
                Text("Your second brain for saved links")
                    .font(.caption)
                    .foregroundStyle(Color.white.opacity(0.50))
            }
            Spacer()
        }
    }

    private var headerSummary: some View {
        HStack {
            Text("\(vm.itemsIndexed) items · \(vm.categories.count) categories")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(Color.white.opacity(0.40))
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
                .tint(Brand.electricBlue)
            }
        }
    }

    private var categoryGrid: some View {
        LazyVGrid(
            columns: [GridItem(.adaptive(minimum: 150), spacing: 10)],
            spacing: 10
        ) {
            CategoryCard(
                label: "All",
                count: vm.itemsIndexed,
                isSelected: vm.selectedCategory == nil,
                onTap: { Task { await vm.selectCategory(nil) } }
            )
            ForEach(vm.categories, id: \.self) { cat in
                CategoryCard(
                    label: cat,
                    isSelected: vm.selectedCategory == cat,
                    onTap: { Task { await vm.selectCategory(cat) } },
                    onRename: { editingCategory = EditingCategory(name: cat) },
                    onDelete: { deleteCategoryTarget = cat }
                )
            }
        }
    }

    /// Horizontal pill row for filtering by content source (Instagram, TikTok,
    /// YouTube, Article). Client-side only — no extra network call.
    private var sourceFilterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(ContentSource.allCases) { source in
                    let selected = vm.selectedSource == source
                    Button {
                        vm.selectedSource = source
                    } label: {
                        HStack(spacing: 5) {
                            Image(systemName: source.systemImage)
                                .font(.caption.weight(.semibold))
                            Text(source.rawValue)
                                .font(.subheadline.weight(.semibold))
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 7)
                        .background(
                            Capsule()
                                .fill(selected
                                      ? Brand.electricBlue
                                      : Color.white.opacity(0.09))
                        )
                        .foregroundStyle(selected ? Color.white : Color.white.opacity(0.60))
                        .overlay(
                            Capsule()
                                .stroke(
                                    selected ? Color.clear : Color.white.opacity(0.15),
                                    lineWidth: 1
                                )
                        )
                        .animation(.easeInOut(duration: 0.18), value: vm.selectedSource)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 2)
            .padding(.vertical, 2)
        }
    }

    private var resultsHeader: some View {
        HStack(spacing: 6) {
            Text(vm.selectedCategory ?? (vm.query.isEmpty ? "All items" : "Results"))
                .font(.title3.weight(.bold))
                .foregroundStyle(.white)
            Text("(\(vm.filteredHits.count))")
                .font(.subheadline)
                .foregroundStyle(Color.white.opacity(0.40))
            Spacer()
        }
    }

    private var emptyState: some View {
        VStack(spacing: 10) {
            Image(systemName: "tray")
                .font(.system(size: 44))
                .foregroundStyle(Color.white.opacity(0.30))
            Text("Nothing to show yet")
                .font(.headline)
                .foregroundStyle(.white)
            Text(vm.query.isEmpty
                 ? "Share a link from Safari or Instagram to seed your library."
                 : "No matches for \"\(vm.query)\".")
                .font(.subheadline)
                .foregroundStyle(Color.white.opacity(0.50))
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
                .fill(Color.red.opacity(0.85))
        )
    }
}

#Preview {
    ContentView()
}
