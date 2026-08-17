import base64
import hashlib
import hmac
import json
import os
import time
from email.utils import formatdate
from urllib.parse import quote, urlencode
import urllib.request

from .runtime import now
from .settings import (
    CAT_MAX_IMAGE_BYTES,
    CAT_OSS_DIR,
    CHAT_IMAGE_ALLOWED_EXTENSIONS,
    CHAT_IMAGE_ALLOWED_MIME_TYPES,
    CHAT_IMAGE_MAX_BYTES,
    CHAT_IMAGE_MAX_COUNT,
    CHAT_IMAGE_OSS_DIR,
    MEDIA_ALLOWED_EXTENSIONS,
    MEDIA_MAX_UPLOAD_BYTES,
    MEDIA_OSS_DIR,
    TTS_OSS_DIR,
)


def cat_oss_config(secrets_data):
    config = secrets_data.get("cat_oss") or {}

    def read(name, key, default=""):
        return str(os.environ.get(name) or config.get(key) or default).strip()

    bucket = read("CAT_OSS_BUCKET", "bucket")
    region = read("CAT_OSS_REGION", "region")
    endpoint = read("CAT_OSS_ENDPOINT", "endpoint")
    access_key_id = read("CAT_OSS_ACCESS_KEY_ID", "access_key_id")
    access_key_secret = read("CAT_OSS_ACCESS_KEY_SECRET", "access_key_secret")
    public_base = read("CAT_OSS_PUBLIC_BASE", "public_base")
    directory = read("CAT_OSS_DIR", "dir", CAT_OSS_DIR).strip("/") or CAT_OSS_DIR

    if endpoint and not endpoint.startswith(("http://", "https://")):
        endpoint = "https://" + endpoint
    if not endpoint and bucket and region:
        endpoint = f"https://{bucket}.oss-{region}.aliyuncs.com"
    if public_base and not public_base.startswith(("http://", "https://")):
        public_base = "https://" + public_base
    if not public_base:
        public_base = endpoint

    return {
        "bucket": bucket,
        "region": region,
        "endpoint": endpoint.rstrip("/") if endpoint else "",
        "public_base": public_base.rstrip("/") if public_base else "",
        "access_key_id": access_key_id,
        "access_key_secret": access_key_secret,
        "directory": directory,
        "max_size": CAT_MAX_IMAGE_BYTES,
        "configured": bool(bucket and access_key_id and access_key_secret and endpoint),
    }


def cat_oss_prefix(config, user_id):
    date_path = time.strftime("%Y/%m/%d", time.localtime())
    return f"{config['directory'].strip('/')}/{user_id}/{date_path}/"


def cat_oss_url(config, oss_key):
    return config["public_base"].rstrip("/") + "/" + quote(oss_key, safe="/-_.~")


def chat_image_oss_config(secrets_data):
    base = cat_oss_config(secrets_data)
    config = secrets_data.get("chat_image_oss") or {}

    def read(name, key, default=""):
        return str(os.environ.get(name) or config.get(key) or default).strip()

    directory = read("CHAT_IMAGE_OSS_DIR", "dir", CHAT_IMAGE_OSS_DIR).strip("/") or CHAT_IMAGE_OSS_DIR
    return {
        **base,
        "directory": directory,
        "max_size": CHAT_IMAGE_MAX_BYTES,
        "configured": bool(base["bucket"] and base["access_key_id"] and base["access_key_secret"] and base["endpoint"]),
    }


def chat_image_prefix(config, user_id):
    date_path = time.strftime("%Y/%m/%d", time.localtime())
    return f"{config['directory'].strip('/')}/{user_id}/{date_path}/"


def chat_image_upload_policy(config, user_id):
    prefix = chat_image_prefix(config, user_id)
    expiration = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() + 600))
    policy = {
        "expiration": expiration,
        "conditions": [
            ["starts-with", "$key", prefix],
            ["starts-with", "$Content-Type", "image/"],
            ["content-length-range", 1, config["max_size"]],
        ],
    }
    encoded_policy = base64.b64encode(
        json.dumps(policy, separators=(",", ":")).encode()
    ).decode()
    signature = base64.b64encode(
        hmac.new(config["access_key_secret"].encode(), encoded_policy.encode(), hashlib.sha1).digest()
    ).decode()
    return {
        "host": config["endpoint"],
        "access_key_id": config["access_key_id"],
        "policy": encoded_policy,
        "signature": signature,
        "key_prefix": prefix,
        "max_size": config["max_size"],
        "max_count": CHAT_IMAGE_MAX_COUNT,
        "allowed_extensions": sorted(CHAT_IMAGE_ALLOWED_EXTENSIONS),
        "allowed_mime_types": sorted(CHAT_IMAGE_ALLOWED_MIME_TYPES),
        "expires_at": now() + 600,
    }


def chat_image_public(row):
    return {
        "id": row["id"],
        "filename": row["filename"],
        "mime_type": row["mime_type"],
        "file_size": row["file_size"],
        "view_url": f"/api/chat-images/{row['id']}/view",
        "created_at": row["created_at"],
    }


def cat_upload_policy(config, user_id):
    prefix = cat_oss_prefix(config, user_id)
    expiration = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() + 600))
    policy = {
        "expiration": expiration,
        "conditions": [
            ["starts-with", "$key", prefix],
            ["starts-with", "$Content-Type", "image/"],
            ["content-length-range", 1, config["max_size"]],
        ],
    }
    encoded_policy = base64.b64encode(
        json.dumps(policy, separators=(",", ":")).encode()
    ).decode()
    signature = base64.b64encode(
        hmac.new(
            config["access_key_secret"].encode(),
            encoded_policy.encode(),
            hashlib.sha1,
        ).digest()
    ).decode()
    return {
        "host": config["endpoint"],
        "access_key_id": config["access_key_id"],
        "policy": encoded_policy,
        "signature": signature,
        "key_prefix": prefix,
        "public_base": config["public_base"],
        "max_size": config["max_size"],
        "expires_at": now() + 600,
    }


def media_oss_config(secrets_data):
    cat_config = cat_oss_config(secrets_data)
    config = secrets_data.get("media_oss") or {}

    def read(name, key, fallback=""):
        return str(os.environ.get(name) or config.get(key) or fallback).strip()

    bucket = read("MEDIA_OSS_BUCKET", "bucket", cat_config["bucket"])
    region = read("MEDIA_OSS_REGION", "region", cat_config["region"])
    endpoint = read("MEDIA_OSS_ENDPOINT", "endpoint", cat_config["endpoint"])
    access_key_id = read("MEDIA_OSS_ACCESS_KEY_ID", "access_key_id", cat_config["access_key_id"])
    access_key_secret = read("MEDIA_OSS_ACCESS_KEY_SECRET", "access_key_secret", cat_config["access_key_secret"])
    public_base = read("MEDIA_OSS_PUBLIC_BASE", "public_base", cat_config["public_base"])
    directory = read("MEDIA_OSS_DIR", "dir", MEDIA_OSS_DIR).strip("/") or MEDIA_OSS_DIR
    try:
        max_size = int(read("MEDIA_MAX_UPLOAD_BYTES", "max_size", str(MEDIA_MAX_UPLOAD_BYTES)))
    except ValueError:
        max_size = MEDIA_MAX_UPLOAD_BYTES

    if endpoint and not endpoint.startswith(("http://", "https://")):
        endpoint = "https://" + endpoint
    if not endpoint and bucket and region:
        endpoint = f"https://{bucket}.oss-{region}.aliyuncs.com"
    if public_base and not public_base.startswith(("http://", "https://")):
        public_base = "https://" + public_base
    if not public_base:
        public_base = endpoint

    return {
        "bucket": bucket,
        "region": region,
        "endpoint": endpoint.rstrip("/") if endpoint else "",
        "public_base": public_base.rstrip("/") if public_base else "",
        "access_key_id": access_key_id,
        "access_key_secret": access_key_secret,
        "directory": directory,
        "max_size": max(1024 * 1024, max_size),
        "configured": bool(bucket and access_key_id and access_key_secret and endpoint),
    }


def media_oss_prefix(config, user_id):
    date_path = time.strftime("%Y/%m/%d", time.localtime())
    return f"{config['directory'].strip('/')}/{user_id}/{date_path}/"


def media_upload_policy(config, user_id):
    prefix = media_oss_prefix(config, user_id)
    expiration = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now() + 600))
    policy = {
        "expiration": expiration,
        "conditions": [
            ["starts-with", "$key", prefix],
            ["content-length-range", 1, config["max_size"]],
        ],
    }
    encoded_policy = base64.b64encode(
        json.dumps(policy, separators=(",", ":")).encode()
    ).decode()
    signature = base64.b64encode(
        hmac.new(
            config["access_key_secret"].encode(),
            encoded_policy.encode(),
            hashlib.sha1,
        ).digest()
    ).decode()
    return {
        "host": config["endpoint"],
        "access_key_id": config["access_key_id"],
        "policy": encoded_policy,
        "signature": signature,
        "key_prefix": prefix,
        "public_base": config["public_base"],
        "max_size": config["max_size"],
        "allowed_extensions": sorted(MEDIA_ALLOWED_EXTENSIONS),
        "expires_at": now() + 600,
    }


def oss_signed_get_url(config, oss_key, expires_seconds=21600):
    expires = now() + max(600, int(expires_seconds))
    canonical_resource = f"/{config['bucket']}/{oss_key}"
    string_to_sign = "GET\n\n\n{}\n{}".format(expires, canonical_resource)
    signature = base64.b64encode(
        hmac.new(config["access_key_secret"].encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    query = urlencode(
        {
            "OSSAccessKeyId": config["access_key_id"],
            "Expires": str(expires),
            "Signature": signature,
        }
    )
    base = config["public_base"].rstrip("/")
    return f"{base}/{quote(oss_key, safe='/-_.~')}?{query}", expires


def tts_oss_config(secrets_data):
    base = media_oss_config(secrets_data)
    config = secrets_data.get("tts_oss") or {}
    directory = str(
        os.environ.get("TTS_OSS_DIR") or config.get("dir") or TTS_OSS_DIR
    ).strip("/") or TTS_OSS_DIR
    return {**base, "directory": directory}


def oss_put_bytes(config, oss_key, data, content_type="application/octet-stream"):
    date_value = formatdate(timeval=None, localtime=False, usegmt=True)
    canonical_resource = f"/{config['bucket']}/{oss_key}"
    string_to_sign = f"PUT\n\n{content_type}\n{date_value}\n{canonical_resource}"
    signature = base64.b64encode(
        hmac.new(config["access_key_secret"].encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    url = config["endpoint"].rstrip("/") + "/" + quote(oss_key, safe="/-_.~")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": content_type,
            "Date": date_value,
            "Authorization": f"OSS {config['access_key_id']}:{signature}",
        },
        method="PUT",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        if response.status not in (200, 201):
            raise RuntimeError("OSS audio upload failed")
    return oss_key
