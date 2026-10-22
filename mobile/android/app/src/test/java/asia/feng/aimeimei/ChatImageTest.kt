package asia.feng.aimeimei

import android.app.Application
import android.content.ContentProvider
import android.content.ContentValues
import android.content.pm.ProviderInfo
import android.database.MatrixCursor
import android.graphics.Bitmap
import android.media.ExifInterface
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.provider.OpenableColumns
import kotlinx.coroutines.*
import okhttp3.CookieJar
import okhttp3.mockwebserver.*
import okio.Buffer
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
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class ChatImageTest {
    private lateinit var app: Application
    private lateinit var server: MockWebServer
    private lateinit var tools: ChatTools
    private lateinit var scope: CoroutineScope
    private lateinit var bytes: ByteArray
    private val requests = CopyOnWriteArrayList<RecordedRequest>()
    private var failImage = false
    private var blockPolicy = false
    @Before fun setup() {
        app = RuntimeEnvironment.getApplication()
        app.getSharedPreferences("chat_drafts", 0).edit().clear().commit()
        File(app.cacheDir, "chat-attachments").deleteRecursively()
        val bitmap = Bitmap.createBitmap(240, 120, Bitmap.Config.ARGB_8888).apply { eraseColor(android.graphics.Color.BLUE) }
        bytes = ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.JPEG, 90, it) }.toByteArray(); bitmap.recycle()
        server = MockWebServer().apply { dispatcher = object : Dispatcher() {
            override fun dispatch(request: RecordedRequest): MockResponse {
                requests.add(request)
                return if (request.requestUrl!!.encodedPath.endsWith("/upload-policy")) {
                    if (blockPolicy) MockResponse().setSocketPolicy(SocketPolicy.NO_RESPONSE) else MockResponse().setResponseCode(503).setBody("{}")
                } else if (failImage) MockResponse().setResponseCode(503).setBody("unavailable")
                else MockResponse().setHeader("Content-Type", "image/jpeg").setBody(Buffer().write(bytes))
            }
        }; start() }
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        tools = ChatTools(app, PlatformApi(server.url("/"), CookieJar.NO_COOKIES), scope) {}
        tools.bind("u1", "c1")
    }
    @After fun close() { tools.bind("", ""); scope.cancel(); server.shutdown() }
    private suspend fun until(condition: () -> Boolean) { withTimeout(7000) { while (!condition()) delay(10) } }
    private fun selection(file: File): Uri {
        val provider = object : ContentProvider() {
            override fun onCreate() = true
            override fun query(uri: Uri, projection: Array<out String>?, selection: String?, args: Array<out String>?, order: String?) = MatrixCursor(arrayOf(OpenableColumns.DISPLAY_NAME)).apply { addRow(arrayOf("手机照片.jpg")) }
            override fun getType(uri: Uri) = "image/jpeg"
            override fun openFile(uri: Uri, mode: String) = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY)
            override fun insert(uri: Uri, values: ContentValues?): Uri? = null
            override fun delete(uri: Uri, selection: String?, args: Array<out String>?) = 0
            override fun update(uri: Uri, values: ContentValues?, selection: String?, args: Array<out String>?) = 0
        }
        provider.attachInfo(app, ProviderInfo().apply { authority = "image-regression-files" })
        ShadowContentResolver.registerProviderInternal("image-regression-files", provider)
        return Uri.parse("content://image-regression-files/photo")
    }
    @Test fun selectedPhotoIsPreviewableBeforeUploadFinishesAndCancellationCleansIt() = runBlocking {
        blockPolicy = true
        val source = File.createTempFile("gallery-", ".jpg", app.cacheDir).apply { writeBytes(bytes) }
        try {
            tools.addFiles(listOf(selection(source), selection(source)), true)
            until { requests.any { it.requestUrl!!.encodedPath.endsWith("upload-policy") } }
            assertEquals(2, tools.attachments.size)
            assertTrue(tools.attachments.all { tools.localFile(it) != null })
            assertEquals("queued", tools.attachments.last().status)
            val item = tools.attachments.first()
            assertEquals("uploading", item.status); assertFalse(item.ready)
            tools.showPreview(item)
            assertNotNull(tools.previewFile); assertNotNull(decodeChatImage(tools.previewFile!!, 480))
            assertEquals(1, requests.size)
            tools.cancelUploads()
            until { File(app.cacheDir, "chat-attachments").walkTopDown().none { it.isFile && it.name.startsWith("selected-") } }
            assertTrue(tools.attachments.isEmpty()); assertFalse(tools.uploading)
        } finally { source.delete() }
    }
    @Test fun failedUploadKeepsLocalPreviewAndCanRetryWithoutSelectingAgain() = runBlocking {
        val source = File.createTempFile("gallery-", ".jpg", app.cacheDir).apply { writeBytes(bytes) }
        try {
            tools.addFiles(listOf(selection(source)), true)
            until { !tools.uploading && tools.attachments.singleOrNull()?.status == "failed" }
            val item = tools.attachments.single()
            assertNotNull(tools.localFile(item)); tools.showPreview(item); assertNotNull(tools.previewFile)
            tools.retryAttachment(item)
            until { !tools.uploading && requests.size == 2 }
            assertEquals("failed", tools.attachments.single().status); assertFalse(tools.ready)
            assertNotNull(tools.localFile(item)); tools.removeAttachment(item)
            assertNull(tools.localFile(item)); assertTrue(tools.attachments.isEmpty())
        } finally { source.delete() }
    }
    @Test fun historyImagesSurviveStateRecreationAndStayIsolatedBetweenAccounts() = runBlocking {
        val item = ChatAttachment("image1", "照片.jpg", "image/jpeg", bytes.size.toLong(), true)
        val first = tools.imageFile(item); assertArrayEquals(bytes, first.readBytes())
        val recreated = ChatTools(app, PlatformApi(server.url("/"), CookieJar.NO_COOKIES), scope) {}
        recreated.bind("u1", "c1")
        assertEquals(first, recreated.imageFile(item)); assertEquals(1, requests.size)
        recreated.bind("u2", "c1"); assertNull(recreated.localFile(item))
        val other = recreated.imageFile(item); assertNotEquals(first.parentFile, other.parentFile); assertEquals(2, requests.size)
        recreated.bind("", ""); assertFalse(first.exists()); assertFalse(other.exists())
    }
    @Test fun failedHistoryPreviewCanBeRetriedAndClosingDoesNotLeaveLoadingState() = runBlocking {
        val item = ChatAttachment("image1", "照片.jpg", "image/jpeg", 100, true)
        failImage = true; tools.showPreview(item)
        until { !tools.previewBusy }
        assertNull(tools.previewFile); assertTrue(tools.previewError.isNotBlank())
        failImage = false; tools.showPreview(item); until { !tools.previewBusy }
        assertNotNull(tools.previewFile); assertEquals("", tools.previewError)
        tools.closePreview(); assertNull(tools.preview); assertFalse(tools.previewBusy)
    }
    @Test fun nonImagesAreRejectedAndCameraExifRotationIsRespected() = runBlocking {
        val invalid = File.createTempFile("invalid-image", ".jpg", app.cacheDir).apply { writeText("<html>not an image</html>") }
        val camera = File.createTempFile("rotated-camera", ".jpg", app.cacheDir).apply { writeBytes(bytes) }
        try {
            assertFalse(chatImageBoundsValid(invalid)); assertNull(decodeChatImage(invalid, 2048))
            ExifInterface(camera.path).apply { setAttribute(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_ROTATE_90.toString()); saveAttributes() }
            val rotated = decodeChatImage(camera, 2048)!!
            assertEquals(120, rotated.width); assertEquals(240, rotated.height)
            val thumbnail = decodeChatImage(camera, 100)!!
            assertTrue(thumbnail.width <= 100 && thumbnail.height <= 100)
        } finally { invalid.delete(); camera.delete() }
    }
}
