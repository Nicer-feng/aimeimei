package asia.feng.aimeimei

import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import org.json.JSONArray
import org.json.JSONObject

internal data class ChatSearchResult(val id: String, val kind: String, val conversationId: String, val messageId: String,
                                     val title: String, val snippet: String, val role: String) {
    companion object {
        fun parse(row: JSONObject) = ChatSearchResult(row.getString("id"), row.optString("type"), row.optString("session_id"),
            row.optLong("message_id").takeIf { it > 0 }?.toString().orEmpty(), row.optString("title"), row.optString("snippet"), row.optString("role"))
    }
}

data class ChatSource(val title: String, val url: String, val snippet: String, val position: Int) {
    val safeUrl get() = url.toHttpUrlOrNull()?.takeIf {
        it.username.isEmpty() && it.password.isEmpty() && it.host.isNotBlank()
    }
    companion object {
        fun parse(row: JSONObject) = ChatSource(row.optString("title"), row.optString("url"), row.optString("snippet"), row.optInt("position"))
    }
}

internal data class AiProfile(val id: String, val title: String, val content: String, val kind: String,
                              val enabled: Boolean, val order: Int, val tokens: Long) {
    companion object {
        fun parse(row: JSONObject) = AiProfile(row.getString("id"), row.optString("title"), row.optString("content"),
            row.optString("type", "profile"), row.optBoolean("enabled"), row.optInt("sort_order", 100), row.optLong("token_estimate"))
    }
}
internal val profileKinds = linkedMapOf("profile" to "个人背景", "project" to "项目资料", "style" to "表达风格", "memory" to "长期记忆")

internal suspend fun PlatformApi.searchChats(query: String): List<ChatSearchResult> = attachmentRows(
    request(listOf("api", "search"), query = mapOf("q" to query.take(80))).optJSONArray("results"))
    .map(ChatSearchResult::parse).filter { it.kind in setOf("conversation", "message", "favorite") }

internal suspend fun PlatformApi.conversationDetail(id: String): Conversation {
    val row = request(listOf("api", "conversations", id)).getJSONObject("conversation")
    return Conversation(row.getString("id"), row.optString("title"), row.optString("model_name"), row.optLong("updated_at"),
        row.optString("model_id"), row.optString("reasoning_mode", "balanced"), row.optBoolean("pinned"))
}

internal suspend fun PlatformApi.profiles(): List<AiProfile> = attachmentRows(request(listOf("api", "profiles")).optJSONArray("profiles")).map(AiProfile::parse)
internal suspend fun PlatformApi.saveProfile(id: String?, title: String, content: String, kind: String, enabled: Boolean, order: Int): AiProfile {
    require(title.isNotBlank() && title.length <= 80 && content.isNotBlank() && content.length <= 12000 && kind in profileKinds)
    val path = listOf("api", "profiles") + listOfNotNull(id)
    return AiProfile.parse(request(path, JSONObject().put("title", title.trim()).put("content", content.trim()).put("type", kind)
        .put("enabled", enabled).put("sort_order", order), if (id == null) "POST" else "PUT").getJSONObject("profile"))
}
internal suspend fun PlatformApi.deleteProfile(id: String) { request(listOf("api", "profiles", id), JSONObject(), "DELETE") }
internal suspend fun PlatformApi.reorderProfiles(ids: List<String>): List<AiProfile> = attachmentRows(
    request(listOf("api", "profiles", "reorder"), JSONObject().put("ids", JSONArray(ids))).optJSONArray("profiles")).map(AiProfile::parse)
