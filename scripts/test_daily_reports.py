"""隔离 HTTP、SQLite 与模拟 APNs 服务回归，不读取真实密钥或发送真实通知。"""
import json
import threading
import unittest
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from test_reading import ReadingTests
from ai_platform.database import db
from ai_platform.runtime import now, token_hash
from ai_platform.daily_reports import publish_report, deliver_pending


class FakeAPNs(BaseHTTPRequestHandler):
    status = 200
    reason = ""
    requests = []
    def log_message(self, *args):
        pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append((dict(self.headers), body, self.path))
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"reason": type(self).reason}).encode())


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

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown(); cls.http.server_close()
        for p in reversed(cls.patches):
            p.stop()
        ReadingTests.tearDownClass()

    def setUp(self):
        FakeAPNs.requests = []; FakeAPNs.status = 200; FakeAPNs.reason = ""
        with db() as conn:
            conn.execute("DELETE FROM report_push_deliveries")
            conn.execute("DELETE FROM report_push_devices")
            conn.execute("DELETE FROM daily_reports")

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

    def register(self, token="a"*64, installation="test-installation-1234"):
        return self.req("/device", "POST", {"token":token,"installation_id":installation})

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
        self.assertGreater(self.req(f"/{rid}")[1]["report"]["read_at"],0)

    def test_idempotency_and_real_apns_http_request(self):
        report = self.publish()
        self.assertEqual(self.register()[0],200)
        self.assertEqual(self.publish()["report_id"],report["report_id"])
        self.assertEqual(len(FakeAPNs.requests),1)
        headers,payload,path = FakeAPNs.requests[0]
        self.assertEqual(headers["apns-topic"],"asia.feng.aimeimei")
        self.assertEqual(headers["apns-push-type"],"alert")
        self.assertNotIn("私有正文",json.dumps(payload,ensure_ascii=False))
        self.assertEqual(payload["report_id"],report["report_id"])
        import jwt
        auth = headers["authorization"].split(" ",1)[1]
        self.assertEqual(jwt.decode(auth,self.key.public_key(),algorithms=["ES256"])["iss"],"TESTTEAM01")
        with self.assertRaises(ValueError):
            self.publish(content="不同正文")
        self.assertEqual(self.req()[1]["unread"],1)
        self.publish(simulation=True)
        self.assertEqual(len(self.req()[1]["reports"]),2)

    def test_transient_retry_and_invalid_token(self):
        self.register()
        FakeAPNs.status=503; FakeAPNs.reason="ServiceUnavailable"
        result=self.publish()
        self.assertEqual(result["delivery"]["pending"],1)
        FakeAPNs.status=200
        self.assertEqual(deliver_pending()["accepted"],1)
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
