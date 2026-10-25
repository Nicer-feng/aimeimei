package asia.feng.aimeimei

import android.app.Application
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
class MobileToolsScreenTest {
    private val dispatcher = UnconfinedTestDispatcher()
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>(effectContext = StandardTestDispatcher(dispatcher.scheduler))
    private lateinit var app: Application
    private lateinit var server: MockWebServer
    private lateinit var model: PlatformViewModel
    private lateinit var preferences: AppPreferences
    private val requests = CopyOnWriteArrayList<RecordedRequest>()
    private var loggedIn = true
    private var incorrectCode = true
    @Before fun setup() {
        app = RuntimeEnvironment.getApplication()
        listOf("chat_drafts", "native_session", "appearance").forEach { app.getSharedPreferences(it, 0).edit().clear().commit() }
        server = MockWebServer().apply { dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                requests.add(request)
                val path = request.requestUrl!!.encodedPath
                val body = when (path) {
                    "/api/me" -> if (loggedIn) """{"authenticated":true,"user":{"id":"u1","username":"family","display_name":"家人"}}""" else """{"authenticated":false}"""
                    "/api/logout" -> { loggedIn = false; "{}" }
                    "/api/captcha" -> """{"captcha_id":"captcha-fixture","image_svg":"<svg xmlns='http://www.w3.org/2000/svg' width='256' height='96'><rect width='256' height='96' fill='white'/></svg>"}"""
                    "/api/conversations" -> """{"conversations":[]}"""
                    "/api/models" -> """{"models":[{"id":"m1","name":"测试模型","model":"test"}]}"""
                    "/api/sms-login/config" -> """{"sms_auth":{"enabled":true,"configured":true,"valid_seconds":300,"resend_seconds":60}}"""
                    "/api/sms-login/send" -> """{"challenge_id":"sms-fixture","resend_after":60}"""
                    "/api/sms-login/verify" -> {
                        if (incorrectCode) return MockResponse().setResponseCode(401).setBody("""{"error":"验证码不正确或已过期"}""")
                        loggedIn = true; """{"user":{"id":"u1","username":"family","display_name":"家人"}}"""
                    }
                    "/api/ocr/tasks" -> """{"tasks":[{"id":"o1","filename":"手写记录.png","status":"completed","recognized_text":"这是识别出的原始文字。"}]}"""
                    "/api/token-activity" -> {
                        val days = org.json.JSONArray()
                        for (n in 1..10) days.put(org.json.JSONObject().put("date", "2026-10-${15+n}").put("request_count", 2).put("input_tokens", n * 60).put("output_tokens", n * 40).put("total_tokens", n * 100).put("estimated_cost", .01))
                        org.json.JSONObject().put("summary", org.json.JSONObject().put("total_tokens", 5500).put("active_days", 10).put("conversation_count", 3)).put("days", days)
                            .put("day_models", org.json.JSONObject().put("2026-10-25", org.json.JSONArray().put(org.json.JSONObject().put("model_name", "测试模型").put("total_tokens", 1000).put("request_count", 2))))
                            .put("top_models", org.json.JSONArray()).put("top_conversations", org.json.JSONArray()).toString()
                    }
                    else -> "{}"
                }
                return MockResponse().setBody(body)
            }
        }; start() }
        model = PlatformViewModel(app, PlatformApi(server.url("/"), CookieJar.NO_COOKIES), {}, {}, dispatcher = dispatcher)
        runBlocking { withTimeout(10000) { while (model.account == null || model.busy) { dispatcher.scheduler.runCurrent(); delay(10) } } }
        preferences = AppPreferences(app).apply { changeMotion(false) }
    }
    @After fun close() { model.tools.bind("", ""); model.sms.verified(); server.shutdown() }
    private fun idleModel() = runBlocking { withTimeout(10000) { while (model.busy) { dispatcher.scheduler.runCurrent(); delay(10) } } }
    private fun await(stage: String = "ui", detail: () -> String = { "" }, condition: () -> Boolean) {
        try {
            runBlocking { withTimeout(15000) { while (true) {
                dispatcher.scheduler.runCurrent(); Shadows.shadowOf(Looper.getMainLooper()).idle(); Snapshot.sendApplyNotifications(); compose.mainClock.advanceTimeByFrame()
                if (condition()) return@withTimeout
                delay(10)
            } } }; compose.waitForIdle()
        } catch (timeout: TimeoutCancellationException) {
            val state = model.tools.mobile
            val tree = runCatching {
                val roots = compose.onAllNodes(isRoot(), useUnmergedTree = true)
                (0 until roots.fetchSemanticsNodes().size).joinToString("\n\n") { index ->
                    "ROOT $index\n" + roots[index].printToString(maxDepth = Int.MAX_VALUE)
                }
            }.getOrElse { "无法读取语义树：$it" }
            val screenshot = runCatching { capture("native-await-timeout-${stage.replace(Regex("[^a-zA-Z0-9-]"), "-")}") }
                .exceptionOrNull()?.let { "截图失败：$it" }.orEmpty()
            val report = """
                等待阶段：$stage（15000ms）
                account=${model.account?.id}, busy=${model.busy}, modelError=${model.error}
                ocrPreparing=${state.preparing}, processing=${state.processing}, ocrError=${state.ocrError}
                image=${state.image?.let { "${it.name}, mime=${it.mime}, exists=${it.file.isFile}, bytes=${it.file.length()}" }}
                historyLoading=${state.historyLoading}, historyError=${state.historyError}
                records=${state.records.map { "${it.id}:${it.status}" }}
                requests=${requests.map { "${it.method} ${it.requestUrl?.encodedPath}" }}
                ${detail()}
                $screenshot
                完整语义树：
                $tree
            """.trimIndent()
            val folder = File("build/reports/native-ui").apply { mkdirs() }
            File(folder, "await-timeout-${stage.replace(Regex("[^a-zA-Z0-9-]"), "-")}.txt").writeText(report)
            throw AssertionError(report).apply { initCause(timeout) }
        }
    }
    private fun capture(name: String, dialog: Boolean = false) = compose.runOnIdle {
        val view = if (dialog) checkNotNull(ShadowDialog.getLatestDialog()?.window?.decorView) else compose.activity.window.decorView
        val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888); view.draw(Canvas(bitmap))
        val folder = File("build/reports/native-ui").apply { mkdirs() }; File(folder, "$name.png").outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }; bitmap.recycle()
    }
    @Test fun fullEditorPersistsDraftAndRequiresConfirmationBeforeClearingWithoutSending() {
        model.editDraft("长材料\n".repeat(100))
        compose.setContent { MeimeiTheme(preferences) { PlatformApp(model, preferences) } }
        compose.onNodeWithText("展开编辑").performClick()
        compose.onNodeWithTag("full-draft-editor").performTextReplacement("第一段材料\n\n第二段材料与问题。")
        capture("native-full-draft-editor", true)
        compose.onNodeWithText("清空", substring = false).performClick(); compose.onNodeWithText("取消", substring = false).performClick()
        assertEquals("第一段材料\n\n第二段材料与问题。", model.draft)
        compose.onNodeWithText("完成", substring = false).performClick()
        assertEquals(model.draft, app.getSharedPreferences("chat_drafts", 0).getString(draftKey("u1", "", "text"), ""))
        assertTrue(requests.none { it.method != "GET" })
    }
    @Test fun smsModeKeepsWrongCodeRecoverableAndOnlySignsInAfterVerification() {
        model.logout(); idleModel(); assertNull(model.account)
        compose.setContent { MeimeiTheme(preferences) { PlatformApp(model, preferences) } }
        compose.onNodeWithText("短信登录", substring = false).performClick()
        await { model.sms.config != null }
        compose.onNodeWithTag("sms-phone").performTextInput("13800138000")
        assertTrue(requests.none { it.requestUrl!!.encodedPath == "/api/sms-login/send" })
        compose.onNodeWithTag("sms-send").performClick(); await { model.sms.challenge.isNotBlank() && !model.sms.sending }
        compose.onNodeWithTag("sms-send").assertIsNotEnabled(); capture("native-sms-login")
        compose.onNodeWithTag("sms-code").performTextInput("123456"); compose.onNodeWithTag("sms-login").performClick()
        await { !model.busy && model.error?.contains("验证码") == true }; assertNull(model.account); assertEquals("sms-fixture", model.sms.challenge)
        incorrectCode = false; compose.onNodeWithTag("sms-login").performClick()
        await { !model.busy && model.account != null }; assertEquals("u1", model.account?.id); assertEquals("", model.sms.phone)
        assertEquals(1, requests.count { it.requestUrl!!.encodedPath == "/api/sms-login/send" })
    }
    @Test fun ocrPreviewsBeforeAnyRecognitionAndImportsEditedTextOnlyAfterDraftChoice() {
        val source = ocrBitmapFixture(app)
        try {
            model.tools.mobile.select(ocrSelectionFixture(app, source))
            dispatcher.scheduler.runCurrent()
            runBlocking { withTimeout(10000) { while (model.tools.mobile.preparing) { dispatcher.scheduler.runCurrent(); delay(10) } } }
            assertNotNull("所选图片准备失败：${model.tools.mobile.ocrError}", model.tools.mobile.image)
            model.editDraft("原来的草稿")
            var used = false
            compose.setContent { MeimeiTheme(preferences) { OcrScreen(model) { used = true } } }
            // 图片和历史记录独立加载；记录可能在屏外，先确认数据，再滚动让对应列表项进入布局。
            await("ocr-history-data") { model.tools.mobile.records.any { it.id == "o1" } && !model.tools.mobile.historyLoading }
            await("ocr-preview-semantics") { compose.onAllNodesWithContentDescription("待识别图片").fetchSemanticsNodes().isNotEmpty() }
            capture("native-ocr-preview")
            assertTrue(requests.none { it.requestUrl!!.encodedPath == "/api/ocr/upload-policy" || it.method == "POST" })
            // 网络数据到达后仍需等待 LazyColumn 消费快照并完成布局；只重试滚动断言，不触发网络。
            var lastScrollAssertion = "尚未滚动"
            await("ocr-record-scroll-layout", detail = { "最后一次滚动断言：$lastScrollAssertion" }) {
                try {
                    compose.onNodeWithTag("ocr-list").performScrollToNode(hasTestTag("ocr-record-o1"))
                    compose.onNodeWithTag("ocr-record-o1").assertIsDisplayed()
                    true
                } catch (failure: AssertionError) { lastScrollAssertion = failure.stackTraceToString(); false }
            }
            compose.onNodeWithText("查看结果", substring = false).performClick()
            compose.onNodeWithTag("ocr-result-text").performTextReplacement("修正后的手写内容。")
            capture("native-ocr-result", true)
            compose.onNodeWithText("带入聊天", substring = false).performClick(); assertFalse(used); assertEquals("原来的草稿", model.draft)
            compose.onNodeWithText("追加到草稿", substring = false).performClick()
            assertTrue(used); assertEquals("原来的草稿\n\n修正后的手写内容。", model.draft)
            assertEquals("这是识别出的原始文字。", model.tools.mobile.records.single().text); assertTrue(requests.none { it.method == "POST" })
        } finally { source.delete() }
    }
    @Test fun personalUsageShowsDailyDetailsAndRecalculatesSelectedRangeWithoutAdminCalls() {
        compose.setContent { MeimeiTheme(preferences) { PersonalUsageScreen(model) {} } }
        await { compose.onAllNodesWithTag("personal-usage-total").fetchSemanticsNodes().isNotEmpty() && !model.tools.mobile.usageLoading }
        compose.onNodeWithTag("personal-usage-total").assertTextEquals("4,900 Token")
        capture("native-personal-usage")
        compose.onNodeWithTag("personal-usage-list").performScrollToNode(hasTestTag("usage-day-2026-10-25"))
        compose.onNodeWithTag("usage-day-2026-10-25").performClick(); compose.onNodeWithText("合计：1,000 Token").assertIsDisplayed(); capture("native-personal-usage-day", true)
        compose.onNodeWithText("关闭", substring = false).performClick()
        compose.onNodeWithTag("personal-usage-list").performScrollToNode(hasText("近30天")); compose.onNodeWithText("近30天").performClick()
        compose.onNodeWithTag("personal-usage-total").assertTextEquals("5,500 Token")
        assertTrue(requests.none { it.requestUrl!!.encodedPath.startsWith("/api/admin") || it.method != "GET" })
    }
}
