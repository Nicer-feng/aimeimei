package asia.feng.aimeimei

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTransformGestures
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
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
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
import java.io.File

@Composable
internal fun AttachmentPicker(model: PlatformViewModel, enabled: Boolean) {
    val context = LocalContext.current
    var open by remember { mutableStateOf(false) }
    var cameraPath by rememberSaveable { mutableStateOf("") }
    var pickerOwner by rememberSaveable { mutableStateOf("") }
    var pickerConversation by rememberSaveable { mutableStateOf("") }
    fun sameContext() = pickerOwner == model.account?.id && pickerConversation == model.selected?.id.orEmpty()
    fun rememberContext() { pickerOwner = model.account?.id.orEmpty(); pickerConversation = model.selected?.id.orEmpty() }
    val images = rememberLauncherForActivityResult(ActivityResultContracts.PickMultipleVisualMedia(5)) { uris ->
        if (sameContext() && !model.streaming && model.pending == null) model.tools.addFiles(uris, true)
    }
    val files = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        if (sameContext() && !model.streaming && model.pending == null) model.tools.addFiles(uris, false)
    }
    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { saved ->
        val root = File(context.cacheDir, "chat-attachments/camera")
        val file = cameraPath.takeIf { it.isNotBlank() }?.let(::File)?.takeIf { it.parentFile?.canonicalFile == root.canonicalFile }
        if (file != null) {
            if (saved && sameContext() && !model.streaming && model.pending == null) {
                val uri = FileProvider.getUriForFile(context, "${context.packageName}.attachments", file)
                model.tools.addFiles(listOf(uri), true)
                // ContentProvider 的读取在后台完成，原相机文件由下一次相机操作或退出账号清理。
            } else file.delete()
        }
        cameraPath = ""
    }
    Box {
        TextButton(onClick = { open = true }, enabled = enabled, modifier = Modifier.testTag("attachment-picker")) { Text("添加") }
        DropdownMenu(open, { open = false }) {
            DropdownMenuItem(text = { Text("选择图片") }, onClick = {
                open = false; rememberContext()
                try { images.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) }
                catch (_: Exception) { model.tools.report("无法打开系统相册，请尝试文件选择") }
            })
            DropdownMenuItem(text = { Text("拍照") }, onClick = {
                open = false; rememberContext()
                try {
                    val root = File(context.cacheDir, "chat-attachments/camera").apply { mkdirs() }
                    root.listFiles()?.filter { it.lastModified() < System.currentTimeMillis() - 3600000 }?.forEach { it.delete() }
                    val file = File.createTempFile("camera-", ".jpg", root); cameraPath = file.path
                    camera.launch(FileProvider.getUriForFile(context, "${context.packageName}.attachments", file))
                } catch (_: Exception) { model.tools.report("无法打开相机，请使用相册选择图片") }
            })
            DropdownMenuItem(text = { Text("选择文件") }, onClick = {
                open = false; rememberContext()
                try { files.launch(arrayOf("*/*")) } catch (_: Exception) { model.tools.report("无法打开系统文件选择器") }
            })
        }
    }
}

@Composable
internal fun AttachmentCard(item: ChatAttachment, onOpen: () -> Unit, onRemove: (() -> Unit)? = null) {
    OutlinedCard(Modifier.fillMaxWidth().testTag("attachment-${item.clientKey}")) {
        Row(Modifier.fillMaxWidth().padding(start = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f).clickable(onClick = onOpen).padding(vertical = 10.dp)) {
                Text("${if (item.image) "图片" else "文件"} · ${item.name}", maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                Text(attachmentStatus(item), color = if (item.status == "failed") MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall)
            }
            if (onRemove != null) TextButton(onClick = onRemove) { Text("移除") }
        }
        if (item.status == "uploading") LinearProgressIndicator(progress = { item.progress / 100f }, modifier = Modifier.fillMaxWidth())
        if (item.status == "copying") LinearProgressIndicator(Modifier.fillMaxWidth())
    }
}

@Composable
internal fun ComposerAttachments(model: PlatformViewModel) {
    val tools = model.tools
    if (tools.attachments.isNotEmpty() || tools.quotes.isNotEmpty()) {
        Column(Modifier.fillMaxWidth().heightIn(max = 200.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            tools.quotes.forEachIndexed { index, quote ->
                Surface(color = MaterialTheme.colorScheme.secondaryContainer, shape = MaterialTheme.shapes.medium) {
                    Row(Modifier.padding(start = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("引用 · ${quote.text}", maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
                        TextButton(onClick = { tools.removeQuote(index) }, enabled = !model.streaming && model.pending == null) { Text("移除") }
                    }
                }
            }
            tools.attachments.forEach { item -> AttachmentCard(item, onOpen = {
                if (!item.image && item.id.isNotEmpty() && !item.ready) tools.refreshDocument(item)
                tools.showPreview(item)
            }, onRemove = if (!model.streaming && model.pending == null) ({ tools.removeAttachment(item) }) else null) }
        }
        if (tools.uploading) TextButton(onClick = tools::cancelUploads) { Text("取消上传") }
    }
    val speech = tools.speech
    if (speech.phase != "idle") OutlinedCard(Modifier.fillMaxWidth().testTag("speech-player")) {
        Column(Modifier.padding(horizontal = 12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(if (speech.phase == "preparing") "正在生成语音…" else "回答朗读", Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
                if (speech.phase != "preparing") TextButton(onClick = speech::toggle) { Text(if (speech.phase == "playing") "暂停" else "播放") }
                TextButton(onClick = speech::stop) { Text("关闭") }
            }
            if (speech.phase == "preparing") LinearProgressIndicator(Modifier.fillMaxWidth())
            else {
                Slider(value = speech.position.toFloat().coerceIn(0f, speech.duration.toFloat().coerceAtLeast(1f)),
                    onValueChange = { speech.seek(it.toInt()) }, valueRange = 0f..speech.duration.toFloat().coerceAtLeast(1f))
                Text("${audioTime(speech.position)} / ${audioTime(speech.duration)}", style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}

private fun audioTime(value: Int) = "%d:%02d".format(value / 60000, value / 1000 % 60)

@Composable
internal fun ChatToolsDialogs(model: PlatformViewModel) {
    if (model.account == null) return
    val context = LocalContext.current
    val tools = model.tools
    tools.menuMessage?.let { message ->
        AlertDialog(onDismissRequest = { tools.menuMessage = null }, title = { Text("消息操作") }, text = {
            Column {
                TextButton(onClick = { copyChatText(context, message.content); tools.menuMessage = null }) { Text("复制全文") }
                TextButton(onClick = { tools.quote(message) }, enabled = !model.streaming && model.pending == null) { Text("引用这条消息") }
                if (message.role == "assistant" && (message.id.toLongOrNull() ?: 0) > 0) {
                    TextButton(onClick = { model.toggleFavorite(message) }, enabled = tools.favoriteBusy == null && !model.streaming) { Text(if (message.favoriteId.isEmpty()) "收藏回答" else "取消收藏") }
                    TextButton(onClick = { tools.showVoices(message) }) { Text("朗读回答") }
                    TextButton(onClick = { tools.showShare(message) }) { Text("创建分享链接") }
                }
                TextButton(onClick = { shareChatText(context, message.content); tools.menuMessage = null }) { Text("通过其他应用分享文字") }
            }
        }, confirmButton = { TextButton(onClick = { tools.menuMessage = null }) { Text("关闭") } })
    }
    tools.voiceMessage?.let { message ->
        val config = tools.voiceConfig ?: return@let
        val voices = attachmentRows(config.optJSONArray("voices"))
        var voice by remember(message.id) { mutableStateOf(config.optString("default_voice")) }
        var speed by remember(message.id) { mutableFloatStateOf(config.optDouble("default_speed", 1.0).toFloat().coerceIn(.5f, 2f)) }
        AlertDialog(onDismissRequest = tools::closeVoices, title = { Text("朗读回答") }, text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text("选择音色", style = MaterialTheme.typography.labelLarge)
                Column(Modifier.heightIn(max = 220.dp).verticalScroll(rememberScrollState())) {
                    voices.forEach { option -> Row(Modifier.fillMaxWidth().clickable { voice = option.getString("id") }, verticalAlignment = Alignment.CenterVertically) {
                        RadioButton(selected = voice == option.optString("id"), onClick = { voice = option.getString("id") }); Text(option.optString("name"))
                    } }
                }
                Text("语速 ${"%.2f".format(speed)}×")
                Slider(speed, { speed = it }, valueRange = .5f..2f, steps = 5)
                if (message.content.length > config.optInt("long_text_threshold", 5000)) Text("回答较长，生成语音可能需要一些时间。", style = MaterialTheme.typography.bodySmall)
            }
        }, confirmButton = { TextButton(onClick = { tools.startSpeech(message, voice, speed) }, enabled = voices.any { it.optString("id") == voice }) { Text("开始朗读") } },
            dismissButton = { TextButton(onClick = tools::closeVoices) { Text("取消") } })
    }
    tools.shareMessage?.let { message ->
        var scope by remember(message.id) { mutableStateOf("assistant") }
        var expiry by remember(message.id) { mutableIntStateOf(86400) }
        var expiryMenu by remember { mutableStateOf(false) }
        var revoke by remember { mutableStateOf(false) }
        AlertDialog(onDismissRequest = tools::closeShare, title = { Text("分享聊天内容") }, text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                if (tools.shareUrl.isEmpty()) {
                    Text("拿到链接的人都可以查看所选内容，请确认分享范围。")
                    listOf("assistant" to "仅这条回答", "turn" to "本轮问答", "conversation" to "整个会话").forEach { (value, label) ->
                        Row(Modifier.fillMaxWidth().clickable(enabled = !tools.sharing) { scope = value }, verticalAlignment = Alignment.CenterVertically) {
                            RadioButton(scope == value, { scope = value }, enabled = !tools.sharing); Text(label)
                        }
                    }
                    Text("有效期")
                    val expiries = listOf(3600 to "1小时", 21600 to "6小时", 86400 to "1天", 604800 to "7天")
                    Box {
                        TextButton(onClick = { expiryMenu = true }, enabled = !tools.sharing) { Text(expiries.first { it.first == expiry }.second) }
                        DropdownMenu(expiryMenu, { expiryMenu = false }) { expiries.forEach { (value, label) ->
                            DropdownMenuItem(text = { Text(label) }, onClick = { expiry = value; expiryMenu = false })
                        } }
                    }
                    if (tools.sharing) LinearProgressIndicator(Modifier.fillMaxWidth())
                } else {
                    Text("链接已创建，到期后自动失效。")
                    Text(tools.shareUrl, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(vertical = 12.dp))
                    TextButton(onClick = { copyChatText(context, tools.shareUrl) }) { Text("复制链接") }
                    TextButton(onClick = { shareChatText(context, tools.shareUrl) }) { Text("分享链接") }
                    TextButton(onClick = { revoke = true }, enabled = !tools.sharing) { Text("撤销链接") }
                }
            }
        }, confirmButton = { if (tools.shareUrl.isEmpty()) TextButton(onClick = { tools.createShare(scope, expiry) }, enabled = !tools.sharing) { Text("创建链接") }
            else TextButton(onClick = tools::closeShare) { Text("完成") } },
            dismissButton = { if (tools.shareUrl.isEmpty()) TextButton(onClick = tools::closeShare, enabled = !tools.sharing) { Text("取消") } })
        if (revoke) AlertDialog(onDismissRequest = { revoke = false }, title = { Text("撤销这条分享链接？") }, text = { Text("撤销后，其他人将无法再通过这条链接查看内容。") },
            confirmButton = { TextButton(onClick = { revoke = false; tools.revokeShare() }) { Text("撤销链接") } },
            dismissButton = { TextButton(onClick = { revoke = false }) { Text("保留") } })
    }
    tools.preview?.let { item -> AttachmentPreview(item, tools.previewFile, tools.previewBusy, tools::closePreview, { tools.refreshDocument(item) }) }
}

@Composable
private fun AttachmentPreview(item: ChatAttachment, file: File?, loading: Boolean, close: () -> Unit, refresh: () -> Unit) {
    val context = LocalContext.current
    if (!item.image) {
        AlertDialog(onDismissRequest = close, title = { Text(item.name) }, text = {
            Column { Text(attachmentStatus(item)); Text("${(item.size / 1024).coerceAtLeast(1)} KB", style = MaterialTheme.typography.bodySmall)
                if (file != null && file.exists()) TextButton(onClick = {
                    try {
                        val uri = FileProvider.getUriForFile(context, "${context.packageName}.attachments", file)
                        context.startActivity(Intent.createChooser(Intent(Intent.ACTION_VIEW).setDataAndType(uri, item.mime.ifBlank { "application/octet-stream" })
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION), "打开文件"))
                    } catch (_: Exception) { android.widget.Toast.makeText(context, "手机上没有能打开此格式的应用", android.widget.Toast.LENGTH_SHORT).show() }
                }) { Text("用其他应用打开") }
                else Text("材料已保存在服务端，解析完成后可在当前聊天中提问。", style = MaterialTheme.typography.bodySmall)
                if (item.id.isNotEmpty() && item.status != "completed") TextButton(onClick = refresh) { Text("刷新解析状态") }
            }
        }, confirmButton = { TextButton(onClick = close) { Text("关闭") } })
        return
    }
    val bitmap by produceState<Bitmap?>(null, file) {
        value = if (file == null) null else withContext(Dispatchers.IO) {
            runCatching {
                val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }; BitmapFactory.decodeFile(file.path, bounds)
                var sample = 1; while (bounds.outWidth / sample > 2048 || bounds.outHeight / sample > 2048) sample *= 2
                BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample })
            }.getOrNull()
        }
    }
    var scale by remember(file) { mutableFloatStateOf(1f) }
    var offset by remember(file) { mutableStateOf(Offset.Zero) }
    Dialog(onDismissRequest = close, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize().padding(16.dp), shape = MaterialTheme.shapes.large) {
            Column(Modifier.padding(16.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) { Text(item.name, Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis); TextButton(onClick = close) { Text("关闭") } }
                Box(Modifier.weight(1f).fillMaxWidth().clipToBounds().pointerInput(file) {
                    detectTransformGestures { _, pan, zoom, _ -> scale = (scale * zoom).coerceIn(1f, 5f); offset = if (scale == 1f) Offset.Zero else offset + pan }
                }, contentAlignment = Alignment.Center) {
                    val image = bitmap
                    if (image != null) Image(image.asImageBitmap(), item.name, Modifier.fillMaxSize().graphicsLayer { scaleX = scale; scaleY = scale; translationX = offset.x; translationY = offset.y }, contentScale = ContentScale.Fit)
                    else if (loading) CircularProgressIndicator() else Text("图片暂时无法显示，请关闭后重试")
                }
                Text("双指缩放，拖动查看", style = MaterialTheme.typography.bodySmall)
            }
        }
    }
}

@Composable
internal fun FavoritesScreen(model: PlatformViewModel, onOpen: () -> Unit) {
    val tools = model.tools
    var query by rememberSaveable { mutableStateOf("") }
    var expanded by remember { mutableStateOf<String?>(null) }
    var remove by remember { mutableStateOf<org.json.JSONObject?>(null) }
    LaunchedEffect(Unit) { tools.loadFavorites() }
    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(query, { query = it }, label = { Text("搜索收藏") }, modifier = Modifier.fillMaxWidth().padding(16.dp), singleLine = true)
        if (tools.favoritesLoading) LinearProgressIndicator(Modifier.fillMaxWidth())
        TextButton(onClick = tools::loadFavorites, modifier = Modifier.align(Alignment.End)) { Text("刷新收藏") }
        val rows = tools.favorites.filter { query.isBlank() || it.optString("content").contains(query, true) || it.optString("conversation_title").contains(query, true) }
        LazyColumn(Modifier.fillMaxSize().testTag("favorites-list"), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (rows.isEmpty() && !tools.favoritesLoading) item { Text(if (query.isBlank()) "暂无收藏，可在聊天回答下添加收藏" else "没有找到相关收藏") }
            items(rows, key = { it.optString("id") }) { row ->
                OutlinedCard {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(row.optString("conversation_title"), style = MaterialTheme.typography.labelLarge)
                        if (expanded == row.optString("id")) MarkdownText(row.optString("content"))
                        else Text(row.optString("content"), maxLines = 5, overflow = TextOverflow.Ellipsis)
                        TextButton(onClick = { expanded = if (expanded == row.optString("id")) null else row.optString("id") }) { Text(if (expanded == row.optString("id")) "收起" else "展开全文") }
                        Row {
                            TextButton(onClick = {
                                if (model.openFavorite(row.optString("conversation_id"), row.opt("message_id").toString())) onOpen()
                                else tools.report("原会话已删除或不在最近列表中，仍可在这里查看收藏全文")
                            }) { Text("查看原消息") }
                            TextButton(onClick = { remove = row }) { Text("取消收藏") }
                        }
                    }
                }
            }
        }
    }
    remove?.let { row -> AlertDialog(onDismissRequest = { remove = null }, title = { Text("取消这条收藏？") },
        confirmButton = { TextButton(onClick = { tools.removeFavorite(row); remove = null }) { Text("取消收藏") } },
        dismissButton = { TextButton(onClick = { remove = null }) { Text("保留") } }) }
}

internal fun copyChatText(context: Context, text: String) {
    (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("槑槑消息", text))
}

internal fun shareChatText(context: Context, text: String) {
    try { context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text), "分享")) }
    catch (_: Exception) { android.widget.Toast.makeText(context, "无法打开系统分享菜单", android.widget.Toast.LENGTH_SHORT).show() }
}
