"""临时目录内验证题库双口令、访问隔离、查询及会话生命周期。"""

import hashlib
import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ncd.auth import LOGIN_LIMIT, NcdAuth, configure_passwords
from ncd.handlers import NcdHandlersMixin


class Handler(NcdHandlersMixin, BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.ncd_dispatch()

    def do_HEAD(self):
        self.ncd_dispatch()

    def do_POST(self):
        self.ncd_dispatch()


class NcdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="ncd-test-")
        cls.previous = os.environ.get("NCD_DATA_DIR")
        os.environ["NCD_DATA_DIR"] = cls.temp.name
        configure_passwords(cls.temp.name, ["first-test-only", "second-test-only"])
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.request_number = 0

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        if cls.previous is None:
            os.environ.pop("NCD_DATA_DIR", None)
        else:
            os.environ["NCD_DATA_DIR"] = cls.previous
        cls.temp.cleanup()

    def request(self, path, method="GET", body=None, cookie=None, headers=None):
        type(self).request_number += 1
        all_headers = {"X-Forwarded-For": f"192.0.2.{type(self).request_number % 250 + 1}"}
        if body is not None:
            body = json.dumps(body).encode()
            all_headers["Content-Type"] = "application/json"
        if cookie:
            all_headers["Cookie"] = cookie
        all_headers.update(headers or {})
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            conn.request(method, path, body, all_headers)
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def login(self, password="first-test-only", headers=None):
        status, response_headers, body = self.request("/ncd/api/login", "POST", {"password": password}, headers=headers)
        self.assertEqual(status, 200, body)
        return response_headers["Set-Cookie"].split(";")[0]

    def test_both_passwords_and_private_page(self):
        for password in ("first-test-only", "second-test-only"):
            cookie = self.login(password)
            status, headers, body = self.request("/ncd/", cookie=cookie)
            self.assertEqual(status, 200)
            self.assertIn(b"search.js", body)
            self.assertNotIn(b"login.js", body)
            self.assertEqual(headers["Cache-Control"], "no-store")

    def test_anonymous_cannot_read_bank(self):
        status, _, body = self.request("/ncd/")
        self.assertEqual(status, 200)
        self.assertIn(b"login.js", body)
        for path in ("/ncd/api/search?q=ETC", "/ncd/api/search?q=ETC&page=1"):
            self.assertEqual(self.request(path)[0], 401)
            self.assertEqual(self.request(path, cookie="ap_session=other-site-token")[0], 401)
        for path in ("/ncd/questions.json", "/ncd/secrets.json", "/ncd/assets/../questions.json", "/ncd/assets/%2e%2e/secrets.json", "/ncd-data/secrets.json"):
            self.assertEqual(self.request(path)[0], 404)

    def test_wrong_password_and_input_types(self):
        self.assertEqual(self.request("/ncd/api/login", "POST", {"password": "wrong-password"})[0], 401)
        for password in (12345678, None, [], "", "a" * 257):
            self.assertEqual(self.request("/ncd/api/login", "POST", {"password": password})[0], 400)

    def test_source_and_option_content(self):
        cookie = self.login()
        status, _, body = self.request("/ncd/api/search?" + urlencode({"q": "二类客车核定载人数"}), cookie=cookie)
        result = json.loads(body)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(result["total"], 1)
        first = result["items"][0]
        self.assertEqual(first["answer"], ["B"])
        self.assertEqual(first["answer_text"], ["10至19人"])
        self.assertTrue(any(s["sheet"] == "2026单选" and s["row"] == 3 for s in first["sources"]))
        self.assertNotIn("2025", json.dumps(first["sources"], ensure_ascii=False))

    def test_query_validation_and_empty(self):
        cookie = self.login()
        for query in ({"q": "a" * 1001}, {"q": "ETC", "page": 0}, {"page": "bad"}, {"page": 10001}):
            self.assertEqual(self.request("/ncd/api/search?" + urlencode(query), cookie=cookie)[0], 400)
        status, _, body = self.request("/ncd/api/search?q=", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["items"], [])

    def test_cookie_flags_and_cross_origin(self):
        status, headers, _ = self.request("/ncd/api/login", "POST", {"password": "first-test-only"}, headers={"Host": "feng.asia", "Origin": "https://feng.asia"})
        self.assertEqual(status, 200)
        for flag in ("Path=/ncd/", "Max-Age=43200", "HttpOnly", "SameSite=Lax", "Secure"):
            self.assertIn(flag, headers["Set-Cookie"])
        self.assertEqual(self.request("/ncd/api/login", "POST", {"password": "first-test-only"}, headers={"Origin": "https://example.invalid"})[0], 403)
        self.assertEqual(self.request("/ncd/api/login", "POST", {"password": "first-test-only"}, headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_expiry_and_logout(self):
        cookie = self.login()
        self.assertEqual(self.request("/ncd/api/logout", "POST", {}, cookie=cookie)[0], 200)
        self.assertEqual(self.request("/ncd/api/search?q=ETC", cookie=cookie)[0], 401)
        cookie = self.login()
        token = cookie.split("=", 1)[1]
        with self.server.ncd_auth.connect() as conn:
            conn.execute("UPDATE sessions SET expires_at=0 WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
        self.assertEqual(self.request("/ncd/api/search?q=ETC", cookie=cookie)[0], 401)

    def test_rate_limit(self):
        headers = {"X-Forwarded-For": "198.51.100.1"}
        for _ in range(LOGIN_LIMIT):
            self.assertEqual(self.request("/ncd/api/login", "POST", {"password": "incorrect"}, headers=headers)[0], 401)
        status, response_headers, _ = self.request("/ncd/api/login", "POST", {"password": "incorrect"}, headers=headers)
        self.assertEqual(status, 429)
        self.assertIn("Retry-After", response_headers)

    def test_rotation_revokes_old_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            configure_passwords(directory, ["old-first", "old-second"])
            auth = NcdAuth(directory)
            token = auth.login("old-first", "127.0.0.1")
            self.assertTrue(auth.authenticated(token))
            configure_passwords(directory, ["new-first", "new-second"])
            self.assertFalse(auth.authenticated(token))
            self.assertIsNone(auth.login("old-first", "127.0.0.1"))
            self.assertIsNotNone(auth.login("new-second", "127.0.0.1"))

    def test_invalid_configuration_has_controlled_error(self):
        with tempfile.TemporaryDirectory() as directory:
            auth = NcdAuth(directory)
            for payload in ("[]", "null"):
                auth.config_path.write_text(payload)
                with self.assertRaises(ValueError):
                    auth.credentials()

    def test_deep_json_is_rejected(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        try:
            raw = '{"password":' + '[' * 1100 + '0' + ']' * 1100 + '}'
            conn.request("POST", "/ncd/api/login", raw.encode(), {"Content-Type": "application/json"})
            response = conn.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
        finally:
            conn.close()

    def test_redirect_head_and_public_assets(self):
        status, headers, _ = self.request("/ncd")
        self.assertEqual((status, headers["Location"]), (302, "/ncd/"))
        for path in ("/ncd/", "/ncd/assets/ncd.css", "/ncd/assets/login.js", "/ncd/assets/search.js"):
            status, headers, body = self.request(path, "HEAD")
            self.assertEqual(status, 200)
            self.assertEqual(body, b"")
            self.assertGreater(int(headers["Content-Length"]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
