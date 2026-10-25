import SwiftUI
import UniformTypeIdentifiers
import MeimeiCore

enum ImportedMedia {
    static func copy(_ url: URL) throws -> URL {
        let access = url.startAccessingSecurityScopedResource(); defer { if access { url.stopAccessingSecurityScopedResource() } }
        let target = FileManager.default.temporaryDirectory.appendingPathComponent("media-source-" + UUID().uuidString)
        var coordinationError: NSError?; var result: Result<Void, Error>?
        NSFileCoordinator().coordinate(readingItemAt: url, options: [], error: &coordinationError) { source in
            result = Result {
                let values = try source.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
                guard values.isRegularFile == true else { throw PlatformError.media("请选择音视频文件") }
                try MediaLimits.validate(filename: url.lastPathComponent, size: values.fileSize ?? 0)
                try FileManager.default.copyItem(at: source, to: target)
                let attrs = try FileManager.default.attributesOfItem(atPath: target.path)
                try MediaLimits.validate(filename: url.lastPathComponent, size: (attrs[.size] as? NSNumber)?.intValue ?? 0)
                try FileManager.default.setAttributes([.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication], ofItemAtPath: target.path)
            }
        }
        do { if let coordinationError { throw coordinationError }; guard let result else { throw PlatformError.storage }; try result.get(); return target }
        catch { try? FileManager.default.removeItem(at: target); throw error }
    }
}

struct MediaView: View {
    let store: AppStore
    @State private var picker = false
    @State private var selected: MediaTask?
    @State private var deleting: MediaTask?
    @State private var file: URL?
    @State private var filename = ""
    @State private var preparing = false
    @State private var error: String?
    @State private var epoch = UUID()
    private var controller: MediaController { store.media }
    var body: some View {
        List {
            Section("上传音视频") {
                Button("从文件选择录音或视频", systemImage: "waveform") { picker = true }.disabled(controller.busy || preparing)
                if file != nil {
                    Text(filename)
                    Button("上传并开始分析") { if let file { self.file = nil; Task { await controller.upload(file: file, filename: filename) } } }.disabled(controller.busy).accessibilityIdentifier("uploadMedia")
                    Button("移除文件", role: .destructive) { removeFile() }.disabled(controller.busy)
                }
                if preparing { ProgressView("正在读取文件…") }
                if controller.busy { ProgressView(value: controller.progress); Text(controller.progress < 1 ? "正在上传或查询…" : "正在提交分析任务…").font(.footnote) }
                if let error = error ?? controller.error { Text(error).foregroundStyle(.red) }
                Text("支持 MP3、MP4、M4A、WAV 等，最多 500MB，仍受后台上传限制。分析沿用听悟服务与现有用量规则；提交后可稍后返回查看。中断后先刷新记录，避免重复提交。").font(.footnote).foregroundStyle(.secondary)
                #if DEBUG
                if ProcessInfo.processInfo.arguments.contains("--ui-testing") {
                    Button("测试音视频") { let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString); try? Data("offline".utf8).write(to: url); file = url; filename = "会议录音.m4a" }.accessibilityIdentifier("testMedia")
                }
                #endif
            }
            Section("分析记录") {
                if controller.tasks.isEmpty { Text("尚无分析记录").foregroundStyle(.secondary) }
                ForEach(controller.tasks) { task in
                    Button { selected = task } label: { VStack(alignment: .leading) { Text(task.filename); Text(task.label).font(.footnote).foregroundStyle(.secondary) } }.accessibilityIdentifier("mediaTask-\(task.id)")
                        .swipeActions { Button("删除", role: .destructive) { deleting = task }.disabled(controller.busy) }
                }
            }
        }
        .navigationTitle("音视频分析")
        .toolbar { ToolbarItem(placement: .primaryAction) { Button("刷新", systemImage: "arrow.clockwise") { Task { await controller.load() } }.disabled(controller.busy) } }
        .task { await controller.load() }.refreshable { await controller.load() }
        .sheet(item: $selected) { task in MediaResultView(store: store, taskID: task.id) }
        .fileImporter(isPresented: $picker, allowedContentTypes: [.data], allowsMultipleSelection: false) { result in
            guard case .success(let urls) = result, let url = urls.first else { return }
            let token = epoch; let owner = store.account?.id
            preparing = true; error = nil
            Task {
                defer { if token == epoch { preparing = false } }
                do {
                    let value = try await Task.detached { try ImportedMedia.copy(url) }.value
                    guard token == epoch, owner == store.account?.id, !Task.isCancelled else { try? FileManager.default.removeItem(at: value); return }
                    removeFile(); filename = url.lastPathComponent; file = value
                } catch { if token == epoch { self.error = (error as? PlatformError)?.localizedDescription ?? "文件读取失败，请重新选择" } }
            }
        }
        .onDisappear { epoch = UUID(); removeFile() }
        .confirmationDialog("删除分析记录？已创建的会话和 OSS 原文件保留。", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            Button("删除记录", role: .destructive) { if let deleting { Task { await controller.delete(deleting) } }; deleting = nil }
        }
    }
    private func removeFile() { if let file { try? FileManager.default.removeItem(at: file) }; file = nil }
}

private struct MediaResultView: View {
    let store: AppStore
    let taskID: String
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @State private var opened = false
    private var controller: MediaController { store.media }
    private var task: MediaTask? { controller.tasks.first { $0.id == taskID } }
    var body: some View {
        NavigationStack {
            List {
                if let task {
                    Section { Text(task.filename); Text(task.label); if !task.error_message.isEmpty { Text(task.error_message).foregroundStyle(.orange) } }
                    if !task.transcript_text.isEmpty { output("转写全文", task.transcript_text) }
                    if !task.summary_text.isEmpty { output("内容摘要", task.summary_text) }
                    if !task.outline_text.isEmpty { output("章节要点", task.outline_text) }
                    if !task.enhanced_summary.isEmpty { output("深度摘要", task.enhanced_summary) }
                    if !task.key_points.isEmpty { output("重点提取", task.key_points) }
                    if !task.mindmap_text.isEmpty { output("思维导图文本", task.mindmap_text) }
                    if !task.copywriting_text.isEmpty { output("文案", task.copywriting_text) }
                    if task.status == "completed" {
                        Button("打开分析会话继续提问") {
                            Task {
                                if let conversation = await controller.conversation(id: taskID, modelID: store.draft.modelID) {
                                    await store.refresh(); await store.select(conversation); opened = true
                                }
                            }
                        }.disabled(controller.busy || store.locked).accessibilityIdentifier("openMediaConversation")
                        if opened { Text("已打开分析会话，关闭工具返回聊天即可继续提问。").foregroundStyle(.secondary) }
                    }
                }
                if let error = controller.error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("分析结果")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("刷新进度") { Task { await controller.refresh(taskID) } }.disabled(controller.busy) }
                ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } }
            }
            .task(id: scenePhase) {
                guard scenePhase == .active else { return }
                for _ in 0..<12 {
                    guard task?.pending == true, !Task.isCancelled else { return }
                    await controller.refresh(taskID)
                    try? await Task.sleep(for: .seconds(5))
                }
            }
        }
    }
    private func output(_ title: String, _ text: String) -> some View {
        Section(title) { MarkdownView(content: text); Button("复制\(title)") { UIPasteboard.general.string = text } }
    }
}
