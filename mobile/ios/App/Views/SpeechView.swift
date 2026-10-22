import SwiftUI
import MeimeiCore

struct SpeechView: View {
    let controller: SpeechController
    let message: ChatMessage
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            Form {
                Section("回答内容") { Text(String(message.content.prefix(180))).font(.callout).lineLimit(5) }
                if controller.configurationLoading { ProgressView("正在读取朗读配置…") }
                if let config = controller.configuration, config.available {
                    Section("朗读设置") {
                        Picker("音色", selection: Binding(get: { controller.voice }, set: controller.setVoice)) {
                            ForEach(config.voices) { Text($0.name).tag($0.id) }
                        }.pickerStyle(.menu).accessibilityIdentifier("speechVoicePicker")
                        Picker("语速", selection: Binding(get: { controller.speed }, set: controller.setSpeed)) {
                            ForEach(Array(Set([0.5, 0.75, 1, 1.25, 1.5, 2, controller.speed])).sorted(), id: \.self) { value in Text(String(format: "%g 倍", value)).tag(value) }
                        }.pickerStyle(.menu).accessibilityIdentifier("speechSpeedPicker")
                    }.disabled(controller.state == .loading || controller.configurationLoading)
                    Section {
                        switch controller.state {
                        case .loading:
                            ProgressView("正在生成并下载语音…")
                            Button("取消加载") { controller.stop() }
                        case .playing:
                            Button("暂停朗读", systemImage: "pause.fill") { controller.pause() }.accessibilityIdentifier("pauseSpeechButton")
                            Button("停止朗读") { controller.stop() }
                        case .paused:
                            Button("继续朗读", systemImage: "play.fill") { controller.resume() }.accessibilityIdentifier("resumeSpeechButton")
                            Button("停止朗读") { controller.stop() }
                        case .idle:
                            Button("播放回答", systemImage: "play.fill") { controller.play(messageID: message.id) }
                                .disabled(controller.needsConfirmation || controller.configurationLoading).accessibilityIdentifier("playSpeechButton")
                        }
                        Text("首次生成需要等待。切换音色或语速会停止当前播放；关闭页面或切到后台会停止朗读。")
                            .font(.footnote).foregroundStyle(.secondary)
                    }
                } else if let config = controller.configuration {
                    Text(!config.enabled ? "语音朗读暂未开启" : "语音服务暂不可用，请检查后台配置与可用音色")
                }
                if let error = controller.error { ErrorNotice(text: error) }
                Button("刷新朗读配置") { Task { controller.stop(); await controller.loadConfiguration(reload: true) } }.disabled(controller.configurationLoading)
            }.navigationTitle("回答朗读").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() } } }
                .task { controller.stop(); await controller.loadConfiguration(reload: true) }
                .onDisappear { controller.stop() }
                .alert("生成长文本语音？", isPresented: Binding(get: { controller.needsConfirmation }, set: { _ in })) {
                    Button("取消", role: .cancel) { controller.cancelLongText() }
                    Button("继续生成") { controller.confirmLongText() }
                } message: { Text("这条回答较长，生成语音需要更多时间，并会使用后台配置的语音服务。是否继续？") }
        }
    }
}
