package asia.feng.aimeimei

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ChatAttachmentsTest {
    @Test fun quoteFormatMatchesTheWebAndHistoryCanSeparateTheQuestion() {
        val text = quoteMessage("新的问题", listOf(ChatQuote("4", "assistant", "第一行\n第二行"), ChatQuote("3", "user", "背景材料")))
        assertTrue(text.contains("【来源：槑槑】\n> 第一行\n> 第二行\n【引用结束】"))
        val display = quotedDisplay(text)
        assertEquals(listOf("第一行\n第二行", "背景材料"), display.first); assertEquals("新的问题", display.second)
        assertEquals(emptyList<String>() to "普通消息", quotedDisplay("普通消息"))
    }
    @Test fun quoteOnlySendHasAnExplicitQuestionAndBoundsTheContext() {
        val text = quoteMessage("", (1..5).map { ChatQuote("$it", "assistant", "长".repeat(13000)) })
        assertEquals(3, quotedDisplay(text).first.size); assertTrue(quotedDisplay(text).first.all { it.length == 12000 })
        assertEquals("请基于以上引用内容进行分析。", quotedDisplay(text).second)
    }
    @Test fun pendingRecordKeepsAttachmentIdentityAndOriginalEditableDraft() {
        val file = ChatAttachment("img1", "照片.jpg", "image/jpeg", 20, true)
        val wire = quoteMessage("问题", listOf(ChatQuote("4", "assistant", "背景")))
        val pending = PendingSend("c1", 5, wire, listOf(file), "问题")
        val parsed = PendingSend.parse(pending.toJson())!!
        assertEquals("img1", parsed.attachments.single().id); assertEquals("问题", parsed.draftText); assertEquals(wire, parsed.content)
        assertNotNull(PendingSend.parse("""{"conversation_id":"c1","baseline":0,"content":"旧版本草稿"}"""))
        assertEquals("旧版本草稿", PendingSend.parse("""{"conversation_id":"c1","baseline":0,"content":"旧版本草稿"}""")!!.draftText)
    }
    @Test fun documentCannotBeSentUntilParsingCompletes() {
        val pending = ChatAttachment.fromJson(JSONObject("""{"id":"doc1","filename":"材料.pdf","status":"processing"}"""), false)
        assertFalse(pending.ready); assertTrue(pending.copy(status = "completed").ready)
        assertFalse(pending.copy(id = "", status = "completed").ready)
        assertFalse(pending.copy(status = "failed").ready)
    }
}
