import SwiftUI
import MeimeiCore

struct WritingView: View {
    let store: AppStore
    let conversationID: String
    @FocusState private var manuscriptFocused: Bool
    @State private var requirements = WritingRequirements()
    @State private var manuscript = ""
    @State private var version: WritingVersion?
    @State private var confirmReset = false
    @State private var confirmReload = false
    @Environment(\.dismiss) private var dismiss
    private var controller: WritingController { store.writing }
    var body: some View {
        NavigationStack {
            Form {
                modeSection
                if let error = controller.error { Section { Text(error).foregroundStyle(.red) } }
                if controller.state != nil { requirementsSection; manuscriptSection; versionsSection }
            }.scrollDismissesKeyboard(.interactively).disabled(controller.busy || store.locked)
            .navigationTitle("写稿模式").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("重新加载") { confirmReload = true }.disabled(controller.busy) }
                ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() }.disabled(controller.busy) }
            }
            .overlay { if controller.busy { ProgressView() } }
            .task { await reload() }
            .sheet(item: $version) { value in versionPreview(value) }
            .interactiveDismissDisabled(controller.busy)
            .confirmationDialog("重新加载会放弃本页未保存的编辑。", isPresented: $confirmReload, titleVisibility: .visible) { Button("重新加载") { Task { await reload() } } }
            .confirmationDialog("开始新项目？旧版本保留，本单要求及定稿锁定会清空。", isPresented: $confirmReset, titleVisibility: .visible) {
                Button("开始新项目", role: .destructive) { Task { if await controller.update(.reset) { sync() } } }
            }
        }
    }
    private var modeSection: some View {
        Section {
            Toggle("为此会话启用写稿", isOn: Binding(get: { controller.enabled }, set: { value in Task { _ = await controller.update(.enabled(value)) } })).disabled(controller.state == nil).accessibilityIdentifier("writingEnabled")
            Text("要求与底稿按会话保存，和 Web 同步。启用后每轮会增加一次要求整理调用，用量计入统计；不同客户建议新建对话。").font(.footnote).foregroundStyle(.secondary)
            if let notice = controller.state?.notice, !notice.isEmpty { Text(notice).foregroundStyle(.orange).font(.footnote) }
        }
    }
    private var requirementsSection: some View {
        Section("本单要求") {
            ForEach(Array(Self.textFields.enumerated()), id: \.offset) { _, field in
                TextField(field.0, text: Binding(get: { requirements[keyPath: field.1] }, set: { requirements[keyPath: field.1] = $0 }), axis: .vertical).lineLimit(1...6)
            }
            DisclosureGroup("检查词（每行一项）") {
                listField("必带词", \.required); listField("避用词", \.forbidden); listField("待补信息", \.missing)
            }
            LabeledContent("最少字数（0 不限）") { TextField("最少字数", value: $requirements.min_chars, format: .number).keyboardType(.numberPad).multilineTextAlignment(.trailing) }
            LabeledContent("最多字数（0 不限）") { TextField("最多字数", value: $requirements.max_chars, format: .number).keyboardType(.numberPad).multilineTextAlignment(.trailing) }
            Button("保存本单要求") { Task { _ = await controller.update(.requirements(requirements)) } }.disabled(!requirements.valid).accessibilityIdentifier("saveWritingRequirements")
        }
    }
    private var manuscriptSection: some View {
        Section(controller.state?.locked_version_id == 0 ? "当前底稿" : "已锁定定稿") {
            TextEditor(text: $manuscript).focused($manuscriptFocused).frame(minHeight: 200).disabled(controller.state?.locked_version_id != 0).accessibilityIdentifier("writingDraft")
            Text("手动保存会新增版本；锁定后需先解锁才能编辑。锁定保护由现有服务端执行，检查结果不代表事实已核实或客户验收。").font(.footnote).foregroundStyle(.secondary)
            Button("保存为新版本") { manuscriptFocused = false; Task { if await controller.update(.draft(manuscript)) { manuscript = controller.state?.current?.content ?? "" } } }.disabled(manuscript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || manuscript.count > 100000 || controller.state?.locked_version_id != 0).accessibilityIdentifier("saveWritingDraft")
            if let state = controller.state, state.current_version_id > 0 {
                Button(state.locked_version_id > 0 ? "解锁定稿" : "锁定定稿") { manuscriptFocused = false; Task { _ = await controller.update(.locked(state.locked_version_id == 0)) } }
                    .disabled(manuscript != (state.current?.content ?? "")).accessibilityIdentifier("lockWritingDraft")
            }
            Button("开始新项目", role: .destructive) { confirmReset = true }
        }
    }
    private var versionsSection: some View {
        Section("历史稿件") {
            ForEach(controller.state?.versions ?? []) { value in
                Button("\(value.label) · #\(value.id)") { Task { await controller.loadVersion(value.id); version = controller.preview } }.accessibilityIdentifier("writingVersion-\(value.id)")
            }
        }
    }
    private func versionPreview(_ value: WritingVersion) -> some View {
        NavigationStack {
            ScrollView { Text(value.content ?? "").textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding() }
                .navigationTitle(value.label)
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("关闭") { version = nil } }
                    ToolbarItem(placement: .confirmationAction) { Button("用作底稿") { Task { if await controller.update(.version(value.id)) { sync(); version = nil } } }.disabled(controller.busy) }
                }
        }.interactiveDismissDisabled(controller.busy)
    }
    private func listField(_ title: String, _ key: WritableKeyPath<WritingRequirements, [String]>) -> some View {
        TextField(title, text: Binding(get: { requirements[keyPath: key].joined(separator: "\n") }, set: { requirements[keyPath: key] = $0.components(separatedBy: .newlines).filter { !$0.isEmpty } }), axis: .vertical).lineLimit(2...6)
    }
    private func reload() async { if await controller.load(conversationID: conversationID) { sync() } }
    private func sync() { requirements = controller.state?.requirements ?? WritingRequirements(); manuscript = controller.state?.current?.content ?? "" }
    private static let textFields: [(String, WritableKeyPath<WritingRequirements, String>)] = [("项目", \.project), ("受众", \.audience), ("账号定位", \.account), ("稿件形式", \.format), ("语气风格", \.tone), ("表达重点", \.focus), ("事实与数据", \.facts), ("拍摄条件", \.shooting), ("其他要求", \.notes)]
}
