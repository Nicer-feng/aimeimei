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
    func testFavoritesUseNumericMessageIDAndIdempotentRemoval() async throws {
        let raw = #"{"id":"f1","message_id":42,"conversation_id":"c1","conversation_title":"测试会话","content":"收藏正文"}"#
        StubProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/favorites"); XCTAssertEqual(request.httpMethod, "POST")
            let value = try self.body(request)
            XCTAssertEqual(value["message_id"] as? Int64, 42); XCTAssertEqual(Set(value.keys), ["message_id"])
            return (201, [:], "{\"favorite\":\(raw)}")
        }
        let item = try await api.favorite(messageID: 42); XCTAssertEqual(item.id, "f1")
        StubProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET"); XCTAssertEqual(request.url?.path, "/api/favorites")
            return (200, [:], "{\"favorites\":[\(raw)]}")
        }
        let values = try await api.favorites(); XCTAssertEqual(values, [item])
        StubProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "DELETE"); XCTAssertEqual(request.url?.path, "/api/favorites/message/42")
            XCTAssertNil(request.httpBody); return (200, [:], #"{"ok":true}"#)
        }
        try await api.unfavorite(messageID: 42)
    }
    func testSearchEncodesQueryWithoutChangingLiteralPlusOrQueryBoundaries() async throws {
        let keyword = "中文 C++ & # ? /"
        StubProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET"); XCTAssertEqual(request.url?.path, "/api/search")
            let components = try XCTUnwrap(URLComponents(url: request.url!, resolvingAgainstBaseURL: false))
            XCTAssertEqual(components.queryItems?.count, 1); XCTAssertEqual(components.queryItems?.first?.value, keyword)
            XCTAssertTrue(components.percentEncodedQuery?.contains("%2B%2B") == true)
            return (200, [:], #"{"results":[{"id":"message:42","type":"message","session_id":"c1","message_id":42,"title":"标题","snippet":"正文"},{"id":"media:1","type":"media","session_id":"","message_id":0,"title":"视频","snippet":"摘要"}]}"#)
        }
        let results = try await api.search(query: keyword)
        XCTAssertEqual(results.count, 1); XCTAssertEqual(results.first?.messageID, 42)
        XCTAssertEqual(results.first?.conversationID, "c1")
    }
    func testPromptsAreReadOnlyAndDeletedFavoritesKeepSnapshot() async throws {
        StubProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET"); XCTAssertEqual(request.url?.path, "/api/prompts")
            return (200, [:], #"{"prompts":[{"id":"p1","title":"计划","content":"帮我制定计划"}]}"#)
        }
        let prompts = try await api.prompts(); XCTAssertEqual(prompts.first?.content, "帮我制定计划")
        let item = try JSONDecoder().decode(FavoriteMessage.self, from: Data(#"{"id":"f1","message_id":42,"conversation_id":"deleted","conversation_title":"原会话已删除","content":"保留内容"}"#.utf8))
        XCTAssertFalse(item.canOpenConversation); XCTAssertEqual(item.content, "保留内容")
        let message = try JSONDecoder().decode(ChatMessage.self, from: Data(#"{"id":42,"role":"assistant","content":"保留内容","favorite_id":"f1"}"#.utf8))
        XCTAssertEqual(message.favoriteID, "f1")
    }
    func testLibraryFailureIsNotAnEmptySuccessOrRetriedWrite() async throws {
        var calls = 0
        StubProtocol.handler = { _ in calls += 1; return (500, ["Content-Type": "text/html"], "<html>upstream unavailable</html>") }
        do { _ = try await api.favorites(); XCTFail("失败不能伪装为空列表") } catch { XCTAssertEqual(error as? PlatformError, .http(500, "")) }
        StubProtocol.handler = { _ in calls += 1; throw URLError(.networkConnectionLost) }
        do { _ = try await api.favorite(messageID: 42); XCTFail("发送失败应明确返回") } catch {}
        XCTAssertEqual(calls, 2)
    }
    func testSMSLoginContractAndSessionCookie() async throws {
        StubProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "GET"); XCTAssertEqual(request.url?.path, "/api/sms-login/config")
            return (200, [:], #"{"sms_auth":{"enabled":true,"configured":true,"country_code":"86","code_length":6}}"#)
        }
        let config = try await api.smsLoginConfig(); XCTAssertTrue(config.available)
        StubProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST"); XCTAssertEqual(request.url?.path, "/api/sms-login/send")
            XCTAssertEqual(try self.body(request) as NSDictionary, ["phone": "13800000000"] as NSDictionary)
            return (200, [:], #"{"challenge_id":"sms-test","expires_at":2000000300,"resend_after":60,"message":"如手机号已绑定，验证码将很快送达。"}"#)
        }
        let challenge = try await api.sendLoginSMS(phone: "13800000000")
        XCTAssertEqual(challenge.id, "sms-test"); XCTAssertEqual(challenge.resendAfter, 60)
        StubProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "POST"); XCTAssertEqual(request.url?.path, "/api/sms-login/verify")
            XCTAssertEqual(try self.body(request) as NSDictionary, ["phone": "13800000000", "code": "123456", "challenge_id": "sms-test"] as NSDictionary)
            return (200, ["Set-Cookie": "ap_session=sms-test-session; Path=/; HttpOnly; Max-Age=3600"], #"{"user":{"id":"u1","username":"family","display_name":"家人"}}"#)
        }
        let account = try await api.loginSMS(phone: "13800000000", code: "123456", challengeID: challenge.id)
        XCTAssertEqual(account.id, "u1"); XCTAssertEqual(try credentials.read()?.token, "sms-test-session")
    }
    func testWrongSMSCodeKeepsExistingCredentialAndReportsUsefulError() async throws {
        try credentials.write(SessionCredential(token: "existing-test-session", expires: Date().addingTimeInterval(3600)))
        StubProtocol.handler = { _ in (401, [:], #"{"error":"验证码无效或已过期"}"#) }
        do { _ = try await api.loginSMS(phone: "13800000000", code: "000000", challengeID: "sms-test"); XCTFail("应拒绝错误验证码") }
        catch {
            XCTAssertEqual(error as? PlatformError, .smsLogin("验证码无效或已过期"))
            XCTAssertFalse((error as? PlatformError)?.isUnauthorized ?? true)
        }
        XCTAssertEqual(try credentials.read()?.token, "existing-test-session")
    }
    func testLostSMSRequestAndRateLimitAreNotRetried() async throws {
        var calls = 0
        StubProtocol.handler = { _ in calls += 1; throw URLError(.networkConnectionLost) }
        do { _ = try await api.sendLoginSMS(phone: "13800000000"); XCTFail("应报告发送失败") } catch {}
        XCTAssertEqual(calls, 1)
        StubProtocol.handler = { _ in calls += 1; return (429, [:], #"{"error":"请稍后再获取验证码"}"#) }
        do { _ = try await api.sendLoginSMS(phone: "13800000000"); XCTFail("应报告限流") }
        catch { XCTAssertEqual(error.localizedDescription, "获取验证码过于频繁，请稍后再试") }
        XCTAssertEqual(calls, 2)
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
