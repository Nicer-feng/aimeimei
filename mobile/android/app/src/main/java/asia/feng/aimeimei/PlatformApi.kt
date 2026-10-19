package asia.feng.aimeimei

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

data class Account(val id: String, val username: String, val displayName: String)
data class Captcha(val id: String, val svg: String)
data class ChatModel(val id: String, val name: String, val actualModel: String, val provider: String)
data class Conversation(val id: String, val title: String, val modelName: String, val updatedAt: Long)
data class ChatMessage(val id: String, val role: String, val content: String, val reasoning: String,
                       val status: String, val attachments: List<String>)
class ApiFailure(val status: Int, message: String) : IOException(message)

class PlatformApi(private val base: HttpUrl, cookies: CookieJar) {
    private val client = OkHttpClient.Builder().cookieJar(cookies)
        .connectTimeout(15, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS)
        .callTimeout(40, TimeUnit.SECONDS).followRedirects(false).build()

    private suspend fun request(segments: List<String>, body: JSONObject? = null): JSONObject = withContext(Dispatchers.IO) {
        val url = base.newBuilder().apply { segments.forEach { addPathSegment(it) } }.build()
        val builder = Request.Builder().url(url).header("Accept", "application/json")
        if (body != null) builder.post(body.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))
        client.newCall(builder.build()).execute().use { response ->
            val raw = response.body?.string().orEmpty()
            val data = try { JSONObject(raw) } catch (_: Exception) {
                throw ApiFailure(response.code, "服务器响应异常，请稍后重试")
            }
            if (!response.isSuccessful) {
                val hint = when (data.optString("error")) {
                    "captcha incorrect" -> "验证码不正确或已过期，请重新输入"
                    "password incorrect" -> "账号或密码不正确"
                    else -> if (response.code == 401) "登录已失效，请重新登录" else "请求失败，请稍后重试（${response.code}）"
                }
                throw ApiFailure(response.code, hint)
            }
            data
        }
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
        ChatModel(it.getString("id"), it.optString("name"), it.optString("model"), it.optString("provider"))
    }
    suspend fun conversations(): List<Conversation> = objects(request(listOf("api", "conversations")).optJSONArray("conversations")).map {
        Conversation(it.getString("id"), it.optString("title", "新对话"), it.optString("model_name"), it.optLong("updated_at"))
    }
    suspend fun messages(id: String): List<ChatMessage> = objects(request(listOf("api", "conversations", id, "messages")).optJSONArray("messages")).map {
        val files = objects(it.optJSONArray("documents")).map { doc -> doc.optString("filename", "文件") }
        val images = objects(it.optJSONArray("images")).map { image -> image.optString("filename", "图片") }
        ChatMessage(it.get("id").toString(), it.optString("role"), it.optString("content"), it.optString("reasoning_content"),
            it.optString("generation_status"), files + images)
    }
    private fun account(value: JSONObject) = Account(value.getString("id"), value.getString("username"), value.optString("display_name"))
    private fun objects(array: JSONArray?): List<JSONObject> = if (array == null) emptyList()
        else (0 until array.length()).mapNotNull { array.optJSONObject(it) }
}
