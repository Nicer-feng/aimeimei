package asia.feng.aimeimei

import android.annotation.SuppressLint
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import android.webkit.CookieManager
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.JsResult
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrl
import java.net.URLEncoder

internal fun webToolUrl(base: HttpUrl, tool: String, conversation: String): String {
    val path = when (tool) { "cloud" -> "/admin/share"; "gifts" -> "/gifts"; else -> "/ai/" }
    val encode = { value: String -> URLEncoder.encode(value, "UTF-8") }
    return base.newBuilder().encodedPath(path).encodedFragment("app-tool=${encode(tool)}&conversation=${encode(conversation)}").build().toString()
}

internal fun sameWebOrigin(base: HttpUrl, value: String): Boolean = runCatching {
    val url = value.toHttpUrl()
    url.scheme == "https" && url.host == base.host && url.port == base.port && url.username.isEmpty() && url.password.isEmpty()
}.getOrDefault(false)

@SuppressLint("SetJavaScriptEnabled")
@Composable
internal fun WebToolScreen(model: PlatformViewModel, tool: String, conversation: String) {
    val context = LocalContext.current
    val base = remember { BuildConfig.API_BASE_URL.toHttpUrl() }
    val url = remember(tool, conversation) { webToolUrl(base, tool, conversation) }
    var webView by remember { mutableStateOf<WebView?>(null) }
    var progress by remember { mutableIntStateOf(0) }
    var failed by remember { mutableStateOf(false) }
    var canGoBack by remember { mutableStateOf(false) }
    var upload by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }
    var jsDialog by remember { mutableStateOf<Pair<String, JsResult>?>(null) }
    val picker = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        upload?.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data)
            ?.filter { it.scheme == "content" }?.toTypedArray())
        upload = null
    }
    val external: (String) -> Unit = { value ->
        if (runCatching { value.toHttpUrl().scheme == "https" }.getOrDefault(false)) {
            try { context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(value))) }
            catch (_: ActivityNotFoundException) { failed = true }
        }
    }
    BackHandler(canGoBack) { webView?.goBack() }
    DisposableEffect(Unit) {
        onDispose {
            jsDialog?.second?.cancel(); jsDialog = null
            upload?.onReceiveValue(null); upload = null
            webView?.apply { stopLoading(); webChromeClient = null; destroy() }
            webView = null
        }
    }
    Column(Modifier.fillMaxSize()) {
        if (progress < 100 && !failed) LinearProgressIndicator(progress = { progress / 100f }, modifier = Modifier.fillMaxWidth())
        if (failed) Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("页面加载失败，请检查网络", style = MaterialTheme.typography.bodySmall, modifier = Modifier.weight(1f).padding(vertical = 12.dp))
            TextButton(onClick = { failed = false; webView?.reload() }) { Text("重试") }
        }
        AndroidView(modifier = Modifier.weight(1f).fillMaxWidth(), factory = {
            WebView(context).apply {
                webView = this
                settings.apply {
                    javaScriptEnabled = true; domStorageEnabled = true
                    allowFileAccess = false; allowContentAccess = true
                    mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
                    javaScriptCanOpenWindowsAutomatically = false
                    mediaPlaybackRequiresUserGesture = true
                    userAgentString += " AimeimeiAndroid/${BuildConfig.VERSION_NAME}"
                }
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                        if (sameWebOrigin(base, request.url.toString())) return false
                        if (request.isForMainFrame) external(request.url.toString())
                        return true
                    }
                    override fun onPageFinished(view: WebView, page: String) { canGoBack = view.canGoBack() }
                    override fun onReceivedError(view: WebView, request: WebResourceRequest, error: WebResourceError) {
                        if (request.isForMainFrame) failed = true
                    }
                }
                webChromeClient = object : WebChromeClient() {
                    override fun onJsAlert(view: WebView, page: String, message: String, result: JsResult): Boolean {
                        if (!sameWebOrigin(base, page)) { result.cancel(); return true }
                        jsDialog?.second?.cancel(); jsDialog = message to result; return true
                    }
                    override fun onJsConfirm(view: WebView, page: String, message: String, result: JsResult): Boolean = onJsAlert(view, page, message, result)
                    override fun onProgressChanged(view: WebView, value: Int) { progress = value; canGoBack = view.canGoBack() }
                    override fun onShowFileChooser(view: WebView, callback: ValueCallback<Array<Uri>>, params: FileChooserParams): Boolean {
                        upload?.onReceiveValue(null); upload = callback
                        try { picker.launch(params.createIntent()) }
                        catch (_: ActivityNotFoundException) { upload?.onReceiveValue(null); upload = null }
                        return true
                    }
                }
                setDownloadListener { target, _, _, _, _ -> external(target) }
                // 每次进入先清除旧网页会话，再只注入当前原生账号的同源 Cookie。
                // 不向 JavaScript 暴露凭据，也不注册原生 JS 桥接。
                val manager = CookieManager.getInstance()
                manager.setAcceptCookie(true); manager.setAcceptThirdPartyCookies(this, false)
                manager.removeAllCookies {
                    val cookie = model.cookies.loadForRequest(base).firstOrNull()
                    if (cookie == null) { failed = true }
                    else manager.setCookie(base.toString(), cookie.toString()) { accepted ->
                        if (accepted && webView === this) { manager.flush(); loadUrl(url) }
                        else if (webView === this) failed = true
                    }
                }
            }
        })
    }
    jsDialog?.let { (message, result) ->
        AlertDialog(onDismissRequest = { result.cancel(); jsDialog = null }, title = { Text("AI槑槑") }, text = { Text(message) },
            confirmButton = { TextButton(onClick = { result.confirm(); jsDialog = null }) { Text("确定") } },
            dismissButton = { TextButton(onClick = { result.cancel(); jsDialog = null }) { Text("取消") } })
    }
}
