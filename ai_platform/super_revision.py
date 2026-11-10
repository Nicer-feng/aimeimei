"""超能修稿只允许替换已定位的正文范围，或向分镜表插入景别列。"""

import json
import re
from dataclasses import dataclass


VERSION = "super-revision-v1"
MAX_DRAFT = 60000
NUMBERS = "一二三四五六七八九十"
EDIT = re.compile(
    r"^(?:请|麻烦)?(?:帮我|给我)?(?:只(?:需要|用)?|仅)?(?:修改|改写|改|调整|优化|润色)"
    r"(?:一下|下)?[：:\s]*(开头|结尾|收尾|第([1-9]|10|[一二三四五六七八九十])段)"
)
COLUMN = re.compile(
    r"^(?:请|麻烦)?(?:帮我|给我)?(?:只(?:需要|用)?|仅)?(?:在时长(?:前面|之前|前))?"
    r"(?:添加|增加|加上|加)(?:一)?列[：:\s]*[「“]?景别[」”]?[。！!\s]*$"
)
PASTED = re.compile(r"(?:^|\s)(?:就)?在(?:这个|这版|这段|以上)(?:的)?基础上(?:来)?(?:修改|改)[，,：:\s]*")
UNSAFE = re.compile(r"(?:同时|顺便|并且|还有|再把|以及|和)(?:也|再)?(?:修改|改|加|删|重写|调整)|"
                    r"(?:^|[\s，,。；;])(?:再|也|另外)?(?:修改|改(?:写|一下|下)?|加(?:上|一列)?|删(?:掉|去)?|重写|调整)"
                    r"[：:\s]*(?:开头|结尾|收尾|第[一二三四五六七八九十\d]+段|标题|景别)|"
                    r"全文|全篇|联网|查资料")
LOCAL_UNCLEAR = re.compile(r"^(?:请|麻烦)?(?:帮我|给我)?(?:(?:只|仅)(?:需要|用)?(?:修改|改|调整)|(?:修改|改|调整)(?:一下|下)?(?:这|那)(?:句|段)|(?:添加|增加|加)(?:一)?列)")
BODY = re.compile(r"(?m)^[ \t]*(?:#{1,6}[ \t]+)?(?:\*\*|【)?(?:正文|口播正文|口播内容|口播稿|口播|台词)"
                  r"(?:[：:](?:\*\*|】)?|(?:\*\*|】)[：:]?|(?=[ \t]*$))[ \t]*")
BOUNDARY = re.compile(r"(?m)^[ \t]*(?:#{1,6}[ \t]+|\|[^\n]+\||(?:脚本|方案)[一二三四五六七八九十\d]+|"
                      r"(?:\*\*|【)?(?:封面文案|发布文案|标题|话题|拍摄说明)[：:]|[-*_]{3,}[ \t]*$|(?:#[\w-]+[ \t]*)+$)")
SHOT_TYPES = {"远景", "全景", "中全景", "中景", "中近景", "近景", "特写", "大特写"}
BAN = re.compile(
    r"(?:不要出现|禁止使用|(?<!取消)禁用|不要用)\s*[「“]([^」”\r\n]{1,16})[」”]"
    r"|(?:^|[\s，,。；;])[「“]?([\u4e00-\u9fffA-Za-z0-9]{1,8})[」”]?\s*(?:是|属于)\s*(?:本单的?)?(?:红线词汇?|禁用词)"
)
UNBAN = re.compile(r"(?:取消禁用|允许使用|可以用)\s*[「“]([^」”\r\n]{1,16})[」”]")
BODY_GOAL = re.compile(r"正文(?:内容)?(?:字数)?[：:\s]*(?:要|控制在|写到)?[：:\s]*(?:大约|约)?\s*(\d{2,4})\s*字(?:左右)?")


class ScopeError(ValueError):
    pass


@dataclass(frozen=True)
class Request:
    target: str
    instruction: str
    pasted: str = ""
    paragraph: int = 0


@dataclass(frozen=True)
class Plan:
    request: Request
    draft: str
    spans: tuple
    context: object
    bans: tuple = ()
    body_span: tuple = ()
    goal: int = 0


def parse_request(text):
    text = text.strip()
    pasted = ""
    if len(text) > 100 or "\n" in text:
        matches = list(PASTED.finditer(text[-300:]))
        if not matches:
            return None
        marker = matches[-1]
        offset = max(0, len(text) - 300)
        pasted, text = text[:offset + marker.start()].rstrip(), text[offset + marker.end():].strip()
        if not pasted:
            return None
    if len(text) > 100 or "\n" in text:
        return None
    if COLUMN.fullmatch(text):
        return Request("景别", text, pasted)
    m = EDIT.match(text)
    if not m:
        if LOCAL_UNCLEAR.match(text):
            raise ScopeError("没能确定要修改的位置。请写明只改开头、结尾、第几段，或给分镜表加景别列。")
        return None
    tail = text[m.end():]
    if (tail and not re.match(r"^[\s，,。；;：:！!？?、]|^改成|^换成|^写成|^更|^推荐", tail)
            or UNSAFE.search(tail) or EDIT.search(tail.lstrip("，,；; "))):
        raise ScopeError("这条指令可能涉及多个位置，请一次只指定一处修改。")
    p = m[2]
    return Request(m[1], text, pasted, (int(p) if p.isdigit() else NUMBERS.index(p) + 1) if p else 0)


def paragraph_spans(draft):
    markers = list(BODY.finditer(draft))
    if len(markers) > 1:
        raise ScopeError("底稿包含多篇正文，请粘贴要改的那一篇。")
    start = markers[0].end() if markers else 0
    end = len(draft)
    boundary = BOUNDARY.search(draft, start)
    if boundary:
        if not markers or re.search(r"(?m)^[ \t]*(?:#{1,6}[ \t]*)?脚本[一二三四五六七八九十\d]+", draft):
            raise ScopeError("底稿正文范围不明确，请只粘贴要改的正文。")
        end = boundary.start()
    # 保留段落外原始空白、标题及话题；不重新序列化原稿。
    return [(start + m.start(), start + m.end())
            for m in re.finditer(r"(?m)\S[^\r\n]*?(?=[ \t]*(?:\r?$))", draft[start:end])]


def storyboard_columns(draft):
    lines = list(re.finditer(r"(?m)^[ \t]*\|[^\r\n]*\|[ \t]*(?=\r?$)", draft))
    cells = lambda line: [x.strip().strip("* ").strip() for x in line.group().strip()[1:-1].split("|")]
    tables = [i for i, line in enumerate(lines) if "时长" in cells(line)
              and any(name in cells(line) for name in ("口播", "口播内容", "台词", "口播文案"))]
    if len(tables) != 1 or tables[0] != 0 or len(lines) < 3 or len(lines) > 32:
        raise ScopeError("请提供一张包含时长和口播内容的完整分镜表。")
    headers = cells(lines[0])
    if "景别" in headers:
        raise ScopeError("这张分镜表已经有景别列。")
    column = headers.index("时长")
    spans, context = [], []
    for i, line in enumerate(lines):
        row = cells(line)
        if (len(row) != len(headers) or "\\|" in line.group()
                or i and draft[lines[i - 1].end():line.start()] not in ("\n", "\r\n")):
            raise ScopeError("分镜表的列数或分隔符不一致，原表未修改。")
        if i == 1 and not all(re.fullmatch(r":?-{3,}:?", x) for x in row):
            raise ScopeError("分镜表缺少有效的表头分隔行。")
        at = line.start() + list(re.finditer(r"\|", line.group()))[column].end()
        spans.append((at, at))
        if i > 1:
            context.append({name: value[:320] for name, value in zip(headers, row)
                            if name in ("画面", "画面描述", "口播", "口播内容", "台词", "口播文案")})
    return tuple(spans), context


def prepare(request, previous_draft, previous_user_texts=()):
    draft = request.pasted or previous_draft
    if not draft or len(draft) > MAX_DRAFT:
        raise ScopeError("没有找到可安全修改的完整底稿，请粘贴要改的那一篇。")
    if request.target == "景别":
        spans, context = storyboard_columns(draft)
        return Plan(request, draft, spans, context)
    spans = paragraph_spans(draft)
    if len(spans) < 2:
        raise ScopeError("没有找到明确的段落边界，请粘贴带分段的底稿。")
    index = request.paragraph - 1 if request.paragraph else (0 if request.target == "开头" else len(spans) - 1)
    if index >= len(spans):
        raise ScopeError("底稿没有这么多段，请核对要改的段落。")
    start, end = spans[index]
    adjacent = []
    for i in (index - 1, index + 1):
        if 0 <= i < len(spans):
            lo, hi = spans[i]
            adjacent.append(draft[lo:hi][:520])
    context = {"target": draft[start:end], "adjacent": adjacent}
    if end - start > 3500:
        raise ScopeError("指定段落过长，请缩小修改范围。")
    terms = {}
    for text in (*previous_user_texts, request.instruction):
        updates = [(m.start(), m[1] or m[2], True) for m in BAN.finditer(text)]
        updates.extend((m.start(), m[1], False) for m in UNBAN.finditer(text))
        for _, term, banned in sorted(updates):
            if banned:
                terms[term] = None
            else:
                terms.pop(term, None)
    goal = BODY_GOAL.search(request.instruction)
    return Plan(request, draft, ((start, end),), context, tuple(terms)[-20:],
                (spans[0][0], spans[-1][1]), int(goal[1]) if goal else 0)


def body_count(text):
    return len(re.sub(r"\s+|\*\*|__", "", text))


def upstream_messages(plan):
    shape = ('{"shots":["中景", "..."]}，每行一个景别，顺序对应原表；只用：'
             + "、".join(sorted(SHOT_TYPES))) if plan.request.target == "景别" else (
        '{"replacement":"替换后的单段文字"}，只写指定段落，不得增加标题、说明、话题、其他段落或材料未提供的事实。')
    data = {"instruction": plan.request.instruction, "scope": plan.request.target,
            "draft_excerpt": plan.context, "forbidden_terms": plan.bans}
    if plan.goal:
        fixed_chars = body_count(plan.draft[slice(*plan.body_span)]) - body_count(plan.context["target"])
        data["body_target_chars"] = plan.goal
        data["unchanged_body_chars"] = fixed_chars
    return [
        {"role": "system", "content": "你只负责本轮局部编辑。相邻内容仅作参考，不能修改。返回单个 JSON 对象，不加 Markdown 围栏。输出格式：" + shape},
        {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
    ]


def apply_result(plan, raw, completed):
    report = {"version": VERSION, "status": "issues", "repaired": False, "issues": [], "calls": []}
    if not completed:
        report["notice"] = "上游未完成，本轮未替换任何文字。"
        return plan.draft, report
    try:
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError
        if plan.request.target == "景别":
            shots = value.get("shots")
            if set(value) != {"shots"} or not isinstance(shots, list) or len(shots) != len(plan.spans) - 2:
                raise ValueError
            if any(not isinstance(shot, str) or shot not in SHOT_TYPES for shot in shots):
                raise ValueError
            replacements = [" 景别 |", " --- |", *[f" {shot} |" for shot in shots]]
        else:
            replacement = value.get("replacement")
            if set(value) != {"replacement"} or not isinstance(replacement, str):
                raise ValueError
            replacement = replacement.strip()
            if (not replacement or len(replacement) > min(3500, max(500, len(plan.context["target"]) * 2))
                    or "\n" in replacement or "\r" in replacement or BODY.match(replacement) or BOUNDARY.match(replacement)):
                raise ValueError
            visible = re.sub(r"[*_`]", "", replacement).casefold()
            banned = [term for term in plan.bans if term.casefold() in visible]
            if banned:
                report["notice"] = "新片段仍包含本单明确禁用的词，原稿未修改。"
                report["issues"] = [f"新片段包含「{term}」" for term in banned]
                return plan.draft, report
            replacements = [replacement]
    except (ValueError, RecursionError):
        report["notice"] = "没有收到符合范围的修改片段，原稿未修改。"
        return plan.draft, report
    result = plan.draft
    for (start, end), replacement in reversed(list(zip(plan.spans, replacements))):
        result = result[:start] + replacement + result[end:]
    report.update(status="passed", repaired=result != plan.draft,
                  notice=f"已仅修改{plan.request.target}，其余原文保留。" if result != plan.draft else "本轮片段与原稿一致。")
    if plan.goal:
        start, end = plan.body_span
        report["notice"] += f" 本次正文约 {body_count(result[start:end + len(result) - len(plan.draft)])} 字，目标约 {plan.goal} 字。"
    return result, report
