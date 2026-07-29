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

from ai_platform.database import db, ensure_default_ai_user, table_columns
from ai_platform.runtime import (
    b64_token,
    current_app_version,
    current_build_info,
    current_year,
    date_text_from_ts,
    ensure_secrets,
    iso_now,
    local_day_start,
    local_month_start,
    now,
    parse_changelog,
    password_hash,
    read_json,
    today_text,
    token_hash,
    verify_password,
    write_private,
)
from ai_platform.settings import (
    ADMIN_KEY_PATH,
    AI_PAGE_PATH,
    APP_DIR,
    BUILD_ID_PATH,
    CAT_GUEST_ID_RE,
    CAT_MAX_IMAGE_BYTES,
    CAT_OSS_DIR,
    CAT_PAGE_PATH,
    CAT_SESSION_COOKIE,
    CAT_SESSION_TTL_SECONDS,
    CHANGELOG_PATH,
    CHAT_IMAGE_ALLOWED_EXTENSIONS,
    CHAT_IMAGE_ALLOWED_MIME_TYPES,
    CHAT_IMAGE_MAX_BYTES,
    CHAT_IMAGE_MAX_COUNT,
    CHAT_IMAGE_OSS_DIR,
    DATA_DIR,
    DB_PATH,
    DEFAULT_AI_USER_ID,
    DEV_MODE,
    FAMILY_PASSWORD_PATH,
    HOME_PAGE_PATH,
    LEGACY_CONFIG_PATH,
    LISTEN,
    MARKDOWN_TEST_PATH,
    MEDIA_ALLOWED_EXTENSIONS,
    MEDIA_MAX_UPLOAD_BYTES,
    MEDIA_OSS_DIR,
    RES_DIR,
    SECRETS_PATH,
    SESSION_COOKIE,
    SESSION_TTL_SECONDS,
    USERNAME_RE,
)


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
              supports_native_web_search INTEGER NOT NULL DEFAULT 0,
              enabled INTEGER NOT NULL DEFAULT 1,
              input_price_per_million REAL NOT NULL DEFAULT 0,
              output_price_per_million REAL NOT NULL DEFAULT 0,
              cost_enabled INTEGER NOT NULL DEFAULT 0,
              cost_note TEXT NOT NULL DEFAULT '',
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
              estimated_cost REAL NOT NULL DEFAULT 0,
              cost_input_price REAL NOT NULL DEFAULT 0,
              cost_output_price REAL NOT NULL DEFAULT 0,
              cost_model_id TEXT NOT NULL DEFAULT '',
              actual_model TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS side_discussions (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              session_id TEXT NOT NULL,
              source_message_id INTEGER NOT NULL,
              source_role TEXT NOT NULL,
              source_created_at INTEGER NOT NULL DEFAULT 0,
              selected_text TEXT NOT NULL,
              model_id TEXT NOT NULL,
              title TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'active',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS side_discussion_messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              discussion_id TEXT NOT NULL,
              role TEXT NOT NULL,
              content TEXT NOT NULL,
              reasoning_content TEXT NOT NULL DEFAULT '',
              input_tokens INTEGER NOT NULL DEFAULT 0,
              output_tokens INTEGER NOT NULL DEFAULT 0,
              total_tokens INTEGER NOT NULL DEFAULT 0,
              estimated_cost REAL NOT NULL DEFAULT 0,
              actual_model TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              FOREIGN KEY (discussion_id) REFERENCES side_discussions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS daily_usage (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL,
              date TEXT NOT NULL,
              request_count INTEGER NOT NULL DEFAULT 0,
              input_tokens INTEGER NOT NULL DEFAULT 0,
              output_tokens INTEGER NOT NULL DEFAULT 0,
              total_tokens INTEGER NOT NULL DEFAULT 0,
              estimated_cost REAL NOT NULL DEFAULT 0,
              updated_at INTEGER NOT NULL,
              UNIQUE(user_id, date)
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
        if "supports_native_web_search" not in model_columns:
            conn.execute(
                "ALTER TABLE models ADD COLUMN supports_native_web_search INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                """
                UPDATE models
                SET supports_native_web_search=1
                WHERE lower(model) LIKE '%qwen%'
                  AND (
                    lower(base_url) LIKE '%dashscope.aliyuncs.com%'
                    OR lower(base_url) LIKE '%.maas.aliyuncs.com%'
                  )
                """
            )
        for column in ("input_price_per_million", "output_price_per_million"):
            if column not in model_columns:
                conn.execute(f"ALTER TABLE models ADD COLUMN {column} REAL NOT NULL DEFAULT 0")
        if "cost_enabled" not in model_columns:
            conn.execute("ALTER TABLE models ADD COLUMN cost_enabled INTEGER NOT NULL DEFAULT 0")
        if "cost_note" not in model_columns:
            conn.execute("ALTER TABLE models ADD COLUMN cost_note TEXT NOT NULL DEFAULT ''")
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
        for column in ("estimated_cost", "cost_input_price", "cost_output_price"):
            if column not in message_columns:
                conn.execute(f"ALTER TABLE messages ADD COLUMN {column} REAL NOT NULL DEFAULT 0")
        if "cost_model_id" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN cost_model_id TEXT NOT NULL DEFAULT ''")
        if "actual_model" not in message_columns:
            conn.execute("ALTER TABLE messages ADD COLUMN actual_model TEXT NOT NULL DEFAULT ''")
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_side_discussions_user_session ON side_discussions(user_id, session_id, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_side_discussion_messages_discussion ON side_discussion_messages(discussion_id, id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_images_user_session ON chat_message_images(user_id, session_id, message_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_favorites_user_created ON favorite_messages(user_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_daily_usage_user_date ON daily_usage(user_id, date)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_cost_created ON messages(role, created_at, estimated_cost)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_profiles_user_sort ON user_profiles(user_id, sort_order ASC, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_media_tasks_user_updated ON media_analysis_tasks(user_id, updated_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_media_tasks_task_id ON media_analysis_tasks(task_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_media_tasks_conversation ON media_analysis_tasks(conversation_id)")

        daily_count = conn.execute("SELECT COUNT(*) AS n FROM daily_usage").fetchone()["n"]
        if daily_count == 0:
            conn.execute(
                """
                INSERT OR IGNORE INTO daily_usage
                (user_id, date, request_count, input_tokens, output_tokens, total_tokens, estimated_cost, updated_at)
                SELECT
                  user_id,
                  date(created_at, 'unixepoch', 'localtime') AS usage_date,
                  COUNT(*) AS request_count,
                  COALESCE(SUM(prompt_tokens), 0) AS input_tokens,
                  COALESCE(SUM(completion_tokens), 0) AS output_tokens,
                  COALESCE(SUM(CASE WHEN total_tokens>0 THEN total_tokens ELSE prompt_tokens+completion_tokens END), 0) AS total_tokens,
                  COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                  ?
                FROM messages
                WHERE role='assistant'
                GROUP BY user_id, usage_date
                """,
                (now(),),
            )

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
        "supports_native_web_search": bool(row["supports_native_web_search"]) if "supports_native_web_search" in row.keys() else False,
        "enabled": bool(row["enabled"]),
        "input_price_per_million": float(row["input_price_per_million"] or 0) if "input_price_per_million" in row.keys() else 0,
        "output_price_per_million": float(row["output_price_per_million"] or 0) if "output_price_per_million" in row.keys() else 0,
        "cost_enabled": bool(row["cost_enabled"]) if "cost_enabled" in row.keys() else False,
        "cost_note": row["cost_note"] if "cost_note" in row.keys() else "",
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
        "supports_native_web_search": bool(row["supports_native_web_search"]) if "supports_native_web_search" in row.keys() else False,
        "pinned": bool(row["pinned"]) if "pinned" in row.keys() else False,
        "pinned_at": row["pinned_at"] if "pinned_at" in row.keys() else 0,
        "updated_at": row["updated_at"],
        "created_at": row["created_at"],
    }


def visible_user_question(content):
    value = str(content or "").strip()
    prefix = "以下是用户从当前会话中引用的内容："
    if not value.startswith(prefix):
        return value
    for marker in ("\n\n用户的新问题：", "\n用户的新问题："):
        _, separator, question = value.rpartition(marker)
        if separator and question.strip():
            return question.strip()
    return value


def side_discussion_public(row):
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "source_message_id": row["source_message_id"],
        "source_role": row["source_role"],
        "source_created_at": row["source_created_at"],
        "selected_text": row["selected_text"],
        "model_id": row["model_id"],
        "model_name": row["model_name"] if "model_name" in row.keys() else "",
        "model": row["model"] if "model" in row.keys() else "",
        "title": row["title"],
        "status": row["status"],
        "message_count": int(row["message_count"] or 0) if "message_count" in row.keys() else 0,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def side_discussion_message_public(row):
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "reasoning_content": row["reasoning_content"],
        "created_at": row["created_at"],
        "usage": {
            "prompt_tokens": int(row["input_tokens"] or 0),
            "completion_tokens": int(row["output_tokens"] or 0),
            "total_tokens": int(row["total_tokens"] or 0),
            "estimated_cost": float(row["estimated_cost"] or 0),
        },
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
    estimated_cost = float(row["estimated_cost"] or 0) if "estimated_cost" in row.keys() else 0.0
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost": estimated_cost,
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


def parse_price(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if number < 0:
        return 0.0
    return min(number, 1000000.0)


def estimate_request_cost(prompt_tokens, completion_tokens, input_price, output_price, enabled=True):
    if not enabled:
        return 0.0
    cost = (max(0, int(prompt_tokens or 0)) / 1000000.0 * parse_price(input_price)) + (
        max(0, int(completion_tokens or 0)) / 1000000.0 * parse_price(output_price)
    )
    return round(cost, 8)


def add_daily_usage(conn, user_id, timestamp, prompt_tokens, completion_tokens, total_tokens, estimated_cost):
    usage_date = date_text_from_ts(timestamp)
    ts = now()
    conn.execute(
        """
        INSERT INTO daily_usage
        (user_id, date, request_count, input_tokens, output_tokens, total_tokens, estimated_cost, updated_at)
        VALUES (?, ?, 1, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id, date) DO UPDATE SET
          request_count=request_count+1,
          input_tokens=input_tokens+excluded.input_tokens,
          output_tokens=output_tokens+excluded.output_tokens,
          total_tokens=total_tokens+excluded.total_tokens,
          estimated_cost=estimated_cost+excluded.estimated_cost,
          updated_at=excluded.updated_at
        """,
        (
            user_id,
            usage_date,
            max(0, int(prompt_tokens or 0)),
            max(0, int(completion_tokens or 0)),
            max(0, int(total_tokens or 0)),
            float(estimated_cost or 0),
            ts,
        ),
    )


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


def responses_input_from_messages(messages):
    converted = []
    for message in messages or []:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if not isinstance(content, list):
            converted.append({"role": role, "content": str(content or "")})
            continue
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type in ("text", "input_text"):
                text = str(item.get("text") or "")
                if text:
                    parts.append({"type": "input_text", "text": text})
            elif item_type in ("image_url", "input_image"):
                image_url = item.get("image_url")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                image_url = str(image_url or "")
                if image_url:
                    parts.append({"type": "input_image", "image_url": image_url})
        converted.append({"role": role, "content": parts or str(content)})
    return converted


def native_search_results_from_item(item, limit=5):
    if not isinstance(item, dict) or item.get("type") != "web_search_call":
        return []
    action = item.get("action") or {}
    results = []
    seen = set()
    for source in action.get("sources") or []:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        parsed = urlparse(url)
        title = str(source.get("title") or parsed.netloc or "联网来源").strip()
        result = search_result(title, url, source.get("snippet") or "")
        if result["url"]:
            results.append(result)
        if len(results) >= limit:
            break
    return results


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
            return self.ai_page()
        if path in ("/dev/markdown", "/dev/markdown/"):
            if not DEV_MODE:
                return self.error(HTTPStatus.NOT_FOUND, "not found")
            return self.static_file(MARKDOWN_TEST_PATH)
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
        if path == "/api/version":
            return self.handle_version()
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
        model_query = str((params.get("model_q") or [""])[0] or "").strip().lower()[:80]
        model_sort = str((params.get("model_sort") or ["tokens"])[0] or "tokens").strip().lower()
        if model_sort not in ("tokens", "requests", "recent"):
            model_sort = "tokens"

        order_sql = {
            "tokens": "total_tokens DESC, request_count DESC, last_used_at DESC",
            "recent": "last_used_at DESC, total_tokens DESC, request_count DESC",
            "created": "u.created_at DESC",
        }[sort]
        model_order_sql = {
            "tokens": "total_tokens DESC, request_count DESC, last_used_at DESC",
            "requests": "request_count DESC, total_tokens DESC, last_used_at DESC",
            "recent": "last_used_at DESC, total_tokens DESC, request_count DESC",
        }[model_sort]
        where_sql = ""
        args = []
        if query:
            where_sql = "WHERE lower(u.username) LIKE ? ESCAPE '\\' OR lower(u.display_name) LIKE ? ESCAPE '\\'"
            like = "%" + like_escape(query) + "%"
            args.extend([like, like])
        model_where_sql = ""
        model_args = []
        if model_query:
            model_where_sql = """
                WHERE lower(mo.name) LIKE ? ESCAPE '\\'
                   OR lower(mo.model) LIKE ? ESCAPE '\\'
                   OR lower(mo.provider) LIKE ? ESCAPE '\\'
            """
            model_like = "%" + like_escape(model_query) + "%"
            model_args.extend([model_like, model_like, model_like])

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

            model_rows = conn.execute(
                f"""
                SELECT
                  mo.id,
                  mo.name,
                  mo.model,
                  mo.provider,
                  mo.enabled,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN 1 ELSE 0 END), 0) AS request_count,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN COALESCE(m.prompt_tokens, 0) ELSE 0 END), 0) AS prompt_tokens,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN COALESCE(m.completion_tokens, 0) ELSE 0 END), 0) AS completion_tokens,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN
                    CASE WHEN COALESCE(m.total_tokens, 0) > 0
                      THEN COALESCE(m.total_tokens, 0)
                      ELSE COALESCE(m.prompt_tokens, 0) + COALESCE(m.completion_tokens, 0)
                    END ELSE 0 END), 0) AS total_tokens,
                  COUNT(DISTINCT CASE WHEN m.role='assistant' THEN c.user_id ELSE NULL END) AS user_count,
                  MAX(CASE WHEN m.role='assistant' THEN m.created_at ELSE NULL END) AS last_used_at
                FROM models mo
                LEFT JOIN conversations c ON c.model_id=mo.id
                LEFT JOIN messages m ON m.conversation_id=c.id AND m.user_id=c.user_id AND m.role='assistant'
                {model_where_sql}
                GROUP BY mo.id
                ORDER BY {model_order_sql}
                LIMIT 200
                """,
                model_args,
            ).fetchall()

            model_details = {}
            model_ids = [row["id"] for row in model_rows]
            if model_ids:
                placeholders = ",".join(["?"] * len(model_ids))
                model_detail_rows = conn.execute(
                    f"""
                    SELECT
                      mo.id AS model_id,
                      m.id AS message_id,
                      m.conversation_id,
                      m.created_at,
                      m.prompt_tokens,
                      m.completion_tokens,
                      CASE WHEN COALESCE(m.total_tokens, 0) > 0
                        THEN COALESCE(m.total_tokens, 0)
                        ELSE COALESCE(m.prompt_tokens, 0) + COALESCE(m.completion_tokens, 0)
                      END AS total_tokens,
                      c.title AS conversation_title,
                      u.username,
                      u.display_name,
                      EXISTS(SELECT 1 FROM message_sources s WHERE s.message_id=m.id) AS web_search
                    FROM messages m
                    JOIN conversations c ON c.id=m.conversation_id AND c.user_id=m.user_id
                    JOIN models mo ON mo.id=c.model_id
                    LEFT JOIN users u ON u.id=m.user_id
                    WHERE m.role='assistant' AND mo.id IN ({placeholders})
                    ORDER BY mo.id ASC, m.created_at DESC, m.id DESC
                    """,
                    model_ids,
                ).fetchall()
                for detail in model_detail_rows:
                    bucket = model_details.setdefault(detail["model_id"], [])
                    if len(bucket) >= 20:
                        continue
                    bucket.append(
                        {
                            "message_id": detail["message_id"],
                            "conversation_id": detail["conversation_id"],
                            "conversation_title": detail["conversation_title"] or "未命名对话",
                            "created_at": detail["created_at"],
                            "username": detail["username"] or "",
                            "display_name": detail["display_name"] or detail["username"] or "",
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

        models = []
        for row in model_rows:
            models.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "model": row["model"],
                    "provider": row["provider"],
                    "enabled": bool(row["enabled"]),
                    "request_count": int(row["request_count"] or 0),
                    "prompt_tokens": int(row["prompt_tokens"] or 0),
                    "completion_tokens": int(row["completion_tokens"] or 0),
                    "total_tokens": int(row["total_tokens"] or 0),
                    "user_count": int(row["user_count"] or 0),
                    "last_used_at": row["last_used_at"] or 0,
                    "recent_requests": model_details.get(row["id"], []),
                }
            )

        top_request_model = next((item for item in sorted(models, key=lambda value: value["request_count"], reverse=True) if item["request_count"] > 0), None)
        top_token_model = next((item for item in sorted(models, key=lambda value: value["total_tokens"], reverse=True) if item["total_tokens"] > 0), None)

        return self.json(
            {
                "summary": {
                    "total_users": int(summary["total_users"] or 0),
                    "total_requests": int(summary["total_requests"] or 0),
                    "prompt_tokens": int(summary["prompt_tokens"] or 0),
                    "completion_tokens": int(summary["completion_tokens"] or 0),
                    "total_tokens": int(summary["total_tokens"] or 0),
                },
                "model_summary": {
                    "total_models": len(models),
                    "total_requests": int(summary["total_requests"] or 0),
                    "total_tokens": int(summary["total_tokens"] or 0),
                    "top_request_model": top_request_model,
                    "top_token_model": top_token_model,
                },
                "users": users,
                "models": models,
                "query": query,
                "sort": sort,
                "model_query": model_query,
                "model_sort": model_sort,
            }
        )

    def handle_admin_cost_stats(self):
        params = parse_qs(urlparse(self.path).query)
        range_key = str((params.get("range") or ["30d"])[0] or "30d").strip().lower()
        if range_key not in ("7d", "30d", "all"):
            range_key = "30d"
        cutoff = 0
        if range_key == "7d":
            cutoff = now() - 7 * 86400
        elif range_key == "30d":
            cutoff = now() - 30 * 86400
        range_where = "m.role='assistant'"
        range_args = []
        if cutoff:
            range_where += " AND m.created_at>=?"
            range_args.append(cutoff)

        with db() as conn:
            total_summary = conn.execute(
                """
                SELECT
                  COALESCE(SUM(estimated_cost), 0) AS total_cost,
                  COUNT(*) AS request_count
                FROM messages
                WHERE role='assistant'
                """
            ).fetchone()
            today_summary = conn.execute(
                """
                SELECT COALESCE(SUM(estimated_cost), 0) AS cost
                FROM messages
                WHERE role='assistant' AND created_at>=?
                """,
                (local_day_start(),),
            ).fetchone()
            month_summary = conn.execute(
                """
                SELECT COALESCE(SUM(estimated_cost), 0) AS cost
                FROM messages
                WHERE role='assistant' AND created_at>=?
                """,
                (local_month_start(),),
            ).fetchone()
            range_summary = conn.execute(
                f"""
                SELECT
                  COALESCE(SUM(m.estimated_cost), 0) AS cost,
                  COUNT(*) AS request_count,
                  COALESCE(SUM(m.prompt_tokens), 0) AS prompt_tokens,
                  COALESCE(SUM(m.completion_tokens), 0) AS completion_tokens,
                  COALESCE(SUM(CASE WHEN m.total_tokens>0 THEN m.total_tokens ELSE m.prompt_tokens+m.completion_tokens END), 0) AS total_tokens
                FROM messages m
                WHERE {range_where}
                """,
                range_args,
            ).fetchone()
            model_rows = conn.execute(
                f"""
                SELECT
                  COALESCE(NULLIF(m.cost_model_id, ''), c.model_id, '') AS model_id,
                  COALESCE(mo.name, m.actual_model, '未知模型') AS model_name,
                  COALESCE(mo.model, m.actual_model, '') AS model_code,
                  COALESCE(mo.provider, '') AS provider,
                  COUNT(*) AS request_count,
                  COALESCE(SUM(m.prompt_tokens), 0) AS prompt_tokens,
                  COALESCE(SUM(m.completion_tokens), 0) AS completion_tokens,
                  COALESCE(SUM(CASE WHEN m.total_tokens>0 THEN m.total_tokens ELSE m.prompt_tokens+m.completion_tokens END), 0) AS total_tokens,
                  COALESCE(SUM(m.estimated_cost), 0) AS estimated_cost,
                  COUNT(DISTINCT m.user_id) AS user_count,
                  MAX(m.created_at) AS last_used_at
                FROM messages m
                LEFT JOIN conversations c ON c.id=m.conversation_id AND c.user_id=m.user_id
                LEFT JOIN models mo ON mo.id=COALESCE(NULLIF(m.cost_model_id, ''), c.model_id)
                WHERE {range_where}
                GROUP BY model_id, model_name, model_code, provider
                ORDER BY estimated_cost DESC, total_tokens DESC, request_count DESC
                LIMIT 100
                """,
                range_args,
            ).fetchall()
            user_rows = conn.execute(
                f"""
                SELECT
                  u.id,
                  u.username,
                  u.display_name,
                  COUNT(*) AS request_count,
                  COALESCE(SUM(m.prompt_tokens), 0) AS prompt_tokens,
                  COALESCE(SUM(m.completion_tokens), 0) AS completion_tokens,
                  COALESCE(SUM(CASE WHEN m.total_tokens>0 THEN m.total_tokens ELSE m.prompt_tokens+m.completion_tokens END), 0) AS total_tokens,
                  COALESCE(SUM(m.estimated_cost), 0) AS estimated_cost,
                  MAX(m.created_at) AS last_used_at
                FROM messages m
                LEFT JOIN users u ON u.id=m.user_id
                WHERE {range_where}
                GROUP BY u.id
                ORDER BY estimated_cost DESC, total_tokens DESC, request_count DESC
                LIMIT 100
                """,
                range_args,
            ).fetchall()

        models = [
            {
                "model_id": row["model_id"] or "",
                "model_name": row["model_name"] or "未知模型",
                "model_code": row["model_code"] or "",
                "provider": row["provider"] or "",
                "request_count": int(row["request_count"] or 0),
                "prompt_tokens": int(row["prompt_tokens"] or 0),
                "completion_tokens": int(row["completion_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "estimated_cost": float(row["estimated_cost"] or 0),
                "user_count": int(row["user_count"] or 0),
                "last_used_at": row["last_used_at"] or 0,
            }
            for row in model_rows
        ]
        users = [
            {
                "user_id": row["id"] or "",
                "username": row["username"] or "",
                "display_name": row["display_name"] or row["username"] or "未知账号",
                "request_count": int(row["request_count"] or 0),
                "prompt_tokens": int(row["prompt_tokens"] or 0),
                "completion_tokens": int(row["completion_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "estimated_cost": float(row["estimated_cost"] or 0),
                "last_used_at": row["last_used_at"] or 0,
            }
            for row in user_rows
        ]
        total_requests = int(total_summary["request_count"] or 0)
        total_cost = float(total_summary["total_cost"] or 0)
        return self.json(
            {
                "range": range_key,
                "summary": {
                    "today_cost": float(today_summary["cost"] or 0),
                    "month_cost": float(month_summary["cost"] or 0),
                    "total_cost": total_cost,
                    "average_request_cost": (total_cost / total_requests) if total_requests else 0,
                    "range_cost": float(range_summary["cost"] or 0),
                    "range_requests": int(range_summary["request_count"] or 0),
                    "range_total_tokens": int(range_summary["total_tokens"] or 0),
                    "top_model": models[0] if models else None,
                    "top_user": users[0] if users else None,
                },
                "models": models,
                "users": users,
            }
        )

    def handle_admin_cost_recalculate(self):
        try:
            data = self.read_body()
        except Exception:
            data = {}
        range_key = str(data.get("range") or "30d").strip().lower()
        if range_key not in ("7d", "30d", "all"):
            range_key = "30d"
        cutoff = 0
        if range_key == "7d":
            cutoff = now() - 7 * 86400
        elif range_key == "30d":
            cutoff = now() - 30 * 86400
        where_sql = "m.role='assistant' AND COALESCE(m.estimated_cost, 0)=0"
        args = []
        if cutoff:
            where_sql += " AND m.created_at>=?"
            args.append(cutoff)
        with db() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  m.id,
                  m.prompt_tokens,
                  m.completion_tokens,
                  m.total_tokens,
                  m.created_at,
                  c.model_id,
                  mo.model AS model_code,
                  mo.input_price_per_million,
                  mo.output_price_per_million,
                  mo.cost_enabled
                FROM messages m
                JOIN conversations c ON c.id=m.conversation_id AND c.user_id=m.user_id
                JOIN models mo ON mo.id=c.model_id
                WHERE {where_sql}
                """,
                args,
            ).fetchall()
            updated = 0
            skipped = 0
            total_cost = 0.0
            for row in rows:
                if not row["cost_enabled"]:
                    skipped += 1
                    continue
                prompt_tokens = int(row["prompt_tokens"] or 0)
                completion_tokens = int(row["completion_tokens"] or 0)
                total_tokens = int(row["total_tokens"] or 0)
                if not total_tokens and (prompt_tokens or completion_tokens):
                    total_tokens = prompt_tokens + completion_tokens
                input_price = parse_price(row["input_price_per_million"])
                output_price = parse_price(row["output_price_per_million"])
                cost = estimate_request_cost(prompt_tokens, completion_tokens, input_price, output_price, True)
                if cost <= 0:
                    skipped += 1
                    continue
                conn.execute(
                    """
                    UPDATE messages
                    SET estimated_cost=?, cost_input_price=?, cost_output_price=?,
                        cost_model_id=?, actual_model=?
                    WHERE id=?
                    """,
                    (
                        cost,
                        input_price,
                        output_price,
                        row["model_id"],
                        row["model_code"] or "",
                        row["id"],
                    ),
                )
                updated += 1
                total_cost += cost
            conn.execute("DELETE FROM daily_usage")
            conn.execute(
                """
                INSERT INTO daily_usage
                (user_id, date, request_count, input_tokens, output_tokens, total_tokens, estimated_cost, updated_at)
                SELECT
                  user_id,
                  date(created_at, 'unixepoch', 'localtime') AS usage_date,
                  COUNT(*) AS request_count,
                  COALESCE(SUM(prompt_tokens), 0) AS input_tokens,
                  COALESCE(SUM(completion_tokens), 0) AS output_tokens,
                  COALESCE(SUM(CASE WHEN total_tokens>0 THEN total_tokens ELSE prompt_tokens+completion_tokens END), 0) AS total_tokens,
                  COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                  ?
                FROM messages
                WHERE role='assistant'
                GROUP BY user_id, usage_date
                """,
                (now(),),
            )
        return self.json(
            {
                "ok": True,
                "range": range_key,
                "updated_messages": updated,
                "skipped_messages": skipped,
                "estimated_cost_added": round(total_cost, 8),
            }
        )

    def handle_token_activity(self):
        user = self.current_user()
        user_id = user["id"]
        end_day_start = local_day_start()
        start_day_start = end_day_start - 364 * 86400
        start_date = date_text_from_ts(start_day_start)
        with db() as conn:
            daily_rows = conn.execute(
                """
                SELECT *
                FROM daily_usage
                WHERE user_id=? AND date>=?
                ORDER BY date ASC
                """,
                (user_id, start_date),
            ).fetchall()
            totals = conn.execute(
                """
                SELECT
                  COALESCE(SUM(request_count), 0) AS request_count,
                  COALESCE(SUM(input_tokens), 0) AS input_tokens,
                  COALESCE(SUM(output_tokens), 0) AS output_tokens,
                  COALESCE(SUM(total_tokens), 0) AS total_tokens,
                  COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                  COUNT(CASE WHEN request_count>0 THEN 1 ELSE NULL END) AS active_days
                FROM daily_usage
                WHERE user_id=?
                """,
                (user_id,),
            ).fetchone()
            conversation_count = conn.execute(
                "SELECT COUNT(*) AS n FROM conversations WHERE user_id=? AND archived=0",
                (user_id,),
            ).fetchone()["n"]
            model_rows = conn.execute(
                """
                SELECT
                  COALESCE(mo.name, msg.actual_model, '未知模型') AS model_name,
                  COALESCE(mo.model, msg.actual_model, '') AS model_code,
                  COUNT(*) AS request_count,
                  COALESCE(SUM(CASE WHEN msg.total_tokens>0 THEN msg.total_tokens ELSE msg.prompt_tokens+msg.completion_tokens END), 0) AS total_tokens,
                  COALESCE(SUM(msg.estimated_cost), 0) AS estimated_cost
                FROM messages msg
                LEFT JOIN conversations c ON c.id=msg.conversation_id AND c.user_id=msg.user_id
                LEFT JOIN models mo ON mo.id=COALESCE(NULLIF(msg.cost_model_id, ''), c.model_id)
                WHERE msg.user_id=? AND msg.role='assistant'
                GROUP BY model_name, model_code
                ORDER BY total_tokens DESC, request_count DESC
                LIMIT 5
                """,
                (user_id,),
            ).fetchall()
            conversation_rows = conn.execute(
                """
                SELECT
                  c.id,
                  c.title,
                  COUNT(msg.id) AS request_count,
                  COALESCE(SUM(CASE WHEN msg.total_tokens>0 THEN msg.total_tokens ELSE msg.prompt_tokens+msg.completion_tokens END), 0) AS total_tokens
                FROM conversations c
                JOIN messages msg ON msg.conversation_id=c.id AND msg.user_id=c.user_id AND msg.role='assistant'
                WHERE c.user_id=?
                GROUP BY c.id
                ORDER BY total_tokens DESC, request_count DESC
                LIMIT 5
                """,
                (user_id,),
            ).fetchall()
            day_model_rows = conn.execute(
                """
                SELECT
                  date(msg.created_at, 'unixepoch', 'localtime') AS usage_date,
                  COALESCE(mo.name, msg.actual_model, '未知模型') AS model_name,
                  COUNT(*) AS request_count,
                  COALESCE(SUM(CASE WHEN msg.total_tokens>0 THEN msg.total_tokens ELSE msg.prompt_tokens+msg.completion_tokens END), 0) AS total_tokens,
                  COALESCE(SUM(msg.estimated_cost), 0) AS estimated_cost
                FROM messages msg
                LEFT JOIN conversations c ON c.id=msg.conversation_id AND c.user_id=msg.user_id
                LEFT JOIN models mo ON mo.id=COALESCE(NULLIF(msg.cost_model_id, ''), c.model_id)
                WHERE msg.user_id=? AND msg.role='assistant' AND msg.created_at>=?
                GROUP BY usage_date, model_name
                ORDER BY usage_date ASC, total_tokens DESC
                """,
                (user_id, start_day_start),
            ).fetchall()

        active_dates = {row["date"] for row in daily_rows if int(row["request_count"] or 0) > 0}
        longest_streak = 0
        current_streak = 0
        streak = 0
        cursor_day = start_day_start
        today_date = today_text()
        while cursor_day <= end_day_start:
            value = date_text_from_ts(cursor_day)
            if value in active_dates:
                streak += 1
                longest_streak = max(longest_streak, streak)
                if value <= today_date:
                    current_streak = streak
            else:
                streak = 0
                if value <= today_date:
                    current_streak = 0
            cursor_day += 86400

        daily_by_date = {row["date"]: row for row in daily_rows}
        days = []
        cursor_day = start_day_start
        while cursor_day <= end_day_start:
            value = date_text_from_ts(cursor_day)
            row = daily_by_date.get(value)
            days.append(
                {
                    "date": value,
                    "request_count": int(row["request_count"] or 0) if row else 0,
                    "input_tokens": int(row["input_tokens"] or 0) if row else 0,
                    "output_tokens": int(row["output_tokens"] or 0) if row else 0,
                    "total_tokens": int(row["total_tokens"] or 0) if row else 0,
                    "estimated_cost": float(row["estimated_cost"] or 0) if row else 0,
                }
            )
            cursor_day += 86400

        day_models = {}
        for row in day_model_rows:
            day_models.setdefault(row["usage_date"], []).append(
                {
                    "model_name": row["model_name"] or "未知模型",
                    "request_count": int(row["request_count"] or 0),
                    "total_tokens": int(row["total_tokens"] or 0),
                    "estimated_cost": float(row["estimated_cost"] or 0),
                }
            )

        total_tokens = int(totals["total_tokens"] or 0)
        active_day_count = int(totals["active_days"] or 0)
        return self.json(
            {
                "summary": {
                    "request_count": int(totals["request_count"] or 0),
                    "input_tokens": int(totals["input_tokens"] or 0),
                    "output_tokens": int(totals["output_tokens"] or 0),
                    "total_tokens": total_tokens,
                    "estimated_cost": float(totals["estimated_cost"] or 0),
                    "conversation_count": int(conversation_count or 0),
                    "active_days": active_day_count,
                    "longest_streak": longest_streak,
                    "current_streak": current_streak,
                    "average_daily_tokens": int(total_tokens / active_day_count) if active_day_count else 0,
                },
                "days": days,
                "day_models": day_models,
                "top_models": [
                    {
                        "model_name": row["model_name"] or "未知模型",
                        "model_code": row["model_code"] or "",
                        "request_count": int(row["request_count"] or 0),
                        "total_tokens": int(row["total_tokens"] or 0),
                        "estimated_cost": float(row["estimated_cost"] or 0),
                    }
                    for row in model_rows
                ],
                "top_conversations": [
                    {
                        "conversation_id": row["id"],
                        "title": row["title"] or "未命名对话",
                        "request_count": int(row["request_count"] or 0),
                        "total_tokens": int(row["total_tokens"] or 0),
                    }
                    for row in conversation_rows
                ],
                "top_agents": [],
                "top_prompts": [],
            }
        )

    def handle_admin_overview(self):
        search = web_search_config(self.server.secrets)
        media_oss = media_oss_config(self.server.secrets)
        chat_oss = chat_image_oss_config(self.server.secrets)
        cat_oss = cat_oss_config(self.server.secrets)
        tingwu = tingwu_config(self.server.secrets)
        with db() as conn:
            user_count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
            active_user_count = conn.execute("SELECT COUNT(*) AS n FROM users WHERE is_active=1").fetchone()["n"]
            model_count = conn.execute("SELECT COUNT(*) AS n FROM models").fetchone()["n"]
            enabled_model_count = conn.execute("SELECT COUNT(*) AS n FROM models WHERE enabled=1").fetchone()["n"]
            conversation_count = conn.execute("SELECT COUNT(*) AS n FROM conversations WHERE archived=0").fetchone()["n"]
        return self.json(
            {
                "overview": {
                    "users": {
                        "total": int(user_count or 0),
                        "active": int(active_user_count or 0),
                    },
                    "models": {
                        "total": int(model_count or 0),
                        "enabled": int(enabled_model_count or 0),
                    },
                    "conversations": {
                        "total": int(conversation_count or 0),
                    },
                    "search": {
                        "enabled": bool(search["enabled"]),
                        "configured": bool(search["api_key"]),
                        "provider": search["provider"],
                        "mode": search["mode"],
                    },
                    "oss": {
                        "cat": bool(cat_oss["configured"]),
                        "chat_image": bool(chat_oss["configured"]),
                        "media": bool(media_oss["configured"]),
                        "configured": bool(cat_oss["configured"] or chat_oss["configured"] or media_oss["configured"]),
                    },
                    "tingwu": {
                        "configured": bool(tingwu_configured(tingwu)),
                    },
                }
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
        supports_native_web_search = 1 if data.get("supports_native_web_search") else 0
        enabled = 1 if data.get("enabled", True) else 0
        input_price = parse_price(data.get("input_price_per_million"))
        output_price = parse_price(data.get("output_price_per_million"))
        cost_enabled = 1 if data.get("cost_enabled") else 0
        cost_note = str(data.get("cost_note") or "").strip()[:500]

        if not name or not base_url or not model:
            return self.error(HTTPStatus.BAD_REQUEST, "name, base_url and model are required")

        model_id = b64_token(12)
        ts = now()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO models
                (id, name, provider, base_url, api_key, model, system_prompt, supports_vision,
                 supports_native_web_search, enabled,
                 input_price_per_million, output_price_per_million, cost_enabled, cost_note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    name,
                    provider,
                    base_url,
                    api_key,
                    model,
                    system_prompt,
                    supports_vision,
                    supports_native_web_search,
                    enabled,
                    input_price,
                    output_price,
                    cost_enabled,
                    cost_note,
                    ts,
                    ts,
                ),
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
            supports_native_web_search = 1 if data.get(
                "supports_native_web_search", bool(row["supports_native_web_search"])
            ) else 0
            enabled = 1 if data.get("enabled", bool(row["enabled"])) else 0
            input_price = parse_price(data.get("input_price_per_million", row["input_price_per_million"]))
            output_price = parse_price(data.get("output_price_per_million", row["output_price_per_million"]))
            cost_enabled = 1 if data.get("cost_enabled", bool(row["cost_enabled"])) else 0
            cost_note = str(data.get("cost_note", row["cost_note"]) or "").strip()[:500]
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
                SET name=?, provider=?, base_url=?, api_key=?, model=?, system_prompt=?, supports_vision=?,
                    supports_native_web_search=?, enabled=?,
                    input_price_per_million=?, output_price_per_million=?, cost_enabled=?, cost_note=?, updated_at=?
                WHERE id=?
                """,
                (
                    name,
                    provider,
                    base_url,
                    api_key,
                    model,
                    system_prompt,
                    supports_vision,
                    supports_native_web_search,
                    enabled,
                    input_price,
                    output_price,
                    cost_enabled,
                    cost_note,
                    now(),
                    model_id,
                ),
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
            SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision,
                   m.supports_native_web_search
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

    def side_discussion_id_from_path(self):
        parts = urllib.parse.urlparse(self.path).path.strip("/").split("/")
        return urllib.parse.unquote(parts[2]) if len(parts) >= 3 else ""

    def side_discussion_row(self, conn, discussion_id, user_id):
        return conn.execute(
            """
            SELECT d.*, m.name AS model_name, m.model AS model,
                   COUNT(dm.id) AS message_count
            FROM side_discussions d
            JOIN models m ON m.id=d.model_id
            LEFT JOIN side_discussion_messages dm ON dm.discussion_id=d.id
            WHERE d.id=? AND d.user_id=?
            GROUP BY d.id
            """,
            (discussion_id, user_id),
        ).fetchone()

    def handle_side_discussions(self):
        user_id = self.current_user()["id"]
        if self.command == "GET":
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            session_id = str((query.get("session_id") or [""])[0]).strip()
            if not session_id:
                return self.error(HTTPStatus.BAD_REQUEST, "session_id required")
            with db() as conn:
                conversation = conn.execute(
                    "SELECT id FROM conversations WHERE id=? AND user_id=? AND archived=0",
                    (session_id, user_id),
                ).fetchone()
                if not conversation:
                    return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
                rows = conn.execute(
                    """
                    SELECT d.*, m.name AS model_name, m.model AS model,
                           COUNT(dm.id) AS message_count
                    FROM side_discussions d
                    JOIN models m ON m.id=d.model_id
                    LEFT JOIN side_discussion_messages dm ON dm.discussion_id=d.id
                    WHERE d.session_id=? AND d.user_id=?
                    GROUP BY d.id
                    ORDER BY d.updated_at DESC
                    LIMIT 50
                    """,
                    (session_id, user_id),
                ).fetchall()
            return self.json({"discussions": [side_discussion_public(row) for row in rows]})

        try:
            data = self.read_body(limit=256 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        session_id = str(data.get("session_id") or "").strip()
        selected_text = str(data.get("selected_text") or "").strip()
        try:
            source_message_id = int(data.get("source_message_id") or 0)
        except (TypeError, ValueError):
            source_message_id = 0
        if not session_id or not source_message_id:
            return self.error(HTTPStatus.BAD_REQUEST, "引用来源不完整")
        if len(selected_text) < 2:
            return self.error(HTTPStatus.BAD_REQUEST, "请至少选择 2 个字符")
        selected_text = selected_text[:12000]
        with db() as conn:
            source = conn.execute(
                """
                SELECT c.id AS session_id, c.title AS conversation_title, c.model_id,
                       msg.role AS source_role, msg.created_at AS source_created_at
                FROM conversations c
                JOIN messages msg ON msg.conversation_id=c.id AND msg.user_id=c.user_id
                WHERE c.id=? AND c.user_id=? AND c.archived=0
                  AND msg.id=? AND msg.role IN ('user', 'assistant')
                """,
                (session_id, user_id, source_message_id),
            ).fetchone()
            if not source:
                return self.error(HTTPStatus.NOT_FOUND, "引用消息不存在")
            discussion_id = b64_token(12)
            title = re.sub(r"\s+", " ", selected_text).strip()[:36] or "侧边讨论"
            ts = now()
            conn.execute(
                """
                INSERT INTO side_discussions(
                  id, user_id, session_id, source_message_id, source_role,
                  source_created_at, selected_text, model_id, title, status,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    discussion_id,
                    user_id,
                    session_id,
                    source_message_id,
                    source["source_role"],
                    source["source_created_at"],
                    selected_text,
                    source["model_id"],
                    title,
                    ts,
                    ts,
                ),
            )
            row = self.side_discussion_row(conn, discussion_id, user_id)
        return self.json({"discussion": side_discussion_public(row)}, status=HTTPStatus.CREATED)

    def handle_side_discussion_item(self):
        user_id = self.current_user()["id"]
        discussion_id = self.side_discussion_id_from_path()
        with db() as conn:
            row = self.side_discussion_row(conn, discussion_id, user_id)
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "side discussion not found")
            messages = conn.execute(
                """
                SELECT *
                FROM side_discussion_messages
                WHERE discussion_id=?
                ORDER BY id ASC
                LIMIT 200
                """,
                (discussion_id,),
            ).fetchall()
        return self.json(
            {
                "discussion": side_discussion_public(row),
                "messages": [side_discussion_message_public(message) for message in messages],
            }
        )

    def handle_side_discussion_send(self):
        user_id = self.current_user()["id"]
        discussion_id = self.side_discussion_id_from_path()
        try:
            data = self.read_body(limit=1024 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        content = str(data.get("content") or "").strip()
        if not content:
            return self.error(HTTPStatus.BAD_REQUEST, "请输入想继续讨论的问题")

        with db() as conn:
            discussion = conn.execute(
                """
                SELECT d.*, c.title AS conversation_title,
                       m.name AS model_name, m.model, m.base_url, m.api_key,
                       m.system_prompt, m.enabled, m.input_price_per_million,
                       m.output_price_per_million, m.cost_enabled
                FROM side_discussions d
                JOIN conversations c ON c.id=d.session_id AND c.user_id=d.user_id
                JOIN models m ON m.id=d.model_id
                WHERE d.id=? AND d.user_id=?
                """,
                (discussion_id, user_id),
            ).fetchone()
            if not discussion:
                return self.error(HTTPStatus.NOT_FOUND, "side discussion not found")
            if not discussion["enabled"]:
                return self.error(HTTPStatus.BAD_REQUEST, "当前讨论使用的模型已停用")
            if not str(discussion["api_key"] or "").strip():
                return self.error(HTTPStatus.BAD_REQUEST, "当前模型尚未配置 API Key")
            ts = now()
            conn.execute(
                """
                INSERT INTO side_discussion_messages(discussion_id, role, content, created_at)
                VALUES (?, 'user', ?, ?)
                """,
                (discussion_id, content, ts),
            )
            conn.execute(
                "UPDATE side_discussions SET updated_at=? WHERE id=? AND user_id=?",
                (ts, discussion_id, user_id),
            )
            history = conn.execute(
                """
                SELECT role, content
                FROM side_discussion_messages
                WHERE discussion_id=?
                ORDER BY id ASC
                LIMIT 60
                """,
                (discussion_id,),
            ).fetchall()

        source_role = "槑槑回复" if discussion["source_role"] == "assistant" else "用户消息"
        system_context = (
            "你正在围绕主会话中的一段引用内容进行独立讨论。\n"
            f"主会话标题：{discussion['conversation_title']}\n"
            f"来源：{source_role}\n\n"
            "引用内容：\n"
            f"{discussion['selected_text']}\n\n"
            "请只依据这段引用内容和用户在侧边栏提出的问题回答。"
            "不要假设你已经看过完整主会话；如果材料不足，请明确说明。"
        )
        upstream_messages = [{"role": "system", "content": system_context}]
        if str(discussion["system_prompt"] or "").strip():
            upstream_messages.append(
                {"role": "system", "content": str(discussion["system_prompt"]).strip()}
            )
        upstream_messages.extend(
            {"role": row["role"], "content": row["content"]} for row in history
        )

        def make_payload(include_usage):
            payload = {
                "model": discussion["model"],
                "messages": upstream_messages,
                "stream": True,
            }
            if include_usage:
                payload["stream_options"] = {"include_usage": True}
            return payload

        def open_upstream(payload):
            request = urllib.request.Request(
                str(discussion["base_url"]).rstrip("/") + "/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={
                    "Authorization": "Bearer " + str(discussion["api_key"]).strip(),
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "User-Agent": "ai-platform/2.0",
                },
                method="POST",
            )
            return urllib.request.urlopen(request, timeout=120)

        try:
            response = open_upstream(make_payload(True))
        except urllib.error.HTTPError as exc:
            detail = exc.read(65536).decode(errors="replace")
            if exc.code == 400 and usage_option_rejected(detail):
                try:
                    response = open_upstream(make_payload(False))
                except urllib.error.HTTPError as retry:
                    retry_detail = retry.read(65536).decode(errors="replace")
                    return self.error(
                        HTTPStatus.BAD_GATEWAY,
                        f"侧边讨论模型请求失败（{retry.code}）",
                        retry_detail,
                    )
                except Exception as retry:
                    return self.error(HTTPStatus.BAD_GATEWAY, "侧边讨论模型请求失败", str(retry))
            else:
                return self.error(
                    HTTPStatus.BAD_GATEWAY,
                    f"侧边讨论模型请求失败（{exc.code}）",
                    detail,
                )
        except Exception as exc:
            return self.error(HTTPStatus.BAD_GATEWAY, "侧边讨论模型请求失败", str(exc))

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        assistant_parts = []
        reasoning_parts = []
        usage_data = None
        buffer = ""
        try:
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except Exception:
                    pass
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
                        usage_data = event["usage"]
                    choice = (event.get("choices") or [{}])[0]
                    if isinstance(choice.get("usage"), dict):
                        usage_data = choice["usage"]
                    delta = choice.get("delta") or {}
                    message = choice.get("message") or {}
                    piece = delta.get("content") or message.get("content") or ""
                    reasoning_piece = (
                        delta.get("reasoning_content")
                        or message.get("reasoning_content")
                        or delta.get("reasoning")
                        or message.get("reasoning")
                        or ""
                    )
                    if piece:
                        assistant_parts.append(str(piece))
                    if reasoning_piece:
                        reasoning_parts.append(str(reasoning_piece))
        finally:
            response.close()

        assistant_text = "".join(assistant_parts).strip()
        reasoning_text = "".join(reasoning_parts).strip()
        assistant_text, think_reasoning = split_think_blocks(assistant_text)
        if think_reasoning:
            reasoning_text = (reasoning_text + "\n\n" + think_reasoning).strip()
        if not assistant_text:
            return
        prompt_tokens, completion_tokens, total_tokens = parse_usage_tokens(usage_data)
        input_price = parse_price(discussion["input_price_per_million"])
        output_price = parse_price(discussion["output_price_per_million"])
        estimated_cost = estimate_request_cost(
            prompt_tokens,
            completion_tokens,
            input_price,
            output_price,
            bool(discussion["cost_enabled"]),
        )
        created_at = now()
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO side_discussion_messages(
                  discussion_id, role, content, reasoning_content,
                  input_tokens, output_tokens, total_tokens,
                  estimated_cost, actual_model, created_at
                )
                VALUES (?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    discussion_id,
                    assistant_text,
                    reasoning_text,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    estimated_cost,
                    discussion["model"],
                    created_at,
                ),
            )
            conn.execute(
                "UPDATE side_discussions SET updated_at=? WHERE id=? AND user_id=?",
                (created_at, discussion_id, user_id),
            )
            add_daily_usage(
                conn,
                user_id,
                created_at,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                estimated_cost,
            )
        event = {
            "type": "message_saved",
            "discussion_id": discussion_id,
            "message_id": cursor.lastrowid,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated_cost": estimated_cost,
            },
        }
        try:
            self.wfile.write(("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()
        except Exception:
            pass

    def handle_side_discussion_conversation(self):
        user_id = self.current_user()["id"]
        discussion_id = self.side_discussion_id_from_path()
        with db() as conn:
            discussion = self.side_discussion_row(conn, discussion_id, user_id)
            if not discussion:
                return self.error(HTTPStatus.NOT_FOUND, "side discussion not found")
            model = conn.execute(
                "SELECT id FROM models WHERE id=? AND enabled=1",
                (discussion["model_id"],),
            ).fetchone()
            if not model:
                return self.error(HTTPStatus.BAD_REQUEST, "当前讨论使用的模型已停用")
            side_messages = conn.execute(
                """
                SELECT *
                FROM side_discussion_messages
                WHERE discussion_id=?
                ORDER BY id ASC
                """,
                (discussion_id,),
            ).fetchall()
            conversation_id = b64_token(12)
            ts = now()
            title = ("侧边讨论：" + discussion["title"])[:80]
            conn.execute(
                """
                INSERT INTO conversations(id, user_id, title, model_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (conversation_id, user_id, title, discussion["model_id"], ts, ts),
            )
            source_role = "槑槑回复" if discussion["source_role"] == "assistant" else "用户消息"
            source_message = (
                f"围绕以下{source_role}继续讨论：\n\n"
                f"> {discussion['selected_text'].replace(chr(10), chr(10) + '> ')}"
            )
            conn.execute(
                """
                INSERT INTO messages(user_id, conversation_id, role, content, created_at)
                VALUES (?, ?, 'user', ?, ?)
                """,
                (user_id, conversation_id, source_message, ts),
            )
            for message in side_messages:
                conn.execute(
                    """
                    INSERT INTO messages(
                      user_id, conversation_id, role, content, reasoning_content,
                      actual_model, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        conversation_id,
                        message["role"],
                        message["content"],
                        message["reasoning_content"],
                        message["actual_model"],
                        message["created_at"],
                    ),
                )
            row = conn.execute(
                """
                SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision,
                       m.supports_native_web_search
                FROM conversations c
                JOIN models m ON m.id=c.model_id
                WHERE c.id=? AND c.user_id=?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return self.json({"conversation": conversation_row(row)}, status=HTTPStatus.CREATED)

    def handle_conversations(self):
        user = self.current_user()
        user_id = user["id"]
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision,
                           m.supports_native_web_search
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
                SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision,
                       m.supports_native_web_search
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
                SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision,
                       m.supports_native_web_search
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
                SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision,
                       m.supports_native_web_search
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
                       estimated_cost,
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
                SELECT c.*, m.name AS model_name, m.base_url, m.api_key, m.model, m.system_prompt,
                       m.supports_vision, m.supports_native_web_search, m.enabled,
                       m.input_price_per_million,
                       m.output_price_per_million, m.cost_enabled
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

            use_native_search = bool(
                use_web_search and convo["supports_native_web_search"]
            )
            if use_web_search and not use_native_search:
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
                title = visible_user_question(user_message_content).replace("\n", " ")[:28] or "图片理解"
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

        def make_upstream_messages(results):
            runtime_context = build_runtime_context(bool(results))
            if use_native_search:
                runtime_context += (
                    "\n本次请求已启用百炼 web_search 工具。必须先调用该工具检索最新资料，"
                    "再依据检索结果回答；不要跳过搜索，也不要假装已经搜索。"
                )
            upstream_messages = [
                {"role": "system", "content": runtime_context}
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
            return upstream_messages

        def make_payload(results, include_usage=True):
            payload = {
                "model": convo["model"],
                "messages": make_upstream_messages(results),
                "stream": True,
            }
            if include_usage:
                payload["stream_options"] = {"include_usage": True}
            return payload

        def make_native_search_payload():
            return {
                "model": convo["model"],
                "input": responses_input_from_messages(make_upstream_messages([])),
                "tools": [{"type": "web_search"}],
                "stream": True,
            }

        def open_upstream(payload, native_search=False):
            endpoint = "/responses" if native_search else "/chat/completions"
            request = urllib.request.Request(
                convo["base_url"].rstrip("/") + endpoint,
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

        payload = make_native_search_payload() if use_native_search else make_payload(search_results)
        search_fallback_notice = ""

        def upstream_error_message(code, detail):
            if code == 403 and (
                "free quota has been exhausted" in detail.lower()
                or "use free tier only" in detail.lower()
            ):
                return "百炼免费额度已用完，请在对应阿里云账号完成付费配置或关闭仅使用免费额度。"
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
            response = (
                open_upstream(payload, native_search=True)
                if use_native_search
                else open_upstream_with_usage_fallback(search_results)
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read(65536).decode(errors="replace")
            if not use_native_search and search_results and exc.code == 400 and "data_inspection_failed" in detail:
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

        def emit_client_event(event):
            try:
                self.wfile.write(
                    ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
                )
                self.wfile.flush()
                return True
            except Exception:
                return False

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
                if not use_native_search:
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
                    if use_native_search:
                        event_type = str(event.get("type") or "")
                        if event_type == "response.output_text.delta":
                            piece = str(event.get("delta") or "")
                            if piece:
                                assistant_parts.append(piece)
                                emit_client_event(
                                    {
                                        "choices": [
                                            {
                                                "index": 0,
                                                "delta": {"content": piece},
                                                "finish_reason": None,
                                            }
                                        ]
                                    }
                                )
                        elif event_type in (
                            "response.reasoning_summary_text.delta",
                            "response.reasoning_text.delta",
                        ):
                            reasoning_piece = str(event.get("delta") or "")
                            if reasoning_piece:
                                reasoning_parts.append(reasoning_piece)
                                emit_client_event(
                                    {
                                        "choices": [
                                            {
                                                "index": 0,
                                                "delta": {
                                                    "reasoning_content": reasoning_piece
                                                },
                                                "finish_reason": None,
                                            }
                                        ]
                                    }
                                )
                        elif event_type == "response.output_item.done":
                            native_results = native_search_results_from_item(
                                event.get("item"), search_config["result_count"]
                            )
                            known_urls = {item["url"] for item in search_results}
                            for item in native_results:
                                if item["url"] not in known_urls:
                                    search_results.append(item)
                                    known_urls.add(item["url"])
                                if len(search_results) >= search_config["result_count"]:
                                    break
                            if search_results:
                                emit_client_event(
                                    {
                                        "type": "search_status",
                                        "status": "done",
                                        "count": len(search_results),
                                        "sources": public_sources(search_results),
                                    }
                                )
                        elif event_type == "response.completed":
                            completed = event.get("response") or {}
                            if isinstance(completed.get("usage"), dict):
                                usage_data = completed.get("usage")
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
        message_created_at = now()
        input_price_snapshot = parse_price(convo["input_price_per_million"])
        output_price_snapshot = parse_price(convo["output_price_per_million"])
        estimated_cost = estimate_request_cost(
            prompt_tokens,
            completion_tokens,
            input_price_snapshot,
            output_price_snapshot,
            bool(convo["cost_enabled"]),
        )
        if assistant_text:
            with db() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO messages(
                      user_id, conversation_id, role, content, reasoning_content,
                      prompt_tokens, completion_tokens, total_tokens,
                      estimated_cost, cost_input_price, cost_output_price, cost_model_id, actual_model,
                      created_at
                    )
                    VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        conversation_id,
                        assistant_text,
                        reasoning_text,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                        estimated_cost,
                        input_price_snapshot if convo["cost_enabled"] else 0,
                        output_price_snapshot if convo["cost_enabled"] else 0,
                        convo["model_id"] if convo["cost_enabled"] else "",
                        convo["model"],
                        message_created_at,
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
                add_daily_usage(
                    conn,
                    user_id,
                    message_created_at,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    estimated_cost,
                )
            saved_event = {
                "type": "message_saved",
                "message_id": message_id,
                "conversation_id": conversation_id,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "estimated_cost": estimated_cost,
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


if __name__ == "__main__":
    main()
