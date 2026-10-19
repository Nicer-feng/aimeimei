package asia.feng.aimeimei

import kotlinx.coroutines.runBlocking
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class AdminApiTest {
    private lateinit var server: MockWebServer
    private lateinit var api: PlatformApi
    @Before fun setup() {
        server = MockWebServer(); server.start()
        api = PlatformApi(server.url("/"), object : CookieJar {
            override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {}
            override fun loadForRequest(url: HttpUrl): List<Cookie> = listOf(Cookie.Builder().name("session").value("test-only-session").domain(url.host).httpOnly().build())
        })
    }
    @After fun close() { server.shutdown() }
    @Test fun nativeManagementUsesSessionCookiesAndEncodedQueryParameters() = runBlocking {
        server.enqueue(MockResponse().setBody("{}"))
        api.adminRequest(listOf("token-stats"), query = mapOf("q" to "家人&role=admin", "view" to "users"))
        val request = server.takeRequest()
        assertEquals("GET", request.method); assertEquals("/api/admin/token-stats", request.requestUrl!!.encodedPath)
        assertEquals("家人&role=admin", request.requestUrl!!.queryParameter("q"))
        assertNull(request.getHeader("X-Admin-Key")); assertEquals("session=test-only-session", request.getHeader("Cookie"))
    }
    @Test fun crudAndSettingsUseExistingMethodsAndNeverSendCredentialsInUrls() = runBlocking {
        for ((path, method) in listOf(listOf("users") to "POST", listOf("users", "u1") to "PUT", listOf("models", "m1") to "DELETE", listOf("tts") to "POST", listOf("sms-auth") to "POST")) {
            server.enqueue(MockResponse().setBody("{}"))
            api.adminRequest(path, method, JSONObject().put("password", "test-only-pass"))
            val request = server.takeRequest()
            assertEquals(method, request.method); assertEquals("/api/admin/" + path.joinToString("/"), request.requestUrl!!.encodedPath)
            assertFalse(request.path!!.contains("test-only")); assertEquals("test-only-pass", JSONObject(request.body.readUtf8()).getString("password"))
        }
    }
    @Test fun usageAndVersionUseTheirOriginalRoutes() = runBlocking {
        for ((path, expected) in listOf(listOf("usage-time", "admin", "user") to "/api/usage-time/admin/user", listOf("version") to "/api/version")) {
            server.enqueue(MockResponse().setBody("{}")); api.adminRequest(path); assertEquals(expected, server.takeRequest().path)
        }
        try { api.adminRequest(listOf("https://outside.example")); fail("Expected path restriction") } catch (_: IllegalArgumentException) {}
    }
    @Test fun serverPermissionFailuresRemainFailures() = runBlocking {
        for (code in listOf(401, 403, 409)) {
            server.enqueue(MockResponse().setResponseCode(code).setBody("""{"error":"denied"}"""))
            try { api.adminRequest(listOf("users")); fail("Expected rejection") } catch (failure: ApiFailure) { assertEquals(code, failure.status) }
        }
    }
    @Test fun explicitBusinessErrorsAreTranslatedWithoutEchoingUnknownServerText() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(400).setBody("""{"error":"at least one active admin is required"}"""))
        try { api.adminRequest(listOf("users", "u1"), "PUT", JSONObject().put("is_active", false)); fail("Expected admin protection") }
        catch (error: ApiFailure) { assertEquals("至少需要保留一位启用的管理员", error.message) }
        assertFalse(adminFailureHint(400, "test-only-private-debug-text").contains("test-only"))
    }

}
