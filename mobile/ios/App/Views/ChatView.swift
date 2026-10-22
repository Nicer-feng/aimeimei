import SwiftUI
import PhotosUI
import AVFoundation
import MeimeiCore

struct ChatView: View {
    let store: AppStore
    @State private var nearBottom = true
    @State private var confirmRestore = false
    @State private var showPrompts = false
    @State private var photos: [PhotosPickerItem] = []
    @State private var showPhotos = false
    @State private var showCamera = false
    @State private var preparing = false
    @State private var mediaContext = UUID()
    @FocusState private var composing: Bool
    var body: some View {
        VStack(spacing: 0) {
            modelBar
            Divider()
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 24) {
                        if store.messages.isEmpty && store.pending == nil { welcome }
                        ForEach(store.messages) { message in
                            MessageRow(store: store, message: message, favorite: store.isFavorite(message), canFavorite: !store.locked,
                                       onFavorite: { Task { await store.toggleFavorite(message) } }).equatable()
                                .id(message.id)
                                .overlay { RoundedRectangle(cornerRadius: 18).stroke(store.focusedMessageID == message.id ? Brand.accent : .clear, lineWidth: 2).allowsHitTesting(false) }
                        }
                        if let pending = store.pending,
                           !store.messages.contains(where: { pending.matches($0) }) {
                            MessageRow(store: store, message: ChatMessage(id: -1, role: "user", content: pending.content, images: (pending.imageIDs ?? []).map { ChatImage(id: $0, filename: "photo.jpg") })).equatable()
                        }
                        if let live = store.live {
                            VStack(alignment: .leading, spacing: 10) {
                                Label(store.streaming ? live.activity : "待核对的回答预览", systemImage: "sparkles")
                                    .font(.caption).foregroundStyle(.secondary)
                                if !live.reasoning.isEmpty {
                                    DisclosureGroup("思考过程") { Text(live.reasoning).font(.callout).foregroundStyle(.secondary).textSelection(.enabled) }
                                }
                                // 生成中只画纯文本，不随每个 token 重新解析 Markdown。
                                if !live.content.isEmpty { Text(live.content).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
                            }.accessibilityIdentifier("liveReply")
                        }
                        Color.clear.frame(height: 1).id("bottom")
                            .onAppear { nearBottom = true }.onDisappear { nearBottom = false }
                    }.padding(20).frame(maxWidth: 800).frame(maxWidth: .infinity)
                }
                .scrollDismissesKeyboard(.interactively)
                .accessibilityIdentifier("chatScroll")
                .onChange(of: store.live?.content) { _, _ in if nearBottom { proxy.scrollTo("bottom", anchor: .bottom) } }
                .onChange(of: store.messages.count) { _, _ in if nearBottom { proxy.scrollTo("bottom", anchor: .bottom) } }
                .onChange(of: store.selected?.id) { _, _ in
                    nearBottom = store.focusedMessageID == nil
                    if let id = store.focusedMessageID { proxy.scrollTo(id, anchor: .center) }
                    else { proxy.scrollTo("bottom", anchor: .bottom) }
                }
                .task(id: store.focusRequest) {
                    guard let id = store.focusedMessageID else { return }
                    await Task.yield()
                    guard !Task.isCancelled else { return }
                    nearBottom = false; proxy.scrollTo(id, anchor: .center)
                }
                .overlay(alignment: .bottomTrailing) {
                    if !nearBottom {
                        Button("回到底部", systemImage: "arrow.down") { nearBottom = true; withAnimation { proxy.scrollTo("bottom", anchor: .bottom) } }
                            .font(.caption).buttonStyle(.borderedProminent).padding()
                    }
                }
            }
            if let error = store.error { ErrorNotice(text: error).padding(.horizontal, 16).padding(.bottom, 8) }
            if store.pending != nil && !store.streaming {
                HStack {
                    Button("刷新核对") { Task { await store.refresh() } }
                    Spacer()
                    Button("恢复问题草稿") { confirmRestore = true }
                }.font(.footnote).padding(.horizontal, 20).padding(.bottom, 8).disabled(store.busy)
            }
        }
        .background(Brand.background)
        .sheet(isPresented: $showPrompts) { LibraryView(store: store, initial: .prompts) }
        .safeAreaInset(edge: .bottom, spacing: 0) { composer }
        .photosPicker(isPresented: $showPhotos, selection: $photos, maxSelectionCount: max(1, 5 - store.draft.images.count), matching: .images)
        .onChange(of: photos) { _, values in
            guard !values.isEmpty else { return }
            let context = mediaContext
            Task {
                preparing = true; defer { preparing = false; photos = [] }
                for photo in values {
                    do {
                        guard let data = try await photo.loadTransferable(type: Data.self) else {
                            throw PlatformError.media("无法读取相册图片，请重新选择")
                        }
                        await importImage(data, context: context)
                        if store.failedImage != nil { break }
                    } catch { store.error = "无法读取相册图片，请重新选择"; break }
                }
            }
        }
        .sheet(isPresented: $showCamera) {
            ChatCamera { data in
                showCamera = false
                if let data { let context = mediaContext; Task { await importImage(data, context: context) } }
            }.ignoresSafeArea()
        }
        .alert("已核对服务器记录？", isPresented: $confirmRestore) {
            Button("继续等待", role: .cancel) {}
            Button("恢复草稿") { store.restorePendingDraft() }
        } message: {
            Text("服务器可能仍在处理刚才的请求。恢复只把问题放回输入框；再次发送可能生成重复回答，请先刷新核对。")
        }
    }
    private var modelBar: some View {
        HStack(spacing: 12) {
            Menu {
                ForEach(store.models) { model in
                    Button {
                        Task { await store.configure(modelID: model.id, mode: store.draft.reasoningMode) }
                    } label: { if store.draft.modelID == model.id { Label(model.name, systemImage: "checkmark") } else { Text(model.name) } }
                }
            } label: { Label(store.currentModel?.name ?? "暂无可用模型", systemImage: "chevron.down").font(.subheadline.weight(.medium)).lineLimit(1) }
                .accessibilityIdentifier("modelMenu")
            Spacer(minLength: 4)
            if let model = store.currentModel {
                Label(model.supportsVision ? "可识图" : "仅文字", systemImage: model.supportsVision ? "photo" : "text.bubble")
                    .font(.caption2).foregroundStyle(.secondary).fixedSize()
            }
            if store.currentModel?.reasoningControl == true {
                Menu {
                    ForEach(ReasoningMode.allCases, id: \.self) { mode in
                        Button(mode.label) { Task { await store.configure(modelID: store.draft.modelID, mode: mode) } }
                    }
                } label: { Label(store.draft.reasoningMode.label, systemImage: "brain").font(.caption) }
                    .accessibilityIdentifier("reasoningMenu")
            }
            if store.busy { ProgressView().controlSize(.small) }
        }.padding(.horizontal, 20).padding(.vertical, 12).disabled(store.locked || store.pending != nil || preparing)
    }
    private var welcome: some View {
        VStack(spacing: 18) {
            Image("Welcome").resizable().scaledToFit().frame(maxWidth: 260).accessibilityHidden(true)
            Text("今天，想聊点什么？").font(.title2.bold())
            Text("一个想法，一点好奇，或是需要一起理清的小事。")
                .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
            VStack(spacing: 10) {
                ForEach(["帮我理清一个想法", "一起制定今天的计划", "把复杂问题讲简单一点"], id: \.self) { text in
                    Button { store.setText(text); composing = true } label: {
                        HStack { Text(text); Spacer(); Image(systemName: "arrow.up.left") }
                            .font(.subheadline).padding(14).background(.background, in: RoundedRectangle(cornerRadius: 14))
                    }.buttonStyle(.plain)
                }
            }.padding(.top, 8)
        }.frame(maxWidth: 460).frame(maxWidth: .infinity).padding(.vertical, 32).accessibilityIdentifier("welcomeView")
    }
    private var composer: some View {
        VStack(spacing: 10) {
            if !store.draft.images.isEmpty || store.uploadingImage != nil || store.failedImage != nil {
                ScrollView(.horizontal) {
                    HStack(alignment: .top, spacing: 10) {
                        ForEach(store.draft.images) { image in
                            VStack {
                                ChatImageTile(store: store, image: image)
                                Button("移除") { store.removeImage(image.id) }.font(.caption)
                                    .disabled(store.locked || store.pending != nil || preparing).accessibilityIdentifier("removeImage-\(image.id)")
                            }
                        }
                        if let data = store.uploadingImage ?? store.failedImage {
                            VStack(spacing: 5) {
                                if let image = UIImage(data: data) { Image(uiImage: image).resizable().scaledToFill().frame(width: 88, height: 66).clipped().clipShape(RoundedRectangle(cornerRadius: 10)) }
                                if store.uploadingImage != nil { ProgressView(value: store.uploadProgress).frame(width: 88); Text("上传中 \(Int(store.uploadProgress * 100))%").font(.caption2) }
                                else {
                                    Text("上传失败").font(.caption).foregroundStyle(.orange)
                                    HStack { Button("重试上传") { Task { await store.retryImage() } }; Button("移除") { store.discardFailedImage() } }.font(.caption)
                                }
                            }
                        }
                    }
                }
            }
            if !store.draft.images.isEmpty && store.currentModel?.supportsVision != true {
                Text("当前模型不支持图片，请切换支持图片的模型或移除图片").font(.caption).foregroundStyle(.orange)
            }
            if preparing && store.uploadingImage == nil { ProgressView("正在处理图片…").font(.caption) }
            HStack(alignment: .bottom, spacing: 10) {
                TextField("和槑槑说点什么…", text: Binding(get: { store.draft.text }, set: store.setText), axis: .vertical)
                    .lineLimit(1...7).focused($composing).padding(12)
                    .background(Brand.background, in: RoundedRectangle(cornerRadius: 16))
                    .disabled(store.streaming || store.pending != nil).accessibilityIdentifier("composerField")
                if store.streaming {
                    Button("停止接收", systemImage: "stop.fill") { store.stop() }
                        .labelStyle(.iconOnly).buttonStyle(.borderedProminent).controlSize(.large).accessibilityIdentifier("stopButton")
                } else {
                    Button("发送", systemImage: "arrow.up") {
                        composing = false; Task { await store.send() }
                    }.labelStyle(.iconOnly).buttonStyle(.borderedProminent).controlSize(.large)
                        .disabled(!store.canSend || preparing).accessibilityIdentifier("sendButton")
                }
            }
            HStack {
                Toggle(isOn: Binding(get: { store.draft.webSearch }, set: store.setSearch)) { Label("联网搜索", systemImage: "globe") }
                    .accessibilityIdentifier("webSearchToggle").toggleStyle(.button).font(.caption).disabled(store.locked || store.pending != nil)
                Button("提示词", systemImage: "text.book.closed") { composing = false; showPrompts = true }
                    .font(.caption).disabled(store.locked || store.pending != nil).accessibilityIdentifier("promptsButton")
                Menu {
                    Button("从相册选择", systemImage: "photo.on.rectangle") { composing = false; mediaContext = store.attachmentContext; showPhotos = true }
                    Button("拍照", systemImage: "camera") {
                        composing = false; mediaContext = store.attachmentContext
                        Task {
                            guard UIImagePickerController.isSourceTypeAvailable(.camera) else { store.error = "此设备无法使用相机"; return }
                            let allowed = await AVCaptureDevice.requestAccess(for: .video)
                            if allowed, mediaContext == store.attachmentContext { showCamera = true } else { store.error = "请在系统设置中允许槑槑使用相机，或从相册选择图片" }
                        }
                    }
                    #if DEBUG
                    if ProcessInfo.processInfo.arguments.contains("--ui-testing") {
                        Button("测试图片") {
                            let data = UIGraphicsImageRenderer(size: CGSize(width: 320, height: 200)).jpegData(withCompressionQuality: 0.8) { context in
                                UIColor.systemTeal.setFill(); context.fill(CGRect(x: 0, y: 0, width: 320, height: 200))
                                ("图片提问" as NSString).draw(at: CGPoint(x: 30, y: 80), withAttributes: [.font: UIFont.boldSystemFont(ofSize: 30), .foregroundColor: UIColor.white])
                            }
                            let context = store.attachmentContext; Task { await importImage(data, context: context) }
                        }
                    }
                    #endif
                } label: { Label("图片", systemImage: "photo") }
                    .font(.caption).disabled(store.locked || store.pending != nil || preparing || store.draft.images.count >= 5 || store.failedImage != nil || store.currentModel?.supportsVision != true)
                    .accessibilityIdentifier("addImageButton")
                Spacer()
                Button("刷新", systemImage: "arrow.clockwise") { Task { await store.refresh() } }
                    .labelStyle(.iconOnly).disabled(store.locked).accessibilityLabel("刷新服务器记录")
            }
        }.padding(.horizontal, 16).padding(.vertical, 12).background(.bar)
    }
    private func importImage(_ data: Data, context: UUID) async {
        let wasPreparing = preparing
        preparing = true; defer { preparing = wasPreparing }
        do {
            let jpeg = try await Task.detached { try ChatImagePreparation.jpeg(data) }.value
            await store.addImage(jpeg, context: context)
        } catch { store.error = (error as? PlatformError)?.localizedDescription ?? "图片处理失败，请重新选择" }
    }
}

private struct MessageRow: View, Equatable {
    let store: AppStore
    let message: ChatMessage
    @State private var showSources = false
    var favorite = false
    var canFavorite = false
    var onFavorite: (() -> Void)?
    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.message == rhs.message && lhs.favorite == rhs.favorite && lhs.canFavorite == rhs.canFavorite
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Label(message.role == "user" ? "你" : "槑槑", systemImage: message.role == "user" ? "person.crop.circle" : "sparkles")
                    .font(.caption.weight(.medium)).foregroundStyle(.secondary)
                Spacer()
                if message.role == "assistant" && message.id > 0 && !message.content.isEmpty {
                    Button(favorite ? "取消收藏" : "收藏回答", systemImage: favorite ? "star.fill" : "star") { onFavorite?() }
                        .labelStyle(.iconOnly).disabled(!canFavorite).accessibilityIdentifier("favoriteMessage-\(message.id)")
                }
                if !message.content.isEmpty {
                    ShareLink(item: message.content) { Image(systemName: "square.and.arrow.up") }.accessibilityLabel("分享消息")
                    Button("复制", systemImage: "doc.on.doc") { UIPasteboard.general.string = message.content }
                        .labelStyle(.iconOnly).accessibilityLabel("复制消息")
                }
            }.font(.caption)
            if !message.reasoning.isEmpty {
                DisclosureGroup("思考过程") { Text(message.reasoning).font(.callout).foregroundStyle(.secondary).textSelection(.enabled) }
            }
            if message.role == "user" { Text(message.content).textSelection(.enabled) }
            else { MarkdownView(content: message.content) }
            if !message.images.isEmpty {
                ScrollView(.horizontal) { HStack { ForEach(message.images) { image in ChatImageTile(store: store, image: image) } } }
            }
            if !message.sources.isEmpty {
                Button("联网来源 · \(message.sources.count)", systemImage: "globe") { showSources = true }
                    .font(.footnote).accessibilityIdentifier("sources-\(message.id)")
            }
            if !message.attachments.isEmpty {
                ForEach(Array(message.attachments.enumerated()), id: \.offset) { _, name in
                    Label(name, systemImage: "paperclip").font(.footnote).foregroundStyle(.secondary)
                }
            }
            if message.role == "assistant" && ["failed", "interrupted"].contains(message.status) {
                Label("回答未完整生成", systemImage: "exclamationmark.circle").font(.caption).foregroundStyle(.orange)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading).padding(16)
        .background(message.role == "user" ? Brand.accent.opacity(0.07) : Color(uiColor: .secondarySystemGroupedBackground), in: RoundedRectangle(cornerRadius: 18))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("message-\(message.id)")
        .sheet(isPresented: $showSources) { ChatSourcesView(sources: message.sources) }
    }
}
