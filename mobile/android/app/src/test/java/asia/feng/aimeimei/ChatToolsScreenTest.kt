package asia.feng.aimeimei

import android.app.Application
import android.graphics.Bitmap
import android.graphics.Canvas
import android.os.Looper
import androidx.activity.ComponentActivity
import androidx.compose.runtime.snapshots.Snapshot
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import kotlinx.coroutines.TimeoutCancellationException
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
    private var promptContent = "请帮我把这段文字润色得清楚自然。"
    private var promptDeleted = false
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
                    path == "/api/models" -> """{"models":[{"id":"m1","name":"测试模型","model":"test","supports_vision":true},{"id":"m2","name":"文字模型","model":"text","supports_vision":false}]}"""
                    path == "/api/conversations/c1/messages" -> """{"messages":[{"id":1,"role":"user","content":"请看这张图片和材料","images":[{"id":"img1","filename":"照片.jpg","mime_type":"image/jpeg","file_size":100}],"documents":[{"id":"doc1","filename":"材料.pdf","mime_type":"application/pdf","file_size":1024,"status":"completed","page_count":2}]},{"id":2,"role":"assistant","content":"这是用于原生界面验收的回答，可以引用、收藏、分享和朗读。","generation_status":"completed","usage":{"prompt_tokens":1200,"completion_tokens":89,"total_tokens":1289,"estimated_cost":0.001}}]}"""
                    path == "/api/conversations/c1/stats" -> """{"stats":{"total_tokens":1289,"message_count":2,"turn_count":1,"model_name":"测试模型","web_search_count":0,"attachment_count":1,"media_task_count":0}}"""
                    path == "/api/prompts" && request.method == "GET" -> if (promptDeleted) """{"prompts":[]}""" else JSONObject().put("prompts", org.json.JSONArray().put(JSONObject().put("id", "p1").put("title", "文字润色").put("content", promptContent))).toString()
                    path == "/api/prompts" && request.method == "POST" -> JSONObject().put("prompt", JSONObject(request.body.readUtf8()).put("id", "p2")).toString()
                    path == "/api/prompts/p1" && request.method == "PUT" -> { val row = JSONObject(request.body.readUtf8()).put("id", "p1"); promptContent = row.getString("content"); JSONObject().put("prompt", row).toString() }
                    path == "/api/prompts/p1" && request.method == "DELETE" -> { promptDeleted = true; "{}" }
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
        model = PlatformViewModel(app, PlatformApi(server.url("/"), CookieJar.NO_COOKIES), {}, {}, dispatcher = dispatcher)
        runBlocking { withTimeout(5000) { while (model.account == null || model.busy) { dispatcher.scheduler.runCurrent(); delay(10) } } }
        model.open(model.conversations.single())
        runBlocking { withTimeout(5000) { while (model.busy || model.messages.size != 2) { dispatcher.scheduler.runCurrent(); delay(10) } } }
        preferences = AppPreferences(app).apply { changeMotion(false) }
    }
    @After fun close() { model.tools.bind("", ""); server.shutdown() }
    private fun show(dark: Boolean = false) {
        if (dark) preferences.changeTheme("dark")
        compose.setContent { MeimeiTheme(preferences) { PlatformApp(model, preferences) } }
        await("chat-initial-actions") {
            try {
                compose.onNodeWithTag("chat-messages").performScrollToNode(hasText("朗读", substring = false))
                compose.onNodeWithText("朗读", substring = false).assertIsDisplayed()
                true
            } catch (_: AssertionError) { false }
        }
    }
    private fun await(stage: String = "native-ui", condition: () -> Boolean) {
        // 让出测试事件循环并推进实际布局，避免空列表首帧或图片解码完成前就结束等待。
        try { runBlocking { withTimeout(15000) {
            while (true) {
                dispatcher.scheduler.runCurrent(); Shadows.shadowOf(Looper.getMainLooper()).idle(); Snapshot.sendApplyNotifications()
                compose.mainClock.advanceTimeByFrame()
                if (condition()) return@withTimeout
                delay(10)
            }
        } } } catch (failure: TimeoutCancellationException) {
            val state = "stage=$stage busy=${model.busy} selected=${model.selected?.id} focus=${model.focusMessageId} " +
                "messages=${model.messages.map { it.id }} preview=${model.tools.preview?.id} previewFile=${model.tools.previewFile?.isFile} " +
                "previewBytes=${model.tools.previewFile?.length()} previewBounds=${model.tools.previewFile?.let { runCatching { chatImageBoundsValid(it) }.getOrNull() }} " +
                "previewBusy=${model.tools.previewBusy} previewError=${model.tools.previewError} " +
                "favoritesLoading=${model.tools.favoritesLoading} favorites=${model.tools.favorites.map { it.optString("id") }} " +
                "requests=${requests.map { it.method + " " + it.requestUrl!!.encodedPath }}"
            val tree = runCatching {
                val roots = compose.onAllNodes(isRoot(), useUnmergedTree = true)
                roots.fetchSemanticsNodes().indices.joinToString("\n") { roots[it].printToString() }
            }.getOrElse { "无法读取语义树：${it.message}" }
            runCatching { capture("native-wait-timeout-$stage", dialog = model.tools.preview != null) }
            throw AssertionError("等待原生界面阶段超时：$state\n$tree", failure)
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
        assertEquals("点击历史图片后应打开同一张图片的原生预览", "img1", model.tools.preview?.id)
        await("image-preview-file") { model.tools.preview?.id == "img1" && model.tools.previewFile?.isFile == true && !model.tools.previewBusy }
        await("image-preview-decoded") { compose.onAllNodesWithContentDescription("照片.jpg").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithContentDescription("照片.jpg").assertIsDisplayed(); capture("native-image-preview", true)
        compose.onNodeWithText("关闭").performClick()
        compose.onNodeWithContentDescription("更多工具").performClick(); compose.onNodeWithText("我的收藏").performClick()
        await("favorites-loaded") { !model.tools.favoritesLoading && model.tools.favorites.any { it.optString("id") == "f1" } &&
            compose.onAllNodesWithTag("favorites-list").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("favorites-list").performScrollToNode(hasText("这是收藏的原生验收回答。"))
        compose.onNodeWithText("这是收藏的原生验收回答。").assertIsDisplayed(); capture("native-favorites")
        compose.onNodeWithText("查看原消息").performClick()
        await("favorite-original-loaded") { !model.busy && model.messages.any { it.id == "2" } &&
            compose.onAllNodesWithTag("chat-messages").fetchSemanticsNodes().isNotEmpty() }
        // 返回原消息的定位和懒列表布局独立进行；主动把验收操作滚入可见区域后再断言。
        compose.onNodeWithTag("chat-messages").performScrollToNode(hasText("朗读", substring = false))
        compose.onNodeWithText("朗读", substring = false).assertIsDisplayed()
        compose.onNodeWithTag("message-2").assertIsDisplayed()
        assertEquals("c1", model.selected?.id)
    }
    @Test fun historyShowsThumbnailAndModelPickerCanFilterImageCapableModels() {
        show()
        compose.onNodeWithTag("chat-messages").performScrollToNode(hasText("图片 · 照片.jpg"))
        await { compose.onAllNodesWithContentDescription("图片缩略图：照片.jpg").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("chat-messages").performScrollToNode(hasContentDescription("图片缩略图：照片.jpg"))
        compose.onNodeWithContentDescription("图片缩略图：照片.jpg").assertIsDisplayed()
        capture("native-history-image-thumbnail")
        compose.onNodeWithText("测试模型 · 图片").performClick()
        compose.onNodeWithText("支持图片").assertIsDisplayed(); compose.onNodeWithText("纯文本模型").assertIsDisplayed()
        compose.onNodeWithText("仅看支持图片").performClick()
        compose.onNodeWithText("文字模型").assertDoesNotExist()
        capture("native-image-model-filter", true)
    }
    @Test fun conversationAndAnswerTokenDetailsUseSavedUsage() {
        show()
        compose.onNodeWithContentDescription("会话统计").performClick()
        await { model.tools.conversationStats != null && !model.tools.statsLoading }
        compose.onNodeWithTag("conversation-token-total").assertTextEquals("1,289 Token").assertIsDisplayed(); compose.onNodeWithText("问答轮数").assertIsDisplayed()
        capture("native-conversation-tokens", true)
        compose.onNodeWithText("关闭").performClick()
        compose.onNodeWithTag("chat-messages").performScrollToNode(hasTestTag("usage-2"))
        compose.onNodeWithTag("usage-2").performClick()
        compose.onNodeWithText("输入：1,200 Token").assertIsDisplayed(); compose.onNodeWithText("输出：89 Token").assertIsDisplayed()
        capture("native-answer-tokens", true)
    }
    @Test fun promptLibraryAppendsOnlyAfterConfirmationAndNeverSendsTheMessage() {
        show()
        compose.runOnIdle { model.editDraft("我原来的草稿") }
        compose.onNodeWithText("提示词", substring = false).performClick()
        await { model.tools.prompts.size == 1 && !model.tools.promptsLoading }
        compose.onNodeWithText("文字润色").assertIsDisplayed(); capture("native-prompt-library")
        compose.onNodeWithText("带入当前聊天").performClick()
        compose.onNodeWithText("输入框里已有草稿").assertIsDisplayed()
        assertEquals("我原来的草稿", model.draft)
        compose.onNodeWithText("追加到草稿").performClick()
        assertEquals("我原来的草稿\n\n请帮我把这段文字润色得清楚自然。", model.draft)
        assertTrue(requests.none { it.method == "POST" && it.requestUrl!!.encodedPath.endsWith("/messages") })
    }
    @Test fun sharedPromptEditsAndDeletionRequireExplicitSaveAndConfirmation() {
        show(); compose.onNodeWithText("提示词", substring = false).performClick()
        await { model.tools.prompts.size == 1 && !model.tools.promptsLoading }
        compose.onNodeWithText("文字润色").performClick(); compose.onNodeWithText("编辑").performClick()
        await { compose.onAllNodesWithTag("prompt-content").fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("prompt-content").performTextReplacement("请先检查逻辑，再润色文字。")
        assertTrue(requests.none { it.method == "PUT" })
        capture("native-prompt-editor", true)
        compose.onNodeWithText("保存").performClick()
        await { !model.tools.promptSaving && model.tools.prompts.single().optString("content") == "请先检查逻辑，再润色文字。" }
        compose.onNodeWithText("文字润色").performClick(); compose.onNodeWithText("删除").performClick()
        compose.onNodeWithText("删除这条共享提示词？").assertIsDisplayed()
        assertFalse(promptDeleted)
        compose.onAllNodesWithText("删除", substring = false).onLast().performClick()
        await { model.tools.prompts.isEmpty() && !model.tools.promptSaving }
        assertTrue(promptDeleted)
    }

}
