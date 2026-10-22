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
    private func login() {
        XCTAssertTrue(app.textFields["usernameField"].waitForExistence(timeout: 15))
        app.textFields["usernameField"].tap(); app.textFields["usernameField"].typeText("family")
        app.secureTextFields["passwordField"].tap(); app.secureTextFields["passwordField"].typeText("test-only")
        app.textFields["captchaField"].tap(); app.textFields["captchaField"].typeText("AB23")
        if !app.buttons["loginButton"].isHittable { app.swipeUp() }
        app.buttons["loginButton"].tap()
        XCTAssertTrue(app.buttons["historyButton"].waitForExistence(timeout: 10))
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
        login(); capture("07-dark-larger-text")
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
