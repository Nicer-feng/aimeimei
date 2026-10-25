package asia.feng.aimeimei

internal sealed interface ReadingBlock {
    data class Text(val source: String) : ReadingBlock
    data class Code(val language: String, val source: String) : ReadingBlock
    data class Table(val rows: List<List<String>>, val alignments: List<Int>, val source: String) : ReadingBlock
}

/** 将需要独立操作的代码和表格从正文中取出，其余内容仍交给原有 Markdown 引擎。 */
internal fun readingBlocks(source: String): List<ReadingBlock> {
    val lines = source.split('\n')
    val result = mutableListOf<ReadingBlock>()
    val text = mutableListOf<String>()
    fun flush() { if (text.isNotEmpty()) { result += ReadingBlock.Text(text.joinToString("\n")); text.clear() } }
    var index = 0
    while (index < lines.size) {
        val fence = Regex("^ {0,3}(`{3,}|~{3,})(.*)$").matchEntire(lines[index])
        if (fence != null && !(fence.groupValues[1][0] == '`' && fence.groupValues[2].contains('`'))) {
            flush()
            val marker = fence.groupValues[1]
            val code = mutableListOf<String>()
            val end = Regex("^ {0,3}${Regex.escape(marker[0].toString())}{${marker.length},}\\s*$")
            index++
            while (index < lines.size && !end.matches(lines[index])) { code += lines[index]; index++ }
            // 末尾的空行属于 split 的终结符，不多加一个换行；闭合代码块保留源代码的换行。
            val closed = index < lines.size
            result += ReadingBlock.Code(normalizeCodeLanguage(fence.groupValues[2].trim().substringBefore(' ')),
                code.joinToString("\n") + if (closed && code.isNotEmpty()) "\n" else "")
            if (closed) index++
            continue
        }
        val header = tableCells(lines[index])
        val divider = if (index + 1 < lines.size) tableCells(lines[index + 1]) else null
        if (header != null && divider != null && header.size == divider.size &&
            divider.all { Regex(":?-{1,}:?").matches(it.trim()) }) {
            flush()
            val rows = mutableListOf(header)
            val tableSource = mutableListOf(lines[index], lines[index + 1])
            index += 2
            while (index < lines.size) {
                val row = tableCells(lines[index]) ?: break
                rows += List(header.size) { row.getOrElse(it) { "" } }
                tableSource += lines[index]; index++
            }
            result += ReadingBlock.Table(rows, divider.map { when {
                it.startsWith(":") && it.endsWith(":") -> 0
                it.endsWith(":") -> 1
                else -> -1
            } }, tableSource.joinToString("\n"))
            continue
        }
        text += lines[index]; index++
    }
    flush()
    return result
}

/** 转义管道和行内代码中的管道不应产生额外列。 */
internal fun tableCells(line: String): List<String>? {
    if (line.isBlank() || line.takeWhile { it == ' ' }.length > 3 || !line.contains('|')) return null
    val trimmed = line.trim()
    val cells = mutableListOf<String>()
    val cell = StringBuilder()
    var index = 0
    var ticks = 0
    while (index < trimmed.length) {
        val char = trimmed[index]
        if (char == '\\' && index + 1 < trimmed.length) {
            cell.append(char).append(trimmed[index + 1]); index += 2; continue
        }
        if (char == '`') {
            var end = index + 1
            while (end < trimmed.length && trimmed[end] == '`') end++
            val count = end - index
            ticks = if (ticks == count) 0 else if (ticks == 0) count else ticks
            cell.append(trimmed.substring(index, end)); index = end; continue
        }
        if (char == '|' && ticks == 0) { cells += cell.toString().trim(); cell.clear() } else cell.append(char)
        index++
    }
    cells += cell.toString().trim()
    if (trimmed.startsWith('|') && cells.firstOrNull().isNullOrEmpty()) cells.removeAt(0)
    if (trimmed.endsWith('|') && cells.lastOrNull().isNullOrEmpty() && !trimmed.endsWith("\\|")) cells.removeAt(cells.lastIndex)
    return cells.takeIf { it.isNotEmpty() }
}

internal fun normalizeCodeLanguage(value: String): String = when (val language = value.lowercase()) {
    "js", "jsx" -> "javascript"
    "ts", "tsx" -> "typescript"
    "py" -> "python"
    "kt", "kts" -> "kotlin"
    "sh", "shell", "zsh" -> "bash"
    "yml" -> "yaml"
    "golang" -> "go"
    "cxx", "c++" -> "cpp"
    "md" -> "markdown"
    "docker" -> "dockerfile"
    "", "plaintext", "txt" -> "text"
    else -> language
}

internal fun mermaidKind(source: String): String? = when {
    Regex("^(?:graph|flowchart)\\s+(?:TD|TB|BT|RL|LR)\\b", RegexOption.IGNORE_CASE).containsMatchIn(source.trim()) -> "流程图"
    source.trim().startsWith("mindmap", true) -> "思维导图"
    source.trim().startsWith("sequenceDiagram", true) -> "时序图"
    source.trim().startsWith("classDiagram", true) -> "类图"
    else -> null
}

internal data class SyntaxRange(val start: Int, val end: Int, val kind: String)

/** 轻量词法着色不执行代码，未识别的语言和过长片段保留完整纯文本。 */
internal fun codeSyntax(source: String, language: String): List<SyntaxRange> {
    if (source.length > 100_000 || language !in setOf("javascript", "typescript", "python", "kotlin", "java", "go", "c", "cpp", "csharp", "swift", "rust", "bash", "json", "yaml", "sql", "html", "xml", "css", "dockerfile")) return emptyList()
    val keywords = ("abstract as async await assert auto bool boolean break case catch char class const constructor continue data def default defer delete do double elif else enum except export extends false final finally float fn for from fun function go if implements import in inline instanceof int interface internal is let long map namespace new nil noexcept null object of open operator override package pass private protected public raise readonly record return select short signed static string struct super switch synchronized template this throw throws true try type typeof union unsigned val var virtual void volatile when where while with yield None True False self null undefined " +
        "SELECT FROM WHERE JOIN LEFT RIGHT INNER OUTER ON GROUP BY ORDER HAVING LIMIT OFFSET INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE DROP ALTER AND OR NOT AS NULL DISTINCT ASC DESC UNION ALL EXISTS CASE THEN ELSE END " +
        "FROM RUN CMD COPY ADD WORKDIR ENTRYPOINT ENV EXPOSE USER VOLUME ARG LABEL").split(' ').toSet()
    val hashComment = language in setOf("python", "bash", "yaml", "dockerfile")
    val slashComment = language !in setOf("json", "yaml", "sql", "bash", "python", "html", "xml")
    val result = mutableListOf<SyntaxRange>()
    var index = 0
    while (index < source.length) {
        val start = index
        val char = source[index]
        when {
            (hashComment && char == '#') || (language == "sql" && source.startsWith("--", index)) ||
                (slashComment && source.startsWith("//", index)) -> {
                index = source.indexOf('\n', index).let { if (it < 0) source.length else it }; result += SyntaxRange(start, index, "comment")
            }
            slashComment && source.startsWith("/*", index) -> {
                index = source.indexOf("*/", index + 2).let { if (it < 0) source.length else it + 2 }; result += SyntaxRange(start, index, "comment")
            }
            language in setOf("html", "xml") && char == '<' -> {
                index = source.indexOf('>', index + 1).let { if (it < 0) source.length else it + 1 }; result += SyntaxRange(start, index, "keyword")
            }
            char == '"' || char == '\'' || char == '`' -> {
                index++
                while (index < source.length) { if (source[index] == '\\') index = (index + 2).coerceAtMost(source.length) else if (source[index++] == char) break }
                result += SyntaxRange(start, index, "string")
            }
            char.isDigit() && (index == 0 || !source[index - 1].isLetterOrDigit()) -> {
                index++; while (index < source.length && (source[index].isLetterOrDigit() || source[index] in "._")) index++
                result += SyntaxRange(start, index, "number")
            }
            char.isLetter() || char == '_' -> {
                index++; while (index < source.length && (source[index].isLetterOrDigit() || source[index] == '_')) index++
                if (source.substring(start, index) in keywords) result += SyntaxRange(start, index, "keyword")
            }
            else -> index++
        }
    }
    return result
}
