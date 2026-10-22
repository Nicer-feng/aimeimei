package asia.feng.aimeimei

import kotlinx.coroutines.runBlocking
import okhttp3.CookieJar
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test

class KnowledgeApiTest {
    private lateinit var server: MockWebServer
    private lateinit var api: PlatformApi
    @Before fun setup() { server = MockWebServer(); server.start(); api = PlatformApi(server.url("/"), CookieJar.NO_COOKIES) }
    @After fun close() { server.shutdown() }
    @Test fun searchEncodesKeywordsAndKeepsMessageLocationWithoutMediaConfusion() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"results":[{"id":"message:42","type":"message","session_id":"old","message_id":42,"title":"旧聊天","snippet":"预算 & 时间","role":"assistant"},{"id":"media:1","type":"media","session_id":"old"},{"id":"favorite:2","type":"favorite","session_id":"","message_id":0}]}"""))
        val rows = api.searchChats("预算 & 时间?#")
        assertEquals(listOf("message:42", "favorite:2"), rows.map { it.id }); assertEquals("42", rows.first().messageId)
        assertEquals("", rows.last().conversationId)
        val request = server.takeRequest(); assertEquals("GET", request.method); assertEquals("预算 & 时间?#", request.requestUrl!!.queryParameter("q"))
        assertEquals("/api/search", request.requestUrl!!.encodedPath)
    }
    @Test fun conversationDetailIsReadOnlyAndRetainsActualModelAndReasoning() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"conversation":{"id":"old","title":"旧聊天","model_id":"m2","model_name":"旧模型","reasoning_mode":"deep","pinned":true}}"""))
        val row = api.conversationDetail("old")
        assertEquals("m2", row.modelId); assertEquals("deep", row.reasoningMode); assertTrue(row.pinned)
        val request = server.takeRequest(); assertEquals("GET", request.method); assertEquals("/api/conversations/old", request.path); assertEquals(0L, request.bodySize)
    }
    @Test fun sourcesKeepSavedOrderAndRejectExecutableOrCredentialLinks() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"messages":[{"id":2,"role":"assistant","sources":[{"title":"后","url":"https://example.com/b?q=1#part","snippet":"摘要","position":2},{"title":"前","url":"http://example.com/a","position":1},{"url":"javascript:alert(1)","position":3}]}]}"""))
        val sources = api.messages("c1").single().sources
        assertEquals(listOf("前", "后", ""), sources.map { it.title }); assertEquals("摘要", sources[1].snippet)
        assertEquals("part", sources[1].safeUrl!!.fragment); assertNull(sources[2].safeUrl)
        assertNull(ChatSource("", "https://user:pass@example.com", "", 0).safeUrl)
        assertNull(ChatSource("", "file:///etc/passwd", "", 0).safeUrl)
    }
    @Test fun profileWritesUseTypedFieldsAndPreserveOrderAndOnlyExplicitDeletion() = runBlocking {
        val profile = """{"profile":{"id":"p1","title":"习惯","content":"简洁回答","type":"style","enabled":false,"sort_order":20,"token_estimate":8}}"""
        server.enqueue(MockResponse().setBody(profile))
        val row = api.saveProfile(null, "习惯", "简洁回答", "style", false, 20)
        assertFalse(row.enabled); val create = server.takeRequest(); assertEquals("POST", create.method)
        val body = JSONObject(create.body.readUtf8()); assertTrue(body.get("enabled") is Boolean); assertEquals(20, body.getInt("sort_order"))
        server.enqueue(MockResponse().setBody(profile)); api.saveProfile("p1", "习惯", "简洁回答", "style", false, 20)
        assertEquals("PUT", server.takeRequest().method)
        server.enqueue(MockResponse().setBody("""{"profiles":[]}""")); api.reorderProfiles(listOf("p2", "p1"))
        val reorder = server.takeRequest(); assertEquals("/api/profiles/reorder", reorder.path); assertEquals("p2", JSONObject(reorder.body.readUtf8()).getJSONArray("ids").getString(0))
        server.enqueue(MockResponse().setBody("{}")); api.deleteProfile("p1")
        val delete = server.takeRequest(); assertEquals("DELETE", delete.method); assertEquals("/api/profiles/p1", delete.path)
    }
    @Test fun invalidProfilesNeverMakeNetworkRequests() = runBlocking {
        for ((title, content, kind) in listOf(Triple("", "内容", "style"), Triple("标题", "", "style"), Triple("标题", "内容", "other"), Triple("标题", "字".repeat(12001), "style"))) {
            try { api.saveProfile(null, title, content, kind, true, 0); fail("Expected validation") } catch (_: IllegalArgumentException) {}
        }
        assertEquals(0, server.requestCount)
    }
}
