from .shared import *


SHARE_EXPIRIES = {3600, 21600, 86400, 604800}
SHARE_SCOPES = {"assistant", "turn", "conversation"}


class ShareHandlersMixin:
    def share_token_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) >= 4 and parts[:3] == ["api", "public", "shares"]:
            return unquote(parts[3])
        return ""

    def share_id_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) >= 3 and parts[:2] == ["api", "conversation-shares"]:
            return unquote(parts[2])
        return ""

    def share_image_id_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) >= 6 and parts[:3] == ["api", "public", "shares"] and parts[4] == "images":
            return unquote(parts[5])
        return ""

    def handle_conversation_shares(self):
        conversation_id = self.conversation_id_from_path()
        user_id = self.current_user()["id"]
        if self.command == "GET":
            with db() as conn:
                exists = conn.execute(
                    "SELECT id FROM conversations WHERE id=? AND user_id=? AND archived=0",
                    (conversation_id, user_id),
                ).fetchone()
                if not exists:
                    return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
                rows = conn.execute(
                    """
                    SELECT id, scope, source_message_id, title, created_at, expires_at,
                           revoked_at, access_count, last_access_at
                    FROM conversation_shares
                    WHERE conversation_id=? AND user_id=?
                    ORDER BY created_at DESC
                    LIMIT 30
                    """,
                    (conversation_id, user_id),
                ).fetchall()
            return self.json({"shares": [self.share_owner_public(row) for row in rows]})

        try:
            data = self.read_body(limit=128 * 1024)
        except Exception:
            return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
        scope = str(data.get("scope") or "conversation").strip().lower()
        if scope not in SHARE_SCOPES:
            return self.error(HTTPStatus.BAD_REQUEST, "分享范围不支持")
        try:
            expires_in = int(data.get("expires_in") or 86400)
        except (TypeError, ValueError):
            expires_in = 0
        if expires_in not in SHARE_EXPIRIES:
            return self.error(HTTPStatus.BAD_REQUEST, "分享有效期不支持")
        try:
            source_message_id = int(data.get("message_id") or 0)
        except (TypeError, ValueError):
            source_message_id = 0
        if scope != "conversation" and not source_message_id:
            return self.error(HTTPStatus.BAD_REQUEST, "请选择要分享的 AI 回答")

        with db() as conn:
            conversation = conn.execute(
                """
                SELECT c.id, c.title, c.created_at, c.updated_at,
                       m.name AS model_name, m.model
                FROM conversations c JOIN models m ON m.id=c.model_id
                WHERE c.id=? AND c.user_id=? AND c.archived=0
                """,
                (conversation_id, user_id),
            ).fetchone()
            if not conversation:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
            messages = conn.execute(
                """
                SELECT id, role, content, created_at
                FROM messages
                WHERE conversation_id=? AND user_id=? AND role IN ('user', 'assistant')
                ORDER BY id ASC
                """,
                (conversation_id, user_id),
            ).fetchall()
            selected = self.select_shared_messages(messages, scope, source_message_id)
            if not selected:
                return self.error(HTTPStatus.BAD_REQUEST, "没有可分享的消息")
            snapshot = self.build_share_snapshot(conn, conversation, selected, scope)
            token = b64_token(32)
            share_id = b64_token(12)
            ts = now()
            conn.execute(
                """
                INSERT INTO conversation_shares(
                  id, user_id, conversation_id, token_hash, scope,
                  source_message_id, title, snapshot_json, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    share_id, user_id, conversation_id, token_hash(token), scope,
                    source_message_id, conversation["title"],
                    json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
                    ts, ts + expires_in,
                ),
            )
            conn.execute(
                "DELETE FROM conversation_shares WHERE expires_at<? AND created_at<?",
                (ts - 30 * 86400, ts - 30 * 86400),
            )
            row = conn.execute(
                """
                SELECT id, scope, source_message_id, title, created_at, expires_at,
                       revoked_at, access_count, last_access_at
                FROM conversation_shares WHERE id=?
                """,
                (share_id,),
            ).fetchone()
        payload = self.share_owner_public(row)
        payload["token"] = token
        payload["url"] = f"/ai/share/{quote(token, safe='')}"
        return self.json({"share": payload}, HTTPStatus.CREATED)

    def select_shared_messages(self, messages, scope, source_message_id):
        rows = list(messages)
        if scope == "conversation":
            return rows
        assistant_index = next(
            (index for index, row in enumerate(rows) if row["id"] == source_message_id and row["role"] == "assistant"),
            -1,
        )
        if assistant_index < 0:
            return []
        if scope == "assistant":
            return [rows[assistant_index]]
        for index in range(assistant_index - 1, -1, -1):
            if rows[index]["role"] == "user":
                return [rows[index], rows[assistant_index]]
        return [rows[assistant_index]]

    def build_share_snapshot(self, conn, conversation, messages, scope):
        message_ids = [row["id"] for row in messages]
        placeholders = ",".join("?" for _ in message_ids)
        sources = conn.execute(
            f"""
            SELECT message_id, title, url, snippet, position
            FROM message_sources WHERE message_id IN ({placeholders})
            ORDER BY message_id, position
            """,
            message_ids,
        ).fetchall() if message_ids else []
        images = conn.execute(
            f"""
            SELECT id, message_id, filename, mime_type, file_size, oss_key, created_at
            FROM chat_message_images WHERE message_id IN ({placeholders})
            ORDER BY message_id, created_at, id
            """,
            message_ids,
        ).fetchall() if message_ids else []
        sources_by_message = {}
        for source in sources:
            sources_by_message.setdefault(source["message_id"], []).append({
                "title": source["title"], "url": source["url"],
                "snippet": source["snippet"], "position": source["position"],
            })
        images_by_message = {}
        for image in images:
            images_by_message.setdefault(image["message_id"], []).append({
                "id": image["id"], "filename": image["filename"],
                "mime_type": image["mime_type"], "file_size": image["file_size"],
                "oss_key": image["oss_key"], "created_at": image["created_at"],
            })
        return {
            "version": 1,
            "scope": scope,
            "title": conversation["title"],
            "model_name": conversation["model_name"],
            "model": conversation["model"],
            "conversation_created_at": conversation["created_at"],
            "snapshot_at": now(),
            "messages": [
                {
                    "id": row["id"], "role": row["role"],
                    "content": visible_user_question(row["content"]) if row["role"] == "user" else row["content"],
                    "created_at": row["created_at"],
                    "sources": sources_by_message.get(row["id"], []),
                    "images": images_by_message.get(row["id"], []),
                }
                for row in messages
            ],
        }

    def share_owner_public(self, row):
        ts = now()
        revoked = bool(row["revoked_at"])
        expired = int(row["expires_at"] or 0) <= ts
        return {
            "id": row["id"], "scope": row["scope"],
            "source_message_id": row["source_message_id"], "title": row["title"],
            "created_at": row["created_at"], "expires_at": row["expires_at"],
            "revoked": revoked, "expired": expired, "active": not revoked and not expired,
            "access_count": row["access_count"], "last_access_at": row["last_access_at"],
        }

    def handle_conversation_share_item(self):
        share_id = self.share_id_from_path()
        user_id = self.current_user()["id"]
        with db() as conn:
            row = conn.execute(
                "SELECT id FROM conversation_shares WHERE id=? AND user_id=?",
                (share_id, user_id),
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "share not found")
            conn.execute(
                "UPDATE conversation_shares SET revoked_at=? WHERE id=? AND user_id=?",
                (now(), share_id, user_id),
            )
        return self.json({"ok": True})

    def public_share_row(self, token):
        if not token or len(token) > 180:
            return None
        with db() as conn:
            return conn.execute(
                "SELECT * FROM conversation_shares WHERE token_hash=?",
                (token_hash(token),),
            ).fetchone()

    def handle_public_share(self):
        token = self.share_token_from_path()
        row = self.public_share_row(token)
        if not row:
            return self.error(HTTPStatus.NOT_FOUND, "分享链接不存在")
        if row["revoked_at"]:
            return self.error(HTTPStatus.GONE, "分享链接已关闭")
        if row["expires_at"] <= now():
            return self.error(HTTPStatus.GONE, "分享链接已过期")
        try:
            snapshot = json.loads(row["snapshot_json"])
        except (TypeError, ValueError):
            return self.error(HTTPStatus.INTERNAL_SERVER_ERROR, "分享内容暂时无法读取")
        for message in snapshot.get("messages") or []:
            for image in message.get("images") or []:
                image.pop("oss_key", None)
                image["view_url"] = f"/api/public/shares/{quote(token, safe='')}/images/{quote(str(image.get('id') or ''), safe='')}"
        with db() as conn:
            conn.execute(
                "UPDATE conversation_shares SET access_count=access_count+1, last_access_at=? WHERE id=?",
                (now(), row["id"]),
            )
        return self.json({"share": {
            "title": row["title"], "scope": row["scope"],
            "created_at": row["created_at"], "expires_at": row["expires_at"],
            "snapshot": snapshot,
        }})

    def handle_public_share_image(self):
        token = self.share_token_from_path()
        image_id = self.share_image_id_from_path()
        row = self.public_share_row(token)
        if not row or row["revoked_at"] or row["expires_at"] <= now():
            return self.error(HTTPStatus.GONE, "分享链接已失效")
        try:
            snapshot = json.loads(row["snapshot_json"])
        except (TypeError, ValueError):
            return self.error(HTTPStatus.NOT_FOUND, "image not found")
        image = next((item for message in snapshot.get("messages") or []
                      for item in message.get("images") or []
                      if str(item.get("id") or "") == image_id), None)
        if not image or not image.get("oss_key"):
            return self.error(HTTPStatus.NOT_FOUND, "image not found")
        config = chat_image_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "图片暂时无法查看")
        signed_url, _ = oss_signed_get_url(config, image["oss_key"], 900)
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", signed_url)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
