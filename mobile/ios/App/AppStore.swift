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
    private(set) var draft = Draft()
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
        !locked && pending == nil && !draft.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && currentModel != nil
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
        selected = nil; messages = []; live = nil; restoreDraft(); error = nil
    }
    func select(_ item: Conversation) async {
        await work {
            generation?.cancel(); runID = UUID()
            let history = try await api.messages(id: item.id)
            selected = item; messages = history; live = nil; restoreDraft()
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
            let marker = PendingSend(conversationID: selected.id, baseline: messages.map(\.id).max() ?? 0, content: text)
            // 标记必须先可靠落盘，再允许真正的模型 POST。
            try local.setPending(marker, accountID: account.id, conversationID: selected.id)
            pending = marker; draft.text = ""; saveDraft()
            accumulator = ReplyAccumulator(); live = accumulator.reply; streaming = true
            let id = UUID(); runID = id
            let search = draft.webSearch
            generation = Task { [weak self] in
                guard let self else { return }
                var failure: Error?
                do {
                    try Task.checkCancellation()
                    try await self.api.stream(id: selected.id, content: text, webSearch: search) { [weak self] event in
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
        } catch { report(error) }
    }
}
