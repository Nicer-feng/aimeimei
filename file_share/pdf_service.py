"""Admin-only PDF page version workflow. PDF bytes travel through private OSS."""
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from urllib.error import HTTPError

from infrastructure.storage import StorageSecurityError

from .database import transaction
from .office_service import object_metadata

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 100
PART_SIZE = 8 * 1024 * 1024
UPLOAD_SECONDS = 3600
PDF_VALIDATE = Path(__file__).with_name('pdf_validate.py')
VALIDATOR_SLOT = threading.BoundedSemaphore(1)
UPLOAD_LOCKS = [threading.Lock() for _ in range(64)]


class PdfServiceError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def ensure(condition, message, status=400):
    if not condition:
        raise PdfServiceError(message, status)


def now():
    return int(time.time())


def version_view(version, file=None):
    return dict(id=version['id'], number=version['version_no'], size=version['size'],
                created_at=version['created_at'],
                published=bool(file and version['object_key'] == file['object_key']))


class PdfService:
    def __init__(self, handler, user_id):
        self.handler, self.user_id = handler, user_id

    def _admin(self):
        user = self.handler.current_user()
        ensure(user and user['id'] == self.user_id and user['role'] == 'admin',
               '仅管理员可以整理 PDF 页面', 403)

    def _file(self, conn, file_id):
        file = self.handler.fs_owned_file(conn, file_id, self.user_id)
        ensure(file['status'] == 'READY', '文件当前不可编辑', 409)
        ensure(file['file_type'] == 'PDF' and file['mime_type'] == 'application/pdf'
               and Path(file['original_filename']).suffix.lower() == '.pdf',
               '仅支持 PDF 文件', 415)
        ensure(0 < file['size'] <= MAX_PDF_BYTES, '仅支持 20 MB 以内的 PDF', 413)
        return file

    def _baseline(self, conn, file):
        exists = conn.execute('SELECT 1 FROM share_office_versions WHERE file_id=? LIMIT 1',
                              (file['id'],)).fetchone()
        if not exists:
            stamp = now()
            conn.execute('INSERT INTO share_office_versions '
                         '(id,file_id,version_no,object_key,size,sha256,created_by,published_at,created_at) '
                         'VALUES(?,?,?,?,?,?,?,?,?)',
                         (uuid.uuid4().hex, file['id'], 1, file['object_key'], file['size'],
                          file['sha256'], self.user_id, stamp, stamp))

    def _revision(self, conn, file):
        number = conn.execute('SELECT COALESCE(MAX(version_no),0) FROM share_office_versions WHERE file_id=?',
                              (file['id'],)).fetchone()[0]
        payload = '\0'.join((file['id'], file['object_key'], file['sha256'], str(file['size']), str(number)))
        return hashlib.sha256(payload.encode('utf-8')).hexdigest()

    def _upload(self, conn, upload_id):
        row = conn.execute('SELECT * FROM share_pdf_uploads WHERE id=? AND user_id=?',
                           (upload_id, self.user_id)).fetchone()
        ensure(row, 'PDF 上传任务不存在', 404)
        return dict(row)

    def _inspect(self, oss, key, expected_size, expected_sha):
        """Stream to disk, then parse in an isolated process. No SQLite lock is held."""
        ensure(0 < expected_size <= MAX_PDF_BYTES, '仅支持 20 MB 以内的 PDF', 413)
        try:
            oss.verify_private(key)
            with tempfile.TemporaryDirectory(prefix='share-pdf-check-') as directory:
                local = str(Path(directory) / 'document.pdf')
                digest, count = oss.download_to(key, local, MAX_PDF_BYTES)
                ensure(count == expected_size and digest == expected_sha,
                       'PDF 文件校验失败，请重新上传', 409)
                if not VALIDATOR_SLOT.acquire(timeout=10):
                    raise PdfServiceError('PDF 校验繁忙，请稍后重试', 429)
                try:
                    try:
                        completed = subprocess.run([sys.executable, '-I', str(PDF_VALIDATE), local],
                                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                                   timeout=20, check=False, text=True)
                    except subprocess.TimeoutExpired as exc:
                        raise PdfServiceError('PDF 校验超时，请换一个文件重试', 422) from exc
                finally:
                    VALIDATOR_SLOT.release()
        except ValueError as exc:
            raise PdfServiceError('PDF 文件超过 20 MB 限制', 413) from exc
        ensure(completed.returncode == 0 and len(completed.stdout) <= 4096,
               'PDF 结构校验失败，请确认文件可正常打开', 422)
        try:
            result = json.loads(completed.stdout)
        except (json.JSONDecodeError, TypeError) as exc:
            raise PdfServiceError('PDF 结构校验失败，请确认文件可正常打开', 422) from exc
        ensure(isinstance(result, dict), 'PDF 结构校验失败', 422)
        ensure('error' not in result, str(result.get('error')), 422)
        pages = result.get('pages')
        ensure(type(pages) is int and 1 <= pages <= MAX_PDF_PAGES,
               '仅支持 1–100 页 PDF', 422)
        return pages

    def _cleanup_one(self, upload):
        with transaction() as conn:
            file = self.handler.fs_owned_file(conn, upload['file_id'], self.user_id)
        oss = self.handler.fs_oss(file)
        if upload['upload_id']:
            try:
                oss.abort(upload['object_key'], upload['upload_id'])
            except HTTPError as exc:
                if exc.code != 404:
                    raise
        oss.delete(upload['object_key'])
        with transaction() as conn:
            conn.execute("UPDATE share_pdf_uploads SET status='ABORTED',upload_id=NULL,updated_at=? "
                         "WHERE id=? AND status='CLEANUP'", (now(), upload['id']))

    def _discard(self, upload):
        with transaction() as conn:
            conn.execute("UPDATE share_pdf_uploads SET status='CLEANUP',updated_at=? "
                         "WHERE id=? AND status IN ('PREPARING','UPLOADING','COMPLETING')",
                         (now(), upload['id']))
        try:
            self._cleanup_one(upload)
        except Exception:
            # The task stays CLEANUP and is retried by the next start/context.
            pass

    def _cleanup_expired(self):
        stamp = now()
        with transaction() as conn:
            rows = [dict(row) for row in conn.execute(
                "SELECT * FROM share_pdf_uploads WHERE user_id=? AND "
                "((status='CLEANUP' AND updated_at<=?) OR "
                "(expires_at<=? AND (status IN ('PREPARING','UPLOADING') "
                "OR (status='COMPLETING' AND lease_until<=?)))) LIMIT 12",
                (self.user_id, stamp - 30, stamp, stamp))]
            for row in rows:
                conn.execute("UPDATE share_pdf_uploads SET status='CLEANUP',updated_at=? WHERE id=?",
                             (stamp, row['id']))
            conn.execute("DELETE FROM share_pdf_uploads WHERE user_id=? AND status IN ('SAVED','ABORTED') "
                         "AND updated_at<?", (self.user_id, stamp - 7 * 86400))
        for row in rows:
            try:
                self._cleanup_one(row)
            except Exception:
                pass

    def dispatch(self, path, data):
        self._admin()
        parts = path.strip('/').split('/')
        method = self.handler.command
        if len(parts) == 3 and parts[0] == 'files':
            file_id, action = parts[1:]
            if action == 'context' and method == 'GET':
                return self.handler.json(self.context(file_id))
            if action == 'start' and method == 'POST':
                return self.handler.json(self.start(file_id, data))
            if action == 'versions' and method == 'GET':
                return self.handler.json(self.versions(file_id))
            if action == 'publish' and method == 'POST':
                return self.handler.json(self.publish(file_id, data))
        if len(parts) == 3 and parts[0] == 'uploads' and method == 'POST':
            upload_id, action = parts[1:]
            if action == 'part':
                return self.handler.json(self.part(upload_id, data))
            if action == 'complete':
                lock = UPLOAD_LOCKS[int(upload_id[:8], 16) % len(UPLOAD_LOCKS)] if re.fullmatch(r'[0-9a-f]{32}', upload_id) else UPLOAD_LOCKS[0]
                with lock:
                    return self.handler.json(self.complete(upload_id, data))
            if action == 'abort':
                lock = UPLOAD_LOCKS[int(upload_id[:8], 16) % len(UPLOAD_LOCKS)] if re.fullmatch(r'[0-9a-f]{32}', upload_id) else UPLOAD_LOCKS[0]
                with lock:
                    return self.handler.json(self.abort(upload_id))
        raise PdfServiceError('接口不存在', 404)

    def context(self, file_id):
        self._cleanup_expired()
        with transaction() as conn:
            file = self._file(conn, file_id)
            ensure(self.handler.fs_rate(conn, 'pdf-context:' + self.user_id, 12, 60),
                   'PDF 编辑请求过于频繁，请稍后重试', 429)
            self._baseline(conn, file)
            revision = self._revision(conn, file)
            file = dict(file)
        oss = self.handler.fs_oss(file)
        self._inspect(oss, file['object_key'], file['size'], file['sha256'])
        with transaction() as conn:
            current = self._file(conn, file_id)
            ensure(self._revision(conn, current) == revision,
                   'PDF 版本已变化，请重新打开', 409)
        return dict(url=oss.access_url(file['object_key'], file['filename'], 'application/pdf'),
                    revision=revision, filename=file['filename'], size=file['size'],
                    max_bytes=MAX_PDF_BYTES, max_pages=MAX_PDF_PAGES)

    def start(self, file_id, data):
        self._cleanup_expired()
        size, digest, revision = data.get('size'), data.get('sha256'), data.get('revision')
        ensure(type(size) is int and 0 < size <= MAX_PDF_BYTES, '仅支持 20 MB 以内的 PDF', 413)
        ensure(isinstance(digest, str) and re.fullmatch(r'[0-9a-f]{64}', digest), 'SHA256 校验值不正确')
        ensure(isinstance(revision, str) and re.fullmatch(r'[0-9a-f]{64}', revision), 'PDF 来源版本参数不正确')
        # The browser normally calls context first. Validate again here so a
        # direct API client cannot bypass signed/encrypted/complex PDF refusal.
        with transaction() as conn:
            source = self._file(conn, file_id)
            self._baseline(conn, source)
            ensure(self._revision(conn, source) == revision, 'PDF 版本已变化，请重新打开', 409)
            source = dict(source)
        self._inspect(self.handler.fs_oss(source), source['object_key'], source['size'], source['sha256'])
        upload_id = uuid.uuid4().hex
        key = 'share/pdf-versions/{}/{}/{}.pdf'.format(self.user_id, file_id, upload_id)
        with transaction() as conn:
            file = self._file(conn, file_id)
            self._baseline(conn, file)
            ensure(self._revision(conn, file) == revision, 'PDF 版本已变化，请重新打开', 409)
            active = conn.execute("SELECT 1 FROM share_pdf_uploads WHERE file_id=? "
                                  "AND status IN ('PREPARING','UPLOADING','COMPLETING')", (file_id,)).fetchone()
            ensure(not active, '该 PDF 已有未完成的保存任务，请先完成或取消', 409)
            count = conn.execute("SELECT COUNT(*) FROM share_pdf_uploads WHERE user_id=? "
                                 "AND status IN ('PREPARING','UPLOADING','COMPLETING')", (self.user_id,)).fetchone()[0]
            ensure(count < 10, '未完成的 PDF 保存任务过多，请先清理', 429)
            stamp = now()
            conn.execute('INSERT INTO share_pdf_uploads '
                         '(id,file_id,user_id,object_key,size,sha256,base_revision,source_key,status,expires_at,created_at,updated_at) '
                         'VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                         (upload_id, file_id, self.user_id, key, size, digest, revision,
                          file['object_key'], 'PREPARING', stamp + UPLOAD_SECONDS, stamp, stamp))
            file = dict(file)
        try:
            oss = self.handler.fs_oss(file)
            multipart_id = oss.begin(key, 'application/pdf')
            ensure(multipart_id, 'OSS 未返回上传标识', 502)
            with transaction() as conn:
                current = self._file(conn, file_id)
                ensure(self._revision(conn, current) == revision,
                       'PDF 版本已变化，请重新打开', 409)
                changed = conn.execute("UPDATE share_pdf_uploads SET upload_id=?,status='UPLOADING',updated_at=? "
                                       "WHERE id=? AND status='PREPARING' AND expires_at>?",
                                       (multipart_id, now(), upload_id, now())).rowcount
                ensure(changed == 1, 'PDF 保存任务已失效，请重新打开', 409)
                self.handler.fs_audit(conn, self.user_id, 'BEGIN_PDF_VERSION_UPLOAD', file_id)
        except Exception:
            self._discard(dict(id=upload_id, file_id=file_id,
                               object_key=key, upload_id=locals().get('multipart_id')))
            raise
        return dict(id=upload_id, part_size=PART_SIZE, part_count=math.ceil(size / PART_SIZE))

    def part(self, upload_id, data):
        with transaction() as conn:
            upload = self._upload(conn, upload_id)
            ensure(upload['status'] == 'UPLOADING' and upload['expires_at'] > now(),
                   'PDF 上传任务已失效', 409)
            file = self._file(conn, upload['file_id'])
            ensure(upload['source_key'] == file['object_key']
                   and upload['base_revision'] == self._revision(conn, file),
                   'PDF 版本已变化，请重新打开', 409)
            part_number = data.get('part_number')
            ensure(type(part_number) is int and 1 <= part_number <= math.ceil(upload['size'] / PART_SIZE),
                   '分片序号不正确')
            md5 = data.get('content_md5')
            ensure(isinstance(md5, str) and re.fullmatch(r'[A-Za-z0-9+/]{22}==', md5),
                   '分片校验值不正确')
        headers = {'Content-Type': 'application/octet-stream', 'Content-MD5': md5}
        oss = self.handler.fs_oss(file)
        return {'url': oss.signed('PUT', upload['object_key'],
                                  {'uploadId': upload['upload_id'], 'partNumber': part_number},
                                  headers, ttl=600), 'headers': headers}

    def complete(self, upload_id, data):
        with transaction() as conn:
            upload = self._upload(conn, upload_id)
            if upload['status'] == 'SAVED':
                version = conn.execute('SELECT * FROM share_office_versions WHERE id=? AND file_id=?',
                                       (upload['version_id'], upload['file_id'])).fetchone()
                ensure(version, '已保存版本不存在，请刷新列表', 409)
                file = self._file(conn, upload['file_id'])
                return dict(version=version_view(version, file), revision=self._revision(conn, file))
            ensure(upload['status'] == 'UPLOADING' or
                   (upload['status'] == 'COMPLETING' and upload['lease_until'] <= now()),
                   'PDF 上传任务不可用，请稍后重试', 409)
            ensure(upload['expires_at'] > now() and upload['upload_id'],
                   'PDF 上传任务已过期', 409)
            parts = data.get('parts')
            expected_parts = math.ceil(upload['size'] / PART_SIZE)
            ensure(isinstance(parts, list) and len(parts) == expected_parts, '上传分片不完整')
            verified = []
            for index, part in enumerate(parts, 1):
                ensure(isinstance(part, dict) and type(part.get('part_number')) is int
                       and part['part_number'] == index
                       and re.fullmatch(r'"?[a-fA-F0-9]{32}"?', str(part.get('etag', ''))),
                       '分片校验不正确')
                verified.append((index, part['etag']))
            conn.execute("UPDATE share_pdf_uploads SET status='COMPLETING',lease_until=?,updated_at=? WHERE id=?",
                         (now() + 120, now(), upload_id))
            file = self._file(conn, upload['file_id'])
            upload = dict(upload)
            file = dict(file)
        try:
            oss = self.handler.fs_oss(file)
            try:
                size, etag = object_metadata(oss, upload['object_key'])
            except HTTPError as exc:
                if exc.code != 404:
                    raise
                oss.complete(upload['object_key'], upload['upload_id'], verified)
                size, etag = object_metadata(oss, upload['object_key'])
            ensure(size == upload['size'], 'OSS PDF 文件大小校验失败', 409)
            pages = self._inspect(oss, upload['object_key'], upload['size'], upload['sha256'])
            stamp = now()
            with transaction() as conn:
                active = self._upload(conn, upload_id)
                ensure(active['status'] == 'COMPLETING' and active['expires_at'] > stamp,
                       'PDF 上传任务已失效', 409)
                current = self._file(conn, upload['file_id'])
                ensure(current['object_key'] == upload['source_key']
                       and self._revision(conn, current) == upload['base_revision'],
                       'PDF 版本已变化，请重新打开', 409)
                number = conn.execute('SELECT COALESCE(MAX(version_no),0)+1 FROM share_office_versions WHERE file_id=?',
                                      (upload['file_id'],)).fetchone()[0]
                version_id = uuid.uuid4().hex
                conn.execute('INSERT INTO share_office_versions '
                             '(id,file_id,version_no,object_key,size,sha256,etag,source_session_id,created_by,created_at) '
                             'VALUES(?,?,?,?,?,?,?,?,?,?)',
                             (version_id, upload['file_id'], number, upload['object_key'], size,
                              upload['sha256'], etag, upload_id, self.user_id, stamp))
                conn.execute("UPDATE share_pdf_uploads SET status='SAVED',version_id=?,upload_id=NULL,"
                             "lease_until=0,updated_at=? WHERE id=?", (version_id, stamp, upload_id))
                self.handler.fs_audit(conn, self.user_id, 'SAVE_PDF_VERSION', version_id)
                revision = self._revision(conn, current)
            return dict(version=dict(id=version_id, number=number, size=size, pages=pages,
                                     created_at=stamp, published=False), revision=revision)
        except PdfServiceError as exc:
            if exc.status in (409, 413, 415, 422):
                self._discard(upload)
            else:
                self._retry(upload_id)
            raise
        except StorageSecurityError:
            self._discard(upload)
            raise
        except Exception:
            self._retry(upload_id)
            raise

    def _retry(self, upload_id):
        with transaction() as conn:
            conn.execute("UPDATE share_pdf_uploads SET status='UPLOADING',lease_until=0,updated_at=? "
                         "WHERE id=? AND status='COMPLETING'", (now(), upload_id))

    def abort(self, upload_id):
        with transaction() as conn:
            upload = self._upload(conn, upload_id)
            if upload['status'] in ('SAVED', 'ABORTED'):
                return {'ok': True}
            ensure(upload['status'] != 'COMPLETING' or upload['lease_until'] <= now(),
                   'PDF 正在校验，请稍后再取消', 409)
            conn.execute("UPDATE share_pdf_uploads SET status='CLEANUP',updated_at=? WHERE id=?",
                         (now(), upload_id))
        self._cleanup_one(upload)
        return {'ok': True}

    def versions(self, file_id):
        with transaction() as conn:
            file = self._file(conn, file_id)
            rows = conn.execute('SELECT * FROM share_office_versions WHERE file_id=? '
                                'ORDER BY version_no DESC LIMIT 100', (file_id,)).fetchall()
            return {'items': [version_view(row, file) for row in rows]}

    def publish(self, file_id, data):
        version_id = data.get('version_id')
        ensure(isinstance(version_id, str) and re.fullmatch(r'[0-9a-f]{32}', version_id),
               '版本参数不正确')
        with transaction() as conn:
            file = self._file(conn, file_id)
            version = conn.execute('SELECT * FROM share_office_versions WHERE id=? AND file_id=?',
                                   (version_id, file_id)).fetchone()
            ensure(version, '版本不存在', 404)
            ensure(version['object_key'] != file['object_key'], '该版本已是当前发布版本', 409)
            busy = conn.execute("SELECT 1 FROM share_pdf_uploads WHERE file_id=? "
                                "AND status IN ('PREPARING','UPLOADING','COMPLETING') AND expires_at>?",
                                (file_id, now())).fetchone()
            ensure(not busy, '该 PDF 正在保存，请稍后发布', 409)
            file, version = dict(file), dict(version)
        oss = self.handler.fs_oss(file)
        size, etag = object_metadata(oss, version['object_key'])
        ensure(size == version['size'] and (not version['etag'] or etag == version['etag']),
               '版本文件已变化，发布已停止', 409)
        self._inspect(oss, version['object_key'], version['size'], version['sha256'])
        with transaction() as conn:
            current = self._file(conn, file_id)
            ensure(current['object_key'] == file['object_key'],
                   '文件已有新发布版本，请刷新版本记录后重试', 409)
            busy = conn.execute("SELECT 1 FROM share_pdf_uploads WHERE file_id=? "
                                "AND status IN ('PREPARING','UPLOADING','COMPLETING') AND expires_at>?",
                                (file_id, now())).fetchone()
            ensure(not busy, '该 PDF 正在保存，请稍后发布', 409)
            conn.execute('UPDATE share_files SET object_key=?,size=?,sha256=?,updated_at=? WHERE id=?',
                         (version['object_key'], version['size'], version['sha256'], now(), file_id))
            conn.execute('UPDATE share_office_versions SET published_at=COALESCE(published_at,?) WHERE id=?',
                         (now(), version_id))
            self.handler.fs_audit(conn, self.user_id, 'PUBLISH_PDF_VERSION', version_id)
            current = self._file(conn, file_id)
            revision = self._revision(conn, current)
        return dict(ok=True, version=version_view(version, current), revision=revision)
