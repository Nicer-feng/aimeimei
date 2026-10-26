import Foundation
import Observation
import MeimeiCore

@MainActor @Observable
final class DailyReportsController {
    private(set) var reports: [DailyReport] = []
    private(set) var unread = 0
    private(set) var busy = false
    private(set) var nextBefore: Int64?
    var error: String?
    var notificationNotice: String?
    var presented = false
    var focusID: Int64?
    private(set) var owner: String?
    var onUnauthorized: (() -> Void)?
    @ObservationIgnored private let api: any PlatformServing
    @ObservationIgnored private var revision = UUID()
    @ObservationIgnored private var savedToken: String?
    @ObservationIgnored private var registeredOwner: String?
    private var readIDs = Set<Int64>()
    let installationID: String

    init(api: any PlatformServing) {
        self.api = api
        let key = "daily-report-installation"
        installationID = UserDefaults.standard.string(forKey: key) ?? UUID().uuidString
        UserDefaults.standard.set(installationID, forKey: key)
    }
    func bind(_ account: Account?) {
        let id = account?.username == "feng" ? account?.id : nil
        guard id != owner else { return }
        revision = UUID(); owner = id; reports = []; unread = 0; nextBefore = nil
        busy = false; presented = false; focusID = nil; error = nil
        registeredOwner = nil; savedToken = nil; notificationNotice = nil
        readIDs = []
    }
    func refresh(older: Bool = false) async {
        guard let owner, !busy else { return }
        let ticket = revision
        busy = true; error = nil
        defer { if ticket == revision { busy = false } }
        do {
            let page = try await api.dailyReports(before: older ? nextBefore : nil)
            guard ticket == revision, self.owner == owner else { return }
            reports = older ? reports + page.reports.filter { item in !reports.contains { $0.id == item.id } } : page.reports
            unread = page.unread; nextBefore = page.nextBefore
            if let focusID, !reports.contains(where: { $0.id == focusID }) {
                let item = try await api.dailyReport(id: focusID)
                guard ticket == revision else { return }
                reports.append(item)
            }
        } catch {
            guard ticket == revision else { return }
            if (error as? PlatformError)?.isUnauthorized == true { onUnauthorized?() }
            self.error = "日报暂时无法加载，请稍后重试"
        }
    }
    func read(_ report: DailyReport) async {
        guard owner != nil, report.readAt == 0, !readIDs.contains(report.id) else { return }
        readIDs.insert(report.id)
        let ticket = revision
        do {
            try await api.readDailyReport(id: report.id)
            guard ticket == revision else { return }
            unread = max(0, unread - 1)
        } catch { if ticket == revision { readIDs.remove(report.id) } }
    }
    func isUnread(_ report: DailyReport) -> Bool { report.readAt == 0 && !readIDs.contains(report.id) }
    func register(token: String) async {
        guard let owner, savedToken != token || registeredOwner != owner else { return }
        let ticket = revision
        do {
            try await api.registerDailyDevice(installationID: installationID, token: token)
            guard ticket == revision else { return }
            savedToken = token; registeredOwner = owner; notificationNotice = nil
        } catch {
            guard ticket == revision else { return }
            notificationNotice = "通知注册未完成，返回应用后会重试"
        }
    }
    func unregister() async {
        guard owner != nil else { return }
        try? await api.removeDailyDevice(installationID: installationID)
        savedToken = nil; registeredOwner = nil
    }
    func open(id: Int64? = nil) {
        guard owner != nil else { return }
        focusID = id; presented = true
    }
}
