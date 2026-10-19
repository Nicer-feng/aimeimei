import Foundation

/// 按 SSE 空行提交完整事件，不使用会忽略空行的 AsyncBytes.lines。
public struct SSEParser {
    private var data: [String] = []
    private var size = 0
    public init() {}
    public mutating func line(_ line: String) throws -> String? {
        if line.isEmpty {
            defer { data.removeAll(keepingCapacity: true); size = 0 }
            return data.isEmpty ? nil : data.joined(separator: "\n")
        }
        guard line.hasPrefix("data:") else { return nil }
        var value = String(line.dropFirst(5))
        if value.first == " " { value.removeFirst() }
        size += value.utf8.count
        guard size <= 1_048_576 else { throw PlatformError.malformedStream }
        data.append(value)
        return nil
    }
}

/// 按字节保留空行与 CR/LF 边界，完整一行后才解码 UTF-8，避免截断中文和表情。
public struct SSEByteParser {
    private var parser = SSEParser()
    private var buffer = Data()
    private var previousCR = false
    public init() {}
    public mutating func byte(_ byte: UInt8) throws -> String? {
        if byte == 10 || byte == 13 {
            if byte == 10 && previousCR { previousCR = false; return nil }
            previousCR = byte == 13
            guard let line = String(data: buffer, encoding: .utf8) else { throw PlatformError.malformedStream }
            buffer.removeAll(keepingCapacity: true)
            return try parser.line(line)
        }
        previousCR = false; buffer.append(byte)
        guard buffer.count <= 1_048_576 else { throw PlatformError.malformedStream }
        return nil
    }
}

public struct StreamEvent: Sendable {
    public let type: String
    public let content: String
    public let reasoning: String
    public let status: String
    public let conversationID: String?
    public let savedID: Int64?
    public let hasError: Bool

    public init(data: String) throws {
        guard let raw = data.data(using: .utf8),
              let value = try JSONSerialization.jsonObject(with: raw) as? [String: Any] else {
            throw PlatformError.malformedStream
        }
        type = value["type"] as? String ?? ""
        status = value["generation_status"] as? String ?? value["status"] as? String ?? ""
        conversationID = value["conversation_id"] as? String
        if let id = value["message_id"] as? Int64, id > 0 { savedID = id }
        else if let text = value["message_id"] as? String, let id = Int64(text), id > 0 { savedID = id }
        else { savedID = nil }
        hasError = value["error"] != nil
        let choice = (value["choices"] as? [[String: Any]])?.first
        let delta = choice?["delta"] as? [String: Any] ?? choice?["message"] as? [String: Any] ?? [:]
        content = delta["content"] as? String ?? ""
        reasoning = ["reasoning_content", "reasoning", "thinking"].compactMap { delta[$0] as? String }.first { !$0.isEmpty } ?? ""
    }
}

public struct ReplyAccumulator {
    public private(set) var reply = LiveReply()
    public init() {}
    public mutating func accept(_ event: StreamEvent, conversationID: String) throws {
        guard event.conversationID == nil || event.conversationID == conversationID else {
            throw PlatformError.malformedStream
        }
        if event.hasError { throw PlatformError.malformedStream }
        reply.content += event.content; reply.reasoning += event.reasoning
        guard reply.content.utf8.count + reply.reasoning.utf8.count <= 4_194_304 else {
            throw PlatformError.malformedStream
        }
        if !event.content.isEmpty { reply.activity = "槑槑正在回答…" }
        else if !event.reasoning.isEmpty { reply.activity = "槑槑正在思考…" }
        if event.type == "search_status" {
            reply.activity = event.status == "done" ? "资料已找到，槑槑正在整理…" : "槑槑正在上网查资料…"
        }
        if event.type == "message.failed" { reply.status = event.status.isEmpty ? "failed" : event.status }
        if event.type == "message_saved" {
            reply.savedID = event.savedID
            reply.status = event.status.isEmpty ? "interrupted" : event.status
        }
    }
}
