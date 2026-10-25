import Foundation
import Observation
import MeimeiCore

@MainActor @Observable
final class OCRController {
    private let api: any PlatformServing
    private var epoch = UUID()
    private(set) var tasks: [OCRTask] = []
    private(set) var busy = false
    private(set) var progress = 0.0
    var error: String?
    var onUnauthorized: (() -> Void)?
    init(api: any PlatformServing) { self.api = api }
    func reset() { epoch = UUID(); tasks = []; busy = false; progress = 0; error = nil }
    private func perform(_ operation: (UUID) async throws -> Void) async {
        guard !busy else { return }; let token = epoch; busy = true; error = nil
        defer { if token == epoch { busy = false } }
        do { try await operation(token) }
        catch {
            guard token == epoch, !Task.isCancelled else { return }
            if let value = error as? PlatformError, value.isUnauthorized { onUnauthorized?() }
            else { self.error = (error as? PlatformError)?.localizedDescription ?? "请求未确认，请先刷新记录核对；不会自动重新识别" }
        }
    }
    func load() async {
        await perform { token in let values = try await api.ocrTasks(); if token == epoch, !Task.isCancelled { tasks = values } }
    }
    func upload(_ jpeg: Data) async {
        await perform { token in
            progress = 0
            let value = try await api.recognizeHandwriting(jpeg) { [weak self] value in
                Task { @MainActor in if let self, token == self.epoch { self.progress = value } }
            }
            guard token == epoch, !Task.isCancelled else { return }
            tasks.removeAll { $0.id == value.id }; tasks.insert(value, at: 0)
        }
    }
    func delete(_ task: OCRTask) async {
        await perform { token in try await api.deleteOCRTask(id: task.id); if token == epoch { tasks.removeAll { $0.id == task.id } } }
    }
}
