import Foundation
import Security
import MeimeiCore

/// 登录凭证只存在本机钥匙串，不同步到 iCloud、不进入普通偏好或构建日志。
final class SessionVault: CredentialStore, @unchecked Sendable {
    private let lock = NSLock()
    private let service = "\(Bundle.main.bundleIdentifier ?? "asia.feng.aimeimei").session.feng.asia"
    private var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service,
         kSecAttrAccount as String: "ap_session", kSecAttrSynchronizable as String: false]
    }
    func read() throws -> SessionCredential? {
        lock.lock(); defer { lock.unlock() }
        var query = query
        query[kSecReturnData as String] = true; query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = result as? Data else { throw PlatformError.storage }
        return try JSONDecoder().decode(SessionCredential.self, from: data)
    }
    func write(_ value: SessionCredential?) throws {
        lock.lock(); defer { lock.unlock() }
        guard let value else {
            let status = SecItemDelete(query as CFDictionary)
            guard status == errSecSuccess || status == errSecItemNotFound else { throw PlatformError.storage }
            return
        }
        let attributes: [String: Any] = [
            kSecValueData as String: try JSONEncoder().encode(value),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        ]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            guard SecItemAdd(query.merging(attributes) { _, new in new } as CFDictionary, nil) == errSecSuccess else {
                throw PlatformError.storage
            }
        } else if status != errSecSuccess { throw PlatformError.storage }
    }
}
