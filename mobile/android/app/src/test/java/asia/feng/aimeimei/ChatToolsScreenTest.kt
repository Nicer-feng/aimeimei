package asia.feng.aimeimei

import android.app.Application
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.UnconfinedTestDispatcher
import kotlinx.coroutines.withTimeout
import okhttp3.CookieJar
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okio.Buffer
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
import java.io.ByteArrayOutputStream
import java.util.concurrent.CopyOnWriteArrayList

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], qualifiers = "w390dp-h844dp-xhdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@OptIn(androidx.compose.ui.test.ExperimentalTestApi::class, kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class ChatToolsScreenTest {
    private val dispatcher = UnconfinedTestDispatcher()
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>(effectContext = dispatcher)
    private lateinit var server: MockWebServer
    private lateinit var model: PlatformViewModel
    private lateinit var preferences: AppPreferences
    private val requests = CopyOnWriteArrayList<RecordedRequest>()
    private var shareBody: JSONObject? = null
    @Before fun setup() {
        val app: Application = RuntimeEnvironment.getApplication()
        listOf("chat_drafts", "native_session", "appearance").forEach { app.getSharedPreferences(it, 0).edit().clear().commit() }
        val image = Bitmap.createBitmap(240, 160, Bitmap.Config.ARGB_8888).apply { eraseColor(android.graphics.Color.rgb(170, 190, 225)) }
        val bytes = ByteArrayOutputStream().also { image.compress(Bitmap.CompressFormat.PNG, 100, it) }.toByteArray(); image.recycle()
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                requests.add(request)
                val path = request.requestUrl!!.encodedPath
                if (path == "/api/chat-images/img1/view") return MockResponse().setHeader("Content-Type", "image/png").setBody(Buffer().write(bytes))
                val body = when {
                    path == "/api/me" -> """{"authenticated":true,"user":{"id":"u1","username":"family","display_name":"家人"}}"""
                    path == "/api/conversations" -> """{"conversations":[{"id":"c1","title":"测试聊天","model_id":"m1"}]}"""
                    path == "/api/models" -> """{"models":[{"id":"m1","name":"测试模型","model":"test","supports_vision":true}]}"""
                    path == "/api/conversations/c1/messages" -> """{"messages":[{"id":1,"role":"user","content":"请看这张图片和材料","images":[{"id":"img1","filename":"照片.jpg","mime_type":"image/jpeg","file_size":100}],"documents":[{"id":"doc1","filename":"材料.pdf","mime_type":"application/pdf","file_size":1024,"status":"completed","page_count":2}]},{"id":2,"role":"assistant","content":"这是用于原生界面验收的回答，可以引用、收藏、分享和朗读。","generation_status":"completed"}]}"""
                    path == "/api/features" -> """{"features":{"selection_quote":true}}"""
                    path == "/api/favorites" && request.method == "POST" -> """{"favorite":{"id":"f1"}}"""
                    path == "/api/favorites" -> """{"favorites":[{"id":"f1","message_id":2,"conversation_id":"c1","conversation_title":"测试聊天","content":"这是收藏的原生验收回答。"}]}"""
                    path == "/api/tts/config" -> """{"tts":{"enabled":true,"configured":true,"default_voice":"v1","default_speed":1,"voices":[{"id":"v1","name":"测试音色"}]}}"""
                    path == "/api/conversations/c1/shares" -> { shareBody = JSONObject(request.body.readUtf8()); """{"share":{"id":"s1","url":"/ai/share/test-token"}}""" }
                    else -> "{}"
                }
                return MockResponse().setBody(body)
            }
        }
        server.start()
        model = PlatformViewModel(app, PlatformApi(server.url("/"), CookieJar.NO_COOKIES), {}, {}, dispatcher = Dispatchers.Unconfined)
        runBlocking { withTimeout(5000) { while (model.account == null || model.busy) delay(10) } }
        model.open(model.conversations.single())
        runBlocking { withTimeout(5000) { while (model.busy || model.messages.size != 2) delay(10) } }
        preferences = AppPreferences(app).apply { changeMotion(false) }
    }
    @After fun close() { model.tools.bind("", ""); server.shutdown() }
    private fun show(dark: Boolean = false) {
        if (dark) preferences.changeTheme("dark")
        compose.setContent { MeimeiTheme(preferences) { PlatformApp(model, preferences) } }
        await { compose.onAllNodesWithText("朗读").fetchSemanticsNodes().isNotEmpty() }
    }
    private fun await(condition: () -> Boolean) {
        compose.waitUntil(15000) {
            dispatcher.scheduler.runCurrent(); Shadows.shadowOf(Looper.getMainLooper()).idle(); Snapshot.sendApplyNotifications(); condition()
        }
        compose.waitForIdle()
    }
    private fun capture(name: String, dialog: Boolean = false) {
        compose.runOnIdle {
            val view = if (dialog) checkNotNull(ShadowDialog.getLatestDialog()?.window?.decorView) else compose.activity.window.decorView
            val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
            view.draw(Canvas(bitmap))
            val folder = java.io.File("build/reports/native-ui").apply { mkdirs() }
            java.io.File(folder, "$name.png").outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }; bitmap.recycle()
        }
    }
    @Test fun attachmentChooserUsesSystemImageCameraAndDocumentActions() {
        show(); compose.onNodeWithTag("attachment-picker").performClick()
        compose.onNodeWithText("选择图片").assertIsDisplayed(); compose.onNodeWithText("拍照").assertIsDisplayed(); compose.onNodeWithText("选择文件").assertIsDisplayed()
        assertTrue(requests.none { it.method == "POST" })
    }
    @Test fun quotingAddsTheDraftWithoutSendingAndShowsNativeAttachmentCards() {
        show(); compose.onAllNodesWithText("引用").onLast().performClick()
        await { model.tools.quotes.size == 1 }
        compose.onNodeWithText("引用 · 这是用于原生界面验收的回答，可以引用、收藏、分享和朗读。").assertIsDisplayed()
        assertTrue(requests.none { it.method == "POST" })
        capture("native-chat-quote")
    }
    @Test fun favoritesVoiceAndPublicSharingRequireNativeUserActions() {
        show(true)
        compose.onAllNodesWithContentDescription("更多消息操作").onLast().performClick()
        compose.onNodeWithText("收藏回答").performClick(); await { model.messages.last().favoriteId == "f1" }
        compose.onNodeWithText("已收藏").assertIsDisplayed()
        compose.onNodeWithText("朗读").performClick(); await { model.tools.voiceMessage != null }
        compose.onNodeWithText("测试音色").assertIsDisplayed(); assertTrue(requests.none { it.requestUrl!!.encodedPath.endsWith("/tts") })
        capture("native-voice-dialog", true)
        compose.onNodeWithText("取消").performClick()
        compose.onAllNodesWithContentDescription("更多消息操作").onLast().performClick()
        compose.onNodeWithText("创建分享链接").performClick()
        compose.onNodeWithText("本轮问答").performClick()
        assertNull(shareBody)
        capture("native-share-dialog", true)
        compose.onNodeWithText("创建链接").performClick(); await { model.tools.shareUrl.isNotEmpty() }
        assertEquals("turn", shareBody!!.getString("scope")); assertEquals(86400, shareBody!!.getInt("expires_in"))
        compose.onNodeWithText("复制链接").assertIsDisplayed()
        compose.onNodeWithText("撤销链接").performClick(); compose.onAllNodesWithText("撤销链接").onLast().performClick()
        await { model.tools.shareMessage == null }
        assertTrue(requests.any { it.method == "DELETE" && it.requestUrl!!.encodedPath == "/api/conversation-shares/s1" })
    }
    @Test fun favoriteListAndImagePreviewStayInsideNativePages() {
        show()
        // 历史内容较长时主动滚动，避免把屏幕外的附件当作已显示。
        compose.onNodeWithTag("chat-messages").performScrollToNode(hasText("图片 · 照片.jpg"))
        compose.onNodeWithText("图片 · 照片.jpg").performClick()
        await { model.tools.previewFile != null }
        await { compose.onAllNodesWithContentDescription("照片.jpg").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithContentDescription("照片.jpg").assertIsDisplayed(); capture("native-image-preview", true)
        compose.onNodeWithText("关闭").performClick()
        compose.onNodeWithContentDescription("更多工具").performClick(); compose.onNodeWithText("我的收藏").performClick()
        await { !model.tools.favoritesLoading && compose.onAllNodesWithTag("favorites-list").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("这是收藏的原生验收回答。").assertIsDisplayed(); capture("native-favorites")
        compose.onNodeWithText("查看原消息").performClick()
        await { compose.onAllNodesWithText("朗读").fetchSemanticsNodes().isNotEmpty() }
        assertEquals("c1", model.selected?.id)
    }
}
