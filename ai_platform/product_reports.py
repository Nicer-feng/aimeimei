"""账号隔离的每日产品推送，复用 APNs 设备并独立管理频道订阅。"""
import hashlib
import json
import re
import threading
from datetime import date

from .daily_reports import notification_preview as daily_notification_preview, report_row, send_apns
from .runtime import now

RECIPIENTS = ("feng", "czq")
_delivery_lock = threading.Lock()


def init_product_report_tables(conn):
    columns = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    for name in ("product_reports_enabled", "product_push_enabled", "product_push_after_id"):
        if name not in columns:
            conn.execute(f"ALTER TABLE users ADD COLUMN {name} INTEGER NOT NULL DEFAULT 0")
    if "product_reports_enabled" not in columns:
        # 仅在首次迁移时为已有目标账号开启，管理员之后的选择不会被覆盖。
        conn.execute("UPDATE users SET product_reports_enabled=1,product_push_enabled=1 WHERE username IN ('feng','czq')")
    conn.executescript("""
      CREATE TABLE IF NOT EXISTS product_report_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), paused INTEGER NOT NULL DEFAULT 0,
        push_after_id INTEGER NOT NULL DEFAULT 0
      );
      INSERT OR IGNORE INTO product_report_settings(id) VALUES(1);
      CREATE TABLE IF NOT EXISTS product_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES users(id),
        report_date TEXT NOT NULL, simulation INTEGER NOT NULL DEFAULT 0,
        title TEXT NOT NULL, content TEXT NOT NULL, content_hash TEXT NOT NULL,
        created_at INTEGER NOT NULL, read_at INTEGER NOT NULL DEFAULT 0,
        UNIQUE(user_id, report_date, simulation)
      );
      CREATE TABLE IF NOT EXISTS product_push_subscriptions (
        device_id INTEGER PRIMARY KEY REFERENCES report_push_devices(id) ON DELETE CASCADE,
        created_at INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS product_push_deliveries (
        report_id INTEGER NOT NULL REFERENCES product_reports(id),
        device_id INTEGER NOT NULL REFERENCES report_push_devices(id) ON DELETE CASCADE,
        state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        updated_at INTEGER NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '',
        PRIMARY KEY(report_id, device_id)
      );
      CREATE INDEX IF NOT EXISTS idx_product_reports_user ON product_reports(user_id,id DESC);
    """)


def configure_user_product_reports(conn, uid, data, reactivated=False):
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    values = []
    for key in ("product_reports_enabled", "product_push_enabled"):
        value = data.get(key, bool(row[key]))
        if not isinstance(value, bool):
            raise ValueError("产品推送开关必须为布尔值")
        values.append(int(value))
    enabled, push = values
    if row["username"] not in RECIPIENTS and (enabled or push):
        raise ValueError("每日产品推送仅开放给 feng 和 czq")
    effective = bool(enabled and push and row["is_active"] and row["username"] in RECIPIENTS)
    changed = (enabled != row["product_reports_enabled"] or push != row["product_push_enabled"]
               or not row["is_active"])
    if changed or reactivated:
        cutoff = conn.execute("SELECT COALESCE(MAX(id),0) FROM product_reports").fetchone()[0]
        conn.execute("UPDATE users SET product_push_after_id=? WHERE id=?", (cutoff, uid))
    conn.execute("UPDATE users SET product_reports_enabled=?,product_push_enabled=? WHERE id=?", (enabled,push,uid))
    if changed or not effective:
        conn.execute("UPDATE product_push_deliveries SET state='cancelled',reason='PermissionChanged' WHERE report_id IN (SELECT id FROM product_reports WHERE user_id=?) AND state IN ('pending','sending')", (uid,))


def push_allowed(conn, uid, rid):
    return bool(conn.execute("""SELECT 1 FROM users u,product_report_settings g
        WHERE u.id=? AND u.username IN ('feng','czq') AND u.is_active=1
        AND u.product_reports_enabled=1 AND u.product_push_enabled=1
        AND g.id=1 AND g.paused=0 AND ?>u.product_push_after_id AND ?>g.push_after_id""", (uid,rid,rid)).fetchone())


def ios_session(conn, uid, session_hash, installation_id):
    row = conn.execute("""SELECT a.metadata_json FROM sessions s
        JOIN auth_session_history h ON h.token_hash=s.token_hash AND h.user_id=s.user_id
        JOIN auth_devices a ON a.id=h.device_id AND a.user_id=s.user_id
        WHERE s.user_id=? AND s.token_hash=? AND s.expires_at>? AND a.installation_id=?""",
        (uid,session_hash,now(),installation_id)).fetchone()
    try:
        return bool(row and json.loads(row[0]).get("platform") == "ios")
    except (ValueError, AttributeError):
        return False


def subscribed_ios_devices(conn, uid):
    rows = conn.execute("""SELECT d.* FROM report_push_devices d
        JOIN product_push_subscriptions p ON p.device_id=d.id WHERE d.user_id=?""", (uid,)).fetchall()
    return [r for r in rows if ios_session(conn,uid,r["session_hash"],r["installation_id"])]


def notification_preview(content):
    return daily_notification_preview(content).replace("点击查看完整日报", "点击查看完整产品推送").replace("今日日报已更新，点击查看详情", "今日产品推送已更新，点击查看详情")


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
    title = f"每日产品推送{' · 模拟' if simulation else ''} · {day}"
    reports, skipped = [], []
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT user_id,content_hash FROM product_reports WHERE report_date=? AND simulation=?", (day,int(simulation))).fetchall()
        if any(row["content_hash"] != digest for row in previous):
            raise ValueError("当日产品推送已存在且正文不同，未覆盖旧记录")
        audience = {row["user_id"] for row in previous}
        owners = []
        for row in conn.execute("SELECT id,username FROM users WHERE is_active=1 AND product_reports_enabled=1 AND username IN ('feng','czq') ORDER BY created_at,rowid"):
            if previous and row["id"] not in audience:
                skipped.append(row["username"])
            else:
                owners.append((row["username"],row["id"]))
        # 所有接收人一次事务保存；通知失败也不会丢失正文。
        for username, uid in owners:
            inserted = conn.execute("INSERT OR IGNORE INTO product_reports(user_id,report_date,simulation,title,content,content_hash,created_at) VALUES(?,?,?,?,?,?,?)",
                         (uid,day,int(simulation),title,content,digest,now()))
            row = conn.execute("SELECT * FROM product_reports WHERE user_id=? AND report_date=? AND simulation=?", (uid,day,int(simulation))).fetchone()
            if row["content_hash"] != digest:
                raise ValueError("当日产品推送已存在且正文不同，未覆盖旧记录")
            devices = subscribed_ios_devices(conn,uid)
            if inserted.rowcount == 1 and push_allowed(conn,uid,row["id"]):
                conn.executemany("INSERT OR IGNORE INTO product_push_deliveries(report_id,device_id) VALUES(?,?)", [(row["id"],d["id"]) for d in devices])
            push = bool(conn.execute("SELECT product_push_enabled FROM users WHERE id=?", (uid,)).fetchone()[0])
            paused = bool(conn.execute("SELECT paused FROM product_report_settings WHERE id=1").fetchone()[0])
            reports.append({"username":username,"report_id":row["id"],"registered_devices":len(devices),
                            "created":inserted.rowcount == 1,"push_enabled":push,"push_paused":paused})
    totals = {"accepted":0,"pending":0,"invalid":0}
    for report in reports:
        report["delivery"] = deliver_pending(report["report_id"])
        with db() as conn:
            report["delivery_totals"] = {row[0]:row[1] for row in conn.execute("SELECT state,COUNT(*) FROM product_push_deliveries WHERE report_id=? GROUP BY state", (report["report_id"],))}
        for state in totals:
            totals[state] += report["delivery"][state]
    return {"report_id":reports[0]["report_id"] if reports else None,"registered_devices":sum(r["registered_devices"] for r in reports),
            "delivery":totals,"reports":reports,"recipient_count":len(reports),"skipped_new_recipients":skipped}


def deliver_pending(report_id=None):
    from .database import db
    counts = {"accepted":0,"pending":0,"invalid":0}
    with _delivery_lock:
        with db() as conn:
            rows = conn.execute("""SELECT p.*,d.token,d.session_hash,d.installation_id,r.title,r.content,r.user_id
                FROM product_push_deliveries p JOIN product_push_subscriptions sub ON sub.device_id=p.device_id
                JOIN report_push_devices d ON d.id=p.device_id JOIN product_reports r ON r.id=p.report_id
                JOIN users u ON u.id=r.user_id
                WHERE (p.state='pending' OR (p.state='sending' AND p.updated_at<?))
                  AND r.created_at>? AND u.is_active=1 AND u.username IN ('feng','czq')
                  AND u.product_reports_enabled=1 AND u.product_push_enabled=1 AND d.user_id=r.user_id
                  AND r.id>u.product_push_after_id AND EXISTS(SELECT 1 FROM product_report_settings g WHERE g.id=1 AND g.paused=0 AND r.id>g.push_after_id)
                  AND (? IS NULL OR r.id=?) ORDER BY r.id LIMIT 20""",
                (now()-120,now()-86400,report_id,report_id)).fetchall()
        for row in rows:
            with db() as conn:
                if not push_allowed(conn,row["user_id"],row["report_id"]) or not ios_session(conn,row["user_id"],row["session_hash"],row["installation_id"]):
                    continue
                changed = conn.execute("UPDATE product_push_deliveries SET state='sending',updated_at=?,attempts=attempts+1 WHERE report_id=? AND device_id=? AND (state='pending' OR (state='sending' AND updated_at<?))",
                    (now(),row["report_id"],row["device_id"],now()-120)).rowcount
            if not changed:
                continue
            payload = {"aps":{"alert":{"title":row["title"],"body":notification_preview(row["content"])},"sound":"default","thread-id":"product-daily"},
                       "report_id":row["report_id"],"kind":"product_daily"}
            try:
                state, reason = send_apns(row["token"],payload,f"product-{row['report_id']}")
            except Exception:
                state, reason = "pending","TransportFailure"
            with db() as conn:
                conn.execute("UPDATE product_push_deliveries SET state=?,reason=?,updated_at=? WHERE report_id=? AND device_id=? AND state='sending'", (state,reason,now(),row["report_id"],row["device_id"]))
            counts[state] += 1
    return counts


def publication_status():
    from .database import db
    with db() as conn:
        paused = bool(conn.execute("SELECT paused FROM product_report_settings WHERE id=1").fetchone()[0])
        users = [{"username":row["username"],"is_active":bool(row["is_active"]),
                  "product_reports_enabled":bool(row["product_reports_enabled"]),"product_push_enabled":bool(row["product_push_enabled"]),
                  "registered_devices":len(subscribed_ios_devices(conn,row["id"]))}
                 for row in conn.execute("SELECT * FROM users WHERE username IN ('feng','czq') ORDER BY username")]
    return {"paused":paused,"recipients":users}


def recent_history():
    from .database import db
    with db() as conn:
        rows = conn.execute("""SELECT report_date,title,content,MAX(created_at) AS created_at FROM product_reports
            WHERE simulation=0 GROUP BY report_date,content_hash ORDER BY report_date DESC LIMIT 30""").fetchall()
    reports = []
    for row in rows:
        item = dict(row)
        # 选题去重保留全部来源链接；正文只给摘要，避免长期任务读取过量历史。
        item["source_urls"] = list(dict.fromkeys(url.rstrip(".,;!?，。；！？") for url in re.findall(r"https?://[^\s<>()\[\]`\"']+",item["content"])))
        item["content_truncated"] = len(item["content"]) > 2000
        item["content"] = item["content"][:2000]
        reports.append(item)
    return {"reports":reports}
