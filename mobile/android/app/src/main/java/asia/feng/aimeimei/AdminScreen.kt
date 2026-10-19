package asia.feng.aimeimei

import androidx.activity.compose.BackHandler
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.tween
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import org.json.JSONObject

internal val adminSections = listOf(
    "overview" to "概览", "users" to "账号管理", "models" to "模型管理", "keys" to "密钥管理",
    "search" to "联网搜索", "tts" to "语音服务", "features" to "插件管理", "tokens" to "Token统计",
    "usage" to "使用时长", "costs" to "成本统计", "system" to "系统设置")

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun AdminScreen(model: PlatformViewModel, preferences: AppPreferences, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var section by remember { mutableStateOf("home") }
    var data by remember { mutableStateOf<JSONObject?>(null) }
    var loading by remember { mutableStateOf(false) }
    var saving by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<String?>(null) }
    var failure by remember { mutableStateOf<String?>(null) }
    var editing by remember { mutableStateOf<AdminForm?>(null) }
    var dirty by remember { mutableStateOf(false) }
    var discard by remember { mutableStateOf(false) }
    var confirm by remember { mutableStateOf<Pair<String, () -> Unit>?>(null) }
    var operation by remember { mutableStateOf<Job?>(null) }
    var revision by remember { mutableIntStateOf(0) }
    suspend fun read(path: List<String>, query: Map<String, String> = emptyMap()) = model.adminRequest(path, query = query)
    fun load(target: String = section) {
        operation?.cancel(); val ticket = ++revision
        section = target; data = null; failure = null
        operation = scope.launch {
            loading = true
            try {
                val result = when (target) {
                    "home", "overview", "features" -> read(listOf("overview"))
                    "users", "models", "search", "tts" -> read(listOf(target))
                    "keys" -> read(listOf("models")).put("search", read(listOf("search")).getJSONObject("search"))
                    "system" -> read(listOf("sms-auth")).put("version", read(listOf("version")))
                    else -> JSONObject()
                }
                if (ticket == revision) data = result
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { if (ticket == revision) failure = error.message ?: "加载失败，请重试" }
            finally { if (ticket == revision) loading = false }
        }
    }
    fun backNow() {
        dirty = false
        if (editing != null) editing = null else if (section != "home") { status = null; load("home") } else onClose()
    }
    val back: () -> Unit = {
        if (!saving) { if (dirty) discard = true else backNow() }
    }
    fun mutate(path: List<String>, method: String, body: JSONObject, done: (JSONObject) -> Unit) {
        if (saving) return
        operation?.cancel(); ++revision; loading = false; saving = true; failure = null; status = null
        operation = scope.launch {
            try { val result = model.adminRequest(path, method, body); done(result) }
            catch (cancelled: CancellationException) { throw cancelled }
            catch (error: Exception) { failure = error.message ?: "保存失败，请检查网络后重试" }
            finally { saving = false }
        }
    }
    LaunchedEffect(Unit) { load() }
    BackHandler { back() }
    if (model.account?.role != "admin") {
        Column(Modifier.fillMaxSize().padding(24.dp)) { Text("当前账号没有管理员权限"); TextButton(onClick = onClose) { Text("返回") } }
        return
    }
    Scaffold(topBar = {
        TopAppBar(title = { Text(editing?.title ?: adminSections.firstOrNull { it.first == section }?.second ?: "后台管理") },
            navigationIcon = { IconButton(onClick = back, enabled = !saving) { Icon(Icons.AutoMirrored.Filled.ArrowBack, "返回") } },
            actions = { if (editing == null && section !in setOf("tokens", "usage", "costs")) IconButton(onClick = { load() }, enabled = !saving && !loading) { Icon(Icons.Default.Refresh, "刷新后台") } })
    }) { padding ->
        Column(Modifier.padding(padding).consumeWindowInsets(padding).fillMaxSize()) {
            if (loading || saving) LinearProgressIndicator(Modifier.fillMaxWidth())
            failure?.let { message -> Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(message, Modifier.weight(1f), color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                if (editing == null) TextButton(onClick = { load() }, enabled = !saving && !loading) { Text("重试") }
            } }
            status?.let { Text(it, Modifier.padding(horizontal = 20.dp, vertical = 8.dp), color = MaterialTheme.colorScheme.primary, style = MaterialTheme.typography.bodySmall) }
            AnimatedContent(targetState = editing, label = "管理页面", modifier = Modifier.weight(1f), transitionSpec = {
                val duration = if (preferences.motion) 160 else 0
                fadeIn(tween(duration)) togetherWith fadeOut(tween(duration))
            }) { form ->
                if (form != null) AdminEditor(form, enabled = !saving, onDirty = { dirty = it }, onSave = { body ->
                    val submit = {
                        mutate(form.path, form.method, body) {
                            dirty = false; editing = null
                            status = if (form.kind == "password") "登录密码已修改，请重新登录" else "已保存"
                            if (form.kind == "password") model.returnedFromWeb() else load()
                        }
                    }
                    when {
                        form.kind == "password" -> confirm = "修改家用登录密码后，所有账号的当前登录都会失效。确认修改？" to submit
                        body.optBoolean("clear_api_key") -> confirm = "清除密钥后，对应服务可能暂不可用。确认清除？" to submit
                        form.kind == "users" && form.source.optString("id").isNotEmpty() && (!body.optBoolean("is_active") || body.optString("role") != form.source.optString("role")) -> confirm = "确认修改这个账号的角色或启用状态？禁用后该账号会退出登录。" to submit
                        else -> submit()
                    }
                }) else if (section in setOf("tokens", "usage", "costs")) {
                    AdminStatistics(model, section, enabled = !saving, onRecalculate = { range, refresh ->
                        confirm = "按当前模型价格回算所选范围内尚未计价的历史消息，并重建每日账本。已有非零费用会保留。确认回算？" to {
                            mutate(listOf("cost-recalculate"), "POST", JSONObject().put("range", range)) { result ->
                                status = "回算完成：更新 ${result.optInt("updated_messages")} 条，跳过 ${result.optInt("skipped_messages")} 条"; refresh()
                            }
                        }
                    })
                } else if (data != null) {
                    val snapshot = data!!
                    val open: (String, JSONObject) -> Unit = { kind, source -> failure = null; status = null; dirty = false; editing = adminForm(kind, source) }
                    LazyColumn(Modifier.fillMaxSize().testTag("admin-list"), contentPadding = PaddingValues(start = 16.dp, end = 16.dp, bottom = 32.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        when (section) {
                            "home" -> {
                                item { AdminHeading("管理工作台", "账号、服务与运行情况") }
                                item { AdminOverview(snapshot.optJSONObject("overview") ?: JSONObject(), compact = true) }
                                items(adminSections) { (id, title) -> AdminRow(title, when(id) {
                                    "users" -> "家庭成员、权限与短信登录"; "models" -> "模型能力、价格与提示词"; "keys" -> "模型与搜索服务密钥"
                                    "tokens" -> "用量趋势、账号与模型明细"; "costs" -> "费用估算与历史回算"; "usage" -> "工作与阅读时长"; else -> "查看与管理"
                                }) { status = null; load(id) } }
                            }
                            "overview" -> item { AdminOverview(snapshot.optJSONObject("overview") ?: JSONObject()) }
                            "users", "models" -> {
                                item { FilledTonalButton(onClick = { open(section, JSONObject()) }, modifier = Modifier.fillMaxWidth()) { Icon(Icons.Default.Add, null); Spacer(Modifier.width(8.dp)); Text(if (section == "users") "新增账号" else "新增模型") } }
                                val rows = jsonRows(snapshot.optJSONArray(section))
                                if (rows.isEmpty()) item { AdminHint("暂无记录") }
                                items(rows, key = { it.optString("id") }) { row ->
                                    AdminCard {
                                        AdminRow(if (section == "users") row.optString("display_name").ifBlank { row.optString("username") } else row.optString("name"),
                                            if (section == "users") "${row.optString("username")} · ${if (row.optString("role") == "admin") "管理员" else "家庭成员"} · ${if(row.optBoolean("is_active")) "已启用" else "已禁用"}"
                                            else "${row.optString("provider")} · ${row.optString("model")} · ${if(row.optBoolean("enabled")) "已启用" else "已停用"}") { open(section, row) }
                                        if (section == "models") TextButton(onClick = {
                                            confirm = "删除模型“${row.optString("name")}”？此操作不能撤销。" to {
                                                mutate(listOf("models", row.getString("id")), "DELETE", JSONObject()) { status = "模型已删除"; load() }
                                            }
                                        }, enabled = !saving) { Text("删除模型", color = MaterialTheme.colorScheme.error) }
                                    }
                                }
                            }
                            "keys" -> {
                                item { AdminHint("使用当前管理员账号管理密钥。已保存的密钥仅显示配置状态，留空保持原值。") }
                                items(jsonRows(snapshot.optJSONArray("models")), key = { it.optString("id") }) { row ->
                                    AdminRow(row.optString("name"), if (row.optBoolean("has_api_key")) "模型密钥已配置" else "模型密钥未配置") { open("model-key", row) }
                                }
                                item { AdminRow("搜索 API Key", if (snapshot.optJSONObject("search")?.optBoolean("has_api_key") == true) "已配置" else "未配置") { open("search", snapshot.getJSONObject("search")) } }
                            }
                            "search", "tts" -> item { AdminRow("配置${if (section == "search") "联网搜索" else "语音服务"}", "编辑配置、密钥${if(section == "tts") "与可用音色" else "与搜索策略"}") { open(section, snapshot.getJSONObject(section)) } }
                            "features" -> {
                                val overview = snapshot.optJSONObject("overview") ?: JSONObject()
                                item { AdminRow("交互功能开关", "对所有账号生效") { open("features", overview.optJSONObject("features") ?: JSONObject()) } }
                                item { AdminOverview(overview, servicesOnly = true) }
                                item { AdminHint("提示词库、收藏、AI档案和桌面对话缩略导航已启用。") }
                            }
                            "system" -> {
                                item { AdminHeading("系统信息", "客户端 ${BuildConfig.VERSION_NAME}") }
                                item { AdminValues(snapshot.optJSONObject("version") ?: JSONObject(), listOf("version" to "服务端版本", "build_id" to "服务端构建", "updated_at" to "最近更新")) }
                                item { ListItem(headlineContent = { Text("数据存储") }, supportingContent = { Text("SQLite") }) }
                                item { ListItem(headlineContent = { Text("服务运行方式") }, supportingContent = { Text("Python 标准库") }) }
                                item { AdminRow("短信登录", "签名、模板与验证码策略") { open("sms-auth", snapshot.getJSONObject("sms_auth")) } }
                                item { AdminRow("修改家用登录密码", "修改后所有账号的会话会失效") { open("password", JSONObject()) } }
                            }
                        }
                    }
                }
            }
        }
    }
    if (discard) AlertDialog(onDismissRequest = { discard = false }, title = { Text("放弃未保存的修改？") }, text = { Text("返回后需要重新填写。") },
        confirmButton = { TextButton(onClick = { discard = false; backNow() }) { Text("放弃修改") } }, dismissButton = { TextButton(onClick = { discard = false }) { Text("继续编辑") } })
    confirm?.let { (message, action) -> AlertDialog(onDismissRequest = { confirm = null }, title = { Text("确认操作") }, text = { Text(message) },
        confirmButton = { TextButton(onClick = { confirm = null; action() }) { Text("确认") } }, dismissButton = { TextButton(onClick = { confirm = null }) { Text("取消") } }) }
}

@Composable
private fun AdminEditor(form: AdminForm, enabled: Boolean, onDirty: (Boolean) -> Unit, onSave: (JSONObject) -> Unit) {
    val initial = remember(form) { form.initialValues() }
    val values = remember(form) { mutableStateMapOf<String, String>().apply { putAll(initial) } }
    val initialVoices = remember(form) { jsonRows(form.source.optJSONArray("voices")).map { row -> listOf("id", "name", "resource_id").associateWith { row.optString(it) } } }
    val voices = remember(form) { mutableStateListOf<Map<String, String>>().apply { addAll(initialVoices) } }
    var error by remember(form) { mutableStateOf<String?>(null) }
    fun changed() { error = null; onDirty(values.toMap() != initial || voices.toList() != initialVoices) }
    LazyColumn(Modifier.fillMaxSize().testTag("admin-editor"), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
        if (form.source.optString("id").isNotEmpty()) item { AdminHint(form.source.optString("display_name").ifBlank { form.source.optString("name") }.ifBlank { form.source.optString("username") }) }
        if (form.source.optBoolean("has_api_key")) item { AdminHint("当前密钥已配置") }
        items(form.fields, key = { it.key }) { field ->
            val value = values[field.key].orEmpty()
            if (form.kind == "tts" && field.key == "default_voice") AdminChoice("默认音色", value, voices.filter { !it["id"].isNullOrBlank() }.map { voice -> voice["id"].orEmpty() to voice["name"].orEmpty().ifBlank { voice["id"].orEmpty() } }, enabled) { values[field.key] = it; changed() }
            else when (field.type) {
                AdminFieldType.SWITCH -> ListItem(headlineContent = { Text(field.label) }, trailingContent = { Switch(value == "true", { values[field.key] = it.toString(); changed() }, enabled = enabled, modifier = Modifier.testTag("admin-field-${field.key}")) })
                AdminFieldType.CHOICE -> AdminChoice(field.label, value, field.choices, enabled) { values[field.key] = it; changed() }
                else -> OutlinedTextField(value, { values[field.key] = it
                        if (form.kind == "models" && field.key in setOf("input_price_per_million", "output_price_per_million") && (it.toDoubleOrNull() ?: 0.0) > 0) values["cost_enabled"] = "true"
                        changed() }, label = { Text(field.label) },
                    supportingText = if (field.help.isNotEmpty()) ({ Text(field.help) }) else null,
                    enabled = enabled, singleLine = field.type != AdminFieldType.MULTILINE,
                    minLines = if (field.type == AdminFieldType.MULTILINE) 3 else 1,
                    visualTransformation = if (field.type == AdminFieldType.SECRET) PasswordVisualTransformation() else VisualTransformation.None,
                    keyboardOptions = KeyboardOptions(keyboardType = when(field.type) { AdminFieldType.SECRET -> KeyboardType.Password; AdminFieldType.NUMBER -> KeyboardType.Decimal; else -> KeyboardType.Text }),
                    modifier = Modifier.fillMaxWidth().testTag("admin-field-${field.key}"))
            }
        }
        if (form.kind == "tts") {
            item { AdminHeading("可用音色", "音色 ID、名称与资源 ID") }
            items(voices.size) { index -> AdminCard {
                Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                    for ((key, label) in listOf("id" to "音色 ID", "name" to "音色名称", "resource_id" to "资源 ID"))
                        OutlinedTextField(voices[index][key].orEmpty(), { text -> voices[index] = voices[index] + (key to text); changed() }, label = { Text(label) }, enabled = enabled, singleLine = true, modifier = Modifier.fillMaxWidth().testTag("admin-voice-$index-$key"))
                    TextButton(onClick = { voices.removeAt(index); changed() }, enabled = enabled) { Text("移除音色", color = MaterialTheme.colorScheme.error) }
                }
            } }
            item { OutlinedButton(onClick = { voices.add(mapOf("id" to "", "name" to "", "resource_id" to "")); changed() }, enabled = enabled) { Text("添加音色") } }
        }
        error?.let { message -> item { Text(message, color = MaterialTheme.colorScheme.error) } }
        item { Button(onClick = { error = form.validate(values, voices); if (error == null) onSave(form.payload(values, voices)) }, enabled = enabled, modifier = Modifier.fillMaxWidth()) { Text("保存") } }
    }
}

@Composable
internal fun AdminChoice(title: String, value: String, options: List<Pair<String, String>>, enabled: Boolean = true, onChange: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        ListItem(headlineContent = { Text(title) }, supportingContent = { Text(options.firstOrNull { it.first == value }?.second ?: value) },
            trailingContent = { Text("⌄") }, modifier = Modifier.fillMaxWidth().clickable(enabled = enabled) { expanded = true })
        DropdownMenu(expanded, { expanded = false }) { options.forEach { (id, label) -> DropdownMenuItem(text = { Text(label) }, onClick = { expanded = false; onChange(id) }) } }
    }
}
@Composable internal fun AdminHeading(title: String, detail: String = "") { Column(Modifier.padding(vertical = 12.dp)) { Text(title, style = MaterialTheme.typography.titleLarge); if (detail.isNotEmpty()) AdminHint(detail) } }
@Composable internal fun AdminHint(text: String) { Text(text, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(vertical = 6.dp)) }
@Composable internal fun AdminRow(title: String, detail: String, onClick: () -> Unit) { ListItem(headlineContent = { Text(title) }, supportingContent = { Text(detail) }, trailingContent = { Text("›") }, modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)) }
@Composable internal fun AdminCard(content: @Composable ColumnScope.() -> Unit) { Card(Modifier.fillMaxWidth(), colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow)) { Column(content = content) } }

@Composable
internal fun AdminOverview(overview: JSONObject, compact: Boolean = false, servicesOnly: Boolean = false) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        if (!servicesOnly) AdminCard {
            Column(Modifier.padding(16.dp)) {
                AdminValues(overview.optJSONObject("users") ?: JSONObject(), listOf("total" to "账号总数", "active" to "启用账号"))
                AdminValues(overview.optJSONObject("models") ?: JSONObject(), listOf("total" to "模型总数", "enabled" to "启用模型", "vision" to "图片理解模型"))
                AdminValues(overview.optJSONObject("conversations") ?: JSONObject(), listOf("total" to "会话总数"))
                AdminValues(overview.optJSONObject("usage") ?: JSONObject(), listOf("total_requests" to "总请求", "total_tokens" to "总 Token"))
            }
        }
        if (!compact) {
            AdminHeading("运行状态")
            listOf("search" to "联网搜索", "oss" to "文件存储", "tingwu" to "音视频分析", "tts" to "语音朗读").forEach { (key, label) ->
                val config = overview.optJSONObject(key) ?: JSONObject()
                val configured = config.optBoolean("configured") && (key != "tingwu" || overview.optJSONObject("oss")?.optBoolean("media") == true)
                ListItem(headlineContent = { Text(label) }, supportingContent = { Text(if (configured) "已配置" else "待配置") },
                    trailingContent = { if (config.has("enabled")) Text(if(config.optBoolean("enabled")) "已启用" else "未启用") })
            }
            val modelCount = overview.optJSONObject("models")?.optInt("vision") ?: 0
            ListItem(headlineContent = { Text("图片理解") }, supportingContent = { Text("$modelCount 个启用模型支持图片理解") })
            val voices = overview.optJSONObject("tts")?.optInt("voice_count") ?: 0
            ListItem(headlineContent = { Text("可用语音音色") }, trailingContent = { Text("$voices 个") })
            val oss = overview.optJSONObject("oss") ?: JSONObject()
            listOf("cat" to "猫咪图片存储", "chat_image" to "聊天图片上传", "media" to "媒体文件存储").forEach { (key, label) ->
                ListItem(headlineContent = { Text(label) }, trailingContent = { Text(if(oss.optBoolean(key)) "已配置" else "待配置") })
            }
        }
    }
}
