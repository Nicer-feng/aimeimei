package asia.feng.aimeimei

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.Image
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

data class WebTool(val id: String, val title: String, val detail: String)
internal val webTools = listOf(
    WebTool("chat", "完整聊天", "图片、文件、引用、分享与语音朗读"),
    WebTool("writing", "写稿工作台", "材料、要求和稿件整理"),
    WebTool("prompts", "提示词库", "常用模板与个人提示词"),
    WebTool("favorites", "我的收藏", "收藏内容与历史回看"),
    WebTool("profiles", "AI档案", "长期偏好与聊天背景"),
    WebTool("media", "音视频分析", "上传媒体、转写与总结"),
    WebTool("ocr", "手写识别", "图片识别与文字提取"),
    WebTool("activity", "Token活动", "查看个人使用统计"),
    WebTool("reading", "摸鱼阅读", "TXT 小说、书库与阅读进度"),
    WebTool("cloud", "槑槑云", "文件分享与在线文档"),
    WebTool("gifts", "槑槑送礼", "礼物与人情往来记录")
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun PlatformApp(model: PlatformViewModel, preferences: AppPreferences) {
    var screen by rememberSaveable { mutableStateOf("chat") }
    var toolId by rememberSaveable { mutableStateOf("chat") }
    var webConversation by rememberSaveable { mutableStateOf("") }
    var webParent by rememberSaveable { mutableStateOf("tools") }
    val drawer = rememberDrawerState(DrawerValue.Closed)
    val scope = rememberCoroutineScope()
    val focus = LocalFocusManager.current
    val keyboard = LocalSoftwareKeyboardController.current
    val closeDrawer = { focus.clearFocus(); keyboard?.hide(); scope.launch { if (preferences.motion) drawer.close() else drawer.snapTo(DrawerValue.Closed) }; Unit }
    val openTool: (String) -> Unit = { id ->
        if (!model.streaming && !model.busy) {
            webParent = screen
            if (id == "admin") screen = "admin"
            else { webParent = screen; toolId = id; webConversation = model.selected?.id.orEmpty(); screen = "web" }
        }
    }
    val back: () -> Unit = {
        when {
            drawer.isOpen -> closeDrawer()
            screen == "web" -> { screen = webParent; model.returnedFromWeb() }
            screen != "chat" -> screen = "chat"
            model.selected != null && !model.streaming -> model.back()
        }
    }
    LaunchedEffect(model.account?.id) { screen = "chat"; drawer.close() }
    BackHandler(drawer.isOpen || screen != "chat" || model.selected != null && !model.streaming) { back() }
    ModalNavigationDrawer(
        drawerState = drawer, gesturesEnabled = model.account != null && screen == "chat",
        drawerContent = {
            if (model.account != null) HistoryDrawer(model, onNew = { model.newConversation(); screen = "chat"; closeDrawer() },
                onOpen = { model.open(it); screen = "chat"; closeDrawer() },
                onTools = { screen = "tools"; closeDrawer() }, onSettings = { screen = "settings"; closeDrawer() })
        }
    ) {
        Scaffold(topBar = {
            if (screen != "admin") TopAppBar(title = {
                Column {
                    Text(when (screen) { "settings" -> "设置"; "tools" -> "更多工具"; "web" -> if (toolId == "admin") "后台管理" else webTools.firstOrNull { it.id == toolId }?.title ?: "AI槑槑"; else -> model.selected?.title ?: "AI槑槑" },
                        maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.titleMedium)
                    if (screen == "chat" && model.account != null) Text(model.currentModel?.name ?: "新聊天", style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }, navigationIcon = {
                if (screen != "chat") IconButton(onClick = back) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回") }
                else if (model.account != null) IconButton(onClick = { focus.clearFocus(); keyboard?.hide(); scope.launch { if (preferences.motion) drawer.open() else drawer.snapTo(DrawerValue.Open) } }) { Icon(Icons.Default.Menu, "打开历史聊天") }
            }, actions = {
                if (screen == "chat") {
                    if (model.account != null) {
                        IconButton(onClick = { model.newConversation() }, enabled = !model.streaming && !model.busy) { Icon(Icons.Default.Add, "新聊天") }
                        IconButton(onClick = { screen = "tools" }) { Icon(Icons.Default.MoreVert, "更多工具") }
                    } else IconButton(onClick = { screen = "settings" }) { Icon(Icons.Default.Settings, "设置") }
                }
            })
        }) { padding ->
            Column(Modifier.padding(padding).consumeWindowInsets(padding).fillMaxSize().imePadding()) {
                if (model.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
                model.error?.let { message ->
                    Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text(message, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f).padding(vertical = 8.dp))
                        if (model.account != null) TextButton(onClick = model::refresh, enabled = !model.busy && !model.streaming) { Text("重试") }
                    }
                }
                AnimatedContent(targetState = screen, label = "页面切换", modifier = Modifier.weight(1f), transitionSpec = {
                    val duration = if (preferences.motion) 180 else 0
                    (fadeIn(tween(duration)) + slideInHorizontally(tween(duration)) { it / 12 }) togetherWith
                        (fadeOut(tween(duration)) + slideOutHorizontally(tween(duration)) { -it / 12 })
                }) { page ->
                    when (page) {
                        "settings" -> SettingsScreen(model, preferences, openTool)
                        "tools" -> ToolScreen(model, openTool)
                        "admin" -> AdminScreen(model, preferences) { screen = webParent; model.returnedFromWeb() }
                        "web" -> WebToolScreen(model, toolId, webConversation)
                        else -> if (model.account == null) LoginForm(model) else ChatScreen(model, openTool)
                    }
                }
            }
        }
    }
}

@Composable
private fun HistoryDrawer(model: PlatformViewModel, onNew: () -> Unit, onOpen: (Conversation) -> Unit, onTools: () -> Unit, onSettings: () -> Unit) {
    var query by rememberSaveable { mutableStateOf("") }
    var menu by remember { mutableStateOf<String?>(null) }
    var editing by remember { mutableStateOf<Conversation?>(null) }
    var deleting by remember { mutableStateOf<Conversation?>(null) }
    var title by remember { mutableStateOf("") }
    val enabled = !model.streaming && !model.busy
    ModalDrawerSheet(modifier = Modifier.widthIn(max = 340.dp).fillMaxHeight()) {
        Row(Modifier.fillMaxWidth().padding(20.dp), verticalAlignment = Alignment.CenterVertically) {
            Image(painterResource(R.drawable.meimei_avatar), "槑槑", Modifier.size(36.dp))
            Text("AI槑槑", style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(start = 10.dp).weight(1f))
        }
        FilledTonalButton(onClick = onNew, enabled = enabled, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
            Icon(Icons.Default.Add, null); Spacer(Modifier.width(8.dp)); Text("新聊天")
        }
        OutlinedTextField(query, { query = it }, placeholder = { Text("搜索聊天标题") }, singleLine = true,
            leadingIcon = { Icon(Icons.Default.Search, null) }, shape = CircleShape,
            modifier = Modifier.fillMaxWidth().padding(16.dp))
        if (model.streaming) Text("回答生成中，完成后可切换聊天", style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 20.dp))
        val matches = model.conversations.filter { it.title.contains(query, ignoreCase = true) }
        LazyColumn(Modifier.weight(1f), contentPadding = PaddingValues(horizontal = 8.dp, vertical = 8.dp)) {
            if (matches.isEmpty()) item { Text(if (query.isBlank()) "还没有聊天，从一个问题开始吧" else "没有匹配的聊天", color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(16.dp)) }
            items(matches, key = { it.id }) { conversation ->
                NavigationDrawerItem(selected = model.selected?.id == conversation.id, onClick = { if (enabled) onOpen(conversation) },
                    label = { Column { Text(conversation.title, maxLines = 1, overflow = TextOverflow.Ellipsis); if (conversation.pinned) Text("已置顶", style = MaterialTheme.typography.labelSmall) } },
                    badge = {
                        Box {
                            IconButton(onClick = { menu = conversation.id }, enabled = enabled) { Icon(Icons.Default.MoreVert, "管理聊天：${conversation.title}") }
                            DropdownMenu(menu == conversation.id, { menu = null }) {
                                DropdownMenuItem(text = { Text(if (conversation.pinned) "取消置顶" else "置顶") }, onClick = { menu = null; model.pin(conversation) })
                                DropdownMenuItem(text = { Text("重命名") }, onClick = { menu = null; title = conversation.title; editing = conversation })
                                DropdownMenuItem(text = { Text("删除", color = MaterialTheme.colorScheme.error) }, onClick = { menu = null; deleting = conversation })
                            }
                        }
                    })
            }
        }
        TextButton(onClick = onTools, modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)) { Text("更多工具") }
        HorizontalDivider(Modifier.padding(horizontal = 20.dp))
        val user = model.account
        ListItem(headlineContent = { Text(user?.displayName?.ifBlank { user.username }.orEmpty()) }, supportingContent = { Text("设置与账号", style = MaterialTheme.typography.bodySmall) },
            leadingContent = { Surface(shape = CircleShape, color = MaterialTheme.colorScheme.primaryContainer) { Text(user?.displayName?.ifBlank { user.username }?.take(1) ?: "槑", modifier = Modifier.padding(12.dp)) } },
            trailingContent = { Icon(Icons.Default.Settings, null) }, modifier = Modifier.clickable(onClick = onSettings).padding(bottom = 8.dp))
    }
    editing?.let { conversation -> AlertDialog(onDismissRequest = { editing = null }, title = { Text("重命名聊天") },
        text = { OutlinedTextField(title, { title = it.take(80) }, singleLine = true, label = { Text("聊天标题") }) },
        confirmButton = { TextButton(onClick = { model.rename(conversation, title); editing = null }, enabled = title.isNotBlank() && enabled) { Text("保存") } },
        dismissButton = { TextButton(onClick = { editing = null }) { Text("取消") } }) }
    deleting?.let { conversation -> AlertDialog(onDismissRequest = { deleting = null }, title = { Text("删除这段聊天？") }, text = { Text("“${conversation.title}”将从历史列表中移除。") },
        confirmButton = { TextButton(onClick = { model.delete(conversation); deleting = null }, enabled = enabled) { Text("删除", color = MaterialTheme.colorScheme.error) } },
        dismissButton = { TextButton(onClick = { deleting = null }) { Text("取消") } }) }
}

@Composable
private fun ToolScreen(model: PlatformViewModel, openTool: (String) -> Unit) {
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(vertical = 12.dp)) {
        item { Text("熟悉的槑槑工具，随时接着用", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(20.dp)) }
        if (model.streaming) item { Text("请等待回答完成，再打开工具", modifier = Modifier.padding(horizontal = 20.dp), color = MaterialTheme.colorScheme.primary) }
        items(webTools, key = { it.id }) { tool -> SettingsRow(tool.title, tool.detail, enabled = !model.streaming && !model.busy, onClick = { openTool(tool.id) }) }
        if (model.account?.role == "admin") item { SettingsRow("后台管理", "账号、模型、联网、语音、统计和系统设置", enabled = !model.streaming && !model.busy, onClick = { openTool("admin") }) }
    }
}

@Composable
private fun SettingsScreen(model: PlatformViewModel, preferences: AppPreferences, openTool: (String) -> Unit) {
    var choice by remember { mutableStateOf("") }
    var logout by remember { mutableStateOf(false) }
    LazyColumn(Modifier.fillMaxSize().testTag("settings-list"), contentPadding = PaddingValues(bottom = 24.dp)) {
        model.account?.let { user ->
            item { SectionLabel("账号") }
            item { SettingsRow(user.displayName.ifBlank { user.username }, "${user.username} · ${if (user.role == "admin") "管理员" else "家庭成员"}") }
        }
        item { SectionLabel("外观与体验") }
        item { SettingsRow("主题", when (preferences.theme) { "light" -> "浅色"; "dark" -> "深色"; else -> "跟随系统" }, onClick = { choice = "theme" }) }
        item { SettingsRow("字体大小", when (preferences.font) { "small" -> "小"; "large" -> "大"; else -> "标准" }, onClick = { choice = "font" }) }
        item { ListItem(headlineContent = { Text("界面动效") }, supportingContent = { Text("页面切换与内容展开") }, trailingContent = { Switch(preferences.motion, preferences::changeMotion) }) }
        if (model.account != null) {
            item { SectionLabel("聊天与工具") }
            item { SettingsRow("AI档案与偏好", "管理长期偏好和聊天背景", enabled = !model.streaming && !model.busy, onClick = { openTool("profiles") }) }
            item { SettingsRow("语音与完整聊天", "朗读、文件、图片、分享和引用", enabled = !model.streaming && !model.busy, onClick = { openTool("chat") }) }
            if (model.account?.role == "admin") item { SettingsRow("后台管理", "管理账号与系统功能", enabled = !model.streaming && !model.busy, onClick = { openTool("admin") }) }
        }
        item { SectionLabel("关于") }
        item { ListItem(headlineContent = { Text("AI槑槑") }, supportingContent = { Text("版本 ${BuildConfig.VERSION_NAME}${if (BuildConfig.DEBUG) " · 验证版" else " · 正式版"}") }, trailingContent = { UpdateAction(model) }) }
        if (model.account != null) item { TextButton(onClick = { logout = true }, enabled = !model.streaming && !model.busy, modifier = Modifier.fillMaxWidth().padding(20.dp)) { Text("退出登录", color = MaterialTheme.colorScheme.error) } }
    }
    if (choice.isNotEmpty()) {
        val options = if (choice == "theme") listOf("system" to "跟随系统", "light" to "浅色", "dark" to "深色") else listOf("small" to "小", "normal" to "标准", "large" to "大")
        AlertDialog(onDismissRequest = { choice = "" }, title = { Text(if (choice == "theme") "主题" else "字体大小") }, text = {
            Column { options.forEach { (value, label) ->
                Row(Modifier.fillMaxWidth().clickable { if (choice == "theme") preferences.changeTheme(value) else preferences.changeFont(value); choice = "" }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    RadioButton(selected = value == if (choice == "theme") preferences.theme else preferences.font, onClick = null)
                    Text(label, Modifier.padding(start = 12.dp))
                }
            } }
        }, confirmButton = { TextButton(onClick = { choice = "" }) { Text("取消") } })
    }
    if (logout) AlertDialog(onDismissRequest = { logout = false }, title = { Text("退出当前账号？") }, text = { Text("云端聊天会保留，下次登录后可继续查看。") },
        confirmButton = { TextButton(onClick = { logout = false; model.logout() }) { Text("退出登录") } }, dismissButton = { TextButton(onClick = { logout = false }) { Text("取消") } })
}

@Composable
private fun SectionLabel(text: String) { Text(text, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary, modifier = Modifier.padding(start = 20.dp, top = 24.dp, bottom = 8.dp)) }

@Composable
private fun SettingsRow(title: String, detail: String, enabled: Boolean = true, onClick: (() -> Unit)? = null) {
    ListItem(headlineContent = { Text(title, color = if (enabled) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant) }, supportingContent = { Text(detail) },
        trailingContent = { if (onClick != null) Text("›", style = MaterialTheme.typography.titleLarge) }, modifier = if (onClick == null) Modifier else Modifier.clickable(enabled = enabled, onClick = onClick))
}
