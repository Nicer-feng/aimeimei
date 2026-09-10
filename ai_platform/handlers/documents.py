from .shared import *
from ..docmind import (
    build_document_context,
    docmind_config,
    docmind_configured,
    document_chunks,
    get_doc_parser_result,
    query_doc_parser_status,
    response_error,
    response_status,
    response_task_id,
    safe_docmind_error,
    submit_doc_parser_job,
)
from ..presenters import document_file_public
from ..storage import document_oss_config, document_oss_prefix, document_upload_policy


class DocumentHandlersMixin:
    def document_id_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        return parts[2] if len(parts) >= 3 else ""

    def document_files_for_ids(self, conn, user_id, document_ids):
        if not document_ids:
            return []
        placeholders = ",".join("?" for _ in document_ids)
        rows = conn.execute(
            f"SELECT * FROM document_files WHERE id IN ({placeholders}) AND user_id=?",
            (*document_ids, user_id),
        ).fetchall()
        row_by_id = {row["id"]: row for row in rows}
        return [row_by_id[item] for item in document_ids if item in row_by_id]

    def handle_document_upload_policy(self):
        config = document_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "材料文件 OSS 还没有配置好")
        return self.json({"policy": document_upload_policy(config, self.current_user()["id"])})

    def handle_documents(self):
        user_id = self.current_user()["id"]
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute("SELECT * FROM document_files WHERE user_id=? ORDER BY updated_at DESC LIMIT 100", (user_id,)).fetchall()
            return self.json({"documents": [document_file_public(row) for row in rows]})
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
        storage = document_oss_config(self.server.secrets)
        service = docmind_config(self.server.secrets)
        if not storage["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "材料文件 OSS 还没有配置好")
        if not docmind_configured(service):
            return self.error(HTTPStatus.BAD_REQUEST, "阿里云文档解析还没有配置好")
        suffix = Path(filename or oss_key).suffix.lower()
        expected_prefix = document_oss_prefix(storage, user_id)
        if not filename or not oss_key:
            return self.error(HTTPStatus.BAD_REQUEST, "请先上传文件")
        if suffix not in DOCUMENT_ALLOWED_EXTENSIONS:
            return self.error(HTTPStatus.BAD_REQUEST, "支持 PDF、Word、Excel、PPT、图片、TXT、Markdown、HTML")
        if file_size <= 0 or file_size > storage["max_size"]:
            return self.error(HTTPStatus.BAD_REQUEST, "单个材料文件不能超过 50MB")
        if suffix in {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"} and file_size > DOCUMENT_MAX_IMAGE_BYTES:
            return self.error(HTTPStatus.BAD_REQUEST, "作为材料解析的单张图片不能超过 20MB")
        if oss_key.startswith("/") or ".." in oss_key.split("/") or not oss_key.startswith(expected_prefix):
            return self.error(HTTPStatus.BAD_REQUEST, "文件路径不合法")
        document_id = b64_token(12)
        ts = now()
        status, task_id, error_message = "submitted", "", ""
        try:
            signed_url, _ = oss_signed_get_url(storage, oss_key, 6 * 60 * 60)
            task_id = response_task_id(submit_doc_parser_job(service, signed_url, filename))
            if not task_id:
                status, error_message = "failed", "文档解析没有返回任务 ID"
        except urllib.error.HTTPError as exc:
            status, error_message = "failed", f"文档解析提交失败：HTTP {exc.code}"
        except Exception as exc:
            status, error_message = "failed", safe_docmind_error(exc)
        with db() as conn:
            conn.execute("""INSERT INTO document_files
                (id,user_id,filename,mime_type,file_size,oss_key,status,parser_task_id,error_message,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (document_id,user_id,filename,mime_type,file_size,oss_key,status,task_id,error_message,ts,ts))
            row = conn.execute("SELECT * FROM document_files WHERE id=? AND user_id=?", (document_id,user_id)).fetchone()
        return self.json({"document": document_file_public(row)}, HTTPStatus.CREATED)

    def refresh_document(self, conn, row):
        if not row or row["status"] in ("completed", "failed") or not row["parser_task_id"]:
            return row
        service = docmind_config(self.server.secrets)
        if not docmind_configured(service):
            conn.execute("UPDATE document_files SET status='failed', error_message=?, updated_at=? WHERE id=?", ("阿里云文档解析还没有配置好", now(), row["id"]))
            return conn.execute("SELECT * FROM document_files WHERE id=?", (row["id"],)).fetchone()
        try:
            status_response = query_doc_parser_status(service, row["parser_task_id"])
            status = response_status(status_response)
            if status in ("success", "completed", "complete"):
                result = get_doc_parser_result(service, row["parser_task_id"], 0, 3000)
                chunks = document_chunks(result)
                if not chunks:
                    raise RuntimeError("没有提取到可用于对话的文本")
                conn.execute("DELETE FROM document_chunks WHERE document_id=? AND user_id=?", (row["id"], row["user_id"]))
                conn.executemany("""INSERT INTO document_chunks
                    (document_id,user_id,ordinal,title,content,page_number,created_at)
                    VALUES (?,?,?,?,?,?,?)""", [(row["id"],row["user_id"],index,item["title"],item["content"],item["page"],now()) for index,item in enumerate(chunks)])
                conn.execute("""UPDATE document_files SET status='completed', parsed_text=?, page_count=?, chunk_count=?, error_message='', updated_at=? WHERE id=?""", ("\n\n".join(item["content"] for item in chunks)[:2_000_000], 0, len(chunks), now(), row["id"]))
            elif status in ("fail", "failed", "error"):
                conn.execute("UPDATE document_files SET status='failed', error_message=?, updated_at=? WHERE id=?", (response_error(status_response) or "文档解析失败", now(), row["id"]))
            else:
                conn.execute("UPDATE document_files SET status='processing', updated_at=? WHERE id=?", (now(), row["id"]))
        except Exception:
            conn.execute("UPDATE document_files SET status='failed', error_message=?, updated_at=? WHERE id=?", ("文档解析失败，请稍后重试", now(), row["id"]))
        return conn.execute("SELECT * FROM document_files WHERE id=?", (row["id"],)).fetchone()

    def handle_document_item(self):
        user_id = self.current_user()["id"]
        document_id = self.document_id_from_path()
        with db() as conn:
            row = conn.execute("SELECT * FROM document_files WHERE id=? AND user_id=?", (document_id,user_id)).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "document not found")
            if self.command == "DELETE":
                conn.execute("DELETE FROM conversation_documents WHERE document_id=? AND user_id=?", (document_id,user_id))
                conn.execute("DELETE FROM document_chunks WHERE document_id=? AND user_id=?", (document_id,user_id))
                conn.execute("DELETE FROM document_files WHERE id=? AND user_id=?", (document_id,user_id))
                return self.json({"ok": True})
            if self.command == "POST" and urlparse(self.path).path.endswith("/refresh"):
                row = self.refresh_document(conn, row)
        return self.json({"document": document_file_public(row)})

    def handle_conversation_documents(self):
        conversation_id = self.conversation_id_from_path()
        user_id = self.current_user()["id"]
        with db() as conn:
            conversation = conn.execute("SELECT id FROM conversations WHERE id=? AND user_id=? AND archived=0", (conversation_id,user_id)).fetchone()
            if not conversation:
                return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
            if self.command == "GET":
                rows = conn.execute("""SELECT d.* FROM conversation_documents cd JOIN document_files d ON d.id=cd.document_id
                    WHERE cd.conversation_id=? AND cd.user_id=? ORDER BY cd.created_at ASC""", (conversation_id,user_id)).fetchall()
                return self.json({"documents": [document_file_public(row) for row in rows]})
            try:
                data = self.read_body()
            except Exception:
                return self.error(HTTPStatus.BAD_REQUEST, "invalid json")
            document_ids = []
            for value in data.get("document_ids") or []:
                value = str(value or "").strip()
                if value and value not in document_ids:
                    document_ids.append(value)
            if len(document_ids) > DOCUMENT_MAX_COUNT:
                return self.error(HTTPStatus.BAD_REQUEST, "单次最多使用 5 份材料")
            rows = self.document_files_for_ids(conn, user_id, document_ids)
            if len(rows) != len(document_ids) or any(row["status"] != "completed" for row in rows):
                return self.error(HTTPStatus.BAD_REQUEST, "材料不存在或仍在解析中")
            conn.execute("DELETE FROM conversation_documents WHERE conversation_id=? AND user_id=?", (conversation_id,user_id))
            conn.executemany("INSERT INTO conversation_documents(conversation_id,document_id,user_id,created_at) VALUES (?,?,?,?)", [(conversation_id,row["id"],user_id,now()) for row in rows])
        return self.json({"documents": [document_file_public(row) for row in rows]})
