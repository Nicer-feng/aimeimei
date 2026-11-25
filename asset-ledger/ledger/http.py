"""仅监听本机的 HTTP 服务。"""

from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import sqlite3
import sys
from urllib.parse import quote, urlsplit

from .data import (
    ApiError, PROJECT_ROOT, SESSION_SECONDS, catalog, database, document_file,
    invalid, log_in, log_out, profile, save_device, save_document, save_project,
    save_system, session_user, string,
)


STATIC_DIR = PROJECT_ROOT / "static"
COOKIE = "asset_ledger_session"
LOCAL_HOST = re.compile(r"(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]{1,5})?", re.I)
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
FILE_ROUTE = re.compile(r"/api/documents/([1-9][0-9]{0,9})/file")
EDIT_ROUTE = re.compile(r"/api/(devices|systems|projects)/([1-9][0-9]{0,9})")
ASSET_ROUTE = re.compile(r"/static/([a-zA-Z0-9_-][a-zA-Z0-9._-]*(?:/[a-zA-Z0-9_-][a-zA-Z0-9._-]*)*)")
BYTE_RANGE = re.compile(r"bytes=([0-9]{0,10})-([0-9]{0,10})")
RESOURCE_WRITERS = {"devices": save_device, "systems": save_system, "projects": save_project}
WRITE_LIMIT = 1024 * 1024
UPLOAD_LIMIT = 12 * 1024 * 1024
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}


class LedgerServer(ThreadingHTTPServer):
    def __init__(self, port, data_dir):
        self.data_dir = data_dir
        super().__init__(("127.0.0.1", port), LedgerHandler)


class LedgerHandler(BaseHTTPRequestHandler):
    server_version = "AssetLedger"
    sys_version = ""

    def setup(self):
        self.request.settimeout(20)
        super().setup()

    def log_request(self, code="-", size="-"):
        # 请求路径、查询参数、Cookie 和录入内容均不写入日志。
        return

    def do_GET(self):
        self.handle_request()

    def do_HEAD(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def do_PATCH(self):
        self.handle_request()

    def handle_request(self):
        try:
            self.check_host()
            target = urlsplit(self.path)
            if target.scheme or target.netloc or target.fragment:
                raise invalid("请求地址格式不正确。")
            if self.command in ("GET", "HEAD") and not target.path.startswith("/api/"):
                self.static(target.path)
            elif target.path == "/api/health" and self.command in ("GET", "HEAD"):
                self.json_response(200, {"status": "ok"})
            else:
                with database(self.server.data_dir) as conn:
                    self.api(conn, target.path, target.query)
        except ApiError as error:
            self.json_response(error.status, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except (sqlite3.Error, OSError, ValueError) as error:
            print(f"台账服务请求失败（{type(error).__name__}）。", file=sys.stderr)
            self.json_response(500, {"error": "服务暂时无法完成请求。"})

    def check_host(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or not LOCAL_HOST.fullmatch(hosts[0]):
            raise ApiError(403, "请通过本地地址访问台账。")

    def check_origin(self):
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or (origins and origins[0].lower() != "http://" + self.headers["Host"].lower()):
            raise ApiError(403, "请求来源与台账访问地址不一致。")
        if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            raise ApiError(403, "请在台账页面内提交请求。")

    def session_token(self):
        try:
            cookies = SimpleCookie(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        token = cookies.get(COOKIE)
        return token.value if token and TOKEN.fullmatch(token.value) else None

    def payload(self, limit=WRITE_LIMIT):
        if self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/json":
            raise ApiError(415, "请提交 JSON 请求。")
        lengths = self.headers.get_all("Content-Length", [])
        if len(lengths) != 1 or not re.fullmatch(r"[0-9]{1,9}", lengths[0]):
            raise invalid("请求长度无效。")
        length = int(lengths[0])
        if length > limit:
            raise ApiError(413, "提交内容超出大小限制。")
        raw = self.rfile.read(length)
        if len(raw) != length:
            raise invalid("请求传输不完整。")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (ValueError, RecursionError):
            raise invalid("请求 JSON 格式不正确。") from None
        if not isinstance(value, dict):
            raise invalid("请求内容应为 JSON 对象。")
        return value

    def api(self, conn, path, query):
        writing = self.command in ("POST", "PATCH")
        if writing:
            self.check_origin()
        token = self.session_token()
        if self.command == "POST" and path == "/api/login":
            payload = self.payload(4096)
            user, new_token = log_in(
                conn,
                string(payload, "username", "账号", 100, required=True),
                string(payload, "password", "密码", 256, required=True, trim=False),
            )
            log_out(conn, token)
            cookie = f"{COOKIE}={new_token}; Path=/; Max-Age={SESSION_SECONDS}; HttpOnly; SameSite=Strict"
            self.json_response(200, profile(conn, user), {"Set-Cookie": cookie})
            return

        if not writing:
            # 授权范围与返回内容使用同一个读取快照。
            conn.execute("BEGIN")
        user = session_user(conn, token)
        if user is None:
            raise ApiError(401, "请登录台账。")
        if not writing:
            if path == "/api/me":
                self.json_response(200, profile(conn, user))
            elif path == "/api/catalog":
                self.json_response(200, catalog(conn, user))
            else:
                match = FILE_ROUTE.fullmatch(path)
                if not match:
                    raise ApiError(404, "页面或记录不存在。")
                filename, contents = document_file(conn, user, int(match[1]))
                conn.rollback()
                self.pdf(filename, contents, download=query == "download=1")
            return

        if self.command == "POST" and path == "/api/logout":
            log_out(conn, token)
            self.json_response(200, {}, {"Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"})
            return
        if user["role"] != "admin":
            raise ApiError(403, "当前账号只有辖区内的查阅权限。")
        if self.command == "POST":
            if path == "/api/documents":
                self.json_response(201, save_document(conn, self.payload(UPLOAD_LIMIT)))
                return
            writer = RESOURCE_WRITERS.get(path.removeprefix("/api/"))
            if writer:
                self.json_response(201, writer(conn, user, self.payload()))
                return
        if self.command == "PATCH":
            match = EDIT_ROUTE.fullmatch(path)
            if match:
                self.json_response(200, RESOURCE_WRITERS[match[1]](conn, user, self.payload(), int(match[2])))
                return
        raise ApiError(404, "页面或记录不存在。")

    def static(self, path):
        if path in ("/", "/index.html"):
            file = STATIC_DIR / "index.html"
        else:
            match = ASSET_ROUTE.fullmatch(path)
            if not match:
                raise ApiError(404, "页面或记录不存在。")
            file = STATIC_DIR / match[1]
        resolved = file.resolve()
        mime = STATIC_TYPES.get(file.suffix)
        if not mime or not resolved.is_relative_to(STATIC_DIR.resolve()) or not resolved.is_file():
            raise ApiError(404, "页面或记录不存在。")
        self.respond(200, resolved.read_bytes(), mime)

    def pdf(self, filename, contents, download):
        disposition = "attachment" if download else "inline"
        extra = {
            "Content-Disposition": f"{disposition}; filename=\"document.pdf\"; filename*=UTF-8''{quote(filename, safe='')}",
            "Accept-Ranges": "bytes",
        }
        requested_range = self.headers.get("Range")
        if requested_range is None:
            self.respond(200, contents, "application/pdf", extra)
            return
        length = len(contents)
        match = BYTE_RANGE.fullmatch(requested_range)
        if not match or not any(match.groups()):
            self.respond(416, b"", "application/pdf", {"Content-Range": f"bytes */{length}"})
            return
        first, last = match.groups()
        start = int(first) if first else max(0, length - int(last))
        end = min(int(last), length - 1) if first and last else length - 1
        if start > end:
            self.respond(416, b"", "application/pdf", {"Content-Range": f"bytes */{length}"})
            return
        extra["Content-Range"] = f"bytes {start}-{end}/{length}"
        self.respond(206, contents[start:end + 1], "application/pdf", extra)

    def json_response(self, status, value, headers=None):
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.respond(status, body, "application/json; charset=utf-8", headers)

    def respond(self, status, content, mime, headers=None):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; frame-src 'self'; frame-ancestors 'self'; "
            "object-src 'none'; form-action 'self'; base-uri 'none'"
        ))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)
