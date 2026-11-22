import json
import os
import re
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie

from ..database import db, session_user
from ..runtime import now
from ..settings import SESSION_COOKIE


def scope_units():
    """读取部署方批准的机房辖区，避免 AI 服务直接打开台账数据库。"""
    configured = json.loads(os.environ.get("AI_PLATFORM_SROOM_SCOPES", "{}"))
    if not isinstance(configured, dict):
        raise ValueError("invalid sroom scopes")
    units = {}
    for key, label in configured.items():
        if not re.fullmatch(r"[1-9][0-9]{0,15}", key) or not isinstance(label, str) or not label.strip():
            raise ValueError("invalid sroom scope")
        unit_id = int(key)
        if unit_id > 2**53 - 1:
            raise ValueError("invalid sroom unit ID")
        units[unit_id] = label.strip()
    return units


def set_sroom_access(conn, actor_id, user_id, role, unit_id=None):
    """由调用方在事务内写入授权和审计；初始化时 actor_id 为空。"""
    previous = conn.execute(
        "SELECT role, unit_id FROM sroom_access WHERE user_id=?", (user_id,)
    ).fetchone()
    old_role, old_unit_id = tuple(previous) if previous else ("off", None)
    if (role, unit_id) == (old_role, old_unit_id):
        return
    if role == "off":
        conn.execute("DELETE FROM sroom_access WHERE user_id=?", (user_id,))
    else:
        conn.execute(
            """INSERT INTO sroom_access(user_id, role, unit_id) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET role=excluded.role, unit_id=excluded.unit_id""",
            (user_id, role, unit_id),
        )
    conn.execute(
        """INSERT INTO sroom_access_audit(actor_user_id, target_user_id, old_role, old_unit_id, role, unit_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (actor_id, user_id, old_role, old_unit_id, role, unit_id, now()),
    )


class SroomAccessHandlersMixin:
    def sroom_browser_token(self):
        # 这里仅接受浏览器会话，已有通用管理密钥或 Bearer 不能代替身份。
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", "")).get(SESSION_COOKIE)
        except CookieError:
            return None
        return cookie.value if cookie else None

    def sroom_same_origin(self):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1:
            return False
        host = hosts[0].lower()
        if host in ("feng.asia", "www.feng.asia"):
            allowed = [f"https://{host}"]
        elif re.fullmatch(r"(?:localhost|127\.0\.0\.1|\[::1\])(?::[0-9]{1,5})?", host):
            allowed = [f"http://{host}", f"https://{host}"]
        else:
            return False
        origins = self.headers.get_all("Origin", [])
        fetch_site = self.headers.get_all("Sec-Fetch-Site", [])
        return len(origins) == 1 and origins[0] in allowed and fetch_site in ([], ["same-origin"])

    def handle_sroom_access(self):
        token = self.sroom_browser_token()
        if not token:
            return self.error(HTTPStatus.UNAUTHORIZED, "请先登录 AI 槑槑。")
        with db() as conn:
            conn.execute("BEGIN")
            user = session_user(conn, token)
            if not user:
                return self.error(HTTPStatus.UNAUTHORIZED, "请先登录 AI 槑槑。")
            grant = conn.execute(
                "SELECT role, unit_id FROM sroom_access WHERE user_id=?", (user["id"],)
            ).fetchone()
        if grant and grant["role"] == "reader":
            try:
                if grant["unit_id"] not in scope_units():
                    grant = None
            except ValueError:
                return self.error(HTTPStatus.SERVICE_UNAVAILABLE, "机房辖区配置暂不可用。")
        if not grant:
            return self.error(HTTPStatus.FORBIDDEN, "该账号尚未开通机房权限。")
        return self.json({"user_id": user["id"], "username": user["username"], **dict(grant)})

    def handle_admin_sroom_access(self, target_id=None):
        token = self.sroom_browser_token()
        if not token:
            return self.error(HTTPStatus.UNAUTHORIZED, "请先登录 AI 槑槑。")
        with db() as conn:
            conn.execute("BEGIN")
            actor = session_user(conn, token)
            if not actor:
                return self.error(HTTPStatus.UNAUTHORIZED, "请先登录 AI 槑槑。")
            if actor["role"] != "admin":
                return self.error(HTTPStatus.FORBIDDEN, "仅 AI 槑槑管理员可管理机房权限。")
            try:
                units = scope_units()
            except ValueError:
                return self.error(HTTPStatus.SERVICE_UNAVAILABLE, "机房辖区配置暂不可用。")
            if target_id is None:
                grants = conn.execute("SELECT user_id, role, unit_id FROM sroom_access ORDER BY user_id").fetchall()
                return self.json({
                    "grants": [dict(grant) for grant in grants],
                    "units": [{"id": ident, "name": name} for ident, name in sorted(units.items())],
                })

        if not self.sroom_same_origin():
            return self.error(HTTPStatus.FORBIDDEN, "请在 AI 槑槑后台提交。")
        if self.headers.get_content_type() != "application/json":
            return self.error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "只接收 JSON。")
        try:
            data = self.read_body(limit=4096)
        except (UnicodeError, ValueError):
            return self.error(HTTPStatus.BAD_REQUEST, "权限数据格式不正确。")
        if not isinstance(data, dict):
            return self.error(HTTPStatus.BAD_REQUEST, "权限数据格式不正确。")
        role = data.get("role")
        unit_id = data.get("unit_id")
        if role not in ("admin", "reader", "off"):
            return self.error(HTTPStatus.BAD_REQUEST, "请选择有效的机房权限。")
        if role == "reader":
            if type(unit_id) is not int or unit_id not in units:
                return self.error(HTTPStatus.BAD_REQUEST, "请选择有效的机房辖区。")
        elif unit_id is not None:
            return self.error(HTTPStatus.BAD_REQUEST, "只有辖区只读权限可指定辖区。")

        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # 等待写锁期间会话或管理员身份可能已被撤销。
            actor = session_user(conn, token)
            if not actor:
                return self.error(HTTPStatus.UNAUTHORIZED, "请先登录 AI 槑槑。")
            if actor["role"] != "admin":
                return self.error(HTTPStatus.FORBIDDEN, "仅 AI 槑槑管理员可管理机房权限。")
            target = conn.execute("SELECT is_active FROM users WHERE id=?", (target_id,)).fetchone()
            if not target:
                return self.error(HTTPStatus.NOT_FOUND, "账号不存在。")
            if role != "off" and not target["is_active"]:
                return self.error(HTTPStatus.CONFLICT, "请先启用该 AI 槑槑账号。")
            set_sroom_access(conn, actor["id"], target_id, role, unit_id)
        return self.json({"user_id": target_id, "role": role, "unit_id": unit_id})
