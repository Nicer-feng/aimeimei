package asia.feng.aimeimei

import org.json.JSONObject
import kotlin.math.max

data class LiveReply(val content: String = "", val reasoning: String = "", val activity: String = "槑槑正在准备回答…")

class ReplyBuffer {
    private val answer = StringBuilder()
    private val thinking = StringBuilder()
    private var visible = 0
    var activity = "槑槑正在准备回答…"; private set
    var savedId: String? = null; private set
    var status = "interrupted"; private set
    fun accept(event: JSONObject) {
        when (event.optString("type")) {
            "search_status" -> activity = if (event.optString("status") == "done") "资料已找到，槑槑正在整理…" else "槑槑正在上网查资料…"
            "message.failed" -> status = event.optString("status", "failed")
            "message_saved" -> {
                savedId = event.opt("message_id")?.toString()?.takeIf { (it.toLongOrNull() ?: 0) > 0 }
                status = event.optString("generation_status", "interrupted")
            }
        }
        val choice = event.optJSONArray("choices")?.optJSONObject(0) ?: return
        val delta = choice.optJSONObject("delta") ?: choice.optJSONObject("message") ?: return
        val thought = listOf("reasoning_content", "reasoning", "thinking").firstNotNullOfOrNull { key ->
            delta.optString(key).takeIf { delta.opt(key) is String && it.isNotEmpty() }
        }.orEmpty()
        thinking.append(thought)
        val text = delta.opt("content") as? String ?: ""
        answer.append(text)
        if (text.isNotEmpty()) activity = "槑槑正在回答…"
        else if (thought.isNotEmpty()) activity = "槑槑正在思考…"
    }
    fun snapshot(elapsedMs: Long = 80, finish: Boolean = false): LiveReply {
        val pending = answer.length - visible
        val step = max(1, ((48 + pending / 2).coerceAtMost(360) * elapsedMs.coerceIn(1, 250) / 1000).toInt())
        visible = if (finish) answer.length else (visible + step).coerceAtMost(answer.length)
        if (visible in 1 until answer.length && Character.isHighSurrogate(answer[visible - 1])) visible++
        return LiveReply(answer.substring(0, visible), thinking.toString(), activity)
    }
}

fun draftKey(accountId: String, conversationId: String, kind: String) = "$accountId:$conversationId:$kind"

data class PendingSend(val conversationId: String, val baseline: Long, val content: String) {
    fun toJson() = JSONObject().put("conversation_id", conversationId).put("baseline", baseline).put("content", content).toString()
    companion object {
        fun parse(value: String?): PendingSend? = runCatching {
            val json = JSONObject(value ?: return@runCatching null)
            PendingSend(json.getString("conversation_id"), json.getLong("baseline"), json.getString("content"))
        }.getOrNull()
    }
}

fun pendingReply(pending: PendingSend, messages: List<ChatMessage>): ChatMessage? {
    val index = messages.indexOfFirst { it.role == "user" && (it.id.toLongOrNull() ?: 0) > pending.baseline && it.content.trim() == pending.content.trim() }
    if (index < 0) return null
    return messages.drop(index + 1).takeWhile { it.role != "user" }.firstOrNull { it.role == "assistant" }
}
