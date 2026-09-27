#!/usr/bin/env python3
"""Failed chat persistence using temporary SQLite and mocked HTTP only."""
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

import test_chat_stream as transport
from ai_platform import database
from ai_platform.database import db, init_db
from ai_platform.presenters import side_discussion_message_public


class Handler(transport.Handler):
    def __init__(self, cid, discussion_id=None, fail=False):
        super().__init__(cid, fail)
        if discussion_id:
            self.path = "/api/side-discussions/" + discussion_id + "/messages"
        self.user_id = "default"

    def current_user(self):
        return {"id": self.user_id, "role": "admin"}


class CallbackResponse(transport.Response):
    def __init__(self, chunks, callback):
        super().__init__(chunks)
        self.callback = callback

    def read(self, size):
        if self.callback:
            callback, self.callback = self.callback, None
            callback()
        return super().read(size)


def http_error(code=503, detail="upstream unavailable"):
    return urllib.error.HTTPError("https://mock.invalid", code, "mock", {}, io.BytesIO(detail.encode()))


class ChatFailureRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db({"family_password_hash": "test-only"})
        with db() as conn:
            conn.execute("""INSERT INTO models(id,name,provider,base_url,api_key,model,
                input_price_per_million,output_price_per_million,cost_enabled,created_at,updated_at)
                VALUES ('recovery','test','mock','https://mock.invalid','fake','mock',1,2,1,0,0)""")

    @classmethod
    def tearDownClass(cls):
        transport.TEMP.cleanup()

    def setUp(self):
        self.cid = self.id().split(".")[-1]
        self.did = "side-" + self.cid
        with db() as conn:
            conn.execute("UPDATE models SET supports_native_web_search=0 WHERE id='recovery'")
            conn.execute("INSERT INTO conversations(id,user_id,title,model_id,created_at,updated_at) VALUES (?,'default','test','recovery',0,0)", (self.cid,))
            cursor = conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('default',?,'user','引用内容',0)", (self.cid,))
            conn.execute("""INSERT INTO side_discussions(id,user_id,session_id,source_message_id,source_role,
                selected_text,model_id,title,created_at,updated_at)
                VALUES (?,'default',?,?,'user','引用内容','recovery','test',0,0)""", (self.did, self.cid, cursor.lastrowid))
        self.handler = Handler(self.cid)
        self.side = Handler(self.cid, self.did)

    def main_replies(self):
        with db() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY id", (self.cid,))]

    def side_replies(self):
        with db() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM side_discussion_messages WHERE discussion_id=? AND role='assistant' ORDER BY id", (self.did,))]

    def daily_usage(self):
        with db() as conn:
            return conn.execute("SELECT COALESCE(SUM(total_tokens),0) FROM daily_usage").fetchone()[0]

    def side_stream(self, chunks, fail=False, callback=None):
        self.side = Handler(self.cid, self.did, fail)
        response = CallbackResponse(chunks, callback)
        with patch("ai_platform.handlers.chat.urllib.request.urlopen", return_value=response):
            self.side.handle_side_discussion_send()
        self.assertEqual(self.side.status, 200)
        self.assertTrue(response.closed)
        return response, self.side.wfile.getvalue().decode()

    def test_main_connection_failure_is_saved_and_returned(self):
        for error in (TimeoutError("mock timeout"), http_error()):
            with self.subTest(error=type(error).__name__):
                before_usage = self.daily_usage()
                with patch("ai_platform.handlers.chat.urllib.request.urlopen", side_effect=error):
                    self.handler.handle_send_message()
                row = self.main_replies()[-1]
                self.assertEqual(self.handler.status, 502)
                self.assertEqual((row["content"], row["generation_status"], row["total_tokens"], row["estimated_cost"]), ("", "failed", 0, 0))
                self.assertEqual(self.handler.result["message_id"], row["id"])
                self.assertEqual(self.handler.result["conversation_id"], self.cid)
                self.assertEqual(self.handler.result["generation_status"], "failed")
                self.assertEqual(self.daily_usage(), before_usage)
        history = Handler(self.cid)
        history.handle_messages()
        self.assertEqual(history.result["messages"][-1]["generation_status"], "failed")

    def test_main_usage_fallback_failure_creates_only_one_marker(self):
        with patch("ai_platform.handlers.chat.urllib.request.urlopen", side_effect=[http_error(400, "unsupported stream_options include_usage"), TimeoutError()]) as request:
            self.handler.handle_send_message()
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(self.main_replies()), 1)
        self.assertEqual(self.handler.status, 502)

    def test_main_native_fallback_failure_is_saved(self):
        with db() as conn:
            conn.execute("UPDATE models SET supports_native_web_search=1 WHERE id='recovery'")
        with patch("ai_platform.handlers.chat.should_use_web_search", return_value=True), patch("ai_platform.handlers.chat.web_extractor_option_rejected", return_value=True), patch("ai_platform.handlers.chat.urllib.request.urlopen", side_effect=[http_error(400), TimeoutError()]) as request:
            self.handler.handle_send_message()
        self.assertEqual(request.call_count, 2)
        self.assertEqual(self.main_replies()[0]["generation_status"], "failed")

    def test_unreadable_http_error_body_does_not_skip_marker(self):
        error = http_error()
        with patch.object(error, "read", side_effect=TimeoutError()), patch("ai_platform.handlers.chat.urllib.request.urlopen", side_effect=error):
            self.side.handle_side_discussion_send()
        self.assertEqual(self.side.status, 502)
        self.assertEqual(self.side_replies()[0]["generation_status"], "failed")

    def test_main_failure_does_not_restore_deleted_conversation(self):
        def fail(*args, **kwargs):
            with db() as conn:
                conn.execute("UPDATE conversations SET archived=1 WHERE id=?", (self.cid,))
            raise TimeoutError()
        with patch("ai_platform.handlers.chat.urllib.request.urlopen", side_effect=fail):
            self.handler.handle_send_message()
        self.assertEqual(self.main_replies(), [])
        self.assertNotIn("message_id", self.handler.result)

    def test_main_fallback_success_does_not_save_failed_marker(self):
        response = transport.Response([transport.event_bytes(transport.delta("成功", "stop"))])
        with patch("ai_platform.handlers.chat.urllib.request.urlopen", side_effect=[http_error(400, "unsupported stream_options include_usage"), response]):
            self.handler.handle_send_message()
        self.assertEqual([(r["content"], r["generation_status"]) for r in self.main_replies()], [("成功", "completed")])

    def test_side_connect_failure_is_saved_and_history_exposes_status(self):
        with patch("ai_platform.handlers.chat.urllib.request.urlopen", side_effect=TimeoutError()):
            self.side.handle_side_discussion_send()
        self.assertEqual(self.side.status, 502)
        row = self.side_replies()[0]
        self.assertEqual((row["content"], row["generation_status"]), ("", "failed"))
        self.assertEqual(self.side.result["message_id"], row["id"])
        self.assertEqual(self.side.result["discussion_id"], self.did)
        self.side.handle_side_discussion_item()
        self.assertEqual(self.side.result["messages"][-1]["generation_status"], "failed")

    def test_side_success_preserves_utf8_and_usage_once(self):
        before = self.daily_usage()
        raw = transport.event_bytes(transport.delta("完整🚗回复", "stop", usage={"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7})) + b"data: [DONE]\n\n"
        _, stream = self.side_stream([raw[i:i + 1] for i in range(len(raw))])
        row = self.side_replies()[0]
        self.assertEqual((row["content"], row["generation_status"], row["total_tokens"]), ("完整🚗回复", "completed", 7))
        self.assertAlmostEqual(row["estimated_cost"], 0.00001)
        self.assertEqual(self.daily_usage() - before, 7)
        self.assertIn('"type": "message_saved"', stream)
        self.assertNotIn('"type": "message.failed"', stream)

    def test_side_partial_upstream_failure_saves_text_and_received_usage(self):
        before = self.daily_usage()
        _, stream = self.side_stream([transport.event_bytes(transport.delta("部分回复", usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5})), TimeoutError("private mock error")])
        row = self.side_replies()[0]
        self.assertEqual((row["content"], row["generation_status"], row["total_tokens"]), ("部分回复", "failed", 5))
        self.assertEqual(self.daily_usage() - before, 5)
        self.assertIn('"type": "message.failed"', stream)
        self.assertNotIn("private mock error", stream)

    def test_side_client_disconnect_stops_reading_and_keeps_partial(self):
        response, _ = self.side_stream([transport.event_bytes(transport.delta("收到的内容")), transport.event_bytes(transport.delta("不要再读", "stop"))], fail=True)
        self.assertEqual(response.read_count, 1)
        self.assertEqual([(r["content"], r["generation_status"]) for r in self.side_replies()], [("收到的内容", "interrupted")])

    def test_side_disconnect_before_headers_saves_empty_interruption(self):
        response = transport.Response([transport.event_bytes(transport.delta("不应读取", "stop"))])
        with patch.object(self.side, "end_headers", side_effect=BrokenPipeError()), patch("ai_platform.handlers.chat.urllib.request.urlopen", return_value=response):
            self.side.handle_side_discussion_send()
        self.assertEqual(response.read_count, 0)
        self.assertTrue(response.closed)
        self.assertEqual([(r["content"], r["generation_status"]) for r in self.side_replies()], [("", "interrupted")])

    def test_side_usage_fallback_failure_records_one_marker(self):
        with patch("ai_platform.handlers.chat.urllib.request.urlopen", side_effect=[http_error(400, "unsupported stream_options include_usage"), TimeoutError()]) as request:
            self.side.handle_side_discussion_send()
        self.assertEqual(request.call_count, 2)
        self.assertEqual(len(self.side_replies()), 1)
        self.assertEqual(self.side.result["generation_status"], "failed")

    def test_side_reasoning_only_disconnect_is_preserved(self):
        self.side_stream([transport.event_bytes({"choices": [{"delta": {"reasoning_content": "思考片段"}}]})], fail=True)
        row = self.side_replies()[0]
        self.assertEqual((row["content"], row["reasoning_content"], row["generation_status"]), ("", "思考片段", "interrupted"))

    def test_side_empty_error_and_eof_leave_terminal_marker(self):
        _, stream = self.side_stream([transport.event_bytes({"error": {"message": "private upstream message"}})])
        self.assertEqual(self.side_replies()[0]["generation_status"], "failed")
        self.assertNotIn("private upstream message", stream)
        self.side_stream([])
        self.assertEqual((self.side_replies()[-1]["content"], self.side_replies()[-1]["generation_status"]), ("", "interrupted"))

    def test_side_deletion_during_stream_does_not_recreate_reply(self):
        def delete():
            with db() as conn:
                conn.execute("DELETE FROM side_discussions WHERE id=?", (self.did,))
        _, stream = self.side_stream([transport.event_bytes(transport.delta("不应复活", "stop"))], callback=delete)
        self.assertEqual(self.side_replies(), [])
        self.assertNotIn('"type": "message_saved"', stream)

    def test_side_parent_deleted_during_stream_does_not_save(self):
        def archive():
            with db() as conn:
                conn.execute("UPDATE conversations SET archived=1 WHERE id=?", (self.cid,))
        self.side_stream([transport.event_bytes(transport.delta("会话已删除", "stop"))], callback=archive)
        self.assertEqual(self.side_replies(), [])
        self.side.handle_side_discussion_item()
        self.assertEqual(self.side.status, 404)

    def test_side_conversion_retains_incomplete_status_without_double_usage(self):
        self.side_stream([transport.event_bytes(transport.delta("部分内容"))])
        before = self.daily_usage()
        self.side.handle_side_discussion_conversation()
        self.assertEqual(self.side.status, 201)
        cid = self.side.result["conversation"]["id"]
        with db() as conn:
            row = conn.execute("SELECT * FROM messages WHERE conversation_id=? AND role='assistant'", (cid,)).fetchone()
        self.assertEqual((row["content"], row["generation_status"]), ("部分内容", "interrupted"))
        self.assertEqual(self.daily_usage(), before)

    def test_side_empty_failure_does_not_enter_next_prompt(self):
        with patch("ai_platform.handlers.chat.urllib.request.urlopen", side_effect=TimeoutError()):
            self.side.handle_side_discussion_send()
        response = transport.Response([transport.event_bytes(transport.delta("恢复回答", "stop"))])
        with patch("ai_platform.handlers.chat.urllib.request.urlopen", return_value=response) as request:
            self.side.handle_side_discussion_send()
        payload = json.loads(request.call_args.args[0].data)
        self.assertTrue(all(message["content"] for message in payload["messages"]))

    def test_other_user_cannot_create_failure_marker(self):
        self.side.user_id = "other"
        with patch("ai_platform.handlers.chat.urllib.request.urlopen") as request:
            self.side.handle_side_discussion_send()
        self.assertEqual(self.side.status, 404)
        request.assert_not_called()
        self.assertEqual(self.side_replies(), [])

    def test_legacy_side_messages_migrate_idempotently_without_data_loss(self):
        with tempfile.TemporaryDirectory(prefix="aimeimei-legacy-side-") as directory:
            path = Path(directory) / "old.db"
            connection = sqlite3.connect(path)
            with connection:
                connection.execute("""CREATE TABLE side_discussion_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, discussion_id TEXT NOT NULL, role TEXT NOT NULL,
                    content TEXT NOT NULL, reasoning_content TEXT NOT NULL DEFAULT '',
                    input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
                    total_tokens INTEGER NOT NULL DEFAULT 0, estimated_cost REAL NOT NULL DEFAULT 0,
                    actual_model TEXT NOT NULL DEFAULT '', created_at INTEGER NOT NULL)""")
                connection.execute("INSERT INTO side_discussion_messages(discussion_id,role,content,total_tokens,created_at) VALUES ('old','assistant','旧回复',9,0)")
            connection.close()
            with patch.object(database, "DB_PATH", path), patch.object(database, "DATA_DIR", Path(directory)):
                init_db({"family_password_hash": "test-only"})
                init_db({"family_password_hash": "test-only"})
                with db() as conn:
                    row = conn.execute("SELECT * FROM side_discussion_messages").fetchone()
                    self.assertEqual((row["content"], row["total_tokens"], row["generation_status"]), ("旧回复", 9, "completed"))
            legacy_public = side_discussion_message_public({"id": 1, "role": "assistant", "content": "旧回复", "reasoning_content": "", "created_at": 0, "input_tokens": 1, "output_tokens": 2, "total_tokens": 3, "estimated_cost": 0})
            self.assertEqual(legacy_public["generation_status"], "completed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
