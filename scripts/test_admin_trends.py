#!/usr/bin/env python3
"""Read-only trend aggregation checks against an isolated SQLite database."""
import os
import sqlite3
import sys
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_platform.handlers.admin import AdminHandlersMixin


class Handler(AdminHandlersMixin):
    def json(self, value):
        return value

    def error(self, status, message):
        return {"status": int(status), "error": message}


class AdminTrendTests(unittest.TestCase):
    def setUp(self):
        self.previous_tz = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Shanghai"
        time.tzset()
        self.addCleanup(self.restore_tz)
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript("""
          CREATE TABLE daily_usage(user_id TEXT, date TEXT, request_count INTEGER,
            input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER, estimated_cost REAL);
          CREATE TABLE messages(user_id TEXT, conversation_id TEXT, role TEXT, content TEXT,
            created_at INTEGER, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER,
            estimated_cost REAL, cost_model_id TEXT, actual_model TEXT);
          CREATE TABLE users(id TEXT, username TEXT, display_name TEXT);
          CREATE TABLE models(id TEXT, name TEXT, model TEXT, provider TEXT);
          CREATE TABLE conversations(id TEXT, user_id TEXT, model_id TEXT);
          INSERT INTO users VALUES ('u', 'test', '测试');
        """)

        @contextmanager
        def db():
            yield self.conn
        for target, replacement in [("db", db), ("today_text", lambda: "2024-03-01")]:
            mocked = patch("ai_platform.handlers.admin." + target, replacement)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.handler = Handler()

    def restore_tz(self):
        if self.previous_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.previous_tz
        time.tzset()

    def test_empty_and_invalid_range(self):
        self.handler.path = "/api/admin/token-stats/daily?range=30d"
        result = self.handler.handle_admin_daily_token_stats()
        self.assertEqual(len(result["days"]), 30)
        self.assertEqual(result["start_date"], "2024-02-01")
        self.assertEqual(result["summary"]["total_tokens"], 0)
        self.assertEqual(self.handler.handle_admin_usage_trend("365d")["status"], 400)

    def test_ledger_sums_users_and_zero_fills_leap_day(self):
        self.conn.executemany("INSERT INTO daily_usage VALUES (?,?,?,?,?,?,?)", [
            ('u', '2024-02-24', 1, 100, 10, 110, .02),
            ('v', '2024-02-24', 2, 200, 20, 220, .04),
            ('u', '2024-03-01', 1, 50, 5, 55, .001),
            ('u', '2024-02-23', 9, 999, 0, 999, 9),
            ('u', '2024-03-02', 9, 999, 0, 999, 9),
        ])
        result = self.handler.handle_admin_usage_trend("7d")
        self.assertEqual(len(result["days"]), 7)
        self.assertEqual(result["days"][0]["total_tokens"], 330)
        self.assertEqual(result["days"][-2]["date"], "2024-02-29")
        self.assertEqual(result["days"][-2]["request_count"], 0)
        self.assertEqual(result["summary"]["total_tokens"], 385)
        self.assertEqual(result["summary"]["request_count"], 4)
        self.assertAlmostEqual(result["summary"]["estimated_cost"], .061)

    def test_cost_series_matches_calendar_range_and_includes_auxiliary_calls(self):
        def timestamp(text):
            return int(time.mktime(time.strptime(text, "%Y-%m-%d %H:%M:%S")))
        fixtures = [
            ('assistant', '', '2024-02-23 23:59:59', 9),
            ('assistant', '', '2024-02-24 00:00:00', .02),
            ('user', '', '2024-02-25 12:00:00', 8),
            ('system', '写稿要求整理（辅助调用）', '2024-02-29 23:59:59', .03),
            ('system', '其他', '2024-03-01 12:00:00', 8),
            ('assistant', '', '2024-03-01 23:59:59', .04),
            ('assistant', '', '2024-03-02 00:00:00', 9),
        ]
        for role, content, created, cost in fixtures:
            self.conn.execute("INSERT INTO messages VALUES ('u','c',?,?,?,?,?,0,?,'','test')", (role, content, timestamp(created), 100, 20, cost))
        self.handler.path = '/api/admin/cost-stats?range=7d'
        result = self.handler.handle_admin_cost_stats()
        self.assertEqual(result['summary']['range_requests'], 3)
        self.assertEqual(result['trend']['summary']['total_tokens'], 360)
        self.assertAlmostEqual(result['trend']['summary']['estimated_cost'], .09)
        self.assertAlmostEqual(result['summary']['range_cost'], result['trend']['summary']['estimated_cost'])
        self.assertEqual(result['trend']['days'][0]['request_count'], 1)
        self.assertEqual(result['trend']['days'][-1]['request_count'], 1)
        self.handler.path = '/api/admin/cost-stats?range=all'
        result = self.handler.handle_admin_cost_stats()
        self.assertEqual(len(result['trend']['days']), 30)
        self.assertEqual(result['summary']['range_requests'], 5)


if __name__ == '__main__':
    unittest.main()
