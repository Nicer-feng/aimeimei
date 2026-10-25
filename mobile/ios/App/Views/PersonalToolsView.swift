import SwiftUI
import MeimeiCore

struct ProfilesView: View {
    let store: AppStore
    @State private var edit: AIProfile?
    @State private var deleting: AIProfile?
    var body: some View {
        List {
            Section {
                Toggle("本次聊天加载 AI 档案", isOn: Binding(get: { store.draft.useProfile }, set: { store.setUseProfile($0) }))
                    .disabled(store.locked).accessibilityIdentifier("useProfileToggle")
                Text("开关随本机会话草稿保存；修改档案会同步到 Web，从下一次提问起生效。").font(.footnote).foregroundStyle(.secondary)
            }
            if let error = store.personal.error { Section { Text(error).foregroundStyle(.red) } }
            Section("我的档案") {
                if store.personal.profiles.isEmpty { Text("尚无档案，点击右上角添加").foregroundStyle(.secondary) }
                ForEach(store.personal.profiles) { profile in
                    Button { edit = profile } label: {
                        VStack(alignment: .leading, spacing: 5) {
                            HStack { Text(profile.title); if !profile.enabled { Text("已停用").font(.caption).foregroundStyle(.secondary) } }
                            Text(profile.content).lineLimit(2).font(.footnote).foregroundStyle(.secondary)
                        }
                    }.accessibilityIdentifier("profile-\(profile.id)")
                    .swipeActions { Button("删除", role: .destructive) { deleting = profile }.disabled(store.personal.busy) }
                }
            }
        }
        .navigationTitle("AI 档案")
        .toolbar { ToolbarItem(placement: .primaryAction) { Button("添加", systemImage: "plus") { edit = AIProfile() }.disabled(store.personal.busy).accessibilityIdentifier("addProfile") } }
        .overlay { if store.personal.busy { ProgressView() } }
        .task { await store.personal.loadProfiles() }
        .refreshable { await store.personal.loadProfiles() }
        .sheet(item: $edit) { profile in ProfileEditor(controller: store.personal, profile: profile) }
        .confirmationDialog("删除该档案？Web 端也会同步删除。", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            Button("删除档案", role: .destructive) { if let deleting { Task { await store.personal.delete(deleting) } }; deleting = nil }
        }
    }
}

private struct ProfileEditor: View {
    let controller: PersonalToolsController
    @State var profile: AIProfile
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            Form {
                TextField("标题", text: $profile.title).accessibilityIdentifier("profileTitle")
                TextEditor(text: $profile.content).frame(minHeight: 180).accessibilityIdentifier("profileContent")
                Picker("类型", selection: $profile.type) {
                    Text("个人背景").tag("profile"); Text("表达风格").tag("style"); Text("项目背景").tag("project"); Text("长期记忆").tag("memory")
                }
                TextField("排序（数字越小越靠前）", value: $profile.sort_order, format: .number).keyboardType(.numbersAndPunctuation)
                Toggle("启用", isOn: $profile.enabled)
                Text("标题最多 80 字，内容最多 12000 字。档案随提问加载，会占用上下文。").font(.footnote).foregroundStyle(.secondary)
                if let error = controller.error { Text(error).foregroundStyle(.red) }
            }
            .disabled(controller.busy)
            .navigationTitle(profile.id.isEmpty ? "新增档案" : "编辑档案")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("取消") { dismiss() }.disabled(controller.busy) }
                ToolbarItem(placement: .confirmationAction) { Button("保存") { Task { if await controller.save(profile) { dismiss() } } }.disabled(!profile.valid || controller.busy).accessibilityIdentifier("saveProfile") }
            }
            .interactiveDismissDisabled(controller.busy)
        }
    }
}

struct ConversationShareView: View {
    let controller: PersonalToolsController
    let conversationID: String
    let messageID: Int64?
    @State private var scope = ShareScope.conversation
    @State private var expires = 86400
    @State private var revoking: ConversationShare?
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            Form {
                Section("创建分享链接") {
                    Picker("范围", selection: $scope) { ForEach(ShareScope.allCases.filter { messageID != nil || $0 == .conversation }) { Text($0.label).tag($0) } }.accessibilityIdentifier("shareScope")
                    Picker("有效期", selection: $expires) { Text("1 小时").tag(3600); Text("6 小时").tag(21600); Text("1 天").tag(86400); Text("7 天").tag(604800) }
                    Text("链接持有者无需登录即可查看所选内容的当前快照（含图片与引用），后续聊天不会加入。请确认分享范围。").font(.footnote).foregroundStyle(.secondary)
                    Button("生成分享链接") { Task { await controller.create(conversationID: conversationID, scope: scope, messageID: messageID, expires: expires) } }.disabled(controller.busy).accessibilityIdentifier("createShare")
                }
                if let share = controller.createdShare, let url = share.publicURL(base: URL(string: "https://feng.asia/")!) {
                    Section("新建链接") { Text(url.absoluteString).textSelection(.enabled).font(.footnote); ShareLink("发送链接", item: url); Button("复制链接") { UIPasteboard.general.url = url } }
                }
                if let error = controller.error { Section { Text(error).foregroundStyle(.red) } }
                Section("此对话的分享记录") {
                    ForEach(controller.shares) { share in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(ShareScope(rawValue: share.scope)?.label ?? "分享")
                            Text("\(share.active ? "有效" : "已失效") · \(share.access_count) 次访问").font(.footnote).foregroundStyle(.secondary)
                            Text(Date(timeIntervalSince1970: share.expires_at), style: .date).font(.caption)
                            if share.active { Button("撤销链接", role: .destructive) { revoking = share }.accessibilityIdentifier("revokeShare-\(share.id)") }
                        }
                    }
                    Text("历史链接不保存完整令牌；如需再次发送，请重新生成。").font(.footnote).foregroundStyle(.secondary)
                }
            }.disabled(controller.busy)
            .navigationTitle("对话分享")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() }.disabled(controller.busy) } }
            .task { controller.clearShareContext(); scope = messageID == nil ? .conversation : .assistant; await controller.loadShares(conversationID: conversationID) }
            .onDisappear { controller.clearShareContext() }
            .interactiveDismissDisabled(controller.busy)
            .confirmationDialog("撤销后，原链接将无法访问。", isPresented: Binding(get: { revoking != nil }, set: { if !$0 { revoking = nil } }), titleVisibility: .visible) {
                Button("确认撤销", role: .destructive) { if let revoking { Task { await controller.revoke(revoking) } }; revoking = nil }
            }
        }
    }
}
