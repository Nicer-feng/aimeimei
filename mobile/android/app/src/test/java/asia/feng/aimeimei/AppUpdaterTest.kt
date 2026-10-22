package asia.feng.aimeimei

import android.app.Application
import android.content.Intent
import android.net.Uri
import kotlinx.coroutines.*
import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28])
class AppUpdaterTest {
    private lateinit var app: Application
    private lateinit var backend: Backend
    private lateinit var packages: Packages
    private lateinit var updater: AppUpdater
    private val instances = mutableListOf<AppUpdater>()
    private val certificate = "ab".repeat(32)
    private inner class Packages : UpdatePackages {
        var current = UpdatePackage("asia.feng.aimeimei", 8, "0.6.0", setOf(certificate))
        override fun installed() = current
        override fun archive(file: File): UpdatePackage = JSONObject(file.readText()).let {
            UpdatePackage(it.getString("package"), it.getLong("code"), it.getString("version"), setOf(it.getString("certificate")))
        }
    }
    private inner class Backend : UpdateBackend {
        var rows = JSONArray()
        val text = mutableMapOf<String, String>()
        val files = mutableMapOf<String, ByteArray>()
        var checks = 0
        var downloads = 0
        var gate: CompletableDeferred<Unit>? = null
        var started = false
        var fail = false
        override fun releases(): JSONArray { checks++; return rows }
        override fun text(url: String) = text.getValue(url)
        override suspend fun download(url: String, file: File, limit: Long, progress: (Int) -> Unit) {
            downloads++; started = true; gate?.await()
            if (fail) { file.writeText("partial"); throw java.io.IOException() }
            val bytes = files.getValue(url); file.writeBytes(bytes); progress(100)
        }
        override fun cancel() {}
        fun offer(code: Long = 9, version: String = "0.6.1", actual: UpdatePackage? = null): UpdateManifest {
            val archive = actual ?: UpdatePackage("asia.feng.aimeimei", code, version, setOf(certificate))
            val bytes = JSONObject().put("package", archive.name).put("code", archive.code).put("version", archive.version).put("certificate", archive.certificates.single()).toString().toByteArray()
            val hash = java.security.MessageDigest.getInstance("SHA-256").digest(bytes).updateHex()
            val info = UpdateManifest(code, version, "asia.feng.aimeimei", "aimeimei-$version.apk", hash, certificate, bytes.size.toLong())
            val base = "https://github.com/$ANDROID_REPOSITORY/releases/download/android/v$version/"
            text[base + "update.json"] = info.toJson().toString(); files[base + info.apkName] = bytes
            rows = JSONArray().put(JSONObject().put("tag_name", "android/v$version").put("assets", JSONArray()
                .put(JSONObject().put("name", "update.json").put("browser_download_url", base + "update.json"))
                .put(JSONObject().put("name", info.apkName).put("browser_download_url", base + info.apkName).put("size", info.size))))
            return info
        }
    }
    @Before fun setup() {
        app = RuntimeEnvironment.getApplication()
        app.getSharedPreferences("android_updates", 0).edit().clear().commit()
        File(app.cacheDir, "updates").deleteRecursively()
        Shadows.shadowOf(app.packageManager).setCanRequestPackageInstalls(true)
        while (Shadows.shadowOf(app).nextStartedActivity != null) { }
        backend = Backend(); packages = Packages(); backend.offer(); updater = create()
    }
    private fun create() = AppUpdater(app, backend, packages, false, Dispatchers.Unconfined).also { instances.add(it) }
    @After fun close() { instances.forEach { it.cancel() }; backend.gate?.complete(Unit) }
    private suspend fun await(condition: () -> Boolean) { withTimeout(7000) { while (!condition() || updater.operationActive) delay(10) } }
    private suspend fun download() { updater.check(); await { updater.state.phase == "available" }; updater.download(); await { updater.state.phase in setOf("ready", "error") } }
    private fun apk() = File(app.cacheDir, "updates").listFiles()!!.single { it.extension == "apk" }
    @Test fun reopeningCompletedDownloadKeepsInstallActionWithoutAnotherCheckOrDownload() = runBlocking {
        download(); assertEquals("ready", updater.state.phase)
        val checks = backend.checks
        backend.offer(8, "0.6.0")
        updater.check(); await { updater.state.phase == "ready" }
        assertEquals(9L, updater.state.manifest!!.versionCode); assertEquals(checks, backend.checks); assertEquals(1, backend.downloads)
        assertTrue(updater.state.message.contains("尚未安装")); assertEquals("0.6.0", updater.installedVersionName)
    }
    @Test fun completedUpdateCanResumeAfterAppStateRecreationWithoutRedownloading() = runBlocking {
        download(); val checks = backend.checks
        val restored = create(); restored.check(); await { restored.state.phase == "ready" }
        assertEquals(9L, restored.state.manifest!!.versionCode); assertEquals(checks, backend.checks); assertEquals(1, backend.downloads)
    }
    @Test fun cachedOlderReleaseCannotHideAnAlreadyDiscoveredHigherVersion() = runBlocking {
        updater.check(); await { updater.state.phase == "available" }
        backend.offer(8, "0.6.0"); updater.check(force = true)
        await { backend.checks == 2 && updater.state.phase != "checking" }
        assertEquals("available", updater.state.phase); assertEquals("0.6.1", updater.state.manifest!!.versionName)
    }
    @Test fun secondReleaseUsesADifferentInstallerUriAndExactVerifiedBytes() = runBlocking {
        download(); updater.install(app); await { updater.state.phase == "ready" }
        val first = Shadows.shadowOf(app).nextStartedActivity!!
        assertEquals(Intent.ACTION_VIEW, first.action); assertEquals("application/vnd.android.package-archive", first.type)
        assertEquals(first.data, first.clipData!!.getItemAt(0).uri)
        assertTrue(first.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
        val firstBytes = app.contentResolver.openInputStream(first.data!!)!!.use { it.readBytes() }
        packages.current = packages.current.copy(code = 9, version = "0.6.1")
        backend.offer(10, "0.6.2"); updater.check(force = true); await { updater.state.phase == "available" }
        updater.download(); await { updater.state.phase == "ready" }; updater.install(app); await { updater.state.phase == "ready" }
        val second = Shadows.shadowOf(app).nextStartedActivity!!
        assertNotEquals(first.data, second.data)
        val secondBytes = app.contentResolver.openInputStream(second.data!!)!!.use { it.readBytes() }
        assertEquals(9, JSONObject(String(firstBytes)).getInt("code")); assertEquals(10, JSONObject(String(secondBytes)).getInt("code"))
        assertTrue(second.data!!.path!!.contains("0.6.2-10-"))
    }
    @Test fun changedCachedApkIsRejectedImmediatelyBeforeOpeningInstaller() = runBlocking {
        download(); val file = apk(); val bytes = file.readBytes(); bytes[0] = (bytes[0].toInt() xor 1).toByte(); file.writeBytes(bytes)
        updater.install(app); await { updater.state.phase != "verifying" }
        assertEquals("error", updater.state.phase); assertNull(Shadows.shadowOf(app).nextStartedActivity)
        assertNull(app.getSharedPreferences("android_updates", 0).getString("ready", null))
    }
    @Test fun permissionRoundTripPreservesTheDownloadedPackage() = runBlocking {
        download(); Shadows.shadowOf(app.packageManager).setCanRequestPackageInstalls(false)
        updater.install(app); await { updater.state.phase == "ready" }
        assertEquals(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Shadows.shadowOf(app).nextStartedActivity!!.action)
        Shadows.shadowOf(app.packageManager).setCanRequestPackageInstalls(true)
        updater.check(); await { updater.state.phase == "ready" }; updater.install(app); await { updater.state.phase == "ready" }
        assertEquals(Intent.ACTION_VIEW, Shadows.shadowOf(app).nextStartedActivity!!.action); assertEquals(1, backend.downloads)
    }
    @Test fun installedVersionComesFromThePackageManagerAndPreventsSameVersionInstallation() = runBlocking {
        download(); packages.current = packages.current.copy(code = 9, version = "0.6.1")
        updater.install(app); await { updater.state.phase == "current" }
        assertEquals("0.6.1", updater.installedVersionName); assertNull(Shadows.shadowOf(app).nextStartedActivity)
    }
    @Test fun declaredNewVersionWithAnOlderArchiveIsNeverReadyToInstall() = runBlocking {
        backend.offer(actual = UpdatePackage("asia.feng.aimeimei", 8, "0.6.0", setOf(certificate)))
        download(); assertEquals("error", updater.state.phase)
        assertNull(app.getSharedPreferences("android_updates", 0).getString("ready", null))
    }
    @Test fun closingAndReopeningDuringDownloadDoesNotLoseProgressOrStartAnotherDownload() = runBlocking {
        backend.gate = CompletableDeferred()
        updater.check(); await { updater.state.phase == "available" }; updater.download(); withTimeout(7000) { while (!backend.started) delay(10) }
        updater.check(); assertEquals("downloading", updater.state.phase); assertEquals(1, backend.downloads)
        backend.gate!!.complete(Unit); await { updater.state.phase == "ready" }
        updater.check(); await { updater.state.phase == "ready" }; assertEquals(1, backend.downloads)
    }
    @Test fun cancelledDownloadCannotPublishLateProgressOrLeaveATemporaryFile() = runBlocking {
        backend.gate = CompletableDeferred()
        updater.check(); await { updater.state.phase == "available" }; updater.download(); withTimeout(7000) { while (!backend.started) delay(10) }
        updater.cancel(); backend.gate!!.complete(Unit)
        await { File(app.cacheDir, "updates").listFiles().orEmpty().none { it.extension == "part" } }
        assertEquals("available", updater.state.phase); assertNull(app.getSharedPreferences("android_updates", 0).getString("ready", null))
    }
    @Test fun failedDownloadCanRetryTheKnownNewVersionEvenIfTheFeedReturnsAnOldRelease() = runBlocking {
        backend.fail = true; download(); assertEquals("error", updater.state.phase)
        backend.offer(8, "0.6.0"); backend.fail = false
        updater.check(force = true); await { updater.state.phase != "checking" }
        assertEquals("available", updater.state.phase); assertEquals("0.6.1", updater.state.manifest!!.versionName)
        updater.download(); await { updater.state.phase == "ready" }
        assertEquals(2, backend.downloads)
    }

}
