package asia.feng.aimeimei

import kotlinx.coroutines.runBlocking
import okhttp3.CookieJar
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

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
}
