import Foundation
import Observation
import MeimeiCore

@MainActor @Observable
final class AppStore {
    private(set) var account: Account?
    private(set) var captcha: Captcha?
    private(set) var smsConfig: SMSLoginConfiguration?
    private(set) var smsLogin = SMSLoginState()
    private(set) var loginNotice: String?
    private(set) var conversations: [Conversation] = []
    private(set) var models: [ChatModel] = []
    private(set) var selected: Conversation?
    private(set) var messages: [ChatMessage] = []
    private(set) var favorites: [FavoriteMessage] = []
    private(set) var prompts: [PromptTemplate] = []
    private(set) var searchResults: [GlobalSearchResult] = []
    private(set) var searching = false
    private(set) var searchError: String?
    private(set) var focusedMessageID: Int64?
    private(set) var focusRequest = UUID()
    @ObservationIgnored private var searchRequest = UUID()
    @ObservationIgnored private var favoriteOverrides: [Int64: Bool] = [:]
    private(set) var draft = Draft()
    private(set) var uploadingImage: Data?
    private(set) var failedImage: Data?
    private(set) var uploadProgress = 0.0
    private(set) var attachmentContext = UUID()
    private(set) var pending: PendingSend?
    private(set) var live: LiveReply?
    private(set) var busy = false
    private(set) var starting = true
    private(set) var streaming = false
    var error: String?
    @ObservationIgnored private let api: any PlatformServing
    @ObservationIgnored private let local: LocalState
    @ObservationIgnored private var generation: Task<Void, Never>?
    @ObservationIgnored private var runID = UUID()
    @ObservationIgnored private var accumulator = ReplyAccumulator()
    @ObservationIgnored private var lastRender = Date.distantPast
    @ObservationIgnored private var foreground = true

    init(api: any PlatformServing, local: LocalState) { self.api = api; self.local = local }
    var locked: Bool { busy || streaming }
    var currentModel: ChatModel? { models.first { $0.id == draft.modelID } }
    var canSend: Bool {
        !locked && pending == nil && (!draft.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !draft.images.isEmpty) && currentModel != nil && failedImage == nil && (draft.images.isEmpty || currentModel?.supportsVision == true)
    }
    private var conversationID: String { selected?.id ?? "" }

    private func report(_ failure: Error) {
        if failure is CancellationError { return }
        if let error = failure as? URLError, error.code == .cancelled { return }
        if let platform = failure as? PlatformError {
            if platform.isUnauthorized, account != nil { clearAccount() }
            error = platform.localizedDescription
        } else if failure is URLError {
            error = "网络连接失败，请检查网络后刷新；未确认的消息不会自动重发"
        } else { error = "操作失败，请稍后刷新重试" }
    }
    private func work(_ operation: () async throws -> Void) async {
        guard !locked else { return }
        busy = true; error = nil
        defer { busy = false }
        do { try await operation() } catch { report(error) }
    }
    func start() async {
        await work {
            if let user = try await api.currentAccount() {
                account = user
                try await loadWorkspace()
                try await restorePosition()
            } else {
                smsConfig = try? await api.smsLoginConfig()
                captcha = try await api.captcha()
            }
        }
        starting = false
    }
    func refreshCaptcha() async {
        await work { captcha = try await api.captcha() }
    }
    func login(username: String, password: String, answer: String) async {
        guard let challenge = captcha else { await refreshCaptcha(); return }
        await work {
            do {
                let user = try await api.login(username: username, password: password, captcha: challenge, answer: answer)
                account = user; captcha = nil; smsLogin = SMSLoginState(); loginNotice = nil
                try await loadWorkspace(); try await restorePosition()
            } catch {
                if account == nil { captcha = try? await api.captcha() }
                throw error
            }
        }
    }
    func setLoginPhone(_ value: String) {
        guard !busy else { return }
        smsLogin.setPhone(value); error = nil; loginNotice = nil
    }
    func loadSMSConfigurationIfNeeded() async {
        // 已登录冷启动后若会话中途失效，返回登录页时也要能启用短信入口。
        guard account == nil, smsConfig == nil else { return }
        smsConfig = try? await api.smsLoginConfig()
    }
    func sendLoginSMS() async {
        guard smsConfig?.available == true, smsLogin.canSend() else { return }
        await work {
            loginNotice = nil
            let challenge = try await api.sendLoginSMS(phone: smsLogin.phone)
            try smsLogin.accept(challenge)
            loginNotice = "如手机号已绑定并启用，验证码将很快送达。"
        }
    }
    func loginSMS(code: String) async {
        guard smsConfig?.available == true, smsLogin.canVerify(code: code), let challenge = smsLogin.challenge else {
            error = "请先获取验证码，并输入有效的 6 位短信验证码"; return
        }
        await work {
            let user = try await api.loginSMS(phone: smsLogin.phone, code: code, challengeID: challenge.id)
            account = user; captcha = nil; smsLogin = SMSLoginState(); loginNotice = nil
            try await loadWorkspace(); try await restorePosition()
        }
    }
    func clearLoginFeedback() { error = nil; loginNotice = nil }
    private func clearAccount() {
        generation?.cancel(); runID = UUID()
        account = nil; selected = nil; messages = []; conversations = []; models = []
        favorites = []; prompts = []; favoriteOverrides = [:]; resetSearch(); focusedMessageID = nil
        uploadingImage = nil; failedImage = nil; attachmentContext = UUID()
        draft = Draft(); pending = nil; live = nil; streaming = false; captcha = nil
        smsLogin = SMSLoginState(); loginNotice = nil
        do { try api.clearCredential() } catch { self.error = "本机登录凭证未能清除，请重试退出" }
    }
    func logout() async {
        await work {
            do { try await api.logout() }
            catch { self.error = "网络未能确认服务器退出；本机登录状态已清除" }
            clearAccount()
            smsConfig = try? await api.smsLoginConfig()
            captcha = try? await api.captcha()
        }
    }
    private func loadWorkspace() async throws {
        let list = try await api.conversations()
        let available = try await api.models()
        conversations = list; models = available
        if let selected {
            self.selected = list.first { $0.id == selected.id }
            if let current = self.selected {
                // 网页或其它设备修改配置后，同步服务端模型，但保留本机未发送草稿。
                draft.modelID = current.modelID; draft.reasoningMode = current.reasoningMode; saveDraft()
            }
        }
    }
    private func restoreDraft() {
        uploadingImage = nil; failedImage = nil; attachmentContext = UUID()
        guard let account else { return }
        draft = local.draft(accountID: account.id, conversationID: conversationID)
        if let selected {
            draft.modelID = selected.modelID; draft.reasoningMode = selected.reasoningMode
        } else if !models.contains(where: { $0.id == draft.modelID }) { draft.modelID = models.first?.id ?? "" }
        pending = local.pending(accountID: account.id, conversationID: conversationID)
    }
    private func restorePosition() async throws {
        selected = nil; messages = []; live = nil; restoreDraft()
        guard let account else { return }
        // 正常启动和重新登录都从新聊天开始；只有未确认发送才恢复原会话。
        for item in local.pendingSends(accountID: account.id).sorted(by: { $0.baseline > $1.baseline }) {
            if let conversation = conversations.first(where: { $0.id == item.conversationID }) {
                selected = conversation; restoreDraft(); try await loadMessages(); return
            }
        }
    }
    private func saveDraft() {
        guard let account else { return }
        do { try local.setDraft(draft, accountID: account.id, conversationID: conversationID) }
        catch { self.error = "草稿暂未保存，请检查设备空间" }
    }
    func removeImage(_ id: String) {
        guard !locked, pending == nil else { return }
        draft.images.removeAll { $0.id == id }; saveDraft()
    }
    func discardFailedImage() { guard !locked else { return }; failedImage = nil; error = nil }
    func retryImage() async { if let data = failedImage { await addImage(data) } }
    func addImage(_ data: Data, context: UUID? = nil) async {
        let expectedContext = context ?? attachmentContext
        let expectedOwner = account?.id
        // 从相册/相机返回可能同时触发前台刷新，等待 GET 完成，避免丢弃刚选的图片。
        for _ in 0..<100 {
            guard !Task.isCancelled, account?.id == expectedOwner, attachmentContext == expectedContext else { return }
            if !busy { break }
            try? await Task.sleep(for: .milliseconds(100))
        }
        guard account != nil, attachmentContext == expectedContext, pending == nil, !streaming else { return }
        guard !busy else { failedImage = data; error = "当前操作尚未结束，请稍后重试上传"; return }
        guard currentModel?.supportsVision == true else { error = "请先切换到支持图片的模型"; return }
        guard draft.images.count < 5 else { error = "单次最多选择 5 张图片"; return }
        let owner = account?.id; let target = attachmentContext
        await work {
            uploadingImage = data; failedImage = nil; uploadProgress = 0
            defer { uploadingImage = nil }
            do {
                let image = try await api.uploadImage(data) { [weak self] value in
                    Task { @MainActor in
                        guard let self, self.attachmentContext == target, self.uploadingImage != nil else { return }
                        self.uploadProgress = value
                    }
                }
                guard account?.id == owner, attachmentContext == target else { return }
                draft.images.append(image); saveDraft()
            } catch {
                if account?.id == owner, attachmentContext == target { failedImage = data }
                throw error
            }
        }
    }
    func imageData(_ image: ChatImage) async throws -> Data {
        guard let owner = account?.id else { throw CancellationError() }
        do {
            let data = try await api.imageData(id: image.id)
            guard account?.id == owner else { throw CancellationError() }
            return data
        } catch {
            if let failure = error as? PlatformError, failure.isUnauthorized { report(failure) }
            throw error
        }
    }
    func setText(_ text: String) { draft.text = text; saveDraft() }
    func setSearch(_ enabled: Bool) { draft.webSearch = enabled; saveDraft() }
    func configure(modelID: String, mode: ReasoningMode) async {
        guard pending == nil else { return }
        await work {
            if let selected {
                self.selected = try await api.configureConversation(id: selected.id, modelID: modelID, mode: mode)
            }
            draft.modelID = modelID; draft.reasoningMode = mode; saveDraft()
        }
    }
    func newChat() {
        guard !locked else { return }
        generation?.cancel(); runID = UUID()
        selected = nil; messages = []; live = nil; restoreDraft(); error = nil; focusedMessageID = nil
    }
    func select(_ item: Conversation) async {
        await work {
            generation?.cancel(); runID = UUID()
            let history = try await api.messages(id: item.id)
            selected = item; messages = history; live = nil; focusedMessageID = nil; restoreDraft()
            for message in history { favoriteOverrides[message.id] = nil }
            try resolvePending()
        }
    }
    func refresh() async {
        guard account != nil else { await start(); return }
        await work {
            guard let user = try await api.currentAccount(), user.id == account?.id else {
                clearAccount(); captcha = try await api.captcha(); return
            }
            let oldID = selected?.id
            try await loadWorkspace()
            if selected != nil { try await loadMessages() }
            else if oldID != nil { messages = []; live = nil; restoreDraft() }
        }
    }
    private func loadMessages() async throws {
        guard let selected else { return }
        messages = try await api.messages(id: selected.id)
        for message in messages { favoriteOverrides[message.id] = nil }
        try resolvePending()
    }
    private func resolvePending() throws {
        guard let account, let pending, let reply = pending.reply(in: messages) else { return }
        guard ["completed", "interrupted", "failed"].contains(reply.status) else { return }
        try local.setPending(nil, accountID: account.id, conversationID: pending.conversationID)
        self.pending = nil; live = nil
        if reply.status != "completed" { error = "回答未完整生成，服务器已保存收到的内容" }
    }
    func rename(_ item: Conversation, title: String) async {
        let title = String(title.trimmingCharacters(in: .whitespacesAndNewlines).prefix(80))
        guard !title.isEmpty else { return }
        await work { try await api.renameConversation(id: item.id, title: title); try await loadWorkspace() }
    }
    func togglePin(_ item: Conversation) async {
        await work { try await api.pinConversation(id: item.id, pinned: !item.pinned); try await loadWorkspace() }
    }
    func delete(_ item: Conversation) async {
        guard local.pending(accountID: account?.id ?? "", conversationID: item.id) == nil else {
            error = "该会话还有待核对的发送，请先进入会话刷新"; return
        }
        await work {
            try await api.deleteConversation(id: item.id)
            if selected?.id == item.id { selected = nil; messages = []; live = nil; restoreDraft() }
            try await loadWorkspace()
        }
    }
    func send() async {
        guard canSend, foreground, let account else { return }
        await work {
            let text = draft.text.trimmingCharacters(in: .whitespacesAndNewlines)
            if selected == nil {
                let welcome = draft
                let created = try await api.createConversation(modelID: draft.modelID, mode: draft.reasoningMode)
                selected = created; conversations.insert(created, at: 0)
                // 新会话继承首页草稿；创建成功仍不代表问题已发送。
                try local.setDraft(welcome, accountID: account.id, conversationID: created.id)
                try local.setDraft(Draft(), accountID: account.id, conversationID: "")
                restoreDraft()
            }
            guard let selected else { return }
            guard foreground else { return }
            let marker = PendingSend(conversationID: selected.id, baseline: messages.map(\.id).max() ?? 0, content: text, imageIDs: draft.images.map(\.id))
            // 标记必须先可靠落盘，再允许真正的模型 POST。
            try local.setPending(marker, accountID: account.id, conversationID: selected.id)
            pending = marker; draft.text = ""; draft.images = []; saveDraft()
            accumulator = ReplyAccumulator(); live = accumulator.reply; streaming = true
            let id = UUID(); runID = id
            let search = draft.webSearch
            generation = Task { [weak self] in
                guard let self else { return }
                var failure: Error?
                do {
                    try Task.checkCancellation()
                    try await self.api.stream(id: selected.id, content: text, imageIDs: marker.imageIDs ?? [], webSearch: search) { [weak self] event in
                        guard let self else { throw CancellationError() }
                        try await self.accept(event, conversationID: selected.id, run: id)
                    }
                } catch { failure = error }
                await self.finished(run: id, failure: failure)
            }
        }
    }
    private func accept(_ event: StreamEvent, conversationID: String, run: UUID) throws {
        guard run == runID else { throw CancellationError() }
        try accumulator.accept(event, conversationID: conversationID)
        let now = Date()
        if now.timeIntervalSince(lastRender) >= 0.08 || event.type == "message_saved" {
            live = accumulator.reply; lastRender = now
        }
    }
    private func finished(run: UUID, failure: Error?) async {
        guard run == runID else { return }
        streaming = false; live = accumulator.reply
        if let failure { report(failure) }
        guard account != nil, foreground, run == runID else { return }
        // 独立于取消过的流任务，有限 GET 核对；绝不重放发送。
        generation = Task { [weak self] in
            guard let self else { return }
            await self.reconcile(run: run)
        }
    }
    private func reconcile(run: UUID) async {
        guard !busy else { return }
        busy = true; defer { busy = false }
        for attempt in 0..<4 {
            guard run == runID, account != nil, foreground, !Task.isCancelled else { return }
            if attempt > 0 { try? await Task.sleep(for: .seconds(attempt)) }
            guard run == runID, account != nil, foreground, !Task.isCancelled else { return }
            do {
                try await loadMessages()
                if pending == nil { try await loadWorkspace(); return }
            } catch { report(error); if account == nil { return } }
        }
        if pending != nil { error = "尚未确认回答已保存，请稍后刷新核对。问题不会自动重发" }
    }
    func stop() { generation?.cancel() }
    func sceneActive(_ active: Bool) async {
        foreground = active
        if !active {
            // iOS 不保证普通聊天长连接在后台存活，保留标记并结束接收。
            if streaming { stop() }
        } else if !starting && account != nil && !locked { await refresh() }
    }
    /// 只在用户明确确认已核对后解锁；不触发任何发送请求。
    func restorePendingDraft() {
        guard !locked, let account, let pending else { return }
        do {
            try local.setPending(nil, accountID: account.id, conversationID: pending.conversationID)
            draft.text = pending.content; saveDraft(); self.pending = nil; live = nil
            if !(pending.imageIDs ?? []).isEmpty { error = "问题文字已恢复。请重新选择图片后发送，原图片不会自动重发" }
        } catch { report(error) }
    }
}

extension AppStore {
    func isFavorite(_ message: ChatMessage) -> Bool { favoriteOverrides[message.id] ?? (message.favoriteID != nil) }

    func loadFavorites() async {
        guard let owner = account?.id else { return }
        await work {
            let values = try await api.favorites()
            guard account?.id == owner else { return }
            let known = Set(favorites.map(\.messageID)).union(values.map(\.messageID))
            let active = Set(values.map(\.messageID))
            for id in known { favoriteOverrides[id] = active.contains(id) }
            favorites = values
        }
    }
    func toggleFavorite(_ message: ChatMessage) async {
        guard message.role == "assistant", message.id > 0, !message.content.isEmpty, let owner = account?.id else { return }
        await work {
            if isFavorite(message) {
                try await api.unfavorite(messageID: message.id)
                guard account?.id == owner else { return }
                favoriteOverrides[message.id] = false; favorites.removeAll { $0.messageID == message.id }
            } else {
                let value = try await api.favorite(messageID: message.id)
                guard account?.id == owner else { return }
                favoriteOverrides[message.id] = true
                favorites.removeAll { $0.messageID == message.id }; favorites.insert(value, at: 0)
            }
        }
    }
    func removeFavorite(_ item: FavoriteMessage) async {
        guard let owner = account?.id else { return }
        await work {
            try await api.unfavorite(messageID: item.messageID)
            guard account?.id == owner else { return }
            favoriteOverrides[item.messageID] = false; favorites.removeAll { $0.id == item.id }
        }
    }
    func loadPrompts() async {
        guard let owner = account?.id else { return }
        await work {
            let values = try await api.prompts()
            guard account?.id == owner else { return }
            prompts = values
        }
    }
    @discardableResult func applyPrompt(_ item: PromptTemplate, replace: Bool = false) -> Bool {
        guard account != nil, !locked, pending == nil, replace || draft.text.isEmpty else { return false }
        setText(item.content); return true
    }
    func resetSearch() {
        searchRequest = UUID(); searchResults = []; searchError = nil; searching = false
    }
    func searchLibrary(_ query: String) async {
        guard let owner = account?.id else { return }
        let requestID = UUID(); searchRequest = requestID
        searchResults = []; searchError = nil; error = nil; searching = true
        defer { if searchRequest == requestID { searching = false } }
        do {
            try await Task.sleep(for: .milliseconds(250))
            let values = try await api.search(query: query)
            try Task.checkCancellation()
            guard searchRequest == requestID, account?.id == owner else { return }
            searchResults = values
        } catch {
            guard searchRequest == requestID, account?.id == owner, !Task.isCancelled else { return }
            if error is CancellationError { return }
            if let failure = error as? PlatformError, failure.isUnauthorized { report(failure) }
            else { searchError = "搜索失败，请检查网络后重试" }
        }
    }
    /// 先取得新数据并核验目标，再切换会话，避免失败时丢失当前草稿和阅读位置。
    func openMessage(conversationID: String, messageID: Int64 = 0) async -> Bool {
        guard let owner = account?.id, !conversationID.isEmpty else { return false }
        var opened = false
        await work {
            let list = try await api.conversations()
            guard account?.id == owner else { return }
            guard let item = list.first(where: { $0.id == conversationID }) else {
                error = "原会话已删除或不可访问，收藏内容仍可查看"; return
            }
            let history = try await api.messages(id: item.id)
            guard account?.id == owner else { return }
            guard messageID == 0 || history.contains(where: { $0.id == messageID }) else {
                error = "原消息已删除或不在当前返回的历史中"; return
            }
            generation?.cancel(); runID = UUID()
            conversations = list; selected = item; messages = history; live = nil
            for message in history { favoriteOverrides[message.id] = nil }
            restoreDraft(); try resolvePending()
            focusedMessageID = messageID > 0 ? messageID : nil; focusRequest = UUID(); opened = true
        }
        return opened
    }
    func favoriteSnapshot(resultID: String) async -> FavoriteMessage? {
        await loadFavorites()
        let id = resultID.hasPrefix("favorite:") ? String(resultID.dropFirst(9)) : resultID
        return favorites.first { $0.id == id }
    }
}
