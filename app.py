#!/usr/bin/env python3
import base64
import hashlib
import hmac
import io
import json
import mimetypes
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
from urllib.parse import unquote, urlencode, urlparse


DATA_DIR = Path(os.environ.get("AI_PLATFORM_DATA", "/opt/ai-platform"))
APP_DIR = Path(__file__).resolve().parent
RES_DIR = APP_DIR / "res"
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
              reasoning_content TEXT NOT NULL DEFAULT '',
              prompt_tokens INTEGER NOT NULL DEFAULT 0,
              completion_tokens INTEGER NOT NULL DEFAULT 0,
              total_tokens INTEGER NOT NULL DEFAULT 0,
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

            CREATE TABLE IF NOT EXISTS prompt_templates (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              content TEXT NOT NULL,
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS favorite_messages (
              id TEXT PRIMARY KEY,
              message_id INTEGER NOT NULL UNIQUE,
              conversation_id TEXT NOT NULL,
              conversation_title TEXT NOT NULL,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              message_created_at INTEGER NOT NULL,
              created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
              token_hash TEXT PRIMARY KEY,
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL
            );
            """
        )

        message_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "reasoning_content" not in message_columns:
            conn.execute(
                "ALTER TABLE messages ADD COLUMN reasoning_content TEXT NOT NULL DEFAULT ''"
            )
        for column in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if column not in message_columns:
                conn.execute(
                    f"ALTER TABLE messages ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
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

        prompt_count = conn.execute("SELECT COUNT(*) AS n FROM prompt_templates").fetchone()["n"]
        if prompt_count == 0:
            ts = now()
            for index, (title, content) in enumerate(DEFAULT_PROMPT_TEMPLATES, 1):
                conn.execute(
                    """
                    INSERT INTO prompt_templates(id, title, content, sort_order, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (b64_token(10), title, content, index * 10, ts, ts),
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


DEFAULT_PROMPT_TEMPLATES = [
    ("润色文字", "帮我润色这段文字，让它更自然、更正式"),
    ("朋友圈文案", "帮我写一段朋友圈文案，语气自然一点"),
    ("工作通知", "帮我写一份工作通知，简洁清楚"),
    ("活动宣传", "帮我写一段活动宣传文案，有吸引力但不要太夸张"),
    ("更礼貌表达", "帮我把这段话改得更礼貌"),
    ("工作总结", "帮我生成一份工作总结"),
    ("整理要点", "帮我把内容整理成条理清晰的要点"),
]


def prompt_template_row(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def favorite_row(row):
    archived = bool(row["conversation_archived"]) if "conversation_archived" in row.keys() else False
    live_title = row["live_conversation_title"] if "live_conversation_title" in row.keys() else ""
    original_title = row["conversation_title"]
    return {
        "id": row["id"],
        "message_id": row["message_id"],
        "conversation_id": row["conversation_id"],
        "conversation_title": "原会话已删除" if archived or not live_title else live_title,
        "original_conversation_title": original_title,
        "role": row["role"],
        "content": row["content"],
        "message_created_at": row["message_created_at"],
        "created_at": row["created_at"],
    }


def message_token_usage(row):
    prompt_tokens = int(row["prompt_tokens"] or 0) if "prompt_tokens" in row.keys() else 0
    completion_tokens = (
        int(row["completion_tokens"] or 0) if "completion_tokens" in row.keys() else 0
    )
    total_tokens = int(row["total_tokens"] or 0) if "total_tokens" in row.keys() else 0
    if not total_tokens and (prompt_tokens or completion_tokens):
        total_tokens = prompt_tokens + completion_tokens
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def parse_usage_tokens(usage):
    if not isinstance(usage, dict):
        return (0, 0, 0)

    def read_int(*keys):
        for key in keys:
            value = usage.get(key)
            if value is None:
                continue
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                continue
        return 0

    prompt_tokens = read_int("prompt_tokens", "input_tokens")
    completion_tokens = read_int("completion_tokens", "output_tokens")
    total_tokens = read_int("total_tokens")
    if not total_tokens and (prompt_tokens or completion_tokens):
        total_tokens = prompt_tokens + completion_tokens
    return (prompt_tokens, completion_tokens, total_tokens)


def usage_option_rejected(detail):
    text = str(detail or "").lower()
    return bool(
        "stream_options" in text
        or "include_usage" in text
        or "unknown field" in text
        or "extra inputs are not permitted" in text
        or "unsupported parameter" in text
    )


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


def public_sources(results):
    sources = []
    for index, item in enumerate(results or [], 1):
        sources.append(
            {
                "title": item.get("title") or f"来源 {index}",
                "url": item.get("url") or "",
                "snippet": item.get("snippet") or "",
                "position": index,
            }
        )
    return sources


def split_think_blocks(content):
    text = str(content or "")
    reasoning_parts = []

    def collect(match):
        value = (match.group(1) or "").strip()
        if value:
            reasoning_parts.append(value)
        return ""

    cleaned = re.sub(
        r"<think>\s*(.*?)\s*</think>",
        collect,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    return cleaned, "\n\n".join(reasoning_parts).strip()


class AppHandler(BaseHTTPRequestHandler):
    server_version = "AIPlatform/2.0"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {self.command} {self.path} - {fmt % args}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self.html(INDEX_HTML)
        if path == "/favicon.ico":
            return self.static_file(RES_DIR / "favicon.ico")
        if path.startswith("/res/"):
            return self.handle_res_file(path)
        if path == "/api/health":
            return self.json({"status": "ok", "time": iso_now()})
        if path == "/api/me":
            return self.handle_me()
        if path == "/api/models":
            return self.require_user(self.handle_models)
        if path == "/api/search-config":
            return self.require_user(self.handle_search_config)
        if path == "/api/prompts":
            return self.require_user(self.handle_prompts)
        if path == "/api/favorites":
            return self.require_user(self.handle_favorites)
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
        if path == "/api/prompts":
            return self.require_user(self.handle_prompts)
        if path == "/api/favorites":
            return self.require_user(self.handle_favorites)
        if path == "/api/conversations":
            return self.require_user(self.handle_conversations)
        if path.startswith("/api/conversations/") and path.endswith("/messages"):
            return self.require_user(self.handle_send_message)
        return self.error(HTTPStatus.NOT_FOUND, "not found")

    def do_PUT(self):
        path = urlparse(self.path).path
        if path.startswith("/api/admin/models/"):
            return self.require_admin(self.handle_admin_model_item)
        if path.startswith("/api/prompts/"):
            return self.require_user(self.handle_prompt_item)
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
        if path.startswith("/api/prompts/"):
            return self.require_user(self.handle_prompt_item)
        if path.startswith("/api/favorites/message/"):
            return self.require_user(self.handle_favorite_by_message)
        if path.startswith("/api/favorites/"):
            return self.require_user(self.handle_favorite_item)
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
        self.send_header("Cache-Control", "public, max-age=86400")
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

    def handle_prompts(self):
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM prompt_templates
                    ORDER BY sort_order ASC, updated_at DESC
                    LIMIT 300
                    """
                ).fetchall()
            return self.json({"prompts": [prompt_template_row(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        title = str(data.get("title") or "").strip()[:80]
        content = str(data.get("content") or "").strip()
        sort_order = clamp_int(data.get("sort_order"), 100, -100000, 100000)
        if not title or not content:
            return self.error(HTTPStatus.BAD_REQUEST, "title and content are required")
        if len(content) > 4000:
            return self.error(HTTPStatus.BAD_REQUEST, "content too long")

        prompt_id = b64_token(10)
        ts = now()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO prompt_templates(id, title, content, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (prompt_id, title, content, sort_order, ts, ts),
            )
            row = conn.execute("SELECT * FROM prompt_templates WHERE id=?", (prompt_id,)).fetchone()
        return self.json({"prompt": prompt_template_row(row)}, HTTPStatus.CREATED)

    def prompt_id_from_path(self):
        return urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]

    def handle_prompt_item(self):
        prompt_id = self.prompt_id_from_path()
        with db() as conn:
            row = conn.execute("SELECT * FROM prompt_templates WHERE id=?", (prompt_id,)).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "prompt not found")

            if self.command == "DELETE":
                conn.execute("DELETE FROM prompt_templates WHERE id=?", (prompt_id,))
                return self.json({"ok": True})

            try:
                data = self.read_body()
            except Exception:
                return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
            title = str(data.get("title", row["title"]) or "").strip()[:80]
            content = str(data.get("content", row["content"]) or "").strip()
            sort_order = clamp_int(data.get("sort_order", row["sort_order"]), row["sort_order"], -100000, 100000)
            if not title or not content:
                return self.error(HTTPStatus.BAD_REQUEST, "title and content are required")
            if len(content) > 4000:
                return self.error(HTTPStatus.BAD_REQUEST, "content too long")
            conn.execute(
                """
                UPDATE prompt_templates
                SET title=?, content=?, sort_order=?, updated_at=?
                WHERE id=?
                """,
                (title, content, sort_order, now(), prompt_id),
            )
            row = conn.execute("SELECT * FROM prompt_templates WHERE id=?", (prompt_id,)).fetchone()
        return self.json({"prompt": prompt_template_row(row)})

    def handle_favorites(self):
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT f.*,
                           c.title AS live_conversation_title,
                           COALESCE(c.archived, 1) AS conversation_archived
                    FROM favorite_messages f
                    LEFT JOIN conversations c ON c.id = f.conversation_id
                    ORDER BY f.created_at DESC
                    LIMIT 300
                    """
                ).fetchall()
            return self.json({"favorites": [favorite_row(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            message_id = int(data.get("message_id") or 0)
        except (TypeError, ValueError):
            message_id = 0
        if message_id <= 0:
            return self.error(HTTPStatus.BAD_REQUEST, "message_id required")

        with db() as conn:
            existing = conn.execute(
                """
                SELECT f.*,
                       c.title AS live_conversation_title,
                       COALESCE(c.archived, 1) AS conversation_archived
                FROM favorite_messages f
                LEFT JOIN conversations c ON c.id = f.conversation_id
                WHERE f.message_id=?
                """,
                (message_id,),
            ).fetchone()
            if existing:
                return self.json({"favorite": favorite_row(existing)})

            message = conn.execute(
                """
                SELECT m.id, m.conversation_id, m.role, m.content, m.created_at,
                       c.title AS conversation_title
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.id=?
                """,
                (message_id,),
            ).fetchone()
            if not message:
                return self.error(HTTPStatus.NOT_FOUND, "message not found")
            if message["role"] != "assistant":
                return self.error(HTTPStatus.BAD_REQUEST, "only assistant messages can be favorited")

            favorite_id = b64_token(10)
            ts = now()
            conn.execute(
                """
                INSERT INTO favorite_messages
                (id, message_id, conversation_id, conversation_title, role, content, message_created_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    favorite_id,
                    message["id"],
                    message["conversation_id"],
                    message["conversation_title"],
                    message["role"],
                    message["content"],
                    message["created_at"],
                    ts,
                ),
            )
            row = conn.execute(
                """
                SELECT f.*,
                       c.title AS live_conversation_title,
                       COALESCE(c.archived, 1) AS conversation_archived
                FROM favorite_messages f
                LEFT JOIN conversations c ON c.id = f.conversation_id
                WHERE f.id=?
                """,
                (favorite_id,),
            ).fetchone()
        return self.json({"favorite": favorite_row(row)}, HTTPStatus.CREATED)

    def favorite_id_from_path(self):
        return urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]

    def handle_favorite_item(self):
        favorite_id = self.favorite_id_from_path()
        with db() as conn:
            row = conn.execute("SELECT id FROM favorite_messages WHERE id=?", (favorite_id,)).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "favorite not found")
            conn.execute("DELETE FROM favorite_messages WHERE id=?", (favorite_id,))
        return self.json({"ok": True})

    def handle_favorite_by_message(self):
        try:
            message_id = int(self.favorite_id_from_path())
        except (TypeError, ValueError):
            message_id = 0
        if message_id <= 0:
            return self.error(HTTPStatus.BAD_REQUEST, "message_id required")
        with db() as conn:
            conn.execute("DELETE FROM favorite_messages WHERE message_id=?", (message_id,))
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
                SELECT id, role, content, reasoning_content,
                       prompt_tokens, completion_tokens, total_tokens,
                       created_at
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
            favorites = conn.execute(
                """
                SELECT id, message_id
                FROM favorite_messages
                WHERE message_id IN (
                  SELECT id FROM messages WHERE conversation_id=?
                )
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
        favorite_by_message = {row["message_id"]: row["id"] for row in favorites}
        return self.json(
            {
                "messages": [
                    {
                        "id": row["id"],
                        "role": row["role"],
                        "content": row["content"],
                        "reasoning_content": row["reasoning_content"],
                        "created_at": row["created_at"],
                        "usage": message_token_usage(row),
                        "sources": sources_by_message.get(row["id"], []),
                        "favorite_id": favorite_by_message.get(row["id"]),
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

        def make_payload(results, include_usage=True):
            upstream_messages = [
                {"role": "system", "content": build_runtime_context(bool(results))}
            ]
            if convo["system_prompt"].strip():
                upstream_messages.append(
                    {"role": "system", "content": convo["system_prompt"].strip()}
                )
            if results:
                upstream_messages.append(
                    {"role": "system", "content": build_search_context(results)}
                )
            upstream_messages.extend(
                {"role": row["role"], "content": row["content"]} for row in history
            )
            payload = {
                "model": convo["model"],
                "messages": upstream_messages,
                "stream": True,
            }
            if include_usage:
                payload["stream_options"] = {"include_usage": True}
            return payload

        def open_upstream(payload):
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
            return urllib.request.urlopen(request, timeout=120)

        def open_upstream_with_usage_fallback(results):
            payload = make_payload(results, include_usage=True)
            try:
                return open_upstream(payload)
            except urllib.error.HTTPError as exc:
                detail = exc.read(65536).decode(errors="replace")
                if exc.code == 400 and usage_option_rejected(detail):
                    payload = make_payload(results, include_usage=False)
                    return open_upstream(payload)
                raise urllib.error.HTTPError(
                    exc.url, exc.code, exc.reason, exc.headers, io.BytesIO(detail.encode())
                )

        payload = make_payload(search_results)
        search_fallback_notice = ""

        try:
            response = open_upstream_with_usage_fallback(search_results)
        except urllib.error.HTTPError as exc:
            detail = exc.read(65536).decode(errors="replace")
            if search_results and exc.code == 400 and "data_inspection_failed" in detail:
                search_results = []
                payload = make_payload(search_results)
                search_fallback_notice = "（联网资料被上游安全策略拦截，本次先按普通模式回答。）\n\n"
                try:
                    response = open_upstream_with_usage_fallback(search_results)
                except urllib.error.HTTPError as retry_exc:
                    retry_detail = retry_exc.read(65536).decode(errors="replace")
                    message = (
                        "upstream content rejected"
                        if "data_inspection_failed" in retry_detail
                        else f"upstream status {retry_exc.code}"
                    )
                    return self.error(HTTPStatus.BAD_GATEWAY, message, retry_detail)
                except Exception as retry_exc:
                    return self.error(
                        HTTPStatus.BAD_GATEWAY, "upstream request failed", str(retry_exc)
                    )
            else:
                message = (
                    "upstream content rejected"
                    if "data_inspection_failed" in detail
                    else f"upstream status {exc.code}"
                )
                return self.error(HTTPStatus.BAD_GATEWAY, message, detail)
        except Exception as exc:
            return self.error(HTTPStatus.BAD_GATEWAY, "upstream request failed", str(exc))

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        if search_results:
            search_event = {
                "type": "search_status",
                "status": "done",
                "count": len(search_results),
                "sources": public_sources(search_results),
            }
            try:
                self.wfile.write(
                    ("data: " + json.dumps(search_event, ensure_ascii=False) + "\n\n").encode()
                )
                self.wfile.flush()
            except Exception:
                pass

        assistant_parts = []
        reasoning_parts = []
        usage_data = None
        if search_fallback_notice:
            notice_event = {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": search_fallback_notice},
                        "finish_reason": None,
                    }
                ]
            }
            try:
                self.wfile.write(
                    ("data: " + json.dumps(notice_event, ensure_ascii=False) + "\n\n").encode()
                )
                self.wfile.flush()
                assistant_parts.append(search_fallback_notice)
            except Exception:
                pass
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
                    if isinstance(event.get("usage"), dict):
                        usage_data = event.get("usage")
                    choice = (event.get("choices") or [{}])[0]
                    if isinstance(choice.get("usage"), dict):
                        usage_data = choice.get("usage")
                    delta = choice.get("delta") or {}
                    message = choice.get("message") or {}
                    piece = delta.get("content") or message.get("content") or ""
                    reasoning_piece = (
                        delta.get("reasoning_content")
                        or message.get("reasoning_content")
                        or delta.get("reasoning")
                        or message.get("reasoning")
                        or delta.get("thinking")
                        or message.get("thinking")
                        or ""
                    )
                    if reasoning_piece:
                        reasoning_parts.append(str(reasoning_piece))
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
        reasoning_text = "".join(reasoning_parts).strip()
        assistant_text, think_reasoning = split_think_blocks(assistant_text)
        if think_reasoning:
            reasoning_text = (reasoning_text + "\n\n" + think_reasoning).strip()
        prompt_tokens, completion_tokens, total_tokens = parse_usage_tokens(usage_data)
        if assistant_text:
            with db() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO messages(
                      conversation_id, role, content, reasoning_content,
                      prompt_tokens, completion_tokens, total_tokens, created_at
                    )
                    VALUES (?, 'assistant', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        conversation_id,
                        assistant_text,
                        reasoning_text,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                        now(),
                    ),
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
            saved_event = {
                "type": "message_saved",
                "message_id": message_id,
                "conversation_id": conversation_id,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                },
            }
            try:
                self.wfile.write(
                    ("data: " + json.dumps(saved_event, ensure_ascii=False) + "\n\n").encode()
                )
                self.wfile.flush()
            except Exception:
                pass


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
  <link rel="icon" href="/favicon.ico" sizes="any">
  <link rel="icon" type="image/png" sizes="16x16" href="/res/favicon-16.png">
  <link rel="icon" type="image/png" sizes="32x32" href="/res/favicon-32.png">
  <link rel="icon" type="image/png" sizes="64x64" href="/res/favicon-64.png">
  <style>
    :root {
      color-scheme: light;
      --bg: #FAF8F4;
      --bg-elevated: #fffdf9;
      --sidebar: #fff8f4;
      --sidebar-strong: #F6E9D6;
      --surface: #ffffff;
      --surface-soft: #F6E9D6;
      --surface-strong: #edd8c8;
      --line: #eadfd2;
      --line-strong: #d6bdab;
      --text: #1f2428;
      --muted: #8A6D5A;
      --muted-2: #b59a87;
      --accent: #E9AFC0;
      --accent-strong: #D98FA8;
      --accent-soft: #FCE8EF;
      --accent-shadow: rgba(217, 143, 168, .22);
      --focus-ring: rgba(217, 143, 168, .18);
      --user-bg: #fff0f6;
      --user-line: #edc0cd;
      --user-shadow: rgba(217, 143, 168, .12);
      --assistant-bg: #ffffff;
      --code-bg: #15201f;
      --code-text: #f3f7f5;
      --green: #16845f;
      --red: #c2413d;
      --yellow: #946300;
      --shadow: 0 18px 46px rgba(46, 41, 32, .12);
      --soft-shadow: 0 8px 24px rgba(46, 41, 32, .08);
      --radius: 8px;
      --content: 900px;
    }
    [data-theme="dark"] {
      color-scheme: dark;
      --bg: #151817;
      --bg-elevated: #1c211f;
      --sidebar: #191d1c;
      --sidebar-strong: #252b29;
      --surface: #202624;
      --surface-soft: #252c2a;
      --surface-strong: #303936;
      --line: #343c39;
      --line-strong: #4a5551;
      --text: #edf2ef;
      --muted: #a8b2ad;
      --muted-2: #78847e;
      --accent: #f0a9bc;
      --accent-strong: #ffc0cf;
      --accent-soft: #3b2630;
      --accent-shadow: rgba(240, 169, 188, .22);
      --focus-ring: rgba(240, 169, 188, .22);
      --user-bg: #3a2632;
      --user-line: #674055;
      --user-shadow: rgba(0, 0, 0, .2);
      --assistant-bg: #202624;
      --code-bg: #0f1413;
      --code-text: #edf2ef;
      --green: #7bcfa8;
      --red: #f08a84;
      --yellow: #e7bf6a;
      --shadow: 0 20px 48px rgba(0, 0, 0, .34);
      --soft-shadow: 0 8px 24px rgba(0, 0, 0, .24);
    }
    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    html, body { height: 100%; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif;
      -webkit-font-smoothing: antialiased;
      overflow-x: hidden;
    }
    button, input, textarea, select { font: inherit; }
    button, select {
      min-height: 40px;
      border: 1px solid transparent;
      border-radius: 8px;
      background: transparent;
      color: var(--text);
      padding: 0 13px;
      cursor: pointer;
      transition: background .16s ease, border-color .16s ease, transform .12s ease, box-shadow .16s ease;
    }
    button:hover, select:hover { background: var(--surface-soft); }
    button:active { transform: translateY(1px); }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #fff;
      box-shadow: 0 8px 20px var(--accent-shadow);
    }
    button.primary:hover { background: var(--accent-strong); }
    button.primary.danger {
      background: var(--red);
      border-color: var(--red);
      color: #fff;
      box-shadow: 0 8px 20px rgba(194, 65, 61, .18);
    }
    button.ghost { background: transparent; }
    button.icon {
      width: 40px;
      min-width: 40px;
      padding: 0;
      display: grid;
      place-items: center;
      font-weight: 700;
    }
    button.accent-toggle {
      color: var(--accent);
      font-size: 18px;
      line-height: 1;
    }
    button.danger { color: var(--red); }
    button.soft {
      background: var(--surface-soft);
      border-color: var(--line);
    }
    button:disabled { opacity: .5; cursor: not-allowed; transform: none; box-shadow: none; }
    input, textarea {
      width: 100%;
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--text);
      padding: 10px 12px;
      outline: none;
      transition: border-color .16s ease, box-shadow .16s ease, background .16s ease;
    }
    textarea { resize: vertical; }
    input:focus, textarea:focus, select:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px var(--focus-ring);
      outline: none;
    }
    .login {
      min-height: 100%;
      display: grid;
      place-items: center;
      padding: 20px;
      background:
        radial-gradient(circle at 50% 8%, color-mix(in srgb, var(--accent-soft) 70%, transparent), transparent 34%),
        linear-gradient(180deg, var(--bg-elevated), var(--bg));
    }
    .login-panel {
      width: min(460px, 100%);
      border: 1px solid color-mix(in srgb, var(--line) 80%, transparent);
      border-radius: 28px;
      background: var(--surface);
      box-shadow: var(--shadow);
      padding: 22px;
      display: grid;
      gap: 14px;
      overflow: hidden;
    }
    .login-mascot {
      width: 100%;
      border-radius: 24px;
      display: block;
      background: var(--accent-soft);
      box-shadow: 0 14px 34px rgba(217, 143, 168, .14);
    }
    .login-copy {
      display: grid;
      gap: 4px;
      text-align: center;
      padding: 2px 4px 4px;
    }
    .login-panel h1 { margin: 0; font-size: 30px; letter-spacing: 0; }
    .login-panel p { margin: 0; color: var(--muted); font-size: 16px; }
    .login-panel label {
      font-weight: 680;
      color: var(--muted);
    }
    .app {
      height: 100vh;
      min-height: 100vh;
      display: grid;
      grid-template-columns: 304px minmax(0, 1fr);
      overflow: hidden;
      background: var(--bg);
    }
    .sidebar {
      border-right: 1px solid var(--line);
      background: var(--sidebar);
      display: grid;
      grid-template-rows: auto auto auto 1fr auto;
      height: 100vh;
      min-height: 0;
      min-width: 0;
      overflow: hidden;
    }
    .side-head {
      padding: 18px 14px 12px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }
    .brand h1 {
      margin: 0;
      font-size: 18px;
      letter-spacing: 0;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .brand h1 .app-version {
      display: inline-flex;
      align-items: center;
      min-height: 20px;
      padding: 0 7px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--surface-soft);
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      line-height: 1;
    }
    .brand span { display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }
    .side-actions {
      padding: 0 12px 12px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
    }
    .side-actions .primary {
      justify-content: flex-start;
      box-shadow: none;
    }
    .side-section-title {
      padding: 2px 16px 8px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    .side-empty {
      margin: 10px 4px;
      padding: 14px;
      border: 1px dashed var(--line);
      border-radius: 8px;
      color: var(--muted);
      background: var(--surface);
      font-size: 13px;
      line-height: 1.6;
    }
    .loading-line {
      height: 14px;
      border-radius: 999px;
      background: linear-gradient(90deg, var(--surface-soft), var(--surface-strong), var(--surface-soft));
      background-size: 180% 100%;
      animation: loadingShimmer 1.1s infinite linear;
    }
    @keyframes loadingShimmer {
      from { background-position: 120% 0; }
      to { background-position: -80% 0; }
    }
    .conversation-list {
      overflow: auto;
      min-height: 0;
      padding: 0 10px 14px;
      overscroll-behavior: contain;
      scrollbar-gutter: stable;
    }
    .conv {
      width: 100%;
      min-height: 58px;
      border: 1px solid transparent;
      background: transparent;
      border-radius: 8px;
      padding: 5px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      align-items: center;
      gap: 4px;
      margin-bottom: 5px;
      position: relative;
      transition: background .16s ease, border-color .16s ease, box-shadow .16s ease;
    }
    .conv:hover { background: var(--sidebar-strong); }
    .conv.active {
      background: var(--surface);
      border-color: var(--line);
      box-shadow: var(--soft-shadow);
    }
    .conv.active::before {
      content: "";
      position: absolute;
      left: 0;
      top: 12px;
      bottom: 12px;
      width: 3px;
      border-radius: 999px;
      background: var(--accent);
    }
    .conv.editing {
      background: var(--surface);
      border-color: var(--line-strong);
      box-shadow: var(--soft-shadow);
    }
    .conv-main {
      min-width: 0;
      min-height: 46px;
      padding: 8px 9px 8px 11px;
      display: grid;
      gap: 3px;
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
      font-size: 14px;
    }
    .conv-meta {
      color: var(--muted);
      font-size: 12px;
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
      width: 32px;
      min-width: 32px;
      height: 32px;
      min-height: 32px;
      padding: 0;
      color: var(--muted);
      background: transparent;
    }
    .conv-action:hover {
      color: var(--text);
      background: var(--surface);
      border-color: var(--line);
    }
    .conv-action.danger:hover {
      color: var(--red);
    }
    .conv-rename {
      min-height: 34px;
      padding: 7px 8px;
      font-size: 14px;
      font-weight: 580;
      background: var(--surface);
    }
    .side-foot {
      border-top: 1px solid var(--line);
      padding: 12px;
      display: grid;
      grid-template-columns: 1fr 1fr;
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
      min-height: 64px;
      border-bottom: 1px solid var(--line);
      background: var(--surface);
      backdrop-filter: blur(12px);
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
      align-items: center;
      gap: 10px;
      padding: 0 18px;
      min-width: 0;
      z-index: 4;
    }
    .top-title {
      min-width: 0;
      grid-column: 2;
      justify-self: center;
      text-align: center;
      max-width: 640px;
    }
    .top-title strong {
      display: block;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
      font-size: 15px;
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
    .top-actions {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      grid-column: 3;
      justify-self: end;
    }
    #openSide { grid-column: 1; justify-self: start; }
    .mobile-only { display: none !important; }
    .messages {
      overflow: auto;
      padding: 32px clamp(14px, 4vw, 48px) 26px;
      display: flex;
      flex-direction: column;
      gap: 20px;
      scroll-behavior: smooth;
      background: linear-gradient(180deg, var(--bg-elevated), var(--bg) 220px);
    }
    .scroll-latest {
      position: absolute;
      left: 50%;
      bottom: 116px;
      z-index: 6;
      min-height: 34px;
      padding: 0 12px;
      border-color: #cbd5e1;
      background: var(--surface);
      color: var(--text);
      box-shadow: var(--soft-shadow);
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
      background: var(--surface);
    }
    .messages-inner {
      width: min(var(--content), 100%);
      margin: 0 auto;
    }
    .empty {
      margin: auto;
      width: min(720px, 100%);
      display: grid;
      gap: 22px;
      text-align: center;
      color: var(--text);
      animation: rise .2s ease;
    }
    .empty h2 {
      margin: 0;
      font-size: clamp(26px, 3.5vw, 38px);
      font-weight: 720;
      letter-spacing: 0;
    }
    .empty p {
      margin: 0;
      color: var(--muted);
      font-size: 16px;
    }
    .prompt-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 4px;
    }
    .prompt-card {
      min-height: 78px;
      border: 1px solid var(--line);
      background: var(--surface);
      border-radius: 8px;
      padding: 14px;
      text-align: left;
      display: grid;
      align-content: center;
      box-shadow: var(--soft-shadow);
    }
    .prompt-card:hover {
      border-color: var(--line-strong);
      background: var(--bg-elevated);
      transform: translateY(-1px);
    }
    .prompt-card strong {
      display: block;
      font-weight: 650;
      margin-bottom: 2px;
    }
    .prompt-card span {
      display: block;
      color: var(--muted);
      font-size: 13px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .bubble {
      width: min(var(--content), 100%);
      margin: 0 auto;
      display: grid;
      gap: 7px;
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
      max-width: min(780px, 100%);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 48px 14px 16px;
      background: var(--assistant-bg);
      box-shadow: var(--soft-shadow);
      white-space: normal;
      overflow-wrap: anywhere;
    }
    .bubble.assistant .bubble-shell {
      background: var(--assistant-bg);
      border-color: var(--line);
      padding-left: 16px;
      padding-right: 46px;
    }
    .bubble.user .bubble-shell {
      background: var(--user-bg);
      border-color: var(--user-line);
      box-shadow: 0 8px 22px var(--user-shadow);
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
      background: var(--surface);
      border: 1px solid var(--line);
      box-shadow: var(--soft-shadow);
    }
    .bubble-shell:hover .copy-btn,
    .copy-btn:focus { opacity: 1; }
    .role {
      color: var(--muted-2);
      font-size: 12px;
      padding: 0 2px;
      font-weight: 650;
    }
    .message-time {
      color: var(--muted-2);
      font-size: 12px;
      line-height: 1;
      padding: 0 2px;
      user-select: none;
    }
    .message-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      padding: 0 2px;
    }
    .message-action {
      min-height: 30px;
      padding: 0 10px;
      border-color: var(--line);
      background: var(--surface);
      color: var(--muted);
      font-size: 12px;
      box-shadow: none;
    }
    .message-action.active {
      color: var(--accent-strong);
      background: var(--accent-soft);
      border-color: var(--accent);
    }
    .reasoning-panel {
      max-width: min(780px, 100%);
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-soft);
      color: var(--muted);
      padding: 12px 14px;
      box-shadow: var(--soft-shadow);
    }
    .reasoning-panel[hidden] { display: none; }
    .reasoning-panel .markdown {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.65;
    }
    .markdown {
      color: var(--text);
      line-height: 1.72;
    }
    .markdown > :first-child { margin-top: 0; }
    .markdown > :last-child { margin-bottom: 0; }
    .markdown p { margin: 0 0 11px; }
    .markdown h1,
    .markdown h2,
    .markdown h3 {
      margin: 18px 0 9px;
      line-height: 1.28;
      letter-spacing: 0;
    }
    .markdown h1 { font-size: 22px; }
    .markdown h2 { font-size: 19px; }
    .markdown h3 { font-size: 16px; }
    .markdown ul,
    .markdown ol {
      margin: 7px 0 13px;
      padding-left: 24px;
    }
    .markdown li { margin: 4px 0; }
    .markdown blockquote {
      margin: 10px 0;
      padding: 10px 12px;
      border-left: 3px solid var(--accent);
      background: var(--surface-soft);
      color: var(--muted);
      border-radius: 0 8px 8px 0;
    }
    .markdown code {
      border: 1px solid var(--line);
      background: var(--surface-soft);
      border-radius: 6px;
      padding: 1px 5px;
      font: 13px/1.5 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    .code-block {
      margin: 12px 0 14px;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--code-bg);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
    }
    .code-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      min-height: 34px;
      padding: 0 12px;
      color: var(--muted-2);
      border-bottom: 1px solid rgba(255,255,255,.08);
      font: 12px/1 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      text-transform: lowercase;
    }
    .markdown pre {
      margin: 0;
      padding: 14px;
      overflow: auto;
      border: 0;
      border-radius: 0;
      background: var(--code-bg);
      color: var(--code-text);
      max-width: 100%;
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
      color: var(--accent-strong);
      text-decoration: none;
      border-bottom: 1px solid var(--line-strong);
    }
    .markdown a:hover { border-bottom-color: currentColor; }
    .markdown table {
      width: 100%;
      border-collapse: collapse;
      margin: 10px 0 12px;
      font-size: 14px;
      display: block;
      overflow-x: auto;
    }
    .markdown th,
    .markdown td {
      border: 1px solid var(--line);
      padding: 8px 9px;
      text-align: left;
      vertical-align: top;
    }
    .markdown th {
      background: var(--surface-soft);
      font-weight: 650;
    }
    .thinking {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      color: var(--muted);
      min-height: 26px;
    }
    .thinking-avatar {
      width: 30px;
      height: 30px;
      border-radius: 999px;
      object-fit: cover;
      border: 2px solid rgba(255, 255, 255, .88);
      box-shadow: 0 8px 18px rgba(217, 143, 168, .18);
      animation: meimeiBreathe 1.8s ease-in-out infinite;
    }
    .thinking strong {
      color: var(--accent-strong);
      font-weight: 650;
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
    @keyframes meimeiBreathe {
      0%, 100% { transform: translateY(0) scale(1); }
      50% { transform: translateY(-1px) scale(1.04); }
    }
    .composer {
      background: linear-gradient(180deg, rgba(255,255,255,0), var(--bg) 34%);
      padding: 12px clamp(12px, 4vw, 48px) 18px;
      display: grid;
      gap: 8px;
    }
    .composer-box {
      width: min(var(--content), 100%);
      margin: 0 auto;
      border: 1px solid var(--line);
      background: var(--surface);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 9px;
      display: grid;
      gap: 8px;
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
      height: 38px;
      color: var(--text);
    }
    .search-toggle {
      min-height: 38px;
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
      min-height: 54px;
      max-height: 180px;
      resize: none;
      border: 0;
      background: transparent;
      padding: 11px 8px;
      box-shadow: none;
    }
    #prompt:focus { box-shadow: none; border-color: transparent; }
    #send {
      width: 40px;
      min-width: 40px;
      height: 42px;
      min-height: 42px;
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
    #send.is-stop {
      background: var(--red);
      border-color: var(--red);
      box-shadow: 0 8px 20px rgba(194, 65, 61, .18);
    }
    #send.is-stop::before {
      content: "■";
      font-size: 13px;
    }
    .status { min-height: 18px; color: var(--muted); font-size: 12px; }
    .status.err { color: var(--red); }
    .status.ok { color: var(--green); }
    .drawer-mask {
      position: fixed;
      inset: 0;
      background: rgba(15,23,42,.38);
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
      background: var(--surface);
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
    .copy-dialog,
    .confirm-dialog,
    .theme-dialog,
    .prompt-dialog,
    .favorite-dialog {
      position: fixed;
      inset: 0;
      z-index: 30;
      display: none;
      place-items: center;
      padding: 18px;
      background: rgba(15,23,42,.38);
    }
    .copy-dialog.show,
    .confirm-dialog.show,
    .theme-dialog.show,
    .prompt-dialog.show,
    .favorite-dialog.show { display: grid; }
    .confirm-dialog { z-index: 40; }
    .copy-panel,
    .confirm-panel,
    .accent-panel,
    .library-panel {
      width: min(720px, 100%);
      max-height: min(680px, 88vh);
      display: grid;
      grid-template-rows: auto minmax(180px, 1fr) auto;
      gap: 10px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 14px;
    }
    .library-panel {
      width: min(940px, 100%);
      grid-template-rows: auto minmax(0, 1fr);
      padding: 0;
      overflow: hidden;
    }
    .confirm-panel {
      width: min(420px, 100%);
      grid-template-rows: auto auto;
      gap: 14px;
      padding: 18px;
    }
    .accent-panel {
      width: min(460px, 100%);
      max-height: min(620px, 88vh);
      grid-template-rows: auto minmax(0, 1fr);
      padding: 0;
      overflow: hidden;
    }
    .copy-panel-head {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }
    .dialog-head {
      min-height: 58px;
      padding: 0 16px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      border-bottom: 1px solid var(--line);
    }
    .dialog-head strong { font-size: 16px; }
    .dialog-body {
      overflow: auto;
      padding: 16px;
      background: var(--surface-soft);
    }
    .library-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(280px, .8fr);
      gap: 14px;
      align-items: start;
    }
    .item-list {
      display: grid;
      gap: 10px;
    }
    .library-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 12px;
      box-shadow: var(--soft-shadow);
      display: grid;
      gap: 8px;
    }
    .library-card strong {
      display: block;
      font-size: 14px;
    }
    .library-card p {
      margin: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
      overflow-wrap: anywhere;
    }
    .library-card-meta {
      color: var(--muted-2);
      font-size: 12px;
    }
    .library-actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .accent-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }
    .accent-option {
      min-height: 54px;
      justify-content: flex-start;
      display: flex;
      align-items: center;
      gap: 10px;
      border-color: var(--line);
      background: var(--surface);
      text-align: left;
    }
    .accent-option.active {
      border-color: var(--accent);
      background: var(--accent-soft);
      color: var(--accent-strong);
    }
    .accent-swatch {
      width: 22px;
      height: 22px;
      min-width: 22px;
      border-radius: 999px;
      border: 2px solid rgba(255,255,255,.88);
      box-shadow: 0 0 0 1px var(--line), 0 6px 14px var(--accent-shadow);
      background: var(--swatch);
    }
    .color-field {
      margin: 0 0 12px;
    }
    .color-field input[type="color"] {
      width: 100%;
      height: 44px;
      padding: 4px;
      cursor: pointer;
    }
    .library-editor {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 14px;
      box-shadow: var(--soft-shadow);
    }
    .library-editor h2 {
      margin: 0 0 12px;
      font-size: 15px;
      letter-spacing: 0;
    }
    .favorite-layout {
      display: grid;
      grid-template-columns: minmax(280px, .9fr) minmax(0, 1.1fr);
      gap: 14px;
      align-items: start;
    }
    .favorite-detail {
      min-height: 260px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 14px;
      box-shadow: var(--soft-shadow);
    }
    .favorite-detail-empty {
      color: var(--muted);
      display: grid;
      place-items: center;
      min-height: 220px;
      text-align: center;
    }
    .copy-panel-head strong { font-size: 15px; }
    .confirm-panel h2 {
      margin: 0 0 6px;
      font-size: 18px;
      letter-spacing: 0;
    }
    .confirm-panel p {
      margin: 0;
      color: var(--muted);
    }
    #manualCopyText {
      min-height: 220px;
      max-height: 52vh;
      resize: vertical;
      white-space: pre-wrap;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      line-height: 1.55;
    }
    .copy-panel-actions,
    .confirm-actions {
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
        width: min(330px, 88vw);
        z-index: 22;
        transform: translateX(-102%);
        transition: transform .22s ease;
        box-shadow: var(--shadow);
      }
      .sidebar.show { transform: translateX(0); }
      .mobile-only { display: inline-grid !important; }
      .main { height: 100vh; }
      .topbar { grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr); }
      .messages { padding-top: 20px; }
    }
    @media (max-width: 620px) {
      body { font-size: 15px; }
      .topbar { padding: 0 10px; min-height: 58px; }
      .top-actions { gap: 4px; }
      button.icon { width: 38px; min-width: 38px; }
      .composer { padding: 8px 10px 12px; }
      .composer-tools { align-items: stretch; flex-direction: column; }
      .composer-left { width: 100%; }
      .model-select { width: 100%; }
      .search-toggle { width: fit-content; }
      .scroll-latest { bottom: 152px; }
      .input-row { grid-template-columns: 1fr auto; }
      .bubble-shell { max-width: 100%; }
      .bubble.user,
      .bubble.assistant { justify-items: stretch; }
      .prompt-grid { grid-template-columns: 1fr; }
      .grid2 { grid-template-columns: 1fr; }
      .drawer { width: 100%; }
      .copy-panel,
      .confirm-panel,
      .accent-panel,
      .library-panel { max-height: 92vh; }
      .accent-grid { grid-template-columns: 1fr; }
      .library-grid,
      .favorite-layout { grid-template-columns: 1fr; }
      .side-foot { grid-template-columns: 1fr 1fr; }
    }

    /* Claude-inspired product refresh */
    :root {
      --bg: #FAF8F4;
      --bg-elevated: #fffdf9;
      --sidebar: #fff8f4;
      --sidebar-strong: #F6E9D6;
      --surface: #ffffff;
      --surface-soft: #F6E9D6;
      --surface-strong: #efdcca;
      --line: #eadfd2;
      --line-strong: #d4b9a5;
      --text: #27231f;
      --muted: #8A6D5A;
      --muted-2: #b49a87;
      --assistant-bg: transparent;
      --code-bg: #181512;
      --code-text: #fbf7ef;
      --shadow: 0 22px 60px rgba(138, 109, 90, .13);
      --soft-shadow: 0 10px 26px rgba(138, 109, 90, .08);
      --content: 1120px;
      --reading: 1040px;
      --composer-width: 1040px;
    }
    [data-theme="dark"] {
      --bg: #181614;
      --bg-elevated: #201d1a;
      --sidebar: #211e1a;
      --sidebar-strong: #2d2823;
      --surface: #24211d;
      --surface-soft: #2b2722;
      --surface-strong: #373027;
      --line: #3e3831;
      --line-strong: #584f45;
      --text: #f1ece4;
      --muted: #b8aea2;
      --muted-2: #8e8377;
      --assistant-bg: transparent;
      --code-bg: #11100f;
      --code-text: #f5efe6;
    }
    body {
      background:
        radial-gradient(circle at 82% 8%, color-mix(in srgb, var(--accent-soft) 58%, transparent), transparent 27%),
        linear-gradient(180deg, var(--bg-elevated), var(--bg));
      font-size: 16px;
      line-height: 1.62;
    }
    button, select, input, textarea { border-radius: 12px; }
    button.primary {
      background: linear-gradient(135deg, var(--accent), var(--accent-strong));
      border-color: transparent;
      box-shadow: 0 12px 28px var(--accent-shadow);
    }
    button.primary:hover {
      background: linear-gradient(135deg, var(--accent-strong), var(--accent));
      transform: translateY(-1px);
    }
    .app {
      grid-template-columns: 322px minmax(0, 1fr);
      background: transparent;
    }
    .sidebar {
      padding: 14px 12px;
      gap: 10px;
      border-right: 1px solid color-mix(in srgb, var(--line) 78%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--sidebar) 92%, #fff 8%), var(--sidebar)),
        var(--sidebar);
    }
    .side-head {
      padding: 6px 4px 8px;
    }
    .brand h1 {
      font-size: 22px;
      font-weight: 760;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 0;
    }
    .brand-copy {
      min-width: 0;
    }
    .brand-avatar {
      width: 42px;
      height: 42px;
      border-radius: 16px;
      object-fit: cover;
      box-shadow: 0 10px 22px rgba(217, 143, 168, .2);
      border: 2px solid rgba(255, 255, 255, .86);
      background: var(--accent-soft);
      flex: 0 0 auto;
    }
    .brand span {
      font-size: 13px;
      color: var(--muted);
    }
    .side-actions {
      padding: 0;
      grid-template-columns: minmax(0, 1fr) 44px;
    }
    .side-actions .primary {
      min-height: 48px;
      border-radius: 14px;
      justify-content: center;
      font-weight: 680;
      letter-spacing: 0;
    }
    .side-actions .icon {
      width: 44px;
      min-width: 44px;
      min-height: 48px;
      border: 1px solid color-mix(in srgb, var(--line) 82%, transparent);
      background: color-mix(in srgb, var(--surface) 72%, transparent);
    }
    .side-section-title {
      padding: 4px 6px 0;
      font-size: 12px;
      letter-spacing: .02em;
      text-transform: uppercase;
    }
    .conversation-list {
      padding: 0 0 10px;
    }
    .conversation-group {
      margin: 16px 8px 7px;
      color: var(--muted-2);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: .03em;
    }
    .conv {
      min-height: 56px;
      margin: 0 0 4px;
      padding: 4px;
      border-radius: 14px;
      border-color: transparent;
    }
    .conv:hover {
      background: color-mix(in srgb, var(--sidebar-strong) 78%, transparent);
    }
    .conv.active {
      background: color-mix(in srgb, var(--surface) 86%, transparent);
      border-color: color-mix(in srgb, var(--accent) 36%, var(--line));
      box-shadow: 0 10px 30px rgba(73, 54, 35, .08);
    }
    .conv.active::before {
      left: 4px;
      top: 14px;
      bottom: 14px;
      width: 4px;
    }
    .conv-main {
      min-height: 48px;
      padding: 8px 10px 8px 16px;
      border-radius: 12px;
    }
    .conv-title {
      font-size: 14px;
      font-weight: 680;
    }
    .conv-meta {
      font-size: 12px;
      color: var(--muted);
    }
    .conv-action {
      width: 30px;
      min-width: 30px;
      height: 30px;
      min-height: 30px;
      border-radius: 10px;
    }
    .side-foot {
      margin: 0 -2px -2px;
      padding: 12px 0 0;
      border-top: 1px solid color-mix(in srgb, var(--line) 74%, transparent);
      grid-template-columns: 1fr 1fr;
    }
    .side-foot button {
      min-height: 42px;
      border: 1px solid color-mix(in srgb, var(--line) 82%, transparent);
      background: color-mix(in srgb, var(--surface) 64%, transparent);
      color: var(--muted);
      font-weight: 620;
    }
    .main {
      grid-template-rows: auto minmax(0, 1fr) auto;
      background:
        radial-gradient(circle at 52% 0, color-mix(in srgb, var(--accent-soft) 38%, transparent), transparent 34%),
        linear-gradient(180deg, var(--bg-elevated), var(--bg));
    }
    .topbar {
      min-height: 66px;
      padding: 0 clamp(14px, 3vw, 34px);
      border-bottom: 1px solid color-mix(in srgb, var(--line) 66%, transparent);
      background: color-mix(in srgb, var(--bg-elevated) 84%, transparent);
      backdrop-filter: blur(18px);
    }
    .top-title strong {
      font-size: 16px;
      font-weight: 740;
    }
    .top-title span {
      font-size: 13px;
    }
    .top-actions .icon {
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface) 58%, transparent);
      border: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
    }
    .messages {
      padding: 30px clamp(18px, 5vw, 72px) 28px;
      gap: 28px;
      background: transparent;
    }
    .messages-inner,
    .bubble {
      width: min(var(--reading), 100%);
    }
    .empty {
      width: min(920px, 100%);
      gap: 26px;
      text-align: left;
      align-content: center;
    }
    .empty-hero {
      width: min(520px, 88vw);
      justify-self: center;
      display: block;
      border-radius: 28px;
      border: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
      box-shadow: 0 18px 48px rgba(138, 109, 90, .11);
      background: var(--surface);
    }
    .empty h2 {
      font-size: clamp(34px, 4.5vw, 56px);
      line-height: 1.05;
      font-weight: 780;
      text-align: center;
    }
    .empty p {
      max-width: 560px;
      margin: 0 auto;
      text-align: center;
      font-size: 17px;
    }
    .prompt-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
    }
    .prompt-card {
      min-height: 104px;
      border-radius: 18px;
      padding: 18px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 94%, #fff 6%), var(--surface));
      border-color: color-mix(in srgb, var(--line) 78%, transparent);
      box-shadow: 0 12px 34px rgba(73, 54, 35, .08);
    }
    .prompt-card:hover {
      border-color: color-mix(in srgb, var(--accent) 44%, var(--line));
      background: color-mix(in srgb, var(--accent-soft) 24%, var(--surface));
      box-shadow: 0 18px 44px rgba(73, 54, 35, .12);
    }
    .prompt-card strong {
      font-size: 15px;
      font-weight: 760;
    }
    .prompt-card span {
      white-space: normal;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      line-height: 1.5;
    }
    .bubble {
      gap: 8px;
    }
    .bubble.assistant {
      justify-items: stretch;
    }
    .bubble.user {
      justify-items: end;
    }
    .bubble-shell {
      max-width: 100%;
      border-radius: 0;
      border: 0;
      box-shadow: none;
      padding: 0;
      background: transparent;
    }
    .bubble.assistant .bubble-shell {
      max-width: min(940px, 100%);
      padding: 2px 0;
      background: transparent;
      border: 0;
    }
    .bubble.user .bubble-shell {
      max-width: min(720px, 78%);
      padding: 13px 16px;
      border: 1px solid color-mix(in srgb, var(--user-line) 86%, transparent);
      border-radius: 20px 20px 6px 20px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--user-bg) 94%, #fff 6%), var(--user-bg));
      box-shadow: 0 12px 26px var(--user-shadow);
    }
    .copy-btn {
      display: none;
    }
    .role {
      padding: 0;
      font-size: 13px;
      color: var(--muted);
    }
    .bubble.assistant .role {
      font-weight: 720;
      color: var(--accent-strong);
    }
    .bubble.user .role,
    .bubble.user .message-time,
    .bubble.user .message-actions {
      justify-self: end;
    }
    .message-time {
      padding: 0;
      font-size: 12px;
      color: var(--muted-2);
    }
    .message-actions {
      gap: 4px;
      padding: 0;
      align-items: center;
    }
    .message-action {
      min-height: 28px;
      padding: 0 8px;
      border: 1px solid transparent;
      border-radius: 999px;
      background: transparent;
      color: var(--muted);
      font-size: 12px;
      font-weight: 620;
    }
    .message-action:hover {
      background: color-mix(in srgb, var(--surface-soft) 78%, transparent);
      border-color: color-mix(in srgb, var(--line) 76%, transparent);
      color: var(--text);
    }
    .message-action.active {
      color: var(--accent-strong);
      background: color-mix(in srgb, var(--accent-soft) 74%, transparent);
      border-color: color-mix(in srgb, var(--accent) 44%, var(--line));
    }
    .reasoning-panel {
      max-width: min(900px, 100%);
      border-radius: 16px;
      border-color: color-mix(in srgb, var(--line) 76%, transparent);
      background: color-mix(in srgb, var(--surface-soft) 78%, transparent);
      box-shadow: none;
    }
    .markdown {
      max-width: min(900px, 100%);
      font-size: 16px;
      line-height: 1.78;
    }
    .markdown p {
      margin: 0 0 14px;
    }
    .markdown h1,
    .markdown h2,
    .markdown h3 {
      margin: 26px 0 12px;
      font-weight: 780;
      color: var(--text);
    }
    .markdown h1 { font-size: 28px; }
    .markdown h2 { font-size: 23px; }
    .markdown h3 { font-size: 18px; }
    .markdown ul,
    .markdown ol {
      margin: 10px 0 16px;
      padding-left: 28px;
    }
    .markdown li {
      margin: 6px 0;
      padding-left: 2px;
    }
    .markdown blockquote {
      margin: 16px 0;
      padding: 12px 16px;
      border-left: 4px solid var(--accent);
      background: color-mix(in srgb, var(--accent-soft) 42%, var(--surface));
      border-radius: 12px;
    }
    .markdown code {
      border-radius: 7px;
      background: color-mix(in srgb, var(--surface-soft) 86%, transparent);
      border-color: color-mix(in srgb, var(--line) 70%, transparent);
    }
    .code-block {
      margin: 16px 0 18px;
      border-radius: 16px;
      box-shadow: 0 14px 36px rgba(0,0,0,.12);
    }
    .markdown pre {
      padding: 18px;
    }
    .markdown table {
      border-radius: 12px;
      border: 1px solid var(--line);
      background: var(--surface);
    }
    .composer {
      padding: 8px clamp(18px, 5vw, 72px) 14px;
      background: linear-gradient(180deg, rgba(255,255,255,0), var(--bg) 32%);
    }
    .composer-box {
      width: min(var(--composer-width), 100%);
      border-radius: 22px;
      padding: 10px;
      gap: 8px;
      border: 1px solid color-mix(in srgb, var(--line) 74%, transparent);
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 94%, #fff 6%), var(--surface));
      box-shadow: 0 20px 60px rgba(73, 54, 35, .16);
      transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
    }
    .composer-box:focus-within {
      border-color: color-mix(in srgb, var(--accent) 58%, var(--line));
      box-shadow: 0 24px 70px rgba(73, 54, 35, .18), 0 0 0 4px var(--focus-ring);
    }
    .composer-chip-row {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      padding: 0 2px;
    }
    .prompt-chip {
      min-height: 30px;
      border-radius: 999px;
      padding: 0 10px;
      border: 1px solid color-mix(in srgb, var(--line) 82%, transparent);
      background: color-mix(in srgb, var(--surface-soft) 70%, transparent);
      color: var(--muted);
      font-size: 13px;
      font-weight: 650;
    }
    .prompt-chip:hover {
      color: var(--accent-strong);
      border-color: color-mix(in srgb, var(--accent) 46%, var(--line));
      background: color-mix(in srgb, var(--accent-soft) 70%, transparent);
    }
    .input-row {
      grid-template-columns: minmax(0, 1fr) 46px;
      gap: 8px;
      align-items: end;
    }
    #prompt {
      min-height: 68px;
      max-height: 210px;
      padding: 10px 10px;
      font-size: 16px;
      line-height: 1.55;
    }
    #send {
      width: 46px;
      min-width: 46px;
      height: 46px;
      min-height: 46px;
      border-radius: 15px;
      box-shadow: 0 14px 30px var(--accent-shadow);
    }
    #send::before {
      font-size: 22px;
    }
    .composer-tools {
      padding: 0 2px 2px;
      align-items: center;
    }
    .composer-left {
      gap: 8px;
    }
    .model-select,
    .search-toggle {
      height: 34px;
      min-height: 34px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface-soft) 66%, transparent);
      border-color: color-mix(in srgb, var(--line) 74%, transparent);
      color: var(--muted);
    }
    .model-select {
      min-width: 270px;
    }
    .status {
      min-height: 18px;
      font-size: 12px;
    }
    .scroll-latest {
      bottom: 148px;
      border-radius: 999px;
      border-color: color-mix(in srgb, var(--line) 80%, transparent);
    }
    @media (max-width: 900px) {
      .app { grid-template-columns: 1fr; }
      .sidebar {
        width: min(340px, 88vw);
        padding: 14px 12px;
      }
      .messages {
        padding: 22px 14px 24px;
      }
      .composer {
        padding: 7px 12px 12px;
      }
      .topbar {
        padding: 0 10px;
      }
      .empty {
        width: min(720px, 100%);
      }
      .prompt-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
    @media (max-width: 620px) {
      body { font-size: 15px; }
      .topbar {
        min-height: 58px;
        grid-template-columns: 42px minmax(0, 1fr) auto;
      }
      .top-title {
        grid-column: 2;
        justify-self: stretch;
      }
      .top-actions {
        grid-column: 3;
      }
      .top-actions .icon {
        width: 36px;
        min-width: 36px;
      }
      .messages {
        padding: 18px 12px 18px;
        gap: 22px;
      }
      .empty h2 {
        font-size: 34px;
      }
      .prompt-grid {
        grid-template-columns: 1fr;
      }
      .bubble.user .bubble-shell {
        max-width: 92%;
      }
      .markdown {
        font-size: 15px;
      }
      .composer-box {
        border-radius: 20px;
        padding: 10px;
      }
      .composer-chip-row {
        overflow-x: auto;
        flex-wrap: nowrap;
        padding-bottom: 2px;
      }
      .prompt-chip {
        white-space: nowrap;
      }
      .composer-tools {
        align-items: stretch;
        flex-direction: column;
      }
      .composer-left {
        width: 100%;
      }
      .model-select {
        width: 100%;
        min-width: 0;
      }
      .search-toggle {
        width: fit-content;
      }
      #prompt {
        min-height: 64px;
      }
      .input-row {
        grid-template-columns: 1fr 46px;
      }
      #send {
        width: 46px;
        min-width: 46px;
        height: 46px;
        min-height: 46px;
      }
      .scroll-latest {
        bottom: 174px;
      }
    }

    /* Product polish: reading surface, identity and composer details */
    .chat-usage {
      display: block;
      margin-top: 2px;
      color: var(--muted-2);
      font-size: 12px;
      white-space: nowrap;
    }
    .nav-count {
      display: inline-grid;
      place-items: center;
      min-width: 20px;
      height: 20px;
      margin-left: 4px;
      padding: 0 6px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--accent-soft) 82%, var(--surface));
      color: var(--accent-strong);
      font-size: 12px;
      font-weight: 760;
    }
    #openFavorites {
      color: var(--text);
      border-color: color-mix(in srgb, var(--accent) 26%, var(--line));
      background: color-mix(in srgb, var(--surface) 74%, var(--accent-soft));
    }
    .empty-kicker {
      width: fit-content;
      margin: 0 auto 12px;
      padding: 7px 12px;
      border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--line));
      border-radius: 999px;
      background: color-mix(in srgb, var(--accent-soft) 58%, transparent);
      color: var(--accent-strong);
      font-size: 13px;
      font-weight: 760;
    }
    .bubble.assistant {
      position: relative;
      padding: 2px 0 6px;
    }
    .bubble.assistant .role {
      display: inline-flex;
      align-items: center;
      gap: 9px;
      min-height: 30px;
      margin-bottom: 4px;
      font-size: 13px;
      font-weight: 760;
    }
    .role-avatar {
      width: 28px;
      height: 28px;
      border-radius: 999px;
      object-fit: cover;
      box-shadow: 0 10px 22px var(--accent-shadow);
      border: 2px solid rgba(255, 255, 255, .88);
      background: var(--accent-soft);
      flex: 0 0 auto;
    }
    .bubble.assistant .bubble-shell {
      max-width: min(980px, 100%);
      padding: 20px 24px 18px;
      border: 1px solid color-mix(in srgb, var(--line) 68%, transparent);
      border-radius: 22px;
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--surface) 92%, #fff 8%), color-mix(in srgb, var(--surface) 90%, var(--surface-soft)));
      box-shadow: 0 16px 46px rgba(73, 54, 35, .075);
    }
    .bubble.assistant .message-content {
      padding-left: 2px;
    }
    .bubble.assistant .message-time,
    .bubble.assistant .message-actions,
    .bubble.assistant .sources-panel,
    .bubble.assistant .reasoning-panel {
      margin-left: 42px;
    }
    .bubble.user .bubble-shell {
      max-width: min(820px, 84%);
      padding: 16px 20px;
      border-radius: 24px 24px 8px 24px;
      font-size: 16px;
      line-height: 1.7;
      border-color: color-mix(in srgb, var(--accent) 22%, var(--user-line));
      background:
        linear-gradient(180deg, color-mix(in srgb, var(--user-bg) 90%, #fff 10%), color-mix(in srgb, var(--user-bg) 92%, var(--accent-soft)));
      box-shadow: 0 16px 34px var(--user-shadow);
    }
    .bubble.user .markdown {
      font-size: 16px;
      line-height: 1.7;
    }
    .message-actions {
      margin-top: 2px;
    }
    .sources-panel {
      width: min(980px, 100%);
      margin-top: 4px;
      display: grid;
      gap: 8px;
    }
    .sources-panel[hidden] {
      display: none;
    }
    .sources-title {
      color: var(--muted);
      font-size: 12px;
      font-weight: 760;
      letter-spacing: .02em;
    }
    .sources-list {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .source-card {
      max-width: min(300px, 100%);
      min-height: 42px;
      padding: 8px 10px;
      display: grid;
      gap: 2px;
      border: 1px solid color-mix(in srgb, var(--line) 72%, transparent);
      border-radius: 12px;
      background: color-mix(in srgb, var(--surface) 82%, transparent);
      color: var(--text);
      text-decoration: none;
      box-shadow: 0 8px 20px rgba(73, 54, 35, .055);
    }
    .source-card:hover {
      border-color: color-mix(in srgb, var(--accent) 38%, var(--line));
      background: color-mix(in srgb, var(--accent-soft) 32%, var(--surface));
    }
    .source-card strong,
    .source-card span {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .source-card strong {
      font-size: 12px;
      font-weight: 720;
    }
    .source-card span {
      color: var(--muted);
      font-size: 11px;
    }
    .message-action {
      min-height: 30px;
      padding: 0 10px;
      color: color-mix(in srgb, var(--muted) 88%, var(--text));
    }
    .message-action.copy-action {
      width: 32px;
      min-width: 32px;
      height: 32px;
      min-height: 32px;
      padding: 0;
      display: inline-grid;
      place-items: center;
      border: 1px solid color-mix(in srgb, var(--line) 82%, transparent);
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface) 86%, transparent);
      color: var(--muted);
      box-shadow: 0 8px 18px rgba(73, 54, 35, .06);
    }
    .message-action.copy-action:hover {
      border-color: color-mix(in srgb, var(--accent) 34%, var(--line));
      background: color-mix(in srgb, var(--accent-soft) 42%, var(--surface));
      color: var(--accent-strong);
    }
    .copy-action svg {
      width: 15px;
      height: 15px;
      display: block;
      fill: none;
      stroke: currentColor;
      stroke-width: 1.8;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
    .bubble.assistant .message-actions {
      width: min(980px, calc(100% - 42px));
    }
    .bubble.assistant .copy-action {
      margin-left: auto;
    }
    .message-action::first-letter {
      letter-spacing: 0;
    }
    .markdown {
      letter-spacing: 0;
    }
    .bubble.assistant .markdown p {
      margin-bottom: 16px;
    }
    .bubble.assistant .markdown > p:first-child {
      font-size: 16.5px;
    }
    .bubble.assistant .markdown h1,
    .bubble.assistant .markdown h2 {
      padding-bottom: 6px;
      border-bottom: 1px solid color-mix(in srgb, var(--line) 52%, transparent);
    }
    .composer-box {
      grid-template-areas:
        "chips chips"
        "input input"
        "tools tools";
      row-gap: 6px;
    }
    .composer-chip-row {
      grid-area: chips;
    }
    .input-row {
      grid-area: input;
    }
    .composer-tools {
      grid-area: tools;
      margin-top: 0;
      padding-top: 8px;
      border-top: 1px solid color-mix(in srgb, var(--line) 54%, transparent);
    }
    .composer-left {
      gap: 9px;
    }
    .model-select {
      padding-left: 14px;
      font-weight: 650;
    }
    .search-toggle,
    .model-select,
    .prompt-chip {
      box-shadow: inset 0 1px 0 rgba(255,255,255,.42);
    }
    .search-toggle span::before {
      content: "⌁";
      margin-right: 5px;
      color: var(--accent-strong);
      font-weight: 800;
    }
    #prompt::placeholder {
      color: color-mix(in srgb, var(--muted-2) 82%, transparent);
    }
    #send {
      align-self: end;
      margin-bottom: 2px;
    }
    .font-toggle {
      color: var(--accent-strong);
      font-size: 13px;
      font-weight: 800;
    }
    html[data-font-size="small"] {
      --ui-font-size: 15px;
      --reading-font-size: 15px;
      --user-font-size: 15px;
      --composer-font-size: 15px;
      --chip-font-size: 12px;
      --meta-font-size: 12px;
      --brand-font-size: 21px;
      --welcome-font-size: clamp(30px, 4vw, 50px);
    }
    html[data-font-size="medium"] {
      --ui-font-size: 16px;
      --reading-font-size: 16px;
      --user-font-size: 16px;
      --composer-font-size: 16px;
      --chip-font-size: 13px;
      --meta-font-size: 12px;
      --brand-font-size: 22px;
      --welcome-font-size: clamp(34px, 4.5vw, 56px);
    }
    html[data-font-size="large"] {
      --ui-font-size: 17px;
      --reading-font-size: 17.5px;
      --user-font-size: 17px;
      --composer-font-size: 17px;
      --chip-font-size: 14px;
      --meta-font-size: 13px;
      --brand-font-size: 23px;
      --welcome-font-size: clamp(36px, 4.8vw, 60px);
    }
    body {
      font-size: var(--ui-font-size, 16px);
    }
    .brand h1 {
      font-size: var(--brand-font-size, 22px);
    }
    .empty h2 {
      font-size: var(--welcome-font-size, clamp(34px, 4.5vw, 56px));
    }
    .markdown,
    .bubble.user .markdown,
    .bubble.assistant .markdown > p:first-child {
      font-size: var(--reading-font-size, 16px);
    }
    .bubble.user .bubble-shell {
      font-size: var(--user-font-size, 16px);
    }
    #prompt {
      font-size: var(--composer-font-size, 16px);
    }
    .prompt-chip,
    .message-action {
      font-size: var(--chip-font-size, 13px);
    }
    .message-time,
    .status,
    .top-title span,
    .brand span,
    .conv-meta,
    .source-card strong,
    .source-card span {
      font-size: var(--meta-font-size, 12px);
    }
    @media (max-width: 620px) {
      .bubble.assistant .bubble-shell {
        padding: 16px 16px 15px;
        border-radius: 18px;
      }
      .bubble.assistant .message-time,
      .bubble.assistant .message-actions,
      .bubble.assistant .sources-panel,
      .bubble.assistant .reasoning-panel {
        margin-left: 0;
      }
      .bubble.assistant .message-actions {
        width: 100%;
      }
      .bubble.user .bubble-shell {
        max-width: 94%;
        padding: 14px 16px;
      }
      .chat-usage {
        display: none;
      }
      .composer-tools {
        padding-top: 8px;
      }
    }

    /* Mobile ergonomics */
    .app,
    .main,
    .sidebar {
      height: var(--app-height, 100vh);
    }
    body.sidebar-open,
    body.dialog-open {
      overflow: hidden;
    }
    @supports (height: 100dvh) {
      .app,
      .main,
      .sidebar {
        height: var(--app-height, 100dvh);
      }
    }
    @media (max-width: 620px) {
      .composer {
        padding-bottom: calc(12px + env(safe-area-inset-bottom, 0px));
      }
      .sidebar {
        width: min(360px, 92vw);
        border-radius: 0 24px 24px 0;
      }
      .side-foot {
        padding-bottom: max(8px, env(safe-area-inset-bottom, 0px));
      }
      .prompt-dialog,
      .favorite-dialog,
      .theme-dialog,
      .copy-dialog,
      .confirm-dialog {
        place-items: end center;
        padding: 0;
      }
      .library-panel,
      .accent-panel,
      .copy-panel,
      .confirm-panel {
        width: 100%;
        max-height: min(86vh, calc(var(--app-height, 100vh) - 34px));
        border-radius: 24px 24px 0 0;
        border-left: 0;
        border-right: 0;
        border-bottom: 0;
      }
      .confirm-panel {
        margin: 0;
      }
      #prompt {
        font-size: var(--composer-font-size, 16px);
      }
    }
  </style>
</head>
<body>
  <div class="login" id="loginView">
    <form class="login-panel" id="loginForm">
      <img class="login-mascot" src="/res/meimei-login.png" alt="槑槑猫咪">
      <div class="login-copy">
        <h1>欢迎回家</h1>
        <p>我是槑槑，陪你把事情慢慢想清楚。</p>
      </div>
      <label>请输入家庭密码<input id="loginPassword" type="password" autocomplete="current-password" placeholder="请输入家庭密码"></label>
      <button class="primary" type="submit" style="width:100%">进入 AI槑槑</button>
      <div class="status err" id="loginStatus"></div>
    </form>
  </div>

  <div class="app" id="appView" style="display:none">
    <aside class="sidebar" id="sidebar">
      <div class="side-head">
        <div class="brand">
          <img class="brand-avatar" src="/res/meimei-avatar.png" alt="槑槑头像">
          <div class="brand-copy">
            <h1>AI槑槑 <span class="app-version">v2.2.0</span></h1>
            <span id="health">连接中</span>
          </div>
        </div>
        <button class="icon mobile-only" id="closeSide" title="关闭">×</button>
      </div>
      <div class="side-actions">
	        <button class="primary" id="newChat">+ 新对话</button>
        <button class="icon" id="refreshConversations" title="刷新">↻</button>
      </div>
      <div class="side-section-title">最近对话</div>
      <div class="conversation-list" id="conversationList"></div>
      <div class="side-foot">
        <button id="openPromptLibrary">提示词库</button>
        <button id="openFavorites">我的收藏 <span class="nav-count" id="favoriteCount">0</span></button>
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
          <span class="chat-usage" id="chatUsage"></span>
        </div>
        <div class="top-actions">
          <button class="icon accent-toggle" id="accentToggle" title="主色调">●</button>
          <button class="icon font-toggle" id="fontSizeToggle" title="字体大小：中">中</button>
          <button class="icon" id="themeToggle" title="切换深浅色">◐</button>
          <button class="icon danger" id="deleteConversation" title="删除当前对话">⌫</button>
        </div>
      </header>

      <section class="messages" id="messages"></section>
      <button class="scroll-latest" id="scrollLatest" type="button" title="回到底部">↓ 回到底部</button>

	      <footer class="composer">
	        <div class="composer-box">
	          <div class="composer-chip-row" aria-label="常用提示词">
	            <button class="prompt-chip" type="button" data-prompt-text="帮我润色下面这段文字，让它更自然、更清楚：">润色</button>
	            <button class="prompt-chip" type="button" data-prompt-text="帮我深度改写下面这段内容，保留原意，但让表达更有条理：">改写</button>
	            <button class="prompt-chip" type="button" data-prompt-text="帮我扩写下面这段内容，补充细节，让它更完整：">扩写</button>
	            <button class="prompt-chip" type="button" data-prompt-text="帮我精简下面这段内容，保留重点，表达更利落：">精简</button>
	            <button class="prompt-chip" id="openPrompts" type="button">更多</button>
	          </div>
	          <div class="input-row">
	            <textarea id="prompt" placeholder="和 AI槑槑聊点什么..."></textarea>
	            <button class="primary" id="send" title="发送">发送</button>
	          </div>
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
	  <section class="confirm-dialog" id="confirmDialog">
	    <div class="confirm-panel" role="dialog" aria-modal="true" aria-labelledby="confirmTitle">
	      <div>
	        <h2 id="confirmTitle">确认操作</h2>
	        <p id="confirmMessage">确定要继续吗？</p>
	      </div>
	      <div class="confirm-actions">
	        <button id="cancelConfirm">取消</button>
	        <button class="primary" id="confirmOk">确定</button>
	      </div>
	    </div>
	  </section>
	  <section class="theme-dialog" id="accentDialog">
	    <div class="accent-panel" role="dialog" aria-modal="true" aria-labelledby="accentDialogTitle">
	      <div class="dialog-head">
	        <strong id="accentDialogTitle">主色调</strong>
	        <button class="icon" id="closeAccentDialog" title="关闭">×</button>
	      </div>
	      <div class="dialog-body">
	        <div class="accent-grid" id="accentPresetList"></div>
	        <label class="color-field">自定义颜色<input id="customAccentColor" type="color" value="#e58aa6"></label>
	        <div class="library-actions">
	          <button class="primary" id="applyCustomAccent" type="button">应用</button>
	          <button id="resetAccent" type="button">恢复粉色</button>
	        </div>
	        <div class="status" id="accentStatus"></div>
	      </div>
	    </div>
	  </section>
	  <section class="prompt-dialog" id="promptDialog">
	    <div class="library-panel" role="dialog" aria-modal="true" aria-labelledby="promptDialogTitle">
	      <div class="dialog-head">
	        <strong id="promptDialogTitle">提示词库</strong>
	        <button class="icon" id="closePromptDialog" title="关闭">×</button>
	      </div>
	      <div class="dialog-body">
	        <div class="library-grid">
	          <div class="item-list" id="promptLibraryList"></div>
	          <section class="library-editor">
	            <h2>新增/编辑提示词</h2>
	            <input id="editingPromptId" type="hidden">
	            <label>标题<input id="promptTitle" placeholder="例如：朋友圈文案"></label>
	            <label>内容<textarea id="promptContent" rows="6" placeholder="写下点击后要填入输入框的内容"></textarea></label>
	            <label>排序<input id="promptSortOrder" type="number" value="100"></label>
	            <div class="library-actions">
	              <button class="primary" id="savePromptTemplate">保存提示词</button>
	              <button id="resetPromptTemplate">清空</button>
	            </div>
	            <div class="status" id="promptLibraryStatus"></div>
	          </section>
	        </div>
	      </div>
	    </div>
	  </section>
	      <section class="favorite-dialog" id="favoriteDialog">
	    <div class="library-panel" role="dialog" aria-modal="true" aria-labelledby="favoriteDialogTitle">
	      <div class="dialog-head">
	        <strong id="favoriteDialogTitle">🐾 我的收藏</strong>
	        <button class="icon" id="closeFavoriteDialog" title="关闭">×</button>
	      </div>
	      <div class="dialog-body">
	        <div class="favorite-layout">
	          <div class="item-list" id="favoriteList"></div>
	          <section class="favorite-detail" id="favoriteDetail"></section>
	        </div>
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
	      prompts: [],
	      favorites: [],
	      selectedFavoriteId: null,
	      conversations: [],
	      currentConversation: null,
	      messages: [],
	      sending: false,
	      editingConversationId: null,
	      streamMessage: null,
	      streamQueue: "",
	      streamTimer: null,
      streamResolve: null,
	      newConversationPromise: null,
	      newConversationModelId: "",
	      firstTokenAt: null,
	      abortController: null,
	      userStopped: false,
	      followOutput: true,
	      hasNewWhilePaused: false,
	      programmaticScroll: false,
	      isComposing: false,
	      lastCompositionEndAt: 0,
	      messageSeq: 0,
	      searchConfig: null,
	      adminKey: localStorage.getItem("aiPlatformAdminKey") || "",
	      theme: localStorage.getItem("aiPlatformTheme") || "",
	      accent: localStorage.getItem("aiPlatformAccent") || "pink",
	      fontSize: localStorage.getItem("aiPlatformFontSize") || "medium"
	    };
    $("adminKey").value = state.adminKey;

    const accentPresets = {
      pink: {
        label: "马卡龙粉",
        light: {
          accent: "#E9AFC0",
          accentStrong: "#D98FA8",
          accentSoft: "#FCE8EF",
          accentShadow: "rgba(217, 143, 168, .22)",
          focusRing: "rgba(217, 143, 168, .18)",
          userBg: "#fff1f5",
          userLine: "#edc0cd",
          userShadow: "rgba(217, 143, 168, .12)"
        },
        dark: {
          accent: "#f0b9c8",
          accentStrong: "#ffcbd7",
          accentSoft: "#3b2630",
          accentShadow: "rgba(240, 185, 200, .22)",
          focusRing: "rgba(240, 185, 200, .22)",
          userBg: "#3a2632",
          userLine: "#674055",
          userShadow: "rgba(0, 0, 0, .2)"
        }
      },
      mint: {
        label: "薄荷绿",
        light: {
          accent: "#5bb7a8",
          accentStrong: "#318779",
          accentSoft: "#e6f6f2",
          accentShadow: "rgba(91, 183, 168, .2)",
          focusRing: "rgba(91, 183, 168, .18)",
          userBg: "#e9f8f5",
          userLine: "#b9ded7",
          userShadow: "rgba(91, 183, 168, .12)"
        },
        dark: {
          accent: "#83d2c5",
          accentStrong: "#a4e2d9",
          accentSoft: "#203936",
          accentShadow: "rgba(131, 210, 197, .22)",
          focusRing: "rgba(131, 210, 197, .22)",
          userBg: "#203633",
          userLine: "#3f665f",
          userShadow: "rgba(0, 0, 0, .2)"
        }
      },
      sky: {
        label: "天空蓝",
        light: {
          accent: "#76a9e8",
          accentStrong: "#4f80c3",
          accentSoft: "#eaf3ff",
          accentShadow: "rgba(118, 169, 232, .2)",
          focusRing: "rgba(118, 169, 232, .18)",
          userBg: "#edf5ff",
          userLine: "#bdd6f5",
          userShadow: "rgba(118, 169, 232, .12)"
        },
        dark: {
          accent: "#93c3ff",
          accentStrong: "#b5d6ff",
          accentSoft: "#23334a",
          accentShadow: "rgba(147, 195, 255, .22)",
          focusRing: "rgba(147, 195, 255, .22)",
          userBg: "#22324a",
          userLine: "#405d88",
          userShadow: "rgba(0, 0, 0, .2)"
        }
      },
      lavender: {
        label: "薰衣草紫",
        light: {
          accent: "#aa94df",
          accentStrong: "#8068ba",
          accentSoft: "#f2edff",
          accentShadow: "rgba(170, 148, 223, .2)",
          focusRing: "rgba(170, 148, 223, .18)",
          userBg: "#f5f0ff",
          userLine: "#d5c8f1",
          userShadow: "rgba(170, 148, 223, .12)"
        },
        dark: {
          accent: "#c4b3f2",
          accentStrong: "#dbcfff",
          accentSoft: "#312944",
          accentShadow: "rgba(196, 179, 242, .22)",
          focusRing: "rgba(196, 179, 242, .22)",
          userBg: "#302842",
          userLine: "#5a4a7a",
          userShadow: "rgba(0, 0, 0, .2)"
        }
      },
      peach: {
        label: "蜜桃橙",
        light: {
          accent: "#e9a16f",
          accentStrong: "#c87945",
          accentSoft: "#fff0e5",
          accentShadow: "rgba(233, 161, 111, .2)",
          focusRing: "rgba(233, 161, 111, .18)",
          userBg: "#fff4ec",
          userLine: "#efcaad",
          userShadow: "rgba(233, 161, 111, .12)"
        },
        dark: {
          accent: "#f1b98f",
          accentStrong: "#ffd2b5",
          accentSoft: "#3b2c24",
          accentShadow: "rgba(241, 185, 143, .22)",
          focusRing: "rgba(241, 185, 143, .22)",
          userBg: "#3a2b24",
          userLine: "#68503f",
          userShadow: "rgba(0, 0, 0, .2)"
        }
      }
    };

    function preferredTheme() {
      if (state.theme === "light" || state.theme === "dark") return state.theme;
      return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    }

    function normalizeHex(value) {
      const match = String(value || "").trim().match(/^#?([0-9a-f]{6})$/i);
      return match ? "#" + match[1].toLowerCase() : "";
    }

    function hexToRgb(hex) {
      const clean = normalizeHex(hex).slice(1);
      return {
        r: parseInt(clean.slice(0, 2), 16),
        g: parseInt(clean.slice(2, 4), 16),
        b: parseInt(clean.slice(4, 6), 16)
      };
    }

    function rgbToHex(rgb) {
      return "#" + [rgb.r, rgb.g, rgb.b].map((value) => {
        return Math.max(0, Math.min(255, Math.round(value))).toString(16).padStart(2, "0");
      }).join("");
    }

    function mixHex(base, target, weight) {
      const a = hexToRgb(base);
      const b = hexToRgb(target);
      return rgbToHex({
        r: a.r * (1 - weight) + b.r * weight,
        g: a.g * (1 - weight) + b.g * weight,
        b: a.b * (1 - weight) + b.b * weight
      });
    }

    function rgbaFromHex(hex, alpha) {
      const rgb = hexToRgb(hex);
      return `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha})`;
    }

    function normalizeAccent(value) {
      if (accentPresets[value]) return value;
      const hex = normalizeHex(value);
      return hex || "pink";
    }

    function accentBaseColor(value = state.accent) {
      const accent = normalizeAccent(value);
      return accentPresets[accent]?.light.accent || accent;
    }

    function buildCustomAccent(hex, theme) {
      const base = normalizeHex(hex) || accentPresets.pink.light.accent;
      if (theme === "dark") {
        return {
          accent: mixHex(base, "#ffffff", .22),
          accentStrong: mixHex(base, "#ffffff", .36),
          accentSoft: mixHex(base, "#151817", .78),
          accentShadow: rgbaFromHex(base, .24),
          focusRing: rgbaFromHex(base, .22),
          userBg: mixHex(base, "#151817", .72),
          userLine: mixHex(base, "#151817", .45),
          userShadow: "rgba(0, 0, 0, .2)"
        };
      }
      return {
        accent: base,
        accentStrong: mixHex(base, "#111827", .22),
        accentSoft: mixHex(base, "#ffffff", .86),
        accentShadow: rgbaFromHex(base, .2),
        focusRing: rgbaFromHex(base, .18),
        userBg: mixHex(base, "#ffffff", .9),
        userLine: mixHex(base, "#ffffff", .58),
        userShadow: rgbaFromHex(base, .12)
      };
    }

    function accentValues(value = state.accent, theme = preferredTheme()) {
      const accent = normalizeAccent(value);
      return accentPresets[accent]?.[theme] || buildCustomAccent(accent, theme);
    }

    function applyAccent(value = state.accent || "pink") {
      const accent = normalizeAccent(value);
      state.accent = accent;
      localStorage.setItem("aiPlatformAccent", accent);
      const values = accentValues(accent, preferredTheme());
      const root = document.documentElement;
      root.style.setProperty("--accent", values.accent);
      root.style.setProperty("--accent-strong", values.accentStrong);
      root.style.setProperty("--accent-soft", values.accentSoft);
      root.style.setProperty("--accent-shadow", values.accentShadow);
      root.style.setProperty("--focus-ring", values.focusRing);
      root.style.setProperty("--user-bg", values.userBg);
      root.style.setProperty("--user-line", values.userLine);
      root.style.setProperty("--user-shadow", values.userShadow);
      const color = accentBaseColor(accent);
      const button = $("accentToggle");
      if (button) {
        button.style.color = color;
        button.title = "主色调：" + (accentPresets[accent]?.label || "自定义");
      }
      const picker = $("customAccentColor");
      if (picker) picker.value = color;
      renderAccentOptions();
    }

    function applyTheme(theme = preferredTheme()) {
      state.theme = theme;
      document.documentElement.dataset.theme = theme;
      localStorage.setItem("aiPlatformTheme", theme);
      const button = $("themeToggle");
      if (button) {
        button.textContent = theme === "dark" ? "☀" : "◐";
        button.title = theme === "dark" ? "切换到浅色模式" : "切换到深色模式";
      }
      applyAccent(state.accent || "pink");
    }

    function toggleTheme() {
      applyTheme(preferredTheme() === "dark" ? "light" : "dark");
    }

    const fontSizeOptions = ["small", "medium", "large"];
    const fontSizeLabels = {
      small: "小",
      medium: "中",
      large: "大"
    };
    const fontSizeNames = {
      small: "小",
      medium: "中",
      large: "大"
    };

    function normalizeFontSize(value) {
      return fontSizeOptions.includes(value) ? value : "medium";
    }

    function applyFontSize(value = state.fontSize || "medium") {
      const size = normalizeFontSize(value);
      state.fontSize = size;
      document.documentElement.dataset.fontSize = size;
      localStorage.setItem("aiPlatformFontSize", size);
      const button = $("fontSizeToggle");
      if (button) {
        button.textContent = fontSizeLabels[size];
        button.title = "字体大小：" + fontSizeNames[size];
      }
      autosizePrompt();
    }

    function toggleFontSize() {
      const current = fontSizeOptions.indexOf(normalizeFontSize(state.fontSize));
      applyFontSize(fontSizeOptions[(current + 1) % fontSizeOptions.length]);
    }

    function renderAccentOptions() {
      const box = $("accentPresetList");
      if (!box) return;
      box.innerHTML = "";
      for (const [key, preset] of Object.entries(accentPresets)) {
        const button = document.createElement("button");
        button.className = "accent-option" + (state.accent === key ? " active" : "");
        button.type = "button";
        button.style.setProperty("--swatch", preset.light.accent);
        const swatch = document.createElement("span");
        swatch.className = "accent-swatch";
        const label = document.createElement("span");
        label.textContent = preset.label;
        button.append(swatch, label);
        button.addEventListener("click", () => {
          applyAccent(key);
          setStatus("accentStatus", "已切换为" + preset.label, "ok");
        });
        box.appendChild(button);
      }
      const custom = normalizeHex(state.accent);
      if (custom && !accentPresets[state.accent]) {
        const button = document.createElement("button");
        button.className = "accent-option active";
        button.type = "button";
        button.style.setProperty("--swatch", custom);
        const swatch = document.createElement("span");
        swatch.className = "accent-swatch";
        const label = document.createElement("span");
        label.textContent = "自定义";
        button.append(swatch, label);
        box.appendChild(button);
      }
    }

    function openAccentDialog() {
      $("accentDialog").classList.add("show");
      $("customAccentColor").value = accentBaseColor();
      setStatus("accentStatus", "");
      setDialogOpenState();
      renderAccentOptions();
    }

    function closeAccentDialog() {
      $("accentDialog").classList.remove("show");
      setDialogOpenState();
    }

    function applyCustomAccent() {
      const color = normalizeHex($("customAccentColor").value);
      if (!color) {
        setStatus("accentStatus", "请选择一个颜色。", "err");
        return;
      }
      applyAccent(color);
      setStatus("accentStatus", "已应用自定义颜色", "ok");
    }

    function resetAccent() {
      applyAccent("pink");
      setStatus("accentStatus", "已恢复马卡龙粉", "ok");
    }

    applyFontSize(state.fontSize);
    applyTheme(preferredTheme());

    function setStatus(id, text, kind = "") {
      const el = $(id);
      el.textContent = text || "";
      el.className = "status" + (kind ? " " + kind : "");
    }

    function friendlyError(value, fallback = "刚刚没处理成功，可以稍后再试一次。") {
      const text = String(value?.message || value || "").trim();
      if (!text) return fallback;
      if (/unauthorized|未登录|登录已过期/i.test(text)) return "登录状态过期了，请重新登录。";
      if (/password incorrect|密码不对/i.test(text)) return "密码不对，再检查一下。";
      if (/model not found|先选择模型|暂无可用模型/i.test(text)) return "还没有可用模型，请先在模型管理里配置。";
      if (/title and content are required/i.test(text)) return "标题和内容都要填写。";
      if (/content too long/i.test(text)) return "内容太长了，稍微精简一下再保存。";
      if (/only assistant messages can be favorited/i.test(text)) return "只能收藏 AI 的回答。";
      if (/favorite not found|prompt not found|message not found/i.test(text)) return "这条内容已经不存在了，刷新后再看看。";
      if (/upstream content rejected|data_inspection_failed|inappropriate content/i.test(text)) return "上游模型的安全策略拒绝了这次内容，换个问法试试。";
      if (/upstream status 400/i.test(text)) return "上游模型拒绝了这次请求，换个问法或关闭联网搜索试试。";
      if (/Failed to fetch|NetworkError|Load failed|网络/i.test(text)) return "网络连接不太顺，稍后再试一下。";
      if (/aborted|AbortError|停止/i.test(text)) return "已停止生成。";
      if (/invalid json|not found|bad request|server|traceback|exception/i.test(text)) return fallback;
      return text.length > 90 ? fallback : text;
    }

    async function readError(res, fallback) {
      try {
        const data = await res.json();
        return friendlyError(data.error || data.detail || JSON.stringify(data), fallback);
      } catch {
        try {
          return friendlyError(await res.text(), fallback);
        } catch {
          return fallback;
        }
      }
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

    function syncViewportHeight() {
      const height = Math.round(window.visualViewport?.height || window.innerHeight || document.documentElement.clientHeight);
      if (height > 0) document.documentElement.style.setProperty("--app-height", height + "px");
    }

    function setDialogOpenState() {
      const open = ["promptDialog", "favoriteDialog", "accentDialog", "copyDialog", "confirmDialog"].some((id) => {
        const el = $(id);
        return el && el.classList.contains("show");
      });
      document.body.classList.toggle("dialog-open", open);
    }

    function isSmallScreen() {
      return window.matchMedia && window.matchMedia("(max-width: 620px)").matches;
    }

    function handlePromptFocus() {
      if (!isSmallScreen()) return;
      setTimeout(() => {
        if (state.messages.length && isNearBottom()) scrollToLatest("auto");
        $("prompt").scrollIntoView({ block: "nearest", behavior: "smooth" });
      }, 120);
    }

    function isImeEnter(event) {
      if (event.isComposing || state.isComposing || event.keyCode === 229) return true;
      return Date.now() - state.lastCompositionEndAt < 160;
    }

    async function bootstrap() {
      try {
        const me = await request("/api/me");
        const data = await me.json();
        if (!data.authenticated) return showLogin();
	        state.authed = true;
	        showApp();
	        await Promise.all([loadModels(), loadSearchConfig(), loadPrompts(), loadFavorites(), loadConversations(), health()]);
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
      let res;
      try {
        res = await request("/api/login", { method: "POST", body: JSON.stringify({ password }) });
      } catch (err) {
        setStatus("loginStatus", friendlyError(err, "现在连不上服务，稍后再试一下。"), "err");
        return;
      }
      if (!res.ok) {
        setStatus("loginStatus", await readError(res, "密码不对，再检查一下。"), "err");
        return;
      }
	      $("loginPassword").value = "";
	      state.authed = true;
	      showApp();
	      await Promise.all([loadModels(), loadSearchConfig(), loadPrompts(), loadFavorites(), loadConversations(), health()]);
	    }

    async function logout() {
      await request("/api/logout", { method: "POST" });
      state.authed = false;
      state.currentConversation = null;
      state.messages = [];
      showLogin();
    }

	    async function loadModels() {
	      try {
	        const res = await api("/api/models");
	        const data = await res.json();
	        state.models = data.models || [];
	        renderModelSelect();
	        if (!state.currentConversation && state.models.length) {
	          $("chatModel").textContent = "准备使用 " + state.models[0].name;
	        }
	      } catch (err) {
	        state.models = [];
	        renderModelSelect();
	        setStatus("chatStatus", friendlyError(err, "模型列表暂时加载失败。"), "err");
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

	    async function loadPrompts() {
	      try {
	        const res = await api("/api/prompts");
	        const data = await res.json();
	        state.prompts = data.prompts || [];
	        renderPromptLibrary();
	      } catch (err) {
	        state.prompts = [];
	        setStatus("promptLibraryStatus", friendlyError(err, "提示词暂时加载失败。"), "err");
	      }
	    }

	    function insertPromptText(text) {
	      $("prompt").value = String(text || "");
	      autosizePrompt();
	      $("prompt").focus();
	    }

	    function openPromptLibrary() {
	      $("promptDialog").classList.add("show");
	      setDialogOpenState();
	      renderPromptLibrary();
	    }

	    function closePromptLibrary() {
	      $("promptDialog").classList.remove("show");
	      setDialogOpenState();
	    }

	    function renderPromptLibrary() {
	      const box = $("promptLibraryList");
	      if (!box) return;
	      box.innerHTML = "";
	      if (!state.prompts.length) {
	        const div = document.createElement("div");
	        div.className = "library-card";
	        div.innerHTML = "<p>还没有提示词。右侧可以新增一个常用模板。</p>";
	        box.appendChild(div);
	        return;
	      }
	      for (const item of state.prompts) {
	        const card = document.createElement("article");
	        card.className = "library-card";
	        const title = document.createElement("strong");
	        title.textContent = item.title;
	        const content = document.createElement("p");
	        content.textContent = item.content;
	        const meta = document.createElement("div");
	        meta.className = "library-card-meta";
	        meta.textContent = "排序 " + item.sort_order + " · " + formatTime(item.updated_at);
	        const actions = document.createElement("div");
	        actions.className = "library-actions";
	        const use = document.createElement("button");
	        use.className = "primary";
	        use.type = "button";
	        use.textContent = "填入输入框";
	        use.addEventListener("click", () => {
	          insertPromptText(item.content);
	          closePromptLibrary();
	        });
	        const edit = document.createElement("button");
	        edit.type = "button";
	        edit.textContent = "编辑";
	        edit.addEventListener("click", () => fillPromptForm(item));
	        const del = document.createElement("button");
	        del.type = "button";
	        del.className = "danger";
	        del.textContent = "删除";
	        del.addEventListener("click", () => deletePromptTemplate(item.id, item.title));
	        actions.append(use, edit, del);
	        card.append(title, content, meta, actions);
	        box.appendChild(card);
	      }
	    }

	    function fillPromptForm(item) {
	      $("editingPromptId").value = item.id || "";
	      $("promptTitle").value = item.title || "";
	      $("promptContent").value = item.content || "";
	      $("promptSortOrder").value = item.sort_order ?? 100;
	      setStatus("promptLibraryStatus", "正在编辑：" + (item.title || ""), "");
	    }

	    function resetPromptForm() {
	      $("editingPromptId").value = "";
	      $("promptTitle").value = "";
	      $("promptContent").value = "";
	      $("promptSortOrder").value = "100";
	      setStatus("promptLibraryStatus", "");
	    }

	    async function savePromptTemplate() {
	      const id = $("editingPromptId").value;
	      const body = {
	        title: $("promptTitle").value.trim(),
	        content: $("promptContent").value.trim(),
	        sort_order: Number($("promptSortOrder").value || 100)
	      };
	      if (!body.title || !body.content) {
	        setStatus("promptLibraryStatus", "标题和内容都要填写。", "err");
	        return;
	      }
	      const res = await api(id ? `/api/prompts/${id}` : "/api/prompts", {
	        method: id ? "PUT" : "POST",
	        body: JSON.stringify(body)
	      });
	      if (!res.ok) {
	        setStatus("promptLibraryStatus", await readError(res, "提示词保存失败，稍后再试一下。"), "err");
	        return;
	      }
	      resetPromptForm();
	      setStatus("promptLibraryStatus", "提示词已保存", "ok");
	      await loadPrompts();
	      if (!state.messages.length) renderEmpty();
	    }

	    async function deletePromptTemplate(id, title) {
	      const ok = await confirmAction({
	        title: "删除提示词",
	        message: `确定删除“${title}”吗？`,
	        confirmText: "删除",
	        danger: true
	      });
	      if (!ok) return;
	      const res = await api(`/api/prompts/${id}`, { method: "DELETE" });
	      if (!res.ok) {
	        setStatus("promptLibraryStatus", await readError(res, "删除提示词失败，稍后再试一下。"), "err");
	        return;
	      }
	      setStatus("promptLibraryStatus", "提示词已删除", "ok");
	      await loadPrompts();
	      if (!state.messages.length) renderEmpty();
	    }

	    async function loadFavorites() {
	      try {
	        const res = await api("/api/favorites");
	        const data = await res.json();
	        state.favorites = data.favorites || [];
	        updateFavoriteCount();
	        renderFavorites();
	      } catch (err) {
	        state.favorites = [];
	        updateFavoriteCount();
	        renderFavorites(friendlyError(err, "收藏暂时加载失败。"));
	      }
	    }

	    function favoriteSummary(content) {
	      const text = String(content || "").replace(/[>#*_`]/g, "").replace(/\[|\]|\(|\)/g, "").replace(/\s+/g, " ").trim();
	      return text.length > 110 ? text.slice(0, 110) + "..." : text;
	    }

	    function openFavorites() {
	      $("favoriteDialog").classList.add("show");
	      setDialogOpenState();
	      loadFavorites();
	    }

	    function closeFavorites() {
	      $("favoriteDialog").classList.remove("show");
	      setDialogOpenState();
	    }

	    function renderFavorites(errorText = "") {
	      const list = $("favoriteList");
	      const detail = $("favoriteDetail");
	      if (!list || !detail) return;
	      list.innerHTML = "";
	      if (errorText) {
	        list.innerHTML = '<div class="library-card"><p></p></div>';
	        list.querySelector("p").textContent = errorText;
	      } else if (!state.favorites.length) {
	        list.innerHTML = '<div class="library-card"><p>还没有收藏。看到好用的 AI 回复时，点消息下面的“收藏”。</p></div>';
	      } else {
	        for (const item of state.favorites) {
	          const card = document.createElement("article");
	          card.className = "library-card";
	          const title = document.createElement("strong");
	          title.textContent = item.conversation_title || "原会话已删除";
	          const meta = document.createElement("div");
	          meta.className = "library-card-meta";
	          meta.textContent = "收藏于 " + formatTime(item.created_at);
	          const summary = document.createElement("p");
	          summary.textContent = favoriteSummary(item.content);
	          const actions = document.createElement("div");
	          actions.className = "library-actions";
	          const view = document.createElement("button");
	          view.className = item.id === state.selectedFavoriteId ? "primary" : "";
	          view.type = "button";
	          view.textContent = "查看";
	          view.addEventListener("click", () => selectFavorite(item.id));
	          const insert = document.createElement("button");
	          insert.type = "button";
	          insert.textContent = "插入输入框";
	          insert.addEventListener("click", () => {
	            insertPromptText(item.content);
	            closeFavorites();
	          });
	          const copy = document.createElement("button");
	          copy.type = "button";
	          copy.textContent = "复制";
	          copy.addEventListener("click", () => copyText(item.content, copy));
	          const del = document.createElement("button");
	          del.className = "danger";
	          del.type = "button";
	          del.textContent = "删除";
	          del.addEventListener("click", () => deleteFavorite(item.id));
	          actions.append(view, insert, copy, del);
	          card.append(title, meta, summary, actions);
	          list.appendChild(card);
	        }
	      }
	      const current = state.favorites.find((item) => item.id === state.selectedFavoriteId) || state.favorites[0];
	      if (current) {
	        state.selectedFavoriteId = current.id;
	        detail.innerHTML = "";
	        const meta = document.createElement("div");
	        meta.className = "library-card-meta";
	        meta.textContent = (current.conversation_title || "原会话已删除") + " · 收藏于 " + formatTime(current.created_at);
	        const content = document.createElement("div");
	        content.className = "markdown";
	        content.innerHTML = renderMarkdown(current.content || "");
	        detail.append(meta, content);
	      } else {
	        state.selectedFavoriteId = null;
	        detail.innerHTML = '<div class="favorite-detail-empty">选择一条收藏查看完整回答</div>';
	      }
	    }

	    function selectFavorite(id) {
	      state.selectedFavoriteId = id;
	      renderFavorites();
	    }

	    async function deleteFavorite(id) {
	      const ok = await confirmAction({
	        title: "删除收藏",
	        message: "确定删除这条收藏吗？原对话内容不会受影响。",
	        confirmText: "删除",
	        danger: true
	      });
	      if (!ok) return;
	      const res = await api(`/api/favorites/${id}`, { method: "DELETE" });
	      if (!res.ok) {
	        setStatus("chatStatus", await readError(res, "删除收藏失败，稍后再试一下。"), "err");
	        return;
	      }
	      const removed = state.favorites.find((item) => item.id === id);
	      if (removed) {
	        const message = state.messages.find((item) => item.id === removed.message_id);
	        if (message) {
	          message.favorite_id = null;
	          updateStreamingMessage(message);
	        }
	      }
	      if (state.selectedFavoriteId === id) state.selectedFavoriteId = null;
	      await loadFavorites();
	    }

	    async function toggleFavoriteMessage(message, button) {
	      if (!message || message.role !== "assistant" || !message.id) return;
	      button.disabled = true;
	      try {
	        if (message.favorite_id) {
	          const res = await api(`/api/favorites/${message.favorite_id}`, { method: "DELETE" });
	          if (!res.ok) throw new Error(await readError(res, "取消收藏失败，稍后再试一下。"));
	          const oldFavoriteId = message.favorite_id;
	          message.favorite_id = null;
	          if (state.selectedFavoriteId === oldFavoriteId) state.selectedFavoriteId = null;
	          setStatus("chatStatus", "已取消收藏", "");
	        } else {
	          const res = await api("/api/favorites", {
	            method: "POST",
	            body: JSON.stringify({ message_id: message.id })
	          });
	          if (!res.ok) throw new Error(await readError(res, "收藏失败，稍后再试一下。"));
	          const data = await res.json();
	          message.favorite_id = data.favorite?.id || null;
	          setStatus("chatStatus", "已收藏", "ok");
	        }
	        updateStreamingMessage(message);
	        await loadFavorites();
	      } catch (err) {
	        setStatus("chatStatus", friendlyError(err, "收藏操作失败，稍后再试一下。"), "err");
	      } finally {
	        button.disabled = false;
	      }
	    }

	    function toggleReasoning(message) {
	      if (!message) return;
	      message.reasoning_open = !message.reasoning_open;
	      updateStreamingMessage(message);
	    }

	    function messageIndexOf(message) {
	      const key = messageKey(message);
	      return state.messages.findIndex((item) => messageKey(item) === key || (message.id && item.id === message.id));
	    }

	    function previousUserMessage(message) {
	      const start = messageIndexOf(message);
	      for (let i = start - 1; i >= 0; i--) {
	        if (state.messages[i]?.role === "user") return state.messages[i];
	      }
	      return null;
	    }

	    async function regenerateFromMessage(message) {
	      const previous = previousUserMessage(message);
	      if (!previous) {
	        setStatus("chatStatus", "没找到上一条问题，可以手动复制后再问一次。", "err");
	        return;
	      }
	      if (state.sending) return setStatus("chatStatus", "上一条还在生成，先等它完成。", "err");
	      setStatus("chatStatus", "正在重新生成...", "");
	      await sendMessage(previous.content || "", { statusText: "正在重新生成..." });
	    }

	    async function continueFromMessage(message) {
	      if (!visibleMessageContent(message)) return;
	      if (state.sending) return setStatus("chatStatus", "上一条还在生成，先等它完成。", "err");
	      await sendMessage("请接着上面的回答继续写，保持原来的语气和结构。", { statusText: "正在继续写..." });
	    }

    async function loadConversations() {
      renderConversationLoading();
      try {
        const res = await api("/api/conversations");
        const data = await res.json();
        state.conversations = data.conversations || [];
        renderConversations();
        if (!state.currentConversation && state.conversations.length) {
          await selectConversation(state.conversations[0].id);
        } else if (!state.conversations.length) {
          renderEmpty();
        }
      } catch (err) {
        renderConversationError(friendlyError(err, "对话列表暂时加载失败。"));
        if (!state.messages.length) renderEmpty();
      }
    }

	    function conversationGroupLabel(ts) {
	      const value = Number(ts || 0);
	      if (!value) return "更早";
	      const day = new Date(value * 1000);
	      const today = new Date();
	      today.setHours(0, 0, 0, 0);
	      const target = new Date(day);
	      target.setHours(0, 0, 0, 0);
	      const diffDays = Math.floor((today - target) / 86400000);
	      if (diffDays <= 0) return "今天";
	      if (diffDays === 1) return "昨天";
	      if (diffDays < 7) return "最近 7 天";
	      if (diffDays < 30) return "最近 30 天";
	      return "更早";
	    }

	    function renderConversations() {
	      const box = $("conversationList");
	      box.innerHTML = "";
      if (!state.conversations.length) {
        const div = document.createElement("div");
        div.className = "side-empty";
        div.textContent = "还没有对话。点上面的“新对话”，或者直接在右侧输入问题。";
        box.appendChild(div);
        return;
	      }
	      let lastGroup = "";
	      for (const conv of state.conversations) {
	        const group = conversationGroupLabel(conv.updated_at || conv.created_at);
	        if (group !== lastGroup) {
	          const title = document.createElement("div");
	          title.className = "conversation-group";
	          title.textContent = group;
	          box.appendChild(title);
	          lastGroup = group;
	        }
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

	    function renderConversationLoading() {
	      const box = $("conversationList");
	      box.innerHTML = "";
	      for (let i = 0; i < 4; i++) {
	        const item = document.createElement("div");
	        item.className = "side-empty";
	        item.innerHTML = '<div class="loading-line" style="width:' + (78 - i * 9) + '%"></div><div class="loading-line" style="width:' + (46 + i * 8) + '%;margin-top:10px"></div>';
	        box.appendChild(item);
	      }
	    }

	    function renderConversationError(message) {
	      const box = $("conversationList");
	      box.innerHTML = "";
	      const div = document.createElement("div");
	      div.className = "side-empty";
	      div.textContent = message || "对话列表暂时加载失败。";
	      box.appendChild(div);
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
	        setStatus("chatStatus", await readError(res, "重命名失败，稍后再试一下。"), "err");
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
        setStatus("chatStatus", "还没有可用模型，请先在模型管理里配置。", "err");
        return null;
      }
      if (state.newConversationPromise) {
        if (!state.newConversationModelId || state.newConversationModelId === modelId) {
          return state.newConversationPromise;
        }
        await state.newConversationPromise.catch(() => null);
      }
      const button = $("newChat");
      if (button) button.disabled = true;
      state.newConversationModelId = modelId;
      state.newConversationPromise = (async () => {
        const res = await api("/api/conversations", { method: "POST", body: JSON.stringify({ model_id: modelId }) });
        if (!res.ok) throw new Error(await readError(res, "新建对话失败，稍后再试一下。"));
        const data = await res.json();
        state.currentConversation = data.conversation;
        state.messages = [];
        await loadConversations();
        updateChatHeader();
        renderMessages({ forceScroll: true });
        return state.currentConversation;
      })();
      try {
        return await state.newConversationPromise;
      } finally {
        state.newConversationPromise = null;
        state.newConversationModelId = "";
        if (button) button.disabled = false;
      }
    }

	    async function selectConversation(id) {
	      state.editingConversationId = null;
	      const conv = state.conversations.find((item) => item.id === id);
	      if (!conv) return;
      state.currentConversation = conv;
      $("modelSelect").value = conv.model_id;
      updateChatHeader();
      renderConversations();
      try {
        const res = await api(`/api/conversations/${id}/messages`);
        if (!res.ok) throw new Error(await readError(res, "消息暂时加载失败。"));
        const data = await res.json();
        state.messages = data.messages || [];
        renderMessages({ forceScroll: true });
        closeSidebar();
      } catch (err) {
        setStatus("chatStatus", friendlyError(err, "消息暂时加载失败。"), "err");
      }
    }

    function updateChatHeader() {
      const conv = state.currentConversation;
      $("chatTitle").textContent = conv ? conv.title : "新对话";
      $("chatModel").textContent = conv ? (conv.model_name + " · " + conv.model) : "请选择模型";
      updateChatUsage();
      renderModelSelect();
    }

		    function renderEmpty() {
		      $("chatTitle").textContent = "新对话";
		      $("chatModel").textContent = state.models[0] ? "准备使用 " + state.models[0].name : "请选择模型";
	      updateChatUsage();
	      const box = $("messages");
	      box.innerHTML = `
	        <div class="empty">
	          <img class="empty-hero" src="/res/meimei-empty-state.png" alt="槑槑欢迎插画">
	          <div>
	            <div class="empty-kicker">家庭 AI 助手 · 槑槑在这里</div>
	            <h2>你好，我是槑槑 🐾</h2>
	            <p>今天想聊点什么？${state.models[0] ? " " + state.models[0].name + " 已就绪。" : ""}</p>
	          </div>
	          <div class="prompt-grid"></div>
	        </div>`;
	      const quickPrompts = [
	        { title: "润色文案", content: "帮我润色下面这段文字，让它更自然、更正式：" },
	        { title: "深度改写", content: "帮我深度改写下面这段内容，保留原意，但让表达更有条理：" },
	        { title: "工作总结", content: "帮我生成一份工作总结，结构清晰，语气正式：" },
	        { title: "活动宣传", content: "帮我写一段活动宣传文案，有吸引力但不要太夸张：" },
	        { title: "朋友圈文案", content: "帮我写一段朋友圈文案，语气自然一点：" },
	        { title: "整理内容", content: "帮我把下面内容整理成条理清晰的要点：" }
	      ];
	      const grid = box.querySelector(".prompt-grid");
	      for (const item of quickPrompts) {
	        const button = document.createElement("button");
	        button.className = "prompt-card";
	        button.dataset.prompt = item.content;
	        const title = document.createElement("strong");
	        title.textContent = item.title;
	        const summary = document.createElement("span");
	        summary.textContent = item.content;
	        button.append(title, summary);
	        grid.appendChild(button);
	      }
	      grid.querySelectorAll(".prompt-card").forEach((button) => {
	        button.addEventListener("click", () => {
	          insertPromptText(button.dataset.prompt || "");
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
	        const lang = escapeHTML(codeLang || "text");
	        html.push('<div class="code-block"><div class="code-head"><span>' + lang + '</span></div><pre><code' + className + ">" + escapeHTML(codeLines.join("\n")) + "</code></pre></div>");
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

	    function splitThinkContent(value) {
	      const reasoning = [];
	      const content = String(value || "").replace(/<think>\s*([\s\S]*?)\s*<\/think>/gi, (_, text) => {
	        const clean = String(text || "").trim();
	        if (clean) reasoning.push(clean);
	        return "";
	      }).trim();
	      return { content, reasoning: reasoning.join("\n\n") };
	    }

	    function visibleMessageContent(message) {
	      return splitThinkContent(message.content || "").content;
	    }

	    function messageReasoningContent(message) {
	      const parts = [];
	      if (message.reasoning_content) parts.push(String(message.reasoning_content).trim());
	      const extracted = splitThinkContent(message.content || "");
	      if (extracted.reasoning) parts.push(extracted.reasoning);
	      return parts.filter(Boolean).join("\n\n").trim();
	    }

	    function sourceDomain(value) {
	      try {
	        return new URL(value).hostname.replace(/^www\./, "");
	      } catch {
	        return "来源";
	      }
	    }

	    function renderSourcesPanel(panel, sources) {
	      if (!panel) return;
	      const items = Array.isArray(sources) ? sources.filter((item) => item && item.url) : [];
	      panel.hidden = !items.length;
	      panel.innerHTML = "";
	      if (!items.length) return;
	      const title = document.createElement("div");
	      title.className = "sources-title";
	      title.textContent = "参考来源";
	      const list = document.createElement("div");
	      list.className = "sources-list";
	      for (const item of items.slice(0, 6)) {
	        const link = document.createElement("a");
	        link.className = "source-card";
	        link.href = safeHref(item.url);
	        link.target = "_blank";
	        link.rel = "noreferrer";
	        link.title = item.title || item.url;
	        const strong = document.createElement("strong");
	        strong.textContent = (item.position ? item.position + ". " : "") + (item.title || sourceDomain(item.url));
	        const domain = document.createElement("span");
	        domain.textContent = sourceDomain(item.url);
	        link.append(strong, domain);
	        list.appendChild(link);
	      }
	      panel.append(title, list);
	    }

	    function formatMessageTime(value) {
	      const ts = Number(value || 0);
	      const date = ts > 0 ? new Date(ts * 1000) : new Date();
	      const pad = (num) => String(num).padStart(2, "0");
	      return pad(date.getHours()) + ":" + pad(date.getMinutes()) + ":" + pad(date.getSeconds());
	    }

	    function messageTotalTokens(message) {
	      const usage = message?.usage || {};
	      const direct = Number(message?.total_tokens || 0);
	      const total = Number(usage.total_tokens || direct || 0);
	      if (total > 0) return total;
	      const prompt = Number(usage.prompt_tokens || message?.prompt_tokens || 0);
	      const completion = Number(usage.completion_tokens || message?.completion_tokens || 0);
	      return prompt + completion;
	    }

	    function formatTokens(value) {
	      const num = Number(value || 0);
	      if (!num) return "";
	      return num >= 1000 ? (num / 1000).toFixed(num >= 10000 ? 0 : 1) + "k tokens" : num + " tokens";
	    }

	    function currentConversationTokens() {
	      return state.messages.reduce((sum, item) => sum + messageTotalTokens(item), 0);
	    }

	    function updateChatUsage() {
	      const el = $("chatUsage");
	      if (!el) return;
	      const tokens = currentConversationTokens();
	      el.textContent = tokens ? "本对话 " + formatTokens(tokens) : "";
	    }

	    function updateFavoriteCount() {
	      const el = $("favoriteCount");
	      if (!el) return;
	      const count = state.favorites.length;
	      el.textContent = String(count);
	      el.hidden = count <= 0;
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
	      const actions = document.createElement("div");
	      actions.className = "message-actions";
	      const sourcesPanel = document.createElement("div");
	      sourcesPanel.className = "sources-panel";
	      sourcesPanel.hidden = true;
	      const reasoningPanel = document.createElement("div");
	      reasoningPanel.className = "reasoning-panel";
	      reasoningPanel.hidden = true;
	      const copy = document.createElement("button");
	      copy.className = "copy-btn";
	      copy.type = "button";
	      copy.title = "复制";
	      copy.textContent = "⧉";
	      copy.addEventListener("click", () => copyText(visibleMessageContent(message), copy));
	      const copyAction = document.createElement("button");
	      copyAction.className = "message-action copy-action";
	      copyAction.type = "button";
	      copyAction.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="8" y="8" width="11" height="11" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1"></path></svg>';
	      copyAction.setAttribute("aria-label", "复制");
	      copyAction.title = "复制这条消息";
	      copyAction.addEventListener("click", () => copyText(visibleMessageContent(message), copyAction));
	      const favorite = document.createElement("button");
	      favorite.className = "message-action favorite-action";
	      favorite.type = "button";
	      favorite.addEventListener("click", () => toggleFavoriteMessage(message, favorite));
	      const regenerate = document.createElement("button");
	      regenerate.className = "message-action regenerate-action";
	      regenerate.type = "button";
	      regenerate.textContent = "重新生成";
	      regenerate.title = "把上一条问题放回输入框";
	      regenerate.addEventListener("click", () => regenerateFromMessage(message));
	      const continueWrite = document.createElement("button");
	      continueWrite.className = "message-action continue-action";
	      continueWrite.type = "button";
	      continueWrite.textContent = "继续写";
	      continueWrite.title = "基于这条回答继续写";
	      continueWrite.addEventListener("click", () => continueFromMessage(message));
	      const reason = document.createElement("button");
	      reason.className = "message-action reason-action";
	      reason.type = "button";
	      reason.addEventListener("click", () => toggleReasoning(message));
	      actions.append(favorite, regenerate, continueWrite, reason, copyAction);

	      shell.append(text, copy);
	      wrap.append(role, shell, sourcesPanel, time, actions, reasoningPanel);
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
	      const actions = wrap.querySelector(".message-actions");
	      const sourcesPanel = wrap.querySelector(".sources-panel");
	      const copyAction = wrap.querySelector(".copy-action");
	      const favorite = wrap.querySelector(".favorite-action");
	      const regenerate = wrap.querySelector(".regenerate-action");
	      const continueWrite = wrap.querySelector(".continue-action");
	      const reason = wrap.querySelector(".reason-action");
	      const reasoningPanel = wrap.querySelector(".reasoning-panel");
	      role.replaceChildren();
	      if (message.role === "user") {
	        role.textContent = "你";
	      } else {
	        const avatar = document.createElement("img");
	        avatar.className = "role-avatar";
	        avatar.src = "/res/meimei-avatar.png";
	        avatar.alt = "";
	        role.append(avatar, document.createTextNode(message.thinking ? "槑槑 · 思考中" : "槑槑"));
	      }
	      renderSourcesPanel(sourcesPanel, message.role === "assistant" ? message.sources : []);
	      if (time) {
	        const tokens = message.role === "assistant" ? messageTotalTokens(message) : 0;
	        time.textContent = formatMessageTime(message.created_at) + (tokens ? " · " + formatTokens(tokens) : "");
	      }

	      if (message.role === "assistant" && message.thinking && !message.content) {
	        text.className = "message-content";
	        text.innerHTML = `
	          <div class="thinking">
	            <img class="thinking-avatar" src="/res/meimei-avatar.png" alt="">
	            <span class="thinking-dots"><span></span><span></span><span></span></span>
	            <span><strong>槑槑</strong>正在整理思路...</span>
	          </div>`;
	        copy.hidden = true;
	        if (actions) actions.hidden = true;
	        return;
	      }

	      text.className = "message-content markdown";
	      const displayContent = visibleMessageContent(message);
	      const reasoningContent = messageReasoningContent(message);
	      text.innerHTML = renderMarkdown(displayContent || "");
	      copy.hidden = !displayContent || message.role === "assistant";
	      const canShowAssistantActions = message.role === "assistant" && (message.id || reasoningContent || displayContent);
	      const canShowUserActions = message.role === "user" && displayContent;
	      if (actions) actions.hidden = !(canShowAssistantActions || canShowUserActions);
	      if (copyAction) {
	        copyAction.hidden = !((message.role === "assistant" || message.role === "user") && displayContent);
	        copyAction.title = message.role === "assistant" ? "复制这条回答" : "复制这条消息";
	      }
	      if (reason) {
	        reason.hidden = !reasoningContent;
	        reason.textContent = message.reasoning_open ? "收起思考" : "思考";
	        reason.classList.toggle("active", Boolean(message.reasoning_open));
	        reason.title = message.reasoning_open ? "收起思考过程" : "查看思考过程";
	      }
	      if (favorite) {
	        favorite.hidden = !(message.role === "assistant" && message.id && displayContent);
	        favorite.textContent = message.favorite_id ? "已收藏" : "收藏";
	        favorite.classList.toggle("active", Boolean(message.favorite_id));
	        favorite.title = message.favorite_id ? "取消收藏" : "收藏这条回答";
	      }
	      if (regenerate) {
	        regenerate.hidden = !(message.role === "assistant" && displayContent);
	      }
	      if (continueWrite) {
	        continueWrite.hidden = !(message.role === "assistant" && displayContent);
	      }
	      if (reasoningPanel) {
	        reasoningPanel.hidden = !(reasoningContent && message.reasoning_open);
	        reasoningPanel.innerHTML = reasoningContent ? '<div class="markdown">' + renderMarkdown(reasoningContent) + '</div>' : "";
	      }
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
	      updateChatUsage();
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
	        updateChatUsage();
	        return;
	      }
	      const fragment = document.createDocumentFragment();
	      for (const msg of state.messages) {
	        fragment.appendChild(createMessageElement(msg));
	      }
	      box.replaceChildren(fragment);
	      settleMessageScroll(previousTop, shouldFollow);
	      updateChatUsage();
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
	      const old = button.innerHTML;
	      button.textContent = "✓";
	      setTimeout(() => {
	        button.innerHTML = old;
	      }, 900);
	    }

	    function openManualCopy(text) {
	      $("manualCopyText").value = text;
	      $("copyDialog").classList.add("show");
	      setDialogOpenState();
	      setTimeout(() => {
	        $("manualCopyText").focus();
	        $("manualCopyText").select();
	      }, 0);
	    }

	    function closeManualCopy() {
	      $("copyDialog").classList.remove("show");
	      $("manualCopyText").value = "";
	      setDialogOpenState();
	    }

	    function confirmAction(options = {}) {
	      const dialog = $("confirmDialog");
	      const ok = $("confirmOk");
	      const cancel = $("cancelConfirm");
	      $("confirmTitle").textContent = options.title || "确认操作";
	      $("confirmMessage").textContent = options.message || "确定要继续吗？";
	      ok.textContent = options.confirmText || "确定";
	      ok.classList.toggle("danger", Boolean(options.danger));
	      dialog.classList.add("show");
	      setDialogOpenState();
	      return new Promise((resolve) => {
	        function cleanup(result) {
	          dialog.classList.remove("show");
	          setDialogOpenState();
	          ok.removeEventListener("click", onOk);
	          cancel.removeEventListener("click", onCancel);
	          dialog.removeEventListener("click", onBackdrop);
	          document.removeEventListener("keydown", onKey);
	          resolve(result);
	        }
	        function onOk() { cleanup(true); }
	        function onCancel() { cleanup(false); }
	        function onBackdrop(event) {
	          if (event.target === dialog) cleanup(false);
	        }
	        function onKey(event) {
	          if (event.key === "Escape") cleanup(false);
	        }
	        ok.addEventListener("click", onOk);
	        cancel.addEventListener("click", onCancel);
	        dialog.addEventListener("click", onBackdrop);
	        document.addEventListener("keydown", onKey);
	        setTimeout(() => cancel.focus(), 0);
	      });
	    }

	    function resetStreamState() {
	      if (state.streamTimer) clearTimeout(state.streamTimer);
	      state.streamMessage = null;
	      state.streamQueue = "";
	      state.streamTimer = null;
	      state.streamResolve = null;
	      state.firstTokenAt = null;
	    }

	    function setSendingUI(isSending) {
	      const send = $("send");
	      state.sending = Boolean(isSending);
	      send.disabled = false;
	      send.classList.toggle("is-stop", state.sending);
	      send.title = state.sending ? "停止生成" : "发送";
	      if (state.sending) $("webSearchToggle").disabled = true;
	    }

	    function stopGeneration() {
	      if (!state.sending) return;
	      state.userStopped = true;
	      setStatus("chatStatus", "正在停止...", "");
	      if (state.abortController) state.abortController.abort();
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

	    async function sendMessage(contentOverride = "", options = {}) {
      const hasOverride = typeof contentOverride === "string" && contentOverride.trim();
      const content = (hasOverride ? contentOverride : $("prompt").value).trim();
      if (!content || state.sending) return;
      let selectedModelId = $("modelSelect").value;
      if (!selectedModelId) return setStatus("chatStatus", "先选择模型", "err");
      if (state.newConversationPromise) {
        setStatus("chatStatus", "正在准备新对话...", "");
        try {
          await state.newConversationPromise;
          selectedModelId = $("modelSelect").value || selectedModelId;
        } catch (err) {
          setStatus("chatStatus", friendlyError(err, "新建对话失败，稍后再试一下。"), "err");
          return;
        }
      }

      if (!state.currentConversation || state.currentConversation.model_id !== selectedModelId) {
        try {
          await newConversation(selectedModelId);
        } catch (err) {
          setStatus("chatStatus", friendlyError(err, "新建对话失败，稍后再试一下。"), "err");
          return;
        }
      }
	      if (!state.currentConversation) return;

	      setStatus("chatStatus", "");
	      resetStreamState();
	      state.userStopped = false;
	      state.abortController = new AbortController();
	      const mode = state.searchConfig?.mode || "auto";
	      const useWebSearch = $("webSearchToggle").checked && !$("webSearchToggle").disabled;
	      setSendingUI(true);
	      if (!hasOverride) {
	        $("prompt").value = "";
	        autosizePrompt();
	      }
	      const sentAt = Math.floor(Date.now() / 1000);
	      state.messages.push({ role: "user", content, created_at: sentAt });
	      const assistant = { role: "assistant", content: "", reasoning_content: "", sources: [], thinking: true, created_at: sentAt };
	      state.messages.push(assistant);
	      state.followOutput = true;
	      state.hasNewWhilePaused = false;
	      renderMessages({ forceScroll: true });
	      const searchStatusText = options.statusText || (
	        mode === "always" ? "正在联网搜索..." :
	        mode === "auto" ? (useWebSearch ? "正在联网搜索..." : "AI 思考中，必要时会自动联网...") :
	        (useWebSearch ? "正在联网搜索..." : "AI 思考中...")
	      );
	      setStatus("chatStatus", searchStatusText, "");

	      try {
	        const res = await api(`/api/conversations/${state.currentConversation.id}/messages`, {
	          method: "POST",
	          body: JSON.stringify({ content, web_search: useWebSearch }),
	          signal: state.abortController.signal
	        });
        if (!res.ok) throw new Error(await readError(res, "发送失败，稍后再试一下。"));
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
	              if (event.type === "search_status") {
	                assistant.sources = event.sources || [];
	                if (event.count) setStatus("chatStatus", "找到 " + event.count + " 个来源，正在生成...", "ok");
	                updateStreamingMessage(assistant);
	                continue;
	              }
	              if (event.usage) {
	                assistant.usage = event.usage;
	                updateStreamingMessage(assistant);
	              }
	              if (event.type === "message_saved" && event.message_id) {
	                assistant.id = event.message_id;
	                assistant.favorite_id = null;
	                assistant.usage = event.usage || assistant.usage || null;
	                updateStreamingMessage(assistant);
	                continue;
	              }
	              const choice = event.choices?.[0] || {};
	              const piece = choice.delta?.content || choice.message?.content || "";
	              const reasoningPiece =
	                choice.delta?.reasoning_content ||
	                choice.message?.reasoning_content ||
	                choice.delta?.reasoning ||
	                choice.message?.reasoning ||
	                choice.delta?.thinking ||
	                choice.message?.thinking ||
	                "";
	              if (reasoningPiece) {
	                assistant.reasoning_content = (assistant.reasoning_content || "") + reasoningPiece;
	                updateStreamingMessage(assistant);
	              }
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
	        if (state.userStopped || err?.name === "AbortError") {
	          if (assistant.content) {
	            enqueueAssistantText(assistant, "\n\n（已停止生成）");
	            await drainAssistantQueue();
	          } else {
	            assistant.content = "已停止生成。";
	            updateStreamingMessage(assistant);
	          }
	          setStatus("chatStatus", "已停止生成", "");
	        } else {
	          const message = friendlyError(err, "发送失败，稍后再试一下。");
	          enqueueAssistantText(assistant, "\n" + message);
	          await drainAssistantQueue();
	          setStatus("chatStatus", message, "err");
	        }
	      } finally {
	        if (assistant.thinking) {
	          assistant.thinking = false;
	          updateStreamingMessage(assistant);
	        }
	        state.abortController = null;
	        state.userStopped = false;
	        setSendingUI(false);
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
	      const ok = await confirmAction({
	        title: "删除对话",
	        message: `确定删除“${conv.title}”吗？删除后会从这里移除。`,
	        confirmText: "删除",
	        danger: true
	      });
	      if (!ok) return;
	      const res = await api(`/api/conversations/${id}`, { method: "DELETE" });
	      if (!res.ok) {
	        setStatus("chatStatus", await readError(res, "删除失败，稍后再试一下。"), "err");
	        return;
	      }
	      state.editingConversationId = null;
	      if (state.currentConversation?.id === id) {
	        state.currentConversation = null;
	        state.messages = [];
	      }
	      await loadConversations();
	      if (!state.currentConversation) renderEmpty();
	    }

	    function openSettings() {
	      $("sidebar").classList.remove("show");
	      document.body.classList.remove("sidebar-open");
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
	        setStatus("searchStatus", await readError(res, "搜索配置保存失败，稍后再试一下。"), "err");
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
        setStatus("modelStatus", await readError(res, "模型保存失败，请检查名称、地址和模型 ID。"), "err");
        return;
      }
      resetModelForm();
      setStatus("modelStatus", "模型已保存", "ok");
      await loadAdminModels();
      await loadModels();
    }

    async function deleteModel(id) {
      const ok = await confirmAction({
        title: "删除模型",
        message: "确定删除这个模型吗？已有对话会保留，关联中的模型会改为停用。",
        confirmText: "删除",
        danger: true
      });
      if (!ok) return;
      const res = await adminApi(`/api/admin/models/${id}`, { method: "DELETE" });
      if (!res.ok) {
        setStatus("modelStatus", await readError(res, "删除模型失败，稍后再试一下。"), "err");
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
        setStatus("adminStatus", await readError(res, "密码修改失败，请确认新密码至少 8 位。"), "err");
        return;
      }
      $("familyPassword").value = "";
      setStatus("adminStatus", "登录密码已修改，需要重新登录", "ok");
    }

    function openSidebar() {
      $("sidebar").classList.add("show");
      $("drawerMask").classList.add("show");
      document.body.classList.add("sidebar-open");
    }
    function closeSidebar() {
      $("sidebar").classList.remove("show");
      document.body.classList.remove("sidebar-open");
      if (!$("settingsDrawer").classList.contains("show")) $("drawerMask").classList.remove("show");
    }
    function autosizePrompt() {
      const el = $("prompt");
      el.style.height = "auto";
      el.style.height = Math.min(el.scrollHeight, 180) + "px";
    }

    $("loginForm").addEventListener("submit", login);
    $("logout").addEventListener("click", logout);
    $("newChat").addEventListener("click", () => {
      newConversation().catch((err) => setStatus("chatStatus", friendlyError(err, "新建对话失败，稍后再试一下。"), "err"));
    });
    $("openPrompts").addEventListener("click", openPromptLibrary);
    document.querySelectorAll(".prompt-chip[data-prompt-text]").forEach((button) => {
      button.addEventListener("click", () => insertPromptText(button.dataset.promptText || ""));
    });
    $("openPromptLibrary").addEventListener("click", openPromptLibrary);
    $("closePromptDialog").addEventListener("click", closePromptLibrary);
    $("promptDialog").addEventListener("click", (event) => {
      if (event.target === $("promptDialog")) closePromptLibrary();
    });
    $("savePromptTemplate").addEventListener("click", savePromptTemplate);
    $("resetPromptTemplate").addEventListener("click", resetPromptForm);
    $("openFavorites").addEventListener("click", openFavorites);
    $("closeFavoriteDialog").addEventListener("click", closeFavorites);
    $("favoriteDialog").addEventListener("click", (event) => {
      if (event.target === $("favoriteDialog")) closeFavorites();
    });
    $("refreshConversations").addEventListener("click", loadConversations);
    $("send").addEventListener("click", () => {
      if (state.sending) stopGeneration();
      else sendMessage();
    });
    $("deleteConversation").addEventListener("click", deleteCurrentConversation);
    $("messages").addEventListener("scroll", handleMessagesScroll, { passive: true });
    $("scrollLatest").addEventListener("click", () => scrollToLatest("smooth"));
    $("prompt").addEventListener("input", autosizePrompt);
    $("prompt").addEventListener("focus", handlePromptFocus);
    $("prompt").addEventListener("compositionstart", () => {
      state.isComposing = true;
    });
    $("prompt").addEventListener("compositionend", () => {
      state.isComposing = false;
      state.lastCompositionEndAt = Date.now();
    });
    $("prompt").addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        if (isImeEnter(event)) {
          if (!event.isComposing && !state.isComposing && event.keyCode !== 229) {
            event.preventDefault();
          }
          return;
        }
        event.preventDefault();
        if (!state.sending) sendMessage();
      }
    });
    $("themeToggle").addEventListener("click", toggleTheme);
    $("accentToggle").addEventListener("click", openAccentDialog);
    $("fontSizeToggle").addEventListener("click", toggleFontSize);
    $("closeAccentDialog").addEventListener("click", closeAccentDialog);
    $("accentDialog").addEventListener("click", (event) => {
      if (event.target === $("accentDialog")) closeAccentDialog();
    });
    $("applyCustomAccent").addEventListener("click", applyCustomAccent);
    $("resetAccent").addEventListener("click", resetAccent);
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
	    syncViewportHeight();
	    window.addEventListener("resize", syncViewportHeight, { passive: true });
	    window.visualViewport?.addEventListener("resize", syncViewportHeight, { passive: true });
	    window.visualViewport?.addEventListener("scroll", syncViewportHeight, { passive: true });

	    bootstrap();
  </script>
</body>
</html>'''


if __name__ == "__main__":
    main()
