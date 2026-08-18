#!/usr/bin/env python3
import hmac
import json
import mimetypes
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from ai_platform.database import db, init_db
from ai_platform.handlers import (
    AdminHandlersMixin,
    AuthHandlersMixin,
    CatHandlersMixin,
    ChatHandlersMixin,
    LibraryHandlersMixin,
    MediaHandlersMixin,
    ShareHandlersMixin,
    TTSHandlersMixin,
)
from ai_platform.runtime import (
    current_app_version,
    current_build_info,
    ensure_secrets,
    iso_now,
    now,
    parse_changelog,
    token_hash,
)
from ai_platform.settings import (
    AI_PAGE_PATH,
    CAT_PAGE_PATH,
    DATA_DIR,
    DEV_MODE,
    HOME_PAGE_PATH,
    LISTEN,
    MARKDOWN_TEST_PATH,
    RES_DIR,
    SESSION_COOKIE,
    SHARE_PAGE_PATH,
)


class AppHandler(
    AuthHandlersMixin,
    CatHandlersMixin,
    AdminHandlersMixin,
    LibraryHandlersMixin,
    MediaHandlersMixin,
    ShareHandlersMixin,
    TTSHandlersMixin,
    ChatHandlersMixin,
    BaseHTTPRequestHandler,
):
    server_version = "AIPlatform/2.0"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {self.command} {self.path} - {fmt % args}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self.ai_page()
        if path in ("/dev/markdown", "/dev/markdown/"):
            if not DEV_MODE:
                return self.error(HTTPStatus.NOT_FOUND, "not found")
            return self.static_file(MARKDOWN_TEST_PATH)
        if path in ("/xiaoji", "/xiaoji/"):
            return self.home_page()
        if path in ("/cat", "/cat/"):
            return self.cat_page()
        if path.startswith("/share/") or path.startswith("/ai/share/"):
            return self.share_page()
        if path == "/favicon.ico":
            return self.static_file(RES_DIR / "favicon.ico")
        if path.startswith("/res/"):
            return self.handle_res_file(path)
        if path == "/cat/api/me":
            return self.handle_cat_me()
        if path == "/cat/api/cats":
            return self.handle_cat_cats()
        if path.startswith("/cat/api/cats/"):
            return self.handle_cat_item()
        if path == "/cat/api/daily-report":
            return self.require_cat_admin(self.handle_cat_daily_report)
        if path == "/cat/api/posts":
            return self.handle_cat_posts()
        if path.startswith("/cat/api/posts/"):
            return self.handle_cat_post_item()
        if path.startswith("/cat/api/users/"):
            return self.handle_cat_user_profile()
        if path == "/cat/api/upload-policy":
            return self.require_cat_user(self.handle_cat_upload_policy)
        if path == "/cat/api/admin/users":
            return self.require_cat_admin(self.handle_cat_admin_users)
        if path == "/api/health":
            return self.json({"status": "ok", "time": iso_now()})
        if path == "/api/version":
            return self.handle_version()
        if path == "/api/changelog":
            return self.handle_changelog()
        if path.startswith("/api/public/shares/") and "/images/" in path:
            return self.handle_public_share_image()
        if path.startswith("/api/public/shares/"):
            return self.handle_public_share()
        if path == "/api/me":
            return self.handle_me()
        if path == "/api/models":
            return self.require_user(self.handle_models)
        if path == "/api/tts/config":
            return self.require_user(self.handle_tts_config)
        if path.startswith("/api/messages/") and path.endswith("/tts/audio"):
            return self.require_user(self.handle_message_tts_audio)
        if path == "/api/search":
            return self.require_user(self.handle_global_search)
        if path == "/api/search-config":
            return self.require_user(self.handle_search_config)
        if path == "/api/profiles":
            return self.require_user(self.handle_profiles)
        if path == "/api/prompts":
            return self.require_user(self.handle_prompts)
        if path == "/api/favorites":
            return self.require_user(self.handle_favorites)
        if path.startswith("/api/chat-images/") and path.endswith("/view"):
            return self.require_user(self.handle_chat_image_view)
        if path == "/api/media/tasks":
            return self.require_user(self.handle_media_tasks)
        if path.startswith("/api/media/tasks/"):
            return self.require_user(self.handle_media_task_item)
        if path == "/api/admin/models":
            return self.require_admin(self.handle_admin_models)
        if path == "/api/admin/tts":
            return self.require_admin(self.handle_admin_tts)
        if path == "/api/admin/search":
            return self.require_admin(self.handle_admin_search)
        if path == "/api/admin/token-stats":
            return self.require_admin(self.handle_admin_token_stats)
        if path == "/api/admin/cost-stats":
            return self.require_admin(self.handle_admin_cost_stats)
        if path == "/api/admin/overview":
            return self.require_admin(self.handle_admin_overview)
        if path == "/api/admin/users":
            return self.require_admin(self.handle_admin_users)
        if path == "/api/token-activity":
            return self.require_user(self.handle_token_activity)
        if path == "/api/side-discussions":
            return self.require_user(self.handle_side_discussions)
        if path.startswith("/api/side-discussions/"):
            return self.require_user(self.handle_side_discussion_item)
        if path == "/api/conversations":
            return self.require_user(self.handle_conversations)
        if path.startswith("/api/conversations/") and path.endswith("/messages"):
            return self.require_user(self.handle_messages)
        if path.startswith("/api/conversations/") and path.endswith("/shares"):
            return self.require_user(self.handle_conversation_shares)
        if path.startswith("/api/conversations/") and path.endswith("/stats"):
            return self.require_user(self.handle_conversation_stats)
        if path.startswith("/api/sessions/") and path.endswith("/stats"):
            return self.require_user(self.handle_conversation_stats)
        return self.error(HTTPStatus.NOT_FOUND, "not found")

    def do_HEAD(self):
        self._head_only = True
        try:
            return self.do_GET()
        finally:
            self._head_only = False

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/cat/api/login":
            return self.handle_cat_login()
        if path == "/cat/api/logout":
            return self.handle_cat_logout()
        if path == "/cat/api/images":
            return self.require_cat_user(self.handle_cat_images)
        if path == "/cat/api/cats":
            return self.require_cat_user(self.handle_cat_cats)
        if path == "/cat/api/posts":
            return self.require_cat_user(self.handle_cat_posts)
        if path.startswith("/cat/api/posts/"):
            return self.handle_cat_post_action()
        if path == "/cat/api/admin/users":
            return self.require_cat_admin(self.handle_cat_admin_users)
        if path == "/api/login":
            return self.handle_login()
        if path == "/api/logout":
            return self.handle_logout()
        if path == "/api/admin/models":
            return self.require_admin(self.handle_admin_models)
        if path == "/api/admin/tts":
            return self.require_admin(self.handle_admin_tts)
        if path == "/api/admin/search":
            return self.require_admin(self.handle_admin_search)
        if path == "/api/admin/cost-recalculate":
            return self.require_admin(self.handle_admin_cost_recalculate)
        if path == "/api/admin/password":
            return self.require_admin(self.handle_admin_password)
        if path == "/api/admin/users":
            return self.require_admin(self.handle_admin_users)
        if path == "/api/profiles":
            return self.require_user(self.handle_profiles)
        if path == "/api/profiles/reorder":
            return self.require_user(self.handle_profile_reorder)
        if path == "/api/prompts":
            return self.require_user(self.handle_prompts)
        if path == "/api/favorites":
            return self.require_user(self.handle_favorites)
        if path.startswith("/api/messages/") and path.endswith("/tts"):
            return self.require_user(self.handle_message_tts_prepare)
        if path == "/api/chat-images/upload-policy":
            return self.require_user(self.handle_chat_image_upload_policy)
        if path == "/api/chat-images":
            return self.require_user(self.handle_chat_images)
        if path == "/api/media/upload-policy":
            return self.require_user(self.handle_media_upload_policy)
        if path == "/api/media/tasks":
            return self.require_user(self.handle_media_tasks)
        if path.startswith("/api/media/tasks/") and path.endswith("/refresh"):
            return self.require_user(self.handle_media_task_refresh)
        if path.startswith("/api/media/tasks/") and path.endswith("/enhance"):
            return self.require_user(self.handle_media_task_enhance)
        if path.startswith("/api/media/tasks/") and path.endswith("/conversation"):
            return self.require_user(self.handle_media_task_conversation)
        if path == "/api/side-discussions":
            return self.require_user(self.handle_side_discussions)
        if path.startswith("/api/side-discussions/") and path.endswith("/messages"):
            return self.require_user(self.handle_side_discussion_send)
        if path.startswith("/api/side-discussions/") and path.endswith("/conversation"):
            return self.require_user(self.handle_side_discussion_conversation)
        if path.startswith("/api/conversations/") and (path.endswith("/pin") or path.endswith("/unpin")):
            return self.require_user(self.handle_conversation_pin)
        if path.startswith("/api/sessions/") and (path.endswith("/pin") or path.endswith("/unpin")):
            return self.require_user(self.handle_conversation_pin)
        if path == "/api/conversations":
            return self.require_user(self.handle_conversations)
        if path.startswith("/api/conversations/") and path.endswith("/messages"):
            return self.require_user(self.handle_send_message)
        if path.startswith("/api/conversations/") and path.endswith("/shares"):
            return self.require_user(self.handle_conversation_shares)
        return self.error(HTTPStatus.NOT_FOUND, "not found")

    def do_PUT(self):
        path = urlparse(self.path).path
        if path.startswith("/cat/api/cats/"):
            return self.require_cat_user(self.handle_cat_item)
        if path.startswith("/cat/api/admin/users/"):
            return self.require_cat_admin(self.handle_cat_admin_user_item)
        if path.startswith("/api/admin/models/"):
            return self.require_admin(self.handle_admin_model_item)
        if path.startswith("/api/admin/users/"):
            return self.require_admin(self.handle_admin_user_item)
        if path.startswith("/api/profiles/"):
            return self.require_user(self.handle_profile_item)
        if path.startswith("/api/prompts/"):
            return self.require_user(self.handle_prompt_item)
        return self.error(HTTPStatus.NOT_FOUND, "not found")

    def do_PATCH(self):
        path = urlparse(self.path).path
        if path.startswith("/api/profiles/"):
            return self.require_user(self.handle_profile_item)
        if path.startswith("/api/conversations/"):
            return self.require_user(self.handle_conversation_item)
        return self.error(HTTPStatus.NOT_FOUND, "not found")

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/cat/api/posts/"):
            return self.require_cat_user(self.handle_cat_post_delete)
        if path.startswith("/cat/api/cats/"):
            return self.require_cat_user(self.handle_cat_item)
        if path.startswith("/api/admin/models/"):
            return self.require_admin(self.handle_admin_model_item)
        if path.startswith("/api/prompts/"):
            return self.require_user(self.handle_prompt_item)
        if path.startswith("/api/profiles/"):
            return self.require_user(self.handle_profile_item)
        if path.startswith("/api/favorites/message/"):
            return self.require_user(self.handle_favorite_by_message)
        if path.startswith("/api/favorites/"):
            return self.require_user(self.handle_favorite_item)
        if path.startswith("/api/media/tasks/"):
            return self.require_user(self.handle_media_task_item)
        if path.startswith("/api/conversation-shares/"):
            return self.require_user(self.handle_conversation_share_item)
        if path.startswith("/api/conversations/"):
            return self.require_user(self.handle_conversation_item)
        return self.error(HTTPStatus.NOT_FOUND, "not found")

    def read_body(self, limit=1024 * 1024):
        length = int(self.headers.get("Content-Length") or "0")
        if length > limit:
            raise ValueError("request body too large")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        return json.loads(raw.decode())

    def html(self, body):
        data = body.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store, max-age=0, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(data)

    def home_page(self):
        try:
            return self.html(HOME_PAGE_PATH.read_text())
        except FileNotFoundError:
            return self.error(HTTPStatus.NOT_FOUND, "home page not found")

    def ai_page(self):
        try:
            return self.html(AI_PAGE_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self.error(HTTPStatus.NOT_FOUND, "AI page not found")

    def cat_page(self):
        try:
            return self.html(CAT_PAGE_PATH.read_text())
        except FileNotFoundError:
            return self.error(HTTPStatus.NOT_FOUND, "cat page not found")

    def share_page(self):
        try:
            return self.html(SHARE_PAGE_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return self.error(HTTPStatus.NOT_FOUND, "share page not found")

    def handle_changelog(self):
        params = parse_qs(urlparse(self.path).query)
        raw_limit = (params.get("limit") or [""])[0]
        limit = None
        if raw_limit:
            try:
                limit = max(1, min(50, int(raw_limit)))
            except ValueError:
                limit = 10
        all_entries = parse_changelog()
        entries = all_entries[:limit] if limit is not None else all_entries
        return self.json(
            {
                "version": current_app_version(),
                "entries": entries,
                "has_more": limit is not None and len(all_entries) > len(entries),
            }
        )

    def handle_version(self):
        raw = json.dumps(current_build_info(), ensure_ascii=False).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(raw)

    def handle_res_file(self, path):
        name = unquote(path.removeprefix("/res/"))
        if not name or name.startswith("/") or ".." in Path(name).parts:
            return self.error(HTTPStatus.NOT_FOUND, "not found")
        try:
            target = (RES_DIR / name).resolve()
            target.relative_to(RES_DIR.resolve())
        except Exception:
            return self.error(HTTPStatus.NOT_FOUND, "not found")
        return self.static_file(target)

    def static_file(self, target):
        if not target.is_file():
            return self.error(HTTPStatus.NOT_FOUND, "not found")
        data = target.read_bytes()
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if target.suffix.lower() in {".css", ".js"}:
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        else:
            self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(data)

    def json(self, data, status=HTTPStatus.OK):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(raw)

    def error(self, status, message, detail=None):
        payload = {"error": message}
        if detail:
            payload["detail"] = detail
        return self.json(payload, status)

    def session_token(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if SESSION_COOKIE in cookie:
            return cookie[SESSION_COOKIE].value
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        return ""

    def current_user(self):
        if hasattr(self, "_current_user_cache"):
            return self._current_user_cache
        token = self.session_token()
        if not token:
            self._current_user_cache = None
            return None
        with db() as conn:
            row = conn.execute(
                """
                SELECT u.*
                FROM sessions s
                JOIN users u ON u.id = s.user_id
                WHERE s.token_hash=? AND s.expires_at>? AND u.is_active=1
                """,
                (token_hash(token), now()),
            ).fetchone()
        self._current_user_cache = row
        return row

    def require_user(self, handler):
        if not self.current_user():
            return self.error(HTTPStatus.UNAUTHORIZED, "unauthorized")
        return handler()

    def require_admin(self, handler):
        got = self.headers.get("X-Admin-Key", "").strip()
        expected = self.server.secrets["admin_key"]
        if got and hmac.compare_digest(got, expected):
            return handler()
        user = self.current_user()
        if user and user["role"] == "admin":
            return handler()
        return self.error(HTTPStatus.UNAUTHORIZED, "admin unauthorized")

class AIPlatformServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler, secrets_data):
        super().__init__(server_address, handler)
        self.secrets = secrets_data


def parse_listen(value):
    if value.startswith(":"):
        return ("", int(value[1:]))
    if ":" in value:
        host, port = value.rsplit(":", 1)
        return (host, int(port))
    return ("", int(value))


def main():
    secrets_data = ensure_secrets()
    init_db(secrets_data)
    address = parse_listen(LISTEN)
    server = AIPlatformServer(address, AppHandler, secrets_data)
    print(f"ai-platform listening on {LISTEN}")
    print(f"data dir: {DATA_DIR}")
    server.serve_forever()


if __name__ == "__main__":
    main()
