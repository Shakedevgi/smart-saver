// Share Extension entry point.
//
// Flow:
//   1. iOS hands us an `NSExtensionContext` carrying one or more
//      `NSExtensionItem`s with attachments that may include a URL.
//   2. We pull the first http(s) URL out of those attachments.
//   3. POST it to the local FastAPI backend's `/api/ingest`.
//   4. Briefly show "Saved!" / "Failed" and dismiss.
//
// We do NOT depend on any of the main-app source files so the extension
// has the smallest possible binary footprint (Apple imposes ~120 MB).

import UIKit
import UniformTypeIdentifiers

private let kIngestEndpoint = URL(string: "https://cryptic-attire-statute.ngrok-free.dev/api/ingest")!
private let kRequestTimeout: TimeInterval = 180  // video pipeline may need ASR + OCR

final class ShareViewController: UIViewController {
    private var spinner: UIActivityIndicatorView!
    private var titleLabel: UILabel!
    private var bodyLabel: UILabel!

    // MARK: - Lifecycle

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        buildUI()
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        Task { await runIngest() }
    }

    // MARK: - UI

    private func buildUI() {
        spinner = UIActivityIndicatorView(style: .large)
        spinner.translatesAutoresizingMaskIntoConstraints = false
        spinner.startAnimating()
        view.addSubview(spinner)

        titleLabel = UILabel()
        titleLabel.translatesAutoresizingMaskIntoConstraints = false
        titleLabel.text = "Saving to Smart Saver…"
        titleLabel.font = .preferredFont(forTextStyle: .title3)
        titleLabel.adjustsFontForContentSizeCategory = true
        titleLabel.textAlignment = .center
        titleLabel.numberOfLines = 0
        view.addSubview(titleLabel)

        bodyLabel = UILabel()
        bodyLabel.translatesAutoresizingMaskIntoConstraints = false
        bodyLabel.text = "Extracting → analyzing → indexing"
        bodyLabel.font = .preferredFont(forTextStyle: .footnote)
        bodyLabel.adjustsFontForContentSizeCategory = true
        bodyLabel.textColor = .secondaryLabel
        bodyLabel.textAlignment = .center
        bodyLabel.numberOfLines = 0
        view.addSubview(bodyLabel)

        NSLayoutConstraint.activate([
            spinner.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            spinner.centerYAnchor.constraint(equalTo: view.centerYAnchor, constant: -36),

            titleLabel.topAnchor.constraint(equalTo: spinner.bottomAnchor, constant: 18),
            titleLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 32),
            titleLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -32),

            bodyLabel.topAnchor.constraint(equalTo: titleLabel.bottomAnchor, constant: 6),
            bodyLabel.leadingAnchor.constraint(equalTo: view.leadingAnchor, constant: 32),
            bodyLabel.trailingAnchor.constraint(equalTo: view.trailingAnchor, constant: -32),
        ])
    }

    @MainActor
    private func setStatus(title: String, body: String, success: Bool) {
        spinner.stopAnimating()
        titleLabel.text = title
        bodyLabel.text = body
        bodyLabel.textColor = success ? .systemGreen : .systemRed
    }

    // MARK: - Work

    private func runIngest() async {
        do {
            let shared = try await extractFirstURL()
            try await postIngest(url: shared)
            await setStatus(title: "Saved!", body: shared.host ?? shared.absoluteString, success: true)
            try? await Task.sleep(nanoseconds: 700_000_000)
            await finishSuccessfully()
        } catch {
            await setStatus(title: "Couldn't save", body: error.localizedDescription, success: false)
            try? await Task.sleep(nanoseconds: 1_400_000_000)
            await finishWithError(error)
        }
    }

    @MainActor
    private func finishSuccessfully() async {
        extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
    }

    @MainActor
    private func finishWithError(_ error: Error) async {
        let ns = error as NSError
        extensionContext?.cancelRequest(withError: ns)
    }

    // MARK: - URL extraction

    private func extractFirstURL() async throws -> URL {
        guard let items = extensionContext?.inputItems as? [NSExtensionItem], !items.isEmpty else {
            throw ShareExtError.noItems
        }
        for item in items {
            for provider in item.attachments ?? [] {
                if let url = try await loadURL(from: provider) { return url }
            }
        }
        throw ShareExtError.noURL
    }

    private func loadURL(from provider: NSItemProvider) async throws -> URL? {
        if provider.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
            let raw = try await provider.loadItem(forTypeIdentifier: UTType.url.identifier, options: nil)
            if let url = raw as? URL { return url }
            if let s = raw as? String, let url = URL(string: s) { return url }
        }
        if provider.hasItemConformingToTypeIdentifier(UTType.text.identifier) {
            let raw = try await provider.loadItem(forTypeIdentifier: UTType.text.identifier, options: nil)
            if let s = raw as? String, let url = Self.firstURL(in: s) { return url }
        }
        return nil
    }

    private static func firstURL(in text: String) -> URL? {
        guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) else {
            return nil
        }
        let range = NSRange(text.startIndex..., in: text)
        if let match = detector.firstMatch(in: text, options: [], range: range),
           let r = Range(match.range, in: text) {
            return URL(string: String(text[r]))
        }
        return nil
    }

    // MARK: - Backend call

    private func postIngest(url: URL) async throws {
        var req = URLRequest(url: kIngestEndpoint)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.timeoutInterval = kRequestTimeout

        let payload: [String: Any] = [
            "url": url.absoluteString,
            "analyze": true,
            "store": true,
        ]
        req.httpBody = try JSONSerialization.data(withJSONObject: payload)

        let (data, response) = try await URLSession.shared.data(for: req)
        guard let http = response as? HTTPURLResponse else {
            throw ShareExtError.invalidResponse
        }
        guard (200..<300).contains(http.statusCode) else {
            let body = String(data: data, encoding: .utf8) ?? ""
            throw ShareExtError.httpStatus(http.statusCode, body)
        }
    }
}

// MARK: - Errors

private enum ShareExtError: LocalizedError {
    case noItems
    case noURL
    case invalidResponse
    case httpStatus(Int, String)

    var errorDescription: String? {
        switch self {
        case .noItems:        return "The share sheet didn't include any items."
        case .noURL:          return "No URL found in the shared content."
        case .invalidResponse: return "The Smart Saver server gave an unreadable response."
        case .httpStatus(let s, let body):
            let snippet = body.isEmpty ? "" : ": \(body.prefix(120))"
            return "Server returned HTTP \(s)\(snippet)"
        }
    }
}
