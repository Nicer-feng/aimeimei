import Foundation

public struct ChatImage: Codable, Identifiable, Equatable, Sendable {
    public let id: String
    public let filename: String
    public init(id: String, filename: String) { self.id = id; self.filename = filename }
}

public struct ChatSource: Decodable, Equatable, Sendable {
    public let title: String
    public let url: String
    public let snippet: String
    public let position: Int
    public var safeURL: URL? {
        guard let value = URL(string: url), ["http", "https"].contains(value.scheme?.lowercased() ?? ""),
              value.host != nil, value.user == nil, value.password == nil else { return nil }
        return value
    }
    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        title = try c.decodeIfPresent(String.self, forKey: .title) ?? "网页来源"
        url = try c.decodeIfPresent(String.self, forKey: .url) ?? ""
        snippet = try c.decodeIfPresent(String.self, forKey: .snippet) ?? ""
        position = try c.decodeIfPresent(Int.self, forKey: .position) ?? 0
    }
    enum CodingKeys: String, CodingKey { case title, url, snippet, position }
}

public struct ImageUploadPolicy: Decodable, Sendable {
    public let host: String
    public let accessKeyID: String
    public let policy: String
    public let signature: String
    public let keyPrefix: String
    public let maxSize: Int
    public let expiresAt: Double
    enum CodingKeys: String, CodingKey {
        case host, policy, signature
        case accessKeyID = "access_key_id", keyPrefix = "key_prefix", maxSize = "max_size", expiresAt = "expires_at"
    }
    public func form(image: Data, key: String, boundary: String) throws -> Data {
        guard !image.isEmpty, image.count <= maxSize, expiresAt > Date().timeIntervalSince1970,
              key.hasPrefix(keyPrefix), !key.contains("\r"), !key.contains("\n") else {
            throw PlatformError.media("图片太大或上传授权已过期，请重新选择图片")
        }
        var body = Data()
        for (name, value) in [("key", key), ("OSSAccessKeyId", accessKeyID), ("policy", policy),
                              ("Signature", signature), ("success_action_status", "204"), ("Content-Type", "image/jpeg")] {
            body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8))
        }
        body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"photo.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".utf8))
        body.append(image); body.append(Data("\r\n--\(boundary)--\r\n".utf8))
        return body
    }
}
