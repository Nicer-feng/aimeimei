import XCTest
@testable import MeimeiCore

final class CoreTests: XCTestCase {
    func testByteFramingKeepsEmptyLinesAndSplitUTF8AcrossCRLFAndLF() throws {
        var parser = SSEByteParser(); var events: [String] = []
        let raw = ": heartbeat\r\n\r\ndata: 你好😀\r\n\r\ndata: 第二行\n\ndata: 未结束"
        for byte in raw.utf8 { if let event = try parser.byte(byte) { events.append(event) } }
        XCTAssertEqual(events, ["你好😀", "第二行"])
    }
    func testSSECommitsOnlyBlankLineAndKeepsMultilineUnicode() throws {
        var parser = SSEParser()
        XCTAssertNil(try parser.line(": heartbeat"))
        XCTAssertNil(try parser.line("event: message"))
        XCTAssertNil(try parser.line("data: {\"choices\": [{\"delta\":"))
        XCTAssertNil(try parser.line("data: {\"content\":\"你好😀\"}}]}"))
        let payload = try XCTUnwrap(parser.line(""))
        let event = try StreamEvent(data: payload)
        XCTAssertEqual(event.content, "你好😀")
        XCTAssertNil(try parser.line(""))
    }
    func testDoneAndFinishReasonNeverConfirmSave() throws {
        var accumulator = ReplyAccumulator()
        try accumulator.accept(StreamEvent(data: #"{"choices":[{"delta":{"content":"一部分"},"finish_reason":"stop"}]}"#), conversationID: "c1")
        XCTAssertNil(accumulator.reply.savedID)
        XCTAssertEqual(accumulator.reply.content, "一部分")
        XCTAssertEqual(accumulator.reply.status, "interrupted")
    }
    func testOnlyPositiveSavedIDAndMatchingConversationCanConfirm() throws {
        var accumulator = ReplyAccumulator()
        try accumulator.accept(StreamEvent(data: #"{"type":"message_saved","message_id":0,"generation_status":"completed"}"#), conversationID: "c1")
        XCTAssertNil(accumulator.reply.savedID)
        XCTAssertThrowsError(try accumulator.accept(StreamEvent(data: #"{"type":"message_saved","message_id":42,"conversation_id":"other"}"#), conversationID: "c1"))
        try accumulator.accept(StreamEvent(data: #"{"type":"message_saved","message_id":"42","conversation_id":"c1","generation_status":"interrupted"}"#), conversationID: "c1")
        XCTAssertEqual(accumulator.reply.savedID, 42)
        XCTAssertEqual(accumulator.reply.status, "interrupted")
    }
    func testReasoningVariantsAndSearchActivity() throws {
        var accumulator = ReplyAccumulator()
        for field in ["reasoning_content", "reasoning", "thinking"] {
            try accumulator.accept(StreamEvent(data: "{\"choices\":[{\"delta\":{\"\(field)\":\"思考\"}}]}"), conversationID: "c1")
        }
        XCTAssertEqual(accumulator.reply.reasoning, "思考思考思考")
        try accumulator.accept(StreamEvent(data: #"{"type":"search_status","status":"done"}"#), conversationID: "c1")
        XCTAssertEqual(accumulator.reply.activity, "资料已找到，槑槑正在整理…")
        XCTAssertThrowsError(try accumulator.accept(StreamEvent(data: #"{"error":{"message":"unavailable"}}"#), conversationID: "c1"))
    }
    func testRecoveryDoesNotTakeOldOrDifferentQuestionsAnswer() {
        let pending = PendingSend(conversationID: "c1", baseline: 10, content: "本次问题")
        let messages = [ChatMessage(id: 9, role: "user", content: "本次问题"), ChatMessage(id: 10, role: "assistant", content: "旧回答", status: "completed"),
                        ChatMessage(id: 11, role: "user", content: "本次问题"), ChatMessage(id: 12, role: "user", content: "另一个问题"),
                        ChatMessage(id: 13, role: "assistant", content: "其它轮的回答", status: "completed")]
        XCTAssertNil(pending.reply(in: messages))
        let resolved = Array(messages.prefix(3)) + [ChatMessage(id: 14, role: "assistant", content: "本次回答", status: "failed")]
        XCTAssertEqual(pending.reply(in: resolved)?.id, 14)
    }
    func testRepeatedIdenticalQuestionsRemainUnconfirmed() {
        let pending = PendingSend(conversationID: "c1", baseline: 0, content: "重复问题")
        XCTAssertNil(pending.reply(in: [ChatMessage(id: 1, role: "user", content: "重复问题"), ChatMessage(id: 2, role: "assistant", content: "回答"), ChatMessage(id: 3, role: "user", content: "重复问题")]))
    }
    func testDraftsAndPendingSurviveRestartWithoutCrossingAccounts() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let local = try LocalState(directory: directory)
        var draft = Draft(); draft.text = "私有草稿"; draft.modelID = "m1"; draft.webSearch = true
        let marker = PendingSend(conversationID: "same", baseline: 20, content: "待核对问题")
        try local.setDraft(draft, accountID: "account1", conversationID: "same")
        try local.setPending(marker, accountID: "account1", conversationID: "same")
        let restored = try LocalState(directory: directory)
        XCTAssertEqual(restored.draft(accountID: "account1", conversationID: "same"), draft)
        XCTAssertEqual(restored.draft(accountID: "account2", conversationID: "same").text, "")
        XCTAssertNil(restored.pending(accountID: "account2", conversationID: "same"))
        XCTAssertEqual(restored.pendingSends(accountID: "account1"), [marker])
        try restored.setPending(nil, accountID: "account1", conversationID: "same")
        XCTAssertTrue(try LocalState(directory: directory).pendingSends(accountID: "account1").isEmpty)
    }
    func testMarkdownCodePreservesLineBreaksAndWideTableIsSeparateBlock() {
        let parsed = MarkdownBlocks.parse("# 标题\n\n正文 **加粗**\n\n```swift\nlet x = 1\nlet y = 2\n```\n\n| A | B |\n| --- | :---: |\n| 长内容 | 测试 |")
        XCTAssertEqual(parsed, [.heading(1, "标题"), .paragraph("正文 **加粗**"), .code("swift", "let x = 1\nlet y = 2"), .table([["A", "B"], ["长内容", "测试"]])])
    }
}

private final class MemoryCredentials: CredentialStore, @unchecked Sendable {
    private let lock = NSLock()
    private var value: SessionCredential?
    func read() throws -> SessionCredential? { lock.lock(); defer { lock.unlock() }; return value }
    func write(_ value: SessionCredential?) throws { lock.lock(); defer { lock.unlock() }; self.value = value }
}

private final class StubProtocol: URLProtocol, @unchecked Sendable {
    static var handler: ((URLRequest) throws -> (Int, [String: String], String))?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (status, headers, body) = try Self.handler!(request)
            let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1", headerFields: headers)!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: Data(body.utf8)); client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}

final class APITests: XCTestCase {
    private var credentials: MemoryCredentials!
    private var api: PlatformAPI!
    override func setUpWithError() throws {
        credentials = MemoryCredentials()
        let configuration = URLSessionConfiguration.ephemeral; configuration.protocolClasses = [StubProtocol.self]
        api = try PlatformAPI(baseURL: URL(string: "https://test.invalid/")!, credentials: credentials, configuration: configuration)
    }
    override func tearDown() { api = nil; StubProtocol.handler = nil }
    private func body(_ request: URLRequest) throws -> [String: Any] {
        let data: Data
        if let raw = request.httpBody { data = raw }
        else if let stream = request.httpBodyStream {
            stream.open(); defer { stream.close() }; var buffer = [UInt8](repeating: 0, count: 4096); var raw = Data()
            while stream.hasBytesAvailable { let count = stream.read(&buffer, maxLength: buffer.count); if count <= 0 { break }; raw.append(buffer, count: count) }
            data = raw
        } else { data = Data() }
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }
    func testLoginUsesCaptchaAndPersistsCookieWithoutSavingPassword() async throws {
        StubProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/login"); XCTAssertEqual(request.httpMethod, "POST")
            let value = try self.body(request)
            XCTAssertEqual(value["username"] as? String, "family")
            XCTAssertEqual(value["password"] as? String, " test-only ")
            XCTAssertEqual(value["captcha_id"] as? String, "challenge"); XCTAssertEqual(value["captcha"] as? String, "AB23")
            return (200, ["Set-Cookie": "ap_session=test-only-session; Path=/; HttpOnly; Max-Age=3600"], #"{"user":{"id":"u1","username":"family","display_name":"家人"}}"#)
        }
        let captcha = try JSONDecoder().decode(Captcha.self, from: Data(#"{"captcha_id":"challenge","image_svg":"<svg/>"}"#.utf8))
        let account = try await api.login(username: " family ", password: " test-only ", captcha: captcha, answer: " AB23 ")
        XCTAssertEqual(account.id, "u1"); XCTAssertEqual(try credentials.read()?.token, "test-only-session")
        StubProtocol.handler = { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "Cookie"), "ap_session=test-only-session")
            XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
            return (200, [:], #"{"authenticated":false,"user":null}"#)
        }
        let current = try await api.currentAccount()
        XCTAssertNil(current); XCTAssertNil(try credentials.read())
    }
    func testHistoryAcceptsIntegerIDsAndKeepsInterruptedAnswer() async throws {
        StubProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/conversations/c1/messages")
            return (200, [:], #"{"messages":[{"id":123,"role":"assistant","content":"部分回答","reasoning_content":null,"generation_status":"interrupted","documents":[{"filename":"材料.pdf"}]}]}"#)
        }
        let messages = try await api.messages(id: "c1")
        XCTAssertEqual(messages.first?.id, 123); XCTAssertEqual(messages.first?.status, "interrupted")
        XCTAssertEqual(messages.first?.attachments, ["材料.pdf"])
    }
    func testRenameDoesNotOverwriteModelOrReasoning() async throws {
        StubProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "PATCH")
            XCTAssertEqual(Set(try self.body(request).keys), ["title"])
            return (200, [:], #"{"conversation":{"id":"c1","title":"新名称","model_id":"m1","model_name":"模型","reasoning_mode":"deep","pinned":true}}"#)
        }
        try await api.renameConversation(id: "c1", title: "新名称")
    }
    func testUnauthorizedAndUnsafeURLAreExplicitFailures() async throws {
        for value in ["http://test.invalid/", "https://user:password@test.invalid/", "https://test.invalid/api", "https://test.invalid/?token=x"] {
            XCTAssertThrowsError(try PlatformAPI(baseURL: URL(string: value)!, credentials: credentials))
        }
        StubProtocol.handler = { _ in (401, [:], #"{"error":"unauthorized"}"#) }
        do { _ = try await api.conversations(); XCTFail("应拒绝失效登录") }
        catch { XCTAssertEqual(error as? PlatformError, .http(401, "unauthorized")) }
    }
    func testStreamReadsSSEAndSendsExactlyOnePost() async throws {
        var calls = 0
        StubProtocol.handler = { request in
            calls += 1
            XCTAssertEqual(request.httpMethod, "POST")
            let body = try self.body(request)
            XCTAssertEqual(body["content"] as? String, "问题"); XCTAssertEqual(body["web_search"] as? Bool, true)
            XCTAssertEqual(body["use_profile"] as? Bool, true)
            return (200, ["Content-Type": "text/event-stream"], ": heartbeat\r\n\r\ndata: {\"choices\":[{\"delta\":{\"content\":\"你好😀\"}}]}\r\n\r\ndata: {\"type\":\"message_saved\",\"message_id\":44,\"generation_status\":\"completed\"}\n\n")
        }
        actor Events {
            var values: [StreamEvent] = []
            func add(_ value: StreamEvent) { values.append(value) }
        }
        let events = Events()
        try await api.stream(id: "c1", content: "问题", webSearch: true) { await events.add($0) }
        let values = await events.values
        XCTAssertEqual(values.map(\.content).joined(), "你好😀"); XCTAssertEqual(values.last?.savedID, 44)
        XCTAssertEqual(calls, 1)
    }
    func testBrokenPostIsNeverRetried() async throws {
        var calls = 0
        StubProtocol.handler = { _ in calls += 1; throw URLError(.networkConnectionLost) }
        do { try await api.stream(id: "c1", content: "仅发一次", webSearch: false) { _ in }; XCTFail("应报告断流") } catch {}
        XCTAssertEqual(calls, 1)
    }
}
