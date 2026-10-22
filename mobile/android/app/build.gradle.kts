import java.net.URI

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val serverUrl = providers.gradleProperty("apiBaseUrl").orElse("https://feng.asia/").get()
val server = URI(serverUrl)
require(server.scheme == "https" && !server.host.isNullOrBlank() && server.userInfo == null &&
    server.query == null && server.fragment == null && server.path in listOf("", "/")) {
    "apiBaseUrl must be an HTTPS origin, for example https://feng.asia/"
}
val signingPath = System.getenv("ANDROID_KEYSTORE_PATH")
val signingNames = listOf("ANDROID_KEYSTORE_PASSWORD", "ANDROID_KEY_ALIAS", "ANDROID_KEY_PASSWORD")
val hasSigning = !signingPath.isNullOrBlank() && signingNames.all { !System.getenv(it).isNullOrBlank() }
if (gradle.startParameter.taskNames.any { it.contains("Release", ignoreCase = true) }) {
    require(hasSigning) { "Release signing is not configured. See mobile/android/README.md." }
}

android {
    namespace = "asia.feng.aimeimei"
    compileSdk = 36
    defaultConfig {
        applicationId = "asia.feng.aimeimei"
        minSdk = 26
        targetSdk = 36
        versionCode = 11
        versionName = "0.6.3"
        resValue("string", "app_name", "AI槑槑")
        buildConfigField("String", "API_BASE_URL", "\"${server.toASCIIString().trimEnd('/')}/\"")
    }
    signingConfigs {
        if (hasSigning) create("family") {
            storeFile = file(requireNotNull(signingPath))
            storePassword = System.getenv("ANDROID_KEYSTORE_PASSWORD")
            keyAlias = System.getenv("ANDROID_KEY_ALIAS")
            keyPassword = System.getenv("ANDROID_KEY_PASSWORD")
        }
    }
    buildTypes {
        debug {
            applicationIdSuffix = ".dev"
            versionNameSuffix = "-preview"
            resValue("string", "app_name", "AI槑槑·验证")
        }
        release {
            isMinifyEnabled = false
            if (hasSigning) signingConfig = signingConfigs.getByName("family")
        }
    }
    buildFeatures { compose = true; buildConfig = true }
    testOptions { unitTests.isIncludeAndroidResources = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.09.01"))
    implementation("androidx.activity:activity-compose:1.11.0")
    implementation("androidx.core:core-ktx:1.17.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-core")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    implementation("com.squareup.okhttp3:okhttp-sse:4.12.0")
    implementation("com.caverock:androidsvg-aar:1.4")
    implementation("io.noties.markwon:core:4.6.2")
    implementation("io.noties.markwon:ext-tables:4.6.2")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    testImplementation("com.squareup.okhttp3:mockwebserver:4.12.0")
    testImplementation("com.squareup.okhttp3:okhttp-tls:4.12.0")
    testImplementation("org.robolectric:robolectric:4.14.1")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.10.2")
    testImplementation("androidx.compose.ui:ui-test-junit4")
    debugImplementation("androidx.compose.ui:ui-test-manifest")
}
