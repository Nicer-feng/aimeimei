package asia.feng.aimeimei

import kotlinx.coroutines.*
import okhttp3.CookieJar
import okhttp3.mockwebserver.Dispatcher
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.RecordedRequest
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.TimeUnit

internal val sideFixture = """{"id":"s1","session_id":"c1","source_message_id":12,"selected_text":"这是一段值得深入讨论的回答。","title":"深入讨论","model_name":"测试模型","message_count":2}"""
internal val sideDetailFixture = """{"discussion":$sideFixture,"messages":[{"id":20,"role":"user","content":"为什么这样判断？"},{"id":21,"role":"assistant","content":"可以从材料和结论两方面检查。","generation_status":"completed","usage":{"total_tokens":28}}]}"""

class SideDiscussionTest {
    private lateinit var server: MockWebServer
    private lateinit var api: PlatformApi
    private lateinit var scope: CoroutineScope
    private lateinit var state: SideDiscussionState
    private val requests = CopyOnWriteArrayList<RecordedRequest>()
    @Volatile private var feature = true
    @Volatile private var streamFails = false
    @Volatile private var slowStream = false
    @Volatile private var delayDetail = false
    @Volatile private var saved = false
    @Volatile private var conversions = 0
    private var unauthorized = 0
    @Before fun setup() {
        server = MockWebServer().apply { dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                requests.add(request)
                val path = request.requestUrl!!.encodedPath
                return when {
                    path == "/api/features" -> MockResponse().setBody("""{"features":{"side_discussion":$feature}}""")
                    path == "/api/side-discussions" && request.method == "POST" -> MockResponse().setResponseCode(201).setBody("""{"discussion":$sideFixture}""")
                    path == "/api/side-discussions" -> MockResponse().setBody("""{"discussions":[$sideFixture]}""")
                    path.endsWith("/conversation") -> { conversions++; MockResponse().setResponseCode(201).setBody("""{"conversation":{"id":"saved-c1"}}""") }
                    path.endsWith("/messages") -> {
                        if (streamFails) MockResponse().setResponseCode(503).setBody("{}")
                        else {
                            saved = true
                            MockResponse().setHeader("Content-Type", "text/event-stream").setBody(
                                "data: {\"choices\":[{\"delta\":{\"content\":\"新回答\"},\"finish_reason\":null}]}\n\n" +
                                    (if (slowStream) ": " + " ".repeat(20000) + "\n\n" else "") +
                                    "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n" +
                                    "data: {\"type\":\"message_saved\",\"message_id\":23,\"discussion_id\":\"s1\",\"generation_status\":\"completed\"}\n\n")
                                .apply { if (slowStream) throttleBody(512, 300, TimeUnit.MILLISECONDS) }
                        }
                    }
                    else -> MockResponse().setBody(if (saved) """{"discussion":$sideFixture,"messages":[{"id":22,"role":"user","content":"继续分析"},{"id":23,"role":"assistant","content":"新回答","generation_status":"completed"}]}""" else sideDetailFixture)
                        .apply { if (delayDetail) setBodyDelay(500, TimeUnit.MILLISECONDS) }
                }
            }
        }; start() }
        api = PlatformApi(server.url("/"), CookieJar.NO_COOKIES)
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        state = SideDiscussionState(api, scope) { unauthorized++ }; state.bind("u1", "c1"); state.refreshAvailability()
    }
    @After fun close() { scope.cancel(); server.shutdown() }
    private suspend fun await(condition: () -> Boolean) = withTimeout(7000) { while (!condition()) delay(10) }
    private suspend fun select() {
        await { state.available }; state.openHistory(); await { !state.loading && state.discussions.isNotEmpty() }
        state.select(state.discussions.single()); await { !state.loading && state.messages.size == 2 }
    }
    @Test fun creationUsesOwnedSourceAndDoesNotInvokeModelUntilExplicitSend() = runBlocking {
        await { state.available }
        state.start(ChatMessage("12", "assistant", "原回答", "", "completed", emptyList()), "  所选引用文字  ")
        await { !state.loading && state.active != null }
        val request = requests.single { it.method == "POST" }
        val body = JSONObject(request.body.readUtf8())
        assertEquals("c1", body.getString("session_id")); assertEquals(12L, body.getLong("source_message_id")); assertEquals("所选引用文字", body.getString("selected_text"))
        assertTrue(requests.none { it.requestUrl!!.encodedPath.endsWith("/messages") })
        assertEquals("", state.draft); assertTrue(state.open)
    }
    @Test fun disabledFeatureStopsCreationAndSwitchingAccountsDropsPrivateState() = runBlocking {
        await { state.available }; feature = false
        state.start(ChatMessage("12", "assistant", "回答内容", "", "completed", emptyList()))
        await { !state.loading && state.error.isNotBlank() }
        assertFalse(state.available); assertTrue(requests.none { it.method == "POST" }); assertNull(state.active)
        feature = true; state.bind("u2", "c1"); state.refreshAvailability(); await { state.available }; state.openHistory(); await { !state.loading }
        assertEquals(1, state.discussions.size); state.bind("", "")
        assertFalse(state.open); assertFalse(state.available); assertTrue(state.discussions.isEmpty()); assertTrue(state.messages.isEmpty()); assertEquals("", state.draft)
    }
    @Test fun streamKeepsSavedStatusAndReconcilesWithoutSendingAgain() = runBlocking {
        select(); state.editDraft("继续分析"); state.send()
        await { !state.sending && !state.loading && state.messages.any { it.id == "23" } }
        assertEquals("新回答", state.messages.last().content); assertEquals("", state.draft); assertFalse(state.needsReview)
        assertEquals(1, requests.count { it.requestUrl!!.encodedPath.endsWith("/messages") })
        assertTrue(requests.none { it.requestUrl!!.encodedPath.startsWith("/api/conversations/") })
    }
    @Test fun uncertainFailureNeverAutomaticallyResendsAndNeedsExplicitConfirmation() = runBlocking {
        select(); streamFails = true; state.editDraft("继续分析"); state.send()
        await { !state.sending && !state.loading }; delay(100)
        assertEquals(1, requests.count { it.requestUrl!!.encodedPath.endsWith("/messages") }); assertEquals("继续分析", state.draft); assertTrue(state.needsReview)
        state.send(); delay(100); assertEquals(1, requests.count { it.requestUrl!!.encodedPath.endsWith("/messages") })
        streamFails = false; state.send(confirmed = true); await { !state.sending && !state.loading && state.messages.any { it.id == "23" } }
        assertEquals(2, requests.count { it.requestUrl!!.encodedPath.endsWith("/messages") })
    }
    @Test fun staleDetailCannotLeakAfterConversationSwitchAndConversionIsNotRepeated() = runBlocking {
        select(); var result = ""
        state.saveConversation { result = it }; await { !state.saving }; assertEquals("saved-c1", result)
        state.saveConversation { result = it }; assertEquals(1, conversions)
        delayDetail = true; state.refresh(); await { state.loading }; state.bind("u1", "c2"); delay(650)
        assertFalse(state.open); assertNull(state.active); assertTrue(state.messages.isEmpty()); assertFalse(state.loading)
    }
    @Test fun stoppingKeepsPartialTextAndNeverAutomaticallyRefreshesOrResends() = runBlocking {
        select(); slowStream = true; state.editDraft("继续分析"); state.send()
        await { state.live?.content?.isNotBlank() == true }; assertTrue(state.sending)
        val count = requests.size; state.stop(); delay(150)
        assertFalse(state.sending); assertTrue(state.needsReview); assertEquals("新回答", state.live?.content)
        assertEquals("继续分析", state.draft); assertEquals(count, requests.size)
        state.bind("u2", "c1"); assertNull(state.live); assertEquals("", state.draft); assertFalse(state.open)
    }
    @Test fun historyRoundTripPreservesUnsentBranchDraft() = runBlocking {
        select(); state.editDraft("还没发送的问题")
        state.openHistory(); await { !state.loading }; state.select(state.discussions.single()); await { !state.loading }
        assertEquals("还没发送的问题", state.draft)
        assertTrue(requests.none { it.method != "GET" })
    }
    @Test fun savedTextRetainsSourceAndOutcomeWithoutTriggeringAnyNetworkWrite() {
        val source = SideDiscussion.parse(JSONObject(sideFixture))
        val quote = sideDiscussionQuote(source, "  可用结论。  ")
        assertTrue(quote.contains("> 这是一段值得深入讨论的回答。")); assertTrue(quote.endsWith("可用结论。"))
        assertTrue(requests.none { it.method == "POST" })
    }
}
