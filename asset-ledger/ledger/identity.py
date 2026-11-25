"""台账向本机 AI 槑槑服务查询当前会话的机房授权。"""

from contextlib import closing
from http.client import HTTPConnection, HTTPException
import json
import re

from .data import ApiError


AI_COOKIE = "ap_session"
IDENTITY_LIMIT = 4096
USERNAME = re.compile(r"[A-Za-z0-9_-]{2,32}")


class IdentityError(ApiError):
    pass


def unavailable():
    return IdentityError(503, "AI 槑槑登录服务暂时不可用，请稍后重试。")


def sroom_user(token):
    if token is None:
        raise IdentityError(401, "请使用 AI 槑槑账号登录。")
    try:
        with closing(HTTPConnection("127.0.0.1", 8000, timeout=2)) as connection:
            connection.request("GET", "/api/sroom/access", headers={"Cookie": f"{AI_COOKIE}={token}"})
            with connection.getresponse() as response:
                if response.status == 401:
                    raise IdentityError(401, "请使用 AI 槑槑账号登录。")
                if response.status == 403:
                    raise IdentityError(403, "当前 AI 槑槑账号未开通机房权限，请联系管理员。")
                if response.status != 200 or response.headers.get_content_type() != "application/json":
                    raise unavailable()
                body = response.read(IDENTITY_LIMIT + 1)
                if len(body) > IDENTITY_LIMIT:
                    raise unavailable()
                identity = json.loads(body)
    except (OSError, HTTPException, ValueError) as error:
        raise unavailable() from error

    if not isinstance(identity, dict) or not {"user_id", "username", "role", "unit_id"} <= identity.keys():
        raise unavailable()
    user_id, username = identity["user_id"], identity["username"]
    role, unit_id = identity["role"], identity["unit_id"]
    if not isinstance(user_id, str) or not 1 <= len(user_id) <= 128:
        raise unavailable()
    if not isinstance(username, str) or not USERNAME.fullmatch(username):
        raise unavailable()
    if not ((role == "admin" and unit_id is None) or (role == "reader" and type(unit_id) is int and 0 < unit_id < 2**63)):
        raise unavailable()
    return {"username": username, "role": role, "unit_id": unit_id}
