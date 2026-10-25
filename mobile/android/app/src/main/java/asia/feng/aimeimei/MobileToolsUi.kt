package asia.feng.aimeimei

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.core.content.FileProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.util.Locale

@Composable
internal fun OcrScreen(model: PlatformViewModel, onUse: () -> Unit) {
    val state = model.tools.mobile
    val context = LocalContext.current
    var pickerOwner by rememberSaveable { mutableStateOf("") }
    var cameraPath by rememberSaveable { mutableStateOf("") }
    var preview by remember { mutableStateOf(false) }
    var retry by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf<OcrRecord?>(null) }
    var query by rememberSaveable { mutableStateOf("") }
    val selectable = !state.preparing && !state.processing && !state.historyLoading && !model.streaming
    val images = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null && pickerOwner == model.account?.id && !model.streaming) state.select(uri)
    }
    val documents = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null && pickerOwner == model.account?.id && !model.streaming) state.select(uri)
    }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { saved ->
        val root = File(context.cacheDir, "chat-attachments/ocr-camera")
        val file = cameraPath.takeIf { it.isNotBlank() }?.let(::File)?.takeIf { it.parentFile?.canonicalFile == root.canonicalFile }
        if (file != null && saved && pickerOwner == model.account?.id && !model.streaming) state.select(FileProvider.getUriForFile(context, "${context.packageName}.attachments", file))
        else file?.delete()
        cameraPath = ""
    }
    LaunchedEffect(model.account?.id) { state.loadOcr() }
    LazyColumn(Modifier.fillMaxSize().testTag("ocr-list"), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item {
            Text("把手写内容变成可编辑文字", style = MaterialTheme.typography.titleLarge)
            Text("拍照或选图后预览，确认再开始识别。单张不超过 10MB。", Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall)
        }
        item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = {
                pickerOwner = model.account?.id.orEmpty()
                try { images.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }
                catch (_: Exception) { model.tools.report("无法打开相册，请尝试选择文件") }
            }, enabled = selectable) { Text("选择图片") }
            OutlinedButton(onClick = {
                pickerOwner = model.account?.id.orEmpty()
                try {
                    val root = File(context.cacheDir, "chat-attachments/ocr-camera").apply { mkdirs() }
                    root.listFiles()?.filter { it.lastModified() < System.currentTimeMillis() - 3600000 }?.forEach { it.delete() }
                    val file = File.createTempFile("ocr-camera-", ".jpg", root); cameraPath = file.path
                    camera.launch(FileProvider.getUriForFile(context, "${context.packageName}.attachments", file))
                } catch (_: Exception) { model.tools.report("无法打开相机，请从相册选择图片") }
            }, enabled = selectable) { Text("拍照") }
            TextButton(onClick = { pickerOwner = model.account?.id.orEmpty(); try { documents.launch(arrayOf("image/*")) } catch (_: Exception) { model.tools.report("无法打开系统文件选择器") } }, enabled = selectable) { Text("文件") }
        } }
        if (state.preparing) item { LinearProgressIndicator(Modifier.fillMaxWidth()); Text("正在准备图片预览…") }
        state.image?.let { image -> item {
            val bitmap by produceState<android.graphics.Bitmap?>(null, image.file) { value = withContext(Dispatchers.IO) { runCatching { decodeChatImage(image.file, 1024) }.getOrNull() } }
            OutlinedCard(Modifier.fillMaxWidth().clickable(enabled = bitmap != null) { preview = true }) {
                Box(Modifier.fillMaxWidth().height(180.dp), contentAlignment = Alignment.Center) {
                    if (bitmap != null) Image(bitmap!!.asImageBitmap(), "待识别图片", Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
                    else Text(if (image.mime == "image/tiff") "TIFF 暂无法预览，可继续识别" else "正在准备预览…")
                }
                Text(image.name, Modifier.padding(12.dp), style = MaterialTheme.typography.bodySmall)
            }
        } }
        item {
            Button(onClick = { if (state.attempted) retry = true else state.recognize() }, enabled = selectable && state.image != null, modifier = Modifier.fillMaxWidth().testTag("ocr-recognize")) {
                Text(if (state.processing) state.phase else if (state.attempted) "再次识别" else "开始识别")
            }
            if (state.processing) {
                if (state.phase == "正在上传图片") LinearProgressIndicator(progress = { state.progress / 100f }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                else LinearProgressIndicator(Modifier.fillMaxWidth().padding(top = 8.dp))
                Text(state.phase, Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall)
            }
            if (state.ocrError.isNotBlank()) Text(state.ocrError, Modifier.padding(top = 8.dp), color = MaterialTheme.colorScheme.error)
        }
        item { Row(verticalAlignment = Alignment.CenterVertically) {
            Text("最近识别", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
            TextButton(onClick = state::loadOcr, enabled = !state.historyLoading && !state.processing) { Text("刷新记录") }
        } }
        item { OutlinedTextField(query, { query = it }, label = { Text("搜索识别记录") }, singleLine = true, modifier = Modifier.fillMaxWidth()) }
        if (state.historyLoading) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        if (state.historyError.isNotBlank()) item { Text(state.historyError, color = MaterialTheme.colorScheme.error) }
        val rows = state.records.filter { "${it.name} ${it.text}".contains(query, ignoreCase = true) }
        if (rows.isEmpty() && !state.historyLoading && state.historyError.isBlank()) item { Text(if (query.isBlank()) "还没有识别记录" else "没有匹配的识别记录") }
        items(rows, key = { it.id }) { row ->
            OutlinedCard(Modifier.fillMaxWidth().clickable(enabled = !state.processing) { state.view(row) }.testTag("ocr-record-${row.id}")) {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(row.name, style = MaterialTheme.typography.titleSmall)
                    Text(if (row.status == "completed") row.text else "识别失败，请更换清晰原图", maxLines = 3, overflow = TextOverflow.Ellipsis)
                    Row {
                        TextButton(onClick = { state.view(row) }, enabled = !state.processing) { Text("查看结果") }
                        TextButton(onClick = { deleting = row }, enabled = selectable) { Text("删除记录") }
                    }
                }
            }
        }
    }
    if (preview) state.image?.let { image -> FullscreenChatImage(ChatAttachment("", image.name, image.mime, image.file.length(), true), image.file, false, "", { preview = false }, {}) }
    if (retry) AlertDialog(onDismissRequest = { retry = false }, title = { Text("重新识别这张图片？") }, text = { Text("可以先刷新记录核对上次结果。继续会重新上传并调用识别服务。") },
        confirmButton = { TextButton(onClick = { retry = false; state.recognize() }) { Text("确认再次识别") } }, dismissButton = { TextButton(onClick = { retry = false; state.loadOcr() }) { Text("先刷新记录") } })
    deleting?.let { row -> AlertDialog(onDismissRequest = { if (!state.processing) deleting = null }, title = { Text("删除这条识别记录？") }, text = { Column { Text(row.name); if (state.ocrError.isNotBlank()) Text(state.ocrError, color = MaterialTheme.colorScheme.error) } },
        confirmButton = { TextButton(onClick = { state.delete(row) { deleting = null } }, enabled = !state.processing) { Text("确认删除") } }, dismissButton = { TextButton(onClick = { deleting = null }, enabled = !state.processing) { Text("取消") } }) }
    state.result?.let { row -> OcrResultDialog(model, row, onUse) }
}

@Composable
private fun OcrResultDialog(model: PlatformViewModel, row: OcrRecord, onUse: () -> Unit) {
    val state = model.tools.mobile; val context = LocalContext.current
    var text by remember(row.id) { mutableStateOf(row.text) }
    var importing by remember { mutableStateOf(false) }
    fun apply(replace: Boolean) { model.editDraft(if (replace || model.draft.isBlank()) text else model.draft + "\n\n" + text); state.view(null); importing = false; onUse() }
    Dialog(onDismissRequest = { state.view(null) }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.systemBarsPadding().imePadding().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("识别结果", Modifier.weight(1f), style = MaterialTheme.typography.titleLarge)
                    TextButton(onClick = { state.view(null) }) { Text("关闭") }
                }
                Text(row.name, style = MaterialTheme.typography.labelMedium)
                if (row.status != "completed") Text("本次未识别出有效文字，请更换清晰的原图。", color = MaterialTheme.colorScheme.error)
                Text("可修改后复制或带入聊天，原识别记录会保留。", style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(text, { text = it }, modifier = Modifier.fillMaxWidth().weight(1f).testTag("ocr-result-text"), enabled = row.status == "completed")
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    OutlinedButton(onClick = { copyChatText(context, text) }, enabled = row.status == "completed" && text.isNotBlank()) { Text("复制文字") }
                    Button(onClick = { if (model.draft.isNotBlank()) importing = true else apply(true) }, enabled = row.status == "completed" && text.isNotBlank() && !model.streaming && !model.busy) { Text("带入聊天") }
                }
            }
        }
    }
    if (importing) AlertDialog(onDismissRequest = { importing = false }, title = { Text("输入框里已有草稿") }, text = { Text("选择追加识别文字，或替换当前草稿。带入后由你确认发送。") },
        confirmButton = { TextButton(onClick = { apply(false) }) { Text("追加到草稿") } },
        dismissButton = { Row { TextButton(onClick = { apply(true) }) { Text("替换草稿") }; TextButton(onClick = { importing = false }) { Text("取消") } } })
}

internal fun usageMoney(value: Double): String = "¥" + String.format(Locale.ROOT, "%.4f", value.takeIf { it.isFinite() && it >= 0 } ?: 0.0)

@Composable
internal fun PersonalUsageScreen(model: PlatformViewModel, onOpen: () -> Unit) {
    val state = model.tools.mobile
    var range by rememberSaveable { mutableIntStateOf(7) }
    var details by remember { mutableStateOf<JSONObject?>(null) }
    LaunchedEffect(model.account?.id) { state.loadUsage() }
    val report = state.usage
    val days = attachmentRows(report?.optJSONArray("days")).takeLast(range)
    val total = days.sumOf { it.optLong("total_tokens") }
    val maximum = days.maxOfOrNull { it.optLong("total_tokens") }?.coerceAtLeast(1) ?: 1
    LazyColumn(Modifier.fillMaxSize().testTag("personal-usage-list"), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        item { Row(verticalAlignment = Alignment.CenterVertically) {
            Text("我的使用情况", Modifier.weight(1f), style = MaterialTheme.typography.titleLarge)
            TextButton(onClick = state::loadUsage, enabled = !state.usageLoading) { Text("刷新") }
        } }
        if (state.usageLoading) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        if (state.usageError.isNotBlank()) item { Text(state.usageError, color = MaterialTheme.colorScheme.error); TextButton(onClick = state::loadUsage, enabled = !state.usageLoading) { Text("重试") } }
        if (report != null) {
            item { Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) { listOf(7 to "近7天", 30 to "近30天", 365 to "近一年").forEach { (value, label) ->
                FilterChip(range == value, { range = value }, label = { Text(label) })
            } } }
            item { OutlinedCard(Modifier.fillMaxWidth()) { Column(Modifier.padding(20.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("所选时间范围", style = MaterialTheme.typography.labelMedium)
                Text("${tokenNumber(total)} Token", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.testTag("personal-usage-total"))
                Text("${tokenNumber(days.sumOf { it.optLong("request_count") })} 次调用 · 估算费用 ${usageMoney(days.sumOf { it.optDouble("estimated_cost", 0.0) })}")
            } } }
            item { report.optJSONObject("summary")?.let { summary ->
                Text("累计 ${tokenNumber(summary.optLong("total_tokens"))} Token · ${summary.optLong("active_days")} 个活跃日 · ${summary.optLong("conversation_count")} 段聊天", style = MaterialTheme.typography.bodySmall)
            }; Text("用量与估算费用以已保存的记录为准。", style = MaterialTheme.typography.bodySmall) }
            item { Text("每日用量 · 点击查看详情", style = MaterialTheme.typography.titleMedium) }
            if (days.isEmpty()) item { Text("这个时间范围还没有用量记录") }
            items(days.asReversed(), key = { it.optString("date") }) { day ->
                OutlinedCard(Modifier.fillMaxWidth().clickable { details = day }.testTag("usage-day-${day.optString("date")}")) {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row { Text(day.optString("date"), Modifier.weight(1f)); Text("${tokenNumber(day.optLong("total_tokens"))} Token") }
                        LinearProgressIndicator(progress = { (day.optLong("total_tokens").toDouble() / maximum).toFloat().coerceIn(0f, 1f) }, modifier = Modifier.fillMaxWidth())
                        Text("${day.optLong("request_count")} 次 · ${usageMoney(day.optDouble("estimated_cost", 0.0))}", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
            item { Text("累计常用模型", style = MaterialTheme.typography.titleMedium) }
            val models = attachmentRows(report.optJSONArray("top_models"))
            if (models.isEmpty()) item { Text("还没有模型使用记录") }
            items(models, key = { "${it.optString("model_name")}:${it.optString("model_code")}" }) { row ->
                ListItem(headlineContent = { Text(row.optString("model_name")) }, supportingContent = { Text("${tokenNumber(row.optLong("total_tokens"))} Token · ${row.optLong("request_count")} 次 · ${usageMoney(row.optDouble("estimated_cost", 0.0))}") })
            }
            item { Text("累计用量较多的聊天", style = MaterialTheme.typography.titleMedium) }
            items(attachmentRows(report.optJSONArray("top_conversations")), key = { it.optString("conversation_id") }) { row ->
                ListItem(headlineContent = { Text(row.optString("title")) }, supportingContent = { Text("${tokenNumber(row.optLong("total_tokens"))} Token · ${row.optLong("request_count")} 次") },
                    modifier = Modifier.clickable(enabled = !model.busy && !model.streaming) { model.openSearchResult(ChatSearchResult("usage", "conversation", row.optString("conversation_id"), "", row.optString("title"), "", ""), onOpen) })
            }
        }
    }
    details?.let { day -> AlertDialog(onDismissRequest = { details = null }, title = { Text(day.optString("date")) }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("输入：${tokenNumber(day.optLong("input_tokens"))} Token"); Text("输出：${tokenNumber(day.optLong("output_tokens"))} Token")
            Text("合计：${tokenNumber(day.optLong("total_tokens"))} Token"); Text("调用：${day.optLong("request_count")} 次")
            Text("估算费用：${usageMoney(day.optDouble("estimated_cost", 0.0))}")
            attachmentRows(report?.optJSONObject("day_models")?.optJSONArray(day.optString("date"))).forEach { row ->
                HorizontalDivider(); Text(row.optString("model_name")); Text("${tokenNumber(row.optLong("total_tokens"))} Token · ${row.optLong("request_count")} 次 · ${usageMoney(row.optDouble("estimated_cost", 0.0))}")
            }
        }
    }, confirmButton = { TextButton(onClick = { details = null }) { Text("关闭") } }) }
}
