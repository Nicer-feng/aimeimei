package asia.feng.aimeimei

import android.app.Application
import android.content.ClipData
import android.content.ContentProvider
import android.content.ContentValues
import android.content.Intent
import android.content.pm.ProviderInfo
import android.database.MatrixCursor
import android.graphics.Bitmap
import android.net.Uri
import android.os.ParcelFileDescriptor
import android.os.Bundle
import android.os.Parcel
import android.provider.OpenableColumns
import kotlinx.coroutines.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowContentResolver
import java.io.File
import java.io.ByteArrayInputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

internal class IncomingShareFixture(private val app: Application) {
    private data class Entry(val file: File, val name: String, val mime: String, val size: Long)
    private val entries = mutableMapOf<String, Entry>()
    init {
        val provider = object : ContentProvider() {
            override fun onCreate() = true
            override fun query(uri: Uri, projection: Array<out String>?, selection: String?, args: Array<out String>?, order: String?) =
                MatrixCursor(arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE)).apply {
                    val row = entries[uri.lastPathSegment] ?: return@apply
                    addRow(arrayOf(row.name, row.size))
                }
            override fun getType(uri: Uri) = entries[uri.lastPathSegment]?.mime
            override fun openFile(uri: Uri, mode: String) = ParcelFileDescriptor.open(entries.getValue(uri.lastPathSegment.orEmpty()).file, ParcelFileDescriptor.MODE_READ_ONLY)
            override fun insert(uri: Uri, values: ContentValues?): Uri? = null
            override fun delete(uri: Uri, selection: String?, args: Array<out String>?) = 0
            override fun update(uri: Uri, values: ContentValues?, selection: String?, args: Array<out String>?) = 0
        }
        provider.attachInfo(app, ProviderInfo().apply { authority = "incoming-share-fixture" })
        ShadowContentResolver.registerProviderInternal("incoming-share-fixture", provider)
    }
    fun add(file: File, name: String = "分享照片.png", mime: String = "image/png", size: Long = file.length()): Uri {
        val key = entries.size.toString(); entries[key] = Entry(file, name, mime, size)
        return Uri.parse("content://incoming-share-fixture/$key")
    }
    fun image(): File {
        val file = File.createTempFile("incoming-fixture-", ".png", app.cacheDir)
        val bitmap = Bitmap.createBitmap(160, 100, Bitmap.Config.ARGB_8888).apply { eraseColor(android.graphics.Color.rgb(230, 200, 210)) }
        file.outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }; bitmap.recycle(); return file
    }
}

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class IncomingShareStateTest {
    private lateinit var app: Application
    private lateinit var scope: CoroutineScope
    private lateinit var state: IncomingShareController
    private lateinit var fixture: IncomingShareFixture
    @Before fun setup() {
        app = RuntimeEnvironment.getApplication()
        File(app.cacheDir, "incoming-shares").deleteRecursively()
        app.getSharedPreferences("incoming_share_receipts", 0).edit().clear().commit()
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        state = IncomingShareController(app, scope); fixture = IncomingShareFixture(app)
    }
    @After fun close() { state.discard(); scope.cancel(); File(app.cacheDir, "incoming-shares").deleteRecursively() }
    private suspend fun await(condition: () -> Boolean) { withTimeout(6000) { while (!condition()) delay(10) } }
    private fun textIntent(text: String) = Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)

    @Test fun textShareWaitsForExplicitLoginAndAppendsOnlyAfterConfirmation() = runBlocking {
        var imported = 0
        assertTrue(state.accept(textIntent("https://example.com/article\n请帮我整理"), "")); await { !state.preparing }
        assertEquals("https://example.com/article\n请帮我整理", state.pending!!.text)
        state.confirm("") { imported++; true }; assertEquals(0, imported)
        state.requestLogin(); assertTrue(state.waitingForLogin)
        state.bindAccount("u1"); assertFalse(state.waitingForLogin); assertEquals("u1", state.pending!!.owner)
        state.confirm("u1") { imported++; assertEquals("u1", it.owner); true }
        await { !state.importing }; assertEquals(1, imported); assertNull(state.pending)
    }

    @Test fun clipDataAndStreamsAreDeduplicatedAndCopiedBeforeSourceGrantExpires() = runBlocking {
        val source = fixture.image(); val uri = fixture.add(source, "../照片")
        val intent = Intent(Intent.ACTION_SEND).setType("image/png").putExtra(Intent.EXTRA_STREAM, uri)
            .apply { clipData = ClipData.newUri(app.contentResolver, "图片", uri) }
        state.accept(intent, "u1"); await { !state.preparing }
        val row = state.pending!!; assertEquals(1, row.images.size)
        val image = row.images.single(); assertEquals("照片.png", image.name)
        assertArrayEquals(source.readBytes(), image.file.readBytes()); source.delete()
        assertNotNull(decodeChatImage(image.file, 480))
        state.accept(intent, "u1"); assertEquals(row.id, state.pending!!.id)
        state.discard(); assertFalse(image.file.exists())
    }

    @Test fun excessiveCountUnsafeUrisAndInvalidImagesNeverBecomePending() = runBlocking {
        val source = fixture.image(); val uris = ArrayList((0..5).map { fixture.add(source) })
        state.accept(Intent(Intent.ACTION_SEND_MULTIPLE).setType("image/png").putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris), "u1")
        await { !state.preparing }; assertNull(state.pending); assertTrue(state.error.contains("5"))
        state.accept(Intent(Intent.ACTION_SEND).setType("image/png").putExtra(Intent.EXTRA_STREAM, Uri.parse("file:///private/data.png")), "u1")
        await { !state.preparing }; assertNull(state.pending); assertTrue(state.error.contains("安全分享"))
        val corrupt = File.createTempFile("incoming-invalid-", ".png", app.cacheDir).apply { writeText("not an image") }
        state.accept(Intent(Intent.ACTION_SEND).setType("image/png").putExtra(Intent.EXTRA_STREAM, fixture.add(corrupt)), "u1")
        await { !state.preparing }; assertNull(state.pending); assertTrue(state.error.contains("无法预览"))
        assertTrue(File(app.cacheDir, "incoming-shares").listFiles().orEmpty().isEmpty()); source.delete(); corrupt.delete()
    }

    @Test fun unsupportedTypeAndOversizedImageAreRejectedUsingAttachmentLimits() = runBlocking {
        val source = fixture.image()
        state.accept(Intent(Intent.ACTION_SEND).setType("image/gif").putExtra(Intent.EXTRA_STREAM, fixture.add(source, "动画.gif", "image/gif")), "u1")
        await { !state.preparing }; assertNull(state.pending); assertTrue(state.error.contains("JPG"))
        state.accept(Intent(Intent.ACTION_SEND).setType("image/png").putExtra(Intent.EXTRA_STREAM, fixture.add(source, size = 20L * 1024 * 1024 + 1)), "u1")
        await { !state.preparing }; assertNull(state.pending); assertTrue(state.error.contains("20MB")); source.delete()
    }

    @Test fun switchingAccountsCancelsAnUnfinishedImportAndRemovesItsFiles() = runBlocking {
        val source = fixture.image()
        state.accept(Intent(Intent.ACTION_SEND).setType("image/png").putExtra(Intent.EXTRA_STREAM, fixture.add(source)), "u1")
        await { !state.preparing }; val copied = state.pending!!.images.single().file
        val finish = CompletableDeferred<Unit>(); var committed = false
        state.confirm("u1") { finish.await(); committed = true; true }; assertTrue(state.importing)
        state.bindAccount("u2"); finish.complete(Unit); delay(30)
        assertFalse(committed); assertNull(state.pending); assertFalse(copied.exists()); source.delete()
    }

    @Test fun failedImportPreservesEditablePreviewAndRetryIsExplicit() = runBlocking {
        state.accept(textIntent("原文"), "u1"); await { !state.preparing }; var attempts = 0
        state.confirm("u1") { attempts++; false }; await { !state.importing }
        assertEquals(1, attempts); assertNotNull(state.pending); assertTrue(state.error.isNotBlank())
        state.editText("改过的链接 https://example.com"); assertEquals("", state.error)
        state.confirm("u1") { attempts++; assertTrue(it.text.startsWith("改过")); true }; await { !state.importing }
        assertEquals(2, attempts); assertNull(state.pending)
    }

    @Test fun textClipDataLinksStayTextAndCannotReadOurOwnPrivateProviders() = runBlocking {
        val clipped = Intent(Intent.ACTION_SEND).setType("text/plain").apply { clipData = ClipData.newRawUri("网页", Uri.parse("https://example.com/article")) }
        state.accept(clipped, "u1"); await { !state.preparing }
        assertEquals("https://example.com/article", state.pending!!.text); assertTrue(state.pending!!.images.isEmpty())
        state.accept(Intent(Intent.ACTION_SEND).setType("image/png").putExtra(Intent.EXTRA_STREAM, Uri.parse("content://0@${app.packageName}.attachments/chat-attachments/private.png")), "u1")
        await { !state.preparing }; assertNull(state.pending); assertTrue(state.error.contains("重新分享"))
    }

    @Test fun pendingSurvivesProcessRecreationButConsumedIntentCannotReplay() = runBlocking {
        val intent = textIntent("待加入草稿")
        state.accept(intent, "u1"); await { !state.preparing }; val id = state.pending!!.id
        await { File(app.cacheDir, "incoming-shares/$id/payload.json").isFile }
        scope.cancel(); scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        state = IncomingShareController(app, scope)
        state.accept(intent, "u1"); await { state.pending != null }; assertEquals(id, state.pending!!.id)
        state.bindAccount("u1"); state.confirm("u1") { true }; await { !state.importing }; assertNull(state.pending)
        state.accept(intent, "u1"); delay(30); assertNull(state.pending)
    }

    @Test fun originalSystemParcelReceivesSavedReceiptAndCannotReplayAConsumedShare() = runBlocking {
        val incoming = textIntent("系统保留的原始分享")
        val parcel = Parcel.obtain()
        val systemOriginal = try {
            incoming.writeToParcel(parcel, 0); parcel.setDataPosition(0); Intent.CREATOR.createFromParcel(parcel)
        } finally { parcel.recycle() }
        assertFalse(systemOriginal.hasExtra(INCOMING_RECEIPT))
        state.accept(incoming, "u1"); await { !state.preparing }
        val saved = Bundle(); saveIncomingShareReceipt(incoming, saved)
        assertEquals(setOf(INCOMING_RECEIPT), saved.keySet())
        state.confirm("u1") { true }; await { !state.importing }; assertNull(state.pending)
        scope.cancel(); scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        state = IncomingShareController(app, scope)
        restoreIncomingShareReceipt(systemOriginal, saved)
        assertEquals(incoming.getStringExtra(INCOMING_RECEIPT), systemOriginal.getStringExtra(INCOMING_RECEIPT))
        state.accept(systemOriginal, "u1"); delay(30)
        assertNull(state.pending); assertFalse(state.preparing)
    }

    @Test fun canceledPreviousShareCannotDeleteTheNextShareWhileBothReachEof() = runBlocking {
        val source = fixture.image(); val bytes = source.readBytes()
        val oldAtEof = CountDownLatch(1); val newAtEof = CountDownLatch(1)
        val releaseOld = CountDownLatch(1); val releaseNew = CountDownLatch(1)
        fun blockedInput(atEof: CountDownLatch, release: CountDownLatch) = object : ByteArrayInputStream(bytes) {
            override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
                val count = super.read(buffer, offset, length)
                if (count < 0) { atEof.countDown(); check(release.await(5, TimeUnit.SECONDS)) { "EOF was not released" } }
                return count
            }
        }
        val oldUri = fixture.add(source, "上一张.png"); val newUri = fixture.add(source, "最新图片.png")
        val resolver = Shadows.shadowOf(app.contentResolver)
        resolver.registerInputStream(oldUri, blockedInput(oldAtEof, releaseOld))
        resolver.registerInputStream(newUri, blockedInput(newAtEof, releaseNew))
        val oldIntent = Intent(Intent.ACTION_SEND).setType("image/png").putExtra(Intent.EXTRA_STREAM, oldUri)
        val newIntent = Intent(Intent.ACTION_SEND).setType("image/png").putExtra(Intent.EXTRA_STREAM, newUri)
        try {
            state.accept(oldIntent, "u1"); assertTrue(oldAtEof.await(5, TimeUnit.SECONDS))
            state.accept(newIntent, "u1"); assertTrue(newAtEof.await(5, TimeUnit.SECONDS))
            val oldId = oldIntent.getStringExtra(INCOMING_RECEIPT)!!; val newId = newIntent.getStringExtra(INCOMING_RECEIPT)!!
            releaseOld.countDown(); await { !File(app.cacheDir, "incoming-shares/$oldId").exists() }
            assertTrue(File(app.cacheDir, "incoming-shares/$newId").isDirectory)
            releaseNew.countDown(); await { !state.preparing }
            assertEquals("最新图片.png", state.pending!!.images.single().name)
            assertTrue(state.pending!!.images.single().file.isFile); assertEquals("", state.error)
        } finally { releaseOld.countDown(); releaseNew.countDown(); source.delete() }
    }

    @Test fun restoreSkipsFreshDirectoriesWithoutManifestAndRemovesExpiredOrphans() = runBlocking {
        scope.cancel()
        val root = File(app.cacheDir, "incoming-shares").apply { mkdirs() }
        val fresh = File(root, "11111111-1111-1111-1111-111111111111").apply { mkdirs() }
        val old = File(root, "22222222-2222-2222-2222-222222222222").apply { mkdirs(); setLastModified(System.currentTimeMillis() - 7200000) }
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined); state = IncomingShareController(app, scope)
        await { !old.exists() }
        assertTrue(fresh.isDirectory); assertNull(state.pending)
    }

    @Test fun restoredShareNeverCrossesItsOriginalAccountAndExpiryCleansLocalData() = runBlocking {
        state.accept(textIntent("账号一的内容"), "u1"); await { !state.preparing }; val id = state.pending!!.id
        await { File(app.cacheDir, "incoming-shares/$id/payload.json").isFile }
        scope.cancel(); scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined)
        state = IncomingShareController(app, scope); state.bindAccount("u2"); await { !File(app.cacheDir, "incoming-shares/$id").exists() }
        assertNull(state.pending); assertFalse(File(app.cacheDir, "incoming-shares/$id").exists())
        state.accept(textIntent("过期内容"), "u2"); await { !state.preparing }; val expired = state.pending!!.id
        val manifest = File(app.cacheDir, "incoming-shares/$expired/payload.json"); await { manifest.isFile }
        scope.cancel()
        manifest.writeText(org.json.JSONObject(manifest.readText()).put("received_at", System.currentTimeMillis() - 7200000).toString())
        scope = CoroutineScope(SupervisorJob() + Dispatchers.Unconfined); state = IncomingShareController(app, scope); await { !manifest.exists() }
        assertNull(state.pending); assertFalse(manifest.exists())
    }
}
