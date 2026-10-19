package asia.feng.aimeimei

import android.app.Application
import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.activity.ComponentActivity
import kotlinx.coroutines.Dispatchers
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import okhttp3.CookieJar
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], qualifiers = "w390dp-h844dp-xhdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class AppShellTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()
    private lateinit var server: MockWebServer
    private lateinit var model: PlatformViewModel
    private lateinit var preferences: AppPreferences
    @Before fun setup() {
        val app: Application = RuntimeEnvironment.getApplication()
        listOf("chat_drafts", "native_session", "appearance").forEach { app.getSharedPreferences(it, 0).edit().clear().commit() }
        server = MockWebServer(); server.start()
        server.enqueue(MockResponse().setBody("""{"authenticated":true,"user":{"id":"u1","username":"family","display_name":"家人","role":"family"}}"""))
        server.enqueue(MockResponse().setBody("""{"conversations":[{"id":"old","title":"历史测试会话","model_id":"m1"}]}"""))
        server.enqueue(MockResponse().setBody("""{"models":[{"id":"m1","name":"测试模型","model":"test"}]}"""))
        model = PlatformViewModel(app, PlatformApi(server.url("/"), CookieJar.NO_COOKIES), {}, {}, dispatcher = Dispatchers.Unconfined)
        // 截图与导航测试关闭过渡，避免在淡入的首帧判断可见性。
        preferences = AppPreferences(app).apply { changeMotion(false) }
        compose.setContent { MeimeiTheme(preferences) { PlatformApp(model, preferences) } }
        compose.waitUntil(10000) { model.account != null && !model.busy }
    }
    @After fun close() { server.shutdown() }
    private fun capture(name: String) {
        val folder = java.io.File("build/reports/native-ui").apply { mkdirs() }
        // Robolectric 没有系统 PixelCopy 合成器，通过原生 Skia 绘制窗口截图。
        compose.runOnIdle {
            val view = compose.activity.window.decorView
            val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888)
            view.draw(Canvas(bitmap))
            java.io.File(folder, "$name.png").outputStream().use { stream ->
                check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, stream))
            }
            bitmap.recycle()
        }
    }
    @Test fun homeDrawerSettingsAndThemeWorkWithoutCreatingAConversation() {
        compose.onNodeWithText("今天，想聊点什么？").assertIsDisplayed()
        compose.onNodeWithText("检查更新").assertDoesNotExist()
        capture("home")
        compose.onNodeWithContentDescription("新聊天").performClick()
        compose.onNodeWithContentDescription("打开历史聊天").performClick()
        compose.onNodeWithText("历史测试会话").assertIsDisplayed()
        capture("history")
        compose.onNodeWithText("设置与账号").performClick()
        compose.onNodeWithText("主题").performClick()
        compose.onNodeWithText("深色").performClick()
        assertEquals("dark", preferences.theme)
        compose.onNodeWithTag("settings-list").performScrollToNode(hasText("检查更新"))
        compose.onNodeWithText("检查更新").assertIsDisplayed()
        capture("settings-dark")
        compose.onNodeWithContentDescription("返回").performClick()
        compose.onNodeWithText("今天，想聊点什么？").assertIsDisplayed()
        assertEquals(3, server.requestCount)
    }
    @Test fun familyToolsDoNotExposeAdministratorEntry() {
        compose.onNodeWithContentDescription("更多工具").performClick()
        compose.waitForIdle()
        capture("tools")
        compose.onNodeWithText("完整聊天").assertIsDisplayed()
        compose.onNodeWithText("后台管理").assertDoesNotExist()
        compose.onNodeWithContentDescription("返回").performClick()
        compose.onNodeWithText("今天，想聊点什么？").assertIsDisplayed()
    }
}
