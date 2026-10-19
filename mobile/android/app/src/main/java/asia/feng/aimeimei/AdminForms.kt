package asia.feng.aimeimei

import org.json.JSONArray
import org.json.JSONObject

internal enum class AdminFieldType { TEXT, SECRET, MULTILINE, NUMBER, SWITCH, CHOICE }
internal data class AdminField(val key: String, val label: String, val type: AdminFieldType = AdminFieldType.TEXT,
    val default: String = "", val required: Boolean = false, val min: Double? = null, val max: Double? = null,
    val choices: List<Pair<String, String>> = emptyList(), val help: String = "")
internal data class AdminForm(val kind: String, val title: String, val fields: List<AdminField>, val source: JSONObject,
    val path: List<String>, val method: String = "POST")
private fun toggle(key: String, title: String, default: Boolean = false) = AdminField(key, title, AdminFieldType.SWITCH, default.toString())
private fun secret(key: String = "api_key", title: String = "API Key") = AdminField(key, title, AdminFieldType.SECRET,
    help = "留空保留已保存的密钥")
private fun number(key: String, title: String, default: String, min: Double, max: Double) =
    AdminField(key, title, AdminFieldType.NUMBER, default, min = min, max = max)
private fun choice(key: String, title: String, default: String, vararg values: Pair<String, String>) =
    AdminField(key, title, AdminFieldType.CHOICE, default, choices = values.toList())

internal fun adminForm(kind: String, source: JSONObject = JSONObject()): AdminForm {
    val editing = source.optString("id").isNotEmpty()
    val modelFields = listOf(
        AdminField("name", "显示名称", required = true), AdminField("provider", "供应商"),
        AdminField("base_url", "API Base URL", required = true), AdminField("model", "模型 ID", required = true),
        AdminField("system_prompt", "系统提示词", AdminFieldType.MULTILINE), toggle("enabled", "启用模型", true),
        toggle("supports_vision", "支持图片理解"), toggle("supports_native_web_search", "百炼原生联网"),
        toggle("supports_reasoning_control", "支持快速、平衡、深度思考档位"),
        number("input_price_per_million", "输入价格（元 / 百万 Token）", "0", 0.0, 1000000000.0),
        number("output_price_per_million", "输出价格（元 / 百万 Token）", "0", 0.0, 1000000000.0),
        toggle("cost_enabled", "参与成本统计"), AdminField("cost_note", "成本备注"), secret())
    val fields = when (kind) {
        "users" -> listOfNotNull(
            if (!editing) AdminField("username", "账号", required = true, help = "字母、数字、下划线或短横线") else null,
            AdminField("display_name", "显示名"),
            choice("role", "角色", "family", "family" to "家庭成员", "admin" to "管理员"), toggle("is_active", "启用账号", true),
            AdminField("phone", "手机号", help = "可选，用于短信登录"), toggle("phone_verified", "确认手机号并启用短信登录"),
            AdminField("password", if (editing) "新密码" else "密码", AdminFieldType.SECRET, required = !editing,
                help = if (editing) "留空保持原密码，修改时至少 6 位" else "至少 6 位"))
        "models" -> modelFields
        "model-key" -> listOf(secret(), toggle("clear_api_key", "清除已保存的模型密钥"))
        "search" -> listOf(choice("provider", "搜索服务", "tavily", "tavily" to "Tavily", "brave" to "Brave Search"),
            toggle("enabled", "启用联网搜索"), choice("mode", "搜索策略", "auto", "auto" to "自动联网", "manual" to "手动开关", "always" to "强制联网"),
            choice("depth", "搜索深度", "advanced", "advanced" to "更准", "basic" to "更快"),
            number("result_count", "结果数量", "5", 1.0, 8.0), secret(), toggle("clear_api_key", "清除已保存的搜索密钥"))
        "tts" -> listOf(toggle("enabled", "启用语音朗读"),
            choice("provider", "语音服务", "volcengine", "volcengine" to "Volcengine / Doubao"),
            AdminField("endpoint", "服务地址", default = "https://openspeech.bytedance.com/api/v3/tts/unidirectional", required = true), secret(),
            AdminField("model", "语音模型", default = "doubao-tts-v3"), AdminField("default_voice", "默认音色 ID", required = true, help = "必须对应下方的一个可用音色"),
            toggle("cache_enabled", "缓存音频到 OSS", true), number("default_speed", "默认语速", "1", 0.5, 2.0),
            number("default_volume", "默认音量", "1", 0.5, 2.0), number("sample_rate", "采样率", "24000", 8000.0, 48000.0),
            number("long_text_threshold", "长文本阈值", "5000", 500.0, 50000.0))
        "features" -> listOf(toggle("selection_quote", "选中文字引用提问", true), toggle("side_discussion", "侧边讨论", true), toggle("long_text_detection", "长文本检测与整理", true))
        "sms-auth" -> listOf(toggle("enabled", "启用短信登录"), AdminField("scheme_name", "方案名称（可选）"),
            AdminField("sign_name", "短信签名"), AdminField("template_code", "验证码模板 Code"),
            AdminField("code_param_name", "验证码参数名", default = "code", required = true), AdminField("minutes_param_name", "有效期参数名（可空）"),
            number("valid_seconds", "验证码有效期（秒）", "300", 60.0, 1800.0), number("resend_seconds", "重发间隔（秒）", "60", 60.0, 600.0))
        "password" -> listOf(AdminField("password", "新的家用登录密码", AdminFieldType.SECRET, required = true, help = "至少 8 位，保存后所有账号的登录会话会失效"))
        else -> error("未知管理表单")
    }
    val title = when (kind) {
        "users" -> if (editing) "编辑账号" else "新增账号"; "models" -> if (editing) "编辑模型" else "新增模型"
        "model-key" -> "模型密钥"; "search" -> "联网搜索"; "tts" -> "语音服务"; "features" -> "交互功能开关"
        "sms-auth" -> "短信登录"; else -> "修改家用登录密码"
    }
    val path = if (kind == "model-key") listOf("models", source.getString("id"))
        else if (editing && kind in setOf("users", "models")) listOf(kind, source.getString("id")) else listOf(kind)
    return AdminForm(kind, title, fields, source, path, if (editing && kind in setOf("users", "models", "model-key")) "PUT" else "POST")
}

internal fun AdminForm.initialValues(): Map<String, String> = fields.associate { field ->
    field.key to if (field.type == AdminFieldType.SECRET || field.key == "clear_api_key") field.default
        else if (!source.has(field.key) || source.isNull(field.key)) field.default else source.get(field.key).toString()
}.toMutableMap().apply {
    if (kind == "models" && (source.optDouble("input_price_per_million") > 0 || source.optDouble("output_price_per_million") > 0)) this["cost_enabled"] = "true"
}

// 仅在内存中保存未提交的凭证，JSON 类型与现有 Web 接口保持一致。
internal fun AdminForm.validate(values: Map<String, String>, voices: List<Map<String, String>>): String? {
    for (field in fields) {
        val raw = values[field.key].orEmpty()
        if (field.required && raw.isBlank()) return "请填写${field.label}"
        if (field.type == AdminFieldType.NUMBER) {
            val value = raw.toDoubleOrNull()
            if (value == null || !value.isFinite() || value < (field.min ?: -Double.MAX_VALUE) || value > (field.max ?: Double.MAX_VALUE))
                return "${field.label}应在 ${field.min} 到 ${field.max} 之间"
            if (field.key in setOf("result_count", "sample_rate", "long_text_threshold", "valid_seconds", "resend_seconds") && value % 1 != 0.0)
                return "${field.label}需要填写整数"
        }
        if (field.type == AdminFieldType.CHOICE && field.choices.none { it.first == raw }) return "请选择${field.label}"
    }
    if (kind == "users") {
        if (source.optString("id").isEmpty() && !Regex("[a-zA-Z0-9_-]{2,32}").matches(values["username"].orEmpty())) return "账号需为 2 到 32 位字母、数字、下划线或短横线"
        val phone = values["phone"].orEmpty().trim()
        if (phone.isNotEmpty() && !Regex("(?:\\+?86)?1[3-9]\\d{9}").matches(phone)) return "请填写正确的手机号"
        if (phone.isEmpty() && values["phone_verified"] == "true") return "请先填写需要确认的手机号"
    }
    val password = values["password"].orEmpty()
    if (password.isNotEmpty() && password.length < if (kind == "password") 8 else 6) return "密码长度不足"
    if (kind == "models" && !Regex("https?://[^\\s]+").matches(values["base_url"].orEmpty().trim())) return "请填写完整的 API 地址"
    if (kind == "tts") {
        if (voices.isEmpty() || voices.any { it["id"].isNullOrBlank() || it["resource_id"].isNullOrBlank() }) return "每个音色都需要音色 ID 和资源 ID"
        if (voices.map { it["id"].orEmpty().trim() }.toSet().size != voices.size) return "音色 ID 不能重复"
        if (voices.none { it["id"].orEmpty().trim() == values["default_voice"].orEmpty().trim() }) return "默认音色 ID 必须在可用音色中"
        if (!values["endpoint"].orEmpty().trim().startsWith("https://")) return "语音服务地址需要使用 HTTPS"
    }
    if (kind == "sms-auth") {
        if (values["enabled"] == "true" && (values["sign_name"].isNullOrBlank() || values["template_code"].isNullOrBlank())) return "启用短信登录前请填写签名和模板"
        if (!Regex("[A-Za-z_][A-Za-z0-9_]*").matches(values["code_param_name"].orEmpty())) return "验证码参数名格式不正确"
        val minutes = values["minutes_param_name"].orEmpty()
        if (minutes.isNotEmpty() && !Regex("[A-Za-z_][A-Za-z0-9_]*").matches(minutes)) return "有效期参数名格式不正确"
    }
    if (values["clear_api_key"] == "true" && !values["api_key"].isNullOrBlank()) return "填写新密钥与清除密钥只能选择一项"
    return null
}
internal fun AdminForm.payload(values: Map<String, String>, voices: List<Map<String, String>>): JSONObject {
    val body = JSONObject()
    fields.forEach { field ->
        val raw = values[field.key].orEmpty()
        when (field.type) {
            AdminFieldType.SWITCH -> body.put(field.key, raw == "true")
            AdminFieldType.NUMBER -> body.put(field.key, raw.toDouble())
            AdminFieldType.SECRET -> if (raw.isNotEmpty()) body.put(field.key, raw)
            else -> body.put(field.key, raw.trim())
        }
    }
    if (kind == "models" && (body.optDouble("input_price_per_million") > 0 || body.optDouble("output_price_per_million") > 0)) body.put("cost_enabled", true)
    if (kind == "tts") body.put("voices", JSONArray().apply { voices.forEach { voice -> put(JSONObject(voice.mapValues { it.value.trim() })) } })
    return if (kind == "features") JSONObject().put("features", body) else body
}
internal fun jsonRows(array: JSONArray?): List<JSONObject> = if (array == null) emptyList() else (0 until array.length()).mapNotNull { array.optJSONObject(it) }
