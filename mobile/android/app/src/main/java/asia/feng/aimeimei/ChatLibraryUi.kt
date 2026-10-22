package asia.feng.aimeimei

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
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import org.json.JSONObject
import java.text.NumberFormat
import java.util.Locale

data class ChatUsage(val input: Long, val output: Long, val total: Long, val cached: Long, val cacheCreated: Long, val cost: Double) {
    companion object {
        fun fromJson(row: JSONObject): ChatUsage {
            val input = row.optLong("prompt_tokens").coerceAtLeast(0); val output = row.optLong("completion_tokens").coerceAtLeast(0)
            return ChatUsage(input, output, row.optLong("total_tokens").takeIf { it > 0 } ?: (input + output),
                row.optLong("cached_tokens").coerceAtLeast(0), row.optLong("cache_creation_tokens").coerceAtLeast(0), row.optDouble("estimated_cost", 0.0).takeIf { it.isFinite() && it > 0 } ?: 0.0)
        }
    }
}

internal fun tokenNumber(value: Long): String = NumberFormat.getIntegerInstance(Locale.CHINA).format(value)
internal fun modelCapabilities(model: ChatModel): String = buildList {
    add(if (model.vision) "支持图片" else "纯文本模型")
    if (model.reasoningControl) add("思考强度可调")
    if (model.nativeSearch) add("原生联网")
}.joinToString(" · ")

@Composable
internal fun ConversationStatsDialog(model: PlatformViewModel) {
    val tools = model.tools
    AlertDialog(onDismissRequest = tools::closeStats, title = { Text("会话统计") }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (tools.statsLoading) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (tools.statsError.isNotBlank()) {
                Text(tools.statsError, color = MaterialTheme.colorScheme.error)
                TextButton(onClick = tools::showStats, enabled = !tools.statsLoading) { Text("重试") }
            }
            tools.conversationStats?.let { stats ->
                Text(tokenNumber(stats.optLong("total_tokens")) + " Token", style = MaterialTheme.typography.headlineMedium)
                listOf("turn_count" to "问答轮数", "message_count" to "消息数", "web_search_count" to "有联网来源的回答", "attachment_count" to "历史图片数", "media_task_count" to "关联音视频任务数").forEach { (key, label) ->
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Text(label); Text(tokenNumber(stats.optLong(key))) }
                }
                Text("当前模型：${stats.optString("model_name")}", style = MaterialTheme.typography.bodySmall)
                Text("统计来自服务端已保存的记录。Token 是累计用量，包含多轮上下文；缺少模型用量时可能不完整。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }, confirmButton = { TextButton(onClick = tools::closeStats) { Text("关闭") } },
        dismissButton = { TextButton(onClick = tools::showStats, enabled = !tools.statsLoading) { Text("刷新") } })
}

@Composable
internal fun PromptsScreen(model: PlatformViewModel, onUse: () -> Unit) {
    val tools = model.tools
    var query by rememberSaveable { mutableStateOf("") }
    var selected by remember { mutableStateOf<JSONObject?>(null) }
    var editing by remember { mutableStateOf(false) }
    var editingId by remember { mutableStateOf<String?>(null) }
    var title by rememberSaveable { mutableStateOf("") }
    var content by rememberSaveable { mutableStateOf("") }
    var deleting by remember { mutableStateOf<JSONObject?>(null) }
    var applying by remember { mutableStateOf<JSONObject?>(null) }
    val enabled = !model.streaming && model.pending == null && !model.busy && !tools.promptSaving
    fun edit(row: JSONObject?) {
        editingId = row?.optString("id"); title = row?.optString("title").orEmpty(); content = row?.optString("content").orEmpty(); editing = true
    }
    fun apply(row: JSONObject) {
        if (model.draft.isBlank()) { model.editDraft(row.optString("content")); selected = null; onUse() }
        else applying = row
    }
    LaunchedEffect(model.account?.id) { tools.loadPrompts() }
    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(query, { query = it }, label = { Text("搜索提示词") }, singleLine = true, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp))
        Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("与网页同步的共享提示词", Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            TextButton(onClick = { edit(null) }, enabled = enabled) { Text("新增") }
            TextButton(onClick = tools::loadPrompts, enabled = !tools.promptsLoading && !tools.promptSaving) { Text("刷新") }
        }
        if (tools.promptsLoading) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (tools.promptError.isNotBlank()) Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(tools.promptError, Modifier.weight(1f), color = MaterialTheme.colorScheme.error)
            TextButton(onClick = tools::loadPrompts, enabled = !tools.promptsLoading) { Text("重试") }
        }
        val matches = tools.prompts.filter { "${it.optString("title")} ${it.optString("content")}".contains(query, ignoreCase = true) }
        LazyColumn(Modifier.weight(1f).testTag("prompts-list"), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            if (matches.isEmpty() && !tools.promptsLoading && tools.promptError.isBlank()) item { Text(if (query.isBlank()) "还没有提示词，添加一个常用模板吧。" else "没有匹配的提示词") }
            items(matches, key = { it.optString("id") }) { row ->
                OutlinedCard(Modifier.fillMaxWidth().clickable { selected = row }) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(row.optString("title"), style = MaterialTheme.typography.titleMedium)
                        Text(row.optString("content"), maxLines = 3, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium)
                        TextButton(onClick = { apply(row) }, enabled = enabled) { Text("带入当前聊天") }
                    }
                }
            }
        }
    }
    selected?.let { row ->
        AlertDialog(onDismissRequest = { selected = null }, title = { Text(row.optString("title")) }, text = {
            Column(Modifier.verticalScroll(rememberScrollState())) {
                Text(row.optString("content"))
                Row {
                    TextButton(onClick = { selected = null; edit(row) }, enabled = enabled) { Text("编辑") }
                    TextButton(onClick = { deleting = row }, enabled = enabled) { Text("删除") }
                }
            }
        }, confirmButton = { TextButton(onClick = { apply(row) }, enabled = enabled) { Text("带入当前聊天") } },
            dismissButton = { TextButton(onClick = { selected = null }) { Text("关闭") } })
    }
    if (editing) AlertDialog(onDismissRequest = { if (!tools.promptSaving) editing = false }, title = { Text(if (editingId == null) "新增提示词" else "编辑提示词") }, text = {
        Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("提示词由所有账号共享，保存后网页也会同步。", style = MaterialTheme.typography.bodySmall)
            OutlinedTextField(title, { title = it.take(80) }, label = { Text("名称") }, singleLine = true, enabled = !tools.promptSaving)
            OutlinedTextField(content, { content = it.take(4000) }, label = { Text("提示词内容") }, modifier = Modifier.heightIn(max = 280.dp), minLines = 4, maxLines = 10, enabled = !tools.promptSaving)
            Text("${content.length} / 4000", style = MaterialTheme.typography.labelSmall)
            if (tools.promptError.isNotBlank()) Text(tools.promptError, color = MaterialTheme.colorScheme.error)
            if (tools.promptSaving) LinearProgressIndicator(Modifier.fillMaxWidth())
        }
    }, confirmButton = { TextButton(onClick = { tools.savePrompt(editingId, title, content) { editing = false; selected = null } }, enabled = !tools.promptSaving && title.isNotBlank() && content.isNotBlank()) { Text("保存") } },
        dismissButton = { TextButton(onClick = { editing = false }, enabled = !tools.promptSaving) { Text("取消") } })
    deleting?.let { row -> AlertDialog(onDismissRequest = { if (!tools.promptSaving) deleting = null }, title = { Text("删除这条共享提示词？") }, text = {
        Column { Text("删除「${row.optString("title")}」后，其他账号也无法再使用。已有聊天不受影响。"); if (tools.promptError.isNotBlank()) Text(tools.promptError, color = MaterialTheme.colorScheme.error) }
    }, confirmButton = { TextButton(onClick = { tools.deletePrompt(row.getString("id")) { deleting = null; selected = null } }, enabled = !tools.promptSaving) { Text("删除") } },
        dismissButton = { TextButton(onClick = { deleting = null }, enabled = !tools.promptSaving) { Text("取消") } }) }
    applying?.let { row -> AlertDialog(onDismissRequest = { applying = null }, title = { Text("输入框里已有草稿") }, text = { Text("可以把提示词追加到草稿后，或替换当前草稿。带入后由你确认发送。") },
        confirmButton = { TextButton(onClick = { model.editDraft(model.draft + "\n\n" + row.optString("content")); applying = null; selected = null; onUse() }, enabled = enabled) { Text("追加到草稿") } },
        dismissButton = { Row {
            TextButton(onClick = { model.editDraft(row.optString("content")); applying = null; selected = null; onUse() }, enabled = enabled) { Text("替换草稿") }
            TextButton(onClick = { applying = null }) { Text("取消") }
        } }) }
}
