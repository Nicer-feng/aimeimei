"""独立口令、登录限流及服务端会话，不使用主站账号。"""

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

SESSION_TTL = 12 * 60 * 60
PASSWORD_ROUNDS = 310000
LOGIN_WINDOW = 15 * 60
LOGIN_LIMIT = 10


class LoginLimited(Exception):
    pass


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PASSWORD_ROUNDS)
    return f"pbkdf2_sha256${PASSWORD_ROUNDS}${salt}${digest.hex()}"


def verify_password(password, encoded):
    try:
        method, rounds, salt, expected = encoded.split("$")
        iterations = int(rounds)
        if method != "pbkdf2_sha256" or not 100000 <= iterations <= 2000000:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations)
        return hmac.compare_digest(actual.hex(), expected)
    except (TypeError, ValueError, AttributeError):
        return False


def configure_passwords(data_dir, passwords):
    if len(passwords) != 2 or any(not isinstance(p, str) or not 6 <= len(p) <= 256 for p in passwords):
        raise ValueError("需设置两个长度为 6 至 256 的密码")
    target_dir = Path(data_dir)
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = target_dir / "secrets.json"
    temporary = target_dir / (".secrets-" + secrets.token_hex(8))
    payload = json.dumps({"password_hashes": [hash_password(p) for p in passwords]}, ensure_ascii=False)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload + "\n")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


class NcdAuth:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.config_path = self.data_dir / "secrets.json"
        self.database_path = self.data_dir / "sessions.db"
        self.data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY,
                    expires_at INTEGER NOT NULL,
                    credential_version TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS login_attempts (
                    ip_hash TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS login_attempts_ip_time
                    ON login_attempts(ip_hash, created_at);
            """)
        os.chmod(self.database_path, 0o600)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.database_path, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def credentials(self):
        data = json.loads(self.config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("访问密码尚未配置")
        hashes = data.get("password_hashes")
        if not isinstance(hashes, list) or len(hashes) != 2 or not all(isinstance(p, str) for p in hashes):
            raise ValueError("访问密码尚未配置")
        version = hashlib.sha256(json.dumps(hashes).encode()).hexdigest()
        return hashes, version

    def login(self, password, ip):
        hashes, version = self.credentials()
        now = int(time.time())
        ip_hash = hashlib.sha256(ip.encode()).hexdigest()
        # 校验前预占一次尝试，避免并发请求绕过次数限制。
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM login_attempts WHERE created_at <= ?", (now - LOGIN_WINDOW,))
            count = conn.execute("SELECT COUNT(*) FROM login_attempts WHERE ip_hash = ?", (ip_hash,)).fetchone()[0]
            if count >= LOGIN_LIMIT:
                raise LoginLimited()
            conn.execute("INSERT INTO login_attempts VALUES (?, ?)", (ip_hash, now))
        # 两个哈希都校验，不通过响应时间暴露命中的是哪个口令。
        matches = [verify_password(password, encoded) for encoded in hashes]
        if not any(matches):
            return None
        token = secrets.token_urlsafe(32)
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ? OR credential_version != ?", (now, version))
            conn.execute("DELETE FROM login_attempts WHERE ip_hash = ?", (ip_hash,))
            conn.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                         (hashlib.sha256(token.encode()).hexdigest(), now + SESSION_TTL, version))
        return token

    def authenticated(self, token):
        if not token or len(token) > 128:
            return False
        _, version = self.credentials()
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM sessions WHERE token_hash = ? AND expires_at > ? AND credential_version = ?",
                               (hashlib.sha256(token.encode()).hexdigest(), int(time.time()), version)).fetchone()
        return row is not None

    def logout(self, token):
        with self.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
