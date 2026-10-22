package asia.feng.aimeimei

import org.json.JSONArray
import org.json.JSONObject

// 附件与安装包使用独立 Provider，避免清单合并时共享路径配置。
class ChatAttachmentProvider : androidx.core.content.FileProvider()

data class ChatAttachment(val id: String, val name: String, val mime: String, val size: Long,
                          val image: Boolean, val status: String = "completed", val progress: Int = 100,
                          val error: String = "", val clientKey: String = id, val pages: Int = 0) {
    val ready get() = id.isNotBlank() && status == "completed"
    fun toJson() = JSONObject().put("id", id).put("filename", name).put("mime_type", mime).put("file_size", size)
        .put("image", image).put("status", status).put("client_key", clientKey).put("page_count", pages)
    companion object {
        fun fromJson(row: JSONObject, image: Boolean = row.optBoolean("image")) = ChatAttachment(
            row.optString("id"), row.optString("filename", "附件"), row.optString("mime_type"), row.optLong("file_size"),
            image, if (image) "completed" else row.optString("status", "submitted"),
            clientKey = row.optString("client_key", row.optString("id")), pages = row.optInt("page_count"))
    }
}

data class ChatQuote(val messageId: String, val role: String, val text: String) {
    fun toJson() = JSONObject().put("message_id", messageId).put("role", role).put("text", text)
}

internal fun quoteMessage(question: String, quotes: List<ChatQuote>): String {
    if (quotes.isEmpty()) return question.trim()
    val blocks = quotes.take(3).joinToString("\n\n") { quote ->
        val role = if (quote.role == "assistant") "槑槑" else "用户"
        "【来源：$role】\n" + quote.text.take(12000).lines().joinToString("\n") { "> $it" } + "\n【引用结束】"
    }
    return "以下是用户从当前会话中引用的内容：\n\n$blocks\n\n用户的新问题：\n${question.trim().ifBlank { "请基于以上引用内容进行分析。" }}"
}

internal fun quotedDisplay(content: String): Pair<List<String>, String> {
    if (!content.startsWith("以下是用户从当前会话中引用的内容：")) return emptyList<String>() to content
    val divider = content.indexOf("用户的新问题：")
    if (divider < 0) return emptyList<String>() to content
    val blocks = Regex("【来源：([^】]+)】\\s*([\\s\\S]*?)\\s*【引用结束】").findAll(content.substring(0, divider))
        .map { it.groupValues[2].lines().joinToString("\n") { line -> line.removePrefix("> ") }.trim() }.toList()
    return blocks to content.substring(divider + "用户的新问题：".length).trim()
}

internal fun attachmentRows(array: JSONArray?) = if (array == null) emptyList() else
    (0 until array.length()).mapNotNull { array.optJSONObject(it) }

internal fun attachmentStatus(item: ChatAttachment) = when (item.status) {
    "copying" -> "正在读取文件…"; "uploading" -> "上传 ${item.progress}%"; "failed" -> item.error.ifBlank { "处理失败，请重试或移除" }
    "completed" -> if (item.image) "图片已就绪" else "解析完成${if (item.pages > 0) " · ${item.pages} 页" else ""}"
    else -> "正在解析，可稍后刷新"
}
