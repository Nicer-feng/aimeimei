package asia.feng.aimeimei

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.withContext
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.asRequestBody
import okio.BufferedSink
import okio.ForwardingSink
import okio.buffer
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.util.UUID
import java.util.concurrent.TimeUnit

// OSS 上传和重定向后的下载使用独立客户端，不把登录 Cookie 交给对象存储。
private val objectClient = OkHttpClient.Builder().cookieJar(CookieJar.NO_COOKIES).followRedirects(false)
    .followSslRedirects(false).retryOnConnectionFailure(false).connectTimeout(20, TimeUnit.SECONDS)
    .readTimeout(90, TimeUnit.SECONDS).writeTimeout(90, TimeUnit.SECONDS).callTimeout(8, TimeUnit.MINUTES).build()

internal fun safeObjectUrl(url: HttpUrl) = url.isHttps && url.username.isEmpty() && url.password.isEmpty()

internal suspend fun PlatformApi.uploadChatFile(file: File, name: String, mime: String, image: Boolean,
                                              onProgress: (Int) -> Unit): ChatAttachment {
    val route = if (image) "chat-images" else "documents"
    val policy = request(listOf("api", route, "upload-policy"), JSONObject()).getJSONObject("policy")
    require(file.length() in 1..policy.getLong("max_size")) { "文件大小超过服务限制" }
    val extension = "." + name.substringAfterLast('.', "").lowercase()
    require(attachmentRowsOrStrings(policy, "allowed_extensions").contains(extension)) { "暂不支持这个文件格式" }
    val host = policy.getString("host").toHttpUrl()
    require(safeObjectUrl(host)) { "上传地址无效" }
    val suffix = name.replace(Regex("[^a-zA-Z0-9._-]"), "-").takeLast(100).ifBlank { "file$extension" }
    val key = policy.getString("key_prefix") + UUID.randomUUID().toString() + "-" + suffix
    val media = mime.ifBlank { if (image) "image/jpeg" else "application/octet-stream" }
    val content = file.asRequestBody(media.toMediaTypeOrNull())
    val progressBody = object : RequestBody() {
        override fun contentType() = content.contentType()
        override fun contentLength() = file.length()
        override fun writeTo(sink: BufferedSink) {
            var written = 0L; var last = -1
            val forwarding = object : ForwardingSink(sink) {
                override fun write(source: okio.Buffer, byteCount: Long) {
                    super.write(source, byteCount); written += byteCount
                    val percent = (written * 98 / file.length().coerceAtLeast(1)).toInt().coerceAtMost(98)
                    if (percent != last) { last = percent; onProgress(percent) }
                }
            }.buffer()
            content.writeTo(forwarding); forwarding.flush()
        }
    }
    val body = MultipartBody.Builder().setType(MultipartBody.FORM).addFormDataPart("key", key)
        .addFormDataPart("OSSAccessKeyId", policy.getString("access_key_id"))
        .addFormDataPart("policy", policy.getString("policy")).addFormDataPart("Signature", policy.getString("signature"))
        .addFormDataPart("success_action_status", "200").addFormDataPart("Content-Type", media)
        .addFormDataPart("file", suffix, progressBody).build()
    objectClient.newCall(Request.Builder().url(host).post(body).build()).awaitResponse().use {
        if (!it.isSuccessful) throw IOException("文件上传失败，请重新选择文件后重试")
    }
    val result = request(listOf("api", route), JSONObject().put("filename", name.take(180)).put("mime_type", media)
        .put("file_size", file.length()).put("oss_key", key))
    return ChatAttachment.fromJson(result.getJSONObject(if (image) "image" else "document"), image)
}

private fun attachmentRowsOrStrings(row: JSONObject, key: String): List<String> {
    val array = row.optJSONArray(key) ?: return emptyList()
    return (0 until array.length()).map { array.optString(it) }
}

internal suspend fun PlatformApi.documentStatus(id: String) = ChatAttachment.fromJson(
    request(listOf("api", "documents", id, "refresh"), JSONObject()).getJSONObject("document"), false)

internal suspend fun PlatformApi.downloadPrivate(segments: List<String>, destination: File,
                                               query: Map<String, String> = emptyMap(), limit: Long = 100L * 1024 * 1024): File = withContext(Dispatchers.IO) {
    var url = base.newBuilder().apply { segments.forEach { addPathSegment(it) }; query.forEach { (key, value) -> addQueryParameter(key, value) } }.build()
    var authenticated = true
    val partial = File(destination.parentFile, destination.name + ".part")
    try {
        for (attempt in 0..3) {
            currentCoroutineContext().ensureActive()
            val downloadClient = if (authenticated) client.newBuilder().readTimeout(90, TimeUnit.SECONDS).callTimeout(8, TimeUnit.MINUTES).build() else objectClient
            downloadClient.newCall(Request.Builder().url(url).build()).awaitResponse().use { response ->
                if (response.code in listOf(301, 302, 303, 307, 308)) {
                    val next = url.resolve(response.header("Location").orEmpty()) ?: throw IOException("下载地址无效")
                    require(safeObjectUrl(next)) { "下载地址无效" }
                    // 一旦离开应用服务，后续跳转也不再发送任何登录 Cookie。
                    authenticated = authenticated && next.host == base.host && next.port == base.port && next.scheme == base.scheme
                    url = next
                } else {
                    if (!response.isSuccessful) throw ApiFailure(response.code, if (response.code == 401) "登录已失效，请重新登录" else "附件或语音下载失败，请稍后重试")
                    val body = response.body ?: throw IOException("下载内容为空")
                    require(body.contentLength() <= limit) { "文件超过预览限制" }
                    var count = 0L
                    body.byteStream().use { input -> partial.outputStream().use { output ->
                        val bytes = ByteArray(64 * 1024)
                        while (true) {
                            currentCoroutineContext().ensureActive()
                            val size = input.read(bytes); if (size < 0) break
                            count += size; require(count <= limit) { "文件超过预览限制" }; output.write(bytes, 0, size)
                        }
                    } }
                    require(count > 0) { "下载内容为空" }
                    if (destination.exists()) check(destination.delete())
                    check(partial.renameTo(destination)); return@withContext destination
                }
            }
        }
        throw IOException("下载跳转次数过多")
    } finally { partial.delete() }
}

internal suspend fun PlatformApi.favorite(messageId: String, add: Boolean): String {
    require((messageId.toLongOrNull() ?: 0) > 0)
    return if (add) request(listOf("api", "favorites"), JSONObject().put("message_id", messageId.toLong())).getJSONObject("favorite").getString("id")
    else { request(listOf("api", "favorites", "message", messageId), JSONObject(), "DELETE"); "" }
}

internal suspend fun PlatformApi.share(conversationId: String, messageId: String, scope: String, expiry: Int): String {
    require(scope in listOf("assistant", "turn", "conversation") && expiry in listOf(3600, 86400, 604800))
    val share = request(listOf("api", "conversations", conversationId, "shares"), JSONObject()
        .put("scope", scope).put("message_id", messageId.toLong()).put("expires_in", expiry)).getJSONObject("share")
    val path = share.getString("url")
    require(path.startsWith("/ai/share/") && !path.contains('?') && !path.contains('#'))
    return base.resolve(path)?.takeIf { it.host == base.host && it.scheme == base.scheme && it.port == base.port }?.toString()
        ?: throw IOException("分享地址无效")
}
