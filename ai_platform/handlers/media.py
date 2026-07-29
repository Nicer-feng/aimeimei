from .shared import *


class MediaHandlersMixin:
    def chat_image_id_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) >= 3:
            return parts[2]
        return ""

    def handle_chat_image_upload_policy(self):
        user = self.current_user()
        config = chat_image_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "图片 OSS 还没有配置好")
        return self.json({"policy": chat_image_upload_policy(config, user["id"])})

    def handle_chat_images(self):
        user = self.current_user()
        user_id = user["id"]
        config = chat_image_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "图片 OSS 还没有配置好")
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        filename = str(data.get("filename") or "").strip()[:180]
        mime_type = str(data.get("mime_type") or "").strip().lower()[:120]
        oss_key = str(data.get("oss_key") or "").strip()
        try:
            file_size = max(0, int(data.get("file_size") or 0))
        except (TypeError, ValueError):
            file_size = 0

        expected_prefix = chat_image_prefix(config, user_id)
        suffix = Path(filename or oss_key).suffix.lower()
        if not filename or not oss_key:
            return self.error(HTTPStatus.BAD_REQUEST, "请先上传图片")
        if suffix not in CHAT_IMAGE_ALLOWED_EXTENSIONS:
            return self.error(HTTPStatus.BAD_REQUEST, "暂不支持这个图片格式")
        if mime_type and mime_type not in CHAT_IMAGE_ALLOWED_MIME_TYPES:
            return self.error(HTTPStatus.BAD_REQUEST, "暂不支持这个图片格式")
        if file_size <= 0 or file_size > config["max_size"]:
            return self.error(HTTPStatus.BAD_REQUEST, "图片大小超出限制")
        if oss_key.startswith("/") or ".." in oss_key.split("/") or not oss_key.startswith(expected_prefix):
            return self.error(HTTPStatus.BAD_REQUEST, "图片路径不合法")

        ts = now()
        oss_url = cat_oss_url(config, oss_key)
        image_id = b64_token(12)
        with db() as conn:
            existing = conn.execute(
                "SELECT * FROM chat_message_images WHERE oss_key=? AND user_id=?",
                (oss_key, user_id),
            ).fetchone()
            if existing:
                return self.json({"image": chat_image_public(existing)})
            conn.execute(
                """
                INSERT INTO chat_message_images
                (id, user_id, session_id, message_id, filename, mime_type, file_size, oss_key, oss_url, created_at)
                VALUES (?, ?, '', 0, ?, ?, ?, ?, ?, ?)
                """,
                (image_id, user_id, filename, mime_type, file_size, oss_key, oss_url, ts),
            )
            row = conn.execute(
                "SELECT * FROM chat_message_images WHERE id=? AND user_id=?",
                (image_id, user_id),
            ).fetchone()
        return self.json({"image": chat_image_public(row)}, HTTPStatus.CREATED)

    def handle_chat_image_view(self):
        user_id = self.current_user()["id"]
        image_id = self.chat_image_id_from_path()
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM chat_message_images WHERE id=? AND user_id=?",
                (image_id, user_id),
            ).fetchone()
        if not row:
            return self.error(HTTPStatus.NOT_FOUND, "image not found")
        config = chat_image_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "图片 OSS 还没有配置好")
        signed_url, _ = oss_signed_get_url(config, row["oss_key"], 900)
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", signed_url)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def media_task_id_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) >= 4:
            return parts[3]
        return ""

    def handle_media_upload_policy(self):
        user = self.current_user()
        config = media_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "音视频 OSS 还没有配置好")
        return self.json({"policy": media_upload_policy(config, user["id"])})

    def handle_media_tasks(self):
        user = self.current_user()
        user_id = user["id"]
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM media_analysis_tasks
                    WHERE user_id=?
                    ORDER BY updated_at DESC
                    LIMIT 100
                    """,
                    (user_id,),
                ).fetchall()
            return self.json({"tasks": [media_task_public(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        filename = str(data.get("filename") or "").strip()[:180]
        mime_type = str(data.get("mime_type") or "").strip()[:120]
        oss_key = str(data.get("oss_key") or "").strip()
        source_language = str(data.get("source_language") or "cn").strip()[:20] or "cn"
        try:
            file_size = max(0, int(data.get("file_size") or 0))
        except (TypeError, ValueError):
            file_size = 0

        config = media_oss_config(self.server.secrets)
        tingwu = tingwu_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "音视频 OSS 还没有配置好")
        if not tingwu_configured(tingwu):
            return self.error(HTTPStatus.BAD_REQUEST, "通义听悟还没有配置好")
        expected_prefix = f"{config['directory'].strip('/')}/{user_id}/"
        suffix = Path(filename or oss_key).suffix.lower()
        if not filename or not oss_key:
            return self.error(HTTPStatus.BAD_REQUEST, "请先上传音视频文件")
        if suffix not in MEDIA_ALLOWED_EXTENSIONS:
            return self.error(HTTPStatus.BAD_REQUEST, "暂不支持这个文件格式")
        if file_size <= 0 or file_size > config["max_size"]:
            return self.error(HTTPStatus.BAD_REQUEST, "文件大小超出限制")
        if oss_key.startswith("/") or ".." in oss_key.split("/") or not oss_key.startswith(expected_prefix):
            return self.error(HTTPStatus.BAD_REQUEST, "文件路径不合法")

        task_row_id = b64_token(12)
        task_key = "aimeimei-" + task_row_id
        signed_url, expires_at = oss_signed_get_url(config, oss_key, 6 * 60 * 60)
        ts = now()
        status = "submitted"
        task_id = ""
        error_message = ""
        raw_result = ""
        try:
            response = tingwu_create_task(tingwu, signed_url, task_key, source_language)
            raw_result = json.dumps(response, ensure_ascii=False)
            task_id = extract_tingwu_task_id(response)
            if not task_id:
                status = "failed"
                error_message = "听悟没有返回任务 ID"
        except urllib.error.HTTPError as exc:
            status = "failed"
            detail = exc.read(4096).decode(errors="replace")
            error_message = f"听悟创建任务失败：HTTP {exc.code}"
            raw_result = json.dumps({"error": error_message, "detail": detail[:1200]}, ensure_ascii=False)
        except Exception as exc:
            status = "failed"
            error_message = "听悟创建任务失败"
            raw_result = json.dumps({"error": error_message, "detail": str(exc)[:1200]}, ensure_ascii=False)

        with db() as conn:
            conn.execute(
                """
                INSERT INTO media_analysis_tasks
                (id, user_id, filename, mime_type, file_size, oss_key, file_url, file_url_expires_at,
                 task_id, task_key, source_language, status, raw_result_json, error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_row_id,
                    user_id,
                    filename,
                    mime_type,
                    file_size,
                    oss_key,
                    signed_url,
                    expires_at,
                    task_id,
                    task_key,
                    source_language,
                    status,
                    raw_result,
                    error_message,
                    ts,
                    ts,
                ),
            )
            row = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_row_id, user_id),
            ).fetchone()
        return self.json({"task": media_task_public(row)}, HTTPStatus.CREATED)

    def refresh_media_task(self, conn, row):
        if not row or not row["task_id"]:
            return row
        if row["status"] in ("completed", "failed"):
            return row
        config = tingwu_config(self.server.secrets)
        if not tingwu_configured(config):
            conn.execute(
                "UPDATE media_analysis_tasks SET status='failed', error_message=?, updated_at=? WHERE id=?",
                ("通义听悟还没有配置好", now(), row["id"]),
            )
            return conn.execute("SELECT * FROM media_analysis_tasks WHERE id=?", (row["id"],)).fetchone()

        try:
            response = tingwu_get_task_info(config, row["task_id"])
            data = tingwu_data(response)
            task_status = str(data.get("TaskStatus") or data.get("Status") or "").upper()
            result = data.get("Result") or {}
            if isinstance(result, str):
                try:
                    result = json.loads(result)
                except json.JSONDecodeError:
                    result = {}
            status = "processing"
            error_message = ""
            result_payloads = {}
            parsed = {}
            if task_status == "COMPLETED":
                status = "completed"
                if isinstance(result, dict):
                    for name in ("Transcription", "AutoChapters", "MeetingAssistance", "Summarization", "TextPolish"):
                        url = result_url(result.get(name))
                        if not url:
                            continue
                        try:
                            result_payloads[name] = fetch_result_json(url)
                        except Exception as exc:
                            result_payloads[name] = {"error": "结果文件读取失败", "detail": str(exc)[:500]}
                parsed = parse_tingwu_results(result_payloads)
            elif task_status in ("FAILED", "INVALID"):
                status = "failed"
                error_message = str(data.get("ErrorMessage") or data.get("Message") or "听悟任务失败")[:1000]
            elif task_status:
                status = "processing"

            raw = {
                "task_info": response,
                "result_payloads": result_payloads,
            }
            conn.execute(
                """
                UPDATE media_analysis_tasks
                SET status=?, raw_result_json=?, transcript_text=?, summary_text=?,
                    outline_text=?, mindmap_text=?, error_message=?, updated_at=?
                WHERE id=?
                """,
                (
                    status,
                    json.dumps(raw, ensure_ascii=False),
                    parsed.get("transcript_text", row["transcript_text"]),
                    parsed.get("summary_text", row["summary_text"]),
                    parsed.get("outline_text", row["outline_text"]),
                    parsed.get("mindmap_text", row["mindmap_text"]),
                    error_message,
                    now(),
                    row["id"],
                ),
            )
        except urllib.error.HTTPError as exc:
            detail = exc.read(4096).decode(errors="replace")
            conn.execute(
                "UPDATE media_analysis_tasks SET error_message=?, updated_at=? WHERE id=?",
                (f"听悟查询失败：HTTP {exc.code} {detail[:600]}", now(), row["id"]),
            )
        except Exception as exc:
            conn.execute(
                "UPDATE media_analysis_tasks SET error_message=?, updated_at=? WHERE id=?",
                ("听悟查询失败：" + str(exc)[:600], now(), row["id"]),
            )
        return conn.execute("SELECT * FROM media_analysis_tasks WHERE id=?", (row["id"],)).fetchone()

    def handle_media_task_item(self):
        user_id = self.current_user()["id"]
        task_id = self.media_task_id_from_path()
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "media task not found")
            if self.command == "DELETE":
                conn.execute(
                    "DELETE FROM media_analysis_tasks WHERE id=? AND user_id=?",
                    (task_id, user_id),
                )
                return self.json({"ok": True})
            row = self.refresh_media_task(conn, row)
        return self.json({"task": media_task_public(row)})

    def handle_media_task_refresh(self):
        user_id = self.current_user()["id"]
        task_id = self.media_task_id_from_path()
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "media task not found")
            if row["status"] in ("completed", "failed") and row["task_id"]:
                conn.execute(
                    "UPDATE media_analysis_tasks SET status='processing', error_message='', updated_at=? WHERE id=?",
                    (now(), task_id),
                )
                row = conn.execute("SELECT * FROM media_analysis_tasks WHERE id=?", (task_id,)).fetchone()
            row = self.refresh_media_task(conn, row)
        return self.json({"task": media_task_public(row)})

    def media_task_conversation_row(self, conn, conversation_id, user_id):
        if not conversation_id:
            return None
        return conn.execute(
            """
            SELECT c.*, m.name AS model_name, m.model AS model, m.supports_vision,
                   m.supports_native_web_search
            FROM conversations c
            JOIN models m ON m.id = c.model_id
            WHERE c.id=? AND c.user_id=? AND c.archived=0
            """,
            (conversation_id, user_id),
        ).fetchone()

    def upsert_media_context_message(self, conn, row, conversation_id, user_id):
        marker = media_context_marker(row["id"])
        content = marker + "\n" + media_analysis_context(row)
        ts = now()
        existing = conn.execute(
            """
            SELECT id FROM messages
            WHERE conversation_id=? AND user_id=? AND role='system' AND content LIKE ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (conversation_id, user_id, marker + "%"),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE messages SET content=?, created_at=? WHERE id=? AND user_id=?",
                (content, ts, existing["id"], user_id),
            )
        else:
            conn.execute(
                "INSERT INTO messages(user_id, conversation_id, role, content, created_at) VALUES (?, ?, 'system', ?, ?)",
                (user_id, conversation_id, content, ts),
            )

    def create_media_conversation(self, conn, row, user_id, model_id):
        if row["status"] != "completed" or not media_analysis_has_context(row):
            return None, "分析完成后才能发送到 AI 对话"

        conversation = self.media_task_conversation_row(conn, row["conversation_id"], user_id)
        if conversation:
            self.upsert_media_context_message(conn, row, conversation["id"], user_id)
            return conversation, ""

        model = None
        if model_id:
            model = conn.execute(
                "SELECT * FROM models WHERE id=? AND enabled=1",
                (model_id,),
            ).fetchone()
        if not model:
            model = conn.execute(
                "SELECT * FROM models WHERE enabled=1 ORDER BY updated_at DESC, created_at DESC LIMIT 1"
            ).fetchone()
        if not model:
            return None, "还没有可用模型，请先配置模型"

        conversation_id = b64_token(12)
        stem = Path(str(row["filename"] or "音视频分析")).stem or "音视频分析"
        title = ("音视频分析：" + stem)[:80]
        ts = now()
        conn.execute(
            """
            INSERT INTO conversations(id, user_id, title, model_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, user_id, title, model["id"], ts, ts),
        )
        self.upsert_media_context_message(conn, row, conversation_id, user_id)
        intro = (
            f"我已经把《{row['filename'] or '这段音视频'}》的转写、摘要和章节要点放进这个分析会话了。\n\n"
            "你可以直接让我生成短视频文案、口播稿、公众号文章、小红书笔记、朋友圈文案或思维导图，也可以继续追问细节。"
        )
        conn.execute(
            "INSERT INTO messages(user_id, conversation_id, role, content, created_at) VALUES (?, ?, 'assistant', ?, ?)",
            (user_id, conversation_id, intro, ts),
        )
        conn.execute(
            "UPDATE media_analysis_tasks SET conversation_id=?, updated_at=? WHERE id=? AND user_id=?",
            (conversation_id, ts, row["id"], user_id),
        )
        conversation = self.media_task_conversation_row(conn, conversation_id, user_id)
        return conversation, ""

    def handle_media_task_conversation(self):
        user_id = self.current_user()["id"]
        task_id = self.media_task_id_from_path()
        try:
            data = self.read_body()
        except Exception:
            data = {}
        model_id = str(data.get("model_id") or "").strip()
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "media task not found")
            row = self.refresh_media_task(conn, row)
            conversation, error_message = self.create_media_conversation(conn, row, user_id, model_id)
            if not conversation:
                return self.error(HTTPStatus.BAD_REQUEST, error_message or "创建分析会话失败")
            updated = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
        return self.json({
            "conversation": conversation_row(conversation),
            "task": media_task_public(updated),
        })

    def pick_media_ai_model(self, conn, model_id):
        model = None
        if model_id:
            model = conn.execute(
                "SELECT * FROM models WHERE id=? AND enabled=1",
                (model_id,),
            ).fetchone()
        if not model:
            model = conn.execute(
                "SELECT * FROM models WHERE enabled=1 ORDER BY updated_at DESC, created_at DESC LIMIT 1"
            ).fetchone()
        return model

    def call_media_ai_model(self, model, row):
        if not model:
            raise ValueError("还没有可用模型，请先配置模型")
        if not str(model["api_key"] or "").strip():
            raise ValueError("模型 API Key 还没有配置")
        context = media_ai_source_context(row)
        if not context:
            raise ValueError("听悟结果还不完整，暂时无法生成 AI 增强分析")
        system_prompt = (
            "你是 AI槑槑 的音视频内容分析助手。"
            "你会基于通义听悟返回的转写、摘要和章节，生成适合家庭用户直接复制使用的二次加工结果。"
            "必须输出严格 JSON，不要使用 Markdown 代码围栏，不要输出解释文字。"
        )
        user_prompt = f"""
请基于下面音视频分析材料，生成 AI 增强分析。

输出严格 JSON 对象，字段必须包含：
- enhanced_summary：深度总结，分层次说明内容价值
- key_points：核心观点，用 Markdown 列表
- copywriting_text：适合复制的综合文案
- short_video：短视频文案，包含标题、开头钩子、正文、结尾引导
- speech_script：口播稿
- wechat_article：公众号文章
- xiaohongshu_note：小红书笔记
- moments_copy：朋友圈文案，给 3 个版本
- selling_points：提取卖点/爆点
- titles：生成 8 个标题
- mindmap_text：Mermaid mindmap 代码

mindmap_text 要求：
- 只放 Mermaid mindmap 内容
- 使用 mindmap 语法
- 中文节点
- 层级不超过 4 层
- 节点不要太长
- 不要解释

音视频分析材料：
{context}
""".strip()
        payload = {
            "model": model["model"],
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "temperature": 0.4,
        }
        request = urllib.request.Request(
            model["base_url"].rstrip("/") + "/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode(),
            headers={
                "Authorization": "Bearer " + str(model["api_key"]).strip(),
                "Content-Type": "application/json",
                "User-Agent": "ai-platform/2.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            raw = response.read().decode()
        data = json.loads(raw or "{}")
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        content = message.get("content") or choice.get("text") or ""
        parsed = extract_json_object(content)
        if not parsed:
            raise ValueError("AI 增强分析没有返回可解析结果")
        return parsed

    def save_media_ai_outputs(self, conn, row, outputs):
        normalized = {}
        for key in (
            "enhanced_summary", "key_points", "copywriting_text", "short_video",
            "speech_script", "wechat_article", "xiaohongshu_note", "moments_copy",
            "selling_points", "titles",
        ):
            normalized[key] = str(outputs.get(key) or "").strip()
        normalized["mindmap_text"] = normalize_mermaid_mindmap(outputs.get("mindmap_text") or outputs.get("mindmap") or "")
        conn.execute(
            """
            UPDATE media_analysis_tasks
            SET enhanced_summary=?, key_points=?, mindmap_text=?, copywriting_text=?,
                ai_outputs_json=?, updated_at=?
            WHERE id=? AND user_id=?
            """,
            (
                normalized["enhanced_summary"],
                normalized["key_points"],
                normalized["mindmap_text"],
                normalized["copywriting_text"],
                json.dumps(normalized, ensure_ascii=False),
                now(),
                row["id"],
                row["user_id"],
            ),
        )

    def handle_media_task_enhance(self):
        user_id = self.current_user()["id"]
        task_id = self.media_task_id_from_path()
        try:
            data = self.read_body()
        except Exception:
            data = {}
        model_id = str(data.get("model_id") or "").strip()
        force = bool(data.get("force"))
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "media task not found")
            row = self.refresh_media_task(conn, row)
            if row["status"] != "completed" or not (row["summary_text"] or row["outline_text"] or row["transcript_text"]):
                return self.error(HTTPStatus.BAD_REQUEST, "分析完成后才能生成 AI 增强分析")
            if not force and (row["enhanced_summary"] or row["key_points"] or row["ai_outputs_json"]):
                return self.json({"task": media_task_public(row), "cached": True})
            model = self.pick_media_ai_model(conn, model_id)
            try:
                outputs = self.call_media_ai_model(model, row)
            except urllib.error.HTTPError as exc:
                detail = exc.read(4096).decode(errors="replace")
                return self.error(HTTPStatus.BAD_GATEWAY, f"AI 增强分析失败：HTTP {exc.code}", detail[:1000])
            except Exception as exc:
                return self.error(HTTPStatus.BAD_GATEWAY, "AI 增强分析失败", str(exc)[:1000])
            self.save_media_ai_outputs(conn, row, outputs)
            updated = conn.execute(
                "SELECT * FROM media_analysis_tasks WHERE id=? AND user_id=?",
                (task_id, user_id),
            ).fetchone()
            if updated["conversation_id"]:
                conversation = self.media_task_conversation_row(conn, updated["conversation_id"], user_id)
                if conversation:
                    self.upsert_media_context_message(conn, updated, conversation["id"], user_id)
        return self.json({"task": media_task_public(updated), "cached": False})
