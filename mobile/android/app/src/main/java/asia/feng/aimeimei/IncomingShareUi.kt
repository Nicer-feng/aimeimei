package asia.feng.aimeimei

import android.graphics.Bitmap
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
internal fun IncomingSharePreview(state: IncomingShareController, accountId: String, accountName: String = "",
                                  canImport: Boolean = true, onDefer: () -> Unit = {}, onImport: suspend (IncomingSharePayload) -> Boolean) {
    val row = state.pending
    if (row == null && !state.preparing && state.error.isBlank()) return
    if (state.deferred || (accountId.isBlank() && state.waitingForLogin)) return
    val needsAccount = row?.owner?.isNotBlank() == true && accountId.isBlank()
    var preview by remember(row?.id) { mutableStateOf<IncomingShareImage?>(null) }
    var discarding by remember(row?.id) { mutableStateOf(false) }
    val busy = state.preparing || state.importing
    Dialog(onDismissRequest = { if (!busy) discarding = true }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize().testTag("incoming-share-preview")) {
            Column(Modifier.systemBarsPadding().imePadding()) {
                Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("分享给槑槑", Modifier.weight(1f), style = MaterialTheme.typography.titleLarge)
                    TextButton(onClick = { discarding = true }, enabled = !busy) { Text("取消") }
                }
                LazyColumn(Modifier.weight(1f).fillMaxWidth(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                    item { Text("先检查分享内容，加入草稿后仍需手动发送。", style = MaterialTheme.typography.bodyMedium) }
                    if (state.preparing) item {
                        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                            CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp); Text("正在读取分享内容…")
                        }
                    }
                    if (needsAccount) item { Text("登录后可继续查看待加入草稿的分享内容。", color = MaterialTheme.colorScheme.onSurfaceVariant) }
                    if (row != null && !needsAccount) {
                        item {
                            OutlinedTextField(row.text, state::editText, enabled = !busy, label = { Text("文字或链接") },
                                placeholder = { Text("可以补充想问的问题") }, minLines = 3, maxLines = 8,
                                modifier = Modifier.fillMaxWidth().testTag("incoming-share-text"))
                        }
                        items(row.images, key = { it.file.name }) { image ->
                            IncomingShareImageCard(image, enabled = !busy, open = { preview = image }, remove = { state.removeImage(image) })
                        }
                        item {
                            Text(if (accountId.isBlank()) "请先登录，再确认加入你的聊天草稿。" else "将追加到${accountName.ifBlank { "当前账号" }}的当前聊天草稿，保留原有文字和附件。",
                                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        }
                    }
                    if (state.error.isNotBlank()) item { Text(state.error, color = MaterialTheme.colorScheme.error, modifier = Modifier.testTag("incoming-share-error")) }
                    item { Text("接收和预览仅保存在本机；点击聊天的发送按钮后才上传图片。", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                }
                Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp)) {
                    if (!canImport && accountId.isNotBlank()) Text("请先完成当前操作，分享内容会保留。", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(bottom = 8.dp))
                    Button(onClick = {
                        if (accountId.isBlank()) state.requestLogin() else state.confirm(accountId, onImport)
                    }, enabled = row != null && !busy && (accountId.isBlank() || canImport) && (row.text.isNotBlank() || row.images.isNotEmpty()),
                        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).testTag("incoming-share-confirm")) {
                        if (state.importing) CircularProgressIndicator(Modifier.size(18.dp), strokeWidth = 2.dp)
                        else Text(if (accountId.isBlank()) "先登录" else "追加到聊天草稿")
                    }
                    TextButton(onClick = { state.deferPreview(); onDefer() }, enabled = !busy, modifier = Modifier.fillMaxWidth()) { Text("暂存，返回聊天") }
                }
            }
        }
    }
    if (discarding) AlertDialog(onDismissRequest = { discarding = false }, title = { Text("取消这次分享？") },
        text = { Text("这次分享的本地副本会被清除，原应用的内容和现有聊天草稿都会保留。") },
        confirmButton = { TextButton(onClick = { discarding = false; state.discard() }) { Text("确认取消") } },
        dismissButton = { TextButton(onClick = { discarding = false }) { Text("继续预览") } })
    val opened = preview
    if (opened != null && row?.images?.any { it.file == opened.file } == true) {
        FullscreenChatImage(ChatAttachment("", opened.name, opened.mime, opened.file.length(), true), opened.file, false, "", { preview = null }, {})
    }
}

@Composable
private fun IncomingShareImageCard(image: IncomingShareImage, enabled: Boolean, open: () -> Unit, remove: () -> Unit) {
    val bitmap by produceState<Bitmap?>(null, image.file) {
        value = withContext(Dispatchers.IO) { runCatching { decodeChatImage(image.file, 720) }.getOrNull() }
    }
    OutlinedCard(Modifier.fillMaxWidth()) {
        Box(Modifier.fillMaxWidth().height(176.dp).testTag("incoming-share-image-${image.file.name}").clickable(enabled = enabled, onClickLabel = "全屏查看分享图片", onClick = open), contentAlignment = Alignment.Center) {
            val imageBitmap = bitmap
            if (imageBitmap != null) Image(imageBitmap.asImageBitmap(), image.name, Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
            else Text("图片预览暂不可用")
            Surface(Modifier.align(Alignment.BottomEnd).padding(6.dp), shape = MaterialTheme.shapes.small,
                color = MaterialTheme.colorScheme.surface.copy(alpha = .9f)) { Text("点击查看大图", Modifier.padding(6.dp), style = MaterialTheme.typography.labelSmall) }
        }
        Row(Modifier.padding(horizontal = 12.dp, vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(image.name, maxLines = 2, style = MaterialTheme.typography.bodyMedium)
                Text("${(image.file.length() / 1024).coerceAtLeast(1)} KB · 待发送", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            TextButton(onClick = remove, enabled = enabled) { Text("移除") }
        }
    }
}
