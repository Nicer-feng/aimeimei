package asia.feng.aimeimei

import android.net.Uri
import android.webkit.WebSettings
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.Shadows
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28])
class RichMarkdownTest {
    @Test fun fencesKeepOriginalSourceWithAliasesTildesAndStreamingTail() {
        val source = "前面的 **回答**。\n\n```js\nconst title = \"</script>\";\n```\n\n~~~python\nprint(1)\n~~~\n\n```sql\nSELECT 1;"
        val code = readingBlocks(source).filterIsInstance<ReadingBlock.Code>()
        assertEquals(3, code.size)
        assertEquals(ReadingBlock.Code("javascript", "const title = \"</script>\";\n"), code[0])
        assertEquals(ReadingBlock.Code("python", "print(1)\n"), code[1])
        assertEquals(ReadingBlock.Code("sql", "SELECT 1;"), code[2])
        assertTrue(readingBlocks(source).filterIsInstance<ReadingBlock.Text>().first().source.contains("**回答**"))
    }
    @Test fun shorterFenceCannotCloseLongFenceAndCodeTablesStayCode() {
        val code = readingBlocks("````markdown\n```\n| a | b |\n| --- | --- |\n````").single() as ReadingBlock.Code
        assertEquals("```\n| a | b |\n| --- | --- |\n", code.source)
        assertTrue(readingBlocks("    ```js\n    code\n    ```").all { it is ReadingBlock.Text })
    }
    @Test fun tablesRespectEscapedPipesInlineCodeAlignmentAndShortRows() {
        val block = readingBlocks("| 名称 | 表达式 | 说明 |\n| :--- | :---: | ---: |\n| a\\|b | `a|b` | **粗体** |\n| 末行 |\n\n后文").filterIsInstance<ReadingBlock.Table>().single()
        assertEquals(listOf(-1, 0, 1), block.alignments)
        assertEquals(listOf("a\\|b", "`a|b`", "**粗体**"), block.rows[1])
        assertEquals(listOf("末行", "", ""), block.rows[2])
        assertEquals("普通 | 文字", (readingBlocks("普通 | 文字").single() as ReadingBlock.Text).source)
        assertFalse(readingBlocks("| a | b |\n| --- |\n").any { it is ReadingBlock.Table })
    }
    @Test fun syntaxRangesNeverReplaceOrExecuteSourceAndUnknownLanguageStaysPlain() {
        val code = "const url = \"https://example.test\"; // 123 is a comment\nreturn 42;"
        val ranges = codeSyntax(code, "javascript")
        assertEquals("const", code.substring(ranges.first().start, ranges.first().end))
        assertEquals(1, ranges.count { it.kind == "comment" })
        assertEquals(1, ranges.count { it.kind == "number" })
        assertEquals("42", ranges.filter { it.kind == "number" }.single().let { code.substring(it.start, it.end) })
        assertTrue(ranges.all { it.start >= 0 && it.end <= code.length && it.start < it.end })
        assertTrue(codeSyntax(code, "not-a-language").isEmpty())
        assertTrue(codeSyntax("x".repeat(100001), "javascript").isEmpty())
    }
    @Test fun diagramSupportsMainWebTypesAndNeverInterpolatesUntrustedHtml() {
        assertEquals("流程图", mermaidKind("flowchart LR\n A --> B"))
        assertEquals("思维导图", mermaidKind("mindmap\n root((计划))"))
        assertEquals("时序图", mermaidKind("sequenceDiagram\n A->>B:Hi"))
        assertNull(mermaidKind("<script>alert(1)</script>"))
        val source = "</script><img src=x onerror=alert(1)>\u2028'\\"
        val html = diagramHtml(source, false)
        assertFalse(html.contains("</script><img"))
        // Android 的 JSON 编码器还可能将斜杠写为 \/；检查安全转义和解码结果，而非某一种合法编码形式。
        assertTrue(html.contains("\\u003c"))
        assertTrue(html.contains("\\u003e"))
        assertEquals(source, org.json.JSONTokener(html.substringAfter("const source=")).nextValue())
        assertTrue(html.contains("securityLevel:'strict'"))
        assertTrue(html.contains("connect-src 'none'"))
        assertTrue(html.contains("fallback.textContent=source"))
        assertFalse(html.contains("addJavascriptInterface"))
    }
    @Test fun rendererAllowsExactlyOneBundledAssetAndBlocksNetworkFilesAndNavigation() {
        assertTrue(isDiagramAsset(Uri.parse("$DIAGRAM_ORIGIN$DIAGRAM_SCRIPT")))
        listOf("https://example.com/$DIAGRAM_SCRIPT", "https://meimei-reading.invalid.evil/$DIAGRAM_SCRIPT", "https://meimei-reading.invalid:443/$DIAGRAM_SCRIPT",
            "https://user@meimei-reading.invalid/$DIAGRAM_SCRIPT", "$DIAGRAM_ORIGIN$DIAGRAM_SCRIPT?x=1", "$DIAGRAM_ORIGIN../secret", "file:///data/data/secret", "content://private/1").forEach {
            assertFalse(it, isDiagramAsset(Uri.parse(it)))
        }
        val view = diagramWebView(ApplicationProvider.getApplicationContext(), "flowchart LR\n A-->B", true)
        assertTrue(view.settings.javaScriptEnabled)
        assertFalse(view.settings.allowFileAccess)
        assertFalse(view.settings.allowContentAccess)
        assertFalse(view.settings.domStorageEnabled)
        assertTrue(view.settings.blockNetworkLoads)
        assertEquals(WebSettings.MIXED_CONTENT_NEVER_ALLOW, view.settings.mixedContentMode)
        assertEquals(DIAGRAM_ORIGIN, Shadows.shadowOf(view).lastLoadDataWithBaseURL.baseUrl)
        view.destroy()
    }
}
