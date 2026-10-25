package asia.feng.aimeimei

import android.app.Application
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
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class SharedDraftIntegrationTest {
    private lateinit var app: Application
    private lateinit var server: MockWebServer
    private lateinit var model: PlatformViewModel
    private var blockPolicy = false
    private val requests = CopyOnWriteArrayList<RecordedRequest>()
    @Before fun setup() {
        app = RuntimeEnvironment.getApplication()
        app.getSharedPreferences("chat_drafts", 0).edit().clear().commit()
        File(app.cacheDir, "chat-attachments").deleteRecursively()
        server = MockWebServer().apply { dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                requests.add(request)
                return when (request.requestUrl!!.encodedPath) {
                    "/api/me" -> MockResponse().setBody("""{"authenticated":true,"user":{"id":"u1","username":"family"}}""")
                    "/api/models" -> MockResponse().setBody("""{"models":[{"id":"m1","name":"图片模型","supports_vision":true}]}""")
                    "/api/conversations" -> MockResponse().setBody("""{"conversations":[]}""")
                    "/api/chat-images/upload-policy" -> if (blockPolicy) MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE) else MockResponse().setResponseCode(503).setBody("{}")
                    else -> MockResponse().setBody("{}")
                }
            }
        }; start() }
        model = PlatformViewModel(app, PlatformApi(server.url("/"), CookieJar.NO_COOKIES), {}, {}, dispatcher = Dispatchers.Unconfined)
        runBlocking { withTimeout(5000) { while (model.busy || model.account == null) delay(10) } }
    }
    @After fun close() { model.tools.bind("", ""); model.incomingShares.discard(); server.shutdown() }
    private fun payload(owner: String = "u1", count: Int = 1): IncomingSharePayload {
        val images = (0 until count).map { index -> IncomingShareImage(File.createTempFile("shared-fixture-$index-", ".png", app.cacheDir).apply { writeText("private-test-image") }, "图片$index.png", "image/png") }
        return IncomingSharePayload("fixture", "分享的文字", images, owner, System.currentTimeMillis())
    }
    @Test fun importingAppendsWithoutNetworkAndLocalImagesSurviveConversationSwitch() = runBlocking {
        val value = payload()
        try {
            model.editDraft("已有草稿")
            assertTrue(model.importShared(value))
            assertEquals("已有草稿\n\n分享的文字", model.draft)
            assertTrue(model.tools.canSend); assertFalse(model.tools.ready)
            val item = model.tools.attachments.single()
            assertEquals("local", item.status)
            val cached = model.tools.localFile(item)!!
            assertNotEquals(value.images.single().file, cached)
            assertTrue(requests.none { it.method != "GET" })
            cached.setLastModified(System.currentTimeMillis() - 25L * 60 * 60 * 1000)
            model.tools.bind("u1", "other"); assertTrue(model.tools.attachments.isEmpty())
            model.tools.bind("u1", ""); assertEquals(item.clientKey, model.tools.attachments.single().clientKey)
            assertEquals(cached, model.tools.localFile(model.tools.attachments.single()))
            model.tools.bind("u2", ""); assertTrue(model.tools.attachments.isEmpty())
        } finally { value.images.forEach { it.file.delete() } }
    }
    @Test fun failedUploadDoesNotCreateConversationOrSendModelRequestAndDoesNotAutoRetry() = runBlocking {
        val value = payload()
        try {
            assertTrue(model.importShared(value)); model.send()
            withTimeout(5000) { while (model.busy || requests.none { it.requestUrl!!.encodedPath.endsWith("upload-policy") }) delay(10) }
            assertEquals("分享的文字", model.draft); assertNull(model.pending); assertFalse(model.streaming)
            assertEquals("failed", model.tools.attachments.single().status)
            assertNotNull(model.tools.localFile(model.tools.attachments.single()))
            model.send(); delay(100)
            assertEquals(1, requests.count { it.method == "POST" })
            assertTrue(requests.none { it.requestUrl!!.encodedPath.endsWith("/messages") })
            val cached = model.tools.localFile(model.tools.attachments.single())!!
            model.tools.bind("u1", "other"); model.tools.bind("u1", "")
            assertTrue(cached.isFile); assertEquals("local", model.tools.attachments.single().status)
        } finally { value.images.forEach { it.file.delete() } }
    }
    @Test fun removingRestoredLocalDraftDeletesItsFallbackFile() = runBlocking {
        val value = payload()
        try {
            assertTrue(model.importShared(value))
            val file = model.tools.localFile(model.tools.attachments.single())!!
            model.tools.bind("u2", ""); model.tools.bind("u1", "")
            model.tools.removeAttachment(model.tools.attachments.single())
            assertFalse(file.exists()); assertTrue(model.tools.attachments.isEmpty())
        } finally { value.images.forEach { it.file.delete() } }
    }
    @Test fun cancellingStagedUploadCannotFallThroughToSendingText() = runBlocking {
        blockPolicy = true
        val value = payload(count = 2)
        try {
            assertTrue(model.importShared(value)); model.send()
            withTimeout(5000) { while (!model.busy || requests.none { it.requestUrl!!.encodedPath.endsWith("upload-policy") }) delay(10) }
            model.tools.cancelUploads()
            withTimeout(5000) { while (model.busy) delay(10) }
            assertEquals("分享的文字", model.draft); assertNull(model.pending); assertFalse(model.streaming)
            assertTrue(model.tools.attachments.isEmpty())
            assertEquals(1, requests.count { it.method == "POST" })
        } finally { value.images.forEach { it.file.delete() } }
    }
    @Test fun removingStagedImageStopsPreflightAndPreservesOtherLocalImage() = runBlocking {
        blockPolicy = true
        val value = payload(count = 2)
        try {
            assertTrue(model.importShared(value)); model.send()
            withTimeout(5000) { while (requests.none { it.requestUrl!!.encodedPath.endsWith("upload-policy") }) delay(10) }
            model.tools.removeAttachment(model.tools.attachments.first())
            withTimeout(5000) { while (model.busy) delay(10) }
            assertEquals(1, model.tools.attachments.size); assertEquals("local", model.tools.attachments.single().status)
            assertFalse(model.streaming); assertNull(model.pending); assertEquals("分享的文字", model.draft)
            assertEquals(1, requests.count { it.method == "POST" })
        } finally { value.images.forEach { it.file.delete() } }
    }
    @Test fun accountMismatchAndImageLimitPreserveExistingDraft() = runBlocking {
        model.editDraft("原草稿")
        val foreign = payload("other")
        val tooMany = payload(count = 6)
        try {
            assertFalse(model.importShared(foreign)); assertFalse(model.importShared(tooMany))
            assertEquals("原草稿", model.draft); assertTrue(model.tools.attachments.isEmpty())
            assertTrue(requests.none { it.method != "GET" })
        } finally { (foreign.images + tooMany.images).forEach { it.file.delete() } }
    }
}
