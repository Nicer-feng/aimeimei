"""本单词项原始出处的有界保存；按用户消息顺序复核，不使用模型摘要作证。"""
import re

from . import super_review


MAX_EVENTS = 80
MAX_CHARS = 12000
_CHANGE = re.compile(r"(?:取消|不再)(?:要求)?(?:禁用|避用|禁止|限制|必须)|(?:可以|允许)(?:直接)?(?:使用|出现|写|说|用)|(?:不用|无需|不必)(?:再)?(?:出现|保留|包含|带上|带|使用)")


def _last_unique(items):
    seen, result = set(), []
    for item in reversed(items):
        text = item["text"]
        if text and text not in seen:
            seen.add(text)
            result.append(item)
    return list(reversed(result))


def _fragments(text):
    fragments = [(item["start"], item["source_quote"]) for item in super_review._forbidden_catalogs(text)]
    for match in re.finditer(r"[^。｡！？!?；;\n\r]+", text):
        fragment = match.group()
        if len(fragment) > 1200:
            continue
        if (_CHANGE.search(fragment)
                or super_review._source_candidates("required", fragment)
                or super_review._source_candidates("forbidden", fragment)
                or super_review.length_requirement(fragment)["source_quote"]):
            fragments.append((match.start(), fragment))
    return sorted(set(fragments))


def build_evidence(state, user_id, conversation_id, history, text, document_context=""):
    """只保存实际用户原句，完整本轮原文始终在最后；返回证据及来源覆盖状态。"""
    history = list(history)
    saved = state.get("literal_sources")
    scoped = (isinstance(saved, dict) and saved.get("user_id") == user_id
              and saved.get("conversation_id") == conversation_id)
    events = []
    if scoped and isinstance(saved.get("events"), list):
        for item in saved["events"][:MAX_EVENTS]:
            if (isinstance(item, dict) and isinstance(item.get("message_id"), int)
                    and not isinstance(item["message_id"], bool) and item["message_id"] >= 0
                    and isinstance(item.get("position"), int) and item["position"] >= 0
                    and isinstance(item.get("text"), str) and 0 < len(item["text"]) <= 1200):
                events.append(dict(item))
    rows = [dict(row) for row in history if row["role"] == "user"]
    high_id = max([entry["message_id"] for entry in events] + [int(row.get("id") or 0) for row in rows] + [0])
    if not rows or rows[-1]["content"] != text:
        rows.append({"id": high_id + 1, "role": "user", "content": text})
    for row in rows:
        message_id = int(row.get("id") or high_id + 1)
        for position, fragment in _fragments(str(row["content"])):
            if 0 < len(fragment) <= 1200:
                events.append({"message_id": message_id, "position": position, "text": fragment})
    events = _last_unique(sorted(events, key=lambda item: (item["message_id"], item["position"])))
    budget, kept = 0, []
    for item in reversed(events):
        if len(kept) < MAX_EVENTS and budget + len(item["text"]) <= MAX_CHARS:
            kept.append(item)
            budget += len(item["text"])
    incomplete = bool((scoped and saved.get("incomplete")) or len(kept) < len(events))
    events = list(reversed(kept))
    state["literal_sources"] = {"user_id": user_id, "conversation_id": conversation_id,
                                "events": events, "incomplete": incomplete}

    # 若完整消息仍在窗口中，不再在它后面追加片段，否则可能颠倒同一句中的撤销顺序。
    recent_rows = [dict(row) for row in history if row["role"] == "user"]
    if not recent_rows or recent_rows[-1]["content"] != text:
        recent_rows.append(rows[-1])
    full_ids = {int(row.get("id") or high_id + 1) for row in recent_rows}
    ordered = [item for item in events if item["message_id"] not in full_ids]
    ordered.extend({"message_id": int(row.get("id") or high_id + 1), "position": -1, "text": str(row["content"])} for row in recent_rows)
    ordered.sort(key=lambda item: (item["message_id"], item["position"]))
    base = [state.get("source_brief", ""), *(state.get("material_excerpts") or []), document_context]
    parts = [{"text": value} for value in base if isinstance(value, str) and value] + ordered
    evidence = "\n\n".join(item["text"] for item in _last_unique(parts))
    return evidence, incomplete
