#!/usr/bin/env python3
"""Local writing integration checks; temporary SQLite and fake upstream only."""
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="aimeimei-writing-test-")
os.environ["AI_PLATFORM_DATA"] = TEMP.name
from app import AppHandler, AIPlatformServer
from ai_platform.database import init_db, db
from ai_platform.runtime import now, token_hash
from ai_platform import writing
from file_share.database import init_share_db


class MockUpstream(BaseHTTPRequestHandler):
    plan = None
    answer = "普通回答。"
    requests = []
    invalid_plan = False
    fail_main = False
    finish_reason = "stop"

    def log_message(self, *args):
        pass

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.__class__.requests.append(data)
        if not data.get("stream"):
            content = "broken json" if self.invalid_plan else json.dumps(self.plan, ensure_ascii=False)
            raw = json.dumps({"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 11, "completion_tokens": 9, "total_tokens": 20}}, ensure_ascii=False).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(raw)
        else:
            if self.fail_main:
                self.send_response(503); self.end_headers(); return
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            event = {"choices": [{"delta": {"content": self.answer}, "finish_reason":self.finish_reason}], "usage": {"prompt_tokens": 30, "completion_tokens": 15, "total_tokens": 45}}
            raw = ("data: " + json.dumps(event, ensure_ascii=False) + "\n\ndata: [DONE]\n\n").encode()
            if self.path.endswith("/responses"):
                events = [{"type":"response.output_text.delta", "delta":self.answer}, {"type":"response.completed", "response":{"status":"completed", "usage":event["usage"]}}]
                raw = "".join("data: " + json.dumps(e,ensure_ascii=False) + "\n\n" for e in events).encode()
            # Exercise UTF-8 chunk splitting through real HTTP.
            for offset in range(0, len(raw), 7):
                self.wfile.write(raw[offset:offset + 7])


class QuietHandler(AppHandler):
    def log_message(self, *args):
        pass


class WritingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db({"family_password_hash": "test-only"})
        init_db({"family_password_hash": "test-only"})
        init_share_db()
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), MockUpstream)
        threading.Thread(target=cls.upstream.serve_forever, daemon=True).start()
        cls.server = AIPlatformServer(("127.0.0.1", 0), QuietHandler, {"admin_key":"local-test-admin-key"})
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = "http://127.0.0.1:" + str(cls.server.server_port)
        with db() as conn:
            cls.uid = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()["id"]
            conn.execute("INSERT INTO users(id,username,display_name,password_hash,role,is_active,created_at,updated_at) VALUES ('other','other','Other','test','family',1,0,0)")
            for uid, token in [(cls.uid, "writing-test"), ("other", "other-test")]:
                conn.execute("INSERT INTO sessions VALUES (?,?,?,?)", (token_hash(token), uid, now(), now() + 3600))
            conn.execute("INSERT INTO models(id,name,provider,base_url,api_key,model,created_at,updated_at) VALUES ('mock','本地测试','mock',?,'fake','mock',0,0)", ("http://127.0.0.1:" + str(cls.upstream.server_port),))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.upstream.shutdown()
        cls.server.server_close(); cls.upstream.server_close()
        TEMP.cleanup()

    def setUp(self):
        MockUpstream.requests = []
        MockUpstream.invalid_plan = False
        MockUpstream.fail_main = False
        MockUpstream.finish_reason = "stop"
        MockUpstream.answer = "视频标题：试试这台车\n视频文案：聊聊日常用车\n正文：\n这台测试车配有后排出风口，夏天后排乘客也能吹到凉风。\n\n再看看后备箱，周末一家人的行李可以按实际空间安排。"
        MockUpstream.plan = {"requirements": writing.requirements({"project":"测试项目", "required":["测试车"], "forbidden":["绝对"], "min_chars":20, "max_chars":500}), "intent":"draft", "scope":"写完整正文", "pasted_draft":"", "confirmed":False, "new_project":False, "full_manuscript":True}
        _, data = self.request("/api/conversations", {"model_id":"mock", "writing_mode":True})
        self.cid = data["conversation"]["id"]

    def request(self, path, data=None, method=None, token="writing-test"):
        req = urllib.request.Request(self.base + path, data=json.dumps(data).encode() if data is not None else None, headers={"Cookie":"ap_session=" + token,"Content-Type":"application/json"},method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                raw = res.read().decode(); status = res.status
                return status, raw if "text/event-stream" in res.headers.get("Content-Type", "") else json.loads(raw)
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def workspace(self):
        return self.request(f"/api/conversations/{self.cid}/writing")[1]["writing"]

    def patch(self, **fields):
        return self.request(f"/api/conversations/{self.cid}/writing", {"revision":self.workspace()["revision"], **fields}, "PATCH")

    def send(self, content="写一条口播稿"):
        return self.request(f"/api/conversations/{self.cid}/messages", {"content":content})

    def test_normal_chat_has_no_writing_call(self):
        self.patch(enabled=False)
        status, stream = self.send("你好")
        self.assertEqual(status, 200)
        self.assertEqual(len(MockUpstream.requests), 1)
        self.assertNotIn(writing.RULES, json.dumps(MockUpstream.requests,ensure_ascii=False))
        self.assertEqual(self.workspace()["versions"], [])

    def test_state_version_usage_and_history(self):
        self.assertEqual(self.send()[0],200)
        state = self.workspace()
        self.assertEqual(state["requirements"]["project"], "测试项目")
        self.assertEqual(state["current"]["content"], MockUpstream.answer)
        self.assertEqual(len(MockUpstream.requests),2)
        self.assertIn("current_draft", MockUpstream.requests[-1]["messages"][-2]["content"])
        _, data = self.request(f"/api/conversations/{self.cid}/messages")
        self.assertEqual(len(data["messages"]),2)
        self.assertIsNotNone(data["messages"][-1]["writing_check"])
        with db() as conn:
            total = conn.execute("SELECT SUM(total_tokens) n FROM messages WHERE conversation_id=?",(self.cid,)).fetchone()["n"]
            self.assertEqual(total,65)
        MockUpstream.plan["intent"]="question"
        self.send("这是什么意思")
        self.assertEqual(self.workspace()["current"]["id"],state["current"]["id"])
        self.assertNotIn("写稿要求整理（辅助调用）",json.dumps(MockUpstream.requests[-1],ensure_ascii=False))

    def test_ownership_and_stale_edits(self):
        self.assertEqual(self.request(f"/api/conversations/{self.cid}/writing",token="other-test")[0],404)
        self.assertEqual(self.request(f"/api/conversations/{self.cid}/writing",{"revision":0,"enabled":True},"PATCH",token="other-test")[0],404)
        self.patch(requirements=writing.requirements({"project":"owner"}))
        self.assertEqual(self.request(f"/api/conversations/{self.cid}/writing",{"revision":0,"enabled":False},"PATCH")[0],409)
        self.assertEqual(self.patch(requirements={"max_chars":-1})[0],400)
        with writing.task_lock(self.uid,self.cid):
            self.assertEqual(self.send()[0],409)

    def test_locked_storyboard_never_streams_changed_dialogue(self):
        original="这台车有后排出风口。\n\n参数还需要客户确认，不能编造。"
        self.patch(draft=original,locked=True)
        MockUpstream.plan.update(intent="storyboard", full_manuscript=False)
        MockUpstream.answer="| 画面 | 台词 | 时长 |\n| --- | --- | --- |\n| 汽车 | 偷改过的台词 | 10s |"
        status, stream = self.send("一个字不要动，分成三段给我分镜")
        self.assertEqual(status,200)
        self.assertNotIn("偷改过",stream)
        _, data=self.request(f"/api/conversations/{self.cid}/messages")
        answer=data["messages"][-1]
        self.assertTrue(writing.locked_storyboard(original,answer["content"]))
        self.assertTrue(answer["writing_check"]["issues"])
        self.assertEqual(self.workspace()["current"]["content"],original)

    def test_invalid_plan_falls_back_without_losing_requirements(self):
        self.patch(requirements=writing.requirements({"project":"保留客户"}))
        MockUpstream.invalid_plan=True
        self.assertEqual(self.send()[0],200)
        self.assertEqual(self.workspace()["requirements"]["project"],"保留客户")
        self.assertTrue(self.workspace()["notice"])

    def test_failed_main_keeps_auxiliary_usage(self):
        MockUpstream.fail_main=True
        self.assertEqual(self.send()[0],502)
        with db() as conn:
            self.assertEqual(conn.execute("SELECT SUM(total_tokens) n FROM messages WHERE conversation_id=?",(self.cid,)).fetchone()["n"],20)
        self.assertEqual(self.workspace()["versions"],[])

    def test_local_edit_merges_without_changing_other_paragraphs(self):
        original = "第一段保持不动。\n\n中间这段需要改写，句子很平。\n\n最后一段保持不动。"
        self.patch(draft=original)
        MockUpstream.plan.update(intent="revise", full_manuscript=False, replace_text="中间这段需要改写，句子很平。")
        MockUpstream.answer = "中间换成有生活场景的新表达。"
        self.assertEqual(self.send("只改中间这一段，其他不动")[0],200)
        self.assertEqual(self.workspace()["current"]["content"], "第一段保持不动。\n\n中间换成有生活场景的新表达。\n\n最后一段保持不动。")

    def test_title_only_and_partial_do_not_replace_manuscript(self):
        self.patch(draft="这是完整底稿，标题修改不能覆盖它。")
        vid=self.workspace()["current_version_id"]
        MockUpstream.plan.update(intent="titles",full_manuscript=False)
        MockUpstream.answer="五个标题"
        self.send("只写标题")
        self.assertEqual(self.workspace()["current_version_id"],vid)
        MockUpstream.plan.update(intent="revise",full_manuscript=False)
        self.send("单独发修改段落")
        self.assertEqual(self.workspace()["current_version_id"],vid)

    def test_legacy_final_draft_is_bootstrapped(self):
        self.patch(enabled=False)
        self.send()
        original=MockUpstream.answer
        self.patch(enabled=True)
        MockUpstream.plan.update(intent="storyboard",full_manuscript=False,confirmed=True)
        MockUpstream.answer="| 台词 |\n| --- |\n| 已经改过 |"
        self.send("这个就是最终脚本，一个字不要动，转分镜")
        self.assertEqual(self.workspace()["current"]["content"],original)
        self.assertTrue(self.workspace()["locked_version_id"])

    def test_new_project_excludes_old_history(self):
        self.send("旧客户的唯一暗号 old-client-marker")
        MockUpstream.plan.update(new_project=True,requirements=writing.requirements({"project":"新客户"}))
        self.send("换一个客户，新项目写稿")
        payload=json.dumps(MockUpstream.requests[-1],ensure_ascii=False)
        self.assertNotIn("old-client-marker",payload)
        self.assertEqual(self.workspace()["requirements"]["project"],"新客户")

    def test_incomplete_answer_keeps_current_draft(self):
        self.patch(draft="已经确认的完整稿件")
        original=self.workspace()["current_version_id"]
        MockUpstream.finish_reason="length"
        self.send()
        self.assertEqual(self.workspace()["current_version_id"],original)
        self.assertIn("未确认完整生成",self.workspace()["notice"])

    def test_native_responses_also_protects_final(self):
        source="原文第一句话。原文第二句话。"
        self.patch(draft=source,locked=True)
        MockUpstream.plan.update(intent="storyboard",full_manuscript=False)
        MockUpstream.answer="| 台词 |\n| --- |\n| 错误改写 |"
        with db() as conn:
            conn.execute("UPDATE models SET supports_native_web_search=1 WHERE id='mock'")
        try:
            with patch("ai_platform.handlers.chat.should_use_web_search",return_value=True):
                status,stream=self.send("转分镜")
            self.assertEqual(status,200)
            self.assertNotIn("错误改写",stream)
            self.assertIn("input",MockUpstream.requests[-1])
            _,data=self.request(f"/api/conversations/{self.cid}/messages")
            self.assertTrue(writing.locked_storyboard(source,data["messages"][-1]["content"]))
        finally:
            with db() as conn:
                conn.execute("UPDATE models SET supports_native_web_search=0 WHERE id='mock'")

    def test_usage_endpoints_and_version_ownership(self):
        self.send()
        for path in ["/api/admin/token-stats", "/api/admin/cost-stats", "/api/admin/token-stats/daily", "/api/admin/token-stats/details?type=models&id=mock"]:
            status,_=self.request(path)
            self.assertEqual(status,200,path)
        vid=self.workspace()["current_version_id"]
        _, data=self.request("/api/conversations",{"model_id":"mock"},token="other-test")
        other=data["conversation"]["id"]
        status,_=self.request(f"/api/conversations/{other}/writing?version_id={vid}",token="other-test")
        self.assertEqual(status,404)

    def test_parser_multiple_manuscripts_and_checks(self):
        source="**视频标题：** 标题一\n**正文：**\n第一份原文。\n\n---\n### 脚本二\n视频标题：标题二\n正文：第二份原文。"
        self.assertEqual(writing.manuscript_bodies(source),["第一份原文。","第二份原文。"])
        repaired,_=writing.preserve_storyboard(source,"bad","分成五段")
        self.assertTrue(writing.locked_storyboard(source,repaired))
        check=writing.validate_output("正文：绝对好，数据xxx。",writing.requirements({"required":["车型全称"],"forbidden":["绝对"],"min_chars":100}),"draft")
        self.assertEqual(len(check["issues"]),4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
