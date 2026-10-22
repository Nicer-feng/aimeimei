import SwiftUI
import ImageIO
import UniformTypeIdentifiers
import MeimeiCore

enum ChatImagePreparation {
    static func jpeg(_ data: Data) throws -> Data {
        guard data.count <= 30 * 1024 * 1024,
              let source = CGImageSourceCreateWithData(data as CFData, nil),
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: 2048
              ] as CFDictionary) else { throw PlatformError.media("无法读取图片，请选择另一张图片") }
        let result = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(result, UTType.jpeg.identifier as CFString, 1, nil) else {
            throw PlatformError.media("图片处理失败，请重新选择")
        }
        CGImageDestinationAddImage(destination, image, [kCGImageDestinationLossyCompressionQuality: 0.82] as CFDictionary)
        guard CGImageDestinationFinalize(destination) else { throw PlatformError.media("图片处理失败，请重新选择") }
        return result as Data
    }
}

struct ChatImageTile: View {
    let store: AppStore
    let image: ChatImage
    @State private var loaded: UIImage?
    @State private var failed = false
    @State private var showPreview = false
    @State private var retry = 0
    var body: some View {
        Button {
            if failed { retry += 1 } else if loaded != nil { showPreview = true }
        } label: {
            Group {
                if let loaded { Image(uiImage: loaded).resizable().scaledToFill() }
                else if failed { Label("重试", systemImage: "arrow.clockwise").font(.caption) }
                else { ProgressView() }
            }.frame(width: 88, height: 88).background(.quaternary).clipShape(RoundedRectangle(cornerRadius: 12))
        }.buttonStyle(.plain).disabled(loaded == nil && !failed).accessibilityLabel(failed ? "重新加载图片" : "预览图片")
            .accessibilityIdentifier("image-\(image.id)")
            .task(id: retry) {
                failed = false
                do {
                    let data = try await store.imageData(image)
                    try Task.checkCancellation()
                    guard let value = UIImage(data: data) else { failed = true; return }
                    loaded = value
                } catch { if !Task.isCancelled { failed = true } }
            }
            .sheet(isPresented: $showPreview) {
                if let loaded { ImagePreview(image: loaded) }
            }
    }
}

private struct ImagePreview: View {
    let image: UIImage
    @State private var scale = 1.0
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            GeometryReader { size in
                ScrollView([.horizontal, .vertical]) {
                    Image(uiImage: image).resizable().scaledToFit()
                        .frame(width: size.size.width * scale, height: size.size.height * scale)
                }
            }.background(Color.black.opacity(0.95))
                .navigationTitle("图片预览").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) { Button(scale == 1 ? "放大" : "适应屏幕") { scale = scale == 1 ? 2.5 : 1 } }
                    ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() } }
                }
        }
    }
}

struct ChatSourcesView: View {
    let sources: [ChatSource]
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            List(Array(sources.enumerated()), id: \.offset) { index, source in
                VStack(alignment: .leading, spacing: 8) {
                    Text("\(source.position > 0 ? source.position : index + 1). \(source.title)").font(.headline)
                    if !source.snippet.isEmpty { Text(source.snippet).font(.subheadline).foregroundStyle(.secondary).textSelection(.enabled) }
                    if let url = source.safeURL {
                        Text(url.host ?? "").font(.caption).foregroundStyle(.secondary)
                        Link("打开原文", destination: url).accessibilityIdentifier("sourceLink-\(index)")
                    } else { Text("该来源没有可打开的网页地址").font(.caption).foregroundStyle(.secondary) }
                }.padding(.vertical, 6)
            }.navigationTitle("联网来源").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() } } }
        }
    }
}

struct ChatCamera: UIViewControllerRepresentable {
    let onImage: (Data?) -> Void
    func makeCoordinator() -> Coordinator { Coordinator(onImage: onImage) }
    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController(); picker.sourceType = .camera; picker.delegate = context.coordinator
        return picker
    }
    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}
    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let onImage: (Data?) -> Void
        init(onImage: @escaping (Data?) -> Void) { self.onImage = onImage }
        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) { onImage(nil) }
        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]) {
            onImage((info[.originalImage] as? UIImage)?.jpegData(compressionQuality: 0.9))
        }
    }
}
