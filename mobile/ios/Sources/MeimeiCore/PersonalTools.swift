import Foundation

public struct AIProfile: Codable, Identifiable, Equatable, Sendable {
    public var id: String
    public var title: String
    public var content: String
    public var type: String
    public var sort_order: Int
    public var enabled: Bool
    public init(id: String = "", title: String = "", content: String = "", type: String = "profile", sort_order: Int = 100, enabled: Bool = true) {
        self.id = id; self.title = title; self.content = content; self.type = type; self.sort_order = sort_order; self.enabled = enabled
    }
    public var valid: Bool { !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && title.count <= 80 && !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && content.count <= 12000 && ["profile", "project", "style", "memory"].contains(type) && (-100000...100000).contains(sort_order) }
}

public enum ShareScope: String, CaseIterable, Identifiable, Sendable {
    case assistant, turn, conversation
    public var id: String { rawValue }
    public var label: String { switch self { case .assistant: "仅此回答"; case .turn: "一问一答"; case .conversation: "整段对话" } }
}
public struct ConversationShare: Decodable, Identifiable, Equatable, Sendable {
    public let id: String
    public let scope: String
    public let title: String
    public let expires_at: Double
    public let active: Bool
    public let access_count: Int
    public let url: String?
    public init(id: String, scope: String, title: String, expires_at: Double, active: Bool, access_count: Int = 0, url: String? = nil) {
        self.id = id; self.scope = scope; self.title = title; self.expires_at = expires_at; self.active = active; self.access_count = access_count; self.url = url
    }
    public func publicURL(base: URL) -> URL? {
        guard let url, url.hasPrefix("/ai/share/"), !url.dropFirst(10).isEmpty, url.dropFirst(10).allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "-" || $0 == "_") }),
              let value = URL(string: url, relativeTo: base)?.absoluteURL,
              value.scheme == "https", value.host == base.host, value.port == base.port,
              value.user == nil, value.password == nil, value.query == nil, value.fragment == nil else { return nil }
        return value
    }
}
