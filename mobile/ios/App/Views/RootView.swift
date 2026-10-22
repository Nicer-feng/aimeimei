import SwiftUI

struct RootView: View {
    let store: AppStore
    @State private var showHistory = false
    @State private var showSettings = false
    @State private var librarySection: LibrarySection?
    var body: some View {
        Group {
            if store.starting { ProgressView("正在恢复账号…") }
            else if store.account == nil { LoginView(store: store) }
            else {
                NavigationStack {
                    ChatView(store: store)
                        .navigationTitle("AI槑槑")
                        .navigationBarTitleDisplayMode(.inline)
                        .toolbar {
                            ToolbarItem(placement: .topBarLeading) {
                                Button("历史", systemImage: "sidebar.left") { showHistory = true }
                                    .accessibilityIdentifier("historyButton").disabled(store.locked)
                            }
                            ToolbarItem(placement: .topBarLeading) {
                                Button("资料库", systemImage: "square.grid.2x2") { librarySection = .favorites }
                                    .accessibilityIdentifier("libraryButton").disabled(store.locked)
                            }
                            ToolbarItemGroup(placement: .topBarTrailing) {
                                Button("新聊天", systemImage: "square.and.pencil") { store.newChat() }
                                    .accessibilityIdentifier("newChatButton").disabled(store.locked)
                                Button("设置", systemImage: "gearshape") { showSettings = true }
                                    .accessibilityIdentifier("settingsButton")
                            }
                        }
                }
            }
        }
        .sheet(isPresented: $showHistory) { HistoryView(store: store) }
        .sheet(isPresented: $showSettings) { SettingsView(store: store) }
        .sheet(item: $librarySection) { LibraryView(store: store, initial: $0) }
        .onChange(of: store.account?.id) { _, account in
            if account == nil { showSettings = false; showHistory = false; librarySection = nil }
        }
        .environment(\.openURL, OpenURLAction { url in
            guard ["https", "http"].contains(url.scheme?.lowercased() ?? "") else { return .discarded }
            return .systemAction
        })
    }
}

private struct SettingsView: View {
    let store: AppStore
    @Environment(\.dismiss) private var dismiss
    @AppStorage("appearance") private var appearance = "system"
    @State private var confirmLogout = false
    var body: some View {
        NavigationStack {
            Form {
                Section("账号") {
                    LabeledContent("当前账号", value: store.account?.label ?? "")
                    Text("与网页版使用同一账号和云端聊天记录").font(.footnote).foregroundStyle(.secondary)
                }
                Section("外观") {
                    Picker("主题", selection: $appearance) {
                        Text("跟随系统").tag("system"); Text("浅色").tag("light"); Text("深色").tag("dark")
                    }
                }
                Section("关于") {
                    LabeledContent("版本", value: "\(Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.2.0") (\(Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "1"))")
                    Text("支持 iOS 17 及以上版本").font(.footnote).foregroundStyle(.secondary)
                    Text("切后台会结束接收；返回后核对服务器已保存内容。不会自动重发问题。").font(.footnote).foregroundStyle(.secondary)
                }
                Section {
                    Button("退出登录", role: .destructive) { confirmLogout = true }.disabled(store.locked)
                }
            }
            .navigationTitle("设置").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
            .confirmationDialog("确认退出当前账号？", isPresented: $confirmLogout, titleVisibility: .visible) {
                Button("退出登录", role: .destructive) { Task { await store.logout() } }
            }
        }
    }
}
