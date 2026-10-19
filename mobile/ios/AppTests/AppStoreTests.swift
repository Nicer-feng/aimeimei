import XCTest
import MeimeiCore
@testable import Meimei

@MainActor
final class AppStoreTests: XCTestCase {
    private var directory: URL!
    private var local: LocalState!
    private var api: DemoAPI!
    private var store: AppStore!
    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        local = try LocalState(directory: directory); api = DemoAPI()
        store = AppStore(api: api, local: local)
    }
    override func tearDownWithError() throws { try FileManager.default.removeItem(at: directory) }
    private func login() async {
        await store.start(); await store.login(username: "family", password: "test-only", answer: "AB23")
        XCTAssertNotNil(store.account)
    }
    private func waitUntilIdle() async throws {
        for _ in 0..<100 {
            if !store.locked && store.pending == nil { return }
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTFail("生成或核对未在限定时间内结束")
    }
    func testNewChatDoesNotCreateConversationAndKeepsWelcomeDraft() async {
        await login(); let count = store.conversations.count
        store.setText("首页未发送的草稿")
        for _ in 0..<4 { store.newChat() }
        XCTAssertEqual(store.conversations.count, count)
        XCTAssertNil(store.selected); XCTAssertEqual(store.draft.text, "首页未发送的草稿")
    }
    func testFirstSendCreatesOnceAndPersistsServerAnswer() async throws {
        await login(); store.setText("仅发送一次")
        await store.send(); await store.send()
        try await waitUntilIdle()
        XCTAssertEqual(store.conversations.count, 2)
        XCTAssertEqual(store.messages.filter { $0.role == "user" }.count, 1)
        XCTAssertEqual(store.messages.last?.status, "completed")
        XCTAssertNil(store.pending); XCTAssertNil(store.live)
        store.newChat(); XCTAssertEqual(store.draft.text, "")
    }
    func testStoppingKeepsInterruptedAnswerAndDoesNotResend() async throws {
        await login(); store.setText("停止测试")
        await store.send(); try await Task.sleep(for: .milliseconds(250)); store.stop()
        try await waitUntilIdle()
        XCTAssertEqual(store.messages.filter { $0.role == "user" }.count, 1)
        XCTAssertEqual(store.messages.last?.status, "interrupted")
        XCTAssertNil(store.pending)
    }
    func testBackgroundAndForegroundOnlyReconcileExistingRequest() async throws {
        await login(); store.setText("后台恢复测试")
        await store.send(); try await Task.sleep(for: .milliseconds(250))
        await store.sceneActive(false)
        try await Task.sleep(for: .milliseconds(250))
        XCTAssertNotNil(store.pending)
        await store.sceneActive(true); try await waitUntilIdle()
        XCTAssertEqual(store.messages.filter { $0.role == "user" }.count, 1)
        XCTAssertEqual(store.messages.last?.status, "interrupted")
    }
    func testRelaunchRestoresOnlyPendingConversationAndResolvesSavedReply() async throws {
        await login()
        let marker = PendingSend(conversationID: "history", baseline: 0, content: "给我一个简单的 Markdown 示例")
        try local.setPending(marker, accountID: "offline-user", conversationID: "history")
        let restored = AppStore(api: api, local: try LocalState(directory: directory))
        await restored.start()
        XCTAssertEqual(restored.selected?.id, "history"); XCTAssertNil(restored.pending)
        XCTAssertEqual(restored.messages.last?.status, "completed")
    }
    func testModelSelectionAndConversationDraftRemainIndependent() async {
        await login(); store.setText("首页草稿")
        await store.configure(modelID: "m2", mode: .fast)
        XCTAssertEqual(store.currentModel?.reasoningControl, false)
        let item = store.conversations[0]
        await store.select(item); store.setText("历史会话草稿")
        store.newChat()
        XCTAssertEqual(store.draft.text, "首页草稿"); XCTAssertEqual(store.draft.modelID, "m2")
        await store.select(item); XCTAssertEqual(store.draft.text, "历史会话草稿")
    }
    func testReloginRestoresPendingWorkAndBackgroundCannotStartSend() async throws {
        await store.start()
        let marker = PendingSend(conversationID: "history", baseline: 0, content: "给我一个简单的 Markdown 示例")
        try local.setPending(marker, accountID: "offline-user", conversationID: "history")
        await store.login(username: "family", password: "test-only", answer: "AB23")
        XCTAssertEqual(store.selected?.id, "history"); XCTAssertNil(store.pending)
        store.newChat(); store.setText("后台不能发起新请求")
        await store.sceneActive(false); await store.send()
        XCTAssertNil(store.selected); XCTAssertNil(store.pending)
        XCTAssertEqual(store.conversations.count, 1)
        XCTAssertEqual(store.draft.text, "后台不能发起新请求")
    }
}
