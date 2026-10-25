import Foundation
import Observation
import MeimeiCore

@MainActor @Observable
final class MediaController {
    private let api: any PlatformServing
    private var epoch = UUID()
    private(set) var tasks: [MediaTask] = []
    private(set) var busy = false
    private(set) var progress = 0.0
    var error: String?
    var onUnauthorized: (() -> Void)?
    init(api: any PlatformServing) { self.api = api }
    func reset() { epoch = UUID(); tasks = []; busy = false; progress = 0; error = nil }
    @discardableResult private func perform(_ operation: (UUID) async throws -> Void) async -> Bool {
        guard !busy else { return false }; let token = epoch; busy = true; error = nil
        defer { if token == epoch { busy = false } }
        do { try await operation(token); return token == epoch && !Task.isCancelled }
        catch {
            guard token == epoch, !Task.isCancelled else { return false }
            if let value = error as? PlatformError, value.isUnauthorized { onUnauthorized?() }
            else { self.error = (error as? PlatformError)?.localizedDescription ?? "请求未确认，请刷新核对任务；不会自动重新提交" }
            return false
        }
    }
    private func upsert(_ value: MediaTask) { tasks.removeAll { $0.id == value.id }; tasks.insert(value, at: 0) }
    func load() async {
        await perform { token in let values = try await api.mediaTasks(); if token == epoch, !Task.isCancelled { tasks = values } }
    }
    func upload(file: URL, filename: String) async {
        defer { try? FileManager.default.removeItem(at: file) }
        await perform { token in
            progress = 0
            let value = try await api.uploadMedia(file: file, filename: filename) { [weak self] value in
                Task { @MainActor in if let self, token == self.epoch { self.progress = value } }
            }
            if token == epoch, !Task.isCancelled { upsert(value) }
        }
    }
    func refresh(_ id: String) async {
        await perform { token in let value = try await api.refreshMedia(id: id); if token == epoch, !Task.isCancelled { upsert(value) } }
    }
    func delete(_ task: MediaTask) async {
        await perform { token in try await api.deleteMedia(id: task.id); if token == epoch { tasks.removeAll { $0.id == task.id } } }
    }
    func conversation(id: String, modelID: String) async -> Conversation? {
        var result: Conversation?
        let success = await perform { token in
            let value = try await api.mediaConversation(id: id, modelID: modelID)
            guard token == epoch, !Task.isCancelled else { return }
            upsert(value.task); result = value.conversation
        }
        return success ? result : nil
    }
}
