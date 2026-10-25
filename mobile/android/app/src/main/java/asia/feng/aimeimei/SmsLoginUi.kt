package asia.feng.aimeimei

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay

@Composable
internal fun LoginForm(model: PlatformViewModel) {
    var smsMode by rememberSaveable { mutableStateOf(false) }
    val sms = model.sms
    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            FilterChip(!smsMode, { smsMode = false }, label = { Text("密码登录") }, enabled = !model.busy && !sms.sending)
            FilterChip(smsMode, { smsMode = true }, label = { Text("短信登录") }, enabled = !model.busy && !sms.sending)
        }
        Box(Modifier.weight(1f)) {
            if (!smsMode) PasswordLoginForm(model) else SmsLoginFields(model)
        }
    }
}

@Composable
private fun SmsLoginFields(model: PlatformViewModel) {
    val sms = model.sms
    var code by remember(sms.challenge, sms.phone) { mutableStateOf("") }
    var remaining by remember { mutableLongStateOf(sms.remaining) }
    LaunchedEffect(Unit) { sms.load() }
    LaunchedEffect(sms.sending, sms.challenge) { while (true) { remaining = sms.remaining; delay(1000) } }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("手机号登录", style = MaterialTheme.typography.headlineSmall)
        Text("使用已绑定并由管理员确认的手机号登录现有账号。", style = MaterialTheme.typography.bodyMedium)
        if (sms.loading) LinearProgressIndicator(Modifier.fillMaxWidth())
        if (sms.config?.available == false) Text("短信登录暂未开放，请切换到密码登录。", color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedTextField(sms.phone, { sms.editPhone(it.take(20)) }, label = { Text("手机号") }, prefix = { Text("+86 ") }, singleLine = true,
            enabled = !model.busy && !sms.sending, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Phone), modifier = Modifier.fillMaxWidth().testTag("sms-phone"))
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(code, { code = it.filter(Char::isDigit).take(6) }, label = { Text("6 位验证码") }, singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), enabled = !model.busy && !sms.sending,
                modifier = Modifier.weight(1f).testTag("sms-code"))
            TextButton(onClick = sms::send, enabled = !model.busy && !sms.sending && sms.config?.available == true && normalizedPhone(sms.phone).isNotBlank() && remaining == 0L,
                modifier = Modifier.testTag("sms-send")) { Text(if (sms.sending) "发送中…" else if (remaining > 0) "${remaining}秒后重发" else "获取验证码") }
        }
        if (sms.notice.isNotBlank()) Text(sms.notice, style = MaterialTheme.typography.bodySmall)
        if (sms.error.isNotBlank()) {
            Text(sms.error, color = MaterialTheme.colorScheme.error)
            if (sms.config == null) TextButton(onClick = sms::load, enabled = !sms.loading) { Text("刷新配置") }
        }
        Button(onClick = { model.loginSms(code) }, enabled = !model.busy && !sms.sending && sms.config?.available == true && sms.challenge.isNotBlank() && code.length == 6,
            modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp).testTag("sms-login")) { Text("验证并登录") }
    }
}
