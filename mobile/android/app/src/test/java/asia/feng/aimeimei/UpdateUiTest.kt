package asia.feng.aimeimei

import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.activity.ComponentActivity
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowDialog

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], qualifiers = "w390dp-h844dp-xhdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class UpdateUiTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()
    private val info = UpdateManifest(10, "0.6.2", "asia.feng.aimeimei", "aimeimei-0.6.2.apk", "ab".repeat(32), "cd".repeat(32), 100)
    private fun capture() { compose.runOnIdle {
        val view = checkNotNull(ShadowDialog.getLatestDialog()?.window?.decorView)
        val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888); view.draw(Canvas(bitmap))
        val folder = java.io.File("build/reports/native-ui").apply { mkdirs() }
        java.io.File(folder, "native-update-ready.png").outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }; bitmap.recycle()
    } }
    @Test fun readyDialogSeparatesInstalledAndTargetVersionsAndOffersInstallation() {
        var installations = 0
        compose.setContent { UpdateDialog(UpdateState("ready", info, message = "v0.6.2 已下载并校验，尚未安装。请点击「安装更新」，再在系统窗口确认。"), "0.6.0", false, {}, {}, { installations++ }, {}, {}) }
        compose.onNodeWithText("更新至 v0.6.2").assertIsDisplayed()
        compose.onNodeWithText("当前安装：v0.6.0").assertIsDisplayed(); compose.onNodeWithText("目标版本：v0.6.2").assertIsDisplayed()
        compose.onNodeWithTag("install-update").assertIsEnabled(); capture()
        compose.onNodeWithTag("install-update").performClick(); assertEquals(1, installations)
    }
    @Test fun backgroundDownloadDoesNotCancelOrPretendToInstall() {
        var closed = false; var cancelled = false
        compose.setContent { UpdateDialog(UpdateState("downloading", info, percent = 65, message = "正在下载 v0.6.2…"), "0.6.0", false, { closed = true }, {}, {}, {}, { cancelled = true }) }
        compose.onNodeWithText("知道了").assertDoesNotExist(); compose.onNodeWithText("后台下载").performClick()
        assertTrue(closed); assertFalse(cancelled)
    }
    @Test fun activeAnswerKeepsTheInstallActionDisabled() {
        compose.setContent { UpdateDialog(UpdateState("ready", info, message = "已下载，尚未安装"), "0.6.0", true, {}, {}, {}, {}, {}) }
        compose.onNodeWithTag("install-update").assertIsNotEnabled()
        compose.onNodeWithText("请等待本次回答完成，或先停止生成，再安装更新。").assertIsDisplayed()
    }

}
