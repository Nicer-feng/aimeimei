from .shared import *
from ..ocr import handwriting_result, ocr_config, ocr_configured, recognize_handwriting
from ..storage import ocr_oss_config, ocr_oss_prefix, ocr_upload_policy
from ..presenters import ocr_task_public


class OcrHandlersMixin:
    def ocr_task_id_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        return parts[3] if len(parts) >= 4 else ""

    def handle_ocr_upload_policy(self):
        user = self.current_user()
        config = ocr_oss_config(self.server.secrets)
        if not config["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "OCR 图片存储还没有配置好")
        return self.json({"policy": ocr_upload_policy(config, user["id"])})

    def handle_ocr_tasks(self):
        user = self.current_user()
        user_id = user["id"]
        if self.command == "GET":
            with db() as conn:
                rows = conn.execute(
                    "SELECT * FROM ocr_tasks WHERE user_id=? ORDER BY updated_at DESC LIMIT 100",
                    (user_id,),
                ).fetchall()
            return self.json({"tasks": [ocr_task_public(row) for row in rows]})

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

        storage = ocr_oss_config(self.server.secrets)
        service = ocr_config(self.server.secrets)
        if not storage["configured"]:
            return self.error(HTTPStatus.BAD_REQUEST, "OCR 图片存储还没有配置好")
        if not ocr_configured(service):
            return self.error(HTTPStatus.BAD_REQUEST, "阿里云 OCR 还没有配置好")
        suffix = Path(filename or oss_key).suffix.lower()
        expected_prefix = ocr_oss_prefix(storage, user_id)
        if not filename or not oss_key:
            return self.error(HTTPStatus.BAD_REQUEST, "请先上传手写图片")
        if suffix not in OCR_ALLOWED_EXTENSIONS:
            return self.error(HTTPStatus.BAD_REQUEST, "仅支持 JPG、PNG、BMP、GIF、TIFF、WebP 图片")
        if mime_type and mime_type not in OCR_ALLOWED_MIME_TYPES:
            return self.error(HTTPStatus.BAD_REQUEST, "暂不支持这个图片格式")
        if file_size <= 0 or file_size > storage["max_size"]:
            return self.error(HTTPStatus.BAD_REQUEST, "单张图片不能超过 10MB")
        if oss_key.startswith("/") or ".." in oss_key.split("/") or not oss_key.startswith(expected_prefix):
            return self.error(HTTPStatus.BAD_REQUEST, "图片路径不合法")

        task_id = b64_token(12)
        ts = now()
        status = "completed"
        text = ""
        block_count = 0
        request_id = ""
        error_message = ""
        try:
            signed_url, _ = oss_signed_get_url(storage, oss_key, 3600)
            result = handwriting_result(recognize_handwriting(service, signed_url))
            text = result["content"]
            block_count = result["block_count"]
            request_id = result["request_id"]
            if not text:
                status = "failed"
                error_message = "没有识别到可展示的文字，请换一张更清晰的图片试试"
        except urllib.error.HTTPError as exc:
            status = "failed"
            error_message = f"阿里云手写识别失败：HTTP {exc.code}"
        except Exception:
            status = "failed"
            error_message = "阿里云手写识别失败，请稍后重试"

        with db() as conn:
            conn.execute(
                """
                INSERT INTO ocr_tasks
                (id, user_id, filename, mime_type, file_size, oss_key, status, recognized_text,
                 block_count, request_id, error_message, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (task_id, user_id, filename, mime_type, file_size, oss_key, status, text,
                 block_count, request_id, error_message, ts, ts),
            )
            row = conn.execute(
                "SELECT * FROM ocr_tasks WHERE id=? AND user_id=?", (task_id, user_id)
            ).fetchone()
        return self.json({"task": ocr_task_public(row)}, HTTPStatus.CREATED)

    def handle_ocr_task_item(self):
        user_id = self.current_user()["id"]
        task_id = self.ocr_task_id_from_path()
        with db() as conn:
            row = conn.execute(
                "SELECT * FROM ocr_tasks WHERE id=? AND user_id=?", (task_id, user_id)
            ).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, "ocr task not found")
            if self.command == "DELETE":
                conn.execute("DELETE FROM ocr_tasks WHERE id=? AND user_id=?", (task_id, user_id))
                return self.json({"ok": True})
        return self.json({"task": ocr_task_public(row)})
