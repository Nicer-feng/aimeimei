#!/usr/bin/env python3
"""超能修稿隔离回归：临时数据库与回环模拟模型，不访问真实供应商。"""
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
from ai_platform import super_revision, super_writing, writing
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
        cls.requests.append({"stage": stage, "body": body, "path": self.path, "headers": dict(self.headers)})
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
            if self.path.endswith("/responses"):
                response = {"status": "completed"}
                if not cls.omit_usage and not cls.omit_main_usage:
                    response["usage"] = usage
                events = [{"type": "response.output_text.delta", "delta": cls.answer},
                          {"type": "response.completed", "response": response}]
            else:
                event = {"choices": [{"delta": {"content": cls.answer},
                                       "finish_reason": cls.finish_reason}]}
                if not cls.omit_usage and not cls.omit_main_usage:
                    event["usage"] = usage
                events = [event]
            raw = ("".join("data: " + json.dumps(event, ensure_ascii=False) + "\n\n" for event in events) + "data: [DONE]\n\n").encode()
            for start in range(0, len(raw), 11):
                self.wfile.write(raw[start:start + 11])
            return
        value = cls.plan if stage == "plan" else cls.review if stage == "check" else cls.repair
        if stage == "check":
            data = json.loads(body["messages"][-1]["content"])
            value = value(data) if callable(value) else dict(value)
            if "issues" in value and isinstance(value["issues"], list):
                value["issues"] = [item(data) if callable(item) else item for item in value["issues"]]
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


class ScopedRevisionRulesTests(unittest.TestCase):
    def test_natural_word_order_keeps_the_exact_requested_range(self):
        draft = "标题：保留\n正文：\n这里是第一段。\n\n这里是第二段。\n\n这里是结尾。"
        for instruction, target, paragraph, original in (
            ("结尾也改下吧 感觉和前面的内容不是很搭配", "结尾", 0, "这里是结尾。"),
            ("第一段要重新写啊 不能按照这个版本来写", "第一段", 1, "这里是第一段。"),
            ("第二段换个说法", "第二段", 2, "这里是第二段。"),
            ("开场再润色一下", "开头", 0, "这里是第一段。"),
            ("改下结尾吧", "结尾", 0, "这里是结尾。"),
        ):
            with self.subTest(instruction=instruction):
                request = super_revision.parse_request(instruction)
                self.assertEqual((request.target, request.paragraph, request.instruction), (target, paragraph, instruction))
                plan = super_revision.prepare(request, draft)
                result, report = super_revision.apply_result(plan, '{"replacement":"本次修改。"}', True)
                self.assertTrue(report["repaired"])
                self.assertEqual(result, draft.replace(original, "本次修改。"))

    def test_pasted_draft_is_selected_instead_of_latest_reply(self):
        draft = "封面文案：保持标题\n正文：\n开头。\n\n这里才是用户贴回来的结尾。"
        request = super_revision.parse_request(draft + "\n就在这个基础上改 只需要改结尾 改成推荐大家去试驾")
        plan = super_revision.prepare(request, "正文：\n另一篇开头。\n另一篇结尾。")
        result, report = super_revision.apply_result(plan, '{"replacement":"可以去试一试。"}', True)
        self.assertEqual(result, draft.replace("这里才是用户贴回来的结尾。", "可以去试一试。"))
        self.assertTrue(report["repaired"])

    def test_nonlocal_and_conflicting_requests_are_not_treated_as_local(self):
        for text in ("这个不太对", "重写整篇稿子", "你觉得这个结尾怎么样？", "第一段要改吗？",
                     "结尾改得怎么样？", "第一段不用改", "结尾怎么改？", "开头改完以后说了什么？"):
            self.assertIsNone(super_revision.parse_request(text))
        for text in ("只改这段", "只改结尾，顺便修改标题", "只改结尾。删掉开头",
                     "结尾也改下吧，第一段要重新写", "第一段要重新写，结尾也调整一下",
                     "结尾也改下吧，重写全文"):
            with self.assertRaises(super_revision.ScopeError):
                super_revision.parse_request(text)

    def test_explicit_length_counts_body_only_and_retains_unmodified_spaces(self):
        draft = "封面文案：不会计入正文字数\r\n正文：\r\n第一段。  \r\n\r\n原结尾。\r\n#话题"
        plan = super_revision.prepare(super_revision.parse_request("改下结尾，正文约750字"), draft)
        result, report = super_revision.apply_result(plan, '{"replacement":"新结尾。"}', True)
        self.assertEqual(result, draft.replace("原结尾。", "新结尾。"))
        self.assertIn("正文约 8 字，目标约 750 字", report["notice"])

    def test_explicit_cancellation_and_incomplete_output(self):
        draft = "正文：\n第一段。\n结尾。"
        plan = super_revision.prepare(super_revision.parse_request("改下结尾"), draft,
                                      ["禁止使用「词语」", "取消禁用「词语」"])
        self.assertEqual(plan.bans, ())
        self.assertEqual(super_revision.apply_result(plan, '{"replacement":"词语"}', False)[0], draft)

    def test_invalid_table_is_refused_and_extra_model_cells_are_not_inserted(self):
        draft = "| 段落 | 时长 | 口播内容 |\n| --- | --- | --- |\n| 1 | 12s | 台词 |"
        request = super_revision.parse_request("加一列景别")
        with self.assertRaises(super_revision.ScopeError):
            super_revision.prepare(request, draft.replace("12s | 台词", "12s | 多余 | 台词"))
        plan = super_revision.prepare(request, draft)
        for bad in ('{"shots":["近景","中景"]}', '{"shots":["中景 | 越界"]}'):
            self.assertEqual(super_revision.apply_result(plan, bad, True)[0], draft)


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
            conn.execute("DELETE FROM user_profiles")
            conn.execute("UPDATE models SET enabled=1,supports_native_web_search=0,system_prompt=''")
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
        MockModels.review = {"issues": []}
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

    def send(self, text="请写一条测试车单人口播稿。必带词：测试车。材料：前排12点按摩、两驱版前备箱106L。不要编造其他资料。", cid=None):
        return self.request(f"/api/conversations/{cid or self.cid}/messages", {"content": text, "web_search": False})

    def rows(self, cid=None):
        with db() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (cid or self.cid,))]

    def last_reply(self):
        status, result = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertEqual(status, 200, result)
        return result["messages"][-1]

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
        # 前端合并用量包含主生成与辅助调用；数据库仍逐调用记账，不能重复累加。
        with db() as conn:
            checks = conn.execute("SELECT message_id,result_json FROM super_checks WHERE user_id='default' AND message_id IN (SELECT id FROM messages WHERE conversation_id=?)", (self.cid,)).fetchall()
        by_id = {row["id"]: row for row in rows}
        for row in checks:
            check = json.loads(row["result_json"])
            main = by_id[row["message_id"]]
            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"):
                combined = main[key] + sum(call[key] for call in check.get("calls", []))
                self.assertEqual(check["usage"][key], combined)
            combined_cost = main["estimated_cost"] + sum(call["estimated_cost"] for call in check.get("calls", []))
            self.assertAlmostEqual(check["usage"]["estimated_cost"], combined_cost, places=7)

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

    def assert_primary_request_identical(self, native_capable, web_search, legacy_writing=False):
        off_cid = self.create()
        on_cid = self.create()
        raw_request = ("请按原始要求写测试车口播稿。正文700至800字，禁用词：智驾。必带词：测试车。\n"
                       + "本单原始材料须完整保留，数字条件和原话不要预先压缩。" * 60
                       + "\n前排12点按摩；两驱版前备箱106L。用户最后一句不能丢。")
        doc_id = off_cid + "-material"
        history = [("user", "摘要水位前的原始请求，主生成不应重复追加。"),
                   ("assistant", "摘要水位前的旧回答。"),
                   ("user", "摘要水位之后的用户拍摄限制，只有一人出镜。"),
                   ("assistant", "上一条原始回答，不能被超能任务状态替代。")]
        with db() as conn:
            conn.execute("UPDATE models SET supports_native_web_search=?,system_prompt='模型后台已有指令必须原样保留。' WHERE id='super-main'", (int(native_capable),))
            conn.execute("INSERT INTO user_profiles(id,user_id,title,content,enabled,created_at,updated_at) VALUES (?,'default','既有档案','用户已启用的原有档案内容。',1,0,0)", (off_cid + "-profile",))
            conn.execute("INSERT INTO document_files(id,user_id,filename,oss_key,status,parsed_text,chunk_count,created_at,updated_at) VALUES (?,'default','本单材料.txt','fixture','completed','仅有本单附件证据。前排12点按摩。',1,0,0)", (doc_id,))
            conn.execute("INSERT INTO document_chunks(document_id,user_id,ordinal,content,created_at) VALUES (?,'default',0,'仅有本单附件证据。前排12点按摩。',0)", (doc_id,))
            for cid in (off_cid, on_cid):
                ids = []
                for index, (role, content) in enumerate(history):
                    ids.append(conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('default',?,?,?,?)", (cid, role, content, index)).lastrowid)
                conn.execute("UPDATE conversations SET context_mode='smart',context_summary='本单早期工作摘要必须保持原样。',context_summary_message_id=?,writing_mode=? WHERE id=?", (ids[1], int(legacy_writing), cid))
                conn.execute("INSERT INTO conversation_documents(conversation_id,document_id,user_id,created_at) VALUES (?,?,'default',0)", (cid, doc_id))
                super_writing.save_task_state(conn, cid, "default", {"draft": "旧超能底稿不得注入主请求。", "requirements": {"tone": "旧超能口吻不得干预主生成"}})
                if legacy_writing:
                    state = writing.get_state(conn, cid, "default")
                    state["history_start_id"] = ids[2]
                    writing.save_state(conn, state)
        for cid in (off_cid, on_cid):
            self.assertIn(self.final("本单上传终稿的独有句子，不能静默进入原流程请求。", cid=cid)[0], [200, 201])
        self.assertEqual(self.enable(cid=on_cid)[0], 200)
        sources = [{"title": "固定合成来源", "url": "https://example.invalid/source", "snippet": "固定搜索材料只供本次回环验证。"}]
        config = {"enabled": True, "mode": "manual", "api_key": "fixture-search-only"}
        with patch.dict(self.server.secrets, {"web_search": config}), \
                patch("ai_platform.handlers.chat.perform_web_search", return_value=sources), \
                patch("ai_platform.handlers.chat.enrich_search_result_snippets", side_effect=lambda rows, *args: rows):
            self.assertEqual(self.request(f"/api/conversations/{off_cid}/messages", {"content": raw_request, "web_search": web_search})[0], 200)
            boundary = len(MockModels.requests)
            self.assertEqual(self.request(f"/api/conversations/{on_cid}/messages", {"content": raw_request, "web_search": web_search})[0], 200)
        before, after = MockModels.requests[:boundary], MockModels.requests[boundary:]
        expected_before = ["plan", "main"] if legacy_writing else ["main"]
        self.assertEqual([item["stage"] for item in before], expected_before)
        self.assertEqual([item["stage"] for item in after], expected_before)
        off = next(item for item in before if item["stage"] == "main")
        on = next(item for item in after if item["stage"] == "main")
        self.assertEqual(off["path"], "/responses" if native_capable and web_search else "/chat/completions")
        # 比较完整实际HTTP请求，不移除工具、思考参数、系统消息或任何模型字段。
        self.assertEqual(on["path"], off["path"])
        self.assertEqual(on["headers"], off["headers"])
        self.assertEqual(on["body"], off["body"])
        payload = on["body"]
        messages = payload.get("messages", payload.get("input", []))
        user_contents = [item["content"] if isinstance(item["content"], str) else "".join(part.get("text", "") for part in item["content"]) for item in messages if item["role"] == "user"]
        self.assertIn(raw_request, user_contents)
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertIn("模型后台已有指令必须原样保留", serialized)
        self.assertIn("用户已启用的原有档案内容", serialized)
        self.assertIn("仅有本单附件证据", serialized)
        self.assertIn("摘要水位之后的用户拍摄限制", serialized)
        self.assertNotIn("旧超能底稿不得注入主请求", serialized)
        self.assertNotIn("旧超能口吻不得干预主生成", serialized)
        self.assertNotIn("本单上传终稿的独有句子", serialized)
        self.assertEqual("本单早期工作摘要必须保持原样" in serialized, not legacy_writing)
        if native_capable and web_search:
            self.assertEqual(payload["tools"], [{"type": "web_search"}, {"type": "web_extractor"}])
        elif web_search:
            self.assertIn("固定搜索材料", serialized)
        self.cid = on_cid
        reply = self.last_reply()
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertIsNone(reply["super_check"])
        self.assertNotIn("check", [item["stage"] for item in MockModels.requests])
        with db() as conn:
            actual = conn.execute("SELECT SUM(total_tokens),SUM(estimated_cost) FROM messages WHERE user_id='default'").fetchone()
            daily = conn.execute("SELECT SUM(total_tokens),SUM(request_count),SUM(estimated_cost) FROM daily_usage WHERE user_id='default'").fetchone()
        self.assertEqual(actual[0], sum(item["usage"]["total_tokens"] for item in MockModels.charged))
        self.assertEqual(daily[0], actual[0])
        self.assertEqual(daily[1], len(MockModels.charged))
        self.assertAlmostEqual(daily[2], actual[1], places=7)

    def test_native_capable_web_on_primary_request_is_identical(self):
        self.assert_primary_request_identical(True, True)

    def test_native_capable_web_off_primary_request_is_identical(self):
        self.assert_primary_request_identical(True, False)

    def test_chat_web_on_primary_request_is_identical(self):
        self.assert_primary_request_identical(False, True)

    def test_chat_web_off_primary_request_is_identical(self):
        self.assert_primary_request_identical(False, False)

    def test_existing_writing_mode_primary_request_and_history_filter_remain_identical(self):
        self.assert_primary_request_identical(False, False, legacy_writing=True)

    def test_full_draft_bypasses_scoped_revision(self):
        MockModels.answer = "正文：\n" + "\n".join("第%d段继续讲本单既有资料。" % index for index in range(12))
        self.assert_primary_request_identical(True, True)

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

    def seed_draft(self, draft, requirement="请写口播稿。智驾是红线词汇。"):
        with db() as conn:
            for role, text in (("user", requirement), ("assistant", draft)):
                conn.execute("""INSERT INTO messages(user_id,conversation_id,role,content,created_at,generation_status)
                    VALUES ('default',?,?,?,?,'completed')""", (self.cid, role, text, now()))

    def test_scoped_ending_uses_one_call_and_preserves_original_bytes(self):
        draft = "封面文案：标题原样\n发布文案：原标题#话题\n\n正文：\n开头有两个空格。  \n\n中间还有一段。\n\n原来的结尾。"
        self.seed_draft(draft, "不会被送到修稿上游的大段材料。" * 1000)
        self.assertEqual(self.enable()[0], 200)
        MockModels.answer = '{"replacement":"有兴趣的话，周末可以到店试试。"}'
        status, stream = self.send("结尾也改下吧，改成推荐大家去试驾")
        self.assertEqual(status, 200, stream)
        self.assertNotIn('"replacement"', stream)
        self.assertEqual(self.last_reply()["content"], draft.replace("原来的结尾。", "有兴趣的话，周末可以到店试试。"))
        self.assertTrue(self.last_reply()["super_check"]["repaired"])
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main"])
        payload = json.dumps(MockModels.requests[0]["body"], ensure_ascii=False)
        for excluded in ("不会被送到修稿上游", "标题原样", "开头有两个空格"):
            self.assertNotIn(excluded, payload)
        self.assertIn("原来的结尾。", payload)
        self.assert_accounting()

    def test_target_first_edit_switch_off_uses_normal_chat(self):
        draft = "正文：\n开头。\n\n原稿结尾。"
        self.seed_draft(draft)
        self.enable()
        self.enable(False)
        self.assertEqual(self.send("第一段要重新写啊")[0], 200)
        self.assertIsNone(self.last_reply()["super_check"])
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main"])
        self.assertIn({"role": "assistant", "content": draft}, MockModels.requests[0]["body"]["messages"])
        self.assertEqual(MockModels.requests[0]["body"]["messages"][-1]["content"], "第一段要重新写啊")

    def test_scoped_storyboard_preserves_existing_cells_and_durations(self):
        draft = "分镜安排\n\n| 段落 | 时长 | 画面描述 | 口播内容 |\n| --- | --- | --- | --- |\n| 1 | 18s | 车外 | 台词一。 |\n| 2 | 28s | 进车 | 台词二。 |\n\n总时长 46s"
        self.seed_draft(draft)
        self.enable()
        MockModels.answer = '{"shots":["全景","近景"]}'
        self.assertEqual(self.send("在时长前面加一列景别")[0], 200)
        reply = self.last_reply()["content"]
        for item in (" 景别 |", " --- |", " 全景 |", " 近景 |"):
            if item != " --- |":
                self.assertIn(item, reply)
        expected = draft.replace("| 段落 | 时长", "| 段落 | 景别 | 时长").replace(
            "| --- | --- | --- | --- |", "| --- | --- | --- | --- | --- |"
        ).replace("| 1 | 18s", "| 1 | 全景 | 18s").replace("| 2 | 28s", "| 2 | 近景 | 28s")
        self.assertEqual(reply, expected)
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main"])

    def test_banned_term_or_wrong_shape_does_not_modify_draft(self):
        draft = "正文：\n这段用户没要求改，即使原文中含智驾也保留。\n\n原结尾。"
        self.seed_draft(draft)
        self.enable()
        for bad in ('{"replacement":"可以体验智驾。"}', '{"replacement":"结尾。","title":"意外标题"}'):
            MockModels.answer = bad
            self.assertEqual(self.send("改下结尾")[0], 200)
            self.assertEqual(self.last_reply()["content"], draft)
            self.assertFalse(self.last_reply()["super_check"]["repaired"])
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main", "main"])
        self.assert_accounting()

    def test_missing_scope_is_rejected_without_saving_or_calling_model(self):
        self.seed_draft("脚本一\n正文：\n甲一。\n甲二。\n脚本二\n正文：\n乙一。\n乙二。")
        self.enable()
        status, result = self.send("只改结尾")
        self.assertEqual(status, 422, result)
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(MockModels.requests, [])

    def test_interrupted_fragment_is_never_committed_as_a_revision(self):
        draft = "正文：\n开头不变。\n结尾不变。"
        self.seed_draft(draft)
        self.enable()
        MockModels.answer = '{"replacement":"候选修改。"}'
        MockModels.finish_reason = "length"
        self.assertEqual(self.send("改下结尾")[0], 200)
        self.assertEqual(self.last_reply()["content"], draft)
        self.assertEqual(self.last_reply()["generation_status"], "interrupted")
        self.assertFalse(self.last_reply()["super_check"]["repaired"])

    def test_legacy_opt_in_does_not_activate_revision_or_delete_history(self):
        self.seed_draft("正文：\n开头不变。\n结尾不变。")
        with db() as conn:
            conn.execute("UPDATE conversations SET super_mode=1 WHERE id=?", (self.cid,))
            mid = self.rows()[-1]["id"]
            conn.execute("INSERT INTO super_checks VALUES (?,'default',?)", (mid, '{"version":"super-postcheck-v6","status":"issues"}'))
        self.assertFalse(self.workspace()["enabled"])
        self.assertEqual(self.last_reply()["super_check"]["version"], "super-postcheck-v6")
        self.assertEqual(self.send("只改结尾")[0], 200)
        self.assertIsNone(self.last_reply()["super_check"])
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main"])

    def test_super_mode_does_not_duplicate_legacy_writing_planner(self):
        with db() as conn:
            conn.execute("UPDATE conversations SET writing_mode=1 WHERE id=?", (self.cid,))
        self.enable()
        self.assertEqual(self.send()[0], 200)
        self.assertEqual(sum(item["stage"] == "plan" for item in MockModels.requests), 1)
        planner = next(item["body"] for item in MockModels.requests if item["stage"] == "plan")
        self.assertEqual(planner["model"], "qwen3.7-max")
        self.assertTrue(planner["messages"][0]["content"].startswith("整理本单写稿要求"))
        self.assertEqual([item["stage"] for item in MockModels.requests], ["plan", "main"])
        self.assert_accounting()

    def test_uploaded_customer_delivery_never_replaces_raw_main_storyboard(self):
        original = "客户已通过的第一段，逐字保留。\n\n客户已通过的第二段，不要擅自润色。"
        self.assertIn(self.final(original)[0], [200, 201])
        self.enable()
        MockModels.answer = "| 台词 | 画面 |\n| --- | --- |\n| 偷改客户已通过的台词 | 汽车 |"
        status, stream = self.send("把客户通过稿整理成分镜表格，台词一个字不动")
        self.assertEqual(status, 200)
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertEqual(result["messages"][-1]["content"], MockModels.answer)
        self.assertEqual(self.workspace()["delivery"]["content"], original)
        main = next(item["body"] for item in MockModels.requests if item["stage"] == "main")
        self.assertNotIn(original, json.dumps(main, ensure_ascii=False))
        self.assertNotIn("plan", [item["stage"] for item in MockModels.requests])
        self.assert_accounting()

    def test_existing_background_summary_runs_without_legacy_super_records(self):
        self.enable()
        with db() as conn:
            for index in range(24):
                conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('default',?,?,?,?)", (self.cid, "user" if index % 2 == 0 else "assistant", "本单要求或稿件-%02d" % index, index))
        QuietHandler.run_context_summary_job(("default", self.cid), self.cid, "default")
        self.assertEqual([item["stage"] for item in MockModels.requests], ["summary"])
        self.assertFalse(any(row["role"] == "system" for row in self.rows()))
        with db() as conn:
            row = conn.execute("SELECT context_summary,context_summary_message_id FROM conversations WHERE id=?", (self.cid,)).fetchone()
        self.assertIn("已保留本单拍摄条件", row["context_summary"])
        self.assertGreater(row["context_summary_message_id"], 0)
        status, result = self.request(f"/api/conversations/{self.cid}/stats")
        self.assertEqual(result["stats"]["message_count"], 24)

    def test_invalid_summary_response_does_not_create_legacy_super_records(self):
        self.enable()
        with db() as conn:
            for index in range(24):
                conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('default',?,?,?,?)", (self.cid, "user" if index % 2 == 0 else "assistant", "需要摘要的原文-%02d" % index, index))
        MockModels.broken_summary_json = True
        QuietHandler.run_context_summary_job(("default", self.cid), self.cid, "default")
        self.assertEqual([item["stage"] for item in MockModels.requests], ["summary"])
        self.assertFalse(any(row["role"] == "system" for row in self.rows()))

    def test_admin_usage_and_cost_include_main_model_without_review_call(self):
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
        self.assertEqual({row["model_code"] for row in costs["models"]}, {"qwen3.7-max"})

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
