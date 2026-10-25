package asia.feng.aimeimei

import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.flow.buffer
import kotlinx.coroutines.flow.callbackFlow
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

internal data class SideDiscussion(val id: String, val conversationId: String, val sourceMessageId: String,
    val selectedText: String, val title: String, val modelName: String, val messageCount: Int) {
    companion object {
        fun parse(row: JSONObject) = SideDiscussion(row.getString("id"), row.getString("session_id"),
            row.get("source_message_id").toString(), row.optString("selected_text"), row.optString("title", "分支追问"),
            row.optString("model_name"), row.optInt("message_count"))
    }
}

internal data class SideDiscussionDetail(val discussion: SideDiscussion, val messages: List<ChatMessage>)

internal suspend fun PlatformApi.sideDiscussions(conversationId: String): List<SideDiscussion> =
    attachmentRows(request(listOf("api", "side-discussions"), query = mapOf("session_id" to conversationId)).optJSONArray("discussions")).map(SideDiscussion::parse)

internal suspend fun PlatformApi.createSideDiscussion(conversationId: String, messageId: String, text: String): SideDiscussion {
    val sourceId = messageId.toLongOrNull()?.takeIf { it > 0 } ?: throw IllegalArgumentException("请等待回答保存后再开始分支追问")
    require(text.trim().length >= 2) { "请至少选择两个字" }
    return SideDiscussion.parse(request(listOf("api", "side-discussions"), JSONObject()
        .put("session_id", conversationId).put("source_message_id", sourceId).put("selected_text", text.trim().take(12000))).getJSONObject("discussion"))
}

internal suspend fun PlatformApi.sideDiscussion(id: String): SideDiscussionDetail {
    val data = request(listOf("api", "side-discussions", id))
    val messages = attachmentRows(data.optJSONArray("messages")).map { row ->
        ChatMessage(row.get("id").toString(), row.optString("role"), row.optString("content"), row.optString("reasoning_content"),
            row.optString("generation_status", "completed"), emptyList(), usage = row.optJSONObject("usage")?.let(ChatUsage::fromJson))
    }
    return SideDiscussionDetail(SideDiscussion.parse(data.getJSONObject("discussion")), messages)
}

internal suspend fun PlatformApi.saveSideConversation(id: String): String =
    request(listOf("api", "side-discussions", id, "conversation"), JSONObject()).getJSONObject("conversation").getString("id")

// 分支拥有独立连接，停止或离开时只取消此连接，不触碰主聊天的生成任务。
internal fun PlatformApi.sideDiscussionStream(id: String, content: String) = callbackFlow {
    val url = base.newBuilder().addPathSegments("api/side-discussions").addPathSegment(id).addPathSegment("messages").build()
    val request = Request.Builder().url(url).header("Accept", "text/event-stream")
        .post(JSONObject().put("content", content).toString().toRequestBody("application/json; charset=utf-8".toMediaType())).build()
    val transport = client.newBuilder().readTimeout(5, TimeUnit.MINUTES).callTimeout(15, TimeUnit.MINUTES).build()
    val source = EventSources.createFactory(transport).newEventSource(request, object : EventSourceListener() {
        override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
            // 此接口在上游结束后继续发送保存事件，不能在上游 [DONE] 提前关闭。
            if (data.trim() == "[DONE]") return
            val event = try { JSONObject(data) } catch (_: Exception) {
                close(IOException("分支响应格式异常，请刷新核对记录")); eventSource.cancel(); return
            }
            if (event.has("error")) {
                close(ApiFailure(502, "分支模型返回错误，请刷新核对已保存内容")); eventSource.cancel(); return
            }
            trySend(event)
            if (event.optString("type") == "message_saved") { close(); eventSource.cancel() }
        }
        override fun onClosed(eventSource: EventSource) { close() }
        override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
            close(ApiFailure(response?.code ?: 0, when (response?.code) {
                401 -> "登录已失效，请重新登录"
                403 -> "分支追问已由管理员关闭"
                404 -> "分支或来源会话已不存在"
                400 -> "当前模型无法继续分支追问，请检查模型配置"
                else -> "连接中断或模型暂不可用，请刷新核对分支记录"
            }))
        }
    })
    awaitClose { source.cancel() }
}.buffer(Channel.UNLIMITED)
