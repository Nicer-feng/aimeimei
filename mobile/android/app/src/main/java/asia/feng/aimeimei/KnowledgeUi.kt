package asia.feng.aimeimei

import android.content.Intent
import android.net.Uri
import android.widget.Toast
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.KeyboardArrowDown
import androidx.compose.material.icons.filled.KeyboardArrowUp
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties

@Composable
internal fun ChatSearchScreen(model: PlatformViewModel, onOpen: () -> Unit, onFavorites: () -> Unit) {
    val state = model.tools.knowledge
    var text by rememberSaveable { mutableStateOf(state.query) }
    var role by rememberSaveable { mutableStateOf("") }
    var detached by remember { mutableStateOf<ChatSearchResult?>(null) }
    val keyboard = LocalSoftwareKeyboardController.current
    LaunchedEffect(text, model.account?.id) { state.search(text) }
    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(text, { text = it.take(80) }, label = { Text("搜索聊天内容") }, placeholder = { Text("标题、问题、回答和收藏") },
            singleLine = true, trailingIcon = { if (text.isNotEmpty()) TextButton(onClick = { text = "" }) { Text("清空") } },
            modifier = Modifier.fillMaxWidth().padding(16.dp).testTag("chat-search-query"))
        Row(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf("" to "全部", "user" to "我的提问", "assistant" to "AI 回答").forEach { (value, label) ->
                FilterChip(role == value, { role = value }, label = { Text(label) }, modifier = Modifier.testTag("search-role-$value"))
            }
        }
        if (state.searching) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (state.searchError.isNotBlank()) Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(state.searchError, Modifier.weight(1f), color = MaterialTheme.colorScheme.error)
            TextButton(onClick = { state.search(text) }) { Text("重试") }
        }
        val rows = state.results.filter { role.isBlank() || it.role == role }
        if (!state.searching && state.searchError.isBlank()) Text(
            if (text.isBlank()) "最近聊天" else "找到 ${rows.size} 条匹配 · 服务端最多返回 60 条综合结果",
            Modifier.padding(horizontal = 20.dp, vertical = 8.dp), style = MaterialTheme.typography.bodySmall)
        LazyColumn(Modifier.weight(1f).testTag("chat-search-results"), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (rows.isEmpty() && !state.searching && state.searchError.isBlank()) item { Text(if (text.isBlank()) "还没有聊天记录" else "没有匹配的聊天内容，试试其他关键词") }
            items(rows, key = { it.id }) { row ->
                OutlinedCard(Modifier.fillMaxWidth().clickable(enabled = !model.busy && !model.streaming) {
                    keyboard?.hide()
                    if (row.conversationId.isBlank()) detached = row
                    else model.openSearchResult(row, onOpen)
                }.testTag("search-result-${row.id}")) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        SearchHighlight(row.title, text, true)
                        Text(when (row.kind) { "favorite" -> "收藏"; "conversation" -> "聊天标题"; else -> if (row.role == "user") "我的提问" else "AI 回答" },
                            style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary)
                        SearchHighlight(row.snippet, text)
                        if (row.conversationId.isBlank()) Text("原会话已删除，收藏内容仍可查看", style = MaterialTheme.typography.bodySmall)
                    }
                }
            }
        }
    }
    detached?.let { row -> AlertDialog(onDismissRequest = { detached = null }, title = { Text(row.title) },
        text = { Text("原会话已删除。可以在「我的收藏」中查看保存的全文。") },
        confirmButton = { TextButton(onClick = { detached = null; onFavorites() }) { Text("打开收藏") } },
        dismissButton = { TextButton(onClick = { detached = null }) { Text("关闭") } }) }
}

@Composable
private fun SearchHighlight(value: String, query: String, title: Boolean = false) {
    val highlight = MaterialTheme.colorScheme.primary
    val content = remember(value, query, highlight) { buildAnnotatedString {
        append(value)
        if (query.isNotBlank()) {
            var offset = 0
            while (offset < value.length) {
                val index = value.indexOf(query, offset, ignoreCase = true)
                if (index < 0) break
                addStyle(SpanStyle(color = highlight, fontWeight = FontWeight.Bold), index, index + query.length)
                offset = index + query.length
            }
        }
    } }
    Text(content, style = if (title) MaterialTheme.typography.titleSmall else MaterialTheme.typography.bodyMedium,
        maxLines = if (title) 2 else 4, overflow = TextOverflow.Ellipsis)
}

@Composable
internal fun MessageSources(message: ChatMessage) {
    if (message.role != "assistant" || message.sources.isEmpty()) return
    var open by remember(message.id) { mutableStateOf(false) }
    val context = LocalContext.current
    TextButton(onClick = { open = true }, modifier = Modifier.testTag("sources-${message.id}")) { Text("联网来源 · ${message.sources.size}") }
    if (open) Dialog(onDismissRequest = { open = false }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.systemBarsPadding()) {
                Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("联网来源", Modifier.weight(1f), style = MaterialTheme.typography.titleLarge)
                    TextButton(onClick = { open = false }) { Text("关闭") }
                }
                Text("以下来源随这条回答保存，可打开原网页核对。", Modifier.padding(horizontal = 20.dp), style = MaterialTheme.typography.bodySmall)
                LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    items(message.sources.withIndex().toList(), key = { it.index }) { (index, source) ->
                        OutlinedCard(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                                Text("${index + 1}. ${source.title.ifBlank { source.safeUrl?.host ?: "资料来源" }}", style = MaterialTheme.typography.titleMedium)
                                SelectionContainer { Text(source.url, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                                if (source.snippet.isNotBlank()) SelectionContainer { Text(source.snippet) }
                                Row {
                                    TextButton(onClick = { copyChatText(context, source.url) }) { Text("复制链接") }
                                    TextButton(enabled = source.safeUrl != null, onClick = {
                                        source.safeUrl?.let { url ->
                                            try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url.toString()))) }
                                            catch (_: Exception) { Toast.makeText(context, "没有可用的浏览器", Toast.LENGTH_SHORT).show() }
                                        }
                                    }) { Text("打开原网页") }
                                }
                                if (source.safeUrl == null) Text("此来源链接无法打开", style = MaterialTheme.typography.bodySmall)
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
internal fun ProfilesScreen(model: PlatformViewModel) {
    val state = model.tools.knowledge
    var query by rememberSaveable { mutableStateOf("") }
    var editing by remember { mutableStateOf(false) }
    var selected by remember { mutableStateOf<AiProfile?>(null) }
    var deleting by remember { mutableStateOf<AiProfile?>(null) }
    var title by rememberSaveable { mutableStateOf("") }
    var content by rememberSaveable { mutableStateOf("") }
    var kind by rememberSaveable { mutableStateOf("profile") }
    var enabled by rememberSaveable { mutableStateOf(true) }
    val editable = !state.saving && !state.profilesLoading && !model.streaming && !model.busy
    fun edit(row: AiProfile?) { selected = row; title = row?.title.orEmpty(); content = row?.content.orEmpty(); kind = row?.kind ?: "profile"; enabled = row?.enabled ?: true; editing = true }
    LaunchedEffect(model.account?.id) { state.loadProfiles() }
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("AI 档案", Modifier.weight(1f), style = MaterialTheme.typography.titleLarge)
            TextButton(onClick = { edit(null) }, enabled = editable) { Text("新增档案") }
            TextButton(onClick = state::loadProfiles, enabled = editable) { Text("刷新") }
        }
        Text("仅当前账号可见，与网页同步。启用的档案会作为后续聊天背景。", Modifier.padding(horizontal = 20.dp), style = MaterialTheme.typography.bodySmall)
        Text("已启用 ${state.profiles.count { it.enabled }} / ${state.profiles.size} 项 · 约 ${tokenNumber(state.profiles.filter { it.enabled }.sumOf { it.tokens })} Token",
            Modifier.padding(horizontal = 20.dp, vertical = 8.dp), style = MaterialTheme.typography.labelMedium)
        OutlinedTextField(query, { query = it }, label = { Text("搜索档案") }, singleLine = true, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp))
        if (state.profilesLoading || state.saving) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (state.profileError.isNotBlank() && !editing) Text(state.profileError, Modifier.padding(16.dp), color = MaterialTheme.colorScheme.error)
        val rows = state.profiles.filter { "${it.title} ${it.content}".contains(query, ignoreCase = true) }
        LazyColumn(Modifier.weight(1f).testTag("profiles-list"), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (rows.isEmpty() && !state.profilesLoading) item { Text(if (query.isBlank()) "还没有档案，添加常用背景，让槑槑更了解你。" else "没有匹配的档案") }
            items(rows, key = { it.id }) { row ->
                OutlinedCard(Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(row.title, Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                            Switch(row.enabled, { state.toggle(row) }, enabled = editable, modifier = Modifier.testTag("profile-enabled-${row.id}"))
                        }
                        Text("${profileKinds[row.kind] ?: "个人背景"} · 约 ${tokenNumber(row.tokens)} Token", style = MaterialTheme.typography.labelSmall)
                        Text(row.content, maxLines = 4, overflow = TextOverflow.Ellipsis)
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            TextButton(onClick = { edit(row) }, enabled = editable) { Text("查看与编辑") }
                            TextButton(onClick = { deleting = row }, enabled = editable) { Text("删除") }
                            Spacer(Modifier.weight(1f))
                            IconButton(onClick = { state.move(row, -1) }, enabled = editable && state.profiles.firstOrNull()?.id != row.id) { Icon(Icons.Default.KeyboardArrowUp, "上移：${row.title}") }
                            IconButton(onClick = { state.move(row, 1) }, enabled = editable && state.profiles.lastOrNull()?.id != row.id) { Icon(Icons.Default.KeyboardArrowDown, "下移：${row.title}") }
                        }
                    }
                }
            }
        }
    }
    if (editing) Dialog(onDismissRequest = { if (!state.saving) editing = false }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.systemBarsPadding().imePadding()) {
                Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = { editing = false }, enabled = !state.saving) { Text("取消") }
                    Text(if (selected == null) "新增 AI 档案" else "编辑 AI 档案", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                    TextButton(onClick = { state.save(selected?.id, title, content, kind, enabled) { editing = false } },
                        enabled = editable && title.isNotBlank() && content.isNotBlank()) { Text("保存") }
                }
                if (state.saving) LinearProgressIndicator(Modifier.fillMaxWidth())
                Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    OutlinedTextField(title, { title = it.take(80) }, label = { Text("名称") }, singleLine = true, enabled = !state.saving, modifier = Modifier.fillMaxWidth().testTag("profile-title"))
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) { profileKinds.entries.take(2).forEach { (value, label) -> FilterChip(kind == value, { kind = value }, label = { Text(label) }, enabled = !state.saving) } }
                    Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) { profileKinds.entries.drop(2).forEach { (value, label) -> FilterChip(kind == value, { kind = value }, label = { Text(label) }, enabled = !state.saving) } }
                    OutlinedTextField(content, { content = it.take(12000) }, label = { Text("背景与偏好") }, minLines = 8, maxLines = 16,
                        enabled = !state.saving, modifier = Modifier.fillMaxWidth().testTag("profile-content"))
                    Text("${content.length} / 12000", style = MaterialTheme.typography.labelSmall)
                    Row(verticalAlignment = Alignment.CenterVertically) { Text("在后续聊天中启用", Modifier.weight(1f)); Switch(enabled, { enabled = it }, enabled = !state.saving) }
                    Text("档案由你手动管理，修改不会改变已经生成的回答。", style = MaterialTheme.typography.bodySmall)
                    if (state.profileError.isNotBlank()) Text(state.profileError, color = MaterialTheme.colorScheme.error)
                }
            }
        }
    }
    deleting?.let { row -> AlertDialog(onDismissRequest = { if (!state.saving) deleting = null }, title = { Text("删除这条 AI 档案？") },
        text = { Column { Text("「${row.title}」删除后将不再用于后续聊天。"); if (state.profileError.isNotBlank()) Text(state.profileError, color = MaterialTheme.colorScheme.error) } },
        confirmButton = { TextButton(onClick = { state.delete(row.id) { deleting = null } }, enabled = !state.saving) { Text("删除档案") } },
        dismissButton = { TextButton(onClick = { deleting = null }, enabled = !state.saving) { Text("取消") } }) }
}
