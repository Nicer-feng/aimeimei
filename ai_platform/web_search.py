import json
import os
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse

from .runtime import current_year, today_text


def usage_option_rejected(detail):
    text = str(detail or "").lower()
    return bool(
        "stream_options" in text
        or "include_usage" in text
        or "unknown field" in text
        or "extra inputs are not permitted" in text
        or "unsupported parameter" in text
    )


def clamp_int(value, default, min_value, max_value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, number))


def web_search_config(secrets_data):
    config = secrets_data.get("web_search") or {}
    provider = str(config.get("provider") or "tavily").strip().lower()
    if provider not in ("tavily", "brave"):
        provider = "tavily"
    mode = str(config.get("mode") or "auto").strip().lower()
    if mode not in ("manual", "auto", "always"):
        mode = "auto"
    depth = str(config.get("depth") or "advanced").strip().lower()
    if depth not in ("basic", "advanced"):
        depth = "advanced"
    api_key = str(config.get("api_key") or "").strip()
    return {
        "provider": provider,
        "api_key": api_key,
        "enabled": bool(config.get("enabled")),
        "result_count": clamp_int(config.get("result_count"), 5, 1, 8),
        "mode": mode,
        "depth": depth,
    }


def public_web_search_config(secrets_data):
    config = web_search_config(secrets_data)
    return {
        "provider": config["provider"],
        "enabled": config["enabled"],
        "configured": bool(config["api_key"]),
        "result_count": config["result_count"],
        "mode": config["mode"],
        "depth": config["depth"],
    }


def search_result(title, url, snippet):
    return {
        "title": str(title or "").strip()[:240],
        "url": str(url or "").strip(),
        "snippet": str(snippet or "").strip()[:900],
    }


FRESHNESS_PATTERNS = [
    "最新", "现在", "目前", "当前", "今天", "昨日", "昨天", "明天", "今年", "本月",
    "近期", "最近", "刚刚", "新版", "新版本", "发布", "更新", "涨价", "降价",
    "价格", "多少钱", "汇率", "股价", "天气", "新闻", "政策", "法规", "公告",
    "官网", "文档", "api", "模型", "版本", "排行", "榜单", "联网", "搜索",
    "today", "latest", "current", "now", "recent", "news", "price", "pricing",
    "weather", "stock", "release", "released", "update", "updated", "version",
    "api", "model", "docs", "documentation", "official", "policy", "law",
]


def should_auto_web_search(content):
    text = str(content or "").strip().lower()
    if not text:
        return False
    if re.search(r"\b20(2[5-9]|3[0-9])\b", text):
        return True
    return any(pattern.lower() in text for pattern in FRESHNESS_PATTERNS)


def should_use_web_search(content, requested, config):
    if not config["enabled"]:
        return False
    if config["mode"] == "always":
        return True
    if requested:
        return True
    if config["mode"] == "auto":
        return should_auto_web_search(content)
    return False


def build_search_query(content):
    text = re.sub(r"\s+", " ", str(content or "")).strip()
    if len(text) > 260:
        text = text[:260]
    year = current_year()
    if year not in text:
        text = f"{text} {year}"
    if not any(word in text.lower() for word in ("official", "官网", "文档", "最新", "latest")):
        text = f"{text} 最新 官方"
    return text


def perform_web_search(query, config):
    query = build_search_query(query)
    provider = config["provider"]
    if provider == "brave":
        return brave_search(query, config["api_key"], config["result_count"])
    return tavily_search(query, config["api_key"], config["result_count"], config["depth"])


def tavily_search(query, api_key, count, depth):
    payload = {
        "query": query,
        "search_depth": depth,
        "max_results": count,
        "include_answer": False,
        "include_raw_content": False,
    }
    request = urllib.request.Request(
        "https://api.tavily.com/search",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "User-Agent": "ai-platform/2.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode())
    results = []
    for item in data.get("results") or []:
        result = search_result(
            item.get("title"),
            item.get("url"),
            item.get("content") or item.get("snippet"),
        )
        if result["url"] and result["title"]:
            results.append(result)
    return results[:count]


def brave_search(query, api_key, count):
    url = "https://api.search.brave.com/res/v1/web/search?" + urlencode(
        {"q": query, "count": count}
    )
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
            "User-Agent": "ai-platform/2.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode())
    results = []
    for item in (data.get("web") or {}).get("results") or []:
        result = search_result(
            item.get("title"),
            item.get("url"),
            item.get("description") or item.get("snippet"),
        )
        if result["url"] and result["title"]:
            results.append(result)
    return results[:count]


def build_runtime_context(has_search_results=False):
    lines = [
        f"当前日期：{today_text()}。",
        "回答任何涉及现在、最新、价格、政策、版本、模型、API、新闻、天气、日期或可能变化的信息时，必须把当前日期作为判断基准。",
    ]
    if has_search_results:
        lines.append("本次对话已提供联网搜索资料。若搜索资料与模型训练记忆冲突，必须以搜索资料为准。")
    else:
        lines.append("如果没有联网搜索资料，不要把旧训练知识当作最新事实；遇到时效性问题应明确说明可能需要联网确认。")
    return "\n".join(lines)


def build_search_context(results):
    lines = [
        f"以下是平台在 {today_text()} 刚刚联网搜索到的资料。",
        "回答时必须优先依据这些资料；不要使用旧训练知识覆盖搜索结果。",
        "如果资料不足、来源太旧或无法相互印证，请直接说明不确定，不要编造。",
    ]
    for index, item in enumerate(results, 1):
        lines.append(
            f"[{index}] {item['title']}\nURL: {item['url']}\n摘要: {item['snippet'] or '无摘要'}"
        )
    lines.append("引用资料时使用 [1]、[2] 这样的编号。不要编造未出现在列表里的来源。")
    return "\n\n".join(lines)


def format_sources_markdown(results):
    if not results:
        return ""
    lines = ["\n\n---\n### 参考来源"]
    for index, item in enumerate(results, 1):
        title = item["title"].replace("[", "\\[").replace("]", "\\]")
        lines.append(f"{index}. [{title}]({item['url']})")
    return "\n".join(lines)


def public_sources(results):
    sources = []
    for index, item in enumerate(results or [], 1):
        sources.append(
            {
                "title": item.get("title") or f"来源 {index}",
                "url": item.get("url") or "",
                "snippet": item.get("snippet") or "",
                "position": index,
            }
        )
    return sources


def responses_input_from_messages(messages):
    converted = []
    for message in messages or []:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if not isinstance(content, list):
            converted.append({"role": role, "content": str(content or "")})
            continue
        parts = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "")
            if item_type in ("text", "input_text"):
                text = str(item.get("text") or "")
                if text:
                    parts.append({"type": "input_text", "text": text})
            elif item_type in ("image_url", "input_image"):
                image_url = item.get("image_url")
                if isinstance(image_url, dict):
                    image_url = image_url.get("url")
                image_url = str(image_url or "")
                if image_url:
                    parts.append({"type": "input_image", "image_url": image_url})
        converted.append({"role": role, "content": parts or str(content)})
    return converted


def native_search_results_from_item(item, limit=5):
    if not isinstance(item, dict) or item.get("type") != "web_search_call":
        return []
    action = item.get("action") or {}
    results = []
    seen = set()
    for source in action.get("sources") or []:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        parsed = urlparse(url)
        title = str(source.get("title") or parsed.netloc or "联网来源").strip()
        result = search_result(title, url, source.get("snippet") or "")
        if result["url"]:
            results.append(result)
        if len(results) >= limit:
            break
    return results


def split_think_blocks(content):
    text = str(content or "")
    reasoning_parts = []

    def collect(match):
        value = (match.group(1) or "").strip()
        if value:
            reasoning_parts.append(value)
        return ""

    cleaned = re.sub(
        r"<think>\s*(.*?)\s*</think>",
        collect,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    return cleaned, "\n\n".join(reasoning_parts).strip()
