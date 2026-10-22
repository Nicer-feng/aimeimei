package asia.feng.aimeimei

import android.app.Application
import android.content.ContentProvider
import android.content.ContentValues
import android.content.pm.ProviderInfo
import android.database.MatrixCursor
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.CookieJar
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import okhttp3.mockwebserver.SocketPolicy
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class ChatToolsStateTest {
    private lateinit var app: Application
    private lateinit var server: MockWebServer
    private var model: PlatformViewModel? = null
    private var user = "u1"
    private var vision = true
    private var quoteEnabled = true
    private var created = false
    private var sent: JSONObject? = null
    private var blockUploadPolicy = false
    private val requests = CopyOnWriteArrayList<RecordedRequest>()
    @Before fun setup() {
        app = RuntimeEnvironment.getApplication()
        listOf("chat_drafts", "native_session").forEach { app.getSharedPreferences(it, 0).edit().clear().commit() }
        server = MockWebServer()
        server.dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                requests.add(request)
                val path = request.requestUrl!!.encodedPath
                if (path == "/api/documents/upload-policy" && blockUploadPolicy) return MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE)
                if (path == "/api/conversations/c1/messages" && request.method == "POST") {
                    sent = JSONObject(request.body.readUtf8())
                    return MockResponse().setHeader("Content-Type", "text/event-stream").setBody("data: {\"choices\":[{\"delta\":{\"content\":\"回答\"}}]}\n\ndata: {\"type\":\"message_saved\",\"message_id\":2,\"generation_status\":\"completed\"}\n\n")
                }
                val body = when {
                    path == "/api/me" -> """{"authenticated":true,"user":{"id":"$user","username":"family","display_name":"家人"}}"""
                    path == "/api/models" -> """{"models":[{"id":"m1","name":"模型","model":"test","supports_vision":$vision}]}"""
                    path == "/api/conversations" && request.method == "POST" -> { created = true; """{"conversation":{"id":"c1","title":"新对话","model_id":"m1"}}""" }
                    path == "/api/conversations" -> if (created) """{"conversations":[{"id":"c1","title":"测试会话","model_id":"m1"}]}""" else """{"conversations":[]}"""
                    path == "/api/features" -> """{"features":{"selection_quote":$quoteEnabled}}"""
                    path == "/api/conversations/c1/messages" -> JSONObject().put("messages", JSONArray().put(JSONObject().put("id", 1).put("role", "user").put("content", sent?.optString("content")))
                        .put(JSONObject().put("id", 2).put("role", "assistant").put("content", "回答").put("generation_status", "completed"))).toString()
                    else -> "{}"
                }
                return MockResponse().setBody(body)
            }
        }
        server.start()
    }
    @After fun close() { model?.tools?.bind("", ""); server.shutdown() }
    private suspend fun start(): PlatformViewModel {
        val value = PlatformViewModel(app, PlatformApi(server.url("/"), CookieJar.NO_COOKIES), {}, {}, dispatcher = Dispatchers.Unconfined)
        model = value
        withTimeout(5000) { while (value.busy || value.account == null) delay(10) }
        return value
    }
    private fun draft(owner: String, items: List<ChatAttachment>) {
        app.getSharedPreferences("chat_drafts", 0).edit().putString(draftKey(owner, "", "attachments"), JSONArray(items.map { it.toJson() }).toString()).commit()
    }
    @Test fun composerDraftsAreScopedByAccountAndDoNotCreateConversations() = runBlocking {
        draft("u1", listOf(ChatAttachment("img1", "照片.jpg", "image/jpeg", 20, true)))
        draft("u2", listOf(ChatAttachment("doc2", "材料.pdf", "application/pdf", 30, false)))
        val value = start(); assertEquals("img1", value.tools.attachments.single().id)
        repeat(3) { value.newConversation() }
        assertNull(value.selected); assertEquals(3, server.requestCount)
        user = "u2"; value.restore()
        withTimeout(5000) { while (value.busy || value.account?.id != "u2") delay(10) }
        assertEquals("doc2", value.tools.attachments.single().id); assertTrue(value.tools.quotes.isEmpty())
        assertTrue(requests.none { it.method == "POST" })
    }
    @Test fun firstSendMovesWelcomeAttachmentsAndOnlyPostsOnce() = runBlocking {
        draft("u1", listOf(ChatAttachment("img1", "照片.jpg", "image/jpeg", 20, true), ChatAttachment("doc1", "材料.pdf", "application/pdf", 40, false)))
        val value = start(); value.editDraft("根据图片和材料分析")
        value.send()
        withTimeout(10000) { while (value.messages.none { it.id == "2" } || value.pending != null || value.busy || value.streaming || value.selected?.title != "测试会话") delay(10) }
        assertEquals("img1", sent!!.getJSONArray("image_ids").getString(0)); assertEquals("doc1", sent!!.getJSONArray("document_ids").getString(0))
        assertEquals(1, requests.count { it.method == "POST" && it.requestUrl!!.encodedPath.endsWith("/messages") })
        assertTrue(value.tools.attachments.isEmpty()); assertNull(value.pending)
        val prefs = app.getSharedPreferences("chat_drafts", 0)
        assertNull(prefs.getString(draftKey("u1", "", "attachments"), null))
        assertEquals("[]", prefs.getString(draftKey("u1", "c1", "attachments"), null))
    }
    @Test fun unparsedDocumentsAndUnsupportedImageModelsCannotSend() = runBlocking {
        draft("u1", listOf(ChatAttachment("doc1", "材料.pdf", "application/pdf", 40, false, "processing")))
        val value = start(); value.editDraft("分析"); value.send()
        assertFalse(value.tools.ready); assertNull(value.pending); assertEquals(3, server.requestCount)
        value.tools.restoreDraft(listOf(ChatAttachment("img1", "图片.jpg", "image/jpeg", 20, true)), emptyList())
        vision = false; value.restore()
        withTimeout(5000) { while (value.busy) delay(10) }
        value.send(); assertTrue(value.error.orEmpty().contains("不支持图片")); assertNull(sent)
    }
    @Test fun quotingRespectsTheServerSwitchAndNeverSendsAutomatically() = runBlocking {
        val value = start(); quoteEnabled = false
        value.tools.quote(ChatMessage("4", "assistant", "原文内容", "", "completed", emptyList()))
        withTimeout(5000) { while (value.tools.notice == null) delay(10) }
        assertTrue(value.tools.quotes.isEmpty()); assertTrue(value.tools.notice!!.contains("关闭"))
        assertTrue(requests.none { it.method == "POST" })
        quoteEnabled = true; value.tools.dismissNotice()
        value.tools.quote(ChatMessage("4", "assistant", "原文内容", "", "completed", emptyList()))
        withTimeout(5000) { while (value.tools.quotes.isEmpty()) delay(10) }
        assertEquals("原文内容", value.tools.quotes.single().text); assertNull(value.selected); assertNull(sent)
    }
    private fun fileSelection(file: File): Uri {
        val provider = object : ContentProvider() {
            override fun onCreate() = true
            override fun query(uri: Uri, projection: Array<out String>?, selection: String?, args: Array<out String>?, order: String?) =
                MatrixCursor(arrayOf(OpenableColumns.DISPLAY_NAME)).apply { addRow(arrayOf("材料.pdf")) }
            override fun getType(uri: Uri) = "application/pdf"
            override fun openFile(uri: Uri, mode: String) = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
            override fun insert(uri: Uri, values: ContentValues?): Uri? = null
            override fun delete(uri: Uri, selection: String?, args: Array<out String>?) = 0
            override fun update(uri: Uri, values: ContentValues?, selection: String?, args: Array<out String>?) = 0
        }
        provider.attachInfo(app, ProviderInfo().apply { authority = "native-test-files" })
        ShadowContentResolver.registerProviderInternal("native-test-files", provider)
        return Uri.parse("content://native-test-files/document")
    }
    @Test fun cancellingUploadStopsTheQueueAndRemovesTemporaryFiles() = runBlocking {
        val value = start(); blockUploadPolicy = true
        val file = File.createTempFile("native-test-document", ".pdf", app.cacheDir).apply { writeText("test-only-material") }
        try {
            val uri = fileSelection(file)
            value.tools.addFiles(listOf(uri, uri), false)
            withTimeout(5000) { while (requests.none { it.requestUrl!!.encodedPath.endsWith("upload-policy") }) delay(10) }
            value.tools.cancelUploads()
            withTimeout(5000) { while (File(app.cacheDir, "chat-attachments").walkTopDown().any { it.isFile && it.name.startsWith("selected-") }) delay(10) }
            assertFalse(value.tools.uploading); assertTrue(value.tools.attachments.isEmpty())
            assertEquals(1, requests.count { it.requestUrl!!.encodedPath.endsWith("upload-policy") })
            assertNull(sent)
        } finally { file.delete() }
    }
    @Test fun removingOneUploadKeepsTheNextSelectedFileInTheQueue() = runBlocking {
        val value = start(); blockUploadPolicy = true
        val file = File.createTempFile("native-test-document", ".pdf", app.cacheDir).apply { writeText("test-only-material") }
        try {
            val uri = fileSelection(file)
            value.tools.addFiles(listOf(uri, uri), false)
            withTimeout(5000) { while (requests.none { it.requestUrl!!.encodedPath.endsWith("upload-policy") }) delay(10) }
            val first = value.tools.attachments.single(); value.tools.removeAttachment(first)
            withTimeout(5000) { while (requests.count { it.requestUrl!!.encodedPath.endsWith("upload-policy") } < 2) delay(10) }
            assertTrue(value.tools.uploading); assertEquals(1, value.tools.attachments.size)
            assertNotEquals(first.clientKey, value.tools.attachments.single().clientKey)
            value.tools.cancelUploads(); assertFalse(value.tools.uploading)
        } finally { file.delete() }
    }
}
