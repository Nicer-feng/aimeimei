import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
from urllib.parse import quote, urlencode, urlparse


def ocr_config(secrets_data):
    config = secrets_data.get("ocr") or {}
    cat = secrets_data.get("cat_oss") or {}

    def read(name, key, fallback=""):
        return str(os.environ.get(name) or config.get(key) or fallback).strip()

    endpoint = read("OCR_ENDPOINT", "endpoint", "https://ocr-api.cn-hangzhou.aliyuncs.com")
    if endpoint and not endpoint.startswith(("http://", "https://")):
        endpoint = "https://" + endpoint
    return {
        "access_key_id": read(
            "OCR_ACCESS_KEY_ID",
            "access_key_id",
            os.environ.get("CAT_OSS_ACCESS_KEY_ID") or cat.get("access_key_id") or "",
        ),
        "access_key_secret": read(
            "OCR_ACCESS_KEY_SECRET",
            "access_key_secret",
            os.environ.get("CAT_OSS_ACCESS_KEY_SECRET") or cat.get("access_key_secret") or "",
        ),
        "endpoint": endpoint.rstrip("/"),
        "version": read("OCR_VERSION", "version", "2021-07-07"),
    }


def ocr_configured(config):
    return bool(config.get("access_key_id") and config.get("access_key_secret") and config.get("endpoint"))


def _percent_encode(value):
    return quote(str(value), safe="~")


def _signed_rpc_url(config, action, params):
    values = {
        "Format": "JSON",
        "Version": config["version"],
        "AccessKeyId": config["access_key_id"],
        "SignatureMethod": "HMAC-SHA1",
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "SignatureVersion": "1.0",
        "SignatureNonce": hashlib.sha256(os.urandom(24)).hexdigest(),
        "Action": action,
        **{key: value for key, value in (params or {}).items() if value is not None},
    }
    canonical = "&".join(
        f"{_percent_encode(key)}={_percent_encode(values[key])}"
        for key in sorted(values)
    )
    string_to_sign = "POST&%2F&" + _percent_encode(canonical)
    signature = base64.b64encode(
        hmac.new(
            (config["access_key_secret"] + "&").encode(),
            string_to_sign.encode(),
            hashlib.sha1,
        ).digest()
    ).decode()
    values["Signature"] = signature
    parsed = urlparse(config["endpoint"])
    base = f"{parsed.scheme or 'https'}://{parsed.netloc or parsed.path}/"
    return base + "?" + urlencode(values, quote_via=quote, safe="~")


def recognize_handwriting(config, image_url):
    url = _signed_rpc_url(
        config,
        "RecognizeHandwriting",
        {
            "Url": image_url,
            "NeedRotate": "true",
            "NeedSortPage": "true",
            "Paragraph": "true",
            "OutputCharInfo": "false",
            "OutputTable": "false",
        },
    )
    request = urllib.request.Request(
        url,
        data=b"",
        headers={"User-Agent": "AI-Meimei-OCR/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        raw = response.read().decode("utf-8", errors="replace")
    data = json.loads(raw or "{}")
    if str(data.get("Code") or "").strip() not in ("", "200", "OK"):
        raise RuntimeError(str(data.get("Message") or "阿里云手写识别失败")[:500])
    return data


def handwriting_result(response):
    data = response.get("Data") if isinstance(response, dict) else {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {"content": data}
    if not isinstance(data, dict):
        data = {}
    paragraphs = data.get("prism_paragraphsInfo") or []
    paragraph_text = []
    if isinstance(paragraphs, list):
        for item in paragraphs:
            if isinstance(item, dict) and str(item.get("word") or "").strip():
                paragraph_text.append(str(item["word"]).strip())
    content = "\n\n".join(paragraph_text).strip() or str(data.get("content") or "").strip()
    if not content:
        words = data.get("prism_wordsInfo") or []
        content = "\n".join(
            str(item.get("word") or "").strip()
            for item in words
            if isinstance(item, dict) and str(item.get("word") or "").strip()
        ).strip()
    return {
        "content": content,
        "block_count": int(data.get("prism_wnum") or len(paragraph_text) or 0),
        "request_id": str(response.get("RequestId") or "")[:120] if isinstance(response, dict) else "",
    }
