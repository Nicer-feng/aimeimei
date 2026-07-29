from .shared import *


class ChatHandlersMixin:
    def side_discussion_id_from_path(self):
        parts = urllib.parse.urlparse(self.path).path.strip("/").split("/")
        return urllib.parse.unquote(parts[2]) if len(parts) >= 3 else ""

    def side_discussion_row(self, conn, discussion_id, user_id):
        return conn.execute(
            """
            SELECT d.*, m.name AS model_name, m.model AS model,
                   COUNT(dm.id) AS message_count
            FROM side_discussions d
            JOIN models m ON m.id=d.model_id
            LEFT JOIN side_discussion_messages dm ON dm.discussion_id=d.id
            WHERE d.id=? AND d.user_id=?
            GROUP BY d.id
            """,
            (discussion_id, user_id),
        ).fetchone()

    def handle_side_discussions(self):
        user_id = self.current_user()["id"]
        if self.command == "GET":
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            session_id = str((query.get("session_id") or [""])[0]).strip()
            if not session_id:
                return self.error(HTTPStatus.BAD_REQUEST, "session_id required")
            with db() as conn:
                conversation = conn.execute(
                    "SELECT id FROM conversations WHERE id=? AND user_id=? AND archived=0",
                    (session_id, user_id),
                ).fetchone()
                if not conversation:
                    return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
                rows = conn.execute(
                    """
                    SELECT d.*, m.name AS model_name, m.model AS model,
                           COUNT(dm.id) AS message_count
                    FROM side_discussions d
                    JOIN models m ON m.id=d.model_id
                    LEFT JOIN side_discussion_messages dm ON dm.discussion_id=d.id
                    WHERE d.session_id=? AND d.user_id=?
                    GROUP BY d.id
                    ORDER BY d.updated_at DESC
                    LIMIT 50
                    """,
                    (session_id, user_id),
                ).fetchall()
            return self.json({"discussions": [side_discussion_public(row) for row in rows]})

        try:
            data = self.read_body(limit=256 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        session_id = str(data.get("session_id") or "").strip()
        selected_text = str(data.get("selected_text") or "").strip()
        try:
            source_message_id = int(data.get("source_message_id") or 0)
        except (TypeError, ValueError):
            source_message_id = 0
        if not session_id or not source_message_id:
            return self.error(HTTPStatus.BAD_REQUEST, "引用来源不完整")
        if len(selected_text) < 2:
            return self.error(HTTPStatus.BAD_REQUEST, "请至少选择 2 个字符")
        selected_text = selected_text[:12000]
        with db() as conn:
            source = conn.execute(
                """
                SELECT c.id AS session_id, c.title AS conversation_title, c.model_id,
                       msg.role AS source_role, msg.created_at AS source_created_at
                FROM conversations c
                JOIN messages msg ON msg.conversation_id=c.id AND msg.user_id=c.user_id
                WHERE c.id=? AND c.user_id=? AND c.archived=0
                  AND msg.id=? AND msg.role IN ('user', 'assistant')
                """,
                (session_id, user_id, source_message_id),
            ).fetchone()
            if not source:
                return self.error(HTTPStatus.NOT_FOUND, "引用消息不存在")
            discussion_id = b64_token(12)
            title = re.sub(r"\s+", " ", selected_text).strip()[:36] or "侧边讨论"
            ts = now()
            conn.execute(
                """
                INSERT INTO side_discussions(
                  id, user_id, session_id, source_message_id, source_role,
                  source_created_at, selected_text, model_id, title, status,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (
                    discussion_id,
                    user_id,
                    session_id,
                    source_message_id,
                    source["source_role"],
                    source["source_created_at"],
                    selected_text,
                    source["model_id"],
                    title,
                    ts,
                    ts,
                ),
            )
            row = self.side_discussion_row(conn, discussion_id, user_id)
        return self.json({"discussion": side_discussion_public(row)}, status=HTTPStatus.CREATED)

    def handle_side_discussion_item(self):
        user_id = self.current_user()["id"]
        discussion_id = self.side_discussion_id_from_path()
        with db() as conn:
            row = self.side_discussion_row(conn, discussion_id, user_id)
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "side discussion not found")
            messages = conn.execute(
                """
                SELECT *
                FROM side_discussion_messages
                WHERE discussion_id=?
                ORDER BY id ASC
                LIMIT 200
                """,
                (discussion_id,),
            ).fetchall()
        return self.json(
            {
                "discussion": side_discussion_public(row),
                "messages": [side_discussion_message_public(message) for message in messages],
            }
        )

    def handle_side_discussion_send(self):
        user_id = self.current_user()["id"]
        discussion_id = self.side_discussion_id_from_path()
        try:
            data = self.read_body(limit=1024 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        content = str(data.get("content") or "").strip()
        if not content:
            return self.error(HTTPStatus.BAD_REQUEST, "请输入想继续讨论的问题")

        with db() as conn:
            discussion = conn.execute(
                """
                SELECT d.*, c.title AS conversation_title,
                       m.name AS model_name, m.model, m.base_url, m.api_key,
                       m.system_prompt, m.enabled, m.input_price_per_million,
                       m.output_price_per_million, m.cost_enabled
                FROM side_discussions d
                JOIN conversations c ON c.id=d.session_id AND c.user_id=d.user_id
                JOIN models m ON m.id=d.model_id
                WHERE d.id=? AND d.user_id=?
                """,
                (discussion_id, user_id),
            ).fetchone()
            if not discussion:
                return self.error(HTTPStatus.NOT_FOUND, "side discussion not found")
            if not discussion["enabled"]:
                return self.error(HTTPStatus.BAD_REQUEST, "当前讨论使用的模型已停用")
            if not str(discussion["api_key"] or "").strip():
                return self.error(HTTPStatus.BAD_REQUEST, "当前模型尚未配置 API Key")
            ts = now()
            conn.execute(
                """
                INSERT INTO side_discussion_messages(discussion_id, role, content, created_at)
                VALUES (?, 'user', ?, ?)
                """,
                (discussion_id, content, ts),
            )
            conn.execute(
                "UPDATE side_discussions SET updated_at=? WHERE id=? AND user_id=?",
                (ts, discussion_id, user_id),
            )
            history = conn.execute(
                """
                SELECT role, content
                FROM side_discussion_messages
                WHERE discussion_id=?
                ORDER BY id ASC
                LIMIT 60
                """,
                (discussion_id,),
            ).fetchall()

        source_role = "槑槑回复" if discussion["source_role"] == "assistant" else "用户消息"
        system_context = (
            "你正在围绕主会话中的一段引用内容进行独立讨论。\n"
            f"主会话标题：{discussion['conversation_title']}\n"
            f"来源：{source_role}\n\n"
            "引用内容：\n"
            f"{discussion['selected_text']}\n\n"
            "请只依据这段引用内容和用户在侧边栏提出的问题回答。"
            "不要假设你已经看过完整主会话；如果材料不足，请明确说明。"
        )
        upstream_messages = [{"role": "system", "content": system_context}]
        if str(discussion["system_prompt"] or "").strip():
            upstream_messages.append(
                {"role": "system", "content": str(discussion["system_prompt"]).strip()}
            )
        upstream_messages.extend(
            {"role": row["role"], "content": row["content"]} for row in history
        )

        def make_payload(include_usage):
            payload = {
                "model": discussion["model"],
                "messages": upstream_messages,
                "stream": True,
            }
            if include_usage:
                payload["stream_options"] = {"include_usage": True}
            return payload

        def open_upstream(payload):
            request = urllib.request.Request(
                str(discussion["base_url"]).rstrip("/") + "/chat/completions",
                data=json.dumps(payload, ensure_ascii=False).encode(),
                headers={
                    "Authorization": "Bearer " + str(discussion["api_key"]).strip(),
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "User-Agent": "ai-platform/2.0",
                },
                method="POST",
            )
            return urllib.request.urlopen(request, timeout=120)

        try:
            response = open_upstream(make_payload(True))
        except urllib.error.HTTPError as exc:
            detail = exc.read(65536).decode(errors="replace")
            if exc.code == 400 and usage_option_rejected(detail):
                try:
                    response = open_upstream(make_payload(False))
                except urllib.error.HTTPError as retry:
                    retry_detail = retry.read(65536).decode(errors="replace")
                    return self.error(
                        HTTPStatus.BAD_GATEWAY,
                        f"侧边讨论模型请求失败（{retry.code}）",
                        retry_detail,
                    )
                except Exception as retry:
                    return self.error(HTTPStatus.BAD_GATEWAY, "侧边讨论模型请求失败", str(retry))
            else:
                return self.error(
                    HTTPStatus.BAD_GATEWAY,
                    f"侧边讨论模型请求失败（{exc.code}）",
                    detail,
                )
        except Exception as exc:
            return self.error(HTTPStatus.BAD_GATEWAY, "侧边讨论模型请求失败", str(exc))

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        assistant_parts = []
        reasoning_parts = []
        usage_data = None
        buffer = ""
        try:
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except Exception:
                    pass
                buffer += chunk.decode(errors="ignore")
                lines = buffer.splitlines(keepends=True)
                if lines and not lines[-1].endswith(("\n", "\r")):
                    buffer = lines.pop()
                else:
                    buffer = ""
                for line in lines:
                    text = line.strip()
                    if not text.startswith("data:"):
                        continue
                    data_text = text[5:].strip()
                    if not data_text or data_text == "[DONE]":
                        continue
                    try:
                        event = json.loads(data_text)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event.get("usage"), dict):
                        usage_data = event["usage"]
                    choice = (event.get("choices") or [{}])[0]
                    if isinstance(choice.get("usage"), dict):
                        usage_data = choice["usage"]
                    delta = choice.get("delta") or {}
                    message = choice.get("message") or {}
                    piece = delta.get("content") or message.get("content") or ""
                    reasoning_piece = (
                        delta.get("reasoning_content")
                        or message.get("reasoning_content")
                        or delta.get("reasoning")
                        or message.get("reasoning")
                        or ""
                    )
                    if piece:
                        assistant_parts.append(str(piece))
                    if reasoning_piece:
                        reasoning_parts.append(str(reasoning_piece))
        finally:
            response.close()

        assistant_text = "".join(assistant_parts).strip()
        reasoning_text = "".join(reasoning_parts).strip()
        assistant_text, think_reasoning = split_think_blocks(assistant_text)
        if think_reasoning:
            reasoning_text = (reasoning_text + "\n\n" + think_reasoning).strip()
        if not assistant_text:
            return
        prompt_tokens, completion_tokens, total_tokens = parse_usage_tokens(usage_data)
        input_price = parse_price(discussion["input_price_per_million"])
        output_price = parse_price(discussion["output_price_per_million"])
        estimated_cost = estimate_request_cost(
            prompt_tokens,
            completion_tokens,
            input_price,
            output_price,
            bool(discussion["cost_enabled"]),
        )
        created_at = now()
        with db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO side_discussion_messages(
                  discussion_id, role, content, reasoning_content,
                  input_tokens, output_tokens, total_tokens,
                  estimated_cost, actual_model, created_at
                )
                VALUES (?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    discussion_id,
                    assistant_text,
                    reasoning_text,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    estimated_cost,
                    discussion["model"],
                    created_at,
                ),
            )
            conn.execute(
                "UPDATE side_discussions SET updated_at=? WHERE id=? AND user_id=?",
                (created_at, discussion_id, user_id),
            )
            add_daily_usage(
                conn,
                user_id,
                created_at,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                estimated_cost,
            )
        event = {
            "type": "message_saved",
            "discussion_id": discussion_id,
            "message_id": cursor.lastrowid,
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "estimated_cost": estimated_cost,
            },
        }
        try:
            self.wfile.write(("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()
        except Exception:
            pass

    def handle_side_discussion_conversation(self):
        user_id = self.current_user()["id"]
        discussion_id = self.side_discussion_id_from_path()
        with db() as conn:
            discussion = self.side_discussion_row(conn, discussion_id, user_id)
            if not discussion:
                return self.error(HTTPStatus.NOT_FOUND, "side discussion not found")
            model = conn.execute(
                "SELECT id FROM models WHERE id=? AND enabled=1",
                (discussion["model_id"],),
            ).fetchone()
            if not model:
                return self.error(HTTPStatus.BAD_REQUEST, "当前讨论使用的模型已停用")
            side_messages = conn.execute(
                """
                SELECT *
                FROM side_discussion_messages
                WHERE discussion_id=?
                ORDER BY id ASC
                """,
                (discussion_id,),
            ).fetchall()
            conversation_id = b64_token(12)
            ts = now()
            title = ("侧边讨论：" + discussion["title"])[:80]
            conn.execute(
                """
                INSERT INTO conversations(id, user_id, title, model_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (conversation_id, user_id, title, discussion["model_id"], ts, ts),
            )
            source_role = "槑槑回复" if discussion["source_role"] == "assistant" else "用户消息"
            source_message = (
                f"围绕以下{source_role}继续讨论：\n\n"
                f"> {discussion['selected_text'].replace(chr(10), chr(10) + '> ')}"
            )
            conn.execute(
                """
                INSERT INTO messages(user_id, conversation_id, role, content, created_at)
                VALUES (?, ?, 'user', ?, ?)
                """,
                (user_id, conversation_id, source_message, ts),
            )
            for message in side_messages:
                conn.execute(
                    """
                    INSERT INTO messages(
                      user_id, conversation_id, role, content, reasoning_content,
                      actual_model, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        conversation_id,
                        message["role"],
                        message["content"],
                        message["reasoning_content"],
                        message["actual_model"],
                        message["created_at"],
                    ),
                )
            row = conn.execute(
                """
                SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision,
                       m.supports_native_web_search
                FROM conversations c
                JOIN models m ON m.id=c.model_id
                WHERE c.id=? AND c.user_id=?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return self.json({"conversation": conversation_row(row)}, status=HTTPStatus.CREATED)

    def handle_conversations(self):
        user = self.current_user()
        user_id = user["id"]
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision,
                           m.supports_native_web_search
                    FROM conversations c
                    JOIN models m ON m.id = c.model_id
                    WHERE c.archived=0 AND c.user_id=?
                    ORDER BY c.pinned DESC, c.updated_at DESC
                    LIMIT 200
                    """,
                    (user_id,),
                ).fetchall()
            return self.json({"conversations": [conversation_row(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        model_id = str(data.get("model_id") or "").strip()
        title = str(data.get("title") or "新对话").strip()[:80] or "新对话"
        with db() as conn:
            model = conn.execute(
                "SELECT * FROM models WHERE id=? AND enabled=1", (model_id,)
            ).fetchone()
            if not model:
                return self.error(HTTPStatus.BAD_REQUEST, "model not found")
            conversation_id = b64_token(12)
            ts = now()
            conn.execute(
                """
                INSERT INTO conversations(id, user_id, title, model_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (conversation_id, user_id, title, model_id, ts, ts),
            )
            row = conn.execute(
                """
                SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision,
                       m.supports_native_web_search
                FROM conversations c JOIN models m ON m.id=c.model_id
                WHERE c.id=? AND c.user_id=?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return self.json({"conversation": conversation_row(row)}, HTTPStatus.CREATED)

    def conversation_id_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) >= 3:
            return parts[2]
        return ""

    def handle_conversation_pin(self):
        conversation_id = self.conversation_id_from_path()
        user_id = self.current_user()["id"]
        pinned = 0 if urlparse(self.path).path.endswith("/unpin") else 1
        with db() as conn:
            existing = conn.execute(
                "SELECT id FROM conversations WHERE id=? AND user_id=? AND archived=0",
                (conversation_id, user_id),
            ).fetchone()
            if not existing:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
            conn.execute(
                "UPDATE conversations SET pinned=?, pinned_at=? WHERE id=? AND user_id=?",
                (pinned, now() if pinned else 0, conversation_id, user_id),
            )
            row = conn.execute(
                """
                SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision,
                       m.supports_native_web_search
                FROM conversations c
                JOIN models m ON m.id = c.model_id
                WHERE c.id=? AND c.user_id=?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return self.json({"ok": True, "conversation": conversation_row(row)})

    def handle_conversation_stats(self):
        conversation_id = self.conversation_id_from_path()
        user_id = self.current_user()["id"]
        with db() as conn:
            row = conn.execute(
                """
                SELECT c.id, c.updated_at, m.name AS model_name, m.model AS model,
                       COUNT(msg.id) AS message_count,
                       COALESCE(SUM(CASE WHEN msg.role='user' THEN 1 ELSE 0 END), 0) AS turn_count,
                       COALESCE(SUM(
                         CASE
                           WHEN msg.total_tokens > 0 THEN msg.total_tokens
                           ELSE COALESCE(msg.prompt_tokens, 0) + COALESCE(msg.completion_tokens, 0)
                         END
                       ), 0) AS total_tokens
                FROM conversations c
                JOIN models m ON m.id = c.model_id
                LEFT JOIN messages msg ON msg.conversation_id=c.id AND msg.user_id=c.user_id AND msg.role!='system'
                WHERE c.id=? AND c.user_id=? AND c.archived=0
                GROUP BY c.id
                """,
                (conversation_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
            web_search_count = conn.execute(
                """
                SELECT COUNT(DISTINCT s.message_id) AS n
                FROM message_sources s
                JOIN messages msg ON msg.id=s.message_id
                WHERE msg.conversation_id=? AND msg.user_id=?
                """,
                (conversation_id, user_id),
            ).fetchone()["n"]
            attachment_count = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM chat_message_images
                WHERE user_id=? AND session_id=? AND message_id>0
                """,
                (user_id, conversation_id),
            ).fetchone()["n"]
            media_task_count = conn.execute(
                """
                SELECT COUNT(*) AS n
                FROM media_analysis_tasks
                WHERE user_id=? AND conversation_id=?
                """,
                (user_id, conversation_id),
            ).fetchone()["n"]
        return self.json(
            {
                "stats": {
                    "total_tokens": int(row["total_tokens"] or 0),
                    "message_count": int(row["message_count"] or 0),
                    "turn_count": int(row["turn_count"] or 0),
                    "model_name": row["model_name"],
                    "model_code": row["model"],
                    "web_search_count": int(web_search_count or 0),
                    "attachment_count": int(attachment_count or 0),
                    "media_task_count": int(media_task_count or 0),
                    "updated_at": row["updated_at"],
                }
            }
        )

    def handle_conversation_item(self):
        conversation_id = self.conversation_id_from_path()
        user_id = self.current_user()["id"]
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id=? AND user_id=? AND archived=0",
                (conversation_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")

            if self.command == "DELETE":
                conn.execute(
                    "UPDATE conversations SET archived=1, updated_at=? WHERE id=? AND user_id=?",
                    (now(), conversation_id, user_id),
                )
                return self.json({"ok": True})

            try:
                data = self.read_body()
            except Exception:
                return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
            title = str(data.get("title") or row["title"]).strip()[:80] or row["title"]
            model_id = str(data.get("model_id") or row["model_id"]).strip()
            if model_id != row["model_id"]:
                model = conn.execute(
                    "SELECT id FROM models WHERE id=? AND enabled=1", (model_id,)
                ).fetchone()
                if not model:
                    return self.error(HTTPStatus.BAD_REQUEST, "model not found")
            conn.execute(
                "UPDATE conversations SET title=?, model_id=?, updated_at=? WHERE id=? AND user_id=?",
                (title, model_id, now(), conversation_id, user_id),
            )
            updated = conn.execute(
                """
                SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision,
                       m.supports_native_web_search
                FROM conversations c JOIN models m ON m.id=c.model_id
                WHERE c.id=? AND c.user_id=?
                """,
                (conversation_id, user_id),
            ).fetchone()
        return self.json({"ok": True, "conversation": conversation_row(updated)})

    def handle_messages(self):
        conversation_id = self.conversation_id_from_path()
        user_id = self.current_user()["id"]
        with db() as conn:
            row = conn.execute(
                "SELECT id FROM conversations WHERE id=? AND user_id=? AND archived=0",
                (conversation_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
            messages = conn.execute(
                """
                SELECT id, role, content, reasoning_content,
                       prompt_tokens, completion_tokens, total_tokens,
                       estimated_cost,
                       created_at
                FROM messages
                WHERE conversation_id=? AND user_id=?
                  AND role!='system'
                ORDER BY id ASC
                """,
                (conversation_id, user_id),
            ).fetchall()
            sources = conn.execute(
                """
                SELECT message_id, title, url, snippet, position
                FROM message_sources
                WHERE message_id IN (
                  SELECT id FROM messages WHERE conversation_id=? AND user_id=?
                  AND role!='system'
                )
                ORDER BY message_id ASC, position ASC
                """,
                (conversation_id, user_id),
            ).fetchall()
            favorites = conn.execute(
                """
                SELECT id, message_id
                FROM favorite_messages
                WHERE message_id IN (
                  SELECT id FROM messages WHERE conversation_id=? AND user_id=?
                  AND role!='system'
                )
                """,
                (conversation_id, user_id),
            ).fetchall()
            images = conn.execute(
                """
                SELECT *
                FROM chat_message_images
                WHERE user_id=? AND session_id=? AND message_id IN (
                  SELECT id FROM messages WHERE conversation_id=? AND user_id=?
                  AND role!='system'
                )
                ORDER BY created_at ASC, id ASC
                """,
                (user_id, conversation_id, conversation_id, user_id),
            ).fetchall()
        sources_by_message = {}
        for source in sources:
            sources_by_message.setdefault(source["message_id"], []).append(
                {
                    "title": source["title"],
                    "url": source["url"],
                    "snippet": source["snippet"],
                    "position": source["position"],
                }
            )
        favorite_by_message = {row["message_id"]: row["id"] for row in favorites}
        images_by_message = {}
        for image in images:
            images_by_message.setdefault(image["message_id"], []).append(chat_image_public(image))
        return self.json(
            {
                "messages": [
                    {
                        "id": row["id"],
                        "role": row["role"],
                        "content": row["content"],
                        "reasoning_content": row["reasoning_content"],
                        "created_at": row["created_at"],
                        "usage": message_token_usage(row),
                        "sources": sources_by_message.get(row["id"], []),
                        "favorite_id": favorite_by_message.get(row["id"]),
                        "images": images_by_message.get(row["id"], []),
                    }
                    for row in messages
                ]
            }
        )

    def handle_send_message(self):
        conversation_id = self.conversation_id_from_path()
        user_id = self.current_user()["id"]
        try:
            data = self.read_body(limit=2 * 1024 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        content = str(data.get("content") or "").strip()
        raw_image_ids = data.get("image_ids") or []
        if not isinstance(raw_image_ids, list):
            raw_image_ids = []
        image_ids = []
        for item in raw_image_ids:
            value = str(item or "").strip()
            if value and value not in image_ids:
                image_ids.append(value)
        if len(image_ids) > CHAT_IMAGE_MAX_COUNT:
            return self.error(HTTPStatus.BAD_REQUEST, "单次最多上传 5 张图片")
        requested_web_search = bool(data.get("web_search"))
        if not content and not image_ids:
            return self.error(HTTPStatus.BAD_REQUEST, "content required")

        search_results = []
        search_config = web_search_config(self.server.secrets)
        use_web_search = should_use_web_search(content, requested_web_search, search_config)
        use_profile = data.get("use_profile", True) is not False
        profile_rows = []
        with db() as conn:
            convo = conn.execute(
                """
                SELECT c.*, m.name AS model_name, m.base_url, m.api_key, m.model, m.system_prompt,
                       m.supports_vision, m.supports_native_web_search, m.enabled,
                       m.input_price_per_million,
                       m.output_price_per_million, m.cost_enabled
                FROM conversations c JOIN models m ON m.id=c.model_id
                WHERE c.id=? AND c.user_id=? AND c.archived=0
                """,
                (conversation_id, user_id),
            ).fetchone()
            if not convo:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
            if not convo["enabled"]:
                return self.error(HTTPStatus.BAD_REQUEST, "model disabled")
            if not convo["api_key"].strip():
                return self.error(HTTPStatus.BAD_REQUEST, "model api key is not configured")
            image_rows = []
            if image_ids:
                if not convo["supports_vision"]:
                    return self.error(HTTPStatus.BAD_REQUEST, "当前模型不支持图片理解，请切换支持图片的模型。")
                if not chat_image_oss_config(self.server.secrets)["configured"]:
                    return self.error(HTTPStatus.BAD_REQUEST, "图片 OSS 还没有配置好")
                placeholders = ",".join("?" for _ in image_ids)
                rows = conn.execute(
                    f"""
                    SELECT *
                    FROM chat_message_images
                    WHERE id IN ({placeholders}) AND user_id=?
                      AND message_id=0
                      AND (session_id='' OR session_id=?)
                    """,
                    (*image_ids, user_id, conversation_id),
                ).fetchall()
                row_by_id = {row["id"]: row for row in rows}
                image_rows = [row_by_id.get(image_id) for image_id in image_ids]
                if any(row is None for row in image_rows):
                    return self.error(HTTPStatus.BAD_REQUEST, "图片附件不存在或已被使用")

            use_native_search = bool(
                use_web_search and convo["supports_native_web_search"]
            )
            if use_web_search and not use_native_search:
                if not search_config["enabled"] or not search_config["api_key"]:
                    return self.error(HTTPStatus.BAD_REQUEST, "web search is not configured")
                try:
                    search_results = perform_web_search(content, search_config)
                except urllib.error.HTTPError as exc:
                    detail = exc.read(65536).decode(errors="replace")
                    return self.error(
                        HTTPStatus.BAD_GATEWAY,
                        f"search upstream status {exc.code}",
                        detail,
                    )
                except Exception as exc:
                    return self.error(
                        HTTPStatus.BAD_GATEWAY, "web search request failed", str(exc)
                    )
                if not search_results:
                    return self.error(HTTPStatus.BAD_GATEWAY, "web search returned no results")

            ts = now()
            user_message_content = content or "请分析这些图片。"
            cursor = conn.execute(
                "INSERT INTO messages(user_id, conversation_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
                (user_id, conversation_id, user_message_content, ts),
            )
            user_message_id = cursor.lastrowid
            if image_rows:
                conn.executemany(
                    "UPDATE chat_message_images SET session_id=?, message_id=? WHERE id=? AND user_id=?",
                    [(conversation_id, user_message_id, row["id"], user_id) for row in image_rows],
                )
            if convo["title"] == "新对话":
                title = visible_user_question(user_message_content).replace("\n", " ")[:28] or "图片理解"
                conn.execute(
                    "UPDATE conversations SET title=?, updated_at=? WHERE id=? AND user_id=?",
                    (title, ts, conversation_id, user_id),
                )
            else:
                conn.execute(
                    "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
                    (ts, conversation_id, user_id),
                )
            history = conn.execute(
                """
                SELECT id, role, content
                FROM messages
                WHERE conversation_id=? AND user_id=?
                ORDER BY id ASC
                LIMIT 80
                """,
                (conversation_id, user_id),
            ).fetchall()
            if use_profile:
                profile_rows = conn.execute(
                    """
                    SELECT *
                    FROM user_profiles
                    WHERE user_id=? AND enabled=1
                    ORDER BY sort_order ASC, updated_at DESC
                    LIMIT 80
                    """,
                    (user_id,),
                ).fetchall()
            history_images = conn.execute(
                """
                SELECT *
                FROM chat_message_images
                WHERE user_id=? AND session_id=? AND message_id IN (
                  SELECT id FROM messages WHERE conversation_id=? AND user_id=?
                )
                ORDER BY created_at ASC, id ASC
                """,
                (user_id, conversation_id, conversation_id, user_id),
            ).fetchall()

        images_by_history_message = {}
        for image in history_images:
            images_by_history_message.setdefault(image["message_id"], []).append(image)
        chat_image_config = chat_image_oss_config(self.server.secrets)

        def upstream_message_from_history(row):
            images = images_by_history_message.get(row["id"], [])
            if row["role"] == "user" and images and convo["supports_vision"]:
                if not chat_image_config["configured"]:
                    raise ValueError("图片 OSS 还没有配置好")
                parts = []
                text_content = str(row["content"] or "").strip()
                if text_content:
                    parts.append({"type": "text", "text": text_content})
                for image in images[:CHAT_IMAGE_MAX_COUNT]:
                    signed_url, _ = oss_signed_get_url(chat_image_config, image["oss_key"], 6 * 60 * 60)
                    parts.append({"type": "image_url", "image_url": {"url": signed_url}})
                return {"role": row["role"], "content": parts or row["content"]}
            if row["role"] == "user" and images:
                names = "、".join(image["filename"] for image in images)
                return {"role": row["role"], "content": (row["content"] or "") + f"\n\n[图片附件：{names}]"}
            return {"role": row["role"], "content": row["content"]}

        def make_upstream_messages(results):
            runtime_context = build_runtime_context(bool(results))
            if use_native_search:
                runtime_context += (
                    "\n本次请求已启用百炼 web_search 工具。必须先调用该工具检索最新资料，"
                    "再依据检索结果回答；不要跳过搜索，也不要假装已经搜索。"
                )
            upstream_messages = [
                {"role": "system", "content": runtime_context}
            ]
            if convo["system_prompt"].strip():
                upstream_messages.append(
                    {"role": "system", "content": convo["system_prompt"].strip()}
                )
            profile_context = build_user_profile_context(profile_rows) if use_profile else ""
            if profile_context:
                upstream_messages.append(
                    {"role": "system", "content": profile_context}
                )
            if results:
                upstream_messages.append(
                    {"role": "system", "content": build_search_context(results)}
                )
            upstream_messages.extend(upstream_message_from_history(row) for row in history)
            return upstream_messages

        def make_payload(results, include_usage=True):
            payload = {
                "model": convo["model"],
                "messages": make_upstream_messages(results),
                "stream": True,
            }
            if include_usage:
                payload["stream_options"] = {"include_usage": True}
            return payload

        def make_native_search_payload():
            return {
                "model": convo["model"],
                "input": responses_input_from_messages(make_upstream_messages([])),
                "tools": [{"type": "web_search"}],
                "stream": True,
            }

        def open_upstream(payload, native_search=False):
            endpoint = "/responses" if native_search else "/chat/completions"
            request = urllib.request.Request(
                convo["base_url"].rstrip("/") + endpoint,
                data=json.dumps(payload).encode(),
                headers={
                    "Authorization": "Bearer " + convo["api_key"].strip(),
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                    "User-Agent": "ai-platform/2.0",
                },
                method="POST",
            )
            return urllib.request.urlopen(request, timeout=120)

        def open_upstream_with_usage_fallback(results):
            payload = make_payload(results, include_usage=True)
            try:
                return open_upstream(payload)
            except urllib.error.HTTPError as exc:
                detail = exc.read(65536).decode(errors="replace")
                if exc.code == 400 and usage_option_rejected(detail):
                    payload = make_payload(results, include_usage=False)
                    return open_upstream(payload)
                raise urllib.error.HTTPError(
                    exc.url, exc.code, exc.reason, exc.headers, io.BytesIO(detail.encode())
                )

        payload = make_native_search_payload() if use_native_search else make_payload(search_results)
        search_fallback_notice = ""

        def upstream_error_message(code, detail):
            if code == 403 and (
                "free quota has been exhausted" in detail.lower()
                or "use free tier only" in detail.lower()
            ):
                return "百炼免费额度已用完，请在对应阿里云账号完成付费配置或关闭仅使用免费额度。"
            if image_ids and (
                "Unexpected item type in content" in detail
                or "support image input" in detail
                or "image input" in detail
            ):
                return "当前模型接口暂时不接受 image_url 图片消息，请换用支持图片理解的模型。"
            if "data_inspection_failed" in detail:
                return "upstream content rejected"
            return f"upstream status {code}"

        try:
            response = (
                open_upstream(payload, native_search=True)
                if use_native_search
                else open_upstream_with_usage_fallback(search_results)
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read(65536).decode(errors="replace")
            if not use_native_search and search_results and exc.code == 400 and "data_inspection_failed" in detail:
                search_results = []
                payload = make_payload(search_results)
                search_fallback_notice = "（联网资料被上游安全策略拦截，本次先按普通模式回答。）\n\n"
                try:
                    response = open_upstream_with_usage_fallback(search_results)
                except urllib.error.HTTPError as retry_exc:
                    retry_detail = retry_exc.read(65536).decode(errors="replace")
                    message = upstream_error_message(retry_exc.code, retry_detail)
                    return self.error(HTTPStatus.BAD_GATEWAY, message, retry_detail)
                except Exception as retry_exc:
                    return self.error(
                        HTTPStatus.BAD_GATEWAY, "upstream request failed", str(retry_exc)
                    )
            else:
                message = upstream_error_message(exc.code, detail)
                return self.error(HTTPStatus.BAD_GATEWAY, message, detail)
        except Exception as exc:
            return self.error(HTTPStatus.BAD_GATEWAY, "upstream request failed", str(exc))

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        if search_results:
            search_event = {
                "type": "search_status",
                "status": "done",
                "count": len(search_results),
                "sources": public_sources(search_results),
            }
            try:
                self.wfile.write(
                    ("data: " + json.dumps(search_event, ensure_ascii=False) + "\n\n").encode()
                )
                self.wfile.flush()
            except Exception:
                pass

        assistant_parts = []
        reasoning_parts = []
        usage_data = None

        def emit_client_event(event):
            try:
                self.wfile.write(
                    ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()
                )
                self.wfile.flush()
                return True
            except Exception:
                return False

        if search_fallback_notice:
            notice_event = {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": search_fallback_notice},
                        "finish_reason": None,
                    }
                ]
            }
            try:
                self.wfile.write(
                    ("data: " + json.dumps(notice_event, ensure_ascii=False) + "\n\n").encode()
                )
                self.wfile.flush()
                assistant_parts.append(search_fallback_notice)
            except Exception:
                pass
        buffer = ""
        try:
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                if not use_native_search:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                buffer += chunk.decode(errors="ignore")
                lines = buffer.splitlines(keepends=True)
                if lines and not lines[-1].endswith(("\n", "\r")):
                    buffer = lines.pop()
                else:
                    buffer = ""
                for line in lines:
                    text = line.strip()
                    if not text.startswith("data:"):
                        continue
                    data_text = text[5:].strip()
                    if not data_text or data_text == "[DONE]":
                        continue
                    try:
                        event = json.loads(data_text)
                    except json.JSONDecodeError:
                        continue
                    if use_native_search:
                        event_type = str(event.get("type") or "")
                        if event_type == "response.output_text.delta":
                            piece = str(event.get("delta") or "")
                            if piece:
                                assistant_parts.append(piece)
                                emit_client_event(
                                    {
                                        "choices": [
                                            {
                                                "index": 0,
                                                "delta": {"content": piece},
                                                "finish_reason": None,
                                            }
                                        ]
                                    }
                                )
                        elif event_type in (
                            "response.reasoning_summary_text.delta",
                            "response.reasoning_text.delta",
                        ):
                            reasoning_piece = str(event.get("delta") or "")
                            if reasoning_piece:
                                reasoning_parts.append(reasoning_piece)
                                emit_client_event(
                                    {
                                        "choices": [
                                            {
                                                "index": 0,
                                                "delta": {
                                                    "reasoning_content": reasoning_piece
                                                },
                                                "finish_reason": None,
                                            }
                                        ]
                                    }
                                )
                        elif event_type == "response.output_item.done":
                            native_results = native_search_results_from_item(
                                event.get("item"), search_config["result_count"]
                            )
                            known_urls = {item["url"] for item in search_results}
                            for item in native_results:
                                if item["url"] not in known_urls:
                                    search_results.append(item)
                                    known_urls.add(item["url"])
                                if len(search_results) >= search_config["result_count"]:
                                    break
                            if search_results:
                                emit_client_event(
                                    {
                                        "type": "search_status",
                                        "status": "done",
                                        "count": len(search_results),
                                        "sources": public_sources(search_results),
                                    }
                                )
                        elif event_type == "response.completed":
                            completed = event.get("response") or {}
                            if isinstance(completed.get("usage"), dict):
                                usage_data = completed.get("usage")
                        continue
                    if isinstance(event.get("usage"), dict):
                        usage_data = event.get("usage")
                    choice = (event.get("choices") or [{}])[0]
                    if isinstance(choice.get("usage"), dict):
                        usage_data = choice.get("usage")
                    delta = choice.get("delta") or {}
                    message = choice.get("message") or {}
                    piece = delta.get("content") or message.get("content") or ""
                    reasoning_piece = (
                        delta.get("reasoning_content")
                        or message.get("reasoning_content")
                        or delta.get("reasoning")
                        or message.get("reasoning")
                        or delta.get("thinking")
                        or message.get("thinking")
                        or ""
                    )
                    if reasoning_piece:
                        reasoning_parts.append(str(reasoning_piece))
                    if piece:
                        assistant_parts.append(piece)
        finally:
            response.close()

        sources_markdown = format_sources_markdown(search_results)
        if sources_markdown:
            source_event = {
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": sources_markdown},
                        "finish_reason": None,
                    }
                ]
            }
            try:
                self.wfile.write(
                    ("data: " + json.dumps(source_event, ensure_ascii=False) + "\n\n").encode()
                )
                self.wfile.flush()
            except Exception:
                pass
            assistant_parts.append(sources_markdown)

        assistant_text = "".join(assistant_parts).strip()
        reasoning_text = "".join(reasoning_parts).strip()
        assistant_text, think_reasoning = split_think_blocks(assistant_text)
        if think_reasoning:
            reasoning_text = (reasoning_text + "\n\n" + think_reasoning).strip()
        prompt_tokens, completion_tokens, total_tokens = parse_usage_tokens(usage_data)
        message_created_at = now()
        input_price_snapshot = parse_price(convo["input_price_per_million"])
        output_price_snapshot = parse_price(convo["output_price_per_million"])
        estimated_cost = estimate_request_cost(
            prompt_tokens,
            completion_tokens,
            input_price_snapshot,
            output_price_snapshot,
            bool(convo["cost_enabled"]),
        )
        if assistant_text:
            with db() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO messages(
                      user_id, conversation_id, role, content, reasoning_content,
                      prompt_tokens, completion_tokens, total_tokens,
                      estimated_cost, cost_input_price, cost_output_price, cost_model_id, actual_model,
                      created_at
                    )
                    VALUES (?, ?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        conversation_id,
                        assistant_text,
                        reasoning_text,
                        prompt_tokens,
                        completion_tokens,
                        total_tokens,
                        estimated_cost,
                        input_price_snapshot if convo["cost_enabled"] else 0,
                        output_price_snapshot if convo["cost_enabled"] else 0,
                        convo["model_id"] if convo["cost_enabled"] else "",
                        convo["model"],
                        message_created_at,
                    ),
                )
                message_id = cursor.lastrowid
                for index, item in enumerate(search_results, 1):
                    conn.execute(
                        """
                        INSERT INTO message_sources(message_id, title, url, snippet, position, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            message_id,
                            item["title"],
                            item["url"],
                            item["snippet"],
                            index,
                            now(),
                        ),
                    )
                conn.execute(
                    "UPDATE conversations SET updated_at=? WHERE id=? AND user_id=?",
                    (now(), conversation_id, user_id),
                )
                add_daily_usage(
                    conn,
                    user_id,
                    message_created_at,
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    estimated_cost,
                )
            saved_event = {
                "type": "message_saved",
                "message_id": message_id,
                "conversation_id": conversation_id,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "estimated_cost": estimated_cost,
                },
            }
            try:
                self.wfile.write(
                    ("data: " + json.dumps(saved_event, ensure_ascii=False) + "\n\n").encode()
                )
                self.wfile.flush()
            except Exception:
                pass
