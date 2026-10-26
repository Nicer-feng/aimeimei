import XCTest

final class MeimeiUITests: XCTestCase {
    private var app: XCUIApplication!
    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication(); app.launchArguments = ["--ui-testing"]
        app.launch()
    }
    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.windows.firstMatch.screenshot())
        attachment.name = name; attachment.lifetime = .keepAlways; add(attachment)
    }
    private func login(_ username: String = "family") {
        XCTAssertTrue(app.textFields["usernameField"].waitForExistence(timeout: 15))
        app.textFields["usernameField"].tap(); app.textFields["usernameField"].typeText(username)
        app.secureTextFields["passwordField"].tap(); app.secureTextFields["passwordField"].typeText("test-only")
        app.textFields["captchaField"].tap(); app.textFields["captchaField"].typeText("AB23")
        if !app.buttons["loginButton"].isHittable { app.swipeUp() }
        app.buttons["loginButton"].tap()
        XCTAssertTrue(app.buttons["historyButton"].waitForExistence(timeout: 10))
    }
    func testPinnedDailyReportHasNoChatComposer() {
        login("feng")
        app.buttons["historyButton"].tap()
        XCTAssertTrue(app.buttons["dailyReportEntry"].waitForExistence(timeout: 5))
        capture("40-daily-report-pinned")
        app.buttons["dailyReportEntry"].tap()
        XCTAssertTrue(app.staticTexts["今日前端更新"].waitForExistence(timeout: 10))
        XCTAssertFalse(app.textViews["composerField"].exists)
        XCTAssertFalse(app.buttons["sendButton"].exists)
        capture("41-daily-report-read-only")
    }
    func testOtherAccountsDoNotHaveDailyReportEntry() {
        login()
        app.buttons["historyButton"].tap()
        XCTAssertFalse(app.buttons["dailyReportEntry"].exists)
    }
    func testWritingDraftSaveAndLock() {
        login(); let tools = app.scrollViews["composerToolsScroll"]; tools.swipeLeft()
        XCTAssertTrue(app.buttons["writingButton"].waitForExistence(timeout: 5)); app.buttons["writingButton"].tap()
        XCTAssertTrue(app.switches["writingEnabled"].waitForExistence(timeout: 5)); app.switches["writingEnabled"].tap()
        let editor = app.textViews["writingDraft"]
        for _ in 0..<8 { if editor.isHittable { break }; app.swipeUp() }
        XCTAssertTrue(editor.isHittable); editor.tap(); editor.typeText("Approved manuscript")
        let save = app.buttons["saveWritingDraft"]
        for _ in 0..<5 { if save.isHittable { break }; app.swipeUp() }; save.tap()
        let lock = app.buttons["lockWritingDraft"]; XCTAssertTrue(lock.waitForExistence(timeout: 5))
        if !lock.isHittable { app.swipeUp() }; lock.tap()
        XCTAssertTrue(app.buttons["解锁定稿"].waitForExistence(timeout: 5)); XCTAssertFalse(app.keyboards.firstMatch.exists); capture("30-writing-locked")
    }
    func testMediaAnalysisResultsAndConversation() {
        login(); app.buttons["settingsButton"].tap(); app.buttons["mediaEntry"].tap()
        XCTAssertTrue(app.buttons["testMedia"].waitForExistence(timeout: 5)); app.buttons["testMedia"].tap(); app.buttons["uploadMedia"].tap()
        let row = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "mediaTask-")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 5)); row.tap()
        XCTAssertTrue(app.staticTexts["分析完成"].waitForExistence(timeout: 15)); capture("31-media-result")
        let open = app.buttons["openMediaConversation"]; if !open.isHittable { app.swipeUp() }; open.tap()
        XCTAssertTrue(app.staticTexts["已打开分析会话，关闭工具返回聊天即可继续提问。"].waitForExistence(timeout: 10))
    }
    func testHandwritingRecognitionAndDraftFill() {
        login(); app.buttons["settingsButton"].tap(); app.buttons["ocrEntry"].tap()
        XCTAssertTrue(app.buttons["testOCRImage"].waitForExistence(timeout: 5)); app.buttons["testOCRImage"].tap(); app.buttons["startOCR"].tap()
        let row = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "ocrTask-")).firstMatch
        XCTAssertTrue(row.waitForExistence(timeout: 5)); capture("28-ocr-history"); row.tap()
        XCTAssertTrue(app.textViews["ocrResultText"].waitForExistence(timeout: 5)); capture("29-ocr-result")
        app.buttons["applyOCR"].tap(); app.navigationBars.buttons.element(boundBy: 0).tap(); app.buttons["完成"].tap()
        let composer = app.textViews["composerField"].exists ? app.textViews["composerField"] : app.textFields["composerField"]
        XCTAssertEqual(composer.value as? String, "今天完成项目计划，明天继续。")
    }
    func testProfilesAndConversationShareCreationAndRevocation() {
        login(); app.buttons["settingsButton"].tap(); app.buttons["profilesEntry"].tap()
        XCTAssertTrue(app.buttons["addProfile"].waitForExistence(timeout: 5)); app.buttons["addProfile"].tap()
        app.textFields["profileTitle"].tap(); app.textFields["profileTitle"].typeText("Style")
        app.textViews["profileContent"].tap(); app.textViews["profileContent"].typeText("Keep it concise")
        app.buttons["saveProfile"].tap()
        XCTAssertTrue(app.staticTexts["Style"].waitForExistence(timeout: 5)); capture("25-profiles")
        app.navigationBars.buttons.element(boundBy: 0).tap(); app.buttons["完成"].tap()
        app.buttons["historyButton"].tap(); app.buttons.containing(.staticText, identifier: "一次小小的好奇").firstMatch.tap()
        app.buttons["shareMessage-2"].tap(); app.buttons["分享链接"].tap()
        XCTAssertTrue(app.buttons["createShare"].waitForExistence(timeout: 5)); app.buttons["createShare"].tap()
        XCTAssertTrue(app.buttons["复制链接"].waitForExistence(timeout: 5)); capture("26-share-link")
        let revoke = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "revokeShare-")).firstMatch
        if !revoke.isHittable { app.swipeUp() }; revoke.tap(); app.buttons["确认撤销"].tap()
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "已失效")).firstMatch.waitForExistence(timeout: 5)); capture("27-share-revoked")
    }
    func testLoginWelcomeHistoryAndFirstSend() {
        XCTAssertTrue(app.textFields["usernameField"].waitForExistence(timeout: 15)); capture("01-login")
        login(); capture("02-welcome")
        for _ in 0..<3 { app.buttons["newChatButton"].tap() }
        app.buttons["historyButton"].tap()
        XCTAssertTrue(app.buttons.containing(.staticText, identifier: "一次小小的好奇").firstMatch.waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["新对话"].exists, "打开新聊天不应创建空会话")
        capture("03-history")
        app.buttons.containing(.staticText, identifier: "一次小小的好奇").firstMatch.tap()
        XCTAssertTrue(app.staticTexts["把想法慢慢理清"].waitForExistence(timeout: 5)); capture("04-markdown")
        app.buttons["newChatButton"].tap()
        let composer = app.textViews["composerField"].exists ? app.textViews["composerField"] : app.textFields["composerField"]
        XCTAssertTrue(composer.waitForExistence(timeout: 5)); composer.tap(); composer.typeText("Hello Meimei")
        app.buttons["sendButton"].tap()
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "我们从哪里开始？")).firstMatch.waitForExistence(timeout: 10))
        XCTAssertTrue(app.buttons["sendButton"].waitForExistence(timeout: 5))
        let confirmed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: app.descendants(matching: .any)["liveReply"])
        XCTAssertEqual(XCTWaiter.wait(for: [confirmed], timeout: 5), .completed)
        capture("05-chat")
    }
    func testModelCapabilityAndDraftSurviveNavigation() {
        login()
        app.buttons["modelMenu"].tap(); app.buttons["槑槑 · 轻快"].tap()
        XCTAssertFalse(app.buttons["reasoningMenu"].exists)
        app.buttons["modelMenu"].tap(); app.buttons["槑槑 · 思考"].tap()
        XCTAssertTrue(app.buttons["reasoningMenu"].waitForExistence(timeout: 5))
        app.buttons["reasoningMenu"].tap(); app.buttons["深度"].tap()
        let composer = app.textViews["composerField"].exists ? app.textViews["composerField"] : app.textFields["composerField"]
        composer.tap(); composer.typeText("Keep this draft")
        app.buttons["newChatButton"].tap()
        XCTAssertEqual(composer.value as? String, "Keep this draft")
        capture("06-draft")
    }
    func testFavoriteSearchAndReturnToOriginalMessage() {
        login(); app.buttons["historyButton"].tap()
        app.buttons.containing(.staticText, identifier: "一次小小的好奇").firstMatch.tap()
        XCTAssertTrue(app.buttons["favoriteMessage-2"].waitForExistence(timeout: 5))
        app.buttons["favoriteMessage-2"].tap()
        app.buttons["libraryButton"].tap()
        XCTAssertTrue(app.buttons["favorite-2"].waitForExistence(timeout: 5))
        capture("11-favorites")
        app.buttons["favorite-2"].tap()
        app.buttons["openFavoriteOrigin"].tap()
        XCTAssertTrue(app.buttons["historyButton"].waitForExistence(timeout: 5))
        app.buttons["libraryButton"].tap()
        app.segmentedControls["librarySections"].buttons["搜索"].tap()
        let field = app.textFields["globalSearchField"]
        XCTAssertTrue(field.waitForExistence(timeout: 5)); field.tap(); field.typeText("Markdown")
        XCTAssertTrue(app.buttons["search-message:1"].waitForExistence(timeout: 5))
        capture("12-global-search")
        app.buttons["search-message:1"].tap()
        XCTAssertTrue(app.buttons["historyButton"].waitForExistence(timeout: 5))
        capture("13-message-location")
    }
    func testPromptReplacementRequiresConfirmationAndDoesNotSend() {
        login()
        let composer = app.textViews["composerField"].exists ? app.textViews["composerField"] : app.textFields["composerField"]
        composer.tap(); composer.typeText("Keep my draft")
        app.buttons["promptsButton"].tap()
        XCTAssertTrue(app.buttons["prompt-daily"].waitForExistence(timeout: 5))
        app.buttons["prompt-daily"].tap(); capture("14-prompt-preview")
        app.buttons["applyPromptButton"].tap()
        XCTAssertTrue(app.alerts["替换当前草稿？"].waitForExistence(timeout: 5))
        app.alerts.buttons["保留草稿"].tap()
        app.buttons["applyPromptButton"].tap(); app.alerts.buttons["替换草稿"].tap()
        XCTAssertTrue(app.buttons["historyButton"].waitForExistence(timeout: 5))
        XCTAssertEqual(composer.value as? String, "请帮我制定今天的计划，列出优先级和下一步。")
        XCTAssertTrue(app.descendants(matching: .any)["welcomeView"].exists)
        capture("15-prompt-draft")
    }
    func testSMSLoginAndPasswordSwitchPreserveCooldown() {
        XCTAssertTrue(app.segmentedControls["loginModePicker"].waitForExistence(timeout: 15))
        app.segmentedControls["loginModePicker"].buttons["短信验证码"].tap()
        let phone = app.textFields["phoneField"]
        XCTAssertTrue(phone.waitForExistence(timeout: 5)); phone.tap(); phone.typeText("13800000000")
        app.buttons["sendSMSButton"].tap()
        let notice = app.staticTexts["smsNotice"]
        XCTAssertTrue(notice.waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["sendSMSButton"].isEnabled)
        app.swipeDown()
        app.segmentedControls["loginModePicker"].buttons["账号密码"].tap()
        XCTAssertTrue(app.textFields["usernameField"].exists)
        app.segmentedControls["loginModePicker"].buttons["短信验证码"].tap()
        XCTAssertFalse(app.buttons["sendSMSButton"].isEnabled)
        let code = app.textFields["smsCodeField"]
        code.tap(); code.typeText("000000")
        if !app.buttons["loginButton"].isHittable { app.swipeUp() }
        app.buttons["loginButton"].tap()
        XCTAssertTrue(app.staticTexts["验证码不正确或已过期"].waitForExistence(timeout: 5))
        capture("09-sms-invalid-code")
        code.tap(); code.typeText("123456")
        if !app.buttons["loginButton"].isHittable { app.swipeUp() }
        app.buttons["loginButton"].tap()
        XCTAssertTrue(app.buttons["historyButton"].waitForExistence(timeout: 10))
        capture("10-sms-login-welcome")
    }
    func testDarkAppearanceLargerTextAndLandscape() {
        app.terminate()
        app.launchArguments += ["-appearance", "dark", "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityM"]
        app.launch()
        login()
        let tools = app.scrollViews["composerToolsScroll"]
        XCTAssertTrue(tools.waitForExistence(timeout: 5)); tools.swipeLeft()
        XCTAssertTrue(app.buttons["documentsButton"].isHittable, "大字模式下应能横向滑动到文件工具")
        tools.swipeRight(); capture("07-dark-larger-text")
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = .portrait }
        let rotated = XCTNSPredicateExpectation(predicate: NSPredicate { [unowned self] _, _ in
            let window = self.app.windows.firstMatch.frame
            let send = self.app.buttons["sendButton"].frame
            let settings = self.app.buttons["settingsButton"].frame
            return window.width > window.height && !send.isEmpty && !settings.isEmpty
                && window.contains(send) && window.contains(settings)
        }, object: nil)
        XCTAssertEqual(XCTWaiter.wait(for: [rotated], timeout: 10), .completed)
        capture("08-landscape")
    }
}

extension MeimeiUITests {
    func testPhotoDraftPreviewImageOnlySendAndSources() {
        login()
        XCTAssertTrue(app.buttons["addImageButton"].isEnabled)
        app.buttons["addImageButton"].tap(); app.buttons["测试图片"].tap()
        let image = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "image-")).firstMatch
        XCTAssertTrue(image.waitForExistence(timeout: 10))
        let loaded = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == true"), object: image)
        XCTAssertEqual(XCTWaiter.wait(for: [loaded], timeout: 5), .completed)
        capture("16-image-draft")
        image.tap(); XCTAssertTrue(app.navigationBars["图片预览"].waitForExistence(timeout: 5)); capture("17-image-preview")
        app.buttons["完成"].tap()
        app.descendants(matching: .any)["webSearchToggle"].tap()
        XCTAssertTrue(app.buttons["sendButton"].isEnabled); app.buttons["sendButton"].tap()
        let sources = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "sources-")).firstMatch
        XCTAssertTrue(sources.waitForExistence(timeout: 15)); capture("18-image-reply")
        sources.tap(); XCTAssertTrue(app.staticTexts["Swift 编程语言的学习与参考资料。"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.links["sourceLink-0"].exists || app.buttons["sourceLink-0"].exists)
        capture("19-web-sources")
    }
    func testTextOnlyModelDisablesPhotoAndReturningKeepsDraft() {
        login(); app.buttons["addImageButton"].tap(); app.buttons["测试图片"].tap()
        let remove = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "removeImage-")).firstMatch
        XCTAssertTrue(remove.waitForExistence(timeout: 10))
        app.buttons["modelMenu"].tap(); app.buttons["槑槑 · 轻快"].tap()
        XCTAssertFalse(app.buttons["addImageButton"].isEnabled); XCTAssertFalse(app.buttons["sendButton"].isEnabled)
        XCTAssertTrue(app.staticTexts["当前模型不支持图片，请切换支持图片的模型或移除图片"].exists)
        app.buttons["modelMenu"].tap(); app.buttons["槑槑 · 思考"].tap()
        XCTAssertTrue(app.buttons["sendButton"].isEnabled)
        remove.tap(); XCTAssertFalse(app.buttons["sendButton"].isEnabled)
    }
}

extension MeimeiUITests {
    func testDocumentQuestionAndSpeechPlaybackControls() {
        login(); app.buttons["documentsButton"].tap()
        XCTAssertTrue(app.buttons["demoDocumentButton"].waitForExistence(timeout: 5)); app.buttons["demoDocumentButton"].tap()
        XCTAssertTrue(app.staticTexts["项目说明.txt"].firstMatch.waitForExistence(timeout: 10)); capture("20-documents")
        app.buttons["完成"].tap()
        if app.buttons["refreshDocumentsButton"].exists { app.buttons["refreshDocumentsButton"].tap() }
        let ready = XCTNSPredicateExpectation(predicate: NSPredicate(format: "enabled == true"), object: app.buttons["sendButton"])
        XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 15), .completed)
        app.buttons["sendButton"].tap()
        let read = app.buttons["readMessage-12"]
        XCTAssertTrue(read.waitForExistence(timeout: 15))
        XCTAssertTrue(app.staticTexts["项目说明.txt"].firstMatch.exists, "仅文件消息也应显示所引用材料的名称")
        capture("21-document-question")
        read.tap(); XCTAssertTrue(app.buttons["playSpeechButton"].waitForExistence(timeout: 10))
        app.buttons["speechVoicePicker"].tap(); app.buttons["清晰男声"].tap()
        app.buttons["speechSpeedPicker"].tap(); app.buttons["1.25 倍"].tap()
        XCTAssertTrue(app.buttons["playSpeechButton"].exists, "选择音色和语速不应自动生成或播放")
        capture("22-speech-settings")
        app.buttons["playSpeechButton"].tap()
        XCTAssertTrue(app.buttons["pauseSpeechButton"].waitForExistence(timeout: 15)); capture("23-speech-playing")
        app.buttons["pauseSpeechButton"].tap(); XCTAssertTrue(app.buttons["resumeSpeechButton"].waitForExistence(timeout: 5)); capture("24-speech-paused")
        app.buttons["resumeSpeechButton"].tap(); XCTAssertTrue(app.buttons["pauseSpeechButton"].waitForExistence(timeout: 5))
        app.buttons["完成"].tap(); XCTAssertTrue(app.buttons["historyButton"].waitForExistence(timeout: 5))
    }
}
