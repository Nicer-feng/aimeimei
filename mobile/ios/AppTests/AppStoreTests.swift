import XCTest
import UIKit
import MeimeiCore
@testable import Meimei

@MainActor
final class AppStoreTests: XCTestCase {
    private var directory: URL!
    private var local: LocalState!
    private var api: DemoAPI!
    private var store: AppStore!
    private var audio: TestAudioOutput!
    override func setUpWithError() throws {
        directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        local = try LocalState(directory: directory); api = DemoAPI()
        audio = TestAudioOutput()
        store = AppStore(api: api, local: local, audioOutput: audio)
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
    func testOCRResultSyncAndLogoutCleanupDoesNotReplaceDraft() async throws {
        await login(); store.setText("保留草稿")
        await store.ocr.upload(Data([255,216,255,217])); XCTAssertEqual(store.ocr.tasks.count, 1)
        XCTAssertEqual(store.draft.text, "保留草稿")
        let value = try XCTUnwrap(store.ocr.tasks.first); await store.ocr.load(); XCTAssertEqual(store.ocr.tasks.first, value)
        await store.ocr.delete(value); XCTAssertTrue(store.ocr.tasks.isEmpty)
        await store.ocr.upload(Data([255,216,255,217])); await store.logout(); XCTAssertTrue(store.ocr.tasks.isEmpty)
    }
    func testPersonalToolsCRUDRevocationAndLogoutCleanup() async throws {
        await login(); store.setUseProfile(false)
        XCTAssertFalse(local.draft(accountID: "offline-user", conversationID: "").useProfile)
        let value = AIProfile(title: "背景", content: "项目背景")
        let saved = await store.personal.save(value); XCTAssertTrue(saved)
        XCTAssertEqual(store.personal.profiles.count, 1)
        let profile = try XCTUnwrap(store.personal.profiles.first)
        await store.personal.delete(profile); XCTAssertTrue(store.personal.profiles.isEmpty)
        await store.personal.create(conversationID: "history", scope: .conversation, messageID: nil, expires: 86400)
        let share = try XCTUnwrap(store.personal.createdShare); XCTAssertTrue(share.active)
        await store.personal.revoke(share); XCTAssertNil(store.personal.createdShare); XCTAssertFalse(store.personal.shares[0].active)
        await store.logout(); XCTAssertTrue(store.personal.profiles.isEmpty); XCTAssertTrue(store.personal.shares.isEmpty)
    }
    func testFavoriteChangesSyncToWebStateAndDoNotChangeDraft() async throws {
        await login(); await store.select(store.conversations[0]); store.setText("保留当前草稿")
        let message = try XCTUnwrap(store.messages.first { $0.id == 2 })
        XCTAssertFalse(store.isFavorite(message))
        await store.toggleFavorite(message); XCTAssertTrue(store.isFavorite(message))
        await store.loadFavorites(); XCTAssertEqual(store.favorites.map(\.messageID), [2])
        let remote = try await api.favorites(); XCTAssertEqual(remote.count, 1)
        await store.removeFavorite(store.favorites[0]); XCTAssertFalse(store.isFavorite(message))
        let remaining = try await api.favorites(); XCTAssertTrue(remaining.isEmpty)
        XCTAssertEqual(store.draft.text, "保留当前草稿")
        _ = try await api.favorite(messageID: 2)
        await store.refresh()
        XCTAssertTrue(store.isFavorite(try XCTUnwrap(store.messages.first { $0.id == 2 })))
    }
    func testPromptRequiresConfirmationAndNeverCreatesOrSendsConversation() async throws {
        await login(); await store.loadPrompts()
        let prompt = try XCTUnwrap(store.prompts.first)
        store.setText("还没写完的草稿")
        XCTAssertFalse(store.applyPrompt(prompt)); XCTAssertEqual(store.draft.text, "还没写完的草稿")
        XCTAssertTrue(store.applyPrompt(prompt, replace: true)); XCTAssertEqual(store.draft.text, prompt.content)
        XCTAssertNil(store.selected); XCTAssertTrue(store.messages.isEmpty); XCTAssertEqual(store.conversations.count, 1)
        let restored = local.draft(accountID: "offline-user", conversationID: "")
        XCTAssertEqual(restored.text, prompt.content)
    }
    func testSearchOpenLocatesMessageAndPreservesOtherConversationDraft() async {
        await login(); store.setText("首页草稿")
        await store.searchLibrary("把想法")
        XCTAssertTrue(store.searchResults.contains { $0.messageID == 2 })
        let opened = await store.openMessage(conversationID: "history", messageID: 2)
        XCTAssertTrue(opened); XCTAssertEqual(store.focusedMessageID, 2); XCTAssertEqual(store.selected?.id, "history")
        store.setText("历史草稿")
        let missing = await store.openMessage(conversationID: "missing", messageID: 42)
        XCTAssertFalse(missing); XCTAssertEqual(store.draft.text, "历史草稿"); XCTAssertEqual(store.selected?.id, "history")
        store.newChat(); XCTAssertNil(store.focusedMessageID); XCTAssertEqual(store.draft.text, "首页草稿")
    }
    func testSlowerPreviousSearchCannotReplaceLatestResults() async throws {
        await login(); await api.setSearchDelay(.milliseconds(500), query: "把想法")
        let old = Task { await store.searchLibrary("把想法") }
        try await Task.sleep(for: .milliseconds(300))
        await store.searchLibrary("没有这个关键词"); await old.value
        XCTAssertTrue(store.searchResults.isEmpty); XCTAssertFalse(store.searching)
    }
    func testDeletedConversationFavoriteCanStillBeReadAndSearched() async {
        await login(); await api.seedArchivedFavorite(); await store.loadFavorites()
        XCTAssertEqual(store.favorites.first?.content, "删除会话后仍保留的收藏快照")
        XCTAssertFalse(store.favorites.first?.canOpenConversation ?? true)
        await store.searchLibrary("快照")
        XCTAssertEqual(store.searchResults.first?.id, "favorite:archived")
        let snapshot = await store.favoriteSnapshot(resultID: "favorite:archived")
        XCTAssertEqual(snapshot?.messageID, 999)
    }
    func testLogoutClearsLibraryAndRejectsSearchArrivingAfterLogout() async throws {
        await login(); await api.seedArchivedFavorite(); await store.loadFavorites(); await store.loadPrompts()
        await api.setSearchDelay(.milliseconds(500), query: "把想法")
        let pendingSearch = Task { await store.searchLibrary("把想法") }
        try await Task.sleep(for: .milliseconds(300)); await store.logout(); await pendingSearch.value
        XCTAssertNil(store.account); XCTAssertTrue(store.favorites.isEmpty); XCTAssertTrue(store.prompts.isEmpty)
        XCTAssertTrue(store.searchResults.isEmpty); XCTAssertFalse(store.searching)
    }
    func testSMSLoginRejectsInvalidCodeThenLoadsSameWorkspace() async {
        await store.start(); XCTAssertTrue(store.smsConfig?.available == true)
        store.setLoginPhone("+86 13800000000")
        await store.sendLoginSMS(); await store.sendLoginSMS()
        var counts = await api.smsCounts(); XCTAssertEqual(counts.sends, 1)
        await store.loginSMS(code: "000000")
        XCTAssertNil(store.account); XCTAssertEqual(store.error, "验证码不正确或已过期")
        XCTAssertNotNil(store.smsLogin.challenge)
        await store.loginSMS(code: "123456")
        XCTAssertEqual(store.account?.id, "offline-user"); XCTAssertEqual(store.conversations.count, 1)
        XCTAssertFalse(store.models.isEmpty); XCTAssertNil(store.smsLogin.challenge)
        XCTAssertEqual(store.smsLogin.phone, ""); XCTAssertNil(store.loginNotice)
        counts = await api.smsCounts(); XCTAssertEqual(counts.verifications, 2)
    }
    func testChangingPhonePreventsVerifyingOldSMSChallenge() async {
        await store.start(); store.setLoginPhone("13800000000"); await store.sendLoginSMS()
        store.setLoginPhone("13900000000"); await store.loginSMS(code: "123456")
        XCTAssertNil(store.account)
        let counts = await api.smsCounts(); XCTAssertEqual(counts.verifications, 0)
    }
    func testExpiredRestoredSessionCanLoadSMSLoginConfiguration() async {
        await login()
        let restored = AppStore(api: api, local: local)
        await restored.start(); XCTAssertNotNil(restored.account); XCTAssertNil(restored.smsConfig)
        try? await api.logout(); await restored.refresh()
        XCTAssertNil(restored.account)
        await restored.loadSMSConfigurationIfNeeded()
        XCTAssertTrue(restored.smsConfig?.available == true)
    }
    func testUnavailableSMSDoesNotBlockPasswordLogin() async {
        await api.setSMSAvailable(false); await store.start()
        XCTAssertFalse(store.smsConfig?.available ?? true)
        store.setLoginPhone("13800000000"); await store.sendLoginSMS()
        let counts = await api.smsCounts(); XCTAssertEqual(counts.sends, 0)
        await store.login(username: "family", password: "test-only", answer: "AB23")
        XCTAssertNotNil(store.account)
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
        _ = try? await api.configureConversation(id: item.id, modelID: "m2", mode: .deep)
        await store.refresh()
        XCTAssertEqual(store.draft.modelID, "m2"); XCTAssertEqual(store.draft.reasoningMode, .deep)
        XCTAssertEqual(store.draft.text, "历史会话草稿")
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

extension AppStoreTests {
    func testImageOnlySendPersistsAndReconcilesWithoutReplay() async throws {
        await login(); await store.addImage(Data([1,2,3]))
        let image = try XCTUnwrap(store.draft.images.first)
        XCTAssertTrue(store.canSend)
        XCTAssertEqual(local.draft(accountID: "offline-user", conversationID: "").images.map(\.id), [image.id])
        store.setSearch(true); await store.send(); try await waitUntilIdle()
        XCTAssertNil(store.pending); XCTAssertTrue(store.draft.images.isEmpty)
        let question = try XCTUnwrap(store.messages.first { $0.role == "user" })
        XCTAssertEqual(question.content, ""); XCTAssertEqual(question.images.map(\.id), [image.id])
        XCTAssertEqual(store.messages.filter { $0.role == "user" }.count, 1)
        XCTAssertEqual(store.messages.last?.sources.first?.safeURL?.host, "www.swift.org")
        await store.refresh(); XCTAssertEqual(store.messages.filter { $0.role == "user" }.count, 1)
    }
    func testUploadFailureKeepsPhotoForExplicitRetryAndNeverSends() async throws {
        await login(); store.setText("保留问题"); await api.setUploadFails(true)
        await store.addImage(Data([1,2,3]))
        XCTAssertNotNil(store.failedImage); XCTAssertTrue(store.draft.images.isEmpty); XCTAssertFalse(store.canSend)
        await store.send(); XCTAssertNil(store.selected)
        await api.setUploadFails(false); await store.retryImage()
        XCTAssertNil(store.failedImage); XCTAssertEqual(store.draft.images.count, 1)
        XCTAssertEqual(store.draft.text, "保留问题"); XCTAssertNil(store.selected)
    }
    func testVisionCapabilityLimitAndStalePickerIsolation() async throws {
        await login()
        let oldContext = store.attachmentContext; store.newChat()
        await store.addImage(Data([1]), context: oldContext); XCTAssertTrue(store.draft.images.isEmpty)
        for _ in 0..<6 { await store.addImage(Data([1,2,3])) }
        XCTAssertEqual(store.draft.images.count, 5)
        await store.configure(modelID: "m2", mode: .balanced); XCTAssertFalse(store.canSend)
        await store.configure(modelID: "m1", mode: .balanced); XCTAssertTrue(store.canSend)
        store.removeImage(store.draft.images[0].id); XCTAssertEqual(store.draft.images.count, 4)
        await store.logout(); XCTAssertTrue(store.draft.images.isEmpty); XCTAssertNil(store.failedImage)
    }
}

extension AppStoreTests {
    func testImagePreparationRejectsInvalidDataAndLimitsLargePhoto() throws {
        XCTAssertThrowsError(try ChatImagePreparation.jpeg(Data("not an image".utf8)))
        let source = UIGraphicsImageRenderer(size: CGSize(width: 4000, height: 1000)).pngData { context in
            UIColor.systemTeal.setFill(); context.fill(CGRect(x: 0, y: 0, width: 4000, height: 1000))
        }
        let jpeg = try ChatImagePreparation.jpeg(source)
        let image = try XCTUnwrap(UIImage(data: jpeg))
        XCTAssertEqual(max(image.size.width, image.size.height), 2048)
        XCTAssertEqual(image.size.width / image.size.height, 4, accuracy: 0.01)
        XCTAssertEqual(Array(jpeg.prefix(2)), [0xFF, 0xD8])
    }
}

@MainActor private final class TestAudioOutput: AudioOutput {
    var onFinish: ((Bool) -> Void)?
    var onPause: (() -> Void)?
    private(set) var plays = 0
    private(set) var pauses = 0
    private(set) var resumes = 0
    private(set) var data: Data?
    func play(_ data: Data) throws { plays += 1; self.data = data }
    func pause() { pauses += 1 }
    func resume() throws { resumes += 1 }
    func stop() { data = nil }
}

extension AppStoreTests {
    private func waitSpeech(_ condition: () -> Bool) async throws {
        for _ in 0..<100 { if condition() { return }; try await Task.sleep(for: .milliseconds(20)) }
        XCTFail("朗读状态未及时更新")
    }
    func testDocumentParsingBlocksSendAndTransientRefreshDoesNotReupload() async throws {
        await login(); store.setText("请总结这份材料")
        await store.addDocument(Data("材料".utf8), filename: "项目说明.txt")
        XCTAssertEqual(store.draft.documents.count, 1); XCTAssertFalse(store.canSend)
        await api.setDocumentRefreshFailure(true); await store.refreshDocuments()
        XCTAssertTrue(store.draft.documents[0].processing); XCTAssertFalse(store.canSend)
        await api.setDocumentRefreshFailure(false); await store.refreshDocuments()
        XCTAssertTrue(store.canSend)
        let count = await api.documentCount(); XCTAssertEqual(count, 1)
        await store.send(); try await waitUntilIdle()
        XCTAssertNil(store.pending); XCTAssertTrue(store.draft.documents.isEmpty)
        XCTAssertEqual(store.messages.first?.documents.first?.filename, "项目说明.txt")
    }
    func testFileOnlyQuestionWorksWithTextModelAndRemovalKeepsWebFile() async throws {
        await login(); await store.configure(modelID: "m2", mode: .balanced)
        await store.addDocument(Data("材料".utf8), filename: "材料.txt"); await store.refreshDocuments()
        let file = try XCTUnwrap(store.draft.documents.first)
        store.removeDocument(file.id)
        let remote = try await api.documents(); XCTAssertEqual(remote.count, 1)
        XCTAssertTrue(store.chooseDocument(file)); XCTAssertTrue(store.canSend)
        store.setDocumentImporting(true, context: store.attachmentContext); XCTAssertFalse(store.canSend)
        store.setDocumentImporting(false, context: store.attachmentContext); XCTAssertTrue(store.canSend)
        await store.send(); try await waitUntilIdle()
        XCTAssertEqual(store.messages.first?.content, ""); XCTAssertEqual(store.messages.first?.documents.map(\.id), [file.id])
    }
    func testDocumentRetryLimitContextAndLogoutIsolation() async throws {
        await login(); let old = store.attachmentContext; store.newChat()
        await store.addDocument(Data([1]), filename: "x.txt", context: old); XCTAssertTrue(store.draft.documents.isEmpty)
        await api.setDocumentFailure(true); await store.addDocument(Data([1]), filename: "失败.txt")
        XCTAssertNotNil(store.failedDocument); XCTAssertFalse(store.canSend)
        await api.setDocumentFailure(false); await store.retryDocument(); XCTAssertNil(store.failedDocument)
        for _ in 0..<5 { await store.addDocument(Data([1]), filename: "材料.txt") }
        XCTAssertEqual(store.draft.documents.count, 5)
        await store.logout(); XCTAssertTrue(store.documents.isEmpty); XCTAssertTrue(store.draft.documents.isEmpty); XCTAssertNil(store.failedDocument)
    }
    func testSpeechPauseResumeAndSettingsNeverRegenerateUntilExplicitPlay() async throws {
        await login(); await store.speech.loadConfiguration()
        let initial = await api.speechCounts(); XCTAssertEqual(initial.audio, 0)
        store.speech.play(messageID: 2); try await waitSpeech { store.speech.state == .playing }
        store.speech.pause(); XCTAssertEqual(store.speech.state, .paused)
        store.speech.resume(); XCTAssertEqual(store.speech.state, .playing)
        let first = await api.speechCounts(); XCTAssertEqual(first.prepare, 1); XCTAssertEqual(first.audio, 1)
        XCTAssertEqual(audio.pauses, 1); XCTAssertEqual(audio.resumes, 1)
        store.speech.setVoice("clear"); store.speech.setSpeed(1.25); XCTAssertEqual(store.speech.state, .idle)
        let still = await api.speechCounts(); XCTAssertEqual(still.audio, 1)
        store.speech.play(messageID: 2); try await waitSpeech { store.speech.state == .playing }
        let changed = await api.speechCounts(); XCTAssertEqual(changed.audio, 2)
        await store.logout(); XCTAssertNil(audio.data); XCTAssertNil(store.speech.configuration)
    }
    func testLongSpeechRequiresConfirmationBeforeAnyAudioRequest() async throws {
        await login(); await api.setSpeechLong(true); await store.speech.loadConfiguration()
        store.speech.play(messageID: 2); try await waitSpeech { store.speech.needsConfirmation }
        let before = await api.speechCounts(); XCTAssertEqual(before.audio, 0)
        store.speech.cancelLongText(); XCTAssertFalse(store.speech.needsConfirmation)
        store.speech.play(messageID: 2); try await waitSpeech { store.speech.needsConfirmation }
        store.speech.confirmLongText(); try await waitSpeech { store.speech.state == .playing }
        let after = await api.speechCounts(); XCTAssertEqual(after.prepare, 2); XCTAssertEqual(after.audio, 1)
    }
    func testStoppedSpeechCannotPlayLateResponseAndDisabledConfigMakesNoRequest() async throws {
        await login(); await store.speech.loadConfiguration(); await api.setSpeechDelay(.milliseconds(250))
        store.speech.play(messageID: 2)
        for _ in 0..<50 { if await api.speechCounts().audio > 0 { break }; try await Task.sleep(for: .milliseconds(10)) }
        store.newChat(); try await Task.sleep(for: .milliseconds(400))
        XCTAssertEqual(audio.plays, 0); XCTAssertEqual(store.speech.state, .idle)
        await api.setSpeechEnabled(false); await store.speech.loadConfiguration(reload: true)
        let before = await api.speechCounts(); store.speech.play(messageID: 2)
        try await Task.sleep(for: .milliseconds(50)); let after = await api.speechCounts()
        XCTAssertEqual(before.prepare, after.prepare); XCTAssertEqual(before.audio, after.audio)
    }
    func testFileImporterReadsSelectedFileAndRejectsEmptyFile() throws {
        let file = directory.appendingPathComponent("项目说明.txt"); try Data("测试材料".utf8).write(to: file)
        let imported = try ImportedDocument.read(file)
        XCTAssertEqual(imported.filename, "项目说明.txt"); XCTAssertEqual(String(decoding: imported.data, as: UTF8.self), "测试材料")
        try Data().write(to: file); XCTAssertThrowsError(try ImportedDocument.read(file))
    }
}
