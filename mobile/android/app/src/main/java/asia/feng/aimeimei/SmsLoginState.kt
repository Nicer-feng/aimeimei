package asia.feng.aimeimei

import android.os.SystemClock
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.*

internal data class SmsConfiguration(val available: Boolean, val validity: Long, val interval: Long)
internal fun normalizedPhone(value: String): String {
    val compact = value.replace(Regex("[\\s-]"), "")
    val raw = when { compact.startsWith("+86") -> compact.removePrefix("+86"); compact.startsWith("0086") -> compact.removePrefix("0086"); else -> compact }
    return raw.takeIf { Regex("1[3-9]\\d{9}").matches(it) }.orEmpty()
}
internal fun smsFailureHint(status: Int, raw: String): String = when (status) {
    401 -> "验证码不正确或已过期，请核对后重试"
    429 -> "获取验证码过于频繁，请稍后再试"
    503 -> "短信登录暂未开放，请使用账号密码登录"
    400 -> "请输入正确的手机号和 6 位验证码"
    else -> if (raw == "短信服务暂时不可用，请稍后重试") raw else "短信服务暂时不可用，请稍后重试"
}

// 手机号、验证码和挑战只留在内存；冷却使用单调时钟，切页不会重复发短信。
internal class SmsLoginState(private val api: PlatformApi, private val scope: CoroutineScope,
                             private val clock: () -> Long = SystemClock::elapsedRealtime) {
    private var generation = 0
    private var configJob: Job? = null
    private var sendJob: Job? = null
    var config by mutableStateOf<SmsConfiguration?>(null); private set
    var loading by mutableStateOf(false); private set
    var sending by mutableStateOf(false); private set
    var error by mutableStateOf(""); private set
    var notice by mutableStateOf(""); private set
    var phone by mutableStateOf(""); private set
    var challenge by mutableStateOf(""); private set
    private var resendAt = 0L
    val remaining get() = ((resendAt - clock() + 999) / 1000).coerceAtLeast(0)
    fun load(force: Boolean = false) {
        if (loading || (!force && config != null)) return
        val ticket = generation
        configJob = scope.launch {
            loading = true; error = ""
            try {
                val row = api.request(listOf("api", "sms-login", "config")).getJSONObject("sms_auth")
                if (ticket == generation) config = SmsConfiguration(row.optBoolean("enabled") && row.optBoolean("configured"),
                    row.optLong("valid_seconds", 300).coerceAtLeast(1), row.optLong("resend_seconds", 60).coerceAtLeast(1))
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { if (ticket == generation) error = "暂时无法读取短信登录配置，可以刷新重试或使用密码登录" }
            finally { if (ticket == generation) loading = false }
        }
    }
    fun editPhone(value: String) {
        if (sending) return
        if (phone != value) { phone = value; challenge = ""; notice = ""; error = "" }
    }
    fun send() {
        val requested = normalizedPhone(phone)
        if (loading || sending || remaining > 0 || config?.available != true || requested.isBlank()) return
        val ticket = generation; phone = requested
        // 即使网络断开，也先保留冷却，防止用户反复点击造成重复发送。
        resendAt = clock() + (config?.interval ?: 60) * 1000
        challenge = ""; error = ""; notice = ""
        sendJob = scope.launch {
            sending = true
            try {
                val row = api.request(listOf("api", "sms-login", "send"), org.json.JSONObject().put("phone", requested))
                if (ticket == generation && phone == requested) {
                    challenge = row.getString("challenge_id")
                    resendAt = clock() + row.optLong("resend_after", config?.interval ?: 60).coerceAtLeast(0) * 1000
                    notice = "如手机号已绑定，验证码将很快送达。"
                }
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (failure: Exception) { if (ticket == generation) error = (failure as? ApiFailure)?.message ?: "发送状态未确认，请稍候再试" }
            finally { if (ticket == generation) sending = false }
        }
    }
    fun verified() { generation++; configJob?.cancel(); sendJob?.cancel(); loading = false; sending = false; challenge = ""; phone = ""; error = ""; notice = ""; resendAt = 0 }
}
