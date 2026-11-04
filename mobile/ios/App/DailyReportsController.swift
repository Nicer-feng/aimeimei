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
    private(set) var pushEnabled = false
    var onUnauthorized: (() -> Void)?
    @ObservationIgnored private let api: any PlatformServing
    @ObservationIgnored private var revision = UUID()
    @ObservationIgnored private var savedToken: String?
    @ObservationIgnored private var registeredOwner: String?
    private var readIDs = Set<Int64>()
    let installationID: String
    let channel: ReportChannel

    init(api: any PlatformServing, channel: ReportChannel = .development) {
        self.api = api; self.channel = channel
        let key = "daily-report-installation"
        installationID = UserDefaults.standard.string(forKey: key) ?? UUID().uuidString
        UserDefaults.standard.set(installationID, forKey: key)
    }
    func bind(_ account: Account?) {
        let id = account.flatMap { (channel == .development ? $0.dailyReportsEnabled : $0.productReportsEnabled) ? $0.id : nil }
        let push = id != nil && (channel == .development ? account?.dailyPushEnabled : account?.productPushEnabled) == true
        if push != pushEnabled { savedToken = nil; registeredOwner = nil; notificationNotice = nil }
        pushEnabled = push
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
            let page: DailyReportsPage
            if channel == .development { page = try await api.dailyReports(before: older ? nextBefore : nil) }
            else { page = try await api.productReports(before: older ? nextBefore : nil) }
            guard ticket == revision, self.owner == owner else { return }
            reports = older ? reports + page.reports.filter { item in !reports.contains { $0.id == item.id } } : page.reports
            unread = page.unread; nextBefore = page.nextBefore
            if let focusID, !reports.contains(where: { $0.id == focusID }) {
                let item: DailyReport
                if channel == .development { item = try await api.dailyReport(id: focusID) }
                else { item = try await api.productReport(id: focusID) }
                guard ticket == revision else { return }
                reports.append(item)
            }
        } catch {
            guard ticket == revision else { return }
            if let platform = error as? PlatformError, case .http(404, _) = platform {
                let account = try? await api.currentAccount()
                guard ticket == revision else { return }
                bind(account); focusID = nil; presented = false
            }
            if (error as? PlatformError)?.isUnauthorized == true { onUnauthorized?() }
            self.error = "\(channel.title)暂时无法加载，请稍后重试"
        }
    }
    func read(_ report: DailyReport) async {
        guard owner != nil, report.readAt == 0, !readIDs.contains(report.id) else { return }
        readIDs.insert(report.id)
        let ticket = revision
        do {
            if channel == .development { try await api.readDailyReport(id: report.id) }
            else { try await api.readProductReport(id: report.id) }
            guard ticket == revision else { return }
            unread = max(0, unread - 1)
        } catch { if ticket == revision { readIDs.remove(report.id) } }
    }
    func isUnread(_ report: DailyReport) -> Bool { report.readAt == 0 && !readIDs.contains(report.id) }
    func register(token: String) async {
        guard pushEnabled, let owner, savedToken != token || registeredOwner != owner else { return }
        let ticket = revision
        do {
            if channel == .development { try await api.registerDailyDevice(installationID: installationID, token: token) }
            else { try await api.registerProductDevice(installationID: installationID, token: token) }
            guard ticket == revision, pushEnabled else { return }
            savedToken = token; registeredOwner = owner; notificationNotice = nil
        } catch {
            guard ticket == revision else { return }
            notificationNotice = "通知注册未完成，返回应用后会重试"
        }
    }
    func unregister() async {
        guard owner != nil else { return }
        if channel == .development { try? await api.removeDailyDevice(installationID: installationID) }
        else { try? await api.removeProductDevice(installationID: installationID) }
        savedToken = nil; registeredOwner = nil
    }
    func reportNotificationStatus(_ status: String) async {
        let ticket = revision
        let info = NativeClientDevice.info(authorization: status)
        guard owner != nil, !Task.isCancelled else { return }
        // 产品通知注册依赖当前会话的 iOS 设备记录，先等待设备上报完成。
        try? await api.reportClientDevice(info)
        guard revision == ticket else { return }
    }
    func open(id: Int64? = nil) {
        guard owner != nil else { return }
        focusID = id; presented = true
    }
}
