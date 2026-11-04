"""超能模式与客户交付稿的账号内接口。"""
from .shared import *
from .. import super_writing, writing


class SuperWritingHandlersMixin:
    def handle_super_writing(self):
        cid, uid = self.conversation_id_from_path(), self.current_user()["id"]
        if not super_writing.eligible(uid):
            return self.error(HTTPStatus.NOT_FOUND, "not found")
        lock = writing.task_lock(uid, cid)
        if not lock.acquire(blocking=False):
            return self.error(HTTPStatus.CONFLICT, "当前对话正在生成或保存，请稍后再试")
        try:
            with db() as conn:
                conversation = conn.execute("SELECT id FROM conversations WHERE id=? AND user_id=? AND archived=0", (cid, uid)).fetchone()
                if not conversation:
                    return self.error(HTTPStatus.NOT_FOUND, "conversation not found")
                if self.command == "GET":
                    return self.json(super_writing.public_state(conn, cid, uid))
                try:
                    data = self.read_body(limit=1024 * 1024)
                    if not isinstance(data, dict):
                        raise ValueError("请求格式不正确")
                    revision = data.get("revision")
                    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                        raise ValueError("请先读取当前交付版本")
                    conn.execute("BEGIN IMMEDIATE")
                    if revision != super_writing.settings_revision(conn, cid, uid):
                        return self.error(HTTPStatus.CONFLICT, "当前对话设置或交付稿已更新，请刷新后重试")
                    if self.command == "PATCH":
                        if not isinstance(data.get("enabled"), bool):
                            raise ValueError("超能模式开关值不正确")
                        conn.execute("UPDATE conversations SET super_mode=? WHERE id=? AND user_id=? AND archived=0",
                                     (int(data["enabled"]), cid, uid))
                    elif self.command == "POST":
                        self._save_super_delivery(conn, cid, uid, data)
                    else:
                        return self.error(HTTPStatus.METHOD_NOT_ALLOWED, "method not allowed")
                    super_writing.bump_revision(conn, cid, uid)
                    result = super_writing.public_state(conn, cid, uid)
                except (ValueError, TypeError) as exc:
                    conn.rollback()
                    return self.error(HTTPStatus.BAD_REQUEST, str(exc))
            return self.json(result, HTTPStatus.CREATED if self.command == "POST" else HTTPStatus.OK)
        finally:
            lock.release()

    def _save_super_delivery(self, conn, cid, uid, data):
        content = data.get("content", "")
        if not isinstance(content, str):
            raise ValueError("交付稿正文须为文字")
        document_id = data.get("document_id", "")
        if not isinstance(document_id, str) or len(document_id) > 100:
            raise ValueError("文件编号不正确")
        filename = data.get("filename", "")
        label = data.get("label", "最终交付")
        if not isinstance(filename, str) or len(filename) > 180:
            raise ValueError("文件名过长或格式不正确")
        if not isinstance(label, str) or len(label) > 80:
            raise ValueError("交付稿名称过长或格式不正确")
        label = label.strip() or "最终交付"
        if document_id:
            document = conn.execute("SELECT * FROM document_files WHERE id=? AND user_id=?", (document_id, uid)).fetchone()
            if not document or document["status"] != "completed":
                raise ValueError("文件不存在或尚未解析完成")
            if not content.strip():
                coverage = conn.execute("""SELECT COUNT(*) n,COUNT(DISTINCT ordinal) ordinals,COALESCE(SUM(LENGTH(content)),0) chars,
                    MIN(ordinal) first,MAX(ordinal) last FROM document_chunks WHERE document_id=? AND user_id=?""", (document_id, uid)).fetchone()
                expected = int(document["chunk_count"] or 0)
                if int(coverage["n"]) != expected or int(coverage["ordinals"]) != expected or (expected and (coverage["first"] != 0 or coverage["last"] != expected - 1)):
                    raise ValueError("文件解析内容不完整，请粘贴终稿正文")
                if int(coverage["chars"]) + max(0, expected - 1) * 2 > super_writing.MAX_DELIVERY_CHARS:
                    raise ValueError("解析正文超过100000字，请粘贴最终交付部分")
                if expected:
                    chunks = conn.execute("SELECT content FROM document_chunks WHERE document_id=? AND user_id=? ORDER BY ordinal", (document_id, uid)).fetchall()
                    content = "\n\n".join(row["content"] for row in chunks).strip()
                else:
                    # 兼容旧版仅保存全文的文档；不截取原文后伪装完整交付。
                    content = str(document["parsed_text"] or "").strip()
            filename = filename or document["filename"]
        content = content.strip()
        if not content or len(content) > super_writing.MAX_DELIVERY_CHARS:
            raise ValueError("交付稿须为1至100000字；过长文件请选取最终交付正文后保存")
        ts = now()
        conn.execute("""UPDATE super_deliveries SET superseded=1,updated_at=?
            WHERE conversation_id=? AND user_id=? AND label=? AND superseded=0""", (ts, cid, uid, label))
        conn.execute("""INSERT INTO super_deliveries
            (conversation_id,user_id,content,source,filename,label,document_id,created_at,updated_at)
            VALUES (?,?,?,'customer',?,?,?,?,?)""", (cid, uid, content, filename.strip(), label, document_id, ts, ts))
