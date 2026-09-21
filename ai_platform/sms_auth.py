"""Alibaba Cloud PNVS SMS authentication helpers.

The provider creates and verifies one-time codes.  This module never receives
or persists a usable verification code.
"""

import json
import os
import re
import urllib.request

from .ocr import _signed_rpc_url

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def normalize_phone(value):
    raw = re.sub(r"[\s-]+", "", str(value or ""))
    if raw.startswith("+86"):
        raw = raw[3:]
    elif raw.startswith("0086"):
        raw = raw[4:]
    return raw if PHONE_RE.fullmatch(raw) else ""


def sms_auth_config(secrets_data):
    stored = secrets_data.get("sms_auth") or {}
    cat = secrets_data.get("cat_oss") or {}

    def read(env_name, key, fallback=""):
        return str(os.environ.get(env_name) or stored.get(key) or fallback).strip()

    access_key_id = read(
        "SMS_AUTH_ACCESS_KEY_ID", "access_key_id",
        os.environ.get("DYPNS_ACCESS_KEY_ID") or os.environ.get("CAT_OSS_ACCESS_KEY_ID") or cat.get("access_key_id") or "",
    )
    access_key_secret = read(
        "SMS_AUTH_ACCESS_KEY_SECRET", "access_key_secret",
        os.environ.get("DYPNS_ACCESS_KEY_SECRET") or os.environ.get("CAT_OSS_ACCESS_KEY_SECRET") or cat.get("access_key_secret") or "",
    )
    endpoint = read("SMS_AUTH_ENDPOINT", "endpoint", "https://dypnsapi.aliyuncs.com")
    if endpoint and not endpoint.startswith(("http://", "https://")):
        endpoint = "https://" + endpoint
    try:
        valid_seconds = max(60, min(1800, int(read("SMS_AUTH_VALID_SECONDS", "valid_seconds", "300"))))
    except ValueError:
        valid_seconds = 300
    try:
        resend_seconds = max(60, min(600, int(read("SMS_AUTH_RESEND_SECONDS", "resend_seconds", "60"))))
    except ValueError:
        resend_seconds = 60
    return {
        "enabled": bool(stored.get("enabled", False)),
        "access_key_id": access_key_id,
        "access_key_secret": access_key_secret,
        "endpoint": endpoint.rstrip("/"),
        "version": read("SMS_AUTH_VERSION", "version", "2017-05-25"),
        "sign_name": read("SMS_AUTH_SIGN_NAME", "sign_name"),
        "template_code": read("SMS_AUTH_TEMPLATE_CODE", "template_code"),
        "scheme_name": read("SMS_AUTH_SCHEME_NAME", "scheme_name"),
        "code_param_name": read("SMS_AUTH_CODE_PARAM", "code_param_name", "code"),
        "minutes_param_name": read("SMS_AUTH_MINUTES_PARAM", "minutes_param_name", "min"),
        "valid_seconds": valid_seconds,
        "resend_seconds": resend_seconds,
        "code_length": 6,
    }


def sms_auth_configured(config):
    return bool(
        config.get("enabled")
        and config.get("access_key_id")
        and config.get("access_key_secret")
        and config.get("endpoint")
        and config.get("sign_name")
        and config.get("template_code")
    )


def public_sms_auth_config(config, include_admin=False):
    result = {
        "enabled": bool(config.get("enabled")),
        "configured": sms_auth_configured(config),
        "country_code": "86",
        "code_length": int(config.get("code_length") or 6),
        "valid_seconds": int(config.get("valid_seconds") or 300),
        "resend_seconds": int(config.get("resend_seconds") or 60),
    }
    if include_admin:
        result.update({
            "sign_name": str(config.get("sign_name") or ""),
            "template_code": str(config.get("template_code") or ""),
            "scheme_name": str(config.get("scheme_name") or ""),
            "code_param_name": str(config.get("code_param_name") or "code"),
            "minutes_param_name": str(config.get("minutes_param_name") or ""),
            "has_access_key": bool(config.get("access_key_id") and config.get("access_key_secret")),
        })
    return result


def _request(config, action, params):
    url = _signed_rpc_url(config, action, params)
    request = urllib.request.Request(
        url, data=b"", headers={"User-Agent": "AI-Meimei-SMSAuth/1.0"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(1024 * 1024).decode("utf-8", errors="replace")
    data = json.loads(raw or "{}")
    if not bool(data.get("Success")) or str(data.get("Code") or "").upper() != "OK":
        raise RuntimeError(str(data.get("Message") or data.get("Code") or "短信服务请求失败")[:300])
    return data


def send_verify_code(config, phone, out_id):
    template_param = {str(config.get("code_param_name") or "code"): "##code##"}
    minutes_key = str(config.get("minutes_param_name") or "").strip()
    if minutes_key:
        template_param[minutes_key] = str(max(1, int(config["valid_seconds"]) // 60))
    params = {
        "PhoneNumber": phone,
        "CountryCode": "86",
        "SignName": config["sign_name"],
        "TemplateCode": config["template_code"],
        "TemplateParam": json.dumps(template_param, ensure_ascii=False, separators=(",", ":")),
        "OutId": out_id,
        "CodeLength": str(config["code_length"]),
        "CodeType": "1",
        "ValidTime": str(config["valid_seconds"]),
        "Interval": str(config["resend_seconds"]),
        "DuplicatePolicy": "1",
        "ReturnVerifyCode": "false",
        "AutoRetry": "1",
    }
    if config.get("scheme_name"):
        params["SchemeName"] = config["scheme_name"]
    return _request(config, "SendSmsVerifyCode", params)


def check_verify_code(config, phone, verify_code, out_id):
    params = {
        "PhoneNumber": phone,
        "CountryCode": "86",
        "VerifyCode": verify_code,
        "OutId": out_id,
        "CaseAuthPolicy": "1",
    }
    if config.get("scheme_name"):
        params["SchemeName"] = config["scheme_name"]
    data = _request(config, "CheckSmsVerifyCode", params)
    model = data.get("Model") if isinstance(data.get("Model"), dict) else {}
    return str(model.get("VerifyResult") or "").upper() == "PASS"
