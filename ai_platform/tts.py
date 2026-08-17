import base64
import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import uuid


DEFAULT_ENDPOINT = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
DEFAULT_VOICE = {
    "id": "zh_female_vv_uranus_bigtts",
    "name": "Vivi 2.0",
    "resource_id": "seed-tts-2.0",
}


class TTSProviderError(RuntimeError):
    pass


def _number(value, fallback, minimum, maximum):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(fallback)
    return max(minimum, min(maximum, number))


def _voices(raw):
    result = []
    seen = set()
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        voice_id = str(item.get("id") or "").strip()
        if not voice_id or voice_id in seen:
            continue
        seen.add(voice_id)
        result.append(
            {
                "id": voice_id,
                "name": str(item.get("name") or voice_id).strip()[:80],
                "resource_id": str(item.get("resource_id") or "seed-tts-2.0").strip(),
            }
        )
    return result or [DEFAULT_VOICE.copy()]


def tts_config(secrets_data):
    saved = secrets_data.get("tts") or {}

    def read(name, key, fallback=""):
        return str(os.environ.get(name) or saved.get(key) or fallback).strip()

    voices = _voices(saved.get("voices"))
    default_voice = read("VOLC_TTS_DEFAULT_VOICE", "default_voice", voices[0]["id"])
    if default_voice not in {item["id"] for item in voices}:
        default_voice = voices[0]["id"]
    api_key = read("VOLC_TTS_API_KEY", "api_key")
    enabled_value = os.environ.get("AI_TTS_ENABLED")
    enabled = bool(saved.get("enabled", True)) if enabled_value is None else enabled_value.lower() in {"1", "true", "yes", "on"}
    return {
        "enabled": enabled,
        "provider": read("AI_TTS_PROVIDER", "provider", "volcengine").lower(),
        "endpoint": read("VOLC_TTS_ENDPOINT", "endpoint", DEFAULT_ENDPOINT),
        "api_key": api_key,
        "model": read("VOLC_TTS_MODEL", "model", "doubao-tts-v3"),
        "voices": voices,
        "default_voice": default_voice,
        "default_speed": _number(saved.get("default_speed"), 1.0, 0.5, 2.0),
        "default_volume": _number(saved.get("default_volume"), 1.0, 0.5, 2.0),
        "sample_rate": int(_number(saved.get("sample_rate"), 24000, 8000, 48000)),
        "audio_format": str(saved.get("audio_format") or "mp3").strip().lower(),
        "cache_enabled": bool(saved.get("cache_enabled", True)),
        "long_text_threshold": int(_number(saved.get("long_text_threshold"), 5000, 500, 50000)),
        "configured": bool(api_key and voices),
    }


def public_tts_config(config, include_admin=False):
    result = {
        "enabled": bool(config["enabled"]),
        "configured": bool(config["configured"]),
        "provider": config["provider"],
        "model": config["model"],
        "voices": config["voices"],
        "default_voice": config["default_voice"],
        "default_speed": config["default_speed"],
        "default_volume": config["default_volume"],
        "sample_rate": config["sample_rate"],
        "audio_format": config["audio_format"],
        "cache_enabled": bool(config["cache_enabled"]),
        "long_text_threshold": config["long_text_threshold"],
    }
    if include_admin:
        result.update({"endpoint": config["endpoint"], "has_api_key": bool(config["api_key"])})
    return result


def resolve_voice(config, voice_id):
    selected = str(voice_id or config["default_voice"]).strip()
    for item in config["voices"]:
        if item["id"] == selected:
            return item
    raise TTSProviderError("选择的音色暂不可用")


def normalize_tts_text(value):
    text = str(value or "")
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.I)
    text = re.sub(r"```[^\n]*\n([\s\S]*?)```", r"\1", text)
    text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"^\s{0,3}(?:#{1,6}|>|[-*+] |\d+[.)] )\s*", "", text, flags=re.M)
    text = re.sub(r"[*_~`|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def tts_text_hash(text):
    return hashlib.sha256(normalize_tts_text(text).encode("utf-8")).hexdigest()


def _speech_rate(speed):
    return int(round((_number(speed, 1.0, 0.5, 2.0) - 1.0) * 100))


def _loudness_rate(volume):
    return int(round((_number(volume, 1.0, 0.5, 2.0) - 1.0) * 100))


def volcengine_audio_chunks(config, voice, text, speed=None, volume=None):
    payload = {
        "user": {"uid": "aimeimei-tts"},
        "req_params": {
            "text": normalize_tts_text(text),
            "speaker": voice["id"],
            "audio_params": {
                "format": config["audio_format"],
                "sample_rate": config["sample_rate"],
                "speech_rate": _speech_rate(speed if speed is not None else config["default_speed"]),
                "loudness_rate": _loudness_rate(volume if volume is not None else config["default_volume"]),
            },
        },
    }
    request = urllib.request.Request(
        config["endpoint"],
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Api-Key": config["api_key"],
            "X-Api-Resource-Id": voice["resource_id"],
            "X-Api-Request-Id": str(uuid.uuid4()),
            "X-Control-Require-Usage-Tokens-Return": "text_words",
        },
        method="POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=90)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:1000]
        raise TTSProviderError(_provider_error(detail, exc.code)) from exc
    except urllib.error.URLError as exc:
        raise TTSProviderError("语音服务网络连接失败") from exc
    with response:
        for raw_line in response:
            if not raw_line.strip():
                continue
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise TTSProviderError("语音服务返回了无法识别的数据") from exc
            code = int(event.get("code") or 0)
            if code == 20000000:
                break
            if code not in (0,):
                raise TTSProviderError(_provider_error(str(event.get("message") or ""), code))
            if event.get("data"):
                try:
                    chunk = base64.b64decode(event["data"])
                except Exception as exc:
                    raise TTSProviderError("语音数据解析失败") from exc
                if chunk:
                    yield chunk


def _provider_error(message, code=None):
    detail = str(message or "").lower()
    if "resource id is mismatched" in detail:
        return "音色与语音模型资源不匹配"
    if code in (401, 403) or "unauthorized" in detail or "forbidden" in detail:
        return "语音服务认证失败或当前资源未开通"
    if "speaker" in detail:
        return "配置的音色暂不可用"
    if "quota" in detail or "balance" in detail:
        return "语音服务额度不足"
    if "length" in detail or "too long" in detail:
        return "朗读内容过长"
    return "语音生成失败，请稍后重试"


def audio_chunks(config, voice, text, speed=None, volume=None):
    if config["provider"] != "volcengine":
        raise TTSProviderError("暂不支持当前语音服务")
    yield from volcengine_audio_chunks(config, voice, text, speed, volume)
