"""题库片段检索：只返回原题，不推断或生成答案。"""

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path


NUMBER_PREFIX = re.compile(r"^\s*(?:第\s*)?\d+\s*(?:[.．](?!\d)|[、)）])\s*")
OPTION_PREFIX = re.compile(r"(?:^|\s)([A-Z])[.、．:：)）]\s*", re.IGNORECASE)
NEGATIONS = ("不", "未", "无", "非", "禁止", "错误")
NUMBER_TERMS = re.compile(r"\d+(?:\.\d+)?|[一二三四五六七八九十百千万]+(?=(?:类|轴|级|小时|天|年|月|日|次|个|米|吨))")


def normalize(value):
    """去除排版差异，保留文字、数字及数字中的小数点。"""
    text = unicodedata.normalize("NFKC", value).casefold()
    return "".join(char for i, char in enumerate(text) if char.isalnum() or char in "%+-−<>=≤≥" or (char in ".:" and i > 0 and i + 1 < len(text) and text[i - 1].isdigit() and text[i + 1].isdigit()))


def bigrams(text):
    return {text[i:i + 2] for i in range(len(text) - 1)}


def semantic_signature(text):
    return set(NUMBER_TERMS.findall(text)), {word for word in NEGATIONS if word in text}


def query_parts(value):
    text = NUMBER_PREFIX.sub("", unicodedata.normalize("NFKC", value).strip())
    text = re.sub(r"^\s*[【\[(]?(?:单选题?|多选题?)[】\])：:\s]*", "", text)
    text = NUMBER_PREFIX.sub("", text)
    markers = list(OPTION_PREFIX.finditer(text))
    stem = text[:markers[0].start()] if markers else text
    options = [normalize(text[marker.end():markers[i + 1].start() if i + 1 < len(markers) else len(text)]) for i, marker in enumerate(markers)]
    tokens = [normalize(part) for part in re.split(r"\s+", stem) if len(normalize(part)) >= 2]
    return normalize(stem), options, tokens, stem


class QuestionBank:
    def __init__(self, path=None):
        payload = json.loads(Path(path or Path(__file__).with_name("questions.json")).read_text(encoding="utf-8"))
        self.metadata = {key: value for key, value in payload.items() if key != "questions"}
        self.items = payload["questions"]
        self._index = []
        for item in self.items:
            stem = normalize(item["question"])
            options = [normalize(option["text"]) for option in item["options"]]
            self._index.append((item, stem, options, stem + "\n" + "\n".join(options), bigrams(stem)))

    def search(self, query, page=1, page_size=20):
        if not isinstance(query, str) or len(query) > 1000:
            raise ValueError("题目内容不能超过 1000 字")
        if isinstance(page, bool) or not isinstance(page, int) or page < 1 or page > 10000:
            raise ValueError("页码无效")
        if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 50:
            raise ValueError("每页数量无效")
        query = query.strip()
        needle, query_options, tokens, _ = query_parts(query)
        matches = []
        similar_matches = []
        if len(needle) >= 2:
            needle_pairs = bigrams(needle)
            query_semantics = semantic_signature(needle)
            for index, (item, stem, options, document, pairs) in enumerate(self._index):
                score = 0
                similar = False
                if needle == stem:
                    score = 100
                elif needle in stem:
                    score = 80 + len(needle) / max(1, len(stem)) * 10
                elif len(stem) >= 8 and stem in needle:
                    score = 70 + len(stem) / len(needle) * 10
                elif len(tokens) >= 2 and all(token in document for token in tokens):
                    score = 60 + sum(token in stem for token in tokens) / len(tokens) * 8
                elif any(needle in option for option in options):
                    score = 50
                elif len(needle) >= 10 and needle_pairs and len(needle_pairs & pairs) / len(needle_pairs) >= 0.72:
                    # 相似匹配不能忽略数字或否定词，否则可能返回含义相反的题。
                    match = SequenceMatcher(None, needle, stem, autojunk=False).find_longest_match()
                    start = max(0, match.b - match.a)
                    candidates = [stem[max(0, start + offset):max(0, start + offset) + len(needle) + extra] for offset in (-1, 0, 1) for extra in (-1, 0, 1)]
                    similarity = max((SequenceMatcher(None, needle, candidate, autojunk=False).ratio() for candidate in candidates if candidate and semantic_signature(candidate) == query_semantics), default=0)
                    if similarity >= 0.9:
                        score = 30 + similarity * 10
                        similar = True
                if not score:
                    continue
                # 考试可能重排选项，比较内容而不比较选项字母。
                if query_options:
                    option_hits = sum(any(part == option or (len(part) >= 3 and part in option) for option in options) for part in query_options)
                    score += option_hits / len(query_options) * 15
                (similar_matches if similar else matches).append((-score, index, item))
        # 已有片段或关键词命中时不混入近似题，防止仅一字之差的题造成误读。
        if not matches:
            matches = similar_matches
        matches.sort(key=lambda match: (match[0], match[1]))
        total = len(matches)
        start = (page - 1) * page_size
        return {"query": query, "total": total, "page": page, "page_size": page_size, "has_more": start + page_size < total, "items": [item for _, _, item in matches[start:start + page_size]]}
