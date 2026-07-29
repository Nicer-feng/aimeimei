import json
import re


def compact_search_text(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def search_snippet(text, query, limit=140):
    value = compact_search_text(text)
    if not value:
        return ""
    needle = compact_search_text(query).lower()
    lower = value.lower()
    index = lower.find(needle) if needle else -1
    if index < 0:
        return value[:limit].rstrip() + ("..." if len(value) > limit else "")
    start = max(0, index - 46)
    end = min(len(value), index + len(needle) + 86)
    snippet = value[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(value):
        snippet += "..."
    return snippet


def like_escape(text):
    return str(text or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_result_row(result_id, result_type, session_id, message_id, title, snippet, role, created_at, score):
    return {
        "id": str(result_id),
        "type": result_type,
        "session_id": session_id or "",
        "message_id": int(message_id or 0),
        "title": title or "未命名对话",
        "snippet": snippet or "",
        "role": role or "",
        "created_at": int(created_at or 0),
        "score": int(score or 0),
    }


def clip_context_text(text, limit):
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + f"\n\n（以上内容较长，已截取前 {limit} 字用于本次 AI 加工上下文。）"


def media_analysis_has_context(row):
    return any(
        str(row[key] or "").strip()
        for key in ("summary_text", "outline_text", "transcript_text", "enhanced_summary", "key_points", "mindmap_text", "copywriting_text")
    )


def media_analysis_context(row):
    filename = str(row["filename"] or "音视频文件").strip()
    sections = [
        "你正在协助用户基于一段音视频分析结果进行后续内容加工。",
        "请优先依据下面的分析上下文回答用户问题，不要要求用户重复上传音视频。",
        "如果用户要求二创，请直接基于上下文生成可用内容；如果信息不足，再简短说明需要补充什么。",
        f"文件名：{filename}",
    ]
    section_specs = [
        ("AI深度总结", row["enhanced_summary"], 16000),
        ("核心观点", row["key_points"], 12000),
        ("智能摘要", row["summary_text"], 12000),
        ("章节要点", row["outline_text"], 20000),
        ("转写全文", row["transcript_text"], 60000),
        ("思维导图", row["mindmap_text"], 12000),
        ("可复制文案", row["copywriting_text"], 12000),
    ]
    for title, value, limit in section_specs:
        clipped = clip_context_text(value, limit)
        if clipped:
            sections.append(f"\n## {title}\n{clipped}")
    return "\n".join(sections).strip()


def media_context_marker(task_id):
    return f"<!-- ai-meimei-media-task:{task_id} -->"


def media_ai_source_context(row):
    sections = [
        f"文件名：{row['filename'] or '音视频文件'}",
    ]
    for title, key, limit in (
        ("听悟智能摘要", "summary_text", 8000),
        ("听悟章节/关键词", "outline_text", 12000),
        ("听悟转写全文", "transcript_text", 36000),
    ):
        value = clip_context_text(row[key], limit)
        if value:
            sections.append(f"\n## {title}\n{value}")
    return "\n".join(sections).strip()


def extract_json_object(text):
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I)
        value = re.sub(r"\s*```$", "", value)
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(value[start:end + 1])
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def normalize_mermaid_mindmap(value):
    text = str(value or "").strip()
    text = re.sub(r"^```(?:mermaid)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text).strip()
    if not text:
        return ""
    if not text.lower().startswith("mindmap"):
        text = "mindmap\n  " + text.replace("\n", "\n  ")
    return text.strip()
