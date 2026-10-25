import SwiftUI
import PhotosUI
import AVFoundation
import MeimeiCore

struct OCRView: View {
    let store: AppStore
    @State private var photo: PhotosPickerItem?
    @State private var image: Data?
    @State private var preparing = false
    @State private var camera = false
    @State private var selected: OCRTask?
    @State private var deleting: OCRTask?
    @State private var preparationError: String?
    var body: some View {
        List {
            Section("拍照识别手写文字") {
                PhotosPicker(selection: $photo, matching: .images) { Label("从相册选择", systemImage: "photo") }.disabled(preparing || store.ocr.busy)
                Button("拍摄手写笔记", systemImage: "camera") {
                    Task {
                        guard UIImagePickerController.isSourceTypeAvailable(.camera) else { preparationError = "当前设备无法使用相机"; return }
                        let status = AVCaptureDevice.authorizationStatus(for: .video)
                        let allowed = status == .authorized ? true : await AVCaptureDevice.requestAccess(for: .video)
                        if allowed { camera = true } else { preparationError = "请在系统设置中允许槑槑使用相机，或从相册选择" }
                    }
                }.disabled(preparing || store.ocr.busy)
                if let image {
                    if let preview = UIImage(data: image) { Image(uiImage: preview).resizable().scaledToFit().frame(maxHeight: 180).accessibilityLabel("待识别图片") }
                    Button("开始识别") { let value = image; self.image = nil; Task { await store.ocr.upload(value) } }.disabled(store.ocr.busy).accessibilityIdentifier("startOCR")
                    Button("移除图片", role: .destructive) { self.image = nil }.disabled(store.ocr.busy)
                }
                if preparing { ProgressView("正在处理图片…") }
                if store.ocr.busy { ProgressView(value: store.ocr.progress); Text(store.ocr.progress < 1 ? "正在上传或读取记录…" : "正在识别，请稍候…").font(.footnote) }
                if let error = preparationError ?? store.ocr.error { Text(error).foregroundStyle(.red) }
                Text("图片会转换为 JPEG 后提交识别，结果与 Web 同步。请保持页面打开；请求中断后先刷新记录，避免重复计费。").font(.footnote).foregroundStyle(.secondary)
                #if DEBUG
                if ProcessInfo.processInfo.arguments.contains("--ui-testing") {
                    Button("测试手写图片") { image = Data([0xff,0xd8,0xff,0xd9]) }.accessibilityIdentifier("testOCRImage")
                }
                #endif
            }
            Section("识别记录") {
                if store.ocr.tasks.isEmpty { Text("尚无识别记录").foregroundStyle(.secondary) }
                ForEach(store.ocr.tasks) { task in
                    Button { selected = task } label: {
                        VStack(alignment: .leading) { Text(task.filename); Text(task.label).font(.footnote).foregroundStyle(.secondary) }
                    }.accessibilityIdentifier("ocrTask-\(task.id)")
                    .swipeActions { Button("删除", role: .destructive) { deleting = task }.disabled(store.ocr.busy) }
                }
            }
        }
        .navigationTitle("手写识别")
        .task { await store.ocr.load() }
        .refreshable { await store.ocr.load() }
        .toolbar { ToolbarItem(placement: .primaryAction) { Button("刷新", systemImage: "arrow.clockwise") { Task { await store.ocr.load() } }.disabled(store.ocr.busy) } }
        .sheet(item: $selected) { task in OCRResultView(store: store, task: task) }
        .sheet(isPresented: $camera) { ChatCamera { data in camera = false; if let data { Task { await prepare(data) } } }.ignoresSafeArea() }
        .onChange(of: photo) { _, item in
            Task { do { if let data = try await item?.loadTransferable(type: Data.self) { await prepare(data) } } catch { preparationError = "图片读取失败，请重新选择" }; photo = nil }
        }
        .confirmationDialog("删除识别记录？Web 记录也会删除，OSS 原图保留。", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
            Button("删除记录", role: .destructive) { if let deleting { Task { await store.ocr.delete(deleting) } }; deleting = nil }
        }
    }
    private func prepare(_ data: Data) async {
        guard !preparing else { return }; preparing = true; preparationError = nil
        defer { preparing = false }
        do {
            let value = try await Task.detached { try ChatImagePreparation.jpeg(data) }.value
            try Task.checkCancellation()
            guard value.count <= 10 * 1024 * 1024 else { throw PlatformError.media("图片不能超过 10MB") }
            image = value
        } catch { preparationError = (error as? PlatformError)?.localizedDescription ?? "图片处理失败" }
    }
}

private struct OCRResultView: View {
    let store: AppStore
    let task: OCRTask
    @State private var text: String
    @State private var replace = false
    @State private var owner: String?
    @State private var context: UUID?
    @State private var error: String?
    @Environment(\.dismiss) private var dismiss
    init(store: AppStore, task: OCRTask) { self.store = store; self.task = task; _text = State(initialValue: task.recognized_text) }
    var body: some View {
        NavigationStack {
            Form {
                Text(task.label)
                if !task.error_message.isEmpty { Text(task.error_message).foregroundStyle(.red) }
                if task.status == "completed" {
                    TextEditor(text: $text).frame(minHeight: 260).accessibilityIdentifier("ocrResultText")
                    Text("可先修正错字；此处修改仅用于复制或填入草稿，不覆盖云端原识别结果。").font(.footnote).foregroundStyle(.secondary)
                    Button("复制文字") { UIPasteboard.general.string = text }
                    Button("填入聊天草稿") { if store.draft.text.isEmpty { apply() } else { replace = true } }.disabled(text.isEmpty || store.locked).accessibilityIdentifier("applyOCR")
                }
                if let error { Text(error).foregroundStyle(.red) }
            }
            .navigationTitle("识别结果")
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("完成") { dismiss() } } }
            .onAppear { owner = store.account?.id; context = store.attachmentContext }
            .confirmationDialog("替换当前未发送的文字？", isPresented: $replace, titleVisibility: .visible) { Button("替换草稿", role: .destructive) { apply() } }
        }
    }
    private func apply() {
        guard owner == store.account?.id, context == store.attachmentContext, !store.locked else { error = "聊天位置已变化，请关闭后重新打开结果"; return }
        store.setText(text); dismiss()
    }
}
