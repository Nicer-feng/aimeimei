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

    def test_parser_markdown_body_labels_and_separate_scripts(self):
        for label in ["**正文：**", "**正文**：", "__正文：__", "__正文__：", "### 正文", "【正文】",
                      "### 正文（口播脚本）", "**正文（口播脚本）：**", "口播正文(约两分钟)："]:
            with self.subTest(label=label):
                source = f"封面文案：别把标题算进正文\n{label}\n第一份口播。\n\n脚本二\n封面文案：第二个标题\n正文：第二份口播。"
                self.assertEqual(writing.manuscript_bodies(source), ["第一份口播。", "第二份口播。"])

    def test_parser_excludes_only_trailing_topic_lines(self):
        body = "大家都在聊#周末出行，这就是今天的话题。\n#内容中途的话题\n接着说自己的体验。"
        source = "正文：\n" + body + "\n\n#品牌话题 #车型话题\n#第三个话题\n"
        self.assertEqual(writing.manuscript_bodies(source), [body])
        check = writing.validate_output(source, writing.requirements({}), "draft")
        self.assertEqual(check["body_chars"], [len(body.replace("\n", ""))])
        self.assertEqual(writing.manuscript_bodies(body + "\n#末尾话题"), [body])
        literal = "正文：\n今天讨论 C# 和 # 符号。\n#这不是话题，而是要读的句子。"
        self.assertEqual(writing.manuscript_bodies(literal), [literal.split("\n", 1)[1]])

    def test_parser_two_scripts_do_not_count_publishing_topics(self):
        source = "**脚本一**\n封面文案：一\n发布文案：发布用的短句。#话题\n正文：\n第一份原文。\n\n#话题甲 #话题乙\n\n---\n**脚本二**\n封面文案：二\n发布文案：第二条短句。\n**正文：**\n第二份原文。\n\n#话题丙"
        self.assertEqual(writing.manuscript_bodies(source), ["第一份原文。", "第二份原文。"])
        restored, _ = writing.preserve_storyboard(source, "分镜改坏了。", "转分镜")
        self.assertTrue(writing.locked_storyboard(source, restored))
        self.assertNotIn("话题", restored)

    def test_parser_excludes_explicit_production_notes_but_keeps_dialogue(self):
        source = """封面文案：这是标题。
### 正文（口播脚本）
**【开头钩子 - 镜头对准主播，表情自然】**
【别急】先把话听完。
**【产品引入 - 手持产品，正面特写】**
产品来了（这个包装挺顺手）。
**【核心卖点1 - 配合画面演示】**
【看完再说。】
**【收尾 - 产品展示+主播总结】**
听听你的看法。
**【画面提示】**
- 场景：室内
- 花字：产品型号
"""
        bodies = writing.manuscript_bodies(source)
        self.assertEqual(len(bodies), 1)
        self.assertEqual([line for line in bodies[0].splitlines() if line.strip()],
                         ["【别急】先把话听完。", "产品来了（这个包装挺顺手）。", "【看完再说。】", "听听你的看法。"])
        check = writing.validate_output(source, writing.requirements({}), "draft")
        expected = "【别急】先把话听完。产品来了（这个包装挺顺手）。【看完再说。】听听你的看法。"
        self.assertEqual(check["body_chars"], [len(expected)])

    def test_sections_separate_cover_publication_body_and_captions(self):
        source = "封面文案：这是封面。\n发布文案：短文案。#话题\n正文：\n只计算这句口播。\n花字：硬数据仅作花字。"
        result = writing.validate_output(source, {}, "draft")
        self.assertEqual(result["body_status"], "recognized")
        self.assertEqual(result["body_scope"], "body")
        self.assertEqual(result["body_chars"], [len("只计算这句口播。")])
        self.assertEqual([part["kind"] for part in result["sections"]], ["cover", "publication", "body", "captions"])
        self.assertEqual(result["sections"][2]["chars"], len("只计算这句口播。"))
        self.assertNotIn("text", result["sections"][2])
        self.assertEqual(writing.manuscript_sections(source)["sections"][2]["text"], "只计算这句口播。")

    def test_missing_body_boundary_does_not_count_entire_delivery(self):
        source = "### 封面文案\n标题内容。\n### 发布文案\n这是发布文案。\n\n后面还有未标明分区的长段文字。"
        result = writing.validate_output(source, {"max_chars": 5}, "draft")
        self.assertEqual(result["body_status"], "unrecognized")
        self.assertEqual(result["body_chars"], [])
        self.assertEqual(result["issues"], [])
        self.assertIn("未检查正文字数", result["count_notice"])
        for incomplete in ("标题：这是唯一标题。", "发布文案：只有发布文案。#品牌", "### 未知交付结构\n一段内容。"):
            with self.subTest(incomplete=incomplete):
                check = writing.validate_output(incomplete, {"max_chars": 1}, "draft")
                self.assertEqual(check["body_status"], "unrecognized")
                self.assertEqual(check["body_chars"], [])
                self.assertEqual(check["issues"], [])

    def test_two_plain_scripts_under_explicit_script_headings_count_separately(self):
        source = "### 脚本一\n第一篇纯口播。\n\n---\n### 脚本二｜另一个切入\n第二篇纯口播。"
        check = writing.validate_output(source, {}, "draft")
        self.assertEqual(check["body_status"], "recognized")
        self.assertEqual(check["body_chars"], [len("第一篇纯口播。"), len("第二篇纯口播。")])

    def test_unknown_internal_heading_does_not_silently_truncate_body(self):
        for heading in ("### 中段", "###中段"):
            source = "正文：\n开场口播。\n" + heading + "\n中间还有很多正文不能默默丢掉。"
            check = writing.validate_output(source, {"min_chars": 100}, "draft")
            self.assertEqual(check["body_status"], "unrecognized")
            self.assertEqual(check["body_chars"], [])
            self.assertEqual(check["issues"], [])
            protected, notice = writing.preserve_storyboard(source, "不可靠分镜", "转分镜")
            self.assertEqual(protected, source)
            self.assertIn("无法确认", notice)

    def test_internal_separator_does_not_silently_truncate_body(self):
        for heading in ("正文：", "### 脚本一"):
            source = heading + "\n一二三四五\n---\n六七八九十"
            check = writing.validate_output(source, {"min_chars": 10}, "draft")
            self.assertEqual(check["body_status"], "unrecognized")
            self.assertEqual(check["body_chars"], [])
            self.assertEqual(check["issues"], [])
        trailing = writing.validate_output("正文：\n一二三四五\n---\n", {}, "draft")
        self.assertEqual(trailing["body_chars"], [5])

    def test_plain_monologue_and_storyboard_have_explicit_count_scope(self):
        plain = writing.validate_output("这是一段没有额外标题的纯口播。", {}, "draft")
        self.assertEqual(plain["body_status"], "plain")
        self.assertEqual(plain["body_chars"], [len("这是一段没有额外标题的纯口播。")])
        source = "| 画面 | 口播内容（语气自然） | 花字 |\n| --- | --- | --- |\n| 车内展示 | 只算这句话。 | 参数不计入正文 |"
        result = writing.validate_output(source, {}, "storyboard")
        self.assertEqual(result["body_status"], "recognized")
        self.assertEqual(result["body_scope"], "dialogue")
        self.assertEqual(result["body_chars"], [len("只算这句话。")])
        limit = {"length_requirement": {"mode": "range", "max_chars": 3, "source_quote": "正文最多3字"}}
        self.assertEqual(len(writing.validate_output(source, limit, "storyboard")["issues"]), 1)

    def test_multiple_storyboard_tables_are_not_one_manuscript(self):
        first = "| 画面 | 台词 | 花字 |\n| --- | --- | --- |\n| 画面一 | 第一表台词。 | 参数一 |"
        second = "| 画面 | 口播内容 | 花字 |\n| --- | --- | --- |\n| 画面二 | 第二表台词更长。 | 参数二 |"
        source = first + "\n\n" + second
        result = writing.validate_output(source, {"min_chars": 100}, "draft")
        self.assertEqual(result["body_scope"], "dialogue")
        self.assertEqual(result["body_chars"], [len("第一表台词。"), len("第二表台词更长。")])
        self.assertEqual(result["issues"], [])
        self.assertIn("未执行单篇字数范围检查", result["count_notice"])
        self.assertEqual(writing.table_dialogue(source), ["第一表台词。", "第二表台词更长。"])

    def test_approximate_length_is_not_invented_hard_bounds(self):
        for mode in ("approx", "target", "none"):
            with self.subTest(mode=mode):
                req = {"min_chars": 700, "max_chars": 800,
                       "length_requirement": {"mode": mode, "target_chars": 750, "source_quote": "正文约750字"}}
                result = writing.validate_output("正文：\n" + "字" * 900, req, "draft")
                self.assertEqual(result["body_chars"], [900])
                self.assertEqual(result["issues"], [])
        req = {"length_requirement": {"mode": "range", "min_chars": 700, "max_chars": 800,
                                      "target_chars": 0, "source_quote": "正文700到800字"}}
        self.assertEqual(len(writing.validate_output("正文：\n" + "字" * 900, req, "draft")["issues"]), 1)
        req["length_requirement"]["mode"] = "approx"
        self.assertEqual(writing.validate_output("正文：\n" + "字" * 900, req, "draft")["issues"], [])

    def test_style_preferences_are_not_code_violations(self):
        req = writing.requirements({"tone": "自然、有观点、少广告味", "notes": "不要死板"})
        self.assertEqual(writing.validate_output("正文：\n产品介绍。", req, "draft")["issues"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
