"""Provider-specific options without changing conversation or message formats."""
import re

from .openai_egress import is_openai_url


def value(row, key, default=None):
    return row[key] if key in row.keys() else default


def openai_efforts(row):
    if not is_openai_url(value(row, "base_url", "")):
        return None
    name = str(value(row, "model", "")).strip().lower()
    if re.fullmatch(r"gpt-6\.1-sol(?:-\d{4}-\d{2}-\d{2})?", name):
        return {"fast": "low", "balanced": "medium", "deep": "high"}
    if re.fullmatch(r"gpt-6\.1-terra(?:-\d{4}-\d{2}-\d{2})?", name):
        return {"fast": "none", "balanced": "medium", "deep": "high"}
    # Unknown official models keep their defaults, never inherit Qwen options.
    return {}


def openai_reasoning_options(row, mode="balanced", responses=False, auxiliary=False):
    efforts = openai_efforts(row)
    if efforts is None:
        return None
    if not efforts or not (auxiliary or value(row, "supports_reasoning_control", False)):
        return {}
    effort = efforts.get("fast" if auxiliary else mode, efforts["balanced"])
    return {"reasoning": {"effort": effort}} if responses else {"reasoning_effort": effort}


def prepare_chat_payload(payload, row, mode="balanced", auxiliary=False):
    efforts = openai_efforts(row)
    if efforts is None:
        return payload
    result = dict(payload)
    for key in ("enable_thinking", "thinking_budget", "enable_search", "search_options", "reasoning_effort"):
        result.pop(key, None)
    result.update(openai_reasoning_options(row, mode, auxiliary=auxiliary))
    if "max_tokens" in result:
        result.setdefault("max_completion_tokens", result.pop("max_tokens"))
    if efforts and result.get("reasoning_effort", "medium") != "none":
        for key in ("temperature", "top_p", "logprobs", "top_logprobs"):
            result.pop(key, None)
    return result


def public_reasoning_options(row):
    efforts = openai_efforts(row)
    if efforts is None:
        return {}
    descriptions = {
        "none": "关闭思考，优先响应速度",
        "low": "低思考强度，不完全关闭思考",
        "medium": "中等思考强度，适合日常写作",
        "high": "高思考强度，耗时与用量更多",
    }
    labels = {"fast": "快速", "balanced": "平衡", "deep": "深度"}
    return {
        "supports_reasoning_control": bool(efforts and value(row, "supports_reasoning_control", False)),
        "supports_native_web_search": False,
        "reasoning_mode_options": {mode: {"effort": effort, "description": descriptions[effort],
            "title": labels[mode] + "：" + descriptions[effort] + "（" + effort + "）"} for mode, effort in efforts.items()},
    }
