import SwiftUI

/// Payload returned by `EditItemSheet.onSave`. The dashboard view model
/// forwards each field to `PATCH /api/items`.
struct EditItemPayload {
    let title: String
    let summary: String
    /// `nil` means "no change" — the picker landed in the "Custom…" slot
    /// but the user left the text field empty.
    let category: String?
}

/// Modal that lets the user edit the title, summary, and category of one
/// stored item.
///
///   - Title and Summary are plain editable strings.
///   - Category is a `Picker` over `knownCategories` plus a "Custom…"
///     option that reveals a free-text field so the user can either
///     reassign to an existing dynamic category or invent a brand new one.
struct EditItemSheet: View {
    @Environment(\.dismiss) private var dismiss

    let hit: SearchHit
    let knownCategories: [String]
    let onSave: (EditItemPayload) async -> Void

    @State private var title: String
    @State private var summary: String
    @State private var categorySelection: String
    @State private var customCategory: String
    @State private var isSaving = false

    /// Sentinel value for the Picker's "Custom…" slot. Empty string is
    /// safe because we never store an item with category="".
    private let customSentinel = "__custom__"

    init(
        hit: SearchHit,
        knownCategories: [String],
        onSave: @escaping (EditItemPayload) async -> Void
    ) {
        self.hit = hit
        self.knownCategories = knownCategories
        self.onSave = onSave
        _title = State(initialValue: hit.metadata.title ?? "")
        _summary = State(initialValue: hit.summary ?? "")

        let currentCat = hit.category ?? ""
        if knownCategories.contains(currentCat) {
            _categorySelection = State(initialValue: currentCat)
            _customCategory = State(initialValue: "")
        } else if !currentCat.isEmpty {
            // The row's category isn't in the known list — drop straight
            // into custom mode pre-filled with the current value.
            _categorySelection = State(initialValue: "__custom__")
            _customCategory = State(initialValue: currentCat)
        } else {
            _categorySelection = State(initialValue: "__custom__")
            _customCategory = State(initialValue: "")
        }
    }

    /// The string we actually send on save.
    private var resolvedCategory: String {
        if categorySelection == customSentinel {
            return customCategory.trimmingCharacters(in: .whitespacesAndNewlines)
        }
        return categorySelection
    }

    private var canSave: Bool {
        if isSaving { return false }
        if categorySelection == customSentinel && resolvedCategory.isEmpty {
            return false
        }
        return true
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Title") {
                    TextField("Title", text: $title, axis: .vertical)
                        .lineLimit(1...3)
                }

                Section("Summary") {
                    TextField("Summary", text: $summary, axis: .vertical)
                        .lineLimit(2...8)
                }

                Section("Category") {
                    Picker("Category", selection: $categorySelection) {
                        ForEach(knownCategories, id: \.self) { cat in
                            Text(cat).tag(cat)
                        }
                        Text("Custom…").tag(customSentinel)
                    }
                    .pickerStyle(.menu)

                    if categorySelection == customSentinel {
                        TextField("New category", text: $customCategory)
                            .textInputAutocapitalization(.words)
                            .autocorrectionDisabled()
                    }
                }

                Section {
                    if let target = URL(string: hit.url) {
                        Link(destination: target) {
                            Label("Open in Safari", systemImage: "safari")
                        }
                    }
                    Text(hit.url)
                        .font(.caption2.monospaced())
                        .foregroundStyle(.tertiary)
                        .textSelection(.enabled)
                }
            }
            .navigationTitle("Edit Item")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(isSaving ? "Saving…" : "Save") {
                        Task {
                            isSaving = true
                            let payload = EditItemPayload(
                                title: title.trimmingCharacters(in: .whitespacesAndNewlines),
                                summary: summary.trimmingCharacters(in: .whitespacesAndNewlines),
                                category: resolvedCategory.isEmpty ? nil : resolvedCategory
                            )
                            await onSave(payload)
                            dismiss()
                        }
                    }
                    .disabled(!canSave)
                }
            }
        }
    }
}
