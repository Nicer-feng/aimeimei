import sqlite3

from .runtime import b64_token, now, password_hash, read_json
from .settings import (
    DATA_DIR,
    DB_PATH,
    DEFAULT_AI_USER_ID,
    LEGACY_CONFIG_PATH,
    SECRETS_PATH,
)


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def table_columns(conn, table):
    return {
        row["name"]
        for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


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
                secrets_data.get("family_password_hash")
                or password_hash("admin-" + b64_token(8)),
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


DEFAULT_PROMPT_TEMPLATES = [
    ("润色文字", "帮我润色这段文字，让它更自然、更正式"),
    ("朋友圈文案", "帮我写一段朋友圈文案，语气自然一点"),
    ("工作通知", "帮我写一份工作通知，简洁清楚"),
    ("活动宣传", "帮我写一段活动宣传文案，有吸引力但不要太夸张"),
    ("更礼貌表达", "帮我把这段话改得更礼貌"),
    ("工作总结", "帮我生成一份工作总结"),
    ("整理要点", "帮我把内容整理成条理清晰的要点"),
]


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
