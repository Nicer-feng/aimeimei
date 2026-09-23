"""Server-side Alibaba IMM WebOffice token adapter for private OSS drafts.

Authenticated routes own file authorization, single-editor locks, draft
creation and business versioning. This module only calls IMM and returns
the minimum fields required by WebOffice JS SDK.
"""

import os
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit


_REGION_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)+$")
_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$")
_EDITABLE_EXTENSIONS = {"doc", "docx", "xls", "xlsx", "ppt", "pptx"}


class IMMWebOfficeError(RuntimeError):
    """Safe error with no upstream URL, token, OSS URI, or AccessKey."""

    def __init__(self, message, code="imm_error"):
        super().__init__(message)
        self.code = code


def _value(body, api_name, attribute):
    if isinstance(body, dict):
        return body.get(api_name) or body.get(attribute)
    return getattr(body, attribute, None)


def _utc_expiry(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(re.sub(r"(\.\d{6})\d+(?=(?:Z|[+-]\d{2}:\d{2})$)", r"\1", value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_url(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (parsed.scheme != "https" or not parsed.hostname
            or not parsed.hostname.endswith(".imm.aliyuncs.com")
            or parsed.username or parsed.password or port not in (None, 443)):
        return None
    return value


def _safe_error(exc):
    # SDK exception messages can contain source URIs, signed URLs and tokens.
    # Never interpolate an upstream exception in the user-visible error.
    code = getattr(exc, "code", "")
    if code in ("Forbidden", "Forbidden.NoPermission", "InvalidAccessKeyId.NotFound"):
        return IMMWebOfficeError("IMM 无权限，请检查项目和 RAM 授权", "permission_denied")
    if code in ("ResourceNotFound", "NoSuchKey", "NoSuchBucket"):
        return IMMWebOfficeError("IMM 项目或编辑草稿不存在，请检查地域和文件", "not_found")
    if isinstance(code, str) and code.startswith("Throttling"):
        return IMMWebOfficeError("IMM 请求过于频繁，请稍后重试", "rate_limited")
    return IMMWebOfficeError("IMM 在线编辑暂时不可用，请稍后重试", "imm_unavailable")


class IMMWebOffice:
    """Issue and refresh WebOffice tokens using existing server-side OSS keys."""

    def __init__(self, oss_config, project_name=None, region=None):
        config = dict(oss_config or {})
        self.project_name = (project_name or os.environ.get("IMM_PROJECT_NAME") or "").strip()
        self.region = (region or os.environ.get("IMM_REGION") or "").strip()
        self.bucket = (config.get("bucket") or "").strip()
        self.access_key_id = config.get("access_key_id") or ""
        self.access_key_secret = config.get("access_key_secret") or ""

        if not self.project_name or not self.region:
            raise IMMWebOfficeError("请先配置 IMM 项目名和地域", "not_configured")
        if not _REGION_RE.fullmatch(self.region) or not _BUCKET_RE.fullmatch(self.bucket):
            raise IMMWebOfficeError("IMM 地域或 OSS Bucket 配置无效", "invalid_config")
        if config.get("region") != self.region:
            raise IMMWebOfficeError("IMM 项目必须与 OSS Bucket 在同一地域", "region_mismatch")
        if not self.access_key_id or not self.access_key_secret:
            raise IMMWebOfficeError("OSS 访问凭据尚未配置", "not_configured")

    def _client(self):
        try:
            from alibabacloud_imm20200930.client import Client
            from alibabacloud_tea_openapi.models import Config
        except ImportError:
            raise IMMWebOfficeError("IMM SDK 尚未安装", "sdk_missing") from None
        try:
            config = Config(
                access_key_id=self.access_key_id,
                access_key_secret=self.access_key_secret,
            )
            config.endpoint = f"imm.{self.region}.aliyuncs.com"
            return Client(config)
        except Exception:
            raise IMMWebOfficeError("IMM 客户端初始化失败", "invalid_config") from None

    @staticmethod
    def _runtime():
        from alibabacloud_tea_util.models import RuntimeOptions
        return RuntimeOptions(connect_timeout=5000, read_timeout=15000)

    @staticmethod
    def _result(body, include_url):
        result = {
            "url": _safe_url(_value(body, "WebofficeURL", "weboffice_url")) if include_url else None,
            "access_token": _value(body, "AccessToken", "access_token"),
            "refresh_token": _value(body, "RefreshToken", "refresh_token"),
            "access_expires_at": _utc_expiry(_value(body, "AccessTokenExpiredTime", "access_token_expired_time")),
            "refresh_expires_at": _utc_expiry(_value(body, "RefreshTokenExpiredTime", "refresh_token_expired_time")),
        }
        if ((include_url and not result["url"])
                or not isinstance(result["access_token"], str) or not result["access_token"]
                or not isinstance(result["refresh_token"], str) or not result["refresh_token"]
                or not result["access_expires_at"] or not result["refresh_expires_at"]):
            raise IMMWebOfficeError("IMM 返回的编辑凭证不完整", "invalid_response")
        return result

    def generate(self, object_key, filename, user_id, user_name):
        """Return URL and tokens for an isolated OSS draft object."""
        if (not isinstance(object_key, str) or not object_key
                or object_key.startswith("/") or any(ch in object_key for ch in "\x00\r\n?#")):
            raise IMMWebOfficeError("编辑草稿路径无效", "invalid_argument")
        if not isinstance(filename, str) or "." not in filename or any(ch in filename for ch in "\x00\r\n"):
            raise IMMWebOfficeError("此文件格式暂不支持在线编辑", "unsupported_file")
        stem, extension = filename.rsplit(".", 1)
        extension = extension.lower()
        if not stem or extension not in _EDITABLE_EXTENSIONS:
            raise IMMWebOfficeError("此文件格式暂不支持在线编辑", "unsupported_file")
        if not user_id or not user_name:
            raise IMMWebOfficeError("编辑用户信息不完整", "invalid_argument")
        try:
            from alibabacloud_imm20200930 import models
            request = models.GenerateWebofficeTokenRequest(
                project_name=self.project_name,
                source_uri=f"oss://{self.bucket}/{object_key}",
                filename=f"{stem}.{extension}",
                permission=models.WebofficePermission(readonly=False),
                user=models.WebofficeUser(id=str(user_id), name=str(user_name)),
            )
            response = self._client().generate_weboffice_token_with_options(
                request, self._runtime()
            )
            return self._result(response.body, include_url=True)
        except IMMWebOfficeError:
            raise
        except Exception as exc:
            raise _safe_error(exc) from None

    def refresh(self, access_token, refresh_token):
        """Return renewed tokens; the browser keeps the URL from generate."""
        if (not isinstance(access_token, str) or not access_token
                or not isinstance(refresh_token, str) or not refresh_token):
            raise IMMWebOfficeError("编辑凭证不完整，请重新打开文档", "invalid_argument")
        try:
            from alibabacloud_imm20200930 import models
            request = models.RefreshWebofficeTokenRequest(
                project_name=self.project_name,
                access_token=access_token,
                refresh_token=refresh_token,
            )
            response = self._client().refresh_weboffice_token_with_options(
                request, self._runtime()
            )
            return self._result(response.body, include_url=False)
        except IMMWebOfficeError:
            raise
        except Exception as exc:
            raise _safe_error(exc) from None
