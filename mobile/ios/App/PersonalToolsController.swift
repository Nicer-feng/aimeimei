import Foundation
import Observation
import MeimeiCore

@MainActor @Observable
final class PersonalToolsController {
    private let api: any PlatformServing
    private var epoch = UUID()
    private(set) var profiles: [AIProfile] = []
    private(set) var shares: [ConversationShare] = []
    private(set) var createdShare: ConversationShare?
    private(set) var busy = false
    var error: String?
    var onUnauthorized: (() -> Void)?
    init(api: any PlatformServing) { self.api = api }
    func reset() { epoch = UUID(); profiles = []; shares = []; createdShare = nil; busy = false; error = nil }
    func clearShareContext() { reset() }
    private func perform(_ operation: (UUID) async throws -> Void) async -> Bool {
        guard !busy else { return false }
        let token = epoch; busy = true; error = nil
        defer { if token == epoch { busy = false } }
        do { try await operation(token); return token == epoch && !Task.isCancelled }
        catch {
            guard token == epoch, !Task.isCancelled else { return false }
            if let value = error as? PlatformError, value.isUnauthorized { onUnauthorized?() }
            else { self.error = (error as? PlatformError)?.localizedDescription ?? "网络操作失败，请刷新核对后重试" }
            return false
        }
    }
    func loadProfiles() async {
        _ = await perform { token in let values = try await api.profiles(); if token == epoch, !Task.isCancelled { profiles = values } }
    }
    func save(_ value: AIProfile) async -> Bool {
        await perform { token in
            let saved = try await api.saveProfile(value)
            guard token == epoch, !Task.isCancelled else { return }
            profiles.removeAll { $0.id == saved.id }; profiles.append(saved)
            profiles.sort { $0.sort_order < $1.sort_order }
        }
    }
    func delete(_ value: AIProfile) async {
        _ = await perform { token in try await api.deleteProfile(id: value.id); if token == epoch { profiles.removeAll { $0.id == value.id } } }
    }
    func loadShares(conversationID: String) async {
        _ = await perform { token in let values = try await api.shares(conversationID: conversationID); if token == epoch, !Task.isCancelled { shares = values } }
    }
    func create(conversationID: String, scope: ShareScope, messageID: Int64?, expires: Int) async {
        _ = await perform { token in
            let value = try await api.createShare(conversationID: conversationID, scope: scope, messageID: messageID, expiresIn: expires)
            guard token == epoch, !Task.isCancelled else { return }
            createdShare = value; shares.insert(value, at: 0)
        }
    }
    func revoke(_ share: ConversationShare) async {
        _ = await perform { token in
            try await api.revokeShare(id: share.id)
            guard token == epoch else { return }
            shares = shares.map { $0.id == share.id ? ConversationShare(id: $0.id, scope: $0.scope, title: $0.title, expires_at: $0.expires_at, active: false, access_count: $0.access_count) : $0 }
            if createdShare?.id == share.id { createdShare = nil }
        }
    }
}
