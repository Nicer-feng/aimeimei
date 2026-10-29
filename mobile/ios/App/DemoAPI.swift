#if DEBUG
import Foundation
import MeimeiCore

/// 仅 Debug 的 UI 测试注入离线数据；不会生成登录凭证或调用真实模型。
actor DemoAPI: PlatformServing {
    private struct WritingRecord {
        var enabled = false; var requirements = WritingRequirements(); var revision = 0
        var versions: [[String: Any]] = []; var current: Int64 = 0; var locked: Int64 = 0
    }
    private var writingRecords: [String: WritingRecord] = [:]
    func writing(conversationID: String, versionID: Int64?) async throws -> WritingResponse {
        let record = writingRecords[conversationID] ?? WritingRecord()
        var state: [String: Any] = ["requirements": try JSONSerialization.jsonObject(with: JSONEncoder().encode(record.requirements)), "revision":record.revision, "current_version_id":record.current, "locked_version_id":record.locked, "versions":record.versions, "notice":""]
        state["current"] = record.versions.first { ($0["id"] as? Int64) == record.current }
        if let versionID { state["selected"] = record.versions.first { ($0["id"] as? Int64) == versionID } }
        return try JSONDecoder().decode(WritingResponse.self, from: JSONSerialization.data(withJSONObject: ["writing":state,"enabled":record.enabled]))
    }
    func updateWriting(conversationID: String, revision: Int, command: WritingCommand) async throws -> WritingResponse {
        var record = writingRecords[conversationID] ?? WritingRecord()
        guard record.revision == revision else { throw PlatformError.http(409, "版本已变化") }
        _ = try command.body(revision: revision)
        switch command {
        case .enabled(let value): record.enabled = value
        case .requirements(let value): record.requirements = value
        case .draft(let text):
            let id = Int64(record.versions.count + 1); record.versions.insert(["id":id,"label":"手动保存","content":text], at: 0); record.current = id; record.locked = 0
        case .version(let id): record.current = id; record.locked = 0
        case .locked(let flag): record.locked = flag ? record.current : 0
        case .reset: record.requirements = WritingRequirements(); record.current = 0; record.locked = 0
        }
        record.revision += 1; writingRecords[conversationID] = record
        return try await writing(conversationID: conversationID, versionID: nil)
    }
    private var analysisTasks: [MediaTask] = []
    private var analysisConversations: [String: String] = [:]
    private static func analysis(_ id: String, status: String) -> MediaTask {
        var value: [String: Any] = ["id":id,"filename":"会议录音.m4a","status":status]
        for key in ["transcript_text","summary_text","outline_text","enhanced_summary","key_points","mindmap_text","copywriting_text","error_message"] { value[key] = "" }
        if status == "completed" { value["transcript_text"] = "会议讨论了项目安排与下一步计划。"; value["summary_text"] = "完成项目计划，并安排下次会议。" }
        return try! JSONDecoder().decode(MediaTask.self, from: JSONSerialization.data(withJSONObject: value))
    }
    func mediaTasks() async throws -> [MediaTask] { analysisTasks }
    func uploadMedia(file: URL, filename: String, progress: @escaping @Sendable (Double) -> Void) async throws -> MediaTask {
        progress(1); let value = Self.analysis(UUID().uuidString, status: "submitted"); analysisTasks.insert(value, at: 0); return value
    }
    func refreshMedia(id: String) async throws -> MediaTask {
        let value = Self.analysis(id, status: "completed"); analysisTasks.removeAll { $0.id == id }; analysisTasks.insert(value, at: 0); return value
    }
    func deleteMedia(id: String) async throws { analysisTasks.removeAll { $0.id == id } }
    func mediaConversation(id: String, modelID: String) async throws -> MediaConversation {
        guard let task = analysisTasks.first(where: { $0.id == id }), task.status == "completed" else { throw PlatformError.media("分析尚未完成") }
        let cid = analysisConversations[id] ?? "media-" + id; analysisConversations[id] = cid
        let item = Self.conversation(cid, "音视频分析：会议录音", modelID)
        if !items.contains(where: { $0.id == cid }) { items.insert(item, at: 0); history[cid] = [ChatMessage(id: 100, role: "assistant", content: "材料已就绪，可以继续提问。", status: "completed")] }
        let raw = #"{"conversation":{"id":"\#(cid)","title":"音视频分析：会议录音","model_id":"\#(modelID)","model_name":"槑槑","reasoning_mode":"balanced","pinned":false},"task":{"id":"\#(id)","filename":"会议录音.m4a","status":"completed","transcript_text":"会议原文","summary_text":"项目计划","outline_text":"","enhanced_summary":"","key_points":"","mindmap_text":"","copywriting_text":"","error_message":""}}"#
        return Self.decode(MediaConversation.self, raw)
    }
    private var handwritingTasks: [OCRTask] = []
    func ocrTasks() async throws -> [OCRTask] { handwritingTasks }
    func recognizeHandwriting(_ jpeg: Data, progress: @escaping @Sendable (Double) -> Void) async throws -> OCRTask {
        progress(1); let value = OCRTask(id: UUID().uuidString, filename: "handwriting.jpg", status: "completed", recognized_text: "今天完成项目计划，明天继续。")
        handwritingTasks.insert(value, at: 0); return value
    }
    func deleteOCRTask(id: String) async throws { handwritingTasks.removeAll { $0.id == id } }
    private var personalProfiles: [AIProfile] = []
    private var personalShares: [ConversationShare] = []
    func profiles() async throws -> [AIProfile] { personalProfiles }
    func saveProfile(_ profile: AIProfile) async throws -> AIProfile {
        guard profile.valid else { throw PlatformError.media("档案格式不正确") }
        var value = profile; if value.id.isEmpty { value.id = UUID().uuidString }
        personalProfiles.removeAll { $0.id == value.id }; personalProfiles.append(value); return value
    }
    func deleteProfile(id: String) async throws { personalProfiles.removeAll { $0.id == id } }
    func shares(conversationID: String) async throws -> [ConversationShare] { personalShares }
    func createShare(conversationID: String, scope: ShareScope, messageID: Int64?, expiresIn: Int) async throws -> ConversationShare {
        let value = ConversationShare(id: UUID().uuidString, scope: scope.rawValue, title: "测试对话", expires_at: Date().timeIntervalSince1970 + Double(expiresIn), active: true, url: "/ai/share/offline-test-token")
        personalShares.insert(value, at: 0); return value
    }
    func revokeShare(id: String) async throws {
        personalShares = personalShares.map { $0.id == id ? ConversationShare(id: $0.id, scope: $0.scope, title: $0.title, expires_at: $0.expires_at, active: false) : $0 }
    }
    private var loggedIn = false
    private var loginName = "family"
    private var dailyReadUsers: Set<String> = []
    private var dailyRegistered = false
    func dailyReports(before: Int64?) async throws -> DailyReportsPage {
        guard ["feng", "czq"].contains(loginName) else { throw PlatformError.http(404, "") }
        let dailyRead = dailyReadUsers.contains(loginName)
        let report: [String: Any] = ["id": loginName == "czq" ? 2 : 1, "report_date": "2026-10-29", "title": "研发日报",
            "content": "## 今日研发更新\n\n- 桌面客户端：音频转换器更新至 1.7.1。\n- 后台前端：新增代理发码审核。\n- Flutter：今日未见新提交。\n- 后端：优化账号与会员接口。\n- 官网：更新产品展示。",
            "created_at": 1792980000, "read_at": dailyRead ? 1 : 0, "simulation": true]
        return try JSONDecoder().decode(DailyReportsPage.self, from: JSONSerialization.data(withJSONObject:
            ["reports": [report], "unread": dailyRead ? 0 : 1, "next_before": NSNull()]))
    }
    func dailyReport(id: Int64) async throws -> DailyReport {
        let report = try await dailyReports(before: nil).reports[0]
        guard report.id == id else { throw PlatformError.http(404, "") }
        return report
    }
    func readDailyReport(id: Int64) async throws {
        _ = try await dailyReport(id: id); dailyReadUsers.insert(loginName)
    }
    func registerDailyDevice(installationID: String, token: String) async throws { dailyRegistered = true }
    func removeDailyDevice(installationID: String) async throws { dailyRegistered = false }
    private var created = 1
    private var smsSends = 0
    private var smsVerifications = 0
    private var smsAvailable = true
    private var savedFavorites: [FavoriteMessage] = []
    private var searchDelays: [String: Duration] = [:]
    func setSearchDelay(_ delay: Duration, query: String) { searchDelays[query] = delay }
    func seedArchivedFavorite() {
        savedFavorites.append(Self.decode(FavoriteMessage.self, #"{"id":"archived","message_id":999,"conversation_id":"deleted","conversation_title":"原会话已删除","content":"删除会话后仍保留的收藏快照"}"#))
    }
    func setSMSAvailable(_ available: Bool) { smsAvailable = available }
    func smsCounts() -> (sends: Int, verifications: Int) { (smsSends, smsVerifications) }
    private var nextMessage: Int64 = 10
    private var items = [DemoAPI.conversation("history", "一次小小的好奇")]
    private var history: [String: [ChatMessage]] = ["history": [
        ChatMessage(id: 1, role: "user", content: "给我一个简单的 Markdown 示例"),
        ChatMessage(id: 2, role: "assistant", content: "## 把想法慢慢理清\n\n**先从一件小事开始。**\n\n- 写下你的问题\n- 找到下一步\n\n```swift\nlet greeting = \"你好，槑槑\"\n```\n\n| 今天 | 明天 |\n| --- | --- |\n| 开始 | 继续 |", status: "completed")
    ]]
    private static func decode<T: Decodable>(_ type: T.Type, _ raw: String) -> T {
        try! JSONDecoder().decode(type, from: Data(raw.utf8))
    }
    private static func conversation(_ id: String, _ title: String, _ model: String = "m1", _ mode: ReasoningMode = .balanced, _ pinned: Bool = false) -> Conversation {
        let data = try! JSONSerialization.data(withJSONObject: ["id": id, "title": title, "model_id": model, "model_name": model == "m1" ? "槑槑 · 思考" : "槑槑 · 轻快", "reasoning_mode": mode.rawValue, "pinned": pinned])
        return try! JSONDecoder().decode(Conversation.self, from: data)
    }
    func captcha() async throws -> Captcha {
        Self.decode(Captcha.self, #"{"captcha_id":"offline","image_svg":"<svg><rect width='128' height='48' rx='14' fill='#fffaf6'/><text x='16' y='34' fill='#6F594B' font-size='24'>AB23</text></svg>"}"#)
    }
    func currentAccount() async throws -> Account? {
        loggedIn ? Self.decode(Account.self, #"{"id":"\#(loginName == "czq" ? "offline-czq" : "offline-user")","username":"\#(loginName)","display_name":"家人"}"#) : nil
    }
    func login(username: String, password: String, captcha: Captcha, answer: String) async throws -> Account {
        loginName = ["feng", "czq"].contains(username) ? username : "family"
        loggedIn = true; return try await currentAccount()!
    }
    func smsLoginConfig() async throws -> SMSLoginConfiguration {
        Self.decode(SMSLoginConfiguration.self, "{\"enabled\":\(smsAvailable),\"configured\":\(smsAvailable),\"country_code\":\"86\",\"code_length\":6}")
    }
    func sendLoginSMS(phone: String) async throws -> SMSLoginChallenge {
        smsSends += 1
        try await Task.sleep(for: .milliseconds(150))
        let body: [String: Any] = ["challenge_id": "offline-sms", "expires_at": Date().addingTimeInterval(300).timeIntervalSince1970,
                                  "resend_after": 60, "message": "离线测试，不发送真实短信"]
        return try JSONDecoder().decode(SMSLoginChallenge.self, from: JSONSerialization.data(withJSONObject: body))
    }
    func loginSMS(phone: String, code: String, challengeID: String) async throws -> Account {
        smsVerifications += 1
        guard code == "123456", challengeID == "offline-sms" else { throw PlatformError.smsLogin("验证码不正确或已过期") }
        loggedIn = true; return try await currentAccount()!
    }
    func logout() async throws { loggedIn = false; loginName = "family" }
    nonisolated func clearCredential() throws {}
    func models() async throws -> [ChatModel] {
        Self.decode([ChatModel].self, #"[{"id":"m1","name":"槑槑 · 思考","supports_reasoning_control":true,"supports_vision":true},{"id":"m2","name":"槑槑 · 轻快","supports_reasoning_control":false}]"#)
    }
    func conversations() async throws -> [Conversation] { items }
    func createConversation(modelID: String, mode: ReasoningMode) async throws -> Conversation {
        created += 1
        let value = Self.conversation("created-\(created)", "新对话", modelID, mode)
        items.insert(value, at: 0); return value
    }
    func configureConversation(id: String, modelID: String, mode: ReasoningMode) async throws -> Conversation {
        let value = Self.conversation(id, items.first { $0.id == id }?.title ?? "新对话", modelID, mode)
        if let index = items.firstIndex(where: { $0.id == id }) { items[index] = value }; return value
    }
    func renameConversation(id: String, title: String) async throws {
        if let index = items.firstIndex(where: { $0.id == id }) {
            let old = items[index]; items[index] = Self.conversation(id, title, old.modelID, old.reasoningMode, old.pinned)
        }
    }
    func pinConversation(id: String, pinned: Bool) async throws {
        if let index = items.firstIndex(where: { $0.id == id }) {
            let old = items[index]; items[index] = Self.conversation(id, old.title, old.modelID, old.reasoningMode, pinned)
        }
    }
    func deleteConversation(id: String) async throws { items.removeAll { $0.id == id } }
    func messages(id: String) async throws -> [ChatMessage] {
        (history[id] ?? []).map { message in
            ChatMessage(id: message.id, role: message.role, content: message.content, reasoning: message.reasoning,
                        status: message.status, attachments: message.attachments,
                        favoriteID: savedFavorites.first { $0.messageID == message.id }?.id, images: message.images, sources: message.sources, documents: message.documents, writingCheck: message.writingCheck)
        }
    }
    func favorites() async throws -> [FavoriteMessage] { savedFavorites }
    func favorite(messageID: Int64) async throws -> FavoriteMessage {
        if let existing = savedFavorites.first(where: { $0.messageID == messageID }) { return existing }
        guard let source = history.first(where: { $0.value.contains { $0.id == messageID && $0.role == "assistant" } }),
              let message = source.value.first(where: { $0.id == messageID }) else { throw PlatformError.http(404, "message not found") }
        let body: [String: Any] = ["id": "f\(messageID)", "message_id": messageID, "conversation_id": source.key,
                                  "conversation_title": items.first { $0.id == source.key }?.title ?? "原会话已删除", "content": message.content]
        let item = try JSONDecoder().decode(FavoriteMessage.self, from: JSONSerialization.data(withJSONObject: body))
        savedFavorites.insert(item, at: 0); return item
    }
    func unfavorite(messageID: Int64) async throws { savedFavorites.removeAll { $0.messageID == messageID } }
    func prompts() async throws -> [PromptTemplate] {
        Self.decode([PromptTemplate].self, #"[{"id":"daily","title":"每日计划","content":"请帮我制定今天的计划，列出优先级和下一步。"}]"#)
    }
    func search(query: String) async throws -> [GlobalSearchResult] {
        if let delay = searchDelays[query] { try? await Task.sleep(for: delay) }
        var rows: [[String: Any]] = []
        for item in items {
            if query.isEmpty || item.title.localizedCaseInsensitiveContains(query) {
                rows.append(["id": "conversation:\(item.id)", "type": "conversation", "session_id": item.id,
                             "message_id": 0, "title": item.title, "snippet": "最近对话"])
            }
            if !query.isEmpty {
                for message in history[item.id] ?? [] where message.content.localizedCaseInsensitiveContains(query) {
                    rows.append(["id": "message:\(message.id)", "type": "message", "session_id": item.id,
                                 "message_id": message.id, "title": item.title, "snippet": message.content])
                }
            }
        }
        for item in savedFavorites where !query.isEmpty && item.content.localizedCaseInsensitiveContains(query) {
            rows.append(["id": "favorite:\(item.id)", "type": "favorite", "session_id": item.canOpenConversation ? item.conversationID : "",
                         "message_id": item.canOpenConversation ? item.messageID : 0, "title": item.conversationTitle, "snippet": item.content])
        }
        return try JSONDecoder().decode([GlobalSearchResult].self, from: JSONSerialization.data(withJSONObject: rows))
    }
    private var uploaded: [String: Data] = [:]
    private var uploadFails = false
    func setUploadFails(_ value: Bool) { uploadFails = value }
    func uploadImage(_ data: Data, progress: @escaping @Sendable (Double) -> Void) async throws -> ChatImage {
        progress(0.25); try await Task.sleep(for: .milliseconds(120))
        if uploadFails { throw URLError(.networkConnectionLost) }
        let id = UUID().uuidString; uploaded[id] = data; progress(1)
        return ChatImage(id: id, filename: "photo.jpg")
    }
    func imageData(id: String) async throws -> Data {
        guard let data = uploaded[id] else { throw PlatformError.http(404, "image not found") }; return data
    }
    private var files: [ChatDocument] = []
    private var documentFailure = false
    private var documentRefreshFailure = false
    private var documentRequests = 0
    private var speechPrepares = 0
    private var speechDownloads = 0
    private var speechLong = false
    private var speechDelay: Duration = .zero
    private var speechEnabled = true
    func setDocumentFailure(_ value: Bool) { documentFailure = value }
    func setDocumentRefreshFailure(_ value: Bool) { documentRefreshFailure = value }
    func setSpeechLong(_ value: Bool) { speechLong = value }
    func setSpeechEnabled(_ value: Bool) { speechEnabled = value }
    func setSpeechDelay(_ value: Duration) { speechDelay = value }
    func speechCounts() -> (prepare: Int, audio: Int) { (speechPrepares, speechDownloads) }
    func documentCount() -> Int { documentRequests }
    func documents() async throws -> [ChatDocument] { files }
    func uploadDocument(_ data: Data, filename: String, progress: @escaping @Sendable (Double) -> Void) async throws -> ChatDocument {
        documentRequests += 1; progress(0.3); try await Task.sleep(for: .milliseconds(100))
        if documentFailure { throw URLError(.networkConnectionLost) }
        let item = ChatDocument(id: UUID().uuidString, filename: filename, status: "processing")
        files.insert(item, at: 0); progress(1); return item
    }
    func refreshDocument(id: String) async throws -> ChatDocument {
        if documentRefreshFailure { throw URLError(.networkConnectionLost) }
        guard let i = files.firstIndex(where: { $0.id == id }) else { throw PlatformError.http(404, "document not found") }
        let item = ChatDocument(id: id, filename: files[i].filename, status: "completed"); files[i] = item; return item
    }
    func speechConfiguration() async throws -> SpeechConfiguration {
        Self.decode(SpeechConfiguration.self, "{\"enabled\":\(speechEnabled),\"configured\":true,\"voices\":[{\"id\":\"gentle\",\"name\":\"温柔女声\"},{\"id\":\"clear\",\"name\":\"清晰男声\"}],\"default_voice\":\"gentle\",\"default_speed\":1}")
    }
    func prepareSpeech(messageID: Int64, voice: String, speed: Double) async throws -> PreparedSpeech {
        speechPrepares += 1
        return Self.decode(PreparedSpeech.self, "{\"cached\":false,\"long_text\":\(speechLong)}")
    }
    func speechAudio(messageID: Int64, voice: String, speed: Double) async throws -> Data {
        speechDownloads += 1
        if speechDelay > .zero { try? await Task.sleep(for: speechDelay) }
        var data = Data()
        func text(_ value: String) { data.append(Data(value.utf8)) }
        func number<T: FixedWidthInteger>(_ value: T) { var v = value.littleEndian; withUnsafeBytes(of: &v) { data.append(contentsOf: $0) } }
        let length: UInt32 = 24000 * 2 * 30
        text("RIFF"); number(length + 36); text("WAVEfmt "); number(UInt32(16)); number(UInt16(1)); number(UInt16(1))
        number(UInt32(24000)); number(UInt32(48000)); number(UInt16(2)); number(UInt16(16)); text("data"); number(length)
        data.append(Data(count: Int(length))); return data
    }
    func stream(id: String, content: String, imageIDs: [String], documentIDs: [String], webSearch: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws {
        nextMessage += 1; history[id, default: []].append(ChatMessage(id: nextMessage, role: "user", content: content, images: imageIDs.map { ChatImage(id: $0, filename: "photo.jpg") }, documents: documentIDs.compactMap { id in files.first { $0.id == id } }))
        var reply = ""
        do {
            for token in ["你好，", "很高兴", "和你一起", "把想法理清。", "\n\n**我们从哪里开始？**"] {
                try await Task.sleep(for: .milliseconds(160)); reply += token
                let data = try JSONSerialization.data(withJSONObject: ["choices": [["delta": ["content": token]]]])
                try await onEvent(StreamEvent(data: String(decoding: data, as: UTF8.self)))
            }
            nextMessage += 1; history[id, default: []].append(ChatMessage(id: nextMessage, role: "assistant", content: reply, status: "completed", sources: webSearch ? Self.decode([ChatSource].self, #"[{"title":"Swift 官方文档","url":"https://www.swift.org/documentation/","snippet":"Swift 编程语言的学习与参考资料。","position":1}]"#) : []))
            try await onEvent(StreamEvent(data: "{\"type\":\"message_saved\",\"conversation_id\":\"\(id)\",\"message_id\":\(nextMessage),\"generation_status\":\"completed\"}"))
        } catch {
            nextMessage += 1; history[id, default: []].append(ChatMessage(id: nextMessage, role: "assistant", content: reply, status: "interrupted"))
            throw error
        }
    }
}

/// 离线 UI 测试只验证播放状态与交互，不依赖云构建机的音频硬件。
@MainActor final class DemoAudioOutput: AudioOutput {
    var onFinish: ((Bool) -> Void)?
    var onPause: (() -> Void)?
    func play(_ data: Data) throws { guard !data.isEmpty else { throw PlatformError.invalidResponse } }
    func pause() {}
    func resume() throws {}
    func stop() {}
}
#endif
