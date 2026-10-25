import Foundation

public struct OCRTask: Codable, Identifiable, Equatable, Sendable {
    public let id: String
    public let filename: String
    public let status: String
    public let recognized_text: String
    public let error_message: String
    public init(id: String, filename: String, status: String, recognized_text: String = "", error_message: String = "") {
        self.id = id; self.filename = filename; self.status = status; self.recognized_text = recognized_text; self.error_message = error_message
    }
    public var label: String { status == "completed" ? "识别完成" : status == "failed" ? "识别失败" : "处理中" }
}
