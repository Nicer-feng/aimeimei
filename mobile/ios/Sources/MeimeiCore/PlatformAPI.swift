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
    func documents() async throws -> [ChatDocument]
    func uploadDocument(_ data: Data, filename: String, progress: @escaping @Sendable (Double) -> Void) async throws -> ChatDocument
    func refreshDocument(id: String) async throws -> ChatDocument
    func writing(conversationID: String, versionID: Int64?) async throws -> WritingResponse
    func updateWriting(conversationID: String, revision: Int, command: WritingCommand) async throws -> WritingResponse
    func mediaTasks() async throws -> [MediaTask]
    func uploadMedia(file: URL, filename: String, progress: @escaping @Sendable (Double) -> Void) async throws -> MediaTask
    func refreshMedia(id: String) async throws -> MediaTask
    func deleteMedia(id: String) async throws
    func mediaConversation(id: String, modelID: String) async throws -> MediaConversation
    func ocrTasks() async throws -> [OCRTask]
    func recognizeHandwriting(_ jpeg: Data, progress: @escaping @Sendable (Double) -> Void) async throws -> OCRTask
    func deleteOCRTask(id: String) async throws
    func profiles() async throws -> [AIProfile]
    func saveProfile(_ profile: AIProfile) async throws -> AIProfile
    func deleteProfile(id: String) async throws
    func shares(conversationID: String) async throws -> [ConversationShare]
    func createShare(conversationID: String, scope: ShareScope, messageID: Int64?, expiresIn: Int) async throws -> ConversationShare
    func revokeShare(id: String) async throws
    func stream(id: String, content: String, imageIDs: [String], documentIDs: [String], webSearch: Bool, useProfile: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws
    func speechConfiguration() async throws -> SpeechConfiguration
    func prepareSpeech(messageID: Int64, voice: String, speed: Double) async throws -> PreparedSpeech
    func speechAudio(messageID: Int64, voice: String, speed: Double) async throws -> Data
    func stream(id: String, content: String, imageIDs: [String], documentIDs: [String], webSearch: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws
}

public extension PlatformServing {
    func writing(conversationID: String, versionID: Int64?) async throws -> WritingResponse { throw PlatformError.media("写稿暂不可用") }
    func updateWriting(conversationID: String, revision: Int, command: WritingCommand) async throws -> WritingResponse { throw PlatformError.media("写稿暂不可用") }
    func mediaTasks() async throws -> [MediaTask] { throw PlatformError.media("音视频暂不可用") }
    func uploadMedia(file: URL, filename: String, progress: @escaping @Sendable (Double) -> Void) async throws -> MediaTask { throw PlatformError.media("音视频暂不可用") }
    func refreshMedia(id: String) async throws -> MediaTask { throw PlatformError.media("音视频暂不可用") }
    func deleteMedia(id: String) async throws { throw PlatformError.media("音视频暂不可用") }
    func mediaConversation(id: String, modelID: String) async throws -> MediaConversation { throw PlatformError.media("音视频暂不可用") }

    func ocrTasks() async throws -> [OCRTask] { throw PlatformError.media("手写识别暂不可用") }
    func recognizeHandwriting(_ jpeg: Data, progress: @escaping @Sendable (Double) -> Void) async throws -> OCRTask { throw PlatformError.media("手写识别暂不可用") }
    func deleteOCRTask(id: String) async throws { throw PlatformError.media("手写识别暂不可用") }

    func profiles() async throws -> [AIProfile] { throw PlatformError.media("AI 档案暂不可用") }
    func saveProfile(_ profile: AIProfile) async throws -> AIProfile { throw PlatformError.media("AI 档案暂不可用") }
    func deleteProfile(id: String) async throws { throw PlatformError.media("AI 档案暂不可用") }
    func shares(conversationID: String) async throws -> [ConversationShare] { throw PlatformError.media("分享暂不可用") }
    func createShare(conversationID: String, scope: ShareScope, messageID: Int64?, expiresIn: Int) async throws -> ConversationShare { throw PlatformError.media("分享暂不可用") }
    func revokeShare(id: String) async throws { throw PlatformError.media("分享暂不可用") }
    func stream(id: String, content: String, imageIDs: [String], documentIDs: [String], webSearch: Bool, useProfile: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws {
        try await stream(id: id, content: content, imageIDs: imageIDs, documentIDs: documentIDs, webSearch: webSearch, onEvent: onEvent)
    }

    func stream(id: String, content: String, imageIDs: [String], webSearch: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws {
        try await stream(id: id, content: content, imageIDs: imageIDs, documentIDs: [], webSearch: webSearch, onEvent: onEvent)
    }
    func stream(id: String, content: String, webSearch: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws {
        try await stream(id: id, content: content, imageIDs: [], documentIDs: [], webSearch: webSearch, onEvent: onEvent)
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

    private struct DocumentList: Decodable { let documents: [ChatDocument] }
    private struct DocumentResponse: Decodable { let document: ChatDocument }
    private struct SpeechConfigResponse: Decodable { let tts: SpeechConfiguration }
    public func documents() async throws -> [ChatDocument] { try await call(DocumentList.self, path: ["api", "documents"]).documents }
    public func refreshDocument(id: String) async throws -> ChatDocument {
        try await call(DocumentResponse.self, path: ["api", "documents", id, "refresh"], method: "POST", body: [:]).document
    }
    public func uploadDocument(_ data: Data, filename: String, progress: @escaping @Sendable (Double) -> Void) async throws -> ChatDocument {
        try DocumentLimits.validate(filename: filename, size: data.count)
        let policy = try await call(PolicyResponse.self, path: ["api", "documents", "upload-policy"], method: "POST", body: [:]).policy
        let ext = (filename as NSString).pathExtension.lowercased()
        let safeFilename = String((filename as NSString).deletingPathExtension.prefix(179 - ext.count)) + "." + ext
        let key = policy.keyPrefix + UUID().uuidString.lowercased() + "." + ext
        let boundary = "Meimei-" + UUID().uuidString
        let form = try policy.documentForm(data: data, key: key, boundary: boundary)
        var request = URLRequest(url: try externalURL(policy.host)); request.httpMethod = "POST"
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        let external = URLSession(configuration: session.configuration, delegate: NoRedirects(progress: progress), delegateQueue: nil)
        defer { external.invalidateAndCancel() }
        let (_, response) = try await external.upload(for: request, from: form)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw PlatformError.media("材料上传失败，请检查网络后重试")
        }
        progress(1)
        return try await call(DocumentResponse.self, path: ["api", "documents"], method: "POST", body: [
            "filename": safeFilename, "mime_type": "application/octet-stream", "file_size": data.count, "oss_key": key
        ]).document
    }
    public func writing(conversationID: String, versionID: Int64? = nil) async throws -> WritingResponse {
        try await call(WritingResponse.self, path: ["api", "conversations", conversationID, "writing"], query: versionID.map { [URLQueryItem(name: "version_id", value: String($0))] } ?? [])
    }
    public func updateWriting(conversationID: String, revision: Int, command: WritingCommand) async throws -> WritingResponse {
        try await call(WritingResponse.self, path: ["api", "conversations", conversationID, "writing"], method: "PATCH", body: command.body(revision: revision))
    }
    private struct MediaTasks: Decodable { let tasks: [MediaTask] }
    private struct MediaResponse: Decodable { let task: MediaTask }
    public func mediaTasks() async throws -> [MediaTask] { try await call(MediaTasks.self, path: ["api", "media", "tasks"]).tasks }
    public func refreshMedia(id: String) async throws -> MediaTask { try await call(MediaResponse.self, path: ["api", "media", "tasks", id, "refresh"], method: "POST", body: [:]).task }
    public func deleteMedia(id: String) async throws { _ = try await call(OK.self, path: ["api", "media", "tasks", id], method: "DELETE") }
    public func mediaConversation(id: String, modelID: String) async throws -> MediaConversation {
        try await call(MediaConversation.self, path: ["api", "media", "tasks", id, "conversation"], method: "POST", body: ["model_id": modelID])
    }
    public func uploadMedia(file: URL, filename: String, progress: @escaping @Sendable (Double) -> Void) async throws -> MediaTask {
        let attrs = try FileManager.default.attributesOfItem(atPath: file.path)
        let size = (attrs[.size] as? NSNumber)?.intValue ?? 0
        try MediaLimits.validate(filename: filename, size: size)
        let policy = try await call(PolicyResponse.self, path: ["api", "media", "upload-policy"], method: "POST", body: [:]).policy
        let ext = (filename as NSString).pathExtension.lowercased()
        let safeName = String((filename as NSString).deletingPathExtension.prefix(179 - ext.count)) + "." + ext
        let key = policy.keyPrefix + UUID().uuidString.lowercased() + "." + ext
        let boundary = "Meimei-" + UUID().uuidString
        let form = FileManager.default.temporaryDirectory.appendingPathComponent("media-form-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: form) }
        try await Task.detached { try policy.writeMediaForm(file: file, key: key, boundary: boundary, output: form) }.value
        try Task.checkCancellation()
        var req = URLRequest(url: try externalURL(policy.host)); req.httpMethod = "POST"; req.timeoutInterval = 900
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        let external = URLSession(configuration: session.configuration, delegate: NoRedirects(progress: progress), delegateQueue: nil)
        defer { external.invalidateAndCancel() }
        let (_, response) = try await external.upload(for: req, fromFile: form)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw PlatformError.media("音视频上传失败，请先核对记录再重试") }
        progress(1)
        return try await call(MediaResponse.self, path: ["api", "media", "tasks"], method: "POST", body: ["filename":safeName, "mime_type":"application/octet-stream", "file_size":size, "oss_key":key, "source_language":"cn"]).task
    }
    private struct OCRTasks: Decodable { let tasks: [OCRTask] }
    private struct OCRResponse: Decodable { let task: OCRTask }
    public func ocrTasks() async throws -> [OCRTask] { try await call(OCRTasks.self, path: ["api", "ocr", "tasks"]).tasks }
    public func deleteOCRTask(id: String) async throws { _ = try await call(OK.self, path: ["api", "ocr", "tasks", id], method: "DELETE") }
    public func recognizeHandwriting(_ jpeg: Data, progress: @escaping @Sendable (Double) -> Void) async throws -> OCRTask {
        guard !jpeg.isEmpty, jpeg.count <= 10 * 1024 * 1024, jpeg.starts(with: [0xff,0xd8]) else { throw PlatformError.media("请选择不超过 10MB 的 JPEG 图片") }
        let policy = try await call(PolicyResponse.self, path: ["api", "ocr", "upload-policy"], method: "POST", body: [:]).policy
        let key = policy.keyPrefix + UUID().uuidString.lowercased() + ".jpg"
        let boundary = "Meimei-" + UUID().uuidString
        let form = try policy.form(image: jpeg, key: key, boundary: boundary)
        var req = URLRequest(url: try externalURL(policy.host)); req.httpMethod = "POST"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        let external = URLSession(configuration: session.configuration, delegate: NoRedirects(progress: progress), delegateQueue: nil)
        defer { external.invalidateAndCancel() }
        let (_, response) = try await external.upload(for: req, from: form)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw PlatformError.media("图片上传失败，请重新选择") }
        progress(1)
        return try await call(OCRResponse.self, path: ["api", "ocr", "tasks"], method: "POST", body: ["filename":"handwriting.jpg", "mime_type":"image/jpeg", "file_size":jpeg.count, "oss_key":key]).task
    }
    private struct Profiles: Decodable { let profiles: [AIProfile] }
    private struct Profile: Decodable { let profile: AIProfile }
    private struct Shares: Decodable { let shares: [ConversationShare] }
    private struct Share: Decodable { let share: ConversationShare }
    public func profiles() async throws -> [AIProfile] { try await call(Profiles.self, path: ["api", "profiles"]).profiles }
    public func saveProfile(_ profile: AIProfile) async throws -> AIProfile {
        guard profile.valid else { throw PlatformError.media("请填写 1–80 字标题、1–12000 字内容及有效排序") }
        let path = ["api", "profiles"] + (profile.id.isEmpty ? [] : [profile.id])
        return try await call(Profile.self, path: path, method: profile.id.isEmpty ? "POST" : "PATCH", body: ["title": profile.title, "content": profile.content, "type": profile.type, "sort_order": profile.sort_order, "enabled": profile.enabled]).profile
    }
    public func deleteProfile(id: String) async throws { _ = try await call(OK.self, path: ["api", "profiles", id], method: "DELETE") }
    public func shares(conversationID: String) async throws -> [ConversationShare] { try await call(Shares.self, path: ["api", "conversations", conversationID, "shares"]).shares }
    public func createShare(conversationID: String, scope: ShareScope, messageID: Int64?, expiresIn: Int) async throws -> ConversationShare {
        guard [3600,21600,86400,604800].contains(expiresIn), scope == .conversation || (messageID ?? 0) > 0 else { throw PlatformError.media("请选择回答和有效期") }
        var body: [String: Any] = ["scope": scope.rawValue, "expires_in": expiresIn]
        if scope != .conversation { body["message_id"] = messageID }
        let value = try await call(Share.self, path: ["api", "conversations", conversationID, "shares"], method: "POST", body: body).share
        guard value.publicURL(base: base) != nil else { throw PlatformError.invalidResponse }
        return value
    }
    public func revokeShare(id: String) async throws { _ = try await call(OK.self, path: ["api", "conversation-shares", id], method: "DELETE") }

    public func speechConfiguration() async throws -> SpeechConfiguration { try await call(SpeechConfigResponse.self, path: ["api", "tts", "config"]).tts }
    public func prepareSpeech(messageID: Int64, voice: String, speed: Double) async throws -> PreparedSpeech {
        guard messageID > 0, speed.isFinite, (0.5...2).contains(speed) else { throw PlatformError.invalidResponse }
        return try await call(PreparedSpeech.self, path: ["api", "messages", String(messageID), "tts"], method: "POST", body: ["voice": voice, "speed": speed])
    }
    public func speechAudio(messageID: Int64, voice: String, speed: Double) async throws -> Data {
        guard messageID > 0, speed.isFinite, (0.5...2).contains(speed) else { throw PlatformError.invalidResponse }
        let query = [URLQueryItem(name: "voice", value: voice), URLQueryItem(name: "speed", value: String(speed))]
        // 只构造当前消息的固定平台路径，不使用响应中的任意 audio_url。
        var req = try request(["api", "messages", String(messageID), "tts", "audio"], query: query)
        req.setValue("audio/*", forHTTPHeaderField: "Accept"); req.timeoutInterval = 300
        let (data, response) = try await session.data(for: req)
        if let http = response as? HTTPURLResponse, http.statusCode == 302 {
            guard http.url?.host == base.host, let location = http.value(forHTTPHeaderField: "Location") else { throw PlatformError.invalidResponse }
            let external = URLSession(configuration: session.configuration, delegate: NoRedirects(), delegateQueue: nil)
            defer { external.invalidateAndCancel() }
            let (audio, remote) = try await external.data(for: URLRequest(url: try externalURL(location)))
            guard let remote = remote as? HTTPURLResponse, remote.statusCode == 200, remote.mimeType?.hasPrefix("audio/") == true else {
                throw PlatformError.media("语音加载失败，请稍后重试")
            }
            return try checkedAudio(audio)
        }
        let http = try checked(response, data: data)
        guard http.mimeType?.hasPrefix("audio/") == true else { throw PlatformError.invalidResponse }
        return try checkedAudio(data)
    }
    private func checkedAudio(_ data: Data) throws -> Data {
        guard !data.isEmpty, data.count <= 50 * 1024 * 1024 else { throw PlatformError.media("语音为空或过大，请选择较短的回答") }
        return data
    }

    /// 所有发送只调用一次 POST；EOF、finish_reason、[DONE] 均不代表入库成功。
    public func stream(id: String, content: String, imageIDs: [String], documentIDs: [String], webSearch: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws {
        try await stream(id: id, content: content, imageIDs: imageIDs, documentIDs: documentIDs, webSearch: webSearch, useProfile: true, onEvent: onEvent)
    }
    public func stream(id: String, content: String, imageIDs: [String], documentIDs: [String], webSearch: Bool, useProfile: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws {
        var request = try request(["api", "conversations", id, "messages"], method: "POST", body: [
            "content": content, "document_ids": documentIDs, "image_ids": imageIDs, "web_search": webSearch, "use_profile": useProfile
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
