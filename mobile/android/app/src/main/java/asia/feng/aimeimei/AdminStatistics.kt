package asia.feng.aimeimei

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.text.NumberFormat
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Locale

internal val adminMetrics = listOf(
    "total_users" to "账号总数", "active_users" to "活跃账号", "total_models" to "模型总数", "user_count" to "使用账号数",
    "total_requests" to "总请求", "request_count" to "请求数", "prompt_tokens" to "输入 Token", "completion_tokens" to "输出 Token",
    "total_tokens" to "总 Token", "cached_tokens" to "缓存命中 Token", "cache_creation_tokens" to "缓存写入 Token",
    "today_cost" to "今日估算费用", "month_cost" to "本月估算费用", "total_cost" to "累计估算费用",
    "average_request_cost" to "平均请求费用", "range_cost" to "本期估算费用", "range_requests" to "本期请求",
    "range_total_tokens" to "本期 Token", "estimated_cost" to "估算费用", "work_ms" to "工作时长", "reading_ms" to "阅读时长", "total_ms" to "总有效时长",
    "last_used_at" to "最近使用", "last_active" to "最后活跃", "created_at" to "时间")
private val chinaZone = ZoneId.of("Asia/Shanghai")
internal fun adminToday(): LocalDate = LocalDate.now(chinaZone)
internal fun adminValue(key: String, value: Any): String = when {
    key.endsWith("_ms") && key != "duration_ms" -> {
        val minutes = (value.toString().toDoubleOrNull() ?: 0.0).toLong() / 60000
        "${minutes / 60} 小时 ${minutes % 60} 分钟"
    }
    key.contains("cost") -> String.format(Locale.CHINA, "¥%.4f", value.toString().toDoubleOrNull() ?: 0.0)
    key in setOf("last_used_at", "last_active", "created_at", "updated_at") && value is Number -> {
        val timestamp = value.toLong()
        if (timestamp <= 0) "暂无记录" else Instant.ofEpochMilli(if (timestamp > 100000000000L) timestamp else timestamp * 1000)
            .atZone(chinaZone).format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"))
    }
    value is Number -> NumberFormat.getNumberInstance(Locale.CHINA).format(value)
    value is Boolean -> if (value) "已启用" else "未启用"
    else -> value.toString()
}
@Composable internal fun AdminValues(data: JSONObject, fields: List<Pair<String, String>> = adminMetrics) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp), modifier = Modifier.fillMaxWidth()) {
        fields.forEach { (key, title) -> if (data.has(key) && !data.isNull(key) && data.opt(key) !is JSONObject) Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
            Text(title, Modifier.weight(1f), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(adminValue(key, data.get(key)), Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
        } }
        if (data.has("reading_ms")) {
            val reading = data.optDouble("reading_ms"); val total = reading + data.optDouble("work_ms")
            Text("阅读占比 ${if(total > 0) (reading / total * 100).toInt() else 0}%", style = MaterialTheme.typography.bodySmall)
        }
    }
}
internal data class AdminStatsQuery(val section: String, val view: String, val term: String, val sort: String,
    val date: String, val start: String, val end: String, val range: String) {
    fun endpoint(): Pair<List<String>, Map<String, String>> = when (section) {
        "usage" -> listOf("usage-time", "admin") to mapOf("start" to start, "end" to end, "q" to term, "sort" to sort)
        "costs" -> listOf("cost-stats") to mapOf("range" to range)
        else -> if (view == "daily") listOf("token-stats", "daily") to mapOf("date" to date, "q" to term, "sort" to sort)
            else listOf("token-stats") to mapOf("view" to view, "q" to term, "sort" to sort, "model_q" to term, "model_sort" to sort)
    }
}
@Composable
internal fun AdminStatistics(model: PlatformViewModel, section: String, enabled: Boolean, onRecalculate: (String, () -> Unit) -> Unit) {
    val scope = rememberCoroutineScope()
    var view by remember(section) { mutableStateOf("users") }
    var term by remember(section) { mutableStateOf("") }
    var sort by remember(section) { mutableStateOf(if(section == "usage") "total" else "tokens") }
    var range by remember(section) { mutableStateOf("30d") }
    var trendRange by remember(section) { mutableStateOf("30d") }
    var date by remember(section) { mutableStateOf(adminToday().toString()) }
    var start by remember(section) { mutableStateOf(adminToday().minusDays(29).toString()) }
    var end by remember(section) { mutableStateOf(adminToday().toString()) }
    var applied by remember(section) { mutableStateOf<AdminStatsQuery?>(null) }
    var data by remember(section) { mutableStateOf<JSONObject?>(null) }
    var trend by remember(section) { mutableStateOf<JSONObject?>(null) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var operation by remember { mutableStateOf<Job?>(null) }
    var details by remember { mutableStateOf<Pair<String, JSONObject>?>(null) }
    var detailLoading by remember { mutableStateOf(false) }
    fun load() {
        val query = AdminStatsQuery(section, view, term, sort, date, start, end, range)
        if (section == "usage" && (start > end || LocalDate.parse(end).toEpochDay() - LocalDate.parse(start).toEpochDay() > 365 || end > adminToday().toString())) {
            error = "请选择不超过 366 天且不晚于今天的日期范围"; return
        }
        operation?.cancel(); loading = true; error = null; data = null; trend = null
        operation = scope.launch {
            try {
                val (path, parameters) = query.endpoint()
                val result = model.adminRequest(path, query = parameters)
                data = result; applied = query
                // 趋势独立于下方账号和单日筛选，失败不抹去已成功加载的明细。
                if (section == "tokens") {
                    trend = model.adminRequest(listOf("token-stats", "daily"), query = mapOf("range" to trendRange))
                } else if (section == "costs") trend = result.optJSONObject("trend")
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) { error = failure.message ?: "统计加载失败，请重试" }
            finally { loading = false }
        }
    }
    fun detail(row: JSONObject) {
        if (detailLoading || applied == null) return
        val query = applied!!
        val title = row.optString("display_name").ifBlank { row.optString("name") }.ifBlank { row.optString("username") }
        details = title to JSONObject(); detailLoading = true
        scope.launch {
            try {
                val id = row.optString("id")
                val result = when {
                    section == "usage" -> model.adminRequest(listOf("usage-time", "admin", "user"), query = mapOf("user_id" to id, "start" to query.start, "end" to query.end))
                    query.view == "daily" -> model.adminRequest(listOf("token-stats", "daily", "details"), query = mapOf("user_id" to id, "date" to query.date))
                    else -> model.adminRequest(listOf("token-stats", "details"), query = mapOf("type" to query.view, "id" to id))
                }
                details = title to result
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) { details = title to JSONObject().put("error", failure.message ?: "明细加载失败，请关闭后重试") }
            finally { detailLoading = false }
        }
    }
    LaunchedEffect(section) { load() }
    val active = enabled && !loading && !detailLoading
    LazyColumn(Modifier.fillMaxSize().testTag("admin-statistics"), contentPadding = PaddingValues(20.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        if (section == "tokens") {
            item { AdminChoice("统计维度", view, listOf("users" to "按账号", "models" to "按模型", "daily" to "按日"), active) { view = it; sort = "tokens" } }
            item { AdminChoice("全站趋势范围", trendRange, listOf("7d" to "近 7 天", "30d" to "近 30 天"), active) { trendRange = it } }
            if (view == "daily") item { AdminDate("统计日期", date, active) { date = it } }
        }
        if (section == "usage") {
            item { AdminDate("开始日期", start, active) { start = it } }
            item { AdminDate("结束日期", end, active) { end = it } }
        }
        if (section == "costs") item { AdminChoice("时间范围", range, listOf("7d" to "近 7 天", "30d" to "近 30 天", "all" to "全部时间"), active) { range = it } }
        else {
            item { OutlinedTextField(term, { term = it.take(80) }, singleLine = true, label = { Text(if(view == "models") "搜索模型、供应商或 ID" else "搜索账号或昵称") }, enabled = active, modifier = Modifier.fillMaxWidth()) }
            item { AdminChoice("排序", sort, if(section == "usage") listOf("total" to "总时长", "work" to "工作时长", "reading" to "阅读时长", "last" to "最近活跃")
                else if (view == "daily") listOf("tokens" to "Token最多", "requests" to "请求最多", "cost" to "花费最高")
                else if(view == "models") listOf("tokens" to "Token最多", "requests" to "请求最多", "recent" to "最近调用")
                else listOf("tokens" to "Token最多", "recent" to "最近使用", "created" to "注册时间"), active) { sort = it } }
        }
        item { Button(onClick = { load() }, enabled = active, modifier = Modifier.fillMaxWidth()) { Text("应用筛选并刷新") } }
        if (loading) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
        error?.let { message -> item { Text(message, color = MaterialTheme.colorScheme.error) } }
        data?.let { result ->
            item { AdminHint(when(section) {
                "usage" -> "按北京时间统计网页前台有焦点的有效使用时长；连续 2 分钟无操作暂停。现有账本尚不包含原生聊天停留时长。"
                "costs" -> "费用根据消息和价格快照估算，不等同于供应商账单；今日尚未结束。"
                else -> "全站趋势使用每日用量账本，不受下方账号和单日筛选影响；今日尚未结束。"
            }) }
            applied?.let { query -> item { AdminHint(when(section) {
                "usage" -> "当前结果：${query.start} 至 ${query.end}"
                "costs" -> "当前结果：${when(query.range) { "7d" -> "近 7 天"; "all" -> "全部时间"; else -> "近 30 天" }}"
                else -> "当前结果：${when(query.view) { "models" -> "按模型"; "daily" -> "按日 ${query.date}"; else -> "按账号" }}${if(query.term.isNotBlank()) " · ${query.term}" else ""}"
            }) } }
            item { AdminCard { Column(Modifier.padding(16.dp)) { AdminValues(result.optJSONObject("summary") ?: JSONObject()) } } }
            trend?.let { series -> item { AdminTrend(series, section == "costs") } }
            if (section == "costs") {
                item { OutlinedButton(onClick = { onRecalculate(applied?.range ?: range) { load() } }, enabled = active, modifier = Modifier.fillMaxWidth()) { Text("回算历史成本") } }
                listOf("models" to "模型费用排行", "users" to "账号费用排行").forEach { (key, title) ->
                    item { AdminHeading(title) }
                    val rows = jsonRows(result.optJSONArray(key))
                    if (rows.isEmpty()) item { AdminHint("暂无记录") }
                    items(rows) { row -> AdminStatCard(row) }
                }
            } else {
                val rows = jsonRows(result.optJSONArray(if (applied?.view == "models" && section == "tokens") "models" else "users"))
                if (rows.isEmpty()) item { AdminHint("暂无符合筛选条件的记录") }
                items(rows) { row -> AdminStatCard(row, onDetails = { detail(row) }) }
            }
        }
    }
    details?.let { (title, result) -> AlertDialog(onDismissRequest = { if (!detailLoading) details = null }, title = { Text("$title · 明细") }, text = {
        LazyColumn(verticalArrangement = Arrangement.spacedBy(12.dp)) {
            if (detailLoading) item { LinearProgressIndicator(Modifier.fillMaxWidth()) }
            if (result.has("error")) item { Text(result.optString("error"), color = MaterialTheme.colorScheme.error) }
            val rows = jsonRows(result.optJSONArray(if(section == "usage") "days" else "recent_requests"))
            if (!detailLoading && !result.has("error") && rows.isEmpty()) item { Text("暂无明细") }
            if(section != "usage") item { AdminHint("最近 20 次请求") }
            items(rows) { row -> Column { Text(row.optString("date").ifBlank { row.optString("conversation_title") }); if(row.optString("model_name").isNotBlank()) AdminHint(row.optString("model_name")); AdminValues(row) } }
        }
    }, confirmButton = { TextButton(onClick = { details = null }, enabled = !detailLoading) { Text("关闭") } }) }
}
@Composable private fun AdminStatCard(row: JSONObject, onDetails: (() -> Unit)? = null) {
    AdminCard { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(row.optString("display_name").ifBlank { row.optString("name") }.ifBlank { row.optString("model_name") }.ifBlank { row.optString("username") }, style = MaterialTheme.typography.titleMedium)
        val identity = row.optString("username").ifBlank { row.optString("model").ifBlank { row.optString("model_code") } }
        if(identity.isNotBlank()) AdminHint(identity)
        AdminValues(row)
        if(onDetails != null) TextButton(onClick = onDetails) { Text("查看明细") }
    } }
}
@OptIn(ExperimentalMaterial3Api::class)
@Composable private fun AdminDate(label: String, value: String, enabled: Boolean, changed: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    AdminRow(label, value) { if (enabled) open = true }
    if (open) {
        val state = rememberDatePickerState(initialSelectedDateMillis = LocalDate.parse(value).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli())
        DatePickerDialog(onDismissRequest = { open = false }, confirmButton = { TextButton(onClick = {
            state.selectedDateMillis?.let { changed(Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString()) }; open = false
        }) { Text("确定") } }, dismissButton = { TextButton(onClick = { open = false }) { Text("取消") } }) { DatePicker(state) }
    }
}
@Composable internal fun AdminTrend(series: JSONObject, costs: Boolean) {
    var metric by remember { mutableStateOf(if(costs) "estimated_cost" else "total_tokens") }
    var style by remember { mutableStateOf("line") }
    var expanded by remember { mutableStateOf(false) }
    val days = jsonRows(series.optJSONArray("days"))
    val color = MaterialTheme.colorScheme.primary
    val options = listOf("total_tokens" to "Token", "request_count" to "请求数", "estimated_cost" to "估算费用")
    AdminCard { Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(if(costs) "成本与调用趋势" else "全站用量趋势", style = MaterialTheme.typography.titleMedium)
        AdminHint("${series.optString("start_date")} 至 ${series.optString("end_date")}")
        AdminChoice("指标", metric, options) { metric = it }
        AdminChoice("图表", style, listOf("line" to "折线", "bar" to "柱状")) { style = it }
        val points = days.map { it.optDouble(metric).coerceAtLeast(0.0) }
        val max = (points.maxOrNull() ?: 0.0).coerceAtLeast(1.0)
        AdminHint("最高 ${adminValue(metric, points.maxOrNull() ?: 0.0)}")
        Canvas(Modifier.fillMaxWidth().height(140.dp).semantics { contentDescription = "${options.first { it.first == metric }.second}趋势，共 ${days.size} 天；可展开每日数据读取" }) {
            if (points.isNotEmpty()) {
                val step = size.width / points.size
                if (style == "bar") points.forEachIndexed { index, value ->
                    val height = (value / max * (size.height - 8.dp.toPx())).toFloat()
                    drawRect(color, Offset(index * step + step * 0.15f, size.height - height), Size(step * 0.7f, height))
                } else {
                    val path = Path()
                    points.forEachIndexed { index, value ->
                        val x = step * (index + 0.5f); val y = size.height - (value / max * (size.height - 8.dp.toPx())).toFloat()
                        if(index == 0) path.moveTo(x, y) else path.lineTo(x, y)
                        drawCircle(color, 2.dp.toPx(), Offset(x, y))
                    }
                    drawPath(path, color, style = Stroke(2.dp.toPx()))
                }
            }
        }
        AdminValues(series.optJSONObject("summary") ?: JSONObject())
        TextButton(onClick = { expanded = !expanded }) { Text(if(expanded) "收起每日数据" else "展开每日数据") }
        if(expanded) days.forEach { day -> Row(Modifier.fillMaxWidth()) { Text(day.optString("date"), Modifier.weight(1f), style = MaterialTheme.typography.bodySmall); Text(adminValue(metric, day.opt(metric) ?: 0), style = MaterialTheme.typography.bodySmall) } }
    } }
}
