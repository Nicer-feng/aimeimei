#!/usr/bin/env python3
"""文档结构保留纯函数回归；不调用供应商，不把合成输入当线上返回。"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_platform.docmind import document_chunks


def cell(x1, y1, x2, y2, text):
    return {"xsc": x1, "ysc": y1, "xec": x2, "yec": y2, "layouts": [{"text": text}]}


def plain_content(chunk):
    text = chunk["content"]
    return text.split("\n", 1)[1] if text.startswith("【原始页标识：") else text


class DocumentStructureTests(unittest.TestCase):
    def chunks(self, layouts, max_chars=1800, **kwargs):
        return document_chunks({"Data": {"layouts": layouts}}, max_chars=max_chars, preserve_structure=True, **kwargs)

    def table(self, **kwargs):
        value = {"type": "table", "pageNum": 0, "index": 0, "uniqueId": "table-a",
                 "cells": [cell(0, 0, 0, 0, "项目"), cell(1, 0, 1, 0, "规格"),
                           cell(0, 1, 0, 1, "方案甲"), cell(1, 1, 1, 1, "室内适用")]}
        value.update(kwargs)
        return value

    def test_legacy_default_snapshot_is_unchanged(self):
        layouts = [{"type": "title", "pageNum": 0, "text": "第一节"}, {"type": "text", "pageNum": 0, "text": "第一节内容"},
                   {"type": "title", "pageNum": 0, "text": "第二节"}, {"type": "text", "pageNum": 0, "text": "第二节内容"}]
        expected = [{"title": "第二节", "content": "第一节\n第一节\n\n第一节\n第一节内容", "page": 0},
                    {"title": "第二节", "content": "第二节\n第二节\n\n第二节\n第二节内容", "page": 0}]
        self.assertEqual(document_chunks({"Data": {"layouts": layouts}}, 21), expected)
        self.assertEqual(document_chunks({"Data": {"layouts": layouts}}, 21, preserve_structure=False), expected)

    def test_legacy_cells_only_behavior_unchanged(self):
        self.assertEqual(document_chunks({"Data": {"layouts": [self.table()]}}), [])

    def test_cells_only_table_is_rendered(self):
        result = self.chunks([self.table()])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["structure_status"], "preserved")
        self.assertEqual(plain_content(result[0]), "<table><tr><td>项目</td><td>规格</td></tr><tr><td>方案甲</td><td>室内适用</td></tr></table>")

    def test_cells_restore_structure_instead_of_flat_text(self):
        result = self.chunks([self.table(text="项目 规格 方案甲 室内适用")])[0]
        self.assertIn("<td>方案甲</td><td>室内适用</td>", result["content"])

    def test_merged_cells_keep_rowspan_and_colspan(self):
        cells = [cell(0, 0, 1, 0, "总表"), cell(0, 1, 0, 2, "共同项目"), cell(1, 1, 1, 1, "条件甲"), cell(1, 2, 1, 2, "条件乙")]
        result = self.chunks([self.table(cells=cells)])[0]
        self.assertIn('<td colspan="2">总表</td>', result["content"])
        self.assertIn('<td rowspan="2">共同项目</td>', result["content"])
        self.assertEqual(result["content"].count("共同项目"), 1)

    def test_cells_follow_coordinates_not_list_order(self):
        layout = self.table()
        layout["cells"].reverse()
        self.assertEqual(plain_content(self.chunks([layout])[0]), plain_content(self.chunks([self.table()])[0]))

    def test_merged_cells_take_priority_over_flattened_markdown(self):
        cells = [cell(0, 0, 0, 1, "分组"), cell(1, 0, 2, 0, "指标"),
                 cell(1, 1, 1, 1, "项目"), cell(2, 1, 2, 1, "数值")]
        text = "| 分组 | 指标 | 指标 |\n| --- | --- | --- |\n| 分组 | 项目 | 数值 |\n"
        result = self.chunks([self.table(cells=cells, markdownContent=text)])[0]
        self.assertIn('rowspan="2"', result["content"])
        self.assertIn('colspan="2"', result["content"])
        self.assertEqual(result["content"].count("分组"), 1)

    def test_invalid_merged_cells_do_not_silently_fall_back_to_flat_markdown(self):
        cells = [cell(0, 0, 0, 1, "分组"), cell(2, 0, 2, 1, "有缺格")]
        text = "| 分组 | 指标 |\n| --- | --- |\n| 分组 | 数据 |\n"
        self.assertEqual(self.chunks([self.table(cells=cells, markdownContent=text)])[0]["structure_status"], "not_representable")

    def test_cell_text_is_escaped_without_interpreting_tags(self):
        result = self.chunks([self.table(cells=[cell(0, 0, 0, 0, '<script a="b">&\n原文')])])[0]
        self.assertIn('&lt;script a=&quot;b&quot;&gt;&amp;<br>原文', result["content"])
        self.assertNotIn("<script", result["content"])

    def test_empty_explicit_cell_is_not_invented_text(self):
        value = cell(0, 0, 0, 0, "")
        value["layouts"] = []
        self.assertIn("<td></td>", self.chunks([self.table(cells=[value])])[0]["content"])

    def test_coordinate_holes_are_not_filled_by_guess(self):
        result = self.chunks([self.table(cells=[cell(0, 0, 0, 0, "甲"), cell(2, 0, 2, 0, "乙")])])[0]
        self.assertEqual(result["structure_status"], "not_representable")

    def test_overlapping_cells_are_not_silently_overwritten(self):
        result = self.chunks([self.table(cells=[cell(0, 0, 1, 0, "甲"), cell(1, 0, 1, 0, "乙")])])[0]
        self.assertEqual(result["structure_status"], "not_representable")

    def test_invalid_coordinates_are_not_guessed(self):
        for change in ({"xsc": None}, {"xsc": "0"}, {"xsc": True}, {"xsc": -1}, {"xec": -1}, {"xec": 200000}):
            with self.subTest(change=change):
                value = cell(0, 0, 0, 0, "原文")
                value.update(change)
                self.assertEqual(self.chunks([self.table(cells=[value])])[0]["structure_status"], "not_representable")

    def test_unknown_cell_text_schema_is_not_silently_empty(self):
        value = {"xsc": 0, "ysc": 0, "xec": 0, "yec": 0, "text": "不能丢掉"}
        self.assertEqual(self.chunks([self.table(cells=[value])])[0]["structure_status"], "not_representable")
        value["layouts"] = []
        self.assertEqual(self.chunks([self.table(cells=[value])])[0]["structure_status"], "not_representable")

    def test_nested_table_not_flattened_into_cell_text(self):
        value = cell(0, 0, 0, 0, "不能当纯文本")
        value["layouts"][0]["type"] = "table"
        self.assertEqual(self.chunks([self.table(cells=[value])])[0]["structure_status"], "not_representable")

    def test_existing_markdown_table_preferred_and_unchanged(self):
        text = "| 项目 | 规格 |\n| --- | --- |\n| 甲 | 室内 |\n"
        result = self.chunks([self.table(markdownContent=text, cells=[])])[0]
        self.assertEqual(plain_content(result), text)
        self.assertEqual(result["structure_status"], "preserved")

    def test_existing_html_table_preferred_and_unchanged(self):
        text = '<table class="original"><tr><td rowspan="2">原文</td></tr><tr></tr></table>\n'
        self.assertEqual(plain_content(self.chunks([self.table(markdownContent=text)])[0]), text)

    def test_existing_html_in_text_or_llm_result_is_preserved(self):
        text = "<table><tr><td>已有解析结果</td></tr></table>"
        for field in ("text", "llmResult"):
            with self.subTest(field=field):
                result = self.chunks([self.table(**{field: text, "cells": []})])[0]
                self.assertEqual(plain_content(result), text)

    def test_incomplete_html_not_silently_flattened(self):
        result = self.chunks([{"type": "text", "markdownContent": "<table><tr><td>未闭合", "pageNum": 0}])[0]
        self.assertEqual(result["structure_status"], "not_representable")

    def test_table_plain_blocks_are_not_claimed_complete(self):
        result = self.chunks([{"type": "table", "blocks": [{"text": "项目甲 参数甲 项目乙 参数乙"}]}])[0]
        self.assertEqual(result["structure_status"], "not_representable")
        self.assertIn("未按纯文本猜测归属", result["content"])

    def test_long_markdown_table_remains_one_atomic_block(self):
        text = "| 项目 | 规格 |\n| --- | --- |\n" + "| 甲 | 原始内容 |\n" * 2000
        result = self.chunks([self.table(markdownContent=text)])
        self.assertEqual(len(result), 1)
        self.assertGreater(len(result[0]["content"]), 16000)
        self.assertEqual(plain_content(result[0]), text)

    def test_long_html_table_remains_one_atomic_block(self):
        text = "<table>" + "<tr><td>原文</td></tr>" * 200 + "</table>"
        result = self.chunks([self.table(markdownContent=text)], max_chars=20)
        self.assertEqual(len(result), 1)
        self.assertEqual(plain_content(result[0]), text)

    def test_table_does_not_merge_with_adjacent_paragraphs(self):
        result = self.chunks([{"type": "text", "pageNum": 0, "text": "表前原文"}, self.table(), {"type": "text", "pageNum": 0, "text": "表后原文"}])
        self.assertEqual(len(result), 3)
        self.assertEqual(plain_content(result[0]), "表前原文")
        self.assertEqual(plain_content(result[2]), "表后原文")

    def test_page_switch_flushes_and_preserves_raw_zero(self):
        result = self.chunks([{"type": "text", "pageNum": 0, "text": "首页原文"}, {"type": "text", "pageNum": 1, "text": "下一页原文"}])
        self.assertEqual([x["pages"] for x in result], [[0], [1]])
        self.assertIn("原始页标识：0", result[0]["content"])
        self.assertEqual([x["page"] for x in result], [0, 1])

    def test_multi_page_table_retains_all_explicit_raw_page_ids(self):
        result = self.chunks([self.table(pageNum=[2, 1, 2])])[0]
        self.assertEqual(result["pages"], [1, 2])
        self.assertIn("原始页标识：1、2", result["content"])

    def test_unknown_page_does_not_become_known_zero(self):
        result = self.chunks([{"type": "text", "text": "无页标识"}])[0]
        self.assertEqual(result["pages"], [])
        self.assertNotIn("原始页标识", result["content"])

    def test_heading_switch_flushes_before_metadata_changes(self):
        result = self.chunks([{"type": "title", "pageNum": 0, "text": "第一节"}, {"type": "text", "pageNum": 0, "text": "段甲"},
                              {"type": "title", "pageNum": 0, "text": "第二节"}, {"type": "text", "pageNum": 0, "text": "段乙"}])
        self.assertEqual([x["title"] for x in result], ["第一节", "第二节"])
        self.assertEqual(plain_content(result[0]), "第一节\n\n段甲")
        self.assertEqual(plain_content(result[1]), "第二节\n\n段乙")

    def test_previous_heading_not_injected_into_next_page(self):
        result = self.chunks([{"type": "title", "pageNum": 0, "text": "旧页标题"}, {"type": "text", "pageNum": 1, "text": "新页原文"}])
        self.assertEqual(result[1]["title"], "")
        self.assertEqual(plain_content(result[1]), "新页原文")

    def test_valid_unique_official_indices_control_order(self):
        result = self.chunks([{"type": "text", "text": "后文", "index": 8, "pageNum": 0}, {"type": "text", "text": "前文", "index": 3, "pageNum": 0}])
        self.assertEqual(plain_content(result[0]), "前文\n\n后文")
        self.assertEqual(result[0]["layout_indices"], [3, 8])

    def test_unique_indices_across_pages_do_not_move_later_page_before_earlier_page(self):
        result = self.chunks([{"type": "text", "text": "前页内容", "index": 5, "pageNum": 0},
                              {"type": "text", "text": "后页后段", "index": 1, "pageNum": 1},
                              {"type": "text", "text": "后页前段", "index": 0, "pageNum": 1}])
        self.assertEqual([item["pages"] for item in result], [[0], [1]])
        self.assertEqual([plain_content(item) for item in result], ["前页内容", "后页前段\n\n后页后段"])

    def test_unique_indices_with_unknown_pages_preserve_provider_order(self):
        result = self.chunks([{"type": "text", "text": "先返回", "index": 8}, {"type": "text", "text": "后返回", "index": 3}])
        self.assertEqual(plain_content(result[0]), "先返回\n\n后返回")

    def test_same_page_in_non_contiguous_groups_is_not_globally_reordered(self):
        result = self.chunks([{"type": "text", "text": "先段", "index": 5, "pageNum": 0},
                              {"type": "text", "text": "中段", "index": 0, "pageNum": 1},
                              {"type": "text", "text": "再次出现的页段", "index": 1, "pageNum": 0}])
        self.assertEqual([item["pages"] for item in result], [[0], [1], [0]])
        self.assertEqual([plain_content(item) for item in result], ["先段", "中段", "再次出现的页段"])

    def test_missing_index_preserves_provider_list_order(self):
        result = self.chunks([{"type": "text", "text": "先返回", "index": 8, "pageNum": 0}, {"type": "text", "text": "无编号", "pageNum": 0}, {"type": "text", "text": "后返回", "index": 3, "pageNum": 0}])
        self.assertEqual(plain_content(result[0]), "先返回\n\n无编号\n\n后返回")

    def test_duplicate_index_preserves_provider_order(self):
        result = self.chunks([{"type": "text", "text": "先", "index": 3, "pageNum": 0}, {"type": "text", "text": "后", "index": 3, "pageNum": 0}])
        self.assertEqual(plain_content(result[0]), "先\n\n后")

    def test_xy_coordinates_never_determine_reading_order(self):
        result = self.chunks([{"type": "text", "text": "供应商先返回", "pos": [{"x": 200, "y": 200}]},
                              {"type": "text", "text": "供应商后返回", "pos": [{"x": 0, "y": 0}]}])
        self.assertEqual(plain_content(result[0]), "供应商先返回\n\n供应商后返回")

    def test_plain_long_text_uses_natural_boundaries_without_loss(self):
        text = "第一段。\n第二段仍为原文。\n" + "长内容" * 30
        result = self.chunks([{"type": "text", "text": text}], max_chars=14)
        self.assertEqual("".join(plain_content(x) for x in result), text)
        self.assertTrue(all(len(plain_content(x)) <= 14 for x in result))
        self.assertEqual(plain_content(result[0]), "第一段。\n第二段仍为原文。\n")

    def test_blocks_fallback_preserves_text_fragments_in_order(self):
        result = self.chunks([{"type": "text", "blocks": [{"text": "同一"}, {"text": "句子"}]}])[0]
        self.assertEqual(plain_content(result), "同一句子")

    def test_multicolumn_blocks_are_not_guessed_into_reading_order(self):
        result = self.chunks([{"type": "multicolumn", "blocks": [{"text": "左右栏未说明"}]}])[0]
        self.assertEqual(result["structure_status"], "not_representable")

    def test_raw_data_string_is_supported(self):
        result = document_chunks({"Data": json.dumps({"layouts": [self.table()]})}, preserve_structure=True)
        self.assertEqual(result[0]["structure_status"], "preserved")

    def test_invalid_layout_reported_not_silently_skipped(self):
        self.assertEqual(self.chunks([None])[0]["structure_status"], "not_representable")

    def test_empty_material_is_empty_not_invented(self):
        self.assertEqual(self.chunks([]), [])

    def test_input_not_mutated(self):
        layouts = [self.table()]
        before = deepcopy(layouts)
        self.chunks(layouts)
        self.assertEqual(layouts, before)

    def test_invalid_chunk_limit_rejected_in_opt_in_only(self):
        for value in (0, -1, True, "1800"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.chunks([], max_chars=value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
