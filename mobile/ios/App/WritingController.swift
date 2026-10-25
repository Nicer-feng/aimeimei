import Foundation
import Observation
import MeimeiCore

@MainActor @Observable
final class WritingController {
    private let api: any PlatformServing
    private var epoch = UUID()
    private(set) var conversationID = ""
    private(set) var state: WritingState?
    private(set) var preview: WritingVersion?
    private(set) var enabled = false
    private(set) var busy = false
    var error: String?
    var onUnauthorized: (() -> Void)?
    init(api: any PlatformServing) { self.api = api }
    func reset() { epoch = UUID(); conversationID = ""; state = nil; preview = nil; enabled = false; busy = false; error = nil }
    private func perform(_ operation: (UUID) async throws -> Void) async -> Bool {
        guard !busy else { return false }; let token = epoch; busy = true; error = nil
        defer { if token == epoch { busy = false } }
        do { try await operation(token); return token == epoch && !Task.isCancelled }
        catch {
            guard token == epoch, !Task.isCancelled else { return false }
            if let value = error as? PlatformError, value.isUnauthorized { onUnauthorized?() }
            else if case PlatformError.http(409, _) = error { self.error = "本单已在其他窗口更新或正在生成，请重新加载后核对；本次编辑未自动覆盖" }
            else { self.error = (error as? PlatformError)?.localizedDescription ?? "请求未确认，请重新加载核对；不会自动保存第二次" }
            return false
        }
    }
    func load(conversationID: String) async -> Bool {
        if self.conversationID != conversationID { reset(); self.conversationID = conversationID }
        return await perform { token in
            let value = try await api.writing(conversationID: conversationID, versionID: nil)
            guard token == epoch, !Task.isCancelled else { return }
            state = value.writing; enabled = value.enabled ?? enabled; preview = nil
        }
    }
    func update(_ command: WritingCommand) async -> Bool {
        guard let state, !conversationID.isEmpty else { return false }
        return await perform { token in
            let value = try await api.updateWriting(conversationID: conversationID, revision: state.revision, command: command)
            guard token == epoch, !Task.isCancelled else { return }
            self.state = value.writing
            if case .enabled(let flag) = command { enabled = flag }
            if let flag = value.enabled { enabled = flag }
        }
    }
    func loadVersion(_ id: Int64) async {
        _ = await perform { token in
            let value = try await api.writing(conversationID: conversationID, versionID: id)
            guard token == epoch, !Task.isCancelled else { return }
            preview = value.writing.selected
        }
    }
}
