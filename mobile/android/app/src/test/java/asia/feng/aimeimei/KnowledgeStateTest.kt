package asia.feng.aimeimei

import kotlinx.coroutines.*
import okhttp3.CookieJar
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import java.util.concurrent.TimeUnit

class KnowledgeStateTest {
    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private lateinit var state: KnowledgeState
    private var unauthorized = 0
    @Before fun setup() {
        server = MockWebServer(); server.start(); scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        state = KnowledgeState(PlatformApi(server.url("/"), CookieJar.NO_COOKIES), scope) { unauthorized++ }; state.bind("a")
    }
    @After fun close() { scope.cancel(); server.shutdown() }
    private suspend fun waitFor(condition: () -> Boolean) { withTimeout(5000) { while (!condition()) delay(10) } }
    private val profiles = """{"profiles":[{"id":"p1","title":"偏好","content":"中文回答","type":"style","enabled":true,"sort_order":10,"token_estimate":5}]}"""
    @Test fun latestSearchWinsEvenWhenOldResponseArrivesLater() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"results":[{"id":"old","type":"message"}]}""").setBodyDelay(600, TimeUnit.MILLISECONDS))
        server.enqueue(MockResponse().setBody("""{"results":[{"id":"new","type":"message"}]}"""))
        state.search("旧词"); waitFor { server.requestCount == 1 }; state.search("新词")
        waitFor { !state.searching }; delay(700)
        assertEquals("新词", state.query); assertEquals("new", state.results.single().id)
    }
    @Test fun switchingAccountsClearsPrivateDataAndCancelsInflightSearch() = runBlocking {
        server.enqueue(MockResponse().setBody(profiles)); state.loadProfiles(); waitFor { !state.profilesLoading }
        assertEquals("p1", state.profiles.single().id)
        server.enqueue(MockResponse().setBody("""{"results":[{"id":"private","type":"message"}]}""").setBodyDelay(600, TimeUnit.MILLISECONDS))
        state.search("私密"); waitFor { server.requestCount == 2 }; state.bind("b"); delay(700)
        assertTrue(state.results.isEmpty()); assertTrue(state.profiles.isEmpty()); assertEquals("", state.query); assertFalse(state.searching)
    }
    @Test fun failedSaveKeepsOriginalProfileAndDoesNotCloseEditor() = runBlocking {
        server.enqueue(MockResponse().setBody(profiles)); state.loadProfiles(); waitFor { !state.profilesLoading }
        server.enqueue(MockResponse().setResponseCode(503).setBody("{}")); var closed = false
        state.save("p1", "新标题", "新内容", "style", false) { closed = true }; waitFor { !state.saving }
        assertFalse(closed); assertEquals("偏好", state.profiles.single().title); assertTrue(state.profiles.single().enabled); assertTrue(state.profileError.isNotBlank())
    }
    @Test fun failedSearchCanRetryAndUnauthorizedRequestsRecheckAccount() = runBlocking {
        server.enqueue(MockResponse().setResponseCode(503).setBody("<html>proxy</html>")); state.search("预算"); waitFor { !state.searching }; assertTrue(state.searchError.isNotBlank())
        server.enqueue(MockResponse().setBody("""{"results":[]}""")); state.search("预算"); waitFor { !state.searching }; assertEquals("", state.searchError)
        server.enqueue(MockResponse().setResponseCode(401).setBody("{}")); state.loadProfiles(); waitFor { !state.profilesLoading }; assertEquals(1, unauthorized)
    }
    @Test fun saveAndDeleteUpdateOnlyAfterServerConfirmation() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"profile":{"id":"p1","title":"偏好","content":"中文回答","type":"style","enabled":true,"sort_order":10}}"""))
        var saved = false; state.save(null, "偏好", "中文回答", "style", true) { saved = true }; waitFor { !state.saving }
        assertTrue(saved); assertEquals("p1", state.profiles.single().id)
        server.enqueue(MockResponse().setResponseCode(503).setBody("{}")); state.delete("p1") {}; waitFor { !state.saving }; assertEquals(1, state.profiles.size)
        server.enqueue(MockResponse().setBody("{}")); var deleted = false; state.delete("p1") { deleted = true }; waitFor { !state.saving }; assertTrue(deleted); assertTrue(state.profiles.isEmpty())
    }
}
