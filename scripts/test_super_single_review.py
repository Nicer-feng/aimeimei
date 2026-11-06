#!/usr/bin/env python3
"""单次复检纯合同回归；人工响应不证明模型的语义判断能力。"""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_platform import super_evidence_review as evidence, super_single_review as single


class SingleReviewTests(unittest.TestCase):
    def setUp(self):
        self.source = "门票已售出一万张。\n\n团体须提前预约。\n\n室内展览正常开放。"
        self.draft = "已有一万位访客，工作人员私下都推荐，进去后立刻凉爽。团体随时参观。"
        self.packet = evidence.build_packet(self.source, self.draft)

    def issue(self, **kwargs):
        value = {"d": "D0001", "difference": "售票张数被写成访客人数。", "kind": "conflict", "s": ["S0001"]}
        value.update(kwargs)
        return value

    def decode(self, items=None, **kwargs):
        return single.decode_review({"issues": [self.issue()] if items is None else items}, self.packet, **kwargs)

    def test_raw_source_and_draft_are_lossless(self):
        data = single.build_data(self.packet)
        self.assertEqual("".join(x["text"] for x in data["source_units"]), self.source)
        self.assertEqual("".join(x["text"] for x in data["draft_units"]), self.draft)
        self.assertEqual(set(data), {"source_units", "draft_units", "review_scope"})
        self.assertEqual(set(data["source_units"][0]), {"id", "text"})

    def test_current_request_in_source_is_not_repeated(self):
        self.assertNotIn("current_request", single.build_data(self.packet, self.source))

    def test_current_request_crossing_units_is_not_repeated(self):
        self.assertNotIn("current_request", single.build_data(self.packet, "提前预约。\n\n室内展览"))

    def test_missing_current_request_is_preserved_without_rewrite(self):
        request = " 这段客户要求，\n逐字保留！ "
        self.assertEqual(single.build_data(self.packet, request)["current_request"], request)

    def test_request_only_in_draft_is_still_sent_as_request(self):
        self.assertEqual(single.build_data(self.packet, self.draft)["current_request"], self.draft)

    def test_blank_request_adds_nothing(self):
        self.assertNotIn("current_request", single.build_data(self.packet, " \n"))

    def test_non_text_request_rejected(self):
        with self.assertRaises(TypeError):
            single.build_data(self.packet, {"summary": "要求"})

    def test_data_and_scope_are_independent_copies(self):
        before = deepcopy(self.packet)
        scope = {"fact_sections": ["标题", "正文"]}
        data = single.build_data(self.packet, scope=scope)
        data["source_units"][0]["text"] = "changed"
        data["review_scope"]["fact_sections"].append("额外")
        self.assertEqual(self.packet, before)
        self.assertEqual(scope["fact_sections"], ["标题", "正文"])

    def test_bad_packet_offsets_cannot_be_sent(self):
        self.packet["source_units"][0]["end"] += 1
        with self.assertRaises(ValueError):
            single.build_data(self.packet)

    def test_bad_packet_offsets_cannot_be_decoded(self):
        self.packet["draft_units"][0]["start"] = 1
        with self.assertRaises(ValueError):
            self.decode()

    def test_only_issues_protocol_is_sufficient(self):
        result = self.decode()
        self.assertTrue(result["review_complete"])
        self.assertEqual(result["review_method"], "single_pass")
        self.assertNotIn("coverage", result)
        self.assertIn("不代表逐事实覆盖", result["review_note"])

    def test_restored_quotes_are_exact_original_text(self):
        result = self.decode()["issues"][0]
        self.assertEqual(result["quote"], self.packet["draft_units"][0]["text"])
        self.assertEqual(result["source_quote"], self.packet["source_units"][0]["text"])
        self.assertFalse(result["grounded"])
        self.assertTrue(result["citation_verified"])
        self.assertEqual(result["status"], "pending")

    def test_same_sentence_multiple_independent_claims_are_preserved(self):
        items = [self.issue(), self.issue(kind="added_claim", s=[], difference="材料未提供工作人员私人推荐的依据。"),
                 self.issue(kind="added_claim", s=[], difference="材料未提供立即产生效果的时效依据。")]
        result = self.decode(items)
        self.assertEqual(len(result["issues"]), 3)
        self.assertEqual({x["draft_id"] for x in result["issues"]}, {"D0001"})

    def test_only_exact_duplicates_removed(self):
        first = self.issue()
        self.assertEqual(len(self.decode([first, deepcopy(first)])["issues"]), 1)

    def test_near_duplicate_text_is_not_semantically_merged(self):
        items = [self.issue(), self.issue(difference=" 售票张数被写成访客人数。")]
        self.assertEqual(len(self.decode(items)["issues"]), 2)

    def test_different_source_order_is_not_exact_duplicate(self):
        items = [self.issue(s=["S0001", "S0003"]), self.issue(s=["S0003", "S0001"])]
        self.assertEqual(len(self.decode(items)["issues"]), 2)

    def test_non_contiguous_sources_are_restored_in_original_order(self):
        item = self.decode([self.issue(s=["S0003", "S0001"])])["issues"][0]
        self.assertEqual(item["source_ids"], ["S0001", "S0003"])
        self.assertEqual(item["source_quote"], self.packet["source_units"][0]["text"] + "\n" + self.packet["source_units"][2]["text"])

    def test_added_claim_accepts_no_positive_source(self):
        item = self.decode([self.issue(kind="added_claim", s=[])])["issues"][0]
        self.assertEqual(item["source_quote"], "")
        self.assertEqual(item["evidence_status"], "not_in_material")
        self.assertFalse(item["citation_verified"])
        self.assertIn("不代表现实虚假", item["verification"])

    def test_added_claim_with_nearest_source_still_is_not_disproof(self):
        item = self.decode([self.issue(kind="added_claim")])["issues"][0]
        self.assertEqual(item["evidence_status"], "not_in_material")
        self.assertFalse(item["grounded"])

    def test_conflict_requires_source(self):
        result = self.decode([self.issue(s=[])])
        self.assertFalse(result["review_complete"])
        self.assertEqual(result["issues"], [])
        self.assertTrue(result["review_unverified"])

    def test_missing_condition_requires_source(self):
        self.assertEqual(self.decode([self.issue(kind="missing_condition", s=[])])["issues"], [])

    def test_one_bad_id_preserves_other_valid_items(self):
        result = self.decode([self.issue(d="D9999"), self.issue()])
        self.assertEqual(len(result["issues"]), 1)
        self.assertFalse(result["review_complete"])

    def test_bad_source_id_not_silently_dropped_from_list(self):
        self.assertEqual(self.decode([self.issue(s=["S0001", "S9999"])])["issues"], [])

    def test_duplicate_source_is_invalid(self):
        self.assertEqual(self.decode([self.issue(s=["S0001", "S0001"])])["issues"], [])

    def test_missing_or_wrong_fields_are_local_failures(self):
        for field, value in [("d", None), ("kind", []), ("kind", "style"), ("s", "S0001"),
                             ("s", [None]), ("difference", None), ("difference", " \n")]:
            with self.subTest(field=field, value=value):
                result = self.decode([self.issue(**{field: value}), self.issue()])
                self.assertEqual(len(result["issues"]), 1)
                self.assertFalse(result["review_complete"])

    def test_missing_issue_source_field_is_invalid_even_for_added_claim(self):
        item = self.issue(kind="added_claim")
        del item["s"]
        self.assertEqual(self.decode([item])["issues"], [])

    def test_non_object_issue_preserves_following_valid_issue(self):
        result = self.decode(["broken", self.issue()])
        self.assertEqual(len(result["issues"]), 1)
        self.assertFalse(result["review_complete"])

    def test_reason_longer_than_old_limit_is_preserved(self):
        text = "较长的具体差异。" * 50
        self.assertGreater(len(text), evidence.MAX_REASON_CHARS)
        self.assertEqual(self.decode([self.issue(difference=text)])["issues"][0]["reason"], text)

    def test_reason_at_limit_preserved_without_strip_or_rewrite(self):
        text = " " + "原" * (single.MAX_REASON_CHARS - 2) + "\n"
        self.assertEqual(self.decode([self.issue(difference=text)])["issues"][0]["reason"], text)

    def test_abnormally_long_reason_is_unverified_not_truncated(self):
        result = self.decode([self.issue(difference="原" * (single.MAX_REASON_CHARS + 1)), self.issue()])
        self.assertEqual(len(result["issues"]), 1)
        self.assertEqual(result["review_unverified"][0]["difference_chars"], single.MAX_REASON_CHARS + 1)
        self.assertFalse(result["review_complete"])

    def test_no_keyword_blacklist_claims_to_judge_semantics(self):
        text = "未发现问题。"
        self.assertEqual(self.decode([self.issue(difference=text)])["issues"][0]["reason"], text)
        self.assertFalse(self.decode([self.issue(difference=text)])["issues"][0]["grounded"])

    def test_source_incomplete_excludes_all_semantic_issues(self):
        result = self.decode([self.issue(), self.issue(kind="added_claim", s=[])], source_complete=False)
        self.assertEqual(result["issues"], [])
        self.assertFalse(result["review_complete"])

    def test_packet_incomplete_excludes_all_semantic_issues(self):
        self.packet["complete"] = False
        result = self.decode()
        self.assertEqual(result["issues"], [])
        self.assertFalse(result["review_complete"])

    def test_empty_issues_is_protocol_complete_not_all_facts_passed(self):
        result = self.decode([])
        self.assertTrue(result["review_complete"])
        self.assertIn("不代表", result["review_note"])
        self.assertNotIn("coverage", result)

    def test_count_limit_preserves_valid_items_but_marks_incomplete(self):
        result = self.decode([self.issue(difference=str(i)) for i in range(single.MAX_ISSUES)])
        self.assertEqual(len(result["issues"]), single.MAX_ISSUES)
        self.assertFalse(result["review_complete"])

    def test_count_over_limit_does_not_silently_accept_whole_result(self):
        result = self.decode([self.issue(difference=str(i)) for i in range(single.MAX_ISSUES + 1)])
        self.assertEqual(len(result["issues"]), single.MAX_ISSUES)
        self.assertTrue(result["review_rejected"])

    def test_invalid_top_level_protocol_raises(self):
        for value in (None, [], {}, {"issues": None}, {"issues": {}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                single.decode_review(value, self.packet)

    def test_obsolete_auxiliary_fields_are_not_required_or_used(self):
        result = single.decode_review({"issues": [self.issue()], "checks": "bad", "risk_checks": None}, self.packet)
        self.assertTrue(result["review_complete"])

    def test_optional_incomplete_true_preserves_valid_items(self):
        result = single.decode_review({"issues": [self.issue()], "incomplete": True}, self.packet)
        self.assertEqual(len(result["issues"]), 1)
        self.assertFalse(result["review_complete"])
        self.assertEqual(result["review_rejected"], [])

    def test_optional_incomplete_is_not_required_to_be_false(self):
        for flag in (False, None, "false"):
            with self.subTest(flag=flag):
                result = single.decode_review({"issues": [self.issue()], "incomplete": flag}, self.packet)
                self.assertTrue(result["review_complete"])

    def test_decoder_does_not_mutate_model_result_or_packet(self):
        value = {"issues": [self.issue(s=["S0003", "S0001"])]}
        before_value, before_packet = deepcopy(value), deepcopy(self.packet)
        single.decode_review(value, self.packet)
        self.assertEqual(value, before_value)
        self.assertEqual(self.packet, before_packet)


if __name__ == "__main__":
    unittest.main(verbosity=2)
