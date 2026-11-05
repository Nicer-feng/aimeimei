"""验证题库来源、选项映射及片段检索的边界。"""

import json
import tempfile
import unittest
from pathlib import Path

from ncd.bank import QuestionBank, normalize, query_parts


class QuestionBankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = QuestionBank()

    def test_visible_sources_and_answers(self):
        self.assertEqual(self.bank.metadata["sheet_counts"], {"2026单选": 1597, "2026多选": 963})
        self.assertEqual(sum(len(item["sources"]) for item in self.bank.items), 2560)
        for item in self.bank.items:
            options = {option["key"]: option["text"] for option in item["options"]}
            self.assertEqual(item["answer_text"], [options[key] for key in item["answer"]])
            self.assertTrue(all(source["sheet"] in {"2026单选", "2026多选"} for source in item["sources"]))

    def test_source_option_count_issue_is_preserved(self):
        item = next(item for item in self.bank.items if any(source["sheet"] == "2026单选" and source["row"] == 1345 for source in item["sources"]))
        self.assertEqual(len(item["options"]), 2)
        self.assertEqual(item["answer_text"], ["正确"])
        self.assertEqual(self.bank.metadata["issues"][0]["actual"], 2)

    def test_partial_stem(self):
        result = self.bank.search("二类客车核定载人数")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["answer_text"], ["10至19人"])

    def test_full_copy_with_question_number_and_options(self):
        result = self.bank.search("99. 江西高速公路二类客车核定载人数为（  ）\nＡ. 10至20人\nＢ. 10至19人\nＣ. 10至21人\nＤ. 10至22人")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["answer"], ["B"])
        tagged = self.bank.search("【单选题】12. 江西高速公路二类客车核定载人数为（ ）")
        self.assertEqual(tagged["total"], 1)
        self.assertEqual(tagged["items"][0]["id"], result["items"][0]["id"])

    def test_distinct_options_are_not_merged(self):
        result = self.bank.search("下列哪项属于鲜活农产品减免范围( )。\nA. 活鸡鸭\nB. 基围虾\nC. 鱼苗\nD. 腌制海蜇")
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["items"][0]["answer_text"], ["基围虾"])
        self.assertEqual(result["items"][1]["answer_text"], ["皮皮虾"])

    def test_keywords_and_pagination(self):
        first = self.bank.search("二类 客车 核定载人数", page_size=1)
        second = self.bank.search("二类 客车 核定载人数", page=2, page_size=1)
        self.assertGreater(first["total"], 1)
        self.assertTrue(first["has_more"])
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])
        self.assertEqual(self.bank.search("收费", page=10000)["items"], [])

    def test_empty_unrelated_and_length_validation(self):
        for query in ("", " ", "?", "a", "不存在的题目阿尔法星舰发射答案"):
            self.assertEqual(self.bank.search(query)["items"], [])
        with self.assertRaises(ValueError):
            self.bank.search("题" * 1001)
        with self.assertRaises(ValueError):
            self.bank.search("收费", page=0)
        with self.assertRaises(ValueError):
            self.bank.search("收费", page_size=51)

    def test_typo_fallback(self):
        result = self.bank.search("对ETC门架设备的巡捡时间间隔应不大于")
        self.assertTrue(result["items"])
        self.assertEqual(result["items"][0]["answer_text"], ["4"])

    def test_similarity_cannot_change_numbers_or_negation(self):
        questions = []
        for stem in ("该车辆第三类车型核定人数应为19人", "收费人员不可以直接通过应急车道", "收费人员可以直接通过另一车道"):
            questions.append({"id": stem, "question": stem, "options": [{"key": "A", "text": "是"}], "answer": ["A"]})
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "questions.json"
            path.write_text(json.dumps({"questions": questions}), encoding="utf-8")
            bank = QuestionBank(path)
            for query in ("该车辆第三类车型核定人数应为18人", "该车辆第二类车型核定人数应为19人", "收费人员可以直接通过应急车道", "收费人员不可以直接通过另一车道"):
                self.assertEqual(bank.search(query)["total"], 0)

    def test_numeric_punctuation_keeps_meaning(self):
        self.assertNotEqual(normalize("10.5"), normalize("105"))
        self.assertNotEqual(normalize("-1"), normalize("1"))
        self.assertNotEqual(normalize("大于20%"), normalize("大于20"))
        self.assertEqual(query_parts("3.14米的高度")[0], "3.14米的高度")


if __name__ == "__main__":
    unittest.main()
