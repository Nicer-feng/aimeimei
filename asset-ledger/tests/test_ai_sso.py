import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import time
import unittest
from unittest.mock import patch

from ledger.data import connect, digest_token, initialize, reset_password
from ledger.edge import PublicSite
from ledger.http import LedgerServer


ADMIN = "a" * 43
FENG = "f" * 43
READER = "r" * 43
LEGACY = "l" * 43


class IdentityFixture(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.requests.append((self.path, self.headers.get("Cookie"), self.headers.get("Authorization")))
        status, payload = self.server.identities.get(self.headers.get("Cookie"), (401, {}))
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if status == 302:
            self.send_header("Location", "/should-not-follow")
        self.end_headers()
        self.wfile.write(body)


class SroomIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        cls.data_dir = Path(directory.name)
        initialize(cls.data_dir)
        with connect(cls.data_dir) as conn:
            reset_password(conn, "admin", "demo-local-password")
            conn.execute("INSERT INTO sessions VALUES (?, ?, ?)", (digest_token(LEGACY), "admin", int(time.time()) + 3600))
        conn.close()
        cls.identity = ThreadingHTTPServer(("127.0.0.1", 0), IdentityFixture)
        cls.start_server(cls.identity)
        cls.ledger = LedgerServer(0, cls.data_dir, PublicSite.parse("https://feng.asia/sroom/"), ai_sso=True)
        cls.start_server(cls.ledger)
        cls.local_ledger = LedgerServer(0, cls.data_dir)
        cls.start_server(cls.local_ledger)

    @classmethod
    def start_server(cls, server):
        Thread(target=server.serve_forever, daemon=True).start()
        cls.addClassCleanup(server.server_close)
        cls.addClassCleanup(server.shutdown)

    def setUp(self):
        self.identity.requests = []
        self.identity.identities = {
            "ap_session=" + ADMIN: (200, self.grant("admin", "admin")),
            "ap_session=" + FENG: (200, self.grant("feng", "admin")),
            "ap_session=" + READER: (200, self.grant("reader", "reader", 2)),
        }
        intercept = patch("ledger.identity.HTTPConnection", side_effect=self.identity_connection)
        intercept.start()
        self.addCleanup(intercept.stop)

    def identity_connection(self, host, port, *, timeout):
        self.assertEqual((host, port, timeout), ("127.0.0.1", 8000, 2))
        return http.client.HTTPConnection(host, self.identity.server_port, timeout=timeout)

    @staticmethod
    def grant(username, role, unit_id=None):
        return {"user_id": "fixture-" + username, "username": username, "role": role, "unit_id": unit_id}

    def request(self, path, token=None, *, headers=None, method="GET", data=None, local=False):
        server = self.local_ledger if local else self.ledger
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=4)
        request_headers = {} if local else {
            "Host": "feng.asia", "X-Forwarded-Proto": "https", "X-Ledger-Client-IP": "192.0.2.1",
        }
        if token:
            request_headers["Cookie"] = "ap_session=" + token
        request_headers.update(headers or {})
        if data is not None:
            request_headers["Content-Type"] = "application/json"
        try:
            connection.request(method, ("" if local else "/sroom") + path,
                               json.dumps(data) if data is not None else None, request_headers)
            with connection.getresponse() as response:
                return response.status, response.headers, response.read()
        finally:
            connection.close()

    def test_old_login_and_cookie_cannot_enter_managed_mode(self):
        status, headers, config = self.request("/api/auth-config")
        self.assertEqual((status, json.loads(config)), (200, {"mode": "ai"}))
        self.assertEqual(headers["Cache-Control"], "private, no-store")
        legacy = {"Cookie": "asset_ledger_session=" + LEGACY}
        self.assertEqual(self.request("/api/catalog", headers=legacy)[0], 401)
        self.assertEqual(self.request("/api/documents/1/file", headers=legacy)[0], 401)
        self.assertEqual(self.request("/api/login", method="POST", data={})[0], 404)
        self.assertEqual(self.request("/api/logout", method="POST", data={})[0], 404)
        self.assertEqual(self.identity.requests, [])

    def test_admin_and_feng_have_identical_catalog_and_write_permissions(self):
        catalogs = []
        for username, token in (("admin", ADMIN), ("feng", FENG)):
            status, _, payload = self.request("/api/me", token)
            self.assertEqual((status, json.loads(payload)),
                             (200, {"username": username, "role": "admin", "scope_name": "全部站点"}))
            status, _, payload = self.request("/api/catalog", token, headers={
                "Cookie": f"arbitrary=not-forwarded; ap_session={token}; asset_ledger_session={LEGACY}",
                "Authorization": "Bearer not-forwarded",
            })
            self.assertEqual(status, 200)
            self.assertEqual(self.identity.requests[-1], ("/api/sroom/access", "ap_session=" + token, None))
            catalogs.append(json.loads(payload))
            self.assertEqual(self.request("/api/devices", token, method="POST", data={})[0], 400)
        self.assertEqual(catalogs[0], catalogs[1])
        self.assertEqual({site["id"] for site in catalogs[0]["sites"]}, {1, 2})

    def test_existing_reader_rules_and_immediate_revocation_apply_to_pdf(self):
        self.assertEqual(self.request("/api/documents/6/file", READER)[0], 404)
        self.assertEqual(self.request("/api/devices", READER, method="POST", data={})[0], 403)
        headers = {"Range": "bytes=0-4"}
        status, _, body = self.request("/api/documents/1/file", READER, headers=headers)
        self.assertEqual((status, body), (206, b"%PDF-"))
        self.identity.identities["ap_session=" + READER] = (403, {})
        for path in ("/api/catalog", "/api/documents/1/file", "/api/documents/1/file?download=1"):
            status, _, error = self.request(path, READER, headers=headers)
            self.assertEqual(status, 403)
            self.assertEqual(json.loads(error)["code"], "sroom_identity")
        self.identity.identities.clear()
        self.assertEqual(self.request("/api/catalog", READER)[0], 401)

    def test_invalid_authorization_and_upstream_results_fail_closed(self):
        self.assertEqual(self.request("/api/me", headers={"Cookie": "ap_session=bad"})[0], 401)
        self.assertEqual(self.request("/api/me", headers={"Authorization": "Bearer " + ADMIN})[0], 401)
        self.assertEqual(self.identity.requests, [])
        invalid_responses = [(302, {}), (500, {}), (200, self.grant("admin", "unknown")),
                             (200, self.grant("reader", "reader", True)), (200, {"limit": "x" * 4096})]
        for response in invalid_responses:
            with self.subTest(status=response[0]):
                self.identity.identities["ap_session=" + ADMIN] = response
                called = len(self.identity.requests)
                self.assertEqual(self.request("/api/catalog", ADMIN)[0], 503)
                self.assertEqual(len(self.identity.requests), called + 1)
        with patch("ledger.identity.HTTPConnection", side_effect=OSError):
            self.assertEqual(self.request("/api/catalog", ADMIN)[0], 503)
        self.identity.identities["ap_session=" + READER] = (200, self.grant("reader", "reader", 999))
        self.assertEqual(self.request("/api/me", READER)[0], 403)

    def test_cross_origin_write_is_rejected_before_identity_check(self):
        self.assertEqual(self.request("/api/devices", ADMIN, method="POST", data={},
                                      headers={"Origin": "https://untrusted.example"})[0], 403)
        self.assertEqual(self.identity.requests, [])

    def test_local_password_mode_remains_available_for_development(self):
        status, _, config = self.request("/api/auth-config", local=True)
        self.assertEqual((status, json.loads(config)), (200, {"mode": "local"}))
        status, headers, _ = self.request("/api/login", local=True, method="POST", data={
            "username": "admin", "password": "demo-local-password",
        })
        self.assertEqual(status, 200)
        self.assertIn("asset_ledger_session=", headers["Set-Cookie"])
        self.assertEqual(self.identity.requests, [])
