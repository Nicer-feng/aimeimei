package asia.feng.aimeimei

import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Bundle
import android.text.method.LinkMovementMethod
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.viewmodel.compose.viewModel
import com.caverock.androidsvg.SVG
import io.noties.markwon.Markwon
import io.noties.markwon.ext.tables.TablePlugin

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            val colors = if (isSystemInDarkTheme()) darkColorScheme(primary = Color(0xFFE6A7BE)) else lightColorScheme(
                primary = Color(0xFF9C4F6F), secondary = Color(0xFF6E7370), background = Color(0xFFFFFAF6), surface = Color(0xFFFFFAF6))
            MaterialTheme(colorScheme = colors) { PlatformApp() }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun PlatformApp(model: PlatformViewModel = viewModel()) {
    BackHandler(enabled = model.selected != null) { model.back() }
    Scaffold(topBar = {
        TopAppBar(title = { Text(model.selected?.title ?: "AI槑槑", maxLines = 1) },
            navigationIcon = {
                if (model.selected != null) IconButton(onClick = model::back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回对话列表") }
            }, actions = {
                if (model.account != null) {
                    IconButton(onClick = model::refresh, enabled = !model.busy) { Icon(Icons.Filled.Refresh, "刷新") }
                    TextButton(onClick = model::logout, enabled = !model.busy) { Text("退出") }
                }
            })
    }) { padding ->
        Column(Modifier.padding(padding).fillMaxSize().imePadding()) {
            if (model.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
            model.error?.let { message ->
                Text(message, color = MaterialTheme.colorScheme.error, modifier = Modifier.padding(horizontal = 20.dp, vertical = 12.dp))
            }
            when {
                model.account == null -> LoginForm(model)
                model.selected != null -> HistoryMessages(model.messages, model.busy)
                else -> ConversationList(model)
            }
        }
    }
}

@Composable
private fun LoginForm(model: PlatformViewModel) {
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var answer by remember(model.captcha?.id) { mutableStateOf("") }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Image(painterResource(R.drawable.meimei_avatar), contentDescription = "槑槑", modifier = Modifier.size(48.dp))
                Column { Text("欢迎回来", style = MaterialTheme.typography.titleLarge);Text("登录你的槑槑账号", color = MaterialTheme.colorScheme.onSurfaceVariant) }
            }
        }
        item { OutlinedTextField(username, { username = it }, label = { Text("账号") }, singleLine = true, enabled = !model.busy, modifier = Modifier.fillMaxWidth()) }
        item { OutlinedTextField(password, { password = it }, label = { Text("密码") }, singleLine = true,
            visualTransformation = PasswordVisualTransformation(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password), enabled = !model.busy, modifier = Modifier.fillMaxWidth()) }
        item {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedTextField(answer, { answer = it.take(4).uppercase() }, label = { Text("验证码") }, singleLine = true,
                    enabled = !model.busy, modifier = Modifier.weight(1f))
                CaptchaImage(model.captcha, !model.busy, model::refreshCaptcha)
            }
        }
        item { Button(onClick = { model.login(username, password, answer) }, enabled = !model.busy && model.captcha != null && username.isNotBlank() && password.isNotEmpty() && answer.length == 4,
            modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) { Text("登录") } }
    }
}

@Composable
private fun CaptchaImage(captcha: Captcha?, enabled: Boolean, refresh: () -> Unit) {
    val bitmap = remember(captcha?.id) {
        runCatching {
            if (captcha == null) null else Bitmap.createBitmap(256, 96, Bitmap.Config.ARGB_8888).also {
                SVG.getFromString(captcha.svg).apply { documentWidth = 256f;documentHeight = 96f }.renderToCanvas(Canvas(it))
            }.asImageBitmap()
        }.getOrNull()
    }
    Surface(shape = RoundedCornerShape(8.dp), modifier = Modifier.width(128.dp).height(56.dp).clickable(enabled = enabled, onClickLabel = "刷新验证码", onClick = refresh)) {
        if (bitmap != null) Image(bitmap, contentDescription = "验证码，点击刷新", modifier = Modifier.fillMaxSize())
        else Box(contentAlignment = Alignment.Center) { Text("刷新验证码", style = MaterialTheme.typography.labelMedium) }
    }
}

@Composable
private fun ConversationList(model: PlatformViewModel) {
    val user = model.account ?: return
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(vertical = 12.dp)) {
        item { Text("${user.displayName.ifBlank { user.username }} · ${model.models.size} 个可用模型", color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(horizontal = 20.dp, vertical = 12.dp)) }
        if (model.conversations.isEmpty() && !model.busy) item { Text("还没有对话记录", modifier = Modifier.padding(20.dp)) }
        items(model.conversations, key = { it.id }) { conversation ->
            ListItem(headlineContent = { Text(conversation.title, maxLines = 2) },
                supportingContent = { Text(conversation.modelName) }, modifier = Modifier.clickable { model.open(conversation) })
            HorizontalDivider(Modifier.padding(horizontal = 20.dp), color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = .5f))
        }
    }
}

@Composable
private fun HistoryMessages(messages: List<ChatMessage>, busy: Boolean) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(24.dp)) {
        if (messages.isEmpty() && !busy) item { Text("这个对话还没有消息", color = MaterialTheme.colorScheme.onSurfaceVariant) }
        items(messages, key = { it.id }) { message ->
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(if (message.role == "user") "你" else "槑槑", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                val background = if (message.role == "user") MaterialTheme.colorScheme.primaryContainer.copy(alpha = .4f) else Color.Transparent
                Box(Modifier.fillMaxWidth().background(background, RoundedCornerShape(8.dp)).padding(if (message.role == "user") 12.dp else 0.dp)) {
                    MarkdownText(message.content.ifBlank { if (message.status in listOf("failed", "interrupted")) "本次回答已中断" else "暂无正文" })
                }
                if (message.attachments.isNotEmpty()) Text("附件：${message.attachments.joinToString("、")}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun MarkdownText(content: String) {
    val color = MaterialTheme.colorScheme.onSurface
    AndroidView(factory = { context ->
        TextView(context).apply { textSize = 16f;setTextIsSelectable(true);movementMethod = LinkMovementMethod.getInstance();setLineSpacing(4f, 1.1f) }
    }, modifier = Modifier.fillMaxWidth(), update = { view ->
        view.setTextColor(android.graphics.Color.argb((color.alpha * 255).toInt(), (color.red * 255).toInt(), (color.green * 255).toInt(), (color.blue * 255).toInt()))
        if (view.tag != content) {
            val renderer = view.getTag(R.id.markdown_renderer) as? Markwon ?: Markwon.builder(view.context).usePlugin(TablePlugin.create(view.context)).build().also { view.setTag(R.id.markdown_renderer, it) }
            renderer.setMarkdown(view, content);view.tag = content
        }
    })
}
