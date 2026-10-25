package asia.feng.aimeimei

import kotlinx.coroutines.*
import okhttp3.CookieJar
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class SmsLoginStateTest {
    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private lateinit var api: PlatformApi
    private lateinit var state: SmsLoginState
    private var time = 1000L
    @Before fun setup() {
        server = MockWebServer(); server.start(); api = PlatformApi(server.url("/"), CookieJar.NO_COOKIES)
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined); state = SmsLoginState(api, scope) { time }
    }
    @After fun close() { scope.cancel(); server.shutdown() }
    private suspend fun waitFor(condition: () -> Boolean) { withTimeout(5000) { while (!condition()) delay(10) } }
    private suspend fun enable() {
        server.enqueue(MockResponse().setBody("""{"sms_auth":{"enabled":true,"configured":true,"valid_seconds":300,"resend_seconds":60}}"""))
        state.load(); waitFor { !state.loading }; assertTrue(state.config!!.available)
    }
    @Test fun sendsOnlyAfterExplicitActionAndKeepsCooldownWhenPhoneChanges() = runBlocking {
        enable(); state.editPhone("+86 138-0013-8000"); assertEquals(1, server.requestCount)
        server.enqueue(MockResponse().setBody("""{"challenge_id":"test-challenge","resend_after":90}"""))
        state.send(); state.send(); waitFor { !state.sending }; assertEquals(2, server.requestCount)
        server.takeRequest(); val request = server.takeRequest(); assertEquals("POST", request.method)
        val body = JSONObject(request.body.readUtf8()); assertEquals("13800138000", body.getString("phone")); assertFalse(body.has("code"))
        assertEquals(90L, state.remaining); assertEquals("test-challenge", state.challenge)
        state.editPhone("13900139000"); assertEquals("", state.challenge); state.send(); assertEquals(2, server.requestCount)
        time += 90000; assertEquals(0L, state.remaining)
        state.verified(); assertEquals("", state.phone); assertEquals("", state.challenge)
    }
    @Test fun failedOrRateLimitedSendsDoNotRetryAutomatically() = runBlocking {
        enable(); state.editPhone("13800138000")
        server.enqueue(MockResponse().setResponseCode(429).setBody("{}")); state.send(); waitFor { !state.sending }
        assertTrue(state.error.contains("频繁")); assertTrue(state.remaining > 0); state.send(); assertEquals(2, server.requestCount)
    }
    @Test fun disabledSmsKeepsPasswordFallbackAndNeverSends() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"sms_auth":{"enabled":false,"configured":false}}""")); state.load(); waitFor { !state.loading }
        state.editPhone("13800138000"); state.send(); assertFalse(state.config!!.available); assertEquals(1, server.requestCount)
    }
    @Test fun verificationUsesChallengeAndExplainsWrongCodeWithoutSessionExpiry() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(401).setBody("""{"error":"验证码不正确或已过期"}"""))
        try { api.loginSms("13800138000", "123456", "test-challenge"); fail("Expected rejection") }
        catch (error: ApiFailure) { assertEquals(401, error.status); assertTrue(error.message!!.contains("验证码")); assertFalse(error.message!!.contains("登录已失效")) }
        val request = server.takeRequest(); assertEquals("/api/sms-login/verify", request.path)
        val body = JSONObject(request.body.readUtf8()); assertEquals("123456", body.getString("code")); assertEquals("test-challenge", body.getString("challenge_id"))
        server.enqueue(MockResponse().setBody("""{"user":{"id":"u1","username":"family","display_name":"家人","role":"family"}}"""))
        assertEquals("u1", api.loginSms("13800138000", "123456", "test-challenge").id)
    }
    @Test fun phoneNormalizationMatchesSupportedMainlandFormats() {
        assertEquals("13800138000", normalizedPhone("0086 13800138000")); assertEquals("13800138000", normalizedPhone("+86 138-0013-8000"))
        assertEquals("", normalizedPhone("123")); assertEquals("", normalizedPhone("+86008613800138000"))
    }
}
