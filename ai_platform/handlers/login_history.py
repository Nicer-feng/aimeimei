import json
import sqlite3
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse, unquote

from ..database import db
from ..runtime import now, token_hash
from ..login_history import META_FIELDS, PLATFORMS, RETENTION_SECONDS, date_bounds, report_device, request_ip, session_state


def page_params(params):
    before = int(params.get("before", ["0"])[0])
    limit = int(params.get("limit", ["50"])[0])
    if not 0 <= before <= 9223372036854775807 or not 1 <= limit <= 100:
        raise ValueError()
    return before, limit


def public_metadata(raw):
    data = json.loads(raw)
    return {key: data.get(key, "") for key in META_FIELDS}


class LoginHistoryHandlersMixin:
    def handle_client_device_info(self):
        user = self.current_user()
        try:
            data = self.read_body(limit=4096)
            if not isinstance(data, dict): raise ValueError()
            with db() as conn:
                report_device(conn, user["id"], token_hash(self.session_token()), data,
                    self.headers.get("User-Agent", ""), request_ip(self)[0])
        except (ValueError, TypeError):
            return self.error(HTTPStatus.BAD_REQUEST, "设备资料格式不正确")
        except sqlite3.Error:
            return self.error(HTTPStatus.SERVICE_UNAVAILABLE, "设备资料暂未保存，请稍后再试")
        return self.json({"ok": True})

    def handle_admin_login_records(self):
        params = parse_qs(urlparse(self.path).query, keep_blank_values=True)
        try:
            before, limit = page_params(params)
            start, end = date_bounds(params)
            platform = params.get("platform", [""])[0]
            uid = params.get("user_id", [""])[0]
            if platform and platform not in PLATFORMS or len(uid) > 128: raise ValueError()
        except (ValueError, TypeError, OverflowError):
            return self.error(HTTPStatus.BAD_REQUEST, "登录记录筛选参数无效")
        clauses, args = ["e.logged_at>=?"], [max(now()-RETENTION_SECONDS,start or 0)]
        if end is not None: clauses.append("e.logged_at<?"); args.append(end)
        if before: clauses.append("e.id<?"); args.append(before)
        if uid: clauses.append("e.user_id=?"); args.append(uid)
        if platform: clauses.append("e.platform=?"); args.append(platform)
        with db() as conn:
            rows = conn.execute("""SELECT e.*,u.username,u.display_name,u.is_active AS account_active,
                h.logout_at,h.expires_at,EXISTS(SELECT 1 FROM sessions s WHERE s.token_hash=h.token_hash AND s.user_id=e.user_id AND s.expires_at>?) AS session_exists
                FROM auth_login_events e JOIN users u ON u.id=e.user_id
                LEFT JOIN auth_session_history h ON h.id=e.session_record_id AND h.user_id=e.user_id
                WHERE """ + " AND ".join(clauses) + " ORDER BY e.id DESC LIMIT ?", (now(),*args,limit+1)).fetchall()
        more = len(rows)>limit; rows=rows[:limit]
        records = [{"id":r["id"],"user_id":r["user_id"],"username":r["username"],"display_name":r["display_name"],
            "logged_at":r["logged_at"],"source_ip":r["source_ip"],"ip_source":r["ip_source"],
            "client":public_metadata(r["metadata_json"]),"session_state":session_state(r) if r["expires_at"] is not None else "unknown"} for r in rows]
        return self.json({"records":records,"next_before":rows[-1]["id"] if more else None,"timezone":"Asia/Shanghai","retention_days":90})

    def handle_admin_user_devices(self):
        uid = unquote(urlparse(self.path).path.rstrip("/").split("/")[-2])
        try:
            before, limit = page_params(parse_qs(urlparse(self.path).query, keep_blank_values=True))
        except (ValueError, TypeError):
            return self.error(HTTPStatus.BAD_REQUEST, "设备分页参数无效")
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not user: return self.error(HTTPStatus.NOT_FOUND, "user not found")
            rows = conn.execute("SELECT * FROM auth_devices WHERE user_id=? AND (?=0 OR id<?) AND last_active_at>=? ORDER BY id DESC LIMIT ?", (uid,before,before,now()-RETENTION_SECONDS,limit+1)).fetchall()
            more = len(rows)>limit; rows=rows[:limit]; devices=[]
            paused = bool(conn.execute("SELECT paused FROM daily_report_settings WHERE id=1").fetchone()[0])
            for row in rows:
                history = conn.execute("""SELECT CASE WHEN h.logout_at>0 THEN 'logged_out' WHEN h.expires_at<=? THEN 'expired'
                    WHEN ?=0 THEN 'account_disabled' WHEN EXISTS(SELECT 1 FROM sessions s WHERE s.token_hash=h.token_hash AND s.user_id=h.user_id AND s.expires_at>?) THEN 'valid' ELSE 'invalid' END AS state,COUNT(*) AS n
                    FROM auth_session_history h WHERE h.device_id=? AND h.user_id=? AND h.last_active_at>=? GROUP BY state""", (now(),user["is_active"],now(),row["id"],uid,now()-RETENTION_SECONDS)).fetchall()
                states = {h["state"]:h["n"] for h in history}
                latest_ip = conn.execute("SELECT last_active_ip FROM auth_session_history WHERE device_id=? AND user_id=? ORDER BY last_active_at DESC,id DESC LIMIT 1", (row["id"],uid)).fetchone()
                binding = conn.execute("""SELECT p.id,EXISTS(SELECT 1 FROM sessions s WHERE s.token_hash=p.session_hash AND s.user_id=p.user_id AND s.expires_at>?) AS valid
                    FROM report_push_devices p WHERE p.user_id=? AND p.installation_id=?""", (now(),uid,row["installation_id"])).fetchone()
                latest = conn.execute("SELECT state FROM report_push_deliveries WHERE device_id=? ORDER BY updated_at DESC,report_id DESC LIMIT 1", (binding["id"],)).fetchone() if binding else None
                meta = public_metadata(row["metadata_json"])
                devices.append({"id":row["id"],"client":meta,"installation_known":bool(row["installation_known"]),
                    "first_login_at":row["first_login_at"],"last_login_at":row["last_login_at"],"last_active_at":row["last_active_at"],
                    "first_reported_at":row["first_reported_at"],"reported_at":row["reported_at"],
                    "last_active_ip":latest_ip[0] if latest_ip else None,"sessions":states,
                    "notification":{"authorization":meta["notification_authorization"],"reported_at":row["reported_at"],
                        "capability":"apns" if meta["platform"]=="ios" else "not_integrated",
                        "registration":"invalid" if latest and latest[0]=="invalid" else "registered" if binding else "not_registered",
                        "binding_session_valid":bool(binding and binding["valid"] and user["is_active"]),
                        "policy_enabled":bool(user["is_active"] and user["daily_reports_enabled"] and user["daily_push_enabled"] and not paused),
                        "last_apns_state":latest[0] if latest else None}})
        return self.json({"devices":devices,"next_before":rows[-1]["id"] if more else None,"timezone":"Asia/Shanghai", "account":{"id":uid,"username":user["username"],"display_name":user["display_name"]}})
