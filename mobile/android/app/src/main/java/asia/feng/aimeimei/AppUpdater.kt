package asia.feng.aimeimei

import android.app.Activity
import android.app.Application
import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.FileProvider
import kotlinx.coroutines.*
import org.json.JSONObject
import java.io.File

// 下载完成仍是待安装状态，只有系统实际安装版本提高才表示升级成功。
data class UpdateState(val phase: String = "idle", val manifest: UpdateManifest? = null,
                       val apkUrl: String = "", val percent: Int = 0, val message: String = "")

class AppUpdater internal constructor(private val app: Application, private val backend: UpdateBackend = GitHubUpdateBackend(),
                                      private val packages: UpdatePackages = AndroidUpdatePackages(app),
                                      private val preview: Boolean = BuildConfig.DEBUG,
                                      dispatcher: CoroutineDispatcher = Dispatchers.Main.immediate) {
    var state by mutableStateOf(UpdateState()); private set
    private val scope = CoroutineScope(SupervisorJob() + dispatcher)
    private val preferences = app.getSharedPreferences("android_updates", Context.MODE_PRIVATE)
    private val folder get() = File(app.cacheDir, "updates").apply { mkdirs() }
    private var job: Job? = null
    private var revision = 0
    internal val operationActive get() = job?.isActive == true
    val installedVersionName get() = runCatching { packages.installed().version }.getOrDefault(BuildConfig.VERSION_NAME)
    private fun target(info: UpdateManifest) = File(folder, "aimeimei-${info.versionName}-${info.versionCode}-${info.sha256.take(16)}.apk")
    private fun current(): UpdateState = UpdateState("current", message = "当前安装版本 v${packages.installed().version}，已是最新正式版。")
    private fun ready(offer: UpdateState) = offer.copy(phase = "ready", percent = 100,
        message = "v${offer.manifest!!.versionName} 已下载并校验，尚未安装。请点击「安装更新」，再在系统窗口确认。")
    private fun verify(file: File, info: UpdateManifest) {
        require(file.isFile && file.length() == info.size && updateHash(file) == info.sha256)
        val installed = packages.installed(); val archive = packages.archive(file)
        require(installed.name == info.packageName && archive.name == info.packageName)
        require(archive.code == info.versionCode && archive.version == info.versionName && archive.code > installed.code)
        require(info.certificateSha256 in installed.certificates && info.certificateSha256 in archive.certificates)
    }
    private fun saved(): UpdateState? {
        val raw = preferences.getString("ready", null) ?: return null
        return runCatching {
            val row = JSONObject(raw); val info = UpdateManifest.parse(row.getJSONObject("manifest")); val url = row.getString("apkUrl")
            require(updateAssetUrl(url, info.versionName, info.apkName))
            verify(target(info), info)
            ready(UpdateState(manifest = info, apkUrl = url))
        }.getOrElse { preferences.edit().remove("ready").commit(); null }
    }
    private fun persist(offer: UpdateState) {
        kotlin.check(preferences.edit().putString("ready", JSONObject().put("manifest", offer.manifest!!.toJson()).put("apkUrl", offer.apkUrl).toString()).commit())
    }
    private fun available(offer: UpdateState): UpdateState? = offer.takeIf { it.manifest != null && it.manifest.versionCode > packages.installed().code }
        ?.copy(phase = "available", percent = 0, message = "发现正式版 v${offer.manifest?.versionName}。下载后还需确认安装。")
    fun check(force: Boolean = false) {
        if (job?.isActive == true) return
        if (preview) { state = UpdateState("preview", message = "当前为内部验证包，请使用长期签名正式版更新。"); return }
        val previous = state
        val ticket = ++revision
        job = scope.launch {
            state = UpdateState("checking", message = "正在检查新版本…")
            var fallback: UpdateState? = null
            try {
                val result = withContext(Dispatchers.IO) {
                    // 重新打开弹窗优先恢复已验证的安装包，不把待安装状态重置成重新下载。
                    val cached = saved()
                    fallback = cached ?: available(previous)
                    if (cached != null && !force) return@withContext cached
                    File(folder, "update.apk").delete()
                    val rows = androidReleases(backend.releases())
                    require(rows.isNotEmpty()) { "更新列表暂未同步" }
                    val release = rows.first(); val version = release.getString("tag_name").removePrefix("android/v")
                    val files = attachmentRows(release.optJSONArray("assets"))
                    val manifestUrl = files.first { it.optString("name") == "update.json" }.getString("browser_download_url")
                    require(updateAssetUrl(manifestUrl, version, "update.json"))
                    val info = UpdateManifest.parse(JSONObject(backend.text(manifestUrl)))
                    val installed = packages.installed()
                    require(info.packageName == installed.name && info.versionName == version)
                    require(info.certificateSha256 in installed.certificates)
                    val apk = files.first { it.optString("name") == info.apkName }
                    val url = apk.getString("browser_download_url")
                    require(updateAssetUrl(url, info.versionName, info.apkName) && apk.getLong("size") == info.size)
                    val known = fallback
                    // 更新源短暂返回旧列表时，保留已经发现的更高版本，不误报当前已最新。
                    if (known?.manifest != null && known.manifest.versionCode >= info.versionCode) return@withContext known
                    if (info.versionCode <= installed.code) current()
                    else UpdateState("available", info, url, message = "发现正式版 v${info.versionName}。下载后还需确认安装。")
                }
                if (ticket == revision) state = result
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) {
                if (ticket == revision) state = fallback ?: UpdateState("error", message = "更新信息暂未同步或校验失败，请重新检查；当前版本没有改变。")
            }
        }
    }
    fun download() {
        val offer = state; val info = offer.manifest ?: return
        if (job?.isActive == true || offer.phase !in setOf("available", "error") || !updateAssetUrl(offer.apkUrl, info.versionName, info.apkName)) return
        val ticket = ++revision
        job = scope.launch {
            state = offer.copy(phase = "downloading", percent = 0, message = "正在下载 v${info.versionName}，下载完成后需要确认安装。")
            var partial: File? = null
            try {
                withContext(Dispatchers.IO) {
                    val file = File.createTempFile("update-", ".part", folder); partial = file
                    backend.download(offer.apkUrl, file, info.size) { percent -> scope.launch {
                        if (ticket == revision && state.phase == "downloading") state = offer.copy(phase = "downloading", percent = percent, message = "正在下载 v${info.versionName}…")
                    } }
                    verify(file, info); currentCoroutineContext().ensureActive()
                    val apk = target(info)
                    if (apk.exists()) kotlin.check(apk.delete())
                    kotlin.check(file.renameTo(apk)); persist(offer)
                }
                if (ticket == revision) state = ready(offer)
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) { if (ticket == revision) state = offer.copy(phase = "error", message = "下载或安装包校验未完成，请重试。当前版本仍为 v$installedVersionName。") }
            finally { partial?.delete() }
        }
    }
    fun install(context: Context) {
        val offer = state; val info = offer.manifest ?: return
        if (offer.phase != "ready" || job?.isActive == true) return
        val ticket = ++revision
        job = scope.launch {
            state = offer.copy(phase = "verifying", message = "正在核对待安装的 v${info.versionName}…")
            try {
                val file = target(info)
                // 安装前重新检查实际文件和当前已安装版本，拒绝旧包、错包或被替换的缓存。
                withContext(Dispatchers.IO) { verify(file, info) }
                if (ticket != revision) return@launch
                if (!app.packageManager.canRequestPackageInstalls()) {
                    context.startActivity(Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${app.packageName}")).apply { if (context !is Activity) addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) })
                    state = ready(offer).copy(message = "允许槑槑安装更新后，返回并点击「安装更新」。v${info.versionName} 已下载，无需重下。")
                    return@launch
                }
                val uri = FileProvider.getUriForFile(context, "${app.packageName}.updates", file)
                context.startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
                    .apply { clipData = ClipData.newRawUri("AI槑槑 ${info.versionName}", uri); addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION); if (context !is Activity) addFlags(Intent.FLAG_ACTIVITY_NEW_TASK) })
                state = ready(offer).copy(message = "已打开 v${info.versionName} 的系统安装器，请确认安装。当前运行版本仍为 v$installedVersionName。")
            } catch (cancelled: CancellationException) { throw cancelled }
            catch (_: Exception) {
                preferences.edit().remove("ready").apply()
                if (ticket == revision) state = if (packages.installed().code >= info.versionCode) current()
                    else offer.copy(phase = "error", message = "待安装文件或权限校验失败，请重新检查并下载更新。")
            }
        }
    }
    fun cancel() {
        revision++; backend.cancel(); job?.cancel(); job = null
        state = state.takeIf { it.manifest != null }?.copy(phase = "available", percent = 0, message = "下载已取消，可以重新下载。") ?: UpdateState()
    }
}
