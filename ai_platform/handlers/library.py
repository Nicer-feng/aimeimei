from .shared import *


class LibraryHandlersMixin:
    def handle_profiles(self):
        user_id = self.current_user()["id"]
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM user_profiles
                    WHERE user_id=?
                    ORDER BY sort_order ASC, updated_at DESC
                    LIMIT 300
                    """,
                    (user_id,),
                ).fetchall()
            return self.json(
                {
                    "profiles": [user_profile_row(row) for row in rows],
                    "totals": profile_totals(rows),
                }
            )

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        title = str(data.get("title") or "").strip()[:80]
        content = str(data.get("content") or "").strip()
        profile_type = str(data.get("type") or "profile").strip().lower()[:32] or "profile"
        if profile_type not in ("profile", "project", "style", "memory"):
            profile_type = "profile"
        enabled = 1 if data.get("enabled", True) else 0
        sort_order = clamp_int(data.get("sort_order"), 100, -100000, 100000)
        if not title or not content:
            return self.error(HTTPStatus.BAD_REQUEST, "title and content are required")
        if len(content) > 12000:
            return self.error(HTTPStatus.BAD_REQUEST, "content too long")

        profile_id = b64_token(10)
        ts = now()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO user_profiles
                (id, user_id, title, content, type, sort_order, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (profile_id, user_id, title, content, profile_type, sort_order, enabled, ts, ts),
            )
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE id=? AND user_id=?",
                (profile_id, user_id),
            ).fetchone()
        return self.json({"profile": user_profile_row(row)}, HTTPStatus.CREATED)

    def profile_id_from_path(self):
        return urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]

    def handle_profile_item(self):
        profile_id = self.profile_id_from_path()
        user_id = self.current_user()["id"]
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE id=? AND user_id=?",
                (profile_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "profile not found")

            if self.command == "DELETE":
                conn.execute("DELETE FROM user_profiles WHERE id=? AND user_id=?", (profile_id, user_id))
                return self.json({"ok": True})

            try:
                data = self.read_body()
            except Exception:
                return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
            title = str(data.get("title", row["title"]) or "").strip()[:80]
            content = str(data.get("content", row["content"]) or "").strip()
            profile_type = str(data.get("type", row["type"]) or "profile").strip().lower()[:32] or "profile"
            if profile_type not in ("profile", "project", "style", "memory"):
                profile_type = "profile"
            enabled = 1 if data.get("enabled", bool(row["enabled"])) else 0
            sort_order = clamp_int(data.get("sort_order", row["sort_order"]), row["sort_order"], -100000, 100000)
            if not title or not content:
                return self.error(HTTPStatus.BAD_REQUEST, "title and content are required")
            if len(content) > 12000:
                return self.error(HTTPStatus.BAD_REQUEST, "content too long")
            conn.execute(
                """
                UPDATE user_profiles
                SET title=?, content=?, type=?, sort_order=?, enabled=?, updated_at=?
                WHERE id=? AND user_id=?
                """,
                (title, content, profile_type, sort_order, enabled, now(), profile_id, user_id),
            )
            row = conn.execute(
                "SELECT * FROM user_profiles WHERE id=? AND user_id=?",
                (profile_id, user_id),
            ).fetchone()
        return self.json({"profile": user_profile_row(row)})

    def handle_profile_reorder(self):
        user_id = self.current_user()["id"]
        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        ids = data.get("ids") or []
        if not isinstance(ids, list):
            return self.error(HTTPStatus.BAD_REQUEST, "ids required")
        clean_ids = []
        for item in ids:
            value = str(item or "").strip()
            if value and value not in clean_ids:
                clean_ids.append(value)
        with db() as conn:
            existing = {
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM user_profiles WHERE user_id=?",
                    (user_id,),
                ).fetchall()
            }
            ts = now()
            for index, profile_id in enumerate(clean_ids):
                if profile_id in existing:
                    conn.execute(
                        "UPDATE user_profiles SET sort_order=?, updated_at=? WHERE id=? AND user_id=?",
                        ((index + 1) * 10, ts, profile_id, user_id),
                    )
            rows = conn.execute(
                """
                SELECT *
                FROM user_profiles
                WHERE user_id=?
                ORDER BY sort_order ASC, updated_at DESC
                """,
                (user_id,),
            ).fetchall()
        return self.json({"profiles": [user_profile_row(row) for row in rows], "totals": profile_totals(rows)})

    def handle_prompts(self):
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM prompt_templates
                    ORDER BY sort_order ASC, updated_at DESC
                    LIMIT 300
                    """
                ).fetchall()
            return self.json({"prompts": [prompt_template_row(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")

        title = str(data.get("title") or "").strip()[:80]
        content = str(data.get("content") or "").strip()
        sort_order = clamp_int(data.get("sort_order"), 100, -100000, 100000)
        if not title or not content:
            return self.error(HTTPStatus.BAD_REQUEST, "title and content are required")
        if len(content) > 4000:
            return self.error(HTTPStatus.BAD_REQUEST, "content too long")

        prompt_id = b64_token(10)
        ts = now()
        with db() as conn:
            conn.execute(
                """
                INSERT INTO prompt_templates(id, title, content, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (prompt_id, title, content, sort_order, ts, ts),
            )
            row = conn.execute("SELECT * FROM prompt_templates WHERE id=?", (prompt_id,)).fetchone()
        return self.json({"prompt": prompt_template_row(row)}, HTTPStatus.CREATED)

    def prompt_id_from_path(self):
        return urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]

    def handle_prompt_item(self):
        prompt_id = self.prompt_id_from_path()
        with db() as conn:
            row = conn.execute("SELECT * FROM prompt_templates WHERE id=?", (prompt_id,)).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "prompt not found")

            if self.command == "DELETE":
                conn.execute("DELETE FROM prompt_templates WHERE id=?", (prompt_id,))
                return self.json({"ok": True})

            try:
                data = self.read_body()
            except Exception:
                return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
            title = str(data.get("title", row["title"]) or "").strip()[:80]
            content = str(data.get("content", row["content"]) or "").strip()
            sort_order = clamp_int(data.get("sort_order", row["sort_order"]), row["sort_order"], -100000, 100000)
            if not title or not content:
                return self.error(HTTPStatus.BAD_REQUEST, "title and content are required")
            if len(content) > 4000:
                return self.error(HTTPStatus.BAD_REQUEST, "content too long")
            conn.execute(
                """
                UPDATE prompt_templates
                SET title=?, content=?, sort_order=?, updated_at=?
                WHERE id=?
                """,
                (title, content, sort_order, now(), prompt_id),
            )
            row = conn.execute("SELECT * FROM prompt_templates WHERE id=?", (prompt_id,)).fetchone()
        return self.json({"prompt": prompt_template_row(row)})

    def handle_favorites(self):
        user = self.current_user()
        user_id = user["id"]
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    """
                    SELECT f.*,
                           c.title AS live_conversation_title,
                           COALESCE(c.archived, 1) AS conversation_archived
                    FROM favorite_messages f
                    LEFT JOIN conversations c ON c.id = f.conversation_id
                    WHERE f.user_id=?
                    ORDER BY f.created_at DESC
                    LIMIT 300
                    """,
                    (user_id,),
                ).fetchall()
            return self.json({"favorites": [favorite_row(row) for row in rows]})

        try:
            data = self.read_body()
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        try:
            message_id = int(data.get("message_id") or 0)
        except (TypeError, ValueError):
            message_id = 0
        if message_id <= 0:
            return self.error(HTTPStatus.BAD_REQUEST, "message_id required")

        with db() as conn:
            existing = conn.execute(
                """
                SELECT f.*,
                       c.title AS live_conversation_title,
                       COALESCE(c.archived, 1) AS conversation_archived
                FROM favorite_messages f
                LEFT JOIN conversations c ON c.id = f.conversation_id
                WHERE f.message_id=? AND f.user_id=?
                """,
                (message_id, user_id),
            ).fetchone()
            if existing:
                return self.json({"favorite": favorite_row(existing)})

            message = conn.execute(
                """
                SELECT m.id, m.conversation_id, m.role, m.content, m.created_at,
                       c.title AS conversation_title
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.id=? AND c.user_id=?
                """,
                (message_id, user_id),
            ).fetchone()
            if not message:
                return self.error(HTTPStatus.NOT_FOUND, "message not found")
            if message["role"] != "assistant":
                return self.error(HTTPStatus.BAD_REQUEST, "only assistant messages can be favorited")

            favorite_id = b64_token(10)
            ts = now()
            conn.execute(
                """
                INSERT INTO favorite_messages
                (id, user_id, message_id, conversation_id, conversation_title, role, content, message_created_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    favorite_id,
                    user_id,
                    message["id"],
                    message["conversation_id"],
                    message["conversation_title"],
                    message["role"],
                    message["content"],
                    message["created_at"],
                    ts,
                ),
            )
            row = conn.execute(
                """
                SELECT f.*,
                       c.title AS live_conversation_title,
                       COALESCE(c.archived, 1) AS conversation_archived
                FROM favorite_messages f
                LEFT JOIN conversations c ON c.id = f.conversation_id
                WHERE f.id=? AND f.user_id=?
                """,
                (favorite_id, user_id),
            ).fetchone()
        return self.json({"favorite": favorite_row(row)}, HTTPStatus.CREATED)

    def favorite_id_from_path(self):
        return urlparse(self.path).path.rstrip("/").rsplit("/", 1)[-1]

    def handle_favorite_item(self):
        favorite_id = self.favorite_id_from_path()
        user_id = self.current_user()["id"]
        with db() as conn:
            row = conn.execute(
                "SELECT id FROM favorite_messages WHERE id=? AND user_id=?",
                (favorite_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "favorite not found")
            conn.execute("DELETE FROM favorite_messages WHERE id=? AND user_id=?", (favorite_id, user_id))
        return self.json({"ok": True})

    def handle_favorite_by_message(self):
        try:
            message_id = int(self.favorite_id_from_path())
        except (TypeError, ValueError):
            message_id = 0
        if message_id <= 0:
            return self.error(HTTPStatus.BAD_REQUEST, "message_id required")
        user_id = self.current_user()["id"]
        with db() as conn:
            conn.execute(
                "DELETE FROM favorite_messages WHERE message_id=? AND user_id=?",
                (message_id, user_id),
            )
        return self.json({"ok": True})
