import SwiftUI
import UniformTypeIdentifiers
import MeimeiCore

struct ImportedDocument: Sendable {
    let data: Data
    let filename: String
    static func read(_ url: URL) throws -> ImportedDocument {
        let accessed = url.startAccessingSecurityScopedResource()
        defer { if accessed { url.stopAccessingSecurityScopedResource() } }
        var coordinationError: NSError?
        var result: Result<ImportedDocument, Error>?
        NSFileCoordinator().coordinate(readingItemAt: url, options: .withoutChanges, error: &coordinationError) { location in
            result = Result {
                let values = try location.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
                guard values.isRegularFile == true else { throw PlatformError.media("请选择一个文件") }
                try DocumentLimits.validate(filename: url.lastPathComponent, size: values.fileSize ?? 0)
                let data = try Data(contentsOf: location)
                try DocumentLimits.validate(filename: url.lastPathComponent, size: data.count)
                return ImportedDocument(data: data, filename: url.lastPathComponent)
            }
        }
        if let coordinationError { throw coordinationError }
        guard let result else { throw PlatformError.media("无法读取文件，请重新选择") }
        return try result.get()
    }
}

struct DocumentsView: View {
    let store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var showImporter = false
    @State private var importing = false
    @State private var importTask: Task<Void, Never>?
    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button("从文件选择材料", systemImage: "doc.badge.plus") { showImporter = true }
                        .disabled(store.locked || importing || store.draft.documents.count >= 5 || store.failedDocument != nil)
                        .accessibilityIdentifier("importDocumentButton")
                    Text("支持 PDF、Word、Excel、PPT、文本和图片。单份最多 50MB，图片最多 20MB；最多引用 5 份。上传后需等待解析完成。")
                        .font(.footnote).foregroundStyle(.secondary)
                    Text("材料仅用于本条问题。移除附件不会删除 Web 中的文件。")
                        .font(.footnote).foregroundStyle(.secondary)
                    #if DEBUG
                    if ProcessInfo.processInfo.arguments.contains("--ui-testing") {
                        Button("测试材料") { Task { await store.addDocument(Data("离线测试材料".utf8), filename: "项目说明.txt") } }
                            .disabled(store.locked || importing).accessibilityIdentifier("demoDocumentButton")
                    }
                    #endif
                }
                if importing { ProgressView("正在读取所选文件…") }
                if let name = store.documentUploadingName {
                    Section("正在上传") { Text(name); ProgressView(value: store.documentUploadProgress) }
                }
                if let item = store.failedDocument {
                    Section("上传失败") {
                        Text(item.filename)
                        Button("重试上传") { Task { await store.retryDocument() } }.disabled(store.locked)
                        Button("移除失败的上传") { store.discardFailedDocument() }.disabled(store.locked)
                    }
                }
                if let error = store.error { ErrorNotice(text: error) }
                Section("我的材料 · 已选择 \(store.draft.documents.count)/5") {
                    if store.busy && store.documents.isEmpty { ProgressView("正在读取材料列表…") }
                    else if store.documents.isEmpty { Text("还没有材料，可从文件选择上传").foregroundStyle(.secondary) }
                    ForEach(store.documents) { item in
                        Button {
                            if store.draft.documents.contains(where: { $0.id == item.id }) { store.removeDocument(item.id) }
                            else { _ = store.chooseDocument(item) }
                        } label: {
                            HStack(alignment: .top) {
                                VStack(alignment: .leading, spacing: 6) {
                                    Text(item.filename).foregroundStyle(.primary)
                                    Text(item.statusLabel).font(.caption).foregroundStyle(item.ready ? Color.secondary : Color.orange)
                                    if !item.errorMessage.isEmpty { Text(String(item.errorMessage.prefix(300))).font(.caption).foregroundStyle(.secondary) }
                                }
                                Spacer()
                                Image(systemName: store.draft.documents.contains(where: { $0.id == item.id }) ? "checkmark.circle.fill" : "circle")
                            }
                        }.buttonStyle(.plain).disabled(store.locked || importing || store.pending != nil)
                            .accessibilityIdentifier("document-\(item.id)")
                    }
                }
            }.navigationTitle("文件问答").navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) { Button("刷新") { Task { await store.refreshDocuments(includeFailed: true); await store.loadDocuments() } }.disabled(store.locked) }
                    ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() } }
                }
                .task { await store.loadDocuments() }
                .onDisappear { if store.documentUploadingName == nil { importTask?.cancel() } }
                .fileImporter(isPresented: $showImporter, allowedContentTypes: [.data], allowsMultipleSelection: true) { result in
                    let context = store.attachmentContext
                    importTask = Task {
                        importing = true; store.setDocumentImporting(true, context: context)
                        defer { importing = false; store.setDocumentImporting(false, context: context) }
                        do {
                            let urls = try result.get()
                            guard urls.count <= 5 - store.draft.documents.count else { throw PlatformError.media("单次最多引用 5 份材料，请减少所选文件") }
                            for url in urls {
                                let file = try await Task.detached { try ImportedDocument.read(url) }.value
                                try Task.checkCancellation()
                                await store.addDocument(file.data, filename: file.filename, context: context)
                                if store.failedDocument != nil || context != store.attachmentContext { break }
                            }
                        } catch {
                            if (error as NSError).domain == NSCocoaErrorDomain && (error as NSError).code == NSUserCancelledError { return }
                            if !Task.isCancelled { store.error = (error as? PlatformError)?.localizedDescription ?? "文件读取已取消或失败，请重新选择" }
                        }
                    }
                }
        }
    }
}

struct DraftDocumentsView: View {
    let store: AppStore
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if store.importingDocuments && store.documentUploadingName == nil { ProgressView("正在读取材料…").font(.caption) }
            ScrollView(.horizontal) {
                HStack(spacing: 10) {
                    ForEach(store.draft.documents) { item in
                        HStack {
                            Image(systemName: "doc.text")
                            VStack(alignment: .leading, spacing: 4) {
                                Text(item.filename).font(.caption).lineLimit(1)
                                Text(item.statusLabel).font(.caption2).foregroundStyle(item.ready ? Color.secondary : Color.orange)
                            }.frame(width: 125, alignment: .leading)
                            Button("移除材料", systemImage: "xmark.circle") { store.removeDocument(item.id) }
                                .labelStyle(.iconOnly).disabled(store.locked || store.pending != nil).accessibilityIdentifier("removeDocument-\(item.id)")
                        }.padding(10).background(Color.secondary.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
                    }
                }
            }
            if store.draft.documents.contains(where: { !$0.ready }) {
                HStack {
                    Text("解析完成后才能发送，暂时离开也可稍后回来刷新。")
                    Spacer()
                    Button("刷新解析状态") { Task { await store.refreshDocuments(includeFailed: true) } }
                        .disabled(store.locked).accessibilityIdentifier("refreshDocumentsButton")
                }.font(.caption)
            }
            if let name = store.documentUploadingName { Text("正在上传：\(name)").font(.caption); ProgressView(value: store.documentUploadProgress) }
            if let item = store.failedDocument {
                HStack {
                    Text("\(item.filename) 上传失败").lineLimit(1)
                    Button("重试上传") { Task { await store.retryDocument() } }.disabled(store.locked)
                    Button("移除") { store.discardFailedDocument() }.disabled(store.locked)
                }.font(.caption)
            }
        }
    }
}
