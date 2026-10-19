package asia.feng.aimeimei

import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.withTimeout
import okhttp3.CookieJar
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

class PlatformApiTest {
    private lateinit var server: MockWebServer
    private lateinit var api: PlatformApi
    @Before fun setup() { server = MockWebServer();server.start();api = PlatformApi(server.url("/"), CookieJar.NO_COOKIES) }
    @After fun close() { server.shutdown() }
    @Test fun unauthenticatedSessionIsNotAnAccount() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"authenticated":false,"user":null}"""))
        assertNull(api.currentAccount());assertEquals("/api/me", server.takeRequest().path)
    }
    @Test fun loginPreservesPasswordAndUsesCaptcha() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"user":{"id":"u1","username":"family","display_name":"家人"}}"""))
        assertEquals("u1", api.login(" family ", "test-only-password", Captcha("c1", ""), " AB23 ").id)
        val request = server.takeRequest();val body = org.json.JSONObject(request.body.readUtf8())
        assertEquals("/api/login", request.path);assertEquals("POST", request.method)
        assertEquals("family", body.getString("username"));assertEquals("c1", body.getString("captcha_id"));assertEquals("AB23", body.getString("captcha"))
    }
    @Test fun expiredSessionHasAnExplicitError() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"error":"unauthorized"}"""))
        try { api.conversations();fail("Expected authentication failure") } catch (failure: ApiFailure) { assertEquals(401, failure.status) }
    }
    @Test fun historyKeepsFailedAnswerAndAttachments() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"messages":[{"id":123,"role":"assistant","content":"保留部分正文","generation_status":"interrupted","documents":[{"filename":"材料.pdf"}]}]}"""))
        val message = api.messages("conversation-1").single()
        assertEquals("123", message.id);assertEquals("保留部分正文", message.content);assertEquals("interrupted", message.status);assertEquals(listOf("材料.pdf"), message.attachments)
        assertEquals("/api/conversations/conversation-1/messages", server.takeRequest().path)
    }
    @Test fun createsAndConfiguresConversationUsingExistingRoutes() = runBlocking {
        val body = """{"conversation":{"id":"c1","title":"新对话","model_id":"m1","model_name":"模型","reasoning_mode":"deep"}}"""
        server.enqueue(MockResponse().setResponseCode(201).setBody(body))
        val created = api.createConversation("m1", "deep")
        assertEquals("m1", created.modelId); assertEquals("deep", created.reasoningMode)
        val post = server.takeRequest(); assertEquals("POST", post.method); assertEquals("/api/conversations", post.path)
        assertEquals("deep", org.json.JSONObject(post.body.readUtf8()).getString("reasoning_mode"))
        server.enqueue(MockResponse().setBody(body))
        api.configureConversation("c1", "m1", "fast")
        val patch = server.takeRequest(); assertEquals("PATCH", patch.method); assertEquals("/api/conversations/c1", patch.path)
        assertEquals("fast", org.json.JSONObject(patch.body.readUtf8()).getString("reasoning_mode"))
    }
    @Test fun readsFragmentedUnicodeSseAndSendsSearchFlag() = runBlocking {
        val payload = ": heartbeat\r\n\r\ndata: {\"choices\":[{\"delta\":{\"content\":\"你好😀\"}}]}\r\n\r\n" +
            "data: {\"type\":\"message_saved\",\"message_id\":33,\"generation_status\":\"completed\"}\n\n"
        server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream").setBody(payload).throttleBody(2, 1, TimeUnit.MILLISECONDS))
        val events = withTimeout(5000) { api.stream("c1", "问题", true).toList() }
        val buffer = ReplyBuffer(); events.forEach(buffer::accept)
        assertEquals("你好😀", buffer.snapshot(finish = true).content); assertEquals("33", buffer.savedId)
        val request = server.takeRequest(); assertEquals("POST", request.method); assertEquals("/api/conversations/c1/messages", request.path)
        val body = org.json.JSONObject(request.body.readUtf8())
        assertTrue(body.getBoolean("web_search")); assertTrue(body.getBoolean("use_profile")); assertEquals("问题", body.getString("content"))
    }
    @Test fun cleanEofWithoutSavedEventRemainsUnconfirmed() = runBlocking {
        server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream").setBody("data: {\"choices\":[{\"delta\":{\"content\":\"一部分\"}}]}\n\ndata: [DONE]\n\n"))
        val buffer = ReplyBuffer()
        withTimeout(5000) { api.stream("c1", "问题", false).collect { buffer.accept(it) } }
        assertNull(buffer.savedId); assertEquals("一部分", buffer.snapshot(finish = true).content)
    }
    @Test fun sseFailureIsNotConvertedToSuccessfulAnswer() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody("{}"))
        try { withTimeout(5000) { api.stream("c1", "问题", false).toList() }; fail("Expected failure") }
        catch (failure: ApiFailure) { assertEquals(401, failure.status) }
    }
}
