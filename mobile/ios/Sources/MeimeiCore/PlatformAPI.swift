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
    func stream(id: String, content: String, webSearch: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws
}

private final class NoRedirects: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
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

    private func request(_ path: [String], method: String = "GET", body: [String: Any]? = nil) throws -> URLRequest {
        let url = path.reduce(base) { $0.appendingPathComponent($1) }
        var request = URLRequest(url: url)
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
    private func call<T: Decodable>(_ type: T.Type, path: [String], method: String = "GET", body: [String: Any]? = nil) async throws -> T {
        let (data, response) = try await session.data(for: request(path, method: method, body: body))
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
        try await call(SMSLoginChallenge.self, path: ["api", "sms-login", "send"], method: "POST", body: ["phone": phone])
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

    /// 所有发送只调用一次 POST；EOF、finish_reason、[DONE] 均不代表入库成功。
    public func stream(id: String, content: String, webSearch: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws {
        var request = try request(["api", "conversations", id, "messages"], method: "POST", body: [
            "content": content, "web_search": webSearch, "use_profile": true
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
