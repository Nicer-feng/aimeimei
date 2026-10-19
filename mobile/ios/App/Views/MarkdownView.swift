import SwiftUI
import MeimeiCore

struct MarkdownView: View {
    private let blocks: [MarkdownBlock]
    init(content: String) { blocks = MarkdownBlocks.parse(content) }
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(blocks.enumerated()), id: \.offset) { _, block in
                switch block {
                case .paragraph(let text): inline(text)
                case .heading(let level, let text): inline(text).font(level <= 2 ? .title3.bold() : .headline)
                case .quote(let text):
                    HStack(alignment: .top, spacing: 10) { RoundedRectangle(cornerRadius: 2).fill(Brand.accent).frame(width: 3); inline(text).foregroundStyle(.secondary) }.fixedSize(horizontal: false, vertical: true)
                case .list(let text): inline(text).padding(.leading, 8)
                case .divider: Divider()
                case .code(let language, let code):
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text(language.isEmpty ? "代码" : language).font(.caption).foregroundStyle(.secondary)
                            Spacer()
                            Button("复制代码", systemImage: "doc.on.doc") { UIPasteboard.general.string = code }.labelStyle(.iconOnly).font(.caption)
                        }
                        ScrollView(.horizontal) { Text(code).font(.system(.callout, design: .monospaced)).textSelection(.enabled).fixedSize(horizontal: true, vertical: false) }
                    }.padding(12).background(Brand.background, in: RoundedRectangle(cornerRadius: 10))
                case .table(let rows):
                    ScrollView(.horizontal) {
                        VStack(alignment: .leading, spacing: 0) {
                            ForEach(Array(rows.enumerated()), id: \.offset) { rowIndex, row in
                                HStack(alignment: .top, spacing: 0) {
                                    ForEach(Array(row.enumerated()), id: \.offset) { _, cell in
                                        inline(cell).font(rowIndex == 0 ? .callout.bold() : .callout).frame(width: 150, alignment: .leading).padding(10)
                                    }
                                }.background(rowIndex.isMultiple(of: 2) ? Brand.background : .clear)
                                Divider()
                            }
                        }
                    }
                }
            }
        }.frame(maxWidth: .infinity, alignment: .leading)
    }
    private func inline(_ text: String) -> some View {
        let value = (try? AttributedString(markdown: text, options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace))) ?? AttributedString(text)
        return Text(value).textSelection(.enabled).fixedSize(horizontal: false, vertical: true)
    }
}
