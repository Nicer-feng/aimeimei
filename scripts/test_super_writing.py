#!/usr/bin/env python3
"""超能写稿隔离回归：临时数据库与回环模拟模型，不访问真实供应商。"""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="aimeimei-super-writing-test-")
os.environ["AI_PLATFORM_DATA"] = TEMP.name
from app import AppHandler, AIPlatformServer
from ai_platform import super_writing, writing
from ai_platform.database import db, init_db
from ai_platform.runtime import now, token_hash
from file_share.database import init_share_db


class MockModels(BaseHTTPRequestHandler):
    """保存实际调用，按阶段返回可核对的独立用量。"""
    requests = []
    charged = []
    answer = ""
    plan = {}
    review = {}
    repair = {}
    broken_plan = False
    broken_review = False
    broken_summary_json = False
    failed_stage = ""
    finish_reason = "stop"
    omit_usage = False
    omit_main_usage = False
    usages = {
        "plan": {"prompt_tokens": 101, "completion_tokens": 17, "total_tokens": 118,
                 "prompt_tokens_details": {"cached_tokens": 20}},
        "check": {"prompt_tokens": 79, "completion_tokens": 11, "total_tokens": 90,
                  "prompt_tokens_details": {"cached_tokens": 9}},
        "repair": {"prompt_tokens": 83, "completion_tokens": 13, "total_tokens": 96},
        "main": {"prompt_tokens": 211, "completion_tokens": 37, "total_tokens": 248,
                 "prompt_tokens_details": {"cached_tokens": 30}},
        "summary": {"prompt_tokens": 103, "completion_tokens": 19, "total_tokens": 122},
    }

    def log_message(self, *args):
        pass

    @classmethod
    def stage(cls, body):
        if body.get("stream"):
            return "main"
        messages = body.get("messages") or body.get("input") or []
        text = str(messages[0].get("content", "")) if messages else ""
        if text.startswith("你是会话上下文压缩器"):
            return "summary"
        if text.startswith("超能槑槑局部修复"):
            return "repair"
        if text.startswith("超能槑槑交付校验"):
            return "check"
        return "plan"

    def do_POST(self):
        cls = type(self)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        stage = cls.stage(body)
        cls.requests.append({"stage": stage, "body": body})
        if stage == cls.failed_stage:
            self.send_response(503)
            self.end_headers()
            self.wfile.write(b'{"error":"fixture unavailable"}')
            return
        usage = cls.usages[stage]
        cls.charged.append({"stage": stage, "model": body["model"], "usage": usage})
        if body.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            event = {"choices": [{"delta": {"content": cls.answer},
                                   "finish_reason": cls.finish_reason}]}
            if not cls.omit_usage and not cls.omit_main_usage:
                event["usage"] = usage
            raw = ("data: " + json.dumps(event, ensure_ascii=False) + "\n\ndata: [DONE]\n\n").encode()
            for start in range(0, len(raw), 11):
                self.wfile.write(raw[start:start + 11])
            return
        value = cls.plan if stage == "plan" else cls.review if stage == "check" else cls.repair
        content = ("已保留本单拍摄条件和明确要求，后续改稿需逐条遵循。" if stage == "summary" else
                   "not-json" if (stage == "plan" and cls.broken_plan) or (stage == "check" and cls.broken_review) else json.dumps(value, ensure_ascii=False))
        result = {"choices": [{"message": {"content": content}}]}
        if not cls.omit_usage:
            result["usage"] = usage
        raw = json.dumps(result, ensure_ascii=False).encode()
        if stage == "summary" and cls.broken_summary_json:
            raw = b'not-a-json-response'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class QuietHandler(AppHandler):
    def log_message(self, *args):
        pass


class SuperWritingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db({"family_password_hash": "fixture-only"})
        init_db({"family_password_hash": "fixture-only"})
        init_share_db()
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), MockModels)
        threading.Thread(target=cls.upstream.serve_forever, daemon=True).start()
        cls.server = AIPlatformServer(("127.0.0.1", 0), QuietHandler, {"admin_key": "fixture-admin-key"})
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)
        with db() as conn:
            for uid, role in [("other", "family"), ("second-admin", "admin")]:
                conn.execute("INSERT INTO users(id,username,display_name,password_hash,role,is_active,created_at,updated_at) VALUES (?,?,?,'fixture',?,1,0,0)", (uid, uid, uid, role))
            for uid in ["default", "other", "second-admin"]:
                conn.execute("INSERT INTO sessions VALUES (?,?,?,?)", (token_hash("super-" + uid), uid, now(), now() + 3600))
            endpoint = "http://127.0.0.1:" + str(cls.upstream.server_port)
            for mid, model, ip, op in [("super-main", "qwen3.7-max", 12, 36), ("super-flash", "qwen3.8-flash", .8, 2.7)]:
                conn.execute("""INSERT INTO models(id,name,provider,base_url,api_key,model,enabled,
                    input_price_per_million,output_price_per_million,cost_enabled,supports_reasoning_control,created_at,updated_at)
                    VALUES (?,?,'fixture',?,'fixture-key',?,1,?,?,1,1,0,0)""", (mid, model, endpoint, model, ip, op))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.upstream.shutdown()
        cls.server.server_close()
        cls.upstream.server_close()
        TEMP.cleanup()

    def setUp(self):
        with db() as conn:
            conn.execute("DELETE FROM conversations")
            conn.execute("DELETE FROM daily_usage")
            conn.execute("UPDATE models SET enabled=1")
        MockModels.requests = []
        MockModels.charged = []
        MockModels.broken_plan = False
        MockModels.broken_review = False
        MockModels.broken_summary_json = False
        MockModels.failed_stage = ""
        MockModels.finish_reason = "stop"
        MockModels.omit_usage = False
        MockModels.omit_main_usage = False
        MockModels.answer = "封面文案：家用车的实用细节\n发布文案：一起看看测试车的日常用法。#测试车\n正文：\n今天咱们看看测试车，这里是前排12点按摩。坐进车里实际感受，喜不喜欢这种力度，还得看你自己的体验。\n\n再看后备箱，周末需要带哪些行李，可以现场摆一摆。"
        MockModels.plan = {
            "requirements": writing.requirements({"project": "测试车", "format": "线下单人口播", "required": ["测试车"], "min_chars": 30, "max_chars": 800, "facts": "前排12点按摩；两驱版前备箱106L。"}),
            "intent": "draft", "scope": "完整口播稿", "full_manuscript": True,
            "replace_text": "", "pasted_draft": "", "confirmed": False, "new_project": False,
        }
        MockModels.review = {"issues": [], "patches": [], "passed": True, "status": "passed"}
        MockModels.repair = {"patches": []}
        self.cid = self.create()

    def request(self, path, body=None, method=None, user="default"):
        request = urllib.request.Request(self.base + path,
            data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
            headers={"Cookie": "ap_session=super-" + user, "Content-Type": "application/json"}, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read().decode()
                return response.status, raw if "text/event-stream" in response.headers.get("Content-Type", "") else json.loads(raw)
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def create(self, user="default", **fields):
        status, result = self.request("/api/conversations", {"model_id": "super-main", **fields}, user=user)
        self.assertEqual(status, 201, result)
        return result["conversation"]["id"]

    def workspace(self, cid=None):
        status, result = self.request(f"/api/conversations/{cid or self.cid}/super-writing")
        self.assertEqual(status, 200, result)
        return result

    def enable(self, enabled=True, cid=None):
        cid = cid or self.cid
        state = self.workspace(cid)
        return self.request(f"/api/conversations/{cid}/super-writing", {"revision": state["revision"], "enabled": enabled}, "PATCH")

    def final(self, content, cid=None, **extra):
        cid = cid or self.cid
        return self.request(f"/api/conversations/{cid}/final-deliveries", {"revision": self.workspace(cid)["revision"], "content": content, **extra}, "POST")

    def send(self, text="请写一条测试车单人口播稿。材料：前排12点按摩、两驱版前备箱106L。不要编造其他资料。", cid=None):
        return self.request(f"/api/conversations/{cid or self.cid}/messages", {"content": text, "web_search": False})

    def rows(self, cid=None):
        with db() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (cid or self.cid,))]

    def assert_accounting(self):
        expected = sum(item["usage"]["total_tokens"] for item in MockModels.charged)
        rows = self.rows()
        self.assertEqual(sum(row["total_tokens"] for row in rows), expected)
        with db() as conn:
            recorded = conn.execute("SELECT COALESCE(SUM(total_tokens),0) FROM daily_usage WHERE user_id='default'").fetchone()[0]
        self.assertEqual(recorded, expected)
        status, result = self.request(f"/api/conversations/{self.cid}/stats")
        self.assertEqual(status, 200)
        self.assertEqual(result["stats"]["total_tokens"], expected)
        prices = {"qwen3.7-max": (12, 36), "qwen3.8-flash": (.8, 2.7)}
        cost = sum((item["usage"]["prompt_tokens"] * prices[item["model"]][0]
                   + item["usage"]["completion_tokens"] * prices[item["model"]][1]) / 1000000
                   for item in MockModels.charged)
        self.assertAlmostEqual(sum(row["estimated_cost"] for row in rows), cost, places=7)
        with db() as conn:
            daily = conn.execute("SELECT COALESCE(SUM(request_count),0),COALESCE(SUM(estimated_cost),0) FROM daily_usage WHERE user_id='default'").fetchone()
        self.assertEqual(daily[0], len(MockModels.charged))
        self.assertAlmostEqual(daily[1], cost, places=7)
        for row in rows:
            if row["role"] == "system" and row["total_tokens"]:
                self.assertEqual(row["actual_model"], "qwen3.8-flash" if row["cost_model_id"] == "super-flash" else "qwen3.7-max")

    def test_default_off_and_per_conversation_switch(self):
        self.assertTrue(self.workspace()["eligible"])
        self.assertFalse(self.workspace()["enabled"])
        second = self.create()
        self.assertEqual(self.enable()[0], 200)
        self.assertTrue(self.workspace()["enabled"])
        self.assertFalse(self.workspace(second)["enabled"])
        third = self.create()
        self.assertFalse(self.workspace(third)["enabled"])
        self.assertEqual(self.enable(False)[0], 200)
        self.assertFalse(self.workspace()["enabled"])
        self.assertEqual(MockModels.requests, [])

    def test_only_bound_account_may_use_mode_or_deliveries(self):
        for user in ["other", "second-admin"]:
            other_cid = self.create(user=user)
            for cid in [self.cid, other_cid]:
                with self.subTest(user=user, cid=cid):
                    for method, suffix, body in [("GET", "super-writing", None), ("PATCH", "super-writing", {"revision": 0, "enabled": True}), ("POST", "final-deliveries", {"revision": 0, "content": "越权内容"})]:
                        status, result = self.request(f"/api/conversations/{cid}/{suffix}", body, method, user)
                        self.assertIn(status, [403, 404], result)
        self.assertFalse(self.workspace()["enabled"])

    def test_delivery_update_preserves_versions_and_never_calls_model(self):
        first = "客户已验收第一版。\n\n第二段的文字应当原样保存。"
        status, result = self.final(first, filename="客户稿.txt")
        self.assertIn(status, [200, 201], result)
        state = self.workspace()
        self.assertEqual(state["delivery"]["content"], first)
        self.assertEqual(state["delivery"]["source"], "customer")
        first_id = state["delivery"]["id"]
        second = first + "\n\n客户验收后的新版本。"
        self.assertIn(self.final(second)[0], [200, 201])
        updated = self.workspace()
        self.assertNotEqual(updated["delivery"]["id"], first_id)
        self.assertEqual(updated["delivery"]["content"], second)
        self.assertGreaterEqual(len(updated["versions"]), 2)
        self.assertEqual(MockModels.requests, [])
        self.assertEqual(self.rows(), [])

    def test_delivery_document_uses_owner_full_text_without_chat_attachment(self):
        content = "客户上传的完整终稿。\n\n" + "此处保留最终口播原文，不应被材料检索截成片段。" * 8
        with db() as conn:
            for did, uid, status, parsed, count in [("final-ok", "default", "completed", content, 1),
                                                   ("final-other", "other", "completed", "其他账号文本", 1),
                                                   ("final-wait", "default", "processing", "", 0),
                                                   ("final-incomplete", "default", "completed", "", 2)]:
                conn.execute("INSERT INTO document_files(id,user_id,filename,oss_key,status,parsed_text,chunk_count,created_at,updated_at) VALUES (?,?,?,'fixture-key',?,?,?,0,0)", (did, uid, did + ".docx", status, parsed, count))
            conn.execute("INSERT INTO document_chunks(document_id,user_id,ordinal,content,created_at) VALUES ('final-ok','default',0,?,0)", (content,))
            conn.execute("INSERT INTO document_chunks(document_id,user_id,ordinal,content,created_at) VALUES ('final-incomplete','default',0,'只解析到一部分',0)")
        for did in ["final-other", "final-wait", "final-incomplete"]:
            status, result = self.request(f"/api/conversations/{self.cid}/final-deliveries", {"revision": self.workspace()["revision"], "document_id": did}, "POST")
            self.assertEqual(status, 400, result)
        status, result = self.request(f"/api/conversations/{self.cid}/final-deliveries", {"revision": self.workspace()["revision"], "document_id": "final-ok"}, "POST")
        self.assertIn(status, [200, 201], result)
        self.assertEqual(self.workspace()["delivery"]["content"], content)
        self.assertEqual(self.workspace()["delivery"]["filename"], "final-ok.docx")
        with db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM conversation_documents WHERE conversation_id=?", (self.cid,)).fetchone()[0], 0)
        self.assertEqual(MockModels.requests, [])

    def test_stale_revision_invalid_type_and_generation_lock(self):
        state = self.workspace()
        self.enable()
        self.assertEqual(self.request(f"/api/conversations/{self.cid}/super-writing", {"revision": state["revision"], "enabled": False}, "PATCH")[0], 409)
        state = self.workspace()
        self.assertEqual(self.request(f"/api/conversations/{self.cid}/super-writing", {"revision": state["revision"], "enabled": "true"}, "PATCH")[0], 400)
        with writing.task_lock("default", self.cid):
            self.assertEqual(self.request(f"/api/conversations/{self.cid}/super-writing", {"revision": state["revision"], "enabled": False}, "PATCH")[0], 409)
            self.assertEqual(self.request(f"/api/conversations/{self.cid}/final-deliveries", {"revision": state["revision"], "content": "生成时不能覆盖客户稿"}, "POST")[0], 409)

    def test_off_path_is_single_main_call_and_no_enhancement(self):
        self.assertEqual(self.send()[0], 200)
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main"])
        payload = json.dumps(MockModels.requests[0]["body"], ensure_ascii=False)
        self.assertNotIn("超能槑槑", payload)
        self.assertEqual(len([row for row in self.rows() if row["role"] == "system"]), 0)
        self.assert_accounting()

    def test_enabled_checks_and_usage_belongs_to_current_conversation(self):
        self.enable()
        status, stream = self.send()
        self.assertEqual(status, 200)
        stages = [item["stage"] for item in MockModels.requests]
        self.assertEqual(stages.count("main"), 1, stages)
        self.assertIn("check", stages)
        self.assert_accounting()
        _, history = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertTrue(all(row["role"] != "system" for row in history["messages"]))
        self.assertIn(MockModels.answer, history["messages"][-1]["content"])

    def test_failed_main_still_keeps_completed_auxiliary_usage(self):
        self.enable()
        MockModels.failed_stage = "main"
        status, result = self.send()
        self.assertEqual(status, 502, result)
        self.assertGreater(len(MockModels.charged), 0)
        self.assert_accounting()
        self.assertEqual(self.rows()[-1]["generation_status"], "failed")

    def test_broken_review_returns_original_and_keeps_its_usage(self):
        self.enable()
        MockModels.broken_review = True
        status, stream = self.send()
        self.assertEqual(status, 200)
        self.assert_accounting()
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        reply = result["messages"][-1]
        self.assertEqual(reply["content"], MockModels.answer)
        check = reply.get("super_check") or {}
        self.assertNotEqual(check.get("status"), "passed")

    def test_review_http_failure_keeps_original_and_marks_unknown_usage(self):
        self.enable()
        MockModels.failed_stage = "check"
        self.assertEqual(self.send()[0], 200)
        self.assert_accounting()
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        reply = result["messages"][-1]
        self.assertEqual(reply["content"], MockModels.answer)
        check = reply.get("super_check") or {}
        self.assertNotEqual(check.get("status"), "passed")
        self.assertTrue(check.get("usage_unknown"))

    def test_missing_usage_is_not_fabricated_or_reported_as_known(self):
        self.enable()
        MockModels.omit_usage = True
        self.assertEqual(self.send()[0], 200)
        rows = self.rows()
        self.assertTrue(any(row["role"] == "system" for row in rows))
        self.assertEqual(sum(row["total_tokens"] for row in rows), 0)
        self.assertEqual(sum(row["estimated_cost"] for row in rows), 0)
        self.assertTrue(any(row["generation_status"] == "usage_unknown" for row in rows))
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertTrue(result["messages"][-1]["super_check"]["usage_unknown"])

    def test_missing_main_usage_is_visible_even_when_auxiliary_usage_is_known(self):
        self.enable()
        MockModels.omit_main_usage = True
        self.assertEqual(self.send()[0], 200)
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        reply = result["messages"][-1]
        self.assertTrue(reply["super_check"]["usage_unknown"])
        expected = sum(item["usage"]["total_tokens"] for item in MockModels.charged if item["stage"] != "main")
        self.assertEqual(sum(row["total_tokens"] for row in self.rows()), expected)

    def test_missing_flash_falls_back_without_phantom_auxiliary_usage(self):
        self.enable()
        with db() as conn:
            conn.execute("UPDATE models SET enabled=0 WHERE id='super-flash'")
        status, stream = self.send()
        self.assertEqual(status, 200)
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main"])
        self.assert_accounting()
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertEqual(result["messages"][-1]["content"], MockModels.answer)
        self.assertNotEqual((result["messages"][-1].get("super_check") or {}).get("status"), "passed")

    def test_broken_plan_is_charged_and_does_not_abort_main(self):
        self.enable()
        MockModels.broken_plan = True
        self.assertEqual(self.send()[0], 200)
        self.assertEqual(sum(item["stage"] == "main" for item in MockModels.requests), 1)
        self.assert_accounting()

    def test_evidence_based_repair_is_local_and_runs_at_most_once(self):
        self.enable()
        MockModels.answer = MockModels.answer.replace("前排12点按摩", "全车12点按摩")
        MockModels.review = {"issues": [{"quote": "全车12点按摩", "reason": "把前排范围改成了全车", "evidence": "本轮材料明确为前排", "source_quote": "前排12点按摩", "severity": "error"}]}
        MockModels.repair = {"patches": [{"old": "全车12点按摩", "new": "前排12点按摩"}]}
        self.assertEqual(self.send()[0], 200)
        stages = [item["stage"] for item in MockModels.requests]
        self.assertEqual(stages.count("main"), 1)
        self.assertEqual(stages.count("repair"), 1)
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        final = result["messages"][-1]["content"]
        self.assertEqual(final, MockModels.answer.replace("全车12点按摩", "前排12点按摩"))
        self.assert_accounting()

    def test_unsubstantiated_review_cannot_trigger_rewrite(self):
        self.enable()
        MockModels.review = {"issues": [{"quote": "前排12点按摩", "reason": "凭空推测按摩点数错误", "evidence": "没有本单来源", "source_quote": "全车20点按摩", "severity": "error"}]}
        self.assertEqual(self.send()[0], 200)
        self.assertNotIn("repair", [item["stage"] for item in MockModels.requests])
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertEqual(result["messages"][-1]["content"], MockModels.answer)
        self.assert_accounting()

    def test_incomplete_main_keeps_actual_usage_and_is_not_reviewed_as_passed(self):
        self.enable()
        MockModels.finish_reason = "length"
        self.assertEqual(self.send()[0], 200)
        self.assert_accounting()
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        reply = result["messages"][-1]
        self.assertNotEqual(reply["generation_status"], "completed")
        self.assertNotEqual((reply.get("super_check") or {}).get("status"), "passed")

    def test_overbroad_repair_preserves_original_and_records_cost(self):
        self.enable()
        MockModels.answer = MockModels.answer.replace("前排12点按摩", "全车12点按摩")
        MockModels.review = {"issues": [{"quote": "全车12点按摩", "reason": "范围不一致", "evidence": "本轮材料", "source_quote": "前排12点按摩", "severity": "error"}]}
        MockModels.repair = {"patches": [{"old": MockModels.answer, "new": "完全重写整篇稿件，不保留任何原文。"}]}
        self.assertEqual(self.send()[0], 200)
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertEqual(result["messages"][-1]["content"], MockModels.answer)
        self.assertLessEqual(sum(item["stage"] == "repair" for item in MockModels.requests), 1)
        self.assert_accounting()

    def test_explicit_local_edit_merges_without_changing_other_text(self):
        self.enable()
        before = "首段必须逐字保留，事实不能顺手更改。\n\n中间这段需要改写，口吻太平。\n\n最后一段必须逐字保留。"
        after = "中间换成自然顺嘴的现场解释。"
        with db() as conn:
            super_writing.save_task_state(conn, self.cid, "default", {"draft": before})
        MockModels.plan.update(intent="revise", full_manuscript=False, replace_text="中间这段需要改写，口吻太平。")
        MockModels.answer = after
        self.assertEqual(self.send("只改中间这一段，其他段落一个字都不要动")[0], 200)
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertEqual(result["messages"][-1]["content"], before.replace("中间这段需要改写，口吻太平。", after))
        self.assert_accounting()

    def test_local_edit_rejects_full_manuscript_or_oversized_segment(self):
        before = "首段必须逐字保留。\n\n中间这段需要改写，口吻太平。\n\n末段也必须逐字保留。"
        self.enable()
        for answer in ["封面文案：擅自重写\n发布文案：另一个版本\n正文：\n整篇稿件都被重写了。", "非常长的替换段。" * 150]:
            with self.subTest(answer_chars=len(answer)):
                with db() as conn:
                    super_writing.save_task_state(conn, self.cid, "default", {"draft": before})
                MockModels.plan.update(intent="revise", full_manuscript=False, replace_text="中间这段需要改写，口吻太平。")
                MockModels.answer = answer
                self.assertEqual(self.send("只改中间这一段，其余不要动")[0], 200)
                _, result = self.request(f"/api/conversations/{self.cid}/messages")
                reply = result["messages"][-1]
                self.assertEqual(reply["content"], before)
                self.assertEqual(reply["super_check"]["status"], "issues")
                with db() as conn:
                    self.assertEqual(super_writing.get_task_state(conn, self.cid, "default")["draft"], before)
        self.assert_accounting()

    def test_local_edit_repair_cannot_change_other_paragraphs(self):
        before = "首段旧数据为全车12点按摩，按用户要求这一段不得修改。\n\n中间这段需要改写。\n\n末段也必须保持不动。"
        replacement = "这台车前备箱容积有200升。"
        self.enable()
        with db() as conn:
            super_writing.save_task_state(conn, self.cid, "default", {"draft": before})
        MockModels.plan.update(intent="revise", full_manuscript=False, replace_text="中间这段需要改写。")
        MockModels.answer = replacement
        MockModels.review = {"issues": [
            {"quote": "全车12点按摩", "reason": "原文范围错误但属于禁止修改的旧段", "evidence": "本轮材料", "source_quote": "前排12点按摩", "severity": "error"},
            {"quote": replacement, "reason": "新段容积数据错误", "evidence": "本轮材料", "source_quote": "两驱版前备箱106L", "severity": "error"},
        ]}
        MockModels.repair = {"patches": [{"old": replacement, "new": "这台车两驱版前备箱容积106升。"}]}
        self.assertEqual(self.send("只改中间这一段，首尾不动。材料：前排12点按摩、两驱版前备箱106L。")[0], 200)
        repair = [item for item in MockModels.requests if item["stage"] == "repair"]
        self.assertEqual(len(repair), 1)
        repair_input = json.loads(repair[0]["body"]["messages"][-1]["content"])
        self.assertNotIn("全车12点按摩", repair_input["allowed_changes"])
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        expected = before.replace("中间这段需要改写。", "这台车两驱版前备箱容积106升。")
        self.assertEqual(result["messages"][-1]["content"], expected)
        self.assert_accounting()

    def test_auxiliary_messages_do_not_enter_next_main_context(self):
        self.enable()
        self.send()
        first_aux = [row["content"] for row in self.rows() if row["role"] == "system"]
        self.assertTrue(first_aux)
        self.send("在这版基础上再写一个口播稿，要求不变。")
        payload = json.dumps([item for item in MockModels.requests if item["stage"] == "main"][-1]["body"], ensure_ascii=False)
        for content in first_aux:
            self.assertNotIn(content, payload)
        self.assert_accounting()

    def test_switching_off_stops_new_auxiliary_calls(self):
        self.enable()
        self.send()
        before = len(MockModels.requests)
        self.enable(False)
        self.assertEqual(self.send("沿用现有稿件，继续正常聊天")[0], 200)
        self.assertEqual([item["stage"] for item in MockModels.requests[before:]], ["main"])
        payload = json.dumps(MockModels.requests[-1]["body"], ensure_ascii=False)
        self.assertNotIn("表达参考；", payload)
        self.assert_accounting()

    def test_super_mode_does_not_duplicate_legacy_writing_planner(self):
        with db() as conn:
            conn.execute("UPDATE conversations SET writing_mode=1 WHERE id=?", (self.cid,))
        self.enable()
        self.assertEqual(self.send()[0], 200)
        self.assertEqual(sum(item["stage"] == "plan" for item in MockModels.requests), 1)
        self.assert_accounting()

    def test_uploaded_customer_delivery_is_locked_for_storyboard(self):
        original = "客户已通过的第一段，逐字保留。\n\n客户已通过的第二段，不要擅自润色。"
        self.assertIn(self.final(original)[0], [200, 201])
        self.enable()
        MockModels.plan.update(intent="storyboard", full_manuscript=False)
        MockModels.answer = "| 台词 | 画面 |\n| --- | --- |\n| 偷改客户已通过的台词 | 汽车 |"
        status, stream = self.send("把客户通过稿整理成分镜表格，台词一个字不动")
        self.assertEqual(status, 200)
        self.assertNotIn("偷改客户", stream)
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertTrue(writing.locked_storyboard(original, result["messages"][-1]["content"]))
        self.assert_accounting()

    def test_background_summary_usage_is_charged_to_current_conversation(self):
        self.enable()
        with db() as conn:
            for index in range(24):
                conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('default',?,?,?,?)", (self.cid, "user" if index % 2 == 0 else "assistant", "本单要求或稿件-%02d" % index, index))
        QuietHandler.run_context_summary_job(("default", self.cid), self.cid, "default")
        self.assertEqual([item["stage"] for item in MockModels.requests], ["summary"])
        self.assert_accounting()
        with db() as conn:
            row = conn.execute("SELECT context_summary,context_summary_message_id FROM conversations WHERE id=?", (self.cid,)).fetchone()
        self.assertIn("已保留本单拍摄条件", row["context_summary"])
        self.assertGreater(row["context_summary_message_id"], 0)
        status, result = self.request(f"/api/conversations/{self.cid}/stats")
        self.assertEqual(result["stats"]["message_count"], 24)

    def test_invalid_summary_response_records_unknown_call(self):
        self.enable()
        with db() as conn:
            for index in range(24):
                conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('default',?,?,?,?)", (self.cid, "user" if index % 2 == 0 else "assistant", "需要摘要的原文-%02d" % index, index))
        MockModels.broken_summary_json = True
        QuietHandler.run_context_summary_job(("default", self.cid), self.cid, "default")
        self.assertEqual([item["stage"] for item in MockModels.requests], ["summary"])
        aux = [row for row in self.rows() if row["role"] == "system"]
        self.assertEqual(len(aux), 1)
        self.assertEqual(aux[0]["generation_status"], "usage_unknown")
        self.assertEqual(aux[0]["total_tokens"], 0)
        self.assertEqual(aux[0]["cost_model_id"], "super-main")

    def test_admin_usage_and_cost_include_auxiliary_actual_models(self):
        self.enable()
        self.assertEqual(self.send()[0], 200)
        self.assert_accounting()
        expected = sum(item["usage"]["total_tokens"] for item in MockModels.charged)
        status, tokens = self.request("/api/admin/token-stats?view=all")
        self.assertEqual(status, 200)
        self.assertEqual(tokens["summary"]["total_tokens"], expected)
        self.assertEqual(tokens["summary"]["total_requests"], len(MockModels.charged))
        for model_id, code in [("super-main", "qwen3.7-max"), ("super-flash", "qwen3.8-flash")]:
            model = next(row for row in tokens["models"] if row["id"] == model_id)
            charged = [item for item in MockModels.charged if item["model"] == code]
            self.assertEqual(model["total_tokens"], sum(item["usage"]["total_tokens"] for item in charged))
            status, details = self.request("/api/admin/token-stats/details?type=models&id=" + model_id)
            self.assertEqual(status, 200)
            self.assertEqual(len(details["recent_requests"]), len(charged))
            self.assertTrue(all(row["model_code"] == code for row in details["recent_requests"]))
        status, costs = self.request("/api/admin/cost-stats?range=all")
        self.assertEqual(status, 200)
        self.assertEqual(costs["summary"]["range_total_tokens"], expected)
        with db() as conn:
            total_cost = conn.execute("SELECT SUM(estimated_cost) FROM messages WHERE conversation_id=?", (self.cid,)).fetchone()[0]
        self.assertAlmostEqual(costs["summary"]["total_cost"], total_cost, places=7)
        self.assertEqual({row["model_code"] for row in costs["models"]}, {"qwen3.7-max", "qwen3.8-flash"})

    def test_smart_summary_preserves_uncovered_messages(self):
        markers = []
        with db() as conn:
            for index in range(20):
                marker = "不可丢失的原文要求-%02d" % index
                cursor = conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('default',?,?,?,?)", (self.cid, "user" if index % 2 == 0 else "assistant", marker, index))
                markers.append((cursor.lastrowid, marker))
            conn.execute("UPDATE conversations SET context_mode='smart',context_summary='摘要仅覆盖最早两条',context_summary_message_id=? WHERE id=?", (markers[1][0], self.cid))
        self.assertEqual(self.send("继续根据现有要求写稿")[0], 200)
        payload = json.dumps(MockModels.requests[-1]["body"], ensure_ascii=False)
        for _, marker in markers[2:]:
            self.assertIn(marker, payload)

    def test_inference_excludes_comments_and_recovers_user_confirmed_body(self):
        body = "正文：\n这是单人现场体验的口播正文。" + "要讲清楚功能怎样解决日常问题。" * 8
        messages = [{"id": 1, "role": "user", "content": "请写汽车口播稿"},
                    {"id": 2, "role": "assistant", "content": body},
                    {"id": 3, "role": "user", "content": body + "\n\nok，这个是最终脚本，一个字不要动，转分镜。"},
                    {"id": 4, "role": "assistant", "content": "| 台词 | 画面 |\n| --- | --- |\n| 这是单人现场体验的口播正文。 | 车旁 |"},
                    {"id": 5, "role": "user", "content": "再给我十条评论和回复"},
                    {"id": 6, "role": "assistant", "content": "1. 评论：车看着不错\n回复：欢迎体验"}]
        candidate = super_writing.infer_delivery(messages)
        self.assertIsNotNone(candidate)
        self.assertIn("单人现场体验", candidate["content"])
        self.assertNotIn("评论：", candidate["content"])
        self.assertNotIn("一个字不要动", candidate["content"])

    def test_user_confirmed_manuscript_has_priority_over_later_storyboard(self):
        final = "用户确认正文独有标记。" + "每一段口播都应保留原文，客户已经验收。" * 10
        altered = "后续分镜改坏的内容。" + "错误版本不应取代用户明确贴回的终稿。" * 10
        messages = [{"id": 1, "role": "user", "content": final + "\n\n这个是最终脚本，一个字不要动，转分镜。"},
                    {"id": 2, "role": "assistant", "content": "| 台词 | 画面 |\n| --- | --- |\n| " + altered + " | 车旁 |"}]
        candidate = super_writing.infer_delivery(messages)
        self.assertIsNotNone(candidate)
        self.assertIn("用户确认正文独有标记", candidate["content"])
        self.assertNotIn("后续分镜改坏", candidate["content"])

    def test_reference_threshold_excludes_inferred_and_other_account(self):
        fallback_cid = self.create(title="测试车线下口播")
        fallback = "正文：\n推定样例独有标记。" + "测试车的空间要结合实际行李解释，不能只报数据。" * 8
        with db() as conn:
            conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('default',?,'user','写一条测试车现场口播稿',0)", (fallback_cid,))
            conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('default',?,'assistant',?,1)", (fallback_cid, fallback))
        with db() as conn:
            early = super_writing.reference_context(conn, "default", self.cid, "测试车现场口播")
        self.assertIn("推定样例独有标记", early)
        for index in range(10):
            cid = self.create(title="测试车线下口播任务%02d" % index)
            self.assertIn(self.final("正文：\n客户确认样例%02d，测试车要把数据和生活场景联系起来。" % index, cid=cid)[0], [200, 201])
        other = self.create(user="other", title="别账号测试车")
        with db() as conn:
            conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('other',?,'assistant',?,1)", (other, "正文：别账号绝密样例不能混入。" + "测试车场景。" * 30))
            ready = super_writing.reference_context(conn, "default", self.cid, "测试车现场口播")
        self.assertNotIn("推定样例独有标记", ready)
        self.assertNotIn("别账号绝密样例", ready)
        self.assertIn("客户确认样例", ready)
        self.assertLessEqual(len(ready), 2400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
