#!/usr/bin/env python3
"""只读审核协议的纯函数回归，不调用模型或真实数据库。"""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_platform import super_review, super_sources


class LiteralTests(unittest.TestCase):
    def normalize(self, source, **req):
        return super_review.normalize_requirements(req, source)[0]

    def test_semantic_commands_are_not_literal(self):
        req = self.normalize("必须包含双证书概念。不要直接复制粘贴Brief原文段落。",
            required=["必须包含双证书概念"], forbidden=["直接复制粘贴Brief原文段落"])
        self.assertEqual(req["required"], [])
        self.assertEqual(req["forbidden"], [])
        self.assertIn("双证书概念", req["notes"])
        self.assertIn("复制粘贴", req["notes"])

    def test_explicit_lists_recovered_from_old_state(self):
        req = self.normalize("必带话题：#品牌甲 #现场演示。禁用词：智驾、绝对安全。")
        self.assertEqual(req["required"], ["#品牌甲", "#现场演示"])
        self.assertEqual(req["forbidden"], ["智驾", "绝对安全"])

    def test_redline_examples_recovered(self):
        req = self.normalize("注意极致之类的极限词和智驾之类的红线词汇。")
        self.assertEqual(req["forbidden"], ["极致", "智驾"])

    def test_long_request_does_not_turn_later_clauses_into_terms(self):
        req = self.normalize("注意不要直接说我的观点我的解读是什么什么，Brief 只用于提取事实和限制，禁止沿用其章节顺序、标题和论证结构。注意注意极致之类的极限词和智驾之类的红线词汇。")
        self.assertEqual(req["forbidden"], ["极致", "智驾"])

    def test_adjacent_hashtags_are_separate_terms(self):
        req = self.normalize("必带话题：#品牌甲#品牌乙#活动主题。")
        self.assertEqual(req["required"], ["#品牌甲", "#品牌乙", "#活动主题"])

    def test_product_mentions_are_not_mandatory(self):
        req = self.normalize("产品名称为品牌甲，使用激光雷达。", required=["品牌甲"], forbidden=["激光雷达"])
        self.assertEqual(req["required"], [])
        self.assertEqual(req["forbidden"], [])

    def test_behavior_instructions_do_not_create_forbidden_words(self):
        req = self.normalize("卖点请转化，不能用原话。禁止使用风险及不恰当描述。")
        self.assertEqual(req["forbidden"], [])

    def test_complete_short_plain_ban_is_traceable(self):
        for source in ("不要出现智驾。", "不要用智驾。"):
            req, audit = super_review.requirements_from_source(source)
            self.assertEqual(req["forbidden"], ["智驾"])
            self.assertIn(audit["accepted"]["forbidden"][0]["source_quote"], source)

    def test_short_style_and_behavior_are_not_words(self):
        for source in ("不要出现广告味。", "别照搬资料结构。", "不要用生硬的表达。"):
            self.assertEqual(self.normalize(source)["forbidden"], [])

    def test_later_plain_ban_can_be_cancelled(self):
        self.assertEqual(self.normalize("不要出现智驾。现在可以用智驾。")["forbidden"], [])

    def test_section_ban_does_not_become_whole_manuscript_rule(self):
        for source in ("标题不要出现智驾。", "正文不要使用“智驾”。", "发布文案禁用词：智驾。"):
            req, audit = super_review.requirements_from_source(source)
            self.assertEqual(req["forbidden"], [])
            self.assertFalse(audit["complete"])
            self.assertEqual(audit["unchecked"][0]["text"], "智驾")
            self.assertIn(audit["unchecked"][0]["source_quote"], source)

    def test_separate_body_length_does_not_scope_global_ban(self):
        req, audit = super_review.requirements_from_source("正文100至120字，禁用词：智驾。")
        self.assertEqual(req["forbidden"], ["智驾"])
        self.assertTrue(audit["complete"])

    def test_existing_unproven_word_is_marked_unchecked(self):
        req, audit = super_review.normalize_requirements({"forbidden": ["原话"]}, "不能用原话。")
        self.assertEqual(req["forbidden"], [])
        self.assertFalse(audit["complete"])
        self.assertEqual(audit["unchecked"][0]["status"], "not_checked")

    def test_explicit_word_list_header(self):
        req = self.normalize("不得使用的词：词甲、词乙。")
        self.assertEqual(req["forbidden"], ["词甲", "词乙"])

    def test_bounded_ocr_catalog_preserves_existing_terms(self):
        source = "产品采用全新配方。4､规避平台敏感字眼: - 程度类:全新､独家等 - 行为类:狂飙､高速飞驰等 5､产品词表:轻便､耐用。"
        req, audit = super_review.normalize_requirements({"forbidden": ["全新", "独家", "狂飙", "高速飞驰", "轻便", "耐用"]}, source)
        self.assertEqual(req["forbidden"], ["全新", "独家", "狂飙", "高速飞驰"])
        self.assertEqual([x["text"] for x in audit["unchecked"]], ["轻便", "耐用"])
        self.assertTrue(all("规避平台敏感字眼" in x["source_quote"] for x in audit["accepted"]["forbidden"]))

    def test_catalog_stops_at_new_section_heading(self):
        source = "规避词：\n- 程度类：独家、全新等\n- 行为类：狂飙\n产品信息：耐用、舒适"
        req = self.normalize(source, forbidden=["全新", "独家", "狂飙", "耐用", "舒适"])
        self.assertEqual(req["forbidden"], ["全新", "独家", "狂飙"])

    def test_catalog_stops_at_blank_line_and_table_boundary(self):
        for suffix in ("\n\n耐用、舒适", " | 耐用、舒适"):
            req = self.normalize("避用词：\n- 程度类：独家、全新" + suffix, forbidden=["全新", "独家", "耐用", "舒适"])
            self.assertEqual(req["forbidden"], ["全新", "独家"])

    def test_plain_product_category_is_not_a_ban_catalog(self):
        req = self.normalize("产品分类：\n- 新品类：全新、独家", forbidden=["全新", "独家"])
        self.assertEqual(req["forbidden"], [])

    def test_negated_catalog_does_not_ban(self):
        req = self.normalize("不是禁用词：全新、独家。", forbidden=["全新", "独家"])
        self.assertEqual(req["forbidden"], [])

    def test_later_permission_overrides_catalog(self):
        req = self.normalize("规避词：\n- 程度类：全新、独家\n\n本轮可以用全新。", forbidden=["全新", "独家"])
        self.assertEqual(req["forbidden"], ["独家"])

    def test_catalog_does_not_turn_single_character_into_substring_rule(self):
        req = self.normalize("规避词：\n- 程度类：最、级、独家", forbidden=["最", "级", "独家"])
        self.assertEqual(req["forbidden"], ["独家"])

    def test_unquoted_generic_prohibition_is_conservative(self):
        req, audit = super_review.normalize_requirements({"forbidden": ["原话"]}, "请避免使用原话。")
        self.assertEqual(req["forbidden"], [])
        self.assertFalse(audit["complete"])

    def test_explicit_quoted_word_is_supported(self):
        req = self.normalize("必须出现“品牌甲”。不要使用“智驾”。")
        self.assertEqual(req["required"], ["品牌甲"])
        self.assertEqual(req["forbidden"], ["智驾"])

    def test_partial_term_of_quoted_expression_is_not_accepted(self):
        req = self.normalize("禁止写“绝对安全”。", forbidden=["安全"])
        self.assertNotIn("安全", req["forbidden"])
        self.assertIn("绝对安全", req["forbidden"])

    def test_cancellation_prefix(self):
        req = self.normalize("不要使用“智驾”。本轮不再禁止使用“智驾”。", forbidden=["智驾"])
        self.assertEqual(req["forbidden"], [])

    def test_new_permission_overrides_old_rule_same_sentence(self):
        req = self.normalize("之前禁止用智驾，现在可以用智驾。", forbidden=["智驾"])
        self.assertEqual(req["forbidden"], [])

    def test_new_permission_overrides_old_rule_new_line(self):
        req = self.normalize("禁用词：智驾\n本轮不再限制智驾", forbidden=["智驾"])
        self.assertEqual(req["forbidden"], [])

    def test_explicit_cancellation_is_resolved_not_unchecked(self):
        req, audit = super_review.normalize_requirements({"forbidden": ["词甲"]}, "禁用词：词甲。现在可以用词甲。")
        self.assertEqual(req["forbidden"], [])
        self.assertTrue(audit["complete"])
        self.assertEqual(audit["unchecked"], [])
        self.assertEqual(audit["discarded"][0]["status"], "cancelled")

    def test_later_ban_overrides_permission(self):
        req = self.normalize("现在可以用智驾。最新要求：禁用词：智驾。")
        self.assertEqual(req["forbidden"], ["智驾"])

    def test_required_cancellation(self):
        req = self.normalize("必带话题：#品牌甲。现在不用带#品牌甲。", required=["#品牌甲"])
        self.assertEqual(req["required"], [])

    def test_other_task_terms_do_not_survive(self):
        req = self.normalize("这单用专业语气，必须出现“品牌乙”。", required=["品牌甲"], forbidden=["专业术语"])
        self.assertEqual(req["required"], ["品牌乙"])
        self.assertEqual(req["forbidden"], [])

    def test_no_unrelated_protocol_promoted(self):
        req = self.normalize("写一份自然口播稿。", required=["只返回JSON", "不写稿"])
        self.assertEqual(req["required"], [])
        self.assertNotIn("只返回JSON", req["notes"])

    def test_single_character_ban_is_not_substring_rule(self):
        req = self.normalize("禁用词：最、第一。")
        self.assertEqual(req["forbidden"], ["第一"])

    def test_external_declared_source_rejected(self):
        req, audit = super_review.normalize_requirements({}, "本单只说品牌甲。",
            {"required": [{"text": "品牌甲", "source_quote": "必须出现品牌甲"}]})
        self.assertEqual(req["required"], [])
        self.assertTrue(audit["discarded"])


class ReviewTests(unittest.TestCase):
    draft = "封面：智驾放心开。正文：这车的辅助驾驶是亮点。售价20万元。"
    source = "不要使用“智驾”。售价18万元，老车主需要回店签协议。"

    def issue(self, **changes):
        item = {"kind": "fact", "quote": "售价20万元。", "claim": "20万元",
                "source_quote": "售价18万元", "expected": "18万元", "reason": "稿件价格与资料不同"}
        item.update(changes)
        return item

    def decode(self, issues, **kwargs):
        return super_review.decode_review({"issues": issues}, self.draft, self.source, {}, **kwargs)

    def test_valid_fact_is_pending_not_fact_certified(self):
        result = self.decode([self.issue()])
        self.assertTrue(result["review_complete"])
        self.assertEqual(result["issues"][0]["status"], "pending")
        self.assertIn("语义结论待核对", result["issues"][0]["verification"])

    def test_wrong_anchor_cannot_be_certified(self):
        result = self.decode([self.issue(quote="这车的辅助驾驶是亮点。", claim="20万元")])
        self.assertFalse(result["review_complete"])
        self.assertEqual(result["issues"], [])

    def test_wording_is_code_scope_not_flash_scope(self):
        result = self.decode([self.issue(kind="wording", quote="封面：智驾放心开。", claim="智驾",
            source_quote="不要使用“智驾”", expected="", reason="本单要求避用该词")])
        self.assertEqual(result["issues"], [])
        self.assertFalse(result["review_complete"])
        self.assertEqual(super_review.requirements_from_source(self.source)[0]["forbidden"], ["智驾"])

    def test_style_is_out_of_scope_even_with_real_quote(self):
        result = self.decode([self.issue(kind="style", reason="语气不够自然")])
        self.assertFalse(result["review_complete"])
        self.assertEqual(result["issues"], [])

    def test_condition_stays_pending(self):
        result = self.decode([self.issue(kind="condition", source_quote="老车主需要回店签协议",
                                       expected="回店签协议", reason="稿中未说明办理条件")])
        self.assertEqual(result["issues"][0]["status"], "pending")

    def test_wording_does_not_survive_latest_permission(self):
        item = self.issue(kind="wording", quote="封面：智驾放心开。", claim="智驾",
            source_quote="不要使用“智驾”", expected="", reason="本单要求避用该词")
        result = super_review.decode_review({"issues": [item]}, self.draft,
            self.source + "本轮可以用智驾。", {"forbidden": ["智驾"]})
        self.assertEqual(result["issues"], [])
        self.assertFalse(result["review_complete"])

    def test_unknown_wording_term_is_rejected(self):
        result = self.decode([self.issue(kind="wording", quote="售价20万元。", claim="20万元",
            source_quote="售价18万元", expected="", reason="不应出现这个词")])
        self.assertEqual(result["issues"], [])

    def test_product_mention_is_not_wording_evidence(self):
        source = "产品采用全新配方。规避词：\n- 程度类：全新、独家"
        item = self.issue(kind="wording", quote="采用全新配方。", claim="全新",
                          source_quote="产品采用全新配方", expected="", reason="出现避用词")
        result = super_review.decode_review({"issues": [item]}, "采用全新配方。", source, {})
        self.assertFalse(result["review_complete"])
        self.assertEqual(result["issues"], [])
        item["source_quote"] = "规避词：\n- 程度类：全新、独家"
        self.assertEqual(super_review.decode_review({"issues": [item]}, "采用全新配方。", source, {})["issues"], [])
        self.assertEqual(super_review.requirements_from_source(source)[0]["forbidden"], ["全新", "独家"])

    def test_source_cannot_be_invented(self):
        result = self.decode([self.issue(source_quote="售价16万元", expected="16万元")])
        self.assertFalse(result["review_complete"])
        self.assertEqual(result["review_rejected"][0]["source_quote"], "售价16万元")

    def test_expected_must_be_in_cited_source(self):
        self.assertFalse(self.decode([self.issue(expected="16万元")])["review_complete"])

    def test_no_issue_claim_is_not_reported_as_error(self):
        self.assertFalse(self.decode([self.issue(reason="此条无问题")])["review_complete"])

    def test_whole_manuscript_omission_without_anchor_is_incomplete(self):
        result = self.decode([self.issue(kind="uncertain", quote="", claim="", expected="", reason="整篇似乎未提及办理条件")])
        self.assertEqual(result["issues"], [])
        self.assertFalse(result["review_complete"])

    def test_whole_manuscript_omission_can_be_unverified(self):
        result = super_review.decode_review({"issues": [], "unverified": [
            {"source_quote": "老车主需要回店签协议", "reason": "整篇是否覆盖办理条件尚无法定位"}
        ]}, self.draft, self.source, {})
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["review_rejected"], [])
        self.assertFalse(result["review_complete"])
        self.assertEqual(result["review_unverified"][0]["status"], "not_checked")

    def test_unverified_cannot_invent_source(self):
        result = super_review.decode_review({"issues": [], "unverified": [
            {"source_quote": "不存在的依据", "reason": "材料不全"}
        ]}, self.draft, self.source, {})
        self.assertFalse(result["review_complete"])
        self.assertTrue(result["review_rejected"])

    def test_invalid_unverified_type_cannot_pass(self):
        result = super_review.decode_review({"issues": [], "unverified": "无"}, self.draft, self.source, {})
        self.assertFalse(result["review_complete"])

    def test_empty_result_is_limited_completion(self):
        result = self.decode([])
        self.assertTrue(result["review_complete"])
        self.assertEqual(result["issues"], [])

    def test_missing_fields_not_silent_success(self):
        result = self.decode([{"quote": "售价20万元。", "reason": "价格有误"}])
        self.assertFalse(result["review_complete"])

    def test_invalid_top_level_raises(self):
        with self.assertRaises(ValueError):
            super_review.decode_review({}, self.draft, self.source, {})

    def test_multiple_occurrences_are_not_unique_anchor(self):
        result = super_review.decode_review({"issues": [self.issue()]}, self.draft + "售价20万元。", self.source, {})
        self.assertFalse(result["review_complete"])

    def test_local_edit_does_not_review_outside_scope(self):
        result = self.decode([self.issue()], local_bounds=(0, 10))
        self.assertFalse(result["review_complete"])

    def test_valid_and_invalid_results_keep_incomplete_state(self):
        result = self.decode([self.issue(), self.issue(source_quote="没有这个资料")])
        self.assertEqual(len(result["issues"]), 1)
        self.assertFalse(result["review_complete"])

    def test_extra_items_cannot_silently_truncate_to_complete(self):
        result = self.decode([self.issue()] * 6)
        self.assertFalse(result["review_complete"])


class SourceHistoryTests(unittest.TestCase):
    def row(self, message_id, text, role="user"):
        return {"id": message_id, "role": role, "content": text}

    def build(self, state, rows):
        return super_sources.build_evidence(state, "default", "task-one", rows, rows[-1]["content"])

    def forbidden(self, evidence):
        return super_review.normalize_requirements({"forbidden": ["词甲"]}, evidence)[0]["forbidden"]

    def test_repeated_original_ban_is_latest(self):
        ban = "禁用词：词甲。"
        state = {"source_brief": ban}
        evidence, _ = self.build(state, [self.row(1, ban), self.row(2, "现在可以用词甲。"), self.row(3, ban)])
        self.assertEqual(self.forbidden(evidence), ["词甲"])
        self.assertLess(evidence.index("可以用词甲"), evidence.rindex("禁用词：词甲"))

    def test_nonfirst_original_source_survives_summary_window(self):
        state = {"source_brief": "本单产品信息。"}
        self.build(state, [self.row(1, "本单产品信息。"), self.row(2, "禁用词：词甲。")])
        evidence, _ = self.build(state, [self.row(100, "继续改写这一篇稿件。")])
        self.assertEqual(self.forbidden(evidence), ["词甲"])
        self.assertTrue(any(item["message_id"] == 2 for item in state["literal_sources"]["events"]))

    def test_cancelled_original_rule_does_not_resurrect(self):
        state = {"source_brief": "禁用词：词甲。"}
        self.build(state, [self.row(1, state["source_brief"]), self.row(2, "本轮不再限制词甲。")])
        evidence, _ = self.build(state, [self.row(100, "继续改写这一篇稿件。")])
        self.assertEqual(self.forbidden(evidence), [])

    def test_new_original_ban_overrides_saved_permission(self):
        state = {"source_brief": "禁用词：词甲。"}
        self.build(state, [self.row(1, state["source_brief"]), self.row(2, "本轮可以用词甲。")])
        evidence, _ = self.build(state, [self.row(100, state["source_brief"])])
        self.assertEqual(self.forbidden(evidence), ["词甲"])

    def test_wrong_conversation_sources_are_not_used(self):
        state = {"source_brief": "本单材料。", "literal_sources": {"user_id": "default", "conversation_id": "another-task", "events": [{"message_id": 1, "position": 0, "text": "禁用词：词甲"}]}}
        evidence, _ = self.build(state, [self.row(100, "继续写稿。")])
        self.assertNotIn("词甲", evidence)

    def test_assistant_summary_is_not_original_evidence(self):
        state = {"source_brief": "本单材料。"}
        evidence, _ = self.build(state, [self.row(1, "禁用词：词甲", "assistant"), self.row(2, "继续写稿。")])
        self.assertNotIn("词甲", evidence)

    def test_full_message_does_not_get_old_fragment_appended_after_it(self):
        text = "禁用词：词甲。现在可以用词甲。"
        state = {"source_brief": "本单材料。"}
        evidence, _ = self.build(state, [self.row(2, text)])
        self.assertEqual(self.forbidden(evidence), [])
        self.assertTrue(evidence.endswith(text))

    def test_source_budget_marks_incomplete(self):
        state = {"source_brief": "本单材料。"}
        rows = [self.row(i, "禁用词：词" + str(i) + "。") for i in range(1, 10)]
        with patch.object(super_sources, "MAX_CHARS", 20):
            _, incomplete = self.build(state, rows)
        self.assertTrue(incomplete)
        self.assertTrue(state["literal_sources"]["incomplete"])
        self.assertLessEqual(sum(len(item["text"]) for item in state["literal_sources"]["events"]), 20)

    def test_length_source_survives_summary_window(self):
        state = {"source_brief": "本单产品信息。"}
        self.build(state, [self.row(1, state["source_brief"]), self.row(2, "正文100至120字。")])
        evidence, _ = self.build(state, [self.row(100, "继续改写这一篇稿件。")])
        self.assertEqual(super_review.length_requirement(evidence)["min_chars"], 100)
        self.build(state, [self.row(101, "取消正文字数要求。")])
        evidence, _ = self.build(state, [self.row(102, "继续改写这一篇稿件。")])
        self.assertEqual(super_review.length_requirement(evidence)["status"], "cancelled")

    def test_fact_correction_outside_twelve_rows_is_not_discarded(self):
        state = {"source_brief": "产品售价18万元，正文650–700字。"}
        rows = [self.row(1, state["source_brief"]), self.row(2, "价格更正为16万元，以此为准。")]
        rows += [self.row(i, "继续讨论材料。") for i in range(3, 20)]
        rows.append(self.row(20, "重新给完整正文。"))
        evidence, incomplete = self.build(state, rows)
        self.assertIn("价格更正为16万元，以此为准。", evidence)
        self.assertLess(evidence.index("18万元"), evidence.index("16万元"))
        self.assertFalse(incomplete)


class LengthTests(unittest.TestCase):
    def test_approximate_length_does_not_invent_interval(self):
        req, _ = super_review.requirements_from_source("写口播稿，正文大概750字左右。")
        length = req["length_requirement"]
        self.assertEqual((length["mode"], length["target_chars"]), ("approx", 750))
        self.assertEqual((req["min_chars"], req["max_chars"]), (0, 0))
        self.assertEqual(length["source_quote"], "正文大概750字左右")

    def test_explicit_range_has_source(self):
        req, _ = super_review.requirements_from_source("正文100至120字。")
        self.assertEqual((req["min_chars"], req["max_chars"]), (100, 120))
        self.assertEqual(req["length_requirement"]["source_quote"], "正文100至120字")

    def test_approximate_range_not_hard_bound(self):
        req, _ = super_review.requirements_from_source("正文约650-700字。")
        self.assertEqual(req["length_requirement"]["mode"], "approx")
        self.assertEqual((req["min_chars"], req["max_chars"]), (0, 0))

    def test_single_target_is_not_hard_equality(self):
        req, _ = super_review.requirements_from_source("正文750字。")
        self.assertEqual(req["length_requirement"]["mode"], "target")
        self.assertEqual((req["min_chars"], req["max_chars"]), (0, 0))

    def test_explicit_minimum_and_maximum(self):
        req, _ = super_review.requirements_from_source("正文最多750字。")
        self.assertEqual((req["min_chars"], req["max_chars"]), (0, 750))
        req, _ = super_review.requirements_from_source("正文至少500字。")
        self.assertEqual((req["min_chars"], req["max_chars"]), (500, 0))

    def test_latest_length_requirement_overrides(self):
        length = super_review.length_requirement("正文100至120字。现在正文约750字。")
        self.assertEqual((length["mode"], length["target_chars"]), ("approx", 750))

    def test_length_cancellation(self):
        self.assertEqual(super_review.length_requirement("正文100至120字。取消正文字数要求。")["status"], "cancelled")

    def test_plain_length_cancellation_is_latest(self):
        for cancel in ("这次不限字数。", "不限制字数。"):
            req, _ = super_review.requirements_from_source("正文650–700字。" + cancel)
            self.assertEqual(req["length_requirement"]["status"], "cancelled")
            self.assertEqual((req["min_chars"], req["max_chars"]), (0, 0))

    def test_local_output_does_not_use_whole_draft_limits(self):
        req, _ = super_review.requirements_from_source("正文650–700字。必带词：词甲。禁用词：智驾。")
        scoped, scope, notice = super_review.output_scope(req, "只改结尾，其他地方不动。")
        self.assertEqual(scope, "local_fragment")
        self.assertTrue(notice)
        self.assertEqual((scoped["min_chars"], scoped["max_chars"]), (0, 0))
        self.assertEqual(scoped["required"], [])
        self.assertEqual(scoped["forbidden"], ["智驾"])
        self.assertEqual(req["min_chars"], 650)
        checked = super_review.writing.validate_output("这就是这次体验的感受。", scoped, "revise")
        self.assertFalse(checked["issues"])
        self.assertTrue(checked["body_chars"])

    def test_additional_length_is_not_total(self):
        self.assertEqual(super_review.length_requirement("正文增加50字。")["mode"], "none")

    def test_title_length_is_not_body_length(self):
        self.assertEqual(super_review.length_requirement("标题字数20字以内。")["mode"], "none")

    def test_invalid_range_not_passed(self):
        req, audit = super_review.requirements_from_source("正文120至100字。")
        self.assertEqual(req["length_requirement"]["status"], "not_checked")
        self.assertFalse(audit["complete"])
        self.assertEqual((req["min_chars"], req["max_chars"]), (0, 0))

    def test_full_output_length_is_not_assumed_to_mean_body(self):
        req, audit = super_review.requirements_from_source("请写测试车口播稿，全文650至700字。")
        self.assertEqual(req["length_requirement"]["status"], "not_checked")
        self.assertEqual(req["length_requirement"]["scope"], "full_output")
        self.assertEqual(req["length_requirement"]["source_quote"], "全文650至700字")
        self.assertEqual((req["min_chars"], req["max_chars"]), (0, 0))
        self.assertFalse(audit["complete"])
        req, audit = super_review.requirements_from_source("全文字数控制在650至700字。")
        self.assertEqual(req["length_requirement"]["status"], "not_checked")
        self.assertEqual((req["min_chars"], req["max_chars"]), (0, 0))
        self.assertFalse(audit["complete"])

    def test_later_body_scope_can_replace_unsupported_full_output_length(self):
        req, audit = super_review.requirements_from_source("全文650至700字。改为正文100至120字。")
        self.assertEqual((req["min_chars"], req["max_chars"]), (100, 120))
        self.assertTrue(audit["complete"])


if __name__ == "__main__":
    unittest.main()
