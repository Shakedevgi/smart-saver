import SwiftUI

/// One card in the dashboard's result list.
struct SearchResultRow: View {
    let hit: SearchHit

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            // Title
            if let title = hit.metadata.title, !title.isEmpty {
                Text(title)
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(.white)
                    .lineLimit(2)
            } else {
                Text(displayHost)
                    .font(.headline)
                    .foregroundStyle(Color.white.opacity(0.55))
                    .lineLimit(1)
            }

            // Summary
            if let summary = hit.summary, !summary.isEmpty {
                Text(summary)
                    .font(.subheadline)
                    .foregroundStyle(Color.white.opacity(0.65))
                    .lineLimit(3)
            }

            // Badge row — horizontal scroll keeps wrapping simple on
            // very-long-tech-list items.
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 6) {
                    if hit.metadata.status == "processing" {
                        ProcessingBadge()
                    } else if hit.metadata.status == "failed" {
                        FailedBadge()
                    }
                    if let cat = hit.category, hit.metadata.status != "processing" {
                        TagBadge(text: cat, systemImage: "tag.fill", color: Brand.electricBlue)
                    }
                    if let loc = hit.metadata.location, !loc.isEmpty {
                        TagBadge(text: loc, systemImage: "mappin.and.ellipse", color: .cyan)
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

            // Source / URL footer
            HStack(spacing: 6) {
                Image(systemName: hit.metadata.sourceType == "video"
                      ? "play.rectangle.fill" : "doc.text.fill")
                    .font(.caption2)
                    .foregroundStyle(Brand.electricBlue.opacity(0.70))
                Text(hit.url)
                    .font(.caption2)
                    .foregroundStyle(Color.white.opacity(0.30))
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer()
                if let dist = hit.distance {
                    Text(String(format: "d %.2f", dist))
                        .font(.caption2)
                        .foregroundStyle(Color.white.opacity(0.25))
                }
            }
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Brand.cardBackground)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(rowBorderColor, lineWidth: rowBorderWidth)
        )
    }

    private var rowBorderColor: Color {
        switch hit.metadata.status {
        case "processing": return Color.yellow.opacity(0.55)
        case "failed":     return Color.red.opacity(0.50)
        default:
            return hit.metadata.isUncertain == true
                ? Color.orange.opacity(0.55)
                : Brand.cardBorder
        }
    }

    private var rowBorderWidth: CGFloat {
        switch hit.metadata.status {
        case "processing", "failed": return 1.5
        default: return hit.metadata.isUncertain == true ? 1.5 : 1.0
        }
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
        .background(color.opacity(0.16))
        .foregroundStyle(color)
        .clipShape(Capsule())
        .overlay(Capsule().stroke(color.opacity(0.30), lineWidth: 0.8))
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
        .background(Color.yellow.opacity(pulse ? 0.32 : 0.16))
        .foregroundStyle(Color.orange)
        .clipShape(Capsule())
        .overlay(Capsule().stroke(Color.yellow.opacity(0.55), lineWidth: 0.8))
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
        .overlay(Capsule().stroke(Color.red.opacity(0.40), lineWidth: 0.8))
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
        .background(Color.orange.opacity(0.18))
        .foregroundStyle(Color.orange)
        .clipShape(Capsule())
        .overlay(Capsule().stroke(Color.orange.opacity(0.40), lineWidth: 0.8))
    }
}
