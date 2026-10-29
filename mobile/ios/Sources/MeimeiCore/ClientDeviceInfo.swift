import Foundation

public struct ClientDeviceInfo: Sendable, Equatable {
    public let installationID: String
    public let platform: String
    public let manufacturer: String
    public let model: String
    public let osVersion: String
    public let appVersion: String
    public let appBuild: String
    public let notificationAuthorization: String
    public init(installationID: String, platform: String, manufacturer: String, model: String, osVersion: String,
                appVersion: String, appBuild: String, notificationAuthorization: String = "unknown") {
        self.installationID = installationID; self.platform = platform; self.manufacturer = manufacturer
        self.model = model; self.osVersion = osVersion; self.appVersion = appVersion; self.appBuild = appBuild
        self.notificationAuthorization = notificationAuthorization
    }
    public var payload: [String: String] {
        ["installation_id": installationID, "platform": platform, "manufacturer": manufacturer, "model": model,
         "os_version": osVersion, "app_version": appVersion, "app_build": appBuild,
         "notification_authorization": notificationAuthorization]
    }
}
