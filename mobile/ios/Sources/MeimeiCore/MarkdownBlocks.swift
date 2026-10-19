import Foundation

public enum MarkdownBlock: Equatable {
    case paragraph(String), heading(Int, String), quote(String), list(String)
    case code(String, String), table([[String]]), divider
}

/// 首版覆盖常用 Markdown 块，所有内容只作为原生文本显示，不执行 HTML。
public enum MarkdownBlocks {
    public static func parse(_ content: String) -> [MarkdownBlock] {
        let lines = content.replacingOccurrences(of: "\r\n", with: "\n").components(separatedBy: "\n")
        var result: [MarkdownBlock] = []; var paragraph: [String] = []; var index = 0
        func flush() {
            if !paragraph.isEmpty { result.append(.paragraph(paragraph.joined(separator: "\n"))); paragraph = [] }
        }
        while index < lines.count {
            let line = lines[index]; let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("```") || trimmed.hasPrefix("~~~") {
                flush(); let fence = String(trimmed.prefix(3)); let language = String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces)
                var code: [String] = []; index += 1
                while index < lines.count && !lines[index].trimmingCharacters(in: .whitespaces).hasPrefix(fence) {
                    code.append(lines[index]); index += 1
                }
                result.append(.code(language, code.joined(separator: "\n")))
            } else if trimmed.isEmpty { flush() }
            else if trimmed == "---" || trimmed == "***" || trimmed == "___" { flush(); result.append(.divider) }
            else if index + 1 < lines.count && line.contains("|") && isTableSeparator(lines[index + 1]) {
                flush(); var rows = [cells(line)]; index += 2
                while index < lines.count && lines[index].contains("|") && !lines[index].trimmingCharacters(in: .whitespaces).isEmpty {
                    rows.append(cells(lines[index])); index += 1
                }
                result.append(.table(rows)); continue
            } else if trimmed.hasPrefix("#"), let space = trimmed.firstIndex(of: " "), trimmed[..<space].allSatisfy({ $0 == "#" }), trimmed.distance(from: trimmed.startIndex, to: space) <= 6 {
                flush(); result.append(.heading(trimmed.distance(from: trimmed.startIndex, to: space), String(trimmed[trimmed.index(after: space)...])))
            } else if trimmed.hasPrefix("> ") { flush(); result.append(.quote(String(trimmed.dropFirst(2)))) }
            else if trimmed.range(of: #"^(?:[-*+] |\d+\. )"#, options: .regularExpression) != nil {
                flush(); result.append(.list(trimmed))
            } else { paragraph.append(line) }
            index += 1
        }
        flush(); return result
    }
    private static func cells(_ line: String) -> [String] {
        var value = line.trimmingCharacters(in: .whitespaces)
        if value.hasPrefix("|") { value.removeFirst() }
        if value.hasSuffix("|") { value.removeLast() }
        return value.components(separatedBy: "|").map { $0.trimmingCharacters(in: .whitespaces) }
    }
    private static func isTableSeparator(_ line: String) -> Bool {
        let parts = cells(line)
        return !parts.isEmpty && parts.allSatisfy {
            $0.range(of: #"^:?-{3,}:?$"#, options: .regularExpression) != nil
        }
    }
}
