import Foundation

public struct WritingRequirements: Codable, Equatable, Sendable {
    public var project = ""
    public var audience = ""
    public var account = ""
    public var format = ""
    public var tone = ""
    public var focus = ""
    public var facts = ""
    public var shooting = ""
    public var notes = ""
    public var required: [String] = []
    public var forbidden: [String] = []
    public var missing: [String] = []
    public var min_chars = 0
    public var max_chars = 0
    public init() {}
    enum CodingKeys: String, CodingKey { case project, audience, account, format, tone, focus, facts, shooting, notes, required, forbidden, missing, min_chars, max_chars }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        project = try c.decodeIfPresent(String.self, forKey: .project) ?? ""
        audience = try c.decodeIfPresent(String.self, forKey: .audience) ?? ""
        account = try c.decodeIfPresent(String.self, forKey: .account) ?? ""
        format = try c.decodeIfPresent(String.self, forKey: .format) ?? ""
        tone = try c.decodeIfPresent(String.self, forKey: .tone) ?? ""
        focus = try c.decodeIfPresent(String.self, forKey: .focus) ?? ""
        facts = try c.decodeIfPresent(String.self, forKey: .facts) ?? ""
        shooting = try c.decodeIfPresent(String.self, forKey: .shooting) ?? ""
        notes = try c.decodeIfPresent(String.self, forKey: .notes) ?? ""
        required = try c.decodeIfPresent([String].self, forKey: .required) ?? []
        forbidden = try c.decodeIfPresent([String].self, forKey: .forbidden) ?? []
        missing = try c.decodeIfPresent([String].self, forKey: .missing) ?? []
        min_chars = try c.decodeIfPresent(Int.self, forKey: .min_chars) ?? 0
        max_chars = try c.decodeIfPresent(Int.self, forKey: .max_chars) ?? 0
    }
    public var valid: Bool {
        [project, audience, account, format, tone, focus, facts, shooting, notes].allSatisfy { $0.count <= 6000 } &&
        [required, forbidden, missing].allSatisfy { $0.count <= 40 && $0.allSatisfy { $0.count <= 300 } } &&
        (0...50000).contains(min_chars) && (0...50000).contains(max_chars) && (max_chars == 0 || min_chars <= max_chars)
    }
}

public struct WritingVersion: Decodable, Identifiable, Equatable, Sendable {
    public let id: Int64
    public let label: String
    public let content: String?
}
public struct WritingState: Decodable, Equatable, Sendable {
    public let requirements: WritingRequirements
    public let revision: Int
    public let current_version_id: Int64
    public let locked_version_id: Int64
    public let current: WritingVersion?
    public let versions: [WritingVersion]
    public let notice: String
    public let selected: WritingVersion?
}
public struct WritingResponse: Decodable, Sendable {
    public let writing: WritingState
    public let enabled: Bool?
}
public enum WritingCommand: Sendable {
    case enabled(Bool), requirements(WritingRequirements), draft(String), version(Int64), locked(Bool), reset
    public func body(revision: Int) throws -> [String: Any] {
        var result: [String: Any] = ["revision": revision]
        switch self {
        case .enabled(let value): result["enabled"] = value
        case .requirements(let value):
            guard value.valid else { throw PlatformError.media("本单要求超出限制，请检查文字、检查词及字数范围") }
            result["requirements"] = try JSONSerialization.jsonObject(with: JSONEncoder().encode(value))
        case .draft(let value):
            let content = value.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !content.isEmpty, content.count <= 100000 else { throw PlatformError.media("稿件须为 1 至 100000 字") }
            result["draft"] = content
        case .version(let value): guard value > 0 else { throw PlatformError.invalidResponse }; result["version_id"] = value
        case .locked(let value): result["locked"] = value
        case .reset: result["action"] = "reset"
        }
        return result
    }
}

public struct WritingCheck: Decodable, Equatable, Sendable {
    public let issues: [String]
    public let body_chars: [Int]
    public let count_note: String
    public let scope: String
}
