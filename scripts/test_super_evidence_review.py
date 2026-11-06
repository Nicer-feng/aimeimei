#!/usr/bin/env python3
"""编号审核的纯合同回归；人工构造响应不证明模型语义能力。"""
import sys
import unittest
import importlib.util
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_platform import super_evidence_review as review


class EvidenceReviewTests(unittest.TestCase):
    def setUp(self):
        self.source = "启禾绘画笔累计交付十二万盒。\n\n每盒二十四支。"
        self.draft = "十二万位用户选择了它。\n每盒二十四支。"
        self.packet = review.build_packet(self.source, self.draft)

    def response(self, kind="conflict", refs=None, difference="交付盒数没有与用户人数建立等价关系。"):
        ids = [unit["id"] for unit in self.packet["draft_units"]]
        return {"checks": [[did, "problem" if index == 0 else "supported"] for index, did in enumerate(ids)],
                "issues": [{"d": ids[0], "kind": kind, "s": ["S0001"] if refs is None else refs,
                            "difference": difference}]}

    def decode(self, value=None, **kwargs):
        return review.decode_review(value if value is not None else self.response(), self.packet, **kwargs)

    def test_original_unicode_and_whitespace_reconstruct_exactly(self):
        source = "\n  使用说明：\r\n规格为12.5毫升。\n\n价格 3.99 元；不要改原文！\t"
        draft = "  标题：小灯\n正文：\n测试完毕。\n\n然后出发！  "
        packet = review.build_packet(source, draft)
        for text, field in ((source, "source_units"), (draft, "draft_units")):
            self.assertEqual("".join(unit["text"] for unit in packet[field]), text)
            for unit in packet[field]:
                self.assertEqual(unit["text"], text[unit["start"]:unit["end"]])

    def test_long_unpunctuated_text_is_losslessly_sliced(self):
        packet = review.build_packet("材" * 1800, "稿" * 1100)
        self.assertEqual("".join(x["text"] for x in packet["source_units"]), "材" * 1800)
        self.assertEqual("".join(x["text"] for x in packet["draft_units"]), "稿" * 1100)
        self.assertLessEqual(max(len(x["text"]) for x in packet["source_units"]), 800)
        self.assertLessEqual(max(len(x["text"]) for x in packet["draft_units"]), 400)

    def test_long_html_table_is_one_source_unit(self):
        table = '<table><tr><td rowspan="2">分组</td><td colspan="2">指标</td></tr>' + '<tr><td>原文。</td><td>保留关系</td></tr>' * 80 + '</table>'
        packet = review.build_packet("前言。\n" + table + "\n结尾。", "原稿。", preserve_source_tables=True)
        matches = [unit for unit in packet["source_units"] if unit["text"] == table]
        self.assertEqual(len(matches), 1)
        self.assertGreater(len(matches[0]["text"]), 800)
        self.assertTrue(packet["complete"])

    def test_nested_html_table_keeps_outer_range_complete(self):
        table = '<TABLE data-note="a>b"><tr><td>外表<table><tr><td>内表。' + '内容' * 500 + '</td></tr></table>外表结束</td></tr></TABLE>'
        packet = review.build_packet("前文\r\n" + table + "\r\n后文", "原稿。", preserve_source_tables=True)
        self.assertEqual([x["text"] for x in packet["source_units"] if x["text"].startswith("<TABLE")], [table])

    def test_html_table_inside_comment_is_not_an_actual_table(self):
        source = "<!-- <table>" + "内容" * 500 + "</table> -->"
        packet = review.build_packet(source, "原稿。", preserve_source_tables=True)
        self.assertLessEqual(max(len(unit["text"]) for unit in packet["source_units"]), 800)

    def test_unclosed_html_table_is_not_guessed_complete(self):
        source = "<table><tr><td>" + "内容" * 500
        packet = review.build_packet(source, "原稿。", preserve_source_tables=True)
        self.assertEqual("".join(x["text"] for x in packet["source_units"]), source)
        self.assertLessEqual(max(len(unit["text"]) for unit in packet["source_units"]), 800)

    def test_long_markdown_table_keeps_header_and_all_rows(self):
        table = "| 项目 | 规格 |\n| :--- | ---: |\n" + "| 原文。 | 原始数据 |\n" * 100
        packet = review.build_packet("前言\n\n" + table + "\n后文", "原稿。", preserve_source_tables=True)
        self.assertEqual([x["text"] for x in packet["source_units"] if "| :--- | ---: |" in x["text"]], [table])

    def test_separate_tables_remain_separate_source_units(self):
        first = "| 左 | 右 |\n| --- | --- |\n| 甲 | 乙 |\n"
        second = "<table><tr><td>另表</td></tr></table>"
        packet = review.build_packet(first + "\n说明\n" + second, "原稿。", preserve_source_tables=True)
        self.assertIn(first, [x["text"] for x in packet["source_units"]])
        self.assertIn(second, [x["text"] for x in packet["source_units"]])

    def test_table_source_offsets_reconstruct_without_any_change(self):
        table = "| 项目 | 内容 |\r\n| --- | --- |\r\n| 甲 | 乙 |\r\n"
        source = "  \n前文\r\n" + table + "\n<table><tr><td>另表</td></tr></table> \t"
        packet = review.build_packet(source, "正文。", preserve_source_tables=True)
        self.assertEqual("".join(x["text"] for x in packet["source_units"]), source)
        self.assertEqual(len(review._index_units(packet["source_units"], "S", len(source))), len(packet["source_units"]))
        for unit in packet["source_units"]:
            self.assertEqual(unit["text"], source[unit["start"]:unit["end"]])

    def test_atomic_table_does_not_bypass_total_source_budget(self):
        table = "<table><tr><td>" + "材" * review.MAX_SOURCE_CHARS + "</td></tr></table>"
        packet = review.build_packet(table, "原稿。", preserve_source_tables=True)
        self.assertFalse(packet["complete"])
        self.assertEqual(packet["source_units"][0]["text"], table)

    def test_source_tables_do_not_change_draft_segmentation(self):
        draft = "<table>" + "正文。" * 100 + "</table>"
        packet = review.build_packet("<table><tr><td>材料</td></tr></table>", draft, preserve_source_tables=True)
        self.assertEqual(packet["draft_units"], review._units(draft, "D", 400))

    def test_table_preservation_is_explicit_and_legacy_default_unchanged(self):
        table = "<table><tr><td>" + "材料" * 500 + "</td></tr></table>"
        legacy = review.build_packet(table, "原稿。")
        structured = review.build_packet(table, "原稿。", preserve_source_tables=True)
        self.assertGreater(len(legacy["source_units"]), 1)
        self.assertEqual(len(structured["source_units"]), 1)

    def test_opt_in_plain_source_keeps_legacy_units(self):
        for source in ("纯文字。\n\n第二段。", " ", "没有标点" * 400, "小于号<不是标签。\r\n另段。", "<![无法识别的声明]>"):
            with self.subTest(source=source[:20]):
                self.assertEqual(review.build_packet(source, "原稿。", preserve_source_tables=True),
                                 review.build_packet(source, "原稿。"))

    @unittest.skipUnless(os.environ.get("MEIMEI_REAL_REVIEW_CASES") and os.environ.get("MEIMEI_EVIDENCE_BASELINE"),
                         "真实原稿与冻结基线由隔离验证环境提供，不将客户原文提交到代码库")
    def test_frozen_four_original_packets_are_field_for_field_unchanged(self):
        spec = importlib.util.spec_from_file_location("frozen_evidence_baseline", os.environ["MEIMEI_EVIDENCE_BASELINE"])
        baseline = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(baseline)
        cases = json.loads(Path(os.environ["MEIMEI_REAL_REVIEW_CASES"]).read_text())
        cases = [item for item in cases if item.get("group") == "primary"]
        self.assertEqual(len(cases), 4)
        self.assertEqual(review.REVIEW_INSTRUCTION, baseline.REVIEW_INSTRUCTION)
        for item in cases:
            with self.subTest(case=item["label"]):
                self.assertEqual(review.build_packet(item["source"], item["draft"]),
                                 baseline.build_packet(item["source"], item["draft"]))

    def test_over_source_chars_is_explicit_without_truncation(self):
        source = "材" * (review.MAX_SOURCE_CHARS + 1)
        packet = review.build_packet(source, "成稿。")
        self.assertFalse(packet["complete"])
        self.assertEqual("".join(x["text"] for x in packet["source_units"]), source)

    def test_over_draft_chars_is_explicit_without_truncation(self):
        draft = "稿" * (review.MAX_DRAFT_CHARS + 1)
        packet = review.build_packet("原始材料。", draft)
        self.assertFalse(packet["complete"])
        self.assertEqual("".join(x["text"] for x in packet["draft_units"]), draft)

    def test_source_unit_limit_is_explicit(self):
        packet = review.build_packet("材。\n\n" * 401, "稿。")
        self.assertEqual(len(packet["source_units"]), 401)
        self.assertFalse(packet["complete"])

    def test_draft_unit_limit_is_explicit(self):
        packet = review.build_packet("材。", "稿。" * 81)
        self.assertEqual(len(packet["draft_units"]), 81)
        self.assertFalse(packet["complete"])

    def test_short_source_lines_are_coalesced_without_summarizing(self):
        source = "颜色：蓝色\n容量：两升\n适用场景：室内\n\n新一段。"
        packet = review.build_packet(source, "容量两升。")
        self.assertEqual(len(packet["source_units"]), 2)
        self.assertEqual("".join(unit["text"] for unit in packet["source_units"]), source)
        self.assertIn("颜色：蓝色\n容量：两升", packet["source_units"][0]["text"])

    def test_empty_or_whitespace_material_is_incomplete(self):
        for source, draft in (("", "稿。"), ("材料。", ""), (" \n", "稿。")):
            self.assertFalse(review.build_packet(source, draft)["complete"])

    def test_nontext_input_is_rejected(self):
        with self.assertRaises(TypeError):
            review.build_packet({}, "稿件")

    def test_conflict_uses_original_ids_not_model_copied_quotes(self):
        result = self.decode()
        issue = result["issues"][0]
        self.assertEqual(issue["quote"], "十二万位用户选择了它。")
        self.assertEqual(issue["source_quote"], "启禾绘画笔累计交付十二万盒。")
        self.assertTrue(result["review_complete"])
        self.assertFalse(issue["grounded"])
        self.assertTrue(issue["citation_verified"])

    def test_discontinuous_sources_are_restored_without_fabricated_join(self):
        result = self.decode(self.response(refs=["S0002", "S0001"]))
        self.assertEqual(result["issues"][0]["source_ids"], ["S0001", "S0002"])
        self.assertIn("每盒二十四支。", result["issues"][0]["evidence"])
        self.assertTrue(result["review_complete"])

    def test_missing_condition_requires_source(self):
        self.packet = review.build_packet("首次预约者须在前一天申请且未使用，可免费取消一次。", "预约后可以免费取消。")
        result = self.decode(self.response(kind="missing_condition", difference="取消权益未说明申请截止、未使用和次数条件。"))
        self.assertEqual(len(result["issues"]), 1)
        self.assertFalse(self.decode(self.response(kind="missing_condition", refs=[]))["review_complete"])

    def test_added_endorsement_can_have_no_positive_source(self):
        self.packet = review.build_packet("面粉供应多家餐饮门店，不要编造人物体验。", "厨师回家给孩子做早餐也只认这款面粉。")
        result = self.decode(self.response(kind="added_claim", refs=[], difference="门店供应未提供厨师家庭自用背书。"))
        issue = result["issues"][0]
        self.assertTrue(result["review_complete"])
        self.assertEqual(issue["source_quote"], "")
        self.assertEqual(issue["evidence_status"], "not_in_material")
        self.assertFalse(issue["grounded"])
        self.assertIn("不代表现实虚假", issue["verification"])

    def test_added_numeric_and_time_claims_can_reference_nearest_material(self):
        for source, draft in (("感应灯经过低温启动测试。", "零下三十二摄氏度依然能正常启动。"),
                              ("清洁泡沫帮助软化油污。", "两秒彻底溶解油污。")):
            self.packet = review.build_packet(source, draft)
            result = self.decode(self.response(kind="added_claim", difference="材料未提供该具体参数或效果承诺。"))
            self.assertEqual(len(result["issues"]), 1)
            self.assertFalse(result["issues"][0]["grounded"])

    def test_incomplete_source_cannot_claim_absence(self):
        result = self.decode(self.response(kind="added_claim", refs=[]), source_complete=False)
        self.assertEqual(result["issues"], [])
        self.assertFalse(result["review_complete"])

    def test_incomplete_source_cannot_use_outdated_positive_evidence(self):
        result = self.decode(source_complete=False)
        self.assertEqual(result["issues"], [])
        self.assertTrue(result["review_unverified"])

    def test_packet_overflow_cannot_pass(self):
        self.packet["complete"] = False
        self.assertFalse(self.decode()["review_complete"])

    def test_conflict_without_source_is_not_accepted(self):
        self.assertEqual(self.decode(self.response(refs=[]))["issues"], [])

    def test_unknown_source_id_is_rejected(self):
        self.assertEqual(self.decode(self.response(refs=["S9999"]))["issues"], [])

    def test_duplicate_source_ids_are_rejected(self):
        self.assertFalse(self.decode(self.response(refs=["S0001", "S0001"]))["review_complete"])

    def test_unknown_draft_id_is_rejected(self):
        value = self.response()
        value["issues"][0]["d"] = "D9999"
        self.assertEqual(self.decode(value)["issues"], [])

    def test_source_id_is_not_accepted_as_draft_id(self):
        value = self.response()
        value["issues"][0]["d"] = "S0001"
        self.assertFalse(self.decode(value)["review_complete"])

    def test_duplicate_draft_text_can_be_located_by_different_ids(self):
        self.packet = review.build_packet("产品无人物体验资料。", "厨师家庭自用。厨师家庭自用。")
        value = self.response(kind="added_claim", refs=[])
        result = self.decode(value)
        self.assertEqual(result["issues"][0]["draft_id"], "D0001")
        self.assertTrue(result["review_complete"])

    def test_missing_coverage_does_not_pass(self):
        value = self.response()
        value["checks"].pop()
        result = self.decode(value)
        self.assertFalse(result["review_complete"])
        self.assertEqual(result["coverage"]["missing_ids"], ["D0002"])
        self.assertEqual(len(result["issues"]), 1)

    def test_bad_reference_does_not_discard_other_located_issue(self):
        value = self.response()
        value["checks"][1][1] = "problem"
        value["issues"].append({"d": "D0002", "kind": "conflict", "s": ["S9999"],
                                "difference": "另一项引用无效。"})
        result = self.decode(value)
        self.assertFalse(result["review_complete"])
        self.assertEqual([item["draft_id"] for item in result["issues"]], ["D0001"])

    def test_factual_cover_line_can_be_reported_by_id(self):
        self.packet = review.build_packet("设备供应研究机构。", "封面标题：工程师在家里也都用这台设备。")
        result = self.decode(self.response(kind="added_claim", refs=[], difference="机构供应未提供工程师家庭自用依据。"))
        self.assertTrue(result["review_complete"])
        self.assertEqual(len(result["issues"]), 1)

    def test_duplicate_coverage_cannot_silently_override(self):
        value = self.response()
        value["checks"].append(["D0001", "supported"])
        result = self.decode(value)
        self.assertFalse(result["review_complete"])
        self.assertEqual(result["issues"], [])

    def test_problem_status_requires_an_issue(self):
        value = self.response()
        value["issues"] = []
        self.assertFalse(self.decode(value)["review_complete"])

    def test_supported_status_cannot_carry_an_issue(self):
        value = self.response()
        value["checks"][0][1] = "supported"
        self.assertEqual(self.decode(value)["issues"], [])

    def test_uncertain_status_is_not_a_confirmed_problem(self):
        value = self.response()
        value["checks"][0][1] = "uncertain"
        value["issues"] = []
        result = self.decode(value)
        self.assertFalse(result["review_complete"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["coverage"]["uncertain_units"], 1)

    def test_supported_paraphrase_and_nonfactual_metadata_can_complete(self):
        self.packet = review.build_packet("产品获得年度设计奖。测得容积12.4升。", "标题：生活新选择。它获设计奖，容积约十二升。")
        value = {"checks": [[unit["id"], "nonfactual" if i == 0 else "supported"]
                            for i, unit in enumerate(self.packet["draft_units"])], "issues": []}
        self.assertTrue(self.decode(value)["review_complete"])

    def test_invalid_checks_rows_mark_incomplete(self):
        for invalid in (["D0001"], ["D0001", "ok"], [True, "supported"], {"D0001": "supported"}):
            value = self.response()
            value["checks"][0] = invalid
            self.assertFalse(self.decode(value)["review_complete"])

    def test_unknown_check_id_cannot_claim_more_coverage(self):
        value = self.response()
        value["checks"].append(["D9999", "supported"])
        result = self.decode(value)
        self.assertFalse(result["review_complete"])
        self.assertEqual(result["coverage"]["covered_units"], 2)

    def test_missing_required_collections_is_rejected(self):
        for value in ({}, {"checks": [], "issues": {}}, {"checks": {}, "issues": []}):
            with self.assertRaises(ValueError):
                self.decode(value)

    def test_invalid_problem_type_is_not_a_style_scoring_backdoor(self):
        self.assertEqual(self.decode(self.response(kind="style"))["issues"], [])

    def test_difference_must_be_bounded_text(self):
        for difference in (None, "", " " * 10, "长" * (review.MAX_REASON_CHARS + 1)):
            self.assertEqual(self.decode(self.response(difference=difference))["issues"], [])

    def test_many_issues_are_not_silently_complete(self):
        value = self.response()
        value["issues"] *= review.MAX_ISSUES + 1
        self.assertFalse(self.decode(value)["review_complete"])

    def test_exact_duplicate_problem_is_not_displayed_twice(self):
        value = self.response()
        value["issues"] *= 2
        self.assertEqual(len(self.decode(value)["issues"]), 1)

    def test_multiple_facts_in_same_unit_can_both_be_checked(self):
        value = self.response(kind="added_claim")
        value["issues"].append({"d": "D0001", "kind": "added_claim", "s": [], "difference": "另一项具体时效未提供依据。"})
        self.assertEqual(len(self.decode(value)["issues"]), 2)

    def test_tampered_offsets_are_rejected(self):
        self.packet["source_units"][0]["end"] += 1
        with self.assertRaises(ValueError):
            self.decode()

    def test_tampered_id_order_is_rejected(self):
        self.packet["draft_units"][0]["id"] = "D0002"
        with self.assertRaises(ValueError):
            self.decode()

    def test_prompt_has_no_brand_specific_examples(self):
        for brand in ("马自达", "别克", "GL8", "福斯", "固特异", "智界"):
            self.assertNotIn(brand, review.REVIEW_INSTRUCTION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
