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
from ai_platform import super_writing, writing, super_generation
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

    def review_issue(self, **changes):
        """按本轮实际编号构造响应，不把复制引文当作新协议必需字段。"""
        quote = changes.pop("quote", "全车12点按摩")
        source = changes.pop("source_quote", "前排12点按摩")
        reason = changes.pop("reason", "稿件把材料限定的前排扩大成全车。")
        changes.pop("claim", None)
        changes.pop("expected", None)
        def build(data):
            draft_id = next((unit["id"] for unit in data["draft_units"] if quote in unit["text"]), "D9999")
            source_id = next((unit["id"] for unit in data["source_units"] if source in unit["text"]), "S9999")
            issue = {"d": draft_id, "kind": "conflict", "s": [source_id], "difference": reason}
            issue.update(changes)
            return issue
        return build

    def postcheck_requirements(self):
        with db() as conn:
            return super_writing.get_task_state(conn, self.cid, "default")["postcheck_requirements"]

    @staticmethod
    def source_text(data):
        return "".join(unit["text"] for unit in data["source_units"])

    def prepare_long_review(self):
        self.enable()
        MockModels.answer = "正文：\n购买后就能免费更换。\n" + "\n".join("第%d段继续解释实际使用体验。" % index for index in range(1, 10))
        MockModels.review = {"issues": [self.review_issue(quote="购买后就能免费更换", kind="missing_condition",
            source_quote="30天内质量问题可免费更换", reason="稿件遗漏30天及质量问题两个适用条件。") ]}
        return "请写小家电口播稿。材料：购买后30天内质量问题可免费更换。其他内容按资料说明。"

    def assert_review_only_metadata(self, check):
        self.assertEqual(check["version"], super_writing.PIPELINE_VERSION)
        self.assertFalse(check["review_complete"])
        self.assertFalse(check["repaired"])
        self.assertEqual(check["repair"]["status"], "disabled_review_only")
        self.assertFalse(check["repair"].get("attempted", False))

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
        self.assertEqual([item["stage"] for item in after], expected_before + ["check"])
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
        check = reply["super_check"]
        self.assertEqual([call["stage"] for call in check["calls"]], ["超能槑槑交付校验"])
        self.assertEqual(check["usage"]["total_tokens"], MockModels.usages["main"]["total_tokens"] + MockModels.usages["check"]["total_tokens"])
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

    def test_long_draft_single_review_does_not_change_primary_request(self):
        MockModels.answer = "正文：\n" + "\n".join("第%d段继续讲本单既有资料。" % index for index in range(12))
        self.assert_primary_request_identical(True, True)

    def test_long_draft_uses_one_review_without_coverage_or_second_round_metadata(self):
        request = self.prepare_long_review()
        self.assertEqual(self.send(request)[0], 200)
        reply = self.last_reply()
        check = reply["super_check"]
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertEqual(check["review_method"], "single_pass")
        self.assertEqual(len(check["issues"]), 1)
        for key in ("first_review", "secondary_review", "coverage"):
            self.assertNotIn(key, check)
        review = next(item["body"] for item in MockModels.requests if item["stage"] == "check")
        data = json.loads(review["messages"][-1]["content"])
        self.assertGreater(len(data["draft_units"]), 8)
        self.assertEqual(self.source_text(data), request)
        self.assertEqual("".join(unit["text"] for unit in data["draft_units"]), MockModels.answer)
        self.assertEqual(set(data), {"source_units", "draft_units", "review_scope"})
        self.assertTrue(data["review_scope"])
        self.assertEqual(review["max_tokens"], 2400)
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main", "check"])
        self.assertEqual(len(check["calls"]), 1)
        self.assert_accounting()

    def test_single_review_timeout_is_recorded_once_without_retry_or_guessing_usage(self):
        request = self.prepare_long_review()
        original_open = super_generation.open_model_request
        timed_out = []
        def timeout_review(request, timeout):
            body = json.loads(request.data)
            if body["messages"][0]["content"].startswith("超能槑槑交付校验"):
                timed_out.append(timeout)
                raise TimeoutError("本地模拟单次复检超时")
            return original_open(request, timeout=timeout)
        with patch.object(super_generation, "open_model_request", side_effect=timeout_review):
            self.assertEqual(self.send(request)[0], 200)
        reply = self.last_reply()
        check = reply["super_check"]
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertEqual(timed_out, [25])
        self.assertEqual(check["issues"], [])
        self.assertEqual(check["status"], "failed")
        self.assertTrue(check["usage_unknown"])
        self.assertEqual(len(check["calls"]), 1)
        self.assertFalse(check["calls"][0]["usage_known"])
        self.assert_accounting()

    def test_same_draft_unit_keeps_distinct_concrete_problems(self):
        self.enable()
        MockModels.answer = "正文：\n购买后可免费更换、终身上门维修。"
        MockModels.review = {"issues": [
            self.review_issue(quote="购买后可免费更换", kind="missing_condition", source_quote="30天内质量问题可免费更换",
                              reason="免费更换承诺遗漏30天内且属于质量问题的条件。"),
            self.review_issue(quote="终身上门维修", kind="conflict", source_quote="只提供两年送修服务",
                              reason="稿件把两年送修写成终身上门维修，时间与服务方式均不同。"),
        ]}
        self.assertEqual(self.send("写小家电口播稿。材料：30天内质量问题可免费更换；只提供两年送修服务。")[0], 200)
        reply = self.last_reply()
        check = reply["super_check"]
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertEqual(len(check["issues"]), 2)
        self.assertEqual(check["issues"][0]["draft_id"], check["issues"][1]["draft_id"])
        self.assertNotEqual(check["issues"][0]["reason"], check["issues"][1]["reason"])
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main", "check"])
        self.assert_accounting()

    def test_single_review_rejects_bad_item_without_discarding_valid_issue(self):
        request = self.prepare_long_review()
        MockModels.review["issues"].append(self.review_issue(quote="购买后就能免费更换", kind="missing_condition", s=[],
                                                            reason="没有材料来源的条件判断不得接纳。"))
        self.assertEqual(self.send(request)[0], 200)
        reply = self.last_reply()
        check = reply["super_check"]
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertEqual(len(check["issues"]), 1)
        self.assertIn("30天", check["issues"][0]["reason"])
        self.assertEqual(len(check["review_rejected"]), 1)
        self.assertFalse(check["review_complete"])
        self.assertEqual(check["status"], "issues")
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main", "check"])
        self.assert_accounting()

    def test_single_review_optional_incomplete_flag_keeps_valid_issue(self):
        request = self.prepare_long_review()
        MockModels.review["incomplete"] = True
        self.assertEqual(self.send(request)[0], 200)
        reply = self.last_reply()
        check = reply["super_check"]
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertEqual(len(check["issues"]), 1)
        self.assertFalse(check["review_complete"])
        self.assertNotIn("coverage", check)
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main", "check"])
        self.assert_accounting()

    def test_single_review_long_specific_difference_is_preserved_without_truncation(self):
        request = self.prepare_long_review()
        difference = "材料的免费更换承诺同时限于购买后的30天内以及存在质量问题，两项适用条件均应随承诺保留。" * 7 + "请核对完整条件。"
        self.assertGreater(len(difference), 240)
        MockModels.review = {"issues": [self.review_issue(quote="购买后就能免费更换",
            kind="missing_condition", source_quote="30天内质量问题可免费更换", reason=difference)]}
        self.assertEqual(self.send(request)[0], 200)
        reply = self.last_reply()
        check = reply["super_check"]
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertEqual(len(check["issues"]), 1)
        self.assertEqual(check["issues"][0]["reason"], difference)
        self.assertTrue(check["review_complete"])
        self.assert_accounting()

    def test_single_draft_unit_uses_only_one_flash_call(self):
        self.enable()
        MockModels.answer = "这台设备适合家用。"
        self.assertEqual(self.send("请写一句口播稿。材料：这台设备适合家用。")[0], 200)
        check = self.last_reply()["super_check"]
        self.assertEqual(check["review_method"], "single_pass")
        self.assertNotIn("secondary_review", check)
        self.assertNotIn("coverage", check)
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main", "check"])
        self.assert_accounting()

    def test_raw_explicit_character_range_and_forbidden_words_are_checked_without_planner(self):
        self.enable()
        MockModels.answer = "封面文案：测试车体验\n发布文案：看看实际用法。#测试车\n正文：\n这个智驾功能需要驾驶员全程注意路况，不能把辅助功能当作接管。"
        self.assertEqual(self.send("请写测试车口播稿。正文100至120字。必带词：测试车。禁用词：智驾。材料只有前排12点按摩。")[0], 200)
        reply = self.last_reply()
        check = reply["super_check"]
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertIn("出现本单避用词：智驾", check["deterministic_issues"])
        self.assertTrue(any("少于要求的100字" in issue for issue in check["deterministic_issues"]))
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main", "check"])
        self.assert_accounting()

    def test_approximate_length_does_not_gain_an_invented_hard_range(self):
        self.enable()
        self.assertEqual(self.send("写测试车口播稿，正文大概750字左右。必带词：测试车。材料：前排12点按摩。")[0], 200)
        check = self.last_reply()["super_check"]
        self.assertFalse(any("少于要求" in issue or "超过要求" in issue for issue in check["deterministic_issues"]))
        self.assertEqual(self.last_reply()["content"], MockModels.answer)
        self.assert_accounting()

    def test_explicit_unlimited_length_cancels_prior_manuscript_range(self):
        self.enable()
        MockModels.answer = "正文：\n辅助功能只是帮手，体验要结合自己的日常需求判断。"
        self.assertEqual(self.send("写测试车口播稿，正文100至120字。材料：前排12点按摩。")[0], 200)
        self.assertTrue(any("少于要求的100字" in issue for issue in self.last_reply()["super_check"]["deterministic_issues"]))
        self.assertEqual(self.send("继续修改口播稿，这次不限字数，说明白就行。")[0], 200)
        reply = self.last_reply()
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertFalse(any("少于要求" in issue or "超过要求" in issue for issue in reply["super_check"]["deterministic_issues"]))
        review = [item["body"] for item in MockModels.requests if item["stage"] == "check"][-1]
        requirements = self.postcheck_requirements()
        self.assertEqual((requirements["min_chars"], requirements["max_chars"]), (0, 0))
        self.assert_accounting()

    def test_returned_local_ending_is_not_checked_against_full_manuscript_minimum(self):
        self.enable()
        self.assertEqual(self.send("请写测试车口播稿，正文650至700字。材料：前排12点按摩。")[0], 200)
        self.assertTrue(any("少于要求的650字" in issue for issue in self.last_reply()["super_check"]["deterministic_issues"]))
        MockModels.answer = "正文：\n能不能用得顺手，还是要结合自己的需求，上车亲自试试。"
        self.assertEqual(self.send("只改结尾，改好单独发出来，不要重发全文。")[0], 200)
        reply = self.last_reply()
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertFalse(any("少于要求的650字" in issue for issue in reply["super_check"]["deterministic_issues"]))
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main", "check", "main", "check"])
        self.assert_accounting()

    def test_full_output_length_scope_is_unverified_instead_of_assumed_to_mean_body(self):
        self.enable()
        self.assertEqual(self.send("请写测试车口播稿，包含封面文案、发布文案和正文，全文650至700字。材料：前排12点按摩。")[0], 200)
        reply = self.last_reply()
        check = reply["super_check"]
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertFalse(check["review_complete"])
        self.assertEqual(check["length_requirement"]["status"], "not_checked")
        self.assertIn("全文650至700字", check["length_requirement"]["source_quote"])
        self.assertFalse(any("少于要求的650字" in issue or "超过要求的700字" in issue for issue in check["deterministic_issues"]))
        self.assertNotIn(check["status"], ("passed", "reviewed"))
        self.assert_accounting()

    def test_titles_and_question_only_requests_skip_manuscript_review_and_length_alerts(self):
        self.enable()
        self.assertEqual(self.send("先写测试车口播稿，正文100至120字。材料：前排12点按摩。")[0], 200)
        cases = [
            ("只给我5个封面标题，不要再写正文。", "1.雨天怎样开更从容\n2.看看底盘怎么接住动作\n3.从安全细节看测试车\n4.前排体验怎么选\n5.先说清楚再作判断"),
            ("先只回答问题，不要写脚本：怎么理解上面这段？", "这段是在说明功能的使用边界，不能把辅助功能理解成车辆替驾驶员接管。"),
        ]
        for request, answer in cases:
            with self.subTest(request=request):
                MockModels.answer = answer
                before = len(MockModels.requests)
                self.assertEqual(self.send(request)[0], 200)
                reply = self.last_reply()
                check = reply["super_check"]
                self.assertEqual(reply["content"], answer)
                self.assertEqual([item["stage"] for item in MockModels.requests[before:]], ["main"])
                self.assertEqual(check["status"], "skipped")
                self.assertFalse(any("少于要求" in issue or "超过要求" in issue for issue in check["deterministic_issues"]))
        self.assert_accounting()

    def test_enabled_checks_and_usage_belongs_to_current_conversation(self):
        self.enable()
        status, stream = self.send()
        self.assertEqual(status, 200)
        stages = [item["stage"] for item in MockModels.requests]
        self.assertEqual(stages.count("main"), 1, stages)
        self.assertEqual(stages.count("check"), 1, stages)
        self.assertNotIn("repair", stages)
        self.assert_accounting()
        _, history = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertTrue(all(row["role"] != "system" for row in history["messages"]))
        self.assertIn(MockModels.answer, history["messages"][-1]["content"])

    def test_unrelated_customer_and_inferred_deliveries_never_enter_generation_or_review(self):
        customer_cid = self.create(title="另一个品牌的线上广告稿")
        customer = "跨单客户唯一标记：旧牌必须用强硬销售腔、必须带旧牌专属词，禁止出现本单柔和词。"
        self.assertIn(self.final(customer, cid=customer_cid)[0], [200, 201])
        inferred_cid = self.create(title="另一个品牌的线下体验稿")
        inferred = "正文：\n跨单推定唯一标记。" + "旧任务必须使用英语标题，强调旧牌专属词，禁止本单柔和词。" * 8
        with db() as conn:
            conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('default',?,'user','请写另一个品牌的单人现场口播稿',0)", (inferred_cid,))
            conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('default',?,'assistant',?,1)", (inferred_cid, inferred))
        self.enable()
        request = "请写测试车口播稿，本单只用柔和自然的中文表达，保留本单柔和词。材料：前排12点按摩、两驱版前备箱106L。"
        with patch.object(super_writing, "reference_context", side_effect=AssertionError("不得自动读取其他任务参考稿")) as reference:
            self.assertEqual(self.send(request)[0], 200)
        reference.assert_not_called()
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main", "check"])
        for item in MockModels.requests:
            payload = json.dumps(item["body"], ensure_ascii=False)
            for marker in ("跨单客户唯一标记", "跨单推定唯一标记", "旧牌专属词", "强硬销售腔"):
                self.assertNotIn(marker, payload, item["stage"])
        main = next(item["body"] for item in MockModels.requests if item["stage"] == "main")
        self.assertIn(request, [message["content"] for message in main["messages"] if message["role"] == "user"])
        self.assert_accounting()

    def test_current_delivery_stays_saved_without_injecting_it_into_main_request(self):
        current = "本单通过稿唯一标记。\n\n前排12点按摩，前备箱只限两驱版106L。结尾保留本单已确认的使用建议。"
        self.assertIn(self.final(current)[0], [200, 201])
        self.enable()
        latest = "在本单通过稿基础上改口播稿，只把结尾改为克制自然的建议，本次不要强调促销优惠，其他事实不变。"
        self.assertEqual(self.send(latest)[0], 200)
        main = next(item["body"] for item in MockModels.requests if item["stage"] == "main")
        review = next(item["body"] for item in MockModels.requests if item["stage"] == "check")
        review_data = json.loads(review["messages"][-1]["content"])
        self.assertNotIn("plan", [item["stage"] for item in MockModels.requests])
        self.assertNotIn("本单通过稿唯一标记", json.dumps(main, ensure_ascii=False))
        self.assertNotIn("本单通过稿唯一标记", json.dumps(review, ensure_ascii=False))
        self.assertIn(latest, [message["content"] for message in main["messages"] if message["role"] == "user"])
        self.assertIn(latest, self.source_text(review_data))
        self.assertEqual(self.workspace()["delivery"]["content"], current)
        self.assert_accounting()

    def test_semantic_requirements_do_not_become_literal_missing_or_forbidden_alerts(self):
        self.enable()
        semantic_required = ["必须提及主动与被动两道防线", "格式：封面文案 + 发布文案 + 正文"]
        semantic_forbidden = ["编造Brief中未出现的数据或功能", "直接复制粘贴Brief原文段落"]
        MockModels.plan["requirements"].update(required=semantic_required + ["测试车", "#测试车"], forbidden=semantic_forbidden + ["旧版车型名"])
        with db() as conn:
            super_writing.save_task_state(conn, self.cid, "default", {"requirements": MockModels.plan["requirements"]})
        request = "请写测试车口播稿。必带词：测试车；必带话题：#测试车。禁用词：旧版车型名。必须提及主动与被动两道防线；格式：封面文案 + 发布文案 + 正文。禁止编造Brief中未出现的数据或功能，禁止直接复制粘贴Brief原文段落。材料：前排12点按摩、两驱版前备箱106L。"
        self.assertEqual(self.send(request)[0], 200)
        check = self.last_reply()["super_check"]
        self.assertFalse(any("缺少本单必带词：" + item in check["deterministic_issues"] for item in semantic_required))
        review = next(item["body"] for item in MockModels.requests if item["stage"] == "check")
        review_data = json.loads(review["messages"][-1]["content"])
        requirements = self.postcheck_requirements()
        self.assertEqual(set(requirements["required"]), {"测试车", "#测试车"})
        self.assertEqual(requirements["forbidden"], ["旧版车型名"])
        for item in semantic_required + semantic_forbidden:
            self.assertIn(item, self.source_text(review_data))
        self.assert_accounting()

    def test_reviewer_cannot_anchor_title_problem_to_safe_body_sentence(self):
        self.enable()
        MockModels.answer = "封面文案：智驾每天都安心\n发布文案：一起看看测试车。\n正文：\n辅助驾驶只是帮手，司机仍要随时注意路况。前排12点按摩要以自己的体验为准。"
        MockModels.review = {"issues": [self.review_issue(kind="wording",
            quote="辅助驾驶只是帮手，司机仍要随时注意路况。", claim="智驾",
            source_quote="禁用词：智驾", expected="", reason="封面用了本单禁用词。") ]}
        self.assertEqual(self.send("写测试车口播稿。禁用词：智驾。材料：前排12点按摩。")[0], 200)
        reply = self.last_reply()
        check = reply["super_check"]
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertEqual(check["issues"], [])
        self.assertFalse(check["review_complete"])
        # 模型定位失败不能吞掉代码已经发现的本单禁词问题。
        self.assertEqual(check["status"], "issues")
        self.assertTrue(check["review_rejected"])
        self.assertIn("出现本单避用词：智驾", check["deterministic_issues"])
        self.assertNotIn("repair", [item["stage"] for item in MockModels.requests])
        self.assert_accounting()

    def test_latest_explicit_cancellation_clears_stale_task_forbidden_term(self):
        self.enable()
        MockModels.answer = "封面文案：测试车的智驾要怎样用\n发布文案：日常体验。#测试车\n正文：\n前排12点按摩仍应按自己的实际体验判断舒适程度。司机要注意路况，辅助功能只是帮手。"
        first = "写测试车口播稿。禁用词：智驾。材料：前排12点按摩。"
        self.assertEqual(self.send(first)[0], 200)
        self.assertIn("出现本单避用词：智驾", self.last_reply()["super_check"]["deterministic_issues"])
        # 平台应按本单最新明确取消重新核对，不能沿用已保存的禁词。
        latest = "继续写口播稿。取消禁用词：智驾。本轮可以按实际语境使用这个词，其他要求保持。"
        self.assertEqual(self.send(latest)[0], 200)
        check = self.last_reply()["super_check"]
        self.assertNotIn("出现本单避用词：智驾", check["deterministic_issues"])
        review = [item["body"] for item in MockModels.requests if item["stage"] == "check"][-1]
        review_data = json.loads(review["messages"][-1]["content"])
        self.assertEqual(self.postcheck_requirements()["forbidden"], [])
        self.assertIn(latest, self.source_text(review_data))
        self.assert_accounting()

    def test_identical_user_request_can_reinstate_previously_cancelled_forbidden_term(self):
        self.enable()
        MockModels.answer = "封面文案：测试车智驾体验\n发布文案：日常怎么用。#测试车\n正文：\n辅助功能只是帮手，司机仍要随时注意路况。前排12点按摩要以自己的实际体验为准。"
        original = "写测试车口播稿。禁用词：智驾。材料：前排12点按摩。"
        requests = [(original, True), ("继续写口播稿。取消禁用词：智驾。本轮允许使用这个词。", False), (original, True)]
        for request, forbidden in requests:
            with self.subTest(request=request, forbidden=forbidden):
                self.assertEqual(self.send(request)[0], 200)
                check = self.last_reply()["super_check"]
                self.assertEqual("出现本单避用词：智驾" in check["deterministic_issues"], forbidden)
                review = [item["body"] for item in MockModels.requests if item["stage"] == "check"][-1]
                requirements = self.postcheck_requirements()
                self.assertEqual("智驾" in requirements["forbidden"], forbidden)
        self.assert_accounting()

    def test_noninitial_literal_requirement_survives_recent_history_and_summary_until_cancelled(self):
        self.enable()
        self.assertEqual(self.send()[0], 200)
        term = "本单关键词"
        requirement = "在原稿上补一条口播要求。必带词：本单关键词。其他要求不变。"
        self.assertEqual(self.send(requirement)[0], 200)
        # 真实HTTP连续交互，让新增要求滑出最近12条消息，而非直接改最终状态。
        for index in range(7):
            self.assertEqual(self.send("继续修改口播稿的自然度，第%d轮，保留此前明确要求。" % index)[0], 200)
        with db() as conn:
            recent = conn.execute("SELECT content FROM messages WHERE conversation_id=? AND role IN ('user','assistant') ORDER BY id DESC LIMIT 12", (self.cid,)).fetchall()
            self.assertFalse(any(requirement in row["content"] for row in recent))
            watermark = conn.execute("SELECT MAX(id) FROM messages WHERE conversation_id=? AND role IN ('user','assistant')", (self.cid,)).fetchone()[0]
            conn.execute("UPDATE conversations SET context_mode='smart',context_summary='压缩摘要仅保留任务概况，未复述中途新增词项。',context_summary_message_id=? WHERE id=?", (watermark, self.cid))
        self.assertEqual(self.send("继续修改口播稿，保留此前所有要求。")[0], 200)
        check = self.last_reply()["super_check"]
        self.assertIn("缺少本单必带词：" + term, check["deterministic_issues"])
        review = [item["body"] for item in MockModels.requests if item["stage"] == "check"][-1]
        review_data = json.loads(review["messages"][-1]["content"])
        self.assertIn(term, self.postcheck_requirements()["required"])
        self.assertIn("必带词：本单关键词", self.source_text(review_data))
        # 已持久化的旧词项也必须让最新明确取消生效。
        self.assertEqual(self.send("继续改口播稿。取消必带词：本单关键词。其他要求不变。")[0], 200)
        check = self.last_reply()["super_check"]
        self.assertNotIn("缺少本单必带词：" + term, check["deterministic_issues"])
        review = [item["body"] for item in MockModels.requests if item["stage"] == "check"][-1]
        self.assertNotIn(term, self.postcheck_requirements()["required"])
        self.assert_accounting()

    def test_early_factual_correction_survives_recent_history_and_summary_for_postreview_only(self):
        self.enable()
        MockModels.answer = "正文：\n这台测试车是前排18点按摩，具体力度还是要结合自己的使用习惯去体验。"
        original = "请写测试车口播稿。材料：前排按摩为18点。"
        correction = "材料更正：前排按摩是16点，不是18点，以这条为准。继续改口播稿。"
        self.assertEqual(self.send(original)[0], 200)
        self.assertEqual(self.send(correction)[0], 200)
        for index in range(7):
            self.assertEqual(self.send("继续改口播稿的表达，第%d轮，不更改已经确认的数据。" % index)[0], 200)
        with db() as conn:
            recent = conn.execute("SELECT content FROM messages WHERE conversation_id=? AND role IN ('user','assistant') ORDER BY id DESC LIMIT 12", (self.cid,)).fetchall()
            self.assertFalse(any(correction in row["content"] for row in recent))
            watermark = conn.execute("SELECT MAX(id) FROM messages WHERE conversation_id=? AND role IN ('user','assistant')", (self.cid,)).fetchone()[0]
            conn.execute("UPDATE conversations SET context_mode='smart',context_summary='工作摘要漏掉了早期按摩点数更正。',context_summary_message_id=? WHERE id=?", (watermark, self.cid))
        MockModels.review = {"issues": [self.review_issue(quote="前排18点按摩", claim="18点",
            source_quote="前排按摩是16点，不是18点，以这条为准", expected="16点",
            reason="当前稿件仍沿用旧值18点，用户后续材料已更正为16点。") ]}
        self.assertEqual(self.send("继续修改口播稿，按此前最新资料检查。")[0], 200)
        reply = self.last_reply()
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertEqual(len(reply["super_check"]["issues"]), 1)
        review = [item["body"] for item in MockModels.requests if item["stage"] == "check"][-1]
        evidence = self.source_text(json.loads(review["messages"][-1]["content"]))
        self.assertIn(correction, evidence)
        self.assertLess(evidence.index("前排按摩为18点"), evidence.index("前排按摩是16点"))
        main = [item["body"] for item in MockModels.requests if item["stage"] == "main"][-1]
        self.assertNotIn(correction, json.dumps(main, ensure_ascii=False))
        self.assertFalse(reply["super_check"]["repaired"])
        self.assert_accounting()

    def test_more_than_eighty_user_messages_skips_incomplete_semantic_review_without_extra_call(self):
        self.enable()
        with db() as conn:
            for index in range(81):
                conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('default',?,'user',?,?)", (self.cid, "历史材料第%d条，用户曾修改过本单事实。" % index, index))
        # 摘要属于既有异步流程，本例只核对当前这次成稿的审核调用边界。
        with patch.object(QuietHandler, "schedule_context_summary"):
            self.assertEqual(self.send()[0], 200)
        reply = self.last_reply()
        check = reply["super_check"]
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertEqual(check["status"], "skipped")
        self.assertFalse(check["review_complete"])
        self.assertTrue(check["literal_term_audit"]["source_history_incomplete"])
        self.assertIn("未能完整纳入", check["notice"])
        self.assertEqual(check["calls"], [])
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main"])
        self.assertEqual(check["usage"]["total_tokens"], MockModels.usages["main"]["total_tokens"])
        self.assert_accounting()

    def test_short_review_invalid_fact_contracts_are_rejected_without_discarding_main_draft(self):
        self.enable()
        MockModels.answer = "正文：\n测试车全车12点按摩。"
        cases = [
            self.review_issue(d="D9999"),
            self.review_issue(d=None),
            self.review_issue(s=["S9999"]),
            self.review_issue(s=[]),
            self.review_issue(s="S0001"),
            self.review_issue(difference=""),
            self.review_issue(difference="过长差异说明" * 400),
            self.review_issue(kind="unknown"),
        ]
        for issue in cases:
            with self.subTest(issue=issue):
                MockModels.review = {"issues": [issue]}
                before = len(MockModels.requests)
                self.assertEqual(self.send()[0], 200)
                reply = self.last_reply()
                check = reply["super_check"]
                self.assertEqual(reply["content"], MockModels.answer)
                self.assertEqual(check["issues"], [])
                self.assertEqual(check["status"], "failed")
                self.assertFalse(check["review_complete"])
                self.assertTrue(check["review_rejected"])
                self.assertEqual([item["stage"] for item in MockModels.requests[before:]], ["main", "check"])
        self.assert_accounting()

    def test_review_packet_preserves_raw_text_without_duplicate_full_inputs(self):
        self.enable()
        original = "请写小型除湿机口播稿。\n材料第一段：额定容量8L。\n\n材料第二段：仅在指定环境温度下测得。"
        self.assertEqual(self.send(original)[0], 200)
        review = next(item["body"] for item in MockModels.requests if item["stage"] == "check")
        data = json.loads(review["messages"][-1]["content"])
        self.assertEqual(self.source_text(data), original)
        self.assertEqual("".join(unit["text"] for unit in data["draft_units"]), MockModels.answer)
        self.assertNotIn("source_material", data)
        self.assertNotIn("draft", data)
        self.assertNotIn("current_request", data)
        self.assertNotIn("requirements", data)
        self.assertNotIn("basic_check", data)
        self.assertTrue(all(set(unit) == {"id", "text"} for unit in data["source_units"] + data["draft_units"]))
        self.assertEqual(review["max_tokens"], 2400)
        self.assertFalse(review["enable_thinking"])
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main", "check"])
        self.assert_accounting()

    def test_added_claim_without_positive_source_quote_is_pending_not_declared_false(self):
        self.enable()
        MockModels.answer = "正文：\n修理师傅自己的家里都用这台除湿机。"
        MockModels.review = {"issues": [self.review_issue(quote="修理师傅自己的家里都用这台除湿机", kind="added_claim", s=[],
            reason="稿件增加修理师傅自用背书，本单材料只提供额定容量，未提供该背书。") ]}
        self.assertEqual(self.send("请写除湿机口播稿。材料：额定容量8L，其他事实不要自行增加。")[0], 200)
        reply = self.last_reply()
        check = reply["super_check"]
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertEqual(len(check["issues"]), 1)
        issue = check["issues"][0]
        self.assertEqual(issue["status"], "pending")
        self.assertFalse(issue["grounded"])
        self.assertEqual(issue["evidence_status"], "not_in_material")
        self.assertIn("本单材料", issue["reason"])
        self.assertIn("不代表现实虚假", issue["verification"])
        self.assertFalse(check["repaired"])
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main", "check"])
        self.assert_accounting()

    def test_missing_required_issues_list_never_looks_like_completed_review(self):
        self.enable()
        MockModels.review = {}
        self.assertEqual(self.send()[0], 200)
        check = self.last_reply()["super_check"]
        self.assertFalse(check["review_complete"])
        self.assertEqual(check["status"], "failed")
        self.assertNotIn("coverage", check)
        self.assertEqual(len(check["calls"]), 1)
        self.assertEqual(self.last_reply()["content"], MockModels.answer)
        self.assert_accounting()

    def test_too_many_draft_units_skips_review_without_extra_charge(self):
        self.enable()
        MockModels.answer = "\n".join("第%d条口播只描述材料中的事实。" % index for index in range(90))
        self.assertEqual(self.send()[0], 200)
        reply = self.last_reply()
        check = reply["super_check"]
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertEqual(check["status"], "skipped")
        self.assertFalse(check["review_complete"])
        self.assertIn("超出本轮检查范围", check["notice"])
        self.assertEqual(check["calls"], [])
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main"])
        self.assert_accounting()

    def test_empty_review_is_finite_review_not_guaranteed_pass(self):
        self.enable()
        self.assertEqual(self.send()[0], 200)
        check = self.last_reply()["super_check"]
        self.assertEqual(check["status"], "reviewed")
        self.assertTrue(check["review_complete"])
        self.assertEqual(check["issues"], [])
        self.assertFalse(check["repaired"])
        self.assertEqual(check["repair"], {"status": "disabled_review_only", "attempted": False})
        self.assertEqual(check["review_method"], "single_pass")
        self.assertIn("不代表", check["review_note"])
        self.assertIn("不代表全部正确或客户验收", check["notice"])
        self.assertNotIn("coverage", check)
        self.assert_accounting()

    def test_failed_main_does_not_start_or_charge_preparation_or_review(self):
        self.enable()
        MockModels.failed_stage = "main"
        status, result = self.send()
        self.assertEqual(status, 502, result)
        self.assertEqual(MockModels.charged, [])
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main"])
        self.assertFalse(any(row["role"] == "system" for row in self.rows()))
        self.assert_accounting()
        self.assertEqual(self.rows()[-1]["generation_status"], "failed")

    def test_prepare_exception_preserves_original_and_review_only_fallback_metadata(self):
        self.enable()
        with patch("ai_platform.handlers.chat.super_generation.prepare", side_effect=ValueError("合成整理异常")):
            self.assertEqual(self.send()[0], 200)
        reply = self.last_reply()
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertEqual(reply["super_check"]["status"], "failed")
        self.assert_review_only_metadata(reply["super_check"])
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main"])
        self.assert_accounting()

    def test_finish_exception_preserves_original_and_review_only_fallback_metadata(self):
        self.enable()
        with patch("ai_platform.handlers.chat.super_generation.finish", side_effect=ValueError("合成审核异常")):
            self.assertEqual(self.send()[0], 200)
        reply = self.last_reply()
        self.assertEqual(reply["content"], MockModels.answer)
        self.assertEqual(reply["super_check"]["status"], "failed")
        self.assert_review_only_metadata(reply["super_check"])
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main"])
        self.assert_accounting()

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

    def test_no_preparation_model_is_called_even_if_old_planner_fixture_is_broken(self):
        self.enable()
        MockModels.broken_plan = True
        self.assertEqual(self.send()[0], 200)
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main", "check"])
        self.assert_accounting()

    def test_grounded_review_is_pending_and_never_calls_repair(self):
        self.enable()
        MockModels.answer = MockModels.answer.replace("前排12点按摩", "全车12点按摩")
        MockModels.review = {"issues": [self.review_issue()]}
        MockModels.repair = {"patches": [{"old": "全车12点按摩", "new": "前排12点按摩"}]}
        self.assertEqual(self.send()[0], 200)
        stages = [item["stage"] for item in MockModels.requests]
        self.assertEqual(stages.count("main"), 1)
        self.assertEqual(stages.count("check"), 1)
        self.assertNotIn("repair", stages)
        reply = self.last_reply()
        self.assertEqual(reply["content"], MockModels.answer)
        check = reply["super_check"]
        self.assertFalse(check["repaired"])
        self.assertEqual(check["repair"], {"status": "disabled_review_only", "attempted": False})
        self.assertEqual(len(check["issues"]), 1)
        self.assertEqual(check["issues"][0]["status"], "pending")
        self.assert_accounting()

    def test_unsubstantiated_review_cannot_trigger_rewrite(self):
        self.enable()
        MockModels.review = {"issues": [self.review_issue(quote="前排12点按摩", claim="12点", source_quote="全车20点按摩", expected="20点")]}
        self.assertEqual(self.send()[0], 200)
        self.assertNotIn("repair", [item["stage"] for item in MockModels.requests])
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertEqual(result["messages"][-1]["content"], MockModels.answer)
        check = result["messages"][-1]["super_check"]
        self.assertFalse(check["review_complete"])
        self.assertEqual(check["status"], "failed")
        self.assertEqual(check["issues"], [])
        self.assertTrue(check["review_rejected"])
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
        self.assertEqual(reply["content"], MockModels.answer)
        self.assert_review_only_metadata(reply["super_check"])
        self.assertEqual([item["stage"] for item in MockModels.requests], ["main"])

    def test_review_cannot_apply_unsolicited_whole_manuscript_patch(self):
        self.enable()
        MockModels.answer = MockModels.answer.replace("前排12点按摩", "全车12点按摩")
        MockModels.review = {"issues": [self.review_issue()],
                             "patches": [{"old": MockModels.answer, "new": "完全重写整篇稿件，不保留任何原文。"}]}
        self.assertEqual(self.send()[0], 200)
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertEqual(result["messages"][-1]["content"], MockModels.answer)
        self.assertNotIn("repair", [item["stage"] for item in MockModels.requests])
        self.assert_accounting()

    def test_explicit_local_edit_keeps_raw_main_segment_without_automatic_merge(self):
        self.enable()
        before = "首段必须逐字保留，事实不能顺手更改。\n\n中间这段需要改写，口吻太平。\n\n最后一段必须逐字保留。"
        after = "中间换成自然顺嘴的现场解释。"
        with db() as conn:
            super_writing.save_task_state(conn, self.cid, "default", {"draft": before})
        MockModels.answer = after
        self.assertEqual(self.send("只改中间这一段，其他段落一个字都不要动")[0], 200)
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertEqual(result["messages"][-1]["content"], after)
        self.assertNotIn("plan", [item["stage"] for item in MockModels.requests])
        self.assert_accounting()

    def test_local_edit_keeps_full_or_oversized_main_without_automatic_replacement(self):
        before = "首段必须逐字保留。\n\n中间这段需要改写，口吻太平。\n\n末段也必须逐字保留。"
        self.enable()
        for answer in ["封面文案：擅自重写\n发布文案：另一个版本\n正文：\n整篇稿件都被重写了。", "非常长的替换段。" * 150]:
            with self.subTest(answer_chars=len(answer)):
                with db() as conn:
                    super_writing.save_task_state(conn, self.cid, "default", {"draft": before})
                MockModels.answer = answer
                self.assertEqual(self.send("只改中间这一段，其余不要动")[0], 200)
                _, result = self.request(f"/api/conversations/{self.cid}/messages")
                reply = result["messages"][-1]
                self.assertEqual(reply["content"], answer)
                self.assertFalse(reply["super_check"]["repaired"])
                self.assertNotIn("repair", [item["stage"] for item in MockModels.requests])
        self.assert_accounting()

    def test_local_edit_review_keeps_raw_fragment_even_when_factual_issue_is_found(self):
        before = "首段旧数据为全车12点按摩，按用户要求这一段不得修改。\n\n中间这段需要改写。\n\n末段也必须保持不动。"
        replacement = "这台车前备箱容积有200升。"
        self.enable()
        with db() as conn:
            super_writing.save_task_state(conn, self.cid, "default", {"draft": before})
        MockModels.answer = replacement
        MockModels.review = {"issues": [
            self.review_issue(reason="原文范围错误但属于禁止修改的旧段。"),
            self.review_issue(quote=replacement, claim="200升", source_quote="两驱版前备箱106L", expected="106L", reason="新段容积数据与本单材料不同。"),
        ]}
        MockModels.repair = {"patches": [{"old": replacement, "new": "这台车两驱版前备箱容积106升。"}]}
        self.assertEqual(self.send("只改中间这一段，首尾不动。材料：前排12点按摩、两驱版前备箱106L。")[0], 200)
        repair = [item for item in MockModels.requests if item["stage"] == "repair"]
        self.assertEqual(repair, [])
        _, result = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertEqual(result["messages"][-1]["content"], replacement)
        self.assertEqual([issue["quote"] for issue in result["messages"][-1]["super_check"]["issues"]], [replacement])
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
        planner = next(item["body"] for item in MockModels.requests if item["stage"] == "plan")
        self.assertEqual(planner["model"], "qwen3.7-max")
        self.assertTrue(planner["messages"][0]["content"].startswith("整理本单写稿要求"))
        self.assertEqual([item["stage"] for item in MockModels.requests], ["plan", "main", "check"])
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
