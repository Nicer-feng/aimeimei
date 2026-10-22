package asia.feng.aimeimei

import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.foundation.layout.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp

@Composable
internal fun UpdateAction(model: PlatformViewModel) {
    val context = LocalContext.current
    val updater = (context.applicationContext as MeimeiApplication).updates
    var open by remember { mutableStateOf(false) }
    TextButton(onClick = { open = true; updater.check() }) { Text(when (updater.state.phase) {
        "ready" -> "安装 v${updater.state.manifest?.versionName}"
        "downloading" -> "下载中 ${updater.state.percent}%"
        else -> "检查更新"
    }) }
    if (open) UpdateDialog(updater.state, updater.installedVersionName, model.streaming,
        close = { open = false }, download = updater::download, install = { updater.install(context) },
        check = { updater.check(force = true) }, cancel = { updater.cancel(); open = false })
}

@Composable
internal fun UpdateDialog(state: UpdateState, currentVersion: String, streaming: Boolean, close: () -> Unit,
                          download: () -> Unit, install: () -> Unit, check: () -> Unit, cancel: () -> Unit) {
    AlertDialog(onDismissRequest = close, title = { Text(state.manifest?.let { "更新至 v${it.versionName}" } ?: "检查应用更新") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("当前安装：v$currentVersion", style = MaterialTheme.typography.bodySmall)
            state.manifest?.let { Text("目标版本：v${it.versionName}", style = MaterialTheme.typography.bodySmall) }
            Text(state.message, Modifier.testTag("update-status"))
            if (state.phase in setOf("checking", "verifying")) LinearProgressIndicator(Modifier.fillMaxWidth())
            if (state.phase == "downloading") {
                LinearProgressIndicator(progress = { state.percent / 100f }, modifier = Modifier.fillMaxWidth()); Text("${state.percent}%")
            }
            if (state.phase == "ready" && streaming) Text("请等待本次回答完成，或先停止生成，再安装更新。")
        }
    }, confirmButton = {
        when (state.phase) {
            "available" -> TextButton(onClick = download) { Text("下载更新") }
            "ready" -> TextButton(onClick = install, enabled = !streaming, modifier = Modifier.testTag("install-update")) { Text("安装更新") }
            "error" -> TextButton(onClick = check) { Text("重新检查") }
            "downloading" -> TextButton(onClick = close) { Text("后台下载") }
            "verifying", "checking" -> Unit
            else -> TextButton(onClick = close) { Text("知道了") }
        }
    }, dismissButton = {
        TextButton(onClick = if (state.phase == "downloading") cancel else close) { Text(if (state.phase == "downloading") "取消下载" else "稍后") }
    })
}
