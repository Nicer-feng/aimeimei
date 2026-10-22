import SwiftUI
import MeimeiCore

enum LibrarySection: String, CaseIterable, Identifiable {
    case favorites = "收藏", search = "搜索", prompts = "提示词"
    var id: String { rawValue }
}

struct LibraryView: View {
    let store: AppStore
    @Environment(\.dismiss) private var dismiss
    @State private var section: LibrarySection
    init(store: AppStore, initial: LibrarySection = .favorites) {
        self.store = store; _section = State(initialValue: initial)
    }
    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Picker("资料库分类", selection: $section) {
                    ForEach(LibrarySection.allCases) { Text($0.rawValue).tag($0) }
                }.pickerStyle(.segmented).padding().accessibilityIdentifier("librarySections")
                switch section {
                case .favorites: FavoritesPanel(store: store, onOpen: { dismiss() })
                case .search: SearchPanel(store: store, onOpen: { dismiss() })
                case .prompts: PromptsPanel(store: store, onApply: { dismiss() })
                }
            }
            .background(Brand.background)
            .navigationTitle("资料库").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("关闭") { dismiss() } } }
        }
    }
}

private struct FavoritesPanel: View {
    let store: AppStore
    let onOpen: () -> Void
    @State private var removing: FavoriteMessage?
    var body: some View {
        List {
            if let error = store.error { ErrorNotice(text: error) }
            if store.busy { ProgressView("正在读取收藏…") }
            if store.favorites.isEmpty && !store.busy {
                ContentUnavailableView("还没有收藏", systemImage: "star", description: Text("在回答上点星标，将内容收藏到这里"))
            }
            ForEach(store.favorites) { item in
                NavigationLink(value: item) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(item.conversationTitle).font(.headline)
                        Text(item.content).font(.subheadline).foregroundStyle(.secondary).lineLimit(3)
                    }.padding(.vertical, 4)
                }.accessibilityIdentifier("favorite-\(item.messageID)")
                    .disabled(store.locked)
                    .swipeActions { Button("取消收藏", role: .destructive) { removing = item } }
            }
        }
        .navigationDestination(for: FavoriteMessage.self) { FavoriteDetail(store: store, item: $0, onOpen: onOpen) }
        .task { await store.loadFavorites() }
        .refreshable { await store.loadFavorites() }
        .confirmationDialog("取消收藏？", isPresented: Binding(get: { removing != nil }, set: { if !$0 { removing = nil } }), titleVisibility: .visible) {
            Button("取消收藏", role: .destructive) {
                if let item = removing { Task { await store.removeFavorite(item) } }; removing = nil
            }
        }
    }
}

private struct FavoriteDetail: View {
    let store: AppStore
    let item: FavoriteMessage
    let onOpen: () -> Void
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text(item.conversationTitle).font(.headline)
                if !item.canOpenConversation {
                    Text("原会话已删除，收藏内容仍保留在这里。").font(.footnote).foregroundStyle(.secondary)
                }
                MarkdownView(content: item.content)
                if let error = store.error { ErrorNotice(text: error) }
                Button("返回原对话", systemImage: "bubble.left") {
                    Task { if await store.openMessage(conversationID: item.conversationID, messageID: item.messageID) { onOpen() } }
                }.buttonStyle(.borderedProminent).disabled(store.locked || !item.canOpenConversation)
                    .accessibilityIdentifier("openFavoriteOrigin")
                ShareLink(item: item.content) { Label("分享收藏内容", systemImage: "square.and.arrow.up") }
            }.padding().frame(maxWidth: 800, alignment: .leading).frame(maxWidth: .infinity)
        }.navigationTitle("收藏内容").navigationBarTitleDisplayMode(.inline)
    }
}

private struct SearchPanel: View {
    let store: AppStore
    let onOpen: () -> Void
    @State private var query = ""
    @State private var snapshot: FavoriteMessage?
    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
                TextField("搜索会话、消息和收藏", text: $query).submitLabel(.search)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .accessibilityIdentifier("globalSearchField")
                if !query.isEmpty { Button("清空", systemImage: "xmark.circle.fill") { query = "" }.labelStyle(.iconOnly) }
            }.padding(12).background(.background, in: RoundedRectangle(cornerRadius: 12)).padding(.horizontal).padding(.bottom, 8)
            List {
                if let error = store.error { ErrorNotice(text: error) }
                if let error = store.searchError {
                    ErrorNotice(text: error)
                    Button("重新搜索") { Task { await store.searchLibrary(query) } }
                }
                if store.searching { ProgressView("正在搜索…") }
                if store.searchResults.isEmpty && !store.searching && store.searchError == nil {
                    ContentUnavailableView("没有找到内容", systemImage: "magnifyingglass", description: Text("换个关键词，搜索你的历史消息和收藏"))
                }
                ForEach(store.searchResults) { item in
                    Button {
                        Task {
                            if item.type == "favorite" && item.conversationID.isEmpty {
                                snapshot = await store.favoriteSnapshot(resultID: item.id)
                                if snapshot == nil && store.error == nil { store.error = "该收藏已移除，请刷新后重试" }
                            } else if await store.openMessage(conversationID: item.conversationID, messageID: item.messageID) { onOpen() }
                        }
                    } label: {
                        VStack(alignment: .leading, spacing: 6) {
                            HStack { Text(item.title).font(.headline).foregroundStyle(Color.primary); Spacer(); Text(item.label).font(.caption).foregroundStyle(Color.secondary) }
                            Text(item.snippet).font(.subheadline).foregroundStyle(Color.secondary).lineLimit(4)
                        }.padding(.vertical, 4)
                    }.buttonStyle(.plain).disabled(store.locked).accessibilityIdentifier("search-\(item.id)")
                }
            }.scrollDismissesKeyboard(.interactively)
        }
        .task(id: query) { await store.searchLibrary(query) }
        .onDisappear { store.resetSearch() }
        .navigationDestination(item: $snapshot) { FavoriteDetail(store: store, item: $0, onOpen: onOpen) }
    }
}

private struct PromptsPanel: View {
    let store: AppStore
    let onApply: () -> Void
    var body: some View {
        List {
            if let error = store.error { ErrorNotice(text: error) }
            if store.busy { ProgressView("正在读取提示词…") }
            if store.prompts.isEmpty && !store.busy {
                ContentUnavailableView("还没有提示词", systemImage: "text.book.closed", description: Text("Web 端配置的常用模板会出现在这里"))
            }
            ForEach(store.prompts) { item in
                NavigationLink(value: item) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(item.title).font(.headline)
                        Text(item.content).font(.subheadline).foregroundStyle(.secondary).lineLimit(3)
                    }.padding(.vertical, 4)
                }.disabled(store.locked).accessibilityIdentifier("prompt-\(item.id)")
            }
        }
        .task { await store.loadPrompts() }
        .refreshable { await store.loadPrompts() }
        .navigationDestination(for: PromptTemplate.self) { PromptDetail(store: store, item: $0, onApply: onApply) }
    }
}

private struct PromptDetail: View {
    let store: AppStore
    let item: PromptTemplate
    let onApply: () -> Void
    @State private var confirmReplace = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                Text(item.title).font(.title2.bold())
                Text(item.content).textSelection(.enabled)
                Text("填入后可以继续编辑，点击发送才会提交给槑槑。").font(.footnote).foregroundStyle(.secondary)
                Button("填入输入框", systemImage: "arrow.down.doc") {
                    if store.draft.text.isEmpty { if store.applyPrompt(item) { onApply() } }
                    else { confirmReplace = true }
                }.buttonStyle(.borderedProminent).disabled(store.locked || store.pending != nil)
                    .accessibilityIdentifier("applyPromptButton")
            }.padding().frame(maxWidth: 800, alignment: .leading).frame(maxWidth: .infinity)
        }.navigationTitle("提示词预览").navigationBarTitleDisplayMode(.inline)
        .alert("替换当前草稿？", isPresented: $confirmReplace) {
            Button("保留草稿", role: .cancel) {}
            Button("替换草稿", role: .destructive) { if store.applyPrompt(item, replace: true) { onApply() } }
        } message: { Text("输入框里已有未发送内容。替换只修改草稿，不会自动发送。") }
    }
}
