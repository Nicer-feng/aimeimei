import Foundation

public struct SessionCredential: Codable, Sendable {
    public let token: String
    public let expires: Date
    public init(token: String, expires: Date) { self.token = token; self.expires = expires }
}

public protocol CredentialStore: Sendable {
    func read() throws -> SessionCredential?
    func write(_ value: SessionCredential?) throws
}

public protocol PlatformServing: Sendable {
    func captcha() async throws -> Captcha
    func currentAccount() async throws -> Account?
    func login(username: String, password: String, captcha: Captcha, answer: String) async throws -> Account
    func smsLoginConfig() async throws -> SMSLoginConfiguration
    func sendLoginSMS(phone: String) async throws -> SMSLoginChallenge
    func loginSMS(phone: String, code: String, challengeID: String) async throws -> Account
    func logout() async throws
    func clearCredential() throws
    func models() async throws -> [ChatModel]
    func conversations() async throws -> [Conversation]
    func createConversation(modelID: String, mode: ReasoningMode) async throws -> Conversation
    func configureConversation(id: String, modelID: String, mode: ReasoningMode) async throws -> Conversation
    func renameConversation(id: String, title: String) async throws
    func pinConversation(id: String, pinned: Bool) async throws
    func deleteConversation(id: String) async throws
    func messages(id: String) async throws -> [ChatMessage]
    func favorites() async throws -> [FavoriteMessage]
    func favorite(messageID: Int64) async throws -> FavoriteMessage
    func unfavorite(messageID: Int64) async throws
    func prompts() async throws -> [PromptTemplate]
    func search(query: String) async throws -> [GlobalSearchResult]
    func uploadImage(_ data: Data, progress: @escaping @Sendable (Double) -> Void) async throws -> ChatImage
    func imageData(id: String) async throws -> Data
    func stream(id: String, content: String, imageIDs: [String], webSearch: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws
}

public extension PlatformServing {
    func stream(id: String, content: String, webSearch: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws {
        try await stream(id: id, content: content, imageIDs: [], webSearch: webSearch, onEvent: onEvent)
    }
}

private final class NoRedirects: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    private let progress: @Sendable (Double) -> Void
    init(progress: @escaping @Sendable (Double) -> Void = { _ in }) { self.progress = progress }
    func urlSession(_ session: URLSession, task: URLSessionTask, didSendBodyData bytesSent: Int64,
                    totalBytesSent: Int64, totalBytesExpectedToSend: Int64) {
        if totalBytesExpectedToSend > 0 { progress(min(1, Double(totalBytesSent) / Double(totalBytesExpectedToSend))) }
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, willPerformHTTPRedirection response: HTTPURLResponse,
                    newRequest request: URLRequest, completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
    }
}

public final class PlatformAPI: PlatformServing, @unchecked Sendable {
    private let base: URL
    private let credentials: any CredentialStore
    private let session: URLSession
    public init(baseURL: URL, credentials: any CredentialStore, configuration: URLSessionConfiguration = .ephemeral) throws {
        guard baseURL.scheme == "https", baseURL.host != nil, baseURL.user == nil, baseURL.password == nil,
              baseURL.query == nil, baseURL.fragment == nil, ["", "/"].contains(baseURL.path) else { throw PlatformError.invalidURL }
        base = baseURL; self.credentials = credentials
        configuration.httpShouldSetCookies = false; configuration.httpCookieStorage = nil
        configuration.urlCache = nil; configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = 60; configuration.timeoutIntervalForResource = 900
        session = URLSession(configuration: configuration, delegate: NoRedirects(), delegateQueue: nil)
    }
    deinit { session.invalidateAndCancel() }

    private func request(_ path: [String], method: String = "GET", body: [String: Any]? = nil, query: [URLQueryItem] = []) throws -> URLRequest {
        let url = path.reduce(base) { $0.appendingPathComponent($1) }
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        if !query.isEmpty { components.queryItems = query }
        // 服务端按表单规则解析查询串，必须保留关键词中的字面加号。
        components.percentEncodedQuery = components.percentEncodedQuery?.replacingOccurrences(of: "+", with: "%2B")
        guard let endpoint = components.url else { throw PlatformError.invalidURL }
        var request = URLRequest(url: endpoint)
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if let credential = try credentials.read(), credential.expires > Date() {
            request.setValue("ap_session=\(credential.token)", forHTTPHeaderField: "Cookie")
        }
        if let body {
            request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        return request
    }
    private func checked(_ response: URLResponse, data: Data = Data()) throws -> HTTPURLResponse {
        guard let http = response as? HTTPURLResponse, http.url?.host == base.host,
              http.url?.scheme == base.scheme, http.url?.port == base.port else { throw PlatformError.invalidResponse }
        guard (200..<300).contains(http.statusCode) else {
            let body = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            throw PlatformError.http(http.statusCode, body?["error"] as? String ?? "")
        }
        return http
    }
    private func call<T: Decodable>(_ type: T.Type, path: [String], method: String = "GET", body: [String: Any]? = nil, query: [URLQueryItem] = []) async throws -> T {
        let (data, response) = try await session.data(for: request(path, method: method, body: body, query: query))
        let http = try checked(response, data: data)
        if let header = http.value(forHTTPHeaderField: "Set-Cookie") {
            let cookie = HTTPCookie.cookies(withResponseHeaderFields: ["Set-Cookie": header], for: base).first { $0.name == "ap_session" }
            if let cookie {
                try credentials.write(cookie.value.isEmpty ? nil : SessionCredential(token: cookie.value, expires: cookie.expiresDate ?? Date()))
            }
        }
        do { return try JSONDecoder().decode(T.self, from: data) }
        catch { throw PlatformError.invalidResponse }
    }
    private struct Me: Decodable { let authenticated: Bool; let user: Account? }
    private struct Login: Decodable { let user: Account }
    private struct Models: Decodable { let models: [ChatModel] }
    private struct Conversations: Decodable { let conversations: [Conversation] }
    private struct Item: Decodable { let conversation: Conversation }
    private struct Messages: Decodable { let messages: [ChatMessage] }
    private struct OK: Decodable { let ok: Bool }
    private struct SMSConfig: Decodable { let sms_auth: SMSLoginConfiguration }
    private struct Favorites: Decodable { let favorites: [FavoriteMessage] }
    private struct Favorite: Decodable { let favorite: FavoriteMessage }
    private struct Prompts: Decodable { let prompts: [PromptTemplate] }
    private struct Search: Decodable { let results: [GlobalSearchResult] }

    public func captcha() async throws -> Captcha { try await call(Captcha.self, path: ["api", "captcha"]) }
    public func currentAccount() async throws -> Account? {
        let value = try await call(Me.self, path: ["api", "me"])
        if !value.authenticated { try clearCredential() }
        return value.authenticated ? value.user : nil
    }
    public func login(username: String, password: String, captcha: Captcha, answer: String) async throws -> Account {
        try await call(Login.self, path: ["api", "login"], method: "POST", body: [
            "username": username.trimmingCharacters(in: .whitespacesAndNewlines), "password": password,
            "captcha_id": captcha.id, "captcha": answer.trimmingCharacters(in: .whitespacesAndNewlines)
        ]).user
    }
    public func smsLoginConfig() async throws -> SMSLoginConfiguration {
        try await call(SMSConfig.self, path: ["api", "sms-login", "config"]).sms_auth
    }
    public func sendLoginSMS(phone: String) async throws -> SMSLoginChallenge {
        do {
            return try await call(SMSLoginChallenge.self, path: ["api", "sms-login", "send"], method: "POST", body: ["phone": phone])
        } catch let failure as PlatformError {
            if case .http(429, _) = failure { throw PlatformError.smsLogin("获取验证码过于频繁，请稍后再试") }
            throw failure
        }
    }
    public func loginSMS(phone: String, code: String, challengeID: String) async throws -> Account {
        do {
            return try await call(Login.self, path: ["api", "sms-login", "verify"], method: "POST", body: [
                "phone": phone, "code": code, "challenge_id": challengeID
            ]).user
        } catch let failure as PlatformError {
            // 仅映射此接口的已知文案，避免把验证码错误误报为已有会话失效。
            if case .http(401, let message) = failure,
               ["验证码无效或已过期", "验证码不正确或已过期"].contains(message) {
                throw PlatformError.smsLogin(message)
            }
            throw failure
        }
    }
    public func logout() async throws { _ = try await call(OK.self, path: ["api", "logout"], method: "POST", body: [:]) }
    public func clearCredential() throws { try credentials.write(nil) }
    public func models() async throws -> [ChatModel] { try await call(Models.self, path: ["api", "models"]).models }
    public func conversations() async throws -> [Conversation] { try await call(Conversations.self, path: ["api", "conversations"]).conversations }
    public func createConversation(modelID: String, mode: ReasoningMode) async throws -> Conversation {
        try await call(Item.self, path: ["api", "conversations"], method: "POST", body: ["model_id": modelID, "reasoning_mode": mode.rawValue]).conversation
    }
    public func configureConversation(id: String, modelID: String, mode: ReasoningMode) async throws -> Conversation {
        try await call(Item.self, path: ["api", "conversations", id], method: "PATCH", body: ["model_id": modelID, "reasoning_mode": mode.rawValue]).conversation
    }
    public func renameConversation(id: String, title: String) async throws {
        _ = try await call(Item.self, path: ["api", "conversations", id], method: "PATCH", body: ["title": title])
    }
    public func pinConversation(id: String, pinned: Bool) async throws {
        _ = try await call(Item.self, path: ["api", "conversations", id, pinned ? "pin" : "unpin"], method: "POST", body: [:])
    }
    public func deleteConversation(id: String) async throws {
        _ = try await call(OK.self, path: ["api", "conversations", id], method: "DELETE")
    }
    public func messages(id: String) async throws -> [ChatMessage] { try await call(Messages.self, path: ["api", "conversations", id, "messages"]).messages }
    public func favorites() async throws -> [FavoriteMessage] { try await call(Favorites.self, path: ["api", "favorites"]).favorites }
    public func favorite(messageID: Int64) async throws -> FavoriteMessage {
        try await call(Favorite.self, path: ["api", "favorites"], method: "POST", body: ["message_id": messageID]).favorite
    }
    public func unfavorite(messageID: Int64) async throws {
        _ = try await call(OK.self, path: ["api", "favorites", "message", String(messageID)], method: "DELETE")
    }
    public func prompts() async throws -> [PromptTemplate] { try await call(Prompts.self, path: ["api", "prompts"]).prompts }
    public func search(query: String) async throws -> [GlobalSearchResult] {
        try await call(Search.self, path: ["api", "search"], query: [URLQueryItem(name: "q", value: String(query.trimmingCharacters(in: .whitespacesAndNewlines).prefix(80)))]).results.filter(\.supported)
    }

    private struct PolicyResponse: Decodable { let policy: ImageUploadPolicy }
    private struct ImageResponse: Decodable { let image: ChatImage }
    private func externalURL(_ value: String) throws -> URL {
        guard let url = URL(string: value), url.scheme == "https", url.host != nil,
              url.user == nil, url.password == nil else { throw PlatformError.invalidResponse }
        return url
    }
    public func uploadImage(_ data: Data, progress: @escaping @Sendable (Double) -> Void) async throws -> ChatImage {
        let policy = try await call(PolicyResponse.self, path: ["api", "chat-images", "upload-policy"], method: "POST", body: [:]).policy
        let key = policy.keyPrefix + UUID().uuidString.lowercased() + ".jpg"
        let boundary = "Meimei-" + UUID().uuidString
        let body = try policy.form(image: data, key: key, boundary: boundary)
        var request = URLRequest(url: try externalURL(policy.host))
        request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        // OSS 请求单独建会话，绝不携带平台 Cookie，也不跟随上传重定向。
        let external = URLSession(configuration: session.configuration, delegate: NoRedirects(progress: progress), delegateQueue: nil)
        defer { external.invalidateAndCancel() }
        let (_, response) = try await external.upload(for: request, from: body)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw PlatformError.media("图片上传失败，请检查网络后重试")
        }
        progress(1)
        return try await call(ImageResponse.self, path: ["api", "chat-images"], method: "POST", body: [
            "filename": "photo.jpg", "mime_type": "image/jpeg", "file_size": data.count, "oss_key": key
        ]).image
    }
    public func imageData(id: String) async throws -> Data {
        let (data, response) = try await session.data(for: request(["api", "chat-images", id, "view"]))
        guard let http = response as? HTTPURLResponse, http.statusCode == 302,
              http.url?.host == base.host, let location = http.value(forHTTPHeaderField: "Location") else {
            _ = try checked(response, data: data); throw PlatformError.invalidResponse
        }
        let external = URLSession(configuration: session.configuration, delegate: NoRedirects(), delegateQueue: nil)
        defer { external.invalidateAndCancel() }
        let (image, remote) = try await external.data(for: URLRequest(url: try externalURL(location)))
        guard let remote = remote as? HTTPURLResponse, remote.statusCode == 200,
              remote.mimeType?.hasPrefix("image/") == true, !image.isEmpty, image.count <= 20 * 1024 * 1024 else {
            throw PlatformError.media("图片加载失败，请重新打开预览")
        }
        return image
    }

    /// 所有发送只调用一次 POST；EOF、finish_reason、[DONE] 均不代表入库成功。
    public func stream(id: String, content: String, imageIDs: [String], webSearch: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws {
        var request = try request(["api", "conversations", id, "messages"], method: "POST", body: [
            "content": content, "image_ids": imageIDs, "web_search": webSearch, "use_profile": true
        ])
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")
        request.timeoutInterval = 300
        let (bytes, response) = try await session.bytes(for: request)
        defer { bytes.task.cancel() }
        let http = try checked(response)
        guard http.mimeType == "text/event-stream" else { throw PlatformError.invalidResponse }
        try await withTaskCancellationHandler {
            var parser = SSEByteParser()
            for try await byte in bytes {
                try Task.checkCancellation()
                guard let data = try parser.byte(byte) else { continue }
                if data.trimmingCharacters(in: .whitespacesAndNewlines) == "[DONE]" { return }
                let event = try StreamEvent(data: data)
                try await onEvent(event)
                if event.type == "message_saved", event.savedID != nil { return }
            }
        } onCancel: { bytes.task.cancel() }
    }
}
