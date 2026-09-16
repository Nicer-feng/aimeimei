from .shared import *
from .. import writing


class WritingHandlersMixin:
    def handle_writing(self):
        cid, uid = self.conversation_id_from_path(), self.current_user()["id"]
        lock = writing.task_lock(uid, cid)
        if not lock.acquire(blocking=False):
            return self.error(HTTPStatus.CONFLICT, "当前对话正在生成或保存，请稍后再试")
        try:
            with db() as conn:
                convo = conn.execute("SELECT id,writing_mode FROM conversations WHERE id=? AND user_id=? AND archived=0", (cid, uid)).fetchone()
                if not convo:
                    return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
                if self.command == "GET":
                    result = writing.public_state(conn, cid, uid)
                    vid = parse_qs(urlparse(self.path).query).get("version_id", [""])[0]
                    if vid:
                        result["selected"] = writing.get_version(conn, cid, uid, vid)
                        if not result["selected"]:
                            return self.error(HTTPStatus.NOT_FOUND, "稿件版本不存在")
                    return self.json({"writing": result, "enabled": bool(convo["writing_mode"])})
                try:
                    data = self.read_body(limit=256 * 1024)
                    if not isinstance(data, dict):
                        raise ValueError("invalid json")
                    state = writing.get_state(conn, cid, uid)
                    if data.get("revision") != state["revision"]:
                        return self.error(HTTPStatus.CONFLICT, "本单要求已更新，请重新打开后再保存")
                    if "requirements" in data:
                        state["requirements_json"] = json.dumps(writing.requirements(data["requirements"]), ensure_ascii=False)
                    if "enabled" in data:
                        if not isinstance(data["enabled"], bool):
                            raise ValueError("写稿模式值不正确")
                        conn.execute("UPDATE conversations SET writing_mode=? WHERE id=? AND user_id=?", (int(data["enabled"]), cid, uid))
                    if data.get("action") == "reset":
                        state.update(history_start_id=conn.execute("SELECT COALESCE(MAX(id),0)+1 n FROM messages WHERE conversation_id=? AND user_id=?", (cid,uid)).fetchone()["n"], requirements_json="{}", current_version_id=0, locked_version_id=0, notice="已开始新项目，旧版本保留但不带入本单要求。")
                    elif "draft" in data:
                        draft = data["draft"]
                        if not isinstance(draft, str) or not 1 <= len(draft.strip()) <= 100000:
                            raise ValueError("稿件须为 1 至 100000 字")
                        vid = writing.save_version(conn, cid, uid, draft.strip(), "手动保存", now())
                        state.update(current_version_id=vid, locked_version_id=0)
                    elif "version_id" in data:
                        version = writing.get_version(conn, cid, uid, data["version_id"])
                        if not version:
                            raise ValueError("稿件版本不存在")
                        state.update(current_version_id=version["id"], locked_version_id=0)
                    if "locked" in data:
                        if not isinstance(data["locked"], bool):
                            raise ValueError("定稿状态不正确")
                        if data["locked"] and not state["current_version_id"]:
                            raise ValueError("请先选择或保存正文，再锁定定稿")
                        state["locked_version_id"] = state["current_version_id"] if data["locked"] else 0
                    state["revision"] += 1
                    state["updated_at"] = now()
                    writing.save_state(conn, state)
                    result = writing.public_state(conn, cid, uid)
                except (ValueError, TypeError) as exc:
                    conn.rollback()
                    return self.error(HTTPStatus.BAD_REQUEST, str(exc))
                return self.json({"writing": result, "ok": True})
        finally:
            lock.release()

    def prepare_writing(self, convo, text, documents, history):
        cid, uid = convo["id"], convo["user_id"]
        with db() as conn:
            state = writing.get_state(conn, cid, uid)
            current = writing.get_version(conn, cid, uid, state["current_version_id"])
        historical_base = None
        if not current and re.search(r"基础上|上面|最终|定稿|分镜|这个脚本", text):
            for row in reversed(history[:-1]):
                if row["role"] == "assistant" and (re.search(r"正文[：:]", row["content"]) or writing.table_dialogue(row["content"])):
                    historical_base = dict(row)
                    current = {"id": 0, "content": row["content"]}
                    break
        usage = None
        try:
            plan, usage, notice = writing.plan_request(convo, state, current, text, documents, history)
        except Exception:
            plan, notice = None, "本轮自动整理暂不可用，沿用已保存要求；可在本单要求中手动修正。"
        if not plan:
            plan = writing.fallback_plan(state, text)
        state["notice"] = notice
        with db() as conn:
            # Record auxiliary usage even if the subsequent main generation fails.
            if usage:
                pt, ct, total = parse_usage_tokens(usage)
                cached, creation = parse_usage_cache_tokens(usage)
                ip, op = parse_price(convo["input_price_per_million"]), parse_price(convo["output_price_per_million"])
                cost = estimate_request_cost(pt, ct, ip, op, bool(convo["cost_enabled"]))
                conn.execute("""INSERT INTO messages(user_id,conversation_id,role,content,prompt_tokens,completion_tokens,total_tokens,
                    cached_tokens,cache_creation_tokens,estimated_cost,cost_input_price,cost_output_price,cost_model_id,actual_model,created_at)
                    VALUES (?,?,'system','写稿要求整理（辅助调用）',?,?,?,?,?,?,?,?,?,?,?)""",
                    (uid,cid,pt,ct,total,cached,creation,cost,ip if convo["cost_enabled"] else 0,op if convo["cost_enabled"] else 0,convo["model_id"],convo["model"],now()))
                add_daily_usage(conn, uid, now(), pt, ct, total, cost, cached, creation)
            if plan["new_project"]:
                state.update(current_version_id=0, locked_version_id=0, history_start_id=history[-1]["id"])
                current = None
            state["requirements_json"] = json.dumps(plan["requirements"], ensure_ascii=False)
            if historical_base and current and not plan["new_project"] and plan["intent"] in {"revise", "storyboard", "titles"}:
                vid = writing.save_version(conn, cid, uid, current["content"], "历史正文底稿", now(), historical_base["id"])
                state["current_version_id"] = vid
                current = writing.get_version(conn, cid, uid, vid)
            elif current and not current["id"]:
                current = None
            if plan["pasted_draft"]:
                vid = writing.save_version(conn, cid, uid, plan["pasted_draft"], "用户指定底稿", now())
                state.update(current_version_id=vid, locked_version_id=0)
                current = writing.get_version(conn, cid, uid, vid)
            if plan["confirmed"] and not current:
                state["notice"] = "尚未确定定稿底稿，请在本单要求中选定正文并锁定后再转分镜。"
            if plan["confirmed"] and current:
                state["locked_version_id"] = current["id"]
            state["revision"] += 1
            state["updated_at"] = now()
            writing.save_state(conn, state)
        return state, current, plan

    def finish_writing(self, conn, state, current, plan, text, message_id):
        cid, uid = state["conversation_id"], state["user_id"]
        locked = current["content"] if current and state["locked_version_id"] else None
        target = plan.get("replace_text", "")
        merged = current["content"].replace(target, text, 1) if current and target else None
        check = writing.validate_output(merged or text, plan["requirements"], plan["intent"], locked)
        if state["notice"]:
            check["issues"].append(state["notice"])
        if plan["intent"] in {"draft", "revise", "rewrite", "variant"}:
            vid = writing.save_version(conn, cid, uid, merged or text, "正文版本" if plan.get("full_manuscript") or merged else "局部修改", now(), message_id)
            if plan.get("full_manuscript", False) or merged:
                state.update(current_version_id=vid, locked_version_id=0)
            else:
                check["issues"].append("本轮为局部修改，原底稿保留；可在本单要求中合并或选择新的完整稿件。")
        state["revision"] += 1
        state["updated_at"] = now()
        writing.save_state(conn, state)
        conn.execute("INSERT INTO writing_checks(message_id,user_id,result_json) VALUES (?,?,?)", (message_id, uid, json.dumps(check, ensure_ascii=False)))
        return check
