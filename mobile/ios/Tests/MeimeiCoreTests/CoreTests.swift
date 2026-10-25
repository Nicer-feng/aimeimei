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
            XCTAssertEqual(body["image_ids"] as? [String], ["pic1"])
            XCTAssertEqual(body["document_ids"] as? [String], ["doc1"])
            return (200, ["Content-Type": "text/event-stream"], ": heartbeat\r\n\r\ndata: {\"choices\":[{\"delta\":{\"content\":\"你好😀\"}}]}\r\n\r\ndata: {\"type\":\"message_saved\",\"message_id\":44,\"generation_status\":\"completed\"}\n\n")
        }
        actor Events {
            var values: [StreamEvent] = []
            func add(_ value: StreamEvent) { values.append(value) }
        }
        let events = Events()
        try await api.stream(id: "c1", content: "问题", imageIDs: ["pic1"], documentIDs: ["doc1"], webSearch: true) { await events.add($0) }
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

extension CoreTests {
    func testImageAndSourcesDecodeAndUnsafeSourceLinksStayClosed() throws {
        let message = try JSONDecoder().decode(ChatMessage.self, from: Data(#"{"id":1,"role":"user","content":"","images":[{"id":"p1","filename":"相片.jpg","view_url":"/api/chat-images/p1/view"}],"sources":[{"title":"资料","url":"https://example.org/a","snippet":"摘要","position":1},{"url":"javascript:alert(1)"},{"url":"https://name:password@example.org"}],"documents":[{"filename":"材料.pdf"}]}"#.utf8))
        XCTAssertEqual(message.images.map(\.id), ["p1"]); XCTAssertEqual(message.attachments, ["材料.pdf"])
        XCTAssertEqual(message.sources.first?.safeURL?.host, "example.org")
        XCTAssertNil(message.sources[1].safeURL); XCTAssertNil(message.sources[2].safeURL)
    }
    func testPendingImageOnlySendMatchesImageIDsAndNeverAnotherImage() {
        let pending = PendingSend(conversationID: "c1", baseline: 1, content: "", imageIDs: ["p1"])
        let correct = ChatMessage(id: 2, role: "user", content: "", images: [ChatImage(id: "p1", filename: "x.jpg")])
        let wrong = ChatMessage(id: 2, role: "user", content: "", images: [ChatImage(id: "p2", filename: "x.jpg")])
        let answer = ChatMessage(id: 3, role: "assistant", content: "识图回答", status: "completed")
        XCTAssertEqual(pending.reply(in: [correct, answer])?.id, 3)
        XCTAssertNil(pending.reply(in: [wrong, answer]))
    }
    func testOldDraftStillDecodesAndImageDraftPersistsPerAccount() throws {
        let old = try JSONDecoder().decode(Draft.self, from: Data(#"{"text":"旧草稿","modelID":"m1","webSearch":false,"reasoningMode":"fast"}"#.utf8))
        XCTAssertTrue(old.images.isEmpty)
        var draft = old; draft.images = [ChatImage(id: "p1", filename: "图片.jpg")]
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: directory) }
        let local = try LocalState(directory: directory); try local.setDraft(draft, accountID: "a", conversationID: "c")
        let restored = try LocalState(directory: directory)
        XCTAssertEqual(restored.draft(accountID: "a", conversationID: "c").images, draft.images)
        XCTAssertTrue(restored.draft(accountID: "b", conversationID: "c").images.isEmpty)
    }
    func testMultipartPolicyAndSizeAndExpiry() throws {
        let raw: [String: Any] = ["host":"https://oss.example.org", "access_key_id":"test", "policy":"test-policy", "signature":"test-signature", "key_prefix":"images/u/", "max_size":3,"expires_at":Date().addingTimeInterval(60).timeIntervalSince1970]
        let policy = try JSONDecoder().decode(ImageUploadPolicy.self, from: JSONSerialization.data(withJSONObject: raw))
        let body = try policy.form(image: Data([1,2,3]), key: "images/u/test.jpg", boundary: "test-boundary")
        let text = String(decoding: body, as: UTF8.self)
        XCTAssertTrue(text.contains("name=\"Content-Type\"\r\n\r\nimage/jpeg"))
        XCTAssertTrue(text.contains("name=\"success_action_status\"\r\n\r\n204"))
        XCTAssertThrowsError(try policy.form(image: Data([1,2,3,4]), key: "images/u/test.jpg", boundary: "b"))
        XCTAssertThrowsError(try policy.form(image: Data([1]), key: "another-user/test.jpg", boundary: "b"))
        var expired = raw; expired["expires_at"] = 0
        let stale = try JSONDecoder().decode(ImageUploadPolicy.self, from: JSONSerialization.data(withJSONObject: expired))
        XCTAssertThrowsError(try stale.form(image: Data([1]), key: "images/u/test.jpg", boundary: "b"))
    }
}

extension APITests {
    func testUploadUsesPolicyThenCookielessOSSAndOnlyThenRegisters() async throws {
        try credentials.write(SessionCredential(token: "test-cookie", expires: Date().addingTimeInterval(600)))
        var steps: [String] = []
        StubProtocol.handler = { request in
            steps.append(request.url?.host == "oss.example.org" ? "oss" : request.url!.path)
            if request.url?.host == "oss.example.org" {
                XCTAssertNil(request.value(forHTTPHeaderField: "Cookie")); XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
                XCTAssertEqual(request.httpMethod, "POST"); XCTAssertTrue(request.value(forHTTPHeaderField: "Content-Type")!.hasPrefix("multipart/form-data"))
                return (204, [:], "")
            }
            XCTAssertEqual(request.value(forHTTPHeaderField: "Cookie"), "ap_session=test-cookie")
            if request.url?.path.hasSuffix("upload-policy") == true {
                XCTAssertEqual(request.httpMethod, "POST")
                let raw: [String: Any] = ["policy":["host":"https://oss.example.org", "access_key_id":"test", "policy":"p", "signature":"s", "key_prefix":"images/u/", "max_size":1024,"expires_at":Date().addingTimeInterval(60).timeIntervalSince1970]]
                return (200, [:], String(decoding: try JSONSerialization.data(withJSONObject: raw), as: UTF8.self))
            }
            let payload = try self.body(request)
            XCTAssertEqual(payload["mime_type"] as? String, "image/jpeg"); XCTAssertEqual(payload["file_size"] as? Int, 3)
            XCTAssertTrue((payload["oss_key"] as? String)?.hasPrefix("images/u/") == true)
            return (201, [:], #"{"image":{"id":"uploaded","filename":"photo.jpg"}}"#)
        }
        let image = try await api.uploadImage(Data([1,2,3])) { _ in }
        XCTAssertEqual(image.id, "uploaded"); XCTAssertEqual(steps, ["/api/chat-images/upload-policy", "oss", "/api/chat-images"])
    }
    func testImagePreviewFetchKeepsPlatformCookieOutOfSignedURL() async throws {
        try credentials.write(SessionCredential(token: "test-cookie", expires: Date().addingTimeInterval(600)))
        StubProtocol.handler = { request in
            if request.url?.host == "test.invalid" {
                XCTAssertEqual(request.url?.path, "/api/chat-images/p1/view")
                XCTAssertEqual(request.value(forHTTPHeaderField: "Cookie"), "ap_session=test-cookie")
                return (302, ["Location":"https://oss.example.org/photo?signature=test"], "")
            }
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie"))
            return (200, ["Content-Type":"image/jpeg"], "test-image")
        }
        let data = try await api.imageData(id: "p1"); XCTAssertEqual(String(decoding: data, as: UTF8.self), "test-image")
    }
    func testImagePreviewRejectsInsecureRedirectBeforeExternalRequest() async throws {
        var calls = 0
        StubProtocol.handler = { _ in calls += 1; return (302, ["Location":"http://oss.example.org/photo"], "") }
        do { _ = try await api.imageData(id: "p1"); XCTFail("不应访问不安全地址") } catch {}
        XCTAssertEqual(calls, 1)
    }
}

extension CoreTests {
    func testDocumentStatusLimitsAndOldDraftCompatibility() throws {
        let old = try JSONDecoder().decode(Draft.self, from: Data(#"{"text":"旧草稿"}"#.utf8))
        XCTAssertTrue(old.documents.isEmpty)
        XCTAssertNoThrow(try DocumentLimits.validate(filename: "项目说明.docx", size: 1024))
        XCTAssertThrowsError(try DocumentLimits.validate(filename: "app.exe", size: 100))
        XCTAssertThrowsError(try DocumentLimits.validate(filename: "材料.pdf", size: DocumentLimits.maxBytes + 1))
        XCTAssertThrowsError(try DocumentLimits.validate(filename: "图片.png", size: 21 * 1024 * 1024))
        XCTAssertThrowsError(try DocumentLimits.validate(filename: "空文件.txt", size: 0))
        let document = try JSONDecoder().decode(ChatDocument.self, from: Data(#"{"id":"d1","filename":"项目说明.pdf","status":"processing","error_message":"稍后刷新"}"#.utf8))
        XCTAssertTrue(document.processing); XCTAssertFalse(document.ready); XCTAssertEqual(document.errorMessage, "稍后刷新")
    }
    func testDocumentOnlyPendingMatchesExactMaterialAndSurvivesEncoding() throws {
        let marker = PendingSend(conversationID: "c", baseline: 1, content: "", documentIDs: ["d1"])
        let restored = try JSONDecoder().decode(PendingSend.self, from: JSONEncoder().encode(marker))
        let question = ChatMessage(id: 2, role: "user", content: "", documents: [ChatDocument(id: "d1", filename: "材料.txt", status: "completed")])
        XCTAssertEqual(question.attachments, ["材料.txt"])
        let answer = ChatMessage(id: 3, role: "assistant", content: "摘要", status: "completed")
        XCTAssertEqual(restored.reply(in: [question, answer])?.id, 3)
        XCTAssertNil(PendingSend(conversationID: "c", baseline: 1, content: "", documentIDs: ["d2"]).reply(in: [question, answer]))
        let old = try JSONDecoder().decode(PendingSend.self, from: Data(#"{"conversationID":"c","baseline":1,"content":"旧问题"}"#.utf8))
        XCTAssertNil(old.documentIDs)
    }
}

extension APITests {
    func testDocumentUploadUsesCookielessOSSAndRegistersOriginalFilename() async throws {
        try credentials.write(SessionCredential(token: "test-cookie", expires: Date().addingTimeInterval(600)))
        var steps: [String] = []
        StubProtocol.handler = { request in
            steps.append(request.url?.host == "oss.example.org" ? "oss" : request.url!.path)
            if request.url?.host == "oss.example.org" {
                XCTAssertNil(request.value(forHTTPHeaderField: "Cookie")); return (204, [:], "")
            }
            XCTAssertEqual(request.value(forHTTPHeaderField: "Cookie"), "ap_session=test-cookie")
            if request.url?.path.hasSuffix("upload-policy") == true {
                let policy: [String: Any] = ["policy":["host":"https://oss.example.org", "access_key_id":"test", "policy":"p", "signature":"s", "key_prefix":"documents/u/", "max_size":1024,"expires_at":Date().addingTimeInterval(60).timeIntervalSince1970]]
                return (200, [:], String(decoding: try JSONSerialization.data(withJSONObject: policy), as: UTF8.self))
            }
            let payload = try self.body(request)
            XCTAssertEqual(payload["filename"] as? String, "中文材料.pdf")
            XCTAssertTrue((payload["oss_key"] as? String)?.hasSuffix(".pdf") == true)
            XCTAssertEqual(payload["file_size"] as? Int, 3)
            return (201, [:], #"{"document":{"id":"d1","filename":"中文材料.pdf","status":"submitted"}}"#)
        }
        let item = try await api.uploadDocument(Data([1,2,3]), filename: "中文材料.pdf") { _ in }
        XCTAssertEqual(item.id, "d1"); XCTAssertFalse(item.ready)
        XCTAssertEqual(steps, ["/api/documents/upload-policy", "oss", "/api/documents"])
    }
    func testDocumentsListAndExplicitRefreshPreserveTransientState() async throws {
        StubProtocol.handler = { request in
            if request.url?.path == "/api/documents" {
                XCTAssertEqual(request.httpMethod, "GET")
                return (200, [:], #"{"documents":[{"id":"d1","filename":"材料.txt","status":"processing"}]}"#)
            }
            XCTAssertEqual(request.url?.path, "/api/documents/d1/refresh"); XCTAssertEqual(request.httpMethod, "POST")
            return (200, [:], #"{"document":{"id":"d1","filename":"材料.txt","status":"processing","error_message":"暂时无法获取"}}"#)
        }
        let rows = try await api.documents(); XCTAssertEqual(rows.count, 1)
        let item = try await api.refreshDocument(id: "d1"); XCTAssertTrue(item.processing); XCTAssertFalse(item.errorMessage.isEmpty)
    }
    func testInvalidDocumentFailsBeforeAnyUploadAndExpiredFormRejected() async throws {
        var calls = 0; StubProtocol.handler = { _ in calls += 1; return (500, [:], "") }
        do { _ = try await api.uploadDocument(Data([1]), filename: "app.exe") { _ in }; XCTFail("不应上传") } catch {}
        XCTAssertEqual(calls, 0)
        let raw: [String: Any] = ["host":"https://oss.example.org", "access_key_id":"test", "policy":"p", "signature":"s", "key_prefix":"documents/u/", "max_size":100,"expires_at":0]
        let policy = try JSONDecoder().decode(ImageUploadPolicy.self, from: JSONSerialization.data(withJSONObject: raw))
        XCTAssertThrowsError(try policy.documentForm(data: Data([1]), key: "documents/u/a.txt", boundary: "b"))
    }
    func testSpeechPreparationAndStreamAudioUsePlatformAuthAndFrozenParameters() async throws {
        try credentials.write(SessionCredential(token: "test-cookie", expires: Date().addingTimeInterval(600)))
        var downloads = 0
        StubProtocol.handler = { request in
            XCTAssertEqual(request.value(forHTTPHeaderField: "Cookie"), "ap_session=test-cookie")
            if request.httpMethod == "POST" {
                XCTAssertEqual(request.url?.path, "/api/messages/42/tts")
                let payload = try self.body(request); XCTAssertEqual(payload["voice"] as? String, "voice+test"); XCTAssertEqual(payload["speed"] as? Double, 1.25)
                return (200, [:], #"{"cached":false,"long_text":true,"audio_url":"https://untrusted.invalid/audio"}"#)
            }
            downloads += 1
            XCTAssertEqual(request.url?.path, "/api/messages/42/tts/audio")
            let items = URLComponents(url: request.url!, resolvingAgainstBaseURL: false)!.queryItems!
            XCTAssertEqual(items.first { $0.name == "voice" }?.value, "voice+test")
            return (200, ["Content-Type":"audio/mpeg"], "audio-bytes")
        }
        let prepared = try await api.prepareSpeech(messageID: 42, voice: "voice+test", speed: 1.25)
        XCTAssertTrue(prepared.longText); XCTAssertEqual(downloads, 0)
        let bytes = try await api.speechAudio(messageID: 42, voice: "voice+test", speed: 1.25)
        XCTAssertEqual(String(decoding: bytes, as: UTF8.self), "audio-bytes"); XCTAssertEqual(downloads, 1)
    }
    func testCachedSpeechRedirectNeverForwardsCookieAndRejectsNonAudio() async throws {
        try credentials.write(SessionCredential(token: "test-cookie", expires: Date().addingTimeInterval(600)))
        StubProtocol.handler = { request in
            if request.url?.host == "test.invalid" { return (302, ["Location":"https://oss.example.org/cached.mp3?signature=test"], "") }
            XCTAssertNil(request.value(forHTTPHeaderField: "Cookie")); return (200, ["Content-Type":"audio/mpeg"], "cached-audio")
        }
        let bytes = try await api.speechAudio(messageID: 42, voice: "test", speed: 1)
        XCTAssertEqual(String(decoding: bytes, as: UTF8.self), "cached-audio")
        StubProtocol.handler = { _ in (200, ["Content-Type":"text/html"], "not audio") }
        do { _ = try await api.speechAudio(messageID: 42, voice: "test", speed: 1); XCTFail("不应接受 HTML") } catch {}
    }
}


extension APITests {
    func testProfileCRUDPreservesDisabledAndNumericOrder() async throws {
        let profile = AIProfile(title: "表达风格", content: "简洁中文", type: "style", sort_order: 20, enabled: false)
        let raw = #"{"id":"p1","title":"表达风格","content":"简洁中文","type":"style","sort_order":20,"enabled":false}"#
        StubProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/profiles"); XCTAssertEqual(request.httpMethod, "POST")
            let payload = try self.body(request); XCTAssertEqual(payload["enabled"] as? Bool, false); XCTAssertEqual(payload["sort_order"] as? Int, 20)
            return (201, [:], "{\"profile\":\(raw)}")
        }
        let value = try await api.saveProfile(profile); XCTAssertFalse(value.enabled)
        StubProtocol.handler = { request in
            XCTAssertEqual(request.httpMethod, "PATCH"); XCTAssertEqual(request.url?.path, "/api/profiles/p1")
            return (200, [:], "{\"profile\":\(raw)}")
        }
        _ = try await api.saveProfile(value)
        StubProtocol.handler = { request in XCTAssertEqual(request.httpMethod, "GET"); return (200, [:], "{\"profiles\":[\(raw)]}") }
        let values = try await api.profiles(); XCTAssertEqual(values, [value])
        StubProtocol.handler = { request in XCTAssertEqual(request.httpMethod, "DELETE"); XCTAssertEqual(request.url?.path, "/api/profiles/p1"); return (200, [:], #"{"ok":true}"#) }
        try await api.deleteProfile(id: "p1")
    }
    func testShareScopeExpiryAndRevocationContract() async throws {
        StubProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/conversations/c1/shares"); XCTAssertEqual(request.httpMethod, "POST")
            let payload = try self.body(request); XCTAssertEqual(payload["scope"] as? String, "turn"); XCTAssertEqual(payload["message_id"] as? Int, 42); XCTAssertEqual(payload["expires_in"] as? Int, 3600)
            return (201, [:], #"{"share":{"id":"s1","scope":"turn","title":"测试","expires_at":1900000000,"active":true,"access_count":0,"url":"/ai/share/abc_123-"}}"#)
        }
        let value = try await api.createShare(conversationID: "c1", scope: .turn, messageID: 42, expiresIn: 3600)
        XCTAssertEqual(value.publicURL(base: URL(string: "https://test.invalid/")!)?.absoluteString, "https://test.invalid/ai/share/abc_123-")
        StubProtocol.handler = { request in XCTAssertEqual(request.httpMethod, "DELETE"); XCTAssertEqual(request.url?.path, "/api/conversation-shares/s1"); return (200, [:], #"{"ok":true}"#) }
        try await api.revokeShare(id: value.id)
        for url in ["https://evil.invalid/ai/share/x", "/ai/share/../admin", "/ai/share/a?x=1", "/ai/share/"] {
            XCTAssertNil(ConversationShare(id: "x", scope: "turn", title: "", expires_at: 0, active: true, url: url).publicURL(base: URL(string: "https://test.invalid/")!))
        }
    }
    func testExplicitProfileOptOutIsSentAsBoolean() async throws {
        StubProtocol.handler = { request in
            let payload = try self.body(request); XCTAssertEqual(payload["use_profile"] as? Bool, false)
            return (200, ["Content-Type":"text/event-stream"], "data: [DONE]\n\n")
        }
        try await api.stream(id: "c1", content: "测试", imageIDs: [], documentIDs: [], webSearch: false, useProfile: false) { _ in }
    }
    func testInvalidProfilesAndShareRequestsNeverReachNetwork() async throws {
        StubProtocol.handler = { _ in XCTFail("无效数据不应发请求"); return (500, [:], "") }
        do { _ = try await api.saveProfile(AIProfile()); XCTFail() } catch {}
        do { _ = try await api.createShare(conversationID: "c1", scope: .assistant, messageID: nil, expiresIn: 3600); XCTFail() } catch {}
        do { _ = try await api.createShare(conversationID: "c1", scope: .conversation, messageID: nil, expiresIn: 2); XCTFail() } catch {}
        let old = try JSONDecoder().decode(Draft.self, from: Data("{}".utf8)); XCTAssertTrue(old.useProfile)
    }
}


extension APITests {
    func testOCRUploadHasNoCookieAndRegistersOnlyAfterOSS() async throws {
        try credentials.write(SessionCredential(token: "test-only", expires: Date().addingTimeInterval(600)))
        var step = 0
        StubProtocol.handler = { request in
            step += 1
            if step == 1 {
                XCTAssertEqual(request.url?.path, "/api/ocr/upload-policy")
                return (200, [:], #"{"policy":{"host":"https://oss.invalid/","access_key_id":"test","policy":"test","signature":"test","key_prefix":"ocr/u1/","max_size":10485760,"expires_at":4102444800}}"#)
            }
            if step == 2 {
                XCTAssertEqual(request.url?.host, "oss.invalid"); XCTAssertNil(request.value(forHTTPHeaderField: "Cookie")); XCTAssertEqual(request.httpMethod, "POST")
                return (204, [:], "")
            }
            XCTAssertEqual(request.url?.path, "/api/ocr/tasks"); let value = try self.body(request)
            XCTAssertEqual(value["mime_type"] as? String, "image/jpeg"); XCTAssertEqual(value["file_size"] as? Int, 4)
            XCTAssertTrue((value["oss_key"] as? String ?? "").hasPrefix("ocr/u1/"))
            return (201, [:], #"{"task":{"id":"o1","filename":"handwriting.jpg","status":"failed","recognized_text":"","error_message":"没有识别到文字"}}"#)
        }
        let result = try await api.recognizeHandwriting(Data([255,216,255,217])) { _ in }
        XCTAssertEqual(step, 3); XCTAssertEqual(result.status, "failed"); XCTAssertFalse(result.error_message.isEmpty)
    }
    func testOCRHistoryAndDeletionAndRejectInvalidImage() async throws {
        StubProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/ocr/tasks"); return (200, [:], #"{"tasks":[{"id":"o1","filename":"笔记.jpg","status":"completed","recognized_text":"原文","error_message":""}]}"#)
        }
        let values = try await api.ocrTasks(); XCTAssertEqual(values[0].recognized_text, "原文")
        StubProtocol.handler = { request in XCTAssertEqual(request.httpMethod, "DELETE"); XCTAssertEqual(request.url?.path, "/api/ocr/tasks/o1"); return (200, [:], #"{"ok":true}"#) }
        try await api.deleteOCRTask(id: "o1")
        StubProtocol.handler = { _ in XCTFail("不应上传无效图片"); return (500, [:], "") }
        do { _ = try await api.recognizeHandwriting(Data()) { _ in }; XCTFail() } catch {}
    }
}


extension APITests {
    func testWritingRevisionBooleanAndVersionSelectionContract() async throws {
        let raw = #"{"writing":{"requirements":{},"revision":3,"current_version_id":0,"locked_version_id":0,"current":null,"versions":[],"notice":""},"enabled":true}"#
        StubProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/conversations/c1/writing"); XCTAssertEqual(request.httpMethod, "PATCH")
            let payload = try self.body(request); XCTAssertEqual(payload["revision"] as? Int, 2); XCTAssertEqual(payload["enabled"] as? Bool, true)
            return (200, [:], raw)
        }
        let result = try await api.updateWriting(conversationID: "c1", revision: 2, command: .enabled(true)); XCTAssertEqual(result.writing.revision, 3)
        StubProtocol.handler = { request in
            XCTAssertEqual(URLComponents(url: request.url!, resolvingAgainstBaseURL: false)?.queryItems?.first?.value, "12")
            return (200, [:], raw)
        }
        _ = try await api.writing(conversationID: "c1", versionID: 12)
        StubProtocol.handler = { _ in (409, [:], #"{"error":"本单要求已更新"}"#) }
        do { _ = try await api.updateWriting(conversationID: "c1", revision: 2, command: .locked(true)); XCTFail() } catch let error as PlatformError { if case .http(409, _) = error {} else { XCTFail() } }
    }
    func testWritingRequirementsAndDraftValidationAndMessageChecks() throws {
        var requirements = WritingRequirements(); requirements.min_chars = 500; requirements.max_chars = 100
        XCTAssertThrowsError(try WritingCommand.requirements(requirements).body(revision: 0))
        XCTAssertThrowsError(try WritingCommand.draft(" ").body(revision: 0))
        requirements.max_chars = 1000; requirements.required = ["产品名"]
        let body = try WritingCommand.requirements(requirements).body(revision: 7)
        let payload = try XCTUnwrap(body["requirements"] as? [String: Any]); XCTAssertEqual(payload["min_chars"] as? Int, 500); XCTAssertEqual(payload["required"] as? [String], ["产品名"])
        let message = try JSONDecoder().decode(ChatMessage.self, from: Data(#"{"id":42,"role":"assistant","content":"正文","writing_check":{"issues":["缺少本单必带词"],"body_chars":[2],"count_note":"不计空白","scope":"不代表事实核实"}}"#.utf8))
        XCTAssertEqual(message.writingCheck?.issues.count, 1)
    }
    func testMediaMultipartStreamsFileAndRejectsExpiredPolicy() throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString); try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: directory) }
        let file = directory.appendingPathComponent("source"); let output = directory.appendingPathComponent("form")
        let content = Data(repeating: 7, count: 150000); try content.write(to: file)
        let policy = try JSONDecoder().decode(ImageUploadPolicy.self, from: Data(#"{"host":"https://oss.invalid","access_key_id":"test","policy":"test","signature":"test","key_prefix":"media/u1/","max_size":200000,"expires_at":4102444800}"#.utf8))
        try policy.writeMediaForm(file: file, key: "media/u1/test.mp4", boundary: "test-boundary", output: output)
        let form = try Data(contentsOf: output); XCTAssertNotNil(form.range(of: content)); XCTAssertTrue(String(decoding: form.suffix(30), as: UTF8.self).contains("--test-boundary--"))
        XCTAssertThrowsError(try policy.writeMediaForm(file: file, key: "other/test.mp4", boundary: "test", output: output))
        XCTAssertThrowsError(try MediaLimits.validate(filename: "test.txt", size: 1)); XCTAssertThrowsError(try MediaLimits.validate(filename: "test.mp4", size: 0))
    }
    func testMediaRefreshQueriesExistingTaskWithoutRecreating() async throws {
        StubProtocol.handler = { request in
            XCTAssertEqual(request.url?.path, "/api/media/tasks/task-1/refresh"); XCTAssertEqual(request.httpMethod, "POST")
            return (200, [:], #"{"task":{"id":"task-1","filename":"会议.mp4","status":"processing","transcript_text":"","summary_text":"","outline_text":"","enhanced_summary":"","key_points":"","mindmap_text":"","copywriting_text":"","error_message":"暂时无法获取，请稍后刷新"}}"#)
        }
        let value = try await api.refreshMedia(id: "task-1"); XCTAssertTrue(value.pending); XCTAssertFalse(value.error_message.isEmpty)
    }
}


extension APITests {
    func testMediaUploadUsesDiskBodyAndPlatformRegistration() async throws {
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString); try Data("media-test".utf8).write(to: file)
        defer { try? FileManager.default.removeItem(at: file) }
        try credentials.write(SessionCredential(token: "test-only", expires: Date().addingTimeInterval(600)))
        var step = 0
        StubProtocol.handler = { request in
            step += 1
            if step == 1 { XCTAssertEqual(request.url?.path, "/api/media/upload-policy"); return (200, [:], #"{"policy":{"host":"https://oss.invalid/","access_key_id":"test","policy":"test","signature":"test","key_prefix":"media/u1/","max_size":200000,"expires_at":4102444800}}"#) }
            if step == 2 { XCTAssertEqual(request.url?.host, "oss.invalid"); XCTAssertNil(request.value(forHTTPHeaderField: "Cookie")); return (204, [:], "") }
            XCTAssertEqual(request.url?.path, "/api/media/tasks"); let payload = try self.body(request)
            XCTAssertEqual(payload["filename"] as? String, "会议.m4a"); XCTAssertEqual(payload["source_language"] as? String, "cn"); XCTAssertEqual(payload["file_size"] as? Int, 10)
            return (201, [:], #"{"task":{"id":"m1","filename":"会议.m4a","status":"submitted","transcript_text":"","summary_text":"","outline_text":"","enhanced_summary":"","key_points":"","mindmap_text":"","copywriting_text":"","error_message":""}}"#)
        }
        let value = try await api.uploadMedia(file: file, filename: "会议.m4a") { _ in }; XCTAssertEqual(step, 3); XCTAssertTrue(value.pending)
    }
}
