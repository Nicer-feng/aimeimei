import Foundation

public struct MediaTask: Decodable, Identifiable, Equatable, Sendable {
    public let id: String
    public let filename: String
    public let status: String
    public let transcript_text: String
    public let summary_text: String
    public let outline_text: String
    public let enhanced_summary: String
    public let key_points: String
    public let mindmap_text: String
    public let copywriting_text: String
    public let error_message: String
    public var pending: Bool { ["submitted", "processing"].contains(status) }
    public var label: String { status == "completed" ? "分析完成" : status == "failed" ? "分析失败" : pending ? "分析中" : status }
}
public struct MediaConversation: Decodable, Sendable {
    public let conversation: Conversation
    public let task: MediaTask
}
public enum MediaLimits {
    public static let maxBytes = 500 * 1024 * 1024
    public static let extensions = ["mp3", "mp4", "m4a", "wav", "aac", "flac", "mov", "avi", "mkv", "webm"]
    public static func validate(filename: String, size: Int) throws {
        guard extensions.contains((filename as NSString).pathExtension.lowercased()) else { throw PlatformError.media("请选择 MP3、MP4、M4A、WAV、AAC、FLAC、MOV、AVI、MKV 或 WebM 文件") }
        guard size > 0, size <= maxBytes else { throw PlatformError.media("音视频文件须大于 0 且不超过 500MB") }
    }
}

extension ImageUploadPolicy {
    /// 音视频分块写入临时表单，避免在内存里复制整段视频。
    public func writeMediaForm(file: URL, key: String, boundary: String, output: URL) throws {
        let attrs = try FileManager.default.attributesOfItem(atPath: file.path)
        let size = (attrs[.size] as? NSNumber)?.intValue ?? 0
        guard size > 0, size <= maxSize, expiresAt > Date().timeIntervalSince1970, key.hasPrefix(keyPrefix), !key.contains("\r"), !key.contains("\n") else { throw PlatformError.media("文件过大或上传授权已过期") }
        guard FileManager.default.createFile(atPath: output.path, contents: nil) else { throw PlatformError.storage }
        let writer = try FileHandle(forWritingTo: output); defer { try? writer.close() }
        for (name, value) in [("key", key), ("OSSAccessKeyId", accessKeyID), ("policy", policy), ("Signature", signature), ("success_action_status", "204"), ("Content-Type", "application/octet-stream")] {
            try writer.write(contentsOf: Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8))
        }
        try writer.write(contentsOf: Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"media\"\r\nContent-Type: application/octet-stream\r\n\r\n".utf8))
        let reader = try FileHandle(forReadingFrom: file); defer { try? reader.close() }
        var total = 0
        while let chunk = try reader.read(upToCount: 65536), !chunk.isEmpty {
            try Task.checkCancellation(); total += chunk.count
            guard total <= size else { throw PlatformError.media("文件内容已变化，请重新选择") }
            try writer.write(contentsOf: chunk)
        }
        guard total == size else { throw PlatformError.media("文件内容已变化，请重新选择") }
        try writer.write(contentsOf: Data("\r\n--\(boundary)--\r\n".utf8))
    }
}
