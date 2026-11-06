#!/usr/bin/env python3
"""材料完整刷新隔离回归：临时SQLite和供应商替身，不访问外部服务。"""
import json
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="aimeimei-document-structure-")
os.environ["AI_PLATFORM_DATA"] = TEMP.name
from ai_platform.database import db, init_db
from ai_platform.handlers import documents


def result(layouts):
    return {"Data": {"layouts": layouts}}


def layouts(count, start=0, page=0):
    return [{"uniqueId": "layout-%s" % index, "index": index, "pageNum": page,
             "type": "paragraph", "text": "材料原句%05d。" % index}
            for index in range(start, start + count)]


class Harness(documents.DocumentHandlersMixin):
    def __init__(self, user_id="default"):
        self.server = SimpleNamespace(secrets={})
        self.user_id = user_id
        self.command, self.path = "POST", "/api/documents/doc/refresh"

    def current_user(self):
        return {"id": self.user_id}

    def json(self, value, status=200):
        return int(status), value

    def error(self, status, message, *args):
        return int(status), {"error": message}


class DocumentRefreshStructureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db({"family_password_hash": "fixture-only"})
        with db() as conn:
            conn.execute("CREATE TABLE refresh_writes(id INTEGER PRIMARY KEY,value INTEGER)")
            conn.execute("INSERT INTO refresh_writes VALUES(1,0)")

    @classmethod
    def tearDownClass(cls):
        TEMP.cleanup()

    def setUp(self):
        self.handler = Harness()
        with db() as conn:
            conn.execute("DELETE FROM document_chunks")
            conn.execute("DELETE FROM document_files")
            conn.execute("INSERT INTO document_files(id,user_id,filename,oss_key,status,parser_task_id,created_at,updated_at) VALUES('doc','default','材料.pdf','fixture/doc','processing','provider-task',0,0)")
        for name, value in (("docmind_config", {}), ("docmind_configured", True)):
            mock = patch.object(documents, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)

    def row(self):
        with db() as conn:
            return conn.execute("SELECT * FROM document_files WHERE id='doc'").fetchone()

    def chunks(self):
        with db() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM document_chunks WHERE document_id='doc' ORDER BY ordinal")]

    def refresh(self, pages, total=None, known=True):
        status = {"Data": {"Status": "success"}}
        if known:
            status["Data"]["NumberOfSuccessfulParsing"] = total
        with patch.object(documents, "query_doc_parser_status", return_value=status), \
                patch.object(documents, "get_doc_parser_result", side_effect=pages) as fetch:
            updated = self.handler.refresh_document(self.row(), retry_failed=True)
        return updated, fetch.call_args_list

    def assert_no_partial_result(self, row, expected_status="failed"):
        self.assertEqual(row["status"], expected_status)
        self.assertEqual(row["parsed_text"], "")
        self.assertEqual(row["chunk_count"], 0)
        self.assertEqual(self.chunks(), [])
        self.assertTrue(row["error_message"])

    def test_admin_fetches_all_counted_batches_and_keeps_zero_page_identifier(self):
        first, last = layouts(3000), layouts(1, start=3000, page=2)
        row, calls = self.refresh([result(first), result(last)], total="3001")
        self.assertEqual(row["status"], "completed")
        self.assertEqual(calls, [call({}, "provider-task", 0, 3000), call({}, "provider-task", 3000, 3000)])
        self.assertIn("材料原句00000。", row["parsed_text"])
        self.assertIn("材料原句03000。", row["parsed_text"])
        self.assertIn("【原始页标识：0】", row["parsed_text"])
        self.assertIn("【原始页标识：2】", row["parsed_text"])
        self.assertEqual(row["page_count"], 0)
        self.assertEqual(row["parsed_text"], "\n\n".join(chunk["content"] for chunk in self.chunks()))
        self.assertEqual(row["chunk_count"], len(self.chunks()))

    def test_string_data_and_uppercase_layout_field_are_supported(self):
        status = {"Data": json.dumps({"Status": "success", "NumberOfSuccessfulParsing": "1"})}
        response = {"Data": json.dumps({"Layouts": layouts(1)})}
        with patch.object(documents, "query_doc_parser_status", return_value=status), \
                patch.object(documents, "get_doc_parser_result", return_value=response):
            row = self.handler.refresh_document(self.row())
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["page_count"], 0)

    def test_short_counted_batch_cannot_complete_partial_document(self):
        row, calls = self.refresh([result(layouts(1))], total=2)
        self.assert_no_partial_result(row)
        self.assertEqual(len(calls), 1)
        self.assertIn("总数不一致", row["error_message"])

    def test_oversized_counted_batch_is_rejected(self):
        row, _ = self.refresh([result(layouts(2))], total=1)
        self.assert_no_partial_result(row)

    def test_duplicate_unique_id_cannot_complete(self):
        duplicate = layouts(2)
        duplicate[1]["uniqueId"] = duplicate[0]["uniqueId"]
        row, _ = self.refresh([result(duplicate)], total=2)
        self.assert_no_partial_result(row)
        self.assertIn("定位标识重复", row["error_message"])

    def test_same_index_and_page_with_different_content_is_not_assumed_duplicate(self):
        values = [{"index": 0, "pageNum": 0, "text": "左侧保留原文。"},
                  {"index": 0, "pageNum": 0, "text": "右侧另一个原文块。"}]
        row, _ = self.refresh([result(values)], total=2)
        self.assertEqual(row["status"], "completed")
        self.assertIn("左侧保留原文", row["parsed_text"])
        self.assertIn("右侧另一个原文块", row["parsed_text"])

    def test_identical_blocks_without_unique_id_in_one_batch_are_preserved(self):
        block = {"index": 0, "pageNum": 0, "text": "同一页面允许再次出现的原句。"}
        row, _ = self.refresh([result([block, dict(block)])], total=2)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["parsed_text"].count(block["text"]), 2)

    def test_identical_position_and_content_replayed_across_batches_is_rejected(self):
        block = {"index": 1, "pageNum": 0, "text": "跨批重复的版面原文。"}
        first = [{"index": 0, "pageNum": 0, "text": "首块。"}, block]
        second = [dict(block), {"index": 2, "pageNum": 0, "text": "末块。"}]
        with patch.object(documents, "STRUCTURED_LAYOUT_BATCH", 2):
            row, calls = self.refresh([result(first), result(second)], total=4)
        self.assert_no_partial_result(row)
        self.assertEqual(len(calls), 2)

    def test_replayed_full_batch_without_ids_is_rejected(self):
        batch = [{"text": "原文%s" % index} for index in range(3000)]
        row, calls = self.refresh([result(batch), result(batch)], known=False)
        self.assert_no_partial_result(row)
        self.assertEqual(len(calls), 2)
        self.assertIn("分页重复", row["error_message"])

    def test_count_above_limit_fails_before_downloading(self):
        row, calls = self.refresh([], total=12001)
        self.assert_no_partial_result(row)
        self.assertEqual(calls, [])
        self.assertIn("12000", row["error_message"])

    def test_invalid_counts_are_not_silently_treated_as_complete(self):
        for total in (-1, True, 1.5, "unknown"):
            with self.subTest(total=total):
                row, calls = self.refresh([], total=total)
                self.assert_no_partial_result(row)
                self.assertEqual(calls, [])

    def test_unknown_count_short_batch_requires_empty_confirmation(self):
        row, calls = self.refresh([result(layouts(2)), result([])], known=False)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(calls, [call({}, "provider-task", 0, 3000), call({}, "provider-task", 2, 3000)])
        self.assertEqual(row["page_count"], 0)

    def test_unknown_count_full_batch_requires_empty_confirmation(self):
        row, calls = self.refresh([result(layouts(3000)), result([])], known=False)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(calls[-1], call({}, "provider-task", 3000, 3000))

    def test_unknown_count_nonempty_after_short_batch_does_not_save_partial_result(self):
        row, calls = self.refresh([result(layouts(2)), result(layouts(1, start=2))], known=False)
        self.assert_no_partial_result(row)
        self.assertEqual(len(calls), 2)
        self.assertIn("短批后仍有内容", row["error_message"])

    def test_unknown_count_over_limit_stops_after_bounded_confirmation(self):
        with patch.object(documents, "STRUCTURED_LAYOUT_BATCH", 2), patch.object(documents, "STRUCTURED_LAYOUT_LIMIT", 8):
            pages = [result(layouts(2, start=start)) for start in (0, 2, 4, 6, 8)]
            row, calls = self.refresh(pages, known=False)
        self.assert_no_partial_result(row)
        self.assertEqual(len(calls), 5)

    def test_unknown_count_exact_limit_completes_only_after_empty_confirmation(self):
        with patch.object(documents, "STRUCTURED_LAYOUT_BATCH", 2), patch.object(documents, "STRUCTURED_LAYOUT_LIMIT", 8):
            pages = [result(layouts(2, start=start)) for start in (0, 2, 4, 6)] + [result([])]
            row, calls = self.refresh(pages, known=False)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(len(calls), 5)

    def test_invalid_layout_response_is_not_mistaken_for_empty_end_page(self):
        for response in ({}, {"Data": {}}, {"Data": {"layouts": None}}, {"Data": {"layouts": "not-a-list"}}):
            with self.subTest(response=response):
                row, _ = self.refresh([response], known=False)
                self.assert_no_partial_result(row)

    def test_download_failure_after_first_batch_remains_retryable_without_partial_save(self):
        first, last = result(layouts(3000)), result(layouts(1, start=3000))
        row, _ = self.refresh([first, TimeoutError()], total=3001)
        self.assert_no_partial_result(row, "processing")
        row, calls = self.refresh([first, last], total=3001)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["parser_task_id"], "provider-task")
        self.assertEqual(len(calls), 2)

    def test_unrepresentable_table_fails_without_saving_readable_partial_text(self):
        values = layouts(1) + [{"type": "table", "text": "对象与数字已经扁平化，无法还原单元格。", "pageNum": 0}]
        row, _ = self.refresh([result(values)], total=2)
        self.assert_no_partial_result(row)
        self.assertIn("平台未能完整保留材料结构", row["error_message"])

    def test_long_markdown_table_is_saved_as_one_complete_original_table(self):
        text = "| 对象 | 条件 |\n| --- | --- |\n" + "".join("| 项目%s | 对应条件%s |\n" % (i, i) for i in range(150))
        self.assertGreater(len(text), 1800)
        row, _ = self.refresh([result([{"type": "table", "pageNum": 0, "markdownContent": text}])], total=1)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["parsed_text"], "【原始页标识：0】\n" + text)
        self.assertEqual(len(self.chunks()), 1)

    def test_cells_table_keeps_row_column_relationship_and_raw_page_list(self):
        def cell(x, y, text):
            return {"xsc": x, "xec": x, "ysc": y, "yec": y, "layouts": [{"text": text}]}
        values = [{"type": "table", "pageNum": [0, 2], "cells": [
            cell(0, 0, "方案"), cell(1, 0, "限制"), cell(0, 1, "方案甲"), cell(1, 1, "仅室内")]}]
        row, _ = self.refresh([result(values)], total=1)
        self.assertEqual(row["status"], "completed")
        self.assertIn("【原始页标识：0、2】", row["parsed_text"])
        self.assertIn("<tr><td>方案甲</td><td>仅室内</td></tr>", row["parsed_text"])
        self.assertEqual(row["page_count"], 0)
        self.assertEqual(self.chunks()[0]["page_number"], 0)

    def test_merged_cells_take_priority_over_flat_markdown_in_saved_material(self):
        def cell(x1, y1, x2, y2, text):
            return {"xsc": x1, "xec": x2, "ysc": y1, "yec": y2, "layouts": [{"text": text}]}
        table = {"type": "table", "pageNum": 0,
                 "markdownContent": "| 总表 | |\n| --- | --- |\n| 共同项目 | 条件甲 |\n| | 条件乙 |\n",
                 "cells": [cell(0, 0, 1, 0, "总表"), cell(0, 1, 0, 2, "共同项目"),
                           cell(1, 1, 1, 1, "条件甲"), cell(1, 2, 1, 2, "条件乙")]}
        row, _ = self.refresh([result([table])], total=1)
        self.assertEqual(row["status"], "completed")
        self.assertIn('<td colspan="2">总表</td>', row["parsed_text"])
        self.assertIn('<td rowspan="2">共同项目</td>', row["parsed_text"])
        self.assertEqual(row["parsed_text"].count("共同项目"), 1)

    def test_empty_complete_result_is_not_marked_completed(self):
        row, calls = self.refresh([], total=0)
        self.assert_no_partial_result(row)
        self.assertEqual(calls, [])
        row, calls = self.refresh([result([])], known=False)
        self.assert_no_partial_result(row)
        self.assertEqual(len(calls), 1)

    def test_parsed_text_over_limit_is_rejected_not_truncated(self):
        chunk = {"content": "字" * 2_000_001, "title": "", "page": 0, "structure_status": "preserved"}
        with patch.object(documents, "document_chunks", return_value=[chunk]) as parser:
            row, _ = self.refresh([result(layouts(1))], total=1)
        self.assert_no_partial_result(row)
        self.assertIn("2000000", row["error_message"])
        self.assertEqual(parser.call_args.kwargs, {"preserve_structure": True})

    def test_parsed_text_at_limit_is_saved_in_full(self):
        text = "首" + "字" * 1_999_998 + "尾"
        chunk = {"content": text, "title": "", "page": 0, "structure_status": "preserved"}
        with patch.object(documents, "document_chunks", return_value=[chunk]):
            row, _ = self.refresh([result(layouts(1))], total=1)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["parsed_text"], text)
        self.assertEqual(self.chunks()[0]["content"], text)

    def test_other_user_keeps_original_one_batch_and_parser_arguments(self):
        with db() as conn:
            conn.execute("UPDATE document_files SET user_id='other' WHERE id='doc'")
        source = result(layouts(1))
        with patch.object(documents, "document_chunks", wraps=documents.document_chunks) as parser:
            row, calls = self.refresh([source], total=6000)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(calls, [call({}, "provider-task", 0, 3000)])
        parser.assert_called_once_with(source)
        self.assertNotIn("原始页标识", row["parsed_text"])

    def test_completed_document_is_not_refreshed_or_rewritten(self):
        with db() as conn:
            conn.execute("UPDATE document_files SET status='completed',parsed_text='既有完整材料',page_count=9,chunk_count=7 WHERE id='doc'")
        before = self.row()
        with patch.object(documents, "query_doc_parser_status") as query, patch.object(documents, "get_doc_parser_result") as fetch:
            after = self.handler.refresh_document(before, retry_failed=True)
        self.assertEqual(dict(after), dict(before))
        query.assert_not_called()
        fetch.assert_not_called()

    def test_failed_document_requires_explicit_retry(self):
        with db() as conn:
            conn.execute("UPDATE document_files SET status='failed',error_message='结构未完整' WHERE id='doc'")
        with patch.object(documents, "query_doc_parser_status") as query:
            row = self.handler.refresh_document(self.row())
        self.assertEqual(row["status"], "failed")
        query.assert_not_called()

    def blocked_fetch(self, during):
        entered, release = threading.Event(), threading.Event()
        output, errors = [], []
        snapshot = self.row()
        def fetch(*args):
            entered.set()
            if not release.wait(5):
                raise AssertionError("本地阻塞替身未及时释放")
            return result(layouts(1))
        def run():
            try:
                output.append(self.handler.refresh_document(snapshot))
            except BaseException as exc:
                errors.append(exc)
        with patch.object(documents, "query_doc_parser_status", return_value={"Data": {"Status": "success", "NumberOfSuccessfulParsing": 1}}), \
                patch.object(documents, "get_doc_parser_result", side_effect=fetch):
            worker = threading.Thread(target=run, daemon=True)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                during()
            finally:
                release.set()
                worker.join(5)
        self.assertFalse(worker.is_alive())
        if errors:
            raise errors[0]
        return output[0]

    def write_during_fetch(self):
        conn = sqlite3.connect(str(Path(TEMP.name) / "ai-platform.db"), timeout=0.2)
        try:
            with conn:
                conn.execute("UPDATE refresh_writes SET value=value+1 WHERE id=1")
        finally:
            conn.close()

    def test_external_fetch_does_not_lock_database_and_late_snapshot_cannot_overwrite(self):
        def update():
            self.write_during_fetch()
            with db() as conn:
                conn.execute("UPDATE document_files SET status='completed',parsed_text='另一次更新已保存',updated_at=99 WHERE id='doc'")
        row = self.blocked_fetch(update)
        self.assertEqual(row["status"], "completed")
        self.assertEqual(row["parsed_text"], "另一次更新已保存")
        self.assertEqual(self.chunks(), [])

    def test_document_deleted_during_download_is_not_recreated(self):
        def delete():
            self.write_during_fetch()
            with db() as conn:
                conn.execute("DELETE FROM document_files WHERE id='doc'")
        row = self.blocked_fetch(delete)
        self.assertIsNone(row)
        self.assertEqual(self.chunks(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
