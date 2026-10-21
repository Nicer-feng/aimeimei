import Foundation

public struct SMSLoginConfiguration: Decodable, Sendable {
    public let enabled: Bool
    public let configured: Bool
    public let countryCode: String
    public let codeLength: Int
    public var available: Bool { enabled && configured && countryCode == "86" && codeLength == 6 }
    enum CodingKeys: String, CodingKey {
        case enabled, configured
        case countryCode = "country_code", codeLength = "code_length"
    }
}

public struct SMSLoginChallenge: Decodable, Sendable {
    public let id: String
    public let expiresAt: TimeInterval
    public let resendAfter: Int
    public let message: String
    enum CodingKeys: String, CodingKey {
        case id = "challenge_id", expiresAt = "expires_at", resendAfter = "resend_after", message
    }
}

/// 只在内存保存短信挑战；换手机号即作废，重发倒计时不因切换页面或后台暂停而重置。
public struct SMSLoginState: Sendable {
    public private(set) var phone = ""
    public private(set) var challenge: SMSLoginChallenge?
    public private(set) var resendUntil = Date.distantPast
    public init() {}

    public static func normalizedPhone(_ value: String) -> String {
        var digits = value.filter { $0 >= "0" && $0 <= "9" }
        if digits.count == 15 && digits.hasPrefix("0086") { digits.removeFirst(4) }
        if digits.count == 13 && digits.hasPrefix("86") { digits.removeFirst(2) }
        return digits
    }
    public var validPhone: Bool { phone.range(of: #"^1[3-9][0-9]{9}$"#, options: .regularExpression) != nil }
    public mutating func setPhone(_ value: String) {
        let normalized = Self.normalizedPhone(value)
        if normalized != phone { challenge = nil }
        phone = normalized
    }
    public mutating func accept(_ value: SMSLoginChallenge, at now: Date = Date()) throws {
        guard validPhone, !value.id.isEmpty, value.expiresAt.isFinite,
              value.expiresAt > now.timeIntervalSince1970, (1...3600).contains(value.resendAfter) else {
            throw PlatformError.invalidResponse
        }
        challenge = value
        resendUntil = now.addingTimeInterval(TimeInterval(value.resendAfter))
    }
    public func remaining(at now: Date = Date()) -> Int {
        max(0, Int(ceil(resendUntil.timeIntervalSince(now))))
    }
    public func canSend(at now: Date = Date()) -> Bool { validPhone && remaining(at: now) == 0 }
    public func canVerify(code: String, at now: Date = Date()) -> Bool {
        guard validPhone, let challenge, challenge.expiresAt > now.timeIntervalSince1970 else { return false }
        return code.range(of: #"^[0-9]{6}$"#, options: .regularExpression) != nil
    }
}
