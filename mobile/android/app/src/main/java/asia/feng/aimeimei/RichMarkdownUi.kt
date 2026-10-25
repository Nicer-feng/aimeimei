package asia.feng.aimeimei

import android.annotation.SuppressLint
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.graphics.Typeface
import android.text.SpannableString
import android.text.Spanned
import android.text.method.LinkMovementMethod
import android.text.style.ForegroundColorSpan
import android.view.ActionMode
import android.view.Menu
import android.view.MenuItem
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.TextView
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import io.noties.markwon.Markwon
import io.noties.markwon.ext.tables.TablePlugin
import org.json.JSONObject
import java.io.ByteArrayInputStream

@Composable
internal fun RichMarkdownText(content: String, onQuote: ((String) -> Unit)? = null, onDiscuss: ((String) -> Unit)? = null) {
    val blocks = remember(content) { readingBlocks(content) }
    var diagram by remember { mutableStateOf<ReadingBlock.Code?>(null) }
    Column(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        blocks.forEach { block -> when (block) {
            is ReadingBlock.Text -> if (block.source.isNotBlank()) SelectableMarkdown(block.source, onQuote, onDiscuss)
            is ReadingBlock.Code -> CodeReadingBlock(block, onQuote, onDiscuss) { diagram = block }
            is ReadingBlock.Table -> WideReadingTable(block, onQuote, onDiscuss)
        } }
    }
    diagram?.let { MermaidReadingDialog(it) { diagram = null } }
}

@Composable
private fun SelectableMarkdown(source: String, onQuote: ((String) -> Unit)?, onDiscuss: ((String) -> Unit)?, modifier: Modifier = Modifier, alignment: Int = -1) {
    val color = MaterialTheme.colorScheme.onSurface.toArgb()
    val fontScale = LocalDensity.current.fontScale
    AndroidView(factory = { context -> TextView(context).apply {
        setTextIsSelectable(true); movementMethod = LinkMovementMethod.getInstance(); setLineSpacing(4f, 1.1f)
    } }, modifier = modifier.fillMaxWidth(), update = { view ->
        view.textSize = 16f * fontScale / view.resources.configuration.fontScale
        view.setTextColor(color)
        view.gravity = android.view.Gravity.TOP or when (alignment) { 0 -> android.view.Gravity.CENTER_HORIZONTAL; 1 -> android.view.Gravity.END; else -> android.view.Gravity.START }
        view.customSelectionActionModeCallback = readingSelection(view, onQuote, onDiscuss)
        if (view.tag != source) {
            val renderer = view.getTag(R.id.markdown_renderer) as? Markwon ?: Markwon.builder(view.context).usePlugin(TablePlugin.create(view.context)).build().also { view.setTag(R.id.markdown_renderer, it) }
            renderer.setMarkdown(view, source); view.tag = source
        }
    })
}

internal fun readingSelection(view: TextView, onQuote: ((String) -> Unit)?, onDiscuss: ((String) -> Unit)?): ActionMode.Callback? {
    if (onQuote == null && onDiscuss == null) return null
    return object : ActionMode.Callback {
        override fun onCreateActionMode(mode: ActionMode, menu: Menu): Boolean {
            if (onQuote != null) menu.add(0, 0x613f, 1, "引用提问")
            if (onDiscuss != null) menu.add(0, 0x6140, 2, "分支追问")
            return true
        }
        override fun onPrepareActionMode(mode: ActionMode, menu: Menu) = false
        override fun onActionItemClicked(mode: ActionMode, item: MenuItem): Boolean {
            val action = when (item.itemId) { 0x613f -> onQuote; 0x6140 -> onDiscuss; else -> return false } ?: return false
            val start = minOf(view.selectionStart, view.selectionEnd).coerceIn(0, view.text.length)
            val end = maxOf(view.selectionStart, view.selectionEnd).coerceIn(0, view.text.length)
            if (end > start) action(view.text.subSequence(start, end).toString())
            mode.finish(); return true
        }
        override fun onDestroyActionMode(mode: ActionMode) {}
    }
}

@Composable
private fun CodeReadingBlock(block: ReadingBlock.Code, onQuote: ((String) -> Unit)?, onDiscuss: ((String) -> Unit)?, openDiagram: () -> Unit) {
    val context = LocalContext.current
    val diagramKind = if (block.language == "mermaid") mermaidKind(block.source) else null
    var copied by remember(block.source) { mutableStateOf(false) }
    LaunchedEffect(copied) { if (copied) { kotlinx.coroutines.delay(1600); copied = false } }
    Surface(Modifier.fillMaxWidth().testTag("reading-code-${block.language}"), shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.surfaceContainer) {
        Column {
            Row(Modifier.fillMaxWidth().padding(start = 12.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(diagramKind ?: block.language, Modifier.weight(1f), style = MaterialTheme.typography.labelMedium)
                TextButton(onClick = { copyReadingText(context, block.source); copied = true }, modifier = Modifier.testTag("reading-copy-code")) { Text(if (copied) "已复制" else "复制") }
            }
            if (diagramKind != null) {
                Text("点开查看，可缩放和左右移动。", Modifier.padding(horizontal = 12.dp), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                OutlinedButton(onClick = openDiagram, modifier = Modifier.padding(12.dp).testTag("reading-open-diagram")) { Text("查看$diagramKind") }
            } else {
                SyntaxCode(block.source, block.language, onQuote, onDiscuss, Modifier.padding(horizontal = 12.dp).padding(bottom = 12.dp))
            }
        }
    }
}

@Composable
private fun SyntaxCode(source: String, language: String, onQuote: ((String) -> Unit)?, onDiscuss: ((String) -> Unit)?, modifier: Modifier = Modifier) {
    val dark = MaterialTheme.colorScheme.surface.luminanceForReading() < .5f
    val color = MaterialTheme.colorScheme.onSurface.toArgb()
    val ranges = remember(source, language) { codeSyntax(source, language) }
    val fontScale = LocalDensity.current.fontScale
    Row(modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
        AndroidView(factory = { context -> TextView(context).apply { typeface = Typeface.MONOSPACE; setTextIsSelectable(true); setLineSpacing(3f, 1.05f); setHorizontallyScrolling(true) } },
            modifier = Modifier.wrapContentWidth(unbounded = true), update = { view ->
                view.textSize = 13f * fontScale / view.resources.configuration.fontScale
                view.setTextColor(color)
                view.customSelectionActionModeCallback = readingSelection(view, onQuote, onDiscuss)
                val key = Triple(source, language, dark)
                if (view.tag != key) {
                    view.text = SpannableString(source.trimEnd('\n')).apply { ranges.forEach { range ->
                        val tokenColor = when (range.kind) {
                            "keyword" -> if (dark) 0xFFCE93D8 else 0xFF7B1FA2
                            "string" -> if (dark) 0xFFA5D6A7 else 0xFF2E7D32
                            "number" -> if (dark) 0xFFFFCC80 else 0xFF995000
                            else -> if (dark) 0xFF9BA59D else 0xFF657368
                        }
                        if (range.start < length) setSpan(ForegroundColorSpan(tokenColor.toInt()), range.start, range.end.coerceAtMost(length), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                    } }
                    view.tag = key
                }
            })
    }
}

@Composable
private fun WideReadingTable(table: ReadingBlock.Table, onQuote: ((String) -> Unit)?, onDiscuss: ((String) -> Unit)?) {
    val context = LocalContext.current
    var copied by remember(table.source) { mutableStateOf(false) }
    LaunchedEffect(copied) { if (copied) { kotlinx.coroutines.delay(1600); copied = false } }
    val widths = remember(table.rows) { table.rows.first().indices.map { column ->
        table.rows.take(50).maxOf { row -> row.getOrElse(column) { "" }.lineSequence().maxOfOrNull { line -> line.fold(0) { width, char -> width + if (char.code > 255) 2 else 1 } } ?: 0 }
            .let { (it * 8 + 24).coerceIn(112, 240).dp }
    } }
    Surface(Modifier.fillMaxWidth().testTag("reading-table"), shape = RoundedCornerShape(12.dp), color = MaterialTheme.colorScheme.surfaceContainerLow) {
        Column {
            Row(Modifier.fillMaxWidth().padding(start = 12.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("表格 · 左右滑动查看", Modifier.weight(1f), style = MaterialTheme.typography.labelMedium)
                TextButton(onClick = { copyReadingText(context, table.source); copied = true }) { Text(if (copied) "已复制" else "复制") }
            }
            Column(Modifier.horizontalScroll(rememberScrollState()).testTag("reading-table-scroll")) {
                table.rows.forEachIndexed { index, row ->
                    Row(Modifier.background(if (index == 0) MaterialTheme.colorScheme.surfaceContainerHighest else Color.Transparent)) {
                        row.forEachIndexed { column, cell ->
                            Box(Modifier.width(widths[column]).padding(horizontal = 10.dp, vertical = 9.dp)) {
                                SelectableMarkdown(if (index == 0) "**$cell**" else cell, onQuote, onDiscuss, alignment = table.alignments[column])
                            }
                        }
                    }
                    HorizontalDivider()
                }
            }
        }
    }
}

private fun Color.luminanceForReading(): Float = .2126f * red + .7152f * green + .0722f * blue

private fun copyReadingText(context: Context, text: String) {
    (context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).setPrimaryClip(ClipData.newPlainText("槑槑内容", text))
}

@Composable
internal fun MermaidReadingDialog(block: ReadingBlock.Code, close: () -> Unit) {
    val context = LocalContext.current
    var sourceMode by remember { mutableStateOf(false) }
    var copied by remember { mutableStateOf(false) }
    var zoom by remember { mutableStateOf(100) }
    var web by remember { mutableStateOf<WebView?>(null) }
    val dark = MaterialTheme.colorScheme.surface.luminanceForReading() < .5f
    val background = MaterialTheme.colorScheme.surface.toArgb()
    LaunchedEffect(copied) { if (copied) { kotlinx.coroutines.delay(1600); copied = false } }
    DisposableEffect(Unit) { onDispose { web?.apply { stopLoading(); loadUrl("about:blank"); destroy() }; web = null } }
    Dialog(onDismissRequest = close, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(Modifier.fillMaxSize()) {
            Column(Modifier.systemBarsPadding()) {
                Row(Modifier.fillMaxWidth().padding(start = 16.dp, end = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(mermaidKind(block.source) ?: "图表", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
                    TextButton(onClick = { copyReadingText(context, block.source); copied = true }) { Text(if (copied) "已复制" else "复制源码") }
                    TextButton(onClick = close) { Text("关闭") }
                }
                Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = { zoom = 100; sourceMode = !sourceMode }) { Text(if (sourceMode) "查看图表" else "查看源码") }
                    if (!sourceMode) {
                        TextButton(onClick = { zoom = (zoom - 25).coerceAtLeast(25); web?.evaluateJavascript("window.setDiagramZoom($zoom)", null) }, enabled = zoom > 25) { Text("缩小") }
                        TextButton(onClick = { zoom = 100; web?.evaluateJavascript("window.setDiagramZoom(100)", null) }) { Text("${zoom}%") }
                        TextButton(onClick = { zoom = (zoom + 25).coerceAtMost(400); web?.evaluateJavascript("window.setDiagramZoom($zoom)", null) }, enabled = zoom < 400) { Text("放大") }
                    }
                }
                if (sourceMode) Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(16.dp)) { SyntaxCode(block.source, "text", null, null) }
                else AndroidView(factory = { viewContext ->
                    diagramWebView(viewContext, block.source, dark).apply { setBackgroundColor(background); web = this }
                }, modifier = Modifier.fillMaxWidth().weight(1f).testTag("reading-diagram-web"), onRelease = { view ->
                    if (web === view) web = null
                    view.stopLoading(); view.loadUrl("about:blank"); view.destroy()
                })
            }
        }
    }
}

internal const val DIAGRAM_ORIGIN = "https://meimei-reading.invalid/"
internal const val DIAGRAM_SCRIPT = "mermaid-11.16.0.min.js"

internal fun isDiagramAsset(url: android.net.Uri): Boolean = url.scheme == "https" && url.host == "meimei-reading.invalid" &&
    url.port == -1 && url.userInfo == null && url.query == null && url.fragment == null && url.encodedPath == "/$DIAGRAM_SCRIPT"

@SuppressLint("SetJavaScriptEnabled")
@Suppress("DEPRECATION")
internal fun diagramWebView(context: Context, source: String, dark: Boolean): WebView = WebView(context).apply {
    settings.apply {
        javaScriptEnabled = true
        allowFileAccess = false; allowContentAccess = false
        allowFileAccessFromFileURLs = false; allowUniversalAccessFromFileURLs = false
        domStorageEnabled = false; databaseEnabled = false
        mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
        blockNetworkLoads = true; blockNetworkImage = true
        cacheMode = WebSettings.LOAD_NO_CACHE
        javaScriptCanOpenWindowsAutomatically = false; setSupportMultipleWindows(false)
        setSupportZoom(true); builtInZoomControls = true; displayZoomControls = false
        useWideViewPort = true
    }
    removeJavascriptInterface("searchBoxJavaBridge_"); removeJavascriptInterface("accessibility"); removeJavascriptInterface("accessibilityTraversal")
    isHorizontalScrollBarEnabled = true
    webViewClient = object : WebViewClient() {
        override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?) = true
        override fun shouldOverrideUrlLoading(view: WebView?, url: String?) = true
        override fun shouldInterceptRequest(view: WebView?, request: WebResourceRequest?): WebResourceResponse {
            return if (request != null && isDiagramAsset(request.url)) {
                WebResourceResponse("application/javascript", "UTF-8", context.assets.open("reading/$DIAGRAM_SCRIPT"))
            } else WebResourceResponse("text/plain", "UTF-8", 403, "Blocked", emptyMap(), ByteArrayInputStream(ByteArray(0)))
        }
    }
    loadDataWithBaseURL(DIAGRAM_ORIGIN, diagramHtml(source, dark), "text/html", "UTF-8", null)
}

internal fun diagramHtml(source: String, dark: Boolean): String {
    // JSON 编码后再转义尖括号，避免模型生成内容提前闭合脚本标签。
    val encoded = JSONObject.quote(source).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    val theme = if (dark) "dark" else "neutral"
    val background = if (dark) "#181418" else "#fffaf6"
    val foreground = if (dark) "#eee4e8" else "#211a1e"
    return """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=5,user-scalable=yes">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'none'; connect-src 'none'; font-src 'none'; frame-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'">
        <style>html,body{margin:0;min-height:100%;background:$background;color:$foreground;font:16px sans-serif}#status{padding:20px;line-height:1.6;width:calc(100vw - 40px)}#viewport{overflow:visible;padding:20px;width:max-content;min-width:calc(100% - 40px)}#diagram{transform-origin:top left}svg{max-width:none!important;height:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;padding:20px;font-size:13px;max-width:calc(100vw - 40px)}</style>
        <script src="$DIAGRAM_SCRIPT"></script></head><body><div id="status" role="status">正在绘制图表…</div><div id="viewport"><div id="diagram"></div></div><pre id="fallback" hidden></pre>
        <script>"use strict";const source=$encoded;window.setDiagramZoom=function(percent){const diagram=document.getElementById('diagram');const svg=diagram.querySelector('svg');if(!svg)return;const box=svg.viewBox.baseVal;const fit=Math.min(box.width,Math.max(240,window.innerWidth-40));const width=fit*percent/100;svg.style.width=width+'px';svg.style.height=(box.height*width/box.width)+'px';};
        (async function(){try{if(!window.mermaid)throw new Error('unavailable');mermaid.initialize({startOnLoad:false,securityLevel:'strict',theme:'$theme',maxTextSize:100000,flowchart:{htmlLabels:false},suppressErrorRendering:true});const result=await mermaid.render('native-diagram',source);document.getElementById('diagram').innerHTML=result.svg;document.getElementById('status').textContent='双指缩放，左右移动查看；也可以使用上方缩放按钮。';setDiagramZoom(100);}catch(error){document.getElementById('status').textContent='图表暂时无法绘制，原始源码已保留。可复制后检查语法。';document.getElementById('diagram').replaceChildren();const fallback=document.getElementById('fallback');fallback.hidden=false;fallback.textContent=source;}})();</script></body></html>""".trimIndent()
}
