"""题库页面与接口，所有题目数据只从已登录接口返回。"""

import ipaddress
import json
import os
import sqlite3
import threading
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .auth import LOGIN_WINDOW, SESSION_TTL, LoginLimited, NcdAuth

WEB_DIR = Path(__file__).resolve().parent / "web"
COOKIE_NAME = "ncd_session"
_INITIALIZE_LOCK = threading.Lock()
ASSETS = {"ncd.css": "text/css; charset=utf-8", "login.js": "text/javascript; charset=utf-8", "search.js": "text/javascript; charset=utf-8"}


class NcdHandlersMixin:
    def ncd_auth(self):
        with _INITIALIZE_LOCK:
            if not hasattr(self.server, "ncd_auth"):
                path = os.environ.get("NCD_DATA_DIR") or str(Path(os.environ.get("AI_PLATFORM_DATA", "/opt/ai-platform")) / "ncd-data")
                self.server.ncd_auth = NcdAuth(path)
        return self.server.ncd_auth

    def ncd_bank(self):
        with _INITIALIZE_LOCK:
            if not hasattr(self.server, "ncd_bank"):
                from .bank import QuestionBank
                self.server.ncd_bank = QuestionBank()
        return self.server.ncd_bank

    def ncd_token(self):
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return cookie[COOKIE_NAME].value if COOKIE_NAME in cookie else ""
        except CookieError:
            return ""

    def ncd_authed(self):
        token = self.ncd_token()
        return bool(token) and self.ncd_auth().authenticated(token)

    def ncd_peer_ip(self):
        peer = self.client_address[0]
        try:
            if ipaddress.ip_address(peer).is_loopback:
                forwarded = self.headers.get("X-Forwarded-For", "").split(",")[-1].strip()
                if forwarded:
                    return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
        return peer

    def ncd_cookie(self, token, max_age):
        # 仅本机 HTTP 预览允许非 Secure，线上域名始终设置 Secure。
        host = urlparse("//" + self.headers.get("Host", "")).hostname
        local_http = host in {"localhost", "127.0.0.1", "::1"} and self.headers.get("X-Forwarded-Proto", "http") == "http"
        try:
            local_http = local_http and ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            local_http = False
        secure = "" if local_http else "; Secure"
        return f"{COOKIE_NAME}={token}; Path=/ncd/; Max-Age={max_age}; HttpOnly; SameSite=Lax{secure}"

    def ncd_reply(self, body, status=200, content_type="application/json; charset=utf-8", headers=None):
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            data = body.encode()
        else:
            data = body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Robots-Tag", "noindex, nofollow, noarchive")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if not getattr(self, "_head_only", False) and self.command != "HEAD":
            self.wfile.write(data)

    def ncd_error(self, status, message, headers=None):
        return self.ncd_reply({"error": message}, status, headers=headers)

    def ncd_same_origin(self):
        if self.headers.get("Sec-Fetch-Site", "") == "cross-site":
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urlparse(origin)
            return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == self.headers.get("Host", "").lower()
        return True

    def ncd_read_json(self):
        if self.headers.get("Transfer-Encoding"):
            raise ValueError("请求格式不正确")
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            raise ValueError("请求需要使用 JSON")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("请求长度不正确") from None
        if not 0 < length <= 4096:
            raise ValueError("请求长度不正确")
        self.connection.settimeout(10)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeError, TimeoutError, RecursionError):
            raise ValueError("请求内容不正确") from None
        if not isinstance(data, dict):
            raise ValueError("请求内容不正确")
        return data

    def ncd_dispatch(self):
        try:
            return self._ncd_dispatch()
        except LoginLimited:
            return self.ncd_error(429, "尝试次数较多，请稍后再试", {"Retry-After": str(LOGIN_WINDOW)})
        except (OSError, sqlite3.Error, ValueError):
            # 不将配置路径、密钥内容或数据库异常返回浏览器。
            return self.ncd_error(503, "暂时无法查询，请稍后再试")

    def _ncd_dispatch(self):
        path = urlparse(self.path).path
        if self.command in {"GET", "HEAD"}:
            if path == "/ncd":
                return self.ncd_reply(b"", 302, headers={"Location": "/ncd/"})
            if path == "/ncd/":
                page = "index.html" if self.ncd_authed() else "login.html"
                return self.ncd_reply((WEB_DIR / page).read_bytes(), content_type="text/html; charset=utf-8")
            if path.startswith("/ncd/assets/"):
                name = path.removeprefix("/ncd/assets/")
                if name in ASSETS:
                    return self.ncd_reply((WEB_DIR / name).read_bytes(), content_type=ASSETS[name])
            if path == "/ncd/api/search":
                if not self.ncd_authed():
                    return self.ncd_error(401, "请先输入访问密码")
                try:
                    params = parse_qs(urlparse(self.path).query, max_num_fields=10)
                    query = (params.get("q") or [""])[0].strip()
                    page = int((params.get("page") or ["1"])[0])
                    if len(query) > 1000 or not 1 <= page <= 10000:
                        raise ValueError()
                except ValueError:
                    return self.ncd_error(400, "搜索内容或页码不正确")
                return self.ncd_reply(self.ncd_bank().search(query, page=page, page_size=20))
            return self.ncd_error(404, "未找到页面")
        if self.command == "POST":
            if path not in {"/ncd/api/login", "/ncd/api/logout"}:
                return self.ncd_error(404, "未找到页面")
            if not self.ncd_same_origin():
                return self.ncd_error(403, "请从当前页面操作")
            if path == "/ncd/api/logout":
                token = self.ncd_token()
                if token:
                    self.ncd_auth().logout(token)
                return self.ncd_reply({"ok": True}, headers={"Set-Cookie": self.ncd_cookie("", 0)})
            try:
                body = self.ncd_read_json()
            except ValueError as exc:
                return self.ncd_error(400, str(exc))
            password = body.get("password")
            if not isinstance(password, str) or not 1 <= len(password) <= 256:
                return self.ncd_error(400, "请输入访问密码")
            token = self.ncd_auth().login(password, self.ncd_peer_ip())
            if token is None:
                return self.ncd_error(401, "密码不正确")
            return self.ncd_reply({"ok": True}, headers={"Set-Cookie": self.ncd_cookie(token, SESSION_TTL)})
        return self.ncd_error(405, "不支持的请求方式")
