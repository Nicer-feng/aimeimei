import hashlib
import hmac
import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import quote, urlencode


def tingwu_config(secrets_data):
    config = secrets_data.get("tingwu") or {}

    def read(name, key, default=""):
        return str(os.environ.get(name) or config.get(key) or default).strip()

    region = read("TINGWU_REGION", "region", "cn-beijing")
    endpoint = read("TINGWU_ENDPOINT", "endpoint", f"https://tingwu.{region}.aliyuncs.com")
    if endpoint and not endpoint.startswith(("http://", "https://")):
        endpoint = "https://" + endpoint
    return {
        "app_key": read("TINGWU_APP_KEY", "app_key"),
        "access_key_id": read("TINGWU_ACCESS_KEY_ID", "access_key_id"),
        "access_key_secret": read("TINGWU_ACCESS_KEY_SECRET", "access_key_secret"),
        "region": region,
        "endpoint": endpoint.rstrip("/") if endpoint else "",
        "version": read("TINGWU_VERSION", "version", "2023-09-30"),
    }


def tingwu_configured(config):
    return bool(config["app_key"] and config["access_key_id"] and config["access_key_secret"] and config["endpoint"])


def acs3_percent_encode(value):
    return quote(str(value), safe="-_.~")


def acs3_request(config, method, path, query, action, body=None):
    parsed = urlparse(config["endpoint"])
    host = parsed.netloc
    body_bytes = json.dumps(body or {}, ensure_ascii=False, separators=(",", ":")).encode()
    if method == "GET":
        body_bytes = b""
    body_hash = hashlib.sha256(body_bytes).hexdigest()
    acs_date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    nonce = b64_token(18)
    headers = {
        "host": host,
        "x-acs-action": action,
        "x-acs-version": config["version"],
        "x-acs-date": acs_date,
        "x-acs-signature-nonce": nonce,
        "x-acs-content-sha256": body_hash,
    }
    if method != "GET":
        headers["content-type"] = "application/json; charset=utf-8"
    signed_keys = sorted(key for key in headers if key == "host" or key.startswith("x-acs-"))
    canonical_headers = "".join(f"{key}:{' '.join(headers[key].strip().split())}\n" for key in signed_keys)
    signed_headers = ";".join(signed_keys)
    canonical_query = "&".join(
        f"{acs3_percent_encode(key)}={acs3_percent_encode(value)}"
        for key, value in sorted((query or {}).items())
    )
    canonical_request = "\n".join(
        [method, path, canonical_query, canonical_headers, signed_headers, body_hash]
    )
    string_to_sign = "ACS3-HMAC-SHA256\n" + hashlib.sha256(canonical_request.encode()).hexdigest()
    signature = hmac.new(
        config["access_key_secret"].encode(),
        string_to_sign.encode(),
        hashlib.sha256,
    ).hexdigest()
    headers["Authorization"] = (
        "ACS3-HMAC-SHA256 "
        f"Credential={config['access_key_id']},"
        f"SignedHeaders={signed_headers},"
        f"Signature={signature}"
    )
    url = config["endpoint"] + path
    if canonical_query:
        url += "?" + canonical_query
    request = urllib.request.Request(
        url,
        data=None if method == "GET" else body_bytes,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode()
    return json.loads(raw or "{}")


def tingwu_create_task(config, file_url, task_key, source_language="cn"):
    body = {
        "AppKey": config["app_key"],
        "Input": {
            "FileUrl": file_url,
            "SourceLanguage": source_language or "cn",
            "TaskKey": task_key,
        },
        "Parameters": {
            "Transcription": {
                "DiarizationEnabled": True,
                "Diarization": {"SpeakerCount": 0},
            },
            "AutoChaptersEnabled": True,
            "MeetingAssistanceEnabled": True,
            "MeetingAssistance": {"Types": ["Actions", "KeyInformation"]},
            "SummarizationEnabled": True,
            "Summarization": {
                "Types": ["Paragraph", "Conversational", "QuestionsAnswering", "MindMap"],
            },
            "TextPolishEnabled": True,
            "LlmOutputLanguage": "cn",
        },
    }
    return acs3_request(config, "PUT", "/openapi/tingwu/v2/tasks", {"type": "offline"}, "CreateTask", body)


def tingwu_get_task_info(config, task_id):
    path = "/openapi/tingwu/v2/tasks/" + acs3_percent_encode(task_id)
    return acs3_request(config, "GET", path, {}, "GetTaskInfo")


def extract_tingwu_task_id(response):
    data = response.get("Data") if isinstance(response, dict) else {}
    if not isinstance(data, dict):
        data = response if isinstance(response, dict) else {}
    for key in ("TaskId", "TaskID", "TaskId".lower(), "task_id"):
        if data.get(key):
            return str(data[key])
    return ""


def tingwu_data(response):
    data = response.get("Data") if isinstance(response, dict) else {}
    return data if isinstance(data, dict) else {}


def result_url(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("Url", "URL", "url", "ResultUrl", "ResultURL"):
            if value.get(key):
                return str(value[key])
    return ""


def fetch_result_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "ai-platform/2.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"text": raw}


def collect_text_values(value, keys=("Text", "text", "Sentence", "sentence", "Content", "content", "Summary", "summary")):
    parts = []
    if isinstance(value, dict):
        for key in keys:
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
        for item in value.values():
            parts.extend(collect_text_values(item, keys))
    elif isinstance(value, list):
        for item in value:
            parts.extend(collect_text_values(item, keys))
    return parts


def join_transcription_words(words):
    text = "".join(
        str(item.get("Text") or item.get("text") or "")
        for item in words
        if isinstance(item, dict)
    ).strip()
    return re.sub(r"\s+", " ", text)


def parse_transcription_payload(payload):
    data = payload.get("Transcription") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    paragraphs = data.get("Paragraphs") or data.get("paragraphs") or []
    lines = []
    if isinstance(paragraphs, list):
        for item in paragraphs:
            if not isinstance(item, dict):
                continue
            text = str(item.get("Text") or item.get("text") or "").strip()
            if not text and isinstance(item.get("Words"), list):
                text = join_transcription_words(item.get("Words") or [])
            if text:
                speaker = str(item.get("SpeakerName") or item.get("SpeakerId") or "").strip()
                lines.append((f"发言人{speaker}：" if speaker and not speaker.startswith("发言") else (speaker + "：" if speaker else "")) + text)
    if lines:
        return "\n\n".join(lines)
    return "\n".join(dict.fromkeys(collect_text_values(payload))).strip()


def parse_auto_chapters_payload(payload):
    chapters = payload.get("AutoChapters") if isinstance(payload, dict) else []
    if isinstance(chapters, dict):
        chapters = chapters.get("Chapters") or chapters.get("chapters") or []
    lines = []
    if isinstance(chapters, list):
        for index, item in enumerate(chapters, 1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("Headline") or item.get("Title") or item.get("title") or f"章节 {index}").strip()
            summary = str(item.get("Summary") or item.get("summary") or "").strip()
            if title or summary:
                lines.append(f"{index}. {title}" + (f"\n   {summary}" if summary else ""))
    if lines:
        return "\n".join(lines)
    return "\n".join(dict.fromkeys(collect_text_values(payload))).strip()


def parse_meeting_assistance_payload(payload):
    data = payload.get("MeetingAssistance") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    lines = []
    keywords = data.get("Keywords") or data.get("keywords") or []
    if isinstance(keywords, list):
        words = [str(item).strip() for item in keywords if str(item).strip()]
        if words:
            lines.append("关键词：" + "、".join(words[:40]))
    key_sentences = data.get("KeySentences") or data.get("keySentences") or []
    if isinstance(key_sentences, list) and key_sentences:
        lines.append("关键句：")
        for item in key_sentences[:12]:
            if isinstance(item, dict):
                text = str(item.get("Text") or item.get("text") or "").strip()
            else:
                text = str(item).strip()
            if text:
                lines.append("- " + text)
    actions = data.get("Actions") or data.get("actions") or []
    if isinstance(actions, list) and actions:
        lines.append("待办/行动：")
        for item in actions[:12]:
            text = str(item.get("Text") if isinstance(item, dict) else item).strip()
            if text:
                lines.append("- " + text)
    return "\n".join(lines).strip()


def parse_summarization_payload(payload):
    data = payload.get("Summarization") if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    lines = []
    title = str(data.get("ParagraphTitle") or data.get("Title") or "").strip()
    summary = str(data.get("ParagraphSummary") or data.get("Summary") or "").strip()
    if title:
        lines.append("## " + title)
    if summary:
        lines.append(summary)
    conversational = data.get("ConversationalSummary") or []
    if isinstance(conversational, list) and conversational:
        lines.append("## 发言总结")
        for item in conversational:
            if not isinstance(item, dict):
                continue
            speaker = str(item.get("SpeakerName") or item.get("SpeakerId") or "发言人").strip()
            text = str(item.get("Summary") or item.get("summary") or "").strip()
            if text:
                lines.append(f"- {speaker}：{text}")
    qa = data.get("QuestionsAnswering") or data.get("QuestionsAnsweringSummary") or []
    if isinstance(qa, list) and qa:
        lines.append("## 问答摘要")
        for item in qa[:12]:
            if isinstance(item, dict):
                question = str(item.get("Question") or item.get("question") or "").strip()
                answer = str(item.get("Answer") or item.get("answer") or item.get("Summary") or "").strip()
                if question or answer:
                    lines.append(f"- {question}" + (f"：{answer}" if answer else ""))
    if lines:
        return "\n\n".join(lines).strip()
    return "\n".join(dict.fromkeys(collect_text_values(payload))).strip()


def parse_tingwu_results(result_payloads):
    transcript_text = ""
    summary_parts = []
    outline_parts = []
    for name, payload in result_payloads.items():
        if name == "Transcription":
            transcript_text = parse_transcription_payload(payload)
        elif name == "AutoChapters":
            value = parse_auto_chapters_payload(payload)
            if value:
                outline_parts.append("## 章节速览\n" + value)
        elif name == "Summarization":
            value = parse_summarization_payload(payload)
            if value:
                summary_parts.append(value)
        elif name == "MeetingAssistance":
            value = parse_meeting_assistance_payload(payload)
            if value:
                outline_parts.append("## 关键词与关键句\n" + value)
        elif name == "TextPolish":
            values = collect_text_values(payload)
            if values:
                outline_parts.append("## 润色/整理\n" + "\n".join(dict.fromkeys(values[:20])))
    return {
        "transcript_text": transcript_text.strip(),
        "summary_text": "\n\n".join(part for part in summary_parts if part).strip(),
        "outline_text": "\n\n".join(part for part in outline_parts if part).strip(),
    }
