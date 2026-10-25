package asia.feng.aimeimei

import android.app.Application
import android.content.ContentProvider
import android.content.ContentValues
import android.content.pm.ProviderInfo
import android.database.MatrixCursor
import android.graphics.Bitmap
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import kotlinx.coroutines.*
import okhttp3.CookieJar
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import java.util.concurrent.TimeUnit

internal fun ocrSelectionFixture(app: Application, file: File, name: String = "手写照片", mime: String = "image/png"): Uri {
    val provider = object : ContentProvider() {
        override fun onCreate() = true
        override fun query(uri: Uri, projection: Array<out String>?, selection: String?, args: Array<out String>?, order: String?) = MatrixCursor(arrayOf(OpenableColumns.DISPLAY_NAME)).apply { addRow(arrayOf(name)) }
        override fun getType(uri: Uri) = mime
        override fun openFile(uri: Uri, mode: String) = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
        override fun insert(uri: Uri, values: ContentValues?): Uri? = null
        override fun delete(uri: Uri, selection: String?, args: Array<out String>?) = 0
        override fun update(uri: Uri, values: ContentValues?, selection: String?, args: Array<out String>?) = 0
    }
    provider.attachInfo(app, ProviderInfo().apply { authority = "native-ocr-fixture" })
    ShadowContentResolver.registerProviderInternal("native-ocr-fixture", provider)
    return Uri.parse("content://native-ocr-fixture/photo")
}
internal fun ocrBitmapFixture(app: Application): File {
    val bitmap = Bitmap.createBitmap(400, 200, Bitmap.Config.ARGB_8888).apply { eraseColor(android.graphics.Color.rgb(235, 225, 200)) }
    val file = File.createTempFile("ocr-photo-", ".png", app.cacheDir)
    file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }; bitmap.recycle(); return file
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class MobileToolsStateTest {
    private lateinit var app: Application
    private lateinit var server: MockWebServer
    private lateinit var scope: CoroutineScope
    private lateinit var state: MobileToolsState
    @Before fun setup() {
        app = RuntimeEnvironment.getApplication(); server = MockWebServer(); server.start(); scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        state = MobileToolsState(app, PlatformApi(server.url("/"), CookieJar.NO_COOKIES), scope) {}; state.bind("u1")
    }
    @After fun close() { state.bind(""); scope.cancel(); server.shutdown() }
    private suspend fun waitFor(condition: () -> Boolean) { withTimeout(6000) { while (!condition()) delay(10) } }
    @Test fun selectionPreviewsOriginalWithoutNetworkAndAccountChangeCleansPrivateCache() = runBlocking {
        val source = ocrBitmapFixture(app)
        try {
            state.select(ocrSelectionFixture(app, source)); waitFor { !state.preparing }
            val selected = state.image!!; assertEquals("手写照片.png", selected.name); assertArrayEquals(source.readBytes(), selected.file.readBytes())
            assertNotNull(decodeChatImage(selected.file, 480)); assertEquals(0, server.requestCount)
            state.bind("u2"); assertNull(state.image); assertFalse(selected.file.exists()); assertTrue(state.records.isEmpty())
        } finally { source.delete() }
    }
    @Test fun invalidImageNeverReachesUploadOrRecognition() = runBlocking {
        val source = File.createTempFile("invalid-ocr-", ".png", app.cacheDir).apply { writeText("not an image") }
        try {
            state.select(ocrSelectionFixture(app, source)); waitFor { !state.preparing }
            assertNull(state.image); assertTrue(state.ocrError.contains("图片")); state.recognize(); assertEquals(0, server.requestCount)
            assertTrue(File(app.cacheDir, "native-ocr").listFiles().orEmpty().isEmpty())
        } finally { source.delete() }
    }
    @Test fun slowUsageResponseCannotLeakAcrossAccountsAndErrorsCanRetry() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"summary":{"total_tokens":123}}""").setBodyDelay(500, TimeUnit.MILLISECONDS))
        state.loadUsage(); waitFor { server.requestCount == 1 }; state.bind("u2"); delay(600); assertNull(state.usage); assertFalse(state.usageLoading)
        server.enqueue(MockResponse().setResponseCode(503).setBody("{}")); state.loadUsage(); waitFor { !state.usageLoading }; assertTrue(state.usageError.isNotBlank())
        server.enqueue(MockResponse().setBody("""{"summary":{"total_tokens":5000000000},"days":[]}""")); state.loadUsage(); waitFor { !state.usageLoading }
        assertEquals(5000000000L, state.usage!!.getJSONObject("summary").getLong("total_tokens")); assertEquals("", state.usageError)
    }
    @Test fun failedDeletionKeepsRecordAndOnlyConfirmedSuccessRemovesIt() = runBlocking {
        server.enqueue(MockResponse().setBody("""{"tasks":[{"id":"o1","filename":"手写.png","status":"completed","recognized_text":"原始文字"}]}"""))
        state.loadOcr(); waitFor { !state.historyLoading }; val row = state.records.single(); state.view(row)
        server.enqueue(MockResponse().setResponseCode(503).setBody("{}")); var done = false; state.delete(row) { done = true }; waitFor { !state.processing }
        assertFalse(done); assertEquals(1, state.records.size); assertEquals(row, state.result)
        server.enqueue(MockResponse().setBody("{}")); state.delete(row) { done = true }; waitFor { !state.processing }
        assertTrue(done); assertTrue(state.records.isEmpty()); assertNull(state.result)
    }
}
