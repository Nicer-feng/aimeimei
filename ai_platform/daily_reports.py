"""账号隔离的只读日报与 APNs 投递，不接入模型会话。"""
import hashlib
import json
import re
import threading
from datetime import date
from pathlib import Path

from .runtime import now, read_json
from .settings import DATA_DIR

TOPIC = "asia.feng.aimeimei"
APNS_ORIGIN = "https://api.push.apple.com"
_delivery_lock = threading.Lock()


def init_daily_report_tables(conn):
    columns = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    for name in ("daily_reports_enabled", "daily_push_enabled", "daily_push_after_id"):
        if name not in columns:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
    if "daily_reports_enabled" not in columns:
        # 只迁移已有接收人一次，后续完全由管理员配置。
        conn.execute("UPDATE users SET daily_reports_enabled=1,daily_push_enabled=1 WHERE username IN ('feng','czq')")
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS daily_report_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL DEFAULT 0,
        push_after_id INTEGER NOT NULL DEFAULT 0
      );
      INSERT OR IGNORE INTO daily_report_settings(id) VALUES(1);
      CREATE TABLE IF NOT EXISTS daily_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES users(id),
        report_date TEXT NOT NULL, simulation INTEGER NOT NULL DEFAULT 0,
        title TEXT NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL,
        created_at INTEGER NOT NULL, read_at INTEGER NOT NULL DEFAULT 0,
        UNIQUE(user_id, report_date, simulation)
      );
      CREATE TABLE IF NOT EXISTS report_push_devices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES users(id), installation_id TEXT NOT NULL,
        token TEXT NOT NULL, session_hash TEXT NOT NULL, updated_at INTEGER NOT NULL,
        UNIQUE(user_id, installation_id)
      );
      CREATE TABLE IF NOT EXISTS report_push_deliveries (
        report_id INTEGER NOT NULL REFERENCES daily_reports(id),
        device_id INTEGER NOT NULL REFERENCES report_push_devices(id) ON DELETE CASCADE,
        state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(report_id, device_id)
      );
      CREATE INDEX IF NOT EXISTS idx_daily_reports_user ON daily_reports(user_id,id DESC);
    """)


def configure_user_reports(conn, uid, data, reactivated=False):
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    values = []
    for key in ("daily_reports_enabled", "daily_push_enabled"):
        value = data.get(key, bool(row[key]))
        if not isinstance(value, bool):
            raise ValueError("日报开关必须为布尔值")
        values.append(int(value))
    enabled, push = values
    effective = bool(enabled and push and row["is_active"])
    changed = (enabled != row["daily_reports_enabled"] or push != row["daily_push_enabled"]
               or not row["is_active"])
    if changed or reactivated:
        cutoff = conn.execute("SELECT COALESCE(MAX(id),0) FROM daily_reports").fetchone()[0]
        conn.execute("UPDATE users SET daily_push_after_id=? WHERE id=?", (cutoff, uid))
    conn.execute("UPDATE users SET daily_reports_enabled=?,daily_push_enabled=? WHERE id=?", (enabled,push,uid))
    if changed or not effective:
        conn.execute("UPDATE report_push_deliveries SET state='cancelled',reason='PermissionChanged' WHERE report_id IN (SELECT id FROM daily_reports WHERE user_id=?) AND state IN ('pending','sending')", (uid,))


def push_allowed(conn, uid, rid):
    return bool(conn.execute("""SELECT 1 FROM users u,daily_report_settings g
        WHERE u.id=? AND u.is_active=1 AND u.daily_reports_enabled=1 AND u.daily_push_enabled=1
        AND g.id=1 AND g.paused=0 AND ?>u.daily_push_after_id AND ?>g.push_after_id""", (uid,rid,rid)).fetchone())


def report_row(row):
    return {key: row[key] for key in ("id", "report_date", "title", "content", "created_at", "read_at")} | {"simulation": bool(row["simulation"])}


def notification_preview(content):
    """只摘取日报前三段纯文本；不修改完整正文，也不调用模型。"""
    paragraphs, current = [], []
    fence = None
    for raw in content.splitlines():
        line = re.sub(r"^(?:>\s*)+", "", raw.strip())
        marker = re.match(r"^(`{3,}|~{3,})", line)
        if fence:
            if re.fullmatch(re.escape(fence[0]) + "{" + str(len(fence)) + ",}\\s*", line):
                fence = None
            continue
        if not line or marker or re.match(r"^#{1,6}(?:\s|$)", line) or re.fullmatch(r"(?:[-*_]\s*){3,}", line):
            if current:
                paragraphs.append(" ".join(current))
                current = []
            if marker:
                fence = marker.group(1)
            continue
        item = re.match(r"^(?:[-+*]|\d+[.)])\s+(.*)", line)
        if item and current:
            paragraphs.append(" ".join(current))
            current = []
        current.append(item.group(1) if item else line)
    if current:
        paragraphs.append(" ".join(current))

    points = []
    for text in paragraphs:
        text = re.sub(r"!?\[([^\]]*)\]\([^\n)]*\)", r"\1", text)
        text = re.sub(r"(`+)(.*?)\1", r"\2", text)
        text = re.sub(r"(\*\*|__|~~)(.*?)\1", r"\2", text)
        text = re.sub(r"(?<!\*)\*(\S(?:.*?\S)?)\*(?!\*)", r"\1", text)
        text = re.sub(r"(?<!\w)_(\S(?:.*?\S)?)_(?!\w)", r"\1", text)
        text = " ".join(text.split())
        if not text:
            continue
        # 每条最多 90 字，保留三条，让后面的模块也有机会出现在预览里。
        points.append("- " + (text[:89].rstrip() + "…" if len(text) > 90 else text))
        if len(points) == 3:
            break
    return "\n".join(points) + "\n点击查看完整日报" if points else "今日日报已更新，点击查看详情"


def publish_report(data):
    from .database import db
    if not isinstance(data, dict) or set(data) - {"date", "content", "simulation"}:
        raise ValueError("仅接受 date、content、simulation")
    day = data.get("date", "")
    try:
        if date.fromisoformat(day).isoformat() != day:
            raise ValueError()
    except (TypeError, ValueError):
        raise ValueError("date 必须是 YYYY-MM-DD") from None
    content, simulation = data.get("content"), data.get("simulation", False)
    if not isinstance(simulation, bool) or not isinstance(content, str) or not 1 <= len(content.strip()) <= 30000:
        raise ValueError("正文必须为 1 至 30000 字，simulation 必须为布尔值")
    content = content.strip()
    digest = hashlib.sha256(content.encode()).hexdigest()
    title = f"研发日报{' · 模拟' if simulation else ''} · {day}"
    reports, skipped = [], []
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT user_id,content_hash FROM daily_reports WHERE report_date=? AND simulation=?", (day,int(simulation))).fetchall()
        if any(row["content_hash"] != digest for row in previous):
            raise ValueError("当日日报已存在且正文不同，未覆盖旧记录")
        audience = {row["user_id"] for row in previous}
        owners = []
        for row in conn.execute("SELECT id,username FROM users WHERE is_active=1 AND daily_reports_enabled=1 ORDER BY created_at,rowid"):
            if previous and row["id"] not in audience:
                skipped.append(row["username"])
            else:
                owners.append((row["username"],row["id"]))
        # 所有账号共用一次事务；任一正文冲突时，不给其他账号留下部分发布。
        for username, uid in owners:
            inserted = conn.execute("INSERT OR IGNORE INTO daily_reports(user_id,report_date,simulation,title,content,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                         (uid, day, int(simulation), title, content, digest, now()))
            row = conn.execute("SELECT * FROM daily_reports WHERE user_id=? AND report_date=? AND simulation=?", (uid, day, int(simulation))).fetchone()
            if row["content_hash"] != digest:
                raise ValueError("当日日报已存在且正文不同，未覆盖旧记录")
            if push_allowed(conn, uid, row["id"]):
                conn.execute("INSERT OR IGNORE INTO report_push_deliveries(report_id,device_id) SELECT ?,id FROM report_push_devices WHERE user_id=?", (row["id"], uid))
            devices = conn.execute("SELECT COUNT(*) FROM report_push_devices WHERE user_id=?", (uid,)).fetchone()[0]
            push = bool(conn.execute("SELECT daily_push_enabled FROM users WHERE id=?", (uid,)).fetchone()[0])
            paused = bool(conn.execute("SELECT paused FROM daily_report_settings WHERE id=1").fetchone()[0])
            reports.append({"username": username, "report_id": row["id"], "registered_devices": devices,
                            "created": inserted.rowcount == 1, "push_enabled": push, "push_paused": paused})
    totals = {"accepted": 0, "pending": 0, "invalid": 0}
    for report in reports:
        report["delivery"] = deliver_pending(report["report_id"])
        with db() as conn:
            report["delivery_totals"] = {row[0]: row[1] for row in conn.execute("SELECT state,COUNT(*) FROM report_push_deliveries WHERE report_id=? GROUP BY state", (report["report_id"],))}
        for state in totals:
            totals[state] += report["delivery"][state]
    return {"report_id": reports[0]["report_id"] if reports else None, "registered_devices": sum(r["registered_devices"] for r in reports),
            "delivery": totals, "reports": reports, "recipient_count": len(reports), "skipped_new_recipients": skipped}


def send_apns(token, payload, collapse_id):
    import httpx
    import jwt
    config = read_json(DATA_DIR / "apns.json", {})
    key_path = Path(config.get("key_path", "/etc/ai-platform/apns/key.p8"))
    if not all(config.get(k) for k in ("key_id", "team_id")) or not key_path.is_file():
        return "pending", "NotConfigured"
    # TestFlight 使用生产 APNs，私钥和设备 token 不进入响应、异常或日志。
    auth = jwt.encode({"iss": config["team_id"], "iat": now()}, key_path.read_bytes(), algorithm="ES256", headers={"kid": config["key_id"]})
    with httpx.Client(http2=True, timeout=15, follow_redirects=False, trust_env=False) as client:
        response = client.post(APNS_ORIGIN + "/3/device/" + token,
            headers={"authorization": "bearer " + auth, "apns-topic": TOPIC,
                     "apns-push-type": "alert", "apns-priority": "10",
                     "apns-expiration": str(now() + 86400), "apns-collapse-id": collapse_id}, json=payload)
    if response.status_code == 200:
        return "accepted", ""
    try:
        reason = response.json().get("reason", "Unknown")
    except (ValueError, AttributeError):
        reason = "Unknown"
    allowed = {"BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic", "ExpiredProviderToken", "InvalidProviderToken", "Forbidden", "BadTopic", "TopicDisallowed", "TooManyRequests", "InternalServerError", "ServiceUnavailable", "Shutdown"}
    reason = reason if reason in allowed else "APNsRejected"
    state = "invalid" if reason in {"BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"} else "pending"
    return state, reason


def deliver_pending(report_id=None):
    from .database import db
    counts = {"accepted": 0, "pending": 0, "invalid": 0}
    # 单进程发布和注册互斥；外部重试使用同一数据库租约避免并发重复通知。
    with _delivery_lock:
        with db() as conn:
            rows = conn.execute("""SELECT p.*,d.token,r.title,r.content,r.user_id FROM report_push_deliveries p
                JOIN report_push_devices d ON d.id=p.device_id JOIN daily_reports r ON r.id=p.report_id
                JOIN users u ON u.id=r.user_id
                JOIN sessions s ON s.token_hash=d.session_hash AND s.user_id=d.user_id AND s.expires_at>strftime('%s','now')
                WHERE (p.state='pending' OR (p.state='sending' AND p.updated_at<?))
                  AND r.created_at>? AND u.is_active=1 AND u.daily_reports_enabled=1 AND u.daily_push_enabled=1 AND d.user_id=r.user_id
                  AND r.id>u.daily_push_after_id AND EXISTS(SELECT 1 FROM daily_report_settings g WHERE g.id=1 AND g.paused=0 AND r.id>g.push_after_id)
                  AND (? IS NULL OR r.id=?) ORDER BY r.id LIMIT 20""",
                (now()-120, now()-86400, report_id, report_id)).fetchall()
        for row in rows:
            with db() as conn:
                if not push_allowed(conn, row["user_id"], row["report_id"]):
                    continue
                changed = conn.execute("UPDATE report_push_deliveries SET state='sending',updated_at=?,attempts=attempts+1 WHERE report_id=? AND device_id=? AND (state='pending' OR (state='sending' AND updated_at<?))",
                    (now(), row["report_id"], row["device_id"], now()-120)).rowcount
            if not changed:
                continue
            payload = {"aps": {"alert": {"title": row["title"], "body": notification_preview(row["content"])}, "sound": "default", "thread-id": "frontend-daily"}, "report_id": row["report_id"], "kind": "frontend_daily"}
            try:
                state, reason = send_apns(row["token"], payload, f"daily-{row['report_id']}")
            except Exception:
                state, reason = "pending", "TransportFailure"
            with db() as conn:
                conn.execute("UPDATE report_push_deliveries SET state=?,reason=?,updated_at=? WHERE report_id=? AND device_id=? AND state='sending'", (state, reason, now(), row["report_id"], row["device_id"]))
            counts[state] += 1
    return counts


def valid_device(data):
    return (isinstance(data, dict) and isinstance(data.get("installation_id"), str)
            and re.fullmatch(r"[A-Za-z0-9-]{16,80}", data["installation_id"])
            and isinstance(data.get("token"), str) and re.fullmatch(r"[a-fA-F0-9]{32,512}", data["token"]))
