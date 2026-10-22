package asia.feng.aimeimei

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class UpdateManifestTest {
    private fun sample() = JSONObject().put("schema", 1).put("versionCode", 4).put("versionName", "0.4.0")
        .put("packageName", "asia.feng.aimeimei").put("apkName", "aimeimei-0.4.0.apk")
        .put("sha256", "ab".repeat(32)).put("certificateSha256", "cd".repeat(32)).put("size", 11000000)
    @Test fun parsesCompleteSignedReleaseMetadata() { val info = UpdateManifest.parse(sample()); assertEquals(4L, info.versionCode); assertEquals("0.4.0", info.versionName) }
    @Test fun rejectsWrongPackage() { assertThrows(IllegalArgumentException::class.java) { UpdateManifest.parse(sample().put("packageName", "other.app")) }; Unit }
    @Test fun rejectsMissingOrMalformedChecksum() { assertThrows(IllegalArgumentException::class.java) { UpdateManifest.parse(sample().put("sha256", "bad")) }; Unit }
    @Test fun rejectsOversizedApk() { assertThrows(IllegalArgumentException::class.java) { UpdateManifest.parse(sample().put("size", MAX_APK_BYTES + 1)) }; Unit }
    @Test fun rejectsPathTraversal() { assertThrows(IllegalArgumentException::class.java) { UpdateManifest.parse(sample().put("apkName", "../update.apk")) }; Unit }
    @Test fun restrictsDownloadsToThisRepositoryAndroidReleases() {
        assertTrue(trustedReleaseUrl("https://github.com/Nicer-feng/aimeimei/releases/download/android/v0.4.0/update.json"))
        for (url in listOf("http://github.com/Nicer-feng/aimeimei/releases/download/android/v0.4.0/update.json",
            "https://github.com/attacker/aimeimei/releases/download/android/v0.4.0/update.json",
            "https://github.com/Nicer-feng/aimeimei/releases/download/file-share/v1/update.json",
            "https://github.com/Nicer-feng/aimeimei/releases/download/android/v1/../update.json",
            "https://github.com/Nicer-feng/aimeimei/releases/download/android/v1/%2e%2e/update.json",
            "https://github.com.evil.test/Nicer-feng/aimeimei/releases/download/android/v1/update.json")) assertFalse(url, trustedReleaseUrl(url))
    }
    @Test fun ignoresOldReleaseCreationOrderDraftsAndOtherProducts() {
        fun row(version: String, draft: Boolean = false) = JSONObject().put("tag_name", "android/v$version").put("draft", draft)
            .put("assets", org.json.JSONArray().put(JSONObject().put("name", "update.json")).put(JSONObject().put("name", "aimeimei-$version.apk")))
        val rows = org.json.JSONArray().put(row("0.6.0")).put(row("0.6.1")).put(row("0.7.0", true)).put(row("0.6.2")).put(JSONObject().put("tag_name", "ios/v9.0.0"))
        assertEquals(listOf("android/v0.6.2", "android/v0.6.1", "android/v0.6.0"), androidReleases(rows).map { it.getString("tag_name") })
    }
    @Test fun requiresMetadataAndApkToBelongToTheExactTargetRelease() {
        assertTrue(updateAssetUrl("https://github.com/Nicer-feng/aimeimei/releases/download/android/v0.6.1/aimeimei-0.6.1.apk", "0.6.1", "aimeimei-0.6.1.apk"))
        assertFalse(updateAssetUrl("https://github.com/Nicer-feng/aimeimei/releases/download/android/v0.6.0/aimeimei-0.6.0.apk", "0.6.1", "aimeimei-0.6.1.apk"))
        assertThrows(IllegalArgumentException::class.java) { UpdateManifest.parse(sample().put("versionName", "../0.4.0")) }
        assertThrows(IllegalArgumentException::class.java) { UpdateManifest.parse(sample().put("apkName", "aimeimei-0.3.0.apk")) }
    }

}
