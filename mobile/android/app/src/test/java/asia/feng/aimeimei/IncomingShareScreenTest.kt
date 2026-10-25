package asia.feng.aimeimei

import android.app.Application
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import kotlinx.coroutines.*
import kotlinx.coroutines.test.StandardTestDispatcher
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowDialog
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], qualifiers = "w390dp-h844dp-xhdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@OptIn(ExperimentalCoroutinesApi::class, ExperimentalTestApi::class)
class IncomingShareScreenTest {
    private val dispatcher = StandardTestDispatcher()
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>(effectContext = dispatcher)
    private lateinit var app: Application
    private lateinit var scope: CoroutineScope
    private lateinit var state: IncomingShareController
    @Before fun setup() {
        app = RuntimeEnvironment.getApplication()
        File(app.cacheDir, "incoming-shares").deleteRecursively()
        app.getSharedPreferences("incoming_share_receipts", 0).edit().clear().commit()
        scope = CoroutineScope(SupervisorJob() + dispatcher); state = IncomingShareController(app, scope)
    }
    @After fun close() { state.discard(); scope.cancel() }
    private fun await(condition: () -> Boolean) {
        runBlocking { withTimeout(10000) { while (true) {
            dispatcher.scheduler.runCurrent(); Shadows.shadowOf(Looper.getMainLooper()).idle(); Snapshot.sendApplyNotifications(); compose.mainClock.advanceTimeByFrame()
            if (condition()) return@withTimeout
            delay(10)
        } } }; compose.waitForIdle()
    }
    private fun capture(name: String) = compose.runOnIdle {
        val view = checkNotNull(ShadowDialog.getLatestDialog()?.window?.decorView)
        val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888); view.draw(Canvas(bitmap))
        val folder = File("build/reports/native-ui").apply { mkdirs() }
        File(folder, "$name.png").outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }; bitmap.recycle()
    }

    @Test fun previewEditsAndDefersWithoutImportingUntilExplicitConfirmation() {
        state.accept(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, "https://example.com/article\n帮我总结这篇文章"), "u1")
        await { !state.preparing }
        var imported = ""; var deferred = false
        compose.setContent { MaterialTheme { IncomingSharePreview(state, "u1", "家人", onDefer = { deferred = true }) { imported = it.text; true } } }
        compose.onNodeWithTag("incoming-share-text").performTextReplacement("请整理为三个要点\nhttps://example.com/article")
        assertEquals("", imported)
        capture("native-incoming-share-text")
        compose.onNodeWithText("暂存，返回聊天").performClick()
        assertTrue(deferred); assertTrue(state.deferred); assertNotNull(state.pending); assertEquals("", imported)
        compose.runOnIdle { state.resumePreview() }
        compose.onNodeWithTag("incoming-share-confirm").performClick()
        await { state.pending == null }; assertTrue(imported.startsWith("请整理"))
    }

    @Test fun imageShareShowsLocalThumbnailFullscreenAndExplicitCancel() {
        val fixture = IncomingShareFixture(app); val source = fixture.image()
        state.accept(Intent(Intent.ACTION_SEND).setType("image/png").putExtra(Intent.EXTRA_STREAM, fixture.add(source)), "u1")
        await { !state.preparing }; val image = state.pending!!.images.single()
        var attempts = 0
        compose.setContent { MaterialTheme { IncomingSharePreview(state, "u1", "家人") { attempts++; true } } }
        compose.onNodeWithTag("incoming-share-image-${image.file.name}").assertExists()
        capture("native-incoming-share-image")
        compose.onNodeWithTag("incoming-share-image-${image.file.name}").performClick()
        compose.onNodeWithText("双指缩放 · 双击放大或还原 · 拖动查看").assertExists()
        compose.onNodeWithText("关闭", substring = false).performClick()
        compose.onNodeWithText("取消", substring = false).performClick()
        compose.onNodeWithText("继续预览").performClick(); assertNotNull(state.pending)
        compose.onNodeWithText("取消", substring = false).performClick()
        compose.onNodeWithText("确认取消").performClick()
        await { state.pending == null }; assertEquals(0, attempts); assertFalse(image.file.exists()); source.delete()
    }

    @Test fun unfinishedMainChatCanBeResumedWithoutLosingShare() {
        state.accept(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, "下一条材料"), "u1")
        await { !state.preparing }
        compose.setContent { MaterialTheme { IncomingSharePreview(state, "u1", canImport = false) { fail("Blocked import must not be called"); true } } }
        compose.onNodeWithTag("incoming-share-confirm").assertIsNotEnabled()
        compose.onNodeWithText("暂存，返回聊天").performClick()
        compose.onNodeWithTag("incoming-share-preview").assertDoesNotExist()
        assertEquals("下一条材料", state.pending!!.text)
    }
}
