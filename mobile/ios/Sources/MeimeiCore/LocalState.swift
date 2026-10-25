import Foundation

public struct PendingSend: Codable, Equatable, Sendable {
    public let conversationID: String
    public let baseline: Int64
    public let content: String
    public let imageIDs: [String]?
    public let documentIDs: [String]?
    public init(conversationID: String, baseline: Int64, content: String, imageIDs: [String] = [], documentIDs: [String] = []) {
        self.conversationID = conversationID; self.baseline = baseline; self.content = content; self.imageIDs = imageIDs; self.documentIDs = documentIDs
    }
    public func matches(_ message: ChatMessage) -> Bool {
        message.role == "user" && message.id > baseline && message.content == content && Set(message.images.map(\.id)) == Set(imageIDs ?? []) && Set(message.documents.map(\.id)) == Set(documentIDs ?? [])
    }
    /// 仅核对本次用户消息之后的相邻回答；同问题出现多次时保守地保持待核对。
    public func reply(in messages: [ChatMessage]) -> ChatMessage? {
        let questions = messages.indices.filter {
            matches(messages[$0])
        }
        guard questions.count == 1, let index = questions.first else { return nil }
        return messages.dropFirst(index + 1).prefix { $0.role != "user" }.first { $0.role == "assistant" && $0.id > 0 }
    }
}

public struct Draft: Codable, Equatable, Sendable {
    public var images: [ChatImage] = []
    public var documents: [ChatDocument] = []
    public var text = ""
    public var webSearch = false
    public var useProfile = true
    public var modelID = ""
    public var reasoningMode: ReasoningMode = .balanced
    public init() {}
    enum CodingKeys: String, CodingKey { case text, webSearch, useProfile, modelID, reasoningMode, images, documents }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        text = try c.decodeIfPresent(String.self, forKey: .text) ?? ""
        webSearch = try c.decodeIfPresent(Bool.self, forKey: .webSearch) ?? false
        useProfile = try c.decodeIfPresent(Bool.self, forKey: .useProfile) ?? true
        modelID = try c.decodeIfPresent(String.self, forKey: .modelID) ?? ""
        reasoningMode = try c.decodeIfPresent(ReasoningMode.self, forKey: .reasoningMode) ?? .balanced
        images = try c.decodeIfPresent([ChatImage].self, forKey: .images) ?? []
        documents = try c.decodeIfPresent([ChatDocument].self, forKey: .documents) ?? []
    }
}

/// 只保存草稿和待核对标记，不缓存历史聊天、密码或登录 Cookie。
public final class LocalState {
    private struct State: Codable {
        var drafts: [String: Draft] = [:]
        var pending: [String: PendingSend] = [:]
    }
    private let file: URL
    private var state: State
    public init(directory: URL) throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var directory = directory
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        try directory.setResourceValues(values)
        file = directory.appendingPathComponent("chat-state.json")
        if FileManager.default.fileExists(atPath: file.path) {
            state = try JSONDecoder().decode(State.self, from: Data(contentsOf: file))
        } else { state = State() }
    }
    private func key(_ accountID: String, _ conversationID: String) -> String {
        // 用数组编码避免账号、会话含分隔符时发生键碰撞。
        String(data: try! JSONEncoder().encode([accountID, conversationID]), encoding: .utf8)!
    }
    private func save(_ next: State) throws {
        let data = try JSONEncoder().encode(next)
        #if os(iOS)
        try data.write(to: file, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        #else
        try data.write(to: file, options: .atomic)
        #endif
        state = next
    }
    public func draft(accountID: String, conversationID: String) -> Draft {
        state.drafts[key(accountID, conversationID)] ?? Draft()
    }
    public func setDraft(_ value: Draft, accountID: String, conversationID: String) throws {
        var next = state; next.drafts[key(accountID, conversationID)] = value; try save(next)
    }
    public func pending(accountID: String, conversationID: String) -> PendingSend? {
        state.pending[key(accountID, conversationID)]
    }
    public func pendingSends(accountID: String) -> [PendingSend] {
        state.pending.filter { entry in
            guard let data = entry.key.data(using: .utf8), let parts = try? JSONDecoder().decode([String].self, from: data) else { return false }
            return parts.first == accountID
        }.map(\.value)
    }
    public func setPending(_ value: PendingSend?, accountID: String, conversationID: String) throws {
        var next = state; next.pending[key(accountID, conversationID)] = value; try save(next)
    }
}
