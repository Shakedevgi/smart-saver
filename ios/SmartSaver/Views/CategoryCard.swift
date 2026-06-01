import SwiftUI

/// One pill on the dashboard's category grid.
///
/// Step 9 redesign: no more long-press / `.contextMenu`. The card now uses
/// `.onTapGesture` for the select-filter action and renders inline pencil
/// + trash icon buttons for rename / delete. Because the icon buttons are
/// independent `Button` views, their hit-testing is unambiguous — taps on
/// them never bubble up to the outer select gesture.
struct CategoryCard: View {
    let label: String
    let count: Int?
    let isSelected: Bool
    let onTap: () -> Void
    let onRename: (() -> Void)?
    let onDelete: (() -> Void)?

    /// Icon override pulled from the local store. Falls back to a
    /// derived-from-label SF Symbol when nil.
    @EnvironmentObject private var iconStore: CategoryIconStore

    init(
        label: String,
        count: Int? = nil,
        isSelected: Bool,
        onTap: @escaping () -> Void,
        onRename: (() -> Void)? = nil,
        onDelete: (() -> Void)? = nil
    ) {
        self.label = label
        self.count = count
        self.isSelected = isSelected
        self.onTap = onTap
        self.onRename = onRename
        self.onDelete = onDelete
    }

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: resolvedIconName)
                .font(.title3)
                .foregroundStyle(isSelected ? Color.white : Color.accentColor)
                .frame(width: 24, alignment: .leading)

            Text(label)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(isSelected ? Color.white : Color.primary)
                .lineLimit(1)

            Spacer(minLength: 0)

            if let count = count {
                Text("\(count)")
                    .font(.caption.weight(.bold))
                    .foregroundStyle(isSelected ? Color.white : Color.accentColor)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(
                        Capsule()
                            .fill(isSelected
                                  ? Color.white.opacity(0.22)
                                  : Color.accentColor.opacity(0.15))
                    )
            }

            actionButtons
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .fill(isSelected ? Color.accentColor : Color(.secondarySystemBackground))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(isSelected ? Color.accentColor : Color.clear, lineWidth: 1)
        )
        // Select-filter on tap. Button taps (pencil/trash) consume their
        // own gesture so this never fires for them.
        .contentShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
        .onTapGesture(perform: onTap)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(Text("\(label) category. \(isSelected ? "Selected" : "Tap to filter")"))
    }

    @ViewBuilder
    private var actionButtons: some View {
        if onRename != nil || onDelete != nil {
            HStack(spacing: 2) {
                if let onRename = onRename {
                    iconButton(systemName: "square.and.pencil",
                               accessibilityLabel: "Edit \(label)",
                               action: onRename)
                }
                if let onDelete = onDelete {
                    iconButton(systemName: "trash",
                               accessibilityLabel: "Delete \(label)",
                               role: .destructive,
                               action: onDelete)
                }
            }
        }
    }

    private func iconButton(
        systemName: String,
        accessibilityLabel: String,
        role: ButtonRole? = nil,
        action: @escaping () -> Void
    ) -> some View {
        Button(role: role, action: action) {
            Image(systemName: systemName)
                .font(.footnote.weight(.semibold))
                .frame(width: 28, height: 28)
                .foregroundStyle(iconForeground(role: role))
                .background(
                    Circle().fill(iconBackground)
                )
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(accessibilityLabel))
    }

    // MARK: - Visual helpers

    private var iconBackground: Color {
        isSelected ? Color.white.opacity(0.20) : Color(.tertiarySystemFill)
    }

    private func iconForeground(role: ButtonRole?) -> Color {
        if role == .destructive {
            return isSelected ? Color.white : Color.red
        }
        return isSelected ? Color.white : Color.accentColor
    }

    /// The SF Symbol to render. Honors the user's custom pick first, then
    /// falls back to a label-derived default.
    private var resolvedIconName: String {
        if let custom = iconStore.icon(for: label) {
            return custom
        }
        return Self.defaultIcon(for: label)
    }

    static func defaultIcon(for label: String) -> String {
        switch label.lowercased() {
        case "all":                            return "rectangle.grid.2x2.fill"
        case "real estate":                    return "house.fill"
        case "tech tools", "programming":      return "hammer.fill"
        case "finance":                        return "dollarsign.circle.fill"
        case "travel":                         return "airplane"
        case "career advice":                  return "briefcase.fill"
        case "recipes", "cooking", "food":     return "fork.knife"
        case "fitness", "workouts", "health":  return "figure.run"
        case "news":                           return "newspaper.fill"
        case "education", "learning":          return "graduationcap.fill"
        case "music":                          return "music.note"
        case "fashion":                        return "tshirt.fill"
        case "gaming", "games":                return "gamecontroller.fill"
        case "photography":                    return "camera.fill"
        case "startup stories", "startups":    return "rocket.fill"
        default:                               return "tag.fill"
        }
    }
}
