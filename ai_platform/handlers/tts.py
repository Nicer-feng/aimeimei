import hashlib
import json
import threading
import time
from http import HTTPStatus
from urllib.parse import parse_qs, quote, urlparse

from .shared import b64_token, db, now, oss_put_bytes, oss_signed_get_url, tts_oss_config
from ..runtime import write_private
from ..settings import SECRETS_PATH
from ..tts import (
    TTSProviderError,
    audio_chunks,
    normalize_tts_text,
    public_tts_config,
    resolve_voice,
    tts_config,
    tts_text_hash,
)


_locks_guard = threading.Lock()
_locks = {}


def _generation_lock(key):
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


class TTSHandlersMixin:
    def handle_tts_config(self):
        return self.json({"tts": public_tts_config(tts_config(self.server.secrets))})

    def handle_admin_tts(self):
        if self.command == "GET":
            return self.json({"tts": public_tts_config(tts_config(self.server.secrets), include_admin=True)})
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "配置格式不正确")
        old = tts_config(self.server.secrets)
        voices = []
        seen = set()
        for item in data.get("voices") if isinstance(data.get("voices"), list) else []:
            if not isinstance(item, dict):
                continue
            voice_id = str(item.get("id") or "").strip()
            resource_id = str(item.get("resource_id") or "").strip()
            if not voice_id or not resource_id or voice_id in seen:
                continue
            seen.add(voice_id)
            voices.append({
                "id": voice_id,
                "name": str(item.get("name") or voice_id).strip()[:80],
                "resource_id": resource_id,
            })
        if not voices:
            return self.error(HTTPStatus.BAD_REQUEST, "至少保留一个可用音色")
        default_voice = str(data.get("default_voice") or voices[0]["id"]).strip()
        if default_voice not in {item["id"] for item in voices}:
            default_voice = voices[0]["id"]
        api_key = old["api_key"]
        if data.get("clear_api_key"):
            api_key = ""
        elif str(data.get("api_key") or "").strip():
            api_key = str(data["api_key"]).strip()
        try:
            default_speed = max(0.5, min(2.0, float(data.get("default_speed") or 1)))
            default_volume = max(0.5, min(2.0, float(data.get("default_volume") or 1)))
            sample_rate = max(8000, min(48000, int(data.get("sample_rate") or 24000)))
            long_text_threshold = max(500, min(50000, int(data.get("long_text_threshold") or 5000)))
        except (TypeError, ValueError):
            return self.error(HTTPStatus.BAD_REQUEST, "语音参数不正确")
        self.server.secrets["tts"] = {
            "enabled": bool(data.get("enabled")),
            "provider": str(data.get("provider") or "volcengine").strip().lower(),
            "endpoint": str(data.get("endpoint") or old["endpoint"]).strip(),
            "api_key": api_key,
            "model": str(data.get("model") or "doubao-tts-v3").strip(),
            "voices": voices,
            "default_voice": default_voice,
            "default_speed": default_speed,
            "default_volume": default_volume,
            "sample_rate": sample_rate,
            "audio_format": "mp3",
            "cache_enabled": bool(data.get("cache_enabled", True)),
            "long_text_threshold": long_text_threshold,
        }
        write_private(SECRETS_PATH, json.dumps(self.server.secrets, ensure_ascii=False, indent=2) + "\n")
        return self.json({"ok": True, "tts": public_tts_config(tts_config(self.server.secrets), include_admin=True)})

    def _tts_message(self, message_id):
        user = self.current_user()
        with db() as conn:
            return conn.execute(
                """
                SELECT m.* FROM messages m
                JOIN conversations c ON c.id=m.conversation_id AND c.user_id=m.user_id
                WHERE m.id=? AND m.user_id=? AND m.role='assistant' AND c.archived=0
                """,
                (message_id, user["id"]),
            ).fetchone()

    def handle_message_tts_prepare(self):
        try:
            message_id = int(urlparse(self.path).path.split("/")[3])
        except (ValueError, IndexError):
            return self.error(HTTPStatus.NOT_FOUND, "消息不存在")
        message = self._tts_message(message_id)
        if not message:
            return self.error(HTTPStatus.NOT_FOUND, "这条回答不存在或不可朗读")
        config = tts_config(self.server.secrets)
        if not config["enabled"]:
            return self.error(HTTPStatus.BAD_REQUEST, "语音朗读暂未开启")
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "语音服务还没有配置好")
        try:
            data = self.read_body()
            voice = resolve_voice(config, data.get("voice"))
            speed = max(0.5, min(2.0, float(data.get("speed") or config["default_speed"])))
        except TTSProviderError as exc:
            return self.error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "语音参数不正确")
        text = normalize_tts_text(message["content"])
        if not text:
            return self.error(HTTPStatus.BAD_REQUEST, "这条回答没有可朗读的文字")
        digest = tts_text_hash(text)
        user_id = self.current_user()["id"]
        with db() as conn:
            cached = conn.execute(
                """
                SELECT id FROM message_tts
                WHERE user_id=? AND message_id=? AND text_hash=? AND voice=? AND speed=? AND status='completed' AND oss_key!=''
                LIMIT 1
                """,
                (user_id, message_id, digest, voice["id"], speed),
            ).fetchone()
        query = "voice={}&speed={}".format(quote(voice["id"], safe=""), quote(str(speed), safe=""))
        return self.json({
            "audio_url": f"/api/messages/{message_id}/tts/audio?{query}",
            "cached": bool(cached),
            "voice": voice,
            "long_text": len(text) > config["long_text_threshold"],
        })

    def handle_message_tts_audio(self):
        try:
            message_id = int(urlparse(self.path).path.split("/")[3])
        except (ValueError, IndexError):
            return self.error(HTTPStatus.NOT_FOUND, "消息不存在")
        message = self._tts_message(message_id)
        if not message:
            return self.error(HTTPStatus.NOT_FOUND, "这条回答不存在或不可朗读")
        config = tts_config(self.server.secrets)
        if not config["enabled"] or not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "语音服务暂不可用")
        params = parse_qs(urlparse(self.path).query)
        try:
            voice = resolve_voice(config, (params.get("voice") or [""])[0])
            speed = max(0.5, min(2.0, float((params.get("speed") or [config["default_speed"]])[0])))
        except (ValueError, TTSProviderError) as exc:
            return self.error(HTTPStatus.BAD_REQUEST, str(exc) or "语音参数不正确")
        text = normalize_tts_text(message["content"])
        digest = tts_text_hash(text)
        user_id = self.current_user()["id"]
        cache_key = f"{user_id}:{message_id}:{digest}:{voice['id']}:{speed}"
        with _generation_lock(cache_key):
            with db() as conn:
                cached = conn.execute(
                    """
                    SELECT * FROM message_tts
                    WHERE user_id=? AND message_id=? AND text_hash=? AND voice=? AND speed=? AND status='completed' AND oss_key!=''
                    LIMIT 1
                    """,
                    (user_id, message_id, digest, voice["id"], speed),
                ).fetchone()
            oss = tts_oss_config(self.server.secrets)
            if cached and oss["configured"]:
                url, _ = oss_signed_get_url(oss, cached["oss_key"], 21600)
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", url)
                self.send_header("Cache-Control", "private, no-store")
                self.end_headers()
                return
            record_id = cached["id"] if cached else b64_token(12)
            ts = now()
            with db() as conn:
                conn.execute(
                    """
                    INSERT INTO message_tts
                    (id,user_id,message_id,provider,model,voice,resource_id,speed,text_hash,oss_key,duration,file_size,status,error_message,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,'',0,0,'generating','',?,?)
                    ON CONFLICT(user_id,message_id,text_hash,voice,speed) DO UPDATE SET
                      status='generating', error_message='', updated_at=excluded.updated_at
                    """,
                    (record_id,user_id,message_id,config["provider"],config["model"],voice["id"],voice["resource_id"],speed,digest,ts,ts),
                )
            audio = bytearray()
            headers_sent = False
            client_open = True
            try:
                for chunk in audio_chunks(config, voice, text, speed, config["default_volume"]):
                    audio.extend(chunk)
                    if not headers_sent:
                        self.send_response(HTTPStatus.OK)
                        self.send_header("Content-Type", "audio/mpeg")
                        self.send_header("Cache-Control", "private, no-store")
                        self.send_header("X-Accel-Buffering", "no")
                        self.end_headers()
                        headers_sent = True
                    if client_open:
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            client_open = False
                if not audio:
                    raise TTSProviderError("语音服务没有返回音频")
                oss_key = ""
                if config["cache_enabled"] and oss["configured"]:
                    oss_key = "{}/{}/{}/{}.mp3".format(
                        oss["directory"].strip("/"), user_id,
                        time.strftime("%Y/%m/%d"),
                        hashlib.sha256(cache_key.encode()).hexdigest()[:32],
                    )
                    oss_put_bytes(oss, oss_key, bytes(audio), "audio/mpeg")
                with db() as conn:
                    conn.execute(
                        """
                        UPDATE message_tts SET oss_key=?,file_size=?,status='completed',error_message='',updated_at=?
                        WHERE user_id=? AND message_id=? AND text_hash=? AND voice=? AND speed=?
                        """,
                        (oss_key,len(audio),now(),user_id,message_id,digest,voice["id"],speed),
                    )
            except Exception as exc:
                friendly = str(exc) if isinstance(exc, TTSProviderError) else "语音生成失败，请稍后重试"
                with db() as conn:
                    conn.execute(
                        """UPDATE message_tts SET status='failed',error_message=?,updated_at=?
                           WHERE user_id=? AND message_id=? AND text_hash=? AND voice=? AND speed=?""",
                        (friendly[:500],now(),user_id,message_id,digest,voice["id"],speed),
                    )
                if not headers_sent:
                    return self.error(HTTPStatus.BAD_GATEWAY, friendly)
