package asia.feng.aimeimei

import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.CookieJar
import okhttp3.HttpUrl.Companion.toHttpUrl
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.io.File

class ChatToolsApiTest {
    private lateinit var server: MockWebServer
    private lateinit var api: PlatformApi
    @Before fun setup() { server = MockWebServer(); server.start(); api = PlatformApi(server.url("/"), CookieJar.NO_COOKIES) }
    @After fun close() { server.shutdown() }
    @Test fun historyKeepsAttachmentIdentifiersAndFavoriteState() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"messages":[{"id":8,"role":"assistant","content":"回答","favorite_id":"f1","images":[{"id":"img1","filename":"照片.jpg","mime_type":"image/jpeg","file_size":20}],"documents":[{"id":"doc1","filename":"材料.pdf","status":"completed","page_count":3}]}]}"""))
        val message = api.messages("c1").single()
        assertEquals("f1", message.favoriteId); assertEquals(listOf("img1", "doc1"), message.media.map { it.id })
        assertTrue(message.media.all { it.ready }); assertEquals(3, message.media.last().pages)
    }
    @Test fun historyPreservesExactTokenAndCostDetailsWithoutInventingMissingUsage() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"messages":[{"id":1,"role":"assistant","usage":{"prompt_tokens":1234,"completion_tokens":56,"total_tokens":1290,"cached_tokens":200,"cache_creation_tokens":100,"estimated_cost":0.0012}},{"id":2,"role":"assistant"}]}"""))
        val messages = api.messages("c1")
        assertEquals(1290L, messages[0].usage!!.total); assertEquals(1234L, messages[0].usage!!.input)
        assertEquals(56L, messages[0].usage!!.output); assertEquals(200L, messages[0].usage!!.cached)
        assertEquals(100L, messages[0].usage!!.cacheCreated); assertEquals(0.0012, messages[0].usage!!.cost, .000001)
        assertNull(messages[1].usage)
        assertEquals(30L, ChatUsage.fromJson(JSONObject("""{"prompt_tokens":10,"completion_tokens":20}""")).total)
    }
    @Test fun sendsAttachmentIdsWithTheExactQuotedTextAndNoSecondPost() = runBlocking {
        server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream").setBody("data: {\"type\":\"message_saved\",\"message_id\":9,\"generation_status\":\"completed\"}\n\n"))
        val content = quoteMessage("解释一下", listOf(ChatQuote("3", "assistant", "原文\n第二行")))
        withTimeout(5000) { api.stream("c1", content, false, listOf("img1"), listOf("doc1")).toList() }
        val request = server.takeRequest(); val body = JSONObject(request.body.readUtf8())
        assertEquals("/api/conversations/c1/messages", request.path); assertEquals(content, body.getString("content"))
        assertEquals("img1", body.getJSONArray("image_ids").getString(0)); assertEquals("doc1", body.getJSONArray("document_ids").getString(0))
        assertEquals(1, server.requestCount)
    }
    @Test fun favoritesUseOwnerCheckedMessageRoutesAndNumericIds() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"favorite":{"id":"fav1"}}""")); assertEquals("fav1", api.favorite("12", true))
        val post = server.takeRequest(); assertEquals("POST", post.method); assertEquals(12, JSONObject(post.body.readUtf8()).getInt("message_id"))
        server.enqueue(MockResponse().setBody("{}")); assertEquals("", api.favorite("12", false))
        val delete = server.takeRequest(); assertEquals("DELETE", delete.method); assertEquals("/api/favorites/message/12", delete.path)
        try { api.favorite("local-preview", true); fail("Expected local id rejection") } catch (_: IllegalArgumentException) {}
        assertEquals(2, server.requestCount)
    }
    @Test fun shareRequiresValidScopeAndDoesNotExposeAnExternalUrl() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"share":{"id":"s1","url":"/ai/share/test-token"}}"""))
        val share = api.share("c1", "12", "turn", 21600)
        assertEquals("s1", share.id); assertEquals(server.url("/ai/share/test-token").toString(), share.url)
        val request = server.takeRequest(); val body = JSONObject(request.body.readUtf8())
        assertEquals("turn", body.getString("scope")); assertEquals(21600, body.getInt("expires_in"))
        server.enqueue(MockResponse().setBody("""{"share":{"id":"s2","url":"https://other.example/secret"}}"""))
        try { api.share("c1", "12", "assistant", 86400); fail("Expected untrusted share rejection") } catch (_: IllegalArgumentException) {}
        try { api.share("c1", "12", "pair", 86400); fail("Expected invalid scope rejection") } catch (_: IllegalArgumentException) {}
        assertEquals(2, server.requestCount)
    }
    @Test fun uploadRejectsPlainHttpPolicyBeforeSendingAnyFile() = runBlocking {
        val file = File.createTempFile("chat-upload-test", ".pdf").apply { writeText("test-only-document") }
        try {
            server.enqueue(MockResponse().setBody(JSONObject().put("policy", JSONObject().put("host", "http://storage.example/")
                .put("max_size", 1000).put("allowed_extensions", org.json.JSONArray(listOf(".pdf")))).toString()))
            try { api.uploadChatFile(file, "材料.pdf", "application/pdf", false) {}; fail("Expected HTTPS policy rejection") } catch (_: IllegalArgumentException) {}
            val request = server.takeRequest(); assertEquals("/api/documents/upload-policy", request.path); assertEquals("POST", request.method)
            assertEquals(1, server.requestCount)
        } finally { file.delete() }
    }
    @Test fun oversizedOrUnsupportedFilesNeverReachObjectStorage() = runBlocking {
        val file = File.createTempFile("chat-upload-test", ".pdf").apply { writeText("test-only-document") }
        try {
            for (policy in listOf("""{"max_size":1,"allowed_extensions":[".pdf"]}""", """{"max_size":1000,"allowed_extensions":[".docx"]}""")) {
                server.enqueue(MockResponse().setBody(JSONObject().put("policy", JSONObject(policy)).toString()))
                try { api.uploadChatFile(file, "材料.pdf", "application/pdf", false) {}; fail("Expected file rejection") } catch (_: IllegalArgumentException) {}
            }
            assertEquals(2, server.requestCount)
        } finally { file.delete() }
    }
    @Test fun signedHttpsRedirectPreservesQueryAndNeverForwardsTheLoginCookie() = runBlocking {
        val certificate = okhttp3.tls.HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
        val serverTls = okhttp3.tls.HandshakeCertificates.Builder().heldCertificate(certificate).build()
        val clientTls = okhttp3.tls.HandshakeCertificates.Builder().addTrustedCertificate(certificate.certificate).build()
        val storage = MockWebServer().apply { useHttps(serverTls.sslSocketFactory(), false); start() }
        val destination = File.createTempFile("signed-image-test", ".jpg").apply { delete() }
        try {
            val cookies = object : CookieJar {
                override fun saveFromResponse(url: okhttp3.HttpUrl, cookies: List<okhttp3.Cookie>) {}
                override fun loadForRequest(url: okhttp3.HttpUrl) = listOf(okhttp3.Cookie.Builder().name("ap_session").value("test-only-session").domain(url.host).build())
            }
            val authenticated = PlatformApi(server.url("/"), cookies)
            val signedUrl = storage.url("/image.jpg").newBuilder().addQueryParameter("OSSAccessKeyId", "test-access").addQueryParameter("Signature", "test+/signature=").addQueryParameter("Expires", "123456").build()
            server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", signedUrl.toString()))
            storage.enqueue(MockResponse().setHeader("Content-Type", "image/jpeg").setBody("image-bytes"))
            val objectDownload = okhttp3.OkHttpClient.Builder().cookieJar(CookieJar.NO_COOKIES).followRedirects(false).sslSocketFactory(clientTls.sslSocketFactory(), clientTls.trustManager).build()
            authenticated.downloadPrivate(listOf("api", "chat-images", "img1", "view"), destination, objectDownloadClient = objectDownload)
            assertEquals("image-bytes", destination.readText())
            assertTrue(server.takeRequest().getHeader("Cookie")!!.contains("ap_session=test-only-session"))
            val request = storage.takeRequest(); assertNull(request.getHeader("Cookie")); assertNull(request.getHeader("Authorization"))
            assertEquals("test+/signature=", request.requestUrl!!.queryParameter("Signature"))
            assertEquals("123456", request.requestUrl!!.queryParameter("Expires"))
            assertFalse(File(destination.path + ".part").exists())
        } finally { storage.shutdown(); destination.delete() }
    }
    @Test fun privateDownloadRejectsHttpRedirectAndRemovesPartialFile() = runBlocking {
        val destination = File.createTempFile("chat-preview-test", ".jpg").apply { delete() }
        server.enqueue(MockResponse().setResponseCode(302).setHeader("Location", "http://storage.example/private.jpg"))
        try {
            try { api.downloadPrivate(listOf("api", "chat-images", "img1", "view"), destination); fail("Expected downgrade rejection") } catch (_: IllegalArgumentException) {}
            assertFalse(destination.exists()); assertFalse(File(destination.path + ".part").exists())
            assertEquals("/api/chat-images/img1/view", server.takeRequest().path); assertEquals(1, server.requestCount)
        } finally { destination.delete() }
    }
    @Test fun privateDownloadEnforcesDeclaredSizeAndDoesNotLeaveAUsableFile() = runBlocking {
        val destination = File.createTempFile("chat-preview-test", ".jpg").apply { delete() }
        server.enqueue(MockResponse().setBody("oversized"))
        try {
            try { api.downloadPrivate(listOf("api", "chat-images", "img1", "view"), destination, limit = 2); fail("Expected size rejection") } catch (_: IllegalArgumentException) {}
            assertFalse(destination.exists()); assertFalse(File(destination.path + ".part").exists())
        } finally { destination.delete() }
        assertTrue(safeObjectUrl("https://storage.example/path".toHttpUrl()))
        assertFalse(safeObjectUrl("https://user:pass@storage.example/path".toHttpUrl()))
    }
    @Test fun multipartUploadMatchesExistingOssPolicyAndKeepsOriginalFileBytes() {
        val file = File.createTempFile("chat-upload-contract", ".pdf").apply { writeText("document-bytes-\u4e2d\u6587") }
        try {
            val policy = JSONObject("""{"host":"https://storage.example/","max_size":1000,"allowed_extensions":[".pdf"],"key_prefix":"documents/u1/","access_key_id":"test-access-id","policy":"test-policy","signature":"test-signature"}""")
            val progress = mutableListOf<Int>()
            val plan = chatUploadRequest(policy, file, "材料.pdf", "application/pdf", false) { progress.add(it) }
            val buffer = okio.Buffer(); plan.request.body!!.writeTo(buffer)
            val body = buffer.readUtf8()
            assertEquals("POST", plan.request.method); assertEquals("https://storage.example/", plan.request.url.toString())
            assertTrue(plan.key.startsWith("documents/u1/")); assertTrue(plan.key.endsWith(".pdf"))
            for (field in listOf("key", "OSSAccessKeyId", "policy", "Signature", "success_action_status", "Content-Type", "file")) assertTrue(field, body.contains("name=\"$field\""))
            assertTrue(body.contains("document-bytes-中文")); assertTrue(body.contains("application/pdf"))
            assertEquals(98, progress.last()); assertNull(plan.request.header("Cookie")); assertNull(plan.request.header("Authorization"))
        } finally { file.delete() }
    }
}
