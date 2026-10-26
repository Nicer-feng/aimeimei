import Foundation

public struct DailyReport: Decodable, Identifiable, Equatable, Sendable {
    public let id: Int64
    public let reportDate: String
    public let title: String
    public let content: String
    public let createdAt: Int64
    public let readAt: Int64
    public let simulation: Bool
    enum CodingKeys: String, CodingKey {
        case id, title, content, simulation
        case reportDate = "report_date", createdAt = "created_at", readAt = "read_at"
    }
}

public struct DailyReportsPage: Decodable, Sendable {
    public let reports: [DailyReport]
    public let unread: Int
    public let nextBefore: Int64?
    enum CodingKeys: String, CodingKey { case reports, unread; case nextBefore = "next_before" }
}
