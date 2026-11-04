import UIKit
import UserNotifications
import MeimeiCore

@MainActor
final class PushNotifications: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    private weak var reports: DailyReportsController?
    private weak var products: DailyReportsController?
    private var token: String?
    private var pending: (channel: ReportChannel, id: Int64)?
    private var boundOwner: String?
    private var registrationReady = false
    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }
    func configure(_ reports: DailyReportsController, products: DailyReportsController) async {
        self.reports = reports; self.products = products
        let owner = reports.owner ?? products.owner
        if boundOwner != owner {
            if boundOwner != nil { pending = nil }
            boundOwner = owner
        }
        registrationReady = false
        guard let owner else { return }
        openPending()
        guard reports.pushEnabled || products.pushEnabled else { return }
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-testing")
            || ProcessInfo.processInfo.environment["MEIMEI_OFFLINE_TESTS"] == "1"
            || ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil { return }
        #endif
        let center = UNUserNotificationCenter.current()
        var settings = await center.notificationSettings()
        if settings.authorizationStatus == .notDetermined {
            _ = try? await center.requestAuthorization(options: [.alert, .sound, .badge])
            settings = await center.notificationSettings()
        }
        let active = reports.owner != nil ? reports : products
        await active.reportNotificationStatus(NativeClientDevice.authorizationName(settings.authorizationStatus))
        guard boundOwner == owner else { return }
        guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else {
            for controller in [reports, products] where controller.pushEnabled {
                controller.notificationNotice = "通知未开启，可在系统设置中允许通知"
            }
            return
        }
        registrationReady = true
        UIApplication.shared.registerForRemoteNotifications()
        await registerDevices()
        openPending()
    }
    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        token = deviceToken.map { String(format: "%02x", $0) }.joined()
        Task { await registerDevices() }
    }
    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        reports?.notificationNotice = "暂时无法连接苹果推送服务，返回应用后会重试"
        products?.notificationNotice = "暂时无法连接苹果推送服务，返回应用后会重试"
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound, .list])
        let kind = notification.request.content.userInfo["kind"] as? String
        Task { @MainActor in
            if kind == ReportChannel.product.notificationKind { await self.products?.refresh() }
            else if kind == ReportChannel.development.notificationKind { await self.reports?.refresh() }
        }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
        let info = response.notification.request.content.userInfo
        let kind = info["kind"] as? String
        let id = (info["report_id"] as? NSNumber)?.int64Value
        Task { @MainActor in
            self.receive(kind: kind, reportID: id)
            completionHandler()
        }
    }
    func receive(kind: String?, reportID: Int64?) {
        guard let kind, let channel = ReportChannel(notificationKind: kind), let reportID, reportID > 0 else { return }
        pending = (channel, reportID); openPending()
    }
    private func registerDevices() async {
        guard registrationReady, let token, let owner = boundOwner else { return }
        if let reports, reports.owner == owner { await reports.register(token: token) }
        guard boundOwner == owner else { return }
        if let products, products.owner == owner { await products.register(token: token) }
    }
    private func openPending() {
        guard let pending else { return }
        let selected = pending.channel == .development ? reports : products
        let other = pending.channel == .development ? products : reports
        guard let selected, selected.owner != nil else { return }
        other?.presented = false
        selected.open(id: pending.id); self.pending = nil
    }
}
