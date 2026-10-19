import SwiftUI
import MeimeiCore

@main
struct MeimeiApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @State private var store: AppStore?
    @State private var launchError: String?
    @AppStorage("appearance") private var appearance = "system"

    var body: some Scene {
        WindowGroup {
            Group {
                if let store { RootView(store: store) }
                else if let launchError {
                    ContentUnavailableView("无法准备本机存储", systemImage: "externaldrive.badge.exclamationmark", description: Text(launchError))
                } else { ProgressView("正在准备槑槑…") }
            }
            .tint(Brand.accent)
            .preferredColorScheme(appearance == "light" ? .light : appearance == "dark" ? .dark : nil)
            .task {
                guard store == nil, launchError == nil else { return }
                do {
                    #if DEBUG
                    let testing = ProcessInfo.processInfo.arguments.contains("--ui-testing")
                        || ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
                    #else
                    let testing = false
                    #endif
                    let directory: URL
                    if testing { directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString) }
                    else { directory = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true).appendingPathComponent("Meimei", isDirectory: true) }
                    let local = try LocalState(directory: directory)
                    let api: any PlatformServing
                    #if DEBUG
                    if testing { api = DemoAPI() }
                    else { api = try PlatformAPI(baseURL: URL(string: "https://feng.asia/")!, credentials: SessionVault()) }
                    #else
                    api = try PlatformAPI(baseURL: URL(string: "https://feng.asia/")!, credentials: SessionVault())
                    #endif
                    let value = AppStore(api: api, local: local)
                    store = value; await value.start()
                } catch { launchError = "请检查设备空间和本机数据权限后重新打开应用" }
            }
            .onChange(of: scenePhase) { _, phase in
                guard phase != .inactive else { return }
                Task { await store?.sceneActive(phase == .active) }
            }
        }
    }
}
