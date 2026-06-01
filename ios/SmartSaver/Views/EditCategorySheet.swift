import SwiftUI

/// Identifiable wrapper so we can drive `.sheet(item:)` off a String.
struct EditingCategory: Identifiable {
    let id = UUID()
    let name: String
}

/// Sheet that lets the user rename a category and / or pick a custom
/// SF Symbol for it. Submits the rename through `onRename` which fires
/// `PATCH /api/categories` on the backend; the icon override is purely
/// local (UserDefaults via `CategoryIconStore`).
struct EditCategorySheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var iconStore: CategoryIconStore

    let originalName: String
    /// Async callback invoked when the name actually changed. Receives
    /// the trimmed new label.
    let onRename: (_ newName: String) async -> Void

    @State private var newName: String
    @State private var selectedSymbol: String?
    @State private var isSaving = false

    /// Curated palette covering Smart Saver's common categories plus
    /// generic-purpose fallbacks. Keeps the picker tidy — we don't ship
    /// a full SF Symbols browser.
    private static let palette: [String] = [
        "tag.fill", "house.fill", "hammer.fill", "dollarsign.circle.fill",
        "airplane", "briefcase.fill", "fork.knife", "figure.run",
        "newspaper.fill", "graduationcap.fill", "music.note", "tshirt.fill",
        "gamecontroller.fill", "camera.fill", "rocket.fill", "heart.fill",
        "book.fill", "cart.fill", "leaf.fill", "globe", "lightbulb.fill",
        "wand.and.stars", "paintpalette.fill", "popcorn.fill",
        "wrench.adjustable", "mappin.and.ellipse", "person.2.fill",
        "calendar", "envelope.fill", "video.fill",
    ]

    init(
        originalName: String,
        onRename: @escaping (String) async -> Void
    ) {
        self.originalName = originalName
        self.onRename = onRename
        _newName = State(initialValue: originalName)
    }

    private var trimmedName: String {
        newName.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private var nameWillChange: Bool {
        !trimmedName.isEmpty && trimmedName != originalName
    }

    private var iconWillChange: Bool {
        let stored = iconStore.icon(for: originalName)
        return selectedSymbol != stored
    }

    private var canSave: Bool {
        !isSaving && !trimmedName.isEmpty && (nameWillChange || iconWillChange)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Name") {
                    TextField("Category name", text: $newName)
                        .textInputAutocapitalization(.words)
                        .autocorrectionDisabled()
                }

                Section {
                    LazyVGrid(
                        columns: [GridItem(.adaptive(minimum: 52), spacing: 10)],
                        spacing: 10
                    ) {
                        ForEach(Self.palette, id: \.self) { symbol in
                            symbolCell(symbol)
                        }
                    }
                    .padding(.vertical, 4)

                    if selectedSymbol != nil {
                        Button("Use default icon", role: .destructive) {
                            selectedSymbol = nil
                        }
                    }
                } header: {
                    Text("Icon")
                } footer: {
                    Text("Stored on this device only — the backend keeps using the category name.")
                }
            }
            .navigationTitle("Edit category")
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
                selectedSymbol = iconStore.icon(for: originalName)
            }
        }
    }

    // MARK: - Subviews

    private func symbolCell(_ symbol: String) -> some View {
        let isPicked = (selectedSymbol == symbol)
        return Button {
            selectedSymbol = symbol
        } label: {
            Image(systemName: symbol)
                .font(.title3)
                .frame(width: 44, height: 44)
                .foregroundStyle(isPicked ? .white : Color.primary)
                .background(
                    Circle().fill(isPicked
                                  ? Color.accentColor
                                  : Color(.tertiarySystemFill))
                )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(symbol))
        .accessibilityAddTraits(isPicked ? .isSelected : [])
    }

    // MARK: - Commit

    @MainActor
    private func commit() async {
        isSaving = true
        defer { isSaving = false }

        // Persist the icon under the (possibly new) name. If only the
        // icon changed, also store it under the original name so the
        // card reflects the change immediately.
        let finalName = nameWillChange ? trimmedName : originalName

        if nameWillChange {
            // Migrate any pre-existing icon under the OLD name first,
            // then optionally overlay the user's new pick.
            iconStore.renameCategory(from: originalName, to: trimmedName)
        }
        if let symbol = selectedSymbol {
            iconStore.setIcon(symbol, for: finalName)
        } else {
            iconStore.clearIcon(for: finalName)
        }

        if nameWillChange {
            await onRename(trimmedName)
        }

        dismiss()
    }
}
