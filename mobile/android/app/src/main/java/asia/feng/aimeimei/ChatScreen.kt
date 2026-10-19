package asia.feng.aimeimei

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import androidx.compose.foundation.interaction.DragInteraction
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

@Composable
internal fun ChatScreen(model: PlatformViewModel) {
    val session = model.selected ?: return
    key(session.id) { ConversationContent(model) }
}

@Composable
private fun ConversationContent(model: PlatformViewModel) {
    val list = rememberLazyListState()
    var following by remember { mutableStateOf(true) }
    var confirmPending by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
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
    LaunchedEffect(model.messages.size, model.streaming) {
        if (following && list.layoutInfo.totalItemsCount > 0) list.scrollToItem(list.layoutInfo.totalItemsCount - 1, Int.MAX_VALUE)
    }
    if (confirmPending) AlertDialog(onDismissRequest = { confirmPending = false }, title = { Text("已核对服务器记录？") },
        text = { Text("服务器可能仍在整理或保存回答。建议先刷新等待；解除后不会自动重发问题，请避免重复提交。") },
        confirmButton = { TextButton(onClick = { confirmPending = false; model.acknowledgePending() }) { Text("已核对，解除等待") } },
        dismissButton = { TextButton(onClick = { confirmPending = false; model.refresh() }) { Text("再刷新一次") } })
    Column(Modifier.fillMaxSize()) {
        Box(Modifier.weight(1f)) {
            LazyColumn(state = list, modifier = Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(24.dp)) {
                if (model.messages.isEmpty() && !model.streaming && !model.busy) item { Text("有什么想和槑槑聊的？", color = MaterialTheme.colorScheme.onSurfaceVariant) }
                items(model.messages, key = { it.id }) { message -> MessageBody(message) }
                model.pending?.let { waiting ->
                    if (model.messages.none { it.role == "user" && (it.id.toLongOrNull() ?: 0) > waiting.baseline && it.content.trim() == waiting.content.trim() }) {
                        item(key = "pending-user") { MessageBody(ChatMessage("pending-user", "user", waiting.content, "", "", emptyList())) }
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
        Composer(model, onSend = { following = true; model.send() })
    }
}

@Composable
private fun MessageBody(message: ChatMessage) {
    val context = LocalContext.current
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(if (message.role == "user") "你" else "槑槑", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (message.reasoning.isNotBlank()) ThinkingText(message.reasoning)
        MarkdownText(message.content.ifBlank { if (message.status in listOf("failed", "interrupted")) "本次回答已中断" else "暂无正文" })
        if (message.attachments.isNotEmpty()) Text("附件：${message.attachments.joinToString("、")}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Row(verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { copy(context, message.content) }) { Text("复制") }
            if (message.status in listOf("failed", "interrupted")) Text("未完整生成", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.error)
        }
    }
}

@Composable
private fun ThinkingText(content: String) {
    var expanded by remember { mutableStateOf(false) }
    Column {
        TextButton(onClick = { expanded = !expanded }) { Text(if (expanded) "收起思考过程" else "查看思考过程") }
        if (expanded) Box(Modifier.fillMaxWidth().heightIn(max = 220.dp).verticalScroll(rememberScrollState())) { MarkdownText(content) }
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
private fun Composer(model: PlatformViewModel, onSend: () -> Unit) {
    val session = model.selected ?: return
    val chosen = model.models.firstOrNull { it.id == session.modelId }
    var showModels by remember { mutableStateOf(false) }
    var showModes by remember { mutableStateOf(false) }
    var filter by remember { mutableStateOf("") }
    val editable = !model.busy && !model.streaming && model.pending == null
    if (showModels) ModalBottomSheet(onDismissRequest = { showModels = false }) {
        Column(Modifier.padding(horizontal = 20.dp).fillMaxWidth()) {
            OutlinedTextField(filter, { filter = it }, label = { Text("搜索模型") }, singleLine = true, modifier = Modifier.fillMaxWidth())
            LazyColumn(Modifier.fillMaxWidth().heightIn(max = 440.dp)) {
                items(model.models.filter { "${it.name} ${it.actualModel} ${it.provider}".contains(filter, ignoreCase = true) }, key = { it.id }) { option ->
                    ListItem(headlineContent = { Text(option.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        supportingContent = { Text("${option.actualModel} · ${option.provider}", maxLines = 1, overflow = TextOverflow.Ellipsis) },
                        trailingContent = { if (option.id == session.modelId) Icon(Icons.Filled.Check, "已选中") },
                        modifier = Modifier.fillMaxWidth().clickable(enabled = editable) { showModels = false; model.configure(option.id, session.reasoningMode) })
                }
            }
        }
    }
    Surface(shadowElevation = 4.dp, tonalElevation = 1.dp) {
        Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(model.draft, model::editDraft, placeholder = { Text("和槑槑聊点什么…") }, modifier = Modifier.weight(1f).heightIn(max = 168.dp), maxLines = 6)
                if (model.streaming) FilledTonalButton(onClick = model::stop) { Text("停止") }
                else Button(onClick = onSend, enabled = editable && model.draft.isNotBlank()) { Text("发送") }
            }
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = { filter = ""; showModels = true }, enabled = editable, modifier = Modifier.weight(1f)) {
                    Text(chosen?.name ?: session.modelName, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                if (chosen?.reasoningControl == true) Box {
                    TextButton(onClick = { showModes = true }, enabled = editable) { Text(modeLabel(session.reasoningMode)) }
                    DropdownMenu(showModes, { showModes = false }) {
                        listOf("fast", "balanced", "deep").forEach { mode -> DropdownMenuItem(text = { Text(modeLabel(mode)) },
                            onClick = { showModes = false; model.configure(session.modelId, mode) },
                            trailingIcon = { if (mode == session.reasoningMode) Icon(Icons.Filled.Check, "已选中") }) }
                    }
                }
                Checkbox(model.webSearch, model::toggleWebSearch, enabled = editable)
                Text("联网", style = MaterialTheme.typography.labelMedium)
            }
        }
    }
}

private fun modeLabel(value: String) = when (value) { "fast" -> "快速"; "deep" -> "深度"; else -> "平衡" }
private fun copy(context: Context, text: String) {
    (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("槑槑消息", text))
}
