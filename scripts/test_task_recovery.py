#!/usr/bin/env python3
"""Isolated task recovery/transaction checks; temporary SQLite, mocked providers."""
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="aimeimei-task-recovery-")
os.environ["AI_PLATFORM_DATA"] = TEMP.name
from ai_platform.database import db, init_db
from ai_platform.handlers.documents import DocumentHandlersMixin
from ai_platform.handlers.media import MediaHandlersMixin

DOC_SUCCESS = {"Data": {"Status": "success"}}
DOC_RESULT = {"Data": {"layouts": [{"text": "可恢复的材料正文", "page": 1}]}}
MEDIA_SUCCESS = {"Data": {"TaskStatus": "COMPLETED", "Result": {}}}


class Harness(DocumentHandlersMixin, MediaHandlersMixin):
    def __init__(self, user_id="owner", command="POST", path="/api/media/tasks/media/refresh"):
        self.server = SimpleNamespace(secrets={})
        self.user_id, self.command, self.path = user_id, command, path
        self.body = {}

    def current_user(self):
        return {"id": self.user_id}

    def read_body(self, **kwargs):
        return self.body

    def json(self, value, status=200):
        return int(status), value

    def error(self, status, message, *args):
        return int(status), {"error": message}


class TaskRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db({"family_password_hash": "test-only"})
        with db() as conn:
            conn.execute("CREATE TABLE task_test_writes (id INTEGER PRIMARY KEY, value INTEGER)")
            conn.execute("INSERT INTO task_test_writes VALUES (1,0)")

    def setUp(self):
        self.handler = Harness()
        with db() as conn:
            conn.execute("DELETE FROM document_chunks")
            conn.execute("DELETE FROM document_files")
            conn.execute("DELETE FROM media_analysis_tasks")
            conn.execute("INSERT INTO document_files(id,user_id,filename,oss_key,status,parser_task_id,created_at,updated_at) VALUES ('doc','owner','test.pdf','test/doc','processing','provider-doc',0,0)")
            conn.execute("INSERT INTO media_analysis_tasks(id,user_id,filename,oss_key,status,task_id,created_at,updated_at) VALUES ('media','owner','test.mp3','test/media','processing','provider-media',0,0)")
        for target in ("documents.docmind_config", "media.tingwu_config"):
            mock = patch("ai_platform.handlers." + target, return_value={})
            mock.start()
            self.addCleanup(mock.stop)
        for target in ("documents.docmind_configured", "media.tingwu_configured"):
            mock = patch("ai_platform.handlers." + target, return_value=True)
            mock.start()
            self.addCleanup(mock.stop)

    def document(self):
        with db() as conn:
            return conn.execute("SELECT * FROM document_files WHERE id='doc'").fetchone()

    def media(self):
        return self.handler.load_media_task("media", "owner")

    def other_write(self):
        # A different connection must commit while the provider is still blocked.
        conn = sqlite3.connect(str(Path(TEMP.name) / "ai-platform.db"), timeout=0.2)
        try:
            with conn:
                conn.execute("UPDATE task_test_writes SET value=value+1 WHERE id=1")
        finally:
            conn.close()

    def blocked_call(self, target, invoke, provider_result, during):
        entered, release = threading.Event(), threading.Event()
        outcome, errors = [], []

        def provider(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise AssertionError("test provider release timed out")
            return provider_result

        def run():
            try:
                outcome.append(invoke())
            except BaseException as exc:
                errors.append(exc)

        with patch(target, side_effect=provider):
            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            try:
                self.assertTrue(entered.wait(3), "provider call was not reached")
                during()
            finally:
                release.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
            if errors:
                raise errors[0]
        return outcome[0]

    def test_document_query_timeout_recovers_same_job(self):
        with patch("ai_platform.handlers.documents.query_doc_parser_status", side_effect=[TimeoutError(), DOC_SUCCESS]) as query, patch("ai_platform.handlers.documents.get_doc_parser_result", return_value=DOC_RESULT):
            row = self.handler.refresh_document(self.document())
            self.assertEqual(row["status"], "processing")
            self.assertTrue(row["error_message"])
            row = self.handler.refresh_document(row)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["parser_task_id"], "provider-doc")
        self.assertEqual(row["error_message"], "")
        self.assertEqual(query.call_count, 2)
        with db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0], 1)

    def test_document_download_timeout_and_old_failed_are_retryable(self):
        with db() as conn:
            conn.execute("UPDATE document_files SET status='failed',error_message='旧查询错误' WHERE id='doc'")
        self.handler.path = "/api/documents/doc/refresh"
        with patch("ai_platform.handlers.documents.query_doc_parser_status", return_value=DOC_SUCCESS), patch("ai_platform.handlers.documents.get_doc_parser_result", side_effect=[TimeoutError(), DOC_RESULT]):
            status, payload = self.handler.handle_document_item()
            self.assertEqual((status, payload["document"]["status"]), (200, "processing"))
            status, payload = self.handler.handle_document_item()
        self.assertEqual((status, payload["document"]["status"]), (200, "completed"))

    def test_document_provider_failure_is_terminal_until_explicit_retry(self):
        with patch("ai_platform.handlers.documents.query_doc_parser_status", return_value={"Data": {"Status": "failed"}, "Message": "unsupported document"}) as query:
            row = self.handler.refresh_document(self.document())
            self.assertEqual(row["status"], "failed")
            self.handler.refresh_document(row)
            self.assertEqual(query.call_count, 1)

    def test_document_delete_during_query_does_not_recreate_chunks(self):
        def delete():
            self.other_write()
            with db() as conn:
                conn.execute("DELETE FROM document_files WHERE id='doc'")
        with patch("ai_platform.handlers.documents.get_doc_parser_result", return_value=DOC_RESULT):
            row = self.blocked_call("ai_platform.handlers.documents.query_doc_parser_status", lambda: self.handler.refresh_document(self.document()), DOC_SUCCESS, delete)
        self.assertIsNone(row)
        with db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM document_chunks").fetchone()[0], 0)

    def test_manual_media_refresh_never_locks_during_provider_query(self):
        with db() as conn:
            conn.execute("UPDATE media_analysis_tasks SET status='completed',transcript_text='旧结果' WHERE id='media'")
        with patch("ai_platform.handlers.media.parse_tingwu_results", return_value={"transcript_text": "新结果"}):
            result = self.blocked_call("ai_platform.handlers.media.tingwu_get_task_info", self.handler.handle_media_task_refresh, MEDIA_SUCCESS, self.other_write)
        self.assertEqual(result[0], 200)
        self.assertEqual(self.media()["transcript_text"], "新结果")

    def test_enhance_commits_refresh_before_waiting_for_model(self):
        def during():
            self.other_write()
            self.assertEqual(self.media()["status"], "completed")
        with patch("ai_platform.handlers.media.tingwu_get_task_info", return_value=MEDIA_SUCCESS), patch("ai_platform.handlers.media.parse_tingwu_results", return_value={"transcript_text": "转写结果"}):
            result = self.blocked_call("ai_platform.handlers.media.MediaHandlersMixin.call_media_ai_model", self.handler.handle_media_task_enhance, {"enhanced_summary": "增强结果"}, during)
        self.assertEqual(result[0], 200)
        self.assertEqual(self.media()["enhanced_summary"], "增强结果")

    def test_media_result_download_failure_keeps_job_retryable(self):
        response = {"Data": {"TaskStatus": "COMPLETED", "Result": {"Transcription": "https://example.invalid/result"}}}
        with patch("ai_platform.handlers.media.tingwu_get_task_info", return_value=response), patch("ai_platform.handlers.media.fetch_result_json", side_effect=TimeoutError()):
            row = self.handler.refresh_media_task(self.media())
        self.assertEqual(row["status"], "processing")
        self.assertEqual(row["task_id"], "provider-media")
        self.assertTrue(row["error_message"])

    def test_late_media_refresh_cannot_overwrite_newer_result(self):
        def update():
            with db() as conn:
                conn.execute("UPDATE media_analysis_tasks SET status='completed',transcript_text='较新结果' WHERE id='media'")
        result = self.blocked_call("ai_platform.handlers.media.tingwu_get_task_info", self.handler.handle_media_task_refresh, {"Data": {"TaskStatus": "PROCESSING"}}, update)
        self.assertEqual(result[0], 200)
        self.assertEqual(self.media()["transcript_text"], "较新结果")
        self.assertEqual(self.media()["status"], "completed")

    def test_late_enhancement_cannot_restore_deleted_task_or_replace_new_output(self):
        for delete in (False, True):
            with self.subTest(delete=delete):
                with db() as conn:
                    conn.execute("UPDATE media_analysis_tasks SET status='completed',transcript_text='结果',ai_outputs_json='' WHERE id='media'")
                def mutate():
                    with db() as conn:
                        if delete:
                            conn.execute("DELETE FROM media_analysis_tasks WHERE id='media'")
                        else:
                            conn.execute("UPDATE media_analysis_tasks SET enhanced_summary='新增强结果' WHERE id='media'")
                self.handler.body = {"force": True}
                result = self.blocked_call("ai_platform.handlers.media.MediaHandlersMixin.call_media_ai_model", self.handler.handle_media_task_enhance, {"enhanced_summary": "过期增强结果"}, mutate)
                self.assertEqual(result[0], 404 if delete else 409)
                if not delete:
                    self.assertEqual(self.media()["enhanced_summary"], "新增强结果")

    def test_refresh_is_owned_by_current_user(self):
        self.handler.user_id = "another-user"
        with patch("ai_platform.handlers.media.tingwu_get_task_info") as query:
            self.assertEqual(self.handler.handle_media_task_refresh()[0], 404)
            query.assert_not_called()
        self.handler.path = "/api/documents/doc/refresh"
        with patch("ai_platform.handlers.documents.query_doc_parser_status") as query:
            self.assertEqual(self.handler.handle_document_item()[0], 404)
            query.assert_not_called()


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        TEMP.cleanup()
