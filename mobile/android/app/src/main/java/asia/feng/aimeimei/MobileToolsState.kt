package asia.feng.aimeimei

import android.app.Application
import android.net.Uri
import android.provider.OpenableColumns
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.File
import java.util.UUID

internal data class OcrImage(val file: File, val name: String, val mime: String)
internal data class OcrRecord(val id: String, val name: String, val text: String, val status: String, val error: String) {
    companion object {
        fun parse(row: JSONObject) = OcrRecord(row.getString("id"), row.optString("filename"), row.optString("recognized_text"), row.optString("status"), row.optString("error_message"))
    }
}

// 相册内容只复制进私有缓存；扩展名缺失时按实际 MIME 补齐，保留原始图供识别。
internal fun prepareOcrImage(app: Application, uri: Uri, folder: File): OcrImage {
    require(uri.scheme == "content") { "请从系统相册或文件中选择图片" }
    var name = ""
    app.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { if (it.moveToFirst()) name = it.getString(0).orEmpty().substringAfterLast('/').take(180) }
    val suffixes = mapOf("jpg" to "image/jpeg", "jpeg" to "image/jpeg", "png" to "image/png", "webp" to "image/webp", "bmp" to "image/bmp", "gif" to "image/gif", "tif" to "image/tiff", "tiff" to "image/tiff")
    val extension = name.substringAfterLast('.', "").lowercase()
    var mime = app.contentResolver.getType(uri).orEmpty().lowercase()
    if (mime == "image/x-ms-bmp") mime = "image/bmp"
    if (mime.isBlank() || mime == "application/octet-stream") mime = suffixes[extension].orEmpty()
    require(mime in suffixes.values) { "请选择 JPG、PNG、WebP、BMP、GIF 或 TIFF 图片" }
    val suffix = suffixes.entries.first { it.value == mime }.key
    if (name.isBlank()) name = "手写图片.$suffix"
    else if (suffixes[extension] != mime) name = name.take(170) + ".$suffix"
    folder.mkdirs(); val file = File(folder, UUID.randomUUID().toString() + ".$suffix")
    try {
        val input = app.contentResolver.openInputStream(uri) ?: error("无法读取图片")
        input.use { source -> file.outputStream().use { output ->
            val bytes = ByteArray(65536); var total = 0L
            while (true) { val count = source.read(bytes); if (count < 0) break; total += count; require(total <= 10L * 1024 * 1024) { "图片不能超过 10MB" }; output.write(bytes, 0, count) }
            require(total > 0) { "图片内容为空，请重新选择" }
        } }
        val valid = if (mime == "image/tiff") file.inputStream().use { source ->
            val header = ByteArray(4); source.read(header) == 4 && (header.contentEquals(byteArrayOf(73, 73, 42, 0)) || header.contentEquals(byteArrayOf(77, 77, 0, 42)))
        } else chatImageBoundsValid(file)
        require(valid) { "图片无法读取，请更换清晰的原图" }
        return OcrImage(file, name, mime)
    } catch (failure: Exception) { file.delete(); throw failure }
}

internal class MobileToolsState(private val app: Application, private val api: PlatformApi, private val scope: CoroutineScope,
                                private val onUnauthorized: () -> Unit) {
    private var owner = ""
    private var revision = 0
    private var historyJob: Job? = null
    private var processJob: Job? = null
    private var usageJob: Job? = null
    private val directory get() = File(app.cacheDir, "native-ocr").apply { mkdirs() }
    var image by mutableStateOf<OcrImage?>(null); private set
    var preparing by mutableStateOf(false); private set
    var processing by mutableStateOf(false); private set
    var phase by mutableStateOf(""); private set
    var progress by mutableStateOf(0); private set
    var attempted by mutableStateOf(false); private set
    var ocrError by mutableStateOf(""); private set
    var records by mutableStateOf<List<OcrRecord>>(emptyList()); private set
    var result by mutableStateOf<OcrRecord?>(null); private set
    var historyLoading by mutableStateOf(false); private set
    var historyError by mutableStateOf(""); private set
    var usage by mutableStateOf<JSONObject?>(null); private set
    var usageLoading by mutableStateOf(false); private set
    var usageError by mutableStateOf(""); private set
    fun bind(accountId: String) {
        if (owner == accountId) return
        owner = accountId; revision++; historyJob?.cancel(); processJob?.cancel(); usageJob?.cancel()
        image = null; preparing = false; processing = false; progress = 0; attempted = false; phase = ""; ocrError = ""
        records = emptyList(); result = null; historyLoading = false; historyError = ""; usage = null; usageLoading = false; usageError = ""
        directory.deleteRecursively()
    }
    private fun failure(error: Exception): String {
        if (error is ApiFailure && error.status == 401) onUnauthorized()
        return when (error) {
            is ApiFailure -> error.message.orEmpty()
            is IllegalArgumentException -> error.message ?: "所选图片不符合要求"
            else -> "操作未完成，请检查网络后重试"
        }
    }
    fun select(uri: Uri) {
        if (owner.isBlank() || preparing || processing) return
        val ticket = revision
        processJob = scope.launch {
            preparing = true; ocrError = ""; var prepared: OcrImage? = null
            try {
                val copied = withContext(Dispatchers.IO) { prepareOcrImage(app, uri, directory).also { prepared = it } }
                if (ticket == revision) { image?.file?.delete(); image = copied; prepared = null; result = null; attempted = false; progress = 0; phase = "" }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { if (ticket == revision) ocrError = failure(error) }
            finally { prepared?.file?.delete(); if (ticket == revision) preparing = false }
        }
    }
    fun loadOcr() {
        if (owner.isBlank() || historyLoading || processing) return
        val ticket = revision
        historyJob = scope.launch {
            historyLoading = true; historyError = ""
            try { val rows = api.ocrRecords(); if (ticket == revision) records = rows }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { if (ticket == revision) historyError = failure(error) }
            finally { if (ticket == revision) historyLoading = false }
        }
    }
    fun recognize() {
        val selected = image ?: return
        if (owner.isBlank() || preparing || processing || historyLoading) return
        val ticket = revision
        processJob = scope.launch {
            processing = true; attempted = true; ocrError = ""; phase = "正在上传图片"; progress = 0
            try {
                val row = api.recognizeOcr(selected) { percent -> scope.launch {
                    if (ticket == revision && processing) { progress = percent; if (percent >= 99) phase = "正在识别文字" }
                } }
                if (ticket == revision) {
                    records = listOf(row) + records.filterNot { it.id == row.id }; result = row; progress = 100; phase = if (row.status == "completed") "识别完成" else "识别未成功"
                    if (row.status != "completed") ocrError = "没有识别出有效文字，请查看记录或更换清晰原图"
                }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { if (ticket == revision) { ocrError = failure(error) + "。可先刷新历史核对识别结果。"; phase = "识别结果尚未确认" } }
            finally { if (ticket == revision) processing = false }
        }
    }
    fun view(row: OcrRecord?) { result = row }
    fun delete(row: OcrRecord, done: () -> Unit) {
        if (processing || preparing || historyLoading || owner.isBlank()) return
        val ticket = revision
        processJob = scope.launch {
            processing = true; ocrError = ""; phase = "正在删除记录"
            try {
                api.request(listOf("api", "ocr", "tasks", row.id), JSONObject(), "DELETE")
                if (ticket == revision) { records = records.filterNot { it.id == row.id }; if (result?.id == row.id) result = null; done() }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { if (ticket == revision) ocrError = failure(error) }
            finally { if (ticket == revision) processing = false }
        }
    }
    fun loadUsage() {
        if (owner.isBlank() || usageLoading) return
        val ticket = revision
        usageJob = scope.launch {
            usageLoading = true; usageError = ""
            try { val row = api.request(listOf("api", "token-activity")); if (ticket == revision) usage = row }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { if (ticket == revision) usageError = failure(error) }
            finally { if (ticket == revision) usageLoading = false }
        }
    }
}
