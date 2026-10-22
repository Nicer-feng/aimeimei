package asia.feng.aimeimei

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.awaitClose
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.callbackFlow
import kotlinx.coroutines.flow.buffer
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withContext
import okhttp3.Call
import okhttp3.Callback
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.sse.EventSource
import okhttp3.sse.EventSourceListener
import okhttp3.sse.EventSources
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resumeWithException

data class Account(val id: String, val username: String, val displayName: String, val role: String = "user")
data class Captcha(val id: String, val svg: String)
data class ChatModel(val id: String, val name: String, val actualModel: String, val provider: String,
                     val reasoningControl: Boolean = false, val nativeSearch: Boolean = false, val vision: Boolean = false)
data class Conversation(val id: String, val title: String, val modelName: String, val updatedAt: Long,
                        val modelId: String = "", val reasoningMode: String = "balanced", val pinned: Boolean = false)
data class ChatMessage(val id: String, val role: String, val content: String, val reasoning: String,
                       val status: String, val attachments: List<String>, val media: List<ChatAttachment> = emptyList(),
                       val favoriteId: String = "", val usage: ChatUsage? = null)
class ApiFailure(val status: Int, message: String) : IOException(message)

class PlatformApi(internal val base: HttpUrl, cookies: CookieJar) {
    internal val client = OkHttpClient.Builder().cookieJar(cookies)
        .connectTimeout(15, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS)
        .callTimeout(40, TimeUnit.SECONDS).followRedirects(false).retryOnConnectionFailure(false).build()

    private val streamClient = client.newBuilder().readTimeout(5, TimeUnit.MINUTES).callTimeout(15, TimeUnit.MINUTES).build()

    internal suspend fun request(segments: List<String>, body: JSONObject? = null, method: String = "POST", query: Map<String, String> = emptyMap()): JSONObject = withContext(Dispatchers.IO) {
        val url = base.newBuilder().apply { segments.forEach { addPathSegment(it) }; query.forEach { (key, value) -> addQueryParameter(key, value) } }.build()
        val builder = Request.Builder().url(url).header("Accept", "application/json")
        if (body != null) builder.method(method, body.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
        client.newCall(builder.build()).awaitResponse().use { response ->
            val raw = response.body?.string().orEmpty()
            val data = try { JSONObject(raw) } catch (_: Exception) {
                throw ApiFailure(response.code, "服务器响应异常，请稍后重试")
            }
            if (!response.isSuccessful) {
                val hint = if (segments.getOrNull(1) in setOf("admin", "usage-time")) adminFailureHint(response.code, data.optString("error")) else when (data.optString("error")) {
                    "captcha incorrect" -> "验证码不正确或已过期，请重新输入"
                    "password incorrect" -> "账号或密码不正确"
                    else -> if (response.code == 401) "登录已失效，请重新登录" else "请求失败，请稍后重试（${response.code}）"
                }
                throw ApiFailure(response.code, hint)
            }
            data
        }
    }

    // 管理接口沿用当前账号 Cookie，路径和参数分别编码，不接受任意外部地址。
    internal suspend fun adminRequest(path: List<String>, method: String = "GET", body: JSONObject? = null,
                                      query: Map<String, String> = emptyMap()): JSONObject {
        require(path.firstOrNull() in setOf("overview", "users", "models", "search", "tts", "sms-auth", "features",
            "token-stats", "cost-stats", "cost-recalculate", "password", "usage-time", "version"))
        require(method in setOf("GET", "POST", "PUT", "DELETE"))
        val route = when (path.first()) {
            "version" -> listOf("api", "version")
            "usage-time" -> { require(path.getOrNull(1) == "admin"); listOf("api") + path }
            else -> listOf("api", "admin") + path
        }
        return request(route, if (method == "GET") null else body ?: JSONObject(), method, query)
    }

    suspend fun captcha(): Captcha = request(listOf("api", "captcha")).let {
        Captcha(it.getString("captcha_id"), it.getString("image_svg"))
    }
    suspend fun currentAccount(): Account? = request(listOf("api", "me")).let {
        if (it.optBoolean("authenticated")) account(it.getJSONObject("user")) else null
    }
    suspend fun login(username: String, password: String, challenge: Captcha, answer: String): Account {
        val body = JSONObject().put("username", username.trim()).put("password", password)
            .put("captcha_id", challenge.id).put("captcha", answer.trim())
        return account(request(listOf("api", "login"), body).getJSONObject("user"))
    }
    suspend fun logout() { request(listOf("api", "logout"), JSONObject()) }
    suspend fun models(): List<ChatModel> = objects(request(listOf("api", "models")).optJSONArray("models")).map {
        ChatModel(it.getString("id"), it.optString("name"), it.optString("model"), it.optString("provider"),
            it.optBoolean("supports_reasoning_control"), it.optBoolean("supports_native_web_search"), it.optBoolean("supports_vision"))
    }
    suspend fun conversations(): List<Conversation> = objects(request(listOf("api", "conversations")).optJSONArray("conversations")).map(::conversation)
    suspend fun createConversation(modelId: String, mode: String): Conversation = conversation(
        request(listOf("api", "conversations"), JSONObject().put("model_id", modelId).put("reasoning_mode", mode)).getJSONObject("conversation"))
    suspend fun configureConversation(id: String, modelId: String, mode: String): Conversation = conversation(
        request(listOf("api", "conversations", id), JSONObject().put("model_id", modelId).put("reasoning_mode", mode), "PATCH").getJSONObject("conversation"))
    suspend fun renameConversation(id: String, title: String): Conversation = conversation(
        request(listOf("api", "conversations", id), JSONObject().put("title", title), "PATCH").getJSONObject("conversation"))
    suspend fun pinConversation(id: String, pinned: Boolean) {
        request(listOf("api", "conversations", id, if (pinned) "pin" else "unpin"), JSONObject())
    }
    suspend fun deleteConversation(id: String) { request(listOf("api", "conversations", id), JSONObject(), "DELETE") }
    suspend fun messages(id: String): List<ChatMessage> = objects(request(listOf("api", "conversations", id, "messages")).optJSONArray("messages")).map {
        val files = objects(it.optJSONArray("documents")).map { doc -> doc.optString("filename", "文件") }
        val images = objects(it.optJSONArray("images")).map { image -> image.optString("filename", "图片") }
        ChatMessage(it.get("id").toString(), it.optString("role"), it.optString("content"), it.optString("reasoning_content"),
            it.optString("generation_status"), files + images,
            objects(it.optJSONArray("images")).map { row -> ChatAttachment.fromJson(row, true) } +
                objects(it.optJSONArray("documents")).map { row -> ChatAttachment.fromJson(row, false) },
            (it.opt("favorite_id") as? String).orEmpty(), it.optJSONObject("usage")?.let(ChatUsage::fromJson))
    }
    private fun account(value: JSONObject) = Account(value.getString("id"), value.getString("username"), value.optString("display_name"), value.optString("role", "user"))
    private fun conversation(value: JSONObject) = Conversation(value.getString("id"), value.optString("title", "新对话"),
        value.optString("model_name"), value.optLong("updated_at"), value.optString("model_id"), value.optString("reasoning_mode", "balanced"), value.optBoolean("pinned"))

    fun stream(id: String, content: String, webSearch: Boolean, imageIds: List<String> = emptyList(), documentIds: List<String> = emptyList()) = callbackFlow {
        val url = base.newBuilder().addPathSegments("api/conversations").addPathSegment(id).addPathSegment("messages").build()
        val body = JSONObject().put("content", content).put("web_search", webSearch).put("use_profile", true)
        if (imageIds.isNotEmpty()) body.put("image_ids", JSONArray(imageIds))
        if (documentIds.isNotEmpty()) body.put("document_ids", JSONArray(documentIds))
        val request = Request.Builder().url(url).post(body.toString().toRequestBody("application/json; charset=utf-8".toMediaType())).build()
        val source = EventSources.createFactory(streamClient).newEventSource(request, object : EventSourceListener() {
            override fun onEvent(eventSource: EventSource, id: String?, type: String?, data: String) {
                if (data.trim() == "[DONE]") { close();eventSource.cancel();return }
                try {
                    val event = JSONObject(data)
                    if (event.has("error")) { close(ApiFailure(502, "模型服务返回错误，已收到的内容将保留"));eventSource.cancel();return }
                    trySend(event)
                    if (event.optString("type") == "message_saved") { close();eventSource.cancel() }
                } catch (_: org.json.JSONException) {
                    close(IOException("流式响应格式异常"));eventSource.cancel()
                }
            }
            override fun onClosed(eventSource: EventSource) { close() }
            override fun onFailure(eventSource: EventSource, t: Throwable?, response: Response?) {
                close(ApiFailure(response?.code ?: 0, when (response?.code) {
                    401 -> "登录已失效，请重新登录"
                    400 -> "请求未被接受，请检查模型或联网配置后刷新记录"
                    else -> "连接中断或模型暂不可用，请刷新核对服务器记录"
                }))
            }
        })
        awaitClose { source.cancel() }
    }.buffer(Channel.UNLIMITED)
    private fun objects(array: JSONArray?): List<JSONObject> = if (array == null) emptyList()
        else (0 until array.length()).mapNotNull { array.optJSONObject(it) }
}

internal suspend fun Call.awaitResponse(): Response = suspendCancellableCoroutine { continuation ->
    continuation.invokeOnCancellation { cancel() }
    enqueue(object : Callback {
        override fun onFailure(call: Call, e: IOException) { if (continuation.isActive) continuation.resumeWithException(e) }
        override fun onResponse(call: Call, response: Response) {
            continuation.resume(response, onCancellation = { _, value, _ -> value.close() })
        }
    })
}

// 只翻译明确的业务错误，不回显任意服务器响应或凭证内容。
internal fun adminFailureHint(status: Int, error: String): String {
    val known = mapOf(
        "at least one active admin is required" to "至少需要保留一位启用的管理员",
        "password must be at least 6 characters" to "密码至少需要 6 位",
        "password must be at least 8 characters" to "家用登录密码至少需要 8 位",
        "name, base_url and model are required" to "请填写模型名称、API 地址和模型 ID",
        "username invalid" to "账号格式不正确", "role invalid" to "请选择正确的账号角色",
        "invalid statistics target" to "统计对象无效，请刷新后重试",
        "invalid statistics date" to "统计日期不正确", "invalid statistics range" to "统计范围不正确",
        "unsupported search provider" to "搜索服务暂不支持", "unsupported search mode" to "搜索策略不正确",
        "unsupported search depth" to "搜索深度不正确")
    val chinese = setOf("账号或手机号已被绑定", "手机号格式不正确", "验证码参数名不合法", "有效期参数名不合法",
        "短信有效期或发送间隔不合法", "请先填写签名、模板，并确认服务端 RAM 凭据已配置短信认证权限",
        "至少保留一个可用音色", "语音参数不正确", "配置格式不正确", "请选择不超过 366 天且不晚于今天的日期范围")
    if (status == 400 || status == 409) { known[error]?.let { return it }; if (error in chinese) return error }
    return when (status) {
        401 -> "登录已失效或管理员权限已变化，请重新登录"
        403 -> "当前账号没有管理员权限"
        409 -> "账号或手机号已被占用，请修改后保存"
        400 -> "请求未被接受，请检查填写的配置和参数范围"
        404 -> "记录已不存在，请返回后刷新"
        else -> "管理请求失败，请稍后重试（$status）"
    }
}
