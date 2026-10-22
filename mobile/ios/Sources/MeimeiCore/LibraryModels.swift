import Foundation

public struct FavoriteMessage: Decodable, Identifiable, Hashable, Sendable {
    public let id: String
    public let messageID: Int64
    public let conversationID: String
    public let conversationTitle: String
    public let content: String
    public var canOpenConversation: Bool { !conversationID.isEmpty && conversationTitle != "原会话已删除" }
    enum CodingKeys: String, CodingKey {
        case id, content
        case messageID = "message_id", conversationID = "conversation_id", conversationTitle = "conversation_title"
    }
}

public struct PromptTemplate: Decodable, Identifiable, Hashable, Sendable {
    public let id: String
    public let title: String
    public let content: String
}

public struct GlobalSearchResult: Decodable, Identifiable, Equatable, Sendable {
    public let id: String
    public let type: String
    public let conversationID: String
    public let messageID: Int64
    public let title: String
    public let snippet: String
    public var supported: Bool { ["conversation", "message", "favorite"].contains(type) }
    public var label: String {
        switch type { case "conversation": return "会话"; case "favorite": return "收藏"; default: return "消息" }
    }
    enum CodingKeys: String, CodingKey {
        case id, type, title, snippet
        case conversationID = "session_id", messageID = "message_id"
    }
}
