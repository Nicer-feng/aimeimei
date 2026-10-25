package asia.feng.aimeimei

import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import kotlinx.coroutines.*
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import okhttp3.CookieJar
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
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
import java.util.concurrent.CopyOnWriteArrayList

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], qualifiers = "w390dp-h844dp-xhdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@OptIn(ExperimentalTestApi::class, ExperimentalCoroutinesApi::class)
class SideDiscussionScreenTest {
    private val dispatcher = UnconfinedTestDispatcher()
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>(effectContext = dispatcher)
    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private lateinit var state: SideDiscussionState
    private val requests = CopyOnWriteArrayList<RecordedRequest>()
    private var imported = ""
    private var appended = false
    private var saved = ""
    private var acceptImport = true
    @Before fun setup() {
        server = MockWebServer().apply { dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                requests.add(request)
                return MockResponse().setBody(when {
                    request.requestUrl!!.encodedPath == "/api/features" -> """{"features":{"side_discussion":true}}"""
                    request.requestUrl!!.encodedPath == "/api/side-discussions" -> """{"discussions":[$sideFixture]}"""
                    request.requestUrl!!.encodedPath.endsWith("/conversation") -> """{"conversation":{"id":"new-c1"}}"""
                    else -> sideDetailFixture
                })
            }
        }; start() }
        scope = CoroutineScope(SupervisorJob() + dispatcher)
        state = SideDiscussionState(PlatformApi(server.url("/"), CookieJar.NO_COOKIES), scope) {}
        state.bind("u1", "c1"); state.refreshAvailability(); await { state.available }; state.openHistory(); await { !state.loading && state.discussions.isNotEmpty() }
        val prefs = AppPreferences(RuntimeEnvironment.getApplication()).apply { changeMotion(false) }
        compose.setContent { MeimeiTheme(prefs) { SideDiscussionDialog(state, "主聊天原有草稿", onUseDraft = { text, append ->
            if (acceptImport) { imported = text; appended = append; true } else false
        }, onSavedConversation = { saved = it }) } }
    }
    @After fun close() { scope.cancel(); server.shutdown() }
    private fun await(condition: () -> Boolean) {
        runBlocking { withTimeout(15000) { while (true) {
            dispatcher.scheduler.runCurrent(); Shadows.shadowOf(Looper.getMainLooper()).idle(); Snapshot.sendApplyNotifications(); compose.mainClock.advanceTimeByFrame()
            if (condition()) return@withTimeout
            delay(10)
        } } }; compose.waitForIdle()
    }
    private fun capture(name: String) = compose.runOnIdle {
        val view = checkNotNull(ShadowDialog.getLatestDialog()?.window?.decorView)
        val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888); view.draw(Canvas(bitmap))
        val folder = File("build/reports/native-ui").apply { mkdirs() }; File(folder, "$name.png").outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }; bitmap.recycle()
    }
    @Test fun historyOpensNativeThreadAndImportRequiresDraftChoiceWithoutSending() {
        await { compose.onAllNodesWithTag("side-discussion-s1").fetchSemanticsNodes().isNotEmpty() }
        capture("native-side-discussion-history")
        compose.onNodeWithTag("side-discussion-s1").performClick()
        await { !state.loading && state.messages.size == 2 }
        compose.onNodeWithTag("side-discussion-messages").performScrollToNode(hasTestTag("side-discussion-import-21"))
        capture("native-side-discussion-thread")
        compose.onNodeWithTag("side-discussion-import-21").performClick()
        assertEquals("", imported); assertTrue(state.open)
        compose.onNodeWithText("追加到草稿", substring = false).performClick()
        assertTrue(appended); assertTrue(imported.contains("可以从材料和结论两方面检查。")); assertFalse(state.open)
        assertTrue(requests.none { it.method != "GET" })
    }
    @Test fun inputRemainsManualAndIndependentSaveReturnsServerConversation() {
        compose.onNodeWithTag("side-discussion-s1").performClick()
        await { !state.loading && compose.onAllNodesWithTag("side-discussion-save").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("side-discussion-input").performTextInput("请解释材料来源")
        assertEquals("请解释材料来源", state.draft); assertTrue(requests.none { it.method != "GET" })
        compose.onNodeWithTag("side-discussion-messages").performScrollToNode(hasTestTag("side-discussion-save"))
        compose.onNodeWithTag("side-discussion-save").performClick()
        await { saved.isNotBlank() && !state.saving }; assertEquals("new-c1", saved)
        assertEquals(1, requests.count { it.method == "POST" }); assertTrue(requests.none { it.requestUrl!!.encodedPath.endsWith("/messages") })
    }
    @Test fun rejectedImportKeepsThreadAndConfirmationOpenUntilDraftCanAcceptIt() {
        compose.onNodeWithTag("side-discussion-s1").performClick()
        await { !state.loading && state.messages.size == 2 }
        compose.onNodeWithTag("side-discussion-messages").performScrollToNode(hasTestTag("side-discussion-import-21"))
        compose.onNodeWithTag("side-discussion-import-21").performClick()
        acceptImport = false
        compose.onNodeWithText("追加到草稿", substring = false).performClick()
        assertTrue(state.open); assertEquals("", imported)
        compose.onNodeWithText("主聊天已有草稿", substring = false).assertIsDisplayed()
        acceptImport = true
        compose.onNodeWithText("追加到草稿", substring = false).performClick()
        assertFalse(state.open); assertTrue(imported.isNotBlank())
    }
}
