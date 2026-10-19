package asia.feng.aimeimei

import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.foundation.layout.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp

@Composable
internal fun UpdateAction(model: PlatformViewModel) {
    val context = LocalContext.current
    val updater = (context.applicationContext as MeimeiApplication).updates
    var open by remember { mutableStateOf(false) }
    TextButton(onClick = { open = true; updater.check() }) { Text("更新") }
    if (!open) return
    val state = updater.state
    AlertDialog(onDismissRequest = { open = false }, title = { Text("应用更新 · v${BuildConfig.VERSION_NAME}") }, text = {
        Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(state.message)
            if (state.phase == "checking") LinearProgressIndicator(Modifier.fillMaxWidth())
            if (state.phase == "downloading") { LinearProgressIndicator(progress = { state.percent / 100f }, modifier = Modifier.fillMaxWidth()); Text("${state.percent}%") }
            if (state.phase == "ready" && model.streaming) Text("请等待本次回答完成，或先停止生成，再安装更新。")
        }
    }, confirmButton = {
        when (state.phase) {
            "available" -> TextButton(onClick = updater::download) { Text("下载更新") }
            "ready" -> TextButton(onClick = { updater.install(context) }, enabled = !model.streaming) { Text("安装更新") }
            "error" -> TextButton(onClick = updater::check) { Text("重新检查") }
            else -> TextButton(onClick = { open = false }) { Text("知道了") }
        }
    }, dismissButton = {
        TextButton(onClick = { if (state.phase == "downloading") updater.cancel(); open = false }) { Text(if (state.phase == "downloading") "取消下载" else "稍后") }
    })
}
