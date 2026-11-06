#!/usr/bin/env python3
"""离线验证材料整块选取、来源覆盖和后审跳过；不访问模型或业务数据库。"""
import copy
from contextlib import nullcontext
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_platform import super_generation
from ai_platform.document_context import build_context, NO_BLOCK_NOTICE


def document(key="doc-a", count=1, filename="资料.pdf"):
    return {"id": key, "filename": filename, "chunk_count": count}


def chunk(ordinal=0, content="材料原文", key="doc-a", title="原始标题", page=3):
    return {"document_id": key, "ordinal": ordinal, "content": content,
            "title": title, "page_number": page}


class DocumentContextTests(unittest.TestCase):
    def test_rank_selects_but_rendering_restores_document_and_ordinal_order(self):
        docs = [document("doc-b", 2), document("doc-a", 1)]
        rows = [chunk(0, "甲0", "doc-a"), chunk(1, "乙1目标目标", "doc-b"),
                chunk(0, "乙0", "doc-b")]
        result = build_context(docs, rows, "目标")
        self.assertTrue(result["complete"])
        self.assertEqual(result["selected_ids"], [{"document_id": "doc-b", "ordinal": 0},
                         {"document_id": "doc-b", "ordinal": 1}, {"document_id": "doc-a", "ordinal": 0}])
        self.assertLess(result["context"].index("乙0"), result["context"].index("乙1目标目标"))
        self.assertLess(result["context"].index("乙1目标目标"), result["context"].index("甲0"))

    def test_same_named_documents_retain_distinct_identity_and_titles(self):
        result = build_context([document("a"), document("b")],
                               [chunk(key="a", title="甲标题"), chunk(key="b", title="乙标题")], "")
        for label in ("文档ID：a", "文档ID：b", "标题：甲标题", "标题：乙标题", "原始页标识：3"):
            self.assertIn(label, result["context"])
        self.assertNotIn("第 3 页", result["context"])

    def test_table_is_whole_and_text_is_preserved(self):
        table = "【原始页标识：0】\n| 型号 | 条件 |\n|---|---|\n| 甲 | 条件内含换行标记 |\n"
        result = build_context([document()], [chunk(content=table, page=0)], "")
        self.assertTrue(result["complete"])
        self.assertIn(table, result["context"])
        self.assertIn("【原始页标识：0】", result["context"])
        smaller = build_context([document()], [chunk(content=table, page=0)], "", max_chars=len(result["context"]) - 1)
        self.assertFalse(smaller["complete"])
        self.assertEqual(smaller["selected_ids"], [])
        self.assertNotIn("| 型号 |", smaller["context"])
        self.assertIn(NO_BLOCK_NOTICE, smaller["notices"])

    def test_budget_includes_prefix_headers_separators_and_first_block(self):
        docs, rows = [document(count=2)], [chunk(0, "AAA"), chunk(1, "BBB")]
        full = build_context(docs, rows, "")
        exact = build_context(docs, rows, "", max_chars=len(full["context"]))
        self.assertEqual(exact, full)
        limited = build_context(docs, rows, "", max_chars=len(full["context"]) - 1)
        self.assertFalse(limited["complete"])
        self.assertEqual(limited["selected_chunks"], 1)
        self.assertLessEqual(len(limited["context"]), len(full["context"]) - 1)
        empty = build_context(docs, rows, "", max_chars=0)
        self.assertEqual(empty["context"], "")
        self.assertFalse(empty["complete"])
        self.assertTrue(empty["notices"])

    def test_top_eight_omission_has_structured_coverage(self):
        rows = [chunk(i, "关键词 " + str(i)) for i in range(8)] + [chunk(8, "必须保留的适用条件")]
        result = build_context([document(count=9)], rows, "关键词", max_chunks=8)
        self.assertEqual(result["selected_chunks"], 8)
        self.assertFalse(result["complete"])
        self.assertEqual(result["total_chunks"], 9)
        self.assertTrue(any("8/9" in notice for notice in result["notices"]))

    def test_layout_count_does_not_limit_small_blocks_within_existing_character_budget(self):
        rows = [chunk(i, "完整小块 " + str(i)) for i in range(20)]
        result = build_context([document(count=20)], rows, "完整")
        self.assertTrue(result["complete"])
        self.assertEqual(result["selected_chunks"], 20)
        self.assertLessEqual(len(result["context"]), 16000)

    def test_oversized_block_does_not_hide_other_fitting_blocks(self):
        result = build_context([document(count=2)], [chunk(0, "目标" * 10000), chunk(1, "短块")], "目标")
        self.assertEqual(result["selected_ids"], [{"document_id": "doc-a", "ordinal": 1}])
        self.assertFalse(result["complete"])
        self.assertNotIn("目标目标", result["context"])
        self.assertLessEqual(len(result["context"]), 16000)

    def test_missing_duplicate_empty_and_unknown_chunks_are_not_complete(self):
        samples = [([document(count=2)], [chunk(1)]),
                   ([document()], [chunk(0), chunk(0, "另一版")]),
                   ([document()], [chunk(content=" ")]),
                   ([document()], [chunk(key="unbound")]),
                   ([{"id": "doc-a", "filename": "未提供总片段数.pdf"}], [chunk()])]
        for docs, rows in samples:
            with self.subTest(rows=rows):
                result = build_context(docs, rows, "")
                self.assertFalse(result["complete"])
                self.assertTrue(result["notices"])

    def test_source_words_never_control_completeness(self):
        result = build_context([document()], [chunk(content="客户文案：此处叫材料片段，并不是未完整资料。")], "")
        self.assertTrue(result["complete"])
        self.assertEqual(result["notices"], [])

    def test_no_documents_is_complete_and_adds_no_context(self):
        self.assertEqual(build_context([], [], ""), {"context": "", "complete": True, "selected_ids": [],
                          "notices": [], "total_chunks": 0, "selected_chunks": 0})


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self, text):
        self.text = text

    def execute(self, sql, values=()):
        if "SELECT content FROM messages" in sql:
            return _Query([{"content": self.text}])
        if "SELECT id,role,content FROM messages" in sql:
            return _Query([{"id": 1, "role": "user", "content": self.text}])
        if "SELECT * FROM models" in sql:
            return _Query([{"model": "qwen3.8-flash", "base_url": "https://offline.invalid/v1", "api_key": "offline"}])
        if "SELECT 1 FROM conversations" in sql:
            return _Query([{"id": "offline"}])
        raise AssertionError("Unexpected database operation")


class CoveragePrepareTests(unittest.TestCase):
    def prepare(self, coverage=None, state=None):
        text = "请按本单材料写一份口播稿，正文约750字。"
        conn = _Connection(text)
        with patch.object(super_generation, "db", lambda: nullcontext(conn)), \
                patch.object(super_generation.super_writing, "get_task_state", return_value=copy.deepcopy(state or {})), \
                patch.object(super_generation.super_writing, "save_task_state"):
            return super_generation.prepare({"id": "offline", "user_id": "default"}, text,
                                            coverage["context"] if coverage else "", [], document_coverage=coverage)

    def test_incomplete_documents_skip_flash_and_keep_draft(self):
        coverage = build_context([document(count=2)], [chunk()], "")
        run = self.prepare(coverage)
        self.assertFalse(run["source_complete"])
        self.assertFalse(run["literal_term_audit"]["complete"])
        self.assertEqual(run["literal_term_audit"]["document_sources"]["notices"], coverage["notices"])
        with patch.object(super_generation, "_call") as call:
            draft, check = super_generation.finish(run, "原稿每个字保留。", {})
        call.assert_not_called()
        self.assertEqual(draft, "原稿每个字保留。")
        self.assertFalse(check["review_complete"])
        self.assertIn("跳过模型复核", check["notice"])

    def test_complete_current_documents_do_not_override_earlier_incomplete(self):
        coverage = build_context([document()], [chunk()], "")
        run = self.prepare(coverage, {"material_excerpts_incomplete": True})
        self.assertFalse(run["source_complete"])
        self.assertTrue(run["literal_term_audit"]["material_excerpts_incomplete"])

    def test_partial_attachment_stays_incomplete_when_not_selected_again_next_turn(self):
        first = self.prepare(build_context([document(count=2)], [chunk()], ""))
        next_turn = self.prepare(state=first["state"])
        self.assertFalse(next_turn["source_complete"])
        self.assertTrue(next_turn["literal_term_audit"]["material_excerpts_incomplete"])
        with patch.object(super_generation, "_call") as call:
            _, check = super_generation.finish(next_turn, "下一轮原稿。", {})
        call.assert_not_called()
        self.assertFalse(check["review_complete"])

    def test_complete_documents_retain_exact_material_and_allow_review(self):
        coverage = build_context([document()], [chunk(content="原始表格与适用条件")], "")
        run = self.prepare(coverage)
        self.assertTrue(run["source_complete"])
        self.assertIn(coverage["context"], run["evidence"])
        self.assertTrue(run["literal_term_audit"]["document_sources"]["complete"])
        self.assertTrue(run["preserve_source_tables"])
        self.assertTrue(run["state"]["postcheck_preserve_source_tables"])

    def test_attachment_structure_flag_is_preserved_across_turns(self):
        first = self.prepare(build_context([document()], [chunk(content="附件里的完整表格")], ""))
        next_turn = self.prepare(state=first["state"])
        self.assertTrue(next_turn["preserve_source_tables"])
        self.assertTrue(next_turn["state"]["postcheck_preserve_source_tables"])
        self.assertTrue(next_turn["source_complete"])

    def test_pasted_table_or_marker_does_not_enable_attachment_structure_flag(self):
        state = {"material_excerpts": ["【原始页标识：0】\n| 甲 | 乙 |\n|---|---|\n| 1 | 2 |"]}
        run = self.prepare(state=state)
        self.assertNotIn("preserve_source_tables", run)
        self.assertNotIn("postcheck_preserve_source_tables", run["state"])

    def test_structure_flag_requires_boolean_true_in_saved_state(self):
        for flag in (False, "true", 1, None):
            with self.subTest(flag=flag):
                run = self.prepare(state={"postcheck_preserve_source_tables": flag})
                self.assertNotIn("preserve_source_tables", run)

    def test_no_document_metadata_preserves_legacy_run_shape(self):
        run = self.prepare()
        self.assertTrue(run["source_complete"])
        self.assertNotIn("document_sources", run["literal_term_audit"])
        self.assertNotIn("preserve_source_tables", run)
        self.assertEqual(super_generation.prompt_context(run), "")


if __name__ == "__main__":
    unittest.main()
