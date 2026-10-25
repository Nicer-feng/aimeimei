package asia.feng.aimeimei

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun SideDiscussionDialog(state: SideDiscussionState, mainDraft: String, canUseDraft: Boolean = true,
    onUseDraft: (text: String, append: Boolean) -> Boolean, onSavedConversation: (id: String) -> Unit) {
    if (!state.open) return
    var stopping by remember { mutableStateOf(false) }
    var leaving by remember { mutableStateOf(false) }
    var retrying by remember { mutableStateOf(false) }
    var savingAgain by remember { mutableStateOf(false) }
    var importing by remember { mutableStateOf<String?>(null) }
    var sourceExpanded by remember(state.active?.id) { mutableStateOf(false) }
    val clipboard = LocalClipboardManager.current
    fun leave() { if (state.sending) { leaving = true; stopping = true } else state.close() }
    fun importText(text: String) {
        if (!canUseDraft) return
        if (mainDraft.isBlank()) { if (onUseDraft(text, false)) state.close() } else importing = text
    }
    Dialog(onDismissRequest = ::leave, properties = DialogProperties(usePlatformDefaultWidth = false,
        dismissOnBackPress = false, dismissOnClickOutside = false)) {
        BackHandler(onBack = ::leave)
        Surface(Modifier.fillMaxSize().testTag("side-discussion-dialog"), color = MaterialTheme.colorScheme.background) {
            Column(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).imePadding()) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                    TextButton(onClick = ::leave, enabled = !state.saving) { Text("返回聊天") }
                    Text("分支追问", Modifier.padding(top = 14.dp), style = MaterialTheme.typography.titleMedium)
                    TextButton(onClick = { state.openHistory() }, enabled = !state.sending && !state.loading && !state.saving) { Text("历史") }
                }
                HorizontalDivider()
                if (state.loading || state.saving) LinearProgressIndicator(Modifier.fillMaxWidth())
                if (state.error.isNotBlank()) Surface(color = MaterialTheme.colorScheme.errorContainer) {
                    Text(state.error, Modifier.fillMaxWidth().padding(12.dp).testTag("side-discussion-error"), style = MaterialTheme.typography.bodySmall)
                }
                val current = state.active
                if (current == null) {
                    LazyColumn(Modifier.weight(1f).fillMaxWidth().testTag("side-discussion-history"), contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                        item { Text("围绕一段回答继续讨论", style = MaterialTheme.typography.titleLarge)
                            Text("分支只使用选中的内容和本分支的问题，不会改动主聊天。", Modifier.padding(top = 8.dp), style = MaterialTheme.typography.bodySmall) }
                        if (!state.loading && state.discussions.isEmpty()) item { Text("还没有分支。返回聊天，长按选中文字或打开回答菜单，选择“分支追问”。") }
                        items(state.discussions, key = { it.id }) { row ->
                            OutlinedCard(onClick = { state.select(row) }, modifier = Modifier.fillMaxWidth().testTag("side-discussion-${row.id}")) {
                                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                    Text(row.title, maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.titleMedium)
                                    Text(row.selectedText, maxLines = 3, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall)
                                    Text("${row.modelName} · ${row.messageCount} 条消息", style = MaterialTheme.typography.labelSmall)
                                }
                            }
                        }
                    }
                } else {
                    val list = rememberLazyListState()
                    val following by remember { derivedStateOf {
                        val last = list.layoutInfo.visibleItemsInfo.lastOrNull()
                        last == null || last.index >= list.layoutInfo.totalItemsCount - 2
                    } }
                    LaunchedEffect(current.id, state.live?.content?.length, state.messages.size) {
                        if (following && list.layoutInfo.totalItemsCount > 0) list.animateScrollToItem(list.layoutInfo.totalItemsCount - 1)
                    }
                    LazyColumn(Modifier.weight(1f).fillMaxWidth().testTag("side-discussion-messages"), state = list,
                        contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                        item {
                            OutlinedCard(Modifier.fillMaxWidth()) { Column(Modifier.padding(12.dp)) {
                                Text("引用内容", style = MaterialTheme.typography.labelLarge)
                                Text(current.selectedText, Modifier.padding(top = 6.dp), maxLines = if (sourceExpanded) Int.MAX_VALUE else 4,
                                    overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall)
                                TextButton(onClick = { sourceExpanded = !sourceExpanded }) { Text(if (sourceExpanded) "收起" else "展开引用") }
                            } }
                            Text("${current.modelName} · 仅围绕这段内容讨论", Modifier.padding(top = 8.dp), style = MaterialTheme.typography.labelSmall)
                            FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                                TextButton(onClick = { state.refresh() }, enabled = !state.sending && !state.loading && !state.saving, modifier = Modifier.testTag("side-discussion-refresh")) { Text("刷新记录") }
                                TextButton(onClick = {
                                    if (state.saveUncertain) savingAgain = true else state.saveConversation(done = onSavedConversation)
                                }, enabled = !state.sending && !state.loading && !state.saving && state.messages.any { it.role == "assistant" && it.content.isNotBlank() }, modifier = Modifier.testTag("side-discussion-save")) {
                                    Text(if (state.savedConversationId.isBlank()) "存为独立聊天" else "打开已保存聊天")
                                }
                            }
                        }
                        if (state.messages.isEmpty() && !state.sending && !state.loading) item { Text("想了解哪一点？在下面输入问题即可开始。", style = MaterialTheme.typography.bodyMedium) }
                        items(state.messages, key = { it.id }) { message ->
                            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text(if (message.role == "user") "你" else "槑槑", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                                if (message.reasoning.isNotBlank()) {
                                    var expanded by remember(message.id) { mutableStateOf(false) }
                                    TextButton(onClick = { expanded = !expanded }) { Text(if (expanded) "收起思考过程" else "查看思考过程") }
                                    if (expanded) Box(Modifier.fillMaxWidth().heightIn(max = 180.dp).verticalScroll(rememberScrollState())) { MarkdownText(message.reasoning) }
                                }
                                MarkdownText(message.content.ifBlank { if (message.status != "completed") "本次回答未完成" else "暂无正文" })
                                if (message.status in setOf("failed", "interrupted")) Text("回答未完成，已保留收到的内容", style = MaterialTheme.typography.labelSmall)
                                if (message.role == "assistant" && message.content.isNotBlank()) FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                                    TextButton(onClick = { clipboard.setText(AnnotatedString(message.content)) }) { Text("复制") }
                                    TextButton(onClick = { importText(sideDiscussionQuote(current, message.content)) }, enabled = canUseDraft && !state.sending && !state.saving,
                                        modifier = Modifier.testTag("side-discussion-import-${message.id}")) { Text("带回主聊天") }
                                }
                                HorizontalDivider()
                            }
                        }
                        if (state.pendingQuestion.isNotBlank() && state.messages.none { it.role == "user" && it.content.trim() == state.pendingQuestion.trim() }) item {
                            Text("你", style = MaterialTheme.typography.labelMedium); Text(state.pendingQuestion)
                        }
                        state.live?.let { reply -> item {
                            if (reply.reasoning.isNotBlank()) Text("${if (state.sending) "正在思考" else "已收到思考内容"} · ${reply.reasoning.length} 字", style = MaterialTheme.typography.labelSmall)
                            if (reply.content.isNotBlank()) {
                                if (state.sending) SelectionContainer { Text(reply.content, style = MaterialTheme.typography.bodyLarge) }
                                else MarkdownText(reply.content)
                            }
                            if (state.sending) Text(reply.activity, style = MaterialTheme.typography.labelSmall)
                            if (!state.sending && reply.content.isNotBlank()) TextButton(onClick = { importText(sideDiscussionQuote(current, reply.content)) }, enabled = canUseDraft) { Text("带回已收到内容") }
                        } }
                    }
                    HorizontalDivider()
                    Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(value = state.draft, onValueChange = state::editDraft, modifier = Modifier.fillMaxWidth().testTag("side-discussion-input"),
                            placeholder = { Text("围绕引用内容继续问…") }, maxLines = 4, enabled = !state.sending && !state.loading && !state.saving)
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                            if (state.sending) OutlinedButton(onClick = { leaving = false; stopping = true }, modifier = Modifier.testTag("side-discussion-stop")) { Text("停止生成") }
                            else Button(onClick = { if (state.needsReview) retrying = true else state.send() }, enabled = state.available && !state.loading && !state.saving && state.draft.isNotBlank(),
                                modifier = Modifier.testTag("side-discussion-send")) { Text("发送") }
                        }
                    }
                }
            }
        }
    }
    if (stopping) AlertDialog(onDismissRequest = { stopping = false }, title = { Text("停止分支生成？") },
        text = { Text("已收到的内容会保留。服务器可能仍在保存，之后可以刷新记录核对。") },
        confirmButton = { TextButton(onClick = { stopping = false; state.stop(); if (leaving) state.close() }) { Text(if (leaving) "停止并返回" else "停止生成") } },
        dismissButton = { TextButton(onClick = { stopping = false }) { Text("继续等待") } })
    if (retrying) AlertDialog(onDismissRequest = { retrying = false }, title = { Text("确认再次调用模型？") },
        text = { Text("上次生成已停止或结果尚未确认。建议先刷新记录；本次发送会再次调用模型并可能计入用量。") },
        confirmButton = { TextButton(onClick = { retrying = false; state.send(confirmed = true) }) { Text("确认发送") } },
        dismissButton = { TextButton(onClick = { retrying = false; state.refresh() }) { Text("先刷新记录") } })
    if (savingAgain) AlertDialog(onDismissRequest = { savingAgain = false }, title = { Text("再次保存独立聊天？") },
        text = { Text("上次保存结果尚未确认，请先查看主聊天历史。再次保存可能创建重复会话。") },
        confirmButton = { TextButton(onClick = { savingAgain = false; state.saveConversation(confirmed = true, done = onSavedConversation) }) { Text("再次保存") } },
        dismissButton = { TextButton(onClick = { savingAgain = false }) { Text("取消") } })
    importing?.let { text -> AlertDialog(onDismissRequest = { importing = null }, title = { Text("主聊天已有草稿") },
        text = { Text("选择如何带回讨论结果，带入后仍需手动发送。") },
        confirmButton = { TextButton(onClick = { if (onUseDraft(text, true)) { importing = null; state.close() } }, enabled = canUseDraft) { Text("追加到草稿") } },
        dismissButton = { Row { TextButton(onClick = { importing = null }) { Text("取消") }; TextButton(onClick = { if (onUseDraft(text, false)) { importing = null; state.close() } }, enabled = canUseDraft) { Text("替换草稿") } } }) }
}

internal fun sideDiscussionQuote(discussion: SideDiscussion, content: String): String =
    "【分支追问结果】\n引用内容：\n" + discussion.selectedText.take(12000).lines().joinToString("\n") { "> $it" } +
        "\n\n讨论结果：\n${content.trim()}"
