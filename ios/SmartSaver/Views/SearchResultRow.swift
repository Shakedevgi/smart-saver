import SwiftUI

/// One card in the dashboard's result list.
struct SearchResultRow: View {
    let hit: SearchHit

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if let title = hit.metadata.title, !title.isEmpty {
                Text(title)
                    .font(.headline)
                    .lineLimit(2)
            } else {
                Text(displayHost)
                    .font(.headline)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            if let summary = hit.summary, !summary.isEmpty {
                Text(summary)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }

            // Tag badges — horizontal scroll keeps wrapping simple on
            // very-long-tech-list items.
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    if hit.metadata.status == "processing" {
                        ProcessingBadge()
                    } else if hit.metadata.status == "failed" {
                        FailedBadge()
                    }
                    if let cat = hit.category, hit.metadata.status != "processing" {
                        TagBadge(text: cat, systemImage: "tag.fill", color: .accentColor)
                    }
                    if let loc = hit.metadata.location, !loc.isEmpty {
                        TagBadge(text: loc, systemImage: "mappin.and.ellipse", color: .blue)
                    }
                    if let price = hit.metadata.price, !price.isEmpty {
                        TagBadge(text: price, systemImage: "dollarsign.circle.fill", color: .green)
                    }
                    ForEach(hit.metadata.technologiesList, id: \.self) { tech in
                        TagBadge(text: tech, systemImage: "wrench.adjustable", color: .purple)
                    }
                    if hit.metadata.isUncertain == true {
                        UncertaintyBadge()
                    }
                }
                .padding(.horizontal, 1)
            }

            HStack(spacing: 6) {
                Image(systemName: hit.metadata.sourceType == "video" ? "play.rectangle.fill" : "doc.text.fill")
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                Text(hit.url)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer()
                if let dist = hit.distance {
                    Text(String(format: "•  d %.2f", dist))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Color(.secondarySystemBackground))
        )
        .overlay(
            // Outline the card in orange when the LLM was uncertain so the
            // user immediately spots it even from across the list. Yellow
            // outline takes precedence while the async pipeline is still
            // running on this item.
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(rowOutlineColor, lineWidth: 1.5)
        )
    }

    private var rowOutlineColor: Color {
        if hit.metadata.status == "processing" { return Color.yellow.opacity(0.6) }
        if hit.metadata.status == "failed" { return Color.red.opacity(0.55) }
        if hit.metadata.isUncertain == true { return Color.orange.opacity(0.6) }
        return Color.clear
    }

    private var displayHost: String {
        URL(string: hit.url)?.host ?? hit.url
    }
}

// MARK: - Badges

struct TagBadge: View {
    let text: String
    let systemImage: String
    let color: Color

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: systemImage).font(.caption2)
            Text(text).font(.caption.weight(.medium))
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 5)
        .background(color.opacity(0.18))
        .foregroundStyle(color)
        .clipShape(Capsule())
        .lineLimit(1)
    }
}

/// Shown while the async pipeline is still running on an item (Step 6).
/// Pulses subtly so the user knows it'll update on its own.
struct ProcessingBadge: View {
    @State private var pulse = false

    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: "hourglass")
                .font(.caption2)
            Text("Processing…")
                .font(.caption.weight(.semibold))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(Color.yellow.opacity(pulse ? 0.35 : 0.18))
        .foregroundStyle(Color.orange)
        .clipShape(Capsule())
        .overlay(Capsule().stroke(Color.yellow.opacity(0.6), lineWidth: 1))
        .onAppear {
            withAnimation(.easeInOut(duration: 1.1).repeatForever(autoreverses: true)) {
                pulse = true
            }
        }
    }
}

/// Shown for items whose background pipeline crashed.
struct FailedBadge: View {
    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: "xmark.octagon.fill")
                .font(.caption2)
            Text("Failed")
                .font(.caption.weight(.semibold))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(Color.red.opacity(0.18))
        .foregroundStyle(Color.red)
        .clipShape(Capsule())
        .overlay(Capsule().stroke(Color.red.opacity(0.55), lineWidth: 1))
    }
}

/// Prominent warning badge for `analysis.is_uncertain == true`. Step 2's
/// dynamic-categorisation contract says the iOS layer must surface this so
/// the user can disambiguate.
struct UncertaintyBadge: View {
    var body: some View {
        HStack(spacing: 5) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.caption2)
            Text("Needs Disambiguation")
                .font(.caption.weight(.semibold))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(Color.orange.opacity(0.22))
        .foregroundStyle(Color.orange)
        .clipShape(Capsule())
        .overlay(
            Capsule().stroke(Color.orange.opacity(0.55), lineWidth: 1)
        )
    }
}
