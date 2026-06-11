#!/usr/bin/env python3
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlparse


DATA_DIR = Path(os.environ.get("AI_PLATFORM_DATA", "/opt/ai-platform"))
LISTEN = os.environ.get("AI_PLATFORM_LISTEN", ":8080")
DB_PATH = DATA_DIR / "ai-platform.db"
SECRETS_PATH = DATA_DIR / "secrets.json"
ADMIN_KEY_PATH = DATA_DIR / "admin.key"
FAMILY_PASSWORD_PATH = DATA_DIR / "family_password.txt"
LEGACY_CONFIG_PATH = DATA_DIR / "config.json"
SESSION_COOKIE = "ap_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14


def now() -> int:
    return int(time.time())


def iso_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def today_text() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def current_year() -> str:
    return time.strftime("%Y", time.localtime())


def b64_token(size: int = 32) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(size)).decode().rstrip("=")


def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    rounds = 260000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), rounds)
    return f"pbkdf2_sha256${rounds}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, rounds, salt, digest = encoded.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), salt.encode(), int(rounds)
        ).hex()
        return hmac.compare_digest(candidate, digest)
    except Exception:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def read_json(path: Path, fallback):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return fallback
    except json.JSONDecodeError:
        return fallback


def write_private(path: Path, content: str):
    path.write_text(content)
    os.chmod(path, 0o600)


def ensure_secrets():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(DATA_DIR, 0o700)

    data = read_json(SECRETS_PATH, {})
    changed = False

    if not data.get("admin_key"):
        if ADMIN_KEY_PATH.exists():
            data["admin_key"] = ADMIN_KEY_PATH.read_text().strip()
        else:
            data["admin_key"] = b64_token()
        changed = True

    if not data.get("family_password_hash"):
        family_password = "home-" + b64_token(12)
        data["family_password_hash"] = password_hash(family_password)
        write_private(FAMILY_PASSWORD_PATH, family_password + "\n")
        changed = True
    elif not FAMILY_PASSWORD_PATH.exists():
        FAMILY_PASSWORD_PATH.write_text(
            "Password already initialized. Change it from the admin panel.\n"
        )
        os.chmod(FAMILY_PASSWORD_PATH, 0o600)

    web_search = data.get("web_search")
    if not isinstance(web_search, dict):
        data["web_search"] = {
            "provider": "tavily",
            "api_key": "",
            "enabled": False,
            "result_count": 5,
            "mode": "auto",
            "depth": "advanced",
        }
        changed = True
    else:
        if web_search.get("mode") not in ("manual", "auto", "always"):
            web_search["mode"] = "auto"
            changed = True
        if web_search.get("depth") not in ("basic", "advanced"):
            web_search["depth"] = "advanced"
            changed = True

    if changed:
        write_private(SECRETS_PATH, json.dumps(data, indent=2) + "\n")

    if not ADMIN_KEY_PATH.exists():
        write_private(ADMIN_KEY_PATH, data["admin_key"] + "\n")

    return data


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS models (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              provider TEXT NOT NULL DEFAULT '',
              base_url TEXT NOT NULL,
              api_key TEXT NOT NULL,
              model TEXT NOT NULL,
              system_prompt TEXT NOT NULL DEFAULT '',
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              model_id TEXT NOT NULL,
              archived INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              FOREIGN KEY (model_id) REFERENCES models(id)
            );

            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              conversation_id TEXT NOT NULL,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS message_sources (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              message_id INTEGER NOT NULL,
              title TEXT NOT NULL,
              url TEXT NOT NULL,
              snippet TEXT NOT NULL DEFAULT '',
              position INTEGER NOT NULL,
              created_at INTEGER NOT NULL,
              FOREIGN KEY (message_id) REFERENCES messages(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS sessions (
              token_hash TEXT PRIMARY KEY,
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL
            );
            """
        )

        count = conn.execute("SELECT COUNT(*) AS n FROM models").fetchone()["n"]
        if count == 0:
            legacy = read_json(LEGACY_CONFIG_PATH, {})
            base_url = legacy.get("base_url") or "https://api.deepseek.com/v1"
            api_key = legacy.get("api_key") or ""
            model = legacy.get("model") or "deepseek-chat"
            system_prompt = legacy.get("system_prompt") or ""
            conn.execute(
                """
                INSERT INTO models
                (id, name, provider, base_url, api_key, model, system_prompt, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    b64_token(12),
                    "默认模型",
                    "OpenAI Compatible",
                    base_url.rstrip("/"),
                    api_key.strip(),
                    model.strip(),
                    system_prompt.strip(),
                    now(),
                    now(),
                ),
            )


def public_model(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "provider": row["provider"],
        "base_url": row["base_url"],
        "model": row["model"],
        "system_prompt": row["system_prompt"],
        "enabled": bool(row["enabled"]),
        "has_api_key": bool(row["api_key"].strip()),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def private_model(row):
	return public_model(row)


def conversation_row(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "model_id": row["model_id"],
        "model_name": row["model_name"],
        "model": row["model"],
        "updated_at": row["updated_at"],
        "created_at": row["created_at"],
    }


def clamp_int(value, default, min_value, max_value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, number))


def web_search_config(secrets_data):
    config = secrets_data.get("web_search") or {}
    provider = str(config.get("provider") or "tavily").strip().lower()
    if provider not in ("tavily", "brave"):
        provider = "tavily"
    mode = str(config.get("mode") or "auto").strip().lower()
    if mode not in ("manual", "auto", "always"):
        mode = "auto"
    depth = str(config.get("depth") or "advanced").strip().lower()
    if depth not in ("basic", "advanced"):
        depth = "advanced"
    api_key = str(config.get("api_key") or "").strip()
    return {
        "provider": provider,
        "api_key": api_key,
        "enabled": bool(config.get("enabled")),
        "result_count": clamp_int(config.get("result_count"), 5, 1, 8),
        "mode": mode,
        "depth": depth,
    }


def public_web_search_config(secrets_data):
    config = web_search_config(secrets_data)
    return {
        "provider": config["provider"],
        "enabled": config["enabled"],
        "configured": bool(config["api_key"]),
        "result_count": config["result_count"],
        "mode": config["mode"],
        "depth": config["depth"],
    }


def search_result(title, url, snippet):
    return {
        "title": str(title or "").strip()[:240],
        "url": str(url or "").strip(),
        "snippet": str(snippet or "").strip()[:900],
    }


FRESHNESS_PATTERNS = [
    "最新", "现在", "目前", "当前", "今天", "昨日", "昨天", "明天", "今年", "本月",
    "近期", "最近", "刚刚", "新版", "新版本", "发布", "更新", "涨价", "降价",
    "价格", "多少钱", "汇率", "股价", "天气", "新闻", "政策", "法规", "公告",
    "官网", "文档", "api", "模型", "版本", "排行", "榜单", "联网", "搜索",
    "today", "latest", "current", "now", "recent", "news", "price", "pricing",
    "weather", "stock", "release", "released", "update", "updated", "version",
    "api", "model", "docs", "documentation", "official", "policy", "law",
]


def should_auto_web_search(content):
    text = str(content or "").strip().lower()
    if not text:
        return False
    if re.search(r"\b20(2[5-9]|3[0-9])\b", text):
        return True
    return any(pattern.lower() in text for pattern in FRESHNESS_PATTERNS)


def should_use_web_search(content, requested, config):
    if not config["enabled"]:
        return False
    if config["mode"] == "always":
        return True
    if requested:
        return True
    if config["mode"] == "auto":
        return should_auto_web_search(content)
    return False


def build_search_query(content):
    text = re.sub(r"\s+", " ", str(content or "")).strip()
    if len(text) > 260:
        text = text[:260]
    year = current_year()
    if year not in text:
        text = f"{text} {year}"
    if not any(word in text.lower() for word in ("official", "官网", "文档", "最新", "latest")):
        text = f"{text} 最新 官方"
    return text


def perform_web_search(query, config):
    query = build_search_query(query)
    provider = config["provider"]
    if provider == "brave":
        return brave_search(query, config["api_key"], config["result_count"])
    return tavily_search(query, config["api_key"], config["result_count"], config["depth"])


def tavily_search(query, api_key, count, depth):
    payload = {
        "query": query,
        "search_depth": depth,
        "max_results": count,
        "include_answer": False,
        "include_raw_content": False,
    }
    request = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "User-Agent": "ai-platform/2.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode())
    results = []
    for item in data.get("results") or []:
        result = search_result(
            item.get("title"),
            item.get("url"),
            item.get("content") or item.get("snippet"),
        )
        if result["url"] and result["title"]:
            results.append(result)
    return results[:count]


def brave_search(query, api_key, count):
    url = "https://api.search.brave.com/res/v1/web/search?" + urlencode(
        {"q": query, "count": count}
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
            "User-Agent": "ai-platform/2.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode())
    results = []
    for item in (data.get("web") or {}).get("results") or []:
        result = search_result(
            item.get("title"),
            item.get("url"),
            item.get("description") or item.get("snippet"),
        )
        if result["url"] and result["title"]:
            results.append(result)
    return results[:count]


def build_runtime_context(has_search_results=False):
    lines = [
        f"当前日期：{today_text()}。",
        "回答任何涉及现在、最新、价格、政策、版本、模型、API、新闻、天气、日期或可能变化的信息时，必须把当前日期作为判断基准。",
    ]
    if has_search_results:
        lines.append("本次对话已提供联网搜索资料。若搜索资料与模型训练记忆冲突，必须以搜索资料为准。")
    else:
        lines.append("如果没有联网搜索资料，不要把旧训练知识当作最新事实；遇到时效性问题应明确说明可能需要联网确认。")
    return "\n".join(lines)


def build_search_context(results):
    lines = [
        f"以下是平台在 {today_text()} 刚刚联网搜索到的资料。",
        "回答时必须优先依据这些资料；不要使用旧训练知识覆盖搜索结果。",
        "如果资料不足、来源太旧或无法相互印证，请直接说明不确定，不要编造。",
    ]
    for index, item in enumerate(results, 1):
        lines.append(
            f"[{index}] {item['title']}\nURL: {item['url']}\n摘要: {item['snippet'] or '无摘要'}"
        )
    lines.append("引用资料时使用 [1]、[2] 这样的编号。不要编造未出现在列表里的来源。")
    return "\n\n".join(lines)


def format_sources_markdown(results):
    if not results:
        return ""
    lines = ["\n\n---\n### 参考来源"]
    for index, item in enumerate(results, 1):
        title = item["title"].replace("[", "\\[").replace("]", "\\]")
        lines.append(f"{index}. [{title}]({item['url']})")
    return "\n".join(lines)


class AppHandler(BaseHTTPRequestHandler):
    server_version = "AIPlatform/2.0"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {self.command} {self.path} - {fmt % args}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self.html(INDEX_HTML)
        if path == "/api/health":
            return self.json({"status": "ok", "time": iso_now()})
        if path == "/api/me":
            return self.handle_me()
        if path == "/api/models":
            return self.require_user(self.handle_models)
        if path == "/api/search-config":
            return self.require_user(self.handle_search_config)
        if path == "/api/admin/models":
            return self.require_admin(self.handle_admin_models)
        if path == "/api/admin/search":
            return self.require_admin(self.handle_admin_search)
        if path == "/api/conversations":
            return self.require_user(self.handle_conversations)
        if path.startswith("/api/conversations/") and path.endswith("/messages"):
            return self.require_user(self.handle_messages)
        return self.error(HTTPStatus.NOT_FOUND, "not found")

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/login":
            return self.handle_login()
        if path == "/api/logout":
            return self.handle_logout()
        if path == "/api/admin/models":
            return self.require_admin(self.handle_admin_models)
        if path == "/api/admin/search":
            return self.require_admin(self.handle_admin_search)
        if path == "/api/admin/password":
            return self.require_admin(self.handle_admin_password)
        if path == "/api/conversations":
            return self.require_user(self.handle_conversations)
        if path.startswith("/api/conversations/") and path.endswith("/messages"):
            return self.require_user(self.handle_send_message)
        return self.error(HTTPStatus.NOT_FOUND, "not found")

    def do_PUT(self):
        path = urlparse(self.path).path
        if path.startswith("/api/admin/models/"):
            return self.require_admin(self.handle_admin_model_item)
        return self.error(HTTPStatus.NOT_FOUND, "not found")

    def do_PATCH(self):
        path = urlparse(self.path).path
        if path.startswith("/api/conversations/"):
            return self.require_user(self.handle_conversation_item)
        return self.error(HTTPStatus.NOT_FOUND, "not found")

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/admin/models/"):
            return self.require_admin(self.handle_admin_model_item)
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
        self.end_headers()
        self.wfile.write(data)

    def json(self, data, status=HTTPStatus.OK):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
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
        token = self.session_token()
        if not token:
            return None
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE token_hash=? AND expires_at>?",
                (token_hash(token), now()),
            ).fetchone()
            if not row:
                return None
        return {"role": "family"}

    def require_user(self, handler):
        if not self.current_user():
            return self.error(HTTPStatus.UNAUTHORIZED, "unauthorized")
        return handler()

    def require_admin(self, handler):
        got = self.headers.get("X-Admin-Key", "").strip()
        if not got:
            got = self.session_token()
        expected = self.server.secrets["admin_key"]
        if not hmac.compare_digest(got, expected):
            return self.error(HTTPStatus.UNAUTHORIZED, "admin unauthorized")
        return handler()

    def handle_login(self):
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        password = str(data.get("password") or "")
        if not verify_password(password, self.server.secrets["family_password_hash"]):
            return self.error(HTTPStatus.UNAUTHORIZED, "password incorrect")

        token = b64_token(32)
        expires = now() + SESSION_TTL_SECONDS
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at<=?", (now(),))
            conn.execute(
                "INSERT INTO sessions(token_hash, created_at, expires_at) VALUES (?, ?, ?)",
                (token_hash(token), now(), expires),
            )

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}",
        )
        raw = json.dumps({"ok": True, "expires_at": expires}).encode()
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def handle_logout(self):
        token = self.session_token()
        if token:
            with db() as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
        )
        raw = b'{"ok":true}'
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def handle_me(self):
        return self.json({"authenticated": bool(self.current_user())})

    def handle_models(self):
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM models WHERE enabled=1 ORDER BY updated_at DESC"
            ).fetchall()
        return self.json({"models": [public_model(row) for row in rows]})

    def handle_search_config(self):
        return self.json({"search": public_web_search_config(self.server.secrets)})

    def handle_admin_search(self):
        if self.command == "GET":
            config = web_search_config(self.server.secrets)
            return self.json(
                {
                    "search": {
                        "provider": config["provider"],
                        "enabled": config["enabled"],
                        "result_count": config["result_count"],
                        "mode": config["mode"],
                        "depth": config["depth"],
                        "has_api_key": bool(config["api_key"]),
                    }
                }
            )

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        provider = str(data.get("provider") or "tavily").strip().lower()
        if provider not in ("tavily", "brave"):
            return self.error(HTTPStatus.BAD_REQUEST, "unsupported search provider")
        mode = str(data.get("mode") or "auto").strip().lower()
        if mode not in ("manual", "auto", "always"):
            return self.error(HTTPStatus.BAD_REQUEST, "unsupported search mode")
        depth = str(data.get("depth") or "advanced").strip().lower()
        if depth not in ("basic", "advanced"):
            return self.error(HTTPStatus.BAD_REQUEST, "unsupported search depth")

        old_config = web_search_config(self.server.secrets)
        api_key = old_config["api_key"]
        if data.get("clear_api_key"):
            api_key = ""
        elif str(data.get("api_key") or "").strip():
            api_key = str(data.get("api_key")).strip()

        self.server.secrets["web_search"] = {
            "provider": provider,
            "api_key": api_key,
            "enabled": bool(data.get("enabled")),
            "result_count": clamp_int(data.get("result_count"), 5, 1, 8),
            "mode": mode,
            "depth": depth,
        }
        write_private(SECRETS_PATH, json.dumps(self.server.secrets, indent=2) + "\n")
        return self.json({"ok": True, "search": public_web_search_config(self.server.secrets)})

    def handle_admin_models(self):
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute("SELECT * FROM models ORDER BY updated_at DESC").fetchall()
            return self.json({"models": [private_model(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        name = str(data.get("name") or "").strip()
        base_url = str(data.get("base_url") or "").strip().rstrip("/")
        api_key = str(data.get("api_key") or "").strip()
        model = str(data.get("model") or "").strip()
        provider = str(data.get("provider") or "").strip()
        system_prompt = str(data.get("system_prompt") or "").strip()
        enabled = 1 if data.get("enabled", True) else 0

        if not name or not base_url or not model:
            return self.error(HTTPStatus.BAD_REQUEST, "name, base_url and model are required")

        model_id = b64_token(12)
        ts = now()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO models
                (id, name, provider, base_url, api_key, model, system_prompt, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (model_id, name, provider, base_url, api_key, model, system_prompt, enabled, ts, ts),
            )
            row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        return self.json({"model": private_model(row)}, HTTPStatus.CREATED)

    def handle_admin_model_item(self):
        model_id = urlparse(self.path).path.rsplit("/", 1)[-1]
        with db() as conn:
            row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "model not found")

            if self.command == "DELETE":
                linked = conn.execute(
                    "SELECT COUNT(*) AS n FROM conversations WHERE model_id=?",
                    (model_id,),
                ).fetchone()["n"]
                if linked:
                    conn.execute(
                        "UPDATE models SET enabled=0, updated_at=? WHERE id=?",
                        (now(), model_id),
                    )
                else:
                    conn.execute("DELETE FROM models WHERE id=?", (model_id,))
                return self.json({"ok": True})

            try:
                data = self.read_body()
            except Exception:
                return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

            name = str(data.get("name", row["name"])).strip()
            provider = str(data.get("provider", row["provider"])).strip()
            base_url = str(data.get("base_url", row["base_url"])).strip().rstrip("/")
            model = str(data.get("model", row["model"])).strip()
            system_prompt = str(data.get("system_prompt", row["system_prompt"])).strip()
            enabled = 1 if data.get("enabled", bool(row["enabled"])) else 0
            api_key = row["api_key"]
            if data.get("clear_api_key"):
                api_key = ""
            elif str(data.get("api_key") or "").strip():
                api_key = str(data.get("api_key")).strip()

            if not name or not base_url or not model:
                return self.error(HTTPStatus.BAD_REQUEST, "name, base_url and model are required")

            conn.execute(
                """
                UPDATE models
                SET name=?, provider=?, base_url=?, api_key=?, model=?, system_prompt=?, enabled=?, updated_at=?
                WHERE id=?
                """,
                (name, provider, base_url, api_key, model, system_prompt, enabled, now(), model_id),
            )
            row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        return self.json({"model": private_model(row)})

    def handle_admin_password(self):
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        password = str(data.get("password") or "")
        if len(password) < 8:
            return self.error(HTTPStatus.BAD_REQUEST, "password must be at least 8 characters")
        self.server.secrets["family_password_hash"] = password_hash(password)
        write_private(SECRETS_PATH, json.dumps(self.server.secrets, indent=2) + "\n")
        write_private(FAMILY_PASSWORD_PATH, password + "\n")
        with db() as conn:
            conn.execute("DELETE FROM sessions")
        return self.json({"ok": True})

    def handle_conversations(self):
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT c.*, m.name AS model_name, m.model AS model
                    FROM conversations c
                    JOIN models m ON m.id = c.model_id
                    WHERE c.archived=0
                    ORDER BY c.updated_at DESC
                    LIMIT 200
                    """
                ).fetchall()
            return self.json({"conversations": [conversation_row(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        model_id = str(data.get("model_id") or "").strip()
        title = str(data.get("title") or "新对话").strip()[:80] or "新对话"
        with db() as conn:
            model = conn.execute(
                "SELECT * FROM models WHERE id=? AND enabled=1", (model_id,)
            ).fetchone()
            if not model:
                return self.error(HTTPStatus.BAD_REQUEST, "model not found")
            conversation_id = b64_token(12)
            ts = now()
            conn.execute(
                """
                INSERT INTO conversations(id, title, model_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (conversation_id, title, model_id, ts, ts),
            )
            row = conn.execute(
                """
                SELECT c.*, m.name AS model_name, m.model AS model
                FROM conversations c JOIN models m ON m.id=c.model_id
                WHERE c.id=?
                """,
                (conversation_id,),
            ).fetchone()
        return self.json({"conversation": conversation_row(row)}, HTTPStatus.CREATED)

    def conversation_id_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) >= 3:
            return parts[2]
        return ""

    def handle_conversation_item(self):
        conversation_id = self.conversation_id_from_path()
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id=? AND archived=0",
                (conversation_id,),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")

            if self.command == "DELETE":
                conn.execute(
                    "UPDATE conversations SET archived=1, updated_at=? WHERE id=?",
                    (now(), conversation_id),
                )
                return self.json({"ok": True})

            try:
                data = self.read_body()
            except Exception:
                return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
            title = str(data.get("title") or row["title"]).strip()[:80] or row["title"]
            conn.execute(
                "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                (title, now(), conversation_id),
            )
        return self.json({"ok": True})

    def handle_messages(self):
        conversation_id = self.conversation_id_from_path()
        with db() as conn:
            row = conn.execute(
                "SELECT id FROM conversations WHERE id=? AND archived=0",
                (conversation_id,),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
            messages = conn.execute(
                """
                SELECT id, role, content, created_at
                FROM messages
                WHERE conversation_id=?
                ORDER BY id ASC
                """,
                (conversation_id,),
            ).fetchall()
            sources = conn.execute(
                """
                SELECT message_id, title, url, snippet, position
                FROM message_sources
                WHERE message_id IN (
                  SELECT id FROM messages WHERE conversation_id=?
                )
                ORDER BY message_id ASC, position ASC
                """,
                (conversation_id,),
            ).fetchall()
        sources_by_message = {}
        for source in sources:
            sources_by_message.setdefault(source["message_id"], []).append(
                {
                    "title": source["title"],
                    "url": source["url"],
                    "snippet": source["snippet"],
                    "position": source["position"],
                }
            )
        return self.json(
            {
                "messages": [
                    {
                        "id": row["id"],
                        "role": row["role"],
                        "content": row["content"],
                        "created_at": row["created_at"],
                        "sources": sources_by_message.get(row["id"], []),
                    }
                    for row in messages
                ]
            }
        )

    def handle_send_message(self):
        conversation_id = self.conversation_id_from_path()
        try:
            data = self.read_body(limit=2 * 1024 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        content = str(data.get("content") or "").strip()
        requested_web_search = bool(data.get("web_search"))
        if not content:
            return self.error(HTTPStatus.BAD_REQUEST, "content required")

        search_results = []
        search_config = web_search_config(self.server.secrets)
        use_web_search = should_use_web_search(content, requested_web_search, search_config)
        with db() as conn:
            convo = conn.execute(
                """
                SELECT c.*, m.name AS model_name, m.base_url, m.api_key, m.model, m.system_prompt, m.enabled
                FROM conversations c JOIN models m ON m.id=c.model_id
                WHERE c.id=? AND c.archived=0
                """,
                (conversation_id,),
            ).fetchone()
            if not convo:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
            if not convo["enabled"]:
                return self.error(HTTPStatus.BAD_REQUEST, "model disabled")
            if not convo["api_key"].strip():
                return self.error(HTTPStatus.BAD_REQUEST, "model api key is not configured")

            if use_web_search:
                if not search_config["enabled"] or not search_config["api_key"]:
                    return self.error(HTTPStatus.BAD_REQUEST, "web search is not configured")
                try:
                    search_results = perform_web_search(content, search_config)
                except urllib.error.HTTPError as exc:
                    detail = exc.read(65536).decode(errors="replace")
                    return self.error(
                        HTTPStatus.BAD_GATEWAY,
                        f"search upstream status {exc.code}",
                        detail,
                    )
                except Exception as exc:
                    return self.error(
                        HTTPStatus.BAD_GATEWAY, "web search request failed", str(exc)
                    )
                if not search_results:
                    return self.error(HTTPStatus.BAD_GATEWAY, "web search returned no results")

            ts = now()
            conn.execute(
                "INSERT INTO messages(conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
                (conversation_id, content, ts),
            )
            if convo["title"] == "新对话":
                title = content.replace("\n", " ")[:28] or "新对话"
                conn.execute(
                    "UPDATE conversations SET title=?, updated_at=? WHERE id=?",
                    (title, ts, conversation_id),
                )
            else:
                conn.execute(
                    "UPDATE conversations SET updated_at=? WHERE id=?",
                    (ts, conversation_id),
                )
            history = conn.execute(
                """
                SELECT role, content
                FROM messages
                WHERE conversation_id=?
                ORDER BY id ASC
                LIMIT 80
                """,
                (conversation_id,),
            ).fetchall()

        upstream_messages = []
        upstream_messages.append(
            {"role": "system", "content": build_runtime_context(bool(search_results))}
        )
        if convo["system_prompt"].strip():
            upstream_messages.append(
                {"role": "system", "content": convo["system_prompt"].strip()}
            )
        if search_results:
            upstream_messages.append(
                {"role": "system", "content": build_search_context(search_results)}
            )
        upstream_messages.extend(
            {"role": row["role"], "content": row["content"]} for row in history
        )
        payload = {
            "model": convo["model"],
            "messages": upstream_messages,
            "stream": True,
        }

        request = urllib.request.Request(
            convo["base_url"].rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Authorization": "Bearer " + convo["api_key"].strip(),
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "User-Agent": "ai-platform/2.0",
            },
            method="POST",
        )

        try:
            response = urllib.request.urlopen(request, timeout=120)
        except urllib.error.HTTPError as exc:
            detail = exc.read(65536).decode(errors="replace")
            return self.error(
                HTTPStatus.BAD_GATEWAY,
                f"upstream status {exc.code}",
                detail,
            )
        except Exception as exc:
            return self.error(HTTPStatus.BAD_GATEWAY, "upstream request failed", str(exc))

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        assistant_parts = []
        buffer = ""
        try:
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
                buffer += chunk.decode(errors="ignore")
                lines = buffer.splitlines(keepends=True)
                if lines and not lines[-1].endswith(("\n", "\r")):
                    buffer = lines.pop()
                else:
                    buffer = ""
                for line in lines:
                    text = line.strip()
                    if not text.startswith("data:"):
                        continue
                    data_text = text[5:].strip()
                    if not data_text or data_text == "[DONE]":
                        continue
                    try:
                        event = json.loads(data_text)
                    except json.JSONDecodeError:
                        continue
                    choice = (event.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    message = choice.get("message") or {}
                    piece = delta.get("content") or message.get("content") or ""
                    if piece:
                        assistant_parts.append(piece)
        finally:
            response.close()

        sources_markdown = format_sources_markdown(search_results)
        if sources_markdown:
            source_event = {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": sources_markdown},
                        "finish_reason": None,
                    }
                ]
            }
            try:
                self.wfile.write(
                    ("data: " + json.dumps(source_event, ensure_ascii=False) + "\n\n").encode()
                )
                self.wfile.flush()
            except Exception:
                pass
            assistant_parts.append(sources_markdown)

        assistant_text = "".join(assistant_parts).strip()
        if assistant_text:
            with db() as conn:
                cursor = conn.execute(
                    "INSERT INTO messages(conversation_id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
                    (conversation_id, assistant_text, now()),
                )
                message_id = cursor.lastrowid
                for index, item in enumerate(search_results, 1):
                    conn.execute(
                        """
                        INSERT INTO message_sources(message_id, title, url, snippet, position, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            message_id,
                            item["title"],
                            item["url"],
                            item["snippet"],
                            index,
                            now(),
                        ),
                    )
                conn.execute(
                    "UPDATE conversations SET updated_at=? WHERE id=?",
                    (now(), conversation_id),
                )


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
    init_db()
    address = parse_listen(LISTEN)
    server = AIPlatformServer(address, AppHandler, secrets_data)
    print(f"ai-platform listening on {LISTEN}")
    print(f"data dir: {DATA_DIR}")
    server.serve_forever()


INDEX_HTML = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI槑槑</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f8fb;
      --sidebar: #f7f7f8;
      --sidebar-strong: #eeeeef;
      --surface: #ffffff;
      --surface-soft: #f3f6fa;
      --line: #dbe2ea;
      --line-strong: #b9c4d2;
      --text: #111827;
      --muted: #6b7280;
      --muted-2: #9ca3af;
      --accent: #111827;
      --teal: #0f766e;
      --blue: #2563eb;
      --green: #16845f;
      --red: #dc2626;
      --shadow: 0 14px 40px rgba(15, 23, 42, .10);
      --soft-shadow: 0 8px 24px rgba(15, 23, 42, .07);
      --radius: 8px;
      --content: 860px;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0;
      background: #f6f8fb;
      color: var(--text);
      font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      -webkit-font-smoothing: antialiased;
    }
    button, input, textarea, select { font: inherit; }
    button, select {
      min-height: 36px;
      border: 1px solid transparent;
      border-radius: 8px;
      background: transparent;
      color: var(--text);
      padding: 0 11px;
      cursor: pointer;
      transition: background .16s ease, border-color .16s ease, transform .12s ease, box-shadow .16s ease;
    }
    button:hover, select:hover { background: #f3f4f6; }
    button:active { transform: translateY(1px); }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      box-shadow: 0 6px 18px rgba(17, 24, 39, .16);
    }
    button.primary:hover { background: #272f3d; }
    button.ghost { background: transparent; }
    button.icon {
      width: 36px;
      min-width: 36px;
      padding: 0;
      display: grid;
      place-items: center;
      font-weight: 700;
    }
    button.danger { color: var(--red); }
    button:disabled { opacity: .5; cursor: not-allowed; transform: none; box-shadow: none; }
    input, textarea {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--text);
      padding: 9px 11px;
      outline: none;
      transition: border-color .16s ease, box-shadow .16s ease, background .16s ease;
    }
    textarea { resize: vertical; }
    input:focus, textarea:focus, select:focus {
      border-color: #9ca3af;
      box-shadow: 0 0 0 3px rgba(17, 24, 39, .08);
      outline: none;
    }
    .login {
      min-height: 100%;
      display: grid;
      place-items: center;
      padding: 20px;
      background:
        radial-gradient(circle at 30% 10%, rgba(15, 118, 110, .10), transparent 32%),
        linear-gradient(180deg, #ffffff, #f7f7f8);
    }
    .login-panel {
      width: min(392px, 100%);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: rgba(255,255,255,.94);
      box-shadow: var(--shadow);
      padding: 24px;
    }
    .login-panel h1 { margin: 0 0 4px; font-size: 23px; letter-spacing: 0; }
    .login-panel p { margin: 0 0 18px; color: var(--muted); }
    .app {
      height: 100vh;
      display: grid;
      grid-template-columns: 292px minmax(0, 1fr);
      overflow: hidden;
      background: var(--bg);
    }
    .sidebar {
      border-right: 1px solid var(--line);
      background:
        linear-gradient(180deg, #fafafa, var(--sidebar));
      display: grid;
      grid-template-rows: auto auto 1fr auto;
      min-width: 0;
    }
    .side-head {
      padding: 14px 12px 10px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }
    .brand h1 { margin: 0; font-size: 16px; letter-spacing: 0; }
    .brand span { display: block; color: var(--muted); font-size: 12px; }
    .side-actions {
      padding: 0 10px 10px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
    }
    .side-actions .primary {
      justify-content: flex-start;
      box-shadow: none;
    }
    .conversation-list {
      overflow: auto;
      padding: 4px 8px 14px;
    }
    .conv {
      width: 100%;
      min-height: 46px;
      border: 1px solid transparent;
      background: transparent;
      border-radius: 8px;
      padding: 4px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: 4px;
      margin-bottom: 3px;
      transition: background .16s ease, border-color .16s ease, box-shadow .16s ease;
    }
    .conv:hover { background: #ededee; }
    .conv.active {
      background: #fff;
      border-color: var(--line);
      box-shadow: var(--soft-shadow);
    }
    .conv.editing {
      background: #fff;
      border-color: var(--line-strong);
      box-shadow: var(--soft-shadow);
    }
    .conv-main {
      min-width: 0;
      min-height: 38px;
      padding: 7px 7px;
      display: grid;
      gap: 1px;
      text-align: left;
      background: transparent;
      border: 0;
    }
    .conv-main:hover { background: transparent; }
    .conv-title {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-weight: 580;
      font-size: 13px;
    }
    .conv-meta {
      color: var(--muted);
      font-size: 11px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .conv-actions {
      display: flex;
      gap: 2px;
      opacity: 0;
      pointer-events: none;
      transition: opacity .14s ease;
    }
    .conv:hover .conv-actions,
    .conv.active .conv-actions,
    .conv.editing .conv-actions,
    .conv:focus-within .conv-actions {
      opacity: 1;
      pointer-events: auto;
    }
    .conv-action {
      width: 30px;
      min-width: 30px;
      height: 30px;
      min-height: 30px;
      padding: 0;
      color: var(--muted);
      background: transparent;
    }
    .conv-action:hover {
      color: var(--text);
      background: #fff;
      border-color: var(--line);
    }
    .conv-action.danger:hover {
      color: var(--red);
    }
    .conv-rename {
      min-height: 34px;
      padding: 7px 8px;
      font-size: 13px;
      font-weight: 580;
      background: #fff;
    }
    .side-foot {
      border-top: 1px solid var(--line);
      padding: 10px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
    }
    .main {
      min-width: 0;
      position: relative;
      display: grid;
      grid-template-rows: auto 1fr auto;
      height: 100vh;
      background: var(--bg);
    }
    .topbar {
      height: 56px;
      border-bottom: 1px solid var(--line);
      background: rgba(255,255,255,.86);
      backdrop-filter: blur(12px);
      display: grid;
      grid-template-columns: auto minmax(0, 1fr) auto;
      align-items: center;
      gap: 10px;
      padding: 0 16px;
      min-width: 0;
      z-index: 4;
    }
    .top-title {
      min-width: 0;
      justify-self: center;
      text-align: center;
      max-width: 640px;
    }
    .top-title strong {
      display: block;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      font-size: 14px;
      font-weight: 650;
    }
    .top-title span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }
    .mobile-only { display: none; }
    .messages {
      overflow: auto;
      padding: 28px clamp(14px, 4vw, 46px) 24px;
      display: flex;
      flex-direction: column;
      gap: 18px;
      scroll-behavior: smooth;
      background:
        linear-gradient(180deg, rgba(255,255,255,.70), rgba(246,248,251,.92) 180px),
        #f6f8fb;
    }
    .scroll-latest {
      position: absolute;
      left: 50%;
      bottom: 116px;
      z-index: 6;
      min-height: 34px;
      padding: 0 12px;
      border-color: #cbd5e1;
      background: rgba(255, 255, 255, .94);
      color: var(--text);
      box-shadow: 0 10px 28px rgba(15, 23, 42, .14);
      opacity: 0;
      pointer-events: none;
      transform: translate(-50%, 10px);
      transition: opacity .16s ease, transform .16s ease, border-color .16s ease;
    }
    .scroll-latest.show {
      opacity: 1;
      pointer-events: auto;
      transform: translate(-50%, 0);
    }
    .scroll-latest:hover {
      border-color: var(--line-strong);
      background: #fff;
    }
    .messages-inner {
      width: min(var(--content), 100%);
      margin: 0 auto;
    }
    .empty {
      margin: auto;
      width: min(720px, 100%);
      display: grid;
      gap: 20px;
      text-align: center;
      color: var(--text);
      animation: rise .2s ease;
    }
    .empty h2 {
      margin: 0;
      font-size: clamp(28px, 4vw, 42px);
      font-weight: 720;
      letter-spacing: 0;
    }
    .empty p {
      margin: 0;
      color: var(--muted);
      font-size: 15px;
    }
    .prompt-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 4px;
    }
    .prompt-card {
      min-height: 66px;
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 8px;
      padding: 12px;
      text-align: left;
      display: grid;
      align-content: center;
      box-shadow: var(--soft-shadow);
    }
    .prompt-card:hover {
      border-color: var(--line-strong);
      background: #fafafa;
    }
    .prompt-card strong {
      display: block;
      font-weight: 650;
      margin-bottom: 2px;
    }
    .prompt-card span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .bubble {
      width: min(var(--content), 100%);
      margin: 0 auto;
      display: grid;
      gap: 6px;
      animation: rise .18s ease;
    }
    @keyframes rise {
      from { opacity: 0; transform: translateY(4px); }
      to { opacity: 1; transform: translateY(0); }
    }
    .bubble.user {
      justify-items: end;
    }
    .bubble.assistant {
      justify-items: start;
    }
    .bubble-shell {
      position: relative;
      max-width: min(760px, 100%);
      border: 1px solid #d8e0ea;
      border-radius: 8px;
      padding: 12px 44px 12px 14px;
      background: #fff;
      box-shadow: 0 10px 28px rgba(15, 23, 42, .08);
      white-space: normal;
      overflow-wrap: anywhere;
    }
    .bubble.assistant .bubble-shell {
      background: #fff;
      border-color: #d8e0ea;
      padding-left: 14px;
      padding-right: 42px;
    }
    .bubble.user .bubble-shell {
      background: #e7f0ff;
      border-color: #b8cdf8;
      box-shadow: 0 8px 22px rgba(37, 99, 235, .10);
    }
    .copy-btn {
      position: absolute;
      top: 7px;
      right: 7px;
      width: 28px;
      height: 28px;
      min-height: 28px;
      padding: 0;
      opacity: 0;
      color: var(--muted);
      background: #fff;
      border: 1px solid var(--line);
      box-shadow: 0 4px 12px rgba(15, 23, 42, .08);
    }
    .bubble-shell:hover .copy-btn,
    .copy-btn:focus { opacity: 1; }
    .role {
      color: var(--muted-2);
      font-size: 12px;
      padding: 0 2px;
    }
    .message-time {
      color: #8a94a6;
      font-size: 11px;
      line-height: 1;
      padding: 0 2px;
      user-select: none;
    }
    .markdown {
      color: var(--text);
      line-height: 1.68;
    }
    .markdown > :first-child { margin-top: 0; }
    .markdown > :last-child { margin-bottom: 0; }
    .markdown p { margin: 0 0 10px; }
    .markdown h1,
    .markdown h2,
    .markdown h3 {
      margin: 16px 0 8px;
      line-height: 1.28;
      letter-spacing: 0;
    }
    .markdown h1 { font-size: 22px; }
    .markdown h2 { font-size: 18px; }
    .markdown h3 { font-size: 15px; }
    .markdown ul,
    .markdown ol {
      margin: 6px 0 12px;
      padding-left: 22px;
    }
    .markdown li { margin: 3px 0; }
    .markdown blockquote {
      margin: 10px 0;
      padding: 8px 12px;
      border-left: 3px solid #9ca3af;
      background: #f3f6fa;
      color: #4b5563;
      border-radius: 0 8px 8px 0;
    }
    .markdown code {
      border: 1px solid #d7dee8;
      background: #f3f6fa;
      border-radius: 6px;
      padding: 1px 5px;
      font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    .markdown pre {
      margin: 10px 0 12px;
      padding: 12px;
      overflow: auto;
      border: 1px solid #ccd6e3;
      border-radius: 8px;
      background: #111827;
      color: #f9fafb;
    }
    .markdown pre code {
      display: block;
      border: 0;
      background: transparent;
      color: inherit;
      padding: 0;
      white-space: pre;
    }
    .markdown a {
      color: #1d4ed8;
      text-decoration: none;
      border-bottom: 1px solid rgba(29, 78, 216, .32);
    }
    .markdown a:hover { border-bottom-color: currentColor; }
    .markdown table {
      width: 100%;
      border-collapse: collapse;
      margin: 10px 0 12px;
      font-size: 13px;
    }
    .markdown th,
    .markdown td {
      border: 1px solid #d7dee8;
      padding: 7px 8px;
      text-align: left;
      vertical-align: top;
    }
    .markdown th {
      background: #f3f6fa;
      font-weight: 650;
    }
    .thinking {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      color: var(--muted);
      min-height: 26px;
    }
    .thinking-dots {
      display: inline-flex;
      gap: 4px;
      align-items: center;
    }
    .thinking-dots span {
      width: 5px;
      height: 5px;
      border-radius: 999px;
      background: var(--muted-2);
      animation: thinkingPulse 1s infinite ease-in-out;
    }
    .thinking-dots span:nth-child(2) { animation-delay: .15s; }
    .thinking-dots span:nth-child(3) { animation-delay: .3s; }
    @keyframes thinkingPulse {
      0%, 80%, 100% { opacity: .32; transform: translateY(0); }
      40% { opacity: 1; transform: translateY(-2px); }
    }
    .composer {
      background: linear-gradient(180deg, rgba(255,255,255,0), #fff 30%);
      padding: 10px clamp(12px, 4vw, 46px) 18px;
      display: grid;
      gap: 8px;
    }
    .composer-box {
      width: min(var(--content), 100%);
      margin: 0 auto;
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 8px;
      box-shadow: 0 14px 38px rgba(15, 23, 42, .10);
      padding: 8px;
      display: grid;
      gap: 7px;
    }
    .composer-tools {
      display: flex;
      gap: 8px;
      align-items: center;
      justify-content: space-between;
      padding: 0 2px;
    }
    .model-select {
      min-width: 220px;
      max-width: 100%;
      background: var(--surface-soft);
      border-color: var(--line);
      height: 34px;
      color: var(--text);
    }
    .search-toggle {
      min-height: 34px;
      margin: 0;
      padding: 0 10px;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-soft);
      color: var(--text);
      cursor: pointer;
      user-select: none;
    }
    .search-toggle input {
      width: 16px;
      min-height: 16px;
      margin: 0;
      accent-color: var(--accent);
      box-shadow: none;
    }
    .search-toggle.disabled {
      opacity: .55;
      cursor: not-allowed;
    }
    .composer-left {
      display: flex;
      gap: 8px;
      align-items: center;
      min-width: 0;
      flex-wrap: wrap;
    }
    .input-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: end;
    }
    #prompt {
      min-height: 50px;
      max-height: 180px;
      resize: none;
      border: 0;
      background: transparent;
      padding: 10px 8px;
      box-shadow: none;
    }
    #prompt:focus { box-shadow: none; border-color: transparent; }
    #send {
      width: 40px;
      min-width: 40px;
      height: 40px;
      min-height: 40px;
      padding: 0;
      border-radius: 8px;
      font-size: 0;
      position: relative;
    }
    #send::before {
      content: "↑";
      font-size: 20px;
      line-height: 1;
    }
    .status { min-height: 18px; color: var(--muted); font-size: 12px; }
    .status.err { color: var(--red); }
    .status.ok { color: var(--green); }
    .drawer-mask {
      position: fixed;
      inset: 0;
      background: rgba(15,23,42,.34);
      display: none;
      z-index: 20;
    }
    .drawer-mask.show { display: block; }
    .drawer {
      position: fixed;
      top: 0;
      right: 0;
      width: min(560px, 100%);
      height: 100%;
      background: #fff;
      border-left: 1px solid var(--line);
      box-shadow: -20px 0 44px rgba(31, 41, 55, .18);
      transform: translateX(100%);
      transition: transform .22s ease;
      z-index: 21;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .drawer.show { transform: translateX(0); }
    .drawer-head {
      height: 58px;
      padding: 0 16px;
      border-bottom: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    .copy-dialog {
      position: fixed;
      inset: 0;
      z-index: 30;
      display: none;
      place-items: center;
      padding: 18px;
      background: rgba(15,23,42,.38);
    }
    .copy-dialog.show { display: grid; }
    .copy-panel {
      width: min(720px, 100%);
      max-height: min(680px, 88vh);
      display: grid;
      grid-template-rows: auto minmax(180px, 1fr) auto;
      gap: 10px;
      background: #fff;
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 14px;
    }
    .copy-panel-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }
    .copy-panel-head strong { font-size: 15px; }
    #manualCopyText {
      min-height: 220px;
      max-height: 52vh;
      resize: vertical;
      white-space: pre-wrap;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      line-height: 1.55;
    }
    .copy-panel-actions {
      display: flex;
      justify-content: flex-end;
      gap: 8px;
      flex-wrap: wrap;
    }
    .drawer-body {
      overflow: auto;
      padding: 16px;
      display: grid;
      gap: 14px;
      align-content: start;
      background: var(--surface-soft);
    }
    .panel {
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--surface);
      padding: 14px;
      box-shadow: var(--soft-shadow);
    }
    .panel h2 {
      margin: 0 0 12px;
      font-size: 15px;
      letter-spacing: 0;
    }
    label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 10px;
    }
    .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
    .model-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 10px 0;
      border-top: 1px solid var(--line);
    }
    .model-row:first-child { border-top: 0; }
    .model-row strong, .model-row span {
      display: block;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }
    .model-row span { color: var(--muted); font-size: 12px; }
    @media (max-width: 900px) {
      .app { grid-template-columns: 1fr; }
      .sidebar {
        position: fixed;
        inset: 0 auto 0 0;
        width: min(320px, 86vw);
        z-index: 18;
        transform: translateX(-102%);
        transition: transform .22s ease;
        box-shadow: var(--shadow);
      }
      .sidebar.show { transform: translateX(0); }
      .mobile-only { display: inline-grid; }
      .main { height: 100vh; }
      .topbar { grid-template-columns: auto minmax(0, 1fr) auto; }
      .messages { padding-top: 20px; }
    }
    @media (max-width: 620px) {
      .topbar { padding: 0 10px; }
      .composer { padding: 8px 10px 12px; }
      .composer-tools { align-items: stretch; flex-direction: column; }
      .composer-left { width: 100%; }
      .model-select { width: 100%; }
      .search-toggle { width: fit-content; }
      .scroll-latest { bottom: 152px; }
      .input-row { grid-template-columns: 1fr auto; }
      .bubble-shell { max-width: 100%; }
      .prompt-grid { grid-template-columns: 1fr; }
      .grid2 { grid-template-columns: 1fr; }
      .drawer { width: 100%; }
    }
  </style>
</head>
<body>
  <div class="login" id="loginView">
    <form class="login-panel" id="loginForm">
      <h1>AI槑槑</h1>
	      <p>为家里人准备好的 AI 工作台</p>
      <label>登录密码<input id="loginPassword" type="password" autocomplete="current-password"></label>
      <button class="primary" type="submit" style="width:100%">登录</button>
      <div class="status err" id="loginStatus"></div>
    </form>
  </div>

  <div class="app" id="appView" style="display:none">
    <aside class="sidebar" id="sidebar">
      <div class="side-head">
        <div class="brand">
          <h1>AI槑槑</h1>
          <span id="health">连接中</span>
        </div>
        <button class="icon mobile-only" id="closeSide" title="关闭">×</button>
      </div>
      <div class="side-actions">
	        <button class="primary" id="newChat">+ 新对话</button>
        <button class="icon" id="refreshConversations" title="刷新">↻</button>
      </div>
      <div class="conversation-list" id="conversationList"></div>
      <div class="side-foot">
        <button id="openSettings">模型管理</button>
        <button id="logout">退出</button>
      </div>
    </aside>

    <main class="main">
      <header class="topbar">
        <button class="icon mobile-only" id="openSide" title="对话">☰</button>
        <div class="top-title">
          <strong id="chatTitle">新对话</strong>
          <span id="chatModel">请选择模型</span>
        </div>
        <button class="icon danger" id="deleteConversation" title="删除对话">⌫</button>
      </header>

      <section class="messages" id="messages"></section>
      <button class="scroll-latest" id="scrollLatest" type="button" title="回到底部">↓ 回到底部</button>

	      <footer class="composer">
	        <div class="composer-box">
	          <div class="composer-tools">
	            <div class="composer-left">
	              <select class="model-select" id="modelSelect"></select>
	              <label class="search-toggle" id="webSearchLabel" title="联网搜索">
	                <input id="webSearchToggle" type="checkbox">
	                <span>联网搜索</span>
	              </label>
	            </div>
	            <div class="status" id="chatStatus"></div>
	          </div>
	          <div class="input-row">
	            <textarea id="prompt" placeholder="问点什么"></textarea>
	            <button class="primary" id="send" title="发送">发送</button>
	          </div>
	        </div>
	      </footer>
    </main>
  </div>

	  <div class="drawer-mask" id="drawerMask"></div>
	  <section class="copy-dialog" id="copyDialog">
	    <div class="copy-panel">
	      <div class="copy-panel-head">
	        <strong>手动复制</strong>
	        <button class="icon" id="closeCopyDialog" title="关闭">×</button>
	      </div>
	      <textarea id="manualCopyText" readonly></textarea>
	      <div class="copy-panel-actions">
	        <button id="selectManualCopy">全选</button>
	        <button class="primary" id="retryManualCopy">再试一次复制</button>
	      </div>
	    </div>
	  </section>
	  <section class="drawer" id="settingsDrawer">
    <div class="drawer-head">
      <strong>模型管理</strong>
      <button class="icon" id="closeSettings" title="关闭">×</button>
    </div>
    <div class="drawer-body">
	      <section class="panel">
	        <h2>管理员</h2>
	        <label>管理密钥<input id="adminKey" type="password" autocomplete="off"></label>
        <div class="grid2">
          <label>新的家用登录密码<input id="familyPassword" type="password" autocomplete="new-password" placeholder="至少 8 位"></label>
          <div style="display:flex;align-items:end"><button id="changePassword">修改登录密码</button></div>
        </div>
	        <div class="status" id="adminStatus"></div>
	      </section>

	      <section class="panel">
	        <h2>联网搜索</h2>
	        <div class="grid2">
	          <label>搜索服务
	            <select id="searchProvider">
	              <option value="tavily">Tavily</option>
	              <option value="brave">Brave Search</option>
	            </select>
	          </label>
	          <label>启用搜索
	            <select id="searchEnabled">
	              <option value="0">关闭</option>
	              <option value="1">开启</option>
	            </select>
	          </label>
	        </div>
	        <div class="grid2">
	          <label>搜索策略
	            <select id="searchMode">
	              <option value="auto">自动联网</option>
	              <option value="manual">手动开关</option>
	              <option value="always">强制联网</option>
	            </select>
	          </label>
	          <label>搜索深度
	            <select id="searchDepth">
	              <option value="advanced">更准</option>
	              <option value="basic">更快</option>
	            </select>
	          </label>
	        </div>
	        <div class="grid2">
	          <label>结果数量
	            <input id="searchResultCount" type="number" min="1" max="8" value="5">
	          </label>
	          <label>搜索 API Key
	            <input id="searchApiKey" type="password" autocomplete="off" placeholder="留空则保持原值">
	          </label>
	        </div>
	        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
	          <button class="primary" id="saveSearch">保存搜索配置</button>
	          <button id="clearSearchKey">清空搜索 Key</button>
	        </div>
	        <div class="status" id="searchStatus"></div>
	      </section>

	      <section class="panel">
        <h2>新增/编辑模型</h2>
        <input id="editingModelId" type="hidden">
        <div class="grid2">
          <label>显示名称<input id="modelName" placeholder="DeepSeek Chat"></label>
          <label>供应商<input id="provider" placeholder="DeepSeek"></label>
        </div>
        <label>API Base URL<input id="baseUrl" placeholder="https://api.deepseek.com/v1"></label>
        <div class="grid2">
          <label>Model<input id="modelCode" placeholder="deepseek-chat"></label>
          <label>API Key<input id="apiKey" type="password" autocomplete="off" placeholder="留空则保持原值"></label>
        </div>
        <label>System Prompt<textarea id="systemPrompt" rows="4"></textarea></label>
        <div class="grid2">
          <label>启用<select id="enabled"><option value="1">启用</option><option value="0">停用</option></select></label>
          <div style="display:flex;align-items:end;gap:8px">
            <button class="primary" id="saveModel">保存模型</button>
            <button id="resetModelForm">清空</button>
          </div>
        </div>
        <div class="status" id="modelStatus"></div>
      </section>

      <section class="panel">
        <h2>已配置模型</h2>
        <div id="adminModelList"></div>
      </section>
    </div>
  </section>

  <script>
    const $ = (id) => document.getElementById(id);
    const state = {
      authed: false,
      models: [],
	      conversations: [],
	      currentConversation: null,
	      messages: [],
	      sending: false,
	      editingConversationId: null,
	      streamMessage: null,
	      streamQueue: "",
	      streamTimer: null,
	      streamResolve: null,
	      firstTokenAt: null,
	      followOutput: true,
	      hasNewWhilePaused: false,
	      programmaticScroll: false,
	      messageSeq: 0,
	      searchConfig: null,
	      adminKey: localStorage.getItem("aiPlatformAdminKey") || ""
	    };
    $("adminKey").value = state.adminKey;

    function setStatus(id, text, kind = "") {
      const el = $(id);
      el.textContent = text || "";
      el.className = "status" + (kind ? " " + kind : "");
    }

    async function request(path, options = {}) {
      const headers = new Headers(options.headers || {});
      if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
      return fetch(path, { credentials: "same-origin", ...options, headers });
    }

    async function api(path, options = {}) {
      const res = await request(path, options);
      if (res.status === 401) {
        state.authed = false;
        showLogin();
        throw new Error("未登录或登录已过期");
      }
      return res;
    }

    async function adminApi(path, options = {}) {
      state.adminKey = $("adminKey").value.trim();
      localStorage.setItem("aiPlatformAdminKey", state.adminKey);
      const headers = new Headers(options.headers || {});
      headers.set("X-Admin-Key", state.adminKey);
      return request(path, { ...options, headers });
    }

    function showLogin() {
      $("loginView").style.display = "grid";
      $("appView").style.display = "none";
      $("loginPassword").focus();
    }

    function showApp() {
      $("loginView").style.display = "none";
      $("appView").style.display = "grid";
      $("prompt").focus();
    }

    async function bootstrap() {
      try {
        const me = await request("/api/me");
        const data = await me.json();
        if (!data.authenticated) return showLogin();
	        state.authed = true;
	        showApp();
	        await Promise.all([loadModels(), loadSearchConfig(), loadConversations(), health()]);
	      } catch {
	        showLogin();
	      }
    }

    async function health() {
      try {
        const res = await request("/api/health");
        $("health").textContent = res.ok ? "在线" : "异常";
      } catch {
        $("health").textContent = "离线";
      }
    }

    async function login(event) {
      event.preventDefault();
      setStatus("loginStatus", "");
      const password = $("loginPassword").value;
      const res = await request("/api/login", { method: "POST", body: JSON.stringify({ password }) });
      if (!res.ok) {
        setStatus("loginStatus", "密码不对", "err");
        return;
      }
	      $("loginPassword").value = "";
	      state.authed = true;
	      showApp();
	      await Promise.all([loadModels(), loadSearchConfig(), loadConversations(), health()]);
	    }

    async function logout() {
      await request("/api/logout", { method: "POST" });
      state.authed = false;
      state.currentConversation = null;
      state.messages = [];
      showLogin();
    }

	    async function loadModels() {
	      const res = await api("/api/models");
	      const data = await res.json();
	      state.models = data.models || [];
	      renderModelSelect();
	      if (!state.currentConversation && state.models.length) {
	        $("chatModel").textContent = "准备使用 " + state.models[0].name;
	      }
	    }

	    async function loadSearchConfig() {
	      try {
	        const res = await api("/api/search-config");
	        const data = await res.json();
	        state.searchConfig = data.search || null;
	      } catch {
	        state.searchConfig = null;
	      }
	      renderSearchToggle();
	    }

	    function renderSearchToggle() {
	      const config = state.searchConfig || {};
	      const available = Boolean(config.enabled && config.configured);
	      const toggle = $("webSearchToggle");
	      const label = $("webSearchLabel");
	      const mode = config.mode || "auto";
	      const text = label.querySelector("span");
	      toggle.disabled = !available || mode === "always";
	      label.classList.toggle("disabled", !available);
	      if (!available) {
	        toggle.checked = false;
	        if (text) text.textContent = "联网搜索";
	        label.title = config.enabled ? "搜索 API Key 未配置" : "后台未启用联网搜索";
	      } else if (mode === "always") {
	        toggle.checked = true;
	        if (text) text.textContent = "强制联网";
	        label.title = "所有问题都会先联网搜索";
	      } else if (mode === "auto") {
	        toggle.checked = false;
	        if (text) text.textContent = "自动联网";
	        label.title = "时效性问题会自动搜索；勾选后可强制本条联网";
	      } else {
	        const saved = localStorage.getItem("aiPlatformWebSearch");
	        toggle.checked = saved === null ? true : saved === "1";
	        if (text) text.textContent = "联网搜索";
	        label.title = "使用 " + config.provider + " 联网搜索";
	      }
	    }

	    function renderModelSelect() {
      const select = $("modelSelect");
      select.innerHTML = "";
      if (!state.models.length) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "暂无可用模型";
        select.appendChild(opt);
        return;
      }
      for (const model of state.models) {
        const opt = document.createElement("option");
        opt.value = model.id;
        opt.textContent = model.name + " · " + model.model;
        select.appendChild(opt);
      }
      if (state.currentConversation) {
        select.value = state.currentConversation.model_id;
      }
    }

    async function loadConversations() {
      const res = await api("/api/conversations");
      const data = await res.json();
      state.conversations = data.conversations || [];
      renderConversations();
      if (!state.currentConversation && state.conversations.length) {
        await selectConversation(state.conversations[0].id);
      } else if (!state.conversations.length) {
        renderEmpty();
      }
    }

	    function renderConversations() {
	      const box = $("conversationList");
	      box.innerHTML = "";
      if (!state.conversations.length) {
        const div = document.createElement("div");
        div.className = "status";
        div.style.padding = "12px";
        div.textContent = "暂无对话";
        box.appendChild(div);
        return;
	      }
	      for (const conv of state.conversations) {
	        const row = document.createElement("div");
	        const active = state.currentConversation?.id === conv.id;
	        const editing = state.editingConversationId === conv.id;
	        row.className = "conv" + (active ? " active" : "") + (editing ? " editing" : "");

	        if (editing) {
	          const input = document.createElement("input");
	          input.className = "conv-rename";
	          input.value = conv.title;
	          input.maxLength = 80;
	          input.addEventListener("keydown", (event) => {
	            if (event.key === "Enter") saveConversationTitle(conv.id, input.value);
	            if (event.key === "Escape") {
	              state.editingConversationId = null;
	              renderConversations();
	            }
	          });

	          const actions = document.createElement("div");
	          actions.className = "conv-actions";
	          const save = document.createElement("button");
	          save.className = "conv-action";
	          save.type = "button";
	          save.title = "保存";
	          save.textContent = "✓";
	          save.addEventListener("click", () => saveConversationTitle(conv.id, input.value));
	          const cancel = document.createElement("button");
	          cancel.className = "conv-action";
	          cancel.type = "button";
	          cancel.title = "取消";
	          cancel.textContent = "×";
	          cancel.addEventListener("click", () => {
	            state.editingConversationId = null;
	            renderConversations();
	          });
	          actions.append(save, cancel);
	          row.append(input, actions);
	          setTimeout(() => {
	            input.focus();
	            input.select();
	          }, 0);
	        } else {
	          const main = document.createElement("button");
	          main.className = "conv-main";
	          main.type = "button";
	          main.innerHTML = `<span class="conv-title"></span><span class="conv-meta"></span>`;
	          main.querySelector(".conv-title").textContent = conv.title;
	          main.querySelector(".conv-meta").textContent = conv.model_name + " · " + formatTime(conv.updated_at);
	          main.addEventListener("click", () => selectConversation(conv.id));

	          const actions = document.createElement("div");
	          actions.className = "conv-actions";
	          const edit = document.createElement("button");
	          edit.className = "conv-action";
	          edit.type = "button";
	          edit.title = "重命名";
	          edit.textContent = "✎";
	          edit.addEventListener("click", () => startRenameConversation(conv.id));
	          const del = document.createElement("button");
	          del.className = "conv-action danger";
	          del.type = "button";
	          del.title = "删除";
	          del.textContent = "⌫";
	          del.addEventListener("click", () => deleteConversationById(conv.id));
	          actions.append(edit, del);
	          row.append(main, actions);
	        }
	        box.appendChild(row);
	      }
	    }

	    function startRenameConversation(id) {
	      state.editingConversationId = id;
	      renderConversations();
	    }

	    async function saveConversationTitle(id, title) {
	      const nextTitle = (title || "").trim();
	      if (!nextTitle) {
	        setStatus("chatStatus", "标题不能为空", "err");
	        return;
	      }
	      const res = await api(`/api/conversations/${id}`, {
	        method: "PATCH",
	        body: JSON.stringify({ title: nextTitle })
	      });
	      if (!res.ok) {
	        setStatus("chatStatus", "重命名失败", "err");
	        return;
	      }
	      state.editingConversationId = null;
	      const currentId = state.currentConversation?.id;
	      await loadConversations();
	      if (currentId) {
	        const updated = state.conversations.find((item) => item.id === currentId);
	        if (updated) {
	          state.currentConversation = updated;
	          updateChatHeader();
	          renderConversations();
	        }
	      }
	      setStatus("chatStatus", "");
	    }

    function formatTime(ts) {
      if (!ts) return "";
      const d = new Date(ts * 1000);
      return d.toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
    }

    async function newConversation(modelId = $("modelSelect").value) {
      if (!modelId && state.models[0]) modelId = state.models[0].id;
      if (!modelId) {
        setStatus("chatStatus", "先在模型管理里配置模型", "err");
        return null;
      }
      const res = await api("/api/conversations", { method: "POST", body: JSON.stringify({ model_id: modelId }) });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      state.currentConversation = data.conversation;
      state.messages = [];
      await loadConversations();
      updateChatHeader();
      renderMessages({ forceScroll: true });
      return state.currentConversation;
    }

	    async function selectConversation(id) {
	      state.editingConversationId = null;
	      const conv = state.conversations.find((item) => item.id === id);
	      if (!conv) return;
      state.currentConversation = conv;
      $("modelSelect").value = conv.model_id;
      updateChatHeader();
      renderConversations();
      const res = await api(`/api/conversations/${id}/messages`);
      const data = await res.json();
      state.messages = data.messages || [];
      renderMessages({ forceScroll: true });
      closeSidebar();
    }

    function updateChatHeader() {
      const conv = state.currentConversation;
      $("chatTitle").textContent = conv ? conv.title : "新对话";
      $("chatModel").textContent = conv ? (conv.model_name + " · " + conv.model) : "请选择模型";
      renderModelSelect();
    }

		    function renderEmpty() {
		      $("chatTitle").textContent = "新对话";
		      $("chatModel").textContent = state.models[0] ? "准备使用 " + state.models[0].name : "请选择模型";
	      const box = $("messages");
	      box.innerHTML = `
	        <div class="empty">
	          <div>
	            <h2>今天想聊什么？</h2>
	            <p>${state.models[0] ? state.models[0].name : "选择一个模型"} 已就绪</p>
	          </div>
	          <div class="prompt-grid">
	            <button class="prompt-card" data-prompt="帮我把这段话改得更清楚、更自然">
	              <strong>润色表达</strong>
	              <span>把想法整理成更顺的文字</span>
	            </button>
	            <button class="prompt-card" data-prompt="帮我规划一个周末家庭行程，轻松一点">
	              <strong>家庭计划</strong>
	              <span>安排出行、购物、做饭和休息</span>
	            </button>
	            <button class="prompt-card" data-prompt="用简单的话解释这个概念，并给一个生活例子">
	              <strong>解释一下</strong>
	              <span>把复杂问题讲得容易懂</span>
	            </button>
	            <button class="prompt-card" data-prompt="帮我写一份简洁的消息回复，语气礼貌">
	              <strong>快速回复</strong>
	              <span>生成微信、邮件或通知文案</span>
	            </button>
	          </div>
	        </div>`;
	      box.querySelectorAll(".prompt-card").forEach((button) => {
	        button.addEventListener("click", () => {
	          $("prompt").value = button.dataset.prompt || "";
	          autosizePrompt();
	          $("prompt").focus();
	        });
		      });
		    }

	    function escapeHTML(value) {
	      return String(value || "")
	        .replace(/&/g, "&amp;")
	        .replace(/</g, "&lt;")
	        .replace(/>/g, "&gt;")
	        .replace(/"/g, "&quot;")
	        .replace(/'/g, "&#39;");
	    }

	    function safeHref(value) {
	      const href = String(value || "").trim();
	      const lower = href.toLowerCase();
	      if (lower.startsWith("http://") || lower.startsWith("https://") || lower.startsWith("mailto:") || href.startsWith("/") || href.startsWith("#")) {
	        return href;
	      }
	      return "#";
	    }

	    function renderInlineMarkdown(value) {
	      const placeholders = [];
	      let text = String(value || "").replace(/`([^`\n]+)`/g, (_, code) => {
	        const token = "\u0000" + placeholders.length + "\u0000";
	        placeholders.push("<code>" + escapeHTML(code) + "</code>");
	        return token;
	      });
	      let html = escapeHTML(text);
	      html = html.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, href) => {
	        return '<a href="' + escapeHTML(safeHref(href)) + '" target="_blank" rel="noreferrer">' + label + "</a>";
	      });
	      html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
	      html = html.replace(/__([^_]+)__/g, "<strong>$1</strong>");
	      html = html.replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
	      html = html.replace(/(^|[^_])_([^_\n]+)_/g, "$1<em>$2</em>");
	      placeholders.forEach((item, index) => {
	        html = html.split("\u0000" + index + "\u0000").join(item);
	      });
	      return html;
	    }

	    function splitTableRow(line) {
	      return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
	    }

	    function isTableDivider(line) {
	      return /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$/.test(line || "");
	    }

	    function renderMarkdown(source) {
	      const lines = String(source || "").replace(/\r\n/g, "\n").split("\n");
	      const html = [];
	      let paragraph = [];
	      let listType = "";
	      let listItems = [];
	      let codeLang = "";
	      let codeLines = [];

	      function flushParagraph() {
	        if (!paragraph.length) return;
	        html.push("<p>" + renderInlineMarkdown(paragraph.join("\n")).replace(/\n/g, "<br>") + "</p>");
	        paragraph = [];
	      }

	      function flushList() {
	        if (!listItems.length) return;
	        const tag = listType === "ol" ? "ol" : "ul";
	        html.push("<" + tag + ">" + listItems.map((item) => "<li>" + renderInlineMarkdown(item) + "</li>").join("") + "</" + tag + ">");
	        listItems = [];
	        listType = "";
	      }

	      function flushCode() {
	        const className = codeLang ? ' class="language-' + escapeHTML(codeLang) + '"' : "";
	        html.push("<pre><code" + className + ">" + escapeHTML(codeLines.join("\n")) + "</code></pre>");
	        codeLines = [];
	        codeLang = "";
	      }

	      for (let i = 0; i < lines.length; i++) {
	        const line = lines[i];
	        const fence = line.match(/^```([A-Za-z0-9_-]+)?\s*$/);
	        if (codeLines.length || codeLang) {
	          if (fence) {
	            flushCode();
	          } else {
	            codeLines.push(line);
	          }
	          continue;
	        }
	        if (fence) {
	          flushParagraph();
	          flushList();
	          codeLang = fence[1] || "text";
	          codeLines = [];
	          continue;
	        }

	        if (!line.trim()) {
	          flushParagraph();
	          flushList();
	          continue;
	        }

	        if (line.includes("|") && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
	          flushParagraph();
	          flushList();
	          const headers = splitTableRow(line);
	          i += 2;
	          const rows = [];
	          while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
	            rows.push(splitTableRow(lines[i]));
	            i++;
	          }
	          i--;
	          html.push(
	            "<table><thead><tr>" +
	            headers.map((cell) => "<th>" + renderInlineMarkdown(cell) + "</th>").join("") +
	            "</tr></thead><tbody>" +
	            rows.map((row) => "<tr>" + row.map((cell) => "<td>" + renderInlineMarkdown(cell) + "</td>").join("") + "</tr>").join("") +
	            "</tbody></table>"
	          );
	          continue;
	        }

	        const heading = line.match(/^(#{1,3})\s+(.+)$/);
	        if (heading) {
	          flushParagraph();
	          flushList();
	          const level = heading[1].length;
	          html.push("<h" + level + ">" + renderInlineMarkdown(heading[2]) + "</h" + level + ">");
	          continue;
	        }

	        const quote = line.match(/^>\s?(.*)$/);
	        if (quote) {
	          flushParagraph();
	          flushList();
	          const parts = [quote[1]];
	          while (i + 1 < lines.length && /^>\s?/.test(lines[i + 1])) {
	            i++;
	            parts.push(lines[i].replace(/^>\s?/, ""));
	          }
	          html.push("<blockquote>" + renderInlineMarkdown(parts.join("\n")).replace(/\n/g, "<br>") + "</blockquote>");
	          continue;
	        }

	        const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
	        const ordered = line.match(/^\s*\d+\.\s+(.+)$/);
	        if (unordered || ordered) {
	          flushParagraph();
	          const nextType = ordered ? "ol" : "ul";
	          if (listType && listType !== nextType) flushList();
	          listType = nextType;
	          listItems.push((unordered || ordered)[1]);
	          continue;
	        }

	        flushList();
	        paragraph.push(line);
	      }
	      if (codeLines.length || codeLang) flushCode();
	      flushParagraph();
	      flushList();
	      return html.join("");
	    }

	    function formatMessageTime(value) {
	      const ts = Number(value || 0);
	      const date = ts > 0 ? new Date(ts * 1000) : new Date();
	      const pad = (num) => String(num).padStart(2, "0");
	      return pad(date.getHours()) + ":" + pad(date.getMinutes()) + ":" + pad(date.getSeconds());
	    }

	    function isNearBottom(box = $("messages")) {
	      return box.scrollHeight - box.scrollTop - box.clientHeight < 96;
	    }

	    function updateScrollLatestButton() {
	      const button = $("scrollLatest");
	      if (!button) return;
	      const awayFromBottom = !isNearBottom();
	      button.textContent = state.hasNewWhilePaused || state.sending ? "↓ 新内容" : "↓ 回到底部";
	      button.classList.toggle("show", awayFromBottom && state.messages.length > 0);
	    }

	    function scrollToLatest(behavior = "auto") {
	      const box = $("messages");
	      state.followOutput = true;
	      state.hasNewWhilePaused = false;
	      if (behavior === "smooth") {
	        state.programmaticScroll = true;
	        box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
	        setTimeout(() => {
	          state.programmaticScroll = false;
	          handleMessagesScroll();
	        }, 460);
	      } else {
	        box.scrollTop = box.scrollHeight;
	      }
	      updateScrollLatestButton();
	    }

	    function handleMessagesScroll() {
	      if (state.programmaticScroll) return;
	      if (isNearBottom()) {
	        state.followOutput = true;
	        state.hasNewWhilePaused = false;
	      } else {
	        state.followOutput = false;
	      }
	      updateScrollLatestButton();
	    }

	    function messageKey(message) {
	      if (!message._clientKey) {
	        Object.defineProperty(message, "_clientKey", {
	          value: "msg_" + (++state.messageSeq),
	          enumerable: false
	        });
	      }
	      return message._clientKey;
	    }

	    function createMessageElement(message) {
	      const wrap = document.createElement("article");
	      wrap.className = "bubble " + message.role;
	      wrap.dataset.messageKey = messageKey(message);

	      const role = document.createElement("div");
	      role.className = "role";
	      const shell = document.createElement("div");
	      shell.className = "bubble-shell";
	      const text = document.createElement("div");
	      text.className = "message-content";
	      const time = document.createElement("div");
	      time.className = "message-time";
	      const copy = document.createElement("button");
	      copy.className = "copy-btn";
	      copy.type = "button";
	      copy.title = "复制";
	      copy.textContent = "⧉";
	      copy.addEventListener("click", () => copyText(message.content || "", copy));

	      shell.append(text, copy);
	      wrap.append(role, shell, time);
	      updateMessageElement(wrap, message);
	      return wrap;
	    }

	    function updateMessageElement(wrap, message) {
	      wrap.className = "bubble " + message.role;
	      wrap.dataset.messageKey = messageKey(message);
	      const role = wrap.querySelector(".role");
	      const text = wrap.querySelector(".message-content");
	      const time = wrap.querySelector(".message-time");
	      const copy = wrap.querySelector(".copy-btn");
	      role.textContent = message.role === "user" ? "你" : (message.thinking ? "AI · 思考中" : "AI");
	      if (time) time.textContent = formatMessageTime(message.created_at);

	      if (message.role === "assistant" && message.thinking && !message.content) {
	        text.className = "message-content";
	        text.innerHTML = `
	          <div class="thinking">
	            <span class="thinking-dots"><span></span><span></span><span></span></span>
	            <span>AI 思考中</span>
	          </div>`;
	        copy.hidden = true;
	        return;
	      }

	      text.className = "message-content markdown";
	      text.innerHTML = renderMarkdown(message.content || "");
	      copy.hidden = !message.content;
	    }

	    function settleMessageScroll(previousTop, shouldFollow) {
	      if (shouldFollow) {
	        scrollToLatest("auto");
	      } else {
	        $("messages").scrollTop = previousTop;
	        state.hasNewWhilePaused = true;
	        updateScrollLatestButton();
	      }
	    }

	    function updateStreamingMessage(message) {
	      const box = $("messages");
	      const previousTop = box.scrollTop;
	      const shouldFollow = state.followOutput || isNearBottom(box);
	      let wrap = box.querySelector(`[data-message-key="${messageKey(message)}"]`);
	      if (!wrap) {
	        wrap = createMessageElement(message);
	        box.appendChild(wrap);
	      } else {
	        updateMessageElement(wrap, message);
	      }
	      settleMessageScroll(previousTop, shouldFollow);
	    }

	    function renderMessages(options = {}) {
	      const box = $("messages");
	      const previousTop = box.scrollTop;
	      const shouldFollow = Boolean(options.forceScroll) || state.followOutput || isNearBottom(box);
	      if (!state.messages.length) {
	        renderEmpty();
	        state.followOutput = true;
	        state.hasNewWhilePaused = false;
	        updateScrollLatestButton();
	        return;
	      }
	      const fragment = document.createDocumentFragment();
	      for (const msg of state.messages) {
	        fragment.appendChild(createMessageElement(msg));
	      }
	      box.replaceChildren(fragment);
	      settleMessageScroll(previousTop, shouldFollow);
	    }

	    async function copyText(text, button) {
	      const value = String(text || "");
	      if (!value) return;
	      if (await writeClipboard(value)) {
	        markCopied(button);
	        setStatus("chatStatus", "已复制", "ok");
	        return;
	      }
	      if (fallbackCopy(value)) {
	        markCopied(button);
	        setStatus("chatStatus", "已复制", "ok");
	        return;
	      }
	      openManualCopy(value);
	      setStatus("chatStatus", "浏览器限制了自动复制", "err");
	    }

	    async function writeClipboard(text) {
	      try {
	        if (!navigator.clipboard || !navigator.clipboard.writeText) return false;
	        await navigator.clipboard.writeText(text);
	        return true;
	      } catch {
	        return false;
	      }
	    }

	    function fallbackCopy(text) {
	      const textarea = document.createElement("textarea");
	      textarea.value = text;
	      textarea.setAttribute("readonly", "");
	      textarea.style.position = "fixed";
	      textarea.style.top = "-1000px";
	      textarea.style.left = "-1000px";
	      textarea.style.width = "1px";
	      textarea.style.height = "1px";
	      textarea.style.opacity = "0";
	      document.body.appendChild(textarea);
	      textarea.focus({ preventScroll: true });
	      textarea.select();
	      textarea.setSelectionRange(0, textarea.value.length);
	      let ok = false;
	      try {
	        ok = document.execCommand("copy");
	      } catch {
	        ok = false;
	      }
	      textarea.remove();
	      return ok;
	    }

	    function markCopied(button) {
	      if (!button) return;
	      const old = button.textContent;
	      button.textContent = "✓";
	      setTimeout(() => button.textContent = old, 900);
	    }

	    function openManualCopy(text) {
	      $("manualCopyText").value = text;
	      $("copyDialog").classList.add("show");
	      setTimeout(() => {
	        $("manualCopyText").focus();
	        $("manualCopyText").select();
	      }, 0);
	    }

	    function closeManualCopy() {
	      $("copyDialog").classList.remove("show");
	      $("manualCopyText").value = "";
	    }

	    function resetStreamState() {
	      if (state.streamTimer) clearTimeout(state.streamTimer);
	      state.streamMessage = null;
	      state.streamQueue = "";
	      state.streamTimer = null;
	      state.streamResolve = null;
	      state.firstTokenAt = null;
	    }

	    function enqueueAssistantText(message, piece) {
	      const text = String(piece || "");
	      if (!text) return;
	      if (message.thinking) {
	        message.thinking = false;
	        state.firstTokenAt = Date.now();
	        setStatus("chatStatus", "正在生成...", "");
	      }
	      if (state.streamMessage !== message) {
	        state.streamMessage = message;
	        state.streamQueue = "";
	      }
	      state.streamQueue += text;
	      if (!state.streamTimer) scheduleStreamTick();
	    }

	    function scheduleStreamTick() {
	      state.streamTimer = setTimeout(streamTick, 32);
	    }

	    function streamTick() {
	      const message = state.streamMessage;
	      if (!message) {
	        state.streamTimer = null;
	        resolveStreamDrain();
	        return;
	      }
	      if (!state.streamQueue) {
	        state.streamTimer = null;
	        resolveStreamDrain();
	        return;
	      }
	      const count = streamChunkSize(state.streamQueue.length);
	      message.content += state.streamQueue.slice(0, count);
	      state.streamQueue = state.streamQueue.slice(count);
	      updateStreamingMessage(message);
	      scheduleStreamTick();
	    }

	    function streamChunkSize(length) {
	      if (length > 1200) return 24;
	      if (length > 600) return 16;
	      if (length > 220) return 10;
	      if (length > 80) return 6;
	      return 3;
	    }

	    function resolveStreamDrain() {
	      if (state.streamResolve) {
	        const resolve = state.streamResolve;
	        state.streamResolve = null;
	        resolve();
	      }
	    }

	    function drainAssistantQueue() {
	      if (!state.streamQueue && !state.streamTimer) return Promise.resolve();
	      return new Promise((resolve) => {
	        state.streamResolve = resolve;
	      });
	    }

	    async function sendMessage() {
      const content = $("prompt").value.trim();
      if (!content || state.sending) return;
      let selectedModelId = $("modelSelect").value;
      if (!selectedModelId) return setStatus("chatStatus", "先选择模型", "err");

      if (!state.currentConversation || state.currentConversation.model_id !== selectedModelId) {
        await newConversation(selectedModelId);
      }
	      if (!state.currentConversation) return;

	      setStatus("chatStatus", "");
	      resetStreamState();
	      state.sending = true;
	      $("send").disabled = true;
	      $("webSearchToggle").disabled = true;
	      $("prompt").value = "";
	      autosizePrompt();
	      const sentAt = Math.floor(Date.now() / 1000);
	      state.messages.push({ role: "user", content, created_at: sentAt });
	      const assistant = { role: "assistant", content: "", thinking: true, created_at: sentAt };
	      state.messages.push(assistant);
	      state.followOutput = true;
	      state.hasNewWhilePaused = false;
	      renderMessages({ forceScroll: true });
	      const mode = state.searchConfig?.mode || "auto";
	      const useWebSearch = $("webSearchToggle").checked && !$("webSearchToggle").disabled;
	      const searchStatusText =
	        mode === "always" ? "正在联网搜索..." :
	        mode === "auto" ? (useWebSearch ? "正在联网搜索..." : "AI 思考中，必要时会自动联网...") :
	        (useWebSearch ? "正在联网搜索..." : "AI 思考中...");
	      setStatus("chatStatus", searchStatusText, "");

	      try {
	        const res = await api(`/api/conversations/${state.currentConversation.id}/messages`, {
	          method: "POST",
	          body: JSON.stringify({ content, web_search: useWebSearch })
	        });
        if (!res.ok) throw new Error(await res.text());
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split(/\r?\n/);
          buffer = lines.pop() || "";
          for (const line of lines) {
            if (!line.startsWith("data:")) continue;
            const payload = line.slice(5).trim();
            if (!payload || payload === "[DONE]") continue;
            try {
              const event = JSON.parse(payload);
	              const choice = event.choices?.[0] || {};
	              const piece = choice.delta?.content || choice.message?.content || "";
	              if (piece) {
	                enqueueAssistantText(assistant, piece);
	              }
	            } catch {}
	          }
	        }
	        assistant.thinking = false;
	        await drainAssistantQueue();
	        if (!assistant.content) {
	          assistant.content = "没有收到可显示的内容。";
	          updateStreamingMessage(assistant);
	        }
	        await loadConversations();
	        setStatus("chatStatus", "");
	      } catch (err) {
	        assistant.thinking = false;
	        enqueueAssistantText(assistant, "\n" + String(err.message || err));
	        await drainAssistantQueue();
	        setStatus("chatStatus", "发送失败", "err");
	      } finally {
	        if (assistant.thinking) {
	          assistant.thinking = false;
	          updateStreamingMessage(assistant);
	        }
	        state.sending = false;
	        $("send").disabled = false;
	        renderSearchToggle();
	        updateScrollLatestButton();
	        $("prompt").focus();
	      }
	    }

	    async function deleteCurrentConversation() {
	      if (!state.currentConversation) return;
	      await deleteConversationById(state.currentConversation.id);
	    }

	    async function deleteConversationById(id) {
	      const conv = state.conversations.find((item) => item.id === id);
	      if (!conv) return;
	      if (!confirm(`删除“${conv.title}”？`)) return;
	      await api(`/api/conversations/${id}`, { method: "DELETE" });
	      state.editingConversationId = null;
	      if (state.currentConversation?.id === id) {
	        state.currentConversation = null;
	        state.messages = [];
	      }
	      await loadConversations();
	      if (!state.currentConversation) renderEmpty();
	    }

	    function openSettings() {
	      $("drawerMask").classList.add("show");
	      $("settingsDrawer").classList.add("show");
	      loadAdminModels();
	      loadAdminSearch();
	    }

    function closeSettings() {
      $("drawerMask").classList.remove("show");
      $("settingsDrawer").classList.remove("show");
    }

	    async function loadAdminModels() {
	      if (!$("adminKey").value.trim()) {
	        setStatus("adminStatus", "填入管理密钥后加载模型", "");
	        return;
      }
      const res = await adminApi("/api/admin/models");
      if (!res.ok) {
        setStatus("adminStatus", "管理密钥无效", "err");
        return;
      }
      setStatus("adminStatus", "管理密钥有效", "ok");
	      const data = await res.json();
	      renderAdminModels(data.models || []);
	    }

	    async function loadAdminSearch() {
	      if (!$("adminKey").value.trim()) {
	        setStatus("searchStatus", "填入管理密钥后加载搜索配置", "");
	        return;
	      }
	      const res = await adminApi("/api/admin/search");
	      if (!res.ok) {
	        setStatus("searchStatus", "管理密钥无效", "err");
	        return;
	      }
	      const data = await res.json();
	      const search = data.search || {};
	      $("searchProvider").value = search.provider || "tavily";
	      $("searchEnabled").value = search.enabled ? "1" : "0";
	      $("searchMode").value = search.mode || "auto";
	      $("searchDepth").value = search.depth || "advanced";
	      $("searchResultCount").value = search.result_count || 5;
	      $("searchApiKey").value = "";
	      $("searchApiKey").placeholder = search.has_api_key ? "已保存，留空保持原值" : "请输入搜索 API Key";
	      setStatus("searchStatus", search.has_api_key ? "搜索 Key 已保存；日期会自动按当天注入" : "尚未配置搜索 Key", search.has_api_key ? "ok" : "");
	    }

	    async function saveSearchConfig(clearKey = false) {
	      const body = {
	        provider: $("searchProvider").value,
	        enabled: $("searchEnabled").value === "1",
	        mode: $("searchMode").value,
	        depth: $("searchDepth").value,
	        result_count: Number($("searchResultCount").value || 5),
	        api_key: $("searchApiKey").value.trim(),
	        clear_api_key: clearKey
	      };
	      const res = await adminApi("/api/admin/search", {
	        method: "POST",
	        body: JSON.stringify(body)
	      });
	      if (!res.ok) {
	        setStatus("searchStatus", await res.text(), "err");
	        return;
	      }
	      $("searchApiKey").value = "";
	      setStatus("searchStatus", clearKey ? "搜索 Key 已清空" : "搜索配置已保存", "ok");
	      await loadAdminSearch();
	      await loadSearchConfig();
	    }

	    function renderAdminModels(models) {
      const box = $("adminModelList");
      box.innerHTML = "";
      if (!models.length) {
        box.innerHTML = '<div class="status">暂无模型</div>';
        return;
      }
      for (const model of models) {
        const row = document.createElement("div");
        row.className = "model-row";
        const info = document.createElement("div");
        info.innerHTML = `<strong></strong><span></span>`;
        info.querySelector("strong").textContent = model.name + (model.enabled ? "" : "（停用）");
        info.querySelector("span").textContent = model.model + " · " + model.base_url + (model.has_api_key ? " · Key 已保存" : " · 未配置 Key");
        const actions = document.createElement("div");
        actions.style.display = "flex";
        actions.style.gap = "6px";
        const edit = document.createElement("button");
        edit.textContent = "编辑";
        edit.addEventListener("click", () => fillModelForm(model));
        const del = document.createElement("button");
        del.className = "danger";
        del.textContent = "删除";
        del.addEventListener("click", () => deleteModel(model.id));
        actions.append(edit, del);
        row.append(info, actions);
        box.appendChild(row);
      }
    }

    function fillModelForm(model) {
      $("editingModelId").value = model.id;
      $("modelName").value = model.name || "";
      $("provider").value = model.provider || "";
      $("baseUrl").value = model.base_url || "";
      $("modelCode").value = model.model || "";
      $("apiKey").value = "";
      $("apiKey").placeholder = model.has_api_key ? "已保存，留空保持原值" : "请输入 API Key";
      $("systemPrompt").value = model.system_prompt || "";
      $("enabled").value = model.enabled ? "1" : "0";
      setStatus("modelStatus", "正在编辑：" + model.name, "");
    }

    function resetModelForm() {
      for (const id of ["editingModelId","modelName","provider","baseUrl","modelCode","apiKey","systemPrompt"]) $(id).value = "";
      $("enabled").value = "1";
      $("apiKey").placeholder = "留空则保持原值";
      setStatus("modelStatus", "");
    }

    async function saveModel() {
      const id = $("editingModelId").value;
      const body = {
        name: $("modelName").value.trim(),
        provider: $("provider").value.trim(),
        base_url: $("baseUrl").value.trim(),
        model: $("modelCode").value.trim(),
        api_key: $("apiKey").value.trim(),
        system_prompt: $("systemPrompt").value.trim(),
        enabled: $("enabled").value === "1"
      };
      const res = await adminApi(id ? `/api/admin/models/${id}` : "/api/admin/models", {
        method: id ? "PUT" : "POST",
        body: JSON.stringify(body)
      });
      if (!res.ok) {
        setStatus("modelStatus", await res.text(), "err");
        return;
      }
      resetModelForm();
      setStatus("modelStatus", "模型已保存", "ok");
      await loadAdminModels();
      await loadModels();
    }

    async function deleteModel(id) {
      if (!confirm("删除这个模型？已有对话会保留，但模型会停用。")) return;
      const res = await adminApi(`/api/admin/models/${id}`, { method: "DELETE" });
      if (!res.ok) {
        setStatus("modelStatus", await res.text(), "err");
        return;
      }
      await loadAdminModels();
      await loadModels();
    }

    async function changePassword() {
      const password = $("familyPassword").value;
      const res = await adminApi("/api/admin/password", {
        method: "POST",
        body: JSON.stringify({ password })
      });
      if (!res.ok) {
        setStatus("adminStatus", await res.text(), "err");
        return;
      }
      $("familyPassword").value = "";
      setStatus("adminStatus", "登录密码已修改，需要重新登录", "ok");
    }

    function openSidebar() {
      $("sidebar").classList.add("show");
      $("drawerMask").classList.add("show");
    }
    function closeSidebar() {
      $("sidebar").classList.remove("show");
      if (!$("settingsDrawer").classList.contains("show")) $("drawerMask").classList.remove("show");
    }
    function autosizePrompt() {
      const el = $("prompt");
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 180) + "px";
    }

    $("loginForm").addEventListener("submit", login);
    $("logout").addEventListener("click", logout);
    $("newChat").addEventListener("click", () => newConversation());
    $("refreshConversations").addEventListener("click", loadConversations);
    $("send").addEventListener("click", sendMessage);
    $("deleteConversation").addEventListener("click", deleteCurrentConversation);
    $("messages").addEventListener("scroll", handleMessagesScroll, { passive: true });
    $("scrollLatest").addEventListener("click", () => scrollToLatest("smooth"));
    $("prompt").addEventListener("input", autosizePrompt);
    $("prompt").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
      }
    });
    $("openSettings").addEventListener("click", openSettings);
    $("closeSettings").addEventListener("click", closeSettings);
    $("drawerMask").addEventListener("click", () => { closeSettings(); closeSidebar(); });
    $("saveModel").addEventListener("click", saveModel);
    $("resetModelForm").addEventListener("click", resetModelForm);
	    $("changePassword").addEventListener("click", changePassword);
	    $("adminKey").addEventListener("change", () => {
	      loadAdminModels();
	      loadAdminSearch();
	    });
	    $("openSide").addEventListener("click", openSidebar);
	    $("closeSide").addEventListener("click", closeSidebar);
	    $("webSearchToggle").addEventListener("change", () => {
	      if ((state.searchConfig?.mode || "auto") === "manual") {
	        localStorage.setItem("aiPlatformWebSearch", $("webSearchToggle").checked ? "1" : "0");
	      }
	    });
	    $("saveSearch").addEventListener("click", () => saveSearchConfig(false));
	    $("clearSearchKey").addEventListener("click", () => saveSearchConfig(true));
	    $("closeCopyDialog").addEventListener("click", closeManualCopy);
	    $("copyDialog").addEventListener("click", (event) => {
	      if (event.target === $("copyDialog")) closeManualCopy();
	    });
	    $("selectManualCopy").addEventListener("click", () => {
	      $("manualCopyText").focus();
	      $("manualCopyText").select();
	    });
	    $("retryManualCopy").addEventListener("click", async () => {
	      const text = $("manualCopyText").value;
	      if (await writeClipboard(text) || fallbackCopy(text)) {
	        closeManualCopy();
	        setStatus("chatStatus", "已复制", "ok");
	      }
	    });

	    bootstrap();
  </script>
</body>
</html>'''


if __name__ == "__main__":
    main()
