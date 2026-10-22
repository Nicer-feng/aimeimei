package asia.feng.aimeimei

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.util.UUID

internal class ChatTools(private val app: Application, private val api: PlatformApi, private val scope: CoroutineScope,
                         private val onUnauthorized: () -> Unit) {
    private val store = app.getSharedPreferences("chat_drafts", 0)
    private var owner = ""
    private var conversation = ""
    private var revision = 0
    private var session = newSession()
    private fun newSession() = CoroutineScope(scope.coroutineContext + SupervisorJob(scope.coroutineContext[Job]))
    private var poll: Job? = null
    private var uploadTask: Job? = null
    private var uploadRun = 0
    private val activeUploads = mutableMapOf<String, Job>()
    private val localFiles = mutableMapOf<String, File>()
    var attachments by mutableStateOf<List<ChatAttachment>>(emptyList()); private set
    var quotes by mutableStateOf<List<ChatQuote>>(emptyList()); private set
    var uploading by mutableStateOf(false); private set
    var notice by mutableStateOf<String?>(null); private set
    var preview by mutableStateOf<ChatAttachment?>(null); private set
    var previewFile by mutableStateOf<File?>(null); private set
    var previewBusy by mutableStateOf(false); private set
    var voiceMessage by mutableStateOf<ChatMessage?>(null); private set
    var voiceConfig by mutableStateOf<JSONObject?>(null); private set
    var shareMessage by mutableStateOf<ChatMessage?>(null); private set
    var shareUrl by mutableStateOf(""); private set
    private var shareId = ""
    var sharing by mutableStateOf(false); private set
    var favorites by mutableStateOf<List<JSONObject>>(emptyList()); private set
    var favoritesLoading by mutableStateOf(false); private set
    var favoriteBusy by mutableStateOf<String?>(null); private set
    var menuMessage by mutableStateOf<ChatMessage?>(null)
    val speech = SpeechPlayer(app, api, scope) { notice = it }
    val ready get() = !uploading && attachments.all { it.ready }
    val hasContent get() = attachments.isNotEmpty() || quotes.isNotEmpty()
    private fun key(kind: String) = draftKey(owner, conversation, kind)
    private fun directory(): File {
        val hash = MessageDigest.getInstance("SHA-256").digest(owner.toByteArray()).take(12).joinToString("") { "%02x".format(it) }
        return File(app.cacheDir, "chat-attachments/$hash").apply { mkdirs() }
    }
    fun bind(accountId: String, conversationId: String) {
        if (owner == accountId && conversation == conversationId) return
        persist(); val oldOwner = owner
        revision++; session.cancel(); session = newSession(); poll = null; uploadTask = null; activeUploads.clear()
        uploading = false; speech.stop(); preview = null; previewFile = null; previewBusy = false
        voiceMessage = null; voiceConfig = null; shareMessage = null; shareUrl = ""; shareId = ""; sharing = false; menuMessage = null
        favoritesLoading = false; favoriteBusy = null; notice = null
        if (oldOwner != accountId) { localFiles.clear(); favorites = emptyList() }
        if (accountId.isEmpty() && oldOwner.isNotEmpty()) {
            val root = File(app.cacheDir, "chat-attachments")
            root.deleteRecursively()
        }
        owner = accountId; conversation = conversationId
        attachments = if (owner.isEmpty()) emptyList() else runCatching {
            attachmentRows(JSONArray(store.getString(key("attachments"), "[]"))).map { ChatAttachment.fromJson(it) }
        }.getOrDefault(emptyList())
        quotes = if (owner.isEmpty()) emptyList() else runCatching {
            attachmentRows(JSONArray(store.getString(key("quotes"), "[]"))).take(3).map { ChatQuote(it.optString("message_id"), it.optString("role"), it.optString("text").take(12000)) }
        }.getOrDefault(emptyList())
        if (owner.isNotEmpty()) {
            var retained = 0L
            val keep = attachments.mapNotNull { localFiles[it.id] }.toSet()
            directory().listFiles()?.sortedByDescending { it.lastModified() }?.forEach { file ->
                if (file !in keep && (file.lastModified() < System.currentTimeMillis() - 86400000L || retained + file.length() > 300L * 1024 * 1024)) file.delete()
                else retained += file.length()
            }
            localFiles.entries.removeAll { !it.value.exists() }
        }
        pollDocuments()
    }
    private fun persist() {
        if (owner.isEmpty()) return
        store.edit().putString(key("attachments"), JSONArray(attachments.filter { it.id.isNotBlank() }.map { it.toJson() }).toString())
            .putString(key("quotes"), JSONArray(quotes.map { it.toJson() }).toString()).apply()
    }
    fun restoreDraft(files: List<ChatAttachment>, citations: List<ChatQuote>) { attachments = files; quotes = citations; persist(); pollDocuments() }
    fun forgetWelcomeDraft() { store.edit().remove(draftKey(owner, "", "attachments")).remove(draftKey(owner, "", "quotes")).apply() }
    fun sent() { attachments = emptyList(); quotes = emptyList(); persist(); poll?.cancel(); poll = null }
    fun dismissNotice() { notice = null }
    fun report(message: String) { notice = message }
    private fun action(block: suspend (Int) -> Unit): Job {
        val ticket = revision
        return session.launch {
            try { block(ticket) }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) {
                if (ticket == revision) {
                    notice = when (error) {
                        is ApiFailure -> error.message
                        is IllegalArgumentException -> error.message ?: "文件或参数不正确"
                        else -> "操作未完成，请检查网络后重试"
                    }
                    if (error is ApiFailure && error.status == 401) onUnauthorized()
                }
            }
        }
    }
    fun removeAttachment(item: ChatAttachment) { activeUploads.remove(item.clientKey)?.cancel(); attachments = attachments.filterNot { it.clientKey == item.clientKey }; persist() }
    fun cancelUploads() { uploadRun++; uploadTask?.cancel(); uploadTask = null; activeUploads.clear(); uploading = false; attachments = attachments.filter { it.id.isNotBlank() }; persist(); pollDocuments() }
    fun removeQuote(index: Int) { quotes = quotes.filterIndexed { i, _ -> i != index }; persist() }
    fun quote(message: ChatMessage, text: String = message.content) {
        if (text.trim().length < 2) { notice = "请至少选择两个字"; return }
        if (quotes.size >= 3) { notice = "一条消息最多引用 3 段内容"; return }
        action { ticket ->
            val features = api.request(listOf("api", "features")).optJSONObject("features")
            if (ticket != revision) return@action
            if (features?.optBoolean("selection_quote", true) == false) { notice = "引用提问已由管理员关闭"; return@action }
            if (quotes.size >= 3) { notice = "一条消息最多引用 3 段内容"; return@action }
            quotes = quotes + ChatQuote(message.id, message.role, text.trim().take(12000)); persist(); menuMessage = null
        }
    }
    fun addFiles(uris: List<Uri>, image: Boolean) {
        if (owner.isEmpty() || uploading || uris.isEmpty()) return
        if (attachments.count { it.image == image } + uris.size > 5) { notice = if (image) "一次最多选择 5 张图片" else "一次最多选择 5 份材料"; return }
        uploading = true
        val run = ++uploadRun
        val targetDirectory = directory()
        uploadTask = action { ticket ->
            try { coroutineScope {
                for (uri in uris) {
                    val pending = ChatAttachment("", if (image) "所选图片" else "所选文件", "", 0, image, "copying", 0, clientKey = UUID.randomUUID().toString())
                    attachments = attachments + pending
                    val child = launch {
                        var file: File? = null
                        var saved = false
                        try {
                            val copied = withContext(Dispatchers.IO) { copySelection(uri, image, targetDirectory) }
                            val selectedFile = copied.first; file = selectedFile
                            val item = pending.copy(name = copied.second, mime = copied.third, size = selectedFile.length(), status = "uploading")
                            if (ticket != revision) return@launch
                            attachments = attachments.map { if (it.clientKey == pending.clientKey) item else it }
                            val uploaded = api.uploadChatFile(selectedFile, item.name, item.mime, image) { progress ->
                                scope.launch { if (ticket == revision) attachments = attachments.map { if (it.clientKey == item.clientKey) it.copy(progress = progress) else it } }
                            }.copy(clientKey = pending.clientKey)
                            if (ticket != revision) return@launch
                            // 用户移除后不重新插入附件；已上传的对象沿用服务端清理机制。
                            if (attachments.any { it.clientKey == pending.clientKey }) {
                                localFiles[uploaded.id] = selectedFile; saved = true
                                attachments = attachments.map { if (it.clientKey == pending.clientKey) uploaded else it }; persist()
                            }
                        } catch (cancelled: CancellationException) { throw cancelled }
                        catch (error: Exception) {
                            if (ticket == revision) attachments = attachments.map { if (it.clientKey == pending.clientKey)
                                it.copy(status = "failed", error = if (error is IllegalArgumentException || error is ApiFailure) error.message.orEmpty() else "上传未完成，请移除后重新选择") else it }
                        } finally { if (!saved) file?.delete() }
                    }
                    activeUploads[pending.clientKey] = child
                    child.join(); activeUploads.remove(pending.clientKey)
                }
            } } finally { if (ticket == revision && run == uploadRun) { uploading = false; uploadTask = null; pollDocuments() } }
        }
    }
    private suspend fun copySelection(uri: Uri, image: Boolean, targetDirectory: File): Triple<File, String, String> {
        require(uri.scheme == "content") { "请选择系统相册或文件中的内容" }
        var name = ""
        app.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) name = cursor.getString(0).orEmpty().substringAfterLast('/').take(180)
        }
        var mime = app.contentResolver.getType(uri).orEmpty()
        val ext = name.substringAfterLast('.', "").lowercase()
        if (mime.isBlank()) mime = MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext).orEmpty()
        if (name.isBlank()) name = "${if (image) "图片" else "文件"}.${MimeTypeMap.getSingleton().getExtensionFromMimeType(mime) ?: if (image) "jpg" else "bin"}"
        if (image) require(mime in listOf("image/jpeg", "image/png", "image/webp")) { "图片支持 JPG、PNG、WebP，请转换后重新选择" }
        val extension = name.substringAfterLast('.', "bin").filter { it.isLetterOrDigit() }.take(10)
        val file = File.createTempFile("selected-", ".$extension", targetDirectory)
        try {
            val limit = if (image) 20L * 1024 * 1024 else 50L * 1024 * 1024
            app.contentResolver.openInputStream(uri)?.use { input -> file.outputStream().use { output ->
                val buffer = ByteArray(64 * 1024); var count = 0L
                while (true) { currentCoroutineContext().ensureActive(); val size = input.read(buffer); if (size < 0) break; count += size
                    require(count <= limit) { if (image) "单张图片不能超过 20MB" else "单个材料不能超过 50MB" }; output.write(buffer, 0, size) }
            } } ?: throw IllegalArgumentException("无法读取所选文件，请重新选择")
            require(file.length() > 0) { "所选文件为空" }
            return Triple(file, name, mime.ifBlank { "application/octet-stream" })
        } catch (error: Exception) { file.delete(); throw error }
    }
    private fun pollDocuments() {
        poll?.cancel(); poll = null
        if (attachments.none { !it.image && it.status in listOf("submitted", "processing", "uploaded") }) return
        poll = action { ticket ->
            repeat(40) {
                delay(3000)
                val pending = attachments.filter { !it.image && it.status in listOf("submitted", "processing", "uploaded") }
                if (pending.isEmpty()) return@action
                for (item in pending) {
                    val updated = api.documentStatus(item.id).copy(clientKey = item.clientKey)
                    if (ticket != revision) return@action
                    attachments = attachments.map { if (it.clientKey == item.clientKey) updated else it }; persist()
                }
            }
            if (ticket == revision) notice = "材料仍在解析，可稍后点击附件刷新状态"
        }
    }
    fun refreshDocument(item: ChatAttachment) = action { ticket ->
        val updated = api.documentStatus(item.id).copy(clientKey = item.clientKey)
        if (ticket == revision) {
            attachments = attachments.map { if (it.clientKey == item.clientKey) updated else it }; persist(); pollDocuments()
            if (preview?.id == item.id) preview = updated
        }
    }
    fun showPreview(item: ChatAttachment) {
        preview = item; previewFile = localFiles[item.id]?.takeIf { it.exists() }; previewBusy = false
        if (item.image && previewFile == null && item.id.isNotBlank()) {
            previewBusy = true
            action { ticket ->
                try {
                    val file = File.createTempFile("image-", ".img", directory())
                    try { api.downloadPrivate(listOf("api", "chat-images", item.id, "view"), file, limit = 20L * 1024 * 1024) }
                    catch (error: Exception) { file.delete(); throw error }
                    if (ticket == revision && preview?.id == item.id) {
                        localFiles.put(item.id, file)?.takeIf { it != file }?.delete(); previewFile = file
                    } else file.delete()
                } finally { if (ticket == revision) previewBusy = false }
            }
        }
    }
    fun closePreview() { preview = null; previewFile = null }
    fun showVoices(message: ChatMessage) = action { ticket ->
        val config = api.request(listOf("api", "tts", "config")).getJSONObject("tts")
        if (ticket == revision) {
            if (!config.optBoolean("enabled") || !config.optBoolean("configured")) notice = "语音朗读尚未开启或配置，请联系管理员"
            else { voiceConfig = config; voiceMessage = message; menuMessage = null }
        }
    }
    fun closeVoices() { voiceMessage = null; voiceConfig = null }
    fun startSpeech(message: ChatMessage, voice: String, speed: Float) {
        closeVoices(); speech.play(message.id, voice, speed, directory())
    }
    fun showShare(message: ChatMessage) { shareMessage = message; shareUrl = ""; shareId = ""; menuMessage = null }
    fun closeShare() { if (!sharing) { shareMessage = null; shareUrl = "" } }
    fun createShare(scope: String, expiry: Int) {
        val message = shareMessage ?: return
        if (sharing || conversation.isEmpty()) return
        sharing = true
        action { ticket ->
            try { val result = api.share(conversation, message.id, scope, expiry); if (ticket == revision) { shareUrl = result.url; shareId = result.id } }
            finally { if (ticket == revision) sharing = false }
        }
    }
    fun revokeShare() {
        if (shareId.isEmpty() || sharing) return
        sharing = true
        action { ticket ->
            try {
                api.request(listOf("api", "conversation-shares", shareId), JSONObject(), "DELETE")
                if (ticket == revision) { shareUrl = ""; shareId = ""; shareMessage = null; notice = "分享链接已撤销" }
            } finally { if (ticket == revision) sharing = false }
        }
    }
    fun toggleFavorite(message: ChatMessage, onChanged: (String) -> Unit) {
        if (favoriteBusy != null) return
        favoriteBusy = message.id
        action { ticket ->
            try { val id = api.favorite(message.id, message.favoriteId.isEmpty()); if (ticket == revision) { onChanged(id); menuMessage = null; notice = if (id.isEmpty()) "已取消收藏" else "已加入收藏" } }
            finally { if (ticket == revision) favoriteBusy = null }
        }
    }
    fun loadFavorites() {
        favoritesLoading = true
        action { ticket ->
            try { val rows = attachmentRows(api.request(listOf("api", "favorites")).optJSONArray("favorites")); if (ticket == revision) favorites = rows }
            finally { if (ticket == revision) favoritesLoading = false }
        }
    }
    fun removeFavorite(row: JSONObject) = action { ticket ->
        api.request(listOf("api", "favorites", row.getString("id")), JSONObject(), "DELETE")
        if (ticket == revision) favorites = favorites.filterNot { it.optString("id") == row.optString("id") }
    }
}
