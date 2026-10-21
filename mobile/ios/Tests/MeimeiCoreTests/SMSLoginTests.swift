import XCTest
@testable import MeimeiCore

final class SMSLoginTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 2_000_000_000)
    private func challenge(expires: TimeInterval = 2_000_000_300) throws -> SMSLoginChallenge {
        try JSONDecoder().decode(SMSLoginChallenge.self, from: Data("{\"challenge_id\":\"test-only\",\"expires_at\":\(expires),\"resend_after\":60,\"message\":\"如手机号已绑定，验证码将很快送达。\"}".utf8))
    }
    func testPhoneNormalizationAndValidation() {
        var state = SMSLoginState()
        for phone in ["+86 138-0000-0000", "008613800000000", "13800000000"] {
            state.setPhone(phone)
            XCTAssertEqual(state.phone, "13800000000"); XCTAssertTrue(state.validPhone)
        }
        for phone in ["123", "12800000000", "138000000000"] {
            state.setPhone(phone); XCTAssertFalse(state.validPhone); XCTAssertFalse(state.canSend(at: now))
        }
    }
    func testCooldownUsesDeadlineAndChangedPhoneInvalidatesChallenge() throws {
        var state = SMSLoginState(); state.setPhone("13800000000")
        try state.accept(challenge(), at: now)
        XCTAssertEqual(state.remaining(at: now.addingTimeInterval(10.1)), 50)
        XCTAssertFalse(state.canSend(at: now.addingTimeInterval(59)))
        XCTAssertTrue(state.canSend(at: now.addingTimeInterval(60)))
        state.setPhone("13900000000")
        XCTAssertNil(state.challenge); XCTAssertFalse(state.canVerify(code: "123456", at: now))
        XCTAssertEqual(state.remaining(at: now), 60)
    }
    func testExpiryAndExactSixASCIIDigitsAreRequired() throws {
        var state = SMSLoginState(); state.setPhone("13800000000"); try state.accept(challenge(), at: now)
        XCTAssertTrue(state.canVerify(code: "123456", at: now))
        for code in ["12345", "1234567", "１２３４５６", "12345a"] { XCTAssertFalse(state.canVerify(code: code, at: now)) }
        XCTAssertFalse(state.canVerify(code: "123456", at: now.addingTimeInterval(300)))
        XCTAssertThrowsError(try state.accept(challenge(expires: now.timeIntervalSince1970 - 1), at: now))
    }
    func testDisabledOrUnsupportedConfigurationIsUnavailable() throws {
        for raw in [
            #"{"enabled":true,"configured":false,"country_code":"86","code_length":6}"#,
            #"{"enabled":false,"configured":true,"country_code":"86","code_length":6}"#,
            #"{"enabled":true,"configured":true,"country_code":"1","code_length":6}"#
        ] {
            let config = try JSONDecoder().decode(SMSLoginConfiguration.self, from: Data(raw.utf8))
            XCTAssertFalse(config.available)
        }
    }
}
