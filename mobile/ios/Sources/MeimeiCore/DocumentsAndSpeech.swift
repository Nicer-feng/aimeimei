import Foundation

public struct ChatDocument: Codable, Identifiable, Equatable, Sendable {
    public let id: String
    public let filename: String
    public let status: String
    public let errorMessage: String
    public var ready: Bool { !id.isEmpty && status == "completed" }
    public var processing: Bool { ["submitted", "processing"].contains(status) }
    public var statusLabel: String {
        if ready { return "解析完成" }
        if processing { return "解析中" }
        return "解析失败"
    }
    public init(id: String, filename: String, status: String, errorMessage: String = "") {
        self.id = id; self.filename = filename; self.status = status; self.errorMessage = errorMessage
    }
    enum CodingKeys: String, CodingKey { case id, filename, status; case errorMessage = "error_message" }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decodeIfPresent(String.self, forKey: .id) ?? ""; filename = try c.decodeIfPresent(String.self, forKey: .filename) ?? "材料"
        status = try c.decodeIfPresent(String.self, forKey: .status) ?? "failed"
        errorMessage = try c.decodeIfPresent(String.self, forKey: .errorMessage) ?? ""
    }
}

public enum DocumentLimits {
    public static let maxBytes = 50 * 1024 * 1024
    public static let extensions: Set<String> = ["pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "xlsm", "rtf", "txt", "md", "markdown", "html", "htm", "jpg", "jpeg", "png", "bmp", "gif", "webp"]
    public static func validate(filename: String, size: Int) throws {
        let ext = (filename as NSString).pathExtension.lowercased()
        guard extensions.contains(ext) else { throw PlatformError.media("请选择 PDF、Word、Excel、PPT、文本或图片材料") }
        guard size > 0, size <= maxBytes else { throw PlatformError.media("单份材料须在 50MB 以内且不能为空") }
        if ["jpg", "jpeg", "png", "bmp", "gif", "webp"].contains(ext), size > 20 * 1024 * 1024 {
            throw PlatformError.media("作为材料解析的单张图片不能超过 20MB")
        }
    }
}

public struct SpeechVoice: Decodable, Identifiable, Equatable, Sendable {
    public let id: String
    public let name: String
}

public struct SpeechConfiguration: Decodable, Sendable {
    public let enabled: Bool
    public let configured: Bool
    public let voices: [SpeechVoice]
    public let defaultVoice: String
    public let defaultSpeed: Double
    public var available: Bool { enabled && configured && !voices.isEmpty }
    enum CodingKeys: String, CodingKey {
        case enabled, configured, voices
        case defaultVoice = "default_voice", defaultSpeed = "default_speed"
    }
}

public struct PreparedSpeech: Decodable, Sendable {
    public let cached: Bool
    public let longText: Bool
    enum CodingKeys: String, CodingKey { case cached; case longText = "long_text" }
}

extension ImageUploadPolicy {
    public func documentForm(data: Data, key: String, boundary: String) throws -> Data {
        guard !data.isEmpty, data.count <= maxSize, expiresAt > Date().timeIntervalSince1970,
              key.hasPrefix(keyPrefix), !key.contains("\r"), !key.contains("\n") else {
            throw PlatformError.media("材料太大或上传授权已过期，请重新选择")
        }
        var body = Data()
        for (name, value) in [("key", key), ("OSSAccessKeyId", accessKeyID), ("policy", policy),
                              ("Signature", signature), ("success_action_status", "204")] {
            body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8))
        }
        // 实际文件名仅在平台登记；表单使用固定安全名称，避免控制字符进入 multipart 头。
        body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"document\"\r\nContent-Type: application/octet-stream\r\n\r\n".utf8))
        body.append(data); body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        return body
    }
}
