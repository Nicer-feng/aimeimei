package asia.feng.aimeimei

import android.app.Application
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.OpenableColumns
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

internal data class IncomingShareImage(val file: File, val name: String, val mime: String)
internal data class IncomingSharePayload(val id: String, val text: String, val images: List<IncomingShareImage>,
                                      val owner: String, val receivedAt: Long)

internal const val INCOMING_RECEIPT = "asia.feng.aimeimei.incoming.receipt"
private const val INCOMING_TEXT_LIMIT = 100000
private const val INCOMING_IMAGE_LIMIT = 20L * 1024 * 1024
private const val INCOMING_EXPIRY = 60L * 60 * 1000
private val incomingImageTypes = mapOf("image/jpeg" to "jpg", "image/png" to "png", "image/webp" to "webp")

internal fun saveIncomingShareReceipt(intent: Intent?, state: Bundle) {
    if (intent?.action !in listOf(Intent.ACTION_SEND, Intent.ACTION_SEND_MULTIPLE)) return
    val receipt = runCatching { intent?.getStringExtra(INCOMING_RECEIPT) }.getOrNull() ?: return
    if (receipt.matches(Regex("[a-fA-F0-9-]{36}"))) state.putString(INCOMING_RECEIPT, receipt)
}

internal fun restoreIncomingShareReceipt(intent: Intent?, state: Bundle?) {
    if (intent?.action !in listOf(Intent.ACTION_SEND, Intent.ACTION_SEND_MULTIPLE)) return
    val receipt = runCatching { state?.getString(INCOMING_RECEIPT) }.getOrNull() ?: return
    if (receipt.matches(Regex("[a-fA-F0-9-]{36}"))) intent?.putExtra(INCOMING_RECEIPT, receipt)
}

// 只读取本地分享内容；账号确认和显式导入之后，聊天模块才接管自己的草稿副本。
internal class IncomingShareController(private val app: Application, private val scope: CoroutineScope) {
    private val root get() = File(app.cacheDir, "incoming-shares").apply { mkdirs() }
    private val receipts = app.getSharedPreferences("incoming_share_receipts", 0)
    private var currentAccount = ""
    private var revision = 0
    private var job: Job? = null
    private var saveJob: Job? = null
    private val diskLock = Any()
    var pending by mutableStateOf<IncomingSharePayload?>(null); private set
    var preparing by mutableStateOf(false); private set
    var importing by mutableStateOf(false); private set
    var waitingForLogin by mutableStateOf(false); private set
    var deferred by mutableStateOf(false); private set
    var error by mutableStateOf(""); private set

    init {
        val ticket = revision
        job = scope.launch {
            val restored = withContext(Dispatchers.IO) { restore() }
            if (ticket == revision) {
                if (restored != null && currentAccount.isNotBlank() && restored.owner.isNotBlank() && restored.owner != currentAccount) {
                    delete(restored.id)
                } else {
                    pending = restored?.let { if (currentAccount.isNotBlank()) it.copy(owner = currentAccount) else it }
                    if (restored != null) { persistPending(); cleanupOthers(restored.id) }
                }
            }
        }
    }

    fun bindAccount(accountId: String) {
        if (accountId == currentAccount) return
        val previous = currentAccount
        currentAccount = accountId
        if (accountId.isNotBlank() && waitingForLogin) { waitingForLogin = false; deferred = false }
        val row = pending
        if (previous.isNotBlank() || (row?.owner?.isNotBlank() == true && row.owner != accountId)) {
            discard()
        } else if (accountId.isNotBlank() && row != null) {
            pending = row.copy(owner = accountId)
            persistPending()
        }
    }

    fun accept(intent: Intent?, accountId: String): Boolean {
        if (intent == null || intent.action !in listOf(Intent.ACTION_SEND, Intent.ACTION_SEND_MULTIPLE)) return false
        // Activity 重建或进程恢复不能再次导入同一份 Intent；标记不含原始文字或 URI。
        val receipt = runCatching { intent.getStringExtra(INCOMING_RECEIPT) }.getOrNull()
        if (!receipt.isNullOrBlank() && receipt == receipts.getString("last", null)) return true
        val id = UUID.randomUUID().toString()
        intent.putExtra(INCOMING_RECEIPT, id)
        receipts.edit().putString("last", id).apply()
        val old = pending
        revision++; job?.cancel(); saveJob?.cancel(); pending = null; preparing = true; importing = false; waitingForLogin = false; deferred = false; error = ""
        old?.let { delete(it.id) }
        currentAccount = accountId
        val ticket = revision
        job = scope.launch {
            var retained = false
            try {
                val row = withContext(Dispatchers.IO) { prepare(intent, id, accountId) }
                if (ticket != revision) return@launch
                if (row.owner.isNotBlank() && row.owner != currentAccount) return@launch
                val bound = row.copy(owner = currentAccount)
                pending = bound; retained = true; persistPending(); cleanupOthers(id)
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) {
                if (ticket == revision) error = if (failure is IllegalArgumentException) failure.message.orEmpty() else "无法读取分享内容，请回到原应用重新分享"
            } finally {
                if (!retained) delete(id)
                if (ticket == revision) preparing = false
            }
        }
        return true
    }

    fun editText(value: String) {
        if (importing || preparing) return
        val row = pending ?: return
        if (value.length > INCOMING_TEXT_LIMIT) { error = "分享文字不能超过 10 万字"; return }
        pending = row.copy(text = value); error = ""; persistPending()
    }

    fun removeImage(image: IncomingShareImage) {
        if (importing || preparing) return
        val row = pending ?: return
        pending = row.copy(images = row.images.filterNot { it.file == image.file })
        image.file.delete(); error = ""; persistPending()
    }

    fun discard() {
        val old = pending
        revision++; job?.cancel(); saveJob?.cancel(); pending = null; preparing = false; importing = false; waitingForLogin = false; deferred = false; error = ""
        old?.let { delete(it.id) }
    }

    fun requestLogin() { if (!importing) { waitingForLogin = true; deferred = true } }
    fun deferPreview() { if (!preparing && !importing) deferred = true }
    fun resumePreview() { deferred = false; waitingForLogin = false }

    fun confirm(accountId: String, import: suspend (IncomingSharePayload) -> Boolean) {
        val row = pending ?: return
        if (accountId.isBlank() || accountId != currentAccount || preparing || importing) return
        if (row.owner.isNotBlank() && row.owner != accountId) { discard(); return }
        if (row.text.isBlank() && row.images.isEmpty()) { error = "请保留文字或至少一张图片"; return }
        if (System.currentTimeMillis() - row.receivedAt > INCOMING_EXPIRY) { discard(); error = "分享内容已过期，请从原应用重新分享"; return }
        val ticket = revision
        importing = true; error = ""
        job = scope.launch {
            try {
                val accepted = import(row.copy(owner = accountId))
                if (ticket == revision) {
                    if (accepted && currentAccount == accountId) { pending = null; saveJob?.cancel(); delete(row.id) }
                    else error = "暂时无法加入草稿，请先完成当前操作再试"
                }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) {
                if (ticket == revision) error = if (failure is IllegalArgumentException) failure.message.orEmpty() else "加入草稿未完成，分享内容已保留，请重试"
            } finally { if (ticket == revision) importing = false }
        }
    }

    private suspend fun prepare(intent: Intent, id: String, owner: String): IncomingSharePayload {
        val clip = intent.clipData
        val raw = intent.getCharSequenceExtra(Intent.EXTRA_TEXT) ?: clip?.let { data ->
            val items = (0 until data.itemCount.coerceAtMost(6)).mapNotNull { index ->
                val item = data.getItemAt(index)
                item.text ?: if (intent.type.orEmpty().startsWith("text/") && item.uri?.scheme in setOf("http", "https")) item.uri.toString() else null
            }
            require(items.sumOf { it.length.toLong() } <= INCOMING_TEXT_LIMIT) { "分享文字不能超过 10 万字，请分段添加" }
            items.joinToString("\n")
        }
        require((raw?.length ?: 0) <= INCOMING_TEXT_LIMIT) { "分享文字不能超过 10 万字，请分段添加" }
        val text = raw?.toString().orEmpty().trim()
        val uris = sharedUris(intent)
        require(uris.size <= 5) { "一次最多分享 5 张图片，请分批添加" }
        require(text.isNotBlank() || uris.isNotEmpty()) { "没有可接收的文字或图片，请在原应用重新选择" }
        val directory = File(root, id).apply { mkdirs() }
        try {
            val images = uris.map { copyImage(it, directory) }
            currentCoroutineContext().ensureActive()
            return IncomingSharePayload(id, text, images, owner, System.currentTimeMillis()).also { save(it) }
        } catch (failure: Exception) { directory.deleteRecursively(); throw failure }
    }

    @Suppress("DEPRECATION")
    private fun sharedUris(intent: Intent): List<Uri> {
        val streams = if (intent.action == Intent.ACTION_SEND_MULTIPLE) {
            if (Build.VERSION.SDK_INT >= 33) intent.getParcelableArrayListExtra(Intent.EXTRA_STREAM, Uri::class.java).orEmpty()
            else intent.getParcelableArrayListExtra<Uri>(Intent.EXTRA_STREAM).orEmpty()
        } else listOfNotNull(if (Build.VERSION.SDK_INT >= 33) intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java) else intent.getParcelableExtra<Uri>(Intent.EXTRA_STREAM))
        // 某些相册仅提供 ClipData；文字 ClipData 的 URI 不可视为待下载链接。
        val clipped = intent.clipData?.let { data -> (0 until data.itemCount.coerceAtMost(6)).mapNotNull { data.getItemAt(it).uri }
            .filterNot { intent.type.orEmpty().startsWith("text/") && it.scheme in setOf("http", "https") } }.orEmpty()
        return (streams + clipped).distinct().also { require(it.size <= 5) { "一次最多分享 5 张图片，请分批添加" } }
    }

    private suspend fun copyImage(uri: Uri, directory: File): IncomingShareImage {
        require(uri.scheme == "content") { "图片必须来自系统相册或应用提供的安全分享，请勿使用文件路径或远程图片地址" }
        // 导出入口不可借自身的非导出 Provider 读取其他账号私有图片。
        require(uri.authority?.substringAfterLast('@') !in setOf("${app.packageName}.updates", "${app.packageName}.attachments")) { "请回到原应用选择图片后重新分享" }
        var name = ""
        app.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)?.use { cursor ->
            if (cursor.moveToFirst()) {
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (nameIndex >= 0) name = cursor.getString(nameIndex).orEmpty().substringAfterLast('/').substringAfterLast('\\').take(180)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) require(cursor.getLong(sizeIndex) <= INCOMING_IMAGE_LIMIT) { "单张图片不能超过 20MB" }
            }
        }
        val extension = name.substringAfterLast('.', "").lowercase()
        var mime = app.contentResolver.getType(uri).orEmpty().substringBefore(';').trim().lowercase()
        if (mime.isBlank() || mime == "application/octet-stream") mime = when (extension) { "jpg", "jpeg" -> "image/jpeg"; "png" -> "image/png"; "webp" -> "image/webp"; else -> "" }
        val suffix = incomingImageTypes[mime] ?: throw IllegalArgumentException("图片支持 JPG、PNG、WebP，请转换后重新分享")
        if (name.isBlank()) name = "分享图片.$suffix"
        else if (extension !in listOf("jpg", "jpeg", "png", "webp")) name = name.take(170) + ".$suffix"
        val file = File(directory, "${UUID.randomUUID()}.$suffix")
        try {
            val source = app.contentResolver.openInputStream(uri) ?: throw IllegalArgumentException("无法读取分享图片，请重新分享")
            source.use { input -> file.outputStream().use { output ->
                val bytes = ByteArray(65536); var count = 0L
                while (true) { currentCoroutineContext().ensureActive(); val size = input.read(bytes); if (size < 0) break
                    count += size; require(count <= INCOMING_IMAGE_LIMIT) { "单张图片不能超过 20MB" }; output.write(bytes, 0, size) }
            } }
            currentCoroutineContext().ensureActive()
            require(file.length() > 0 && chatImageBoundsValid(file)) { "分享图片无法预览，请更换原图或转换为 JPG" }
            return IncomingShareImage(file, name, mime)
        } catch (failure: Exception) { file.delete(); throw failure }
    }

    private fun persistPending() {
        val row = pending ?: return
        saveJob?.cancel()
        saveJob = scope.launch { withContext(Dispatchers.IO) { synchronized(diskLock) { if (pending == row) save(row) } } }
    }

    private fun save(row: IncomingSharePayload) = synchronized(diskLock) {
        val folder = File(root, row.id)
        if (!folder.isDirectory) return@synchronized
        val json = JSONObject().put("id", row.id).put("text", row.text).put("owner", row.owner).put("received_at", row.receivedAt)
            .put("images", JSONArray(row.images.map { JSONObject().put("file", it.file.name).put("name", it.name).put("mime", it.mime) }))
        val temporary = File(folder, "payload.tmp")
        temporary.writeText(json.toString())
        if (!temporary.renameTo(File(folder, "payload.json"))) temporary.delete()
    }

    private suspend fun restore(): IncomingSharePayload? {
        val context = currentCoroutineContext()
        return synchronized(diskLock) {
        var latest: IncomingSharePayload? = null
        for (folder in root.listFiles().orEmpty().sortedByDescending { it.lastModified() }) {
            context.ensureActive()
            // 新分享可能尚未写好清单；取消的恢复扫描不能删除正在复制的目录。
            if (!File(folder, "payload.json").isFile) {
                if (folder.lastModified() < System.currentTimeMillis() - INCOMING_EXPIRY) folder.deleteRecursively()
                continue
            }
            var expired = false
            val row = runCatching {
                require(folder.isDirectory && folder.name.matches(Regex("[a-fA-F0-9-]{36}")))
                val file = File(folder, "payload.json"); require(file.isFile && file.length() <= 512 * 1024)
                val json = JSONObject(file.readText()); val received = json.getLong("received_at")
                expired = received > System.currentTimeMillis() + 60000 || System.currentTimeMillis() - received > INCOMING_EXPIRY
                require(!expired)
                val text = json.getString("text"); require(text.length <= INCOMING_TEXT_LIMIT)
                val items = json.getJSONArray("images"); require(items.length() <= 5)
                val images = (0 until items.length()).map { index ->
                    val item = items.getJSONObject(index); val image = File(folder, item.getString("file"))
                    require(image.canonicalFile.parentFile == folder.canonicalFile && image.isFile && image.length() in 1..INCOMING_IMAGE_LIMIT)
                    val mime = item.getString("mime"); require(mime in incomingImageTypes.keys && chatImageBoundsValid(image))
                    IncomingShareImage(image, item.getString("name").take(180), mime)
                }
                require(text.isNotBlank() || images.isNotEmpty())
                IncomingSharePayload(folder.name, text, images, json.optString("owner"), received)
            }.getOrNull()
            context.ensureActive()
            if (row != null && (latest == null || row.receivedAt > latest.receivedAt)) latest = row
            else if (row == null && (expired || folder.lastModified() < System.currentTimeMillis() - INCOMING_EXPIRY)) folder.deleteRecursively()
        }
        latest
        }
    }

    // 只有主线程已确认接收代次的当前分享才清理其他目录。
    private fun cleanupOthers(id: String) = synchronized(diskLock) {
        root.listFiles().orEmpty().filter { it.name != id }.forEach { it.deleteRecursively() }
    }

    private fun delete(id: String) = synchronized(diskLock) {
        if (id.matches(Regex("[a-fA-F0-9-]{36}"))) File(root, id).deleteRecursively()
    }
}
