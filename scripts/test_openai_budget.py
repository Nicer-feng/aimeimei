#!/usr/bin/env python3
"""临时数据库、回环 HTTP 和假传输；不请求真实模型、不产生费用。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import io
import json
import os
import threading
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import test_chat_stream as fixture
from app import AppHandler
from ai_platform.database import db, init_db
from ai_platform import openai_budget as b, openai_egress as e


def request(stream=True, model='budget-fixture', **options):
    payload = {'model': model, 'messages': [{'role': 'user', 'content': '测试内容不应写入账本'}], 'stream': stream, **options}
    return urllib.request.Request('https://api.openai.com/v1/chat/completions', data=json.dumps(payload).encode(), method='POST')


class BudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db({'family_password_hash': 'fixture-only'})
        with db() as conn:
            conn.execute("INSERT INTO models(id,name,provider,base_url,api_key,model,input_price_per_million,output_price_per_million,created_at,updated_at) VALUES('budget','预算测试','OpenAI','https://api.openai.com/v1','sk-fixture','budget-fixture',13.436,67.18,0,0)")
            conn.execute("INSERT INTO models(id,name,provider,base_url,api_key,model,input_price_per_million,output_price_per_million,created_at,updated_at) VALUES('other','其它模型','Qwen','https://example.invalid/v1','sk-fixture','other-fixture',13.436,67.18,0,0)")
        class Handler(AppHandler):
            def log_message(self, *args):
                pass
            def current_user(self):
                role = self.headers.get('X-Fixture-Role')
                return {'id': 'default', 'role': role} if role else None
            def record_user_activity(self, user):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.server.secrets = {'admin_key': 'fixture'}
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(2)
        fixture.TEMP.cleanup()

    def setUp(self):
        with db() as conn:
            conn.execute('DELETE FROM openai_budget_events')
            conn.execute("UPDATE openai_budget_settings SET enabled=1,limit_micro=50000000,cny_per_usd='6.718'")
            conn.execute("UPDATE models SET input_price_per_million=13.436,output_price_per_million=67.18,cost_enabled=1,enabled=1 WHERE id='budget'")
        e._active = 0

    def http(self, role=None, data=None):
        req = urllib.request.Request('http://127.0.0.1:%s/api/admin/openai-budget' % self.server.server_port,
            data=json.dumps(data).encode() if data is not None else None,
            headers={'X-Fixture-Role': role} if role else {}, method='POST' if data is not None else 'GET')
        try:
            with urllib.request.urlopen(req) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as response:
            return response.code, json.load(response)

    def response(self, body, stream=False, **options):
        return b.BudgetResponse(io.BytesIO(body), b.begin(request(stream=stream, **options)))

    def charged(self, pt=1000, ct=1000):
        ticket = b.begin(request())
        b.settle(ticket, (pt, ct))
        return ticket

    def config(self, limit=50, enabled=True, rate=6.718):
        return b.configure({'enabled': enabled, 'limit_usd': limit, 'cny_per_usd': rate})

    def test_defaults(self):
        s = b.summary()
        self.assertEqual((s['enabled'], s['limit_usd'], s['timezone'], s['spent_usd']), (True, 50, 'Asia/Shanghai', 0))

    def test_actual_json_usage(self):
        body = json.dumps({'usage': {'prompt_tokens': 1000, 'completion_tokens': 2000}}).encode()
        response = self.response(body)
        self.assertEqual(response.read(), body)
        response.close(); response.close()
        self.assertEqual((b.summary()['spent_usd'], b.summary()['reserved_usd'], b.summary()['request_count']), (.022, 0, 1))

    def test_split_utf8_sse_and_max_usage_not_double_counted(self):
        event = {'choices': [{'delta': {'content': '中文🚀'}}], 'usage': {'prompt_tokens': 1000, 'completion_tokens': 2000}}
        body = ('data: ' + json.dumps(event, ensure_ascii=False) + '\r\n\r\n') * 2 + 'data: [DONE]\n\n'
        response = self.response(body.encode(), stream=True)
        copied = b''
        while True:
            chunk = response.read1(3)
            if not chunk: break
            copied += chunk
        response.close()
        self.assertEqual(copied, body.encode())
        self.assertEqual(b.summary()['spent_usd'], .022)

    def test_responses_usage_and_cache_conservative(self):
        response = self.response(b'data: {"type":"response.completed","response":{"usage":{"input_tokens":1000,"output_tokens":2000,"input_tokens_details":{"cached_tokens":999}}}}', stream=True)
        response.read(); response.close()
        self.assertEqual(b.summary()['spent_usd'], .022)

    def test_missing_usage_is_not_free(self):
        response = self.response(b'{"choices":[{"message":{"content":"sk-do-not-record"}}]}')
        response.read(); response.close()
        s = b.summary()
        self.assertGreater(s['spent_usd'], 0)
        self.assertEqual(s['uncertain_requests'], 1)
        with db() as conn:
            self.assertNotIn('sk-do-not-record', str([dict(r) for r in conn.execute('SELECT * FROM openai_budget_events')]))

    def test_zero_usage_is_zero(self):
        response = self.response(b'{"usage":{"prompt_tokens":0,"completion_tokens":0}}')
        response.read(); response.close()
        self.assertEqual(b.summary()['spent_usd'], 0)

    def test_early_close_and_partial_json_keep_reservation(self):
        response = self.response(b'{"usage":{"prompt_tokens":5000000')
        response.read(5); response.close()
        self.assertEqual(b.summary()['uncertain_requests'], 1)

    def test_all_accounts_share_gate_and_model_switch_is_untouched(self):
        self.charged(1000000, 4800000)
        self.assertEqual(b.summary()['spent_usd'], 50)
        with self.assertRaises(b.BudgetError): b.begin(request())
        with db() as conn:
            self.assertEqual(conn.execute("SELECT enabled FROM models WHERE id='budget'").fetchone()[0], 1)

    def test_inflight_can_finish_over_budget(self):
        self.config(.1)
        ticket = b.begin(request())
        b.settle(ticket, (1000, 20000))
        self.assertEqual(b.summary()['spent_usd'], .202)
        with self.assertRaises(b.BudgetError): b.check()

    def test_concurrent_reservations_are_atomic(self):
        self.config(.1)
        def attempt(_):
            try: return b.begin(request())
            except b.BudgetError: return None
        with ThreadPoolExecutor(max_workers=12) as pool:
            accepted = [t for t in pool.map(attempt, range(24)) if t]
        self.assertEqual(len(accepted), 2)
        self.assertAlmostEqual(b.summary()['reserved_usd'], .1)
        b.settle(accepted[0], (1, 1))
        self.assertIsNotNone(b.begin(request()))

    def test_lowering_and_raising_limit_does_not_reset_spend(self):
        self.charged()
        self.config(.01)
        self.assertTrue(b.summary()['exhausted'])
        self.config(100)
        b.check()
        self.assertEqual(b.summary()['spent_usd'], .012)

    def test_disable_limit_still_accounts(self):
        self.config(.01, enabled=False)
        self.charged(); self.charged()
        b.check()
        self.assertEqual(b.summary()['spent_usd'], .024)

    def test_cost_statistics_switch_cannot_bypass_budget(self):
        with db() as conn: conn.execute("UPDATE models SET cost_enabled=0 WHERE id='budget'")
        self.charged()
        self.assertEqual(b.summary()['spent_usd'], .012)

    def test_missing_price_fails_closed(self):
        with db() as conn: conn.execute("UPDATE models SET input_price_per_million=0,output_price_per_million=0 WHERE id='budget'")
        with self.assertRaises(b.BudgetError) as error: b.begin(request())
        self.assertEqual(error.exception.code, 'budget_missing_price')

    def test_disabled_protection_does_not_block_unpriced_models(self):
        self.config(enabled=False)
        with db() as conn: conn.execute("UPDATE models SET input_price_per_million=0,output_price_per_million=0 WHERE id='budget'")
        self.charged()
        self.assertEqual(b.summary()['unpriced_requests'], 1)
        self.assertEqual(b.summary()['spent_usd'], 0)

    def test_new_exchange_rate_only_affects_new_requests(self):
        ticket = b.begin(request())
        self.config(rate=13.436)
        b.settle(ticket, (1000, 1000))
        self.charged()
        self.assertEqual(b.summary()['spent_usd'], .018)

    def test_beijing_month_rollover_and_inflight_assignment(self):
        nov = datetime(2026, 11, 30, 15, 59, 59, tzinfo=timezone.utc).timestamp()
        with patch.object(b.time, 'time', return_value=nov):
            self.charged(1000000, 4800000)
            self.config(60)
            ticket = b.begin(request())
            self.assertEqual(b.summary()['period'], '2026-11')
        with patch.object(b.time, 'time', return_value=nov + 1):
            b.settle(ticket, (1000, 1000))
            self.assertEqual((b.summary()['period'], b.summary()['spent_usd']), ('2026-12', 0))
            b.check()
        with patch.object(b.time, 'time', return_value=nov): self.assertEqual(b.summary()['spent_usd'], 50.012)

    def test_rejected_request_releases_reservation(self):
        ticket = b.begin(request())
        b.settle(ticket, rejected=True); b.settle(ticket, (1000000, 1000000))
        self.assertEqual((b.summary()['spent_usd'], b.summary()['reserved_usd']), (0, 0))

    def test_unknown_network_result_conservatively_accounted(self):
        ticket = b.begin(request())
        b.settle(ticket)
        self.assertEqual(b.summary()['uncertain_requests'], 1)

    def test_only_billable_post_is_tracked(self):
        self.assertIsNone(b.begin(urllib.request.Request('https://api.openai.com/v1/models')))
        self.assertEqual(b.summary()['request_count'], 0)

    def test_non_openai_transport_is_unaffected(self):
        self.config(.01); self.charged()
        req = urllib.request.Request('https://example.invalid/v1/chat/completions', data=b'{}')
        with patch('urllib.request.urlopen', return_value='other-provider') as mocked:
            self.assertEqual(e.open_model_request(req), 'other-provider')
            mocked.assert_called_once()

    def test_transport_gate_runs_before_network(self):
        self.charged(1000000, 4800000)
        with patch.object(e, 'read_config', return_value={'enabled': True, 'subscription_url': 'fixture', 'selected_node': 'fixture'}), \
             patch.object(e, 'read_client', return_value={'proxy_url': 'http://127.0.0.1:1'}), \
             patch('urllib.request.build_opener') as network:
            with self.assertRaises(b.BudgetError): e.open_model_request(request())
            network.assert_not_called()
        self.assertEqual(e._active, 0)

    def test_admin_http_permissions_and_bad_values(self):
        self.assertEqual(self.http()[0], 401)
        self.assertEqual(self.http('member')[0], 401)
        self.assertEqual(self.http('admin')[1]['budget']['limit_usd'], 50)
        for bad in (float('nan'), float('inf'), -1, 0, 'bad'):
            self.assertEqual(self.http('admin', {'enabled': True, 'limit_usd': bad, 'cny_per_usd': 6.718})[0], 400)
        self.assertEqual(self.http('member', {'enabled': False, 'limit_usd': 99, 'cny_per_usd': 6.718})[0], 401)
        code, data = self.http('admin', {'enabled': True, 'limit_usd': 75, 'cny_per_usd': 6.718})
        self.assertEqual((code, data['budget']['limit_usd']), (200, 75))

    def test_history_seed_is_once_and_survives_message_deletion(self):
        with db() as conn:
            conn.execute("INSERT OR IGNORE INTO conversations(id,user_id,title,model_id,created_at,updated_at) VALUES('legacy-budget','default','test','budget',0,0)")
            ts = int(b.time.time())
            ids = []
            for role in ('assistant', 'system'):
                ids.append(conn.execute("""INSERT INTO messages(user_id,conversation_id,role,content,prompt_tokens,completion_tokens,cost_model_id,cost_input_price,cost_output_price,created_at)
                    VALUES('default','legacy-budget',?,'test',1000,1000,'budget',13.436,67.18,?)""", (role, ts)).lastrowid)
            conn.execute('DELETE FROM openai_budget_settings')
            b.init_tables(conn); b.init_tables(conn)
            conn.execute('DELETE FROM messages WHERE id IN (?,?)', ids)
        self.assertEqual((b.summary()['spent_usd'], b.summary()['request_count']), (.024, 2))

    def test_reinitialization_does_not_recover_live_owner(self):
        ticket = b.begin(request())
        with db() as conn: b.init_tables(conn)
        self.assertGreater(b.summary()['reserved_usd'], 0)
        self.assertEqual(b.summary()['uncertain_requests'], 0)
        b.settle(ticket, rejected=True)

    def test_chat_preflight_rejects_without_saving_user_message(self):
        self.charged(1000000, 4800000)
        with db() as conn:
            conn.execute("INSERT OR IGNORE INTO conversations(id,user_id,title,model_id,created_at,updated_at) VALUES('budget-preflight','default','test','budget',0,0)")
        handler = fixture.Handler('budget-preflight')
        with patch('urllib.request.build_opener') as network:
            handler.handle_send_message()
            network.assert_not_called()
        self.assertEqual(handler.status, 429)
        self.assertIn('本月 OpenAI 额度已用完', handler.result['error'])
        with db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM messages WHERE conversation_id='budget-preflight'").fetchone()[0], 0)

    def test_dead_owner_is_recovered_without_free_usage(self):
        b.begin(request())
        with db() as conn:
            conn.execute("UPDATE openai_budget_events SET owner_pid=2147483647")
            b.init_tables(conn)
        self.assertEqual(b.summary()['uncertain_requests'], 1)
        self.assertGreater(b.summary()['spent_usd'], 0)


if __name__ == '__main__': unittest.main(verbosity=2)
