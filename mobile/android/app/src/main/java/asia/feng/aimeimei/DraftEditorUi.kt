package asia.feng.aimeimei

import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties

@Composable
internal fun DraftEditor(model: PlatformViewModel, close: () -> Unit) {
    var clearing by remember { mutableStateOf(false) }
    val context = LocalContext.current
    Dialog(onDismissRequest = close, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.systemBarsPadding().imePadding()) {
                Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("编辑草稿", Modifier.weight(1f), style = MaterialTheme.typography.titleLarge)
                    TextButton(onClick = close) { Text("完成") }
                }
                Text("草稿自动保存，完成后返回聊天确认发送。", Modifier.padding(horizontal = 20.dp), style = MaterialTheme.typography.bodySmall)
                OutlinedTextField(model.draft, model::editDraft, placeholder = { Text("在这里慢慢写，长问题和材料也能展开编辑…") },
                    enabled = !model.busy, modifier = Modifier.weight(1f).fillMaxWidth().padding(16.dp).testTag("full-draft-editor"))
                Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("${model.draft.codePointCount(0, model.draft.length)} 字", Modifier.weight(1f), style = MaterialTheme.typography.labelMedium)
                    TextButton(onClick = { copyChatText(context, model.draft) }, enabled = model.draft.isNotEmpty()) { Text("复制全文") }
                    TextButton(onClick = { clearing = true }, enabled = model.draft.isNotEmpty() && !model.busy) { Text("清空") }
                }
            }
        }
    }
    if (clearing) AlertDialog(onDismissRequest = { clearing = false }, title = { Text("清空当前草稿？") }, text = { Text("聊天记录和已添加的附件会保留。") },
        confirmButton = { TextButton(onClick = { model.editDraft(""); clearing = false }) { Text("确认清空") } },
        dismissButton = { TextButton(onClick = { clearing = false }) { Text("取消") } })
}
