"""Admin-only WebOffice sessions and immutable business versions for 槑槑云."""
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import time
import uuid
from urllib.error import HTTPError

from infrastructure.storage import shared_storage_config
from .database import transaction


MAX_EDIT_BYTES = 20 * 1024 * 1024
EDIT_FORMATS = ('docx', 'xlsx')


class OfficeServiceError(Exception):
    def __init__(self, message, status=400):
        self.message = message
        self.status = status


def ensure(condition, message, status=400):
    if not condition:
        raise OfficeServiceError(message, status)


def now():
    return int(time.time())


def token_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def expiry_epoch(value):
    try:
        parsed = datetime.fromisoformat(re.sub(r'(\.\d{6})\d+(?=(?:Z|[+-]\d{2}:\d{2})$)', r'\1', value).replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('timezone missing')
        result = int(parsed.timestamp())
    except (AttributeError, TypeError, ValueError) as exc:
        raise OfficeServiceError('文档编辑凭证的有效期异常', 502) from exc
    ensure(result > now() + 30, '文档编辑凭证已过期，请重试', 502)
    return result


def object_metadata(oss, key):
    head = {name.lower(): value for name, value in oss.head(key).items()}
    try:
        size = int(head['content-length'])
        etag = head['etag'].strip('"')
    except (KeyError, TypeError, ValueError) as exc:
        raise OfficeServiceError('OSS 未返回完整文件信息', 502) from exc
    ensure(size >= 0 and bool(re.fullmatch(r'[A-Za-z0-9-]+', etag)), 'OSS 文件信息不完整', 502)
    return size, etag


class OfficeService:
    def __init__(self, handler, user_id):
        self.handler = handler
        self.user_id = user_id

    def _admin(self):
        user = self.handler.current_user()
        ensure(user and user['id'] == self.user_id and user['role'] == 'admin', '仅管理员可以使用在线编辑', 403)
        return user

    def _settings(self):
        store = shared_storage_config(self.handler.server.secrets)
        project = os.environ.get('IMM_PROJECT_NAME', '').strip()
        region = os.environ.get('IMM_REGION', '').strip()
        switched_on = os.environ.get('IMM_OFFICE_ENABLED', '').strip().lower() in ('1', 'true', 'yes')
        enabled = bool(switched_on and project and region and store['configured'] and store.get('region') == region)
        return dict(enabled=enabled, project=project, region=region, store=store,
                    max_bytes=MAX_EDIT_BYTES, formats=list(EDIT_FORMATS))

    def _client(self, settings):
        from .imm_office import IMMWebOffice
        return IMMWebOffice(settings['store'], settings['project'], settings['region'])

    def _enabled(self):
        settings = self._settings()
        ensure(settings['enabled'], '在线编辑尚未配置完成，请检查 IMM 项目、地域和功能开关', 503)
        return settings

    def _owned_file(self, conn, file_id):
        row = self.handler.fs_owned_file(conn, file_id, self.user_id)
        ensure(row['status'] == 'READY', '文件当前不可编辑', 409)
        return row

    def _editable_file(self, conn, file_id):
        row = self._owned_file(conn, file_id)
        ext = Path(row['original_filename']).suffix.lower().lstrip('.')
        ensure(ext in EDIT_FORMATS, '试用阶段仅支持 DOCX 和 XLSX', 415)
        ensure(0 < row['size'] <= MAX_EDIT_BYTES, '试用阶段仅支持 20 MB 以内的文件', 413)
        return row, ext

    def _session(self, session_id, live=True):
        with transaction() as conn:
            session = conn.execute('SELECT * FROM share_office_sessions WHERE id=? AND user_id=?',
                                   (session_id, self.user_id)).fetchone()
            ensure(session, '编辑会话不存在', 404)
            file = self._owned_file(conn, session['file_id'])
            if live:
                ensure(session['status'] == 'ACTIVE' and session['expires_at'] > now(), '编辑会话已结束，请重新打开文件', 409)
            return dict(session), dict(file)

    def dispatch(self, path, data):
        self._admin()
        parts = path.strip('/').split('/')
        method = self.handler.command
        if method == 'GET' and parts == ['config']:
            settings = self._settings()
            return self.handler.json({key: settings[key] for key in ('enabled', 'max_bytes', 'formats')})
        if len(parts) == 3 and parts[0] == 'files' and parts[2] == 'versions' and method == 'GET':
            return self.handler.json(self.versions(parts[1]))
        if len(parts) == 3 and parts[0] == 'files' and parts[2] == 'start' and method == 'POST':
            return self.handler.json(self.start(parts[1]))
        if len(parts) == 3 and parts[0] == 'files' and parts[2] == 'publish' and method == 'POST':
            return self.handler.json(self.publish(parts[1], data))
        if len(parts) == 3 and parts[0] == 'sessions' and method == 'POST':
            if parts[2] == 'refresh':
                return self.handler.json(self.refresh(parts[1], data))
            if parts[2] == 'snapshot':
                return self.handler.json(self.snapshot(parts[1]))
            if parts[2] == 'close':
                return self.handler.json(self.close(parts[1]))
        raise OfficeServiceError('接口不存在', 404)

    def versions(self, file_id):
        with transaction() as conn:
            file = self._owned_file(conn, file_id)
            rows = conn.execute('SELECT id, version_no, object_key, size, created_at FROM share_office_versions '
                                'WHERE file_id=? ORDER BY version_no DESC LIMIT 100', (file_id,)).fetchall()
            items = [dict(id=row['id'], number=row['version_no'], size=row['size'],
                          created_at=row['created_at'], published=row['object_key'] == file['object_key'])
                     for row in rows]
        return {'items': items}

    def start(self, file_id):
        settings = self._enabled()
        session_id = uuid.uuid4().hex
        draft_key = None
        recovery_key = None
        recovery_marker = None
        stamp = now()
        with transaction() as conn:
            file, ext = self._editable_file(conn, file_id)
            conn.execute("UPDATE share_office_sessions SET status='EXPIRED',updated_at=? "
                         "WHERE file_id=? AND ((status='PREPARING' AND expires_at<=?) "
                         "OR (status='ACTIVE' AND refresh_expires_at<=?))",
                         (stamp, file_id, stamp, stamp))
            busy = conn.execute("SELECT 1 FROM share_office_sessions WHERE file_id=? "
                                "AND status IN ('PREPARING','ACTIVE')", (file_id,)).fetchone()
            ensure(not busy, '该文件已有编辑会话，请先关闭原页面或等待凭证过期', 409)
            previous = conn.execute("SELECT draft_key,source_key,recoverable,draft_etag_at_publish "
                                    "FROM share_office_sessions WHERE file_id=? AND status IN ('EXPIRED','CLOSED') "
                                    "ORDER BY created_at DESC,rowid DESC LIMIT 1", (file_id,)).fetchone()
            if previous and previous['source_key'] == file['object_key']:
                if previous['recoverable'] or previous['draft_etag_at_publish']:
                    recovery_key = previous['draft_key']
                    recovery_marker = None if previous['recoverable'] else previous['draft_etag_at_publish']
            baseline = conn.execute('SELECT 1 FROM share_office_versions WHERE file_id=? LIMIT 1', (file_id,)).fetchone()
            if not baseline:
                conn.execute('INSERT INTO share_office_versions '
                             '(id,file_id,version_no,object_key,size,sha256,created_by,published_at,created_at) '
                             'VALUES(?,?,?,?,?,?,?,?,?)',
                             (uuid.uuid4().hex, file_id, 1, file['object_key'], file['size'], file['sha256'],
                              self.user_id, stamp, stamp))
            draft_key = f'share/office-drafts/{self.user_id}/{session_id}.{ext}'
            conn.execute('INSERT INTO share_office_sessions '
                         '(id,file_id,user_id,draft_key,source_key,status,expires_at,refresh_expires_at,created_at,updated_at) '
                         'VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (session_id, file_id, self.user_id, draft_key, file['object_key'],
                          'PREPARING', stamp + 300, stamp + 300, stamp, stamp))
        oss = None
        copied = False
        recovered = False
        recovery_lost = False
        try:
            oss = self.handler.fs_oss(file)
            source_key = file['object_key']
            if recovery_key:
                try:
                    candidate_size, candidate_etag = object_metadata(oss, recovery_key)
                    if recovery_marker is None or candidate_etag != recovery_marker:
                        source_key = recovery_key
                        source_size, source_etag = candidate_size, candidate_etag
                        recovered = True
                except HTTPError as exc:
                    if exc.code != 404:
                        raise
                    recovery_lost = recovery_marker is None
            if not recovered:
                source_size, source_etag = object_metadata(oss, source_key)
            if recovered:
                ensure(0 < source_size <= MAX_EDIT_BYTES, '上次编辑草稿超出 20 MB 限制', 413)
            else:
                ensure(source_size == file['size'], '文件大小与记录不一致，请先核对原文件', 409)
            oss.copy_object(source_key, draft_key, source_etag)
            copied = True
            draft_size, _ = object_metadata(oss, draft_key)
            ensure(draft_size == source_size, '草稿复制校验失败', 502)
            oss.verify_private(draft_key)
            user = dict(self._admin())
            token = self._client(settings).generate(draft_key, file['filename'], self.user_id,
                                                    user.get('display_name') or user.get('username') or '槑槑云用户')
            expires_at = expiry_epoch(token['access_expires_at'])
            refresh_expires_at = expiry_epoch(token['refresh_expires_at'])
            with transaction() as conn:
                current = self._owned_file(conn, file_id)
                ensure(current['object_key'] == file['object_key'], '源文件已更新，请重新打开', 409)
                changed = conn.execute("UPDATE share_office_sessions SET status='ACTIVE',source_etag=?,"
                                       'access_token_hash=?,refresh_token_hash=?,expires_at=?,refresh_expires_at=?,updated_at=? '
                                       "WHERE id=? AND status='PREPARING'",
                                       (source_etag, token_hash(token['access_token']), token_hash(token['refresh_token']),
                                        expires_at, refresh_expires_at, now(), session_id)).rowcount
                ensure(changed == 1, '编辑会话已失效，请重试', 409)
                if not recovered:
                    conn.execute('UPDATE share_office_versions SET etag=? WHERE file_id=? AND object_key=? AND etag IS NULL',
                                 (source_etag, file_id, file['object_key']))
                self.handler.fs_audit(conn, self.user_id, 'START_OFFICE_EDIT', file_id)
            return {'session_id': session_id, 'recovered': recovered, 'recovery_lost': recovery_lost, **token}
        except Exception:
            with transaction() as conn:
                conn.execute("UPDATE share_office_sessions SET status='FAILED',updated_at=? "
                             "WHERE id=? AND status='PREPARING'", (now(), session_id))
            if copied and oss is not None:
                try:
                    oss.delete(draft_key)
                except Exception:
                    pass
            raise

    def refresh(self, session_id, data):
        settings = self._enabled()
        session, _ = self._session(session_id, live=False)
        ensure(session['status'] == 'ACTIVE' and session['refresh_expires_at'] > now(),
               '编辑会话已结束，请重新打开文件', 409)
        access_token = data.get('access_token')
        refresh_token = data.get('refresh_token')
        ensure(isinstance(access_token, str) and isinstance(refresh_token, str)
               and access_token and refresh_token, '编辑凭证缺失', 400)
        old_access_hash, old_refresh_hash = token_hash(access_token), token_hash(refresh_token)
        ensure(old_access_hash == session['access_token_hash'] and old_refresh_hash == session['refresh_token_hash'],
               '编辑凭证已更新，请刷新页面', 409)
        token = self._client(settings).refresh(access_token, refresh_token)
        expires_at = expiry_epoch(token['access_expires_at'])
        refresh_expires_at = expiry_epoch(token['refresh_expires_at'])
        with transaction() as conn:
            changed = conn.execute('UPDATE share_office_sessions SET access_token_hash=?,refresh_token_hash=?,expires_at=?,refresh_expires_at=?,updated_at=? '
                                   "WHERE id=? AND user_id=? AND status='ACTIVE' AND refresh_expires_at>? AND access_token_hash=? AND refresh_token_hash=?",
                                   (token_hash(token['access_token']), token_hash(token['refresh_token']),
                                    expires_at, refresh_expires_at, now(), session_id, self.user_id, now(), old_access_hash, old_refresh_hash)).rowcount
            ensure(changed == 1, '编辑会话已变更，请重新打开文件', 409)
        return token

    def snapshot(self, session_id):
        self._enabled()
        session, file = self._session(session_id)
        oss = self.handler.fs_oss(file)
        try:
            size, etag = object_metadata(oss, session['draft_key'])
        except HTTPError as exc:
            if exc.code == 404:
                raise OfficeServiceError('草稿文件不存在，请重新打开编辑器', 409) from exc
            raise
        ensure(0 < size <= MAX_EDIT_BYTES, '编辑后的文件超出 20 MB 试用限制', 413)
        if session['last_snapshot_etag'] == etag:
            with transaction() as conn:
                existing = conn.execute('SELECT id,version_no,object_key,size,created_at FROM share_office_versions '
                                        'WHERE source_session_id=? ORDER BY version_no DESC LIMIT 1',
                                        (session_id,)).fetchone()
                if existing:
                    return {'version': dict(id=existing['id'], number=existing['version_no'],
                                            size=existing['size'], created_at=existing['created_at'],
                                            published=existing['object_key'] == file['object_key'])}
        ext = Path(file['original_filename']).suffix.lower()
        version_id = uuid.uuid4().hex
        version_key = f'share/office-versions/{self.user_id}/{file["id"]}/{version_id}{ext}'
        copied = False
        try:
            try:
                oss.copy_object(session['draft_key'], version_key, etag)
            except HTTPError as exc:
                if exc.code == 412:
                    raise OfficeServiceError('草稿仍在同步，请稍后再保存版本', 409) from exc
                raise
            copied = True
            version_size, version_etag = object_metadata(oss, version_key)
            ensure(version_size == size, '版本文件大小校验失败', 502)
            oss.verify_private(version_key)
            digest, count = oss.sha256(version_key)
            ensure(count == size, '版本文件校验失败，请重试', 502)
            with transaction() as conn:
                active = conn.execute('SELECT status,expires_at FROM share_office_sessions WHERE id=? AND user_id=?',
                                      (session_id, self.user_id)).fetchone()
                current = self._owned_file(conn, file['id'])
                ensure(active and active['status'] == 'ACTIVE' and active['expires_at'] > now(),
                       '编辑会话已结束，请重新打开文件', 409)
                number = conn.execute('SELECT COALESCE(MAX(version_no),0)+1 FROM share_office_versions WHERE file_id=?',
                                      (file['id'],)).fetchone()[0]
                conn.execute('INSERT INTO share_office_versions '
                             '(id,file_id,version_no,object_key,size,sha256,etag,source_session_id,created_by,created_at) '
                             'VALUES(?,?,?,?,?,?,?,?,?,?)',
                             (version_id, current['id'], number, version_key, size, digest,
                              version_etag, session_id, self.user_id, now()))
                conn.execute('UPDATE share_office_sessions SET last_snapshot_etag=?,updated_at=? WHERE id=?',
                             (etag, now(), session_id))
                self.handler.fs_audit(conn, self.user_id, 'SAVE_OFFICE_VERSION', version_id)
            return {'version': dict(id=version_id, number=number, size=size, created_at=now(), published=False)}
        except Exception:
            if copied:
                try:
                    oss.delete(version_key)
                except Exception:
                    pass
            raise

    def publish(self, file_id, data):
        self._admin()
        version_id = data.get('version_id')
        ensure(isinstance(version_id, str) and re.fullmatch(r'[a-f0-9]{32}', version_id), '版本参数不正确')
        with transaction() as conn:
            file = self._owned_file(conn, file_id)
            version = conn.execute('SELECT * FROM share_office_versions WHERE id=? AND file_id=?',
                                   (version_id, file_id)).fetchone()
            ensure(version, '版本不存在', 404)
            version = dict(version)
            ensure(version['object_key'] != file['object_key'], '该版本已是当前发布版本', 409)
            preparing = conn.execute("SELECT 1 FROM share_office_sessions WHERE file_id=? "
                                     "AND status='PREPARING' AND expires_at>?", (file_id, now())).fetchone()
            ensure(not preparing, '文件正在准备编辑，请稍后再发布版本', 409)
            editing_before = conn.execute("SELECT id,draft_key FROM share_office_sessions WHERE file_id=? "
                                          "AND status='ACTIVE' AND refresh_expires_at>?", (file_id, now())).fetchone()
            ensure(not editing_before or version['source_session_id'] == editing_before['id'],
                   '文件正在编辑，请关闭编辑器后再发布其他版本', 409)
        oss = self.handler.fs_oss(file)
        size, etag = object_metadata(oss, version['object_key'])
        ensure(size == version['size'] and (not version['etag'] or etag == version['etag']),
               '版本文件已变化，发布已停止', 409)
        oss.verify_private(version['object_key'])
        draft_etag = object_metadata(oss, editing_before['draft_key'])[1] if editing_before else None
        with transaction() as conn:
            current = self._owned_file(conn, file_id)
            ensure(current['object_key'] == file['object_key'], '文件已有新发布版本，请刷新版本记录后重试', 409)
            preparing = conn.execute("SELECT 1 FROM share_office_sessions WHERE file_id=? "
                                     "AND status='PREPARING' AND expires_at>?", (file_id, now())).fetchone()
            ensure(not preparing, '文件正在准备编辑，请稍后再发布版本', 409)
            editing = conn.execute("SELECT id,draft_key FROM share_office_sessions WHERE file_id=? "
                                   "AND status='ACTIVE' AND refresh_expires_at>?", (file_id, now())).fetchone()
            ensure((not editing and not editing_before) or
                   (editing and editing_before and editing['id'] == editing_before['id']
                    and editing['draft_key'] == editing_before['draft_key']),
                   '编辑会话已变化，请刷新后重试发布', 409)
            conn.execute('UPDATE share_files SET object_key=?,size=?,sha256=?,updated_at=? WHERE id=?',
                         (version['object_key'], version['size'], version['sha256'], now(), file_id))
            conn.execute('UPDATE share_office_versions SET published_at=COALESCE(published_at,?) WHERE id=?',
                         (now(), version_id))
            # A publication changes the next editing baseline. An active draft may
            # recover only if its content changes after this publication marker.
            conn.execute('UPDATE share_office_sessions SET recoverable=0,updated_at=? WHERE file_id=?',
                         (now(), file_id))
            conn.execute("UPDATE share_office_sessions SET status='SUPERSEDED' "
                         "WHERE file_id=? AND status IN ('CLOSED','EXPIRED')", (file_id,))
            if editing:
                conn.execute('UPDATE share_office_sessions SET source_key=?,draft_etag_at_publish=? WHERE id=?',
                             (version['object_key'], draft_etag, editing['id']))
            self.handler.fs_audit(conn, self.user_id, 'PUBLISH_OFFICE_VERSION', version_id)
        return {'ok': True, 'version': dict(id=version_id, number=version['version_no'],
                                             size=version['size'], created_at=version['created_at'], published=True)}

    def close(self, session_id):
        with transaction() as conn:
            session = conn.execute('SELECT * FROM share_office_sessions WHERE id=? AND user_id=?',
                                   (session_id, self.user_id)).fetchone()
            ensure(session, '编辑会话不存在', 404)
            if session['status'] == 'ACTIVE':
                conn.execute("UPDATE share_office_sessions SET status='CLOSED',updated_at=? WHERE id=?", (now(), session_id))
                self.handler.fs_audit(conn, self.user_id, 'CLOSE_OFFICE_EDIT', session['file_id'])
        return {'ok': True}
