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
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse


DATA_DIR = Path(os.environ.get("AI_PLATFORM_DATA", "/opt/ai-platform"))
APP_DIR = Path(__file__).resolve().parent
RES_DIR = APP_DIR / "res"
HOME_PAGE_PATH = APP_DIR / "index.html"
CAT_PAGE_PATH = APP_DIR / "cat.html"
CHANGELOG_PATH = APP_DIR / "CHANGELOG.md"
VERSION_PATH = APP_DIR / "VERSION"
LISTEN = os.environ.get("AI_PLATFORM_LISTEN", ":8080")
DB_PATH = DATA_DIR / "ai-platform.db"
SECRETS_PATH = DATA_DIR / "secrets.json"
ADMIN_KEY_PATH = DATA_DIR / "admin.key"
FAMILY_PASSWORD_PATH = DATA_DIR / "family_password.txt"
LEGACY_CONFIG_PATH = DATA_DIR / "config.json"
SESSION_COOKIE = "ap_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
CAT_SESSION_COOKIE = "cat_session"
CAT_SESSION_TTL_SECONDS = 60 * 60 * 24 * 30
CAT_OSS_DIR = "cat"
CAT_MAX_IMAGE_BYTES = 12 * 1024 * 1024
CHAT_IMAGE_OSS_DIR = "chat-images"
CHAT_IMAGE_MAX_BYTES = 20 * 1024 * 1024
CHAT_IMAGE_MAX_COUNT = 5
CHAT_IMAGE_ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
CHAT_IMAGE_ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
MEDIA_OSS_DIR = "tingwu"
MEDIA_MAX_UPLOAD_BYTES = int(os.environ.get("MEDIA_MAX_UPLOAD_MB", "500") or "500") * 1024 * 1024
MEDIA_ALLOWED_EXTENSIONS = {".mp3", ".mp4", ".m4a", ".wav", ".aac", ".flac", ".mov", ".avi", ".mkv", ".webm"}
CAT_GUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_-]{2,32}$")
DEFAULT_AI_USER_ID = "default"


def now() -> int:
    return int(time.time())


def iso_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def today_text() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def current_year() -> str:
    return time.strftime("%Y", time.localtime())


def current_app_version() -> str:
    try:
        value = VERSION_PATH.read_text(encoding="utf-8").strip()
        if value:
            return value.lstrip("v")
    except OSError:
        pass
    entries = parse_changelog()
    if entries:
        return entries[0]["version"]
    return ""


def parse_changelog(limit=None):
    try:
        text = CHANGELOG_PATH.read_text(encoding="utf-8")
    except OSError:
        return []
    entries = []
    current = None

    def finish_entry():
        if not current:
            return
        points = current["points"]
        title = ""
        for point in points:
            if "版本号同步" not in point and "全站版本号" not in point:
                title = point.rstrip("。")
                break
        if not title and points:
            title = points[0].rstrip("。")
        current["title"] = title or "更新内容"
        entries.append(current.copy())

    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = re.match(r"^##\s+v?([0-9][^\s]*)\s*(?:-\s*(.+?))?\s*$", line)
        if match:
            finish_entry()
            date_text = (match.group(2) or "").strip()
            current = {
                "version": match.group(1).strip().lstrip("v"),
                "date": date_text,
                "title": "",
                "points": [],
                "commit": "",
            }
            continue
        if not current:
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", line)
        if bullet:
            point = bullet.group(1).strip()
            if point:
                current["points"].append(point)
            continue
        commit = re.search(r"\b([0-9a-f]{7,40})\b", line, re.I)
        if commit and not current.get("commit"):
            current["commit"] = commit.group(1)[:12]
    finish_entry()
    if limit is not None:
        return entries[: max(0, int(limit))]
    return entries


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


def table_columns(conn, table):
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_default_ai_user(conn, secrets_data):
    count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    if count == 0:
        ts = now()
        conn.execute(
            """
            INSERT INTO users
            (id, username, display_name, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'admin', 1, ?, ?)
            """,
            (
                DEFAULT_AI_USER_ID,
                "admin",
                "默认账号",
                secrets_data.get("family_password_hash") or password_hash("admin-" + b64_token(8)),
                ts,
                ts,
            ),
        )
        return DEFAULT_AI_USER_ID

    row = conn.execute(
        """
        SELECT id
        FROM users
        ORDER BY CASE WHEN role='admin' THEN 0 ELSE 1 END, created_at ASC
        LIMIT 1
        """
    ).fetchone()
    return row["id"] if row else DEFAULT_AI_USER_ID


def init_db(secrets_data=None):
    secrets_data = secrets_data or read_json(SECRETS_PATH, {})
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
              supports_vision INTEGER NOT NULL DEFAULT 0,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY,
              username TEXT NOT NULL UNIQUE,
              display_name TEXT NOT NULL,
              password_hash TEXT NOT NULL,
              role TEXT NOT NULL DEFAULT 'family',
              is_active INTEGER NOT NULL DEFAULT 1,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS conversations (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL DEFAULT 'default',
              title TEXT NOT NULL,
              model_id TEXT NOT NULL,
              archived INTEGER NOT NULL DEFAULT 0,
              pinned INTEGER NOT NULL DEFAULT 0,
              pinned_at INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              FOREIGN KEY (model_id) REFERENCES models(id)
            );

            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL DEFAULT 'default',
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

            CREATE TABLE IF NOT EXISTS chat_message_images (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              session_id TEXT NOT NULL DEFAULT '',
              message_id INTEGER NOT NULL DEFAULT 0,
              filename TEXT NOT NULL,
              mime_type TEXT NOT NULL DEFAULT '',
              file_size INTEGER NOT NULL DEFAULT 0,
              oss_key TEXT NOT NULL UNIQUE,
              oss_url TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS prompt_templates (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL DEFAULT '',
              title TEXT NOT NULL,
              content TEXT NOT NULL,
              sort_order INTEGER NOT NULL DEFAULT 0,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_profiles (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              title TEXT NOT NULL,
              content TEXT NOT NULL,
              type TEXT NOT NULL DEFAULT 'profile',
              sort_order INTEGER NOT NULL DEFAULT 0,
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS favorite_messages (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL DEFAULT 'default',
              message_id INTEGER NOT NULL UNIQUE,
              conversation_id TEXT NOT NULL,
              conversation_title TEXT NOT NULL,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              message_created_at INTEGER NOT NULL,
              created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS media_analysis_tasks (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              filename TEXT NOT NULL,
              mime_type TEXT NOT NULL DEFAULT '',
              file_size INTEGER NOT NULL DEFAULT 0,
              oss_key TEXT NOT NULL,
              file_url TEXT NOT NULL DEFAULT '',
              file_url_expires_at INTEGER NOT NULL DEFAULT 0,
              task_id TEXT NOT NULL DEFAULT '',
              task_key TEXT NOT NULL DEFAULT '',
              source_language TEXT NOT NULL DEFAULT 'cn',
              status TEXT NOT NULL DEFAULT 'uploaded',
              raw_result_json TEXT NOT NULL DEFAULT '',
              transcript_text TEXT NOT NULL DEFAULT '',
              summary_text TEXT NOT NULL DEFAULT '',
              outline_text TEXT NOT NULL DEFAULT '',
              enhanced_summary TEXT NOT NULL DEFAULT '',
              key_points TEXT NOT NULL DEFAULT '',
              mindmap_text TEXT NOT NULL DEFAULT '',
              copywriting_text TEXT NOT NULL DEFAULT '',
              ai_outputs_json TEXT NOT NULL DEFAULT '',
              conversation_id TEXT NOT NULL DEFAULT '',
              error_message TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
              token_hash TEXT PRIMARY KEY,
              user_id TEXT NOT NULL DEFAULT 'default',
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cat_users (
              id TEXT PRIMARY KEY,
              username TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              nickname TEXT NOT NULL,
              avatar_url TEXT NOT NULL DEFAULT '',
              role TEXT NOT NULL DEFAULT 'member',
              status TEXT NOT NULL DEFAULT 'active',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cat_sessions (
              token_hash TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              expires_at INTEGER NOT NULL,
              FOREIGN KEY (user_id) REFERENCES cat_users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS cat_images (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              oss_key TEXT NOT NULL UNIQUE,
              image_url TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              FOREIGN KEY (user_id) REFERENCES cat_users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS cats (
              id TEXT PRIMARY KEY,
              owner_user_id TEXT NOT NULL,
              name TEXT NOT NULL,
              avatar_url TEXT NOT NULL DEFAULT '',
              breed TEXT NOT NULL DEFAULT '',
              gender TEXT NOT NULL DEFAULT '',
              birthday TEXT NOT NULL DEFAULT '',
              description TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              FOREIGN KEY (owner_user_id) REFERENCES cat_users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS cat_posts (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              cat_id TEXT NOT NULL DEFAULT '',
              title TEXT NOT NULL,
              content TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'published',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              FOREIGN KEY (user_id) REFERENCES cat_users(id)
            );

            CREATE TABLE IF NOT EXISTS cat_post_images (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              post_id TEXT NOT NULL,
              image_id TEXT,
              image_url TEXT NOT NULL,
              sort_order INTEGER NOT NULL DEFAULT 0,
              FOREIGN KEY (post_id) REFERENCES cat_posts(id) ON DELETE CASCADE,
              FOREIGN KEY (image_id) REFERENCES cat_images(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS cat_post_likes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              post_id TEXT NOT NULL,
              actor_key TEXT NOT NULL,
              actor_type TEXT NOT NULL,
              actor_name TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              UNIQUE(post_id, actor_key),
              FOREIGN KEY (post_id) REFERENCES cat_posts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS cat_comments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              post_id TEXT NOT NULL,
              actor_key TEXT NOT NULL,
              actor_type TEXT NOT NULL,
              actor_name TEXT NOT NULL,
              content TEXT NOT NULL,
              created_at INTEGER NOT NULL,
              FOREIGN KEY (post_id) REFERENCES cat_posts(id) ON DELETE CASCADE
            );
            """
        )

        default_user_id = ensure_default_ai_user(conn, secrets_data)

        model_columns = table_columns(conn, "models")
        if "supports_vision" not in model_columns:
            conn.execute("ALTER TABLE models ADD COLUMN supports_vision INTEGER NOT NULL DEFAULT 0")
        conversation_columns = table_columns(conn, "conversations")
        if "user_id" not in conversation_columns:
            conn.execute(
                f"ALTER TABLE conversations ADD COLUMN user_id TEXT NOT NULL DEFAULT '{DEFAULT_AI_USER_ID}'"
            )
        if "pinned" not in conversation_columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
        if "pinned_at" not in conversation_columns:
            conn.execute("ALTER TABLE conversations ADD COLUMN pinned_at INTEGER NOT NULL DEFAULT 0")
        message_columns = table_columns(conn, "messages")
        if "user_id" not in message_columns:
            conn.execute(
                f"ALTER TABLE messages ADD COLUMN user_id TEXT NOT NULL DEFAULT '{DEFAULT_AI_USER_ID}'"
            )
        if "reasoning_content" not in message_columns:
            conn.execute(
                "ALTER TABLE messages ADD COLUMN reasoning_content TEXT NOT NULL DEFAULT ''"
            )
        for column in ("prompt_tokens", "completion_tokens", "total_tokens"):
            if column not in message_columns:
                conn.execute(
                    f"ALTER TABLE messages ADD COLUMN {column} INTEGER NOT NULL DEFAULT 0"
                )
        favorite_columns = table_columns(conn, "favorite_messages")
        if "user_id" not in favorite_columns:
            conn.execute(
                f"ALTER TABLE favorite_messages ADD COLUMN user_id TEXT NOT NULL DEFAULT '{DEFAULT_AI_USER_ID}'"
            )
        prompt_columns = table_columns(conn, "prompt_templates")
        if "user_id" not in prompt_columns:
            conn.execute("ALTER TABLE prompt_templates ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
        session_columns = table_columns(conn, "sessions")
        if "user_id" not in session_columns:
            conn.execute(
                f"ALTER TABLE sessions ADD COLUMN user_id TEXT NOT NULL DEFAULT '{DEFAULT_AI_USER_ID}'"
            )
        media_columns = table_columns(conn, "media_analysis_tasks")
        if "conversation_id" not in media_columns:
            conn.execute("ALTER TABLE media_analysis_tasks ADD COLUMN conversation_id TEXT NOT NULL DEFAULT ''")
        for column in ("enhanced_summary", "key_points", "mindmap_text", "copywriting_text", "ai_outputs_json"):
            if column not in media_columns:
                conn.execute(f"ALTER TABLE media_analysis_tasks ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")

        conn.execute("UPDATE conversations SET user_id=? WHERE user_id='' OR user_id IS NULL", (default_user_id,))
        conn.execute(
            """
            UPDATE messages
            SET user_id=COALESCE((SELECT user_id FROM conversations WHERE conversations.id=messages.conversation_id), ?)
            WHERE user_id='' OR user_id IS NULL
            """,
            (default_user_id,),
        )
        conn.execute(
            """
            UPDATE favorite_messages
            SET user_id=COALESCE((SELECT user_id FROM conversations WHERE conversations.id=favorite_messages.conversation_id), ?)
            WHERE user_id='' OR user_id IS NULL
            """,
            (default_user_id,),
        )
        conn.execute("UPDATE sessions SET user_id=? WHERE user_id='' OR user_id IS NULL", (default_user_id,))
        conn.execute(
            "UPDATE conversations SET user_id=? WHERE user_id=? AND NOT EXISTS (SELECT 1 FROM users WHERE id=conversations.user_id)",
            (default_user_id, DEFAULT_AI_USER_ID),
        )
        conn.execute(
            "UPDATE messages SET user_id=? WHERE user_id=? AND NOT EXISTS (SELECT 1 FROM users WHERE id=messages.user_id)",
            (default_user_id, DEFAULT_AI_USER_ID),
        )
        conn.execute(
            "UPDATE favorite_messages SET user_id=? WHERE user_id=? AND NOT EXISTS (SELECT 1 FROM users WHERE id=favorite_messages.user_id)",
            (default_user_id, DEFAULT_AI_USER_ID),
        )
        conn.execute(
            "UPDATE sessions SET user_id=? WHERE user_id=? AND NOT EXISTS (SELECT 1 FROM users WHERE id=sessions.user_id)",
            (default_user_id, DEFAULT_AI_USER_ID),
        )

        conn.execute("CREATE INDEX IF NOT EXISTS idx_conversations_user_updated ON conversations(user_id, archived, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_user_conversation ON messages(user_id, conversation_id, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_images_user_session ON chat_message_images(user_id, session_id, message_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user_created ON favorite_messages(user_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_profiles_user_sort ON user_profiles(user_id, sort_order ASC, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_media_tasks_user_updated ON media_analysis_tasks(user_id, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_media_tasks_task_id ON media_analysis_tasks(task_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_media_tasks_conversation ON media_analysis_tasks(conversation_id)")

        cat_post_columns = table_columns(conn, "cat_posts")
        if "cat_id" not in cat_post_columns:
            conn.execute("ALTER TABLE cat_posts ADD COLUMN cat_id TEXT NOT NULL DEFAULT ''")

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
                (id, name, provider, base_url, api_key, model, system_prompt, supports_vision, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?, ?)
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
                    INSERT INTO prompt_templates(id, user_id, title, content, sort_order, created_at, updated_at)
                    VALUES (?, '', ?, ?, ?, ?, ?)
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
        "supports_vision": bool(row["supports_vision"]) if "supports_vision" in row.keys() else False,
        "enabled": bool(row["enabled"]),
        "has_api_key": bool(row["api_key"].strip()),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def private_model(row):
	return public_model(row)


def ai_user_public(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def conversation_row(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "model_id": row["model_id"],
        "model_name": row["model_name"],
        "model": row["model"],
        "supports_vision": bool(row["supports_vision"]) if "supports_vision" in row.keys() else False,
        "pinned": bool(row["pinned"]) if "pinned" in row.keys() else False,
        "pinned_at": row["pinned_at"] if "pinned_at" in row.keys() else 0,
        "updated_at": row["updated_at"],
        "created_at": row["created_at"],
    }


def estimate_profile_tokens(text) -> int:
    value = str(text or "")
    cjk = sum(1 for char in value if "\u4e00" <= char <= "\u9fff")
    other = max(0, len(value) - cjk)
    return max(0, int(cjk * 0.8 + other / 4))


def user_profile_row(row):
    title = row["title"]
    content = row["content"]
    text = f"{title}\n{content}"
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "title": title,
        "content": content,
        "type": row["type"],
        "sort_order": row["sort_order"],
        "enabled": bool(row["enabled"]),
        "char_count": len(text),
        "token_estimate": estimate_profile_tokens(text),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def profile_totals(rows):
    enabled_rows = [row for row in rows if bool(row["enabled"])]
    all_text = "\n".join(f"{row['title']}\n{row['content']}" for row in enabled_rows)
    return {
        "enabled_count": len(enabled_rows),
        "total_count": len(rows),
        "char_count": len(all_text),
        "token_estimate": estimate_profile_tokens(all_text),
    }


def build_user_profile_context(rows):
    enabled_rows = [row for row in rows if bool(row["enabled"]) and str(row["content"] or "").strip()]
    if not enabled_rows:
        return ""
    parts = ["用户长期档案："]
    for row in enabled_rows:
        title = str(row["title"] or "").strip() or "未命名"
        content = str(row["content"] or "").strip()
        parts.append(f"【{title}】\n{content}")
    return "\n\n".join(parts)


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


def media_task_public(row):
    return {
        "id": row["id"],
        "filename": row["filename"],
        "mime_type": row["mime_type"],
        "file_size": row["file_size"],
        "task_id": row["task_id"],
        "task_key": row["task_key"],
        "source_language": row["source_language"],
        "status": row["status"],
        "transcript_text": row["transcript_text"],
        "summary_text": row["summary_text"],
        "outline_text": row["outline_text"],
        "enhanced_summary": row["enhanced_summary"],
        "key_points": row["key_points"],
        "mindmap_text": row["mindmap_text"],
        "copywriting_text": row["copywriting_text"],
        "ai_outputs_json": row["ai_outputs_json"],
        "conversation_id": row["conversation_id"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def compact_search_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def search_snippet(text, query, limit=140):
    value = compact_search_text(text)
    if not value:
        return ""
    needle = compact_search_text(query).lower()
    lower = value.lower()
    index = lower.find(needle) if needle else -1
    if index < 0:
        return value[:limit].rstrip() + ("..." if len(value) > limit else "")
    start = max(0, index - 46)
    end = min(len(value), index + len(needle) + 86)
    snippet = value[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(value):
        snippet += "..."
    return snippet


def like_escape(text):
    return str(text or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_result_row(result_id, result_type, session_id, message_id, title, snippet, role, created_at, score):
    return {
        "id": str(result_id),
        "type": result_type,
        "session_id": session_id or "",
        "message_id": int(message_id or 0),
        "title": title or "未命名对话",
        "snippet": snippet or "",
        "role": role or "",
        "created_at": int(created_at or 0),
        "score": int(score or 0),
    }


def clip_context_text(text, limit):
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + f"\n\n（以上内容较长，已截取前 {limit} 字用于本次 AI 加工上下文。）"


def media_analysis_has_context(row):
    return any(
        str(row[key] or "").strip()
        for key in ("summary_text", "outline_text", "transcript_text", "enhanced_summary", "key_points", "mindmap_text", "copywriting_text")
    )


def media_analysis_context(row):
    filename = str(row["filename"] or "音视频文件").strip()
    sections = [
        "你正在协助用户基于一段音视频分析结果进行后续内容加工。",
        "请优先依据下面的分析上下文回答用户问题，不要要求用户重复上传音视频。",
        "如果用户要求二创，请直接基于上下文生成可用内容；如果信息不足，再简短说明需要补充什么。",
        f"文件名：{filename}",
    ]
    section_specs = [
        ("AI深度总结", row["enhanced_summary"], 16000),
        ("核心观点", row["key_points"], 12000),
        ("智能摘要", row["summary_text"], 12000),
        ("章节要点", row["outline_text"], 20000),
        ("转写全文", row["transcript_text"], 60000),
        ("思维导图", row["mindmap_text"], 12000),
        ("可复制文案", row["copywriting_text"], 12000),
    ]
    for title, value, limit in section_specs:
        clipped = clip_context_text(value, limit)
        if clipped:
            sections.append(f"\n## {title}\n{clipped}")
    return "\n".join(sections).strip()


def media_context_marker(task_id):
    return f"<!-- ai-meimei-media-task:{task_id} -->"


def media_ai_source_context(row):
    sections = [
        f"文件名：{row['filename'] or '音视频文件'}",
    ]
    for title, key, limit in (
        ("听悟智能摘要", "summary_text", 8000),
        ("听悟章节/关键词", "outline_text", 12000),
        ("听悟转写全文", "transcript_text", 36000),
    ):
        value = clip_context_text(row[key], limit)
        if value:
            sections.append(f"\n## {title}\n{value}")
    return "\n".join(sections).strip()


def extract_json_object(text):
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
        value = re.sub(r"\s*```$", "", value)
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(value[start:end + 1])
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def normalize_mermaid_mindmap(value):
    text = str(value or "").strip()
    text = re.sub(r"^```(?:mermaid)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text).strip()
    if not text:
        return ""
    if not text.lower().startswith("mindmap"):
        text = "mindmap\n  " + text.replace("\n", "\n  ")
    return text.strip()


def cat_user_public(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "nickname": row["nickname"],
        "avatar_url": row["avatar_url"],
        "role": row["role"],
        "status": row["status"],
        "created_at": row["created_at"],
    }


def cat_public(row):
    keys = set(row.keys())
    return {
        "id": row["id"],
        "owner_user_id": row["owner_user_id"],
        "name": row["name"],
        "avatar_url": row["avatar_url"],
        "breed": row["breed"],
        "gender": row["gender"],
        "birthday": row["birthday"],
        "description": row["description"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "post_count": int(row["post_count"] or 0) if "post_count" in keys else 0,
        "owner": {
            "id": row["owner_user_id"],
            "username": row["owner_username"],
            "nickname": row["owner_nickname"],
            "avatar_url": row["owner_avatar_url"],
        }
        if "owner_username" in keys
        else None,
    }


def cat_post_card(row):
    keys = set(row.keys())
    cat = None
    if "cat_id" in keys and row["cat_id"] and "cat_name" in keys and row["cat_name"]:
        cat = {
            "id": row["cat_id"],
            "name": row["cat_name"] or "",
            "avatar_url": row["cat_avatar_url"] or "",
            "breed": row["cat_breed"] or "",
            "gender": row["cat_gender"] or "",
            "birthday": row["cat_birthday"] or "",
            "description": row["cat_description"] or "",
        }
    return {
        "id": row["id"],
        "cat_id": row["cat_id"] if "cat_id" in keys else "",
        "cat": cat,
        "title": row["title"],
        "content": row["content"],
        "cover_url": row["cover_url"] or "",
        "image_count": int(row["image_count"] or 0),
        "like_count": int(row["like_count"] or 0) if "like_count" in keys else 0,
        "comment_count": int(row["comment_count"] or 0) if "comment_count" in keys else 0,
        "liked_by_me": bool(row["liked_by_me"]) if "liked_by_me" in keys else False,
        "created_at": row["created_at"],
        "author": {
            "id": row["user_id"],
            "username": row["username"],
            "nickname": row["nickname"],
            "avatar_url": row["avatar_url"],
        },
    }


def cat_comment_public(row):
    return {
        "id": row["id"],
        "post_id": row["post_id"],
        "author_type": row["actor_type"],
        "author_name": row["actor_name"],
        "content": row["content"],
        "created_at": row["created_at"],
    }


def cat_oss_config(secrets_data):
    config = secrets_data.get("cat_oss") or {}

    def read(name, key, default=""):
        return str(os.environ.get(name) or config.get(key) or default).strip()

    bucket = read("CAT_OSS_BUCKET", "bucket")
    region = read("CAT_OSS_REGION", "region")
    endpoint = read("CAT_OSS_ENDPOINT", "endpoint")
    access_key_id = read("CAT_OSS_ACCESS_KEY_ID", "access_key_id")
    access_key_secret = read("CAT_OSS_ACCESS_KEY_SECRET", "access_key_secret")
    public_base = read("CAT_OSS_PUBLIC_BASE", "public_base")
    directory = read("CAT_OSS_DIR", "dir", CAT_OSS_DIR).strip("/") or CAT_OSS_DIR

    if endpoint and not endpoint.startswith(("http://", "https://")):
        endpoint = "https://" + endpoint
    if not endpoint and bucket and region:
        endpoint = f"https://{bucket}.oss-{region}.aliyuncs.com"
    if public_base and not public_base.startswith(("http://", "https://")):
        public_base = "https://" + public_base
    if not public_base:
        public_base = endpoint

    return {
        "bucket": bucket,
        "region": region,
        "endpoint": endpoint.rstrip("/") if endpoint else "",
        "public_base": public_base.rstrip("/") if public_base else "",
        "access_key_id": access_key_id,
        "access_key_secret": access_key_secret,
        "directory": directory,
        "max_size": CAT_MAX_IMAGE_BYTES,
        "configured": bool(bucket and access_key_id and access_key_secret and endpoint),
    }


def cat_oss_prefix(config, user_id):
    date_path = time.strftime("%Y/%m/%d", time.localtime())
    return f"{config['directory'].strip('/')}/{user_id}/{date_path}/"


def cat_oss_url(config, oss_key):
    return config["public_base"].rstrip("/") + "/" + quote(oss_key, safe="/-_.~")


def chat_image_oss_config(secrets_data):
    base = cat_oss_config(secrets_data)
    config = secrets_data.get("chat_image_oss") or {}

    def read(name, key, default=""):
        return str(os.environ.get(name) or config.get(key) or default).strip()

    directory = read("CHAT_IMAGE_OSS_DIR", "dir", CHAT_IMAGE_OSS_DIR).strip("/") or CHAT_IMAGE_OSS_DIR
    return {
        **base,
        "directory": directory,
        "max_size": CHAT_IMAGE_MAX_BYTES,
        "configured": bool(base["bucket"] and base["access_key_id"] and base["access_key_secret"] and base["endpoint"]),
    }


def chat_image_prefix(config, user_id):
    date_path = time.strftime("%Y/%m/%d", time.localtime())
    return f"{config['directory'].strip('/')}/{user_id}/{date_path}/"


def chat_image_upload_policy(config, user_id):
    prefix = chat_image_prefix(config, user_id)
    expiration = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() + 600))
    policy = {
        "expiration": expiration,
        "conditions": [
            ["starts-with", "$key", prefix],
            ["starts-with", "$Content-Type", "image/"],
            ["content-length-range", 1, config["max_size"]],
        ],
    }
    encoded_policy = base64.b64encode(
        json.dumps(policy, separators=(",", ":")).encode()
    ).decode()
    signature = base64.b64encode(
        hmac.new(config["access_key_secret"].encode(), encoded_policy.encode(), hashlib.sha1).digest()
    ).decode()
    return {
        "host": config["endpoint"],
        "access_key_id": config["access_key_id"],
        "policy": encoded_policy,
        "signature": signature,
        "key_prefix": prefix,
        "max_size": config["max_size"],
        "max_count": CHAT_IMAGE_MAX_COUNT,
        "allowed_extensions": sorted(CHAT_IMAGE_ALLOWED_EXTENSIONS),
        "allowed_mime_types": sorted(CHAT_IMAGE_ALLOWED_MIME_TYPES),
        "expires_at": now() + 600,
    }


def chat_image_public(row):
    return {
        "id": row["id"],
        "filename": row["filename"],
        "mime_type": row["mime_type"],
        "file_size": row["file_size"],
        "view_url": f"/api/chat-images/{row['id']}/view",
        "created_at": row["created_at"],
    }


def cat_upload_policy(config, user_id):
    prefix = cat_oss_prefix(config, user_id)
    expiration = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() + 600))
    policy = {
        "expiration": expiration,
        "conditions": [
            ["starts-with", "$key", prefix],
            ["starts-with", "$Content-Type", "image/"],
            ["content-length-range", 1, config["max_size"]],
        ],
    }
    encoded_policy = base64.b64encode(
        json.dumps(policy, separators=(",", ":")).encode()
    ).decode()
    signature = base64.b64encode(
        hmac.new(
            config["access_key_secret"].encode(),
            encoded_policy.encode(),
            hashlib.sha1,
        ).digest()
    ).decode()
    return {
        "host": config["endpoint"],
        "access_key_id": config["access_key_id"],
        "policy": encoded_policy,
        "signature": signature,
        "key_prefix": prefix,
        "public_base": config["public_base"],
        "max_size": config["max_size"],
        "expires_at": now() + 600,
    }


def media_oss_config(secrets_data):
    cat_config = cat_oss_config(secrets_data)
    config = secrets_data.get("media_oss") or {}

    def read(name, key, fallback=""):
        return str(os.environ.get(name) or config.get(key) or fallback).strip()

    bucket = read("MEDIA_OSS_BUCKET", "bucket", cat_config["bucket"])
    region = read("MEDIA_OSS_REGION", "region", cat_config["region"])
    endpoint = read("MEDIA_OSS_ENDPOINT", "endpoint", cat_config["endpoint"])
    access_key_id = read("MEDIA_OSS_ACCESS_KEY_ID", "access_key_id", cat_config["access_key_id"])
    access_key_secret = read("MEDIA_OSS_ACCESS_KEY_SECRET", "access_key_secret", cat_config["access_key_secret"])
    public_base = read("MEDIA_OSS_PUBLIC_BASE", "public_base", cat_config["public_base"])
    directory = read("MEDIA_OSS_DIR", "dir", MEDIA_OSS_DIR).strip("/") or MEDIA_OSS_DIR
    try:
        max_size = int(read("MEDIA_MAX_UPLOAD_BYTES", "max_size", str(MEDIA_MAX_UPLOAD_BYTES)))
    except ValueError:
        max_size = MEDIA_MAX_UPLOAD_BYTES

    if endpoint and not endpoint.startswith(("http://", "https://")):
        endpoint = "https://" + endpoint
    if not endpoint and bucket and region:
        endpoint = f"https://{bucket}.oss-{region}.aliyuncs.com"
    if public_base and not public_base.startswith(("http://", "https://")):
        public_base = "https://" + public_base
    if not public_base:
        public_base = endpoint

    return {
        "bucket": bucket,
        "region": region,
        "endpoint": endpoint.rstrip("/") if endpoint else "",
        "public_base": public_base.rstrip("/") if public_base else "",
        "access_key_id": access_key_id,
        "access_key_secret": access_key_secret,
        "directory": directory,
        "max_size": max(1024 * 1024, max_size),
        "configured": bool(bucket and access_key_id and access_key_secret and endpoint),
    }


def media_oss_prefix(config, user_id):
    date_path = time.strftime("%Y/%m/%d", time.localtime())
    return f"{config['directory'].strip('/')}/{user_id}/{date_path}/"


def media_upload_policy(config, user_id):
    prefix = media_oss_prefix(config, user_id)
    expiration = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() + 600))
    policy = {
        "expiration": expiration,
        "conditions": [
            ["starts-with", "$key", prefix],
            ["content-length-range", 1, config["max_size"]],
        ],
    }
    encoded_policy = base64.b64encode(
        json.dumps(policy, separators=(",", ":")).encode()
    ).decode()
    signature = base64.b64encode(
        hmac.new(
            config["access_key_secret"].encode(),
            encoded_policy.encode(),
            hashlib.sha1,
        ).digest()
    ).decode()
    return {
        "host": config["endpoint"],
        "access_key_id": config["access_key_id"],
        "policy": encoded_policy,
        "signature": signature,
        "key_prefix": prefix,
        "public_base": config["public_base"],
        "max_size": config["max_size"],
        "allowed_extensions": sorted(MEDIA_ALLOWED_EXTENSIONS),
        "expires_at": now() + 600,
    }


def oss_signed_get_url(config, oss_key, expires_seconds=21600):
    expires = now() + max(600, int(expires_seconds))
    canonical_resource = f"/{config['bucket']}/{oss_key}"
    string_to_sign = "GET\n\n\n{}\n{}".format(expires, canonical_resource)
    signature = base64.b64encode(
        hmac.new(config["access_key_secret"].encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    query = urlencode(
        {
            "OSSAccessKeyId": config["access_key_id"],
            "Expires": str(expires),
            "Signature": signature,
        }
    )
    base = config["public_base"].rstrip("/")
    return f"{base}/{quote(oss_key, safe='/-_.~')}?{query}", expires


def tingwu_config(secrets_data):
    config = secrets_data.get("tingwu") or {}

    def read(name, key, default=""):
        return str(os.environ.get(name) or config.get(key) or default).strip()

    region = read("TINGWU_REGION", "region", "cn-beijing")
    endpoint = read("TINGWU_ENDPOINT", "endpoint", f"https://tingwu.{region}.aliyuncs.com")
    if endpoint and not endpoint.startswith(("http://", "https://")):
        endpoint = "https://" + endpoint
    return {
        "app_key": read("TINGWU_APP_KEY", "app_key"),
        "access_key_id": read("TINGWU_ACCESS_KEY_ID", "access_key_id"),
        "access_key_secret": read("TINGWU_ACCESS_KEY_SECRET", "access_key_secret"),
        "region": region,
        "endpoint": endpoint.rstrip("/") if endpoint else "",
        "version": read("TINGWU_VERSION", "version", "2023-09-30"),
    }


def tingwu_configured(config):
    return bool(config["app_key"] and config["access_key_id"] and config["access_key_secret"] and config["endpoint"])


def acs3_percent_encode(value):
    return quote(str(value), safe="-_.~")


def acs3_request(config, method, path, query, action, body=None):
    parsed = urlparse(config["endpoint"])
    host = parsed.netloc
    body_bytes = json.dumps(body or {}, ensure_ascii=False, separators=(",", ":")).encode()
    if method == "GET":
        body_bytes = b""
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    acs_date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    nonce = b64_token(18)
    headers = {
        "host": host,
        "x-acs-action": action,
        "x-acs-version": config["version"],
        "x-acs-date": acs_date,
        "x-acs-signature-nonce": nonce,
        "x-acs-content-sha256": body_hash,
    }
    if method != "GET":
        headers["content-type"] = "application/json; charset=utf-8"
    signed_keys = sorted(key for key in headers if key == "host" or key.startswith("x-acs-"))
    canonical_headers = "".join(f"{key}:{' '.join(headers[key].strip().split())}\n" for key in signed_keys)
    signed_headers = ";".join(signed_keys)
    canonical_query = "&".join(
        f"{acs3_percent_encode(key)}={acs3_percent_encode(value)}"
        for key, value in sorted((query or {}).items())
    )
    canonical_request = "\n".join(
        [method, path, canonical_query, canonical_headers, signed_headers, body_hash]
    )
    string_to_sign = "ACS3-HMAC-SHA256\n" + hashlib.sha256(canonical_request.encode()).hexdigest()
    signature = hmac.new(
        config["access_key_secret"].encode(),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()
    headers["Authorization"] = (
        "ACS3-HMAC-SHA256 "
        f"Credential={config['access_key_id']},"
        f"SignedHeaders={signed_headers},"
        f"Signature={signature}"
    )
    url = config["endpoint"] + path
    if canonical_query:
        url += "?" + canonical_query
    request = urllib.request.Request(
        url,
        data=None if method == "GET" else body_bytes,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode()
    return json.loads(raw or "{}")


def tingwu_create_task(config, file_url, task_key, source_language="cn"):
    body = {
        "AppKey": config["app_key"],
        "Input": {
            "FileUrl": file_url,
            "SourceLanguage": source_language or "cn",
            "TaskKey": task_key,
        },
        "Parameters": {
            "Transcription": {
                "DiarizationEnabled": True,
                "Diarization": {"SpeakerCount": 0},
            },
            "AutoChaptersEnabled": True,
            "MeetingAssistanceEnabled": True,
            "MeetingAssistance": {"Types": ["Actions", "KeyInformation"]},
            "SummarizationEnabled": True,
            "Summarization": {
                "Types": ["Paragraph", "Conversational", "QuestionsAnswering", "MindMap"],
            },
            "TextPolishEnabled": True,
            "LlmOutputLanguage": "cn",
        },
    }
    return acs3_request(config, "PUT", "/openapi/tingwu/v2/tasks", {"type": "offline"}, "CreateTask", body)


def tingwu_get_task_info(config, task_id):
    path = "/openapi/tingwu/v2/tasks/" + acs3_percent_encode(task_id)
    return acs3_request(config, "GET", path, {}, "GetTaskInfo")


def extract_tingwu_task_id(response):
    data = response.get("Data") if isinstance(response, dict) else {}
    if not isinstance(data, dict):
        data = response if isinstance(response, dict) else {}
    for key in ("TaskId", "TaskID", "TaskId".lower(), "task_id"):
        if data.get(key):
            return str(data[key])
    return ""


def tingwu_data(response):
    data = response.get("Data") if isinstance(response, dict) else {}
    return data if isinstance(data, dict) else {}


def result_url(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("Url", "URL", "url", "ResultUrl", "ResultURL"):
            if value.get(key):
                return str(value[key])
    return ""


def fetch_result_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "ai-platform/2.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"text": raw}


def collect_text_values(value, keys=("Text", "text", "Sentence", "sentence", "Content", "content", "Summary", "summary")):
    parts = []
    if isinstance(value, dict):
        for key in keys:
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
        for item in value.values():
            parts.extend(collect_text_values(item, keys))
    elif isinstance(value, list):
        for item in value:
            parts.extend(collect_text_values(item, keys))
    return parts


def join_transcription_words(words):
    text = "".join(
        str(item.get("Text") or item.get("text") or "")
        for item in words
        if isinstance(item, dict)
    ).strip()
    return re.sub(r"\s+", " ", text)


def parse_transcription_payload(payload):
    data = payload.get("Transcription") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    paragraphs = data.get("Paragraphs") or data.get("paragraphs") or []
    lines = []
    if isinstance(paragraphs, list):
        for item in paragraphs:
            if not isinstance(item, dict):
                continue
            text = str(item.get("Text") or item.get("text") or "").strip()
            if not text and isinstance(item.get("Words"), list):
                text = join_transcription_words(item.get("Words") or [])
            if text:
                speaker = str(item.get("SpeakerName") or item.get("SpeakerId") or "").strip()
                lines.append((f"发言人{speaker}：" if speaker and not speaker.startswith("发言") else (speaker + "：" if speaker else "")) + text)
    if lines:
        return "\n\n".join(lines)
    return "\n".join(dict.fromkeys(collect_text_values(payload))).strip()


def parse_auto_chapters_payload(payload):
    chapters = payload.get("AutoChapters") if isinstance(payload, dict) else []
    if isinstance(chapters, dict):
        chapters = chapters.get("Chapters") or chapters.get("chapters") or []
    lines = []
    if isinstance(chapters, list):
        for index, item in enumerate(chapters, 1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("Headline") or item.get("Title") or item.get("title") or f"章节 {index}").strip()
            summary = str(item.get("Summary") or item.get("summary") or "").strip()
            if title or summary:
                lines.append(f"{index}. {title}" + (f"\n   {summary}" if summary else ""))
    if lines:
        return "\n".join(lines)
    return "\n".join(dict.fromkeys(collect_text_values(payload))).strip()


def parse_meeting_assistance_payload(payload):
    data = payload.get("MeetingAssistance") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    lines = []
    keywords = data.get("Keywords") or data.get("keywords") or []
    if isinstance(keywords, list):
        words = [str(item).strip() for item in keywords if str(item).strip()]
        if words:
            lines.append("关键词：" + "、".join(words[:40]))
    key_sentences = data.get("KeySentences") or data.get("keySentences") or []
    if isinstance(key_sentences, list) and key_sentences:
        lines.append("关键句：")
        for item in key_sentences[:12]:
            if isinstance(item, dict):
                text = str(item.get("Text") or item.get("text") or "").strip()
            else:
                text = str(item).strip()
            if text:
                lines.append("- " + text)
    actions = data.get("Actions") or data.get("actions") or []
    if isinstance(actions, list) and actions:
        lines.append("待办/行动：")
        for item in actions[:12]:
            text = str(item.get("Text") if isinstance(item, dict) else item).strip()
            if text:
                lines.append("- " + text)
    return "\n".join(lines).strip()


def parse_summarization_payload(payload):
    data = payload.get("Summarization") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    lines = []
    title = str(data.get("ParagraphTitle") or data.get("Title") or "").strip()
    summary = str(data.get("ParagraphSummary") or data.get("Summary") or "").strip()
    if title:
        lines.append("## " + title)
    if summary:
        lines.append(summary)
    conversational = data.get("ConversationalSummary") or []
    if isinstance(conversational, list) and conversational:
        lines.append("## 发言总结")
        for item in conversational:
            if not isinstance(item, dict):
                continue
            speaker = str(item.get("SpeakerName") or item.get("SpeakerId") or "发言人").strip()
            text = str(item.get("Summary") or item.get("summary") or "").strip()
            if text:
                lines.append(f"- {speaker}：{text}")
    qa = data.get("QuestionsAnswering") or data.get("QuestionsAnsweringSummary") or []
    if isinstance(qa, list) and qa:
        lines.append("## 问答摘要")
        for item in qa[:12]:
            if isinstance(item, dict):
                question = str(item.get("Question") or item.get("question") or "").strip()
                answer = str(item.get("Answer") or item.get("answer") or item.get("Summary") or "").strip()
                if question or answer:
                    lines.append(f"- {question}" + (f"：{answer}" if answer else ""))
    if lines:
        return "\n\n".join(lines).strip()
    return "\n".join(dict.fromkeys(collect_text_values(payload))).strip()


def parse_tingwu_results(result_payloads):
    transcript_text = ""
    summary_parts = []
    outline_parts = []
    for name, payload in result_payloads.items():
        if name == "Transcription":
            transcript_text = parse_transcription_payload(payload)
        elif name == "AutoChapters":
            value = parse_auto_chapters_payload(payload)
            if value:
                outline_parts.append("## 章节速览\n" + value)
        elif name == "Summarization":
            value = parse_summarization_payload(payload)
            if value:
                summary_parts.append(value)
        elif name == "MeetingAssistance":
            value = parse_meeting_assistance_payload(payload)
            if value:
                outline_parts.append("## 关键词与关键句\n" + value)
        elif name == "TextPolish":
            values = collect_text_values(payload)
            if values:
                outline_parts.append("## 润色/整理\n" + "\n".join(dict.fromkeys(values[:20])))
    return {
        "transcript_text": transcript_text.strip(),
        "summary_text": "\n\n".join(part for part in summary_parts if part).strip(),
        "outline_text": "\n\n".join(part for part in outline_parts if part).strip(),
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
        if path in ("/xiaoji", "/xiaoji/"):
            return self.home_page()
        if path in ("/cat", "/cat/"):
            return self.cat_page()
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
        if path == "/api/changelog":
            return self.handle_changelog()
        if path == "/api/me":
            return self.handle_me()
        if path == "/api/models":
            return self.require_user(self.handle_models)
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
        if path == "/api/admin/search":
            return self.require_admin(self.handle_admin_search)
        if path == "/api/admin/token-stats":
            return self.require_admin(self.handle_admin_token_stats)
        if path == "/api/admin/users":
            return self.require_admin(self.handle_admin_users)
        if path == "/api/conversations":
            return self.require_user(self.handle_conversations)
        if path.startswith("/api/conversations/") and path.endswith("/messages"):
            return self.require_user(self.handle_messages)
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
        if path == "/api/admin/search":
            return self.require_admin(self.handle_admin_search)
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
        if path.startswith("/api/conversations/") and (path.endswith("/pin") or path.endswith("/unpin")):
            return self.require_user(self.handle_conversation_pin)
        if path.startswith("/api/sessions/") and (path.endswith("/pin") or path.endswith("/unpin")):
            return self.require_user(self.handle_conversation_pin)
        if path == "/api/conversations":
            return self.require_user(self.handle_conversations)
        if path.startswith("/api/conversations/") and path.endswith("/messages"):
            return self.require_user(self.handle_send_message)
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

    def cat_page(self):
        try:
            return self.html(CAT_PAGE_PATH.read_text())
        except FileNotFoundError:
            return self.error(HTTPStatus.NOT_FOUND, "cat page not found")

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

    def cat_session_token(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        if CAT_SESSION_COOKIE in cookie:
            return cookie[CAT_SESSION_COOKIE].value
        auth = self.headers.get("X-Cat-Token", "")
        if auth:
            return auth.strip()
        return ""

    def current_cat_user(self):
        token = self.cat_session_token()
        if not token:
            return None
        with db() as conn:
            row = conn.execute(
                """
                SELECT u.*
                FROM cat_sessions s
                JOIN cat_users u ON u.id = s.user_id
                WHERE s.token_hash=? AND s.expires_at>? AND u.status='active'
                """,
                (token_hash(token), now()),
            ).fetchone()
        return row

    def cat_guest_id(self):
        guest_id = self.headers.get("X-Cat-Guest-Id", "").strip()
        if guest_id and CAT_GUEST_ID_RE.match(guest_id):
            return guest_id
        return ""

    def cat_actor(self, require_guest=False):
        user = self.current_cat_user()
        if user:
            return {
                "key": f"user:{user['id']}",
                "type": "user",
                "name": user["nickname"],
                "user": user,
            }
        guest_id = self.cat_guest_id()
        if not guest_id:
            if require_guest:
                raise ValueError("请先以游客身份进入相册")
            return None
        suffix = re.sub(r"[^A-Za-z0-9]", "", guest_id)[-4:].upper() or "0000"
        guest_name = f"游客{suffix}"
        return {
            "key": f"guest:{guest_id}",
            "type": "guest",
            "name": guest_name,
            "user": None,
        }

    def require_cat_user(self, handler):
        if not self.current_cat_user():
            return self.error(HTTPStatus.UNAUTHORIZED, "请先登录小猫书")
        return handler()

    def require_cat_admin(self, handler):
        got = self.headers.get("X-Admin-Key", "").strip()
        expected = self.server.secrets["admin_key"]
        if got and hmac.compare_digest(got, expected):
            return handler()
        user = self.current_cat_user()
        if user and user["role"] == "admin":
            return handler()
        return self.error(HTTPStatus.UNAUTHORIZED, "需要管理员权限")

    def handle_login(self):
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        username = str(data.get("username") or "admin").strip().lower()
        password = str(data.get("password") or "")
        if not username or not password:
            return self.error(HTTPStatus.BAD_REQUEST, "username and password are required")
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        if (
            not user
            or not user["is_active"]
            or not verify_password(password, user["password_hash"])
        ):
            return self.error(HTTPStatus.UNAUTHORIZED, "password incorrect")

        token = b64_token(32)
        expires = now() + SESSION_TTL_SECONDS
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at<=?", (now(),))
            conn.execute(
                "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token_hash(token), user["id"], now(), expires),
            )

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_TTL_SECONDS}",
        )
        raw = json.dumps(
            {"ok": True, "expires_at": expires, "user": ai_user_public(user)},
            ensure_ascii=False,
        ).encode()
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
        user = self.current_user()
        return self.json(
            {"authenticated": bool(user), "user": ai_user_public(user) if user else None}
        )

    def handle_cat_me(self):
        user = self.current_cat_user()
        config = cat_oss_config(self.server.secrets)
        return self.json(
            {
                "authenticated": bool(user),
                "user": cat_user_public(user) if user else None,
                "oss_configured": config["configured"],
            }
        )

    def handle_cat_login(self):
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "请输入正确的登录信息")
        username = str(data.get("username") or "").strip().lower()
        password = str(data.get("password") or "")
        if not username or not password:
            return self.error(HTTPStatus.BAD_REQUEST, "请输入账号和密码")

        with db() as conn:
            row = conn.execute(
                "SELECT * FROM cat_users WHERE username=?", (username,)
            ).fetchone()
            if (
                not row
                or row["status"] != "active"
                or not verify_password(password, row["password_hash"])
            ):
                return self.error(HTTPStatus.UNAUTHORIZED, "账号或密码不正确")

            token = b64_token(32)
            expires = now() + CAT_SESSION_TTL_SECONDS
            conn.execute("DELETE FROM cat_sessions WHERE expires_at<=?", (now(),))
            conn.execute(
                """
                INSERT INTO cat_sessions(token_hash, user_id, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (token_hash(token), row["id"], now(), expires),
            )

        payload = json.dumps(
            {"ok": True, "user": cat_user_public(row), "expires_at": expires},
            ensure_ascii=False,
        ).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            f"{CAT_SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={CAT_SESSION_TTL_SECONDS}",
        )
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def handle_cat_logout(self):
        token = self.cat_session_token()
        if token:
            with db() as conn:
                conn.execute("DELETE FROM cat_sessions WHERE token_hash=?", (token_hash(token),))
        payload = b'{"ok":true}'
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header(
            "Set-Cookie",
            f"{CAT_SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
        )
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def handle_cat_admin_users(self):
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    "SELECT * FROM cat_users ORDER BY created_at DESC LIMIT 200"
                ).fetchall()
            return self.json({"users": [cat_user_public(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "请填写正确的账号信息")

        username = str(data.get("username") or "").strip().lower()
        nickname = str(data.get("nickname") or "").strip()[:40]
        password = str(data.get("password") or "")
        avatar_url = str(data.get("avatar_url") or "").strip()[:800]
        role = str(data.get("role") or "member").strip().lower()
        status = str(data.get("status") or "active").strip().lower()

        if not re.fullmatch(r"[a-z0-9_][a-z0-9_.-]{1,31}", username or ""):
            return self.error(HTTPStatus.BAD_REQUEST, "账号只能使用小写字母、数字、点、横线和下划线")
        if len(password) < 6:
            return self.error(HTTPStatus.BAD_REQUEST, "密码至少 6 位")
        if role not in ("member", "admin"):
            role = "member"
        if status not in ("active", "disabled"):
            status = "active"
        if not nickname:
            nickname = username

        user_id = b64_token(10)
        ts = now()
        try:
            with db() as conn:
                conn.execute(
                    """
                    INSERT INTO cat_users
                    (id, username, password_hash, nickname, avatar_url, role, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        username,
                        password_hash(password),
                        nickname,
                        avatar_url,
                        role,
                        status,
                        ts,
                        ts,
                    ),
                )
                row = conn.execute("SELECT * FROM cat_users WHERE id=?", (user_id,)).fetchone()
        except sqlite3.IntegrityError:
            return self.error(HTTPStatus.CONFLICT, "这个账号已经存在")
        return self.json({"user": cat_user_public(row)}, HTTPStatus.CREATED)

    def handle_cat_admin_user_item(self):
        user_id = urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "请填写正确的账号信息")
        with db() as conn:
            row = conn.execute("SELECT * FROM cat_users WHERE id=?", (user_id,)).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "账号不存在")
            nickname = str(data.get("nickname", row["nickname"]) or "").strip()[:40] or row["nickname"]
            avatar_url = str(data.get("avatar_url", row["avatar_url"]) or "").strip()[:800]
            role = str(data.get("role", row["role"]) or "member").strip().lower()
            status = str(data.get("status", row["status"]) or "active").strip().lower()
            password = str(data.get("password") or "")
            if role not in ("member", "admin"):
                role = row["role"]
            if status not in ("active", "disabled"):
                status = row["status"]
            if password:
                if len(password) < 6:
                    return self.error(HTTPStatus.BAD_REQUEST, "密码至少 6 位")
                conn.execute(
                    """
                    UPDATE cat_users
                    SET nickname=?, avatar_url=?, role=?, status=?, password_hash=?, updated_at=?
                    WHERE id=?
                    """,
                    (nickname, avatar_url, role, status, password_hash(password), now(), user_id),
                )
                conn.execute("DELETE FROM cat_sessions WHERE user_id=?", (user_id,))
            else:
                conn.execute(
                    """
                    UPDATE cat_users
                    SET nickname=?, avatar_url=?, role=?, status=?, updated_at=?
                    WHERE id=?
                    """,
                    (nickname, avatar_url, role, status, now(), user_id),
                )
            row = conn.execute("SELECT * FROM cat_users WHERE id=?", (user_id,)).fetchone()
        return self.json({"user": cat_user_public(row)})

    def clean_cat_payload(self, data):
        name = str(data.get("name") or "").strip()[:40]
        avatar_url = str(data.get("avatar_url") or "").strip()[:1000]
        breed = str(data.get("breed") or "").strip()[:40]
        gender = str(data.get("gender") or "").strip()[:12]
        birthday = str(data.get("birthday") or "").strip()[:10]
        description = str(data.get("description") or "").strip()[:500]
        if avatar_url and not re.match(r"^https?://", avatar_url):
            avatar_url = ""
        if birthday and not re.match(r"^\d{4}-\d{2}-\d{2}$", birthday):
            birthday = ""
        return {
            "name": name,
            "avatar_url": avatar_url,
            "breed": breed,
            "gender": gender,
            "birthday": birthday,
            "description": description,
        }

    def cat_owner_allowed(self, cat_row, user):
        return bool(cat_row and user and (cat_row["owner_user_id"] == user["id"] or user["role"] == "admin"))

    def handle_cat_cats(self):
        params = parse_qs(urlparse(self.path).query)
        scope = (params.get("scope") or ["public"])[0]
        if self.command == "GET":
            current = self.current_cat_user()
            values = []
            where = "EXISTS (SELECT 1 FROM cat_posts p WHERE p.cat_id=c.id AND p.status='published')"
            if scope == "mine":
                if not current:
                    return self.error(HTTPStatus.UNAUTHORIZED, "请先登录小猫书")
                where = "c.owner_user_id=?"
                values.append(current["id"])
            with db() as conn:
                rows = conn.execute(
                    f"""
                    SELECT c.*, u.username AS owner_username, u.nickname AS owner_nickname,
                           u.avatar_url AS owner_avatar_url,
                           (SELECT COUNT(*) FROM cat_posts p WHERE p.cat_id=c.id AND p.status='published') AS post_count
                    FROM cats c
                    JOIN cat_users u ON u.id = c.owner_user_id
                    WHERE {where}
                    ORDER BY post_count DESC, c.updated_at DESC
                    LIMIT 200
                    """,
                    tuple(values),
                ).fetchall()
            return self.json({"cats": [cat_public(row) for row in rows]})

        user = self.current_cat_user()
        try:
            data = self.read_body(limit=32 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "猫咪资料格式不正确")
        payload = self.clean_cat_payload(data)
        if not payload["name"]:
            return self.error(HTTPStatus.BAD_REQUEST, "请填写猫咪名字")
        cat_id = b64_token(12)
        ts = now()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO cats
                (id, owner_user_id, name, avatar_url, breed, gender, birthday, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cat_id,
                    user["id"],
                    payload["name"],
                    payload["avatar_url"],
                    payload["breed"],
                    payload["gender"],
                    payload["birthday"],
                    payload["description"],
                    ts,
                    ts,
                ),
            )
            row = conn.execute(
                """
                SELECT c.*, u.username AS owner_username, u.nickname AS owner_nickname,
                       u.avatar_url AS owner_avatar_url,
                       0 AS post_count
                FROM cats c
                JOIN cat_users u ON u.id = c.owner_user_id
                WHERE c.id=?
                """,
                (cat_id,),
            ).fetchone()
        return self.json({"cat": cat_public(row)}, HTTPStatus.CREATED)

    def handle_cat_item(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        cat_id = parts[3] if len(parts) >= 4 else ""
        if len(parts) != 4:
            return self.error(HTTPStatus.NOT_FOUND, "not found")
        if self.command == "GET":
            actor = self.cat_actor()
            actor_key = actor["key"] if actor else ""
            with db() as conn:
                cat = conn.execute(
                    """
                    SELECT c.*, u.username AS owner_username, u.nickname AS owner_nickname,
                           u.avatar_url AS owner_avatar_url,
                           (SELECT COUNT(*) FROM cat_posts p WHERE p.cat_id=c.id AND p.status='published') AS post_count
                    FROM cats c
                    JOIN cat_users u ON u.id = c.owner_user_id
                    WHERE c.id=?
                    """,
                    (cat_id,),
                ).fetchone()
                if not cat:
                    return self.error(HTTPStatus.NOT_FOUND, "这只猫咪不存在")
                rows = conn.execute(
                    """
                    SELECT p.*, u.username, u.nickname, u.avatar_url,
                           c.id AS cat_id, c.name AS cat_name, c.avatar_url AS cat_avatar_url,
                           c.breed AS cat_breed, c.gender AS cat_gender, c.birthday AS cat_birthday,
                           c.description AS cat_description,
                           (SELECT image_url FROM cat_post_images WHERE post_id=p.id ORDER BY sort_order ASC, id ASC LIMIT 1) AS cover_url,
                           (SELECT COUNT(*) FROM cat_post_images WHERE post_id=p.id) AS image_count,
                           (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id) AS like_count,
                           (SELECT COUNT(*) FROM cat_comments WHERE post_id=p.id) AS comment_count,
                           (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id AND actor_key=?) AS liked_by_me
                    FROM cat_posts p
                    JOIN cat_users u ON u.id = p.user_id
                    LEFT JOIN cats c ON c.id = p.cat_id
                    WHERE p.status='published' AND p.cat_id=?
                    ORDER BY p.created_at DESC, p.id DESC
                    LIMIT 120
                    """,
                    (actor_key, cat_id),
                ).fetchall()
            return self.json({"cat": cat_public(cat), "posts": [cat_post_card(row) for row in rows]})

        user = self.current_cat_user()
        with db() as conn:
            cat = conn.execute("SELECT * FROM cats WHERE id=?", (cat_id,)).fetchone()
            if not cat:
                return self.error(HTTPStatus.NOT_FOUND, "这只猫咪不存在")
            if not self.cat_owner_allowed(cat, user):
                return self.error(HTTPStatus.FORBIDDEN, "只能管理自己的猫咪")
            if self.command == "DELETE":
                conn.execute("UPDATE cat_posts SET cat_id='' WHERE cat_id=?", (cat_id,))
                conn.execute("DELETE FROM cats WHERE id=?", (cat_id,))
                return self.json({"ok": True})
            try:
                data = self.read_body(limit=32 * 1024)
            except Exception:
                return self.error(HTTPStatus.BAD_REQUEST, "猫咪资料格式不正确")
            payload = self.clean_cat_payload(data)
            if not payload["name"]:
                return self.error(HTTPStatus.BAD_REQUEST, "请填写猫咪名字")
            ts = now()
            conn.execute(
                """
                UPDATE cats
                SET name=?, avatar_url=?, breed=?, gender=?, birthday=?, description=?, updated_at=?
                WHERE id=?
                """,
                (
                    payload["name"],
                    payload["avatar_url"],
                    payload["breed"],
                    payload["gender"],
                    payload["birthday"],
                    payload["description"],
                    ts,
                    cat_id,
                ),
            )
            row = conn.execute(
                """
                SELECT c.*, u.username AS owner_username, u.nickname AS owner_nickname,
                       u.avatar_url AS owner_avatar_url,
                       (SELECT COUNT(*) FROM cat_posts p WHERE p.cat_id=c.id AND p.status='published') AS post_count
                FROM cats c
                JOIN cat_users u ON u.id = c.owner_user_id
                WHERE c.id=?
                """,
                (cat_id,),
            ).fetchone()
        return self.json({"cat": cat_public(row)})

    def handle_cat_daily_report(self):
        today_start = int(time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1)))
        tomorrow_start = today_start + 86400
        with db() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.title, p.content, p.created_at,
                       p.cat_id, c.name AS cat_name
                FROM cat_posts p
                LEFT JOIN cats c ON c.id = p.cat_id
                WHERE p.status='published' AND p.created_at>=? AND p.created_at<?
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT 200
                """,
                (today_start, tomorrow_start),
            ).fetchall()
        cat_ids = {row["cat_id"] for row in rows if row["cat_id"]}
        items = [
            {
                "id": row["id"],
                "title": row["title"],
                "content": row["content"],
                "created_at": row["created_at"],
                "cat_id": row["cat_id"],
                "cat_name": row["cat_name"] or "未关联猫咪",
            }
            for row in rows
        ]
        return self.json(
            {
                "date": today_text(),
                "cat_count": len(cat_ids),
                "post_count": len(rows),
                "items": items,
            }
        )

    def handle_cat_upload_policy(self):
        user = self.current_cat_user()
        config = cat_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "OSS 还没有配置好，暂时不能上传图片")
        return self.json({"policy": cat_upload_policy(config, user["id"])})

    def handle_cat_images(self):
        user = self.current_cat_user()
        config = cat_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "OSS 还没有配置好，暂时不能上传图片")
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "图片信息保存失败")
        oss_key = str(data.get("oss_key") or "").strip()
        expected_prefix = f"{config['directory'].strip('/')}/{user['id']}/"
        if (
            not oss_key
            or oss_key.startswith("/")
            or ".." in oss_key.split("/")
            or not oss_key.startswith(expected_prefix)
        ):
            return self.error(HTTPStatus.BAD_REQUEST, "图片路径不正确")
        image_url = cat_oss_url(config, oss_key)
        image_id = b64_token(10)
        ts = now()
        with db() as conn:
            existing = conn.execute(
                "SELECT * FROM cat_images WHERE oss_key=?", (oss_key,)
            ).fetchone()
            if existing:
                return self.json(
                    {
                        "image": {
                            "id": existing["id"],
                            "oss_key": existing["oss_key"],
                            "image_url": existing["image_url"],
                            "created_at": existing["created_at"],
                        }
                    }
                )
            conn.execute(
                """
                INSERT INTO cat_images(id, user_id, oss_key, image_url, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (image_id, user["id"], oss_key, image_url, ts),
            )
        return self.json(
            {
                "image": {
                    "id": image_id,
                    "oss_key": oss_key,
                    "image_url": image_url,
                    "created_at": ts,
                }
            },
            HTTPStatus.CREATED,
        )

    def load_cat_post(self, conn, post_id, actor_key=""):
        row = conn.execute(
            """
            SELECT p.*, u.username, u.nickname, u.avatar_url,
                   c.name AS cat_name, c.avatar_url AS cat_avatar_url,
                   c.breed AS cat_breed, c.gender AS cat_gender, c.birthday AS cat_birthday,
                   c.description AS cat_description,
                   (SELECT image_url FROM cat_post_images WHERE post_id=p.id ORDER BY sort_order ASC, id ASC LIMIT 1) AS cover_url,
                   (SELECT COUNT(*) FROM cat_post_images WHERE post_id=p.id) AS image_count,
                   (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id) AS like_count,
                   (SELECT COUNT(*) FROM cat_comments WHERE post_id=p.id) AS comment_count,
                   (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id AND actor_key=?) AS liked_by_me
            FROM cat_posts p
            JOIN cat_users u ON u.id = p.user_id
            LEFT JOIN cats c ON c.id = p.cat_id
            WHERE p.id=? AND p.status='published'
            """,
            (actor_key or "", post_id),
        ).fetchone()
        if not row:
            return None
        images = conn.execute(
            """
            SELECT image_url, sort_order
            FROM cat_post_images
            WHERE post_id=?
            ORDER BY sort_order ASC, id ASC
            """,
            (post_id,),
        ).fetchall()
        post = cat_post_card(row)
        post["content"] = row["content"]
        post["images"] = [
            {"image_url": image["image_url"], "sort_order": image["sort_order"]}
            for image in images
        ]
        comments = conn.execute(
            """
            SELECT id, post_id, actor_type, actor_name, content, created_at
            FROM cat_comments
            WHERE post_id=?
            ORDER BY created_at ASC, id ASC
            LIMIT 200
            """,
            (post_id,),
        ).fetchall()
        post["comments"] = [cat_comment_public(comment) for comment in comments]
        return post

    def handle_cat_posts(self):
        if self.command == "GET":
            actor = self.cat_actor()
            actor_key = actor["key"] if actor else ""
            params = parse_qs(urlparse(self.path).query)
            limit = clamp_int((params.get("limit") or ["20"])[0], 20, 1, 30)
            before = clamp_int((params.get("before") or ["0"])[0], 0, 0, 10**12)
            cat_id = str((params.get("cat_id") or [""])[0]).strip()
            where = "p.status='published'"
            values = []
            if cat_id:
                where += " AND p.cat_id=?"
                values.append(cat_id)
            if before:
                where += " AND p.created_at<?"
                values.append(before)
            with db() as conn:
                rows = conn.execute(
                    f"""
                    SELECT p.*, u.username, u.nickname, u.avatar_url,
                           c.name AS cat_name, c.avatar_url AS cat_avatar_url,
                           c.breed AS cat_breed, c.gender AS cat_gender, c.birthday AS cat_birthday,
                           c.description AS cat_description,
                           (SELECT image_url FROM cat_post_images WHERE post_id=p.id ORDER BY sort_order ASC, id ASC LIMIT 1) AS cover_url,
                           (SELECT COUNT(*) FROM cat_post_images WHERE post_id=p.id) AS image_count,
                           (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id) AS like_count,
                           (SELECT COUNT(*) FROM cat_comments WHERE post_id=p.id) AS comment_count,
                           (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id AND actor_key=?) AS liked_by_me
                    FROM cat_posts p
                    JOIN cat_users u ON u.id = p.user_id
                    LEFT JOIN cats c ON c.id = p.cat_id
                    WHERE {where}
                    ORDER BY p.created_at DESC, p.id DESC
                    LIMIT ?
                    """,
                    (actor_key, *values, limit + 1),
                ).fetchall()
            has_more = len(rows) > limit
            rows = rows[:limit]
            next_cursor = rows[-1]["created_at"] if has_more and rows else None
            return self.json(
                {
                    "posts": [cat_post_card(row) for row in rows],
                    "next_cursor": next_cursor,
                }
            )

        user = self.current_cat_user()
        try:
            data = self.read_body(limit=128 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "发布内容格式不正确")
        title = str(data.get("title") or "").strip()[:80]
        content = str(data.get("content") or "").strip()[:4000]
        cat_id = str(data.get("cat_id") or "").strip()
        image_ids = data.get("image_ids") or []
        if not isinstance(image_ids, list):
            image_ids = []
        image_ids = [str(item).strip() for item in image_ids if str(item).strip()][:9]
        if not cat_id:
            return self.error(HTTPStatus.BAD_REQUEST, "请选择这条动态属于哪只猫咪")
        if not title:
            return self.error(HTTPStatus.BAD_REQUEST, "请填写标题")
        if not image_ids:
            return self.error(HTTPStatus.BAD_REQUEST, "请至少上传一张猫咪照片")

        post_id = b64_token(12)
        ts = now()
        with db() as conn:
            cat = conn.execute(
                "SELECT * FROM cats WHERE id=? AND owner_user_id=?",
                (cat_id, user["id"]),
            ).fetchone()
            if not cat:
                return self.error(HTTPStatus.BAD_REQUEST, "请选择自己创建的猫咪")
            placeholders = ",".join("?" for _ in image_ids)
            image_rows = conn.execute(
                f"""
                SELECT *
                FROM cat_images
                WHERE id IN ({placeholders}) AND user_id=?
                """,
                (*image_ids, user["id"]),
            ).fetchall()
            image_by_id = {row["id"]: row for row in image_rows}
            ordered_images = [image_by_id.get(image_id) for image_id in image_ids]
            if any(row is None for row in ordered_images):
                return self.error(HTTPStatus.BAD_REQUEST, "有图片还没有上传完成")

            conn.execute(
                """
                INSERT INTO cat_posts(id, user_id, cat_id, title, content, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'published', ?, ?)
                """,
                (post_id, user["id"], cat_id, title, content, ts, ts),
            )
            for index, image in enumerate(ordered_images):
                conn.execute(
                    """
                    INSERT INTO cat_post_images(post_id, image_id, image_url, sort_order)
                    VALUES (?, ?, ?, ?)
                    """,
                    (post_id, image["id"], image["image_url"], index),
                )
            post = self.load_cat_post(conn, post_id, f"user:{user['id']}")
        return self.json({"post": post}, HTTPStatus.CREATED)

    def handle_cat_post_item(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        post_id = parts[3] if len(parts) >= 4 else ""
        if len(parts) != 4:
            return self.error(HTTPStatus.NOT_FOUND, "not found")
        actor = self.cat_actor()
        actor_key = actor["key"] if actor else ""
        with db() as conn:
            post = self.load_cat_post(conn, post_id, actor_key)
        if not post:
            return self.error(HTTPStatus.NOT_FOUND, "这条动态不存在")
        return self.json({"post": post})

    def handle_cat_post_action(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) != 5 or parts[:3] != ["cat", "api", "posts"]:
            return self.error(HTTPStatus.NOT_FOUND, "not found")
        post_id, action = parts[3], parts[4]
        if action == "like":
            return self.handle_cat_post_like(post_id)
        if action == "comments":
            return self.handle_cat_post_comment(post_id)
        return self.error(HTTPStatus.NOT_FOUND, "not found")

    def handle_cat_post_delete(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        post_id = parts[3] if len(parts) >= 4 else ""
        if len(parts) != 4:
            return self.error(HTTPStatus.NOT_FOUND, "not found")
        user = self.current_cat_user()
        with db() as conn:
            post = conn.execute(
                "SELECT id, user_id, title FROM cat_posts WHERE id=? AND status='published'",
                (post_id,),
            ).fetchone()
            if not post:
                return self.error(HTTPStatus.NOT_FOUND, "这条动态不存在")
            if user["role"] != "admin" and post["user_id"] != user["id"]:
                return self.error(HTTPStatus.FORBIDDEN, "只能删除自己发布的动态")
            conn.execute("DELETE FROM cat_posts WHERE id=?", (post_id,))
        return self.json({"ok": True, "id": post_id})

    def handle_cat_post_like(self, post_id):
        try:
            actor = self.cat_actor(require_guest=True)
        except ValueError as exc:
            return self.error(HTTPStatus.UNAUTHORIZED, str(exc))
        with db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM cat_posts WHERE id=? AND status='published'", (post_id,)
            ).fetchone()
            if not exists:
                return self.error(HTTPStatus.NOT_FOUND, "这条动态不存在")
            liked = conn.execute(
                "SELECT id FROM cat_post_likes WHERE post_id=? AND actor_key=?",
                (post_id, actor["key"]),
            ).fetchone()
            if liked:
                conn.execute("DELETE FROM cat_post_likes WHERE id=?", (liked["id"],))
                is_liked = False
            else:
                conn.execute(
                    """
                    INSERT INTO cat_post_likes(post_id, actor_key, actor_type, actor_name, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (post_id, actor["key"], actor["type"], actor["name"], now()),
                )
                is_liked = True
            like_count = conn.execute(
                "SELECT COUNT(*) AS n FROM cat_post_likes WHERE post_id=?", (post_id,)
            ).fetchone()["n"]
        return self.json({"liked": is_liked, "like_count": int(like_count)})

    def handle_cat_post_comment(self, post_id):
        try:
            actor = self.cat_actor(require_guest=True)
        except ValueError as exc:
            return self.error(HTTPStatus.UNAUTHORIZED, str(exc))
        try:
            data = self.read_body(limit=16 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "评论内容格式不正确")
        content = str(data.get("content") or "").strip()
        content = re.sub(r"\s+\n", "\n", content)
        if not content:
            return self.error(HTTPStatus.BAD_REQUEST, "写点评论再发送吧")
        if len(content) > 500:
            return self.error(HTTPStatus.BAD_REQUEST, "评论太长啦，控制在 500 字以内")
        ts = now()
        with db() as conn:
            exists = conn.execute(
                "SELECT 1 FROM cat_posts WHERE id=? AND status='published'", (post_id,)
            ).fetchone()
            if not exists:
                return self.error(HTTPStatus.NOT_FOUND, "这条动态不存在")
            cursor = conn.execute(
                """
                INSERT INTO cat_comments(post_id, actor_key, actor_type, actor_name, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (post_id, actor["key"], actor["type"], actor["name"], content, ts),
            )
            row = conn.execute(
                """
                SELECT id, post_id, actor_type, actor_name, content, created_at
                FROM cat_comments
                WHERE id=?
                """,
                (cursor.lastrowid,),
            ).fetchone()
            comment_count = conn.execute(
                "SELECT COUNT(*) AS n FROM cat_comments WHERE post_id=?", (post_id,)
            ).fetchone()["n"]
        return self.json(
            {"comment": cat_comment_public(row), "comment_count": int(comment_count)},
            HTTPStatus.CREATED,
        )

    def handle_cat_user_profile(self):
        actor = self.cat_actor()
        actor_key = actor["key"] if actor else ""
        user_id = urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]
        with db() as conn:
            user = conn.execute(
                "SELECT * FROM cat_users WHERE id=? AND status='active'", (user_id,)
            ).fetchone()
            if not user:
                return self.error(HTTPStatus.NOT_FOUND, "这个主页不存在")
            rows = conn.execute(
                """
                SELECT p.*, u.username, u.nickname, u.avatar_url,
                       c.name AS cat_name, c.avatar_url AS cat_avatar_url,
                       c.breed AS cat_breed, c.gender AS cat_gender, c.birthday AS cat_birthday,
                       c.description AS cat_description,
                       (SELECT image_url FROM cat_post_images WHERE post_id=p.id ORDER BY sort_order ASC, id ASC LIMIT 1) AS cover_url,
                       (SELECT COUNT(*) FROM cat_post_images WHERE post_id=p.id) AS image_count,
                       (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id) AS like_count,
                       (SELECT COUNT(*) FROM cat_comments WHERE post_id=p.id) AS comment_count,
                       (SELECT COUNT(*) FROM cat_post_likes WHERE post_id=p.id AND actor_key=?) AS liked_by_me
                FROM cat_posts p
                JOIN cat_users u ON u.id = p.user_id
                LEFT JOIN cats c ON c.id = p.cat_id
                WHERE p.status='published' AND p.user_id=?
                ORDER BY p.created_at DESC, p.id DESC
                LIMIT 120
                """,
                (actor_key, user_id),
            ).fetchall()
        return self.json({"user": cat_user_public(user), "posts": [cat_post_card(row) for row in rows]})

    def handle_models(self):
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM models WHERE enabled=1 ORDER BY updated_at DESC"
            ).fetchall()
        return self.json({"models": [public_model(row) for row in rows]})

    def handle_search_config(self):
        return self.json({"search": public_web_search_config(self.server.secrets)})

    def handle_global_search(self):
        user_id = self.current_user()["id"]
        params = parse_qs(urlparse(self.path).query)
        query = compact_search_text((params.get("q") or [""])[0])[:80]
        results = []
        with db() as conn:
            if not query:
                rows = conn.execute(
                    """
                    SELECT id, title, updated_at
                    FROM conversations
                    WHERE user_id=? AND archived=0
                    ORDER BY updated_at DESC
                    LIMIT 8
                    """,
                    (user_id,),
                ).fetchall()
                for row in rows:
                    results.append(
                        search_result_row(
                            row["id"],
                            "conversation",
                            row["id"],
                            0,
                            row["title"],
                            "最近对话",
                            "",
                            row["updated_at"],
                            20,
                        )
                    )
                return self.json({"query": query, "results": results})

            like = "%" + like_escape(query) + "%"
            conversation_rows = conn.execute(
                """
                SELECT id, title, updated_at
                FROM conversations
                WHERE user_id=? AND archived=0 AND title LIKE ? ESCAPE '\\'
                ORDER BY updated_at DESC
                LIMIT 20
                """,
                (user_id, like),
            ).fetchall()
            for row in conversation_rows:
                results.append(
                    search_result_row(
                        "conversation:" + row["id"],
                        "conversation",
                        row["id"],
                        0,
                        row["title"],
                        search_snippet(row["title"], query),
                        "",
                        row["updated_at"],
                        100,
                    )
                )

            message_rows = conn.execute(
                """
                SELECT m.id, m.conversation_id, m.role, m.content, m.created_at,
                       c.title AS conversation_title
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.user_id=? AND c.user_id=? AND c.archived=0
                  AND m.role!='system' AND m.content LIKE ? ESCAPE '\\'
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT 50
                """,
                (user_id, user_id, like),
            ).fetchall()
            for row in message_rows:
                score = 86 if row["role"] == "user" else 82
                results.append(
                    search_result_row(
                        "message:" + str(row["id"]),
                        "message",
                        row["conversation_id"],
                        row["id"],
                        row["conversation_title"],
                        search_snippet(row["content"], query),
                        row["role"],
                        row["created_at"],
                        score,
                    )
                )

            favorite_rows = conn.execute(
                """
                SELECT f.id, f.message_id, f.conversation_id, f.conversation_title,
                       f.role, f.content, f.created_at,
                       c.id AS live_conversation_id
                FROM favorite_messages f
                LEFT JOIN conversations c ON c.id = f.conversation_id AND c.user_id=f.user_id AND c.archived=0
                WHERE f.user_id=? AND f.content LIKE ? ESCAPE '\\'
                ORDER BY f.created_at DESC
                LIMIT 30
                """,
                (user_id, like),
            ).fetchall()
            for row in favorite_rows:
                results.append(
                    search_result_row(
                        "favorite:" + row["id"],
                        "favorite",
                        row["live_conversation_id"] or "",
                        row["message_id"] if row["live_conversation_id"] else 0,
                        row["conversation_title"] or "原会话已删除",
                        search_snippet(row["content"], query),
                        row["role"],
                        row["created_at"],
                        72,
                    )
                )

            media_rows = conn.execute(
                """
                SELECT id, filename, conversation_id, summary_text, enhanced_summary,
                       key_points, copywriting_text, updated_at, created_at
                FROM media_analysis_tasks
                WHERE user_id=? AND (
                  filename LIKE ? ESCAPE '\\'
                  OR summary_text LIKE ? ESCAPE '\\'
                  OR enhanced_summary LIKE ? ESCAPE '\\'
                  OR key_points LIKE ? ESCAPE '\\'
                  OR copywriting_text LIKE ? ESCAPE '\\'
                )
                ORDER BY updated_at DESC
                LIMIT 30
                """,
                (user_id, like, like, like, like, like),
            ).fetchall()
            for row in media_rows:
                source_text = "\n".join(
                    str(row[key] or "")
                    for key in ("filename", "enhanced_summary", "key_points", "summary_text", "copywriting_text")
                )
                results.append(
                    search_result_row(
                        "media:" + row["id"],
                        "media",
                        row["conversation_id"],
                        0,
                        row["filename"] or "音视频分析",
                        search_snippet(source_text, query),
                        "",
                        row["updated_at"] or row["created_at"],
                        68,
                    )
                )

        results.sort(key=lambda item: (item["score"], item["created_at"]), reverse=True)
        return self.json({"query": query, "results": results[:60]})

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

    def handle_admin_token_stats(self):
        params = parse_qs(urlparse(self.path).query)
        query = str((params.get("q") or [""])[0] or "").strip().lower()[:80]
        sort = str((params.get("sort") or ["tokens"])[0] or "tokens").strip().lower()
        if sort not in ("tokens", "recent", "created"):
            sort = "tokens"

        order_sql = {
            "tokens": "total_tokens DESC, request_count DESC, last_used_at DESC",
            "recent": "last_used_at DESC, total_tokens DESC, request_count DESC",
            "created": "u.created_at DESC",
        }[sort]
        where_sql = ""
        args = []
        if query:
            where_sql = "WHERE lower(u.username) LIKE ? ESCAPE '\\' OR lower(u.display_name) LIKE ? ESCAPE '\\'"
            like = "%" + like_escape(query) + "%"
            args.extend([like, like])

        with db() as conn:
            summary = conn.execute(
                """
                SELECT
                  COUNT(DISTINCT u.id) AS total_users,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN 1 ELSE 0 END), 0) AS total_requests,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN COALESCE(m.prompt_tokens, 0) ELSE 0 END), 0) AS prompt_tokens,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN COALESCE(m.completion_tokens, 0) ELSE 0 END), 0) AS completion_tokens,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN
                    CASE WHEN COALESCE(m.total_tokens, 0) > 0
                      THEN COALESCE(m.total_tokens, 0)
                      ELSE COALESCE(m.prompt_tokens, 0) + COALESCE(m.completion_tokens, 0)
                    END ELSE 0 END), 0) AS total_tokens
                FROM users u
                LEFT JOIN messages m ON m.user_id=u.id
                """
            ).fetchone()

            rows = conn.execute(
                f"""
                SELECT
                  u.id,
                  u.username,
                  u.display_name,
                  u.role,
                  u.is_active,
                  u.created_at,
                  COUNT(DISTINCT c.id) AS conversation_count,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN 1 ELSE 0 END), 0) AS request_count,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN COALESCE(m.prompt_tokens, 0) ELSE 0 END), 0) AS prompt_tokens,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN COALESCE(m.completion_tokens, 0) ELSE 0 END), 0) AS completion_tokens,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN
                    CASE WHEN COALESCE(m.total_tokens, 0) > 0
                      THEN COALESCE(m.total_tokens, 0)
                      ELSE COALESCE(m.prompt_tokens, 0) + COALESCE(m.completion_tokens, 0)
                    END ELSE 0 END), 0) AS total_tokens,
                  MAX(CASE WHEN m.role='assistant' THEN m.created_at ELSE NULL END) AS last_used_at
                FROM users u
                LEFT JOIN conversations c ON c.user_id=u.id
                LEFT JOIN messages m ON m.user_id=u.id AND m.conversation_id=c.id
                {where_sql}
                GROUP BY u.id
                ORDER BY {order_sql}
                LIMIT 200
                """,
                args,
            ).fetchall()

            details = {}
            user_ids = [row["id"] for row in rows]
            if user_ids:
                placeholders = ",".join(["?"] * len(user_ids))
                detail_rows = conn.execute(
                    f"""
                    SELECT
                      m.id,
                      m.user_id,
                      m.conversation_id,
                      m.created_at,
                      m.prompt_tokens,
                      m.completion_tokens,
                      CASE WHEN COALESCE(m.total_tokens, 0) > 0
                        THEN COALESCE(m.total_tokens, 0)
                        ELSE COALESCE(m.prompt_tokens, 0) + COALESCE(m.completion_tokens, 0)
                      END AS total_tokens,
                      c.title AS conversation_title,
                      mo.name AS model_name,
                      mo.model AS model_code,
                      EXISTS(SELECT 1 FROM message_sources s WHERE s.message_id=m.id) AS web_search
                    FROM messages m
                    LEFT JOIN conversations c ON c.id=m.conversation_id AND c.user_id=m.user_id
                    LEFT JOIN models mo ON mo.id=c.model_id
                    WHERE m.role='assistant' AND m.user_id IN ({placeholders})
                    ORDER BY m.user_id ASC, m.created_at DESC, m.id DESC
                    """,
                    user_ids,
                ).fetchall()
                for detail in detail_rows:
                    bucket = details.setdefault(detail["user_id"], [])
                    if len(bucket) >= 20:
                        continue
                    bucket.append(
                        {
                            "message_id": detail["id"],
                            "conversation_id": detail["conversation_id"],
                            "conversation_title": detail["conversation_title"] or "未命名对话",
                            "created_at": detail["created_at"],
                            "model_name": detail["model_name"] or "",
                            "model_code": detail["model_code"] or "",
                            "prompt_tokens": int(detail["prompt_tokens"] or 0),
                            "completion_tokens": int(detail["completion_tokens"] or 0),
                            "total_tokens": int(detail["total_tokens"] or 0),
                            "duration_ms": None,
                            "web_search": bool(detail["web_search"]),
                        }
                    )

        users = []
        for row in rows:
            users.append(
                {
                    "id": row["id"],
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "role": row["role"],
                    "is_active": bool(row["is_active"]),
                    "created_at": row["created_at"],
                    "conversation_count": int(row["conversation_count"] or 0),
                    "request_count": int(row["request_count"] or 0),
                    "prompt_tokens": int(row["prompt_tokens"] or 0),
                    "completion_tokens": int(row["completion_tokens"] or 0),
                    "total_tokens": int(row["total_tokens"] or 0),
                    "last_used_at": row["last_used_at"] or 0,
                    "recent_requests": details.get(row["id"], []),
                }
            )

        return self.json(
            {
                "summary": {
                    "total_users": int(summary["total_users"] or 0),
                    "total_requests": int(summary["total_requests"] or 0),
                    "prompt_tokens": int(summary["prompt_tokens"] or 0),
                    "completion_tokens": int(summary["completion_tokens"] or 0),
                    "total_tokens": int(summary["total_tokens"] or 0),
                },
                "users": users,
                "query": query,
                "sort": sort,
            }
        )

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
        supports_vision = 1 if data.get("supports_vision") else 0
        enabled = 1 if data.get("enabled", True) else 0

        if not name or not base_url or not model:
            return self.error(HTTPStatus.BAD_REQUEST, "name, base_url and model are required")

        model_id = b64_token(12)
        ts = now()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO models
                (id, name, provider, base_url, api_key, model, system_prompt, supports_vision, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (model_id, name, provider, base_url, api_key, model, system_prompt, supports_vision, enabled, ts, ts),
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
            supports_vision = 1 if data.get("supports_vision", bool(row["supports_vision"])) else 0
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
                SET name=?, provider=?, base_url=?, api_key=?, model=?, system_prompt=?, supports_vision=?, enabled=?, updated_at=?
                WHERE id=?
                """,
                (name, provider, base_url, api_key, model, system_prompt, supports_vision, enabled, now(), model_id),
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
            conn.execute(
                "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
                (self.server.secrets["family_password_hash"], now(), DEFAULT_AI_USER_ID),
            )
            conn.execute("DELETE FROM sessions")
        return self.json({"ok": True})

    def handle_admin_users(self):
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    "SELECT * FROM users ORDER BY created_at ASC"
                ).fetchall()
            return self.json({"users": [ai_user_public(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        username = str(data.get("username") or "").strip().lower()
        display_name = str(data.get("display_name") or username).strip()[:40]
        password = str(data.get("password") or "")
        role = str(data.get("role") or "family").strip().lower()
        is_active = 1 if data.get("is_active", True) else 0

        if not USERNAME_RE.match(username):
            return self.error(HTTPStatus.BAD_REQUEST, "username invalid")
        if role not in ("admin", "family"):
            return self.error(HTTPStatus.BAD_REQUEST, "role invalid")
        if len(password) < 6:
            return self.error(HTTPStatus.BAD_REQUEST, "password must be at least 6 characters")
        if not display_name:
            display_name = username

        user_id = b64_token(10)
        ts = now()
        try:
            with db() as conn:
                conn.execute(
                    """
                    INSERT INTO users
                    (id, username, display_name, password_hash, role, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        username,
                        display_name,
                        password_hash(password),
                        role,
                        is_active,
                        ts,
                        ts,
                    ),
                )
                row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        except sqlite3.IntegrityError:
            return self.error(HTTPStatus.CONFLICT, "username already exists")
        return self.json({"user": ai_user_public(row)}, HTTPStatus.CREATED)

    def admin_user_id_from_path(self):
        return urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]

    def handle_admin_user_item(self):
        user_id = self.admin_user_id_from_path()
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        with db() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "user not found")

            display_name = str(data.get("display_name", row["display_name"]) or "").strip()[:40] or row["display_name"]
            role = str(data.get("role", row["role"]) or row["role"]).strip().lower()
            if role not in ("admin", "family"):
                return self.error(HTTPStatus.BAD_REQUEST, "role invalid")
            is_active = 1 if data.get("is_active", bool(row["is_active"])) else 0
            password = str(data.get("password") or "")

            if (row["role"] == "admin" and (role != "admin" or not is_active)):
                active_admins = conn.execute(
                    "SELECT COUNT(*) AS n FROM users WHERE role='admin' AND is_active=1 AND id<>?",
                    (user_id,),
                ).fetchone()["n"]
                if active_admins <= 0:
                    return self.error(HTTPStatus.BAD_REQUEST, "at least one active admin is required")

            password_clause = ""
            params = [display_name, role, is_active, now()]
            if password:
                if len(password) < 6:
                    return self.error(HTTPStatus.BAD_REQUEST, "password must be at least 6 characters")
                password_clause = ", password_hash=?"
                params.append(password_hash(password))
            params.append(user_id)
            conn.execute(
                f"""
                UPDATE users
                SET display_name=?, role=?, is_active=?, updated_at=?{password_clause}
                WHERE id=?
                """,
                tuple(params),
            )
            if not is_active:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self.json({"user": ai_user_public(row)})

    def handle_profiles(self):
        user_id = self.current_user()["id"]
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM user_profiles
                    WHERE user_id=?
                    ORDER BY sort_order ASC, updated_at DESC
                    LIMIT 300
                    """,
                    (user_id,),
                ).fetchall()
            return self.json(
                {
                    "profiles": [user_profile_row(row) for row in rows],
                    "totals": profile_totals(rows),
                }
            )

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        title = str(data.get("title") or "").strip()[:80]
        content = str(data.get("content") or "").strip()
        profile_type = str(data.get("type") or "profile").strip().lower()[:32] or "profile"
        if profile_type not in ("profile", "project", "style", "memory"):
            profile_type = "profile"
        enabled = 1 if data.get("enabled", True) else 0
        sort_order = clamp_int(data.get("sort_order"), 100, -100000, 100000)
        if not title or not content:
            return self.error(HTTPStatus.BAD_REQUEST, "title and content are required")
        if len(content) > 12000:
            return self.error(HTTPStatus.BAD_REQUEST, "content too long")

        profile_id = b64_token(10)
        ts = now()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO user_profiles
                (id, user_id, title, content, type, sort_order, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (profile_id, user_id, title, content, profile_type, sort_order, enabled, ts, ts),
            )
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE id=? AND user_id=?",
                (profile_id, user_id),
            ).fetchone()
        return self.json({"profile": user_profile_row(row)}, HTTPStatus.CREATED)

    def profile_id_from_path(self):
        return urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]

    def handle_profile_item(self):
        profile_id = self.profile_id_from_path()
        user_id = self.current_user()["id"]
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE id=? AND user_id=?",
                (profile_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "profile not found")

            if self.command == "DELETE":
                conn.execute("DELETE FROM user_profiles WHERE id=? AND user_id=?", (profile_id, user_id))
                return self.json({"ok": True})

            try:
                data = self.read_body()
            except Exception:
                return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
            title = str(data.get("title", row["title"]) or "").strip()[:80]
            content = str(data.get("content", row["content"]) or "").strip()
            profile_type = str(data.get("type", row["type"]) or "profile").strip().lower()[:32] or "profile"
            if profile_type not in ("profile", "project", "style", "memory"):
                profile_type = "profile"
            enabled = 1 if data.get("enabled", bool(row["enabled"])) else 0
            sort_order = clamp_int(data.get("sort_order", row["sort_order"]), row["sort_order"], -100000, 100000)
            if not title or not content:
                return self.error(HTTPStatus.BAD_REQUEST, "title and content are required")
            if len(content) > 12000:
                return self.error(HTTPStatus.BAD_REQUEST, "content too long")
            conn.execute(
                """
                UPDATE user_profiles
                SET title=?, content=?, type=?, sort_order=?, enabled=?, updated_at=?
                WHERE id=? AND user_id=?
                """,
                (title, content, profile_type, sort_order, enabled, now(), profile_id, user_id),
            )
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE id=? AND user_id=?",
                (profile_id, user_id),
            ).fetchone()
        return self.json({"profile": user_profile_row(row)})

    def handle_profile_reorder(self):
        user_id = self.current_user()["id"]
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        ids = data.get("ids") or []
        if not isinstance(ids, list):
            return self.error(HTTPStatus.BAD_REQUEST, "ids required")
        clean_ids = []
        for item in ids:
            value = str(item or "").strip()
            if value and value not in clean_ids:
                clean_ids.append(value)
        with db() as conn:
            existing = {
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM user_profiles WHERE user_id=?",
                    (user_id,),
                ).fetchall()
            }
            ts = now()
            for index, profile_id in enumerate(clean_ids):
                if profile_id in existing:
                    conn.execute(
                        "UPDATE user_profiles SET sort_order=?, updated_at=? WHERE id=? AND user_id=?",
                        ((index + 1) * 10, ts, profile_id, user_id),
                    )
            rows = conn.execute(
                """
                SELECT *
                FROM user_profiles
                WHERE user_id=?
                ORDER BY sort_order ASC, updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return self.json({"profiles": [user_profile_row(row) for row in rows], "totals": profile_totals(rows)})

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
        user = self.current_user()
        user_id = user["id"]
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT f.*,
                           c.title AS live_conversation_title,
                           COALESCE(c.archived, 1) AS conversation_archived
                    FROM favorite_messages f
                    LEFT JOIN conversations c ON c.id = f.conversation_id
                    WHERE f.user_id=?
                    ORDER BY f.created_at DESC
                    LIMIT 300
                    """,
                    (user_id,),
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
                WHERE f.message_id=? AND f.user_id=?
                """,
                (message_id, user_id),
            ).fetchone()
            if existing:
                return self.json({"favorite": favorite_row(existing)})

            message = conn.execute(
                """
                SELECT m.id, m.conversation_id, m.role, m.content, m.created_at,
                       c.title AS conversation_title
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.id=? AND c.user_id=?
                """,
                (message_id, user_id),
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
                (id, user_id, message_id, conversation_id, conversation_title, role, content, message_created_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    favorite_id,
                    user_id,
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
                WHERE f.id=? AND f.user_id=?
                """,
                (favorite_id, user_id),
            ).fetchone()
        return self.json({"favorite": favorite_row(row)}, HTTPStatus.CREATED)

    def favorite_id_from_path(self):
        return urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]

    def handle_favorite_item(self):
        favorite_id = self.favorite_id_from_path()
        user_id = self.current_user()["id"]
        with db() as conn:
            row = conn.execute(
                "SELECT id FROM favorite_messages WHERE id=? AND user_id=?",
                (favorite_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "favorite not found")
            conn.execute("DELETE FROM favorite_messages WHERE id=? AND user_id=?", (favorite_id, user_id))
        return self.json({"ok": True})

    def handle_favorite_by_message(self):
        try:
            message_id = int(self.favorite_id_from_path())
        except (TypeError, ValueError):
            message_id = 0
        if message_id <= 0:
            return self.error(HTTPStatus.BAD_REQUEST, "message_id required")
        user_id = self.current_user()["id"]
        with db() as conn:
            conn.execute(
                "DELETE FROM favorite_messages WHERE message_id=? AND user_id=?",
                (message_id, user_id),
            )
        return self.json({"ok": True})

    def chat_image_id_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) >= 3:
            return parts[2]
        return ""

    def handle_chat_image_upload_policy(self):
        user = self.current_user()
        config = chat_image_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "图片 OSS 还没有配置好")
        return self.json({"policy": chat_image_upload_policy(config, user["id"])})

    def handle_chat_images(self):
        user = self.current_user()
        user_id = user["id"]
        config = chat_image_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "图片 OSS 还没有配置好")
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        filename = str(data.get("filename") or "").strip()[:180]
        mime_type = str(data.get("mime_type") or "").strip().lower()[:120]
        oss_key = str(data.get("oss_key") or "").strip()
        try:
            file_size = max(0, int(data.get("file_size") or 0))
        except (TypeError, ValueError):
            file_size = 0

        expected_prefix = chat_image_prefix(config, user_id)
        suffix = Path(filename or oss_key).suffix.lower()
        if not filename or not oss_key:
            return self.error(HTTPStatus.BAD_REQUEST, "请先上传图片")
        if suffix not in CHAT_IMAGE_ALLOWED_EXTENSIONS:
            return self.error(HTTPStatus.BAD_REQUEST, "暂不支持这个图片格式")
        if mime_type and mime_type not in CHAT_IMAGE_ALLOWED_MIME_TYPES:
            return self.error(HTTPStatus.BAD_REQUEST, "暂不支持这个图片格式")
        if file_size <= 0 or file_size > config["max_size"]:
            return self.error(HTTPStatus.BAD_REQUEST, "图片大小超出限制")
        if oss_key.startswith("/") or ".." in oss_key.split("/") or not oss_key.startswith(expected_prefix):
            return self.error(HTTPStatus.BAD_REQUEST, "图片路径不合法")

        ts = now()
        oss_url = cat_oss_url(config, oss_key)
        image_id = b64_token(12)
        with db() as conn:
            existing = conn.execute(
                "SELECT * FROM chat_message_images WHERE oss_key=? AND user_id=?",
                (oss_key, user_id),
            ).fetchone()
            if existing:
                return self.json({"image": chat_image_public(existing)})
            conn.execute(
                """
                INSERT INTO chat_message_images
                (id, user_id, session_id, message_id, filename, mime_type, file_size, oss_key, oss_url, created_at)
                VALUES (?, ?, '', 0, ?, ?, ?, ?, ?, ?)
                """,
                (image_id, user_id, filename, mime_type, file_size, oss_key, oss_url, ts),
            )
            row = conn.execute(
                "SELECT * FROM chat_message_images WHERE id=? AND user_id=?",
                (image_id, user_id),
            ).fetchone()
        return self.json({"image": chat_image_public(row)}, HTTPStatus.CREATED)

    def handle_chat_image_view(self):
        user_id = self.current_user()["id"]
        image_id = self.chat_image_id_from_path()
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM chat_message_images WHERE id=? AND user_id=?",
                (image_id, user_id),
            ).fetchone()
        if not row:
            return self.error(HTTPStatus.NOT_FOUND, "image not found")
        config = chat_image_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "图片 OSS 还没有配置好")
        signed_url, _ = oss_signed_get_url(config, row["oss_key"], 900)
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", signed_url)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def media_task_id_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) >= 4:
            return parts[3]
        return ""

    def handle_media_upload_policy(self):
        user = self.current_user()
        config = media_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "音视频 OSS 还没有配置好")
        return self.json({"policy": media_upload_policy(config, user["id"])})

    def handle_media_tasks(self):
        user = self.current_user()
        user_id = user["id"]
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM media_analysis_tasks
                    WHERE user_id=?
                    ORDER BY updated_at DESC
                    LIMIT 100
                    """,
                    (user_id,),
                ).fetchall()
            return self.json({"tasks": [media_task_public(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        filename = str(data.get("filename") or "").strip()[:180]
        mime_type = str(data.get("mime_type") or "").strip()[:120]
        oss_key = str(data.get("oss_key") or "").strip()
        source_language = str(data.get("source_language") or "cn").strip()[:20] or "cn"
        try:
            file_size = max(0, int(data.get("file_size") or 0))
        except (TypeError, ValueError):
            file_size = 0

        config = media_oss_config(self.server.secrets)
        tingwu = tingwu_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "音视频 OSS 还没有配置好")
        if not tingwu_configured(tingwu):
            return self.error(HTTPStatus.BAD_REQUEST, "通义听悟还没有配置好")
        expected_prefix = f"{config['directory'].strip('/')}/{user_id}/"
        suffix = Path(filename or oss_key).suffix.lower()
        if not filename or not oss_key:
            return self.error(HTTPStatus.BAD_REQUEST, "请先上传音视频文件")
        if suffix not in MEDIA_ALLOWED_EXTENSIONS:
            return self.error(HTTPStatus.BAD_REQUEST, "暂不支持这个文件格式")
        if file_size <= 0 or file_size > config["max_size"]:
            return self.error(HTTPStatus.BAD_REQUEST, "文件大小超出限制")
        if oss_key.startswith("/") or ".." in oss_key.split("/") or not oss_key.startswith(expected_prefix):
            return self.error(HTTPStatus.BAD_REQUEST, "文件路径不合法")

        task_row_id = b64_token(12)
        task_key = "aimeimei-" + task_row_id
        signed_url, expires_at = oss_signed_get_url(config, oss_key, 6 * 60 * 60)
        ts = now()
        status = "submitted"
        task_id = ""
        error_message = ""
        raw_result = ""
        try:
            response = tingwu_create_task(tingwu, signed_url, task_key, source_language)
            raw_result = json.dumps(response, ensure_ascii=False)
            task_id = extract_tingwu_task_id(response)
            if not task_id:
                status = "failed"
                error_message = "听悟没有返回任务 ID"
        except urllib.error.HTTPError as exc:
            status = "failed"
            detail = exc.read(4096).decode(errors="replace")
            error_message = f"听悟创建任务失败：HTTP {exc.code}"
            raw_result = json.dumps({"error": error_message, "detail": detail[:1200]}, ensure_ascii=False)
        except Exception as exc:
            status = "failed"
            error_message = "听悟创建任务失败"
            raw_result = json.dumps({"error": error_message, "detail": str(exc)[:1200]}, ensure_ascii=False)

        with db() as conn:
            conn.execute(
                """
                INSERT INTO media_analysis_tasks
                (id, user_id, filename, mime_type, file_size, oss_key, file_url, file_url_expires_at,
                 task_id, task_key, source_language, status, raw_result_json, error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_row_id,
                    user_id,
                    filename,
                    mime_type,
                    file_size,
                    oss_key,
                    signed_url,
                    expires_at,
                    task_id,
                    task_key,
                    source_language,
                    status,
                    raw_result,
                    error_message,
                    ts,
                    ts,
                ),
            )
            row = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_row_id, user_id),
            ).fetchone()
        return self.json({"task": media_task_public(row)}, HTTPStatus.CREATED)

    def refresh_media_task(self, conn, row):
        if not row or not row["task_id"]:
            return row
        if row["status"] in ("completed", "failed"):
            return row
        config = tingwu_config(self.server.secrets)
        if not tingwu_configured(config):
            conn.execute(
                "UPDATE media_analysis_tasks SET status='failed', error_message=?, updated_at=? WHERE id=?",
                ("通义听悟还没有配置好", now(), row["id"]),
            )
            return conn.execute("SELECT * FROM media_analysis_tasks WHERE id=?", (row["id"],)).fetchone()

        try:
            response = tingwu_get_task_info(config, row["task_id"])
            data = tingwu_data(response)
            task_status = str(data.get("TaskStatus") or data.get("Status") or "").upper()
            result = data.get("Result") or {}
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    result = {}
            status = "processing"
            error_message = ""
            result_payloads = {}
            parsed = {}
            if task_status == "COMPLETED":
                status = "completed"
                if isinstance(result, dict):
                    for name in ("Transcription", "AutoChapters", "MeetingAssistance", "Summarization", "TextPolish"):
                        url = result_url(result.get(name))
                        if not url:
                            continue
                        try:
                            result_payloads[name] = fetch_result_json(url)
                        except Exception as exc:
                            result_payloads[name] = {"error": "结果文件读取失败", "detail": str(exc)[:500]}
                parsed = parse_tingwu_results(result_payloads)
            elif task_status in ("FAILED", "INVALID"):
                status = "failed"
                error_message = str(data.get("ErrorMessage") or data.get("Message") or "听悟任务失败")[:1000]
            elif task_status:
                status = "processing"

            raw = {
                "task_info": response,
                "result_payloads": result_payloads,
            }
            conn.execute(
                """
                UPDATE media_analysis_tasks
                SET status=?, raw_result_json=?, transcript_text=?, summary_text=?,
                    outline_text=?, mindmap_text=?, error_message=?, updated_at=?
                WHERE id=?
                """,
                (
                    status,
                    json.dumps(raw, ensure_ascii=False),
                    parsed.get("transcript_text", row["transcript_text"]),
                    parsed.get("summary_text", row["summary_text"]),
                    parsed.get("outline_text", row["outline_text"]),
                    parsed.get("mindmap_text", row["mindmap_text"]),
                    error_message,
                    now(),
                    row["id"],
                ),
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode(errors="replace")
            conn.execute(
                "UPDATE media_analysis_tasks SET error_message=?, updated_at=? WHERE id=?",
                (f"听悟查询失败：HTTP {exc.code} {detail[:600]}", now(), row["id"]),
            )
        except Exception as exc:
            conn.execute(
                "UPDATE media_analysis_tasks SET error_message=?, updated_at=? WHERE id=?",
                ("听悟查询失败：" + str(exc)[:600], now(), row["id"]),
            )
        return conn.execute("SELECT * FROM media_analysis_tasks WHERE id=?", (row["id"],)).fetchone()

    def handle_media_task_item(self):
        user_id = self.current_user()["id"]
        task_id = self.media_task_id_from_path()
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "media task not found")
            if self.command == "DELETE":
                conn.execute(
                    "DELETE FROM media_analysis_tasks WHERE id=? AND user_id=?",
                    (task_id, user_id),
                )
                return self.json({"ok": True})
            row = self.refresh_media_task(conn, row)
        return self.json({"task": media_task_public(row)})

    def handle_media_task_refresh(self):
        user_id = self.current_user()["id"]
        task_id = self.media_task_id_from_path()
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "media task not found")
            if row["status"] in ("completed", "failed") and row["task_id"]:
                conn.execute(
                    "UPDATE media_analysis_tasks SET status='processing', error_message='', updated_at=? WHERE id=?",
                    (now(), task_id),
                )
                row = conn.execute("SELECT * FROM media_analysis_tasks WHERE id=?", (task_id,)).fetchone()
            row = self.refresh_media_task(conn, row)
        return self.json({"task": media_task_public(row)})

    def media_task_conversation_row(self, conn, conversation_id, user_id):
        if not conversation_id:
            return None
        return conn.execute(
            """
            SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision
            FROM conversations c
            JOIN models m ON m.id = c.model_id
            WHERE c.id=? AND c.user_id=? AND c.archived=0
            """,
            (conversation_id, user_id),
        ).fetchone()

    def upsert_media_context_message(self, conn, row, conversation_id, user_id):
        marker = media_context_marker(row["id"])
        content = marker + "\n" + media_analysis_context(row)
        ts = now()
        existing = conn.execute(
            """
            SELECT id FROM messages
            WHERE conversation_id=? AND user_id=? AND role='system' AND content LIKE ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (conversation_id, user_id, marker + "%"),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE messages SET content=?, created_at=? WHERE id=? AND user_id=?",
                (content, ts, existing["id"], user_id),
            )
        else:
            conn.execute(
                "INSERT INTO messages(user_id, conversation_id, role, content, created_at) VALUES (?, ?, 'system', ?, ?)",
                (user_id, conversation_id, content, ts),
            )

    def create_media_conversation(self, conn, row, user_id, model_id):
        if row["status"] != "completed" or not media_analysis_has_context(row):
            return None, "分析完成后才能发送到 AI 对话"

        conversation = self.media_task_conversation_row(conn, row["conversation_id"], user_id)
        if conversation:
            self.upsert_media_context_message(conn, row, conversation["id"], user_id)
            return conversation, ""

        model = None
        if model_id:
            model = conn.execute(
                "SELECT * FROM models WHERE id=? AND enabled=1",
                (model_id,),
            ).fetchone()
        if not model:
            model = conn.execute(
                "SELECT * FROM models WHERE enabled=1 ORDER BY updated_at DESC, created_at DESC LIMIT 1"
            ).fetchone()
        if not model:
            return None, "还没有可用模型，请先配置模型"

        conversation_id = b64_token(12)
        stem = Path(str(row["filename"] or "音视频分析")).stem or "音视频分析"
        title = ("音视频分析：" + stem)[:80]
        ts = now()
        conn.execute(
            """
            INSERT INTO conversations(id, user_id, title, model_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, user_id, title, model["id"], ts, ts),
        )
        self.upsert_media_context_message(conn, row, conversation_id, user_id)
        intro = (
            f"我已经把《{row['filename'] or '这段音视频'}》的转写、摘要和章节要点放进这个分析会话了。\n\n"
            "你可以直接让我生成短视频文案、口播稿、公众号文章、小红书笔记、朋友圈文案或思维导图，也可以继续追问细节。"
        )
        conn.execute(
            "INSERT INTO messages(user_id, conversation_id, role, content, created_at) VALUES (?, ?, 'assistant', ?, ?)",
            (user_id, conversation_id, intro, ts),
        )
        conn.execute(
            "UPDATE media_analysis_tasks SET conversation_id=?, updated_at=? WHERE id=? AND user_id=?",
            (conversation_id, ts, row["id"], user_id),
        )
        conversation = self.media_task_conversation_row(conn, conversation_id, user_id)
        return conversation, ""

    def handle_media_task_conversation(self):
        user_id = self.current_user()["id"]
        task_id = self.media_task_id_from_path()
        try:
            data = self.read_body()
        except Exception:
            data = {}
        model_id = str(data.get("model_id") or "").strip()
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "media task not found")
            row = self.refresh_media_task(conn, row)
            conversation, error_message = self.create_media_conversation(conn, row, user_id, model_id)
            if not conversation:
                return self.error(HTTPStatus.BAD_REQUEST, error_message or "创建分析会话失败")
            updated = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
        return self.json({
            "conversation": conversation_row(conversation),
            "task": media_task_public(updated),
        })

    def pick_media_ai_model(self, conn, model_id):
        model = None
        if model_id:
            model = conn.execute(
                "SELECT * FROM models WHERE id=? AND enabled=1",
                (model_id,),
            ).fetchone()
        if not model:
            model = conn.execute(
                "SELECT * FROM models WHERE enabled=1 ORDER BY updated_at DESC, created_at DESC LIMIT 1"
            ).fetchone()
        return model

    def call_media_ai_model(self, model, row):
        if not model:
            raise ValueError("还没有可用模型，请先配置模型")
        if not str(model["api_key"] or "").strip():
            raise ValueError("模型 API Key 还没有配置")
        context = media_ai_source_context(row)
        if not context:
            raise ValueError("听悟结果还不完整，暂时无法生成 AI 增强分析")
        system_prompt = (
            "你是 AI槑槑 的音视频内容分析助手。"
            "你会基于通义听悟返回的转写、摘要和章节，生成适合家庭用户直接复制使用的二次加工结果。"
            "必须输出严格 JSON，不要使用 Markdown 代码围栏，不要输出解释文字。"
        )
        user_prompt = f"""
请基于下面音视频分析材料，生成 AI 增强分析。

输出严格 JSON 对象，字段必须包含：
- enhanced_summary：深度总结，分层次说明内容价值
- key_points：核心观点，用 Markdown 列表
- copywriting_text：适合复制的综合文案
- short_video：短视频文案，包含标题、开头钩子、正文、结尾引导
- speech_script：口播稿
- wechat_article：公众号文章
- xiaohongshu_note：小红书笔记
- moments_copy：朋友圈文案，给 3 个版本
- selling_points：提取卖点/爆点
- titles：生成 8 个标题
- mindmap_text：Mermaid mindmap 代码

mindmap_text 要求：
- 只放 Mermaid mindmap 内容
- 使用 mindmap 语法
- 中文节点
- 层级不超过 4 层
- 节点不要太长
- 不要解释

音视频分析材料：
{context}
""".strip()
        payload = {
            "model": model["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "temperature": 0.4,
        }
        request = urllib.request.Request(
            model["base_url"].rstrip("/") + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={
                "Authorization": "Bearer " + str(model["api_key"]).strip(),
                "Content-Type": "application/json",
                "User-Agent": "ai-platform/2.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode()
        data = json.loads(raw or "{}")
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or choice.get("text") or ""
        parsed = extract_json_object(content)
        if not parsed:
            raise ValueError("AI 增强分析没有返回可解析结果")
        return parsed

    def save_media_ai_outputs(self, conn, row, outputs):
        normalized = {}
        for key in (
            "enhanced_summary", "key_points", "copywriting_text", "short_video",
            "speech_script", "wechat_article", "xiaohongshu_note", "moments_copy",
            "selling_points", "titles",
        ):
            normalized[key] = str(outputs.get(key) or "").strip()
        normalized["mindmap_text"] = normalize_mermaid_mindmap(outputs.get("mindmap_text") or outputs.get("mindmap") or "")
        conn.execute(
            """
            UPDATE media_analysis_tasks
            SET enhanced_summary=?, key_points=?, mindmap_text=?, copywriting_text=?,
                ai_outputs_json=?, updated_at=?
            WHERE id=? AND user_id=?
            """,
            (
                normalized["enhanced_summary"],
                normalized["key_points"],
                normalized["mindmap_text"],
                normalized["copywriting_text"],
                json.dumps(normalized, ensure_ascii=False),
                now(),
                row["id"],
                row["user_id"],
            ),
        )

    def handle_media_task_enhance(self):
        user_id = self.current_user()["id"]
        task_id = self.media_task_id_from_path()
        try:
            data = self.read_body()
        except Exception:
            data = {}
        model_id = str(data.get("model_id") or "").strip()
        force = bool(data.get("force"))
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "media task not found")
            row = self.refresh_media_task(conn, row)
            if row["status"] != "completed" or not (row["summary_text"] or row["outline_text"] or row["transcript_text"]):
                return self.error(HTTPStatus.BAD_REQUEST, "分析完成后才能生成 AI 增强分析")
            if not force and (row["enhanced_summary"] or row["key_points"] or row["ai_outputs_json"]):
                return self.json({"task": media_task_public(row), "cached": True})
            model = self.pick_media_ai_model(conn, model_id)
            try:
                outputs = self.call_media_ai_model(model, row)
            except urllib.error.HTTPError as exc:
                detail = exc.read(4096).decode(errors="replace")
                return self.error(HTTPStatus.BAD_GATEWAY, f"AI 增强分析失败：HTTP {exc.code}", detail[:1000])
            except Exception as exc:
                return self.error(HTTPStatus.BAD_GATEWAY, "AI 增强分析失败", str(exc)[:1000])
            self.save_media_ai_outputs(conn, row, outputs)
            updated = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
            if updated["conversation_id"]:
                conversation = self.media_task_conversation_row(conn, updated["conversation_id"], user_id)
                if conversation:
                    self.upsert_media_context_message(conn, updated, conversation["id"], user_id)
        return self.json({"task": media_task_public(updated), "cached": False})

    def handle_conversations(self):
        user = self.current_user()
        user_id = user["id"]
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision
                    FROM conversations c
                    JOIN models m ON m.id = c.model_id
                    WHERE c.archived=0 AND c.user_id=?
                    ORDER BY c.pinned DESC, c.updated_at DESC
                    LIMIT 200
                    """,
                    (user_id,),
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
                INSERT INTO conversations(id, user_id, title, model_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (conversation_id, user_id, title, model_id, ts, ts),
            )
            row = conn.execute(
                """
                SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision
                FROM conversations c JOIN models m ON m.id=c.model_id
                WHERE c.id=? AND c.user_id=?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return self.json({"conversation": conversation_row(row)}, HTTPStatus.CREATED)

    def conversation_id_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) >= 3:
            return parts[2]
        return ""

    def handle_conversation_pin(self):
        conversation_id = self.conversation_id_from_path()
        user_id = self.current_user()["id"]
        pinned = 0 if urlparse(self.path).path.endswith("/unpin") else 1
        with db() as conn:
            existing = conn.execute(
                "SELECT id FROM conversations WHERE id=? AND user_id=? AND archived=0",
                (conversation_id, user_id),
            ).fetchone()
            if not existing:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
            conn.execute(
                "UPDATE conversations SET pinned=?, pinned_at=? WHERE id=? AND user_id=?",
                (pinned, now() if pinned else 0, conversation_id, user_id),
            )
            row = conn.execute(
                """
                SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision
                FROM conversations c
                JOIN models m ON m.id = c.model_id
                WHERE c.id=? AND c.user_id=?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return self.json({"ok": True, "conversation": conversation_row(row)})

    def handle_conversation_stats(self):
        conversation_id = self.conversation_id_from_path()
        user_id = self.current_user()["id"]
        with db() as conn:
            row = conn.execute(
                """
                SELECT c.id, c.updated_at, m.name AS model_name, m.model AS model,
                       COUNT(msg.id) AS message_count,
                       COALESCE(SUM(CASE WHEN msg.role='user' THEN 1 ELSE 0 END), 0) AS turn_count,
                       COALESCE(SUM(
                         CASE
                           WHEN msg.total_tokens > 0 THEN msg.total_tokens
                           ELSE COALESCE(msg.prompt_tokens, 0) + COALESCE(msg.completion_tokens, 0)
                         END
                       ), 0) AS total_tokens
                FROM conversations c
                JOIN models m ON m.id = c.model_id
                LEFT JOIN messages msg ON msg.conversation_id=c.id AND msg.user_id=c.user_id AND msg.role!='system'
                WHERE c.id=? AND c.user_id=? AND c.archived=0
                GROUP BY c.id
                """,
                (conversation_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
            web_search_count = conn.execute(
                """
                SELECT COUNT(DISTINCT s.message_id) AS n
                FROM message_sources s
                JOIN messages msg ON msg.id=s.message_id
                WHERE msg.conversation_id=? AND msg.user_id=?
                """,
                (conversation_id, user_id),
            ).fetchone()["n"]
            attachment_count = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM chat_message_images
                WHERE user_id=? AND session_id=? AND message_id>0
                """,
                (user_id, conversation_id),
            ).fetchone()["n"]
            media_task_count = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM media_analysis_tasks
                WHERE user_id=? AND conversation_id=?
                """,
                (user_id, conversation_id),
            ).fetchone()["n"]
        return self.json(
            {
                "stats": {
                    "total_tokens": int(row["total_tokens"] or 0),
                    "message_count": int(row["message_count"] or 0),
                    "turn_count": int(row["turn_count"] or 0),
                    "model_name": row["model_name"],
                    "model_code": row["model"],
                    "web_search_count": int(web_search_count or 0),
                    "attachment_count": int(attachment_count or 0),
                    "media_task_count": int(media_task_count or 0),
                    "updated_at": row["updated_at"],
                }
            }
        )

    def handle_conversation_item(self):
        conversation_id = self.conversation_id_from_path()
        user_id = self.current_user()["id"]
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id=? AND user_id=? AND archived=0",
                (conversation_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")

            if self.command == "DELETE":
                conn.execute(
                    "UPDATE conversations SET archived=1, updated_at=? WHERE id=? AND user_id=?",
                    (now(), conversation_id, user_id),
                )
                return self.json({"ok": True})

            try:
                data = self.read_body()
            except Exception:
                return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
            title = str(data.get("title") or row["title"]).strip()[:80] or row["title"]
            model_id = str(data.get("model_id") or row["model_id"]).strip()
            if model_id != row["model_id"]:
                model = conn.execute(
                    "SELECT id FROM models WHERE id=? AND enabled=1", (model_id,)
                ).fetchone()
                if not model:
                    return self.error(HTTPStatus.BAD_REQUEST, "model not found")
            conn.execute(
                "UPDATE conversations SET title=?, model_id=?, updated_at=? WHERE id=? AND user_id=?",
                (title, model_id, now(), conversation_id, user_id),
            )
            updated = conn.execute(
                """
                SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision
                FROM conversations c JOIN models m ON m.id=c.model_id
                WHERE c.id=? AND c.user_id=?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return self.json({"ok": True, "conversation": conversation_row(updated)})

    def handle_messages(self):
        conversation_id = self.conversation_id_from_path()
        user_id = self.current_user()["id"]
        with db() as conn:
            row = conn.execute(
                "SELECT id FROM conversations WHERE id=? AND user_id=? AND archived=0",
                (conversation_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
            messages = conn.execute(
                """
                SELECT id, role, content, reasoning_content,
                       prompt_tokens, completion_tokens, total_tokens,
                       created_at
                FROM messages
                WHERE conversation_id=? AND user_id=?
                  AND role!='system'
                ORDER BY id ASC
                """,
                (conversation_id, user_id),
            ).fetchall()
            sources = conn.execute(
                """
                SELECT message_id, title, url, snippet, position
                FROM message_sources
                WHERE message_id IN (
                  SELECT id FROM messages WHERE conversation_id=? AND user_id=?
                  AND role!='system'
                )
                ORDER BY message_id ASC, position ASC
                """,
                (conversation_id, user_id),
            ).fetchall()
            favorites = conn.execute(
                """
                SELECT id, message_id
                FROM favorite_messages
                WHERE message_id IN (
                  SELECT id FROM messages WHERE conversation_id=? AND user_id=?
                  AND role!='system'
                )
                """,
                (conversation_id, user_id),
            ).fetchall()
            images = conn.execute(
                """
                SELECT *
                FROM chat_message_images
                WHERE user_id=? AND session_id=? AND message_id IN (
                  SELECT id FROM messages WHERE conversation_id=? AND user_id=?
                  AND role!='system'
                )
                ORDER BY created_at ASC, id ASC
                """,
                (user_id, conversation_id, conversation_id, user_id),
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
        images_by_message = {}
        for image in images:
            images_by_message.setdefault(image["message_id"], []).append(chat_image_public(image))
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
                        "images": images_by_message.get(row["id"], []),
                    }
                    for row in messages
                ]
            }
        )

    def handle_send_message(self):
        conversation_id = self.conversation_id_from_path()
        user_id = self.current_user()["id"]
        try:
            data = self.read_body(limit=2 * 1024 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        content = str(data.get("content") or "").strip()
        raw_image_ids = data.get("image_ids") or []
        if not isinstance(raw_image_ids, list):
            raw_image_ids = []
        image_ids = []
        for item in raw_image_ids:
            value = str(item or "").strip()
            if value and value not in image_ids:
                image_ids.append(value)
        if len(image_ids) > CHAT_IMAGE_MAX_COUNT:
            return self.error(HTTPStatus.BAD_REQUEST, "单次最多上传 5 张图片")
        requested_web_search = bool(data.get("web_search"))
        if not content and not image_ids:
            return self.error(HTTPStatus.BAD_REQUEST, "content required")

        search_results = []
        search_config = web_search_config(self.server.secrets)
        use_web_search = should_use_web_search(content, requested_web_search, search_config)
        use_profile = data.get("use_profile", True) is not False
        profile_rows = []
        with db() as conn:
            convo = conn.execute(
                """
                SELECT c.*, m.name AS model_name, m.base_url, m.api_key, m.model, m.system_prompt, m.supports_vision, m.enabled
                FROM conversations c JOIN models m ON m.id=c.model_id
                WHERE c.id=? AND c.user_id=? AND c.archived=0
                """,
                (conversation_id, user_id),
            ).fetchone()
            if not convo:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
            if not convo["enabled"]:
                return self.error(HTTPStatus.BAD_REQUEST, "model disabled")
            if not convo["api_key"].strip():
                return self.error(HTTPStatus.BAD_REQUEST, "model api key is not configured")
            image_rows = []
            if image_ids:
                if not convo["supports_vision"]:
                    return self.error(HTTPStatus.BAD_REQUEST, "当前模型不支持图片理解，请切换支持图片的模型。")
                if not chat_image_oss_config(self.server.secrets)["configured"]:
                    return self.error(HTTPStatus.BAD_REQUEST, "图片 OSS 还没有配置好")
                placeholders = ",".join("?" for _ in image_ids)
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM chat_message_images
                    WHERE id IN ({placeholders}) AND user_id=?
                      AND message_id=0
                      AND (session_id='' OR session_id=?)
                    """,
                    (*image_ids, user_id, conversation_id),
                ).fetchall()
                row_by_id = {row["id"]: row for row in rows}
                image_rows = [row_by_id.get(image_id) for image_id in image_ids]
                if any(row is None for row in image_rows):
                    return self.error(HTTPStatus.BAD_REQUEST, "图片附件不存在或已被使用")

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
            user_message_content = content or "请分析这些图片。"
            cursor = conn.execute(
                "INSERT INTO messages(user_id, conversation_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
                (user_id, conversation_id, user_message_content, ts),
            )
            user_message_id = cursor.lastrowid
            if image_rows:
                conn.executemany(
                    "UPDATE chat_message_images SET session_id=?, message_id=? WHERE id=? AND user_id=?",
                    [(conversation_id, user_message_id, row["id"], user_id) for row in image_rows],
                )
            if convo["title"] == "新对话":
                title = user_message_content.replace("\n", " ")[:28] or "图片理解"
                conn.execute(
                    "UPDATE conversations SET title=?, updated_at=? WHERE id=? AND user_id=?",
                    (title, ts, conversation_id, user_id),
                )
            else:
                conn.execute(
                    "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
                    (ts, conversation_id, user_id),
                )
            history = conn.execute(
                """
                SELECT id, role, content
                FROM messages
                WHERE conversation_id=? AND user_id=?
                ORDER BY id ASC
                LIMIT 80
                """,
                (conversation_id, user_id),
            ).fetchall()
            if use_profile:
                profile_rows = conn.execute(
                    """
                    SELECT *
                    FROM user_profiles
                    WHERE user_id=? AND enabled=1
                    ORDER BY sort_order ASC, updated_at DESC
                    LIMIT 80
                    """,
                    (user_id,),
                ).fetchall()
            history_images = conn.execute(
                """
                SELECT *
                FROM chat_message_images
                WHERE user_id=? AND session_id=? AND message_id IN (
                  SELECT id FROM messages WHERE conversation_id=? AND user_id=?
                )
                ORDER BY created_at ASC, id ASC
                """,
                (user_id, conversation_id, conversation_id, user_id),
            ).fetchall()

        images_by_history_message = {}
        for image in history_images:
            images_by_history_message.setdefault(image["message_id"], []).append(image)
        chat_image_config = chat_image_oss_config(self.server.secrets)

        def upstream_message_from_history(row):
            images = images_by_history_message.get(row["id"], [])
            if row["role"] == "user" and images and convo["supports_vision"]:
                if not chat_image_config["configured"]:
                    raise ValueError("图片 OSS 还没有配置好")
                parts = []
                text_content = str(row["content"] or "").strip()
                if text_content:
                    parts.append({"type": "text", "text": text_content})
                for image in images[:CHAT_IMAGE_MAX_COUNT]:
                    signed_url, _ = oss_signed_get_url(chat_image_config, image["oss_key"], 6 * 60 * 60)
                    parts.append({"type": "image_url", "image_url": {"url": signed_url}})
                return {"role": row["role"], "content": parts or row["content"]}
            if row["role"] == "user" and images:
                names = "、".join(image["filename"] for image in images)
                return {"role": row["role"], "content": (row["content"] or "") + f"\n\n[图片附件：{names}]"}
            return {"role": row["role"], "content": row["content"]}

        def make_payload(results, include_usage=True):
            upstream_messages = [
                {"role": "system", "content": build_runtime_context(bool(results))}
            ]
            if convo["system_prompt"].strip():
                upstream_messages.append(
                    {"role": "system", "content": convo["system_prompt"].strip()}
                )
            profile_context = build_user_profile_context(profile_rows) if use_profile else ""
            if profile_context:
                upstream_messages.append(
                    {"role": "system", "content": profile_context}
                )
            if results:
                upstream_messages.append(
                    {"role": "system", "content": build_search_context(results)}
                )
            upstream_messages.extend(upstream_message_from_history(row) for row in history)
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

        def upstream_error_message(code, detail):
            if image_ids and (
                "Unexpected item type in content" in detail
                or "support image input" in detail
                or "image input" in detail
            ):
                return "当前模型接口暂时不接受 image_url 图片消息，请换用支持图片理解的模型。"
            if "data_inspection_failed" in detail:
                return "upstream content rejected"
            return f"upstream status {code}"

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
                    message = upstream_error_message(retry_exc.code, retry_detail)
                    return self.error(HTTPStatus.BAD_GATEWAY, message, retry_detail)
                except Exception as retry_exc:
                    return self.error(
                        HTTPStatus.BAD_GATEWAY, "upstream request failed", str(retry_exc)
                    )
            else:
                message = upstream_error_message(exc.code, detail)
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
                      user_id, conversation_id, role, content, reasoning_content,
                      prompt_tokens, completion_tokens, total_tokens, created_at
                    )
                    VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
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
                    "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
                    (now(), conversation_id, user_id),
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
    init_db(secrets_data)
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
  <script>
    window.tailwind = window.tailwind || {};
    window.tailwind.config = {
      corePlugins: { preflight: false },
      theme: {
        extend: {
          colors: {
            primary: "var(--primary)",
            secondary: "var(--secondary)",
            surface: "var(--surface)",
            border: "var(--border)",
            muted: "var(--muted)",
            text: "var(--text)"
          },
          borderRadius: {
            ui: "var(--radius)",
            card: "var(--radius-card)",
            modal: "var(--radius-modal)"
          },
          boxShadow: {
            ui: "var(--shadow)",
            soft: "var(--soft-shadow)",
            glass: "var(--glass-shadow)"
          }
        }
      }
    };
  </script>
  <script src="https://cdn.tailwindcss.com/3.4.17"></script>
  <script defer src="https://unpkg.com/lucide@1.21.0/dist/umd/lucide.min.js"></script>
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
      --primary: var(--accent);
      --primary-strong: var(--accent-strong);
      --secondary: #F6E9D6;
      --border: var(--line);
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
      --glass-shadow: 0 20px 52px rgba(46, 41, 32, .14);
      --radius: 8px;
      --radius-card: 16px;
      --radius-modal: 24px;
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
      --primary: var(--accent);
      --primary-strong: var(--accent-strong);
      --secondary: #252c2a;
      --border: var(--line);
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
      --glass-shadow: 0 22px 54px rgba(0, 0, 0, .38);
    }
    * { box-sizing: border-box; }
    [hidden] { display: none !important; }
    html, body {
      height: 100%;
      min-height: 100%;
      overflow: hidden;
      overscroll-behavior: none;
    }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font: 15px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", sans-serif;
      -webkit-font-smoothing: antialiased;
      overflow: hidden;
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
    .ui-btn {
      min-height: 40px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--surface);
      color: var(--text);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      font-weight: 680;
      box-shadow: none;
    }
    .ui-btn-primary {
      background: var(--primary);
      border-color: var(--primary);
      color: #fff;
      box-shadow: 0 10px 24px var(--accent-shadow);
    }
    .ui-btn-secondary {
      background: var(--secondary);
      border-color: var(--border);
      color: var(--text);
    }
    .ui-btn-ghost {
      background: transparent;
      border-color: transparent;
      color: var(--muted);
    }
    .ui-icon-btn {
      display: inline-grid;
      place-items: center;
      gap: 0;
    }
    .ui-card {
      border: 1px solid var(--border);
      border-radius: var(--radius-card);
      background: var(--surface);
      box-shadow: var(--soft-shadow);
    }
    .ui-modal {
      border: 1px solid color-mix(in srgb, var(--border) 72%, transparent);
      border-radius: var(--radius-modal);
      background: var(--surface);
      box-shadow: var(--shadow);
    }
    .ui-input,
    .ui-select {
      min-height: 42px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: var(--surface);
      color: var(--text);
    }
    .ui-badge {
      min-height: 22px;
      border: 1px solid var(--border);
      border-radius: 999px;
      background: var(--surface-soft);
      color: var(--muted);
      display: inline-flex;
      align-items: center;
      padding: 0 8px;
      font-size: 12px;
      font-weight: 720;
    }
    .ui-toast {
      border: 1px solid color-mix(in srgb, var(--border) 78%, transparent);
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface) 88%, transparent);
      color: var(--text);
      box-shadow: var(--glass-shadow);
      -webkit-backdrop-filter: blur(16px) saturate(150%);
      backdrop-filter: blur(16px) saturate(150%);
    }
    .lucide {
      width: 18px;
      height: 18px;
      stroke-width: 2;
      flex: 0 0 auto;
    }
    .icon .lucide,
    .composer-action .lucide,
    .sidebar-action .lucide,
    .side-primary-action .lucide,
    .message-action .lucide {
      width: 18px;
      height: 18px;
    }
    .lucide-ready .icon-fallback {
      display: none !important;
    }
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
	    .login-panel label,
	    .library-editor label,
	    .drawer .panel label,
	    .media-upload label,
	    .color-field {
	      display: grid;
	      gap: 7px;
	      color: var(--muted);
	      font-size: 13px;
	      font-weight: 680;
	    }
	    .login-panel input:not([type="hidden"]),
	    .library-editor input:not([type="hidden"]),
	    .library-editor textarea,
	    .drawer .panel input:not([type="hidden"]),
	    .drawer .panel select,
	    .drawer .panel textarea,
	    .media-upload input[type="file"],
	    .color-field input[type="color"],
	    #manualCopyText {
	      min-height: 44px;
	      border: 1px solid color-mix(in srgb, var(--line) 78%, transparent);
	      border-radius: 14px;
	      background: color-mix(in srgb, var(--surface) 88%, var(--surface-soft));
	      color: var(--text);
	      box-shadow: inset 0 1px 0 rgba(255,255,255,.42);
	    }
	    .library-editor textarea,
	    .drawer .panel textarea,
	    #manualCopyText {
	      line-height: 1.65;
	    }
	    .drawer .panel select,
	    .library-editor input[type="number"] {
	      cursor: pointer;
	    }
	    .empty-state {
	      min-height: 180px;
	      display: grid;
	      place-items: center;
	      gap: 8px;
	      padding: 24px;
	      border: 1px dashed color-mix(in srgb, var(--line) 78%, transparent);
	      border-radius: 18px;
	      background: color-mix(in srgb, var(--surface) 76%, var(--surface-soft));
	      color: var(--muted);
	      text-align: center;
	    }
	    .empty-state.compact {
	      min-height: 120px;
	      padding: 16px;
	    }
	    .empty-state .lucide {
	      width: 28px;
	      height: 28px;
	      color: var(--accent-strong);
	      stroke-width: 1.9;
	    }
	    .empty-state strong {
	      color: var(--text);
	      font-size: 15px;
	      font-weight: 760;
	    }
	    .empty-state p {
	      max-width: 320px;
	      margin: 0;
	      color: var(--muted);
	      font-size: 13px;
	      line-height: 1.6;
	    }
	    .login {
      height: 100%;
      min-height: 100%;
      display: grid;
      place-items: center;
      padding: 20px;
      overflow: auto;
      overscroll-behavior: contain;
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
    .login-copy .app-version {
      justify-self: center;
      min-height: 24px;
      padding: 0 10px;
      border: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface-soft) 70%, transparent);
      color: var(--muted);
      font-size: 12px;
      font-weight: 760;
    }
    .login-copy .app-version:hover,
    .login-copy .app-version:focus-visible {
      border-color: color-mix(in srgb, var(--accent) 50%, var(--line));
      background: color-mix(in srgb, var(--accent-soft) 70%, var(--surface));
    }
    .login-panel label {
      font-weight: 680;
      color: var(--muted);
    }
    .site-icp {
      color: var(--muted-2);
      font-size: 12px;
      line-height: 1.5;
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 6px 10px;
      text-align: center;
    }
    .site-icp a {
      color: inherit;
      text-decoration: none;
    }
    .site-icp a:hover {
      color: var(--accent-strong);
    }
    .version-trigger {
      appearance: none;
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      cursor: pointer;
      text-decoration: none;
      transition: color .15s ease, background .15s ease, border-color .15s ease, transform .15s ease, box-shadow .15s ease;
    }
    .version-trigger:hover,
    .version-trigger:focus-visible {
      color: var(--accent-strong);
      outline: none;
    }
    .site-icp .version-trigger {
      min-height: 0;
      padding: 0;
      border-radius: 999px;
    }
    .site-icp .version-trigger:hover,
    .site-icp .version-trigger:focus-visible {
      transform: translateY(-1px);
    }
    .app {
      height: var(--app-height, 100vh);
      min-height: 0;
      display: grid;
      grid-template-columns: var(--sidebar-width, 304px) minmax(0, 1fr);
      overflow: hidden;
      background: var(--bg);
    }
    .sidebar {
      border-right: 1px solid var(--line);
      background: var(--sidebar);
      display: grid;
      grid-template-rows: auto auto auto 1fr auto;
      height: var(--app-height, 100vh);
      min-height: 0;
      min-width: 0;
      overflow: hidden;
      position: relative;
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
    .brand h1 .app-version:hover,
    .brand h1 .app-version:focus-visible {
      border-color: color-mix(in srgb, var(--accent) 58%, var(--line));
      background: color-mix(in srgb, var(--accent-soft) 72%, var(--surface));
      box-shadow: 0 8px 20px rgba(217, 143, 168, .14);
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
    .side-primary-action,
    .sidebar-action {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
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
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-weight: 580;
      font-size: 14px;
    }
    .conv-title-text {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .conv-pin-indicator {
      display: inline-grid;
      place-items: center;
      width: 16px;
      height: 16px;
      color: var(--accent-strong);
      opacity: .86;
      flex: 0 0 auto;
    }
    .conv-pin-indicator .lucide {
      width: 13px;
      height: 13px;
      stroke-width: 2.4;
    }
    .conv-meta {
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .conv-model {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .conv-time {
      flex: 0 0 auto;
      white-space: nowrap;
    }
    .conv-time::before {
      content: "·";
      margin: 0 6px;
      color: var(--muted-2);
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
    .conv.pinned .pin-action,
    .conv.editing .conv-actions,
    .conv:focus-within .conv-actions {
      opacity: 1;
      pointer-events: auto;
    }
    .conv.pinned .pin-action {
      color: var(--accent-strong);
      background: color-mix(in srgb, var(--accent-soft) 72%, transparent);
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
    .conv-action .lucide {
      width: 15px;
      height: 15px;
      stroke-width: 2.2;
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
      min-height: 0;
      position: relative;
      display: grid;
      grid-template-rows: auto 1fr auto;
      height: var(--app-height, 100vh);
      overflow: hidden;
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
      min-height: 0;
      overflow-x: hidden;
      overflow-y: auto;
      padding: 32px clamp(14px, 4vw, 48px) 26px;
      display: flex;
      flex-direction: column;
      gap: 20px;
      scroll-behavior: smooth;
      overscroll-behavior-y: contain;
      -webkit-overflow-scrolling: touch;
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
      width: 100%;
      max-width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      background: var(--surface-soft);
      color: var(--muted);
      padding: 0;
      margin: 0 0 14px;
      overflow: hidden;
      box-shadow: none;
    }
    .reasoning-panel[hidden] { display: none; }
    .reasoning-toggle {
      width: 100%;
      min-height: 38px;
      padding: 0 12px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      border: 0;
      border-radius: 0;
      background: transparent;
      color: var(--muted);
      font-size: 13px;
      font-weight: 720;
      box-shadow: none;
    }
    .reasoning-toggle::after {
      content: "⌄";
      color: var(--muted-2);
      transition: transform .16s ease;
    }
    .reasoning-panel.open .reasoning-toggle::after {
      transform: rotate(180deg);
    }
    .reasoning-body {
      padding: 10px 12px 12px;
      border-top: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
    }
    .reasoning-body[hidden] { display: none; }
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
	      overflow-x: auto;
	      -webkit-overflow-scrolling: touch;
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
	    .markdown-scroll,
	    .table-wrapper,
	    .media-wrapper {
	      max-width: 100%;
	      overflow-x: auto;
	      overflow-y: hidden;
	      -webkit-overflow-scrolling: touch;
	      overscroll-behavior-x: contain;
	    }
	    .media-wrapper {
	      display: block;
	      margin: 12px 0 14px;
	    }
	    .markdown img {
	      display: block;
	      max-width: none;
	      height: auto;
	      border-radius: 12px;
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
	    .table-wrapper {
	      position: relative;
	      margin: 12px 0 14px;
	      border: 1px solid var(--line);
	      border-radius: 12px;
	      background: var(--surface);
	    }
	    .table-wrapper table {
	      width: max-content;
	      min-width: max-content;
	      max-width: none;
	      border-collapse: separate;
	      border-spacing: 0;
	      margin: 0;
	      font-size: 14px;
	    }
	    .table-wrapper th,
	    .table-wrapper td {
	      border: 0;
	      border-right: 1px solid var(--line);
	      border-bottom: 1px solid var(--line);
	      padding: 8px 9px;
	      text-align: left;
	      vertical-align: top;
	      white-space: nowrap;
	      word-break: normal;
	      overflow-wrap: normal;
	    }
	    .table-wrapper tr > :last-child { border-right: 0; }
	    .table-wrapper tbody tr:last-child > td { border-bottom: 0; }
	    .table-wrapper th {
	      background: var(--surface-soft);
	      font-weight: 650;
	    }
	    .table-scroll-hint {
	      display: none;
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
    .search-toggle .lucide {
      width: 16px;
      height: 16px;
      color: var(--accent-strong);
      stroke-width: 2.2;
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
      grid-template-columns: 42px minmax(0, 1fr) 42px 42px auto;
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
    .composer-action {
      width: 42px;
      min-width: 42px;
      height: 42px;
      min-height: 42px;
      padding: 0;
      border-radius: 12px;
      display: inline-grid;
      place-items: center;
      border: 1px solid color-mix(in srgb, var(--line) 82%, transparent);
      background: color-mix(in srgb, var(--surface-soft) 76%, transparent);
      color: var(--muted);
      font-size: 19px;
      font-weight: 800;
      line-height: 1;
      box-shadow: inset 0 1px 0 rgba(255,255,255,.42);
    }
    .composer-action:hover {
      color: var(--accent-strong);
      border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
      background: color-mix(in srgb, var(--accent-soft) 66%, transparent);
    }
    .composer-action[disabled] {
      cursor: not-allowed;
      opacity: .45;
    }
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
	    .favorite-dialog,
	    .profile-dialog,
	    .media-dialog {
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
	    .favorite-dialog.show,
	    .profile-dialog.show,
	    .media-dialog.show { display: grid; }
    .confirm-dialog { z-index: 40; }
    .copy-panel,
    .confirm-panel,
    .accent-panel,
    .profile-panel,
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
    .profile-panel {
      width: min(980px, 100%);
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
	    .dialog-title,
	    .panel-title,
	    .library-editor-title {
	      display: inline-flex;
	      align-items: center;
	      gap: 8px;
	    }
	    .dialog-title .lucide,
	    .panel-title .lucide,
	    .library-editor-title .lucide {
	      width: 17px;
	      height: 17px;
	      color: var(--accent-strong);
	      stroke-width: 2.2;
	    }
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
    .profile-summary {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .profile-layout {
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(300px, .9fr);
      gap: 14px;
      align-items: start;
    }
    .profile-token-warning {
      color: var(--yellow);
      font-weight: 720;
    }
    .profile-card {
      cursor: grab;
    }
    .profile-card.dragging {
      opacity: .58;
      transform: scale(.99);
    }
    .profile-card.disabled {
      opacity: .62;
    }
    .profile-card-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
    }
    .profile-card-title {
      min-width: 0;
      display: grid;
      gap: 3px;
    }
    .profile-card-title strong {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .profile-card-content {
      white-space: pre-wrap;
      max-height: 130px;
      overflow: hidden;
    }
    .profile-switch {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      color: var(--muted);
      font-size: 12px;
      cursor: pointer;
      user-select: none;
    }
    .profile-switch input {
      width: 16px;
      min-height: 16px;
      accent-color: var(--accent);
      box-shadow: none;
    }
    .profile-status-chip {
      justify-self: center;
      width: fit-content;
      min-height: 24px;
      margin: 3px auto 0;
      padding: 0 9px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      border: 1px solid color-mix(in srgb, var(--line) 72%, transparent);
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface) 62%, transparent);
      color: var(--muted);
      font-size: 12px;
      font-weight: 720;
    }
    .profile-status-chip .lucide {
      width: 14px;
      height: 14px;
      color: var(--accent-strong);
    }
    .profile-status-chip.disabled {
      opacity: .64;
    }
    .profile-status-chip:hover,
    .profile-status-chip:focus-visible {
      color: var(--accent-strong);
      border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
      background: color-mix(in srgb, var(--accent-soft) 56%, var(--surface));
    }
    .profile-popover {
      position: absolute;
      top: 72px;
      left: 50%;
      z-index: 13;
      width: min(360px, calc(100vw - 24px));
      display: none;
      transform: translateX(-50%);
      border: 1px solid var(--glass-border);
      border-radius: 22px;
      background: var(--glass-bg);
      color: var(--text);
      box-shadow: var(--glass-shadow-strong);
      -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(160%);
      backdrop-filter: blur(var(--glass-blur)) saturate(160%);
      overflow: hidden;
    }
    .profile-popover.show {
      display: grid;
      animation: searchScaleIn .16s cubic-bezier(.2, .8, .2, 1) both;
    }
    .profile-popover-head,
    .profile-popover-foot {
      padding: 12px;
      border-bottom: 1px solid color-mix(in srgb, var(--line) 72%, transparent);
    }
    .profile-popover-foot {
      border-top: 1px solid color-mix(in srgb, var(--line) 72%, transparent);
      border-bottom: 0;
    }
    .profile-popover-list {
      display: grid;
      gap: 6px;
      max-height: 260px;
      overflow: auto;
      padding: 10px 12px;
      color: var(--muted);
      font-size: 13px;
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
	    .library-actions .ui-btn {
	      min-height: 36px;
	      border-radius: 999px;
	      padding: 0 12px;
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
	    .media-layout {
	      display: grid;
	      grid-template-columns: minmax(260px, .85fr) minmax(0, 1.15fr);
	      gap: 14px;
	      align-items: start;
	    }
	    .media-upload {
	      margin-bottom: 14px;
	      border: 1px solid color-mix(in srgb, var(--accent) 30%, var(--line));
	      border-radius: 14px;
	      background: color-mix(in srgb, var(--accent-soft) 38%, var(--surface));
	      padding: 14px;
	      display: grid;
	      gap: 10px;
	    }
	    .media-upload-row {
	      display: grid;
	      grid-template-columns: minmax(0, 1fr) auto;
	      gap: 10px;
	      align-items: end;
	    }
		    .media-tabs {
		      display: flex;
		      gap: 8px;
		      flex-wrap: wrap;
		      margin-bottom: 12px;
		    }
		    .media-dialog-title,
		    .media-upload-title,
		    .media-ai-title {
		      display: inline-flex;
		      align-items: center;
		      gap: 8px;
		    }
		    .media-dialog-title .lucide,
		    .media-upload-title .lucide,
		    .media-ai-title .lucide,
		    .media-tab .lucide,
		    .media-task-badge .lucide,
		    .media-ai-actions .lucide,
		    .library-actions .lucide {
		      width: 16px;
		      height: 16px;
		      color: currentColor;
		      stroke-width: 2.2;
		    }
		    .media-ai-panel {
		      border: 1px solid color-mix(in srgb, var(--accent) 28%, var(--line));
	      border-radius: 16px;
	      background:
	        radial-gradient(circle at 12% 8%, color-mix(in srgb, var(--accent-soft) 70%, transparent), transparent 36%),
	        color-mix(in srgb, var(--accent-soft) 24%, var(--surface));
	      padding: 12px;
	      display: grid;
	      gap: 10px;
	    }
		    .media-ai-panel strong {
		      font-size: 15px;
		    }
	    .media-ai-actions {
	      display: flex;
	      flex-wrap: wrap;
	      gap: 8px;
	    }
	    .media-ai-actions button {
	      min-height: 36px;
	      border-radius: 999px;
	      padding: 0 12px;
	    }
	    .media-ai-actions .primary {
	      box-shadow: 0 10px 24px var(--accent-shadow);
	    }
	    .media-ai-hint {
	      color: var(--muted);
	      font-size: 12px;
	      line-height: 1.6;
	    }
		    .media-tab {
		      min-height: 34px;
		      padding: 0 12px;
		      border-radius: 999px;
		      display: inline-flex;
		      align-items: center;
		      gap: 6px;
		    }
	    .media-tab.active {
	      border-color: color-mix(in srgb, var(--accent) 54%, var(--line));
	      background: var(--accent-soft);
	      color: var(--accent-strong);
	    }
	    .media-detail {
	      min-height: 360px;
	      border: 1px solid var(--line);
	      border-radius: 12px;
	      background: var(--surface);
	      padding: 14px;
	      box-shadow: var(--soft-shadow);
	      display: grid;
	      gap: 12px;
	      align-content: start;
	    }
	    .media-task-head {
	      display: flex;
	      justify-content: space-between;
	      gap: 12px;
	      align-items: flex-start;
	      flex-wrap: wrap;
	      border-bottom: 1px solid var(--line);
	      padding-bottom: 10px;
	    }
	    .media-task-head strong {
	      display: block;
	      color: var(--text);
	      font-size: 16px;
	      margin-bottom: 2px;
	    }
	    .media-task-badge {
	      display: inline-flex;
	      align-items: center;
	      min-height: 30px;
	      border-radius: 999px;
	      padding: 0 10px;
	      background: var(--accent-soft);
	      color: var(--accent-strong);
	      font-size: 12px;
	      font-weight: 700;
	    }
	    .media-result {
	      max-height: min(56vh, 620px);
	      overflow: auto;
	      border: 1px solid var(--line);
	      border-radius: 12px;
	      background: var(--surface-soft);
	      padding: 14px;
	    }
	    .media-result pre {
	      margin: 0;
	      white-space: pre-wrap;
	      word-break: break-word;
	      font: inherit;
	      line-height: 1.7;
	    }
	    .media-empty {
	      min-height: 260px;
	      display: grid;
	      place-items: center;
	      color: var(--muted);
	      text-align: center;
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
    .token-summary-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 8px;
      margin-bottom: 12px;
    }
    .token-summary-card {
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--surface-soft);
      padding: 10px;
      display: grid;
      gap: 4px;
      min-width: 0;
    }
    .token-summary-card span {
      color: var(--muted);
      font-size: 12px;
    }
    .token-summary-card strong {
      font-size: 18px;
      letter-spacing: 0;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .token-filter-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 180px auto;
      gap: 10px;
      align-items: end;
    }
    .token-user-row {
      align-items: start;
    }
    .token-user-main {
      min-width: 0;
      display: grid;
      gap: 5px;
    }
    .token-user-main strong,
    .token-user-main span {
      display: block;
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }
    .token-user-main span {
      color: var(--muted);
      font-size: 12px;
    }
    .token-user-stats {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
    }
    .token-user-stats b {
      color: var(--text);
      font-weight: 720;
    }
    .token-detail {
      grid-column: 1 / -1;
      border: 1px solid var(--line);
      border-radius: 12px;
      background: var(--surface-soft);
      padding: 8px;
      overflow-x: auto;
    }
    .token-detail table {
      width: 100%;
      min-width: 720px;
      border-collapse: collapse;
      font-size: 12px;
    }
    .token-detail th,
    .token-detail td {
      padding: 7px 8px;
      text-align: left;
      border-bottom: 1px solid var(--line);
      white-space: nowrap;
    }
    .token-detail tr:last-child td { border-bottom: 0; }
    .token-detail th {
      color: var(--muted);
      font-weight: 720;
    }
    @media (max-width: 900px) {
      .token-summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .token-filter-row { grid-template-columns: 1fr; }
    }
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
      .input-row { grid-template-columns: 38px minmax(0, 1fr) 38px 38px 44px; }
      .bubble-shell { max-width: 100%; }
      .bubble.user,
      .bubble.assistant { justify-items: stretch; }
      .prompt-grid { grid-template-columns: 1fr; }
      .grid2 { grid-template-columns: 1fr; }
      .drawer { width: 100%; }
      .copy-panel,
      .confirm-panel,
      .accent-panel,
      .profile-panel,
      .library-panel { max-height: 92vh; }
      .accent-grid { grid-template-columns: 1fr; }
	      .library-grid,
	      .favorite-layout,
	      .profile-layout,
	      .media-layout { grid-template-columns: 1fr; }
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
      --sidebar-width: 322px;
      --composer-width: 1040px;
      --composer-glass-rgb: 255, 252, 248;
      --composer-field-rgb: 255, 255, 255;
      --composer-control-rgb: 246, 233, 214;
      --composer-glass-opacity: .8;
      --composer-field-opacity: .38;
      --composer-field-focus-opacity: .46;
      --composer-control-opacity: .44;
      --composer-glass-blur: 18px;
      --composer-field-blur: 12px;
      --glass-opacity: var(--composer-glass-opacity);
      --glass-blur: var(--composer-glass-blur);
      --glass-bg: rgba(var(--composer-glass-rgb), var(--glass-opacity));
      --glass-border: color-mix(in srgb, var(--line) 52%, rgba(255,255,255,.72));
      --glass-shadow:
        inset 0 1px 0 rgba(255,255,255,.82),
        inset 0 -1px 0 rgba(255,255,255,.34),
        0 18px 50px rgba(73, 54, 35, .14);
      --glass-shadow-strong:
        inset 0 1px 0 rgba(255,255,255,.82),
        inset 0 -1px 0 rgba(255,255,255,.38),
        0 20px 58px rgba(73, 54, 35, .16);
      --scroll-latest-bottom: calc(max(12px, env(safe-area-inset-bottom, 0px)) + 160px);
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
      --composer-glass-rgb: 31, 28, 25;
      --composer-field-rgb: 255, 255, 255;
      --composer-control-rgb: 255, 255, 255;
      --glass-border: color-mix(in srgb, var(--line) 72%, rgba(255,255,255,.12));
      --glass-shadow:
        inset 0 1px 0 rgba(255,255,255,.1),
        inset 0 -1px 0 rgba(255,255,255,.04),
        0 18px 50px rgba(0, 0, 0, .34);
      --glass-shadow-strong:
        inset 0 1px 0 rgba(255,255,255,.12),
        inset 0 -1px 0 rgba(255,255,255,.06),
        0 20px 58px rgba(0, 0, 0, .42);
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
      grid-template-columns: var(--sidebar-width) minmax(0, 1fr);
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
    .global-search-trigger {
      width: 100%;
      min-height: 44px;
      justify-content: flex-start;
      gap: 10px;
      padding: 0 12px;
      border: 1px solid color-mix(in srgb, var(--line) 82%, transparent);
      border-radius: 16px;
      background: color-mix(in srgb, var(--surface) 72%, transparent);
      color: var(--muted);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.42);
      font-weight: 650;
      text-align: left;
    }
    .global-search-trigger:hover,
    .global-search-trigger:focus-visible {
      color: var(--text);
      border-color: color-mix(in srgb, var(--accent) 36%, var(--line));
      background: color-mix(in srgb, var(--surface) 88%, var(--accent-soft));
    }
    .global-search-trigger .shortcut {
      margin-left: auto;
      min-width: 42px;
      padding: 3px 7px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface-soft) 80%, transparent);
      color: var(--muted-2);
      font-size: 11px;
      font-weight: 760;
      text-align: center;
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
      display: flex;
      align-items: center;
      min-width: 0;
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
    .side-foot button .lucide {
      width: 15px;
      height: 15px;
      color: currentColor;
      stroke-width: 2.2;
    }
    .side-icp {
      grid-column: 1 / -1;
      padding-top: 4px;
    }
    .sidebar-resizer {
      display: none;
      position: absolute;
      top: 0;
      right: -6px;
      bottom: 0;
      width: 12px;
      min-width: 12px;
      min-height: 0;
      padding: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
      cursor: col-resize;
      z-index: 8;
      touch-action: none;
    }
    .sidebar-resizer::before {
      content: "";
      position: absolute;
      top: 18px;
      bottom: 18px;
      left: 5px;
      width: 2px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--accent) 38%, transparent);
      opacity: 0;
      transition: opacity .16s ease, background .16s ease;
    }
    .sidebar-resizer:hover::before,
    .sidebar-resizer:focus-visible::before,
    body.sidebar-resizing .sidebar-resizer::before {
      opacity: 1;
      background: color-mix(in srgb, var(--accent) 72%, var(--line));
    }
    body.sidebar-resizing {
      cursor: col-resize;
      user-select: none;
    }
    body.sidebar-resizing .main,
    body.sidebar-resizing .messages {
      pointer-events: none;
    }
    .global-search-dialog {
      position: fixed;
      inset: 0;
      z-index: 90;
      display: none;
      place-items: start center;
      padding: min(12vh, 96px) 18px 24px;
      background: rgba(34, 28, 24, .18);
      -webkit-backdrop-filter: blur(10px) saturate(120%);
      backdrop-filter: blur(10px) saturate(120%);
    }
    .global-search-dialog.show {
      display: grid;
      animation: searchFadeIn .16s ease both;
    }
    .global-search-panel {
      width: min(720px, 100%);
      max-height: min(76vh, 720px);
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      overflow: hidden;
      border: 1px solid color-mix(in srgb, var(--line) 72%, transparent);
      border-radius: 26px;
      background: color-mix(in srgb, var(--surface) 88%, transparent);
      box-shadow: 0 26px 80px rgba(73, 54, 35, .18);
      -webkit-backdrop-filter: blur(20px) saturate(155%);
      backdrop-filter: blur(20px) saturate(155%);
      transform-origin: 50% 12%;
      animation: searchScaleIn .18s cubic-bezier(.2, .8, .2, 1) both;
    }
    .global-search-head {
      display: flex;
      align-items: center;
      gap: 12px;
      min-height: 70px;
      padding: 12px 16px;
      border-bottom: 1px solid color-mix(in srgb, var(--line) 72%, transparent);
    }
    .global-search-head .lucide {
      color: var(--muted);
    }
    #globalSearchInput {
      min-height: 46px;
      padding: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
      box-shadow: none;
      font-size: 18px;
      font-weight: 650;
    }
    #globalSearchInput:focus {
      box-shadow: none;
    }
    .global-search-key {
      flex: 0 0 auto;
      padding: 5px 9px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface-soft) 84%, transparent);
      color: var(--muted);
      font-size: 12px;
      font-weight: 760;
    }
    .global-search-list {
      min-height: 230px;
      overflow: auto;
      padding: 10px;
    }
    .global-search-item {
      width: 100%;
      display: grid;
      grid-template-columns: 38px minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      min-height: 76px;
      padding: 12px;
      border: 1px solid transparent;
      border-radius: 18px;
      background: transparent;
      color: var(--text);
      text-align: left;
      transition: background .14s ease, border-color .14s ease, transform .14s ease;
    }
    .global-search-item:hover,
    .global-search-item.active {
      border-color: color-mix(in srgb, var(--accent) 28%, transparent);
      background: color-mix(in srgb, var(--accent-soft) 48%, var(--surface));
      transform: translateY(-1px);
    }
    .global-search-icon {
      width: 38px;
      height: 38px;
      display: inline-grid;
      place-items: center;
      border-radius: 14px;
      background: color-mix(in srgb, var(--surface-soft) 76%, transparent);
      color: var(--accent-strong);
    }
    .global-search-content {
      min-width: 0;
      display: grid;
      gap: 5px;
    }
    .global-search-title {
      display: flex;
      gap: 8px;
      align-items: center;
      min-width: 0;
      color: var(--text);
      font-weight: 760;
    }
    .global-search-title span:first-child {
      overflow: hidden;
      white-space: nowrap;
      text-overflow: ellipsis;
    }
    .global-search-role {
      flex: 0 0 auto;
      padding: 2px 7px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface-soft) 86%, transparent);
      color: var(--muted);
      font-size: 11px;
      font-weight: 760;
    }
    .global-search-snippet {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.55;
    }
    .global-search-snippet mark {
      border-radius: 5px;
      background: color-mix(in srgb, var(--accent) 22%, transparent);
      color: var(--accent-strong);
      padding: 0 2px;
    }
    .global-search-time {
      color: var(--muted-2);
      font-size: 12px;
      white-space: nowrap;
    }
    .changelog-dialog {
      position: fixed;
      inset: 0;
      z-index: 46;
      display: none;
      pointer-events: none;
    }
    .changelog-dialog.show {
      display: block;
    }
    .changelog-dialog.full {
      pointer-events: auto;
      display: grid;
      place-items: center;
      padding: min(10vh, 82px) 18px 24px;
      background: rgba(34, 28, 24, .16);
      -webkit-backdrop-filter: blur(10px) saturate(120%);
      backdrop-filter: blur(10px) saturate(120%);
    }
    .changelog-panel {
      position: absolute;
      width: min(430px, calc(100vw - 24px));
      max-height: min(72vh, 640px);
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      overflow: hidden;
      pointer-events: auto;
      border: 1px solid var(--glass-border);
      border-radius: 24px;
      background: var(--glass-bg);
      color: var(--text);
      box-shadow: var(--glass-shadow-strong);
      -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(160%);
      backdrop-filter: blur(var(--glass-blur)) saturate(160%);
      transform-origin: 50% 0;
      animation: searchScaleIn .16s cubic-bezier(.2, .8, .2, 1) both;
    }
    .changelog-dialog.full .changelog-panel {
      position: relative;
      inset: auto !important;
      width: min(760px, 100%);
      max-height: min(82vh, 760px);
      transform-origin: 50% 12%;
    }
    .changelog-head,
    .changelog-foot {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 12px 14px;
      border-bottom: 1px solid color-mix(in srgb, var(--line) 72%, transparent);
    }
    .changelog-foot {
      border-top: 1px solid color-mix(in srgb, var(--line) 72%, transparent);
      border-bottom: 0;
      justify-content: flex-end;
    }
    .changelog-title {
      min-width: 0;
      display: flex;
      align-items: center;
      gap: 9px;
      font-weight: 780;
      color: var(--text);
    }
    .changelog-title .lucide {
      color: var(--accent-strong);
      width: 18px;
      height: 18px;
      stroke-width: 2.2;
    }
    .changelog-list {
      overflow: auto;
      padding: 10px;
      display: grid;
      gap: 10px;
      min-height: 180px;
    }
    .changelog-entry {
      display: grid;
      gap: 8px;
      padding: 12px;
      border: 1px solid color-mix(in srgb, var(--line) 72%, transparent);
      border-radius: 18px;
      background: color-mix(in srgb, var(--surface) 68%, transparent);
      box-shadow: 0 10px 26px rgba(73, 54, 35, .06);
    }
    .changelog-entry.is-current {
      border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
      background: color-mix(in srgb, var(--accent-soft) 42%, var(--surface));
    }
    .changelog-entry-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
    }
    .changelog-version {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      min-width: 0;
      font-weight: 800;
      color: var(--text);
    }
    .changelog-date {
      flex: 0 0 auto;
      color: var(--muted-2);
      font-size: 12px;
    }
    .changelog-current {
      border: 1px solid color-mix(in srgb, var(--accent) 45%, transparent);
      border-radius: 999px;
      padding: 2px 7px;
      background: color-mix(in srgb, var(--accent-soft) 70%, transparent);
      color: var(--accent-strong);
      font-size: 11px;
      font-weight: 760;
    }
    .changelog-entry h3 {
      margin: 0;
      color: var(--text);
      font-size: 14px;
      letter-spacing: 0;
      line-height: 1.35;
    }
    .changelog-points {
      margin: 0;
      padding: 0 0 0 17px;
      color: var(--muted);
      display: grid;
      gap: 4px;
      font-size: 13px;
      line-height: 1.55;
    }
    .changelog-points li {
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .changelog-dialog.full .changelog-points li {
      display: list-item;
      overflow: visible;
    }
    .changelog-commit {
      color: var(--muted-2);
      font-size: 11px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    .changelog-more {
      min-height: 38px;
      border-radius: 999px;
      color: var(--accent-strong);
      background: color-mix(in srgb, var(--surface-soft) 72%, transparent);
    }
    .changelog-more .lucide {
      width: 16px;
      height: 16px;
    }
    .changelog-empty {
      min-height: 160px;
      display: grid;
      place-items: center;
      color: var(--muted);
      text-align: center;
    }
    .search-hit-highlight .bubble-shell {
      animation: searchHitPulse 1.8s ease;
    }
    @keyframes searchFadeIn {
      from { opacity: 0; }
      to { opacity: 1; }
    }
    @keyframes searchScaleIn {
      from { opacity: 0; transform: scale(.975) translateY(-6px); }
      to { opacity: 1; transform: scale(1) translateY(0); }
    }
    @keyframes searchHitPulse {
      0%, 100% { box-shadow: inherit; }
      16% { box-shadow: 0 0 0 4px color-mix(in srgb, var(--accent) 22%, transparent), var(--shadow); }
    }
    @media (min-width: 901px) {
      .sidebar-resizer {
        display: block;
      }
    }
    .main {
      position: relative;
      overflow: hidden;
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
      padding-bottom: clamp(180px, 22vh, 248px);
    }
    .conversation-minimap {
      position: absolute;
      left: clamp(14px, 1.8vw, 28px);
      top: 86px;
      bottom: clamp(188px, 23vh, 258px);
      z-index: 5;
      width: 8px;
      padding: 7px 0;
      border-radius: 16px;
      border: 0;
      background: transparent;
      box-shadow: none;
      opacity: .42;
      transform-origin: left center;
      filter: saturate(.94);
      transition: opacity .2s ease, width .24s cubic-bezier(.2, .8, .2, 1), transform .24s cubic-bezier(.2, .8, .2, 1), filter .24s ease, background .2s ease, box-shadow .2s ease;
    }
    .conversation-minimap:hover,
    .conversation-minimap:focus-within,
    .conversation-minimap.is-scrolling {
      opacity: .86;
      background: color-mix(in srgb, var(--surface) 16%, transparent);
      filter: saturate(1.02);
    }
    .conversation-minimap.is-expanded {
      width: 56px;
      opacity: .92;
      transform: translateX(-2px);
      background: color-mix(in srgb, var(--surface) 26%, transparent);
      box-shadow: 0 16px 46px rgba(73, 54, 35, .06);
      -webkit-backdrop-filter: blur(10px) saturate(130%);
      backdrop-filter: blur(10px) saturate(130%);
    }
    .minimap-track {
      position: relative;
      height: 100%;
      border-radius: 999px;
    }
    .minimap-viewport {
      position: absolute;
      left: 50%;
      width: 8px;
      min-height: 18px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--accent) 24%, transparent);
      background: color-mix(in srgb, var(--accent-soft) 34%, transparent);
      box-shadow: 0 5px 16px rgba(73, 54, 35, .05);
      pointer-events: none;
      transform: translateX(-50%);
      transition: top .12s ease, height .12s ease, width .18s ease, opacity .16s ease, background .16s ease, border-color .16s ease;
    }
    .conversation-minimap.is-expanded .minimap-viewport {
      width: 42px;
      border-color: color-mix(in srgb, var(--accent) 34%, transparent);
      background: color-mix(in srgb, var(--accent-soft) 44%, transparent);
    }
    .minimap-marker {
      position: absolute;
      left: 0;
      right: 0;
      width: 100%;
      min-height: 2px;
      padding: 0;
      border: 0;
      border-radius: 999px;
      background: transparent;
      transform: none;
      cursor: pointer;
      opacity: .74;
      overflow: visible;
      transition: width .14s ease, opacity .14s ease, transform .14s ease, background .14s ease;
    }
    .minimap-marker:hover,
    .minimap-marker:focus-visible {
      opacity: 1;
      outline: none;
    }
    .minimap-marker::before,
    .minimap-marker::after {
      content: "";
      position: absolute;
      left: 50%;
      top: 50%;
      border-radius: 999px;
      transform: translate(-50%, -50%);
      transition: width .16s ease, height .16s ease, opacity .16s ease, box-shadow .16s ease, background .16s ease;
    }
    .minimap-marker::before {
      width: 2px;
      height: 100%;
      min-height: 2px;
      background: color-mix(in srgb, var(--muted-2) 54%, transparent);
      opacity: .74;
    }
    .conversation-minimap.is-expanded .minimap-marker::before {
      width: 8px;
      background: color-mix(in srgb, var(--muted-2) 42%, transparent);
      opacity: .68;
    }
    .minimap-marker:hover::before,
    .minimap-marker:focus-visible::before {
      width: 12px;
      opacity: .9;
      background: color-mix(in srgb, var(--muted) 50%, transparent);
    }
    .minimap-marker::after {
      width: 0;
      height: 0;
    }
    .minimap-marker.has-search::after {
      width: 4px;
      height: 4px;
      background: #5b9cf0;
      box-shadow: 0 0 0 1px rgba(91, 156, 240, .18);
    }
    .minimap-marker.has-media::after {
      width: 4px;
      height: 4px;
      background: #a78bfa;
      box-shadow: 0 0 0 1px rgba(167, 139, 250, .18);
    }
    .minimap-marker.has-image::after,
    .minimap-marker.has-attachment::after {
      width: 4px;
      height: 4px;
      background: #42b883;
      box-shadow: 0 0 0 1px rgba(66, 184, 131, .18);
    }
    .minimap-marker.has-favorite::after {
      width: 4px;
      height: 4px;
      background: color-mix(in srgb, var(--accent) 78%, #ffffff);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 20%, transparent);
    }
    .conversation-minimap.is-expanded .minimap-marker.has-search::after,
    .conversation-minimap.is-expanded .minimap-marker.has-media::after,
    .conversation-minimap.is-expanded .minimap-marker.has-image::after,
    .conversation-minimap.is-expanded .minimap-marker.has-attachment::after,
    .conversation-minimap.is-expanded .minimap-marker.has-favorite::after {
      width: 6px;
      height: 6px;
    }
    .minimap-tooltip {
      position: absolute;
      left: calc(100% + 10px);
      top: 0;
      width: 248px;
      max-width: min(248px, calc(100vw - 96px));
      padding: 12px 13px;
      border: 1px solid var(--line);
      border-radius: 16px;
      background: var(--surface);
      color: var(--text);
      box-shadow: 0 16px 42px rgba(73, 54, 35, .16);
      opacity: 0;
      transform: translate(7px, -50%) scale(.985);
      pointer-events: none;
      transition: opacity .16s ease, transform .18s cubic-bezier(.2, .8, .2, 1), top .12s ease;
    }
    .minimap-tooltip.show {
      opacity: 1;
      transform: translate(0, -50%) scale(1);
    }
    .minimap-tooltip strong {
      display: block;
      margin-bottom: 4px;
      font-size: 13px;
      font-weight: 760;
      color: var(--text);
    }
    .minimap-tooltip span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.45;
    }
    .minimap-tooltip p {
      margin: 7px 0 0;
      color: var(--text);
      font-size: 12px;
      line-height: 1.55;
    }
    .conversation-minimap[hidden] {
      display: none !important;
    }
    .messages-inner,
    .bubble {
      width: min(var(--reading), 100%);
    }
    .empty {
      width: min(1040px, 100%);
      gap: 22px;
      text-align: center;
      justify-items: center;
      align-content: center;
    }
    .empty-hero {
      width: min(640px, 100%);
      height: clamp(220px, 22vw, 300px);
      justify-self: center;
      display: block;
      object-fit: cover;
      object-position: center center;
      border-radius: 28px;
      border: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
      box-shadow: 0 18px 48px rgba(138, 109, 90, .11);
      background: var(--surface);
    }
    .empty-copy {
      width: min(720px, 100%);
      text-align: center;
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
      width: 100%;
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
      width: 100%;
      max-width: 100%;
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
	    .table-wrapper {
	      border-radius: 12px;
	      border: 1px solid var(--line);
	      background: var(--surface);
	    }
    .composer {
      position: absolute;
      left: 0;
      right: 0;
      bottom: max(12px, env(safe-area-inset-bottom, 0px));
      z-index: 9;
      padding: 0 clamp(18px, 5vw, 72px);
      pointer-events: none;
      background: transparent;
    }
    .composer-box {
      width: min(var(--composer-width), 100%);
      border-radius: 28px;
      padding: 11px;
      gap: 9px;
      pointer-events: auto;
      border: 1px solid var(--glass-border);
      background: var(--glass-bg);
      -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(160%);
      backdrop-filter: blur(var(--glass-blur)) saturate(160%);
      box-shadow: var(--glass-shadow);
      transition: border-color .18s ease, box-shadow .18s ease, transform .18s ease;
    }
    .composer-box:focus-within {
      border-color: color-mix(in srgb, var(--accent) 58%, var(--line));
      box-shadow: var(--glass-shadow-strong), 0 0 0 4px var(--focus-ring);
    }
    [data-theme="dark"] .composer {
      background: transparent;
    }
    [data-theme="dark"] .composer-box {
      border-color: color-mix(in srgb, var(--line) 58%, rgba(255,255,255,.18));
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,.14),
        inset 0 -1px 0 rgba(255,255,255,.05),
        0 18px 54px rgba(0,0,0,.34);
    }
    @supports not ((backdrop-filter: blur(1px)) or (-webkit-backdrop-filter: blur(1px))) {
      .composer-box {
        background: color-mix(in srgb, var(--surface) 92%, var(--bg));
      }
      #prompt,
      .prompt-chip,
      .composer-action,
	      .model-select,
	      .model-picker,
	      .search-toggle {
	        background: color-mix(in srgb, var(--surface) 86%, transparent);
	      }
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
    .attachment-preview-row,
    .message-images {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    .attachment-preview-row {
      padding: 0 2px;
    }
    .attachment-preview {
      width: 72px;
      height: 72px;
      border: 1px solid color-mix(in srgb, var(--line) 62%, transparent);
      border-radius: 16px;
      overflow: hidden;
      background: var(--surface-soft);
      position: relative;
      box-shadow: var(--soft-shadow);
    }
    .attachment-preview img {
      transition: filter .18s ease, opacity .18s ease;
    }
    .attachment-preview.is-uploading img {
      filter: brightness(.48) saturate(.72);
      opacity: .92;
    }
    .attachment-preview.is-error img {
      filter: brightness(.58) grayscale(.18);
    }
    .attachment-preview img,
    .message-image-btn img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }
	    .attachment-remove {
	      position: absolute;
	      right: 4px;
      top: 4px;
      width: 22px;
      min-width: 22px;
      height: 22px;
      min-height: 22px;
      padding: 0;
      border-radius: 999px;
      background: rgba(43, 37, 35, .72);
      color: #fff;
      border: 0;
	      font-size: 14px;
	      line-height: 1;
	    }
	    .attachment-remove .lucide {
	      width: 13px;
	      height: 13px;
	      stroke-width: 2.6;
	    }
    .attachment-ring {
      --progress: 0;
      position: absolute;
      left: 50%;
      top: 50%;
      width: 42px;
      height: 42px;
      transform: translate(-50%, -50%);
      border-radius: 999px;
      display: grid;
      place-items: center;
      background:
        radial-gradient(circle at center, rgba(43,37,35,.72) 0 48%, transparent 49%),
        conic-gradient(var(--accent) calc(var(--progress) * 1%), rgba(255,255,255,.36) 0);
      color: #fff;
      font-size: 11px;
      font-weight: 800;
      box-shadow: 0 8px 18px rgba(43,37,35,.16);
    }
    .attachment-progress {
      position: absolute;
      left: 0;
      right: 0;
      bottom: 0;
      padding: 3px 4px;
      background: rgba(43, 37, 35, .62);
      color: #fff;
      font-size: 11px;
      text-align: center;
    }
    .message-images {
      margin-bottom: 10px;
    }
    .message-image-btn {
      width: min(180px, 42vw);
      aspect-ratio: 4 / 3;
      min-height: 0;
      padding: 0;
      border: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
      border-radius: 16px;
      overflow: hidden;
      background: var(--surface-soft);
      box-shadow: var(--soft-shadow);
    }
    .image-preview-dialog {
      position: fixed;
      inset: 0;
      z-index: 45;
      display: none;
      place-items: center;
      padding: 18px;
      background: rgba(15, 23, 42, .72);
    }
    .image-preview-dialog.show { display: grid; }
    .image-preview-panel {
      max-width: min(960px, 96vw);
      max-height: min(760px, 90vh);
      display: grid;
      gap: 10px;
    }
    .image-preview-panel img {
      max-width: 100%;
      max-height: calc(90vh - 56px);
      border-radius: 18px;
      object-fit: contain;
      box-shadow: var(--shadow);
      background: var(--surface);
    }
    .input-row {
      grid-template-columns: 42px minmax(0, 1fr) 42px 42px 46px;
      gap: 8px;
      align-items: end;
    }
    #prompt {
      min-height: 62px;
      max-height: min(210px, 38vh);
      padding: 12px 15px;
      font-size: 16px;
      line-height: 1.55;
      border: 1px solid color-mix(in srgb, var(--line) 42%, transparent);
      border-radius: 22px;
      background: rgba(var(--composer-field-rgb), var(--composer-field-opacity));
      -webkit-backdrop-filter: blur(var(--composer-field-blur)) saturate(1.25);
      backdrop-filter: blur(var(--composer-field-blur)) saturate(1.25);
    }
    #prompt:focus {
      border-color: color-mix(in srgb, var(--accent) 32%, transparent);
      background: rgba(var(--composer-field-rgb), var(--composer-field-focus-opacity));
    }
    #send {
      width: 46px;
      min-width: 46px;
      height: 46px;
      min-height: 46px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--accent) 28%, rgba(255,255,255,.44));
      background: linear-gradient(180deg, color-mix(in srgb, var(--accent) 82%, #fff 18%), var(--accent-strong));
      box-shadow:
        inset 0 1px 0 rgba(255,255,255,.44),
        0 14px 30px var(--accent-shadow);
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
	    .model-picker {
	      min-width: 270px;
	      max-width: min(420px, 100%);
	      height: 34px;
	      min-height: 34px;
	      padding: 0 10px 0 12px;
	      display: inline-flex;
	      align-items: center;
	      gap: 8px;
	      border: 1px solid color-mix(in srgb, var(--line) 74%, transparent);
	      border-radius: 999px;
	      background: rgba(var(--composer-control-rgb), var(--composer-control-opacity));
	      color: var(--muted);
	      -webkit-backdrop-filter: blur(var(--composer-field-blur)) saturate(1.2);
	      backdrop-filter: blur(var(--composer-field-blur)) saturate(1.2);
	      box-shadow: inset 0 1px 0 rgba(255,255,255,.42);
	    }
	    .model-picker .lucide {
	      width: 16px;
	      height: 16px;
	      color: var(--accent-strong);
	      stroke-width: 2.2;
	    }
	    .model-picker .model-select {
	      width: 100%;
	      min-width: 0;
	      height: 100%;
	      min-height: 0;
	      padding: 0 24px 0 0;
	      border: 0;
	      background: transparent;
	      box-shadow: none;
	    }
	    .model-select,
	    .search-toggle {
	      height: 34px;
      min-height: 34px;
      border-radius: 999px;
      background: rgba(var(--composer-control-rgb), var(--composer-control-opacity));
      border-color: color-mix(in srgb, var(--line) 74%, transparent);
      color: var(--muted);
      -webkit-backdrop-filter: blur(var(--composer-field-blur)) saturate(1.2);
      backdrop-filter: blur(var(--composer-field-blur)) saturate(1.2);
    }
    .prompt-chip,
    .composer-action {
      background: rgba(var(--composer-control-rgb), var(--composer-control-opacity));
      border-color: color-mix(in srgb, var(--line) 60%, transparent);
      -webkit-backdrop-filter: blur(var(--composer-field-blur)) saturate(1.25);
      backdrop-filter: blur(var(--composer-field-blur)) saturate(1.25);
    }
    .messages,
    .messages .bubble,
    .messages .bubble-shell,
    .messages .message-content,
    .messages .markdown {
      -webkit-user-select: text;
      user-select: text;
    }
    .composer,
    .composer *,
    .scroll-latest,
    .scroll-latest *,
    .model-picker,
    .model-picker *,
    .search-toggle,
    .search-toggle *,
    .prompt-chip,
    .composer-action,
    .interface-popover,
    .interface-popover *,
    .attachment-preview-row,
    .attachment-preview-row *,
    .model-picker-dialog,
    .model-picker-dialog * {
      -webkit-user-select: none;
      user-select: none;
    }
    #prompt,
    #modelPickerSearch {
      -webkit-user-select: text;
      user-select: text;
    }
	    .model-select {
	      min-width: 270px;
	    }
	    .model-picker .model-select {
	      width: 100%;
	      min-width: 0;
	      height: 100%;
	      min-height: 0;
	      padding: 0 24px 0 0;
	      border: 0;
	      background: transparent;
	      box-shadow: none;
	      -webkit-backdrop-filter: none;
	      backdrop-filter: none;
	    }
    .model-picker {
      position: relative;
      padding: 0;
      border: 0;
      background: transparent;
      box-shadow: none;
      -webkit-backdrop-filter: none;
      backdrop-filter: none;
    }
    .model-select.is-native-hidden {
      position: absolute;
      width: 1px;
      height: 1px;
      min-width: 1px;
      min-height: 1px;
      opacity: 0;
      pointer-events: none;
    }
    .model-picker-button {
      width: 100%;
      min-width: 270px;
      max-width: min(420px, 100%);
      height: 34px;
      min-height: 34px;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 0 11px 0 12px;
      border: 1px solid color-mix(in srgb, var(--line) 74%, transparent);
      border-radius: 999px;
      background: rgba(var(--composer-control-rgb), var(--composer-control-opacity));
      color: var(--muted);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.42);
      -webkit-backdrop-filter: blur(var(--composer-field-blur)) saturate(1.2);
      backdrop-filter: blur(var(--composer-field-blur)) saturate(1.2);
      text-align: left;
    }
    .model-picker-button:hover,
    .model-picker-button[aria-expanded="true"] {
      color: var(--text);
      border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
      background: color-mix(in srgb, var(--accent-soft) 58%, rgba(var(--composer-control-rgb), var(--composer-control-opacity)));
    }
    .model-picker-button .model-picker-main {
      min-width: 0;
      display: grid;
      gap: 0;
      flex: 1 1 auto;
    }
    .model-picker-name,
    .model-picker-code {
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .model-picker-name {
      color: var(--text);
      font-size: 13px;
      font-weight: 760;
      line-height: 1.15;
    }
    .model-picker-code {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.15;
    }
    .model-picker-button .chevron {
      flex: 0 0 auto;
      width: 16px;
      height: 16px;
      color: var(--muted);
      transition: transform .16s ease;
    }
    .model-picker-button[aria-expanded="true"] .chevron {
      transform: rotate(180deg);
    }
    .model-picker-dialog {
      position: fixed;
      inset: 0;
      z-index: 34;
      display: none;
      pointer-events: none;
    }
    .model-picker-dialog.show {
      display: block;
      pointer-events: auto;
    }
    .model-picker-popover {
      position: fixed;
      width: min(430px, calc(100vw - 24px));
      max-height: min(70vh, 560px);
      display: grid;
      grid-template-rows: auto minmax(0, 1fr);
      overflow: hidden;
      border: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
      border-radius: 24px;
      background: color-mix(in srgb, var(--surface) 88%, transparent);
      box-shadow: 0 24px 72px rgba(73, 54, 35, .18);
      -webkit-backdrop-filter: blur(22px) saturate(155%);
      backdrop-filter: blur(22px) saturate(155%);
      transform-origin: 16% 100%;
      animation: modelPickerIn .16s cubic-bezier(.2, .8, .2, 1) both;
    }
    .model-picker-search {
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 58px;
      padding: 10px 14px;
      border-bottom: 1px solid color-mix(in srgb, var(--line) 70%, transparent);
    }
    .model-picker-search .lucide {
      width: 17px;
      height: 17px;
      color: var(--muted);
    }
    #modelPickerSearch {
      min-height: 38px;
      padding: 0;
      border: 0;
      border-radius: 0;
      background: transparent;
      box-shadow: none;
      font-size: 15px;
      font-weight: 650;
    }
    #modelPickerSearch:focus {
      box-shadow: none;
    }
    .model-picker-list {
      overflow: auto;
      padding: 8px;
    }
    .model-option {
      width: 100%;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 12px;
      align-items: center;
      min-height: 76px;
      padding: 11px 12px;
      border: 1px solid transparent;
      border-radius: 18px;
      background: transparent;
      color: var(--text);
      text-align: left;
      transition: background .14s ease, border-color .14s ease, transform .14s ease;
    }
    .model-option:hover,
    .model-option.active {
      border-color: color-mix(in srgb, var(--accent) 26%, transparent);
      background: color-mix(in srgb, var(--accent-soft) 44%, var(--surface));
      transform: translateY(-1px);
    }
    .model-option-main {
      min-width: 0;
      display: grid;
      gap: 6px;
    }
    .model-option-title {
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }
    .model-option-title strong {
      min-width: 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 14px;
      font-weight: 780;
    }
    .model-provider {
      flex: 0 0 auto;
      padding: 2px 7px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface-soft) 82%, transparent);
      color: var(--muted);
      font-size: 11px;
      font-weight: 760;
    }
    .model-code-line {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .model-tags {
      display: flex;
      gap: 5px;
      flex-wrap: wrap;
    }
    .model-tag {
      display: inline-flex;
      align-items: center;
      gap: 3px;
      min-height: 20px;
      padding: 0 7px;
      border-radius: 999px;
      background: color-mix(in srgb, var(--surface-soft) 74%, transparent);
      color: var(--muted);
      font-size: 11px;
      font-weight: 720;
    }
    .model-tag .lucide {
      width: 12px;
      height: 12px;
      stroke-width: 2.3;
    }
    .model-check {
      width: 28px;
      height: 28px;
      display: inline-grid;
      place-items: center;
      border-radius: 999px;
      color: var(--accent-strong);
      background: color-mix(in srgb, var(--accent-soft) 74%, transparent);
      opacity: 0;
    }
    .model-option.selected .model-check {
      opacity: 1;
    }
    @keyframes modelPickerIn {
      from { opacity: 0; transform: translateY(7px) scale(.985); }
      to { opacity: 1; transform: translateY(0) scale(1); }
    }
    .status {
      min-height: 18px;
      font-size: 12px;
    }
    .scroll-latest {
      position: absolute;
      left: auto;
      right: 24px;
      bottom: var(--scroll-latest-bottom);
      z-index: 11;
      width: 44px;
      min-width: 44px;
      height: 44px;
      min-height: 44px;
      display: grid;
      place-items: center;
      padding: 0;
      border-radius: 999px;
      border: 1px solid var(--glass-border);
      background: var(--glass-bg);
      color: var(--accent-strong);
      -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(160%);
      backdrop-filter: blur(var(--glass-blur)) saturate(160%);
      box-shadow: var(--glass-shadow);
      font-size: 0;
      opacity: 0;
      pointer-events: none;
      transform: translateY(8px) scale(.94);
      transition:
        opacity .18s ease,
        transform .18s ease,
        box-shadow .18s ease,
        border-color .18s ease,
        background .18s ease;
    }
    .scroll-latest.show {
      opacity: 1;
      pointer-events: auto;
      transform: translateY(0) scale(1);
    }
    .scroll-latest:hover,
    .scroll-latest:focus-visible {
      border-color: color-mix(in srgb, var(--accent) 50%, var(--glass-border));
      box-shadow: var(--glass-shadow-strong), 0 0 0 4px var(--focus-ring);
      transform: translateY(-1px) scale(1.06);
    }
    .scroll-latest .lucide {
      width: 21px;
      height: 21px;
      stroke-width: 2.35;
    }
    .scroll-latest .icon-fallback {
      font-size: 18px;
      line-height: 1;
    }
    .interface-popover {
      position: absolute;
      right: clamp(18px, 5vw, 72px);
      bottom: calc(100% + 12px);
      z-index: 12;
      width: min(390px, calc(100vw - 24px));
      display: none;
      pointer-events: auto;
    }
    .interface-popover.show {
      display: block;
    }
    .interface-panel {
      display: grid;
      overflow: hidden;
      border: 1px solid var(--glass-border);
      border-radius: 24px;
      background: var(--glass-bg);
      -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(160%);
      backdrop-filter: blur(var(--glass-blur)) saturate(160%);
      box-shadow: var(--glass-shadow-strong);
    }
    [data-theme="dark"] .interface-panel {
      box-shadow: var(--glass-shadow-strong);
    }
	    .interface-panel .dialog-head {
	      min-height: 54px;
	      padding: 0 14px 0 16px;
	      background: color-mix(in srgb, var(--surface) 44%, transparent);
	    }
	    .interface-title {
	      display: inline-flex;
	      align-items: center;
	      gap: 8px;
	    }
	    .interface-title .lucide {
	      width: 17px;
	      height: 17px;
	      color: var(--accent-strong);
	      stroke-width: 2.2;
	    }
    .interface-panel .dialog-body {
      display: grid;
      gap: 14px;
      padding: 14px;
      background: transparent;
      overflow: visible;
    }
    .interface-section {
      display: grid;
      gap: 12px;
    }
    .interface-section h2 {
      margin: 0;
      font-size: 13px;
      color: var(--muted);
      font-weight: 760;
    }
    .range-field {
      display: grid;
      gap: 9px;
      margin: 0;
      padding: 12px;
      border: 1px solid color-mix(in srgb, var(--line) 72%, transparent);
      border-radius: 18px;
      background: color-mix(in srgb, var(--surface) 52%, transparent);
      box-shadow: inset 0 1px 0 rgba(255,255,255,.42);
    }
    .range-field-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      color: var(--text);
    }
    .range-field-head strong {
      font-size: 14px;
      font-weight: 720;
    }
    .range-field-head span {
      flex: 0 0 auto;
      color: var(--accent-strong);
      font-size: 13px;
      font-weight: 760;
    }
    .range-field input[type="range"] {
      width: 100%;
      min-height: 30px;
      padding: 0;
      accent-color: var(--accent);
      cursor: pointer;
      box-shadow: none;
    }
    .range-field small,
    .interface-hint {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
    }
    .interface-actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      flex-wrap: wrap;
    }
    .interface-actions button {
      min-height: 38px;
      border-radius: 999px;
    }
    #openInterfaceSettings.active {
      color: var(--accent-strong);
      border-color: color-mix(in srgb, var(--accent) 42%, var(--line));
      background: color-mix(in srgb, var(--accent-soft) 66%, transparent);
    }
    @media (max-width: 900px) {
      .app { grid-template-columns: 1fr; }
      .main {
        --scroll-latest-bottom: calc(max(10px, env(safe-area-inset-bottom, 0px)) + 204px);
      }
      .sidebar {
        width: min(340px, 88vw);
        padding: 14px 12px;
      }
      .sidebar-resizer {
        display: none;
      }
      .messages {
        padding: 22px 14px 232px;
      }
      .composer {
        position: fixed;
        left: 0;
        right: 0;
        z-index: 18;
        padding: 0 12px;
        transform: translateZ(0);
      }
      .interface-popover {
        right: 12px;
      }
      .topbar {
        padding: 0 10px;
      }
      .empty {
        width: min(720px, 100%);
        gap: 18px;
      }
      .empty-hero {
        width: min(560px, 100%);
        height: 220px;
      }
      .prompt-grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }
    @media (max-width: 620px) {
      body { font-size: 15px; }
      .main {
        --scroll-latest-bottom: calc(max(10px, env(safe-area-inset-bottom, 0px)) + 188px);
      }
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
        padding: 18px 12px 210px;
        gap: 22px;
      }
      .empty h2 {
        font-size: 34px;
      }
      .empty-hero {
        height: 190px;
        border-radius: 22px;
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
	      .table-wrapper.is-overflowing {
	        padding-bottom: 30px;
	      }
	      .table-wrapper.is-overflowing::after {
	        content: "";
	        position: absolute;
	        top: 0;
	        right: 0;
	        bottom: 30px;
	        width: 42px;
	        pointer-events: none;
	        background: linear-gradient(90deg, transparent, var(--surface));
	      }
	      .table-wrapper.is-overflowing .table-scroll-hint {
	        display: inline-flex;
	        position: absolute;
	        right: 9px;
	        bottom: 6px;
	        z-index: 1;
	        padding: 3px 8px;
	        border-radius: 999px;
	        border: 1px solid color-mix(in srgb, var(--line) 80%, transparent);
	        background: color-mix(in srgb, var(--surface) 86%, transparent);
	        color: var(--muted);
	        font-size: 11px;
	        line-height: 1.4;
	        box-shadow: 0 6px 16px rgba(73, 54, 35, .08);
	        transition: opacity .18s ease;
	      }
	      .table-wrapper.is-scrolled .table-scroll-hint {
	        opacity: 0;
	      }
	      .composer-box {
	        border-radius: 24px;
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
        align-items: center;
        flex-direction: row;
        gap: 8px;
        padding-top: 6px;
      }
	      .composer-left {
	        width: auto;
	        flex: 1 1 auto;
	        flex-wrap: nowrap;
	      }
	      .model-picker {
	        width: auto;
	        min-width: 0;
	        flex: 1 1 auto;
	      }
	      .model-picker-button {
	        min-width: 0;
	        max-width: none;
	      }
	      .model-select {
	        width: auto;
	        min-width: 0;
        flex: 1 1 auto;
      }
      .search-toggle {
        width: auto;
        flex: 0 0 auto;
        padding: 0 9px;
      }
      .status {
        display: none;
      }
      #prompt {
        min-height: 58px;
      }
      .input-row {
        grid-template-columns: 42px minmax(0, 1fr) 42px 42px 46px;
      }
      #send {
        width: 46px;
        min-width: 46px;
        height: 46px;
        min-height: 46px;
      }
      .scroll-latest {
        right: 16px;
        bottom: var(--scroll-latest-bottom);
        width: 42px;
        min-width: 42px;
        height: 42px;
        min-height: 42px;
      }
      .model-picker-dialog.show {
        display: grid;
        place-items: end center;
        background: rgba(34, 28, 24, .18);
        -webkit-backdrop-filter: blur(8px) saturate(115%);
        backdrop-filter: blur(8px) saturate(115%);
      }
      .changelog-dialog.show,
      .changelog-dialog.full {
        display: grid;
        place-items: end center;
        pointer-events: auto;
        padding: 12px 10px max(10px, env(safe-area-inset-bottom, 0px));
        background: rgba(34, 28, 24, .18);
        -webkit-backdrop-filter: blur(8px) saturate(115%);
        backdrop-filter: blur(8px) saturate(115%);
      }
      .changelog-panel,
      .changelog-dialog.full .changelog-panel {
        position: relative;
        inset: auto !important;
        width: 100%;
        max-height: min(82vh, 720px);
        border-radius: 24px;
        transform-origin: 50% 100%;
      }
      .model-picker-popover {
        inset: auto 0 0 0 !important;
        width: 100%;
        max-height: min(76vh, calc(var(--app-height, 100vh) - 42px));
        border-right: 0;
        border-bottom: 0;
        border-left: 0;
        border-radius: 24px 24px 0 0;
        transform-origin: 50% 100%;
      }
      .model-option {
        min-height: 72px;
      }
      .global-search-dialog {
        place-items: end center;
        padding: 0;
      }
      .global-search-panel {
        width: 100%;
        max-height: min(86vh, calc(var(--app-height, 100vh) - 34px));
        border-radius: 24px 24px 0 0;
        border-right: 0;
        border-bottom: 0;
        border-left: 0;
      }
      .global-search-head {
        min-height: 62px;
        padding: 10px 14px;
      }
      #globalSearchInput {
        font-size: 16px;
      }
      .global-search-item {
        grid-template-columns: 34px minmax(0, 1fr);
        min-height: 72px;
      }
      .global-search-icon {
        width: 34px;
        height: 34px;
        border-radius: 12px;
      }
      .global-search-time {
        grid-column: 2;
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
    .bubble.assistant .sources-panel {
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
	      display: inline-flex;
	      align-items: center;
	      justify-content: center;
	      gap: 6px;
	    }
	    .message-action .lucide,
	    .reasoning-toggle .lucide {
	      width: 14px;
	      height: 14px;
	      stroke-width: 2.2;
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
    .composer-action,
    .prompt-chip {
      box-shadow: inset 0 1px 0 rgba(255,255,255,.42);
    }
    .search-toggle .icon-fallback {
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
      .bubble.assistant .sources-panel {
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
        display: block;
        font-size: 11px;
        max-width: min(72vw, 260px);
        margin: 1px auto 0;
      }
      .conversation-minimap {
        display: none !important;
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
        bottom: max(10px, env(safe-area-inset-bottom, 0px));
        padding: 0 10px;
      }
      .interface-popover {
        left: 10px;
        right: 10px;
        bottom: calc(100% + 10px);
        width: auto;
      }
      .interface-panel {
        border-radius: 22px;
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
	      .profile-dialog,
	      .media-dialog,
	      .theme-dialog,
      .copy-dialog,
      .confirm-dialog {
        place-items: end center;
        padding: 0;
      }
	      .library-panel,
	      .profile-panel,
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
    <form class="login-panel ui-card" id="loginForm">
      <img class="login-mascot" src="/res/meimei-login.png" alt="槑槑猫咪">
      <div class="login-copy">
        <h1>欢迎回家</h1>
	        <p>我是槑槑，陪你把事情慢慢想清楚。</p>
        <button class="app-version version-trigger" type="button" data-version-trigger>v2.8.9</button>
      </div>
	      <label>账号<input id="loginUsername" autocomplete="username" placeholder="默认账号：admin"></label>
	      <label>密码<input id="loginPassword" type="password" autocomplete="current-password" placeholder="请输入账号密码"></label>
      <button class="primary" type="submit" style="width:100%">进入 AI槑槑</button>
      <div class="status err" id="loginStatus"></div>
      <footer class="site-icp">
        <button class="version-trigger" type="button" data-version-trigger>v2.8.9</button>
        <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">赣ICP备2026013740号</a>
      </footer>
    </form>
  </div>

  <div class="app" id="appView" style="display:none">
    <aside class="sidebar" id="sidebar">
      <div class="side-head">
        <div class="brand">
          <img class="brand-avatar" src="/res/meimei-avatar.png" alt="槑槑头像">
          <div class="brand-copy">
            <h1>AI槑槑 <button class="app-version ui-badge version-trigger" type="button" data-version-trigger>v2.8.9</button></h1>
	            <span><span id="health">连接中</span> · <span id="currentUserLabel">未登录</span></span>
          </div>
        </div>
        <button class="icon mobile-only ui-icon-btn" id="closeSide" title="关闭"><i data-lucide="x" aria-hidden="true"></i><span class="icon-fallback">×</span></button>
      </div>
      <button class="global-search-trigger inline-flex items-center" id="openGlobalSearch" type="button">
        <i data-lucide="search" aria-hidden="true"></i>
        <span>搜索历史对话...</span>
        <span class="shortcut" id="globalSearchShortcut">⌘K</span>
      </button>
      <div class="side-actions">
		        <button class="primary side-primary-action inline-flex items-center justify-center gap-2" id="newChat"><i data-lucide="plus" aria-hidden="true"></i><span>新对话</span></button>
        <button class="icon ui-icon-btn" id="refreshConversations" title="刷新"><i data-lucide="rotate-cw" aria-hidden="true"></i><span class="icon-fallback">↻</span></button>
      </div>
      <div class="side-section-title">最近对话</div>
      <div class="conversation-list" id="conversationList"></div>
      <div class="side-foot">
		        <button class="sidebar-action inline-flex items-center justify-center gap-2" id="openPromptLibrary"><i data-lucide="book-open" aria-hidden="true"></i><span>提示词库</span></button>
		        <button class="sidebar-action inline-flex items-center justify-center gap-2" id="openFavorites"><i data-lucide="star" aria-hidden="true"></i><span>我的收藏</span> <span class="nav-count" id="favoriteCount">0</span></button>
		        <button class="sidebar-action inline-flex items-center justify-center gap-2" id="openProfiles"><i data-lucide="user-round-cog" aria-hidden="true"></i><span>AI档案</span></button>
		        <button class="sidebar-action inline-flex items-center justify-center gap-2" id="openMediaAnalysis"><i data-lucide="file-video" aria-hidden="true"></i><span>音视频分析</span></button>
		        <button class="sidebar-action inline-flex items-center justify-center gap-2" id="openSettings"><i data-lucide="settings" aria-hidden="true"></i><span>模型管理</span></button>
		        <button class="sidebar-action inline-flex items-center justify-center gap-2" id="logout"><i data-lucide="log-out" aria-hidden="true"></i><span>退出</span></button>
	        <footer class="site-icp side-icp">
	          <button class="version-trigger" type="button" data-version-trigger>v2.8.9</button>
          <a href="https://beian.miit.gov.cn/" target="_blank" rel="noopener noreferrer">赣ICP备2026013740号</a>
        </footer>
      </div>
      <button class="sidebar-resizer" id="sidebarResizer" type="button" aria-label="调整侧边栏宽度" title="拖动调整侧边栏宽度"></button>
    </aside>

    <main class="main">
      <header class="topbar">
        <button class="icon mobile-only ui-icon-btn" id="openSide" title="对话"><i data-lucide="menu" aria-hidden="true"></i><span class="icon-fallback">☰</span></button>
        <div class="top-title">
          <strong id="chatTitle">新对话</strong>
          <span id="chatModel">请选择模型</span>
          <span class="chat-usage" id="chatUsage"></span>
          <button class="profile-status-chip" id="profileStatus" type="button"><i data-lucide="brain" aria-hidden="true"></i><span>AI档案未加载</span></button>
        </div>
        <div class="top-actions">
          <button class="icon accent-toggle" id="accentToggle" title="主色调">●</button>
          <button class="icon font-toggle" id="fontSizeToggle" title="字体大小：中">中</button>
          <button class="icon" id="themeToggle" title="切换深浅色">◐</button>
          <button class="icon danger ui-icon-btn" id="deleteConversation" title="删除当前对话"><i data-lucide="trash-2" aria-hidden="true"></i><span class="icon-fallback">⌫</span></button>
        </div>
      </header>

      <div class="profile-popover" id="profilePopover" role="dialog" aria-label="本次聊天 AI档案">
        <div class="profile-popover-head">
          <strong>本次 AI档案</strong>
          <div class="library-card-meta" id="profilePopoverMeta">0 条</div>
        </div>
        <div class="profile-popover-list" id="profileLoadedList"></div>
        <label class="profile-popover-foot profile-switch"><input id="disableProfileForConversation" type="checkbox"><span>本次聊天不加载 AI档案</span></label>
      </div>
      <section class="messages" id="messages"></section>
      <nav class="conversation-minimap" id="conversationMinimap" aria-label="对话缩略导航" hidden>
        <div class="minimap-track" id="minimapTrack">
          <div class="minimap-viewport" id="minimapViewport"></div>
        </div>
        <div class="minimap-tooltip" id="minimapTooltip" role="tooltip"></div>
      </nav>
      <button class="scroll-latest" id="scrollLatest" type="button" title="回到底部" aria-label="回到底部">
        <i data-lucide="arrow-down" aria-hidden="true"></i><span class="icon-fallback">↓</span>
      </button>

	      <footer class="composer">
	        <div class="composer-box ui-card">
	          <div class="composer-chip-row" aria-label="常用提示词">
		            <button class="prompt-chip ui-badge inline-flex items-center" type="button" data-prompt-text="帮我润色下面这段文字，让它更自然、更清楚：">润色</button>
		            <button class="prompt-chip ui-badge inline-flex items-center" type="button" data-prompt-text="帮我深度改写下面这段内容，保留原意，但让表达更有条理：">改写</button>
		            <button class="prompt-chip ui-badge inline-flex items-center" type="button" data-prompt-text="帮我扩写下面这段内容，补充细节，让它更完整：">扩写</button>
			            <button class="prompt-chip ui-badge inline-flex items-center" type="button" data-prompt-text="帮我精简下面这段内容，保留重点，表达更利落：">精简</button>
		            <button class="prompt-chip ui-badge inline-flex items-center" id="openPrompts" type="button">更多</button>
	          </div>
	          <div class="attachment-preview-row" id="attachmentPreviewRow" hidden></div>
		          <div class="input-row">
		            <input id="imageInput" type="file" accept="image/jpeg,image/png,image/webp" multiple hidden>
		            <button class="composer-action ui-icon-btn" id="attachImage" type="button" title="上传图片" aria-label="上传图片"><i data-lucide="image-plus" aria-hidden="true"></i><span class="icon-fallback">＋</span></button>
		            <textarea id="prompt" placeholder="和 AI槑槑聊点什么..."></textarea>
		            <button class="composer-action ui-icon-btn" id="insertNewline" type="button" title="换行（Shift+Enter）" aria-label="换行"><i data-lucide="corner-down-left" aria-hidden="true"></i><span class="icon-fallback">↵</span></button>
		            <button class="composer-action ui-icon-btn" id="openInterfaceSettings" type="button" title="界面设置" aria-label="界面设置"><i data-lucide="sliders-horizontal" aria-hidden="true"></i><span class="icon-fallback">⚙</span></button>
		            <button class="primary" id="send" title="发送">发送</button>
		          </div>
	          <div class="composer-tools">
	            <div class="composer-left">
	              <div class="model-picker">
	                <button class="model-picker-button" id="modelPickerButton" type="button" aria-haspopup="listbox" aria-expanded="false">
	                  <i data-lucide="sparkles" aria-hidden="true"></i><span class="icon-fallback">✦</span>
	                  <span class="model-picker-main">
	                    <span class="model-picker-name" id="modelPickerName">选择模型</span>
	                    <span class="model-picker-code" id="modelPickerCode">暂无可用模型</span>
	                  </span>
	                  <i class="chevron" data-lucide="chevron-down" aria-hidden="true"></i>
	                </button>
	                <select class="model-select ui-select is-native-hidden" id="modelSelect" tabindex="-1" aria-hidden="true"></select>
	              </div>
		              <label class="search-toggle inline-flex items-center gap-2" id="webSearchLabel" title="联网搜索">
		                <input id="webSearchToggle" type="checkbox">
		                <i data-lucide="globe-2" aria-hidden="true"></i><span class="icon-fallback">⌁</span>
		                <span>联网搜索</span>
		              </label>
	            </div>
		            <div class="status" id="chatStatus"></div>
		          </div>
		        </div>
			        <div class="interface-popover" id="interfacePopover" role="dialog" aria-modal="false" aria-labelledby="interfacePopoverTitle">
			          <div class="interface-panel ui-modal">
			            <div class="dialog-head">
			              <strong class="interface-title" id="interfacePopoverTitle"><i data-lucide="sliders-horizontal" aria-hidden="true"></i><span>界面设置</span></strong>
			              <button class="icon ui-icon-btn" id="closeInterfaceSettings" type="button" title="关闭"><i data-lucide="x" aria-hidden="true"></i><span class="icon-fallback">×</span></button>
			            </div>
		            <div class="dialog-body">
		              <section class="interface-section">
		                <h2>输入区</h2>
		                <label class="range-field">
		                  <span class="range-field-head">
		                    <strong>输入框透明度</strong>
		                    <span id="composerOpacityValue">80%</span>
		                  </span>
		                  <input id="composerOpacityRange" type="range" min="0" max="100" step="1" value="80">
		                  <small>推荐 20% ~ 90%，越高越不透明。</small>
		                </label>
		                <label class="range-field">
		                  <span class="range-field-head">
		                    <strong>毛玻璃强度</strong>
		                    <span id="composerBlurValue">18px</span>
		                  </span>
		                  <input id="composerBlurRange" type="range" min="0" max="30" step="1" value="18">
		                  <small>实时调整底部输入区的 backdrop-filter blur。</small>
		                </label>
			              </section>
			              <div class="interface-actions">
			                <button class="ui-btn ui-btn-secondary inline-flex items-center gap-2" id="resetInterfaceSettings" type="button"><i data-lucide="rotate-ccw" aria-hidden="true"></i><span>恢复默认设置</span></button>
			                <span class="interface-hint">后续可继续加入深色模式、字体大小、气泡宽度和 AI 回复字号。</span>
		              </div>
		              <div class="status" id="interfaceStatus"></div>
		            </div>
		          </div>
			        </div>
		      </footer>
	  <section class="model-picker-dialog" id="modelPickerDialog">
	    <div class="model-picker-popover" id="modelPickerPopover" role="dialog" aria-label="选择模型">
	      <div class="model-picker-search">
	        <i data-lucide="search" aria-hidden="true"></i>
	        <input id="modelPickerSearch" autocomplete="off" placeholder="搜索模型、供应商或能力...">
	      </div>
	      <div class="model-picker-list" id="modelPickerList" role="listbox"></div>
	    </div>
	  </section>
    </main>
  </div>

	  <div class="drawer-mask" id="drawerMask"></div>
	  <section class="copy-dialog" id="copyDialog">
	    <div class="copy-panel ui-modal">
	      <div class="copy-panel-head">
	        <strong>手动复制</strong>
	        <button class="icon ui-icon-btn" id="closeCopyDialog" title="关闭"><i data-lucide="x" aria-hidden="true"></i><span class="icon-fallback">×</span></button>
	      </div>
	      <textarea id="manualCopyText" readonly></textarea>
	      <div class="copy-panel-actions">
	        <button id="selectManualCopy">全选</button>
	        <button class="primary" id="retryManualCopy">再试一次复制</button>
	      </div>
	    </div>
	  </section>
	  <section class="image-preview-dialog" id="imagePreviewDialog">
	    <div class="image-preview-panel">
	      <button class="icon ui-icon-btn" id="closeImagePreview" type="button" title="关闭" style="justify-self:end;background:rgba(255,255,255,.86)"><i data-lucide="x" aria-hidden="true"></i><span class="icon-fallback">×</span></button>
	      <img id="imagePreviewFull" alt="图片预览">
	    </div>
	  </section>
	  <section class="global-search-dialog" id="globalSearchDialog">
	    <div class="global-search-panel ui-modal" role="dialog" aria-modal="true" aria-label="搜索历史对话">
	      <div class="global-search-head">
	        <i data-lucide="search" aria-hidden="true"></i>
	        <input id="globalSearchInput" autocomplete="off" placeholder="搜索历史对话、消息、收藏、音视频...">
	        <span class="global-search-key">Esc</span>
	      </div>
	      <div class="global-search-list" id="globalSearchResults" role="listbox"></div>
	    </div>
	  </section>
	  <section class="changelog-dialog" id="changelogDialog" aria-label="更新日志">
	    <div class="changelog-panel ui-modal" id="changelogPanel" role="dialog" aria-modal="false" aria-labelledby="changelogTitle">
	      <div class="changelog-head">
	        <strong class="changelog-title" id="changelogTitle"><i data-lucide="history" aria-hidden="true"></i><span id="changelogTitleText">最近更新</span></strong>
	        <button class="icon ui-icon-btn" id="closeChangelog" type="button" title="关闭"><i data-lucide="x" aria-hidden="true"></i><span class="icon-fallback">×</span></button>
	      </div>
	      <div class="changelog-list" id="changelogList"></div>
	      <div class="changelog-foot">
	        <button class="changelog-more ui-btn ui-btn-secondary inline-flex items-center gap-2" id="openFullChangelog" type="button"><i data-lucide="list" aria-hidden="true"></i><span>查看更多更新</span><i data-lucide="chevron-right" aria-hidden="true"></i></button>
	      </div>
	    </div>
	  </section>
	  <section class="confirm-dialog" id="confirmDialog">
	    <div class="confirm-panel ui-modal" role="dialog" aria-modal="true" aria-labelledby="confirmTitle">
	      <div>
	        <h2 id="confirmTitle">确认操作</h2>
	        <p id="confirmMessage">确定要继续吗？</p>
	      </div>
      <div class="confirm-actions">
        <button id="cancelConfirm">取消</button>
        <button id="secondaryConfirm" hidden>新建对话</button>
        <button class="primary" id="confirmOk">确定</button>
      </div>
	    </div>
	  </section>
	  <section class="theme-dialog" id="accentDialog">
	    <div class="accent-panel ui-modal" role="dialog" aria-modal="true" aria-labelledby="accentDialogTitle">
	      <div class="dialog-head">
		        <strong class="dialog-title" id="accentDialogTitle"><i data-lucide="palette" aria-hidden="true"></i><span>主色调</span></strong>
	        <button class="icon ui-icon-btn" id="closeAccentDialog" title="关闭"><i data-lucide="x" aria-hidden="true"></i><span class="icon-fallback">×</span></button>
	      </div>
	      <div class="dialog-body">
	        <div class="accent-grid" id="accentPresetList"></div>
	        <label class="color-field">自定义颜色<input id="customAccentColor" type="color" value="#e58aa6"></label>
	        <div class="library-actions">
		          <button class="primary ui-btn ui-btn-primary inline-flex items-center gap-2" id="applyCustomAccent" type="button"><i data-lucide="check" aria-hidden="true"></i><span>应用</span></button>
		          <button class="ui-btn ui-btn-secondary inline-flex items-center gap-2" id="resetAccent" type="button"><i data-lucide="rotate-ccw" aria-hidden="true"></i><span>恢复粉色</span></button>
	        </div>
	        <div class="status" id="accentStatus"></div>
	      </div>
	    </div>
	  </section>
	  <section class="prompt-dialog" id="promptDialog">
	    <div class="library-panel ui-modal" role="dialog" aria-modal="true" aria-labelledby="promptDialogTitle">
	      <div class="dialog-head">
		        <strong class="dialog-title" id="promptDialogTitle"><i data-lucide="book-open" aria-hidden="true"></i><span>提示词库</span></strong>
	        <button class="icon ui-icon-btn" id="closePromptDialog" title="关闭"><i data-lucide="x" aria-hidden="true"></i><span class="icon-fallback">×</span></button>
	      </div>
	      <div class="dialog-body">
	        <div class="library-grid">
	          <div class="item-list" id="promptLibraryList"></div>
	          <section class="library-editor">
		            <h2 class="library-editor-title"><i data-lucide="pencil" aria-hidden="true"></i><span>新增/编辑提示词</span></h2>
	            <input id="editingPromptId" type="hidden">
	            <label>标题<input id="promptTitle" placeholder="例如：朋友圈文案"></label>
	            <label>内容<textarea id="promptContent" rows="6" placeholder="写下点击后要填入输入框的内容"></textarea></label>
	            <label>排序<input id="promptSortOrder" type="number" value="100"></label>
	            <div class="library-actions">
		              <button class="primary ui-btn ui-btn-primary inline-flex items-center gap-2" id="savePromptTemplate"><i data-lucide="save" aria-hidden="true"></i><span>保存提示词</span></button>
		              <button class="ui-btn ui-btn-secondary inline-flex items-center gap-2" id="resetPromptTemplate"><i data-lucide="eraser" aria-hidden="true"></i><span>清空</span></button>
	            </div>
	            <div class="status" id="promptLibraryStatus"></div>
	          </section>
	        </div>
	      </div>
	    </div>
	  </section>
	  <section class="profile-dialog" id="profileDialog">
	    <div class="profile-panel ui-modal" role="dialog" aria-modal="true" aria-labelledby="profileDialogTitle">
	      <div class="dialog-head">
		        <strong class="dialog-title" id="profileDialogTitle"><i data-lucide="user-round-cog" aria-hidden="true"></i><span>AI档案</span></strong>
	        <button class="icon ui-icon-btn" id="closeProfileDialog" title="关闭"><i data-lucide="x" aria-hidden="true"></i><span class="icon-fallback">×</span></button>
	      </div>
	      <div class="dialog-body">
	        <div class="profile-summary">
	          <span id="profileSummary">当前 Profile：约 0 Token</span>
	          <span id="profileWarning" class="profile-token-warning" hidden>AI档案较长，会增加每次模型调用成本。</span>
	        </div>
	        <div class="profile-layout">
	          <div class="item-list" id="profileList"></div>
	          <section class="library-editor">
		            <h2 class="library-editor-title"><i data-lucide="pencil" aria-hidden="true"></i><span>新增/编辑档案</span></h2>
	            <input id="editingProfileId" type="hidden">
	            <label>标题<input id="profileTitle" placeholder="例如：输出风格"></label>
	            <label>内容<textarea id="profileContent" rows="8" placeholder="写下希望槑槑长期参考的信息"></textarea></label>
	            <div class="grid2">
	              <label>类型<select id="profileType"><option value="profile">profile</option><option value="style">style</option><option value="project">project</option><option value="memory">memory</option></select></label>
	              <label>排序<input id="profileSortOrder" type="number" value="100"></label>
	            </div>
	            <label class="profile-switch"><input id="profileEnabled" type="checkbox" checked><span>启用，聊天时自动加载</span></label>
	            <div class="library-card-meta" id="profileEditorMeta">0 字 · 约 0 Token</div>
	            <div class="library-actions">
		              <button class="primary ui-btn ui-btn-primary inline-flex items-center gap-2" id="saveProfile"><i data-lucide="save" aria-hidden="true"></i><span>保存档案</span></button>
		              <button class="ui-btn ui-btn-secondary inline-flex items-center gap-2" id="resetProfile"><i data-lucide="eraser" aria-hidden="true"></i><span>清空</span></button>
	            </div>
	            <div class="status" id="profileStatusText"></div>
	          </section>
	        </div>
	      </div>
	    </div>
	  </section>
	      <section class="favorite-dialog" id="favoriteDialog">
	    <div class="library-panel ui-modal" role="dialog" aria-modal="true" aria-labelledby="favoriteDialogTitle">
	      <div class="dialog-head">
		        <strong class="dialog-title" id="favoriteDialogTitle"><i data-lucide="star" aria-hidden="true"></i><span>我的收藏</span></strong>
	        <button class="icon ui-icon-btn" id="closeFavoriteDialog" title="关闭"><i data-lucide="x" aria-hidden="true"></i><span class="icon-fallback">×</span></button>
	      </div>
	      <div class="dialog-body">
	        <div class="favorite-layout">
	          <div class="item-list" id="favoriteList"></div>
	          <section class="favorite-detail" id="favoriteDetail"></section>
	        </div>
	      </div>
	    </div>
	  </section>
	  <section class="media-dialog" id="mediaDialog">
	    <div class="library-panel ui-modal" role="dialog" aria-modal="true" aria-labelledby="mediaDialogTitle">
	      <div class="dialog-head">
	        <strong class="media-dialog-title" id="mediaDialogTitle"><i data-lucide="file-video" aria-hidden="true"></i><span>音视频分析</span></strong>
	        <button class="icon ui-icon-btn" id="closeMediaDialog" title="关闭"><i data-lucide="x" aria-hidden="true"></i><span class="icon-fallback">×</span></button>
	      </div>
	      <div class="dialog-body">
	        <section class="media-upload">
	          <div>
		            <strong class="media-upload-title"><i data-lucide="upload" aria-hidden="true"></i><span>上传音频/视频</span></strong>
		            <p class="library-card-meta">支持 mp3、mp4、m4a、wav 等格式，文件会上传到 OSS 后交给通义听悟处理。</p>
	          </div>
	          <div class="media-upload-row">
	            <label>选择文件<input id="mediaFile" type="file" accept=".mp3,.mp4,.m4a,.wav,.aac,.flac,.mov,.avi,.mkv,.webm,audio/*,video/*"></label>
		            <button class="primary ui-btn ui-btn-primary inline-flex items-center gap-2" id="uploadMediaTask" type="button"><i data-lucide="upload" aria-hidden="true"></i><span>开始分析</span></button>
	          </div>
	          <div class="status" id="mediaStatus"></div>
	        </section>
	        <div class="media-layout">
	          <div class="item-list" id="mediaTaskList"></div>
	          <section class="media-detail" id="mediaTaskDetail"></section>
	        </div>
	      </div>
	    </div>
	  </section>
	  <section class="drawer" id="settingsDrawer">
    <div class="drawer-head">
	      <strong class="dialog-title"><i data-lucide="settings" aria-hidden="true"></i><span>模型管理</span></strong>
      <button class="icon ui-icon-btn" id="closeSettings" title="关闭"><i data-lucide="x" aria-hidden="true"></i><span class="icon-fallback">×</span></button>
    </div>
    <div class="drawer-body">
      <section class="panel">
		        <h2 class="panel-title"><i data-lucide="shield" aria-hidden="true"></i><span>管理员</span></h2>
	        <label>管理密钥<input id="adminKey" type="password" autocomplete="off"></label>
        <div class="grid2">
          <label>新的家用登录密码<input id="familyPassword" type="password" autocomplete="new-password" placeholder="至少 8 位"></label>
	          <div style="display:flex;align-items:end"><button class="ui-btn ui-btn-secondary inline-flex items-center gap-2" id="changePassword"><i data-lucide="key-round" aria-hidden="true"></i><span>修改登录密码</span></button></div>
        </div>
	        <div class="status" id="adminStatus"></div>
	      </section>

	      <section class="panel" id="accountAdminPanel">
		        <h2 class="panel-title"><i data-lucide="users" aria-hidden="true"></i><span>账号管理</span></h2>
	        <input id="editingUserId" type="hidden">
	        <div class="grid2">
	          <label>账号<input id="accountUsername" autocomplete="off" placeholder="只能用字母、数字、_、-"></label>
	          <label>显示名<input id="accountDisplayName" placeholder="家人昵称"></label>
	        </div>
	        <div class="grid2">
	          <label>角色<select id="accountRole"><option value="family">家庭成员</option><option value="admin">管理员</option></select></label>
	          <label>状态<select id="accountActive"><option value="1">启用</option><option value="0">禁用</option></select></label>
	        </div>
	        <label>密码<input id="accountPassword" type="password" autocomplete="new-password" placeholder="新增账号必填，编辑时留空保持原密码"></label>
	        <div class="library-actions">
		          <button class="primary ui-btn ui-btn-primary inline-flex items-center gap-2" id="saveAccount"><i data-lucide="save" aria-hidden="true"></i><span>保存账号</span></button>
		          <button class="ui-btn ui-btn-secondary inline-flex items-center gap-2" id="resetAccountForm"><i data-lucide="eraser" aria-hidden="true"></i><span>清空</span></button>
	        </div>
	        <div class="status" id="accountStatus"></div>
	        <div id="accountList"></div>
	      </section>

	      <section class="panel" id="tokenStatsPanel">
		        <h2 class="panel-title"><i data-lucide="bar-chart-3" aria-hidden="true"></i><span>Token统计</span></h2>
	        <div class="token-summary-grid" id="tokenSummaryGrid"></div>
	        <div class="token-filter-row">
	          <label>搜索用户名<input id="tokenStatsQuery" autocomplete="off" placeholder="输入账号或昵称"></label>
	          <label>排序
	            <select id="tokenStatsSort">
	              <option value="tokens">Token最多</option>
	              <option value="recent">最近使用</option>
	              <option value="created">注册时间</option>
	            </select>
	          </label>
	          <div style="display:flex;align-items:end">
		            <button class="ui-btn ui-btn-secondary inline-flex items-center gap-2" id="refreshTokenStats" type="button"><i data-lucide="refresh-cw" aria-hidden="true"></i><span>刷新</span></button>
	          </div>
	        </div>
	        <div class="status" id="tokenStatsStatus"></div>
	        <div id="tokenStatsList"></div>
	      </section>

	      <section class="panel">
		        <h2 class="panel-title"><i data-lucide="search" aria-hidden="true"></i><span>联网搜索</span></h2>
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
		          <button class="primary ui-btn ui-btn-primary inline-flex items-center gap-2" id="saveSearch"><i data-lucide="save" aria-hidden="true"></i><span>保存搜索配置</span></button>
		          <button class="ui-btn ui-btn-secondary inline-flex items-center gap-2" id="clearSearchKey"><i data-lucide="key-round" aria-hidden="true"></i><span>清空搜索 Key</span></button>
	        </div>
	        <div class="status" id="searchStatus"></div>
	      </section>

	      <section class="panel">
	        <h2 class="panel-title"><i data-lucide="bot" aria-hidden="true"></i><span>新增/编辑模型</span></h2>
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
          <label>图片理解<select id="supportsVision"><option value="0">不支持</option><option value="1">支持图片理解</option></select></label>
        </div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
	          <button class="primary ui-btn ui-btn-primary inline-flex items-center gap-2" id="saveModel"><i data-lucide="save" aria-hidden="true"></i><span>保存模型</span></button>
	          <button class="ui-btn ui-btn-secondary inline-flex items-center gap-2" id="resetModelForm"><i data-lucide="eraser" aria-hidden="true"></i><span>清空</span></button>
        </div>
        <div class="status" id="modelStatus"></div>
      </section>

      <section class="panel">
	        <h2 class="panel-title"><i data-lucide="list" aria-hidden="true"></i><span>已配置模型</span></h2>
        <div id="adminModelList"></div>
      </section>
    </div>
  </section>

  <script>
    const $ = (id) => document.getElementById(id);
    const state = {
	      authed: false,
	      user: null,
	      models: [],
	      prompts: [],
	      profiles: [],
	      profileTotals: null,
	      editingProfileId: null,
	      profileDragId: "",
	      profileDisabledByConversation: {},
	      favorites: [],
	      selectedFavoriteId: null,
	      mediaTasks: [],
	      selectedMediaTaskId: null,
	      mediaTab: "summary",
	      mediaUploading: false,
	      mediaPollTimer: null,
	      conversations: [],
	      currentConversation: null,
	      conversationStats: null,
	      messages: [],
	      attachments: [],
	      uploadingImages: false,
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
	      minimapQueued: false,
	      minimapFadeTimer: 0,
	      minimapCollapseTimer: 0,
	      minimapTooltipTimer: 0,
	      chatSelectionActive: false,
	      chatSelectionStartedInMessages: false,
	      globalSearchResults: [],
	      globalSearchQuery: "",
	      globalSearchSelected: 0,
	      globalSearchLoading: false,
	      globalSearchError: "",
	      globalSearchTimer: 0,
	      globalSearchSeq: 0,
	      tokenStats: null,
	      tokenStatsExpandedUserId: "",
	      tokenStatsTimer: 0,
	      changelogEntries: [],
	      changelogVersion: "",
	      changelogHasMore: false,
	      changelogFull: false,
	      changelogAnchor: null,
	      modelPickerFilter: "",
	      modelPickerSelectedIndex: 0,
	      isComposing: false,
	      lastCompositionEndAt: 0,
	      messageSeq: 0,
	      searchConfig: null,
		      adminKey: localStorage.getItem("aiPlatformAdminKey") || "",
		      theme: localStorage.getItem("aiPlatformTheme") || "",
		      accent: localStorage.getItem("aiPlatformAccent") || "pink",
		      fontSize: localStorage.getItem("aiPlatformFontSize") || "medium",
		      composerOpacity: localStorage.getItem("aiPlatformComposerOpacity") || "80",
		      composerBlur: localStorage.getItem("aiPlatformComposerBlur") || "18",
		      sidebarWidth: localStorage.getItem("aiPlatformSidebarWidth") || "322"
	    };
	    let lucideRefreshQueued = false;
	    $("adminKey").value = state.adminKey;

	    function renderLucideIcons() {
	      if (!window.lucide || typeof window.lucide.createIcons !== "function") return;
	      window.lucide.createIcons({
	        attrs: {
	          "stroke-width": 2,
	          "aria-hidden": "true"
	        }
	      });
	      document.documentElement.classList.add("lucide-ready");
	    }

	    function queueLucideRefresh() {
	      if (lucideRefreshQueued) return;
	      lucideRefreshQueued = true;
	      requestAnimationFrame(() => {
	        lucideRefreshQueued = false;
	        renderLucideIcons();
	      });
	    }

	    function iconMarkup(name, fallback = "") {
	      return '<i data-lucide="' + escapeHTML(name) + '" aria-hidden="true"></i>' + (fallback ? '<span class="icon-fallback">' + escapeHTML(fallback) + '</span>' : "");
	    }

	    function iconLabel(name, label, fallback = "") {
	      return iconMarkup(name, fallback) + '<span>' + escapeHTML(label) + '</span>';
	    }

	    function createIconButton(name, label, options = {}) {
	      const button = document.createElement("button");
	      button.type = "button";
	      const tone = options.primary ? "primary ui-btn ui-btn-primary" : "ui-btn ui-btn-secondary";
	      button.className = tone + (options.danger ? " danger" : "") + " inline-flex items-center gap-2";
	      button.innerHTML = iconLabel(name, label, options.fallback || "");
	      return button;
	    }

	    function createIconOnlyButton(name, title, options = {}) {
	      const button = document.createElement("button");
	      button.type = "button";
	      button.className = (options.className || "ui-icon-btn") + (options.danger ? " danger" : "");
	      button.title = title;
	      button.setAttribute("aria-label", title);
	      button.innerHTML = iconMarkup(name, options.fallback || "");
	      return button;
	    }

	    function createEmptyState(icon, title, description = "", options = {}) {
	      const node = document.createElement("div");
	      node.className = "empty-state" + (options.compact ? " compact" : "");
	      node.innerHTML = iconMarkup(icon, options.fallback || "") + '<strong>' + escapeHTML(title) + '</strong>' + (description ? '<p>' + escapeHTML(description) + '</p>' : "");
	      return node;
	    }

	    window.addEventListener("load", renderLucideIcons, { once: true });

	    function userStorageKey(key) {
	      return state.user?.id ? `aiPlatform:${state.user.id}:${key}` : key;
	    }

	    function getUserStorage(key, fallback = null) {
	      const value = localStorage.getItem(userStorageKey(key));
	      return value === null ? fallback : value;
	    }

	    function setUserStorage(key, value) {
	      localStorage.setItem(userStorageKey(key), value);
	    }

	    function applyCurrentUser(user) {
	      state.user = user || null;
	      const label = $("currentUserLabel");
	      if (label) {
	        label.textContent = state.user ? (state.user.display_name || state.user.username) : "未登录";
	      }
	    }

	    function loadUserPreferences() {
	      state.theme = getUserStorage("aiPlatformTheme", localStorage.getItem("aiPlatformTheme") || "");
	      state.accent = getUserStorage("aiPlatformAccent", localStorage.getItem("aiPlatformAccent") || "pink");
	      state.fontSize = getUserStorage("aiPlatformFontSize", localStorage.getItem("aiPlatformFontSize") || "medium");
	      state.composerOpacity = getUserStorage("aiPlatformComposerOpacity", localStorage.getItem("aiPlatformComposerOpacity") || "80");
	      state.composerBlur = getUserStorage("aiPlatformComposerBlur", localStorage.getItem("aiPlatformComposerBlur") || "18");
	      state.sidebarWidth = getUserStorage("aiPlatformSidebarWidth", localStorage.getItem("aiPlatformSidebarWidth") || "322");
	      loadProfileSessionPrefs();
	      applyInterfaceSettings({ save: false });
	      applyFontSize(state.fontSize);
	      applyTheme(preferredTheme());
	      applySidebarWidth(state.sidebarWidth, false);
	    }

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
	      setUserStorage("aiPlatformAccent", accent);
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
	      setUserStorage("aiPlatformTheme", theme);
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
	      setUserStorage("aiPlatformFontSize", size);
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

	    const interfaceDefaults = {
	      composerOpacity: 80,
	      composerBlur: 18
	    };

	    function clampNumber(value, min, max, fallback) {
	      const number = Number(value);
	      if (!Number.isFinite(number)) return fallback;
	      return Math.max(min, Math.min(max, number));
	    }

	    function updateInterfaceControls(opacity, blur) {
	      const opacityRange = $("composerOpacityRange");
	      const blurRange = $("composerBlurRange");
	      const opacityValue = $("composerOpacityValue");
	      const blurValue = $("composerBlurValue");
	      if (opacityRange) opacityRange.value = String(opacity);
	      if (blurRange) blurRange.value = String(blur);
	      if (opacityValue) opacityValue.textContent = opacity + "%";
	      if (blurValue) blurValue.textContent = blur + "px";
	    }

	    function applyInterfaceSettings(options = {}) {
	      const opacity = Math.round(clampNumber(
	        options.opacity ?? state.composerOpacity,
	        0,
	        100,
	        interfaceDefaults.composerOpacity
	      ));
	      const blur = Math.round(clampNumber(
	        options.blur ?? state.composerBlur,
	        0,
	        30,
	        interfaceDefaults.composerBlur
	      ));
	      state.composerOpacity = String(opacity);
	      state.composerBlur = String(blur);
	      const ratio = opacity / 100;
	      const root = document.documentElement;
	      root.style.setProperty("--composer-glass-opacity", ratio.toFixed(2));
	      root.style.setProperty("--composer-field-opacity", (ratio * .48).toFixed(2));
	      root.style.setProperty("--composer-field-focus-opacity", Math.min(1, ratio * .48 + .08).toFixed(2));
	      root.style.setProperty("--composer-control-opacity", (ratio * .55).toFixed(2));
	      root.style.setProperty("--composer-glass-blur", blur + "px");
	      root.style.setProperty("--composer-field-blur", Math.round(blur * .67) + "px");
	      if (options.save !== false) {
		        setUserStorage("aiPlatformComposerOpacity", String(opacity));
		        setUserStorage("aiPlatformComposerBlur", String(blur));
	      }
	      updateInterfaceControls(opacity, blur);
	    }

	    function openInterfaceSettings() {
	      $("interfacePopover").classList.add("show");
	      $("openInterfaceSettings").classList.add("active");
	      setStatus("interfaceStatus", "");
	      updateInterfaceControls(Number(state.composerOpacity), Number(state.composerBlur));
	    }

	    function closeInterfaceSettings() {
	      $("interfacePopover").classList.remove("show");
	      $("openInterfaceSettings").classList.remove("active");
	    }

	    function toggleInterfaceSettings(event) {
	      event?.stopPropagation();
	      if ($("interfacePopover").classList.contains("show")) closeInterfaceSettings();
	      else openInterfaceSettings();
	    }

	    function resetInterfaceSettings() {
	      applyInterfaceSettings({
	        opacity: interfaceDefaults.composerOpacity,
	        blur: interfaceDefaults.composerBlur
	      });
	      setStatus("interfaceStatus", "已恢复默认设置", "ok");
	    }

	    function handleInterfaceOutsideClick(event) {
	      const popover = $("interfacePopover");
	      if (!popover.classList.contains("show")) return;
	      if (popover.contains(event.target) || $("openInterfaceSettings").contains(event.target)) return;
	      closeInterfaceSettings();
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

	    applyInterfaceSettings({ save: false });
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
	      if (/username and password/i.test(text)) return "请输入账号和密码。";
	      if (/username already exists/i.test(text)) return "这个账号已经存在了。";
	      if (/username invalid/i.test(text)) return "账号只能使用 2-32 位字母、数字、下划线或短横线。";
	      if (/at least one active admin/i.test(text)) return "至少要保留一个可用的管理员账号。";
      if (/model not found|先选择模型|暂无可用模型/i.test(text)) return "还没有可用模型，请先在模型管理里配置。";
      if (/title and content are required/i.test(text)) return "标题和内容都要填写。";
      if (/content too long/i.test(text)) return "内容太长了，稍微精简一下再保存。";
	      if (/only assistant messages can be favorited/i.test(text)) return "只能收藏 AI 的回答。";
	      if (/音视频 OSS|OSS 还没有配置/i.test(text)) return "音视频上传存储还没配置好。";
	      if (/通义听悟还没有配置/i.test(text)) return "通义听悟还没配置好。";
	      if (/文件大小超出限制/i.test(text)) return "文件太大了，换个小一点的文件试试。";
	      if (/暂不支持这个文件格式/i.test(text)) return "这个格式暂时不支持，换 mp3、mp4、m4a 或 wav 试试。";
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
	        applyCurrentUser(null);
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

	    function hasAdminAccess() {
	      return state.user?.role === "admin" || Boolean($("adminKey").value.trim());
	    }

	    function showLogin() {
	      $("loginView").style.display = "grid";
	      $("appView").style.display = "none";
	      $("loginUsername").focus();
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
	      const open = ["promptDialog", "profileDialog", "favoriteDialog", "mediaDialog", "accentDialog", "copyDialog", "globalSearchDialog", "modelPickerDialog", "changelogDialog", "confirmDialog"].some((id) => {
        const el = $(id);
        return el && el.classList.contains("show");
      });
      document.body.classList.toggle("dialog-open", open);
    }

	    function isSmallScreen() {
	      return window.matchMedia && window.matchMedia("(max-width: 620px)").matches;
	    }

	    const sidebarWidthDefaults = {
	      min: 286,
	      value: 322
	    };

	    function isSidebarResizableViewport() {
	      return window.matchMedia && window.matchMedia("(min-width: 901px)").matches;
	    }

	    function maxSidebarWidth() {
	      return Math.max(sidebarWidthDefaults.min, Math.floor(window.innerWidth * .5));
	    }

	    function normalizeSidebarWidth(value) {
	      return Math.round(clampNumber(value, sidebarWidthDefaults.min, maxSidebarWidth(), sidebarWidthDefaults.value));
	    }

	    function applySidebarWidth(value = state.sidebarWidth, save = true) {
	      if (!isSidebarResizableViewport()) return;
	      const width = normalizeSidebarWidth(value);
	      state.sidebarWidth = String(width);
	      document.documentElement.style.setProperty("--sidebar-width", width + "px");
		      if (save) setUserStorage("aiPlatformSidebarWidth", String(width));
	    }

	    function startSidebarResize(event) {
	      if (!isSidebarResizableViewport() || event.button !== 0) return;
	      if (document.body.classList.contains("sidebar-resizing")) return;
	      event.preventDefault();
	      closeInterfaceSettings();
	      document.body.classList.add("sidebar-resizing");
	      const appLeft = $("appView").getBoundingClientRect().left;
	      const moveEvent = event.type === "mousedown" ? "mousemove" : "pointermove";
	      const upEvent = event.type === "mousedown" ? "mouseup" : "pointerup";
	      const cancelEvent = event.type === "mousedown" ? "mouseleave" : "pointercancel";
	      function widthFromEvent(pointerEvent) {
	        return pointerEvent.clientX - appLeft;
	      }
	      function onMove(pointerEvent) {
	        applySidebarWidth(widthFromEvent(pointerEvent), false);
	      }
	      function onUp(pointerEvent) {
	        applySidebarWidth(widthFromEvent(pointerEvent), true);
	        document.body.classList.remove("sidebar-resizing");
	        document.removeEventListener(moveEvent, onMove);
	        document.removeEventListener(upEvent, onUp);
	        document.removeEventListener(cancelEvent, onUp);
	      }
	      document.addEventListener(moveEvent, onMove);
	      document.addEventListener(upEvent, onUp);
	      document.addEventListener(cancelEvent, onUp);
	      onMove(event);
	    }

	    applySidebarWidth(state.sidebarWidth, false);

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
	        applyCurrentUser(data.user || null);
	        loadUserPreferences();
		        state.authed = true;
		        showApp();
		        await Promise.all([loadModels(), loadSearchConfig(), loadPrompts(), loadProfiles(), loadFavorites(), loadConversations(), health()]);
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
	      const username = $("loginUsername").value.trim();
	      const password = $("loginPassword").value;
	      let res;
	      try {
	        res = await request("/api/login", { method: "POST", body: JSON.stringify({ username, password }) });
      } catch (err) {
        setStatus("loginStatus", friendlyError(err, "现在连不上服务，稍后再试一下。"), "err");
        return;
      }
	      if (!res.ok) {
		setStatus("loginStatus", await readError(res, "密码不对，再检查一下。"), "err");
		return;
	      }
	      const data = await res.json();
		      $("loginPassword").value = "";
		      applyCurrentUser(data.user || null);
		      loadUserPreferences();
		      state.authed = true;
	      showApp();
	      await Promise.all([loadModels(), loadSearchConfig(), loadPrompts(), loadProfiles(), loadFavorites(), loadConversations(), health()]);
	    }

    async function logout() {
      await request("/api/logout", { method: "POST" });
	      state.authed = false;
	      applyCurrentUser(null);
	      state.currentConversation = null;
	      state.conversationStats = null;
	      state.profiles = [];
	      state.profileTotals = null;
	      state.profileDisabledByConversation = {};
      state.messages = [];
      clearAttachments();
	      closeProfilePopover();
	      closeProfiles();
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
		        const saved = getUserStorage("aiPlatformWebSearch", localStorage.getItem("aiPlatformWebSearch"));
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
        syncModelPickerButton();
        renderModelPickerList();
        return;
      }
      for (const model of state.models) {
        const opt = document.createElement("option");
        opt.value = model.id;
        opt.textContent = model.name + (model.supports_vision ? " · 可看图" : "") + " · " + model.model;
        select.appendChild(opt);
      }
      if (state.currentConversation) {
        select.value = state.currentConversation.model_id;
      }
      updateVisionUI();
      syncModelPickerButton();
      renderModelPickerList();
    }

    function selectedModel() {
      const id = $("modelSelect")?.value || state.currentConversation?.model_id || "";
      return state.models.find((model) => model.id === id) || null;
    }

    function modelProviderLabel(model) {
      const raw = String(model?.provider || model?.name || model?.model || "").trim();
      if (/小米|mimo|MiMo/i.test(raw)) return "小米";
      if (/qwen|通义|aliyun|阿里/i.test(raw)) return "Qwen";
      if (/deepseek|深度求索/i.test(raw)) return "DeepSeek";
      if (/kimi|moonshot|月之暗面/i.test(raw)) return "Kimi";
      if (/openai|gpt/i.test(raw)) return "OpenAI";
      if (/claude|anthropic/i.test(raw)) return "Claude";
      return raw || "模型";
    }

    function modelCapabilityTags(model) {
      const text = [model?.name, model?.provider, model?.model].join(" ").toLowerCase();
      const tags = [];
      if (model?.supports_vision) tags.push({ icon: "image", label: "可看图" });
      if (/reason|thinking|r1|推理|思考|qwq/.test(text)) tags.push({ icon: "brain", label: "推理" });
      if (/flash|turbo|lite|mini|fast|快速|speed/.test(text)) tags.push({ icon: "zap", label: "快速" });
      if (/max|pro|主力|旗舰|plus/.test(text)) tags.push({ icon: "sparkles", label: "主力" });
      return tags.slice(0, 4);
    }

    function modelSearchText(model) {
      return [model?.name, model?.model, model?.provider, modelProviderLabel(model), ...modelCapabilityTags(model).map((tag) => tag.label)]
        .join(" ")
        .toLowerCase();
    }

    function filteredModels() {
      const query = String(state.modelPickerFilter || "").trim().toLowerCase();
      if (!query) return state.models.slice();
      return state.models.filter((model) => modelSearchText(model).includes(query));
    }

    function syncModelPickerButton() {
      const button = $("modelPickerButton");
      const name = $("modelPickerName");
      const code = $("modelPickerCode");
      if (!button || !name || !code) return;
      const model = selectedModel();
      button.disabled = !state.models.length;
      name.textContent = model ? model.name : "选择模型";
      code.textContent = model ? model.model : (state.models.length ? "请选择一个模型" : "暂无可用模型");
      button.title = model ? `${model.name} · ${modelProviderLabel(model)} · ${model.model}` : "选择模型";
    }

    function positionModelPickerPopover() {
      const popover = $("modelPickerPopover");
      const button = $("modelPickerButton");
      if (!popover || !button || isSmallScreen()) return;
      const rect = button.getBoundingClientRect();
      const width = Math.min(430, window.innerWidth - 24);
      const left = clampNumber(rect.left, 12, Math.max(12, window.innerWidth - width - 12), 12);
      const maxTop = Math.max(12, window.innerHeight - Math.min(560, window.innerHeight * .7) - 12);
      const preferredTop = rect.top - 10 - Math.min(560, window.innerHeight * .7);
      const belowTop = rect.bottom + 10;
      popover.style.width = width + "px";
      popover.style.left = left + "px";
      popover.style.top = (preferredTop > 12 ? preferredTop : Math.min(belowTop, maxTop)) + "px";
      popover.style.bottom = "auto";
    }

    function openModelPicker() {
      if (!state.models.length) return;
      closeInterfaceSettings();
      const dialog = $("modelPickerDialog");
      const button = $("modelPickerButton");
      const search = $("modelPickerSearch");
      if (!dialog || !button || !search) return;
      state.modelPickerFilter = "";
      search.value = "";
      const currentId = $("modelSelect").value;
      const list = filteredModels();
      state.modelPickerSelectedIndex = Math.max(0, list.findIndex((model) => model.id === currentId));
      dialog.classList.add("show");
      button.setAttribute("aria-expanded", "true");
      positionModelPickerPopover();
      renderModelPickerList();
      setDialogOpenState();
      if (!isSmallScreen()) {
        setTimeout(() => search.focus(), 40);
      }
    }

    function closeModelPicker() {
      const dialog = $("modelPickerDialog");
      const button = $("modelPickerButton");
      if (dialog) dialog.classList.remove("show");
      if (button) button.setAttribute("aria-expanded", "false");
      setDialogOpenState();
    }

    function renderModelPickerList() {
      const box = $("modelPickerList");
      if (!box) return;
      const models = filteredModels();
      box.replaceChildren();
      if (!models.length) {
        box.appendChild(createEmptyState("search", "没有找到模型", "换个关键词试试看。", { compact: true }));
        queueLucideRefresh();
        return;
      }
      state.modelPickerSelectedIndex = clampNumber(state.modelPickerSelectedIndex, 0, models.length - 1, 0);
      const currentId = $("modelSelect")?.value || "";
      for (const [index, model] of models.entries()) {
        const selected = model.id === currentId;
        const button = document.createElement("button");
        button.type = "button";
        button.className = "model-option" + (selected ? " selected" : "") + (index === state.modelPickerSelectedIndex ? " active" : "");
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", selected ? "true" : "false");
        const tags = modelCapabilityTags(model);
        button.innerHTML =
          '<span class="model-option-main">' +
            '<span class="model-option-title"><strong>' + escapeHTML(model.name) + '</strong><span class="model-provider">' + escapeHTML(modelProviderLabel(model)) + '</span></span>' +
            '<span class="model-code-line">' + escapeHTML(model.model) + '</span>' +
            '<span class="model-tags">' + tags.map((tag) => '<span class="model-tag">' + iconMarkup(tag.icon) + '<span>' + escapeHTML(tag.label) + '</span></span>').join("") + '</span>' +
          '</span>' +
          '<span class="model-check">' + iconMarkup("check", "✓") + '</span>';
        button.addEventListener("mouseenter", () => setModelPickerSelectedIndex(index));
        button.addEventListener("click", () => chooseModel(model.id));
        box.appendChild(button);
      }
      queueLucideRefresh();
      scrollActiveModelOptionIntoView();
    }

    function scrollActiveModelOptionIntoView() {
      const active = $("modelPickerList")?.querySelector(".model-option.active");
      if (active) active.scrollIntoView({ block: "nearest" });
    }

    function setModelPickerSelectedIndex(index) {
      const models = filteredModels();
      if (!models.length) return;
      state.modelPickerSelectedIndex = clampNumber(index, 0, models.length - 1, 0);
      const items = $("modelPickerList")?.querySelectorAll(".model-option") || [];
      items.forEach((node, itemIndex) => node.classList.toggle("active", itemIndex === state.modelPickerSelectedIndex));
      scrollActiveModelOptionIntoView();
    }

    function moveModelPickerSelection(delta) {
      const models = filteredModels();
      if (!models.length) return;
      setModelPickerSelectedIndex((state.modelPickerSelectedIndex + delta + models.length) % models.length);
    }

    async function updateCurrentConversationModel(modelId) {
      if (!state.currentConversation) return false;
      const model = state.models.find((item) => item.id === modelId);
      if (!model) return false;
      const res = await api(`/api/conversations/${state.currentConversation.id}`, {
        method: "PATCH",
        body: JSON.stringify({ model_id: modelId })
      });
      if (!res.ok) {
        setStatus("chatStatus", await readError(res, "切换模型失败，稍后再试一下。"), "err");
        return false;
      }
      const data = await res.json();
      state.currentConversation = data.conversation || {
        ...state.currentConversation,
        model_id: model.id,
        model_name: model.name,
        model: model.model,
        supports_vision: Boolean(model.supports_vision)
      };
      upsertConversation(state.currentConversation);
      $("modelSelect").value = state.currentConversation.model_id;
      updateChatHeader();
      await loadConversationStats(state.currentConversation.id);
      updateVisionUI();
      return true;
    }

    function hasCurrentConversationHistory() {
      return state.messages.some((message) => message && message.role !== "system" && (message.content || message.id || message.images?.length));
    }

    async function chooseModel(modelId) {
      const select = $("modelSelect");
      const model = state.models.find((item) => item.id === modelId);
      if (!select || !model) return;
      closeModelPicker();
      if (state.sending) {
        setStatus("chatStatus", "槑槑还在回复，等这条生成完再切换模型。", "err");
        return;
      }
      const previousId = select.value || state.currentConversation?.model_id || "";
      if (previousId === modelId) {
        syncModelPickerButton();
        $("prompt").focus();
        return;
      }
      if (state.currentConversation) {
        if (hasCurrentConversationHistory()) {
          const action = await confirmAction({
            title: "切换这个对话的模型？",
            message: "当前对话已有历史内容。可以让 " + model.name + " 读取这段上下文继续聊，也可以新建一个空对话使用它。",
            confirmText: "当前对话继续",
            secondaryText: "新建对话",
            cancelText: "取消"
          });
          if (action === true) {
            if (await updateCurrentConversationModel(modelId)) {
              setStatus("chatStatus", "已切换到 " + model.name + "，会带着当前上下文继续。", "ok");
            }
          } else if (action === "secondary") {
            await newConversation(modelId);
            setStatus("chatStatus", "已新建对话，准备使用 " + model.name + "。", "ok");
          } else {
            select.value = previousId;
            syncModelPickerButton();
            renderModelPickerList();
          }
        } else {
          if (await updateCurrentConversationModel(modelId)) {
            setStatus("chatStatus", "已切换到 " + model.name + "。", "ok");
          }
        }
        if (state.attachments.length && !selectedModelSupportsVision()) {
          setStatus("chatStatus", "当前模型不支持图片理解，请切换支持图片的模型。", "err");
        }
        $("prompt").focus();
        return;
      }
      select.value = modelId;
      select.dispatchEvent(new Event("change", { bubbles: true }));
      if (!state.currentConversation) {
        $("chatModel").textContent = "准备使用 " + model.name;
      }
      setStatus("chatStatus", "已选择 " + model.name + "，新对话会使用它。", "ok");
      $("prompt").focus();
    }

    function handleModelPickerSearchInput() {
      state.modelPickerFilter = $("modelPickerSearch").value.trim();
      const models = filteredModels();
      const currentId = $("modelSelect").value;
      const currentIndex = models.findIndex((model) => model.id === currentId);
      state.modelPickerSelectedIndex = currentIndex >= 0 ? currentIndex : 0;
      renderModelPickerList();
    }

    function handleModelPickerKeydown(event) {
      if (event.key === "Escape") {
        event.preventDefault();
        closeModelPicker();
        return;
      }
      if (event.key === "ArrowDown") {
        event.preventDefault();
        moveModelPickerSelection(1);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        moveModelPickerSelection(-1);
        return;
      }
      if (event.key === "Enter") {
        event.preventDefault();
        const model = filteredModels()[state.modelPickerSelectedIndex];
        if (model) chooseModel(model.id);
      }
    }

    function selectedModelSupportsVision() {
      return Boolean(selectedModel()?.supports_vision);
    }

    function updateVisionUI() {
      const button = $("attachImage");
      if (!button) return;
      const model = selectedModel();
      const supported = Boolean(model?.supports_vision);
      button.disabled = !supported || state.uploadingImages || state.sending;
      button.title = supported ? "上传图片" : "当前模型不支持图片理解，请切换支持图片的模型。";
      button.setAttribute("aria-label", button.title);
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
	        box.appendChild(createEmptyState("book-open", "还没有提示词", "右侧可以新增一个常用模板。", { compact: true }));
	        queueLucideRefresh();
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
		        const use = createIconButton("corner-down-left", "填入输入框", { primary: true, fallback: "↵" });
		        use.addEventListener("click", () => {
		          insertPromptText(item.content);
		          closePromptLibrary();
		        });
		        const edit = createIconButton("pencil", "编辑", { fallback: "✎" });
		        edit.addEventListener("click", () => fillPromptForm(item));
		        const del = createIconButton("trash-2", "删除", { danger: true, fallback: "删" });
		        del.addEventListener("click", () => deletePromptTemplate(item.id, item.title));
		        actions.append(use, edit, del);
		        card.append(title, content, meta, actions);
		        box.appendChild(card);
		      }
		      queueLucideRefresh();
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

	    function estimateClientTokens(text) {
	      const value = String(text || "");
	      let cjk = 0;
	      for (const char of value) {
	        if (char >= "\u4e00" && char <= "\u9fff") cjk++;
	      }
	      const other = Math.max(0, value.length - cjk);
	      return Math.max(0, Math.round(cjk * .8 + other / 4));
	    }

	    function enabledProfiles() {
	      return state.profiles.filter((item) => item.enabled && String(item.content || "").trim());
	    }

	    function profileTextStats(title, content) {
	      const text = [title, content].filter(Boolean).join("\n");
	      return {
	        chars: text.length,
	        tokens: estimateClientTokens(text)
	      };
	    }

	    function currentProfileTotals() {
	      const profiles = enabledProfiles();
	      const text = profiles.map((item) => [item.title, item.content].join("\n")).join("\n");
	      return {
	        enabled_count: profiles.length,
	        total_count: state.profiles.length,
	        char_count: text.length,
	        token_estimate: estimateClientTokens(text)
	      };
	    }

	    function loadProfileSessionPrefs() {
	      try {
	        state.profileDisabledByConversation = JSON.parse(getUserStorage("aiPlatformProfileDisabledByConversation", "{}") || "{}") || {};
	      } catch {
	        state.profileDisabledByConversation = {};
	      }
	    }

	    function saveProfileSessionPrefs() {
	      setUserStorage("aiPlatformProfileDisabledByConversation", JSON.stringify(state.profileDisabledByConversation || {}));
	    }

	    function profileDisabledForConversation(id = state.currentConversation?.id) {
	      return Boolean(id && state.profileDisabledByConversation?.[id]);
	    }

	    function setProfileDisabledForCurrentConversation(disabled) {
	      const id = state.currentConversation?.id;
	      if (!id) {
	        const checkbox = $("disableProfileForConversation");
	        if (checkbox) checkbox.checked = false;
	        setStatus("chatStatus", "先进入一个对话，再设置本次是否加载 AI档案。", "err");
	        return;
	      }
	      if (disabled) state.profileDisabledByConversation[id] = true;
	      else delete state.profileDisabledByConversation[id];
	      saveProfileSessionPrefs();
	      renderProfileStatus();
	      renderProfilePopover();
	    }

	    function updateProfileEditorMeta() {
	      const meta = $("profileEditorMeta");
	      if (!meta) return;
	      const stats = profileTextStats($("profileTitle").value.trim(), $("profileContent").value.trim());
	      meta.textContent = stats.chars + " 字 · 约 " + stats.tokens + " Token";
	    }

	    function updateProfileSummary() {
	      const totals = state.profileTotals || currentProfileTotals();
	      const summary = $("profileSummary");
	      const warning = $("profileWarning");
	      if (summary) {
	        summary.textContent = "当前 Profile：已启用 " + Number(totals.enabled_count || 0) + " 条 · 约 " + Number(totals.token_estimate || 0) + " Token";
	      }
	      if (warning) warning.hidden = Number(totals.token_estimate || 0) <= 1000;
	    }

	    function renderProfileStatus() {
	      const button = $("profileStatus");
	      if (!button) return;
	      const label = button.querySelector("span") || button;
	      const enabledCount = enabledProfiles().length;
	      const disabled = profileDisabledForConversation();
	      button.classList.toggle("disabled", disabled || !enabledCount);
	      if (disabled) {
	        label.textContent = "本次未加载 AI档案";
	        button.title = "当前会话已关闭 AI档案加载";
	      } else if (enabledCount) {
	        label.textContent = "本次已加载 AI档案（" + enabledCount + "条）";
	        button.title = "聊天时会自动参考已启用的 AI档案";
	      } else {
	        label.textContent = "AI档案未设置";
	        button.title = "点击管理长期档案";
	      }
	      queueLucideRefresh();
	    }

	    function renderProfilePopover() {
	      const list = $("profileLoadedList");
	      if (!list) return;
	      const profiles = enabledProfiles();
	      const disabled = profileDisabledForConversation();
	      const checkbox = $("disableProfileForConversation");
	      const meta = $("profilePopoverMeta");
	      list.innerHTML = "";
	      if (checkbox) {
	        checkbox.checked = disabled;
	        checkbox.disabled = !state.currentConversation;
	      }
	      if (meta) {
	        meta.textContent = profiles.length ? (profiles.length + " 条 · 约 " + currentProfileTotals().token_estimate + " Token") : "0 条";
	      }
	      if (!profiles.length) {
	        list.appendChild(createEmptyState("brain", "还没有启用的 AI档案", "可以在左侧菜单的“AI档案”里添加。", { compact: true }));
	      } else {
	        for (const item of profiles) {
	          const row = document.createElement("label");
	          row.className = "profile-switch";
	          const input = document.createElement("input");
	          input.type = "checkbox";
	          input.checked = !disabled;
	          input.disabled = true;
	          const text = document.createElement("span");
	          text.textContent = item.title;
	          row.title = item.content || item.title;
	          row.append(input, text);
	          list.appendChild(row);
	        }
	      }
	      queueLucideRefresh();
	    }

	    function openProfilePopover(event) {
	      event?.stopPropagation();
	      const popover = $("profilePopover");
	      if (!popover) return;
	      renderProfilePopover();
	      popover.classList.add("show");
	      setDialogOpenState();
	    }

	    function closeProfilePopover() {
	      const popover = $("profilePopover");
	      if (!popover) return;
	      popover.classList.remove("show");
	      setDialogOpenState();
	    }

	    function toggleProfilePopover(event) {
	      const popover = $("profilePopover");
	      if (popover?.classList.contains("show")) closeProfilePopover();
	      else openProfilePopover(event);
	    }

	    function handleProfileOutsideClick(event) {
	      const popover = $("profilePopover");
	      if (!popover || !popover.classList.contains("show")) return;
	      if (popover.contains(event.target) || $("profileStatus")?.contains(event.target)) return;
	      closeProfilePopover();
	    }

	    function applyProfilesPayload(data) {
	      state.profiles = data.profiles || [];
	      state.profileTotals = data.totals || currentProfileTotals();
	      renderProfileList();
	      updateProfileSummary();
	      renderProfileStatus();
	      renderProfilePopover();
	    }

	    async function loadProfiles() {
	      try {
	        const res = await api("/api/profiles");
	        const data = await res.json();
	        applyProfilesPayload(data);
	      } catch (err) {
	        state.profiles = [];
	        state.profileTotals = null;
	        renderProfileList(friendlyError(err, "AI档案暂时加载失败。"));
	        renderProfileStatus();
	      }
	    }

	    async function openProfiles() {
	      $("profileDialog").classList.add("show");
	      setDialogOpenState();
	      resetProfileForm(false);
	      await loadProfiles();
	    }

	    function closeProfiles() {
	      $("profileDialog").classList.remove("show");
	      setDialogOpenState();
	    }

	    function renderProfileList(errorText = "") {
	      const box = $("profileList");
	      if (!box) return;
	      box.innerHTML = "";
	      if (errorText) {
	        box.appendChild(createEmptyState("alert-circle", "AI档案加载失败", errorText, { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      if (!state.profiles.length) {
	        box.appendChild(createEmptyState("user-round-cog", "还没有 AI档案", "先添加职业、输出风格或常用平台，让槑槑更懂你。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      for (const item of state.profiles) {
	        const card = document.createElement("article");
	        card.className = "library-card profile-card" + (item.enabled ? "" : " disabled");
	        card.draggable = true;
	        card.dataset.id = item.id;
	        card.addEventListener("dragstart", (event) => {
	          state.profileDragId = item.id;
	          card.classList.add("dragging");
	          event.dataTransfer.effectAllowed = "move";
	          event.dataTransfer.setData("text/plain", item.id);
	        });
	        card.addEventListener("dragend", () => {
	          state.profileDragId = "";
	          card.classList.remove("dragging");
	        });
	        card.addEventListener("dragover", (event) => {
	          event.preventDefault();
	          event.dataTransfer.dropEffect = "move";
	        });
	        card.addEventListener("drop", (event) => {
	          event.preventDefault();
	          moveProfileBefore(item.id);
	        });

	        const head = document.createElement("div");
	        head.className = "profile-card-head";
	        const titleBox = document.createElement("div");
	        titleBox.className = "profile-card-title";
	        const title = document.createElement("strong");
	        title.textContent = item.title || "未命名档案";
	        const stats = profileTextStats(item.title, item.content);
	        const meta = document.createElement("span");
	        meta.className = "library-card-meta";
	        meta.textContent = item.type + " · " + stats.chars + " 字 · 约 " + stats.tokens + " Token";
	        titleBox.append(title, meta);
	        const toggle = document.createElement("label");
	        toggle.className = "profile-switch";
	        const toggleInput = document.createElement("input");
	        toggleInput.type = "checkbox";
	        toggleInput.checked = Boolean(item.enabled);
	        toggleInput.addEventListener("change", () => toggleProfileEnabled(item.id, toggleInput.checked));
	        const toggleText = document.createElement("span");
	        toggleText.textContent = item.enabled ? "启用" : "停用";
	        toggle.append(toggleInput, toggleText);
	        head.append(titleBox, toggle);

	        const content = document.createElement("p");
	        content.className = "profile-card-content";
	        content.textContent = item.content || "";
	        const footer = document.createElement("div");
	        footer.className = "library-actions";
	        const edit = createIconButton("pencil", "编辑", { fallback: "✎" });
	        edit.addEventListener("click", () => fillProfileForm(item));
	        const del = createIconButton("trash-2", "删除", { danger: true, fallback: "删" });
	        del.addEventListener("click", () => deleteProfile(item.id, item.title));
	        const grip = document.createElement("span");
	        grip.className = "library-card-meta";
	        grip.innerHTML = iconLabel("grip-vertical", "拖拽排序");
	        footer.append(edit, del, grip);
	        card.append(head, content, footer);
	        box.appendChild(card);
	      }
	      queueLucideRefresh();
	    }

	    function moveProfileBefore(targetId) {
	      const dragId = state.profileDragId;
	      if (!dragId || dragId === targetId) return;
	      const list = state.profiles.slice();
	      const from = list.findIndex((item) => item.id === dragId);
	      const to = list.findIndex((item) => item.id === targetId);
	      if (from < 0 || to < 0) return;
	      const [dragged] = list.splice(from, 1);
	      const nextTo = list.findIndex((item) => item.id === targetId);
	      list.splice(nextTo, 0, dragged);
	      state.profiles = list;
	      state.profileTotals = currentProfileTotals();
	      renderProfileList();
	      updateProfileSummary();
	      renderProfileStatus();
	      saveProfileOrder();
	    }

	    async function saveProfileOrder() {
	      const res = await api("/api/profiles/reorder", {
	        method: "POST",
	        body: JSON.stringify({ ids: state.profiles.map((item) => item.id) })
	      });
	      if (!res.ok) {
	        setStatus("profileStatusText", await readError(res, "排序保存失败，稍后再试一下。"), "err");
	        await loadProfiles();
	        return;
	      }
	      const data = await res.json();
	      applyProfilesPayload(data);
	      setStatus("profileStatusText", "排序已保存", "ok");
	    }

	    function fillProfileForm(item) {
	      state.editingProfileId = item.id || "";
	      $("editingProfileId").value = item.id || "";
	      $("profileTitle").value = item.title || "";
	      $("profileContent").value = item.content || "";
	      $("profileType").value = item.type || "profile";
	      $("profileSortOrder").value = item.sort_order ?? 100;
	      $("profileEnabled").checked = Boolean(item.enabled);
	      updateProfileEditorMeta();
	      setStatus("profileStatusText", "正在编辑：" + (item.title || ""), "");
	    }

	    function resetProfileForm(clearStatus = true) {
	      state.editingProfileId = null;
	      $("editingProfileId").value = "";
	      $("profileTitle").value = "";
	      $("profileContent").value = "";
	      $("profileType").value = "profile";
	      $("profileSortOrder").value = "100";
	      $("profileEnabled").checked = true;
	      updateProfileEditorMeta();
	      if (clearStatus) setStatus("profileStatusText", "");
	    }

	    async function saveProfile() {
	      const id = $("editingProfileId").value;
	      const body = {
	        title: $("profileTitle").value.trim(),
	        content: $("profileContent").value.trim(),
	        type: $("profileType").value || "profile",
	        sort_order: Number($("profileSortOrder").value || 100),
	        enabled: $("profileEnabled").checked
	      };
	      if (!body.title || !body.content) {
	        setStatus("profileStatusText", "标题和内容都要填写。", "err");
	        return;
	      }
	      const res = await api(id ? `/api/profiles/${id}` : "/api/profiles", {
	        method: id ? "PUT" : "POST",
	        body: JSON.stringify(body)
	      });
	      if (!res.ok) {
	        setStatus("profileStatusText", await readError(res, "AI档案保存失败，稍后再试一下。"), "err");
	        return;
	      }
	      resetProfileForm(false);
	      await loadProfiles();
	      setStatus("profileStatusText", "AI档案已保存", "ok");
	    }

	    async function toggleProfileEnabled(id, enabled) {
	      const item = state.profiles.find((profile) => profile.id === id);
	      if (!item) return;
	      const res = await api(`/api/profiles/${id}`, {
	        method: "PATCH",
	        body: JSON.stringify({ ...item, enabled })
	      });
	      if (!res.ok) {
	        setStatus("profileStatusText", await readError(res, "状态保存失败，稍后再试一下。"), "err");
	        await loadProfiles();
	        return;
	      }
	      await loadProfiles();
	      setStatus("profileStatusText", enabled ? "已启用" : "已停用", "ok");
	    }

	    async function deleteProfile(id, title) {
	      const ok = await confirmAction({
	        title: "删除 AI档案",
	        message: `确定删除“${title || "这条档案"}”吗？删除后后续聊天不会再参考它。`,
	        confirmText: "删除",
	        danger: true
	      });
	      if (!ok) return;
	      const res = await api(`/api/profiles/${id}`, { method: "DELETE" });
	      if (!res.ok) {
	        setStatus("profileStatusText", await readError(res, "删除 AI档案失败，稍后再试一下。"), "err");
	        return;
	      }
	      if ($("editingProfileId").value === id) resetProfileForm(false);
	      await loadProfiles();
	      setStatus("profileStatusText", "AI档案已删除", "ok");
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

	    async function openFavorites() {
	      $("favoriteDialog").classList.add("show");
	      setDialogOpenState();
	      await loadFavorites();
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
	        list.appendChild(createEmptyState("alert-circle", "收藏加载失败", errorText, { compact: true }));
	      } else if (!state.favorites.length) {
	        list.appendChild(createEmptyState("star", "还没有收藏", "看到好用的 AI 回复时，点消息下面的“收藏”。", { compact: true }));
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
		          const view = createIconButton("eye", "查看", { primary: item.id === state.selectedFavoriteId, fallback: "看" });
		          view.addEventListener("click", () => selectFavorite(item.id));
		          const insert = createIconButton("corner-down-left", "插入输入框", { fallback: "↵" });
		          insert.addEventListener("click", () => {
		            insertPromptText(item.content);
		            closeFavorites();
		          });
		          const copy = createIconButton("copy", "复制", { fallback: "⧉" });
		          copy.addEventListener("click", () => copyText(item.content, copy));
		          const del = createIconButton("trash-2", "删除", { danger: true, fallback: "删" });
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
		        queueMarkdownOverflowRefresh(content);
	      } else {
	        state.selectedFavoriteId = null;
	        detail.replaceChildren(createEmptyState("eye", "选择一条收藏", "在左侧选择一条收藏查看完整回答。"));
	      }
	      queueLucideRefresh();
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

	    function formatFileSize(value) {
	      const size = Number(value || 0);
	      if (size >= 1024 * 1024 * 1024) return (size / 1024 / 1024 / 1024).toFixed(1) + " GB";
	      if (size >= 1024 * 1024) return (size / 1024 / 1024).toFixed(1) + " MB";
	      if (size >= 1024) return (size / 1024).toFixed(1) + " KB";
	      return size + " B";
	    }

	    function mediaStatusText(status) {
	      const map = {
	        uploaded: "已上传",
	        submitted: "已提交",
	        processing: "转写中",
	        completed: "已完成",
	        failed: "失败"
	      };
	      return map[status] || status || "处理中";
	    }

	    async function openMediaAnalysis() {
	      $("mediaDialog").classList.add("show");
	      setDialogOpenState();
	      await loadMediaTasks();
	    }

	    function closeMediaAnalysis() {
	      $("mediaDialog").classList.remove("show");
	      setDialogOpenState();
	      if (state.mediaPollTimer) clearTimeout(state.mediaPollTimer);
	      state.mediaPollTimer = null;
	    }

	    async function loadMediaTasks() {
	      try {
	        const res = await api("/api/media/tasks");
	        const data = await res.json();
	        state.mediaTasks = data.tasks || [];
	        if (!state.selectedMediaTaskId && state.mediaTasks[0]) state.selectedMediaTaskId = state.mediaTasks[0].id;
	        renderMediaTasks();
	        renderMediaDetail();
	        scheduleMediaPolling();
	      } catch (err) {
	        state.mediaTasks = [];
	        renderMediaTasks();
	        setStatus("mediaStatus", friendlyError(err, "音视频任务加载失败。"), "err");
	      }
	    }

	    function scheduleMediaPolling() {
	      if (state.mediaPollTimer) clearTimeout(state.mediaPollTimer);
	      state.mediaPollTimer = null;
	      if (!$("mediaDialog").classList.contains("show")) return;
	      const active = state.mediaTasks.some((task) => ["uploaded", "submitted", "processing"].includes(task.status));
	      if (!active) return;
	      state.mediaPollTimer = setTimeout(() => {
	        refreshSelectedMediaTask(true).catch(() => loadMediaTasks());
	      }, 30000);
	    }

	    function renderMediaTasks() {
	      const list = $("mediaTaskList");
	      list.innerHTML = "";
	      if (!state.mediaTasks.length) {
	        list.appendChild(createEmptyState("file-video", "还没有任务", "上传一段音频或视频，槑槑会帮你转写和整理。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      for (const task of state.mediaTasks) {
	        const card = document.createElement("article");
	        card.className = "library-card" + (task.id === state.selectedMediaTaskId ? " active" : "");
	        const title = document.createElement("strong");
	        title.textContent = task.filename || "音视频文件";
	        const meta = document.createElement("div");
	        meta.className = "library-card-meta";
	        meta.textContent = mediaStatusText(task.status) + " · " + formatFileSize(task.file_size) + " · " + formatTime(task.updated_at) + (task.conversation_id ? " · 已建会话" : "");
	        const summary = document.createElement("p");
	        summary.textContent = task.error_message || task.summary_text || task.outline_text || task.transcript_text || "等待通义听悟处理结果";
	        const actions = document.createElement("div");
	        actions.className = "library-actions";
	        const view = document.createElement("button");
	        view.type = "button";
	        view.className = (task.id === state.selectedMediaTaskId ? "primary ui-btn ui-btn-primary" : "ui-btn ui-btn-secondary") + " inline-flex items-center gap-2";
	        view.innerHTML = iconLabel("eye", "查看", "看");
	        view.addEventListener("click", () => selectMediaTask(task.id));
	        const refresh = document.createElement("button");
	        refresh.type = "button";
	        refresh.className = "ui-btn ui-btn-secondary inline-flex items-center gap-2";
	        refresh.innerHTML = iconLabel("rotate-cw", "刷新", "↻");
	        refresh.addEventListener("click", () => refreshMediaTask(task.id));
	        actions.append(view, refresh);
	        card.append(title, meta, summary, actions);
	        list.appendChild(card);
	      }
	      queueLucideRefresh();
	    }

	    function selectMediaTask(id) {
	      state.selectedMediaTaskId = id;
	      state.mediaTab = "summary";
	      renderMediaTasks();
	      renderMediaDetail();
	      refreshSelectedMediaTask(false).catch(() => {});
	    }

	    function currentMediaTask() {
	      return state.mediaTasks.find((item) => item.id === state.selectedMediaTaskId) || state.mediaTasks[0] || null;
	    }

	    function mediaTabContent(task) {
	      const outputs = mediaAIOutputs(task);
	      const enhanced = [
	        task.enhanced_summary ? "## 深度总结\n" + task.enhanced_summary : "",
	        task.key_points ? "## 核心观点\n" + task.key_points : "",
	        outputs.selling_points ? "## 卖点/爆点\n" + outputs.selling_points : "",
	        outputs.titles ? "## 标题方向\n" + outputs.titles : ""
	      ].filter(Boolean).join("\n\n");
	      const copywriting = [
	        task.copywriting_text ? "## 综合文案\n" + task.copywriting_text : "",
	        outputs.short_video ? "## 短视频文案\n" + outputs.short_video : "",
	        outputs.speech_script ? "## 口播稿\n" + outputs.speech_script : "",
	        outputs.wechat_article ? "## 公众号文章\n" + outputs.wechat_article : "",
	        outputs.xiaohongshu_note ? "## 小红书笔记\n" + outputs.xiaohongshu_note : "",
	        outputs.moments_copy ? "## 朋友圈文案\n" + outputs.moments_copy : ""
	      ].filter(Boolean).join("\n\n");
	      const fields = {
	        summary: task.summary_text || "",
	        outline: task.outline_text || "",
	        transcript: task.transcript_text || "",
	        enhanced,
	        mindmap: task.mindmap_text ? "```mermaid\n" + task.mindmap_text + "\n```" : "",
	        copywriting
	      };
	      return fields[state.mediaTab] || "";
	    }

	    function mediaAIOutputs(task) {
	      if (!task?.ai_outputs_json) return {};
	      try {
	        const data = JSON.parse(task.ai_outputs_json);
	        return data && typeof data === "object" ? data : {};
	      } catch {
	        return {};
	      }
	    }

	    function mediaHasEnhanced(task) {
	      return Boolean(task?.enhanced_summary || task?.key_points || task?.ai_outputs_json);
	    }

	    function mediaHasCopywriting(task) {
	      const outputs = mediaAIOutputs(task);
	      return Boolean(
	        task?.copywriting_text ||
	        outputs.short_video ||
	        outputs.speech_script ||
	        outputs.wechat_article ||
	        outputs.xiaohongshu_note ||
	        outputs.moments_copy ||
	        outputs.copywriting_text
	      );
	    }

	    function mediaTaskReadyForAI(task) {
	      return Boolean(
	        task &&
	        task.status === "completed" &&
	        (task.summary_text || task.outline_text || task.transcript_text || task.mindmap_text || task.copywriting_text)
	      );
	    }

	    function mediaCreativePrompt(type, task) {
	      const filename = task?.filename || "这段音视频";
	      const prompts = {
	        shortVideo: `请基于《${filename}》的音视频分析结果，生成一版适合短视频发布的文案。要求：给出3个标题方向、1段开头钩子、正文分镜/画面建议、结尾引导，语气自然有吸引力。`,
	        speech: `请基于《${filename}》的音视频分析结果，生成一版口播稿。要求：适合真人口播，开头抓人，中间逻辑清楚，结尾有行动引导，语言口语化。`,
	        article: `请基于《${filename}》的音视频分析结果，生成一篇公众号文章。要求：标题、导语、小标题结构、正文、结尾总结都完整，表达清楚，有阅读层次。`,
	        xiaohongshu: `请基于《${filename}》的音视频分析结果，生成一篇小红书笔记。要求：给出标题、正文、分点内容、适合的表情符号和话题标签，语气真诚自然。`,
	        moments: `请基于《${filename}》的音视频分析结果，生成3版朋友圈文案。要求：分别是自然分享版、简短有梗版、正式一点版。`,
	        mindmap: `请基于《${filename}》的音视频分析结果，生成一份 Mermaid mindmap。要求：只输出 Mermaid，使用 mindmap 语法，中文节点，层级不超过4层，节点不要太长，不要输出解释文字。`,
	        sellingPoints: `请基于《${filename}》的音视频分析结果，提取最适合传播的卖点/爆点。要求：分为核心卖点、情绪卖点、标题爆点、可延展选题。`,
	        titles: `请基于《${filename}》的音视频分析结果，生成12个标题。要求：分别覆盖短视频、小红书、公众号和朋友圈语境，标题自然不夸张。`
	      };
	      return prompts[type] || prompts.shortVideo;
	    }

	    function mediaCreativeIcon(type) {
	      const icons = {
	        shortVideo: "video",
	        speech: "mic",
	        article: "file-text",
	        xiaohongshu: "book-open",
	        moments: "share-2",
	        mindmap: "git-branch",
	        sellingPoints: "tag",
	        titles: "type"
	      };
	      return icons[type] || "sparkles";
	    }

	    function mediaTabIcon(key) {
	      const icons = {
	        summary: "file-text",
	        outline: "list",
	        transcript: "align-left",
	        enhanced: "sparkles",
	        mindmap: "git-branch",
	        copywriting: "clipboard"
	      };
	      return icons[key] || "file-text";
	    }

	    function mediaStatusIcon(status) {
	      const icons = {
	        completed: "check-circle",
	        failed: "alert-circle",
	        processing: "loader",
	        uploaded: "clock",
	        pending: "clock"
	      };
	      return icons[status] || "circle";
	    }

	    function upsertMediaConversationTask(task, conversation) {
	      if (!task) return;
	      if (conversation?.id) task.conversation_id = conversation.id;
	      upsertMediaTask(task);
	      renderMediaTasks();
	      renderMediaDetail();
	    }

	    async function ensureMediaConversation(task, options = {}) {
	      if (!mediaTaskReadyForAI(task)) {
	        setStatus("mediaStatus", "分析完成后才能发送到 AI 对话。", "err");
	        return null;
	      }
	      const modelId = $("modelSelect").value || state.currentConversation?.model_id || state.models[0]?.id || "";
	      const res = await api(`/api/media/tasks/${task.id}/conversation`, {
	        method: "POST",
	        body: JSON.stringify({ model_id: modelId })
	      });
	      if (!res.ok) {
	        setStatus("mediaStatus", await readError(res, "创建分析会话失败。"), "err");
	        return null;
	      }
	      const data = await res.json();
	      upsertConversation(data.conversation);
	      upsertMediaConversationTask(data.task, data.conversation);
	      if (options.open) {
	        closeMediaAnalysis();
	        await selectConversation(data.conversation.id);
	        setStatus("chatStatus", "已进入音视频分析会话，可以继续加工内容。", "ok");
	      } else {
	        setStatus("mediaStatus", "分析会话已创建，可以随时进入继续加工。", "ok");
	      }
	      return data.conversation;
	    }

	    async function sendMediaPromptToAI(task, type) {
	      if (state.sending) {
	        setStatus("mediaStatus", "上一条还在生成，先等它完成。", "err");
	        return;
	      }
	      const conversation = await ensureMediaConversation(task, { open: true });
	      if (!conversation) return;
	      await sendMessage(mediaCreativePrompt(type, task), { statusText: "正在基于音视频分析生成内容..." });
	    }

	    async function enhanceMediaTask(task, force = false) {
	      if (!mediaTaskReadyForAI(task)) {
	        setStatus("mediaStatus", "分析完成后才能生成 AI 增强分析。", "err");
	        return;
	      }
	      const modelId = $("modelSelect").value || state.currentConversation?.model_id || state.models[0]?.id || "";
	      setStatus("mediaStatus", force ? "正在重新生成 AI 增强分析..." : "正在生成 AI 增强分析...", "");
	      const res = await api(`/api/media/tasks/${task.id}/enhance`, {
	        method: "POST",
	        body: JSON.stringify({ model_id: modelId, force })
	      });
	      if (!res.ok) {
	        setStatus("mediaStatus", await readError(res, "AI 增强分析失败。"), "err");
	        return;
	      }
	      const data = await res.json();
	      upsertMediaTask(data.task);
	      state.mediaTab = data.task?.mindmap_text ? "mindmap" : "enhanced";
	      renderMediaTasks();
	      renderMediaDetail();
	      setStatus("mediaStatus", data.cached ? "已加载缓存的 AI 增强分析。" : "AI 增强分析已生成。", "ok");
	    }

	    function createMediaAIButtons(task) {
	      const panel = document.createElement("section");
	      panel.className = "media-ai-panel";
	      const title = document.createElement("strong");
	      title.className = "media-ai-title";
	      title.innerHTML = iconLabel("sparkles", "AI 持续加工", "✦");
	      const hint = document.createElement("div");
	      hint.className = "media-ai-hint";
	      hint.textContent = mediaTaskReadyForAI(task)
	        ? "已可把摘要、章节和转写作为上下文，进入专属 AI 会话继续加工。"
	        : "分析完成后，可以一键创建 AI 加工会话，无需重复上传。";
	      const mainActions = document.createElement("div");
	      mainActions.className = "media-ai-actions";
	      const enhance = document.createElement("button");
	      enhance.type = "button";
	      enhance.className = (mediaHasEnhanced(task) ? "ui-btn ui-btn-secondary" : "primary ui-btn ui-btn-primary") + " inline-flex items-center gap-2";
	      enhance.innerHTML = mediaHasEnhanced(task)
	        ? iconLabel("rotate-cw", "重新生成AI增强", "↻")
	        : iconLabel("sparkles", "生成AI增强分析", "✦");
	      enhance.disabled = !mediaTaskReadyForAI(task);
	      enhance.addEventListener("click", () => enhanceMediaTask(task, mediaHasEnhanced(task)).catch((err) => setStatus("mediaStatus", friendlyError(err, "AI 增强分析失败。"), "err")));
	      const send = document.createElement("button");
	      send.type = "button";
	      send.className = (mediaHasEnhanced(task) ? "primary ui-btn ui-btn-primary" : "ui-btn ui-btn-secondary") + " inline-flex items-center gap-2";
	      send.innerHTML = iconLabel("message-square", "发送到AI对话", "↗");
	      send.disabled = !mediaTaskReadyForAI(task);
	      send.addEventListener("click", () => ensureMediaConversation(task, { open: true }).catch((err) => setStatus("mediaStatus", friendlyError(err, "创建分析会话失败。"), "err")));
	      const create = document.createElement("button");
	      create.type = "button";
	      create.className = "ui-btn ui-btn-secondary inline-flex items-center gap-2";
	      create.innerHTML = task.conversation_id ? iconLabel("message-square", "进入分析会话", "↗") : iconLabel("plus", "创建分析会话", "+");
	      create.disabled = !mediaTaskReadyForAI(task);
	      create.addEventListener("click", () => ensureMediaConversation(task, { open: Boolean(task.conversation_id) }).catch((err) => setStatus("mediaStatus", friendlyError(err, "创建分析会话失败。"), "err")));
	      mainActions.append(enhance, send, create);
	      const creativeActions = document.createElement("div");
	      creativeActions.className = "media-ai-actions";
	      const items = [
	        ["shortVideo", "短视频文案"],
	        ["speech", "口播稿"],
	        ["article", "公众号文章"],
	        ["xiaohongshu", "小红书笔记"],
	        ["moments", "朋友圈文案"],
	        ["mindmap", "思维导图"],
	        ["sellingPoints", "提取卖点"],
	        ["titles", "生成标题"]
	      ];
	      for (const [type, label] of items) {
	        const button = document.createElement("button");
	        button.type = "button";
	        button.className = "ui-btn ui-btn-secondary inline-flex items-center gap-2";
	        button.innerHTML = iconLabel(mediaCreativeIcon(type), label, "•");
	        button.disabled = !mediaTaskReadyForAI(task);
	        button.addEventListener("click", () => sendMediaPromptToAI(task, type).catch((err) => setStatus("mediaStatus", friendlyError(err, "发送到 AI 对话失败。"), "err")));
	        creativeActions.appendChild(button);
	      }
	      panel.append(title, hint, mainActions, creativeActions);
	      return panel;
	    }

	    function renderMediaDetail() {
	      const detail = $("mediaTaskDetail");
	      const task = currentMediaTask();
	      if (!task) {
	        detail.replaceChildren(createEmptyState("file-video", "选择或上传任务", "上传音频/视频后，这里会显示转写、摘要和 AI 增强结果。"));
	        queueLucideRefresh();
	        return;
	      }
	      state.selectedMediaTaskId = task.id;
	      const tabs = [
	        ["summary", "智能摘要"],
	        ["outline", "章节要点"],
	        ["transcript", "转写全文"],
	        ["enhanced", "AI增强"]
	      ];
	      if (task.mindmap_text) tabs.push(["mindmap", "思维导图"]);
	      if (mediaHasCopywriting(task)) tabs.push(["copywriting", "可复制文案"]);
	      if (!tabs.some(([key]) => key === state.mediaTab)) {
	        state.mediaTab = mediaHasEnhanced(task) ? "enhanced" : "summary";
	      }
	      detail.innerHTML = "";
	      const head = document.createElement("div");
	      head.className = "media-task-head";
	      const headText = document.createElement("div");
	      const headTitle = document.createElement("strong");
	      headTitle.textContent = task.filename || "音视频文件";
	      const headMeta = document.createElement("div");
	      headMeta.className = "library-card-meta";
	      headMeta.textContent = "创建 " + formatTime(task.created_at) + (task.updated_at ? " · 更新 " + formatTime(task.updated_at) : "");
	      headText.append(headTitle, headMeta);
	      const badge = document.createElement("span");
	      badge.className = "media-task-badge";
	      badge.innerHTML = iconLabel(mediaStatusIcon(task.status), mediaStatusText(task.status), "•");
	      head.append(headText, badge);
	      const tabBar = document.createElement("div");
	      tabBar.className = "media-tabs";
	      for (const [key, label] of tabs) {
	        const button = document.createElement("button");
	        button.type = "button";
	        button.className = "media-tab ui-btn ui-btn-secondary" + (state.mediaTab === key ? " active" : "");
	        button.innerHTML = iconLabel(mediaTabIcon(key), label, "•");
	        button.addEventListener("click", () => {
	          state.mediaTab = key;
	          renderMediaDetail();
	        });
	        tabBar.appendChild(button);
	      }
	      const aiPanel = createMediaAIButtons(task);
	      const content = document.createElement("div");
	      content.className = "media-result markdown";
	      const text = task.error_message || mediaTabContent(task) || (
	        state.mediaTab === "enhanced"
	          ? "还没有生成 AI 增强分析。点上方“生成AI增强分析”，槑槑会基于转写、摘要和章节生成深度总结、观点、文案和思维导图。"
	          : (task.status === "completed" ? "这个部分暂时没有结果，可以刷新状态或生成 AI 增强分析。" : "任务处理中，稍后刷新看看。")
	      );
	      content.innerHTML = renderMarkdown(text);
	      const actions = document.createElement("div");
	      actions.className = "library-actions";
	      const copy = document.createElement("button");
	      copy.type = "button";
	      copy.className = "ui-btn ui-btn-secondary inline-flex items-center gap-2";
	      copy.innerHTML = iconLabel("copy", "复制当前内容", "⧉");
	      copy.addEventListener("click", () => copyText(text, copy));
	      const refresh = document.createElement("button");
	      refresh.type = "button";
	      refresh.className = "ui-btn ui-btn-secondary inline-flex items-center gap-2";
	      refresh.innerHTML = iconLabel("rotate-cw", "刷新状态", "↻");
	      refresh.addEventListener("click", () => refreshMediaTask(task.id));
	      const del = document.createElement("button");
	      del.type = "button";
	      del.className = "danger ui-btn ui-btn-secondary inline-flex items-center gap-2";
	      del.innerHTML = iconLabel("trash-2", "删除任务", "删");
	      del.addEventListener("click", () => deleteMediaTask(task.id));
	      actions.append(copy, refresh, del);
	      detail.append(head, aiPanel, tabBar, content, actions);
	      queueMarkdownOverflowRefresh(content);
	      queueLucideRefresh();
	    }

	    function upsertMediaTask(task) {
	      if (!task) return;
	      const index = state.mediaTasks.findIndex((item) => item.id === task.id);
	      if (index >= 0) state.mediaTasks.splice(index, 1, task);
	      else state.mediaTasks.unshift(task);
	      state.selectedMediaTaskId = task.id;
	    }

	    async function refreshMediaTask(id) {
	      const res = await api(`/api/media/tasks/${id}/refresh`, { method: "POST" });
	      if (!res.ok) {
	        setStatus("mediaStatus", await readError(res, "刷新任务失败。"), "err");
	        return;
	      }
	      const data = await res.json();
	      upsertMediaTask(data.task);
	      renderMediaTasks();
	      renderMediaDetail();
	      scheduleMediaPolling();
	    }

	    async function refreshSelectedMediaTask(silent = false) {
	      const task = currentMediaTask();
	      if (!task) return;
	      const res = await api(`/api/media/tasks/${task.id}`);
	      if (!res.ok) {
	        if (!silent) setStatus("mediaStatus", await readError(res, "刷新任务失败。"), "err");
	        return;
	      }
	      const data = await res.json();
	      upsertMediaTask(data.task);
	      renderMediaTasks();
	      renderMediaDetail();
	      scheduleMediaPolling();
	    }

	    async function deleteMediaTask(id) {
	      const ok = await confirmAction({
	        title: "删除音视频任务",
	        message: "确定删除这个分析任务吗？不会删除 OSS 里的原始文件。",
	        confirmText: "删除",
	        danger: true
	      });
	      if (!ok) return;
	      const res = await api(`/api/media/tasks/${id}`, { method: "DELETE" });
	      if (!res.ok) {
	        setStatus("mediaStatus", await readError(res, "删除任务失败。"), "err");
	        return;
	      }
	      state.mediaTasks = state.mediaTasks.filter((item) => item.id !== id);
	      if (state.selectedMediaTaskId === id) state.selectedMediaTaskId = state.mediaTasks[0]?.id || null;
	      renderMediaTasks();
	      renderMediaDetail();
	    }

	    function safeMediaFilename(name) {
	      return String(name || "media").replace(/[\\/]+/g, "_").replace(/[^\w.\-\u4e00-\u9fa5]+/g, "_").slice(0, 120);
	    }

	    async function uploadMediaTask() {
	      if (state.mediaUploading) return;
	      const file = $("mediaFile").files?.[0];
	      if (!file) {
	        setStatus("mediaStatus", "先选择一个音频或视频文件。", "err");
	        return;
	      }
	      state.mediaUploading = true;
	      $("uploadMediaTask").disabled = true;
	      setStatus("mediaStatus", "正在获取上传凭证...", "");
	      try {
	        const policyRes = await api("/api/media/upload-policy", { method: "POST" });
	        if (!policyRes.ok) throw new Error(await readError(policyRes, "上传配置不可用。"));
	        const { policy } = await policyRes.json();
	        if (file.size > policy.max_size) throw new Error("文件大小超出限制");
	        const key = policy.key_prefix + Date.now() + "-" + Math.random().toString(36).slice(2, 8) + "-" + safeMediaFilename(file.name);
	        const form = new FormData();
	        form.append("key", key);
	        form.append("OSSAccessKeyId", policy.access_key_id);
	        form.append("policy", policy.policy);
	        form.append("Signature", policy.signature);
	        form.append("success_action_status", "200");
	        form.append("Content-Type", file.type || "application/octet-stream");
	        form.append("file", file);
	        setStatus("mediaStatus", "正在上传到 OSS...", "");
	        const uploadRes = await fetch(policy.host, { method: "POST", body: form });
	        if (!uploadRes.ok) throw new Error("上传 OSS 失败");
	        setStatus("mediaStatus", "上传完成，正在创建听悟任务...", "");
	        const createRes = await api("/api/media/tasks", {
	          method: "POST",
	          body: JSON.stringify({
	            filename: file.name,
	            mime_type: file.type || "",
	            file_size: file.size,
	            oss_key: key,
	            source_language: "cn"
	          })
	        });
	        if (!createRes.ok) throw new Error(await readError(createRes, "创建听悟任务失败。"));
	        const data = await createRes.json();
	        upsertMediaTask(data.task);
	        $("mediaFile").value = "";
	        renderMediaTasks();
	        renderMediaDetail();
	        scheduleMediaPolling();
	        setStatus(
	          "mediaStatus",
	          data.task?.status === "failed" ? "任务创建失败，请查看详情。" : "已提交听悟，稍后刷新查看结果。",
	          data.task?.status === "failed" ? "err" : "ok"
	        );
	      } catch (err) {
	        setStatus("mediaStatus", friendlyError(err, "上传或创建任务失败。"), "err");
	      } finally {
	        state.mediaUploading = false;
	        $("uploadMediaTask").disabled = false;
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
        sortConversations();
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
	      function appendGroup(titleText) {
	        const title = document.createElement("div");
	        title.className = "conversation-group";
	        title.textContent = titleText;
	        box.appendChild(title);
	      }
	      function appendConversation(conv) {
	        const row = document.createElement("div");
	        const active = state.currentConversation?.id === conv.id;
	        const editing = state.editingConversationId === conv.id;
	        row.className = "conv" + (active ? " active" : "") + (editing ? " editing" : "") + (conv.pinned ? " pinned" : "");

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
	          const save = createIconOnlyButton("check", "保存", { className: "conv-action ui-icon-btn", fallback: "✓" });
	          save.addEventListener("click", () => saveConversationTitle(conv.id, input.value));
	          const cancel = createIconOnlyButton("x", "取消", { className: "conv-action ui-icon-btn", fallback: "×" });
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
		          main.innerHTML = `<span class="conv-title"><span class="conv-title-text"></span></span><span class="conv-meta"><span class="conv-model"></span><span class="conv-time"></span></span>`;
		          main.querySelector(".conv-title-text").textContent = conv.title;
		          if (conv.pinned) {
		            const pin = document.createElement("span");
		            pin.className = "conv-pin-indicator";
		            pin.title = "已置顶";
		            pin.innerHTML = iconMarkup("pin", "📌");
		            main.querySelector(".conv-title").appendChild(pin);
		          }
		          main.querySelector(".conv-model").textContent = conv.model_name || "未命名模型";
		          main.querySelector(".conv-time").textContent = formatTime(conv.updated_at);
		          main.addEventListener("click", () => selectConversation(conv.id));

	          const actions = document.createElement("div");
	          actions.className = "conv-actions";
	          const pinToggle = createIconOnlyButton(conv.pinned ? "pin-off" : "pin", conv.pinned ? "取消置顶" : "置顶", { className: "conv-action pin-action ui-icon-btn", fallback: conv.pinned ? "取" : "置" });
	          pinToggle.addEventListener("click", () => togglePinConversation(conv.id));
	          const edit = createIconOnlyButton("pencil", "重命名", { className: "conv-action ui-icon-btn", fallback: "✎" });
	          edit.addEventListener("click", () => startRenameConversation(conv.id));
	          const del = createIconOnlyButton("trash-2", "删除", { className: "conv-action ui-icon-btn", danger: true, fallback: "⌫" });
	          del.addEventListener("click", () => deleteConversationById(conv.id));
	          actions.append(pinToggle, edit, del);
	          row.append(main, actions);
	        }
	        box.appendChild(row);
	      }
	      const pinned = state.conversations.filter((conv) => conv.pinned);
	      const normal = state.conversations.filter((conv) => !conv.pinned);
	      if (pinned.length) {
	        appendGroup("置顶");
	        pinned.forEach(appendConversation);
	      }
	      let lastGroup = "";
	      for (const conv of normal) {
	        const group = conversationGroupLabel(conv.updated_at || conv.created_at);
	        if (group !== lastGroup) {
	          appendGroup(group);
	          lastGroup = group;
	        }
	        appendConversation(conv);
	      }
	      queueLucideRefresh();
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

    function sortConversations() {
      state.conversations.sort((a, b) => {
        const pinnedDelta = Number(Boolean(b.pinned)) - Number(Boolean(a.pinned));
        if (pinnedDelta) return pinnedDelta;
        return Number(b.updated_at || 0) - Number(a.updated_at || 0);
      });
    }

    function upsertConversation(conversation) {
      if (!conversation) return;
      const index = state.conversations.findIndex((item) => item.id === conversation.id);
      if (index >= 0) {
        state.conversations.splice(index, 1, conversation);
      } else {
        state.conversations.unshift(conversation);
      }
      sortConversations();
      renderConversations();
    }

	    async function togglePinConversation(id) {
	      const conv = state.conversations.find((item) => item.id === id);
	      if (!conv) return;
	      const action = conv.pinned ? "unpin" : "pin";
	      const res = await api(`/api/conversations/${id}/${action}`, { method: "POST" });
	      if (!res.ok) {
	        setStatus("chatStatus", await readError(res, conv.pinned ? "取消置顶失败，稍后再试一下。" : "置顶失败，稍后再试一下。"), "err");
	        return;
	      }
	      const data = await res.json();
	      upsertConversation(data.conversation);
	      if (state.currentConversation?.id === id) {
	        state.currentConversation = data.conversation;
	        updateChatHeader();
	      }
	      setStatus("chatStatus", conv.pinned ? "已取消置顶" : "已置顶", "ok");
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
        state.conversationStats = null;
        state.messages = [];
        await loadConversations();
        updateChatHeader();
        renderProfileStatus();
        renderProfilePopover();
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

	    async function selectConversation(id, options = {}) {
	      state.editingConversationId = null;
	      const conv = state.conversations.find((item) => item.id === id);
	      if (!conv) return;
      state.currentConversation = conv;
      $("modelSelect").value = conv.model_id;
      updateChatHeader();
      renderProfileStatus();
      renderProfilePopover();
      renderConversations();
      try {
        const res = await api(`/api/conversations/${id}/messages`);
        if (!res.ok) throw new Error(await readError(res, "消息暂时加载失败。"));
        const data = await res.json();
        state.messages = data.messages || [];
        const targetMessageId = Number(options.messageId || 0);
        renderMessages({ forceScroll: !targetMessageId });
        await loadConversationStats(id);
        closeSidebar();
        if (targetMessageId) {
          requestAnimationFrame(() => scrollToMessageId(targetMessageId));
        }
      } catch (err) {
        setStatus("chatStatus", friendlyError(err, "消息暂时加载失败。"), "err");
      }
    }

    function scrollToMessageId(messageId) {
      const box = $("messages");
      if (!box || !messageId) return false;
      const message = state.messages.find((item) => Number(item.id || 0) === Number(messageId));
      if (!message) return false;
      const wrap = box.querySelector(`[data-message-key="${messageKey(message)}"]`);
      if (!wrap) return false;
      const target = clampNumber(
        wrap.offsetTop - Math.max(72, box.clientHeight * .18),
        0,
        Math.max(0, box.scrollHeight - box.clientHeight),
        0
      );
      state.programmaticScroll = true;
      box.scrollTo({ top: target, behavior: "smooth" });
      wrap.classList.add("search-hit-highlight");
      setTimeout(() => {
        state.programmaticScroll = false;
        handleMessagesScroll();
      }, 520);
      setTimeout(() => wrap.classList.remove("search-hit-highlight"), 1900);
      queueConversationMinimap();
      return true;
    }

    function updateChatHeader() {
      const conv = state.currentConversation;
      $("chatTitle").textContent = conv ? conv.title : "新对话";
      $("chatModel").textContent = conv ? (conv.model_name + (conv.supports_vision ? " · 可看图" : "") + " · " + conv.model) : "请选择模型";
      updateChatUsage();
      renderProfileStatus();
      renderProfilePopover();
      renderModelSelect();
    }

		    function renderEmpty() {
		      $("chatTitle").textContent = "新对话";
		      $("chatModel").textContent = state.models[0] ? "准备使用 " + state.models[0].name : "请选择模型";
	      state.conversationStats = null;
	      updateChatUsage();
	      renderProfileStatus();
	      renderProfilePopover();
	      hideConversationMinimap();
	      const box = $("messages");
	      box.innerHTML = `
	        <div class="empty">
	          <img class="empty-hero" src="/res/meimei-empty-state.png?v=2.2.13" alt="槑槑欢迎插画">
	          <div class="empty-copy">
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

	    function escapeRegExp(value) {
	      return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
	    }

	    function globalSearchShortcutText() {
	      return /Mac|iPhone|iPad|iPod/i.test(navigator.platform || navigator.userAgent || "") ? "⌘K" : "Ctrl K";
	    }

	    function globalSearchIcon(type, role) {
	      if (type === "conversation") return "messages-square";
	      if (type === "favorite") return "star";
	      if (type === "media") return "file-video";
	      if (role === "user") return "user-round";
	      if (role === "assistant") return "cat";
	      return "message-square";
	    }

	    function globalSearchTypeLabel(item) {
	      if (item.type === "conversation") return "会话";
	      if (item.type === "favorite") return "收藏";
	      if (item.type === "media") return "音视频";
	      if (item.role === "user") return "用户消息";
	      if (item.role === "assistant") return "槑槑回复";
	      return "消息";
	    }

	    function highlightSearchText(value, query = state.globalSearchQuery) {
	      const text = String(value || "");
	      const q = String(query || "").trim();
	      if (!q) return escapeHTML(text);
	      const pattern = new RegExp("(" + escapeRegExp(q) + ")", "ig");
	      return escapeHTML(text).replace(pattern, "<mark>$1</mark>");
	    }

	    function openGlobalSearch() {
	      if (!state.authed) return;
	      const dialog = $("globalSearchDialog");
	      const input = $("globalSearchInput");
	      if (!dialog || !input) return;
	      dialog.classList.add("show");
	      setDialogOpenState();
	      state.globalSearchSelected = 0;
	      state.globalSearchQuery = "";
	      state.globalSearchError = "";
	      input.value = "";
	      renderGlobalSearchResults();
	      runGlobalSearch("");
	      setTimeout(() => {
	        input.focus();
	        input.select();
	      }, 30);
	    }

	    function closeGlobalSearch() {
	      const dialog = $("globalSearchDialog");
	      if (!dialog) return;
	      dialog.classList.remove("show");
	      if (state.globalSearchTimer) {
	        clearTimeout(state.globalSearchTimer);
	        state.globalSearchTimer = 0;
	      }
	      setDialogOpenState();
	    }

	    function versionLabel(version) {
	      const text = String(version || "").trim();
	      return text ? (text.startsWith("v") ? text : "v" + text) : "v";
	    }

	    function renderChangelogLoading() {
	      const box = $("changelogList");
	      if (!box) return;
	      box.replaceChildren(createEmptyState("loader-circle", "槑槑正在翻更新记录...", "稍等一下。", { compact: true }));
	      queueLucideRefresh();
	    }

	    function renderChangelogEntries() {
	      const box = $("changelogList");
	      const more = $("openFullChangelog");
	      const title = $("changelogTitleText");
	      if (!box || !more || !title) return;
	      const entries = state.changelogEntries || [];
	      title.textContent = state.changelogFull ? "完整更新日志" : "最近更新";
	      more.hidden = state.changelogFull || (!state.changelogHasMore && entries.length <= 8);
	      box.replaceChildren();
	      if (!entries.length) {
	        const empty = document.createElement("div");
	        empty.className = "changelog-empty";
	        empty.textContent = "暂无更新日志";
	        box.appendChild(empty);
	        queueLucideRefresh();
	        return;
	      }
	      const current = String(state.changelogVersion || "").replace(/^v/i, "");
	      for (const entry of entries) {
	        const article = document.createElement("article");
	        const isCurrent = String(entry.version || "").replace(/^v/i, "") === current;
	        article.className = "changelog-entry" + (isCurrent ? " is-current" : "");
	        const points = Array.isArray(entry.points) ? entry.points : [];
	        const visiblePoints = state.changelogFull ? points : points.slice(0, 4);
	        article.innerHTML =
	          '<div class="changelog-entry-head">' +
	            '<span class="changelog-version"><span>' + escapeHTML(versionLabel(entry.version)) + '</span>' +
	              (isCurrent ? '<span class="changelog-current">当前版本</span>' : '') +
	            '</span>' +
	            '<span class="changelog-date">' + escapeHTML(entry.date || "") + '</span>' +
	          '</div>' +
	          '<h3>' + escapeHTML(entry.title || "更新内容") + '</h3>' +
	          '<ul class="changelog-points">' + (visiblePoints.length ? visiblePoints.map((point) => '<li>' + escapeHTML(point) + '</li>').join("") : '<li>暂无详细说明。</li>') + '</ul>' +
	          (entry.commit ? '<span class="changelog-commit">' + escapeHTML(entry.commit) + '</span>' : '');
	        box.appendChild(article);
	      }
	      queueLucideRefresh();
	    }

	    function positionChangelogPanel() {
	      const dialog = $("changelogDialog");
	      const panel = $("changelogPanel");
	      const anchor = state.changelogAnchor;
	      if (!dialog || !panel || !anchor || state.changelogFull || isSmallScreen()) return;
	      const rect = anchor.getBoundingClientRect();
	      const width = Math.min(430, window.innerWidth - 24);
	      const height = Math.min(panel.offsetHeight || 520, window.innerHeight - 24);
	      const left = clampNumber(rect.left, 12, Math.max(12, window.innerWidth - width - 12), 12);
	      let top = rect.bottom + 10;
	      if (top + height > window.innerHeight - 12) top = rect.top - height - 10;
	      top = clampNumber(top, 12, Math.max(12, window.innerHeight - height - 12), 12);
	      panel.style.width = width + "px";
	      panel.style.left = left + "px";
	      panel.style.top = top + "px";
	      panel.style.bottom = "auto";
	    }

	    async function openChangelog(event, options = {}) {
	      event?.preventDefault();
	      event?.stopPropagation();
	      const dialog = $("changelogDialog");
	      const panel = $("changelogPanel");
	      if (!dialog || !panel) return;
	      state.changelogFull = Boolean(options.full);
	      if (!state.changelogFull) state.changelogAnchor = event?.currentTarget || state.changelogAnchor;
	      dialog.classList.add("show");
	      dialog.classList.toggle("full", state.changelogFull);
	      panel.setAttribute("aria-modal", state.changelogFull ? "true" : "false");
	      renderChangelogLoading();
	      setDialogOpenState();
	      try {
	        const url = "/api/changelog" + (state.changelogFull ? "" : "?limit=8");
	        const res = await request(url);
	        if (!res.ok) throw new Error(await readError(res, "更新日志暂时加载失败。"));
	        const data = await res.json();
	        state.changelogEntries = data.entries || [];
	        state.changelogVersion = data.version || "";
	        state.changelogHasMore = Boolean(data.has_more);
	        renderChangelogEntries();
	        requestAnimationFrame(positionChangelogPanel);
	      } catch (err) {
	        const box = $("changelogList");
	        if (box) box.replaceChildren(createEmptyState("circle-alert", friendlyError(err, "更新日志暂时加载失败。"), "", { compact: true }));
	        queueLucideRefresh();
	      }
	    }

	    function closeChangelog() {
	      const dialog = $("changelogDialog");
	      if (!dialog) return;
	      dialog.classList.remove("show", "full");
	      state.changelogFull = false;
	      setDialogOpenState();
	    }

	    function handleChangelogOutsideClick(event) {
	      const dialog = $("changelogDialog");
	      const panel = $("changelogPanel");
	      if (!dialog || !panel || !dialog.classList.contains("show")) return;
	      if (panel.contains(event.target) || event.target.closest?.("[data-version-trigger]")) return;
	      closeChangelog();
	    }

	    function scheduleGlobalSearch() {
	      const input = $("globalSearchInput");
	      state.globalSearchQuery = input ? input.value.trim() : "";
	      state.globalSearchLoading = true;
	      state.globalSearchError = "";
	      renderGlobalSearchResults();
	      if (state.globalSearchTimer) clearTimeout(state.globalSearchTimer);
	      state.globalSearchTimer = window.setTimeout(() => {
	        state.globalSearchTimer = 0;
	        runGlobalSearch(state.globalSearchQuery);
	      }, 200);
	    }

	    async function runGlobalSearch(query) {
	      const seq = ++state.globalSearchSeq;
	      state.globalSearchLoading = true;
	      state.globalSearchError = "";
	      renderGlobalSearchResults();
	      try {
	        const res = await api("/api/search?q=" + encodeURIComponent(query || ""));
	        if (!res.ok) throw new Error(await readError(res, "搜索失败，稍后再试一下。"));
	        const data = await res.json();
	        if (seq !== state.globalSearchSeq) return;
	        state.globalSearchResults = data.results || [];
	        state.globalSearchSelected = 0;
	        state.globalSearchLoading = false;
	        renderGlobalSearchResults();
	      } catch (err) {
	        if (seq !== state.globalSearchSeq) return;
	        state.globalSearchResults = [];
	        state.globalSearchLoading = false;
	        state.globalSearchError = friendlyError(err, "搜索暂时不可用，稍后再试一下。");
	        renderGlobalSearchResults();
	      }
	    }

	    function renderGlobalSearchResults() {
	      const box = $("globalSearchResults");
	      if (!box) return;
	      box.replaceChildren();
	      if (state.globalSearchLoading && !state.globalSearchResults.length) {
	        box.appendChild(createEmptyState("loader-circle", "槑槑正在搜索...", "稍等一下，正在翻历史记录。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      if (state.globalSearchError) {
	        box.appendChild(createEmptyState("circle-alert", state.globalSearchError, "", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      if (!state.globalSearchResults.length) {
	        const title = state.globalSearchQuery ? "槑槑没有找到相关内容" : "输入关键词开始搜索";
	        const desc = state.globalSearchQuery ? "换个关键词试试看。" : "可以搜索会话标题、历史消息、收藏和音视频分析。";
	        box.appendChild(createEmptyState("search", title, desc, { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      for (const [index, item] of state.globalSearchResults.entries()) {
	        const button = document.createElement("button");
	        button.type = "button";
	        button.className = "global-search-item" + (index === state.globalSearchSelected ? " active" : "");
	        button.setAttribute("role", "option");
	        button.setAttribute("aria-selected", index === state.globalSearchSelected ? "true" : "false");
	        button.dataset.index = String(index);
	        const roleLabel = item.role ? (item.role === "assistant" ? "槑槑" : (item.role === "user" ? "用户" : item.role)) : globalSearchTypeLabel(item);
	        button.innerHTML =
	          '<span class="global-search-icon">' + iconMarkup(globalSearchIcon(item.type, item.role)) + '</span>' +
	          '<span class="global-search-content">' +
	            '<span class="global-search-title"><span>' + highlightSearchText(item.title || "未命名对话") + '</span><span class="global-search-role">' + escapeHTML(roleLabel) + '</span></span>' +
	            '<span class="global-search-snippet">' + highlightSearchText(item.snippet || "最近对话") + '</span>' +
	          '</span>' +
	          '<span class="global-search-time">' + escapeHTML(formatTime(item.created_at)) + '</span>';
	        button.addEventListener("mouseenter", () => {
	          setGlobalSearchSelected(index);
	        });
	        button.addEventListener("click", () => openGlobalSearchResult(item));
	        box.appendChild(button);
	      }
	      queueLucideRefresh();
	      scrollSelectedGlobalSearchIntoView();
	    }

	    function scrollSelectedGlobalSearchIntoView() {
	      const selected = $("globalSearchResults")?.querySelector(".global-search-item.active");
	      if (selected) selected.scrollIntoView({ block: "nearest" });
	    }

	    function setGlobalSearchSelected(index) {
	      if (!state.globalSearchResults.length) return;
	      state.globalSearchSelected = clampNumber(index, 0, state.globalSearchResults.length - 1, 0);
	      const items = $("globalSearchResults")?.querySelectorAll(".global-search-item") || [];
	      items.forEach((node, itemIndex) => {
	        const active = itemIndex === state.globalSearchSelected;
	        node.classList.toggle("active", active);
	        node.setAttribute("aria-selected", active ? "true" : "false");
	      });
	      scrollSelectedGlobalSearchIntoView();
	    }

	    function moveGlobalSearchSelection(delta) {
	      if (!state.globalSearchResults.length) return;
	      const length = state.globalSearchResults.length;
	      setGlobalSearchSelected((state.globalSearchSelected + delta + length) % length);
	    }

	    function handleGlobalSearchKeydown(event) {
	      if (event.key === "Escape") {
	        event.preventDefault();
	        closeGlobalSearch();
	        return;
	      }
	      if (event.key === "ArrowDown") {
	        event.preventDefault();
	        moveGlobalSearchSelection(1);
	        return;
	      }
	      if (event.key === "ArrowUp") {
	        event.preventDefault();
	        moveGlobalSearchSelection(-1);
	        return;
	      }
	      if (event.key === "Home") {
	        event.preventDefault();
	        setGlobalSearchSelected(0);
	        return;
	      }
	      if (event.key === "End") {
	        event.preventDefault();
	        setGlobalSearchSelected(Math.max(0, state.globalSearchResults.length - 1));
	        return;
	      }
	      if (event.key === "Enter") {
	        event.preventDefault();
	        const item = state.globalSearchResults[state.globalSearchSelected];
	        if (item) openGlobalSearchResult(item);
	      }
	    }

	    async function openGlobalSearchResult(item) {
	      if (!item) return;
	      closeGlobalSearch();
	      const sessionId = item.session_id || "";
	      if (sessionId) {
	        if (!state.conversations.some((conv) => conv.id === sessionId)) {
	          await loadConversations();
	        }
	        await selectConversation(sessionId, { messageId: item.message_id });
	        return;
	      }
	      if (item.type === "favorite") {
	        const favoriteId = String(item.id || "").replace(/^favorite:/, "");
	        await openFavorites();
	        state.selectedFavoriteId = Number(favoriteId || 0) || null;
	        renderFavorites();
	        setStatus("chatStatus", "原会话已删除，已打开收藏内容。", "");
	        return;
	      }
	      if (item.type === "media") {
	        const taskId = String(item.id || "").replace(/^media:/, "");
	        await openMediaAnalysis();
	        state.selectedMediaTaskId = taskId;
	        renderMediaTasks();
	        renderMediaDetail();
	        return;
	      }
	      setStatus("chatStatus", "这条结果暂时无法直接打开。", "err");
	    }

	    function renderInlineMarkdown(value) {
	      const placeholders = [];
	      let text = String(value || "").replace(/`([^`\n]+)`/g, (_, code) => {
	        const token = "\u0000" + placeholders.length + "\u0000";
	        placeholders.push("<code>" + escapeHTML(code) + "</code>");
	        return token;
	      });
	      let html = escapeHTML(text);
	      html = html.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, (_, alt, href) => {
	        const src = safeHref(href);
	        if (src === "#") return escapeHTML(alt || "");
	        return '<span class="media-wrapper"><img src="' + escapeHTML(src) + '" alt="' + alt + '" loading="lazy"></span>';
	      });
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
	            '<div class="table-wrapper" role="region" aria-label="表格，可左右滑动查看"><table><thead><tr>' +
	            headers.map((cell) => "<th>" + renderInlineMarkdown(cell) + "</th>").join("") +
	            "</tr></thead><tbody>" +
	            rows.map((row) => "<tr>" + row.map((cell) => "<td>" + renderInlineMarkdown(cell) + "</td>").join("") + "</tr>").join("") +
	            '</tbody></table><span class="table-scroll-hint">← 左右滑动查看 →</span></div>'
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

	    function refreshMarkdownOverflow(root = document) {
	      const scope = root || document;
	      scope.querySelectorAll(".table-wrapper").forEach((wrapper) => {
	        const table = wrapper.querySelector("table");
	        const overflowing = Boolean(table && table.scrollWidth > wrapper.clientWidth + 2);
	        wrapper.classList.toggle("is-overflowing", overflowing);
	        wrapper.classList.toggle("is-scrolled", wrapper.scrollLeft > 8);
	        if (!wrapper.dataset.scrollHintBound) {
	          wrapper.dataset.scrollHintBound = "1";
	          wrapper.addEventListener("scroll", () => {
	            wrapper.classList.toggle("is-scrolled", wrapper.scrollLeft > 8);
	          }, { passive: true });
	        }
	      });
	    }

	    function queueMarkdownOverflowRefresh(root = document) {
	      requestAnimationFrame(() => refreshMarkdownOverflow(root));
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

	    function renderReasoningPanel(panel, message, reasoningContent) {
	      if (!panel) return;
	      if (message.role !== "assistant" || !reasoningContent) {
	        panel.hidden = true;
	        panel.replaceChildren();
	        return;
	      }
	      panel.hidden = false;
	      panel.classList.toggle("open", Boolean(message.reasoning_open));
	      const toggle = document.createElement("button");
	      toggle.className = "reasoning-toggle";
	      toggle.type = "button";
	      const toggleLabel = message.reasoning_open ? "收起思考过程" : (message.thinking ? "槑槑正在思考" : "查看思考过程");
	      toggle.innerHTML = iconLabel(message.thinking ? "loader" : "brain", toggleLabel, "思");
	      toggle.title = message.reasoning_open ? "收起思考过程" : "展开思考过程";
	      toggle.addEventListener("click", () => toggleReasoning(message));
	      const body = document.createElement("div");
	      body.className = "reasoning-body";
	      body.hidden = !message.reasoning_open;
	      body.innerHTML = '<div class="markdown">' + renderMarkdown(reasoningContent) + '</div>';
	      panel.replaceChildren(toggle, body);
	      queueMarkdownOverflowRefresh(body);
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

	    async function loadConversationStats(id = state.currentConversation?.id) {
	      if (!id) {
	        state.conversationStats = null;
	        updateChatUsage();
	        return;
	      }
	      try {
	        const res = await api(`/api/conversations/${id}/stats`);
	        if (!res.ok) throw new Error(await readError(res, "统计暂时加载失败。"));
	        const data = await res.json();
	        if (state.currentConversation?.id !== id) return;
	        state.conversationStats = data.stats || null;
	      } catch {
	        if (state.currentConversation?.id === id) state.conversationStats = null;
	      }
	      updateChatUsage();
	    }

	    function updateChatUsage() {
	      const el = $("chatUsage");
	      if (!el) return;
	      if (!state.currentConversation) {
	        el.textContent = "";
	        el.title = "";
	        return;
	      }
	      const stats = state.conversationStats || {};
	      const tokens = Math.max(Number(stats.total_tokens || 0), currentConversationTokens());
	      const localTurns = state.messages.filter((item) => item.role === "user").length;
	      const turns = Math.max(Number(stats.turn_count || 0), localTurns);
	      const compactParts = [];
	      if (tokens) compactParts.push(formatTokens(tokens));
	      if (turns) compactParts.push(turns + "轮");
	      const detailParts = [...compactParts];
	      if (stats.web_search_count) detailParts.push(stats.web_search_count + "次联网");
	      if (stats.attachment_count) detailParts.push(stats.attachment_count + "张图片");
	      if (stats.media_task_count) detailParts.push(stats.media_task_count + "个音视频");
	      if (stats.model_code) detailParts.push(stats.model_code);
	      if (stats.updated_at) detailParts.push("更新 " + formatTime(stats.updated_at));
	      const mobile = isSmallScreen();
	      const visibleParts = mobile ? compactParts : detailParts;
	      el.textContent = visibleParts.length ? visibleParts.join(" · ") : "";
	      el.title = detailParts.join(" · ");
	    }

	    function updateFavoriteCount() {
	      const el = $("favoriteCount");
	      if (!el) return;
	      const count = state.favorites.length;
	      el.textContent = String(count);
	      el.hidden = count <= 0;
	    }

	    function minimapAvailable() {
	      return window.matchMedia && window.matchMedia("(min-width: 901px)").matches;
	    }

	    function hideConversationMinimap() {
	      const minimap = $("conversationMinimap");
	      const tooltip = $("minimapTooltip");
	      if (state.minimapFadeTimer) {
	        clearTimeout(state.minimapFadeTimer);
	        state.minimapFadeTimer = 0;
	      }
	      if (state.minimapCollapseTimer) {
	        clearTimeout(state.minimapCollapseTimer);
	        state.minimapCollapseTimer = 0;
	      }
	      if (state.minimapTooltipTimer) {
	        clearTimeout(state.minimapTooltipTimer);
	        state.minimapTooltipTimer = 0;
	      }
	      if (minimap) {
	        minimap.hidden = true;
	        minimap.classList.remove("is-scrolling", "is-expanded");
	      }
	      if (tooltip) tooltip.classList.remove("show");
	    }

	    function expandConversationMinimap() {
	      const minimap = $("conversationMinimap");
	      if (!minimap || minimap.hidden) return;
	      if (state.minimapCollapseTimer) {
	        clearTimeout(state.minimapCollapseTimer);
	        state.minimapCollapseTimer = 0;
	      }
	      minimap.classList.add("is-expanded");
	    }

	    function scheduleCollapseConversationMinimap() {
	      const minimap = $("conversationMinimap");
	      if (!minimap || minimap.hidden) return;
	      if (state.minimapCollapseTimer) clearTimeout(state.minimapCollapseTimer);
	      state.minimapCollapseTimer = window.setTimeout(() => {
	        minimap.classList.remove("is-expanded");
	        hideMinimapTooltip(true);
	        state.minimapCollapseTimer = 0;
	      }, 300);
	    }

	    function handleMinimapOutsidePointer(event) {
	      const minimap = $("conversationMinimap");
	      if (!minimap || minimap.hidden || !minimap.classList.contains("is-expanded")) return;
	      if (minimap.contains(event.target)) return;
	      const active = document.activeElement;
	      if (active && minimap.contains(active) && typeof active.blur === "function") active.blur();
	      scheduleCollapseConversationMinimap();
	    }

	    function pulseConversationMinimap() {
	      const minimap = $("conversationMinimap");
	      if (!minimap || minimap.hidden) return;
	      minimap.classList.add("is-scrolling");
	      if (state.minimapFadeTimer) clearTimeout(state.minimapFadeTimer);
	      state.minimapFadeTimer = window.setTimeout(() => {
	        minimap.classList.remove("is-scrolling");
	        state.minimapFadeTimer = 0;
	      }, 820);
	    }

	    function messageMinimapFlags(message) {
	      const content = String(message?.content || "");
	      const sources = Array.isArray(message?.sources) ? message.sources : [];
	      const images = messageImages(message);
	      return {
	        search: sources.length > 0 || /联网搜索|参考来源|搜索结果/i.test(content),
	        media: /ai-meimei-media-task|音视频分析|通义听悟|转写全文|智能摘要/i.test(content),
	        image: images.length > 0,
	        attachment: images.length > 0 || /附件|文件|图片/i.test(content),
	        favorite: Boolean(message?.favorite_id)
	      };
	    }

	    function messageMinimapTitle(message, flags) {
	      const base = message?.role === "user" ? "用户" : (message?.role === "assistant" ? "槑槑" : "系统");
	      const tags = [];
	      if (flags.search) tags.push("联网搜索");
	      if (flags.media) tags.push("音视频分析");
	      if (flags.image) tags.push("图片");
	      else if (flags.attachment) tags.push("附件");
	      if (flags.favorite) tags.push("已收藏");
	      return tags.length ? base + " · " + tags.join(" · ") : base;
	    }

	    function messageMinimapSummary(message) {
	      const text = visibleMessageContent(message)
	        .replace(/[#>*_`\[\]()]/g, "")
	        .replace(/\s+/g, " ")
	        .trim();
	      if (text) return text.slice(0, 60);
	      if (messageImages(message).length) return "图片消息";
	      if (message?.thinking) return "槑槑正在整理思路...";
	      return "暂无可预览内容";
	    }

	    function minimapMarkerClass(message, flags) {
	      const classes = ["minimap-marker", "is-" + (message?.role || "system")];
	      if (flags.search) classes.push("has-search");
	      if (flags.media) classes.push("has-media");
	      if (flags.image) classes.push("has-image");
	      if (flags.attachment) classes.push("has-attachment");
	      if (flags.favorite) classes.push("has-favorite");
	      return classes.join(" ");
	    }

	    function showMinimapTooltip(message, marker, event) {
	      const tooltip = $("minimapTooltip");
	      const minimap = $("conversationMinimap");
	      if (!tooltip || !minimap || !marker) return;
	      expandConversationMinimap();
	      if (state.minimapTooltipTimer) {
	        clearTimeout(state.minimapTooltipTimer);
	        state.minimapTooltipTimer = 0;
	      }
	      const flags = messageMinimapFlags(message);
	      const tokens = messageTotalTokens(message);
	      const meta = [formatMessageTime(message?.created_at)];
	      if (tokens) meta.push(formatTokens(tokens));
	      tooltip.innerHTML =
	        "<strong>" + escapeHTML(messageMinimapTitle(message, flags)) + "</strong>" +
	        "<span>" + escapeHTML(meta.filter(Boolean).join(" · ")) + "</span>" +
	        "<p>" + escapeHTML(messageMinimapSummary(message)) + "</p>";
	      const pointerY = event?.clientY ? event.clientY - minimap.getBoundingClientRect().top : marker.offsetTop + marker.offsetHeight / 2;
	      const y = clampNumber(pointerY, 34, Math.max(34, minimap.clientHeight - 34), 34);
	      tooltip.style.top = y + "px";
	      tooltip.classList.add("show");
	    }

	    function hideMinimapTooltip(immediate = false) {
	      const tooltip = $("minimapTooltip");
	      if (!tooltip) return;
	      if (state.minimapTooltipTimer) clearTimeout(state.minimapTooltipTimer);
	      if (immediate) {
	        tooltip.classList.remove("show");
	        state.minimapTooltipTimer = 0;
	        return;
	      }
	      state.minimapTooltipTimer = window.setTimeout(() => {
	        tooltip.classList.remove("show");
	        state.minimapTooltipTimer = 0;
	      }, 120);
	    }

	    function updateConversationMinimapViewport() {
	      const box = $("messages");
	      const track = $("minimapTrack");
	      const viewport = $("minimapViewport");
	      const minimap = $("conversationMinimap");
	      if (!box || !track || !viewport || !minimap || minimap.hidden) return;
	      const trackHeight = track.clientHeight;
	      const scrollHeight = Math.max(box.scrollHeight, box.clientHeight, 1);
	      const height = clampNumber((box.clientHeight / scrollHeight) * trackHeight, 18, trackHeight, trackHeight);
	      const top = clampNumber((box.scrollTop / scrollHeight) * trackHeight, 0, Math.max(0, trackHeight - height), 0);
	      viewport.style.height = height + "px";
	      viewport.style.top = top + "px";
	    }

	    function scrollToMinimapMessage(message, behavior = "smooth") {
	      const box = $("messages");
	      const wrap = box?.querySelector(`[data-message-key="${messageKey(message)}"]`);
	      if (!box || !wrap) return;
	      const target = clampNumber(
	        wrap.offsetTop - Math.max(36, (box.clientHeight - wrap.offsetHeight) / 2),
	        0,
	        Math.max(0, box.scrollHeight - box.clientHeight),
	        0
	      );
	      state.programmaticScroll = true;
	      box.scrollTo({ top: target, behavior });
	      pulseConversationMinimap();
	      setTimeout(() => {
	        state.programmaticScroll = false;
	        handleMessagesScroll();
	      }, behavior === "smooth" ? 520 : 0);
	      updateConversationMinimapViewport();
	    }

	    function renderConversationMinimap() {
	      const minimap = $("conversationMinimap");
	      const track = $("minimapTrack");
	      const viewport = $("minimapViewport");
	      const box = $("messages");
	      if (!minimap || !track || !viewport || !box) return;
	      track.querySelectorAll(".minimap-marker").forEach((node) => node.remove());
	      if (!minimapAvailable() || !state.messages.length) {
	        hideConversationMinimap();
	        return;
	      }
	      minimap.hidden = false;
	      const scrollHeight = Math.max(box.scrollHeight, box.clientHeight, 1);
	      const trackHeight = track.clientHeight;
	      if (!trackHeight || !scrollHeight) {
	        hideConversationMinimap();
	        return;
	      }
	      for (const message of state.messages) {
	        const wrap = box.querySelector(`[data-message-key="${messageKey(message)}"]`);
	        if (!wrap) continue;
	        const flags = messageMinimapFlags(message);
	        const marker = document.createElement("button");
	        marker.type = "button";
	        marker.className = minimapMarkerClass(message, flags);
	        marker.setAttribute("aria-label", messageMinimapTitle(message, flags));
	        marker.style.top = clampNumber((wrap.offsetTop / scrollHeight) * trackHeight, 0, trackHeight - 2, 0) + "px";
	        const rawHeight = (Math.max(wrap.offsetHeight, 24) / scrollHeight) * trackHeight;
	        const minHeight = 2;
	        marker.style.height = clampNumber(rawHeight, minHeight, Math.max(minHeight, Math.min(28, trackHeight)), minHeight) + "px";
	        marker.addEventListener("click", (event) => {
	          event.preventDefault();
	          scrollToMinimapMessage(message, "smooth");
	        });
	        marker.addEventListener("pointerenter", (event) => showMinimapTooltip(message, marker, event));
	        marker.addEventListener("pointermove", (event) => showMinimapTooltip(message, marker, event));
	        marker.addEventListener("pointerleave", hideMinimapTooltip);
	        marker.addEventListener("focus", () => showMinimapTooltip(message, marker));
	        marker.addEventListener("blur", hideMinimapTooltip);
	        track.appendChild(marker);
	      }
	      updateConversationMinimapViewport();
	    }

	    function queueConversationMinimap() {
	      if (state.minimapQueued) return;
	      state.minimapQueued = true;
	      requestAnimationFrame(() => {
	        state.minimapQueued = false;
	        renderConversationMinimap();
	      });
	    }

	    function isNearBottom(box = $("messages")) {
	      return box.scrollHeight - box.scrollTop - box.clientHeight < 96;
	    }

	    function updateScrollLatestButton() {
	      const button = $("scrollLatest");
	      if (!button) return;
	      const awayFromBottom = !isNearBottom();
	      const label = state.hasNewWhilePaused || state.sending ? "查看新内容" : "回到底部";
	      button.title = label;
	      button.setAttribute("aria-label", label);
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
	      updateConversationMinimapViewport();
	      pulseConversationMinimap();
	    }

	    function selectionNodeInside(node, root) {
	      if (!node || !root) return false;
	      const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
	      return Boolean(element && root.contains(element));
	    }

	    function editableSelectionNode(node) {
	      const element = node?.nodeType === Node.ELEMENT_NODE ? node : node?.parentElement;
	      return Boolean(element?.closest("textarea, input, [contenteditable='true']"));
	    }

	    function lastMessageSelectionBoundary() {
	      const box = $("messages");
	      if (!box) return null;
	      const messages = box.querySelectorAll(".bubble");
	      return messages.length ? messages[messages.length - 1] : null;
	    }

	    function clampChatSelectionToMessages() {
	      if (!state.chatSelectionActive && !state.chatSelectionStartedInMessages) return;
	      const selection = window.getSelection?.();
	      if (!selection || selection.rangeCount === 0 || selection.isCollapsed) return;
	      const box = $("messages");
	      const composer = document.querySelector(".composer");
	      const latest = $("scrollLatest");
	      const anchorInMessages = selectionNodeInside(selection.anchorNode, box);
	      const focusInMessages = selectionNodeInside(selection.focusNode, box);
	      if (!anchorInMessages || focusInMessages) return;
	      const focusInBlockedArea =
	        selectionNodeInside(selection.focusNode, composer) ||
	        selectionNodeInside(selection.focusNode, latest) ||
	        !focusInMessages;
	      if (!focusInBlockedArea) return;
	      const boundary = lastMessageSelectionBoundary();
	      if (!boundary) return;
	      const range = document.createRange();
	      try {
	        range.setStart(selection.anchorNode, selection.anchorOffset);
	        range.setEndAfter(boundary);
	        selection.removeAllRanges();
	        selection.addRange(range);
	      } catch {}
	    }

	    function beginChatTextSelection(event) {
	      if (event.button !== undefined && event.button !== 0) return;
	      if (editableSelectionNode(event.target)) return;
	      if (!selectionNodeInside(event.target, $("messages"))) return;
	      state.chatSelectionActive = true;
	      state.chatSelectionStartedInMessages = true;
	    }

	    function endChatTextSelection() {
	      if (!state.chatSelectionStartedInMessages) return;
	      clampChatSelectionToMessages();
	      setTimeout(() => {
	        state.chatSelectionActive = false;
	        state.chatSelectionStartedInMessages = false;
	      }, 80);
	    }

	    function handleComposerSelectStart(event) {
	      if (event.target === $("prompt")) return;
	      event.preventDefault();
	      if (state.chatSelectionStartedInMessages) clampChatSelectionToMessages();
	    }

	    function handleSelectionChange() {
	      clampChatSelectionToMessages();
	    }

	    function handleMessagesScroll() {
	      updateConversationMinimapViewport();
	      pulseConversationMinimap();
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
	      const imagePanel = document.createElement("div");
	      imagePanel.className = "message-images";
	      imagePanel.hidden = true;
	      const copy = document.createElement("button");
	      copy.className = "copy-btn";
	      copy.type = "button";
	      copy.title = "复制";
	      copy.innerHTML = '<i data-lucide="copy" aria-hidden="true"></i><span class="icon-fallback">⧉</span>';
	      copy.addEventListener("click", () => copyText(visibleMessageContent(message), copy));
	      const copyAction = document.createElement("button");
	      copyAction.className = "message-action copy-action";
	      copyAction.type = "button";
	      copyAction.innerHTML = '<i data-lucide="copy" aria-hidden="true"></i><span class="icon-fallback">⧉</span>';
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
	      regenerate.innerHTML = iconLabel("rotate-cw", "重新生成", "↻");
	      regenerate.title = "把上一条问题放回输入框";
	      regenerate.addEventListener("click", () => regenerateFromMessage(message));
	      const continueWrite = document.createElement("button");
	      continueWrite.className = "message-action continue-action";
	      continueWrite.type = "button";
	      continueWrite.innerHTML = iconLabel("pen-line", "继续写", "✎");
	      continueWrite.title = "基于这条回答继续写";
	      continueWrite.addEventListener("click", () => continueFromMessage(message));
	      const reason = document.createElement("button");
	      reason.className = "message-action reason-action";
	      reason.type = "button";
	      reason.addEventListener("click", () => toggleReasoning(message));
	      actions.append(favorite, regenerate, continueWrite, copyAction);

	      shell.append(reasoningPanel, imagePanel, text, copy);
	      wrap.append(role, shell, sourcesPanel, time, actions);
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
	      const imagePanel = wrap.querySelector(".message-images");
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

	      const displayContent = visibleMessageContent(message);
	      const reasoningContent = messageReasoningContent(message);
	      renderReasoningPanel(reasoningPanel, message, reasoningContent);
	      renderMessageImages(imagePanel, messageImages(message));

	      if (message.role === "assistant" && message.thinking && !displayContent) {
	        text.className = "message-content";
	        text.innerHTML = `
	          <div class="thinking">
	            <img class="thinking-avatar" src="/res/meimei-avatar.png" alt="">
	            <span class="thinking-dots"><span></span><span></span><span></span></span>
	            <span><strong>槑槑</strong>正在整理思路...</span>
	          </div>`;
	        if (imagePanel) imagePanel.hidden = true;
	        copy.hidden = true;
	        if (actions) actions.hidden = true;
	        return;
	      }

	      text.className = "message-content markdown";
	      text.innerHTML = renderMarkdown(displayContent || "");
	      queueMarkdownOverflowRefresh(text);
	      copy.hidden = !displayContent || message.role === "assistant";
	      const canShowAssistantActions = message.role === "assistant" && Boolean(displayContent);
	      const canShowUserActions = message.role === "user" && displayContent;
	      if (actions) actions.hidden = !(canShowAssistantActions || canShowUserActions);
	      if (copyAction) {
	        copyAction.hidden = !((message.role === "assistant" || message.role === "user") && displayContent);
	        copyAction.title = message.role === "assistant" ? "复制这条回答" : "复制这条消息";
	      }
	      if (reason) reason.hidden = true;
	      if (favorite) {
	        favorite.hidden = !(message.role === "assistant" && message.id && displayContent);
	        favorite.innerHTML = message.favorite_id ? iconLabel("star", "已收藏", "★") : iconLabel("star", "收藏", "☆");
	        favorite.classList.toggle("active", Boolean(message.favorite_id));
	        favorite.title = message.favorite_id ? "取消收藏" : "收藏这条回答";
	      }
	      if (regenerate) {
	        regenerate.hidden = !(message.role === "assistant" && displayContent);
	      }
	      if (continueWrite) {
	        continueWrite.hidden = !(message.role === "assistant" && displayContent);
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
	      queueLucideRefresh();
	      queueConversationMinimap();
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
	        hideConversationMinimap();
	        return;
	      }
	      const fragment = document.createDocumentFragment();
	      for (const msg of state.messages) {
	        fragment.appendChild(createMessageElement(msg));
	      }
	      box.replaceChildren(fragment);
	      settleMessageScroll(previousTop, shouldFollow);
	      updateChatUsage();
	      queueLucideRefresh();
	      queueConversationMinimap();
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

	    function safeImageFilename(name) {
	      return String(name || "image").replace(/[\\/]+/g, "_").replace(/[^\w.\-\u4e00-\u9fa5]+/g, "_").slice(0, 120);
	    }

	    function attachmentClientId() {
	      if (window.crypto?.randomUUID) return window.crypto.randomUUID();
	      return "img_" + Date.now() + "_" + Math.random().toString(36).slice(2, 8);
	    }

	    function imageDisplayUrl(image) {
	      return image?.preview_url || image?.view_url || image?.oss_url || image?.image_url || "";
	    }

	    function messageImages(message) {
	      return Array.isArray(message?.images) ? message.images : [];
	    }

	    function renderMessageImages(container, images = []) {
	      if (!container) return;
	      container.replaceChildren();
	      container.hidden = !images.length;
	      for (const image of images) {
	        const url = imageDisplayUrl(image);
	        if (!url) continue;
	        const button = document.createElement("button");
	        button.className = "message-image-btn";
	        button.type = "button";
	        button.title = image.filename || "查看图片";
	        const img = document.createElement("img");
	        img.src = url;
	        img.alt = image.filename || "聊天图片";
	        img.loading = "lazy";
	        img.addEventListener("load", queueConversationMinimap, { once: true });
	        button.appendChild(img);
	        button.addEventListener("click", () => openImagePreview(url));
	        container.appendChild(button);
	      }
	      container.hidden = !container.children.length;
	    }

	    function renderAttachmentPreviews() {
	      const row = $("attachmentPreviewRow");
	      if (!row) return;
	      row.replaceChildren();
	      row.hidden = !state.attachments.length;
	      for (const item of state.attachments) {
	        const card = document.createElement("div");
	        card.className = "attachment-preview" + (item.status === "uploading" ? " is-uploading" : "") + (item.status === "error" ? " is-error" : "");
	        card.title = item.filename || "图片";
	        const img = document.createElement("img");
	        img.src = item.preview_url || item.view_url || "";
	        img.alt = item.filename || "待发送图片";
	        card.appendChild(img);
	        if (item.status === "uploading" || item.status === "error" || item.justUploaded) {
	          const ring = document.createElement("div");
	          ring.className = "attachment-ring";
	          ring.style.setProperty("--progress", String(item.status === "error" ? 100 : Math.max(0, Math.min(100, Number(item.progress || 0)))));
	          ring.textContent = item.status === "error" ? "!" : (item.progress >= 100 ? "✓" : Math.round(item.progress || 0) + "%");
	          card.appendChild(ring);
	        }
		        const remove = document.createElement("button");
		        remove.className = "attachment-remove ui-icon-btn";
		        remove.type = "button";
		        remove.title = "移除图片";
		        remove.innerHTML = '<i data-lucide="x" aria-hidden="true"></i><span class="icon-fallback">×</span>';
		        remove.addEventListener("click", () => removeAttachment(item.client_id));
		        card.appendChild(remove);
	        if (item.status !== "ready") {
	          const status = document.createElement("div");
	          status.className = "attachment-progress";
	          status.textContent = item.status === "error" ? "上传失败" : "上传中";
	          card.appendChild(status);
	        }
		        row.appendChild(card);
		      }
		      queueLucideRefresh();
		    }

	    function removeAttachment(clientId) {
	      const item = state.attachments.find((entry) => entry.client_id === clientId);
	      if (item?.preview_url) URL.revokeObjectURL(item.preview_url);
	      state.attachments = state.attachments.filter((entry) => entry.client_id !== clientId);
	      renderAttachmentPreviews();
	      updateVisionUI();
	    }

	    function clearAttachments() {
	      for (const item of state.attachments) {
	        if (item.preview_url) URL.revokeObjectURL(item.preview_url);
	      }
	      state.attachments = [];
	      renderAttachmentPreviews();
	      updateVisionUI();
	    }

	    function openImagePreview(url) {
	      if (!url) return;
	      $("imagePreviewFull").src = url;
	      $("imagePreviewDialog").classList.add("show");
	      setDialogOpenState();
	    }

	    function closeImagePreview() {
	      $("imagePreviewDialog").classList.remove("show");
	      $("imagePreviewFull").src = "";
	      setDialogOpenState();
	    }

	    function uploadFormWithProgress(url, form, onProgress) {
	      return new Promise((resolve, reject) => {
	        const xhr = new XMLHttpRequest();
	        xhr.open("POST", url);
	        xhr.upload.onprogress = (event) => {
	          if (!event.lengthComputable) return;
	          const percent = Math.max(1, Math.min(96, Math.round((event.loaded / event.total) * 96)));
	          onProgress(percent);
	        };
	        xhr.onload = () => {
	          if (xhr.status >= 200 && xhr.status < 300) {
	            onProgress(98);
	            resolve(xhr);
	          } else {
	            reject(new Error("图片上传 OSS 失败"));
	          }
	        };
	        xhr.onerror = () => reject(new Error("图片上传 OSS 失败"));
	        xhr.ontimeout = () => reject(new Error("图片上传超时"));
	        xhr.timeout = 120000;
	        xhr.send(form);
	      });
	    }

	    async function uploadChatImageAttachment(item) {
	      const policyRes = await api("/api/chat-images/upload-policy", { method: "POST" });
	      if (!policyRes.ok) throw new Error(await readError(policyRes, "图片上传配置不可用。"));
	      const { policy } = await policyRes.json();
	      if (item.file.size > policy.max_size) throw new Error("单张图片不能超过 20MB");
	      const key = policy.key_prefix + Date.now() + "-" + Math.random().toString(36).slice(2, 8) + "-" + safeImageFilename(item.file.name);
	      const form = new FormData();
	      form.append("key", key);
	      form.append("OSSAccessKeyId", policy.access_key_id);
	      form.append("policy", policy.policy);
	      form.append("Signature", policy.signature);
	      form.append("success_action_status", "200");
	      form.append("Content-Type", item.file.type || "application/octet-stream");
	      form.append("file", item.file);
	      await uploadFormWithProgress(policy.host, form, (progress) => {
	        item.progress = progress;
	        renderAttachmentPreviews();
	      });
	      const saveRes = await api("/api/chat-images", {
	        method: "POST",
	        body: JSON.stringify({
	          filename: item.file.name,
	          mime_type: item.file.type || "",
	          file_size: item.file.size,
	          oss_key: key
	        })
	      });
	      if (!saveRes.ok) throw new Error(await readError(saveRes, "图片信息保存失败。"));
	      const data = await saveRes.json();
	      item.progress = 100;
	      return data.image;
	    }

	    async function handleImageFiles(fileList) {
	      const input = $("imageInput");
	      const files = Array.from(fileList || []);
	      if (input) input.value = "";
	      if (!files.length) return;
	      if (!selectedModelSupportsVision()) {
	        setStatus("chatStatus", "当前模型不支持图片理解，请切换支持图片的模型。", "err");
	        return;
	      }
	      if (state.attachments.length + files.length > 5) {
	        setStatus("chatStatus", "单次最多上传 5 张图片。", "err");
	        return;
	      }
	      const allowedTypes = new Set(["image/jpeg", "image/png", "image/webp"]);
	      const allowedExts = [".jpg", ".jpeg", ".png", ".webp"];
	      const items = [];
	      for (const file of files) {
	        const lowerName = file.name.toLowerCase();
	        const extOk = allowedExts.some((ext) => lowerName.endsWith(ext));
	        if (!allowedTypes.has(file.type) && !extOk) {
	          setStatus("chatStatus", "只支持 jpg、jpeg、png、webp 图片。", "err");
	          return;
	        }
	        if (file.size > 20 * 1024 * 1024) {
	          setStatus("chatStatus", "单张图片不能超过 20MB。", "err");
	          return;
	        }
	        items.push({
	          client_id: attachmentClientId(),
	          file,
	          filename: file.name,
	          preview_url: URL.createObjectURL(file),
	          progress: 1,
	          status: "uploading"
	        });
	      }
	      state.attachments.push(...items);
	      state.uploadingImages = true;
	      updateVisionUI();
	      renderAttachmentPreviews();
	      setStatus("chatStatus", "正在上传图片...", "");
	      try {
	        for (const item of items) {
	          try {
	            const image = await uploadChatImageAttachment(item);
	            item.id = image.id;
	            item.view_url = image.view_url;
	            item.filename = image.filename || item.filename;
	            item.progress = 100;
	            item.status = "ready";
	            item.justUploaded = true;
	            setTimeout(() => {
	              item.justUploaded = false;
	              renderAttachmentPreviews();
	            }, 650);
	          } catch (err) {
	            item.status = "error";
	            item.progress = 100;
	            item.error = friendlyError(err, "图片上传失败。");
	          }
	          renderAttachmentPreviews();
	        }
	        const failed = items.filter((item) => item.status === "error");
	        if (failed.length) {
	          setStatus("chatStatus", failed[0].error || "有图片上传失败，请移除后重试。", "err");
	        } else {
	          setStatus("chatStatus", "图片已添加，输入问题后发送。", "ok");
	        }
	      } finally {
	        state.uploadingImages = false;
	        updateVisionUI();
	      }
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
	      const secondary = $("secondaryConfirm");
	      $("confirmTitle").textContent = options.title || "确认操作";
	      $("confirmMessage").textContent = options.message || "确定要继续吗？";
	      ok.textContent = options.confirmText || "确定";
	      cancel.textContent = options.cancelText || "取消";
	      secondary.textContent = options.secondaryText || "";
	      secondary.hidden = !options.secondaryText;
	      ok.classList.toggle("danger", Boolean(options.danger));
	      secondary.classList.toggle("danger", Boolean(options.secondaryDanger));
	      dialog.classList.add("show");
	      setDialogOpenState();
	      return new Promise((resolve) => {
	        function cleanup(result) {
	          dialog.classList.remove("show");
	          setDialogOpenState();
	          ok.removeEventListener("click", onOk);
	          cancel.removeEventListener("click", onCancel);
	          secondary.removeEventListener("click", onSecondary);
	          dialog.removeEventListener("click", onBackdrop);
	          document.removeEventListener("keydown", onKey);
	          secondary.hidden = true;
	          secondary.classList.remove("danger");
	          resolve(result);
	        }
	        function onOk() { cleanup(true); }
	        function onCancel() { cleanup(false); }
	        function onSecondary() { cleanup("secondary"); }
	        function onBackdrop(event) {
	          if (event.target === dialog) cleanup(false);
	        }
	        function onKey(event) {
	          if (event.key === "Escape") cleanup(false);
	        }
	        ok.addEventListener("click", onOk);
	        cancel.addEventListener("click", onCancel);
	        secondary.addEventListener("click", onSecondary);
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
	      updateVisionUI();
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
	      const readyAttachments = hasOverride ? [] : state.attachments.filter((item) => item.status === "ready" && item.id);
	      const failedAttachments = hasOverride ? [] : state.attachments.filter((item) => item.status === "error");
	      const uploadingAttachments = hasOverride ? [] : state.attachments.filter((item) => item.status === "uploading");
	      if (state.sending) return;
	      if (!content && !readyAttachments.length) {
	        if (state.uploadingImages || uploadingAttachments.length) setStatus("chatStatus", "图片还在上传，稍等一下再发送。", "err");
	        else if (failedAttachments.length) setStatus("chatStatus", "有图片上传失败，请移除后重试。", "err");
	        return;
	      }
	      if (state.uploadingImages || uploadingAttachments.length) {
	        setStatus("chatStatus", "图片还在上传，稍等一下再发送。", "err");
	        return;
	      }
	      if (failedAttachments.length) {
	        setStatus("chatStatus", "有图片上传失败，请移除后重试。", "err");
	        return;
	      }
	      if (readyAttachments.length && !selectedModelSupportsVision()) {
	        setStatus("chatStatus", "当前模型不支持图片理解，请切换支持图片的模型。", "err");
	        return;
	      }
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

	      if (!state.currentConversation) {
	        try {
	          await newConversation(selectedModelId);
	        } catch (err) {
	          setStatus("chatStatus", friendlyError(err, "新建对话失败，稍后再试一下。"), "err");
	          return;
	        }
	      } else if (state.currentConversation.model_id !== selectedModelId) {
	        const switched = await updateCurrentConversationModel(selectedModelId);
	        if (!switched) return;
	      }
	      if (!state.currentConversation) return;
	      if (readyAttachments.length && !state.currentConversation.supports_vision) {
	        setStatus("chatStatus", "当前模型不支持图片理解，请切换支持图片的模型。", "err");
	        return;
	      }

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
	      const sentImages = readyAttachments.map((item) => ({
	        id: item.id,
	        filename: item.filename,
	        view_url: item.view_url,
	        mime_type: item.mime_type || item.file?.type || "",
	        file_size: item.file_size || item.file?.size || 0
	      }));
	      if (!hasOverride) clearAttachments();
	      const userContent = content || "请分析这些图片。";
	      state.messages.push({ role: "user", content: userContent, images: sentImages, created_at: sentAt });
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
	        const useProfile = !profileDisabledForConversation(state.currentConversation.id);
	        const res = await api(`/api/conversations/${state.currentConversation.id}/messages`, {
	          method: "POST",
	          body: JSON.stringify({ content, web_search: useWebSearch, use_profile: useProfile, image_ids: readyAttachments.map((item) => item.id) }),
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
	        await loadConversationStats(state.currentConversation?.id);
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
	      loadAdminUsers();
	      loadTokenStats();
	    }

    function closeSettings() {
      $("drawerMask").classList.remove("show");
      $("settingsDrawer").classList.remove("show");
    }

		    async function loadAdminModels() {
		      if (!hasAdminAccess()) {
		        setStatus("adminStatus", "管理员账号或管理密钥可加载模型", "");
		        $("adminModelList").innerHTML = "";
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
		      if (!hasAdminAccess()) {
		        setStatus("searchStatus", "管理员账号或管理密钥可加载搜索配置", "");
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

	    function tokenNumber(value) {
	      return Number(value || 0).toLocaleString();
	    }

	    function renderTokenSummary(summary = {}) {
	      const box = $("tokenSummaryGrid");
	      if (!box) return;
	      const cards = [
	        ["总用户数", summary.total_users || 0],
	        ["总请求数", summary.total_requests || 0],
	        ["累计输入 Token", summary.prompt_tokens || 0],
	        ["累计输出 Token", summary.completion_tokens || 0],
	        ["累计 Token", summary.total_tokens || 0]
	      ];
	      box.innerHTML = cards.map(([label, value]) => (
	        '<div class="token-summary-card"><span>' + escapeHTML(label) + '</span><strong>' + tokenNumber(value) + '</strong></div>'
	      )).join("");
	    }

	    function scheduleTokenStatsLoad() {
	      clearTimeout(state.tokenStatsTimer);
	      state.tokenStatsTimer = setTimeout(loadTokenStats, 180);
	    }

	    async function loadTokenStats() {
	      const list = $("tokenStatsList");
	      if (!hasAdminAccess()) {
	        if (list) list.innerHTML = '<div class="status">管理员账号或管理密钥可查看 Token 统计。</div>';
	        renderTokenSummary({});
	        setStatus("tokenStatsStatus", "");
	        return;
	      }
	      const query = encodeURIComponent(($("tokenStatsQuery")?.value || "").trim());
	      const sort = encodeURIComponent($("tokenStatsSort")?.value || "tokens");
	      setStatus("tokenStatsStatus", "正在加载 Token 统计...", "");
	      const res = await adminApi(`/api/admin/token-stats?q=${query}&sort=${sort}`);
	      if (!res.ok) {
	        if (list) list.innerHTML = "";
	        renderTokenSummary({});
	        setStatus("tokenStatsStatus", await readError(res, "Token 统计加载失败，稍后再试一下。"), "err");
	        return;
	      }
	      const data = await res.json();
	      state.tokenStats = data;
	      renderTokenSummary(data.summary || {});
	      renderTokenStatsList(data.users || []);
	      setStatus("tokenStatsStatus", data.users?.length ? "" : "没有匹配的账号。", data.users?.length ? "" : "err");
	    }

	    function renderTokenStatsList(users) {
	      const box = $("tokenStatsList");
	      if (!box) return;
	      box.innerHTML = "";
	      if (!users.length) {
	        box.appendChild(createEmptyState("bar-chart-3", "暂无 Token 记录", "有聊天请求后，这里会显示各账号用量。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      for (const user of users) {
	        const row = document.createElement("div");
	        row.className = "model-row token-user-row";
	        const main = document.createElement("div");
	        main.className = "token-user-main";
	        const title = document.createElement("strong");
	        title.textContent = (user.display_name || user.username) + " · " + user.username + (user.is_active ? "" : "（已禁用）");
	        const meta = document.createElement("span");
	        meta.textContent = "注册 " + formatTime(user.created_at) + " · 最后使用 " + (user.last_used_at ? formatTime(user.last_used_at) : "暂无");
	        const stats = document.createElement("div");
	        stats.className = "token-user-stats";
	        stats.innerHTML =
	          '<span>对话 <b>' + tokenNumber(user.conversation_count) + '</b></span>' +
	          '<span>请求 <b>' + tokenNumber(user.request_count) + '</b></span>' +
	          '<span>输入 <b>' + tokenNumber(user.prompt_tokens) + '</b></span>' +
	          '<span>输出 <b>' + tokenNumber(user.completion_tokens) + '</b></span>' +
	          '<span>总计 <b>' + tokenNumber(user.total_tokens) + '</b></span>';
	        main.append(title, meta, stats);
	        const actions = document.createElement("div");
	        actions.className = "library-actions";
	        const expanded = state.tokenStatsExpandedUserId === user.id;
	        const detailBtn = createIconButton(expanded ? "chevron-up" : "chevron-down", expanded ? "收起" : "详情", { fallback: expanded ? "收" : "详" });
	        detailBtn.addEventListener("click", () => {
	          state.tokenStatsExpandedUserId = expanded ? "" : user.id;
	          renderTokenStatsList(state.tokenStats?.users || []);
	        });
	        actions.append(detailBtn);
	        row.append(main, actions);
	        if (expanded) row.appendChild(renderTokenUserDetail(user));
	        box.appendChild(row);
	      }
	      queueLucideRefresh();
	    }

	    function renderTokenUserDetail(user) {
	      const detail = document.createElement("div");
	      detail.className = "token-detail";
	      const rows = user.recent_requests || [];
	      if (!rows.length) {
	        detail.textContent = "最近还没有请求记录。";
	        return detail;
	      }
	      const tableRows = rows.map((item) => {
	        const model = [item.model_name, item.model_code].filter(Boolean).join(" · ") || "-";
	        const web = item.web_search ? "是" : "否";
	        const duration = item.duration_ms ? (Number(item.duration_ms) / 1000).toFixed(1) + "s" : "-";
	        return '<tr>' +
	          '<td>' + escapeHTML(formatTime(item.created_at)) + '</td>' +
	          '<td title="' + escapeHTML(model) + '">' + escapeHTML(model) + '</td>' +
	          '<td>' + tokenNumber(item.prompt_tokens) + '</td>' +
	          '<td>' + tokenNumber(item.completion_tokens) + '</td>' +
	          '<td>' + tokenNumber(item.total_tokens) + '</td>' +
	          '<td>' + escapeHTML(duration) + '</td>' +
	          '<td>' + web + '</td>' +
	        '</tr>';
	      }).join("");
	      detail.innerHTML =
	        '<table><thead><tr><th>时间</th><th>模型</th><th>输入Token</th><th>输出Token</th><th>总Token</th><th>耗时</th><th>联网</th></tr></thead><tbody>' +
	        tableRows +
	        '</tbody></table>';
	      return detail;
	    }

	    function renderAdminModels(models) {
	      const box = $("adminModelList");
	      box.innerHTML = "";
	      if (!models.length) {
	        box.appendChild(createEmptyState("bot", "暂无模型", "添加一个模型后，家人就可以开始使用 AI槑槑。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
      for (const model of models) {
        const row = document.createElement("div");
        row.className = "model-row";
        const info = document.createElement("div");
        info.innerHTML = `<strong></strong><span></span>`;
        info.querySelector("strong").textContent = model.name + (model.enabled ? "" : "（停用）");
        info.querySelector("span").textContent = model.model + (model.supports_vision ? " · 支持图片理解" : "") + " · " + model.base_url + (model.has_api_key ? " · Key 已保存" : " · 未配置 Key");
	        const actions = document.createElement("div");
	        actions.className = "library-actions";
	        const edit = createIconButton("pencil", "编辑", { fallback: "✎" });
	        edit.addEventListener("click", () => fillModelForm(model));
	        const del = createIconButton("trash-2", "删除", { danger: true, fallback: "删" });
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
      $("supportsVision").value = model.supports_vision ? "1" : "0";
      setStatus("modelStatus", "正在编辑：" + model.name, "");
    }

    function resetModelForm() {
      for (const id of ["editingModelId","modelName","provider","baseUrl","modelCode","apiKey","systemPrompt"]) $(id).value = "";
      $("enabled").value = "1";
      $("supportsVision").value = "0";
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
        enabled: $("enabled").value === "1",
        supports_vision: $("supportsVision").value === "1"
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

	    async function loadAdminUsers() {
	      const box = $("accountList");
	      if (!hasAdminAccess()) {
	        box.innerHTML = '<div class="status">管理员账号或管理密钥可管理家庭账号。</div>';
	        setStatus("accountStatus", "");
	        return;
	      }
	      const res = await adminApi("/api/admin/users");
	      if (!res.ok) {
	        box.innerHTML = "";
	        setStatus("accountStatus", await readError(res, "账号列表加载失败。"), "err");
	        return;
	      }
	      const data = await res.json();
	      renderAdminUsers(data.users || []);
	      setStatus("accountStatus", "");
	    }

	    function renderAdminUsers(users) {
	      const box = $("accountList");
	      box.innerHTML = "";
	      if (!users.length) {
	        box.appendChild(createEmptyState("users", "暂无账号", "新增家庭账号后，每个人会看到自己的会话和收藏。", { compact: true }));
	        queueLucideRefresh();
	        return;
	      }
	      for (const user of users) {
	        const row = document.createElement("div");
	        row.className = "model-row";
	        const info = document.createElement("div");
	        info.innerHTML = `<strong></strong><span></span>`;
	        info.querySelector("strong").textContent = (user.display_name || user.username) + (user.is_active ? "" : "（已禁用）");
	        info.querySelector("span").textContent = user.username + " · " + (user.role === "admin" ? "管理员" : "家庭成员") + " · " + formatTime(user.created_at);
		        const actions = document.createElement("div");
		        actions.className = "library-actions";
		        const edit = createIconButton("pencil", "编辑", { fallback: "✎" });
		        edit.addEventListener("click", () => fillAccountForm(user));
	        actions.append(edit);
	        row.append(info, actions);
	        box.appendChild(row);
	      }
	      queueLucideRefresh();
	    }

	    function fillAccountForm(user) {
	      $("editingUserId").value = user.id || "";
	      $("accountUsername").value = user.username || "";
	      $("accountUsername").disabled = true;
	      $("accountDisplayName").value = user.display_name || "";
	      $("accountRole").value = user.role || "family";
	      $("accountActive").value = user.is_active ? "1" : "0";
	      $("accountPassword").value = "";
	      $("accountPassword").placeholder = "留空保持原密码";
	      setStatus("accountStatus", "正在编辑：" + (user.display_name || user.username), "");
	    }

	    function resetAccountForm() {
	      $("editingUserId").value = "";
	      $("accountUsername").value = "";
	      $("accountUsername").disabled = false;
	      $("accountDisplayName").value = "";
	      $("accountRole").value = "family";
	      $("accountActive").value = "1";
	      $("accountPassword").value = "";
	      $("accountPassword").placeholder = "新增账号必填，编辑时留空保持原密码";
	      setStatus("accountStatus", "");
	    }

	    async function saveAccount() {
	      if (!hasAdminAccess()) {
	        setStatus("accountStatus", "需要管理员账号或管理密钥。", "err");
	        return;
	      }
	      const id = $("editingUserId").value;
	      const body = {
	        username: $("accountUsername").value.trim(),
	        display_name: $("accountDisplayName").value.trim(),
	        role: $("accountRole").value,
	        is_active: $("accountActive").value === "1",
	        password: $("accountPassword").value
	      };
	      const res = await adminApi(id ? `/api/admin/users/${id}` : "/api/admin/users", {
	        method: id ? "PUT" : "POST",
	        body: JSON.stringify(body)
	      });
	      if (!res.ok) {
	        setStatus("accountStatus", await readError(res, "账号保存失败，请检查账号和密码。"), "err");
	        return;
	      }
	      resetAccountForm();
	      await loadAdminUsers();
	      setStatus("accountStatus", "账号已保存", "ok");
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
    function insertNewlineAtCursor() {
      const el = $("prompt");
      const start = typeof el.selectionStart === "number" ? el.selectionStart : el.value.length;
      const end = typeof el.selectionEnd === "number" ? el.selectionEnd : el.value.length;
      el.setRangeText("\n", start, end, "end");
      autosizePrompt();
      el.focus();
    }

    $("globalSearchShortcut").textContent = globalSearchShortcutText();
    $("loginForm").addEventListener("submit", login);
    $("logout").addEventListener("click", logout);
    $("newChat").addEventListener("click", () => {
      newConversation().catch((err) => setStatus("chatStatus", friendlyError(err, "新建对话失败，稍后再试一下。"), "err"));
    });
    $("openGlobalSearch").addEventListener("click", openGlobalSearch);
    $("globalSearchDialog").addEventListener("click", (event) => {
      if (event.target === $("globalSearchDialog")) closeGlobalSearch();
    });
    $("globalSearchInput").addEventListener("input", scheduleGlobalSearch);
    $("globalSearchInput").addEventListener("keydown", handleGlobalSearchKeydown);
    $("modelPickerButton").addEventListener("click", openModelPicker);
    $("modelPickerDialog").addEventListener("click", (event) => {
      if (event.target === $("modelPickerDialog")) closeModelPicker();
    });
    $("modelPickerSearch").addEventListener("input", handleModelPickerSearchInput);
    $("modelPickerSearch").addEventListener("keydown", handleModelPickerKeydown);
    $("openPrompts").addEventListener("click", openPromptLibrary);
    document.querySelectorAll(".prompt-chip[data-prompt-text]").forEach((button) => {
      button.addEventListener("click", () => insertPromptText(button.dataset.promptText || ""));
    });
    $("openPromptLibrary").addEventListener("click", openPromptLibrary);
    $("closePromptDialog").addEventListener("click", closePromptLibrary);
	    $("promptDialog").addEventListener("click", (event) => {
	      if (event.target === $("promptDialog")) closePromptLibrary();
	    });
	    $("openProfiles").addEventListener("click", openProfiles);
	    $("closeProfileDialog").addEventListener("click", closeProfiles);
	    $("profileDialog").addEventListener("click", (event) => {
	      if (event.target === $("profileDialog")) closeProfiles();
	    });
	    $("saveProfile").addEventListener("click", saveProfile);
	    $("resetProfile").addEventListener("click", resetProfileForm);
	    $("profileTitle").addEventListener("input", updateProfileEditorMeta);
	    $("profileContent").addEventListener("input", updateProfileEditorMeta);
	    $("profileStatus").addEventListener("click", toggleProfilePopover);
	    $("disableProfileForConversation").addEventListener("change", () => setProfileDisabledForCurrentConversation($("disableProfileForConversation").checked));
	    document.addEventListener("click", handleProfileOutsideClick);
	    document.querySelectorAll("[data-version-trigger]").forEach((button) => {
	      button.addEventListener("click", (event) => openChangelog(event, { full: false }));
	    });
	    $("closeChangelog").addEventListener("click", closeChangelog);
	    $("openFullChangelog").addEventListener("click", (event) => openChangelog(event, { full: true }));
	    document.addEventListener("click", handleChangelogOutsideClick);
	    $("savePromptTemplate").addEventListener("click", savePromptTemplate);
    $("resetPromptTemplate").addEventListener("click", resetPromptForm);
	    $("openFavorites").addEventListener("click", openFavorites);
	    $("closeFavoriteDialog").addEventListener("click", closeFavorites);
	    $("favoriteDialog").addEventListener("click", (event) => {
	      if (event.target === $("favoriteDialog")) closeFavorites();
	    });
	    $("openMediaAnalysis").addEventListener("click", openMediaAnalysis);
	    $("closeMediaDialog").addEventListener("click", closeMediaAnalysis);
	    $("mediaDialog").addEventListener("click", (event) => {
	      if (event.target === $("mediaDialog")) closeMediaAnalysis();
	    });
	    $("uploadMediaTask").addEventListener("click", uploadMediaTask);
		    $("refreshConversations").addEventListener("click", loadConversations);
	    $("sidebarResizer").addEventListener("pointerdown", startSidebarResize);
	    $("sidebarResizer").addEventListener("mousedown", startSidebarResize);
	    $("sidebarResizer").addEventListener("dblclick", () => applySidebarWidth(sidebarWidthDefaults.value, true));
		    $("send").addEventListener("click", () => {
	      if (state.sending) stopGeneration();
	      else sendMessage();
	    });
	    $("attachImage").addEventListener("click", () => {
	      if (!selectedModelSupportsVision()) {
	        setStatus("chatStatus", "当前模型不支持图片理解，请切换支持图片的模型。", "err");
	        return;
	      }
	      $("imageInput").click();
	    });
	    $("imageInput").addEventListener("change", (event) => {
	      handleImageFiles(event.target.files).catch((err) => setStatus("chatStatus", friendlyError(err, "图片上传失败。"), "err"));
	    });
	    $("insertNewline").addEventListener("click", insertNewlineAtCursor);
	    $("deleteConversation").addEventListener("click", deleteCurrentConversation);
	    $("messages").addEventListener("pointerdown", beginChatTextSelection);
	    $("messages").addEventListener("scroll", handleMessagesScroll, { passive: true });
	    document.addEventListener("pointerup", endChatTextSelection);
	    document.addEventListener("pointercancel", endChatTextSelection);
	    document.addEventListener("selectionchange", handleSelectionChange);
	    document.querySelector(".composer")?.addEventListener("selectstart", handleComposerSelectStart);
	    $("scrollLatest").addEventListener("selectstart", (event) => event.preventDefault());
	    $("conversationMinimap").addEventListener("pointerenter", expandConversationMinimap);
	    $("conversationMinimap").addEventListener("pointerleave", scheduleCollapseConversationMinimap);
	    $("conversationMinimap").addEventListener("focusin", expandConversationMinimap);
	    $("conversationMinimap").addEventListener("focusout", scheduleCollapseConversationMinimap);
	    document.addEventListener("pointerdown", handleMinimapOutsidePointer);
    $("scrollLatest").addEventListener("click", () => scrollToLatest("smooth"));
	    $("prompt").addEventListener("input", autosizePrompt);
	    $("prompt").addEventListener("focus", handlePromptFocus);
	    $("openInterfaceSettings").addEventListener("click", toggleInterfaceSettings);
	    $("closeInterfaceSettings").addEventListener("click", closeInterfaceSettings);
	    $("interfacePopover").addEventListener("click", (event) => event.stopPropagation());
	    $("composerOpacityRange").addEventListener("input", () => {
	      applyInterfaceSettings({
	        opacity: $("composerOpacityRange").value,
	        blur: $("composerBlurRange").value
	      });
	    });
	    $("composerBlurRange").addEventListener("input", () => {
	      applyInterfaceSettings({
	        opacity: $("composerOpacityRange").value,
	        blur: $("composerBlurRange").value
	      });
	    });
	    $("resetInterfaceSettings").addEventListener("click", resetInterfaceSettings);
	    document.addEventListener("click", handleInterfaceOutsideClick);
	    document.addEventListener("keydown", (event) => {
	      const key = String(event.key || "").toLowerCase();
	      if ((event.metaKey || event.ctrlKey) && key === "k") {
	        event.preventDefault();
	        openGlobalSearch();
	        return;
	      }
	      if (event.key === "Escape") {
	        closeModelPicker();
	        closeGlobalSearch();
	        closeChangelog();
	        closeProfilePopover();
	        closeProfiles();
	        closeInterfaceSettings();
	        closeImagePreview();
	      }
	    });
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
	    $("modelSelect").addEventListener("change", () => {
	      syncModelPickerButton();
	      renderModelPickerList();
	      updateVisionUI();
	      if (state.attachments.length && !selectedModelSupportsVision()) {
	        setStatus("chatStatus", "当前模型不支持图片理解，请切换支持图片的模型。", "err");
	      }
	    });
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
		    $("saveAccount").addEventListener("click", saveAccount);
		    $("resetAccountForm").addEventListener("click", resetAccountForm);
		    $("adminKey").addEventListener("change", () => {
		      loadAdminModels();
		      loadAdminSearch();
		      loadAdminUsers();
		      loadTokenStats();
		    });
	    $("tokenStatsQuery").addEventListener("input", scheduleTokenStatsLoad);
	    $("tokenStatsSort").addEventListener("change", loadTokenStats);
	    $("refreshTokenStats").addEventListener("click", loadTokenStats);
	    $("openSide").addEventListener("click", openSidebar);
	    $("closeSide").addEventListener("click", closeSidebar);
	    $("webSearchToggle").addEventListener("change", () => {
	      if ((state.searchConfig?.mode || "auto") === "manual") {
		        setUserStorage("aiPlatformWebSearch", $("webSearchToggle").checked ? "1" : "0");
	      }
	    });
	    $("saveSearch").addEventListener("click", () => saveSearchConfig(false));
	    $("clearSearchKey").addEventListener("click", () => saveSearchConfig(true));
		    $("closeCopyDialog").addEventListener("click", closeManualCopy);
		    $("copyDialog").addEventListener("click", (event) => {
		      if (event.target === $("copyDialog")) closeManualCopy();
		    });
	    $("closeImagePreview").addEventListener("click", closeImagePreview);
	    $("imagePreviewDialog").addEventListener("click", (event) => {
	      if (event.target === $("imagePreviewDialog")) closeImagePreview();
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
			    window.addEventListener("resize", () => applySidebarWidth(state.sidebarWidth, true), { passive: true });
			    window.addEventListener("resize", updateChatUsage, { passive: true });
			    window.addEventListener("resize", positionModelPickerPopover, { passive: true });
			    window.addEventListener("resize", positionChangelogPanel, { passive: true });
			    window.addEventListener("resize", () => queueMarkdownOverflowRefresh($("messages")), { passive: true });
			    window.addEventListener("resize", queueConversationMinimap, { passive: true });
			    window.addEventListener("blur", endChatTextSelection);
		    window.visualViewport?.addEventListener("resize", syncViewportHeight, { passive: true });
	    window.visualViewport?.addEventListener("scroll", syncViewportHeight, { passive: true });

	    queueLucideRefresh();
	    bootstrap();
  </script>
</body>
</html>'''


if __name__ == "__main__":
    main()
