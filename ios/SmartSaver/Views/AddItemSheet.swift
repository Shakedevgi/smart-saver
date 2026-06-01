import SwiftUI

/// Modal launched from the dashboard's "+" toolbar button. The user
/// fills in URL, title, summary, and category — Save fires
/// `POST /api/items`, which bypasses the extractor + LLM pipeline and
/// directly inserts a `status="completed"` row.
///
/// Auto-prepends `https://` when the user types a bare host so the
/// backend's URL classifier doesn't bounce the request as UNKNOWN.
struct AddItemSheet: View {
    @Environment(\.dismiss) private var dismiss

    let knownCategories: [String]
    let onSave: (ManualItemDraft) async -> Void

    @State private var url = ""
    @State private var title = ""
    @State private var summary = ""
    @State private var categorySelection: String = ""
    @State private var customCategory = ""
    @State private var isSaving = false

    /// Sentinel used as the picker's "Custom…" tag. Real category
    /// names never collide with this.
    private let customSentinel = "__custom__"

    init(knownCategories: [String], onSave: @escaping (ManualItemDraft) async -> Void) {
        self.knownCategories = knownCategories
        self.onSave = onSave
    }

    private var resolvedCategory: String {
        if categorySelection == customSentinel {
            return customCategory.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return categorySelection
    }

    private var normalizedURL: String {
        let trimmed = url.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return "" }
        if trimmed.lowercased().hasPrefix("http://") || trimmed.lowercased().hasPrefix("https://") {
            return trimmed
        }
        return "https://" + trimmed
    }

    private var canSave: Bool {
        guard !isSaving else { return false }
        guard !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return false }
        guard !normalizedURL.isEmpty else { return false }
        guard !resolvedCategory.isEmpty else { return false }
        return true
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://…", text: $url)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("Link")
                } footer: {
                    Text("Plain `example.com/foo` works too — we'll prepend `https://`.")
                }

                Section("Title") {
                    TextField("What is this?", text: $title, axis: .vertical)
                        .lineLimit(1...3)
                }

                Section("Summary") {
                    TextField("Why this matters / what to remember", text: $summary, axis: .vertical)
                        .lineLimit(2...8)
                }

                Section("Category") {
                    Picker("Category", selection: $categorySelection) {
                        ForEach(knownCategories, id: \.self) { cat in
                            Text(cat).tag(cat)
                        }
                        Text("New category…").tag(customSentinel)
                    }
                    .pickerStyle(.menu)

                    if categorySelection == customSentinel {
                        TextField("New category", text: $customCategory)
                            .textInputAutocapitalization(.words)
                            .autocorrectionDisabled()
                    }
                }
            }
            .navigationTitle("Add Item")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Saving…" : "Save") {
                        Task { await commit() }
                    }
                    .disabled(!canSave)
                }
            }
            .onAppear {
                // Default the picker to the first known category, or
                // straight to Custom… if the user has none yet.
                if categorySelection.isEmpty {
                    categorySelection = knownCategories.first ?? customSentinel
                }
            }
        }
    }

    @MainActor
    private func commit() async {
        isSaving = true
        defer { isSaving = false }
        let draft = ManualItemDraft(
            url: normalizedURL,
            title: title.trimmingCharacters(in: .whitespacesAndNewlines),
            summary: summary.trimmingCharacters(in: .whitespacesAndNewlines),
            category: resolvedCategory
        )
        await onSave(draft)
        dismiss()
    }
}

/// Plain struct passed from `AddItemSheet` back to the dashboard view
/// model. The view model forwards each field to
/// `NetworkManager.createManualItem`.
struct ManualItemDraft {
    let url: String
    let title: String
    let summary: String
    let category: String
}
