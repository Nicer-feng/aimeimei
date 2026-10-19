import XCTest

final class MeimeiUITests: XCTestCase {
    private var app: XCUIApplication!
    override func setUp() {
        continueAfterFailure = false
        app = XCUIApplication(); app.launchArguments = ["--ui-testing"]
        app.launch()
    }
    private func capture(_ name: String) {
        let attachment = XCTAttachment(screenshot: app.screenshot())
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
    func testDarkAppearanceLargerTextAndLandscape() {
        app.terminate()
        app.launchArguments += ["-appearance", "dark", "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityM"]
        app.launch()
        login(); capture("07-dark-larger-text")
        XCUIDevice.shared.orientation = .landscapeLeft
        defer { XCUIDevice.shared.orientation = .portrait }
        XCTAssertTrue(app.buttons["sendButton"].waitForExistence(timeout: 5))
        capture("08-landscape")
    }
}
