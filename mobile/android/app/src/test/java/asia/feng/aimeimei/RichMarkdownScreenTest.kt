package asia.feng.aimeimei

import android.content.ClipboardManager
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import androidx.activity.ComponentActivity
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.compose.ui.unit.dp
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import org.robolectric.annotation.GraphicsMode
import org.robolectric.shadows.ShadowDialog
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], qualifiers = "w390dp-h844dp-xhdpi")
@GraphicsMode(GraphicsMode.Mode.NATIVE)
class RichMarkdownScreenTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()
    private val code = "const title = \"槑槑阅读增强\";\n// 复制保留完整代码\nconsole.log(title);\n"
    private val content = """### 更轻松地阅读回答

代码可以复制，宽表格可以左右滑动，流程图可以全屏查看。

```js
${code.trimEnd()}
```

| 功能 | 使用场景 | 处理方式 | 结果 | 建议 |
| --- | --- | --- | --- | --- |
| 代码高亮 | 查看示例程序 | 原生显示 | 保留格式 | 点击复制 |
| 宽表格 | 对比多列内容 | 左右滑动 | 完整阅读 | 可复制表格 |

```mermaid
flowchart LR
 A[收到材料] --> B[整理要点] --> C[完成草稿]
```
"""
    private fun show() = compose.setContent { MaterialTheme { Surface { Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp)) { RichMarkdownText(content) } } } }
    private fun capture(name: String, dialog: Boolean = false) = compose.runOnIdle {
        val view = if (dialog) checkNotNull(ShadowDialog.getLatestDialog()?.window?.decorView) else compose.activity.window.decorView
        val bitmap = Bitmap.createBitmap(view.width, view.height, Bitmap.Config.ARGB_8888); view.draw(Canvas(bitmap))
        val folder = File("build/reports/native-ui").apply { mkdirs() }
        File(folder, "$name.png").outputStream().use { check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, it)) }; bitmap.recycle()
    }
    @Test fun codeCopiesExactSourceAndTableScrollsWithoutMovingMainAnswer() {
        show()
        compose.onAllNodesWithTag("reading-copy-code")[0].performClick()
        compose.runOnIdle { assertEquals(code, (compose.activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).primaryClip!!.getItemAt(0).text.toString()) }
        compose.onNodeWithTag("reading-table-scroll").performTouchInput { swipeLeft() }
        compose.runOnIdle { assertTrue(compose.onNodeWithTag("reading-table-scroll").fetchSemanticsNode().config[SemanticsProperties.HorizontalScrollAxisRange].value() > 0f) }
        capture("native-rich-reading")
    }
    @Test fun diagramHasFullScreenSourceAndCopyFallbackWithoutAnyWebBridge() {
        show()
        compose.onNodeWithTag("reading-open-diagram").performScrollTo().performClick()
        compose.onNodeWithText("复制源码", substring = false).assertIsDisplayed()
        compose.onNodeWithText("查看源码", substring = false).performClick()
        compose.onNodeWithText("复制源码", substring = false).performClick()
        compose.runOnIdle { assertTrue((compose.activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager).primaryClip!!.getItemAt(0).text.toString().contains("A[收到材料]")) }
        capture("native-diagram-source", true)
        compose.onNodeWithText("关闭", substring = false).performClick()
        compose.onNodeWithTag("reading-diagram-web").assertDoesNotExist()
    }
}
