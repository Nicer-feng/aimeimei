package asia.feng.aimeimei

import kotlinx.coroutines.runBlocking
import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.io.File

class OcrApiTest {
    private lateinit var server: MockWebServer
    private lateinit var objects: MockWebServer
    private lateinit var upload: OkHttpClient
    private lateinit var api: PlatformApi
    private lateinit var file: File
    @Before fun setup() {
        val certificate = HeldCertificate.Builder().commonName("localhost").addSubjectAlternativeName("localhost").build()
        val tls = HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val trusted = HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        objects = MockWebServer().apply { useHttps(tls.sslSocketFactory(), false); start() }
        server = MockWebServer(); server.start()
        api = PlatformApi(server.url("/"), object : CookieJar {
            override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {}
            override fun loadForRequest(url: HttpUrl) = listOf(Cookie.Builder().name("ap_session").value("test-only").domain("localhost").build())
        })
        upload = OkHttpClient.Builder().sslSocketFactory(trusted.sslSocketFactory(), trusted.trustManager).cookieJar(CookieJar.NO_COOKIES).build()
        file = File.createTempFile("ocr-api-", ".png").apply { writeBytes(byteArrayOf(1, 2, 3)) }
    }
    @After fun close() { server.shutdown(); objects.shutdown(); file.delete() }
    private fun policy() = JSONObject().put("policy", JSONObject().put("host", objects.url("/").toString()).put("access_key_id", "test-only").put("policy", "test-policy")
        .put("signature", "test-only").put("key_prefix", "test/owner/").put("max_size", 10485760).put("allowed_extensions", org.json.JSONArray(listOf(".png"))))
    @Test fun realHttpsUploadNeverReceivesSessionCookieAndRecognitionPostsExactlyOnce() = runBlocking {
        server.enqueue(MockResponse().setBody(policy().toString())); objects.enqueue(MockResponse().setResponseCode(204))
        server.enqueue(MockResponse().setBody("""{"task":{"id":"o1","filename":"手写.png","status":"completed","recognized_text":"原始识别文字"}}"""))
        val progress = mutableListOf<Int>(); val result = api.recognizeOcr(OcrImage(file, "手写.png", "image/png"), { progress.add(it) }, upload)
        assertEquals("原始识别文字", result.text); assertTrue(progress.contains(99)); assertEquals(2, server.requestCount); assertEquals(1, objects.requestCount)
        val policyRequest = server.takeRequest(); assertEquals("/api/ocr/upload-policy", policyRequest.path); assertNotNull(policyRequest.getHeader("Cookie"))
        val objectRequest = objects.takeRequest(); assertNull(objectRequest.getHeader("Cookie")); assertNull(objectRequest.getHeader("Authorization")); assertEquals("POST", objectRequest.method)
        val recordRequest = server.takeRequest(); assertEquals("/api/ocr/tasks", recordRequest.path); assertNotNull(recordRequest.getHeader("Cookie"))
        val body = JSONObject(recordRequest.body.readUtf8()); assertEquals("手写.png", body.getString("filename")); assertEquals(3L, body.getLong("file_size")); assertTrue(body.getString("oss_key").startsWith("test/owner/"))
    }
    @Test fun failedUploadCannotCreateOrRetryRecognitionTask() = runBlocking {
        server.enqueue(MockResponse().setBody(policy().toString())); objects.enqueue(MockResponse().setResponseCode(503))
        try { api.recognizeOcr(OcrImage(file, "手写.png", "image/png"), {}, upload); fail("Expected upload failure") } catch (_: IllegalArgumentException) {}
        assertEquals(1, server.requestCount); assertEquals(1, objects.requestCount)
    }
    @Test fun serverKeepsFailedRecognitionAsVisibleHistoryRatherThanSuccessfulText() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"tasks":[{"id":"o1","filename":"手写.png","status":"failed","recognized_text":"","error_message":"识别失败"}]}"""))
        val row = api.ocrRecords().single(); assertEquals("failed", row.status); assertEquals("", row.text)
        assertEquals("GET", server.takeRequest().method)
    }
}
