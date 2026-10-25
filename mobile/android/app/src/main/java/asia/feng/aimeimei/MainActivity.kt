package asia.feng.aimeimei

import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import android.Manifest
import android.os.Build
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
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.Density
import androidx.compose.ui.platform.LocalDensity
import com.caverock.androidsvg.SVG

class MainActivity : ComponentActivity() {
    private val model get() = (application as MeimeiApplication).chat
    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        restoreIncomingShareReceipt(intent, savedInstanceState)
        model.incomingShares.accept(intent, model.account?.id.orEmpty())
        if (Build.VERSION.SDK_INT >= 33 && !getPreferences(MODE_PRIVATE).getBoolean("notification_requested", false)) {
            getPreferences(MODE_PRIVATE).edit().putBoolean("notification_requested", true).apply()
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        setContent {
            val preferences = remember { AppPreferences(applicationContext) }
            MeimeiTheme(preferences) { PlatformApp(model, preferences) }
        }
    }
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent); setIntent(intent)
        model.incomingShares.accept(intent, model.account?.id.orEmpty())
    }
    override fun onSaveInstanceState(outState: Bundle) {
        saveIncomingShareReceipt(intent, outState)
        super.onSaveInstanceState(outState)
    }
    override fun onStart() { super.onStart(); model.foreground() }
    override fun onStop() { if (!isChangingConfigurations) model.background(); super.onStop() }
}

@Composable
internal fun MeimeiTheme(preferences: AppPreferences, content: @Composable () -> Unit) {
    val dark = when (preferences.theme) { "dark" -> true; "light" -> false; else -> isSystemInDarkTheme() }
    val density = LocalDensity.current
    val colors = if (dark) darkColorScheme(primary = Color(0xFFE6A7BE)) else lightColorScheme(
        primary = Color(0xFF9C4F6F), secondary = Color(0xFF6E7370), background = Color(0xFFFFFAF6), surface = Color(0xFFFFFAF6))
    CompositionLocalProvider(LocalDensity provides Density(density.density, density.fontScale * preferences.fontScale), LocalAppMotion provides preferences.motion) {
        MaterialTheme(colorScheme = colors, content = content)
    }
}

@Composable
internal fun PasswordLoginForm(model: PlatformViewModel) {
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var answer by remember(model.captcha?.id) { mutableStateOf("") }
    LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                Image(painterResource(R.drawable.meimei_avatar), contentDescription = "槑槑", modifier = Modifier.size(48.dp).clip(RoundedCornerShape(14.dp)))
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
internal fun MarkdownText(content: String, onQuote: ((String) -> Unit)? = null, onDiscuss: ((String) -> Unit)? = null) {
    RichMarkdownText(content, onQuote, onDiscuss)
}
