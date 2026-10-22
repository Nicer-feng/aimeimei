package asia.feng.aimeimei

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File

internal fun chatImageBoundsValid(file: File): Boolean {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(file.path, bounds)
    return bounds.outWidth > 0 && bounds.outHeight > 0
}

// 限制解码尺寸，并修正手机相机写入的旋转和镜像方向。
internal fun decodeChatImage(file: File, maxDimension: Int): Bitmap? {
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeFile(file.path, bounds)
    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null
    var sample = 1
    while (bounds.outWidth / sample > maxDimension || bounds.outHeight / sample > maxDimension) sample *= 2
    val bitmap = BitmapFactory.decodeFile(file.path, BitmapFactory.Options().apply { inSampleSize = sample }) ?: return null
    val orientation = runCatching { ExifInterface(file.path).getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL) }.getOrDefault(1)
    val matrix = Matrix().apply {
        when (orientation) {
            2 -> setScale(-1f, 1f)
            3 -> setRotate(180f)
            4 -> setScale(1f, -1f)
            5 -> { setRotate(90f); postScale(-1f, 1f) }
            6 -> setRotate(90f)
            7 -> { setRotate(270f); postScale(-1f, 1f) }
            8 -> setRotate(270f)
        }
    }
    return if (matrix.isIdentity) bitmap else Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true).also { if (it !== bitmap) bitmap.recycle() }
}

@Composable
internal fun ChatImageThumbnail(item: ChatAttachment, tools: ChatTools, onOpen: () -> Unit) {
    val local = tools.localFile(item)
    var retry by remember(item.clientKey, item.id) { mutableIntStateOf(0) }
    var failure by remember(item.clientKey, item.id) { mutableStateOf(false) }
    val bitmap by produceState<Bitmap?>(null, item.id, item.clientKey, local?.path, retry) {
        value = null; failure = false
        try {
            val file = local ?: tools.imageFile(item)
            value = withContext(Dispatchers.IO) { decodeChatImage(file, 480) }
            failure = value == null
        } catch (cancelled: CancellationException) { throw cancelled }
        catch (_: Exception) { failure = true }
    }
    Surface(shape = MaterialTheme.shapes.medium, color = MaterialTheme.colorScheme.surfaceContainerHigh,
        modifier = Modifier.fillMaxWidth().height(132.dp).testTag("thumbnail-${item.clientKey}")) {
        Box(Modifier.fillMaxSize().clickable(onClickLabel = "全屏查看图片", onClick = onOpen), contentAlignment = Alignment.Center) {
            val image = bitmap
            if (image != null) {
                Image(image.asImageBitmap(), "图片缩略图：${item.name}", Modifier.fillMaxSize(), contentScale = ContentScale.Fit)
                Surface(Modifier.align(Alignment.BottomEnd).padding(6.dp), shape = MaterialTheme.shapes.small, color = MaterialTheme.colorScheme.surface.copy(alpha = .88f)) {
                    Text("点击查看大图", Modifier.padding(horizontal = 8.dp, vertical = 4.dp), style = MaterialTheme.typography.labelSmall)
                }
            } else if (failure) Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(if (item.id.isBlank()) "本地预览暂不可用" else "图片加载失败", style = MaterialTheme.typography.bodySmall)
                TextButton(onClick = { retry++ }) { Text("重新加载图片") }
            } else CircularProgressIndicator(Modifier.size(24.dp), strokeWidth = 2.dp)
        }
    }
}

@Composable
internal fun FullscreenChatImage(item: ChatAttachment, file: File?, loading: Boolean, error: String, close: () -> Unit, retry: () -> Unit) {
    var decoding by remember(file) { mutableStateOf(file != null) }
    val bitmap by produceState<Bitmap?>(null, file) {
        decoding = file != null
        value = if (file == null) null else withContext(Dispatchers.IO) { runCatching { decodeChatImage(file, 2048) }.getOrNull() }
        decoding = false
    }
    var scale by remember(file) { mutableFloatStateOf(1f) }
    var offset by remember(file) { mutableStateOf(Offset.Zero) }
    var size by remember { mutableStateOf(IntSize.Zero) }
    Dialog(onDismissRequest = close, properties = DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false)) {
        Surface(Modifier.fillMaxSize(), color = Color.Black, contentColor = Color.White) {
            Column(Modifier.systemBarsPadding().padding(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(item.name, Modifier.weight(1f), maxLines = 1, color = Color.White)
                    TextButton(onClick = close) { Text("关闭", color = Color.White) }
                }
                Box(Modifier.weight(1f).fillMaxWidth().clipToBounds().onSizeChanged { size = it }
                    .pointerInput(file) { detectTapGestures(onDoubleTap = { scale = if (scale > 1f) 1f else 2f; offset = Offset.Zero }) }
                    .pointerInput(file) { detectTransformGestures { _, pan, zoom, _ ->
                        scale = (scale * zoom).coerceIn(1f, 5f)
                        val x = size.width * (scale - 1f) / 2; val y = size.height * (scale - 1f) / 2
                        offset = Offset((offset.x + pan.x).coerceIn(-x, x), (offset.y + pan.y).coerceIn(-y, y))
                    } }, contentAlignment = Alignment.Center) {
                    val image = bitmap
                    if (image != null) Image(image.asImageBitmap(), item.name, Modifier.fillMaxSize().graphicsLayer {
                        scaleX = scale; scaleY = scale; translationX = offset.x; translationY = offset.y
                    }, contentScale = ContentScale.Fit)
                    else if (loading || decoding) CircularProgressIndicator(color = Color.White)
                    else Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(error.ifBlank { "图片暂时无法显示" }, color = Color.White)
                        TextButton(onClick = retry) { Text("重试", color = Color.White) }
                    }
                }
                Text("双指缩放 · 双击放大或还原 · 拖动查看", color = Color.LightGray, style = MaterialTheme.typography.bodySmall, modifier = Modifier.align(Alignment.CenterHorizontally))
            }
        }
    }
}
