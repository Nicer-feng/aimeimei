import SwiftUI
import MeimeiCore

struct HistoryView: View {
    let store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var query = ""
    @State private var renaming: Conversation?
    @State private var deleting: Conversation?
    @State private var title = ""
    private var filtered: [Conversation] {
        store.conversations.filter { query.isEmpty || $0.title.localizedCaseInsensitiveContains(query) }
    }
    private var showDaily: Bool { store.daily.owner != nil && (query.isEmpty || "研发日报".localizedCaseInsensitiveContains(query)) }
    var body: some View {
        NavigationStack {
            List {
                if let error = store.error { ErrorNotice(text: error).listRowSeparator(.hidden) }
                if showDaily {
                    Button {
                        dismiss()
                        Task { try? await Task.sleep(for: .milliseconds(350)); store.daily.open() }
                    } label: {
                        HStack(spacing: 12) {
                            Image("Avatar").resizable().scaledToFit().frame(width: 36, height: 36)
                            VStack(alignment: .leading, spacing: 4) {
                                Text("研发日报").foregroundStyle(.primary)
                                Label("已置顶", systemImage: "pin.fill").font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if store.daily.unread > 0 { Text(String(store.daily.unread)).font(.caption.bold()).foregroundStyle(Brand.accent) }
                        }.padding(.vertical, 6)
                    }.accessibilityIdentifier("dailyReportEntry")
                }
                ForEach(filtered) { item in
                    Button {
                        Task { await store.select(item); if store.selected?.id == item.id { dismiss() } }
                    } label: {
                        HStack(spacing: 12) {
                            Image(systemName: item.pinned ? "pin.fill" : "bubble.left").foregroundStyle(Brand.accent)
                            VStack(alignment: .leading, spacing: 4) {
                                Text(item.title).lineLimit(2).foregroundStyle(.primary)
                                Text(item.modelName).font(.caption).foregroundStyle(.secondary)
                            }
                            Spacer()
                            if store.selected?.id == item.id { Image(systemName: "checkmark").foregroundStyle(Brand.accent) }
                        }.padding(.vertical, 6)
                    }
                    .contextMenu {
                        Button(item.pinned ? "取消置顶" : "置顶", systemImage: item.pinned ? "pin.slash" : "pin") {
                            Task { await store.togglePin(item) }
                        }
                        Button("重命名", systemImage: "pencil") { title = item.title; renaming = item }
                        Button("删除", systemImage: "trash", role: .destructive) { deleting = item }
                    }
                    .swipeActions {
                        Button("删除", role: .destructive) { deleting = item }
                        Button("重命名") { title = item.title; renaming = item }.tint(Brand.accent)
                    }
                }
            }
            .overlay {
                if filtered.isEmpty && !store.busy && !showDaily {
                    ContentUnavailableView(query.isEmpty ? "还没有聊天" : "没有找到聊天", systemImage: "bubble.left.and.bubble.right", description: Text(query.isEmpty ? "发送第一条消息后，对话会出现在这里" : "换个关键词试试"))
                        .allowsHitTesting(false)
                }
            }
            .accessibilityIdentifier("historyList")
            .searchable(text: $query, prompt: "搜索聊天标题")
            .refreshable { await store.refresh() }
            .navigationTitle("历史聊天").navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() } }
                ToolbarItem(placement: .primaryAction) {
                    Button("新聊天", systemImage: "square.and.pencil") { store.newChat(); dismiss() }.disabled(store.locked)
                }
            }
            .disabled(store.locked)
            .alert("重命名聊天", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
                TextField("聊天标题", text: $title)
                Button("取消", role: .cancel) { renaming = nil }
                Button("保存") {
                    if let item = renaming { Task { await store.rename(item, title: title) } }
                    renaming = nil
                }
            }
            .confirmationDialog("删除后将从历史列表移除", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
                Button("删除聊天", role: .destructive) {
                    if let item = deleting { Task { await store.delete(item) } }; deleting = nil
                }
            }
        }
    }
}
