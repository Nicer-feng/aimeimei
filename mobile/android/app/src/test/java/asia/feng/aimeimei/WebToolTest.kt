package asia.feng.aimeimei

import okhttp3.HttpUrl.Companion.toHttpUrl
import org.junit.Assert.*
import org.junit.Test

class WebToolTest {
    private val base = "https://feng.asia/".toHttpUrl()
    @Test fun embeddedToolsOnlyTrustTheConfiguredHttpsOrigin() {
        assertTrue(sameWebOrigin(base, "https://feng.asia/ai/#app-tool=admin"))
        for (url in listOf("http://feng.asia/ai/", "https://feng.asia.evil.test/", "https://evil.test/", "https://feng.asia:8443/", "https://user:pass@feng.asia/", "file:///etc/passwd", "javascript:alert(1)", "content://private/data")) {
            assertFalse(url, sameWebOrigin(base, url))
        }
    }
    @Test fun conversationAndToolAreEncodedAsFragmentData() {
        val url = webToolUrl(base, "chat", "会话&app-tool=admin").toHttpUrl()
        assertEquals("/ai/", url.encodedPath); assertNull(url.query)
        assertEquals("会话&app-tool=admin", java.net.URLDecoder.decode(url.encodedFragment!!.substringAfter("&conversation="), "UTF-8"))
        assertEquals("/admin/share", webToolUrl(base, "cloud", "").toHttpUrl().encodedPath)
        assertEquals("/gifts", webToolUrl(base, "gifts", "").toHttpUrl().encodedPath)
    }
}
