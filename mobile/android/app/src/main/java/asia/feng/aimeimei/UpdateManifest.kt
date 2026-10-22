package asia.feng.aimeimei

import org.json.JSONObject
import org.json.JSONArray
import java.net.URI

const val ANDROID_REPOSITORY = "Nicer-feng/aimeimei"
const val MAX_APK_BYTES = 150L * 1024 * 1024

data class UpdateManifest(val versionCode: Long, val versionName: String, val packageName: String,
                          val apkName: String, val sha256: String, val certificateSha256: String, val size: Long) {
    fun toJson() = JSONObject().put("schema", 1).put("versionCode", versionCode).put("versionName", versionName).put("packageName", packageName)
        .put("apkName", apkName).put("sha256", sha256).put("certificateSha256", certificateSha256).put("size", size)
    companion object {
        fun parse(json: JSONObject): UpdateManifest {
            require(json.getInt("schema") == 1) { "不支持的更新格式" }
            val value = UpdateManifest(json.getLong("versionCode"), json.getString("versionName"), json.getString("packageName"),
                json.getString("apkName"), json.getString("sha256").lowercase(), json.getString("certificateSha256").lowercase(), json.getLong("size"))
            require(value.versionCode > 0 && value.versionName.matches(Regex("[0-9]{1,9}\\.[0-9]{1,9}\\.[0-9]{1,9}")))
            require(value.packageName == "asia.feng.aimeimei")
            require(value.apkName == "aimeimei-${value.versionName}.apk")
            require(value.sha256.matches(Regex("[a-f0-9]{64}")) && value.certificateSha256.matches(Regex("[a-f0-9]{64}")))
            require(value.size in 1..MAX_APK_BYTES)
            return value
        }
    }
}

fun trustedReleaseUrl(value: String): Boolean = runCatching {
    val uri = URI(value)
    uri.scheme == "https" && uri.host == "github.com" && uri.port == -1 && uri.userInfo == null &&
        uri.query == null && uri.fragment == null && uri.path.startsWith("/$ANDROID_REPOSITORY/releases/download/android/") &&
        !uri.path.split('/').any { it == ".." || it == "." }
}.getOrDefault(false)

// 不依赖 GitHub 创建时间排序，避免补发旧版本或其它产品发布影响安卓更新。
internal fun androidReleases(releases: JSONArray): List<JSONObject> = attachmentRows(releases).filter { row ->
    !row.optBoolean("draft") && !row.optBoolean("prerelease") && row.optString("tag_name").matches(Regex("android/v[0-9]{1,9}\\.[0-9]{1,9}\\.[0-9]{1,9}")) &&
        attachmentRows(row.optJSONArray("assets")).map { it.optString("name") }.containsAll(listOf("update.json", "aimeimei-${row.optString("tag_name").removePrefix("android/v")}.apk"))
}.sortedWith(compareByDescending<JSONObject> { it.getString("tag_name").removePrefix("android/v").split('.')[0].toLong() }
    .thenByDescending { it.getString("tag_name").removePrefix("android/v").split('.')[1].toLong() }
    .thenByDescending { it.getString("tag_name").removePrefix("android/v").split('.')[2].toLong() })

internal fun updateAssetUrl(url: String, version: String, file: String) = trustedReleaseUrl(url) &&
    URI(url).path == "/$ANDROID_REPOSITORY/releases/download/android/v$version/$file"
