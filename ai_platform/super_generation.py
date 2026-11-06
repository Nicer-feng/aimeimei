"""超能槑槑只做成稿后的有限检查，不干预原流程的主模型输入或正文。"""
import json
import re
import urllib.request

from . import writing, super_writing, super_review, super_sources, super_evidence_review, super_single_review
from .database import db
from .model_options import prepare_chat_payload
from .openai_egress import open_model_request
from .runtime import now
from .usage import (parse_usage_tokens, parse_usage_cache_tokens, parse_price,
                    estimate_request_cost, add_daily_usage)


VERSION = "super-postcheck-v6"


def _intent(text):
    tail = text[-1800:]
    if re.search(r"(?:先)?(?:只|仅)(?:回答|解释|讨论)(?:问题|一下|这个)?", tail):
        return "question"
    positive = re.sub(r"(?:不要|不用|无需|别|不需要)(?:再)?(?:写|生成|提供|输出)?(?:完整)?(?:正文|脚本|口播稿)", "", tail)
    if (re.search(r"(?:只|仅)(?:给我|需要|要|生成|写|提供|输出)?[^。！？\n]{0,24}(?:标题|封面文案|发布文案)", positive)
            and not re.search(r"正文|完整.{0,3}(脚本|稿)|口播稿", positive)):
        return "titles"
    if re.search(r"分镜|转.{0,4}表格", tail):
        return "storyboard"
    if re.search(r"(?:写|给|来|生成|提供|输出).{0,12}(?:条|组|个)?评论|评论.{0,12}(?:带上回复|一半问答)", tail):
        return "question"
    if re.search(r"标题|封面", positive) and not re.search(r"正文|完整.{0,3}(脚本|稿)|口播稿", positive):
        return "titles"
    if re.search(r"口播|脚本|正文|稿件|重写|改稿", text):
        return "revise" if re.search(r"修改|改一下|基础上|重写|再写|优化", tail) else "draft"
    return "question"


def _json_object(text):
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value)
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError("辅助结果不是对象")
    return result


def _record(run, model, stage, usage):
    """每次调用独立记账，不能等待主生成成功后再补记。"""
    known = isinstance(usage, dict) and any(k in usage for k in ("prompt_tokens", "input_tokens", "completion_tokens", "output_tokens", "total_tokens"))
    pt, ct, total = parse_usage_tokens(usage)
    cached, creation = parse_usage_cache_tokens(usage)
    ip, op = parse_price(model.get("input_price_per_million")), parse_price(model.get("output_price_per_million"))
    enabled = bool(model.get("cost_enabled"))
    cost = estimate_request_cost(pt, ct, ip, op, enabled)
    entry = {"stage": stage, "model": model["model"], "prompt_tokens": pt,
             "completion_tokens": ct, "total_tokens": total, "cached_tokens": cached,
             "cache_creation_tokens": creation, "estimated_cost": cost, "usage_known": known}
    with db() as conn:
        if not conn.execute("SELECT 1 FROM conversations WHERE id=? AND user_id=? AND archived=0",
                            (run["cid"], run["uid"])).fetchone():
            return
        ts = now()
        conn.execute("""INSERT INTO messages(user_id,conversation_id,role,content,prompt_tokens,
            completion_tokens,total_tokens,cached_tokens,cache_creation_tokens,estimated_cost,
            cost_input_price,cost_output_price,cost_model_id,actual_model,created_at,generation_status)
            VALUES (?,?,'system',?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (run["uid"], run["cid"], stage + ("（用量未返回）" if not known else ""), pt, ct,
             total, cached, creation, cost, ip if enabled else 0, op if enabled else 0,
             model.get("model_id") or model.get("id"), model["model"], ts,
             "completed" if known else "usage_unknown"))
        if known:
            add_daily_usage(conn, run["uid"], ts, pt, ct, total, cost, cached, creation)
    run["calls"].append(entry)


def _call(run, model, stage, instruction, data, max_tokens=2400):
    payload = {"model": model["model"], "messages": [
        {"role": "system", "content": stage + "\n" + instruction},
        {"role": "user", "content": json.dumps(data, ensure_ascii=False)}],
        "stream": False, "max_tokens": max_tokens}
    if str(model["model"]).startswith("qwen"):
        payload["enable_thinking"] = False
    payload = prepare_chat_payload(payload, model, auxiliary=True)
    request = urllib.request.Request(model["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Authorization": "Bearer " + model["api_key"].strip(), "Content-Type": "application/json"},
        method="POST")
    recorded = False
    try:
        with open_model_request(request, timeout=25) as response:
            raw = response.read(2 * 1024 * 1024)
        result = json.loads(raw.decode())
        _record(run, model, stage, result.get("usage"))
        recorded = True
        choice = (result.get("choices") or [{}])[0]
        if choice.get("finish_reason") not in (None, "stop"):
            raise ValueError("辅助结果未完整生成")
        return _json_object((choice.get("message") or {}).get("content"))
    except Exception:
        if not recorded:
            _record(run, model, stage, None)
        raise


def record_summary(conversation, usage):
    """后台摘要也是当前对话的实际开销，不藏在交付调用之外。"""
    run = {"cid": conversation["id"], "uid": conversation["user_id"], "calls": []}
    _record(run, dict(conversation), "超能槑槑会话摘要", usage)


def prepare(conversation, text, document_context, history, document_coverage=None):
    """只收集本单原始材料与可追溯要求，不调用整理模型、不修改主请求。"""
    cid, uid = conversation["id"], conversation["user_id"]
    with db() as conn:
        state = dict(super_writing.get_task_state(conn, cid, uid))
        first = conn.execute("SELECT content FROM messages WHERE conversation_id=? AND user_id=? AND role='user' ORDER BY id LIMIT 1", (cid, uid)).fetchone()
        raw_rows = conn.execute("""SELECT id,role,content FROM messages
            WHERE conversation_id=? AND user_id=? AND role='user' ORDER BY id DESC LIMIT 81""", (cid, uid)).fetchall()
        flash = conn.execute("""SELECT * FROM models WHERE enabled=1 AND TRIM(api_key)!=''
            AND model IN ('qwen3.8-flash','qwen3.8-omni-flash')
            ORDER BY CASE model WHEN 'qwen3.8-flash' THEN 0 ELSE 1 END, id LIMIT 1""").fetchone()
    brief = str(first["content"] if first else text)
    if len(brief) > 30000:
        raise ValueError("材料超出本版后置检查范围")
    state["source_brief"] = brief
    excerpts = state.get("material_excerpts")
    excerpts = [item for item in excerpts if isinstance(item, str)] if isinstance(excerpts, list) else []
    if document_context and document_context not in excerpts:
        if sum(map(len, excerpts)) + len(document_context) <= 34000:
            excerpts.append(document_context)
        else:
            state["material_excerpts_incomplete"] = True
    state["material_excerpts"] = excerpts
    if document_coverage is not None:
        # 仅由真实附件路径的结构元数据启用，跨轮保留；粘贴正文的格式不能触发结构推断。
        state["postcheck_preserve_source_tables"] = True
    # 后审独立读取本单原始用户消息，不能让主流程摘要水位或12条窗口吞掉事实更正。
    raw_history = [dict(row) for row in reversed(raw_rows[:80])]
    evidence, incomplete = super_sources.build_evidence(state, uid, cid, raw_history, text, document_context)
    incomplete = bool(incomplete or len(raw_rows) > 80 or len(evidence) > 70000)
    # 旧整理器保存的 requirements、底稿、客户上传稿均不充当新硬要求或事实依据。
    document_incomplete = document_coverage is not None and document_coverage.get("complete") is not True
    if document_incomplete:
        # 片段会跨轮保存在material_excerpts中；不能在下一轮未重选附件时把已知缺口当成完整材料。
        state["material_excerpts_incomplete"] = True
    req, audit = super_review.requirements_from_source(text if incomplete or document_incomplete else evidence)
    audit["source_history_incomplete"] = incomplete
    audit["material_excerpts_incomplete"] = bool(state.get("material_excerpts_incomplete"))
    if document_coverage is not None:
        audit["document_sources"] = {key: document_coverage[key] for key in
                                     ("complete", "selected_ids", "notices", "total_chunks", "selected_chunks")
                                     if key in document_coverage}
    audit["complete"] = bool(audit["complete"] and not incomplete and not audit["material_excerpts_incomplete"]
                             and not document_incomplete)
    intent = _intent(text)
    if (intent == "question" and re.search(r"只改|改一下|结尾|开头|删掉|压缩|缩短|字数", text[-1200:])
            and not re.search(r"评论|回复|(?:只|仅)(?:回答|解释|讨论)", text[-1200:])):
        intent = "revise"
    run = {"cid": cid, "uid": uid, "state": state,
           "plan": {"requirements": req, "intent": intent}, "flash": dict(flash) if flash else None,
           "calls": [], "notice": "", "text": text, "documents": document_context,
           "evidence": evidence, "literal_term_audit": audit, "version": VERSION,
           "source_complete": not incomplete and not audit["material_excerpts_incomplete"] and not document_incomplete}
    if state.get("postcheck_preserve_source_tables") is True:
        run["preserve_source_tables"] = True
    # 此处只保存原始出处和本轮检查配置，不推进旧底稿/锁稿/整理器状态。
    state["postcheck_requirements"] = req
    with db() as conn:
        if conn.execute("SELECT 1 FROM conversations WHERE id=? AND user_id=? AND archived=0", (cid, uid)).fetchone():
            super_writing.save_task_state(conn, cid, uid, state)
    return run


def prompt_context(run):
    """开启后置检查不新增任何主模型输入。"""
    return ""


def finish(run, text, conversation):
    """返回原文与检查记录；任何成功、拒绝、失败分支都不改稿。"""
    plan = run["plan"]
    req, scope, scope_notice = super_review.output_scope(plan["requirements"], run["text"])
    check = writing.validate_output(text, req, plan["intent"])
    if scope_notice:
        check["count_notice"] = scope_notice + check.get("count_notice", "")
    result = {"status": "skipped", "notice": "本轮只做确定性检查，未执行模型复核。", "issues": [], "repaired": False,
              "version": VERSION, "body_chars": check["body_chars"], "deterministic_issues": check["issues"],
              "repair": {"status": "disabled_review_only", "attempted": False},
              "review_complete": False, "review_rejected": [], "review_unverified": [], "literal_term_audit": run.get("literal_term_audit", {}),
              "length_requirement": plan["requirements"].get("length_requirement", {}),
              "check_scope": scope, "scope_notice": scope_notice}
    for key in ("body_status", "body_scope", "sections", "count_note", "count_notice"):
        if key in check:
            result[key] = check[key]
    if run["flash"] and plan["intent"] in {"draft", "revise", "rewrite", "variant", "storyboard"}:
        if not run.get("source_complete", True):
            result["notice"] = "本单原始材料未能完整纳入，本轮跳过模型复核，避免使用过期事实判断；仅列出可确认的本轮规则检查。"
        elif len(text) > 18000 or len(run["evidence"]) > 70000:
            result["notice"] = "稿件或材料较长，本轮仅做确定性检查，未完成模型复核。"
        else:
            try:
                packet = super_evidence_review.build_packet(run["evidence"], text,
                    preserve_source_tables=run.get("preserve_source_tables", False))
                if not packet["complete"]:
                    result["notice"] = "原始材料或稿件单元超出本轮检查范围，已跳过模型复核；原稿保持不变。"
                    result["review_unverified"] = [{"status": "not_checked", "reason": notice}
                                                   for notice in packet.get("notices", [])]
                    result["usage_unknown"] = any(not call["usage_known"] for call in run["calls"])
                    return text, result
                # 只发本单完整原文，代码提取的规则不替代原始需求，也不暗示模型结论。
                data = super_single_review.build_data(packet, current_request=run["text"], scope=scope_notice or None)
                result["review_method"] = "single_pass"
                inspected = _call(run, run["flash"], "超能槑槑交付校验",
                                  super_single_review.REVIEW_INSTRUCTION, data, 2400)
                reviewed = super_single_review.decode_review(inspected, packet, source_complete=run.get("source_complete", True))
                result.update(reviewed)
                if (not run.get("literal_term_audit", {}).get("complete", True)
                        or check.get("body_status") == "unrecognized"):
                    result["review_complete"] = False
                status = ("issues" if reviewed["issues"] or check["issues"] else
                          "reviewed" if result["review_complete"] else "failed")
                notice = ("已列出本单事实或条件的待核对内容，原稿保持不变。" if status == "issues" else
                          "本轮未发现可定位的事实疑点，不代表全部正确或客户验收。")
                if not result["review_complete"]:
                    notice = "部分检查无法可靠定位、缺少依据或正文范围不明确，本轮检查未完整完成；原稿保持不变。"
                result.update(status=status, notice=notice)
            except Exception:
                result.update(status="failed", issues=[], review_complete=False,
                              notice="本次模型复检未完成，原稿保持不变；仅保留确定性检查结果。")
    elif not run["flash"]:
        result["notice"] = "未配置可用的Flash，本轮仅做确定性检查，原稿保持不变。"
    result["usage_unknown"] = any(not call["usage_known"] for call in run["calls"])
    return text, result


def combined_usage(run, main_usage):
    result = dict(main_usage)
    for call in run["calls"]:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens", "cache_creation_tokens", "estimated_cost"):
            result[key] = result.get(key, 0) + call.get(key, 0)
    result["estimated_cost"] = round(result.get("estimated_cost", 0), 8)
    return result
