package asia.feng.aimeimei

import android.app.Application
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import kotlinx.coroutines.*
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import okhttp3.CookieJar
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.json.JSONObject
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
@OptIn(androidx.compose.ui.test.ExperimentalTestApi::class, ExperimentalCoroutinesApi::class)
class KnowledgeScreenTest {
    private val dispatcher = UnconfinedTestDispatcher()
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>(effectContext = StandardTestDispatcher(dispatcher.scheduler))
    private lateinit var server: MockWebServer
    private lateinit var model: PlatformViewModel
    private lateinit var preferences: AppPreferences
    private val requests = CopyOnWriteArrayList<RecordedRequest>()
    private var profile = JSONObject("""{"id":"p1","title":"表达偏好","content":"请用中文简洁回答，先说结论。","type":"style","enabled":true,"sort_order":10,"token_estimate":18}""")
    private var deleted = false
    @Before fun setup() {
        val app: Application = RuntimeEnvironment.getApplication()
        listOf("chat_drafts", "native_session", "appearance").forEach { app.getSharedPreferences(it, 0).edit().clear().commit() }
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                requests.add(request)
                val path = request.requestUrl!!.encodedPath
                val body = when {
                    path == "/api/me" -> """{"authenticated":true,"user":{"id":"u1","username":"family","display_name":"家人"}}"""
                    path == "/api/conversations" -> """{"conversations":[]}"""
                    path == "/api/models" -> """{"models":[{"id":"m2","name":"历史模型","model":"test"}]}"""
                    path == "/api/search" -> if (request.requestUrl!!.queryParameter("q").isNullOrBlank()) """{"results":[]}""" else """{"results":[{"id":"message:99","type":"message","session_id":"old","message_id":99,"title":"上个月的预算讨论","snippet":"预算原文回答：按实际需求安排。","role":"assistant"}]}"""
                    path == "/api/conversations/old" -> """{"conversation":{"id":"old","title":"上个月的预算讨论","model_id":"m2","reasoning_mode":"deep"}}"""
                    path == "/api/conversations/old/messages" -> """{"messages":[{"id":98,"role":"user","content":"之前的预算是什么？"},{"id":99,"role":"assistant","content":"预算原文回答：按实际需求安排。","generation_status":"completed","sources":[{"title":"官方预算资料","url":"https://example.com/budget?q=2026#detail","snippet":"这是随回答保存的来源摘要，打开原网页可以继续核对。","position":1}]}]}"""
                    path == "/api/profiles" && request.method == "GET" -> JSONObject().put("profiles", org.json.JSONArray().apply { if (!deleted) put(profile) }).toString()
                    path == "/api/profiles/p1" && request.method == "PUT" -> { profile = JSONObject(request.body.readUtf8()).put("id", "p1"); JSONObject().put("profile", profile).toString() }
                    path == "/api/profiles/p1" && request.method == "DELETE" -> { deleted = true; "{}" }
                    else -> "{}"
                }
                return MockResponse().setBody(body)
            }
        }
        server.start()
        model = PlatformViewModel(app, PlatformApi(server.url("/"), CookieJar.NO_COOKIES), {}, {}, dispatcher = dispatcher)
        runBlocking { withTimeout(10000) { while (model.account == null || model.busy) { dispatcher.scheduler.runCurrent(); delay(10) } } }
        preferences = AppPreferences(app).apply { changeMotion(false) }
    }
    @After fun close() { model.tools.bind("", ""); server.shutdown() }
    private fun await(condition: () -> Boolean) {
        runBlocking { withTimeout(15000) {
            while (true) {
                dispatcher.scheduler.runCurrent(); Shadows.shadowOf(Looper.getMainLooper()).idle(); Snapshot.sendApplyNotifications(); compose.mainClock.advanceTimeByFrame()
                if (condition()) return@withTimeout
                delay(10)
            }
        } }; compose.waitForIdle()
    }
    private fun capture(name: String, dialog: Boolean = false) = compose.runOnIdle {
        val view = if (dialog) checkNotNull(ShadowDialog.getLatestDialog()?.window?.decorView) else compose.activity.window.decorView
        val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888); view.draw(Canvas(bitmap))
        val directory = File("build/reports/native-ui").apply { mkdirs() }
        File(directory, "$name.png").outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }; bitmap.recycle()
    }
    @Test fun drawerSearchOpensOldConversationAndLocatesOriginalMessageWithoutSending() {
        compose.setContent { MeimeiTheme(preferences) { PlatformApp(model, preferences) } }
        compose.onNodeWithContentDescription("打开历史聊天").performClick(); compose.onNodeWithText("搜索聊天内容").performClick()
        compose.onNodeWithTag("chat-search-query").performTextInput("预算")
        await { compose.onAllNodesWithTag("search-result-message:99").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("search-role-assistant").performClick()
        capture("native-fulltext-search")
        compose.onNodeWithTag("search-result-message:99").performClick()
        await { !model.busy && compose.onAllNodesWithTag("message-99").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("message-99").assertIsDisplayed(); assertEquals("old", model.selected?.id); assertEquals("m2", model.currentModelId)
        assertTrue(model.conversations.isEmpty()); assertTrue(requests.none { it.method != "GET" })
        compose.runOnIdle { model.foreground() }
        await { !model.busy }; assertEquals("old", model.selected?.id)
    }
    @Test fun savedSourcesOpenInNativeDialogAndExternalBrowser() {
        model.openSearchResult(ChatSearchResult("m", "message", "old", "99", "", "", "assistant")) {}
        runBlocking { withTimeout(10000) { while (model.busy) { dispatcher.scheduler.runCurrent(); delay(10) } } }
        compose.setContent { MeimeiTheme(preferences) { ChatScreen(model) {} } }
        compose.onNodeWithTag("chat-messages").performScrollToNode(hasTestTag("sources-99"))
        compose.onNodeWithTag("sources-99").performClick()
        compose.onNodeWithText("1. 官方预算资料").assertIsDisplayed()
        compose.onNodeWithText("这是随回答保存的来源摘要，打开原网页可以继续核对。").assertIsDisplayed()
        capture("native-web-sources", true)
        compose.onNodeWithText("打开原网页").performClick()
        val intent = Shadows.shadowOf(compose.activity).nextStartedActivity
        assertEquals(Intent.ACTION_VIEW, intent.action); assertEquals("https://example.com/budget?q=2026#detail", intent.dataString)
        assertTrue(requests.none { it.method != "GET" })
    }
    @Test fun profilesRequireExplicitSaveAndDeleteConfirmationAndCanBeDisabled() {
        compose.setContent { MeimeiTheme(preferences) { ProfilesScreen(model) } }
        await { compose.onAllNodesWithText("表达偏好").fetchSemanticsNodes().isNotEmpty() }
        capture("native-ai-profiles")
        compose.onNodeWithText("查看与编辑").performClick(); compose.onNodeWithTag("profile-content").performTextReplacement("先说明结论，再列出依据。")
        assertTrue(requests.none { it.method == "PUT" }); capture("native-ai-profile-editor", true)
        compose.onNodeWithText("保存", substring = false).performClick()
        await { !model.tools.knowledge.saving && compose.onAllNodesWithText("先说明结论，再列出依据。").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("profile-enabled-p1").performClick()
        await { !model.tools.knowledge.saving && !model.tools.knowledge.profiles.single().enabled }
        compose.onNodeWithText("删除", substring = false).performClick(); assertFalse(deleted)
        compose.onNodeWithText("删除档案").performClick()
        await { model.tools.knowledge.profiles.isEmpty() && !model.tools.knowledge.saving }; assertTrue(deleted)
        assertTrue(requests.none { it.method == "POST" && it.requestUrl!!.encodedPath.endsWith("messages") })
    }
}
