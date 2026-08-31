import concurrent.futures
import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlparse

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

SNIPPET_MIN_LENGTH = 80
SNIPPET_MAX_LENGTH = 360
SOURCE_FETCH_LIMIT = 6
SOURCE_FETCH_TIMEOUT = 3
SOURCE_CACHE_TTL = 7 * 24 * 3600
STOPWORDS = {
    "的", "了", "和", "是", "在", "有", "与", "及", "或", "吗", "呢", "啊", "把", "给", "为", "对", "中", "上", "下", "最新", "官方",
    "the", "and", "for", "with", "from", "this", "that", "what", "when", "where", "how", "latest", "official",
}


def normalize_space(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def source_url_hash(url):
    return hashlib.sha256(str(url or "").strip().encode()).hexdigest()


def extract_keywords(*values):
    text = " ".join(str(value or "") for value in values).lower()
    words = set()
    for word in re.findall(r"[a-z0-9][a-z0-9._+-]{1,}|[\u4e00-\u9fff]{2,}", text):
        if word in STOPWORDS:
            continue
        if re.fullmatch(r"[\u4e00-\u9fff]{2,}", word) and len(word) > 4:
            for size in (2, 3, 4):
                for index in range(0, max(0, len(word) - size + 1)):
                    piece = word[index:index + size]
                    if piece not in STOPWORDS:
                        words.add(piece)
        else:
            words.add(word)
    return words


def clean_html_text(raw_html):
    value = str(raw_html or "")
    value = re.sub(r"(?is)<(script|style|noscript|svg|canvas|iframe|form|header|footer|nav|aside)[^>]*>.*?</\1>", " ", value)
    value = re.sub(r"(?is)<!--.*?-->", " ", value)
    value = re.sub(r"(?is)</(p|div|section|article|main|h[1-6]|li|tr|br)>", "\n", value)
    value = re.sub(r"(?is)<[^>]+>", " ", value)
    value = html.unescape(value)
    value = value.replace("\u00a0", " ")
    lines = []
    for line in re.split(r"[\r\n]+", value):
        line = normalize_space(line)
        if len(line) < 24:
            continue
        if line.count("|") > 8 or line.count("/") > 16:
            continue
        if re.search(r"(登录|注册|菜单|导航|广告|cookie|隐私政策|版权所有|ICP备案)", line) and len(line) < 80:
            continue
        lines.append(line)
    return "\n".join(lines[:240])


def fetch_page_text(url):
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; AI-Meimei/2.0; +https://feng.asia)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=SOURCE_FETCH_TIMEOUT) as response:
        content_type = response.headers.get("Content-Type", "")
        if not any(kind in content_type.lower() for kind in ("text/html", "text/plain", "application/xhtml")):
            return ""
        data = response.read(524288)
        charset_match = re.search(r"charset=([\w.-]+)", content_type, re.I)
        charset = charset_match.group(1) if charset_match else "utf-8"
        try:
            raw = data.decode(charset, errors="replace")
        except LookupError:
            raw = data.decode("utf-8", errors="replace")
    return clean_html_text(raw)


def paragraph_score(paragraph, keywords):
    lower = paragraph.lower()
    score = 0
    for keyword in keywords:
        if not keyword:
            continue
        hits = lower.count(keyword.lower())
        if hits:
            score += hits * (3 if len(keyword) >= 4 else 2)
    if re.search(r"\b20\d{2}\b", paragraph):
        score += 1
    return score


def relevant_snippet_from_text(text, query, title=""):
    paragraphs = [normalize_space(item) for item in re.split(r"(?:\n+|(?<=[。！？；.!?;])\s+)", text or "")]
    paragraphs = [item for item in paragraphs if len(item) >= 24]
    if not paragraphs:
        return ""
    keywords = extract_keywords(query, title)
    ranked = []
    for index, paragraph in enumerate(paragraphs[:180]):
        score = paragraph_score(paragraph, keywords)
        if score > 0:
            ranked.append((score, index, paragraph))
    if ranked:
        selected = sorted(sorted(ranked, reverse=True)[:2], key=lambda item: item[1])
        snippet = " ".join(item[2] for item in selected)
    else:
        snippet = paragraphs[0]
    snippet = normalize_space(snippet)
    if len(snippet) > SNIPPET_MAX_LENGTH:
        snippet = snippet[:SNIPPET_MAX_LENGTH].rstrip() + "..."
    return snippet


def cached_source_snippet(conn, url):
    if not conn or not url:
        return ""
    try:
        row = conn.execute(
            "SELECT snippet, fetched_at FROM source_snippet_cache WHERE url_hash=?",
            (source_url_hash(url),),
        ).fetchone()
    except Exception:
        return ""
    if not row:
        return ""
    try:
        if int(row["fetched_at"] or 0) < int(time.time()) - SOURCE_CACHE_TTL:
            return ""
    except Exception:
        return ""
    return str(row["snippet"] or "").strip()


def save_source_snippet_cache(conn, url, snippet, status="ok"):
    if not conn or not url:
        return
    try:
        conn.execute(
            """
            INSERT INTO source_snippet_cache(url_hash, url, snippet, fetch_status, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(url_hash) DO UPDATE SET
              url=excluded.url,
              snippet=excluded.snippet,
              fetch_status=excluded.fetch_status,
              fetched_at=excluded.fetched_at
            """,
            (source_url_hash(url), url, str(snippet or "")[:900], status, int(time.time())),
        )
    except Exception:
        pass


def fetch_relevant_source_snippet(item, query):
    try:
        page_text = fetch_page_text(item.get("url") or "")
        snippet = relevant_snippet_from_text(page_text, query, item.get("title") or "")
        return item.get("url") or "", snippet, "ok" if snippet else "empty"
    except Exception:
        return item.get("url") or "", "", "failed"


def enrich_search_result_snippets(results, query, conn=None):
    if not results:
        return results
    needs_fetch = []
    for item in results[:SOURCE_FETCH_LIMIT]:
        snippet = normalize_space(item.get("snippet") or "")
        if len(snippet) >= SNIPPET_MIN_LENGTH:
            item["snippet"] = snippet[:900]
            continue
        cached = cached_source_snippet(conn, item.get("url") or "")
        if cached:
            item["snippet"] = cached[:900]
            continue
        needs_fetch.append(item)
    if needs_fetch:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(3, len(needs_fetch))) as executor:
            future_map = {
                executor.submit(fetch_relevant_source_snippet, item, query): item
                for item in needs_fetch
            }
            done, pending = concurrent.futures.wait(
                future_map,
                timeout=SOURCE_FETCH_TIMEOUT * 2,
                return_when=concurrent.futures.ALL_COMPLETED,
            )
            for future in pending:
                future.cancel()
            for future in done:
                try:
                    url, snippet, status = future.result()
                except Exception:
                    continue
                item = future_map.get(future)
                if not item:
                    continue
                if snippet:
                    item["snippet"] = snippet[:900]
                save_source_snippet_cache(conn, url or item.get("url") or "", snippet, status)
    for item in results:
        item["snippet"] = normalize_space(item.get("snippet") or "")[:900]
    return results



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
