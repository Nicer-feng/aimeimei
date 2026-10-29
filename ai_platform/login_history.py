"""仅供管理员查询的客户端声明、成功登录事件和独立会话历史。"""
import ipaddress
import json
import os
import re
from datetime import datetime, timedelta, timezone

import ua_parser

from .runtime import b64_token, now

_ua = ua_parser.parser
RETENTION_SECONDS = 90 * 86400
PLATFORMS = {"ios", "android", "web_desktop", "web_mobile", "unknown"}
AUTHORIZATIONS = {"unknown", "not_determined", "denied", "authorized", "provisional", "ephemeral", "not_supported"}
META_FIELDS = ("platform", "manufacturer", "model", "os_name", "os_version", "browser", "browser_version", "app_version", "app_build", "notification_authorization")


def init_login_history_tables(conn):
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS auth_devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id),
        installation_id TEXT NOT NULL, installation_known INTEGER NOT NULL DEFAULT 0,
        metadata_json TEXT NOT NULL, first_login_at INTEGER NOT NULL DEFAULT 0,
        last_login_at INTEGER NOT NULL DEFAULT 0, last_active_at INTEGER NOT NULL DEFAULT 0,
        first_reported_at INTEGER NOT NULL DEFAULT 0, reported_at INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL, UNIQUE(user_id,installation_id)
      );
      CREATE TABLE IF NOT EXISTS auth_session_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id),
        token_hash TEXT NOT NULL UNIQUE, device_id INTEGER REFERENCES auth_devices(id) ON DELETE SET NULL,
        created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL, logout_at INTEGER NOT NULL DEFAULT 0,
        last_active_at INTEGER NOT NULL, last_active_ip TEXT, first_reported_at INTEGER NOT NULL DEFAULT 0
      );
      CREATE TABLE IF NOT EXISTS auth_login_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL REFERENCES users(id),
        session_record_id INTEGER REFERENCES auth_session_history(id) ON DELETE SET NULL,
        device_id INTEGER REFERENCES auth_devices(id) ON DELETE SET NULL,
        logged_at INTEGER NOT NULL, source_ip TEXT, ip_source TEXT NOT NULL,
        platform TEXT NOT NULL, metadata_json TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS auth_history_maintenance (id INTEGER PRIMARY KEY CHECK(id=1), cleaned_at INTEGER NOT NULL DEFAULT 0);
      INSERT OR IGNORE INTO auth_history_maintenance(id) VALUES(1);
      CREATE INDEX IF NOT EXISTS idx_auth_events_user ON auth_login_events(user_id,id DESC);
      CREATE INDEX IF NOT EXISTS idx_auth_events_time ON auth_login_events(logged_at,id);
      CREATE INDEX IF NOT EXISTS idx_auth_events_platform ON auth_login_events(platform,id DESC);
      CREATE INDEX IF NOT EXISTS idx_auth_devices_user ON auth_devices(user_id,id DESC);
      CREATE INDEX IF NOT EXISTS idx_auth_sessions_device ON auth_session_history(device_id,last_active_at);
      CREATE INDEX IF NOT EXISTS idx_auth_devices_retention ON auth_devices(last_active_at,id);
      CREATE INDEX IF NOT EXISTS idx_auth_sessions_retention ON auth_session_history(last_active_at,id);
    """)


def resolve_client_ip(peer, forwarded, trusted=None):
    try:
        remote = ipaddress.ip_address(peer)
        networks = [ipaddress.ip_network(x.strip()) for x in (trusted if trusted is not None else os.environ.get("AI_PLATFORM_TRUSTED_PROXIES", "")).split(",") if x.strip()]
    except ValueError:
        return None, "unavailable"
    def is_trusted(address):
        return any(address.version == network.version and address in network for network in networks)
    if not is_trusted(remote):
        return str(remote), "direct"
    if not isinstance(forwarded, str) or len(forwarded) > 1024:
        return None, "unavailable_forwarded"
    try:
        parts = forwarded.split(",")
        if not 1 <= len(parts) <= 16 or not all(p.strip() for p in parts):
            raise ValueError()
        chain = [ipaddress.ip_address(p.strip()) for p in parts]
    except ValueError:
        return None, "unavailable_forwarded"
    for address in reversed(chain):
        if not is_trusted(address):
            return str(address), "trusted_forwarded"
    return str(chain[0]), "trusted_forwarded"


def request_ip(handler):
    values = handler.headers.get_all("X-Forwarded-For", [])
    return resolve_client_ip(handler.client_address[0], values[0] if len(values) == 1 else None)


def clean_text(value, limit=80):
    return "".join(c for c in value if c.isprintable())[:limit].strip() if isinstance(value, str) else ""


def client_metadata(client, user_agent):
    client = client if isinstance(client, dict) else {}
    install = client.get("installation_id", "")
    install = install if isinstance(install, str) and re.fullmatch(r"[A-Za-z0-9-]{16,80}", install) else ""
    agent = clean_text(user_agent, 1024)
    try:
        parsed = _ua.parse(agent)
        browser, system = parsed.user_agent, parsed.os
    except Exception:
        browser = system = None
    version = lambda item: ".".join(str(getattr(item, key, "") or "") for key in ("major", "minor", "patch", "patch_minor") if getattr(item, key, None))
    platform = client.get("platform")
    if platform not in ("ios", "android"):
        mobile = bool(re.search(r"Mobile|Android|iPhone|iPad|iPod", agent, re.I))
        platform = "web_mobile" if mobile else "web_desktop" if browser else "unknown"
    native = platform in ("ios", "android")
    authorization = client.get("notification_authorization", "unknown")
    meta = {"platform": platform, "manufacturer": clean_text(client.get("manufacturer")) if native else "",
        "model": clean_text(client.get("model")) if native else "",
        "os_name": ("iOS" if platform == "ios" else "Android") if native else clean_text(getattr(system, "family", "")),
        "os_version": clean_text(client.get("os_version")) if native else version(system),
        "browser": "" if native else clean_text(getattr(browser, "family", "")),
        "browser_version": "" if native else version(browser),
        "app_version": clean_text(client.get("app_version"),32) if native else "",
        "app_build": clean_text(client.get("app_build"),32) if native else "",
        "notification_authorization": authorization if isinstance(authorization,str) and authorization in AUTHORIZATIONS else "unknown"}
    return install, meta


def _device(conn, uid, install, meta, ts, login=False):
    known = bool(install)
    install = install or "unreported-" + b64_token(18)
    raw = json.dumps(meta, ensure_ascii=False, sort_keys=True)
    conn.execute("""INSERT INTO auth_devices(user_id,installation_id,installation_known,metadata_json,first_login_at,last_login_at,last_active_at,first_reported_at,reported_at,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,installation_id) DO UPDATE SET
        metadata_json=CASE WHEN excluded.reported_at>=auth_devices.reported_at THEN excluded.metadata_json ELSE auth_devices.metadata_json END,
        last_active_at=MAX(auth_devices.last_active_at,excluded.last_active_at),reported_at=MAX(auth_devices.reported_at,excluded.reported_at),
        first_reported_at=CASE WHEN auth_devices.first_reported_at=0 THEN excluded.first_reported_at WHEN excluded.first_reported_at=0 THEN auth_devices.first_reported_at ELSE MIN(auth_devices.first_reported_at,excluded.first_reported_at) END,
        first_login_at=CASE WHEN auth_devices.first_login_at=0 THEN excluded.first_login_at WHEN excluded.first_login_at=0 THEN auth_devices.first_login_at ELSE MIN(auth_devices.first_login_at,excluded.first_login_at) END,
        last_login_at=MAX(auth_devices.last_login_at,excluded.last_login_at)""",
        (uid,install,int(known),raw,ts if login else 0,ts if login else 0,ts,ts if known else 0,ts if known else 0,ts))
    return conn.execute("SELECT id FROM auth_devices WHERE user_id=? AND installation_id=?", (uid,install)).fetchone()[0]


def record_login(conn, uid, session_hash, created, expires, client, user_agent, ip, ip_source):
    install, meta = client_metadata(client, user_agent)
    did = _device(conn, uid, install, meta, created, login=True)
    cursor = conn.execute("INSERT INTO auth_session_history(user_id,token_hash,device_id,created_at,expires_at,last_active_at,last_active_ip,first_reported_at) VALUES(?,?,?,?,?,?,?,?)",
        (uid,session_hash,did,created,expires,created,ip,created if install else 0))
    conn.execute("INSERT INTO auth_login_events(user_id,session_record_id,device_id,logged_at,source_ip,ip_source,platform,metadata_json) VALUES(?,?,?,?,?,?,?,?)",
        (uid,cursor.lastrowid,did,created,ip,ip_source,meta["platform"],json.dumps(meta,ensure_ascii=False,sort_keys=True)))


def touch_session(conn, uid, session_hash, ip):
    ts = now()
    history = conn.execute("SELECT * FROM auth_session_history WHERE token_hash=? AND user_id=?", (session_hash,uid)).fetchone()
    if not history:
        session = conn.execute("SELECT * FROM sessions WHERE token_hash=? AND user_id=?", (session_hash,uid)).fetchone()
        if session:
            conn.execute("INSERT OR IGNORE INTO auth_session_history(user_id,token_hash,created_at,expires_at,last_active_at,last_active_ip) VALUES(?,?,?,?,?,?)", (uid,session_hash,session["created_at"],session["expires_at"],ts,ip))
    elif history["last_active_at"] <= ts-60:
        changed = conn.execute("UPDATE auth_session_history SET last_active_at=?,last_active_ip=? WHERE id=? AND last_active_at<=?", (ts,ip,history["id"],ts-60)).rowcount
        if changed and history["device_id"]:
            conn.execute("UPDATE auth_devices SET last_active_at=MAX(last_active_at,?) WHERE id=? AND user_id=?", (ts,history["device_id"],uid))


def report_device(conn, uid, session_hash, data, user_agent, ip):
    install, meta = client_metadata(data, user_agent)
    if not install:
        raise ValueError("安装实例 ID 未上报或格式不正确")
    touch_session(conn, uid, session_hash, ip)
    old = conn.execute("SELECT d.metadata_json,h.device_id FROM auth_session_history h JOIN auth_devices d ON d.id=h.device_id WHERE h.token_hash=? AND h.user_id=?", (session_hash,uid)).fetchone()
    if old and json.loads(old[0]).get("platform") in ("ios","android") and meta["platform"].startswith("web"):
        return
    ts = now()
    current = conn.execute("SELECT id,metadata_json,reported_at FROM auth_devices WHERE user_id=? AND installation_id=?", (uid,install)).fetchone()
    if current and old and old["device_id"] == current["id"] and json.loads(current["metadata_json"]) == meta and current["reported_at"] > ts-60:
        return
    did = _device(conn, uid, install, meta, ts)
    conn.execute("UPDATE auth_session_history SET device_id=?,first_reported_at=CASE WHEN first_reported_at=0 THEN ? ELSE first_reported_at END,last_active_at=?,last_active_ip=? WHERE token_hash=? AND user_id=?", (did,ts,ts,ip,session_hash,uid))


def session_state(row, ts=None):
    ts = now() if ts is None else ts
    if row["logout_at"]: return "logged_out"
    if row["expires_at"] <= ts: return "expired"
    if not row["account_active"]: return "account_disabled"
    return "valid" if row["session_exists"] else "invalid"


def cleanup_history(conn, limit=500):
    ts = now(); cutoff = ts-RETENTION_SECONDS
    last = conn.execute("SELECT cleaned_at FROM auth_history_maintenance WHERE id=1").fetchone()[0]
    if last > ts-300: return {}
    conn.execute("UPDATE auth_history_maintenance SET cleaned_at=? WHERE id=1", (ts,))
    counts = {}
    counts["events"] = conn.execute("DELETE FROM auth_login_events WHERE id IN (SELECT id FROM auth_login_events WHERE logged_at<? ORDER BY logged_at,id LIMIT ?)", (cutoff,limit)).rowcount
    counts["sessions"] = conn.execute("""DELETE FROM auth_session_history WHERE id IN (SELECT h.id FROM auth_session_history h WHERE h.last_active_at<?
        AND NOT EXISTS(SELECT 1 FROM sessions s WHERE s.token_hash=h.token_hash AND s.expires_at>?) ORDER BY h.last_active_at,h.id LIMIT ?)""", (cutoff,ts,limit)).rowcount
    counts["devices"] = conn.execute("""DELETE FROM auth_devices WHERE id IN (SELECT d.id FROM auth_devices d WHERE d.last_active_at<?
        AND NOT EXISTS(SELECT 1 FROM auth_session_history h JOIN sessions s ON s.token_hash=h.token_hash WHERE h.device_id=d.id AND s.expires_at>?) ORDER BY d.last_active_at,d.id LIMIT ?)""", (cutoff,ts,limit)).rowcount
    return counts


def date_bounds(params):
    values = []
    for key in ("from", "to"):
        value = params.get(key,[""])[0]
        if not value:
            values.append(None); continue
        day = datetime.strptime(value, "%Y-%m-%d")
        if day.strftime("%Y-%m-%d") != value: raise ValueError()
        if key == "to": day += timedelta(days=1)
        values.append(int(day.replace(tzinfo=timezone(timedelta(hours=8))).timestamp()))
    if all(v is not None for v in values) and values[0] >= values[1]: raise ValueError()
    return values
