import UIKit
import UserNotifications

@MainActor
final class PushNotifications: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    private weak var reports: DailyReportsController?
    private var token: String?
    private var pendingID: Int64?
    func application(_ application: UIApplication, didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }
    func configure(_ reports: DailyReportsController) async {
        self.reports = reports
        guard reports.owner != nil else { return }
        openPending()
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-testing") { return }
        #endif
        let center = UNUserNotificationCenter.current()
        var settings = await center.notificationSettings()
        if settings.authorizationStatus == .notDetermined {
            _ = try? await center.requestAuthorization(options: [.alert, .sound, .badge])
            settings = await center.notificationSettings()
        }
        guard settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional else {
            reports.notificationNotice = "通知未开启，可在系统设置中允许日报通知"
            return
        }
        UIApplication.shared.registerForRemoteNotifications()
        if let token { await reports.register(token: token) }
        openPending()
    }
    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        token = deviceToken.map { String(format: "%02x", $0) }.joined()
        if let token, let reports { Task { await reports.register(token: token) } }
    }
    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        reports?.notificationNotice = "暂时无法连接苹果推送服务，返回应用后会重试"
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound, .list])
        Task { @MainActor in await self.reports?.refresh() }
    }
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
        let info = response.notification.request.content.userInfo
        let kind = info["kind"] as? String
        let id = (info["report_id"] as? NSNumber)?.int64Value
        Task { @MainActor in
            if kind == "frontend_daily", let id, id > 0 { self.pendingID = id; self.openPending() }
            completionHandler()
        }
    }
    private func openPending() {
        guard let id = pendingID, let reports, reports.owner != nil else { return }
        reports.open(id: id); pendingID = nil
    }
}
