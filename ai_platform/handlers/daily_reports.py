from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

from ..database import db
from ..daily_reports import report_row, valid_device, deliver_pending, push_allowed
from ..runtime import now, token_hash


class DailyReportHandlersMixin:
    def handle_admin_daily_report_settings(self):
        if self.command == "GET":
            with db() as conn:
                paused = bool(conn.execute("SELECT paused FROM daily_report_settings WHERE id=1").fetchone()[0])
            return self.json({"paused": paused})
        try:
            data = self.read_body(limit=4096)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        if not isinstance(data, dict) or set(data) != {"paused"} or not isinstance(data["paused"], bool):
            return self.error(HTTPStatus.BAD_REQUEST, "paused 必须为布尔值")
        with db() as conn:
            previous = bool(conn.execute("SELECT paused FROM daily_report_settings WHERE id=1").fetchone()[0])
            if previous != data["paused"]:
                cutoff = conn.execute("SELECT COALESCE(MAX(id),0) FROM daily_reports").fetchone()[0]
                conn.execute("UPDATE daily_report_settings SET paused=?,push_after_id=? WHERE id=1", (int(data["paused"]),cutoff))
                conn.execute("UPDATE report_push_deliveries SET state='cancelled',reason='GlobalPause' WHERE state IN ('pending','sending')")
        return self.json({"ok": True, "paused": data["paused"]})

    def handle_daily_reports(self):
        user = self.current_user()
        if not user["daily_reports_enabled"]:
            return self.error(HTTPStatus.NOT_FOUND, "not found")
        uid, path = user["id"], urlparse(self.path).path.rstrip("/")
        if path == "/api/daily-reports" and self.command == "GET":
            try:
                before = int(parse_qs(urlparse(self.path).query).get("before", ["0"])[0])
                if not 0 <= before <= 9223372036854775807:
                    raise ValueError()
            except ValueError:
                return self.error(HTTPStatus.BAD_REQUEST, "invalid cursor")
            with db() as conn:
                rows = conn.execute("SELECT * FROM daily_reports WHERE user_id=? AND (?=0 OR id<?) ORDER BY id DESC LIMIT 30", (uid,before,before)).fetchall()
                unread = conn.execute("SELECT COUNT(*) FROM daily_reports WHERE user_id=? AND read_at=0", (uid,)).fetchone()[0]
            return self.json({"reports": [report_row(r) for r in rows], "unread": unread, "next_before": rows[-1]["id"] if len(rows)==30 else None})
        if path == "/api/daily-reports/device":
            try:
                data = self.read_body(limit=4096)
            except Exception:
                return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
            if self.command == "DELETE":
                installation = data.get("installation_id") if isinstance(data, dict) else None
                if not isinstance(installation, str):
                    return self.error(HTTPStatus.BAD_REQUEST, "invalid installation")
                with db() as conn:
                    conn.execute("DELETE FROM report_push_devices WHERE user_id=? AND installation_id=?", (uid,installation))
                return self.json({"ok": True})
            if self.command != "POST":
                return self.error(HTTPStatus.METHOD_NOT_ALLOWED, "read only")
            if not valid_device(data):
                return self.error(HTTPStatus.BAD_REQUEST, "invalid device")
            if not user["daily_push_enabled"]:
                return self.error(HTTPStatus.FORBIDDEN, "日报通知已关闭")
            with db() as conn:
                old = conn.execute("SELECT * FROM report_push_devices WHERE user_id=? AND installation_id=?", (uid,data["installation_id"])).fetchone()
                if not old and conn.execute("SELECT COUNT(*) FROM report_push_devices WHERE user_id=?", (uid,)).fetchone()[0] >= 10:
                    return self.error(HTTPStatus.CONFLICT, "too many devices")
                # 同一设备切换账号后只通知当前登录者，不按可伪造的安装 ID 清理其他账号。
                conn.execute("DELETE FROM report_push_devices WHERE token=? AND NOT (user_id=? AND installation_id=?)", (data["token"].lower(),uid,data["installation_id"]))
                conn.execute("INSERT INTO report_push_devices(user_id,installation_id,token,session_hash,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(user_id,installation_id) DO UPDATE SET token=excluded.token,session_hash=excluded.session_hash,updated_at=excluded.updated_at", (uid,data["installation_id"],data["token"].lower(),token_hash(self.session_token()),now()))
                device = conn.execute("SELECT id FROM report_push_devices WHERE user_id=? AND installation_id=?", (uid,data["installation_id"])).fetchone()[0]
                if old and old["token"] != data["token"].lower():
                    conn.execute("DELETE FROM report_push_deliveries WHERE device_id=? AND state='invalid'", (device,))
                # 注册只绑定后续通知，不为安装前保存的日报补建投递。
            deliver_pending()
            return self.json({"ok": True})
        parts = path.split("/")
        if len(parts) in (4,5) and parts[3].isdigit():
            rid = int(parts[3])
            if rid > 9223372036854775807:
                return self.error(HTTPStatus.NOT_FOUND, "not found")
            with db() as conn:
                row = conn.execute("SELECT * FROM daily_reports WHERE id=? AND user_id=?", (rid,uid)).fetchone()
                if not row:
                    return self.error(HTTPStatus.NOT_FOUND, "not found")
                if self.command == "GET" and len(parts)==4:
                    return self.json({"report": report_row(row)})
                if self.command == "POST" and len(parts)==5 and parts[4]=="read":
                    conn.execute("UPDATE daily_reports SET read_at=? WHERE id=? AND user_id=? AND read_at=0", (now(),rid,uid))
                    return self.json({"ok": True})
            return self.error(HTTPStatus.METHOD_NOT_ALLOWED, "read only")
        return self.error(HTTPStatus.METHOD_NOT_ALLOWED, "read only")
