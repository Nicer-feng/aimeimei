import Foundation
import Observation
import AVFAudio
import MeimeiCore

@MainActor protocol AudioOutput: AnyObject {
    var onFinish: ((Bool) -> Void)? { get set }
    var onPause: (() -> Void)? { get set }
    func play(_ data: Data) throws
    func pause()
    func resume() throws
    func stop()
}

@MainActor final class DeviceAudioOutput: NSObject, AudioOutput, AVAudioPlayerDelegate {
    var onFinish: ((Bool) -> Void)?
    var onPause: (() -> Void)?
    private var player: AVAudioPlayer?
    private var observers: [NSObjectProtocol] = []
    override init() {
        super.init()
        #if os(iOS)
        observers.append(NotificationCenter.default.addObserver(forName: AVAudioSession.interruptionNotification, object: nil, queue: .main) { [weak self] notification in
            guard let kind = notification.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt,
                  kind == AVAudioSession.InterruptionType.began.rawValue else { return }
            Task { @MainActor [weak self] in self?.onPause?() }
        })
        observers.append(NotificationCenter.default.addObserver(forName: AVAudioSession.routeChangeNotification, object: nil, queue: .main) { [weak self] notification in
            guard let reason = notification.userInfo?[AVAudioSessionRouteChangeReasonKey] as? UInt,
                  reason == AVAudioSession.RouteChangeReason.oldDeviceUnavailable.rawValue else { return }
            Task { @MainActor [weak self] in self?.onPause?() }
        })
        #endif
    }
    deinit { observers.forEach(NotificationCenter.default.removeObserver) }
    private func activate() throws {
        #if os(iOS)
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.playback, mode: .spokenAudio)
        try session.setActive(true)
        #endif
    }
    private func deactivate() {
        #if os(iOS)
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        #endif
    }
    func play(_ data: Data) throws {
        stop()
        do {
            let value = try AVAudioPlayer(data: data); player = value; value.delegate = self
            try activate()
            guard value.prepareToPlay(), value.play() else { throw PlatformError.media("语音无法播放，请重试") }
        } catch { stop(); throw error }
    }
    func pause() { player?.pause(); deactivate() }
    func resume() throws {
        try activate()
        guard player?.play() == true else { deactivate(); throw PlatformError.media("语音无法继续，请重新播放") }
    }
    func stop() { player?.delegate = nil; player?.stop(); player = nil; deactivate() }
    nonisolated func audioPlayerDidFinishPlaying(_ player: AVAudioPlayer, successfully flag: Bool) {
        Task { @MainActor [weak self] in
            guard let self, self.player === player else { return }
            self.stop(); self.onFinish?(flag)
        }
    }
    nonisolated func audioPlayerDecodeErrorDidOccur(_ player: AVAudioPlayer, error: Error?) {
        Task { @MainActor [weak self] in
            guard let self, self.player === player else { return }
            self.stop(); self.onFinish?(false)
        }
    }
}

@MainActor @Observable final class SpeechController {
    enum State { case idle, loading, playing, paused }
    private struct Request { let messageID: Int64; let voice: String; let speed: Double }
    private(set) var configuration: SpeechConfiguration?
    private(set) var configurationLoading = false
    private(set) var voice = ""
    private(set) var speed = 1.0
    private(set) var state = State.idle
    private(set) var needsConfirmation = false
    private(set) var error: String?
    @ObservationIgnored var onUnauthorized: (() -> Void)?
    @ObservationIgnored private let api: any PlatformServing
    @ObservationIgnored private let output: any AudioOutput
    @ObservationIgnored private var operation: Task<Void, Never>?
    @ObservationIgnored private var token = UUID()
    @ObservationIgnored private var configToken = UUID()
    @ObservationIgnored private var pending: Request?
    init(api: any PlatformServing, output: any AudioOutput) {
        self.api = api; self.output = output
        output.onFinish = { [weak self] success in
            self?.state = .idle
            if !success { self?.error = "音频播放失败，请重新播放" }
        }
        output.onPause = { [weak self] in self?.pause() }
    }
    func loadConfiguration(reload: Bool = false) async {
        guard !configurationLoading, reload || configuration == nil else { return }
        let id = UUID(); configToken = id; configurationLoading = true; error = nil
        if reload { configuration = nil }
        defer { if configToken == id { configurationLoading = false } }
        do {
            let value = try await api.speechConfiguration()
            guard configToken == id else { return }
            configuration = value
            voice = value.voices.contains(where: { $0.id == value.defaultVoice }) ? value.defaultVoice : value.voices.first?.id ?? ""
            speed = value.defaultSpeed.isFinite ? min(2, max(0.5, value.defaultSpeed)) : 1
        } catch {
            guard configToken == id else { return }
            if let failure = error as? PlatformError, failure.isUnauthorized { onUnauthorized?(); return }
            self.error = "无法读取朗读配置，请检查网络后重试"
        }
    }
    func setVoice(_ value: String) { stop(); voice = value }
    func setSpeed(_ value: Double) { guard value.isFinite else { return }; stop(); speed = min(2, max(0.5, value)) }
    func play(messageID: Int64) {
        guard configuration?.available == true, configuration?.voices.contains(where: { $0.id == voice }) == true, messageID > 0 else { return }
        stop(); state = .loading
        let request = Request(messageID: messageID, voice: voice, speed: speed); let id = token
        operation = Task { [weak self] in
            guard let self else { return }
            do {
                let prepared = try await api.prepareSpeech(messageID: messageID, voice: request.voice, speed: request.speed)
                try Task.checkCancellation(); guard token == id else { return }
                if prepared.longText && !prepared.cached {
                    pending = request; needsConfirmation = true; state = .idle; return
                }
                try await download(request, token: id)
            } catch { fail(error, token: id) }
        }
    }
    func confirmLongText() {
        guard let request = pending else { return }
        needsConfirmation = false; pending = nil; state = .loading; let id = token
        operation = Task { [weak self] in
            guard let self else { return }
            do { try await download(request, token: id) } catch { fail(error, token: id) }
        }
    }
    func cancelLongText() { pending = nil; needsConfirmation = false }
    private func download(_ request: Request, token id: UUID) async throws {
        let data = try await api.speechAudio(messageID: request.messageID, voice: request.voice, speed: request.speed)
        try Task.checkCancellation(); guard token == id else { return }
        try output.play(data); state = .playing
    }
    private func fail(_ failure: Error, token id: UUID) {
        guard token == id else { return }
        state = .idle
        if failure is CancellationError || (failure as? URLError)?.code == .cancelled { return }
        if let platform = failure as? PlatformError, platform.isUnauthorized { onUnauthorized?() }
        error = (failure as? PlatformError)?.localizedDescription ?? "朗读失败，请检查网络后重试"
    }
    func pause() { guard state == .playing else { return }; output.pause(); state = .paused }
    func resume() {
        guard state == .paused else { return }
        do { try output.resume(); state = .playing } catch { output.stop(); state = .idle; self.error = "语音无法继续，请重新播放" }
    }
    func stop() {
        token = UUID(); operation?.cancel(); operation = nil
        output.stop(); state = .idle; error = nil; cancelLongText()
    }
    func reset() { stop(); configToken = UUID(); configuration = nil; configurationLoading = false; voice = ""; speed = 1 }
}
