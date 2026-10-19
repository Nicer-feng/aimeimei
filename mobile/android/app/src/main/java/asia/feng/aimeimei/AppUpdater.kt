package asia.feng.aimeimei

import android.app.Application
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.SystemClock
import android.provider.Settings
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.FileProvider
import kotlinx.coroutines.*
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.io.ByteArrayOutputStream
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

data class UpdateState(val phase: String = "idle", val manifest: UpdateManifest? = null,
                       val apkUrl: String = "", val percent: Int = 0, val message: String = "")

class AppUpdater(private val app: Application) {
    var state by mutableStateOf(UpdateState()); private set
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)
    private val client = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS)
        .callTimeout(5, TimeUnit.MINUTES).followSslRedirects(false).build()
    private var job: Job? = null
    @Volatile private var call: Call? = null
    private val folder get() = File(app.cacheDir, "updates").apply { mkdirs() }
    private fun request(url: String) = client.newCall(Request.Builder().url(url).header("User-Agent", "Aimeimei-Android/${BuildConfig.VERSION_NAME}").build())

    fun check() {
        if (job?.isActive == true) return
        if (BuildConfig.DEBUG) {
            state = UpdateState("preview", message = "当前是临时签名验证包。请先按项目说明配置长期签名并安装正式版；正式版以后支持应用内覆盖更新，无需卸载。")
            return
        }
        job = scope.launch {
            state = UpdateState("checking", message = "正在检查新版本…")
            try {
                val result = withContext(Dispatchers.IO) {
                    val releases = JSONArray(readText("https://api.github.com/repos/$ANDROID_REPOSITORY/releases?per_page=30"))
                    val release = (0 until releases.length()).map { releases.getJSONObject(it) }.firstOrNull {
                        !it.optBoolean("draft") && !it.optBoolean("prerelease") && it.optString("tag_name").startsWith("android/v")
                    } ?: return@withContext UpdateState("current", message = "暂未发布可用的正式更新")
                    val assets = release.getJSONArray("assets")
                    val files = (0 until assets.length()).map { assets.getJSONObject(it) }
                    val manifestUrl = files.firstOrNull { it.optString("name") == "update.json" }?.getString("browser_download_url") ?: throw IOException("更新信息尚未发布完整")
                    require(trustedReleaseUrl(manifestUrl))
                    val info = UpdateManifest.parse(JSONObject(readText(manifestUrl)))
                    require(info.packageName == BuildConfig.APPLICATION_ID) { "更新包与当前应用不匹配" }
                    if (info.versionCode <= BuildConfig.VERSION_CODE) return@withContext UpdateState("current", message = "当前已是最新版本 v${BuildConfig.VERSION_NAME}")
                    val apk = files.firstOrNull { it.optString("name") == info.apkName } ?: throw IOException("安装包尚未发布完整")
                    val url = apk.getString("browser_download_url")
                    require(trustedReleaseUrl(url) && apk.getLong("size") == info.size)
                    require(signers(app.packageManager.getPackageInfo(app.packageName, signingFlags())).contains(info.certificateSha256)) { "更新包的签名与当前安装版本不同，已拒绝更新" }
                    UpdateState("available", info, url, message = "发现新版本 v${info.versionName}")
                }
                state = result
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { state = UpdateState("error", message = "检查更新失败，或更新信息/签名不匹配，请稍后重试。聊天功能不受影响。") }
        }
    }
    private fun readText(url: String): String {
        val next = request(url); call = next
        return next.execute().use { response ->
            if (!response.isSuccessful) throw IOException("检查更新失败")
            val body = response.body ?: throw IOException("更新响应为空")
            if (body.contentLength() > 1024 * 1024) throw IOException("更新信息过大")
            val output = ByteArrayOutputStream()
            body.byteStream().use { input ->
                val chunk = ByteArray(8192)
                while (true) {
                    val count = input.read(chunk); if (count < 0) break
                    require(output.size() + count <= 1024 * 1024)
                    output.write(chunk, 0, count)
                }
            }
            output.toByteArray().toString(Charsets.UTF_8)
        }
    }
    fun download() {
        val offer = state
        val info = offer.manifest ?: return
        if (job?.isActive == true || !trustedReleaseUrl(offer.apkUrl)) return
        job = scope.launch {
            state = offer.copy(phase = "downloading", message = "正在下载更新…")
            val partial = File.createTempFile("update-", ".part", folder)
            try {
                withContext(Dispatchers.IO) {
                    val next = request(offer.apkUrl); call = next
                    val hash = MessageDigest.getInstance("SHA-256")
                    var size = 0L; var publishedAt = 0L
                    next.execute().use { response ->
                        if (!response.isSuccessful) throw IOException("下载失败")
                        val body = response.body ?: throw IOException("下载响应为空")
                        body.byteStream().use { input -> partial.outputStream().use { output ->
                            val bytes = ByteArray(64 * 1024)
                            while (true) {
                                ensureActive()
                                val count = input.read(bytes); if (count < 0) break
                                size += count; require(size <= info.size && size <= MAX_APK_BYTES)
                                output.write(bytes, 0, count); hash.update(bytes, 0, count)
                                val now = SystemClock.elapsedRealtime()
                                if (now - publishedAt > 250) { publishedAt = now; val percent = (size * 100 / info.size).toInt(); withContext(Dispatchers.Main) { state = offer.copy(phase = "downloading", percent = percent, message = "正在下载更新…") } }
                            }
                        } }
                    }
                    require(size == info.size && hash.digest().hex() == info.sha256)
                    val apk = File(folder, "update.apk")
                    if (apk.exists()) check(apk.delete())
                    check(partial.renameTo(apk))
                    verifyApk(apk, info)
                }
                state = offer.copy(phase = "ready", percent = 100, message = "更新已校验，点击后由系统确认安装；现有聊天和登录数据会保留。")
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { File(folder, "update.apk").delete(); state = offer.copy(phase = "error", message = "下载失败或安装包校验不通过，请重试。") }
            finally { partial.delete() }
        }
    }
    private fun verifyApk(file: File, info: UpdateManifest) {
        val archive = app.packageManager.getPackageArchiveInfo(file.path, signingFlags()) ?: error("无效安装包")
        val version = if (Build.VERSION.SDK_INT >= 28) archive.longVersionCode else @Suppress("DEPRECATION") archive.versionCode.toLong()
        require(archive.packageName == app.packageName && version == info.versionCode && version > BuildConfig.VERSION_CODE)
        require(signers(archive).contains(info.certificateSha256))
    }
    fun install(context: Context) {
        if (state.phase != "ready") return
        try {
            if (!app.packageManager.canRequestPackageInstalls()) {
                context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${app.packageName}")))
                state = state.copy(message = "允许槑槑安装更新后，请返回并再次点击安装。")
                return
            }
            val uri = FileProvider.getUriForFile(context, "${app.packageName}.updates", File(folder, "update.apk"))
            context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION))
        } catch (_: Exception) { state = state.copy(message = "无法打开系统安装器，请检查安装权限后重试。") }
    }
    fun cancel() { call?.cancel(); job?.cancel(); job = null; state = UpdateState() }
    private fun signingFlags() = if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES else @Suppress("DEPRECATION") PackageManager.GET_SIGNATURES
    @Suppress("DEPRECATION")
    private fun signers(info: PackageInfo): Set<String> {
        val signatures = if (Build.VERSION.SDK_INT >= 28) info.signingInfo?.apkContentsSigners else info.signatures
        return signatures.orEmpty().map { MessageDigest.getInstance("SHA-256").digest(it.toByteArray()).hex() }.toSet()
    }
}

private fun ByteArray.hex() = joinToString("") { "%02x".format(it) }
