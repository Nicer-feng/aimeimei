import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path

from .settings import (
    ADMIN_KEY_PATH,
    APP_ENTRY_PATH,
    BUILD_ID_PATH,
    CHANGELOG_PATH,
    DATA_DIR,
    FAMILY_PASSWORD_PATH,
    SECRETS_PATH,
    VERSION_PATH,
)


def now() -> int:
    return int(time.time())


def iso_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def today_text() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def local_day_start(ts=None) -> int:
    t = time.localtime(now() if ts is None else int(ts))
    return int(
        time.mktime(
            (
                t.tm_year,
                t.tm_mon,
                t.tm_mday,
                0,
                0,
                0,
                t.tm_wday,
                t.tm_yday,
                t.tm_isdst,
            )
        )
    )


def local_month_start(ts=None) -> int:
    t = time.localtime(now() if ts is None else int(ts))
    return int(
        time.mktime(
            (
                t.tm_year,
                t.tm_mon,
                1,
                0,
                0,
                0,
                t.tm_wday,
                t.tm_yday,
                t.tm_isdst,
            )
        )
    )


def date_text_from_ts(ts) -> str:
    try:
        value = int(ts or now())
    except (TypeError, ValueError):
        value = now()
    return time.strftime("%Y-%m-%d", time.localtime(value))


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


def current_build_info():
    version = current_app_version()
    build_id = ""
    updated_at = ""
    try:
        build_id = BUILD_ID_PATH.read_text(encoding="utf-8").strip()
        updated_at = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(BUILD_ID_PATH.stat().st_mtime),
        )
    except OSError:
        pass
    if not build_id:
        try:
            stamp = int(APP_ENTRY_PATH.stat().st_mtime)
        except OSError:
            stamp = now()
        build_id = f"{version or 'dev'}-{stamp}"
        updated_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(stamp))
    return {
        "version": f"v{version}" if version else "",
        "build_id": build_id,
        "updated_at": updated_at,
    }


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
