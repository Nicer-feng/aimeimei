"""仅监听本机的 HTTP 服务。"""

from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import ip_address
import json
import re
import sqlite3
import sys
from urllib.parse import quote, urlsplit

from .attachment_formats import FORMATS, extension
from .data import (
    ApiError, PROJECT_ROOT, SESSION_SECONDS, catalog, database, delete_record, document_file,
    invalid, log_in, log_out, profile, rack_availability, save_device, save_document, save_project,
    save_rack, save_room, save_room_layout, save_system, session_user, set_device_archive, string,
)
from .edge import LoginThrottle
from .identity import AI_COOKIE, IdentityError, sroom_user


STATIC_DIR = PROJECT_ROOT / "static"
COOKIE = "asset_ledger_session"
LOCAL_HOST = re.compile(r"(?:127\.0\.0\.1|localhost|\[::1\])(?::[0-9]{1,5})?", re.I)
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
FILE_ROUTE = re.compile(r"/api/documents/([1-9][0-9]{0,9})/file")
EDIT_ROUTE = re.compile(r"/api/(devices|systems|projects|rooms|racks)/([1-9][0-9]{0,9})")
DELETE_ROUTE = re.compile(r"/api/(documents|devices|systems|projects)/([1-9][0-9]{0,9})")
DEVICE_ARCHIVE_ROUTE = re.compile(r"/api/devices/([1-9][0-9]{0,9})/(archive|restore)")
ROOM_LAYOUT_ROUTE = re.compile(r"/api/rooms/([1-9][0-9]{0,9})/layout")
ASSET_ROUTE = re.compile(r"/static/([a-zA-Z0-9_-][a-zA-Z0-9._-]*(?:/[a-zA-Z0-9_-][a-zA-Z0-9._-]*)*)")
ENCODING_QUALITY = re.compile(r"\s*q\s*=\s*(0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)\s*", re.I)
BYTE_RANGE = re.compile(r"bytes=([0-9]{0,10})-([0-9]{0,10})")
RESOURCE_WRITERS = {
    "devices": save_device, "systems": save_system, "projects": save_project, "rooms": save_room, "racks": save_rack,
}
WRITE_LIMIT = 1024 * 1024
UPLOAD_LIMIT = 12 * 1024 * 1024
PDFJS_CACHE_QUERY = "v=6.5.438"
PDFJS_CACHE_FILES = {"vendor/pdfjs/pdf.min.mjs", "vendor/pdfjs/pdf.worker.min.mjs"}
PRIVATE_CACHE = "private, no-store"
VERSIONED_CACHE = "public, max-age=31536000, immutable"
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
    ".bcmap": "application/octet-stream", ".pfb": "application/x-font-type1",
    ".ttf": "font/ttf", ".wasm": "application/wasm", ".icc": "application/vnd.iccprofile",
}


def accepts_gzip(headers):
    qualities = {}
    for field in headers:
        for item in field.split(","):
            coding, separator, parameter = item.partition(";")
            coding = coding.strip().lower()
            if coding not in ("gzip", "*"):
                continue
            match = ENCODING_QUALITY.fullmatch(parameter) if separator else None
            quality = float(match[1]) if match else (0 if separator else 1)
            qualities[coding] = min(quality, qualities.get(coding, 1))
    return qualities.get("gzip", qualities.get("*", 0)) > 0


class LedgerServer(ThreadingHTTPServer):
    def __init__(self, port, data_dir, public_site=None, *, ai_sso=False):
        self.data_dir = data_dir
        self.public_site = public_site
        self.ai_sso = ai_sso
        self.login_throttle = LoginThrottle()
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

    def do_DELETE(self):
        self.handle_request()

    def handle_request(self):
        try:
            target = urlsplit(self.path)
            if target.scheme or target.netloc or target.fragment:
                raise invalid("请求地址格式不正确。")
            path = self.route_path(target.path)
            if self.command in ("GET", "HEAD") and not path.startswith("/api/"):
                self.static(path, target.query)
            elif path == "/api/health" and self.command in ("GET", "HEAD"):
                self.json_response(200, {"status": "ok"})
            elif path == "/api/auth-config" and self.command in ("GET", "HEAD"):
                self.json_response(200, {"mode": "ai" if self.server.ai_sso else "local"})
            else:
                with database(self.server.data_dir) as conn:
                    self.api(conn, path, target.query)
        except ApiError as error:
            payload = {"error": str(error)}
            if isinstance(error, IdentityError):
                payload["code"] = "sroom_identity"
            self.json_response(error.status, payload)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except (sqlite3.Error, OSError, ValueError) as error:
            print(f"台账服务请求失败（{type(error).__name__}）。", file=sys.stderr)
            self.json_response(500, {"error": "服务暂时无法完成请求。"})

    def route_path(self, path):
        hosts = self.headers.get_all("Host", [])
        host = hosts[0].lower() if len(hosts) == 1 else ""
        self.public_peer = None
        self.cookie_path = "/"
        if LOCAL_HOST.fullmatch(host):
            self.request_origin = "http://" + host
            return path

        site = self.server.public_site
        if (site is None or host not in (site.host, site.host + ":443") or
                self.headers.get_all("X-Forwarded-Proto", []) != ["https"]):
            raise ApiError(403, "请通过台账的指定访问地址打开。")
        if not path.startswith(site.prefix):
            raise ApiError(404, "页面或记录不存在。")
        # 该字段由监听公网 HTTPS 的 Caddy 写入，应用本身仍只监听回环地址。
        peers = self.headers.get_all("X-Ledger-Client-IP", [])
        try:
            self.public_peer = str(ip_address(peers[0] if len(peers) == 1 else ""))
        except ValueError:
            raise ApiError(403, "台账入口校验失败。") from None
        self.request_origin = site.origin
        self.cookie_path = site.prefix
        return "/" + path[len(site.prefix):]

    def check_origin(self):
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or (origins and origins[0].lower() != self.request_origin):
            raise ApiError(403, "请求来源与台账访问地址不一致。")
        if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            raise ApiError(403, "请在台账页面内提交请求。")

    def session_token(self, name=COOKIE):
        try:
            headers = self.headers.get_all("Cookie", [])
            if len(headers) != 1:
                return None
            cookies = SimpleCookie(headers[0])
        except CookieError:
            return None
        token = cookies.get(name)
        return token.value if token and TOKEN.fullmatch(token.value) else None

    def session_cookie(self, token, max_age):
        flags = "; HttpOnly; SameSite=Strict"
        if self.public_peer is not None:
            flags += "; Secure"
        return f"{COOKIE}={token}; Path={self.cookie_path}; Max-Age={max_age}{flags}"

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
        writing = self.command in ("POST", "PATCH", "DELETE")
        if writing:
            self.check_origin()
        managed = self.server.ai_sso
        if managed and self.command == "POST" and path in ("/api/login", "/api/logout"):
            raise ApiError(404, "请使用 AI 槑槑登录或退出。")
        token = self.session_token(AI_COOKIE if managed else COOKIE)
        if self.command == "POST" and path == "/api/login":
            payload = self.payload(4096)
            if self.public_peer is not None and not self.server.login_throttle.allow(self.public_peer):
                self.json_response(429, {"error": "登录请求过于频繁，请稍后重试。"}, {"Retry-After": "60"})
                return
            user, new_token = log_in(
                conn,
                string(payload, "username", "账号", 100, required=True),
                string(payload, "password", "密码", 256, required=True, trim=False),
            )
            log_out(conn, token)
            self.json_response(200, profile(conn, user), {"Set-Cookie": self.session_cookie(new_token, SESSION_SECONDS)})
            return

        if managed:
            user = sroom_user(token)
        if not writing:
            # 授权范围与返回内容使用同一个读取快照。
            conn.execute("BEGIN")
        if not managed:
            user = session_user(conn, token)
        if user is None:
            raise ApiError(401, "请登录台账。")
        if managed and user["role"] == "reader" and not conn.execute(
            "SELECT 1 FROM units WHERE id = ?", (user["unit_id"],),
        ).fetchone():
            raise IdentityError(403, "当前账号的机房辖区不可用，请联系管理员。")
        if not writing:
            if path == "/api/me":
                self.json_response(200, profile(conn, user))
            elif path == "/api/catalog":
                self.json_response(200, catalog(conn, user))
            elif path == "/api/rack-availability":
                self.json_response(200, rack_availability(conn, user, query))
            else:
                match = FILE_ROUTE.fullmatch(path)
                if not match:
                    raise ApiError(404, "页面或记录不存在。")
                filename, contents = document_file(conn, user, int(match[1]))
                conn.rollback()
                self.attachment(filename, contents, download=query == "download=1")
            return

        if self.command == "POST" and path == "/api/logout":
            log_out(conn, token)
            self.json_response(200, {}, {"Set-Cookie": self.session_cookie("", 0)})
            return
        if user["role"] != "admin":
            raise ApiError(403, "当前账号只有辖区内的查阅权限。")
        if self.command == "POST":
            if path == "/api/documents":
                self.json_response(201, save_document(conn, self.payload(UPLOAD_LIMIT)))
                return
            archive = DEVICE_ARCHIVE_ROUTE.fullmatch(path)
            if archive:
                self.json_response(200, set_device_archive(conn, user, int(archive[1]), archive[2] == "archive"))
                return
            writer = RESOURCE_WRITERS.get(path.removeprefix("/api/"))
            if writer:
                self.json_response(201, writer(conn, user, self.payload()))
                return
        if self.command == "PATCH":
            layout = ROOM_LAYOUT_ROUTE.fullmatch(path)
            if layout:
                self.json_response(200, save_room_layout(conn, self.payload(), int(layout[1])))
                return
            match = EDIT_ROUTE.fullmatch(path)
            if match:
                self.json_response(200, RESOURCE_WRITERS[match[1]](conn, user, self.payload(), int(match[2])))
                return
        if self.command == "DELETE":
            match = DELETE_ROUTE.fullmatch(path)
            if match:
                delete_record(conn, match[1], int(match[2]))
                self.json_response(200, {})
                return
        raise ApiError(404, "页面或记录不存在。")

    def static(self, path, query):
        if path in ("/", "/index.html"):
            asset = "index.html"
        else:
            match = ASSET_ROUTE.fullmatch(path)
            if not match:
                raise ApiError(404, "页面或记录不存在。")
            asset = match[1]
        static_root = STATIC_DIR.resolve()
        file = static_root / asset
        resolved = file.resolve()
        mime = STATIC_TYPES.get(file.suffix)
        if not mime or not resolved.is_relative_to(static_root) or not resolved.is_file():
            raise ApiError(404, "页面或记录不存在。")
        if asset not in PDFJS_CACHE_FILES or query != PDFJS_CACHE_QUERY or resolved != file:
            self.respond(200, resolved.read_bytes(), mime)
            return

        headers = {"Vary": "Accept-Encoding"}
        sidecar = file.with_name(file.name + ".gz")
        # 只为两个已知公开模块读取同目录的预压缩副本。
        if accepts_gzip(self.headers.get_all("Accept-Encoding", [])) and not sidecar.is_symlink() and sidecar.is_file():
            resolved = sidecar
            headers["Content-Encoding"] = "gzip"
        self.respond(200, resolved.read_bytes(), mime, headers, cache_control=VERSIONED_CACHE)

    def attachment(self, filename, contents, download):
        suffix = extension(filename)
        file_format = FORMATS.get(suffix)
        if file_format is None:
            raise ApiError(404, "档案文件格式无法识别。")
        disposition = "inline" if file_format.inline and not download else "attachment"
        extra = {
            "Content-Disposition": (
                f"{disposition}; filename=\"document{suffix}\"; filename*=UTF-8''{quote(filename, safe='')}"
            ),
            "Accept-Ranges": "bytes",
        }
        requested_range = self.headers.get("Range")
        if requested_range is None:
            self.respond(200, contents, file_format.mime, extra)
            return
        length = len(contents)
        match = BYTE_RANGE.fullmatch(requested_range)
        if not match or not any(match.groups()):
            self.respond(416, b"", file_format.mime, {"Content-Range": f"bytes */{length}"})
            return
        first, last = match.groups()
        start = int(first) if first else max(0, length - int(last))
        end = min(int(last), length - 1) if first and last else length - 1
        if start > end:
            self.respond(416, b"", file_format.mime, {"Content-Range": f"bytes */{length}"})
            return
        extra["Content-Range"] = f"bytes {start}-{end}/{length}"
        self.respond(206, contents[start:end + 1], file_format.mime, extra)

    def json_response(self, status, value, headers=None):
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.respond(status, body, "application/json; charset=utf-8", headers)

    def respond(self, status, content, mime, headers=None, *, cache_control=PRIVATE_CACHE):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; frame-src 'self'; frame-ancestors 'self'; "
            "font-src 'self' blob:; worker-src 'self'; "
            "object-src 'none'; form-action 'self'; base-uri 'none'"
        ))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(content)
