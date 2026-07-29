import sqlite3

from .runtime import b64_token, now, password_hash
from .settings import DATA_DIR, DB_PATH, DEFAULT_AI_USER_ID


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
