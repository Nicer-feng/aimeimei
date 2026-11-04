"""临时数据库、本机 HTTP 和模拟 APNs 验证产品频道隔离与真实投递请求。"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta

import test_daily_reports as fixture
from ai_platform.database import db
from ai_platform.daily_reports import publish_report as publish_daily
from ai_platform.login_history import record_login
from ai_platform.product_reports import (
    configure_user_product_reports, deliver_pending, init_product_report_tables,
    notification_preview, publication_status, publish_report, recent_history,
)
from ai_platform.runtime import now, token_hash


class ProductReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.DailyReportTests.setUpClass()
        cls.path = fixture.DailyReportTests.path

    @classmethod
    def tearDownClass(cls):
        fixture.DailyReportTests.tearDownClass()

    def setUp(self):
        fixture.FakeAPNs.requests = []
        fixture.FakeAPNs.payload_sizes = []
        fixture.FakeAPNs.responses = {}
        fixture.FakeAPNs.status = 200
        fixture.FakeAPNs.reason = ""
        with db() as conn:
            init_product_report_tables(conn)
            conn.execute("DELETE FROM product_push_deliveries")
            conn.execute("DELETE FROM product_push_subscriptions")
            conn.execute("DELETE FROM report_push_deliveries")
            conn.execute("DELETE FROM report_push_devices")
            conn.execute("DELETE FROM product_reports")
            conn.execute("DELETE FROM daily_reports")
            conn.execute("UPDATE product_report_settings SET paused=0,push_after_id=0")
            conn.execute("UPDATE daily_report_settings SET paused=0,push_after_id=0")
            conn.execute("UPDATE users SET is_active=1,product_reports_enabled=0,product_push_enabled=0,product_push_after_id=0,daily_reports_enabled=0,daily_push_enabled=0,daily_push_after_id=0")
            conn.execute("UPDATE users SET product_reports_enabled=1,product_push_enabled=1,daily_reports_enabled=1,daily_push_enabled=1 WHERE username IN ('feng','czq')")
            for uid in ("daily-feng","daily-czq"):
                conn.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?,?)", (token_hash(uid),uid,now(),now()+3600))
                conn.execute("DELETE FROM auth_session_history WHERE token_hash=?", (token_hash(uid),))
                record_login(conn,uid,token_hash(uid),now(),now()+3600,
                             {"platform":"ios","installation_id":"product-installation-1234"},"",None,"unavailable")

    def request(self, path="", method="GET", body=None, user="daily-feng", admin=False):
        headers = {"X-Admin-Key":"test-only"} if admin else {"Authorization":"Bearer " + user} if user else {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        target = path if path.startswith("/api/") else "/api/product-reports" + path
        request = urllib.request.Request(fixture.ReadingTests.url + target,method=method,headers=headers,
            data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(request,timeout=15) as response:
                return response.status,json.load(response)
        except urllib.error.HTTPError as error:
            return error.code,json.load(error)

    def register(self, user="daily-feng", token="a"*64):
        return self.request("/device","POST",{"installation_id":"product-installation-1234","token":token},user=user)

    def register_daily(self):
        return self.request("/api/daily-reports/device","POST",{"installation_id":"product-installation-1234","token":"a"*64})

    def publish(self, content="- [好用产品](https://example.invalid) 带来新体验", day=None, simulation=False):
        return publish_report({"date":day or date.today().isoformat(),"content":content,"simulation":simulation})

    def flags(self, user="daily-feng", read=True, push=True, **extra):
        return self.request("/api/admin/users/" + user,"PUT",
            {"product_reports_enabled":read,"product_push_enabled":push,**extra},admin=True)

    def pause(self, paused):
        return self.request("/api/admin/product-report-settings","POST",{"paused":paused},admin=True)

    def test_initialization_only_seeds_existing_target_accounts_once(self):
        with sqlite3.connect(":memory:") as conn:
            conn.execute("CREATE TABLE users(id TEXT PRIMARY KEY,username TEXT)")
            conn.executemany("INSERT INTO users VALUES(?,?)",[("1","feng"),("2","czq"),("3","other")])
            init_product_report_tables(conn)
            self.assertEqual(list(conn.execute("SELECT product_reports_enabled,product_push_enabled FROM users ORDER BY id")),[(1,1),(1,1),(0,0)])
            conn.execute("UPDATE users SET product_reports_enabled=0,product_push_enabled=0")
            init_product_report_tables(conn)
            self.assertEqual(conn.execute("SELECT SUM(product_reports_enabled) FROM users").fetchone()[0],0)

    def test_two_owners_same_body_independent_reads_and_product_payload(self):
        self.assertEqual(self.register()[0],200)
        self.assertEqual(self.register(user="daily-czq",token="b"*64)[0],200)
        result = self.publish()
        self.assertEqual(result["recipient_count"],2)
        self.assertEqual(result["delivery"]["accepted"],2)
        feng, czq = result["reports"]
        self.assertNotEqual(feng["report_id"],czq["report_id"])
        own = self.request()[1]["reports"][0]
        other = self.request(user="daily-czq")[1]["reports"][0]
        self.assertEqual(own["content"],other["content"])
        self.assertTrue(own["title"].startswith("每日产品推送"))
        self.assertEqual(self.request(f"/{own['id']}",user="daily-czq")[0],404)
        self.assertEqual(self.request(f"/{own['id']}/read","POST",{})[0],200)
        self.assertEqual(self.request(user="daily-czq")[1]["unread"],1)
        headers,payload,_ = fixture.FakeAPNs.requests[0]
        self.assertEqual(payload["kind"],"product_daily")
        self.assertEqual(payload["aps"]["thread-id"],"product-daily")
        self.assertIn("产品推送",payload["aps"]["alert"]["body"])
        self.assertEqual(headers["apns-topic"],"asia.feng.aimeimei")
        self.assertTrue(headers["apns-collapse-id"].startswith("product-"))
        self.assertEqual(len(self.request("/api/daily-reports")[1]["reports"]),0)

    def test_ios_metadata_and_current_session_are_required(self):
        with db() as conn:
            conn.execute("UPDATE auth_devices SET metadata_json=? WHERE user_id='daily-feng'", (json.dumps({"platform":"android"}),))
        self.assertEqual(self.register()[0],403)
        with db() as conn:
            conn.execute("UPDATE auth_devices SET metadata_json=? WHERE user_id='daily-feng'", (json.dumps({"platform":"ios"}),))
        self.assertEqual(self.register()[0],200)
        with db() as conn:
            conn.execute("UPDATE auth_devices SET metadata_json=? WHERE user_id='daily-feng'", (json.dumps({"platform":"android"}),))
        self.assertEqual(self.publish()["delivery"]["accepted"],0)
        self.assertEqual(publication_status()["recipients"][1]["registered_devices"],0)
        self.assertEqual(self.request(user=None)[0],401)
        self.assertEqual(self.request(user="reader-a")[0],404)

    def test_non_target_account_cannot_be_enabled_even_if_manually_flagged(self):
        self.assertEqual(self.flags(user="reader-a")[0],400)
        with db() as conn:
            conn.execute("UPDATE users SET product_reports_enabled=1,product_push_enabled=1 WHERE id='reader-a'")
        self.assertEqual(self.request(user="reader-a")[0],404)
        self.assertEqual(self.publish()["recipient_count"],2)

    def test_idempotency_conflict_and_no_partial_overwrite(self):
        self.register()
        original = self.publish()
        self.assertEqual(self.publish()["report_id"],original["report_id"])
        self.assertEqual(len(fixture.FakeAPNs.requests),1)
        with self.assertRaisesRegex(ValueError,"未覆盖"):
            self.publish(content="不同内容")
        with db() as conn:
            conn.execute("DELETE FROM product_push_deliveries WHERE report_id=?", (original["report_id"],))
            conn.execute("DELETE FROM product_reports WHERE id=?", (original["report_id"],))
        with self.assertRaisesRegex(ValueError,"未覆盖"):
            self.publish(content="仍然不同")
        self.assertEqual(self.request()[1]["reports"],[])

    def test_product_unsubscribe_preserves_daily_device_and_only_cancels_product(self):
        self.assertEqual(self.register_daily()[0],200)
        self.register()
        fixture.FakeAPNs.status=503
        fixture.FakeAPNs.reason="ServiceUnavailable"
        self.assertEqual(self.publish()["delivery"]["pending"],1)
        self.assertEqual(self.request("/device","DELETE",{"installation_id":"product-installation-1234"})[0],200)
        with db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM report_push_devices").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM product_push_subscriptions").fetchone()[0],0)
        fixture.FakeAPNs.status=200
        self.assertEqual(deliver_pending()["accepted"],0)
        result=publish_daily({"date":date.today().isoformat(),"content":"研发日报仍然可推"})
        self.assertEqual(result["delivery"]["accepted"],1)
        self.assertEqual(fixture.FakeAPNs.requests[-1][1]["kind"],"frontend_daily")

    def test_product_only_registration_does_not_subscribe_daily_channel(self):
        self.register()
        daily=publish_daily({"date":date.today().isoformat(),"content":"日报"})
        self.assertEqual(daily["delivery"]["accepted"],0)
        self.assertEqual(self.publish()["delivery"]["accepted"],1)

    def test_daily_unsubscribe_preserves_product_and_stops_daily_delivery(self):
        self.assertEqual(self.register_daily()[0],200)
        self.register()
        self.assertEqual(self.request("/api/daily-reports/device","DELETE",{"installation_id":"product-installation-1234"})[0],200)
        self.assertEqual(publish_daily({"date":date.today().isoformat(),"content":"日报"})["delivery"]["accepted"],0)
        self.assertEqual(self.publish()["delivery"]["accepted"],1)

    def test_daily_permission_and_global_pause_do_not_block_product_channel(self):
        self.register()
        self.assertEqual(self.request("/api/admin/users/daily-feng","PUT",{"daily_reports_enabled":False,"daily_push_enabled":False},admin=True)[0],200)
        self.assertEqual(self.request("/api/admin/daily-report-settings","POST",{"paused":True},admin=True)[0],200)
        self.assertEqual(self.publish()["delivery"]["accepted"],1)

    def test_pause_saves_content_and_resume_never_replays_old_records(self):
        self.register()
        self.assertEqual(self.pause(True)[0],200)
        self.assertTrue(self.request("/api/admin/product-report-settings",admin=True)[1]["paused"])
        original=self.publish()
        self.assertEqual(original["recipient_count"],2)
        self.assertEqual(original["delivery"]["accepted"],0)
        self.assertEqual(self.pause(False)[0],200)
        self.publish()
        self.register()
        self.assertEqual(fixture.FakeAPNs.requests,[])
        self.assertEqual(self.publish(simulation=True)["delivery"]["accepted"],1)

    def test_permission_disable_resume_and_deactivation_cancel_pending(self):
        self.register()
        fixture.FakeAPNs.status=503
        fixture.FakeAPNs.reason="ServiceUnavailable"
        self.publish()
        self.assertEqual(self.flags(push=False)[0],200)
        fixture.FakeAPNs.status=200
        self.assertEqual(deliver_pending()["accepted"],0)
        self.assertEqual(self.flags()[0],200)
        self.publish()
        self.assertEqual(len(fixture.FakeAPNs.requests),1)
        self.assertEqual(self.publish(simulation=True)["delivery"]["accepted"],1)
        self.assertEqual(self.flags(is_active=False)[0],200)
        self.assertEqual(self.request()[0],401)

    def test_new_subscription_does_not_backfill_and_only_failed_recipient_retries(self):
        original=self.publish()
        self.register()
        self.publish()
        self.assertEqual(fixture.FakeAPNs.requests,[])
        self.register(user="daily-czq",token="b"*64)
        fixture.FakeAPNs.responses["/3/device/"+"b"*64]=(503,"ServiceUnavailable")
        result=self.publish(simulation=True)
        self.assertEqual(result["delivery"],{"accepted":1,"pending":1,"invalid":0})
        fixture.FakeAPNs.responses={}
        self.assertEqual(deliver_pending()["accepted"],1)
        self.assertEqual(deliver_pending()["accepted"],0)
        self.assertEqual(len(fixture.FakeAPNs.requests),3)

    def test_expired_session_and_account_switch_stop_delivery_to_old_owner(self):
        self.register()
        self.register(user="daily-czq")
        with db() as conn:
            self.assertEqual(conn.execute("SELECT user_id FROM report_push_devices").fetchone()[0],"daily-czq")
            conn.execute("UPDATE sessions SET expires_at=0 WHERE user_id='daily-czq'")
        self.assertEqual(self.publish()["delivery"]["accepted"],0)

    def test_history_is_deduplicated_and_status_excludes_tokens(self):
        self.register()
        self.publish()
        self.publish(simulation=True)
        self.assertEqual(len(recent_history()["reports"]),1)
        status=publication_status()
        self.assertEqual(len(status["recipients"]),2)
        self.assertNotIn("a"*64,json.dumps(status))
        self.assertNotIn("token",json.dumps(status))
        self.assertNotIn("session",json.dumps(status))

    def test_history_preserves_all_source_urls_after_summary_truncation(self):
        self.publish(content="前文"*1500+"\n[来源](https://example.invalid/full/source)\nhttps://github.com/example/project")
        history=recent_history()["reports"]
        self.assertEqual(len(history[0]["content"]),2000)
        self.assertTrue(history[0]["content_truncated"])
        self.assertEqual(history[0]["source_urls"],["https://example.invalid/full/source","https://github.com/example/project"])

    def test_no_enabled_recipient_writes_nothing(self):
        self.assertEqual(self.flags(read=False,push=False)[0],200)
        self.assertEqual(self.flags(user="daily-czq",read=False,push=False)[0],200)
        result=self.publish()
        self.assertEqual(result["recipient_count"],0)
        self.assertIsNone(result["report_id"])
        self.assertEqual(recent_history()["reports"],[])
        self.assertEqual(fixture.FakeAPNs.requests,[])

    def test_sanitized_backup_removes_both_subscription_and_delivery_credentials(self):
        self.register()
        self.publish()
        from ai_platform.backup import create_sanitized_snapshot
        with tempfile.TemporaryDirectory(prefix="product-backup-") as temporary:
            target=os.path.join(temporary,"sanitized.db")
            create_sanitized_snapshot(self.path/"test.db",target)
            with sqlite3.connect(target) as conn:
                for table in ("report_push_devices","product_push_subscriptions","product_push_deliveries","auth_session_history"):
                    self.assertEqual(conn.execute("SELECT COUNT(*) FROM "+table).fetchone()[0],0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM product_reports").fetchone()[0],2)

    def test_trusted_cli_status_history_and_invalid_input_are_machine_readable(self):
        self.register()
        self.publish()
        with tempfile.TemporaryDirectory(prefix="product-cli-") as temporary:
            source=sqlite3.connect(self.path/"test.db")
            destination=sqlite3.connect(os.path.join(temporary,"ai-platform.db"))
            source.backup(destination)
            source.close()
            destination.close()
            environment={**os.environ,"AI_PLATFORM_DATA":temporary}
            script=str(fixture.Path(__file__).resolve().parent/"publish_product_report.py")
            for option in ("--status","--history"):
                result=subprocess.run([sys.executable,script,option],capture_output=True,env=environment,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr.decode())
                decoded=json.loads(result.stdout)
                self.assertTrue(decoded["ok"])
                self.assertNotIn("a"*64,result.stdout.decode())
            invalid=subprocess.run([sys.executable,script],input=b"{}",capture_output=True,env=environment,timeout=10)
            self.assertEqual(invalid.returncode,1)
            self.assertFalse(json.loads(invalid.stdout)["ok"])

    def test_read_only_validation_pagination_and_payload_size(self):
        self.register()
        result=self.publish(content="## 产品\n"+"\n".join("- "+"😀"*500 for _ in range(4)))
        rid=result["report_id"]
        self.assertLessEqual(fixture.FakeAPNs.payload_sizes[0],4096)
        for method in ("POST","PUT","PATCH","DELETE"):
            self.assertEqual(self.request(f"/{rid}",method,{"content":"tampered"})[0],405)
        self.assertEqual(self.request("/device","GET")[0],405)
        self.assertEqual(self.request("?before=oops")[0],400)
        for payload in ({"date":"2026-99-99","content":"x"},{"date":"2026-11-04","content":""},{"date":"2026-11-04","content":"x","user_id":"other"}):
            with self.assertRaises(ValueError):
                publish_report(payload)
        self.assertEqual(notification_preview(""),"今日产品推送已更新，点击查看详情")
        for offset in range(1,32):
            self.publish(day=(date.today()-timedelta(days=offset)).isoformat())
        first=self.request()[1]
        self.assertEqual(len(first["reports"]),30)
        self.assertEqual(len(self.request("?before="+str(first["next_before"]))[1]["reports"]),2)


if __name__ == "__main__":
    unittest.main()
