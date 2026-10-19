#if DEBUG
import Foundation
import MeimeiCore

/// 仅 Debug 的 UI 测试注入离线数据；不会生成登录凭证或调用真实模型。
actor DemoAPI: PlatformServing {
    private var loggedIn = false
    private var created = 1
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
        loggedIn ? Self.decode(Account.self, #"{"id":"offline-user","username":"family","display_name":"家人"}"#) : nil
    }
    func login(username: String, password: String, captcha: Captcha, answer: String) async throws -> Account {
        loggedIn = true; return try await currentAccount()!
    }
    func logout() async throws { loggedIn = false }
    nonisolated func clearCredential() throws {}
    func models() async throws -> [ChatModel] {
        Self.decode([ChatModel].self, #"[{"id":"m1","name":"槑槑 · 思考","supports_reasoning_control":true},{"id":"m2","name":"槑槑 · 轻快","supports_reasoning_control":false}]"#)
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
    func messages(id: String) async throws -> [ChatMessage] { history[id] ?? [] }
    func stream(id: String, content: String, webSearch: Bool, onEvent: @escaping @Sendable (StreamEvent) async throws -> Void) async throws {
        nextMessage += 1; history[id, default: []].append(ChatMessage(id: nextMessage, role: "user", content: content))
        var reply = ""
        do {
            for token in ["你好，", "很高兴", "和你一起", "把想法理清。", "\n\n**我们从哪里开始？**"] {
                try await Task.sleep(for: .milliseconds(160)); reply += token
                let data = try JSONSerialization.data(withJSONObject: ["choices": [["delta": ["content": token]]]])
                try await onEvent(StreamEvent(data: String(decoding: data, as: UTF8.self)))
            }
            nextMessage += 1; history[id, default: []].append(ChatMessage(id: nextMessage, role: "assistant", content: reply, status: "completed"))
            try await onEvent(StreamEvent(data: "{\"type\":\"message_saved\",\"conversation_id\":\"\(id)\",\"message_id\":\(nextMessage),\"generation_status\":\"completed\"}"))
        } catch {
            nextMessage += 1; history[id, default: []].append(ChatMessage(id: nextMessage, role: "assistant", content: reply, status: "interrupted"))
            throw error
        }
    }
}
#endif
