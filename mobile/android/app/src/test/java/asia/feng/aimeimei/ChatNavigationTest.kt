package asia.feng.aimeimei

import android.app.Application
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withTimeout
import okhttp3.CookieJar
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
@OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
class ChatNavigationTest {
    private lateinit var server: MockWebServer
    private lateinit var app: Application
    private lateinit var model: PlatformViewModel
    private var starts = 0
    @Before fun setup() {
        Dispatchers.setMain(Dispatchers.Unconfined)
        app = RuntimeEnvironment.getApplication()
        app.getSharedPreferences("chat_drafts", 0).edit().clear().commit()
        app.getSharedPreferences("native_session", 0).edit().clear().commit()
        server = MockWebServer(); server.start()
    }
    @After fun close() { server.shutdown(); Dispatchers.resetMain() }
    private fun bootstrap(history: String = "[]") {
        server.enqueue(MockResponse().setBody("""{"authenticated":true,"user":{"id":"u1","username":"family","display_name":"家人","role":"family"}}"""))
        server.enqueue(MockResponse().setBody("""{"conversations":$history}"""))
        server.enqueue(MockResponse().setBody("""{"models":[{"id":"m1","name":"模型","model":"test"}]}"""))
        model = PlatformViewModel(app, PlatformApi(server.url("/"), CookieJar.NO_COOKIES), { starts++ }, {})
    }
    private suspend fun idle() { withTimeout(5000) { while (model.busy || model.streaming) delay(10) } }
    @Test fun coldStartAndRepeatedNewChatKeepHistoryAndWelcomeDraft() = runBlocking {
        app.getSharedPreferences("chat_drafts", 0).edit()
            .putString(draftKey("u1", "", "last"), "old")
            .putString(draftKey("u1", "", "text"), "欢迎页草稿").commit()
        bootstrap("""[{"id":"old","title":"旧会话","model_id":"m1"}]"""); idle()
        assertNull(model.selected); assertEquals("欢迎页草稿", model.draft)
        repeat(5) { model.newConversation() }
        assertEquals(3, server.requestCount); assertEquals(1, model.conversations.size); assertNull(model.selected)
        assertEquals("欢迎页草稿", model.draft); assertEquals(0, starts)
    }
    @Test fun firstSendCreatesOnceAndKeepsSearchAndModelBeforeSending() = runBlocking {
        bootstrap(); idle()
        model.editDraft("你好"); model.toggleWebSearch(true)
        server.enqueue(MockResponse().setBody("""{"conversation":{"id":"c1","title":"新对话","model_id":"m1","reasoning_mode":"balanced"}}"""))
        server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream").setBody("data: {\"choices\":[{\"delta\":{\"content\":\"回答\"}}]}\n\ndata: {\"type\":\"message_saved\",\"message_id\":2,\"generation_status\":\"completed\"}\n\n"))
        server.enqueue(MockResponse().setBody("""{"messages":[{"id":1,"role":"user","content":"你好"},{"id":2,"role":"assistant","content":"回答","generation_status":"completed"}]}"""))
        model.send(); idle()
        val requests = (0 until server.requestCount).map { server.takeRequest() }
        assertEquals(1, requests.count { it.method == "POST" && it.path == "/api/conversations" })
        val send = requests.single { it.method == "POST" && it.path == "/api/conversations/c1/messages" }
        val body = org.json.JSONObject(send.body.readUtf8())
        assertEquals("你好", body.getString("content")); assertTrue(body.getBoolean("web_search")); assertEquals(1, starts)
        assertNull(model.pending); assertEquals("c1", model.selected?.id)
    }
    @Test fun failedConversationCreationPreservesDraftAndDoesNotStartGeneration() = runBlocking {
        bootstrap(); idle(); model.editDraft("保留这句话")
        server.enqueue(MockResponse().setResponseCode(503).setBody("{}"))
        model.send(); idle()
        assertEquals("保留这句话", model.draft); assertNull(model.selected); assertEquals(0, starts)
    }
}
