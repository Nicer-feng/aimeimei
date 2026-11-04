#!/usr/bin/env python3
"""Real loopback HTTP controller and TLS CONNECT fixtures; no paid/external APIs."""
import base64
import contextlib
import importlib.util
import io
from concurrent.futures import ThreadPoolExecutor
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import test_chat_stream as fixture
from app import AppHandler
from ai_platform.database import db, init_db
from ai_platform import openai_egress as e
from ai_platform.model_options import openai_reasoning_options, prepare_chat_payload, public_reasoning_options


class EgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="meimei-egress-test-")
        root = cls.root = Path(cls.temp.name)
        cls.patches = [patch.object(e, "CONFIG_PATH", root / "settings.json"),
                       patch.object(e, "CLIENT_PATH", root / "client.json"),
                       patch.object(e, "RUNTIME_PATH", root / "config.json")]
        for p in cls.patches:
            p.start()
        config = root / "cert.cnf"
        config.write_text("[req]\ndistinguished_name=dn\nx509_extensions=ext\nprompt=no\n[dn]\nCN=api.openai.com\n[ext]\nsubjectAltName=DNS:api.openai.com\nbasicConstraints=critical,CA:TRUE\n")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                        "-keyout", str(root / "key.pem"), "-out", str(root / "cert.pem"), "-config", str(config)],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(root / "cert.pem"), str(root / "key.pem"))
        cls.trust = ssl.create_default_context(cafile=str(root / "cert.pem"))
        cls.calls, cls.mode, cls.delay = [], "normal", 0
        cls.reload_fail = False

        class Origin(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                cls.calls.append(("origin", self.path, self.headers.get("Authorization")))
                if cls.delay:
                    time.sleep(cls.delay)
                status = 200 if self.headers.get("Authorization") else 401
                if cls.mode == "forbidden":
                    status = 403
                if cls.mode == "redirect":
                    self.send_response(302); self.send_header("Location", "https://leak.invalid/secret"); self.end_headers(); return
                body = json.dumps({"id": self.path.rsplit("/", 1)[-1]} if status == 200 else {"error": "private upstream body"}).encode()
                self.send_response(status); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                cls.calls.append(('completion', self.path, payload))
                forbidden = {'enable_thinking', 'thinking_budget', 'max_tokens', 'temperature', 'top_p', 'logprobs', 'top_logprobs'}
                if forbidden.intersection(payload) or payload.get('reasoning_effort') not in ('none', 'low', 'medium', 'high'):
                    self.send_error(400, 'incompatible fixture parameters'); return
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream' if payload.get('stream') else 'application/json')
                self.end_headers()
                if payload.get('stream'):
                    event = {'choices': [{'delta': {'content': '本地模拟脚本正文。'}, 'finish_reason': 'stop'}],
                             'usage': {'prompt_tokens': 3, 'completion_tokens': 5, 'total_tokens': 8}}
                    self.wfile.write(('data: ' + json.dumps(event, ensure_ascii=False) + '\n\ndata: [DONE]\n\n').encode())
                else:
                    content = json.dumps({'requirements': {}, 'intent': 'draft', 'full_manuscript': True, 'scope': '本地测试', 'enhanced_summary': '本地摘要'}, ensure_ascii=False)
                    self.wfile.write(json.dumps({'choices': [{'message': {'content': content}}],
                        'usage': {'prompt_tokens': 3, 'completion_tokens': 5, 'total_tokens': 8}}, ensure_ascii=False).encode())

        class Controller(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_CONNECT(self):
                cls.calls.append(("connect", self.path, self.headers.get("Proxy-Authorization")))
                if self.path != "api.openai.com:443":
                    self.send_error(403); return
                expected = "Basic " + base64.b64encode(b"user:fixture-password").decode()
                if self.headers.get("Proxy-Authorization") != expected:
                    self.send_error(407); return
                self.send_response(200); self.end_headers()
                tls = context.wrap_socket(self.connection, server_side=True)
                try:
                    Origin(tls, self.client_address, self.server)
                finally:
                    tls.close()

            def do_GET(self):
                if self.headers.get("Authorization") != "Bearer " + "x" * 40:
                    self.send_error(401); return
                self.send_response(200); self.end_headers()
                self.wfile.write(json.dumps({"all": ["REJECT", "test-node"], "now": "test-node"}).encode())

            def do_PUT(self):
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                cls.calls.append(("control", self.path, body))
                self.send_response(400 if cls.reload_fail and self.path.startswith("/configs") else 204); self.end_headers()

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Controller)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True); cls.worker.start()
        cls.client = {"proxy_url": "http://user:fixture-password@127.0.0.1:" + str(cls.server.server_port),
                      "controller_url": "http://127.0.0.1:" + str(cls.server.server_port), "controller_secret": "x" * 40,
                      "runtime_path": str(e.RUNTIME_PATH)}
        init_db({"family_password_hash": "fixture-only"})
        with db() as conn:
            conn.execute("INSERT INTO models(id,name,provider,base_url,api_key,model,input_price_per_million,output_price_per_million,created_at,updated_at) VALUES('official','test','OpenAI','https://api.openai.com/v1','sk-fixture-only','gpt-fixture',13.436,67.18,0,0)")

        class Handler(AppHandler):
            def log_message(self, *args):
                pass

            def current_user(self):
                role = self.headers.get("X-Fixture-Role")
                return {"id": "default", "role": role} if role else None

            def record_user_activity(self, user):
                pass

        cls.app = ThreadingHTTPServer(("127.0.0.1", 0), Handler); cls.app.secrets = {"admin_key": "fixture-only"}
        cls.app_thread = threading.Thread(target=cls.app.serve_forever, daemon=True); cls.app_thread.start()
        original = urllib.request.build_opener
        def trusted(*handlers):
            return original(*handlers, urllib.request.HTTPSHandler(context=cls.trust))
        cls.opener_patch = patch.object(urllib.request, "build_opener", trusted); cls.opener_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.opener_patch.stop()
        for server in (cls.server, cls.app):
            server.shutdown(); server.server_close()
        cls.worker.join(2); cls.app_thread.join(2)
        for p in reversed(cls.patches):
            p.stop()
        cls.temp.cleanup(); fixture.TEMP.cleanup()

    def setUp(self):
        type(self).calls.clear(); type(self).mode = "normal"; type(self).delay = 0; type(self).reload_fail = False
        e._cache.clear(); e._checks.clear(); e._active = 0
        self.cfg = {"enabled": True, "subscription_url": "https://subscription.example/token-fixture", "selected_node": "test-node"}
        e.write_config(e.CONFIG_PATH, self.cfg); e.write_config(e.CLIENT_PATH, self.client)
        e.write_config(e.RUNTIME_PATH, e.runtime_config(self.cfg, self.client), 0o640)
        self.model = {"id": "official", "model": "gpt-fixture", "api_key": "sk-fixture-only"}
        with db() as conn:
            conn.execute("UPDATE models SET model='gpt-fixture',supports_reasoning_control=0,supports_native_web_search=0 WHERE id='official'")

    def stream(self, name, mode='balanced', writing=False):
        cid = self.id().split('.')[-1] + name + mode
        with db() as conn:
            conn.execute("UPDATE models SET model=?,supports_reasoning_control=1 WHERE id='official'", (name,))
            conn.execute("INSERT INTO conversations(id,user_id,title,model_id,reasoning_mode,writing_mode,created_at,updated_at) VALUES (?,'default','fixture','official',?,?,0,0)", (cid, mode, int(writing)))
        conn = http.client.HTTPConnection('127.0.0.1', self.app.server_port, timeout=15)
        conn.request('POST', '/api/conversations/' + cid + '/messages',
            json.dumps({'content': '请根据材料写一段视频脚本。', 'web_search': False}), {'X-Fixture-Role': 'admin', 'Content-Type': 'application/json'})
        response = conn.getresponse(); body = response.read().decode(); status = response.status; conn.close()
        self.assertEqual(status, 200, body)
        self.assertIn('message_saved', body)
        self.assertIn('本地模拟脚本正文', body)
        return cid

    def test_sol_terra_modes_through_real_tls_and_main_chat(self):
        for name, fast in [('gpt-6.1-sol', 'low'), ('gpt-6.1-terra', 'none')]:
            for mode, effort in [('fast', fast), ('balanced', 'medium'), ('deep', 'high')]:
                self.calls.clear(); self.stream(name, mode)
                calls = [c[2] for c in self.calls if c[0] == 'completion']
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0]['reasoning_effort'], effort)
                self.assertTrue(calls[0]['stream_options']['include_usage'])

    def test_writing_planner_has_its_own_compatible_options(self):
        for name, effort in [('gpt-6.1-sol', 'low'), ('gpt-6.1-terra', 'none')]:
            self.calls.clear(); self.stream(name, 'deep', writing=True)
            calls = [c[2] for c in self.calls if c[0] == 'completion']
            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0]['reasoning_effort'], effort)
            self.assertEqual(calls[0]['max_completion_tokens'], 7000)
            self.assertEqual(calls[1]['reasoning_effort'], 'high')

    def test_summary_and_media_use_compatible_options(self):
        cid = 'summary-options'
        with db() as conn:
            conn.execute("UPDATE models SET model='gpt-6.1-sol',supports_reasoning_control=1 WHERE id='official'")
            conn.execute("INSERT INTO conversations(id,user_id,title,model_id,created_at,updated_at) VALUES (?,'default','fixture','official',0,0)", (cid,))
            conn.executemany("INSERT INTO messages(conversation_id,user_id,role,content,created_at) VALUES (?,'default',?,'历史材料',?)", [(cid, 'user' if i % 2 == 0 else 'assistant', i) for i in range(26)])
            model = dict(conn.execute("SELECT * FROM models WHERE id='official'").fetchone())
        AppHandler.run_context_summary_job('fixture-summary', cid, 'default')
        summary = [c[2] for c in self.calls if c[0] == 'completion']
        self.assertEqual(summary[0]['reasoning_effort'], 'low')
        self.assertEqual(summary[0]['max_completion_tokens'], 1800)
        with db() as conn:
            self.assertTrue(conn.execute("SELECT context_summary FROM conversations WHERE id=?", (cid,)).fetchone()[0])
        with patch('ai_platform.handlers.media.media_ai_source_context', return_value='本地转写材料'):
            result = fixture.Handler(cid).call_media_ai_model(model, {})
        self.assertEqual(result['enhanced_summary'], '本地摘要')
        payload = [c[2] for c in self.calls if c[0] == 'completion'][-1]
        self.assertNotIn('temperature', payload)
        self.assertEqual(payload['reasoning_effort'], 'medium')

    def test_provider_options_are_isolated_and_unknown_models_safe(self):
        row = {'base_url': 'https://api.openai.com/v1', 'model': 'gpt-6.1-sol', 'supports_reasoning_control': True}
        self.assertEqual(openai_reasoning_options(row, 'fast'), {'reasoning_effort': 'low'})
        self.assertEqual(openai_reasoning_options(row, 'deep', responses=True), {'reasoning': {'effort': 'high'}})
        payload = {'enable_thinking': False, 'temperature': .4, 'top_p': .8, 'max_tokens': 123, 'messages': []}
        clean = prepare_chat_payload(payload, row, 'fast')
        self.assertEqual(clean, {'reasoning_effort': 'low', 'max_completion_tokens': 123, 'messages': []})
        self.assertIn('enable_thinking', payload)
        row['model'] = 'unknown-future-model'
        self.assertFalse(public_reasoning_options(row)['supports_reasoning_control'])
        self.assertEqual(openai_reasoning_options(row, 'fast'), {})
        row['base_url'] = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
        self.assertIs(prepare_chat_payload(payload, row), payload)
        for native in (False, True):
            row.update(reasoning_mode='fast', model='qwen-fixture')
            expected = {'reasoning': {'effort': 'none'}} if native else {'enable_thinking': False}
            self.assertEqual(AppHandler.reasoning_request_options(row, native_search=native), expected)

    def test_unconfigured_models_do_not_take_over_default(self):
        with db() as conn:
            conn.execute("INSERT INTO models(id,name,provider,base_url,api_key,model,created_at,updated_at) VALUES('no-key','test','OpenAI','https://api.openai.com/v1','','gpt-6.1-sol',9999999999,9999999999)")
        try:
            code, data = self.req('/api/models')
            self.assertEqual(code, 200)
            self.assertEqual(data['models'][0]['id'], 'official')
            empty = next(m for m in data['models'] if m['id'] == 'no-key')
            self.assertEqual(empty['reasoning_mode_options']['fast']['effort'], 'low')
        finally:
            with db() as conn:
                conn.execute("DELETE FROM models WHERE id='no-key'")

    def test_writing_model_setup_prices_idempotence_and_key_preservation(self):
        path = Path(__file__).resolve().parents[1] / 'deploy/openai-egress/configure-writing-models.py'
        spec = importlib.util.spec_from_file_location('seed_models', path)
        seed = importlib.util.module_from_spec(spec); spec.loader.exec_module(seed)
        backup = self.root / 'model-backup'; backup.mkdir(mode=0o700)
        data_dir = Path(fixture.TEMP.name); (data_dir / 'admin.key').write_text('fixture-only')
        try:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                seed.apply(data_dir, backup, 'http://127.0.0.1:' + str(self.app.server_port))
            with db() as conn:
                rows = conn.execute("SELECT * FROM models WHERE model IN ('gpt-6.1-sol','gpt-6.1-terra')").fetchall()
                self.assertEqual(len(rows), 2)
                prices = {row['model']: (row['input_price_per_million'], row['output_price_per_million']) for row in rows}
                self.assertEqual(prices, {'gpt-6.1-sol': (13.436, 67.18), 'gpt-6.1-terra': (6.718, 33.59)})
                self.assertTrue(all(not row['api_key'] for row in rows))
                conn.execute("UPDATE models SET api_key='sk-seed-private-fixture' WHERE model='gpt-6.1-sol'")
            with contextlib.redirect_stdout(io.StringIO()) as output:
                seed.apply(data_dir, backup, 'http://127.0.0.1:' + str(self.app.server_port))
            self.assertNotIn('sk-seed-private-fixture', output.getvalue())
            with db() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM models WHERE model IN ('gpt-6.1-sol','gpt-6.1-terra')").fetchone()[0], 2)
                self.assertEqual(conn.execute("SELECT api_key FROM models WHERE model='gpt-6.1-sol'").fetchone()[0], 'sk-seed-private-fixture')
            self.assertFalse(any(call[0] == 'completion' for call in self.calls))
        finally:
            with db() as conn:
                conn.execute("DELETE FROM models WHERE model IN ('gpt-6.1-sol','gpt-6.1-terra')")

    def req(self, path, body=None, role="admin"):
        conn = http.client.HTTPConnection("127.0.0.1", self.app.server_port, timeout=15)
        headers = {"Content-Type": "application/json"}
        if role:
            headers["X-Fixture-Role"] = role
        conn.request("POST" if body is not None else "GET", path, json.dumps(body).encode() if body is not None else None, headers)
        response = conn.getresponse(); status = response.status; data = json.load(response); conn.close()
        return status, data

    def test_proxy_tls_connect_no_chat(self):
        self.assertEqual(e.probe()["status"], "reachable")
        self.assertEqual([c[1] for c in self.calls if c[0] == "origin"], ["/v1/models"])
        self.assertEqual(e._active, 0)

    def test_api_model_test_real_tls(self):
        self.assertEqual(e.probe(self.model)["status"], "reachable")
        self.assertEqual(self.calls[0][:2], ("connect", "api.openai.com:443"))
        self.assertEqual(self.calls[1], ("origin", "/v1/models/gpt-fixture", "Bearer sk-fixture-only"))

    def test_no_proxy_cannot_bypass_scoped_route(self):
        with patch.dict(os.environ, {"NO_PROXY": "*", "no_proxy": "*"}):
            self.assertEqual(e.probe(self.model)["status"], "reachable")
        self.assertEqual(self.calls[0][:2], ("connect", "api.openai.com:443"))

    def test_disabled_fail_closed_and_manual_test_allowed(self):
        e.configure({"enabled": False})
        with self.assertRaises(e.EgressError):
            e.open_model_request(urllib.request.Request("https://api.openai.com/v1/chat/completions"))
        self.assertFalse(self.calls)
        self.assertEqual(e.availability(self.model)["status"], "disabled")
        self.assertFalse(self.calls)
        self.assertEqual(e.probe(self.model)["status"], "reachable")

    def test_other_upstream_is_unchanged(self):
        url = "http://127.0.0.1:" + str(self.server.server_port) + "/proxies/OPENAI"
        with e.open_model_request(urllib.request.Request(url, headers={"Authorization": "Bearer " + "x" * 40})) as response:
            self.assertIn("test-node", response.read().decode())
        self.assertFalse(self.calls)

    def test_permission_error_redacted(self):
        type(self).mode = "forbidden"
        data = e.probe(self.model)
        self.assertEqual(data["code"], "http_403")
        self.assertNotIn("private", json.dumps(data)); self.assertNotIn("sk-fixture", json.dumps(data))

    def test_redirect_does_not_forward_credentials(self):
        type(self).mode = "redirect"
        self.assertEqual(e.probe(self.model)["status"], "unavailable")
        self.assertEqual(sum(c[0] == "connect" for c in self.calls), 1)

    def test_cached_singleflight_concurrent(self):
        type(self).delay = .15
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: e.availability(self.model), range(8)))
        self.assertTrue(all(r["status"] == "reachable" for r in results))
        e.availability(self.model)
        self.assertEqual(sum(c[0] == "origin" for c in self.calls), 1)
        self.assertEqual(e._active, 0)

    def test_missing_key_does_not_request(self):
        self.assertEqual(e.probe({"model": "gpt-fixture"})["code"], "missing_key")
        self.assertFalse(self.calls)

    def test_invalid_url_and_subscription(self):
        for url in ("http://api.openai.com/v1/models", "https://api.openai.com:bad/v1/models", "https://api.openai.com.evil/v1/models"):
            with self.assertRaises(e.EgressError):
                e.validate_openai_url(url)
        for url in ("http://example.com", "https://127.0.0.1/private", "https://169.254.169.254/latest"):
            with self.assertRaises(e.EgressError):
                e.validate_subscription(url)

    def test_public_config_never_exposes_credentials(self):
        self.assertEqual(os.stat(e.CONFIG_PATH).st_mode & 0o777, 0o600)
        raw = json.dumps(e.public_config())
        for secret in ("token-fixture", "fixture-password", "x" * 40):
            self.assertNotIn(secret, raw)
        runtime = e.runtime_config(self.cfg, self.client)
        self.assertEqual(runtime["proxy-providers"]["subscription"]["type"], "file")
        self.assertNotIn("url", runtime["proxy-providers"]["subscription"])
        self.assertFalse(runtime["tun"]["enable"])

    def test_node_update_blocked_during_requests(self):
        e._active = 1
        try:
            with self.assertRaises(e.EgressError):
                e.configure({"selected_node": "other"})
            self.assertEqual(e.read_config(), self.cfg)
        finally:
            e._active = 0

    def test_config_reload_rollback(self):
        provider = self.root / "subscription.yaml"; provider.write_bytes(b"original")
        before = e.RUNTIME_PATH.read_bytes()
        type(self).reload_fail = True
        with patch.object(e, "download_subscription", return_value=b"new fixture provider"):
            with self.assertRaises(e.EgressError):
                e.configure({}, reload_subscription=True)
        self.assertEqual(provider.read_bytes(), b"original")
        self.assertEqual(e.RUNTIME_PATH.read_bytes(), before)
        self.assertEqual(e.read_config(), self.cfg)

    def test_http_auth_and_config_validation(self):
        for path in ("/api/admin/openai-egress", "/api/models/official/availability"):
            self.assertEqual(self.req(path, role=None)[0], 401)
        self.assertEqual(self.req("/api/admin/openai-egress", role="family")[0], 401)
        self.assertEqual(self.req("/api/admin/openai-egress", body=[])[0], 400)
        self.assertEqual(self.req("/api/admin/openai-egress/test", body=[])[0], 400)
        self.assertEqual(self.req("/api/admin/openai-egress/test", body={"kind": "invalid"})[0], 400)

    def test_http_api_test_and_user_availability(self):
        status, data = self.req("/api/admin/openai-egress/test", {"kind": "model", "model_id": "official"})
        self.assertEqual((status, data["status"]), (200, "reachable"))
        status, data = self.req("/api/models/official/availability", role="family")
        self.assertEqual((status, data["status"]), (200, "reachable"))
        self.assertEqual(self.req("/api/models/missing/availability")[0], 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
