package asia.feng.aimeimei

import android.app.Application
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.os.Build
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import okhttp3.CacheControl
import okhttp3.Call
import okhttp3.OkHttpClient
import okhttp3.Request
import org.json.JSONArray
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

internal data class UpdatePackage(val name: String, val code: Long, val version: String, val certificates: Set<String>)
internal interface UpdatePackages {
    fun installed(): UpdatePackage
    fun archive(file: File): UpdatePackage
}
internal class AndroidUpdatePackages(private val app: Application) : UpdatePackages {
    private fun flags() = if (Build.VERSION.SDK_INT >= 28) PackageManager.GET_SIGNING_CERTIFICATES else @Suppress("DEPRECATION") PackageManager.GET_SIGNATURES
    @Suppress("DEPRECATION") private fun read(info: PackageInfo): UpdatePackage {
        val signatures = if (Build.VERSION.SDK_INT >= 28) info.signingInfo?.apkContentsSigners else info.signatures
        val code = if (Build.VERSION.SDK_INT >= 28) info.longVersionCode else info.versionCode.toLong()
        return UpdatePackage(info.packageName, code, info.versionName.orEmpty(), signatures.orEmpty().map { MessageDigest.getInstance("SHA-256").digest(it.toByteArray()).updateHex() }.toSet())
    }
    override fun installed() = read(app.packageManager.getPackageInfo(app.packageName, flags()))
    override fun archive(file: File) = read(app.packageManager.getPackageArchiveInfo(file.path, flags()) ?: error("安装包无法解析"))
}

internal interface UpdateBackend {
    fun releases(): JSONArray
    fun text(url: String): String
    suspend fun download(url: String, file: File, limit: Long, progress: (Int) -> Unit)
    fun cancel()
}
internal class GitHubUpdateBackend : UpdateBackend {
    private val client = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS).readTimeout(45, TimeUnit.SECONDS)
        .callTimeout(15, TimeUnit.MINUTES).followSslRedirects(false).build()
    @Volatile private var call: Call? = null
    private fun request(url: String) = client.newCall(Request.Builder().url(url)
        .header("User-Agent", "Aimeimei-Android/${BuildConfig.VERSION_NAME}")
        .header("Pragma", "no-cache").cacheControl(CacheControl.Builder().noCache().noStore().build()).build())
    override fun releases() = JSONArray(text("https://api.github.com/repos/$ANDROID_REPOSITORY/releases?per_page=100&page=1"))
    override fun text(url: String): String {
        val next = request(url); call = next
        try { return next.execute().use { response ->
            if (!response.isSuccessful) throw IOException("更新服务暂不可用")
            val body = response.body ?: throw IOException("更新信息为空")
            require(body.contentLength() <= 1024 * 1024)
            val output = ByteArrayOutputStream()
            body.byteStream().use { input ->
                val chunk = ByteArray(8192)
                while (true) { val n = input.read(chunk); if (n < 0) break; require(output.size() + n <= 1024 * 1024); output.write(chunk, 0, n) }
            }
            output.toByteArray().toString(Charsets.UTF_8)
        } } finally { if (call === next) call = null }
    }
    override suspend fun download(url: String, file: File, limit: Long, progress: (Int) -> Unit) {
        val next = request(url); call = next
        try { next.execute().use { response ->
            if (!response.isSuccessful) throw IOException("安装包下载失败")
            val body = response.body ?: throw IOException("安装包内容为空")
            require(body.contentLength() <= limit)
            var size = 0L; var last = -1
            body.byteStream().use { input -> file.outputStream().use { output ->
                val bytes = ByteArray(64 * 1024)
                while (true) {
                    currentCoroutineContext().ensureActive()
                    val n = input.read(bytes); if (n < 0) break; size += n; require(size <= limit)
                    output.write(bytes, 0, n)
                    val percent = (size * 100 / limit).toInt().coerceIn(0, 100)
                    if (percent != last) { last = percent; progress(percent) }
                }
            } }
            require(size == limit)
        } } finally { if (call === next) call = null }
    }
    override fun cancel() { call?.cancel() }
}

internal fun ByteArray.updateHex() = joinToString("") { "%02x".format(it) }
internal fun updateHash(file: File): String {
    val hash = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { input -> val bytes = ByteArray(64 * 1024); while (true) { val n = input.read(bytes); if (n < 0) break; hash.update(bytes, 0, n) } }
    return hash.digest().updateHex()
}
