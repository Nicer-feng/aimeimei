from .shared import *


class AdminHandlersMixin:
    def handle_models(self):
        with db() as conn:
            rows = conn.execute(
                "SELECT * FROM models WHERE enabled=1 ORDER BY updated_at DESC"
            ).fetchall()
        return self.json({"models": [public_model(row) for row in rows]})

    def handle_search_config(self):
        return self.json({"search": public_web_search_config(self.server.secrets)})

    def handle_global_search(self):
        user_id = self.current_user()["id"]
        params = parse_qs(urlparse(self.path).query)
        query = compact_search_text((params.get("q") or [""])[0])[:80]
        results = []
        with db() as conn:
            if not query:
                rows = conn.execute(
                    """
                    SELECT id, title, updated_at
                    FROM conversations
                    WHERE user_id=? AND archived=0
                    ORDER BY updated_at DESC
                    LIMIT 8
                    """,
                    (user_id,),
                ).fetchall()
                for row in rows:
                    results.append(
                        search_result_row(
                            row["id"],
                            "conversation",
                            row["id"],
                            0,
                            row["title"],
                            "最近对话",
                            "",
                            row["updated_at"],
                            20,
                        )
                    )
                return self.json({"query": query, "results": results})

            like = "%" + like_escape(query) + "%"
            conversation_rows = conn.execute(
                """
                SELECT id, title, updated_at
                FROM conversations
                WHERE user_id=? AND archived=0 AND title LIKE ? ESCAPE '\\'
                ORDER BY updated_at DESC
                LIMIT 20
                """,
                (user_id, like),
            ).fetchall()
            for row in conversation_rows:
                results.append(
                    search_result_row(
                        "conversation:" + row["id"],
                        "conversation",
                        row["id"],
                        0,
                        row["title"],
                        search_snippet(row["title"], query),
                        "",
                        row["updated_at"],
                        100,
                    )
                )

            message_rows = conn.execute(
                """
                SELECT m.id, m.conversation_id, m.role, m.content, m.created_at,
                       c.title AS conversation_title
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.user_id=? AND c.user_id=? AND c.archived=0
                  AND m.role!='system' AND m.content LIKE ? ESCAPE '\\'
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT 50
                """,
                (user_id, user_id, like),
            ).fetchall()
            for row in message_rows:
                score = 86 if row["role"] == "user" else 82
                results.append(
                    search_result_row(
                        "message:" + str(row["id"]),
                        "message",
                        row["conversation_id"],
                        row["id"],
                        row["conversation_title"],
                        search_snippet(row["content"], query),
                        row["role"],
                        row["created_at"],
                        score,
                    )
                )

            favorite_rows = conn.execute(
                """
                SELECT f.id, f.message_id, f.conversation_id, f.conversation_title,
                       f.role, f.content, f.created_at,
                       c.id AS live_conversation_id
                FROM favorite_messages f
                LEFT JOIN conversations c ON c.id = f.conversation_id AND c.user_id=f.user_id AND c.archived=0
                WHERE f.user_id=? AND f.content LIKE ? ESCAPE '\\'
                ORDER BY f.created_at DESC
                LIMIT 30
                """,
                (user_id, like),
            ).fetchall()
            for row in favorite_rows:
                results.append(
                    search_result_row(
                        "favorite:" + row["id"],
                        "favorite",
                        row["live_conversation_id"] or "",
                        row["message_id"] if row["live_conversation_id"] else 0,
                        row["conversation_title"] or "原会话已删除",
                        search_snippet(row["content"], query),
                        row["role"],
                        row["created_at"],
                        72,
                    )
                )

            media_rows = conn.execute(
                """
                SELECT id, filename, conversation_id, summary_text, enhanced_summary,
                       key_points, copywriting_text, updated_at, created_at
                FROM media_analysis_tasks
                WHERE user_id=? AND (
                  filename LIKE ? ESCAPE '\\'
                  OR summary_text LIKE ? ESCAPE '\\'
                  OR enhanced_summary LIKE ? ESCAPE '\\'
                  OR key_points LIKE ? ESCAPE '\\'
                  OR copywriting_text LIKE ? ESCAPE '\\'
                )
                ORDER BY updated_at DESC
                LIMIT 30
                """,
                (user_id, like, like, like, like, like),
            ).fetchall()
            for row in media_rows:
                source_text = "\n".join(
                    str(row[key] or "")
                    for key in ("filename", "enhanced_summary", "key_points", "summary_text", "copywriting_text")
                )
                results.append(
                    search_result_row(
                        "media:" + row["id"],
                        "media",
                        row["conversation_id"],
                        0,
                        row["filename"] or "音视频分析",
                        search_snippet(source_text, query),
                        "",
                        row["updated_at"] or row["created_at"],
                        68,
                    )
                )

        results.sort(key=lambda item: (item["score"], item["created_at"]), reverse=True)
        return self.json({"query": query, "results": results[:60]})

    def handle_admin_search(self):
        if self.command == "GET":
            config = web_search_config(self.server.secrets)
            return self.json(
                {
                    "search": {
                        "provider": config["provider"],
                        "enabled": config["enabled"],
                        "result_count": config["result_count"],
                        "mode": config["mode"],
                        "depth": config["depth"],
                        "has_api_key": bool(config["api_key"]),
                    }
                }
            )

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        provider = str(data.get("provider") or "tavily").strip().lower()
        if provider not in ("tavily", "brave"):
            return self.error(HTTPStatus.BAD_REQUEST, "unsupported search provider")
        mode = str(data.get("mode") or "auto").strip().lower()
        if mode not in ("manual", "auto", "always"):
            return self.error(HTTPStatus.BAD_REQUEST, "unsupported search mode")
        depth = str(data.get("depth") or "advanced").strip().lower()
        if depth not in ("basic", "advanced"):
            return self.error(HTTPStatus.BAD_REQUEST, "unsupported search depth")

        old_config = web_search_config(self.server.secrets)
        api_key = old_config["api_key"]
        if data.get("clear_api_key"):
            api_key = ""
        elif str(data.get("api_key") or "").strip():
            api_key = str(data.get("api_key")).strip()

        self.server.secrets["web_search"] = {
            "provider": provider,
            "api_key": api_key,
            "enabled": bool(data.get("enabled")),
            "result_count": clamp_int(data.get("result_count"), 5, 1, 8),
            "mode": mode,
            "depth": depth,
        }
        write_private(SECRETS_PATH, json.dumps(self.server.secrets, indent=2) + "\n")
        return self.json({"ok": True, "search": public_web_search_config(self.server.secrets)})

    def handle_admin_token_stats(self):
        params = parse_qs(urlparse(self.path).query)
        query = str((params.get("q") or [""])[0] or "").strip().lower()[:80]
        sort = str((params.get("sort") or ["tokens"])[0] or "tokens").strip().lower()
        if sort not in ("tokens", "recent", "created"):
            sort = "tokens"
        model_query = str((params.get("model_q") or [""])[0] or "").strip().lower()[:80]
        model_sort = str((params.get("model_sort") or ["tokens"])[0] or "tokens").strip().lower()
        if model_sort not in ("tokens", "requests", "recent"):
            model_sort = "tokens"

        order_sql = {
            "tokens": "total_tokens DESC, request_count DESC, last_used_at DESC",
            "recent": "last_used_at DESC, total_tokens DESC, request_count DESC",
            "created": "u.created_at DESC",
        }[sort]
        model_order_sql = {
            "tokens": "total_tokens DESC, request_count DESC, last_used_at DESC",
            "requests": "request_count DESC, total_tokens DESC, last_used_at DESC",
            "recent": "last_used_at DESC, total_tokens DESC, request_count DESC",
        }[model_sort]
        where_sql = ""
        args = []
        if query:
            where_sql = "WHERE lower(u.username) LIKE ? ESCAPE '\\' OR lower(u.display_name) LIKE ? ESCAPE '\\'"
            like = "%" + like_escape(query) + "%"
            args.extend([like, like])
        model_where_sql = ""
        model_args = []
        if model_query:
            model_where_sql = """
                WHERE lower(mo.name) LIKE ? ESCAPE '\\'
                   OR lower(mo.model) LIKE ? ESCAPE '\\'
                   OR lower(mo.provider) LIKE ? ESCAPE '\\'
            """
            model_like = "%" + like_escape(model_query) + "%"
            model_args.extend([model_like, model_like, model_like])

        with db() as conn:
            summary = conn.execute(
                """
                SELECT
                  COUNT(DISTINCT u.id) AS total_users,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN 1 ELSE 0 END), 0) AS total_requests,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN COALESCE(m.prompt_tokens, 0) ELSE 0 END), 0) AS prompt_tokens,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN COALESCE(m.completion_tokens, 0) ELSE 0 END), 0) AS completion_tokens,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN
                    CASE WHEN COALESCE(m.total_tokens, 0) > 0
                      THEN COALESCE(m.total_tokens, 0)
                      ELSE COALESCE(m.prompt_tokens, 0) + COALESCE(m.completion_tokens, 0)
                    END ELSE 0 END), 0) AS total_tokens
                FROM users u
                LEFT JOIN messages m ON m.user_id=u.id
                """
            ).fetchone()

            rows = conn.execute(
                f"""
                SELECT
                  u.id,
                  u.username,
                  u.display_name,
                  u.role,
                  u.is_active,
                  u.created_at,
                  COUNT(DISTINCT c.id) AS conversation_count,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN 1 ELSE 0 END), 0) AS request_count,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN COALESCE(m.prompt_tokens, 0) ELSE 0 END), 0) AS prompt_tokens,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN COALESCE(m.completion_tokens, 0) ELSE 0 END), 0) AS completion_tokens,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN
                    CASE WHEN COALESCE(m.total_tokens, 0) > 0
                      THEN COALESCE(m.total_tokens, 0)
                      ELSE COALESCE(m.prompt_tokens, 0) + COALESCE(m.completion_tokens, 0)
                    END ELSE 0 END), 0) AS total_tokens,
                  MAX(CASE WHEN m.role='assistant' THEN m.created_at ELSE NULL END) AS last_used_at
                FROM users u
                LEFT JOIN conversations c ON c.user_id=u.id
                LEFT JOIN messages m ON m.user_id=u.id AND m.conversation_id=c.id
                {where_sql}
                GROUP BY u.id
                ORDER BY {order_sql}
                LIMIT 200
                """,
                args,
            ).fetchall()

            details = {}
            user_ids = [row["id"] for row in rows]
            if user_ids:
                placeholders = ",".join(["?"] * len(user_ids))
                detail_rows = conn.execute(
                    f"""
                    SELECT
                      m.id,
                      m.user_id,
                      m.conversation_id,
                      m.created_at,
                      m.prompt_tokens,
                      m.completion_tokens,
                      CASE WHEN COALESCE(m.total_tokens, 0) > 0
                        THEN COALESCE(m.total_tokens, 0)
                        ELSE COALESCE(m.prompt_tokens, 0) + COALESCE(m.completion_tokens, 0)
                      END AS total_tokens,
                      c.title AS conversation_title,
                      mo.name AS model_name,
                      mo.model AS model_code,
                      EXISTS(SELECT 1 FROM message_sources s WHERE s.message_id=m.id) AS web_search
                    FROM messages m
                    LEFT JOIN conversations c ON c.id=m.conversation_id AND c.user_id=m.user_id
                    LEFT JOIN models mo ON mo.id=c.model_id
                    WHERE m.role='assistant' AND m.user_id IN ({placeholders})
                    ORDER BY m.user_id ASC, m.created_at DESC, m.id DESC
                    """,
                    user_ids,
                ).fetchall()
                for detail in detail_rows:
                    bucket = details.setdefault(detail["user_id"], [])
                    if len(bucket) >= 20:
                        continue
                    bucket.append(
                        {
                            "message_id": detail["id"],
                            "conversation_id": detail["conversation_id"],
                            "conversation_title": detail["conversation_title"] or "未命名对话",
                            "created_at": detail["created_at"],
                            "model_name": detail["model_name"] or "",
                            "model_code": detail["model_code"] or "",
                            "prompt_tokens": int(detail["prompt_tokens"] or 0),
                            "completion_tokens": int(detail["completion_tokens"] or 0),
                            "total_tokens": int(detail["total_tokens"] or 0),
                            "duration_ms": None,
                            "web_search": bool(detail["web_search"]),
                        }
                    )

            model_rows = conn.execute(
                f"""
                SELECT
                  mo.id,
                  mo.name,
                  mo.model,
                  mo.provider,
                  mo.enabled,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN 1 ELSE 0 END), 0) AS request_count,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN COALESCE(m.prompt_tokens, 0) ELSE 0 END), 0) AS prompt_tokens,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN COALESCE(m.completion_tokens, 0) ELSE 0 END), 0) AS completion_tokens,
                  COALESCE(SUM(CASE WHEN m.role='assistant' THEN
                    CASE WHEN COALESCE(m.total_tokens, 0) > 0
                      THEN COALESCE(m.total_tokens, 0)
                      ELSE COALESCE(m.prompt_tokens, 0) + COALESCE(m.completion_tokens, 0)
                    END ELSE 0 END), 0) AS total_tokens,
                  COUNT(DISTINCT CASE WHEN m.role='assistant' THEN c.user_id ELSE NULL END) AS user_count,
                  MAX(CASE WHEN m.role='assistant' THEN m.created_at ELSE NULL END) AS last_used_at
                FROM models mo
                LEFT JOIN conversations c ON c.model_id=mo.id
                LEFT JOIN messages m ON m.conversation_id=c.id AND m.user_id=c.user_id AND m.role='assistant'
                {model_where_sql}
                GROUP BY mo.id
                ORDER BY {model_order_sql}
                LIMIT 200
                """,
                model_args,
            ).fetchall()

            model_details = {}
            model_ids = [row["id"] for row in model_rows]
            if model_ids:
                placeholders = ",".join(["?"] * len(model_ids))
                model_detail_rows = conn.execute(
                    f"""
                    SELECT
                      mo.id AS model_id,
                      m.id AS message_id,
                      m.conversation_id,
                      m.created_at,
                      m.prompt_tokens,
                      m.completion_tokens,
                      CASE WHEN COALESCE(m.total_tokens, 0) > 0
                        THEN COALESCE(m.total_tokens, 0)
                        ELSE COALESCE(m.prompt_tokens, 0) + COALESCE(m.completion_tokens, 0)
                      END AS total_tokens,
                      c.title AS conversation_title,
                      u.username,
                      u.display_name,
                      EXISTS(SELECT 1 FROM message_sources s WHERE s.message_id=m.id) AS web_search
                    FROM messages m
                    JOIN conversations c ON c.id=m.conversation_id AND c.user_id=m.user_id
                    JOIN models mo ON mo.id=c.model_id
                    LEFT JOIN users u ON u.id=m.user_id
                    WHERE m.role='assistant' AND mo.id IN ({placeholders})
                    ORDER BY mo.id ASC, m.created_at DESC, m.id DESC
                    """,
                    model_ids,
                ).fetchall()
                for detail in model_detail_rows:
                    bucket = model_details.setdefault(detail["model_id"], [])
                    if len(bucket) >= 20:
                        continue
                    bucket.append(
                        {
                            "message_id": detail["message_id"],
                            "conversation_id": detail["conversation_id"],
                            "conversation_title": detail["conversation_title"] or "未命名对话",
                            "created_at": detail["created_at"],
                            "username": detail["username"] or "",
                            "display_name": detail["display_name"] or detail["username"] or "",
                            "prompt_tokens": int(detail["prompt_tokens"] or 0),
                            "completion_tokens": int(detail["completion_tokens"] or 0),
                            "total_tokens": int(detail["total_tokens"] or 0),
                            "duration_ms": None,
                            "web_search": bool(detail["web_search"]),
                        }
                    )

        users = []
        for row in rows:
            users.append(
                {
                    "id": row["id"],
                    "username": row["username"],
                    "display_name": row["display_name"],
                    "role": row["role"],
                    "is_active": bool(row["is_active"]),
                    "created_at": row["created_at"],
                    "conversation_count": int(row["conversation_count"] or 0),
                    "request_count": int(row["request_count"] or 0),
                    "prompt_tokens": int(row["prompt_tokens"] or 0),
                    "completion_tokens": int(row["completion_tokens"] or 0),
                    "total_tokens": int(row["total_tokens"] or 0),
                    "last_used_at": row["last_used_at"] or 0,
                    "recent_requests": details.get(row["id"], []),
                }
            )

        models = []
        for row in model_rows:
            models.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "model": row["model"],
                    "provider": row["provider"],
                    "enabled": bool(row["enabled"]),
                    "request_count": int(row["request_count"] or 0),
                    "prompt_tokens": int(row["prompt_tokens"] or 0),
                    "completion_tokens": int(row["completion_tokens"] or 0),
                    "total_tokens": int(row["total_tokens"] or 0),
                    "user_count": int(row["user_count"] or 0),
                    "last_used_at": row["last_used_at"] or 0,
                    "recent_requests": model_details.get(row["id"], []),
                }
            )

        top_request_model = next((item for item in sorted(models, key=lambda value: value["request_count"], reverse=True) if item["request_count"] > 0), None)
        top_token_model = next((item for item in sorted(models, key=lambda value: value["total_tokens"], reverse=True) if item["total_tokens"] > 0), None)

        return self.json(
            {
                "summary": {
                    "total_users": int(summary["total_users"] or 0),
                    "total_requests": int(summary["total_requests"] or 0),
                    "prompt_tokens": int(summary["prompt_tokens"] or 0),
                    "completion_tokens": int(summary["completion_tokens"] or 0),
                    "total_tokens": int(summary["total_tokens"] or 0),
                },
                "model_summary": {
                    "total_models": len(models),
                    "total_requests": int(summary["total_requests"] or 0),
                    "total_tokens": int(summary["total_tokens"] or 0),
                    "top_request_model": top_request_model,
                    "top_token_model": top_token_model,
                },
                "users": users,
                "models": models,
                "query": query,
                "sort": sort,
                "model_query": model_query,
                "model_sort": model_sort,
            }
        )

    def handle_admin_cost_stats(self):
        params = parse_qs(urlparse(self.path).query)
        range_key = str((params.get("range") or ["30d"])[0] or "30d").strip().lower()
        if range_key not in ("7d", "30d", "all"):
            range_key = "30d"
        cutoff = 0
        if range_key == "7d":
            cutoff = now() - 7 * 86400
        elif range_key == "30d":
            cutoff = now() - 30 * 86400
        range_where = "m.role='assistant'"
        range_args = []
        if cutoff:
            range_where += " AND m.created_at>=?"
            range_args.append(cutoff)

        with db() as conn:
            total_summary = conn.execute(
                """
                SELECT
                  COALESCE(SUM(estimated_cost), 0) AS total_cost,
                  COUNT(*) AS request_count
                FROM messages
                WHERE role='assistant'
                """
            ).fetchone()
            today_summary = conn.execute(
                """
                SELECT COALESCE(SUM(estimated_cost), 0) AS cost
                FROM messages
                WHERE role='assistant' AND created_at>=?
                """,
                (local_day_start(),),
            ).fetchone()
            month_summary = conn.execute(
                """
                SELECT COALESCE(SUM(estimated_cost), 0) AS cost
                FROM messages
                WHERE role='assistant' AND created_at>=?
                """,
                (local_month_start(),),
            ).fetchone()
            range_summary = conn.execute(
                f"""
                SELECT
                  COALESCE(SUM(m.estimated_cost), 0) AS cost,
                  COUNT(*) AS request_count,
                  COALESCE(SUM(m.prompt_tokens), 0) AS prompt_tokens,
                  COALESCE(SUM(m.completion_tokens), 0) AS completion_tokens,
                  COALESCE(SUM(CASE WHEN m.total_tokens>0 THEN m.total_tokens ELSE m.prompt_tokens+m.completion_tokens END), 0) AS total_tokens
                FROM messages m
                WHERE {range_where}
                """,
                range_args,
            ).fetchone()
            model_rows = conn.execute(
                f"""
                SELECT
                  COALESCE(NULLIF(m.cost_model_id, ''), c.model_id, '') AS model_id,
                  COALESCE(mo.name, m.actual_model, '未知模型') AS model_name,
                  COALESCE(mo.model, m.actual_model, '') AS model_code,
                  COALESCE(mo.provider, '') AS provider,
                  COUNT(*) AS request_count,
                  COALESCE(SUM(m.prompt_tokens), 0) AS prompt_tokens,
                  COALESCE(SUM(m.completion_tokens), 0) AS completion_tokens,
                  COALESCE(SUM(CASE WHEN m.total_tokens>0 THEN m.total_tokens ELSE m.prompt_tokens+m.completion_tokens END), 0) AS total_tokens,
                  COALESCE(SUM(m.estimated_cost), 0) AS estimated_cost,
                  COUNT(DISTINCT m.user_id) AS user_count,
                  MAX(m.created_at) AS last_used_at
                FROM messages m
                LEFT JOIN conversations c ON c.id=m.conversation_id AND c.user_id=m.user_id
                LEFT JOIN models mo ON mo.id=COALESCE(NULLIF(m.cost_model_id, ''), c.model_id)
                WHERE {range_where}
                GROUP BY model_id, model_name, model_code, provider
                ORDER BY estimated_cost DESC, total_tokens DESC, request_count DESC
                LIMIT 100
                """,
                range_args,
            ).fetchall()
            user_rows = conn.execute(
                f"""
                SELECT
                  u.id,
                  u.username,
                  u.display_name,
                  COUNT(*) AS request_count,
                  COALESCE(SUM(m.prompt_tokens), 0) AS prompt_tokens,
                  COALESCE(SUM(m.completion_tokens), 0) AS completion_tokens,
                  COALESCE(SUM(CASE WHEN m.total_tokens>0 THEN m.total_tokens ELSE m.prompt_tokens+m.completion_tokens END), 0) AS total_tokens,
                  COALESCE(SUM(m.estimated_cost), 0) AS estimated_cost,
                  MAX(m.created_at) AS last_used_at
                FROM messages m
                LEFT JOIN users u ON u.id=m.user_id
                WHERE {range_where}
                GROUP BY u.id
                ORDER BY estimated_cost DESC, total_tokens DESC, request_count DESC
                LIMIT 100
                """,
                range_args,
            ).fetchall()

        models = [
            {
                "model_id": row["model_id"] or "",
                "model_name": row["model_name"] or "未知模型",
                "model_code": row["model_code"] or "",
                "provider": row["provider"] or "",
                "request_count": int(row["request_count"] or 0),
                "prompt_tokens": int(row["prompt_tokens"] or 0),
                "completion_tokens": int(row["completion_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "estimated_cost": float(row["estimated_cost"] or 0),
                "user_count": int(row["user_count"] or 0),
                "last_used_at": row["last_used_at"] or 0,
            }
            for row in model_rows
        ]
        users = [
            {
                "user_id": row["id"] or "",
                "username": row["username"] or "",
                "display_name": row["display_name"] or row["username"] or "未知账号",
                "request_count": int(row["request_count"] or 0),
                "prompt_tokens": int(row["prompt_tokens"] or 0),
                "completion_tokens": int(row["completion_tokens"] or 0),
                "total_tokens": int(row["total_tokens"] or 0),
                "estimated_cost": float(row["estimated_cost"] or 0),
                "last_used_at": row["last_used_at"] or 0,
            }
            for row in user_rows
        ]
        total_requests = int(total_summary["request_count"] or 0)
        total_cost = float(total_summary["total_cost"] or 0)
        return self.json(
            {
                "range": range_key,
                "summary": {
                    "today_cost": float(today_summary["cost"] or 0),
                    "month_cost": float(month_summary["cost"] or 0),
                    "total_cost": total_cost,
                    "average_request_cost": (total_cost / total_requests) if total_requests else 0,
                    "range_cost": float(range_summary["cost"] or 0),
                    "range_requests": int(range_summary["request_count"] or 0),
                    "range_total_tokens": int(range_summary["total_tokens"] or 0),
                    "top_model": models[0] if models else None,
                    "top_user": users[0] if users else None,
                },
                "models": models,
                "users": users,
            }
        )

    def handle_admin_cost_recalculate(self):
        try:
            data = self.read_body()
        except Exception:
            data = {}
        range_key = str(data.get("range") or "30d").strip().lower()
        if range_key not in ("7d", "30d", "all"):
            range_key = "30d"
        cutoff = 0
        if range_key == "7d":
            cutoff = now() - 7 * 86400
        elif range_key == "30d":
            cutoff = now() - 30 * 86400
        where_sql = "m.role='assistant' AND COALESCE(m.estimated_cost, 0)=0"
        args = []
        if cutoff:
            where_sql += " AND m.created_at>=?"
            args.append(cutoff)
        with db() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  m.id,
                  m.prompt_tokens,
                  m.completion_tokens,
                  m.total_tokens,
                  m.created_at,
                  c.model_id,
                  mo.model AS model_code,
                  mo.input_price_per_million,
                  mo.output_price_per_million,
                  mo.cost_enabled
                FROM messages m
                JOIN conversations c ON c.id=m.conversation_id AND c.user_id=m.user_id
                JOIN models mo ON mo.id=c.model_id
                WHERE {where_sql}
                """,
                args,
            ).fetchall()
            updated = 0
            skipped = 0
            total_cost = 0.0
            for row in rows:
                if not row["cost_enabled"]:
                    skipped += 1
                    continue
                prompt_tokens = int(row["prompt_tokens"] or 0)
                completion_tokens = int(row["completion_tokens"] or 0)
                total_tokens = int(row["total_tokens"] or 0)
                if not total_tokens and (prompt_tokens or completion_tokens):
                    total_tokens = prompt_tokens + completion_tokens
                input_price = parse_price(row["input_price_per_million"])
                output_price = parse_price(row["output_price_per_million"])
                cost = estimate_request_cost(prompt_tokens, completion_tokens, input_price, output_price, True)
                if cost <= 0:
                    skipped += 1
                    continue
                conn.execute(
                    """
                    UPDATE messages
                    SET estimated_cost=?, cost_input_price=?, cost_output_price=?,
                        cost_model_id=?, actual_model=?
                    WHERE id=?
                    """,
                    (
                        cost,
                        input_price,
                        output_price,
                        row["model_id"],
                        row["model_code"] or "",
                        row["id"],
                    ),
                )
                updated += 1
                total_cost += cost
            conn.execute("DELETE FROM daily_usage")
            conn.execute(
                """
                INSERT INTO daily_usage
                (user_id, date, request_count, input_tokens, output_tokens, total_tokens, estimated_cost, updated_at)
                SELECT
                  user_id,
                  date(created_at, 'unixepoch', 'localtime') AS usage_date,
                  COUNT(*) AS request_count,
                  COALESCE(SUM(prompt_tokens), 0) AS input_tokens,
                  COALESCE(SUM(completion_tokens), 0) AS output_tokens,
                  COALESCE(SUM(CASE WHEN total_tokens>0 THEN total_tokens ELSE prompt_tokens+completion_tokens END), 0) AS total_tokens,
                  COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                  ?
                FROM messages
                WHERE role='assistant'
                GROUP BY user_id, usage_date
                """,
                (now(),),
            )
        return self.json(
            {
                "ok": True,
                "range": range_key,
                "updated_messages": updated,
                "skipped_messages": skipped,
                "estimated_cost_added": round(total_cost, 8),
            }
        )

    def handle_token_activity(self):
        user = self.current_user()
        user_id = user["id"]
        end_day_start = local_day_start()
        start_day_start = end_day_start - 364 * 86400
        start_date = date_text_from_ts(start_day_start)
        with db() as conn:
            daily_rows = conn.execute(
                """
                SELECT *
                FROM daily_usage
                WHERE user_id=? AND date>=?
                ORDER BY date ASC
                """,
                (user_id, start_date),
            ).fetchall()
            totals = conn.execute(
                """
                SELECT
                  COALESCE(SUM(request_count), 0) AS request_count,
                  COALESCE(SUM(input_tokens), 0) AS input_tokens,
                  COALESCE(SUM(output_tokens), 0) AS output_tokens,
                  COALESCE(SUM(total_tokens), 0) AS total_tokens,
                  COALESCE(SUM(estimated_cost), 0) AS estimated_cost,
                  COUNT(CASE WHEN request_count>0 THEN 1 ELSE NULL END) AS active_days
                FROM daily_usage
                WHERE user_id=?
                """,
                (user_id,),
            ).fetchone()
            conversation_count = conn.execute(
                "SELECT COUNT(*) AS n FROM conversations WHERE user_id=? AND archived=0",
                (user_id,),
            ).fetchone()["n"]
            model_rows = conn.execute(
                """
                SELECT
                  COALESCE(mo.name, msg.actual_model, '未知模型') AS model_name,
                  COALESCE(mo.model, msg.actual_model, '') AS model_code,
                  COUNT(*) AS request_count,
                  COALESCE(SUM(CASE WHEN msg.total_tokens>0 THEN msg.total_tokens ELSE msg.prompt_tokens+msg.completion_tokens END), 0) AS total_tokens,
                  COALESCE(SUM(msg.estimated_cost), 0) AS estimated_cost
                FROM messages msg
                LEFT JOIN conversations c ON c.id=msg.conversation_id AND c.user_id=msg.user_id
                LEFT JOIN models mo ON mo.id=COALESCE(NULLIF(msg.cost_model_id, ''), c.model_id)
                WHERE msg.user_id=? AND msg.role='assistant'
                GROUP BY model_name, model_code
                ORDER BY total_tokens DESC, request_count DESC
                LIMIT 5
                """,
                (user_id,),
            ).fetchall()
            conversation_rows = conn.execute(
                """
                SELECT
                  c.id,
                  c.title,
                  COUNT(msg.id) AS request_count,
                  COALESCE(SUM(CASE WHEN msg.total_tokens>0 THEN msg.total_tokens ELSE msg.prompt_tokens+msg.completion_tokens END), 0) AS total_tokens
                FROM conversations c
                JOIN messages msg ON msg.conversation_id=c.id AND msg.user_id=c.user_id AND msg.role='assistant'
                WHERE c.user_id=?
                GROUP BY c.id
                ORDER BY total_tokens DESC, request_count DESC
                LIMIT 5
                """,
                (user_id,),
            ).fetchall()
            day_model_rows = conn.execute(
                """
                SELECT
                  date(msg.created_at, 'unixepoch', 'localtime') AS usage_date,
                  COALESCE(mo.name, msg.actual_model, '未知模型') AS model_name,
                  COUNT(*) AS request_count,
                  COALESCE(SUM(CASE WHEN msg.total_tokens>0 THEN msg.total_tokens ELSE msg.prompt_tokens+msg.completion_tokens END), 0) AS total_tokens,
                  COALESCE(SUM(msg.estimated_cost), 0) AS estimated_cost
                FROM messages msg
                LEFT JOIN conversations c ON c.id=msg.conversation_id AND c.user_id=msg.user_id
                LEFT JOIN models mo ON mo.id=COALESCE(NULLIF(msg.cost_model_id, ''), c.model_id)
                WHERE msg.user_id=? AND msg.role='assistant' AND msg.created_at>=?
                GROUP BY usage_date, model_name
                ORDER BY usage_date ASC, total_tokens DESC
                """,
                (user_id, start_day_start),
            ).fetchall()

        active_dates = {row["date"] for row in daily_rows if int(row["request_count"] or 0) > 0}
        longest_streak = 0
        current_streak = 0
        streak = 0
        cursor_day = start_day_start
        today_date = today_text()
        while cursor_day <= end_day_start:
            value = date_text_from_ts(cursor_day)
            if value in active_dates:
                streak += 1
                longest_streak = max(longest_streak, streak)
                if value <= today_date:
                    current_streak = streak
            else:
                streak = 0
                if value <= today_date:
                    current_streak = 0
            cursor_day += 86400

        daily_by_date = {row["date"]: row for row in daily_rows}
        days = []
        cursor_day = start_day_start
        while cursor_day <= end_day_start:
            value = date_text_from_ts(cursor_day)
            row = daily_by_date.get(value)
            days.append(
                {
                    "date": value,
                    "request_count": int(row["request_count"] or 0) if row else 0,
                    "input_tokens": int(row["input_tokens"] or 0) if row else 0,
                    "output_tokens": int(row["output_tokens"] or 0) if row else 0,
                    "total_tokens": int(row["total_tokens"] or 0) if row else 0,
                    "estimated_cost": float(row["estimated_cost"] or 0) if row else 0,
                }
            )
            cursor_day += 86400

        day_models = {}
        for row in day_model_rows:
            day_models.setdefault(row["usage_date"], []).append(
                {
                    "model_name": row["model_name"] or "未知模型",
                    "request_count": int(row["request_count"] or 0),
                    "total_tokens": int(row["total_tokens"] or 0),
                    "estimated_cost": float(row["estimated_cost"] or 0),
                }
            )

        total_tokens = int(totals["total_tokens"] or 0)
        active_day_count = int(totals["active_days"] or 0)
        return self.json(
            {
                "summary": {
                    "request_count": int(totals["request_count"] or 0),
                    "input_tokens": int(totals["input_tokens"] or 0),
                    "output_tokens": int(totals["output_tokens"] or 0),
                    "total_tokens": total_tokens,
                    "estimated_cost": float(totals["estimated_cost"] or 0),
                    "conversation_count": int(conversation_count or 0),
                    "active_days": active_day_count,
                    "longest_streak": longest_streak,
                    "current_streak": current_streak,
                    "average_daily_tokens": int(total_tokens / active_day_count) if active_day_count else 0,
                },
                "days": days,
                "day_models": day_models,
                "top_models": [
                    {
                        "model_name": row["model_name"] or "未知模型",
                        "model_code": row["model_code"] or "",
                        "request_count": int(row["request_count"] or 0),
                        "total_tokens": int(row["total_tokens"] or 0),
                        "estimated_cost": float(row["estimated_cost"] or 0),
                    }
                    for row in model_rows
                ],
                "top_conversations": [
                    {
                        "conversation_id": row["id"],
                        "title": row["title"] or "未命名对话",
                        "request_count": int(row["request_count"] or 0),
                        "total_tokens": int(row["total_tokens"] or 0),
                    }
                    for row in conversation_rows
                ],
                "top_agents": [],
                "top_prompts": [],
            }
        )

    def handle_admin_overview(self):
        search = web_search_config(self.server.secrets)
        media_oss = media_oss_config(self.server.secrets)
        chat_oss = chat_image_oss_config(self.server.secrets)
        cat_oss = cat_oss_config(self.server.secrets)
        tingwu = tingwu_config(self.server.secrets)
        tts = tts_config(self.server.secrets)
        with db() as conn:
            user_count = conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
            active_user_count = conn.execute("SELECT COUNT(*) AS n FROM users WHERE is_active=1").fetchone()["n"]
            model_count = conn.execute("SELECT COUNT(*) AS n FROM models").fetchone()["n"]
            enabled_model_count = conn.execute("SELECT COUNT(*) AS n FROM models WHERE enabled=1").fetchone()["n"]
            conversation_count = conn.execute("SELECT COUNT(*) AS n FROM conversations WHERE archived=0").fetchone()["n"]
        return self.json(
            {
                "overview": {
                    "users": {
                        "total": int(user_count or 0),
                        "active": int(active_user_count or 0),
                    },
                    "models": {
                        "total": int(model_count or 0),
                        "enabled": int(enabled_model_count or 0),
                    },
                    "conversations": {
                        "total": int(conversation_count or 0),
                    },
                    "search": {
                        "enabled": bool(search["enabled"]),
                        "configured": bool(search["api_key"]),
                        "provider": search["provider"],
                        "mode": search["mode"],
                    },
                    "oss": {
                        "cat": bool(cat_oss["configured"]),
                        "chat_image": bool(chat_oss["configured"]),
                        "media": bool(media_oss["configured"]),
                        "configured": bool(cat_oss["configured"] or chat_oss["configured"] or media_oss["configured"]),
                    },
                    "tingwu": {
                        "configured": bool(tingwu_configured(tingwu)),
                    },
                    "tts": {
                        "enabled": bool(tts["enabled"]),
                        "configured": bool(tts["configured"]),
                        "voice_count": len(tts["voices"]),
                    },
                }
            }
        )

    def handle_admin_models(self):
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute("SELECT * FROM models ORDER BY updated_at DESC").fetchall()
            return self.json({"models": [private_model(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        name = str(data.get("name") or "").strip()
        base_url = str(data.get("base_url") or "").strip().rstrip("/")
        api_key = str(data.get("api_key") or "").strip()
        model = str(data.get("model") or "").strip()
        provider = str(data.get("provider") or "").strip()
        system_prompt = str(data.get("system_prompt") or "").strip()
        supports_vision = 1 if data.get("supports_vision") else 0
        supports_native_web_search = 1 if data.get("supports_native_web_search") else 0
        enabled = 1 if data.get("enabled", True) else 0
        input_price = parse_price(data.get("input_price_per_million"))
        output_price = parse_price(data.get("output_price_per_million"))
        cost_enabled = 1 if data.get("cost_enabled") else 0
        cost_note = str(data.get("cost_note") or "").strip()[:500]

        if not name or not base_url or not model:
            return self.error(HTTPStatus.BAD_REQUEST, "name, base_url and model are required")

        model_id = b64_token(12)
        ts = now()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO models
                (id, name, provider, base_url, api_key, model, system_prompt, supports_vision,
                 supports_native_web_search, enabled,
                 input_price_per_million, output_price_per_million, cost_enabled, cost_note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_id,
                    name,
                    provider,
                    base_url,
                    api_key,
                    model,
                    system_prompt,
                    supports_vision,
                    supports_native_web_search,
                    enabled,
                    input_price,
                    output_price,
                    cost_enabled,
                    cost_note,
                    ts,
                    ts,
                ),
            )
            row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        return self.json({"model": private_model(row)}, HTTPStatus.CREATED)

    def handle_admin_model_item(self):
        model_id = urlparse(self.path).path.rsplit("/", 1)[-1]
        with db() as conn:
            row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "model not found")

            if self.command == "DELETE":
                linked = conn.execute(
                    "SELECT COUNT(*) AS n FROM conversations WHERE model_id=?",
                    (model_id,),
                ).fetchone()["n"]
                if linked:
                    conn.execute(
                        "UPDATE models SET enabled=0, updated_at=? WHERE id=?",
                        (now(), model_id),
                    )
                else:
                    conn.execute("DELETE FROM models WHERE id=?", (model_id,))
                return self.json({"ok": True})

            try:
                data = self.read_body()
            except Exception:
                return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

            name = str(data.get("name", row["name"])).strip()
            provider = str(data.get("provider", row["provider"])).strip()
            base_url = str(data.get("base_url", row["base_url"])).strip().rstrip("/")
            model = str(data.get("model", row["model"])).strip()
            system_prompt = str(data.get("system_prompt", row["system_prompt"])).strip()
            supports_vision = 1 if data.get("supports_vision", bool(row["supports_vision"])) else 0
            supports_native_web_search = 1 if data.get(
                "supports_native_web_search", bool(row["supports_native_web_search"])
            ) else 0
            enabled = 1 if data.get("enabled", bool(row["enabled"])) else 0
            input_price = parse_price(data.get("input_price_per_million", row["input_price_per_million"]))
            output_price = parse_price(data.get("output_price_per_million", row["output_price_per_million"]))
            cost_enabled = 1 if data.get("cost_enabled", bool(row["cost_enabled"])) else 0
            cost_note = str(data.get("cost_note", row["cost_note"]) or "").strip()[:500]
            api_key = row["api_key"]
            if data.get("clear_api_key"):
                api_key = ""
            elif str(data.get("api_key") or "").strip():
                api_key = str(data.get("api_key")).strip()

            if not name or not base_url or not model:
                return self.error(HTTPStatus.BAD_REQUEST, "name, base_url and model are required")

            conn.execute(
                """
                UPDATE models
                SET name=?, provider=?, base_url=?, api_key=?, model=?, system_prompt=?, supports_vision=?,
                    supports_native_web_search=?, enabled=?,
                    input_price_per_million=?, output_price_per_million=?, cost_enabled=?, cost_note=?, updated_at=?
                WHERE id=?
                """,
                (
                    name,
                    provider,
                    base_url,
                    api_key,
                    model,
                    system_prompt,
                    supports_vision,
                    supports_native_web_search,
                    enabled,
                    input_price,
                    output_price,
                    cost_enabled,
                    cost_note,
                    now(),
                    model_id,
                ),
            )
            row = conn.execute("SELECT * FROM models WHERE id=?", (model_id,)).fetchone()
        return self.json({"model": private_model(row)})

    def handle_admin_password(self):
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        password = str(data.get("password") or "")
        if len(password) < 8:
            return self.error(HTTPStatus.BAD_REQUEST, "password must be at least 8 characters")
        self.server.secrets["family_password_hash"] = password_hash(password)
        write_private(SECRETS_PATH, json.dumps(self.server.secrets, indent=2) + "\n")
        write_private(FAMILY_PASSWORD_PATH, password + "\n")
        with db() as conn:
            conn.execute(
                "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
                (self.server.secrets["family_password_hash"], now(), DEFAULT_AI_USER_ID),
            )
            conn.execute("DELETE FROM sessions")
        return self.json({"ok": True})

    def handle_admin_users(self):
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    "SELECT * FROM users ORDER BY created_at ASC"
                ).fetchall()
            return self.json({"users": [ai_user_public(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        username = str(data.get("username") or "").strip().lower()
        display_name = str(data.get("display_name") or username).strip()[:40]
        password = str(data.get("password") or "")
        role = str(data.get("role") or "family").strip().lower()
        is_active = 1 if data.get("is_active", True) else 0

        if not USERNAME_RE.match(username):
            return self.error(HTTPStatus.BAD_REQUEST, "username invalid")
        if role not in ("admin", "family"):
            return self.error(HTTPStatus.BAD_REQUEST, "role invalid")
        if len(password) < 6:
            return self.error(HTTPStatus.BAD_REQUEST, "password must be at least 6 characters")
        if not display_name:
            display_name = username

        user_id = b64_token(10)
        ts = now()
        try:
            with db() as conn:
                conn.execute(
                    """
                    INSERT INTO users
                    (id, username, display_name, password_hash, role, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        username,
                        display_name,
                        password_hash(password),
                        role,
                        is_active,
                        ts,
                        ts,
                    ),
                )
                row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        except sqlite3.IntegrityError:
            return self.error(HTTPStatus.CONFLICT, "username already exists")
        return self.json({"user": ai_user_public(row)}, HTTPStatus.CREATED)

    def admin_user_id_from_path(self):
        return urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]

    def handle_admin_user_item(self):
        user_id = self.admin_user_id_from_path()
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        with db() as conn:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "user not found")

            display_name = str(data.get("display_name", row["display_name"]) or "").strip()[:40] or row["display_name"]
            role = str(data.get("role", row["role"]) or row["role"]).strip().lower()
            if role not in ("admin", "family"):
                return self.error(HTTPStatus.BAD_REQUEST, "role invalid")
            is_active = 1 if data.get("is_active", bool(row["is_active"])) else 0
            password = str(data.get("password") or "")

            if (row["role"] == "admin" and (role != "admin" or not is_active)):
                active_admins = conn.execute(
                    "SELECT COUNT(*) AS n FROM users WHERE role='admin' AND is_active=1 AND id<>?",
                    (user_id,),
                ).fetchone()["n"]
                if active_admins <= 0:
                    return self.error(HTTPStatus.BAD_REQUEST, "at least one active admin is required")

            password_clause = ""
            params = [display_name, role, is_active, now()]
            if password:
                if len(password) < 6:
                    return self.error(HTTPStatus.BAD_REQUEST, "password must be at least 6 characters")
                password_clause = ", password_hash=?"
                params.append(password_hash(password))
            params.append(user_id)
            conn.execute(
                f"""
                UPDATE users
                SET display_name=?, role=?, is_active=?, updated_at=?{password_clause}
                WHERE id=?
                """,
                tuple(params),
            )
            if not is_active:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self.json({"user": ai_user_public(row)})
