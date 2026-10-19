package asia.feng.aimeimei

import android.app.Application
import android.os.Looper
import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
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
import java.util.concurrent.CopyOnWriteArrayList

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], qualifiers = "w390dp-h844dp-xhdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
@OptIn(androidx.compose.ui.test.ExperimentalTestApi::class, kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class AdminScreenTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>(effectContext = UnconfinedTestDispatcher())
    private lateinit var server: MockWebServer
    private lateinit var model: PlatformViewModel
    private lateinit var preferences: AppPreferences
    private var role = "admin"
    private val requests = CopyOnWriteArrayList<RecordedRequest>()
    private val overview = """{"overview":{"users":{"total":2,"active":2},"models":{"total":1,"enabled":1,"vision":1},"conversations":{"total":3},"usage":{"total_requests":12,"total_tokens":2000},"features":{"selection_quote":true,"side_discussion":true,"long_text_detection":true},"search":{"configured":true,"enabled":true},"oss":{"configured":true,"chat_image":true,"media":true},"tingwu":{"configured":true},"tts":{"configured":true,"enabled":true,"voice_count":1}}}"""
    @Before fun setup() {
        val app: Application = RuntimeEnvironment.getApplication()
        listOf("chat_drafts", "native_session", "appearance").forEach { app.getSharedPreferences(it, 0).edit().clear().commit() }
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                requests.add(request)
                val path = request.requestUrl!!.encodedPath
                val body = when {
                    path == "/api/me" -> """{"authenticated":true,"user":{"id":"a1","username":"admin","display_name":"管理员","role":"$role"}}"""
                    path == "/api/conversations" -> """{"conversations":[]}"""
                    path == "/api/models" || path == "/api/admin/models" -> """{"models":[{"id":"m1","name":"模型 A","model":"test","provider":"测试","base_url":"https://example.com/v1","enabled":true,"supports_vision":true,"has_api_key":true}]}"""
                    path == "/api/admin/users" -> if (request.method == "POST") """{"user":{"id":"u2"}}""" else """{"users":[{"id":"u1","username":"family","display_name":"家人","role":"family","is_active":true}]}"""
                    path == "/api/admin/overview" -> overview
                    path == "/api/admin/search" -> """{"search":{"provider":"tavily","enabled":true,"mode":"auto","depth":"advanced","result_count":5,"has_api_key":true}}"""
                    path == "/api/admin/tts" -> """{"tts":{"enabled":true,"provider":"volcengine","configured":true,"default_voice":"v1","voices":[{"id":"v1","name":"测试音色","resource_id":"test-resource"}]}}"""
                    path == "/api/admin/sms-auth" -> """{"sms_auth":{"enabled":false,"code_param_name":"code","valid_seconds":300,"resend_seconds":60}}"""
                    path == "/api/version" -> """{"version":"v2.28.7","build_id":"fixture-build","updated_at":"2026-10-19"}"""
                    path == "/api/admin/token-stats/daily" && request.requestUrl!!.queryParameter("range") != null -> """{"days":[{"date":"2026-10-19","total_tokens":2000,"request_count":12}],"summary":{"total_tokens":2000},"start_date":"2026-10-13","end_date":"2026-10-19"}"""
                    path == "/api/admin/token-stats" || path == "/api/admin/token-stats/daily" -> """{"summary":{"total_tokens":2000,"total_requests":12},"users":[{"id":"u1","display_name":"家人","username":"family","total_tokens":2000}],"models":[{"id":"m1","name":"模型 A","total_tokens":2000}]}"""
                    path == "/api/admin/cost-stats" -> """{"summary":{"range_cost":0.25,"range_requests":12},"users":[],"models":[]}"""
                    path == "/api/usage-time/admin" -> """{"summary":{"total_ms":60000,"work_ms":60000,"reading_ms":0},"users":[{"id":"u1","display_name":"家人","work_ms":60000,"reading_ms":0,"total_ms":60000}]}"""
                    path == "/api/usage-time/admin/user" -> """{"days":[{"date":"2026-10-19","work_ms":60000,"reading_ms":120000}],"summary":{"work_ms":60000,"reading_ms":120000}}"""
                    path.endsWith("details") -> """{"recent_requests":[{"conversation_title":"测试聊天","model_name":"模型 A","total_tokens":2000}]}"""
                    else -> "{}"
                }
                return MockResponse().setBody(body)
            }
        }
        server.start()
        model = PlatformViewModel(app, PlatformApi(server.url("/"), CookieJar.NO_COOKIES), {}, {}, dispatcher = Dispatchers.Unconfined)
        runBlocking { withTimeout(10000) { while (model.account == null || model.busy) delay(10) } }
        // 预热数字与嵌套 JSON 的平台解析类，避免首次后台加载与 Robolectric 主线程类初始化互相等待。
        org.json.JSONObject(overview)
        preferences = AppPreferences(app).apply { changeMotion(false) }
    }
    @After fun close() { server.shutdown() }
    private fun showShell() { compose.setContent { MeimeiTheme(preferences) { PlatformApp(model, preferences) } } }
    private fun showAdmin(dark: Boolean = false) {
        if (dark) preferences.changeTheme("dark")
        compose.setContent { MeimeiTheme(preferences) { AdminScreen(model, preferences) {} } }
        awaitTag("admin-list")
    }
    private fun awaitCondition(condition: () -> Boolean) {
        // 网络完成后的主线程回调不属于 Compose 虚拟时钟，需要显式推进 Robolectric 消息队列。
        compose.waitUntil(30000) { Shadows.shadowOf(Looper.getMainLooper()).idle(); condition() }
    }
    private fun awaitTag(tag: String) {
        compose.waitForIdle()
        try { awaitCondition { compose.onAllNodesWithTag(tag).fetchSemanticsNodes().isNotEmpty() } }
        catch (error: androidx.compose.ui.test.ComposeTimeoutException) {
            val pending = Thread.getAllStackTraces().entries.filter { (thread, stack) ->
                thread.name.startsWith("DefaultDispatcher") || stack.any { it.className.contains("Http1ExchangeCodec") }
            }.take(8).joinToString("\n") { (thread, stack) -> "${thread.name} ${thread.state}\n${stack.joinToString("\n")}" }
            throw AssertionError("等待 $tag 超时，已收到请求：${requests.map { it.requestUrl?.encodedPath }}\n${compose.onRoot().printToString()}\n$pending", error)
        }
        compose.waitForIdle()
    }
    private fun module(title: String) { compose.onNodeWithTag("admin-list").performScrollToNode(hasText(title)); compose.onNodeWithText(title).performClick(); compose.waitForIdle() }
    private fun capture(name: String) {
        compose.runOnIdle {
            val folder = java.io.File("build/reports/native-ui").apply { mkdirs() }
            val view = compose.activity.window.decorView
            val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
            view.draw(Canvas(bitmap)); java.io.File(folder, "$name.png").outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }; bitmap.recycle()
        }
    }
    @Test fun settingsOpenNativeWorkspaceAndBackReturnsToSettings() {
        showShell()
        compose.onNodeWithContentDescription("打开历史聊天").performClick()
        compose.onNodeWithText("设置与账号").performClick()
        compose.onNodeWithTag("settings-list").performScrollToNode(hasText("后台管理"))
        compose.onNodeWithText("后台管理").performClick()
        awaitTag("admin-list"); compose.onNodeWithText("管理工作台").assertIsDisplayed(); capture("admin-home")
        compose.onNodeWithContentDescription("返回").performClick()
        compose.onNodeWithText("主题").assertIsDisplayed()
    }
    @Test fun editsKeepDraftOnCancelAndCreateAccountUsesNativeForm() {
        showAdmin(); module("账号管理"); awaitTag("admin-list")
        compose.onNodeWithText("新增账号").performClick(); awaitTag("admin-editor")
        compose.onNodeWithTag("admin-field-username").performTextInput("family2")
        compose.onNodeWithTag("admin-field-display_name").performTextInput("测试家人")
        capture("admin-account")
        compose.onNodeWithContentDescription("返回").performClick()
        compose.onNodeWithText("继续编辑").performClick()
        compose.onNodeWithTag("admin-field-username").assertTextContains("family2")
        compose.onNodeWithTag("admin-editor").performScrollToNode(hasTestTag("admin-field-password"))
        compose.onNodeWithTag("admin-field-password").performTextInput("test-only-pass")
        compose.onNodeWithTag("admin-editor").performScrollToNode(hasText("保存")); compose.onNodeWithText("保存").performClick()
        awaitTag("admin-list")
        val post = requests.single { it.method == "POST" && it.requestUrl!!.encodedPath == "/api/admin/users" }
        val body = org.json.JSONObject(post.body.readUtf8())
        assertEquals("family2", body.getString("username")); assertTrue(body.getBoolean("is_active"))
        assertNull(post.getHeader("X-Admin-Key"))
    }
    @Test fun keyDeletionRequiresConfirmationAndDoesNotSubmitOnCancel() {
        showAdmin(true); module("密钥管理"); awaitTag("admin-list")
        compose.onNodeWithText("模型 A").performClick(); awaitTag("admin-editor")
        compose.onNodeWithTag("admin-field-clear_api_key").performClick()
        compose.onNodeWithText("保存").performClick()
        compose.onNodeWithText("取消").performClick()
        assertTrue(requests.none { it.method == "PUT" })
        capture("admin-keys-dark")
    }
    @Test fun nativeStatisticsShowChartAndRequestDetails() {
        showAdmin(); module("Token统计"); awaitTag("admin-statistics")
        awaitCondition { requests.any { it.requestUrl!!.encodedPath == "/api/admin/token-stats/daily" } }
        compose.onNodeWithTag("admin-statistics").performScrollToNode(hasText("查看明细"))
        capture("admin-statistics")
        compose.onNodeWithText("查看明细").performClick()
        awaitCondition { compose.onAllNodesWithText("测试聊天").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("测试聊天").assertIsDisplayed()
        assertTrue(requests.any { it.requestUrl!!.queryParameter("type") == "users" && it.requestUrl!!.queryParameter("id") == "u1" })
        compose.onNodeWithText("关闭").performClick()
    }
    @Test fun voiceAndSystemModulesUseNativeEditors() {
        showAdmin(true); module("语音服务"); awaitTag("admin-list")
        compose.onNodeWithText("配置语音服务").performClick(); awaitTag("admin-editor")
        compose.onNodeWithTag("admin-editor").performScrollToNode(hasText("默认音色"))
        compose.onNodeWithText("默认音色").performClick()
        compose.onAllNodesWithText("测试音色").onLast().performClick()
        compose.onNodeWithTag("admin-editor").performScrollToNode(hasTestTag("admin-voice-0-name"))
        compose.onNodeWithTag("admin-voice-0-name").assertTextContains("测试音色")
        capture("admin-voices-dark")
        compose.onNodeWithContentDescription("返回").performClick(); awaitTag("admin-list")
        compose.onNodeWithContentDescription("返回").performClick(); awaitTag("admin-list")
        module("系统设置"); awaitTag("admin-list")
        compose.onNodeWithText("fixture-build").assertExists()
        compose.onNodeWithText("短信登录").performClick(); awaitTag("admin-editor")
        compose.onNodeWithTag("admin-field-code_param_name").assertTextContains("code")
    }
    @Test fun familyAccountCannotCallNativeAdminGateway() {
        role = "family"; model.restore()
        runBlocking { withTimeout(10000) { while(model.busy || model.account?.role != "family") delay(10) } }
        val before = server.requestCount
        runBlocking {
            try { model.adminRequest(listOf("users")); fail("Expected permission rejection") }
            catch (error: ApiFailure) { assertEquals(403, error.status) }
        }
        assertEquals(before, server.requestCount)
    }

    @Test fun dailyUsageShowsCombinedDurationWhenServerOnlyReturnsWorkAndReading() {
        showAdmin(); module("使用时长"); awaitTag("admin-statistics")
        compose.onNodeWithTag("admin-statistics").performScrollToNode(hasText("查看明细"))
        compose.onNodeWithText("查看明细").performClick()
        awaitCondition { compose.onAllNodesWithText("3分").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("3分").assertIsDisplayed()
        compose.onNodeWithText("阅读占比 66.7%").assertIsDisplayed()
        capture("admin-usage-details")
        compose.onNodeWithText("关闭").performClick()
    }

}
