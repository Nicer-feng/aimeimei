import UIKit
import UserNotifications
import MeimeiCore

@MainActor
enum NativeClientDevice {
    static func info(authorization: String = "unknown") -> ClientDeviceInfo {
        let key = "daily-report-installation"
        let id = UserDefaults.standard.string(forKey: key) ?? UUID().uuidString
        UserDefaults.standard.set(id, forKey: key)
        var system = utsname(); uname(&system)
        let model = withUnsafePointer(to: &system.machine) {
            $0.withMemoryRebound(to: CChar.self, capacity: 256) { String(cString: $0) }
        }
        return ClientDeviceInfo(installationID: id, platform: "ios", manufacturer: "Apple",
            model: model, osVersion: UIDevice.current.systemVersion,
            appVersion: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "",
            appBuild: Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "",
            notificationAuthorization: authorization)
    }
    static func authorizationName(_ status: UNAuthorizationStatus) -> String {
        switch status {
        case .notDetermined: return "not_determined"
        case .denied: return "denied"
        case .authorized: return "authorized"
        case .provisional: return "provisional"
        case .ephemeral: return "ephemeral"
        @unknown default: return "unknown"
        }
    }
    static func current() async -> ClientDeviceInfo {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-testing") || ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil { return info() }
        #endif
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        return info(authorization: authorizationName(settings.authorizationStatus))
    }
}
