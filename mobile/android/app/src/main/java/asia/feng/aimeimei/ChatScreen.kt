package asia.feng.aimeimei

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.foundation.interaction.DragInteraction
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.first

@Composable
internal fun ChatScreen(model: PlatformViewModel, openTool: (String) -> Unit) {
    if (model.selected == null) {
        Column(Modifier.fillMaxSize()) {
            Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(28.dp), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                Image(painterResource(R.drawable.meimei_welcome), "槑槑欢迎插画", Modifier.widthIn(max = 300.dp).fillMaxWidth().height(220.dp), contentScale = ContentScale.Fit)
                Spacer(Modifier.height(20.dp))
                Text("今天，想聊点什么？", style = MaterialTheme.typography.headlineSmall)
                Text("有问题，慢慢说，槑槑在这里", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(top = 10.dp, bottom = 24.dp))
                listOf("帮我润色" to "帮我润色下面这段文字，让它更自然、更清楚：", "一起想点子" to "我想和你一起想几个点子：", "解释一个问题" to "请用通俗的语言帮我解释：").forEach { (label, prompt) ->
                    OutlinedButton(onClick = { model.editDraft(prompt) }, enabled = !model.busy, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) { Text(label) }
                }
                if (model.models.isEmpty() && !model.busy) Text("暂无可用模型，请联系管理员配置。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(top = 12.dp))
            }
            Composer(model, onSend = model::send, openTool = openTool)
        }
    } else key(model.selected?.id) { ConversationContent(model, openTool) }
}

@Composable
private fun ConversationContent(model: PlatformViewModel, openTool: (String) -> Unit) {
    val list = rememberLazyListState()
    var following by remember { mutableStateOf(true) }
    var confirmPending by remember { mutableStateOf(false) }
    var highlighted by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    val waiting = model.pending
    val showPendingUser = waiting != null && model.messages.none { it.role == "user" && (it.id.toLongOrNull() ?: 0) > waiting.baseline && it.content.trim() == waiting.content.trim() }
    LaunchedEffect(list) {
        list.interactionSource.interactions.collect { interaction ->
            when (interaction) {
                is DragInteraction.Start -> following = false
                is DragInteraction.Stop, is DragInteraction.Cancel -> {
                    delay(350); following = !list.canScrollForward
                }
            }
        }
    }
    val expectedItems = model.messages.size + (if (showPendingUser) 1 else 0) + 1
    LaunchedEffect(expectedItems, model.streaming) {
        snapshotFlow { list.layoutInfo.totalItemsCount }.first { it >= expectedItems }
        if (following && model.focusMessageId.isEmpty()) list.scrollToItem(list.layoutInfo.totalItemsCount - 1, Int.MAX_VALUE)
    }
    LaunchedEffect(model.focusMessageId, model.messages.size) {
        val id = model.focusMessageId
        if (id.isNotBlank()) {
            val index = model.messages.indexOfFirst { it.id == id }
            if (index >= 0) {
                snapshotFlow { list.layoutInfo.totalItemsCount }.first { it > index }
                following = false; highlighted = id; list.scrollToItem(index); model.clearFocusMessage()
            }
        }
    }
    if (confirmPending) AlertDialog(onDismissRequest = { confirmPending = false }, title = { Text("已核对服务器记录？") },
        text = { Text("服务器可能仍在整理或保存回答。建议先刷新等待；解除后不会自动重发问题，请避免重复提交。") },
        confirmButton = { TextButton(onClick = { confirmPending = false; model.acknowledgePending() }) { Text("已核对，解除等待") } },
        dismissButton = { TextButton(onClick = { confirmPending = false; model.refresh() }) { Text("再刷新一次") } })
    Column(Modifier.fillMaxSize()) {
        Box(Modifier.weight(1f)) {
            LazyColumn(state = list, modifier = Modifier.fillMaxSize().testTag("chat-messages"), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(24.dp)) {
                if (model.messages.isEmpty() && !model.streaming && !model.busy) item { Text("有什么想和槑槑聊的？", color = MaterialTheme.colorScheme.onSurfaceVariant) }
                items(model.messages, key = { it.id }) { message ->
                    Box(Modifier.fillMaxWidth().background(if (highlighted == message.id) MaterialTheme.colorScheme.secondaryContainer.copy(alpha = .35f) else androidx.compose.ui.graphics.Color.Transparent,
                        RoundedCornerShape(12.dp)).testTag("message-${message.id}")) { MessageBody(message, model) }
                }
                model.pending?.let { waiting ->
                    if (model.messages.none { it.role == "user" && (it.id.toLongOrNull() ?: 0) > waiting.baseline && it.content.trim() == waiting.content.trim() }) {
                        item(key = "pending-user") { MessageBody(ChatMessage("pending-user", "user", waiting.content, "", "", waiting.attachments.map { it.name }, waiting.attachments), model) }
                    }
                }
                item(key = "live-reply") { LiveMessage(model, follow = { following }, scroll = {
                    val last = list.layoutInfo.totalItemsCount - 1
                    if (last >= 0) list.scrollToItem(last, Int.MAX_VALUE)
                }) }
            }
            if (!following) FilledTonalButton(onClick = {
                following = true
                scope.launch { if (list.layoutInfo.totalItemsCount > 0) list.animateScrollToItem(list.layoutInfo.totalItemsCount - 1, Int.MAX_VALUE) }
            }, modifier = Modifier.align(Alignment.BottomEnd).padding(12.dp)) { Text("回到底部") }
        }
        if (model.pending != null && !model.streaming) Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), horizontalArrangement = Arrangement.End) {
            TextButton(onClick = model::refresh, enabled = !model.busy) { Text("刷新核对") }
            TextButton(onClick = { confirmPending = true }, enabled = !model.busy) { Text("核对后继续") }
        }
        Composer(model, onSend = { following = true; model.send() }, openTool = openTool)
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MessageBody(message: ChatMessage, model: PlatformViewModel? = null) {
    val context = LocalContext.current
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(if (message.role == "user") "你" else "槑槑", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.combinedClickable(onClick = {}, onLongClick = { model?.tools?.menuMessage = message }))
        if (message.reasoning.isNotBlank()) ThinkingText(message.reasoning)
        val user = message.role == "user"
        Box(Modifier.fillMaxWidth().background(if (user) MaterialTheme.colorScheme.primaryContainer.copy(alpha = .4f) else androidx.compose.ui.graphics.Color.Transparent, RoundedCornerShape(18.dp)).padding(if (user) 14.dp else 0.dp)) {
            val display = quotedDisplay(message.content)
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                display.first.forEach { quote -> Surface(color = MaterialTheme.colorScheme.secondaryContainer, shape = MaterialTheme.shapes.small) {
                    Text(quote, Modifier.padding(10.dp), maxLines = 4, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall)
                } }
                MarkdownText(display.second.ifBlank { if (message.status in listOf("failed", "interrupted")) "本次回答已中断" else "暂无正文" },
                    onQuote = model?.takeIf { !it.streaming && it.pending == null }?.let { viewModel -> { text -> viewModel.tools.quote(message, text) } })
            }
        }
        if (model != null) message.media.forEach { item -> AttachmentCard(item, onOpen = { model.tools.showPreview(item) }, tools = model.tools) }
        else if (message.attachments.isNotEmpty()) Text("附件：${message.attachments.joinToString("、")}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        MessageSources(message)
        if (message.role == "assistant") message.usage?.let { usage ->
            var details by remember(message.id) { mutableStateOf(false) }
            TextButton(onClick = { details = true }, modifier = Modifier.testTag("usage-${message.id}")) { Text(if (usage.total > 0) "${tokenNumber(usage.total)} Token" else "Token 未返回", style = MaterialTheme.typography.labelSmall) }
            if (details) AlertDialog(onDismissRequest = { details = false }, title = { Text("本条回答用量") }, text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("输入：${tokenNumber(usage.input)} Token"); Text("输出：${tokenNumber(usage.output)} Token"); Text("合计：${tokenNumber(usage.total)} Token")
                    if (usage.cached > 0) Text("缓存命中：${tokenNumber(usage.cached)} Token")
                    if (usage.cacheCreated > 0) Text("缓存写入：${tokenNumber(usage.cacheCreated)} Token")
                    if (usage.cost > 0) Text("估算费用：¥${"%.6f".format(java.util.Locale.ROOT, usage.cost)}")
                    Text("以服务端保存的用量为准，未返回用量不表示没有消耗。", style = MaterialTheme.typography.bodySmall)
                }
            }, confirmButton = { TextButton(onClick = { details = false }) { Text("关闭") } })
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { copy(context, message.content) }) { Text("复制") }
            if (model != null) {
                TextButton(onClick = { model.tools.quote(message) }, enabled = !model.streaming && model.pending == null) { Text("引用") }
                if (message.role == "assistant" && (message.id.toLongOrNull() ?: 0) > 0) TextButton(onClick = { model.tools.showVoices(message) }) { Text("朗读") }
                IconButton(onClick = { model.tools.menuMessage = message }) { Icon(Icons.Default.MoreVert, "更多消息操作") }
            }
            if (message.favoriteId.isNotEmpty()) Text("已收藏", style = MaterialTheme.typography.labelSmall)
            if (message.status in listOf("failed", "interrupted")) Text("未完整生成", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
        }
    }
}

@Composable
private fun ThinkingText(content: String) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        TextButton(onClick = { expanded = !expanded }) { Text(if (expanded) "收起思考过程" else "查看思考过程") }
        if (LocalAppMotion.current) {
            AnimatedVisibility(expanded) { Box(Modifier.fillMaxWidth().heightIn(max = 220.dp).verticalScroll(rememberScrollState())) { MarkdownText(content) } }
        } else if (expanded) Box(Modifier.fillMaxWidth().heightIn(max = 220.dp).verticalScroll(rememberScrollState())) { MarkdownText(content) }
    }
}

@Composable
private fun LiveMessage(model: PlatformViewModel, follow: () -> Boolean, scroll: suspend () -> Unit) {
    val reply = model.live ?: return
    val context = LocalContext.current
    LaunchedEffect(model) {
        var previous = -1
        while (isActive) {
            delay(160)
            val length = model.live?.content?.length ?: 0
            if (length != previous && follow()) { scroll(); previous = length }
        }
    }
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (model.streaming) CircularProgressIndicator(Modifier.size(14.dp), strokeWidth = 2.dp)
            Text(if (model.streaming) reply.activity else "已暂停，等待核对保存结果", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (reply.reasoning.isNotBlank()) {
            Text(reply.reasoning.takeLast(90).replace('\n', ' '), maxLines = 1, overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            ThinkingText(reply.reasoning)
        }
        if (reply.content.isNotEmpty()) SelectionContainer { Text(reply.content, style = MaterialTheme.typography.bodyLarge) }
        if (!model.streaming && reply.content.isNotEmpty()) TextButton(onClick = { copy(context, reply.content) }) { Text("复制已收到的内容") }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Composer(model: PlatformViewModel, onSend: () -> Unit, openTool: (String) -> Unit) {
    val chosen = model.currentModel
    var showModels by remember { mutableStateOf(false) }
    var showModes by remember { mutableStateOf(false) }
    var filter by remember { mutableStateOf("") }
    var visionOnly by remember { mutableStateOf(false) }
    val imageAttached = model.tools.attachments.any { it.image }
    val editable = !model.busy && !model.streaming && model.pending == null
    if (showModels) ModalBottomSheet(onDismissRequest = { showModels = false }) {
        Column(Modifier.padding(horizontal = 20.dp).fillMaxWidth()) {
            OutlinedTextField(filter, { filter = it }, label = { Text("搜索模型") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            Row(verticalAlignment = Alignment.CenterVertically) { FilterChip(selected = visionOnly, onClick = { visionOnly = !visionOnly }, label = { Text("仅看支持图片") }) }
            val matches = model.models.filter { (!visionOnly || it.vision) && "${it.name} ${it.actualModel} ${it.provider}".contains(filter, ignoreCase = true) }
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = 440.dp)) {
                if (matches.isEmpty()) item { Text("没有符合条件的模型", Modifier.padding(vertical = 20.dp)) }
                items(matches, key = { it.id }) { option ->
                    ListItem(headlineContent = { Text(option.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        supportingContent = { Column {
                            Text("${option.actualModel} · ${option.provider}", maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(modelCapabilities(option), style = MaterialTheme.typography.labelSmall, color = if (option.vision) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
                        } },
                        trailingContent = { if (option.id == model.currentModelId) Icon(Icons.Filled.Check, "已选中") },
                        modifier = Modifier.fillMaxWidth().clickable(enabled = editable) { showModels = false; model.configure(option.id, model.currentReasoningMode) })
                }
            }
        }
    }
    Surface(shadowElevation = 4.dp, tonalElevation = 1.dp) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            ComposerAttachments(model)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(model.draft, model::editDraft, enabled = !model.busy, placeholder = { Text("和槑槑聊点什么…") }, modifier = Modifier.weight(1f).heightIn(max = 168.dp), maxLines = 6, shape = RoundedCornerShape(20.dp))
                if (model.streaming) FilledTonalButton(onClick = model::stop) { Text("停止") }
                else Button(onClick = onSend, enabled = editable && chosen != null && (!imageAttached || chosen.vision) && (model.draft.isNotBlank() || model.tools.hasContent) && model.tools.ready) { Text("发送") }
            }
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                AttachmentPicker(model, editable && !model.tools.uploading)
                TextButton(onClick = { filter = ""; showModels = true }, enabled = editable, modifier = Modifier.weight(1f)) {
                    Text((chosen?.name ?: model.selected?.modelName ?: "选择模型") + if (chosen?.vision == true) " · 图片" else "", maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                if (chosen?.reasoningControl == true) Box {
                    TextButton(onClick = { showModes = true }, enabled = editable) { Text(modeLabel(model.currentReasoningMode)) }
                    DropdownMenu(showModes, { showModes = false }) {
                        listOf("fast", "balanced", "deep").forEach { mode -> DropdownMenuItem(text = { Text(modeLabel(mode)) },
                            onClick = { showModes = false; model.configure(model.currentModelId, mode) },
                            trailingIcon = { if (mode == model.currentReasoningMode) Icon(Icons.Filled.Check, "已选中") }) }
                    }
                }
                Checkbox(model.webSearch, model::toggleWebSearch, enabled = editable)
                Text("联网", style = MaterialTheme.typography.labelMedium)
            }
            if (imageAttached && chosen?.vision != true) Text("当前模型不支持图片，请切换到标有「支持图片」的模型。", color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
            Row {
                TextButton(onClick = { openTool("prompts") }, enabled = editable && !model.tools.uploading) { Text("提示词") }
                TextButton(onClick = { openTool("chat") }, enabled = editable && !model.tools.uploading) { Text("更多聊天工具") }
            }
        }
    }
}

private fun modeLabel(value: String) = when (value) { "fast" -> "快速"; "deep" -> "深度"; else -> "平衡" }
private fun copy(context: Context, text: String) {
    (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("槑槑消息", text))
}
