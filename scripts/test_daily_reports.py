"""隔离 HTTP、SQLite 与模拟 APNs 服务回归，不读取真实密钥或发送真实通知。"""
import json
import threading
import time
import unittest
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from test_reading import ReadingTests
from ai_platform.database import db
from ai_platform.runtime import now, token_hash
from ai_platform.daily_reports import publish_report, deliver_pending, notification_preview


class DailyReportPreviewTests(unittest.TestCase):
    def test_plain_text_and_wrapped_list_items(self):
        content = "## 今日前端更新\n\n- **PDF**：[阅读位置](https://example.invalid)与 `sunwoo_flutter`\n  跨行说明\n- __录屏__：*布局*优化\n- 后台：~~旧版~~新版\n- 不展示第四条"
        self.assertEqual(notification_preview(content), "- PDF：阅读位置与 sunwoo_flutter 跨行说明\n- 录屏：布局优化\n- 后台：旧版新版\n点击查看完整日报")

    def test_long_items_do_not_hide_later_modules(self):
        preview = notification_preview("1. " + "甲" * 500 + "\n2. 第二模块\n3. 第三模块\n4. 第四模块")
        self.assertIn("甲" * 89 + "…", preview)
        self.assertIn("第二模块", preview)
        self.assertIn("第三模块", preview)
        self.assertNotIn("第四模块", preview)
        self.assertLessEqual(len(preview), 300)

    def test_empty_formatting_and_code_use_fallback(self):
        fallback = "今日日报已更新，点击查看详情"
        for content in ("", "## 标题\n---", "```python\n不应预览的代码\n```", "~~~\n```\n仍在代码内\n~~~", "- ![](image.png)"):
            with self.subTest(content=content):
                self.assertEqual(notification_preview(content), fallback)

    def test_paragraphs_and_quotes_are_readable(self):
        self.assertEqual(notification_preview("> **PDF** 更新\n\n下一段正文"), "- PDF 更新\n- 下一段正文\n点击查看完整日报")


class FakeAPNs(BaseHTTPRequestHandler):
    status = 200
    reason = ""
    requests = []
    payload_sizes = []
    responses = {}
    def log_message(self, *args):
        pass
    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).payload_sizes.append(len(raw))
        body = json.loads(raw)
        type(self).requests.append((dict(self.headers), body, self.path))
        status, reason = type(self).responses.get(self.path, (type(self).status, type(self).reason))
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"reason": reason}).encode())


class DailyReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ReadingTests.setUpClass()
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), FakeAPNs)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.path = Path(ReadingTests.temp.name)
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        cls.key = ec.generate_private_key(ec.SECP256R1())
        key_path = cls.path / "fake.p8"
        key_path.write_bytes(cls.key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        (cls.path / "apns.json").write_text(json.dumps({"key_id": "TESTKEY001", "team_id": "TESTTEAM01", "key_path": str(key_path)}))
        cls.patches = [patch("ai_platform.daily_reports.DATA_DIR", cls.path), patch("ai_platform.daily_reports.APNS_ORIGIN", f"http://127.0.0.1:{cls.http.server_port}")]
        for p in cls.patches:
            p.start()
        with db() as conn:
            conn.execute("INSERT INTO users(id,username,display_name,password_hash,created_at,updated_at) VALUES('daily-feng','feng','test','x',?,?)", (now(),now()))
            conn.execute("INSERT INTO sessions VALUES(?,?,?,?)", (token_hash("daily-feng"),"daily-feng",now(),now()+3600))
            conn.execute("INSERT INTO users(id,username,display_name,password_hash,created_at,updated_at) VALUES('daily-czq','czq','test','x',?,?)", (now(),now()))
            conn.execute("INSERT INTO sessions VALUES(?,?,?,?)", (token_hash("daily-czq"),"daily-czq",now(),now()+3600))
            conn.execute("UPDATE users SET daily_reports_enabled=1,daily_push_enabled=1 WHERE username IN ('feng','czq')")

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close()
        for p in reversed(cls.patches):
            p.stop()
        ReadingTests.tearDownClass()

    def setUp(self):
        FakeAPNs.requests = []; FakeAPNs.status = 200; FakeAPNs.reason = ""
        FakeAPNs.payload_sizes = []
        FakeAPNs.responses = {}
        with db() as conn:
            conn.execute("DELETE FROM report_push_deliveries")
            conn.execute("DELETE FROM report_push_devices")
            conn.execute("DELETE FROM daily_reports")
            conn.execute("UPDATE users SET is_active=1 WHERE username IN ('feng','czq')")
            conn.execute("UPDATE users SET daily_reports_enabled=CASE WHEN username IN ('feng','czq') THEN 1 ELSE 0 END,daily_push_enabled=CASE WHEN username IN ('feng','czq') THEN 1 ELSE 0 END,daily_push_after_id=0")
            conn.execute("UPDATE daily_report_settings SET paused=0,push_after_id=0")

    def req(self, path="", method="GET", body=None, user="daily-feng"):
        import urllib.request
        import urllib.error
        headers = {"Authorization": "Bearer " + user} if user else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(ReadingTests.url + "/api/daily-reports" + path,
            data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def publish(self, day=None, content="测试日报 **私有正文**", simulation=False):
        return publish_report({"date": day or date.today().isoformat(), "content": content, "simulation": simulation})

    def register(self, token="a"*64, installation="test-installation-1234", user="daily-feng"):
        return self.req("/device", "POST", {"token":token,"installation_id":installation}, user=user)

    def test_two_recipients_have_same_content_and_isolated_read_state(self):
        self.register()
        self.register(token="b"*64, user="daily-czq")
        with db() as conn:
            before = tuple(conn.execute("SELECT (SELECT COUNT(*) FROM conversations),(SELECT COUNT(*) FROM messages)").fetchone())
        result = self.publish()
        self.assertEqual(result["registered_devices"], 2)
        self.assertEqual(result["delivery"]["accepted"], 2)
        self.assertEqual([r["username"] for r in result["reports"]], ["feng", "czq"])
        first, second = result["reports"]
        self.assertNotEqual(first["report_id"], second["report_id"])
        feng = self.req()[1]["reports"][0]
        czq = self.req(user="daily-czq")[1]["reports"][0]
        self.assertEqual(feng["content"], czq["content"])
        self.assertTrue(czq["title"].startswith("研发日报"))
        self.assertEqual(self.req(f"/{feng['id']}", user="daily-czq")[0], 404)
        self.assertEqual(self.req(f"/{czq['id']}/read", "POST", {})[0], 404)
        self.assertEqual(self.req(f"/{feng['id']}/read", "POST", {})[0], 200)
        self.assertEqual(self.req(user="daily-czq")[1]["unread"], 1)
        self.publish()
        self.assertEqual(len(FakeAPNs.requests), 2)
        with db() as conn:
            after = tuple(conn.execute("SELECT (SELECT COUNT(*) FROM conversations),(SELECT COUNT(*) FROM messages)").fetchone())
        self.assertEqual(before, after)

    def test_retry_only_failed_recipient(self):
        self.register()
        self.register(token="b"*64, user="daily-czq")
        FakeAPNs.responses["/3/device/" + "b"*64] = (503, "ServiceUnavailable")
        result = self.publish()
        self.assertEqual(result["reports"][0]["delivery"]["accepted"], 1)
        self.assertEqual(result["reports"][1]["delivery"]["pending"], 1)
        FakeAPNs.responses = {}
        self.assertEqual(deliver_pending()["accepted"], 1)
        self.assertEqual(len(FakeAPNs.requests), 3)
        self.assertTrue(FakeAPNs.requests[-1][2].endswith("b"*64))
        self.publish()
        self.assertEqual(len(FakeAPNs.requests), 3)

    def test_first_device_registration_and_same_body_retry_do_not_backfill_notifications(self):
        original=self.publish()
        self.assertEqual(original['registered_devices'],0)
        self.assertEqual(self.register()[0],200)
        self.assertEqual(FakeAPNs.requests,[])
        repeated=self.publish()
        self.assertEqual(repeated['delivery']['accepted'],0)
        with db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM report_push_deliveries').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM daily_reports').fetchone()[0],2)
        self.assertEqual(self.publish(simulation=True)['delivery']['accepted'],1)

    def test_conflict_rolls_back_all_recipients(self):
        original = self.publish()
        with db() as conn:
            conn.execute("DELETE FROM daily_reports WHERE user_id='daily-feng'")
        with self.assertRaisesRegex(ValueError, "未覆盖"):
            self.publish(content="不允许部分覆盖")
        self.assertEqual(self.req()[1]["reports"], [])
        other = self.req(user="daily-czq")[1]["reports"]
        self.assertEqual(other[0]["id"], original["reports"][1]["report_id"])
        self.assertEqual(other[0]["content"], "测试日报 **私有正文**")

    def test_inactive_recipient_does_not_block_other_account(self):
        with db() as conn:
            conn.execute("UPDATE users SET is_active=0 WHERE username='czq'")
        self.register()
        result = self.publish()
        self.assertEqual([r["username"] for r in result["reports"]], ["feng"])
        self.assertEqual(len(result["reports"]), 1)
        self.assertEqual(result["delivery"]["accepted"], 1)

    def test_device_token_follows_current_account_not_installation_id(self):
        self.register()
        # 同安装 ID、不同 token 的其他手机不被误删。
        self.register(token="b"*64, user="daily-czq")
        self.register(user="daily-czq", installation="switched-installation-1234")
        self.req("/device", "DELETE", {"installation_id":"switched-installation-1234"})
        with db() as conn:
            users = conn.execute("SELECT user_id,COUNT(*) FROM report_push_devices GROUP BY user_id").fetchall()
        self.assertEqual([tuple(row) for row in users], [("daily-czq", 2)])
        result = self.publish()
        self.assertEqual(result["reports"][0]["registered_devices"], 0)
        self.assertEqual(result["reports"][1]["delivery"]["accepted"], 2)

    def admin(self, path, data=None, method=None, authorized=True):
        import urllib.request
        import urllib.error
        headers = {"X-Admin-Key": "test-only"} if authorized else {"Authorization": "Bearer reader-a"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(ReadingTests.url + path, method=method,
            headers=headers, data=json.dumps(data).encode() if data is not None else None)
        try:
            with urllib.request.urlopen(req) as response: return response.status, json.load(response)
        except urllib.error.HTTPError as error: return error.code, json.load(error)

    def flags(self, uid, read=True, push=True, **extra):
        result = self.admin('/api/admin/users/' + uid, {"daily_reports_enabled":read,"daily_push_enabled":push,**extra}, 'PUT')
        self.assertEqual(result[0], 200)
        return result[1]

    def test_admin_only_dynamic_recipient_and_independent_switches(self):
        self.assertEqual(self.admin('/api/admin/users/reader-a', {"daily_reports_enabled":True}, 'PUT', False)[0], 401)
        self.assertEqual(self.admin('/api/admin/daily-report-settings', {"paused":True}, authorized=False)[0], 401)
        self.assertEqual(self.admin('/api/admin/users/reader-a', {"daily_push_enabled":"false"}, 'PUT')[0], 400)
        self.flags('reader-a', push=False)
        result = self.publish()
        self.assertEqual(result['recipient_count'], 3)
        own = self.req(user='reader-a')[1]
        self.assertEqual(own['unread'], 1)
        self.assertEqual(self.register(user='reader-a')[0], 403)
        other = next(r for r in result['reports'] if r['username'] == 'feng')
        self.assertEqual(self.req('/'+str(other['report_id']), user='reader-a')[0], 404)
        self.flags('reader-a', read=False, push=True)
        self.assertEqual(self.req(user='reader-a')[0], 404)

    def test_push_disable_and_reenable_do_not_replay_history(self):
        self.register()
        FakeAPNs.status=503; FakeAPNs.reason='ServiceUnavailable'
        old = self.publish()
        self.assertEqual(old['delivery']['pending'], 1)
        self.flags('daily-feng', push=False)
        FakeAPNs.status=200
        self.assertEqual(deliver_pending()['accepted'], 0)
        self.assertEqual(self.req()[0], 200)
        self.flags('daily-feng')
        self.publish()
        self.register()
        self.assertEqual(len(FakeAPNs.requests), 1)
        self.assertEqual(self.publish(simulation=True)['delivery']['accepted'], 1)

    def test_global_pause_saves_reports_without_replaying_notifications(self):
        self.register()
        self.assertEqual(self.admin('/api/admin/daily-report-settings', {'paused':True})[0], 200)
        result = self.publish()
        self.assertEqual(result['recipient_count'], 2)
        self.assertEqual(result['delivery']['accepted'], 0)
        self.assertEqual(self.req()[1]['unread'], 1)
        self.admin('/api/admin/daily-report-settings', {'paused':False})
        self.publish(); self.register()
        self.assertEqual(len(FakeAPNs.requests), 0)
        self.assertEqual(self.publish(simulation=True)['delivery']['accepted'], 1)

    def test_deactivation_stops_pending_retry_and_revokes_access(self):
        self.register()
        FakeAPNs.status=503; FakeAPNs.reason='ServiceUnavailable'
        self.publish()
        self.flags('daily-feng', is_active=False)
        FakeAPNs.status=200
        self.assertEqual(deliver_pending()['accepted'], 0)
        self.assertEqual(self.req()[0], 401)
        with db() as conn:
            conn.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?,?)', (token_hash('daily-feng'),'daily-feng',now(),now()+3600))

    def test_permission_migration_seeds_only_once(self):
        import sqlite3
        from ai_platform.daily_reports import init_daily_report_tables
        with sqlite3.connect(':memory:') as conn:
            conn.execute('CREATE TABLE users(id TEXT PRIMARY KEY,username TEXT)')
            conn.executemany('INSERT INTO users VALUES(?,?)', [('1','feng'),('2','czq'),('3','other')])
            init_daily_report_tables(conn)
            self.assertEqual(list(conn.execute('SELECT daily_reports_enabled,daily_push_enabled FROM users ORDER BY id')), [(1,1),(1,1),(0,0)])
            conn.execute('UPDATE users SET daily_reports_enabled=0,daily_push_enabled=0')
            init_daily_report_tables(conn)
            self.assertEqual(conn.execute('SELECT SUM(daily_reports_enabled) FROM users').fetchone()[0], 0)

    def test_enabling_new_recipient_does_not_backfill_published_day(self):
        self.publish()
        self.flags('reader-a')
        again = self.publish()
        self.assertEqual(again['skipped_new_recipients'], ['reader-a'])
        self.assertEqual(self.req(user='reader-a')[1]['reports'], [])
        self.assertEqual(self.publish(simulation=True)['recipient_count'], 3)

    def test_all_permission_and_pause_combinations(self):
        self.flags('daily-feng', read=False, push=False)
        self.flags('daily-czq', read=False, push=False)
        for i, (read, push, paused) in enumerate((r,p,g) for r in (False,True) for p in (False,True) for g in (False,True)):
            with self.subTest(read=read, push=push, paused=paused):
                self.flags('reader-a', read, push)
                self.admin('/api/admin/daily-report-settings', {'paused':paused})
                code = self.register(user='reader-a')[0]
                self.assertEqual(code, 404 if not read else 403 if not push else 200)
                result = self.publish(day=(date.today()+timedelta(days=i+1)).isoformat())
                self.assertEqual(result['recipient_count'], int(read))
                self.assertEqual(result['delivery']['accepted'], int(read and push and not paused))

    def test_account_isolation_and_read_only_contract(self):
        rid = self.publish()["report_id"]
        for path in ("", f"/{rid}", "/device"):
            self.assertEqual(self.req(path,user=None)[0],401)
            self.assertEqual(self.req(path,user="reader-a")[0],404)
        for method in ("POST", "PATCH", "DELETE", "PUT"):
            self.assertEqual(self.req(f"/{rid}",method,{"content":"tampered"})[0],405)
        self.assertEqual(self.req("", "POST", {"content":"no chat"})[0],405)
        self.assertEqual(self.req(f"/{rid}/messages", "POST", {"content":"no model"})[0],405)
        self.assertEqual(self.req(f"/{rid}/read", "POST", {})[0],200)
        # 现有处理器在 SQLite 上下文退出前写出响应，等待工作线程完成提交。
        deadline = time.monotonic() + 1
        read_at = self.req(f"/{rid}")[1]["report"]["read_at"]
        while not read_at and time.monotonic() < deadline:
            time.sleep(0.01)
            read_at = self.req(f"/{rid}")[1]["report"]["read_at"]
        self.assertGreater(read_at,0)

    def test_idempotency_and_real_apns_http_request(self):
        self.assertEqual(self.register()[0],200)
        report = self.publish()
        self.assertEqual(self.publish()["report_id"],report["report_id"])
        self.assertEqual(len(FakeAPNs.requests),1)
        headers,payload,path = FakeAPNs.requests[0]
        self.assertEqual(headers["apns-topic"],"asia.feng.aimeimei")
        self.assertEqual(headers["apns-push-type"],"alert")
        self.assertEqual(payload["aps"]["alert"]["body"], notification_preview("测试日报 **私有正文**"))
        self.assertEqual(payload["kind"], "frontend_daily")
        self.assertEqual(payload["aps"]["thread-id"], "frontend-daily")
        self.assertEqual(payload["report_id"],report["report_id"])
        import jwt
        auth = headers["authorization"].split(" ",1)[1]
        self.assertEqual(jwt.decode(auth,self.key.public_key(),algorithms=["ES256"])["iss"],"TESTTEAM01")
        with self.assertRaises(ValueError):
            self.publish(content="不同正文")
        self.assertEqual(self.req()[1]["unread"],1)
        self.publish(simulation=True)
        self.assertEqual(len(self.req()[1]["reports"]),2)

    def test_preview_payload_size_and_full_report_preserved(self):
        self.register()
        for content in ("## 日报\n" + "\n".join("- " + "😀" * 500 for _ in range(4)),
                        "## 日报\n" + "\n".join("- " + "中文摘要" * 100 for _ in range(4))):
            with self.subTest(content_type=content[10:20]):
                report = self.publish(content=content, simulation="中文" in content)
                headers, payload, path = FakeAPNs.requests[-1]
                self.assertEqual(payload["report_id"], report["report_id"])
                self.assertLessEqual(FakeAPNs.payload_sizes[-1], 4096)
                self.assertLessEqual(len(payload["aps"]["alert"]["body"]), 300)
                self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False).encode("utf-8")), 4096)
                self.assertLessEqual(len(json.dumps(payload, ensure_ascii=True).encode("ascii")), 4096)
                self.assertEqual(self.req(f"/{report['report_id']}")[1]["report"]["content"], content)

    def test_transient_retry_and_invalid_token(self):
        self.register()
        FakeAPNs.status=503; FakeAPNs.reason="ServiceUnavailable"
        result=self.publish()
        self.assertEqual(result["delivery"]["pending"],1)
        FakeAPNs.status=200
        self.assertEqual(deliver_pending()["accepted"],1)
        self.assertEqual(FakeAPNs.requests[0][1], FakeAPNs.requests[1][1])
        self.assertEqual(deliver_pending()["accepted"],0)
        FakeAPNs.status=410; FakeAPNs.reason="Unregistered"
        self.publish(simulation=True)
        count=len(FakeAPNs.requests)
        deliver_pending()
        self.assertEqual(len(FakeAPNs.requests),count)

    def test_token_deduplication_logout_and_pagination(self):
        self.register()
        self.register(installation="new-installation-1234")
        with db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM report_push_devices").fetchone()[0],1)
            conn.execute("UPDATE sessions SET expires_at=0 WHERE user_id='daily-feng'")
        self.assertEqual(self.publish()["delivery"]["accepted"],0)
        with db() as conn:
            conn.execute("UPDATE sessions SET expires_at=? WHERE user_id='daily-feng'",(now()+3600,))
        self.assertEqual(self.req("/device","DELETE",{"installation_id":"new-installation-1234"})[0],200)
        for offset in range(1,33):
            self.publish(day=(date.today()-timedelta(days=offset)).isoformat())
        first=self.req()[1]
        self.assertEqual(len(first["reports"]),30)
        self.assertEqual(len(self.req("?before="+str(first["next_before"]))[1]["reports"]),3)

    def test_validation_and_sanitized_backup(self):
        for data in ({"token":"bad","installation_id":"test-installation-1234"},[],{"token":"a"*64}):
            self.assertEqual(self.req("/device","POST",data)[0],400)
        for payload in ({"date":"2026-99-99","content":"x"},{"date":"2026-10-26","content":""},{"date":"2026-10-26","content":"x","user_id":"other"}):
            with self.assertRaises(ValueError):
                publish_report(payload)
        self.register()
        from ai_platform.backup import create_sanitized_snapshot
        create_sanitized_snapshot(self.path/"test.db",self.path/"sanitized.db")
        import sqlite3
        with sqlite3.connect(self.path/"sanitized.db") as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM report_push_devices").fetchone()[0],0)


if __name__ == "__main__":
    unittest.main()
