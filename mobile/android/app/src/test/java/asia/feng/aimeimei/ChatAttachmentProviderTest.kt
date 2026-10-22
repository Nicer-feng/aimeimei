package asia.feng.aimeimei

import android.app.Application
import androidx.core.content.FileProvider
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28])
class ChatAttachmentProviderTest {
    @Test fun cameraAndDocumentCacheCanBeSharedThroughTheirOwnProvider() {
        val app: Application = RuntimeEnvironment.getApplication()
        val folder = File(app.cacheDir, "chat-attachments/camera").apply { mkdirs() }
        val file = File.createTempFile("native-camera-test", ".jpg", folder)
        try {
            val uri = FileProvider.getUriForFile(app, "${app.packageName}.attachments", file)
            assertEquals("content", uri.scheme); assertEquals("${app.packageName}.attachments", uri.authority)
            assertTrue(uri.path!!.startsWith("/chat-attachments/"))
        } finally { file.delete() }
    }
    @Test fun attachmentProviderCannotExposeUpdateApksOrOtherPrivateFiles() {
        val app: Application = RuntimeEnvironment.getApplication()
        val updates = File(app.cacheDir, "updates").apply { mkdirs() }
        val apk = File.createTempFile("native-update-test", ".apk", updates)
        val other = File.createTempFile("native-private-test", ".txt", app.cacheDir)
        try {
            for (file in listOf(apk, other)) {
                try { FileProvider.getUriForFile(app, "${app.packageName}.attachments", file); fail("Unexpected private path exposure") }
                catch (_: IllegalArgumentException) {}
            }
            assertEquals("${app.packageName}.updates", FileProvider.getUriForFile(app, "${app.packageName}.updates", apk).authority)
        } finally { apk.delete(); other.delete() }
    }
}
