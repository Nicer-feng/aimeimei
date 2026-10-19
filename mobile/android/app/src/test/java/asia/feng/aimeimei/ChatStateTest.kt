package asia.feng.aimeimei

import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test

class ChatStateTest {
    private fun event(text: String) = JSONObject().put("choices", org.json.JSONArray().put(JSONObject().put("delta", JSONObject().put("content", text))))
    @Test fun unicodeIsNotSplitAndFinishStopsTheQueue() {
        val buffer = ReplyBuffer()
        val text = "你好😀，这是一段分批到达的回答。".repeat(60)
        buffer.accept(event(text))
        val first = buffer.snapshot().content
        assertTrue(first.length < text.length)
        assertFalse(first.last().isHighSurrogate())
        assertEquals(text, buffer.snapshot(finish = true).content)
        assertEquals(text, buffer.snapshot().content)
    }
    @Test fun finishReasonAndDoneAreNotPersistenceConfirmation() {
        val buffer = ReplyBuffer()
        buffer.accept(JSONObject("""{"choices":[{"delta":{"content":"正文"},"finish_reason":"stop"}]}"""))
        assertNull(buffer.savedId)
        buffer.accept(JSONObject("""{"type":"message_saved","message_id":12,"generation_status":"interrupted"}"""))
        assertEquals("12", buffer.savedId); assertEquals("interrupted", buffer.status)
    }
    @Test fun missingMessageIdIsNotSuccess() {
        val buffer = ReplyBuffer()
        buffer.accept(JSONObject("""{"type":"message_saved","generation_status":"completed"}"""))
        assertNull(buffer.savedId)
    }
    @Test fun reasoningAndSearchEventsDoNotLeakIntoAnswer() {
        val buffer = ReplyBuffer()
        for (field in listOf("reasoning_content", "reasoning", "thinking")) {
            buffer.accept(JSONObject("""{"choices":[{"delta":{"$field":"思考"}}]}"""))
        }
        buffer.accept(JSONObject("""{"type":"search_status","status":"done","count":3}"""))
        val result = buffer.snapshot(finish = true)
        assertEquals("思考思考思考", result.reasoning); assertEquals("", result.content); assertTrue(result.activity.contains("资料"))
    }
    @Test fun recoveryMustMatchTheNewUserTurn() {
        val waiting = PendingSend("c1", 10, "问题")
        fun message(id: String, role: String, content: String) = ChatMessage(id, role, content, "", "completed", emptyList())
        val history = listOf(message("9", "user", "问题"), message("10", "assistant", "旧回答"))
        assertNull(pendingReply(waiting, history))
        assertNull(pendingReply(waiting, history + message("11", "user", "其它问题") + message("12", "assistant", "其它回答")))
        assertEquals("12", pendingReply(waiting, history + message("11", "user", "问题") + message("12", "assistant", "回答"))?.id)
        assertNull(pendingReply(waiting, history + message("11", "user", "问题") + message("12", "user", "其它问题") + message("13", "assistant", "其它回答")))
    }
    @Test fun recoveryMarkerRoundTripsWithoutLosingDraft() {
        val waiting = PendingSend("c1", 77, "长文\n\"内容\"😀".repeat(300))
        assertEquals(waiting, PendingSend.parse(waiting.toJson())); assertNull(PendingSend.parse("invalid"))
        assertNotEquals(draftKey("u1", "c1", "text"), draftKey("u2", "c1", "text"))
        assertNotEquals(draftKey("u1", "c1", "text"), draftKey("u1", "c2", "text"))
    }
}
