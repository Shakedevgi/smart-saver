// Async/await wrapper over URLSession for the four FastAPI endpoints.
// One shared singleton; URLSession is thread-safe so no actor isolation needed.

import Foundation

// TODO: Replace the placeholder below with your Cloud Run service URL after deployment.
// Get your URL from: gcloud run services describe smart-saver --region <your-region> --format="value(status.url)"
// Example: "https://<your-service>.<region>.run.app"
let kDefaultAPIBaseURL = URL(string: "https://YOUR_CLOUD_RUN_URL_HERE")!

enum APIError: LocalizedError {
    case invalidResponse
    case http(status: Int, body: String)
    case encoding(Error)
    case decoding(Error)
    case transport(Error)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "Server returned a response we couldn't interpret."
        case .http(let status, let body):
            return "HTTP \(status). \(body.prefix(160))"
        case .encoding(let err):
            return "Failed to encode request: \(err.localizedDescription)"
        case .decoding(let err):
            return "Failed to decode response: \(err.localizedDescription)"
        case .transport(let err):
            return "Network error: \(err.localizedDescription)"
        }
    }
}

final class NetworkManager {
    static let shared = NetworkManager()

    var baseURL: URL
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(baseURL: URL = kDefaultAPIBaseURL, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.session = session

        let dec = JSONDecoder()
        dec.keyDecodingStrategy = .convertFromSnakeCase
        self.decoder = dec

        let enc = JSONEncoder()
        enc.keyEncodingStrategy = .convertToSnakeCase
        self.encoder = enc
    }

    // MARK: - Endpoints

    func fetchCategories() async throws -> [String] {
        let resp: CategoriesResponse = try await get("/api/categories")
        return resp.categories
    }

    func search(query: String, category: String? = nil, limit: Int = 10) async throws -> SearchResponse {
        struct Body: Encodable {
            let query: String
            let limit: Int
            let category: String?
        }
        return try await post("/api/search", body: Body(query: query, limit: limit, category: category))
    }

    func health() async throws -> HealthResponse {
        try await get("/api/health")
    }

    // MARK: - Item management

    /// Insert a fully-specified item via `POST /api/items`. Bypasses
    /// the extractor + LLM pipeline; the row lands at status="completed"
    /// immediately. Returns the raw response body — we don't decode
    /// because the dashboard refreshes off `/api/health` and
    /// `/api/search` right after a successful save.
    @discardableResult
    func createManualItem(
        url itemURL: String,
        title: String,
        summary: String,
        category: String
    ) async throws -> Data {
        var req = URLRequest(url: baseURL.appendingPathComponent("/api/items"))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        do {
            req.httpBody = try encoder.encode(ManualItemRequest(
                url: itemURL,
                title: title,
                summary: summary,
                category: category
            ))
        } catch {
            throw APIError.encoding(error)
        }
        let (data, response) = try await sessionData(for: req)
        try Self.assert2xx(response, data: data)
        return data
    }

    @discardableResult
    func deleteItem(url itemURL: String) async throws -> DeleteItemResponse {
        try await request("/api/items", method: "DELETE",
                          body: DeleteItemRequest(url: itemURL))
    }

    @discardableResult
    func updateItem(
        url itemURL: String,
        title: String? = nil,
        summary: String? = nil,
        category: String? = nil
    ) async throws -> UpdateItemResponse {
        try await request("/api/items", method: "PATCH",
                          body: UpdateItemRequest(url: itemURL,
                                                  title: title,
                                                  summary: summary,
                                                  category: category))
    }

    // MARK: - Category management

    @discardableResult
    func renameCategory(oldName: String, newName: String) async throws -> CategoryBulkResponse {
        try await request("/api/categories", method: "PATCH",
                          body: RenameCategoryRequest(oldName: oldName, newName: newName))
    }

    @discardableResult
    func deleteCategory(name: String) async throws -> CategoryBulkResponse {
        try await request("/api/categories", method: "DELETE",
                          body: DeleteCategoryRequest(name: name))
    }

    /// Used by the Share Extension. Decode is opt-in because the response
    /// `IngestionResult` is large and the extension typically only needs to
    /// know it succeeded.
    @discardableResult
    func ingest(urlToIngest: String, existingCategories: [String]? = nil) async throws -> Data {
        let body = IngestRequest(url: urlToIngest, existingCategories: existingCategories)
        let req = try makePostRequest("/api/ingest", body: body, timeout: 180)
        let (data, response) = try await sessionData(for: req)
        try Self.assert2xx(response, data: data)
        return data
    }

    // MARK: - Helpers

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let req = makeGetRequest(path)
        let (data, response) = try await sessionData(for: req)
        try Self.assert2xx(response, data: data)
        return try Self.decode(T.self, from: data, using: decoder)
    }

    private func post<B: Encodable, T: Decodable>(_ path: String, body: B) async throws -> T {
        let req = try makePostRequest(path, body: body)
        let (data, response) = try await sessionData(for: req)
        try Self.assert2xx(response, data: data)
        return try Self.decode(T.self, from: data, using: decoder)
    }

    /// Generic helper for `DELETE` / `PATCH` calls that take a JSON body.
    /// URLSession on iOS supports a body on both verbs without ceremony.
    private func request<B: Encodable, T: Decodable>(
        _ path: String, method: String, body: B
    ) async throws -> T {
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = method
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        do {
            req.httpBody = try encoder.encode(body)
        } catch {
            throw APIError.encoding(error)
        }
        let (data, response) = try await sessionData(for: req)
        try Self.assert2xx(response, data: data)
        return try Self.decode(T.self, from: data, using: decoder)
    }

    private func sessionData(for request: URLRequest) async throws -> (Data, URLResponse) {
        do {
            return try await session.data(for: request)
        } catch {
            throw APIError.transport(error)
        }
    }

    private func makeGetRequest(_ path: String) -> URLRequest {
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = "GET"
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        return req
    }

    private func makePostRequest<B: Encodable>(_ path: String, body: B, timeout: TimeInterval = 30) throws -> URLRequest {
        var req = URLRequest(url: baseURL.appendingPathComponent(path))
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.timeoutInterval = timeout
        do {
            req.httpBody = try encoder.encode(body)
        } catch {
            throw APIError.encoding(error)
        }
        return req
    }

    private static func assert2xx(_ response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { throw APIError.invalidResponse }
        if !(200..<300).contains(http.statusCode) {
            let body = String(data: data, encoding: .utf8) ?? ""
            throw APIError.http(status: http.statusCode, body: body)
        }
    }

    private static func decode<T: Decodable>(_ type: T.Type, from data: Data, using decoder: JSONDecoder) throws -> T {
        do {
            return try decoder.decode(type, from: data)
        } catch {
            throw APIError.decoding(error)
        }
    }
}
