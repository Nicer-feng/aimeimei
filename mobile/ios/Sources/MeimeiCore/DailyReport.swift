import Foundation

public enum ReportChannel: String, Identifiable, Sendable {
    case development, product
    public var id: String { rawValue }
    public var title: String { self == .development ? "研发日报" : "每日产品推送" }
    public var notificationKind: String { self == .development ? "frontend_daily" : "product_daily" }
    public var entryIdentifier: String { self == .development ? "dailyReportEntry" : "productReportEntry" }
    public var itemIdentifier: String { self == .development ? "dailyReport" : "productReport" }
    public init?(notificationKind: String) {
        switch notificationKind {
        case "frontend_daily": self = .development
        case "product_daily": self = .product
        default: return nil
        }
    }
}

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
