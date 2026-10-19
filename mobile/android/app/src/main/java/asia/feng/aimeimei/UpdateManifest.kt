package asia.feng.aimeimei

import org.json.JSONObject
import java.net.URI

const val ANDROID_REPOSITORY = "Nicer-feng/aimeimei"
const val MAX_APK_BYTES = 150L * 1024 * 1024

data class UpdateManifest(val versionCode: Long, val versionName: String, val packageName: String,
                          val apkName: String, val sha256: String, val certificateSha256: String, val size: Long) {
    companion object {
        fun parse(json: JSONObject): UpdateManifest {
            require(json.getInt("schema") == 1) { "不支持的更新格式" }
            val value = UpdateManifest(json.getLong("versionCode"), json.getString("versionName"), json.getString("packageName"),
                json.getString("apkName"), json.getString("sha256").lowercase(), json.getString("certificateSha256").lowercase(), json.getLong("size"))
            require(value.versionCode > 0 && value.versionName.length in 1..40)
            require(value.packageName == "asia.feng.aimeimei")
            require(value.apkName.matches(Regex("aimeimei-[A-Za-z0-9._-]+\\.apk")))
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
