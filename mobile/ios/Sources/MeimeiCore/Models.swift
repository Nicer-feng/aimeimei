import Foundation

public struct Account: Codable, Equatable, Sendable {
    public let id: String
    public let username: String
    public let displayName: String
    public var label: String { displayName.isEmpty ? username : displayName }
    enum CodingKeys: String, CodingKey { case id, username; case displayName = "display_name" }
}

public struct Captcha: Decodable, Sendable {
    public let id: String
    public let svg: String
    enum CodingKeys: String, CodingKey { case id = "captcha_id"; case svg = "image_svg" }
}

public struct ChatModel: Decodable, Identifiable, Equatable, Sendable {
    public let id: String
    public let name: String
    public let supportsVision: Bool
    public let reasoningControl: Bool
    enum CodingKeys: String, CodingKey {
        case id, name
        case supportsVision = "supports_vision"
        case reasoningControl = "supports_reasoning_control"
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id); name = try c.decode(String.self, forKey: .name)
        reasoningControl = try c.decodeIfPresent(Bool.self, forKey: .reasoningControl) ?? false
        supportsVision = try c.decodeIfPresent(Bool.self, forKey: .supportsVision) ?? false
    }
}

public enum ReasoningMode: String, Codable, CaseIterable, Sendable {
    case fast, balanced, deep
    public var label: String {
        switch self { case .fast: return "快速"; case .balanced: return "平衡"; case .deep: return "深度" }
    }
}

public struct Conversation: Decodable, Identifiable, Equatable, Sendable {
    public let id: String
    public let title: String
    public let modelID: String
    public let modelName: String
    public let reasoningMode: ReasoningMode
    public let pinned: Bool
    enum CodingKeys: String, CodingKey {
        case id, title, pinned
        case modelID = "model_id", modelName = "model_name", reasoningMode = "reasoning_mode"
    }
}

public struct ChatMessage: Decodable, Identifiable, Equatable, Sendable {
    public let id: Int64
    public let role: String
    public let content: String
    public let reasoning: String
    public let status: String
    public let attachments: [String]
    public let favoriteID: String?
    public let documents: [ChatDocument]
    public let images: [ChatImage]
    public let sources: [ChatSource]
    public let writingCheck: WritingCheck?

    public init(id: Int64, role: String, content: String, reasoning: String = "", status: String = "", attachments: [String] = [], favoriteID: String? = nil, images: [ChatImage] = [], sources: [ChatSource] = [], documents: [ChatDocument] = [], writingCheck: WritingCheck? = nil) {
        self.id = id; self.role = role; self.content = content
        self.reasoning = reasoning; self.status = status
        self.attachments = attachments.isEmpty ? documents.map(\.filename) : attachments
        self.favoriteID = favoriteID; self.images = images; self.sources = sources; self.documents = documents; self.writingCheck = writingCheck
    }
    enum CodingKeys: String, CodingKey {
        case id, role, content, documents, images, sources
        case writingCheck = "writing_check"
        case reasoning = "reasoning_content", status = "generation_status", favoriteID = "favorite_id"
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(Int64.self, forKey: .id)
        role = try c.decode(String.self, forKey: .role)
        content = try c.decodeIfPresent(String.self, forKey: .content) ?? ""
        reasoning = try c.decodeIfPresent(String.self, forKey: .reasoning) ?? ""
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? ""
        favoriteID = try c.decodeIfPresent(String.self, forKey: .favoriteID)
        documents = try c.decodeIfPresent([ChatDocument].self, forKey: .documents) ?? []
        images = try c.decodeIfPresent([ChatImage].self, forKey: .images) ?? []
        sources = try c.decodeIfPresent([ChatSource].self, forKey: .sources) ?? []
        writingCheck = try c.decodeIfPresent(WritingCheck.self, forKey: .writingCheck)
        attachments = documents.map(\.filename)
    }
}

public struct LiveReply: Equatable, Sendable {
    public var content = ""
    public var reasoning = ""
    public var activity = "槑槑正在准备回答…"
    public var savedID: Int64?
    public var status = "interrupted"
    public init() {}
}

public enum PlatformError: Error, LocalizedError, Equatable {
    case invalidURL, invalidResponse, malformedStream, storage
    case http(Int, String)
    case smsLogin(String)
    case media(String)
    public var errorDescription: String? {
        switch self {
        case .invalidURL: return "服务器地址必须是完整的 HTTPS 域名"
        case .invalidResponse: return "服务器响应异常，请稍后刷新"
        case .malformedStream: return "流式连接异常，请刷新核对服务器记录"
        case .storage: return "无法保存本机状态，请检查设备空间后重试"
        case .smsLogin(let message), .media(let message): return message
        case .http(_, "短信登录暂未配置"): return "短信登录暂不可用，请使用账号密码登录"
        case .http(_, "手机号格式不正确"): return "请输入正确的中国大陆手机号"
        case .http(_, "短信服务暂时不可用，请稍后重试"), .http(_, "验证码发送失败，请检查后台短信配置"),
             .http(_, "验证码核验失败，请稍后重试"): return "短信服务暂不可用，请稍后重试或使用账号密码登录"
        case .http(_, "captcha incorrect"): return "验证码不正确或已过期，请重新输入"
        case .http(_, "password incorrect"): return "账号或密码不正确"
        case .http(_, "message not found"), .http(_, "conversation not found"): return "原消息或会话已删除，请刷新后重试"
        case .http(_, "favorite not found"): return "该收藏已移除，请刷新列表"
        case .http(_, "语音朗读暂未开启"): return "语音朗读暂未开启"
        case .http(_, "语音服务还没有配置好"), .http(_, "语音服务暂不可用"): return "语音服务暂不可用，请检查后台配置"
        case .http(_, "这条回答没有可朗读的文字"): return "这条回答没有可朗读的文字"
        case .http(_, "这条回答不存在或不可朗读"): return "这条回答不存在或不可朗读，请刷新聊天记录"
        case .http(_, "document not found"): return "材料已删除或不可访问，请重新选择材料"
        case .http(_, "材料不存在或仍在解析中"): return "材料不存在或仍在解析中，请刷新材料状态"
        case .http(_, "材料文件 OSS 还没有配置好"), .http(_, "阿里云文档解析还没有配置好"): return "材料解析服务暂未配置，请联系管理员"
        case .http(401, _): return "登录已失效，请重新登录"
        case .http(409, _): return "当前会话仍在生成，请稍后刷新核对"
        case .http(400, _): return "请求未被接受，请检查模型或联网配置"
        case .http(let status, _): return "服务暂时不可用（\(status)），请稍后重试"
        }
    }
    public var isUnauthorized: Bool {
        if case .http(401, _) = self { return true }; return false
    }
}
